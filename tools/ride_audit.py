"""Ride audit: do vehicles sink into the road on ramps, bridge approaches and hills?

Drives every vehicle type (car, van, bus, articulated bus, lorry, tanker, semi with its trailer, bike) along every
inclined drivable edge of a built world (bridge decks and their ramps, edges with a grade over 2.5 %, quay ramps), in
its lane, at street speed with a 60 fps clock, posing it each frame with the game's own code (actors.ride), and
compares the drawn model's lowest vertices with the RENDERED surface: the up-facing triangles of meshes.bin (roads,
decks, ramps, kerbs) and the terrain mesh.  Reports how far below that surface the model goes.

    python tools/ride_audit.py data/cache/world [--old] [--kinds car,bus,...] [--every 3]

--old poses with a copy of the pre-fix code (centre height + pitch from two points, smoothed), for before/after.
Use a ~10 % sample world (see memory: real-map crop), not the whole city."""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import actors  # noqa: E402
import gl3d  # noqa: E402
import vehicles as V  # noqa: E402
import world as world_mod  # noqa: E402

C = 2.0                                                       # surface bin size (m)
KINDS = {"car": V.IDS.index("Golf Dvojka"), "van": V.IDS.index("Ford Transit Shverc"), "bus": V.BUS,
         "artic": V.IDS.index("JSP Zglobni"), "lorry": V.IDS.index("Kamion Tovarnik"),
         "tanker": V.IDS.index("Cisterna Gorivo"), "semi": V.SEMI, "bike": V.IDS.index("Moped Tomos")}


class Surface:
    """Up-facing triangles of the rendered world near the audited edges, binned in C m cells."""

    def __init__(self, w, want):
        tris = []
        for ch in w.chunks.values():
            for mat, (off, n) in ch["m"].items():
                pos = w.mesh_arrays(off, n)[0].reshape(-1, 3, 3).astype(np.float64)
                nrm = np.cross(pos[:, 1] - pos[:, 0], pos[:, 2] - pos[:, 0])
                ln = np.linalg.norm(nrm, axis=1) + 1e-12
                tris.append(pos[nrm[:, 1] / ln > 0.5])      # up-facing (either winding is drawn: abs below)
                tris.append(pos[nrm[:, 1] / ln < -0.5])
        T = np.concatenate(tris)
        lo = np.floor(T[:, :, [0, 2]].min(1) / C).astype(np.int64)
        hi = np.floor(T[:, :, [0, 2]].max(1) / C).astype(np.int64)
        wa = np.array(sorted(want))
        ox, oz = wa[:, 0].min(), wa[:, 1].min()
        R = np.zeros((wa[:, 0].max() - ox + 2, wa[:, 1].max() - oz + 2), bool)
        R[wa[:, 0] - ox, wa[:, 1] - oz] = True
        I = np.zeros((R.shape[0] + 1, R.shape[1] + 1), np.int64)     # integral image: any wanted cell under the triangle's box
        I[1:, 1:] = R.cumsum(0).cumsum(1)
        x0 = np.clip(lo[:, 0] - ox, 0, R.shape[0])
        z0 = np.clip(lo[:, 1] - oz, 0, R.shape[1])
        x1 = np.clip(hi[:, 0] - ox + 1, 0, R.shape[0])
        z1 = np.clip(hi[:, 1] - oz + 1, 0, R.shape[1])
        sel = (I[x1, z1] - I[x0, z1] - I[x1, z0] + I[x0, z0]) > 0
        T, lo, hi = T[sel], lo[sel], hi[sel]
        self.g = {}
        for i in range(len(T)):
            for cx in range(int(lo[i, 0]), int(hi[i, 0]) + 1):
                for cz in range(int(lo[i, 1]), int(hi[i, 1]) + 1):
                    self.g.setdefault((cx, cz), []).append(i)
        self.T = T
        self.big = 0.5 * np.abs((T[:, 1, 0] - T[:, 0, 0]) * (T[:, 2, 2] - T[:, 0, 2]) - (T[:, 2, 0] - T[:, 0, 0]) * (T[:, 1, 2] - T[:, 0, 2])) >= 1.0
        self.g = {c: np.array(v) for c, v in self.g.items()}
        self.w = w

    def top(self, x, z, ymax, phys=None):
        """Highest rendered surface at (x, z) not above ymax (so a deck overhead does not count).  Small triangles
        (< 1 m2: kerb posts, hedges, benches, steps) count only within 0.3 m of the physics surface `phys`: higher up
        they are obstacles in the lane (a collision, reported apart), not road the wheels sink into."""
        best = float(self.w.th(x, z))                          # the terrain mesh
        idx = self.g.get((int(math.floor(x / C)), int(math.floor(z / C))))
        if idx is None:
            return best
        t = self.T[idx]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        v0x, v0z = b[:, 0] - a[:, 0], b[:, 2] - a[:, 2]
        v1x, v1z = c[:, 0] - a[:, 0], c[:, 2] - a[:, 2]
        px, pz = x - a[:, 0], z - a[:, 2]
        d = v0x * v1z - v1x * v0z
        d = np.where(np.abs(d) < 1e-12, 1e-12, d)
        u = (px * v1z - v1x * pz) / d
        v = (v0x * pz - px * v0z) / d
        ok = (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
        if ok.any():
            y = a[:, 1] + u * (b[:, 1] - a[:, 1]) + v * (c[:, 1] - a[:, 1])
            m = ok & (y <= ymax)
            if phys is not None:
                m &= self.big[idx] | (y <= phys + 0.3)
            y = y[m]
            if len(y):
                best = max(best, float(y.max()))
        return best


def bottom_points(pos, keep=40):
    """The model's lowest vertices (wheel bottoms, sills, bumpers), thinned to about `keep`."""
    pos = np.asarray(pos, np.float64).reshape(-1, 3)
    low = pos[pos[:, 1] < pos[:, 1].min() + 0.45]
    low = np.unique(np.round(low, 2), axis=0)
    if len(low) > keep:
        low = low[np.argsort(low[:, 1])[:keep]]
    return low


def mat_np(pitch, roll, h, x, y, z):
    """The renderer's transform (render.py cars): roll, pitch, heading, translate, as a 4x4 acting on column vectors."""
    cr, sr, cp, sp, ch, sh = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch), math.cos(-h), math.sin(-h)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Rz = np.array([[cp, -sp, 0], [sp, cp, 0], [0, 0, 1]])
    Ry = np.array([[ch, 0, sh], [0, 1, 0], [-sh, 0, ch]])
    return Ry @ Rz @ Rx, np.array([x, y, z])


