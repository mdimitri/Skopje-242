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


WALK_W = {"footway": 1.2, "path": 0.9, "pedestrian": 2.0, "steps": 1.0, "cycleway": 1.3, "track": 1.0}


def bridge_mesh(m, B, decks, cx, cy, base, gfn=None):
    """Elevated carriageways at their real deck heights: asphalt, 2.4 m pavements with kerbs, parapets, soffit and piers."""
    for d in B:
        e, ln, hw = d["e"], d["ln"], d["hw"]
        deck = decks.get(e["road"])
        if deck is None or ln.length < 4:
            continue
        n = max(2, int(ln.length / 2.0))
        P, H, F, F2 = [], [], [], []
        for i in range(n + 1):
            p = ln.interpolate(ln.length * i / n)
            q = ln.interpolate(min(ln.length, ln.length * i / n + 1.0))
            r = ln.interpolate(max(0.0, ln.length * i / n - 1.0))
            tx, ty = q.x - r.x, q.y - r.y
            l = math.hypot(tx, ty) or 1.0
            P.append((p.x, p.y))
            F.append((-ty / l, tx / l))
            H.append(float(deck.at(p.x + cx, p.y + cy)[0]) - base)
            F2.append(gfn(p.x, p.y) if gfn else 0.0)
        Ha = np.array(H)
        k = 6
        Hp = np.concatenate([np.full(k, Ha[0]), Ha, np.full(k, Ha[-1])])
        H = list(np.convolve(Hp, np.ones(2 * k + 1) / (2 * k + 1), "valid"))
        # ramp down to the ground over the last 30 m wherever the deck ends on a ground road
        Ha = np.array(H)
        G = np.array(F2)
        Ha = np.maximum(Ha, G)
        s_ = np.linspace(0.0, ln.length, n + 1)
        for end, node in ((0, e["a"]), (1, e["b"])):
            if node in d.get("gnodes", ()) and abs(Ha[0 if end == 0 else -1] - G[0 if end == 0 else -1]) > 0.5:
                t = np.clip((s_ if end == 0 else ln.length - s_) / 30.0, 0, 1)
                t = t * t * (3 - 2 * t)
                Ha = G + (Ha - G) * t
        H = list(Ha)
        SWB = 2.4
        inner = 0  # side (+1/-1 along F) facing a twin carriageway: no pavement there
        if e["ow"]:
            mid = ln.interpolate(ln.length / 2)
            best = 25.0
            for o in B:
                if o is d or not o["e"]["ow"]:
                    continue
                dd = o["ln"].distance(mid)
                if dd < best:
                    best = dd
                    q = o["ln"].interpolate(o["ln"].project(mid))
                    k = int(n / 2)
                    inner = 1 if (q.x - mid.x) * F[k][0] + (q.y - mid.y) * F[k][1] > 0 else -1
        def edge(off):
            return [(p[0] + f[0] * off, p[1] + f[1] * off) for p, f in zip(P, F)]
        def quadstrip(o0, o1, dy, col):
            A, Bb = edge(o0), edge(o1)
            for i in range(n):
                m.quad((A[i][0], H[i] + dy, A[i][1]), (A[i + 1][0], H[i + 1] + dy, A[i + 1][1]), (Bb[i + 1][0], H[i + 1] + dy, Bb[i + 1][1]), (Bb[i][0], H[i] + dy, Bb[i][1]), col)
        def vwall(o, y0, y1, col):
            A = edge(o)
            for i in range(n):
                m.quad((A[i][0], H[i] + y0, A[i][1]), (A[i + 1][0], H[i + 1] + y0, A[i + 1][1]), (A[i + 1][0], H[i + 1] + y1, A[i + 1][1]), (A[i][0], H[i] + y1, A[i][1]), col)
        quadstrip(-hw, hw, 0.0, ASPH)
        for sg in (-1, 1):
            if sg == inner:
                vwall(sg * hw, -1.1, 1.05, (196, 194, 188))
                quadstrip(sg * (hw - 0.3), sg * hw, 1.05, (214, 212, 206))
                continue
            quadstrip(sg * hw, sg * (hw + SWB), KERB, KTOP)
            vwall(sg * hw, 0.0, KERB, KFACE)
            A = edge(sg * (hw + SWB))
            for i in range(n):
                t0, t1 = min(1.05, KERB + 0.3 * (H[i] - G[i])), min(1.05, KERB + 0.3 * (H[i + 1] - G[i + 1]))
                m.quad((A[i][0], H[i] - 1.1, A[i][1]), (A[i + 1][0], H[i + 1] - 1.1, A[i + 1][1]), (A[i + 1][0], H[i + 1] + t1, A[i + 1][1]), (A[i][0], H[i] + t0, A[i][1]), (196, 194, 188))
            for i in range(n):
                if H[i] - G[i] < 6.0 and H[i + 1] - G[i + 1] < 6.0:
                    A = edge(sg * (hw + SWB))
                    m.quad((A[i][0], G[i] - 0.3, A[i][1]), (A[i + 1][0], G[i + 1] - 0.3, A[i + 1][1]), (A[i + 1][0], H[i + 1] - 1.1, A[i + 1][1]), (A[i][0], H[i] - 1.1, A[i][1]), (178, 176, 170))
            A0, A1 = edge(sg * (hw + SWB - 0.25)), edge(sg * (hw + SWB))
            for i in range(n):
                t0, t1 = min(1.05, KERB + 0.3 * (H[i] - G[i])), min(1.05, KERB + 0.3 * (H[i + 1] - G[i + 1]))
                m.quad((A0[i][0], H[i] + t0, A0[i][1]), (A0[i + 1][0], H[i + 1] + t1, A0[i + 1][1]), (A1[i + 1][0], H[i + 1] + t1, A1[i + 1][1]), (A1[i][0], H[i] + t0, A1[i][1]), (214, 212, 206))
            quadstrip(sg * (hw - 0.45), sg * (hw - 0.31), 0.05, WHITE)
        if not e["ow"]:
            quadstrip(-0.07, 0.07, 0.05, WHITE)
        quadstrip(-hw - (0 if inner == -1 else SWB), hw + (0 if inner == 1 else SWB), -1.1, (150, 148, 142))
        for i in range(2, n - 1, 10):
            if H[i] - G[i] > 3.5:
                m.box(P[i][0], G[i] - 0.3, P[i][1], 1.8, H[i] - 1.1 - G[i] + 0.3, 2 * (hw + SWB) - 1.0, (176, 174, 168), math.atan2(F[i][0], -F[i][1]) + math.pi / 2)
        for i in range(3, n - 2, 12):
            for sg in (-1, 1):
                x, z = P[i][0] + F[i][0] * sg * (hw + SWB - 0.9), P[i][1] + F[i][1] * sg * (hw + SWB - 0.9)
                m.cyl(x, H[i] + KERB, H[i] + 8.0, z, 0.1, jd.POLE, 6)


