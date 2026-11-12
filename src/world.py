"""Runtime world: loads the baked pickle, builds collision grid + routing graph."""
import array
import bisect
import json
import math
import os
import pickle
import zlib

import numpy as np


class WorldError(Exception):
    pass


PARTS = ["meta", "areas", "roads", "edges", "buildings", "props", "chunks", "surf", "terrain"]


def validate(path):
    """Cheap integrity check of a world directory: manifest + file sizes."""
    try:
        man = json.load(open(os.path.join(path, "manifest.json")))
        for fn, size in man["sizes"].items():
            if os.path.getsize(os.path.join(path, fn)) != size:
                return f"{fn} has the wrong size (corrupt or incomplete)"
        return None
    except Exception as e:  # noqa: BLE001
        return f"manifest unreadable: {e}"


def _read_with_progress(fn, progress, label, base, span):
    size = os.path.getsize(fn)
    buf = bytearray()
    with open(fn, "rb") as f:
        while True:
            b = f.read(4 * 1024 * 1024)
            if not b:
                break
            buf += b
            progress(base + span * 0.6 * len(buf) / max(size, 1), f"{label}: reading {len(buf) / 1e6:.0f}/{size / 1e6:.0f} MB")
    progress(base + span * 0.6, f"{label}: unpacking")
    return pickle.loads(buf)                           # (bytes(buf) copied the whole file once more)


