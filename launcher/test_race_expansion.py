"""Execute expanded native bridges against all byte-sized race IDs."""
import ctypes as C
import json
from pathlib import Path
import struct
import sys
import unittest

import bloodelf_patch as bp
import character_equipment_patch as equipment
from durotar_patch import sections
from race_catalog import ADDITIONS, BASE_IDS, PLAYABLE_IDS, PORTRAITS
from race_patch import Image, apply, existing
from race_picker_patch import groups

INSTALLED = Path(__file__).resolve().parents[1] / 'downloads/race-expansion/baseline/ASR.exe'
FOLDERS = ('Worgen', 'KulTiran', 'Draenei', 'EarthenDwarf', 'DarkIronDwarf',
           'LightforgedDraenei', 'VoidElf', 'Mechagnome', 'Dracthyr', 'Harronir',
           'Nightborne', 'HighmountainTauren', 'MagharOrc', 'ZandalariTroll',
           'Vulpera', 'Pandaren', 'Goblin')
PREFIXES = ('Wo', 'Kt', 'Dr', 'Ed', 'Di', 'Ld', 'Ve', 'Mg', 'Dt', 'Hr',
            'Nb', 'Ht', 'Mo', 'Za', 'Vu', 'Pa', 'Go')
CATALOG = {r.id: dict(folder=f, prefix=p) for r, f, p in zip(ADDITIONS, FOLDERS, PREFIXES)}


class Mapped:
    def __init__(self, data):
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.VirtualAlloc.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32]
        self.kernel.VirtualAlloc.restype = C.c_void_p
        self.kernel.VirtualFree.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
        _, opt, _, secs = sections(data)
        self.size = struct.unpack_from('<I', data, opt+56)[0]
        preferred = struct.unpack_from('<Q', data, opt+24)[0]
        self.base = self.kernel.VirtualAlloc(None, self.size+65536, 0x3000, 0x40)
        if not self.base:
            raise OSError(C.get_last_error())
        self.cursor = self.size
        for _, va, raw, size, _ in secs:
            self.write(va, data[raw:raw+size])
        image = Image(data)
        rva, length = struct.unpack_from('<II', data, opt+152)
        reloc, at = image.read(rva, length), 0
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


class CatalogTests(unittest.TestCase):
    def test_horn_texture_uses_default_marking_dependency(self):
        from race_assets import Choices
        class Custom:
            options = {'Horn Markings': 1}
            def choices(self, name):
                return [12] if name == 'Horn Markings' else []
            def texture(self, choice, target, related=None):
                return 900 if target == 10 and related == 12 else None
        choice = Choices(Custom(), 28)
        self.assertEqual(choice.texture(44, 10), 900)
        self.assertIsNone(choice.texture(44, 10, 13))

    def test_zandalari_tusks_are_selectable_facial_geosets(self):
        from race_assets import Choices
        from character_upgrade import mapping
        class Custom:
            options = {'Tusks': 1}
            def choices(self, name):
                return [11, 12] if name == 'Tusks' else []
            def geoset(self, choice, group):
                return 4007 if choice == 11 and group == 40 else 4001 if choice == 12 and group == 40 else None
        geosets, _, facial = mapping(Choices(Custom(), 31))
        self.assertEqual((geosets[4007], geosets[4001]), (102, 103))
        self.assertEqual(facial, [(0, [2, 0, 0]), (1, [3, 0, 0])])

    def test_collection_selectors_do_not_import_all_variants_for_none(self):
        from race_assets import collection_geoset
        self.assertIsNone(collection_geoset((4489412, 14, -1)))
        self.assertIsNone(collection_geoset((5792408, 1, 0)))
        self.assertEqual(collection_geoset((4375631, 24, 1)), 2401)
        self.assertEqual(collection_geoset((6255032, 0, 2)), 2)

    def test_dragon_wings_keep_the_third_skin_atlas_tile(self):
        from test_retail_m2 import retail_files
        import retail_m2
        from race_assets import DragonConverter
        source, skeleton, skin = retail_files()
        raw = bytearray(retail_m2.chunks(source)['MD21'])
        _, texture = retail_m2.arr(raw, 0x50)
        struct.pack_into('<I', raw, texture, 10)
        wrapped = b'MD21'+struct.pack('<I', len(raw))+raw
        result = DragonConverter(wrapped, skeleton, skin, 'DragonWing', {0}, {0: 0}, []).convert()
        _, tex = retail_m2.arr(result, 0x5C)
        self.assertEqual(struct.unpack_from('<I', result, tex)[0], 8)
        _, verts = retail_m2.arr(result, 0x44)
        self.assertAlmostEqual(struct.unpack_from('<f', result, verts+32)[0], 0.5625)

    def test_requested_roster_and_unique_portrait_cells(self):
        self.assertEqual(len(ADDITIONS), 17)
        self.assertEqual(len(set(PLAYABLE_IDS)), 26)
        cells = [PORTRAITS[r] for r in PLAYABLE_IDS]
        self.assertEqual(len(set(cells)), 26)
        self.assertTrue(all(0 <= x <= 960 and y in (0, 64) for x, y in cells))
        self.assertEqual(set(groups()[0]) | set(groups()[1]), set(PLAYABLE_IDS))

    def test_merged_customization_preserves_the_body_rig_and_valid_view(self):
        from test_retail_m2 import retail_files
        import retail_m2
        from race_model_merge import merge
        from verify_character_upgrade import model
        body = retail_m2.Converter(*retail_files(), 'Body', {0}, {0: 0}, []).convert()
        accessory = retail_m2.Converter(*retail_files(), 'Hair', {0}, {0: 0}, []).convert()
        result, report = merge(body, accessory, 102)
        self.assertIn(102, model(result, 'Merged'))
        self.assertEqual(struct.unpack_from('<I', result, 0x44)[0], 6)
        self.assertEqual(report['indices'], 3)
        count, offset = retail_m2.arr(body, 0x34)
        self.assertEqual(result[offset:offset+count*108], body[offset:offset+count*108])


