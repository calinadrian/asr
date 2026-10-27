"""GitHub Actions side of publishing: decide from launcher/version.json, then build, sign and release.

decide   sets the step output publish=true when version.json is above the latest release
publish  writes the signing key and server certificate from secrets, fetches the pinned
         co-op installer, then runs release.py --stage-only and --promote (which uploads)
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
import release  # noqa: E402

LATEST = f'https://github.com/{release.GITHUB_REPO}/releases/latest/download/latest-envelope.json'
INSTALLER = ('https://github.com/bymarvin/azeroth-survivors-together/releases/download/v0.0.30/'
             'Azeroth-Survivors-Together-Installer.exe')


def wanted():
    target = json.loads((ROOT / 'launcher/version.json').read_text())
    with urllib.request.urlopen(LATEST, timeout=60) as response:
        latest = json.loads(base64.b64decode(json.loads(response.read())['manifest']))
    newer = (tuple(map(int, target['version'].split('.'))) > tuple(map(int, latest['version'].split('.')))
             and target['sequence'] > latest['sequence'])
    print(f"version.json {target['version']} (sequence {target['sequence']}); "
          f"latest release {latest['version']} (sequence {latest['sequence']})")
    return target if newer else None


def decide():
    target = wanted()
    print('Publishing.' if target else 'Nothing to publish: raise both version and sequence in launcher/version.json.')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f"publish={'true' if target else 'false'}\n")


def publish():
    target = wanted()
    if not target:
        return
    release.STATE.mkdir(parents=True, exist_ok=True)
    (release.STATE / 'release-signing-key.pem').write_text(os.environ['RELEASE_SIGNING_KEY'])
    (release.STATE / 'server-cert.pem').write_text(os.environ['SERVER_CERT'])
    installer = ROOT / 'downloads/Azeroth-Survivors-Together-Installer.exe'
    installer.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(INSTALLER, timeout=120) as response:
        installer.write_bytes(response.read())  # release.py checks it against its pinned hash
    version, sequence = target['version'], str(target['sequence'])
    for mode in ('--stage-only', '--promote'):
        subprocess.run([sys.executable, str(ROOT / 'launcher/release.py'), '--version', version, '--sequence', sequence, mode], check=True)


if __name__ == '__main__':
    {'decide': decide, 'publish': publish}[sys.argv[1]]()
