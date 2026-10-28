"""Preserve race 10 through character validation when saving or entering a run."""
import struct

from durotar_patch import Code, align, sections

MARKER = b'ASR Blood Elf transition v1\0'.ljust(32, b'\0')


def apply(source, profile):
    data = bytearray(source)
    pe, optional, table, secs = sections(data)
    index, (_, va, raw, size, virtual) = next((i, s) for i, s in enumerate(secs) if s[0] == b'.asrrace')
    site = profile['rva']
    at = next(r + site-v for _, v, r, n, _ in secs if v <= site < v+n)
    # edi holds the selected race, cl is race-1. AL still holds the class ID
    # used by the fallback path; do not change it or broaden the valid interval.
    code = (Code().raw('83ff0a').jcc('e', profile['accepted'])
            .raw('80f908').jcc('b', profile['accepted']).jmp(profile['fallback']))
    marker = data.find(MARKER, raw, raw+virtual)
    if marker >= 0:
        rva = va+marker-raw
        blob = MARKER + code.assemble(rva+len(MARKER))
        if marker+len(blob) != raw+virtual or data[marker:marker+len(blob)] != blob:
            raise ValueError('Unknown Blood Elf transition payload')
    else:
        if data[at:at+5].hex() != profile['before']:
            raise ValueError('Unsupported Blood Elf character validator')
        if raw+size != len(data):
            raise ValueError('Blood Elf transition patch requires the final race section')
        start = align(virtual, 16)
        rva = va+start
        blob = MARKER + code.assemble(rva+len(MARKER))
        alignment, file_alignment = struct.unpack_from('<II', data, optional+32)
        new_size = align(start+len(blob), file_alignment)
        data.extend(bytes(max(0, raw+new_size-len(data))))
        data[raw+start:raw+start+len(blob)] = blob
        struct.pack_into('<I', data, table+index*40+8, start+len(blob))
        struct.pack_into('<I', data, table+index*40+16, new_size)
        struct.pack_into('<I', data, optional+56, align(va+start+len(blob), alignment))
        data[at:at+5] = b'\xe9' + struct.pack('<i', rva+len(MARKER)-site-5)
    if data[at:at+5] != b'\xe9' + struct.pack('<i', rva+len(MARKER)-site-5):
        raise ValueError('Unknown Blood Elf transition hook')
    # The spawn handler has a separate inlined display lookup. Reuse the already
    # extended female/male tables, including Human's fallback entry for race 9.
    def offset(address):
        return next(r+address-v for _, v, r, n, _ in secs if v <= address < v+n)

    spawn = profile['spawn']
    bound = spawn['bound']
    bound_at = offset(bound['rva'])
    if data[bound_at:bound_at+2].hex() not in (bound['before'], bound['after']):
        raise ValueError('Unsupported Blood Elf spawn display bound')
    for ref in spawn['references']:
        src = offset(ref['source'])
        if data[src:src+3] != b'\x48\x8d\x0d':
            raise ValueError('Unsupported Blood Elf display table source')
        target = ref['source']+7+struct.unpack_from('<i', data, src+3)[0]
        dest = offset(ref['rva'])
        expected = bytes.fromhex(ref['before'][:6]) + struct.pack('<i', target-ref['rva']-7)
        if data[dest:dest+7] not in (bytes.fromhex(ref['before']), expected):
            raise ValueError('Unsupported Blood Elf spawn display reference')
        data[dest:dest+7] = expected
    data[bound_at:bound_at+2] = bytes.fromhex(bound['after'])
    struct.pack_into('<I', data, optional+64, 0)
    return bytes(data)
