"""Retail character down-conversion, texture and CASC block contracts, on synthetic files."""
import struct
import unittest
import zlib

import blp
import casc
import retail_m2
import retail_textures


class Blob:
    """Builds a buffer whose arrays are addressed from its own start, as retail chunks are."""
    def __init__(self, size):
        self.data = bytearray(size)

    def add(self, raw):
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data += raw
        return offset

    def array(self, at, count, raw):
        struct.pack_into('<II', self.data, at, count, self.add(raw) if count else 0)


def track(blob, at, keys, value_size):
    """A retail M2Track with one per-sequence key list (time, raw value)."""
    struct.pack_into('<Hh', blob.data, at, 1, -1)
    times = [struct.pack('<II', len(k), blob.add(b''.join(struct.pack('<I', t) for t, _ in k))) for k in keys]
    values = [struct.pack('<II', len(k), blob.add(b''.join(v for _, v in k))) for k in keys]
    blob.array(at + 4, len(keys), b''.join(times))
    blob.array(at + 12, len(keys), b''.join(values))


def retail_files(triangles=1):
    model = Blob(0x130)
    model.data[0:8] = b'MD20' + struct.pack('<I', 274)
    vertex = lambda x, z, u: struct.pack('<3f4B4B3f2f2f', x, 0, z, 255, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, u, 0.5, 0, 0)
    model.array(0x3C, 3, vertex(0, 0, 0.25) + vertex(1, 0, 0.75) + vertex(0, 1, 0.25))
    model.array(0x50, 2, struct.pack('<IIII', 1, 0, 0, 0) + struct.pack('<IIII', 6, 0, 0, 0))
    model.array(0x70, 1, struct.pack('<HH', 0x804, 0))
    model.array(0x78, 2, struct.pack('<2H', 0, 1))
    model.array(0x80, 2, struct.pack('<2H', 0, 1))
    model.array(0x90, 1, struct.pack('<H', 0))
    model_file = b'MD21' + struct.pack('<I', len(model.data)) + bytes(model.data)

    seqs = Blob(32)
    stand = struct.pack('<HHIfIhHIIHH', 0, 0, 1000, 0, 0x20, 0, 0, 0, 0, 150, 150) + bytes(28) + struct.pack('<hH', -1, 0)
    unknown = struct.pack('<HHIfIhHIIHH', 900, 0, 500, 0, 0x20, 0, 0, 0, 0, 0, 0) + bytes(28) + struct.pack('<hH', -1, 1)
    seqs.array(8, 2, stand + unknown)
    bones = Blob(16)
    rows = bytearray(struct.pack('<iIhHI', -1, 0, -1, 0, 0) + bytes(72) +
                     struct.pack('<iIhHI', -1, 0, 0, 0, 0) + bytes(60) + struct.pack('<3f', 0, 0, 1))
    offset = bones.add(bytes(rows))
    struct.pack_into('<II', bones.data, 0, 2, offset)
    # Bone 1 turns 90 degrees about Z in the stand sequence; the unknown sequence has no keys.
    # Retail packs each component as round(c * 32767) + 32767, stored as int16.
    half = round(0.70710678 * 32767) + 32767 - 65536
    track(bones, offset + 88 + 36, [[(0, struct.pack('<4h', 32767, 32767, half, half))], []], 8)
    skel = b''.join(tag + struct.pack('<I', len(body)) + body for tag, body in
                    ((b'SKS1', bytes(seqs.data)), (b'SKB1', bytes(bones.data))))

    skin = Blob(64)
    skin.data[0:4] = b'SKIN'
    skin.array(4, 3, struct.pack('<3H', 0, 1, 2))
    skin.array(12, 6 * triangles, struct.pack('<3H', 0, 1, 2) * 2 * triangles)
    skin.array(20, 3, bytes(12))
    n = 3 * triangles
    sub = lambda sid, start: struct.pack('<10H', sid, start >> 16, 0, 3, start & 0xFFFF, n, 1, 0, 1, 0) + bytes(28)
    skin.array(28, 2, sub(0, 0) + sub(1704, n))
    batch = lambda section, combo: struct.pack('<BbHHHHHHHHHHH', 0, 0, 0x8001, section, section, 0xFFFF, 0, 0, 2,
                                               combo, 5, 0, 0)
    skin.array(36, 2, batch(0, 0) + batch(1, 1))
    return model_file, skel, bytes(skin.data)


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.converter = retail_m2.Converter(*retail_files(), 'Test', {0}, {0: 0}, [(0, 0), (5, 0)])
        self.out = self.converter.convert()
        self.arr = lambda at: struct.unpack_from('<II', self.out, at)

    def test_writes_a_v256_model_with_only_known_sequences(self):
        self.assertEqual(self.out[:8], b'MD20' + struct.pack('<I', 256))
        count, offset = self.arr(0x1C)
        self.assertEqual(count, 1)
        ident, _, start, end = struct.unpack_from('<HHII', self.out, offset)
        self.assertEqual((ident, start, end), (0, 0, 1000))
        # An animation the model lacks falls back to stand.
        count, offset = self.arr(0x2C)
        self.assertEqual([struct.unpack_from('<hh', self.out, offset + 4 * i) for i in range(count)],
                         [(0, 0), (0, 0)])

    def test_expands_compressed_rotations_to_unit_floats(self):
        _, bones = self.arr(0x34)
        rotation = bones + 108 + 40
        (ranges, range_at), (_, times_at), (keys, values_at) = (self.arr(rotation + 4), self.arr(rotation + 12),
                                                              self.arr(rotation + 20))
        self.assertEqual((ranges, keys), (1, 1))
        quat = struct.unpack_from('<4f', self.out, values_at)
        self.assertAlmostEqual(sum(c * c for c in quat), 1, places=3)
        self.assertAlmostEqual(quat[3], 0.7071, places=3)
        self.assertEqual(struct.unpack_from('<II', self.out, range_at), (0, 0))
        self.assertEqual(struct.unpack_from('<3f', self.out, bones + 108 + 96), (0, 0, 1))

    def test_drops_unmapped_geosets_and_remaps_body_uvs(self):
        _, view = self.arr(0x4C)
        submeshes, offset = self.arr(view + 24)
        batches, batch_at = self.arr(view + 32)
        self.assertEqual((submeshes, batches), (1, 1))
        self.assertEqual(self.converter.report['dropped'], {1704: 3})
        flags, _, shader, section, _, _, _, _, count, _, coords = struct.unpack_from('<BbHHHHHHHHH', self.out, batch_at)
        self.assertEqual((shader, section, count, coords), (0, 0, 1, 0))
        _, verts = self.arr(0x44)
        uvs = [struct.unpack_from('<2f', self.out, verts + 48 * i + 32) for i in range(3)]
        self.assertEqual(uvs[0], (0.5, 0.5))                 # body: u doubled
        self.assertAlmostEqual(uvs[1][0], 0.25)              # face: moved into the classic strip
        self.assertAlmostEqual(uvs[1][1], 0.625 + 0.375 * 0.5)

    def test_portrait_bounds_follow_retained_vertices_instead_of_retail_effects(self):
        model, skeleton, skin = retail_files()
        retail = bytearray(model)
        # A retail global box can span discarded wings/effects far above the humanoid.
        struct.pack_into('<7f', retail, 8 + 0xA0, -10, -10, -1, 10, 10, 9, 17)
        result = retail_m2.Converter(bytes(retail), skeleton, skin, 'Test', {0}, {0: 0}, []).convert()
        bounds = struct.unpack_from('<7f', result, 0xB4)
        self.assertEqual(bounds[:6], (0, 0, 0, 1, 0, 1))
        self.assertAlmostEqual(bounds[6], 0.5**0.5)

    def test_refuses_more_indices_than_a_1_12_view_holds(self):
        # Two geosets of 32769 indices each: either fits alone, both together do not.
        files = retail_files(triangles=10923)
        retail_m2.Converter(*files, 'Test', {0}, {0: 0}, []).convert()
        with self.assertRaisesRegex(ValueError, '65538 indices'):
            retail_m2.Converter(*files, 'Test', {0}, {0: 0, 1704: 1704}, []).convert()


