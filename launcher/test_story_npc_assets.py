"""NPC model isolation preserves the upgraded roster and zone-photo archive."""
from pathlib import Path
import unittest
from bloodelf_assets import Dbc
from durotar_assets import Chain,dbc,canonical
from photo_archive import read_stored
from story_npc_assets import prepare

ROOT=Path(__file__).parents[1]
SOURCE=ROOT/'downloads/durotar-assets/vanilla-1.12.1/app/Data'
INSTALLED=ROOT/'downloads/stonetalon/Data'

@unittest.skipUnless(SOURCE.exists() and INSTALLED.exists(),'Requires local game asset fixtures')
class NPCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive,cls.report=prepare(SOURCE,INSTALLED)
        blobs=read_stored(cls.archive)
        cls.entries=dict(zip(blobs[0].decode().splitlines(),blobs[1:],strict=True))

    def test_only_selected_npc_displays_change_and_player_rows_are_preserved(self):
        game=Chain(INSTALLED,exclude=('patch-Z.MPQ',))
        try:
            original,_=dbc(game.read(r'DBFilesClient\CreatureDisplayInfo.dbc'))
            patched,_=dbc(self.entries[r'DBFilesClient\CreatureDisplayInfo.dbc'])
            selected={int(v) for v in self.report['displays']}
            self.assertEqual(set(original),set(patched))
            for ident,row in original.items():
                if ident not in selected:self.assertEqual(patched[ident],row)
                else:self.assertEqual(patched[ident][:1]+patched[ident][2:],row[:1]+row[2:])
            models=Dbc(game.read(r'DBFilesClient\CreatureModelData.dbc'))
            result=Dbc(self.entries[r'DBFilesClient\CreatureModelData.dbc'])
            self.assertEqual(result.records[:len(models.records)],models.records)
            self.assertEqual(result.strings[:len(models.strings)],models.strings)
        finally:game.close()

    def test_npc_meshes_are_complete_vanilla_models_and_zone_photos_survive(self):
        vanilla=Chain(SOURCE)
        try:
            for original,alias in self.report['models'].items():self.assertEqual(self.entries[alias],vanilla.read(original))
        finally:vanilla.close()
        previous=read_stored((INSTALLED/'patch-Z.MPQ').read_bytes())
        for name,data in zip(previous[0].decode().splitlines(),previous[1:]):
            if name.lower().startswith('interface\\'):self.assertEqual(self.entries[name],data)
        self.assertEqual(prepare(SOURCE,INSTALLED)[0],self.archive)

if __name__=='__main__':unittest.main()
