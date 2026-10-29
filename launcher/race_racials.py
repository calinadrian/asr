"""Race-specific survival passives, adapted to ASR's native combat stats.

These are ASR adaptations, not retail spell implementations. The tooltip names
the exact effect applied by the native passive dispatcher. No gathering,
damage-school restriction, conditional proc or pet mechanic is claimed.
"""
from dataclasses import dataclass
import struct

REVISION = 2
# Reviewed native stat kinds; the dispatcher is at RVA 0x5be93fd.
STATS = {0: 'max health', 1: 'damage', 2: 'cooldown reduction',
         3: 'movement speed', 4: 'critical strike chance', 5: 'damage reduction',
         6: 'health per second', 7: 'pickup range', 8: 'experience',
         9: 'gold', 10: 'luck', 11: 'health per kill'}


@dataclass(frozen=True)
class Trait:
    name: str
    kind: int
    value: float

    @property
    def line(self):
        if self.kind in (6, 11):
            effect = f'+{self.value:g} {STATS[self.kind]}'
        elif self.kind == 2:
            effect = f'-{self.value*100:g}% cooldowns'
        else:
            effect = f'+{self.value*100:g}% {STATS[self.kind]}'
        return f'{self.name}: {effect}'


def traits(*rows):
    return tuple(Trait(*row) for row in rows)


KITS = {
    22: traits(('Viciousness', 4, .03), ('Running Wild', 3, .08), ('Aberration', 5, .04)),
    32: traits(('Brush It Off', 6, .8), ('Rime of the Ancient Mariner', 5, .05),
               ('Jack of All Trades', 10, .10)),
    11: traits(('Heroic Presence', 1, .06), ('Gift of the Naaru', 6, 1), ('Shadow Resistance', 5, .04)),
    84: traits(('Titan-Wrought Frame', 5, .06), ('Ingest Minerals', 0, .08), ('Wide-Eyed Wonder', 8, .12)),
    34: traits(('Forged in Flames', 5, .05), ('Dungeon Delver', 3, .06), ('Mass Production', 2, .05)),
    30: traits(('Demonbane', 1, .07), ('Holy Providence', 6, 1), ('Forge of Light', 0, .08)),
    29: traits(('Entropic Embrace', 1, .08), ('Preternatural Calm', 2, .06), ('Chill of Night', 5, .04)),
    37: traits(('Combat Analysis', 1, .06), ('Re-Arm', 6, 1.2), ('Skeleton Pinkie', 9, .15)),
    52: traits(('Awakened', 4, .03), ('Discerning Eye', 7, .25), ('Glide', 3, .08)),
    86: traits(('Subterranean Predator', 8, .10), ('Lash Out', 4, .03), ('One with Nature', 7, .25)),
    27: traits(('Magical Affinity', 1, .08), ('Ancient History', 8, .08), ('Arcane Resistance', 5, .04)),
    28: traits(('Rugged Tenacity', 5, .06), ('Mountaineer', 0, .10), ('Waste Not, Want Not', 9, .15)),
    36: traits(('Ancestral Call', 1, .06), ('Savage Blood', 5, .05), ('Sympathetic Vigor', 0, .10)),
    31: traits(("Embrace of Pa'ku", 4, .03), ('City of Gold', 9, .20), ("Regeneratin'", 6, 1)),
    35: traits(('Nose for Trouble', 5, .05), ('Alpaca Saddlebags', 7, .35), ('Bag of Tricks', 10, .15)),
    24: traits(('Epicurean', 0, .12), ('Inner Peace', 8, .10), ('Bouncy', 5, .05)),
    9: traits(('Time is Money', 2, .07), ('Best Deals Anywhere', 9, .20),
              ('Better Living Through Chemistry', 6, .8)),
}


def patch_record(image, at, race_id):
    kit = KITS[race_id]
    effects = image.put(b''.join(struct.pack('<If', t.kind, t.value) for t in kit), 4)
    image.pointer(at+32, effects)
    struct.pack_into('<Q', image.payload, at-image.rva+40, len(kit))
    # New races are passive-only: never inherit another race's active timer/proc.
    image.text(at+48, '')
    lines = image.put(bytes(len(kit)*16))
    for index, trait in enumerate(kit):
        image.text(lines+index*16, trait.line)
    image.pointer(at+64, lines)
    struct.pack_into('<Q', image.payload, at-image.rva+72, len(kit))


def manifest():
    return {str(rid): [{'name': t.name, 'kind': t.kind, 'value': t.value, 'line': t.line}
                      for t in kit] for rid, kit in KITS.items()}


def allow_passive_only_races(image, profile):
    """Supply a harmless definition for the legacy mandatory racial slot.

    Several native call sites inline the ability lookup. A catalog sentinel is
    therefore required; patching only the
    standalone resolver does not cover the co-op simulation's inlined lookup.
    """
    from durotar_patch import Code
    p = profile['abilities']
    old = image.lea(p['refs'][1])
    count, stride = p['count']+1, p['record']
    source = image.read(old, count*stride)
    template = None
    for index in range(count):
        ptr, size = struct.unpack_from('<QQ', source, index*stride)
        if image.read(ptr-image.base, size) == b'perception':
            template = source[index*stride:(index+1)*stride]
    if template is None:
        raise ValueError('No supported native ability display template')
    catalog = image.put(source+template)
    for index in range(count+1):
        for delta in (0, 16, 32, 48):
            image.relocations.append(catalog+index*stride+delta)
    empty = catalog+count*stride
    image.text(empty, '')
    image.text(empty+16, 'Racial Traits')
    offset = empty-image.rva
    struct.pack_into('<I', image.payload, offset+64, 0)
    image.payload[offset+68:offset+116] = bytes(48)
    struct.pack_into('<f', image.payload, offset+72, 1e9)
    for site in p['refs']:
        delta = image.lea(site)-old
        if delta not in (0, 120, 240):
            raise ValueError('Unsupported native ability reference')
        image.retarget(site, catalog+delta)
    for site in p['bounds']:
        if image.read(site, 4) != struct.pack('<I', count*stride):
            raise ValueError('Unsupported native ability catalog bound')
        image.edit(site, struct.pack('<I', (count+1)*stride))
