"""Worn footpaths: desire lines that people trample into grass, dirt and empty ground between buildings.

Three kinds, all procedural and deterministic, returned as extra "path" roads flagged worn=True (walkable, never drivable,
left off the minimap / map, no benches or lamps):
  cut     a shortcut between two walkable roads whose walk along the network is much longer than the straight line
  door    a spur from a building's side to the nearest walkable road
  poi     a spur from a map POI standing on open ground to the nearest walkable road
Ends are joined onto the existing roads with new junction nodes, so pedestrians can use them.
"""
import heapq
import math
import random

import numpy as np
from PIL import Image, ImageDraw

from progress import frac

SAMPLE = 14.0              # spacing of join candidates along the walkable roads (m)
FRESH = -50_000_000        # node ids for the new junctions / path vertices (connect_roads uses small negatives)


def _walkable(rd):
    return (rd["walk"] and not rd["bridge"] and not rd.get("tunnel") and rd["layer"] == 0 and rd["cls"] not in ("motorway", "steps")
            and len(rd["nodes"]) == len(rd["pts"]) and len(rd["pts"]) >= 2)


def generate(roads, buildings, bld_img, surf_img, rails, pois, stops, T, hx, hy, cell, seed=242):
    rnd = random.Random(seed)
    nx, ny = bld_img.size

    def cells(pts):
        return [((x + hx) / cell, (y + hy) / cell) for x, y in pts]

    def mask(draw_fn):
        im = Image.new("L", (nx, ny), 0)
        draw_fn(ImageDraw.Draw(im))
        return np.asarray(im, dtype=np.uint8) > 0

    bld_raw = np.asarray(bld_img, dtype=np.uint8) > 0
    bld_d = bld_raw.copy()                                   # buildings grown by one cell (2 m)
    bld_d[1:] |= bld_raw[:-1]
    bld_d[:-1] |= bld_raw[1:]
    bld_d[:, 1:] |= bld_raw[:, :-1]
    bld_d[:, :-1] |= bld_raw[:, 1:]
    wet = np.asarray(surf_img, dtype=np.uint8) == 1
    rail_m = mask(lambda d: [d.line(cells(r["pts"]), fill=255, width=3) for r in rails if len(r["pts"]) > 1])
    road_m = mask(lambda d: [d.line(cells(r["pts"]), fill=255, width=max(1, int(round(r["w"] / cell)))) for r in roads])
    hard = wet | rail_m
    worn_m = np.zeros((ny, nx), bool)

    def cix(x, y):
        return int((x + hx) / cell), int((y + hy) / cell)

    def at(m, x, y):
        i, j = cix(x, y)
        return bool(m[j, i]) if 0 <= i < nx and 0 <= j < ny else True

    # ---- join candidates: resampled walkable roads, linked into a graph ----------------------------------
    frac(0.11, "worn paths")
    S = []                                       # (x, y, road, seg, t)
    adj = []
    by_node = {}
    for ri, rd in enumerate(roads):
        if ri % 256 == 0:
            frac(0.11 + 0.03 * ri / max(1, len(roads)), "worn paths")
        if not _walkable(rd):
            continue
        pts, nodes = rd["pts"], rd["nodes"]
        prev = None
        for k in range(len(pts) - 1):
            (ax, ay), (bx, by) = pts[k], pts[k + 1]
            L = math.hypot(bx - ax, by - ay)
            for q in range(max(1, int(L // SAMPLE))):
                t = q * SAMPLE / L
                i = len(S)
                S.append((ax + (bx - ax) * t, ay + (by - ay) * t, ri, k, t))
                adj.append([])
                if prev is not None:
                    d = math.hypot(S[i][0] - S[prev][0], S[i][1] - S[prev][1])
                    adj[i].append((prev, d))
                    adj[prev].append((i, d))
                if q == 0:
                    by_node.setdefault(nodes[k], []).append(i)
                prev = i
        i = len(S)                               # last vertex of the road
        S.append((pts[-1][0], pts[-1][1], ri, len(pts) - 2, 1.0))
        adj.append([])
        d = math.hypot(S[i][0] - S[prev][0], S[i][1] - S[prev][1])
        adj[i].append((prev, d))
        adj[prev].append((i, d))
        by_node.setdefault(nodes[-1], []).append(i)
    for lst in by_node.values():
        for a in lst:
            for b in lst:
                if a != b:
                    adj[a].append((b, 0.0))
    G = 48.0
    grid = {}
    for i, s in enumerate(S):
        grid.setdefault((int(s[0] // G), int(s[1] // G)), []).append(i)

    def near(x, y, rmin, rmax):
        out = []
        r = int(rmax // G) + 1
        gx, gy = int(x // G), int(y // G)
        for cx in range(gx - r, gx + r + 1):
            for cy in range(gy - r, gy + r + 1):
                for i in grid.get((cx, cy), ()):
                    d = math.hypot(S[i][0] - x, S[i][1] - y)
                    if rmin <= d <= rmax:
                        out.append((d, i))
        return out

    def reach(a, b, limit):
        """True when the road network joins sample a to sample b within `limit` metres."""
        best = {a: 0.0}
        h = [(0.0, a)]
        while h:
            d, u = heapq.heappop(h)
            if u == b:
                return True
            if d > best.get(u, 1e18):
                continue
            for v, w in adj[u]:
                nd = d + w
                if nd <= limit and nd < best.get(v, 1e18):
                    best[v] = nd
                    heapq.heappush(h, (nd, v))
        return False

    # ---- a path polyline: gentle meander, then checked against everything it must not cross -----------------
    def route(p0, p1, door):
        L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        n = max(2, int(L / 5.0))
        ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
        amp, ph1, ph2 = rnd.uniform(0.3, 1.3), rnd.uniform(0, 6.3), rnd.uniform(0, 6.3)
        pl = []
        for q in range(n + 1):
            f = q / n
            off = amp * math.sin(math.pi * f) * (0.7 * math.sin(ph1 + f * 5.0) + 0.3 * math.sin(ph2 + f * 11.0))
            pl.append((p0[0] + (p1[0] - p0[0]) * f - uy * off, p0[1] + (p1[1] - p0[1]) * f + ux * off))
        slope = 0.0
        prev = None
        for (ax, ay), (bx, by) in zip(pl, pl[1:]):
            seg = max(1.0, math.hypot(bx - ax, by - ay))
            for q in range(int(seg // 1.5) + 1):
                f = q * 1.5 / seg
                x, y = ax + (bx - ax) * f, ay + (by - ay) * f
                s0 = math.hypot(x - p0[0], y - p0[1])
                s1 = math.hypot(x - p1[0], y - p1[1])
                if at(hard, x, y):
                    return None
                if at(bld_d, x, y) and not (door and s0 < 3.5):
                    return None
                if at(road_m, x, y) and s1 > 8.0 and (door or s0 > 8.0):
                    return None
                if at(worn_m, x, y) and s0 > 4 and s1 > 4:
                    return None
                h = T.hs(x, y)
                if prev is not None:
                    slope = max(slope, abs(h - prev[0]) / max(0.5, math.hypot(x - prev[1], y - prev[2])))
                prev = (h, x, y)
        return pl if slope < 0.4 else None

    inserts = {}                                 # road -> [(seg, t, node id, point)]
    fresh = [FRESH]
    out = []
    used = set()

    def new_id():
        fresh[0] -= 1
        return fresh[0]

    def join(si):
        """Node id for the road point of sample si: an existing vertex when we are on one, else a new junction."""
        x, y, ri, k, t = S[si]
        rd = roads[ri]
        if t < 0.12:
            return rd["nodes"][k], (rd["pts"][k])
        if t > 0.88:
            return rd["nodes"][k + 1], (rd["pts"][k + 1])
        nid_ = new_id()
        inserts.setdefault(ri, []).append((k, t, nid_, (x, y)))
        return nid_, (x, y)

    def emit(pl, a_si, b_si, w, kind):
        na, pa = join(a_si)
        pts = [pa] + pl[1:-1]
        nodes = [na] + [new_id() for _ in pl[1:-1]]
        if b_si is not None:
            nb, pb = join(b_si)
        else:
            nb, pb = new_id(), pl[-1]
        pts.append(pb)
        nodes.append(nb)
        out.append({"pts": pts, "w": w, "cls": "path", "speed": 0, "drive": 0, "walk": 1, "ow": 0, "bridge": False, "layer": 0,
                    "nodes": nodes, "id": -len(out) - 1, "name": "", "lanes": 0, "tunnel": False, "worn": kind})
        used.add(a_si)
        if b_si is not None:
            used.add(b_si)
        for (x, y) in pts:
            i, j = cix(x, y)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    if 0 <= i + di < nx and 0 <= j + dj < ny:
                        worn_m[j + dj, i + di] = True

    att = [(q[0], q[1]) for q in pois] + [(q[0], q[1]) for q in stops]
    agrid = {}
    for x, y in att:
        agrid.setdefault((int(x // 40), int(y // 40)), []).append((x, y))

    def attractive(x, y):
        gx, gy = int(x // 40), int(y // 40)
        return any(math.hypot(px - x, py - y) < 40 for dx in (-1, 0, 1) for dy in (-1, 0, 1) for px, py in agrid.get((gx + dx, gy + dy), ()))

    # ---- 1: cut-throughs ------------------------------------------------------------------------------------
    order = list(range(len(S)))
    rnd.shuffle(order)
    nc = 0
    for oi_, a in enumerate(order):
        if oi_ % 512 == 0:
            frac(0.14 + 0.04 * oi_ / max(1, len(order)), "worn paths")
        if a in used:
            continue
        ax, ay, ra = S[a][0], S[a][1], S[a][2]
        cands = [(d, b) for d, b in near(ax, ay, 22.0, 80.0) if S[b][2] != ra and b not in used]
        rnd.shuffle(cands)
        for d, b in cands[:10]:
            bx, by = S[b][0], S[b][1]
            if at(bld_raw, (ax + bx) / 2, (ay + by) / 2) or at(hard, (ax + bx) / 2, (ay + by) / 2):
                continue
            if rnd.random() > (0.3 if attractive(ax, ay) or attractive(bx, by) else 0.1):
                continue
            if reach(a, b, 3.0 * d + 20):
                continue                                            # the walk round is short: nobody would trample a shortcut
            pl = route((ax, ay), (bx, by), False)
            if pl is None:
                continue
            emit(pl, a, b, rnd.uniform(1.3, 1.9), "cut")
            nc += 1
            break

    # ---- 2: door spurs from buildings ---------------------------------------------------------------------------
    nd = 0
    frac(0.18, "worn paths")
    for bi_, b in enumerate(buildings):
        if bi_ % 512 == 0:
            frac(0.18 + 0.01 * bi_ / max(1, len(buildings)), "worn paths")
        if b["area"] < 120 or rnd.random() > 0.12:
            continue
        ring = b["ring"]
        cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
        best = None
        for p, q in zip(ring, ring[1:] + ring[:1]):
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            if L < 4:
                continue
            mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            nxv, nyv = (q[1] - p[1]) / L, -(q[0] - p[0]) / L
            if nxv * (mx - cx) + nyv * (my - cy) < 0:
                nxv, nyv = -nxv, -nyv
            dx_, dy_ = mx + nxv * 1.0, my + nyv * 1.0
            for d, si in near(dx_, dy_, 6.0, 40.0):
                if si not in used and (best is None or d < best[0]):
                    best = (d, si, dx_, dy_)
        if best is None:
            continue
        d, si, dx_, dy_ = best
        if near(dx_, dy_, 0.0, 5.5):
            continue                                                # a real path already passes the door
        pl = route((dx_, dy_), (S[si][0], S[si][1]), True)
        if pl is None:
            continue
        emit(pl[::-1], si, None, rnd.uniform(1.0, 1.5), "door")
        nd += 1

    # ---- 3: spurs to POIs on open ground ------------------------------------------------------------------------
    npoi = 0
    for q in pois:
        x, y = q[0], q[1]
        if at(bld_d, x, y) or at(road_m, x, y) or at(hard, x, y) or rnd.random() > 0.35:
            continue
        c = [(d, si) for d, si in near(x, y, 7.0, 55.0) if si not in used]
        if not c:
            continue
        d, si = min(c)
        pl = route((x, y), (S[si][0], S[si][1]), False)
        if pl is None:
            continue
        emit(pl[::-1], si, None, rnd.uniform(1.2, 1.7), "poi")
        npoi += 1

    for ri, lst in inserts.items():
        r2 = roads[ri]
        for k, t, nid_, pt in sorted(lst, key=lambda q: (q[0], q[1]), reverse=True):
            r2["pts"].insert(k + 1, pt)
            r2["nodes"].insert(k + 1, nid_)
    print(f"[build] worn footpaths: {len(out)} ({nc} shortcuts, {nd} building spurs, {npoi} POI spurs)")
    return out
