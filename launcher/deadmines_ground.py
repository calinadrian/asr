"""Ground map of the mine caves and Ironclad Cove for The Deadmines chapter.

The game has no height data for DeadminesInstance: its height lookup fails
everywhere in the cove, so creatures keep whatever height they had and float
or sink as they move. This builds a 2-yard grid of the caves and cove's walkable ground
from the vanilla client's ADT terrain, liquid and the AZ_Deadmines_B WMO, which
story_chapters answers those lookups from and places enemy spawns with.

Each cell holds the lowest dry floor reachable from the Mast Room start
through continuous steps, or nothing. Logs, roofs and disconnected geometry
do not become ground just because they have open space overhead. Spawnable
cells are dry, open and level with their neighbours; every cell also names
the nearest spawnable cell, so a spawn over water or rock moves onto ground.

Run as a script to rebuild assets/deadmines_ground.bin from the client data.
"""
import heapq, math, struct, sys, zlib
from pathlib import Path
import deadmines_arena as arena

ASSET = Path(__file__).with_name('assets')/'deadmines_ground.bin'
X0, Y0, CELL, W, H = -340.0, -1020.0, 2.0, 200, 370   # x -340..60, y -1020..-280
MID, TILE = 17066.666, 1600/3
MAP = 'DeadminesInstance'
WMO = ('World\\wmo\\Dungeon\\AZ_Deadmines\\AZ_Deadmines_B.wmo', (17718.26171875, 29.84957504272461, 17223.072265625), (0.0, -91.0, 0.0))
NONE = 0xffff
START = (-291.0, -515.0, 49.58)
MAX_STEP = 3.0
ARENA_RADIUS = arena.RADIUS
SPAWN_CLEARANCE = 4.0
SPAWN_HEIGHT = 6.0


def load(path=ASSET):
    """(heights, targets): W*H f32 heights (NaN where nothing) and (tx, ty) u16 nearest spawnable cells."""
    raw = zlib.decompress(path.read_bytes())
    heights = struct.unpack_from(f'<{W*H}f', raw, 0)
    targets = struct.unpack_from(f'<{W*H*2}H', raw, W*H*4)
    return heights, list(zip(targets[::2], targets[1::2]))


def pack(heights, targets):
    return zlib.compress(struct.pack(f'<{W*H}f', *heights) + struct.pack(f'<{W*H*2}H', *(v for t in targets for v in t)), 9)


def clipped_height(poly, z, above):
    """Clip a triangle/polygon against a horizontal plane."""
    out = []
    for a, b in zip(poly, poly[1:]+poly[:1]):
        ina, inb = (a[2] >= z, b[2] >= z) if above else (a[2] <= z, b[2] <= z)
        if ina:
            out.append(a)
        if ina != inb:
            t = (z-a[2])/(b[2]-a[2])
            out.append(tuple(a[k]+t*(b[k]-a[k]) for k in range(3)))
    return out


def footprint_distance(x, y, poly):
    """Horizontal distance to a convex clipped triangle, including its interior."""
    signs, best = [], math.inf
    for a, b in zip(poly, poly[1:]+poly[:1]):
        dx, dy = b[0]-a[0], b[1]-a[1]
        signs.append(dx*(y-a[1])-dy*(x-a[0]))
        t = max(0.0, min(1.0, ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy or 1)))
        best = min(best, math.hypot(x-a[0]-t*dx, y-a[1]-t*dy))
    # Degenerate vertical faces have no area; their edge distance still counts.
    if signs and (all(v > 1e-6 for v in signs) or all(v < -1e-6 for v in signs)):
        return 0.0
    return best


