"""Far city ring: real-building facade captures on prisms and depth-correct sprites.
Legacy worlds and pending captures use footprint blocks. Trees retain their cheap
pyramids. GPU captures are prepared before the main 3D pass, within a frame budget.
"""
import math
import time

import numpy as np

import gl3d

WALLS = np.array([(214, 204, 186), (226, 220, 206), (196, 186, 170), (232, 214, 190), (186, 184, 180), (210, 196, 172)], np.float32)
ROOFS = np.array([(150, 148, 146), (168, 92, 70), (128, 128, 130), (176, 170, 160)], np.float32)
TREE = np.array((70, 112, 58), np.float32)
HAZE = np.array((196, 210, 226), np.float32)
TILE = 3                                     # chunks per side of a last-band tile (360 m)
NEAR_BAND = 900.0                            # textured per-chunk blocks out to here, coarse merged tiles beyond


class FarView:
    def __init__(self, world, tex=None, textures=None):
        self.w = world
        self.tex = None                          # own mipmapped copy of facade texture A (windows), tinted by the vertex colours
        if tex is not None:
            try:
                import pyray as rl
                img = rl.load_image_from_texture(tex)
                t = rl.load_texture_from_image(img)
                rl.unload_image(img)
                rl.gen_texture_mipmaps(t)            # far away the windows average out instead of shimmering
                rl.set_texture_filter(t, rl.TEXTURE_FILTER_TRILINEAR)
                self.tex = t
            except Exception as e:  # noqa: BLE001 - untextured blocks rather than no far view
                print(f"[farview] texture copy failed: {e}")
        self.models = {}                         # chunk key -> Model or None (empty chunk)
        self.idx = None
        self.sph = {}
        self.captures = None
        self._captured = []
        self.tree_models = {}
        if textures is not None and any(c.get("lod") for c in world.chunks.values()):
            from buildinglod import Captures
            self.captures = Captures(world, textures)

    def prepare(self, pos, fr, far):
        """GPU captures must finish before entering the scene's 3D pass."""
        self._plan(pos[0], pos[1], NEAR_BAND, far)
        if self.captures is not None:
            # Prewarm visible full-mesh chunks too, before they leave the stream.
            keys = [self._items[i] for i in np.flatnonzero(fr.spheres(self._sp))]
            self.captures.prepare(keys)

    def close(self):
        if self.captures is not None:
            self.captures.close()
        for model in self.models.values():
            gl3d.free_model(model)
        for model in self.tree_models.values():
            gl3d.free_model(model)
        self.models.clear()
        if self.tex is not None:
            import pyray as rl
            rl.unload_texture(self.tex)

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

    def _build(self, key, trees_only=False):
        """key: a chunk (cx, cy) -> textured blocks and trees; or a tile ("T", tx, ty) of TILE x TILE chunks -> one coarse
        merged mesh for the last band: only buildings that make the skyline (tall or big), plain walls, no trees, hazed."""
        w = self.w
        bi, ti = self.idx
        tris, cols, uvs = [], [], []
        PL = (0.08, 0.06)                                    # a plain patch of facade texture A (above the windows): roofs, trees
        coarse = key[0] == "T"
        if coarse:
            ks = [(key[1] * TILE + i, key[2] * TILE + j) for i in range(TILE) for j in range(TILE)]
            ids = [i for k in ks for i in bi.get(k, ())]
            ids = [i for i in ids if w.buildings[i]["h"] >= 9.0 or (w.buildings[i]["bb"][2] - w.buildings[i]["bb"][0]) * (w.buildings[i]["bb"][3] - w.buildings[i]["bb"][1]) >= 600]
        else:
            ids = bi.get(key, ())
        for i in (() if trees_only else ids):
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
                if coarse:
                    uvs += [(PL, PL, PL), (PL, PL, PL)]
                    continue
                L = math.hypot(bx - ax, by - ay) / 3.0           # one window bay every 3 m, one storey every 3 m (as the near facades)
                v0, v1 = (b["h"] + 0.5) / 3.0, 0.0
                uvs += [((0, v0), (L, v0), (L, v1)), ((0, v0), (L, v1), (0, v1))]
            v, tr = b.get("v"), b.get("tri")
            if v is not None and tr is not None and len(tr):
                V = np.asarray(v, np.float32)[:, :2]
                for t in np.asarray(tr, np.int64).reshape(-1, 3):
                    tris.append(tuple((float(V[k, 0]), top, float(V[k, 1])) for k in t))
                    cols.append(rc)
                    uvs.append((PL, PL, PL))
        tk = None if coarse else ti.get(key)
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
                    uvs.append((PL, PL, PL))
        if not tris:
            return None
        t = np.asarray(tris, np.float32)
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
        n *= np.where(n[:, 1:2] < -0.2, -1.0, 1.0)            # roofs / tree faces lit from above whichever way they wind
        c = np.asarray(cols, np.float32) * np.clip(0.62 + 0.45 * np.abs(n @ gl3d.SUN), 0, 1.15)[:, None]
        if coarse:
            c = c * 0.7 + HAZE * 0.3                          # aerial perspective: the far skyline fades towards the sky

        rgba = np.full((len(t) * 3, 4), 255, np.uint8)
        rgba[:, :3] = np.clip(np.repeat(c, 3, 0), 0, 255)
        m = gl3d.make_model(t.reshape(-1, 3), np.asarray(uvs, np.float32).reshape(-1, 2), rgba)
        if m is not None and self.tex is not None:
            gl3d.set_texture(m, self.tex)
        return m

    def _plan(self, x, y, near, far):
        """Items for the view from (x, y): per-chunk blocks where any part of the tile is nearer than NEAR_BAND, one coarse
        tile mesh where the whole tile is beyond it. Recomputed only when the viewer crosses a chunk."""
        S = self.w.chunk
        T = S * TILE
        ck = (math.floor(x / S), math.floor(y / S))
        if getattr(self, "_pk", None) == (ck, near, far):
            return
        self._pk = (ck, near, far)
        lx, ly = int(self.w.hx // T) + 1, int(self.w.hy // T) + 1
        TX, TY = np.meshgrid(np.arange(max(math.floor((x - far) / T), -lx), min(math.floor((x + far) / T), lx) + 1),
                             np.arange(max(math.floor((y - far) / T), -ly), min(math.floor((y + far) / T), ly) + 1), indexing="ij")
        TX, TY = TX.ravel(), TY.ravel()
        gap = lambda X, Y, s_: np.hypot(np.maximum(np.maximum(X * s_ - x, 0), x - (X + 1) * s_), np.maximum(np.maximum(Y * s_ - y, 0), y - (Y + 1) * s_))
        tg = gap(TX, TY, T)
        items, sp = [], []
        for tx, ty, g in zip(TX.tolist(), TY.tolist(), tg.tolist()):
            if g >= far:
                continue
            if g >= NEAR_BAND and self.captures is None:
                k = ("T", tx, ty)
                v = self.sph.get(k)
                if v is None:
                    cx, cz = tx * T + T / 2, ty * T + T / 2
                    v = self.sph[k] = (cx, self.w.ground_y(cx, cz) + 20, cz, T * 0.75 + 40)
                items.append(k)
                sp.append(v)
                continue
            for i in range(TILE):
                for j in range(TILE):
                    k = (tx * TILE + i, ty * TILE + j)
                    if gap(np.array(k[0]), np.array(k[1]), S) >= far:
                        continue
                    v = self.sph.get(k)
                    if v is None:
                        cx, cz = k[0] * S + S / 2, k[1] * S + S / 2
                        v = self.sph[k] = (cx, self.w.ground_y(cx, cz) + 15, cz, S * 0.75 + 30)
                        records = self.w.chunks.get(k, {}).get("lod", ()) if self.captures else ()
                        if records:
                            lo = np.min([r[0] for r in records], axis=0)
                            hi = np.max([r[1] for r in records], axis=0)
                            lo = np.minimum(lo, (k[0]*S,v[1]-30,k[1]*S))
                            hi = np.maximum(hi, ((k[0]+1)*S,v[1]+30,(k[1]+1)*S))
                            c = (lo+hi)*0.5
                            v = self.sph[k] = (*c,float(np.linalg.norm(hi-lo)*0.5))
                    items.append(k)
                    sp.append(v)
        d2 = [(v[0] - x) ** 2 + (v[2] - y) ** 2 for v in sp]
        o = sorted(range(len(items)), key=d2.__getitem__)                 # nearest first: they get built first
        self._items = [items[i] for i in o]
        self._sp = np.asarray([sp[i] for i in o], np.float64).reshape(-1, 4)

    def draw(self, rl, pos, skip, fr, far, budget_ms=3.0, cam=None, dark=0.0):
        """Draws the far blocks round pos = (x, y) out to `far` m, leaving out chunks in `skip` (streamed meshes) and what is
        outside the frustum; builds missing ones within the time budget. Returns the number of draw calls."""
        if self.idx is None:
            self._index()
        t0 = time.perf_counter()
        self._plan(pos[0], pos[1], NEAR_BAND, far)
        items = self._items
        self._captured = []
        if not items:
            return 0
        n = 0
        zero, white = rl.Vector3(0, 0, 0), rl.WHITE
        for i in np.flatnonzero(fr.spheres(self._sp)).tolist():
            k = items[i]
            if k in skip:
                continue
            if self.captures is not None and self.captures.draw(k, cam, dark):
                self._captured.append(k)
                if k not in self.tree_models:
                    self.tree_models[k] = self._build(k, trees_only=True)
                trees = self.tree_models[k]
                if trees is not None:
                    rl.draw_model(trees, zero, 1.0, white)
                n += 1
                continue
            m = self.models.get(k, 0)
            if m == 0:
                if (time.perf_counter() - t0) * 1000 > budget_ms:
                    continue
                m = self.models[k] = self._build(k)
            if m is not None:
                rl.draw_model(m, zero, 1.0, white)
                n += 1
        return n

    def windows(self, rl, cam, dark):
        if self.captures is None or dark <= 0.02:
            return
        rl.begin_mode_3d(cam)
        rl.rl_disable_backface_culling()
        rl.rl_disable_depth_mask()
        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
        try:
            for key in self._captured:
                self.captures.draw(key, cam, dark, glow=True)
        finally:
            rl.end_blend_mode()
            rl.rl_enable_depth_mask()
            rl.end_mode_3d()
