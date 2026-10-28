"""Build ASR's zone-lighting MPQ: the game's LightIntBand.dbc with dark zones lifted.

Every exterior surface (terrain, walls, doodads, creatures) is lit as
clamp(ambient + sun diffuse * N.L), from LightIntBand rows 1 and 0 of the zone's
Light.dbc params, and fades into row 7's fog colour. Duskwood and other night or
gloomy zones author those colours near black, so walls vanish into the ground.
Each colour darker than its floor is raised to the floor's luminance, keeping
its hue where it can; colours already brighter, and every other row, are unchanged.

The arena's red boundary ("Edge of the Battlefield") is drawn with the AuraRed
glow models: additive red smoke at 25-45% strength that the zone fog then
covers, so in Duskwood's teal haze it all but disappears. The archive also
carries those models at full strength and full red, unfogged and unlit.
"""
import mmap
import struct
import zlib
from pathlib import Path

from photo_archive import MASK, build, crypt, name_hash, read_stored

NAME = 'DBFilesClient\\LightIntBand.dbc'
ARCHIVE = 'patch-Y.MPQ'
# Rows are numbered from 0 within each params' block of 18; floors are relative luminance.
FLOORS = {0: 0.55, 1: 0.40, 7: 0.30}
ROWS = 18
AURAS = ['World\\Generic\\PassiveDoodads\\ParticleEmitters\\' + name + '.m2'
         for name in ('AuraRed', 'AuraRedShort', 'AuraRedTall', 'AuraRedVeryTall')]
# M2 material flags: 0x01 unlit, 0x02 unfogged.
UNLIT, UNFOGGED = 0x01, 0x02


def luminance(r, g, b):
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def lift(color, floor):
    """A BGRA colour no darker than floor, with the same hue and alpha."""
    b, g, r, a = color & 255, color >> 8 & 255, color >> 16 & 255, color >> 24
    current = luminance(r, g, b)
    if current >= floor:
        return color
    # At most double, so a near-black tint does not become a vivid colour.
    scale = min(floor / current, 2) if current else 0
    r, g, b = (min(c * scale, 255) for c in (r, g, b))
    # Mix in white for the rest of the lift, and for what a saturated channel lost.
    short = floor - luminance(r, g, b)
    if short > 0:
        mix = short / (1 - luminance(r, g, b))
        r, g, b = (c + (255 - c) * mix for c in (r, g, b))
    r, g, b = (round(c) for c in (r, g, b))
    return a << 24 | r << 16 | g << 8 | b


def brighten(dbc):
    magic, records, fields, size, strings = struct.unpack_from('<4sIIII', dbc)
    if magic != b'WDBC' or fields != 34 or size != 136:
        raise ValueError('Unexpected LightIntBand.dbc layout')
    out = bytearray(dbc)
    for i in range(records):
        at = 20 + i * size
        row = (struct.unpack_from('<I', dbc, at)[0] - 1) % ROWS
        if row in FLOORS:
            count = struct.unpack_from('<I', dbc, at + 4)[0]
            for j in range(min(count, 16)):
                pos = at + 72 + j * 4
                struct.pack_into('<I', out, pos, lift(struct.unpack_from('<I', dbc, pos)[0], FLOORS[row]))
    return bytes(out)


def vivid(m2):
    """A vanilla (version 256) glow model at full strength, its colours at full brightness, unfogged and unlit."""
    if m2[:8] != b'MD20\x00\x01\x00\x00':
        raise ValueError('Unexpected aura model version')
    out = bytearray(m2)

    def values(track, size):
        count, offset = struct.unpack_from('<II', m2, track + 20)
        return [offset + i * size for i in range(count)]

    colours, at = struct.unpack_from('<II', m2, 0x54)
    for i in range(colours):
        for pos in values(at + i * 56, 12):  # M2Color: an RGB track, then its alpha track
            rgb = struct.unpack_from('<3f', m2, pos)
            struct.pack_into('<3f', out, pos, *(c / max(rgb) for c in rgb) if max(rgb) else rgb)
        for pos in values(at + i * 56 + 28, 2):
            struct.pack_into('<h', out, pos, 32767)
    weights, at = struct.unpack_from('<II', m2, 0x64)
    for i in range(weights):
        for pos in values(at + i * 28, 2):
            struct.pack_into('<h', out, pos, 32767)
    materials, at = struct.unpack_from('<II', m2, 0x84)
    for i in range(materials):
        flags = struct.unpack_from('<H', m2, at + i * 4)[0]
        struct.pack_into('<H', out, at + i * 4, flags | UNLIT | UNFOGGED)
    return bytes(out)


