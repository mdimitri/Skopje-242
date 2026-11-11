"""Chunk baking, streaming (LRU) and the whole-city overview texture.

Each 120 m chunk of the map is rasterised ONCE into a GPU render texture (4 px/m, mipmapped) from the
pre-indexed OSM-derived geometry; per frame the game just draws a handful of textured quads.
"""
import math
import os
import random
import time

import numpy as np
import pyray as rl

from gfx import disc, fill_tris, quad, rect_rot, seg
import gl3d

PPM = 4.0                       # chunk texture resolution, pixels per metre
SKEW = 0.22                     # apparent roof lift per metre of building height
GROUND = (201, 196, 182)

ROAD_FILL = {
    "motorway": (92, 94, 102), "trunk": (88, 90, 98), "primary": (88, 90, 98), "secondary": (92, 94, 101),
    "tertiary": (97, 99, 106), "unclassified": (100, 102, 108), "residential": (102, 104, 110),
    "living_street": (126, 124, 124), "service": (118, 118, 122), "pedestrian": (206, 198, 184),
    "footway": (194, 188, 176), "path": (182, 168, 138), "steps": (168, 164, 160), "cycleway": (186, 150, 140),
    "track": (160, 140, 110),
}
SIDEWALK = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "primary_link", "secondary_link", "tertiary_link", "trunk_link", "motorway_link"}
MARK = {"primary", "secondary", "tertiary", "trunk", "motorway", "unclassified", "residential"}


def road_col(cls):
    return ROAD_FILL.get(cls.replace("_link", ""), (100, 102, 108))


def _turn(pts, k):
    """True when vertex k needs a round join (end or noticeable bend)."""
    if k == 0 or k >= len(pts) - 1:
        return True
    ax, ay = pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]
    bx, by = pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]
    d = math.hypot(ax, ay) * math.hypot(bx, by)
    return d > 0 and (ax * bx + ay * by) / d < 0.99


def _road_pass(world, items, mode):
    roads = world.roads
    for ri, k in items:
        rd = roads[ri]
        pts = rd["pts"]
        (x1, y1), (x2, y2) = pts[k], pts[k + 1]
        cls, w = rd["cls"], rd["w"]
        if mode == "side":
            if cls not in SIDEWALK:
                continue
            hw, col = w / 2 + 1.7, (184, 180, 170)
        elif mode == "case":
            hw, col = w / 2 + (0.9 if rd["bridge"] else 0.3), ((72, 72, 78) if rd["bridge"] else (66, 68, 74))
        elif mode == "fill":
            hw, col = w / 2, road_col(cls)
        else:  # markings
            if cls not in MARK or w < 5.5:
                continue
            dx, dy = x2 - x1, y2 - y1
            d = math.hypot(dx, dy)
            if d < 4:
                continue
            ux, uy = dx / d, dy / d
            t = 1.0
            mc = (232, 228, 205) if w >= 8 else (200, 200, 196)
            while t + 3.0 < d:
                seg(x1 + ux * t, y1 + uy * t, x1 + ux * (t + 3.0), y1 + uy * (t + 3.0), 0.11 if w < 8 else 0.15, mc)
                t += 9.0
            continue
        seg(x1, y1, x2, y2, hw, col)
        if _turn(pts, k):
            disc(x1, y1, hw, col, 8)
        if k == len(pts) - 2:
            disc(x2, y2, hw, col, 8)



def _crosswalk(xw):
    x, y, ax, ay, w = xw[0], xw[1], xw[2], xw[3], xw[4]
    rx, ry = ay, -ax                                  # across the road
    white = (236, 234, 226, 230)
    k = -w / 2 + 0.6
    while k < w / 2 - 0.3:                            # zebra bars run along the road
        seg(x + rx * k - ax * 1.5, y + ry * k - ay * 1.5, x + rx * k + ax * 1.5, y + ry * k + ay * 1.5, 0.26, white)
        k += 1.0
    seg(x + ax * 2.6, y + ay * 2.6, x + ax * 2.6 + rx * (w / 2 - 0.3), y + ay * 2.6 + ry * (w / 2 - 0.3), 0.14, white)   # stop line (right-hand lane)


