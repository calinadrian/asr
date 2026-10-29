"""Regression coverage for the complete added-boss body roster."""
from pathlib import Path
import unittest
from audit_story_bodies import audit
from story_npc_assets import selected_displays

ROOT=Path(__file__).parents[1]
GAME=ROOT/'downloads/barrens/Data'
SOURCE=ROOT/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

@unittest.skipUnless(GAME.exists() and SOURCE.exists(),'Requires native game asset fixtures')
class BossBodyTests(unittest.TestCase):
    def test_all_added_bosses_have_complete_matching_meshes_and_textures(self):
        report=audit(GAME,SOURCE)
        self.assertEqual(report['bosses'],38)
        self.assertEqual({r['zone'] for r in report['results']},{'westfall','deadmines','barrens','wailing','stonetalon','stv','durotar','elwynn'})
        for boss in report['results']:
            self.assertGreater(boss['vertices'],0);self.assertGreater(boss['triangles'],0)
            self.assertGreater(boss['assets_checked'],0)
            if boss['npc_skin']:
                self.assertTrue(boss['isolated'],boss['name'])
                self.assertIn(boss['display'],selected_displays())
        stv=[r['name'] for r in report['results'] if r['zone']=='stv']
        self.assertEqual(stv,["Sin'Dall","Bhag'thera",'Tethis','Colonel Kurzen','King Bangalash'])

if __name__=='__main__':unittest.main()