def blocked_spawns(heights, obstacles):
    """Reject a 4-yard-wide margin around walls/logs through elite body height."""
    blocked = set()
    for triangle in obstacles:
        lo = (max(0, int((min(v[0] for v in triangle)-SPAWN_CLEARANCE-X0)//CELL)),
              max(0, int((min(v[1] for v in triangle)-SPAWN_CLEARANCE-Y0)//CELL)))
        hi = (min(W-1, int((max(v[0] for v in triangle)+SPAWN_CLEARANCE-X0)//CELL)),
              min(H-1, int((max(v[1] for v in triangle)+SPAWN_CLEARANCE-Y0)//CELL)))
        for gx in range(lo[0], hi[0]+1):
            for gy in range(lo[1], hi[1]+1):
                i = gx*H+gy
                z = heights[i]
                x, y = X0+(gx+0.5)*CELL, Y0+(gy+0.5)*CELL
                if i in blocked or not math.isfinite(z) or math.hypot(x-START[0], y-START[1]) > ARENA_RADIUS:
                    continue
                poly = clipped_height(list(triangle), z+0.5, True)
                poly = clipped_height(poly, z+SPAWN_HEIGHT, False) if poly else []
                if poly and footprint_distance(x, y, poly) <= SPAWN_CLEARANCE:
                    blocked.add(i)
    return blocked


def connected_floors(candidates, start=START):
    """Follow continuous floors from the hero, never snap onto a separate roof.

    A cell is settled by the cheapest walk from the start. Height changes cost
    extra, so a bridge/log above the floor cannot win just for having open sky.
    Unreachable geometry remains absent instead of becoming another ground layer.
    """
    gx, gy = int((start[0]-X0)//CELL), int((start[1]-Y0)//CELL)
    seed = gx*H+gy
    if seed not in candidates:
        raise ValueError('Deadmines start has no walkable floor')
    z, head = min(candidates[seed], key=lambda pair: abs(pair[0]-start[2]))
    queue = [(0.0, seed, z, head)]
    heights, room = [math.nan]*(W*H), [0.0]*(W*H)
    while queue:
        cost, i, z, head = heapq.heappop(queue)
        if not math.isnan(heights[i]):
            continue
        heights[i], room[i] = z, head
        gx, gy = divmod(i, H)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            x, y = gx+dx, gy+dy
            if not (0 <= x < W and 0 <= y < H):
                continue
            n = x*H+y
            if not math.isnan(heights[n]):
                continue
            for nz, nh in candidates.get(n, ()):
                delta = abs(nz-z)
                if delta <= MAX_STEP:
                    heapq.heappush(queue, (cost+CELL+delta*4, n, nz, nh))
    return heights, room


def lookup_heights(heights, targets):
    """Holes use nearby safe ground, never the native ADT above the dungeon."""
    result = []
    for i, z in enumerate(heights):
        tx, ty = targets[i]
        if tx == NONE or ty == NONE:
            raise ValueError('Deadmines ground has no safe spawn target')
        result.append(heights[tx*H+ty] if math.isnan(z) else z)
    if not all(math.isfinite(z) for z in result):
        raise ValueError('Invalid Deadmines lookup heights')
    return result


def elite_spawns():
    """One checked, separated anchor for each of the chapter's three elite types."""
    heights, targets = load()
    safe = [i for i in range(W*H) if targets[i] == divmod(i,H)]
    chosen = []
    for lx,ly in ((158,150),(84,133),(168,94)):
        wx,wy,_ = arena.world(lx,ly)
        options = []
        for i in safe:
            x,y = X0+(i//H+.5)*CELL,Y0+(i%H+.5)*CELL
            if math.hypot(x-START[0],y-START[1]) >= 24 and all(math.hypot(x-a,y-b)>=45 for a,b,_ in chosen):
                options.append(((x-wx)**2+(y-wy)**2,i,x,y))
        if not options:
            raise ValueError('Not enough separated elite spawn positions')
        _,i,x,y = min(options)
        chosen.append((x,y,heights[i]))
    return tuple(chosen)


def build(data_dir):
    from durotar_assets import Chain, chunks
    chain = Chain(data_dir)
    up, every, obstacles = {}, {}, []

    def key(x, y):
        return int((x-X0)//CELL), int((y-Y0)//CELL)

    def add(table, k, z):
        if 0 <= k[0] < W and 0 <= k[1] < H:
            table.setdefault(k, []).append(z)

    # WMO surfaces: up-facing ones are floors; all of them bound the space above.
    root, pos, rot = WMO
    yaw = math.radians(rot[1]+180)
    ox, oy, oz = MID-pos[2], MID-pos[0], pos[1]
    c, s = math.cos(yaw), math.sin(yaw)
    count = struct.unpack_from('<I', dict(chunks(chain.read(root)))[b'MOHD'], 4)[0]
    for i in range(count):
        body = dict(chunks(chain.read(root[:-4]+f'_{i:03}.wmo')))[b'MOGP'][0x44:]
        sub = dict(chunks(body))
        v = struct.unpack(f'<{len(sub[b"MOVT"])//4}f', sub[b'MOVT'])
        idx = struct.unpack(f'<{len(sub[b"MOVI"])//2}H', sub[b'MOVI'])
        pts = [(ox+v[j]*c-v[j+1]*s, oy+v[j]*s+v[j+1]*c, oz+v[j+2]) for j in range(0, len(v), 3)]
        for t in range(len(idx)//3):
            a, b, d = pts[idx[t*3]], pts[idx[t*3+1]], pts[idx[t*3+2]]
            ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
            wx, wy, wz = d[0]-a[0], d[1]-a[1], d[2]-a[2]
            nx, ny, nz = uy*wz-uz*wy, uz*wx-ux*wz, ux*wy-uy*wx
            floor = nz/(math.sqrt(nx*nx+ny*ny+nz*nz) or 1) > 0.7
            if not floor:
                obstacles.append((a, b, d))
            # Rasterize at the exact cell centre. Sampling triangle edges into
            # cells mixed cave ceilings/walls with floors and left holes.
            if abs(nz) < 1e-8:
                continue
            lo = key(min(a[0], b[0], d[0]), min(a[1], b[1], d[1]))
            hi = key(max(a[0], b[0], d[0]), max(a[1], b[1], d[1]))
            for gx in range(max(0, lo[0]), min(W-1, hi[0])+1):
                for gy in range(max(0, lo[1]), min(H-1, hi[1])+1):
                    x, y = X0+(gx+0.5)*CELL, Y0+(gy+0.5)*CELL
                    p = ((x-a[0])*wy-(y-a[1])*wx)/nz
                    q = (ux*(y-a[1])-uy*(x-a[0]))/nz
                    if p < -1e-6 or q < -1e-6 or p+q > 1.000001:
                        continue
                    z = a[2]+p*uz+q*wz
                    add(every, (gx, gy), z)
                    if floor:
                        add(up, (gx, gy), z)

    # ADT terrain (nearest vertex) and liquid (each chunk's MCLQ base height).
    terrain, water = {}, {}
    tiles = {}
    for gx in range(W):
        for gy in range(H):
            x, y = X0+(gx+0.5)*CELL, Y0+(gy+0.5)*CELL
            tx, ty = int(32-y/TILE), int(32-x/TILE)
            if (tx, ty) not in tiles:
                adt = chain.read(f'World\\Maps\\{MAP}\\{MAP}_{tx}_{ty}.adt')
                found, at = [], 0
                while adt and at < len(adt):
                    tag, size = struct.unpack_from('<4sI', adt, at)
                    if tag[::-1] == b'MCNK':
                        px, py, pz = struct.unpack_from('<3f', adt, at+8+0x68)
                        mcvt = struct.unpack_from('<I', adt, at+8+0x14)[0]
                        mclq, lsize = struct.unpack_from('<II', adt, at+8+0x60)
                        hs = struct.unpack_from('<145f', adt, at+mcvt+8)
                        lq = struct.unpack_from('<f', adt, at+mclq+8)[0] if lsize > 8 else None
                        found.append((px, py, pz, hs, lq))
                    at += 8+size
                tiles[tx, ty] = found
            for px, py, pz, hs, lq in tiles[tx, ty]:
                if px-TILE/16 <= x <= px and py-TILE/16 <= y <= py:
                    r, q = round((px-x)/(TILE/128)), round((py-y)/(TILE/128))
                    terrain[gx, gy] = pz+hs[r*17+q]
                    if lq is not None:
                        water[gx, gy] = lq
                    break

    # Keep all floor layers until traversal chooses one. Picking the surface
    # with most headroom chose log tops and roofs over the cave floor.
    candidates = {}
    for gx in range(W):
        for gy in range(H):
            k = (gx, gy)
            cands = list(up.get(k, []))
            if k in terrain and terrain[k] < 100.0 and -260 <= X0+(gx+0.5)*CELL < 60 and Y0+(gy+0.5)*CELL < -600:
                cands.append(terrain[k])
            lq = water.get(k)
            for z in sorted(set(round(z, 2) for z in cands)):
                if lq is not None and z < lq+0.3:
                    continue
                above = [a for a in every.get(k, []) if a > z+2.0]
                head = min(above)-z if above else 999.0
                if head >= 3.0:
                    candidates.setdefault(gx*H+gy, []).append((z, head))
    # An overhead log/bridge is not another floor to climb onto. Prefer the
    # lowest dry surface with standing room, then keep its connected layer.
    candidates = {i: [min(layers)] for i, layers in candidates.items()}
    heights, room = connected_floors(candidates)
    blocked = blocked_spawns(heights, obstacles+list(arena.obstacle_triangles()))
    spawnable = [False]*(W*H)
    for gx in range(1, W-1):
        for gy in range(1, H-1):
            i = gx*H+gy
            z = heights[i]
            x, y = X0+(gx+0.5)*CELL, Y0+(gy+0.5)*CELL
            if not arena.inside(x, y, SPAWN_CLEARANCE):
                continue
            if math.isnan(z) or room[i] < 8.0 or i in blocked:
                continue
            ring = [heights[(gx+dx)*H+gy+dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
            spawnable[i] = all(not math.isnan(h) and abs(h-z) <= 1.0 for h in ring) and \
                all(room[(gx+dx)*H+gy+dy] >= 3.0 for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    # nearest spawnable cell for every cell: breadth-first from all spawnable cells
    targets = [(NONE, NONE)]*(W*H)
    frontier = [i for i in range(W*H) if spawnable[i]]
    if not frontier:
        raise ValueError('Deadmines arena has no clear spawn locations')
    for i in frontier:
        targets[i] = (i//H, i % H)
    while frontier:
        nxt = []
        for i in frontier:
            gx, gy = divmod(i, H)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (gx+dx, gy+dy)
                if 0 <= n[0] < W and 0 <= n[1] < H and targets[n[0]*H+n[1]][0] == NONE:
                    targets[n[0]*H+n[1]] = targets[i]
                    nxt.append(n[0]*H+n[1])
        frontier = nxt
    return heights, targets


if __name__ == '__main__':
    data = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parents[1]/'downloads/durotar-assets/vanilla-1.12.1/app/Data')
    heights, targets = build(data)
    ASSET.parent.mkdir(exist_ok=True)
    ASSET.write_bytes(pack(heights, targets))
    spawn = sum(1 for i, t in enumerate(targets) if t == divmod(i, H))
    print(ASSET, ASSET.stat().st_size, 'bytes;', sum(not math.isnan(h) for h in heights), 'ground cells,', spawn, 'spawnable')
