"""Check dry terrain, manual elite anchors and source heights for Stonetalon."""
import math
from pathlib import Path
import unittest
import stonetalon_zone as Z
from durotar_assets import Chain

DATA=Path(__file__).parents[1]/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

@unittest.skipUnless(DATA.exists(),'Requires vanilla Kalimdor ADTs')
class TerrainTests(unittest.TestCase):
    def test_manual_placements_match_dry_gently_sloping_terrain(self):
        self.assertEqual(Z.audit(DATA),(Z.FLOOR_START,*Z.CAMPS))
        self.assertGreaterEqual(Z.START[2]-Z.FLOOR_START[2],.5)
        for i,p in enumerate(Z.CAMPS):
            self.assertLess(math.dist(p[:2],Z.START[:2]),Z.RADIUS-10)
            self.assertGreater(math.dist(p[:2],Z.START[:2]),24)
            for q in Z.CAMPS[:i]:self.assertGreater(math.dist(p[:2],q[:2]),45)

    def test_spawn_stays_above_the_installed_terrain_after_float32_rounding(self):
        import struct
        installed=Path(__file__).parents[1]/'downloads/stonetalon/Data'
        chain=Chain(installed)
        try:
            x,y,z=struct.unpack('<3f',struct.pack('<3f',*Z.START))
            actual_floor,_,_=Z.terrain_sample(chain,x,y)
            self.assertGreater(z-actual_floor,.5)
            self.assertLess(z-actual_floor,1.1)
        finally:chain.close()

    def test_arena_rings_avoid_river_and_steep_mountain_sides(self):
        chain=Chain(DATA)
        try:
            for radius in (Z.RADIUS/2,Z.RADIUS):
                for i in range(32):
                    angle=i*math.tau/32
                    z,area,wet=Z.terrain_sample(chain,Z.START[0]+radius*math.cos(angle),Z.START[1]+radius*math.sin(angle))
                    self.assertFalse(wet)
                    self.assertIn(area,(461,636))
                    self.assertLess(z,45)
        finally:chain.close()

if __name__=='__main__':unittest.main()
