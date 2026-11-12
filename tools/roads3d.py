"""3D road network built from the routing graph: smoothed centrelines, mitred asphalt ribbons with gutters,
junction fills, raised pavements with curb faces, lane markings and zebra crossings.

The OSM polylines are only used as guidance: corners are rounded, higher-class roads sit on top of lower ones, and
pavements / markings are cut away where another road's asphalt crosses them.  Everything is plain numpy triangles
(material 'solid': vertex colours on a white pixel), streamed per chunk like the buildings.
"""
import math
import os

import numpy as np

import par
from progress import Bar

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
BRIDGE_SW = 2.4                                          # extra deck width per side on a driven bridge: a real pavement to walk on
Y_BASE, Y_STEP = 0.05, 0.016
PIECE = 24.0                                             # longest ribbon piece (also keeps pieces inside their chunk)
SAG = 0.012                                              # allowed gap between a flat piece and the curved terrain (m)
CHUNK = 120.0                                            # chunk size of build_world.chunk_of (pool workers rebuild it)
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
        q = getattr(_T, "q", None)
        if q is not None and min(q.at_s(ax + (bx - ax) * t, ay + (by - ay) * t) for t in (0.0, 0.25, 0.5, 0.75, 1.0)) < -0.01:
            return min(max(n, int(math.ceil(ln / 1.5))), int(math.ceil(ln)))     # river quays: 1 m ground detail, follow it
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


_CLIPPED = 0


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
        e = self.d.setdefault((key, id(self.deck)), ([], [], self.deck, []))
        rgba = (min(255, col[0] * shade), min(255, col[1] * shade), min(255, col[2] * shade), 255)
        e[0].extend((a, b, c, a, c, d))
        e[1].extend((rgba,) * 6)
        self.n += 6

    def flush(self, add, mat):
        for k_, ((key, _did), (p, c, deck, pre)) in enumerate(self.d.items()):
            if _TICK[0] and k_ % 8 == 0:
                _TICK[0](k_ / max(1, len(self.d)))
            pos = np.concatenate([q[0] for q in pre] + [np.array(p, np.float32).reshape(-1, 3)])      # pre: blocks from the pool workers
            c = np.concatenate([q[1] for q in pre] + [np.array(c, np.uint8).reshape(-1, 4)])
            pos, c = _clean_tris(pos, c)
            if deck is None:
                pos, c = _drop_covered_pavement(pos, c)
                pos, c = _clean_tris(pos, c)                  # slivers left by the clipper
            if deck is not None:
                pos[:, 1] += np.array([deck.at(x, z)[0] for x, z in zip(pos[:, 0], pos[:, 2])], np.float32)
            elif self.T is not None:
                pos[:, 1] += self.T.h(pos[:, 0], pos[:, 2])
            add(key, mat, pos, np.zeros((len(pos), 2), np.float32), c)


def _clean_tris(pos, col):
    """Drops zero-area triangles and exact duplicates (same three vertices to 1 mm in the same winding)."""
    n = len(pos) // 3
    if n < 1:
        return pos, col
    t = pos[:n * 3].reshape(n, 3, 3).astype(np.float64)
    keep = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) * 0.5 >= 1e-5
    k = np.round(t * 1000).astype(np.int64)
    rows = np.stack([k.reshape(n, 9), np.roll(k, -1, axis=1).reshape(n, 9), np.roll(k, -2, axis=1).reshape(n, 9)], axis=1)
    can = rows[np.arange(n), np.argmin(rows.reshape(n, 3, 9)[:, :, 0] * 1_000_000_007 + rows.reshape(n, 3, 9)[:, :, 1] * 1_009 + rows.reshape(n, 3, 9)[:, :, 2], axis=1)]
    _, idx = np.unique(can, axis=0, return_index=True)
    uniq = np.zeros(n, bool)
    uniq[idx] = True
    keep &= uniq
    if keep.all():
        return pos, col
    ki = np.repeat(keep, 3)
    return pos[:n * 3][ki], col[:n * 3][ki]


def _raster(a, b, c3):
    """Interior cell centres of a triangle given in grid units -> (x0, y0, mask); mask is None for a degenerate one."""
    mx0, mx1 = int(min(a[0], b[0], c3[0])), int(max(a[0], b[0], c3[0])) + 1
    my0, my1 = int(min(a[1], b[1], c3[1])), int(max(a[1], b[1], c3[1])) + 1
    gx, gy = np.meshgrid(np.arange(mx0, mx1 + 1) + 0.5, np.arange(my0, my1 + 1) + 0.5)
    d = (b[1] - c3[1]) * (a[0] - c3[0]) + (c3[0] - b[0]) * (a[1] - c3[1])
    if abs(d) < 1e-9:
        return mx0, my0, None
    l1 = ((b[1] - c3[1]) * (gx - c3[0]) + (c3[0] - b[0]) * (gy - c3[1])) / d
    l2 = ((c3[1] - a[1]) * (gx - c3[0]) + (a[0] - c3[0]) * (gy - c3[1])) / d
    return mx0, my0, (l1 > 0.12) & (l2 > 0.12) & (1 - l1 - l2 > 0.12)


