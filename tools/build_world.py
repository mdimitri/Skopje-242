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
sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from geo import HX, HY, project
from progress import Bar, each, phase, spread, flat, frac, span
import par
import terrain as terrain_mod
import arch as arch_mod
import worship

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 69
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


TUNNEL_ROADS = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential")


def lift_over_tunnels(roads, margin=8.0):
    """A road tunnel lies on the ground here, so whatever crosses over it (a plaza, a street, a footpath on a higher layer) is cut
    at the crossing and the cut piece becomes a bridge: the existing deck code then lifts it clear of the road below."""
    tun = [r for r in roads if r.get("tunnel")]
    if not tun:
        return roads

    def cross(a, b, c, d):                       # parameter t on a-b where it meets c-d, else None
        rx, ry, sx, sy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
        den = rx * sy - ry * sx
        if abs(den) < 1e-9:
            return None
        t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
        u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
        return t if 0 < t < 1 and 0 < u < 1 else None

    fresh = [-1]
    out = []
    for rd in roads:
        if rd.get("tunnel") or rd["bridge"] or not (rd["drive"] or rd["walk"]) or len(rd["nodes"]) != len(rd["pts"]) or rd["layer"] < 0:
            out.append(rd)
            continue
        pts, nodes = rd["pts"], rd["nodes"]
        cuts = []                                # (arc length of the crossing, half width of the tunnel road)
        cum = [0.0]
        for k in range(len(pts) - 1):
            cum.append(cum[-1] + math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]))
        for tr in tun:
            if set(tr["nodes"]) & set(nodes):
                continue                         # meets the tunnel at a shared node: a junction, not a crossing
            for k in range(len(pts) - 1):
                for j in range(len(tr["pts"]) - 1):
                    t = cross(pts[k], pts[k + 1], tr["pts"][j], tr["pts"][j + 1])
                    if t is not None:
                        cuts.append((cum[k] + t * (cum[k + 1] - cum[k]), tr["w"] / 2))
        if not cuts:
            out.append(rd)
            continue
        s0 = max(0.0, min(c - h for c, h in cuts) - margin)
        s1 = min(cum[-1], max(c + h for c, h in cuts) + margin)

        def at(s):                               # point on the polyline at arc length s -> (k, point)
            for k in range(len(pts) - 1):
                if s <= cum[k + 1] or k == len(pts) - 2:
                    f = (s - cum[k]) / max(cum[k + 1] - cum[k], 1e-9)
                    return k, (pts[k][0] + (pts[k + 1][0] - pts[k][0]) * f, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * f)

        k0, p0 = at(s0)
        k1, p1 = at(s1)
        n0, n1 = fresh[0], fresh[0] - 1
        fresh[0] -= 2
        mid = [p0] + pts[k0 + 1:k1 + 1] + [p1]
        mid_n = [n0] + nodes[k0 + 1:k1 + 1] + [n1]
        pieces = [(pts[:k0 + 1] + [p0], nodes[:k0 + 1] + [n0], False), (mid, mid_n, True), ([p1] + pts[k1 + 1:], [n1] + nodes[k1 + 1:], False)]
        for pp, nn, br in pieces:
            if len(pp) >= 2 and sum(math.hypot(pp[i + 1][0] - pp[i][0], pp[i + 1][1] - pp[i][1]) for i in range(len(pp) - 1)) > 1.0:
                piece = dict(rd, pts=pp, nodes=nn)
                if br:
                    piece.update(bridge=True, layer=max(rd["layer"], 1))
                out.append(piece)
    print(f"[build] tunnels: {len(tun)} road tunnels, {sum(1 for r in out if r['bridge']) - sum(1 for r in roads if r['bridge'])} crossings lifted into bridges")
    return out


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
        if ri % 256 == 0:
            frac(0.06 * ri / max(1, len(roads)), "roads joined")      # (graph phase: 0 .. 0.2 is this and the worn paths)
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
        if ri % 256 == 0:
            frac(0.06 + 0.04 * ri / max(1, len(roads)), "roads joined")
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


def bld_style(t, ar, outer, r):
    """Height, roof / wall colour, facade material and the small pitched-roof flag of one building, with the random draws in the
    world build's order (src/photogram.py calls it to show the current look of a building)."""
    h = building_height(t, ar, r)
    roofc = vary(r.choice(ROOFS), r)
    if h > 14 and r.random() < 0.6:
        roofc = vary(r.choice(ROOFS[3:8]), r, 6)
    wallc = vary(r.choice(WALLS), r, 6)
    b_type = t.get("building", "yes")
    mat = MAT_FACADE_B if (h > 16 and r.random() < .45) or b_type in ("commercial", "office", "retail", "industrial") else MAT_FACADE_A
    small = ar < 240 and h < 11 and len(outer) <= 8 and is_convex(outer) and r.random() < 0.75
    if mat == MAT_FACADE_A:
        if h >= 22 or (h >= 15 and r.random() < 0.6):
            mat = MAT_PANEL                  # Аеродром / Карпош / Ѓорче Петров blocks
        elif h < 10 and (small or b_type in ("house", "detached", "semidetached_house", "terrace")):
            mat = MAT_HOUSE
    if not small and h >= 7 and mat in (MAT_FACADE_A, MAT_PANEL):
        q_ = r.random()
        if mat == MAT_PANEL:
            mat = MAT_BRICK if q_ < 0.3 else MAT_MIX if q_ < 0.5 else MAT_CONC if q_ < 0.58 else MAT_CONCG if q_ < 0.66 else MAT_CREAM if q_ < 0.8 else MAT_PANEL
        else:
            mat = MAT_BRICK if q_ < 0.25 else MAT_MIX if q_ < 0.4 else MAT_CREAM if q_ < 0.6 else MAT_FACADE_A
        if mat == MAT_BRICK:
            wallc = vary((250, 244, 238), r, 5)
        elif mat in (MAT_CONC, MAT_CONCG, MAT_MIX):
            wallc = vary((236, 234, 228), r, 5)
    return h, roofc, wallc, mat, small


# ----------------------------------------------------------------- mesh generation (numpy)
MAT_FACADE_A, MAT_FACADE_B, MAT_ROOF, MAT_SOLID = 0, 1, 2, 3
MAT_GRAF = 6                         # wall graffiti decals (atlas from src/graffiti.py)
GRAF_COLS, GRAF_ROWS, GRAF_N = 4, 52, 205
MAT_BRICK, MAT_CONC, MAT_CONCG, MAT_CREAM, MAT_MIX = 7, 8, 9, 10, 11     # photo-based Skopje facades
MAT_PANEL, MAT_HOUSE = 4, 5          # Skopje socialist prefab high-rise, family house (round 9)
# photo-fitted facades (src/photogram.py, ДЕТАЛИ): procedural surfaces, textures from gl3d.surface_textures (same order as gl3d.SURF_NAMES)
MAT_SURF = {"plas": 12, "concw": 13, "tilew": 14, "brkw": 15, "metw": 16, "glaz": 17}
MAT_KIT2, MAT_KIT3 = 18, 19          # photo-facade relief (frames, sills, fins ...) and clutter (AC, dishes, wear): the game's
                                      # detail setting and far ring leave them out (src/archkit.py TIER); drawn with "glaz"
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


def walls(ring, h, tint, y0=None, fh=3.2, bw=3.4):
    """Wall quads for a ring (x,z); returns pos(N,3) uv(N,2) col(N,4).  fh / bw: the floor height and window-bay width (m) of one texture tile."""
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
    floors = np.maximum(1, np.round((h - yb) / fh))
    nb = np.maximum(1, np.round(ln / bw))
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


def _cable(p0, p1, sag, n=8, col=(34, 34, 38)):
    """A thin sagging cable (TV / phone line) between two points as crossed ribbons -> pos, uv, col."""
    pts = []
    for k in range(n + 1):
        t = k / n
        pts.append((p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t - sag * 4 * t * (1 - t), p0[2] + (p1[2] - p0[2]) * t))
    pos = []
    for a, b in zip(pts[:-1], pts[1:]):
        dx, dz = b[0] - a[0], b[2] - a[2]
        l = math.hypot(dx, dz) or 1
        nx, nz = -dz / l * 0.03, dx / l * 0.03
        for q in ((a[0] - nx, a[1], a[2] - nz), (a[0] + nx, a[1], a[2] + nz), (b[0] + nx, b[1], b[2] + nz),
                  (a[0] - nx, a[1], a[2] - nz), (b[0] + nx, b[1], b[2] + nz), (b[0] - nx, b[1], b[2] - nz)):
            pos.append(q)
        for q in ((a[0], a[1] - 0.03, a[2]), (a[0], a[1] + 0.03, a[2]), (b[0], b[1] + 0.03, b[2]),
                  (a[0], a[1] - 0.03, a[2]), (b[0], b[1] + 0.03, b[2]), (b[0], b[1] - 0.03, b[2])):
            pos.append(q)
    pos = np.array(pos, np.float32)
    return pos, np.zeros((len(pos), 2), np.float32), np.tile(np.array([*col, 255], np.uint8), (len(pos), 1))


def _junk_piece(kind, x, y, z, yaw, seed):
    import junk
    ids = [i for i, c in enumerate(junk.CATALOG) if c[1] == kind]
    if not ids:
        return None
    g = junk.make(ids[seed % len(ids)], x, z, yaw, seed)
    pos, uv, col = g.out()
    if not len(pos):
        return None
    pos = pos.copy()
    pos[:, 1] += y
    return pos, uv, col


def _prism(cx, cz, sx, sz, y0, rise, yaw, col):
    """Gabled roof piece: ridge along local x, eaves along the long sides -> pos, uv, col (open bottom)."""
    ca, sa = math.cos(yaw), math.sin(yaw)

    def w(x, z, y):
        return (cx + ca * x - sa * z, y, cz + sa * x + ca * z)
    hx, hz = sx / 2, sz / 2
    A, B, C, D = w(-hx, -hz, y0), w(hx, -hz, y0), w(hx, hz, y0), w(-hx, hz, y0)
    R0, R1 = w(-hx, 0, y0 + rise), w(hx, 0, y0 + rise)
    tris = [(A, B, R1), (A, R1, R0), (D, R0, R1), (D, R1, C), (A, R0, D), (B, C, R1)]
    pos = np.array([v for t in tris for v in t], np.float32)
    cols = []
    for k, t in enumerate(tris):
        sh = (1.0, 0.82, 0.9, 0.9, 0.78, 0.78)[k] * (1.0 if k < 4 else 0.9)
        cols += [(*[min(255, c * sh) for c in col], 255)] * 3
    return pos, np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


def _wedge(cx, cz, sx, sz, y0, rise, yaw, col):
    """Monopitch roof: rises along local x from 0 to `rise` -> pos, uv, col."""
    ca, sa = math.cos(yaw), math.sin(yaw)

    def w(x, z, y):
        return (cx + ca * x - sa * z, y, cz + sa * x + ca * z)
    hx, hz = sx / 2, sz / 2
    A, B, C, D = w(-hx, -hz, y0), w(hx, -hz, y0 + rise), w(hx, hz, y0 + rise), w(-hx, hz, y0)
    Bl, Cl = w(hx, -hz, y0), w(hx, hz, y0)
    tris = [(A, B, C), (A, C, D), (B, Bl, Cl), (B, Cl, C), (A, Bl, B), (D, C, Cl)]
    pos = np.array([v for t in tris for v in t], np.float32)
    cols = []
    for k in range(6):
        sh = (1.0, 1.0, 0.85, 0.85, 0.8, 0.8)[k]
        cols += [(*[min(255, c * sh) for c in col], 255)] * 3
    return pos, np.zeros((len(pos), 2), np.float32), np.array(cols, np.uint8)


