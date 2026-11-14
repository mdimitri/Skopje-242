"""Far ring of the helicopter view: per 120 m chunk, one cheap merged mesh of flat-shaded building prisms (footprint walls +
the pre-triangulated roof) and trees as small green pyramids. Drawn only for chunks beyond the streamed (full / lite)
meshes, over the coarse whole-city ground (the overview map: roads and blocks). Built at load-free cost: lazily, a few
chunks per frame, from world.buildings / world.trees."""
import math
import time

import numpy as np

import gl3d

WALLS = np.array([(214, 204, 186), (226, 220, 206), (196, 186, 170), (232, 214, 190), (186, 184, 180), (210, 196, 172)], np.float32)
ROOFS = np.array([(150, 148, 146), (168, 92, 70), (128, 128, 130), (176, 170, 160)], np.float32)
TREE = np.array((70, 112, 58), np.float32)


class FarView:
    def __init__(self, world):
        self.w = world
        self.models = {}                         # chunk key -> Model or None (empty chunk)
        self.idx = None
        self.sph = {}

    def _index(self):
        w, S = self.w, self.w.chunk
        bi = {}
        for i, b in enumerate(getattr(w, "buildings", ())):
            x0, y0, x1, y1 = b["bb"]
            bi.setdefault((math.floor((x0 + x1) / 2 / S), math.floor((y0 + y1) / 2 / S)), []).append(i)
        ta = np.asarray(getattr(w, "trees", ()), np.float64).reshape(-1, 4)
        ti = {}
        if len(ta):
            kx, ky = np.floor(ta[:, 0] / S).astype(np.int64), np.floor(ta[:, 1] / S).astype(np.int64)
            o = np.lexsort((ky, kx))
            ks = np.stack([kx[o], ky[o]], 1)
            cut = np.flatnonzero(np.any(ks[1:] != ks[:-1], 1)) + 1
            for a, b in zip(np.r_[0, cut], np.r_[cut, len(o)]):
                ti[(int(ks[a, 0]), int(ks[a, 1]))] = o[a:b]
        self.idx, self.ta = (bi, ti), ta

    def _build(self, key):
        w = self.w
        bi, ti = self.idx
        tris, cols = [], []
        for i in bi.get(key, ()):
            b = w.buildings[i]
            ring = b["ring"]
            x0, y0, x1, y1 = b["bb"]
            g = w.ground_y((x0 + x1) / 2, (y0 + y1) / 2)
            top = g + b["h"]
            hsh = (int(x0 * 7.1) ^ int(y0 * 3.3)) & 1023
            wc, rc = WALLS[hsh % len(WALLS)], ROOFS[(hsh // 7) % len(ROOFS)]
            m = len(ring)
            for j in range(m):
                (ax, ay), (bx, by) = ring[j], ring[(j + 1) % m]
                p0, p1, p2, p3 = (ax, g - 0.5, ay), (bx, g - 0.5, by), (bx, top, by), (ax, top, ay)
                tris += [(p0, p1, p2), (p0, p2, p3)]
                cols += [wc, wc]
            v, tr = b.get("v"), b.get("tri")
            if v is not None and tr is not None and len(tr):
                V = np.asarray(v, np.float32)[:, :2]
                for t in np.asarray(tr, np.int64).reshape(-1, 3):
                    tris.append(tuple((float(V[k, 0]), top, float(V[k, 1])) for k in t))
                    cols.append(rc)
        tk = ti.get(key)
        if tk is not None:
            T = self.ta[tk]
            for x, y, r, _k in T.tolist():
                g = w.ground_y(x, y)
                r = max(1.6, r)
                h0, h1 = g + 1.2, g + 1.2 + 2.6 * r
                ap = (x, h1, y)
                b4 = [(x + r, h0, y), (x, h0, y + r), (x - r, h0, y), (x, h0, y - r)]
                for j in range(4):
                    tris.append((b4[j], b4[(j + 1) % 4], ap))
                    cols.append(TREE)
        if not tris:
            return None
        t = np.asarray(tris, np.float32)
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
        n *= np.where(n[:, 1:2] < -0.2, -1.0, 1.0)            # roofs / tree faces lit from above whichever way they wind
        c = np.asarray(cols, np.float32) * np.clip(0.62 + 0.45 * np.abs(n @ gl3d.SUN), 0, 1.15)[:, None]
        rgba = np.full((len(t) * 3, 4), 255, np.uint8)
        rgba[:, :3] = np.clip(np.repeat(c, 3, 0), 0, 255)
        return gl3d.make_model(t.reshape(-1, 3), np.zeros((len(t) * 3, 2), np.float32), rgba)

    def draw(self, rl, keys, skip, fr, budget_ms=3.0):
        """Draws the far meshes of `keys` (nearest first) that are not in `skip` (chunks with streamed meshes) and inside
        the frustum; builds missing ones within the time budget. Returns the number drawn."""
        if self.idx is None:
            self._index()
        t0 = time.perf_counter()
        S = self.w.chunk
        n = 0
        zero, white = rl.Vector3(0, 0, 0), rl.WHITE
        for k in keys:
            if k in skip:
                continue
            sp = self.sph.get(k)
            if sp is None:
                cx, cz = k[0] * S + S / 2, k[1] * S + S / 2
                sp = self.sph[k] = (cx, self.w.ground_y(cx, cz) + 15, cz, S * 0.75 + 30)
            if not fr.sphere(*sp):
                continue
            if k not in self.models:
                if (time.perf_counter() - t0) * 1000 > budget_ms:
                    continue
                self.models[k] = self._build(k)
            m = self.models[k]
            if m is not None:
                rl.draw_model(m, zero, 1.0, white)
                n += 1
        return n