def _halfplane(poly, p, q, keep_inside):
    """Sutherland-Hodgman: the part of convex polygon `poly` on one side of line p->q (inside = left of the line)."""
    out = []
    n = len(poly)
    sg = 1.0 if keep_inside else -1.0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        fa = sg * ((q[0] - p[0]) * (a[1] - p[1]) - (q[1] - p[1]) * (a[0] - p[0]))
        fb = sg * ((q[0] - p[0]) * (b[1] - p[1]) - (q[1] - p[1]) * (b[0] - p[0]))
        if fa >= 0:
            out.append(a)
        if (fa >= 0) != (fb >= 0):
            t = fa / (fa - fb)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _poly_minus_tri(poly, tri):
    """Convex pieces of convex `poly` that lie outside triangle `tri` (both lists of (x, z))."""
    ar = (tri[1][0] - tri[0][0]) * (tri[2][1] - tri[0][1]) - (tri[1][1] - tri[0][1]) * (tri[2][0] - tri[0][0])
    if ar < 0:
        tri = [tri[0], tri[2], tri[1]]
    pieces, rem = [], poly
    for i in range(3):
        p, q = tri[i], tri[(i + 1) % 3]
        outside = _halfplane(rem, p, q, False)
        if len(outside) >= 3:
            pieces.append(outside)
        rem = _halfplane(rem, p, q, True)
        if len(rem) < 3:
            return pieces
    return pieces


def _area2(pl):
    return sum(pl[i][0] * pl[(i + 1) % len(pl)][1] - pl[(i + 1) % len(pl)][0] * pl[i][1] for i in range(len(pl)))


