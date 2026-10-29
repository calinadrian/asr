"""Source terrain checks for the outdoor Stranglethorn chapter."""
import math
from pathlib import Path
import unittest
import stranglethorn_zone as Z
from durotar_assets import Chain

ROOT=Path(__file__).parents[1]
DATA=ROOT/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

@unittest.skipUnless(DATA.exists(),'Requires vanilla Azeroth terrain')
class JungleTests(unittest.TestCase):
    def test_jungle_is_dry_and_manual_camps_have_room(self):
        self.assertEqual(Z.audit(DATA),(Z.FLOOR_START,*Z.CAMPS))
        for i,p in enumerate(Z.CAMPS):
            self.assertLess(math.dist(p[:2],Z.START[:2]),Z.RADIUS-10)
            self.assertGreater(math.dist(p[:2],Z.START[:2]),24)
            for q in Z.CAMPS[:i]:self.assertGreater(math.dist(p[:2],q[:2]),45)

    def test_spawn_clearance_survives_float32_rounding(self):
        import struct
        chain=Chain(DATA)
        try:
            x,y,z=struct.unpack('<3f',struct.pack('<3f',*Z.START))
            floor,area,wet=Z.terrain_sample(chain,x,y)
            self.assertEqual(area,33);self.assertFalse(wet)
            self.assertGreater(z-floor,.5);self.assertLess(z-floor,1.1)
        finally:chain.close()

if __name__=='__main__':unittest.main()