def bridge_lanes(edges):
    """Lanes per direction for every bridge edge, taken from the road that continues onto it at either end
    (a bridge never has fewer or more lanes than its approaches), shared by the whole bridge."""
    at = {}
    for e in edges:
        if e["drive"] and not e["bridge"]:
            at.setdefault(e["a"], []).append(e)
            at.setdefault(e["b"], []).append(e)
    groups = {}
    for e in edges:
        if e["drive"] and e["bridge"]:
            groups.setdefault(e["road"], []).append(e)
    out = {}
    for road, G in groups.items():
        nodes = {n for e in G for n in (e["a"], e["b"])}
        cnt = {}
        for e in G:
            cnt[e["a"]] = cnt.get(e["a"], 0) + 1
            cnt[e["b"]] = cnt.get(e["b"], 0) + 1
        ends = [n for n in nodes if cnt[n] == 1]
        cand = [per_dir(a) for n in ends for a in at.get(n, []) if a["ow"] == G[0]["ow"] and a["cls"] == G[0]["cls"]]
        own = max(per_dir(e) for e in G)
        out[road] = max(cand) if cand else own
    return out


def _out_dir(ln, start):
    c = list(ln.coords)
    a, b = (c[0], c[min(len(c) - 1, 2)]) if start else (c[-1], c[max(0, len(c) - 3)])
    dx, dy = b[0] - a[0], b[1] - a[1]
    l = math.hypot(dx, dy) or 1.0
    return dx / l, dy / l


def ribbon(d, inc, T=36.0):
    """Carriageway ribbon whose half-width eases (smoothstep) from its own to the width of the wider road it continues
    or splits from at each end node, so lane counts change by tapering, never by a step."""
    ln, hw, e = d["ln"], d["hw"], d["e"]
    ends = [hw, hw]
    for k, (node, start) in enumerate(((e["a"], True), (e["b"], False))):
        ux, uy = _out_dir(ln, start)
        for o in inc.get(node, ()):
            if o is d or o["hw"] <= ends[k]:
                continue
            ox, oy = _out_dir(o["ln"], o["e"]["a"] == node)
            if abs(ux * ox + uy * oy) > 0.8:
                ends[k] = o["hw"]
    if ends[0] == hw and ends[1] == hw or ln.length < 6:
        return ln.buffer(hw, cap_style=1, join_style=1, resolution=16)
    L = ln.length
    Tt = min(T, L * 0.5)
    n = max(2, int(L / 1.5))
    discs = []
    for i in range(n + 1):
        s_ = L * i / n
        r = hw
        for end, dist in ((0, s_), (1, L - s_)):
            if ends[end] > hw and dist < Tt:
                t = dist / Tt
                t = t * t * (3 - 2 * t)
                r = max(r, hw + (ends[end] - hw) * (1 - t))
        pt = ln.interpolate(s_)
        discs.append(pt.buffer(r, resolution=8))
    return unary_union([unary_union([discs[i], discs[i + 1]]).convex_hull for i in range(n)])


