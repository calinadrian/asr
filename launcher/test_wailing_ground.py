"""Validate Wailing Caverns' packaged floors and reproducible source geometry."""
import math
from pathlib import Path
import unittest
import wailing_ground as G

DATA=Path(__file__).parents[1]/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

class GroundTests(unittest.TestCase):
    def test_start_camps_and_all_spawn_targets_are_safe(self):
        heights,targets=G.load()
        safe={i for i,t in enumerate(targets) if t==divmod(i,G.H)}
        self.assertGreater(len(safe),1000)
        for tx,ty in targets:self.assertIn(tx*G.H+ty,safe)
        for point in (G.START,*G.elite_spawns()):
            x,y,z=point;i=int((x-G.X0)//G.CELL)*G.H+int((y-G.Y0)//G.CELL)
            self.assertIn(i,safe)
            self.assertAlmostEqual(z,heights[i],places=2)
        camps=G.elite_spawns()
        for i,a in enumerate(camps):
            self.assertGreaterEqual(math.dist(a[:2],G.START[:2]),24)
            for b in camps[:i]:self.assertGreaterEqual(math.dist(a[:2],b[:2]),45)
        for i in safe:
            gx,gy=divmod(i,G.H)
            self.assertTrue(G.inside(G.X0+(gx+.5)*G.CELL,G.Y0+(gy+.5)*G.CELL,6))
            for dx in (-1,0,1):
                for dy in (-1,0,1):self.assertLessEqual(abs(heights[(gx+dx)*G.H+gy+dy]-heights[i]),1)
        self.assertTrue(all(math.isfinite(z) for z in G.lookup_heights(heights,targets)))

    def test_wdt_global_model_is_an_asset_dependency(self):
        from durotar_assets import dependencies
        name=G.ROOT.encode()+b'\0'
        chunk=b'OMWM'+__import__('struct').pack('<I',len(name))+name
        self.assertEqual(list(dependencies('World/Maps/WailingCaverns/WailingCaverns.wdt',chunk)),[G.ROOT])

    @unittest.skipUnless(DATA.exists(),'Requires vanilla source WMO')
    def test_packaged_grid_matches_vanilla_geometry(self):
        heights,targets=G.build(DATA)
        self.assertEqual(G.pack(heights,targets),G.ASSET.read_bytes())

if __name__=='__main__':unittest.main()
