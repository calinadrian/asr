"""Build Durotar's terrain, creature and card archive (patch-X.MPQ) from a vanilla 1.12.1 Data folder.

Only assets absent from ASR are added. Existing shared models, DBCs, lighting and
textures are preserved. durotar_patch.py adds the zone itself to the native game.
"""
import argparse
import hashlib
import json
import mmap
import struct
from pathlib import Path

from photo_archive import MASK, build, read_stored, crypt, name_hash
from zone_light import extract

ARCHIVE = 'patch-X.MPQ'
DISPLAYS = (2486, 381, 1960, 1185, 1218, 1252, 2487, 4186, 1964,
            6088, 6814, 4194, 6113, 2491)


def chunks(data):
    at = 0
    while at < len(data):
        if at + 8 > len(data):
            raise ValueError('Truncated chunk header')
        tag, size = struct.unpack_from('<4sI', data, at)
        at += 8
        if at + size > len(data):
            raise ValueError('Truncated chunk payload')
        yield tag[::-1], data[at:at + size]
        at += size


def names(data):
    return [s.decode('ascii').replace('/', '\\') for s in data.split(b'\0') if s]


def canonical(name):
    name = name.replace('/', '\\').strip('\0')
    if name.lower().endswith(('.mdx', '.mdl')):
        name = name[:-4] + '.m2'
    if not name or ':' in name or '..' in name.split('\\'):
        raise ValueError(f'Invalid game asset name: {name!r}')
    return name


def dependencies(name, data):
    suffix = Path(name).suffix.lower()
    if suffix in ('.adt', '.wmo', '.wdt'):
        table = dict(chunks(data))
        for tag in (b'MTEX', b'MMDX', b'MWMO', b'MOTX', b'MODN', b'MOSB'):
            yield from names(table.get(tag, b''))
        if suffix == '.wmo' and b'MOHD' in table:
            count = struct.unpack_from('<I', table[b'MOHD'], 4)[0]
            if count > 4096:
                raise ValueError('Invalid WMO group count')
            for index in range(count):
                yield name[:-4] + f'_{index:03}.wmo'
    elif suffix == '.m2':
        if data[:8] != b'MD20\x00\x01\x00\x00':
            raise ValueError(f'Expected vanilla M2: {name}')
        count, offset = struct.unpack_from('<II', data, 0x5c)
        if offset + count * 16 > len(data):
            raise ValueError(f'Truncated M2 texture table: {name}')
        for index in range(count):
            kind, _, length, pos = struct.unpack_from('<IIII', data, offset + index * 16)
            if kind == 0 and length:
                if pos + length > len(data):
                    raise ValueError(f'Truncated M2 texture name: {name}')
                yield data[pos:pos + length].rstrip(b'\0').decode('ascii')


class Chain:
    def __init__(self, folder, exclude=()):
        paths = [p for p in Path(folder).glob('*.MPQ') if p.name.lower() not in {n.lower() for n in exclude}]
        if not paths:
            raise ValueError(f'No MPQ archives in {folder}')
        # Patch files take priority over base archives, later patches first.
        self.paths = sorted(paths, key=lambda p: (
            p.stem.lower().startswith('patch-'), p.stem.lower() == 'patch',
            p.stem.lower()), reverse=True)
        self.cache = {}
        self.archives = []
        for path in self.paths:
            if path.stem.lower() == 'backup':
                continue
            with path.open('rb') as file:
                archive = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
            try:
                start = archive.find(b'MPQ\x1a')
                if start < 0:
                    raise ValueError(f'Not an MPQ: {path}')
                _, _, _, _, shift, hp, bp, slots, count = struct.unpack_from('<4sIIHHIIII', archive, start)
                hashes = struct.unpack('<' + 'I' * slots * 4, crypt(
                    struct.unpack_from('<' + 'I' * slots * 4, archive, start + hp),
                    name_hash('(hash table)', 0x300), decrypt=True))
                blocks = struct.unpack('<' + 'I' * count * 4, crypt(
                    struct.unpack_from('<' + 'I' * count * 4, archive, start + bp),
                    name_hash('(block table)', 0x300), decrypt=True))
                self.archives.append((archive, start, 512 << shift, hashes, blocks, slots))
            except BaseException:
                archive.close()
                self.close()
                raise

    def close(self):
        for archive, *_ in self.archives:
            archive.close()
        self.archives.clear()

    def read(self, name):
        key = name.lower()
        if key not in self.cache:
            self.cache[key] = None
            a, b = name_hash(name, 0x100), name_hash(name, 0x200)
            for archive, start, sector, hashes, blocks, slots in self.archives:
                slot = name_hash(name, 0) & (slots - 1)
                for _ in range(slots):
                    first, second, _, index = hashes[slot * 4:slot * 4 + 4]
                    if index == MASK:
                        break
                    if (first, second) == (a, b) and index < len(blocks) // 4:
                        self.cache[key] = extract(archive, start, sector, *blocks[index * 4:index * 4 + 4])
                        break
                    slot = (slot + 1) & (slots - 1)
                if self.cache[key] is not None:
                    break
        return self.cache[key]