def roof_structure(ring, h, rg, roofc):
    """Procedural 70s-80s Yugoslav roof crowns instead of a flat slab: dormer crown, sawtooth, monopitch, castle-notched parapet."""
    r = np.asarray(ring, dtype=np.float64)
    xs, zs = r[:, 0], r[:, 1]
    w_, l_ = xs.max() - xs.min(), zs.max() - zs.min()
    cx, cz = (xs.min() + xs.max()) / 2, (zs.min() + zs.max()) / 2
    st = rg.choice(("crown", "saw", "mono", "notch", "flat", "flat"))
    col = tuple(min(255, c * rg.uniform(0.8, 1.05)) for c in roofc)
    out = []
    if st == "crown":                                          # a row of small gables around the rim (Kapishtec towers)
        d = np.roll(r, -1, axis=0) - r
        ln = np.hypot(d[:, 0], d[:, 1])
        for i in np.argsort(-ln)[:3]:
            if ln[i] < 8:
                continue
            ux, uz = d[i] / ln[i]
            yaw = math.atan2(uz, ux)
            n = int(ln[i] // 3.4)
            for b in range(n):
                t = (b + 0.5) * ln[i] / n
                px, pz = r[i][0] + ux * t + uz * 1.0, r[i][1] + uz * t - ux * 1.0
                if _inside_ring(px, pz, ring, 0.6):
                    out.append(_prism(px, pz, 2.6, 2.2, h, rg.uniform(1.0, 1.7), yaw + math.pi / 2, col))
    elif st == "saw" and w_ > 10 and l_ > 10:                  # sawtooth teeth
        k = rg.randint(3, 6)
        ax = rg.random() < 0.5
        for q in range(k):
            f = (q + 0.5) / k - 0.5
            px, pz = (cx + f * w_ * 0.8, cz) if ax else (cx, cz + f * l_ * 0.8)
            sx, sz = (w_ * 0.8 / k * 0.9, l_ * 0.6) if ax else (w_ * 0.6, l_ * 0.8 / k * 0.9)
            if all(_inside_ring(px + a_ * sx / 2, pz + b_ * sz / 2, ring, 0.6) for a_, b_ in ((1, 1), (-1, -1), (1, -1), (-1, 1))):
                out.append(_wedge(px, pz, sx, sz, h, rg.uniform(1.4, 2.2), 0.0 if ax else math.pi / 2, col))
    elif st == "mono":                                         # one big slanted roof over most of the slab
        sx, sz = w_ * 0.7, l_ * 0.7
        if all(_inside_ring(cx + a_ * sx / 2, cz + b_ * sz / 2, ring, 0.6) for a_, b_ in ((1, 1), (-1, -1), (1, -1), (-1, 1))):
            out.append(_wedge(cx, cz, sx, sz, h, rg.uniform(1.8, 3.5), rg.choice((0.0, math.pi / 2, math.pi, -math.pi / 2)), col))
    elif st == "notch":                                        # brutalist crenellated parapet blocks along the rim
        d = np.roll(r, -1, axis=0) - r
        ln = np.hypot(d[:, 0], d[:, 1])
        for i in range(len(r)):
            if ln[i] < 5:
                continue
            ux, uz = d[i] / ln[i]
            yaw = math.atan2(uz, ux)
            n = int(ln[i] // 2.4)
            for b in range(0, n, 2):
                t = (b + 0.5) * ln[i] / n
                out.append(box(r[i][0] + ux * t, r[i][1] + uz * t, ln[i] / n * 1.1, 0.5, rg.uniform(0.8, 1.6), h, (156, 154, 148), yaw))
    return out


def facade_extras(ring, h, rg, wallc):
    """Per-building structure on the street walls, one style per building: balcony columns/rows, a lift shaft, a fire-escape stair -> list of (pos, uv, col)."""
    r = np.asarray(ring, dtype=np.float64)
    d = np.roll(r, -1, axis=0) - r
    ln = np.hypot(d[:, 0], d[:, 1])
    walls_ = [i for i in np.argsort(-ln)[:4] if ln[i] >= 7.0]
    if not walls_ or h < 8:
        return []
    out = []
    floors = max(2, int(h // 3.2))
    slab = tuple(c * 0.86 for c in wallc)
    rail = (74, 74, 80)
    dark = (70, 70, 76)
    style = rg.choice(("rows", "columns", "alternate", "bare", "bare", "loggia"))
    period = rg.choice((2, 3, 4))
    phase = rg.randrange(period)
    two_sides = rg.random() < 0.6
    budget = 140

    def at(i, t, off):
        x0, z0 = r[i]
        dx, dz = d[i] / ln[i]
        return x0 + dx * t + dz * off, z0 + dz * t - dx * off, math.atan2(dz, dx)
    closed = set(rg.sample(range(5), rg.choice((0, 0, 1, 2))))
    closed_col = ((226, 222, 206), (186, 150, 112), (150, 168, 176), (206, 190, 150))
    if rg.random() < 0.2:                                        # pillars under a wall (open ground floor / added columns)
        i = walls_[0]
        for q in range(max(2, int(ln[i] // 3.4))):
            cx, cz, yaw = at(i, (q + 0.5) * ln[i] / max(2, int(ln[i] // 3.4)), 0.9)
            out.append(box(cx, cz, 0.55, 0.55, 3.4, 0.0, (150, 148, 142), yaw))

    for k, i in enumerate(walls_[: 2 if two_sides else 1]):
        nb = int(ln[i] // 3.4)
        if style == "bare" or nb < 2:
            break
        for b in range(nb):
            if style == "columns" and b % period != phase:
                continue
            for f in range(1, floors):
                if style == "alternate" and (b + f) % 2:
                    continue
                if style == "rows" and f % 2:
                    continue
                if style == "loggia" and (b + f) % period:
                    continue
                if budget <= 0:
                    break
                t = (b + 0.5) * ln[i] / nb
                cx, cz, yaw = at(i, t, 0.62)
                y0 = f * 3.2 - 0.1
                if (b * 7 + k) % 5 in closed:                          # terrace column closed in by the owners: a room that sticks out
                    out.append(box(cx, cz, 2.3, 1.2, 2.7, y0, closed_col[(b + k) % len(closed_col)], yaw))
                    budget -= 1
                    continue
                badd_ = box(cx, cz, 2.3, 1.2, 0.16, y0, slab, yaw)
                out.append(badd_)
                cx, cz, yaw = at(i, t, 1.17)
                out.append(box(cx, cz, 2.3, 0.07, 0.95, y0 + 0.16, rail, yaw))
                for kind, pr in (("dish", 0.12), ("rack", 0.14), ("antenna", 0.05), ("bike", 0.04)):   # stray dishes, laundry, Y antennas, a bike
                    if rg.random() < pr:
                        cx3, cz3, _y = at(i, t + rg.uniform(-0.6, 0.6), 0.75 if kind != "dish" else 1.05)
                        jp = _junk_piece(kind, cx3, y0 + 0.16, cz3, yaw + rg.uniform(-0.4, 0.4), rg.randrange(1 << 20))
                        if jp:
                            out.append(jp)
                budget -= 2
    ac_p = rg.choice((0.12, 0.25, 0.4, 0.55))                  # air-conditioner density differs per building
    ac_n = 0
    for i in walls_:
        nb = max(1, int(ln[i] // 3.4))
        for b in range(nb):
            for f in range(floors):
                if ac_n < 160 and rg.random() < ac_p:
                    t = (b + rg.choice((0.25, 0.75))) * ln[i] / nb
                    cx, cz, yaw = at(i, t, 0.22)
                    out.append(box(cx, cz, 0.85, 0.42, 0.55, f * 3.2 + rg.uniform(0.9, 1.5), (236, 236, 234), yaw))
                    ac_n += 1
    sty2 = rg.choice(("fins", "bands", "bays", "none", "none"))
    i = walls_[0]
    if sty2 == "fins" and h > 10:                              # vertical concrete fins
        for q in range(2, int(ln[i] // 3.4), 2):
            cx, cz, yaw = at(i, q * ln[i] / max(1, int(ln[i] // 3.4)), 0.4)
            out.append(box(cx, cz, 0.5, 0.8, h + 0.8, 0.0, (170, 166, 158), yaw))
    elif sty2 == "bands" and h > 8:                            # continuous cantilevered slab bands
        for f in range(2, floors, 2):
            cx, cz, yaw = at(i, ln[i] / 2, 0.9)
            out.append(box(cx, cz, ln[i] - 0.4, 1.8, 0.35, f * 3.2 - 0.2, (160, 158, 150), yaw))
    elif sty2 == "bays" and h > 8 and ln[i] > 12:              # projecting bay: two window-widths pushed out the full height
        t = ln[i] * rg.uniform(0.3, 0.7)
        cx, cz, yaw = at(i, t, 1.0)
        out.append(box(cx, cz, 6.4, 2.0, h, 0.0, rg.choice(((196, 186, 168), (178, 98, 72), (214, 210, 200))), yaw))
    if h > 13 and rg.random() < 0.45:                       # lift shaft: a tall box on the wall, poking above the roof
        i = walls_[-1] if len(walls_) > 1 else walls_[0]
        cx, cz, yaw = at(i, ln[i] * rg.uniform(0.25, 0.75), 0.7)
        out.append(box(cx, cz, 2.6, 1.4, h + 2.6, 0.0, tuple(c * 0.92 for c in wallc), yaw))
    if h > 8 and rg.random() < 0.35:                         # fire escape: landings alternating left/right and stair steps
        i = walls_[-1]
        t0 = ln[i] * rg.uniform(0.3, 0.7)
        for f in range(1, floors):
            side = 1 if f % 2 else -1
            cx, cz, yaw = at(i, t0 + side * 0.7, 0.55)
            out.append(box(cx, cz, 1.8, 1.0, 0.1, f * 3.2, dark, yaw))
            for s_ in range(4):
                cx, cz, yaw = at(i, t0 + side * (0.7 - side * 0.5 * 0) - side * (0.6 + s_ * 0.5) * 0 + (-side) * (0.2 + s_ * 0.4), 0.55)
                out.append(box(cx, cz, 0.4, 0.8, 0.08, f * 3.2 + 0.2 + s_ * 0.5, dark, yaw))
    if h > 12:                                                # rooftop leftovers: dishes, Y antennas, laundry, the odd bike
        xs, zs = r[:, 0], r[:, 1]
        for _k in range(rg.randint(2, 5)):
            for _try in range(6):
                px, pz = rg.uniform(xs.min(), xs.max()), rg.uniform(zs.min(), zs.max())
                if _inside_ring(px, pz, ring, 1.2):
                    jp = _junk_piece(rg.choice(("dish", "dish", "antenna", "antenna", "bike", "rack")), px, h, pz, rg.uniform(0, 6.283), rg.randrange(1 << 20))
                    if jp:
                        out.append(jp)
                    break
    if h > 8 and rg.random() < 0.3:                          # janky "added floor": a smaller, differently coloured box on the roof, off-centre
        xs, zs = r[:, 0], r[:, 1]
        cx, cz = (xs.min() + xs.max()) / 2, (zs.min() + zs.max()) / 2
        w_, l_ = (xs.max() - xs.min()), (zs.max() - zs.min())
        for _try in range(6):
            px, pz = cx + rg.uniform(-0.2, 0.2) * w_, cz + rg.uniform(-0.2, 0.2) * l_
            sx, sz = w_ * rg.uniform(0.3, 0.55), l_ * rg.uniform(0.3, 0.55)
            if all(_inside_ring(px + a_ * sx / 2, pz + b_ * sz / 2, ring, 0.8) for a_, b_ in ((1, 1), (-1, -1), (1, -1), (-1, 1))):
                col = rg.choice(((196, 188, 170), (170, 120, 96), (150, 150, 146), (214, 200, 150)))
                for k_ in range(rg.choice((1, 1, 2))):
                    out.append(box(px, pz, sx, sz, 2.9, h + k_ * 2.9, col))
                out.append(box(px, pz, sx + 0.6, sz + 0.6, 0.2, h, (120, 118, 114)))
                break
    if h > 10 and rg.random() < 0.2:                         # brutalist cantilever: a raw concrete block hung on a wall
        i = walls_[0]
        t = ln[i] * rg.uniform(0.3, 0.7)
        cx, cz, yaw = at(i, t, 1.6)
        fl = rg.randrange(2, max(3, floors))
        out.append(box(cx, cz, rg.uniform(4, 7), 3.2, 3.0, fl * 3.2, (150, 148, 142), yaw))
        for dt in (-1.5, 1.5):
            cx2, cz2, yaw2 = at(i, t + dt, 1.0)
            out.append(box(cx2, cz2, 0.5, 0.5, fl * 3.2, 0.0, (132, 130, 126), yaw2))
    return out


def graffiti_geo(ring, h, rng, n_max=2, big=False):
    """Alpha-keyed graffiti quads flat on the street-facing walls of one building -> (pos, uv, col) or None (y relative to the wall foot)."""
    r = np.asarray(ring, dtype=np.float32)
    d = np.roll(r, -1, axis=0) - r
    ln = np.hypot(d[:, 0], d[:, 1])
    order = [i for i in np.argsort(-(ln - 12.0 * (d[:, 0] / np.maximum(ln, 1e-3))))[:5] if ln[i] >= 4.5]      # long walls, south-facing ones first (the camera sees those)
    if not order or h < 3.0:
        return None
    P, U, C = [], [], []
    for i in rng.sample(order, min(len(order), n_max)):
        w = rng.uniform(3.0, 5.6) * (2.0 if big else 1.0) * rng.uniform(1.0, 1.5)       # up to 50% larger
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
        u1, u0 = (cell % GRAF_COLS) / GRAF_COLS + e, (cell % GRAF_COLS + 1) / GRAF_COLS - e       # u runs against the wall direction: seen from outside the text reads left to right
        v0, v1 = (cell // GRAF_COLS) / GRAF_ROWS + e / 6, (cell // GRAF_COLS + 1) / GRAF_ROWS - e / 6
        A, B, Cc, D = (ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)
        P += [A, B, Cc, A, Cc, D]
        U += [(u0, v1), (u1, v1), (u1, v0), (u0, v1), (u1, v0), (u0, v0)]
        sh = int(255 * min(1.0, 0.82 + 0.3 * max(0.0, float(nx * SUN[0] + nz * SUN[2]))))     # paint stays vivid on shaded walls
        C += [(sh, sh, sh, 255)] * 6
    if not P:
        return None
    return np.array(P, np.float32), np.array(U, np.float32), np.array(C, np.uint8)


def roof_graffiti(ring, bb, h, rng, n_max=1):
    """Big graffiti pieces painted flat on a roof, upright for the (north-up) game camera -> (pos, uv, col) or None."""
    bw, bd = bb[2] - bb[0], bb[3] - bb[1]
    P, U, C = [], [], []
    for _ in range(n_max):
        for _try in range(8):
            w = rng.uniform(6.0, 11.0) * rng.uniform(1.0, 1.5)
            hh = w * 0.5
            if w > bw * 0.95 or hh > bd * 0.95:
                continue
            ang = math.radians(rng.uniform(-22, 22))
            ca, sa = math.cos(ang), math.sin(ang)
            cx, cz = rng.uniform(bb[0], bb[2]), rng.uniform(bb[1], bb[3])
            ux, uz, vx, vz = ca, sa, -sa, ca                 # u along the text, v towards the bottom of the picture (south)
            corn = [(cx + ux * a * w / 2 + vx * b * hh / 2, cz + uz * a * w / 2 + vz * b * hh / 2) for a, b in ((-1, 1), (1, 1), (1, -1), (-1, -1))]
            if not all(pip(q, ring) for q in corn + [(cx, cz)]):
                continue
            cell = rng.randrange(GRAF_N)
            e = 3.0 / 1024
            u0, u1 = (cell % GRAF_COLS) / GRAF_COLS + e, (cell % GRAF_COLS + 1) / GRAF_COLS - e
            v0, v1 = (cell // GRAF_COLS) / GRAF_ROWS + e / 6, (cell // GRAF_COLS + 1) / GRAF_ROWS - e / 6
            y = h + 0.07
            A, B, Cc, D = ((q[0], y, q[1]) for q in corn)
            P += [A, B, Cc, A, Cc, D]
            U += [(u0, v1), (u1, v1), (u1, v0), (u0, v1), (u1, v0), (u0, v0)]
            C += [(255, 255, 255, 255)] * 6
            break
    if not P:
        return None
    return np.array(P, np.float32), np.array(U, np.float32), np.array(C, np.uint8)


def pitched_graffiti(ring, h, apex_h, rng):
    """One piece on the south-ish slope of a pyramid roof (the side the game camera sees) -> (pos, uv, col) or None."""
    r = np.asarray(ring, dtype=np.float32)
    cx, cz = float(r[:, 0].mean()), float(r[:, 1].mean())
    d = np.roll(r, -1, axis=0) - r
    ln = np.hypot(d[:, 0], d[:, 1])
    best, bs = -1, -9.0
    for i in range(len(r)):
        if ln[i] < 3.2:
            continue
        nz = -d[i, 0] / ln[i]                                  # outward z of the edge (outward = (dz, -dx)): > 0 faces south, towards the camera
        sc = nz + 0.002 * float(ln[i])
        if sc > bs:
            best, bs = i, sc
    if best < 0:
        return None
    i = best
    w = min(float(ln[i]) * 0.9, 9.0 * rng.uniform(1.0, 1.5))
    s0 = rng.uniform(0.0, float(ln[i]) - w)
    ux, uz = d[i, 0] / ln[i], d[i, 1] / ln[i]
    a = (r[i, 0] + ux * s0, r[i, 1] + uz * s0)
    b = (a[0] + ux * w, a[1] + uz * w)
    dist = math.hypot((a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cz) or 1.0
    L = math.hypot(dist, apex_h)
    t0 = 0.12
    t1 = min(0.8, t0 + (w * 0.5) / L)

    def pt(q, t):
        return (q[0] + (cx - q[0]) * t, h + apex_h * t + 0.05, q[1] + (cz - q[1]) * t)
    A, B, Cc, D = pt(a, t0), pt(b, t0), pt(b, t1), pt(a, t1)
    cell = rng.randrange(GRAF_N)
    e = 3.0 / 1024
    u1, u0 = (cell % GRAF_COLS) / GRAF_COLS + e, (cell % GRAF_COLS + 1) / GRAF_COLS - e   # mirrored along the edge, see graffiti_geo
    v0, v1 = (cell // GRAF_COLS) / GRAF_ROWS + e / 6, (cell // GRAF_COLS + 1) / GRAF_ROWS - e / 6
    P = [A, B, Cc, A, Cc, D]
    U = [(u0, v1), (u1, v1), (u1, v0), (u0, v1), (u1, v0), (u0, v0)]
    return np.array(P, np.float32), np.array(U, np.float32), np.array([(255, 255, 255, 255)] * 6, np.uint8)


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


def mansard(ring, y0, rise, col):
    """Mansard roof: the slopes from the wall top in to an inset ring `rise` higher, and its flat top -> pos, uv, col."""
    r = np.asarray(ring, np.float64)
    n = len(r)
    inset = min(rise * 0.55, 0.3 * min(np.ptp(r[:, 0]), np.ptp(r[:, 1])))
    nin = []
    for i in range(n):
        d = r[(i + 1) % n] - r[i]
        ln = math.hypot(*d) or 1.0
        nin.append(np.array([-d[1], d[0]]) / ln)                  # inward normal (positive-shoelace ring)
    q = []
    for i in range(n):
        m = nin[i - 1] + nin[i]
        den = 1.0 + float(nin[i - 1] @ nin[i])
        q.append(r[i] + (m / den if den > 0.2 else nin[i]) * inset)
    pos, uv, cols = [], [], []
    y1 = y0 + rise
    for i in range(n):
        a, b, qa, qb = r[i], r[(i + 1) % n], q[i], q[(i + 1) % n]
        nrm = np.array([-nin[i][0] * rise, inset, -nin[i][1] * rise])
        nrm /= np.linalg.norm(nrm) or 1.0
        sh = max(0.55, min(1.15, shade(nrm) * 1.05))
        c = (*[min(255, v * sh) for v in col], 255)
        for p_, y in ((a, y0), (b, y0), (qb, y1), (a, y0), (qb, y1), (qa, y1)):
            pos.append((p_[0], y, p_[1]))
            uv.append((p_[0] / 3.0, p_[1] / 3.0 + y))
            cols.append(c)
    try:
        v_, tri = triangulate([tuple(p_) for p_ in q], [])
        fp = flat_poly(v_, tri, y1, 6.0, [c * 1.02 for c in col])
    except Exception:  # noqa: BLE001 - a self-crossing inset: slopes only
        fp = None
    out = (np.array(pos, np.float32), np.array(uv, np.float32), np.array(cols, np.uint8))
    if fp:
        out = tuple(np.concatenate([x, y_]) for x, y_ in zip(out, fp))
    return out


SURF_BASE = {"plas": 0.84, "concw": 0.80, "tilew": 0.86, "brkw": 0.80, "metw": 0.86}     # mean of each texture (gl3d.surface_textures)
GLASS_BASE, PAINT_BASE = 0.26, 0.88


def _depth_in(ring, p, nrm):
    """How deep the outline is from wall point p straight inwards (along -nrm) -> m (6 when nothing is hit)."""
    d = -np.asarray(nrm, float)
    best = None
    n = len(ring)
    for i in range(n):
        a, e = ring[i], ring[(i + 1) % n]
        s_ = e - a
        den = d[0] * s_[1] - d[1] * s_[0]
        if abs(den) < 1e-9:
            continue
        w = a - p
        t = (w[0] * s_[1] - w[1] * s_[0]) / den
        q = (w[0] * d[1] - w[1] * d[0]) / den
        if t > 0.3 and 0 <= q <= 1 and (best is None or t < best):
            best = t
    return float(best) if best else 6.0


def photo_on(fit):
    """Does this fit get the procedural photo facade?  (Inferred buildings can be switched to the plain look.)"""
    if not (fit and fit.get("params") and fit.get("cycle")):
        return False
    return fit.get("src") == "photo" or (fit.get("opts") or {}).get("inferred", "lite") != "none"


OSM_KIT = os.environ.get("SK242_OSM_KIT", "1") != "0"          # the element kit on the buildings without photos


def _sep(p, q):
    """True when convex polygons p, q (x, z lists) do not overlap by more than 2 cm (separating axis)."""
    for poly in (p, q):
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            nx, nz = b[1] - a[1], a[0] - b[0]
            l_ = math.hypot(nx, nz) or 1.0
            pa = [(x * nx + z * nz) / l_ for x, z in p]
            pb = [(x * nx + z * nz) / l_ for x, z in q]
            if min(pa) > max(pb) - 0.02 or min(pb) > max(pa) - 0.02:
                return True
    return False


def _kit_flush(put, fl):
    """The deferred undersides of one building's kit boxes: dropped where another box's top lies in the same plane (a lid on a
    roof room, stacked tiers), which would z-fight with it."""
    by_y = {}
    for ty, tw in fl["top"]:
        by_y.setdefault(int(round(ty * 50)), []).append(tw)
    for mt, w4, y0, col in fl["bot"]:
        k = int(round(y0 * 50))
        if not any(not _sep(w4, tw) for kk in (k - 1, k, k + 1) for tw in by_y.get(kk, ())):
            put(mt, [(p_[0], y0, p_[1]) for p_ in w4[::-1]], [(0.6, 0.2)] * 4, col)
    sides = {}
    for f in fl["side"]:
        sides.setdefault(f[0], []).append(f)
    for (ka, ko), lst in sides.items():
        near_ = [g for kk in ((ka, ko - 1), (ka, ko), (ka, ko + 1)) for g in sides.get(kk, ())]
        for f in lst:
            _k, sg, u0, u1, y0, y1, mt, pts, col = f
            if not any(g[1] != sg and g[2] <= u0 + 0.01 and g[3] >= u1 - 0.01 and g[4] <= y0 + 0.01 and g[5] >= y1 - 0.01 for g in near_):
                put(mt, pts, [(0.6, 0.2)] * 4, col)                   # a side against an opposite side covering it: inside the pair
    fl["bot"], fl["top"], fl["side"] = [], [], []


def _kit_faces(put, mt, cx, cz, sx, sz, hh, y0, col, yw, wall, y_bot, fl=None):
    """One kit box as quads: on a wall without the face against the wall, with an underside when it hangs above y_bot (the
    ground for wall pieces, the roof for roof pieces).  fl: {"top": [], "bot": []} defers the undersides to _kit_flush."""
    ca, sa = math.cos(yw), math.sin(yw)
    w4 = [(cx + ca * x - sa * z, cz + sa * x + ca * z) for x, z in ((-sx / 2, -sz / 2), (sx / 2, -sz / 2), (sx / 2, sz / 2), (-sx / 2, sz / 2))]
    if wall and sz <= 0.035:                                          # a flat piece on the wall (joint, band, stain): its front only,
        a_, b_ = [(p_[0] + sa * 0.02, p_[1] - ca * 0.02) for p_ in w4[:2]]     # 2 cm further out: at 1-3 cm it z-fought the wall far off
        put(mt, [(a_[0], y0, a_[1]), (b_[0], y0, b_[1]), (b_[0], y0 + hh, b_[1]), (a_[0], y0 + hh, a_[1])], [(0.6, 0.2)] * 4, col)
        return
    for k_ in range(4):
        if wall and k_ == 2:                                          # local +z = into the wall
            continue
        a_, b_ = w4[k_], w4[(k_ + 1) % 4]
        nx, nz = b_[1] - a_[1], -(b_[0] - a_[0])
        l_ = math.hypot(nx, nz) or 1.0
        shd = float(np.clip(0.52 + 0.55 * max(0.0, (nx * SUN[0] + nz * SUN[2]) / l_), 0.45, 1.12))
        pts = [(a_[0], y0, a_[1]), (b_[0], y0, b_[1]), (b_[0], y0 + hh, b_[1]), (a_[0], y0 + hh, a_[1])]
        if fl is None:
            put(mt, pts, [(0.6, 0.2)] * 4, [c * shd for c in col])
            continue
        nx, nz = nx / l_, nz / l_                                     # side faces wait for _kit_flush: abutting boxes' touching sides go
        sg = 1 if (nx > 1e-6 or (abs(nx) <= 1e-6 and nz > 0)) else -1
        cnx, cnz = nx * sg, nz * sg
        ua, ub = a_[0] * cnz - a_[1] * cnx, b_[0] * cnz - b_[1] * cnx
        fl["side"].append(((round(math.atan2(cnz, cnx) * 500), round((a_[0] * cnx + a_[1] * cnz) * 100)), sg, min(ua, ub), max(ua, ub),
                           y0, y0 + hh, mt, pts, [c * shd for c in col]))
    tp = float(np.clip(0.52 + 0.55 * SUN[1], 0.45, 1.12))
    put(mt, [(p_[0], y0 + hh, p_[1]) for p_ in w4], [(0.6, 0.2)] * 4, [c * tp for c in col])
    if fl is not None:
        fl["top"].append((y0 + hh, w4))
    if y0 > y_bot + (0.3 if wall else 0.02):                          # not on the roof's plane either: that z-fights
        if fl is not None:
            fl["bot"].append((mt, w4, y0, [c * 0.55 for c in col]))
        else:
            put(mt, [(p_[0], y0, p_[1]) for p_ in w4[::-1]], [(0.6, 0.2)] * 4, [c * 0.55 for c in col])


# mean colour of each facade texture (gl3d.build_textures, measured 2026-11-12): a textured wall shows tint x this / 255, so the
# kit's pieces in "the wall's colour" use that, not the bare tint
TEX_MEAN = {0: (179, 176, 169), 1: (130, 153, 164), 4: (154, 155, 153), 5: (204, 187, 171), 7: (174, 106, 87), 8: (153, 135, 121),
            9: (142, 148, 135), 10: (188, 188, 181), 11: (176, 158, 150)}


def osm_kit(outer, h, mat, wallc, fh, bw, y_bot, seed, ar, small, ids=None, hide=None):
    """src/archkit.py elements on a building without photos: its archetype from the world's facade material and size, one pick
    per element group from its own seed, placed on the texture's tile grid (bays of the wall / floor lines) -> [(material, pos, uv,
    col)].  Silhouette and rhythm go to "glaz", relief and clutter to MAT_KIT2 / MAT_KIT3 (left out by the detail setting)."""
    import archkit
    if ids is None:
        ids = archkit.osm_ids(archkit.osm_archetype(mat, h, ar, small), seed)
    if not ids:
        return []
    acc = {}

    def put(mt, pts, uvs, col):
        e_ = acc.setdefault(mt, ([], [], []))
        c = (*[int(min(255, max(0, v))) for v in col], 255)
        for k in (0, 1, 2, 0, 2, 3):
            e_[0].append(pts[k])
            e_[1].append(uvs[k])
            e_[2].append(c)
    KMAT = (MAT_SURF["glaz"], MAT_SURF["glaz"], MAT_KIT2, MAT_KIT3)
    wallc = tuple(w_ * t_ / 255.0 for w_, t_ in zip(wallc, TEX_MEAN.get(mat, (176, 172, 166))))
    r = np.asarray(outer, np.float64)
    n = len(r)
    longest = max(range(n), key=lambda j: float(np.hypot(*(r[(j + 1) % n] - r[j])))) if n else 0
    floors = max(1, round((h - y_bot) / fh))
    fh_ = (h - y_bot) / floors
    fams = [(e, archkit.BY_ID[e][1]) for e in ids]
    nbox = 0
    fl = {"top": [], "bot": [], "side": []}
    for i in range(n):
        a, b = r[i], r[(i + 1) % n]
        ln = float(np.hypot(*(b - a)))
        if ln < 1.5 or _hide_edge(hide, i, ln, 0.5) > y_bot + 0.3:     # a party wall (party_walls): nothing on it
            continue
        t_ = (b - a) / ln
        nrm = np.array([t_[1], -t_[0]])
        yaw = math.atan2(t_[1], t_[0])
        nb = max(1, round(ln / bw))
        W = {"a": a, "ln": ln, "h": h, "fh": fh_, "pv": y_bot, "y_bot": y_bot, "cols": [(ln * j / nb, ln * (j + 1) / nb) for j in range(nb)],
             "D": lambda u, y: 0.0, "wins": [None] * nb, "balc": [False] * nb, "loggia": [False] * nb, "bdep": [0.9] * nb,
             "wallc": tuple(wallc), "longest": i == longest, "accent": [tuple(v * 0.8 for v in wallc)]}
        for eid, fam in fams:
            if archkit.FAMILIES[fam][2] != "wall" or nbox >= archkit.MAX_BOXES:
                continue
            if fam in ("shopfront", "canopy", "tower", "pilotis") and i != longest:
                continue                                            # one street front per building
            tr_ = archkit.TIER[fam]
            for it in archkit.kit_wall([eid], W)[:archkit.MAX_BOXES - nbox]:
                u_, o_, ky0, su_, sd_, hh_, rgb_ = it[:7]
                cx, cz = a + t_ * u_ + nrm * o_
                _kit_faces(put, KMAT[tr_], cx, cz, su_, sd_, hh_, ky0, [c / PAINT_BASE for c in rgb_], yaw + (it[7] if len(it) > 7 else 0.0),
                           len(it) == 7, y_bot, fl)
                nbox += 1
    if not small:
        for eid, fam in fams:
            if archkit.FAMILIES[fam][2] != "roof":
                continue
            for x_, z_, ky0, sx_, sz_, hh_, rgb_, yw_ in archkit.kit_roof([eid], r, h, wallc, None):
                _kit_faces(put, KMAT[archkit.TIER[fam]], x_, z_, sx_, sz_, hh_, ky0, [c / PAINT_BASE for c in rgb_], yw_, False, h, fl)
    _kit_flush(put, fl)
    return [(m_, np.array(P_, np.float32), np.array(U_, np.float32), np.array(C_, np.uint8)) for m_, (P_, U_, C_) in acc.items() if P_]


def photo_facade(outer, h, fit, y_bot0=0.0, hide=None):
    """Walls of a photo-fitted building (src/photogram.py ДЕТАЛИ), all procedural from the fitted numbers: every wall cut into its
    bay columns x floors; each cell a wall surface (plaster / concrete / tiles / brick / metal texture in the photo's colour) with a
    recessed window (reveals, glass, frame, glazing bars, blind, sill) or a loggia, balcony slab and parapet or railing, AC units.
    Walls the photos did not see repeat the building's own columns.  Inferred buildings (no photo of their own) get the lighter
    set (no frames, bars, sills, posts or AC).  -> [(material, pos, uv, col)]."""
    params, cyc = fit.get("params") or [], fit.get("cycle") or []
    if not params or not cyc:
        return []
    op = fit.get("opts") or {}                                     # the builder's element switches (photoview ЕЛЕМЕНТИ tab)

    def on(k):
        return bool(op.get(k, True))
    full = fit.get("src") == "photo" or op.get("inferred", "lite") == "full"
    import archkit
    kit = archkit.kit_ids(fit, op) if on("kit_on") else []
    sat = float(op.get("sat", 1.0))                                # colour strength (1 = as measured)

    def satc(c_):
        if abs(sat - 1.0) < 1e-3:
            return tuple(c_)
        m_ = sum(c_) / 3.0
        return tuple(float(min(255, max(0, m_ + (v - m_) * sat))) for v in c_)
    nbox = [0]
    fh0, bw0 = max(2.4, fit.get("floor", 3.2)), max(2.0, fit.get("bay", 3.4))
    seen = fit.get("walls") or []
    r = np.asarray(outer, np.float64)
    n = len(r)
    acc = {}

    def put(mat, pts, uvs, col):
        e_ = acc.setdefault(mat, ([], [], []))
        c = (*[int(min(255, max(0, v))) for v in col], 255)
        for k in (0, 1, 2, 0, 2, 3):
            e_[0].append(pts[k])
            e_[1].append(uvs[k])
            e_[2].append(c)

    def put_box(mat, cx, cz, sx, sz, hh, y0, col, yaw, uv=(0.75, 0.5)):
        pos, _uv, cl = box(cx, cz, sx, sz, hh, y0, col, yaw)
        e_ = acc.setdefault(mat, ([], [], []))
        e_[0].extend(map(tuple, pos))
        e_[1].extend([uv] * len(pos))
        e_[2].extend(map(tuple, cl))

    KMAT = (MAT_SURF["glaz"], MAT_SURF["glaz"], MAT_KIT2, MAT_KIT3)

    kfl = {"top": [], "bot": [], "side": []}

    def kbox(cx, cz, sx, sz, hh, y0, col, yw, tier=1, wall=False, yb=None):
        _kit_faces(put, KMAT[tier], cx, cz, sx, sz, hh, y0, col, yw, wall, y_bot if yb is None else yb, kfl)
    longest = max(range(n), key=lambda j: float(np.hypot(*(r[(j + 1) % n] - r[j])))) if n else 0
    for i in range(n):
        a, b = r[i], r[(i + 1) % n]
        d = b - a
        ln = float(math.hypot(*d))
        y_bot = max(y_bot0, _hide_edge(hide, i, ln))               # a party wall (party_walls): only above the neighbour
        if ln < 0.15 or y_bot >= h - 0.3:
            continue
        t_ = d / ln
        nrm = np.array([t_[1], -t_[0]])                            # outward
        yaw = math.atan2(t_[1], t_[0])
        sh = float(np.clip(0.52 + 0.55 * max(0.0, float(np.array([nrm[0], 0, nrm[1]]) @ SUN)), 0.45, 1.12))
        w = next((w for w in seen if np.hypot(*(np.array(w["a"]) - a)) < 1.5 and np.hypot(*(np.array(w["b"]) - b)) < 1.5), None)
        opp = None
        if not w and fit.get("opp", True) and on("opp"):   # an unseen wall facing a seen one of about its length: the seen one's order, front to back
            par = [s_ for s_ in seen if 0.6 < ln / max(0.1, s_["ln"]) < 1.6
                   and float((np.array(s_["b"]) - np.array(s_["a"])) @ t_) / max(0.1, s_["ln"]) < -0.85]
            opp = max(par, key=lambda s_: s_["ln"]) if par else None
        bands, gf = [], None
        if w or opp:
            src_ = w or opp
            k = ln / max(0.1, src_["ln"])
            cols = [(c[0] * k, c[1] * k, c[2], c[4] if len(c) > 4 else -1, c[5] if len(c) > 5 else 0.0) for c in src_["cols"]]
            if opp:
                cols = [(ln - c1, ln - c0, pi_, -1, d_) for c0, c1, pi_, _g, d_ in reversed(cols)]
            fh, pv, ref = src_["fh"], src_["pv"] % src_["fh"], src_.get("shade", 0.85)
            cells = src_.get("cells", {}) if w else {}
            wallc, surf = src_["wall"], src_.get("surf", fit.get("surf", "plas"))
            bands = src_.get("bands") or []
            gf = src_.get("gf") if w else None
            secs = src_.get("secs") or [] if w else []
        else:
            nb = max(1, int(round(ln / bw0)))
            cols = [(ln * j / nb, ln * (j + 1) / nb, cyc[(j + i * 3) % len(cyc)], -1, 0.0) for j in range(nb)]
            fh, pv, ref, cells = fh0, 0.0, 0.85, {}
            wallc, surf = fit.get("wallc", (200, 200, 200)), fit.get("surf", "plaster")
            secs = []
        wallc = satc(wallc)
        if sat != 1.0 and cells:
            cells = {k_: satc(v_) for k_, v_ in cells.items()}
        if not on("relief"):
            cols = [(c0, c1, pi_, g_, 0.0) for c0, c1, pi_, g_, _d in cols]
            gf = None
        if not on("ground"):
            gf = None
            cols = [(c0, c1, pi_, -1, d_) for c0, c1, pi_, _g, d_ in cols]
        if not on("bands"):
            bands = []
        if not on("cells"):
            cells = {}
        # lower roof-line sections: their upper storeys stand back (a set-back / a lower wing in front), the depth half the plan's
        steps_ = []
        if on("steps") and w:
            for su0, su1, sh_, sb_, *_r in secs:
                wt_ = sh_ - sb_
                if wt_ < h - 1.0 and su1 - su0 >= 2.0 and wt_ > 2.5:
                    mid = a + t_ * (su0 + su1) / 2
                    steps_.append((su0 * k, su1 * k, wt_, -min(6.0, 0.45 * _depth_in(r, mid, nrm))))
        lit = float(np.clip(sh / ref, 0.72, 1.18))
        glassy = surf == "glass"
        smat = {"plaster": "plas", "concrete": "concw", "tiles": "tilew", "brick": "brkw", "metal": "metw", "glass": "metw"}.get(surf, "plas")
        MS, MG = MAT_SURF[smat], MAT_SURF["glaz"]
        base = SURF_BASE[smat]

        off = [0.0]                                                # the current cell's depth out of (+) / into (-) the OSM wall

        def N(dd):
            return nrm * (dd + off[0])

        def P(u, y, dd=0.0):
            q = a + t_ * u + N(dd)
            return (float(q[0]), float(y), float(q[1]))

        def wall_rect(u0, u1, y0, y1, col):
            if u1 - u0 < 0.01 or y1 - y0 < 0.01:
                return
            put(MS, [P(u0, y0), P(u1, y0), P(u1, y1), P(u0, y1)], [(u0 / 4, -y0 / 4), (u1 / 4, -y0 / 4), (u1 / 4, -y1 / 4), (u0 / 4, -y1 / 4)],
                [c * lit / base for c in col])

        def paint(pts, col, k_=1.0, mt=None):
            put(mt or MG, pts, [(0.6, 0.2), (0.9, 0.2), (0.9, 0.8), (0.6, 0.8)], [c * lit * k_ / PAINT_BASE for c in col])

        cuts = [y_bot] + [pv + k_ * fh for k_ in range(int(math.ceil(h / fh)) + 1) if y_bot < pv + k_ * fh < h - 0.05] + [h]
        cuts = sorted(set(cuts + [st_[2] for st_ in steps_ if y_bot < st_[2] < h - 0.05]))

        def setback(u0, u1, y0):
            return next((st_[3] for st_ in steps_ if st_[0] <= (u0 + u1) / 2 < st_[1] and y0 >= st_[2] - 0.01), 0.0)
        gcols = set(gf["cols"]) if gf else set()
        # Skopje has no hollow volumes: above the ground storey a wall may stand back by a reveal or a shallow loggia only (a deeper
        # recess leaves the roof slab overhanging empty air, the glass-facade-over-void look); the arcade below keeps its depth
        Dg = [[(max(-1.5, d_ + setback(_u0, _u1, y0)) + (gf["d"] if ci in gcols and y1 <= gf["y"] + 0.05 else 0.0)) for y0, y1 in zip(cuts[:-1], cuts[1:])]
              for ci, (_u0, _u1, _pi, _g, d_) in enumerate(cols)]
        for ci, (u0, u1, pi, gpi, _d) in enumerate(cols):
            if pi >= len(params) or u1 - u0 < 0.05:
                continue
            cw = u1 - u0
            for bi, (y0, y1) in enumerate(zip(cuts[:-1], cuts[1:])):
                off[0] = Dg[ci][bi]
                p = params[gpi] if (0 <= gpi < len(params) and y0 <= 1.5 < y1) else params[pi]   # the ground storey's own look
                fl = int(math.floor((y0 + 1e-3 - pv) / fh))
                wc = cells.get(f"{ci},{fl}", wallc) if w else wallc
                if glassy:
                    wc = p.get("frame") or (70, 76, 82)
                fullcell = y1 - y0 > 0.95 * fh and y0 > 0.05
                win = p.get("win") if on("windows") else None
                if glassy and fullcell:
                    win = [0.03, 0.97, 0.06, 0.96]
                if not fullcell or not win:
                    wall_rect(u0, u1, y0, y1, wc)
                    continue
                wx0, wx1 = u0 + win[0] * cw, u0 + win[1] * cw
                wy0, wy1 = y0 + win[2] * fh, y0 + win[3] * fh
                rec = 0.05 if glassy else float(p.get("rec", 0.18))
                wall_rect(u0, wx0, y0, y1, wc)
                wall_rect(wx1, u1, y0, y1, wc)
                wall_rect(wx0, wx1, y0, wy0, wc)
                wall_rect(wx0, wx1, wy1, y1, wc)
                rc = [c * (0.62 if rec > 0.5 else 0.86) for c in wc]          # reveals (a loggia's walls are in shade)
                for pts in ((P(wx0, wy0), P(wx0, wy0, -rec), P(wx0, wy1, -rec), P(wx0, wy1)),
                            (P(wx1, wy1), P(wx1, wy1, -rec), P(wx1, wy0, -rec), P(wx1, wy0)),
                            (P(wx1, wy0), P(wx1, wy0, -rec), P(wx0, wy0, -rec), P(wx0, wy0)),
                            (P(wx0, wy1), P(wx0, wy1, -rec), P(wx1, wy1, -rec), P(wx1, wy1))):
                    put(MS, list(pts), [(0, 0), (rec / 4, 0), (rec / 4, 0.3), (0, 0.3)], [c * lit / base for c in rc])
                g = p.get("glass") or (70, 80, 92)
                gd = -rec + 0.02
                put(MG, [P(wx0, wy0, gd), P(wx1, wy0, gd), P(wx1, wy1, gd), P(wx0, wy1, gd)],
                    [(0.05, 0.95), (0.45, 0.95), (0.45, 0.05), (0.05, 0.05)], [c * lit / (GLASS_BASE * 255) * 255 for c in g])
                bl = p.get("blind")
                if bl and not glassy and on("blinds"):                                          # blind / roller shutter, down from the top
                    yb = wy1 - bl[0] * (wy1 - wy0)
                    paint([P(wx0, yb, gd + 0.04), P(wx1, yb, gd + 0.04), P(wx1, wy1, gd + 0.04), P(wx0, wy1, gd + 0.04)], bl[1:], 0.97)
                fc = p.get("frame") or (236, 236, 232)
                fw, fd = 0.06, gd + 0.07                                  # glass, blind, frame, bars: 3 cm apart (no flicker far off)
                if full and on("frames"):
                    for (x0_, x1_, y0_, y1_) in ((wx0, wx0 + fw, wy0, wy1), (wx1 - fw, wx1, wy0, wy1),
                                                 (wx0, wx1, wy0, wy0 + fw), (wx0, wx1, wy1 - fw, wy1)):
                        paint([P(x0_, y0_, fd), P(x1_, y0_, fd), P(x1_, y1_, fd), P(x0_, y1_, fd)], fc, 1.0, MAT_KIT2)
                    nm = 1 if glassy else int(p.get("mull", 0))
                    for m_ in range(1, nm + 1):                                 # glazing bars
                        xm = wx0 + (wx1 - wx0) * m_ / (nm + 1)
                        paint([P(xm - 0.025, wy0, fd + 0.02), P(xm + 0.025, wy0, fd + 0.02), P(xm + 0.025, wy1, fd + 0.02), P(xm - 0.025, wy1, fd + 0.02)], fc, 1.0, MAT_KIT2)
                    if wy1 - wy0 > 1.6:                                          # transom of a tall (door) opening
                        yt = wy0 + (wy1 - wy0) * 0.72
                        paint([P(wx0, yt - 0.025, fd + 0.02), P(wx1, yt - 0.025, fd + 0.02), P(wx1, yt + 0.025, fd + 0.02), P(wx0, yt + 0.025, fd + 0.02)], fc, 1.0, MAT_KIT2)
                if full and p.get("sill") and not glassy and on("sills"):
                    cx, cz = a + t_ * (wx0 + wx1) / 2 + N(0.03)
                    put_box(MAT_KIT2, cx, cz, wx1 - wx0 + 0.1, 0.16, 0.05, wy0 - 0.05, [c * lit * 1.02 / PAINT_BASE for c in wc], yaw)
                if full and on("ac"):
                    for fx, cy, aw, ah, *cc in p.get("ac", []):                # AC units with a dark fan grille
                        cu = u0 + fx * cw
                        cx, cz = a + t_ * cu + N(0.18)
                        yb_ = y0 + cy - ah / 2
                        put_box(MAT_KIT3, cx, cz, aw, 0.35, ah, yb_, [c * lit / PAINT_BASE for c in cc], yaw)
                        gr = ah * 0.32
                        paint([P(cu - gr - aw * 0.12, yb_ + ah / 2 - gr, 0.38), P(cu + gr - aw * 0.12, yb_ + ah / 2 - gr, 0.38),
                               P(cu + gr - aw * 0.12, yb_ + ah / 2 + gr, 0.38), P(cu - gr - aw * 0.12, yb_ + ah / 2 + gr, 0.38)], (58, 60, 62), 1.0, MAT_KIT3)
                bc = p.get("balc")
                if bc and not glassy and on("balconies"):                                           # balcony: slab + parapet or railing
                    dep, rc_, solid = bc[0], satc(bc[1:4]), (bc[4] if len(bc) > 4 else 1) or not full
                    cx, cz = a + t_ * (u0 + u1) / 2 + N(dep / 2)
                    bw_ = cw * 0.96
                    put_box(MG, cx, cz, bw_, dep, 0.16, y0, [c * lit * 0.95 / PAINT_BASE for c in wc], yaw)
                    if solid:
                        ox, oz = a + t_ * (u0 + u1) / 2 + N(dep - 0.04)
                        put_box(MG, ox, oz, bw_, 0.08, 0.92, y0 + 0.16, [c * lit / PAINT_BASE for c in rc_], yaw)
                        for su in (u0 + (cw - bw_) / 2 + 0.04, u1 - (cw - bw_) / 2 - 0.04):
                            sx_, sz_ = a + t_ * su + N(dep / 2)
                            put_box(MG, sx_, sz_, 0.08, dep - 0.1, 0.9, y0 + 0.16, [c * lit * 0.94 / PAINT_BASE for c in rc_], yaw)
                    else:
                        ox, oz = a + t_ * (u0 + u1) / 2 + N(dep - 0.03)
                        put_box(MG, ox, oz, bw_, 0.06, 0.06, y0 + 1.0, [c * lit / PAINT_BASE for c in rc_], yaw)
                        put_box(MG, ox, oz, bw_, 0.04, 0.04, y0 + 0.24, [c * lit / PAINT_BASE for c in rc_], yaw)
                        nposts = max(2, int(bw_ / 0.14))
                        for k_ in range(nposts + 1):
                            pu = u0 + (cw - bw_) / 2 + bw_ * k_ / nposts
                            px_, pz_ = a + t_ * pu + N(dep - 0.03)
                            put_box(MG, px_, pz_, 0.025, 0.025, 0.84, y0 + 0.16, [c * lit * 0.9 / PAINT_BASE for c in rc_], yaw)
        # ---- the wall's relief: side faces where neighbouring columns stand at different depths (and at the wall's ends when
        # a column stands out), caps / soffits where a column's depth changes between storeys and at the wall top
        off[0] = 0.0

        def lit_n(nv):
            return float(np.clip(float(np.clip(0.52 + 0.55 * max(0.0, float(np.array([nv[0], 0, nv[1]]) @ SUN)), 0.45, 1.12)) / ref, 0.6, 1.25))

        def relief(pts, nv, col):
            put(MS, pts, [(0, 0), (0.1, 0), (0.1, 0.5), (0, 0.5)], [c * lit_n(nv) / base for c in col])

        nc = len(cols)
        for bi, (y0, y1) in enumerate(zip(cuts[:-1], cuts[1:])):
            for ci in range(-1, nc):
                dl = Dg[ci][bi] if ci >= 0 else 0.0
                dr_ = Dg[ci + 1][bi] if ci + 1 < nc else 0.0
                u = cols[ci][1] if ci >= 0 else cols[0][0]
                if (ci < 0 and dr_ <= 0.02) or (ci + 1 >= nc and dl <= 0.02) or abs(dl - dr_) < 0.02:
                    continue
                relief([P(u, y0, dl), P(u, y0, dr_), P(u, y1, dr_), P(u, y1, dl)], t_ if dl > dr_ else -t_, wallc)
        for ci, (u0, u1, *_r) in enumerate(cols):
            for bi in range(len(cuts) - 1):
                y = cuts[bi + 1]
                lo_ = Dg[ci][bi]
                up_ = Dg[ci][bi + 1] if bi + 1 < len(cuts) - 1 else 0.0
                if abs(lo_ - up_) < 0.02:
                    continue
                if bi + 1 == len(cuts) - 1 and lo_ < 0:              # under the roof's edge over a recessed top
                    up_ = 0.0
                inner, outer = min(lo_, up_), max(lo_, up_)
                if lo_ > up_:
                    put(MS, [P(u0, y, inner), P(u1, y, inner), P(u1, y, outer), P(u0, y, outer)], [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)],
                        [c * 1.05 / base for c in wallc])
                else:
                    ys = y - 0.05 if bi + 1 == len(cuts) - 1 else y         # under the roof slab, not in its plane
                    put(MS, [P(u0, ys, outer), P(u1, ys, outer), P(u1, ys, inner), P(u0, ys, inner)], [(0, 0), (0.1, 0), (0.1, 0.1), (0, 0.1)],
                        [c * 0.55 / base for c in wallc])
        # ---- horizontal elements: plinth, string courses, cornice (following the columns' depths)
        for kind_, by0, by1, dep, *bc in bands:
            if by1 > h + 0.3:
                continue
            bi = max(0, min(len(cuts) - 2, sum(1 for c_ in cuts[1:-1] if c_ <= by0)))
            for ci, (u0, u1, *_r) in enumerate(cols):
                cx, cz = a + t_ * (u0 + u1) / 2 + nrm * (Dg[ci][bi] + dep / 2)
                put_box(MG, cx, cz, u1 - u0, dep, by1 - by0 if kind_ != "plinth" else by1 - y_bot, by0 if kind_ != "plinth" else y_bot,
                        [c * lit / PAINT_BASE for c in satc(bc)], yaw)
        if gf and gf.get("pil") and y_bot <= y_bot0 + 0.01:                                         # arcade pillars on the line of the wall above
            for pu in gf["pil"]:
                ci = next((j for j, c_ in enumerate(cols) if c_[0] <= pu < c_[1]), 0)
                cx, cz = a + t_ * pu + nrm * (cols[ci][4] - 0.22)
                put_box(MG, cx, cz, 0.42, 0.42, gf["y"] - y_bot, y_bot, [c * lit / PAINT_BASE for c in wallc], yaw)
        if kit and nbox[0] < archkit.MAX_BOXES and y_bot <= y_bot0 + 0.3:   # the element kit (src/archkit.py) on this wall
            def D_(u, y, cols=cols, Dg=Dg, cuts=cuts):
                ci = next((j for j, c_ in enumerate(cols) if u < c_[1]), len(cols) - 1)
                bi = max(0, min(len(cuts) - 2, sum(1 for c_ in cuts[1:-1] if c_ <= y)))
                return max(0.0, Dg[ci][bi]) if ci >= 0 else 0.0
            pp = [params[c_[2]] if 0 <= c_[2] < len(params) else {} for c_ in cols]
            cand = [tuple(v) for v in cells.values()] + [tuple(q["balc"][1:4]) for q in pp if q.get("balc")] + [tuple(b_[4:7]) for b_ in bands if len(b_) >= 7]
            cand = sorted({c_ for c_ in cand if len(c_) == 3}, key=lambda c_: -(max(c_) - min(c_)))
            accent = [satc(c_) for c_ in cand if max(c_) - min(c_) > 22 and sum(abs(x - y) for x, y in zip(c_, wallc)) > 40][:2]
            Wk = {"a": a, "ln": ln, "h": h, "fh": fh, "pv": pv, "y_bot": y_bot, "cols": [(c_[0], c_[1]) for c_ in cols], "D": D_,
                  "wins": [q.get("win") if q.get("win") and not glassy else None for q in pp],
                  "balc": [bool(q.get("balc")) for q in pp], "bdep": [float(q["balc"][0]) if q.get("balc") else 0.9 for q in pp], "loggia": [q.get("rec", 0) > 0.5 for q in pp],
                  "wallc": wallc, "longest": i == longest, "accent": accent or [tuple(v * 0.8 for v in wallc)]}
            for eid_ in kit:
                if archkit.FAMILIES[archkit.BY_ID[eid_][1]][2] != "wall" or nbox[0] >= archkit.MAX_BOXES:
                    continue
                tr_ = archkit.TIER[archkit.BY_ID[eid_][1]]
                for it in archkit.kit_wall([eid_], Wk)[:max(0, archkit.MAX_BOXES - nbox[0])]:
                    u_, o_, ky0, su_, sd_, hh_, rgb_ = it[:7]
                    cx, cz = a + t_ * u_ + nrm * o_
                    kbox(cx, cz, su_, sd_, hh_, ky0, [c * lit / PAINT_BASE for c in rgb_], yaw + (it[7] if len(it) > 7 else 0.0), tr_, len(it) == 7)
                    nbox[0] += 1
    if kit and nbox[0] < archkit.MAX_BOXES:
        for eid_ in kit:
            tr_ = archkit.TIER[archkit.BY_ID[eid_][1]]
            for x_, z_, ky0, sx_, sz_, hh_, rgb_, yw_ in archkit.kit_roof([eid_], r, h, fit.get("wallc", (200, 200, 200)), fit.get("roof")):
                kbox(x_, z_, sx_, sz_, hh_, ky0, [c / PAINT_BASE for c in rgb_], yw_, tr_, yb=h)
    _kit_flush(put, kfl)
    return [(m_, np.array(P_, np.float32), np.array(U_, np.float32), np.array(C_, np.uint8)) for m_, (P_, U_, C_) in acc.items() if P_]


ROOF_KINDS = ("flat", "shed", "gable", "hip", "pyramid", "mansard", "gambrel", "halfhip")


def _roof_too_steep(outer, rf, max_deg=20.0):
    """True when a fitted pitched roof is steeper than max_deg (rise over the half of the footprint's narrow side) or is a mansard / gambrel."""
    kind = rf.get("kind")
    if kind in (None, "flat"):
        return False
    if kind in ("mansard", "gambrel"):
        return True
    rise = float(rf.get("rise", 0.0))
    r = np.asarray(outer, np.float64)
    best = None
    for i in range(len(r)):                                    # narrow side of the minimum-width bounding rectangle
        d = r[(i + 1) % len(r)] - r[i]
        ln = float(np.hypot(*d))
        if ln < 1e-6:
            continue
        u = d / ln
        v = np.array([-u[1], u[0]])
        wv = float((r @ v).max() - (r @ v).min())
        best = wv if best is None else min(best, wv)
    if not best:
        return False
    run = best if kind == "shed" else best / 2.0
    return math.degrees(math.atan2(rise, run)) > max_deg


def photo_roof(outer, h, fit, roofc, wallc):
    """The fitted roof (src/photogram.py roof_shape) through src/archlib.py: roof pieces, gable walls, fascia, downpipes,
    chimneys, housings -> [(material, pos, uv, col)] or None when the fit has no roof of a known kind."""
    import archlib
    rf = dict(fit.get("roof") or {})
    op = fit.get("opts") or {}
    if not op.get("roofs", True):                                    # the builder's switches: plain flat roofs
        return None
    if not op.get("roof_extras", True):
        rf["chim"], rf["hous"] = [], []
    if not op.get("eaves", True):
        rf["eave"] = 0.0
    if rf.get("kind") == "pitched":                                  # older fits
        rf["kind"] = "hip"
    if rf.get("kind") not in ROOF_KINDS:
        return None
    m = archlib.roof_mesh(outer, h, rf, roofc, wallc, triangulate)
    if m is None:
        return None
    smat = {"plaster": "plas", "concrete": "concw", "tiles": "tilew", "brick": "brkw", "metal": "metw"}.get(fit.get("surf"), "plas")
    out = []
    for part, mat, k in (("roof", MAT_ROOF, 1.0), ("wall", MAT_SURF[smat], 1.0 / SURF_BASE[smat]), ("solid", MAT_SOLID, 1.0)):
        pos, col = m[part]
        if not pos:
            continue
        P_ = np.array(pos, np.float32)
        C_ = np.array(col, np.float32)
        C_[:, :3] = np.clip(C_[:, :3] * k, 0, 255)
        U_ = np.stack([(P_[:, 0] + P_[:, 2]) / (3.0 if part == "roof" else 4.0), (P_[:, 1] if part != "roof" else P_[:, 2]) / -4.0], 1)
        if part == "roof":
            U_ = np.stack([P_[:, 0] / 3.0, P_[:, 2] / 3.0 + P_[:, 1] / 3.0], 1)
        out.append((mat, P_, U_.astype(np.float32), C_.astype(np.uint8)))
    return out


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


def seg_grid(segs, cell=30.0):
    """segs [(ax, ay, bx, by, r)] -> grid for near_seg."""
    g = {}
    for sg in segs:
        ax, ay, bx, by, r = sg
        for gx in range(int((min(ax, bx) - r) // cell), int((max(ax, bx) + r) // cell) + 1):
            for gy in range(int((min(ay, by) - r) // cell), int((max(ay, by) + r) // cell) + 1):
                g.setdefault((gx, gy), []).append(sg)
    return g


def near_seg(g, x, y, extra=0.0, cell=30.0):
    """(distance - r) of the closest segment within reach, or None: negative means inside a segment's corridor."""
    best = None
    for ax, ay, bx, by, r in g.get((int(x // cell), int(y // cell)), ()):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
        d = math.hypot(x - ax - dx * t, y - ay - dy * t) - r - extra
        if best is None or d < best[0]:
            best = (d, ax + dx * t, ay + dy * t, r, dx, dy)
    return best


def clip_ring(ring, g):
    """Push the parts of a building outline that lie over road asphalt or pavement (corridor segments in g) back to the
    corridor edge; long edges get extra points first.  -> new ring, or the same list when nothing touched the corridor."""
    dens, hit = [], False
    mx_ = sum(p[0] for p in ring) / len(ring)
    my_ = sum(p[1] for p in ring) / len(ring)
    for k, p in enumerate(ring):
        q = ring[(k + 1) % len(ring)]
        dens.append(p)
        n = int(math.hypot(q[0] - p[0], q[1] - p[1]) // 2.5)
        for j in range(1, n + 1):
            dens.append((p[0] + (q[0] - p[0]) * j / (n + 1), p[1] + (q[1] - p[1]) * j / (n + 1)))
    out = []
    for x, y in dens:
        for _ in range(3):
            b = near_seg(g, x, y)
            if b is None or b[0] >= 0:
                break
            d, cx, cy, r, sx, sy = b
            ux, uy = x - cx, y - cy
            l = math.hypot(ux, uy)
            if l < 1e-3:                               # exactly on the centreline: step to the side the building lies on
                sl = math.hypot(sx, sy) or 1.0
                ux, uy = -sy / sl, sx / sl
                if ux * (mx_ - x) + uy * (my_ - y) < 0:
                    ux, uy = -ux, -uy
                l = 1.0
            x, y = cx + ux / l * (r + 0.05), cy + uy / l * (r + 0.05)
            hit = True
        out.append((x, y))
    if not hit:
        return ring
    res = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - res[-1][0], p[1] - res[-1][1]) > 0.05:
            res.append(p)
    return res


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


def load_photogram(src):
    """{OSM id: fitted look} that src/photogram.py wrote next to the OSM files (photogram.json), or {} = the generated look."""
    try:
        d = json.load(open(os.path.join(src, "photogram.json"), encoding="utf-8"))
        op = d.get("opts") or {}                                    # the photogrammetry screen's element switches / kit
        out = {int(k): v for k, v in d["buildings"].items()}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}
    if op:
        for v in out.values():
            v.setdefault("opts", op)
    return out


def load_elements(src):
    elements, seen = [], set()
    # side files in data/osm that are not Overpass element dumps (read elsewhere with _read_list / main.py)
    side = {"box.json", "bus_stops.json", "signals.json", "transit.json", "rail.json", "map_pois.json", "map_poi_kinds.json", "photogram.json", "photogram.off.json"}
    files = [f for f in sorted(glob.glob(os.path.join(src, "*.json"))) if os.path.basename(f) not in side]
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


def _tree_job(a):
    return tree_geo(*a)


def _lamp_job(a):
    return lamp_geo(*a)


_BT = [None]                                  # the pool worker's copy of the terrain


def party_walls(jobs, T):
    """Walls two buildings share (outline edges on the same line, 5 cm, facing each other: OSM's shared nodes or a neighbour's
    longer edge): each building's wall there is drawn only above the neighbour's roof, otherwise the two back-to-back walls
    fight in the depth buffer (the game draws without backface culling).  -> per job None (a free building) or per outline
    edge a list of (u0, u1, height above the building's own base under which the wall is hidden), u in metres along the edge."""
    G_ = 8.0
    tops, bases, segs, grid = [], [], [], {}
    for j, job in enumerate(jobs):
        ring = np.asarray(job[2], np.float64)
        tz = T.h(ring[:, 0], ring[:, 1])
        base = float(np.mean(tz)) if len(tz) else 0.0
        bases.append(base)
        tops.append(base + float(job[6]))
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            ln = float(np.hypot(*(b - a)))
            if ln < 0.15:
                continue
            si = len(segs)
            segs.append((j, i, a, b, ln))
            for gx in range(int(math.floor(min(a[0], b[0]) / G_)), int(math.floor(max(a[0], b[0]) / G_)) + 1):
                for gy in range(int(math.floor(min(a[1], b[1]) / G_)), int(math.floor(max(a[1], b[1]) / G_)) + 1):
                    grid.setdefault((gx, gy), []).append(si)
    out = [None] * len(jobs)
    seen = set()
    for cell in grid.values():
        for p in range(len(cell)):
            for q in range(p + 1, len(cell)):
                s1, s2 = cell[p], cell[q]
                if (s1, s2) in seen or segs[s1][0] == segs[s2][0]:
                    continue
                seen.add((s1, s2))
                j1, i1, a1, b1, l1 = segs[s1]
                j2, i2, a2, b2, l2 = segs[s2]
                t1, t2 = (b1 - a1) / l1, (b2 - a2) / l2
                if float(t1 @ t2) > -0.999:                    # walls back to back run opposite ways
                    continue
                nv = np.array([-t1[1], t1[0]])
                if abs(float((a2 - a1) @ nv)) > 0.05 or abs(float((b2 - a1) @ nv)) > 0.05:
                    continue
                u_a, u_b = float((a2 - a1) @ t1), float((b2 - a1) @ t1)
                lo, hi = max(0.0, min(u_a, u_b)), min(l1, max(u_a, u_b))
                if hi - lo < 0.3:
                    continue
                for j, i, l_, u0, u1, oth in ((j1, i1, l1, lo, hi, j2), (j2, i2, l2, u_a - hi, u_a - lo, j1)):
                    if out[j] is None:
                        out[j] = [[] for _ in jobs[j][2]]
                    out[j][i].append((max(0.0, u0), min(l_, u1), tops[oth] - bases[j]))
    return out


def _hide_edge(hide, i, ln, frac=0.9):
    """Height under which the whole edge i is hidden (its party-wall pieces cover >= frac of it), else -inf."""
    iv = hide[i] if hide else ()
    if not iv or sum(u1 - u0 for u0, u1, _c in iv) < frac * ln:
        return -1e9
    return min(c for _u0, _u1, c in iv)


def _split_party(outer, hide, y0):
    """The outline with each edge cut at its party-wall pieces, and the wall foot per new edge (the neighbour's roof where hidden)."""
    r = np.asarray(outer, np.float64)
    pts, yb = [], []
    for i in range(len(r)):
        a, b = r[i], r[(i + 1) % len(r)]
        ln = float(np.hypot(*(b - a)))
        cuts = sorted({0.0, ln, *[min(ln, max(0.0, u)) for u0, u1, _c in (hide[i] or ()) for u in (u0, u1)]})
        for u0, u1 in zip(cuts[:-1], cuts[1:]):
            if u1 - u0 < 1e-3:
                continue
            m = (u0 + u1) / 2
            pts.append(a + (b - a) * (u0 / max(ln, 1e-9)))
            yb.append(max([y0] + [c for v0, v1, c in (hide[i] or ()) if v0 - 1e-3 <= m <= v1 + 1e-3]))
    return np.array(pts), np.array(yb, np.float32)


def _bld_init(T):
    _BT[0] = T


def _bld_job(job):
    """One building's meshes on the terrain (walls, roof, facade extras, graffiti, roof junk) -> (binfo entry, [(material, pos, uv, col)]).
    Runs in a pool worker; the building's own random streams make the result independent of the other buildings."""
    (key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop, fit, *hide) = job
    hide = hide[0] if hide else None                                  # party walls: per edge, hidden below this (party_walls)
    fh, bw = (fit or {}).get("floor", 3.2), (fit or {}).get("bay", 3.4)
    T = _BT[0]
    adds = []
    ring = np.asarray(outer, np.float64)
    tz = T.h(ring[:, 0], ring[:, 1])
    cxm, cym = ring[:, 0].mean(), ring[:, 1].mean()
    base = float(np.mean(tz)) if len(tz) else 0.0
    skirt = max(0.0, base - float(min(tz.min(), T.hs(cxm, cym)))) + 0.3
    skirt_a = np.full(len(outer), -skirt, np.float32)

    def badd(m, pos, uv, col, base=base):
        pos = np.asarray(pos, np.float32).copy()
        pos[:, 1] += base
        adds.append((m, pos, uv, col))

    binf = (key, cxm, cym, base, h, 0.5 * max(ring[:, 0].max() - ring[:, 0].min(), ring[:, 1].max() - ring[:, 1].min()))
    if (fit or {}).get("arch"):                                       # Porta Macedonia: the arch mesh replaces walls and roof
        badd(MAT_SOLID, *arch_mod.arch_mesh(fit["arch"], box, shade))
        return binf, adds
    if (fit or {}).get("worship"):                                    # church / mosque model replaces walls and roof
        badd(MAT_SOLID, *worship.mesh(fit["worship"], shade))
        return binf, adds
    photo = photo_on(fit)                                             # procedural facade from the photos' numbers (ДЕТАЛИ fit)
    roof_fit = (fit or {}).get("roof") if photo else None
    if photo:
        for m_, *g in photo_facade(outer, h, fit, -skirt, hide):
            badd(m_, *g)
    else:
        sr_, sy_ = _split_party(outer, hide, -skirt) if hide else (outer, skirt_a)
        w = walls(sr_, h, wallc, sy_, fh, bw)
        if w:
            badd(mat, *w)
    rg = random.Random(len(outer) * 7919 ^ int(cxm * 131) ^ int(cym * 17))
    extras = facade_extras(outer, h, rg, wallc) if (not small and ar > 60 and not photo) else []      # the photos have their own
    n_el = min(1.0, len(extras) / 40.0)                                       # the more added elements, the more graffiti
    if not photo and rg.random() < min(0.98, {MAT_HOUSE: 0.75, MAT_PANEL: 0.85}.get(mat, 0.65) + 0.3 * n_el):          # graffiti on the street wall(s)
        gg = graffiti_geo(outer, h, rg, 3 + int(3 * n_el), big=(mat == MAT_PANEL and rg.random() < 0.25 + 0.3 * n_el))
        if gg:
            badd(MAT_GRAF, *gg)
    if roof_fit and not small and _roof_too_steep(outer, roof_fit):           # blocks keep calm roofs: a learned pitch over 20 degrees (or a mansard / gambrel) becomes a flat roof with parapet
        fit = dict(fit, roof=dict(roof_fit, kind="flat", rise=0.0))
        roof_fit = fit["roof"]
    proof = photo_roof(outer, h, fit, roofc, wallc) if roof_fit else None
    if proof is not None:
        for m_, *g in proof:
            badd(m_, *g)
    if proof is not None and (roof_fit.get("kind") == "flat" or not any(m_ == MAT_ROOF and len(g_[0]) for m_, *g_ in proof)):   # (a pitched fit with no roof pieces, e.g. rise < 0.3 m, is a flat roof: never an open top)
        for hole in holes:
            hw_ = walls(hole[::-1], h, wallc, np.full(len(hole), -skirt, np.float32), fh, bw)
            if hw_:
                badd(mat, *hw_)
        fp = flat_poly(verts, tri, h, 6.0, [c * 1.02 for c in roofc])
        if fp:
            badd(MAT_ROOF, *fp)
        pr = _parapet(outer, h, 0.95 if h > 8 else 0.35, [c * 0.82 for c in wallc])
        if pr:
            badd(MAT_SOLID, *pr)
    elif proof is not None:
        for hole in holes:
            hw_ = walls(hole[::-1], h, wallc, np.full(len(hole), -skirt, np.float32), fh, bw)
            if hw_:
                badd(mat, *hw_)
    elif small:
        badd(MAT_ROOF, *pyramid(outer, h, 1.8 + math.sqrt(ar) * 0.12, roofc))
        if rg.random() < 0.14:                                             # a piece on the visible roof slope (80% fewer than v42)
            pg = pitched_graffiti(outer, h, 1.8 + math.sqrt(ar) * 0.12, rg)
            if pg:
                badd(MAT_GRAF, *pg)
    else:
        for hole in holes:
            hw_ = walls(hole[::-1], h, wallc, np.full(len(hole), -skirt, np.float32), fh, bw)
            if hw_:
                badd(mat, *hw_)
        fp = flat_poly(verts, tri, h, 6.0, [c * 1.02 for c in roofc])
        if fp:
            badd(MAT_ROOF, *fp)
        pr = _parapet(outer, h, 0.95 if h > 8 else 0.35, [c * 0.82 for c in wallc])   # roof rim / attic wall
        if pr:
            badd(MAT_SOLID, *pr)
        if ar > 70 and rg.random() < 0.17:                                  # roof pieces (80% fewer than v42): the only graffiti a top-down camera reads
            rgf = roof_graffiti(outer, (ring[:, 0].min(), ring[:, 1].min(), ring[:, 0].max(), ring[:, 1].max()), h, rg, 2 if ar > 350 else 1)
            if rgf:
                badd(MAT_GRAF, *rgf)
        for ex_ in (roof_structure(outer, h, rg, roofc) if (ar > 80 and h > 8) else ()):
            badd(MAT_SOLID, *ex_)
        for ex_ in extras:
            badd(MAT_SOLID, *ex_)
        if OSM_KIT and h >= 4:                                              # the element kit by archetype (src/archkit.py OSM_POOLS)
            import archkit
            ids_ = archkit.osm_ids((fit or {}).get("osm_arch") or archkit.osm_archetype(mat, h, ar, small),
                                   ((int(cxm * 13.7) * 92821) ^ int(cym * 7.3)) & 0x7FFFFFFF)
            for m_, *g in osm_kit(outer, h, mat, wallc, fh, bw, -skirt, 0, ar, small, ids_, hide):
                badd(m_, *g)
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
    return binf, adds


def stage(name, **kw):
    """Marks a stage boundary of main() for tools/stages.py (incremental build); a plain run ignores it."""


def rebind(ns):
    """After a resume: the drawing handles that cannot be cached, drawn onto the restored images."""
    for im, dr in (("surf", "sd"), ("occ", "od"), ("bld", "bd")):
        if im in ns:
            ns[dr] = ImageDraw.Draw(ns[im])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "osm"))
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "cache", "world"))
    ap.add_argument("--allow-flat", action="store_true", help="build a flat city when terrain.npy is missing or for another box")
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
    photo_fit = load_photogram(a.src)
    print(f"[build] {len(elements)} OSM elements from {a.src}")
    if not any(e.get("tags", {}).get("highway") for e in elements):
        raise SystemExit("[build] no roads found in source data")

    tfile = os.path.join(a.src, "terrain.npy")
    try:
        T = terrain_mod.load(tfile, HX, HY)
        print(f"[build] terrain: {tfile} (range {float(T.g.min()):+.0f} .. {float(T.g.max()):+.0f} m)")
        real_terrain = True
    except Exception as ex:  # noqa: BLE001
        if not a.allow_flat:
            raise SystemExit(f"[build] terrain missing or for another box ({ex}); run tools/fetch_terrain.py --force")
        print(f"[build] terrain: none ({ex}) - FLAT city (--allow-flat)")
        T = terrain_mod.flat(HX, HY)
        real_terrain = False

    stage("map", data=("elements", "terrain.npy"))
    surf = Image.new("L", (NCX, NCY), 0)       # 0 ground, 1 water, 2 bridge, 3 road
    occ = Image.new("L", (NCX, NCY), 0)       # buildings + roads
    bld = Image.new("L", (NCX, NCY), 0)       # buildings only
    sd, od, bd = ImageDraw.Draw(surf), ImageDraw.Draw(occ), ImageDraw.Draw(bld)

    def cells(pts):
        return [((x + HX) / CELL, (y + HY) / CELL) for x, y in pts]

    mesh = MeshAcc()

    # ---- buildings (+ their 3D meshes) -------------------------------------------------------
    passages = [geom_pts(e) for e in elements if e.get("type") == "way" and e.get("tags", {}).get("tunnel") == "building_passage"
                and e.get("tags", {}).get("highway")]
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
                if arch_mod.is_arch(t):                    # Porta Macedonia: a triumphal arch with an open passage (tools/arch.py)
                    frame = arch_mod.arch_frame(outer, passages)
                    for pier in arch_mod.arch_piers(frame):
                        pv, pt_ = triangulate(pier, [])
                        pxs, pys = [p[0] for p in pier], [p[1] for p in pier]
                        buildings.append({"ring": pier, "v": pv, "tri": pt_, "h": arch_mod.H, "bb": (min(pxs), min(pys), max(pxs), max(pys)),
                                          "area": abs(shoelace(pier))})
                        od.polygon(cells(pier), fill=255)
                        bd.polygon(cells(pier), fill=255)
                    bb = (min(p[0] for p in outer), min(p[1] for p in outer), max(p[0] for p in outer), max(p[1] for p in outer))
                    pending.append((chunk_of((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), MAT_SOLID, outer, holes, verts, tri, arch_mod.H,
                                    (232, 228, 216), (232, 228, 216), ar, False, [], {"arch": frame}))
                    continue
                ws = worship.kind(t, el["id"]) and worship.build(worship.kind(t, el["id"]), outer, t)
                if ws:                                     # church / mosque / türbe model (tools/worship.py), never photo-fitted to a box
                    wh = worship.height(ws)
                    xs, ys = [p[0] for p in outer], [p[1] for p in outer]
                    bb = (min(xs), min(ys), max(xs), max(ys))
                    buildings.append({"ring": outer, "v": verts, "tri": tri, "h": wh, "bb": bb, "area": ar})
                    od.polygon(cells(outer), fill=255)
                    bd.polygon(cells(outer), fill=255)
                    for sr, sh_ in worship.solids(ws):     # minaret bases stand outside the footprint: solid too
                        sv, st_ = triangulate(sr, [])
                        sxs, sys_ = [p[0] for p in sr], [p[1] for p in sr]
                        buildings.append({"ring": sr, "v": sv, "tri": st_, "h": sh_, "bb": (min(sxs), min(sys_), max(sxs), max(sys_)),
                                          "area": abs(shoelace(sr))})
                        od.polygon(cells(sr), fill=255)
                        bd.polygon(cells(sr), fill=255)
                    pending.append((chunk_of((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2), MAT_SOLID, outer, holes, verts, tri, wh,
                                    (230, 220, 200), (176, 90, 60), ar, False, [], {"worship": ws}))
                    continue
                h, roofc, wallc, mat, small = bld_style(t, ar, outer, r)
                fit = photo_fit.get(el["id"])             # the photo-fitted look (src/photogram.py), when --src has photogram.json
                if fit:
                    h, mat = fit.get("h", h), fit.get("mat", mat)
                    wallc, roofc = tuple(fit.get("wallc", wallc)), tuple(fit.get("roofc", roofc))
                    small = small and fit.get("pitched", True)
                xs = [p[0] for p in outer]
                ys = [p[1] for p in outer]
                bb = (min(xs), min(ys), max(xs), max(ys))
                buildings.append({"ring": outer, "v": verts, "tri": tri, "h": h, "bb": bb, "area": ar})
                od.polygon(cells(outer), fill=255)
                bd.polygon(cells(outer), fill=255)
                key = chunk_of((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
                rooftop = []
                if not small and ar > 300 and r.random() < 0.8:        # rooftop boxes: stairwell / AC units
                    for _ in range(r.randint(1, 3)):
                        px, py = r.uniform(bb[0], bb[2]), r.uniform(bb[1], bb[3])
                        if pip((px, py), outer) and all(pip((px + dx, py + dy), outer) for dx, dy in ((2, 2), (-2, -2), (2, -2), (-2, 2))):
                            rooftop.append((px, py, r.uniform(1.5, 3.2), r.uniform(1.5, 3.2), r.uniform(1.0, 2.4)))
                if not fit and OSM_KIT:                   # the archetype for the element kit, from the tags too
                    import archkit
                    fit = {"osm_arch": archkit.osm_archetype(mat, h, ar, small, t)}
                pending.append((key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop, fit))
            except Exception as e:  # noqa: BLE001 - skip a malformed building
                print(f"   skipped building {el.get('id')}: {e}")
    print(f"[build] buildings: {len(buildings)}")

    # ---- areas / water / rails ---------------------------------------------------------------
    areas, wlines, rails = [], [], []
    river_polys = []
    lakes = Image.new("L", (NCX, NCY), 0)                     # standing water: lakes, ponds, basins
    ld = ImageDraw.Draw(lakes)
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
            if not kind or el["id"] == 176160189:           # 176160189 = Macedonia Square fountain basin: no water under the statue
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
                    if t.get("water") in ("river", "canal", "stream", "riverbank") or t.get("waterway") == "riverbank":
                        river_polys.append((outer, holes))       # gets quays (tools/quays.py), not the plain carve
                    else:
                        ld.polygon(cells(outer), fill=1)
                        for h_ in holes:
                            ld.polygon(cells(h_), fill=0)
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
            tunnel = t.get("tunnel") == "yes" and hw in TUNNEL_ROADS
            if t.get("area") == "yes" or (t.get("tunnel") in ("yes", "building_passage", "culvert") and not tunnel):
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
                          "bridge": bridge, "layer": layer, "nodes": nodes, "id": el["id"], "name": t.get("name", ""), "lanes": lanes, "turn": (t.get("turn:lanes:forward") or (t.get("turn:lanes", "") if ow else ""), t.get("turn:lanes:backward", "")),
                          "tunnel": tunnel})
        except Exception as e:  # noqa: BLE001
            print(f"   skipped road {el.get('id')}: {e}")
    phase("roads")                                           # the bar above ended at 100 %: the slow steps after it keep it moving
    frac(0.02, "bridges over tunnels")
    roads = lift_over_tunnels(roads)
    frac(0.1, "rivers")
    water_a = np.asarray(surf, dtype=np.uint8) == 1          # water before roads/bridges are painted over it
    T = terrain_mod.carve_water(T, water_a & (np.asarray(lakes, dtype=np.uint8) == 1), CELL)
    frac(0.2, "quays")
    import quays
    T.q, quay_info = quays.build(T, river_polys, [(wl["pts"], wl["w"]) for wl in wlines], roads, buildings, bld, CELL, HX, HY)
    frac(1.0, "quays")
    del lakes, ld

    # ---- building meshes, now that the ground under them is known ------------------------------
    import roads3d as _r3
    roads3d_SW = _r3.SW_W
    binfo = []
    bgrid = seg_grid([(a_[0], a_[1], b_[0], b_[1], rd["w"] / 2 + roads3d_SW + 0.1) for rd in roads
                      if rd["drive"] and not rd["bridge"] and not rd.get("tunnel") and rd["cls"] not in ("footway", "path", "steps", "cycleway", "pedestrian")
                      for a_, b_ in zip(rd["pts"], rd["pts"][1:])])
    bmap = {id(b_["ring"]): b_ for b_ in buildings}
    n_clip = n_drop = 0
    jobs_ = []
    for (key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop, fit) in each(pending, "building meshes on terrain", feed=("bmesh", None, lambda it: list(it[2][0]))):
        o2 = clip_ring(outer, bgrid)
        if o2 is not outer:
            n_clip += 1
            bi_ = bmap.get(id(outer))
            tri2 = None
            if len(o2) >= 3 and abs(shoelace(o2)) >= 8:
                if shoelace(o2) < 0:
                    o2 = o2[::-1]
                try:
                    v2, tri2 = triangulate(o2, [])
                except Exception:  # noqa: BLE001
                    tri2 = None
            if not tri2:
                n_drop += 1
                if bi_:
                    bi_["tri"], bi_["v"], bi_["area"] = [], [], 0.0
                continue
            outer, holes, verts, tri, ar = o2, [], v2, tri2, abs(shoelace(o2))
            if bi_:
                xs_ = [p[0] for p in o2]
                ys_ = [p[1] for p in o2]
                bi_.update(ring=o2, v=v2, tri=tri2, bb=(min(xs_), min(ys_), max(xs_), max(ys_)), area=ar)
        jobs_.append((key, mat, outer, holes, verts, tri, h, wallc, roofc, ar, small, rooftop, fit))
    hide_ = party_walls(jobs_, T)
    jobs_ = [j_ + (hd_,) for j_, hd_ in zip(jobs_, hide_)]
    bb_ = Bar("building meshes on terrain", max(1, len(jobs_)))
    for binf_, adds_ in par.pmap(_bld_job, jobs_, init=(_bld_init, (T,)), chunk=16, on=lambda d, t: bb_.update(d)):         # the meshes: pure per-building work, on all cores
        binfo.append(binf_)
        for m_, pos_, uv_, col_ in adds_:
            mesh.add(binf_[0], m_, pos_, uv_, col_)
    bb_.done()
    phase("cables and ground")
    buildings[:] = [b_ for b_ in buildings if len(b_["tri"])]
    print(f"[build] buildings clipped off roads/pavements: {n_clip} trimmed, {n_drop} dropped")
    if binfo:                                                  # TV / phone cables from block to block
        tall = [b for b in binfo if b[4] > 10]
        gx = {}
        for b in tall:
            gx.setdefault((int(b[1] // 40), int(b[2] // 40)), []).append(b)
        rc = random.Random(5)
        for b in span(tall, 0.0, 0.5, "cables"):
            if rc.random() > 0.45:
                continue
            cands = [o for dx in (-1, 0, 1) for dz in (-1, 0, 1) for o in gx.get((int(b[1] // 40) + dx, int(b[2] // 40) + dz), ())
                     if o is not b and 12.0 < math.hypot(o[1] - b[1], o[2] - b[2]) < 48.0]
            if not cands:
                continue
            o = rc.choice(cands)
            dist = math.hypot(o[1] - b[1], o[2] - b[2])
            ux, uz = (o[1] - b[1]) / dist, (o[2] - b[2]) / dist
            for _c in range(rc.randint(1, 3)):
                hb, ho = rc.uniform(0.55, 0.95) * min(b[4], 40.0), rc.uniform(0.55, 0.95) * min(o[4], 40.0)
                off = rc.uniform(-2.5, 2.5)
                p0 = (b[1] + ux * (b[5] + 0.4) - uz * off, b[3] + hb, b[2] + uz * (b[5] + 0.4) + ux * off)
                p1 = (o[1] - ux * (o[5] + 0.4) - uz * off, o[3] + ho, o[2] - uz * (o[5] + 0.4) + ux * off)
                mesh.add(b[0], MAT_SOLID, *_cable(p0, p1, 0.02 * dist + 0.4))
    del pending
    for rd in span(sorted(roads, key=lambda q: (q["bridge"], q["layer"])), 0.5, 1.0, "road paint"):
        val = 2 if rd["bridge"] else 3
        wpx = max(1, int(round((rd["w"] + 3) / CELL)))
        sd.line(cells(rd["pts"]), fill=val, width=wpx)
        od.line(cells(rd["pts"]), fill=255, width=wpx)
    roads.sort(key=lambda q: (q["bridge"], q["layer"], -q["w"]))
    print(f"[build] roads: {len(roads)}")
    stage("graph", data=("map_pois.json", "bus_stops.json"))
    phase("graph")

    connect_roads(roads)
    try:                                                        # round 29: trampled desire-line paths over open ground
        import footpaths
        worn = footpaths.generate(roads, buildings, bld, surf, rails, [q for q in _read_list(os.path.join(a.src, "map_pois.json")) if len(q) == 4],
                                  _read_list(os.path.join(a.src, "bus_stops.json")), T, HX, HY, CELL)
        for rd in worn:
            sd.line(cells(rd["pts"]), fill=3, width=max(1, int(round((rd["w"] + 3) / CELL))))
            od.line(cells(rd["pts"]), fill=255, width=max(1, int(round((rd["w"] + 3) / CELL))))
        roads.extend(worn)
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
    frac(0.2, "roads joined")
    # ---- routing graph ----------------------------------------------------------------------------
    use = {}
    for rd in span(roads, 0.2, 0.3, "junctions"):
        if rd["drive"] or rd["walk"]:
            for n in rd["nodes"]:
                use[n] = use.get(n, 0) + 1
    node_ids, edges = {}, []

    def nid(osm):
        if osm not in node_ids:
            node_ids[osm] = len(node_ids)
        return node_ids[osm]

    for ri, rd in enumerate(span(roads, 0.3, 0.6, "edges")):
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
                                  "ow": rd["ow"], "w": rd["w"], "road": ri, "bridge": rd["bridge"], "lanes": rd.get("lanes", 0),
                                  "worn": rd.get("worn", ""), "turn": rd.get("turn", ("", ""))})
                start = i
    import lanefix
    print(f"[build] lane dips repaired: {lanefix.repair(edges)} edges")
    import roads3d
    roads3d.smooth_edges(edges)                  # rounded corners; junction end points stay put
    frac(0.95, "rounded corners")
    print(f"[build] graph: {len(node_ids)} nodes, {len(edges)} edges ({sum(1 for e in edges if e['drive'])} drivable)")
    spread("graph", edges, lambda e: flat(e["pts"], 60))
    phase("bridge decks")

    # ---- bridge decks: ends meet the terrain, the middle clears whatever runs underneath ---------------
    under = {}                                      # 12 m grid of ways a bridge may pass over
    for ri, rd in enumerate(span(roads, 0.0, 0.4, "ways under bridges")):
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
    for ri, rd in enumerate(span(roads, 0.4, 1.0, "decks")):
        if rd["bridge"] and (rd["drive"] or rd["walk"]) and len(rd["pts"]) >= 2:
            try:
                decks[ri] = terrain_mod.make_deck(T, {"pts": rd["pts"]}, lower, rd["w"] / 2 + 0.6 + (roads3d.BRIDGE_SW if rd["drive"] else 0.0))
            except Exception as ex:  # noqa: BLE001 - a bad bridge stays flat
                print(f"   deck for road {rd['id']} skipped: {ex}")
    if T.q is not None:
        nj, nl, nskip = __import__('quays').fix_decks(decks, T, roads)
        print(f"[build] river quays: {nj} bridge joints lifted, {nl} decks lifted over the walkways below or smoothed "
              f"({nskip} crossings too close to an end)")
    print(f"[build] bridges: {terrain_mod.twin_decks(decks, T)} deck samples raised to the deck beside them")
    try:                                                        # approaches: embankments and vertical curves into the roads (after twin_decks: it would kink them again)
        _barr = np.asarray(bld)
        __import__("ramps").smooth(T, decks, roads, lambda x, y: bool(_barr[min(NCY - 1, max(0, int((y + HY) / CELL))), min(NCX - 1, max(0, int((x + HX) / CELL)))]), HX, HY)
    except Exception as ex:  # noqa: BLE001 - the old profiles stay
        import traceback
        traceback.print_exc()
        print(f"[build] ramps skipped: {ex}")
    lifted = sum(1 for d in decks.values() if max(d.h) - min(d.h) > 1.5)
    print(f"[build] bridges: {len(decks)} decks ({lifted} with a real rise)")
    spread("bridge", [roads[ri] for ri in decks], lambda r: flat(r["pts"], 30))
    stage("props")
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
    for el in span(elements, 0.0, 1.0, "neighbourhoods"):
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
    for el in span(elements, 0.0, 1.0, "trees and lamps from the map"):
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
        big_wood = ar["kind"] == "wood" and abs(shoelace(ar["outer"])) > 15000.0       # v62: large woods get 2.5x bigger trees, 6x fewer
        if big_wood:
            spacing *= 2.5
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
                    trees.append((px, py, (r.uniform(2.2, 4.4) * (2.5 if big_wood else 1.0)) if ar["kind"] == "wood" else r.uniform(2.0, 3.8), r.randint(0, 3)))
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
        x0_, x1_, y0_, y1_ = min(max(cx_ - k, 0), NCX), min(max(cx_ + k + 1, 0), NCX), min(max(cy_ - k, 0), NCY), min(max(cy_ + k + 1, 0), NCY)
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
            big = cls in ("trunk", "primary", "secondary") or (cls == "tertiary" and w >= 9.0)      # round 31: boulevards and big streets are lit on both kerbs
            step = 22.0 if cls in ("trunk", "primary", "secondary") else 28.0 if big else 36.0 if cls == "tertiary" else 55.0
            s, side = r.uniform(5, step), 1
            while s < L - 3:
                x, y, dx, dy = at(s)
                off = w / 2 + 1.4
                for sd in ((1, -1) if big and not e["ow"] else (side,)):
                    px, py = x - dy * off * sd, y + dx * off * sd
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
    phase("parked cars")
    lot_cars = _fill_lots(areas, bld_a, to_cell, NCX, NCY, HX, HY)
    frac(0.1, "car parks")
    asph = {}                                                   # round 26: nobody parks on asphalt: not on any road (parking-lot aisles and service lanes included)
    for rd_ in span(roads, 0.1, 0.3, "road grid"):
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
    parked = [q for q in span(parked, 0.3, 0.6, "parked cars") if _clear_of_asphalt(q)] + [q for q in span(lot_cars, 0.6, 0.7, "car parks") if _clear_of_asphalt(q, 0.5)]     # car-park bays leave aisles and access lanes open
    kept, taken = [], {}                                        # round 23: cars of crossing streets must not overlap
    for q in span(parked, 0.7, 0.95, "parked cars"):
        gx_, gy_ = int(q[0] // 4), int(q[1] // 4)
        if any((q[0] - o[0]) ** 2 + (q[1] - o[1]) ** 2 < 2.4 ** 2 for i_ in (-1, 0, 1) for j_ in (-1, 0, 1) for o in taken.get((gx_ + i_, gy_ + j_), ())):
            continue
        taken.setdefault((gx_, gy_), []).append(q)
        kept.append(q)
    parked = kept
    parked = [q for q in parked if random.Random(int(q[0] * 7.0) * 100003 + int(q[1] * 13.0)).random() < 0.5]     # round 27: half as many everywhere, the centre-to-suburb gradient stays
    print(f"[build] trees {len(trees)}  lamps {len(lamps)}  parked cars {len(parked)}")

    stage("furniture", data=("bus_stops.json", "signals.json"))
    phase("furniture")
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
    stage("leisure", data=("map_pois.json",))
    phase("leisure")
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

    stage("monument")
    phase("monument")
    frac(0.05, "monument")
    try:                                                        # round 32: Warrior on a Horse in the Macedonia Square fountain
        import monument
        posts = list(posts) + monument.build(add_c, chunk_of, lambda x, y: T.hs(x, y))
        frac(0.5, "statues")
        import statues
        _sp, _placed = statues.build(add_c, chunk_of, lambda x, y: _not_building(x, y) and not _is_water(x, y), lambda x, y: T.hs(x, y))
        posts = list(posts) + _sp
        print(f"[build] statues placed: {_placed}")
        for ri_, rd_ in enumerate(roads):                       # round 32: the Stone Bridge arcade
            if rd_["id"] == 411079115 and ri_ in decks:
                monument.build_bridge(decks[ri_], lambda x, y: T.hs(x, y), mesh.add, chunk_of)
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] monument skipped: {e}")

    stage("construction")
    phase("construction sites")
    works = []
    try:                                                        # round 20: fenced building sites on empty lots in built-up areas
        import construction
        kill = Image.new("L", (NCX, NCY), 0)
        kd = ImageDraw.Draw(kill)
        for ar in span(areas, 0.0, 0.25, "parks and squares"):
            if ar["kind"] in ("park", "playground", "pitch", "cemetery", "wood", "water", "plaza", "parking", "sand", "rock"):
                kd.polygon([to_cell(px, py) for px, py in ar["outer"]], fill=1)
        free_mask = (occ_a == 0) & (surf_a == 0) & (np.asarray(kill) == 0)
        frac(0.3, "empty lots")
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
            for a_, b_, c_, d_ in span(lots, 0.85, 1.0, "trees on the lots"):
                keep &= ~((ta[:, 0] >= a_) & (ta[:, 0] <= c_) & (ta[:, 1] >= b_) & (ta[:, 1] <= d_))
            trees = [t for t, k in zip(trees, keep) if k]
        parked = list(parked) + cparked
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] construction skipped: {e}")

    stage("stations", data=("map_pois.json", "buildings.json"))
    phase("petrol stations and car washes")
    frac(0.01, "reading the map")
    fsites = []
    def clear_of_bld(x, y):                                     # no building and no water (paved forecourts are fine)
        if abs(x) >= HX - 5 or abs(y) >= HY - 5:
            return False
        cx, cy = to_cell(x, y)
        return not bld_a[cy, cx] and surf_a[cy, cx] != 1

    try:                                                        # round 30: OSM petrol stations and car washes tied to the road graph
        import stations
        sp_, fsites, sparked = stations.build(a.src, edges, add_c, chunk_of, lambda x, y: float(T.hs(x, y)), clear_of_bld, HX, HY)
        posts = list(posts) + sp_
        parked = list(parked) + sparked
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] stations skipped: {e}")

    stage("fill")
    phase("fill: gardens, scrub, boulders")
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
    stage("cleanup")
    phase("carriageway cleanup")
    cgrid_ = {}
    for e_ in span(edges, 0.0, 0.3, "lane grid"):
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
    lamps = [q for q in span(lamps, 0.3, 0.4, "lamps") if not in_lane(q[0], q[1], 0.22)]
    trees = [q for q in span(trees, 0.4, 0.7, "trees") if not in_lane(q[0], q[1], 0.5)]
    posts = [q for q in span(posts, 0.7, 1.0, "posts") if (len(q) >= 5 and q[3] > T.hs(q[0], q[1]) + 2.2) or not in_lane(q[0], q[1])]
    print(f"[build] cleared from the carriageways: {n_l - len(lamps)} lamps, {n_t - len(trees)} trees, {n_p - len(posts)} posts")

    stage("rail", data=("rail.json",))
    phase("railway")
    stations, track = [], {"lines": [], "crossings": []}
    rl = None
    try:                                                        # round 21: railway viaducts, level crossings, stations
        import rail
        rl = _read_list(os.path.join(a.src, "rail.json"))
        if rl:
            _barr = np.asarray(bld)
            rp, stations, track = rail.build(rl, edges, add_c, mesh.add, chunk_of, lambda x, y: float(T.hs(x, y)), in_lane,
                                             lift=lambda items, keep: __import__("ramps")._lift_overlay(T, items, lambda x, y, _v: keep(x, y) or bool(
                                                 _barr[min(NCY - 1, max(0, int((y + HY) / CELL))), min(NCX - 1, max(0, int((x + HX) / CELL)))]), HX, HY))
            posts = list(posts) + rp
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] railway skipped: {e}")

    n_t0 = len(trees)                                           # no trees under train tracks or overpasses (and none on the track bed)
    tsegs = []
    for e_ in edges:
        if e_["bridge"] and (e_["drive"] or e_["walk"]):
            tsegs += [(a_[0], a_[1], b_[0], b_[1], e_["w"] / 2 + 2.0) for a_, b_ in zip(e_["pts"], e_["pts"][1:])]
    try:
        for r_ in (rl or []):
            if r_[0] == "way" and r_[1] == "rail" and not r_[3]:
                rr_ = 5.0 if r_[2] else 3.5
                tsegs += [(a_[0], a_[1], b_[0], b_[1], rr_) for a_, b_ in zip(r_[4], r_[4][1:])]
    except Exception:  # noqa: BLE001
        pass
    tgrid = seg_grid(tsegs)
    trees = [q for q in trees if (near_seg(tgrid, q[0], q[1]) or (1,))[0] >= 0]
    print(f"[build] trees removed from under rails / overpasses: {n_t0 - len(trees)}")
    stage("roads3d")
    try:
        phase("3D roads")
        roads3d.PIER_SKIP = lambda x, y, r: in_lane(x, y, -r) or __import__("monument").on_bridge(x, y)          # no bridge pier in a street passing underneath
        nv, piers = roads3d.build(edges, xwalks, mesh.add, chunk_of, MAT_SOLID, T=T, decks=decks)
        posts = list(posts) + piers
        roads3d_ok = True
        print(f"[build] 3D roads: {nv / 1e6:.2f} M vertices")
        if T.q is not None:
            __import__("quays").furnish(T, edges, quay_info, mesh.add, chunk_of, MAT_SOLID)
    except Exception as e:  # noqa: BLE001 - fall back to the flat 2D roads in the ground texture
        import traceback
        traceback.print_exc()
        print(f"[build] 3D roads failed ({e}); using flat roads")
        roads3d_ok = False
    spread("road3d", edges, lambda e: flat(e["pts"], 60))
    stage("rasters")
    phase("ground rasters")
    hg = Image.new("L", (NCX, NCY), 0)       # ground height class: 0 ground, 1 asphalt, 2 pavement
    hd = ImageDraw.Draw(hg)
    for e_ in span(edges, 0.0, 0.3, "pavements"):
        if roads3d._base(e_["cls"]) in roads3d.SIDEWALK and not e_["bridge"]:
            hd.line(cells(e_["pts"]), fill=2, width=max(1, int(round((e_["w"] + 2 * roads3d.SW_W) / CELL))))
    for e_ in span(sorted(edges, key=lambda q: roads3d.rank_of(q["cls"])), 0.3, 0.6, "asphalt"):
        if e_["drive"] or e_["walk"]:
            hd.line(cells(e_["pts"]), fill=1, width=max(1, int(round(e_["w"] / CELL))))

    hg_arr = np.asarray(hg, dtype=np.uint8).copy()
    hg_arr[water_a] |= 4                                        # bit 2: ground-level water (also under bridges)
    posts = [p if len(p) >= 5 else (p[0], p[1], p[2], T.hs(p[0], p[1]) - 1.0, T.hs(p[0], p[1]) + 2.4) for p in span(posts, 0.6, 0.7, "collision posts")]

    tj_ = [(x, y, r_, sh, i) for i, (x, y, r_, sh) in enumerate(each(trees, "tree meshes", feed=("trees", None, lambda t: [t[0], t[1]])))]
    for (x, y, _r, _s, _i), g_ in zip(tj_, par.pmap(_tree_job, tj_, chunk=256, on=lambda d, t: frac(0.7 + 0.2 * d / t, "tree meshes"))):                 # the meshes themselves on all cores
        add_c(chunk_of(x, y), MAT_SOLID, *g_)
    lj_ = [(x, y) for x, y in each(lamps, "lamp meshes", feed=("props", None, lambda p: [p[0], p[1]]))]
    for (x, y), g_ in zip(lj_, par.pmap(_lamp_job, lj_, chunk=256, on=lambda d, t: frac(0.9 + 0.1 * d / t, "lamp meshes"))):
        add_c(chunk_of(x, y), MAT_SOLID, *g_)

    # ---- fire escapes up to the flat roofs, launch ramps between roofs ------------------------------
    stage("escapes")
    phase("fire escapes and roof jumps")
    plats, esc_info = [], {}
    try:
        import escapes
        plats, esc_info = escapes.build(buildings, T, bld_a, occ_a, surf_a, hg_arr, CELL, HX, HY, mesh.add, chunk_of, MAT_SOLID)
    except Exception as e:  # noqa: BLE001 - decoration
        import traceback
        traceback.print_exc()
        print(f"[build] fire escapes skipped: {e}")

    # ---- chunk index (for ground baking) ---------------------------------------------------------
    stage("index")
    chunks = {}

    def slot(c):
        d = chunks.get(c)
        if d is None:
            d = chunks[c] = {"b": [], "a": [], "r": [], "wl": [], "rail": [], "t": [], "x": [], "m": {}, "bb": None}
        return d

    SKEW = 0.22
    for i, b in enumerate(buildings):          # (fast)
        x0, y0, x1, y1 = b["bb"]
        h = b["h"]
        for c in chunk_range(x0, y0, x1 + h * 0.3, y1 + h * 0.2):
            slot(c)["b"].append(i)
    phase("chunk index: areas")
    spread("areas", areas, lambda a: flat(a["v"]))
    for i, ar in enumerate(span(areas, 0.0, 0.5, "areas")):
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
    frac(0.7, "roads")
    index_lines(wlines, "wl", lambda w_: w_["w"] / 2 + 2)
    index_lines(rails, "rail", lambda r_: 3)
    frac(0.75, "rivers and rails")
    for i, xw_ in enumerate(xwalks):
        for c in chunk_range(xw_[0] - xw_[4], xw_[1] - xw_[4], xw_[0] + xw_[4], xw_[1] + xw_[4]):
            slot(c)["x"].append(i)
    for i, p in enumerate(span(trees, 0.75, 1.0, "trees")):
        for c in chunk_range(p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5):
            slot(c)["t"].append(i)

    # ---- spawn point -------------------------------------------------------------------------------------
    stage("write")
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
                  "sites": sites, "works": works, "fuelsites": fsites, "stations": stations, "track": track},
        "chunks": {"chunks": chunks},
        "surf": {"surf": zlib.compress(np.asarray(surf, dtype=np.uint8).tobytes(), 6),
                 "hgt": zlib.compress(hg_arr.tobytes(), 6)},
        "terrain": {"terrain": {"grid": np.asarray(T.g, np.float32).tobytes(), "nx": T.nx, "ny": T.ny, "step": terrain_mod.STEP,
                                "real": bool(real_terrain), "quay": T.q.pack() if T.q is not None else None},
                    "decks": [d.pack() for d in decks.values()], "plats": plats, "esc": esc_info},
    }
    sizes = {"meshes.bin": os.path.getsize(os.path.join(tmp, "meshes.bin"))}
    phase("write world parts")
    try:                                        # the last build's sizes tell how far each write has got
        est = json.load(open(os.path.join(a.out, "manifest.json")))["sizes"]
    except Exception:  # noqa: BLE001
        est = {}
    tot = sum(est.get(n + ".pkl", 0) for n in parts) or 0
    wrote = [0]

    class _Count:
        def __init__(self, f, name, k):
            self.f, self.name, self.k = f, name, k

        def write(self, b):
            mv = memoryview(b)
            for o in range(0, max(1, len(mv)), 1 << 22):          # big blobs (terrain, rasters) in 4 MB steps
                piece = mv[o:o + (1 << 22)]
                wrote[0] += len(piece)
                frac(min(0.99, wrote[0] / tot) if tot else self.k / len(parts), self.name)
                self.f.write(piece)
            return len(mv)
    for k, (name, obj) in enumerate(parts.items()):
        fn = name + ".pkl"
        with open(os.path.join(tmp, fn), "wb") as f:
            pickle.dump(obj, _Count(f, name, k), protocol=pickle.HIGHEST_PROTOCOL)
        sizes[fn] = os.path.getsize(os.path.join(tmp, fn))
        if not tot:
            frac((k + 1) / len(parts), name)
    json.dump({"version": VERSION, "sizes": sizes, "stages": globals().get("STAGE_FPS")}, open(os.path.join(tmp, "manifest.json"), "w"))
    frac(0.99, "replacing the old world")
    if os.path.isdir(a.out):
        import shutil
        shutil.rmtree(a.out)
    os.replace(tmp, a.out)
    print(f"[build] wrote {a.out} ({sum(sizes.values()) / 1e6:.1f} MB), {len(chunks)} chunks")


if __name__ == "__main__":
    if "--no-stages" in sys.argv:                       # one plain run of main(), no stage cache
        sys.argv.remove("--no-stages")
        main()
    else:
        import stages
        stages.run()
