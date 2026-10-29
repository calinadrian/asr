"""Protect collection identity and later progression while replacing early armor."""
import json
from pathlib import Path
import struct
import unittest

from starter_missions import Builder
import modern_armor_patch as armor

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'downloads/race-expansion/baseline/ASR.exe'


@unittest.skipUnless(BASE.exists(),'Requires the frozen native fixture')
class NativeArmorTests(unittest.TestCase):
    def test_only_the_two_early_appearance_arrays_change(self):
        source=BASE.read_bytes()
        image=Builder(source)
        records=json.loads(armor.PROFILE.read_text())['records']
        armor.apply(image)
        expected=set()
        for record in records:
            at=image.offset(record['rva'])
            expected.update(range(at,at+64))
            self.assertEqual(struct.unpack('<16I',image.read(record['rva'],64)),
                             tuple(armor.display_id(record['class_id'],tier,slot)
                                   for tier in range(2) for slot in range(8)))
            # Tier 2 onward, class flags, names, bonuses and all drop logic stay byte-identical.
            self.assertEqual(image.data[at+64:at+168],source[at+64:at+168])
        profile=json.loads(armor.PROFILE.read_text())
        for edit in profile['outfit_guards']+profile['starting_cache']:
            at=image.offset(edit['rva'])
            expected.update(range(at,at+len(bytes.fromhex(edit['before']))))
        changed={i for i,(a,b) in enumerate(zip(source,image.data)) if a!=b}
        self.assertTrue(changed)
        self.assertLessEqual(changed,expected)

    def test_changed_native_inputs_are_refused(self):
        image=Builder(BASE.read_bytes())
        record=json.loads(armor.PROFILE.read_text())['records'][0]
        image.data[image.offset(record['rva'])]^=1
        with self.assertRaisesRegex(ValueError,'Unsupported native'):
            armor.apply(image)


class CatalogTests(unittest.TestCase):
    def test_missing_layered_chest_surface_gets_opaque_fabric(self):
        from modern_armor_assets import solid_clothing
        image=(2,1,bytearray((180,120,60,255,255,255,255,0)))
        backing=(2,1,bytearray((30,40,50,255,30,40,50,255)))
        result=solid_clothing(image,backing)
        self.assertEqual(result[2][:4],bytearray((180,120,60,255)))
        self.assertEqual(result[2][4:],bytearray((30,40,50,255)))

    def test_legacy_texture_binding_uses_the_legacy_header(self):
        from modern_armor_assets import rebind_primary
        data=bytearray(0x180)
        struct.pack_into('<II',data,0x5c,1,0x144)
        struct.pack_into('<4I',data,0x144,0,0,4,0x160)
        data[0x160:0x164]=b'old\0'
        result=rebind_primary(data,r'ASR\new.blp')
        count,offset=struct.unpack_from('<II',result,0x5c)
        self.assertEqual((count,offset),(1,0x144))
        _,_,size,name=struct.unpack_from('<4I',result,offset)
        self.assertEqual(result[name:name+size],b'ASR\\new.blp\0')

    def test_unsupported_effect_pass_is_removed_without_removing_solid_armor(self):
        from modern_armor_assets import omit_unsupported_effects
        data=bytearray(0x200)
        struct.pack_into('<II',data,0x4c,1,0x144)
        struct.pack_into('<II',data,0x84,2,0x174)
        struct.pack_into('<HHHH',data,0x174,0,0,17,4)
        struct.pack_into('<II',data,0x144+32,2,0x180)
        struct.pack_into('<H',data,0x180+10,0)
        struct.pack_into('<H',data,0x198+10,1)
        result,omitted=omit_unsupported_effects(data)
        self.assertEqual(omitted,1)
        n,at=struct.unpack_from('<II',result,0x144+32)
        self.assertEqual(n,1)
        self.assertEqual(struct.unpack_from('<H',result,at+10)[0],0)
    def test_visual_ids_are_unique_and_fit_the_legacy_display_range(self):
        records=json.loads(armor.PROFILE.read_text())['records']
        self.assertEqual({r['class_id'] for r in records},{1,2,3,4,5,7,8,9,11})
        ids=[armor.display_id(r['class_id'],tier,slot) for r in records for tier in range(2) for slot in range(8)]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertTrue(all(0<v<65536 for v in ids))

    @unittest.skipUnless(BASE.exists(),'Requires the frozen native fixture')
    def test_built_chapters_use_only_the_two_replaced_tiers(self):
        import story_chapters as story
        from durotar_patch import PROFILE
        image=Builder(BASE.read_bytes())
        tiers=struct.unpack('<12Q',image.read(PROFILE['tier'],96))
        built={*story.ALLIANCE_PATH,*story.HORDE_PATH,story.STV}
        self.assertEqual({tiers[story.SCALE[z]] for z in built},{0,1})


@unittest.skipUnless((ROOT/'downloads/modern-armor/patch-R.MPQ').exists(),'Requires prepared retail armor')
class AssetTests(unittest.TestCase):
    def test_complete_class_sets_and_original_displays_are_preserved(self):
        import hashlib
        from photo_archive import read_stored
        from bloodelf_assets import Dbc,dbc_name
        from durotar_assets import Chain
        root=ROOT/'downloads/modern-armor'
        report=json.loads((root/'patch-R.json').read_text())
        blobs=read_stored((root/'patch-R.MPQ').read_bytes())
        entries=dict(zip(blobs[0].decode().splitlines(),blobs[1:],strict=True))
        self.assertEqual(set(entries),set(report['assets']))
        for name,data in entries.items():
            self.assertEqual(hashlib.sha256(data).hexdigest(),report['assets'][name],name)
        table=Dbc(entries[dbc_name('ItemDisplayInfo')])
        rows={r[0]:r for r in table.rows()}
        game=Chain(ROOT/'downloads/main-build/Data',exclude=('patch-R.MPQ',))
        try:
            before=Dbc(game.read(dbc_name('ItemDisplayInfo')))
            self.assertEqual(table.records[:len(before.records)],before.records)
        finally:game.close()
        self.assertEqual(len(report['sets']),18)
        for kit in report['sets']:
            self.assertEqual(len(kit['displays']),8)
            for item in kit['displays']:
                self.assertIn(item['id'],rows)
            for slot,region in ((2,3),(2,4),(4,5),(4,6),(5,7),(7,2)):
                self.assertEqual({t['sex'] for t in kit['textures'] if (t['slot'],t['region'])==(slot,region)}, {'M','F'})
            self.assertEqual({(h['race'],h['sex']) for h in kit['helmets'] if h['race']==1},{(1,'M'),(1,'F')})
        import blp
        for name,data in entries.items():
            if '_chest_tu_' in name.lower() or '_chest_tl_' in name.lower():
                self.assertTrue(all(a==255 for a in blp.decode(data,0)[2][3::4]),name)
        self.assertEqual({r['race'] for r in report['unsupported']},{52})
        after=Dbc(entries[dbc_name('CharStartOutfit')])
        game=Chain(ROOT/'downloads/main-build/Data',exclude=('patch-R.MPQ',))
        try:before=Dbc(game.read(dbc_name('CharStartOutfit')))
        finally:game.close()
        self.assertEqual(len(before.records),len(after.records))
        for old,new in zip(before.records,after.records):
            self.assertEqual(old[:56],new[:56])  # identities and all gameplay item IDs


if __name__=='__main__':unittest.main()
