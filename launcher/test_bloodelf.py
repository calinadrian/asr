"""Blood Elf DBC rows and archive consistency, on synthetic 1.12 tables."""
import struct
import unittest

import bloodelf_assets as ba


def table(fields, rows, size=None):
    """A WDBC with u32 rows; str values go to the string block."""
    strings = bytearray(b'\0')
    records = []
    for row in rows:
        words = []
        for v in row:
            if isinstance(v, str):
                words.append(len(strings))
                strings += v.encode() + b'\0'
            else:
                words.append(v)
        records.append(struct.pack(f'<{len(words)}I', *words))
    size = size or fields * 4
    return struct.pack('<4sIIII', b'WDBC', len(records), fields, size, len(strings)) + b''.join(records) + bytes(strings)


def human_race(race_id, faction):
    row = [race_id, 12, faction, 4140, 49, 50, 'Hu', 0x3F800000, 7, 7, 836, 1604, 15007, 1096, 2, 'Human', 81,
           'Human', 0, 0, 0, 0, 0, 0, 0, 8323199, 'NORMAL', 'PIERCINGS', 'NORMAL']
    return row


def tables():
    return dict(
        ChrRaces=ba.Dbc(table(29, [human_race(1, 1), human_race(5, 5)])),
        CharBaseInfo=ba.Dbc(struct.pack('<4sIIII', b'WDBC', 1, 2, 2, 1) + bytes((1, 1)) + b'\0'),
        CharSections=ba.Dbc(table(10, [[7, 1, 0, 0, 0, 0, 'Skin.blp', 0, 0, 0]])),
        CharHairGeosets=ba.Dbc(table(6, [[3, 1, 0, 0, 0, 1]])),
        CharacterFacialHairStyles=ba.Dbc(table(9, [[1, 0, 0, 0, 0, 0, 1, 1, 1]])),
        CreatureDisplayInfo=ba.Dbc(table(12, [[49, 49, 0, 0, 0x3F800000, 255, 0, 0, 0, 1, 0, 0],
                                              [50, 50, 0, 0, 0x3F800000, 255, 0, 0, 0, 1, 0, 0]])),
        CreatureModelData=ba.Dbc(table(16, [[49, 4, 'Character\\Human\\Male\\HumanMale.mdx'] + [0] * 13,
                                            [50, 4, 'Character\\Human\\Female\\HumanFemale.mdx'] + [0] * 13])))


def model(geosets):
    """The smallest v256 file verify() reads: a view whose submeshes carry these geoset IDs."""
    data = bytearray(0x144)
    data[0:8] = b'MD20' + struct.pack('<I', 256)
    view = len(data)
    data += bytes(44)
    struct.pack_into('<II', data, 0x4C, 1, view)
    struct.pack_into('<II', data, view + 24, len(geosets), len(data))
    for g in geosets:
        data += struct.pack('<H', g) + bytes(30)
    return bytes(data)


class RowTests(unittest.TestCase):
    def setUp(self):
        self.t = tables()
        rows = {sex: ([(10, sex, s, 0, 0, f'{ba.FOLDER}\\{sex}{s}.blp', '', '') for s in range(5)],
                      [(0, 2), (1, 3)], [(0, 100), (1, 102)] if sex == 0 else [])
                for sex in (0, 1)}
        self.models = {0: f'{ba.FOLDER}\\Male\\BloodElfMale.m2', 1: f'{ba.FOLDER}\\Female\\BloodElfFemale.m2'}
        ba.add_rows(self.t, rows, self.models)
        self.entries = {ba.dbc_name(k): v.bytes() for k, v in self.t.items()}
        self.entries[self.models[0]] = model([0, 2, 3, 102])
        self.entries[self.models[1]] = model([0, 2, 3])
        for sex in (0, 1):
            for s in range(5):
                self.entries[f'{ba.FOLDER}\\{sex}{s}.blp'] = b'BLP2'

    def test_race_row_copies_the_human_with_horde_faction_and_new_displays(self):
        races = ba.Dbc(self.entries[ba.dbc_name('ChrRaces')])
        row = next(r for r in races.rows() if r[0] == 10)
        self.assertEqual(row[2], 5)
        self.assertEqual((row[4], row[5]), (15476, 15475))
        self.assertEqual((races.string(row[6]), races.string(row[15]), races.string(row[17])),
                         ('Be', 'BloodElf', 'Blood Elf'))
        self.assertEqual(row[16], 0)

    def test_displays_reach_mdx_names_of_the_converted_models(self):
        models = ba.Dbc(self.entries[ba.dbc_name('CreatureModelData')])
        names = [models.string(r[2]) for r in models.rows()]
        self.assertIn('Character\\BloodElf\\Male\\BloodElfMale.mdx', names)
        displays = ba.Dbc(self.entries[ba.dbc_name('CreatureDisplayInfo')]).rows()
        self.assertEqual(sorted(r[0] for r in displays), [49, 50, 15475, 15476])

    def test_byte_records_and_ids_continue_from_the_table(self):
        base = ba.Dbc(self.entries[ba.dbc_name('CharBaseInfo')])
        self.assertEqual([r[1] for r in base.records if r[0] == 10], list(ba.CLASSES))
        sections = ba.Dbc(self.entries[ba.dbc_name('CharSections')]).rows()
        self.assertEqual([r[0] for r in sections], list(range(7, 18)))
        facial = [r for r in ba.Dbc(self.entries[ba.dbc_name('CharacterFacialHairStyles')]).rows() if r[0] == 10]
        self.assertEqual([(r[1], r[2], r[6]) for r in facial], [(0, 0, 0), (0, 1, 2), (1, 0, 0)])

    def test_consistent_data_verifies(self):
        self.assertEqual(ba.verify(self.entries, NoGame()), [])

    def test_verify_names_missing_textures_and_geosets(self):
        del self.entries[f'{ba.FOLDER}\\03.blp']
        self.entries[self.models[1]] = model([0, 2])
        problems = ba.verify(self.entries, NoGame())
        self.assertTrue(any('03.blp' in p for p in problems))
        self.assertTrue(any('absent geoset 3' in p for p in problems))

    def test_a_second_race_10_is_refused(self):
        with self.assertRaises(ValueError):
            ba.add_rows(self.t, {}, {})

    def test_strings_are_shared_and_record_sizes_checked(self):
        races = self.t['ChrRaces']
        self.assertEqual(races.text('Human'), races.text('Human'))
        with self.assertRaises(ValueError):
            races.add([1, 2, 3])


class NoGame:
    def read(self, name):
        return None


if __name__ == '__main__':
    unittest.main()
