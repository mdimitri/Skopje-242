"""River quays: a fine (1 m) height overlay along every river.

Profile across a bank, by the distance d from the water's edge (the city never rises, it is only cut down):
    water at Hw  |  stone revetment up to the promenade (Hb = Hw + RISE, R_W wide)  |  lower promenade up to E  |
    grass embankment (1:2) up to the city ground.
E (how far the lower promenade reaches) comes from the OSM footpaths / cycleways that run along the water: their outer
edge + a margin, tapering off where they end, so a path that leaves the water climbs a gentle ramp.  Without such a
path E = R_W: revetment, then straight up the embankment.  Streets, pavements, buildings and bridge ends are never cut:
next to them the bank turns into a steep stone wall instead (at most KP metres of drop per metre of distance).

The overlay is a sparse set of TILE x TILE m tiles of height deltas (<= 0), sampled every QSTEP m and read bilinearly,
on top of the 10 m terrain; the same tiles carry a class per post (for painting: water, stone, promenade, grass).
"""
import heapq
import math
import numpy as np
from PIL import Image, ImageDraw

import par
from progress import frac

QSTEP = 1.0
TILE = 32                       # posts per tile side (tiles store TILE + 1 posts so a lookup never leaves its tile)
DROP = 3.4                      # water surface below the city ground of the banks (their mean) ...
MIN_DROP = 3.4                  # ... and below the lower bank: room under the bridges for the promenade
BANK_OFF = 32.0                 # ... measured this far beyond the water's edge
RISE = 0.9                      # promenade above the water
R_W = 1.6                       # width of the stone revetment between water and promenade
EMB = 0.5                       # grade of the grass embankment (rise per metre)
KP = 1.1                        # steepest cut next to protected ground (stone wall)
REACH = 46.0                    # the overlay fades out between REACH - 8 and REACH metres from the water
LOW_D = 18.0                    # a path this close to the water (and running along it) is on the lower promenade
MARGIN = 1.3                    # promenade beyond the outer edge of its path
RAMP_BIKE = 0.10                # steepest cycleway coming down from a street to the promenade
RAMP_FOOT = 0.6                 # ... and footpath (a flight of steps)
TAPER = 0.22                    # promenade end: its width shrinks this much per metre along the bank (a ~11 % ramp)
PIN_END = 8.0                   # a walkway under a deck this close to its end crosses it at grade
CLEAR_Q = 2.4                   # headroom for a walkway under a deck on the quays (the deck is lifted for it)
MAX_LIFT = 0.15                 # ... at most this grade from the deck's ends
DECK_G = 0.10                   # steepest grade a deck over the quays keeps between its lifts
FOOTISH = ("footway", "cycleway", "path", "bridleway", "track")
C_NONE, C_WATER, C_STONE, C_PROM, C_GRASS, C_WALL = 0, 1, 2, 3, 4, 5


def _seg_dist(px, py, S):
    """px, py: (n,) points; S: (m, 4) segments -> (dist (n, m), t (n, m))."""
    ax, ay, bx, by = S[:, 0][None], S[:, 1][None], S[:, 2][None], S[:, 3][None]
    dx, dy = bx - ax, by - ay
    l2 = np.maximum(dx * dx + dy * dy, 1e-9)
    t = np.clip(((px[:, None] - ax) * dx + (py[:, None] - ay) * dy) / l2, 0.0, 1.0)
    return np.hypot(px[:, None] - ax - dx * t, py[:, None] - ay - dy * t), t


def _pieces(fn, x, y, n=128):
    """fn(x, y) over a long run of points in pieces of n: each piece has a small bounding box, so few segments to test."""
    if len(x) <= n:
        return fn(x, y)
    parts = [fn(x[i:i + n], y[i:i + n]) for i in range(0, len(x), n)]
    if isinstance(parts[0], tuple):
        return tuple(np.concatenate(c) for c in zip(*parts))
    return np.concatenate(parts)


def _softplus(x, k):
    """Smooth max(0, x) with a rounding of about k."""
    return k * np.logaddexp(0.0, x / k)


def _smin(a, b, k):
    """Smooth min(a, b) (never above either)."""
    return -k * np.logaddexp(-a / k, -b / k)


def _subdiv(pts, step):
    out = [pts[0]]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.ceil(math.hypot(bx - ax, by - ay) / step)))
        out += [(ax + (bx - ax) * k / n, ay + (by - ay) * k / n) for k in range(1, n + 1)]
    return out


class _Grid:
    """Segments bucketed into a coarse grid for 'everything within r of this box' queries."""

    def __init__(self, segs, cell=64.0):
        self.c = cell
        self.S = np.asarray(segs, np.float64).reshape(-1, 4)
        self.g = {}
        for i, (ax, ay, bx, by) in enumerate(self.S):
            for gx in range(int(math.floor(min(ax, bx) / cell)), int(math.floor(max(ax, bx) / cell)) + 1):
                for gy in range(int(math.floor(min(ay, by) / cell)), int(math.floor(max(ay, by) / cell)) + 1):
                    self.g.setdefault((gx, gy), []).append(i)

    def near(self, x0, y0, x1, y1, r):
        c = self.c
        ids = set()
        for gx in range(int(math.floor((x0 - r) / c)), int(math.floor((x1 + r) / c)) + 1):
            for gy in range(int(math.floor((y0 - r) / c)), int(math.floor((y1 + r) / c)) + 1):
                ids.update(self.g.get((gx, gy), ()))
        return np.fromiter(sorted(ids), np.int64, len(ids))


