"""Refine zone cards in the supported native desktop layout.

Code edits verify complete original instructions. New visual constants live in
their own read-only PE section so shared game/UI values are never overwritten.
Unknown layouts fail before an output file is written. Reapplying is safe.
"""
import argparse
import json
import struct
from pathlib import Path

PROFILE = Path(__file__).with_name('zone-cards-profile.json')
SECTION = b'.asrui\0\0'


def apply(source, profile=None):
    profile = profile or json.loads(PROFILE.read_text(encoding='utf-8'))
    data = bytearray(source)
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    optional = pe + 24
    if data[pe:pe + 4] != b'PE\0\0' or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected a 64-bit Windows game')
    base = struct.unpack_from('<Q', data, optional + 24)[0]
    if base != 0x140000000:
        raise ValueError('Unsupported native game image base')
    count = struct.unpack_from('<H', data, pe + 6)[0]
    table = optional + struct.unpack_from('<H', data, pe + 20)[0]
    sections = []
    for index in range(count):
        pos = table + 40 * index
        virtual_size, va, size, raw = struct.unpack_from('<IIII', data, pos + 8)
        sections.append((bytes(data[pos:pos + 8]), va, raw, size, virtual_size))

    def offset(rva):
        for _, va, raw, size, _ in sections:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError(f'Unsupported native game address {rva:#x}')

    def align(value, boundary):
        return (value + boundary - 1) // boundary * boundary

    file_alignment = struct.unpack_from('<I', data, optional + 36)[0]
    section_alignment = struct.unpack_from('<I', data, optional + 32)[0]
    payload = bytes.fromhex(profile['payload'])
    existing = [s for s in sections if s[0] == SECTION]
    prior = None
    if len(existing) > 1:
        raise ValueError('Duplicate ASR UI sections')
    if existing:
        _, va, raw, _, virtual_size = existing[0]
        if virtual_size != len(payload) or data[raw:raw + len(payload)] != payload:
            for previous in profile.get('previous', []):
                old_payload = bytes.fromhex(previous['payload'])
                if virtual_size == len(old_payload) and data[raw:raw + len(old_payload)] == old_payload:
                    prior = previous
                    break
            if prior is None:
                raise ValueError('Unrecognized ASR UI constants')
        if len(payload) > existing[0][3]:
            raise ValueError('Updated UI constants do not fit the reserved section')
    else:
        va = align(max(s[1] + max(s[3], s[4]) for s in sections), section_alignment)
        raw = align(len(data), file_alignment)
        header = table + count * 40
        if header + 40 > min(s[2] for s in sections) or any(data[header:header + 40]):
            raise ValueError('No free PE section header for ASR UI constants')

    # Validate every instruction before modifying the output or extending it.
    edits = []
    prior_patches = {p['rva']: p for p in prior['patches']} if prior else {}
    for patch in profile['patches']:
        before = bytes.fromhex(patch['before'])
        if 'constant' in patch:
            after = bytearray.fromhex(patch.get('after_template', patch['before']))
            rip_end = patch.get('rip_end', len(before))
            if not patch['disp_offset'] + 4 <= rip_end <= len(before):
                raise ValueError('Invalid UI instruction address span')
            struct.pack_into('<i', after, patch['disp_offset'], va + patch['constant'] - (patch['rva'] + rip_end))
            after = bytes(after)
        else:
            after = bytes.fromhex(patch['after'])
        if len(after) != len(before):
            raise ValueError('UI patch must preserve instruction-block length')
        pos = offset(patch['rva'])
        actual = bytes(data[pos:pos + len(before)])
        accepted = [before]
        if existing:
            accepted.append(after)
        if patch['rva'] in prior_patches:
            previous = prior_patches[patch['rva']]
            old_after = bytearray.fromhex(previous.get('after_template', previous.get('after', previous['before'])))
            if 'constant' in previous:
                struct.pack_into('<i', old_after, previous['disp_offset'], va + previous['constant'] - (previous['rva'] + previous.get('rip_end', len(old_after))))
            accepted.append(bytes(old_after))
        if actual not in accepted:
            raise ValueError('Unsupported native game layout: ' + patch['name'])
        edits.append((pos, after))

    if not existing:
        size = align(len(payload), file_alignment)
        data.extend(b'\0' * (raw + size - len(data)))
        data[raw:raw + len(payload)] = payload
        struct.pack_into('<8sIIIIIIHHI', data, header, SECTION, len(payload), va, size, raw, 0, 0, 0, 0, 0x40000040)
        struct.pack_into('<H', data, pe + 6, count + 1)
        struct.pack_into('<I', data, optional + 56, align(va + len(payload), section_alignment))
        initialized = struct.unpack_from('<I', data, optional + 8)[0]
        struct.pack_into('<I', data, optional + 8, initialized + size)
        struct.pack_into('<I', data, optional + 64, 0)
    elif prior:
        size = existing[0][3]
        data[raw:raw + size] = payload + b'\0' * (size - len(payload))
        header = table + next(i for i, s in enumerate(sections) if s[0] == SECTION) * 40
        struct.pack_into('<I', data, header + 8, len(payload))
        struct.pack_into('<I', data, optional + 64, 0)
    for pos, replacement in edits:
        data[pos:pos + len(replacement)] = replacement
    return bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = apply(args.exe.read_bytes())
    args.out.write_bytes(result)
    print(f'Updated zone cards: {args.out}')
