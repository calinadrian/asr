"""The branching story: faction chapters that meet in Stranglethorn Vale.

Alliance: Elwynn Forest > Westfall > The Deadmines > Duskwood > Stranglethorn Vale
Horde:    Durotar > The Barrens > Wailing Caverns > Stonetalon Mountains > Stranglethorn Vale
Both factions then continue together through the original zone order.

Applied by starter_missions.apply() on the same final payload. The six new zones
are catalog records 13-18. Until their assets exist they are playable stand-ins
that copy a donor zone's terrain, enemies and bosses, and say so on their card.

Progress keeps the native per-class "zones opened" counter and save format. A
chapter opens when its predecessor has a completion record for the class; the
counter advances only when Stranglethorn Vale is cleared, which opens Warsong
Gulch. Older saves keep what they had opened: a counter of 2 (Duskwood reached)
opens the hero's whole faction path, and 3 or more also opens Stranglethorn.

The validator computes an "open zones" bit mask for the hero it checks, with the
hero's faction, into this payload's state; the cards, the Armory, the picker and
the Story panel's hero read it. Co-op ignores zone progress: a guest of any
faction plays the host's map.
"""
import struct

from durotar_patch import Code, PROFILE
import deadmines_ground as ground
import deadmines_arena as arena
import wailing_ground
import stonetalon_zone
import barrens_zone
import stranglethorn_zone
import story_map

# Wailing has overlapping floors. Its 2-D spawn grid must not pull a player
# through rock onto another storey when validating client WMO movement.
WAILING_PLAYER_HEIGHT_SITES = (0x5be8623, 0x5be8a8f)
WAILING_PLAYER_HEIGHT_STEP = 3.0

RECORD, TIER, COUNT = 240, 8, 13
ENEMY_SIZE, BOSS_SIZE = 80, 104
# id, name, chapter subtitle, donor record, scaling/loot index
CHAPTERS = (
    ('westfall', 'Westfall', 'Alliance · Chapter 2', 0, 0),
    ('deadmines', 'The Deadmines', 'Alliance · Chapter 3', 0, 1),
    ('barrens', 'The Barrens', 'Horde · Chapter 2', 12, 0),
    ('wailing', 'Wailing Caverns', 'Horde · Chapter 3', 12, 1),
    ('stonetalon', 'Stonetalon Mountains', 'Horde · Chapter 4', 12, 1),
    ('stv', 'Stranglethorn Vale', 'Together · Chapter 5', 6, 2),
)
INDEX = {chapter[0]: COUNT+i for i, chapter in enumerate(CHAPTERS)}
TOTAL = COUNT+len(CHAPTERS)
ZONE_IDS = ('elwynn', 'duskwood', 'wsg', 'ungoro', 'ab', 'feralas', 'arena', 'sm', 'av', 'brm', 'aq', 'naxx', 'durotar')
DONOR_NAMES = {0: 'Elwynn Forest', 6: 'Gurubashi Arena', 12: 'Durotar'}
ALLIANCE_PATH = (0, INDEX['westfall'], INDEX['deadmines'], 1)
HORDE_PATH = (12, INDEX['barrens'], INDEX['wailing'], INDEX['stonetalon'])
STV = INDEX['stv']
# Dungeons are open to both factions: clearing your own road's chapter 2 opens
# the other road's dungeon too.
DUNGEONS = (ALLIANCE_PATH[2], HORDE_PATH[2])
DUNGEON_LINE = ('Dungeon', (0.72, 0.58, 1.0))
# Picker and Armory order: both chapter rows side by side, then the shared road.
ORDER = (0, 12, ALLIANCE_PATH[1], HORDE_PATH[1], ALLIANCE_PATH[2], HORDE_PATH[2],
         1, HORDE_PATH[3], STV, *range(2, 12))
SCALE = bytes([*range(12), 0, *(chapter[4] for chapter in CHAPTERS)])  # reward, level and loot rank
ACHIEVEMENT_POINTS = (10, 10, 10, 10, 10, 15)
# Victories that no longer advance the counter: every chapter before Stranglethorn.
NO_ADVANCE = (*ALLIANCE_PATH, *HORDE_PATH)
COMPLETED = 0x5aba570  # (progress, class, zone) -> stars; 0 = never cleared
LOOKUP = 0x5ab48d0
ALLOC, COPY = 0x21c0, 0x600ae51


# Built chapter zones: their own terrain, creatures and bosses (patch-S.MPQ,
# from story_assets.py). Centres stand on the ground found in the vanilla maps.
# Enemy and boss creature IDs stay clear of the catalog and Durotar's IDs.
ZONES = {
    'westfall': dict(
        map=0, map_folder='Azeroth', area=40, center=(-10850.0, 900.0, 35.0), music=10,
        card='loadscreenasrwestfall', enemy_id=1620, boss_id=1700,
        blurb='The farms of Westfall lie abandoned. Defias bandits, gnolls and runaway harvest '
              "golems roam the fields while the People's Militia holds Sentinel Hill. Find out "
              'who leads the Brotherhood.',
        enemies=(('Young Goretusk', 377), ('Coyote', 161), ('Riverpaw Gnoll', 174), ('Murloc Coastrunner', 188),
                 ('Defias Trapper', 2335), ('Fleshripper', 410), ('Harvest Watcher', 71), ('Riverpaw Mongrel', 376),
                 ('Defias Smuggler', 2337), ('Murloc Tidehunter', 346), ('Riverpaw Mystic', 204),
                 ('Defias Pathstalker', 2340)),
        bosses=(('Vultros', 507), ('Old Murk-Eye', 391), ('Sergeant Brashclaw', 175),
                ('Foe Reaper 4000', 953), ('Klaven Mortwake', 2073))),
    'deadmines': dict(
        map=36, map_folder='DeadminesInstance', all_tiles=(range(30, 36), range(30, 36)), area=1581,
        center=ground.START, music=12, card='loadscreenasrdeadmines', card_source='LoadScreenDeadmines',
        # Start in the Mast Room, on the level cave floor. Ground lookup
        # and enemy placement use the WMO floor map, including the tunnels.
        ground=ground,
        radius=ground.ARENA_RADIUS, bounds=arena.outline(),
        enemy_id=1640, boss_id=1710,
        blurb='Beneath Moonbrook the Defias Brotherhood builds a warship in secret. Fight through '
              "the mine, the goblin foundry and Ironclad Cove to end Edwin VanCleef's revenge.",
        enemies=(('Defias Strip Miner', 2145), ('Defias Miner', 2311), ('Goblin Woodcarver', 7051),
                 ('Defias Watchman', 2332), ('Goblin Craftsman', 7053), ('Defias Evoker', 2314),
                 ('Defias Taskmaster', 2146), ('Goblin Engineer', 7031), ('Defias Henchman', 2347),
                 ('Remote-Controlled Golem', 2280), ('Defias Pirate', 2350), ('Defias Squallshaper', 4418)),
        bosses=(("Rhahk'Zor", 14403), ("Sneed's Shredder", 1269), ('Gilnid', 7056),
                ('Mr. Smite', 2026), ('Edwin VanCleef', 2029))),
}
ZONES['barrens'] = dict(
    map=1, map_folder='Kalimdor', area=17, center=barrens_zone.START,
    radius=barrens_zone.RADIUS, camps=barrens_zone.CAMPS,
    music=10, card='loadscreenasrbarrens', card_source='LoadScreenKalimdor',
    enemy_id=1800, boss_id=1820,
    blurb="Beyond Durotar, the open savannah stretches around the Crossroads. "
          "Battle Razormane quilboar, Kolkar centaurs and the Barrens' wild beasts, "
          "then face Humar the Pridelord beneath the acacia trees.",
    enemies=(('Greater Plainstrider',178),('Zhevra Runner',6087),('Savannah Huntress',1056),
             ('Sunscale Screecher',1747),('Razormane Water Seeker',1964),
             ('Razormane Thornweaver',6096),('Kolkar Wrangler',9442),
             ('Kolkar Stormer',9443),('Hecklefang Hyena',2710),
             ('Aean Swiftriver',4345),('Hannah Bladeleaf',4348),('Marcus Bel',4347)),
    bosses=(('Barak Kodobane',4874),('Hezrul Bloodmark',9448),('Echeyakee',1934),
            ('Snort the Heckler',2713),('Humar the Pridelord',4424)))
