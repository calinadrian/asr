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


if __name__ == '__main__':
    unittest.main()
