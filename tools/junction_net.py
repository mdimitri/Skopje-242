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
MARGIN = 60.0                                        # edges this far beyond the window still shape what is inside it


def per_dir(e):
    """Lanes per direction (the larger direction of a two-way road), from the graph's lane standard
    (tools/roadclean.standardise)."""
    from roadwidth import lane_count
    if e["ow"]:
        return lane_count(e)
    return max(lane_count(e, 1), lane_count(e, -1))


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


def _wall_ring(m, ring, y0, y1, col, half=None):
    """Kerb face along a ring; with `half` the artificial edges where the window clips the geometry are left out."""
    c = [tuple(q) for q in ring.coords]
    if half is None:
        m.wall(c, y0, y1, col)
        return
    run = [c[0]]
    for a, b in zip(c, c[1:]):
        on = (abs(abs(a[0]) - half) < 1e-3 and abs(abs(b[0]) - half) < 1e-3 and (a[0] > 0) == (b[0] > 0)) or \
             (abs(abs(a[1]) - half) < 1e-3 and abs(abs(b[1]) - half) < 1e-3 and (a[1] > 0) == (b[1] > 0))
        if on:
            if len(run) > 1:
                m.wall(run, y0, y1, col)
            run = [b]
        else:
            run.append(b)
    if len(run) > 1:
        m.wall(run, y0, y1, col)


def context(edges):
    """Whole-network facts the per-window build needs (computed once): bridge lanes, nodes under bridges, node degrees."""
    gdeg = {}
    for e in edges:
        if e["drive"] and not e["bridge"]:
            gdeg[e["a"]] = gdeg.get(e["a"], 0) + 1
            gdeg[e["b"]] = gdeg.get(e["b"], 0) + 1
    bn = {n for e in edges if e["drive"] and e["bridge"] for n in (e["a"], e["b"])}
    return {"BL": bridge_lanes(edges), "gn": set(gdeg), "gdeg": gdeg, "bn": bn}


def regularise(E, join=35.0, straight=40.0):
    """Drawing-only clean-up of the OSM junction geometry: nearby junction nodes (joined by short edges) become one
    junction, the arms leave it on straight approaches, and opposite arms of a road carry the same lanes.  Works on
    copies of the edge dicts, so the traffic graph is untouched."""
    deg = {}
    for d in E:
        for k in ("a", "b"):
            deg[d["e"][k]] = deg.get(d["e"][k], 0) + 1
    jn_nodes = {n for n, c in deg.items() if c >= 3}
    parent = {n: n for n in jn_nodes}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    internal = set()
    for i, d in enumerate(E):
        a, b = d["e"]["a"], d["e"]["b"]
        if a in jn_nodes and b in jn_nodes and a != b and d["ln"].length < join:
            parent[find(a)] = find(b)
            internal.add(i)
    members = {}
    for n in jn_nodes:
        members.setdefault(find(n), []).append(n)
    where = {}
    for d in E:
        c = d["ln"].coords
        where[d["e"]["a"]] = c[0]
        where[d["e"]["b"]] = c[-1]
    centre = {}
    for root, ns in members.items():
        xs = [where[n] for n in ns if n in where]
        centre[root] = (sum(p[0] for p in xs) / len(xs), sum(p[1] for p in xs) / len(xs))
    out = []
    for i, d in enumerate(E):
        if i in internal:
            continue
        e = dict(d["e"])
        ln = d["ln"]
        pts = list(ln.coords)
        for end, key in ((0, "a"), (1, "b")):
            n = e[key]
            if n not in jn_nodes:
                continue
            root = find(n)
            c = centre[root]
            e[key] = root
            L = ln.length
            if L < straight + 12:
                pts = [c] + pts[1:] if end == 0 else pts[:-1] + [c]
                continue
            # straight approach: centre -> the point `straight` metres out, then the original line
            if end == 0:
                q = ln.interpolate(straight)
                rest = [p for p in pts if LineString(pts).project(Point(p)) > straight]
                pts = [c, (q.x, q.y)] + rest
            else:
                q = ln.interpolate(L - straight)
                rest = [p for p in pts if LineString(pts).project(Point(p)) < L - straight]
                pts = rest + [(q.x, q.y), c]
            ln = LineString(pts)
        if len(pts) < 2:
            continue
        nd = dict(d)
        nd["e"] = e
        nd["ln"] = LineString(pts)
        out.append(nd)
    # opposite arms of one road: the wider lane count on both sides of the junction
    at = {}
    for d in out:
        for k in ("a", "b"):
            if d["e"][k] in jn_nodes or d["e"][k] in members:
                at.setdefault(d["e"][k], []).append((d, k))
    for n, arms in at.items():
        for i in range(len(arms)):
            for j in range(i + 1, len(arms)):
                (d1, k1), (d2, k2) = arms[i], arms[j]
                if d1["e"]["cls"] != d2["e"]["cls"] or d1["e"]["ow"] != d2["e"]["ow"]:
                    continue
                u1 = _out_dir(d1["ln"], k1 == "a")
                u2 = _out_dir(d2["ln"], k2 == "a")
                if u1[0] * u2[0] + u1[1] * u2[1] < -0.85:
                    per = max(d1["per"], d2["per"])
                    for d in (d1, d2):
                        d["per"] = per
                        d["hw"] = per * LW / 2 if d["e"]["ow"] else per * LW
    return out


