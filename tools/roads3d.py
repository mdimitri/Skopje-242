"""3D road network built from the routing graph: smoothed centrelines, mitred asphalt ribbons with gutters,
junction fills, raised pavements with curb faces, lane markings and zebra crossings.

The OSM polylines are only used as guidance: corners are rounded, higher-class roads sit on top of lower ones, and
pavements / markings are cut away where another road's asphalt crosses them.  Everything is plain numpy triangles
(material 'solid': vertex colours on a white pixel), streamed per chunk like the buildings.
"""
import math

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
Y_BASE, Y_STEP = 0.05, 0.012
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


def y_of(e):
    if _base(e["cls"]) in FOOT:
        return 0.04
    return Y_BASE + Y_STEP * rank_of(e["cls"]) + (0.01 if e["bridge"] else 0.0)


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

    def covered(self, x, y, me, bridge, my_rank=None):
        """True when another road's asphalt (for markings: of higher precedence) lies over (x, y)."""
        c = self.CELL
        for s in self.segs.get((int(x // c), int(y // c)), ()):
            i, ax, ay, bx, by, hw, rk, br = s
            if i == me or br != bridge:
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


def _junctions(out, edges):
    """One seamless asphalt plate over every junction where roads of different classes (or 3+ roads) meet: no steps
    between their heights, no gutter lines or end caps showing, one colour (that of the most important road)."""
    inc = {}
    for i, e in enumerate(edges):
        if e["drive"] and not e["bridge"] and len(e["pts"]) >= 2 and _base(e["cls"]) not in FOOT:
            inc.setdefault(e["a"], []).append((i, 0))
            inc.setdefault(e["b"], []).append((i, 1))
    n = 0
    for node, lst in inc.items():
        ranks = {rank_of(edges[i]["cls"]) for i, _ in lst}
        if len(lst) < 2 or (len(lst) == 2 and len(ranks) == 1 and
                            abs(edges[lst[0][0]]["w"] - edges[lst[1][0]]["w"]) < 0.6):
            continue
        top = max(lst, key=lambda q: (rank_of(edges[q[0]]["cls"]), edges[q[0]]["w"]))
        maxhw = max(edges[i]["w"] / 2 for i, _ in lst)
        y = max(y_of(edges[i]) for i, _ in lst) + 0.006
        col = FILL.get(_base(edges[top[0]]["cls"]), (100, 102, 108))
        P = []
        for i, end in lst:
            e = edges[i]
            pts = e["pts"]
            cum = _cum(pts)
            L = cum[-1]
            hw = e["w"] / 2
            d = min(L * 0.45, maxhw * 1.15 + 1.0, 9.0)
            s0 = d if end == 0 else L - d
            q = _at(pts, cum, s0)
            q2 = _at(pts, cum, min(L, s0 + 0.5) if end == 0 else max(0.0, s0 - 0.5))
            tx, tz = q2[0] - q[0], q2[1] - q[1]
            tl = math.hypot(tx, tz) or 1.0
            nx, nz = -tz / tl, tx / tl
            P += [(q[0] + nx * hw, q[1] + nz * hw), (q[0] - nx * hw, q[1] - nz * hw)]
            c0 = pts[0] if end == 0 else pts[-1]
            P += [(c0[0] + nx * hw, c0[1] + nz * hw), (c0[0] - nx * hw, c0[1] - nz * hw)]
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
        deck = decks.get(e["road"]) if (decks and e["bridge"]) else None
        out.deck = deck
        foot = cls in FOOT
        jit = 0 if foot else (i * 7 % 9) - 4
        base = FILL.get(cls, (100, 102, 108))
        col = tuple(max(0, min(255, c + jit)) for c in base)
        L, R = offset(pts, fr, hw), offset(pts, fr, -hw)
        if not foot:                                           # gutter strips + the asphalt itself
            g = 0.42
            L2, R2 = offset(pts, fr, hw - g), offset(pts, fr, -(hw - g))
            dark = tuple(c * 0.8 for c in col)
            _strip(out, L, L2, y, dark)
            _strip(out, R2, R, y, dark)
            _strip(out, L2, R2, y, col)
        else:
            _strip(out, L, R, y, col)
        # round fill at both ends so mitred junctions have no gaps
        for p in (pts[0], pts[-1]):
            r = hw - (0.0 if foot else 0.0)
            ring = [(p[0] + math.cos(a * math.pi / 6) * r, p[1] + math.sin(a * math.pi / 6) * r) for a in range(12)]
            for k in range(0, 12, 2):
                a, b, c2 = ring[k], ring[(k + 1) % 12], ring[(k + 2) % 12]
                out.quad((p[0], y + 0.003, p[1]), (a[0], y + 0.003, a[1]), (b[0], y + 0.003, b[1]), (c2[0], y + 0.003, c2[1]), col)
        # pavements with a curb face
        if cls in SIDEWALK and not e["bridge"]:
            for side in (1, -1):
                inner = offset(pts, fr, side * hw)
                outer = offset(pts, fr, side * (hw + SW_W))
                piece = 0
                for k in range(len(pts) - 1):
                    ln = math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
                    nsub = _pieces(ln, pts[k][0], pts[k][1], pts[k + 1][0], pts[k + 1][1], 10.0)
                    for s in range(nsub):
                        t0, t1 = s / nsub, (s + 1) / nsub
                        i0 = (inner[k][0] + (inner[k + 1][0] - inner[k][0]) * t0, inner[k][1] + (inner[k + 1][1] - inner[k][1]) * t0)
                        i1 = (inner[k][0] + (inner[k + 1][0] - inner[k][0]) * t1, inner[k][1] + (inner[k + 1][1] - inner[k][1]) * t1)
                        o0 = (outer[k][0] + (outer[k + 1][0] - outer[k][0]) * t0, outer[k][1] + (outer[k + 1][1] - outer[k][1]) * t0)
                        o1 = (outer[k][0] + (outer[k + 1][0] - outer[k][0]) * t1, outer[k][1] + (outer[k + 1][1] - outer[k][1]) * t1)
                        mx, my = (i0[0] + o1[0]) * 0.5, (i0[1] + o1[1]) * 0.5
                        piece += 1
                        if cov.near_junction(mx, my) and (cov.covered(mx, my, i, False) or cov.covered(i0[0], i0[1], i, False)
                                                         or cov.covered(o1[0], o1[1], i, False)):
                            continue
                        pav = 178 + (4 if piece % 2 else -4) + (jit * 0)
                        pc = (pav, pav - 4, pav - 12)
                        out.quad((i0[0], SW_H, i0[1]), (i1[0], SW_H, i1[1]), (o1[0], SW_H, o1[1]), (o0[0], SW_H, o0[1]), pc)
                        out.quad((i0[0], y, i0[1]), (i1[0], y, i1[1]), (i1[0], SW_H, i1[1]), (i0[0], SW_H, i0[1]),
                                 (150, 148, 142), 0.78)
        # lane markings
        if cls in MARK and e["drive"] and w >= 5.5 and e["len"] > 4:
            _markings(out, cov, i, e, pts, fr, y + 0.025)
        if deck is not None:                                   # girders + piers under the deck
            _slab(out, pts, fr, hw + 0.0, y)
            if e["road"] not in pier_done:
                pier_done.add(e["road"])
                _piers(pout, piers, deck, T)
        out.deck = None
    _junctions(out, edges)
    for x, yy, ax, ay, w, *_r in xwalks:                      # zebra crossings + stop lines
        _zebra(out, x, yy, ax, ay, w)
    out.flush(add, mat)
    pout.flush(add, mat)
    return out.n + pout.n, piers


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


def _markings(out, cov, i, e, pts, fr, y):
    w, rk = e["w"], rank_of(e["cls"])
    white, yellow = (236, 234, 224), (232, 206, 96)
    if e["ow"]:
        lanes = max(1, int(round(w / 3.2)))
        for k in range(1, lanes):
            _line(out, cov, i, e, pts, fr, -w / 2 + k * w / lanes, y, 0.13, white, True, rk)
    else:
        if w >= 8.0:
            _line(out, cov, i, e, pts, fr, 0.14, y, 0.11, yellow, False, rk)
            _line(out, cov, i, e, pts, fr, -0.14, y, 0.11, yellow, False, rk)
        else:
            _line(out, cov, i, e, pts, fr, 0.0, y, 0.13, white, True, rk)
        if w >= 11.0:
            for sgn in (1, -1):
                _line(out, cov, i, e, pts, fr, sgn * w / 4, y, 0.12, white, True, rk)
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