class Overlay:
    """Sparse fine height overlay.  idx: (nty, ntx) int32 tile index or -1; d: (n, TILE+1, TILE+1) float32 deltas;
    cls: same shape, uint8 classes."""

    def __init__(self, hx, hy, idx, d, cls):
        self.hx, self.hy = hx, hy
        self.idx, self.d, self.cls = idx, d, cls

    def pack(self):
        return {"step": QSTEP, "tile": TILE, "nty": int(self.idx.shape[0]), "ntx": int(self.idx.shape[1]),
                "idx": self.idx.astype(np.int32).tobytes(), "d": self.d.astype(np.float32).tobytes(),
                "cls": self.cls.astype(np.uint8).tobytes(), "n": int(len(self.d))}

    def at(self, x, y):
        """Vectorised delta (bilinear) for numpy arrays of world x, y."""
        x = np.asarray(x, np.float64)
        y = np.asarray(y, np.float64)
        out = np.zeros(np.broadcast(x, y).shape, np.float64)
        fx = (x + self.hx) / QSTEP
        fy = (y + self.hy) / QSTEP
        nty, ntx = self.idx.shape
        tx = np.floor(fx / TILE).astype(np.int64)
        ty = np.floor(fy / TILE).astype(np.int64)
        ok = (tx >= 0) & (ty >= 0) & (tx < ntx) & (ty < nty)
        if not ok.any():
            return out
        ti = np.full(out.shape, -1, np.int64)
        ti[ok] = self.idx[ty[ok], tx[ok]]
        m = ti >= 0
        if not m.any():
            return out
        lx = fx[m] - tx[m] * TILE
        ly = fy[m] - ty[m] * TILE
        ix = np.minimum(lx.astype(np.int64), TILE - 1)
        iy = np.minimum(ly.astype(np.int64), TILE - 1)
        u, v = lx - ix, ly - iy
        D, k = self.d, ti[m]
        a = D[k, iy, ix] * (1 - u) + D[k, iy, ix + 1] * u
        b = D[k, iy + 1, ix] * (1 - u) + D[k, iy + 1, ix + 1] * u
        out[m] = a * (1 - v) + b * v
        return out

    def at_s(self, x, y):
        fx = (x + self.hx) / QSTEP
        fy = (y + self.hy) / QSTEP
        tx, ty = int(math.floor(fx / TILE)), int(math.floor(fy / TILE))
        nty, ntx = self.idx.shape
        if not (0 <= tx < ntx and 0 <= ty < nty):
            return 0.0
        k = int(self.idx[ty, tx])
        if k < 0:
            return 0.0
        lx, ly = fx - tx * TILE, fy - ty * TILE
        ix, iy = min(int(lx), TILE - 1), min(int(ly), TILE - 1)
        u, v = lx - ix, ly - iy
        D = self.d[k]
        a = float(D[iy, ix]) * (1 - u) + float(D[iy, ix + 1]) * u
        b = float(D[iy + 1, ix]) * (1 - u) + float(D[iy + 1, ix + 1]) * u
        return a * (1 - v) + b * v


# --------------------------------------------------------------------------------------------- water level
def _levels(lines, T, half_w):
    """Water surface along each river centreline: the mean of the two banks (city ground BANK_OFF m beyond the water's
    edge) minus DROP, but at least MIN_DROP below the lower bank, smoothed (rolling median, then mean); tributaries blend into the river they flow into.
    half_w(x, y) -> distance from a centreline point to the nearest bank.  -> list of (pts (n, 2), level (n,)), every 10 m."""
    out = []
    for pts in sorted(lines, key=lambda p: -sum(math.dist(a, b) for a, b in zip(p, p[1:]))):
        P = np.array(_subdiv(pts, 10.0), np.float64)
        if len(P) < 2:
            continue
        tg = np.gradient(P, axis=0)
        tg /= np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-9)[:, None]
        nrm = np.stack([-tg[:, 1], tg[:, 0]], 1)
        off = (np.minimum(half_w(P[:, 0], P[:, 1]), 80.0) + BANK_OFF)[:, None]
        L_, R_ = P + nrm * off, P - nrm * off
        gl, gr = T.h(L_[:, 0], L_[:, 1]).astype(np.float64), T.h(R_[:, 0], R_[:, 1]).astype(np.float64)
        n = len(gl)

        def smooth(g):
            lo = np.array([np.median(g[max(0, i - 6):i + 7]) for i in range(n)])
            return np.array([lo[max(0, i - 15):i + 16].mean() for i in range(n)])
        lv = np.minimum(smooth(0.5 * (gl + gr)) - DROP, smooth(np.minimum(gl, gr)) - MIN_DROP)
        if out:                                                  # meet the bigger river at a confluence
            S = np.concatenate([np.stack([p[:-1, 0], p[:-1, 1], p[1:, 0], p[1:, 1]], 1) for p, _ in out])
            V = np.concatenate([np.stack([l[:-1], l[1:]], 1) for _, l in out])
            for end in (0, n - 1):
                d, t = _seg_dist(P[end:end + 1, 0], P[end:end + 1, 1], S)
                j = int(np.argmin(d[0]))
                if d[0, j] < 40.0:
                    target = V[j, 0] + (V[j, 1] - V[j, 0]) * t[0, j]
                    s = np.arange(n) if end == 0 else (n - 1 - np.arange(n))
                    w = np.clip(1.0 - s * 10.0 / 300.0, 0.0, 1.0)
                    lv = lv + (target - lv[end]) * w
        out.append((P, lv))
    return out


# --------------------------------------------------------------------------------------------- bridges
EXT_UP = 9.0                    # a bridge end must clear the promenade by this much (the embankment above it)
EXT_MAX = 45.0                  # longest extension