def dbc(data):
    magic, count, fields, size, strings = struct.unpack_from('<4sIIII', data)
    if magic != b'WDBC' or size != fields * 4 or len(data) != 20 + count * size + strings:
        raise ValueError('Invalid vanilla DBC')
    rows = {}
    for index in range(count):
        row = struct.unpack_from('<' + 'I' * fields, data, 20 + index * size)
        rows[row[0]] = row
    return rows, data[20 + count * size:]


def creature_assets(chain, displays=DISPLAYS):
    display_rows, display_strings = dbc(chain.read('DBFilesClient\\CreatureDisplayInfo.dbc'))
    models, model_strings = dbc(chain.read('DBFilesClient\\CreatureModelData.dbc'))
    extras, extra_strings = dbc(chain.read('DBFilesClient\\CreatureDisplayInfoExtra.dbc'))
    for display in displays:
        row = display_rows[display]
        if row[3]:
            # Humanoid NPCs wear a pre-baked skin and armor texture named by the last field.
            bake = extra_strings[extras[row[3]][-1]:].split(b'\0', 1)[0].decode('ascii')
            yield 'Textures\\BakedNpcTextures\\' + bake
        model = models[row[1]]
        pos = model[2]
        path = model_strings[pos:].split(b'\0', 1)[0].decode('ascii')
        yield canonical(path)
        if row[3]:
            # Character NPCs use their baked body atlas. Legacy Skin1 strings
            # can name retired creature textures which are never sampled.
            continue
        for pos in row[6:9]:
            if pos:
                skin = display_strings[pos:].split(b'\0', 1)[0].decode('ascii')
                folder = path.rsplit('\\', 1)[0]
                yield folder + '\\' + skin + ('' if skin.lower().endswith('.blp') else '.blp')


def prepare(source, installed):
    vanilla, game = Chain(source), Chain(installed)
    pending = [f'World\\Maps\\Kalimdor\\Kalimdor_{x}_{y}.adt'
               for x in range(39, 42) for y in range(29, 32)]
    pending += list(creature_assets(vanilla))
    translations = vanilla.read('Textures\\Minimap\\md5translate.trs').decode('ascii')
    wanted = {f'kalimdor\\map{x}_{y}.blp' for x in range(39, 42) for y in range(29, 32)}
    found = set()
    for line in translations.splitlines():
        parts = line.split('\t')
        if len(parts) == 2 and parts[0].lower() in wanted:
            pending.append('Textures\\Minimap\\' + parts[1])
            found.add(parts[0].lower())
    if found != wanted:
        raise ValueError('Durotar minimap translation entries are missing')
    card = vanilla.read('Interface\\Glues\\LoadingScreens\\LoadScreenKalimdor.blp')
    if card is None:
        raise ValueError('Vanilla Kalimdor loading-screen artwork is missing')
    entries = {'Interface\\ASR\\zone-photos_____\\loadscreenasrdurotar.blp': card}
    checked, missing = set(), []
    while pending:
        name = canonical(pending.pop())
        key = name.lower()
        if key in checked:
            continue
        checked.add(key)
        data = game.read(name)
        if data is None:
            data = vanilla.read(name)
            if data is None:
                missing.append(name)
                continue
            entries[name] = data
        pending.extend(dependencies(name, data))
    if missing:
        raise ValueError('Missing asset dependencies: ' + ', '.join(sorted(missing)))
    archive = build(entries)
    vanilla.close()
    game.close()
    restored = read_stored(archive)
    expected = sorted(entries.items())
    # build() adds the listfile first, followed by entries in sorted order.
    if restored[1:] != [value for _, value in expected]:
        raise ValueError('Durotar archive failed read-back verification')
    return archive, {'checked': len(checked), 'added': len(entries),
                     'assets': {n: hashlib.sha256(b).hexdigest() for n, b in sorted(entries.items())}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--installed', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    archive, report = prepare(args.source, args.installed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(archive)
    args.out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Built {args.out}: {report["added"]} assets, {report["checked"]} dependencies checked, {len(archive):,} bytes')
