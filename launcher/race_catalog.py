"""Requested ASR roster, resolved against the installed retail DB2/listfile data.

IDs are WoW race IDs; model IDs must come from ChrRaceXChrModel, never arithmetic.
Neutral races use one saved identity and can appear in both faction picker groups.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Race:
    id: int
    name: str
    template: int
    faction: str


ADDITIONS = (
    Race(22, 'Worgen', 1, 'alliance'),
    Race(32, 'Kul Tiran', 1, 'alliance'),
    Race(11, 'Draenei', 1, 'alliance'),
    Race(84, 'Earthen', 3, 'neutral'),
    Race(34, 'Dark Iron Dwarf', 3, 'alliance'),
    Race(30, 'Lightforged Draenei', 1, 'alliance'),
    Race(29, 'Void Elf', 10, 'alliance'),
    Race(37, 'Mechagnome', 7, 'alliance'),
    Race(52, 'Dracthyr', 10, 'neutral'),
    Race(86, 'Haranir', 4, 'neutral'),
    Race(27, 'Nightborne', 4, 'horde'),
    Race(28, 'Highmountain Tauren', 6, 'horde'),
    Race(36, "Mag'har Orc", 2, 'horde'),
    Race(31, 'Zandalari Troll', 8, 'horde'),
    Race(35, 'Vulpera', 8, 'horde'),
    Race(24, 'Pandaren', 1, 'neutral'),
    Race(9, 'Goblin', 7, 'horde'),
)

BY_ID = {r.id: r for r in ADDITIONS}
BASE_IDS = (1, 2, 3, 4, 5, 6, 7, 8, 10)
PLAYABLE_IDS = (*BASE_IDS, *(r.id for r in ADDITIONS))
LEGACY_PORTRAITS = {1: (0, 0), 3: (64, 0), 4: (128, 0), 7: (192, 0),
                    2: (0, 64), 5: (64, 64), 6: (128, 64), 8: (192, 64), 10: (256, 64)}
_free_portraits = [(x, y) for y in (0, 64) for x in range(0, 1024, 64)
                   if (x, y) not in LEGACY_PORTRAITS.values()]
PORTRAITS = {**LEGACY_PORTRAITS, **{r.id: xy for r, xy in zip(ADDITIONS, _free_portraits)}}


def resolve(storage, names):
    """Return verified model/customization metadata, without modifying either game."""
    import db2
    races = db2.Table(storage.read(names['dbfilesclient/chrraces.db2']))
    links = db2.Table(storage.read(names['dbfilesclient/chrracexchrmodel.db2']))
    models = db2.Table(storage.read(names['dbfilesclient/chrmodel.db2']))
    result = {}
    for race in ADDITIONS:
        if race.id not in races.rows or races.string(race.id, 2) != race.name:
            raise ValueError(f'Retail race identity changed: {race.name}')
        folder, prefix = races.string(race.id, 1), races.string(race.id, 0)
        sexes = {}
        for sex, label in enumerate(('Male', 'Female')):
            matches = [v[1] for v in links.rows.values() if v[0] == race.id and v[2] == sex]
            if len(matches) != 1:
                raise ValueError(f'{race.name} {label}: ambiguous ChrRaceXChrModel')
            chr_model = matches[0]
            source_folder = 'Orc' if race.id == 36 else folder
            stem = f'character/{source_folder}/{label}/{source_folder}{label}'.lower()
            flat = f'character/{source_folder}/{source_folder}{label}'.lower()
            paths = (stem+'_hd.m2', stem+'.m2', flat+'.m2')
            # Both Dracthyr body-type selectors share the dragon mesh. The
            # sex-specific files are visage meshes and must not stand in for it.
            if race.id == 52:
                paths = ('character/dracthyr/dracthyrdragon.m2',)
            candidates = [names[p] for p in paths if p in names]
            model = next((fid for fid in candidates if storage.read(fid) is not None), None)
            if model is None:
                raise ValueError(f'{race.name} {label}: no available retail model')
            sexes[sex] = dict(model=model, chr_model=chr_model,
                              texture_layout=models.rows[chr_model][5])
        result[race.id] = dict(name=race.name, folder=folder, prefix=prefix, sexes=sexes)
    return result
