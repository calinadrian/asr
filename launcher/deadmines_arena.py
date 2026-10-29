"""Mast Room arena outline and timber barricades across its two WMO portals."""
import math
import struct
from pathlib import Path

ROOT = 'World\\wmo\\Dungeon\\AZ_Deadmines\\AZ_Deadmines_B.wmo'
GROUP = ROOT[:-4]+'_041.wmo'
# Same transform as the vanilla Deadmines B WMO placement.
OX, OY, OZ = 17066.666-17223.072265625, 17066.666-17718.26171875, 29.84957504272461
C, S = math.cos(math.radians(89)), math.sin(math.radians(89))
# Mast Room plus the connected western cave. Its far choke point owns the
# western gate; the Mast Room arch itself remains open.
LOCAL_OUTLINE = ((176.,110.91),(176.,164.),(110.49,164.),(110.49,151.),
                 (73.2,149.9),(64.7,138.2),(63.3,121.),(110.49,121.),
                 (110.49,110.91),(158.,110.91),(158.,102.),(153.,98.),
                 (156.,94.),(156.,80.),(152.04,73.09),(160.38,60.19),
                 (169.,68.),(175.,77.),(179.,90.),(181.,98.),(177.,105.))
RADIUS = 110.0
from typing import NamedTuple

class Gate(NamedTuple):
    start: tuple
    end: tuple
    bottom: float
    top: float

# Both visible frames fit below the passage ceiling and inside the jambs.
GATES = (Gate((64.7,138.2),(73.2,149.9),17.1,25.85),
         Gate((152.04,73.09),(160.38,60.19),17.8,25.5))

GATE_GROUPS = (20,7)


def world(x, y, z=0):
    return OX+x*C-y*S, OY+x*S+y*C, OZ+z


def local(x, y):
    dx, dy = x-OX, y-OY
    return dx*C+dy*S, -dx*S+dy*C