ZONES['wailing'] = dict(
    map=43, map_folder='WailingCaverns', all_tiles=(range(0), range(0)), area=718,
    center=wailing_ground.START, music=12, card='loadscreenasrwailing', card_source='LoadScreenWailingCaverns',
    ground=wailing_ground, radius=wailing_ground.ARENA_RADIUS,
    enemy_id=1660, boss_id=1720,
    blurb="The dreams of Naralex have become a nightmare. Descend into the Wailing Caverns, "
          "face the Druids of the Fang and their twisted beasts, and defeat Mutanus the Devourer.",
    enemies=(('Deviate Coiler',1742),('Deviate Stinglash',4091),('Deviate Creeper',1744),
             ('Deviate Slayer',949),('Deviate Stalker',1746),('Deviate Ravager',1747),
             ('Deviate Guardian',755),('Devouring Ectoplasm',4266),('Evolving Ectoplasm',1751),
             ('Deviate Lurker',1752),('Druid of the Fang',4211),('Nightmare Ectoplasm',470)),
    bosses=(('Lady Anacondra',4313),('Lord Cobrahn',4213),('Lord Pythas',4214),
            ('Lord Serpentis',4215),('Mutanus the Devourer',4088)))
ZONES['stonetalon'] = dict(
    map=1, map_folder='Kalimdor', area=406, center=stonetalon_zone.START,
    radius=stonetalon_zone.RADIUS, camps=stonetalon_zone.CAMPS,
    music=10, card='loadscreenasrstonetalon', card_source='LoadScreenKalimdor',
    enemy_id=1680, boss_id=1730,
    blurb="The Venture Company tears through the forests of Windshear Crag. Fight their "
          "logging crews and war machines, survive Stonetalon's wild creatures, and bring "
          "down Gerenzo Wrenchwhistle before the mountains are stripped bare.",
    enemies=(('Venture Co. Operator',7230),('Venture Co. Logger',7228),
             ('Venture Co. Cutter',7225),('Venture Co. Deforester',7226),
             ('Venture Co. Engineer',7227),('Venture Co. Machine Smith',7229),
             ('Windshear Tunnel Rat',373),('Deepmoss Creeper',760),
             ('Deepmoss Webspinner',1989),('Pridewing Wyvern',295),
             ('Venture Co. Shredder',1269),('Windshear Geomancer',163)),
    bosses=(('XT:4',1269),('XT:9',1269),('Foreman Rigger',4600),
            ('Taskmaster Whipfang',487),('Gerenzo Wrenchwhistle',3885)))
ZONES['stv'] = dict(
    map=0, map_folder='Azeroth', area=33, center=stranglethorn_zone.START,
    radius=stranglethorn_zone.RADIUS, camps=stranglethorn_zone.CAMPS,
    music=10, card='loadscreenasrstranglethorn', card_source='LoadScreenEasternKingdom',
    enemy_id=1740, boss_id=1760,
    blurb="The roads of Alliance and Horde meet beneath Stranglethorn's jungle canopy. "
          "Survive its great cats and raptors, confront the Skullsplitter and Mosh'Ogg "
          "tribes, and face the legendary King Bangalash.",
    enemies=(('Young Stranglethorn Tiger',598),('Panther',599),('Lashtail Raptor',788),
             ('Elder Stranglethorn Tiger',698),('Shadowmaw Panther',633),
             ('Skullsplitter Scout',4625),('Skullsplitter Mystic',4616),
             ('Skullsplitter Headhunter',4635),('Young Lashtail Raptor',2571),
             ('Kurzen Elite',4446),("Mosh'Ogg Shaman",536),("Mosh'Ogg Lord",11569)),
    bosses=(("Sin'Dall",471),("Bhag'thera",613),('Tethis',8472),
            ('Colonel Kurzen',637),('King Bangalash',616)))
