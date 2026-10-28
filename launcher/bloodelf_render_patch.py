"""Include Blood Elf in the character customization range loader's fixed race loop."""
import struct

from durotar_patch import Code, align, sections

MARKER = b'ASR Blood Elf ranges v1\0'.ljust(32, b'\0')


def apply(source, profile):
    data = bytearray(source)
    pe, optional, table, secs = sections(data)
    index, (_, va, raw, size, virtual) = next((i, s) for i, s in enumerate(secs) if s[0] == b'.asrrace')

    def offset(rva):
        for _, v, r, n, _ in secs:
            if v <= rva < v+n:
                return r + rva-v
        raise ValueError('Unsupported Blood Elf range address')

    hook, bound = profile['ranges_hook'], profile['ranges_bound']
    count = len(hook['before'])//2
    resume = hook['rva'] + count
    code = (Code().raw('4883f808').jcc('ne', 'original').raw('be0a000000').jmp(resume)
            .label('original').raw(hook['before']).jmp(resume))
    marker = data.find(MARKER, raw, raw+virtual)
    if marker >= 0:
        rva = va + marker-raw
        blob = MARKER + code.assemble(rva + len(MARKER))
        if data[marker:marker+len(blob)] != blob or marker+len(blob) > raw+virtual:
            raise ValueError('Unknown Blood Elf range payload')
    else:
        if (data[offset(hook['rva']):offset(hook['rva'])+len(hook['before'])//2].hex() != hook['before']
                or data[offset(bound['rva']):offset(bound['rva'])+4].hex() != bound['before']):
            raise ValueError('Unsupported Blood Elf range loader')
        if raw+size != len(data):
            raise ValueError('Blood Elf range patch requires the final race section')
        start = align(virtual, 16)
        rva = va+start
        blob = MARKER + code.assemble(rva+len(MARKER))
        file_alignment = struct.unpack_from('<I', data, optional+36)[0]
        new_size = align(start+len(blob), file_alignment)
        data.extend(bytes(max(0, raw+new_size-len(data))))
        data[raw+start:raw+start+len(blob)] = blob
        struct.pack_into('<I', data, table+index*40+8, start+len(blob))
        struct.pack_into('<I', data, table+index*40+16, new_size)
        alignment = struct.unpack_from('<I', data, optional+32)[0]
        struct.pack_into('<I', data, optional+56, align(va+start+len(blob), alignment))
        at = offset(hook['rva'])
        data[at:at+count] = b'\xe9' + struct.pack('<i', rva+len(MARKER)-hook['rva']-5) + b'\x90'*(count-5)
        data[offset(bound['rva']):offset(bound['rva'])+4] = bytes.fromhex(bound['after'])
    expected = b'\xe9' + struct.pack('<i', rva+len(MARKER)-hook['rva']-5) + b'\x90'*(count-5)
    if (data[offset(hook['rva']):offset(hook['rva'])+count] != expected
            or data[offset(bound['rva']):offset(bound['rva'])+4].hex() != bound['after']):
        raise ValueError('Unknown Blood Elf range hook')
    struct.pack_into('<I', data, optional+64, 0)
    return bytes(data)