def old_step(b, kind, lv, x, y, h, dt):
    b.gz = lv(x, y)
    fx, fy = math.cos(h), math.sin(h)
    hb = V.DIMS[kind][0] * 0.31
    pt = math.atan2(lv(x + fx * hb, y + fy * hb) - lv(x - fx * hb, y - fy * hb), 2 * hb)
    rl_ = math.atan2(lv(x + fy * 0.85, y - fx * 0.85) - lv(x - fy * 0.85, y + fx * 0.85), 1.7)
    k = min(1.0, dt * 9)
    b.pitch += (pt - b.pitch) * k
    b.roll += (rl_ - b.roll) * k
    b.tgz, b.tpitch, b.troll = b.gz, b.pitch, b.roll   # the trailer was drawn with the tractor's height and tilt


class _P:                                                   # stand-in for a car: the attributes ride() reads / writes
    def __init__(self, kind):
        self.kind = kind
        self.pitch = self.roll = 0.0
        self.gz = None
        self.trh = None
        self.tgz = self.tpitch = self.troll = None


def audited_edges(w, every):
    out = []
    for i, e in enumerate(w.edges):
        if not e["drive"] or len(e["pts"]) < 2:
            continue
        P = e["pts"]
        if any(abs(x) > w.hx - 40 or abs(y) > w.hy - 40 for x, y in P):
            continue                                       # the height-class raster ends at the world box
        steep = e["bridge"] or "_link" in e["cls"]
        if not steep:
            for (ax, ay), (bx, by) in zip(P, P[1:]):
                L = math.hypot(bx - ax, by - ay)
                if L > 2 and abs(w.ground_y(bx, by) - w.ground_y(ax, ay)) / L > 0.025:
                    steep = True
                    break
        if steep:
            out.append(i)
    return out[::every]


