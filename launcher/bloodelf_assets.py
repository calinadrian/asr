"""Build patch-W.MPQ: the Blood Elf race's 1.12 models, textures and DBC rows from a retail install.

Both models are converted with retail_m2 and their customization textures cut with
retail_textures. Hair styles are added in display order while the model stays within 1.12's
65,535 indices. The installed game's DBCs get race 10 rows: ChrRaces, CharBaseInfo,
CharSections, CharHairGeosets, CharacterFacialHairStyles, CreatureDisplayInfo and
CreatureModelData. Nothing in the retail install or the installed Data is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import casc
import db2
from durotar_assets import Chain
from photo_archive import build, read_stored
import retail_m2
import retail_textures

ARCHIVE = 'patch-W.MPQ'
RACE, FOLDER, PREFIX = 10, 'Character\\BloodElf', 'Be'
CLASSES = (2, 3, 4, 5, 8, 9)            # paladin, hunter, rogue, priest, mage, warlock
DISPLAYS = {0: 15476, 1: 15475}         # the IDs TBC gave the Blood Elf player models
RACE_ATLAS = 'Interface\\Glues\\CharacterCreate\\UI-CharacterCreate-Races.blp'
RACE_ATLAS_FILE = 131152               # 512x256, including Blood Elf at (256, 64/192)
SEXES = {0: dict(name='Male', model=1100087, skel=1838675, skin=1100099, chr_model=19),
         1: dict(name='Female', model=1100258, skel=1838505, skin=1100298, chr_model=20)}
# Retail geosets with a 1.12 counterpart, and the retail-only ones that close the body (bare waist,
# feet, torso, hands, face, eyes, eyebrows) folded into the always-shown base mesh.
KEEP = (401, 402, 403, 404, 501, 502, 503, 504, 701, 702, 802, 803, 902, 903, 1002, 1102, 1202,
        1301, 1302, 1502, 1503, 1504)
FOLD = (1801, 2001, 2201, 2301, 3202, 3301, 3401)
FACIAL_STYLES = 7                       # clean and the first six beards


class Dbc:
    """A 1.12 DBC kept as raw records, so tables with byte fields or no ID column survive."""
    def __init__(self, data):
        magic, self.count, self.fields, self.size, strings = struct.unpack_from('<4sIIII', data)
        if magic != b'WDBC' or len(data) != 20 + self.count * self.size + strings:
            raise ValueError('Invalid vanilla DBC')
        self.records = [data[20 + i * self.size:20 + (i + 1) * self.size] for i in range(self.count)]
        self.strings = bytearray(data[20 + self.count * self.size:])

    def rows(self):
        return [struct.unpack(f'<{self.size // 4}I', r) for r in self.records] if self.size % 4 == 0 else []

    def string(self, offset):
        return self.strings[offset:self.strings.index(b'\0', offset)].decode('latin-1')

    def text(self, value):
        """The offset of value in the string block, appending it when it is new."""
        if not value:
            return 0
        raw = value.encode('latin-1') + b'\0'
        found = self.strings.find(b'\0' + raw)
        if found >= 0:
            return found + 1
        offset = len(self.strings)
        self.strings += raw
        return offset

    def add(self, values):
        """Append a record of u32 values; str values are stored in the string block."""
        words = [self.text(v) if isinstance(v, str) else v for v in values]
        record = struct.pack(f'<{len(words)}I', *words)
        if len(record) != self.size:
            raise ValueError(f'Record of {len(record)} bytes for a {self.size}-byte table')
        self.records.append(record)

    def add_raw(self, record):
        self.records.append(record)

    def next_id(self):
        return max(r[0] for r in self.rows()) + 1

    def bytes(self):
        return struct.pack('<4sIIII', b'WDBC', len(self.records), self.fields, self.size,
                           len(self.strings)) + b''.join(self.records) + bytes(self.strings)


def dbc_name(table):
    return f'DBFilesClient\\{table}.dbc'


def vanilla_animations(game, sex):
    """The animation IDs and PlayableAnimationLookup of the 1.12 human model of that sex."""
    data = game.read(f'Character\\Human\\{sex}\\Human{sex}.m2')
    count, offset = struct.unpack_from('<II', data, 0x1C)
    ids = {struct.unpack_from('<H', data, offset + 68 * i)[0] for i in range(count)}
    count, offset = struct.unpack_from('<II', data, 0x2C)
    return ids, [struct.unpack_from('<hh', data, offset + 4 * i) for i in range(count)]


def convert_model(retail, custom, sex, game):
    info = SEXES[sex]
    ids, playable = vanilla_animations(game, info['name'])
    files = [retail.read(info[k]) for k in ('model', 'skel', 'skin')]
    eyes = f'{FOLDER}\\BloodElf{info["name"]}Eyes.blp'
    geosets = {0: 0, **{g: g for g in KEEP}, **{g: 0 for g in FOLD}}
    facial = [custom.geoset(c, 1) for c in custom.choices('Facial Hair')[:FACIAL_STYLES]]
    geosets.update({g: g for g in facial if g})
    probe = retail_m2.Converter(*files, '', ids, geosets, playable, {19: eyes})
    counts = probe.index_counts()
    budget = 0xFFFF - sum(c for g, c in counts.items() if g in geosets)
    kept = []
    for position, choice in enumerate(custom.choices('Hair Style')):
        g = custom.geoset(choice, 0)
        if g is None or counts.get(g, 0) > budget:
            break
        budget -= counts.get(g, 0)
        geosets[g] = g
        kept.append(position)
    converter = retail_m2.Converter(*files, f'BloodElf{info["name"]}', ids, geosets, playable, {19: eyes})
    model = converter.convert()
    return model, kept, len([g for g in facial if g is not None]), converter.report


def add_rows(tables, sex_rows, sex_models):
    races = tables['ChrRaces']
    template = next(r for r in races.rows() if r[0] == 1)
    if any(r[0] == RACE for r in races.rows()):
        raise ValueError('The installed ChrRaces already has race 10')
    row = list(template)
    row[0], row[4], row[5] = RACE, DISPLAYS[0], DISPLAYS[1]
    row[2] = next(r for r in races.rows() if r[0] == 5)[2]   # the Undead's Horde faction template
    row[6], row[15], row[16] = PREFIX, 'BloodElf', 0
    row[17:25] = ['Blood Elf'] + [0] * 7
    races.add(row)

    base = tables['CharBaseInfo']
    for cls in CLASSES:
        base.add_raw(bytes((RACE, cls)))

    displays, models = tables['CreatureDisplayInfo'], tables['CreatureModelData']
    for sex, name in sex_models.items():
        human_display = next(r for r in displays.rows() if r[0] == (49 if sex == 0 else 50))
        human_model = list(next(r for r in models.rows() if r[0] == human_display[1]))
        model_id = models.next_id()
        human_model[0], human_model[2] = model_id, name[:-3] + '.mdx'
        models.add(human_model)
        display = list(human_display)
        display[0], display[1] = DISPLAYS[sex], model_id
        display[6:9] = [0, 0, 0]
        displays.add(display)

    sections, hair, facial = tables['CharSections'], tables['CharHairGeosets'], tables['CharacterFacialHairStyles']
    section_id, hair_id = sections.next_id(), hair.next_id()
    for sex, (rows, hair_geosets, facial_geosets) in sex_rows.items():
        for race, s, section, variation, color, *textures in rows:
            sections.add([section_id, race, s, section, variation, color, *textures, 0])
            section_id += 1
        for variation, geoset in hair_geosets:
            hair.add([hair_id, RACE, sex, variation, geoset, 0])
            hair_id += 1
        for variation, geoset in facial_geosets or [(0, 100)]:
            facial.add([RACE, sex, variation, 0, 0, 0, geoset % 100, 0, 0])


def verify(entries, game):
    """Follow race 10 through the patched tables to every model, geoset and texture they name."""
    lower = {k.lower(): v for k, v in entries.items()}
    read = lambda name: lower.get(name.lower()) or game.read(name)
    table = lambda name: Dbc(read(dbc_name(name)))
    problems = []
    races = table('ChrRaces')
    race = next((r for r in races.rows() if r[0] == RACE), None)
    if race is None:
        return ['ChrRaces has no race 10']
    displays = {r[0]: r for r in table('CreatureDisplayInfo').rows()}
    models = table('CreatureModelData')
    model_rows = {r[0]: r for r in models.rows()}
    geosets = {}
    for sex, display in ((0, race[4]), (1, race[5])):
        model = model_rows.get(displays.get(display, (0, 0))[1])
        path = models.string(model[2])[:-4] + '.m2' if model else None
        data = read(path) if path else None
        if data is None:
            problems.append(f'sex {sex}: display {display} names no model file')
            continue
        _, view = struct.unpack_from('<II', data, 0x4C)
        count, offset = struct.unpack_from('<II', data, view + 24)
        geosets[sex] = {struct.unpack_from('<H', data, offset + 32 * i)[0] for i in range(count)}
    sections = table('CharSections')
    seen = set()
    for r in sections.rows():
        if r[1] != RACE:
            continue
        seen.add((r[2], r[3]))
        for offset in r[6:9]:
            name = sections.string(offset) if offset else ''
            if name and read(name) is None:
                problems.append(f'CharSections {r[0]} names missing {name}')
    for sex in (0, 1):
        missing = [s for s in range(5) if (sex, s) not in seen]
        if missing:
            problems.append(f'sex {sex} has no CharSections of types {missing}')
    for r in table('CharHairGeosets').rows():
        if r[1] == RACE and r[4] not in geosets.get(r[2], ()):
            problems.append(f'hair style {r[3]} of sex {r[2]} uses absent geoset {r[4]}')
    for r in table('CharacterFacialHairStyles').rows():
        if r[0] == RACE and r[6] and 100 + r[6] not in geosets.get(r[1], ()):
            problems.append(f'facial style {r[2]} of sex {r[1]} uses absent geoset {100 + r[6]}')
    base = Dbc(read(dbc_name('CharBaseInfo')))
    if sorted(r[1] for r in base.records if r[0] == RACE) != sorted(CLASSES):
        problems.append('CharBaseInfo does not list the Blood Elf classes')
    return problems


def prepare(retail_folder, installed):
    retail, game = casc.Casc(retail_folder), Chain(installed)
    try:
        tables = {k: db2.Table(retail.read(v)) for k, v in retail_textures.TABLES.items()}
        entries, sex_rows, sex_models, report = {}, {}, {}, {}
        for sex, info in SEXES.items():
            custom = retail_textures.Customization(tables, info['chr_model'])
            model, hair_styles, facial_styles, model_report = convert_model(retail, custom, sex, game)
            name = f'{FOLDER}\\{info["name"]}\\BloodElf{info["name"]}.m2'
            entries[name] = model
            sex_models[sex] = name
            textures = retail_textures.Builder(retail, custom, RACE, sex, FOLDER, f'BloodElf{info["name"]}',
                                               hair_styles, facial_styles if sex == 0 else 0).build()
            for path, data in textures.files.items():
                if entries.get(path, data) != data:
                    raise ValueError(f'{path} differs between the sexes')
                entries[path] = data
            sex_rows[sex] = (textures.rows, textures.hair_geosets, textures.facial_geosets)
            report[info['name']] = dict(model=model_report, hair_styles=len(hair_styles),
                                        sections=len(textures.rows), textures=len(textures.files))
        dbcs = {t: Dbc(game.read(dbc_name(t))) for t in
                ('ChrRaces', 'CharBaseInfo', 'CharSections', 'CharHairGeosets', 'CharacterFacialHairStyles',
                 'CreatureDisplayInfo', 'CreatureModelData')}
        add_rows(dbcs, sex_rows, sex_models)
        for table, d in dbcs.items():
            entries[dbc_name(table)] = d.bytes()
        atlas = retail.read(RACE_ATLAS_FILE)
        if struct.unpack_from('<II', atlas, 12) != (512, 256):
            raise ValueError('Unsupported Blood Elf portrait atlas dimensions')
        entries[RACE_ATLAS] = atlas
        problems = verify(entries, game)
        if problems:
            raise ValueError('Blood Elf data is inconsistent: ' + '; '.join(problems[:10]))
    finally:
        retail.close()
        game.close()
    archive = build(entries)
    if read_stored(archive)[1:] != [v for _, v in sorted(entries.items())]:
        raise ValueError('Blood Elf archive failed read-back verification')
    report['files'] = len(entries)
    report['assets'] = {n: hashlib.sha256(b).hexdigest() for n, b in sorted(entries.items())}
    return archive, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('retail', type=Path, help='the retail World of Warcraft folder (holds .build.info)')
    parser.add_argument('--installed', required=True, type=Path, help="the game's Data folder")
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    archive, report = prepare(args.retail, args.installed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(archive)
    args.out.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Built {args.out}: {report["files"]} files, {len(archive):,} bytes')
