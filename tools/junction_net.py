"""Network-based junction designer: takes the REAL edges around a point and redraws them cleanly.

The asphalt is the union of all nearby carriageway ribbons, closed with a kerb radius (rounded concave corners). Gaps
wider than ~2.6 m that survive the closing are raised islands/medians (slip-road triangles, splitter islands, boulevard
medians) -- found from the real geometry, not guessed.  Pavements, kerbs, lane paint, zebras, stop lines, arrows, lamps,
trees and signals follow the real edges.

    xvfb-run -a python tools/junction_net.py dump.pkl out_dir x,y [x,y ...]
"""
import math
import os
import pickle
import sys

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import substring, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "src"))
import mapbox_earcut as earcut  # noqa: E402
import junction_design as jd  # noqa: E402
from junction_design import ASPH, GRASS, KERB, KFACE, KTOP, LW, SW, WHITE, Mesh  # noqa: E402

CAP = {"motorway": 3, "trunk": 3, "primary": 3, "secondary": 3, "tertiary": 3, "unclassified": 1, "residential": 1,
       "living_street": 1, "service": 1}
R_KERB = 7.0
RANGE = 120.0


def per_dir(e):
    cls = e["cls"].replace("_link", "")
    cap = CAP.get(cls, 1)
    if e["cls"].endswith("_link"):
        cap = 1
    if e["ow"]:
        n = e["lanes"] or max(1, round(e["w"] / 3.5))
        return max(1, min(n, cap if cls != "tertiary" else 3))
    dl = e.get("directional_lanes")
    n = max(dl) if dl else max(1, (e["lanes"] or round(e["w"] / 3.5)) // 2)
    return max(1, min(n, 2 if cls == "tertiary" else cap))


def half_w(e):
    n = per_dir(e)
    return n * LW / 2 if e["ow"] else n * LW


def polys_of(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def tri_poly(m, poly, y, col):
    ext = list(poly.exterior.coords)[:-1]
    ring_ends = [len(ext)]
    pts = list(ext)
    for h in poly.interiors:
        c = list(h.coords)[:-1]
        pts += c
        ring_ends.append(len(pts))
    v = np.array(pts, np.float64)
    try:
        idx = np.array(earcut.triangulate_float64(v, np.array(ring_ends, np.uint32))).reshape(-1, 3)
    except Exception:  # noqa: BLE001
        return
    for t in idx:
        m.tri((v[t[0]][0], y, v[t[0]][1]), (v[t[1]][0], y, v[t[1]][1]), (v[t[2]][0], y, v[t[2]][1]), col)


def walls_of(m, poly, y0, y1, col):
    m.wall([tuple(c) for c in poly.exterior.coords], y0, y1, col)
    for h in poly.interiors:
        m.wall([tuple(c) for c in h.coords], y0, y1, col)


def stroke(m, g, y, col):
    for p in polys_of(g):
        tri_poly(m, p, y, col)


def dashed_segments(line, dash=3.0, gap=6.0, start=1.0):
    out, s = [], start
    L = line.length
    while s + dash <= L:
        out.append(substring(line, s, s + dash))
        s += dash + gap
    return out


def build(edges, cx, cy, buildings=()):
    E = []
    for e in edges:
        if not e["drive"] or e["bridge"]:
            continue
        P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
        if min(math.hypot(p[0], p[1]) for p in P) > RANGE + 30 or len(P) < 2:
            continue
        ln = LineString(P)
        if ln.length < 3.0:
            continue
        E.append({"e": e, "ln": ln, "hw": half_w(e), "per": per_dir(e)})
    # junction nodes: >= 3 incident drive edges
    inc = {}
    for d in E:
        inc.setdefault(d["e"]["a"], []).append(d)
        inc.setdefault(d["e"]["b"], []).append(d)
    nodes = {n: L for n, L in inc.items() if len(L) >= 3}
    ribs = [d["ln"].buffer(d["hw"], cap_style=1, join_style=1, resolution=8) for d in E]
    U = unary_union(ribs)
    C = U.buffer(R_KERB, resolution=12).buffer(-R_KERB, resolution=12)
    gap = C.difference(U)
    isl = gap.buffer(-1.3, resolution=6).buffer(1.3, resolution=6).intersection(gap)
    isl = unary_union([p for p in polys_of(isl) if p.area > 6.0])
    asph = C.difference(isl)
    pave = asph.buffer(SW, resolution=10).difference(asph).difference(isl)
    clip = Polygon([(-RANGE, -RANGE), (RANGE, -RANGE), (RANGE, RANGE), (-RANGE, RANGE)])
    asph, pave, isl = asph.intersection(clip), pave.intersection(clip), isl.intersection(clip)
    m = Mesh()
    for p in polys_of(asph):
        tri_poly(m, p, 0.0, ASPH)
    for p in polys_of(pave):
        tri_poly(m, p, KERB, KTOP)
    for p in polys_of(asph):
        walls_of(m, p, 0.0, KERB, KFACE) if False else None
    for p in polys_of(pave):
        pass
    # kerb faces: along the boundary between asphalt and pavement / island
    for p in polys_of(asph):
        for ring in [p.exterior] + list(p.interiors):
            m.wall([tuple(c) for c in ring.coords], 0.0, KERB, KFACE)
    for p in polys_of(isl):
        tri_poly(m, p, KERB, KTOP)
        ins = p.buffer(-0.35)
        for q in polys_of(ins):
            tri_poly(m, q, KERB + 0.04, GRASS)
        walls_of(m, p, 0.0, KERB, KFACE)
    # paint zone: asphalt without junction cores and islands
    core = unary_union([Point(0, 0).buffer(0)] + [Point(L[0]["ln"].coords[0] if L[0]["e"]["a"] == n else L[0]["ln"].coords[-1]).buffer(9.0 + max(d["hw"] for d in L)) for n, L in nodes.items()])
    zone = asph.difference(core).difference(isl.buffer(0.3))
    for d in E:
        ln, hw, per, e = d["ln"], d["hw"], d["per"], d["e"]
        if ln.length < 12:
            continue
        def paint(off, w, dash=False):
            try:
                path = shapely.offset_curve(ln, off) if abs(off) > 1e-6 else ln
            except Exception:  # noqa: BLE001
                return
            parts = dashed_segments(path) if dash else [path]
            for s_ in parts:
                if s_.is_empty or s_.length < 0.3:
                    continue
                for g in (s_.buffer(w / 2, cap_style=2).intersection(zone),):
                    stroke(m, g, 0.05, WHITE)
        if e["ow"]:
            for k in range(1, per):
                paint(-hw + LW * k, 0.15, True)
        else:
            if per >= 1:
                paint(0.0, 0.15)
            for k in range(1, per):
                paint(LW * k, 0.15, True)
                paint(-LW * k, 0.15, True)
        paint(hw - 0.35, 0.14)
        paint(-(hw - 0.35), 0.14)
    # crossings, stop lines and arrows at the mouth of every junction
    for n, L in nodes.items():
        c0 = L[0]["ln"].coords[0] if L[0]["e"]["a"] == n else L[0]["ln"].coords[-1]
        r_core = 9.0 + max(d["hw"] for d in L)
        for d in L:
            e, ln, hw = d["e"], d["ln"], d["hw"]
            out_line = ln if e["a"] == n else LineString(list(ln.coords)[::-1])
            if out_line.length < r_core + 20:
                continue
            def at(s_):
                p = out_line.interpolate(s_)
                q = out_line.interpolate(min(out_line.length, s_ + 1.0))
                tx, ty = q.x - p.x, q.y - p.y
                l = math.hypot(tx, ty) or 1.0
                return p.x, p.y, tx / l, ty / l
            x, y, tx, ty = at(r_core + 3.5)
            nx, ny = -ty, tx
            k = -hw + 0.6
            while k < hw - 0.3:
                a = (x + nx * (k - 0.25), y + ny * (k - 0.25))
                b = (x + nx * (k + 0.25), y + ny * (k + 0.25))
                poly = Polygon([a, b, (b[0] + tx * 3.0, b[1] + ty * 3.0), (a[0] + tx * 3.0, a[1] + ty * 3.0)]).intersection(asph.difference(isl))
                stroke(m, poly, 0.05, WHITE)
                k += 1.0
            inbound = (not e["ow"]) or (e["b"] == n)
            if inbound:
                x, y, tx, ty = at(r_core + 8.0)
                nx, ny = -ty, tx
                lo, hi = (0.0, hw) if not e["ow"] else (-hw, hw)       # inbound lanes are on the left of the outward line
                a = (x + nx * lo, y + ny * lo)
                b = (x + nx * hi, y + ny * hi)
                poly = Polygon([a, b, (b[0] + tx * 0.5, b[1] + ty * 0.5), (a[0] + tx * 0.5, a[1] + ty * 0.5)]).intersection(asph.difference(isl))
                stroke(m, poly, 0.05, WHITE)
                for ds in (15.0, 32.0):
                    if r_core + ds + 3 > out_line.length:
                        continue
                    for lane in range(d["per"]):
                        off = (lane + 0.5) * LW if not e["ow"] else -hw + (lane + 0.5) * LW
                        x, y, tx, ty = at(r_core + ds)
                        nx, ny = -ty, tx
                        px, py = x + nx * off, y + ny * off
                        # arrow points toward the junction: -t
                        fx, fy = -tx, -ty
                        rx, ry = -fy, fx
                        sh = [(px - fx * 1.8 + rx * 0.14, py - fy * 1.8 + ry * 0.14), (px + rx * 0.14, py + ry * 0.14), (px - rx * 0.14, py - ry * 0.14), (px - fx * 1.8 - rx * 0.14, py - fy * 1.8 - ry * 0.14)]
                        stroke(m, Polygon(sh).intersection(zone), 0.05, WHITE)
                        hd = [(px + fx * 1.2, py + fy * 1.2), (px + rx * 0.55, py + ry * 0.55), (px - rx * 0.55, py - ry * 0.55)]
                        stroke(m, Polygon(hd).intersection(zone), 0.05, WHITE)
    # street furniture on the pavements
    def free(p, r=0.5):
        return pave.buffer(0.01).contains(Point(p)) and not asph.buffer(r).contains(Point(p))
    for d in E:
        ln, hw = d["ln"], d["hw"]
        s_ = 10.0
        while s_ < ln.length - 5:
            p = ln.interpolate(s_)
            q = ln.interpolate(s_ + 1.0)
            tx, ty = q.x - p.x, q.y - p.y
            l = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / l, tx / l
            for side in (-1, 1):
                lp = (p.x + nx * side * (hw + SW - 0.8), p.y + ny * side * (hw + SW - 0.8))
                if free(lp) and (int(s_ / 30) % 2 == (0 if side == 1 else 1)) and abs(p.x) < RANGE and abs(p.y) < RANGE:
                    m.cyl(lp[0], KERB, 8.0, lp[1], 0.1, jd.POLE, 6)
                    ax, ay = lp[0] - nx * side * 1.8, lp[1] - ny * side * 1.8
                    m.box((lp[0] + ax) / 2, 7.9, (lp[1] + ay) / 2, 1.9, 0.1, 0.1, jd.POLE, math.atan2(ay - lp[1], ax - lp[0]))
                    m.box(ax, 7.8, ay, 0.5, 0.15, 0.25, (240, 232, 190), math.atan2(ay - lp[1], ax - lp[0]))
                tp = (p.x + nx * side * (hw + SW + 1.8), p.y + ny * side * (hw + SW + 1.8))
                if (int(s_ / 18) % 2 == 0) and not pave.buffer(0.5).contains(Point(tp)) and not asph.buffer(1.5).contains(Point(tp)) and abs(tp[0]) < RANGE and abs(tp[1]) < RANGE:
                    if int(s_) % 3 == 0:
                        m.cyl(tp[0], 0, 2.4, tp[1], 0.12, (96, 76, 58), 6)
                        m.octa(tp[0], 2.1, tp[1], 1.6, 2.1, (74, 128, 68))
            s_ += 6.0
    for n, L in nodes.items():
        if len(L) < 4 and not any(d["per"] >= 2 for d in L):
            continue
        r_core = 9.0 + max(d["hw"] for d in L)
        for d in L:
            e, ln, hw = d["e"], d["ln"], d["hw"]
            inbound = (not e["ow"]) or (e["b"] == n)
            if not inbound:
                continue
            out_line = ln if e["a"] == n else LineString(list(ln.coords)[::-1])
            if out_line.length < r_core + 12:
                continue
            p = out_line.interpolate(r_core + 10.0)
            q = out_line.interpolate(r_core + 11.0)
            tx, ty = q.x - p.x, q.y - p.y
            l = math.hypot(tx, ty) or 1.0
            tx, ty = tx / l, ty / l
            nx, ny = -ty, tx
            side = 1                                         # inbound lanes are on the left of the outward line
            pole = (p.x + nx * (hw + SW - 0.9), p.y + ny * (hw + SW - 0.9)) if not e["ow"] else (p.x + nx * (hw + SW - 0.9), p.y + ny * (hw + SW - 0.9))
            if not pave.buffer(0.2).contains(Point(pole)):
                continue
            m.cyl(pole[0], KERB, 4.2, pole[1], 0.1, jd.POLE, 8)
            jd.signal_head(m, pole[0], pole[1], math.atan2(ty, tx) + math.pi / 2, (hash(n) % 2) == 0)
    # context: buildings away from the roads
    keep = asph.buffer(SW + 2.0)
    for ring, h in buildings:
        pts = [(x - cx, y - cy) for x, y in ring]
        if len(pts) < 3 or abs(pts[0][0]) > RANGE or abs(pts[0][1]) > RANGE:
            continue
        try:
            poly = Polygon(pts)
            if not poly.is_valid or poly.intersects(keep):
                continue
        except Exception:  # noqa: BLE001
            continue
        top = min(float(h), 30.0)
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % len(pts)]
            m.quad((ax, 0.0, ay), (bx, 0.0, by), (bx, top, by), (ax, top, ay), (200, 194, 184))
        tri_poly(m, poly, top, (170, 164, 156))
    m.quad((-300, -0.3, -300), (300, -0.3, -300), (300, -0.3, 300), (-300, -0.3, 300), jd.GROUND)
    return m


def main():
    dump = pickle.load(open(sys.argv[1], "rb"))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    import junction_scenes as js
    for i, a in enumerate(sys.argv[3:]):
        cx, cy = (float(v) for v in a.split(","))
        m = build(dump["edges"], cx, cy, dump.get("buildings", ()))
        js.render(m, out, {"top": ((0, 150, -1), (0, 0, 0)), "aerial": ((60, 85, -85), (0, 0, 0))}, f"net{i}")
        print("done", i, cx, cy, len(m.P) // 3, "tris")


if __name__ == "__main__":
    main()
