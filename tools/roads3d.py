"""3D road network built from the routing graph: smoothed centrelines, mitred asphalt ribbons with gutters,
junction fills, raised pavements with curb faces, lane markings and zebra crossings.

The OSM polylines are only used as guidance: corners are rounded, higher-class roads sit on top of lower ones, and
pavements / markings are cut away where another road's asphalt crosses them.  Everything is plain numpy triangles
(material 'solid': vertex colours on a white pixel), streamed per chunk like the buildings.
"""
import math
import os

import numpy as np

SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)
TOP = 0.52 + 0.55 * float(SUN[1])                       # flat surfaces facing up
RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1,
        "living_street": 0, "service": 0}
FILL = {
    "motorway": (92, 94, 102), "trunk": (88, 90, 98), "primary": (88, 90, 98), "secondary": (92, 94, 101),
    "tertiary": (97, 99, 106), "unclassified": (100, 102, 108), "residential": (102, 104, 110),
    "living_street": (126, 124, 124), "service": (118, 118, 122), "pedestrian": (206, 198, 184),
    "footway": (194, 188, 176), "path": (182, 168, 138), "steps": (168, 164, 160), "cycleway": (186, 150, 140),
    "track": (160, 140, 110),
}
SIDEWALK = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "primary_link", "secondary_link", "tertiary_link", "trunk_link", "living_street"}
MARK = {"primary", "secondary", "tertiary", "trunk", "motorway", "unclassified", "residential"}
FOOT = {"pedestrian", "footway", "path", "steps", "cycleway", "track"}
SW_W, SW_H = 2.0, 0.16
Y_BASE, Y_STEP = 0.05, 0.016
PIECE = 24.0                                             # longest ribbon piece (also keeps pieces inside their chunk)
SAG = 0.012                                              # allowed gap between a flat piece and the curved terrain (m)
_T = None                                                # terrain used by the piece splitter (set by build)


def _pieces(ln, ax, ay, bx, by, base=PIECE):
    """Number of pieces for a segment: short enough to hug the terrain within SAG, long enough to stay cheap."""
    n = max(1, int(math.ceil(ln / base)))
    if _T is not None and ln > 3.0:
        h0, h1 = _T.hs(ax, ay), _T.hs(bx, by)
        sag = 0.0
        for t in (0.25, 0.5, 0.75):
            sag = max(sag, abs(_T.hs(ax + (bx - ax) * t, ay + (by - ay) * t) - (h0 + (h1 - h0) * t)))
        n = max(n, int(math.ceil(math.sqrt(sag / SAG))))
    return min(n, max(1, int(math.ceil(ln / 3.0))))
SLAB = 0.9                                               # bridge deck thickness


def _base(cls):
    return cls.replace("_link", "")


def rank_of(cls):
    return RANK.get(_base(cls), 0)


_MICRO = {}                                              # id(edge) -> tiny height offset: coplanar ribbons of one rank never z-fight


def y_of(e):
    mc = _MICRO.get(id(e), 0.0)
    if _base(e["cls"]) in FOOT:
        return 0.04 + mc
    return Y_BASE + Y_STEP * rank_of(e["cls"]) + (0.01 if e["bridge"] else 0.0) + mc