def read_mpq(path, name):
    """One file from a game MPQ (v1, zlib or bzip2 sectors), or None when it is not there."""
    with open(path, 'rb') as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as archive:
        return find(archive, name, path)


def find(archive, name, path):
    start = archive.find(b'MPQ\x1a')
    if start < 0:
        raise ValueError(f'{path} is not an MPQ archive')
    _, _, _, _, shift, hp, bp, slots, count = struct.unpack_from('<4sIIHHIIII', archive, start)
    hashes = struct.unpack('<%dI' % (slots * 4), crypt(struct.unpack_from('<%dI' % (slots * 4), archive, start + hp),
                                                           name_hash('(hash table)', 0x300), decrypt=True))
    blocks = struct.unpack('<%dI' % (count * 4), crypt(struct.unpack_from('<%dI' % (count * 4), archive, start + bp),
                                                           name_hash('(block table)', 0x300), decrypt=True))
    a, b, slot = name_hash(name, 0x100), name_hash(name, 0x200), name_hash(name, 0) & (slots - 1)
    for _ in range(slots):
        first, second, _, index = hashes[slot * 4:slot * 4 + 4]
        if index == MASK:
            return None
        if (first, second) == (a, b) and index < count:
            return extract(archive, start, 512 << shift, *blocks[index * 4:index * 4 + 4])
        slot = (slot + 1) & (slots - 1)
    return None


def extract(archive, start, sector, pos, packed, size, flags):
    if flags & 0x10100:
        raise ValueError('Encrypted or imploded MPQ files are not supported')
    raw = archive[start + pos:start + pos + packed]
    if not flags & 0x200:
        return raw[:size]
    if flags & 0x1000000:
        return inflate(raw, size)
    sectors = (size + sector - 1) // sector
    offsets = struct.unpack_from('<%dI' % (sectors + 1), raw)
    return b''.join(inflate(raw[offsets[i]:offsets[i + 1]], min(sector, size - i * sector)) for i in range(sectors))


def inflate(chunk, size):
    if len(chunk) == size:
        return chunk
    if chunk[0] == 0x02:
        return zlib.decompress(chunk[1:])
    if chunk[0] == 0x10:
        import bz2
        return bz2.decompress(chunk[1:])
    raise ValueError(f'Unsupported MPQ compression {chunk[0]:#x}')


def original(data, name=NAME):
    """The game's own copy of name: from the highest patch, ignoring ASR's archives."""
    archives = [p for p in Path(data).glob('*.MPQ') if p.name.lower() not in ('patch-y.mpq', 'patch-z.mpq')]
    # patch.MPQ first, then patch-2 to patch-9 and the lettered ones; the last one wins.
    for path in sorted(archives, key=lambda p: (p.stem.lower() != 'patch', p.stem.lower()), reverse=True):
        if (found := read_mpq(path, name)) is not None:
            return found
    raise ValueError(f'No {name} in {data}')


def build_lighting(data):
    entries = {NAME: brighten(original(data))}
    entries.update({name: vivid(original(data, name)) for name in AURAS})
    archive = build(entries)
    if len(read_stored(archive)) != len(entries) + 1:
        raise ValueError('Lighting archive failed read-back verification')
    return archive


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path, help='the game Data folder to read LightIntBand.dbc from')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    archive = build_lighting(args.data)
    args.out.write_bytes(archive)
    print(f'Built {args.out}: brighter zone lighting and boundary walls, {len(archive)} bytes')
