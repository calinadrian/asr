"""Blood Elf executable patch: locale phrasing everywhere, and the full patch on the installed 0.124.3 game."""
import json
from pathlib import Path
import struct
import unittest

import bloodelf_patch as bp
import durotar_patch
import bloodelf_picker_patch

INSTALLED = Path(r'D:\Personal\ASR\ASR.exe')


class LocaleTests(unittest.TestCase):
    def test_racial_lines_keep_each_language_phrasing(self):
        self.assertEqual(bp.rename('War Stomp: every 15 sec, stuns nearby enemies for 2 sec', 'Arcane Torrent', ((15, 20),)),
                         'Arcane Torrent: every 20 sec, stuns nearby enemies for 2 sec')
        self.assertEqual(bp.rename('Esprit vif : -8% de temps de recharge', 'Affinité arcanique', ((8, 5),)),
                         'Affinité arcanique : -5% de temps de recharge')
        self.assertEqual(bp.rename('Expansive Mind: -%8 bekleme süresi', 'Gizemli Yakınlık', ((8, 5),)),
                         'Gizemli Yakınlık: -%5 bekleme süresi')
        self.assertEqual(bp.rename('战争践踏：每15秒，使附近敌人昏迷2秒', '奥术洪流', ((15, 20),)), '奥术洪流：每20秒，使附近敌人昏迷2秒')

    def test_a_line_without_the_expected_number_is_refused(self):
        with self.assertRaises(ValueError):
            bp.rename('War Stomp: every 30 sec', 'Arcane Torrent', ((15, 20),))

    def test_json_gains_the_keys_and_stays_valid(self):
        blob = '{\n  "race.tauren.line1": "War Stomp: every 15 sec, stuns nearby enemies for 2 sec",\n' \
               '  "race.nightelf.line3": "Nature Resistance: +5% damage reduction",\n' \
               '  "race.gnome.line2": "Expansive Mind: -8% cooldowns"\n}\n'
        out = json.loads(bp.extend_json(blob.encode(), bp.locale_entries(blob.encode(), 'en')))
        self.assertEqual(out['race.bloodelf.name'], 'Blood Elf')
        self.assertEqual(out['race.bloodelf.line2'], 'Magic Resistance: +5% damage reduction')
        self.assertEqual(out['race.bloodelf.line3'], 'Arcane Affinity: -5% cooldowns')
        self.assertEqual(out['ability.arcane_torrent.name'], 'Arcane Torrent')
        self.assertEqual(out['race.tauren.line1'], 'War Stomp: every 15 sec, stuns nearby enemies for 2 sec')

    def test_every_supported_locale_has_names(self):
        self.assertEqual(len(bp.NAMES), bp.PROFILE['locales']['count'])
        self.assertTrue(all(len(v) == 4 and all(v) for v in bp.NAMES.values()))


