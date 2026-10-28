"""Set the version and the build code the game shows in its corner label, e.g. "v0.120.6 (2624daa5)".

The game's updater and the co-op lobby read the same version string, and the label shows an
8-character build code right before it. Both are fixed-length strings inside the executable,
so a new version must keep the old one's length (0.120.5 -> 0.120.6, not 0.121.10).
"""
import argparse
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def current(exe_bytes):
    """The (build code, version, code offset) of the corner label.

    The label's data is the 8 hex characters, a reference to the version string and the "v{} ({})"
    format; up to 0.123 the version string itself directly follows the code.
    """
    found = list(re.finditer(rb'(?<![0-9a-f])([0-9a-f]{8})(?:\d+\.\d+\.\d+\x00)?(.{8})(.)\x00{7}\x01v\xc0\x02 \(\xc0\x01\)', exe_bytes, re.S))
    if len(found) != 1:
        raise ValueError(f'Could not find a single version label in the executable (found {len(found)})')
    match = found[0]
    version = read_string(exe_bytes, struct.unpack('<Q', match[2])[0], match[3][0])
    if not re.fullmatch(rb'\d+\.\d+\.\d+', version):
        raise ValueError('The version label does not reference a version')
    return match[1].decode(), version.decode(), match.start(1)


def read_string(data, address, length):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    rva = address - struct.unpack_from('<Q', data, pe + 48)[0]
    for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
        _, va, size, raw = struct.unpack_from('<IIII', data, table + 40 * index + 8)
        if va <= rva < va + size:
            return data[raw + rva - va:raw + rva - va + length]
    raise ValueError('The version label references an unknown address')


# The game updates itself only when its file is named AzerothSurvivors (it compares the lowercased name with a
# 16-byte constant). This keeps the load of the name, then jumps to the accepted branch, so ASR.exe updates too:
#   cmp qword [rbp-0x38], 16 / mov rdx, [rbp-0x28] / jnz rejected
#   -> mov rdx, [rbp-0x28] / jmp accepted / nop x5
NAME_CHECK = bytes.fromhex('48837dc810' '488b55d8' '7543' '488b45c0f30f6f00')
NAME_FREE = bytes.fromhex('488b55d8' 'eb72' '9090909090' '488b45c0f30f6f00')


def allow_any_name(data):
    if data.count(NAME_FREE) == 1:
        return data
    if data.count(NAME_CHECK) != 1:
        raise ValueError('The game\'s file-name check was not found; this build needs a new analysis')
    return data.replace(NAME_CHECK, NAME_FREE)


def stamp(source, output, version, build=None):
    import brand_game
    data = brand_game.apply(allow_any_name(Path(source).read_bytes()), (ROOT / 'launcher/asr.ico').read_bytes())
    import zone_cards
    data = zone_cards.apply(data)
    import addon_manager_patch
    data = addon_manager_patch.apply(data)
    import addon_refresh_patch
    data = addon_refresh_patch.apply(data)
    old_code, old_version, at = current(data)
    build = build or subprocess.run(['git', 'rev-parse', '--short=8', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    if len(version) != len(old_version) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError(f'The new version must have the same length as {old_version}')
    if not re.fullmatch(r'[0-9a-f]{8}', build):
        raise ValueError('The build code must be 8 lowercase hex characters')
    data = data[:at] + build.encode() + data[at + 8:]
    data = data.replace(old_version.encode(), version.encode())
    Path(output).write_bytes(data)
    print(f'{source}: v{old_version} ({old_code}) -> {output}: v{version} ({build})')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe')
    parser.add_argument('--version', required=True)
    parser.add_argument('--build', help='8 hex characters; default: this repository\'s current commit')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    stamp(args.exe, args.out, args.version, args.build)