# The Deadmines now owns its bosses; Elwynn's last three become forest bosses.
# (boss slot, name, display), keeping each slot's timing, loot and creature ID.
ELWYNN_BOSSES = ((2, 'Fedfennel', 204), (3, 'Princess', 703), (4, 'Morgan the Collector', 2322))
ZONES['westfall']['retitled_bosses'] = tuple((name, display) for _, name, display in ELWYNN_BOSSES)
ELWYNN_BOSS_ID = 690
YELLS = {
    'Barak Kodobane': 'The Kolkar will trample you!',
    'Hezrul Bloodmark': 'The Bloodmark clan rides to war!',
    'Echeyakee': 'Echeyakee roars across the savannah!',
    'Snort the Heckler': 'Snort the Heckler circles the clearing!',
    'Humar the Pridelord': 'Humar the Pridelord emerges from the shade!',
    "Sin'Dall": "Sin'Dall prowls from the jungle!",
    "Bhag'thera": "Bhag'thera stalks the clearing!",
    'Tethis': 'Tethis charges through the undergrowth!',
    'Colonel Kurzen': 'You will not leave this jungle alive!',
    'King Bangalash': 'King Bangalash answers the challenge!',
    'XT:4': 'XT:4 activates its saw blades!',
    'XT:9': 'XT:9 begins its demolition routine!',
    'Foreman Rigger': 'Back to work! The Venture Company owns this clearing!',
    'Taskmaster Whipfang': 'You will answer to the taskmaster!',
    'Gerenzo Wrenchwhistle': 'These mountains are mine to strip!',
    'Lady Anacondra': 'None can stand against the serpent lords!',
    'Lord Cobrahn': 'You will never wake the dreamer!',
    'Lord Pythas': 'The coils of nightmare tighten around you!',
    'Lord Serpentis': 'The dream will consume you!',
    'Mutanus the Devourer': 'Mutanus rises from the nightmare!',
    'Vultros': 'Vultros shrieks and dives from the sky!',
    'Old Murk-Eye': 'Mrrglglgl! Old Murk-Eye rises from the surf!',
    'Sergeant Brashclaw': 'Riverpaw take farms! You die!',
    'Foe Reaper 4000': 'The Foe Reaper 4000 grinds to life!',
    'Klaven Mortwake': "You'll never find the Brotherhood's leader!",
    "Rhahk'Zor": 'VanCleef pay big for your heads!',
    "Sneed's Shredder": "Sneed's Shredder roars to life!",
    'Gilnid': 'Gilnid fires up the foundry!',
    'Mr. Smite': "We're under attack! Avast, ye swabs! Repel the invaders!",
    'Edwin VanCleef': 'None may challenge the Brotherhood!',
    'Fedfennel': 'Grrr... Riverpaw land!',
    'Princess': 'Princess squeals and charges!',
    'Morgan the Collector': 'Your coin purse looks heavy, friend.',
}


def creature_strings():
    """Locale keys for every story creature: enemy.<id>, boss.<id>.name and .yell."""
    strings = {}
    for zone in ZONES.values():
        for k, (name, _) in enumerate(zone['enemies']):
            strings[f"enemy.{zone['enemy_id']+k}"] = name
        for k, (name, _) in enumerate(zone['bosses']):
            strings[f"boss.{zone['boss_id']+k}.name"] = name
            strings[f"boss.{zone['boss_id']+k}.yell"] = YELLS[name]
    for slot, name, _ in ELWYNN_BOSSES:
        strings[f'boss.{ELWYNN_BOSS_ID+slot}.name'] = name
        strings[f'boss.{ELWYNN_BOSS_ID+slot}.yell'] = YELLS[name]
    return strings


def description(chapter):
    zone, name, _, donor, _ = chapter
    if zone in ZONES:
        return ZONES[zone]['blurb']
    return (f'{name} is still being built. Until then this chapter plays on '
            f'{DONOR_NAMES[donor]}, with its enemies and bosses.')


def next_table():
    """Card order as a successor table: next[i] follows zone i; TOTAL ends the list."""
    table = bytearray(range(1, TOTAL+1))
    for a, b in zip(ORDER, ORDER[1:]):
        table[a] = b
    table[ORDER[-1]] = TOTAL
    return bytes(table)


def predecessors(horde):
    """The zone whose final boss a locked card names."""
    pred = bytearray(max(i-1, 0) for i in range(TOTAL))
    for path in (ALLIANCE_PATH, HORDE_PATH):
        for a, b in zip(path, path[1:]):
            pred[b] = a
    pred[STV] = (HORDE_PATH if horde else ALLIANCE_PATH)[-1]
    road = HORDE_PATH if horde else ALLIANCE_PATH
    for dungeon in DUNGEONS:
        pred[dungeon] = road[1]
    pred[2] = STV
    return bytes(pred)


def is_id(code, zone, miss):
    """rcx/rdx are a zone ID's bytes and length."""
    code.raw('4883fa'+bytes([len(zone)]).hex()).jcc('ne', miss)
    for i, ch in enumerate(zone.encode()):
        code.raw('8079'+bytes([i, ch]).hex()).jcc('ne', miss)
    return code


def rip_target(image, site):
    return site+7+struct.unpack_from('<i', image.read(site, 7), 3)[0]


def jump_target(image, site):
    ins = image.read(site, 5)
    if ins[0] != 0xe9:
        raise ValueError(f'Expected a reviewed bridge at {site:#x}')
    return site+5+struct.unpack_from('<i', ins, 1)[0]


def rehook(image, site, size, code):
    """Replace an earlier patch's bridge jump at site with a new bridge."""
    jump_target(image, site)
    image.hook(site, image.read(site, size), code)


def align16(n):
    return (n+15)//16*16


def put_code(image, code):
    return image.put(code.assemble(image.rva+align16(len(image.payload))), 16)


def absolute_pointers(image):
    rva, size = struct.unpack_from('<II', image.data, image.opt+152)
    reloc, at, out = image.read(rva, size), 0, set()
    while at < len(reloc):
        page, block = struct.unpack_from('<II', reloc, at)
        out.update(page+(w & 4095) for w in struct.unpack_from(f'<{(block-8)//2}H', reloc, at+8) if w >> 12 == 10)
        at += block
    return out


