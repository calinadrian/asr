"""Build the requested additional races into a separate, reviewable W archive.

The installed game's W is retained, including its upgraded original characters.
Each converted race is checkpointed; failed characters are reported, never
replaced with another race. No installation or release is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import blp
from bloodelf_assets import Dbc, dbc_name, vanilla_animations, RACE_ATLAS
import casc
from character_upgrade import listfile, mapping, required, texture_names
import db2
from durotar_assets import Chain, dependencies
from photo_archive import build, read_stored
from race_catalog import ADDITIONS, PORTRAITS, resolve
import retail_m2
import retail_textures
from race_model_merge import merge as merge_accessory
from verify_character_upgrade import model as validate_model

TABLE_NAMES = ('ChrRaces', 'CharBaseInfo', 'CharSections', 'CharHairGeosets',
               'CharacterFacialHairStyles', 'CreatureDisplayInfo', 'CreatureModelData')


def portraits(storage, game, names, resolved):
    original = blp.decode(game.read(RACE_ATLAS))
    atlas = (1024, 256, bytearray(1024*256*4))
    blp.paste(atlas, original, 0, 0, blend=False)
    sources = {}
    for race in ADDITIONS:
        folder = resolved[race.id]['folder'].lower()
        x, y = PORTRAITS[race.id]
        for sex, label in enumerate(('male', 'female')):
            path = f'interface/characterframe/temporaryportrait-{label}-{folder}.blp'
            if race.id in (84, 86):
                portrait = Path(__file__).parent/'assets'/'race-portraits'/f'{race.id}-{label}.blp'
                icon = blp.decode(portrait.read_bytes())
                if icon[:2] != (64, 64):
                    raise ValueError(f'Unexpected portrait dimensions: {portrait}')
                blp.paste(atlas, icon, x, y+sex*128, blend=False)
                sources[f'{race.id}:{sex}'] = dict(asset=portrait.name, sha256=hashlib.sha256(portrait.read_bytes()).hexdigest())
                continue
            fid = names.get(path)
            if not fid:
                raise ValueError(f'Missing race portrait: {path}')
            icon = blp.resize(blp.decode(required(storage, fid)), 64, 64)
            blp.paste(atlas, icon, x, y+sex*128, blend=False)
            sources[f'{race.id}:{sex}'] = fid
    return blp.encode(atlas), sources


class Choices:
    """Map the five native selectors to the race's actual retail options."""
    def __init__(self, custom, race):
        self.c = custom
        self.defaults = tuple(values[0] for option in custom.options if (values := custom.choices(option)))
        self.race = 6 if race == 28 else race
        self.alias = {}
        for name, alternatives in {
            'Skin Color': ('Skin Color', 'Fur Color', 'Primary Color'),
            'Hair Color': ('Hair Color', 'Horn Color', 'Fur Color', 'Skin Color', 'Primary Color'),
            'Hair Style': ('Hair Style', 'Horn Style', 'Horns'),
            'Facial Hair': ('Facial Hair', 'Beard', 'Beard Style', 'Tusks', 'Tusk', 'Earrings'),
        }.items():
            self.alias[name] = next((n for n in alternatives if custom.choices(n)), '')
        if race == 28:
            self.alias.update({'Hair Style': 'Horn Style', 'Hair Color': 'Horn Color'})
        self.counts = {n: max(1, len(self.choices(n))) for n in
                       ('Skin Color', 'Face', 'Hair Style', 'Hair Color', 'Facial Hair')}

    def choices(self, name):
        return self.c.choices(self.alias.get(name, name))

    def texture(self, choice, target, related=None):
        if choice is None:
            return None
        result = self.c.texture(choice, target, related)
        if not result and related is None:
            for dependency in self.defaults:
                result = self.c.texture(choice, target, dependency)
                if result:
                    break
        if target == 5 and not result:
            result = self.c.texture(choice, 4, related)
        return result

    def geoset(self, choice, group):
        if self.race == 6 and group == 0:
            group = 24
        return self.c.geoset(choice, group)


