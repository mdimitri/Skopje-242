"""Triangle soup with flat sun shading, shapely-polygon filling and a few solid primitives (poles, boxes, trees, cars)."""
import math

import mapbox_earcut as earcut
import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon

SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)
MERGE = 0.005          # outline points that move a filled shape by less than this (m) are merged: fewer triangles


def merged(g):
    return shapely.simplify(g, MERGE) if g is not None and MERGE else g


def polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for h in getattr(g, "geoms", []) for p in polys(h)]


class Mesh:
    def __init__(self):
        self.P, self.C = [], []

    def tri(self, a, b, c, col, lit=True):
        a, b, c = np.asarray(a, float), np.asarray(b, float), np.asarray(c, float)
        k = 1.0
        if lit:
            n = np.cross(b - a, c - a)
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                return
            n = n / ln
            if n[1] < 0:
                n = -n
            k = 0.62 + 0.46 * max(0.0, float(n @ SUN)) - 0.08 * (1 - n[1])
        cc = [max(0, min(255, int(v * k))) for v in col[:3]] + [255]
        self.P += [a, b, c]
        self.C += [cc] * 3

    def quad(self, a, b, c, d, col):
        self.tri(a, b, c, col)
        self.tri(a, c, d, col)

    def tris(self, t, col, lit=True):
        """Many tri() at once: t is (n, 3, 3)."""
        if lit:
            n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
            ln = np.sqrt((n * n).sum(axis=1))
            keep = ln >= 1e-12
            t, n, ln = t[keep], n[keep], ln[keep]
            n = n / ln[:, None]
            n[n[:, 1] < 0] *= -1
            k = 0.62 + 0.46 * np.maximum(0.0, n @ SUN) - 0.08 * (1 - n[:, 1])
        else:
            k = np.ones(len(t))
        cc = np.full((len(t), 4), 255)
        cc[:, :3] = np.clip(np.trunc(np.asarray(col[:3], float) * k[:, None]), 0, 255)
        self.P.extend(t.reshape(-1, 3))
        self.C.extend(np.repeat(cc, 3, axis=0).tolist())

    def poly(self, g, y, col, lit=True):
        """Fill a shapely (Multi)Polygon, holes included, flat at height y (y may be a function of coordinate arrays
        (x, z) -> heights)."""
        for p in polys(merged(g)):
            if p.area < 1e-4:
                continue
            rings = [np.asarray(p.exterior.coords)[:-1]] + [np.asarray(r.coords)[:-1] for r in p.interiors]
            v = np.concatenate(rings).astype(np.float64)
            ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
            idx = np.asarray(earcut.triangulate_float64(v, ends)).reshape(-1, 3)
            if not len(idx):
                continue
            height = np.broadcast_to(y(v[:, 0], v[:, 1]) if callable(y) else y, len(v))
            self.tris(np.stack([v[idx, 0], height[idx], v[idx, 1]], axis=2), col, lit)

    def wall_ring(self, coords, y0, y1, col):
        c = np.asarray(coords, float)
        if len(c) < 2:
            return
        a, b = c[:-1, :2], c[1:, :2]
        far = ((a - b) ** 2).sum(axis=1) >= 1e-8
        a, b = a[far], b[far]
        if not len(a):
            return
        low, high = np.full(len(a), y0, float), np.full(len(a), y1, float)
        p, q = np.stack([a[:, 0], low, a[:, 1]], 1), np.stack([b[:, 0], low, b[:, 1]], 1)
        r, t = np.stack([b[:, 0], high, b[:, 1]], 1), np.stack([a[:, 0], high, a[:, 1]], 1)
        self.tris(np.stack([np.stack([p, q, r], 1), np.stack([p, r, t], 1)], 1).reshape(-1, 3, 3), col)

    def prism(self, g, y0, y1, top, side):
        """Raised slab: flat top at y1 and vertical faces down to y0 on every boundary ring."""
        g = merged(g)
        self.poly(g, y1, top)
        for p in polys(g):
            self.wall_ring(p.exterior.coords, y0, y1, side)
            for r in p.interiors:
                self.wall_ring(r.coords, y0, y1, side)

    def box(self, x, y0, z, sx, sy, sz, col, yaw=0.0, roof=None):
        c, s = math.cos(yaw), math.sin(yaw)

        def q(dx, dz):
            return (x + dx * c - dz * s, z + dx * s + dz * c)
        base = [q(-sx / 2, -sz / 2), q(sx / 2, -sz / 2), q(sx / 2, sz / 2), q(-sx / 2, sz / 2)]
        for i in range(4):
            a, b = base[i], base[(i + 1) % 4]
            self.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + sy, b[1]), (a[0], y0 + sy, a[1]), col)
        self.quad(*[(p[0], y0 + sy, p[1]) for p in base], roof or col)

    def cyl(self, x, y0, y1, z, r, col, n=8):
        pts = [(x + r * math.cos(a * 2 * math.pi / n), z + r * math.sin(a * 2 * math.pi / n)) for a in range(n + 1)]
        self.wall_ring(pts, y0, y1, col)
        for i in range(n):
            self.tri((x, y1, z), (pts[i][0], y1, pts[i][1]), (pts[i + 1][0], y1, pts[i + 1][1]), col)

    def blob(self, x, y, z, r, h, col, n=9):
        """Rounded tree crown: two stacked cones, slightly varied colour."""
        for lvl, (yy, rr, hh) in enumerate(((y, r, h * 0.62), (y + h * 0.38, r * 0.72, h * 0.62))):
            ring = [(x + rr * math.cos(a * 2 * math.pi / n), z + rr * math.sin(a * 2 * math.pi / n)) for a in range(n + 1)]
            k = 1.0 + 0.08 * lvl
            cc = tuple(min(255, int(v * k)) for v in col)
            for i in range(n):
                a, b = ring[i], ring[i + 1]
                self.tri((a[0], yy, a[1]), (b[0], yy, b[1]), (x, yy + hh, z), cc)
                self.tri((b[0], yy, b[1]), (a[0], yy, a[1]), (x, yy - hh * 0.25, z), cc)

    def car(self, x, z, yaw, col, y=0.0, length=4.4, width=1.8):
        """Simple saloon: body, cabin, dark glass band, wheels implied by a darker skirt."""
        fx, fz = math.cos(yaw), math.sin(yaw)
        dark = (30, 32, 36)
        self.box(x, y + 0.18, z, length, 0.55, width, col, yaw)
        self.box(x - fx * 0.2, y + 0.73, z - fz * 0.2, length * 0.55, 0.5, width * 0.9, (60, 74, 88), yaw, roof=col)
        self.box(x, y + 0.05, z, length * 0.85, 0.2, width * 0.92, dark, yaw)