def apply(image, horde, lines):
    """horde(code, operand, yes, no) tests a race byte; lines maps zone 0/12 to (text, rgb)."""
    p, h = PROFILE, PROFILE['hooks']
    image.writable = True
    state = image.put(bytes(16), 16)  # u32 open mask, u8 horde, u8 valid
    map_state = image.put(bytes(8), 8)  # u8 overlay (0 closed, Story, Dungeons), u32 last picked zone at +4
    mask, horde_flag, valid = state, state+4, state+5

    # Catalog: the Durotar copy's 13 records, then the six chapter stand-ins.
    old_ptr, count = struct.unpack('<QQ', image.read(p['slices'][0], 16))
    old = old_ptr-image.base
    if count != COUNT:
        raise ValueError('Expected the 13-zone Durotar catalog')
    for i, zone in enumerate(ZONE_IDS):
        ptr, n = struct.unpack('<QQ', image.read(old+i*RECORD+8, 16))
        if image.read(ptr-image.base, n).decode() != zone:
            raise ValueError('Unexpected native zone order')
    sources = [*range(COUNT), *(chapter[3] for chapter in CHAPTERS)]
    catalog = image.put(b''.join(image.read(old+s*RECORD, RECORD) for s in sources), 16)
    pointers = absolute_pointers(image)
    for i, source in enumerate(sources):
        image.relocations += [catalog+i*RECORD+o for o in range(0, RECORD, 8) if old+source*RECORD+o in pointers]
    for i, chapter in enumerate(CHAPTERS):
        record = catalog+(COUNT+i)*RECORD
        image.text(record+8, chapter[0])
        image.text(record+24, chapter[1])
        image.text(record+40, chapter[2])
        image.text(record+168, description(chapter))

    # Built zones: terrain, music, card, and their own enemies and bosses,
    # cloned from Elwynn's records with names, displays and creature IDs set.
    elwynn_enemies, enemy_count = struct.unpack('<QQ', image.read(old+120, 16))
    elwynn_bosses, boss_count = struct.unpack('<QQ', image.read(old+136, 16))
    elwynn_enemies, elwynn_bosses = elwynn_enemies-image.base, elwynn_bosses-image.base
    if (enemy_count, boss_count) != (12, 5):
        raise ValueError("Unexpected Elwynn enemy or boss schedule")

    def clone(source, count, size, skip=()):
        copy = image.put(image.read(source, count*size), 8)
        image.relocations += [copy+k*size+o for k in range(count) for o in range(0, size, 8)
                              if source+k*size+o in pointers and o not in skip]
        return copy

    built = {}
    for i, chapter in enumerate(CHAPTERS):
        zone = ZONES.get(chapter[0])
        if not zone:
            continue
        record = catalog+(COUNT+i)*RECORD
        at = record-image.rva
        struct.pack_into('<II3f', image.payload, at+192, zone['map'], zone['area'], *zone['center'])
        struct.pack_into('<I', image.payload, at+220, zone['music'])
        image.text(record+152, zone['card'])
        if 'bounds' in zone:
            # +88 is the zone's walkable outline, (x, y) f32 pairs; +216 its radius.
            outline = image.put(b''.join(struct.pack('<2f', *point) for point in zone['bounds']), 4)
            image.pointer(record+88, outline)
            struct.pack_into('<Q', image.payload, at+96, len(zone['bounds']))
        if 'radius' in zone:
            struct.pack_into('<f', image.payload, at+216, zone['radius'])
        enemies = clone(elwynn_enemies, 12, ENEMY_SIZE)
        for k, (name, display) in enumerate(zone['enemies']):
            image.text(enemies+k*ENEMY_SIZE+16, name)
            struct.pack_into('<II', image.payload, enemies-image.rva+k*ENEMY_SIZE+32, zone['enemy_id']+k, display)
        bosses = clone(elwynn_bosses, 5, BOSS_SIZE, skip=(48,))
        for k, (name, display) in enumerate(zone['bosses']):
            at_boss = bosses+k*BOSS_SIZE
            image.text(at_boss, name)
            image.text(at_boss+32, f'{name} joins the battle!')
            # An empty phase list: the copied Elwynn records summon none of Elwynn's adds.
            struct.pack_into('<QQ', image.payload, at_boss-image.rva+48, 8, 0)
            struct.pack_into('<II', image.payload, at_boss-image.rva+64, zone['boss_id']+k, display)
        image.pointer(record+120, enemies)
        image.pointer(record+136, bosses)
        struct.pack_into('<Q', image.payload, at+128, 12)
        struct.pack_into('<Q', image.payload, at+144, 5)
        built[chapter[0]] = (record, enemies, bosses, zone)
    # Elwynn's last three bosses become forest bosses; their slots, timing,
    # loot and creature IDs are unchanged. The fields keep native relocations.
    for slot, name, display in ELWYNN_BOSSES:
        at_boss = elwynn_bosses+slot*BOSS_SIZE
        for offset, text in ((0, name), (32, f'{name} joins the battle!')):
            encoded = text.encode()
            image.edit(at_boss+offset, struct.pack('<QQ', image.base+image.put(encoded, 1), len(encoded)))
        image.edit(at_boss+68, struct.pack('<I', display))
    # The native server answers creature queries through an ID switch; route
    # each built zone's IDs to the enemy and boss serializers, as for Durotar.
    hq = h['query']
    previous_query = jump_target(image, hq['rva'])
    slot = struct.pack('<I', hq['zone_slot']).hex()
    id_range = lambda first, last: '4489f02d'+struct.pack('<I', first).hex()+'83f8'+bytes([last]).hex()
    code = Code().raw('50')
    for name, (record, enemies, bosses, zone) in built.items():
        code.raw(id_range(zone['enemy_id'], 11)).jcc('be', f'enemy_{name}')
        code.raw(id_range(zone['boss_id'], 4)).jcc('be', f'boss_{name}')
    code.raw('58').jmp(previous_query)
    for name, (record, enemies, bosses, zone) in built.items():
        code.label(f'enemy_{name}').raw(f'6bc0{ENEMY_SIZE:02x}').rel('4c8d3d', enemies).raw('4901c7584989dc4c89eb')
        code.rel('488d05', record).raw('488985'+slot).jmp(hq['enemy'])  # zone record in its stack slot
        code.label(f'boss_{name}').raw(f'6bc0{BOSS_SIZE:02x}').rel('4c8d3d', bosses).raw('4901c7584989dc4c89eb')
        code.jmp(hq['boss'])
    rehook(image, hq['rva'], hq['size'], code)
    # Native polygon boundaries originally only recognize WSG and SM. Route
    # Deadmines through the same outside test and closest-edge correction.
    for site, polygon in ((0x5bdce38, 0x5bdce41),
                          (0x5be82b4, 0x5be82bd),
                          (0x5be88c2, 0x5be88cb)):
        before = image.read(site, 9)
        if before[:5] != bytes.fromhex('83f8070f85'):
            raise ValueError('Unsupported native polygon dispatch')
        circular = site+9+struct.unpack_from('<i', before, 5)[0]
        code = Code().raw('83f8'+bytes([INDEX['deadmines']]).hex()).jcc('e', polygon)
        code.raw('83f807').jcc('ne', circular).jmp(polygon)
        image.hook(site, before, code)

    # Stationary camps have their own tagged placement table (+56/+64).
    # Without it the game falls back to the outer circle, outside the caves.
    for record, _, _, zone in built.values():
        if not (zone.get('ground') or zone.get('camps')):
            continue
        camps=zone['camps'] if zone.get('camps') else zone['ground'].elite_spawns()
        tagged=image.put(b''.join(struct.pack('<Q2f',i,*point[:2]) for i,point in enumerate(camps)),8)
        image.pointer(record+56,tagged)
        struct.pack_into('<Q',image.payload,record-image.rva+64,len(camps))
        positions=image.put(b''.join(struct.pack('<2f',*point[:2]) for point in camps),8)
        image.pointer(record+104,positions)
        struct.pack_into('<Q',image.payload,record-image.rva+112,len(camps))
    site=0x5bf95f8
    before=image.read(site,10)
    if before!=bytes.fromhex('4983f8030f87b1f0ffff'):
        raise ValueError('Unsupported native camp-count check')
    code=Code().raw('5152')
    for name, (_, _, _, zone) in built.items():
        if not (zone.get('ground') or zone.get('camps')):
            continue
        code.raw('498b8c24d0020000').raw('498b9424d8020000')
        is_id(code, name, 'camp_next_'+name).jmp('three_camps').label('camp_next_'+name)
    code.jmp('native').label('three_camps').raw('5a594983f802').jcc('a',0x5bf86b3).jmp(site+10)
    code.label('native').raw('5a594983f803').jcc('a',0x5bf86b3).jmp(site+10)
    image.hook(site,before,code)

    # Zones with a ground map (Deadmines and Wailing): the game has no height data for
    # the map, so its height lookup 0x5ba3040 (rcx = terrain, xmm1/xmm2 = x/y;
    # returns al = found, xmm0 = height) fails and creatures keep stale heights.
    # While such a zone runs, lookups inside the map answer from it.
    # Enemy spawns: 0x5bffab0 picks a spot around the hero into [rbp+0x1f8]
    # (x, y, z); some spawns copy a given spot there instead. Both pass the two
    # sites below with r14 = the zone record; there the spot moves to the
    # nearest spawnable cell (dry, open, level) at its ground height. The same
    # sites note which zone is running. rax and xmm0-3 are free there.
    running = None
    ground_states = {}
    for name, (record, enemies, bosses, zone) in built.items():
        if not zone.get('ground'):
            continue
        G = zone['ground']
        heights, targets = G.load()
        table = image.put(struct.pack(f'<{G.W*G.H}f', *G.lookup_heights(heights, targets)), 16)
        nearest = image.put(struct.pack(f'<{G.W*G.H*2}H', *(v for t in targets for v in t)), 16)
        consts = image.put(struct.pack('<7f', G.X0, G.Y0, G.X0+G.W*G.CELL, G.Y0+G.H*G.CELL,
                                       1/G.CELL, G.CELL, G.CELL/2), 16)
        running = image.put(bytes(8), 8)
        ground_states[name] = running
        x0, y0, x1, y1, inv, cell, half = (consts+4*k for k in range(7))
        # Camps are constructed before ordinary enemies spawn, so activate the
        # cave lookup at run initialization rather than waiting for a spawn hook.
        site=0x5bf7854
        before=image.read(site,10)
        continuation = jump_target(image, site) if before[0] == 0xe9 else None
        if continuation is None and before!=bytes.fromhex('4989ccc681830d000001'):
            raise ValueError('Unsupported native run initialization')
        code=Code().raw('4989cc505152').rel('c605',running,'00')
        code.raw('498b8c24d0020000').raw('498b9424d8020000')
        is_id(code, name, 'ready').rel('c605',running,'01')
        code.label('ready').raw('5a5958')
        if continuation is None:
            code.raw(before).jmp(site+10)
        else:
            code.jmp(continuation)
        image.hook(site,before,code)



        def index(code, coord, origin, count, reg):
            """reg (eax/edx) = clamp(int((coord-origin)/cell), 0, count-1) for xmm1/xmm2; r10 is scratch."""
            r = {'eax': 'c0', 'edx': 'd2'}[reg]
            code.raw('0f28' + {'xmm1': 'c1', 'xmm2': 'c2'}[coord])
            code.rel('f30f5c05', origin).rel('f30f5905', inv)
            code.raw('f30f2c' + {'eax': 'c0', 'edx': 'd0'}[reg])                # cvttss2si
            code.raw('4531d2').raw('85' + r).raw('410f4c' + {'eax': 'c2', 'edx': 'd2'}[reg])
            code.raw('41ba' + struct.pack('<I', count-1).hex()).raw('4439' + {'eax': 'd0', 'edx': 'd2'}[reg])
            code.raw('410f4f' + {'eax': 'c2', 'edx': 'd2'}[reg])

        lookup = 0x5ba3040
        before = image.read(lookup, 5)
        continuation = jump_target(image, lookup) if before[0] == 0xe9 else None
        if continuation is None and before != bytes.fromhex('564883ec40'):
            raise ValueError('Unsupported native height lookup')
        code = Code().rel('803d', running, '00').jcc('e', 'native')
        # Clamp out-of-grid queries to safe edge ground as well. Falling back
        # to the native ADT here can lift a hero onto the dungeon's roof.
        index(code, 'xmm1', x0, G.W, 'eax')
        index(code, 'xmm2', y0, G.H, 'edx')
        code.raw('69c0' + struct.pack('<I', G.H).hex()).raw('01d0')             # eax = ix*H + iy
        code.rel('488d15', table).raw('f30f100482')                             # xmm0 = heights[eax]
        code.raw('b801000000c3')
        code.label('native')
        if continuation is None:
            code.raw(before).jmp(lookup+len(before))
        else:
            code.jmp(continuation)
        image.hook(lookup, before, code)

        for site in (0x5c005af, 0x5c005f4):
            before = image.read(site, 9)
            continuation = jump_target(image, site) if before[0] == 0xe9 else None
            if continuation is None and before != bytes.fromhex('f3440f1086c00c0000'):
                raise ValueError('Unsupported native enemy spawn')
            code = Code().rel('488d05', record).raw('4939c6').jcc('e', 'mine')
            code.rel('c605', running, '00').jmp('done')
            code.label('mine').rel('c605', running, '01')
            code.raw('515241504151415241534883ec08')                             # rcx, rdx, r8-r11
            code.raw('f30f108df8010000f30f1095fc010000')                         # xmm1, xmm2 = spawn x, y
            index(code, 'xmm1', x0, G.W, 'eax')
            index(code, 'xmm2', y0, G.H, 'edx')
            code.raw('69c0' + struct.pack('<I', G.H).hex()).raw('01d0')         # eax = cell
            code.rel('488d15', nearest).raw('0fb70c82').raw('440fb7448202')       # ecx, r8d = nearest tx, ty
            code.raw('4469c9' + struct.pack('<I', G.H).hex()).raw('4501c1')      # r9d = tx*H + ty
            # Always use the tested cell centre, including already-safe cells.
            # Keeping a random point within that cell can lose wall clearance.
            code.raw('f30f2ac1').rel('f30f5905', cell).rel('f30f5805', x0).rel('f30f5805', half)
            code.raw('f30f1185f8010000')                                        # x = cell centre
            code.raw('f3410f2ac0').rel('f30f5905', cell).rel('f30f5805', y0).rel('f30f5805', half)
            code.raw('f30f1185fc010000')                                        # y = cell centre
            code.label('ground').rel('488d15', table).raw('f3420f10048a')        # xmm0 = heights[r9]
            code.raw('f30f118500020000')                                        # z = ground
            code.label('restore').raw('4883c408415b415a415941585a59')
            code.label('done')
            if continuation is None:
                code.raw(before).jmp(site+len(before))
            else:
                code.jmp(continuation)
            image.hook(site, before, code)

    # The movement packet has a height from the client's physical WMO mover.
    # At a wall, the grid may describe a ledge ~50 yards above that player.
    # Keep the physical height when the grid belongs to a different storey.
    # xmm14 holds incoming z throughout this handler (loaded at 0x5be8178,
    # untouched until the epilogue). The first site validates the packet;
    # the second builds a corrective teleport with a native +0.5 offset.
    step = image.put(struct.pack('<f', WAILING_PLAYER_HEIGHT_STEP), 4)
    half_yard = image.put(struct.pack('<f', .5), 4)
    absolute = image.put(struct.pack('<4I', *([0x7fffffff]*4)), 16)
    for site in WAILING_PLAYER_HEIGHT_SITES:
        before = image.read(site, 5)
        if before != b'\xe8'+struct.pack('<i', 0x5ba3040-site-5):
            raise ValueError('Unsupported native player floor validation')
        code = Code().rel('e8', 0x5ba3040)
        code.rel('803d', ground_states['wailing'], '00').jcc('e', 'done')
        code.raw('a801').jcc('e', 'done')
        code.raw('4883ec100f111c24')  # preserve xmm3
        code.raw('0f28d8')  # xmm3 = grid floor
        code.raw('f3410f5cde')  # subtract incoming z in xmm14
        code.rel('0f541d', absolute).rel('0f2e1d', step).jcc('be', 'restore')
        if site == WAILING_PLAYER_HEIGHT_SITES[0]:
            code.raw('410f28c6')  # use incoming z
        else:
            code.raw('410f28c6').rel('f30f5c05', half_yard)  # cancel native +0.5
        code.label('restore').raw('0f101c244883c410')
        code.label('done').jmp(site+5)
        image.hook(site, before, code)

    # Per-zone tables: tiers follow the scaling rank, achievements get scores.
    # The Durotar copies of both tier tables, found through their references.
    def tiers(copy, original):
        values = image.read(copy, COUNT*TIER)
        if values != image.read(original, 12*TIER)+bytes(TIER):
            raise ValueError('Unexpected Durotar tier table')
        return copy, image.put(values+b''.join(values[s*TIER:(s+1)*TIER] for s in SCALE[COUNT:]), 8)
    others = {rip_target(image, site) for site in p['references']}-set(range(old, old+COUNT*RECORD))
    old_tier, tier = tiers(min(others), p['tier'])
    old_ui_tier, ui_tier = tiers(rip_target(image, p['ui_tier_references'][0]), p['ui_tier'])
    for site in p['references']:
        target = rip_target(image, site)
        if old <= target < old+COUNT*RECORD:
            new = catalog+target-old
        elif old_tier <= target < old_tier+COUNT*TIER:
            new = tier+target-old_tier
        else:
            raise ValueError(f'Unexpected zone reference at {site:#x}')
        image.edit(site+3, struct.pack('<i', new-site-7))
    for site in p['end_references']:
        if rip_target(image, site) != old+COUNT*RECORD:
            raise ValueError('Unexpected zone end reference')
        image.edit(site+3, struct.pack('<i', catalog+TOTAL*RECORD-site-7))
    for site in p['ui_tier_references']:
        if rip_target(image, site) != old_ui_tier:
            raise ValueError('Unexpected Armory tier reference')
        image.edit(site+3, struct.pack('<i', ui_tier-site-7))
    # The Durotar patch raised each hard-coded zone bound by one zone's step
    # (a count, 240-byte records, 56-byte picker rows); raise them to TOTAL.
    for edit in p['edits']:
        before, after = bytes.fromhex(edit['before']), bytes.fromhex(edit['after'])
        if image.read(edit['rva'], len(after)) != after:
            raise ValueError(f"Unexpected Durotar edit: {edit['name']}")
        step = int.from_bytes(after[-4:], 'little')-int.from_bytes(before[-4:], 'little')
        size = 4 if step in (1, RECORD, 56) else 1  # imm32, else a trailing imm8
        if size == 1:
            step = after[-1]-before[-1]
        value = int.from_bytes(after[-size:], 'little')
        image.edit(edit['rva']+len(after)-size, (value+step*(TOTAL-COUNT)).to_bytes(size, 'little'))
    # The slice pointer keeps its native relocation entry.
    image.edit(p['slices'][0], struct.pack('<QQ', image.base+catalog, TOTAL))
    site = p['achievement_points']['reference']
    scores = struct.unpack('<13I', image.read(rip_target(image, site), 52))
    table = image.put(struct.pack(f'<{TOTAL}I', *scores, *ACHIEVEMENT_POINTS), 8)
    image.edit(site+3, struct.pack('<i', table-site-7))

    # Zone ID lookup: the new IDs, then the Durotar bridge.
    previous = jump_target(image, LOOKUP)
    code = Code()
    for zone, i in INDEX.items():
        is_id(code, zone, f'not_{zone}').raw('b8'+struct.pack('<I', i).hex()+'c3').label(f'not_{zone}')
    # The Story and Dungeons buttons' IDs stand for the zone picked before them.
    for ident in (story_map.TOGGLE_ID, story_map.DUNGEON_ID):
        is_id(code, ident.decode(), f'not_{ident.decode()}').rel('8b05', map_state+4).raw('c3').label(f'not_{ident.decode()}')
    rehook(image, LOOKUP, h['lookup']['size'], code.jmp(previous))
    # Reward/level scaling and loot read the scaling rank.
    scale = image.put(SCALE, 1)
    rank = put_code(image, Code().raw('4883ec28').rel('e8', LOOKUP).raw('4883c428')
                    .raw('4883f8'+bytes([TOTAL]).hex()).jcc('ae', 'done')
                    .rel('488d0d', scale).raw('0fb60401').label('done').raw('c3'))
    for call in p['rank_calls']:
        image.edit(call+1, struct.pack('<i', rank-call-5))
    hk = h['loot_zone']
    rehook(image, hk['rva'], hk['size'], Code().raw('50').rel('488d05', scale).raw('460fb6040058')
           .raw(hk['before']).jmp(hk['resume']))

    # The open-zone mask: rcx = progress, edx = class, r8d = race.
    def opened(code, after, legacy, zone, tag=''):
        """Open zone if `after` was cleared, or the counter has reached `legacy`."""
        code.raw('4983fc'+bytes([legacy]).hex()).jcc('ae', f'open{zone}{tag}')
        code.raw('4889f189da41b8'+struct.pack('<I', after).hex()).rel('e8', COMPLETED)
        code.raw('84c0').jcc('e', f'shut{zone}{tag}')
        code.label(f'open{zone}{tag}').raw('4181cd'+struct.pack('<I', 1 << zone).hex()).label(f'shut{zone}{tag}')
    code = Code().raw('53565741544155554883ec28').raw('4889ce89d331ff')
    horde(code, bytes.fromhex('4180f8'), 'horde', 'faction')
    code.label('horde').raw('bf01000000').label('faction')
    # r12 = this class's counter, 1 when absent (as natively).
    code.raw('488b4e20488b562848c1e2044531c041bc01000000')
    code.label('scan').raw('4c39c2').jcc('be', 'counted').raw('42381c01').jcc('e', 'found')
    code.raw('4983c010').jmp('scan')
    code.label('found').raw('4e8b640108').label('counted')
    # Original zones 2-11 open by the counter, capped at 12 as natively.
    code.raw('b90c0000004983fc0c410f42cc').raw('b801000000d3e0ffc825fc0f00004189c5')
    code.raw('85ff').jcc('ne', 'horde_path')
    for tag, path in (('a', ALLIANCE_PATH), ('h', HORDE_PATH)):
        if tag == 'h':
            code.label('horde_path')
        code.raw('4181cd'+struct.pack('<I', 1 << path[0]).hex())
        for a, b in zip(path, path[1:]):
            opened(code, a, 2, b)
        opened(code, path[-1], 3, STV, tag)
        other = HORDE_PATH[2] if tag == 'a' else ALLIANCE_PATH[2]
        opened(code, path[1], 2, other, tag)
        code.jmp('store')
    code.label('store').rel('44892d', mask).rel('40883d', horde_flag).rel('c605', valid, '01')
    code.raw('4883c4285d415d415c5f5e5bc3')
    compute = put_code(image, code)
    # Validator entry: rdx = progress, r8 = hero (class +0x30, race +0x31).
    site, before = 0x5aba301, bytes.fromhex('418a58304c8945f0')
    image.hook(site, before, Code().raw('50515241504151415241534883ec28')
               .raw('4889d1410fb65030450fb64031').rel('e8', compute)
               .raw('4883c428415b415a415941585a5958').raw(before).jmp(site+len(before)))

    # Validation: an unopened zone falls back to the hero's faction starter.
    def starter(code):
        return code.rel('0fb605', horde_flag).raw('6bc00c')  # movzx eax, horde / imul eax, 12
    for name in ('validate_ae', 'validate_b'):
        hk = h[name]
        rehook(image, hk['rva'], hk['size'], starter(Code().rel('0fa305', mask).jcc('b', hk['accepted']))
               .jmp(0x5aba400))
    hk = h['select_b']
    rehook(image, hk['rva'], hk['size'], starter(Code().rel('0fa305', mask).jcc('b', hk['accepted']))
           .jmp(0x5b3a7d7))
    # Zone cards and the Armory's drop tables lock what the mask has not opened.
    for name in ('card_lock', 'card_lock_selected'):
        hk = h[name]
        locked = bytes.fromhex(hk['before'])[6:10]
        rehook(image, hk['rva'], hk['size'], Code().rel('0fa335', mask).raw(b'\x0f\x93\x85'+locked).jmp(hk['resume']))
    index = bytes.fromhex(h['drop_order']['before'])[17:21]
    load = '488b85'+index.hex()
    hk = h['drop_unlocked']
    rehook(image, hk['rva'], hk['size'], Code().raw('50'+load).rel('0fa305', mask).raw('400f92c758').jmp(hk['resume']))
    hk = h['drop_lock']
    rehook(image, hk['rva'], hk['size'], Code().raw('50'+load).rel('0fa305', mask).raw('58')
           .jcc('ae', hk['rejected']).jmp(hk['accepted']))
    hk = h['drop_lock_detail']
    alliance_pred, horde_pred = image.put(predecessors(False), 1), image.put(predecessors(True), 1)
    code = Code().raw(load).rel('0fa305', mask).jcc('b', hk['accepted'])
    # Native locked details subtract one from the zone index. Elwynn can now
    # be locked for Horde heroes, so zero must never reach that subtraction.
    # Starters have faction requirements; other chapters use the actual road.
    code.raw('4883f800').jcc('e', 'alliance').raw('4883f80c').jcc('e', 'horde')
    code.rel('488d0d', alliance_pred).rel('803d', horde_flag, '00').jcc('e', 'predecessor')
    code.rel('488d0d', horde_pred).label('predecessor').raw('0fb6040148ffc0').jmp(hk['resume'])
    for label, text in (('alliance', 'Alliance only'), ('horde', 'Horde only')):
        encoded = text.encode()
        code.label(label).raw('48c785a003000000000000')
        code.rel('488d05', image.put(encoded, 1)).raw('488985a8030000')
        code.raw('48c785b0030000'+struct.pack('<I', len(encoded)).hex()).jmp(0x1e5e3f)
    rehook(image, hk['rva'], hk['size'], code)

    # Card and drop-table order.
    successor = image.put(next_table(), 1)
    hk = h['card_order']
    rehook(image, hk['rva'], hk['size'], Code().raw('50').rel('488d05', successor).raw('460fb67c38ff')
           .rel('488d1d', catalog).raw('4969c7'+struct.pack('<I', RECORD).hex()+'4801c358')
           .raw(hk['before']).jmp(hk['resume']))
    hk = h['drop_order']
    rehook(image, hk['rva'], hk['size'], Code().raw(hk['before']).raw('50'+load).rel('488d0d', successor)
           .raw('0fb64401ff').raw('488985'+index.hex()).raw('4869c0'+struct.pack('<I', RECORD).hex())
           .rel('488d0d', catalog).raw('4801c158').jmp(hk['resume']))

    # A victory before Stranglethorn opens chapters by completion, not the
    # counter; Stranglethorn advances the counter as Duskwood once did.
    hk = h['unlock']
    code = Code()
    for zone in NO_ADVANCE:
        code.raw('4883f8'+bytes([zone]).hex()).jcc('e', hk['far'])
    code.raw('4883f8'+bytes([STV]).hex()).jcc('ne', 'native').raw('b801000000')
    code.label('native').raw('4883f80a').jcc('a', hk['far']).jmp(hk['resume'])
    rehook(image, hk['rva'], hk['size'], code)

    # Status lines. Starters always show their faction. A faction road's other
    # chapters show it too, unless they're this hero's and still locked (then
    # the lock hint shows). Dungeons say "Dungeon" once open. dil = locked.
    site, before = 0x20d362, bytes.fromhex('4084ff488dbc24a8030000')
    kinds = dict(lines)
    kinds['dungeon'] = DUNGEON_LINE
    kinds['maplocked'] = ('Locked', (1.0, 0.45, 0.30))
    chosen = image.put(bytes(8), 8)  # the line's colour for the colour hook, or 0
    code = Code()
    for zone in lines:
        code.raw('48833b'+bytes([zone]).hex()).jcc('e', f'line{zone}')
    for zone in DUNGEONS:
        code.raw('48833b'+bytes([zone]).hex()).jcc('e', 'dungeon')
    for zone in ALLIANCE_PATH[1:]:
        code.raw('48833b'+bytes([zone]).hex()).jcc('e', 'alliance_chapter')
    for zone in HORDE_PATH[1:]:
        code.raw('48833b'+bytes([zone]).hex()).jcc('e', 'horde_chapter')
    # The compact overview keeps prerequisites in the regular expanded list;
    # multi-line boss requirements otherwise overflow its fixed-height cards.
    code.label('native').rel('803d', map_state, '00').jcc('e', 'full_hint')
    code.raw('4084ff').jcc('ne', 'linemaplocked')
    code.label('full_hint').rel('48c705', chosen, '00000000').raw(before).jmp(site+len(before))
    code.label('alliance_chapter').rel('803d', horde_flag, '00').jcc('ne', 'line0')
    code.raw('4084ff').jcc('ne', 'native').jmp('line0')
    code.label('horde_chapter').rel('803d', horde_flag, '00').jcc('e', 'line12')
    code.raw('4084ff').jcc('ne', 'native').jmp('line12')
    code.label('dungeon').raw('4084ff').jcc('ne', 'native').jmp('linedungeon')
    for zone, (text, rgb) in kinds.items():
        encoded = text.encode()
        code.label(f'line{zone}').rel('488d05', image.put(struct.pack('<I3f', 0, *rgb), 16)).rel('488905', chosen)
        code.rel('488d05', image.put(encoded, 1))
        code.raw('b9'+struct.pack('<I', len(encoded)).hex()).jmp('line')
    # A static String with zero capacity, which Rust never frees.
    code.label('line').raw('48c784243002000000000000')
    code.raw('4889842438020000').raw('48898c2440020000')
    code.raw('488dbc24a8030000').raw('4c8b7c2440').jmp(0x20d4b7)
    image.hook(site, before, code)
    site, before = 0x20d512, image.read(0x20d512, 7)
    if before[:3] != bytes.fromhex('0f1005'):
        raise ValueError('Unsupported native lock-hint colour')
    hint = site+7+struct.unpack_from('<i', before, 3)[0]
    code = Code().raw('50').rel('488b05', chosen).raw('4885c0').jcc('e', 'native')
    code.raw('0f1000').rel('48c705', chosen, '00000000').raw('58').jmp(site+7)
    code.label('native').raw('58').rel('0f1005', hint).jmp(site+7)
    image.hook(site, before, code)
    # A locked card names the final boss of the zone before it on the hero's path.
    site, before = 0x20d378, bytes.fromhex('488b0b48ffc9')
    image.hook(site, before, Code().raw('488b0b50').rel('488d05', alliance_pred)
               .rel('803d', horde_flag, '00').jcc('e', 'read').rel('488d05', horde_pred)
               .label('read').raw('0fb60c0858').jmp(site+len(before)))

    # Before the Story panel and Enter button are built, move a hero whose zone
    # the mask has not opened (say, after a race change) to the faction starter.
    # The old String is leaked rather than freed in case anything still reads it.
    site, before = 0x20cdb8, bytes.fromhex('498b04244889442420')
    code = Code().raw('554889e5').raw('515241504151415241535356574154')
    code.raw('4883e4f04883ec20').raw('4c89cb')  # align; rbx = hero
    # The Story or Dungeons button was clicked: open that overlay (or close it
    # if it was open) and put back the zone the ID stood for, as a static
    # String (capacity 0, never freed).
    code.raw('488b4b20488b5328')
    is_id(code, story_map.TOGGLE_ID.decode(), 'not_story').raw('31c0')
    code.rel('803d', map_state, bytes([story_map.STORY]).hex()).raw('0f95c0').rel('8805', map_state).jmp('restore')
    code.label('not_story')
    is_id(code, story_map.DUNGEON_ID.decode(), 'picked').raw('31c0')
    code.rel('803d', map_state, bytes([story_map.DUNGEONS]).hex()).raw('0f95c000c0').rel('8805', map_state)
    code.label('restore').rel('8b05', map_state+4).raw('4869c0'+struct.pack('<I', RECORD).hex()).rel('488d15', catalog).raw('4801d0')
    code.raw('488b4808488b5010').raw('48c7431800000000').raw('48894b20').raw('48895328')
    code.label('picked')
    code.rel('803d', valid, '00').jcc('e', 'keep')
    code.raw('488b4b20488b5328').rel('e8', LOOKUP)
    code.raw('4883f8'+bytes([TOTAL]).hex()).jcc('ae', 'keep')
    # Picking another zone closes the map.
    code.rel('3b05', map_state+4).jcc('e', 'same').rel('c605', map_state, '00').rel('8905', map_state+4)
    code.label('same').rel('0fa305', mask).jcc('b', 'keep')
    code.rel('488d35', image.put(b'elwynn', 1)).raw('bf06000000')
    code.rel('803d', horde_flag, '00').jcc('e', 'replace')
    code.rel('488d35', image.put(b'durotar', 1)).raw('bf07000000')
    # r12 = alloc(len, 1); copy; hero.zone = String { cap: len, ptr: r12, len }.
    code.label('replace').raw('4889f9ba01000000').rel('e8', ALLOC)
    code.raw('4885c0').jcc('e', 'keep').raw('4989c4')
    code.raw('4889c14889f24989f8').rel('e8', COPY)
    code.raw('48897b18').raw('4c896320').raw('48897b28')
    code.label('keep').raw('488d65b0').raw('415c5f5e5b415b415a415941585a59').raw('5d')
    code.raw(before).jmp(site+len(before))
    image.hook(site, before, code)

    story_map.install(image, dict(open=map_state), HORDE_PATH, ALLIANCE_PATH, STV, ORDER, DUNGEONS, mask)

    # Co-op: any hero may join any party. The lobby lists every room as opened,
    # and neither the join check nor the run start measures zones opened.
    for name in ('picker_b', 'picker_ae'):
        hk = h[name]
        rehook(image, hk['rva'], hk['size'], Code().jmp(hk['accepted']))
    hk = h['picker_lea_ae']
    rehook(image, hk['rva'], hk['size'], Code().raw(bytes.fromhex(hk['before'])[3:10]).jmp(hk['accepted']))
    site, before = 0x5b4d4df, bytes.fromhex('0fb68dda0100004139ce')
    if image.read(0x5b4d4e9, 2) != bytes.fromhex('7317'):
        raise ValueError('Unsupported native co-op zone check')
    image.hook(site, before, Code().jmp(0x5b4d4eb))
    for site, before in ((0x5c7f2be, '4c39c0'), (0x5c7f3ba, '4939d0')):
        if image.read(site, 3).hex() != before:
            raise ValueError('Unsupported native co-op run start')
        image.edit(site, bytes.fromhex('f99090'))  # stc: the zone always counts as opened
    return dict(mask=mask, horde=horde_flag, valid=valid, catalog=catalog, compute=compute, story_map=map_state, ground=ground_states['deadmines'], ground_states=ground_states)
