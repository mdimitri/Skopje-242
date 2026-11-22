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
import surfacepack
import treegen

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
    stop = xw[6] if len(xw) > 6 else 1
    if stop:
        x, y = x + ax * 2.6, y + ay * 2.6
        divider = xw[7] if len(xw) > 7 else 0.0
        lo, hi = (-w / 2 + 0.3 if stop == 2 else divider), w / 2 - 0.3
        seg(x + rx * lo, y + ry * lo, x + rx * hi, y + ry * hi, 0.14, white)


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
    yield                                                  # the numpy phases are 5-10 ms each on a big chunk: one per call, so the bake can stop between them
    H = w.th_v(X, Y, quay=cut).astype(np.float64)
    gy, gx = np.gradient(H, res)
    slope = np.hypot(gx, gy)
    yield
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
    yield
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
    yield
    rgba = np.ascontiguousarray(rgba)
    img = rl.Image(gl3d.ffi.from_buffer(rgba), N, N, 1, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    tex = rl.load_texture_from_image(img)
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_BILINEAR)
    rl.draw_texture_pro(tex, rl.Rectangle(0, 0, N, N), rl.Rectangle(ox, oy, span, span), rl.Vector2(0, 0), 0.0, rl.WHITE)
    rl.rl_draw_render_batch_active()                    # draw now: the texture is freed right after
    rl.unload_texture(tex)


def bake_steps(world, cx, cy, rt, decals=()):
    """Ground only: land use, water, roads, markings, building footprints, decals.
    Buildings / trees / lamps are real 3D meshes (see Streamer).
    A generator: each next() paints one stage into rt, so the Streamer can spread one bake over several frames."""
    S, M = world.chunk, world.margin
    ox, oy = cx * S - M, cy * S - M
    ch = world.chunks.get((cx, cy))
    span = S + 2 * M
    rng = random.Random(cx * 7919 + cy * 104729)

    def stages():
        if ch is not None:
            def blotches():
                for _ in range(46):          # ground variation: soft blotches
                    c = rng.choice(((190, 184, 168, 20), (212, 208, 194, 20), (178, 182, 156, 18)))
                    disc(ox + rng.uniform(0, span), oy + rng.uniform(0, span), rng.uniform(4, 14), c, 8)
            yield blotches
            A = world.areas

            def areas():
                for ai, ks in ch["a"]:
                    a = A[ai]
                    fill_tris(a["v"], a["tri"], world.area_style[a["kind"]][1], 0, 0, ks)
            yield areas

            def tufts():
                for ai, _ks in ch["a"]:        # grass tufts
                    a = A[ai]
                    if a["kind"] in ("park", "grass", "wood", "scrub", "cemetery"):
                        x0, y0, x1, y1 = a["bb"]
                        if x1 > ox and x0 < ox + span and y1 > oy and y0 < oy + span:
                            col = world.area_style[a["kind"]][1]
                            for _ in range(14):
                                disc(rng.uniform(max(x0, ox), min(x1, ox + span)), rng.uniform(max(y0, oy), min(y1, oy + span)),
                                     rng.uniform(.8, 2.2), (col[0] - 14, col[1] - 10, col[2] - 14, 70), 6)
            yield tufts

            def water_rail():
                for wi, k in ch["wl"]:
                    w = world.wlines[wi]
                    (x1, y1), (x2, y2) = w["pts"][k], w["pts"][k + 1]
                    seg(x1, y1, x2, y2, w["w"] / 2, (86, 146, 198))
                    disc(x1, y1, w["w"] / 2, (86, 146, 198), 8)
            yield water_rail
            quay = _paint_quays(world, ox, oy, span)
            for _ in range(5):                               # up to 5 phases, one per stage (an exhausted generator does nothing)
                yield lambda: next(quay, None)

            def rails():
                for ri, k in ch["rail"]:
                    pts = world.rails[ri]["pts"]
                    (x1, y1), (x2, y2) = pts[k], pts[k + 1]
                    seg(x1, y1, x2, y2, 1.5, (150, 140, 128))
                    seg(x1, y1, x2, y2, 0.12, (80, 80, 86))
            yield rails
            ground = [it for it in ch["r"] if not world.roads[it[0]]["bridge"]]
            bridges = [it for it in ch["r"] if world.roads[it[0]]["bridge"]]

            def deck_shadow():
                for ri, k in bridges:                    # soft deck shadow on the water below
                    rd_ = world.roads[ri]
                    (bx1, by1), (bx2, by2) = rd_["pts"][k], rd_["pts"][k + 1]
                    seg(bx1 + 1.5, by1 + 1.8, bx2 + 1.5, by2 + 1.8, rd_["w"] / 2 + 1.0, (12, 34, 62, 70))
            yield deck_shadow
            if not getattr(world, "roads3d", False):          # otherwise the roads are real 3D meshes
                for grp in (ground, bridges):
                    for mode in ("side", "case", "fill", "mark"):
                        yield lambda grp=grp, mode=mode: _road_pass(world, grp, mode)
                xws = getattr(world, "xwalks", ())

                def zebras():
                    for i in ch.get("x", ()):         # zebra crossings + stop lines
                        _crosswalk(xws[i])
                yield zebras
            B = world.buildings

            def footprints():
                for i in ch["b"]:                 # ground contact (shadows are real-time, see sunshadow.py)
                    b = B[i]
                    fill_tris(b["v"], b["tri"], (120, 116, 112, 255))
            yield footprints
        if not getattr(world, "roads3d", False):
            def decal_pass():
                for d in decals:
                    draw_decal(d)
            yield decal_pass

    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(*GROUND, 255))
    rl.end_texture_mode()
    yield
    for stage in stages():
        rl.begin_texture_mode(rt)
        rl.begin_mode_2d(rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(ox, oy), 0.0, PPM))
        try:
            stage()
        finally:
            rl.end_mode_2d()
            rl.end_texture_mode()
        yield


