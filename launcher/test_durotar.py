"""Durotar executable patch, asset dependency and release contracts, without the game binary."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import durotar_assets
import durotar_patch
import game_release

BASE = 0x140000000
PROFILE = durotar_patch.PROFILE
STRINGS, ENEMIES, BOSSES = PROFILE['tier'] // 4096 * 4096, PROFILE['tier'] // 4096 * 4096 + 0x1000, PROFILE['tier'] // 4096 * 4096 + 0x1400
RELOC = (max(PROFILE['catalog'] + 13*240, *PROFILE['slices']) + 16) // 4096 * 4096 + 0x1000


def fixture(profile=PROFILE):
    """A sparse PE carrying the production profile's original bytes at their reviewed addresses."""
    catalog, lookup = profile['catalog'], profile['lookup']
    used = [lookup, *profile['references'], *profile['end_references'], *profile['rank_calls'],
            *profile['ui_tier_references'], *(e['rva'] for e in profile['edits']),
            *(h['rva'] for h in profile['hooks'].values()), *profile['slices'], profile['ui_tier'], profile['ui_tier'] + 96,
            STRINGS, ENEMIES + 12*80, BOSSES + 5*104, profile['tier'] + 96, catalog + 13*240,
            profile['achievement_points']['table'] + 48, profile['achievement_points']['reference']]
    # One compact section per cluster of used addresses keeps the fixture small.
    sections, raw = [], 0x400
    for address in sorted(used):
        if sections and address + 32 <= sections[-1][1] + 0x100000:
            sections[-1][2] = max(sections[-1][2], (address + 32 - sections[-1][1] + 511) // 512 * 512)
        else:
            sections.append([b'.s%d' % len(sections), address // 4096 * 4096, (address % 4096 + 32 + 511) // 512 * 512])
    for section in sections:
        section.append(raw)
        raw += section[2]
    sections.append([b'.reloc', RELOC, 512, raw])
    data = bytearray(sections[-1][3] + 512)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, len(sections))
    struct.pack_into('<H', data, 0x94, 240)
    optional = 0x98
    struct.pack_into('<H', data, optional, 0x20b)
    struct.pack_into('<Q', data, optional+24, BASE)
    struct.pack_into('<II', data, optional+32, 4096, 512)
    struct.pack_into('<I', data, optional+56, RELOC + 4096)
    for i, (name, va, size, raw) in enumerate(sections):
        struct.pack_into('<8sIIIIIIHHI', data, optional+240+i*40, name, size, va, size, raw, 0, 0, 0, 0, 0x40000040)

    def at(rva):
        return next(raw + rva - va for _, va, size, raw in sections if va <= rva < va + size)

    def put(rva, value):
        data[at(rva):at(rva)+len(value)] = value

    put(STRINGS, b'elwynn')
    for field, value in ((8, (BASE + STRINGS, 6)), (120, (BASE + ENEMIES, 12)), (136, (BASE + BOSSES, 5))):
        put(catalog + field, struct.pack('<QQ', *value))
    put(profile['tier'], struct.pack('<12Q', 0, 0, 1, 1, 2, 2, 3, 3, 5, 5, 4, 4))
    put(profile['ui_tier'], struct.pack('<12Q', 0, 0, 1, 1, 2, 2, 3, 3, 5, 5, 4, 4))
    for site in profile['slices']:
        put(site, struct.pack('<QQ', BASE + catalog, 12))
    for site in profile['ui_tier_references']:
        put(site, b'\x48\x8d\x3d' + struct.pack('<i', profile['ui_tier'] - site - 7))
    relocs = [catalog+8, catalog+120, catalog+136]
    pages = {}
    for rva in relocs:
        pages.setdefault(rva & ~4095, []).append(0xa000 | rva & 4095)
    table = b''.join(struct.pack('<II', page, 8 + 2*len(w + [0]*(len(w) % 2))) + struct.pack(f'<{len(w) + len(w) % 2}H', *w, *[0]*(len(w) % 2))
                     for page, w in pages.items())
    put(RELOC, table)
    struct.pack_into('<II', data, optional+152, RELOC, len(table))
    for site in profile['references']:
        target = profile['tier'] if site in TIER_SITES else catalog + 240
        put(site, b'\x48\x8d\x05' + struct.pack('<i', target - site - 7))
    for site in profile['end_references']:
        put(site, b'\x48\x8d\x0d' + struct.pack('<i', catalog + 12*240 - site - 7))
    for call in profile['rank_calls']:
        put(call, b'\xe8' + struct.pack('<i', lookup - call - 5))
    for edit in profile['edits']:
        put(edit['rva'], bytes.fromhex(edit['before']))
    for hook in profile['hooks'].values():
        put(hook['rva'], bytes.fromhex(hook['before']))
    points = profile['achievement_points']
    put(points['table'], struct.pack('<12I', *points['original']) + b'type')
    put(points['reference'], bytes.fromhex(points['before']))
    return bytes(data)


TIER_SITES = set(PROFILE['references'][-4:])  # Fixture choice: any reference may target the tier table.


def section(data, name):
    pe = struct.unpack_from('<I', data, 60)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe+20)[0]
    for i in range(struct.unpack_from('<H', data, pe+6)[0]):
        if data[table+i*40:table+i*40+8] == name:
            virtual, va, _, raw = struct.unpack_from('<IIII', data, table+i*40+8)
            return va, raw, virtual
    raise AssertionError(name)


def locate(data, rva):
    pe = struct.unpack_from('<I', data, 60)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe+20)[0]
    for i in range(struct.unpack_from('<H', data, pe+6)[0]):
        _, va, size, raw = struct.unpack_from('<IIII', data, table+i*40+8)
        if va <= rva < va + size:
            return raw + rva - va
    raise AssertionError(hex(rva))


