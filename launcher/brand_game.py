"""Apply ASR's title and runtime icon to the supported native desktop layout.

All edits retain their size and verify their original bytes. Unknown layouts fail
before any output is written. Authorship, save formats and protocol names stay intact.
"""
import argparse
import hashlib
import struct
import zlib
from pathlib import Path

TITLE = b'Azeroth Survivors'
BASE = 0x140000000
# The same edits at each supported build's addresses: 0.120/0.121, then 0.124.0.
LAYOUTS = (
    dict(titles=(0x146184028, 0x146186d90, 0x1461b7868),
         lengths=((0x14003fc2d, '48c7461811000000'), (0x140070efe, '48c7858001000011000000'),
                  (0x1402451a7, '48c7476811000000'), (0x14024530c, '49c7456811000000')),
         checks=((0x14024510f, '49837c056811'), (0x140245273, '48837c026811')),
         compares=((0x14024511b, 0x140245142), (0x14024527f, 0x1402452a6)),
         skips=((0x14030426f, 0x14030440a), (0x1403046ce, 0x1403048c2)),
         credit=(0x1400e03c7, 0x1400e056c, ((0x1400e03c7, '488b9df0000000', None), (0x1400e0439, '440f101d', 4),
                 (0x1400e051a, '448b35', 3), (0x1400e0528, '440f1025', 4), (0x1400e0538, 'f2440f102d', 5))),
         icon=0x615694e),
    dict(titles=(0x146210150, 0x146200f18, 0x1461f7160),
         lengths=((0x1402c5a4d, '48c7461811000000'), (0x1402694de, '48c7858801000011000000'),
                  (0x14016c8c7, '48c7476811000000'), (0x14016ca2c, '49c7456811000000')),
         checks=((0x14016c82f, '49837c056811'), (0x14016c993, '48837c026811')),
         compares=((0x14016c83b, 0x14016c862), (0x14016c99f, 0x14016c9c6)),
         skips=((0x1402047ef, 0x14020498a), (0x140204c4e, 0x140204e42)),
         credit=(0x140296505, 0x1402966ad, ((0x140296505, '488b9d70040000', None), (0x140296577, '440f101d', 4),
                 (0x140296658, '448b35', 3), (0x140296666, '440f1025', 4), (0x140296676, 'f2440f102d', 5))),
         icon=0x61bb4b0),
)


def apply(data, ico):
    failure = None
    for layout in LAYOUTS:
        try:
            return brand(bytearray(data), ico, layout)
        except ValueError as error:
            failure = failure or error
    raise failure


