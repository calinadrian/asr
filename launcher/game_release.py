"""Publish the game to the GitHub release that ASR.exe and the game's own updaters read.

The game's updaters read JSON manifests whose files are gzip streams split into parts,
named relative to the manifest; they check each result's size and SHA-256 but no
signature, so only ship files you have tested.

  latest.json   the executable (WOW_ROGUE_UPDATE_URL)
  patches.json  data patches the game keeps current itself (WOW_ROGUE_DATA_URL)
  base.json     the base data a fresh install needs, read only by ASR.exe
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
BASE_DATA = 'patch.MPQ'


def pack(source, prefix, folder):
    """Gzip source into PART_SIZE parts named <prefix>-part-NNN.bin; return its manifest entry."""
    digest, size = hashlib.sha256(), 0
    packed = folder / (prefix + '.gz')
    with source.open('rb') as data, gzip.GzipFile(packed, 'wb', compresslevel=9, mtime=0) as out:
        while chunk := data.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    parts = []
    with packed.open('rb') as stream:
        while chunk := stream.read(PART_SIZE):
            name = f'{prefix}-part-{len(parts):03}.bin'
            (folder / name).write_bytes(chunk)
            parts.append(dict(url=name, size=len(chunk)))
    packed.unlink()
    return dict(size=size, sha256=digest.hexdigest(), parts=parts)


def ensure_release(tag):
    if subprocess.run(['gh', 'release', 'view', tag, '--repo', GITHUB_REPO], capture_output=True).returncode:
        subprocess.run(['gh', 'release', 'create', tag, '--repo', GITHUB_REPO, '--prerelease', '--latest=false',
                        '--title', 'ASR game', '--notes', 'The game and its data, read by ASR.exe and the game itself.'], check=True)


def upload(tag, folder, manifests):
    """Parts first, manifests last: nobody sees a manifest whose parts are missing."""
    parts = sorted(str(p) for p in folder.glob('*.bin'))
    for start in range(0, len(parts), 20):
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + parts[start:start + 20], check=True)
    subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + [str(folder / m) for m in manifests], check=True)


def publish(exe, version, notes, tag=GAME_TAG):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric version such as 0.120.5')
    if version.encode() not in Path(exe).read_bytes():
        raise ValueError(f'{exe} does not report version {version}; the game would download it again on every start')
    with tempfile.TemporaryDirectory(prefix='asr-game-') as scratch:
        folder = Path(scratch)
        entry = pack(Path(exe), f'game-{version}', folder)
        (folder / 'latest.json').write_text(json.dumps(dict(version=version, notes=notes, **entry), indent=1))
        ensure_release(tag)
        upload(tag, folder, ['latest.json'])
    print(f'Published game {version} to https://github.com/{GITHUB_REPO}/releases/download/{tag}/latest.json')


def publish_data(data, tag=GAME_TAG):
    data = Path(data)
    with tempfile.TemporaryDirectory(prefix='asr-game-') as scratch:
        folder = Path(scratch)
        patches, base = [], []
        for source in sorted(data.glob('*.MPQ'), key=lambda p: p.name.lower()):
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()[:16]
            # Content-addressed part names: a changed file never overwrites parts a download is using.
            entry = dict(name=source.name, **pack(source, f'data-{source.stem}-{digest}', folder))
            (base if source.name == BASE_DATA else patches).append(entry)
            print(f'Packed {source.name}: {len(entry["parts"])} parts', flush=True)
        (folder / 'patches.json').write_text(json.dumps(dict(patches=patches), indent=1))
        (folder / 'base.json').write_text(json.dumps(dict(patches=base), indent=1))
        ensure_release(tag)
        upload(tag, folder, ['patches.json', 'base.json'])
    print(f'Published {len(patches) + len(base)} data files to https://github.com/{GITHUB_REPO}/releases/tag/{tag}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe')
    parser.add_argument('--version')
    parser.add_argument('--notes', default='')
    parser.add_argument('--data', help='a game Data folder to publish instead of an executable')
    parser.add_argument('--tag', default=GAME_TAG)
    args = parser.parse_args()
    if args.data:
        publish_data(args.data, args.tag)
    elif args.exe and args.version:
        publish(args.exe, args.version, args.notes, args.tag)
    else:
        parser.error('give --exe and --version, or --data')
