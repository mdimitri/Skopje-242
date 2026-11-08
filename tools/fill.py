"""Round 29: fill the empty ground with Skopje-flavoured small things instead of one repeated texture.

Regions of open ground (no building, road, water or mapped area) are split into 18 m blocks.  Slow value noise picks a "mood"
for each stretch of about 150-400 m, so neighbouring stretches differ: kitchen-garden plots with a shed, dry scrub and
boulders, vine rows, haystacks and stubble, wild bushes.  Everything is a few dozen triangles baked into the chunk meshes
(like the other street furniture); only walnuts and mulberries are returned as trees.  -> (posts, trees)"""
import math
import random

import numpy as np

from furniture import G
import par
from progress import Bar
from junk import _prism

DRY = ((128, 124, 70), (146, 134, 78), (110, 118, 64), (150, 140, 96), (118, 108, 66))
SOIL = (112, 86, 62)
CROP = ((70, 130, 60), (92, 140, 56), (120, 150, 66), (60, 112, 52))
WOOD = (140, 108, 74)
TIN = ((150, 150, 156), (170, 120, 90), (120, 140, 160), (180, 90, 70))
STONE = ((150, 146, 138), (132, 128, 122), (166, 158, 146))
STRAW = (206, 178, 96)
BLK = 14.0


def _noise(n, rng, scale):
    """Smooth 0..1 value noise on an n x n grid: random lattice every `scale` blocks, bilinearly spread."""
    m = n // scale + 3
    lat = np.array([[rng.random() for _ in range(m)] for _ in range(m)])
    ys, xs = np.mgrid[0:n, 0:n] / scale
    x0, y0 = xs.astype(int), ys.astype(int)
    fx, fy = xs - x0, ys - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    return (lat[y0, x0] * (1 - fx) * (1 - fy) + lat[y0, x0 + 1] * fx * (1 - fy)
            + lat[y0 + 1, x0] * (1 - fx) * fy + lat[y0 + 1, x0 + 1] * fx * fy)


def scrub(g, x, z, r, seed):
    """Dry shrub: three overlapping lumps of different tone, so it reads as a bush, not a hexagon."""
    rr = random.Random(seed)
    c = DRY[seed % len(DRY)]
    h = r * rr.uniform(0.7, 1.2)
    _prism(g, x, 0.0, z, r, h * 0.55, 7, tuple(v * 0.84 for v in c))
    for i in range(2):
        a = rr.uniform(0, 6.28)
        k = rr.uniform(0.88, 1.12)
        _prism(g, x + math.cos(a) * r * 0.5, h * 0.3, z + math.sin(a) * r * 0.5, r * rr.uniform(0.5, 0.75), h * rr.uniform(0.5, 0.8), 6,
               tuple(min(255, v * k) for v in c))
    if rr.random() < 0.3:                                              # wild flowers: poppy, daisy, chicory
        fc = rr.choice(((200, 60, 50), (240, 240, 235), (120, 140, 210), (236, 200, 60)))
        for _ in range(3):
            a = rr.uniform(0, 6.28)
            g.box(x + math.cos(a) * r * 0.8, h * 0.55, z + math.sin(a) * r * 0.8, 0.12, 0.08, 0.12, fc)


def tuft(g, x, z, seed):
    """A little clump of dry grass blades: single leaning triangles, drawn from both sides."""
    rr = random.Random(seed)
    c = DRY[seed % len(DRY)]
    for _ in range(4):
        a = rr.uniform(0, 6.28)
        ca, sa = math.cos(a), math.sin(a)
        bx, bz = x + rr.uniform(-.2, .2), z + rr.uniform(-.2, .2)
        h, lean = rr.uniform(0.35, 0.7), rr.uniform(0.05, 0.2)
        col = tuple(v * rr.uniform(.9, 1.15) for v in c)
        p0, p1, tip = (bx - sa * .04, 0, bz + ca * .04), (bx + sa * .04, 0, bz - ca * .04), (bx + ca * lean, h, bz + sa * lean)
        g.tri(p0, p1, tip, col, (ca, 0.3, sa))
        g.tri(p1, p0, tip, col, (-ca, 0.3, -sa))


def boulder(g, x, z, r, seed):
    rr = random.Random(seed)
    c = STONE[seed % len(STONE)]
    _prism(g, x, 0.0, z, r, r * 0.7, 6, c, rz=r * rr.uniform(0.7, 1.0))
    _prism(g, x + r * 0.1, r * 0.7, z, r * 0.6, r * 0.3, 5, tuple(v * 1.06 for v in c))