def _quay_cells(w, x0, z0, side, n, sub=4, tol=0.025):
    """Ground mesh refinement along the river quays: the n x n cells of `side / n` m whose 1 m heights leave the bilinear
    of their corners by more than `tol` (revetments, embankment edges) are split into sub x sub quads.  A refined cell's
    border next to a coarse cell follows the coarse edge exactly (no cracks).  -> None, or (mask (n, n), triangle
    positions (k, 3))."""
    if getattr(w, "qidx", None) is None:
        return None
    c = side / n
    if (w.quay_cut_v(np.array([x0, x0 + side, x0, x0 + side, x0 + side / 2]),
                     np.array([z0, z0, z0 + side, z0 + side, z0 + side / 2])) == 0).all():
        span = w.qtile * w.qstep                           # quick out: no quay tile under this chunk at all
        tx0, tx1 = int((x0 - c + w.hx) // span), int((x0 + side + c + w.hx) // span)
        ty0, ty1 = int((z0 - c + w.hy) // span), int((z0 + side + c + w.hy) // span)
        a = w.qidx_a[max(0, ty0):max(0, ty1 + 1), max(0, tx0):max(0, tx1 + 1)]
        if not (a >= 0).any():
            return None
    m = (n + 2) * sub + 1                                   # 1 m posts over the chunk plus one cell all round
    g = x0 - c + np.arange(m) * (c / sub)
    h = z0 - c + np.arange(m) * (c / sub)
    GX, GZ = np.meshgrid(g, h)
    F = w.th_v(GX, GZ).astype(np.float64)
    C = F[::sub, ::sub]                                     # cell corners (n + 3) ^ 2
    t = np.arange(sub + 1) / sub
    B = np.lib.stride_tricks.sliding_window_view(F, (sub + 1, sub + 1))[::sub, ::sub]     # (n+2, n+2, sub+1, sub+1)
    c00, c01, c10, c11 = C[:-1, :-1, None, None], C[:-1, 1:, None, None], C[1:, :-1, None, None], C[1:, 1:, None, None]
    tv, tu = t[None, None, :, None], t[None, None, None, :]
    L = (c00 * (1 - tu) + c01 * tu) * (1 - tv) + (c10 * (1 - tu) + c11 * tu) * tv
    bent = np.abs(B - L).max(axis=(2, 3)) > tol             # (n+2, n+2), padded
    fine = bent[1:-1, 1:-1]
    if not fine.any():
        return None
    ci, cj = np.nonzero(fine)
    blk = B[ci + 1, cj + 1].copy()                          # (k, sub+1, sub+1) heights; rows = z, cols = x
    Lb = L[ci + 1, cj + 1]
    for side_, nb in (("w", bent[ci + 1, cj]), ("e", bent[ci + 1, cj + 2]), ("n", bent[ci, cj + 1]), ("s", bent[ci + 2, cj + 1])):
        k = ~nb                                             # coarse neighbour: follow its straight edge
        if not k.any():
            continue
        if side_ == "w":
            blk[k, :, 0] = Lb[k, :, 0]
        elif side_ == "e":
            blk[k, :, -1] = Lb[k, :, -1]
        elif side_ == "n":
            blk[k, 0, :] = Lb[k, 0, :]
        else:
            blk[k, -1, :] = Lb[k, -1, :]
    xs = (x0 + cj * c)[:, None, None] + (t * c)[None, None, :] + np.zeros((1, sub + 1, 1))
    zs = (z0 + ci * c)[:, None, None] + (t * c)[None, :, None] + np.zeros((1, 1, sub + 1))
    V = np.stack([xs, blk, zs], -1).reshape(len(ci), -1, 3)
    q = (np.arange(sub)[:, None] * (sub + 1) + np.arange(sub)[None, :]).ravel()
    tri = np.stack([q, q + 1, q + sub + 2, q, q + sub + 2, q + sub + 1], 1).ravel()
    return fine, V[:, tri, :].reshape(-1, 3).astype(np.float32)


QUAY_STONE, QUAY_GRASS = (150, 144, 134), (118, 146, 86)


def _paint_quays(world, ox, oy, span, res=0.5):
    """Stone revetments / walls and grass embankments along the river quays: wherever the quay cut slopes, coloured by
    the class of the 1 m posts around (tools/quays.py: 1 water, 2 stone, 3 promenade, 4 grass, 5 wall)."""
    w = world
    if getattr(w, "qidx", None) is None:
        return
    st, T = w.qstep, w.qtile
    sp = T * st
    a = w.qidx_a[max(0, int((oy + w.hy) // sp)):max(0, int((oy + span + w.hy) // sp) + 1),
                 max(0, int((ox + w.hx) // sp)):max(0, int((ox + span + w.hx) // sp) + 1)]
    if not (a >= 0).any():
        return
    N = int(round(span / res))
    c = ox + (np.arange(N) + 0.5) * res
    r = oy + (np.arange(N) + 0.5) * res
    X, Y = np.meshgrid(c, r)
    cut = w.quay_cut_v(X, Y)
    if not (cut < -0.05).any():
        return
    H = w.th_v(X, Y).astype(np.float64)
    gy, gx = np.gradient(H, res)
    slope = np.hypot(gx, gy)
    fx, fy = (X + w.hx) / st, (Y + w.hy) / st
    tx, ty = np.floor(fx / T).astype(np.int64), np.floor(fy / T).astype(np.int64)
    ok = (tx >= 0) & (ty >= 0) & (tx < w.qntx) & (ty < w.qnty)
    ti = np.full(X.shape, -1, np.int64)
    ti[ok] = w.qidx_a[ty[ok], tx[ok]]
    m = ti >= 0
    ix = np.zeros(X.shape, np.int64)
    iy = np.zeros(X.shape, np.int64)
    ix[m] = np.minimum((fx[m] - tx[m] * T).astype(np.int64), T - 1)
    iy[m] = np.minimum((fy[m] - ty[m] * T).astype(np.int64), T - 1)
    k = np.where(m, ti, 0)
    u, v = fx - np.floor(fx), fy - np.floor(fy)
    wg = np.zeros(X.shape)                                 # bilinear share of grass posts / of stone and water posts
    wh = np.zeros(X.shape)
    for cc, wt in ((w.qcls[k, iy, ix], (1 - u) * (1 - v)), (w.qcls[k, iy, ix + 1], u * (1 - v)),
                   (w.qcls[k, iy + 1, ix], (1 - u) * v), (w.qcls[k, iy + 1, ix + 1], u * v)):
        wg += wt * (cc == 4)
        wh += wt * ((cc == 1) | (cc == 2) | (cc == 5))
    t_ = np.clip((slope - 0.12) / 0.2, 0.0, 1.0)
    alpha = np.where(m & (cut < -0.05), t_ * t_ * (3 - 2 * t_), 0.0)
    g = np.clip(wg / np.maximum(wg + wh, 1e-6) * 1.6 - 0.3, 0.0, 1.0)
    g = np.where(wg + wh < 1e-6, 1.0, g)
    rng = np.random.default_rng(int(ox * 7 + oy * 13) & 0xFFFF)
    tint = rng.integers(-9, 10, X.shape)
    courses = ((np.floor(X / 0.9) + np.floor(Y / 0.9)) % 2 == 0) * (1 - g) * 10      # a hint of stone courses
    rgba = np.zeros(X.shape + (4,), np.uint8)
    for ch in range(3):
        rgba[..., ch] = np.clip(QUAY_STONE[ch] * (1 - g) + QUAY_GRASS[ch] * g + tint - courses, 0, 255)
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    if not rgba[..., 3].any():
        return
    rgba = np.ascontiguousarray(rgba)
    img = rl.Image(gl3d.ffi.from_buffer(rgba), N, N, 1, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    tex = rl.load_texture_from_image(img)
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_BILINEAR)
    rl.draw_texture_pro(tex, rl.Rectangle(0, 0, N, N), rl.Rectangle(ox, oy, span, span), rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.rl_draw_render_batch_active()                    # draw now: the texture is freed right after
    rl.unload_texture(tex)


def bake_chunk(world, cx, cy, rt, decals=()):
    """Ground only: land use, water, roads, markings, building footprints, decals.
    Buildings / trees / lamps are real 3D meshes (see Streamer)."""
    S, M = world.chunk, world.margin
    ox, oy = cx * S - M, cy * S - M
    ch = world.chunks.get((cx, cy))
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(*GROUND, 255))
    rl.begin_mode_2d(rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(ox, oy), 0.0, PPM))
    try:
        if ch is not None:
            rng = random.Random(cx * 7919 + cy * 104729)
            span = S + 2 * M
            for _ in range(46):          # ground variation: soft blotches
                c = rng.choice(((190, 184, 168, 20), (212, 208, 194, 20), (178, 182, 156, 18)))
                disc(ox + rng.uniform(0, span), oy + rng.uniform(0, span), rng.uniform(4, 14), c, 8)
            A = world.areas
            for ai, ks in ch["a"]:
                a = A[ai]
                fill_tris(a["v"], a["tri"], world.area_style[a["kind"]][1], 0, 0, ks)
            for ai, _ks in ch["a"]:        # grass tufts
                a = A[ai]
                if a["kind"] in ("park", "grass", "wood", "scrub", "cemetery"):
                    x0, y0, x1, y1 = a["bb"]
                    if x1 > ox and x0 < ox + span and y1 > oy and y0 < oy + span:
                        col = world.area_style[a["kind"]][1]
                        for _ in range(14):
                            disc(rng.uniform(max(x0, ox), min(x1, ox + span)), rng.uniform(max(y0, oy), min(y1, oy + span)),
                                 rng.uniform(.8, 2.2), (col[0] - 14, col[1] - 10, col[2] - 14, 70), 6)
            for wi, k in ch["wl"]:
                w = world.wlines[wi]
                (x1, y1), (x2, y2) = w["pts"][k], w["pts"][k + 1]
                seg(x1, y1, x2, y2, w["w"] / 2, (86, 146, 198))
                disc(x1, y1, w["w"] / 2, (86, 146, 198), 8)
            _paint_quays(world, ox, oy, span)
            for ri, k in ch["rail"]:
                pts = world.rails[ri]["pts"]
                (x1, y1), (x2, y2) = pts[k], pts[k + 1]
                seg(x1, y1, x2, y2, 1.5, (150, 140, 128))
                seg(x1, y1, x2, y2, 0.12, (80, 80, 86))
            ground = [it for it in ch["r"] if not world.roads[it[0]]["bridge"]]
            bridges = [it for it in ch["r"] if world.roads[it[0]]["bridge"]]
            for ri, k in bridges:                    # soft deck shadow on the water below
                rd_ = world.roads[ri]
                (bx1, by1), (bx2, by2) = rd_["pts"][k], rd_["pts"][k + 1]
                seg(bx1 + 1.5, by1 + 1.8, bx2 + 1.5, by2 + 1.8, rd_["w"] / 2 + 1.0, (12, 34, 62, 70))
            if not getattr(world, "roads3d", False):          # otherwise the roads are real 3D meshes
                for gi, grp in enumerate((ground, bridges)):
                    for mode in ("side", "case", "fill", "mark"):
                        _road_pass(world, grp, mode)
                xws = getattr(world, "xwalks", ())
                for i in ch.get("x", ()):         # zebra crossings + stop lines
                    _crosswalk(xws[i])
            B = world.buildings
            for i in ch["b"]:                 # ground contact (shadows are real-time, see sunshadow.py)
                b = B[i]
                fill_tris(b["v"], b["tri"], (120, 116, 112, 255))
        if not getattr(world, "roads3d", False):
            for d in decals:
                draw_decal(d)
    finally:
        rl.end_mode_2d()
        rl.end_texture_mode()


def draw_decal(d):
    if d[0] == "l":
        _, x1, y1, x2, y2, w, col = d
        seg(x1, y1, x2, y2, w, col)
    else:
        _, x, y, r, col = d
        disc(x, y, r, col, 8)


CAR_COLORS = gl3d.CAR_COLORS


def _sphere(x0, z0, x1, z1, y0, y1):
    """Bounding sphere of a box (x0..x1, y0..y1, z0..z1)."""
    return ((x0 + x1) * 0.5, (y0 + y1) * 0.5, (z0 + z1) * 0.5, 0.5 * math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2) + 1.0)


class Streamer:
    """LRU caches of baked ground textures and uploaded 3D chunk meshes, with a per-frame time budget."""

    def __init__(self, world, tex, max_ground=120, max_mesh=110):
        self.world = world
        self.tex = tex
        self.max_ground, self.max_mesh = max_ground, max_mesh
        self.lite_keys = set()
        self.ground = {}      # key -> [rt, last_used]
        self.meshes = {}      # key -> [{mat: model}, last_used]
        self.bad = set()
        self.frame = 0
        self.baked = 0
        self.bake_ms = 0.0
        self.mesh_loaded = 0
        self.recent = []      # (load number, bb) of the latest mesh loads
        self.sph = {}         # key -> bounding sphere (x, y, z, r) of its meshes / of its ground mesh: view-frustum culling
        self.gsph = {}
        self.size = int((world.chunk + 2 * world.margin) * PPM)
        self.pool = []
        self.decals = {}      # key -> history list (replayed on rebake)
        self.pending = {}     # key -> new decals to draw this frame
        self.errors = 0
        self.clock = None     # set by main: decals (blood, scorch) fade out after DECAL_MIN in-game minutes
        self.born = {}        # id(decal) -> clock.minutes when it was added
        self._purge_t = 0

    # ---- ground mesh: the terrain under one chunk, textured with its baked ground texture
    def _ground_model(self, key, rt):
        w = self.world
        S, M = w.chunk, w.margin
        side = S + 2 * M
        n = int(round(side / 4.0)) if w.hilly else 1
        x0, z0 = key[0] * S - M, key[1] * S - M
        xs = x0 + np.arange(n + 1) * (side / n)
        zs = z0 + np.arange(n + 1) * (side / n)
        X, Z = np.meshgrid(xs, zs)
        Y = w.th_v(X, Z) if w.hilly else np.zeros_like(X, np.float32)
        P = np.stack([X, Y, Z], -1).astype(np.float32)
        U = np.stack([(X - x0) / side, 1.0 - (Z - z0) / side], -1).astype(np.float32)
        i00 = (np.arange(n)[:, None] * (n + 1) + np.arange(n)[None, :]).ravel()
        fine = _quay_cells(w, x0, z0, side, n) if n > 1 else None
        if fine is not None:
            i00 = i00[~fine[0].ravel()]                     # 4 m cells the river quays bend are drawn at 1 m instead
        idx = np.stack([i00, i00 + 1, i00 + n + 2, i00, i00 + n + 2, i00 + n + 1], 1).ravel()
        pos = P.reshape(-1, 3)[idx]
        uv = U.reshape(-1, 2)[idx]
        if fine is not None:
            fp = fine[1]
            pos = np.concatenate([pos, fp])
            uv = np.concatenate([uv, np.stack([(fp[:, 0] - x0) / side, 1.0 - (fp[:, 2] - z0) / side], -1).astype(np.float32)])
            Y = np.concatenate([Y.ravel(), fp[:, 1]])
            idx = np.arange(len(pos))
        col = np.full((len(idx), 4), 255, np.uint8)
        self.gsph[key] = _sphere(x0, z0, x0 + side, z0 + side, float(Y.min()), float(Y.max()))
        m = gl3d.make_model(pos, uv, col)
        if m is not None:
            gl3d.set_texture(m, rt.texture)
            gl3d.apply_ground_detail(m)
        return m

    # ---- ground textures
    def _bake(self, key):
        t0 = time.perf_counter()
        rt = self.pool.pop() if self.pool else rl.load_render_texture(self.size, self.size)
        bake_chunk(self.world, key[0], key[1], rt, self.decals.get(key, ()))
        rl.gen_texture_mipmaps(rt.texture)
        rl.set_texture_filter(rt.texture, rl.TEXTURE_FILTER_TRILINEAR)
        rl.set_texture_wrap(rt.texture, rl.TEXTURE_WRAP_CLAMP)
        old = self.ground.get(key)
        self.ground[key] = [rt, self.frame, self._ground_model(key, rt)]
        self.baked += 1
        self.bake_ms = (time.perf_counter() - t0) * 1000

    def _load_meshes(self, key, lite=False):
        ch = self.world.chunks.get(key)
        (self.lite_keys.add if lite else self.lite_keys.discard)(key)
        out = {}
        y0, y1 = 1e9, -1e9
        if ch:
            for mat, (off, n) in ch["m"].items():
                pos, uv, col = self.world.mesh_arrays(off, n)
                if n:
                    ys = pos[:, 1]
                    y0, y1 = min(y0, float(ys.min())), max(y1, float(ys.max()))
                if self.world.broken:
                    pos = self.world.hide_broken(pos, ch.get("bb"))
                if mat == 6 and ("graf" not in self.tex or lite):
                    continue                                     # atlas failed: no decals rather than facade-textured ones
                m = gl3d.make_model(pos, uv, col)
                if m is not None:
                    names = ("A", "B", "roof", "white", "panel", "house", "graf", "brick", "conc", "concg", "cream", "mix") + gl3d.SURF_NAMES
                    gl3d.set_texture(m, self.tex.get(names[mat]) or self.tex["A"])
                    if lite:
                        pass
                    elif mat == 3 and getattr(self.world, "roads3d", False):
                        gl3d.apply_road_detail(m)                        # manholes, cracks, patches, oil on the asphalt
                    elif mat in (0, 1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17):
                        gl3d.apply_building_detail(m)                    # facade / roof relief towards the sun, grit, streaks
                    out[mat] = m
        self.meshes[key] = [out, self.frame]
        bb = ch.get("bb") if ch else None
        self.recent.append((self.mesh_loaded + 1, bb))         # (the sun shadow redraws only for new meshes near it)
        if len(self.recent) > 256:
            del self.recent[:128]
        self.sph[key] = _sphere(bb[0], bb[1], bb[2], bb[3], y0, y1) if bb is not None and y1 >= y0 else None
        self.mesh_loaded += 1

    def loaded_near(self, since, x0, z0, x1, z1):
        """Was a chunk mesh touching the box loaded after load number `since`?  (None when the log does not reach back.)"""
        if not self.recent or self.recent[0][0] > since + 1:
            return None
        for n, bb in reversed(self.recent):
            if n <= since:
                break
            if bb is None or (bb[2] >= x0 and bb[0] <= x1 and bb[3] >= z0 and bb[1] <= z1):
                return True
        return False

    def get_ground(self, key):
        e = self.ground.get(key)
        if e:
            e[1] = self.frame
            return e[0]
        return None

    def get_ground_model(self, key):
        e = self.ground.get(key)
        if e:
            e[1] = self.frame
            return e[2]
        return None

    def reload_near(self, x, y):
        """Drop uploaded chunk meshes around (x, y) so they reload with broken props hidden."""
        for key in list(self.meshes):
            ch = self.world.chunks.get(key)
            bb = ch.get("bb") if ch else None
            if bb is None or (bb[0] - 5 < x < bb[2] + 5 and bb[1] - 5 < y < bb[3] + 5):
                for m in self.meshes[key][0].values():
                    gl3d.free_model(m)
                del self.meshes[key]

    def get_meshes(self, key):
        e = self.meshes.get(key)
        if e:
            e[1] = self.frame
            return e[0]
        return None

    def update(self, wanted, want_meshes, budget_ms=8.0, lite=()):
        """lite: keys loaded at low quality (no facade/road detail, no graffiti) until they leave the set, then reloaded in full."""
        self.frame += 1
        t0 = time.perf_counter()
        n = 0
        for key in wanted:
            need_g = key not in self.ground and key not in self.bad
            up = key in self.meshes and key in self.lite_keys and key not in lite           # came close: swap the low-quality meshes for full ones
            need_m = want_meshes and (key not in self.meshes or up) and key not in self.bad and key in self.world.chunks
            if key in self.ground:
                self.ground[key][1] = self.frame
            if key in self.meshes:
                self.meshes[key][1] = self.frame
            if not (need_g or need_m):
                continue
            if n and (time.perf_counter() - t0) * 1000 > budget_ms:
                break
            try:
                if need_g:
                    self._bake(key)
                if need_m:
                    if need_g and (time.perf_counter() - t0) * 1000 > budget_ms:       # the bake alone used the frame's budget: meshes next frame
                        break
                    if up:
                        for m in self.meshes.pop(key)[0].values():
                            gl3d.free_model(m)
                    self._load_meshes(key, key in lite)
            except Exception as e:  # noqa: BLE001 - never let one chunk kill the game
                self.errors += 1
                self.bad.add(key)
                print(f"[stream] chunk {key} failed: {e}")
            n += 1
        self._evict()
        self._purge_decals()
        self._flush_decals()

    def _evict(self):
        if len(self.ground) > self.max_ground:
            for key, e in sorted(self.ground.items(), key=lambda kv: kv[1][1])[: len(self.ground) - self.max_ground]:
                if e[1] < self.frame - 2:
                    self.pool.append(e[0])
                    gl3d.free_model(e[2])
                    del self.ground[key]
        if len(self.meshes) > self.max_mesh:
            for key, e in sorted(self.meshes.items(), key=lambda kv: kv[1][1])[: len(self.meshes) - self.max_mesh]:
                if e[1] < self.frame - 2:
                    for m in e[0].values():
                        gl3d.free_model(m)
                    del self.meshes[key]

    # ---- decals: skid marks, blood, scorch burn into the ground textures and persist
    def add_decal(self, d):
        """d = ('l', x1,y1,x2,y2, halfwidth, rgba) or ('d', x,y,r, rgba)."""
        S = self.world.chunk
        x, y = (d[1], d[2])
        key = (math.floor(x / S), math.floor(y / S))
        hist = self.decals.setdefault(key, [])
        if len(hist) < 700:
            hist.append(d)
            if self.clock is not None and d[0] == "d":
                self.born[id(d)] = self.clock.minutes
        self.pending.setdefault(key, []).append(d)

    DECAL_MIN = 20.0

    def _purge_decals(self):
        """Blood and scorch blobs disappear DECAL_MIN in-game minutes after they were made (skid lines stay)."""
        if self.clock is None or not self.born:
            return
        self._purge_t += 1
        if self._purge_t < 30:
            return
        self._purge_t = 0
        now = self.clock.minutes
        baked = not getattr(self.world, "roads3d", False)
        for key, hist in self.decals.items():
            old = [d for d in hist if now - self.born.get(id(d), now) > self.DECAL_MIN]
            if not old:
                continue
            gone = {id(d) for d in old}
            hist[:] = [d for d in hist if id(d) not in gone]
            for i in gone:
                self.born.pop(i, None)
            e = self.ground.get(key)
            if baked and e:                                   # the texture has them burnt in: rebake without
                self.pool.append(e[0])
                gl3d.free_model(e[2])
                del self.ground[key]

    def _flush_decals(self):
        if not self.pending:
            return
        if getattr(self.world, "roads3d", False):          # decals are drawn as 3D quads above the road instead
            self.pending.clear()
            return
        S, M = self.world.chunk, self.world.margin
        done = 0
        for key in list(self.pending):
            ds = self.pending.pop(key)
            e = self.ground.get(key)
            if not e:
                continue
            rt = e[0]
            rl.begin_texture_mode(rt)
            rl.begin_mode_2d(rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(key[0] * S - M, key[1] * S - M), 0.0, PPM))
            for d in ds:
                draw_decal(d)
            rl.end_mode_2d()
            rl.end_texture_mode()
            rl.gen_texture_mipmaps(rt.texture)
            done += 1
            if done >= 3:
                break


# ------------------------------------------------------------------ overview / minimap
def bake_overview(world, size, path, progress=None):
    """Whole city in one texture (far LOD, minimap, map). Cached as PNG. Returns (texture, width)."""
    P = progress or (lambda f, note="": None)
    stamp = f"{int(world.stamp)}"
    while size >= 1024:
        sizeh = int(round(size * world.hy / world.hx))
        png = f"{path}_{size}_{stamp}c.png"          # "c": bumped when building shadows changed ("b": face culling fix)
        if os.path.exists(png) and os.path.exists(png + ".ok"):
            try:
                data = open(png, "rb").read()
                if len(data) >= int(open(png + ".ok").read().strip()):
                    img = rl.load_image_from_memory(".png", data, len(data))
                    if rl.is_image_valid(img) and img.width == size and img.height == sizeh:
                        tex = rl.load_texture_from_image(img)
                        rl.unload_image(img)
                        P(1.0, "cached")
                        break
            except Exception:  # noqa: BLE001 - corrupt cache -> rebake
                pass
        rt = rl.load_render_texture(size, sizeh)
        if not rl.is_render_texture_valid(rt):
            size //= 2
            continue
        cam = rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(-world.hx, -world.hy), 0.0, size / (2 * world.hx))
        first = [True]

        def pass_(fn, items, step, label, lo, hi):
            for i in range(0, max(1, len(items)), step):
                rl.begin_texture_mode(rt)
                if first[0]:
                    rl.clear_background(rl.Color(*GROUND, 255))
                    first[0] = False
                rl.begin_mode_2d(cam)
                fn(items[i:i + step])
                rl.end_mode_2d()
                rl.end_texture_mode()
                P(lo + (hi - lo) * min(1.0, (i + step) / max(1, len(items))), label)

        def f_areas(chunk):
            for a in chunk:
                fill_tris(a["v"], a["tri"], world.area_style[a["kind"]][1])

        def f_water(chunk):
            for w in chunk:
                for (x1, y1), (x2, y2) in zip(w["pts"], w["pts"][1:]):
                    seg(x1, y1, x2, y2, w["w"] / 2, (86, 146, 198))

        def f_roads(chunk):
            for rd in chunk:
                hw = max(rd["w"] / 2, 1.1 if rd["cls"] in ("footway", "path", "steps", "cycleway") else 2.0)
                col = road_col(rd["cls"]) if rd["drive"] else (214, 208, 196)
                p = rd["pts"]
                for (x1, y1), (x2, y2) in zip(p, p[1:]):
                    seg(x1, y1, x2, y2, hw, col)

        def f_bld(chunk):
            for b in chunk:
                fill_tris(b["v"], b["tri"], (176, 164, 154))

        def f_trees(chunk):
            for t in chunk:
                disc(t[0], t[1], 2.4, (84, 132, 70, 140), 6)

        pass_(f_areas, world.areas, 60, "land use & parks", 0.0, 0.2)
        pass_(f_water, world.wlines, 200, "rivers", 0.2, 0.25)
        pass_(f_roads, [r for r in world.roads if not r["bridge"] and not r.get("worn")], 600, "roads", 0.25, 0.55)
        pass_(f_roads, [r for r in world.roads if r["bridge"]], 600, "bridges", 0.55, 0.6)
        pass_(f_bld, world.buildings, 400, "buildings", 0.6, 0.85)
        pass_(f_trees, world.trees[::3], 1000, "trees", 0.85, 0.92)
        P(0.93, "saving the map")
        img = rl.load_image_from_texture(rt.texture)
        rl.image_flip_vertical(img)
        try:
            rl.export_image(img, png)
            with open(png + ".ok", "w") as f:
                f.write(str(os.path.getsize(png)))
        except Exception:  # noqa: BLE001 - cache is optional
            pass
        tex = rl.load_texture_from_image(img)
        rl.unload_image(img)
        rl.unload_render_texture(rt)
        break
    else:
        raise RuntimeError("cannot create the overview texture")
    rl.gen_texture_mipmaps(tex)
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_CLAMP)
    return tex, size
