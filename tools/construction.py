"""Round 20: building sites on empty lots in built-up parts of the city.

Each site is a rectangle of bare earth inside a fence of breakable corrugated sheet panels (one collision post per panel,
a gate gap on one side) with one building in some stage of construction: an excavation with spoil banks and a ramp, a
foundation slab, bare columns and floors, brick walls, an almost finished block with windows.  A concrete mixer stands
by the gate and the game (src/works.py) puts workers on the site, plays construction noise and drifts dust over it.

Geometry is baked into the chunk meshes like the other street furniture.
-> (posts, works, parked): breakable collision posts, (x, y, radius, stage, yaw, gate_x, gate_y) per site, parked mixers."""
import math
import random

import numpy as np

from furniture import G
from progress import span
from junk import _prism

DIRT, DIRT_D, DIRT_L = (128, 104, 76), (78, 62, 46), (150, 124, 92)
CONC, CONC_D = (168, 168, 164), (132, 132, 130)
BRICK, BRICK_D = (176, 96, 66), (150, 84, 58)
STEEL, REBAR, WOOD, PLANK = (120, 122, 130), (110, 70, 50), (156, 118, 76), (186, 152, 104)
FENCE = ((60, 110, 150), (60, 110, 150), (200, 200, 205), (70, 130, 90))
YEL, NET = (232, 188, 40), (70, 150, 90)
B = 0.05                                    # the dirt pad top above the terrain
FH = 2.3                                    # fence panel height
SIZES = ((46, 38), (36, 30), (28, 24), (22, 18))      # lot rectangles tried, largest first (m)
FLOOR_H = 3.1
LOTS = []                                   # (x0, y0, x1, y1) of every placed lot: build_world drops the trees inside


def _wedge(g, x0, z0, x1, z1, w, y_hi, col):
    """A ramp from (x0, z0) at y_hi down to (x1, z1) at the ground, w wide."""
    dx, dz = x1 - x0, z1 - z0
    ln = math.hypot(dx, dz) or 1.0
    px, pz = -dz / ln * w / 2, dx / ln * w / 2
    a, b = (x0 + px, z0 + pz), (x0 - px, z0 - pz)
    c, d = (x1 - px, z1 - pz), (x1 + px, z1 + pz)
    g.quad((a[0], y_hi, a[1]), (b[0], y_hi, b[1]), (c[0], 0.0, c[1]), (d[0], 0.0, d[1]), col, (dz / ln * 0.5, 0.85, -dx / ln * 0.5))


