"""Checked open-savannah placements south of the Crossroads in The Barrens."""
import math
from stonetalon_zone import terrain_sample

FLOOR_START=(-800.,-2600.,93.153)
SPAWN_CLEARANCE=1.
START=(*FLOOR_START[:2],FLOOR_START[2]+SPAWN_CLEARANCE)
RADIUS=150.
CAMP_XY=((-880.,-2660.),(-720.,-2670.),(-800.,-2490.))
CAMPS=((-880.,-2660.,91.7291),(-720.,-2670.,94.5189),(-800.,-2490.,92.2826))


def audit(data_dir):
    from durotar_assets import Chain
    chain=Chain(data_dir)
    try:
        result=[]
        for x,y in (START[:2],*CAMP_XY):
            z,area,wet=terrain_sample(chain,x,y)
            if area not in (17,458) or wet:raise ValueError(f'Not dry Barrens savannah: {(x,y,area,wet)}')
            for dx,dy in ((-4,0),(4,0),(0,-4),(0,4)):
                h,_,w=terrain_sample(chain,x+dx,y+dy)
                if w or abs(h-z)>2:raise ValueError(f'Unsafe placement: {(x,y)}')
            result.append((x,y,round(z,4)))
        for radius in (RADIUS/2,RADIUS):
            for i in range(32):
                a=i*math.tau/32;x,y=START[0]+radius*math.cos(a),START[1]+radius*math.sin(a)
                z,area,wet=terrain_sample(chain,x,y)
                if wet or area not in (17,458):raise ValueError(f'Arena leaves the savannah: {(x,y,area,wet)}')
        return tuple(result)
    finally:chain.close()


if __name__=='__main__':
    import sys
    print(audit(sys.argv[1]))
