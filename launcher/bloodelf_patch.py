"""Add the Blood Elf (DBC race 10) to the native game as a ninth playable race.

The eight race records are copied into a new PE section with the Blood Elf appended, and every
validated lookup is pointed at the copies: the (records, count) slice the picker reads, the
pointer tables that map race IDs 2..8 to records (now 2..10, with 9 falling back to Human as
unknown races always did), the Human fallbacks and the loops over all records. The small
per-race tables (faction template, display IDs, language) get copies with race 10 appended, and
the Horde test learns bit 8. Arcane Torrent is appended to the ability catalog, a copy of War
Stomp's record with its own name, icon and cooldown. Every locale gains the race's name and lines.

native-bloodelf.json holds the reviewed sites of the supported layout: 0.124.3 after
durotar_patch. Every edit checks its original bytes and unknown builds are refused. This patch
rewrites the base-relocation directory, so it runs after durotar_patch.
"""
import argparse
import json
from pathlib import Path
import re
import struct

from durotar_patch import Code, align, sections

SECTION = b'.asrrace'
MARKER = b'ASR Blood Elf v1\0'.ljust(64, b'\0')
PROFILE = json.loads(Path(__file__).with_name('native-bloodelf.json').read_text())

RACE = dict(id=10, name='Blood Elf', key='BLOODELF', active='arcane_torrent',
            passives=((5, 0.05), (2, 0.05)),       # damage reduction, cooldown reduction
            lines=('- Arcane Torrent: every 20 sec, stuns nearby enemies for 2 sec',
                   '- Magic Resistance: +5% damage reduction',
                   '- Arcane Affinity: -5% cooldowns'))
ABILITY = dict(name='Arcane Torrent', icon='Spell_Shadow_Teleport', spell=1449, cooldown=20.0)

# Localized names: (race, Arcane Torrent, Magic Resistance, Arcane Affinity).
NAMES = {
    'en': ('Blood Elf', 'Arcane Torrent', 'Magic Resistance', 'Arcane Affinity'),
    'pl': ('Krwawy elf', 'Potok Arkanów', 'Odporność na magię', 'Powinowactwo z arkanami'),
    'cs': ('Krvavý elf', 'Arkánový proud', 'Odolnost vůči magii', 'Arkánová afinita'),
    'de': ('Blutelf', 'Arkaner Strom', 'Magiewiderstand', 'Arkane Affinität'),
    'pt': ('Elfo Sangrento', 'Torrente Arcana', 'Resistência à Magia', 'Afinidade Arcana'),
    'es': ('Elfo de sangre', 'Torrente Arcano', 'Resistencia a la magia', 'Afinidad arcana'),
    'fr': ('Elfe de sang', 'Torrent arcanique', 'Résistance à la magie', 'Affinité arcanique'),
    'ro': ('Elf de sânge', 'Torent arcan', 'Rezistență la magie', 'Afinitate arcană'),
    'tr': ('Kan Elfi', 'Gizemli Sel', 'Büyü Direnci', 'Gizemli Yakınlık'),
    'ru': ('Эльф крови', 'Волшебный поток', 'Сопротивление магии', 'Родство с тайной магией'),
    'uk': ('Ельф крові', 'Чародійний потік', 'Опір магії', 'Спорідненість з таємною магією'),
    'zh': ('血精灵', '奥术洪流', '魔法抗性', '奥术亲和'),
    'ja': ('ブラッドエルフ', 'アーケイン・トレント', '魔法耐性', 'アーケイン親和'),
    'ko': ('블러드 엘프', '비전 격류', '마법 저항', '비전 친화'),
}


def rename(line, name, numbers=()):
    """A localized racial line with its leading name replaced and its numbers changed."""
    for sep in (' : ', ': ', '：', ':'):
        if sep in line:
            text = line.split(sep, 1)[1]
            break
    else:
        raise ValueError(f'Unexpected racial line {line!r}')
    for old, new in numbers:
        text, count = re.subn(rf'(?<!\d){old}(?!\d)', str(new), text, count=1)
        if not count:
            raise ValueError(f'No {old} in {line!r}')
    return f'{name}{sep}{text}'


def locale_entries(blob, code):
    """The Blood Elf keys for one locale, phrased from the existing Tauren, Night Elf and Gnome lines."""
    strings = json.loads(blob)
    race, torrent, magic, affinity = NAMES[code]
    return {'race.bloodelf.name': race,
            'race.bloodelf.line1': rename(strings['race.tauren.line1'], torrent, ((15, 20),)),
            'race.bloodelf.line2': rename(strings['race.nightelf.line3'], magic),
            'race.bloodelf.line3': rename(strings['race.gnome.line2'], affinity, ((8, 5),)),
            'ability.arcane_torrent.name': torrent}


def extend_json(blob, entries):
    text = blob.decode('utf-8')
    end = text.rstrip().rfind('}')
    body = text[:end].rstrip()
    added = ''.join(f',\n  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}'
                    for k, v in entries.items())
    result = (body + added + '\n' + text[end:]).encode('utf-8')
    json.loads(result)
    return result


