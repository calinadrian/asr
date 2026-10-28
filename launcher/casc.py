"""Read files from a local retail World of Warcraft install (CASC storage), by FileDataID.

Only what asset preparation needs: the local index buckets, the encoding table, the TSFM root and
BLTE blocks stored raw or zlib-compressed. Encrypted blocks are refused. Nothing is written to the
install.
"""
import mmap
from pathlib import Path
import struct
import zlib


class Casc:
    def __init__(self, folder):
        """folder holds .build.info, Data\\config and Data\\data, e.g. ...\\World of Warcraft."""
        self.root_dir = Path(folder)
        self.data_dir = self.root_dir / 'Data' / 'data'
        self.archives = {}
        info = (self.root_dir / '.build.info').read_text().splitlines()
        fields = [f.split('!')[0] for f in info[0].split('|')]
        rows = [dict(zip(fields, line.split('|'))) for line in info[1:] if line]
        row = next(r for r in rows if r.get('Active') == '1' and r.get('Product', 'wow') == 'wow')
        self.version = row['Version']
        self.build = self._config(row['Build Key'])
        self._read_indexes()
        self._read_encoding(bytes.fromhex(self.build['encoding'].split()[1]))
        self._read_root(self.ekey(bytes.fromhex(self.build['root'].split()[0])))

    def _config(self, key):
        path = self.root_dir / 'Data' / 'config' / key[:2] / key[2:4] / key
        result = {}
        for line in path.read_text().splitlines():
            if ' = ' in line and not line.startswith('#'):
                name, value = line.split(' = ', 1)
                result[name] = value
        return result

    def _read_indexes(self):
        latest = {}
        for path in self.data_dir.glob('*.idx'):
            bucket, version = int(path.stem[:2], 16), int(path.stem[2:], 16)
            if version > latest.get(bucket, (-1, None))[0]:
                latest[bucket] = (version, path)
        self.index = {}
        for _, path in latest.values():
            data = path.read_bytes()
            header_size = struct.unpack_from('<I', data)[0]
            version, _, _, size_len, loc_len, key_len, seg_bits = struct.unpack_from('<HBBBBBB', data, 8)
            if version != 7 or (size_len, loc_len, key_len, seg_bits) != (4, 5, 9, 30):
                raise ValueError(f'Unsupported CASC index {path.name}')
            pos = (8 + header_size + 15) & ~15
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 8
            for entry in range(pos, pos + length, 18):
                key = data[entry:entry + 9]
                high, low = data[entry + 9], struct.unpack_from('>I', data, entry + 10)[0]
                size = struct.unpack_from('<I', data, entry + 14)[0]
                # Later buckets do not repeat keys; the first location seen wins.
                self.index.setdefault(key, ((high << 2) | (low >> 30), low & 0x3FFFFFFF, size))

    def _archive(self, number):
        if number not in self.archives:
            with (self.data_dir / f'data.{number:03d}').open('rb') as file:
                self.archives[number] = mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ)
        return self.archives[number]

    def read_ekey(self, ekey):
        location = self.index.get(ekey[:9])
        if location is None:
            raise KeyError(f'{ekey.hex()} is not stored locally')
        number, offset, size = location
        archive = self._archive(number)
        # 30-byte local header: reversed key, size, flags and checksums, then the BLTE stream.
        return blte(archive[offset + 30:offset + size])

    def _read_encoding(self, ekey):
        data = self.read_ekey(ekey)
        magic, _, ckey_len, ekey_len, ce_page_kb, _, ce_pages, _, _, espec_size = struct.unpack_from(
            '>2sBBBHHIIBI', data)
        if magic != b'EN' or (ckey_len, ekey_len) != (16, 16):
            raise ValueError('Unsupported encoding table')
        pos = 22 + espec_size + ce_pages * 32
        page = ce_page_kb * 1024
        self.encoding = {}
        for start in range(pos, pos + ce_pages * page, page):
            entry = start
            while entry + 22 <= start + page and data[entry]:
                count = data[entry]
                ckey = data[entry + 6:entry + 22]
                self.encoding[ckey] = data[entry + 22:entry + 38]
                entry += 22 + count * 16

    def ekey(self, ckey):
        return self.encoding[ckey]

    def _read_root(self, ekey):
        data = self.read_ekey(ekey)
        if data[:4] != b'TSFM':
            raise ValueError('Unsupported root format')
        header_size, version = struct.unpack_from('<II', data, 4)
        if version not in (1, 2):
            raise ValueError(f'Unsupported root version {version}')
        pos = header_size
        self.files = {}
        while pos < len(data):
            if version == 2:
                count, locale, flags1, flags2, flags3 = struct.unpack_from('<IIIIB', data, pos)
                content, pos = flags1 | flags2 | (flags3 << 17), pos + 17
            else:
                count, content, locale = struct.unpack_from('<III', data, pos)
                pos += 12
            deltas = struct.unpack_from(f'<{count}i', data, pos)
            pos += count * 4
            ckeys = pos
            pos += count * 16
            if not content & 0x10000000:
                pos += count * 8
            # Prefer enUS (0x2) or locale-neutral blocks; skip low-violence copies (0x80).
            usable = locale & 0x2 or locale == 0xFFFFFFFF or locale == 0x1FFF6
            file_id = -1
            for i, delta in enumerate(deltas):
                file_id += delta + 1
                if usable and not content & 0x80 and file_id not in self.files:
                    self.files[file_id] = data[ckeys + i * 16:ckeys + i * 16 + 16]

    def read(self, file_id):
        """The file's bytes, or None when the install does not have it."""
        ckey = self.files.get(file_id)
        if ckey is None or ckey not in self.encoding:
            return None
        try:
            return self.read_ekey(self.encoding[ckey])
        except KeyError:
            return None

    def close(self):
        for archive in self.archives.values():
            archive.close()
        self.archives.clear()


def blte(data):
    if data[:4] != b'BLTE':
        raise ValueError('Not a BLTE stream')
    header_size = struct.unpack_from('>I', data, 4)[0]
    if header_size == 0:
        blocks = [(len(data) - 8, None)]
        pos = 8
    else:
        count = struct.unpack_from('>I', data, 8)[0] & 0xFFFFFF
        blocks = [struct.unpack_from('>II', data, 12 + i * 24) for i in range(count)]
        pos = header_size
    out = bytearray()
    for compressed, _ in blocks:
        block = data[pos:pos + compressed]
        pos += compressed
        mode = block[:1]
        if mode == b'N':
            out += block[1:]
        elif mode == b'Z':
            out += zlib.decompress(block[1:])
        elif mode == b'E':
            raise PermissionError('Encrypted BLTE block')
        else:
            raise ValueError(f'Unsupported BLTE block mode {mode!r}')
    return bytes(out)
