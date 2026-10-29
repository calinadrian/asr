"""Outdoor Stranglethorn chapter placements, away from Gurubashi Arena and Zul'Gurub."""
import math
from stonetalon_zone import terrain_sample as _terrain_sample

FLOOR_START=(-11920.,-180.,17.1614)
SPAWN_CLEARANCE=1.
START=(*FLOOR_START[:2],FLOOR_START[2]+SPAWN_CLEARANCE)
RADIUS=100.
CAMP_XY=((-11970.,-200.),(-11865.,-240.),(-11870.,-160.))
CAMPS=((-11970.,-200.,15.5808),(-11865.,-240.,14.5846),(-11870.,-160.,14.2174))


def terrain_sample(chain,x,y):
    return _terrain_sample(chain,x,y,'Azeroth')


def audit(data_dir):
    from durotar_assets import Chain
    chain=Chain(data_dir)
    try:
        result=[]
        for x,y in (START[:2],*CAMP_XY):
            z,area,wet=terrain_sample(chain,x,y)
            if area!=33 or wet:raise ValueError(f'Not dry Stranglethorn jungle: {(x,y,area,wet)}')
            for dx,dy in ((-4,0),(4,0),(0,-4),(0,4)):
                h,_,w=terrain_sample(chain,x+dx,y+dy)
                if w or abs(h-z)>2:raise ValueError(f'Unsafe placement: {(x,y)}')
            result.append((x,y,round(z,4)))
        for radius in (RADIUS/2,RADIUS):
            for i in range(32):
                a=i*math.tau/32;x,y=START[0]+radius*math.cos(a),START[1]+radius*math.sin(a)
                z,area,wet=terrain_sample(chain,x,y)
                if wet:raise ValueError(f'Arena crosses water: {(x,y)}')
                if area in (19,1741,2177):raise ValueError('Arena/raid terrain is outside this chapter')
        return tuple(result)
    finally:chain.close()


if __name__=='__main__':
    import sys
    print(audit(sys.argv[1]))
