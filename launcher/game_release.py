"""Publish the game to the GitHub release that ASR.exe and the game's own updaters read.

The game's updaters read JSON manifests whose files are gzip streams split into parts,
named relative to the manifest; they check each result's size and SHA-256 but no
signature, so only ship files you have tested.

  latest.json   what the game's updater installs (WOW_ROGUE_UPDATE_URL): the update helper, ASR-Setup
                built from launcher/Setup.cs, which then brings in game.json's executable as ASR.exe and
                adds Play ASR to installations made before it existed
  game.json     the game executable, with the same version, read by ASR-Setup and the update helper
  patches.json  data patches the game keeps current itself (WOW_ROGUE_DATA_URL), including ASR's own
                patch-Z.MPQ (zone photos), patch-Y.MPQ (brighter zone lighting) and patch-X.MPQ (Durotar)
  base.json     the base data a fresh install needs, read only by ASR-Setup
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GITHUB_REPO = 'calinadrian/asr'
# Keep this tag stable: installed games read their update manifests from it.
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
    for manifest in manifests:  # one at a time, in the order given
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber', str(folder / manifest)], check=True)


def require_live_data(tag, folder):
    """Never ship a game whose zone-photo or Durotar assets are missing from the data feed."""
    from photo_archive import build_photos
    from durotar_assets import ARCHIVE
    expected = hashlib.sha256(build_photos(ROOT / 'launcher/zone-photos')).hexdigest()
    subprocess.run(['gh', 'release', 'download', tag, '--repo', GITHUB_REPO,
                    '--pattern', 'patches.json', '--dir', str(folder), '--clobber'], check=True)
    patches = json.loads((folder / 'patches.json').read_text(encoding='utf-8-sig')).get('patches', [])
    if not any(p.get('name') == 'patch-Z.MPQ' and p.get('sha256') == expected for p in patches):
        raise ValueError('Publish data first with asr publish-data DATA-FOLDER: the live data feed needs the matching zone-photo archive')
    if not any(p.get('name', '').lower() == ARCHIVE.lower() for p in patches):
        raise ValueError(f'Publish Durotar first with --durotar VANILLA-DATA --data DATA: the live data feed needs {ARCHIVE}')
    (folder / 'patches.json').unlink()


def build_setup(output):
    """Compile ASR-Setup (launcher/Setup.cs and Relay.cs) as asr setup does."""
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/optimize+', f'/out:{output}',
                    f'/win32icon:{ROOT / "launcher/asr.ico"}', '/reference:System.Windows.Forms.dll',
                    '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll',
                    '/reference:System.IO.Compression.dll', str(ROOT / 'launcher/Setup.cs'),
                    str(ROOT / 'launcher/Relay.cs'), str(ROOT / 'launcher/AddonStore.cs'),
                    str(ROOT / 'launcher/AddonManager.cs'), str(ROOT / 'launcher/GameUi.cs')], check=True)


def prepare(exe, version, notes, folder, build=None):
    """Write game.json, latest.json and their parts into folder."""
    import stamp_game
    # Windows shell resources are separate from the game's embedded runtime icon. Replacing them resizes
    # .rsrc and moves every later section, so it happens before our patches add sections that code refers to.
    iconed = folder / 'icon.exe'
    iconed.write_bytes(Path(exe).read_bytes())
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                    str(ROOT / 'launcher/set_game_icon.ps1'), '-Exe', str(iconed),
                    '-Ico', str(ROOT / 'launcher/asr.ico')], check=True)
    # The game reports this exact version, so its updater does not offer the same build again.
    stamped = folder / 'AzerothSurvivors.exe'
    stamp_game.stamp(iconed, stamped, version, build)
    iconed.unlink()
    entry = pack(stamped, f'game-{version}', folder)
    stamped.unlink()
    (folder / 'game.json').write_text(json.dumps(dict(version=version, notes=notes, **entry), indent=1))
    # The game's updater installs this in the game's place; it then brings in game.json's executable.
    helper = folder / 'update-helper.exe'
    build_setup(helper)
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    entry = pack(helper, f'update-{version}-{digest[:16]}', folder)
    helper.unlink()
    (folder / 'latest.json').write_text(json.dumps(dict(version=version, notes=notes, **entry), indent=1))


def publish(exe, version, notes, tag=GAME_TAG):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Use a numeric version such as 0.120.6')
    # The label shows this repository's commit, so it must be one GitHub has.
    if not subprocess.run(['git', 'branch', '-r', '--contains', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        raise ValueError('Push your commits first: the game shows the current commit in its version label')
    with tempfile.TemporaryDirectory(prefix='asr-game-') as scratch:
        folder = Path(scratch)
        require_live_data(tag, folder)
        prepare(exe, version, notes, folder)
        ensure_release(tag)
        # game.json before latest.json: the helper a game downloads must find the game it brings in.
        upload(tag, folder, ['game.json', 'latest.json'])
    describe(version, notes, tag)
    print(f'Published game {version} to https://github.com/{GITHUB_REPO}/releases/download/{tag}/latest.json')


def publish_zone_photos(tag=GAME_TAG):
    """Add the current zone photos without republishing unchanged game data."""
    from photo_archive import build_photos
    with tempfile.TemporaryDirectory(prefix='asr-zone-photos-') as scratch:
        folder = Path(scratch)
        subprocess.run(['gh', 'release', 'download', tag, '--repo', GITHUB_REPO,
                        '--pattern', 'patches.json', '--dir', str(folder)], check=True)
        path = folder / 'patches.json'
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(manifest.get('patches'), list) or not manifest['patches']:
            raise ValueError('Publish the base game data before adding zone photos')
        photos = folder / 'patch-Z.MPQ'
        photos.write_bytes(build_photos(ROOT / 'launcher/zone-photos'))
        digest = hashlib.sha256(photos.read_bytes()).hexdigest()
        entry = dict(name='patch-Z.MPQ', **pack(photos, f'data-patch-Z-{digest[:16]}', folder))
        manifest['patches'] = [p for p in manifest['patches'] if p.get('name', '').lower() != 'patch-z.mpq'] + [entry]
        path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
        upload(tag, folder, ['patches.json'])
    print(f'Published zone photos; existing game data retained on {tag}')


def publish_lighting(data, tag=GAME_TAG):
    """Add the brighter zone lighting, built from data's LightIntBand.dbc, without republishing other data."""
    from zone_light import ARCHIVE, build_lighting
    with tempfile.TemporaryDirectory(prefix='asr-zone-light-') as scratch:
        folder = Path(scratch)
        subprocess.run(['gh', 'release', 'download', tag, '--repo', GITHUB_REPO,
                        '--pattern', 'patches.json', '--dir', str(folder)], check=True)
        path = folder / 'patches.json'
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(manifest.get('patches'), list) or not manifest['patches']:
            raise ValueError('Publish the base game data before adding zone lighting')
        lighting = folder / ARCHIVE
        lighting.write_bytes(build_lighting(data))
        digest = hashlib.sha256(lighting.read_bytes()).hexdigest()
        entry = dict(name=ARCHIVE, **pack(lighting, f'data-{lighting.stem}-{digest[:16]}', folder))
        manifest['patches'] = [p for p in manifest['patches'] if p.get('name', '').lower() != ARCHIVE.lower()] + [entry]
        path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
        upload(tag, folder, ['patches.json'])
    print(f'Published zone lighting; existing game data retained on {tag}')


