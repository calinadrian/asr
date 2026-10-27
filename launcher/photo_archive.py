"""Build ASR's zone-photo MPQ from prepared BLP2 textures.

Uses the vanilla MPQ v1 stored-file envelope read by benilla-mpq. Only the
named loading-screen assets are overridden; gameplay data is not included.
"""
import struct
from pathlib import Path


def table():
    result = [0] * 0x500
    seed = 0x100001
    for low in range(256):
        for high in range(5):
            seed = (seed * 125 + 3) % 0x2aaaab
            first = (seed & 0xffff) << 16
            seed = (seed * 125 + 3) % 0x2aaaab
            result[low + high * 256] = first | (seed & 0xffff)
    return result


CRYPT = table()
MASK = 0xffffffff


def name_hash(name, kind):
    a, b = 0x7fed7fed, 0xeeeeeeee
    for ch in name.replace('/', '\\').upper().encode('ascii'):
        a = CRYPT[kind + ch] ^ ((a + b) & MASK)
        b = (ch + a + b + (b << 5) + 3) & MASK
    return a


def crypt(words, key, decrypt=False):
    result = []
    seed = 0xeeeeeeee
    for word in words:
        seed = (seed + CRYPT[0x400 + (key & 255)]) & MASK
        transformed = word ^ ((key + seed) & MASK)
        result.append(transformed)
        plain = transformed if decrypt else word
        key = (((~key << 21) + 0x11111111) | (key >> 11)) & MASK
        seed = (plain + seed + (seed << 5) + 3) & MASK
    return struct.pack('<' + 'I' * len(result), *result)


def build(entries):
    entries = dict(entries)
    entries['(listfile)'] = ('\r\n'.join(sorted(entries)) + '\r\n').encode('ascii')
    slots = 1
    while slots < len(entries) * 2:
        slots *= 2
    hash_pos = 32
    block_pos = hash_pos + slots * 16
    data_pos = block_pos + len(entries) * 16
    hashes = [MASK] * (slots * 4)
    blocks, payload = [], bytearray()
    for index, (name, data) in enumerate(sorted(entries.items())):
        slot = name_hash(name, 0) & (slots - 1)
        while hashes[slot * 4 + 3] != MASK:
            slot = (slot + 1) & (slots - 1)
        hashes[slot * 4:slot * 4 + 4] = [name_hash(name, 0x100), name_hash(name, 0x200), 0, index]
        blocks.extend([data_pos + len(payload), len(data), len(data), 0x80000000])
        payload.extend(data)
    header = struct.pack('<4sIIHHIIII', b'MPQ\x1a', 32, data_pos + len(payload), 0, 3,
                         hash_pos, block_pos, slots, len(entries))
    return header + crypt(hashes, name_hash('(hash table)', 0x300)) + crypt(blocks, name_hash('(block table)', 0x300)) + payload


def read_stored(archive):
    """Read back the narrow archive format this builder emits for verification."""
    magic, header, size, version, shift, hp, bp, slots, count = struct.unpack_from('<4sIIHHIIII', archive)
    if magic != b'MPQ\x1a' or size != len(archive) or version != 0:
        raise ValueError('Invalid photo archive header')
    words = struct.unpack_from('<' + 'I' * (count * 4), archive, bp)
    plain = crypt(words, name_hash('(block table)', 0x300), decrypt=True)
    files = []
    for i in range(count):
        pos, packed, size, flags = struct.unpack_from('<IIII', plain, i * 16)
        if flags != 0x80000000 or packed != size or pos + size > len(archive):
            raise ValueError('Invalid stored photo block')
        files.append(archive[pos:pos + size])
    return files


def build_photos(textures):
    textures = sorted(Path(textures).glob('*.blp'))
    if len(textures) != 12:
        raise ValueError('Expected exactly 12 zone photo textures')
    entries = {'interface\\asr\\zone-photos_____\\' + p.name: p.read_bytes() for p in textures}
    archive = build(entries)
    if len(read_stored(archive)) != 13:
        raise ValueError('Photo archive failed read-back verification')
    return archive


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('textures', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    archive = build_photos(args.textures)
    args.out.write_bytes(archive)
    print(f'Built {args.out}: 12 zone photos, {len(archive)} bytes')

