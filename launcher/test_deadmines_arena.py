"""Verify rendered barricades also seal the original passage collision openings."""
import struct
import unittest
from pathlib import Path
import deadmines_arena as arena
from durotar_assets import Chain, chunks

DATA = Path(__file__).parents[1]/'downloads/durotar-assets/vanilla-1.12.1/app/Data'


def intersects(start, end, triangle):
    def sub(a,b):return tuple(x-y for x,y in zip(a,b))
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    a,b,c=triangle;d=sub(end,start);e1,e2=sub(b,a),sub(c,a)
    p=cross(d,e2);det=dot(e1,p)
    if abs(det)<1e-8:return False
    t=sub(start,a);u=dot(t,p)/det
    q=cross(t,e1);v=dot(d,q)/det;along=dot(e2,q)/det
    return -1e-6<=u and -1e-6<=v and u+v<=1.000001 and 0<=along<=1


@unittest.skipUnless(DATA.exists(),'Requires vanilla WMO fixture')
class BarricadeTests(unittest.TestCase):
    def test_original_portal_graph_and_camera_groups_are_untouched(self):
        entries=arena.build_entries(DATA)
        self.assertEqual(set(entries),{arena.ROOT[:-4]+f'_{i:03}.wmo' for i in arena.GATE_GROUPS})
        self.assertNotIn(arena.ROOT,entries)
        chain=Chain(DATA)
        try:
            for path,raw in entries.items():
                old=dict(chunks(chain.read(path)))[b'MOGP']
                new=dict(chunks(raw))[b'MOGP']
                self.assertEqual(old[:12],new[:12])
                self.assertEqual(old[36:40],new[36:40]) # exact original portal refs
                self.assertEqual(old[40:44],new[40:44]) # original TRANS/INT batches
                self.assertEqual(struct.unpack_from('<H',new,44)[0],struct.unpack_from('<H',old,44)[0]+1)
                before=dict(chunks(old[68:]));after=dict(chunks(new[68:]))
                for tag in (b'MOPY',b'MOVI',b'MOVT',b'MONR',b'MOTV',b'MOCV',b'MOBA'):
                    self.assertTrue(after[tag].startswith(before[tag]),(path,tag))
        finally:chain.close()

    def test_barriers_are_sealed_for_jumps_without_climbable_planks(self):
        entries=arena.build_entries(DATA)
        chain=Chain(DATA)
        try:
            for number,gate in zip(arena.GATE_GROUPS,arena.GATES):
                path=arena.ROOT[:-4]+f'_{number:03}.wmo'
                original=dict(chunks(dict(chunks(chain.read(path)))[b'MOGP'][68:]))
                body=dict(chunks(entries[path]))[b'MOGP'];sub=dict(chunks(body[68:]))
                verts=list(struct.iter_unpack('<3f',sub[b'MOVT']))
                indices=struct.unpack(f'<{len(sub[b"MOVI"])//2}H',sub[b'MOVI'])
                first=len(original[b'MOVI'])//6
                render_count=struct.unpack_from('<H',sub[b'MOBA'][-24:],16)[0]//3
                triangles=[]
                for k in range(first,len(indices)//3):
                    flags=sub[b'MOPY'][k*2]
                    self.assertTrue(flags&2)
                    if k < first+render_count:
                        self.assertTrue(flags&4) # boards must not become a staircase
                        continue
                    self.assertFalse(flags&4)
                    points=[verts[i] for i in indices[k*3:k*3+3]]
                    if max(p[2] for p in points)-min(p[2] for p in points)<1e-5:
                        self.assertTrue(points[0][2]<=gate.bottom-2.9 or points[0][2]>=gate.top+5.9)
                    triangles.append(points)
                ax,ay=gate.start;bx,by=gate.end
                length=((bx-ax)**2+(by-ay)**2)**.5
                nx,ny=(by-ay)/length,-(bx-ax)/length
                for along in (.01,.25,.5,.75,.99):
                    x,y=ax+(bx-ax)*along,ay+(by-ay)*along
                    # Across gaps, below the floor and above normal jump height.
                    for z in (gate.bottom-2,gate.bottom+.2,(gate.bottom+gate.top)/2,gate.top+4):
                        a,b=(x-nx*2,y-ny*2,z),(x+nx*2,y+ny*2,z)
                        self.assertTrue(any(intersects(a,b,t) for t in triangles),(number,along,z))
                        self.assertTrue(any(intersects(b,a,t) for t in triangles),(number,along,z))
                self.assertTrue(all(sub[b'MOCV'][k]==0 for k in range(len(original[b'MOCV'])+3,len(sub[b'MOCV']),4)))
                self.assertEqual(len(sub[b'MOCV'])//4,len(verts))
                self.assertEqual(len(sub[b'MONR'])//12,len(verts))
                self.assertEqual(sum(struct.unpack_from('<3H',body,40)),len(sub[b'MOBA'])//24)
        finally:chain.close()


if __name__=='__main__':unittest.main()