def inside(x, y, margin=0):
    x, y = local(x, y)
    odd, nearest = False, math.inf
    for a,b in zip(LOCAL_OUTLINE,LOCAL_OUTLINE[1:]+LOCAL_OUTLINE[:1]):
        dx,dy=b[0]-a[0],b[1]-a[1]
        t=max(0.,min(1.,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        nearest=min(nearest,math.hypot(x-a[0]-t*dx,y-a[1]-t*dy))
        if (a[1]>y)!=(b[1]>y) and x < a[0]+(y-a[1])*dx/dy:
            odd=not odd
    return odd and nearest >= margin


def outline():
    return tuple(struct.unpack('<2f',struct.pack('<2f',*world(x,y)[:2])) for x,y in LOCAL_OUTLINE)


def gate_quads():
    for gate in GATES:
        a,b=gate.start,gate.end
        yield [(a[0],a[1],gate.bottom-.2),(b[0],b[1],gate.bottom-.2),
               (b[0],b[1],gate.top+.2),(a[0],a[1],gate.top+.2)]


def obstacle_triangles():
    for quad in gate_quads():
        dx,dy=quad[1][0]-quad[0][0],quad[1][1]-quad[0][1]
        length=math.hypot(dx,dy);nx,ny=dy/length,-dx/length
        for offset in (-.45,.45):
            p=[world(v[0]+nx*offset,v[1]+ny*offset,v[2]) for v in quad]
            yield p[0],p[1],p[2]
            yield p[0],p[2],p[3]


def chunk(tag, data):
    return tag[::-1]+struct.pack('<I',len(data))+data


def patch_group(source, material=7, gates=GATES, collision_bottom=None, collision_top=None):
    from durotar_assets import chunks
    outer = list(chunks(source))
    original = next(value for tag,value in outer if tag==b'MOGP')
    header = bytearray(original[:68])
    sub = dict(chunks(original[68:]))
    verts = list(struct.iter_unpack('<3f',sub[b'MOVT']))
    normals = list(struct.iter_unpack('<3f',sub[b'MONR']))
    uvs = list(struct.iter_unpack('<2f',sub[b'MOTV']))
    colors = bytearray(sub[b'MOCV'])
    indices = list(struct.unpack(f'<{len(sub[b"MOVI"])//2}H',sub[b'MOVI']))
    flags = bytearray(sub[b'MOPY'])
    render_start, vertex_start = len(indices), len(verts)

    def face(points, solid=False):
        a,b,c,d = points
        u = [b[k]-a[k] for k in range(3)];v = [c[k]-a[k] for k in range(3)]
        n = (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        length = math.sqrt(sum(q*q for q in n))
        n = tuple(q/length for q in n)
        start = len(verts); verts.extend(points); normals.extend([n]*4)
        # Sample the plain timber strip of the mine beam atlas.
        uvs.extend(((.72,.05),(.97,.05),(.97,.95),(.72,.95)))
        colors.extend(bytes((80,85,95,0))*4)
        indices.extend(start+k for k in (0,1,2,0,2,3))
        # NOCAMCOLLIDE permits a close camera without weakening player collision.
        flags.extend(bytes((0x22 if solid else 0x26,material))*2)

    for gate in gates:
        ax,ay=gate.start;bx,by=gate.end
        width=math.hypot(bx-ax,by-ay);tx,ty=(bx-ax)/width,(by-ay)/width
        nx,ny=ty,-tx
        def timber(u0,u1,z0,z1,depth):
            def pt(u,d,z):return ax+tx*u+nx*d,ay+ty*u+ny*d,z
            p=[pt(u0,-depth,z0),pt(u1,-depth,z0),pt(u1,depth,z0),pt(u0,depth,z0),
               pt(u0,-depth,z1),pt(u1,-depth,z1),pt(u1,depth,z1),pt(u0,depth,z1)]
            for f in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
                face([p[k] for k in f])
        step=(gate.top-gate.bottom)/6
        for level in range(6):
            z0=gate.bottom+level*step
            timber(.12,width-.12,z0,z0+step*.84,.23)
        timber(.12,.45,gate.bottom,gate.top,.38)
        timber(width-.45,width-.12,gate.bottom,gate.top,.38)
    render_count = len(indices)-render_start
    max_render_vertex = len(verts)-1
    # Decorative planks are DETAIL (no walk collision), so they cannot form
    # climbable steps. One seamless volume extends below floor/above ceiling.
    for gate in gates:
        ax,ay=gate.start;bx,by=gate.end
        width=math.hypot(bx-ax,by-ay);nx,ny=(by-ay)/width,-(bx-ax)/width
        def p(x,y,d,z):return x+nx*d,y+ny*d,z
        low = gate.bottom-3 if collision_bottom is None else collision_bottom
        high = gate.top+6 if collision_top is None else collision_top
        points=[p(ax,ay,-.45,low),p(bx,by,-.45,low),p(bx,by,.45,low),p(ax,ay,.45,low),
                p(ax,ay,-.45,high),p(bx,by,-.45,high),p(bx,by,.45,high),p(ax,ay,.45,high)]
        for f in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)):
            face([points[k] for k in f],True)
            face([points[k] for k in reversed(f)],True)
    assert len(verts)<65536
    sub[b'MOVT'] = b''.join(struct.pack('<3f',*p) for p in verts)
    sub[b'MONR'] = b''.join(struct.pack('<3f',*p) for p in normals)
    sub[b'MOTV'] = b''.join(struct.pack('<2f',*p) for p in uvs)
    sub[b'MOCV'] = bytes(colors)
    sub[b'MOVI'] = struct.pack(f'<{len(indices)}H',*indices)
    sub[b'MOPY'] = bytes(flags)
    # EXT batch: alpha is not the interior self-illumination mask.
    # Retain the original INT batches and append ordinary shaded timber.
    bbox = [math.floor(min(p[k] for p in verts[vertex_start:])) for k in range(3)]
    bbox += [math.ceil(max(p[k] for p in verts[vertex_start:])) for k in range(3)]
    sub[b'MOBA'] += struct.pack('<6hI3H2B',*bbox,render_start,render_count,vertex_start,max_render_vertex,0,material)
    batches = struct.unpack_from('<H',header,44)[0]
    struct.pack_into('<H',header,44,batches+1)
    struct.pack_into('<6f',header,12,
                     *(min(p[k] for p in verts) for k in range(3)),
                     *(max(p[k] for p in verts) for k in range(3)))
    group = bytes(header)+b''.join(chunk(tag,data) for tag,data in sub.items())
    return b''.join(chunk(tag,group if tag==b'MOGP' else data) for tag,data in outer)


def build_entries(data_dir):
    from durotar_assets import Chain
    chain=Chain(data_dir)
    try:
        # Keep the root and its portal/camera graph byte-for-byte original.
        # Each barrier belongs to the actual passage group containing it.
        return {ROOT[:-4]+f'_{group:03}.wmo':patch_group(chain.read(ROOT[:-4]+f'_{group:03}.wmo'),gates=(gate,))
                for group,gate in zip(GATE_GROUPS,GATES)}
    finally:chain.close()


def build_archive(data_dir):
    from photo_archive import build
    return build(build_entries(data_dir))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.write_bytes(build_archive(args.data))
    print('Built',args.out)