def _extend_bridges(roads, nearest_bank, reach):
    """A bridge whose end lands on the lower promenade (or on the embankment above it) is carried on along the road it
    continues into, until the city ground: the promenade passes under the deck instead of being blocked.  Only a plain
    continuation (the one way going straight on from the end node, same one-way sense; pavements drawn as their own
    ways do not count) is taken over.  -> (number of bridge ends extended, [bridge ends left on the quay])."""
    at = {}
    for rd in roads:
        if len(rd["nodes"]) == len(rd["pts"]):
            for n in set(rd["nodes"]):
                at.setdefault(n, []).append(rd)
    fresh = [-10 ** 12]
    done, stuck = 0, []
    for rd in list(roads):
        if not rd.get("bridge") or len(rd["nodes"]) != len(rd["pts"]) or len(rd["pts"]) < 2:
            continue
        for end in (0, -1):
            node, p = rd["nodes"][end], rd["pts"][end]
            if any(o is not rd and o.get("bridge") for o in at.get(node, ())):
                continue                                            # a joint between two pieces of the same deck
            d, j, t, sd = nearest_bank(np.array([p[0]]), np.array([p[1]]))
            need = float(reach(j, t, sd)[0]) + EXT_UP
            if not (-1.0 <= d[0] < need):
                if -1.0 <= d[0] < REACH:
                    stuck.append(p)                                 # beyond the promenade, but the bank may still be cut
                continue
            q = rd["pts"][-2] if end == -1 else rd["pts"][1]
            hd = math.atan2(p[1] - q[1], p[0] - q[0])               # heading off the bridge end
            cands = []
            for o in at.get(node, ()):
                if o is rd or o.get("tunnel") or len(o["nodes"]) != len(o["pts"]):
                    continue
                if rd.get("drive") and o["cls"] in FOOTISH:           # a pavement drawn as its own way: not the road on
                    continue
                if o["nodes"][0] == node and node not in o["nodes"][1:]:
                    sq, sn_, fw = list(o["pts"]), list(o["nodes"]), True
                elif o["nodes"][-1] == node and node not in o["nodes"][:-1]:
                    sq, sn_, fw = list(o["pts"])[::-1], list(o["nodes"])[::-1], False
                else:
                    cands.append(None)                              # the end node sits mid-way along it: a junction
                    continue
                ho = math.atan2(sq[1][1] - sq[0][1], sq[1][0] - sq[0][0])
                straight = abs((ho - hd + math.pi) % (2 * math.pi) - math.pi) < math.radians(40)
                cands.append((o, sq, sn_, fw) if straight else None)
            if len(cands) != 1 or cands[0] is None:
                stuck.append(p)
                continue
            o, seq, sn, fwd = cands[0]
            if o.get("bridge") or o["layer"] != 0 or o["ow"] != rd["ow"] or (rd["ow"] and fwd != (end == -1)):
                stuck.append(p)                                     # (one-way: the flow must run on through the end node)
                continue
            cum = [0.0]
            for a, b in zip(seq, seq[1:]):
                cum.append(cum[-1] + math.dist(a, b))
            if cum[-1] < 4.0:
                stuck.append(p)
                continue
            ss = np.arange(1.0, min(cum[-1] - 2.0, EXT_MAX) + 0.01, 1.0)
            if not len(ss):
                stuck.append(p)
                continue
            k_ = np.clip(np.searchsorted(cum, ss) - 1, 0, len(seq) - 2)
            tt = (ss - np.array(cum)[k_]) / np.maximum(np.array(cum)[k_ + 1] - np.array(cum)[k_], 1e-9)
            P = np.array(seq)
            xs = P[k_, 0] + (P[k_ + 1, 0] - P[k_, 0]) * tt
            ys = P[k_, 1] + (P[k_ + 1, 1] - P[k_, 1]) * tt
            dd, jj, t2, sd2 = nearest_bank(xs, ys)
            ok = np.nonzero(dd >= reach(jj, t2, sd2) + EXT_UP)[0]
            s_cut = float(ss[ok[0]]) if len(ok) else float(ss[-1])
            near = [m for m in range(1, len(seq) - 1) if abs(cum[m] - s_cut) < 2.0]
            if near:                                                # close to an existing node: split there
                m = near[0]
                ext_p, ext_n, rest_p, rest_n = seq[1:m + 1], sn[1:m + 1], seq[m:], sn[m:]
            else:
                k = max(0, min(int(np.searchsorted(cum, s_cut)) - 1, len(seq) - 2))
                f_ = (s_cut - cum[k]) / max(cum[k + 1] - cum[k], 1e-9)
                cut = (seq[k][0] + (seq[k + 1][0] - seq[k][0]) * f_, seq[k][1] + (seq[k + 1][1] - seq[k][1]) * f_)
                fresh[0] -= 1
                ext_p, ext_n = seq[1:k + 1] + [cut], sn[1:k + 1] + [fresh[0]]
                rest_p, rest_n = [cut] + seq[k + 1:], [fresh[0]] + sn[k + 1:]
            if end == -1:
                rd["pts"] = list(rd["pts"]) + ext_p
                rd["nodes"] = list(rd["nodes"]) + ext_n
            else:
                rd["pts"] = ext_p[::-1] + list(rd["pts"])
                rd["nodes"] = ext_n[::-1] + list(rd["nodes"])
            o["pts"], o["nodes"] = (rest_p, rest_n) if fwd else (rest_p[::-1], rest_n[::-1])
            for n in set(rd["nodes"]):
                lst = at.setdefault(n, [])
                if rd not in lst:
                    lst.append(rd)
            if node in at and o in at[node] and node not in o["nodes"]:
                at[node].remove(o)
            done += 1
    return done, stuck


# --------------------------------------------------------------------------------------------- the build
_W = {}                                                   # worker process: its tile function


def _worker_init(args):
    build(*args, log=lambda *a, **k: None, _worker=True)


def _tile_job(t_):
    return _W["tile"](t_)