@unittest.skipUnless(INSTALLED.exists() and sys.platform == 'win32', 'Reviewed native Windows build required')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patched = apply(INSTALLED.read_bytes(), CATALOG)

    def setUp(self):
        self.map = Mapped(self.patched)
        self.addCleanup(self.map.close)

    def test_catalog_identity_and_all_sparse_lookup_ids(self):
        fn = self.map.function(bytes.fromhex('4883ec28')+self.map.call(0x5ab4f70)+
                               bytes.fromhex('488b40504883c428c3'), [C.c_uint32])
        for race in range(256):
            self.assertEqual(fn(race), race if race in PLAYABLE_IDS else 1, race)

    def test_transition_accepts_only_playable_ids(self):
        p = bp.PROFILE['transition']
        self.map.write(p['accepted'], bytes.fromhex('b801000000c3'))
        self.map.write(p['fallback'], bytes.fromhex('31c0c3'))
        fn = self.map.function(bytes.fromhex('574883ec2089cfb85a000000')+self.map.call(p['rva'])+
                               bytes.fromhex('4883c4205fc3'), [C.c_uint32])
        for race in range(256):
            self.assertEqual(fn(race), int(race in PLAYABLE_IDS), race)

    def test_horde_membership_for_all_race_bytes(self):
        p = bp.PROFILE['horde']
        self.map.write(p['resume'], bytes.fromhex('0fb6c2c3'))
        fn = self.map.function(bytes.fromhex('534883ec2089cb80eb02')+self.map.call(p['rva'])+
                               bytes.fromhex('4883c4205bc3'), [C.c_uint32])
        horde = {2, 5, 6, 8, 10} | {r.id for r in ADDITIONS if r.faction == 'horde'}
        for race in range(256):
            self.assertEqual(fn(race), int(race in horde), race)

    def test_customization_loader_visits_all_26_sparse_race_ids(self):
        site = bp.PROFILE['render']['ranges_hook']['rva']
        self.map.write(site+5, b'\xc3')
        fn = self.map.function(bytes.fromhex('564883ec204889c8')+self.map.call(site)+
                               bytes.fromhex('89f04883c4205ec3'), [C.c_uint64])
        self.assertEqual([fn(i) for i in range(26)], list(PLAYABLE_IDS))

    def test_spawn_displays_for_every_race_and_both_sexes(self):
        image = Image(self.patched)
        for sex, label in enumerate(('male', 'female')):
            at = image.lea(bp.PROFILE['display'][label+'_ref'])
            table = struct.unpack('<85I', image.read(at, 85*4))
            for rid in range(2, 87):
                if rid in CATALOG:
                    self.assertEqual(table[rid-2], 200000+rid*2+sex)
                elif rid not in BASE_IDS:
                    self.assertEqual(table[rid-2], 49+sex)

    def test_helmet_prefixes_and_unknown_race_fallback(self):
        self.map.write(equipment.SITE+len(equipment.BEFORE), bytes.fromhex('4889c8c3'))
        fn = self.map.function(bytes.fromhex('41574883ec204189cf89d1')+self.map.call(equipment.SITE)+
                               bytes.fromhex('4883c420415fc3'), [C.c_uint32, C.c_uint32])
        legacy = (b'Hu', b'Or', b'Dw', b'Ni', b'Sc', b'Ta', b'Gn', b'Tr')
        for race in range(256):
            index = max(1, min(race, 8))
            prefix = CATALOG[race]['prefix'].encode() if race in CATALOG else b'Be' if race == 10 else legacy[index-1]
            self.assertEqual(C.string_at(fn(race, index*16), 2), prefix, race)

    def test_faction_loops_and_ids(self):
        self.map.write(0x1fbe8a, bytes.fromhex('b801000000c3'))
        self.map.write(0x1fc900, bytes.fromhex('31c0c3'))
        loop = self.map.function(bytes.fromhex('554881ec800b00004889e548898d900700004889d0')+
                                 self.map.call(0x1fbe80)+bytes.fromhex('4881c4800b00005dc3'),
                                 [C.c_uint64, C.c_uint64])
        for group, races in enumerate(groups(), 1):
            for i in range(len(races)+1):
                self.assertEqual(loop(group, i), int(i < len(races)))
        self.map.write(0x1fbe9d, bytes.fromhex('400fb6c7c3'))
        fn = self.map.function(bytes.fromhex('57554881ec800b00004889e548898d900700004889d0')+
                               self.map.call(0x1fbe95)+bytes.fromhex('4881c4800b00005d5fc3'),
                               [C.c_uint64, C.c_uint64])
        for group, races in enumerate(groups(), 1):
            self.assertEqual([fn(group, i) for i in range(len(races))], races)

    def test_class_lists_inherit_explicit_templates(self):
        self.map.write(0x5acc4c7, bytes.fromhex('48891a4c897208c3'))
        fn = self.map.function(bytes.fromhex('5341564883ec2889c8ffc8')+self.map.call(0x5acc4ae)+
                               bytes.fromhex('4883c428415e5bc3'), [C.c_uint32, C.c_void_p])
        for cls in range(1, 12):
            out = (C.c_uint64*2)()
            fn(cls, out)
            allowed = list(C.string_at(out[1], out[0]))
            self.assertEqual(len(set(allowed)), len(allowed))
            for race in ADDITIONS:
                self.assertEqual(race.id in allowed, race.template in allowed, (cls, race.name))

    def test_portrait_coordinates_for_every_new_race(self):
        self.map.write(0x1fc2c0, bytes.fromhex('660f7ec248c1e0204809d0c3'))
        fn = self.map.function(bytes.fromhex('574883ec2089cf')+self.map.call(0x1fc19b)+
                               bytes.fromhex('4883c4205fc3'), [C.c_uint32])
        for rid in (*CATALOG, 10):
            x, y = PORTRAITS[rid]
            self.assertEqual(fn(rid), (y << 32) | struct.unpack('<I', struct.pack('<f', x))[0], rid)

    def test_reapply_and_damaged_payload_and_hook_refusal(self):
        self.assertEqual(apply(self.patched, CATALOG), self.patched)
        self.assertEqual(len(existing(self.patched)['race_ids']), 26)
        for at in (self.patched.index(b'ASR expanded races v1')+120,
                   Image(self.patched).offset(bp.PROFILE['transition']['rva'])+1):
            damaged = bytearray(self.patched)
            damaged[at] ^= 1
            with self.assertRaises(ValueError):
                apply(damaged, CATALOG)


if __name__ == '__main__':
    unittest.main()
