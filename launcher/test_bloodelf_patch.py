"""Blood Elf executable patch: locale phrasing everywhere, and the full patch on the installed 0.124.3 game."""
import json
from pathlib import Path
import struct
import unittest

import bloodelf_patch as bp

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
        cls.original = INSTALLED.read_bytes()
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

    def test_lookups_accept_race_10(self):
        for site, value in bp.PROFILE['races']['bounds']:
            first = self.read(self.patched, site, 1)[0]
            at = site + (1 if first == 0x3c else 3 if first in range(0x40, 0x50) else 2)
            self.assertEqual(self.read(self.patched, at, 1)[0], value + 2)

    def test_reapplying_changes_nothing(self):
        self.assertEqual(bp.apply(self.patched), self.patched)

    def test_a_game_without_durotar_is_refused(self):
        data = bytearray(self.original)
        data[data.find(b'.asrzone'):data.find(b'.asrzone') + 8] = b'.asrzonX'
        with self.assertRaises(ValueError):
            bp.apply(bytes(data))


if __name__ == '__main__':
    unittest.main()
