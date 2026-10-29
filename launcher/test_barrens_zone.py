"""Verify dry Barrens terrain and manually placed elite camps."""
import math
import struct
from pathlib import Path
import unittest
import barrens_zone as Z
from durotar_assets import Chain

ROOT=Path(__file__).parents[1]
DATA=ROOT/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

@unittest.skipUnless(DATA.exists(),'Requires vanilla Kalimdor terrain')
class BarrensTests(unittest.TestCase):
    def test_dry_savannah_and_separated_manual_camps(self):
        self.assertEqual(Z.audit(DATA),(Z.FLOOR_START,*Z.CAMPS))
        for i,p in enumerate(Z.CAMPS):
            distance=math.dist(p[:2],Z.START[:2])
            self.assertGreater(distance,24);self.assertLess(distance,Z.RADIUS-10)
            for q in Z.CAMPS[:i]:self.assertGreater(math.dist(p[:2],q[:2]),45)

    def test_spawn_has_clearance_above_the_actual_terrain_triangle(self):
        chain=Chain(DATA)
        try:
            x,y,z=struct.unpack('<3f',struct.pack('<3f',*Z.START));floor,area,wet=Z.terrain_sample(chain,x,y)
            self.assertEqual(area,17);self.assertFalse(wet)
            self.assertGreater(z-floor,.5);self.assertLess(z-floor,1.1)
        finally:chain.close()

if __name__=='__main__':unittest.main()
