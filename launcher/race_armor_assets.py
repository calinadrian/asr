"""Add supported helmet variants for the expanded roster to the existing V archive.

Newer races reuse some equipment meshes in retail. Those explicit shared-rig
aliases are recorded; unrelated race meshes are never substituted. Dragon-form
Dracthyr do not receive humanoid helmet substitutes.
"""
import argparse
import hashlib
import json
from pathlib import Path

from armor_upgrade import ALIASES, HEAD, convert
from bloodelf_assets import Dbc, dbc_name
import casc
from character_upgrade import listfile
from durotar_assets import Chain
from photo_archive import build, read_stored
from race_catalog import ADDITIONS, resolve

SHARED_HELMETS = {84: 'Dw', 34: 'Dw', 30: 'Dr', 29: 'Be', 37: 'Gn',
                  27: 'Ni', 28: 'Ta', 36: 'Or', 86: 'Ni'}


def prepare(retail, installed, names_path, out):
    storage, game = casc.Casc(retail), Chain(installed)
    report = dict(helmets=[], unsupported=[], assets={})
    try:
        names = listfile(names_path)
        catalog = resolve(storage, names)
        original = (installed/'patch-V.MPQ').read_bytes()
        report['base_armor_archive_sha256'] = hashlib.sha256(original).hexdigest()
        blobs = read_stored(original)
        entries = dict(zip(blobs[0].decode('ascii').splitlines(), blobs[1:], strict=True))
        displays = Dbc(game.read(dbc_name('ItemDisplayInfo')))
        heads = sorted({displays.string(row[1])[:-4] for row in displays.rows()
                        if row[1] and displays.string(row[1]).lower().startswith('helm')})
        cache = {}
        for race in ADDITIONS:
            prefix = catalog[race.id]['prefix']
            print(f'Helmet variants: {race.name}', flush=True)
            for stem in heads:
                source_stem = ALIASES.get(stem.lower(), stem)
                for sex in ('M', 'F'):
                    destination = HEAD+f'{stem}_{prefix}{sex}.m2'
                    if race.id == 52:
                        report['unsupported'].append(dict(path=destination, reason='Dragon form has no legacy humanoid helmet mesh'))
                        continue
                    aliases = [prefix]
                    if race.id in SHARED_HELMETS:
                        aliases.append(SHARED_HELMETS[race.id])
                    if race.id == 31 and sex == 'F':
                        aliases.append('Tr')
                    candidates = [HEAD+f'{source_stem}_{p}{sep}{sex}.m2'
                                  for p in aliases for sep in ('', '_')]
                    if stem.lower() == 'helm_goggles_b_04':
                        candidates.append(HEAD+stem+'.m2')
                    found = False
                    errors = []
                    for path in candidates:
                        fid = names.get(path.lower().replace('\\', '/'))
                        if not fid:
                            continue
                        try:
                            if fid not in cache:
                                cache[fid] = convert(storage, fid, entries)
                            entries[destination] = cache[fid]
                            report['helmets'].append(dict(path=destination, source=path, file_id=fid,
                                                          shared_rig=not path.lower().endswith((f'_{prefix}{sex}.m2'.lower(),
                                                                                              f'_{prefix}_{sex}.m2'.lower()))))
                            found = True
                            break
                        except (ValueError, PermissionError) as error:
                            errors.append(str(error))
                    if not found:
                        report['unsupported'].append(dict(path=destination, reason='; '.join(errors) or 'No compatible retail source'))
        report['files'] = len(entries)
        report['assets'] = {p: hashlib.sha256(b).hexdigest() for p, b in sorted(entries.items())}
        archive = build(entries)
        if read_stored(archive)[1:] != [b for _, b in sorted(entries.items())]:
            raise ValueError('Expanded helmet archive failed read-back')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(archive)
        out.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
        print(f'Built {out}: {len(report["helmets"])} new variants; {len(report["unsupported"])} unsupported', flush=True)
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