def haystack(g, x, z, seed):
    r = 0.9 + (seed % 3) * 0.15
    _prism(g, x, 0.0, z, r, r * 1.1, 8, STRAW)
    _prism(g, x, r * 1.1, z, r * 0.7, r * 0.4, 8, tuple(v * 0.94 for v in STRAW))
    _prism(g, x, r * 1.5, z, r * 0.25, r * 0.3, 6, tuple(v * 0.9 for v in STRAW))


def garden(g, x, z, yaw, rr):
    """A kitchen-garden plot: low fence of posts and a rail, ridged beds, a tin-roofed shed and a water barrel."""
    w, d = rr.uniform(8, 13), rr.uniform(6, 9)
    ca, sa = math.cos(yaw), math.sin(yaw)

    def P(u, v):
        return x + ca * u - sa * v, z + sa * u + ca * v
    for u in (-w / 2, w / 2):
        for v in range(int(-d / 2), int(d / 2) + 1, 2):
            px, pz = P(u, v)
            g.box(px, 0, pz, 0.08, 1.1, 0.08, WOOD)
    for v in (-d / 2, d / 2):
        for u in range(int(-w / 2), int(w / 2) + 1, 2):
            px, pz = P(u, v)
            g.box(px, 0, pz, 0.08, 1.1, 0.08, WOOD)
    for v in (-d / 2, d / 2):
        px, pz = P(0, v)
        g.box(px, 0.5, pz, w, 0.05, 0.04, WOOD, yaw)
        g.box(px, 0.9, pz, w, 0.05, 0.04, WOOD, yaw)
    for u in (-w / 2, w / 2):
        px, pz = P(u, 0)
        g.box(px, 0.5, pz, 0.04, 0.05, d, WOOD, yaw)
        g.box(px, 0.9, pz, 0.04, 0.05, d, WOOD, yaw)
    col = rr.choice(CROP)
    n = int((d - 3) / 1.1)
    for i in range(n):                                              # beds: soil ridge with a leafy crop on top
        px, pz = P(0.0 + 1.5, -d / 2 + 1.0 + i * 1.1)
        g.box(px, 0, pz, w - 4.2, 0.18, 0.7, SOIL, yaw)
        g.box(px, 0.18, pz, w - 4.4, 0.3, 0.45, tuple(v * rr.uniform(.85, 1.1) for v in col), yaw)
    sx, sz = P(-w / 2 + 1.4, 0.0)                                   # shed
    sc = rr.choice(TIN)
    g.box(sx, 0, sz, 2.0, 1.9, 2.4, WOOD, yaw)
    g.box(sx, 1.9, sz, 2.3, 0.1, 2.7, sc, yaw)
    bx, bz = P(-w / 2 + 1.2, d / 2 - 1.0)
    _prism(g, bx, 0, bz, 0.35, 0.9, 8, (60, 90, 150))
    return w, d


def vines(g, x, z, yaw, rr):
    """Rows of trellis posts, wire and leafy vines."""
    rows, ln = rr.randint(3, 5), rr.uniform(14, 24)
    ca, sa = math.cos(yaw), math.sin(yaw)
    leaf = rr.choice(CROP)
    for i in range(rows):
        v = (i - rows / 2) * 2.2
        for u in np.arange(-ln / 2, ln / 2 + 0.1, 3.0):
            g.box(x + ca * u - sa * v, 0, z + sa * u + ca * v, 0.09, 1.5, 0.09, WOOD)
        g.box(x - sa * v, 0.55, z + ca * v, ln, 0.8, 0.5, tuple(c * 0.92 for c in leaf), yaw)
        g.box(x - sa * v, 1.3, z + ca * v, ln, 0.05, 0.05, (90, 90, 90), yaw)
    return ln / 2 + 1.5, rows * 1.1 + 1.5


def _build_ops(ops):
    """One block's scrub / boulders / haystacks / tufts -> its mesh (runs in a worker)."""
    g = G()
    for op in ops:
        {"s": scrub, "b": boulder, "h": haystack, "t": tuft}[op[0]](g, *op[1:])
    return g.out()