def apply(source, profile=PROFILE):
    data = bytearray(source)
    pe, optional, table, secs = sections(data)
    base = struct.unpack_from('<Q', data, optional+24)[0]

    def offset(rva):
        for _, va, raw, size, _ in secs:
            if va <= rva < va + size:
                return raw + rva - va
        raise ValueError('Unsupported native Blood Elf address')

    def read(rva, size):
        at = offset(rva)
        return bytes(data[at:at+size])

    races, abilities = profile['races'], profile['abilities']
    if not any(s[0] == b'.asrzone' for s in secs):
        raise ValueError('Apply durotar_patch first: the Blood Elf patch follows it')
    existing = [s for s in secs if s[0] == SECTION]
    if existing:
        _, va, raw, _, _ = existing[0]
        if len(existing) > 1 or data[raw:raw+len(MARKER)] != MARKER:
            raise ValueError('Unknown Blood Elf section')
        from bloodelf_picker_patch import apply as apply_picker
        from bloodelf_render_patch import apply as apply_render
        from bloodelf_run_patch import apply as apply_run
        return apply_run(apply_render(apply_picker(data, profile['picker']), profile['render']), profile['transition'])

    def lea_target(site):
        ins = read(site, 7)
        if ins[0] & 0xf0 != 0x40 or ins[1] != 0x8d or ins[2] & 0xc7 != 5:
            raise ValueError(f'Unsupported native race reference at {site:#x}')
        return site + 7 + struct.unpack_from('<i', ins, 3)[0]

    def immediate(site):
        """The imm8 of cmp al, imm8 (3c ib), cmp r8, imm8 (80 /7 ib) or its REX form."""
        first = read(site, 1)[0]
        return site + (1 if first == 0x3c else 3 if first in range(0x40, 0x50) else 2)

    def check_bound(site, value):
        if read(immediate(site), 1)[0] != value:
            raise ValueError(f'Unsupported native race bound at {site:#x}')

    # Validate the whole layout before writing anything.
    count, record = races['count'], races['record']
    for site in races['human_refs']:
        if lea_target(site) != races['table']:
            raise ValueError('Native race fallback changed')
    for site in races['table_refs']:
        if lea_target(site) not in races['pointer_tables']:
            raise ValueError('Native race lookup changed')
    pointers = [base + races['table'] + record*i for i in range(1, count)]
    for t in races['pointer_tables']:
        if list(struct.unpack('<7Q', read(t, 56))) != pointers:
            raise ValueError('Unexpected native race pointer table')
    for site, value in races['bounds']:
        check_bound(site, value)
    for site in races['loops']:
        if read(site, 6) != b'\x48\x3d' + struct.pack('<I', count*record):
            raise ValueError('Unsupported native race loop')
    if struct.unpack('<QQ', read(races['slice'], 16)) != (base + races['table'], count):
        raise ValueError('Unsupported native race list')
    first = struct.unpack('<QQ', read(races['table'], 16))
    if read(first[0] - base, first[1]) != b'Human':
        raise ValueError('The native race table does not start with Human')
    for name in ('faction', 'display', 'language'):
        check_bound(*profile[name]['bound'])
    if (lea_target(profile['faction']['ref']) != profile['faction']['table']
            or lea_target(profile['display']['female_ref']) != profile['display']['female']
            or lea_target(profile['display']['male_ref']) != profile['display']['male']
            or lea_target(profile['language']['ref']) != profile['language']['table']):
        raise ValueError('Native per-race table changed')
    horde = profile['horde']
    if read(horde['rva'], len(horde['before'])//2).hex() != horde['before']:
        raise ValueError('Unsupported native Horde test')
    a_table, a_count, a_record = abilities['table'], abilities['count'], abilities['record']
    for site in abilities['refs']:
        if not a_table <= lea_target(site) < a_table + a_count*a_record:
            raise ValueError('Native ability reference changed')
    for site in abilities['bounds']:
        if read(site, 4) != struct.pack('<I', a_count*a_record):
            raise ValueError('Unsupported native ability loop')
    names = []
    for i in range(a_count):
        name, length = struct.unpack('<QQ', read(a_table + a_record*i, 16))
        names.append(read(name - base, length))
    if names.count(abilities['template'].encode()) != 1 or RACE['active'].encode() in names:
        raise ValueError('Unexpected native ability catalog')
    template = names.index(abilities['template'].encode())

    section_alignment, file_alignment = struct.unpack_from('<II', data, optional+32)
    cva = align(max(v + max(s, z) for _, v, _, s, z in secs), section_alignment)
    header = table + len(secs)*40
    if header + 40 > min(s[2] for s in secs) or any(data[header:header+40]):
        raise ValueError('No room for the Blood Elf PE section')

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

    def retarget(site, new):
        struct.pack_into('<i', data, offset(site)+3, cva + new - site - 7)

    # Races: the eight records, then the Blood Elf built from the Human's.
    records = clone(races['table'], count*record, record)
    elf = records + count*record
    payload[elf:elf+record] = payload[records:records+record]
    relocations.extend(cva + elf + t - races['table'] for t in absolute if races['table'] <= t < races['table'] + record)
    text(elf, RACE['name'])
    text(elf+16, RACE['key'])
    passives = put(b''.join(struct.pack('<If', k, v) for k, v in RACE['passives']), 4)
    pointer(elf+32, passives); struct.pack_into('<Q', payload, elf+40, len(RACE['passives']))
    text(elf+48, RACE['active'])
    lines = put(bytes(16*len(RACE['lines'])))
    for i, line in enumerate(RACE['lines']):
        text(lines + 16*i, line)
    pointer(elf+64, lines); struct.pack_into('<Q', payload, elf+72, len(RACE['lines']))
    struct.pack_into('<Q', payload, elf+80, RACE['id'])

    # IDs 2..10: the original seven, then 9 (Goblin, unplayable) as Human and 10 as the Blood Elf.
    lookup = put(bytes(8*9))
    for i, target in enumerate([records + record*k for k in range(1, count)] + [records, elf]):
        pointer(lookup + 8*i, target)
    for site in races['human_refs']:
        retarget(site, records)
    for site in races['table_refs']:
        retarget(site, lookup)

    def widen(site, value):
        data[offset(immediate(site))] = value + 2
    for site, value in races['bounds']:
        widen(site, value)
    for site in races['loops']:
        struct.pack_into('<I', data, offset(site)+2, (count+1)*record)
    struct.pack_into('<QQ', data, offset(races['slice']), base + cva + records, count+1)

    def extend_dwords(table_rva, values):
        return put(read(table_rva, 28) + struct.pack('<2I', *values), 4)
    t = extend_dwords(profile['faction']['table'], profile['faction']['values'])
    retarget(profile['faction']['ref'], t); widen(*profile['faction']['bound'])
    display = profile['display']
    retarget(display['female_ref'], extend_dwords(display['female'], display['values']['female']))
    retarget(display['male_ref'], extend_dwords(display['male'], display['values']['male']))
    widen(*display['bound'])
    t = extend_dwords(profile['language']['table'], profile['language']['values'])
    retarget(profile['language']['ref'], t); widen(*profile['language']['bound'])

    # Arcane Torrent: War Stomp's record (stun nearby enemies) with its own name, icon and cooldown.
    catalog = clone(a_table, a_count*a_record, a_record)
    torrent = catalog + a_count*a_record
    src = catalog + template*a_record
    payload[torrent:torrent+a_record] = payload[src:src+a_record]
    relocations.extend(cva + torrent + t - (a_table + template*a_record) for t in absolute
                       if a_table + template*a_record <= t < a_table + (template+1)*a_record)
    text(torrent, RACE['active']); text(torrent+16, ABILITY['name']); text(torrent+32, ABILITY['icon'])
    struct.pack_into('<I', payload, torrent+64, ABILITY['spell'])
    struct.pack_into('<f', payload, torrent+72, ABILITY['cooldown'])
    for site in abilities['refs']:
        retarget(site, catalog + lea_target(site) - a_table)
    for site in abilities['bounds']:
        struct.pack_into('<I', data, offset(site), (a_count+1)*a_record)

    # The Horde test: bit 8 of the mask is race 10.
    pos = align(len(payload), 16)
    bridge = Code().raw('80fb09').raw('0f92c0').raw('ba59010000').raw('89d9').raw('d3ea').raw('20c2').jmp(horde['resume'])
    put(bridge.assemble(cva + pos), 16)
    at = offset(horde['rva'])
    data[at:at+14] = b'\xe9' + struct.pack('<i', cva + pos - horde['rva'] - 5) + b'\x90'*9

    # Every locale gains the race and its lines. Each entry is (code, name, json, flag).
    locales = profile['locales']
    for i in range(locales['count']):
        entry = locales['table'] + i*locales['stride']
        code_ptr, code_len = struct.unpack('<QQ', read(entry, 16))
        json_ptr, json_len = struct.unpack('<QQ', read(entry+32, 16))
        code = read(code_ptr - base, code_len).decode()
        if code not in NAMES:
            raise ValueError(f'Unexpected native locale {code!r}')
        blob = read(json_ptr - base, json_len)
        extended = extend_json(blob, locale_entries(blob, code))
        struct.pack_into('<QQ', data, offset(entry+32), base + cva + put(extended, 1), len(extended))

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
    from bloodelf_picker_patch import apply as apply_picker
    from bloodelf_render_patch import apply as apply_render
    from bloodelf_run_patch import apply as apply_run
    return apply_run(apply_render(apply_picker(data, profile['picker']), profile['render']), profile['transition'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.write_bytes(apply(args.exe.read_bytes()))
    print(f'Added the Blood Elf: {args.out}')
