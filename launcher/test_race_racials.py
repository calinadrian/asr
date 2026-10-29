"""Execute the shipped passive dispatcher against each new race's actual data."""
import ctypes as C
from pathlib import Path
import struct
import sys
import unittest

import bloodelf_patch as bp
import race_racials as racial
from race_catalog import ADDITIONS
from race_patch import apply, Image, existing
from test_race_expansion import Mapped, CATALOG, INSTALLED


class Definitions(unittest.TestCase):
    def test_every_added_race_has_a_distinct_supported_passive_kit(self):
        self.assertEqual(set(racial.KITS), {r.id for r in ADDITIONS})
        effects = []
        for kit in racial.KITS.values():
            self.assertEqual(len(kit), 3)
            self.assertEqual(len({t.name for t in kit}), 3)
            self.assertTrue(all(t.kind in racial.STATS and t.value > 0 for t in kit))
            effects.append(tuple(sorted((t.kind, t.value) for t in kit)))
        self.assertEqual(len(set(effects)), len(effects))


@unittest.skipUnless(INSTALLED.exists() and sys.platform == 'win32', 'Native Windows build required')
class NativePassives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patched = apply(INSTALLED.read_bytes(), CATALOG)

    def setUp(self):
        self.map = Mapped(self.patched)
        self.addCleanup(self.map.close)
        # Redirect only the continuation after the real passive loop to capture
        # its results. The dispatcher and all twelve cases execute unchanged.
        capture = bytearray()
        for index, reg in enumerate((13, 4, 14, 3, 10, 12, 0, 11, 0, 7, 8, 5)):
            if index in (6, 8):
                capture += bytes.fromhex('f30f1085')+struct.pack('<I', 0x80 if index == 6 else 0x70)
            capture += bytes((0xf3, 0x41 | (4 if reg >= 8 else 0), 0x0f, 0x11,
                              0x42 | ((reg & 7) << 3), index*4))
        self.map.write(0x5be94a7, bytes(capture)+b'\xc3')
        prologue = bytearray.fromhex('554881ec00020000488dac24000100004d89c2')
        epilogue = bytearray()
        # Preserve Windows x64 nonvolatile SIMD registers around the native loop.
        for reg in range(6, 16):
            rex = b'\x44' if reg >= 8 else b''
            address = bytes((0x84 | ((reg & 7) << 3), 0x24))+struct.pack('<I', (reg-6)*16)
            prologue += rex+b'\x0f\x11'+address
            epilogue += rex+b'\x0f\x10'+address
        prologue += bytes.fromhex('0f57d2450f57db450f57e4b80000803f660f6ee0')
        prologue += bytes.fromhex('c78580000000cdcc4c3f4889d0')
        prologue += bytes.fromhex('48898db0000000488d8d90000000')
        code = prologue+self.map.call(0x5be9399)+epilogue+bytes.fromhex('4881c4000200005dc3')
        self.dispatch = self.map.function(bytes(code), [C.c_void_p, C.c_uint64, C.c_void_p])

    def check_effects(self, data, count, effects):
        result = (C.c_float*12)()
        self.dispatch(data, count, C.addressof(result))
        expected = [1., 1., 0., 1., .05, 0., .8, 9., 1., 1., 0., 0.]
        for kind, value in effects:
            if kind == 7:
                expected[kind] *= 1+value
            else:
                expected[kind] += value
        for kind, value in enumerate(expected):
            self.assertAlmostEqual(result[kind], value, places=5, msg=racial.STATS[kind])

    def test_all_native_effect_kinds_change_the_correct_combat_stat(self):
        for kind in range(12):
            with self.subTest(kind=kind):
                blob = C.create_string_buffer(struct.pack('<If', kind, .125))
                self.check_effects(C.addressof(blob), 1, [(kind, .125)])

    def test_every_race_runs_its_own_passives_without_an_inherited_active(self):
        image = Image(self.patched)
        records, count = struct.unpack('<QQ', image.read(bp.PROFILE['races']['slice'], 16))
        for index in range(count):
            record = self.map.base+records-image.base+88*index
            rid = C.c_uint64.from_address(record+80).value
            if rid not in racial.KITS:
                continue
            with self.subTest(race=rid):
                ptr, length = struct.unpack('<QQ', C.string_at(record+32, 16))
                self.check_effects(ptr, length, [(t.kind, t.value) for t in racial.KITS[rid]])
                self.assertEqual(C.c_uint64.from_address(record+56).value, 0)
                ptr, length = struct.unpack('<QQ', C.string_at(record+64, 16))
                lines = [C.string_at(*struct.unpack('<QQ', C.string_at(ptr+16*i, 16))).decode()
                         for i in range(length)]
                self.assertEqual(lines, [t.line for t in racial.KITS[rid]])
        self.assertEqual(existing(self.patched)['racial_revision'], racial.REVISION)

    def test_all_locales_describe_the_applied_passives(self):
        import json
        image = Image(self.patched)
        p = bp.PROFILE['locales']
        for index in range(p['count']):
            entry = p['table']+index*p['stride']
            ptr, length = struct.unpack('<QQ', image.read(entry+32, 16))
            strings = json.loads(image.read(ptr-image.base, length))
            for race in ADDITIONS:
                key = CATALOG[race.id]['folder'].lower()
                self.assertEqual([strings[f'race.{key}.line{i+1}'] for i in range(3)],
                                 [t.line for t in racial.KITS[race.id]])

    def test_original_race_effects_and_actives_are_preserved(self):
        before, after = Image(INSTALLED.read_bytes()), Image(self.patched)
        old, count = struct.unpack('<QQ', before.read(bp.PROFILE['races']['slice'], 16))
        new, _ = struct.unpack('<QQ', after.read(bp.PROFILE['races']['slice'], 16))
        for index in range(count):
            for delta, stride in ((32, 8), (48, 1)):
                op, on = struct.unpack('<QQ', before.read(old-before.base+88*index+delta, 16))
                np, nn = struct.unpack('<QQ', after.read(new-after.base+88*index+delta, 16))
                self.assertEqual(on, nn)
                self.assertEqual(before.read(op-before.base, on*stride),
                                 after.read(np-after.base, nn*stride))

    def test_empty_active_resolves_to_a_harmless_compatibility_slot(self):
        from durotar_patch import Code
        # Supply the mapped game's memcmp thunk for the original nonempty path.
        compare = (Code().raw('31c0').label('loop').raw('4d85c0').jcc('e', 'done')
                   .raw('0fb601440fb60a4429c8').jcc('ne', 'done')
                   .raw('48ffc148ffc249ffc8').jmp('loop').label('done').raw('c3'))
        self.map.write(0x600ae4b, compare.assemble(0x600ae4b))
        fn = self.map.function(bytes.fromhex('4883ec28')+self.map.call(0x5ab4fb0)+
                               bytes.fromhex('4883c428c3'), [C.c_void_p, C.c_uint64])
        ptr = fn(None, 0)
        self.assertEqual(C.c_uint32.from_address(ptr+64).value, 0)
        self.assertGreater(C.c_float.from_address(ptr+72).value, 1e8)
        self.assertEqual(C.string_at(ptr+104, 12), bytes(12))
        name, size = struct.unpack('<QQ', C.string_at(ptr, 16))
        self.assertEqual(size, 0)
        query = C.create_string_buffer(b'war_stomp')
        original = fn(C.addressof(query), 9)
        name, size = struct.unpack('<QQ', C.string_at(original, 16))
        self.assertEqual(C.string_at(name, size), b'war_stomp')
        self.assertEqual(C.c_uint32.from_address(original+64).value, 20549)



if __name__ == '__main__':
    unittest.main()