class Textures(retail_textures.Builder):
    def build(self):
        super().build()
        # Some races bake faces/fur into their skin, with no separate face or
        # hair-color material. Keep a valid selector without borrowing artwork.
        skins = [r for r in self.rows if r[2] == 0]
        existing = {(r[2], r[3], r[4]) for r in self.rows}
        for skin in skins:
            color = skin[4]
            if (1, 0, color) not in existing:
                self.row(1, 0, color)
        if not self.hair_geosets:
            self.hair_geosets = [(0, 0)]
            self.row(3, 0, 0)
        if not any(r[2] == 2 for r in self.rows):
            self.row(2, 0, 0)
        return self


class DragonTextures(retail_textures.Builder):
    """Keep dragon skin atlases separate from painted humanoid armor regions."""
    def build(self):
        for color, choice in enumerate(self.c.choices('Skin Color')):
            atlas = (1024, 256, bytearray(1024*256*4))
            primary = None
            for tile, target in enumerate((1, 2, 3)):
                fid = self.c.texture(choice, target)
                if not fid:
                    raise ValueError(f'Dracthyr skin lacks texture target {target}')
                image = blp.resize(self.image(fid, 256), 256, 256)
                blp.paste(atlas, image, tile*256, 0, blend=False)
                primary = primary or image
            self.row(0, 0, color,
                     self.put(f'{self.prefix}Skin00_{color:02d}', primary),
                     self.put(f'{self.prefix}SkinExtra00_{color:02d}', atlas))
            self.row(1, 0, color)
            self.row(4, 0, color)
        for color, choice in enumerate(self.c.choices('Hair Color')):
            fid = self.c.texture(choice, 10)
            name = self.put(f'{self.prefix}HornColor{color:02d}', self.image(fid, 256)) if fid else ''
            for variation in range(self.c.counts['Hair Style']):
                self.row(3, variation, color, name)
        self.row(2, 0, 0)
        self.hair_geosets = [(0, 0)]
        self.facial_geosets = [(0, 0)]
        choices = self.c.choices('Eye Color')
        fid = self.c.texture(choices[0], 25) if choices else None
        self.eye_texture = self.put(f'{self.prefix}Eyes', self.image(fid, 64)) if fid else None
        return self


