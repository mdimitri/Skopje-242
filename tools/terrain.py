"""Terrain: elevation grid (10 m posts), water carving and bridge deck profiles.

Heights are metres relative to the city centre (so the numbers stay small).  The grid covers the whole world box.
The same bilinear sampler is used by the build step (to lift roads, buildings, trees ...) and at run time (ground mesh,
physics), so everything agrees to the millimetre.
"""
import math
import os

import numpy as np

STEP = 10.0
CLEAR_ROAD, CLEAR_FOOT = 4.4, 3.0           # headroom under a bridge deck over a road / over a footpath
SLAB = 0.9                                   # deck thickness (girder depth)
END_KEEP = 24.0                              # no clearance constraints this close to a bridge end


def grid_shape(hx, hy):
    return int(round(2 * hy / STEP)) + 1, int(round(2 * hx / STEP)) + 1


class Terrain:
    def __init__(self, grid, hx, hy):
        self.g = np.asarray(grid, np.float32)
        self.hx, self.hy = hx, hy
        self.ny, self.nx = self.g.shape

    def h(self, x, y):
        """Bilinear height at world (x, y); accepts scalars or numpy arrays."""
        fx = np.clip((np.asarray(x, np.float64) + self.hx) / STEP, 0, self.nx - 1.001)
        fy = np.clip((np.asarray(y, np.float64) + self.hy) / STEP, 0, self.ny - 1.001)
        ix, iy = fx.astype(np.int64), fy.astype(np.int64)
        tx, ty = fx - ix, fy - iy
        g = self.g
        a = g[iy, ix] * (1 - tx) + g[iy, ix + 1] * tx
        b = g[iy + 1, ix] * (1 - tx) + g[iy + 1, ix + 1] * tx
        return (a * (1 - ty) + b * ty).astype(np.float32)

    def hs(self, x, y):
        return float(self.h(x, y))


def flat(hx, hy):
    return Terrain(np.zeros(grid_shape(hx, hy), np.float32), hx, hy)


def synthetic(hx, hy):
    """Hills + a river valley for the demo city (no network): max slope about 9 %."""
    ny, nx = grid_shape(hx, hy)
    xs = np.linspace(-hx, hx, nx)[None, :]
    ys = np.linspace(-hy, hy, ny)[:, None]
    g = 0.012 * ys * -1.0                                                  # north is higher
    for cx, cy, r, a in ((-1500, -1300, 650, 46), (350, -250, 170, 24), (2300, -900, 800, 38), (-3600, 900, 900, 55),
                         (3800, 1500, 700, 30), (900, 1800, 500, 22)):
        g = g + a * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * r * r)))
    g = g + 2.0 * np.sin(xs / 420.0) * np.cos(ys / 360.0)
    g = g - float(g[ny // 2, nx // 2])
    return Terrain(g, hx, hy)


def carve_water(T, water_mask, cell, depth=1.8):
    """Sink the river bed `depth` below the surrounding banks.  water_mask: bool array at `cell` metres per pixel."""
    ny, nx = T.g.shape
    wy, wx = np.nonzero(water_mask[::5, ::5])                       # coarse sample of water pixels
    if len(wx) == 0:
        return T
    px = (wx * 5 * cell + 2.5 * cell) - T.hx
    py = (wy * 5 * cell + 2.5 * cell) - T.hy
    ix = np.clip(((px + T.hx) / STEP).round().astype(int), 0, nx - 1)
    iy = np.clip(((py + T.hy) / STEP).round().astype(int), 0, ny - 1)
    wet = np.zeros_like(T.g, bool)
    wet[iy, ix] = True
    # fill small holes of the coarse sampling
    for _ in range(1):
        wet = wet | np.roll(wet, 1, 0) & np.roll(wet, -1, 0) | np.roll(wet, 1, 1) & np.roll(wet, -1, 1)
    bank = T.g.copy()
    for _ in range(4):                                                # banks = highest of the neighbourhood
        bank = np.maximum.reduce([bank, np.roll(bank, 1, 0), np.roll(bank, -1, 0), np.roll(bank, 1, 1), np.roll(bank, -1, 1)])
    dist = np.where(wet, 0.0, 99.0)
    for it in range(1, 5):                                            # soft shoulders: 1..4 posts from the water
        nb = np.minimum.reduce([dist, np.roll(dist, 1, 0) + 1, np.roll(dist, -1, 0) + 1, np.roll(dist, 1, 1) + 1,
                                np.roll(dist, -1, 1) + 1])
        dist = nb
    g = np.where(wet, bank - depth, T.g)
    sh = (dist > 0) & (dist <= 4)
    f = 1.0 - dist / 5.0
    g = np.where(sh, np.minimum(T.g, bank - depth * f), g)
    return Terrain(g, T.hx, T.hy)


def save(T, path):
    np.save(path, T.g)


def load(path, hx, hy):
    g = np.load(path)
    if g.shape != grid_shape(hx, hy):
        raise ValueError(f"terrain grid {g.shape} does not match the world box {grid_shape(hx, hy)}")
    return Terrain(g, hx, hy)


# ----------------------------------------------------------------------------------------- bridge decks
def _pchip(xs, ys, x):
    """Monotone cubic Hermite interpolation (Fritsch-Carlson); no overshoot between the knots."""
    n = len(xs)
    if n == 1:
        return np.full_like(x, ys[0], dtype=float)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros(n)
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, n - 1):
        m[i] = 0.0 if d[i - 1] * d[i] <= 0 else 2 * d[i - 1] * d[i] / (d[i - 1] + d[i])
    i = np.clip(np.searchsorted(xs, x) - 1, 0, n - 2)
    t = (x - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i]
            + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1])


