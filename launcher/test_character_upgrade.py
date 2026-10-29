"""Compatibility contracts for character/equipment conversion and the helmet bridge."""
import ctypes
from pathlib import Path
import struct
import sys
import unittest

import character_equipment_patch as equipment
from character_upgrade import legacy_root_scale, mapping
from durotar_patch import sections
import retail_m2
import retail_textures
from test_retail_m2 import retail_files
from verify_character_upgrade import verify

INSTALLED = Path(__file__).resolve().parents[1] / 'downloads/race-expansion/baseline/ASR.exe'


class FacialTextureTests(unittest.TestCase):
    def build(self, painted=True, palette=False):
        class Custom:
            def choices(self, option):
                return {'Skin Color': [1], 'Face': [2], 'Hair Color': [3],
                        'Hair Style': [4], 'Facial Hair': [5]}.get(option, [])
            def texture(self, choice, target, related=None):
                return {(1, 1): 10, (1, 2): 20, (3, 10): 30,
                        (5, 8): 50 if painted else None}.get((choice, target))
            def geoset(self, choice, group):
                return 102 if group == 1 else 2
        class Builder(retail_textures.Builder):
            def image(self, fid, height):
                color = {10: (100, 60, 40, 255), 20: (10, 90, 10, 255),
                         30: (40, 20, 10, 255), 50: (50, 30, 20, 128)}[fid]
                w, h = (8, 4) if fid == 10 else (4, 4)
                return w, h, bytearray(bytes(color)*(w*h))
            def put(self, name, image):
                path = self.folder+'\\'+name+'.blp'
                self.files[path] = image
                return path
        return Builder(None, Custom(), 1, 0, r'Character\Human', 'HumanMale', [0], 1,
                       shared_hair=False, preserve_body_palette=palette).build()

    def test_facial_overlay_is_cut_from_the_retail_mask_and_keeps_alpha(self):
        result = self.build()
        row = next(r for r in result.rows if r[2] == 2)
        self.assertIn('HumanMaleFacialLowerHair', row[5])
        self.assertIn('HumanMaleFacialUpperHair', row[6])
        self.assertEqual(result.files[row[5]][2][3], 128)
        empty = self.build(painted=False)
        row = next(r for r in empty.rows if r[2] == 2)
        self.assertEqual(row[5:8], ('', '', ''))

    def test_extra_atlas_keeps_fur_and_original_body_palette_separate(self):
        result = self.build(palette=True)
        row = next(r for r in result.rows if r[2] == 0)
        width, height, pixels = result.files[row[6]]
        self.assertEqual((width, height), (8, 4))
        self.assertEqual(tuple(pixels[:4]), (10, 90, 10, 255))
        self.assertEqual(tuple(pixels[4*4:4*5]), (100, 60, 40, 255))