# ----------------------------------------------------------------------------------------- smoothing
def smooth(pts, cut=6.0):
    """Round the corners of a polyline with quadratic Béziers. End points never move, so junctions stay connected."""
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, p, b = pts[i - 1], pts[i], pts[i + 1]
        v1 = (a[0] - p[0], a[1] - p[1])
        v2 = (b[0] - p[0], b[1] - p[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 0.6 or l2 < 0.6 or (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < -0.995:
            out.append(p)
            continue
        c1, c2 = min(cut, l1 * 0.45), min(cut, l2 * 0.45)
        p1 = (p[0] + v1[0] / l1 * c1, p[1] + v1[1] / l1 * c1)
        p2 = (p[0] + v2[0] / l2 * c2, p[1] + v2[1] / l2 * c2)
        for k in range(5):
            t = k / 4.0
            out.append(((1 - t) ** 2 * p1[0] + 2 * (1 - t) * t * p[0] + t * t * p2[0],
                        (1 - t) ** 2 * p1[1] + 2 * (1 - t) * t * p[1] + t * t * p2[1]))
    out.append(pts[-1])
    res = [out[0]]
    for q in out[1:]:
        if math.hypot(q[0] - res[-1][0], q[1] - res[-1][1]) > 0.08:
            res.append(q)
    if len(res) < 2:
        return list(pts)
    res[-1] = pts[-1]
    return res


def smooth_edges(edges):
    for e in edges:
        pts = smooth(e["pts"])
        cum = [0.0]
        for k in range(1, len(pts)):
            cum.append(cum[-1] + math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]))
        if cum[-1] > 0.5:
            e["pts"], e["cum"], e["len"] = pts, cum, cum[-1]


# ----------------------------------------------------------------------------------------- geometry helpers
def _frames(pts):
    """Per vertex: unit normal (left of travel) and miter scale."""
    n = len(pts)
    segs = []
    for i in range(n - 1):
        dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        l = math.hypot(dx, dy) or 1.0
        segs.append((dx / l, dy / l))
    out = []
    for i in range(n):
        if i == 0:
            t = segs[0]
        elif i == n - 1:
            t = segs[-1]
        else:
            tx, ty = segs[i - 1][0] + segs[i][0], segs[i - 1][1] + segs[i][1]
            l = math.hypot(tx, ty)
            t = (tx / l, ty / l) if l > 1e-6 else segs[i]
        nrm = (-t[1], t[0])
        s = 1.0
        if 0 < i < n - 1:
            ns = (-segs[i - 1][1], segs[i - 1][0])
            s = 1.0 / max(0.6, nrm[0] * ns[0] + nrm[1] * ns[1])
        out.append((nrm, s))
    return out


def offset(pts, fr, off):
    return [(p[0] + f[0][0] * off * f[1], p[1] + f[0][1] * off * f[1]) for p, f in zip(pts, fr)]


def _cum(pts):
    c = [0.0]
    for i in range(1, len(pts)):
        c.append(c[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    return c


def _at(pts, cum, s):
    lo, hi = 0, len(cum) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if cum[m] <= s:
            lo = m
        else:
            hi = m
    d = (cum[hi] - cum[lo]) or 1.0
    t = (s - cum[lo]) / d
    return (pts[lo][0] + (pts[hi][0] - pts[lo][0]) * t, pts[lo][1] + (pts[hi][1] - pts[lo][1]) * t)


class Out:
    """Collects triangles per chunk and hands them to the mesh accumulator.

    Heights are relative: flush() adds the terrain height under every vertex (or, for a bridge, the deck height)."""

    def __init__(self, chunk_of, T=None):
        self.chunk_of = chunk_of
        self.T = T
        self.deck = None                      # Deck of the bridge being built, else None (= lie on the terrain)
        self.d = {}
        self.n = 0

    def quad(self, a, b, c, d, col, shade=TOP):
        """a..d: (x, y_up, z) corners in order."""
        key = self.chunk_of((a[0] + c[0]) * 0.5, (a[2] + c[2]) * 0.5)
        e = self.d.setdefault((key, id(self.deck)), ([], [], self.deck))
        rgba = (min(255, col[0] * shade), min(255, col[1] * shade), min(255, col[2] * shade), 255)
        e[0].extend((a, b, c, a, c, d))
        e[1].extend((rgba,) * 6)
        self.n += 6

    def flush(self, add, mat):
        for (key, _did), (p, c, deck) in self.d.items():
            pos = np.array(p, np.float32)
            if deck is not None:
                pos[:, 1] += np.array([deck.at(x, z)[0] for x, z in zip(pos[:, 0], pos[:, 2])], np.float32)
            elif self.T is not None:
                pos[:, 1] += self.T.h(pos[:, 0], pos[:, 2])
            add(key, mat, pos, np.zeros((len(pos), 2), np.float32), np.array(c, np.uint8))


def _strip(out, L, R, y, col, shade=TOP):
    """Quad strip between two offset polylines, cut into pieces: every piece lands in the right chunk and follows the terrain."""
    for i in range(len(L) - 1):
        ln = math.hypot(L[i + 1][0] - L[i][0], L[i + 1][1] - L[i][1])
        n = _pieces(ln, L[i][0], L[i][1], L[i + 1][0], L[i + 1][1])
        for s in range(n):
            t0, t1 = s / n, (s + 1) / n
            l0 = (L[i][0] + (L[i + 1][0] - L[i][0]) * t0, L[i][1] + (L[i + 1][1] - L[i][1]) * t0)
            l1 = (L[i][0] + (L[i + 1][0] - L[i][0]) * t1, L[i][1] + (L[i + 1][1] - L[i][1]) * t1)
            r0 = (R[i][0] + (R[i + 1][0] - R[i][0]) * t0, R[i][1] + (R[i + 1][1] - R[i][1]) * t0)
            r1 = (R[i][0] + (R[i + 1][0] - R[i][0]) * t1, R[i][1] + (R[i + 1][1] - R[i][1]) * t1)
            out.quad((l0[0], y, l0[1]), (l1[0], y, l1[1]), (r1[0], y, r1[1]), (r0[0], y, r0[1]), col, shade)


def _pdist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - dx * t, py - ay - dy * t)


class Cover:
    """Which asphalt covers a point?  Only built around junctions, where roads actually overlap."""

    CELL = 24.0

    def __init__(self, edges):
        deg = {}
        for e in edges:
            if e["drive"] or e["walk"]:
                deg[e["a"]] = deg.get(e["a"], 0) + 1
                deg[e["b"]] = deg.get(e["b"], 0) + 1
        self.zone = set()
        self.segs = {}
        c = self.CELL
        for i, e in enumerate(edges):
            if not e["drive"] or _base(e["cls"]) not in RANK:
                continue
            hw = e["w"] / 2
            pts = e["pts"]
            for k in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[k], pts[k + 1]
                for cx in range(int((min(ax, bx) - hw) // c), int((max(ax, bx) + hw) // c) + 1):
                    for cy in range(int((min(ay, by) - hw) // c), int((max(ay, by) + hw) // c) + 1):
                        self.segs.setdefault((cx, cy), []).append((i, ax, ay, bx, by, hw, rank_of(e["cls"]), e["bridge"]))
            for nid, p in ((e["a"], pts[0]), (e["b"], pts[-1])):
                if deg.get(nid, 0) >= 3:
                    cx, cy = int(p[0] // c), int(p[1] // c)
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            self.zone.add((cx + dx, cy + dy))

    def near_junction(self, x, y):
        c = self.CELL
        return (int(x // c), int(y // c)) in self.zone

    def others(self, x, y, me, skip=()):
        """Is any other road's centreline indexed in this cell (cheap pre-check before sampling covered())?"""
        c = self.CELL
        return any(sg[0] != me and sg[0] not in skip for sg in self.segs.get((int(x // c), int(y // c)), ()))

    def covered(self, x, y, me, bridge, my_rank=None, skip=()):
        """True when another road's asphalt (for markings: of higher precedence) lies over (x, y)."""
        c = self.CELL
        for s in self.segs.get((int(x // c), int(y // c)), ()):
            i, ax, ay, bx, by, hw, rk, br = s
            if i == me or br != bridge or i in skip:
                continue
            if my_rank is not None and not (rk > my_rank or (rk == my_rank and i < me)):
                continue
            if _pdist(x, y, ax, ay, bx, by) < hw - 0.05:
                return True
        return False


# ----------------------------------------------------------------------------------------- the build
def _wall(out, P, y_top, y_bot, col, shade):
    """Vertical face under the polyline P (cut into pieces <= PIECE)."""
    for i in range(len(P) - 1):
        ln = math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1])
        n = _pieces(ln, P[i][0], P[i][1], P[i + 1][0], P[i + 1][1])
        for s in range(n):
            t0, t1 = s / n, (s + 1) / n
            a = (P[i][0] + (P[i + 1][0] - P[i][0]) * t0, P[i][1] + (P[i + 1][1] - P[i][1]) * t0)
            b = (P[i][0] + (P[i + 1][0] - P[i][0]) * t1, P[i][1] + (P[i + 1][1] - P[i][1]) * t1)
            out.quad((a[0], y_top, a[1]), (b[0], y_top, b[1]), (b[0], y_bot, b[1]), (a[0], y_bot, a[1]), col, shade)


def _slab(out, pts, fr, hw, y):
    """Concrete deck body: kerb ledges, both girder faces and the underside of a bridge."""
    ext = hw + 0.6
    Lo, Ro = offset(pts, fr, ext), offset(pts, fr, -ext)
    Li, Ri = offset(pts, fr, hw), offset(pts, fr, -hw)
    conc = (176, 172, 164)
    _strip(out, Li, Lo, y - 0.01, conc, 0.95)
    _strip(out, Ro, Ri, y - 0.01, conc, 0.95)
    _wall(out, Lo, y - 0.01, y - SLAB, conc, 0.78)
    _wall(out, Ro, y - 0.01, y - SLAB, conc, 0.78)
    _strip(out, Lo, Ro, y - SLAB, (120, 118, 114), 0.62)


def _hull(P):
    P = sorted(set(P))
    if len(P) < 3:
        return P
    cr = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in P:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(hi) >= 2 and cr(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def _cut_d(L, maxhw):
    """How far from a junction node the roads' own ribbons / pavements stop and the junction plate takes over."""
    return min(L * 0.45, maxhw * 1.15 + 1.0, 9.0)


def _away(e, end):
    """Unit direction leaving the node along edge e (end 0 = starts there, 1 = ends there)."""
    pts = e["pts"]
    cum = _cum(pts)
    L = cum[-1]
    s = min(2.5, L * 0.5)
    p = pts[0] if end == 0 else pts[-1]
    q = _at(pts, cum, s if end == 0 else L - s)
    d = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
    return ((q[0] - p[0]) / d, (q[1] - p[1]) / d)


def _plate_nodes(edges, joints):
    """node -> ([(edge, end)], widest half width) for every junction that gets an asphalt plate."""
    inc = {}
    for i, e in enumerate(edges):
        if e["drive"] and not e["bridge"] and len(e["pts"]) >= 2 and _base(e["cls"]) not in FOOT:
            inc.setdefault(e["a"], []).append((i, 0))
            inc.setdefault(e["b"], []).append((i, 1))
    res = {}
    for node, lst in inc.items():
        if len(lst) < 2 or (len(lst) == 2 and all(q in joints for q in lst)):
            continue
        res[node] = (lst, max(edges[i]["w"] / 2 for i, _ in lst))
    return res


def _joints(edges):
    """Nodes where exactly two ribbons of the same rank meet end to end (road continues, bends, widens or narrows).
    Both get the SAME cross-section there (bisector normal, mean half width), so asphalt and pavements share vertices."""
    inc = {}
    for i, e in enumerate(edges):
        if (e["drive"] or e["walk"]) and not e["bridge"] and len(e["pts"]) >= 2:
            inc.setdefault(e["a"], []).append((i, 0))
            inc.setdefault(e["b"], []).append((i, 1))
    J = {}
    for node, lst in inc.items():
        if len(lst) != 2 or lst[0][0] == lst[1][0]:
            continue
        (i, ei), (j, ej) = lst
        A, B = edges[i], edges[j]
        if (_base(A["cls"]) in FOOT) != (_base(B["cls"]) in FOOT) or rank_of(A["cls"]) != rank_of(B["cls"]):
            continue
        dA, dB = _away(A, ei), _away(B, ej)
        tx, ty = dB[0] - dA[0], dB[1] - dA[1]
        tl = math.hypot(tx, ty)
        if tl < 0.6:                                      # a hairpin: leave it to the plate
            continue
        T = (tx / tl, ty / tl)
        hwn = (A["w"] + B["w"]) / 4.0
        out = {}
        for (k, ek, d) in ((i, ei, dA), (j, ej, dB)):
            t = T if ((ek == 1) if k == i else (ek == 0)) else (-T[0], -T[1])     # travel direction of that edge at the node
            n = (-t[1], t[0])
            seg = d if ek == 0 else (-d[0], -d[1])                              # direction of its own end segment
            c = n[0] * -seg[1] + n[1] * seg[0]
            if c < 0.6:
                out = None
                break
            out[(k, ek)] = (n, 1.0 / c, hwn)
        if out:
            J.update(out)
    return J


def _ribbon(e, i, J, plates):
    """The edge's centreline with extra vertices where its width tapers to a shared joint and where it stops at a
    junction plate.  -> (pts, per-vertex half widths, frames, first vertex of the pavement run, last vertex)."""
    pts = e["pts"]
    cum = _cum(pts)
    L = cum[-1]
    hw = e["w"] / 2
    marks = []
    taper = {}
    for end in (0, 1):
        j = J.get((i, end))
        if j and abs(j[2] - hw) > 0.05:
            T = min(14.0, L * 0.4)
            taper[end] = (T, j[2])
            marks.append(T if end == 0 else L - T)
    cut = {}
    for end in (0, 1):
        node = e["a"] if end == 0 else e["b"]
        pl = plates.get(node)
        if pl and (i, end) in pl[0]:                     # asphalt and pavement both stop where the junction plate takes over
            d = _cut_d(L, pl[1])
            cut[end] = d
            marks.append(d if end == 0 else L - d)
    ss = list(cum)
    for m in sorted(marks):
        if 0.1 < m < L - 0.1:
            k = min(range(len(ss)), key=lambda q: abs(ss[q] - m))
            if abs(ss[k] - m) > 0.15:
                ss.append(m)
    ss = sorted(set(ss))
    P = [pts[0] if abs(s_) < 1e-9 else (pts[-1] if abs(s_ - L) < 1e-9 else _at(pts, cum, s_)) for s_ in ss]
    hwv = []
    for s_ in ss:
        h = hw
        if 0 in taper:
            T, hn = taper[0]
            h = hn + (hw - hn) * min(1.0, s_ / T)
        if 1 in taper:
            T, hn = taper[1]
            h = min(h, hn + (hw - hn) * min(1.0, (L - s_) / T)) if 0 in taper else hn + (hw - hn) * min(1.0, (L - s_) / T)
        hwv.append(h)
    fr = _frames(P)
    for end, k in ((0, 0), (1, len(P) - 1)):
        j = J.get((i, end))
        if j:
            fr[k] = (j[0], j[1])
    k0 = min(range(len(ss)), key=lambda q: abs(ss[q] - cut[0])) if 0 in cut else 0
    k1 = min(range(len(ss)), key=lambda q: abs(ss[q] - (L - cut[1]))) if 1 in cut else len(P) - 1
    return P, hwv, fr, k0, k1


def _spath(P, k0, k1, frac):
    """Path length along P from vertex k0 to vertex k1, plus frac of the segment k1 (k0 <= k1; frac in 0..1)."""
    s = 0.0
    for q in range(k0, k1):
        s += math.hypot(P[q + 1][0] - P[q][0], P[q + 1][1] - P[q][1])
    if k1 + 1 < len(P):
        s += frac * math.hypot(P[k1 + 1][0] - P[k1][0], P[k1 + 1][1] - P[k1][1])
    return s


def _free_runs(bad, ta, tb, length):
    """Sub-intervals of [ta, tb] where bad(t) is False, sampled every ~0.5 m and refined to ~3 cm at each edge."""
    n = max(1, int(math.ceil(length / 0.5)))
    ts = [ta + (tb - ta) * q / n for q in range(n + 1)]
    flags = [bad(t) for t in ts]
    if not any(flags):
        return [(ta, tb)]

    def edge(lo, hi, lo_bad):                                    # bisect the switch between lo and hi
        for _ in range(5):
            mid = (lo + hi) * 0.5
            if bad(mid) == lo_bad:
                lo = mid
            else:
                hi = mid
        return hi if lo_bad else lo
    runs, start = [], (ta if not flags[0] else None)
    for q in range(1, n + 1):
        if flags[q - 1] and not flags[q]:
            start = edge(ts[q - 1], ts[q], True)
        elif not flags[q - 1] and flags[q]:
            runs.append((start, edge(ts[q - 1], ts[q], False)))
            start = None
    if start is not None:
        runs.append((start, tb))
    return [r for r in runs if r[1] - r[0] > 1e-4]


def _offset_v(P, fr, hwv, side, extra=0.0):
    return [(p[0] + f[0][0] * (h + extra) * side * f[1], p[1] + f[0][1] * (h + extra) * side * f[1]) for p, f, h in zip(P, fr, hwv)]


def _bez(a, c, b, n=6):
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0], (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1])
            for t in (k / n for k in range(n + 1))]


def _isect(p, d, q, e):
    """Intersection of the lines p + d*t and q + e*u, or None when (nearly) parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 0.12:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)


def _corners(out, edges, plates, ribs, trims):
    """Curb corners at every junction: the pavements of neighbouring roads join in a smooth arc (shared vertices at both
    ends), with asphalt filling the space between the arc and the junction plate."""
    for node, (lst, maxhw) in plates.items():
        ent = []
        for i, end in lst:
            e = edges[i]
            da = _away(e, end)
            ang0 = math.atan2(da[1], da[0])
            P, hwv, fr, k0, k1 = ribs[i]
            kk = k0 if end == 0 else k1
            if _base(e["cls"]) not in SIDEWALK or not ((end == 0 and k0 > 0) or (end == 1 and k1 < len(P) - 1)):
                ent.append(dict(a=ang0, ok=False))             # no pavement on this road: the corner next to it stays open
                continue
            (nx, ny), sc = fr[kk]
            if end == 1:
                nx, ny = -nx, -ny                                   # "left" of the direction leaving the node
            h = hwv[kk]
            p = P[kk]
            sl = 1 if end == 0 else -1                             # pavement side on the left of the leaving direction
            ent.append(dict(i=i, a=ang0, d=da, p=p, l=(nx, ny), sc=sc, h=h, ok=True, tl=trims.get((i, end, sl)), tr=trims.get((i, end, -sl))))
        order = sorted(ent, key=lambda q: q["a"])
        if len(order) < 2:
            continue
        cx = cz = None
        for i, end in lst:
            pe = edges[i]["pts"]
            cx, cz = pe[0] if end == 0 else pe[-1]
            break
        yv = max(y_of(edges[i]) for i, _ in lst) + 0.012
        top = max(lst, key=lambda q: (rank_of(edges[q[0]]["cls"]), edges[q[0]]["w"]))
        col = FILL.get(_base(edges[top[0]]["cls"]), (100, 102, 108))
        n = len(order)
        for k in range(n):
            X, Y = order[k], order[(k + 1) % n]
            if not (X["ok"] and Y["ok"]):
                continue
            ang = (Y["a"] - X["a"]) % (2 * math.pi)
            sx, sy = X["sc"], Y["sc"]
            A = (X["p"][0] + X["l"][0] * X["h"] * sx, X["p"][1] + X["l"][1] * X["h"] * sx)
            B = (Y["p"][0] - Y["l"][0] * Y["h"] * sy, Y["p"][1] - Y["l"][1] * Y["h"] * sy)
            A2 = (X["p"][0] + X["l"][0] * (X["h"] + SW_W) * sx, X["p"][1] + X["l"][1] * (X["h"] + SW_W) * sx)
            B2 = (Y["p"][0] - Y["l"][0] * (Y["h"] + SW_W) * sy, Y["p"][1] - Y["l"][1] * (Y["h"] + SW_W) * sy)
            if X["tl"]:                                            # the pavement was trimmed back from the cut: start the corner there
                A, A2 = X["tl"]
            if Y["tr"]:
                B, B2 = Y["tr"]
            Q = Q2 = None
            if ang < math.radians(172):
                Q = _isect(A, X["d"], B, Y["d"])
                Q2 = _isect(A2, X["d"], B2, Y["d"])
                lim = 3.0 * (math.hypot(A[0] - B[0], A[1] - B[1]) + 1.0)
                if Q and math.hypot(Q[0] - A[0], Q[1] - A[1]) > lim:
                    Q = None
                if Q2 and math.hypot(Q2[0] - A2[0], Q2[1] - A2[1]) > lim:
                    Q2 = None
            if Q and Q2:
                I, O = _bez(A, Q, B), _bez(A2, Q2, B2)
                for j in range(len(I) - 1):                        # asphalt between the plate's straight edge and the arc
                    out.quad((A[0], yv, A[1]), (I[j][0], yv, I[j][1]), (I[j + 1][0], yv, I[j + 1][1]), (I[j + 1][0], yv, I[j + 1][1]), col)
                    out.quad((A[0], yv, A[1]), (I[j + 1][0], yv, I[j + 1][1]), (I[j][0], yv, I[j][1]), (I[j][0], yv, I[j][1]), col)
            else:
                I, O = [A, B], [A2, B2]
            pc = (178, 174, 166)
            for j in range(len(I) - 1):
                out.quad((I[j][0], SW_H, I[j][1]), (I[j + 1][0], SW_H, I[j + 1][1]), (O[j + 1][0], SW_H, O[j + 1][1]), (O[j][0], SW_H, O[j][1]), pc)
                out.quad((I[j][0], yv - 0.012, I[j][1]), (I[j + 1][0], yv - 0.012, I[j + 1][1]), (I[j + 1][0], SW_H, I[j + 1][1]),
                         (I[j][0], SW_H, I[j][1]), (150, 148, 142), 0.78)


def _junctions(out, edges, plates):
    """One seamless asphalt plate over every junction where roads of different classes (or 3+ roads) meet: no steps
    between their heights, no gutter lines or end caps showing, one colour (that of the most important road)."""
    n = 0
    for node, (lst, maxhw) in plates.items():
        top = max(lst, key=lambda q: (rank_of(edges[q[0]]["cls"]), edges[q[0]]["w"]))
        y = max(y_of(edges[i]) for i, _ in lst) + 0.012
        col = FILL.get(_base(edges[top[0]]["cls"]), (100, 102, 108))
        P = []
        hwm = min(edges[i]["w"] / 2 for i, _ in lst)
        for i, end in lst:
            e = edges[i]
            pts = e["pts"]
            cum = _cum(pts)
            L = cum[-1]
            hw = e["w"] / 2
            d = _cut_d(L, maxhw)
            s0 = d if end == 0 else L - d
            q = _at(pts, cum, s0)
            q2 = _at(pts, cum, min(L, s0 + 0.5) if end == 0 else max(0.0, s0 - 0.5))
            tx, tz = q2[0] - q[0], q2[1] - q[1]
            tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl, tx / tl
            P += [(q[0] + nx * hw, q[1] + nz * hw), (q[0] - nx * hw, q[1] - nz * hw)]
            c0 = pts[0] if end == 0 else pts[-1]
            P += [(c0[0] + nx * hwm, c0[1] + nz * hwm), (c0[0] - nx * hwm, c0[1] - nz * hwm)]   # (narrowest: a wide side road never pokes out behind)
        H = _hull(P)
        if len(H) < 3:
            continue
        cx = sum(p[0] for p in H) / len(H)
        cz = sum(p[1] for p in H) / len(H)
        for k in range(len(H)):                         # fan, both windings (cheap; no culling surprises)
            a, b = H[k], H[(k + 1) % len(H)]
            out.quad((cx, y, cz), (a[0], y, a[1]), (b[0], y, b[1]), (b[0], y, b[1]), col)
            out.quad((cx, y, cz), (b[0], y, b[1]), (a[0], y, a[1]), (a[0], y, a[1]), col)
        n += 1
    print(f"[roads3d] {n} junction plates")


def _pier(out, x, z, yaw, sx, sz, y0, y1, col=(168, 164, 156)):
    ca, sa = math.cos(yaw), math.sin(yaw)
    c = [(-sx / 2, -sz / 2), (sx / 2, -sz / 2), (sx / 2, sz / 2), (-sx / 2, sz / 2)]
    w = [(x + ca * u - sa * v, z + sa * u + ca * v) for u, v in c]
    for i in range(4):
        a, b = w[i], w[(i + 1) % 4]
        nx, nz = b[1] - a[1], -(b[0] - a[0])
        ln = math.hypot(nx, nz) or 1.0
        sh = 0.52 + 0.55 * max(0.0, (nx * SUN[0] + nz * SUN[2]) / ln)
        out.quad((a[0], y1, a[1]), (b[0], y1, b[1]), (b[0], y0, b[1]), (a[0], y0, a[1]), col, sh)


def build(edges, xwalks, add, chunk_of, mat, T=None, decks=None):
    """Adds all road geometry to the mesh accumulator.  -> (number of vertices, pier collision posts)."""
    global _T
    _T = T
    cov = Cover(edges)
    _MICRO.clear()
    for i_, e_ in enumerate(edges):
        _MICRO[id(e_)] = (i_ * 5 % 8) * 0.0011
    joints = _joints(edges)
    partners = {}                                          # edge -> the edges it continues into at a shared joint (they never cut its pavement)
    jn = {}
    for (k_, end_) in joints:
        jn.setdefault(edges[k_]["a"] if end_ == 0 else edges[k_]["b"], []).append(k_)
    for ks in jn.values():
        for k_ in ks:
            partners.setdefault(k_, set()).update(q for q in ks if q != k_)
    trims = {}
    deg = {}
    for e_ in edges:
        if e_["drive"] or e_["walk"]:
            deg[e_["a"]] = deg.get(e_["a"], 0) + 1
            deg[e_["b"]] = deg.get(e_["b"], 0) + 1
    plates = _plate_nodes(edges, joints)
    ribs = {}
    out = Out(chunk_of, T)
    pout = Out(chunk_of)                                   # piers: absolute heights
    piers = []
    pier_done = set()
    order = sorted(range(len(edges)), key=lambda i: (edges[i]["bridge"], rank_of(edges[i]["cls"])))
    for i in order:
        e = edges[i]
        if not (e["drive"] or e["walk"]):
            continue
        cls, pts, w = _base(e["cls"]), e["pts"], e["w"]
        if len(pts) < 2:
            continue
        fr = _frames(pts)
        y = y_of(e)
        hw = w / 2
        if e["bridge"]:
            ribs[i] = (pts, [hw] * len(pts), fr, 0, len(pts) - 1)
        else:
            ribs[i] = _ribbon(e, i, joints, plates)
        RP, RH, RF, RK0, RK1 = ribs[i]
        deck = decks.get(e["road"]) if (decks and e["bridge"]) else None
        out.deck = deck
        foot = cls in FOOT
        jit = 0 if foot else (i * 7 % 9) - 4
        base = FILL.get(cls, (100, 102, 108))
        col = tuple(max(0, min(255, c + jit)) for c in base)
        a0, a1 = (RK0, RK1) if RK1 > RK0 else (0, len(RP) - 1)
        AP, AF, AH = RP[a0:a1 + 1], RF[a0:a1 + 1], RH[a0:a1 + 1]       # asphalt: up to the junction plates' cuts
        L, R = _offset_v(AP, AF, AH, 1), _offset_v(AP, AF, AH, -1)
        if not foot:                                           # gutter strips + the asphalt itself
            g = 0.42
            L2, R2 = _offset_v(AP, AF, AH, 1, -g), _offset_v(AP, AF, AH, -1, -g)
            dark = tuple(c * 0.8 for c in col)
            _strip(out, L, L2, y, dark)
            _strip(out, R2, R, y, dark)
            _strip(out, L2, R2, y, col)
        else:
            _strip(out, L, R, y, col)
        # round fill at both ends so mitred junctions have no gaps
        for p, end_ in ((pts[0], 0), (pts[-1], 1)):
            if (i, end_) in joints:                            # shared cross-section: nothing to fill
                continue
            if (e["a"] if end_ == 0 else e["b"]) in plates:      # the plate covers the junction
                continue
            if e["bridge"] and deg.get(e["a"] if end_ == 0 else e["b"], 0) >= 2:     # deck meets its approach road: no bulge over it
                continue
            r = hw - (0.0 if foot else 0.0)
            ring = [(p[0] + math.cos(a * math.pi / 6) * r, p[1] + math.sin(a * math.pi / 6) * r) for a in range(12)]
            for k in range(0, 12, 2):
                a, b, c2 = ring[k], ring[(k + 1) % 12], ring[(k + 2) % 12]
                out.quad((p[0], y + 0.003, p[1]), (a[0], y + 0.003, a[1]), (b[0], y + 0.003, b[1]), (c2[0], y + 0.003, c2[1]), col)
        # pavements with a curb face, trimmed exactly where another road's asphalt starts (never drawn over it)
        if cls in SIDEWALK and not e["bridge"]:
            skip = partners.get(i, ())
            for side in (1, -1):
                inner = _offset_v(RP, RF, RH, side)
                outer = _offset_v(RP, RF, RH, side, SW_W)
                piece = 0
                first = last = None
                for k in range(RK0, RK1):                       # from the plate's cut to the plate's cut (or the shared joint)
                    ln = math.hypot(RP[k + 1][0] - RP[k][0], RP[k + 1][1] - RP[k][1])
                    nsub = _pieces(ln, RP[k][0], RP[k][1], RP[k + 1][0], RP[k + 1][1], 10.0)
                    I0, I1, O0, O1 = inner[k], inner[k + 1], outer[k], outer[k + 1]
                    lerp = lambda A, B, t: (A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t)

                    bend = any(RF[q][1] > 1.01 for q in range(max(0, k - 6), min(len(RP), k + 8)))
                    near_k = range(max(0, k - 6), min(len(RP) - 1, k + 7)) if bend else ()
                    hmin = min(RH[max(0, k - 6):k + 8]) - 0.1
                    busy = bend or any(cov.others(q[0], q[1], i, skip) for q in (I0, I1, O0, O1))

                    def bad(t):
                        ip, op = lerp(I0, I1, t), lerp(O0, O1, t)
                        for u in (0.04, 0.5, 0.96):
                            px_, py_ = ip[0] + (op[0] - ip[0]) * u, ip[1] + (op[1] - ip[1]) * u
                            if cov.covered(px_, py_, i, False, skip=skip):
                                return True
                            for q in near_k:                    # inside of a tight bend: the offset folds over the road's own asphalt
                                if _pdist(px_, py_, RP[q][0], RP[q][1], RP[q + 1][0], RP[q + 1][1]) < hmin:
                                    return True
                        return False
                    for sp in range(nsub):
                        runs = _free_runs(bad, sp / nsub, (sp + 1) / nsub, ln / nsub) if busy else ((sp / nsub, (sp + 1) / nsub),)
                        for t0, t1 in runs:
                            i0, i1, o0, o1 = lerp(I0, I1, t0), lerp(I0, I1, t1), lerp(O0, O1, t0), lerp(O0, O1, t1)
                            if first is None:
                                first = (i0, o0)
                            last = (i1, o1)
                            piece += 1
                            pav = 178 + (4 if piece % 2 else -4)
                            pc = (pav, pav - 4, pav - 12)
                            out.quad((i0[0], SW_H, i0[1]), (i1[0], SW_H, i1[1]), (o1[0], SW_H, o1[1]), (o0[0], SW_H, o0[1]), pc)
                            out.quad((i0[0], y, i0[1]), (i1[0], y, i1[1]), (i1[0], SW_H, i1[1]), (i0[0], SW_H, i0[1]),
                                     (150, 148, 142), 0.78)
                if first is not None:                            # where the pavement really starts / stops: the curb corners join there
                    trims[(i, 0, side)], trims[(i, 1, side)] = first, last
        # dead ends: the pavement wraps round the rounded asphalt end instead of stopping flush with it
        if cls in SIDEWALK and not e["bridge"]:
            for end_ in (0, 1):
                nd = e["a"] if end_ == 0 else e["b"]
                if (i, end_) in joints or nd in plates or deg.get(nd, 0) != 1:
                    continue
                p_ = pts[0] if end_ == 0 else pts[-1]
                da = _away(e, end_)
                nx_, ny_ = -da[1], da[0]
                prev = None
                for q in range(9):
                    th = math.pi * q / 8
                    ux, uy = nx_ * math.cos(th) - da[0] * math.sin(th), ny_ * math.cos(th) - da[1] * math.sin(th)
                    cur = ((p_[0] + ux * hw, p_[1] + uy * hw), (p_[0] + ux * (hw + SW_W), p_[1] + uy * (hw + SW_W)))
                    if prev:
                        (i0, o0), (i1, o1) = prev, cur
                        out.quad((i0[0], SW_H, i0[1]), (i1[0], SW_H, i1[1]), (o1[0], SW_H, o1[1]), (o0[0], SW_H, o0[1]), (172, 168, 158))
                        out.quad((i0[0], y, i0[1]), (i1[0], y, i1[1]), (i1[0], SW_H, i1[1]), (i0[0], SW_H, i0[1]), (150, 148, 142), 0.78)
                    prev = cur
        # lane markings
        if cls in MARK and e["drive"] and w >= 5.5 and e["len"] > 4:
            _markings(out, cov, i, e, pts, fr, y + 0.025)
        if deck is not None:                                   # girders + piers under the deck
            _slab(out, pts, fr, hw + 0.0, y)
            if e["road"] not in pier_done:
                pier_done.add(e["road"])
                _piers(pout, piers, deck, T)
        out.deck = None
    _junctions(out, edges, plates)
    _corners(out, edges, plates, ribs, trims)
    for x, yy, ax, ay, w, *_r in xwalks:                      # zebra crossings + stop lines
        _zebra(out, x, yy, ax, ay, w)
    if os.environ.get("ROADS_DEBUG"):
        _debug_dump(out, edges, os.environ["ROADS_DEBUG"])
    out.flush(add, mat)
    pout.flush(add, mat)
    return out.n + pout.n, piers


def _debug_dump(out, edges, prefix, S=8.0, R=45.0, count=14):
    """ROADS_DEBUG=<path prefix>: writes top-down PNGs (<prefix>_N.png) around the busiest junctions, bridge ends and dead ends."""
    from PIL import Image, ImageDraw
    tris = []
    for (p, c, deck) in out.d.values():
        for k in range(0, len(p), 3):
            tris.append((p[k:k + 3], c[k], deck is not None))
    tris.sort(key=lambda t: max(q[1] for q in t[0]) + (1.0 if t[2] else 0.0))
    deg, at = {}, {}
    for e in edges:
        for nd, q in ((e["a"], e["pts"][0]), (e["b"], e["pts"][-1])):
            deg[nd] = deg.get(nd, 0) + 1
            at[nd] = (q, e["bridge"])
    picks = sorted(at, key=lambda n: (-(at[n][1]) * 5 - deg[n]))[:count]
    for n_, nd in enumerate(picks):
        (cx, cy), _b = at[nd]
        W = int(2 * R * S)
        im = Image.new("RGB", (W, W), (60, 110, 60))
        d = ImageDraw.Draw(im)
        for t, col, _deck in tris:
            if not any(abs(q[0] - cx) < R and abs(q[2] - cy) < R for q in t):
                continue
            d.polygon([((q[0] - cx + R) * S, (q[2] - cy + R) * S) for q in t], fill=tuple(int(v) for v in col[:3]))
        im.save(f"{prefix}_{n_}.png")





PIER_SKIP = None          # set by build_world: (x, z, radius) -> True when a pier there would stand in a drivable lane below


def _piers(pout, piers, deck, T):
    """Concrete piers every ~22 m wherever the deck is clearly above the ground (rivers, valleys, over-roads)."""
    L = deck.len
    s = 18.0
    while s < L - 14.0:
        # position at s
        k = 0
        while k < len(deck.cum) - 2 and deck.cum[k + 1] < s:
            k += 1
        t = (s - deck.cum[k]) / ((deck.cum[k + 1] - deck.cum[k]) or 1.0)
        (ax, ay), (bx, by) = deck.pts[k], deck.pts[k + 1]
        x, z = ax + (bx - ax) * t, ay + (by - ay) * t
        yaw = math.atan2(by - ay, bx - ax)
        dh = deck.h[k] + (deck.h[k + 1] - deck.h[k]) * t
        tg = T.hs(x, z) if T is not None else 0.0
        if dh - tg > 1.6:
            width = max(2.0, deck.hw * 2 - 1.5)
            for lat in ((-1, 1) if width > 7 else (0,)):
                off = lat * width * 0.27
                px, pz = x - math.sin(yaw) * off, z + math.cos(yaw) * off
                sz = 1.3 if lat else min(width * 0.7, 6.0)
                if PIER_SKIP is not None and PIER_SKIP(px, pz, max(0.9, sz * 0.5)):
                    continue                               # the deck spans the street underneath instead
                tg2 = T.hs(px, pz) if T is not None else 0.0
                _pier(pout, px, pz, yaw, 1.3, sz, tg2 - 0.5, dh - SLAB + 0.05)
                piers.append((px, pz, max(0.9, sz * 0.5), tg2 - 1.0, dh - SLAB))
        s += 22.0


def _line(out, cov, me, e, pts, fr, off, y, width, col, dashed, rank):
    """A marking line at lateral offset `off` from the centreline: continuous or dashed (3 m on, 6 m off)."""
    P = offset(pts, fr, off)
    cum = _cum(P)
    total = cum[-1]
    spans = []
    if dashed:
        s = 1.2
        while s + 3.0 < total - 0.8:
            spans.append((s, s + 3.0))
            s += 9.0
    else:
        spans.append((0.6, total - 0.6))
    for s0, s1 in spans:
        if s1 - s0 < 0.3:
            continue
        n = max(1, int(math.ceil((s1 - s0) / 3.0)))
        prev = _at(P, cum, s0)
        for k in range(1, n + 1):
            q = _at(P, cum, s0 + (s1 - s0) * k / n)
            mx, my = (prev[0] + q[0]) * 0.5, (prev[1] + q[1]) * 0.5
            if cov.near_junction(mx, my) and (cov.covered(mx, my, me, e["bridge"], rank) or cov.covered(q[0], q[1], me, e["bridge"], rank)):
                prev = q
                continue
            dx, dy = q[0] - prev[0], q[1] - prev[1]
            l = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / l * width / 2, dx / l * width / 2
            out.quad((prev[0] + nx, y, prev[1] + ny), (q[0] + nx, y, q[1] + ny), (q[0] - nx, y, q[1] - ny), (prev[0] - nx, y, prev[1] - ny), col)
            prev = q


def lanes_per_way(e):
    """Lanes in each travel direction: the OSM lanes count where the map has one, otherwise from the width (one-way
    roads round(w/3.2), two-way roads two each way from 11 m).  src/actors.Traffic.lanes_of drives on these."""
    n, w = e.get("lanes", 0), e["w"]
    if e["ow"]:
        return n if n else max(1, int(round(w / 3.2)))
    return max(1, n // 2) if n else (2 if w >= 11.0 else 1)


def _markings(out, cov, i, e, pts, fr, y):
    w, rk = e["w"], rank_of(e["cls"])
    white, yellow = (236, 234, 224), (232, 206, 96)
    n_ = lanes_per_way(e)
    if n_ >= 3:                                              # 3+ lanes a side: the kerb lane is painted yellow, bus only (cars ignore it)
        lw = w / n_ if e["ow"] else w / 2 / n_
        for sgn in ((1,) if e["ow"] else (1, -1)):
            _line(out, cov, i, e, pts, fr, sgn * (w / 2 - lw / 2), y - 0.008, lw - 0.35, (214, 184, 70), False, rk)
    if e["ow"]:
        lanes = lanes_per_way(e)
        for k in range(1, lanes):
            _line(out, cov, i, e, pts, fr, -w / 2 + k * w / lanes, y, 0.13, white, True, rk)
    else:
        if w >= 8.0:
            _line(out, cov, i, e, pts, fr, 0.14, y, 0.11, yellow, False, rk)
            _line(out, cov, i, e, pts, fr, -0.14, y, 0.11, yellow, False, rk)
        else:
            _line(out, cov, i, e, pts, fr, 0.0, y, 0.13, white, True, rk)
        n = lanes_per_way(e)
        for k in range(1, n):
            for sgn in (1, -1):
                _line(out, cov, i, e, pts, fr, sgn * k * w / 2 / n, y, 0.12, white, True, rk)
    if w >= 7.0:
        for sgn in (1, -1):
            _line(out, cov, i, e, pts, fr, sgn * (w / 2 - 0.4), y, 0.1, white, False, rk)


def _zebra(out, x, y, ax, ay, w):
    rx, ry = ay, -ax                                         # across the road
    white = (240, 238, 230)
    yy = 0.134
    k = -w / 2 + 0.6
    while k < w / 2 - 0.3:
        cx, cy = x + rx * k, y + ry * k
        hl, hw = 1.5, 0.26
        a = (cx - ax * hl - rx * hw, yy, cy - ay * hl - ry * hw)
        b = (cx + ax * hl - rx * hw, yy, cy + ay * hl - ry * hw)
        c = (cx + ax * hl + rx * hw, yy, cy + ay * hl + ry * hw)
        d = (cx - ax * hl + rx * hw, yy, cy - ay * hl + ry * hw)
        out.quad(a, b, c, d, white)
        k += 1.0
    cx, cy = x + ax * 2.6, y + ay * 2.6                       # stop line on the right-hand lane
    hw = 0.14
    a = (cx - ax * hw, yy, cy - ay * hw)
    b = (cx + ax * hw, yy, cy + ay * hw)
    c = (b[0] + rx * (w / 2 - 0.3), yy, b[2] + ry * (w / 2 - 0.3))
    d = (a[0] + rx * (w / 2 - 0.3), yy, a[2] + ry * (w / 2 - 0.3))
    out.quad(a, b, c, d, white)