def build(T, river_polys, river_lines, roads, buildings, bld_img, cell, hx, hy, log=print, _worker=False):
    """river_polys: [(outer, holes)]; river_lines: [(pts, width)] (width >= 8: painted as water);
    roads: build_world road dicts; buildings: dicts with 'ring'; bld_img: building mask at `cell` m.
    -> (Overlay or None, info dict for the meshes)."""
    if not river_polys and not river_lines:
        return None, {}
    tick = (lambda f, sub='quays': None) if _worker else (lambda f, sub='quays': frac(f, sub))      # (workers stay silent)
    pinit = None
    if not _worker and par.jobs() > 1:                  # start the workers now: they repeat the set-up below while this process does it
        pinit = (_worker_init, ((T, river_polys, river_lines, roads, buildings, bld_img, cell, hx, hy),))
        try:
            par._pool(pinit)
        except (OSError, ImportError):
            pinit = None
    W, H = int(round(2 * hx / QSTEP)), int(round(2 * hy / QSTEP))
    mask = Image.new("1", (W, H), 0)                    # river polygons at 1 m
    md = ImageDraw.Draw(mask)

    def px(p):
        return [((x + hx) / QSTEP, (y + hy) / QSTEP) for x, y in p]
    for outer, holes in river_polys:
        md.polygon(px(outer), fill=1)
        for h_ in holes:
            md.polygon(px(h_), fill=0)
    M = np.asarray(mask, bool)

    def wet_poly(x, y):
        ix = np.clip(((np.asarray(x) + hx) / QSTEP).astype(np.int64), 0, W - 1)
        iy = np.clip(((np.asarray(y) + hy) / QSTEP).astype(np.int64), 0, H - 1)
        return M[iy, ix]

    wide = [(pts, w) for pts, w in river_lines if w >= 8 and len(pts) > 1]
    LS = [(a[0], a[1], b[0], b[1], w / 2) for pts, w in wide for a, b in zip(_subdiv(pts, 4.0), _subdiv(pts, 4.0)[1:])]
    LS = np.array(LS, np.float64).reshape(-1, 5)
    lgrid = _Grid(LS[:, :4]) if len(LS) else None

    def wet(x, y):
        x, y = np.asarray(x, np.float64), np.asarray(y, np.float64)
        w_ = wet_poly(x, y)
        if lgrid is not None:
            ids = lgrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), 12.0)
            if len(ids):
                xf, yf, S_ = x.ravel(), y.ravel(), LS[ids, :4]
                hit = np.zeros(len(xf), bool)
                step = max(1, 2_000_000 // len(ids))          # bound the (points x segments) matrix (was 2.7 GiB)
                for i in range(0, len(xf), step):
                    d, _ = _seg_dist(xf[i:i + step], yf[i:i + step], S_)
                    hit[i:i + step] = (d - LS[ids, 4][None] < 0).any(1)
                w_ = w_ | hit.reshape(x.shape)
        return w_

    # ---- bank chains: polygon rings (land on one side) and both sides of wide river lines
    chains = []                                         # each: dict(P (n,2), hw, closed)
    for outer, holes in river_polys:
        for ring in [outer] + list(holes):
            if len(ring) >= 3:
                chains.append({"P": np.array(_subdiv(list(ring) + [ring[0]], 4.0), np.float64), "hw": 0.0})
    for pts, w in wide:
        P = np.array(_subdiv(pts, 4.0), np.float64)
        if len(P) >= 2:
            chains.append({"P": P, "hw": w / 2})
    # bank elements: (ax, ay, bx, by, hw, chain, k); drop the ones with water on both sides (shared polygon edges,
    # river lines running inside a river polygon)
    E = []
    for ci, ch in enumerate(chains):
        P, hw = ch["P"], ch["hw"]
        A, B = P[:-1], P[1:]
        L = np.hypot(*(B - A).T)
        ok = L > 1e-6
        nx_, ny_ = -(B - A)[:, 1] / np.maximum(L, 1e-6), (B - A)[:, 0] / np.maximum(L, 1e-6)
        mx, my = (A[:, 0] + B[:, 0]) / 2, (A[:, 1] + B[:, 1]) / 2
        o = hw + 1.5
        both = np.zeros(len(mx), bool)
        for q0 in range(0, len(mx), 256):              # in pieces along the bank: small boxes, few segments each, and the bar moves
            tick(0.2 + 0.02 * (ci + q0 / max(1, len(mx))) / max(1, len(chains)), 'rivers')
            sl = slice(q0, q0 + 256)
            both[sl] = wet(mx[sl] + nx_[sl] * o, my[sl] + ny_[sl] * o) & wet(mx[sl] - nx_[sl] * o, my[sl] - ny_[sl] * o)
        for k in np.nonzero(ok & ~both)[0]:
            E.append((A[k, 0], A[k, 1], B[k, 0], B[k, 1], hw, ci, k))
    if not E:
        return None, {}
    E = np.array(E, np.float64)
    egrid = _Grid(E[:, :4])
    for ch in chains:                                   # promenade reach per chain vertex and side (+1 = left, -1 = right)
        ch["E"] = {1: np.zeros(len(ch["P"])), -1: np.zeros(len(ch["P"]))}

    def nearest_bank(x, y):
        """-> (d_out, element index, t, side) for (n,) points (d_out < 0 inside a river line)."""
        ids = egrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), REACH + 4)
        if not len(ids):
            n = len(x)
            return np.full(n, 1e9), np.zeros(n, np.int64), np.zeros(n), np.ones(n)
        S = E[ids]
        d, t = _seg_dist(x, y, S[:, :4])
        d = d - S[:, 4][None]
        j = np.argmin(d, 1)
        r = np.arange(len(x))
        tt = t[r, j]
        s = S[j]
        cr = (s[:, 2] - s[:, 0]) * (y - s[:, 1]) - (s[:, 3] - s[:, 1]) * (x - s[:, 0])
        return d[r, j], ids[j], tt, np.where(cr >= 0, 1.0, -1.0)

    # ---- water level along the centrelines
    def half_w(x, y):
        out_ = []
        for i in range(0, len(x), 64):
            if (i // 64) % 16 == 0:
                tick(0.22 + 0.03 * i / max(1, len(x)))
            out_.append(np.abs(nearest_bank(x[i:i + 64], y[i:i + 64])[0]))
        return np.concatenate(out_)
    lev = _levels([pts for pts, w in river_lines if len(pts) > 1], T, half_w)
    if lev:
        CS = np.concatenate([np.stack([p[:-1, 0], p[:-1, 1], p[1:, 0], p[1:, 1]], 1) for p, _ in lev])
        CV = np.concatenate([np.stack([l[:-1], l[1:]], 1) for _, l in lev])
        cgrid = _Grid(CS)
    else:
        cgrid = None

    def level(x, y):
        if cgrid is None:
            return T.h(x, y) - DROP
        r = 80.0
        while True:
            ids = cgrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), r)
            if len(ids) or r > 2000:
                break
            r *= 2
        if not len(ids):
            return T.h(x, y) - DROP
        d, t = _seg_dist(x, y, CS[ids])
        j = np.argmin(d, 1)
        rr = np.arange(len(x))
        v = CV[ids[j]]
        return v[:, 0] + (v[:, 1] - v[:, 0]) * t[rr, j]

    # ---- protected ground: streets with their pavements, pedestrian streets, buildings, bridge ends left on the quay
    BLD = np.asarray(bld_img, np.uint8) > 0
    bh, bw = BLD.shape
    prot = {}

    def build_prot(discs=()):
        PS = list(discs)
        for rd in roads:
            if rd.get("worn") or rd.get("tunnel") or rd.get("bridge") or rd["cls"] in FOOTISH or rd["cls"] == "steps":
                continue
            r_ = rd["w"] / 2 + (2.6 if rd.get("drive") else 0.6)
            for a_, b_ in zip(rd["pts"], rd["pts"][1:]):
                PS.append((a_[0], a_[1], b_[0], b_[1], r_))
        for b_ in buildings:
            ring = b_["ring"]
            for a_, c_ in zip(ring, list(ring[1:]) + [ring[0]]):
                PS.append((a_[0], a_[1], c_[0], c_[1], 0.3))
        prot["S"] = np.array(PS, np.float64).reshape(-1, 5)
        prot["g"] = _Grid(prot["S"][:, :4]) if len(PS) else None

    def prot_dist(x, y):
        """Distance to protected ground (0 on it), capped at 99."""
        PS, pgrid = prot["S"], prot["g"]
        dp = np.full(len(x), 99.0)
        if pgrid is not None:
            ids = pgrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), 14.0)
            if len(ids):
                d_, _ = _seg_dist(x, y, PS[ids, :4])
                dp = np.minimum(dp, np.maximum((d_ - PS[ids, 4][None]).min(1), 0.0))
        bx_ = np.clip(((x + hx) / cell).astype(np.int64), 0, bw - 1)
        by_ = np.clip(((y + hy) / cell).astype(np.int64), 0, bh - 1)
        return np.where(BLD[by_, bx_], 0.0, dp)

    # ---- lower promenade: paths running along the water, with room for the bank above them
    PB = [0.25, 0.1]                                    # progress range of the running promenade() pass

    def promenade():
        for ch in chains:
            ch["E"] = {1: np.zeros(len(ch["P"])), -1: np.zeros(len(ch["P"]))}
        nlow = 0
        for ri_, rd in enumerate(roads):
            if ri_ % 32 == 0:
                tick(PB[0] + PB[1] * ri_ / max(1, len(roads)))
            if rd["cls"] not in FOOTISH or rd.get("bridge") or rd.get("tunnel") or rd.get("worn"):
                continue
            P = np.array(_subdiv(rd["pts"], 2.0), np.float64)
            if len(P) < 2:
                continue
            x0, y0 = P.min(0)
            x1, y1 = P.max(0)
            if not len(egrid.near(x0, y0, x1, y1, LOW_D + 2)):
                continue
            d, j, t, side = _pieces(nearest_bank, P[:, 0], P[:, 1])
            gd = np.abs(np.gradient(d, 2.0)) if len(d) > 2 else np.zeros_like(d)
            use = (d >= -0.5) & (d <= LOW_D) & (gd < 0.45)
            hw_ = max(rd["w"], 2.0) / 2
            if use.any():                   # the bank between the path and protected ground (a street, its pavement,
                drop = np.maximum(T.h(P[:, 0], P[:, 1]) - _pieces(level, P[:, 0], P[:, 1]) - RISE, 0.0)      # a building) must fit
                use &= _pieces(prot_dist, P[:, 0], P[:, 1]) >= drop / KP + hw_ + MARGIN
            if not use.any():
                continue
            nlow += 1
            rch = np.maximum(d, 0.0) + hw_ + MARGIN
            for k in np.nonzero(use)[0]:
                ci, kk = int(E[j[k], 5]), int(E[j[k], 6])
                sd = int(side[k]) if chains[ci]["hw"] > 0 else 1
                arr = chains[ci]["E"][sd]
                for v in (kk, kk + 1):
                    arr[v] = max(arr[v], rch[k])
        for ch in chains:                               # taper along the chain, smooth the wobble of the paths away
            P = ch["P"]
            s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
            for sd in (1, -1):
                e = ch["E"][sd]
                if not e.any():
                    continue
                f = e.copy()
                for _ in range(2):
                    for i in range(1, len(f)):
                        f[i] = max(f[i], f[i - 1] - TAPER * (s[i] - s[i - 1]))
                    for i in range(len(f) - 2, -1, -1):
                        f[i] = max(f[i], f[i + 1] - TAPER * (s[i + 1] - s[i]))
                g = f.copy()
                for i in range(len(f)):                 # running max over +-6 m, then mean over +-8 m
                    g[i] = f[(s >= s[i] - 6) & (s <= s[i] + 6)].max()
                h_ = g.copy()
                for i in range(len(g)):
                    h_[i] = g[(s >= s[i] - 8) & (s <= s[i] + 8)].mean()
                ch["E"][sd] = np.where(h_ > R_W + 0.5, h_, 0.0)
        return nlow

    def reach(j, t, side):
        """Promenade reach (>= R_W) at the nearest bank point (element j, parameter t, side)."""
        ch_i, kk = E[j, 5].astype(np.int64), E[j, 6].astype(np.int64)
        e = np.zeros(len(j))
        for ci in np.unique(ch_i):
            m = ch_i == ci
            ch = chains[int(ci)]
            sd = side[m] if ch["hw"] > 0 else np.ones(m.sum())
            ea = np.where(sd > 0, ch["E"][1][kk[m]], ch["E"][-1][kk[m]])
            eb = np.where(sd > 0, ch["E"][1][kk[m] + 1], ch["E"][-1][kk[m] + 1])
            e[m] = ea + (eb - ea) * t[m]
        return np.maximum(e, R_W)

    # promenade -> bridges carried on over it -> streets / bridge ends that stay -> promenade again with them
    build_prot()
    tick(0.22, 'rivers')
    promenade()
    tick(0.36)
    nx_b, stuck = _extend_bridges(roads, nearest_bank, reach)
    tick(0.44)
    PB[:] = [0.44, 0.1]
    build_prot([(x_, y_, x_, y_, 4.0) for x_, y_ in stuck])
    nlow = promenade()
    tick(0.55)
    log(f"[quays] {len(chains)} bank lines, {len(E)} bank segments, {nlow} riverside paths on the lower promenade, "
        f"{nx_b} bridge ends carried on over it, {len(stuck)} bridge ends kept up on the bank")

    # ---- the base profile at any points (no walkway ramps yet): -> height, base, inside, d, reach, lower bound
    def profile(x, y):
        base = T.h(x, y).astype(np.float64)
        d, j, t, side = nearest_bank(x, y)
        inside = wet(x, y) | (d <= 0)
        d = np.where(inside, 0.0, np.maximum(d, 0.0))
        e = reach(j, t, side)
        hw_ = level(x, y)
        # rounded creases everywhere: a sharp crease sampled every metre shows as a saw-tooth along a diagonal bank
        u_ = np.clip(d / R_W, 0.0, 1.0)
        prof = hw_ + RISE * u_ * u_ * (3 - 2 * u_) + EMB * _softplus(d - e, 0.9)
        h = np.where(inside, hw_, _smin(base, prof, 0.35))
        lim = base - KP * prot_dist(x, y)                 # protected ground
        return h, base, inside, d, e, lim

    def by_tile(x, y, fn):
        """fn over the points, in TILE-sized groups (the segment lookups are per bounding box)."""
        key = np.floor((x + hx) / TILE).astype(np.int64) * 100003 + np.floor((y + hy) / TILE).astype(np.int64)
        out = np.zeros(len(x))
        for k in np.unique(key):
            m = key == k
            out[m] = fn(x[m], y[m])
        return out

    def cut0(x, y):
        h, base, inside, d, e, lim = profile(x, y)
        h = np.where(inside, h, -_smin(-h, -lim, 0.25))
        return np.maximum(0.0, (base - h) * np.clip((REACH - d) / 8.0, 0.0, 1.0))

    # ---- walkways: one network (ways joined at their shared nodes) that follows the quay profile but never
    # climbs faster along it than a ramp: cycleways RAMP_BIKE, footpaths a staircase's pitch RAMP_FOOT (the steps are
    # added in furnish).  Streets, bridge ends and the city above are cut 0, so every way leaving them climbs down
    # gently, wherever it joins.  Under a bridge near its end (the deck still at the ground there) a walkway is not
    # cut at all: it crosses the deck at grade instead of passing under it with no headroom (further out the deck is
    # lifted over it instead, in fix_decks).
    tick(0.6)
    bri = []
    for rd in roads:
        if rd.get("bridge") and len(rd["pts"]) >= 2:
            P = np.array(_subdiv(rd["pts"], 2.0), np.float64)
            s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
            near_end = np.minimum(s, s[-1] - s) < PIN_END
            for k in range(len(P) - 1):
                if near_end[k] or near_end[k + 1]:
                    bri.append((P[k, 0], P[k, 1], P[k + 1, 0], P[k + 1, 1], rd["w"] / 2 + 0.6))
    bri = np.array(bri, np.float64).reshape(-1, 5)
    bgrid = _Grid(bri[:, :4], 32.0) if len(bri) else None
    NX, NG, NW, NE = [], [], [], []                     # node xy, ramp grade of its way, half width; edges
    joint = {}
    for rd in roads:
        c = rd["cls"]
        if (c not in FOOTISH and c != "steps") or rd.get("bridge") or rd.get("tunnel") or len(rd["pts"]) < 2:
            continue
        P = np.array(_subdiv(rd["pts"], 1.0), np.float64)
        x0, y0 = P.min(0)
        x1, y1 = P.max(0)
        if not len(egrid.near(x0, y0, x1, y1, REACH)):
            continue
        G = RAMP_BIKE if c in ("cycleway", "track", "bridleway") else RAMP_FOOT
        i0 = sum(len(a_) for a_ in NX)
        NX.append(P)
        NG.append(np.full(len(P), G))
        NW.append(np.full(len(P), max(rd["w"], 2.0) / 2))
        seg = np.hypot(*np.diff(P, axis=0).T)
        NE += [(i0 + k, i0 + k + 1, G * seg[k]) for k in range(len(seg))]
        for q in rd["pts"]:
            k_ = (round(q[0], 2), round(q[1], 2))
            i_ = i0 + int(np.argmin(np.hypot(P[:, 0] - q[0], P[:, 1] - q[1])))
            if k_ in joint:
                NE.append((joint[k_], i_, 0.0))
            else:
                joint[k_] = i_
    WL = np.zeros((0, 5))
    if NX:
        NX = np.concatenate(NX)
        NW = np.concatenate(NW)
        NG = np.concatenate(NG)
        c0 = c_prof = by_tile(NX[:, 0], NX[:, 1], cut0)
        if bgrid is not None:
            def under(x, y):
                ids = bgrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), 12.0)
                if not len(ids):
                    return np.zeros(len(x))
                d_, _ = _seg_dist(x, y, bri[ids, :4])
                return ((d_ - bri[ids, 4][None]) < 0.5).any(1).astype(np.float64)
            pin = by_tile(NX[:, 0], NX[:, 1], under) > 0
            c0 = np.where(pin, 0.0, c0)
        adj = [[] for _ in range(len(NX))]
        for a_, b_, w_ in NE:
            adj[a_].append((b_, w_))
            adj[b_].append((a_, w_))
        hb = T.h(NX[:, 0], NX[:, 1]).astype(np.float64)
        hv = hb - c0                                    # upper envelope of the height: hv(v) >= hv(u) - grade * length
        heap = [(-float(v), i) for i, v in enumerate(hv)]
        heapq.heapify(heap)
        while heap:
            v, i = heapq.heappop(heap)
            v = -v
            if v < hv[i]:
                continue
            for k, w_ in adj[i]:
                if v - w_ > hv[k] + 1e-6:
                    hv[k] = v - w_
                    heapq.heappush(heap, (-hv[k], k))
        cc = np.maximum(hb - hv, 0.0)                   # (never above the ground: a natural slope stays as it is)
        m = cc < c_prof - 0.03
        WL = np.stack([NX[m, 0], NX[m, 1], cc[m], NW[m], NG[m]], 1)
        log(f"[quays] walkways: {len(NX)} samples, {int(m.sum())} lifted onto ramps / stairs, "
            f"{int(pin.sum()) if bgrid is not None else 0} at grade across bridge ends")
    wgrid = _Grid(np.stack([WL[:, 0], WL[:, 1], WL[:, 0], WL[:, 1]], 1), 32.0) if len(WL) else None

    def walk_lim(x, y, base):
        if wgrid is None:
            return np.full(len(x), -1e9)
        ids = wgrid.near(float(x.min()), float(y.min()), float(x.max()), float(y.max()), 6.0)
        if not len(ids):
            return np.full(len(x), -1e9)
        S = WL[ids]
        dd = np.hypot(x[:, None] - S[:, 0][None], y[:, None] - S[:, 1][None])
        # the walkway's own grade nearby (so its ramp stays exact between samples), then a wall down at its edges
        need = S[:, 2][None] + np.maximum(S[:, 4][None] * dd, KP * (dd - S[:, 3][None] - 0.4))
        return base - need.min(1)

    tick(0.68)
    # ---- tiles near the banks
    ntx, nty = int(math.ceil(W / TILE)), int(math.ceil(H / TILE))
    want = set()
    offs = np.linspace(-REACH, REACH, int(math.ceil(2 * REACH / (TILE * QSTEP * 0.5))) + 1)     # < half a tile apart
    for ax, ay, bx, by, *_ in E:
        for x_, y_ in ((ax, ay), (bx, by)):
            for dx in offs:
                for dy in offs:
                    tx_ = int(math.floor((x_ + dx + hx) / QSTEP / TILE))
                    ty_ = int(math.floor((y_ + dy + hy) / QSTEP / TILE))
                    if 0 <= tx_ < ntx and 0 <= ty_ < nty:
                        want.add((tx_, ty_))
    for outer, _h in river_polys:                       # the whole water surface too (it is lowered to the water level)
        xs, ys = [p[0] for p in outer], [p[1] for p in outer]
        for tx_ in range(max(0, int((min(xs) + hx) / QSTEP / TILE)), min(ntx - 1, int((max(xs) + hx) / QSTEP / TILE)) + 1):
            for ty_ in range(max(0, int((min(ys) + hy) / QSTEP / TILE)), min(nty - 1, int((max(ys) + hy) / QSTEP / TILE)) + 1):
                if M[ty_ * TILE: (ty_ + 1) * TILE, tx_ * TILE: (tx_ + 1) * TILE].any():
                    want.add((tx_, ty_))
    idx = np.full((nty, ntx), -1, np.int32)
    Ds, Cs = [], []
    k1 = np.arange(TILE + 1) * QSTEP

    def one_tile(t_):
        """-> (delta, cls) of one tile or None; reads shared state only."""
        tx_, ty_ = t_
        X, Y = np.meshgrid(tx_ * TILE * QSTEP - hx + k1, ty_ * TILE * QSTEP - hy + k1)
        x, y = X.ravel(), Y.ravel()
        h, base, inside, d, e, lim = profile(x, y)
        if (d > REACH).all() and not inside.any():
            return None
        wl = walk_lim(x, y, base)
        walled = (h < np.maximum(lim, wl) - 0.02) & ~inside
        # walls rounded off; the walkway ramps exact (a rounded max would put a hump at the foot of every ramp)
        h = np.where(inside, h, np.maximum(-_smin(-h, -lim, 0.25), wl))
        fade = np.clip((REACH - d) / 8.0, 0.0, 1.0)
        delta = np.minimum(0.0, (h - base) * fade)
        if not (delta < -0.01).any():
            return None
        cls = np.full(len(x), C_NONE, np.uint8)
        cut = delta < -0.05
        cls[cut & (d <= e) & (d >= R_W)] = C_PROM
        cls[cut & (d > e)] = C_GRASS
        cls[cut & (d < R_W)] = C_STONE
        cls[cut & walled] = C_WALL
        cls[inside] = C_WATER
        return delta.reshape(TILE + 1, TILE + 1).astype(np.float32), cls.reshape(TILE + 1, TILE + 1)

    if _worker:                                         # a pool worker: the set-up above is rebuilt here, the tiles come as jobs
        _W["tile"] = one_tile
        return None, {}
    tiles = sorted(want)

    def got(k_):
        if k_ % 8 == 0:
            tick(0.7 + 0.27 * k_ / max(1, len(tiles)))
    if pinit is not None and len(tiles) > 300:          # the tiles are independent: all cores
        res = par.pmap(_tile_job, tiles, init=pinit,
                       chunk=max(4, len(tiles) // (par.jobs() * 8)), on=lambda d, t: got(d))
    else:
        if pinit is not None:
            par.close()
        res = []
        for k_, t_ in enumerate(tiles):
            got(k_)
            res.append(one_tile(t_))
    for t_, r_ in zip(tiles, res):                      # in tile order: the same overlay however many cores ran it
        if r_ is not None:
            idx[t_[1], t_[0]] = len(Ds)
            Ds.append(r_[0])
            Cs.append(r_[1])
    if not Ds:
        return None, {}
    ov = Overlay(hx, hy, idx, np.stack(Ds), np.stack(Cs))
    log(f"[quays] overlay: {len(Ds)} tiles of {TILE} m ({len(Ds) * (TILE + 1) ** 2 * 5 / 1e6:.1f} MB)")
    return ov, {"chains": chains, "E": E}


# --------------------------------------------------------------------------------------------- 3D: steps and copings
STAIR_GRADE = 0.2               # a walkway steeper than this on the quays gets steps
STEP_RISE = 0.16
C_TREAD, C_RISER, C_COPING = (182, 178, 170), (148, 144, 138), (196, 190, 178)
STAIR_CLS = ("footway", "path", "steps", "pedestrian", "track", "bridleway")


def _cls_at(ov, x, y):
    """Class of the nearest overlay post (0 outside the tiles)."""
    fx = np.rint((np.asarray(x, np.float64) + ov.hx) / QSTEP).astype(np.int64)
    fy = np.rint((np.asarray(y, np.float64) + ov.hy) / QSTEP).astype(np.int64)
    tx, ty = fx // TILE, fy // TILE
    nty, ntx = ov.idx.shape
    ok = (tx >= 0) & (ty >= 0) & (tx < ntx) & (ty < nty)
    out = np.zeros(fx.shape, np.uint8)
    k = np.full(fx.shape, -1, np.int64)
    k[ok] = ov.idx[ty[ok], tx[ok]]
    m = k >= 0
    out[m] = ov.cls[k[m], fy[m] - ty[m] * TILE, fx[m] - tx[m] * TILE]
    return out


class _Mesh:
    def __init__(self, add, chunk_of, mat):
        self.add, self.chunk_of, self.mat = add, chunk_of, mat
        self.d = {}

    def quad(self, a, b, c, d, col):
        """a..d: (x, y_up, z), counter-clockwise seen from outside."""
        key = self.chunk_of((a[0] + c[0]) * 0.5, (a[2] + c[2]) * 0.5)
        p, cl = self.d.setdefault(key, ([], []))
        p.extend((a, b, c, a, c, d))
        cl.extend((col + (255,),) * 6)

    def box(self, P, top, bot, col_top, col_side):
        """P: 4 footprint corners (x, z) in order; a prism from bot to top (per-corner lists), faces wound outward."""
        if sum(P[i][0] * P[(i + 1) % 4][1] - P[(i + 1) % 4][0] * P[i][1] for i in range(4)) > 0:
            P, top, bot = P[::-1], top[::-1], bot[::-1]
        T_ = [(P[i][0], top[i], P[i][1]) for i in range(4)]
        B_ = [(P[i][0], bot[i], P[i][1]) for i in range(4)]
        self.quad(T_[0], T_[1], T_[2], T_[3], col_top)
        for i in range(4):
            j = (i + 1) % 4
            self.quad(T_[j], T_[i], B_[i], B_[j], col_side)

    def flush(self):
        n = 0
        for key, (p, c) in self.d.items():
            pos = np.array(p, np.float32).reshape(-1, 3)
            self.add(key, self.mat, pos, np.zeros((len(pos), 2), np.float32), np.array(c, np.uint8).reshape(-1, 4))
            n += len(pos)
        return n


def _shade(col, k):
    return tuple(int(min(255, c * k)) for c in col)


def furnish(T, edges, info, add, chunk_of, mat, log=print):
    """Steps where a walkway climbs a quay slope, and a stone coping along the top of the river revetments."""
    ov = getattr(T, "q", None)
    if ov is None:
        return 0
    M = _Mesh(add, chunk_of, mat)
    nst = 0
    for e in edges:
        if e["cls"] not in STAIR_CLS or e.get("bridge") or len(e["pts"]) < 2:
            continue
        P = np.array(_subdiv(e["pts"], 0.25), np.float64)
        if len(P) < 6 or (ov.at(P[:, 0], P[:, 1]) > -0.05).all():
            continue
        h = T.h(P[:, 0], P[:, 1]).astype(np.float64)
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])
        g = np.abs(np.gradient(h, s, edge_order=1)) if s[-1] > 0 else np.zeros_like(h)
        k = max(1, int(round(0.5 / 0.25)))
        gs = np.convolve(g, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
        steep = (gs > STAIR_GRADE) & (ov.at(P[:, 0], P[:, 1]) < -0.05)
        i = 0
        hw = max(0.8, min(1.6, e.get("w", 2.0) / 2))
        while i < len(P):
            if not steep[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(P) and (steep[j + 1] or (j + 4 < len(P) and steep[j + 1:j + 5].any())):
                j += 1
            a, b = i, j
            i = j + 1
            rise = abs(h[b] - h[a])
            if s[b] - s[a] < 1.0 or rise < 0.4:
                continue
            n = max(2, int(round(rise / STEP_RISE)))
            up = h[b] > h[a]
            for q in range(n):
                sa = s[a] + (s[b] - s[a]) * q / n
                sb = s[a] + (s[b] - s[a]) * (q + 1) / n
                ia = int(np.searchsorted(s, sa))
                ib = min(len(P) - 1, int(np.searchsorted(s, sb)))
                ia = min(ia, ib)
                pa, pb = P[ia], P[ib]
                dx, dy = pb - pa
                L = math.hypot(dx, dy)
                if L < 1e-6:
                    continue
                nx_, ny_ = -dy / L * hw, dx / L * hw
                top = h[a] + (h[b] - h[a]) * ((q + 1) / n if up else q / n) + 0.04
                corners = [(pa[0] + nx_, pa[1] + ny_), (pb[0] + nx_, pb[1] + ny_), (pb[0] - nx_, pb[1] - ny_), (pa[0] - nx_, pa[1] - ny_)]
                gnd = [float(T.hs(cx, cz)) for cx, cz in corners]
                bot = [v - 0.25 for v in gnd]
                tt = max(top, max(gnd) + 0.04)
                M.box(corners, [tt] * 4, bot, _shade(C_TREAD, 1.0), _shade(C_RISER, 0.85))
            nst += 1
    # copings along the revetment tops
    ncp = 0
    for ch in info.get("chains", ()):
        P = np.array(_subdiv([tuple(p) for p in ch["P"]], 2.0), np.float64)
        if len(P) < 2:
            continue
        tg = np.gradient(P, axis=0)
        tg /= np.maximum(np.hypot(tg[:, 0], tg[:, 1]), 1e-9)[:, None]
        nrm = np.stack([-tg[:, 1], tg[:, 0]], 1)
        for sd in ((1.0, -1.0) if ch["hw"] > 0 else (1.0, -1.0)):
            base = P + nrm * sd * ch["hw"]
            land = _cls_at(ov, *(base + nrm * sd * (R_W + 1.0)).T)
            sea = _cls_at(ov, *(base - nrm * sd * 1.0).T)
            Q = base + nrm * sd * (R_W - 0.25)
            inner, outer = Q - nrm * sd * 0.2, Q + nrm * sd * 0.35
            cut = ov.at(Q[:, 0], Q[:, 1])
            ok = (sea == C_WATER) & np.isin(land, (C_PROM, C_GRASS, C_STONE)) & (cut < -0.3)
            hin = T.h(inner[:, 0], inner[:, 1]).astype(np.float64)
            hout = T.h(outer[:, 0], outer[:, 1]).astype(np.float64)
            for k in range(len(P) - 1):
                if not (ok[k] and ok[k + 1]):
                    continue
                if np.hypot(*(Q[k + 1] - Q[k])) > 3.5:
                    continue
                top = [hout[k] + 0.14, hout[k + 1] + 0.14, hout[k + 1] + 0.14, hout[k] + 0.14]
                corners = [tuple(outer[k]), tuple(outer[k + 1]), tuple(inner[k + 1]), tuple(inner[k])]
                bot = [hout[k] - 0.1, hout[k + 1] - 0.1, hin[k + 1] - 0.2, hin[k] - 0.2]
                M.box(corners, top, bot, _shade(C_COPING, 1.0), _shade(C_COPING, 0.8))
                ncp += 1
    nv = M.flush()
    log(f"[quays] {nst} flights of steps, {ncp * 2 / 1000:.1f} km of coping, {nv / 1e6:.2f} M vertices")
    return nv


def fix_decks(decks, T, ways=None):
    """A deck end that is a joint with the next piece of the same bridge may stand over the quay cut (every other end
    is carried on or kept on protected ground): lift it to the uncut ground, the lift easing off linearly to the other
    end, so neither piece dips into the cut (a ring of a bridge, both ends one joint, rises as a whole).
    -> number of ends lifted; with `ways` (that, decks lifted over the walkways below, crossings too close to an end
    for it)."""
    ov = getattr(T, "q", None)
    if ov is None:
        return 0 if ways is None else (0, 0, 0)
    n = 0
    for d in decks.values():
        hs = np.array(d.h, np.float64)
        cum = np.array(d.cum, np.float64)
        L = max(cum[-1], 1e-6)
        g0, g1 = (max(-ov.at_s(*d.pts[e_]), 0.0) for e_ in (0, -1))
        g0, g1 = (g_ if g_ >= 0.05 else 0.0 for g_ in (g0, g1))
        if not (g0 or g1):
            continue
        hs += g0 * (1.0 - cum / L) + g1 * (cum / L)                     # the whole piece rises with its joints
        n += (g0 > 0) + (g1 > 0)
        d.h = [float(v) for v in hs]
    if ways is None:
        return n
    # walkways passing under a deck over the quays with too little headroom (near its end, where the deck still keeps
    # to the ground; the cut below made the mid-span lifts over the promenade unneeded): lift the deck over them,
    # rising from both ends, if that stays a walkable grade
    W = []
    for rd in ways:
        if rd.get("bridge") or rd.get("tunnel") or not (rd["cls"] in FOOTISH or rd["cls"] in ("steps", "pedestrian")):
            continue
        W += [(a_[0], a_[1], b_[0], b_[1]) for a_, b_ in zip(rd["pts"], rd["pts"][1:])]
    if not W:
        return n, 0, 0
    W = np.array(W, np.float64)
    wg = _Grid(W, 32.0)
    nl = nskip = 0
    for d in decks.values():
        P = np.array(d.pts, np.float64)
        hs = np.array(d.h, np.float64)
        cum = np.array(d.cum, np.float64)
        L = cum[-1]
        if (ov.at(P[:, 0], P[:, 1]) > -0.05).all():                  # only the bridges over the quays
            continue
        ids = wg.near(float(P[:, 0].min()), float(P[:, 1].min()), float(P[:, 0].max()), float(P[:, 1].max()), 1.0)
        lift = np.zeros(len(P))
        for k in range(len(P) - 1):
            (ax, ay), (bx, by) = P[k], P[k + 1]
            for cx, cy, ex, ey in W[ids]:
                d1x, d1y, d2x, d2y = bx - ax, by - ay, ex - cx, ey - cy
                den = d1x * d2y - d1y * d2x
                if abs(den) < 1e-9:
                    continue
                t = ((cx - ax) * d2y - (cy - ay) * d2x) / den
                u = ((cx - ax) * d1y - (cy - ay) * d1x) / den
                if not (0 <= t <= 1 and 0 <= u <= 1):
                    continue
                x, y = ax + d1x * t, ay + d1y * t
                sc = cum[k] + (cum[k + 1] - cum[k]) * t
                gap = (hs[k] + (hs[k + 1] - hs[k]) * t) - float(T.hs(x, y))
                if gap < 0.45 or gap >= CLEAR_Q:                    # at grade (a crossing), or clear
                    continue
                need = CLEAR_Q - gap
                if need / max(min(sc, L - sc) - 1.5, 0.5) > MAX_LIFT:
                    nskip += 1
                    continue
                a0, b0 = max(sc - 1.5, 0.5), max(L - sc - 1.5, 0.5)       # flat over the walkway, ramps to the ends
                lift = np.maximum(lift, need * np.clip(np.minimum(cum / a0, (L - cum) / b0), 0.0, 1.0))
        hs = hs + lift
        # the clearance lifts can leave a deck dipping between them, towards the lowered water, then climbing steeply:
        # fill the dips so no slope is steeper than DECK_G (the ends stay where they meet the ground)
        f = hs.copy()
        for _ in range(2):
            for i in range(1, len(f) - 1):
                f[i] = max(f[i], f[i - 1] - DECK_G * (cum[i] - cum[i - 1]))
            for i in range(len(f) - 2, 0, -1):
                f[i] = max(f[i], f[i + 1] - DECK_G * (cum[i + 1] - cum[i]))
        if lift.any() or (f > hs + 0.01).any():
            d.h = [float(v) for v in f]
            nl += 1
    return n, nl, nskip
