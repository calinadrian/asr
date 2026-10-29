"""Fit character-only pane cameras; leave geometry, rigs and gameplay scale intact."""
import math
import re
import struct

from retail_m2 import arr

CHARACTER = re.compile(r'^character\\([^\\]+)\\(male|female)\\\1\2\.m2$', re.I)
FOV = 0.5
STAGE_DISTANCE = 10.5
# Keep the projected floor in place when moving the shared camera closer.
STAGE_TARGET_ABOVE_FEET = 1.85 * STAGE_DISTANCE / 12.0


def camera(data):
    count, offset = arr(data, 0x44)
    points = [struct.unpack_from('<3f', data, offset+48*i) for i in range(count)]
    if not points or not all(math.isfinite(v) for p in points for v in p):
        raise ValueError('Preview camera requires finite character geometry')
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    factor = 1.0
    bones, bone_at = arr(data, 0x34)
    for i in range(bones):
        at = bone_at+108*i
        if struct.unpack_from('<h', data, at+8)[0] == -1:
            keys, values = arr(data, at+88)
            if keys:
                # Expansion rigs can have enlarged attached hair/antler roots.
                # Reserve space for those; an effect's shrinking root must never
                # shrink the camera's estimate of the whole character.
                factor = max(factor, struct.unpack_from('<f', data, values)[0])
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError('Invalid character root scale')
    height = (high[2]-low[2])*factor
    if height <= 0:
        raise ValueError('Character has no preview height')
    # One shared standoff preserves the models' actual relative sizes. Fitting
    # each body to the same screen height incorrectly makes Goblins as large
    # as Tauren. The shared distance provides a modest zoom without changing
    # individual race proportions.
    distance = STAGE_DISTANCE
    # Aim the same distance above each model's ground, rather than its centre.
    # Centring each body independently makes short races float above tall ones.
    ground = low[2]*factor
    center = ground+STAGE_TARGET_ABOVE_FEET
    record = bytearray(124)
    struct.pack_into('<ifff', record, 0, 1, FOV, 100.0, 0.02)
    struct.pack_into('<3f', record, 44, distance, 0.0, center)
    struct.pack_into('<3f', record, 84, 0.0, 0.0, center)
    for track in (16, 56, 96):
        struct.pack_into('<Hh', record, track, 0, -1)
    return bytes(record), dict(height=height, distance=distance, target_height=center,
                              ground_height=ground)


def fit(data):
    record, report = camera(data)
    count, offset = arr(data, 0x124)
    if count > 64 or offset+count*124 > len(data):
        raise ValueError('Invalid existing character camera array')
    records = [data[offset+124*i:offset+124*(i+1)] for i in range(count)]
    if len(records) > 1 and records[1] == record:
        return data, report
    # Keep an existing head camera and lookup. Camera-less converted characters
    # retain an empty portrait lookup, so unit-frame portraits keep their fallback.
    records = records or [record]
    if len(records) == 1:
        records.append(record)
    else:
        records[1] = record
    out = bytearray(data)
    out.extend(bytes((-len(out)) % 4))
    at = len(out)
    out.extend(b''.join(records))
    struct.pack_into('<II', out, 0x124, len(records), at)
    return bytes(out), report


def fit_characters(entries):
    reports = {}
    for path in entries:
        if CHARACTER.fullmatch(path):
            entries[path], reports[path] = fit(entries[path])
    if len(reports) != 52:
        raise ValueError(f'Expected 52 framed character models, found {len(reports)}')
    return reports


def remove_floor_glow(image):
    # These two sRGBA stops belong only to the armory's floor gradient.
    for address, expected in ((0x61f9430, (1.0, .72, .30, .38)),
                              (0x61f9440, (.55, .30, .08, .18))):
        before = struct.pack('<4f', *expected)
        after = before[:12]+bytes(4)
        if image.read(address, 16) not in (before, after):
            raise ValueError('Unsupported native armory floor gradient')
        image.edit(address+12, bytes(4))