class Deck:
    """Height profile of a bridge: dense samples every ~3 m along the edge polyline."""

    def __init__(self, pts, hs, hw):
        self.pts = [(float(x), float(y)) for x, y in pts]
        self.h = [float(v) for v in hs]
        self.hw = float(hw)                      # half width of the walkable / drivable deck incl. parapet
        cum = [0.0]
        for k in range(1, len(self.pts)):
            cum.append(cum[-1] + math.hypot(self.pts[k][0] - self.pts[k - 1][0], self.pts[k][1] - self.pts[k - 1][1]))
        self.cum = cum
        self.len = cum[-1]

    def at(self, x, y):
        """-> (height, s, lateral distance) of the nearest point on the deck centreline."""
        best = (1e18, 0.0, 0.0)
        pts, cum, hs = self.pts, self.cum, self.h
        for k in range(len(pts) - 1):
            ax, ay = pts[k]
            bx, by = pts[k + 1]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            d = math.hypot(x - ax - dx * t, y - ay - dy * t)
            if d < best[0]:
                best = (d, cum[k] + (cum[k + 1] - cum[k]) * t, hs[k] + (hs[k + 1] - hs[k]) * t)
        return best[2], best[1], best[0]

    def pack(self):
        return {"pts": self.pts, "cum": self.cum, "h": self.h, "hw": self.hw, "len": self.len}


def resample(pts, step=3.0):
    """Polyline -> (points every <= step metres, cumulative distance)."""
    out, cum = [pts[0]], [0.0]
    s = 0.0
    for k in range(1, len(pts)):
        ax, ay = pts[k - 1]
        bx, by = pts[k]
        L = math.hypot(bx - ax, by - ay)
        n = max(1, int(math.ceil(L / step)))
        for i in range(1, n + 1):
            t = i / n
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
            cum.append(s + L * t)
        s += L
    return out, cum


def make_deck(T, edge, lower, hw):
    """Deck profile for a bridge edge.

    Ends meet the terrain.  Where the deck crosses another road / footpath (`lower(x, y)` -> clearance wanted there or 0),
    it is lifted to clear it, with a smooth monotone profile in between."""
    pts, cum = resample(edge["pts"], 3.0)
    L = cum[-1]
    t_end0, t_end1 = T.hs(*pts[0]), T.hs(*pts[-1])
    knots = [(0.0, t_end0), (L, t_end1)]
    inter = (t_end1 - t_end0)
    if L > 2 * END_KEEP + 4:
        run = None
        for (x, y), s in zip(pts, cum):
            c = lower(x, y) if END_KEEP <= s <= L - END_KEEP else 0.0
            if c > 0:
                if run is None:
                    run = [s, s, c, T.hs(x, y)]
                else:
                    run[1] = s
                    run[2] = max(run[2], c)
                    run[3] = max(run[3], T.hs(x, y))
            elif run is not None:
                knots += [(run[0] - 3.0, None), (run[1] + 3.0, None)]
                knots.append((run[0], run[3] + run[2]))
                knots.append((run[1], run[3] + run[2]))
                run = None
        if run is not None:
            knots.append((run[0], run[3] + run[2]))
            knots.append((run[1], run[3] + run[2]))
    knots = [(s, v) for s, v in knots if v is not None]
    knots.sort()
    xs, ys = [], []
    for s, v in knots:                                                  # merge duplicate stations
        if xs and s - xs[-1] < 1.0:
            ys[-1] = max(ys[-1], v)
        else:
            xs.append(s)
            ys.append(v)
    # make the deck monotone-smooth but never lower than the straight chord between the ends
    s_arr = np.array(cum)
    prof = _pchip(np.array(xs), np.array(ys), s_arr)
    chord = t_end0 + (s_arr / max(L, 1e-6)) * inter
    prof = np.maximum(prof, chord)
    ground = T.h(np.array([p[0] for p in pts]), np.array([p[1] for p in pts]))
    keep = (s_arr >= 6) & (s_arr <= L - 6)
    prof = np.where(keep, np.maximum(prof, ground + 0.35), prof)
    return Deck(pts, prof, hw)
