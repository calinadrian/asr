"""Checked WMO floor grid for Wailing Caverns' Pit of Fangs arena.

The WDT places its global WMO at the origin with zero rotation: the native
placement transform maps local (x,y,z) to (-x,-y,z). No ADT terrain exists.
Rebuild with: python launcher/wailing_ground.py <vanilla Data directory>.
"""
import math
import struct
import sys
import zlib
from collections import deque
from pathlib import Path
from deadmines_ground import clipped_height, footprint_distance
import wailing_arena as arena

ASSET = Path(__file__).with_name('assets')/'wailing_ground.bin'
ROOT = r'world\wmo\dungeon\kl_wailing\wailingcaverns_instance.wmo'
GROUP = 2  # Pit of Fangs: a dry, enclosed chamber, including its rock outcrops.
X0, Y0, CELL, W, H = -180., 340., 2., 130, 120
START = (-31., 451., -101.85)
ARENA_RADIUS = arena.RADIUS
NONE = 0xffff


def inside(x, y, margin=0):
    return arena.in_play_area(x,y,margin) and math.hypot(x-START[0], y-START[1]) <= ARENA_RADIUS-margin


def load(path=ASSET):
    raw = zlib.decompress(path.read_bytes())
    heights = struct.unpack_from(f'<{W*H}f', raw)
    cells = struct.unpack_from(f'<{W*H*2}H', raw, W*H*4)
    return heights, list(zip(cells[::2], cells[1::2]))


def pack(heights, targets):
    return zlib.compress(struct.pack(f'<{W*H}f', *heights)+struct.pack(f'<{W*H*2}H', *(v for t in targets for v in t)), 9)


def lookup_heights(heights, targets):
    result = [heights[tx*H+ty] if not math.isfinite(z) else z for z,(tx,ty) in zip(heights, targets)]
    if not all(math.isfinite(z) for z in result):
        raise ValueError('Wailing Caverns has invalid fallback ground')
    return result


def elite_spawns():
    heights, targets = load()
    # Fixed designer-selected anchors; never scatter camps by a distance score.
    anchors = ((-81.,411.),(1.,475.),(-99.,453.))
    chosen=[]
    for x,y in anchors:
        gx,gy=int((x-X0)//CELL),int((y-Y0)//CELL);i=gx*H+gy
        if targets[i] != (gx,gy):
            raise ValueError(f'Manual Wailing camp is not on clear floor: {(x,y)}')
        chosen.append((x,y,heights[i]))
    return tuple(chosen)



def build(data_dir):
    from durotar_assets import Chain,chunks
    chain = Chain(data_dir)
    try:
        group = dict(chunks(chain.read(ROOT[:-4]+f'_{GROUP:03}.wmo')))[b'MOGP']
    finally:
        chain.close()
    sub = dict(chunks(group[68:]))
    if b'MLIQ' in sub:
        raise ValueError('The selected Wailing arena must be dry')
    verts = [(-x,-y,z) for x,y,z in struct.iter_unpack('<3f',sub[b'MOVT'])]
    indices = struct.unpack(f'<{len(sub[b"MOVI"])//2}H',sub[b'MOVI'])
    floors, surfaces, obstacles = {}, {}, []
    for k in range(0,len(indices),3):
        a,b,c = [verts[i] for i in indices[k:k+3]]
        u,v = [b[j]-a[j] for j in range(3)],[c[j]-a[j] for j in range(3)]
        nx,ny,nz = u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]
        floor = nz/(math.sqrt(nx*nx+ny*ny+nz*nz) or 1) > .7
        if not floor: obstacles.append((a,b,c))
        if abs(nz)<1e-8: continue
        for gx in range(max(0,int((min(a[0],b[0],c[0])-X0)//CELL)),min(W-1,int((max(a[0],b[0],c[0])-X0)//CELL))+1):
            for gy in range(max(0,int((min(a[1],b[1],c[1])-Y0)//CELL)),min(H-1,int((max(a[1],b[1],c[1])-Y0)//CELL))+1):
                x,y = X0+(gx+.5)*CELL,Y0+(gy+.5)*CELL
                p=((x-a[0])*v[1]-(y-a[1])*v[0])/nz
                q=(u[0]*(y-a[1])-u[1]*(x-a[0]))/nz
                if min(p,q)<-1e-6 or p+q>1.000001: continue
                z=a[2]+p*u[2]+q*v[2];i=gx*H+gy
                surfaces.setdefault(i,[]).append(z)
                if floor: floors.setdefault(i,[]).append(z)
    candidates={}
    for i,layers in floors.items():
        for z in sorted(set(round(z,2) for z in layers)):
            head=min([v-z for v in surfaces[i] if v>z+2]+[999.])
            if head>=3:
                candidates[i]=(z,head);break
    seed=int((START[0]-X0)//CELL)*H+int((START[1]-Y0)//CELL)
    if seed not in candidates: raise ValueError('Wailing start has no ground')
    heights,room=[math.nan]*(W*H),[0.]*(W*H)
    queue=deque([seed]); heights[seed],room[seed]=candidates[seed]
    while queue:
        i=queue.popleft();gx,gy=divmod(i,H)
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            x,y=gx+dx,gy+dy;n=x*H+y
            if 0<=x<W and 0<=y<H and n in candidates and not math.isfinite(heights[n]):
                z,head=candidates[n]
                if abs(z-heights[i])<=3:
                    heights[n],room[n]=z,head;queue.append(n)
    obstacles.extend(arena.obstacle_triangles())
    safe=[]
    for i,z in enumerate(heights):
        gx,gy=divmod(i,H);x,y=X0+(gx+.5)*CELL,Y0+(gy+.5)*CELL
        if not math.isfinite(z) or not (0<gx<W-1 and 0<gy<H-1) or not inside(x,y,6) or room[i]<8:continue
        if any(not math.isfinite(heights[(gx+dx)*H+gy+dy]) or abs(heights[(gx+dx)*H+gy+dy]-z)>1 for dx in (-1,0,1) for dy in (-1,0,1)):continue
        blocked=False
        for tri in obstacles:
            if x<min(v[0] for v in tri)-4 or x>max(v[0] for v in tri)+4 or y<min(v[1] for v in tri)-4 or y>max(v[1] for v in tri)+4:continue
            poly=clipped_height(list(tri),z+.5,True)
            poly=clipped_height(poly,z+6,False) if poly else []
            if poly and footprint_distance(x,y,poly)<=4:blocked=True;break
        if not blocked:safe.append(i)
    if not safe:raise ValueError('Wailing Caverns has no safe spawn cells')
    targets=[(NONE,NONE)]*(W*H);queue=deque(safe)
    for i in safe:targets[i]=divmod(i,H)
    while queue:
        i=queue.popleft();gx,gy=divmod(i,H)
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            x,y=gx+dx,gy+dy;n=x*H+y
            if 0<=x<W and 0<=y<H and targets[n][0]==NONE:targets[n]=targets[i];queue.append(n)
    return heights,targets


if __name__=='__main__':
    heights,targets=build(sys.argv[1]);ASSET.parent.mkdir(exist_ok=True);ASSET.write_bytes(pack(heights,targets))
    print('Ground:',sum(math.isfinite(z) for z in heights),'safe:',sum(t==divmod(i,H) for i,t in enumerate(targets)),'camps:',elite_spawns())
