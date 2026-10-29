"""Extend the reviewed native Blood Elf build to the full requested roster.

Builds a candidate only. Class rules are inherited from explicit templates;
new races have their own verified ASR passive kits. Sparse race IDs
have independent records; NPC race IDs continue to fall back to Human.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import bloodelf_patch as bloodelf
import character_equipment_patch as equipment
from durotar_patch import Code, align, sections
from race_catalog import ADDITIONS, BASE_IDS, PLAYABLE_IDS
import race_racials

MARKER = b'ASR expanded races v1\0'.ljust(64, b'\0')
HEADER_SIZE = 112


class Image:
    def __init__(self, source):
        self.data = bytearray(source)
        self.pe, self.optional, self.table, self.sections = sections(source)
        self.base = struct.unpack_from('<Q', source, self.optional+24)[0]
        matches = [(i, s) for i, s in enumerate(self.sections) if s[0] == b'.asrrace']
        if len(matches) != 1:
            raise ValueError('Expanded races require the reviewed Blood Elf build')
        self.index, (_, self.va, self.raw, self.size, self.virtual) = matches[0]
        if self.raw+self.size != len(source):
            raise ValueError('Expanded races require the final ASR race section')
        self.start = align(self.virtual, 16)
        self.rva = self.va+self.start
        self.payload = bytearray(MARKER+bytes(HEADER_SIZE-len(MARKER)))
        self.edits, self.relocations = {}, []

    def offset(self, rva):
        if 0 <= rva < min(s[2] for s in self.sections):
            return rva
        for _, va, raw, size, _ in self.sections:
            if va <= rva < va+size:
                return raw+rva-va
        raise ValueError(f'Unsupported expanded-race address {rva:#x}')

    def read(self, rva, length):
        at = self.offset(rva)
        return bytes(self.data[at:at+length])

    def edit(self, rva, value):
        at = self.offset(rva)
        self.data[at:at+len(value)] = value
        self.edits[rva] = value.hex()

    def put(self, value, boundary=8):
        pos = align(len(self.payload), boundary)
        self.payload.extend(bytes(pos-len(self.payload)))
        self.payload.extend(value)
        return self.rva+pos

    def code(self, code):
        rva = self.rva+align(len(self.payload), 16)
        return self.put(code.assemble(rva), 16)

    def pointer(self, rva, target):
        struct.pack_into('<Q', self.payload, rva-self.rva, self.base+target)
        self.relocations.append(rva)

    def text(self, at, text):
        encoded = text.encode()
        self.pointer(at, self.put(encoded, 1))
        struct.pack_into('<Q', self.payload, at-self.rva+8, len(encoded))

    def lea(self, site):
        ins = self.read(site, 7)
        if ins[0] & 0xf0 != 0x40 or ins[1] != 0x8d or ins[2] & 0xc7 != 5:
            raise ValueError(f'Unsupported race reference {site:#x}')
        return site+7+struct.unpack_from('<i', ins, 3)[0]

    def retarget(self, site, target):
        self.lea(site)
        self.edit(site+3, struct.pack('<i', target-site-7))

    def hook(self, site, count, target):
        self.edit(site, b'\xe9'+struct.pack('<i', target-site-5)+b'\x90'*(count-5))

    def finish(self, metadata):
        reloc_rva, reloc_size = struct.unpack_from('<II', self.data, self.optional+152)
        reloc = bytearray(self.read(reloc_rva, reloc_size))
        pages = {}
        for rva in sorted(set(self.relocations)):
            pages.setdefault(rva & ~4095, []).append(0xa000 | (rva & 4095))
        for page, words in sorted(pages.items()):
            if len(words) % 2:
                words.append(0)
            reloc += struct.pack('<II', page, 8+len(words)*2)+struct.pack(f'<{len(words)}H', *words)
        reloc_target = self.put(reloc, 4)
        self.edit(self.optional_directory_rva(152), struct.pack('<II', reloc_target, len(reloc)))
        metadata['edits'] = self.edits
        manifest = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()
        manifest_rva = self.put(manifest, 1)
        struct.pack_into('<II', self.payload, 64, manifest_rva-self.rva, len(manifest))
        # Hash includes the manifest, tables and bridges, excluding only this field.
        self.payload[72:104] = hashlib.sha256(self.payload).digest()
        alignment, file_alignment = struct.unpack_from('<II', self.data, self.optional+32)
        virtual = self.start+len(self.payload)
        size = align(virtual, file_alignment)
        self.data.extend(bytes(max(0, self.raw+size-len(self.data))))
        self.data[self.raw+self.start:self.raw+self.start+len(self.payload)] = self.payload
        struct.pack_into('<I', self.data, self.table+self.index*40+8, virtual)
        struct.pack_into('<I', self.data, self.table+self.index*40+16, size)
        struct.pack_into('<I', self.data, self.optional+56, align(self.va+virtual, alignment))
        struct.pack_into('<I', self.data, self.optional+64, 0)
        return bytes(self.data)

    def optional_directory_rva(self, delta):
        # PE optional header lives in the mapped headers, outside section ranges.
        # edit() below handles this directory separately in finish().
        return self.optional+delta


def existing(source):
    image = Image(source)
    at = source.find(MARKER, image.raw, image.raw+image.virtual)
    if at < 0:
        return None
    offset, length = struct.unpack_from('<II', source, at+64)
    end = at+offset+length
    if offset < HEADER_SIZE or end != image.raw+image.virtual:
        raise ValueError('Unknown expanded-race payload length')
    payload = bytearray(source[at:end])
    digest = bytes(payload[72:104])
    payload[72:104] = bytes(32)
    if hashlib.sha256(payload).digest() != digest:
        raise ValueError('Expanded-race payload hash mismatch')
    manifest = json.loads(source[at+offset:end])
    if manifest['race_ids'] != list(PLAYABLE_IDS):
        raise ValueError('Expanded-race roster differs')
    for rva, expected in manifest['edits'].items():
        if image.read(int(rva), len(expected)//2).hex() != expected:
            raise ValueError(f'Expanded-race hook changed at {int(rva):#x}')
    return manifest


def apply(source, catalog):
    previous = existing(source)
    if previous:
        if previous.get('racial_revision') != race_racials.REVISION:
            raise ValueError('Stale racial mechanics; rebuild from the frozen baseline executable')
        if json.dumps(previous['catalog'], sort_keys=True) != json.dumps({str(k): v for k, v in catalog.items()}, sort_keys=True):
            raise ValueError('Existing expanded-race catalog differs from the requested assets')
        return bytes(source)
    # Validate every existing hook and table against its owning patch first.
    source = equipment.apply(bloodelf.apply(source))
    image, p = Image(source), bloodelf.PROFILE
    if set(catalog) != {r.id for r in ADDITIONS}:
        raise ValueError('All requested races must have validated assets')
    ptr, count = struct.unpack('<QQ', image.read(p['races']['slice'], 16))
    if count != len(BASE_IDS):
        raise ValueError('Unexpected input race count')
    source_records = {}
    for i in range(count):
        rva = ptr-image.base+i*88
        rid = struct.unpack('<Q', image.read(rva+80, 8))[0]
        source_records[rid] = rva
    if set(source_records) != set(BASE_IDS):
        raise ValueError('Unexpected input race identities')
    records = image.put(bytes(88*len(PLAYABLE_IDS)))
    positions = {rid: records+i*88 for i, rid in enumerate(PLAYABLE_IDS)}
    for rid in PLAYABLE_IDS:
        spec = next((r for r in ADDITIONS if r.id == rid), None)
        original = source_records[spec.template if spec else rid]
        at = positions[rid]
        image.payload[at-image.rva:at-image.rva+88] = image.read(original, 88)
        for delta in (0, 16, 32, 48, 64):
            image.relocations.append(at+delta)
        if spec:
            image.text(at, spec.name)
            image.text(at+16, catalog[rid]['folder'].upper())
            struct.pack_into('<Q', image.payload, at-image.rva+80, rid)
            race_racials.patch_record(image, at, rid)
    maximum = max(PLAYABLE_IDS)
    lookup = image.put(bytes((maximum-1)*8))
    for rid in range(2, maximum+1):
        image.pointer(lookup+(rid-2)*8, positions.get(rid, records))
    for site in p['races']['human_refs']:
        image.retarget(site, records)
    for site in p['races']['table_refs']:
        image.retarget(site, lookup)
    def bound(site, original):
        first = image.read(site, 1)[0]
        delta = 1 if first == 0x3c else 3 if first in range(0x40, 0x50) else 2
        if image.read(site+delta, 1) != bytes((original+2,)):
            raise ValueError(f'Race bound changed at {site:#x}')
        image.edit(site+delta, bytes((maximum-2+(original-6),)))
    for site, original in p['races']['bounds']:
        bound(site, original)
    for site in p['races']['loops']:
        image.edit(site+2, struct.pack('<I', len(PLAYABLE_IDS)*88))
    image.edit(p['races']['slice'], struct.pack('<QQ', image.base+records, len(PLAYABLE_IDS)))
    def extend_table(site, values, fallback=1):
        original = struct.unpack('<9I', image.read(image.lea(site), 36))
        table = image.put(struct.pack(f'<{maximum-1}I', *[
            values.get(rid, original[rid-2] if rid <= 10 else fallback) for rid in range(2, maximum+1)]), 4)
        image.retarget(site, table)
        return table
    faction = {r.id: (5 if r.faction == 'horde' else 1) for r in ADDITIONS}
    extend_table(p['faction']['ref'], faction)
    bound(*p['faction']['bound'])
    language = {r.id: (1 if r.faction == 'horde' else 7) for r in ADDITIONS}
    extend_table(p['language']['ref'], language, fallback=7)
    bound(*p['language']['bound'])
    for sex, label in enumerate(('male', 'female')):
        table = extend_table(p['display'][label+'_ref'], {r.id: 200000+r.id*2+sex for r in ADDITIONS}, fallback=49+sex)
        spawn_ref = p['transition']['spawn']['references'][1-sex]
        image.retarget(spawn_ref['rva'], table)
    bound(*p['display']['bound'])
    image.edit(p['transition']['spawn']['bound']['rva']+1, bytes((maximum-2,)))
    # Preserve the original calling convention: BL is race-2; return DL boolean.
    horde = image.put(bytes([int(((i+2) & 255) in (2, 5, 6, 8, 10) or faction.get((i+2) & 255) == 5)
                             for i in range(256)]), 1)
    code = (Code().raw('50').raw('0fb6c3').rel('488d15', horde)
            .raw('0fb61402').raw('58').jmp(p['horde']['resume']))
    image.hook(p['horde']['rva'], 14, image.code(code))
    ids = image.put(bytes(PLAYABLE_IDS), 1)
    render = p['render']
    image.edit(render['ranges_bound']['rva']+3, bytes((len(PLAYABLE_IDS),)))
    # Preserve RDX, the original byte-array base, for subsequent loop iterations.
    code = Code().raw('52').rel('488d15', ids).raw('0fb63402').raw('5a').jmp(render['ranges_hook']['rva']+5)
    image.hook(render['ranges_hook']['rva'], 5, image.code(code))
    accepted = image.put(bytes([int(i in PLAYABLE_IDS) for i in range(256)]), 1)
    transition = p['transition']
    code = (Code().raw('5052').raw('400fb6d7').rel('488d05', accepted)
            .raw('803c1000').raw('5a58').jcc('ne', transition['accepted']).jmp(transition['fallback']))
    image.hook(transition['rva'], 5, image.code(code))
    # Correct helmet prefixes using the actual race byte, after the legacy clamp.
    prefixes = image.put(bytes(512), 2)
    for spec in ADDITIONS:
        prefix = catalog[spec.id]['prefix'].encode('ascii')
        if len(prefix) != 2:
            raise ValueError('Native helmet prefixes must contain two ASCII bytes')
        at = prefixes-image.rva+spec.id*2
        image.payload[at:at+2] = prefix
    code = (Code().rel('488d15', equipment.TABLE).raw('4180ff08').jcc('be', 'legacy')
            .raw('4180ff0a').jcc('e', 'bloodelf')
            .raw('5152').rel('488d15', prefixes).raw('410fb6cf').raw('488d0c4a').raw('5a')
            .raw('66833900').jcc('e', 'unknown').raw('4883c408')
            .jmp('done').label('unknown').raw('59').jmp('legacy')
            .label('bloodelf').rel('488d0d', image.put(b'Be', 1)).jmp('done')
            .label('legacy').raw('488b4c11f0').label('done').jmp(equipment.SITE+len(equipment.BEFORE)))
    image.hook(equipment.SITE, len(equipment.BEFORE), image.code(code))
    # Every locale gets the same truthful ASR passive values, never old racials.
    locales = p['locales']
    for i in range(locales['count']):
        entry = locales['table']+i*locales['stride']
        pointer, length = struct.unpack('<QQ', image.read(entry+32, 16))
        strings = json.loads(image.read(pointer-image.base, length))
        for spec in ADDITIONS:
            key = catalog[spec.id]['folder'].lower()
            strings[f'race.{key}.name'] = spec.name
            for line in range(1, 4):
                strings[f'race.{key}.line{line}'] = race_racials.KITS[spec.id][line-1].line
        blob = json.dumps(strings, ensure_ascii=False, separators=(',', ':')).encode()
        target = image.put(blob, 1)
        image.edit(entry+32, struct.pack('<QQ', image.base+target, len(blob)))
    from race_picker_patch import patch_picker
    patch_picker(image, catalog, source_records)
    from character_preview import remove_floor_glow
    remove_floor_glow(image)
    race_racials.allow_passive_only_races(image, p)
    return image.finish(dict(race_ids=list(PLAYABLE_IDS), catalog=catalog,
                             racial_revision=race_racials.REVISION, racials=race_racials.manifest(),
                             source_sha256=hashlib.sha256(source).hexdigest()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('--assets', type=Path, required=True, help='validated W manifest')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.assets.read_text())
    if manifest.get('failures') or len(manifest.get('characters', {})) != 34:
        raise ValueError('All 34 character conversions must pass before building the executable')
    args.out.write_bytes(apply(args.exe.read_bytes(), {int(k): v for k, v in manifest['races'].items()}))
    print(f'Built expanded race candidate: {args.out}')