def brand(data, ico, layout):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    sections = []
    native_regions = []
    for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
        pos = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0] + 40 * index
        _, va, size, raw = struct.unpack_from('<IIII', data, pos + 8)
        sections.append((va, raw, size))
        if data[pos:pos+4] != b'.asr':
            native_regions.append((raw, size))

    def offset(address):
        for va, raw, size in sections:
            if va <= address - BASE < va + size:
                return raw + address - BASE - va
        raise ValueError('Unsupported native game address')

    def patch(address, before, after):
        if len(before) != len(after):
            raise ValueError('Brand patches must preserve executable layout')
        pos = offset(address)
        existing = data[pos:pos + len(before)]
        if existing not in (before, after):
            raise ValueError(f'Unsupported game layout at {address:#x}')
        data[pos:pos + len(before)] = after

    # Fallback title, presence text and both native window title constructors.
    for address in layout['titles']:
        patch(address, TITLE, b'ASR' + b' ' * 14)
    # Keep the allocation capacity (17) but expose exactly three characters.
    for address, before in layout['lengths']:
        original = bytes.fromhex(before)
        patch(address, original, original[:-4] + struct.pack('<I', 3))

    # The window system enforces its title each frame. Compare only the three
    # actual bytes, without reading beyond a three-byte string allocation.
    for address, before in layout['checks']:
        original = bytes.fromhex(before)
        patch(address, original, original[:-1] + b'\x03')
    comparison = bytes.fromhex('f30f6f00660f74c60fb64010660f6ec8660f74cf660fdbc8660fd7c13dffff0000')
    for start, mismatch in layout['compares']:
        # cmp word [rax], 'AS'; jne mismatch; cmp byte [rax+2], 'R'
        # The original following JE still branches back to the next window.
        code = bytes.fromhex('6681384153')
        code += b'\x0f\x85' + struct.pack('<i', mismatch - (start + 11))
        code += bytes.fromhex('80780252')
        code += b'\x90' * (len(comparison) - len(code))
        patch(start, comparison, code)

    # Upstream's support and Discord buttons: jump over their creation.
    for site, resume in layout['skips']:
        pos = offset(site)
        jump = b'\xe9' + struct.pack('<i', resume - site - 5)
        if data[pos:pos + 5] != jump:
            if data[pos] != 0xe8:
                raise ValueError(f'Unsupported game layout at {site:#x}')
            data[pos:pos + 5] = jump
    # The "Made by" credit: skip its creation, keeping the registers the code after it reads.
    start, resume, kept = layout['credit']
    payload = bytearray()
    for origin, prefix, disp in kept:
        pos = offset(origin)
        code = bytearray.fromhex(prefix) + (data[pos + disp:pos + disp + 4] if disp else b'')
        if data[pos:pos + len(prefix) // 2] != bytes.fromhex(prefix) or (origin == start) != (not payload):
            raise ValueError(f'Unsupported game layout at {origin:#x}')
        if disp:
            target = origin + len(code) + struct.unpack_from('<i', code, disp)[0]
            struct.pack_into('<i', code, disp, target - (start + len(payload) + len(code)))
        payload += code
    payload += b'\xe9' + struct.pack('<i', resume - (start + len(payload)) - 5)
    data[offset(start):offset(start) + len(payload)] = payload

    # Translations are fixed-size embedded JSON. Put padding outside the value,
    # so every language renders and centers exactly "ASR".
    old = b'"game.title": "Azeroth Survivors"'
    new = b'"game.title": "ASR"' + b' ' * 14
    # Race patches retain the twelve original JSONs and add extended copies.
    # Validate the owning native table, then brand both the originals and copies.
    count = sum(data[raw:raw+size].count(old) + data[raw:raw+size].count(new)
                for raw, size in native_regions)
    if count != 12:
        raise ValueError(f'Expected 12 game-title translations, found {count}')
    data = data.replace(old, new)

    # Winit loads this PNG directly, independently of Windows' executable icon.
    size, pos = struct.unpack_from('<II', ico, 14)
    png = ico[pos:pos + size]
    if png[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack_from('>II', png, 16) != (256, 256):
        raise ValueError('Expected a 256px PNG as the first ASR icon entry')
    location, length = layout['icon'], 142890
    if data[location:location + 8] != png[:8]:
        raise ValueError('Unsupported runtime icon location')
    # A valid ancillary chunk fills the reserved slot without shifting pointers.
    payload = b'ASR\0' + b' ' * (length - len(png) - 16)
    chunk = b'tEXt' + payload
    padded = png[:-12] + struct.pack('>I', len(payload)) + chunk + struct.pack('>I', zlib.crc32(chunk)) + png[-12:]
    if len(padded) != length:
        raise ValueError('ASR icon does not fit the native icon slot')
    existing = bytes(data[location:location + length])
    if existing != padded and hashlib.sha256(existing).hexdigest() != '93ac97ef17e6e9d04a193846567fe2a0b09869ea2278d08f20a1a02bbf04c855':
        raise ValueError('Unsupported runtime icon; analyze this game build first')
    data[location:location + length] = padded
    return bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--ico', type=Path, default=Path(__file__).with_name('asr.ico'))
    args = parser.parse_args()
    result = apply(args.exe.read_bytes(), args.ico.read_bytes())
    args.out.write_bytes(result)
    print(f'Branded {args.out}: ASR title, 12 languages, runtime icon')
