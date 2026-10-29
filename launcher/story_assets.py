"""Build the story-chapter archive (patch-S.MPQ) from a vanilla 1.12.1 Data folder.

Covers the chapter zones defined in story_chapters.ZONES: their terrain tiles
(with every WMO, doodad and texture they reference), creature models and
textures, minimap tiles and card artwork. Like durotar_assets.py, only files
the installed game lacks are added; existing shared assets are preserved.
"""
import argparse
import hashlib
import json
from pathlib import Path

from durotar_assets import Chain, canonical, creature_assets, dependencies
from photo_archive import build, read_stored
from story_chapters import ZONES

ARCHIVE = 'patch-S.MPQ'
TILE = 1600/3


def tiles(zone):
    """The 3x3 terrain tiles around a zone's centre, or every tile of an instance."""
    folder = zone['map_folder']
    if 'all_tiles' in zone:
        return [(x, y) for x in zone['all_tiles'][0] for y in zone['all_tiles'][1]]
    x, y, _ = zone['center']
    tx, ty = int(32-y/TILE), int(32-x/TILE)
    return [(a, b) for a in range(tx-1, tx+2) for b in range(ty-1, ty+2)]


def prepare(source, installed):
    vanilla, game = Chain(source), Chain(installed, exclude=(ARCHIVE,))
    pending, entries = [], {}
    translations = vanilla.read('Textures\\Minimap\\md5translate.trs').decode('ascii')
    minimap = {}
    for line in translations.splitlines():
        parts = line.split('\t')
        if len(parts) == 2:
            minimap[parts[0].lower()] = parts[1]
    for zone in ZONES.values():
        folder = zone['map_folder']
        if 'all_tiles' in zone:
            pending.append(f'World\\Maps\\{folder}\\{folder}.wdt')
        for x, y in tiles(zone):
            name = f'World\\Maps\\{folder}\\{folder}_{x}_{y}.adt'
            if vanilla.read(name) is None and game.read(name) is None:
                continue  # the map has no tile there
            pending.append(name)
            texture = minimap.get(f'{folder.lower()}\\map{x}_{y}.blp')
            if texture:
                pending.append('Textures\\Minimap\\' + texture)
        displays = [d for _, d in zone['enemies']]+[d for _, d in zone['bosses']]
        pending += list(creature_assets(vanilla, displays))
        if zone.get('card_source'):
            card = vanilla.read(f"Interface\\Glues\\LoadingScreens\\{zone['card_source']}.blp")
            if card is None:
                raise ValueError(f"Vanilla loading-screen artwork is missing: {zone['card_source']}")
            entries[f"Interface\\ASR\\zone-photos_____\\{zone['card']}.blp"] = card
    for _, display in (d for zone in ZONES.values() for d in zone.get('retitled_bosses', ())):
        pending += list(creature_assets(vanilla, [display]))
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
        # Interior minimaps are keyed by WMO group, not ADT tile coordinates.
        if name.lower().startswith('world\\') and name.lower().endswith('.wmo'):
            prefix = name[6:-4].lower()+'_'
            pending.extend('Textures\\Minimap\\'+texture for key,texture in minimap.items() if key.startswith(prefix))
    if missing:
        raise ValueError('Missing asset dependencies: ' + ', '.join(sorted(missing)))
    archive = build(entries)
    vanilla.close()
    game.close()
    restored = read_stored(archive)
    # build() adds the listfile first, followed by entries in sorted order.
    if restored[1:] != [value for _, value in sorted(entries.items())]:
        raise ValueError('Story archive failed read-back verification')
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
    args.out.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Built {args.out}: {report["added"]} assets, {report["checked"]} dependencies checked, {len(archive):,} bytes')