def fence(g, cx, cz, hw, hd, gate_side, rr):
    """Corrugated panels around the lot.  -> [(x, z)] panel centres (breakable posts); gate_side 0..3 = +x -x +z -z."""
    pts = []
    n_x, n_z = int(2 * hw // 1.6), int(2 * hd // 1.6)
    sx, sz = 2 * hw / n_x, 2 * hd / n_z
    for side in range(4):
        along_x = side >= 2
        n = n_x if along_x else n_z
        step = sx if along_x else sz
        sgn = 1 if side in (0, 2) else -1
        for i in range(n):
            t = -(hw if along_x else hd) + (i + 0.5) * step
            if side == gate_side and abs(t) < 3.2:
                continue
            x, z = (cx + t, cz + sgn * hd) if along_x else (cx + sgn * hw, cz + t)
            col = FENCE[(i + side) % len(FENCE)]
            yaw = 0.0 if along_x else math.pi / 2
            g.box(x, 0.0, z, step * 1.02, FH, 0.07, col, yaw)
            g.box(x, FH - 0.12, z, step * 1.02, 0.12, 0.12, (210, 210, 214), yaw)
            if i % 2 == 0:
                g.box(x, 0.0, z, 0.14, FH + 0.2, 0.2, STEEL, yaw)
            if rr.random() < 0.1:
                g.box(x, 1.0, z + (0.05 if along_x else 0.0), 0.6, 0.5, 0.01, (230, 230, 40), yaw)      # a sticker / sign
            pts.append((x, z))
    # a gate leaf standing open at the gap
    return pts


def columns(g, x0, z0, x1, z1, nx, nz, floors, rr):
    """Concrete columns on a grid with floor slabs; -> ((xs, zs))."""
    xs = [x0 + (x1 - x0) * i / nx for i in range(nx + 1)]
    zs = [z0 + (z1 - z0) * j / nz for j in range(nz + 1)]
    for f in range(floors):
        for x in xs:
            for z in zs:
                g.box(x, B + f * FLOOR_H, z, 0.4, FLOOR_H, 0.4, CONC)
        g.box((x0 + x1) / 2, B + (f + 1) * FLOOR_H - 0.28, (z0 + z1) / 2, x1 - x0 + 0.8, 0.28, z1 - z0 + 0.8, CONC_D)
    for x in xs:                                                      # rebar stubs on the top
        for z in zs:
            for k in range(3):
                g.box(x + (k - 1) * 0.1, B + floors * FLOOR_H, z + (k - 1) * 0.08, 0.025, 1.0 + rr.random() * 0.5, 0.025, REBAR)
    return xs, zs


def brick_walls(g, x0, z0, x1, z1, f0, f1, rr, windows=True, skip_front=0):
    """Brick walls on the four sides, floors f0..f1-1, with window openings (piers, sills and lintels)."""
    for f in range(f0, f1):
        y0 = B + f * FLOOR_H
        for side in range(4):
            if side == skip_front:
                continue
            if side < 2:
                a, b, fixed, axis = z0, z1, (x1 if side == 0 else x0), "z"
            else:
                a, b, fixed, axis = x0, x1, (z1 if side == 2 else z0), "x"
            ln = b - a
            n = max(2, int(ln // 3.0))
            cell = ln / n
            for i in range(n):
                c = a + (i + 0.5) * cell
                px, pz = (fixed, c) if axis == "z" else (c, fixed)
                sx, sz = (0.3, cell) if axis == "z" else (cell, 0.3)
                col = BRICK if (i + f) % 3 else BRICK_D
                if windows and (i + f) % 3 != 2:
                    g.box(px, y0, pz, sx, 0.95, sz, col)                                   # sill
                    g.box(px, y0 + 2.2, pz, sx, FLOOR_H - 2.2 - 0.28, sz, col)             # lintel
                    for s in (-1, 1):                                                     # piers beside the opening
                        ox, oz = (0.0, s * cell * 0.4) if axis == "z" else (s * cell * 0.4, 0.0)
                        g.box(px + ox, y0 + 0.95, pz + oz, *((0.3, 1.25, cell * 0.2) if axis == "z" else (cell * 0.2, 1.25, 0.3)), col)
                else:
                    g.box(px, y0, pz, sx, FLOOR_H - 0.28, sz, col)


def scaffold(g, x0, z0, x1, z1, floors, net):
    """A steel scaffold with plank decks along the front (z1 side)."""
    z = z1 + 1.1
    n = int((x1 - x0) // 2.2)
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        g.box(x, 0.0, z, 0.07, floors * FLOOR_H + 1.2, 0.07, STEEL)
    for f in range(floors + 1):
        y = f * FLOOR_H + 0.9
        g.box((x0 + x1) / 2, y, z, x1 - x0, 0.06, 0.07, STEEL)
        if f:
            g.box((x0 + x1) / 2, y - 0.2, z - 0.4, x1 - x0, 0.06, 1.0, PLANK)
    if net:
        g.box((x0 + x1) / 2, 1.0, z + 0.05, x1 - x0, floors * FLOOR_H - 0.6, 0.02, NET)


def crane(g, x, z, h, yaw):
    """Tower crane: lattice mast, slewing jib with counter-weight, hook line."""
    for s in (-1, 1):
        for t in (-1, 1):
            g.box(x + s * 0.55, 0, z + t * 0.55, 0.1, h, 0.1, YEL)
    for k in range(int(h // 2.5)):
        g.box(x, k * 2.5 + 1.2, z, 1.2, 0.07, 0.07, YEL)
        g.box(x, k * 2.5 + 1.2, z, 0.07, 0.07, 1.2, YEL)
    g.box(x, h, z, 1.3, 1.4, 1.3, (230, 230, 232), yaw)                                 # cab
    ca, sa = math.cos(yaw), math.sin(yaw)
    g.box(x + ca * 9, h + 1.4, z + sa * 9, 24.0, 0.45, 0.45, YEL, yaw)                   # jib
    g.box(x - ca * 4.5, h + 0.9, z - sa * 4.5, 1.6, 1.0, 1.0, (90, 90, 96), yaw)        # counter-weight
    g.box(x + ca * 15, h - 6.0, z + sa * 15, 0.03, 7.4, 0.03, (30, 30, 34))               # hoist line
    g.box(x + ca * 15, h - 6.4, z + sa * 15, 0.5, 0.4, 0.5, (190, 60, 50))                 # hook block


def building(g, bx0, bz0, bx1, bz1, stage, rr):
    """One building in a stage of construction; -> number of floors reached (0 = excavation)."""
    cx, cz = (bx0 + bx1) / 2, (bz0 + bz1) / 2
    hx, hz = (bx1 - bx0) / 2, (bz1 - bz0) / 2
    if stage == 0:                                                    # excavation: dark floor between raised spoil banks, a ramp in
        g.box(cx, 0.0, cz, hx * 2, B + 0.03, hz * 2, DIRT_D)
        t = 3.2
        for s in (-1, 1):
            g.box(cx + s * (hx + t / 2), 0.0, cz, t, 1.5, hz * 2 + 2 * t, DIRT_L)         # spoil banks
            g.box(cx, 0.0, cz + s * (hz + t / 2), hx * 2, 1.5, t, DIRT_L)
        _wedge(g, bx0 - 0.5, cz, bx0 + hx * 0.7, cz, 4.2, 1.5, DIRT)                      # the ramp down from the west bank
        for k in range(5):                                            # puddle-dark patches and a pump hose
            g.box(cx + rr.uniform(-hx, hx) * 0.7, B + 0.03, cz + rr.uniform(-hz, hz) * 0.7, rr.uniform(1.5, 3), 0.01, rr.uniform(1.5, 3), (58, 50, 44), rr.random() * 3)
        for k in range(8):                                            # formwork boards leaning at the edge
            g.box(bx1 - 0.2, 1.5, bz0 + hz * 2 * k / 8 + 0.5, 0.05, 0.7, 1.0, PLANK)
        return 0
    if stage == 1:                                                    # foundation slab, formwork and rebar mat
        g.box(cx, 0.0, cz, hx * 2 + 0.4, B + 0.5, hz * 2 + 0.4, CONC)
        for i in range(8):
            for j in range(6):
                x, z = bx0 + (bx1 - bx0) * (i + 0.5) / 8, bz0 + (bz1 - bz0) * (j + 0.5) / 6
                g.box(x, B + 0.5, z, 0.04, 0.9 + rr.random() * 0.5, 0.04, REBAR)
        for s in (-1, 1):
            g.box(cx + s * (hx + 0.3), B, cz, 0.08, 0.7, hz * 2 + 0.7, PLANK)
        _wedge(g, bx0 - 5.0, cz, bx0 - 0.6, cz, 3.6, 0.0, DIRT)
        return 0
    floors = {2: 1, 3: 2, 4: 3, 5: 4}[stage]
    nx, nz = max(2, int(hx * 2 // 5)), max(2, int(hz * 2 // 5))
    columns(g, bx0, bz0, bx1, bz1, nx, nz, floors, rr)
    g.box(cx, 0.0, cz, hx * 2 + 1.0, B + 0.3, hz * 2 + 1.0, CONC_D)
    if stage >= 4:
        brick_walls(g, bx0, bz0, bx1, bz1, 0, floors - (1 if stage == 4 else 0), rr, windows=stage == 5, skip_front=2)
    if stage == 5:
        g.box(cx, B + floors * FLOOR_H - 0.3, cz, hx * 2 + 1.0, 0.35, hz * 2 + 1.0, (120, 118, 114))      # roof slab
        g.box(cx + hx * 0.4, B + floors * FLOOR_H, cz, 1.4, 1.0, 1.4, BRICK_D)                           # stair head
    if stage >= 3:
        scaffold(g, bx0, bz0, bx1, bz1, floors, net=stage == 5)
    return floors


def yard(g, cx, cz, hw, hd, bx0, bz0, bx1, bz1, gate_side, rr, taken):
    """Site hut, brick / pipe stacks, sand heaps, barrels and a pile of planks on the free part of the lot."""
    def spot(r, tries=40):
        for _ in range(tries):
            x, z = cx + rr.uniform(-hw + 3, hw - 3), cz + rr.uniform(-hd + 3, hd - 3)
            if bx0 - 4 < x < bx1 + 4 and bz0 - 4 < z < bz1 + 4:
                continue
            if all(math.hypot(x - tx, z - tz) > r + tr for tx, tz, tr in taken):
                taken.append((x, z, r))
                return x, z
        return None
    s = spot(3.0)
    if s:                                                             # container office
        g.box(s[0], B, s[1], 5.8, 2.5, 2.4, (200, 120, 40) if rr.random() < 0.5 else (60, 100, 150), 0.0)
        g.box(s[0], B + 2.5, s[1], 6.0, 0.1, 2.6, (230, 230, 230))
        g.box(s[0] + 2.91, B + 1.0, s[1], 0.02, 0.8, 1.0, (130, 190, 230))
    for _ in range(rr.randint(2, 3)):                                 # sand / gravel heaps
        s = spot(2.4)
        if s:
            r = rr.uniform(1.6, 2.4)
            _prism(g, s[0], B, s[1], r, 1.3, 7, (196, 178, 128) if rr.random() < 0.5 else (140, 140, 138))
            _prism(g, s[0], B + 1.3, s[1], r * 0.45, 0.7, 7, (190, 172, 124))
    for _ in range(rr.randint(2, 3)):                                 # stacked bricks / blocks
        s = spot(1.8)
        if s:
            for k in range(3):
                g.box(s[0], B + k * 0.5, s[1], 2.0, 0.5, 1.2, BRICK if k % 2 else BRICK_D)
    for _ in range(rr.randint(1, 2)):                                 # plank pile + barrels
        s = spot(1.6)
        if s:
            for k in range(4):
                g.box(s[0], B + k * 0.12, s[1], 3.0, 0.12, 0.9, PLANK, 0.05 * k)
            _prism(g, s[0] + 2.0, B, s[1], 0.3, 0.9, 8, (60, 90, 170))


def build(density, bright, free_mask, cell, hx, hy, add, chunk_of, th, trees, log=print, max_sites=900, per_km=4):
    """density(x, y): share of built-up ground around a point; free_mask: bool grid of empty ground (True = free);
    cell: its resolution in m.  -> (posts, works, parked)"""
    import vehicles
    mixer = vehicles.IDS.index("Betonjerka")
    ny, nx = free_mask.shape
    ii = np.pad(free_mask.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)     # integral image of free cells

    def all_free(x0, y0, w, h):                                       # whole rectangle (x0,y0 = corner in m) is free ground
        c0, r0 = int((x0 + hx) // cell), int((y0 + hy) // cell)
        c1, r1 = c0 + int(w // cell) + 1, r0 + int(h // cell) + 1
        if c0 < 1 or r0 < 1 or c1 >= nx - 1 or r1 >= ny - 1:
            return False
        s = ii[r1, c1] - ii[r0, c1] - ii[r1, c0] + ii[r0, c0]
        return s == (r1 - r0) * (c1 - c0)

    rr = random.Random(2420)
    tg = {}
    for t in span(trees, 0.3, 0.35, "trees on the lots"):
        tg.setdefault((int(t[0] // 40), int(t[1] // 40)), []).append(t)
    cands = []
    step = 16.0
    ys = np.arange(-hy + 60, hy - 60, step)
    xs = np.arange(-hx + 60, hx - 60, step)
    # coarse prefilter on the free grid: only look at cells that are free
    for y in span(ys, 0.35, 0.45, "empty lots"):
        row = int((y + hy) // cell)
        for x in xs:
            if free_mask[row, int((x + hx) // cell)]:
                cands.append((x, y))
    rr.shuffle(cands)
    placed, posts, works, parked = [], [], [], []
    per_km_n = {}                                                       # sites per 1 km square: every built-up square gets a few
    pg = {}                                                          # placed sites on a 100 m grid (spacing test)
    for x, y in span(cands, 0.45, 0.85, "building sites"):
        if len(works) >= max_sites:
            break
        km = (int((x + hx) // 1000), int((y + hy) // 1000))
        if per_km_n.get(km, 0) >= per_km:
            continue
        gk = (int(x // 100), int(y // 100))
        if any(abs(x - px) < 70 and abs(y - py) < 70 for a in (-1, 0, 1) for b in (-1, 0, 1) for px, py in pg.get((gk[0] + a, gk[1] + b), ())):
            continue
        for w, d in SIZES:
            x0, y0 = x - w / 2 - 2, y - d / 2 - 2                     # a 2 m margin of free ground around the fence
            if not all_free(x0, y0, w + 4, d + 4):
                continue
            if density(x, y) < 0.03:
                break
            if any(abs(t[0] - x) < w / 2 + 6 and abs(t[1] - y) < d / 2 + 6 for k in ((int(x // 40) + a, int(y // 40) + b) for a in (-1, 0, 1) for b in (-1, 0, 1)) for t in tg.get(k, ())):
                continue
            hs = [th(x + sx * w / 2, y + sy * d / 2) for sx in (-1, 0, 1) for sy in (-1, 0, 1)]
            if max(hs) - min(hs) > 1.6:
                continue
            placed.append((x, y))
            pg.setdefault(gk, []).append((x, y))
            per_km_n[km] = per_km_n.get(km, 0) + 1
            LOTS.append((x - w / 2 - 1, y - d / 2 - 1, x + w / 2 + 1, y + d / 2 + 1))
            r = random.Random(int(x * 7 + y * 13))
            stage = r.choice((0, 1, 2, 3, 3, 4, 4, 5, 5))
            gate = r.randrange(4)
            hw, hd = w / 2, d / 2
            g = G()
            g.box(x, -1.0, y, w + 0.6, 1.0 + B, d + 0.6, DIRT)                                  # the levelled pad
            fp = fence(g, x, y, hw, hd, gate, r)
            # the building sits against the side opposite the gate, the yard and the mixer by the gate
            bw, bd = w * r.uniform(0.42, 0.55), d * r.uniform(0.42, 0.55)
            if gate < 2:
                bcx, bcz = x - (1 if gate == 0 else -1) * (hw - bw / 2 - 5), y + r.uniform(-1, 1) * 3
            else:
                bcx, bcz = x + r.uniform(-1, 1) * 3, y - (1 if gate == 2 else -1) * (hd - bd / 2 - 5)
            bx0, bx1, bz0, bz1 = bcx - bw / 2, bcx + bw / 2, bcz - bd / 2, bcz + bd / 2
            floors = building(g, bx0, bz0, bx1, bz1, stage, r)
            taken = [(bcx, bcz, max(bw, bd) / 2 + 4)]
            gx, gz = ((x + hw, y), (x - hw, y), (x, y + hd), (x, y - hd))[gate]
            inx, inz = ((-1, 0), (1, 0), (0, -1), (0, 1))[gate]
            taken.append((gx + inx * 6, gz + inz * 6, 5.0))
            yard(g, x, y, hw, hd, bx0, bz0, bx1, bz1, gate, r, taken)
            if stage >= 2:
                crane(g, bx1 + 3.0 if bx1 + 3 < x + hw - 2 else bx0 - 3.0, bcz, FLOOR_H * 5.0, r.uniform(0, 6.28))
            pos, uv, col = g.out()
            add(chunk_of(x, y), 3, pos, uv, col)
            t0 = th(x, y)
            for px, pz in fp:                                          # every fence panel is a breakable post
                posts.append((px, pz, 0.7, t0 - 1.0, t0 + FH + 0.1))
            if stage >= 1:                                             # the building: tall posts around its footprint
                hi = t0 + max(1.0, floors * FLOOR_H + 1.2)
                per = int((bw + bd) * 2 // 2.2)
                for k in range(per):
                    u = k / per * 4.0
                    side, f = int(u), u - int(u)
                    px, pz = ((bx0 + (bx1 - bx0) * f, bz0), (bx1, bz0 + (bz1 - bz0) * f), (bx1 - (bx1 - bx0) * f, bz1), (bx0, bz1 - (bz1 - bz0) * f))[side]
                    posts.append((px, pz, 0.9, t0 - 1.0, hi))
            else:                                                      # the spoil banks of the hole
                for k in range(int((bw + bd) * 2 // 3)):
                    u = k / int((bw + bd) * 2 // 3) * 4.0
                    side, f = int(u), u - int(u)
                    px, pz = ((bx0 + (bx1 - bx0) * f, bz0 - 1.6), (bx1 + 1.6, bz0 + (bz1 - bz0) * f), (bx1 - (bx1 - bx0) * f, bz1 + 1.6), (bx0 - 1.6, bz1 - (bz1 - bz0) * f))[side]
                    if side == 3 and abs(pz - bcz) < 3.0:
                        continue                                       # the ramp
                    posts.append((px, pz, 1.3, t0 - 1.0, t0 + 1.5))
            parked.append((gx + inx * 7 - inz * 4, gz + inz * 7 + inx * 4, math.atan2(inx, -inz), r.randint(0, 15), mixer))
            works.append((round(float(x), 1), round(float(y), 1), round(max(hw, hd) * 0.8, 1), stage, round(float(bcx), 1), round(float(bcz), 1), round(float(bw), 1), round(float(bd), 1),
                          round(float(gx), 1), round(float(gz), 1)))
            break
    log(f"[build] construction: {len(works)} sites, {len(posts)} fence / building posts, stages "
        + " ".join(str(sum(1 for w_ in works if w_[3] == s)) for s in range(6)))
    return posts, works, parked
