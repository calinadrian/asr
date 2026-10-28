"""Extend the Appearance screen's independent faction rows for Blood Elf.

The native race catalog does not drive this screen: each faction has four
inline IDs. Keep Alliance's four and append race 10 to Horde, include the six
Blood Elf classes in the allowed-race builder, and use its portrait atlas cell.
Bridges contain no calls or absolute pointers and extend the existing race section.
"""
import struct

from durotar_patch import Code, align, sections

MARKER = b'ASR Blood Elf picker v1\0'.ljust(32, b'\0')


def payload(rva, profile):
    data = bytearray(MARKER)
    lists = {}
    for key, races in profile['classes'].items():
        lists[int(key)] = rva + len(data)
        data.extend(bytes([*races, 10]))
    codes = {}
    # rbp+0x790 is the already-incremented faction iterator: 1 Alliance, 2 Horde.
    codes['loop'] = (Code().raw('4883bd9007000002').jcc('ne', 'alliance')
                     .raw('4883f805').jmp('test').label('alliance').raw('4883f804')
                     .label('test').jcc('e', profile['loop_done']).jmp(profile['loop_continue']))
    # The fifth Horde slot has no backing inline byte; synthesize race 10.
    codes['race'] = (Code().raw('4883f804').jcc('ne', 'original').raw('40b70a')
                     .jmp(profile['hooks']['race']['rva'] + 8).label('original')
                     .raw(profile['hooks']['race']['before']).jmp(profile['hooks']['race']['rva'] + 8))
    # Blood Elf: x=256, y=64 in the 512x256 race atlas; sex adds 128 later.
    # xmm15 holds 64.0 in this function. Preserve all other registers.
    codes['portrait'] = (Code().raw('4080ff0a').jcc('ne', 'original')
                         .raw('410f28c7f30f58c0f30f58c0b840000000')
                         .jmp(profile['portrait_ready']).label('original')
                         .raw(profile['hooks']['portrait']['before'])
                         .jmp(profile['hooks']['portrait']['rva'] + 9))
    code = Code()
    for class_id in lists:
        code.raw('83f8' + bytes([class_id-1]).hex()).jcc('e', f'class{class_id}')
    code.raw('c1e003').rel('488d0d', profile['counts']).raw('488b1c08')
    code.rel('488d0d', profile['pointers']).raw('4c8b3408').jmp('done')
    for class_id, address in lists.items():
        code.label(f'class{class_id}').raw('bb' + struct.pack('<I', len(profile['classes'][str(class_id)])+1).hex())
        code.rel('4c8d35', address).jmp('done')
    code.label('done').jmp(profile['hooks']['allowed']['rva'] + 25)
    codes['allowed'] = code
    targets = {}
    for name, code in codes.items():
        data.extend(bytes(align(len(data), 16) - len(data)))
        targets[name] = rva + len(data)
        data.extend(code.assemble(targets[name]))
    return bytes(data), targets


def apply(source, profile):
    data = bytearray(source)
    pe, optional, table, secs = sections(data)
    matches = [(i, s) for i, s in enumerate(secs) if s[0] == b'.asrrace']
    if len(matches) != 1:
        raise ValueError('Apply the Blood Elf race patch before its picker patch')
    index, (_, va, raw, size, virtual) = matches[0]

    def offset(rva):
        for _, v, r, n, _ in secs:
            if v <= rva < v+n:
                return r + rva-v
        raise ValueError('Unsupported native Blood Elf picker address')

    base = struct.unpack_from('<Q', data, optional+24)[0]
    for key, races in profile['classes'].items():
        slot = int(key)-1
        count = struct.unpack_from('<Q', data, offset(profile['counts'])+slot*8)[0]
        pointer = struct.unpack_from('<Q', data, offset(profile['pointers'])+slot*8)[0]
        at = offset(pointer-base)
        if count != len(races) or data[at:at+count] != bytes(races):
            raise ValueError('Unsupported native Blood Elf class restrictions')
    at = data.find(MARKER, raw, raw+virtual)
    if at >= 0:
        blob, targets = payload(va + at-raw, profile)
        if at + len(blob) > raw + virtual or data[at:at+len(blob)] != blob:
            raise ValueError('Unknown Blood Elf picker payload')
    else:
        for hook in profile['hooks'].values():
            at = offset(hook['rva'])
            if data[at:at+len(hook['before'])//2].hex() != hook['before']:
                raise ValueError('Unsupported native Blood Elf picker hook')
        if raw + size != len(data) or va + size != max(v+s for _, v, _, s, _ in secs):
            raise ValueError('Blood Elf picker requires the final race section')
        start = align(virtual, 16)
        blob, targets = payload(va + start, profile)
        file_alignment = struct.unpack_from('<I', data, optional+36)[0]
        new_size = align(start + len(blob), file_alignment)
        data.extend(bytes(max(0, raw + new_size - len(data))))
        data[raw+start:raw+start+len(blob)] = blob
        struct.pack_into('<I', data, table+index*40+8, start + len(blob))
        struct.pack_into('<I', data, table+index*40+16, new_size)
        section_alignment = struct.unpack_from('<I', data, optional+32)[0]
        struct.pack_into('<I', data, optional+56, align(va + start + len(blob), section_alignment))
        for name, hook in profile['hooks'].items():
            at, count = offset(hook['rva']), len(hook['before'])//2
            data[at:at+count] = b'\xe9' + struct.pack('<i', targets[name]-hook['rva']-5) + b'\x90'*(count-5)
    for name, hook in profile['hooks'].items():
        at, count = offset(hook['rva']), len(hook['before'])//2
        expected = b'\xe9' + struct.pack('<i', targets[name]-hook['rva']-5) + b'\x90'*(count-5)
        if data[at:at+count] != expected:
            raise ValueError('Unknown Blood Elf picker hook')
    struct.pack_into('<I', data, optional+64, 0)
    return bytes(data)
