"""Execute native faction bridges and exercise the story lifecycle in Lua 5.1."""
import ctypes as C
import json
from pathlib import Path
import struct
import unittest

import starter_missions as missions
import story_chapters as story

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

SOURCE = Path(__file__).resolve().parents[1] / 'downloads/race-expansion/baseline/ASR.exe'


class Mapped:
    """Map reviewed PE bytes for isolated bridge calls, without running the game."""
    def __init__(self, data):
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
        self.kernel.VirtualAlloc.restype = C.c_void_p
        self.kernel.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
        _, opt, _, sections = missions.sections(data)
        self.size = struct.unpack_from('<I', data, opt+56)[0]
        preferred = struct.unpack_from('<Q', data, opt+24)[0]
        self.base = self.kernel.VirtualAlloc(None, self.size+65536, 0x3000, 0x40)
        if not self.base:
            raise OSError(C.get_last_error())
        self.cursor = self.size
        for _, va, raw, size, _ in sections:
            self.write(va, data[raw:raw+size])
        rva, length = struct.unpack_from('<II', data, opt+152)
        reloc = missions.Builder(data).read(rva, length)
        at = 0
        while at < len(reloc):
            page, size = struct.unpack_from('<II', reloc, at)
            for word in struct.unpack_from(f'<{(size-8)//2}H', reloc, at+8):
                if word >> 12 == 10:
                    ptr = C.c_uint64.from_address(self.base+page+(word & 4095))
                    ptr.value += self.base-preferred
            at += size

    def write(self, rva, data):
        C.memmove(self.base+rva, data, len(data))

    def call(self, rva):
        return b'\x49\xbb'+struct.pack('<Q', self.base+rva)+b'\x41\xff\xd3'

    def function(self, code, args):
        at = self.cursor
        self.cursor += (len(code)+15) & ~15
        self.write(at, code)
        return C.CFUNCTYPE(C.c_uint64, *args)(self.base+at)

    def close(self):
        self.kernel.VirtualFree(self.base, 0, 0x8000)


class StoryMapLayoutTests(unittest.TestCase):
    def test_approved_card_positions_and_paths_are_unchanged(self):
        import hashlib
        import story_map as sm
        shared = [z for z in story.ORDER if z not in (*story.HORDE_PATH, *story.ALLIANCE_PATH, story.STV)]
        spots = sm.layout(story.HORDE_PATH, story.ALLIANCE_PATH, story.STV, shared)
        geometry = b''.join(struct.pack('<Iff', k, *v) for k, v in sorted(spots.items()))
        geometry += sm.rect_table(sm.connectors(spots, story.HORDE_PATH, story.ALLIANCE_PATH, story.STV, shared))
        self.assertEqual(hashlib.sha256(geometry).hexdigest(),
                         'a5e535d0a510100ecf43dbc951b3e706f4d5d8e5120ede9c41f0f2ad31dc66e6')

    def test_every_zone_has_a_spot_on_one_connected_road(self):
        import story_map as sm
        shared = [z for z in story.ORDER if z not in (*story.HORDE_PATH, *story.ALLIANCE_PATH, story.STV)]
        spots = sm.layout(story.HORDE_PATH, story.ALLIANCE_PATH, story.STV, shared)
        self.assertEqual(sorted(spots), list(range(story.TOTAL)))
        cards = [(x, y, x+sm.CARD_W, y+sm.CARD_H) for x, y in spots.values()]
        for i, a in enumerate(cards):
            self.assertLessEqual(a[2], 86.0)                      # inside the card list
            self.assertLessEqual(a[3], 62.0)
            for b in cards[i+1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])
        lines = sm.connectors(spots, story.HORDE_PATH, story.ALLIANCE_PATH, story.STV, shared)
        links = 2*(len(story.HORDE_PATH)-1) + 2 + len(shared)
        elbows = 2                                               # both roads turn into Stranglethorn
        self.assertEqual(len(lines), links+elbows)
        for (_, x), (_, y), (wt, w), (ht, h) in lines:
            w = w if wt == sm.VW else 0.0
            h = h if ht == sm.VH else 0.0
            for c in cards:                                       # never through a card
                self.assertFalse(x+0.01 < c[2] and c[0] < x+w-0.01 and y+0.01 < c[3] and c[1] < y+h-0.01)


