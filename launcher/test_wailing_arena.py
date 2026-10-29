"""Barricade collision and native radius/camp regression tests for Wailing."""
import math
import struct
import unittest
from pathlib import Path
import wailing_arena as A
import wailing_ground as G
from durotar_assets import Chain,chunks
from test_deadmines_arena import intersects

DATA=Path(__file__).parents[1]/'downloads/durotar-assets/vanilla-1.12.1/app/Data'

@unittest.skipUnless(DATA.exists(),'Requires vanilla Wailing WMO')
class BarricadeTests(unittest.TestCase):
    def test_unchanged_portals_and_lower_barricade_with_open_upper_ramp(self):
        entries=A.build_entries(DATA)
        self.assertEqual(set(entries),{A.GROUP})
        chain=Chain(DATA)
        try:original=dict(chunks(chain.read(A.GROUP)))[b'MOGP']
        finally:chain.close()
        body=dict(chunks(entries[A.GROUP]))[b'MOGP']
        self.assertEqual(original[:12],body[:12])
        self.assertEqual(original[36:44],body[36:44])
        before=dict(chunks(original[68:]));after=dict(chunks(body[68:]))
        for tag in (b'MOPY',b'MOVI',b'MOVT',b'MONR',b'MOTV',b'MOCV',b'MOBA',b'MOBN',b'MOBR'):
            self.assertTrue(after[tag].startswith(before[tag]),tag)
        verts=list(struct.iter_unpack('<3f',after[b'MOVT']))
        indices=struct.unpack(f'<{len(after[b"MOVI"])//2}H',after[b'MOVI'])
        render_count=struct.unpack_from('<H',after[b'MOBA'][-24:],16)[0]//3
        first=len(before[b'MOVI'])//6
        triangles=[]
        for k in range(first,len(indices)//3):
            flag=after[b'MOPY'][k*2]
            self.assertTrue(flag&2)
            if k<first+render_count:self.assertTrue(flag&4)
            else:
                self.assertFalse(flag&4)
                triangles.append([verts[v] for v in indices[k*3:k*3+3]])
        self.assertEqual(len(A.GATES),1)
        # The removed upper wall must leave neither boards nor invisible collision.
        added_verts=verts[len(before[b'MOVT'])//12:]
        self.assertTrue(all(v[0]<100 for v in added_verts))
        self.assertFalse(any(intersects((108.,-450.,-72.),(112.,-450.,-72.),t) for t in triangles))
        for gate in A.GATES:
            ax,ay=gate.start;bx,by=gate.end;length=math.hypot(bx-ax,by-ay);nx,ny=(by-ay)/length,-(bx-ax)/length
            for along in (.01,.25,.5,.75,.99):
                x,y=ax+(bx-ax)*along,ay+(by-ay)*along
                for z in (A.COLLISION_BOTTOM+1,gate.bottom-2,gate.bottom+.2,(gate.bottom+gate.top)/2,gate.top+4,A.COLLISION_TOP-1):
                    a,b=(x-nx*2,y-ny*2,z),(x+nx*2,y+ny*2,z)
                    self.assertTrue(any(intersects(a,b,t) for t in triangles),(gate,along,z))
                    self.assertTrue(any(intersects(b,a,t) for t in triangles),(gate,along,z))

    def test_circle_outside_whole_room_and_manual_elite_anchors(self):
        chain=Chain(DATA)
        try:body=dict(chunks(chain.read(A.GROUP)))[b'MOGP']
        finally:chain.close()
        lo,hi=struct.unpack_from('<3f',body,12),struct.unpack_from('<3f',body,24)
        for x in (lo[0],hi[0]):
            for y in (lo[1],hi[1]):self.assertLess(math.hypot(-x-G.START[0],-y-G.START[1])+15,G.ARENA_RADIUS)
        for gate in A.WORLD_GATES:
            for x,y in (gate.start,gate.end):self.assertLess(math.dist((x,y),G.START[:2])+20,G.ARENA_RADIUS)
        self.assertEqual(tuple(p[:2] for p in G.elite_spawns()),((-81.,411.),(1.,475.),(-99.,453.)))
        heights,targets=G.load()
        for i,target in enumerate(targets):
            if target==divmod(i,G.H):
                x,y=G.X0+(i//G.H+.5)*G.CELL,G.Y0+(i%G.H+.5)*G.CELL
                self.assertTrue(A.in_play_area(x,y,6))

if __name__=='__main__':unittest.main()