def publish_durotar(source, data, tag=GAME_TAG):
    """Add Durotar's archive, built from a vanilla 1.12.1 Data folder against data, without republishing other data."""
    from durotar_assets import ARCHIVE, prepare
    with tempfile.TemporaryDirectory(prefix='asr-durotar-') as scratch:
        folder = Path(scratch)
        subprocess.run(['gh', 'release', 'download', tag, '--repo', GITHUB_REPO,
                        '--pattern', 'patches.json', '--dir', str(folder)], check=True)
        path = folder / 'patches.json'
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(manifest.get('patches'), list) or not manifest['patches']:
            raise ValueError('Publish the base game data before adding Durotar')
        archive = folder / ARCHIVE
        archive.write_bytes(prepare(source, data)[0])
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        entry = dict(name=ARCHIVE, **pack(archive, f'data-{archive.stem}-{digest[:16]}', folder))
        manifest['patches'] = [p for p in manifest['patches'] if p.get('name', '').lower() != ARCHIVE.lower()] + [entry]
        path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
        upload(tag, folder, ['patches.json'])
    print(f'Published Durotar; existing game data retained on {tag}')


def pack_addons(folder):
    """Zip every addon in launcher/addon as <name>.zip, its folder at the root as Install AddOns expects."""
    zips = []
    for addon in sorted(p for p in (ROOT / 'launcher/addon').iterdir() if p.is_dir()):
        path = folder / f'{addon.name}.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(addon.rglob('*')):
                if file.is_file():
                    info = zipfile.ZipInfo(f'{addon.name}/{file.relative_to(addon).as_posix()}', (1980, 1, 1, 0, 0, 0))
                    archive.writestr(info, file.read_bytes(), zipfile.ZIP_DEFLATED)
        zips.append(path)
    return zips


