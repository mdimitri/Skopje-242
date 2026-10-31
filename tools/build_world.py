"""Turn raw Overpass JSON (data/osm*) into the runtime world (data/cache/world*.pkl).

Everything the map does not provide is generated here, deterministically (seeded by OSM ids):
building heights / colours / roofs, trees, street lamps, parked cars, surface mask, road graph.
"""
import argparse
import glob
import json
import math
import os
import pickle
import random
import sys
import zlib

import numpy as np
from PIL import Image, ImageDraw
import mapbox_earcut as earcut

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import HX, HY, project
from progress import Bar, each, phase, spread, flat
import terrain as terrain_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 35
CHUNK = 120.0
MARGIN = 4.0
CELL = 2.0                     # surface-mask resolution (m)
NCX = int(2 * HX / CELL)
NCY = int(2 * HY / CELL)

# ----------------------------------------------------------------- road classes
# cls: (width m, speed m/s, drivable, walkable)
ROAD = {
    "motorway": (14, 27, 1, 0), "motorway_link": (7, 14, 1, 0), "trunk": (14, 22, 1, 0), "trunk_link": (7, 12, 1, 0),
    "primary": (14, 15, 1, 1), "primary_link": (7, 10, 1, 1), "secondary": (7, 13.5, 1, 1),
    "secondary_link": (7, 9, 1, 1), "tertiary": (7, 12.5, 1, 1), "tertiary_link": (7, 9, 1, 1),
    "unclassified": (7, 10, 1, 1), "residential": (7, 9, 1, 1), "living_street": (7, 4.5, 1, 1),
    "service": (4.4, 5, 1, 1), "pedestrian": (4, 0, 0, 1), "footway": (2.2, 0, 0, 1), "path": (1.8, 0, 0, 1),
    "steps": (2, 0, 0, 1), "cycleway": (2.2, 0, 0, 1), "track": (3.5, 0, 0, 1),
}
CLSID = {k: i for i, k in enumerate(ROAD)}

AREA_STYLE = {   # kind: (z-order, rgb)
    "residential": (0, (205, 199, 187)), "commercial": (0, (213, 204, 196)), "industrial": (0, (190, 188, 190)),
    "farmland": (0, (205, 205, 160)), "sand": (0, (226, 215, 172)), "rock": (0, (172, 166, 156)),
    "grass": (1, (158, 196, 118)), "park": (1, (146, 190, 110)), "wood": (1, (100, 152, 86)),
    "scrub": (1, (128, 165, 100)), "pitch": (1, (132, 182, 106)), "cemetery": (1, (150, 186, 126)),
    "playground": (1, (190, 190, 150)), "plaza": (2, (212, 202, 186)), "parking": (2, (172, 172, 178)),
    "water": (3, (86, 146, 198)),
}