def _arms_at(n, L, road):
    """Arms of junction n as the reference design sees them: outward unit u from the junction centre c, the lateral
    normal v (inbound side +v), and the inbound / outbound lane bands [(s0, s1, lanes)].  A one-way pair (one in, one
    out, leaving in nearly the same direction) is one boulevard arm with the gap between them as its median.  h is
    where the arm's kerbs are clear of the corner fillets (its cross-section is the arm's own width)."""
    c = L[0]["ln"].coords[0] if L[0]["e"]["a"] == n else L[0]["ln"].coords[-1]
    raw = []
    for d in L:
        e = d["e"]
        out_line = d["ln"] if e["a"] == n else LineString(list(d["ln"].coords)[::-1])
        if out_line.length < 8:
            continue
        q = out_line.interpolate(min(20.0, out_line.length * 0.6))
        u = (q.x - c[0], q.y - c[1])
        l = math.hypot(*u) or 1.0
        u = (u[0] / l, u[1] / l)
        v = (-u[1], u[0])
        hw = d["hw"]
        if e["ow"]:
            kind = "in" if e["b"] == n else "out"
            raw.append({"u": u, "v": v, "line": out_line, "d": d, "bands": [(-hw, hw, d["per"], kind)]})
        else:
            raw.append({"u": u, "v": v, "line": out_line, "d": d, "bands": [(0.0, hw, d["per"], "in"), (-hw, 0.0, d["per"], "out")]})
    # a merge or diverge of one-way roads (ramps joining, a carriageway splitting) is not a crossing: no zebra, no stop
    # line; it is drawn as a taper with a hatched gore (see _gore)
    if len(raw) == 3 and all(r["d"]["e"]["ow"] for r in raw):
        best = max(raw[i]["u"][0] * raw[j]["u"][0] + raw[i]["u"][1] * raw[j]["u"][1] for i in range(3) for j in range(i + 1, 3))
        kinds = [r["bands"][0][3] for r in raw]
        if best > 0.82 and (kinds.count("in") == 1 or kinds.count("out") == 1):
            return []
    # pair one-way carriageways: cost = angle between them + how far apart they run (soft, best pairs first)
    used, arms = set(), []
    cand = []
    for i, a in enumerate(raw):
        for j, b in enumerate(raw):
            if i >= j or len(a["bands"]) != 1 or len(b["bands"]) != 1 or a["bands"][0][3] == b["bands"][0][3]:
                continue
            cosang = a["u"][0] * b["u"][0] + a["u"][1] * b["u"][1]
            pa, pb = a["line"].interpolate(min(20.0, a["line"].length * 0.6)), b["line"].interpolate(min(20.0, b["line"].length * 0.6))
            gap = math.hypot(pa.x - pb.x, pa.y - pb.y)
            cost = (1 - cosang) * 20 + gap / 30.0
            if cost < 1.5:
                cand.append((cost, i, j, gap))
    for cost, i, j, gap in sorted(cand):
        if i in used or j in used:
            continue
        used |= {i, j}
        a, b = raw[i], raw[j]
        u = (a["u"][0] + b["u"][0], a["u"][1] + b["u"][1])
        l = math.hypot(*u) or 1.0
        u = (u[0] / l, u[1] / l)
        v = (-u[1], u[0])
        bands = []
        for r in (a, b):
            pt = r["line"].interpolate(min(20.0, r["line"].length * 0.6))
            off = (pt.x - c[0]) * v[0] + (pt.y - c[1]) * v[1]
            s0, s1, lanes, kind = r["bands"][0]
            bands.append((off + s0, off + s1, lanes, kind))
        arms.append({"u": u, "v": v, "bands": bands, "c": c, "n": n, "ds": [a["d"], b["d"]], "deg": len(L)})
    for i, a in enumerate(raw):
        if i not in used:
            arms.append({"u": a["u"], "v": a["v"], "bands": a["bands"], "c": c, "n": n, "ds": [a["d"]], "deg": len(L)})
    for a in arms:
        lo = min(b[0] for b in a["bands"])
        hi = max(b[1] for b in a["bands"])
        width = sum(b[1] - b[0] for b in a["bands"])
        a["lo"], a["hi"] = lo, hi
        # contiguous carriageways of the arm (one for a street, two for a boulevard)
        bs = sorted(a["bands"])
        groups = [[bs[0][0], bs[0][1]]]
        for b0, b1, _l, _k in bs[1:]:
            if b0 <= groups[-1][1] + 0.05:
                groups[-1][1] = max(groups[-1][1], b1)
            else:
                groups.append([b0, b1])
        h = 80.0
        for k in range(0, 160):
            dd = k * 0.5
            ok = True
            for g0, g1 in groups:
                cut = road.intersection(LineString([_arm_pt0(c, a, dd, g0 - 12), _arm_pt0(c, a, dd, g1 + 12)]))
                mid = Point(_arm_pt0(c, a, dd, (g0 + g1) / 2)).buffer(0.3)
                piece = [q for q in getattr(cut, "geoms", [cut]) if not q.is_empty and q.intersects(mid)]
                if not piece or piece[0].length > (g1 - g0) + 0.6:
                    ok = False
                    break
            if ok:
                h = dd
                break
        a["h"] = h
        a["Ln"] = h + 30.0
        a["zone"] = _arm_poly(a, 0.0, a["Ln"], lo - 0.2, hi + 0.2)
    return arms


