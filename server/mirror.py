"""Copy the newest signed launcher release from GitHub into this server's update channel.

Launchers up to 0.1.4 only read hassian.duckdns.org; mirroring keeps them updating
when releases are published from GitHub Actions.
"""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

GITHUB = 'https://github.com/calinadrian/asr/releases/'
ARCHIVE_EXE = 'WorldOfSurvive.exe'  # the launcher's name inside every release archive


def fetch(url, limit):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'ASR-server'}), timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds its size limit: ' + url)
    return data


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def sync(state):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    updates = state / 'updates'
    envelope = json.loads(fetch(GITHUB + 'latest/download/latest-envelope.json', 100000))
    raw, signature = base64.b64decode(envelope['manifest']), base64.b64decode(envelope['signature'])
    key = serialization.load_pem_private_key((state / 'release-signing-key.pem').read_bytes(), password=None)
    key.public_key().verify(signature, raw, padding.PKCS1v15(), hashes.SHA256())
    manifest = json.loads(raw)
    current = json.loads((updates / 'latest.json').read_bytes())['sequence'] if (updates / 'latest.json').exists() else 0
    if manifest['sequence'] <= current:
        return None
    blob = fetch(f"{GITHUB}download/v{manifest['version']}/{manifest['sha256']}.zip", manifest['size'])
    if len(blob) != manifest['size'] or hashlib.sha256(blob).hexdigest() != manifest['sha256']:
        raise ValueError('GitHub archive does not match its signed manifest')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        exe = archive.read(ARCHIVE_EXE)
    atomic(updates / manifest['archive'], blob)
    atomic(updates / 'ASR.exe', exe)
    atomic(updates / 'latest.json', raw)
    atomic(updates / 'latest.sig', signature)
    # The envelope is what launchers read, so it is written last.
    atomic(updates / 'latest-envelope.json', json.dumps(envelope, separators=(',', ':')).encode())
    return manifest['version']


def run(state, interval=600):
    while True:
        try:
            version = sync(state)
            if version:
                print(f'Mirrored launcher {version} from GitHub', flush=True)
        except Exception as error:  # a failed check keeps serving the current release
            print(f'GitHub mirror check failed: {error}', file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == '__main__':
    print(sync(Path(__file__).resolve().parents[1] / 'server/state') or 'Already current')
