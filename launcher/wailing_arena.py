"""Lower-tunnel timber barricade for the Pit of Fangs, keeping its portals intact."""
from pathlib import Path
from deadmines_arena import Gate, patch_group

ROOT = r'world\wmo\dungeon\kl_wailing\wailingcaverns_instance.wmo'
GROUP = ROOT[:-4]+'_002.wmo'
ARCHIVE = 'patch-U.MPQ'
# World-space manual placement: the low tunnel throat. The upper ramp is open.
# Visible timber spans floor to ceiling; the solid slab extends into the rock.
WORLD_GATES = (
    Gate((-85.,372.),(-57.,372.),-107.,-65.),
)
# WDT global-WMO transform: world (-x,-y,z).
GATES = tuple(Gate(tuple(-v for v in gate.start),tuple(-v for v in gate.end),gate.bottom,gate.top) for gate in WORLD_GATES)
RADIUS = 190.
COLLISION_BOTTOM, COLLISION_TOP = -130., -40.


def in_play_area(x,y,margin=0):
    # Keep ordinary enemies on the arena side of the lower barricade.
    return y >= 372.+margin


def obstacle_triangles():
    for gate in WORLD_GATES:
        ax,ay=gate.start;bx,by=gate.end
        low,high=COLLISION_BOTTOM,COLLISION_TOP
        a,b,c,d=(ax,ay,low),(bx,by,low),(bx,by,high),(ax,ay,high)
        yield a,b,c
        yield a,c,d


def build_entries(data_dir):
    from durotar_assets import Chain
    chain=Chain(data_dir)
    try:
        # Material 38 is the Wailing Caverns' own timber texture. Root,
        # visibility graph and all existing faces remain byte-for-byte intact.
        return {GROUP:patch_group(chain.read(GROUP),material=38,gates=GATES,collision_bottom=COLLISION_BOTTOM,collision_top=COLLISION_TOP)}
    finally:chain.close()


def build_archive(data_dir):
    from photo_archive import build
    return build(build_entries(data_dir))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data',type=Path);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.parent.mkdir(exist_ok=True,parents=True);args.out.write_bytes(build_archive(args.data))
    print('Built',args.out)