class DragonConverter(retail_m2.Converter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.remap_body = False
        self.usable.update((7, 9, 10))

    def build_view(self):
        super().build_view()
        types, lookup = self.texture_types(), self.u16s(0x80)
        for i, sub in enumerate(self.submeshes):
            kinds = {types[lookup[struct.unpack_from('<H', b, 16)[0]]]
                     for b in self.batches if struct.unpack_from('<H', b, 4)[0] == i}
            tiles = {{1: 0, 8: 1, 7: 2, 10: 2}[k] for k in kinds if k in (1, 7, 8, 10)}
            if len(tiles) > 1:
                raise ValueError('Dracthyr submesh has conflicting atlas UV layouts')
            if tiles:
                tile = tiles.pop()
                first, count = struct.unpack_from('<HH', sub, 4)
                for v in range(first, first+count):
                    u = struct.unpack_from('<f', self.vertices, v*48+32)[0]
                    struct.pack_into('<f', self.vertices, v*48+32, (u % 1.0+tile)*0.25)

    def convert(self):
        data = bytearray(super().convert())
        count, at = retail_m2.arr(data, 0x5C)
        types = self.texture_types()
        for i in range(count):
            kind = types[i]
            if kind in (1, 7, 8, 9, 10):
                struct.pack_into('<I', data, at+16*i, 6 if kind == 9 else 8)
        _, lookup = retail_m2.arr(data, 0x7C)
        repl = [0xffff]*14
        for i in range(count):
            kind = struct.unpack_from('<I', data, at+16*i)[0]
            if kind in (1, 2, 6, 8):
                repl[kind] = i
        struct.pack_into('<14H', data, lookup, *repl)
        return bytes(data)


def collection_geoset(row):
    """A collection selector's exact mesh; zero/negative values mean none."""
    return row[1]*100+row[2] if 0 < row[2] < 100 else None


def accessories(storage, tables, custom, entries, dynamic, dragon=False):
    """Convert separate retail hair, beard and mechanical-body meshes."""
    table = tables['skinned']
    defaults = {choices[0] for option in custom.c.options
                if (choices := custom.c.choices(option))}
    requested, seen = [], set()
    for option in custom.c.options:
        choices = custom.c.choices(option)
        variable = option in (custom.alias['Hair Style'], custom.alias['Facial Hair'])
        if option == custom.alias['Hair Style']:
            choices = custom.choices('Hair Style')
        elif option == custom.alias['Facial Hair']:
            choices = custom.choices('Facial Hair')
        for variant, choice in enumerate(choices if variable else choices[:1]):
            for element in custom.c.elements(choice):
                if not element[3] or (element[1] and element[1] not in defaults):
                    continue
                row = table.rows.get(element[3])
                if not row:
                    raise ValueError(f'Absent customization mesh record {element[3]}')
                fid = row[0]
                source_geoset = collection_geoset(row)
                if source_geoset is None:
                    # Zero is the explicit "none" choice, not permission to
                    # import every hairstyle stored in a collection model.
                    continue
                geo = (variant+2 if option == custom.alias['Hair Style'] else
                       102+variant if option == custom.alias['Facial Hair'] else 0)
                if (fid, source_geoset, geo) not in seen:
                    requested.append((fid, source_geoset, geo, option, variant))
                    seen.add((fid, source_geoset, geo))
    result = []
    for fid, source_geoset, geo, option, variant in requested:
        source = required(storage, fid)
        ch = retail_m2.chunks(source) if source[:4] != b'MD20' else {'MD21': source}
        fixed = texture_names(storage, source, entries)
        skel = required(storage, struct.unpack('<I', ch['SKID'])[0]) if 'SKID' in ch else None
        candidates = []
        for lod, skin_id in enumerate(struct.unpack('<'+'I'*(len(ch['SFID'])//4), ch['SFID'])):
            if not skin_id:
                continue
            skin = required(storage, skin_id)
            count, at = retail_m2.arr(skin, 28)
            present = {struct.unpack_from('<H', skin, at+48*i)[0] for i in range(count)}
            if source_geoset not in present:
                continue
            geosets = {source_geoset: 0}
            converter_type = DragonConverter if dragon else retail_m2.Converter
            converter = converter_type(source, skel, skin, f'Customization{fid}', {0}, geosets,
                                       [], dynamic, texture_names=fixed)
            total = converter.index_counts().get(source_geoset, 0)
            if total and total <= 65535:
                candidates.append((total, lod, skin_id, converter))
        if not candidates:
            raise ValueError(f'Customization mesh {fid} has no usable LOD')
        _, lod, skin_id, converter = min(candidates, key=lambda v: (v[0], v[1]))
        output = converter.convert()
        if converter.report['indices']:
            result.append((output, geo, dict(model=fid, source_geoset=source_geoset, lod=lod, skin=skin_id, option=option,
                                             variant=variant, geoset=geo)))
    return result


def convert(storage, game, tables, info, race, sex, cached=None):
    label = ('Male', 'Female')[sex]
    folder, source = info['folder'], info['sexes'][sex]
    custom = Choices(retail_textures.Customization(tables, source['chr_model']), race.id)
    path = f'Character\\{folder}\\{label}\\{folder}{label}.m2'
    entries = dict(cached[0]) if cached else {}
    geosets, hair, facial = mapping(custom)
    if race.id == 52:
        # The dragon's wings are an unconditional region using its third skin
        # material (legacy type 10), rather than a humanoid customization option.
        geosets[4601] = 0
    # Allied/custom body regions extend beyond the original converter's known
    # groups. Select their actual default, including tails and mechanical limbs.
    defaults = {choices[0] for option in custom.c.options if (choices := custom.c.choices(option))}
    for option in custom.c.options:
        if option in (custom.alias['Hair Style'], custom.alias['Facial Hair']):
            continue
        choices = custom.c.choices(option)
        if choices:
            selected_groups = set()
            for element in custom.c.elements(choices[0]):
                if element[1] and element[1] not in defaults:
                    continue
                g = tables['geoset'].rows.get(element[2])
                if g and g[0] >= 16 and 0 < g[1] < 100 and g[0] not in selected_groups:
                    selected_groups.add(g[0])
                    ident = g[0]*100+g[1]
                    geosets = {k: v for k, v in geosets.items() if k//100 != g[0]}
                    geosets[ident] = 0
    model = required(storage, source['model'])
    ch = retail_m2.chunks(model) if model[:4] != b'MD20' else {'MD21': model}
    skel_id = struct.unpack('<I', ch['SKID'])[0] if 'SKID' in ch else None
    skeleton = required(storage, skel_id) if skel_id else None
    keep, playable = vanilla_animations(game, label)
    fixed = texture_names(storage, model, entries)
    builder_type = DragonTextures if race.id == 52 else Textures
    dragon_atlas = f'Character\\{folder}\\{folder}{label}SkinExtra00_00.blp'
    reuse = cached and race.id != 28 and (race.id != 52 or dragon_atlas in entries)
    textures = cached[1] if reuse else builder_type(storage, custom, race.id, sex, f'Character\\{folder}', folder+label,
                        list(range(len(custom.choices('Hair Style')))),
                        len(custom.choices('Facial Hair')), shared_hair=False).build()
    if reuse:
        textures.files = {}
        textures.rows = [r for r in textures.rows if
                         (r[2] != 3 or r[3] < custom.counts['Hair Style']) and
                         (r[2] != 2 or r[3] < custom.counts['Facial Hair'])]
        eye = f'Character\\{folder}\\{folder}{label}Eyes.blp'
        textures.eye_texture = eye if eye in entries else None
    entries.update(textures.files)
    dynamic = {}
    if textures.eye_texture:
        dynamic[19] = textures.eye_texture
    # Resolve default race-specific materials (jewelry, mechanical parts, etc.)
    # by their texture targets. Do not render unsupported types as white skin.
    targets = {}
    for option in custom.c.options:
        choices = custom.c.choices(option)
        if not choices:
            continue
        for element in custom.c.elements(choices[0]):
            material = tables['material'].rows.get(element[4])
            if material:
                if element[1] and element[1] not in defaults:
                    continue
                fid = custom.c.files.get(material[1])
                if fid:
                    targets.setdefault(material[0], fid)
    for kind, target in ((19, 25), (20, 38), (21, 39), (22, 40), (23, 41)):
        if target in targets:
            name = f'ASR\\Race{race.id}\\{label}Material{target}.blp'
            if name not in entries:
                data = required(storage, targets[target])
                entries[name] = blp.encode(blp.decode(data, retail_textures.level_for(data, 256)))
            dynamic[kind] = name
    if not any(custom.texture(choice, 2) for choice in custom.choices('Skin Color')) and 2 in targets:
        name = f'ASR\\Race{race.id}\\{label}DefaultExtra.blp'
        if name not in entries:
            data = required(storage, targets[2])
            entries[name] = blp.encode(blp.decode(data, retail_textures.level_for(data, 256)))
        dynamic[8] = name
    extra_models = accessories(storage, tables, custom, entries, dynamic, dragon=race.id == 52)
    extra_budget = sum(retail_m2.arr(data, retail_m2.arr(data, 0x4C)[1]+8)[0] for data, _, _ in extra_models)
    if 'SFID' not in ch:
        raise ValueError('No skin FileDataID array')
    chosen = None
    for lod, skin_id in enumerate(struct.unpack('<'+'I'*(len(ch['SFID'])//4), ch['SFID'])):
        if not skin_id:
            continue
        skin = required(storage, skin_id)
        converter_type = DragonConverter if race.id == 52 else retail_m2.Converter
        converter = converter_type(model, skeleton, skin, folder+label, keep, geosets,
                                       playable, dynamic, texture_names=fixed)
        total = sum(n for g, n in converter.index_counts().items() if g in geosets)
        if total+extra_budget <= 65535:
            chosen = (lod, skin_id, converter)
            break
    if chosen is None:
        raise ValueError('No complete customization LOD fits the legacy view limit')
    lod, skin_id, converter = chosen
    output = converter.convert()
    accessory_report = []
    for extra, geo, info_extra in extra_models:
        output, merged = merge_accessory(output, extra, geo)
        accessory_report.append(dict(**info_extra, **merged))
        if info_extra['option'] == custom.alias['Hair Style']:
            hair[info_extra['variant']] = (info_extra['variant'], geo)
        elif info_extra['option'] == custom.alias['Facial Hair']:
            variation = info_extra['variant']
            facial[variation] = (variation, [geo-100, 0, 0])
    present = validate_model(output, path)
    if not converter.report['batches'] or not converter.report['indices']:
        raise ValueError('Empty converted character')
    entries[path] = output
    # mapping() supports multiple facial-geoset groups; retain them all.
    textures.hair_geosets = [(v, g if g in present else 0) for v, g in hair] or [(0, 0)]
    facial = [(v, [p if group+p in present else 0 for group, p in zip((100, 300, 200), picks)])
              for v, picks in facial] or [(0, [0, 0, 0])]
    return entries, dict(path=path, model=source['model'], chr_model=source['chr_model'],
                         skeleton=skel_id, skin=skin_id, lod=lod, accessories=accessory_report,
                         **converter.report), textures, facial


def add_rows(dbcs, race, info, converted):
    """Add race/display/customization identities with deterministic private displays."""
    races = dbcs['ChrRaces']
    old = next((r for r in races.rows() if r[0] == race.id), None)
    if old and race.id != 9:
        raise ValueError(f'Race {race.id} is already present; use the original input W')
    if old:
        races.records = [b for b in races.records if struct.unpack_from('<I', b)[0] != race.id]
    row = list(next(r for r in races.rows() if r[0] == 1))
    row[0], row[4], row[5] = race.id, 200000+race.id*2, 200001+race.id*2
    row[2] = next(r for r in races.rows() if r[0] == (5 if race.faction == 'horde' else 1))[2]
    row[6], row[15], row[16] = info['prefix'], info['folder'], 0
    row[17:25] = [race.name]+[0]*7
    races.add(row)
    base = dbcs['CharBaseInfo']
    classes = sorted({b[1] for b in base.records if b[0] == race.template})
    base.records = [b for b in base.records if b[0] != race.id]
    for cls in classes:
        base.add_raw(bytes((race.id, cls)))
    for name, column in (('CharSections', 1), ('CharHairGeosets', 1), ('CharacterFacialHairStyles', 0)):
        table = dbcs[name]
        table.records = [b for b in table.records if struct.unpack_from('<I', b, column*4)[0] != race.id]
    displays, models = dbcs['CreatureDisplayInfo'], dbcs['CreatureModelData']
    for sex, (report, textures, facial) in converted.items():
        display_id = row[4+sex]
        if any(r[0] == display_id for r in displays.rows()):
            raise ValueError(f'Conflicting display ID {display_id}')
        display = list(next(r for r in displays.rows() if r[0] == (49 if sex == 0 else 50)))
        model = list(next(r for r in models.rows() if r[0] == display[1]))
        model[0], model[2] = models.next_id(), report['path'][:-3]+'.mdx'
        models.add(model)
        display[0], display[1], display[6:9] = display_id, model[0], [0, 0, 0]
        displays.add(display)
        sections, hair = dbcs['CharSections'], dbcs['CharHairGeosets']
        for rid, s, kind, variation, color, *paths in textures.rows:
            sections.add([sections.next_id(), rid, s, kind, variation, color, *paths, 0])
        for variation, geoset in textures.hair_geosets:
            hair.add([hair.next_id(), race.id, sex, variation, geoset, 0])
        for variation, picks in facial:
            dbcs['CharacterFacialHairStyles'].add([race.id, sex, variation, 0, 0, 0, *picks])
    return classes


def prepare(retail, installed, names_path, out):
    storage, game = casc.Casc(retail), Chain(installed)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = dict(retail_build=storage.version, characters={}, failures={}, races={})
    try:
        names = listfile(names_path)
        resolved = resolve(storage, names)
        tables = {k: db2.Table(required(storage, fid)) for k, fid in retail_textures.TABLES.items()}
        tables['skinned'] = db2.Table(required(storage, 3460183))
        # Preserve the installed upgraded base roster and all supporting assets.
        base_archive = (installed/'patch-W.MPQ').read_bytes()
        report['base_race_archive_sha256'] = hashlib.sha256(base_archive).hexdigest()
        blobs = read_stored(base_archive)
        entries = dict(zip(blobs[0].decode('ascii').splitlines(), blobs[1:], strict=True))
        dbcs = {name: Dbc(game.read(dbc_name(name))) for name in TABLE_NAMES}
        for race in ADDITIONS:
            info, converted, race_entries = resolved[race.id], {}, {}
            for sex, label in enumerate(('Male', 'Female')):
                key = info['folder']+label
                print(f'Converting {key}...', flush=True)
                checkpoint = out.parent/'characters'/key
                try:
                    marker = checkpoint/'report.json'
                    if marker.exists():
                        saved = json.loads(marker.read_text())
                        if saved['retail_build'] != storage.version or saved['source'] != info['sexes'][sex]:
                            raise ValueError('Stale character checkpoint; remove it before rebuilding')
                        result = saved['character']
                        files = {p: (checkpoint/'files'/p.replace('\\', '/')).read_bytes() for p in saved['files']}
                        if any(hashlib.sha256(files[p]).hexdigest() != h for p, h in saved['files'].items()):
                            raise ValueError('Character checkpoint hash mismatch')
                        textures = type('SavedTextures', (), saved['textures'])()
                        facial = saved['facial']
                        if saved.get('mesh_revision') != (8 if race.id in (28, 31) else 7):
                            files, result, textures, facial = convert(storage, game, tables, info, race, sex,
                                                                     cached=(files, textures))
                    else:
                        files, result, textures, facial = convert(storage, game, tables, info, race, sex)
                    for path, data in files.items():
                        dest = checkpoint/'files'/path.replace('\\', '/')
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                    marker.write_text(json.dumps(dict(retail_build=storage.version, source=info['sexes'][sex],
                        mesh_revision=(8 if race.id in (28, 31) else 7), character=result, files={p: hashlib.sha256(b).hexdigest() for p, b in files.items()},
                        textures=dict(rows=textures.rows, hair_geosets=textures.hair_geosets), facial=facial), indent=2))
                    race_entries.update(files)
                    converted[sex] = (result, textures, facial)
                    report['characters'][key] = result
                except (ValueError, KeyError, PermissionError, struct.error) as error:
                    report['failures'][key] = str(error)
                    print(f'FAILED {key}: {error}', flush=True)
            if len(converted) == 2:
                classes = add_rows(dbcs, race, info, converted)
                entries.update(race_entries)
                report['races'][race.id] = dict(**info, classes=classes, template=race.template, faction=race.faction)
        (out.parent/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
        if report['failures']:
            raise ValueError(f'{len(report["failures"])} character conversions failed; no playable archive emitted')
        for name, table in dbcs.items():
            entries[dbc_name(name)] = table.bytes()
        entries[RACE_ATLAS], report['portraits'] = portraits(storage, game, names, resolved)
        from character_preview import fit_characters
        report['preview_cameras'] = fit_characters(entries)
        lower = {p.lower(): b for p, b in entries.items()}
        for path, data in entries.items():
            if path.lower().endswith('.m2'):
                validate_model(data, path)
                for dependency in dependencies(path, data):
                    if dependency.lower() not in lower and game.read(dependency) is None:
                        raise ValueError(f'{path}: missing {dependency}')
        archive = build(entries)
        if read_stored(archive)[1:] != [b for _, b in sorted(entries.items())]:
            raise ValueError('Race archive failed read-back verification')
        report['assets'] = {p: hashlib.sha256(b).hexdigest() for p, b in sorted(entries.items())}
        report['files'] = len(entries)
        out.write_bytes(archive)
        out.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Built {out}: {len(entries)} files', flush=True)
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
    prepare(args.retail, args.installed, args.listfile, args.out)
