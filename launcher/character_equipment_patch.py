"""Give race 10 its Be helmet suffix instead of the native clamp's Tr suffix.

Supports only the reviewed 0.124.3/0.124.4 equipment loader. The bridge uses
relative addresses, preserves the old loader for every other race, and is
appended to the existing ASR race section without adding a PE header.
"""
import argparse
from pathlib import Path
import struct

from durotar_patch import Code, align, sections

MARKER = b'ASR character equipment v1\0'.ljust(32, b'\0')
SITE = 0x7B29BD
BEFORE = bytes.fromhex('488d150cb9ad05488b4c11f0')
TABLE = 0x628E2D0


def payload(rva):
    prefix = rva + len(MARKER)
    start = align(len(MARKER) + 2, 16)
    code = (Code().rel('488d15', TABLE).raw('4180ff0a').jcc('ne', 'legacy')
            .rel('488d0d', prefix).jmp('done').label('legacy').raw('488b4c11f0')
            .label('done').jmp(SITE + len(BEFORE)))
    return MARKER + b'Be' + bytes(start-len(MARKER)-2) + code.assemble(rva+start), rva+start


def apply(source):
    data = bytearray(source)
    _, optional, table, secs = sections(data)
    def offset(rva):
        return next(raw+rva-va for _, va, raw, size, _ in secs if va <= rva < va+size)
    matches = [(i, s) for i, s in enumerate(secs) if s[0] == b'.asrrace']
    if len(matches) != 1:
        raise ValueError('Equipment upgrade requires the supported ASR Blood Elf race patch')
    index, (_, va, raw, size, virtual) = matches[0]
    base = struct.unpack_from('<Q', data, optional+24)[0]
    strings = offset(TABLE)-17
    if data[strings:strings+17] != b'HuOrDwNiScTaGnTr\0':
        raise ValueError('Unsupported native equipment race prefixes')
    for i in range(8):
        pointer, length = struct.unpack_from('<QQ', data, offset(TABLE)+i*16)
        if (pointer, length) != (base+TABLE-17+i*2, 2):
            raise ValueError('Unsupported native equipment prefix table')
    at = offset(SITE)
    marker = data.find(MARKER, raw, raw+virtual)
    if marker >= 0:
        blob, target = payload(va+marker-raw)
        if marker+len(blob) > raw+virtual or data[marker:marker+len(blob)] != blob:
            raise ValueError('Unknown equipment bridge payload')
    else:
        if data[at:at+len(BEFORE)] != BEFORE:
            raise ValueError('Unsupported native equipment prefix hook')
        if raw+size != len(data):
            raise ValueError('Equipment upgrade requires the final ASR race section')
        start = align(virtual, 16)
        blob, target = payload(va+start)
        alignment, file_alignment = struct.unpack_from('<II', data, optional+32)
        new_size = align(start+len(blob), file_alignment)
        data.extend(bytes(max(0, raw+new_size-len(data))))
        data[raw+start:raw+start+len(blob)] = blob
        struct.pack_into('<I', data, table+index*40+8, start+len(blob))
        struct.pack_into('<I', data, table+index*40+16, new_size)
        struct.pack_into('<I', data, optional+56, align(va+start+len(blob), alignment))
        data[at:at+len(BEFORE)] = b'\xe9'+struct.pack('<i', target-SITE-5)+b'\x90'*(len(BEFORE)-5)
    expected = b'\xe9'+struct.pack('<i', target-SITE-5)+b'\x90'*(len(BEFORE)-5)
    if data[at:at+len(BEFORE)] != expected:
        raise ValueError('Unknown equipment prefix hook')
    struct.pack_into('<I', data, optional+64, 0)
    return bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.write_bytes(apply(args.exe.read_bytes()))
    print(f'Wrote {args.out}')
