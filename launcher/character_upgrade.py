"""Build a separate, reversible retail-character patch for the nine ASR races.

Reads both installations without modifying them. Existing customization keys are
retained; retail choices are mapped onto those keys. The manifest records every
source, LOD and fallback so preparation is distinct from approval to ship.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import blp
from bloodelf_assets import Dbc, dbc_name
import casc
import db2
from durotar_assets import Chain
from photo_archive import build, read_stored
import retail_m2
import retail_textures

RACES = {
    1: ('Human', 'Hu', (1011653, 1000764)),
    2: ('Orc', 'Or', (917116, 949470)),
    3: ('Dwarf', 'Dw', (878772, 950080)),
    4: ('NightElf', 'Ni', (974343, 921844)),
    5: ('Scourge', 'Sc', (959310, 997378)),
    6: ('Tauren', 'Ta', (968705, 986648)),
    7: ('Gnome', 'Gn', (900914, 940356)),
    8: ('Troll', 'Tr', (1022938, 1018060)),
    10: ('BloodElf', 'Be', (1100087, 1100258)),
}
SECTIONS = ('CharSections', 'CharHairGeosets', 'CharacterFacialHairStyles')


def listfile(path):
    with Path(path).open(encoding='utf-8') as source:
        return {name.strip().lower(): int(fid) for line in source
                if (parts := line.partition(';'))[1]
                for fid, _, name in [parts]}


def required(storage, fid):
    data = storage.read(fid)
    if data is None:
        raise ValueError(f'Required retail FileDataID {fid} is unavailable locally')
    return data


def texture_names(storage, model, entries):
    """Resolve TXID's fixed textures by index, without conflating type-0 entries."""
    ch = retail_m2.chunks(model) if model[:4] != b'MD20' else {'MD21': model}
    m = ch['MD21']
    txids = ch.get('TXID', b'')
    out = {}
    count, offset = retail_m2.arr(m, 0x50)
    for index in range(min(count, len(txids) // 4)):
        fid = struct.unpack_from('<I', txids, index * 4)[0]
        kind = struct.unpack_from('<I', m, offset + index * 16)[0]
        if kind == 0 and fid:
            path = f'ASR\\Retail\\Texture{fid}.blp'
            if path not in entries:
                data = required(storage, fid)
                entries[path] = blp.encode(blp.decode(data, retail_textures.level_for(data, 256)))
            out[index] = path
    return out


class Choices:
    """Expose retail choices using the existing save's customization ranges."""
    def __init__(self, custom, race, old_sections, old_hair, old_facial):
        self.c, self.race = custom, race
        self.alias = {'Facial Hair': next((n for n in ('Facial Hair', 'Beard', 'Jaw Features', 'Tusks',
                                                      'Earrings', 'Markings') if custom.choices(n)), '')}
        if race == 4 and custom.choices('Markings') and not custom.choices('Beard'):
            self.alias['Facial Hair'] = 'Markings'
        if race == 6:
            self.alias.update({'Hair Style': 'Horn Style', 'Hair Color': 'Horn Color'})
        self.rows = old_sections
        self.styles = sorted({r[3] for r in old_hair})
        self.facial = sorted({r[2] for r in old_facial})
        self.counts = {
            'Skin Color': 1 + max(r[5] for r in old_sections if r[3] == 0),
            'Face': 1 + max(r[4] for r in old_sections if r[3] == 1),
            'Hair Color': 1 + max((r[5] for r in old_sections if r[3] == 3), default=0),
            'Hair Style': 1 + max(self.styles, default=0),
            'Facial Hair': 1 + max(self.facial, default=0),
        }
        self.fallbacks = []
        self.cached = {}
        for option, count in self.counts.items():
            source = custom.choices(self.alias.get(option, option))
            if not source and option not in ('Facial Hair',):
                raise ValueError(f'Race {race}: no retail choices for {option}')
            self.cached[option] = [source[i % len(source)] for i in range(count)] if source else []
            if source and count > len(source):
                self.fallbacks.append(f'{option}: {count} legacy values map to {len(source)} retail choices')

    def choices(self, name):
        return self.cached.get(name, self.c.choices(name))

    def texture(self, choice, target, related=None):
        if target == 8 and self.alias['Facial Hair'] == 'Markings':
            colors = self.c.choices('Markings Color')
            colors = [ch for ch in colors if any(
                self.c.t['material'].rows.get(e[4], [None])[0] == 17 for e in self.c.elements(ch))]
            hair = self.choices('Hair Color')
            index = hair.index(related) if related in hair else 0
            return self.c.texture(colors[index % len(colors)], 17, choice) if colors else None
        result = self.c.texture(choice, target, related)
        # Tauren female face components use target 4 for the original face choices.
        return result or (self.c.texture(choice, 4, related) if target == 5 and self.race == 6 else None)

    def geoset(self, choice, group):
        if group == 0 and self.race == 6:
            return self.c.geoset(choice, 24)
        return self.c.geoset(choice, group)


def mapping(custom):
    """Select only legacy clothing and one coherent default for newer body regions."""
    out = {0: 0, **{g: g for g in (401, 402, 403, 404, 501, 502, 503, 504,
            802, 803, 902, 903, 1002, 1102, 1103, 1202, 1301, 1302, 1502, 1503, 1504)}}
    for g in (1801, 2001, 2201, 2301, 3202, 3301, 3401):
        out[g] = 0
    # Default retail options close race-specific face, jaw, tusk and horn regions.
    for option in custom.c.options:
        choices = custom.c.choices(option)
        if not choices or option in ('Hair Style', 'Horn Style', custom.alias['Facial Hair']):
            continue
        for group in (2, 3, 7, 19, 24, 29, 30, 32, 33, 34, 40):
            g = custom.c.geoset(choices[0], group)
            if g is not None and g % 100:
                if group == 7:
                    out[g] = 702
                elif group >= 16:
                    # Replace earlier defaults in this region, rather than overlap them.
                    out = {k: v for k, v in out.items() if k // 100 != group}
                    out[g] = 0
                else:
                    out[g] = 0
    out.setdefault(702, 702)
    hair = []
    for variation, choice in enumerate(custom.choices('Hair Style')):
        g = custom.geoset(choice, 0)
        target = (variation + 2) if custom.race == 6 else (g or 1)
        if g:
            out[g] = target
        hair.append((variation, target))
    facial, assigned_facial = [], {}
    for variation, choice in enumerate(custom.choices('Facial Hair')):
        picks = []
        for group in (1, 3, 2):
            g = custom.c.geoset(choice, group)
            if g is not None and g % 100:
                out[g] = g
            picks.append((g or group * 100) % 100)
        if custom.race in (8, 31):
            g = custom.c.geoset(choice, 40)
            if g:
                target = assigned_facial.setdefault(g, 102 + variation)
                out[g] = target
                picks[0] = target - 100
        if not any(picks):
            # Jewelry is a selectable facial feature in the legacy customization UI.
            for group in (16, 35):
                g = custom.c.geoset(choice, group)
                if g and g % 100:
                    target = assigned_facial.setdefault(g, 102 + variation)
                    out[g] = target
                    picks[0] = target - 100
        facial.append((variation, picks))
    return out, hair, facial


def animations(data):
    count, offset = retail_m2.arr(data, 0x1C)
    keep = {struct.unpack_from('<H', data, offset + 68 * i)[0] for i in range(count)}
    count, offset = retail_m2.arr(data, 0x2C)
    return keep, list(struct.iter_unpack('<hh', data[offset:offset + count * 4]))


def attachment_height(data, ident=11, effective=False):
    count, offset = retail_m2.arr(data, 0x104)
    for i in range(count):
        if struct.unpack_from('<I', data, offset+48*i)[0] == ident:
            height = struct.unpack_from('<f', data, offset+48*i+16)[0]
            if effective:
                bone = struct.unpack_from('<H', data, offset+48*i+4)[0]
                count, bones = retail_m2.arr(data, 0x34)
                for _ in range(count):
                    parent = struct.unpack_from('<h', data, bones+108*bone+8)[0]
                    if parent == -1:
                        n, values = retail_m2.arr(data, bones+108*bone+68+20)
                        scale = struct.unpack_from('<f', data, values+8)[0] if n else 1.0
                        pivot = struct.unpack_from('<f', data, bones+108*bone+104)[0]
                        return pivot+(height-pivot)*scale
                    bone = parent
                raise ValueError('Cyclic reference character skeleton')
            return height
    raise ValueError(f'Missing character reference attachment {ident}')


def legacy_root_scale(data, factor):
    """Scale the whole rig, including riders, rather than detaching scaled vertices.

    Tauren's retail mesh is authored larger than the old client model. Applying
    the factor at every root preserves all bone-local equipment relationships.
    """
    if not 0.5 <= factor <= 1.5:
        raise ValueError('Unsupported character scale correction')
    out = bytearray(data)
    seqs, seq_at = retail_m2.arr(out, 0x1C)
    bones, bone_at = retail_m2.arr(out, 0x34)
    def append(blob):
        out.extend(bytes((-len(out)) % 4))
        at = len(out)
        out.extend(blob)
        return at
    for i in range(bones):
        bone = bone_at+108*i
        if struct.unpack_from('<h', out, bone+8)[0] != -1:
            continue
        scale = bone+68
        count, at = retail_m2.arr(out, scale+20)
        if count:
            values = struct.unpack_from(f'<{count*3}f', out, at)
            struct.pack_into(f'<{count*3}f', out, at, *(v*factor for v in values))
        else:
            ranges = append(b''.join(struct.pack('<II', j, j) for j in range(seqs)))
            times = append(b''.join(out[seq_at+68*j+4:seq_at+68*j+8] for j in range(seqs)))
            values = append(struct.pack('<3f', factor, factor, factor)*seqs)
            struct.pack_into('<HhIIIIII', out, scale, 0, -1, seqs, ranges, seqs, times, seqs, values)
    for at in (0xB4, 0xD0):
        values = struct.unpack_from('<7f', out, at)
        struct.pack_into('<7f', out, at, *(v*factor for v in values))
    for i in range(seqs):
        at = seq_at+68*i
        speed = struct.unpack_from('<f', out, at+12)[0]
        struct.pack_into('<f', out, at+12, speed*factor)
        bounds = struct.unpack_from('<7f', out, at+36)
        struct.pack_into('<7f', out, at+36, *(v*factor for v in bounds))
    return bytes(out)


def clear_missing_legacy_overlays(entries, game):
    """Remove already-broken optional facial-overlay references from legacy rows."""
    names = {name.lower() for name in entries}
    path = dbc_name('CharSections')
    table = Dbc(entries[path])
    cleared = []
    for index, row in enumerate(table.rows()):
        if row[1] not in RACES or row[3] != 2:
            continue
        values = list(row)
        for col in range(6, 9):
            if not row[col]:
                continue
            texture = table.string(row[col])
            if texture.lower() not in names and game.read(texture) is None:
                values[col] = 0
                cleared.append(dict(row=row[0], path=texture))
        table.records[index] = struct.pack('<10I', *values)
    entries[path] = table.bytes()
    return cleared


def merge_race_archive(entries, installed):
    """Replace W while retaining its race/display tables and portrait atlas.

    The native loader mounts only patch-?.MPQ; a later multi-letter filename is
    ignored. A separate lower-priority patch also loses to W's customization DBCs.
    """
    source = Path(installed) / 'patch-W.MPQ'
    blobs = read_stored(source.read_bytes())
    names = blobs[0].decode('ascii').splitlines()
    original = dict(zip(names, blobs[1:], strict=True))
    incoming = {name.lower(): name for name in entries}
    for name, data in original.items():
        if name.lower() not in incoming:
            entries[name] = data
    return hashlib.sha256(source.read_bytes()).hexdigest()


def convert_character(storage, game, tables, dbcs, race, sex, entries):
    folder, _, ids = RACES[race]
    label = ('Male', 'Female')[sex]
    path = f'Character\\{folder}\\{label}\\{folder}{label}.m2'
    old_sections = [r for r in dbcs['CharSections'].rows() if r[1:3] == (race, sex)]
    old_hair = [r for r in dbcs['CharHairGeosets'].rows() if r[1:3] == (race, sex)]
    old_facial = [r for r in dbcs['CharacterFacialHairStyles'].rows() if r[:2] == (race, sex)]
    custom = Choices(retail_textures.Customization(tables, (race - 1) * 2 + sex + 1),
                     race, old_sections, old_hair, old_facial)
    geosets, hair, facial = mapping(custom)
    model = required(storage, ids[sex])
    ch = retail_m2.chunks(model)
    skel_id = struct.unpack('<I', ch['SKID'])[0] if 'SKID' in ch else None
    skeleton = required(storage, skel_id) if skel_id else None
    keep, playable = animations(game.read(path))
    eye_path = f'Character\\{folder}\\{folder}{label}Eyes.blp'
    fixed = texture_names(storage, model, entries)
    dynamic = {19: eye_path}
    for option in ('Jewelry Color', 'Earring Color'):
        choices = custom.c.choices(option)
        fid = custom.c.texture(choices[0], 38) if choices else None
        if fid:
            path_extra = f'Character\\{folder}\\{folder}{label}Jewelry.blp'
            data = required(storage, fid)
            entries[path_extra] = blp.encode(blp.decode(data, retail_textures.level_for(data, 256)))
            dynamic[20] = path_extra
            break
    # The first LOD that fits keeps complete triangles and every mapped feature.
    candidates = struct.unpack('<' + 'I' * (len(ch['SFID']) // 4), ch['SFID'])
    chosen = None
    for lod, fid in enumerate(candidates):
        skin = required(storage, fid)
        converter = retail_m2.Converter(model, skeleton, skin, folder + label, keep, geosets,
                                       playable, dynamic, texture_names=fixed)
        total = sum(n for g, n in converter.index_counts().items() if g in geosets)
        if total <= 65535:
            chosen = (lod, fid, converter)
            break
    if chosen is None:
        raise ValueError(f'{folder}{label}: all complete customization meshes exceed 65535 indices')
    lod, skin_id, converter = chosen
    output = converter.convert()
    if race == 6 and sex == 1:
        output = retail_m2.preserve_body_palette(output, converter)
    scale_factor = 1.0
    if race == 6:
        scale_factor = attachment_height(game.read(path), effective=True) / attachment_height(output)
        output = legacy_root_scale(output, scale_factor)
    entries[path] = output
    builder = retail_textures.Builder(storage, custom, race, sex, f'Character\\{folder}',
                    folder + label, list(range(custom.counts['Hair Style'])),
                    custom.counts['Facial Hair'], shared_hair=False,
                    preserve_body_palette=(race == 6 and sex == 1)).build()
    # Preserve every saved customization key and the NPC-only flags; use the nearest
    # ordinary retail choice when a legacy key has no one-to-one retail equivalent.
    generated = {(r[2], r[3], r[4]): r[5:8] for r in builder.rows}
    sections = dbcs['CharSections']
    for index, row in enumerate(sections.rows()):
        if row[1:3] != (race, sex):
            continue
        textures = generated.get((row[3], row[4], row[5]))
        if textures is None:
            textures = generated.get((row[3], 0, row[5]))
        if textures is None:
            candidates = [v for k, v in sorted(generated.items()) if k[0] == row[3] and k[2] == row[5]]
            if candidates:
                textures = candidates[0]
            else:
                candidates = [v for k, v in sorted(generated.items()) if k[0] == row[3]]
                if not candidates:
                    raise ValueError(f'{folder}{label}: no textures for customization {row[3:6]}')
                textures = candidates[row[5] % len(candidates)]
            custom.fallbacks.append(f'Legacy texture key {row[3:6]} uses an ordinary retail fallback')
        # An old painted beard is authored for the old face UVs. It must never
        # be applied to a retail head, even when the new choice is geoset-only.
        updated = list(row)
        updated[6:9] = [sections.text(t) for t in textures]
        sections.records[index] = struct.pack('<10I', *updated)
    hair_map = dict(hair)
    for index, row in enumerate(dbcs['CharHairGeosets'].rows()):
        if row[1:3] == (race, sex):
            updated = list(row)
            updated[4:6] = [hair_map[row[3]], 0]
            dbcs['CharHairGeosets'].records[index] = struct.pack('<6I', *updated)
    facial_map = dict(facial)
    for index, row in enumerate(dbcs['CharacterFacialHairStyles'].rows()):
        if row[:2] == (race, sex):
            updated = list(row)
            updated[6:9] = facial_map.get(row[2], [0, 0, 0])
            dbcs['CharacterFacialHairStyles'].records[index] = struct.pack('<9I', *updated)
    entries.update(builder.files)
    if eye_path not in entries:
        raise ValueError(f'{folder}{label}: no eye texture')
    return dict(model_file=ids[sex], skeleton_file=skel_id, skin_file=skin_id, lod=lod,
                legacy_scale_factor=scale_factor,
                path=path, customizations=custom.counts, fallbacks=custom.fallbacks,
                **converter.report)


def prepare(retail, installed, out):
    storage, game = casc.Casc(retail), Chain(installed)
    entries, report = {}, {'characters': {}, 'retail_build': storage.version}
    try:
        tables = {k: db2.Table(required(storage, v)) for k, v in retail_textures.TABLES.items()}
        dbcs = {k: Dbc(game.read(dbc_name(k))) for k in SECTIONS}
        for race, (folder, _, _) in RACES.items():
            for sex, label in enumerate(('Male', 'Female')):
                print(f'Converting {folder}{label}...', flush=True)
                report['characters'][folder + label] = convert_character(
                    storage, game, tables, dbcs, race, sex, entries)
                # Keep reviewable intermediates, allowing failures to be diagnosed.
                for name, data in entries.items():
                    dest = out.parent / 'files' / name.replace('\\', '/')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
        for name, table in dbcs.items():
            entries[dbc_name(name)] = table.bytes()
        report['cleared_missing_legacy_overlays'] = clear_missing_legacy_overlays(entries, game)
        report['base_race_archive_sha256'] = merge_race_archive(entries, installed)
        archive = build(entries)
        if read_stored(archive)[1:] != [data for _, data in sorted(entries.items())]:
            raise ValueError('Archive read-back differs from source entries')
        report['assets'] = {k: hashlib.sha256(v).hexdigest() for k, v in sorted(entries.items())}
        report['files'] = len(entries)
        out.write_bytes(archive)
        out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'Built {out}: {len(entries)} files, {len(archive):,} bytes', flush=True)
    finally:
        storage.close()
        game.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('retail', type=Path)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    prepare(args.retail, args.installed, args.out)
