"""Add Durotar to the native game as a thirteenth zone and a second starter beside Elwynn Forest.

The twelve original zone records, Elwynn's enemy and boss tables and the zone tier table are copied
into a new PE section, Durotar is appended, and every validated code reference is pointed at the
copies. Durotar keeps its own zone index (12) for its terrain, enemies, completion record and
difficulty progress, while starter checks and reward/level scaling treat it as Elwynn's rank, so
a fresh character may pick either starter and a victory in either opens Duskwood.

native-durotar.json holds the reviewed sites of the supported 0.124 layout. Every edit checks its
original bytes and unknown builds are refused. Reapplying verifies the existing section. This patch
owns the base-relocation directory, so it runs after the other executable patches.
"""
import argparse
import json
from pathlib import Path
import struct

SECTION = b'.asrzone'
MARKER = b'ASR Durotar v2\0'.ljust(64, b'\0')
PROFILE = json.loads(Path(__file__).with_name('native-durotar.json').read_text())

ZONE = dict(id='durotar', name='Durotar', subtitle='The Burning Blade', card='loadscreenasrdurotar',
            description='Scorpids and boars roam the red canyons. Razormane warbands close in as the '
                        'Burning Blade gathers its cultists. Break their invasion and reclaim Durotar.',
            map=1, area=14, center=(587.5, -4311.4, 19.0), music=6)
# (name, creature display); creature IDs follow at ENEMY_ID and BOSS_ID, clear of the original catalog.
ENEMIES = (('Clattering Scorpid', 2486), ('Dire Mottled Boar', 381), ('Bloodtalon Taillasher', 1960),
           ('Vile Familiar', 1185), ('Razormane Quilboar', 1218), ('Razormane Scout', 1252),
           ('Armored Scorpid', 2487), ('Burning Blade Neophyte', 4186), ('Razormane Battleguard', 1964),
           ('Razormane Dustrunner', 6088), ('Dustwind Pillager', 6814), ('Burning Blade Cultist', 4194))
BOSSES = (('Geolord Mottle', 6113), ('Death Flayer', 2491), ('Razormane Battleguard', 1964),
          ('Burning Blade Neophyte', 4186), ('Burning Blade Cultist', 4194))
ENEMY_ID, BOSS_ID = 1600, 1690
ENEMY_SIZE, BOSS_SIZE, TIER_SIZE = 80, 104, 8


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


class Code:
    """x86-64 bridge bytes with rel32 branches and RIP-relative operands resolved at a fixed RVA."""
    def __init__(self):
        self.items = []

    def raw(self, hexbytes):
        self.items.append(('raw', bytes.fromhex(hexbytes) if isinstance(hexbytes, str) else hexbytes))
        return self

    def label(self, name):
        self.items.append(('label', name))
        return self

    def rel(self, opcode, target, suffix=''):
        """opcode, then rel32/disp32 to target (an RVA or a label), then suffix bytes."""
        self.items.append(('rel', bytes.fromhex(opcode), target, bytes.fromhex(suffix)))
        return self

    def jmp(self, target):
        return self.rel('e9', target)

    def jcc(self, condition, target):
        return self.rel('0f' + {'e': '84', 'ne': '85', 'b': '82', 'ae': '83', 'be': '86', 'a': '87'}[condition], target)


    def assemble(self, rva):
        labels, at = {}, rva
        for item in self.items:
            if item[0] == 'label':
                labels[item[1]] = at
            else:
                at += len(item[1]) if item[0] == 'raw' else len(item[1]) + 4 + len(item[3])
        out = bytearray()
        for item in self.items:
            if item[0] == 'raw':
                out += item[1]
            elif item[0] == 'rel':
                _, opcode, target, suffix = item
                target = labels[target] if isinstance(target, str) else target
                end = rva + len(out) + len(opcode) + 4 + len(suffix)
                out += opcode + struct.pack('<i', target - end) + suffix
        return bytes(out)


def is_durotar(code, miss):
    """rcx/rdx are the zone ID's bytes and length."""
    return (code.raw('4883fa07').jcc('ne', miss)                 # cmp rdx, 7
                .raw('81396475726f').jcc('ne', miss)             # cmp dword [rcx], 'duro'
                .raw('668179047461').jcc('ne', miss)             # cmp word [rcx+4], 'ta'
                .raw('80790672').jcc('ne', miss))                # cmp byte [rcx+6], 'r'


