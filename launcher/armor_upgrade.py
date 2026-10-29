"""Prepare retail versions of armor referenced by the installed item display table.

Does not introduce items, change stats, or write either installation. Unsupported
assets are listed explicitly; they are never replaced with another race's mesh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import blp
from bloodelf_assets import Dbc, dbc_name
import casc
from character_upgrade import RACES, listfile, required, texture_names
from durotar_assets import Chain
from photo_archive import build, read_stored
import retail_m2

HEAD = 'Item\\ObjectComponents\\Head\\'
ALIASES = {
    'helm_engi_c_02': 'helm_engi_c_02space',
    'helm_leather__raidrogue_a_01': 'helm_leather_raidrogue_a_01',
    'helm_leather_a': 'helm_leather_a_01',
    'helm_leather_pvphorde_c': 'helm_leather_pvphorde_c_01',
    'helm_mail_pvphorde_c': 'helm_mail_pvphorde_c_01',
    'helm_mask_zulgurub_d': 'helm_mask_zulgurub_d_01',
    'helm_plate_a_01': 'helm_plate_a_01crusader',
    'helm_plate_raidwarrior_b': 'helm_plate_raidwarrior_b_01',
    'helm_robe_ahnqiraj_a': 'helm_robe_ahnqiraj_a_01',
    'helm_robe_holiday_summerfest_a': 'helm_robe_holiday_summerfest_a_01',
}
REGIONS = ('ArmUpperTexture', 'ArmLowerTexture', 'HandTexture', 'TorsoUpperTexture',
           'TorsoLowerTexture', 'LegUpperTexture', 'LegLowerTexture', 'FootTexture')


def convert(storage, fid, entries):
    model = required(storage, fid)
    if model[:8] == b'MD20\x00\x01\x00\x00':
        return model
    ch = retail_m2.chunks(model) if model[:4] != b'MD20' else {'MD21': model}
    if 'SFID' not in ch:
        raise ValueError('Equipment has no skin FileDataID')
    skin = required(storage, struct.unpack_from('<I', ch['SFID'])[0])
    skeleton = required(storage, struct.unpack('<I', ch['SKID'])[0]) if 'SKID' in ch else None
    count, offset = retail_m2.arr(skin, 28)
    geosets = {struct.unpack_from('<H', skin, offset + 48 * i)[0]:
               struct.unpack_from('<H', skin, offset + 48 * i)[0] for i in range(count)}
    fixed = texture_names(storage, model, entries)
    converter = retail_m2.Converter(model, skeleton, skin, f'ASR armor {fid}', {0}, geosets,
                                   [], remap_body=False, texture_names=fixed)
    output = converter.convert()
    if not converter.report['batches'] or not converter.report['indices']:
        raise ValueError('Equipment conversion produced an empty mesh')
    return output


def prepare(retail, installed, names_path, out):
    lookup = listfile(names_path)
    storage, game = casc.Casc(retail), Chain(installed)
    entries, cache = {}, {}
    report = dict(retail_build=storage.version, helmets=[], shoulders=[], textures=[], unsupported=[])
    def model(source_path, destination, bucket):
        fid = lookup.get(source_path.lower().replace('\\', '/'))
        if not fid:
            report['unsupported'].append(dict(path=destination, reason='No retail source', source=source_path))
            return
        if fid not in cache:
            try:
                cache[fid] = convert(storage, fid, entries)
            except (ValueError, PermissionError) as error:
                report['unsupported'].append(dict(path=destination, source=source_path,
                                                  file_id=fid, reason=str(error)))
                return
        entries[destination] = cache[fid]
        report[bucket].append(dict(path=destination, source=source_path, file_id=fid))
    try:
        displays = Dbc(game.read(dbc_name('ItemDisplayInfo')))
        heads = sorted({displays.string(r[1])[:-4] for r in displays.rows()
                        if r[1] and displays.string(r[1]).lower().startswith('helm')})
        for stem in heads:
            print(f'Helmet {stem}', flush=True)
            src = ALIASES.get(stem.lower(), stem)
            for _, prefix, _ in RACES.values():
                for sex in 'MF':
                    source_path = HEAD + f'{src}_{prefix}{sex}.m2'
                    # The engineering goggle is shared, apart from Dwarf variants.
                    if stem.lower() == 'helm_goggles_b_04' and (prefix, sex) != ('Dw', 'M'):
                        source_path = HEAD + stem + '.m2'
                    model(source_path, HEAD + f'{stem}_{prefix}{sex}.m2', 'helmets')
        shoulders = sorted({displays.string(r[col]) for r in displays.rows() for col in (1, 2)
                            if r[col] and displays.string(r[col]).lower().startswith(('lshoulder', 'rshoulder', 'shoulder'))})
        for name in shoulders:
            path = 'Item\\ObjectComponents\\Shoulder\\' + name[:-4] + '.m2'
            print(f'Shoulder {name}', flush=True)
            model(path, path, 'shoulders')
        textures = set()
        for row in displays.rows():
            for region, value in zip(REGIONS, row[14:22]):
                if value:
                    stem = displays.string(value)
                    for sex in ('U', 'M', 'F'):
                        path = f'Item\\TextureComponents\\{region}\\{stem}_{sex}.blp'
                        key = path.lower().replace('\\', '/')
                        if key in lookup:
                            textures.add((path, lookup[key]))
            for col in (3, 4):
                if row[col]:
                    stem = displays.string(row[col])
                    for directory in ('Head', 'Shoulder'):
                        path = f'Item\\ObjectComponents\\{directory}\\{stem}.blp'
                        key = path.lower().replace('\\', '/')
                        if key in lookup:
                            textures.add((path, lookup[key]))
        for path, fid in sorted(textures):
            try:
                data = required(storage, fid)
                blp.decode(data, 0)  # Refuse formats the asset tools cannot inspect.
            except (ValueError, PermissionError) as error:
                report['unsupported'].append(dict(path=path, file_id=fid, reason=str(error),
                                                  retained_legacy=game.read(path) is not None))
                continue
            entries[path] = data
            report['textures'].append(dict(path=path, file_id=fid))
        archive = build(entries)
        if read_stored(archive)[1:] != [v for _, v in sorted(entries.items())]:
            raise ValueError('Armor archive failed read-back verification')
        report['files'] = len(entries)
        report['assets'] = {k: hashlib.sha256(v).hexdigest() for k, v in sorted(entries.items())}
        out.write_bytes(archive)
        out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'Built {out}: {len(entries)} files, {len(archive):,} bytes; '
              f'{len(report["unsupported"])} unsupported variants', flush=True)
    finally:
        storage.close()
        game.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('retail', type=Path)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--listfile', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    prepare(args.retail, args.installed, args.listfile, args.out)