def bake_chunk(world, cx, cy, rt, decals=()):
    for _ in bake_steps(world, cx, cy, rt, decals):
        pass


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


TREE_NEAR, TREE_FAR = 3, 1                # tree detail level inside / beyond the full-detail ring (src/treegen.py)
TREE_RINGS = ((60.0, 4), (150.0, 3), (300.0, 2))   # metres from the avatar to the chunk -> tree level (4 = most detailed); beyond the last ring: TREE_FAR. Same in every view
TREE_SLICE = 40                          # trees made per step of a chunk's tree job (spreads a dense chunk's ~90 ms over frames)
TREE_DOWN_AFTER = 120                    # updates a chunk must stay in the far ring before its trees drop to TREE_FAR (no flip-flop at the border)
TREES_FROM = 78                      # world format version from which tree meshes are made at runtime (tools/build_world.py VERSION)


class Streamer:
    """LRU caches of baked ground textures and uploaded 3D chunk meshes, with a per-frame time budget."""

    def __init__(self, world, tex, max_ground=120, max_mesh=110):
        self.world = world
        self.tex = tex
        self.max_ground, self.max_mesh = max_ground, max_mesh
        self.lite_keys = set()
        self.tree_lvl = {}                       # key -> detail level of the tree meshes now loaded for the chunk (src/treegen.py)
        self.focus = None                        # (x, y) the avatar: chunks pick their tree level by distance from it (main.py sets it every frame)
        self._tree_dirty = set()                 # chunks whose trees changed (shed / felled): their tree meshes are redone in place
        self._tj = {}                            # key -> unfinished tree job (see _tree_models)
        self._lite_run = {}                      # key -> consecutive updates spent in the far ring (hysteresis for downgrades)
        self.stale = set()                       # chunks whose meshes are redone (a prop broke) while the old ones keep drawing
        self.detail = 2                          # the ДЕТАЛИ setting (main.py): 0 leaves out facade relief, 0-1 the clutter
        self.ground = {}      # key -> [rt, last_used]
        self.meshes = {}      # key -> [{mat: model}, last_used]
        self.bad = set()
        if getattr(world, "version", 0) >= TREES_FROM:
            treegen.warm()                           # runtime trees: every species / variant mesh made during loading
        self.frame = 0
        self.baked = 0
        self.bake_ms = 0.0
        self.mesh_loaded = 0
        self.recent = []      # (load number, bb) of the latest mesh loads
        self.sph = {}         # key -> bounding sphere (x, y, z, r) of its meshes / of its ground mesh: view-frustum culling
        self.gsph = {}
        self.size = int((world.chunk + 2 * world.margin) * PPM)
        self.pool = []
        self._baking = None   # [key, render texture, bake_steps generator, ms so far]: the ground bake in progress
        self.decals = {}      # key -> history list (replayed on rebake)
        self.pending = {}     # key -> new decals to draw this frame
        self.errors = 0
        self.clock = None     # set by main: decals (blood, scorch) fade out after DECAL_MIN in-game minutes
        self.born = {}        # id(decal) -> clock.minutes when it was added
        self._purge_t = 0
        self._part = {}       # key -> unfinished mesh upload (see _load_meshes)

    def set_texture_pack(self, mode):
        if surfacepack.select(mode):
            for _, _, model in self.ground.values():
                surfacepack.bind(model)
            for cache in (self.meshes, self._part):
                for entry in cache.values():
                    for model in entry[0].values():
                        surfacepack.bind(model)
        return surfacepack.current_mode()

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
            surfacepack.bind(m)
        return m

    # ---- ground textures
    def _abandon_bake(self):
        if self._baking is not None:
            self.pool.append(self._baking[1])                  # half-painted: the next bake clears it again
            self._baking = None

    def _bake(self, key, deadline):
        """Paints one chunk's ground texture stage by stage; True when finished, False when the frame's time is up (call again)."""
        if self._baking is not None and self._baking[0] != key:
            self._abandon_bake()
        if self._baking is None:
            rt = self.pool.pop() if self.pool else rl.load_render_texture(self.size, self.size)
            self._baking = [key, rt, bake_steps(self.world, key[0], key[1], rt, self.decals.setdefault(key, [])), 0.0]
        bk = self._baking
        t0 = time.perf_counter()
        try:
            while True:
                next(bk[2])
                if time.perf_counter() >= deadline:
                    bk[3] += (time.perf_counter() - t0) * 1000
                    return False
        except StopIteration:
            pass
        rt = bk[1]
        self._baking = None
        rl.gen_texture_mipmaps(rt.texture)
        rl.set_texture_filter(rt.texture, rl.TEXTURE_FILTER_TRILINEAR)
        rl.set_texture_wrap(rt.texture, rl.TEXTURE_WRAP_CLAMP)
        old = self.ground.get(key)
        self.ground[key] = [rt, self.frame, self._ground_model(key, rt)]
        self.baked += 1
        self.bake_ms = bk[3] + (time.perf_counter() - t0) * 1000
        return True

    def _load_meshes(self, key, lite=False, deadline=None):
        """Uploads a chunk's meshes one material at a time; past `deadline` (perf_counter) it stops and the next call
        carries on, so one big chunk cannot cost a whole frame.  Returns True when the chunk is complete."""
        ch = self.world.chunks.get(key)
        part = self._part.get(key)
        if part is not None and part[4] != lite:
            self._drop_part(key)
            part = None
        if part is None:
            todo0 = list(ch["m"].items()) if ch else []
            if ch and ch.get("t") and getattr(self.world, "version", 0) >= TREES_FROM:
                todo0.append(("trees", None))                    # the world stores only tree positions: their meshes are made here (src/treegen.py)
            part = self._part[key] = [{}, todo0, 1e9, -1e9, lite]
        out, todo = part[0], part[1]
        processed = False
        while todo:
            if deadline is not None and (out or processed) and time.perf_counter() > deadline:
                return False
            mat, (off, n) = todo.pop(0) if todo[0][0] != "trees" else (todo.pop(0)[0], (0, 0))
            processed = True
            if mat == "trees":
                if not self._tree_models(key, ch, self._tree_want(key, lite), out, part, deadline):
                    todo.insert(0, ("trees", None))              # unfinished: carries on next frame
                    return False
                continue
            pos, uv, col = self.world.mesh_arrays(off, n)
            if n:
                ys = pos[:, 1]
                part[2], part[3] = min(part[2], float(ys.min())), max(part[3], float(ys.max()))
            if mat == 6 and ("graf" not in self.tex or lite):
                continue                                     # atlas failed: no decals rather than facade-textured ones
            if (mat == 18 and (lite or self.detail < 1)) or (mat == 19 and (lite or self.detail < 2)):
                continue                                     # facade relief / clutter (src/archkit.py TIER): detail setting, far ring
            if self.world.broken or getattr(self.world, "broken_extra", None):
                pos = self.world.hide_broken(pos, ch.get("bb"))
            m = gl3d.make_model(pos, uv, col)
            if m is not None:
                names = ("A", "B", "roof", "white", "panel", "house", "graf", "brick", "conc", "concg", "cream", "mix") + gl3d.SURF_NAMES + ("glaz", "glaz")
                gl3d.set_texture(m, self.tex.get(names[mat]) or self.tex["A"])
                if lite:
                    pass
                elif mat == 3 and getattr(self.world, "roads3d", False):
                    gl3d.apply_road_detail(m)                        # manholes, cracks, patches, oil on the asphalt
                elif mat == 3:
                    gl3d.object_detail(m, "concrete", key[0] * 7 + key[1] * 11)
                elif mat in (0, 1, 2, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
                    gl3d.apply_building_detail(m, mat)               # facade / roof relief towards the sun, grit, streaks
                surfacepack.bind(m)
                out[mat] = m
        del self._part[key]
        self.stale.discard(key)
        old = self.meshes.get(key)
        if old:                                                  # low-quality set swapped for the full one only now
            for m in old[0].values():
                gl3d.free_model(m)
        y0, y1 = part[2], part[3]
        self.meshes[key] = [out, self.frame]
        (self.lite_keys.add if lite else self.lite_keys.discard)(key)      # only now: a half-done upgrade must stay pending
        if len(part) > 5:
            self.tree_lvl[key] = part[5]
        bb = ch.get("bb") if ch else None
        self.recent.append((self.mesh_loaded + 1, bb))         # (the sun shadow redraws only for new meshes near it)
        if len(self.recent) > 256:
            del self.recent[:128]
        self.sph[key] = _sphere(bb[0], bb[1], bb[2], bb[3], y0, y1) if bb is not None and y1 >= y0 else None
        self.mesh_loaded += 1
        return True

    def _tree_models(self, key, ch, lvl, out, part, deadline=None):
        """Runtime trees of one chunk: mat 20 = trunks / limbs / crown lumps, 21 = alpha-cut leaf sprites, 22 = a plain crown blob that
        only the sun-shadow pass draws (sprites would cast square shadows).  The trees are made TREE_SLICE at a time and the job stops once
        `deadline` has passed (a dense chunk at the finest level takes ~90 ms in one go); returns True when the meshes are in `out`."""
        job = self._tj.get(key)
        if job is None or job["lvl"] != lvl:
            w = self.world
            tr = w.trees[np.asarray(ch["t"], np.int64)]
            S = w.chunk
            own = (np.floor(tr[:, 0] / S) == key[0]) & (np.floor(tr[:, 1] / S) == key[1])      # a tree near an edge is listed by both chunks
            tr = tr[own]
            if not len(tr) or gl3d.tree_pack() is None:
                self._tj.pop(key, None)
                return True
            rows = np.c_[tr, w.th_v(tr[:, 0], tr[:, 1])].tolist()
            ts = getattr(w, "tree_state", None)
            if ts:                                           # felled trees are gone (they lie as models of their own), shed ones are bare
                sd = getattr(w, "shedding", {})
                rows = [r + [ts.get((r[0], r[1]), (0,))[0] == 1] for r in rows if ts.get((r[0], r[1]), (0,))[0] != 2 and (r[0], r[1]) not in sd]
            job = self._tj[key] = {"lvl": lvl, "rows": rows, "i": 0, "p": {20: [], 21: [], 22: []}}
        rows, acc = job["rows"], job["p"]
        while True:                                              # at least one slice per call, so a starved chunk still gets there
            i0 = job["i"]
            sl = rows[i0:i0 + TREE_SLICE]
            job["i"] = i0 + len(sl)
            sol, crd = treegen.place(sl, lvl)
            got = {20: sol, 21: crd, 22: treegen.place([r for r in sl if len(r) < 6 or not r[5]], 1)[0] if lvl > TREE_FAR else None}
            for mat, arr in got.items():
                if arr is not None:
                    acc[mat].append(arr)
            if job["i"] >= len(rows):
                break
            if deadline is not None and time.perf_counter() > deadline:
                return False
        del self._tj[key]
        w = self.world
        for mat, lst in acc.items():
            if not lst:
                continue
            pos, uv, col = (np.concatenate([a[k] for a in lst]) for k in range(3))
            part[2], part[3] = min(part[2], float(pos[:, 1].min())), max(part[3], float(pos[:, 1].max()))
            m = gl3d.tree_model(pos, uv, col)
            if m is not None:
                out[mat] = m
        if len(part) > 5:
            part[5] = lvl
        else:
            part.append(lvl)
        return True

    def _tree_want(self, key, lite):
        """Tree detail level a chunk should have: by its distance from the avatar (the same for the top-down and the chase view)."""
        if self.focus is None:
            return TREE_FAR if lite else TREE_NEAR
        S, (fx, fy) = self.world.chunk, self.focus
        gap = math.hypot(max(key[0] * S - fx, 0.0, fx - (key[0] + 1) * S), max(key[1] * S - fy, 0.0, fy - (key[1] + 1) * S))
        for r, lv in TREE_RINGS:
            if gap < r:
                return lv
        return TREE_FAR

    def _retree(self, key, lvl, deadline=None):
        """Swap only the tree meshes of a loaded chunk for another level of detail (the rest of the chunk stays)."""
        ch = self.world.chunks.get(key)
        e = self.meshes.get(key)
        if not ch or not e:
            return True
        new, tmp = {}, [None, None, 1e9, -1e9]
        if not self._tree_models(key, ch, lvl, new, tmp, deadline):
            return False
        for mat in (20, 21, 22):
            old = e[0].pop(mat, None)
            if old is not None:
                gl3d.free_model(old)
        e[0].update(new)
        self.tree_lvl[key] = lvl
        self.mesh_loaded += 1                                    # (the sun shadow redraws for them)
        self.recent.append((self.mesh_loaded, ch.get("bb")))
        return True

    def _drop_part(self, key):
        self._tj.pop(key, None)
        part = self._part.pop(key, None)
        if part:
            for m in part[0].values():
                gl3d.free_model(m)

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
                self.stale.add(key)                              # old meshes stay on screen until the new ones are complete (freeing them made the chunk blink out)
                self._drop_part(key)

    def tree_changed(self, x, y):
        """A tree at (x, y) was stripped or felled: redo the tree meshes of its chunk (the rest of the chunk stays)."""
        if getattr(self.world, "version", 0) < TREES_FROM:
            return self.reload_near(x, y)
        S = self.world.chunk
        key = (int(x // S), int(y // S))
        self._tj.pop(key, None)
        self._tree_dirty.add(key)

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
            up = key in self.meshes and ((key in self.lite_keys and key not in lite) or key in self.stale)           # came close: swap the low-quality meshes for full ones
            need_m = want_meshes and (key not in self.meshes or up) and key not in self.bad and key in self.world.chunks
            if key in self.ground:
                self.ground[key][1] = self.frame
            if key in self.meshes:
                self.meshes[key][1] = self.frame
            if key in self.meshes and key not in self._part and self.tree_lvl.get(key) is not None:
                want = self._tree_want(key, key in lite)
                run = self._lite_run[key] = self._lite_run.get(key, 0) + 1 if want < self.tree_lvl[key] else 0
                dirty = key in self._tree_dirty
                if (dirty or (self.tree_lvl[key] != want and (want > self.tree_lvl[key] or run >= TREE_DOWN_AFTER))) and not need_m:
                    if n and (time.perf_counter() - t0) * 1000 > budget_ms:
                        break
                    if not self._retree(key, self.tree_lvl[key] if dirty else want, t0 + budget_ms / 1000.0):      # approaching: sprites at once; receding: blobs after a while
                        break                                    # unfinished: carries on next frame
                    self._tree_dirty.discard(key)
                    n += 1
            if not (need_g or need_m):
                continue
            if n and (time.perf_counter() - t0) * 1000 > budget_ms:
                break
            try:
                if need_g and not self._bake(key, t0 + budget_ms / 1000.0):
                    break                                        # unfinished: carries on next frame
                if need_m:
                    if need_g and (time.perf_counter() - t0) * 1000 > budget_ms:       # the bake alone used the frame's budget: meshes next frame
                        break
                    if not self._load_meshes(key, key in lite, t0 + budget_ms / 1000.0):
                        break                                    # unfinished: carries on next frame
            except Exception as e:  # noqa: BLE001 - never let one chunk kill the game
                self.errors += 1
                self.bad.add(key)
                if self._baking is not None and self._baking[0] == key:
                    self._abandon_bake()
                print(f"[stream] chunk {key} failed: {e}")
            n += 1
        if self._baking is not None and self._baking[0] not in wanted:
            self._abandon_bake()                                 # walked away from a half-painted chunk
        for key in [k for k in self._part if k not in wanted]:
            self._drop_part(key)                                 # walked away from a half-loaded chunk
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
                    self.tree_lvl.pop(key, None)
                    self._lite_run.pop(key, None)
                    self._tj.pop(key, None)

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
def bake_overview(world, size, path, progress=None, loading=None):
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
        pass_(f_roads, [r for r in world.roads if not r["bridge"] and not r.get("worn")], 160, "roads", 0.25, 0.55)
        pass_(f_roads, [r for r in world.roads if r["bridge"]], 160, "bridges", 0.55, 0.6)
        pass_(f_bld, world.buildings, 128, "buildings", 0.6, 0.85)
        pass_(f_trees, world.trees[::3], 500, "trees", 0.85, 0.92)
        P(0.93, "saving the map")
        img = rl.load_image_from_texture(rt.texture)
        rl.image_flip_vertical(img)
        def save_png():
            try:
                rl.export_image(img, png)
                with open(png + ".ok", "w") as f:
                    f.write(str(os.path.getsize(png)))
            except Exception:  # noqa: BLE001 - cache is optional
                pass

        if loading is None:
            save_png()
        else:
            loading(save_png)
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
