"""Release contracts that run without game binaries, accounts or a graphics device."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import game_release
import photo_archive
import zone_cards
import zone_light


ROOT = Path(__file__).resolve().parents[1]


class ZonePatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(zone_cards.PROFILE.read_text())

    def fixture(self):
        # Sparse virtual addresses, compact file sections: exercise the actual
        # production profile without distributing the third-party executable.
        code = [p for p in self.profile['patches'] if p['rva'] < 0x6000000]
        strings = [p for p in self.profile['patches'] if p['rva'] >= 0x6000000]
        sections = []
        raw = 0x400
        for name, patches in ((b'.text', code), (b'.rdata', strings)):
            va = min(p['rva'] for p in patches) // 4096 * 4096
            end = max(p['rva'] + len(bytes.fromhex(p['before'])) for p in patches)
            size = (end - va + 511) // 512 * 512
            sections.append((name, va, size, raw))
            raw += size
        data = bytearray(raw)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 0x80)
        data[0x80:0x84] = b'PE\0\0'
        struct.pack_into('<HH', data, 0x84, 0x8664, 2)
        struct.pack_into('<H', data, 0x94, 240)
        optional = 0x98
        struct.pack_into('<H', data, optional, 0x20b)
        struct.pack_into('<Q', data, optional + 24, 0x140000000)
        struct.pack_into('<II', data, optional + 32, 4096, 512)
        for index, (name, va, size, pos) in enumerate(sections):
            struct.pack_into('<8sIIIIIIHHI', data, optional + 240 + index * 40,
                             name, size, va, size, pos, 0, 0, 0, 0, 0x40000040)
        for entry in self.profile['patches']:
            for _, va, size, pos in sections:
                if va <= entry['rva'] < va + size:
                    before = bytes.fromhex(entry['before'])
                    at = pos + entry['rva'] - va
                    data[at:at + len(before)] = before
                    break
        return bytes(data)

    @staticmethod
    def locate(data, rva):
        pe = struct.unpack_from('<I', data, 60)[0]
        table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
        for i in range(struct.unpack_from('<H', data, pe + 6)[0]):
            _, va, size, raw = struct.unpack_from('<IIII', data, table + i * 40 + 8)
            if va <= rva < va + size:
                return raw + rva - va
        raise AssertionError(f'Unmapped address {rva:x}')

    def test_native_instruction_address_and_typed_inset(self):
        result = zone_cards.apply(self.fixture())
        entry = next(p for p in self.profile['patches'] if p.get('after_template'))
        at = self.locate(result, entry['rva'])
        target = entry['rva'] + 7 + struct.unpack_from('<i', result, at + 3)[0]
        red = struct.unpack_from('<4f', result, self.locate(result, target))
        self.assertEqual(red[:2], (0, 1))
        self.assertAlmostEqual(red[2], .36, places=5)
        self.assertAlmostEqual(red[3], .32, places=5)
        inset = next(p for p in self.profile['patches'] if 'scroll viewport' in p['name'])
        self.assertEqual(struct.unpack_from('<IfIf', bytes.fromhex(self.profile['payload']), inset['constant']), (1, 20, 1, 20))

    def test_all_previous_profiles_upgrade_and_reapply(self):
        source = self.fixture()
        expected = zone_cards.apply(source)
        self.assertEqual(zone_cards.apply(expected), expected)
        for previous in self.profile['previous']:
            with self.subTest(version=previous['format']):
                old = zone_cards.apply(source, previous)
                self.assertEqual(zone_cards.apply(old), expected)

    def test_unknown_code_is_rejected(self):
        source = bytearray(self.fixture())
        source[self.locate(source, self.profile['patches'][0]['rva'])] ^= 1
        with self.assertRaisesRegex(ValueError, 'Unsupported native game layout'):
            zone_cards.apply(source)


class PhotoPublishTests(unittest.TestCase):
    def test_incremental_publish_retains_existing_data_and_metadata(self):
        existing = {'format': 1, 'patches': [{'name': 'patch-2.MPQ', 'sha256': 'unchanged', 'parts': [{'url': 'existing.bin'}]}]}
        expected = photo_archive.build_photos(game_release.ROOT / 'launcher/zone-photos')

        def download(args, **kwargs):
            folder = Path(args[args.index('--dir') + 1])
            (folder / 'patches.json').write_text(json.dumps(existing))

        def upload(tag, folder, manifests):
            self.assertEqual(manifests, ['patches.json'])
            manifest = json.loads((folder / 'patches.json').read_text())
            self.assertEqual(manifest['format'], 1)
            self.assertEqual(manifest['patches'][0], existing['patches'][0])
            self.assertEqual(len(manifest['patches']), 2)
            photos = manifest['patches'][1]
            self.assertEqual(photos['name'], 'patch-Z.MPQ')
            self.assertEqual(photos['sha256'], hashlib.sha256(expected).hexdigest())
            packed = b''.join((folder / p['url']).read_bytes() for p in photos['parts'])
            self.assertEqual(gzip.decompress(packed), expected)
            self.assertEqual(sum(f.startswith(b'BLP2') for f in photo_archive.read_stored(expected)), 12)

        with patch.object(game_release.subprocess, 'run', download), patch.object(game_release, 'upload', upload):
            game_release.publish_zone_photos()

    def test_game_publish_uploads_the_game_before_the_helper_that_fetches_it(self):
        uploaded = []

        class Pushed:
            stdout = '  origin/main\n'

        with patch.object(game_release.subprocess, 'run', lambda *a, **k: Pushed()), \
                patch.object(game_release, 'require_zone_photos', lambda tag, folder: None), \
                patch.object(game_release, 'prepare', lambda exe, version, notes, folder: None), \
                patch.object(game_release, 'ensure_release', lambda tag: None), \
                patch.object(game_release, 'describe', lambda *a: None), \
                patch.object(game_release, 'upload', lambda tag, folder, manifests: uploaded.append(manifests)):
            game_release.publish('game.exe', '0.120.9', 'notes')
        self.assertEqual(uploaded, [['game.json', 'latest.json']])

    def test_game_publish_rejects_missing_photo_data(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)

            def download(args, **kwargs):
                (folder / 'patches.json').write_text('{"patches":[]}')

            with patch.object(game_release.subprocess, 'run', download):
                with self.assertRaisesRegex(ValueError, 'Publish data first'):
                    game_release.require_zone_photos('game', folder)


class AddonPublishTests(unittest.TestCase):
    def test_each_addon_zips_with_its_folder_at_the_root(self):
        with tempfile.TemporaryDirectory() as scratch:
            zips = game_release.pack_addons(Path(scratch))
            self.assertIn('ASR_HUD.zip', [z.name for z in zips])
            import zipfile
            with zipfile.ZipFile(Path(scratch) / 'ASR_HUD.zip') as archive:
                names = archive.namelist()
            self.assertIn('ASR_HUD/ASR_HUD.toc', names)
            toc = (game_release.ROOT / 'launcher/addon/ASR_HUD/ASR_HUD.toc').read_text()
            for line in toc.splitlines():
                if line and not line.startswith('#'):
                    self.assertIn('ASR_HUD/' + line, names)
            entry = next(a for a in game_release.addons_manifest(zips)['addons'] if a['name'] == 'ASR_HUD')
            data = (Path(scratch) / 'ASR_HUD.zip').read_bytes()
            self.assertEqual(entry, dict(name='ASR_HUD', url='ASR_HUD.zip', size=len(data),
                                         sha256=hashlib.sha256(data).hexdigest()))


class ZoneLightTests(unittest.TestCase):
    def table(self, rows):
        """A LightIntBand.dbc with one record per (id, colours)."""
        records = b''
        for id, colours in rows:
            padding = [0] * (16 - len(colours))
            records += struct.pack('<34I', id, len(colours), *range(len(colours)), *padding, *colours, *padding)
        return struct.pack('<4sIIII', b'WDBC', len(rows), 34, 136, 1) + records + bytes(1)

    def colours(self, dbc):
        count = struct.unpack_from('<I', dbc, 4)[0]
        return [struct.unpack_from('<%dI' % struct.unpack_from('<I', dbc, 24 + i * 136)[0], dbc, 92 + i * 136)
                for i in range(count)]

    def luminance(self, colour):
        return zone_light.luminance(colour >> 16 & 255, colour >> 8 & 255, colour & 255)

    def test_dark_light_rises_to_its_floor_and_bright_light_is_kept(self):
        night, noon = 0xff1a3855, 0xff9db2c8  # Duskwood's night ambient; an already bright colour
        # Ids count from 1 in blocks of 18 rows: 2 is an ambient row, 3 a sky row, 20 the next block's ambient.
        lifted = self.colours(zone_light.brighten(self.table([(2, [night, noon]), (3, [night]), (20, [0xff000000])])))
        self.assertAlmostEqual(self.luminance(lifted[0][0]), zone_light.FLOORS[1], delta=0.01)
        r, g, b = lifted[0][0] >> 16 & 255, lifted[0][0] >> 8 & 255, lifted[0][0] & 255
        self.assertTrue(r < g < b, 'keeps the blue hue')
        self.assertEqual(lifted[0][1], noon)
        self.assertEqual(lifted[1], (night,), 'sky rows are untouched')
        self.assertEqual(lifted[2][0] >> 24, 0xff, 'keeps alpha')
        self.assertAlmostEqual(self.luminance(lifted[2][0]), zone_light.FLOORS[1], delta=0.01)

    def aura(self):
        """A version 256 glow model: one dim red colour, 45% strength, one fogged additive material."""
        m2 = bytearray(0x200)
        m2[:8] = b'MD20\x00\x01\x00\x00'

        def track(at, values):
            struct.pack_into('<HhIIIIII', m2, at, 0, -1, 0, 0, 0, 0, 1, values)

        struct.pack_into('<II', m2, 0x54, 1, 0x150)  # colours
        track(0x150, 0x1c0)
        track(0x16c, 0x1d0)
        struct.pack_into('<II', m2, 0x64, 1, 0x188)  # transparency
        track(0x188, 0x1d4)
        struct.pack_into('<II', m2, 0x84, 1, 0x1a4)  # materials
        struct.pack_into('<HH', m2, 0x1a4, 0x14, 4)
        struct.pack_into('<3f', m2, 0x1c0, 0.682, 0.161, 0.0)
        struct.pack_into('<h', m2, 0x1d0, 32767)
        struct.pack_into('<h', m2, 0x1d4, 14745)
        return bytes(m2)

    def test_boundary_aura_is_full_strength_bright_unfogged_and_unlit(self):
        m2 = zone_light.vivid(self.aura())
        r, g, b = struct.unpack_from('<3f', m2, 0x1c0)
        self.assertEqual(r, 1.0)
        self.assertAlmostEqual(g, 0.161 / 0.682, places=4)
        self.assertEqual(struct.unpack_from('<h', m2, 0x1d4)[0], 32767)
        self.assertEqual(struct.unpack_from('<HH', m2, 0x1a4), (0x14 | zone_light.UNLIT | zone_light.UNFOGGED, 4))
        self.assertEqual(len(m2), 0x200)

    def test_archive_lifts_the_highest_game_patch_and_reads_back(self):
        dbc = self.table([(2, [0xff1a3855])])
        auras = {name: self.aura() for name in zone_light.AURAS}
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch)
            (data / 'patch.MPQ').write_bytes(photo_archive.build({zone_light.NAME: b'old', **auras}))
            (data / 'patch-2.MPQ').write_bytes(photo_archive.build({zone_light.NAME: dbc}))
            (data / 'patch-Y.MPQ').write_bytes(photo_archive.build({zone_light.NAME: b'ours'}))
            self.assertEqual(zone_light.original(data), dbc)
            archive = data / 'out.MPQ'
            archive.write_bytes(zone_light.build_lighting(data))
            self.assertEqual(zone_light.read_mpq(archive, zone_light.NAME), zone_light.brighten(dbc))
            for name in zone_light.AURAS:
                self.assertEqual(zone_light.read_mpq(archive, name), zone_light.vivid(auras[name]))


if __name__ == '__main__':
    unittest.main()