def connect_roads(roads, radius=7.0, drive_radius=12.0):
    """Join dead ends that stop just short of another road (a gap in the data): the end moves onto the nearest vertex or onto a new
    junction node inserted into that road.  Same level only (never bridges, never motorways), the end must point at the road.
    A street end may reach drive_radius, a path only radius."""
    use = {}
    for rd in roads:
        if (rd["drive"] or rd["walk"]) and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                use[n] = use.get(n, 0) + 1
    cs = 16.0
    grid = {}
    for ri, rd in enumerate(roads):
        if not (rd["drive"] or rd["walk"]) or rd["bridge"] or rd["cls"] == "motorway" or len(rd["nodes"]) != len(rd["pts"]):
            continue
        pts = rd["pts"]
        for k in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[k], pts[k + 1]
            rg = max(radius, drive_radius)
            for cx in range(int((min(ax, bx) - rg) // cs), int((max(ax, bx) + rg) // cs) + 1):
                for cy in range(int((min(ay, by) - rg) // cs), int((max(ay, by) + rg) // cs) + 1):
                    grid.setdefault((cx, cy), []).append((ri, k))
    inserts = {}                                    # road -> [(segment k, t, new node id, point)]
    fresh = -1
    snapped = merged = 0
    for ri, rd in enumerate(roads):
        if not (rd["drive"] or rd["walk"]) or rd["bridge"] or len(rd["nodes"]) != len(rd["pts"]) or len(rd["pts"]) < 2:
            continue
        for end in (0, -1):
            node, p = rd["nodes"][end], rd["pts"][end]
            if use.get(node, 0) != 1:
                continue
            q = rd["pts"][1] if end == 0 else rd["pts"][-2]
            dl = math.hypot(p[0] - q[0], p[1] - q[1]) or 1.0
            dx, dy = (p[0] - q[0]) / dl, (p[1] - q[1]) / dl
            best = None
            for ri2, k in grid.get((int(p[0] // cs), int(p[1] // cs)), ()):
                r2 = roads[ri2]
                if ri2 == ri or r2["layer"] != rd["layer"] or r2["bridge"]:
                    continue
                if rd["drive"] and not r2["drive"]:
                    continue
                (ax, ay), (bx, by) = r2["pts"][k], r2["pts"][k + 1]
                ex, ey = bx - ax, by - ay
                l2 = ex * ex + ey * ey
                t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * ex + (p[1] - ay) * ey) / l2))
                qx, qy = ax + ex * t, ay + ey * t
                d = math.hypot(p[0] - qx, p[1] - qy)
                if d > (drive_radius if rd["drive"] else radius) or d < 0.05:
                    continue
                if (qx - p[0]) * dx + (qy - p[1]) * dy < 0.2 * d:         # not pointing at it: a parallel neighbour
                    continue
                if best is None or d < best[0]:
                    best = (d, ri2, k, t, qx, qy)
            if best is None:
                continue
            d, ri2, k, t, qx, qy = best
            r2 = roads[ri2]
            if t < 0.15 or t > 0.85:                                       # right at a vertex: share that node
                kk = k if t < 0.5 else k + 1
                rd["nodes"][end] = r2["nodes"][kk]
                rd["pts"][end] = r2["pts"][kk]
                use[r2["nodes"][kk]] = use.get(r2["nodes"][kk], 0) + 1
                merged += 1
            else:
                fresh -= 1
                inserts.setdefault(ri2, []).append((k, t, fresh, (qx, qy)))
                rd["nodes"][end] = fresh
                rd["pts"][end] = (qx, qy)
                use[fresh] = 2
                snapped += 1
    for ri2, lst in inserts.items():
        r2 = roads[ri2]
        for k, t, nid_, pt in sorted(lst, key=lambda q: (q[0], q[1]), reverse=True):
            r2["pts"].insert(k + 1, pt)
            r2["nodes"].insert(k + 1, nid_)
    print(f"[build] connected {merged + snapped} dead ends to nearby roads ({snapped} new junctions)")
    return merged + snapped


def _inside(x, y, ring):
    c = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            c = not c
    return c


def _fill_lots(areas, bld_a, to_cell, ncx, ncy, hx, hy, occupancy=(0.62, 0.85)):
    """Car parks (amenity=parking areas): rows of 2.6 x 5.2 m bays along the lot's longest side, two rows nose to
    nose between 6 m aisles, filled to 62-85 %.  A bay is used only when the whole car stands inside the lot, clear of
    holes and buildings."""
    out = []
    for ar in areas:
        if ar["kind"] != "parking" or ar["area"] < 120:
            continue
        ring = ar["outer"]
        r = random.Random(ar["id"])
        occ = r.uniform(*occupancy)
        (ax, ay), (bx, by) = max(zip(ring, ring[1:] + ring[:1]), key=lambda q: (q[1][0] - q[0][0]) ** 2 + (q[1][1] - q[0][1]) ** 2)
        L = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / L, (by - ay) / L                   # along the rows
        vx, vy = -uy, ux                                        # across them
        us = [(p[0] - ax) * ux + (p[1] - ay) * uy for p in ring]
        vs = [(p[0] - ax) * vx + (p[1] - ay) * vy for p in ring]
        v, k = min(vs) + 2.8, 0
        while v < max(vs) - 2.6:
            face = 1.0 if k % 2 == 0 else -1.0                  # each pair of rows faces its aisle
            u = min(us) + 1.5
            while u < max(us) - 1.4:
                x, y = ax + ux * u + vx * v, ay + uy * u + vy * v
                corners = [(x + ux * a_ * 1.2 + vx * b_ * 2.5, y + uy * a_ * 1.2 + vy * b_ * 2.5) for a_ in (-1, 1) for b_ in (-1, 1)]
                ok = abs(x) < hx - 5 and abs(y) < hy - 5 and all(_inside(cx, cy, ring) for cx, cy in corners) \
                    and not any(_inside(x, y, h) for h in ar["holes"])
                if ok:
                    ix, iy = to_cell(x, y)
                    ok = 0 <= ix < ncx and 0 <= iy < ncy and not bld_a[iy, ix]
                if ok and r.random() < occ:
                    hd = math.atan2(vy, vx) + (0.0 if face > 0 else math.pi) + r.uniform(-0.06, 0.06)
                    out.append((x, y, hd, r.randint(0, 15), r.choice((0, 0, 1, 1, 1, 2, 3, 4, 4, 7, 7, 8))))
                u += 2.6
            v += 5.4 if k % 2 == 0 else 5.4 + 6.0                # aisle after every second row
            k += 1
    print(f"[build] car parks: {sum(1 for a in areas if a['kind'] == 'parking')} lots, {len(out)} parked cars")
    return out


def area_kind(t):
    if t.get("natural") == "water" or t.get("waterway") == "riverbank" or t.get("landuse") in ("reservoir", "basin"):
        return "water"
    if t.get("highway") == "pedestrian" or t.get("place") == "square":
        return "plaza"
    if t.get("amenity") == "parking":
        return "parking"
    n = t.get("natural")
    if n in ("wood",):
        return "wood"
    if n in ("scrub", "grassland"):
        return "scrub" if n == "scrub" else "grass"
    if n in ("sand", "beach"):
        return "sand"
    if n == "bare_rock":
        return "rock"
    le = t.get("leisure")
    if le in ("park", "garden", "nature_reserve", "recreation_ground", "golf_course"):
        return "park"
    if le in ("pitch", "stadium", "track", "sports_centre"):
        return "pitch"
    if le == "playground":
        return "playground"
    lu = t.get("landuse")
    if lu in ("forest",):
        return "wood"
    if lu in ("grass", "meadow", "village_green", "orchard", "vineyard", "greenfield", "flowerbed"):
        return "grass"
    if lu in ("cemetery",):
        return "cemetery"
    if lu in ("residential",):
        return "residential"
    if lu in ("commercial", "retail", "construction"):
        return "commercial"
    if lu in ("industrial", "railway", "garages", "quarry"):
        return "industrial"
    if lu in ("farmland", "farmyard", "allotments"):
        return "farmland"
    return None


# ----------------------------------------------------------------- geometry helpers
def shoelace(p):
    s = 0.0
    n = len(p)
    for i in range(n):
        x1, y1 = p[i]
        x2, y2 = p[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def pip(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def dedupe_ring(p):
    out = []
    for q in p:
        if not out or (abs(out[-1][0] - q[0]) > 1e-3 or abs(out[-1][1] - q[1]) > 1e-3):
            out.append(q)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-3 and abs(out[0][1] - out[-1][1]) < 1e-3:
        out.pop()
    return out


def triangulate(outer, holes):
    verts = list(outer)
    ends = [len(outer)]
    for h in holes:
        verts.extend(h)
        ends.append(len(verts))
    arr = np.array(verts, dtype=np.float64).reshape(-1, 2)
    try:
        idx = earcut.triangulate_float64(arr, np.array(ends, dtype=np.uint32))
    except Exception:  # noqa: BLE001
        return verts, []
    return verts, [int(i) for i in idx]


def join_rings(segments):
    """Join open way pieces (lists of points) into closed rings."""
    rings, pool = [], [list(s) for s in segments if len(s) > 1]
    key = lambda p: (round(p[0], 2), round(p[1], 2))
    while pool:
        cur = pool.pop()
        guard = 0
        while key(cur[0]) != key(cur[-1]) and guard < 10000:
            guard += 1
            for i, s in enumerate(pool):
                if key(s[0]) == key(cur[-1]):
                    cur += s[1:]
                elif key(s[-1]) == key(cur[-1]):
                    cur += s[::-1][1:]
                elif key(s[-1]) == key(cur[0]):
                    cur = s[:-1] + cur
                elif key(s[0]) == key(cur[0]):
                    cur = s[::-1][:-1] + cur
                else:
                    continue
                pool.pop(i)
                break
            else:
                break
        if len(cur) >= 4 and key(cur[0]) == key(cur[-1]):
            rings.append(cur[:-1])
    return rings


def geom_pts(el):
    return [project(g["lat"], g["lon"]) for g in el.get("geometry", []) if g]


def polygons_of(el):
    """-> list of (outer, [holes]) in local metres."""
    t = el.get("tags", {})
    if el["type"] == "way":
        g = geom_pts(el)
        if len(g) >= 4 and el["geometry"][0] == el["geometry"][-1]:
            return [(dedupe_ring(g), [])]
        return []
    if el["type"] == "relation":
        outers, inners = [], []
        for m in el.get("members", []):
            if m.get("type") != "way" or not m.get("geometry"):
                continue
            pts = [project(g["lat"], g["lon"]) for g in m["geometry"] if g]
            (inners if m.get("role") == "inner" else outers).append(pts)
        outs = join_rings(outers)
        ins = join_rings(inners)
        res = []
        for o in outs:
            o = dedupe_ring(o)
            if len(o) < 3:
                continue
            hs = [dedupe_ring(h) for h in ins if len(h) > 2 and pip(h[0], o)]
            res.append((o, [h for h in hs if len(h) > 2]))
        return res
    return []


def chunk_range(minx, miny, maxx, maxy):
    c0x, c1x = math.floor((minx - MARGIN) / CHUNK), math.floor((maxx + MARGIN) / CHUNK)
    c0y, c1y = math.floor((miny - MARGIN) / CHUNK), math.floor((maxy + MARGIN) / CHUNK)
    limx, limy = int(HX // CHUNK) + 1, int(HY // CHUNK) + 1
    for cx in range(max(c0x, -limx), min(c1x, limx - 1) + 1):
        for cy in range(max(c0y, -limy), min(c1y, limy - 1) + 1):
            yield cx, cy


def to_cell(x, y):
    return int((x + HX) / CELL), int((y + HY) / CELL)


# ----------------------------------------------------------------- palettes
ROOFS = [(176, 84, 62), (160, 76, 58), (140, 90, 70), (150, 150, 156), (120, 124, 130), (96, 100, 108),
         (190, 172, 146), (172, 160, 140), (110, 130, 140), (200, 190, 170), (132, 70, 60)]
WALLS = [(232, 224, 205), (225, 205, 170), (230, 190, 170), (214, 214, 208), (200, 215, 205), (236, 232, 222),
         (220, 196, 150)]


def vary(c, r, a=10):
    return tuple(max(0, min(255, v + r.randint(-a, a))) for v in c)


def building_height(t, area, r):
    def num(v):
        try:
            return float(str(v).replace("m", "").replace(",", ".").strip())
        except ValueError:
            return None
    h = num(t.get("height", "")) if t.get("height") else None
    if h is None and t.get("building:levels"):
        lv = num(t["building:levels"])
        if lv:
            h = lv * 3.1 + 1.0
    if h is None:
        b = t.get("building", "yes")
        if b in ("garage", "garages", "shed", "roof", "carport", "kiosk", "hut", "cabin", "service"):
            return r.uniform(2.6, 3.8)
        if b in ("house", "detached", "semidetached_house", "bungalow", "terrace"):
            return r.uniform(5.0, 9.0)
        if area < 70:
            h = r.uniform(3.5, 7)
        elif area < 250:
            h = r.uniform(6, 13)
        elif area < 900:
            h = r.uniform(9, 26)
        else:
            h = r.uniform(10, 34)
        if b in ("apartments", "residential", "dormitory"):
            h = max(h, r.uniform(15, 30))
    return max(2.5, min(h, 90.0))


# ----------------------------------------------------------------- mesh generation (numpy)
MAT_FACADE_A, MAT_FACADE_B, MAT_ROOF, MAT_SOLID = 0, 1, 2, 3
MAT_GRAF = 6                         # wall graffiti decals (atlas from src/graffiti.py)
GRAF_COLS, GRAF_ROWS, GRAF_N = 4, 8, 32
MAT_PANEL, MAT_HOUSE = 4, 5          # Skopje socialist prefab high-rise, family house (round 9)
SUN = np.array([-0.45, 0.80, -0.40])          # direction TO the sun (x east, y up, z south): from the north-west
SUN = SUN / np.linalg.norm(SUN)


def shade(n):
    """Baked lambert-ish shading for a unit normal (x,y,z)."""
    return 0.52 + 0.55 * max(0.0, float(np.dot(n, SUN)))


class MeshAcc:
    """Accumulates per-(chunk, material) geometry as lists of numpy blocks."""

    def __init__(self):
        self.d = {}

    def add(self, key, mat, pos, uv, col):
        e = self.d.setdefault((key, mat), ([], [], []))
        e[0].append(pos); e[1].append(uv); e[2].append(col)


def chunk_of(x, z):
    return (math.floor(x / CHUNK), math.floor(z / CHUNK))


def walls(ring, h, tint, y0=None):
    """Wall quads for a ring (x,z); returns pos(N,3) uv(N,2) col(N,4)."""
    r = np.asarray(ring, dtype=np.float32)
    nxt = np.roll(r, -1, axis=0)
    d = nxt - r
    ln = np.hypot(d[:, 0], d[:, 1])
    yb = np.zeros(len(r), np.float32) if y0 is None else np.asarray(y0, np.float32)
    ok = (ln > 0.15) & (yb < h - 0.3)
    r, nxt, d, ln, yb = r[ok], nxt[ok], d[ok], ln[ok], yb[ok]
    n = len(r)
    if n == 0:
        return None
    floors = np.maximum(1, np.round((h - yb) / 3.2))
    nb = np.maximum(1, np.round(ln / 3.4))
    p = np.empty((n, 6, 3), np.float32)
    uv = np.empty((n, 6, 2), np.float32)
    # quad corners: A(bottom,start) B(bottom,end) C(top,end) D(top,start); triangles ABC, ACD
    A = np.stack([r[:, 0], yb, r[:, 1]], 1)
    B = np.stack([nxt[:, 0], yb, nxt[:, 1]], 1)
    C = np.stack([nxt[:, 0], np.full(n, h), nxt[:, 1]], 1)
    D = np.stack([r[:, 0], np.full(n, h), r[:, 1]], 1)
    for i, q in enumerate((A, B, C, A, C, D)):
        p[:, i] = q
    ua = np.zeros(n); ub = nb
    for i, (u, v) in enumerate(((ua, floors), (ub, floors), (ub, 0), (ua, floors), (ub, 0), (ua, 0))):
        uv[:, i, 0] = u
        uv[:, i, 1] = v
    # outward normal for rings with positive shoelace (y-down): (dy,-dx)
    nrm = np.stack([d[:, 1] / ln, np.zeros(n), -d[:, 0] / ln], 1)
    sh = 0.52 + 0.55 * np.clip(nrm @ SUN, 0, None)
    sh = np.clip(sh, 0.45, 1.12)
    col = np.empty((n, 6, 4), np.uint8)
    base = np.array(tint, np.float32)
    for i in range(6):
        ao = 0.78 if i in (0, 1, 3) else 1.0          # darker at the foot
        col[:, i, :3] = np.clip(base[None, :] * (sh * ao)[:, None], 0, 255)
    col[:, :, 3] = 255
    return p.reshape(-1, 3), uv.reshape(-1, 2), col.reshape(-1, 4)


def graffiti_geo(ring, h, rng, n_max=2, big=False):
    """Alpha-keyed graffiti quads flat on the street-facing walls of one building -> (pos, uv, col) or None (y relative to the wall foot)."""
    r = np.asarray(ring, dtype=np.float32)
    d = np.roll(r, -1, axis=0) - r
    ln = np.hypot(d[:, 0], d[:, 1])
    order = [i for i in np.argsort(-ln)[:4] if ln[i] >= 4.5]
    if not order or h < 3.0:
        return None
    P, U, C = [], [], []
    for i in rng.sample(order, min(len(order), n_max)):
        w = rng.uniform(2.6, 4.8) * (2.0 if big else 1.0)
        if w > ln[i] - 1.0:
            w = ln[i] - 1.0
        if w < 1.4:
            continue
        hh = w * 0.5
        yc = rng.uniform(4.0, min(h - hh - 0.5, 9.0)) if big and h > 12 else rng.uniform(0.2, 0.9) + hh / 2 + 0.8
        if yc + hh / 2 > h - 0.3:
            continue
        ux, uz = d[i, 0] / ln[i], d[i, 1] / ln[i]
        nx, nz = uz, -ux                                    # outward, as in walls()
        s0 = rng.uniform(0.5, ln[i] - w - 0.5)
        ax, az = r[i, 0] + ux * s0 + nx * 0.05, r[i, 1] + uz * s0 + nz * 0.05
        bx, bz = ax + ux * w, az + uz * w
        y0, y1 = yc - hh / 2, yc + hh / 2
        cell = rng.randrange(GRAF_N)
        e = 3.0 / 1024                                      # keep clear of neighbouring cells
        u0, u1 = (cell % GRAF_COLS) / GRAF_COLS + e, (cell % GRAF_COLS + 1) / GRAF_COLS - e
        v0, v1 = (cell // GRAF_COLS) / GRAF_ROWS + e, (cell // GRAF_COLS + 1) / GRAF_ROWS - e
        A, B, Cc, D = (ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)
        P += [A, B, Cc, A, Cc, D]
        U += [(u0, v1), (u1, v1), (u1, v0), (u0, v1), (u1, v0), (u0, v0)]
        sh = int(255 * min(1.0, 0.82 + 0.3 * max(0.0, float(nx * SUN[0] + nz * SUN[2]))))     # paint stays vivid on shaded walls
        C += [(sh, sh, sh, 255)] * 6
    if not P:
        return None
    return np.array(P, np.float32), np.array(U, np.float32), np.array(C, np.uint8)


def flat_poly(v, tri, y, scale_uv, col):
    if not tri:
        return None
    t = np.asarray(tri, dtype=np.int64)
    pts = np.asarray(v, dtype=np.float32)[t]
    pos = np.empty((len(t), 3), np.float32)
    pos[:, 0], pos[:, 1], pos[:, 2] = pts[:, 0], y, pts[:, 1]
    uv = (pts / scale_uv).astype(np.float32)
    c = np.empty((len(t), 4), np.uint8)
    c[:, :3] = np.clip(col, 0, 255)
    c[:, 3] = 255
    return pos, uv, c


def is_convex(ring):
    n = len(ring)
    sg = 0
    for i in range(n):
        ax, ay = ring[i]; bx, by = ring[(i + 1) % n]; cx, cy = ring[(i + 2) % n]
        cr = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(cr) < 1e-6:
            continue
        s = 1 if cr > 0 else -1
        if sg and s != sg:
            return False
        sg = s
    return True


def pyramid(ring, y0, apex_h, col):
    cx = sum(p[0] for p in ring) / len(ring)
    cz = sum(p[1] for p in ring) / len(ring)
    pos, uv, cols = [], [], []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        tri = [(a[0], y0, a[1]), (b[0], y0, b[1]), (cx, y0 + apex_h, cz)]
        e1 = np.array([b[0] - a[0], 0, b[1] - a[1]]); e2 = np.array([cx - a[0], apex_h, cz - a[1]])
        nrm = np.cross(e1, e2)
        nl = np.linalg.norm(nrm)
        nrm = nrm / nl if nl else np.array([0, 1, 0])
        if nrm[1] < 0:
            nrm = -nrm
        sh = max(0.55, min(1.15, shade(nrm) * 1.05))
        for q in tri:
            pos.append(q); uv.append((q[0] / 3.0, q[2] / 3.0)); cols.append((*[min(255, c * sh) for c in col], 255))
    return np.array(pos, np.float32), np.array(uv, np.float32), np.array(cols, np.uint8)


def _parapet(ring, h, ph, col):
    """Low wall round the edge of a flat roof (outside face + inside face + top), so roofs read as roofs."""
    pos, cols = [], []
    n = len(ring)
    for i in range(n):
        (ax, az), (bx, bz) = ring[i], ring[(i + 1) % n]
        nx, nz = bz - az, -(bx - ax)
        ln = math.hypot(nx, nz) or 1.0
        nx, nz = nx / ln, nz / ln
        for sgn in (1, -1):
            sh = shade(np.array([nx * sgn, 0, nz * sgn]))
            ox, oz = -nx * 0.12 * (sgn < 0), -nz * 0.12 * (sgn < 0)
            q = [(ax + ox, h, az + oz), (bx + ox, h, bz + oz), (bx + ox, h + ph, bz + oz),
                 (ax + ox, h, az + oz), (bx + ox, h + ph, bz + oz), (ax + ox, h + ph, az + oz)]
            pos += q if sgn > 0 else [q[0], q[2], q[1], q[3], q[5], q[4]]
            cols += [(*[min(255, v * sh) for v in col], 255)] * 6
        sh = shade(np.array([0, 1, 0]))
        t = [(ax, h + ph, az), (bx, h + ph, bz), (bx - nx * 0.12, h + ph, bz - nz * 0.12),
             (ax, h + ph, az), (bx - nx * 0.12, h + ph, bz - nz * 0.12), (ax - nx * 0.12, h + ph, az - nz * 0.12)]
        pos += t
        cols += [(*[min(255, v * sh * 1.1) for v in col], 255)] * 6
    if not pos:
        return None
    pos = np.array(pos, np.float32)
    return pos, np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


def _inside_ring(x, y, ring, margin=0.0):
    """Point in polygon, at least `margin` metres from its edges."""
    ins = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            ins = not ins
        dx, dy = xj - xi, yj - yi
        l2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((x - xi) * dx + (y - yi) * dy) / l2))
        if (x - xi - dx * t) ** 2 + (y - yi - dy * t) ** 2 < margin * margin:
            return False
        j = i
    return ins


def box(cx, cz, sx, sz, h, y0, col, yaw=0.0):
    """Closed-top box (5 faces) as triangles; returns pos, uv, col."""
    ca, sa = math.cos(yaw), math.sin(yaw)
    hx, hz = sx / 2, sz / 2
    c = [(-hx, -hz), (hx, -hz), (hx, hz), (-hx, hz)]
    w = [(cx + ca * x - sa * z, cz + sa * x + ca * z) for x, z in c]
    pos, cols = [], []
    for i in range(4):
        a, b = w[i], w[(i + 1) % 4]
        nx, nz = (b[1] - a[1]), -(b[0] - a[0])
        l = math.hypot(nx, nz) or 1
        sh = shade(np.array([nx / l, 0, nz / l]))
        q = [(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + h, b[1]), (a[0], y0, a[1]), (b[0], y0 + h, b[1]), (a[0], y0 + h, a[1])]
        pos += q
        cols += [(*[min(255, v * sh) for v in col], 255)] * 6
    sh = shade(np.array([0, 1, 0]))
    top = [(w[0][0], y0 + h, w[0][1]), (w[1][0], y0 + h, w[1][1]), (w[2][0], y0 + h, w[2][1]),
           (w[0][0], y0 + h, w[0][1]), (w[2][0], y0 + h, w[2][1]), (w[3][0], y0 + h, w[3][1])]
    pos += top
    cols += [(*[min(255, v * sh) for v in col], 255)] * 6
    return np.array(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


TREE_GREENS = ((70, 128, 58), (86, 142, 62), (62, 114, 54), (110, 140, 52), (56, 96, 60), (124, 150, 70))
AUTUMN = ((196, 120, 40), (210, 170, 50), (170, 70, 40))


def tree_geo(x, z, r, shade_i, seed):
    """Seven kinds of tree so streets and parks don't look cloned: cone (pine/spruce), round crown (lime, plane),
    two-lump crown, tall poplar, birch (white trunk), autumn crown, bare dead tree."""
    rr = random.Random(seed)
    sp = rr.choices(range(7), (18, 30, 20, 10, 8, 9, 5))[0]
    trunk_h = (2.1 + r * 0.25) * (1.25 if sp == 3 else 1.0)
    pos, cols = [], []
    bark = (230, 230, 222) if sp == 4 else ((92, 70, 50) if sp != 6 else (80, 66, 54))
    tw = 0.12 if sp in (3, 4) else (0.17 + r * 0.02)
    th = trunk_h + (r * 1.1 if sp == 6 else 0.0)
    for ang in (0.0, math.pi / 2):
        ca, sa = math.cos(ang) * tw, math.sin(ang) * tw
        a = (x - ca, z - sa); b = (x + ca, z + sa)
        q = [(a[0], 0, a[1]), (b[0], 0, b[1]), (b[0], th, b[1]), (a[0], 0, a[1]), (b[0], th, b[1]), (a[0], th, a[1])]
        pos += q; cols += [(*bark, 255)] * 6
    if sp == 4:                                                  # birch: dark marks on the white trunk
        for k in range(3):
            y = trunk_h * (0.25 + 0.22 * k)
            pos += [(x - tw * 1.05, y, z), (x + tw * 1.05, y, z), (x + tw * 1.05, y + 0.08, z)]
            cols += [(40, 40, 40, 255)] * 3
    if sp == 6:                                                  # bare tree: a few branches, no leaves
        for k in range(5):
            a0 = rr.uniform(0, 6.28)
            y0 = th * rr.uniform(0.45, 0.9)
            ln = r * rr.uniform(0.6, 1.0)
            ex, ez, ey = x + math.cos(a0) * ln, z + math.sin(a0) * ln, y0 + ln * 0.7
            pos += [(x, y0, z), (x + math.cos(a0 + 1.57) * 0.06, y0 + 0.1, z + math.sin(a0 + 1.57) * 0.06), (ex, ey, ez)]
            cols += [(*bark, 255)] * 3
        return np.array(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)
    g = AUTUMN[shade_i % 3] if sp == 5 else (TREE_GREENS[(shade_i + seed) % 6] if sp != 0 else (46, 92, 56))
    g = tuple(min(255, max(0, c + rr.randint(-10, 10))) for c in g)

    def crown(cx, cz, rad, y_lo, y_mid, y_hi, n, off):
        nonlocal pos, cols
        for i in range(n):
            a0 = off + 2 * math.pi * i / n; a1 = off + 2 * math.pi * (i + 1) / n
            p0 = (cx + math.cos(a0) * rad, y_mid, cz + math.sin(a0) * rad)
            p1 = (cx + math.cos(a1) * rad, y_mid, cz + math.sin(a1) * rad)
            sh = 0.82 + 0.25 * math.cos(a0 + 0.8)
            lo = (*[min(255, c * sh * 0.78) for c in g], 255)
            hi = (*[min(255, c * sh * 1.18) for c in g], 255)
            pos += [p0, p1, (cx, y_hi, cz)]
            cols += [lo, lo, hi]
            if y_lo is not None:                                 # underside: a round crown, not a cone
                pos += [p1, p0, (cx, y_lo, cz)]
                cols += [lo, lo, (*[c * 0.55 for c in g], 255)]

    off = rr.uniform(0, 6.28)
    if sp == 0:                                                  # conifer: two stacked cones, tall and narrow
        crown(x, z, r * 0.75, None, trunk_h - 0.6, trunk_h + r * 1.6, 7, off)
        crown(x, z, r * 0.5, None, trunk_h + r * 0.8, trunk_h + r * 2.4, 6, off + 0.4)
    elif sp == 3:                                                # poplar: slim and very tall
        crown(x, z, r * 0.45, trunk_h - 0.8, trunk_h + r * 0.6, trunk_h + r * 2.8, 6, off)
    elif sp == 2:                                                # two lumps side by side
        for k in (-1, 1):                                        # lumps stay over the trunk and overlap: one crown, not two trees
            cx, cz = x + math.cos(off) * k * r * 0.2, z + math.sin(off) * k * r * 0.2
            crown(cx, cz, r * 0.85, trunk_h - 0.4, trunk_h + r * 0.5 + k * 0.1, trunk_h + r * 1.1 + k * 0.1, 6, off + k)
    else:                                                        # round crowns (also birch and autumn)
        rad = r * (0.7 if sp == 4 else 1.0)
        crown(x, z, rad, trunk_h - 0.4, trunk_h + rad * 0.5, trunk_h + rad * 1.2, 7, off)
    return np.array(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


def lamp_geo(x, z):
    pos, cols = [], []
    for ang in (0.0, math.pi / 2):
        ca, sa = math.cos(ang) * 0.09, math.sin(ang) * 0.09
        a = (x - ca, z - sa); b = (x + ca, z + sa)
        pos += [(a[0], 0, a[1]), (b[0], 0, b[1]), (b[0], 6.4, b[1]), (a[0], 0, a[1]), (b[0], 6.4, b[1]), (a[0], 6.4, a[1])]
        cols += [(70, 72, 78, 255)] * 6
    hx, hz = 0.55, 0.28
    y = 6.5
    pos += [(x - hx, y, z - hz), (x + hx, y, z - hz), (x + hx, y, z + hz), (x - hx, y, z - hz), (x + hx, y, z + hz), (x - hx, y, z + hz)]
    cols += [(255, 238, 170, 255)] * 6
    return np.array(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


# ----------------------------------------------------------------- main build
def _read_list(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:  # noqa: BLE001
        return []


def load_elements(src):
    elements, seen = [], set()
    files = sorted(glob.glob(os.path.join(src, "*.json")))
    for f in each(files, "read OSM files"):
        try:
            data = json.load(open(f, encoding="utf-8"))["elements"]
        except Exception as e:  # noqa: BLE001 - tolerate a corrupt optional file
            print(f"   WARNING: could not read {os.path.basename(f)} ({e}); skipping")
            if os.path.basename(f) in ("roads.json", "buildings.json"):
                raise
            continue
        for el in data:
            k = (el.get("type"), el.get("id"))
            if k not in seen:
                seen.add(k)
                elements.append(el)
    return elements


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "osm"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "cache", "world"))
    a = ap.parse_args()

    if os.path.exists(os.path.join(a.src, "pbf", "country.osm.pbf")) and not os.path.exists(os.path.join(a.src, "bus_stops.json")):
        try:                                                    # real bus stops (and lines / POIs) from the country file
            os.environ["SK242_OSM_DIR"] = a.src
            import fetch_extras
            fetch_extras.OSM = a.src
            fetch_extras.main()
        except Exception as e:  # noqa: BLE001 - optional
            print(f"[build] extras skipped: {e}")
    elements = load_elements(a.src)
    print(f"[build] {len(elements)} OSM elements from {a.src}")
    if not any(e.get("tags", {}).get("highway") for e in elements):
        raise SystemExit("[build] no roads found in source data")

    tfile = os.path.join(a.src, "terrain.npy")
    try:
        T = terrain_mod.load(tfile, HX, HY)
        print(f"[build] terrain: {tfile} (range {float(T.g.min()):+.0f} .. {float(T.g.max()):+.0f} m)")
        real_terrain = True
    except Exception as ex:  # noqa: BLE001 - the city still builds, just flat
        print(f"[build] terrain: none ({ex}) - FLAT city. Run tools/fetch_terrain.py for hills and slopes")
        T = terrain_mod.flat(HX, HY)
        real_terrain = False

    surf = Image.new("L", (NCX, NCY), 0)       # 0 ground, 1 water, 2 bridge, 3 road
    occ = Image.new("L", (NCX, NCY), 0)       # buildings + roads
    bld = Image.new("L", (NCX, NCY), 0)       # buildings only
    sd, od, bd = ImageDraw.Draw(surf), ImageDraw.Draw(occ), ImageDraw.Draw(bld)

    def cells(pts):
        return [((x + HX) / CELL, (y + HY) / CELL) for x, y in pts]

    mesh = MeshAcc()

    # ---- buildings (+ their 3D meshes) -------------------------------------------------------
    buildings = []
    pending = []                      # mesh emission waits until the river bed is carved into the terrain
    for el in each([e for e in elements if "building" in e.get("tags", {}) and e["tags"].get("building") != "no"],
                   "buildings -> 3D meshes", feed=("buildings", buildings, lambda b: list(b["ring"][0]))):
        t = el["tags"]
        try:
            polys = polygons_of(el)
        except Exception:  # noqa: BLE001
            continue
        for p_i, (outer, holes) in enumerate(polys):
            try:
                if len(outer) < 3:
                    continue
                ar = abs(shoelace(outer))
                if ar < 8:
                    continue
                r = random.Random(el["id"])
                if shoelace(outer) < 0:
                    outer = outer[::-1]
                verts, tri = triangulate(outer, holes)
                if not tri:
                    continue
                h = building_height(t, ar, r)
                xs = [p[0] for p in outer]
                ys = [p[1] for p in outer]
                roofc = vary(r.choice(ROOFS), r)
                if h > 14 and r.random() < 0.6:
                    roofc = vary(r.choice(ROOFS[3:8]), r, 6)
                wallc = vary(r.choice(WALLS), r, 6)
                bb = (min(xs), min(ys), max(xs), max(ys))
                buildings.append({"ring": outer, "v": verts, "tri": tri, "h": h, "bb": bb, "area": ar})
                od.polygon(cells(outer), fill=255)
                bd.polygon(cells(outer), fill=255)
                key = chunk_of((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                b_type = t.get("building", "yes")
                mat = MAT_FACADE_B if (h > 16 and r.random() < .45) or b_type in ("commercial", "office", "retail", "industrial") else MAT_FACADE_A
                small = ar < 240 and h < 11 and len(outer) <= 8 and is_convex(outer) and r.random() < 0.75
                if mat == MAT_FACADE_A:
                    if h >= 22 or (h >= 15 and r.random() < 0.6):
                        mat = MAT_PANEL                  # Аеродром / Карпош / Ѓорче Петров blocks
                    elif h < 10 and (small or b_type in ("house", "detached", "semidetached_house", "terrace")):
                        mat = MAT_HOUSE
                rooftop = []
                if not small and ar > 300 and r.random() < 0.8:        # rooftop boxes: stairwell / AC units
                    for _ in range(r.randint(1, 3)):
                        px, py = r.uniform(bb[0], bb[2]), r.uniform(bb[1], bb[3])
                        if pip((px, py), outer) and all(pip((px + dx, py + dy), outer) for dx, dy in ((2, 2), (-2, -2), (2, -2), (-2, 2))):
                            rooftop.append((px, py, r.uniform(1.5, 3.2), r.uniform(1.5, 3.2), r.uniform(1.0, 2.4)))
                pending.append((key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop))
            except Exception as e:  # noqa: BLE001 - skip a malformed building
                print(f"   skipped building {el.get('id')}: {e}")
    print(f"[build] buildings: {len(buildings)}")

    # ---- areas / water / rails ---------------------------------------------------------------
    areas, wlines, rails = [], [], []
    for el in each(elements, "areas / water / rails", feed=("areas", areas, lambda a: flat(a["v"]))):
        t = el.get("tags", {})
        if not t or "building" in t:
            continue
        try:
            if el["type"] == "way" and t.get("highway") and t.get("area") != "yes":
                continue
            ww = t.get("waterway")
            if ww in ("river", "stream", "canal") and el["type"] == "way":
                w = {"river": 22.0, "canal": 8.0, "stream": 3.0}[ww]
                if t.get("tunnel") or t.get("culvert"):
                    continue
                wlines.append({"pts": geom_pts(el), "w": w})
                continue
            if t.get("railway") and el["type"] == "way":
                if t.get("tunnel") not in (None, "no"):
                    continue
                rails.append({"pts": geom_pts(el), "bridge": t.get("bridge") not in (None, "no")})
                continue
            kind = area_kind(t)
            if not kind:
                continue
            for outer, holes in polygons_of(el):
                if len(outer) < 3:
                    continue
                ar = abs(shoelace(outer))
                if ar < 30:
                    continue
                verts, tri = triangulate(outer, holes)
                if not tri:
                    continue
                xs = [p[0] for p in outer]
                ys = [p[1] for p in outer]
                areas.append({"kind": kind, "outer": outer, "holes": holes, "v": verts, "tri": tri, "area": ar,
                              "bb": (min(xs), min(ys), max(xs), max(ys)), "id": el["id"]})
                if kind == "water":
                    sd.polygon(cells(outer), fill=1)
                    for h_ in holes:
                        sd.polygon(cells(h_), fill=0)
        except Exception as e:  # noqa: BLE001
            print(f"   skipped area {el.get('id')}: {e}")
    areas.sort(key=lambda q: (AREA_STYLE[q["kind"]][0], -q["area"]))
    for wl in wlines:
        if wl["w"] >= 8 and len(wl["pts"]) > 1:
            sd.line(cells(wl["pts"]), fill=1, width=max(1, int(wl["w"] / CELL)))
    print(f"[build] areas: {len(areas)}  waterlines: {len(wlines)}  rails: {len(rails)}")

    # ---- roads ---------------------------------------------------------------------------------
    roads = []
    for el in each([e for e in elements if e.get("type") == "way" and e.get("tags", {}).get("highway") in ROAD], "roads",
                   feed=("roads", roads, lambda r: flat(r["pts"], 60))):
        t = el["tags"]
        hw = t["highway"]
        try:
            if t.get("area") == "yes" or t.get("tunnel") in ("yes", "building_passage", "culvert"):
                continue
            pts = geom_pts(el)
            if len(pts) < 2:
                continue
            w, spd, drv, walk = ROAD[hw]
            if hw == "service" and t.get("service") in ("parking_aisle", "driveway", "drive-through", "emergency_access"):
                drv = 0
            if t.get("access") in ("private", "no") or t.get("motor_vehicle") in ("no", "private"):
                drv = 0
            lanes = 0
            if t.get("lanes"):
                try:
                    lanes = max(0, int(t["lanes"]))
                    w = max(w, lanes * 3.5)
                except ValueError:
                    pass
            ms = t.get("maxspeed", "")
            if ms.isdigit() and drv:
                spd = min(spd * 1.4, max(4.0, int(ms) / 3.6 * 0.95))      # drivers keep to about the posted limit
            ow = 0
            o = t.get("oneway")
            nodes = el.get("nodes", [])
            if o in ("yes", "true", "1") or t.get("junction") in ("roundabout",) or hw in ("motorway",):
                ow = 1
            elif o == "-1":
                ow = 1
                pts = pts[::-1]
                nodes = nodes[::-1]
            bridge = t.get("bridge") not in (None, "no")
            try:
                layer = int(t.get("layer", "1" if bridge else "0"))
            except ValueError:
                layer = 0
            roads.append({"pts": pts, "w": w, "cls": hw, "speed": spd, "drive": drv, "walk": walk, "ow": ow,
                          "bridge": bridge, "layer": layer, "nodes": nodes, "id": el["id"], "name": t.get("name", ""), "lanes": lanes})
        except Exception as e:  # noqa: BLE001
            print(f"   skipped road {el.get('id')}: {e}")
    water_a = np.asarray(surf, dtype=np.uint8) == 1          # water before roads/bridges are painted over it
    if real_terrain or True:
        T = terrain_mod.carve_water(T, water_a, CELL)

    # ---- building meshes, now that the ground under them is known ------------------------------
    for (key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop) in each(pending, "building meshes on terrain", feed=("bmesh", None, lambda it: list(it[2][0]))):
        ring = np.asarray(outer, np.float64)
        tz = T.h(ring[:, 0], ring[:, 1])
        cxm, cym = ring[:, 0].mean(), ring[:, 1].mean()
        base = float(np.mean(tz)) if len(tz) else 0.0
        skirt = max(0.0, base - float(min(tz.min(), T.hs(cxm, cym)))) + 0.3
        skirt_a = np.full(len(outer), -skirt, np.float32)

        def badd(m, pos, uv, col, base=base, key=key):
            pos = np.asarray(pos, np.float32).copy()
            pos[:, 1] += base
            mesh.add(key, m, pos, uv, col)

        w = walls(outer, h, wallc, skirt_a)
        if w:
            badd(mat, *w)
        rg = random.Random(len(outer) * 7919 ^ int(cxm * 131) ^ int(cym * 17))
        if rg.random() < {MAT_HOUSE: 0.4, MAT_PANEL: 0.5}.get(mat, 0.3):          # graffiti on the street wall(s)
            gg = graffiti_geo(outer, h, rg, 2 if mat != MAT_PANEL else 3, big=(mat == MAT_PANEL and rg.random() < 0.25))
            if gg:
                badd(MAT_GRAF, *gg)
        if small:
            badd(MAT_ROOF, *pyramid(outer, h, 1.8 + math.sqrt(ar) * 0.12, roofc))
        else:
            for hole in holes:
                hw_ = walls(hole[::-1], h, wallc, np.full(len(hole), -skirt, np.float32))
                if hw_:
                    badd(mat, *hw_)
            fp = flat_poly(verts, tri, h, 6.0, [c * 1.02 for c in roofc])
            if fp:
                badd(MAT_ROOF, *fp)
            pr = _parapet(outer, h, 0.55 if h > 8 else 0.35, [c * 0.82 for c in wallc])   # roof rim / attic wall
            if pr:
                badd(MAT_SOLID, *pr)
            for (px, py, sx, sz, hh) in rooftop:
                badd(MAT_SOLID, *box(px, py, sx, sz, hh, h, (150, 150, 156)))
            rj = random.Random(hash(key) ^ len(outer) * 977 ^ int(cxm * 13))
            if ar > 40 and rj.random() < 0.85:                      # roof junk: dishes, tanks, coops, laundry ...
                import junk
                x0_, y0_ = ring[:, 0].min(), ring[:, 1].min()
                x1_, y1_ = ring[:, 0].max(), ring[:, 1].max()
                for _k in range(rj.randint(5, 8 + int(min(30, ar / 40)))):
                    for _try in range(6):
                        px_, py_ = rj.uniform(x0_, x1_), rj.uniform(y0_, y1_)
                        if _inside_ring(px_, py_, outer, 1.0):
                            g_ = junk.make(rj.choice(junk.ROOF), px_, py_, rj.uniform(0, 6.283), rj.randrange(1 << 20))
                            pos_, uv_, col_ = g_.out()
                            if len(pos_):
                                pos_ = pos_.copy()
                                pos_[:, 1] += h
                                badd(MAT_SOLID, pos_, uv_, col_)
                            break
    del pending
    for rd in sorted(roads, key=lambda q: (q["bridge"], q["layer"])):
        val = 2 if rd["bridge"] else 3
        wpx = max(1, int(round((rd["w"] + 3) / CELL)))
        sd.line(cells(rd["pts"]), fill=val, width=wpx)
        od.line(cells(rd["pts"]), fill=255, width=wpx)
    roads.sort(key=lambda q: (q["bridge"], q["layer"], -q["w"]))
    print(f"[build] roads: {len(roads)}")
    phase("graph")

    connect_roads(roads)
    # ---- routing graph ----------------------------------------------------------------------------
    use = {}
    for rd in roads:
        if rd["drive"] or rd["walk"]:
            for n in rd["nodes"]:
                use[n] = use.get(n, 0) + 1
    node_ids, edges = {}, []

    def nid(osm):
        if osm not in node_ids:
            node_ids[osm] = len(node_ids)
        return node_ids[osm]

    for ri, rd in enumerate(roads):
        if not (rd["drive"] or rd["walk"]) or len(rd["nodes"]) != len(rd["pts"]):
            continue
        ns, ps = rd["nodes"], rd["pts"]
        start = 0
        for i in range(1, len(ps)):
            if i == len(ps) - 1 or use.get(ns[i], 0) >= 2:
                seg = ps[start:i + 1]
                cum = [0.0]
                for k in range(1, len(seg)):
                    cum.append(cum[-1] + math.hypot(seg[k][0] - seg[k - 1][0], seg[k][1] - seg[k - 1][1]))
                if cum[-1] > 0.5:
                    edges.append({"a": nid(ns[start]), "b": nid(ns[i]), "pts": seg, "cum": cum, "len": cum[-1],
                                  "cls": rd["cls"], "speed": rd["speed"], "drive": rd["drive"], "walk": rd["walk"],
                                  "ow": rd["ow"], "w": rd["w"], "road": ri, "bridge": rd["bridge"], "lanes": rd.get("lanes", 0)})
                start = i
    import roads3d
    roads3d.smooth_edges(edges)                  # rounded corners; junction end points stay put
    print(f"[build] graph: {len(node_ids)} nodes, {len(edges)} edges ({sum(1 for e in edges if e['drive'])} drivable)")
    spread("graph", edges, lambda e: flat(e["pts"], 60))
    phase("bridge decks")

    # ---- bridge decks: ends meet the terrain, the middle clears whatever runs underneath ---------------
    under = {}                                      # 12 m grid of ways a bridge may pass over
    for ri, rd in enumerate(roads):
        if rd["bridge"] or not (rd["drive"] or rd["walk"]):
            continue
        hwr = rd["w"] / 2 + (2.0 if rd["drive"] else 0.5)
        clear = terrain_mod.CLEAR_ROAD if rd["drive"] else terrain_mod.CLEAR_FOOT
        for k in range(len(rd["pts"]) - 1):
            (ax, ay), (bx, by) = rd["pts"][k], rd["pts"][k + 1]
            for cx_ in range(int((min(ax, bx) - hwr) // 12), int((max(ax, bx) + hwr) // 12) + 1):
                for cy_ in range(int((min(ay, by) - hwr) // 12), int((max(ay, by) + hwr) // 12) + 1):
                    under.setdefault((cx_, cy_), []).append((ax, ay, bx, by, hwr, clear))

    def lower(x, y):
        best = 0.0
        for ax, ay, bx, by, hwr, clear in under.get((int(x // 12), int(y // 12)), ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            if math.hypot(x - ax - dx * t, y - ay - dy * t) < hwr:
                best = max(best, clear)
        return best

    decks = {}
    for ri, rd in enumerate(roads):
        if rd["bridge"] and (rd["drive"] or rd["walk"]) and len(rd["pts"]) >= 2:
            try:
                decks[ri] = terrain_mod.make_deck(T, {"pts": rd["pts"]}, lower, rd["w"] / 2 + 0.6)
            except Exception as ex:  # noqa: BLE001 - a bad bridge stays flat
                print(f"   deck for road {rd['id']} skipped: {ex}")
    lifted = sum(1 for d in decks.values() if max(d.h) - min(d.h) > 1.5)
    print(f"[build] bridges: {len(decks)} decks ({lifted} with a real rise)")
    spread("bridge", [roads[ri] for ri in decks], lambda r: flat(r["pts"], 30))
    phase("places")

    # ---- procedural props -------------------------------------------------------------------------
    occ_a = np.asarray(occ, dtype=np.uint8)
    bld_a = np.asarray(bld, dtype=np.uint8)
    surf_a = np.asarray(surf, dtype=np.uint8)

    def free(x, y):
        if abs(x) >= HX - 5 or abs(y) >= HY - 5:
            return False
        cx, cy = to_cell(x, y)
        return not occ_a[cy, cx] and surf_a[cy, cx] == 0

    places = []          # (name_en or None, name, x, y, kind, polygon or None, osm ref)
    PLACE_KINDS = ("suburb", "neighbourhood", "quarter", "city_district", "district", "borough", "village", "town", "hamlet", "locality", "square")
    for el in elements:
        t = el.get("tags", {})
        if not t.get("name"):
            continue
        kind = t.get("place") if t.get("place") in PLACE_KINDS else ("admin" + t.get("admin_level", "") if t.get("boundary") == "administrative" and t.get("admin_level") in ("7", "8", "9", "10") else None)
        if not kind:
            continue
        nm_en = t.get("name:en") or t.get("name:latin") or t.get("int_name")
        ref = f"{el.get('type', '?')[0]}{el.get('id')}"
        try:
            if el.get("type") == "node" and "lat" in el:
                x, y = project(el["lat"], el["lon"])
                if abs(x) < HX and abs(y) < HY:
                    places.append((nm_en, t["name"], x, y, kind, None, ref))
            elif el.get("type") in ("way", "relation"):
                polys = polygons_of(el)
                if not polys:
                    continue
                ring = max((p[0] for p in polys), key=lambda r: abs(shoelace(r)))
                if abs(shoelace(ring)) < 2000:
                    continue
                cx = sum(p[0] for p in ring) / len(ring)
                cy = sum(p[1] for p in ring) / len(ring)
                step = max(1, len(ring) // 80)
                poly = [(round(p[0], 1), round(p[1], 1)) for p in ring[::step]]
                if abs(cx) < HX and abs(cy) < HY:
                    places.append((nm_en, t["name"], cx, cy, kind, poly, ref))
        except Exception as e:  # noqa: BLE001 - a bad boundary must not stop the build
            print(f"   skipped place {t.get('name')}: {e}")
    print(f"[build] places: {len(places)} ({sum(1 for p in places if p[5])} with outlines)")
    spread("places", places, lambda p: [p[2], p[3]])
    phase("street furniture")
    trees, lamps, parked = [], [], []
    rr = random.Random(1234)
    for el in elements:
        t = el.get("tags", {})
        if el.get("type") == "node" and "lat" in el:
            x, y = project(el["lat"], el["lon"])
            if abs(x) > HX or abs(y) > HY:
                continue
            if t.get("natural") == "tree":
                trees.append((x, y, rr.uniform(2.0, 3.6), rr.randint(0, 3)))
            elif t.get("highway") == "street_lamp":
                lamps.append((x, y))

    for ar in each(areas, "procedural trees in parks/woods", feed=("trees", trees, lambda t: [t[0], t[1]])):
        spacing = {"wood": 6.0, "park": 5.5, "cemetery": 6.0, "playground": 9.0, "grass": 19.0, "scrub": 9.0}.get(ar["kind"])   # round 8: 4x denser
        if not spacing:
            continue
        x0, y0, x1, y1 = ar["bb"]
        x0, y0 = max(x0, -HX), max(y0, -HY)
        x1, y1 = min(x1, HX), min(y1, HY)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > 30e6:
            continue
        w, h = int(x1 - x0) + 2, int(y1 - y0) + 2
        m = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(m)
        md.polygon([(px - x0, py - y0) for px, py in ar["outer"]], fill=255)
        for hl in ar["holes"]:
            md.polygon([(px - x0, py - y0) for px, py in hl], fill=0)
        ma = np.asarray(m)
        r = random.Random(ar["id"])
        gy = y0
        while gy < y1:
            gx = x0
            while gx < x1:
                px, py = gx + r.uniform(-spacing * .4, spacing * .4), gy + r.uniform(-spacing * .4, spacing * .4)
                ix, iy = int(px - x0), int(py - y0)
                if 0 <= ix < w and 0 <= iy < h and ma[iy, ix] and free(px, py):
                    trees.append((px, py, r.uniform(2.2, 4.4) if ar["kind"] == "wood" else r.uniform(2.0, 3.8), r.randint(0, 3)))
                gx += spacing
            gy += spacing

    import bisect
    _deg = {}
    for e_ in edges:
        for nd_ in (e_["a"], e_["b"]):
            _deg[nd_] = _deg.get(nd_, 0) + 1
    _bi = np.pad(bld_a.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def _bld_share(x, y, rad=30.0):
        """Share of building cells within rad metres: a quiet, built-up street has plenty."""
        cx_, cy_ = to_cell(x, y)
        k = int(rad / CELL)
        x0_, x1_, y0_, y1_ = max(cx_ - k, 0), min(cx_ + k + 1, NCX), max(cy_ - k, 0), min(cy_ + k + 1, NCY)
        n_ = (x1_ - x0_) * (y1_ - y0_)
        return float(_bi[y1_, x1_] - _bi[y0_, x1_] - _bi[y1_, x0_] + _bi[y0_, x0_]) / n_ if n_ > 0 else 0.0

    for e in each([e for e in edges if e["drive"] and not e["bridge"]], "street trees, lamps, parked cars",
                  feed=(("parked", parked, lambda p: [p[0], p[1]]), ("props", lamps, lambda p: [p[0], p[1]]))):
        r = random.Random(e["a"] * 100003 + e["b"])
        cls, w = e["cls"], e["w"]
        pts, cum, L = e["pts"], e["cum"], e["len"]

        def at(s):
            i = min(max(bisect.bisect_right(cum, s) - 1, 0), len(pts) - 2)
            seg = cum[i + 1] - cum[i] or 1.0
            tt = (s - cum[i]) / seg
            dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            d = math.hypot(dx, dy) or 1.0
            return pts[i][0] + dx * tt, pts[i][1] + dy * tt, dx / d, dy / d

        if cls in ("primary", "secondary", "tertiary", "residential", "unclassified", "living_street"):
            s, side = r.uniform(4, 12), 1
            step = 7.5 if cls != "residential" else 9.5        # round 8: 4x the street trees
            while s < L - 4:
                if r.random() < 0.9:
                    x, y, dx, dy = at(s)
                    off = w / 2 + 2.6
                    px, py = x - dy * off * side, y + dx * off * side
                    if free(px, py):
                        trees.append((px, py, r.uniform(1.9, 3.0), r.randint(0, 3)))
                side = -side
                s += step * r.uniform(0.8, 1.3)
        if cls in ("primary", "secondary", "tertiary", "trunk", "residential", "unclassified"):
            step = 36.0 if cls in ("primary", "secondary", "tertiary") else 55.0
            s, side = r.uniform(5, step), 1
            while s < L - 3:
                x, y, dx, dy = at(s)
                off = w / 2 + 1.4
                px, py = x - dy * off * side, y + dx * off * side
                if abs(px) < HX - 3 and abs(py) < HY - 3:
                    lamps.append((px, py))
                side = -side
                s += step
        if cls in ("residential", "unclassified", "tertiary") and L > 40 and w >= 6.0:
            # round 23: streets among many buildings are quiet and full of cars; the dense ones park both kerbs, diagonally where wide enough
            mx, my, _, _ = at(L / 2)
            dense = cls != "tertiary" and w <= 9.5 and _bld_share(mx, my) >= 0.06
            diag = dense and w >= 6.0
            if diag:
                e["sw"] = roads3d.SW_W * 1.5                             # wider pavement so the bays sit on it, not in the lane
            ctr = min(1.0, max(0.35, math.hypot(mx, my) / 1800.0))      # fewer on wide roads towards the centre
            sides = (1, -1) if dense and not e["ow"] and w >= 7.5 else (None,)     # round 31: narrow streets park one kerb only (two-kerb rows stalled traffic)
            for fixed in sides:
                s = 14.0 if diag else 11.0
                while s < L - (14.0 if diag else 11.0):
                    busy = 1.0 if dense else min(1.0, min(s if _deg.get(e["a"], 0) >= 3 else 99.0, (L - s) if _deg.get(e["b"], 0) >= 3 else 99.0) / 50.0)
                    if r.random() < (0.78 if diag else 0.7 if dense else 0.10 * busy * ctr):     # wide roads: half the cars, tapering at busy junctions
                        x, y, dx, dy = at(s)
                        _, _, dx0, dy0 = at(max(s - 7.0, 0.0))
                        _, _, dx1, dy1 = at(min(s + 7.0, L))
                        if dx0 * dx1 + dy0 * dy1 < 0.97:                          # a bend or curve: nobody parks there
                            s += 3.0
                            continue
                        side = fixed or (1 if e["ow"] else r.choice((1, -1)))     # one-way (boulevard halves): right kerb only, never the median
                        off = w / 2 + (2.45 if diag else 0.98)                  # wholly on the pavement (Skopje parks on it); diagonal bays on pavement and grass
                        px, py = x - dy * off * side, y + dx * off * side
                        dg = diag
                        if dg:                                                   # a building beside the pavement leaves no room: park parallel
                            for k_ in (-1.8, 0.0, 1.8):
                                qx_, qy_ = x + dx * k_ - dy * (w / 2 + 4.8) * side, y + dy * k_ + dx * (w / 2 + 4.8) * side
                                cx2, cy2 = to_cell(qx_, qy_)
                                if not (0 <= cx2 < NCX and 0 <= cy2 < NCY) or bld_a[cy2, cx2]:
                                    dg = False
                                    break
                            if not dg:
                                off = w / 2 + 0.98
                                px, py = x - dy * off * side, y + dx * off * side
                        if abs(px) < HX - 5 and abs(py) < HY - 5:
                            ix, iy = to_cell(px, py)
                            if not bld_a[iy, ix]:
                                hd = math.atan2(dy, dx) + (0.0 if side == 1 else math.pi)
                                if dg:
                                    hd += r.choice((0.72, 0.8, 0.88))             # ~45 deg, nose towards the kerb (kerb is at +90 deg of travel)
                                parked.append((px, py, hd, r.randint(0, 15), r.choice((0, 0, 1, 1, 1, 2, 3, 4, 4, 7, 7, 8))))
                    s += r.uniform(2.6, 3.1) if diag else r.uniform(5.2, 6.0) if dense else r.uniform(6.0, 9.0)
    lot_cars = _fill_lots(areas, bld_a, to_cell, NCX, NCY, HX, HY)
    asph = {}                                                   # round 26: nobody parks on asphalt: not on any road (parking-lot aisles and service lanes included)
    for rd_ in roads:
        if rd_["bridge"] or rd_["cls"] in ("footway", "path", "steps", "cycleway", "track", "pedestrian"):
            continue
        for (ax_, ay_), (bx_, by_) in zip(rd_["pts"], rd_["pts"][1:]):
            for gx_ in range(int((min(ax_, bx_) - 4) // 16), int((max(ax_, bx_) + 4) // 16) + 1):
                for gy_ in range(int((min(ay_, by_) - 4) // 16), int((max(ay_, by_) + 4) // 16) + 1):
                    asph.setdefault((gx_, gy_), []).append((ax_, ay_, bx_, by_, rd_["w"] / 2 - 0.02))

    def _on_asphalt(px_, py_):
        for ax_, ay_, bx_, by_, hw_ in asph.get((int(px_ // 16), int(py_ // 16)), ()):
            dx_, dy_ = bx_ - ax_, by_ - ay_
            l2_ = dx_ * dx_ + dy_ * dy_ or 1.0
            t_ = max(0.0, min(1.0, ((px_ - ax_) * dx_ + (py_ - ay_) * dy_) / l2_))
            if (px_ - ax_ - dx_ * t_) ** 2 + (py_ - ay_ - dy_ * t_) ** 2 < hw_ * hw_:
                return True
        return False

    def _clear_of_asphalt(q, pad=0.0):
        c_, s_ = math.cos(q[2]), math.sin(q[2])
        return not any(_on_asphalt(q[0] + c_ * u_ - s_ * v_, q[1] + s_ * u_ + c_ * v_)
                       for u_ in (-2.1 - pad, 0.0, 2.1 + pad) for v_ in (-0.85 - pad, 0.0, 0.85 + pad))
    parked = [q for q in parked if _clear_of_asphalt(q)] + [q for q in lot_cars if _clear_of_asphalt(q, 0.5)]     # car-park bays leave aisles and access lanes open
    kept, taken = [], {}                                        # round 23: cars of crossing streets must not overlap
    for q in parked:
        gx_, gy_ = int(q[0] // 4), int(q[1] // 4)
        if any((q[0] - o[0]) ** 2 + (q[1] - o[1]) ** 2 < 2.4 ** 2 for i_ in (-1, 0, 1) for j_ in (-1, 0, 1) for o in taken.get((gx_ + i_, gy_ + j_), ())):
            continue
        taken.setdefault((gx_, gy_), []).append(q)
        kept.append(q)
    parked = kept
    parked = [q for q in parked if random.Random(int(q[0] * 7.0) * 100003 + int(q[1] * 13.0)).random() < 0.5]     # round 27: half as many everywhere, the centre-to-suburb gradient stays
    print(f"[build] trees {len(trees)}  lamps {len(lamps)}  parked cars {len(parked)}")

    import furniture

    def _cell_ok(x, y):
        cx_, cy_ = to_cell(x, y)
        return 0 <= cx_ < NCX and 0 <= cy_ < NCY, cx_, cy_

    def _is_water(x, y):
        ok_, cx_, cy_ = _cell_ok(x, y)
        return bool(ok_ and water_a[cy_, cx_])

    def _not_building(x, y):
        ok_, cx_, cy_ = _cell_ok(x, y)
        return bool(ok_ and not bld_a[cy_, cx_])

    def add_c(key, mat, pos, uv, col):
        """Props stand on the terrain: lift by the height under the prop's centre (no tilt)."""
        pos = np.asarray(pos, np.float32).copy()
        pos[:, 1] += T.hs(float(pos[:, 0].mean()), float(pos[:, 2].mean()))
        mesh.add(key, mat, pos, uv, col)

    try:
        xwalks, posts, bridge_lamps = furniture.build(edges, roads, _is_water, _not_building, add_c, chunk_of, (HX, HY),
                                                      decks=decks, add_abs=mesh.add, terrain_h=lambda x, z: T.hs(x, z),
                                                      bus_stops=_read_list(os.path.join(a.src, "bus_stops.json")),
                                                      signals=_read_list(os.path.join(a.src, "signals.json")))
        lamps += bridge_lamps
        _st = list(__import__("furniture").STOPS)
        if _st:                                                 # round 23: no parked car within 16 m of a bus stop
            parked = [q for q in parked if all((q[0] - t[0]) ** 2 + (q[1] - t[1]) ** 2 > 256 and (q[0] - t[4]) ** 2 + (q[1] - t[5]) ** 2 > 256 for t in _st)]
    except Exception as e:  # noqa: BLE001 - furniture is decoration, never fatal
        print(f"[build] furniture skipped: {e}")
        xwalks, posts = [], []
    sites = []
    try:                                                        # round 13: bushes, playgrounds, pitches, school yards
        import leisure
        pois_ = _read_list(os.path.join(a.src, "map_pois.json"))
        lp, sites = leisure.build(areas, [q for q in pois_ if len(q) == 4], edges, add_c, chunk_of,
                                  lambda x, y: abs(x) < HX - 8 and abs(y) < HY - 8, free, _not_building,
                                  lambda x, y, ring: _inside_ring(x, y, ring, 0.5))
        posts = list(posts) + lp
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] leisure skipped: {e}")

    works = []
    try:                                                        # round 20: fenced building sites on empty lots in built-up areas
        import construction
        kill = Image.new("L", (NCX, NCY), 0)
        kd = ImageDraw.Draw(kill)
        for ar in areas:
            if ar["kind"] in ("park", "playground", "pitch", "cemetery", "wood", "water", "plaza", "parking", "sand", "rock"):
                kd.polygon([to_cell(px, py) for px, py in ar["outer"]], fill=1)
        free_mask = (occ_a == 0) & (surf_a == 0) & (np.asarray(kill) == 0)
        bi = np.pad(bld_a.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
        def density(x, y, rad=int(160 / CELL)):
            c, r_ = to_cell(x, y)
            c0, c1, r0, r1 = max(0, c - rad), min(NCX - 1, c + rad), max(0, r_ - rad), min(NCY - 1, r_ + rad)
            return (bi[r1 + 1, c1 + 1] - bi[r0, c1 + 1] - bi[r1 + 1, c0] + bi[r0, c0]) / max(1, (r1 - r0 + 1) * (c1 - c0 + 1))
        cp, works, cparked = construction.build(density, None, free_mask, CELL, HX, HY, add_c, chunk_of, lambda x, y: T.hs(x, y),
                                                [(q[0], q[1]) for q in posts])
        posts = list(posts) + cp
        lots = construction.LOTS
        if lots and trees:                                      # a site clears its lot of trees
            ta = np.array([(t[0], t[1]) for t in trees])
            keep = np.ones(len(trees), bool)
            for a_, b_, c_, d_ in lots:
                keep &= ~((ta[:, 0] >= a_) & (ta[:, 0] <= c_) & (ta[:, 1] >= b_) & (ta[:, 1] <= d_))
            trees = [t for t, k in zip(trees, keep) if k]
        parked = list(parked) + cparked
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] construction skipped: {e}")

    try:                                                        # round 29: open ground gets gardens, scrub, boulders, vines
        import fill
        am = Image.new("L", (NCX, NCY), 0)
        amd = ImageDraw.Draw(am)
        for ar in areas:
            if ar["kind"] in ("park", "playground", "pitch", "cemetery", "wood", "water", "plaza", "parking", "sand", "rock", "grass", "scrub"):
                amd.polygon([to_cell(px, py) for px, py in ar["outer"]], fill=1)
        am_a = np.asarray(am)
        fp, ft = fill.build(lambda x, y: _bld_share(x, y, 80.0),
                            lambda x, y: free(x, y) and not _is_water(x, y) and _not_building(x, y),
                            lambda x, y: not am_a[to_cell(x, y)[1], to_cell(x, y)[0]],
                            None, add_c, chunk_of, HX, HY)
        posts = list(posts) + fp
        trees = list(trees) + ft
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] fill skipped: {e}")

    # ---- leftovers on the carriageway: lamps, trees and collision posts that stand inside a drivable lane (OSM street_lamp
    # nodes on the centre line, links, bridge lamps above a road, fence panels of a site that overlaps a street) block
    # cars and turns for good, so they go; posts up on a bridge deck are left alone
    cgrid_ = {}
    for e_ in edges:
        if e_["drive"] and not e_["bridge"]:
            for (ax_, ay_), (bx_, by_) in zip(e_["pts"], e_["pts"][1:]):
                for gx_ in range(int(min(ax_, bx_) // 20) - 1, int(max(ax_, bx_) // 20) + 2):
                    for gy_ in range(int(min(ay_, by_) // 20) - 1, int(max(ay_, by_) // 20) + 2):
                        cgrid_.setdefault((gx_, gy_), []).append((ax_, ay_, bx_, by_, e_["w"] / 2 - 0.2))

    def in_lane(x, y, r=0.0):
        for ax_, ay_, bx_, by_, hw_ in cgrid_.get((int(x // 20), int(y // 20)), ()):
            dx_, dy_ = bx_ - ax_, by_ - ay_
            t_ = max(0.0, min(1.0, ((x - ax_) * dx_ + (y - ay_) * dy_) / (dx_ * dx_ + dy_ * dy_ or 1e-9)))
            if math.hypot(x - ax_ - dx_ * t_, y - ay_ - dy_ * t_) < hw_ - r:
                return True
        return False

    n_l, n_t, n_p = len(lamps), len(trees), len(posts)
    lamps = [q for q in lamps if not in_lane(q[0], q[1], 0.22)]
    trees = [q for q in trees if not in_lane(q[0], q[1], 0.5)]
    posts = [q for q in posts if (len(q) >= 5 and q[3] > T.hs(q[0], q[1]) + 2.2) or not in_lane(q[0], q[1])]
    print(f"[build] cleared from the carriageways: {n_l - len(lamps)} lamps, {n_t - len(trees)} trees, {n_p - len(posts)} posts")

    stations, track = [], {"lines": [], "crossings": []}
    try:                                                        # round 21: railway viaducts, level crossings, stations
        import rail
        rl = _read_list(os.path.join(a.src, "rail.json"))
        if rl:
            rp, stations, track = rail.build(rl, edges, add_c, mesh.add, chunk_of, lambda x, y: float(T.hs(x, y)), in_lane)
            posts = list(posts) + rp
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] railway skipped: {e}")

    try:
        phase("3D roads")
        roads3d.PIER_SKIP = lambda x, y, r: in_lane(x, y, -r)           # no bridge pier in a street passing underneath
        nv, piers = roads3d.build(edges, xwalks, mesh.add, chunk_of, MAT_SOLID, T=T, decks=decks)
        posts = list(posts) + piers
        roads3d_ok = True
        print(f"[build] 3D roads: {nv / 1e6:.2f} M vertices")
    except Exception as e:  # noqa: BLE001 - fall back to the flat 2D roads in the ground texture
        import traceback
        traceback.print_exc()
        print(f"[build] 3D roads failed ({e}); using flat roads")
        roads3d_ok = False
    spread("road3d", edges, lambda e: flat(e["pts"], 60))
    phase("ground rasters")
    hg = Image.new("L", (NCX, NCY), 0)       # ground height class: 0 ground, 1 asphalt, 2 pavement
    hd = ImageDraw.Draw(hg)
    for e_ in edges:
        if roads3d._base(e_["cls"]) in roads3d.SIDEWALK and not e_["bridge"]:
            hd.line(cells(e_["pts"]), fill=2, width=max(1, int(round((e_["w"] + 2 * roads3d.SW_W) / CELL))))
    for e_ in sorted(edges, key=lambda q: roads3d.rank_of(q["cls"])):
        if e_["drive"] or e_["walk"]:
            hd.line(cells(e_["pts"]), fill=1, width=max(1, int(round(e_["w"] / CELL))))

    hg_arr = np.asarray(hg, dtype=np.uint8).copy()
    hg_arr[water_a] |= 4                                        # bit 2: ground-level water (also under bridges)
    posts = [p if len(p) == 5 else (p[0], p[1], p[2], T.hs(p[0], p[1]) - 1.0, T.hs(p[0], p[1]) + 2.4) for p in posts]

    for i, (x, y, r_, sh) in enumerate(each(trees, "tree meshes", feed=("trees", None, lambda t: [t[0], t[1]]))):
        add_c(chunk_of(x, y), MAT_SOLID, *tree_geo(x, y, r_, sh, i))
    for x, y in each(lamps, "lamp meshes", feed=("props", None, lambda p: [p[0], p[1]])):
        add_c(chunk_of(x, y), MAT_SOLID, *lamp_geo(x, y))

    # ---- chunk index (for ground baking) ---------------------------------------------------------
    chunks = {}

    def slot(c):
        d = chunks.get(c)
        if d is None:
            d = chunks[c] = {"b": [], "a": [], "r": [], "wl": [], "rail": [], "t": [], "x": [], "m": {}, "bb": None}
        return d

    SKEW = 0.22
    for i, b in enumerate(buildings):
        x0, y0, x1, y1 = b["bb"]
        h = b["h"]
        for c in chunk_range(x0, y0, x1 + h * 0.3, y1 + h * 0.2):
            slot(c)["b"].append(i)
    for i, ar in enumerate(each(areas, "chunk index: areas", feed=("areas", None, lambda a: flat(a["v"])))):
        pass
    for i, ar in enumerate(areas):
        x0, y0, x1, y1 = ar["bb"]
        tri, v = ar["tri"], ar["v"]
        ntri = len(tri) // 3
        if ntri <= 24:
            for c in chunk_range(x0, y0, x1, y1):
                slot(c)["a"].append((i, None))
            continue
        per = {}
        for k in range(ntri):
            p = [v[tri[3 * k]], v[tri[3 * k + 1]], v[tri[3 * k + 2]]]
            for c in chunk_range(min(q[0] for q in p), min(q[1] for q in p), max(q[0] for q in p), max(q[1] for q in p)):
                per.setdefault(c, []).append(k)
        for c, ks in per.items():
            slot(c)["a"].append((i, ks))

    def index_lines(lst, key, pad_fn):
        for i, ln in enumerate(lst):
            pts = ln["pts"]
            pad = pad_fn(ln)
            for k in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[k], pts[k + 1]
                for c in chunk_range(min(ax, bx) - pad, min(ay, by) - pad, max(ax, bx) + pad, max(ay, by) + pad):
                    slot(c)[key].append((i, k))

    index_lines(roads, "r", lambda rd: rd["w"] / 2 + 3)
    index_lines(wlines, "wl", lambda w_: w_["w"] / 2 + 2)
    index_lines(rails, "rail", lambda r_: 3)
    for i, xw_ in enumerate(xwalks):
        for c in chunk_range(xw_[0] - xw_[4], xw_[1] - xw_[4], xw_[0] + xw_[4], xw_[1] + xw_[4]):
            slot(c)["x"].append(i)
    for i, p in enumerate(trees):
        for c in chunk_range(p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5):
            slot(c)["t"].append(i)

    # ---- spawn point -------------------------------------------------------------------------------------
    phase("spawn point")
    best, spawn = 1e18, (0.0, 0.0, 0.0)
    for e in edges:
        if not e["drive"] or e["cls"] in ("service", "living_street") or e["len"] < 25:
            continue
        for k in range(len(e["pts"]) - 1):
            (ax, ay), (bx, by) = e["pts"][k], e["pts"][k + 1]
            mx, my = (ax + bx) / 2, (ay + by) / 2
            d = mx * mx + my * my
            if d < best:
                best, spawn = d, (mx, my, math.atan2(by - ay, bx - ax))
    print(f"[build] spawn {spawn[0]:.0f},{spawn[1]:.0f} ({math.sqrt(best):.0f} m from centre)")

    # ---- write: mesh blob + pickled parts + manifest (atomic, with sizes for integrity checks) ------------
    phase("write world")
    tmp = a.out + ".tmp"
    if os.path.isdir(tmp):
        import shutil
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    off = 0
    nverts_total = 0
    with open(os.path.join(tmp, "meshes.bin"), "wb") as f:
        for (key, mat), (P, U, C) in each(sorted(mesh.d.items()), "write mesh blob",
                                         feed=("chunk", None, lambda it: [(it[0][0][0] + 0.5) * CHUNK, (it[0][0][1] + 0.5) * CHUNK])):
            pos = np.concatenate(P).astype(np.float32)
            uv = np.concatenate(U).astype(np.float32)
            col = np.concatenate(C).astype(np.uint8)
            n = len(pos)
            n -= n % 3
            pos, uv, col = pos[:n], uv[:n], col[:n]
            f.write(pos.tobytes()); f.write(uv.tobytes()); f.write(col.tobytes())
            d = slot(key)
            d["m"][mat] = (off, n)
            lo, hi = pos.min(axis=0), pos.max(axis=0)
            bb = d["bb"]
            d["bb"] = (float(lo[0]), float(lo[2]), float(hi[0]), float(hi[2]), float(hi[1])) if bb is None else (
                min(bb[0], float(lo[0])), min(bb[1], float(lo[2])), max(bb[2], float(hi[0])), max(bb[3], float(hi[2])), max(bb[4], float(hi[1])))
            off += n * (12 + 8 + 4)
            nverts_total += n
    print(f"[build] meshes: {nverts_total / 1e6:.2f} M vertices, {off / 1e6:.1f} MB")

    parts = {
        "meta": {"version": VERSION, "hx": HX, "hy": HY, "half": HX, "chunk": CHUNK, "margin": MARGIN, "cell": CELL, "spawn": spawn,
                 "area_style": dict(AREA_STYLE), "ncx": NCX, "ncy": NCY, "roads3d": bool(roads3d_ok)},
        "areas": {"areas": areas, "wlines": wlines, "rails": rails},
        "roads": {"roads": roads},
        "edges": {"edges": edges},
        "buildings": {"buildings": buildings},
        "props": {"trees": trees, "lamps": lamps, "parked": parked, "posts": posts, "xwalks": xwalks, "places": places,
                  "signals": list(__import__("furniture").SIGNALS), "bus_stops": list(__import__("furniture").STOPS),
                  "sites": sites, "works": works, "stations": stations, "track": track},
        "chunks": {"chunks": chunks},
        "surf": {"surf": zlib.compress(np.asarray(surf, dtype=np.uint8).tobytes(), 6),
                 "hgt": zlib.compress(hg_arr.tobytes(), 6)},
        "terrain": {"terrain": {"grid": np.asarray(T.g, np.float32).tobytes(), "nx": T.nx, "ny": T.ny, "step": terrain_mod.STEP,
                                "real": bool(real_terrain)},
                    "decks": [d.pack() for d in decks.values()]},
    }
    sizes = {"meshes.bin": os.path.getsize(os.path.join(tmp, "meshes.bin"))}
    for name, obj in each(parts.items(), "write world parts"):
        fn = name + ".pkl"
        with open(os.path.join(tmp, fn), "wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        sizes[fn] = os.path.getsize(os.path.join(tmp, fn))
    json.dump({"version": VERSION, "sizes": sizes}, open(os.path.join(tmp, "manifest.json"), "w"))
    if os.path.isdir(a.out):
        import shutil
        shutil.rmtree(a.out)
    os.replace(tmp, a.out)
    print(f"[build] wrote {a.out} ({sum(sizes.values()) / 1e6:.1f} MB), {len(chunks)} chunks")


if __name__ == "__main__":
    main()