def _arm_pt0(c, a, d, s):
    u, v = a["u"], a["v"]
    return (c[0] + u[0] * d + v[0] * s, c[1] + u[1] * d + v[1] * s)


def _arm_pt(a, d, s):
    c, u, v = a["c"], a["u"], a["v"]
    return (c[0] + u[0] * d + v[0] * s, c[1] + u[1] * d + v[1] * s)


def _arm_poly(a, d0, d1, s0, s1):
    return Polygon([_arm_pt(a, d0, s0), _arm_pt(a, d1, s0), _arm_pt(a, d1, s1), _arm_pt(a, d0, s1)])


def _arm_marks(m, a, road, zone_arm):
    """Markings of one arm, after the reference junction: continental zebra set back from the corner, stop line over
    the inbound lanes, solid lane lines and edge lines up to the arm's end, centre double line, two rows of arrows."""
    h, Ln = a["h"], a["Ln"]
    paint = []
    # zebra: bars 0.5 m wide, 1 m pitch, 3.2 m long, across all lanes
    s = a["lo"] + 0.6
    while s < a["hi"] - 0.4:
        paint.append(_arm_poly(a, h + 1.0, h + 4.2, s - 0.25, s + 0.25))
        s += 1.0
    sl = h + 6.0
    for s0, s1, lanes, kind in a["bands"]:
        if kind == "in":
            paint.append(_arm_poly(a, sl - 0.25, sl + 0.25, s0 + 0.15, s1 - 0.15))        # stop line
            w = (s1 - s0) / max(1, lanes)
            for k in range(1, lanes):
                paint.append(_arm_poly(a, sl + 0.6, Ln, s0 + w * k - 0.075, s0 + w * k + 0.075))
            for ds in (12.0, 28.0):
                if h + ds + 3 > Ln:
                    continue
                for k in range(lanes):
                    sc = s0 + w * (k + 0.5)
                    kind_ = "thru"
                    if lanes >= 2 and k == lanes - 1:
                        kind_ = "left"
                    elif lanes >= 3 and k == 0:
                        kind_ = "right"
                    paint += _arrow_polys(a, h + ds, sc, kind_)
        else:
            w = (s1 - s0) / max(1, lanes)
            for k in range(1, lanes):
                paint.append(_arm_poly(a, sl + 0.6, Ln, s0 + w * k - 0.075, s0 + w * k + 0.075))
        paint.append(_arm_poly(a, sl + 0.6, Ln, s0 + 0.28, s0 + 0.42))                   # edge lines
        paint.append(_arm_poly(a, sl + 0.6, Ln, s1 - 0.42, s1 - 0.28))
    kinds = {b[3] for b in a["bands"]}
    if len(a["bands"]) == 2 and abs(a["bands"][0][0] - a["bands"][1][1]) < 0.01 and kinds == {"in", "out"}:
        paint.append(_arm_poly(a, sl + 0.6, Ln, -0.20, -0.08))                           # double centre line
        paint.append(_arm_poly(a, sl + 0.6, Ln, 0.08, 0.20))
    g = unary_union(paint).intersection(road)
    stroke(m, g, 0.05, WHITE)