def build(dense, free, area_ok, hs, add, chunk_of, HX, HY, log=print):
    """dense(x, y): built-up share 0..1; free(x, y): open ground; area_ok(x, y): not inside a park/wood/pitch/plaza/water area.
    -> (posts, trees)"""
    n = int(2 * HX / BLK) + 1
    nb = int(2 * HY / BLK) + 1
    nn = max(n, nb)
    rng = random.Random(2910)
    mood = _noise(nn, rng, 9) * 0.65 + _noise(nn, rng, 22) * 0.35         # 160 - 400 m stretches
    wet = _noise(nn, rng, 14)
    posts, trees = [], []
    samples = []
    cnt = dict(garden=0, scrub=0, vines=0, hay=0, rock=0, tuft=0, tree=0)

    def ok(x, z, r):
        return all(free(x + dx, z + dz) and area_ok(x + dx, z + dz) for dx, dz in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)))

    jobs, ops_n = [], 0                                                     # in block order: ("add", key, mesh) | ("ops", key, [op, ...])
    bar = Bar("fill: gardens, scrub, boulders", 1000, unit="")      # 0-30 %: planning the blocks, 30-100 %: building them on the pool
    for by in range(nb):
        bar.update(int(300 * by / nb))
        for bx in range(n):
            x0, z0 = -HX + bx * BLK, -HY + by * BLK
            r = random.Random(bx * 73856093 ^ by * 19349663)
            cx, cz = x0 + r.uniform(4, BLK - 4), z0 + r.uniform(4, BLK - 4)
            if not ok(cx, cz, 2.5):
                continue
            m, d = mood[by, bx], dense(cx, cz)
            hi = d > 0.05                                                   # near houses vs. open edge of town
            roll = r.random()
            if hi and m < 0.42 and roll < 0.30 and ok(cx, cz, 7.0):
                g = G()
                w, dd = garden(g, cx, cz, r.choice((0, math.pi / 2)) + r.uniform(-.15, .15), r)
                jobs.append(("add", chunk_of(cx, cz), g.out()))
                posts.append((cx - w / 2 + 1.4, cz, 1.3))
                samples.append((round(cx), round(cz)))
                cnt["garden"] += 1
                if r.random() < 0.7:
                    trees.append((cx + w / 2 + 3.0, cz + r.uniform(-3, 3), r.uniform(2.6, 3.8), r.randint(0, 3)))
                    cnt["tree"] += 1
            elif not hi and 0.5 < m < 0.7 and wet[by, bx] > 0.45 and roll < 0.35 and ok(cx, cz, 12.0):
                g = G()
                hw, hd = vines(g, cx, cz, r.uniform(0, 3.14), r)
                jobs.append(("add", chunk_of(cx, cz), g.out()))
                cnt["vines"] += 1
            elif roll < 0.65 + 0.3 * (1 - m):                              # dry scrub, boulders, tufts: denser where the mood is dry
                ops = []                                                    # the shapes only use their own seeds: built later, in parallel
                for _ in range(r.randint(3, 6)):
                    px, pz = cx + r.uniform(-6, 6), cz + r.uniform(-6, 6)
                    if not ok(px, pz, 1.2):
                        continue
                    k = r.random()
                    if k < 0.40:
                        rb = r.uniform(0.5, 1.1)
                        ops.append(("s", px, pz, rb, cnt["scrub"] + bx))
                        cnt["scrub"] += 1
                    elif k < 0.47:
                        rb = r.uniform(0.4, 0.9)
                        ops.append(("b", px, pz, rb, bx + by))
                        posts.append((px, pz, rb * 0.9))
                        cnt["rock"] += 1
                    elif k < 0.53 and not hi:
                        ops.append(("h", px, pz, bx * 7 + by))
                        posts.append((px, pz, 1.0))
                        cnt["hay"] += 1
                    else:
                        for _t in range(r.randint(2, 4)):
                            ops.append(("t", px + r.uniform(-1.2, 1.2), pz + r.uniform(-1.2, 1.2), bx + by + _t))
                        cnt["tuft"] += 1
                jobs.append(("ops", chunk_of(cx, cz), ops))
                if r.random() < 0.16 and m > 0.4 and ok(cx, cz, 3.5):          # a lone walnut / mulberry / poplar
                    trees.append((cx + r.uniform(-4, 4), cz + r.uniform(-4, 4), r.uniform(2.4, 4.0), r.randint(0, 3)))
                    cnt["tree"] += 1
    todo = [j[2] for j in jobs if j[0] == "ops"]
    built = iter(par.pmap(_build_ops, todo, chunk=64, on=lambda d, t: bar.update(300 + 700 * d // t)))
    for kind, key, data in jobs:
        pos, uv, col = data if kind == "add" else next(built)
        if len(pos):
            add(key, 3, pos, uv, col)
    bar.done()
    log("[build] fill: " + ", ".join(f"{v} {k}" for k, v in cnt.items()))
    log(f"[build] fill samples: {samples[::max(1, len(samples) // 8)]}")
    return posts, trees