def run(w, kinds, every, old, speed=11.0, dt=1 / 60):
    eds = audited_edges(w, every)
    want = set()
    for i in eds:
        for (ax, ay), (bx, by) in zip(w.edges[i]["pts"], w.edges[i]["pts"][1:]):
            n = int(math.hypot(bx - ax, by - ay) / 1.0) + 1
            for k in range(n + 1):
                x, y = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
                for dx in range(-6, 7):
                    for dz in range(-6, 7):
                        want.add((int(math.floor(x / C)) + dx, int(math.floor(y / C)) + dz))
    print(f"[ride] {len(eds)} inclined drivable edges, binning the rendered surface ...", flush=True)
    S = Surface(w, want)
    print(f"[ride] {len(S.T)} up-facing triangles", flush=True)
    res = {}
    for name in kinds:
        kind = KINDS[name]
        body = bottom_points(gl3d.car_arrays(kind, 0)[0])
        trl = bottom_points(gl3d.trailer_arrays()[0]) if kind == V.SEMI else None
        rows = []
        for i in eds:
            e = w.edges[i]
            br = e["bridge"]
            lv = (lambda x_, y_: w.level(x_, y_, 1e9)) if br else w.ground_y      # as the game's traffic (actors.Traffic.update)
            for d in (1, -1):
                P = e["pts"] if d == 1 else e["pts"][::-1]
                lane = (e["w"] / 4 if not e.get("ow") else 0.0)
                b = _P(kind)
                tra = None
                s = 0.0
                cum = [0.0]
                for (ax, ay), (bx, by) in zip(P, P[1:]):
                    cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
                L = cum[-1]
                j = 0
                fr_ = 0
                worst = (0.0, None)
                while s < L:
                    while j < len(P) - 2 and cum[j + 1] < s:
                        j += 1
                    (ax, ay), (bx, by) = P[j], P[j + 1]
                    seg = max(1e-6, cum[j + 1] - cum[j])
                    t = (s - cum[j]) / seg
                    h = math.atan2(by - ay, bx - ax)
                    x = ax + (bx - ax) * t - math.sin(h) * lane
                    y = ay + (by - ay) * t + math.cos(h) * lane
                    if kind == V.SEMI:                     # the trailer axle on the kingpin's path
                        hx, hy = x + math.cos(h) * V.SEMI_HITCH, y + math.sin(h) * V.SEMI_HITCH
                        if tra is None:
                            tra = (hx - math.cos(h) * V.SEMI_AXLE, hy - math.sin(h) * V.SEMI_AXLE)
                        dx, dy = hx - tra[0], hy - tra[1]
                        th = math.atan2(dy, dx)
                        tra = (hx - math.cos(th) * V.SEMI_AXLE, hy - math.sin(th) * V.SEMI_AXLE)
                        b.trh = th
                    if old:
                        old_step(b, kind, lv, x, y, h, dt)
                    else:
                        b.gz = max(lv(x, y), actors.ride(b, lambda x_, y_: lv(x_, y_), x, y, h, dt))
                    s += speed * dt
                    fr_ += 1
                    if s < 3.0 or fr_ % 4:
                        continue                           # let the smoothing settle on the first frames; measure every 4th frame (0.7 m)
                    R, tr = mat_np(b.pitch, b.roll, h, x, b.gz, y)
                    pen = 0.0
                    parts = [(body, R, tr)]
                    if trl is not None:
                        th_ = b.trh if b.trh is not None else h
                        R2, tr2 = mat_np(b.tpitch, b.troll, th_, x + math.cos(h) * V.SEMI_HITCH, b.tgz, y + math.sin(h) * V.SEMI_HITCH)
                        parts.append((trl, R2, tr2))
                    for pts, R_, t_ in parts:
                        W = pts @ R_.T + t_
                        for wx, wy, wz in W:
                            top = S.top(wx, wz, wy + 0.8, lv(wx, wz))
                            if top - wy > pen:
                                pen = top - wy
                                if os.environ.get("RIDE_DEBUG") and pen > 0.5:
                                    print(f"    debug {name} edge {i} d {d} s {s:.1f} vertex ({wx:.2f},{wy:.2f},{wz:.2f}) top {top:.2f} "
                                          f"gz {b.gz:.2f} pitch {b.pitch:.3f} roll {b.roll:.3f} centre-level {lv(x, y):.2f}")
                    rows.append(pen)
                    if pen > worst[0]:
                        worst = (pen, (round(x, 1), round(y, 1)))
                if worst[1] is not None:
                    res.setdefault(name + "_worst", []).append((worst[0], worst[1], "bridge" if br else e["cls"]))
        a = np.array(rows) if rows else np.zeros(1)
        res[name] = a
        print(f"[ride] {name:7s} poses {len(a):6d}  sinking >5cm {100 * np.mean(a > 0.05):5.1f}%  >15cm {100 * np.mean(a > 0.15):5.1f}%  "
              f"p95 {np.percentile(a, 95):.3f} m  max {a.max():.3f} m", flush=True)
        ws = sorted(res.get(name + "_worst", []), reverse=True)[:3]
        for p_, xy, cls in ws:
            print(f"         worst {p_:.2f} m at {xy} ({cls})")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--old", action="store_true")
    ap.add_argument("--kinds", default=",".join(KINDS))
    ap.add_argument("--every", type=int, default=1, help="audit every n-th inclined edge")
    a = ap.parse_args()
    w = world_mod.World(a.world)
    run(w, a.kinds.split(","), a.every, a.old)


if __name__ == "__main__":
    main()