@unittest.skipUnless(INSTALLED.exists(), 'the installed 0.124.3 game is needed')
class InstalledGameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = durotar_patch.apply(INSTALLED.read_bytes())
        cls.patched = bp.apply(cls.original)

    def read(self, data, rva, size):
        _, _, _, secs = bp.sections(bytearray(data))
        for _, va, raw, length, _ in secs:
            if va <= rva < va + length:
                return data[raw + rva - va:raw + rva - va + size]
        raise KeyError(hex(rva))

    def test_the_race_list_has_nine_records_ending_with_the_blood_elf(self):
        base = 0x140000000
        ptr, count = struct.unpack('<QQ', self.read(self.patched, bp.PROFILE['races']['slice'], 16))
        self.assertEqual(count, 9)
        record = self.read(self.patched, ptr - base + 8*88, 88)
        name, length = struct.unpack_from('<QQ', record)
        self.assertEqual(self.read(self.patched, name - base, length), b'Blood Elf')
        self.assertEqual(struct.unpack_from('<Q', record, 80)[0], 10)

    def test_appearance_picker_uses_bridges_for_faction_rows_and_class_lists(self):
        # The visible Appearance row is independent of the nine-record catalog.
        for name, hook in bp.PROFILE['picker']['hooks'].items():
            instruction = self.read(self.patched, hook['rva'], len(hook['before'])//2)
            self.assertEqual(instruction[0], 0xe9, name)
            target = hook['rva'] + 5 + struct.unpack_from('<i', instruction, 1)[0]
            race_section = next(s for s in bp.sections(self.patched)[3] if s[0] == bp.SECTION)
            self.assertTrue(race_section[1] <= target < race_section[1]+race_section[4], name)
        self.assertEqual(self.patched.count(bloodelf_picker_patch.MARKER), 1)

    def test_customization_loader_includes_blood_elf_after_the_original_eight(self):
        spec = bp.PROFILE['render']
        self.assertEqual(self.read(self.patched, spec['ranges_bound']['rva'], 4).hex(),
                         spec['ranges_bound']['after'])
        self.assertEqual(self.read(self.patched, spec['ranges_hook']['rva'], 1), b'\xe9')

    def test_character_validation_preserves_blood_elf_at_run_start(self):
        site = bp.PROFILE['transition']['rva']
        instruction = self.read(self.patched, site, 5)
        self.assertEqual(instruction[0], 0xe9)
        target = site+5+struct.unpack_from('<i', instruction, 1)[0]
        self.assertEqual(self.read(self.patched, target, 3), bytes.fromhex('83ff0a'))
        damaged = bytearray(self.patched)
        for _, va, raw, size, _ in bp.sections(damaged)[3]:
            if va <= site < va+size:
                damaged[raw+site-va+1] ^= 1
                break
        with self.assertRaisesRegex(ValueError, 'transition'):
            bp.apply(damaged)

    def test_run_spawn_uses_the_extended_male_and_female_display_tables(self):
        spawn = bp.PROFILE['transition']['spawn']
        self.assertEqual(self.read(self.patched, spawn['bound']['rva'], 2).hex(), '3c08')
        for ref in spawn['references']:
            targets = [site+7+struct.unpack_from('<i', self.read(self.patched, site, 7), 3)[0]
                       for site in (ref['rva'], ref['source'])]
            self.assertEqual(targets[0], targets[1])
            self.assertIn(struct.unpack('<9I', self.read(self.patched, targets[0], 36))[-1], (15475, 15476))

    def test_damaged_appearance_hooks_are_refused(self):
        for name, hook in bp.PROFILE['picker']['hooks'].items():
            data = bytearray(self.patched)
            for _, va, raw, size, _ in bp.sections(data)[3]:
                if va <= hook['rva'] < va+size:
                    data[raw+hook['rva']-va+1] ^= 1
                    break
            with self.subTest(hook=name), self.assertRaisesRegex(ValueError, 'picker'):
                bp.apply(data)

    def test_lookups_accept_race_10(self):
        for site, value in bp.PROFILE['races']['bounds']:
            first = self.read(self.patched, site, 1)[0]
            at = site + (1 if first == 0x3c else 3 if first in range(0x40, 0x50) else 2)
            self.assertEqual(self.read(self.patched, at, 1)[0], value + 2)

    def test_reapplying_changes_nothing(self):
        self.assertEqual(bp.apply(self.patched), self.patched)

    def test_blood_elf_and_durotar_points_patches_coexist(self):
        self.assertEqual(durotar_patch.apply(self.patched), self.patched)
        spec = durotar_patch.PROFILE['achievement_points']
        site = spec['reference']
        target = site + 7 + struct.unpack('<i', self.read(self.patched, site+3, 4))[0]
        self.assertEqual(struct.unpack('<13I', self.read(self.patched, target, 52)),
                         (*spec['original'], 10))
        self.assertNotIn(b'.asrachv', [s[0] for s in bp.sections(self.patched)[3]])

    def test_a_game_without_durotar_is_refused(self):
        data = bytearray(self.original)
        data[data.find(b'.asrzone'):data.find(b'.asrzone') + 8] = b'.asrzonX'
        with self.assertRaises(ValueError):
            bp.apply(bytes(data))


if __name__ == '__main__':
    unittest.main()
