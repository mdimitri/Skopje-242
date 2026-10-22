"""Runtime world: loads the baked pickle, builds collision grid + routing graph."""
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
    return pickle.loads(bytes(buf))


class World:
    def __init__(self, path, progress=None):
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
            if bi % 2000 == 0:
                P(0.8 * bi / max(nb, 1), f"building collision {bi}/{nb}")
        self.cgrid = g
        pg = {}
        th = self.th
        for x, y, r, _s in self.trees:
            t = th(x, y)
            pg.setdefault((int(x // cg), int(y // cg)), []).append((x, y, 0.5 if r < 3.5 else 0.65, t - 1.0, t + 9.0))
        for x, y in self.lamps:
            t = th(x, y)
            pg.setdefault((int(x // cg), int(y // cg)), []).append((x, y, 0.22, t - 1.0, t + 6.5))
        for p in getattr(self, "posts", ()):
            x, y, r = p[0], p[1], p[2]
            lo, hi = (p[3], p[4]) if len(p) >= 5 else (th(x, y) - 1.0, th(x, y) + 2.4)
            pg.setdefault((int(x // cg), int(y // cg)), []).append((x, y, r, lo, hi))
        self.pgrid = pg
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
        # bridge decks: 8 m hash of centreline segments (x1, y1, x2, y2, h1, h2, half width)
        self.dgrid = {}
        for d in getattr(self, "decks", ()):
            pts, hs, hw = d["pts"], d["h"], d["hw"]
            for k in range(len(pts) - 1):
                (ax, ay), (bx, by) = pts[k], pts[k + 1]
                seg = (ax, ay, bx, by, hs[k], hs[k + 1], hw)
                m = hw + 5.6
                for cx in range(int((min(ax, bx) - m) // 8), int((max(ax, bx) + m) // 8) + 1):
                    for cy in range(int((min(ay, by) - m) // 8), int((max(ay, by) + m) // 8) + 1):
                        self.dgrid.setdefault((cx, cy), []).append(seg)

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
        return (a * (1 - ty) + b * ty).astype(np.float32)

    def ground_y(self, x, y):
        """Height of the walkable surface on the ground here: terrain + asphalt / pavement build-up."""
        t = self.th(x, y)
        if self.hgt is None:
            return t
        ix = int((x + self.hx) / self.cell)
        iy = int((y + self.hy) / self.cell)
        if 0 <= ix < self.ncx and 0 <= iy < self.ncy:
            return t + self.GROUND_Y[self.hgt[iy * self.ncx + ix] & 3]
        return t

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

    def level(self, x, y, wy):
        """Surface that something whose feet are at absolute height `wy` stands on: deck if on / above it, else ground."""
        d = self.deck_h(x, y) if self.dgrid else None
        if d is not None and wy >= d - 0.7:
            return d
        return self.ground_y(x, y)

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
        if self.surf[k] == 2 and (not self.dgrid or self.deck_h(x, y) is None):
            return False                                     # a bridge without a 3D deck: drive across at ground level
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
        tree = e[2] >= 0.45 and e[4] - e[3] > 8
        self.broken.append((e[0], e[1], 4.2 if tree else max(0.7, e[2] + 0.5), e[4] + (6 if tree else 0.5)))
        self.broken_ver += 1

    def hide_broken(self, pos, bb):
        """Collapse the triangles of broken props inside one chunk mesh (all 3 vertices near the prop)."""
        near = [b for b in self.broken if bb is None or (bb[0] - 5 < b[0] < bb[2] + 5 and bb[1] - 5 < b[1] < bb[3] + 5)]
        if not near:
            return pos
        pos = pos.copy()
        t = pos[: len(pos) - len(pos) % 3].reshape(-1, 3, 3)
        kill = np.zeros(len(t), bool)
        for bx, by, r, hi in near:
            d2 = (t[:, :, 0] - bx) ** 2 + (t[:, :, 2] - by) ** 2
            kill |= np.all(d2 < r * r, axis=1) & np.all(t[:, :, 1] < hi, axis=1)
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
                if e["drive"] and e["cls"] not in ("service", "living_street") and e["len"] > 12:
                    self.drive_cells.setdefault(c, []).append(i)
                if e["walk"] and e["cls"] not in ("steps",):
                    self.walk_cells.setdefault(c, []).append(i)

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