def addons_manifest(zips):
    """addons.json: verified downloads and descriptions for the in-game addon manager."""
    addons = []
    for z in zips:
        entry = dict(name=z.stem, url=z.name, size=z.stat().st_size,
                     sha256=hashlib.sha256(z.read_bytes()).hexdigest())
        with zipfile.ZipFile(z) as archive:
            toc = archive.read(f'{z.stem}/{z.stem}.toc').decode('utf-8-sig')
        metadata = dict(re.findall(r'^##\s*(Title|Notes|Version):\s*(.*?)\s*$', toc, re.MULTILINE | re.IGNORECASE))
        for key, value in metadata.items():
            target = {'title': 'title', 'notes': 'description', 'version': 'version'}[key.lower()]
            entry[target] = value[:240 if target == 'description' else 120]
        addons.append(entry)
    return dict(addons=addons)


def prepare_addons(folder):
    """Keep old catalog downloads valid while new catalog metadata propagates."""
    zips = pack_addons(folder)
    manifest = addons_manifest(zips)
    published = []
    for archive, entry in zip(zips, manifest['addons']):
        immutable = archive.with_name(f"{entry['name']}-{entry['sha256'][:16]}.zip")
        archive.rename(immutable)
        entry['url'] = immutable.name
        published.append(immutable)
    return published, manifest


def publish_addons(tag=GAME_TAG):
    """Upload addon zips, then the catalog players browse from Options > AddOns."""
    with tempfile.TemporaryDirectory(prefix='asr-addons-') as scratch:
        folder = Path(scratch)
        zips, manifest = prepare_addons(folder)
        (folder / 'addons.json').write_text(json.dumps(manifest, indent=1))
        ensure_release(tag)
        # Zips first, the manifest last: nobody sees a manifest whose zips are missing.
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber'] + [str(z) for z in zips], check=True)
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', GITHUB_REPO, '--clobber', str(folder / 'addons.json')], check=True)
    for z in zips:
        print(f'Published https://github.com/{GITHUB_REPO}/releases/download/{tag}/{z.name}')


def publish_data(data, tag=GAME_TAG):
    data = Path(data)
    with tempfile.TemporaryDirectory(prefix='asr-game-') as scratch:
        folder = Path(scratch)
        patches, base = [], []
        from photo_archive import build_photos
        from zone_light import ARCHIVE, build_lighting
        photos = folder / 'patch-Z.MPQ'
        photos.write_bytes(build_photos(ROOT / 'launcher/zone-photos'))
        lighting = folder / ARCHIVE
        lighting.write_bytes(build_lighting(data))
        sources = [p for p in data.glob('*.MPQ') if p.name.lower() not in ('patch-z.mpq', ARCHIVE.lower())] + [photos, lighting]
        for source in sorted(sources, key=lambda p: p.name.lower()):
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
    parser.add_argument('--zone-photos', action='store_true', help='publish only the zone-photo data update')
    parser.add_argument('--data', help='a game Data folder to publish instead of an executable')
    parser.add_argument('--lighting', action='store_true', help='with --data, publish only the zone-lighting update built from it')
    parser.add_argument('--durotar', metavar='VANILLA-DATA', help="with --data, publish only Durotar's archive, built from a vanilla 1.12.1 Data folder")
    parser.add_argument('--addons', action='store_true', help="publish ASR's addons as zips on the release")
    parser.add_argument('--tag', default=GAME_TAG)
    parser.add_argument('--describe', action='store_true', help='only retitle the release and rewrite its notes for --version')
    args = parser.parse_args()
    if args.describe:
        describe(args.version, args.notes, args.tag)
    elif args.zone_photos:
        publish_zone_photos(args.tag)
    elif args.addons:
        publish_addons(args.tag)
    elif args.lighting and args.data:
        publish_lighting(args.data, args.tag)
    elif args.durotar and args.data:
        publish_durotar(args.durotar, args.data, args.tag)
    elif args.data:
        publish_data(args.data, args.tag)
    elif args.exe and args.version:
        publish(args.exe, args.version, args.notes, args.tag)
    else:
        parser.error('give --exe and --version, or --data')
