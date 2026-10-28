"""Native refresh bridge: mutation guards, section protection and unwind contracts."""
import hashlib
import struct
import unittest
from unittest.mock import patch
import addon_refresh_patch as refresh


class RefreshPatchTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(0x3000)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 0x80)
        data[0x80:0x84] = b'PE\0\0'
        struct.pack_into('<H', data, 0x86, 1)
        struct.pack_into('<H', data, 0x94, 240)
        optional = 0x98
        struct.pack_into('<H', data, optional, 0x20b)
        struct.pack_into('<II', data, optional+32, 0x1000, 0x200)
        struct.pack_into('<II', data, optional+136, 0x2000, 12)
        struct.pack_into('<8sIIIIIIHHI', data, optional+240, b'.text', 0x2c00, 0x1000, 0x2c00, 0x400, 0, 0, 0, 0, 0x60000020)
        data[0x400:0x406] = refresh.ORIGINAL
        struct.pack_into('<III', data, 0x1400, 0x1000, 0x1006, 0x2020)
        self.digest = hashlib.sha256(data[0x400:0x406]).hexdigest()
        return bytes(data)

    def apply(self, data):
        with patch.object(refresh, 'HOOK', 0x1000), patch.object(refresh, 'FUNCTIONS', ((0x1000, 0x1006, self.digest),)), patch.object(refresh, 'IMPORTS', {}):
            return refresh.apply(data)

    def test_idempotent_and_preserves_exception_entries(self):
        original = self.fixture()
        result = self.apply(original)
        self.assertEqual(self.apply(result), result)
        self.assertEqual(struct.unpack_from('<H', result, 0x86)[0], 3)
        table = 0x98+240
        code_flags = struct.unpack_from('<I', result, table+40+36)[0]
        data_flags = struct.unpack_from('<I', result, table+80+36)[0]
        self.assertTrue(code_flags & 0x20000000)
        self.assertFalse(code_flags & 0x80000000)
        self.assertFalse(data_flags & 0x20000000)
        self.assertTrue(data_flags & 0x80000000)
        va, size = struct.unpack_from('<II', result, 0x98+136)
        _, cva, raw, _, _ = self.section(result, table+40)
        at = raw+va-cva
        self.assertEqual(size, 24)
        self.assertEqual(result[at:at+12], original[0x1400:0x140c])
        begin, end, unwind = struct.unpack_from('<III', result, at+12)
        self.assertEqual(begin, cva+64)
        self.assertGreater(end, begin)
        self.assertEqual(result[raw+unwind-cva], 1)
        self.assertEqual(result[0x400], 0xe8)

    @staticmethod
    def section(data, at):
        virtual, va, size, raw = struct.unpack_from('<IIII', data, at+8)
        return data[at:at+8], va, raw, size, virtual

    def test_unknown_hook_and_modified_payload_rejected(self):
        source = bytearray(self.fixture()); source[0x400] ^= 1
        with self.assertRaises(ValueError): self.apply(source)
        result = bytearray(self.apply(self.fixture()))
        _, _, raw, _, _ = self.section(result, 0x98+240+40)
        result[raw+64] ^= 1
        with self.assertRaises(ValueError): self.apply(result)
        result = bytearray(self.apply(self.fixture()))
        struct.pack_into('<I', result, 0x98+240+40+36, 0xe0000020)
        with self.assertRaises(ValueError): self.apply(result)


if __name__ == '__main__': unittest.main()
