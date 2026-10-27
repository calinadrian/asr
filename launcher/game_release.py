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
        subprocess.run(['gh', 'release', 'create', tag, '--repo', GITHUB_REPO, '--latest',
                        '--title', 'ASR', '--notes', 'ASR, the game and its data.'], check=True)


def describe(version, notes, tag=GAME_TAG):
    """Title the release after the version players get, with install instructions and what changed."""
    text = (ROOT / 'launcher/release-notes.md').read_text(encoding='utf-8')
    text = text.replace('{version}', version).replace('{notes}', notes or 'Improvements and fixes.')
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False, encoding='utf-8') as file:
        file.write(text)
    try:
        subprocess.run(['gh', 'release', 'edit', tag, '--repo', GITHUB_REPO, '--title', f'ASR {version}',
                        '--notes-file', file.name, '--prerelease=false', '--latest'], check=True)
    finally:
        Path(file.name).unlink()


def upload(tag, folder, manifests):
    """Parts first, manifests last: nobody sees a manifest whose parts are missing."""
    parts = sorted(str(p) for p in folder.glob('*.bin'))
    for start in range(0, len(parts), 20):
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + parts[start:start + 20], check=True)
    subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + [str(folder / m) for m in manifests], check=True)


def publish(exe, version, notes, tag=GAME_TAG):
    import stamp_game
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric version such as 0.120.6')
    # The label shows this repository's commit, so it must be one GitHub has.
    if not subprocess.run(['git', 'branch', '-r', '--contains', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        raise ValueError('Push your commits first: the game shows the current commit in its version label')
    with tempfile.TemporaryDirectory(prefix='asr-game-') as scratch:
        folder = Path(scratch)
        # The game reports this exact version, so its updater does not offer the same build again.
        stamped = folder / 'AzerothSurvivors.exe'
        stamp_game.stamp(exe, stamped, version)
        entry = pack(stamped, f'game-{version}', folder)
        stamped.unlink()
        (folder / 'latest.json').write_text(json.dumps(dict(version=version, notes=notes, **entry), indent=1))
        ensure_release(tag)
        upload(tag, folder, ['latest.json'])
    describe(version, notes, tag)
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
    parser.add_argument('--describe', action='store_true', help='only retitle the release and rewrite its notes for --version')
    args = parser.parse_args()
    if args.describe:
        describe(args.version, args.notes, args.tag)
    elif args.data:
        publish_data(args.data, args.tag)
    elif args.exe and args.version:
        publish(args.exe, args.version, args.notes, args.tag)
    else:
        parser.error('give --exe and --version, or --data')
