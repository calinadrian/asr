"""Stonetalon chapter placements on the dry Windshear Crag clearing.

Native Kalimdor terrain supplies player and creature heights. This reader
checks manual starts/camps against vanilla ADT triangles and liquid data;
it does not replace the engine's outdoor movement or ground lookup.
"""
import struct

FLOOR_START = (1380., -350., 7.7909)
SPAWN_CLEARANCE = 1.0
START = (*FLOOR_START[:2], FLOOR_START[2]+SPAWN_CLEARANCE)
RADIUS = 110.
CAMP_XY = ((1290.,-370.),(1400.,-420.),(1430.,-290.))
CAMPS = ((1290.,-370.,12.5557),(1400.,-420.,20.7806),(1430.,-290.,8.0886))


def terrain_sample(chain,x,y,map_folder='Kalimdor'):
    from durotar_assets import chunks
    tile=1600/3
    tx,ty=int(32-y/tile),int(32-x/tile)
    data=chain.read(f'World\\Maps\\{map_folder}\\{map_folder}_{tx}_{ty}.adt')
    if data is None:raise ValueError('Stonetalon terrain tile missing')
    for tag,b in chunks(data):
        if tag!=b'MCNK':continue
        px,py,pz=struct.unpack_from('<3f',b,104)
        if not (px-tile/16<=x<=px and py-tile/16<=y<=py):continue
        offset=struct.unpack_from('<I',b,20)[0]
        heights=struct.unpack_from('<145f',b,offset)
        fx,fy=(px-x)/(tile/128),(py-y)/(tile/128)
        r,q=min(7,int(fx)),min(7,int(fy));u,v=fx-r,fy-q
        a,bh,c,d=(heights[r*17+q],heights[(r+1)*17+q],heights[(r+1)*17+q+1],heights[r*17+q+1])
        mid=heights[r*17+9+q]
        triangles=(((0.,0.,a),(1.,0.,bh),(.5,.5,mid)),((1.,0.,bh),(1.,1.,c),(.5,.5,mid)),((1.,1.,c),(0.,1.,d),(.5,.5,mid)),((0.,1.,d),(0.,0.,a),(.5,.5,mid)))
        z=None
        for a,bh,c in triangles:
            det=(bh[0]-a[0])*(c[1]-a[1])-(bh[1]-a[1])*(c[0]-a[0])
            p=((u-a[0])*(c[1]-a[1])-(v-a[1])*(c[0]-a[0]))/det
            qv=((bh[0]-a[0])*(v-a[1])-(bh[1]-a[1])*(u-a[0]))/det
            if min(p,qv)>=-1e-6 and p+qv<=1.000001:z=pz+a[2]+p*(bh[2]-a[2])+qv*(c[2]-a[2]);break
        if z is None:raise ValueError('Terrain interpolation failed')
        liquid,length=struct.unpack_from('<II',b,96)
        wet=False
        if length>8:
            # MCLQ includes an 8-byte min/max, 81 vertices, then 64 tile flags.
            flags=b[liquid+8+81*8:liquid+8+81*8+64]
            if len(flags)==64:wet=(flags[r*8+q]&15)!=15
        return z,struct.unpack_from('<I',b,52)[0],wet
    raise ValueError('Stonetalon point outside terrain chunks')


def audit(data_dir):
    from durotar_assets import Chain
    chain=Chain(data_dir)
    try:
        result=[]
        for x,y in (START[:2],*CAMP_XY):
            z,area,wet=terrain_sample(chain,x,y)
            if area!=461 or wet:raise ValueError(f'Placement outside dry Windshear Crag: {(x,y,area,wet)}')
            neighbours=[terrain_sample(chain,x+dx,y+dy)[0] for dx,dy in ((-4,0),(4,0),(0,-4),(0,4))]
            if max(abs(v-z) for v in neighbours)>2:raise ValueError(f'Placement too steep: {(x,y)}')
            result.append((x,y,round(z,4)))
        return tuple(result)
    finally:chain.close()


if __name__=='__main__':
    import sys
    print(audit(sys.argv[1]))
