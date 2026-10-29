import struct
import unittest

import character_preview as preview
import retail_m2
from test_retail_m2 import retail_files


class PreviewTests(unittest.TestCase):
    def model(self):
        source, skeleton, skin = retail_files()
        return retail_m2.Converter(source, skeleton, skin, 'Preview', {0}, {0: 0}, []).convert()

    def test_camera_changes_leave_gameplay_and_head_portrait_data_unchanged(self):
        original = self.model()
        fitted, _ = preview.fit(original)
        self.assertEqual(original[:0x124], fitted[:0x124])
        self.assertEqual(original[0x12c:], fitted[0x12c:len(original)])
        self.assertEqual(retail_m2.arr(fitted, 0x124)[0], 2)
        self.assertEqual(preview.fit(fitted)[0], fitted)

    def test_large_and_small_bodies_keep_actual_relative_size(self):
        small = self.model()
        large = bytearray(small)
        count, at = retail_m2.arr(large, 0x44)
        for i in range(count):
            position = struct.unpack_from('<3f', large, at+48*i)
            struct.pack_into('<3f', large, at+48*i, *(v*3 for v in position))
        _, a = preview.camera(small)
        _, b = preview.camera(large)
        self.assertEqual(b['distance'], a['distance'])
        self.assertAlmostEqual(b['height']/a['height'], 3)
        self.assertEqual(b['target_height'], a['target_height'])

    def test_offset_models_share_the_same_projected_floor(self):
        original = self.model()
        shifted = bytearray(original)
        count, at = retail_m2.arr(shifted, 0x44)
        for i in range(count):
            z = struct.unpack_from('<f', shifted, at+48*i+8)[0]
            struct.pack_into('<f', shifted, at+48*i+8, z+2)
        _, a = preview.camera(original)
        _, b = preview.camera(shifted)
        floor_a = (a['ground_height']-a['target_height'])/a['distance']
        floor_b = (b['ground_height']-b['target_height'])/b['distance']
        self.assertAlmostEqual(floor_a, floor_b)

    def test_floor_edit_refuses_unknown_native_layout(self):
        class Unknown:
            def read(self, address, length):
                return bytes(length)
            def edit(self, address, data):
                raise AssertionError('Unverified native code was modified')
        with self.assertRaises(ValueError):
            preview.remove_floor_glow(Unknown())


if __name__ == '__main__':
    unittest.main()