def build(edges, cx, cy, buildings=(), decks=None, T=None):
    E, B, W = [], [], []
    BL = bridge_lanes(edges)
    gn = {n for e in edges if e["drive"] and not e["bridge"] for n in (e["a"], e["b"])}
    for e in edges:
        if not e["drive"] and not e["bridge"] and e["cls"] in WALK_W and len(e["pts"]) >= 2:
            P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
            if min(math.hypot(p[0], p[1]) for p in P) < RANGE:
                W.append({"e": e, "ln": LineString(P), "hw": WALK_W[e["cls"]]})
            continue
        if e["drive"] and e["bridge"]:
            P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
            if len(P) >= 2 and min(math.hypot(p[0], p[1]) for p in P) < RANGE + 30:
                nb = BL.get(e["road"], per_dir(e))
                B.append({"e": e, "ln": LineString(P), "hw": nb * LW / 2 if e["ow"] else nb * LW, "per": nb, "gnodes": gn})
            continue
        if not e["drive"]:
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
    ribs = [ribbon(d, inc) for d in E]
    # dead ends get a turning bulb (cul-de-sac) instead of a bare round cap
    for n, L in inc.items():
        if len(L) == 1 and L[0]["ln"].length > 20:
            d = L[0]
            start = d["e"]["a"] == n
            ux, uy = _out_dir(d["ln"], start)
            end = d["ln"].coords[0] if start else d["ln"].coords[-1]
            if math.hypot(end[0], end[1]) > RANGE - 15:
                continue                                  # cut off by the window, not a real dead end
            rb = max(d["hw"] + 4.5, 10.0)
            bx, by = end[0] + ux * rb * 0.6, end[1] + uy * rb * 0.6   # centre sits inside the road so the bulb stands 0.4 r proud
            ribs.append(Point(bx, by).buffer(rb, resolution=24))
    U = unary_union(ribs)
    C = U.buffer(R_KERB, resolution=16).buffer(-R_KERB, resolution=16).simplify(0.04)
    gap = C.difference(U)
    isl = gap.buffer(-1.3, resolution=6).buffer(1.3, resolution=6).intersection(gap)
    isl = unary_union([p for p in polys_of(isl) if p.area > 6.0])
    asph = C.difference(isl)
    pave = asph.buffer(SW, resolution=10).difference(asph).difference(isl)
    clip = Polygon([(-RANGE, -RANGE), (RANGE, -RANGE), (RANGE, RANGE), (-RANGE, RANGE)])
    asph, pave, isl = asph.intersection(clip), pave.intersection(clip), isl.intersection(clip)
    m = Mesh()
    tbase = float(T.h(cx, cy)) if T is not None else 0.0
    gfn = (lambda x, z: float(T.h(x + cx, z + cy)) - tbase) if T is not None else None
    m.gfn = gfn
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
            tri_poly(m, q, KERB + 0.10, GRASS)
        walls_of(m, p, 0.0, KERB, KFACE)
    if W and B:
        corr = unary_union([d["ln"].buffer(d["hw"] + 2.6) for d in B])
        W = [w for w in W if w["ln"].intersection(corr).length < 0.5 * w["ln"].length]
    if W:
        foot = unary_union([w["ln"].buffer(w["hw"], cap_style=1, resolution=6) for w in W if w["e"]["cls"] != "cycleway"])
        cyc = unary_union([w["ln"].buffer(w["hw"], cap_style=1, resolution=6) for w in W if w["e"]["cls"] == "cycleway"])
        cut = asph.union(isl)
        stroke(m, foot.difference(cut).intersection(clip), KERB + 0.05, (214, 210, 202))
        cyc = cyc.difference(cut).intersection(clip)
        stroke(m, cyc, KERB + 0.09, (176, 92, 84))
        # footpaths and cycleways cross carriageways only as zebra crossings
        bars = []
        road_only = asph.difference(isl)
        for w in W:
            seg = w["ln"].intersection(road_only)
            for g in (getattr(seg, "geoms", [seg])):
                if g.is_empty or g.geom_type != "LineString" or not 3.0 <= g.length <= 28.0:
                    continue
                c0, c1 = g.coords[0], g.coords[-1]
                L = g.length
                if w["ln"].project(Point(c0)) < 2.0 or w["ln"].project(Point(c1)) > w["ln"].length - 2.0 or w["ln"].project(Point(c0)) > w["ln"].project(Point(c1)) and w["ln"].project(Point(c1)) < 2.0:
                    continue                                    # path starts or ends at the road: no crossing
                if g.intersection(road_only.boundary.buffer(1.8)).length > 0.35 * L:
                    continue                                    # runs along the kerb, not across
                ux, uy = (c1[0] - c0[0]) / L, (c1[1] - c0[1]) / L
                nx, ny = -uy, ux
                k = 0.6
                while k < L - 0.5:
                    cx_, cy_ = c0[0] + ux * k, c0[1] + uy * k
                    hl, hb = 1.5, 0.25
                    bars.append(Polygon([(cx_ - nx * hl - ux * hb, cy_ - ny * hl - uy * hb), (cx_ + nx * hl - ux * hb, cy_ + ny * hl - uy * hb),
                                         (cx_ + nx * hl + ux * hb, cy_ + ny * hl + uy * hb), (cx_ - nx * hl + ux * hb, cy_ - ny * hl + uy * hb)]))
                    k += 1.0
        if bars:
            stroke(m, unary_union(bars).intersection(road_only).intersection(clip), 0.06, WHITE)
        for w in W:
            if w["e"]["cls"] != "cycleway":
                continue
            s_ = 6.0
            while s_ < w["ln"].length - 3:
                p = w["ln"].interpolate(s_)
                q = w["ln"].interpolate(min(w["ln"].length, s_ + 1.0))
                tx, ty = q.x - p.x, q.y - p.y
                l = math.hypot(tx, ty) or 1.0
                tx, ty = tx / l, ty / l
                nx, ny = -ty, tx
                for off in (-0.55, 0.55):                     # bicycle glyph: two wheels and a frame
                    wx, wy = p.x + tx * off, p.y + ty * off
                    ring = Point(wx, wy).buffer(0.32, resolution=6).difference(Point(wx, wy).buffer(0.24, resolution=6))
                    stroke(m, ring, KERB + 0.14, WHITE)
                stroke(m, LineString([(p.x - tx * 0.55, p.y - ty * 0.55), (p.x, p.y + 0.0), (p.x + tx * 0.55, p.y + ty * 0.55)]).buffer(0.05), KERB + 0.14, WHITE)
                s_ += 25.0
    if B and decks:
        base = min(float(decks[d["e"]["road"]].at(*d["ln"].coords[0][:2] if False else (d["ln"].coords[0][0] + cx, d["ln"].coords[0][1] + cy))[0]) for d in B if d["e"]["road"] in decks) if any(d["e"]["road"] in decks for d in B) else 0.0
        if T is not None:
            base = tbase
        m.gfn = None
        bridge_mesh(m, B, decks, cx, cy, base, gfn)
        m.gfn = gfn
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
            lines = [path] if isinstance(path, LineString) else list(getattr(path, "geoms", []))
            parts = [q for ln_ in lines for q in (dashed_segments(ln_) if dash else [ln_])]
            for s_ in parts:
                if s_.is_empty or s_.length < 0.3:
                    continue
                for g in (s_.buffer(w / 2, cap_style=2).intersection(zone),):
                    stroke(m, g, 0.05, WHITE)
        if e["ow"]:
            for k in range(1, per):
                paint(-hw + LW * k, 0.15, True)
        else:
            if per >= 2:
                paint(0.14, 0.11)
                paint(-0.14, 0.11)
            else:
                paint(0.0, 0.14, True)
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
                raised = Polygon([a, b, (b[0] + tx * 3.0, b[1] + ty * 3.0), (a[0] + tx * 3.0, a[1] + ty * 3.0)]).intersection(isl)
                stroke(m, raised, KERB + 0.07, (222, 220, 214))
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
        g0 = gfn(poly.centroid.x, poly.centroid.y) if gfn else 0.0
        top += g0
        m.gfn = None
        for i in range(len(pts)):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % len(pts)]
            m.quad((ax, g0 - 2.0, ay), (bx, g0 - 2.0, by), (bx, top, by), (ax, top, ay), (200, 194, 184))
        tri_poly(m, poly, top, (170, 164, 156))
        m.gfn = gfn
    m.quad((-300, -0.3, -300), (300, -0.3, -300), (300, -0.3, 300), (-300, -0.3, 300), jd.GROUND)
    return m


def main():
    dump = pickle.load(open(sys.argv[1], "rb"))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    import junction_scenes as js
    for i, a in enumerate(sys.argv[3:]):
        cx, cy = (float(v) for v in a.split(","))
        m = build(dump["edges"], cx, cy, dump.get("buildings", ()), dump.get("decks"), dump.get("T"))
        js.render(m, out, {"top": ((0, 150, -1), (0, 0, 0)), "aerial": ((60, 85, -85), (0, 0, 0))}, f"net{i}")
        print("done", i, cx, cy, len(m.P) // 3, "tris")


if __name__ == "__main__":
    main()