def _drop_covered_pavement(pos, col, G=0.2):
    """Pavement-top triangles (all vertices at SW_H) that lie completely inside earlier pavement triangles are drawn
    twice at the same height: drop them (z-fighting, extra polygons).  Raster test on a G-metre grid per chunk."""
    n = len(pos) // 3
    if n < 2:
        return pos, col
    t = pos.reshape(n, 3, 3)
    top = np.nonzero(np.all(np.abs(t[:, :, 1] - SW_H) < 1e-6, axis=1))[0]
    if len(top) < 2:
        return pos, col
    x0, z0 = float(t[top][:, :, 0].min()) - 1.0, float(t[top][:, :, 2].min()) - 1.0
    W = int((float(t[top][:, :, 0].max()) - x0) / G) + 3
    H = int((float(t[top][:, :, 2].max()) - z0) / G) + 3
    if W * H > 4_000_000:
        return pos, col
    grid = np.zeros((H, W), bool)
    keep = np.ones(n, bool)
    cc = col[:n * 3].reshape(n, 3, 4)[:, 0, :3].astype(int)
    aidx = np.nonzero((np.abs(t[:, 0, 1] - t[:, 1, 1]) < 1e-6) & (np.abs(t[:, 1, 1] - t[:, 2, 1]) < 1e-6) & (t[:, 0, 1] < SW_H - 0.03)
                      & (t[:, 0, 1] > 0.0) & (cc[:, 0] <= 135) & (cc[:, 2] >= cc[:, 0]))[0]
    bucket = {}
    for k in aidx:
        for bx in range(int(t[k, :, 0].min() // 8), int(t[k, :, 0].max() // 8) + 1):
            for bz in range(int(t[k, :, 2].min() // 8), int(t[k, :, 2].max() // 8) + 1):
                bucket.setdefault((bx, bz), []).append(k)
    extra_p, extra_c = [], []
    asp = np.zeros((H, W), bool)                            # cheap pre-test: only triangles touching asphalt cells go to the exact clipper
    for k in aidx:
        a, b, c3 = [((t[k, j, 0] - x0) / G, (t[k, j, 2] - z0) / G) for j in range(3)]
        ax0, ay0, am = _raster(a, b, c3)
        if am is not None:
            sub = asp[ay0:ay0 + am.shape[0], ax0:ax0 + am.shape[1]]
            sub |= am[:sub.shape[0], :sub.shape[1]]
    for k in top:
        if not keep[k]:
            continue
        a, b, c3 = [((t[k, j, 0] - x0) / G, (t[k, j, 2] - z0) / G) for j in range(3)]
        px0, py0, pm = _raster(a, b, c3)
        if pm is None:
            continue
        psub = asp[py0:py0 + pm.shape[0], px0:px0 + pm.shape[1]]
        if not (pm[:psub.shape[0], :psub.shape[1]] & psub).any():
            continue
        tri = [(float(t[k, j, 0]), float(t[k, j, 2])) for j in range(3)]
        cand = set()
        for bx in range(int(min(v[0] for v in tri) // 8), int(max(v[0] for v in tri) // 8) + 1):
            for bz in range(int(min(v[1] for v in tri) // 8), int(max(v[1] for v in tri) // 8) + 1):
                cand.update(bucket.get((bx, bz), ()))
        if not cand:
            continue
        orient = _area2(tri)
        pieces = [tri]
        hit = False
        for q in cand:
            at = [(float(t[q, j, 0]), float(t[q, j, 2])) for j in range(3)]
            if max(v[0] for v in at) < min(v[0] for v in tri) or min(v[0] for v in at) > max(v[0] for v in tri) or \
               max(v[1] for v in at) < min(v[1] for v in tri) or min(v[1] for v in at) > max(v[1] for v in tri):
                continue
            new_pieces = []
            for pc in pieces:
                out_ = _poly_minus_tri(pc, at)
                if abs(sum(abs(_area2(o)) for o in out_)) < abs(_area2(pc)) - 1e-6:
                    hit = True                              # the asphalt triangle really removed some area
                else:
                    out_ = [pc]
                new_pieces.extend(out_)
            pieces = new_pieces
            if not pieces:
                break
        if not hit:
            continue
        keep[k] = False
        cc3 = col[k * 3:k * 3 + 3]
        for pc in pieces:
            if abs(_area2(pc)) < 2e-3:
                continue
            if (_area2(pc) > 0) != (orient > 0):
                pc = pc[::-1]
            for i in range(1, len(pc) - 1):
                for v in (pc[0], pc[i], pc[i + 1]):
                    extra_p.append((v[0], SW_H, v[1]))
                extra_c.extend(cc3[:1].tolist() * 3)
    for k in top:
        if not keep[k]:
            continue
        a, b, c3 = [((t[k, j, 0] - x0) / G, (t[k, j, 2] - z0) / G) for j in range(3)]
        mx0, mx1 = int(min(a[0], b[0], c3[0])), int(max(a[0], b[0], c3[0])) + 1
        my0, my1 = int(min(a[1], b[1], c3[1])), int(max(a[1], b[1], c3[1])) + 1
        gx, gy = np.meshgrid(np.arange(mx0, mx1 + 1) + 0.5, np.arange(my0, my1 + 1) + 0.5)
        d = (b[1] - c3[1]) * (a[0] - c3[0]) + (c3[0] - b[0]) * (a[1] - c3[1])
        if abs(d) < 1e-9:
            keep[k] = False                                 # degenerate sliver
            continue
        l1 = ((b[1] - c3[1]) * (gx - c3[0]) + (c3[0] - b[0]) * (gy - c3[1])) / d
        l2 = ((c3[1] - a[1]) * (gx - c3[0]) + (a[0] - c3[0]) * (gy - c3[1])) / d
        m = (l1 > 0.12) & (l2 > 0.12) & (1 - l1 - l2 > 0.12)         # interior cells only (shared borders do not count)
        if not m.any():
            continue
        sub = grid[my0:my1 + 1, mx0:mx1 + 1]
        if np.all(sub[m]):
            keep[k] = False
        else:
            sub |= m
    ki = np.repeat(keep, 3)
    global _CLIPPED
    if extra_p:
        _CLIPPED += len(extra_p) // 3
        return (np.concatenate([pos[ki], np.array(extra_p, np.float32)]), np.concatenate([col[ki], np.array(extra_c, np.uint8).reshape(-1, 4)]))
    return pos[ki], col[ki]


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

    def set_cores(self, edges, plates):
        """Junction centres (plate nodes): no lane markings inside radius = widest half width + 1.5 m."""
        self.cores = {}
        c = self.CELL
        for e in edges:
            for nd, p in ((e["a"], e["pts"][0]), (e["b"], e["pts"][-1])):
                if nd in plates and (nd, p) not in self.cores:
                    self.cores[(nd, p)] = 1
                    self.cores.setdefault((int(p[0] // c), int(p[1] // c)), []).append((p[0], p[1], plates[nd][1] + 1.5))

    def in_core(self, x, y):
        c = self.CELL
        cx, cy = int(x // c), int(y // c)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py, r in getattr(self, "cores", {}).get((cx + dx, cy + dy), ()):
                    if (x - px) ** 2 + (y - py) ** 2 < r * r:
                        return True
        return False

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
    if isinstance(extra, list):
        return [(p[0] + f[0][0] * (h + x) * side * f[1], p[1] + f[0][1] * (h + x) * side * f[1]) for p, f, h, x in zip(P, fr, hwv, extra)]
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


def _clip_foot(L, R, covered):
    """Cut a footway strip back at both ends to where it leaves the asphalt of the road it joins (it used to run on to the
    node on the carriageway's centre line, a slab of pavement across the road).  None when all of it lies on asphalt."""
    def at(L, R, k, k2, t):
        return ((L[k][0] + (L[k2][0] - L[k][0]) * t, L[k][1] + (L[k2][1] - L[k][1]) * t),
                (R[k][0] + (R[k2][0] - R[k][0]) * t, R[k][1] + (R[k2][1] - R[k][1]) * t))

    def mid(l, r):
        return (l[0] + r[0]) / 2, (l[1] + r[1]) / 2

    def head(L, R):
        for k in range(len(L) - 1):
            if not covered(*mid(L[k], R[k])):
                return L[k:], R[k:]
            if not covered(*mid(L[k + 1], R[k + 1])):
                lo, hi = 0.0, 1.0                                  # the asphalt's edge, by bisection along the segment
                for _ in range(7):
                    m = (lo + hi) / 2
                    lo, hi = (m, hi) if covered(*mid(*at(L, R, k, k + 1, m))) else (lo, m)
                nl, nr = at(L, R, k, k + 1, hi)
                return [nl] + L[k + 1:], [nr] + R[k + 1:]
        return None

    h = head(L, R)
    if h is None:
        return None
    t = head(h[0][::-1], h[1][::-1])
    return None if t is None else (t[0][::-1], t[1][::-1])


def _hull_grid(hulls, c=40.0):
    """The junction hulls indexed by 40 m cell: (cell -> hulls whose box touches it)."""
    g = {}
    for h in hulls:
        for cx in range(int(h[0] // c), int(h[2] // c) + 1):
            for cy in range(int(h[1] // c), int(h[3] // c) + 1):
                g.setdefault((cx, cy), []).append(h)
    return g


def _in_hulls(hulls, x, y, c=40.0):
    """Is (x, y) inside a junction plate (the convex asphalt hull)?  `hulls` = _hull_grid()."""
    for x0, y0, x1, y1, H in hulls.get((int(x // c), int(y // c)), ()):
        if x0 <= x <= x1 and y0 <= y <= y1:
            n = len(H)
            side = [(H[(k + 1) % n][0] - H[k][0]) * (y - H[k][1]) - (H[(k + 1) % n][1] - H[k][1]) * (x - H[k][0]) for k in range(n)]
            if all(v >= -0.05 for v in side) or all(v <= 0.05 for v in side):
                return True
    return False


_TICK = [None]                                             # progress of the slow junction passes: fn(fraction)


def _corners(out, edges, plates, ribs, trims, cov, hulls):
    """Curb corners at every junction: the pavements of neighbouring roads join in a smooth arc (shared vertices at both
    ends), with asphalt filling the space between the arc and the junction plate."""
    hulls = _hull_grid(hulls)
    for k_, (node, (lst, maxhw)) in enumerate(plates.items()):
        if _TICK[0] and k_ % 16 == 0:
            _TICK[0](k_ / max(1, len(plates)))
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
            br = edges[top[0]]["bridge"]
            for j in range(len(I) - 1):
                mx_ = (I[j][0] + I[j + 1][0] + O[j][0] + O[j + 1][0]) / 4
                my_ = (I[j][1] + I[j + 1][1] + O[j][1] + O[j + 1][1]) / 4
                ix_, iy_ = (I[j][0] + I[j + 1][0]) / 2, (I[j][1] + I[j + 1][1]) / 2
                if (cov.covered(mx_, my_, -1, br) or _in_hulls(hulls, mx_, my_)) and (cov.covered(ix_, iy_, -1, br) or _in_hulls(hulls, ix_, iy_)):
                    continue                                       # that stretch lies on a carriageway: no kerb across asphalt
                out.quad((I[j][0], SW_H, I[j][1]), (I[j + 1][0], SW_H, I[j + 1][1]), (O[j + 1][0], SW_H, O[j + 1][1]), (O[j][0], SW_H, O[j][1]), pc)
                out.quad((I[j][0], yv - 0.012, I[j][1]), (I[j + 1][0], yv - 0.012, I[j + 1][1]), (I[j + 1][0], SW_H, I[j + 1][1]),
                         (I[j][0], SW_H, I[j][1]), (200, 196, 188), 0.92)


def _junctions(out, edges, plates, hulls):
    """One seamless asphalt plate over every junction where roads of different classes (or 3+ roads) meet: no steps
    between their heights, no gutter lines or end caps showing, one colour (that of the most important road)."""
    n = 0
    for k_, (node, (lst, maxhw)) in enumerate(plates.items()):
        if _TICK[0] and k_ % 16 == 0:
            _TICK[0](k_ / max(1, len(plates)))
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
        hulls.append((min(p[0] for p in H), min(p[1] for p in H), max(p[0] for p in H), max(p[1] for p in H), H))
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


class _X:
    """Everything one street's geometry needs, read-only (shared with the pool workers)."""


def _edge_body(i, X, out, pout, piers, ribs, trims, do_piers):
    """The geometry of edge i: its ribbon, asphalt, pavements, markings, bridge body -> out / pout / piers / ribs / trims."""
    edges, joints, plates, partners, deg, decks, cov, T = X.edges, X.joints, X.plates, X.partners, X.deg, X.decks, X.cov, X.T
    e = edges[i]
    if not (e["drive"] or e["walk"]):
        return
    cls, pts, w = _base(e["cls"]), e["pts"], e["w"]
    if len(pts) < 2:
        return
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
        if not e["drive"] and not e["bridge"]:
            lr = _clip_foot(L, R, lambda x_, y_: cov.covered(x_, y_, i, False))
            if lr is not None:
                _strip(out, lr[0], lr[1], y, col)
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
        if foot and not e["drive"] and cov.covered(p[0], p[1], i, False):
            continue                                       # a footway's end on a carriageway: no disc of pavement there
        r = hw - (0.0 if foot else 0.0)
        ring = [(p[0] + math.cos(a * math.pi / 6) * r, p[1] + math.sin(a * math.pi / 6) * r) for a in range(12)]
        for k in range(0, 12, 2):
            a, b, c2 = ring[k], ring[(k + 1) % 12], ring[(k + 2) % 12]
            out.quad((p[0], y + 0.003, p[1]), (a[0], y + 0.003, a[1]), (b[0], y + 0.003, b[1]), (c2[0], y + 0.003, c2[1]), col)
    bsw = BRIDGE_SW if (e["bridge"] and e["drive"]) else 0.0
    if bsw:                                                # bridge pavements: raised strips with a kerb face on both flanks of the carriageway
        for side in (1, -1):
            I_, O_ = offset(pts, fr, side * hw), offset(pts, fr, side * (hw + bsw))
            _strip(out, I_, O_, SW_H, (178, 174, 166))
            _wall(out, I_, SW_H, y, (200, 196, 188), 0.92)
    # pavements with a curb face, trimmed exactly where another road's asphalt starts (never drawn over it)
    if cls in SIDEWALK and not e["bridge"]:
        skip = partners.get(i, ())
        for side in (1, -1):
            inner = _offset_v(RP, RF, RH, side)
            sw_ = e.get("sw")
            if sw_:                                         # wider pavement beside diagonal bays, eased back to normal over the last 6 m of each end
                dd = [min(math.hypot(q[0] - pts[0][0], q[1] - pts[0][1]), math.hypot(q[0] - pts[-1][0], q[1] - pts[-1][1])) for q in RP]
                sw_ = [SW_W + (sw_ - SW_W) * min(1.0, max(0.0, (d_ - 10.0) / 6.0)) for d_ in dd]
            outer = _offset_v(RP, RF, RH, side, sw_ or SW_W)
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
                                 (200, 196, 188), 0.92)
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
                    out.quad((i0[0], y, i0[1]), (i1[0], y, i1[1]), (i1[0], SW_H, i1[1]), (i0[0], SW_H, i0[1]), (200, 196, 188), 0.92)
                prev = cur
    # lane markings
    if cls in MARK and e["drive"] and w >= 5.5 and e["len"] > 4:
        _markings(out, cov, i, e, pts, fr, y + 0.025)
    if deck is not None:                                   # girders + piers under the deck
        _slab(out, pts, fr, hw + bsw, y)
        if do_piers:
            _piers(pout, piers, deck, T)
    out.deck = None


def _prepare(edges, joints, plates, decks, T):
    X = _X()
    X.edges, X.joints, X.plates, X.decks, X.T = edges, joints, plates, decks, T
    partners = {}                                          # edge -> the edges it continues into at a shared joint (they never cut its pavement)
    jn = {}
    for (k_, end_) in joints:
        jn.setdefault(edges[k_]["a"] if end_ == 0 else edges[k_]["b"], []).append(k_)
    for ks in jn.values():
        for k_ in ks:
            partners.setdefault(k_, set()).update(q for q in ks if q != k_)
    deg = {}
    for e_ in edges:
        if e_["drive"] or e_["walk"]:
            deg[e_["a"]] = deg.get(e_["a"], 0) + 1
            deg[e_["b"]] = deg.get(e_["b"], 0) + 1
    X.partners, X.deg = partners, deg
    return X


_W = [None]                                                # the worker's own copy of the context


def _init_worker(edges, joints, plates, decks, T, chunk):
    global _T
    _T = T
    _MICRO.clear()
    for i_, e_ in enumerate(edges):
        _MICRO[id(e_)] = (i_ * 5 % 8) * 0.0011
    X = _prepare(edges, joints, plates, decks, T)
    X.cov = Cover(edges)
    X.cov.set_cores(edges, plates)
    X.chunk_of = lambda x, z: (math.floor(x / chunk), math.floor(z / chunk))      # = build_world.chunk_of
    X.roadof = {id(d): r for r, d in (decks or {}).items()}
    _W[0] = X


def _pack(out, roadof):
    """An Out's entries as arrays that cross the process boundary cheaply: [(chunk key, road of its deck or None, pos, rgba)]."""
    return [(key, roadof.get(did), np.array(p, np.float32).reshape(-1, 3), np.array(c, np.uint8).reshape(-1, 4))
            for (key, did), (p, c, _deck, _pre) in out.d.items()]


def _edge_job(job):
    """job = [(edge index, builds its bridge piers?)] in order -> its meshes and per-edge results (runs in a worker)."""
    X = _W[0]
    out, pout = Out(X.chunk_of, X.T), Out(X.chunk_of)
    ribs, trims, piers = {}, {}, []
    for i, do_piers in job:
        e = X.edges[i]
        out.deck = X.decks.get(e["road"]) if (X.decks and e["bridge"]) else None
        _edge_body(i, X, out, pout, piers, ribs, trims, do_piers)
    return _pack(out, X.roadof), _pack(pout, X.roadof), ribs, trims, piers, out.n, pout.n


def _merge(out, packed, decks):
    for key, road, pos, col in packed:
        deck = decks.get(road) if road is not None else None
        e = out.d.setdefault((key, id(deck)), ([], [], deck, []))
        e[3].append((pos, col))
        out.n += len(pos)


def build(edges, xwalks, add, chunk_of, mat, T=None, decks=None):
    """Adds all road geometry to the mesh accumulator.  -> (number of vertices, pier collision posts)."""
    global _T
    _T = T
    bar = Bar("3D roads", 1000, unit="")

    def prog(f, note=None):
        bar.update(int(1000 * f), note)
    cov = Cover(edges)
    prog(0.02, "cover grid")
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
    prog(0.04, "joints")
    plates = _plate_nodes(edges, joints)
    cov.set_cores(edges, plates)
    prog(0.06, "junction plates")
    ribs = {}
    out = Out(chunk_of, T)
    pout = Out(chunk_of)                                   # piers: absolute heights
    piers = []
    pier_done = set()
    order = sorted(range(len(edges)), key=lambda i: (edges[i]["bridge"], rank_of(edges[i]["cls"])))
    pier_edges, done_ = set(), set()
    for i in order:
        e = edges[i]
        if (e["drive"] or e["walk"]) and len(e["pts"]) >= 2 and e["road"] not in done_ and decks and e["bridge"] and decks.get(e["road"]) is not None:
            done_.add(e["road"])
            pier_edges.add(i)
    prog(0.065, "junction plates")
    X = _prepare(edges, joints, plates, decks, T)
    prog(0.07, "streets")
    X.cov, X.chunk_of = cov, chunk_of
    nj = par.jobs()
    if nj > 1 and len(order) > 400 and chunk_of(CHUNK * 3 + 1, -CHUNK * 2 - 1) == (3, -3):
        nslice = nj * 6
        slices = [[(i, False) for i in order[k * len(order) // nslice:(k + 1) * len(order) // nslice]] for k in range(nslice)]
        for k_, (po, pp, rb, tr, pr, n1, n2) in enumerate(par.pmap(_edge_job, slices, init=(_init_worker, (edges, joints, plates, decks, T, CHUNK)), chunk=1)):
            prog(0.06 + 0.64 * (k_ + 1) / nslice, "streets")
            _merge(out, po, decks)
            _merge(pout, pp, decks)
            ribs.update(rb)
            trims.update(tr)
            piers.extend(pr)
        for i in order:                                    # piers last: PIER_SKIP (a closure over the lane grid) lives in this process only
            if i in pier_edges:
                _piers(pout, piers, decks[edges[i]["road"]], T)
    else:
        for n_, i in enumerate(order):
            prog(0.06 + 0.64 * n_ / max(1, len(order)), "streets")
            e = edges[i]
            out.deck = decks.get(e["road"]) if (decks and e["bridge"]) else None
            _edge_body(i, X, out, pout, piers, ribs, trims, i in pier_edges)
    hulls = []
    _TICK[0] = lambda f: prog(0.7 + 0.12 * f, "junctions")
    _junctions(out, edges, plates, hulls)
    _TICK[0] = lambda f: prog(0.82 + 0.12 * f, "corners")
    _corners(out, edges, plates, ribs, trims, cov, hulls)
    _TICK[0] = None
    for k_, (x, yy, ax, ay, w, *_r) in enumerate(xwalks):    # zebra crossings + stop lines
        if k_ % 32 == 0:
            prog(0.94 + 0.03 * k_ / max(1, len(xwalks)), "crossings")
        _zebra(out, x, yy, ax, ay, w)
        if _has_pavement(cov, edges, x, yy, w):
            _kerb_ramps(out, x, yy, ax, ay, w)
    prog(0.968, "lane arrows")
    _approach_marks(out, cov, edges, xwalks)
    _TICK[0] = lambda f: prog(0.97 + 0.025 * f, "mesh")
    if os.environ.get("ROADS_DEBUG"):
        _debug_dump(out, edges, os.environ["ROADS_DEBUG"])
    out.flush(add, mat)
    print('[roads] pavement triangles clipped out of asphalt:', _CLIPPED)
    _TICK[0] = None
    pout.flush(add, mat)
    bar.done()
    return out.n + pout.n, piers


def _debug_dump(out, edges, prefix, S=8.0, R=45.0, count=14):
    """ROADS_DEBUG=<path prefix>: writes top-down PNGs (<prefix>_N.png) around the busiest junctions, bridge ends and dead ends."""
    from PIL import Image, ImageDraw
    tris = []
    for (p, c, deck, _pre) in out.d.values():
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
            if cov.in_core(mx, my) or cov.in_core(q[0], q[1]):
                prev = q
                continue
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
    roads round(w/3.5), two-way roads two each way from 13 m).  src/actors.Traffic.lanes_of drives on these."""
    n, w = e.get("lanes", 0), e["w"]
    if e["ow"]:
        return n if n else max(1, int(round(w / 3.5)))
    return max(1, n // 2) if n else (2 if w >= 13.0 else 1)


def _markings(out, cov, i, e, pts, fr, y):
    w, rk = e["w"], rank_of(e["cls"])
    white, yellow = (236, 234, 224), (232, 206, 96)
    bus = lanes_per_way(e) >= 3                              # 3+ lanes a side: the kerb lane's markings are yellow (bus only, cars ignore it)
    bus_c = (232, 190, 40)
    if e["ow"]:
        lanes = lanes_per_way(e)
        for k in range(1, lanes):
            yl = bus and k == lanes - 1
            _line(out, cov, i, e, pts, fr, -w / 2 + k * w / lanes, y, 0.13, bus_c if yl else white, not yl, rk)
    else:
        if w >= 8.0:
            _line(out, cov, i, e, pts, fr, 0.14, y, 0.11, yellow, False, rk)
            _line(out, cov, i, e, pts, fr, -0.14, y, 0.11, yellow, False, rk)
        else:
            _line(out, cov, i, e, pts, fr, 0.0, y, 0.13, white, True, rk)
        n = lanes_per_way(e)
        for k in range(1, n):
            yl = bus and k == n - 1
            for sgn in (1, -1):
                _line(out, cov, i, e, pts, fr, sgn * k * w / 2 / n, y, 0.12, bus_c if yl else white, not yl, rk)
    if w >= 7.0:
        for sgn in (1, -1):
            _line(out, cov, i, e, pts, fr, sgn * (w / 2 - 0.4), y, 0.1, bus_c if bus else white, False, rk)


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


def _has_pavement(cov, edges, x, y, w):
    """Is the crossing on a road that has raised pavements (not a bridge, not a service lane)?"""
    c = cov.CELL
    best, bi = 1e9, None
    for sg in cov.segs.get((int(x // c), int(y // c)), ()):
        d = _pdist(x, y, sg[1], sg[2], sg[3], sg[4])
        if d < best:
            best, bi = d, sg[0]
    if bi is None or best > w / 2 + 1.0:
        return False
    e = edges[bi]
    return not e["bridge"] and e["cls"] in SIDEWALK


def _kerb_ramps(out, x, y, ax, ay, w):
    """Dropped kerb where the zebra meets each pavement: a sloped pavement-coloured wedge over the kerb face with a
    yellow tactile (blister) patch beyond it.  A handful of quads per crossing."""
    rx, ry = ay, -ax
    pc, tac = (178, 174, 166), (214, 184, 70)
    hl = 1.2                                                 # half the ramp's length along the road
    for sgn in (1, -1):
        e0, e1 = sgn * (w / 2 - 0.06), sgn * (w / 2 + 0.95)
        e2 = sgn * (w / 2 + 1.55)
        def P(lat, a_, yy):
            return (x + rx * lat + ax * a_, yy, y + ry * lat + ay * a_)
        def both(a, b, c, d, col, sh=TOP):                   # either winding: whichever faces up survives culling
            out.quad(a, b, c, d, col, sh)
            out.quad(d, c, b, a, col, sh)
        both(P(e0, -hl, 0.03), P(e0, hl, 0.03), P(e1, hl, SW_H + 0.004), P(e1, -hl, SW_H + 0.004), (196, 192, 184), 0.95)
        for k in range(4):                                   # tactile bars across the walking direction
            a0 = -hl + 0.15 + k * 0.58
            both(P(e1, a0, SW_H + 0.007), P(e1, a0 + 0.34, SW_H + 0.007), P(e2, a0 + 0.34, SW_H + 0.007), P(e2, a0, SW_H + 0.007), tac)


ARROW = (236, 234, 224)


def _turns(e, end):
    """Turn arrows of the lanes approaching edge end `end` (0 = node a, 1 = node b), leftmost lane first.
    From OSM turn:lanes where the map has it, else a default: the left lane may turn left, the right lane right."""
    fwd, bwd = e.get("turn", ("", ""))
    if e["ow"]:
        if end == 0:
            return None                                       # one-way traffic only reaches node b
        n, tag = lanes_per_way(e), fwd
    else:
        n, tag = lanes_per_way(e), (fwd if end == 1 else bwd)
    if tag:
        lanes = [set(x.split(";")) for x in tag.split("|")]
        return lanes if 1 <= len(lanes) <= 6 else None
    if n < 2:
        return None
    return [{"left", "through"}] + [{"through"}] * (n - 2) + [{"through", "right"}]


def _arrow(out, C, u, r, y, kinds):
    """One painted arrow: C centre, u unit vector of travel, r unit vector to the driver's right."""
    def P(f, l):
        return (C[0] + u[0] * f + r[0] * l, y, C[1] + u[1] * f + r[1] * l)

    def quad(pts):
        q = [P(*v) for v in pts]
        out.quad(*q, ARROW)
        out.quad(*q[::-1], ARROW)                             # both windings: one of them faces up

    def tri(pts):
        a, b, c = [P(*q) for q in pts]
        out.quad(a, b, c, c, ARROW)
        out.quad(c, b, a, a, ARROW)
    straight = "through" in kinds or not (kinds & {"left", "right", "slight_left", "slight_right"})
    top = 0.6 if straight else -0.3
    quad([(-2.6, -0.08), (top, -0.08), (top, 0.08), (-2.6, 0.08)])
    if straight:
        tri([(0.6, -0.33), (1.8, 0.0), (0.6, 0.33)])
    for side, names in ((-1, ("left", "slight_left")), (1, ("right", "slight_right"))):
        if kinds & set(names):
            quad([(-0.66, 0.0), (-0.66, side * 0.75), (-0.36, side * 0.75), (-0.36, 0.0)] if side > 0 else
                 [(-0.66, side * 0.75), (-0.66, 0.0), (-0.36, 0.0), (-0.36, side * 0.75)])
            tri([(-1.05, side * 0.75), (-0.51, side * 1.5), (0.03, side * 0.75)] if side > 0 else
                [(0.03, side * 0.75), (-0.51, side * 1.5), (-1.05, side * 0.75)])


def _approach_marks(out, cov, edges, xwalks):
    """Lane arrows on every multi-lane (or turn-lane tagged) approach to a junction, and give-way teeth across the
    approach of a minor road meeting a bigger one where there is no signalled crossing."""
    inc = {}
    for i, e in enumerate(edges):
        if e["drive"] and len(e["pts"]) >= 2:
            inc.setdefault(e["a"], []).append((i, 0))
            inc.setdefault(e["b"], []).append((i, 1))
    xg = {}
    for xw in xwalks:
        xg.setdefault((int(xw[0] // 20), int(xw[1] // 20)), []).append((xw[0], xw[1]))

    def near_x(x, y, r):
        return any((x - qx) ** 2 + (y - qy) ** 2 < r * r for gx in (-1, 0, 1) for gy in (-1, 0, 1)
                   for qx, qy in xg.get((int(x // 20) + gx, int(y // 20) + gy), ()))
    for node, lst in inc.items():
        if len(lst) < 3:
            continue
        maxw = max(edges[i]["w"] for i, _ in lst)
        top = max(rank_of(edges[i]["cls"]) for i, _ in lst)
        for i, end in lst:
            e = edges[i]
            if e["bridge"] or _base(e["cls"]) not in MARK or e["w"] < 5.5:
                continue
            pts = e["pts"] if end == 1 else e["pts"][::-1]      # walk towards the junction
            cum = _cum(pts)
            L = cum[-1]
            d_stop = maxw / 2 + 3.2 + 3.4                       # just behind the zebra's stop line
            y = y_of(e) + 0.027
            w = e["w"]

            def frame(s):
                p = _at(pts, cum, s)
                q = _at(pts, cum, min(L, s + 1.0)) if s + 1.0 <= L else p
                o = _at(pts, cum, max(0.0, s - 1.0))
                dx, dy = q[0] - o[0], q[1] - o[1]
                ln = math.hypot(dx, dy) or 1.0
                u = (dx / ln, dy / ln)
                return p, u, (-u[1], u[0])                      # right of the driver (furniture.py: r = (ay, -ax) with a = -u)
            if e["ow"] and end == 0:
                continue
            lo, hi = (-w / 2, w / 2) if e["ow"] else (0.0, w / 2)
            if L - d_stop > 4.0 and rank_of(e["cls"]) < top and not near_x(*_at(pts, cum, L - (maxw / 2 + 3.2))[:2], 7.0):
                p, u, r = frame(L - d_stop + 1.0)                # give-way teeth across the approach lanes
                k = lo + 0.35
                while k + 0.3 < hi - 0.2:
                    C = (p[0] + r[0] * (k + 0.3), p[1] + r[1] * (k + 0.3))
                    a = (C[0] - r[0] * 0.3, y, C[1] - r[1] * 0.3)
                    b = (C[0] - u[0] * 0.6, y, C[1] - u[1] * 0.6)    # the tooth points at the approaching driver
                    c = (C[0] + r[0] * 0.3, y, C[1] + r[1] * 0.3)
                    out.quad(a, b, c, c, ARROW)
                    out.quad(c, b, a, a, ARROW)
                    k += 0.9
            lanes = _turns(e, end)
            if not lanes:
                continue
            s_ar = L - d_stop - 4.5
            if s_ar < 3.0:
                continue
            p, u, r = frame(s_ar)
            if cov.in_core(p[0], p[1]) or (cov.near_junction(p[0], p[1]) and cov.covered(p[0], p[1], i, False)):
                continue
            n = len(lanes)
            for k, kinds in enumerate(lanes):
                off = lo + (k + 0.5) * (hi - lo) / n
                _arrow(out, (p[0] + r[0] * off, p[1] + r[1] * off), u, r, y, kinds)