def jump_target(data, rva):
    return rva + 5 + struct.unpack_from('<i', data, locate(data, rva)+1)[0]


class DurotarPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = fixture()
        cls.result = durotar_patch.apply(cls.source)

    def string(self, rva):
        pointer, length = struct.unpack_from('<QQ', self.result, locate(self.result, rva))
        at = locate(self.result, pointer - BASE)
        return self.result[at:at+length].decode()

    def test_reapplying_is_unchanged(self):
        self.assertEqual(durotar_patch.apply(self.result), self.result)

    def test_durotar_achievement_uses_ten_points_and_preserves_original_scores(self):
        spec = PROFILE['achievement_points']
        self.assertEqual(struct.unpack_from('<I', self.source, locate(self.source, spec['table'])+48)[0],
                         1701869940)
        site = spec['reference']
        target = site + 7 + struct.unpack_from('<i', self.result, locate(self.result, site)+3)[0]
        self.assertEqual(struct.unpack_from('<13I', self.result, locate(self.result, target)),
                         (*spec['original'], 10))
        self.assertEqual(self.result[locate(self.result, spec['table'])+48:locate(self.result, spec['table'])+52], b'type')

    def test_existing_durotar_installation_gets_points_fix(self):
        with patch.object(durotar_patch, 'achievement_points', side_effect=lambda data, profile: bytes(data)):
            old = durotar_patch.apply(self.source)
        self.assertEqual(durotar_patch.apply(old), self.result)

    def test_unknown_or_damaged_points_layout_is_rejected(self):
        spec = PROFILE['achievement_points']
        site = spec['reference']
        target = site + 7 + struct.unpack_from('<i', self.result, locate(self.result, site)+3)[0]
        for original, at in ((self.source, locate(self.source, spec['table'])),
                             (self.source, locate(self.source, spec['reference'])),
                             (self.result, locate(self.result, target)+48),
                             (self.result, locate(self.result, spec['reference'])+3)):
            damaged = bytearray(original)
            damaged[at] ^= 1
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, 'achievement'):
                durotar_patch.apply(damaged)

    def test_durotar_is_the_thirteenth_record_with_its_own_schedule(self):
        va, _, _ = section(self.result, durotar_patch.SECTION)
        site = PROFILE['references'][0]
        catalog = site + 7 + struct.unpack_from('<i', self.result, locate(self.result, site)+3)[0] - 240
        self.assertGreaterEqual(catalog, va)
        self.assertEqual(self.string(catalog + 8), 'elwynn')
        zone = catalog + 12*240
        self.assertEqual([self.string(zone + f) for f in (8, 24, 40, 152)],
                         ['durotar', 'Durotar', 'The Burning Blade', 'loadscreenasrdurotar'])
        self.assertEqual(struct.unpack_from('<II', self.result, locate(self.result, zone+192)), (1, 14))
        enemies, count = struct.unpack_from('<QQ', self.result, locate(self.result, zone+120))
        self.assertEqual(count, 12)
        self.assertEqual(self.string(enemies - BASE + 16), 'Clattering Scorpid')
        self.assertEqual(struct.unpack_from('<I', self.result, locate(self.result, enemies - BASE + 11*80 + 32))[0], 1611)
        bosses, _ = struct.unpack_from('<QQ', self.result, locate(self.result, zone+136))
        self.assertEqual(struct.unpack_from('<QQI', self.result, locate(self.result, bosses - BASE + 4*104 + 48)), (8, 0, 1694))
        end = PROFILE['end_references'][0]
        self.assertEqual(end + 7 + struct.unpack_from('<i', self.result, locate(self.result, end)+3)[0], catalog + 13*240)

    def test_picker_and_armory_list_thirteen_zones_with_durotar_as_a_starter(self):
        site = PROFILE['references'][0]
        catalog = site + 7 + struct.unpack_from('<i', self.result, locate(self.result, site)+3)[0] - 240
        for slice_site in PROFILE['slices']:
            self.assertEqual(struct.unpack_from('<QQ', self.result, locate(self.result, slice_site)), (BASE + catalog, 13))
        for ref in PROFILE['ui_tier_references']:
            table = ref + 7 + struct.unpack_from('<i', self.result, locate(self.result, ref)+3)[0]
            self.assertEqual(struct.unpack_from('<13Q', self.result, locate(self.result, table)),
                             (0, 0, 1, 1, 2, 2, 3, 3, 5, 5, 4, 4, 0))
        # The card loops visit Elwynn (index 0) then Durotar: after index 0 the next index is 12.
        order = locate(self.result, jump_target(self.result, PROFILE['hooks']['card_order']['rva']))
        self.assertEqual(self.result[order:order+4], bytes.fromhex('4983ff01'))
        self.assertEqual(self.result[order+10:order+23], bytes.fromhex('4881c3500a000041bf0c000000'))

    def test_every_new_pointer_is_relocated(self):
        va, raw, virtual = section(self.result, durotar_patch.SECTION)
        rva, size = struct.unpack_from('<II', self.result, 0x98+152)
        table, relocated, at = self.result[locate(self.result, rva):locate(self.result, rva)+size], set(), 0
        while at < len(table):
            page, block = struct.unpack_from('<II', table, at)
            relocated |= {page + (w & 4095) for w in struct.unpack_from(f'<{(block-8)//2}H', table, at+8) if w >> 12 == 10}
            at += block
        self.assertTrue({PROFILE['catalog']+8, PROFILE['catalog']+120} <= relocated)
        pointers = {va + k for k in range(0, virtual - 7, 8)
                    if BASE <= struct.unpack_from('<Q', self.result, raw + k)[0] < BASE + 0x10000000}
        self.assertTrue(pointers)
        self.assertEqual(pointers - relocated, set())

    def test_hooks_jump_into_bridges_that_return_to_the_game(self):
        va, _, virtual = section(self.result, durotar_patch.SECTION)
        for name, hook in PROFILE['hooks'].items():
            with self.subTest(hook=name):
                at = locate(self.result, hook['rva'])
                self.assertEqual(self.result[at], 0xe9)
                self.assertEqual(self.result[at+5:at+hook['size']], b'\x90'*(hook['size']-5))
                self.assertTrue(va <= jump_target(self.result, hook['rva']) < va + virtual)
        bridge = locate(self.result, jump_target(self.result, PROFILE['lookup']))
        self.assertEqual(self.result[bridge:bridge+4], bytes.fromhex('4883fa07'))
        rank = jump_target(self.result, PROFILE['rank_calls'][0])
        self.assertTrue(all(jump_target(self.result, c) == rank for c in PROFILE['rank_calls']))
        # Four ID checks of ten, twelve, twelve and ten bytes, then xor eax, eax / ret, else the lookup.
        self.assertEqual(self.result[locate(self.result, rank)+44:locate(self.result, rank)+47], bytes.fromhex('31c0c3'))
        self.assertEqual(jump_target(self.result, rank+47), PROFILE['lookup'])

    def test_bounds_extend_to_thirteen_zones(self):
        for edit in PROFILE['edits']:
            at = locate(self.result, edit['rva'])
            self.assertEqual(self.result[at:at+len(edit['after'])//2].hex(), edit['after'])

    def test_unknown_layouts_are_rejected(self):
        for rva in (PROFILE['lookup'], PROFILE['hooks']['query']['rva'], PROFILE['edits'][0]['rva']):
            source = bytearray(self.source)
            source[locate(source, rva)] ^= 1
            with self.subTest(rva=hex(rva)), self.assertRaisesRegex(ValueError, 'Unsupported native'):
                durotar_patch.apply(bytes(source))

    def test_branches_resolve_labels_and_addresses(self):
        code = durotar_patch.Code().jcc('e', 'out').raw('90').label('out').jmp(0x1000).rel('4c8d3d', 0x2000)
        assembled = code.assemble(0x100)
        self.assertEqual(assembled[:2], b'\x0f\x84')
        self.assertEqual(struct.unpack_from('<i', assembled, 2)[0], 1)
        self.assertEqual(0x100 + 12 + struct.unpack_from('<i', assembled, 8)[0], 0x1000)
        self.assertEqual(0x100 + 19 + struct.unpack_from('<i', assembled, 15)[0], 0x2000)


def dbc(rows, strings=b'\0'):
    fields = len(rows[0])
    return (b'WDBC' + struct.pack('<IIII', len(rows), fields, fields*4, len(strings))
            + b''.join(struct.pack(f'<{fields}I', *r) for r in rows) + strings)


class DurotarAssetTests(unittest.TestCase):
    def test_humanoids_bring_their_baked_npc_texture(self):
        strings = b'\0Creature\\Orc\\Orc.mdx\0'
        files = {
            'DBFilesClient\\CreatureDisplayInfo.dbc': dbc([(1, 5, 0, 0, 0, 0, 0, 0, 0), (2, 5, 0, 9, 0, 0, 0, 0, 0)]),
            'DBFilesClient\\CreatureModelData.dbc': dbc([(5, 0, 1)], strings),
            'DBFilesClient\\CreatureDisplayInfoExtra.dbc': dbc([(9, 2, 0, 1)], b'\0abc.blp\0'),
        }

        class Chain:
            read = staticmethod(files.get)

        self.assertEqual(list(durotar_assets.creature_assets(Chain, (1, 2))),
                         ['Creature\\Orc\\Orc.m2', 'Textures\\BakedNpcTextures\\abc.blp', 'Creature\\Orc\\Orc.m2'])


class DurotarReleaseTests(unittest.TestCase):
    def test_game_publish_requires_durotar_data(self):
        from photo_archive import build_photos
        import hashlib
        from main_build import required_data
        photos = required_data()['patch-Z.MPQ']
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)

            def download(args, **kwargs):
                (folder / 'patches.json').write_text(json.dumps({'patches': [{'name': 'patch-Z.MPQ', 'sha256': photos}]}))

            with patch.object(game_release.subprocess, 'run', download):
                with self.assertRaisesRegex(ValueError, 'Publish Durotar first'):
                    game_release.require_live_data('game', folder)

    def test_durotar_publish_retains_other_data(self):
        existing = {'patches': [{'name': 'patch-2.MPQ', 'sha256': 'unchanged', 'parts': [{'url': 'existing.bin'}]},
                                {'name': 'patch-X.MPQ', 'sha256': 'old', 'parts': []}]}

        def download(args, **kwargs):
            (Path(args[args.index('--dir') + 1]) / 'patches.json').write_text(json.dumps(existing))

        def upload(tag, folder, manifests):
            manifest = json.loads((folder / 'patches.json').read_text())
            self.assertEqual(manifests, ['patches.json'])
            self.assertEqual(manifest['patches'][0], existing['patches'][0])
            self.assertEqual([p['name'] for p in manifest['patches']], ['patch-2.MPQ', 'patch-X.MPQ'])
            self.assertNotEqual(manifest['patches'][1]['sha256'], 'old')

        with patch.object(game_release.subprocess, 'run', download), patch.object(game_release, 'upload', upload), \
                patch.object(durotar_assets, 'prepare', lambda source, data: (b'archive', {})):
            game_release.publish_durotar('vanilla', 'data')


if __name__ == '__main__':
    unittest.main()