def sections(data):
    pe = struct.unpack_from('<I', data, 60)[0]
    optional = pe + 24
    if data[pe:pe+4] != b'PE\0\0' or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected a native 64-bit Windows game')
    table = optional + struct.unpack_from('<H', data, pe+20)[0]
    found = []
    for i in range(struct.unpack_from('<H', data, pe+6)[0]):
        at = table + i*40
        virtual, va, size, raw = struct.unpack_from('<IIII', data, at+8)
        found.append((bytes(data[at:at+8]), va, raw, size, virtual))
    return pe, optional, table, found


def apply(source, profile=PROFILE):
    data = bytearray(source)
    pe, optional, table, secs = sections(data)
    base = struct.unpack_from('<Q', data, optional+24)[0]

    def offset(rva):
        for _, va, raw, size, _ in secs:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError('Unsupported native Durotar address')

    def read(rva, size):
        at = offset(rva)
        return bytes(data[at:at+size])

    existing = [s for s in secs if s[0] == SECTION]
    if existing:
        _, va, raw, _, virtual = existing[0]
        hook = profile['hooks']['lookup']['rva']
        if len(existing) > 1 or data[raw:raw+len(MARKER)] != MARKER or read(hook, 1) != b'\xe9':
            raise ValueError('Unknown Durotar section')
        return bytes(data)

    hooks, catalog_rva, count, record = profile['hooks'], profile['catalog'], profile['zones'], profile['record']
    lookup = profile['lookup']
    if read(lookup, hooks['lookup']['size']).hex() != hooks['lookup']['before']:
        raise ValueError('Unsupported native zone layout; analyze this build for Durotar first')
    for hook in hooks.values():
        if read(hook['rva'], hook['size']).hex() != hook['before']:
            raise ValueError('Unsupported native Durotar hook layout')
    for edit in profile['edits']:
        if read(edit['rva'], len(edit['before'])//2).hex() != edit['before']:
            raise ValueError(f"Unsupported native layout: {edit['name']}")
    first_id, first_length = struct.unpack('<QQ', read(catalog_rva + 8, 16))
    if first_length != 6 or read(first_id - base, 6) != b'elwynn':
        raise ValueError('The native zone catalog does not start with Elwynn Forest')

    section_alignment, file_alignment = struct.unpack_from('<II', data, optional+32)
    cva = align(max(v + max(s, z) for _, v, _, s, z in secs), section_alignment)
    header = table + len(secs)*40
    if header + 40 > min(s[2] for s in secs) or any(data[header:header+40]):
        raise ValueError('No room for the Durotar PE section')

    reloc_rva, reloc_size = struct.unpack_from('<II', data, optional+152)
    reloc_data = read(reloc_rva, reloc_size)
    absolute, at = [], 0
    while at < len(reloc_data):
        page, size = struct.unpack_from('<II', reloc_data, at)
        if size < 8:
            raise ValueError('Invalid native relocations')
        absolute += [page + (v & 4095) for v in struct.unpack_from(f'<{(size-8)//2}H', reloc_data, at+8) if v >> 12 == 10]
        at += size

    payload, relocations = bytearray(MARKER), []

    def put(value, boundary=8):
        pos = align(len(payload), boundary)
        payload.extend(b'\0'*(pos - len(payload)))
        payload.extend(value)
        return pos

    def clone(rva, size, extra=0):
        pos = put(read(rva, size) + b'\0'*extra)
        relocations.extend(cva + pos + t - rva for t in absolute if rva <= t < rva + size)
        return pos

    def pointer(at, target):
        struct.pack_into('<Q', payload, at, base + cva + target)
        relocations.append(cva + at)

    def text(at, value):
        encoded = value.encode()
        pointer(at, put(encoded, 1))
        struct.pack_into('<Q', payload, at+8, len(encoded))

    catalog = clone(catalog_rva, count*record, record)
    zone = catalog + count*record
    payload[zone:zone+record] = payload[catalog:catalog+record]
    relocations.extend(cva + zone + t - catalog_rva for t in absolute if catalog_rva <= t < catalog_rva + record)
    text(zone+8, ZONE['id']); text(zone+24, ZONE['name']); text(zone+40, ZONE['subtitle'])
    text(zone+152, ZONE['card']); text(zone+168, ZONE['description'])
    struct.pack_into('<II3f', payload, zone+192, ZONE['map'], ZONE['area'], *ZONE['center'])
    struct.pack_into('<I', payload, zone+220, ZONE['music'])

    first = offset(catalog_rva)
    enemy_rva, enemy_count = struct.unpack_from('<QQ', data, first+120)
    boss_rva, boss_count = struct.unpack_from('<QQ', data, first+136)
    if (enemy_count, boss_count) != (len(ENEMIES), len(BOSSES)):
        raise ValueError('Unexpected Elwynn enemy or boss schedule')
    enemies = clone(enemy_rva - base, enemy_count*ENEMY_SIZE)
    bosses = clone(boss_rva - base, boss_count*BOSS_SIZE)
    for i, (name, display) in enumerate(ENEMIES):
        text(enemies + i*ENEMY_SIZE + 16, name)
        struct.pack_into('<II', payload, enemies + i*ENEMY_SIZE + 32, ENEMY_ID + i, display)
    for i, (name, display) in enumerate(BOSSES):
        at = bosses + i*BOSS_SIZE
        text(at, name); text(at+32, f'{name} joins the battle!')
        # An empty phase list, so the copied Elwynn records summon none of Elwynn's adds.
        struct.pack_into('<QQ', payload, at+48, 8, 0)
        struct.pack_into('<II', payload, at+64, BOSS_ID + i, display)
    pointer(zone+120, enemies); pointer(zone+136, bosses)
    tier = clone(profile['tier'], count*TIER_SIZE, TIER_SIZE)  # Durotar shares Elwynn's tier, zero.
    ui_tier = clone(profile['ui_tier'], count*TIER_SIZE, TIER_SIZE)  # The Armory's own copy.

    def retarget(site, old, new):
        ins = read(site, 7)
        if ins[0] & 0xf0 != 0x40 or ins[1] not in (0x8d, 0x8b) or ins[2] & 0xc7 != 5:
            raise ValueError('Unsupported native zone reference')
        if site + 7 + struct.unpack_from('<i', ins, 3)[0] != old:
            raise ValueError('Native zone reference changed')
        struct.pack_into('<i', data, offset(site)+3, new - site - 7)

    for site in profile['references']:
        target = site + 7 + struct.unpack_from('<i', read(site, 7), 3)[0]
        if catalog_rva <= target < catalog_rva + count*record:
            retarget(site, target, cva + catalog + target - catalog_rva)
        elif profile['tier'] <= target < profile['tier'] + count*TIER_SIZE:
            retarget(site, target, cva + tier + target - profile['tier'])
        else:
            raise ValueError('Native zone reference changed')
    for site in profile['end_references']:
        retarget(site, catalog_rva + count*record, cva + catalog + (count+1)*record)
    for site in profile['ui_tier_references']:
        retarget(site, profile['ui_tier'], cva + ui_tier)
    # The zone picker reads a static (records, count) slice; its pointer is already relocated.
    for site in profile['slices']:
        if struct.unpack('<QQ', read(site, 16)) != (base + catalog_rva, count):
            raise ValueError('Unsupported native zone list')
        struct.pack_into('<QQ', data, offset(site), base + cva + catalog, count + 1)
    for edit in profile['edits']:
        at = offset(edit['rva'])
        data[at:at+len(edit['after'])//2] = bytes.fromhex(edit['after'])

    def bridge(hook, code):
        pos = align(len(payload), 16)
        put(code.assemble(cva + pos), 16)
        at, size = offset(hook['rva']), hook['size']
        data[at:at+size] = b'\xe9' + struct.pack('<i', cva + pos - hook['rva'] - 5) + b'\x90'*(size-5)
        return cva + pos

    h = hooks['lookup']
    bridge(h, is_durotar(Code(), 'original').raw('b80c000000c3')       # mov eax, 12 / ret
           .label('original').raw(h['before']).jmp(h['resume']))
    # Reward and level scaling read Durotar as the first zone's rank.
    pos = align(len(payload), 16)
    rank = cva + pos
    put(is_durotar(Code(), 'normal').raw('31c0c3').label('normal').jmp(lookup).assemble(rank), 16)
    for call in profile['rank_calls']:
        if read(call, 1) != b'\xe8' or call + 5 + struct.unpack_from('<i', read(call, 5), 1)[0] != lookup:
            raise ValueError('Unsupported native zone scaling call')
        struct.pack_into('<i', data, offset(call)+1, rank - call - 5)

    h = hooks['unlock']  # A Durotar victory advances the first progression step and opens Duskwood.
    bridge(h, Code().raw('4883f80c').jcc('ne', 'normal').raw('31c0').label('normal')
           .raw('4883f80a').jcc('a', h['far']).jmp(h['resume']))

    # Starter validation, selection and picker availability accept Durotar on a fresh save.
    for name in ('validate_ae', 'validate_b', 'select_b', 'picker_b', 'picker_ae', 'picker_lea_ae'):
        h = hooks[name]
        before = bytes.fromhex(h['before'])
        if before[:3] not in (bytes.fromhex('4c39c0'), bytes.fromhex('4839c8')):
            raise ValueError('Unsupported native starter comparison')
        code = Code()
        if name == 'picker_lea_ae':
            code.raw(before[3:10])  # lea r13, [rbp+0xc0]; flags are untouched
        code.raw('4883f80c').jcc('e', h['accepted']).raw(before[:3])
        if name.endswith('_b'):
            code.jcc('b', h['accepted']).jmp(h['rejected'])
        else:
            code.jcc('ae', h['rejected']).jmp(h['accepted'])
        bridge(h, code)

    # The picker builds its cards in catalog order. Its loop advances with rbx = next record and
    # r15 = next index; visit Elwynn, Durotar, then the rest, so the starters sit together while
    # every zone keeps its index.
    h = hooks['card_order']
    step = lambda value: struct.pack('<I', value & 0xffffffff).hex()
    bridge(h, Code()
           .raw('4983ff01').jcc('ne', 'durotar')                                   # after Elwynn
           .raw('4881c3' + step((count-1)*record) + '41bf' + step(count)).jmp('next')
           .label('durotar').raw(f'4983ff{count+1:02x}').jcc('ne', 'last')         # after Durotar
           .raw('4881eb' + step(count*record) + '41bf' + step(1)).jmp('next')
           .label('last').raw(f'4983ff{count:02x}').jcc('ne', 'next')              # after the last zone
           .raw('4881c3' + step(record) + '41bf' + step(count+1))
           .label('next').raw(h['before']).jmp(h['resume']))
    # A card is locked when its index reaches the unlocked count; Durotar is a starter.
    for name in ('card_lock', 'card_lock_selected'):
        h = hooks[name]
        before = bytes.fromhex(h['before'])  # cmp rsi, [rcx or rax] / setae byte [rbp+locked]
        if before[:2] != b'\x48\x3b' or before[3:6] != b'\x0f\x93\x85':
            raise ValueError('Unsupported native zone card lock')
        bridge(h, Code().raw(before).raw(f'4883fe{count:02x}').jcc('ne', 'done')           # cmp rsi, 12
               .raw(b'\xc6\x85' + before[6:10] + b'\0').label('done').jmp(h['resume']))  # locked = 0

    # The Armory's drop tables list zones the same way, with the index in a stack slot.
    h = hooks['drop_order']
    before = bytes.fromhex(h['before'])  # mov rcx, [rbp+record] / add rcx, 240 / inc qword [rbp+index]
    if before[:3] != b'\x48\x8b\x8d' or before[7:14] != bytes.fromhex('4881c1f0000000') or before[14:17] != b'\x48\xff\x85':
        raise ValueError('Unsupported native drop table list')
    index = before[17:21]
    set_index = lambda value: b'\x48\xc7\x85' + index + struct.pack('<I', value)
    bridge(h, Code().raw(before).raw(b'\x48\x8b\x85' + index)                       # mov rax, next index
           .raw('4883f801').jcc('ne', 'durotar')
           .raw('4881c1' + step((count-1)*record)).raw(set_index(count)).jmp('next')
           .label('durotar').raw(f'4883f8{count+1:02x}').jcc('ne', 'last')
           .raw('4881e9' + step(count*record)).raw(set_index(1)).jmp('next')
           .label('last').raw(f'4883f8{count:02x}').jcc('ne', 'next')
           .raw('4881c1' + step(record)).raw(set_index(count+1))
           .label('next').jmp(h['resume']))
    is_index_durotar = b'\x48\x83\xbd' + index + bytes([count])                     # cmp qword [rbp+index], 12
    h = hooks['drop_unlocked']  # cmp [rbp+index], rax / setb dil
    bridge(h, Code().raw(h['before']).raw(is_index_durotar).jcc('ne', 'done').raw('40b701')
           .label('done').jmp(h['resume']))
    h = hooks['drop_lock']  # cmp [rbp+index], rax / jae locked
    bridge(h, Code().raw(is_index_durotar).jcc('e', h['accepted']).raw(h['before'][:14])
           .jcc('ae', h['rejected']).jmp(h['accepted']))
    h = hooks['drop_lock_detail']  # mov rax, [rbp+index] / cmp rax, [r12] / jb unlocked
    bridge(h, Code().raw(h['before'][:14]).raw(f'4883f8{count:02x}').jcc('e', h['accepted'])
           .raw(h['before'][14:22]).jcc('b', h['accepted']).jmp(h['resume']))

    # The native server serializes creature-query replies through an ID switch; route Durotar's
    # IDs to its existing enemy and boss serializers using the new records.
    h = hooks['query']
    slot = struct.pack('<I', h['zone_slot']).hex()
    # push rax / mov eax, r14d / sub eax, first ID / cmp eax, last index / jbe ...
    id_range = lambda value, last: '4489f02d' + struct.pack('<I', value).hex() + f'83f8{last:02x}'
    bridge(h, Code().raw('50')
           .raw(id_range(ENEMY_ID, len(ENEMIES)-1)).jcc('be', 'enemy')
           .raw(id_range(BOSS_ID, len(BOSSES)-1)).jcc('be', 'boss')
           .raw('58').raw(h['before']).jmp(h['resume'])
           # imul eax, eax, size / lea r15, [records] / add r15, rax / pop rax / mov r12, rbx / mov rbx, r13
           .label('enemy').raw(f'6bc0{ENEMY_SIZE:02x}').rel('4c8d3d', cva + enemies).raw('4901c7584989dc4c89eb')
           .rel('488d05', cva + zone).raw('488985' + slot).jmp(h['enemy'])  # zone record in its stack slot
           .label('boss').raw(f'6bc0{BOSS_SIZE:02x}').rel('4c8d3d', cva + bosses).raw('4901c7584989dc4c89eb')
           .jmp(h['boss']))

    # Windows relocates every absolute pointer in the copied records under ASLR.
    pages = {}
    for rva in sorted(set(relocations)):
        pages.setdefault(rva & ~4095, []).append(0xa000 | (rva & 4095))
    new_reloc = bytearray(reloc_data)
    for page, words in sorted(pages.items()):
        if len(words) % 2:
            words.append(0)
        new_reloc += struct.pack('<II', page, 8 + 2*len(words)) + struct.pack(f'<{len(words)}H', *words)
    reloc = put(new_reloc, 4)

    raw = align(len(data), file_alignment)
    size = align(len(payload), file_alignment)
    data.extend(b'\0'*(raw + size - len(data)))
    data[raw:raw+len(payload)] = payload
    struct.pack_into('<8sIIIIIIHHI', data, header, SECTION, len(payload), cva, size, raw, 0, 0, 0, 0, 0x60000060)
    struct.pack_into('<H', data, pe+6, len(secs)+1)
    struct.pack_into('<I', data, optional+56, align(cva + len(payload), section_alignment))
    struct.pack_into('<II', data, optional+152, cva + reloc, len(new_reloc))
    struct.pack_into('<I', data, optional+64, 0)
    return bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.write_bytes(apply(args.exe.read_bytes()))
    print(f'Added Durotar: {args.out}')