def _arrow_polys(a, d, s, kind):
    """Lane arrow for an inbound lane at (d, s); cars travel toward the junction (-u)."""
    def P(f, r):                                       # f: forward (toward the junction), r: to the driver's right (-v)
        return _arm_pt(a, d - f, s - r)
    out = [Polygon([P(-2.6, -0.14), P(0.2, -0.14), P(0.2, 0.14), P(-2.6, 0.14)])]
    if kind == "thru":
        out.append(Polygon([P(0.2, -0.5), P(1.4, 0.0), P(0.2, 0.5)]))
    else:
        sg = -1.0 if kind == "left" else 1.0
        out.append(Polygon([P(-0.1, -0.14 * sg), P(0.6, 0.6 * sg), P(0.8, 0.4 * sg), P(0.1, -0.14 * sg)]).convex_hull)
        out.append(Polygon([P(0.3, 0.3 * sg), P(1.1, 1.2 * sg), P(1.2, 0.2 * sg)]).convex_hull)
    return out


def build(edges, cx, cy, buildings=(), decks=None, T=None, port=False, ctx=None):
    """port=True: only what replaces the game's ground-road surfaces (asphalt, kerbs, pavements, islands, paint, zebras),
    heights relative to the terrain, no furniture / bridges / buildings; ctx = context(edges) when `edges` is a subset."""
    E, B, W = [], [], []
    pending_bars = []
    ctx = ctx or context(edges)
    BL, gn, gdeg = ctx["BL"], ctx["gn"], ctx["gdeg"]
    for e in edges:
        if not e["drive"] and not e["bridge"] and e["cls"] in WALK_W and len(e["pts"]) >= 2:
            P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
            if min(math.hypot(p[0], p[1]) for p in P) < RANGE:
                W.append({"e": e, "ln": LineString(P), "hw": WALK_W[e["cls"]]})
            continue
        if e["drive"] and e["bridge"]:
            P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
            if len(P) >= 2 and min(math.hypot(p[0], p[1]) for p in P) < RANGE + MARGIN:
                nb = BL.get(e["road"], per_dir(e))
                B.append({"e": e, "ln": LineString(P), "hw": nb * LW / 2 if e["ow"] else nb * LW, "per": nb, "gnodes": gn})
            continue
        if not e["drive"]:
            continue
        P = [(p[0] - cx, p[1] - cy) for p in e["pts"]]
        if min(math.hypot(p[0], p[1]) for p in P) > RANGE + MARGIN or len(P) < 2:
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
    bulbs = []
    # dead ends get a turning bulb (cul-de-sac) instead of a bare round cap
    for n, L in inc.items():
        if gdeg.get(n, 0) == 1 and L[0]["ln"].length > 20:
            d = L[0]
            start = d["e"]["a"] == n
            ux, uy = _out_dir(d["ln"], start)
            end = d["ln"].coords[0] if start else d["ln"].coords[-1]
            rb = max(d["hw"] + 4.5, 10.0)
            bx, by = end[0] + ux * rb * 0.6, end[1] + uy * rb * 0.6   # centre sits inside the road so the bulb stands 0.4 r proud
            ribs.append(Point(bx, by).buffer(rb, resolution=24))
            bulbs.append(Point(bx, by).buffer(rb + 4.0, resolution=12))
    U = unary_union(ribs)
    C = U.buffer(R_KERB, resolution=16).buffer(-R_KERB, resolution=16).simplify(0.04)
    gap = C.difference(U)
    isl = gap.buffer(-1.3, resolution=6).buffer(1.3, resolution=6).intersection(gap)
    keep_isl = [p for p in polys_of(isl) if p.area > 6.0]
    if B:                                              # leftovers between a deck foot and the ground road are paved, not grass
        ends = [Point(d["ln"].coords[k]).buffer(d["hw"] + 8.0) for d in B for k, nd in ((0, d["e"]["a"]), (-1, d["e"]["b"])) if nd in gn]
        foot = unary_union(ends) if ends else Polygon()
        keep_isl = [p for p in keep_isl if not (p.area < 250.0 and p.intersects(foot))]
    isl = unary_union(keep_isl)
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
    hf = RANGE if port else None
    for p in polys_of(asph):
        for ring in [p.exterior] + list(p.interiors):
            _wall_ring(m, ring, 0.0, KERB, KFACE, hf)
    for p in polys_of(isl):
        tri_poly(m, p, KERB, KTOP)
        ins = p.buffer(-0.35)
        for q in polys_of(ins):
            tri_poly(m, q, KERB + 0.10, GRASS)
        for ring in [p.exterior] + list(p.interiors):
            _wall_ring(m, ring, 0.0, KERB, KFACE, hf)
    if W and B and not port:
        corr = unary_union([d["ln"].buffer(d["hw"] + 2.6) for d in B])
        W = [w for w in W if w["ln"].intersection(corr).length < 0.5 * w["ln"].length]
    if W:
        foot = unary_union([w["ln"].buffer(w["hw"], cap_style=1, resolution=6) for w in W if w["e"]["cls"] != "cycleway"])
        cyc = unary_union([w["ln"].buffer(w["hw"], cap_style=1, resolution=6) for w in W if w["e"]["cls"] == "cycleway"])
        cut = asph.union(isl)
        if not port:
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
        pending_bars = bars
        for w in ([] if port else W):
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
    if B and decks and not port:
        base = min(float(decks[d["e"]["road"]].at(*d["ln"].coords[0][:2] if False else (d["ln"].coords[0][0] + cx, d["ln"].coords[0][1] + cy))[0]) for d in B if d["e"]["road"] in decks) if any(d["e"]["road"] in decks for d in B) else 0.0
        if T is not None:
            base = tbase
        m.gfn = None
        bridge_mesh(m, B, decks, cx, cy, base, gfn)
        m.gfn = gfn
    # junction arms (one-way pairs read as one boulevard arm) and where each arm's own markings take over
    road_only = asph.difference(isl)
    arms_all = []
    for n, L in nodes.items():
        if n in ctx.get("bn", ()):                     # ramps meeting at a deck end: a merge, never a crossing
            continue
        arms_all += _arms_at(n, L, road_only)
    # two junctions close together share the road between them: the bigger junction keeps its arm markings there,
    # the smaller one's arm is left plain (no doubled zebras / stop lines on one short link)
    by_edge = {}
    for a_ in arms_all:
        for d_ in a_["ds"]:
            by_edge.setdefault(id(d_), []).append(a_)
    drop = set()
    for L_ in by_edge.values():
        if len(L_) == 2:
            a1, a2 = L_
            length = max(d_["ln"].length for d_ in a1["ds"] if any(d_ is q for q in a2["ds"]))
            if a1["Ln"] + a2["Ln"] > length:
                lesser, bigger = sorted((a1, a2), key=lambda q: (q["deg"], q["hi"] - q["lo"]))
                drop.add(id(lesser))
                bigger["Ln"] = max(bigger["h"] + 7.0, min(bigger["Ln"], length - lesser["h"] - 2.0))
                bigger["zone"] = _arm_poly(bigger, 0.0, bigger["Ln"], bigger["lo"] - 0.2, bigger["hi"] + 0.2)
    arms_all = [a_ for a_ in arms_all if id(a_) not in drop]
    zone_arm = unary_union([a_["zone"] for a_ in arms_all]) if arms_all else Polygon()
    if pending_bars:                                   # path crossings away from the junction mouths (those have their own zebras)
        stroke(m, unary_union(pending_bars).intersection(road_only).difference(zone_arm.buffer(4.0)).intersection(clip), 0.06, WHITE)
    # paint zone: asphalt without junction cores, arm mouths and islands
    core = unary_union([Point(0, 0).buffer(0), zone_arm] + [Point(L[0]["ln"].coords[0] if L[0]["e"]["a"] == n else L[0]["ln"].coords[-1]).buffer(6.0 + max(d["hw"] for d in L)) for n, L in nodes.items()])
    zone = asph.difference(core).difference(isl.buffer(0.3))
    if bulbs:
        zone = zone.difference(unary_union(bulbs))              # no lane paint inside a turning bulb
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
                if s_.is_empty or s_.length < (0.3 if dash else 6.0):
                    continue
                for g in (s_.buffer(w / 2, cap_style=2).intersection(zone),):
                    for q in polys_of(g):
                        if q.area > 0.12 * w * 2.0:                        # drop the slivers left where the zone clips a line
                            stroke(m, q, 0.05, WHITE)
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
    # junction mouths: crossings, stop lines, lane lines and arrows laid out per arm, like the reference junction
    for arm in arms_all:
        _arm_marks(m, arm, asph.difference(isl), zone_arm)
    # street furniture on the pavements
    if port:
        return m
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