@unittest.skipUnless(SOURCE.exists(), 'Requires the reviewed native game fixture')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_bytes()
        state, apply = {}, story.apply
        story.apply = lambda *args: state.update(apply(*args)) or state
        try:
            cls.patched = missions.apply(cls.source)
        finally:
            story.apply = apply
        cls.state = state

    def test_idempotent_and_rejects_corruption(self):
        self.assertEqual(missions.apply(self.patched), self.patched)
        self.assertEqual(missions.remove(self.patched), self.source)
        damaged = bytearray(self.patched)
        at = damaged.find(missions.MARKER)
        damaged[at+115] ^= 1
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            missions.apply(damaged)

    def test_active_english_mission_copy(self):
        import bloodelf_patch
        image = missions.Builder(self.patched)
        spec = bloodelf_patch.PROFILE['locales']
        for i in range(spec['count']):
            entry = spec['table']+i*spec['stride']
            ptr, length = struct.unpack('<QQ', image.read(entry, 16))
            if image.read(ptr-image.base, length) != b'en':
                continue
            ptr, length = struct.unpack('<QQ', image.read(entry+32, 16))
            strings = json.loads(image.read(ptr-image.base, length))
            self.assertEqual(strings['picker.zone'], missions.PANEL_TITLE)
            self.assertNotIn(b'ASR starter story', self.patched)  # narration is not loaded
            for zone, text in missions.STORIES.items():
                self.assertEqual(strings[f'zone.{zone}.subtitle'], missions.MISSION_TITLES[zone])
                self.assertEqual(strings[f'zone.{zone}.blurb'], text)
            for chapter in story.CHAPTERS:
                self.assertEqual(strings[f'zone.{chapter[0]}.name'], chapter[1])
            return
        self.fail('Missing active English mission locale')

    def set_state(self, mapped, mask, horde=False):
        C.c_uint32.from_address(mapped.base+self.state['mask']).value = mask
        C.c_uint8.from_address(mapped.base+self.state['horde']).value = int(horde)
        C.c_uint8.from_address(mapped.base+self.state['valid']).value = 1

    def test_mask_follows_completions_and_legacy_counters(self):
        mapped = Mapped(self.patched)
        try:
            call = mapped.function(bytes.fromhex('4883ec28')+mapped.call(self.state['compute'])+bytes.fromhex('4883c428c3'),
                                   [C.c_void_p, C.c_uint64, C.c_uint64])
            ctx = C.create_string_buffer(0x400)
            entries = (C.c_uint64*2)(1, 0)  # class 1 and its counter
            struct.pack_into('<QQ', ctx, 0x20, C.addressof(entries), 1)
            bit = lambda *zones: sum(1 << z for z in zones)
            w, d, b, wc, st, stv = (story.INDEX[z] for z in ('westfall', 'deadmines', 'barrens', 'wailing', 'stonetalon', 'stv'))
            cases = (  # race, counter, cleared zones, open zones
                (1, 1, (), (0,)), (1, 1, (0,), (0, w)), (1, 1, (0, w), (0, w, d, wc)),
                (1, 1, (0, w, d), (0, w, d, wc, 1)),
                (1, 1, (0, w, d, 1), (0, w, d, wc, 1, stv)), (1, 2, (), (0, w, d, wc, 1)),
                (1, 3, (), (0, w, d, wc, 1, stv, 2)), (1, 6, (), (0, w, d, wc, 1, stv, 2, 3, 4, 5)),
                (2, 1, (), (12,)), (2, 1, (12, b), (12, b, wc, d)), (2, 1, (12, b, wc, st), (12, b, wc, d, st, stv)),
                (2, 2, (), (12, b, wc, d, st)), (28, 1, (12,), (12, b)), (1, 1, (12, b), (0,)),
                (1, 1, (0, w, wc), (0, w, d, wc)),   # the other road's dungeon doesn't open your chapter 4
            )
            for race, counter, cleared, expected in cases:
                # COMPLETED stub: al = whether zone r8 is in the cleared set.
                mapped.write(story.COMPLETED, bytes.fromhex('48b8')+struct.pack('<Q', bit(*cleared))+bytes.fromhex('4c0fa3c00f92c0c3'))
                entries[1] = counter
                call(C.addressof(ctx), 1, race)
                mask = C.c_uint32.from_address(mapped.base+self.state['mask']).value
                self.assertEqual(mask, bit(*expected), (race, counter, cleared))
                self.assertEqual(C.c_uint8.from_address(mapped.base+self.state['horde']).value, int(race in missions.HORDE_IDS))
        finally:
            mapped.close()

    def test_cards_validation_and_picker_follow_the_mask(self):
        mapped = Mapped(self.patched)
        try:
            mask = sum(1 << z for z in (0, story.INDEX['westfall'], 3))
            self.set_state(mapped, mask)
            for name in ('card_lock', 'card_lock_selected'):
                spec = missions.PROFILE['hooks'][name]
                locked = bytes.fromhex(spec['before'])[6:10]
                mapped.write(spec['resume'], b'\x0f\xb6\x85'+locked+b'\xc3')
                wrapper = bytes.fromhex('55564883ec284889cd4889d6')+mapped.call(spec['rva'])+bytes.fromhex('4883c4285e5dc3')
                call = mapped.function(wrapper, [C.c_void_p, C.c_uint64])
                scratch = C.create_string_buffer(2048)
                for zone in range(story.TOTAL):
                    self.assertEqual(call(C.addressof(scratch), zone), int(not mask >> zone & 1), (name, zone))
            # Validation keeps an opened zone, otherwise the faction starter.
            # Stops after the native catalog multiply: returns zone*240.
            mapped.write(0x5aba407, b'\xc3')
            mapped.write(0x5b3a7de, b'\xc3')
            for name in ('validate_ae', 'validate_b', 'select_b'):
                spec = missions.PROFILE['hooks'][name]
                mapped.write(spec['accepted'], b'\xc3')
                call = mapped.function(bytes.fromhex('4883ec284889c8')+mapped.call(spec['rva'])+bytes.fromhex('4883c428c3'), [C.c_uint64])
                for horde in (False, True):
                    self.set_state(mapped, mask, horde)
                    for zone in range(story.TOTAL):
                        expected = zone if mask >> zone & 1 else (12 if horde else 0)*240
                        self.assertEqual(call(zone), expected, (name, horde, zone))
        finally:
            mapped.close()

    def test_lookup_order_and_victory_unlocks(self):
        mapped = Mapped(self.patched)
        try:
            lookup = mapped.function(bytes.fromhex('4883ec28')+mapped.call(story.LOOKUP)+bytes.fromhex('4883c428c3'), [C.c_char_p, C.c_uint64])
            for zone, index in (*story.INDEX.items(), ('durotar', 12), ('elwynn', 0), ('duskwood', 1), ('naxx', 11)):
                self.assertEqual(lookup(zone.encode(), len(zone)), index, zone)
            self.assertEqual(sorted(story.ORDER), list(range(story.TOTAL)))
            spec = missions.PROFILE['hooks']['unlock']
            mapped.write(spec['far'], bytes.fromhex('b8ff000000c3'))
            mapped.write(spec['resume'], b'\xc3')
            call = mapped.function(bytes.fromhex('4883ec284889c8')+mapped.call(spec['rva'])+bytes.fromhex('4883c428c3'), [C.c_uint64])
            for zone in range(story.TOTAL):
                expected = 255 if zone in story.NO_ADVANCE or zone == 11 else 1 if zone == story.STV else zone
                self.assertEqual(call(zone), expected, zone)
        finally:
            mapped.close()

    def test_built_zones_have_their_own_terrain_and_creatures(self):
        image = missions.Builder(self.patched)
        base = image.base
        text = lambda at: image.read(struct.unpack('<Q', image.read(at, 8))[0]-base, struct.unpack('<Q', image.read(at+8, 8))[0]).decode()
        catalog = struct.unpack('<Q', image.read(missions.PROFILE['slices'][0], 8))[0]-base
        for zone, spec in story.ZONES.items():
            record = catalog+story.INDEX[zone]*story.RECORD
            self.assertEqual(text(record+8), zone)
            self.assertEqual(image.read(record+192, 20), struct.pack('<II3f', spec['map'], spec['area'], *spec['center']))
            self.assertEqual(text(record+152), spec['card'])
            if 'radius' in spec:
                self.assertEqual(struct.unpack('<f', image.read(record+216, 4))[0], spec['radius'])
            if 'bounds' in spec:
                outline, points = struct.unpack('<QQ', image.read(record+88, 16))
                self.assertEqual([struct.unpack('<2f', image.read(outline-base+8*k, 8)) for k in range(points)], list(spec['bounds']))
                self.assertEqual(struct.unpack('<f', image.read(record+216, 4))[0], spec['radius'])
            enemies, count = struct.unpack('<QQ', image.read(record+120, 16))
            self.assertEqual(count, 12)
            for k, (name, display) in enumerate(spec['enemies']):
                at = enemies-base+k*story.ENEMY_SIZE
                self.assertEqual((text(at+16), *struct.unpack('<II', image.read(at+32, 8))), (name, spec['enemy_id']+k, display))
            bosses, count = struct.unpack('<QQ', image.read(record+136, 16))
            self.assertEqual(count, 5)
            for k, (name, display) in enumerate(spec['bosses']):
                at = bosses-base+k*story.BOSS_SIZE
                self.assertEqual((text(at), *struct.unpack('<II', image.read(at+64, 8))), (name, spec['boss_id']+k, display))
                self.assertEqual(struct.unpack('<QQ', image.read(at+48, 16))[1], 0)  # no inherited adds
        elwynn = struct.unpack('<Q', image.read(catalog+136, 8))[0]-base
        for slot, name, display in story.ELWYNN_BOSSES:
            at = elwynn+slot*story.BOSS_SIZE
            self.assertEqual((text(at), struct.unpack('<I', image.read(at+68, 4))[0]), (name, display))
        self.assertEqual(text(elwynn), 'Hogger')

    def test_creature_queries_reach_built_zone_records(self):
        mapped = Mapped(self.patched)
        try:
            spec = missions.PROFILE['hooks']['query']
            mapped.write(spec['enemy'], bytes.fromhex('4c89f8c3'))   # return r15, the record
            mapped.write(spec['boss'], bytes.fromhex('4c89f848f7d8c3'))  # return -record
            mapped.write(spec['resume'], bytes.fromhex('31c0c3'))
            # rbp = scratch (the zone-record stack slot), r14d = creature ID.
            wrapper = bytes.fromhex('55415641574154534883ec204889cd4989d6')+mapped.call(spec['rva'])
            wrapper += bytes.fromhex('4883c4205b415c415f415e5dc3')
            call = mapped.function(wrapper, [C.c_void_p, C.c_uint64])
            scratch = C.create_string_buffer(0x400)
            image = missions.Builder(self.patched)
            catalog = struct.unpack('<Q', image.read(missions.PROFILE['slices'][0], 8))[0]-image.base
            for zone, zspec in story.ZONES.items():
                record = catalog+story.INDEX[zone]*story.RECORD
                enemies = struct.unpack('<Q', image.read(record+120, 8))[0]-image.base
                bosses = struct.unpack('<Q', image.read(record+136, 8))[0]-image.base
                for k in range(12):
                    self.assertEqual(call(C.addressof(scratch), zspec['enemy_id']+k), mapped.base+enemies+k*story.ENEMY_SIZE)
                    self.assertEqual(struct.unpack_from('<Q', scratch, spec['zone_slot'])[0], mapped.base+record)
                for k in range(5):
                    self.assertEqual(-call(C.addressof(scratch), zspec['boss_id']+k) & (2**64-1), mapped.base+bosses+k*story.BOSS_SIZE)
            self.assertEqual(call(C.addressof(scratch), 1595), 0)  # neither ours nor Durotar's
        finally:
            mapped.close()

    def test_deadmines_room_boundary_blocks_both_passages(self):
        import deadmines_arena as arena
        mapped = Mapped(self.patched)
        try:
            call = mapped.function(bytes.fromhex('4883ec28')+mapped.call(0x5bdcdf0)+bytes.fromhex('4883c428c3'),
                                   [C.c_void_p, C.c_float, C.c_float])
            context = C.create_string_buffer(0x400)
            name = C.create_string_buffer(b'deadmines')
            struct.pack_into('<QQ',context,0x2d0,C.addressof(name),9)
            cases = [(150,137,0), (113,136,0), (108,136,0), (90,136,0), (61,140,1),
                     (167,114,0), (167,108,0), (167,84,0), (167,80,0), (157,68,0), (154,64,1), (177,137,1)]
            for x,y,outside in cases:
                wx,wy,_ = arena.world(x,y)
                self.assertEqual(call(C.addressof(context),wx,wy)&1,outside,(x,y))
        finally:
            mapped.close()

    def test_cave_ground_is_enabled_before_camps_initialize(self):
        mapped=Mapped(self.patched)
        try:
            mapped.write(0x5bf785e,bytes.fromhex('c3'))
            wrapper=bytes.fromhex('41544883ec20')+mapped.call(0x5bf7854)+bytes.fromhex('4883c420415cc3')
            call=mapped.function(wrapper,[C.c_void_p])
            context=C.create_string_buffer(0x1000)
            running=C.c_uint8.from_address(mapped.base+self.state['ground'])
            for zone,expected in (('deadmines',1),('elwynn',0),('deadmines',1)):
                name=C.create_string_buffer(zone.encode())
                struct.pack_into('<QQ',context,0x2d0,C.addressof(name),len(zone))
                call(C.addressof(context))
                self.assertEqual(running.value,expected)
        finally:mapped.close()

    def test_stationary_camps_use_three_fixed_interior_positions(self):
        import deadmines_ground as G
        image=missions.Builder(self.patched)
        catalog=struct.unpack('<Q',image.read(missions.PROFILE['slices'][0],8))[0]-image.base
        record=catalog+story.INDEX['deadmines']*story.RECORD
        ptr,count=struct.unpack('<QQ',image.read(record+56,16))
        self.assertEqual(count,3)
        for i,point in enumerate(G.elite_spawns()):
            tag,x,y=struct.unpack('<Q2f',image.read(ptr-image.base+i*16,16))
            self.assertEqual((tag,x,y),(i,*point[:2]))
        ptr,count=struct.unpack('<QQ',image.read(record+104,16))
        self.assertEqual(count,3)
        self.assertEqual([struct.unpack('<2f',image.read(ptr-image.base+i*8,8)) for i in range(3)],
                         [point[:2] for point in G.elite_spawns()])
        mapped=Mapped(self.patched)
        try:
            mapped.write(0x5bf9602,bytes.fromhex('b801000000c3'))
            mapped.write(0x5bf86b3,bytes.fromhex('31c0c3'))
            wrapper=bytes.fromhex('5541544883ec284989cc4989d0')+mapped.call(0x5bf95f8)+bytes.fromhex('4883c428415c5dc3')
            call=mapped.function(wrapper,[C.c_void_p,C.c_uint64])
            scratch=C.create_string_buffer(0x400)
            for zone,limit in (('deadmines',3),('wailing',3),('stonetalon',3),('stv',3),('barrens',3),('westfall',4)):
                name=C.create_string_buffer(zone.encode())
                struct.pack_into('<QQ',scratch,0x2d0,C.addressof(name),len(zone))
                for index in range(5):self.assertEqual(call(C.addressof(scratch),index),int(index<limit))
        finally:mapped.close()

    def test_three_elite_anchors_are_separated_and_on_clear_floor(self):
        import deadmines_ground as G
        import math
        heights,targets=G.load()
        anchors=G.elite_spawns()
        self.assertEqual(len(anchors),3)
        for n,(x,y,z) in enumerate(anchors):
            gx,gy=int((x-G.X0)//G.CELL),int((y-G.Y0)//G.CELL)
            self.assertEqual(targets[gx*G.H+gy],(gx,gy))
            self.assertTrue(G.arena.inside(x,y,G.SPAWN_CLEARANCE))
            self.assertAlmostEqual(z,heights[gx*G.H+gy])
            for a,b,_ in anchors[:n]:self.assertGreaterEqual(math.hypot(x-a,y-b),45)

    def test_deadmines_spawn_targets_stay_in_compact_room(self):
        import deadmines_ground as G
        import math
        heights, targets = G.load()
        safe = {divmod(i, G.H) for i in range(G.W*G.H) if targets[i] == divmod(i, G.H)}
        self.assertTrue(safe)
        for gx, gy in safe:
            x, y = G.X0+(gx+0.5)*G.CELL, G.Y0+(gy+0.5)*G.CELL
            self.assertTrue(G.arena.inside(x, y, G.SPAWN_CLEARANCE))
            self.assertTrue(math.isfinite(heights[gx*G.H+gy]))
        self.assertTrue(all(t in safe for t in targets))

    def test_elite_spawn_clearance_rejects_wall_but_not_high_ceiling(self):
        import deadmines_ground as G
        import math
        gx, gy = int((G.START[0]-G.X0)//G.CELL), int((G.START[1]-G.Y0)//G.CELL)
        i = gx*G.H+gy
        heights = [math.nan]*(G.W*G.H)
        heights[i] = 50.0
        x, y = G.START[:2]
        # A vertical wall three yards away intersects the elite clearance.
        wall = [(x+3, y-5, 48), (x+3, y+5, 48), (x+3, y, 62)]
        self.assertIn(i, G.blocked_spawns(heights, [wall]))
        # The same wall beyond the margin must remain usable.
        far = [(a+3, b, c) for a, b, c in wall]
        self.assertNotIn(i, G.blocked_spawns(heights, [far]))
        # An overhead log within the body volume blocks the point.
        log = [(x-5, y-5, 54), (x+5, y-5, 54), (x, y+5, 54)]
        self.assertIn(i, G.blocked_spawns(heights, [log]))
        high = [(a, b, c+8) for a, b, c in log]
        self.assertNotIn(i, G.blocked_spawns(heights, [high]))

    def test_deadmines_starts_on_spawnable_mine_floor(self):
        import deadmines_ground as ground
        x, y, z = story.ZONES['deadmines']['center']
        heights, targets = ground.load()
        gx, gy = int((x-ground.X0)//ground.CELL), int((y-ground.Y0)//ground.CELL)
        self.assertEqual(targets[gx*ground.H+gy], (gx, gy))
        self.assertAlmostEqual(z, heights[gx*ground.H+gy], places=2)
        # The mine floor is below its ceiling; the ADT's dummy terrain here
        # is at 302 yards and must never become the cave's ground height.
        self.assertLess(z, 60)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                self.assertLess(abs(heights[(gx+dx)*ground.H+gy+dy]-z), 1)

    def test_deadmines_creatures_follow_connected_cave_ground(self):
        import deadmines_ground as ground
        heights, targets = ground.load()
        G = ground

        def cell(x, y):
            return int((x-G.X0)//G.CELL)*G.H + int((y-G.Y0)//G.CELL)

        mapped = Mapped(self.patched)
        try:
            image = missions.Builder(self.patched)
            catalog = struct.unpack('<Q', image.read(missions.PROFILE['slices'][0], 8))[0]-image.base
            running = C.c_uint8.from_address(mapped.base+self.state['ground'])
            # rcx = terrain; xmm1, xmm2 = x, y; returns al, and xmm0 through the 4th argument.
            lookup = mapped.function(bytes.fromhex('534883ec204c89cb')+mapped.call(0x5ba3040)+bytes.fromhex('f30f11034883c4205bc3'),
                                     [C.c_void_p, C.c_float, C.c_float, C.c_void_p])
            water, dock = (-303.0, -499.0), (-291.0, -517.0)
            cave = story.ZONES['deadmines']['center'][:2]
            self.assertNotEqual(divmod(cell(*water), G.H), targets[cell(*water)])  # overhead log is not spawnable ground
            self.assertEqual(divmod(cell(*dock), G.H), targets[cell(*dock)])
            for site in (0x5c005af, 0x5c005f4):
                mapped.write(site+9, bytes.fromhex('c3'))
                # rbp = scratch holding the spawn spot at +0x1f8; r14 = zone record.
                wrapper = bytes.fromhex('554156415753564883ec204889cd4889ce4989d64d89c7')+mapped.call(site)+bytes.fromhex('4883c4205e5b415f415e5dc3')
                call = mapped.function(wrapper, [C.c_void_p, C.c_uint64, C.c_uint64])
                scratch = C.create_string_buffer(0x400)
                enemy_ptr = struct.unpack('<Q', image.read(catalog+story.INDEX['deadmines']*story.RECORD+120,8))[0]-image.base
                tx, ty = targets[cell(*water)]
                moved = (G.X0+(tx+0.5)*G.CELL, G.Y0+(ty+0.5)*G.CELL, heights[tx*G.H+ty])
                for zone, spot, expected, flag in (
                        ('westfall', (*water, 5.0), (*water, 5.0), 0),
                        ('deadmines', (*water, 5.0), moved, 1),
                        ('deadmines', (dock[0]+0.8, dock[1]+0.8, 50.0), (*dock, heights[cell(*dock)]), 1),
                        ('deadmines', (*cave, 300.0), (*cave, heights[cell(*cave)]), 1)):
                    struct.pack_into('<3f', scratch, 0x1f8, *spot)
                    call(C.addressof(scratch), mapped.base+catalog+story.INDEX[zone]*story.RECORD,mapped.base+enemy_ptr)
                    got = struct.unpack_from('<3f', scratch, 0x1f8)
                    for a, b in zip(got, expected):
                        self.assertAlmostEqual(a, b, places=2, msg=(site, zone, spot))
                    self.assertEqual(running.value, flag)
                for elite,anchor in enumerate(G.elite_spawns(),9):
                    struct.pack_into('<3f',scratch,0x1f8,*water,300.)
                    call(C.addressof(scratch),mapped.base+catalog+story.INDEX['deadmines']*story.RECORD,
                         mapped.base+enemy_ptr+elite*story.ENEMY_SIZE)
                    got = struct.unpack_from('<3f',scratch,0x1f8)
                    for a,b in zip(got,moved):self.assertAlmostEqual(a,b,places=3)
                height = C.c_float()
                safe_heights = G.lookup_heights(heights, targets)
                for x, y in (dock, water, cave, (-100.0, -820.0), (-1000.0, -2000.0), (1000.0, 2000.0)):
                    found = lookup(None, x, y, C.addressof(height))
                    self.assertEqual(found & 0xff, 1)
                    ix = max(0, min(G.W-1, int((x-G.X0)/G.CELL)))
                    iy = max(0, min(G.H-1, int((y-G.Y0)/G.CELL)))
                    self.assertAlmostEqual(height.value, safe_heights[ix*G.H+iy], places=3)
                # The old log-top lookup here jumped from ~50 to ~71 yards.
                self.assertLess(safe_heights[cell(*water)], 55)
        finally:
            mapped.close()

    def test_wailing_ground_hooks_and_zone_transitions(self):
        import wailing_ground as G
        mapped = Mapped(self.patched)
        try:
            image = missions.Builder(self.patched)
            catalog = self.state['catalog']
            record=catalog+story.INDEX['wailing']*story.RECORD
            self.assertEqual(struct.unpack('<f',image.read(record+216,4))[0],G.ARENA_RADIUS)
            for offset,stride,format in ((56,16,'<Q2f'),(104,8,'<2f')):
                ptr,count=struct.unpack('<QQ',image.read(record+offset,16))
                self.assertEqual(count,3)
                for k,point in enumerate(G.elite_spawns()):
                    values=struct.unpack(format,image.read(ptr-image.base+k*stride,stride))
                    self.assertEqual(values[-2:],point[:2])
            flags = {name: C.c_uint8.from_address(mapped.base+address) for name,address in self.state['ground_states'].items()}
            mapped.write(0x5bf785e, b'\xc3')
            init = mapped.function(bytes.fromhex('41544883ec20')+mapped.call(0x5bf7854)+bytes.fromhex('4883c420415cc3'), [C.c_void_p])
            context = C.create_string_buffer(0x1000)
            for zone in ('wailing','deadmines','wailing','westfall'):
                name = C.create_string_buffer(zone.encode())
                struct.pack_into('<QQ',context,0x2d0,C.addressof(name),len(zone))
                init(C.addressof(context))
                self.assertEqual({k:f.value for k,f in flags.items()}, {k:int(k==zone) for k in flags})
            heights, targets = G.load()
            for site in (0x5c005af,0x5c005f4):
                mapped.write(site+9,b'\xc3')
                wrapper = bytes.fromhex('554156415753564883ec204889cd4889ce4989d64d89c7')+mapped.call(site)+bytes.fromhex('4883c4205e5b415f415e5dc3')
                spawn = mapped.function(wrapper,[C.c_void_p,C.c_uint64,C.c_uint64])
                scratch = C.create_string_buffer(0x400)
                record=catalog+story.INDEX['wailing']*story.RECORD
                enemy=struct.unpack('<Q',image.read(record+120,8))[0]-image.base
                for x,y in (G.START[:2],(-170.,350.),(70.,570.),(0.,450.)):
                    struct.pack_into('<3f',scratch,0x1f8,x,y,300.)
                    spawn(C.addressof(scratch),mapped.base+record,mapped.base+enemy)
                    ix,iy=int((x-G.X0)//G.CELL),int((y-G.Y0)//G.CELL)
                    tx,ty=targets[ix*G.H+iy]
                    expected=(G.X0+(tx+.5)*G.CELL,G.Y0+(ty+.5)*G.CELL,heights[tx*G.H+ty])
                    for got,want in zip(struct.unpack_from('<3f',scratch,0x1f8),expected):self.assertAlmostEqual(got,want,places=3)
                    self.assertEqual(flags['wailing'].value,1)
                    self.assertEqual(flags['deadmines'].value,0)
            lookup=mapped.function(bytes.fromhex('534883ec204c89cb')+mapped.call(0x5ba3040)+bytes.fromhex('f30f11034883c4205bc3'),[C.c_void_p,C.c_float,C.c_float,C.c_void_p])
            table=G.lookup_heights(heights,targets)
            for x,y in (G.START[:2],(-1000.,-1000.),(1000.,1000.)):
                height=C.c_float()
                self.assertEqual(lookup(None,x,y,C.addressof(height))&255,1)
                ix=max(0,min(G.W-1,int((x-G.X0)/G.CELL)));iy=max(0,min(G.H-1,int((y-G.Y0)/G.CELL)))
                self.assertAlmostEqual(height.value,table[ix*G.H+iy],places=3)
        finally:mapped.close()

    def test_wailing_wall_contacts_do_not_teleport_between_storeys(self):
        import wailing_ground as G
        mapped=Mapped(self.patched)
        try:
            # Deterministic native lookup stub: rcx -> grid height, incoming
            # z at rcx+8. Run the actual compiled movement call-site bridges.
            mapped.write(0x5ba3040,bytes.fromhex('f30f1001b801000000c3'))
            active=C.c_uint8.from_address(mapped.base+self.state['ground_states']['wailing'])
            wrapper_head=bytes.fromhex('534883ec30440f117424204889d3440f107108')
            wrapper_tail=bytes.fromhex('f30f1103440f107424204883c4305bc3')
            heights,targets=G.load();table=G.lookup_heights(heights,targets)
            transitions=[]
            for x in range(G.W-1):
                for y in range(G.H-1):
                    i=x*G.H+y
                    for j in (i+1,i+G.H):
                        if abs(table[i]-table[j])>10:
                            transitions.extend(((table[i],table[j]),(table[j],table[i])))
            self.assertGreater(len(transitions),500)
            cases=[(-101.,-100.),(-100.,-101.),(-90.,-90.),(-100.,-98.),(-98.,-100.),*transitions]
            scratch=C.create_string_buffer(16);out=C.c_float()
            for index,site in enumerate(story.WAILING_PLAYER_HEIGHT_SITES):
                mapped.write(site+5,b'\xc3')
                call=mapped.function(wrapper_head+mapped.call(site)+wrapper_tail,[C.c_void_p,C.c_void_p])
                for enabled in (0,1):
                    active.value=enabled
                    for incoming,grid in cases:
                        struct.pack_into('<f',scratch,0,grid)
                        struct.pack_into('<f',scratch,8,incoming)
                        self.assertEqual(call(C.addressof(scratch),C.addressof(out))&255,1)
                        clamped=enabled and abs(grid-incoming)>story.WAILING_PLAYER_HEIGHT_STEP
                        expected=(incoming-.5*index) if clamped else grid
                        self.assertAlmostEqual(out.value,expected,places=3,msg=(site,enabled,incoming,grid))
        finally:mapped.close()

    def test_stonetalon_uses_native_outdoor_terrain_and_manual_camps(self):
        import stonetalon_zone as Z
        image=missions.Builder(self.patched);record=self.state['catalog']+story.INDEX['stonetalon']*story.RECORD
        self.assertEqual(image.read(record+192,20),struct.pack('<II3f',1,406,*Z.START))
        self.assertEqual(struct.unpack('<f',image.read(record+216,4))[0],Z.RADIUS)
        self.assertNotIn('stonetalon',self.state['ground_states'])
        for offset,stride,fmt in ((56,16,'<Q2f'),(104,8,'<2f')):
            ptr,count=struct.unpack('<QQ',image.read(record+offset,16))
            self.assertEqual(count,3)
            for k,p in enumerate(Z.CAMPS):self.assertEqual(struct.unpack(fmt,image.read(ptr-image.base+k*stride,stride))[-2:],p[:2])
        self.assertEqual(story.predecessors(True)[story.INDEX['stonetalon']],story.INDEX['wailing'])

    def test_stranglethorn_jungle_is_separate_from_preserved_native_arena(self):
        import stranglethorn_zone as Z
        image=missions.Builder(self.patched);catalog=self.state['catalog'];record=catalog+story.INDEX['stv']*story.RECORD
        self.assertEqual(image.read(record+192,20),struct.pack('<II3f',0,33,*Z.START))
        self.assertEqual(struct.unpack('<f',image.read(record+216,4))[0],Z.RADIUS)
        self.assertNotIn('stv',self.state['ground_states'])
        for offset,stride,fmt in ((56,16,'<Q2f'),(104,8,'<2f')):
            ptr,count=struct.unpack('<QQ',image.read(record+offset,16));self.assertEqual(count,3)
            self.assertEqual([struct.unpack(fmt,image.read(ptr-image.base+k*stride,stride))[-2:] for k in range(3)],[p[:2] for p in Z.CAMPS])
        base=missions.Builder(missions.remove(self.patched))
        original=struct.unpack('<Q',base.read(missions.PROFILE['slices'][0],8))[0]-base.base
        self.assertEqual(image.read(catalog+6*story.RECORD,story.RECORD),base.read(original+6*story.RECORD,story.RECORD))
        spec=story.ZONES['stv']
        self.assertEqual([name for name,_ in spec['bosses']],["Sin'Dall","Bhag'thera",'Tethis','Colonel Kurzen','King Bangalash'])
        self.assertEqual([name for name,_ in spec['enemies'][-3:]],['Kurzen Elite',"Mosh'Ogg Shaman","Mosh'Ogg Lord"])

    def test_barrens_uses_savannah_and_elites_without_changing_durotar(self):
        import barrens_zone as Z
        image=missions.Builder(self.patched);catalog=self.state['catalog'];record=catalog+story.INDEX['barrens']*story.RECORD
        self.assertEqual(image.read(record+192,20),struct.pack('<II3f',1,17,*Z.START))
        self.assertEqual(struct.unpack('<f',image.read(record+216,4))[0],Z.RADIUS)
        self.assertNotIn('barrens',self.state['ground_states'])
        for offset,stride,fmt in ((56,16,'<Q2f'),(104,8,'<2f')):
            ptr,count=struct.unpack('<QQ',image.read(record+offset,16));self.assertEqual(count,3)
            self.assertEqual([struct.unpack(fmt,image.read(ptr-image.base+k*stride,stride))[-2:] for k in range(3)],[p[:2] for p in Z.CAMPS])
        base=missions.Builder(missions.remove(self.patched));original=struct.unpack('<Q',base.read(missions.PROFILE['slices'][0],8))[0]-base.base
        # Starter subtitle/blurb pointers are relocated by the existing story patch.
        for offset,length in ((0,40),(56,112),(184,56)):
            self.assertEqual(image.read(catalog+12*story.RECORD+offset,length),base.read(original+12*story.RECORD+offset,length))
        self.assertEqual(story.predecessors(True)[story.INDEX['barrens']],12)
        self.assertEqual(story.predecessors(True)[story.INDEX['wailing']],story.INDEX['barrens'])
        self.assertEqual([n for n,_ in story.ZONES['barrens']['enemies'][-3:]],['Aean Swiftriver','Hannah Bladeleaf','Marcus Bel'])

    def test_story_map_title_toggles_and_picking_closes(self):
        import story_map
        mapped = Mapped(self.patched)
        try:
            self.set_state(mapped, (1 << story.TOTAL)-1)
            state = self.state['story_map']
            opened = C.c_uint8.from_address(mapped.base+state)
            picked = C.c_uint32.from_address(mapped.base+state+4)
            site = 0x20cdb8
            mapped.write(site+9, bytes.fromhex('c3'))
            # r9 = hero (zone String at +0x18 cap, +0x20 ptr, +0x28 len); r12 = any readable slot.
            wrapper = bytes.fromhex('5341544155' '4883ec30' '4989c9' '4c8d642428')+mapped.call(site)                 + bytes.fromhex('4883c430' '415d415c5b' 'c3')
            call = mapped.function(wrapper, [C.c_void_p])
            hero = C.create_string_buffer(0x40)

            def zone(text):
                raw = C.create_string_buffer(text.encode(), len(text))
                hero.keep = raw
                struct.pack_into('<QQQ', hero, 0x18, len(text), C.addressof(raw), len(text))
                call(C.addressof(hero))
                cap, ptr, length = struct.unpack_from('<QQQ', hero, 0x18)
                return cap, C.string_at(ptr, length).decode()

            picked.value, opened.value = story.INDEX['westfall'], 0
            self.assertEqual(zone('story-map'), (0, 'westfall'))   # opens; the zone it stood for returns
            self.assertEqual(opened.value, 1)
            self.assertEqual(zone('westfall')[1], 'westfall')       # same zone: stays open
            self.assertEqual(opened.value, 1)
            self.assertEqual(zone('story-map'), (0, 'westfall'))   # the title again closes it
            self.assertEqual(opened.value, 0)
            zone('story-map')
            self.assertEqual(zone('elwynn')[1], 'elwynn')           # picking another zone closes it
            self.assertEqual((opened.value, picked.value), (0, 0))
            lookup = mapped.function(bytes.fromhex('4883ec28')+mapped.call(story.LOOKUP)+bytes.fromhex('4883c428c3'),
                                     [C.c_char_p, C.c_uint64])
            picked.value = story.INDEX['stv']
            self.assertEqual(lookup(story_map.TOGGLE_ID, len(story_map.TOGGLE_ID)), story.INDEX['stv'])
        finally:
            mapped.close()

    def test_map_does_not_spawn_click_targets_behind_it(self):
        import story_map
        mapped = Mapped(self.patched)
        try:
            opened = C.c_uint8.from_address(mapped.base+self.state['story_map'])
            counter = C.c_uint32()
            for site, target in story_map.COVERED_PANELS:
                # Execute the production call gate with a harmless panel stub.
                mapped.write(target, bytes.fromhex('48b8')+struct.pack('<Q', C.addressof(counter))
                             +bytes.fromhex('ff00c3'))
                mapped.write(site+5, b'\xc3')
                call = mapped.function(bytes.fromhex('4883ec28')+mapped.call(site)
                                       +bytes.fromhex('4883c428c3'), [])
                for mode, expected in ((0, 1), (1, 0), (2, 0), (0, 1)):
                    counter.value, opened.value = 0, mode
                    call()
                    self.assertEqual(counter.value, expected, (site, mode))
        finally:
            mapped.close()

    def test_coop_ignores_zone_progress(self):
        mapped = Mapped(self.patched)
        try:
            mapped.write(0x5b4d502, bytes.fromhex('b801000000c3'))
            mapped.write(0x5b4d4eb, bytes.fromhex('31c0c3'))
            call = mapped.function(bytes.fromhex('4883ec28')+mapped.call(0x5b4d4df)+bytes.fromhex('4883c428c3'), [])
            self.assertEqual(call(), 0)
            image = missions.Builder(self.patched)
            for site in (0x5c7f2be, 0x5c7f3ba):
                self.assertEqual(image.read(site, 3), bytes.fromhex('f99090'))
        finally:
            mapped.close()

    def test_picker_lights_only_unlocked_races(self):
        mapped = Mapped(self.patched)
        try:
            mapped.write(0x1fb573, b'\xc3')
            # rbp = scratch; the allowed Vec<u8> is {cap, ptr, len} at +0x398.
            wrapper = bytes.fromhex('554883ec204889cd')+mapped.call(0x1fb56c)+bytes.fromhex('4883c4205dc3')
            call = mapped.function(wrapper, [C.c_void_p])
            buffer = C.create_string_buffer(0x620)
            scratch = (C.addressof(buffer)+15) & ~15  # the original movaps needs alignment
            races = bytes([1, 22, 3, 4, 10, 7, 2, 52, 5, 6, 8, 86, 0, 9])
            allowed = C.create_string_buffer(races)
            C.memmove(scratch+0x398, struct.pack('<QQQ', len(races), C.addressof(allowed), len(races)), 24)
            call(scratch)
            length = C.c_uint64.from_address(scratch+0x3a8).value
            self.assertEqual(allowed.raw[:length], bytes([1, 3, 4, 7, 2, 5, 6, 8]))
        finally:
            mapped.close()

    def test_faction_lines_and_lock_hints(self):
        mapped = Mapped(self.patched)
        try:
            mapped.write(0x20d4b7, bytes.fromhex('4889c8c3'))  # return the text length
            mapped.write(0x20d36d, bytes.fromhex('31c0c3'))
            # rbx = zone index slot. The bridge writes the caller's String at
            # rsp+0x230; inside this call that is the wrapper's rsp+0x228.
            wrapper = bytes.fromhex('5355574157' '4881ec28040000' '4889cb' '4889d5' '4489c7')+mapped.call(0x20d362)
            wrapper += bytes.fromhex('488b8c2428020000' '488b942430020000' '48894d00' '48895508')
            wrapper += bytes.fromhex('4881c428040000' '415f5f5d5bc3')
            call = mapped.function(wrapper, [C.c_void_p, C.c_void_p, C.c_uint64])  # dil = locked
            alliance, horde = (missions.FACTION_LINES[z][0] for z in (0, 12))
            dungeon = story.DUNGEON_LINE[0]
            for hero_horde in (False, True):
                self.set_state(mapped, 0, hero_horde)
                for locked in (0, 1):
                    for zone in range(story.TOTAL):
                        if zone in (0, 12):
                            text = alliance if zone == 0 else horde
                        elif zone in story.DUNGEONS:
                            text = None if locked else dungeon
                        elif zone in story.ALLIANCE_PATH[1:]:
                            text = alliance if hero_horde or not locked else None
                        elif zone in story.HORDE_PATH[1:]:
                            text = horde if not hero_horde or not locked else None
                        else:
                            text = None
                        index, out = C.c_uint64(zone), (C.c_uint64*2)()
                        length = call(C.byref(index), out, locked)
                        if text is None:
                            self.assertEqual(length, 0, (hero_horde, locked, zone))
                            continue
                        self.assertEqual(out[0], 0)  # capacity 0: never freed
                        self.assertEqual(C.string_at(out[1], length), text.encode(), (hero_horde, locked, zone))
            # A locked card names the previous zone on the hero's own path.
            mapped.write(0x20d37e, bytes.fromhex('4889c8c3'))
            hint = mapped.function(bytes.fromhex('534883ec204889cb')+mapped.call(0x20d378)+bytes.fromhex('4883c4205bc3'), [C.c_void_p])
            for hero_horde in (False, True):
                self.set_state(mapped, 0, hero_horde)
                pred = story.predecessors(hero_horde)
                for zone in range(1, story.TOTAL):
                    index = C.c_uint64(zone)
                    self.assertEqual(hint(C.byref(index)), pred[zone], (hero_horde, zone))
            self.assertEqual(story.predecessors(False)[story.STV], 1)
            self.assertEqual(story.predecessors(True)[story.STV], story.INDEX['stonetalon'])
            self.assertEqual(story.predecessors(False)[1], story.INDEX['deadmines'])
            self.assertEqual(story.predecessors(True)[story.INDEX['deadmines']], story.INDEX['barrens'])
            self.assertEqual(story.predecessors(False)[story.INDEX['wailing']], story.INDEX['westfall'])
        finally:
            mapped.close()


@unittest.skipIf(LuaRuntime is None, 'Requires Lua 5.1 test runtime')
class StoryTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime()
        self.lua.execute('''
frames={}; methods={}; texts={};
function methods:SetScript(k,v) self[k]=v end
function methods:SetText(v) self.text=v; texts[v]=true end
function methods:SetWidth(v) self.width=v end
function methods:GetWidth() return rawget(self,"width") or 1280 end
function methods:GetStringHeight() return 100 end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false end
function methods:SetAlpha(v) self.alpha=v end
function newframe(name)
 local f=setmetatable({}, {__index=function(t,k) return methods[k] or function() end end});
 table.insert(frames,f); if name then _G[name]=f end; return f
end
function CreateFrame(_,name) return newframe(name) end
function methods:CreateFontString() return newframe() end
UIParent=newframe();
AZS_ZONE={}; phase=nil; runtime=nil;
function AZS_GetPhase() return phase end
function AZS_GetRunTime() return runtime end
function tick(dt) arg1=dt; frames[2].OnUpdate() end
''')
        self.lua.execute(Path(__file__).with_name('starter_story.lua').read_text())

    def state(self, zone='elwynn', phase='playing', time=0):
        self.lua.globals().AZS_ZONE.zone = zone
        self.lua.globals().phase = phase
        self.lua.globals().runtime = time
        self.lua.eval('tick')(0.2)

    def test_story_matches_mission_and_fades_out(self):
        for zone in missions.STORIES:
            self.state(zone)
            self.assertTrue(self.lua.globals().ASRStarterStory.shown)
            self.assertTrue(self.lua.globals().texts[missions.STORIES[zone]])
            self.lua.eval('tick')(20)
            self.assertFalse(self.lua.globals().ASRStarterStory.shown)
            self.state(zone, None, None)

    def test_skip_does_not_reopen_but_new_run_does(self):
        self.state()
        self.lua.execute('for _,f in ipairs(frames) do if f.text=="Continue" then f.OnClick() end end')
        self.state()
        self.assertFalse(self.lua.globals().ASRStarterStory.shown)
        self.state(phase=None, time=None)
        self.state()
        self.assertTrue(self.lua.globals().ASRStarterStory.shown)

    def test_no_intro_for_other_zones_or_late_party_join(self):
        self.state('duskwood')
        self.assertIsNone(self.lua.globals().ASRStarterStory)
        self.state('durotar', time=45)
        self.assertIsNone(self.lua.globals().ASRStarterStory)

    def test_retry_and_zone_change(self):
        self.state()
        self.state(time=30)
        self.lua.eval('tick')(20)
        self.state(time=0)
        self.assertTrue(self.lua.globals().ASRStarterStory.shown)
        self.state('durotar')
        self.assertTrue(self.lua.globals().texts[missions.STORIES['durotar']])

    def test_native_zone_metadata_and_victory(self):
        self.lua.globals().AZS_ZONE.zname = 'Elwynn Forest'
        self.state(zone='elwynn')
        self.assertTrue(self.lua.globals().ASRStarterStory.shown)
        self.state(zone='elwynn', phase='victory')
        self.assertFalse(self.lua.globals().ASRStarterStory.shown)


if __name__ == '__main__':
    unittest.main()