class EquipmentModelTests(unittest.TestCase):
    def test_retail_hair_keeps_texture_repeat_flags(self):
        model, skeleton, skin = retail_files()
        m = bytearray(retail_m2.chunks(model)['MD21'])
        _, at = struct.unpack_from('<II', m, 0x50)
        struct.pack_into('<I', m, at+16+4, 3)
        wrapped = b'MD21'+struct.pack('<I', len(m))+bytes(m)
        out = retail_m2.Converter(wrapped, skeleton, skin, 'Wrap', {0}, {0: 0}, []).convert()
        _, at = struct.unpack_from('<II', out, 0x5C)
        self.assertEqual(struct.unpack_from('<II', out, at+16), (6, 3))

    def test_oral_palette_is_kept_out_of_the_overwritten_face_strip(self):
        model, skeleton, skin = retail_files()
        m = bytearray(retail_m2.chunks(model)['MD21'])
        _, at = struct.unpack_from('<II', m, 0x3C)
        for i, uv in enumerate(((0.1, 0.7), (0.2, 0.7), (0.1, 0.9))):
            struct.pack_into('<2f', m, at+48*i+32, *uv)
        _, at = struct.unpack_from('<II', m, 0x50)
        struct.pack_into('<I', m, at+16, 8)
        wrapped = b'MD21'+struct.pack('<I', len(m))+bytes(m)
        c = retail_m2.Converter(wrapped, skeleton, skin, 'Palette', {0}, {0: 0, 1704: 1704}, [])
        result = retail_m2.preserve_body_palette(c.convert(), c)
        n, at = struct.unpack_from('<II', result, 0x44)
        self.assertEqual(n, 9)
        self.assertEqual(c.report['preserved_body_palette_triangles'], 1)
        # Fur stays on the left, original body detail stays on the right.
        self.assertAlmostEqual(struct.unpack_from('<f', result, at+48*3+32)[0], 0.05)
        self.assertAlmostEqual(struct.unpack_from('<f', result, at+48*6+32)[0], 0.6)
        self.assertAlmostEqual(struct.unpack_from('<f', result, at+48*7+32)[0], 0.7)
        _, view = struct.unpack_from('<II', result, 0x4C)
        self.assertEqual(struct.unpack_from('<I', result, view+8)[0], 6)

    def test_legacy_height_scales_root_track_without_detaching_mesh_or_child_bones(self):
        original = retail_m2.Converter(*retail_files(), 'Scale', {0}, {0: 0}, []).convert()
        scaled = legacy_root_scale(original, 0.75)
        n, at = struct.unpack_from('<II', original, 0x44)
        self.assertEqual(scaled[at:at+n*48], original[at:at+n*48])
        _, bones = struct.unpack_from('<II', scaled, 0x34)
        count, values = struct.unpack_from('<II', scaled, bones+68+20)
        self.assertEqual(count, 1)
        self.assertEqual(struct.unpack_from('<3f', scaled, values), (0.75, 0.75, 0.75))
        self.assertEqual(struct.unpack_from('<I', scaled, bones+108+68+20)[0], 0)
        self.assertAlmostEqual(struct.unpack_from('<f', scaled, 0xB4+20)[0],
                               struct.unpack_from('<f', original, 0xB4+20)[0]*0.75)
        scaled_again = legacy_root_scale(scaled, 0.5)
        self.assertEqual(struct.unpack_from('<3f', scaled_again, values), (0.375, 0.375, 0.375))

    def test_lod_skin_uses_its_global_vertex_window(self):
        model, skeleton, skin = retail_files()
        m = bytearray(retail_m2.chunks(model)['MD21'])
        _, old_at = struct.unpack_from('<II', m, 0x3C)
        verts = bytearray(m[old_at:old_at+3*48])
        shifted = bytearray(verts)
        for i in range(3):
            x = struct.unpack_from('<f', shifted, i*48)[0]
            struct.pack_into('<f', shifted, i*48, x+100)
        at = len(m)
        m.extend(verts+shifted)
        struct.pack_into('<II', m, 0x3C, 6, at)
        skin = bytearray(skin)
        struct.pack_into('<I', skin, 44, 3)
        wrapped = b'MD21'+struct.pack('<I', len(m))+bytes(m)
        out = retail_m2.Converter(wrapped, skeleton, bytes(skin), 'LOD', {0}, {0: 0}, []).convert()
        _, vertices = struct.unpack_from('<II', out, 0x44)
        self.assertEqual(struct.unpack_from('<f', out, vertices)[0], 100)
        _, view = struct.unpack_from('<II', out, 0x4C)
        self.assertEqual(struct.unpack_from('<I', out, view+40)[0], 256)

    def test_native_archive_name_guard_rejects_unmountable_multi_letter_suffix(self):
        with self.assertRaisesRegex(ValueError, 'native loader requires'):
            verify([Path('patch-ZC.MPQ')], Path('unused'))

    def test_tauren_skin_extra_stays_replaceable_instead_of_disappearing(self):
        model, skeleton, skin = retail_files()
        model = bytearray(model)
        _, at = struct.unpack_from('<II', model, 8+0x50)
        struct.pack_into('<I', model, 8+at, 8)
        c = retail_m2.Converter(bytes(model), skeleton, skin, 'Fur', {0}, {0: 0}, [])
        out = c.convert()
        _, textures = struct.unpack_from('<II', out, 0x5C)
        self.assertEqual(struct.unpack_from('<I', out, textures)[0], 8)
        self.assertEqual(c.report['indices'], 3)
        _, lookup = struct.unpack_from('<II', out, 0x7C)
        self.assertEqual(struct.unpack_from('<H', out, lookup+2*8)[0], 0)

    def test_armor_uvs_are_not_remapped_like_character_body_uvs(self):
        converter = retail_m2.Converter(*retail_files(), 'Helmet', {0}, {0: 0}, [], remap_body=False)
        out = converter.convert()
        n, at = struct.unpack_from('<II', out, 0x44)
        self.assertEqual(n, 3)
        self.assertEqual([struct.unpack_from('<2f', out, at+i*48+32) for i in range(n)],
                         [(0.25, 0.5), (0.75, 0.5), (0.25, 0.5)])

    def test_fixed_textures_are_resolved_by_index(self):
        model, skeleton, skin = retail_files()
        model = bytearray(model)
        n, at = struct.unpack_from('<II', model, 8+0x50)
        for i in range(n):
            struct.pack_into('<I', model, 8+at+16*i, 0)
        names = {0: r'ASR\First.blp', 1: r'ASR\Second.blp'}
        c = retail_m2.Converter(bytes(model), skeleton, skin, 'Test', {0}, {0: 0}, [],
                               remap_body=False, texture_names=names)
        out = c.convert()
        n, at = struct.unpack_from('<II', out, 0x5C)
        for i in range(n):
            kind, _, length, pos = struct.unpack_from('<IIII', out, at+16*i)
            self.assertEqual(kind, 0)
            self.assertEqual(out[pos:pos+length], names[i].encode()+b'\0')
        self.assertEqual(c.report['batches'], 1)

    def test_inline_skeleton_uses_the_models_array_offsets(self):
        model, skeleton, skin = retail_files()
        ch = retail_m2.chunks(skeleton)
        m = bytearray(retail_m2.chunks(model)['MD21'])
        # Use a static single-bone model; all inline directory offsets refer to m.
        m.extend(bytes((-len(m)) % 16))
        bone_at = len(m)
        m.extend(bytes(88))
        struct.pack_into('<h', m, bone_at+8, -1)
        for off in (bone_at+16, bone_at+36, bone_at+56):
            struct.pack_into('<Hh', m, off, 0, -1)
        struct.pack_into('<II', m, 0x2C, 1, bone_at)
        m.extend(bytes((-len(m)) % 16))
        sequence_at = len(m)
        n, at = struct.unpack_from('<II', ch['SKS1'], 8)
        m.extend(ch['SKS1'][at:at+64])
        struct.pack_into('<II', m, 0x1C, 1, sequence_at)
        converter = retail_m2.Converter(bytes(m), None, skin, 'Inline', {0}, {0: 0}, [], remap_body=False)
        out = converter.convert()
        self.assertEqual(struct.unpack_from('<I', out, 0x34)[0], 1)
        self.assertEqual(struct.unpack_from('<I', out, 0x1C)[0], 1)

    def test_repeated_legacy_tusk_choices_keep_both_save_values_visible(self):
        class Custom:
            race = 8
            alias = {'Facial Hair': 'Tusks'}
            options = []
            def choices(self, name):
                return [10, 11, 10] if name == 'Facial Hair' else []
            def geoset(self, choice, group):
                return {10: 4001, 11: 4002}[choice] if group == 40 else None
        custom = Custom()
        custom.c = custom
        geosets, _, facial = mapping(custom)
        self.assertEqual(geosets[4001], 102)
        self.assertEqual(geosets[4002], 103)
        self.assertEqual([picks[0] for _, picks in facial], [2, 3, 2])