class World:
    def __init__(self, path, progress=None, on_part=None):
        P = progress or (lambda f, note="": None)
        err = validate(path)
        if err:
            raise WorldError(err)
        self.path = path
        n = len(PARTS)
        try:
            for i, name in enumerate(PARTS):
                d = _read_with_progress(os.path.join(path, name + ".pkl"), P, name, i / n * 0.6, 0.6 / n)
                self.__dict__.update(d)
                if on_part:
                    on_part(name, d)
                P((i + 1) / n * 0.6, f"{name}: ok")
            self.stamp = os.path.getmtime(os.path.join(path, "manifest.json"))
            self.surf = zlib.decompress(self.surf)
            self.hgt = zlib.decompress(self.hgt) if getattr(self, "hgt", None) else None
            self.mesh_file = np.memmap(os.path.join(path, "meshes.bin"), dtype=np.uint8, mode="r")
        except WorldError:
            raise
        except Exception as e:  # noqa: BLE001
            raise WorldError(f"cannot load world data: {e}") from e
        self.hx = getattr(self, 'hx', self.half)
        self.hy = getattr(self, 'hy', self.half)
        self.ncx = int(2 * self.hx / self.cell)
        self.ncy = int(2 * self.hy / self.cell)
        self._load_terrain()
        self._build_collision(lambda f, note="": P(0.6 + 0.2 * f, note))
        self._build_graph(lambda f, note="": P(0.8 + 0.2 * f, note))

    # ---- GPU mesh blob -------------------------------------------------------------
    def mesh_arrays(self, off, n):
        mm = self.mesh_file
        pos = np.frombuffer(mm[off: off + n * 12], dtype=np.float32).reshape(n, 3)
        uv = np.frombuffer(mm[off + n * 12: off + n * 20], dtype=np.float32).reshape(n, 2)
        col = np.frombuffer(mm[off + n * 20: off + n * 24], dtype=np.uint8).reshape(n, 4)
        return pos, uv, col

    # ---- surface mask: 0 ground, 1 water, 2 bridge, 3 road
    def surface(self, x, y):
        ix = int((x + self.hx) / self.cell)
        iy = int((y + self.hy) / self.cell)
        if 0 <= ix < self.ncx and 0 <= iy < self.ncy:
            return self.surf[iy * self.ncx + ix]
        return 0

    # ---- static collision: building footprints (edges) + trees/lamps (circles) in hashed grids
    def _build_collision(self, P):
        self.cg = 16.0
        g = {}
        cg = self.cg
        nb = len(self.buildings)
        for bi, b in enumerate(self.buildings):
            ring = b["ring"]
            m = len(ring)
            for i in range(m):
                (ax, ay), (bx, by) = ring[i], ring[(i + 1) % m]
                x0, x1 = sorted((ax, bx))
                y0, y1 = sorted((ay, by))
                for cx in range(int(x0 // cg), int(x1 // cg) + 1):
                    for cy in range(int(y0 // cg), int(y1 // cg) + 1):
                        g.setdefault((cx, cy), []).append((ax, ay, bx, by))
            if bi % 300 == 0:
                P(0.8 * bi / max(nb, 1), f"building collision {bi}/{nb}")
        self.cgrid = g
        pg = {}
        th = self.th
        P(0.8, "trees")
        ta = np.array(self.trees, np.float64).reshape(-1, 4)
        tt = self.th_v(ta[:, 0], ta[:, 1]).tolist()                       # all heights at once: th() per tree was most of this function's time
        for (x, y, r, _s), t, cx, cy in zip(self.trees, tt, (ta[:, 0] // cg).astype(np.int64).tolist(), (ta[:, 1] // cg).astype(np.int64).tolist()):
            pg.setdefault((cx, cy), []).append((x, y, 0.5 if r < 3.5 else 0.65, t - 1.0, t + 9.0))
        for x, y in self.lamps:
            t = th(x, y)
            pg.setdefault((int(x // cg), int(y // cg)), []).append((x, y, 0.22, t - 1.0, t + 6.5))
        self.hide_extra, self.broken_extra = {}, []
        for p in getattr(self, "posts", ()):
            x, y, r = p[0], p[1], p[2]
            if len(p) >= 6 and p[5]:
                self.hide_extra[(p[0], p[1])] = tuple(p[5])         # (radius, from, to): signal arm / billboard panel that falls with its pole
            lo, hi = (p[3], p[4]) if len(p) >= 5 else (th(x, y) - 1.0, th(x, y) + 2.4)
            pg.setdefault((int(x // cg), int(y // cg)), []).append((x, y, r, lo, hi))
        self.pgrid = pg
        self.trees = ta                                                  # (x, y, radius, kind): half a million Python tuples become one 15 MB block
        self.broken, self.broken_ver = [], 0
        P(1.0, "collision ready")

    GROUND_Y = (0.0, 0.07, 0.16, 0.0)
    G = 9.81

    # ---- terrain: 10 m heightfield (bilinear), bridge decks, water
    def _load_terrain(self):
        t = getattr(self, "terrain", None)
        self.tstep = 10.0
        if t:
            self.tnx, self.tny, self.tstep = t["nx"], t["ny"], t["step"]
            self.tgrid = np.frombuffer(t["grid"], dtype=np.float32).reshape(self.tny, self.tnx)
            self.tl = self.tgrid.ravel().tolist()
            self.hilly = bool(t.get("real", False)) or float(np.ptp(self.tgrid)) > 1.0
        else:
            self.tnx, self.tny = 2, 2
            self.tgrid = np.zeros((2, 2), np.float32)
            self.tl = [0.0] * 4
            self.hilly = False
        self._load_quays(t)
        # bridge decks: 8 m hash of centreline segments (x1, y1, x2, y2, h1, h2, half width)
        self.dgrid = {}
        top = self._deck_tops()
        for di, d in enumerate(getattr(self, "decks", ())):
            pts, hs, hw = d["pts"], d["h"], d["hw"]
            for k in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[k], pts[k + 1]
                seg = (ax, ay, bx, by, hs[k] + top[di], hs[k + 1] + top[di], hw)
                m = hw + 5.6
                for cx in range(int((min(ax, bx) - m) // 8), int((max(ax, bx) + m) // 8) + 1):
                    for cy in range(int((min(ay, by) - m) // 8), int((max(ay, by) + m) // 8) + 1):
                        self.dgrid.setdefault((cx, cy), []).append(seg)

        # fire escapes / roofs / jump ramps: 8 m hash of walkable surfaces for foot and bike riders (see tools/escapes.py)
        self.pg2 = {}
        for pl in getattr(self, "plats", ()):
            if pl[0] == 0:
                r = math.hypot(pl[5], pl[6])
                x0, x1, y0, y1 = pl[1] - r, pl[1] + r, pl[2] - r, pl[2] + r
            else:
                xs, ys = [q[0] for q in pl[1]], [q[1] for q in pl[1]]
                x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
                pl = (1, pl[1], pl[2], (x0, y0, x1, y1))
            for cx in range(int(x0 // 8), int(x1 // 8) + 1):
                for cy in range(int(y0 // 8), int(y1 // 8) + 1):
                    self.pg2.setdefault((cx, cy), []).append(pl)

    def plat_h(self, x, y, wy):
        """Highest escape stair / landing / ramp / roof surface at (x, y) that something with its feet at wy can step onto, or None."""
        best = None
        lim = wy + 0.7
        for p in self.pg2.get((int(x // 8), int(y // 8)), ()):
            if p[0] == 0:
                dx, dy = x - p[1], y - p[2]
                s = dx * p[3] + dy * p[4]
                if abs(s) > p[5] or abs(-dx * p[4] + dy * p[3]) > p[6]:
                    continue
                h = p[7] + (p[8] - p[7]) * (s + p[5]) / (2 * p[5])
            else:
                if p[2] > lim or (best is not None and p[2] <= best):
                    continue
                b = p[3]
                if x < b[0] or x > b[2] or y < b[1] or y > b[3] or not self._in_ring(x, y, p[1]):
                    continue
                h = p[2]
            if h <= lim and (best is None or h > best):
                best = h
        return best

    def plat_wall(self, x, y, wy):
        """A roof taller than the rider's feet is here: its wall blocks (an elevated rider must not walk into a building)."""
        lim = wy + 0.7
        for p in self.pg2.get((int(x // 8), int(y // 8)), ()):
            if p[0] == 1 and p[2] > lim:
                b = p[3]
                if b[0] <= x <= b[2] and b[1] <= y <= b[3] and self._in_ring(x, y, p[1]):
                    return True
        return False

    @staticmethod
    def _in_ring(x, y, ring):
        inside = False
        xj, yj = ring[-1]
        for xi, yi in ring:
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            xj, yj = xi, yi
        return inside

    def _load_quays(self, t):
        # river quays (tools/quays.py): sparse 1 m tiles of height cuts on top of the 10 m grid, plus a class per post
        q = t.get("quay") if t else None
        self.qidx = None
        self.tgrid_low = self.tgrid                     # the 10 m grid lowered under the quay cuts (far LOD model)
        if q:
            self.qstep, self.qtile = float(q["step"]), int(q["tile"])
            self.qnty, self.qntx = int(q["nty"]), int(q["ntx"])
            m = self.qtile + 1
            self.qidx_a = np.frombuffer(q["idx"], np.int32).reshape(self.qnty, self.qntx)
            self.qd = np.frombuffer(q["d"], np.float32).reshape(-1, m, m)
            self.qcls = np.frombuffer(q["cls"], np.uint8).reshape(-1, m, m)
            self.qidx = self.qidx_a.ravel().tolist()
            self.ql = array.array("f", self.qd.tobytes())      # compact; indexing gives plain floats
            self.hilly = True
            low = self.tgrid.copy()
            span = self.qtile * self.qstep
            for ty, tx in zip(*np.nonzero(self.qidx_a >= 0)):
                dmin = float(self.qd[self.qidx_a[ty, tx]].min())
                j0 = max(0, int((tx * span) // self.tstep) - 1)
                j1 = min(self.tnx - 1, int(((tx + 1) * span) // self.tstep) + 2)
                i0 = max(0, int((ty * span) // self.tstep) - 1)
                i1 = min(self.tny - 1, int(((ty + 1) * span) // self.tstep) + 2)
                low[i0:i1 + 1, j0:j1 + 1] = np.minimum(low[i0:i1 + 1, j0:j1 + 1], self.tgrid[i0:i1 + 1, j0:j1 + 1] + dmin)
            self.tgrid_low = low

    def quay_cut(self, x, y):
        """Height cut of the river quays at (x, y) (<= 0; 0 away from the rivers)."""
        q = self.qidx
        if q is None:
            return 0.0
        fx = (x + self.hx) / self.qstep
        fy = (y + self.hy) / self.qstep
        if fx < 0.0 or fy < 0.0:
            return 0.0
        T = self.qtile
        tx, ty = int(fx) // T, int(fy) // T
        if tx >= self.qntx or ty >= self.qnty:
            return 0.0
        k = q[ty * self.qntx + tx]
        if k < 0:
            return 0.0
        lx, ly = fx - tx * T, fy - ty * T
        ix, iy = int(lx), int(ly)
        if ix >= T:
            ix = T - 1
        if iy >= T:
            iy = T - 1
        u, v = lx - ix, ly - iy
        m = T + 1
        i = (k * m + iy) * m + ix
        g = self.ql
        a = g[i] + (g[i + 1] - g[i]) * u
        b = g[i + m] + (g[i + m + 1] - g[i + m]) * u
        return a + (b - a) * v

    def quay_cut_v(self, x, y):
        """Vectorised quay_cut for numpy arrays."""
        x = np.asarray(x, np.float64)
        y = np.asarray(y, np.float64)
        out = np.zeros(np.broadcast(x, y).shape, np.float64)
        if self.qidx is None:
            return out
        T = self.qtile
        fx = (x + self.hx) / self.qstep
        fy = (y + self.hy) / self.qstep
        tx = np.floor(fx / T).astype(np.int64)
        ty = np.floor(fy / T).astype(np.int64)
        ok = (tx >= 0) & (ty >= 0) & (tx < self.qntx) & (ty < self.qnty)
        ti = np.full(out.shape, -1, np.int64)
        ti[ok] = self.qidx_a[ty[ok], tx[ok]]
        m = ti >= 0
        if not m.any():
            return out
        lx = fx[m] - tx[m] * T
        ly = fy[m] - ty[m] * T
        ix = np.minimum(lx.astype(np.int64), T - 1)
        iy = np.minimum(ly.astype(np.int64), T - 1)
        u, v = lx - ix, ly - iy
        D, k = self.qd, ti[m]
        a = D[k, iy, ix] * (1 - u) + D[k, iy, ix + 1] * u
        b = D[k, iy + 1, ix] * (1 - u) + D[k, iy + 1, ix + 1] * u
        out[m] = a * (1 - v) + b * v
        return out

    def th(self, x, y):
        """Terrain height (bilinear on the 10 m grid); metres above the city-centre elevation."""
        st = self.tstep
        fx = (x + self.hx) / st
        fy = (y + self.hy) / st
        nx, ny = self.tnx, self.tny
        if fx < 0.0:
            fx = 0.0
        elif fx > nx - 1.001:
            fx = nx - 1.001
        if fy < 0.0:
            fy = 0.0
        elif fy > ny - 1.001:
            fy = ny - 1.001
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        g = self.tl
        i = iy * nx + ix
        a = g[i] + (g[i + 1] - g[i]) * tx
        b = g[i + nx] + (g[i + nx + 1] - g[i + nx]) * tx
        if self.qidx is not None:
            return a + (b - a) * ty + self.quay_cut(x, y)
        return a + (b - a) * ty

    def th_v(self, x, y):
        """Vectorised terrain height for numpy arrays (mesh building)."""
        st = self.tstep
        fx = np.clip((np.asarray(x, np.float64) + self.hx) / st, 0, self.tnx - 1.001)
        fy = np.clip((np.asarray(y, np.float64) + self.hy) / st, 0, self.tny - 1.001)
        ix, iy = fx.astype(np.int64), fy.astype(np.int64)
        tx, ty = fx - ix, fy - iy
        g = self.tgrid
        a = g[iy, ix] * (1 - tx) + g[iy, ix + 1] * tx
        b = g[iy + 1, ix] * (1 - tx) + g[iy + 1, ix + 1] * tx
        if self.qidx is not None:
            return (a * (1 - ty) + b * ty + self.quay_cut_v(x, y)).astype(np.float32)
        return (a * (1 - ty) + b * ty).astype(np.float32)

    def ground_y(self, x, y):
        """Height of the walkable surface on the ground here: terrain + asphalt / pavement build-up."""
        st = self.tstep                                         # (th() inlined: this is called thousands of times per frame)
        fx = (x + self.hx) / st
        fy = (y + self.hy) / st
        nx = self.tnx
        if fx < 0.0:
            fx = 0.0
        elif fx > nx - 1.001:
            fx = nx - 1.001
        if fy < 0.0:
            fy = 0.0
        elif fy > self.tny - 1.001:
            fy = self.tny - 1.001
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        g = self.tl
        i = iy * nx + ix
        a = g[i] + (g[i + 1] - g[i]) * tx
        b = g[i + nx] + (g[i + nx + 1] - g[i + nx]) * tx
        t = a + (b - a) * ty
        if self.qidx is not None:
            t += self.quay_cut(x, y)
        if self.hgt is None:
            return t
        ix = int((x + self.hx) / self.cell)
        iy = int((y + self.hy) / self.cell)
        if 0 <= ix < self.ncx and 0 <= iy < self.ncy:
            k = iy * self.ncx + ix
            he = self._hedge
            if he is None:
                he = self._hedge_mask()
            c = self.hgt[k] & 3
            if c == 1 or he[k]:                                 # asphalt (its height depends on the road's rank) or a kerb / verge edge
                sub = self._hsub.get(k)
                if sub is None:
                    sub = self._hsub_cell(ix, iy, c)
                return t + sub[min(3, int(((y + self.hy) / self.cell - iy) * 4)) * 4 + min(3, int(((x + self.hx) / self.cell - ix) * 4))]
            return t + self.GROUND_Y[c]
        return t

    _hedge = None

    def _hedge_mask(self):
        """Cells of the 2 m height-class mask (0 ground, 1 asphalt, 2 pavement) next to a cell of another class. There the
        rendered kerb edge can be anywhere inside the cell, so ground_y looks the class up at 0.5 m from the road geometry."""
        h = (np.frombuffer(self.hgt, np.uint8).reshape(self.ncy, self.ncx) & 3)
        e = np.zeros_like(h, dtype=bool)
        e[:, 1:] |= h[:, 1:] != h[:, :-1]
        e[:, :-1] |= h[:, :-1] != h[:, 1:]
        e[1:, :] |= h[1:, :] != h[:-1, :]
        e[:-1, :] |= h[:-1, :] != h[1:, :]
        self._hedge = e.ravel().tobytes()
        self._hsub = {}
        g = {}
        for ed in self.edges:                                   # the same edges / widths the build rasterised (tools/build_world.py)
            if ed.get("bridge"):
                continue
            base = ed["cls"].replace("_link", "")
            sw = base in self.KERB_CLS
            asp = None
            if ed.get("drive") or ed.get("walk"):                # asphalt top as tools/roads3d.py y_of() lays it (without its <1 cm jitter)
                asp = 0.04 if base in self.FOOT_CLS else 0.05 + 0.016 * self.ROAD_RANK.get(base, 0)
            if not (sw or asp):
                continue
            hw = ed["w"] / 2
            rr = hw + (self.KERB_W if sw else 0.0) + 1.0
            for (ax, ay), (bx, by) in zip(ed["pts"], ed["pts"][1:]):
                for cx in range(int((min(ax, bx) - rr) // 16), int((max(ax, bx) + rr) // 16) + 1):
                    for cy in range(int((min(ay, by) - rr) // 16), int((max(ay, by) + rr) // 16) + 1):
                        g.setdefault((cx, cy), []).append((ax, ay, bx, by, hw, sw, asp))
        self._hgrid = g
        return self._hedge

    FOOT_CLS = {"pedestrian", "footway", "path", "steps", "cycleway", "track"}           # = tools/roads3d.py FOOT / RANK
    ROAD_RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1,
                 "living_street": 0, "service": 0}

    def _hsub_cell(self, ix, iy, cls):
        """Surface build-up of the 4 x 4 sub-cells (0.5 m) of one cell, as the 3D roads draw it: the highest asphalt
        ribbon within its half width, else pavement up to KERB_W beyond a city street, else bare ground. Where the road
        geometry finds nothing (junction plates, areas) the 2 m mask's class decides."""
        out = array.array("f")
        for j in range(4):
            for i in range(4):
                x = (ix + (i + 0.5) / 4) * self.cell - self.hx
                y = (iy + (j + 0.5) / 4) * self.cell - self.hy
                top, pav = None, False
                for ax, ay, bx, by, hw, sw, asp in self._hgrid.get((int(x // 16), int(y // 16)), ()):
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy or 1e-9
                    tt = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
                    d = math.hypot(x - ax - dx * tt, y - ay - dy * tt)
                    if asp is not None and d < hw:
                        if top is None or asp > top:
                            top = asp                           # asphalt wins over pavement; the higher-ranked road on top
                    elif sw and d < hw + self.KERB_W:
                        pav = True
                out.append(top if top is not None else (self.GROUND_Y[2] if pav else (self.GROUND_Y[cls] if cls == 1 else 0.0)))
        self._hsub[iy * self.ncx + ix] = out
        return out

    def _deck_tops(self):
        """Per deck: how far its drawn carriageway lies above the deck profile -- tools/roads3d.py y_of() lays the
        asphalt Y_BASE + Y_STEP * rank (+1 cm on a bridge) above it, footways 4 cm.  Without this cars and people
        sank 6-15 cm into every bridge (tools/ride_audit.py).  The highest-ranked bridge edge along the deck decides."""
        out = []
        br = [e for e in getattr(self, "edges", ()) if e.get("bridge") and len(e["pts"]) >= 2]
        for d in getattr(self, "decks", ()):
            pts = d["pts"]
            mx, my = pts[len(pts) // 2]
            best, bd = 0.0, 4.0
            for e in br:
                for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy or 1e-9
                    t = max(0.0, min(1.0, ((mx - ax) * dx + (my - ay) * dy) / l2))
                    dd = math.hypot(mx - ax - dx * t, my - ay - dy * t)
                    if dd < bd:
                        base = e["cls"].replace("_link", "")
                        off = 0.04 if base in self.FOOT_CLS else 0.05 + 0.016 * self.ROAD_RANK.get(base, 0) + 0.01
                        if dd < bd - 0.5 or off > best:
                            best = off
                        bd = min(bd, dd)
            out.append(best)
        return out

    def deck_h(self, x, y):
        """Height of the bridge deck above (x, y), or None."""
        segs = self.dgrid.get((int(x // 8), int(y // 8)))
        if not segs:
            return None
        best, bd = None, 1e18
        # the drawn deck carries pavements and a parapet beyond the carriageway half width, and OSM decks often
        # leave small gaps where bridge ways join: be generous, more so where the surface mask says "bridge"
        pad = 2.6 + (3.0 if self.surface(x, y) == 2 else 0.0)
        for ax, ay, bx, by, ha, hb, hw in segs:
            hw = hw + pad
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            ex, ey = x - ax - dx * t, y - ay - dy * t
            d2 = ex * ex + ey * ey
            if d2 < hw * hw and d2 < bd - 1e-6:                 # the nearest centreline point decides the height
                bd = d2
                best = ha + (hb - ha) * t
        return best

    def level(self, x, y, wy, plat=False):
        """Surface that something whose feet are at absolute height `wy` stands on: deck if on / above it, else ground.
        plat=True (people and bikes): fire escapes, roofs and jump ramps count too."""
        d = self.deck_h(x, y) if self.dgrid else None
        g = self.ground_y(x, y)
        if d is not None and wy >= d - 0.7 and d > g:          # (a deck profile running on below the street at a bridge end is buried: the street wins)
            g = d
        if plat and self.pg2:
            h = self.plat_h(x, y, wy)
            if h is not None and h > g:
                return h
        return g

    def wet(self, x, y, wy):
        """In ground-level water (river / lake), also under a bridge, unless standing on a deck or a road."""
        if self.hgt is None:
            return self.surface(x, y) == 1
        ix = int((x + self.hx) / self.cell)
        iy = int((y + self.hy) / self.cell)
        if not (0 <= ix < self.ncx and 0 <= iy < self.ncy):
            return False
        k = iy * self.ncx + ix
        if not (self.hgt[k] & 4) or self.surf[k] == 3:
            return False
        d = self.deck_h(x, y) if self.dgrid else None
        if self.surf[k] == 2 and d is None:
            return False                                     # a bridge without a 3D deck: drive across at ground level
        if d is not None and wy >= d - 0.9:
            return False                                     # standing on the deck (its ends dip to bank level: never "in the river")
        return wy <= self.th(x, y) + 0.6

    def slope_at(self, x, y, dx, dy, wy, d=1.2):
        """Rise over run of the surface in direction (dx, dy) (unit vector)."""
        return (self.level(x + dx * d, y + dy * d, wy) - self.level(x - dx * d, y - dy * d, wy)) / (2 * d)

    def edges_near(self, x, y, r):
        cg = self.cg
        g = self.cgrid
        out = []
        for cx in range(int((x - r) // cg), int((x + r) // cg) + 1):
            for cy in range(int((y - r) // cg), int((y + r) // cg) + 1):
                e = g.get((cx, cy))
                if e:
                    out.extend(e)
        return out

    def break_point(self, e):
        """A car knocked this tree / post / prop over: it stops colliding and its mesh triangles are hidden."""
        cg = self.cg
        cell = self.pgrid.get((int(e[0] // cg), int(e[1] // cg)))
        if cell and e in cell:
            cell.remove(e)
        tree = e[2] >= 0.45 and e[4] - max(e[3], self.ground_y(e[0], e[1]) - 0.3) > 8       # (`lo` of low props reaches far below the ground)
        hgt = e[4] - max(e[3], self.ground_y(e[0], e[1]) - 0.3)
        self.broken.append((e[0], e[1], 4.2 if tree else max(0.7, e[2] + 0.5), e[4] + (6 if tree else 0.5),
                            "tree" if tree else ("post" if hgt > 5.0 else "mid"), int(e[0] * 37 + e[1] * 91) & 0xffff))
        hx = self.hide_extra.get((e[0], e[1]))
        if hx:
            g0 = self.ground_y(e[0], e[1])
            self.broken_extra.append((e[0], e[1], hx[0], g0 + hx[1], g0 + hx[2]) + ((e[0] + hx[3], e[1] + hx[4]) if len(hx) > 3 else ()))
        self.broken_ver += 1

    def hide_broken(self, pos, bb):
        """Collapse the triangles of broken props inside one chunk mesh (all 3 vertices near the prop)."""
        near = [b for b in self.broken if bb is None or (bb[0] - 5 < b[0] < bb[2] + 5 and bb[1] - 5 < b[1] < bb[3] + 5)]
        extra = [b for b in self.broken_extra if bb is None or (bb[0] - 5 < b[0] < bb[2] + 5 and bb[1] - 5 < b[1] < bb[3] + 5)]
        if not near and not extra:
            return pos
        pos = pos.copy()
        t = pos[: len(pos) - len(pos) % 3].reshape(-1, 3, 3)
        kill = np.zeros(len(t), bool)
        for bx, by, r, hi, *_k in near:
            cand = np.nonzero((np.abs(t[:, 0, 0] - bx) < r) & (np.abs(t[:, 0, 2] - by) < r))[0]       # first vertex near it: the only triangles worth the full test
            if not len(cand):
                continue
            tc = t[cand]
            d2 = (tc[:, :, 0] - bx) ** 2 + (tc[:, :, 2] - by) ** 2
            kill[cand[np.all(d2 < r * r, axis=1) & np.all(tc[:, :, 1] < hi, axis=1)]] = True
        for bx, by, r, lo, hi, *arm in extra:                             # the part high above the ground: a signal arm (a segment), a billboard panel (a disc)
            ex, ey = arm if arm else (bx, by)
            rr = r + math.hypot(ex - bx, ey - by)
            cand = np.nonzero((np.abs(t[:, 0, 0] - bx) < rr) & (np.abs(t[:, 0, 2] - by) < rr))[0]
            if len(cand):
                tc = t[cand]
                sx, sy = ex - bx, ey - by
                l2 = sx * sx + sy * sy or 1.0
                u = np.clip(((tc[:, :, 0] - bx) * sx + (tc[:, :, 2] - by) * sy) / l2, 0.0, 1.0) if arm else 0.0
                d2 = (tc[:, :, 0] - bx - sx * u) ** 2 + (tc[:, :, 2] - by - sy * u) ** 2
                kill[cand[np.all((d2 < r * r) & (tc[:, :, 1] > lo) & (tc[:, :, 1] < hi), axis=1)]] = True
        t[kill] = 0.0
        return pos

    def points_near(self, x, y, r):
        cg = self.cg
        g = self.pgrid
        out = []
        for cx in range(int((x - r) // cg), int((x + r) // cg) + 1):
            for cy in range(int((y - r) // cg), int((y + r) // cg) + 1):
                e = g.get((cx, cy))
                if e:
                    out.extend(e)
        return out

    # ---- routing graph
    def _build_graph(self, P=lambda f, note='': None):
        self.out = {}          # node -> [(edge, dir)] for driving
        self.walk_out = {}
        for i, e in enumerate(self.edges):
            e["i"] = i
            if e["drive"]:
                self.out.setdefault(e["a"], []).append((i, 1))
                if not e["ow"]:
                    self.out.setdefault(e["b"], []).append((i, -1))
            if e["walk"]:
                self.walk_out.setdefault(e["a"], []).append((i, 1))
                self.walk_out.setdefault(e["b"], []).append((i, -1))
        self.main = self._main_net()
        P(0.2, 'routing graph')
        sg = 64.0
        self.sg = sg
        self.drive_cells, self.walk_cells = {}, {}
        for i, e in enumerate(self.edges):
            cells = {(int(x // sg), int(y // sg)) for x, y in e["pts"]}
            for k in range(len(e["pts"]) - 1):
                (ax, ay), (bx, by) = e["pts"][k], e["pts"][k + 1]
                cells.add((int((ax + bx) / 2 // sg), int((ay + by) / 2 // sg)))
            for c in cells:
                if e["drive"] and e["cls"] not in ("service", "living_street") and e["len"] > 12 and e["a"] in self.main and e["b"] in self.main:
                    self.drive_cells.setdefault(c, []).append(i)
                if e["walk"] and e["cls"] not in ("steps",):
                    self.walk_cells.setdefault(c, []).append(i)

    def _main_net(self):
        """Nodes of the largest strongly connected part of the driving graph: from each of them every other one can be
        reached under the one-way rules.  Traffic is born and routed only here, so no car starts in a closed-off pocket."""
        rev = {}
        for n, lst in self.out.items():
            for ei, d in lst:
                e = self.edges[ei]
                rev.setdefault(e["b"] if d == 1 else e["a"], []).append(n)
        order, seen = [], set()
        for n0 in self.out:                                   # Kosaraju, iterative: finishing order on the graph ...
            if n0 in seen:
                continue
            seen.add(n0)
            st = [(n0, iter(self.out.get(n0, ())))]
            while st:
                n, it = st[-1]
                for ei, d in it:
                    e = self.edges[ei]
                    m = e["b"] if d == 1 else e["a"]
                    if m not in seen:
                        seen.add(m)
                        st.append((m, iter(self.out.get(m, ()))))
                        break
                else:
                    st.pop()
                    order.append(n)
        best, seen = set(), set()
        for n0 in reversed(order):                            # ... then components on the reversed graph
            if n0 in seen:
                continue
            comp, st = {n0}, [n0]
            seen.add(n0)
            while st:
                for m in rev.get(st.pop(), ()):
                    if m not in seen:
                        seen.add(m)
                        comp.add(m)
                        st.append(m)
            if len(comp) > len(best):
                best = comp
        return best

    KERB_CLS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
                "primary_link", "secondary_link", "tertiary_link", "trunk_link"}
    KERB_W, KERB_H = 2.0, 0.16                     # pavement width / height, same as tools/roads3d.py

    def _kerb_grid(self):
        g = {}
        for e in self.edges:
            if not e["drive"] or e["bridge"]:
                continue
            hw, k = e["w"] / 2, e["cls"] in self.KERB_CLS
            for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                rr = hw + self.KERB_W + 1
                for cx in range(int((min(ax, bx) - rr) // 16), int((max(ax, bx) + rr) // 16) + 1):
                    for cy in range(int((min(ay, by) - rr) // 16), int((max(ay, by) + rr) // 16) + 1):
                        g.setdefault((cx, cy), []).append((ax, ay, bx, by, hw, k))
        self._kg = g

    def kerb(self, x, y):
        """True when (x, y) is on a raised pavement beside a city street (and not on any road's asphalt)."""
        if getattr(self, "_kg", None) is None:
            self._kerb_grid()
        on = False
        for ax, ay, bx, by, hw, k in self._kg.get((int(x // 16), int(y // 16)), ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            d = math.hypot(x - ax - dx * t, y - ay - dy * t)
            if d < hw:
                return False                           # asphalt of some road wins (junctions)
            if k and d < hw + self.KERB_W:
                on = True
        return on

    def edge_point(self, e, s):
        """Position & unit tangent at distance s along the stored direction of edge e."""
        cum, pts = e["cum"], e["pts"]
        i = min(max(bisect.bisect_right(cum, s) - 1, 0), len(pts) - 2)
        seg = cum[i + 1] - cum[i] or 1.0
        t = min(max((s - cum[i]) / seg, 0.0), 1.0)
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy) or 1.0
        return ax + dx * t, ay + dy * t, dx / d, dy / d

    def nearest_drive_point(self, x, y, radius=400):
        best, res = 1e18, None
        sg = self.sg
        for cx in range(int((x - radius) // sg), int((x + radius) // sg) + 1):
            for cy in range(int((y - radius) // sg), int((y + radius) // sg) + 1):
                for ei in self.drive_cells.get((cx, cy), ()):
                    e = self.edges[ei]
                    for k in range(len(e["pts"]) - 1):
                        ax, ay = e["pts"][k]
                        bx, by = e["pts"][k + 1]
                        mx, my = (ax + bx) / 2, (ay + by) / 2
                        d = (mx - x) ** 2 + (my - y) ** 2
                        if d < best:
                            best, res = d, (mx, my, math.atan2(by - ay, bx - ax))
        return res

    def nearest_walk_point(self, x, y, radius=60):
        """-> (edge index, s) of the closest walkable edge point (for putting pedestrians back on the paths)."""
        best, res = 1e18, None
        sg = self.sg
        for cx in range(int((x - radius) // sg), int((x + radius) // sg) + 1):
            for cy in range(int((y - radius) // sg), int((y + radius) // sg) + 1):
                for ei in self.walk_cells.get((cx, cy), ()):
                    e = self.edges[ei]
                    for k, (px, py) in enumerate(e["pts"]):
                        d = (px - x) ** 2 + (py - y) ** 2
                        if d < best:
                            best, res = d, (ei, e["cum"][k])
        return res
