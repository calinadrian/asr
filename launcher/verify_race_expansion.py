"""Verify all 26 native race identities and the complete staged asset closure."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from bloodelf_assets import Dbc, dbc_name, RACE_ATLAS
from durotar_assets import Chain, dependencies
from photo_archive import read_stored
from race_catalog import ADDITIONS, BASE_IDS, PLAYABLE_IDS
from race_patch import Image, existing
from verify_character_upgrade import model


def verify(candidate, installed):
    entries, reports = {}, {}
    for letter in ('V', 'W'):
        archive = candidate/f'patch-{letter}.MPQ'
        report = json.loads(archive.with_suffix('.json').read_text())
        blobs = read_stored(archive.read_bytes())
        names = blobs[0].decode('ascii').splitlines()
        if names != sorted(report['assets']) or len(names) != len(blobs)-1:
            raise ValueError(f'{archive.name}: listfile/manifest mismatch')
        for path, data in zip(names, blobs[1:], strict=True):
            if hashlib.sha256(data).hexdigest() != report['assets'][path]:
                raise ValueError(f'{path}: manifest hash mismatch')
            if path.lower() in entries and entries[path.lower()] != data:
                raise ValueError(f'Conflicting archive entries: {path}')
            entries[path.lower()] = data
        reports[letter] = report
    if reports['W'].get('failures') or len(reports['W']['characters']) != 34:
        raise ValueError('All 34 new characters must convert successfully')
    game = Chain(installed)
    try:
        def read(path):
            return entries.get(path.lower()) or game.read(path)
        def table(name):
            return Dbc(read(dbc_name(name)))
        models = {}
        for path, data in entries.items():
            if path.endswith('.m2'):
                models[path] = model(data, path)
                for dependency in dependencies(path, data):
                    if read(dependency) is None:
                        raise ValueError(f'{path}: missing {dependency}')
        races = table('ChrRaces')
        by_race = {r[0]: r for r in races.rows()}
        if not set(PLAYABLE_IDS) <= by_race.keys():
            raise ValueError('Race DBC does not contain the complete roster')
        displays = {r[0]: r for r in table('CreatureDisplayInfo').rows()}
        model_table = table('CreatureModelData')
        model_rows = {r[0]: r for r in model_table.rows()}
        sections, hair, facial = (table(n) for n in ('CharSections', 'CharHairGeosets', 'CharacterFacialHairStyles'))
        classes = table('CharBaseInfo')
        catalog = reports['W']['races']
        for spec in ADDITIONS:
            rid = spec.id
            row = by_race[rid]
            info = catalog[str(rid)]
            if races.string(row[17]) != spec.name or races.string(row[6]) != info['prefix']:
                raise ValueError(f'Race {rid}: wrong name or equipment prefix')
            actual_classes = sorted(b[1] for b in classes.records if b[0] == rid)
            if actual_classes != info['classes']:
                raise ValueError(f'Race {rid}: class DBC differs from native specification')
            for sex in (0, 1):
                display = displays[row[4+sex]]
                path = model_table.string(model_rows[display[1]][2])[:-4]+'.m2'
                geosets = models[path.lower()]
                sex_rows = [r for r in sections.rows() if r[1:3] == (rid, sex)]
                if {r[3] for r in sex_rows} != set(range(5)):
                    raise ValueError(f'{path}: missing native customization category')
                keys = [r[3:6] for r in sex_rows]
                if len(keys) != len(set(keys)):
                    raise ValueError(f'{path}: ambiguous customization key')
                for r in sex_rows:
                    for offset in r[6:9]:
                        if offset and read(sections.string(offset)) is None:
                            raise ValueError(f'{path}: missing customization texture')
                for r in hair.rows():
                    if r[1:3] == (rid, sex) and r[4] > 1 and r[4] not in geosets:
                        raise ValueError(f'{path}: hairstyle {r[3]} names an absent geoset')
                for r in facial.rows():
                    if r[:2] == (rid, sex):
                        if any(v and group+v not in geosets for group, v in zip((100, 300, 200), r[6:9])):
                            raise ValueError(f'{path}: facial style {r[2]} names an absent geoset')
        # Existing player customizations survive byte-for-byte. String blocks
        # only grow, so their old string offsets remain meaningful as well.
        for name, race_col in (('CharSections', 1), ('CharHairGeosets', 1), ('CharacterFacialHairStyles', 0)):
            before = Dbc(game.read(dbc_name(name)))
            after = table(name)
            old = [b for b in before.records if struct.unpack_from('<I', b, race_col*4)[0] in BASE_IDS]
            new = [b for b in after.records if struct.unpack_from('<I', b, race_col*4)[0] in BASE_IDS]
            if old != new:
                raise ValueError(f'{name}: changed an existing player customization')
        if struct.unpack_from('<II', read(RACE_ATLAS), 12) != (1024, 256):
            raise ValueError('Unexpected expanded race atlas dimensions')
        exe = (candidate/'ASR.exe').read_bytes()
        native = existing(exe)
        if not native or native.get('fixture_only'):
            raise ValueError('Executable is not a validated expanded-roster candidate')
        import race_racials
        if (native.get('racial_revision') != race_racials.REVISION
                or native.get('racials') != race_racials.manifest()):
            raise ValueError('Executable lacks the current race-specific passive kits')
        for rid, data in native['catalog'].items():
            if data != catalog[rid]:
                raise ValueError('Native race specifications differ from the asset build')
        image = Image(exe)
        import bloodelf_patch
        pointer, count = struct.unpack('<QQ', image.read(bloodelf_patch.PROFILE['races']['slice'], 16))
        ids = [struct.unpack('<Q', image.read(pointer-image.base+i*88+80, 8))[0] for i in range(count)]
        if ids != list(PLAYABLE_IDS):
            raise ValueError('Native roster order differs')
        return dict(races=count, new_characters=34, character_models=52, models=len(models), assets=len(entries),
                    racial_passive_kits=len(race_racials.KITS),
                    helmet_variants=len(reports['V']['helmets']), unsupported_helmets=len(reports['V']['unsupported']),
                    sha256={n: hashlib.sha256((candidate/n).read_bytes()).hexdigest()
                            for n in ('ASR.exe', 'patch-W.MPQ', 'patch-V.MPQ')})
    finally:
        game.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.candidate, args.installed)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