@unittest.skipUnless(INSTALLED.exists(), 'Supported installed executable required')
class EquipmentBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = INSTALLED.read_bytes()
        cls.patched = equipment.apply(cls.original)

    def test_is_idempotent_and_rejects_unknown_hook(self):
        self.assertEqual(equipment.apply(self.patched), self.patched)
        data = bytearray(self.original)
        _, _, _, secs = sections(data)
        at = next(r+equipment.SITE-v for _, v, r, n, _ in secs if v <= equipment.SITE < v+n)
        data[at] ^= 1
        with self.assertRaisesRegex(ValueError, 'prefix hook'):
            equipment.apply(data)

    @unittest.skipUnless(sys.platform == 'win32', 'Executes reviewed Windows x64 bridge')
    def test_executes_all_race_ids_and_changes_only_blood_elf(self):
        data = self.patched
        _, opt, _, secs = sections(data)
        size = struct.unpack_from('<I', data, opt+56)[0]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
        kernel.VirtualAlloc.restype = ctypes.c_void_p
        kernel.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        address = kernel.VirtualAlloc(None, size+4096, 0x3000, 0x40)
        self.assertTrue(address)
        try:
            for _, va, raw, length, _ in secs:
                ctypes.memmove(address+va, data[raw:raw+length], length)
            # This bridge touches only its own RIP-relative payload and the prefix
            # table. Rebase that table, without executing the game or its imports.
            for i in range(8):
                ptr = address+equipment.TABLE-17+i*2
                ctypes.memmove(address+equipment.TABLE+i*16, struct.pack('<QQ', ptr, 2), 16)
            ctypes.memmove(address+equipment.SITE+len(equipment.BEFORE), bytes.fromhex('4889c8c3'), 4)
            site = next(raw+equipment.SITE-va for _, va, raw, n, _ in secs
                        if va <= equipment.SITE < va+n)
            target = equipment.SITE+5+struct.unpack_from('<i', data, site+1)[0]
            # (race, clamped index*16) -> prefix pointer; preserve nonvolatile r15.
            wrapper = (bytes.fromhex('41574883ec204189cf89d1') + b'\x49\xbb' +
                       struct.pack('<Q', address+target) + bytes.fromhex('41ffd34883c420415fc3'))
            ctypes.memmove(address+size, wrapper, len(wrapper))
            fn = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32)(address+size)
            prefixes = [b'Hu', b'Or', b'Dw', b'Ni', b'Sc', b'Ta', b'Gn', b'Tr']
            for race in range(256):
                index = max(1, min(race, 8))
                result = ctypes.string_at(fn(race, index*16), 2)
                self.assertEqual(result, b'Be' if race == 10 else prefixes[index-1], race)
        finally:
            kernel.VirtualFree(address, 0, 0x8000)


if __name__ == '__main__':
    unittest.main()