class TextureTests(unittest.TestCase):
    def image(self, w, h, alpha=255):
        return w, h, bytearray(b''.join(bytes((x * 255 // w, y * 255 // h, 80, alpha))
                                        for y in range(h) for x in range(w)))

    def test_dxt_round_trip_keeps_size_mips_and_colour(self):
        source = self.image(64, 32)
        data = blp.encode(source)
        self.assertEqual(data[:4], b'BLP2')
        self.assertEqual(blp.mip_count(data), 7)          # 64x32 down to 1x1
        w, h, px = blp.decode(data)
        self.assertEqual((w, h), (64, 32))
        error = max(abs(a - b) for a, b in zip(px, source[2]))
        self.assertLess(error, 40)
        self.assertEqual(blp.decode(data, 2)[:2], (16, 8))

    def test_transparent_images_use_dxt3(self):
        data = blp.encode(self.image(8, 8, alpha=0))
        self.assertEqual(data[8:11], bytes((2, 8, 1)))
        self.assertEqual(set(blp.decode(data)[2][3::4]), {0})

    def test_face_square_becomes_classic_strips(self):
        upper, lower = retail_textures.strips(self.image(512, 512))
        self.assertEqual((upper[:2], lower[:2]), ((128, 32), (128, 64)))
        # The top third of the square ends up in the upper strip.
        self.assertLess(upper[2][1], lower[2][1])

    def test_only_ordinary_player_choices_are_carried(self):
        class Table:
            def __init__(self, rows, names=None):
                self.rows, self.names = rows, names or {}

            def string(self, row, field):
                return self.names[row]

        tables = dict(option=Table({7: [0, 7, 0, 0, 19]}, {7: 'Skin Color'}),
                      # (name, id, option, requirement, ui, sort)
                      choice=Table({1: [0, 1, 7, 141, 0, 2], 2: [0, 2, 7, 141, 0, 1],
                                    3: [0, 3, 7, 115, 0, 3], 4: [0, 4, 7, 12, 0, 4],
                                    5: [0, 5, 7, 666, 0, 5]}),
                      # (unused, type, class mask, unused, unlock)
                      requirement=Table({141: [0, 3, 0xFFFFFFFF, 0, 0], 115: [0, 3, 32, 0, 0],
                                         12: [0, 2, 0xFFFFFFFF, 0, 0], 666: [0, 3, 30687, 0, 15579]}),
                      texture=Table({}), element=Table({}), material=Table({}), geoset=Table({}))
        custom = retail_textures.Customization(tables, 19)
        self.assertEqual(custom.choices('Skin Color'), [2, 1])
        self.assertEqual(custom.choices('Horns'), [])


class BlteTests(unittest.TestCase):
    def test_reads_raw_and_zlib_blocks_and_refuses_encrypted_ones(self):
        blocks = [b'N' + b'abc', b'Z' + zlib.compress(b'defg')]
        header = struct.pack('>BI', 0xF, len(blocks))[0:1] + len(blocks).to_bytes(3, 'big')
        table = b''.join(struct.pack('>II', len(b), 0) + bytes(16) for b in blocks)
        data = b'BLTE' + struct.pack('>I', 12 + len(table)) + header + table + b''.join(blocks)
        self.assertEqual(casc.blte(data), b'abcdefg')
        self.assertEqual(casc.blte(b'BLTE' + bytes(4) + b'Nxyz'), b'xyz')
        with self.assertRaises(PermissionError):
            casc.blte(b'BLTE' + bytes(4) + b'E...')


if __name__ == '__main__':
    unittest.main()
