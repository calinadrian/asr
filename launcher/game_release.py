"""Publish a game executable to the GitHub release the game's own updater reads.

The game's updater (WOW_ROGUE_UPDATE_URL) fetches a JSON manifest, downloads the
listed parts relative to it, joins and gunzips them, and checks the result
against the manifest's size and SHA-256. It checks no signature, so only ship an
executable you have tested.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GITHUB_REPO = 'calinadrian/asr'
# One pre-release keeps the game files out of releases/latest, where launchers find their own updates.
GAME_TAG = 'game'
PART_SIZE = 20 * 1024 * 1024


def publish(exe, version, notes, tag=GAME_TAG):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric version such as 0.120.4')
    data = Path(exe).read_bytes()
    packed = gzip.compress(data, compresslevel=9, mtime=0)
    names, parts = [], []
    with tempfile.TemporaryDirectory(dir=ROOT / 'downloads') as scratch:
        folder = Path(scratch)
        for index in range(0, len(packed), PART_SIZE):
            name = f'game-{version}-part-{index // PART_SIZE:03}.bin'
            (folder / name).write_bytes(packed[index:index + PART_SIZE])
            names.append(name)
            parts.append(dict(url=name, size=len(packed[index:index + PART_SIZE])))
        manifest = dict(version=version, notes=notes, size=len(data), sha256=hashlib.sha256(data).hexdigest(), parts=parts)
        (folder / 'latest.json').write_text(json.dumps(manifest, indent=1))
        exists = subprocess.run(['gh', 'release', 'view', tag, '--repo', GITHUB_REPO], capture_output=True).returncode == 0
        if not exists:
            subprocess.run(['gh', 'release', 'create', tag, '--repo', GITHUB_REPO, '--prerelease', '--latest=false',
                            '--title', 'ASR game', '--notes', 'Game executable updates read by the game itself.'], check=True)
        # Parts first, manifest last: a game never sees a manifest whose parts are missing.
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + [str(folder / n) for n in names], check=True)
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber', str(folder / 'latest.json')], check=True)
    print(f'Published game {version} ({len(data)} bytes, {len(parts)} parts) to '
          f'https://github.com/{GITHUB_REPO}/releases/download/{tag}/latest.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--notes', default='')
    parser.add_argument('--tag', default=GAME_TAG)
    args = parser.parse_args()
    publish(args.exe, args.version, args.notes, args.tag)
