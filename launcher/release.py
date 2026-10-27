"""Build and publish a signed Windows launcher release on our local server."""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'server/state'
UPDATES = STATE / 'updates'
GITHUB_REPO = 'calinadrian/asr'
# Launchers up to 0.1.6 accept only this name for the launcher inside a release; newer ones install it as ASR.exe.
ARCHIVE_EXE = 'WorldOfSurvive.exe'


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def publish(version, sequence, output=None, stage_only=True):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric version such as 0.1.1')
    release_root = ROOT / 'downloads/launcher-candidate' if stage_only else UPDATES
    release_root.mkdir(parents=True, exist_ok=True)
    latest_path = release_root / 'latest.json'
    if (UPDATES / 'latest.json').exists():
        previous = json.loads((UPDATES / 'latest.json').read_bytes())
        if sequence <= previous['sequence']:
            raise ValueError('Use a release sequence greater than the published sequence')
        if tuple(map(int, version.split('.'))) <= tuple(map(int, previous['version'].split('.'))):
            raise ValueError('Use a version greater than the published version')
    key_path = STATE / 'release-signing-key.pem'
    if not key_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        atomic(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    public = key.public_key().public_numbers()
    encode = lambda n: base64.b64encode(n.to_bytes((n.bit_length() + 7) // 8, 'big')).decode()
    xml = '<RSAKeyValue><Modulus>' + encode(public.n) + '</Modulus><Exponent>' + encode(public.e) + '</Exponent></RSAKeyValue>'
    cert = x509.load_pem_x509_certificate((STATE / 'server-cert.pem').read_bytes())
    build_root = ROOT / 'downloads/launcher-build'
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build_root) as scratch:
        build = Path(scratch)
        (build / 'release-key.xml').write_text(xml)
        (build / 'server.cer').write_bytes(cert.public_bytes(serialization.Encoding.DER))
        installer = ROOT / 'downloads/Azeroth-Survivors-Together-Installer.exe'
        if not installer.is_file():
            raise ValueError('The verified upstream co-op installer must be present in downloads/')
        installer_sha = hashlib.sha256(installer.read_bytes()).hexdigest()
        # Match the exact upstream installer already reviewed and installed for this project.
        if installer_sha != 'ec9c410f907090f2d1c265faf182c109047f7b3226396153d5af35fee9b17b72':
            raise ValueError('Unexpected co-op installer; review the new upstream release before updating this pin')
        (build / 'BuildInfo.cs').write_text(
            f'[assembly: System.Reflection.AssemblyVersion("{version}.0")]\n'
            f'[assembly: System.Reflection.AssemblyFileVersion("{version}.0")]\n'
            '[assembly: System.Reflection.AssemblyTitle("ASR")]\n'
            'namespace ASR { internal static class BuildInfo {\n'
            f'public const string Version = "{version}"; public const long Sequence = {sequence}L;\n'
            'public const string InstallerUrl = "https://github.com/bymarvin/azeroth-survivors-together/releases/download/v0.0.30/Azeroth-Survivors-Together-Installer.exe";\n'
            f'public const string InstallerSha = "{installer_sha}";\n' + '} }\n')
        exe = build / 'ASR.exe'
        compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+', '/platform:anycpu',
            '/out:' + str(exe), '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
            '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
            '/reference:System.IO.Compression.FileSystem.dll',
            '/resource:' + str(build / 'release-key.xml') + ',release-key.xml',
            '/resource:' + str(build / 'server.cer') + ',server.cer',
            '/resource:' + str(STATE / 'server-cert.pem') + ',server-cert.pem',
            '/resource:' + str(ROOT / 'launcher/client/bootstrap.py') + ',client/bootstrap.py',
            '/resource:' + str(ROOT / 'launcher/client/settings.json') + ',client/settings.json',
            str(ROOT / 'launcher/ASR.cs'), str(build / 'BuildInfo.cs')], check=True)
        payload = {ARCHIVE_EXE: exe.read_bytes(), 'server-cert.pem': (STATE / 'server-cert.pem').read_bytes()}
        for path in sorted((ROOT / 'launcher/client').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                payload['client/' + path.relative_to(ROOT / 'launcher/client').as_posix()] = path.read_bytes()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
        blob = stream.getvalue()
        digest = hashlib.sha256(blob).hexdigest()
        manifest = dict(version=version, sequence=sequence, archive=f'releases/{digest}.zip',
            size=len(blob), sha256=digest, files=[dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                                              for name, data in payload.items()])
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        signature = key.sign(raw, padding.PKCS1v15(), hashes.SHA256())
        # A signed envelope gives the server one atomic publication point for manifest and signature.
        envelope = json.dumps(dict(manifest=base64.b64encode(raw).decode(),
                                   signature=base64.b64encode(signature).decode()), separators=(',', ':')).encode()
        atomic(release_root / f'releases/{digest}.zip', blob)
        atomic(release_root / 'ASR.exe', payload[ARCHIVE_EXE])
        atomic(release_root / f'manifests/{hashlib.sha256(raw).hexdigest()}.json', raw)
        atomic(release_root / f'manifests/{hashlib.sha256(raw).hexdigest()}.sig', signature)
        atomic(release_root / 'latest.sig', signature)
        atomic(latest_path, raw)
        atomic(release_root / 'latest-envelope.json', envelope)
        destination = Path(output) if output else release_root / 'ASR.exe'
        atomic(destination, payload[ARCHIVE_EXE])
        print(f'{"Staged" if stage_only else "Published"} {version} (sequence {sequence}): {destination}')


def promote(version, sequence):
    candidate = ROOT / 'downloads/launcher-candidate'
    raw = (candidate / 'latest.json').read_bytes()
    signature = (candidate / 'latest.sig').read_bytes()
    key = serialization.load_pem_private_key((STATE / 'release-signing-key.pem').read_bytes(), password=None)
    key.public_key().verify(signature, raw, padding.PKCS1v15(), hashes.SHA256())
    manifest = json.loads(raw)
    if manifest['version'] != version or manifest['sequence'] != sequence:
        raise ValueError('Candidate does not match the requested release')
    previous = json.loads((UPDATES / 'latest.json').read_bytes()) if (UPDATES / 'latest.json').exists() else {'sequence': 0}
    if sequence <= previous['sequence']:
        raise ValueError('A newer or identical release is already published')
    if not re.fullmatch(r'releases/[0-9a-f]{64}\.zip', manifest['archive']):
        raise ValueError('Invalid candidate archive path')
    blob = (candidate / manifest['archive']).read_bytes()
    if len(blob) != manifest['size'] or hashlib.sha256(blob).hexdigest() != manifest['sha256']:
        raise ValueError('Candidate archive changed')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        exe = archive.read(ARCHIVE_EXE)
    atomic(UPDATES / manifest['archive'], blob)
    atomic(UPDATES / 'ASR.exe', exe)
    atomic(UPDATES / 'latest.json', raw)
    atomic(UPDATES / 'latest.sig', signature)
    atomic(UPDATES / 'latest-envelope.json', json.dumps(dict(manifest=base64.b64encode(raw).decode(),
        signature=base64.b64encode(signature).decode()), separators=(',', ':')).encode())
    atomic(ROOT / 'downloads/ASR.exe', exe)
    print(f'Published tested candidate {version} (sequence {sequence})')
    upload(version, sequence)


def upload(version, sequence):
    """Attach the published release to GitHub, where launchers since 0.1.5 look for updates."""
    raw = (UPDATES / 'latest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest['version'] != version or manifest['sequence'] != sequence:
        raise ValueError('The published release does not match the requested release')
    # Launchers fetch releases/latest/download/latest-envelope.json, then download/v<version>/<sha256>.zip.
    assets = [UPDATES / 'latest-envelope.json', UPDATES / manifest['archive'], UPDATES / 'ASR.exe']
    result = subprocess.run(['gh', 'release', 'create', 'v' + version, '--repo', GITHUB_REPO, '--latest',
        '--title', f'ASR {version}', '--notes', f'Launcher update {version} (sequence {sequence}).'] + [str(a) for a in assets])
    if result.returncode:
        raise SystemExit(f'GitHub upload failed. The server channel is already updated; retry with:\n'
                         f'  asr upload {version} {sequence}')
    print(f'Uploaded {version} to https://github.com/{GITHUB_REPO}/releases')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', type=int, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--stage-only', action='store_true')
    mode.add_argument('--promote', action='store_true')
    mode.add_argument('--upload', action='store_true')
    args = parser.parse_args()
    if args.promote:
        promote(args.version, args.sequence)
    elif args.upload:
        upload(args.version, args.sequence)
    else:
        publish(args.version, args.sequence, stage_only=True)
