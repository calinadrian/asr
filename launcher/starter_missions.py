"""Build a local native 0.124 starter-mission candidate; never edits the input.

Apply after the character/race patches. Existing race assets and saved identities
remain intact. This is a final patch: rebuild from the baseline to change it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from durotar_patch import Code, PROFILE, align, is_durotar, sections

MARKER = b'ASR starter missions v2\0'.ljust(64, b'\0')
TITLE = 'A hero is born'
MISSION_TITLES = {'elwynn': f'Alliance: {TITLE}', 'durotar': f'Horde: {TITLE}'}
PANEL_TITLE = 'Story'
# Shown under each starter card in its faction colour (Bevy Srgba: tag, r, g, b).
FACTION_LINES = {0: ('Alliance only', (0.40, 0.65, 1.0)), 12: ('Horde only', (1.0, 0.45, 0.30))}
ALLIANCE = (1, 3, 4, 7)
HORDE = (2, 5, 6, 8)
# Races open to new characters. Every other race stays listed but dimmed, with
# an empty portrait cell, until a later unlock exists.
UNLOCKED = (*ALLIANCE, *HORDE)
LOCKED_PORTRAIT = (640, 64)
STORIES = {
    'elwynn': "Beneath the calm forests of Elwynn, the first chapter of a greater destiny begins. A young adventurer leaves Northshire Abbey and sets out across Elwynn Forest, helping those in need while unknowingly taking the first steps toward becoming one of Azeroth's greatest heroes.",
    'durotar': 'Beneath the harsh skies of Durotar, a young warrior begins their journey among the newly founded Horde. Helping their people survive in a rugged land, they battle wild beasts, rebellious quilboar, and ancient threats, unaware that their path will one day shape the fate of all Azeroth.',
}
# Retain the correct faction for existing expansion characters, although new
# selections expose only Classic races. Neutral races follow their native template.
HORDE_IDS = (*HORDE, 10, 27, 28, 36, 31, 35, 9, 52)


class Builder:
    def __init__(self, source):
        self.data = bytearray(source)
        self.pe, self.opt, self.table, self.secs = sections(source)
        self.index = len(self.secs)-1
        _, self.va, self.raw, self.size, self.virtual = self.secs[-1]
        if self.raw+self.size != len(source) or self.secs[-1][0] != b'.asrrace':
            raise ValueError('Starter missions require the final reviewed ASR race section')
        self.base = struct.unpack_from('<Q', source, self.opt+24)[0]
        self.start = align(self.virtual, 16)
        self.rva = self.va+self.start
        self.payload = bytearray(MARKER + bytes(48))
        self.edits = {}
        self.originals = {}
        self.relocations = []  # RVAs of absolute pointers this payload adds
        self.writable = False  # the payload holds runtime state

    def offset(self, rva):
        return next(r+rva-v for _, v, r, n, _ in self.secs if v <= rva < v+n)

    def read(self, rva, n):
        at = self.offset(rva)
        return bytes(self.data[at:at+n])

    def put(self, value, boundary=8):
        at = align(len(self.payload), boundary)
        self.payload.extend(bytes(at-len(self.payload))+value)
        return self.rva+at

    def edit(self, rva, value):
        at = self.offset(rva)
        self.originals.setdefault(str(rva), bytes(self.data[at:at+len(value)]).hex())
        self.data[at:at+len(value)] = value
        self.edits[str(rva)] = value.hex()

    def hook(self, site, before, code):
        if self.read(site, len(before)) != before:
            raise ValueError(f'Unsupported starter-mission hook at {site:#x}')
        target = self.rva+align(len(self.payload), 16)
        self.put(code.assemble(target), 16)
        self.edit(site, b'\xe9'+struct.pack('<i', target-site-5)+b'\x90'*(len(before)-5))

    def pointer(self, rva, target):
        """Store an absolute pointer in this payload and relocate it under ASLR."""
        struct.pack_into('<Q', self.payload, rva-self.rva, self.base+target)
        self.relocations.append(rva)

    def text(self, rva, text):
        encoded = text.encode()
        self.pointer(rva, self.put(encoded, 1))
        struct.pack_into('<Q', self.payload, rva-self.rva+8, len(encoded))

    def finish(self):
        directory = struct.unpack_from('<II', self.data, self.opt+152)
        flags_at = self.table+self.index*40+36
        characteristics = struct.unpack_from('<I', self.data, flags_at)[0]
        if self.relocations:
            # Extend a copy of the base-relocation directory, as earlier patches do.
            reloc = bytearray(self.read(*directory))
            pages = {}
            for rva in sorted(set(self.relocations)):
                pages.setdefault(rva & ~4095, []).append(0xa000 | (rva & 4095))
            for page, words in sorted(pages.items()):
                if len(words) % 2:
                    words.append(0)
                reloc += struct.pack('<II', page, 8+2*len(words))+struct.pack(f'<{len(words)}H', *words)
            struct.pack_into('<II', self.data, self.opt+152, self.put(bytes(reloc), 4), len(reloc))
        if self.writable:
            struct.pack_into('<I', self.data, flags_at, characteristics | 0x80000000)
        manifest = json.dumps({'edits': self.edits, 'originals': self.originals,
                               'relocations': list(directory), 'characteristics': characteristics,
                               'virtual': self.virtual, 'size': self.size,
                               'image_size': struct.unpack_from('<I', self.data, self.opt+56)[0],
                               'checksum': struct.unpack_from('<I', self.data, self.opt+64)[0],
                               'tail': bytes(self.data[self.raw+self.virtual:]).hex()}, sort_keys=True).encode()
        at = self.put(manifest, 1)
        struct.pack_into('<II', self.payload, 64, at-self.rva, len(manifest))
        self.payload[72:104] = hashlib.sha256(self.payload).digest()
        virtual = self.start+len(self.payload)
        sa, fa = struct.unpack_from('<II', self.data, self.opt+32)
        size = align(virtual, fa)
        self.data.extend(bytes(self.raw+size-len(self.data)))
        self.data[self.raw+self.start:self.raw+virtual] = self.payload
        struct.pack_into('<I', self.data, self.table+self.index*40+8, virtual)
        struct.pack_into('<I', self.data, self.table+self.index*40+16, size)
        struct.pack_into('<I', self.data, self.opt+56, align(self.va+virtual, sa))
        struct.pack_into('<I', self.data, self.opt+64, 0)
        return bytes(self.data)


def horde(code, operand, yes, no):
    """Compare a byte-sized race without changing any general-purpose register."""
    for race in HORDE_IDS:
        code.raw(operand+bytes([race])).jcc('e', yes)
    return code.jmp(no)


def apply(source):
    image = Builder(source)
    at = source.find(MARKER, image.raw, image.raw+image.virtual)
    if at >= 0:
        offset, length = struct.unpack_from('<II', source, at+64)
        end = at+offset+length
        if offset < 112 or end != image.raw+image.virtual:
            raise ValueError('Unknown starter-mission payload length')
        payload = bytearray(source[at:end])
        digest = bytes(payload[72:104]); payload[72:104] = bytes(32)
        if hashlib.sha256(payload).digest() != digest:
            raise ValueError('Starter-mission payload hash mismatch')
        for rva, expected in json.loads(source[at+offset:end])['edits'].items():
            if image.read(int(rva), len(expected)//2).hex() != expected:
                raise ValueError('Starter-mission hook changed')
        return bytes(source)

    # Resolve the expanded zone slice instead of assuming where a prior patch put it.
    ptr, count = struct.unpack('<QQ', image.read(PROFILE['slices'][0], 16))
    if count != 13:
        raise ValueError('Apply the native Durotar patch first')
    catalog = ptr-image.base
    for index, zone in ((0, 'elwynn'), (12, 'durotar')):
        record = catalog+index*240
        p, n = struct.unpack('<QQ', image.read(record+8, 16))
        if image.read(p-image.base, n).decode() != zone:
            raise ValueError('Unsupported starter zone identities')
        for delta, text in ((40, MISSION_TITLES[zone]), (168, STORIES[zone])):
            encoded = text.encode()
            target = image.put(encoded, 1)
            # Both fields already have native DIR64 relocation entries.
            image.edit(record+delta, struct.pack('<QQ', image.base+target, len(encoded)))

    # English localization overrides the catalog's subtitle and blurb. Extend
    # its active JSON rather than truncating the new text to old string slots.
    # Creature names and boss yells are looked up by creature ID in every
    # locale; the story's creatures are added to each (names are proper nouns,
    # yells are English).
    import bloodelf_patch
    import story_chapters
    creatures = story_chapters.creature_strings()
    locales = bloodelf_patch.PROFILE['locales']
    found = 0
    for i in range(locales['count']):
        entry = locales['table']+i*locales['stride']
        p, n = struct.unpack('<QQ', image.read(entry, 16))
        english = image.read(p-image.base, n) == b'en'
        p, n = struct.unpack('<QQ', image.read(entry+32, 16))
        strings = json.loads(image.read(p-image.base, n))
        strings.update(creatures)
        if english:
            if strings.get('zone.elwynn.subtitle') != 'The Defias Uprising' or strings.get('picker.zone') != 'Zone':
                raise ValueError('Unsupported English starter localization')
            strings['picker.zone'] = PANEL_TITLE
            for chapter in story_chapters.CHAPTERS:
                strings[f'zone.{chapter[0]}.name'] = chapter[1]
                strings[f'zone.{chapter[0]}.subtitle'] = chapter[2]
                strings[f'zone.{chapter[0]}.blurb'] = story_chapters.description(chapter)
            for zone in STORIES:
                strings[f'zone.{zone}.subtitle'] = MISSION_TITLES[zone]
                strings[f'zone.{zone}.blurb'] = STORIES[zone]
            found += 1
        encoded = json.dumps(strings, ensure_ascii=False, separators=(',', ':')).encode()
        target = image.put(encoded, 1)
        image.edit(entry+32, struct.pack('<QQ', image.base+target, len(encoded)))
    if found != 1:
        raise ValueError('Expected one English starter locale')

    # The in-run story narration (starter_story.lua) is not loaded for now; the
    # mission copy above still tells it on the Story cards.

    # Every race stays in its faction row. The picker's allowed list (a Vec<u8>
    # at rbp+0x398) decides which icons are lit and clickable; keep only the
    # unlocked races there. The save validator calls the same builder itself,
    # so existing characters of other races remain valid.
    p = bloodelf_patch.PROFILE['picker']
    if image.read(p['hooks']['loop']['rva'], 1) != b'\xe9':
        raise ValueError('Apply the reviewed race picker first')
    site, before = 0x1fb56c, bytes.fromhex('0f29b570050000')
    code = (Code().raw('50515241504151')  # push rax, rcx, rdx, r8, r9
            .raw('488b8da0030000488b95a80300004531c04531c9')
            .label('next').raw('4939d0').jcc('ae', 'done')
            .raw('428a0401').raw('49ffc0').raw('3c01').jcc('b', 'next').raw('3c08').jcc('a', 'next')
            .raw('42880409').raw('49ffc1').jmp('next')
            .label('done').raw('4c898da8030000')
            .raw('415941585a5958').raw(before).jmp(site+len(before)))
    image.hook(site, before, code)
    # Locked races show an empty atlas cell, so their identity stays hidden.
    site = p['hooks']['portrait']['rva']
    before = image.read(site, 9)
    if before[:1] != b'\xe9':
        raise ValueError('Apply the reviewed race portraits first')
    roster = site+5+struct.unpack_from('<i', before, 1)[0]
    x, y = LOCKED_PORTRAIT
    code = Code().raw('4080ff01').jcc('b', 'locked').raw('4080ff08').jcc('be', roster)
    code.label('locked').rel('f30f1005', image.put(struct.pack('<f', float(x)), 4))
    code.raw('b8'+struct.pack('<I', y).hex()).jmp(p['portrait_ready'])
    image.hook(site, before, code)

    # The expanded card lists every enemy by name, then the boss chips. Story
    # cards keep only the bosses: read the enemy slice as empty.
    site, before = 0x21483b, bytes.fromhex('488b5778488b8780000000')
    image.hook(site, before, Code().raw('488b577831c0').jmp(site+len(before)))

    # The branching story: chapter zones, the open-zone mask and every rule
    # that decides what a hero may pick, enter or unlock.
    import story_chapters
    story_chapters.apply(image, horde, FACTION_LINES)
    return image.finish()


def remove(source):
    """Verify and reverse this final patch before an ordinary restamp/rebuild."""
    image = Builder(source)
    at = source.find(MARKER, image.raw, image.raw+image.virtual)
    if at < 0:
        return bytes(source)
    apply(source)  # Validate the complete payload and all owned edits first.
    offset, length = struct.unpack_from('<II', source, at+64)
    manifest = json.loads(source[at+offset:at+offset+length])
    data = bytearray(source)
    for rva, original in manifest['originals'].items():
        pos = image.offset(int(rva)); value = bytes.fromhex(original)
        data[pos:pos+len(value)] = value
    data = data[:image.raw+manifest['size']]
    data[image.raw+manifest['virtual']:] = bytes.fromhex(manifest['tail'])
    struct.pack_into('<I', data, image.table+image.index*40+8, manifest['virtual'])
    struct.pack_into('<I', data, image.table+image.index*40+16, manifest['size'])
    struct.pack_into('<I', data, image.opt+56, manifest['image_size'])
    struct.pack_into('<I', data, image.opt+64, manifest['checksum'])
    struct.pack_into('<II', data, image.opt+152, *manifest['relocations'])
    struct.pack_into('<I', data, image.table+image.index*40+36, manifest['characteristics'])
    return bytes(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.out.resolve():
        parser.error('Output must be a separate candidate')
    result = apply(args.source.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(result)
