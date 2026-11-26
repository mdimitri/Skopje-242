"""3D helpers: mesh upload, procedural textures, procedural car / pedestrian / pickup models (with dents)."""
import math
import random
from functools import lru_cache

import numpy as np

import characterart
import surfacepack
import weaponart
import pyray as rl

ffi = rl.ffi
SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)


# ------------------------------------------------------------------ mesh upload
def make_model(pos, uv, col):
    """numpy arrays -> raylib Model living in VRAM (CPU copies are dropped)."""
    pos = np.ascontiguousarray(pos, dtype=np.float32)
    uv = np.ascontiguousarray(uv, dtype=np.float32)
    col = np.ascontiguousarray(col, dtype=np.uint8)
    n = len(pos) - len(pos) % 3
    if n <= 0:
        return None
    m = rl.Mesh()
    m.vertexCount = n
    m.triangleCount = n // 3
    m.vertices = ffi.cast("float *", ffi.from_buffer(pos))
    m.texcoords = ffi.cast("float *", ffi.from_buffer(uv))
    m.colors = ffi.cast("unsigned char *", ffi.from_buffer(col))
    rl.upload_mesh(ffi.addressof(m), False)
    m.vertices = ffi.NULL
    m.texcoords = ffi.NULL
    m.colors = ffi.NULL
    return rl.load_model_from_mesh(m)


def set_texture(model, tex):
    model.materials[0].maps[0].texture = tex


def free_model(model):
    if model is not None:
        surfacepack.forget(model)
        rl.unload_model(model)


# ------------------------------------------------------------------ procedural textures
def _to_texture(rt, mipmaps=True):
    img = rl.load_image_from_texture(rt.texture)
    rl.image_flip_vertical(img)
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.unload_render_texture(rt)
    if mipmaps:
        rl.gen_texture_mipmaps(tex)
        rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_REPEAT)
    return tex


def _speckle(rng, n, size, base_alpha=18):
    for _ in range(n):
        v = rng.choice((0, 0, 255))
        rl.draw_rectangle(rng.randrange(size), rng.randrange(size), rng.choice((1, 2, 3)), rng.choice((1, 2)),
                          rl.Color(v, v, v, rng.randrange(6, base_alpha)))


def _grime(rng, S, amount=1.0, peel=True):
    """Skopje wear drawn over a facade tile: rain streaks, damp blotches, soot above sills, peeled plaster, cracks."""
    for _ in range(int(7 * amount)):                                           # damp / water blotches
        rl.draw_circle(rng.randrange(S), rng.randrange(S), rng.uniform(6, 20), rl.Color(70, 60, 48, rng.randrange(8, 22)))
    for _ in range(int(16 * amount)):                                          # long rain streaks running down
        x, y0 = rng.randrange(S), rng.randrange(S // 2)
        w = rng.choice((1, 1, 2, 3))
        rl.draw_rectangle(x, y0, w, rng.randrange(20, S - y0), rl.Color(54, 48, 42, rng.randrange(10, 34)))
    rl.draw_rectangle_gradient_v(0, S - 26, S, 26, rl.Color(60, 54, 46, 0), rl.Color(60, 54, 46, int(60 * amount)))   # grimy base
    for _ in range(int(2 * amount) + 1 if peel else 0):                          # plaster fallen off: bare concrete / brick
        x, y = rng.randrange(S - 20), rng.randrange(S - 20)
        w, h = rng.randrange(8, 24), rng.randrange(6, 18)
        rl.draw_rectangle(x, y, w, h, rl.Color(150, 138, 124, 235) if rng.random() < .6 else rl.Color(168, 100, 78, 235))
        rl.draw_rectangle_lines(x - 1, y - 1, w + 2, h + 2, rl.Color(90, 80, 70, 140))
    for _ in range(int(3 * amount)):                                           # cracks
        x, y = rng.randrange(S), rng.randrange(S)
        for _k in range(7):
            nx_, ny_ = x + rng.randrange(-5, 6), y + rng.randrange(2, 9)
            rl.draw_line(x, y, nx_, ny_, rl.Color(36, 32, 28, 120))
            x, y = nx_, ny_


def build_textures(tick=None):
    """facade A (residential windows), facade B (office glass ribbon), roof, one white pixel. Greyscale-ish: tinted by vertex colour."""
    rng = random.Random(7)
    S = 128
    tex = {}
    # --- facade A
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(244, 240, 232, 255))
    _speckle(rng, 260, S)
    rl.draw_rectangle(0, 20, S, 6, rl.Color(205, 202, 196, 255))              # slab edge / shadow band
    rl.draw_rectangle(30, 30, 68, 74, rl.Color(250, 250, 250, 255))           # frame
    rl.draw_rectangle_gradient_v(35, 35, 58, 64, rl.Color(52, 70, 92, 255), rl.Color(120, 146, 172, 255))
    rl.draw_rectangle(62, 35, 4, 64, rl.Color(236, 236, 236, 255))            # mullion
    rl.draw_rectangle(26, 104, 76, 5, rl.Color(190, 186, 180, 255))           # sill
    rl.draw_rectangle(38, 38, 16, 22, rl.Color(255, 255, 255, 50))            # glass glint
    rl.end_texture_mode()
    tex["A"] = _to_texture(rt)
    if tick:
        tick(1 / 10)
    # --- facade B (office ribbon)
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(220, 224, 227, 255))
    rl.draw_rectangle_gradient_v(0, 22, S, 84, rl.Color(40, 78, 96, 255), rl.Color(110, 160, 182, 255))
    for x in (0, 42, 84):
        rl.draw_rectangle(x, 22, 4, 84, rl.Color(214, 218, 222, 255))
    rl.draw_rectangle(0, 18, S, 5, rl.Color(200, 204, 208, 255))
    rl.draw_rectangle(0, 106, S, 4, rl.Color(190, 194, 198, 255))
    rl.draw_rectangle(10, 30, 26, 16, rl.Color(255, 255, 255, 40))
    _grime(rng, S, 1.1)
    rl.end_texture_mode()
    tex["B"] = _to_texture(rt)
    if tick:
        tick(2 / 10)
    # --- roof (tar paper / tiles)
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(226, 226, 226, 255))
    for i in range(0, S, 16):
        rl.draw_line(0, i, S, i, rl.Color(0, 0, 0, 26))
        off = 8 if (i // 16) % 2 else 0
        for j in range(off, S, 16):
            rl.draw_line(j, i, j, i + 16, rl.Color(0, 0, 0, 14))
    _speckle(rng, 420, S, 30)
    rl.end_texture_mode()
    tex["roof"] = _to_texture(rt)
    if tick:
        tick(3 / 10)
    # --- Skopje socialist prefab block (Аеродром, Карпош): panel joints, loggia, odd closed-in balconies, AC unit
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(198, 193, 184, 255))
    _speckle(rng, 320, S, 24)
    for k in range(0, S, 4):                                                 # rain streaks under the sills
        rl.draw_line(k, 100, k + rng.randrange(-1, 2), 100 + rng.randrange(6, 26), rl.Color(80, 76, 70, rng.randrange(6, 22)))
    rl.draw_rectangle(0, 0, S, 3, rl.Color(150, 146, 140, 255))               # horizontal panel joint
    rl.draw_rectangle(0, 0, 3, S, rl.Color(160, 156, 150, 255))               # vertical joint
    rl.draw_rectangle(14, 18, 100, 62, rl.Color(64, 66, 70, 255))             # deep loggia
    rl.draw_rectangle_gradient_v(18, 22, 44, 54, rl.Color(56, 74, 94, 255), rl.Color(118, 140, 162, 255))
    rl.draw_rectangle(66, 22, 44, 54, rl.Color(232, 228, 214, 255))           # neighbour closed theirs in (PVC)
    rl.draw_rectangle(70, 26, 16, 44, rl.Color(120, 150, 170, 255))
    rl.draw_rectangle(90, 26, 16, 44, rl.Color(120, 150, 170, 255))
    rl.draw_rectangle(10, 80, 108, 22, rl.Color(196, 192, 184, 255))          # balcony parapet slab
    for x in range(14, 62, 6):
        rl.draw_rectangle(x, 82, 2, 18, rl.Color(120, 118, 114, 255))
    rl.draw_rectangle(24, 106, 20, 12, rl.Color(236, 236, 236, 255))         # AC unit
    rl.draw_rectangle(27, 109, 14, 6, rl.Color(170, 170, 170, 255))
    _grime(rng, S, 1.5)
    rl.end_texture_mode()
    tex["panel"] = _to_texture(rt)
    if tick:
        tick(4 / 10)
    # --- family house (Влае, Ѓорче, Butel): warm stucco, roller-shutter windows, a bit of bare brick
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(230, 218, 198, 255))
    _speckle(rng, 380, S, 26)
    if True:                                                                # unfinished corner: bare red brick
        for y in range(0, 40, 8):
            for x in range((y // 8) % 2 * 8, 40, 16):
                rl.draw_rectangle(x, y + 88, 15, 7, rl.Color(200, 120, 90, 255))
    rl.draw_rectangle(36, 26, 56, 60, rl.Color(250, 250, 248, 255))          # frame
    rl.draw_rectangle_gradient_v(41, 31, 46, 50, rl.Color(60, 74, 90, 255), rl.Color(130, 150, 168, 255))
    rl.draw_rectangle(41, 31, 46, 20, rl.Color(214, 206, 192, 255))          # roller shutter half down
    for y in range(31, 51, 3):
        rl.draw_line(41, y, 87, y, rl.Color(170, 160, 146, 255))
    rl.draw_rectangle(32, 86, 64, 5, rl.Color(200, 190, 176, 255))           # sill
    rl.draw_rectangle(98, 30, 6, 40, rl.Color(110, 70, 50, 255))             # wooden shutter
    rl.draw_rectangle(24, 30, 6, 40, rl.Color(110, 70, 50, 255))
    _grime(rng, S, 1.4)
    rl.end_texture_mode()
    tex["house"] = _to_texture(rt)
    if tick:
        tick(5 / 10)
    # --- residential mid-rise "A" gets balconies with railings and laundry, the Skopje classic
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(224, 216, 202, 255))
    _speckle(rng, 300, S, 22)
    rl.draw_rectangle(0, 20, S, 5, rl.Color(204, 198, 188, 255))
    rl.draw_rectangle(22, 28, 50, 58, rl.Color(250, 250, 250, 255))
    rl.draw_rectangle_gradient_v(26, 32, 42, 50, rl.Color(52, 70, 92, 255), rl.Color(120, 146, 172, 255))
    rl.draw_rectangle(46, 32, 3, 50, rl.Color(236, 236, 236, 255))
    rl.draw_rectangle(80, 30, 34, 56, rl.Color(70, 68, 66, 255))             # balcony door
    rl.draw_rectangle(76, 86, 44, 4, rl.Color(180, 176, 170, 255))           # balcony slab
    for x in range(76, 120, 5):
        rl.draw_rectangle(x, 70, 1, 16, rl.Color(60, 60, 62, 255))           # railing bars
    rl.draw_rectangle(76, 68, 44, 2, rl.Color(60, 60, 62, 255))
    rl.draw_line(78, 62, 118, 62, rl.Color(90, 90, 90, 255))                 # laundry line
    for x, c in ((82, (200, 60, 60)), (92, (240, 240, 240)), (104, (70, 110, 190))):
        rl.draw_rectangle(x, 62, 7, 10, rl.Color(*c, 255))
    rl.draw_rectangle(18, 98, 22, 12, rl.Color(234, 234, 234, 255))          # AC unit
    _grime(rng, S, 1.3)
    rl.end_texture_mode()
    tex["A"] = _to_texture(rt)
    if tick:
        tick(6 / 10)
    # --- roof: weathered tar / tiles with patches, cracks and stains
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(222, 220, 216, 255))
    for i in range(0, S, 16):
        rl.draw_line(0, i, S, i, rl.Color(0, 0, 0, 30))
        off = 8 if (i // 16) % 2 else 0
        for j in range(off, S, 16):
            rl.draw_line(j, i, j, i + 16, rl.Color(0, 0, 0, 16))
    for _ in range(3):                                                      # repair patches / water stains
        rl.draw_circle(rng.randrange(S), rng.randrange(S), rng.uniform(8, 22), rl.Color(60, 58, 54, rng.randrange(6, 14)))
    for _ in range(5):                                                      # cracks
        x, y = rng.randrange(S), rng.randrange(S)
        for _k in range(8):
            nx_, ny_ = x + rng.randrange(-9, 10), y + rng.randrange(-9, 10)
            rl.draw_line(x, y, nx_, ny_, rl.Color(30, 28, 26, 90))
            x, y = nx_, ny_
    _speckle(rng, 520, S, 34)
    rl.end_texture_mode()
    tex["roof"] = _to_texture(rt)
    if tick:
        tick(7 / 10)
    # --- Skopje reference photos (Kapishtec, Aerodrom, Karposh, Chair): red brick with white bands, concrete towers with coloured infill, cream loggia blocks
    def _win(x, y, w, h, frame=(244, 244, 240), glass=((52, 70, 92), (120, 146, 172))):
        rl.draw_rectangle(x - 2, y - 2, w + 4, h + 4, rl.Color(*frame, 255))
        rl.draw_rectangle_gradient_v(x, y, w, h, rl.Color(*glass[0], 255), rl.Color(*glass[1], 255))
        rl.draw_rectangle(x + w // 2 - 1, y, 2, h, rl.Color(*frame, 255))
        rl.draw_rectangle(x - 3, y + h + 2, w + 6, 3, rl.Color(200, 196, 188, 255))

    rt = rl.load_render_texture(S, S)                                          # red brick block, white cornice band
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(188, 92, 64, 255))
    for y in range(0, S, 6):
        rl.draw_line(0, y, S, y, rl.Color(228, 196, 176, 90))
        for x in range((y // 6) % 2 * 8, S, 16):
            rl.draw_line(x, y, x, y + 6, rl.Color(228, 196, 176, 70))
            if rng.random() < .3:
                rl.draw_rectangle(x + 1, y + 1, 14, 5, rl.Color(150, 66, 44, 70))
    _win(44, 30, 40, 52)
    rl.draw_rectangle(0, S - 5, S, 5, rl.Color(236, 230, 220, 255))             # white cornice
    _grime(rng, S, 1.0, peel=False)
    rl.end_texture_mode()
    tex["brick"] = _to_texture(rt)
    rt = rl.load_render_texture(S, S)                                          # grey concrete tower, brown infill panel, pilaster, round balcony edge
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(176, 172, 162, 255))
    _speckle(rng, 420, S, 26)
    rl.draw_rectangle(0, 0, 18, S, rl.Color(196, 192, 182, 255))                # pilaster
    rl.draw_rectangle(18, 0, 3, S, rl.Color(120, 116, 108, 255))
    rl.draw_rectangle(30, 8, 80, 104, rl.Color(150, 98, 64, 255))               # coloured infill
    _win(46, 34, 48, 40, glass=((70, 84, 100), (130, 150, 166)))
    rl.draw_rectangle(0, 116, S, 12, rl.Color(160, 156, 146, 255))              # slab edge
    _grime(rng, S, 1.3)
    rl.end_texture_mode()
    tex["conc"] = _to_texture(rt)
    rt = rl.load_render_texture(S, S)                                          # same tower, faded green panels
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(164, 158, 146, 255))
    _speckle(rng, 420, S, 26)
    rl.draw_rectangle(0, 0, 18, S, rl.Color(184, 178, 166, 255))
    rl.draw_rectangle(18, 0, 3, S, rl.Color(112, 108, 98, 255))
    rl.draw_rectangle(30, 8, 80, 52, rl.Color(114, 142, 116, 255))
    rl.draw_rectangle(30, 62, 80, 50, rl.Color(142, 168, 138, 255))
    _win(46, 34, 48, 40, glass=((70, 84, 100), (130, 150, 166)))
    rl.draw_rectangle(0, 116, S, 12, rl.Color(150, 146, 136, 255))
    _grime(rng, S, 1.3)
    rl.end_texture_mode()
    tex["concg"] = _to_texture(rt)
    rt = rl.load_render_texture(S, S)                                          # cream block: two glazed-in loggias, blinds, laundry
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(232, 226, 208, 255))
    _speckle(rng, 300, S, 22)
    rl.draw_rectangle(0, 0, S, 4, rl.Color(204, 198, 184, 255))
    for x0 in (10, 68):
        rl.draw_rectangle(x0, 18, 50, 72, rl.Color(236, 236, 232, 255))
        for k in range(3):
            rl.draw_rectangle_gradient_v(x0 + 3 + k * 16, 21, 14, 66, rl.Color(80, 100, 120, 255), rl.Color(150, 172, 188, 255))
        rl.draw_rectangle(x0, 52, 50, 3, rl.Color(236, 236, 232, 255))
        if rng.random() < .6:
            rl.draw_rectangle(x0 + 3 + rng.randrange(3) * 16, 21, 14, rng.randrange(14, 40), rl.Color(206, 190, 150, 255))   # blind
    rl.draw_rectangle(8, 94, 112, 4, rl.Color(196, 190, 176, 255))
    rl.draw_line(14, 104, 54, 104, rl.Color(90, 90, 90, 255))
    for x, c in ((18, (200, 60, 60)), (30, (240, 240, 240)), (42, (70, 110, 190))):
        rl.draw_rectangle(x, 104, 8, 11, rl.Color(*c, 255))
    _grime(rng, S, 1.1)
    rl.end_texture_mode()
    tex["cream"] = _to_texture(rt)
    if tick:
        tick(7.5 / 10)
    rt = rl.load_render_texture(S, S)                                          # white concrete body with brick piers and a frame (Karposh / Chair mixed blocks)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(222, 218, 208, 255))
    _speckle(rng, 360, S, 24)
    rl.draw_rectangle(0, 0, 30, S, rl.Color(176, 92, 66, 255))                  # brick pier
    for y in range(0, S, 6):
        rl.draw_line(0, y, 30, y, rl.Color(228, 196, 176, 90))
    rl.draw_rectangle(30, 0, 4, S, rl.Color(150, 146, 138, 255))
    _win(46, 30, 60, 40)
    rl.draw_rectangle(34, 96, 94, 8, rl.Color(184, 180, 170, 255))              # concrete spandrel
    rl.draw_rectangle(0, 112, S, 5, rl.Color(160, 156, 146, 255))
    _grime(rng, S, 1.2)
    rl.end_texture_mode()
    tex["mix"] = _to_texture(rt)
    if tick:
        tick(7.8 / 10)
    try:
        import graffiti
        tex["graf"] = graffiti.build_atlas()
        if tick:
            tick(8 / 10)
    except Exception:  # noqa: BLE001 - no graffiti rather than no game
        import traceback
        print("[graffiti] atlas failed:\n" + traceback.format_exc())
    img = rl.gen_image_color(4, 4, rl.WHITE)
    tex["white"] = rl.load_texture_from_image(img)
    if tick:
        tick(9 / 10)
    rl.unload_image(img)
    try:
        for name, arr in surface_textures().items():
            tex[name] = _np_texture(arr)
    except Exception:  # noqa: BLE001 - the photo-fitted facades fall back to nothing rather than the game to nothing
        import traceback
        print("[gfx] surface textures failed:\n" + traceback.format_exc())
    return tex


# names of the procedural surfaces of the photo-fitted facades (build_world.MAT_SURF order)
SURF_NAMES = ("plas", "concw", "tilew", "brkw", "metw", "glaz")


def _np_texture(arr):
    rgba = np.ascontiguousarray(np.concatenate([arr, np.full(arr.shape[:2] + (1,), 255, np.uint8)], 2))
    img = rl.Image(ffi.from_buffer(rgba), arr.shape[1], arr.shape[0], 1, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    t = rl.load_texture_from_image(img)
    rl.gen_texture_mipmaps(t)
    rl.set_texture_filter(t, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(t, rl.TEXTURE_WRAP_REPEAT)
    return t


def _noise(rng, n, cell):
    """Smooth value noise (n, n) in 0..1 with features of `cell` px, tileable."""
    k = max(1, n // cell)
    g = rng.random((k, k))
    x = np.arange(n) * k / n
    i0 = np.floor(x).astype(int)
    t = x - i0
    t = t * t * (3 - 2 * t)
    i1 = (i0 + 1) % k
    a = g[i0][:, i0] * (1 - t)[None, :] + g[i0][:, i1] * t[None, :]
    b = g[i1][:, i0] * (1 - t)[None, :] + g[i1][:, i1] * t[None, :]
    return a * (1 - t)[:, None] + b * t[:, None]


def surface_textures(n=256):
    """Wall finishes for the photo-fitted facades, 4 m x 4 m per repeat (64 px/m), near-white so the fitted colour is the vertex
    colour; the building shader turns their light / dark grain into bump and roughness.  Subtle on purpose.  Plus 'glaz':
    left half glazing (dark: glossy by day, lit at night like every facade's glass), right half smooth paint (frames, rails, AC)."""
    rng = np.random.default_rng(242)
    fine = rng.random((n, n))
    mid = _noise(rng, n, 16)
    big = _noise(rng, n, 64)
    out = {}
    plas = 0.84 + 0.035 * (fine - 0.5) + 0.04 * (mid - 0.5) + 0.03 * (big - 0.5)          # trowelled render
    out["plas"] = plas
    pores = (rng.random((n, n)) > 0.985) * -0.10
    conc = 0.80 + 0.03 * (fine - 0.5) + 0.05 * (mid - 0.5) + 0.05 * (big - 0.5) + pores
    conc[(np.arange(n) % 96) < 1, :] -= 0.06                                               # formwork / panel joints every 1.5 m
    conc[:, (np.arange(n) % 192) < 1] -= 0.06
    out["concw"] = conc
    tile = 0.86 + 0.02 * (fine - 0.5) + 0.03 * (rng.random((n // 16, n // 16)).repeat(16, 0).repeat(16, 1) - 0.5)
    tile[(np.arange(n) % 16) < 1, :] -= 0.12                                               # 0.25 m ceramic tiles, grout lines
    tile[:, (np.arange(n) % 16) < 1] -= 0.12
    out["tilew"] = tile
    brk = np.zeros((n, n))
    ch, cw = 5, 16                                                                         # 7.8 cm courses, 25 cm bricks
    for r in range(0, n, ch):
        off = (r // ch % 2) * cw // 2
        for c in range(-cw, n, cw):
            v = 0.80 + 0.08 * (rng.random() - 0.5)
            brk[r:r + ch, max(0, c + off):max(0, c + off + cw)] = v
    brk += 0.03 * (fine - 0.5)
    brk[(np.arange(n) % ch) == 0, :] = 0.66                                                # mortar
    for r in range(0, n, ch):
        off = (r // ch % 2) * cw // 2
        brk[r:r + ch, [(c + off) % n for c in range(0, n, cw)]] = 0.66
    out["brkw"] = brk
    met = 0.86 + 0.012 * (fine - 0.5) + 0.02 * (big - 0.5)
    met[:, (np.arange(n) % 64) < 1] -= 0.10                                                # 1 m cladding panels
    met[(np.arange(n) % 128) < 1, :] -= 0.08
    out["metw"] = met
    gl = np.empty((n, n))
    yy = np.linspace(0, 1, n)[:, None]
    gl[:, :n // 2] = 0.24 + 0.04 * yy + 0.02 * (big[:, :n // 2] - 0.5)                    # glazing: lum < 0.18..0.36 = glass (lit at night)
    gl[:, n // 2:] = 0.88 + 0.015 * (fine[:, n // 2:] - 0.5)                                  # paint
    out["glaz"] = gl
    return {k: np.clip(v[..., None] * 255, 0, 255).astype(np.uint8).repeat(3, 2) for k, v in out.items()}


# ------------------------------------------------------------------ geometry helpers
def _shade(n):
    return 0.52 + 0.55 * np.clip(n @ SUN, 0, None)


def grid_face(o, du, dv, nu, nv):
    """Quad grid: points o + i/nu*du + j/nv*dv -> triangle vertices (N,3)."""
    o, du, dv = np.array(o, np.float32), np.array(du, np.float32), np.array(dv, np.float32)
    P = o + (np.arange(nu + 1) / nu)[:, None, None] * du + (np.arange(nv + 1) / nv)[None, :, None] * dv
    p00, p10, p01, p11 = P[:-1, :-1], P[1:, :-1], P[:-1, 1:], P[1:, 1:]
    return np.stack((p00, p10, p11, p00, p11, p01), axis=2).reshape(-1, 3).astype(np.float32)


def box_faces(cx, cy, cz, sx, sy, sz, nx=1, ny=1, nz=1, bottom=False):
    """Box centred at x,z with base at y=cy; returns dict face-> (vertices, normal)."""
    x0, x1, z0, z1, y0, y1 = cx - sx / 2, cx + sx / 2, cz - sz / 2, cz + sz / 2, cy, cy + sy
    f = {
        "top": (grid_face((x0, y1, z0), (sx, 0, 0), (0, 0, sz), nx, nz), (0, 1, 0)),
        "front": (grid_face((x1, y0, z0), (0, 0, sz), (0, sy, 0), nz, ny), (1, 0, 0)),
        "back": (grid_face((x0, y0, z1), (0, 0, -sz), (0, sy, 0), nz, ny), (-1, 0, 0)),
        "left": (grid_face((x0, y0, z0), (sx, 0, 0), (0, sy, 0), nx, ny), (0, 0, -1)),
        "right": (grid_face((x1, y0, z1), (-sx, 0, 0), (0, sy, 0), nx, ny), (0, 0, 1)),
    }
    if bottom:
        f["bottom"] = (grid_face((x0, y0, z0), (sx, 0, 0), (0, 0, sz), nx, nz), (0, -1, 0))
    return f


# ------------------------------------------------------------------ car model
import vehicles as V
import carbody

CAR_DIMS = V.DIMS
CAR_COLORS = [(190, 40, 40), (40, 80, 170), (230, 230, 232), (30, 30, 34), (150, 152, 158), (215, 190, 40),
              (40, 120, 70), (200, 110, 40), (110, 40, 130), (90, 150, 170), (140, 100, 70), (170, 170, 120)]
GLASS = (36, 48, 62)
# (cabin length frac, cabin centre frac, front taper, rear taper, side taper, side windows)
_CAB = {"hatch": (0.56, -0.07, 0.26, 0.07, 0.12, 2), "sedan": (0.46, -0.06, 0.24, 0.22, 0.14, 2),
        "taxi": (0.46, -0.06, 0.24, 0.22, 0.14, 2), "mini": (0.58, -0.04, 0.22, 0.06, 0.12, 2),
        "suv": (0.74, -0.10, 0.10, 0.04, 0.07, 2), "van": (0.88, 0.0, 0.10, 0.02, 0.04, 3),
        "pickup": (0.36, 0.10, 0.22, 0.05, 0.10, 1), "bus": (0.985, 0.0, 0.03, 0.0, 0.0, 6),
        "wagon": (0.70, -0.12, 0.12, 0.05, 0.12, 2), "limo": (0.60, -0.04, 0.20, 0.20, 0.14, 4),
        "truck": (0.24, 0.38, 0.10, 0.0, 0.05, 1), "tractor": (0.32, -0.12, 0.06, 0.0, 0.05, 1)}


# real-car silhouettes (round 9): (hood drop m, trunk drop m, plan rounding 0..1, windshield rake +, rear rake +, roof pinch +)
_ERA = {
    "boxy": (0.07, 0.04, 0.12, 0.0, 0.0, 0.0),        # 80s Yugo / Golf 2 / Lada / 190 / Kadett: straight lines
    "modern": (0.22, 0.10, 0.50, 0.12, 0.06, 0.04),   # 2000s Golf 5 / Passat B6 / Astra G: low nose, raked glass
    "bubble": (0.16, 0.12, 0.85, 0.12, 0.14, 0.10),   # Fico / Trabant / 2CV / 126: round little things
    "brick": (0.02, 0.0, 0.06, -0.04, -0.04, 0.0),    # Niva / G-class / Hummer: a box with wheels
    "soft": (0.14, 0.06, 0.35, 0.06, 0.04, 0.02),     # 90s Uno / Clio / Corolla / Megane
}
_ERA_OF = {}
_ROUND_LAMPS = {"Zastava Yugo", "Zastava 101 Skala", "Zastava Koral", "Golf Dvojka", "Lada Niva", "Fico", "Trabant 601",
               "Pachuvka 2CV", "Renault 4 Katrca", "Fiat 126 Peglica", "Moskvich 412", "Wartburg 353"}
for _n, _e in (("Zastava Yugo", "boxy"), ("Golf Dvojka", "boxy"), ("Lada Niva", "brick"), ("Mercedes 190", "boxy"),
               ("Taxi Zlatna Zolta", "boxy"), ("Fico", "bubble"), ("Zastava 101 Skala", "boxy"), ("Zastava Koral", "boxy"),
               ("Lada Samara", "boxy"), ("Lada 1500", "boxy"), ("Moskvich 412", "boxy"), ("Trabant 601", "bubble"),
               ("Wartburg 353", "boxy"), ("Skoda Octavia Karavan", "modern"), ("Pachuvka 2CV", "bubble"),
               ("Renault 4 Katrca", "boxy"), ("Fiat 126 Peglica", "bubble"), ("Fiat Punto", "soft"), ("Fiat Uno", "boxy"),
               ("Opel Kadett", "boxy"), ("Opel Astra Karavan", "soft"), ("Audi 80 Bachok", "boxy"), ("BMW E36 Bavarka", "soft"),
               ("BMW X5 Chorbadzija", "modern"), ("Mercedes 124 Taksist", "boxy"), ("Mercedes S Mafijash", "modern"),
               ("Mercedes G Politichar", "brick"), ("Passat Dijaspora", "soft"), ("Golf Trojka Gastarbajter", "soft"),
               ("Renault Clio", "soft"), ("Toyota Corolla", "soft"), ("Land Cruiser Lovec", "brick"),
               ("Nissan Qashqai", "modern"), ("Dacia Duster", "modern"), ("Dacia Logan", "soft"), ("Kia Picanto", "bubble"),
               ("Tesla Elon", "modern"), ("Hummer Patriot", "brick"), ("Smart Sitnichka", "bubble"),
               ("Cayenne od Germanija", "modern"), ("Range Rover Ortak", "brick"), ("Policiska Skoda", "modern"),
               ("Golf Petka TDI", "modern"), ("Golf Shestka Uvezen", "modern"), ("Passat B5 Karavan", "soft"),
               ("Passat B6 TDI", "modern"), ("Audi A4 Avant Shvajcarska", "modern"), ("Audi A6 Nemachka", "modern"),
               ("BMW E46 Tjunirana", "modern"), ("BMW E39 520d", "soft"), ("Mercedes C Klasa W203", "modern"),
               ("Mercedes E Klasa W211", "modern"), ("Opel Astra G", "soft"), ("Opel Corsa C", "modern"),
               ("Peugeot 206", "modern"), ("Peugeot 307 SW", "modern"), ("Fiat Stilo", "modern"), ("Skoda Fabia", "modern"),
               ("Skoda Octavia Taksi", "modern"), ("Seat Leon Kupra", "modern"), ("Hyundai Getz", "modern"),
               ("Toyota Yaris", "bubble"), ("Ford Focus Karavan", "modern"), ("Volvo V70 Dedov", "boxy"),
               ("Golf Chetvorka Bez Registracija", "soft"), ("Svadbarska Limuzina", "modern")):
    _ERA_OF[_n] = _e


def _shape_body(v, kind, st, L, W, y0, belt, cx, cl):
    """Bend the lower-body box into the real car's silhouette: sloping bonnet / boot lid, rounded corners."""
    era = _ERA.get(_ERA_OF.get(V.IDS[kind]))
    if era is None and st == "bus":                      # buses: rounded plan corners and a slightly shorter, rounded nose / tail
        era = (0.0, 0.0, 1.3)
    if era is None:
        return v
    hood, trunk, rnd = era[0], era[1], era[2]
    v = v.copy()
    xf, xr = cx + cl / 2, cx - cl / 2                    # windshield foot / rear window foot
    top = np.clip((v[:, 1] - y0) / max(0.05, belt - y0), 0, 1)
    fwd = np.clip((v[:, 0] - xf) / max(0.1, L / 2 - xf), 0, 1)
    back = np.clip((xr - v[:, 0]) / max(0.1, xr + L / 2), 0, 1)
    if st in ("sedan", "taxi", "limo"):                  # boot lid only on three-box cars
        v[:, 1] -= trunk * back ** 1.4 * top
    else:
        v[:, 1] -= trunk * 0.4 * back ** 2 * top
    v[:, 1] -= hood * fwd ** 1.3 * top
    u = np.abs(v[:, 0]) / (L / 2)
    v[:, 2] *= 1 - rnd * 0.16 * np.clip((u - 0.62) / 0.38, 0, 1) ** 2          # rounded corners seen from above
    v[:, 0] *= 1 - rnd * 0.05 * top ** 2 * np.clip((u - 0.5) / 0.5, 0, 1)        # rounded nose / tail profile
    return v


def _wheel_face(vs, cs, cx, cy, z, R, rim, hub):
    """One wheel face, built from a handful of triangles in layers (z steps of 4 mm): ('steel', n) a pressed-steel wheel with a hubcap and n
    ventilation slots, ('alloy', n) n tapered spokes over a dark dish with a centre cap, ('multi', n) the same with a bright outer lip,
    ('truck', n) a flat disc with n hand holes and a centre nut.  Every pattern is rotation-visible and cheap (25-55 triangles)."""
    kind, n = rim[:2]
    if kind in ("golf_steel", "w201_15_hole", "e36_style_14"):
        carbody.draw_period_rim(vs, cs, cx, cy, z, R, rim)
        return
    hub = np.asarray(hub, np.float32)
    r = R * (rim[2] if len(rim) == 3 else 0.80)

    def tri(p0, p1, p2, zz, col):
        vs.extend(((p0[0], p0[1], zz), (p1[0], p1[1], zz), (p2[0], p2[1], zz)))
        cs.extend([col] * 3)

    def pt(rr, a):
        return (cx + rr * math.cos(a), cy + rr * math.sin(a))

    def quad(r0, r1, a0, a1, b0, b1, zz, col):                 # inner edge r0 from a0..a1, outer edge r1 from b0..b1
        p00, p01, p10, p11 = pt(r0, a0), pt(r0, a1), pt(r1, b0), pt(r1, b1)
        tri(p00, p10, p11, zz, col)
        tri(p00, p11, p01, zz, col)

    def disc(rr, col, zz, m=12):
        for k in range(m):
            tri((cx, cy), pt(rr, 2 * math.pi * k / m), pt(rr, 2 * math.pi * (k + 1) / m), zz, col)

    tau = 2 * math.pi
    if kind == "spoked":
        for i in range(n):
            a = tau * i / n
            quad(r * 0.15, r * 1.12, a - 0.12, a + 0.12, a - 0.016, a + 0.016, z, hub)
        disc(r * 0.19, hub * 1.12, z + 0.003, 8)
    elif kind == "steel":
        disc(r, hub * 0.62, z)
        disc(r * 0.52, hub * 1.08, z + 0.004, 8)
        for k in range(n):
            a = tau * (k + 0.5) / n
            quad(r * 0.66, r * 0.93, a - 0.11, a + 0.11, a - 0.14, a + 0.14, z + 0.004, hub * 0.2)
    elif kind == "hubcap":
        disc(r, hub*0.89, z)
        for k in range(n):
            a = tau*(k+0.5)/n
            quad(r*0.60, r*0.86, a-0.10, a+0.10, a-0.15, a+0.15, z+0.004, hub*0.38)
        disc(r*0.40, hub*1.07, z+0.01, 8)
    elif kind in ("alloy", "multi"):
        disc(r, hub * 0.22, z)
        if kind == "multi":
            for k in range(12):                                  # the bright outer lip
                a0, a1 = tau * k / 12, tau * (k + 1) / 12
                quad(r * 0.9, r, a0, a1, a0, a1, z + 0.002, hub * 0.95)
        wi, wo = (0.35, 0.62) if kind == "alloy" else (0.26, 0.40)
        for k in range(n):
            a, s = tau * k / n, tau / n
            quad(r * 0.2, r * 0.9, a - s * wi / 2, a + s * wi / 2, a - s * wo / 2, a + s * wo / 2, z + 0.004, hub)
        disc(r * 0.24, hub * 0.8, z + 0.008, 6)
    else:                                                        # truck / bus
        disc(r, hub * 0.8, z)
        for k in range(n):
            a = tau * (k + 0.5) / n
            quad(r * 0.46, r * 0.8, a - 0.16, a + 0.16, a - 0.2, a + 0.2, z + 0.004, hub * 0.18)
        disc(r * 0.26, hub * 1.0, z + 0.008, 6)


def _cyl(cx, cy, cz, R, wd, tyre, hub, sides=12, rim=("alloy", 5), face=0):
    """Wheel with its axis along z. Returns (verts, colours).  face = +1 / -1: only that side gets the wheel-face design (the other
    one is against the car); 0 = both (a front wheel model that is drawn on either side)."""
    vs, cs = [], []
    za, zb = cz - wd / 2, cz + wd / 2
    spoked = rim[0] == "spoked"
    for i in range(sides):
        a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
        p0 = (cx + R * math.cos(a0), cy + R * math.sin(a0))
        p1 = (cx + R * math.cos(a1), cy + R * math.sin(a1))
        am = (a0 + a1) / 2
        sh = 0.55 + 0.5 * max(0.0, math.cos(am) * 0.4 + math.sin(am) * 0.9)
        vs += [(p0[0], p0[1], za), (p1[0], p1[1], za), (p1[0], p1[1], zb), (p0[0], p0[1], za), (p1[0], p1[1], zb), (p0[0], p0[1], zb)]
        cs += [tyre * sh] * 6
        for z in ((za, zb) if face == 0 else ((zb,) if face > 0 else (za,))):        # tyre sidewalls
            if spoked:
                r0 = (cx + (p0[0]-cx)*0.88, cy + (p0[1]-cy)*0.88, z)
                r1 = (cx + (p1[0]-cx)*0.88, cy + (p1[1]-cy)*0.88, z)
                vs.extend((r0, p0+(z,), p1+(z,), r0, p1+(z,), r1))
                cs.extend([tyre*0.85] * 6)
            else:
                vs += [(cx, cy, z), p0 + (z,), p1 + (z,)]
                cs += [tyre * 0.8] * 3
    for z, sg in ((zb + 0.012, 1), (za - 0.012, -1)):
        if face in (0, sg):
            n0 = len(vs)
            _wheel_face(vs, cs, cx, cy, 0.0, R, rim, hub)
            for i in range(n0, len(vs)):                         # lift the layers off the tyre, away from the wheel centre plane
                x_, y_, zz = vs[i]
                vs[i] = (x_, y_, z + sg * zz)
    return np.array(vs, np.float32), np.array(cs, np.float32)


_GLYPH = {"П": ("1111", "1001", "1001", "1001", "1001"), "О": ("0110", "1001", "1001", "1001", "0110"),
          "Л": ("0111", "0101", "0101", "0101", "1001"), "И": ("1001", "1001", "1011", "1101", "1001"),
          "Ц": ("1001", "1001", "1001", "1111", "0001"), "Ј": ("0011", "0001", "0001", "1001", "0110"),
          "А": ("0110", "1001", "1111", "1001", "1001")}


def _truck_cab(parts, box, quad, A, gl, body_c, L, W, y0, belt, roof, cl, ex):
    """Cab-over lorry cab: raked windscreen, side windows, grille and lamps, bumper, mirrors, steps, tanks, exhaust."""
    def poly(pts, n, col):
        v = np.array([q for k in range(1, len(pts) - 1) for q in (pts[0], pts[k], pts[k + 1])], np.float32)
        parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1)), True))

    xf, cw = L / 2, W * 0.98
    yb, ys, yt, rk = belt - 0.05, belt + 0.85, roof, 0.45
    rk = {"armytruck": 0.12, "fire": 0.28, "tanker": 0.38, "garbage": 0.34,
          "mixer": 0.50, "cargo": 0.35, "semi": 0.48}.get(ex, rk)
    xr = xf - cl
    prof = [(xf - 0.02, yb), (xf - 0.02, ys), (xf - 0.02 - rk, yt), (xr, yt), (xr, yb)]
    dark, chrome = (30, 30, 34), (196, 198, 204)
    for s in (-1, 1):
        poly([(x, y, s * cw / 2) for x, y in prof], (0, 0, s), body_c)
        zz = s * (cw / 2 + 0.012)
        poly([(xf - 0.5, ys + 0.12, zz), (xf - 1.45, ys + 0.12, zz), (xf - 1.45, yt - 0.2, zz), (xf - 0.72, yt - 0.2, zz)], (0, 0, s), gl((0, 0, s)))
        quad((xf - 1.5, yb + 0.05, zz), (0.03, 0, 0), (0, yt - yb - 0.1, 0), (0, 0, s), dark)                 # door seam
        quad((xf - 1.38, ys - 0.05, zz + 0.004), (0.18, 0, 0), (0, 0.05, 0), (0, 0, s), chrome)               # handle
        box(xf - 0.28, ys - 0.2, s * (cw / 2 + 0.2), 0.08, 0.6, 0.16, dark)                                   # mirror
        box(xf - 0.8, y0 + 0.02, s * (cw / 2 + 0.05), 0.5, 0.07, 0.22, dark)                                  # step
        box(xr - 0.6, y0 - 0.02, s * (W / 2 - 0.2), 1.1, 0.55, 0.36, (190, 192, 198))                         # fuel tank
        quad((xf - 0.02 - 0.02, yb + 0.4, s * cw * 0.40 - 0.12 + 0.0), (0, 0, 0.24), (0, 0.2, 0), (1, 0, 0), (255, 244, 180))   # headlamp
        quad((xf + 0.01, ys - 0.38, s * cw * 0.40 - 0.12), (0, 0, 0.24), (0, 0.22, 0), (1, 0, 0), (255, 244, 180))
    quad((xf - 0.02, yb, -cw / 2), (0, 0, cw), (0, ys - yb, 0), (1, 0, 0), body_c)                            # lower front
    quad((xf + 0.012, yb + 0.22, -cw * 0.3), (0, 0, cw * 0.6), (0, ys - yb - 0.4, 0), (1, 0, 0), (28, 28, 32), 2, 1)   # grille
    bars = {"armytruck": 5, "fire": 3, "cargo": 2, "semi": 3, "tanker": 4, "garbage": 2, "mixer": 3}.get(ex, 3)
    trim = chrome if ex in ("fire", "tanker") else (77, 81, 85)
    for k in range(bars):
        quad((xf + 0.016, yb + 0.27 + k * (0.39 / bars), -cw * 0.3), (0, 0, cw * 0.6), (0, 0.032, 0), (1, 0, 0), trim)
    if ex in ("cargo", "semi", "garbage", "mixer"):
        quad((xf+0.022, yb+0.51, -cw*0.26), (0,0,cw*0.52), (0,0.036,0), (1,0,0), (185,192,200))
    poly([(xf - 0.02, ys, -cw / 2), (xf - 0.02, ys, cw / 2), (xf - 0.02 - rk, yt, cw / 2), (xf - 0.02 - rk, yt, -cw / 2)], (0.9, 0.45, 0), body_c)   # screen surround
    g0 = (xf - 0.005, ys + 0.1, cw / 2 - 0.1)
    poly([(g0[0], g0[1], -g0[2]), (g0[0], g0[1], g0[2]), (g0[0] - rk + 0.07, yt - 0.12, g0[2]), (g0[0] - rk + 0.07, yt - 0.12, -g0[2])], (0.9, 0.45, 0), gl((1, 0.4, 0)))
    poly([(xf - 0.02 - rk, yt, -cw / 2), (xf - 0.02 - rk, yt, cw / 2), (xr, yt, cw / 2), (xr, yt, -cw / 2)], (0, 1, 0), body_c * 1.08)
    quad((xr - 0.004, yb, -cw / 2), (0, 0, cw), (0, yt - yb, 0), (-1, 0, 0), body_c * 0.9)
    box(xf + 0.03, y0, 0, 0.28, 0.4, cw + 0.06, (74, 76, 82))                                                 # bumper
    quad((xf + 0.172, y0 + 0.08, -0.25), (0, 0, 0.5), (0, 0.14, 0), (1, 0, 0), (236, 236, 230))
    box(xf - 0.2, yt, 0, 0.35, 0.1, cw * 0.92, tuple(body_c * 0.85))                                          # sun visor
    for z in (-0.6, -0.3, 0.0, 0.3, 0.6):
        box(xf - 0.25, yt + 0.1, z, 0.08, 0.1, 0.16, (255, 170, 30))                                          # roof marker lamps
    if ex in ("semi", "tanker"):
        box(xr + 0.25, yt, 0, 0.7, 0.55, cw * 0.78, tuple(body_c * 1.05))                                     # roof deflector
        for s in (-1, 1):
            box(xr - 0.14, belt, s * (cw / 2 - 0.15), 0.12, 2.3, 0.12, chrome)                                # exhaust stacks
    for s in (-1, 1):                                                                                          # mudflaps behind the last axle
        box(-L * 0.36 - 0.55, y0 - 0.05, s * (W / 2 - 0.3), 0.04, 0.45, 0.5, dark)


def _crew_bed(ex, xb, x1, belt, W, top_h, box, quad):
    """Load bed of the road-crew trucks (crews.py): the paint truck's tanks and spray boom, the arrow-board truck's lamp panel and
    crash cushion, the cone truck's stacked cones.  xb..x1 is the bed's length (x), belt its floor, W the body width."""
    cl = x1 - xb
    mid = (x1 + xb) / 2
    dark, amber, white, red = (44, 46, 52), (255, 168, 24), (244, 244, 240), (214, 40, 36)
    box(mid, belt, 0, cl, 0.16, W * 0.96, (52, 54, 60))                                          # flat bed
    for s in (-1, 1):                                                                            # rails along the bed
        box(mid, belt + 0.16, s * W * 0.46, cl, 0.22, 0.05, (230, 190, 30))
    for k in range(6):                                                                           # chevron panel on the tail: red / white
        cc = red if k % 2 == 0 else white
        quad((xb - 0.014, belt + 0.1 + k * 0.1, -W * 0.48), (0, 0, W * 0.96), (0, 0.1, 0), (-1, 0, 0), cc)
    if ex == "linepaint":
        for k, (zc, col) in enumerate(((-0.55, white), (0.55, (240, 200, 40)))):                 # two paint tanks, white and yellow
            box(xb + cl * 0.30, belt + 0.16, zc, cl * 0.38, 0.95, 0.9, (150, 154, 160))
            box(xb + cl * 0.30, belt + 0.62, zc, cl * 0.385, 0.3, 0.905, col)
            box(xb + cl * 0.30, belt + 1.11, zc, 0.5, 0.12, 0.5, (96, 100, 108))                 # filler hatch
        box(xb + cl * 0.68, belt + 0.16, -0.5, cl * 0.22, 0.7, 0.8, (70, 74, 80))                # glass-bead hopper
        box(xb + cl * 0.68, belt + 0.16, 0.45, cl * 0.22, 0.5, 0.7, (216, 106, 28))              # compressor
        box(xb + cl * 0.86, belt + 0.16, -W * 0.62, 0.7, 0.07, W * 0.5 + 0.4, (78, 80, 86))      # spray boom: out to the left (the lane line), low
        box(xb + cl * 0.86, belt - 0.3, -W * 1.0 - 0.1, 0.18, 0.5, 0.18, (30, 30, 34))            # gun and nozzle over the line being painted
        box(xb + cl * 0.86 - 0.3, belt - 0.12, -W * 1.0 - 0.1, 0.16, 0.2, 0.16, (240, 240, 236))
    elif ex == "arrowboard":
        box(xb + 0.55, belt + 0.16, 0, 0.28, 1.0, 0.28, (80, 84, 90))                           # mast
        pw, ph, y0 = W * 0.9, 1.3, belt + 1.1
        box(xb + 0.45, y0, 0, 0.12, ph, pw, (22, 22, 24))                                       # the black board, facing backwards
        lamps = [(-0.38 + k * 0.1, 0.0) for k in range(8)] + [(0.30 - k * 0.07, 0.07 * (k + 1) * s_) for k in range(3) for s_ in (-1, 1)]
        for zr, yr in lamps:                                                                    # arrow of amber lamps pointing to the right
            quad((xb + 0.385, y0 + ph * 0.5 + yr * 1.4 - 0.05, zr * pw - 0.05), (0, 0, 0.1), (0, 0.1, 0), (-1, 0, 0), amber)
        box(xb - 0.5, y0 - 0.7, 0, 0.9, 0.7, W * 0.9, (236, 190, 30))                           # crash cushion hung on the tail
        for k in range(4):
            quad((xb - 0.955, y0 - 0.7, -W * 0.45 + k * W * 0.225), (0, 0, W * 0.112), (0, 0.7, 0), (-1, 0, 0), (30, 30, 34))
    elif ex == "conetruck":
        for col_i in range(7):                                                                  # stacked cones in their rack
            xx = xb + 0.7 + col_i * (cl - 1.5) / 6
            for zz in (-0.62, 0.0, 0.62):
                box(xx, belt + 0.16, zz, 0.36, 0.34, 0.36, (240, 110, 30))
                box(xx, belt + 0.50, zz, 0.26, 0.34, 0.26, (240, 110, 30))
                box(xx, belt + 0.66, zz, 0.28, 0.07, 0.28, (240, 240, 236))
        for s in (-1, 1):
            box((x1 + xb) / 2, belt + 0.16, s * W * 0.46, cl * 0.96, 0.8, 0.04, (150, 154, 160))  # rack sides
        box(xb + 0.35, belt + 0.16, 0, 0.7, 0.05, W * 0.8, (36, 38, 42))                         # the roller chute off the back
        box(xb + 0.3, belt + 0.16, 0, 0.2, 1.3, 0.2, (80, 84, 90))                               # mast of the arrow board over the cones
        pw = W * 0.9
        box(xb + 0.25, belt + 1.4, 0, 0.1, 1.0, pw, (22, 22, 24))                                # the black board, facing backwards
        for zr in [-0.38 + k * 0.1 for k in range(8)] + [0.30, 0.23, 0.16]:
            for yr in ((0.0,) if zr < 0.3 else (-0.07 * (0.37 - zr) * 10, 0.07 * (0.37 - zr) * 10)):
                quad((xb + 0.195, belt + 1.9 + yr - 0.05, zr * pw - 0.05), (0, 0, 0.1), (0, 0.1, 0), (-1, 0, 0), (255, 168, 24))


def _extras(kind, st, ex, L, W, y0, belt, roof, top_h, cx, cl, cw, body_c, accent, parts, box, quad, cab_ref=None):
    """Body-specific add-ons: cargo boxes, sirens, ladders, luggage, logos. `box`/`quad` are car_arrays' helpers."""
    xb, xf = -L / 2, L / 2
    bar = lambda x, z, c1, c2: (box(x, top_h if st == "truck" else roof, z - 0.3, 0.3, 0.14, 0.55, c1),
                                box(x, top_h if st == "truck" else roof, z + 0.3, 0.3, 0.14, 0.55, c2))
    if ex == "semi":                                                       # tractor unit: fifth-wheel plate on the chassis
        box(xb + 1.35, belt, 0, 1.5, 0.14, W * 0.8, (40, 42, 46))
        return
    if st == "truck":                                                      # cargo box behind the cab
        x1 = cx - cl / 2 - 0.12
        cgl, cgx = x1 - xb, (x1 + xb) / 2
        col = tuple(body_c)
        if ex == "garbage":
            col = (40, 130, 70)
        if ex == "armytruck":
            col = (70, 82, 48)                                             # canvas tarp over the cargo bed
        if ex == "tanker":
            tank_top = top_h - 0.09
            tank_bottom = belt + 0.13
            mid = (tank_top + tank_bottom) / 2
            rings = [
                _ring(W*0.45*scale, mid + (tank_bottom-mid)*scale, mid+(tank_top-mid)*scale, x, 16)
                for x, scale in ((xb+0.10, 0.86), (xb+0.39, 1.0), (x1-0.27, 1.0), (x1-0.025, 0.86))
            ]
            shell = _loft(rings)
            _tri_parts(shell, lambda q: (164, 42, 46) if abs(q[1]-mid) < 0.19 else (196, 200, 208),
                       parts, lambda q: (q[0], mid, 0), True)
            for ix, sign in ((0, -1), (-1, 1)):
                ring = rings[ix]
                _tri_parts([(ring[0], a, b) for a, b in zip(ring[1:], ring[2:])], lambda q: (191, 196, 203),
                           parts, lambda q: (q[0]-sign, mid, 0))
            box(cgx, belt, 0, cgl*0.85, 0.22, W*0.55, (70, 73, 79))
            for x in (cgx-cgl*0.22, cgx+cgl*0.22):
                box(x, tank_top-0.04, 0, 0.33, 0.12, 0.47, (124, 129, 137))
        elif ex == "mixer":                                               # drum: a revolved, rear-high cone-cylinder with a spiral stripe
            u_r = ((0.0, 0.55), (0.12, 0.88), (0.35, 0.95), (0.65, 0.95), (0.88, 0.7), (1.0, 0.3))
            xa, xz = xb + 0.25, x1 - 0.25
            n = 14
            ring = lambda u, r: [(xa + (xz - xa) * (1 - u), belt + 1.15 + 0.2 * u + r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n) * 1.0) for k in range(n)]
            rings = [ring(1 - u, r) for u, r in u_r]
            for i in range(len(rings) - 1):
                for k in range(n):
                    k2 = (k + 1) % n
                    a, b, c2, d = rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]
                    mid = np.array([(a[j] + c2[j]) / 2 for j in range(3)], np.float32)
                    nn = np.array((0.0, mid[1] - (belt + 1.2), mid[2]), np.float32)
                    nn /= max(1e-6, float(np.linalg.norm(nn)))
                    stripe = (k + i) % 4 == 0
                    cc = np.array((240, 240, 238) if stripe else (236, 140, 40), np.float32) * _shade(nn)
                    v = np.array([a, b, c2, a, c2, d], np.float32)
                    parts.append((v, np.tile(cc, (6, 1)), True))
            box(xb + 0.5, belt + 0.55, 0, 1.0, 1.0, W * 0.6, (60, 62, 66))        # drum frame / hopper
            box(xz - 0.15, belt + 0.05, 0, 0.5, 0.7, W * 0.7, (200, 120, 36))      # drum support behind the cab
        elif ex in ("linepaint", "arrowboard", "conetruck"):
            _crew_bed(ex, xb, x1, belt, W, top_h, box, quad)
        else:
            from_h = top_h - belt if ex != "fire" else 1.5
            for name, (v, n) in box_faces(cgx, belt, 0, cgl, from_h, W * 0.96, 6, 3, 3).items():
                parts.append((v, np.tile(np.array(col, np.float32) * _shade(np.array(n, np.float32)), (len(v), 1)), True))
            if ex == "armytruck":                                          # tarp hoops showing through the canvas, tailgate
                for k in range(5):
                    xk = xb + 0.3 + k * (cgl - 0.6) / 4
                    for sd in (-1, 1):
                        quad((xk - 0.04, belt + 0.1, sd * (W * 0.48 + 0.012)), (0.08, 0, 0), (0, from_h - 0.15, 0), (0, 0, sd), (52, 62, 36))
                    quad((xk - 0.04, top_h + 0.004, -W * 0.48), (0.08, 0, 0), (0, 0, W * 0.96), (0, 1, 0), (52, 62, 36))
                quad((xb - 0.012, belt, -W * 0.48), (0, 0, W * 0.96), (0, 0.5, 0), (-1, 0, 0), (60, 70, 42))
            if ex == "garbage":
                box(xb - 0.1, belt + 0.1, 0, 0.5, 1.6, W * 0.8, (30, 90, 50))
                for s in (-1, 1):
                    quad((xb + 0.4, belt + 0.8, s * (W * 0.48 + 0.01)), (cgl - 0.8, 0, 0), (0, 0.25, 0), (0, 0, s), (30, 100, 56))
            if ex == "fire":
                for s in (-1, 1):
                    box(cgx, belt + 1.5, s * 0.4, cgl * 0.82, 0.06, 0.08, (210, 210, 214))
                for k in range(6):
                    box(xb + 0.8 + k * (cgl - 1.2) / 5, belt + 1.5, 0, 0.06, 0.05, 0.8, (210, 210, 214))
                for s in (-1, 1):
                    for k in range(3):
                        quad((xb + 0.5 + k * cgl * 0.3, belt + 0.1, s * (W * 0.48 + 0.01)), (cgl * 0.27, 0, 0), (0, 1.1, 0), (0, 0, s), (176, 178, 184))
        if ex == "fire":
            bar(cx, 0.0, (230, 40, 40), (40, 90, 230))
        elif ex in ("linepaint", "arrowboard", "conetruck"):
            bar(cx, 0.0, (255, 168, 24), (255, 168, 24))                                   # amber beacons
        return
    if st == "tractor":
        box(xf - 0.8, belt + 0.5, 0, 0.12, 1.0, 0.12, (30, 30, 34))        # exhaust
        for s_ in (-1, 1):                                                  # rear mudguards over the big wheels, a step below them
            box(-L * 0.28, 1.78, s_ * (W / 2 - 0.12), 1.5, 0.07, 0.5, tuple(body_c * 0.9))
        for s in (-1, 1):
            box(xf + 0.02, belt - 0.2, s * 0.4, 0.06, 0.2, 0.25, (255, 244, 180))
        return
    if ex == "roofload":                                                   # Gastarbeiter luggage + mattress
        box(cx - 0.1, roof, 0.0, cl * 0.55, 0.42, cw * 0.55, (120, 84, 50))
        box(cx + 0.55, roof, 0.18, 0.55, 0.32, 0.5, (86, 100, 124))
        box(cx - 0.2, roof + 0.42, 0.0, cl * 0.7, 0.2, cw * 0.6, (206, 214, 232))
        for k in (-0.5, 0.0, 0.5):
            quad((cx + k * cl * 0.4, roof + 0.62, -cw * 0.3), (0.05, 0, 0), (0, 0, cw * 0.6), (0, 1, 0), (40, 40, 44))
    elif ex == "marica":                                                   # dark blue police van, ПОЛИЦИЈА in big white letters on both sides
        bar(cx, 0.0, (220, 30, 30), (40, 80, 230))
        cell, gap = 0.09, 0.09
        word = [_GLYPH[ch] for ch in "ПОЛИЦИЈА"]
        x0 = -0.5 * len(word) * (4 * cell + gap) - 0.3
        for sd in (-1, 1):
            for gi, g in enumerate(word):
                for r, row in enumerate(g):
                    for cI, bit in enumerate(row):
                        if bit == "1":
                            cc = cI if sd == 1 else 3 - cI                  # the left side is read the other way round:
                            gj = gi if sd == 1 else len(word) - 1 - gi      # the letters mirrored and in the reverse order
                            quad((x0 + gj * (4 * cell + gap) + cc * cell, belt - 0.08 - (r + 1) * cell, sd * (W / 2 + 0.014)), (cell, 0, 0), (0, cell, 0), (0, 0, sd), (246, 246, 250))
    elif ex == "army":                                                     # olive drab: jerrycans on the tail, whip antenna, black grille guard
        box(xb - 0.12, y0 + 0.25, -W * 0.25, 0.16, 0.45, 0.3, (60, 70, 42))
        box(xb - 0.12, y0 + 0.25, W * 0.25, 0.16, 0.45, 0.3, (60, 70, 42))
        box(xb + 0.25, roof, W * 0.4, 0.04, 1.6, 0.04, (24, 24, 26))
        box(xf + 0.12, y0 + 0.05, 0, 0.08, belt - y0 - 0.05, W * 0.8, (30, 32, 30))
        for s in (-1, 1):                                                  # small Macedonian flag on the doors
            quad((cx - 0.15, belt - 0.42, s * (W / 2 + 0.014)), (0.36, 0, 0), (0, 0.22, 0), (0, 0, s), (200, 30, 30))
            quad((cx - 0.01, belt - 0.35, s * (W / 2 + 0.016)), (0.08, 0, 0), (0, 0.08, 0), (0, 0, s), (250, 210, 30))
    elif ex == "police":
        bar(cx, 0.0, (220, 30, 30), (40, 80, 230))
        for s in (-1, 1):
            quad((xb + 0.3, belt - 0.5, s * (W / 2 + 0.012)), (L - 0.6, 0, 0), (0, 0.34, 0), (0, 0, s), (30, 70, 180))
    elif ex == "ambulance":
        for s in (-1, 1):
            quad((xb + 0.2, belt - 0.4, s * (W / 2 + 0.012)), (L - 0.4, 0, 0), (0, 0.22, 0), (0, 0, s), (200, 30, 30))
            quad((cx - 0.5, belt + 0.55, s * (W / 2 + 0.014)), (1.0, 0, 0), (0, 0.28, 0), (0, 0, s), (210, 30, 30))
            quad((cx - 0.14, belt + 0.19, s * (W / 2 + 0.014)), (0.28, 0, 0), (0, 0.9, 0), (0, 0, s), (210, 30, 30))
        quad((cx - 0.6, roof + 0.004, -0.15), (1.2, 0, 0), (0, 0, 0.3), (0, 1, 0), (210, 30, 30))
        quad((cx - 0.15, roof + 0.005, -0.6), (0.3, 0, 0), (0, 0, 1.2), (0, 1, 0), (210, 30, 30))
        bar(cx + cl * 0.35, 0.0, (40, 90, 230), (40, 90, 230))
    elif ex == "tow":
        box((xb + (cx - cl / 2)) / 2, belt, 0, (cx - cl / 2) - xb, 0.12, W * 0.96, (70, 72, 78))
        box(xb + 0.6, belt + 0.12, 0, 0.2, 1.3, 0.2, (60, 62, 68))
        box(cx, roof, 0, 0.25, 0.12, 0.5, (255, 170, 20))
    elif ex == "post":
        for s in (-1, 1):
            quad((xb + 0.2, belt - 0.3, s * (W / 2 + 0.012)), (L - 0.4, 0, 0), (0, 0.32, 0), (0, 0, s), (200, 30, 30))
    elif ex in ("logo", "burek", "icecream"):
        lc = {"logo": (240, 130, 30), "burek": (150, 80, 40), "icecream": (230, 90, 140)}[ex]
        for s in (-1, 1):
            quad((cx - cl * 0.3, belt + 0.1, s * (cw / 2 + 0.02)), (cl * 0.6, 0, 0), (0, roof - belt - 0.3, 0), (0, 0, s), lc)
        if ex == "burek":
            box(cx, roof, 0, 0.9, 0.35, 0.9, (196, 130, 60))
        if ex == "icecream":
            box(cx, roof, 0, 0.5, 0.5, 0.5, (240, 220, 160))
            box(cx, roof + 0.5, 0, 0.7, 0.3, 0.7, (250, 250, 250))
    elif ex == "spoiler":
        box(xb + 0.3, belt + 0.02, 0, 0.3, 0.07, W * 0.86, (20, 20, 24))
        for s in (-1, 1):
            box(xb + 0.3, belt - 0.05, s * W * 0.3, 0.1, 0.1, 0.06, (20, 20, 24))
        quad((xb + 0.1, belt + 0.004, -0.14), (L * 0.28, 0, 0), (0, 0, 0.28), (0, 1, 0), (240, 240, 240))
    elif ex == "ribbons":
        for k in (-1, 0, 1):
            box(xf - 0.9, belt + 0.01, k * 0.45, 1.2, 0.04, 0.12, (250, 250, 250))
        box(xf - 1.5, belt + 0.04, 0, 0.3, 0.2, 0.3, (240, 150, 190))
        quad((xb + 0.1, belt + 0.004, -0.5), (0.8, 0, 0), (0, 0, 1.0), (0, 1, 0), (242, 214, 228))
    elif ex == "coach":
        for s in (-1, 1):
            quad((xb + 0.3, y0 + 0.1, s * (W / 2 + 0.012)), (L - 0.6, 0, 0), (0, 0.4, 0), (0, 0, s), (200, 40, 40))
        box(cx - 2.0, roof, 0, 1.6, 0.25, 1.4, (190, 192, 196))


_BIKE_RIMS = {"bike": ("spoked", 12), "kick": ("alloy", 3), "moped": ("spoked", 9), "scooter": ("alloy", 3)}


def _bike_parts(ex, body_c, A, box, quad, parts, bake=True):
    """Two-wheelers (x forward, y up, z right), no rider. ex = bike | moped | scooter | kick."""
    dark, steel, tyre, hub = (36, 36, 40), (150, 152, 158), A((24, 24, 26)), A((170, 170, 176))
    bc = tuple(body_c)

    def wheel(x, r, wd):
        if bake:                                                  # else the renderer draws them spinning (bike_wheels)
            v, c = _cyl(x, r, 0.0, r, wd, tyre, hub, rim=_BIKE_RIMS[ex])
            parts.append((v, c, False))

    if ex == "bike":
        wheel(0.62, 0.34, 0.05)
        wheel(-0.62, 0.34, 0.05)
        for a, b, radius, color in (
            ((-0.32, 0.73, 0), (0.47, 0.79, 0), 0.022, bc),
            ((-0.24, 0.33, 0), (0.47, 0.78, 0), 0.026, bc),
            ((-0.24, 0.33, 0), (-0.32, 0.73, 0), 0.022, bc),
            ((-0.62, 0.34, 0), (-0.32, 0.73, 0), 0.018, bc),
            ((-0.62, 0.34, 0), (-0.24, 0.33, 0), 0.018, bc),
            ((0.62, 0.34, 0), (0.47, 0.78, 0), 0.022, steel),
        ):
            _tri_parts(_tube(a, b, radius, 4), lambda q: color, parts)
        box(0.5, 0.88, 0, 0.05, 0.05, 0.5, dark)                  # handlebar
        box(0.5, 0.64, 0, 0.04, 0.26, 0.04, steel)                # stem
        box(-0.32, 0.73, 0, 0.029, 0.13, 0.029, steel)
        box(-0.3, 0.855, 0, 0.26, 0.07, 0.12, dark)                # saddle
        box(0.02, 0.28, 0, 0.18, 0.18, 0.05, steel)               # chainring
        box(0.6, 0.72, 0, 0.08, 0.1, 0.11, (236, 232, 210))       # lamp (one, on the centre line, like a real bike)
        quad((0.642, 0.73, -0.045), (0, 0, 0.09), (0, 0.08, 0), (1, 0, 0), (255, 244, 180))
        box(-0.44, 0.74, 0, 0.05, 0.06, 0.09, (210, 30, 30))      # rear reflector / tail light under the saddle
    elif ex == "kick":
        wheel(0.46, 0.14, 0.05)
        wheel(-0.46, 0.14, 0.05)
        box(-0.025, 0.121, 0, 0.79, 0.065, 0.157, dark)
        box(-0.029, 0.187, 0, 0.67, 0.009, 0.145, (57, 60, 66))                 # deck
        _tri_parts(_tube((0.46, 0.14, 0), (0.33, 1.05, 0), 0.026, 6), lambda q: steel, parts)
        box(0.33, 1.02, 0, 0.05, 0.05, 0.5, dark)                 # bars
        box(-0.5, 0.22, 0, 0.18, 0.04, 0.2, bc)                   # brake plate
        box(0.37, 0.9, 0, 0.05, 0.08, 0.1, (236, 232, 210))       # lamp on the column
        quad((0.397, 0.91, -0.04), (0, 0, 0.08), (0, 0.06, 0), (1, 0, 0), (255, 244, 180))
        box(-0.58, 0.18, 0, 0.03, 0.06, 0.14, (210, 30, 30))      # tail light on the brake plate
    else:
        mo = ex == "moped"
        r = 0.27 if mo else 0.24
        wheel(0.68, r, 0.1)
        wheel(-0.68, r, 0.1)
        if mo:
            box(-0.05, 0.33, 0, 0.58, 0.071, 0.11, dark)
            box(-0.36, 0.63, 0, 0.46, 0.12, 0.16, bc)             # fuel tank below the saddle
            for side in (-1,1):
                quad((-0.66, r, side*0.080), (0.31,0.36,0), (0.037,0,0), (0,0,side), steel)
        else:
            box(-0.05, 0.249, 0, 0.81, 0.128, 0.29, dark)
            box(-0.48, 0.49, 0, 0.62, 0.235, 0.32, bc)
        if mo:
            _tri_parts(_tube((-0.31, 0.40, 0), (0.48, 0.82, 0), 0.052, 6), lambda q: bc, parts)
            _tri_parts(_tube((0.68, r, 0), (0.48, 0.84, 0), 0.023, 4), lambda q: steel, parts)
        else:
            box(0.48, 0.34, 0, 0.15, 0.65, 0.37, bc)               # scooter leg shield
            box(-0.40, 0.35, 0, 0.31, 0.245, 0.28, bc)              # under-seat fairing
            points = [(0.68 + (r + 0.04) * math.cos(a), r + (r + 0.04) * math.sin(a))
                      for a in np.linspace(0.49, 2.62, 5)]
            for (x, y), (xx, yy) in zip(points, points[1:]):
                quad((x, y, -0.069), (xx-x, yy-y, 0), (0, 0, 0.138), (0, 1, 0), bc)
        box(-0.28, 0.743 if mo else 0.688, 0, 0.51, 0.076, 0.21 if mo else 0.27, dark)   # seat
        if mo:
            _tri_parts(_tube((0.46, 0.77, 0), (0.55, 1.01, 0), 0.035, 5), lambda q: steel, parts)
        box(0.55, 0.98, 0, 0.1, 0.07, 0.62, dark)                 # handlebar
        box(0.62, 0.96, 0, 0.12, 0.14, 0.2, bc)                   # headlight housing
        quad((0.685, 0.9, -0.08), (0, 0, 0.16), (0, 0.1, 0), (1, 0, 0), (255, 244, 180))
        quad((-0.835, 0.55, -0.1), (0, 0, 0.2), (0, 0.1, 0), (-1, 0, 0), (210, 30, 30))
        box(-0.78, 0.36, 0, 0.055, 0.096, 0.16, (236, 236, 230))      # plate
        if mo:
            box(0.0, 0.5, 0.26, 0.5, 0.2, 0.1, steel)              # engine cover
        else:
            box(-0.72, 0.72, 0, 0.37, 0.035, 0.31, dark)
            box(-0.73, 0.755, 0, 0.36, 0.31, 0.375, bc)            # rack-mounted delivery top case
            box(-0.73, 1.052, 0, 0.378, 0.054, 0.395, bc)


_HELI_ST = [   # fuselage stations (x, half width, bottom y, top y), nose to the clamshell doors (MBB/Kawasaki BK117)
    (3.10, 0.34, 0.74, 1.22), (3.00, 0.55, 0.58, 1.42), (2.80, 0.72, 0.48, 1.62), (2.50, 0.85, 0.43, 1.83), (2.10, 0.93, 0.42, 2.00),
    (1.60, 0.96, 0.42, 2.11), (1.10, 0.97, 0.42, 2.16), (0.70, 0.97, 0.42, 2.18), (-0.20, 0.97, 0.44, 2.18), (-1.00, 0.96, 0.48, 2.17), (-1.70, 0.94, 0.56, 2.15),
    (-2.20, 0.90, 0.70, 2.12), (-2.45, 0.84, 0.86, 2.08), (-2.60, 0.70, 1.10, 2.02), (-2.70, 0.40, 1.45, 1.98)]


def _tri_parts(tris, colfn, parts, centre=None, quads=False):
    """Triangles (N,3,3) -> parts with flat sun shading; normals turned away from `centre(p)` (a point inside the hull).
    quads: the triangles come in pairs (a loft): both halves of a quad take the colour of the quad's centre (clean edges)."""
    t = np.asarray(tris, np.float32)
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    c = t.mean(1)
    if quads and len(c) % 2 == 0:
        c = np.repeat((c[0::2] + c[1::2]) / 2, 2, 0)
    if centre is not None:
        inside = np.array([centre(q) for q in c], np.float32)
        flip = np.einsum("ij,ij->i", n, c - inside) < 0
        n[flip] *= -1
        t[flip] = t[flip][:, [0, 2, 1]]                  # winding too: back-face culling keeps the outer side
    col = np.array([colfn(q) for q in c], np.float32) * _shade(n)[:, None]
    parts.append((t.reshape(-1, 3), np.repeat(col, 3, 0), True))


def _ring(hw, yb, yt, x, k=24, e=2.6):
    out = []
    yc, hh = (yb + yt) / 2, (yt - yb) / 2
    for i in range(k):
        a = 2 * math.pi * i / k
        ca, sa = math.cos(a), math.sin(a)
        out.append((x, yc + hh * math.copysign(abs(sa) ** (2 / e), sa), hw * math.copysign(abs(ca) ** (2 / e), ca)))
    return out


def _loft(rings):
    tris = []
    k = len(rings[0])
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(k):
            j = (i + 1) % k
            tris += [(r0[i], r1[i], r1[j]), (r0[i], r1[j], r0[j])]
    return tris


def _tube(p0, p1, r, k=8):
    """Round tube between two points (skids, struts)."""
    p0, p1 = np.array(p0, np.float32), np.array(p1, np.float32)
    d = p1 - p0
    d /= np.linalg.norm(d) + 1e-9
    a = np.array((0, 1, 0), np.float32) if abs(d[1]) < 0.9 else np.array((1, 0, 0), np.float32)
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    ring = lambda p: [tuple(p + r * (math.cos(2 * math.pi * i / k) * u + math.sin(2 * math.pi * i / k) * v)) for i in range(k)]
    return _loft([ring(p0), ring(p1)])


def _heli_parts(body_c, A, box, quad, parts):
    """Medical helicopter (x forward, y up, z right), rotors left out (see rotor_model): lofted white fuselage with a red
    stripe, red crosses, tinted glazing, high tail boom, 2-blade tail rotor, end-plate stabiliser, engine hump (BK117), tubular skids. ~2600 triangles."""
    wh, red, dark, glass, grey = (240, 240, 244), (204, 30, 36), (44, 46, 52), (58, 86, 116), (176, 178, 186)
    st = _HELI_ST
    # finer stations in between (smooth hull)
    xs = []
    for (x0, *a0), (x1, *a1) in zip(st, st[1:]):
        for t in (0.0, 0.25, 0.5, 0.75):
            xs.append((x0 + (x1 - x0) * t, *[p + (q - p) * t for p, q in zip(a0, a1)]))
    xs.append(st[-1])
    rings = [_ring(hw, yb, yt, x) for x, hw, yb, yt in xs]
    x0, hw0, yb0, yt0 = st[0]                           # blunt, rounded bubble nose: a shrunken cap ring, then the centre
    ym = (yb0 + yt0) / 2
    hh0 = (yt0 - yb0) / 2
    caps = [_ring(hw0 * k, ym - 0.02 - hh0 * k, ym - 0.02 + hh0 * k, x0 + 0.16 * math.sqrt(1 - k * k)) for k in (0.3, 0.6, 0.85)]
    tip = [(x0 + 0.16, ym - 0.02, 0.0)] * len(rings[0])    # rounded radome dome
    hull = _loft([tip] + caps + rings)

    def at(x):                                         # hull section at x (linear between stations)
        if x >= xs[0][0]:
            return xs[0][1:]
        for (x0, *a0), (x1, *a1) in zip(xs, xs[1:]):
            if x1 <= x <= x0:
                t = (x0 - x) / (x0 - x1)
                return [p + (q - p) * t for p, q in zip(a0, a1)]
        return xs[-1][1:]

    def hull_col(q):
        x, y, z = q
        hw, yb, yt = at(x)
        f = (y - yb) / max(0.01, yt - yb)
        if x > 3.02:
            return wh                                      # radome nose cap
        if 1.15 < x and f > 0.44 and not (f > 0.93 and x < 1.9):
            if abs(z) < 0.075:
                return (222, 225, 229)
            return glass                                   # long sloping windscreen running down to the low nose
        if x > 2.15 and 0.14 < f < 0.38 and abs(z) > 0.18:
            return glass                                   # chin windows either side of the nose
        if (0.6 < x < 1.15 or -0.75 < x < -0.15) and 0.58 < f < 0.84 and abs(z) > hw * 0.8:
            return glass                                   # cockpit door and rear cabin windows
        if 0.30 < f < 0.42 and x > -2.4:
            return red                                     # livery stripe
        if f < 0.08:
            return grey                                    # belly
        return wh

    centre = lambda q: (q[0], sum(at(q[0])[1:]) / 2, 0.0)
    _tri_parts(hull, hull_col, parts, centre, True)
    rear = rings[-1]
    _tri_parts([(rear[0], rear[i], rear[i + 1]) for i in range(1, len(rear) - 1)], lambda q: wh, parts, lambda q: (q[0] + 1, q[1], 0))
    # high slim tail boom off the cabin roof, rising slightly to the tail rotor
    bx = [(-2.5, 0.34, 1.80), (-3.8, 0.26, 1.88), (-5.2, 0.21, 1.96), (-6.6, 0.18, 2.04), (-7.2, 0.16, 2.08)]
    brings = [_ring(r, y - r, y + r, x, 14, 2.0) for x, r, y in bx]
    _tri_parts(_loft(brings), lambda q: red if abs(q[1] - 1.78) < 0.05 and q[0] < -3.0 else wh, parts, lambda q: (q[0], 1.95, 0.0))
    # swept vertical fin with the tail rotor gearbox, and the horizontal stabiliser with canted end plates
    box(-7.05, 2.55, 0, 0.7, 0.85, 0.09, red)
    box(-7.35, 2.95, 0, 0.45, 0.3, 0.08, red)
    box(-7.25, 1.85, 0, 0.5, 0.35, 0.08, red)
    box(-7.0, 2.15, -0.14, 0.22, 0.22, 0.2, grey)
    box(-5.4, 2.0, 0, 0.6, 0.07, 2.2, wh)
    for sd in (-1, 1):
        box(-5.45, 2.05, sd * 1.1, 0.62, 0.62, 0.05, red)
    # engine cowling hump on the roof (two turbines side by side), oil-cooler grille at its back
    cw = [(1.0, 0.30, 2.14, 2.24), (0.5, 0.50, 2.14, 2.48), (-0.6, 0.58, 2.14, 2.62), (-1.8, 0.56, 2.12, 2.58), (-2.5, 0.40, 2.0, 2.36), (-2.75, 0.2, 1.98, 2.2)]
    crings = [_ring(hw, yb, yt, x, 16, 3.0) for x, hw, yb, yt in cw]
    _tri_parts(_loft(crings), lambda q: wh, parts, lambda q: (q[0], 2.3, 0.0), True)
    box(-2.1, 2.42, 0, 0.1, 0.18, 0.7, dark)
    # rotor mast, hub fairing, exhausts
    _tri_parts(_tube((-0.6, 2.55, 0), (-0.6, 2.85, 0), 0.16, 12), lambda q: dark, parts, lambda q: (-1.0, q[1], 0.0))
    for sd in (-1, 1):
        _tri_parts(_tube((-2.2, 2.4, sd * 0.3), (-2.7, 2.42, sd * 0.36), 0.11, 10), lambda q: dark, parts, lambda q: (q[0], 2.41, sd * 0.33))
    # red crosses on both sides of the cabin and on the cowling
    for sd in (-1, 1):
        zs = sd * 0.985
        quad((-0.05, 1.42, zs), (0.8, 0, 0), (0, 0.22, 0), (0, 0, sd), red)
        quad((0.24, 1.13, zs), (0.22, 0, 0), (0, 0.8, 0), (0, 0, sd), red)
        for xx in (-1.29, 0.59):
            quad((xx, 0.88, zs - sd * 0.012), (0.023, 0, 0), (0, 0.85, 0), (0, 0, sd), (112, 116, 121))
        quad((-1.22, 1.09, zs), (0.22, 0, 0), (0, 0.046, 0), (0, 0, sd), dark)  # sliding-door handle
        quad((-1.29, 0.87, zs - sd*0.012), (1.90, 0, 0), (0, 0.025, 0), (0, 0, sd), (163, 167, 170))
    box(1.6, 2.2, 0, 0.9, 0.03, 0.28, red)           # red cross on the cabin roof: what you see from above
    box(1.6, 2.2, 0, 0.28, 0.03, 0.9, red)
    # skids: two tubes with upturned toes, two cross tubes, steps
    for sd in (-1, 1):
        z = sd * 1.05
        _tri_parts(_tube((-1.7, 0.08, z), (1.9, 0.08, z), 0.06), lambda q: dark, parts, lambda q: (q[0], 0.08, z))
        _tri_parts(_tube((1.9, 0.08, z), (2.25, 0.3, z), 0.06), lambda q: dark, parts, lambda q: (q[0], q[1], z))
        for cx in (1.2, -0.9):
            _tri_parts(_tube((cx, 0.08, z), (cx, 0.42, sd * 0.7), 0.055), lambda q: dark, parts, lambda q: (cx, q[1], q[2] * 0.8))
        box(0.28, 0.32, sd * 0.98, 0.81, 0.043, 0.18, grey)
        quad((-0.62, 0.91, sd*0.983), (0.91, 0, 0), (0, 0.081, 0), (0, 0, sd), red)
    _tri_parts(_tube((1.2, 0.42, -0.7), (1.2, 0.42, 0.7), 0.055), lambda q: dark, parts, lambda q: (1.2, 0.42, q[2]))
    _tri_parts(_tube((-0.9, 0.42, -0.7), (-0.9, 0.42, 0.7), 0.055), lambda q: dark, parts, lambda q: (-0.9, 0.42, q[2]))
    # lights: landing light under the nose, beacons, nav lights, searchlight
    box(2.7, 0.44, 0, 0.18, 0.1, 0.24, (255, 244, 180))
    box(-1.6, 2.6, 0.0, 0.14, 0.12, 0.14, (240, 40, 40))
    box(-7.5, 3.12, 0, 0.12, 0.08, 0.12, (240, 40, 40))
    box(-5.45, 2.4, 1.1, 0.08, 0.06, 0.08, (40, 220, 60))
    box(-5.45, 2.4, -1.1, 0.08, 0.06, 0.08, (240, 40, 40))
    box(2.3, 0.34, 0.55, 0.3, 0.2, 0.22, dark)


_CAMO = ((44, 56, 32), (104, 88, 58), (30, 34, 26))


def _camo_n(x, y, z):
    """Low-frequency noise of a point: which camouflage blotch it falls in (-1 base, else an index of _CAMO)."""
    n = math.sin(x * 1.7 + z * 0.9) + math.sin(y * 2.3 - x * 1.1 + 1.3) + math.sin(z * 2.1 + x * 0.6 + 2.0)
    return 0 if n > 0.95 else (1 if n < -1.1 else (2 if -0.15 < n < 0.0 else -1))


def _camo_parts(parts, body_c):
    """Paint the body-coloured triangles of an army vehicle in green / brown / black blotches (per triangle)."""
    bc = np.asarray(body_c, np.float32)
    for i, (v, c, d) in enumerate(parts):
        if len(v) < 3:
            continue
        cc = np.asarray(c, np.float32).copy()
        r = cc / np.maximum(bc, 1.0)
        body = (np.abs(r[:, 0] - r[:, 1]) < 0.12) & (np.abs(r[:, 1] - r[:, 2]) < 0.12)
        if not body.any():
            continue
        t = v[: len(v) - len(v) % 3].reshape(-1, 3, 3).mean(1)
        for k, q in enumerate(t):
            j = _camo_n(*q)
            if j >= 0 and body[k * 3]:
                cc[k * 3: k * 3 + 3] *= np.asarray(_CAMO[j], np.float32) / bc
        parts[i] = (v, cc, d)


A_ARMY = np.array((70, 82, 48), np.float32)
APC_TURRET = (0.62, 2.0)           # BTR-80 turret ring: x along the hull, height of the roof (local metres)
APC_TRACK = 1.21                   # half track of the BTR-80's wheels (track 2.41 m)
APC_STYLE = {"turret": "80", "camo": True, "covers": "open"}     # look of the БТР-80 (turret "80a" = 30 mm 2A72 outside, "80" = cone turret)


def _poly(pts, col, parts, centre=(0.0, 1.25, 0.0)):
    """Convex flat plate through `pts` (fan), shaded, facing away from `centre`."""
    c = np.asarray(centre, np.float32)
    _tri_parts([(pts[0], pts[k], pts[k + 1]) for k in range(1, len(pts) - 1)], lambda q: np.asarray(col, np.float32), parts, centre=lambda q: c)


def _disc(x, y, z, r, h, col, parts, k=16, axis="y"):
    """Short cylinder (hatch, port, lens): axis y (on a roof) or x (facing forward / back)."""
    if axis == "y":
        p0, p1 = (x, y, z), (x, y + h, z)
    else:
        p0, p1 = (x, y, z), (x + h, y, z)
    _tri_parts(_tube(p0, p1, r, k), lambda q: np.asarray(col, np.float32), parts, centre=lambda q: p0)
    ring = [tuple(np.asarray(p1) + (np.array((0, 0, r * math.cos(2 * math.pi * i / k)), np.float32) +
            (np.array((r * math.sin(2 * math.pi * i / k), 0, 0), np.float32) if axis == "y" else np.array((0, r * math.sin(2 * math.pi * i / k), 0), np.float32))))
            for i in range(k)]
    _tri_parts([(p1, ring[i], ring[(i + 1) % k]) for i in range(k)], lambda q: np.asarray(col, np.float32) * 0.92, parts,
               centre=lambda q: p0)


# hull rings of the BTR-80, left side bottom -> belt -> chamfer -> roof edge (x, y, half width); the right side mirrors them
_APC_RINGS = [
    [(3.80, 0.97, 0.52), (3.86, 1.02, 0.66), (3.84, 1.05, 0.62), (3.82, 1.07, 0.54)],      # nose edge
    [(3.00, 0.50, 0.90), (3.10, 1.22, 1.36), (2.62, 1.50, 1.12), (2.40, 1.62, 0.96)],      # glacis / lower nose plate break
    [(2.20, 0.48, 0.98), (2.20, 1.32, 1.45), (2.02, 1.88, 1.16), (1.96, 2.00, 1.00)],      # top of the vision-block plate
    [(-2.55, 0.48, 0.98), (-2.55, 1.32, 1.45), (-2.55, 1.88, 1.16), (-2.55, 2.00, 1.00)],  # end of the troop compartment
    [(-3.30, 0.56, 0.95), (-3.46, 1.30, 1.42), (-3.46, 1.80, 1.12), (-3.40, 1.92, 0.98)],  # engine deck
    [(-3.60, 0.86, 0.86), (-3.84, 1.22, 1.30), (-3.84, 1.56, 1.05), (-3.78, 1.70, 0.92)],  # tail
]


def _apc_up(x, y, s, d=0.012):
    """Point on the upper side plate (belt 1.32 -> chamfer 1.88) of the middle hull, d metres proud of it."""
    t = (y - 1.32) / 0.56
    return (x, y + d * 0.46, s * (1.45 - 0.29 * t + d * 0.89))


def _apc_lo(x, y, s, d=0.012):
    """Point on the lower side plate (bottom 0.48 -> belt 1.32)."""
    t = (y - 0.48) / 0.84
    return (x, y - d * 0.49, s * (0.98 + 0.47 * t + d * 0.87))


def _apc_wheel(cx, cy, cz, face=0, R=0.60, wd=0.42):
    """BTR-80 wheel, axis along z: tall KI-80 off-road tyre with staggered tread lugs, deep sidewall, small green hub with the
    tyre-inflation cap.  Returns (verts, colours) like _cyl."""
    vs, cs = [], []
    tyre, side, hub, dark = np.array((30, 30, 30), np.float32), np.array((38, 38, 37), np.float32), A_ARMY * 1.04, np.array((39, 42, 33), np.float32)
    n = 28
    za, zm, zb = cz - wd / 2, cz, cz + wd / 2

    def P(a, r, z):
        return (cx + r * math.cos(a), cy + r * math.sin(a), z)
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        sh = 0.55 + 0.5 * max(0.0, math.cos((a0 + a1) / 2) * 0.4 + math.sin((a0 + a1) / 2) * 0.9)
        for h, (z0, z1) in enumerate(((za, zm), (zm, zb))):          # each half of the tread: lug on alternate segments, staggered = chevrons
            r = R if (i + h) % 2 == 0 else R - 0.045
            vs += [P(a0, r, z0), P(a1, r, z0), P(a1, r, z1), P(a0, r, z0), P(a1, r, z1), P(a0, r, z1)]
            cs += [tyre * sh] * 6
            if r == R:                                                   # lug side walls
                for a in (a0, a1):
                    vs += [P(a, R - 0.045, z0), P(a, R, z0), P(a, R, z1), P(a, R - 0.045, z0), P(a, R, z1), P(a, R - 0.045, z1)]
                    cs += [tyre * 0.7] * 6
        for z, sg in ((za, -1), (zb, 1)):
            if face and sg != face:
                continue
            zi = z + sg * 0.02                                           # sidewall bulge, then the small rim, then the hub
            vs += [P(a0, R - 0.045, z), P(a1, R - 0.045, z), P(a1, 0.34, zi), P(a0, R - 0.045, z), P(a1, 0.34, zi), P(a0, 0.34, zi)]
            cs += [side] * 6
            vs += [P(a0, 0.34, zi), P(a1, 0.34, zi), P(a1, 0.27, zi - sg * 0.04), P(a0, 0.34, zi), P(a1, 0.27, zi - sg * 0.04), P(a0, 0.27, zi - sg * 0.04)]
            cs += [hub * 0.8] * 6
            vs += [(cx, cy, zi - sg * 0.01), P(a0, 0.27, zi - sg * 0.04), P(a1, 0.27, zi - sg * 0.04)]
            cs += [hub] * 3
            if i % 4 == 0:                                               # wheel nuts
                b = (a0 + a1) / 2
                q = P(b, 0.19, zi + sg * 0.0)
                for d in ((0.025, 0.025), (-0.025, 0.025), (-0.025, -0.025)), ((0.025, 0.025), (-0.025, -0.025), (0.025, -0.025)):
                    vs += [(q[0] + d[k][0], q[1] + d[k][1], zi + sg * 0.005) for k in range(3)]
                    cs += [dark] * 3
            for k in range(8):                                           # central inflation cap
                b0, b1 = 2 * math.pi * k / 8, 2 * math.pi * (k + 1) / 8
                if i == 0:
                    vs += [(cx, cy, zi + sg * 0.06), P(b0, 0.07, zi + sg * 0.005), P(b1, 0.07, zi + sg * 0.005)]
                    cs += [dark * 1.4] * 3
    return np.asarray(vs, np.float32), np.asarray(cs, np.float32)


def _apc_parts(body_c, A, box, quad, parts):
    """BTR-80: wedge-nosed, chined eight-wheeled hull (x forward, y up, z right); the turret is turret_model() (it rotates)."""
    sty = APC_STYLE
    bc = np.asarray(body_c, np.float32)
    rings = []
    for r in _APC_RINGS:
        left = [(x, y, -h) for x, y, h in r]
        ring = left + [(x, y, -z) for x, y, z in reversed(left)]
        fine = []                                                    # each plate split in 4 across (fine camouflage, smooth shading stays flat)
        for i in range(len(ring)):
            p0, p1 = np.asarray(ring[i]), np.asarray(ring[(i + 1) % len(ring)])
            fine += [tuple(p0 + (p1 - p0) * t) for t in (0.0, 0.25, 0.5, 0.75)]
        rings.append(fine)
    dense = [rings[0]]
    for r0, r1 in zip(rings, rings[1:]):                             # and every ~0.3 m along the hull
        n = max(1, int(round(abs(r0[0][0] - r1[0][0]) / 0.3)))
        dense += [[tuple(np.asarray(a) + (np.asarray(b) - np.asarray(a)) * (k / n)) for a, b in zip(r0, r1)] for k in range(1, n + 1)]
    tris = _loft(dense)
    for r in (rings[0], rings[-1]):                                  # nose edge and rear plate
        tris += [(r[0], r[k], r[k + 1]) for k in range(1, len(r) - 1)]

    def col(q):
        j = _camo_n(*q) if sty["camo"] else -1
        return bc if j < 0 else np.asarray(_CAMO[j], np.float32)
    _tri_parts(tris, col, parts, centre=lambda q: (max(-3.0, min(3.0, q[0])), 1.2, 0.0))
    dark, glass, metal, edge = (26, 28, 24), (36, 50, 60), (52, 56, 50), bc * 0.72
    rubber = (30, 30, 30)
    for s in (-1, 1):
        # wheel wells: dark recesses in the lower side plate behind each wheel
        for ax in (2.30, 0.82, -0.70, -2.18):
            _poly([_apc_lo(ax - 0.66, 0.52, s), _apc_lo(ax + 0.66, 0.52, s), _apc_lo(ax + 0.60, 1.26, s), _apc_lo(ax - 0.60, 1.26, s)], (22, 22, 20), parts)
            _poly([_apc_up(ax - 0.70, 1.33, s, 0.02), _apc_up(ax + 0.70, 1.33, s, 0.02), _apc_up(ax + 0.70, 1.37, s, 0.02), _apc_up(ax - 0.70, 1.37, s, 0.02)], edge, parts)
        # side door between axles 2 and 3: upper half on the upper plate, lower half (the step) on the lower plate, frame, hinges
        _poly([_apc_up(-0.42, 1.36, s), _apc_up(0.52, 1.36, s), _apc_up(0.52, 1.80, s), _apc_up(-0.42, 1.80, s)], bc * 0.86, parts)
        _poly([_apc_lo(-0.42, 0.78, s), _apc_lo(0.52, 0.78, s), _apc_lo(0.52, 1.28, s), _apc_lo(-0.42, 1.28, s)], bc * 0.86, parts)
        for (x0, x1, y0, y1) in ((-0.44, -0.40, 1.36, 1.80), (0.50, 0.54, 1.36, 1.80), (-0.44, 0.54, 1.78, 1.82)):
            _poly([_apc_up(x0, y0, s, 0.02), _apc_up(x1, y0, s, 0.02), _apc_up(x1, y1, s, 0.02), _apc_up(x0, y1, s, 0.02)], dark, parts)
        for hx in (-0.36, 0.46):
            box(*_apc_up(hx, 1.55, s, 0.04)[:2], s * 1.36, 0.06, 0.12, 0.05, metal)
        box(0.05, 0.80, s * 1.16, 0.7, 0.04, 0.12, metal)                                 # fold-down step
        # firing ports: ball mounts on the upper side plates
        for px in (1.45, -1.10, -1.85):
            p0 = np.asarray(_apc_up(px, 1.62, s, 0.0), np.float32)
            n = np.asarray((0.0, 0.46, 0.89 * s), np.float32)
            _tri_parts(_tube(tuple(p0), tuple(p0 + n * 0.06), 0.09, 12), lambda q: np.asarray(metal, np.float32), parts, centre=lambda q: tuple(p0 - n))
            _tri_parts(_tube(tuple(p0 + n * 0.05), tuple(p0 + n * 0.09), 0.035, 8), lambda q: np.asarray(dark, np.float32), parts, centre=lambda q: tuple(p0))
        # grab rails along the upper hull, tow hooks, mud flaps
        rp = [_apc_up(x, 1.84, s, 0.06) for x in (1.6, -2.3)]
        _tri_parts(_tube(rp[0], rp[1], 0.018, 6), lambda q: np.asarray(metal, np.float32), parts, centre=lambda q: (q[0], 1.6, 0.0))
        for x in (1.6, -0.35, -2.3):
            _tri_parts(_tube(_apc_up(x, 1.84, s, 0.0), _apc_up(x, 1.84, s, 0.07), 0.016, 6), lambda q: np.asarray(metal, np.float32), parts, centre=lambda q: (q[0], 1.6, 0.0))
        box(3.62, 0.70, s * 0.55, 0.22, 0.1, 0.12, dark)                                 # front tow hooks
        box(-3.70, 0.84, s * 0.52, 0.22, 0.1, 0.12, dark)                                # rear tow hooks
        box(-2.90, 0.50, s * 1.20, 0.04, 0.45, 0.42, rubber)                             # mud flap behind the last wheel
        box(3.02, 0.62, s * 1.20, 0.04, 0.38, 0.42, rubber)
        # headlamps in their guards on the nose, side and tail lights
        box(3.40, 1.18, s * 0.92, 0.22, 0.18, 0.26, metal)
        for dz in (-0.06, 0.06):
            _disc(3.51, 1.27, s * 0.92 + dz, 0.05, 0.03, (250, 240, 190), parts, 10, "x")
        _tri_parts(_tube((3.40, 1.40, s * 0.78), (3.62, 1.40, s * 0.78), 0.015, 5) + _tube((3.40, 1.40, s * 1.06), (3.62, 1.40, s * 1.06), 0.015, 5) +
                   _tube((3.62, 1.40, s * 0.78), (3.62, 1.40, s * 1.06), 0.015, 5), lambda q: np.asarray(metal, np.float32), parts)
        box(-3.83, 1.30, s * 0.95, 0.05, 0.12, 0.16, (190, 30, 24))                      # tail lights
        box(-3.83, 1.43, s * 0.95, 0.05, 0.08, 0.16, (230, 150, 40))
        # exhaust mufflers on the rear quarters, with mesh guards
        _tri_parts(_tube((-2.85, 1.70, s * 1.18), (-3.45, 1.70, s * 1.18), 0.11, 10), lambda q: np.asarray((48, 46, 42), np.float32), parts, centre=lambda q: (q[0], 1.70, s * 1.18))
        box(-3.15, 1.60, s * 1.18, 0.7, 0.24, 0.3, (60, 64, 50))
        # whip antennas on the rear roof corners
        _tri_parts(_tube((-2.45, 2.0, s * 0.82), (-2.62, 4.2, s * 0.86), 0.012, 4), lambda q: np.asarray(dark, np.float32), parts)
        box(-2.45, 2.0, s * 0.82, 0.12, 0.10, 0.12, dark)
        # driver's (left) and commander's (right) hatches behind the vision blocks
        _disc(1.68, 2.0, s * 0.45, 0.27, 0.05, bc * 0.9, parts, 16)
        box(1.68, 2.05, s * 0.45, 0.30, 0.04, 0.05, metal)
        for k in range(3):                                                                # periscopes round the hatch
            box(1.98, 2.0, s * (0.25 + k * 0.2), 0.10, 0.08, 0.12, dark)
        # roof hatches behind the turret
        box(-0.72, 2.0, s * 0.46, 0.66, 0.04, 0.56, bc * 0.88)
        box(-0.72, 2.04, s * 0.46, 0.08, 0.03, 0.56, metal)
        # Macedonian flag on the upper hull side, in front of the door
        _poly([_apc_up(0.75, 1.52, s, 0.02), _apc_up(1.2, 1.52, s, 0.02), _apc_up(1.2, 1.78, s, 0.02), _apc_up(0.75, 1.78, s, 0.02)], (200, 30, 30), parts)
        fx, fy = 0.975, 1.65                                             # North Macedonia: yellow sun with eight broadening rays
        for k in range(8):
            t = k * math.pi / 4
            c_, s_ = math.cos(t), math.sin(t)
            w_ = 0.045
            _poly([_apc_up(fx + c_ * 0.03, fy + s_ * 0.03, s, 0.03), _apc_up(fx + c_ * 0.4 - s_ * w_, fy + s_ * 0.4 + c_ * w_, s, 0.03),
                   _apc_up(fx + c_ * 0.4 + s_ * w_, fy + s_ * 0.4 - c_ * w_, s, 0.03)] if False else
                  [_apc_up(fx, fy, s, 0.03), _apc_up(max(0.75, min(1.2, fx + c_ * 0.3 - s_ * w_)), max(1.52, min(1.78, fy + s_ * 0.3 + c_ * w_)), s, 0.03),
                   _apc_up(max(0.75, min(1.2, fx + c_ * 0.3 + s_ * w_)), max(1.52, min(1.78, fy + s_ * 0.3 - c_ * w_)), s, 0.03)], (250, 210, 30), parts)
        _poly([_apc_up(fx + 0.045 * math.cos(k * math.pi / 6), fy + 0.045 * math.sin(k * math.pi / 6), s, 0.035) for k in range(12)], (250, 210, 30), parts)
        _poly([_apc_up(fx + 0.036 * math.cos(k * math.pi / 6), fy + 0.036 * math.sin(k * math.pi / 6), s, 0.04) for k in range(12)], (200, 30, 30), parts)
        _poly([_apc_up(fx + 0.028 * math.cos(k * math.pi / 6), fy + 0.028 * math.sin(k * math.pi / 6), s, 0.045) for k in range(12)], (250, 210, 30), parts)
    # vision blocks: two big windscreens on the steep front plate (driver left, commander right) with their armoured covers
    def fp(t, z, d=0.012):                                           # point on the front plate between rings 1 and 2 (t 0 bottom .. 1 top)
        return (2.40 - 0.44 * t + d * 0.65, 1.62 + 0.38 * t + d * 0.76, z)
    for s in (-1, 1):
        z0, z1 = s * 0.10, s * 0.82
        _poly([fp(0.12, z0), fp(0.12, z1), fp(0.88, z1), fp(0.88, z0)], glass, parts)
        _poly([fp(0.08, z0 - s * 0.03, 0.02), fp(0.08, z1 + s * 0.03, 0.02), fp(0.12, z1 + s * 0.03, 0.02), fp(0.12, z0 - s * 0.03, 0.02)], dark, parts)
        if sty["covers"] == "open":                                   # hinged at the top, swung up and forward
            h0, h1 = fp(0.95, z0, 0.03), fp(0.95, z1, 0.03)
            _poly([h0, h1, (h1[0] + 0.30, h1[1] + 0.40, z1), (h0[0] + 0.30, h0[1] + 0.40, z0)], bc * 0.95, parts)
            _poly([(h0[0] + 0.02, h0[1] + 0.02, z0), (h1[0] + 0.02, h1[1] + 0.02, z1), (h1[0] + 0.31, h1[1] + 0.41, z1), (h0[0] + 0.31, h0[1] + 0.41, z0)], bc * 0.8, parts)
        else:
            _poly([fp(0.08, z0, 0.05), fp(0.08, z1, 0.05), fp(0.95, z1, 0.05), fp(0.95, z0, 0.05)], bc * 0.95, parts)
            for t in (0.4, 0.6):
                _poly([fp(t, z0 + s * 0.15, 0.06), fp(t, z1 - s * 0.15, 0.06), fp(t + 0.03, z1 - s * 0.15, 0.06), fp(t + 0.03, z0 + s * 0.15, 0.06)], dark, parts)
    # trim vane folded flat on the upper glacis, with its ribs
    def gp(t, z, d):                                                 # point on the upper glacis (t 0 nose edge .. 1 front plate)
        return (3.82 - 1.42 * t + d * 0.36, 1.07 + 0.55 * t + d * 0.93, z)
    _poly([gp(0.10, -0.62, 0.04), gp(0.10, 0.62, 0.04), gp(0.62, 0.86, 0.04), gp(0.62, -0.86, 0.04)], bc * 0.9, parts)
    for z in (-0.5, -0.17, 0.17, 0.5):
        _poly([gp(0.12, z - 0.02, 0.07), gp(0.12, z + 0.02, 0.07), gp(0.6, z * 1.3 + 0.02, 0.07), gp(0.6, z * 1.3 - 0.02, 0.07)], bc * 0.7, parts)
    # engine deck: two louvred grilles and an access panel
    for s in (-1, 1):
        for k in range(9):
            box(-1.95 - k * 0.15, 2.0, s * 0.52, 0.06, 0.03, 0.64, dark)
    box(-3.05, 1.95, 0, 0.55, 0.03, 0.5, bc * 0.85)
    # rear: water-jet outlet with its cover plate, number plate, tow pintle
    box(-3.83, 0.95, 0, 0.06, 0.42, 0.52, bc * 0.8)
    box(-3.86, 1.22, 0, 0.03, 0.12, 0.42, (220, 220, 210))
    box(-3.70, 0.62, 0, 0.3, 0.12, 0.14, dark)
    # front number plate and convoy light on the nose
    _poly([gp(0.05, -0.22, 0.02), gp(0.05, 0.22, 0.02), gp(0.1, 0.22, 0.02), gp(0.1, -0.22, 0.02)], (220, 220, 210), parts)
    # tools on the glacis: shovel and crowbar
    _tri_parts(_tube(gp(0.66, -0.55, 0.05), gp(0.95, -0.40, 0.05), 0.022, 5), lambda q: np.asarray((110, 84, 50), np.float32), parts)
    _tri_parts(_tube(gp(0.66, 0.55, 0.05), gp(0.95, 0.30, 0.05), 0.018, 5), lambda q: np.asarray(metal, np.float32), parts)


def turret_model():
    """BTR-80 turret on its own pivot (y up, barrel along +x).  "80a": faceted turret with the 30 mm 2A72 mounted outside on top,
    coaxial PKT, sight, searchlight, six smoke dischargers;  "80": the classic low cone with the gun in a mantlet."""
    parts = []
    bc = np.asarray(V.ARMY, np.float32)
    sty = APC_STYLE
    dark, metal, glass = (30, 32, 30), (54, 58, 50), (40, 60, 80)

    def col(q):
        j = _camo_n(q[0] + 0.3, q[1] + 2.0, q[2]) if sty["camo"] else -1
        return bc if j < 0 else np.asarray(_CAMO[j], np.float32)
    k = 12
    _tri_parts(_tube((0, -0.02, 0), (0, 0.05, 0), 0.86, 20), lambda q: np.asarray(metal, np.float32), parts, centre=lambda q: (0, -0.5, 0))   # ring
    if sty["turret"] == "80a":
        lo = [(0.80 * math.cos(2 * math.pi * (i + 0.5) / k), 0.05, 0.80 * math.sin(2 * math.pi * (i + 0.5) / k)) for i in range(k)]
        hi = [(0.60 * math.cos(2 * math.pi * (i + 0.5) / k) - 0.05, 0.50, 0.58 * math.sin(2 * math.pi * (i + 0.5) / k)) for i in range(k)]
        tris = _loft([lo, hi]) + [(hi[0], hi[i + 1], hi[i]) for i in range(1, k - 1)]
        _tri_parts(tris, col, parts, centre=lambda q: (0.0, 0.2, 0.0))
        gy = 0.66                                                                     # bore height above the ring
        box_ = lambda cx, cy, cz, sx, sy, sz, c: [parts.append((v, np.tile(np.asarray(c, np.float32) * _shade(np.asarray(n, np.float32)), (len(v), 1)))) for _n, (v, n) in box_faces(cx, cy, cz, sx, sy, sz).items()]
        box_(0.18, 0.48, 0.0, 0.72, 0.10, 0.44, bc * 0.85)                           # gun cradle on the roof
        box_(0.10, 0.56, 0.0, 1.00, 0.20, 0.26, bc * 0.9)                            # receiver / armoured gun cover
        box_(0.10, 0.76, 0.0, 0.80, 0.03, 0.22, bc * 0.75)
        _tri_parts(_tube((0.60, gy, 0.0), (1.05, gy, 0.0), 0.065, 12), lambda q: np.asarray(metal, np.float32), parts)     # recoil sleeve
        _tri_parts(_tube((1.05, gy, 0.0), (3.05, gy, 0.0), 0.036, 10), lambda q: np.asarray(dark, np.float32), parts)      # 30 mm barrel
        _tri_parts(_tube((2.92, gy, 0.0), (3.12, gy, 0.0), 0.05, 10), lambda q: np.asarray((24, 24, 26), np.float32), parts)
        _tri_parts(_tube((0.55, gy - 0.04, -0.20), (1.30, gy - 0.04, -0.20), 0.022, 6), lambda q: np.asarray(dark, np.float32), parts)   # coaxial PKT
        box_(0.42, 0.50, -0.20, 0.30, 0.14, 0.10, metal)
        box_(0.28, 0.50, 0.36, 0.34, 0.26, 0.20, bc * 0.8)                           # gunner's sight 1PZ-9
        box_(0.46, 0.58, 0.36, 0.02, 0.12, 0.14, glass)
        box_(0.22, 0.52, -0.42, 0.24, 0.18, 0.18, metal)                             # searchlight
        _disc(0.34, 0.61, -0.42, 0.07, 0.02, (240, 236, 200), parts, 10, "x")
        _disc(-0.28, 0.50, 0.18, 0.22, 0.05, bc * 0.85, parts, 14)                   # commander's hatch
        ry = 0.30
    else:
        lo = [(0.78 * math.cos(2 * math.pi * i / 16), 0.05, 0.78 * math.sin(2 * math.pi * i / 16)) for i in range(16)]
        hi = [(0.50 * math.cos(2 * math.pi * i / 16) - 0.06, 0.48, 0.50 * math.sin(2 * math.pi * i / 16)) for i in range(16)]
        tris = _loft([lo, hi]) + [(hi[0], hi[i + 1], hi[i]) for i in range(1, 15)]
        _tri_parts(tris, col, parts, centre=lambda q: (0.0, 0.2, 0.0))
        gy = 0.28
        for _n, (v, n) in box_faces(0.62, 0.10, 0.0, 0.30, 0.36, 0.62).items():                         # mantlet
            parts.append((v, np.tile(bc * 0.85 * _shade(np.asarray(n, np.float32)), (len(v), 1))))
        _tri_parts(_tube((0.70, gy, 0.0), (3.05, gy, 0.0), 0.05, 10), lambda q: np.asarray(dark, np.float32), parts)
        _tri_parts(_tube((2.85, gy, 0.0), (3.10, gy, 0.0), 0.075, 10), lambda q: np.asarray((24, 24, 26), np.float32), parts)
        _tri_parts(_tube((0.70, gy - 0.02, 0.20), (1.40, gy - 0.02, 0.20), 0.025, 6), lambda q: np.asarray(dark, np.float32), parts)
        for _n, (v, n) in box_faces(0.10, 0.46, -0.22, 0.30, 0.16, 0.20).items():                        # sight
            parts.append((v, np.tile(np.asarray(metal, np.float32) * _shade(np.asarray(n, np.float32)), (len(v), 1))))
        _disc(-0.25, 0.47, 0.15, 0.2, 0.04, bc * 0.85, parts, 14)
        ry = 0.22
    for s in (-1, 1):                                                                # 902V smoke dischargers on the turret rear
        for i in range(3):
            a = math.pi * (0.78 + 0.07 * i) * s
            bx, bz = 0.66 * math.cos(a), 0.66 * math.sin(a)
            _tri_parts(_tube((bx, ry, bz), (bx - 0.18, ry + 0.16, bz + s * 0.04), 0.045, 8), lambda q: np.asarray(dark, np.float32), parts)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(np.concatenate([p[1] for p in parts]), 0, 255)
    rgba[:, 3] = 255
    return object_detail(make_model(pos, np.zeros((len(pos), 2), np.float32), rgba), "metal")


def rotor_model(kind, tail=False):
    """Spinning blades of the helicopter: 4 tapered, twisted blades and a hub about y at the mast, or the 2-blade
    tail rotor about z."""
    parts = []
    dark, hub = np.array((38, 38, 42), np.float32), np.array((90, 92, 100), np.float32)
    tris = []
    if tail:
        for i in range(2):                               # two-blade see-saw tail rotor (BK117)
            a = math.pi * i
            c, s_ = math.cos(a), math.sin(a)
            pa = lambda r, w: (r * c - w * s_, r * s_ + w * c, 0.0)
            tris += [(pa(0.06, -0.09), pa(0.98, -0.07), pa(0.98, 0.07)), (pa(0.06, -0.09), pa(0.98, 0.07), pa(0.06, 0.09))]
        _tri_parts(tris, lambda q: dark, parts)
        _tri_parts(_tube((0, 0, -0.06), (0, 0, 0.06), 0.1, 10), lambda q: hub, parts)
    else:
        R, n = 5.1, 10
        for b in range(4):
            a = b * math.pi / 2
            c, s_ = math.cos(a), math.sin(a)
            for i in range(n):
                r0, r1 = 0.3 + (R - 0.3) * i / n, 0.3 + (R - 0.3) * (i + 1) / n
                w0, w1 = 0.17 - 0.05 * i / n, 0.17 - 0.05 * (i + 1) / n
                tw0, tw1 = 0.03 * (1 - i / n), 0.03 * (1 - (i + 1) / n)
                pt = lambda r, w, y: (r * c - w * s_, y, r * s_ + w * c)
                q = [pt(r0, -w0, -tw0), pt(r1, -w1, -tw1), pt(r1, w1, tw1), pt(r0, w0, tw0)]
                tris += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
                lo = [(x, y - 0.035, z) for x, y, z in q]
                tris += [(lo[0], lo[2], lo[1]), (lo[0], lo[3], lo[2])]
        _tri_parts(tris, lambda q: dark, parts)
        _tri_parts(_tube((0, -0.12, 0), (0, 0.12, 0), 0.32, 14), lambda q: hub, parts)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return object_detail(make_model(pos, np.zeros((len(pos), 2), np.float32), rgba), "metal", kind)


def stairs_model(flights):
    """Steel stairs in world space from Sim.heli_stairs ramps (0, cx, cy, ux, uy, half_len, half_w, h0, h1): steps, stringers, rails."""
    parts = []
    steel, rail = np.array((88, 92, 100), np.float32), np.array((150, 40, 40), np.float32)

    def add(lx, ly, lz, sx, sy, sz, col, f):
        _z, cx, cy, ux, uy = f[:5]
        for name, (v, n) in box_faces(lx, ly, lz, sx, sy, sz).items():
            w = np.empty_like(v)
            w[:, 0] = cx + v[:, 0] * ux - v[:, 2] * uy
            w[:, 2] = cy + v[:, 0] * uy + v[:, 2] * ux
            w[:, 1] = v[:, 1]
            nn = np.array((n[0] * ux - n[2] * uy, n[1], n[0] * uy + n[2] * ux), np.float32)
            parts.append((w, np.tile(col * _shade(nn), (len(v), 1))))

    for f in flights:
        hl, hw, h0, h1 = f[5], f[6], f[7], f[8]
        if abs(h1 - h0) < 0.01:                                  # landing / bridge: a flat plate
            add(0, h0 - 0.12, 0, hl * 2, 0.12, hw * 2, steel, f)
            continue
        k = max(2, int((h1 - h0) / 0.22))
        for i in range(k):
            t = (i + 0.5) / k
            add(-hl + 2 * hl * t, h0 + (h1 - h0) * t - 0.06, 0, 2 * hl / k + 0.02, 0.06, hw * 2, steel, f)
        for sd in (-1, 1):                                       # stringers and a hand rail on each side, as stepped boxes
            for i in range(k):
                t = (i + 0.5) / k
                y = h0 + (h1 - h0) * t
                add(-hl + 2 * hl * t, y - 0.3, sd * hw, 2 * hl / k + 0.02, 0.3, 0.06, steel, f)
                add(-hl + 2 * hl * t, y + 0.95, sd * hw, 2 * hl / k + 0.02, 0.05, 0.05, rail, f)
            add(-hl + 0.05, h0, sd * hw, 0.05, 1.0, 0.05, rail, f)
    if not parts:
        return None
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return object_detail(make_model(pos, np.zeros((len(pos), 2), np.float32), rgba), "metal", 3)



_TYRE_R = {"mini": 0.27, "hatch": 0.30, "sedan": 0.31, "taxi": 0.31, "wagon": 0.31, "limo": 0.33, "van": 0.34,
           "suv": 0.38, "pickup": 0.38}



_COMMERCIAL_RIMS = {
    "Gradski Avtobus": ("truck", 8, 0.61), "Avtobus Skopje-Ohrid": ("hubcap", 8, 0.62),
    "JSP Dvokatnik": ("truck", 10, 0.61), "JSP Zglobni": ("truck", 10, 0.60),
    "Pozharna": ("truck", 10, 0.59), "Smetar Kamion": ("truck", 8, 0.59),
    "Betonjerka": ("truck", 10, 0.60), "Kamion Tovarnik": ("truck", 8, 0.62),
    "Tir Rinfuz": ("truck", 10, 0.59), "Cisterna Gorivo": ("truck", 10, 0.59),
    "Traktor IMT": ("steel", 6, 0.64), "Voen Kamion": ("steel", 8, 0.58),
    "Voen Hamer": ("steel", 8, 0.61), "Voena Niva": ("steel", 8, 0.60),
    "Kamion za Linii": ("truck", 8, 0.60), "Signalen Kamion": ("truck", 8, 0.60), "Kamion za Konusi": ("truck", 8, 0.60),
}

_COMMERCIAL_WIDTH_HEIGHT = {
    "Gradski Avtobus": (2.50, 3.12), "Avtobus Skopje-Ohrid": (2.55, 3.65),
    "JSP Dvokatnik": (2.50, 4.20), "JSP Zglobni": (2.55, 3.10),
    "Pozharna": (2.41, 3.21), "Smetar Kamion": (2.50, 3.28),
    "Betonjerka": (2.50, 3.72), "Kamion Tovarnik": (2.44, 3.46),
    "Tir Rinfuz": (2.51, 3.91), "Cisterna Gorivo": (2.49, 3.48),
    "Voen Hamer": (2.16, 1.83), "Voena Niva": (1.68, 1.64), "Voen Kamion": (2.49, 3.08),
    "Kamion za Linii": (2.46, 3.30), "Signalen Kamion": (2.46, 3.30), "Kamion za Konusi": (2.46, 3.20),
}


def visual_dims(kind):
    kind %= V.N
    name = V.IDS[kind]
    dims = V.DIMS[kind]
    if name in _COMMERCIAL_WIDTH_HEIGHT:
        length, _, bottom, belt, _ = dims
        width, height = _COMMERCIAL_WIDTH_HEIGHT[name]
        return length, width, bottom, belt, height
    return carbody.render_dims(name, dims)


@lru_cache(maxsize=None)
def indicator_mounts(kind):
    """Lens rectangles on each end, in the same local frames as the vehicle meshes."""
    name, style = V.IDS[kind], V.STYLE[kind]
    length, width, bottom, belt, _ = visual_dims(kind)
    if style in carbody.LOFT_STYLES and carbody.has(name):
        return carbody.indicator_mounts(name, length, width, belt)
    if kind == V.SEMI:
        return ((V.SEMI_SHIFT + V.SEMI_TRACTOR_L / 2 + 0.014, belt - 0.23, width * 0.424, 0.105, 0.075),
                (V.SEMI_HITCH - V.SEMI_TRAILER_L + 0.096, 1.23, 1.135, 0.07, 0.064))
    if kind in V.BIKES:
        return (length * 0.5 - 0.05, 0.78, 0.16, 0.045, 0.039), (-length * 0.5 + 0.12, 0.73, 0.14, 0.045, 0.039)
    y = belt - 0.215
    return ((length * 0.5 + 0.012, y, width * 0.423, 0.105, 0.078),
            (-length * 0.5 - 0.012, y, width * 0.423, 0.105, 0.074))


def _wheel_layout(st, L, name=None):
    """(x, radius, width) of every wheel pair, the front axle first."""
    if name is not None and st in carbody.LOFT_STYLES and carbody.has(name):          # the real car's axle positions and tyre size
        lay = carbody.layout(name, L)
        r = lay["tr"] or _TYRE_R.get(st, 0.34)
        return [(lay["ax_f"], r, 0.7 * r), (lay["ax_r"], r, 0.7 * r)]
    if name == "JSP Zglobni":
        return [(x, 0.493, 0.30) for x in (V.ARTIC_FRONT_AXLE, V.ARTIC_MIDDLE_AXLE, V.ARTIC_REAR_AXLE)]
    if name == "Voen Hamer":
        return [(L*0.326, 0.432, 0.252), (-L*0.347, 0.432, 0.252)]
    if name == "Voena Niva":
        return [(L*0.294, 0.347, 0.178), (-L*0.292, 0.347, 0.178)]
    if name in ("Pozharna", "Kamion Tovarnik"):
        return [(L*0.328, 0.48, 0.28), (-L*0.27, 0.48, 0.30)]
    if L > 11:
        return [(L * 0.34, 0.5, 0.3), (-L * 0.28, 0.5, 0.3), (-L * 0.38, 0.5, 0.3)]
    r = _TYRE_R.get(st, 0.34)                                      # real tyre radii: 13" Yugo ~0.28 m, SUV ~0.38 m
    if st == "apc":                                                # BTR-80: four axles, big off-road tyres
        return [(2.30, 0.60, 0.40), (0.82, 0.60, 0.40), (-0.70, 0.60, 0.40), (-2.18, 0.60, 0.40)]
    return {"bus": [(L * 0.32, 0.50, 0.26), (-L * 0.30, 0.50, 0.26)],
            "truck": [(L * 0.36, 0.5, 0.34), (-L * 0.22, 0.5, 0.34), (-L * 0.36, 0.5, 0.34)],
            "tractor": [(L * 0.36, 0.45, 0.28), (-L * 0.28, 0.85, 0.5)]}.get(st, [(L * 0.31, r, 0.26), (-L * 0.31, r, 0.26)])


_BIKE_WHEELS = {"bike": (0.62, 0.34, 0.05), "kick": (0.46, 0.14, 0.05), "moped": (0.68, 0.27, 0.1), "scooter": (0.68, 0.24, 0.1)}


def _bike_wheel_model(kind):
    """(axle x of the front wheel, radius, model of one spokeless-looking wheel at the origin) for a two-wheeler."""
    ex = V.EXTRA[kind % V.N]
    x, r, wd = _BIKE_WHEELS[ex]
    v, c = _cyl(0.0, 0.0, 0.0, r, wd, np.array((24, 24, 26), np.float32),
                np.array((170, 170, 176), np.float32), rim=_BIKE_RIMS[ex])
    rgba = np.empty((len(v), 4), np.uint8)
    rgba[:, :3] = np.clip(c, 0, 255)
    rgba[:, 3] = 255
    model = object_detail(make_model(v, np.zeros((len(v), 2), np.float32), rgba), "vehicle", kind)
    return x, r, model


def front_wheel(kind):
    """(axle x, track half-width z, wheel model with its centre at the origin) of a car's front wheels, which the renderer
    turns by the steering angle (car_arrays(steer_wheels=True) leaves them out of the body)."""
    kind %= V.N
    name, style = V.IDS[kind], V.STYLE[kind]
    if style == "bike":
        x, r, m = _bike_wheel_model(kind)
        return x, r, 0.0, m
    L, W = visual_dims(kind)[:2]
    semi = V.EXTRA[kind] == "semi"
    wx, wr, wd = _wheel_layout(style, V.SEMI_TRACTOR_L if semi else L, name)[0]
    wx += V.SEMI_SHIFT if semi else 0.0
    lay = carbody.layout(name, L) if carbody.has(name) else None
    if style == "apc":
        v, c = _apc_wheel(0.0, 0.0, 0.0)
        track = APC_TRACK
    else:
        hub = np.array(lay["hub"] if lay else (158, 158, 164), np.float32)
        rim = lay["rim"] if lay else _COMMERCIAL_RIMS.get(name, ("truck", 5))
        v, c = _cyl(0.0, 0.0, 0.0, wr, wd, np.array((26, 26, 28), np.float32), hub, 16 if lay else 12, rim)
        track = carbody.wheel_track(W, wd) if lay else W / 2 - 0.02
    rgba = np.empty((len(v), 4), np.uint8)
    rgba[:, :3] = np.clip(c, 0, 255)
    rgba[:, 3] = 255
    model = object_detail(make_model(v, np.zeros((len(v), 2), np.float32), rgba), "vehicle", kind)
    return wx, wr, track, model


def rear_axles(kind):
    """[(axle x, radius, track half-width z, model of that axle's wheel pair with its centre at the origin)] of every axle behind the
    front one; the renderer spins them (steer_wheels=True models leave all wheels out of the body)."""
    kind %= V.N
    if V.STYLE[kind] == "bike":
        x, r, m = _bike_wheel_model(kind)
        return [(-x, r, 0.0, m)]
    L, W = visual_dims(kind)[:2]
    semi = V.EXTRA[kind] == "semi"
    name = V.IDS[kind]
    out = []
    for wx, wr, wd in _wheel_layout(V.STYLE[kind], V.SEMI_TRACTOR_L if semi else L, name)[1:]:
        lay = carbody.layout(name, L) if carbody.has(name) else None
        hub = np.array(lay["hub"] if lay else (176, 178, 184), np.float32)
        rim = lay["rim"] if lay else _COMMERCIAL_RIMS.get(name, ("truck", 5))
        track = carbody.wheel_track(W, wd) if lay else W / 2 - 0.02
        vs, cs = [], []
        for s in (-1, 1):
            apc = V.STYLE[kind] == "apc"
            v, c = _apc_wheel(0.0, 0.0, s * APC_TRACK, s) if apc else _cyl(0.0, 0.0, s * track, wr, wd, np.array((26, 26, 28), np.float32), hub, 16 if lay else 12, rim, s)
            vs.append(v)
            cs.append(c)
        v, c = np.concatenate(vs), np.concatenate(cs)
        rgba = np.empty((len(v), 4), np.uint8)
        rgba[:, :3] = np.clip(c, 0, 255)
        rgba[:, 3] = 255
        model = object_detail(make_model(v, np.zeros((len(v), 2), np.float32), rgba), "vehicle", kind)
        out.append((wx + (V.SEMI_SHIFT if semi else 0.0), wr, 0.0, model))
    return out


def car_arrays(kind, color, dents=(), burnt=0.0, player=False, steer_wheels=False):
    """car_arrays plus a material tag in uv.x for the gloss shader: 1 = paint, 2 = glass, 0 = matte.  The default shader
    samples a 1x1 white texture, so the tag changes nothing when gloss is off."""
    pos, uv, col = _car_arrays(kind, color, dents, burnt, player, steer_wheels)
    if burnt > 0 or len(pos) == 0:
        return pos, uv, col
    kind = kind % V.N
    fixed = V.FIXED[kind]
    two = color >= 12 and fixed is None
    ci = (color * 5 + 3) % 12 if two else color % 12
    body = np.array((206, 36, 36) if player else (fixed if fixed else CAR_COLORS[ci]), np.float32)
    c = col[:, :3].astype(np.float32)
    n = np.linalg.norm(c, axis=1) + 1e-3
    d = c / n[:, None]

    def near(ref, tol):
        r = np.asarray(ref, np.float32)
        return d @ (r / np.linalg.norm(r)) > 1 - tol

    paint = near(body, 0.002) & (n > 0.35 * np.linalg.norm(body))
    if two:
        paint |= near((236, 236, 240) if color % 2 == 0 else (30, 30, 34), 0.002) & (n > 25)
    uv[:, 0] = np.where(near(GLASS, 0.003) & (n < 200), 2.0, np.where(paint, 1.0, 0.0))
    return pos, uv, col


def _car_arrays(kind, color, dents=(), burnt=0.0, player=False, steer_wheels=False):
    """Vertices/colours of a car in local space (x forward, y up, z right); dents = [(lx, lz, nx, nz, mag)]."""
    kind = kind % V.N
    L, W, y0, belt, roof = visual_dims(kind)
    st = V.STYLE[kind]
    name = V.IDS[kind]
    ex = V.EXTRA[kind]
    semi = ex == "semi"
    if semi:
        L = V.SEMI_TRACTOR_L                                       # tractor unit only; the trailer is trailer_arrays, hinged at the fifth wheel
    top_h = roof                                                   # full height (cargo box on trucks)
    if st == "truck":
        roof = belt + 1.5                                          # cab roof
    fixed = V.FIXED[kind]
    two = color >= 12 and fixed is None
    ci = (color * 5 + 3) % 12 if two else color % 12
    body_c = np.array((206, 36, 36) if player else (fixed if fixed else CAR_COLORS[ci]), np.float32)
    accent = np.array((236, 236, 240) if color % 2 == 0 else (30, 30, 34), np.float32) if two else body_c
    if st == "bus":
        accent = np.array((40, 100, 190), np.float32)
    rng = np.random.RandomState(kind * 131 + color)
    parts = []                       # (verts, rgb per vertex, deformable)

    def A(c):
        return np.array(c, np.float32)

    def addf(faces, colfn, deform=True):
        for name, (v, n) in faces.items():
            parts.append((v, colfn(name, v, A(n)), deform))

    def quad(o, du, dv, n, col, nu=1, nv=1, deform=True, lst=None):
        v = grid_face(o, du, dv, nu, nv)
        c = np.tile(A(col) * _shade(A(n)), (len(v), 1))
        (parts if lst is None else lst).append((v, c, deform))

    def box(cx_, cy_, cz_, sx, sy, sz, col, deform=True, lst=None):
        for name, (v, n) in box_faces(cx_, cy_, cz_, sx, sy, sz).items():
            (parts if lst is None else lst).append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1)), deform))

    if st == "bike":
        _bike_parts(ex, body_c, A, box, quad, parts, not steer_wheels)
        return _finish_arrays(parts, dents, burnt, belt)
    if st == "heli":
        _heli_parts(body_c, A, box, quad, parts)
        return _finish_arrays(parts, dents, burnt, 1.0)
    if st == "apc":
        _apc_parts(body_c, A, box, quad, parts)
        for wx, wr, wd_ in ([] if steer_wheels else _wheel_layout(st, L)):
            for s_ in (-1, 1):
                v, c = _apc_wheel(wx, wr, s_ * APC_TRACK, s_)
                parts.append((v, c, False))
        return _finish_arrays(parts, dents, burnt, 1.4)
    if st in carbody.LOFT_STYLES and carbody.has(V.IDS[kind]):
        return _loft_arrays(kind, color, dents, burnt, player, steer_wheels, (L, W, y0, belt, roof, st, ex), (body_c, accent, two, rng),
                            parts, A, quad, box)

    # ---- lower body
    def body_col(name, v, n):
        sh = _shade(n)
        c = np.tile(body_c * sh, (len(v), 1))
        c = c * np.clip(0.72 + 0.4 * (v[:, 1:2] - y0) / (belt - y0), 0.6, 1.1)
        if st == "truck":                                                  # behind the cab the slab is the dark chassis frame
            k = np.clip((min(2.45, 0.27 * L) - (L / 2 - v[:, 0:1])) / 0.3, 0.0, 1.0)
            c = c * k + np.array((46, 48, 54), np.float32) * _shade(n) * (1 - k)
        return c
    add_box_h = belt - y0
    BW = W * 0.55 if st == "tractor" else W
    wheels = _wheel_layout(st, L, name)
    panels = box_faces(0, y0, 0, L, add_box_h, BW, 8 if L < 7 else 14, 2, 4)
    if st != "tractor":
        for side, key in ((-1, "left"), (1, "right")):
            z = side * BW / 2
            stations = {-L / 2: y0, L / 2: y0}
            for axle, radius, _ in wheels:
                reach = radius + 0.068
                for f in (-1, -.8, -.5, 0, .5, .8, 1):
                    x = axle + f * reach
                    if -L / 2 < x < L / 2:
                        stations[x] = max(y0, min(belt - 0.085, radius + reach * math.sqrt(1 - f*f)))
            rows = sorted(stations.items())
            triangles = []
            for (a, ya), (b, yb) in zip(rows, rows[1:]):
                lo, hi = (a, ya, z), (b, yb, z)
                up, vp = (a, belt, z), (b, belt, z)
                triangles.extend((lo, hi, vp, lo, vp, up) if side < 0 else (lo, vp, hi, lo, up, vp))
            panels[key] = (np.asarray(triangles, np.float32), (0, 0, side))
    addf(panels, body_col)

    cl_f, cx_f, ft, rt, stp, nwin = _CAB[st]
    if L > 11:
        nwin = 11 if name == "JSP Zglobni" else 9
    if name == "JSP Dvokatnik":
        ft, rt, stp, nwin = 0.020, 0.012, 0.026, 6
    elif name == "JSP Zglobni":
        ft, rt, stp = 0.036, 0.013, 0.023
    elif ex == "coach":
        ft, rt, stp, nwin = 0.12, 0.023, 0.046, 7
    elif st == "bus":
        ft, rt, stp, nwin = 0.065, 0.016, 0.018, 5
    elif name == "Voen Hamer":
        cl_f, cx_f, ft, rt, stp, nwin = 0.44, -0.015, 0.21, 0.028, 0.08, 2
    elif name == "Voena Niva":
        cl_f, cx_f, ft, rt, stp, nwin = 0.68, -0.105, 0.21, 0.13, 0.05, 2
    era = _ERA.get(_ERA_OF.get(V.IDS[kind]))
    if era is not None:
        ft, rt, stp = max(0.0, ft + era[3]), max(0.0, rt + era[4]), stp + era[5]
    cl, cx = L * cl_f, L * cx_f
    if st == "truck":                                                      # forward-control cab, 2.3-2.5 m long, flush with the nose
        cab_fraction = {"fire": 0.40, "armytruck": 0.29, "cargo": 0.28, "semi": 0.40,
                        "tanker": 0.24, "garbage": 0.31, "mixer": 0.27}.get(ex, 0.27)
        cl = min(2.85, cab_fraction*L)
        cx = L / 2 - cl / 2
        roof = min(top_h - 0.06, belt + (2.10 if ex == "semi" else 1.69))
    parts[:] = [(_shape_body(v, kind, st, L, W, y0, belt, cx, cl), c, d) for v, c, d in parts]
    H, cw = roof - belt, W * 0.9
    # ---- cabin (everything in `cab` gets the taper applied)
    cab = []
    side_c = accent if st in ("van",) else body_c
    for name, (v, n) in box_faces(cx, belt, 0, cl, H, cw, 4 if L < 7 else 8, 2, 3).items():
        n = A(n)
        if name == "top":
            cab.append((v, np.tile(np.clip(accent * 1.05 if two and st != "van" else body_c * 1.08, 0, 255) * _shade(n), (len(v), 1)), True))
        else:
            cab.append((v, np.tile(side_c * _shade(n), (len(v), 1)), True))
    gl = lambda n: A(GLASS) * (0.85 + 0.5 * _shade(A(n)))
    wy0, wy1 = belt + 0.10 * H, belt + 0.90 * H
    if st == "bus":
        wy0 = belt + 0.22
    gap = 0.16 if st == "bus" else 0.13
    x_lo, x_hi = cx - cl / 2 + 0.12, cx + cl / 2 - 0.12
    wl = (x_hi - x_lo - gap * (nwin - 1)) / nwin
    dd = st == "bus" and ex == "jsp" and roof > 4.0                          # double-decker: two rows of windows, a floor band between
    rows = [(wy0, belt + 1.30), (belt + 1.70, wy1)] if dd else [(wy0, wy1)]
    for s in (-1, 1):
        for r0, r1 in rows:
            for k in range(nwin):
                xa = x_lo + k * (wl + gap)
                quad((xa, r0, s * (cw / 2 + 0.012)), (wl, 0, 0), (0, r1 - r0, 0), (0, 0, s), gl((0, 0, s)), 2, 1, True, cab)
        if dd:                                                                # cream stripe along the upper-deck floor
            quad((cx - cl / 2 + 0.05, belt + 1.42, s * (cw / 2 + 0.014)), (cl - 0.1, 0, 0), (0, 0.16, 0), (0, 0, s), (232, 226, 200), 1, 1, True, cab)
    if st != "pickup" or True:
        if dd:
            for r0, r1 in ((belt + 0.22, belt + 1.30), (belt + 1.70, belt + 0.93 * H)):
                quad((cx + cl / 2 + 0.012, r0, -(cw / 2 - 0.09)), (0, 0, cw - 0.18), (0, r1 - r0, 0), (1, 0, 0), gl((1, 0, 0)), 2, 1, True, cab)
        else:
            quad((cx + cl / 2 + 0.012, belt + 0.07 * H, -(cw / 2 - 0.09)), (0, 0, cw - 0.18), (0, 0.86 * H, 0), (1, 0, 0), gl((1, 0, 0)), 2, 1, True, cab)
        quad((cx - cl / 2 - 0.012, belt + 0.10 * H, -(cw / 2 - 0.09)), (0, 0, cw - 0.18), (0, 0.78 * H, 0), (-1, 0, 0), gl((-1, 0, 0)), 2, 1, True, cab)
    if player:
        quad((cx - cl / 2, roof + 0.006, -0.16 * W), (cl, 0, 0), (0, 0, 0.32 * W), (0, 1, 0), (240, 240, 240), 2, 1, True, cab)
    if st == "taxi":
        box(cx, roof, 0, 0.42, 0.16, 0.6, (240, 240, 235), True, cab)
        box(cx, roof + 0.16, 0, 0.30, 0.05, 0.5, (30, 30, 34), True, cab)
    if st == "bus":
        box(cx - 1.0, roof, 0, 1.6, 0.22, 1.4, (190, 192, 196), True, cab)         # roof AC unit
        quad((cx + cl / 2 + 0.014, roof - 0.42, -0.9), (0, 0, 1.8), (0, 0.22, 0), (1, 0, 0), (255, 170, 30), 1, 1, True, cab)
    if st == "suv":
        for zz in (-0.62, 0.62):
            box(cx, roof + 0.0, zz * 0.9 * W / 1.4, cl * 0.9, 0.05, 0.05, (28, 28, 30), True, cab)
    if st == "truck":
        _truck_cab(parts, box, quad, A, gl, body_c, L, W, y0, belt, roof, cl, ex)
    for v, c, d in ([] if st == "truck" else cab):
        v = v.copy()
        t = np.clip((v[:, 1] - belt) / H, 0, 1.2)
        k = np.where(v[:, 0] > cx, ft, rt)
        v[:, 0] = cx + (v[:, 0] - cx) * (1 - k * t)
        v[:, 2] *= (1 - stp * t)
        parts.append((v, c, d))

    # ---- lower body details
    xf, xb = L / 2, -L / 2
    round_hl = V.IDS[kind] in _ROUND_LAMPS
    for s in (-1, 1):                                                       # headlights / taillights
        lz = s * 0.26 * W if s > 0 else -0.46 * W
        if round_hl:                                                        # round lamp: an octagon of two crossed quads in a chrome ring
            quad((xf + 0.004, belt - 0.36, lz - 0.01), (0, 0, 0.20 * W + 0.02), (0, 0.26, 0), (1, 0, 0), (200, 200, 204))
            quad((xf + 0.006, belt - 0.34, lz), (0, 0, 0.20 * W), (0, 0.22, 0), (1, 0, 0), (255, 244, 180))
        else:
            quad((xf + 0.006, belt - 0.34, lz), (0, 0, 0.20 * W), (0, 0.22, 0), (1, 0, 0), (255, 244, 180))
        quad((xb - 0.006, belt - 0.34, s * 0.26 * W if s > 0 else -0.46 * W), (0, 0, 0.20 * W), (0, 0.22, 0), (-1, 0, 0), (210, 30, 30))
    if st not in ("bus", "van"):
        quad((xf + 0.006, y0 + 0.16, -0.22 * W), (0, 0, 0.44 * W), (0, belt - y0 - 0.38, 0), (1, 0, 0), (28, 28, 32), 2, 1)       # grille
    if st == "bus":
        if dd:
            panel, trim = (154, 27, 35), (235, 227, 207)
        elif ex == "coach":
            panel, trim = (44, 49, 56), (171, 178, 185)
        elif name == "JSP Zglobni":
            panel, trim = (39, 41, 47), (138, 147, 156)
        else:
            panel, trim = (38, 37, 43), (189, 193, 195)
        quad((xf + 0.011, y0 + 0.16, -0.437*W), (0, 0, 0.874*W),
             (0, 0.26, 0), (1, 0, 0), panel)
        quad((xf + 0.013, y0 + 0.409, -0.437*W), (0, 0, 0.874*W),
             (0, 0.027, 0), (1, 0, 0), trim)
        for side in (-1, 1):
            if dd or name == "Gradski Avtobus":
                _disc(xf+0.016, y0+0.305, side*W*0.366, 0.10, 0.015, (220, 226, 220), parts, 9, "x")
            else:
                quad((xf+0.017, y0+0.23, side*W*0.366-0.13), (0, 0, 0.26),
                     (0, 0.095, 0), (1, 0, 0), (215, 224, 224))
    if st == "van":
        quad((xf + 0.006, belt - 0.5, -0.04), (0, 0, 0.08), (0, 0.42, 0), (1, 0, 0), (210, 210, 214))                       # VW "V"
    bump_c = (120, 122, 128) if st not in ("bus", "taxi") else (60, 62, 66)
    bh = 0.2 if st != "bus" else 0.3
    box(xf + 0.04, y0, 0, 0.12, bh, W * 1.0, bump_c)
    box(xb - 0.04, y0, 0, 0.12, bh, W * 1.0, bump_c)
    quad((xf + 0.106, y0 + 0.03, -0.2), (0, 0, 0.4), (0, 0.12, 0), (1, 0, 0), (236, 236, 226))
    quad((xb - 0.106, y0 + 0.03, -0.2), (0, 0, 0.4), (0, 0.12, 0), (-1, 0, 0), (236, 236, 226))
    for s in (-1, 1):
        zz = s * (W / 2 + 0.008)
        for dx in (cx + cl * 0.30, cx - cl * 0.20):                         # door lines
            if st != "bus":
                quad((dx, y0 + 0.14, zz), (0.03, 0, 0), (0, belt - y0 - 0.14, 0), (0, 0, s), (22, 22, 25))
        if st == "taxi":
            for k in range(14):
                col = (20, 20, 22) if k % 2 else (240, 240, 235)
                quad((xb + 0.35 + k * (L - 0.7) / 14, belt - 0.34, zz), ((L - 0.7) / 14, 0, 0), (0, 0.14, 0), (0, 0, s), col)
        if st == "bus":
            quad((xb + 0.2, belt - 0.42, zz), (L - 0.4, 0, 0), (0, 0.22, 0), (0, 0, s), tuple(accent))
            if s > 0:
                for dx in (L * 0.30, -L * 0.18):
                    quad((dx, y0 + 0.08, zz + 0.004), (1.1, 0, 0), (0, (1.8 if dd else roof - y0 - 0.5), 0), (0, 0, 1), (58, 72, 96), 1, 2)
        mx = cx + cl / 2 - 0.12
        box(mx, belt + 0.18, s * (W / 2 + 0.08), 0.1, 0.1, 0.16, (40, 40, 44))      # mirrors
        if st == "bus":                                                              # big arm-mounted rear-view mirrors
            box(mx - 0.1, belt + 0.55, s * (W / 2 + 0.22), 0.05, 0.42, 0.22, (30, 30, 34))
            box(mx - 0.1, belt + 0.2, s * (W / 2 + 0.12), 0.05, 0.05, 0.22, (30, 30, 34))
    if st == "pickup":
        bx0 = cx - cl / 2 - 0.02
        quad((xb + 0.05, belt + 0.004, -W / 2 + 0.06), (bx0 - xb - 0.05, 0, 0), (0, 0, W - 0.12), (0, 1, 0), (46, 44, 42), 2, 2)
        for s in (-1, 1):
            box((xb + bx0) / 2, belt, s * (W / 2 - 0.05), bx0 - xb, 0.28, 0.08, tuple(body_c * 0.95))
        box(xb + 0.05, belt, 0, 0.08, 0.28, W - 0.1, tuple(body_c * 0.95))
        box(bx0 - 0.05, belt, 0, 0.08, 0.3, W - 0.1, tuple(body_c * 0.9))
    if name == "Voen Hamer":
        for side in (-1,1):
            box(xf-L*0.152, y0+0.14, side*(W/2-0.064), 0.86, 0.19, 0.17, body_c*0.79)
            _disc(xf+0.008, belt-0.095, side*W*0.375, 0.12, 0.015, (200,203,188), parts, 8, "x")
        for i in range(-3, 4):
            quad((xf+0.019, y0+0.225, i*0.079-0.025), (0,0,0.05), (0,0.19,0), (1,0,0), (42,47,42))
    if name == "Voena Niva":
        for side in (-1,1):
            _disc(xf+0.008, belt-0.115, side*W*0.37, 0.103, 0.015, (214,218,208), parts, 8, "x")
            quad((xf+0.016, belt-0.018, side*W*0.37-0.082), (0,0,0.165), (0,0.048,0), (1,0,0), (204,128,60))
    if st == "suv" and name != "Voen Hamer":
        box(xb - 0.2, y0 + 0.1, 0, 0.18, 0.62, 0.62, (30, 30, 32), True)
        box(xb - 0.3, y0 + 0.2, 0, 0.02, 0.42, 0.42, (70, 72, 76), True)
    if rng.rand() < 0.35 and st not in ("bus",):                             # a bit of rust / dirt
        for _ in range(2):
            rx = rng.uniform(-L * 0.35, L * 0.35)
            s = rng.choice((-1, 1))
            quad((rx, y0 + 0.02, s * (W / 2 + 0.009)), (rng.uniform(0.3, 0.7), 0, 0), (0, rng.uniform(0.15, 0.3), 0), (0, 0, s), (112, 62, 38))
    # small details: number plates, door seams and handles, dark wheel-arch shadows, side sills
    quad((xf + 0.012, y0 + 0.08, -0.25), (0, 0, 0.5), (0, 0.12, 0), (1, 0, 0), (236, 236, 230))
    quad((xf + 0.014, y0 + 0.08, -0.25), (0, 0, 0.06), (0, 0.12, 0), (1, 0, 0), (30, 60, 170))
    quad((xb - 0.012, y0 + 0.12, 0.25), (0, 0, -0.5), (0, 0.12, 0), (-1, 0, 0), (236, 236, 230))
    for s in (-1, 1):
        zs = s * (W / 2 + 0.008)
        for dxs in ((cx + cl * 0.05,) if st in ("bus", "truck") else (cx + cl * 0.05, cx - cl * 0.42)):
            quad((dxs, y0 + 0.1, zs), (0.025, 0, 0), (0, belt - y0 - 0.1, 0), (0, 0, s), tuple(body_c * 0.55))
            quad((dxs + 0.12, belt - 0.16, zs + s * 0.004), (0.16, 0, 0), (0, 0.04, 0), (0, 0, s), (40, 40, 44))
        if st == "tractor":
            quad((xb + 0.05, y0 - 0.02, zs), (xf - xb - 0.1, 0, 0), (0, 0.07, 0), (0, 0, s), (40, 40, 42))
        else:
            for (a, r0, _), (b, r1, _) in zip(reversed(wheels[1:]), reversed(wheels[:-1])):
                start, stop = a + r0 + 0.069, b - r1 - 0.069
                if start < stop:
                    quad((start, y0 - 0.02, zs), (stop-start, 0, 0), (0, 0.06, 0), (0, 0, s), (40, 40, 42))
    if name == "JSP Zglobni":
        joint = V.ARTIC_HINGE
        box(joint, y0, 0, 0.76, roof - y0, W*1.014, (43, 43, 46))
        for k in range(8):
            x = joint - 0.326 + k*0.093
            for side in (-1, 1):
                quad((x, y0, side*W*0.513), (0.029, 0, 0), (0, roof-y0, 0), (0, 0, side), (70, 71, 74))
    if st == "tractor":
        box(xf - 0.78, belt - 0.06, 0, 1.43, 0.35, W * 0.40, body_c * 0.96)
        for k in range(5):
            quad((xf - 0.057, belt-0.012+k*0.050, -W*0.184), (0, 0, W*0.368), (0, 0.021, 0), (1, 0, 0), (65, 69, 72))
        for side in (-1, 1):
            box(xb + 0.75, 1.59, side*W*0.43, 1.10, 0.10, 0.37, body_c)
    if st == "bus":
        for side in (-1, 1):
            for yf, color in ((y0+0.14, (215, 50, 44)), (y0+0.26, (220, 138, 52))):
                quad((xb-0.018, yf, side*W*0.35 - 0.14), (0, 0, 0.28), (0, 0.084, 0), (-1, 0, 0), color)
        if ex == "coach":
            for k in range(3):
                xx = xb + 1.55 + k * 1.42
                for side in (-1, 1):
                    quad((xx, y0+0.07, side*(W/2+0.013)), (0.021, 0, 0), (0, 0.67, 0), (0, 0, side), (84, 86, 90))
    _extras(kind, st, ex, L, W, y0, belt, roof, top_h, cx, cl, cw, body_c, accent, parts, box, quad, cab_ref=None)
    for wi, (wx, wr, wd_) in enumerate(wheels):                             # wheels (not deformable)
        if steer_wheels:
            continue                                                        # the front pair is drawn separately, turned
        for s in (-1, 1):
            v, c = _cyl(wx, wr, s * (W / 2 - 0.02), wr, wd_, A((26, 26, 28)), A((176, 178, 184)), 12, _COMMERCIAL_RIMS.get(name, ("truck", 5)), s)
            parts.append((v, c, False))

    if fixed == V.ARMY:
        _camo_parts(parts, body_c)
    if semi:                                                                # move the short tractor to the front of the rig's footprint
        parts[:] = [(v + np.array((V.SEMI_SHIFT, 0, 0), np.float32), c, d) for v, c, d in parts]
    return _finish_arrays(parts, dents, burnt, belt)


def _loft_arrays(kind, color, dents, burnt, player, steer_wheels, dims, look, parts, A, quad, box):
    """Car-like vehicles built from carbody's real profile; roof furniture, extras and wheels as for every other model."""
    L, W, y0, belt, roof, st, ex = dims
    body_c, accent, two, rng = look
    name = V.IDS[kind]
    lay = carbody.layout(name, L)
    wheels = _wheel_layout(st, L, name)
    parts += carbody.build(name, L, W, belt, roof, body_c, accent, two, _shade, (58, 76, 98), wheels[0][1])
    cx, cl, cw = lay["cx"], lay["cl"], W * 0.9
    yb = carbody.spec(name, L)["gc"]
    if player:
        quad((cx - cl / 2, roof + 0.006, -0.16 * W), (cl, 0, 0), (0, 0, 0.32 * W), (0, 1, 0), (240, 240, 240), 2, 1)
    if st == "taxi":
        box(cx, roof, 0, 0.42, 0.16, 0.6, (240, 240, 235))
        box(cx, roof + 0.16, 0, 0.30, 0.05, 0.5, (30, 30, 34))
        for s in (-1, 1):
            zz = s * (W / 2 + 0.01)
            for k in range(14):
                quad((-L / 2 + 0.35 + k * (L - 0.7) / 14, belt - 0.34, zz), ((L - 0.7) / 14, 0, 0), (0, 0.14, 0), (0, 0, s),
                     (20, 20, 22) if k % 2 else (240, 240, 235))
    if st == "suv":
        for zz in (-0.62, 0.62):
            box(cx, roof, zz * 0.9 * W / 1.4, cl * 0.9, 0.05, 0.05, (28, 28, 30))
    if rng.rand() < 0.35:                                                    # a bit of rust / dirt
        for _ in range(2):
            rx = rng.uniform(-L * 0.35, L * 0.35)
            s = rng.choice((-1, 1))
            quad((rx, yb + 0.04, s * (W / 2 + 0.009)), (rng.uniform(0.3, 0.7), 0, 0), (0, rng.uniform(0.15, 0.3), 0), (0, 0, s), (112, 62, 38))
    _extras(kind, st, ex, L, W, y0, belt, roof, roof, cx, cl, cw, body_c, accent, parts, box, quad, cab_ref=None)
    for wi, (wx, wr, wd_) in enumerate(wheels):
        if steer_wheels:
            continue
        for s in (-1, 1):
            v, c = _cyl(wx, wr, s * carbody.wheel_track(W, wd_), wr, wd_, A((26, 26, 28)), A(lay["hub"]), 16, lay["rim"], s)
            parts.append((v, c, False))
    return _finish_arrays(parts, dents, burnt, belt)


def trailer_arrays(wheels=True):
    """Semi trailer, origin at the kingpin, extending towards -x; hinged to the tractor's fifth wheel by the renderer."""
    A = lambda c: np.array(c, np.float32)
    parts = []
    W, T, y0, top = 2.55, V.SEMI_TRAILER_L, 0.95, 4.05
    def box(cx_, cy_, cz_, sx, sy, sz, col):
        for _n, (v, n) in box_faces(cx_, cy_, cz_, sx, sy, sz).items():
            parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1)), False))
    def quad(o, du, dv, n, col):
        v = grid_face(o, du, dv, 1, 1)
        parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1)), False))
    box(-T / 2 + 0.3, y0, 0, T, top - y0, W, (214, 216, 220))                      # box body
    box(-T / 2 + 0.3, 0.62, 0, T - 0.4, 0.3, 0.9, (40, 42, 46))                    # chassis beam under it
    box(-0.1, 0.78, 0, 0.5, 0.2, 0.9, (40, 42, 46))                                 # kingpin plate
    box(-2.6, 0.3, 0.7, 0.14, 0.7, 0.14, (60, 62, 68))                              # landing legs
    box(-2.6, 0.3, -0.7, 0.14, 0.7, 0.14, (60, 62, 68))
    for sd in (-1, 1):
        zs = sd * (W / 2 + 0.012)
        quad((-T + 0.6, y0 + 1.1, zs), (T - 0.9, 0, 0), (0, 0.55, 0), (0, 0, sd), (40, 90, 170))   # livery stripe
        quad((-T + 0.4, y0 - 0.02, zs), (T - 0.6, 0, 0), (0, 0.12, 0), (0, 0, sd), (40, 42, 46))   # lower skirt rail
        for k in range(1, 5):
            quad((-k * T/5 + 0.04, y0+0.025, zs+sd*0.005), (0.15, 0, 0), (0, 0.058, 0), (0, 0, sd), (227, 143, 52))
        for x in np.linspace(-T+0.60, -0.07, 12):
            quad((x, y0+0.12, zs+sd*0.004), (0.039, 0, 0), (0, 0.62, 0), (0, 0, sd), (114, 121, 130))
        for k in range(1, 6):                                                        # panel ribs
            quad((-k * T / 6.0, y0 + 0.1, zs), (0.05, 0, 0), (0, top - y0 - 0.2, 0), (0, 0, sd), (176, 178, 184))
        box(-T + 0.15, y0 + 0.2, sd * (W / 2 - 0.2), 0.1, 0.18, 0.2, (210, 30, 30))      # tail lamps
        box(-T - 0.05, 0.62, sd * (W / 2 - 0.3), 0.04, 0.45, 0.5, (30, 30, 34))          # mudflaps
    quad((-T + 0.3 - 0.01, y0 + 0.1, -W / 2 + 0.05), (0, 0, W - 0.1), (0, top - y0 - 0.2, 0), (-1, 0, 0), (200, 202, 208))  # rear doors
    quad((-T + 0.3 - 0.012, y0 + 0.1, -0.015), (0, 0, 0.03), (0, top - y0 - 0.2, 0), (-1, 0, 0), (60, 62, 68))
    box(-T + 0.2, 0.62, 0, 0.1, 0.12, W * 0.92, (60, 62, 68))                         # underride bar
    for z in (-0.22, 0.22):
        quad((-T+0.279, y0+0.23, z), (0, 0, 0.034), (0, top-y0-0.48, 0), (-1, 0, 0), (113, 116, 123))
    for ax in ((-T + 1.4, -T + 2.6, -T + 3.8) if wheels else ()):                    # tri-axle (the renderer spins them otherwise)
        for sd in (-1, 1):
            v, c = _cyl(ax, 0.5, sd * (W / 2 - 0.02), 0.5, 0.3, A((26, 26, 28)), A((176, 178, 184)), 12, ("truck", 5), sd)
            parts.append((v, c, False))
    return _finish_arrays(parts, (), 0.0, y0)


def trailer_model():
    pos, uv, col = trailer_arrays(False)
    return object_detail(make_model(pos, uv, col), "metal", 5)


def trailer_axles():
    """([axle x from the kingpin], radius, model of one axle's wheel pair at the origin) of the semi trailer."""
    A = lambda c: np.array(c, np.float32)
    T, W = V.SEMI_TRAILER_L, 2.55
    vs, cs = [], []
    for sd in (-1, 1):
        v, c = _cyl(0.0, 0.0, sd * (W / 2 - 0.02), 0.5, 0.3, A((26, 26, 28)), A((176, 178, 184)), 12, ("truck", 5), sd)
        vs.append(v)
        cs.append(c)
    v, c = np.concatenate(vs), np.concatenate(cs)
    rgba = np.empty((len(v), 4), np.uint8)
    rgba[:, :3] = np.clip(c, 0, 255)
    rgba[:, 3] = 255
    wheels = object_detail(make_model(v, np.zeros((len(v), 2), np.float32), rgba), "vehicle", 5)
    return (-T + 1.4, -T + 2.6, -T + 3.8), 0.5, wheels


def _finish_arrays(parts, dents, burnt, belt):
    """Join the parts, push the dents in, scorch the paint."""
    pos = np.concatenate([p[0] for p in parts])
    col = np.concatenate([p[1] for p in parts]).astype(np.float32)
    deform = np.concatenate([np.full(len(p[0]), p[2]) for p in parts])
    pos0 = pos.copy() if dents else pos
    for (lx, lz, nx, nz, mag) in dents:
        d = np.hypot(pos[:, 0] - lx, pos[:, 2] - lz)
        rad = 0.9 + mag * 1.6
        f = np.clip(1 - d / rad, 0, 1) ** 1.6 * deform
        wob = np.sin(pos[:, 0] * 9.1 + pos[:, 2] * 7.3 + lx * 3) * 0.04 * mag
        pos[:, 0] += nx * mag * f + wob * f
        pos[:, 2] += nz * mag * f + wob * f
        pos[:, 1] -= 0.10 * mag * f * (pos[:, 1] > belt - 0.2)
        col *= (1 - 0.45 * np.clip(f * mag * 2.2, 0, 1))[:, None]
        col[(f > 0.35), 0] += 18
    if dents:                                         # many hits on one spot (a wreck traffic keeps running into) pushed a panel
        for ax, k in ((0, 0.22), (2, 0.30)):          # through the cabin and out the far side: crumple at most this share of the car
            lim = k * (pos0[:, ax].max() - pos0[:, ax].min())
            np.clip(pos[:, ax], pos0[:, ax] - lim, pos0[:, ax] + lim, out=pos[:, ax])
    if burnt > 0:
        col = col * (1 - 0.8 * burnt) + 14 * burnt
    col = np.clip(col, 0, 255)
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = col
    rgba[:, 3] = 255
    return pos.astype(np.float32), np.zeros((len(pos), 2), np.float32), rgba


def door_geom(kind):
    """Driver's door: (hinge x, door length) in car-local space (see vehicles.door_geom)."""
    return V.door_geom(kind)


def door_model(kind, color):
    """The swinging door panel; hinge at the origin, panel along -x, outer face toward -z."""
    L, W, y0, belt, roof = visual_dims(kind)
    _hx, dl = door_geom(kind)
    fixed = V.FIXED[kind]
    two = color >= 12 and fixed is None
    ci = (color * 5 + 3) % 12 if two else color % 12
    bc = (206, 36, 36) if color < 0 else (fixed if fixed else CAR_COLORS[ci])
    H = (belt + 1.5 if V.STYLE[kind] == "truck" else roof) - belt
    parts = []
    for y_, h_, c_, t_ in ((y0 + 0.1, belt - y0 - 0.1, bc, 0.07), (belt, 0.75 * H, GLASS, 0.03), (belt + 0.75 * H, 0.05, bc, 0.05)):
        for name, (v, n) in box_faces(-dl / 2, y_, 0, dl, h_, t_).items():
            parts.append((v, np.tile(np.array(c_, np.float32) * _shade(np.array(n, np.float32)), (len(v), 1))))
    pos = np.concatenate([q[0] for q in parts]).astype(np.float32)
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(np.concatenate([q[1] for q in parts]), 0, 255)
    rgba[:, 3] = 255
    return object_detail(make_model(pos, np.zeros((len(pos), 2), np.float32), rgba), "paint", kind)


_BUS_BELLOWS_HALF = 0.58
_BUS_BELLOWS_OVERLAP = 0.06


def _bus_section(arrays, rear=False):
    """Trim the existing bus shell at the bellows, preserving materials on cut triangles."""
    pos, uv, col = arrays
    side = -1 if rear else 1
    cut = V.ARTIC_HINGE + side * _BUS_BELLOWS_HALF
    dist = ((pos[:, 0] - cut) * side).reshape(-1, 3)
    inside = dist >= 0
    keep = np.repeat(inside.all(axis=1), 3)
    edges = np.flatnonzero(inside.any(axis=1) & ~inside.all(axis=1))
    attrs = np.column_stack((pos, uv, col)).reshape(-1, 3, 9)
    clipped = []
    for i in edges:
        face = []
        for j in range(3):
            a, b = attrs[i, j - 1], attrs[i, j]
            da, db = dist[i, j - 1], dist[i, j]
            if (da >= 0) != (db >= 0):
                face.append(a + (b - a) * da / (da - db))
            if db >= 0:
                face.append(b)
        for j in range(1, len(face) - 1):
            clipped.extend((face[0], face[j], face[j + 1]))
    if not clipped:
        return pos[keep], uv[keep], col[keep]
    cut_vertices = np.asarray(clipped, dtype=np.float32)
    return (np.concatenate((pos[keep], cut_vertices[:, :3])),
            np.concatenate((uv[keep], cut_vertices[:, 3:5])),
            np.concatenate((col[keep], np.rint(cut_vertices[:, 5:]).astype(np.uint8))))


def bus_rear_model():
    arrays = car_arrays(V.ARTIC_BUS, 0, steer_wheels=True)
    return gloss_apply(make_model(*_bus_section(arrays, rear=True)), V.ARTIC_BUS)


def bus_bellows_arrays(bend):
    """The folds span the front and rear cross-sections at the given articulation angle."""
    _, width, bottom, _, top = visual_dims(V.ARTIC_BUS)
    hinge, gap = V.ARTIC_HINGE, _BUS_BELLOWS_HALF + _BUS_BELLOWS_OVERLAP
    c, s = math.cos(bend), math.sin(bend)
    rings = []
    for i in range(13):
        f = i / 12
        w = width * 0.5 - (0.05 if i % 2 else 0.0)
        roof = top - (0.045 if i % 2 else 0.015)
        rings.append([((1 - f) * (hinge + gap) + f * (hinge - gap * c - z * s), y,
                       (1 - f) * z + f * (-gap * s + z * c))
                      for y, z in ((bottom, w), (roof, w), (roof, -w), (bottom, -w))])
    pos, colors = [], []
    for i, (a, b) in enumerate(zip(rings, rings[1:])):
        for j in range(4):
            k = (j + 1) % 4
            pos.extend((a[j], a[k], b[k], a[j], b[k], b[j]))
            shade = (59 if i % 2 == 0 else 39) + (9 if j == 1 else 0)
            colors.extend([(shade, shade, shade + 3, 255)] * 6)
    return np.asarray(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.asarray(colors, np.uint8)


def car_scene_arrays(kind, color, dents=(), burnt=0.0, player=False):
    arrays = car_arrays(kind, color, dents, burnt, player, steer_wheels=True)
    return _bus_section(arrays) if kind == V.ARTIC_BUS else arrays


def car_model(kind, color, dents=(), burnt=0.0, player=False, steer_wheels=False, scene=False):
    pos, uv, col = car_scene_arrays(kind, color, dents, burnt, player) if scene else car_arrays(kind, color, dents, burnt, player, steer_wheels)
    return gloss_apply(make_model(pos, uv, col), car_material_variant(kind, color))


def car_material_variant(kind, color):
    """Keep material variation consistent between the car's render models."""
    if kind == V.ARTIC_BUS:
        return kind  # The shared rear body uses the same material as the front.
    return kind + 7 * color


# ------------------------------------------------------------------ glossy cars: clear-coat / metallic paint and reflective glass
# One extra shader, no extra draw calls: procedural sky/cloud reflections and sun/moon highlight.
OBJECT_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp; uniform mat4 matModel;
out vec4 fragColor; out vec3 wp; out vec3 localPos; out vec2 uv;
void main(){ fragColor = vertexColor; uv = vertexTexCoord; localPos = vertexPosition;
             wp = (matModel * vec4(vertexPosition, 1.0)).xyz;
             gl_Position = mvp * vec4(vertexPosition, 1.0); }"""
OBJECT_FS = """#version 330
in vec4 fragColor; in vec3 wp; in vec3 localPos; in vec2 uv;
uniform sampler2D texture0;
uniform vec4 colDiffuse; uniform vec4 colSpecular;
uniform vec3 SUNL;
out vec4 finalColor;
""" + surfacepack.SHADER + """void main(){
  vec4 base = texture(texture0, uv) * colDiffuse * fragColor;
  if (generatedSurfaces == 2){
    float family = round(colSpecular.r * 255.0);
    float variant = round(colSpecular.g * 255.0);
    bool interior = family == 27.0;
    if (interior) {
      family = uv.x;
      if (family > 24.0) { finalColor = base; return; }
    }
    float lum = dot(base.rgb, vec3(0.299, 0.587, 0.114));
    vec3 localN = normalize(cross(dFdx(localPos), dFdy(localPos)));
    vec3 n = normalize(cross(dFdx(wp), dFdy(wp)));
    if (family == 25.0) {
      vec2 slot = floor(clamp(uv, vec2(0.0), vec2(0.99999)) * vec2(4.0, 2.0));
      float tile = slot.x + 4.0 * slot.y;
      family = tile >= 7.0 ? 16.0 : (tile >= 6.0 ? 17.0 : (tile == 0.0 && lum < 0.24 ? 15.0 : 14.0));
      variant = mod(variant + tile * 3.0, 20.0);
    } else if (family == 26.0) {
      if (uv.x > 1.5) { finalColor = base; return; }
      family = uv.x > 0.5 ? 20.0 : (lum < 0.18 ? 21.0 : (base.r - base.b > 0.14 ? 11.0 : (lum > 0.55 ? 7.0 : 22.0)));
    }
    float repeatM = family >= 14.0 && family <= 19.0 ? 0.48 : (family >= 20.0 && family <= 22.0 ? 0.60 : 2.2);
    vec2 materialUV = surfaceProjection(localPos, localN) / repeatM;
    vec4 detail = interior ? surfaceSample(materialUV, localPos.xz, family, 0.75) :
                             objectSample(materialUV, family, variant);
    vec3 bumped = surfaceNormal(wp, n, detail.a, surfaceAmplitude(family));
    float light = clamp(1.0 + 0.55 * (dot(bumped, SUNL) - dot(n, SUNL)), 0.64, 1.36);
    base.rgb *= mix(vec3(1.0), detail.rgb * 2.0, family == 16.0 ? 0.28 : 0.70) * light;
  }
  finalColor = base;
}"""
_object_shader = None
_OBJECT_ROLES = {name: i for i, name in enumerate(surfacepack.EXPANDED_FAMILIES + ("character", "vehicle", "interior"))}


def object_detail(model, role, variant=0):
    """Give a mesh a stable material family and variant in the expanded pack."""
    global _object_shader
    if model is None:
        return None
    if _object_shader is None:
        sh = rl.load_shader_from_memory(OBJECT_VS, OBJECT_FS)
        if sh.id and sh.id != rl.rl_get_shader_id_default():
            _sun_register(sh)
            surfacepack.register(sh)
            sh.locs[rl.SHADER_LOC_COLOR_SPECULAR] = rl.get_shader_location(sh, "colSpecular")
            _object_shader = sh
        else:
            _object_shader = False
    if _object_shader:
        material = model.materials[0]
        material.shader = _object_shader
        material.maps[rl.MATERIAL_MAP_SPECULAR].color = rl.Color(_OBJECT_ROLES[role], int(variant) % 20, 0, 255)
        surfacepack.track(model)
    return model


CAR_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp; uniform mat4 matModel;
out vec4 fragColor; out vec3 wp; out vec3 localPos; out float mat;
void main(){ fragColor = vertexColor; mat = vertexTexCoord.x; localPos = vertexPosition; wp = (matModel * vec4(vertexPosition, 1.0)).xyz;
             gl_Position = mvp * vec4(vertexPosition, 1.0); }"""
CAR_FS = """#version 330
in vec4 fragColor; in vec3 wp; in vec3 localPos; in float mat;
uniform vec4 colDiffuse; uniform vec4 colSpecular;
uniform vec3 SUNL; uniform vec3 viewPos;
uniform vec4 gloss;              // x = strength (0 = exactly the plain look), y = light-source strength
uniform vec3 skyZ; uniform vec3 skyH; uniform vec3 grnd; uniform vec3 lightC; uniform vec3 lightD;
out vec4 finalColor;
""" + surfacepack.SHADER + """
float cloudNoise(vec3 p){
  vec3 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  vec3 h = vec3(17.0, 59.0, 113.0);
  float n = dot(i, h);
  vec4 a = fract(sin(n + vec4(0.0, 17.0, 59.0, 76.0)) * 43758.5453);
  vec4 b = fract(sin(n + vec4(113.0, 130.0, 172.0, 189.0)) * 43758.5453);
  return mix(mix(mix(a.x, a.y, f.x), mix(a.z, a.w, f.x), f.y),
             mix(mix(b.x, b.y, f.x), mix(b.z, b.w, f.x), f.y), f.z);
}
vec3 reflectedSky(vec3 R){
  vec3 env = R.y > 0.0 ? mix(skyH, skyZ, sqrt(R.y)) : mix(skyH * 0.7, grnd, clamp(-R.y * 4.0, 0.0, 1.0));
  // Direction-space texture stays fixed in the world as the car or camera turns.
  // 3D noise avoids a panorama seam and stretching at the zenith.
  vec3 p = R * vec3(6.0, 12.0, 6.0) + vec3(3.2, 0.7, 8.1);
  float clouds = cloudNoise(p) * 0.65 + cloudNoise(p * 2.03) * 0.25 + cloudNoise(p * 4.07) * 0.10;
  float coverage = smoothstep(0.45, 0.67, clouds) * smoothstep(0.0, 0.16, R.y);
  // The same live palette makes clouds white by day, warm at dusk, dim blue at night.
  vec3 cloudColor = skyH * 0.85 + lightC * (0.25 * gloss.y);
  return mix(env, cloudColor, coverage * 0.85);
}
void main(){
  vec4 base = colDiffuse * fragColor;
  vec3 N = normalize(cross(dFdx(wp), dFdy(wp)));
  if (generatedSurfaces == 2 && mat < 1.5){
    float lum = dot(base.rgb, vec3(0.299, 0.587, 0.114));
    float family = mat > 0.5 ? 20.0 : (lum < 0.13 ? 21.0 : 22.0);
    vec3 localN = normalize(cross(dFdx(localPos), dFdy(localPos)));
    vec4 detail = objectSample(surfaceProjection(localPos, localN) / 0.65, family, round(colSpecular.r * 255.0));
    vec3 bumped = surfaceNormal(wp, N, detail.a, surfaceAmplitude(family));
    base.rgb *= mix(vec3(1.0), detail.rgb * 2.0, 0.45)
              * clamp(1.0 + 0.48 * (dot(bumped, lightD) - dot(N, lightD)), 0.73, 1.27);
    N = bumped;
  }
  float k = gloss.x * step(0.5, mat);
  if (k <= 0.0) { finalColor = base; return; }
  vec3 V = normalize(viewPos - wp);
  if (dot(N, V) < 0.0) N = -N;
  float nv = clamp(dot(N, V), 0.0, 1.0);
  vec3 R = reflect(-V, N);
  vec3 env = reflectedSky(R);
  float fr = pow(1.0 - nv, 5.0);
  float lit = clamp(dot(N, lightD) * 4.0, 0.0, 1.0) * gloss.y;
  vec3 spec = lightC * (pow(max(dot(R, lightD), 0.0), 220.0) * 3.0) * lit;
  vec3 c;
  if (mat > 1.5) {                                                // glass: a mirror at grazing angles, see-through-dark head on
    float r = clamp(k * (0.38 + 0.62 * fr), 0.0, 0.95);
    c = mix(base.rgb, env, r) + spec * k;
  } else {                                                        // paint: metallic flake tinted by the paint + clear coat
    float r = clamp(k * (0.18 + 0.65 * fr), 0.0, 0.9);
    vec3 flake = base.rgb * lightC * pow(max(dot(N, normalize(lightD + V)), 0.0), 24.0) * 0.55 * lit;
    c = base.rgb * (1.0 - 0.35 * r) + env * r + (flake + spec * 0.8) * k;
  }
  finalColor = vec4(c, base.a);
}"""
_gloss = {"on": False, "sh": None, "loc": None}


def _gloss_shader():
    if _gloss["sh"] is None:
        sh = rl.load_shader_from_memory(CAR_VS, CAR_FS)
        _gloss["sh"] = sh
        _gloss["loc"] = {n: rl.get_shader_location(sh, n) for n in ("viewPos", "gloss", "skyZ", "skyH", "grnd", "lightC", "lightD")}
        _sun_register(sh)
        surfacepack.register(sh)
        sh.locs[rl.SHADER_LOC_COLOR_SPECULAR] = rl.get_shader_location(sh, "colSpecular")
    return _gloss["sh"]


def gloss_apply(model, variant=0):
    """Give a car its paint and glass shader when gloss is enabled."""
    if model is None or not _gloss["on"]:
        return object_detail(model, "vehicle", variant)
    material = model.materials[0]
    material.shader = _gloss_shader()
    material.maps[rl.MATERIAL_MAP_SPECULAR].color = rl.Color(int(variant) % 20, 0, 0, 255)
    surfacepack.track(model)
    return model


def _mix(a, b, t):
    return [x + (y - x) * t for x, y in zip(a, b)]


def gloss_frame(cam_pos, hour, dark, sun, on, strength):
    """Once a frame: camera position, sky colours and the light (sun by day, moon by night) for the car shader."""
    _gloss["on"] = bool(on)
    if _gloss["sh"] is None and not on:
        return
    sh, loc = _gloss_shader(), _gloss["loc"]
    sun = np.asarray(SUN if sun is None else sun, np.float64)
    elev = max(0.0, float(sun[1]))
    low = 1.0 - min(1.0, elev / 0.35)                                  # 1 near sunrise / sunset
    zen = _mix((0.36, 0.55, 0.82), (0.30, 0.33, 0.52), low)
    hor = _mix((0.76, 0.84, 0.92), (0.98, 0.62, 0.38), low)
    sunc = _mix((1.0, 0.97, 0.9), (1.0, 0.62, 0.35), low)
    zen = _mix(zen, (0.03, 0.05, 0.10), dark)
    hor = _mix(hor, (0.10, 0.12, 0.18), dark)
    moon = np.array([0.35, 0.75, -0.55]) / np.linalg.norm([0.35, 0.75, -0.55])
    ld = sun if dark < 0.5 else moon
    lc = _mix(sunc, (0.55, 0.62, 0.8), dark)
    li = (1.0 - dark) if dark < 0.5 else 0.35 * dark
    vals = {"viewPos": (cam_pos.x, cam_pos.y, cam_pos.z), "skyZ": zen, "skyH": hor, "grnd": _mix((0.33, 0.32, 0.3), (0.05, 0.05, 0.06), dark),
            "lightC": lc, "lightD": ld}
    for n, v in vals.items():
        if loc[n] >= 0:
            rl.set_shader_value(sh, loc[n], ffi.new("float[3]", [float(x) for x in v]), rl.SHADER_UNIFORM_VEC3)
    if loc["gloss"] >= 0:
        rl.set_shader_value(sh, loc["gloss"], ffi.new("float[4]", [float(strength) if on else 0.0, float(li), 0.0, 0.0]), rl.SHADER_UNIFORM_VEC4)


# ------------------------------------------------------------------ pedestrians
SKIN = [(236, 190, 160), (200, 150, 110), (150, 105, 80), (240, 205, 180)]
HAIR = [(50, 36, 28), (190, 150, 80), (20, 20, 22), (120, 70, 40)]
_STREET_SCALES = {"Dete": .64, "Devojka": .95, "Pop": 1.04, "Penzioner": .95, "Advokat": 1.03,
                  "Teretana Brat": 1.10, "Golabar": .93, "Dedo na Kolo": .95, "Trotinet Dete": .64}


class _StreetParts:
    """Shared human mesh primitives plus rigid props for the ambient role recipes."""

    def __init__(self, tier):
        self.tier = tier
        self.parts, self.uvs = [], []

    def add(self, cx, y, cz, sx, sy, sz, col, form=None, material=0):
        color = np.asarray(col, np.float32)
        if form is None:
            # Signs, shields, vehicle panels and other rigid props keep their flat faces.
            for vertices, normal in box_faces(cx, y, cz, sx, sy, sz).values():
                self.parts.append((vertices, np.tile(color * _shade(np.asarray(normal)), (len(vertices), 1))))
                self.uvs.append(np.tile((.125, .25), (len(vertices), 1)))
            return
        detail = self.tier if form != 'feature' else max(1, self.tier - 1)
        tile = material if self.tier == 3 else int(self.tier == 2 and material != 0)
        vertices, normals, uv = characterart.street_part(form, detail, tile)
        size = np.array((sx, sy, sz), np.float32)
        points = vertices * size + np.array((cx, y + sy/2, cz), np.float32)
        lighting = .64 + .43 * np.maximum(0., characterart.unit(normals / size) @ SUN)
        self.parts.append((points, color * lighting[:, None]))
        self.uvs.append(uv)

    def wheel(self, cx, cy, cz, radius, width, col=(26, 26, 28), hub=(170, 170, 176)):
        pos, rgb = _cyl(cx, cy, cz, radius, width, np.asarray(col), np.asarray(hub), sides=(8, 12, 16)[self.tier - 1])
        self.parts.append((pos, rgb))
        self.uvs.append(np.tile((.125, .25), (len(pos), 1)))

    def head(self, x, y, skin, hair, width=.27, height=.29, nose=.065):
        self.add(x, y, 0, .27, height, width, skin, 'round', 7)
        self.add(x + .122, y + height*.34, 0, nose, .064, .067, skin, 'feature', 7)
        self.add(x + .131, y + height*.24, 0, .018, .022, .092, (121, 69, 56), 'feature')
        for side in (-1, 1):
            z = side * width
            self.add(x - .016, y + height*.40, z*.48, .068, .071, .043, skin, 'feature', 7)
            self.add(x + .129, y + height*.58, z*.23, .024, .033, .058, (238, 225, 208), 'feature')
            self.add(x + .142, y + height*.59, z*.23, .014, .027, .028, (48, 34, 32), 'feature')
            if self.tier >= 2:
                self.add(x + .124, y + height*.72, z*.23, .027, .016, .065, hair, 'feature', 6)

    def arrays(self, pos):
        rgba = np.full((len(pos), 4), 255, np.uint8)
        rgba[:, :3] = np.clip(np.concatenate([part[1] for part in self.parts]), 0, 255)
        return pos, np.concatenate(self.uvs, dtype=np.float32), rgba


def _swing(parts, i0, px, py, ang):
    """Rotate parts[i0:] around a joint in the walking plane (x forward, y up)."""
    if abs(ang) < 1e-4:
        return
    c, s_ = math.cos(ang), math.sin(ang)
    for k in range(i0, len(parts)):
        v, col = parts[k]
        v = np.asarray(v, np.float32)
        x, y = v[:, 0] - px, v[:, 1] - py
        v2 = v.copy()
        v2[:, 0] = px + x * c - y * s_
        v2[:, 1] = py + x * s_ + y * c
        parts[k] = (v2, col)


def _phase(frame):
    """Walk / run cycle. 20..27 = walk, 30..37 = run: eight phases of one stride cycle, limbs swing as a cosine;
    12 = standing (arms hanging, legs together); 0/1/6/7 and 8..11 = the old four-pose cycle (kept for callers).
    -> (base frame, leg swing angle, forward lean as a shear, cycle phase in radians or None, running)."""
    if frame == 12:
        return 0, 0.0, 0.0, None, False
    if 20 <= frame < 38:
        run = frame >= 30
        amp = WALK_AMP * (1.45 if run else 1.0)
        ph = 2 * math.pi * (frame % 10) / 8
        return 0, amp * math.cos(ph), (0.35 if run else 0.12), ph, run
    run = frame >= 8
    if run:
        frame = {8: 0, 9: 1, 10: 6, 11: 7}[frame]
    amp = 0.8 if run else 0.55
    th = amp if frame == 0 else (-amp if frame == 1 else 0.0)
    lean = 0.0
    if frame in (0, 1, 6, 7):
        lean = 0.4 if run else 0.1
    if frame in (6, 7):
        frame = 0
    return frame, th, lean, (0.0 if frame in (0, 1) else None), run


# Thigh swing (radians either way) of the walk cycle; the run cycle swings 1.5x as far. A step is then
# 2 * hip * sin(swing) ~ 0.95 m walking, 1.35 m running (plus the flight), which render._gait matches so feet do not slide.
WALK_AMP = 0.7


def _knee(sg, th, ph, run):
    """Knee bend of a leg swinging by sg * th: the leg travelling forward (in swing) folds, peaking as it passes the
    other one, so the foot clears the ground; the standing leg stays nearly straight."""
    if ph is None:
        return 0.0
    return 0.08 + (1.35 if run else 0.8) * max(0.0, -sg * math.sin(ph))


def _leg(parts, add, z, a, flex, hip, col, shin_col, shoe, feet, bare_thigh=False, bare_shin=False, w=0.17, toe=0.28):
    """Thigh from the hip, shin from the knee, foot from the ankle (toes forward). The thigh swings by a, the shin
    bends back by flex at the knee; the boxes overlap at the joints so no gap opens when they bend.
    The foot boxes' indices go to feet (the caller plants the lowest one on the ground)."""
    k = hip / 2
    i0 = len(parts)
    add(0.0, k - 0.048, z, w + 0.034, hip - k + 0.08, w + .02, col, 'limb', 7 if bare_thigh else 4)
    i1 = len(parts)
    add(0.0, 0.052, z, w, k + 0.023, w - 0.01, shin_col, 'limb', 7 if bare_shin else 4)
    f0 = len(parts)
    add(0.06, 0.0, z, toe, 0.12, w, shoe, 'round', 1)
    feet.extend(range(f0, len(parts)))
    _swing(parts, i0, 0.0, hip, a)
    _swing(parts, i1, k * math.sin(a), hip - k * math.cos(a), -flex)


def _arm(parts, add, x, sh, z, a, bend, col, hand, held=()):
    """Upper arm from the shoulder (x, sh), forearm from the elbow, hand; held = boxes (cx, y, cz, sx, sy, sz, col)
    gripped in the hand, which move with the forearm. The arm swings by a, the forearm bends forward by bend."""
    u, f, w = .34, .30, .13
    i0 = len(parts)
    add(x, sh - u - 0.048, z, w * 1.18, u + 0.10, w * 1.04, col, 'limb', 1)
    i1 = len(parts)
    add(x, sh - u - f - 0.018, z, w, f + .065, w - 0.01, col, 'limb', 1)
    add(x, sh - u - f - 0.085, z, w - 0.02, 0.12, w - 0.025, hand, 'round', 7)
    for b in held:
        add(*b)
    _swing(parts, i0, x, sh, a)
    _swing(parts, i1, x + u * math.sin(a), sh - u * math.cos(a), bend)


def _elbow(a, run):
    """Forearm bend: a little when walking (more as the arm comes forward), held near a right angle when running."""
    return (1.3 if run else 0.25) + 0.35 * max(0.0, a)


def _reach(sx, sy, gx, gy, u, f):
    """Two-bone reach: (shoulder swing, elbow bend) that puts the hand of an arm (upper u, forearm + hand f) on (gx, gy),
    the elbow dropping below the line; straight out if the grip is beyond reach."""
    dx, dy = gx - sx, gy - sy
    d = min(math.hypot(dx, dy), u + f - 1e-3)
    t = math.atan2(dx, -dy)
    al = math.acos(max(-1.0, min(1.0, (u * u + d * d - f * f) / (2 * u * d))))
    ga = math.acos(max(-1.0, min(1.0, (u * u + f * f - d * d) / (2 * u * f))))
    return t - al, math.pi - ga


def _ground(parts, feet):
    """How far the lowest foot is off the ground: the body drops by this so the standing foot stays planted."""
    return min(float(parts[k][0][:, 1].min()) for k in feet) if feet else 0.0


def _lean(pos, lean):
    """Upper body (above the hips) leans forward: shear x with height."""
    if lean:
        pos[:, 0] += np.maximum(pos[:, 1] - 0.8, 0.0) * lean


def _strike(add, kind, sk, legc, shoe, arm=None):
    """The fight poses. The caller leaves out the limbs that move (both arms for 4, the right leg for 5), so these
    replace them instead of growing on top of them. 4 = punch: right arm thrown straight out, left in guard;
    5 = high front kick with the right leg."""
    arm = sk if arm is None else arm
    if kind == 4:
        add(0.2, 1.24, 0.3, 0.40, 0.15, 0.15, arm, 'round', 1)
        add(0.52, 1.24, 0.3, 0.37, 0.135, 0.135, arm, 'round', 1)
        add(0.69, 1.23, 0.3, 0.16, 0.15, 0.15, sk, 'round', 7)
        add(0.06, 1.0, -0.34, 0.15, 0.39, 0.14, arm, 'limb', 1)
        add(0.2, 1.0, -0.3, 0.34, 0.135, 0.135, arm, 'round', 1)
        add(0.37, 1.0, -0.3, 0.13, 0.13, 0.125, sk, 'round', 7)
    else:
        add(0.26, 0.74, 0.11, 0.57, 0.19, 0.18, legc, 'round', 4)
        add(0.67, 0.8, 0.11, 0.41, 0.16, 0.16, legc, 'round', 4)
        add(0.87, 0.8, 0.11, 0.27, 0.13, 0.18, shoe, 'round', 1)


def _ped_special(arch, tone, frame, skin, tier):
    """Street roles with equipment or ride-specific poses, using shared human parts."""
    A = lambda c: np.array(c, np.float32)
    strike = frame if frame in (4, 5) else 0
    jump = frame == 16
    if strike:
        frame = 0
    name = V.PED_IDS[arch]
    sk = A(SKIN[skin % 4])
    hair = A(HAIR[(skin + tone) % 4])
    mesh = _StreetParts(tier)
    parts, add, wheel = mesh.parts, mesh.add, mesh.wheel

    # (scale, torso colours, legs, shoes, skirt?, hat kind)
    D = dict(torso=(120, 120, 130), legs=(52, 66, 104), shoe=(30, 28, 28), skirt=None, rider=None,
             belly=0.0, wide=0.0, shorts=False, arms_up=False, head_fwd=0.0, stride=1.0, grip=None)
    hat = None
    held = []                         # (sx, sy, sz, col, y, z) hand-held boxes swinging with the right arm
    held_l = []                       # ... and with the left
    extra = []                        # static boxes (x, y, z, sx, sy, sz, col) in body space
    P3 = lambda a, b, c: [a, b, c][tone % 3]
    if name == "Patar":                                                    # road crew (crews.py): lime hi-vis vest with bands, white hard hat, orange trousers, cone in hand
        D.update(torso=P3((196, 232, 36), (206, 236, 40), (188, 226, 30)), legs=(232, 112, 24), shoe=(34, 30, 26)); hat = ("helmet", (240, 240, 236))
        extra += [(0.0, 0.8, 0, 0.3, 0.06, 0.54, (232, 232, 228)), (0.0, 1.0, 0, 0.3, 0.05, 0.54, (232, 232, 228)),
                  (-0.16, 0.9, 0, 0.02, 0.4, 0.12, (232, 232, 228))]
        held = [(0.1, 0.12, 0.1, (240, 110, 30), 0.55, 0.0)]
    elif name == "Paramedik":                                              # ambulance crew: orange hi-vis jacket, white reflective bands, medical bag
        D.update(torso=P3((255, 112, 24), (250, 120, 30), (255, 100, 20)), legs=(40, 52, 80), shoe=(26, 26, 28))
        extra += [(0.0, 0.8, 0, 0.3, 0.06, 0.54, (240, 240, 236)), (0.0, 1.0, 0, 0.3, 0.05, 0.54, (240, 240, 236)),
                  (0.16, 1.1, 0, 0.02, 0.1, 0.1, (200, 30, 40))]
        held = [(0.05, 0.1, 0.05, (230, 230, 226), 0.65, 0.0)]
    elif name == "Vojnik":                                                   # barracks guard: camo uniform, helmet, vest, rifle slung on the back
        D.update(torso=P3((84, 96, 58), (78, 90, 54), (90, 100, 62)), legs=(76, 86, 54), shoe=(22, 22, 22)); hat = ("helmet", (62, 72, 44))
        extra += [(0.0, 0.95, 0, 0.32, 0.4, 0.54, (58, 66, 40)), (0.17, 0.8, -0.12, 0.06, 0.16, 0.12, (44, 52, 32)),
                  (0.17, 0.8, 0.12, 0.06, 0.16, 0.12, (44, 52, 32)), (-0.2, 0.55, 0.12, 0.07, 0.85, 0.07, (24, 24, 26)),
                  (-0.2, 0.75, 0.12, 0.09, 0.14, 0.08, (60, 44, 30)), (0.0, 0.8, 0, 0.29, 0.06, 0.52, (40, 40, 30))]
    elif name == "Pandur":
        D.update(torso=(70, 92, 134), legs=(44, 54, 86)); hat = ("cap", (40, 54, 94))
        extra += [(0, 0.84, 0, 0.3, 0.06, 0.54, (240, 240, 240))]
        held = [(0.06, 0.5, 0.06, (240, 240, 240), 0.55, 0.0)]
    elif name == "Parkingar":
        D.update(torso=(255, 150, 0), legs=(60, 60, 72)); hat = ("cap", (250, 220, 40))
        extra += [(0.0, 0.95, 0, 0.3, 0.06, 0.54, (240, 240, 120)), (0.16, 0.8, 0.0, 0.02, 0.6, 0.12, (240, 240, 120))]
        held = [(0.2, 0.03, 0.15, (240, 240, 240), 0.7, 0.0)]
    elif name == "Pop":
        D.update(torso=(22, 22, 26), legs=(22, 22, 26), skirt=(22, 22, 26)); hat = ("tall", (22, 22, 26))
        extra += [(0.14, 1.28, 0, 0.1, 0.22, 0.16, (200, 200, 196)), (0.1, 0.9, 0, 0.04, 0.35, 0.05, (210, 170, 40))]
        held = [(0.05, 0.22, 0.12, (214, 176, 50), 0.6, 0.0)]
    elif name == "Hipster":
        D.update(torso=P3((200, 100, 60), (70, 110, 90), (60, 70, 130)), legs=(30, 30, 34)); hat = ("beanie", (64, 64, 66))
        extra += [(0.14, 1.34, 0, 0.1, 0.12, 0.2, (66, 44, 30)), (0.0, 0.62, 0.4, 0.1, 0.32, 0.38, (130, 90, 56))]
    elif name == "Influenser":
        D.update(torso=(232, 120, 172), legs=(240, 240, 240), arms_up=True); hat = None
        extra += [(-0.1, 0.95, 0, 0.1, 0.6, 0.28, (240, 214, 120))]
        held = [(0.04, 0.22, 0.1, (20, 20, 24), 1.78, 0.0), (0.03, 0.5, 0.03, (60, 60, 64), 1.5, 0.0)]
    elif name == "Telefonash":
        D.update(torso=(110, 110, 124), legs=(48, 62, 100), head_fwd=0.1)
        hat = ("hood", (110, 110, 124))
        extra += [(0.3, 1.1, 0, 0.03, 0.16, 0.08, (20, 20, 24))]
    elif name == "Penzioner":
        D.update(torso=(130, 100, 70), legs=(60, 60, 72)); hat = ("flat", (110, 102, 92))
        held = [(0.04, 0.75, 0.04, (110, 70, 40), 0.0, 0.0)]
    elif name == "Kafana Chicko":
        D.update(torso=(236, 236, 226), legs=(40, 40, 52), belly=0.12); hat = None
        extra += [(0.0, 0.8, 0, 0.3, 0.6, 0.52, (40, 40, 50)), (0.145, 1.44, 0, 0.03, 0.04, 0.16, (30, 30, 34))]
        held = [(0.05, 0.1, 0.05, (200, 130, 40), 0.7, 0.0)]
    elif name == "Turist":
        D.update(torso=P3((230, 90, 90), (60, 170, 200), (240, 190, 60)), legs=(210, 190, 140), shorts=True)
        hat = ("brim", (240, 232, 190))
        extra += [(0.19, 1.05, 0, 0.12, 0.1, 0.2, (24, 24, 28)), (0.1, 0.86, 0, 0.04, 0.16, 0.5, (230, 80, 70))]
        held = [(0.3, 0.02, 0.4, (236, 236, 226), 0.7, 0.0)]
    elif name == "Gastarbajter":
        D.update(torso=(40, 40, 44), legs=(30, 30, 40), stride=0.8)
        extra += [(0.14, 1.34, 0, 0.1, 0.06, 0.22, (14, 14, 16)), (0.14, 1.2, 0, 0.03, 0.1, 0.12, (230, 190, 40)),
                  (0.0, 0.0, 0.5, 0.22, 0.62, 0.42, (130, 70, 40)), (0.0, 0.0, -0.5, 0.22, 0.62, 0.42, (170, 40, 40))]
        hat = None
    elif name == "Majka so Kolichka":
        D.update(torso=(200, 120, 160), legs=(48, 62, 100)); hat = ("long", tuple(hair))
        D["grip"] = (0.62, 0.98)
    elif name == "Partiski Aktivist":
        D.update(torso=(50, 90, 200), legs=(36, 40, 60)); hat = None
        extra += [(0.14, 0.9, 0, 0.03, 0.4, 0.05, (210, 30, 40)), (0.0, 0.62, -0.4, 0.1, 0.3, 0.3, (240, 240, 240))]
        held = [(0.03, 1.5, 0.03, (170, 150, 120), 0.2, 0.0), (0.02, 0.45, 0.7, (210, 30, 40), 1.6, 0.0)]
    elif name == "Advokat":
        D.update(torso=(30, 32, 40), legs=(30, 32, 40)); hat = None
        extra += [(0.14, 0.9, 0, 0.02, 0.5, 0.14, (236, 236, 236)), (0.14, 1.46, 0, 0.1, 0.05, 0.24, (14, 14, 16))]
        held = [(0.1, 0.28, 0.42, (190, 192, 198), 0.2, 0.0)]
    elif name == "Teretana Brat":
        D.update(torso=(232, 232, 236), legs=(30, 30, 36), wide=0.22, shorts=True); hat = None
        held = [(0.1, 0.26, 0.1, (50, 90, 200), 0.65, 0.0)]
    elif name == "Kiosk Chika":
        D.update(torso=(180, 60, 100), legs=(60, 60, 70)); hat = ("bun", tuple(hair))
        extra += [(0.34, 0.92, 0, 0.5, 0.05, 0.56, (240, 240, 240)), (0.4, 0.97, 0.15, 0.2, 0.06, 0.2, (210, 40, 40)),
                  (0.3, 0.97, -0.18, 0.22, 0.06, 0.16, (60, 120, 200))]
    elif name == "Ribar":
        D.update(torso=(110, 130, 90), legs=(110, 100, 70)); hat = ("brim", (150, 140, 90))
        extra += [(0.9, 1.5, 0.35, 1.9, 0.03, 0.03, (90, 66, 40))]
        held_l = [(0.25, 0.3, 0.25, (50, 90, 160), 0.44, 0.06)]               # the bucket, carried in the left hand
    elif name == "Golabar":
        D.update(torso=(120, 110, 100), legs=(70, 66, 60)); hat = ("scarf", (150, 70, 90))
        extra += [(0.3, 0.0, 0.2, 0.14, 0.12, 0.1, (130, 130, 138)), (0.5, 0.0, -0.2, 0.14, 0.12, 0.1, (110, 110, 120)),
                  (0.25, 0.0, -0.4, 0.14, 0.12, 0.1, (150, 150, 156)), (0.12, 0.7, 0.4, 0.2, 0.22, 0.14, (230, 220, 190))]
    elif name == "Komunalec":
        D.update(torso=(150, 180, 220), legs=(40, 44, 58)); hat = ("flat", (30, 44, 80))
        extra += [(0.14, 0.9, 0, 0.02, 0.45, 0.06, (160, 30, 40))]
        held = [(0.2, 0.03, 0.26, (200, 40, 40), 0.7, 0.0)]
    elif name == "Nevesta":
        D.update(torso=(248, 248, 250), legs=(248, 248, 250), skirt=(248, 248, 250)); hat = ("long", tuple(hair))
        held = [(0.12, 0.12, 0.12, (240, 120, 160), 0.7, 0.0)]
    elif name == "Dostavuvach":
        D.update(torso=(255, 208, 0), legs=(36, 40, 50)); hat = ("cap", (255, 208, 0))
        extra += [(-0.3, 0.8, 0, 0.38, 0.72, 0.56, (255, 210, 20)), (-0.3, 0.8, 0, 0.4, 0.04, 0.58, (40, 40, 44))]
        held = [(0.04, 0.16, 0.08, (20, 20, 24), 0.8, 0.0)]
    elif name == "Jogger":
        D.update(torso=P3((60, 220, 120), (255, 90, 160), (60, 200, 240)), legs=(30, 30, 36), shorts=True, stride=1.3)
        hat = ("band", (240, 240, 240))
        extra += [(0.0, 1.46, 0.0, 0.02, 0.04, 0.38, (30, 30, 34))]
    elif name == "Velosipedist":
        D.update(torso=P3((240, 230, 40), (230, 40, 40), (40, 120, 230)), legs=(30, 30, 36), rider="road", shorts=True); hat = ("helmet", (30, 30, 34))
    elif name == "Dedo na Kolo":
        D.update(torso=(120, 100, 70), legs=(70, 64, 56), rider="old"); hat = ("flat", (110, 102, 92))
    elif name == "Moped Tomos":
        D.update(torso=(90, 60, 40), legs=(40, 50, 80), rider="moped"); hat = None
    elif name == "Glovo Skuter":
        D.update(torso=(255, 208, 0), legs=(36, 40, 50), rider="courier"); hat = ("helmet", (240, 240, 240))
    elif name == "Trotinet Dete":
        D.update(torso=P3((240, 80, 80), (60, 180, 240), (250, 200, 40)), legs=(52, 66, 104), rider="kick"); hat = ("helmet", (240, 120, 40))
    elif name == "E-Trotinet Hipster":
        D.update(torso=(70, 110, 90), legs=(30, 30, 34), rider="escooter"); hat = ("beanie", (64, 64, 66))
        extra += [(0.14, 1.34, 0, 0.1, 0.12, 0.2, (66, 44, 30))]
    elif name == "Skejter":
        D.update(torso=P3((230, 230, 40), (200, 60, 60), (60, 60, 70)), legs=(80, 90, 110), rider="skate", stride=0.5); hat = ("cap", (30, 30, 34))
    elif name == "Rolerash":
        D.update(torso=(240, 120, 40), legs=(30, 30, 36), rider="blades", stride=1.5); hat = ("helmet", (60, 140, 220))
        extra += [(0.0, 0.7, -0.4, 0.14, 0.2, 0.12, (30, 30, 34)), (0.0, 0.7, 0.4, 0.14, 0.2, 0.12, (30, 30, 34))]
    elif name == "Kocija":
        D.update(torso=(130, 100, 70), legs=(60, 56, 50), rider="cart"); hat = ("brim", (150, 130, 80))
    torso, legc = D["torso"], D["legs"]
    rider = D["rider"]
    frame, th, lean, ph, run = _phase(3 if jump else frame)
    if strike:
        th = lean = 0.0
        ph = None
    th = max(-1.1, min(1.1, th * D["stride"]))             # (a long-striding jogger still keeps the hips together)
    sit = rider in ("road", "old", "moped", "courier", "cart") and frame < 2
    Y = -0.2 if sit else 0.0                                 # upper body lowered when seated
    bx = -0.05 if sit else 0.0
    # ---------------- vehicle under the rider (not drawn once knocked off)
    if rider and frame < 2:
        if rider in ("road", "old"):
            for xx in (-0.58, 0.58):
                wheel(xx, 0.34, 0, 0.34, 0.05, (24, 24, 26), (150, 150, 156))
            fr = (200, 40, 40) if rider == "road" else (60, 70, 70)
            add(0.0, 0.52, 0, 1.0, 0.05, 0.05, fr); add(-0.1, 0.5, 0, 0.05, 0.4, 0.05, fr)
            add(0.5, 0.55, 0, 0.05, 0.5, 0.05, fr); add(0.5, 0.98 if rider == "old" else 0.85, 0, 0.1, 0.05, 0.5, (30, 30, 34))
            add(-0.22, 0.88, 0, 0.3, 0.06, 0.14, (30, 30, 34))
            add(0.6, 0.7, 0, 0.07, 0.09, 0.1, (255, 244, 180)); add(-0.4, 0.78, 0, 0.04, 0.06, 0.08, (210, 30, 30))      # lamp, tail light
            if rider == "old":
                add(0.62, 0.7, 0, 0.3, 0.26, 0.42, (150, 100, 50)); add(0.62, 0.95, 0.1, 0.12, 0.2, 0.06, (60, 150, 60))
        elif rider in ("moped", "courier"):
            col = (210, 90, 30) if rider == "moped" else (90, 92, 98)
            for xx in (-0.6, 0.6):
                wheel(xx, 0.28, 0, 0.28, 0.1)
            add(0.0, 0.3, 0, 1.0, 0.4, 0.34, col); add(-0.1, 0.7, 0, 0.5, 0.1, 0.3, (30, 30, 34))
            add(0.55, 0.65, 0, 0.12, 0.45, 0.1, (60, 62, 68)); add(0.55, 1.0, 0, 0.1, 0.05, 0.6, (30, 30, 34))
            add(0.62, 0.9, 0, 0.08, 0.12, 0.16, (255, 244, 180)); add(-0.51, 0.55, 0, 0.03, 0.08, 0.16, (210, 30, 30))
            if rider == "courier":
                add(-0.55, 0.78, 0, 0.55, 0.6, 0.55, (255, 210, 0)); add(-0.55, 1.38, 0, 0.56, 0.05, 0.56, (40, 40, 44))
        elif rider in ("kick", "escooter"):
            col = (40, 120, 220) if rider == "kick" else (30, 30, 34)
            ln = 0.9 if rider == "kick" else 1.1
            add(0.0, 0.1, 0, ln, 0.06, 0.2, col)
            for xx in (-ln / 2 + 0.05, ln / 2 - 0.05):
                wheel(xx, 0.1, 0, 0.1 if rider == "kick" else 0.14, 0.05)
            add(ln / 2 - 0.05, 0.1, 0, 0.04, 0.8 if rider == "kick" else 1.05, 0.04, (120, 120, 126))
            add(ln / 2 - 0.01, 0.75 if rider == "kick" else 0.95, 0, 0.04, 0.07, 0.08, (255, 244, 180)); add(-ln / 2 - 0.01, 0.13, 0, 0.03, 0.04, 0.12, (210, 30, 30))
            add(ln / 2 - 0.05, 0.9 if rider == "kick" else 1.15, 0, 0.08, 0.04, 0.5, (30, 30, 34))
        elif rider == "skate":
            add(0.0, 0.1, 0, 0.8, 0.04, 0.22, (200, 160, 60) if tone else (60, 140, 200))
            for xx in (-0.28, 0.28):
                for zz in (-0.08, 0.08):
                    wheel(xx, 0.07, zz, 0.05, 0.04, (220, 220, 220))
        elif rider == "cart":
            horse = (110, 70, 40)
            add(1.68, .69, 0, 1.48, .66, .53, horse, 'round', 6)
            add(2.18, .89, 0, .47, .75, .36, horse, 'limb', 6)
            add(2.48, 1.18, 0, .57, .35, .31, horse, 'round', 6)
            add(2.70, 1.19, 0, .27, .21, .24, (90, 56, 34), 'round', 6)
            add(2.09, 1.16, 0, .29, .42, .15, (51, 37, 25), 'limb', 6)
            add(.99, .58, 0, .16, .63, .15, (51, 37, 25), 'limb', 6)
            for s in (-1, 1):
                add(2.36, 1.47, s*.10, .12, .18, .083, horse, 'feature', 6)
                add(2.55, 1.39, s*.125, .063, .052, .033, (36, 26, 22), 'feature')
            for k, (lx, lz) in enumerate(((2.2, -0.15), (2.2, 0.15), (1.2, -0.15), (1.2, 0.15))):
                off = 0.18 * (1 if (k + frame) % 2 else -1)
                add(lx + off, .015, lz, .148, .89, .143, (90, 56, 34), 'limb', 6)
                add(lx + off+.036, 0., lz, .185, .12, .144, (53, 41, 36), 'round')
            add(0.0, 0.5, 0, 2.2, 0.15, 1.2, (150, 110, 70)); add(0.0, 0.65, -0.6, 2.2, 0.35, 0.06, (130, 94, 58))
            add(0.0, 0.65, 0.6, 2.2, 0.35, 0.06, (130, 94, 58)); add(-1.1, 0.65, 0, 0.06, 0.35, 1.2, (130, 94, 58))
            add(1.1, 0.55, 0, 1.2, 0.04, 0.05, (90, 66, 40))
            for zz in (-0.65, 0.65):
                wheel(-0.4, 0.5, zz, 0.5, 0.08, (60, 40, 24), (120, 90, 60))
            add(-0.8, 0.65, 0, 0.7, 0.8, 0.8, (210, 190, 120))                      # hay
    # ---------------- legs
    feet = []
    if sit:
        hx0 = 0.09 if rider != "cart" else -0.06                # hip; the thigh runs forward to the knee, the shin down from it
        for s in (-1, 1):
            pd = 0.3 * (1 if (frame == 0) == (s > 0) else -1) * (0.0 if rider in ("moped", "courier", "cart") else 1.0)
            i0 = len(parts)
            add(hx0 + 0.22, 0.585, s * 0.11, 0.52, 0.18, 0.18, legc, 'round', 4)
            i1 = len(parts)
            add(hx0 + 0.42, 0.04, s * 0.11, 0.18, 0.66, 0.16, legc, 'limb', 4)
            add(hx0 + 0.47, 0.0, s * 0.11, 0.26, 0.11, 0.16, D["shoe"], 'round', 1)
            _swing(parts, i0, hx0, 0.67, 0.5 * pd)           # pedalling: the knee rises and falls ...
            _swing(parts, i1, hx0 + 0.42 * math.cos(0.5 * pd), 0.67 + 0.42 * math.sin(0.5 * pd), -0.6 * pd)   # ... the shin follows it
    else:
        skirt = D["skirt"] is not None
        lc2 = D["legs"]
        for s in (-1, 1):
            if strike == 5 and s > 0:
                continue
            step = -.45 if jump else -s * th
            flex = 1.0 if jump else _knee(-s, th, ph, run) * (.64, .85, 1.)[tier - 1]
            bare_shin = skirt or D["shorts"]
            _leg(parts, add, s * 0.11, step, flex, 0.82, sk if skirt else lc2, sk if bare_shin else lc2,
                 D["shoe"], feet, bare_thigh=skirt, bare_shin=bare_shin, w=0.15 if skirt else 0.17, toe=0.38 if rider == "blades" else 0.28)
        if name == "Nevesta":
            add(0, .08, 0, .63, .84, .72, D["skirt"], 'hem', 5)
            add(-.147, .88, 0, .08, .76, .40, (223, 222, 237), 'hem', 5)
        elif skirt:
            add(0.0, 0.3, 0, 0.4, 0.61, 0.50, D["skirt"], 'hem', 5)
        else:
            add(bx, 0.685, 0, 0.29, 0.24, 0.45, lc2, 'round', 4)
    # ---------------- torso, arms, head
    wd = 0.5 + D["wide"]
    add(bx, 0.773 + Y, 0, 0.30 + D["belly"], 0.65, wd + .018, torso, 'torso', 1)
    add(bx, 1.239 + Y, 0, 0.255, 0.185, wd + 0.08, torso, 'round', 1)
    add(bx + .016, 1.347 + Y, 0, .146, .18, .141, sk, 'round', 7)
    ac = A(torso) * 0.92
    if frame == 3 or D["arms_up"]:
        for side in (-1, 1):
            _arm(parts, add, bx, 1.36 + Y, side * (.30 + D["wide"]/2), 2.28, .30, ac, sk)
    elif sit or rider in ("kick", "escooter"):
        grip = {"road": (0.5, 0.88), "old": (0.5, 1.0), "moped": (0.55, 1.0), "courier": (0.55, 1.0), "cart": (0.75, 0.75),
                "kick": (0.4, 0.92), "escooter": (0.5, 1.15)}[rider]
        for s in (-1, 1):                                    # both hands on the handlebar (the reins), the elbows bent to reach it
            a, bend = _reach(bx, 1.36 + Y, *grip, 0.34, 0.34)
            _arm(parts, add, bx, 1.36 + Y, s * .285, a, bend, ac, sk)
    else:
        z = .283 + D["wide"] / 2
        for zz_, sg in ((-z, -1), (z, 1)):
            if strike == 4:                                  # (punching: both arms are drawn by _strike)
                continue
            hb = [(0.02, yy - 0.74 + 0.64 if yy else 0.0, sg * (z + 0.08 + zz), sx, sy, sz, col)   # props carried in that hand
                  for (sx, sy, sz, col, yy, zz) in (held if sg > 0 else held_l)]
            if D["grip"]:                                    # both hands on a push bar in front
                a, bend = _reach(0.0, 1.38, *D["grip"], 0.34, 0.34)
            else:
                a = sg * th * (0.5 if hb else 0.9)
                bend = 0.15 if hb else _elbow(a, run) * (.72, .91, 1.)[tier - 1]
            _arm(parts, add, 0.0, 1.38, zz_, a, bend, ac, sk, held=hb)
    for (x, y, z, sx, sy, sz, col) in extra:
        if frame == 2 and y < 0.3:
            continue
        add(bx + x, y + Y + (0.0 if y < 0.3 else 0.0), z, sx, sy, sz, col)
    hx = 0.02 + D["head_fwd"]
    head_y = 1.42 + Y
    old = name in ("Penzioner", "Dedo na Kolo", "Kafana Chicko")
    mesh.head(hx + bx, head_y, sk, hair, .286 if old else .252, .282, .083 if old else .059)
    if hat:
        k, col = hat
        if k == "cap":
            add(hx + bx, 1.62 + Y, 0, 0.3, 0.11, 0.3, col, 'round', 1)
            add(hx + 0.13 + bx, 1.61 + Y, 0, 0.17, 0.043, 0.26, col, 'round', 1)
        elif k == "tall":
            add(hx + bx, 1.62 + Y, 0, 0.3, 0.26, 0.3, col, 'limb', 2)
        elif k in ("beanie", "hood", "scarf", "bun", "helmet", "band"):
            add(hx + bx, 1.6 + Y, 0, 0.31, 0.16, 0.3, col, 'round', 3 if k == 'scarf' else 1)
            if k == "bun":
                add(hx - 0.14 + bx, 1.64 + Y, 0, 0.12, 0.12, 0.12, col, 'round', 6)
            if k == "helmet":
                add(hx - 0.1 + bx, 1.56 + Y, 0, 0.14, 0.1, 0.3, col, 'round', 1)
        elif k == "flat":
            add(hx + bx, 1.62 + Y, 0, 0.32, 0.084, 0.32, col, 'round', 2)
        elif k == "brim":
            add(hx + bx, 1.62 + Y, 0, 0.5, 0.05, 0.5, col, 'round', 1)
            add(hx + bx, 1.65 + Y, 0, 0.28, 0.1, 0.28, col, 'round', 1)
        elif k == "long":
            add(hx - 0.03 + bx, 1.53 + Y, 0, 0.28, 0.20, 0.28, col, 'round', 6)
            add(hx - 0.12 + bx, 1.0 + Y, 0, 0.14, 0.59, 0.28, col, 'limb', 6)
    else:
        add(hx - 0.045 + bx, 1.584 + Y, 0, 0.29, 0.17, 0.269, hair, 'round', 6)
    if strike:
        _strike(add, strike, sk, D["legs"], D["shoe"], ac)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    if not rider:
        _lean(pos, lean)
        if ph is not None:
            pos[:, 1] = np.maximum(pos[:, 1] - _ground(parts, feet), 0.0)   # the standing foot stays planted (the body bobs), nothing carried sinks in
    if D["grip"] and frame < 2 and not strike:
        # Add the pram after the walk transforms so its wheels stay on the ground.
        start = len(parts)
        add(.91, .25, 0, .58, .12, .45, (104, 105, 116), 'round')
        add(1.02, .34, 0, .74, .34, .48, (229, 156, 175), 'hem', 5)
        add(1.20, .52, 0, .38, .30, .48, (158, 105, 134), 'round', 1)
        for side in (-1, 1):
            add(.70, .31, side*.20, .047, .67, .05, (63, 61, 67))
            for x in (.74, 1.23):
                wheel(x, .13, side*.218, .13, .047)
        add(.66, .94, 0, .083, .059, .55, (45, 44, 52), 'round')
        pos = np.concatenate([pos, *(part[0] for part in parts[start:])]).astype(np.float32, copy=False)
    pos *= ped_scale(arch)
    if frame == 2:
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    return mesh.arrays(pos)


def _street_arrays(arch, tone, frame, skin, tier):
    if 40 <= frame <= 47:                              # crawling on all fours, face down, the walk cycle drives the limbs
        pos, uv, rgba = _street_arrays(arch, tone, frame - 20, skin, tier)
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos = pos.copy()
        c = np.clip(x, -0.15, 0.3)                     # the body's own depth: front (chest) down, back up
        hx = c + (x - c) * np.where(x < c, 0.12, 0.35)
        pos[:, 0] = y * 0.55 - 0.1 + (x - c) * 0.7     # on all fours: head forward, body shortened; a limb swung forward
        pos[:, 1] = (0.3 - hx) * 0.8 + 0.22 + np.abs(np.sin(math.pi * (frame % 10) / 4)) * 0.03   # reaches along the body, not up
        return pos, uv, rgba
    if arch >= 10:
        return _ped_special(arch, tone, frame, skin, tier)
    A = lambda c: np.array(c, np.float32)
    strike = frame if frame in (4, 5) else 0
    jump = frame == 16
    if strike:
        frame = 0
    sk = A(SKIN[skin % 4])
    hair = A(HAIR[(skin + tone) % 4])
    mesh = _StreetParts(tier)
    parts, add = mesh.parts, mesh.add

    jeans, dark = (52, 66, 104), (34, 36, 44)
    legc, shoe = jeans, (30, 28, 28)
    pal = [[(200, 60, 60), (60, 90, 190), (70, 150, 90)], [(100, 60, 90), (70, 84, 70), (120, 100, 60)],
           [(40, 44, 60), (60, 60, 66), (34, 50, 70)], [(80, 90, 120), (150, 70, 50), (60, 110, 100)],
           [(200, 30, 30), (200, 30, 30), (220, 220, 220)], [(240, 200, 40), (60, 160, 220), (230, 100, 140)],
           [(240, 120, 20), (240, 120, 20), (230, 200, 30)], [(220, 90, 140), (90, 150, 220), (240, 220, 100)],
           [(236, 236, 232), (236, 236, 232), (236, 236, 232)], [(60, 130, 60)] * 3]
    torso = pal[arch][tone % 3]
    if arch == 2:
        legc = (36, 38, 50)
    elif arch == 6:
        legc = (70, 72, 84)
    elif arch == 3:
        legc = (60, 70, 100) if tone != 1 else (50, 50, 54)
    elif arch == 9:
        legc = (46, 52, 78)
    frame, th, lean, ph, run = _phase(3 if jump else frame)
    if strike:
        th = lean = 0.0
        ph = None
    th *= 0.7 if arch == 1 else 1.0
    skirt = arch in (1, 7)                                   # skirt / dress: bare legs under it
    feet = []
    for sg, z_ in ((1, -0.11), (-1, 0.11)):
        if strike == 5 and sg < 0:                           # (the kicking leg is drawn by _strike)
            continue
        step = -.45 if jump else th * sg
        flex = 1.0 if jump else _knee(sg, th, ph, run) * (.64, .85, 1.)[tier - 1]
        _leg(parts, add, z_, step, flex, 0.82, sk if skirt else legc, sk if skirt else legc, shoe, feet,
             bare_thigh=skirt, bare_shin=skirt, w=0.15 if skirt else 0.17)
    if skirt:
        add(0.0, 0.38, 0, 0.42, 0.51, 0.48, torso if arch == 7 else (90, 70, 60), 'hem', 5)
    else:
        add(0.0, 0.68, 0, 0.29, 0.24, 0.45, legc, 'round', 4)
    chest = {0: (.36,.50), 3: (.28,.47), 5: (.28,.45), 6: (.33,.55), 7: (.29,.43)}
    depth, width = chest.get(arch, (.30,.50))
    add(0, .765, 0, depth, .65, width, torso, 'torso', 2 if arch == 0 else 1)
    add(0, 1.239, 0, .255, .185, width + .07, torso, 'round', 1)
    arms_c = A(torso) * 0.92
    if arch == 4:
        add(0.0, 1.30, 0, 0.30, 0.12, 0.54, (230, 230, 232) if tone != 1 else (20, 20, 20))      # scarf
    if arch == 2:
        add(0.14, 0.9, 0, 0.02, 0.45, 0.12, (240, 240, 240))
        add(0.15, 0.9, 0, 0.03, 0.34, 0.05, (190, 30, 40))                                         # tie
    if arch == 6:
        add(0.0, 0.8, 0, 0.30, 0.6, 0.12, (230, 230, 40))                                          # hi-vis stripes
    if arch == 8:
        add(0.14, 0.45, 0, 0.04, 0.55, 0.46, (246, 246, 244))                                      # apron
    if frame == 3:
        for side in (-1, 1):
            _arm(parts, add, 0., 1.38, side*.30, 2.28, .30, arms_c, sk)
    else:
        for sg in (-1, 1):
            if strike == 4:                                   # (punching: both arms are drawn by _strike)
                continue
            held = ()
            if sg > 0 and arch == 2:
                held = ((0.0, 0.42, 0.40, 0.08, 0.22, 0.34, (110, 70, 40)),)                       # briefcase
            if sg > 0 and arch == 1:
                held = ((0.0, 0.4, 0.42, 0.18, 0.26, 0.2, (180, 60, 60)),)                         # shopping bag
            a = sg * th * (0.5 if held else 0.9)              # a loaded hand swings less
            bend = .1 if held else _elbow(a, run) * (.72, .91, 1.)[tier - 1]
            _arm(parts, add, 0.0, 1.38, (width/2 + .025)*sg, a, bend, arms_c, sk, held=held)
        if arch == 8:
            add(0.16, 0.9, 0, 0.3, 0.05, 0.5, (210, 170, 110))                                     # burek tray
    mesh.head(.02, 1.42, sk, hair, .275 if arch in (0, 5) else .248, .29, .076 if arch == 0 else .057)
    add(.02, 1.35, 0, .145, .165, .13, sk, 'round', 7)
    if arch not in (1, 7):
        add(0.0, .80, 0, depth*.90, .055, width*.92, (30, 28, 30), 'round', 1)
    if arch == 0 and tone != 2:
        add(.157, 1.493, 0, .045, .041, .162, hair * .8, 'feature', 6)
    if arch == 1:
        add(-.04, 1.50, 0, .29, .22, .30, (130, 60, 80) if tone != 1 else (60, 80, 120), 'round', 3)
    elif arch == 6:
        add(0, 1.613, 0, .327, .173, .321, (238, 182, 33), 'round')
        add(.038, 1.613, 0, .386, .047, .345, (250, 203, 44), 'round')
    elif arch == 8:
        add(0.0, 1.62, 0, 0.26, 0.26, 0.26, (248, 248, 246))                                         # chef hat
    elif arch == 4:
        add(0.0, 1.62, 0, 0.30, 0.1, 0.30, (20, 20, 22))                                             # cap
    elif arch == 9:
        add(0.0, 1.62, 0, 0.32, 0.08, 0.30, (40, 90, 40))
    else:
        add(-.035, 1.571, 0, .28, .182, .28, hair, 'round', 6)
        if arch == 7:
            add(-.10, 1.05, 0, .12, .57, .29, hair, 'limb', 6)
    if arch in (3, 5):
        add(-.17, .82, 0, .25, .50 if arch == 3 else .34, .36, (40, 70, 160) if tone != 1 else (190, 60, 40), 'round', 1)
        for side in (-1, 1):
            add(.112, .983, side*.139, .041, .29, .053, (47, 46, 60), 'limb', 2)
    if strike:
        _strike(add, strike, sk, legc, shoe, arms_c)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    _lean(pos, lean)
    if ph is not None:
        pos[:, 1] = np.maximum(pos[:, 1] - _ground(parts, feet), 0.0)   # the standing foot stays planted (the body bobs), nothing carried sinks in
    pos *= ped_scale(arch)
    if frame == 2:                                          # lie on the back: rotate about z
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    return mesh.arrays(pos)


def ped_scale(arch):
    """Body size of a person model (its stride scales with it)."""
    if arch >= 100:
        arch = characterart.hero_arch(arch)
    if arch in characterart.DESIGNS:
        return characterart.scale(arch)
    return _STREET_SCALES.get(V.PED_IDS[arch], 1.0)


def ped_model(arch, tone, frame, skin=0):
    return make_model(*ped_arrays(arch, tone, frame, skin))


def ped_visual(arch, tone, frame, skin, tier):
    if arch >= 100:
        arch = characterart.hero_arch(arch)
    frame = characterart.lod_frame(frame, tier)
    if arch in characterart.DESIGNS:
        return characterart.mesh(arch, tone, frame, skin, tier)
    return _street_arrays(arch, tone, frame, skin, tier), None


def ped_arrays(arch, tone, frame, skin=0):
    return ped_visual(arch, tone, frame, skin, 1)[0]


def ped_atlas(tier):
    size = characterart.ATLAS_SIZES[tier - 1]
    pixels = characterart.atlas(size)
    image = rl.Image()
    image.data = ffi.from_buffer(pixels)
    image.width = image.height = size
    image.mipmaps = 1
    image.format = rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8
    tex = rl.load_texture_from_image(image)
    rl.gen_texture_mipmaps(ffi.addressof(tex))
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    return tex


# ------------------------------------------------------------------ pickups
def prism_arrays(radius, height, sides, top_col, side_col):
    pos, col = [], []
    for i in range(sides):
        a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
        p0, p1 = (math.cos(a0) * radius, math.sin(a0) * radius), (math.cos(a1) * radius, math.sin(a1) * radius)
        pos += [(p0[0], 0, p0[1]), (p1[0], 0, p1[1]), (p1[0], height, p1[1]), (p0[0], 0, p0[1]), (p1[0], height, p1[1]), (p0[0], height, p0[1])]
        sh = 0.75 + 0.3 * math.cos(a0 + 0.8)
        col += [(*[c * sh for c in side_col], 255)] * 6
        pos += [(0, height, 0), (p0[0], height, p0[1]), (p1[0], height, p1[1])]
        col += [(*top_col, 255)] * 3
    return np.array(pos, np.float32), np.zeros((len(pos), 2), np.float32), np.clip(np.array(col), 0, 255).astype(np.uint8)


def _boxes_model(boxes):
    """boxes (cx, base y, cz, sx, sy, sz, colour) -> one model."""
    parts = []
    for cx, y, cz, sx, sy, sz, col in boxes:
        for _nm, (v, n) in box_faces(cx, y, cz, sx, sy, sz).items():
            parts.append((v, np.tile(np.array(col, np.float32) * _shade(np.array(n, np.float32)), (len(v), 1))))
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.clip(np.concatenate([p[1] for p in parts]), 0, 255).astype(np.uint8)
    col = np.concatenate([col, np.full((len(col), 1), 255, np.uint8)], 1) if col.shape[1] == 3 else col
    return make_model(pos, np.zeros((len(pos), 2), np.float32), col)


def weapon_model(kind):
    d = weaponart.DEPTH[kind]
    model = _boxes_model([(x + w / 2, y, 0.0, w, h, d, c) for x, y, w, h, c in weaponart.BOXES[kind]])
    return object_detail(model, "metal", sum(map(ord, kind)))


def dog_model(coat, frame):
    import dogart
    return object_detail(_boxes_model(dogart.boxes(coat, frame)), "fur", coat)


def bird_model(art, frame):
    import birdart
    return object_detail(_boxes_model(birdart.boxes(art, frame)), "feather", sum(map(ord, str(art))))


def wreck_model(kind, seed):
    """What is left of a broken tree / post / prop: a charred stump, a bent pole lying down, a crumpled heap."""
    rg = random.Random(seed)
    if kind == "tree":
        return _boxes_model([(0, 0, 0, 0.5, 0.9, 0.5, (52, 40, 30)), (0.1, 0.9, 0.05, 0.3, 0.4, 0.25, (36, 30, 26))])   # the stump: the felled tree itself lies beside it (render, w.fallen)
    if kind == "post":
        return _boxes_model([(0, 0, 0, 0.3, 0.5, 0.3, (88, 88, 92)), (1.9, 0.0, 0.1, 3.6, 0.14, 0.14, (110, 110, 116)),
                             (3.8, 0.0, 0.1, 0.6, 0.16, 0.3, (80, 80, 84))])
    boxes = []
    for i in range(5):
        c = rg.choice(((84, 90, 96), (110, 84, 60), (60, 70, 66), (130, 126, 120)))
        boxes.append((rg.uniform(-0.35, 0.35), rg.uniform(0, 0.12) + 0.0, rg.uniform(-0.35, 0.35), rg.uniform(0.25, 0.6),
                      rg.uniform(0.08, 0.25), rg.uniform(0.15, 0.45), c))
    return _boxes_model(boxes)


def pickup_model(kind):
    if kind == "burek":
        return object_detail(make_model(*prism_arrays(0.55, 0.42, 9, (240, 200, 90), (196, 130, 60))), "paper")
    if kind == "cash":
        return object_detail(make_model(*prism_arrays(0.42, 0.14, 6, (120, 200, 110), (60, 140, 70))), "paper", 6)
    if kind in weaponart.BOXES:                          # the weapon itself, barrel along +x (spun in the world, held by the avatar)
        return weapon_model(kind)
    if kind == "fuel":                                   # red jerry can
        return object_detail(make_model(*prism_arrays(0.45, 0.6, 4, (210, 40, 30), (150, 20, 20))), "plastic")
    return object_detail(make_model(*prism_arrays(0.32, 0.7, 8, (240, 240, 240), (190, 36, 30))), "ceramic")


# ------------------------------------------------------------------ sun state shared by the ground, road and building shaders
SHADOW_TEX = None               # packed-depth texture of the sun's view (set by sunshadow.py); models made later bind it to map 3
_sun_shaders = []               # (shader, {uniform: location})
_sun_state = {"L": SUN.copy(), "vp": np.eye(4), "shd": (0.0, 1.0 / 2048, 0.0)}


def _sun_push(sh, loc):
    L = _sun_state["L"]
    H = L + np.array([0.0, 0.894, 0.447])
    H = H / np.linalg.norm(H)
    for name, v in (("SUNL", L), ("SUNH", H)):
        if loc[name] >= 0:
            rl.set_shader_value(sh, loc[name], ffi.new("float[3]", [float(x) for x in v]), rl.SHADER_UNIFORM_VEC3)
    if loc["shd"] >= 0:
        k, texel, bias = _sun_state["shd"]
        rl.set_shader_value(sh, loc["shd"], ffi.new("float[4]", [k, texel, bias, 0.0]), rl.SHADER_UNIFORM_VEC4)
    if loc["lightVP"] >= 0:
        rl.set_shader_value_matrix(sh, loc["lightVP"], rl.Matrix(*[float(x) for x in _sun_state["vp"].ravel()]))


def _sun_register(sh):
    loc = {n: rl.get_shader_location(sh, n) for n in ("SUNL", "SUNH", "lightVP", "shd", "texture3")}
    if loc["texture3"] >= 0:
        rl.set_shader_value(sh, loc["texture3"], ffi.new("int *", 3), rl.SHADER_UNIFORM_INT)
    _sun_shaders.append((sh, loc))
    _sun_push(sh, loc)


def set_sun(toward_sun, strength, light_vp, texel, bias):
    """Move the sun: unit vector towards it, shadow strength 0..1, the shadow map's view-projection matrix (4x4, column vectors)."""
    _sun_state["L"] = np.asarray(toward_sun, np.float64)
    _sun_state["vp"] = light_vp
    _sun_state["shd"] = (float(strength), float(texel), float(bias))
    for sh, loc in _sun_shaders:
        _sun_push(sh, loc)


# ------------------------------------------------------------------ ground detail (cheap: one shader, one 256² texture)
DETAIL_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp;
out vec2 fragTexCoord; out vec4 fragColor; out vec2 wpos; out vec3 wp;
void main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; wpos = vertexPosition.xz; wp = vertexPosition;
             gl_Position = mvp * vec4(vertexPosition, 1.0); }"""
BUMP_FN = """
uniform vec3 SUNL;      // unit vector towards the sun (moves with the game clock, see set_sun)
uniform vec3 SUNH;      // half vector sun / camera (the camera looks down at ~63 deg)
uniform sampler2D texture3;     // sun shadow map: depth packed into red + green, seen from the sun
uniform mat4 lightVP;
uniform vec4 shd;       // x = shadow strength (0 = off), y = texel size, z = depth bias, w = unused
vec3 geoN(vec3 p){ return normalize(cross(dFdx(p), dFdy(p))); }                           // faces the viewer for any visible surface
// bump from a height value that is already in a register: derivatives only, so it costs no texture fetches
vec3 bumpN(vec3 p, vec3 n, float h, float strength){
  vec3 dpx = dFdx(p), dpy = dFdy(p);
  vec3 r1 = cross(dpy, n), r2 = cross(n, dpx);
  float det = dot(dpx, r1);
  vec3 g = sign(det) * (dFdx(h) * r1 + dFdy(h) * r2);
  return normalize(abs(det) * n - strength * g);
}
// real-time sun shadow: 0 = lit ... shd.x = fully shadowed. Surfaces turned away from the sun keep their baked shading.
float sunShadow(vec3 p, vec3 n){
  float nl = dot(n, SUNL);
  float k = smoothstep(0.02, 0.15, nl);
  if (shd.x <= 0.0 || k <= 0.0) return 0.0;
  vec3 s = (lightVP * vec4(p + n * (0.15 + 0.4 * (1.0 - nl)), 1.0)).xyz * 0.5 + 0.5;
  float edge = smoothstep(0.0, 0.05, min(min(s.x, 1.0 - s.x), min(s.y, 1.0 - s.y)));
  if (edge <= 0.0) return 0.0;
  float z = s.z - shd.z;
  vec2 o = vec2(0.75 * shd.y, 0.0);
  vec4 a = vec4(texture(texture3, s.xy + o.xx + o.yy).rg, texture(texture3, s.xy - o.xx - o.yy).rg);
  vec4 b = vec4(texture(texture3, s.xy + o.xy - o.yx).rg, texture(texture3, s.xy - o.xy + o.yx).rg);
  vec4 d = vec4(a.x + a.y / 255.0, a.z + a.w / 255.0, b.x + b.y / 255.0, b.z + b.w / 255.0);
  float occ = dot(vec4(lessThan(d, vec4(z))), vec4(0.25));
  return shd.x * edge * k * occ;
}
vec3 shade(vec3 c, float s){ return c * (1.0 - s * vec3(0.42, 0.37, 0.24)); }     // shadow: darker and a little blue
// rough: 0 = mirror (glass, wet water), 1 = chalk. Relights the baked colour for the bumped normal and adds the sun glint.
vec3 relight(vec3 c, vec3 n, vec3 nb, float rough, float k){
  float sk = clamp(shd.x / 0.92, 0.0, 1.0);                       // how much real sun there is: no relief relight or glint at night
  float d = 0.55 * (dot(nb, SUNL) - dot(n, SUNL)) * sk;
  c *= 1.0 + k * d / (0.52 + 0.55 * max(dot(n, SUNL), 0.0));
  float sm = 1.0 - rough;
  float spec = pow(max(dot(nb, SUNH), 0.0), mix(6.0, 120.0, sm * sm)) * sm * sm * 0.9 * sk;
  return c + vec3(1.0, 0.96, 0.88) * spec * k;
}
"""
DETAIL_FS = """#version 330
in vec2 fragTexCoord; in vec4 fragColor; in vec2 wpos; in vec3 wp;
uniform sampler2D texture0; uniform sampler2D texture1; uniform sampler2D texture2; uniform vec4 colDiffuse; uniform float time;
out vec4 finalColor;
""" + BUMP_FN + surfacepack.SHADER + """const vec3 WATER = vec3(0.337, 0.573, 0.776);
const vec3 GROUND = vec3(0.788, 0.769, 0.714);
float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
// road wear: the further from the centre (world origin), the rougher; asphalt only (dark grey), not pavements
vec3 wear(vec3 c, float road, float crack){
  if (road < 0.5) return c;
  float rough = smoothstep(500.0, 4200.0, length(wpos));
  float cr2 = texture(texture2, wpos / 3.1 + 0.37).r;
  c *= 1.0 - road * cr2 * (0.08 + 0.5 * rough);                                       // fine crazing, worse on the outskirts
  c *= 1.0 - road * crack * rough * 0.25;
  float oilz = texture(texture1, wpos / 15.0 + 0.5).g, oilf = texture(texture1, wpos / 5.3).r;
  float oil = smoothstep(0.80 - 0.06 * rough, 0.88, oilz * 0.8 + oilf * 0.3);          // oil slicks: dark, with a faint rainbow sheen
  vec3 sheen = 0.5 + 0.5 * cos(6.2832 * (oilf * 2.0 + vec3(0.0, 0.33, 0.67)));
  c = mix(c, c * 0.55 + sheen * 0.05, road * oil * 0.75);
  float pot = smoothstep(0.86 - 0.08 * rough, 0.93, texture(texture1, wpos / 9.0 + 0.2).b * 0.5 + texture(texture1, wpos / 2.7).r * 0.5 + 0.3 * rough);
  c = mix(c, c * vec3(0.45, 0.42, 0.4), road * pot * rough * 0.9);                      // potholes, only out of town
  vec2 cell = floor(wpos / 14.0);
  float h1 = h21(cell), h2 = h21(cell + 3.7), h3 = h21(cell + 8.1);
  {
    if (h1 < 0.8) {                                                                    // manhole cover: ring, disc, grating lines
      vec2 mc = (cell + 0.1 + 0.8 * vec2(h2, h3)) * 14.0;
      vec2 q = wpos - mc;
      float dm = length(q);
      float disc = 1.0 - smoothstep(0.40, 0.46, dm);
      float ring = smoothstep(0.34, 0.38, dm) * disc;
      float grate = 0.5 + 0.5 * sin(q.x * 38.0 + q.y * 5.0);
      c = mix(c, vec3(0.19, 0.18, 0.17) * (0.85 + 0.25 * grate), disc * 0.9);
      c = mix(c, vec3(0.34, 0.33, 0.31), ring * 0.7);
    }
    vec2 cell2 = floor(wpos / 41.0 + 0.13);
    float g1 = h21(cell2 + 11.3);
    if (g1 < 0.35) {                                                                    // repair strip / trench patch: fresh dark tar with an edge
      vec2 pc = (cell2 + 0.5) * 41.0 + (vec2(h21(cell2 + 2.1), h21(cell2 + 5.9)) - 0.5) * 20.0;
      vec2 q = wpos - pc;
      if (g1 < 0.175) q = q.yx;
      vec2 a = abs(q) - vec2(3.0 + 5.0 * h21(cell2 + 1.1), 0.55 + 0.5 * h21(cell2 + 4.4));
      float inside = 1.0 - smoothstep(-0.05, 0.05, max(a.x, a.y));
      float edge = (1.0 - smoothstep(0.0, 0.08, abs(max(a.x, a.y)))) * 0.6;
      c = mix(c, c * 0.62, inside * 0.8);
      c = mix(c, c * 1.35, edge);
    }
  }
  return c;
}
void main(){
  vec4 base = texture(texture0, fragTexCoord) * colDiffuse * fragColor;
  vec4 w = texture(texture1, wpos / 53.0 + 0.31);                // large-scale warp + scale drift: the 3.5 m grain tile never lines up twice
  vec2 uv = wpos / (3.5 + 1.6 * w.b) + (w.gr - 0.5) * 1.3;
  vec4 d = texture(texture1, uv);
  d.a *= 0.9;
  float hl = texture(texture1, uv + vec2(0.45, 0.4) / 256.0).r - d.r;   // bump: height step towards the fixed sun (one fetch)
  float lit = clamp((0.8 + 7.0 * hl) * 1.25, 0.6, 1.25);
  float ground = 1.0 - smoothstep(0.05, 0.16, distance(base.rgb, GROUND));
  float grass = clamp((base.g - max(base.r, base.b)) * 8.0, 0.0, 1.0);
  float k = max(max(ground, grass), 0.3);                          // roads keep a light asphalt grain
  if (generatedSurfaces != 0) k *= 0.45;
  vec3 c = base.rgb * mix(1.0, lit * (0.88 + 0.24 * d.g), k);
  if (ground > 0.0) {                                              // dirt / ochre-green patches: only on bare ground (texture fetches skipped elsewhere)
    float big = texture(texture1, wpos / 41.0).b;                  // large patches of dirt / worn ground
    float big2 = w.b;                                              // the 53 m warp sample doubles as the second, incommensurate patch scale
    float macro = texture(texture1, mat2(0.6, 0.8, -0.8, 0.6) * wpos / 211.0 + 0.3).b;
    c = mix(c, c * vec3(0.93, 0.88, 0.8), ground * smoothstep(0.55, 0.8, big * 0.55 + big2 * 0.45) * 0.8);   // dirt patches
    c *= mix(vec3(1.0), mix(vec3(1.08, 0.97, 0.78), vec3(0.84, 1.04, 0.82), smoothstep(0.3, 0.7, macro)), ground * 0.85);   // dry ochre ... fresh green stretches
  }
  c = mix(c, c * vec3(0.8, 0.95, 0.75), grass * d.a * 0.6);                           // grass blades
  float lum = dot(base.rgb, vec3(0.333));
  float grey = 1.0 - clamp((max(base.r, max(base.g, base.b)) - min(base.r, min(base.g, base.b))) * 9.0, 0.0, 1.0);
  float paved = grey * (1.0 - grass) * (1.0 - ground);                                 // asphalt and concrete: cracks and patches
  if (paved > 0.0) {
    vec4 cr = texture(texture2, wpos / 7.0);
    float crack = cr.r * smoothstep(0.45, 0.75, texture(texture1, wpos / 29.0).b + 0.25);   // cracks come in worn zones
    c *= 1.0 - paved * crack * (lum > 0.5 ? 0.35 : 0.55);
    c = mix(c, c * 0.82, paved * cr.g * 0.7);                            // tar patches / potholes
    float road = paved * (1.0 - smoothstep(0.38, 0.52, lum));
    c = wear(c, road, crack);
  }
  float wet = 1.0 - smoothstep(0.04, 0.12, distance(base.rgb, WATER));   // rivers / lakes: moving ripples
  vec4 material = vec4(0.5);
  float materialBump = 0.0;
  if (generatedSurfaces != 0) {
    float asphalt = grey * (1.0 - smoothstep(0.47, 0.59, lum));
    float paving = (1.0 - smoothstep(0.025, 0.085, distance(base.rgb, vec3(0.72, 0.70, 0.66)))) * (1.0 - ground);
    float plants = smoothstep(0.01, 0.12, base.g - max(base.r, base.b));
    float soil = max(ground, smoothstep(0.04, 0.17, base.r - base.b) *
                             smoothstep(0.005, 0.09, base.r - base.g) *
                             smoothstep(0.025, 0.09, base.g - base.b));
    float family = asphalt >= paving ? 0.0 : 1.0;
    float coverage = max(asphalt, paving);
    if (plants > coverage) { family = 2.0; coverage = plants; }
    if (soil > coverage) { family = 3.0; coverage = soil; }
    vec2 uvMaterial = wpos / 3.0;
    coverage *= 1.0 - wet;
    if (generatedSurfaces == 2 && wet > 0.5){
      family = 8.0;
      coverage = wet;
      uvMaterial = wpos / 4.0 + vec2(time * 0.017, time * 0.009);
    }
    material = surfaceSample(uvMaterial, wpos, family, coverage);
    materialBump = surfaceAmplitude(family);
    if (generatedSurfaces == 1) c *= material.rgb * 2.0;
  }
  float wh = 0.0;
  if (wet > 0.0) {
    float r1 = texture(texture1, wpos / 9.0 + vec2(time * 0.031, time * 0.012)).r;
    float r2 = texture(texture1, wpos / 6.0 - vec2(time * 0.019, -time * 0.027)).r;
    float wave = r1 + r2 - 1.0;
    vec3 wc = base.rgb * (1.0 + wave * 0.22) + vec3(0.9, 0.95, 1.0) * smoothstep(0.38, 0.5, wave) * 0.25;
    c = mix(c, wc, wet);
    wh = wave * 0.5 + 0.5;
  }
  {
    float fadeb = 1.0 - smoothstep(40.0, 130.0, gl_FragCoord.z / gl_FragCoord.w);          // relief only up close
    vec3 n0 = geoN(wp);
    float hb = mix(d.r, wh, wet);
    float strg = mix(mix(0.10, 0.05, grass), 0.012, wet);
    if (generatedSurfaces != 0) strg *= mix(0.45, 1.0, wet);
    vec3 nb = bumpN(wp, n0, hb, strg * 1.25);
    if (generatedSurfaces == 2){
      c *= mix(vec3(1.0), material.rgb * 2.0, mix(1.0, 0.32, wet));
      nb = surfaceNormal(wp, nb, material.a, materialBump);
    }
    float rough = mix(mix(0.92, 0.97, grass), 0.86, paved);                                // grass / dirt chalky, asphalt a little tighter
    rough = mix(rough, 0.12, wet);                                                         // water: glossy
    c = relight(c, n0, nb, rough, fadeb * mix(0.7, 1.4, wet));
  }
  c = shade(c, sunShadow(wp, geoN(wp)));
  finalColor = vec4(c, base.a);
}"""
# the road / prop mesh (one material for both): only flat dark-grey surfaces get the road wear, walls and trees stay as baked
SOLID_FS = DETAIL_FS[:DETAIL_FS.index("void main(){")]+ """void main(){
  vec4 base = texture(texture0, fragTexCoord) * colDiffuse * fragColor;
  vec3 c = base.rgb;
  vec3 nrm = normalize(cross(dFdx(wp), dFdy(wp)));
  float lum = dot(c, vec3(0.333));
  float grey = 1.0 - clamp((max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b))) * 9.0, 0.0, 1.0);
  float road = grey * (1.0 - smoothstep(0.38, 0.52, lum)) * step(0.92, abs(nrm.y));
  float crack = texture(texture2, wpos / 7.0).r * smoothstep(0.45, 0.75, texture(texture1, wpos / 29.0).b + 0.25);
  c *= 1.0 - road * crack * 0.3;
  c = wear(c, road, crack);
  float flatSurface = step(0.92, abs(nrm.y));
  float sw = smoothstep(0.53, 0.60, lum) * (1.0 - smoothstep(0.78, 0.83, lum))
             * (1.0 - smoothstep(0.06, 0.14, max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b))))
             * flatSurface;                                       // warm pale concrete: sidewalks, islands and ramps
  float grass = smoothstep(0.05, 0.105, base.g - max(base.r, base.b)) * flatSurface;
  vec4 grain = texture(texture1, wpos / 2.3);
  float detailStrength = generatedSurfaces == 0 ? 1.0 : 0.65;
  c *= 1.0 + detailStrength * ((0.24 * road + 0.34 * grass) * (grain.r - 0.5) - 0.14 * grass * grain.a);
  if (sw > 0.0) {
    vec2 sp = wpos / vec2(0.95, 0.62) + vec2(0.0, 0.0);
    vec2 cell = floor(sp);
    float tone = h21(cell + 3.7);
    vec2 f = abs(fract(sp) - 0.5);
    float fw = fwidth(wpos.x) + fwidth(wpos.y);
    float seam = smoothstep(0.455, 0.485, max(f.x, f.y)) * (1.0 - smoothstep(0.05, 0.2, fw));
    float grit = texture(texture1, wpos / 1.7).r - 0.5;
    float stain = smoothstep(0.55, 0.8, texture(texture1, wpos / 23.0).b);
    c *= 1.0 + sw * detailStrength * ((tone - 0.5) * 0.09 + grit * 0.1 - stain * 0.07 - seam * 0.16);
  }
  vec4 material = vec4(0.5);
  float materialBump = 0.0;
  if (generatedSurfaces != 0) {
    float family = road >= sw ? 0.0 : 1.0;
    float weight = max(road, sw);
    vec2 uv = wpos / 3.0;
    if (grass > weight) {
      family = 2.0;
      weight = grass;
      uv = wpos / 2.7;
    }
    if (generatedSurfaces == 2 && weight < 0.20){
      float leafy = smoothstep(0.045, 0.14, base.g - max(base.r, base.b));
      float bark = smoothstep(0.04, 0.14, base.r - base.b) *
                   smoothstep(0.02, 0.16, lum) * (1.0 - smoothstep(0.45, 0.65, lum));
      float upright = 1.0 - smoothstep(0.60, 0.95, abs(nrm.y));
      family = leafy > 0.25 ? 10.0 : (bark > 0.23 ? 9.0 : (lum > 0.45 ? 23.0 : 7.0));
      weight = max(leafy, upright * max(bark, 0.36)) * (1.0 - smoothstep(0.68, 0.85, lum));
      uv = surfaceProjection(wp, nrm) / (family >= 23.0 ? 2.4 : 1.2);
    }
    material = surfaceSample(uv, wpos, family, weight);
    materialBump = surfaceAmplitude(family);
    c *= material.rgb * 2.0;
  }
  {
    float fadeb = 1.0 - smoothstep(35.0, 110.0, gl_FragCoord.z / gl_FragCoord.w);
    float sat = max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b));
    float flat_ = step(0.92, abs(nrm.y));
    float hb = texture(texture1, (flat_ > 0.5 ? wpos : vec2(wp.x + wp.z, wp.y)) / 1.3).r + 0.6 * texture(texture2, wpos / 7.0).r * road;   // grain, cracks sunk in
    float strg = road > 0.5 ? 0.15 : (sw > 0.5 ? 0.1 : 0.0);
    if (generatedSurfaces != 0) strg *= 0.45;
    vec3 nb = bumpN(wp, nrm, hb, strg);
    if (generatedSurfaces == 2) nb = surfaceNormal(wp, nb, material.a, materialBump);
    float rough = mix(0.62, 0.9, flat_);                                                     // poles, signs, car bodies of the mesh: semi-gloss; ground-level slabs: matt
    rough = mix(rough, 0.95, max(max(road, sw), grass));                                      // road, pavement and grass: matt
    rough = mix(rough, 0.3, (1.0 - road) * (1.0 - sw) * (1.0 - flat_));                  // upright props (signs, billboards, lamp poles): smooth painted metal, no relief
    c = relight(c, nrm, nb, rough, fadeb);
  }
  c = shade(c, sunShadow(wp, nrm));
  finalColor = vec4(c, base.a);
}"""
# facades and roofs: texture emboss towards the fixed sun (window frames, bricks, tiles get relief), fine grit and weathering streaks
BUILD_FS = """#version 330
in vec2 fragTexCoord; in vec4 fragColor; in vec2 wpos; in vec3 wp;
uniform sampler2D texture0; uniform sampler2D texture1; uniform vec4 colDiffuse; uniform vec4 colSpecular;
out vec4 finalColor;
""" + BUMP_FN + surfacepack.SHADER + """float hh(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main(){
  vec4 base = texture(texture0, fragTexCoord) * colDiffuse * fragColor;
  vec3 nrm = normalize(cross(dFdx(wp), dFdy(wp)));
  float wall = 1.0 - step(0.6, abs(nrm.y));
  float l0 = dot(texture(texture0, fragTexCoord).rgb, vec3(0.333));
  float l1 = dot(texture(texture0, fragTexCoord + vec2(0.0035, 0.0035)).rgb, vec3(0.333));
  float emb = clamp((l1 - l0) * 1.8, -0.22, 0.22);                        // lit edges towards the sun, dark ones away
  vec2 q = wall > 0.5 ? vec2(wp.x + wp.z, wp.y) : wpos;
  float grit = texture(texture1, q / 2.1).r - 0.5;
  float stain = texture(texture1, wall > 0.5 ? vec2((wp.x + wp.z) / 11.0, wp.y / 38.0) : wpos / 17.0).b;
  float fade = 1.0 - smoothstep(60.0, 160.0, gl_FragCoord.z / gl_FragCoord.w);   // detail only up close (far away it would shimmer)
  float k = 1.0 + fade * (grit * 0.16 - (stain - 0.5) * (wall > 0.5 ? 0.22 : 0.14));
  vec3 c = base.rgb * k;
  vec4 material = vec4(0.5);
  float materialBump = 0.0;
  if ((generatedSurfaces == 1 && colSpecular.r < 0.5) || (generatedSurfaces == 2 && colSpecular.g < 0.5)) {
    // The red component carries the atlas row. Dark window glass uses the original atlas.
    float family = round((generatedSurfaces == 2 ? colSpecular.g : colSpecular.r) * 255.0);
    vec2 uv = wp.xz;
    if (wall > 0.5) uv = vec2(dot(wp.xz, normalize(vec2(nrm.z, -nrm.x))), -wp.y);
    float mask = wall > 0.5 ? smoothstep(0.27, 0.53, l0) : 1.0;
    material = surfaceSample(uv / 4.0, wpos, family, mask * fade);
    materialBump = surfaceAmplitude(family);
    c *= material.rgb * 2.0;
  }
  {
    // normal map from the facade texture: dark mortar / frames / sills sit low, glazing is smooth and glossy, plaster and brick chalky
    float sat = max(base.r, max(base.g, base.b)) - min(base.r, min(base.g, base.b));
    float glass = (1.0 - smoothstep(0.16, 0.30, l0)) * wall;                              // dark glazing
    float hb = l0 + 0.5 * grit * 0.16;
    vec3 nb = bumpN(wp, nrm, hb, 0.45 * (1.0 - glass));
    if (generatedSurfaces == 2) nb = surfaceNormal(wp, nb, material.a, materialBump);
    float rough = mix(0.88, 0.22, glass);
    rough = mix(rough, 0.75, (1.0 - wall) * 0.6);                                          // roofs: tile / metal sheet, a little sheen
    c = relight(c, nrm, nb, rough, fade * (0.9 + 1.4 * glass));
  }
  if (wall > 0.5) {
    float lum = dot(c, vec3(0.333));
    float a = hh(floor(wp.xz / 17.0)), b = hh(floor(wp.xz / 17.0) + 7.3);   // only wear varies in the shader; tone is per building (vertex colour)
    float u = wp.x + wp.z;
    float rain = smoothstep(0.52, 0.85, texture(texture1, vec2(u / 1.1, wp.y / 26.0)).r) * smoothstep(0.35, 0.7, stain);
    float blot = smoothstep(0.55, 0.9, texture(texture1, vec2(u / 9.0, wp.y / 7.0) + a).b);
    float peel = smoothstep(0.80, 0.86, texture(texture1, vec2(u / 6.0, wp.y / 5.0) + b * 9.0).b) * step(0.45, a);
    float g = 1.0 - smoothstep(90.0, 230.0, gl_FragCoord.z / gl_FragCoord.w);
    c *= 1.0 - g * (rain * 0.2 + blot * 0.16);
    c = mix(c, vec3(0.50, 0.44, 0.38) * (0.8 + lum * 0.3), peel * g * 0.55);
  }
  c *= mix(1.0, (0.52 + 0.55 * max(dot(nrm, SUNL), 0.0)) / (0.52 + 0.55 * max(dot(nrm, vec3(-0.4494, 0.7990, -0.3995)), 0.0)), clamp(shd.x / 0.92, 0.0, 1.0));   // vertex colours were lit by the old fixed sun: relight for the real one
  c = shade(c, sunShadow(wp, nrm));
  finalColor = vec4(c, base.a);
}"""
_bld = None


def building_detail():
    global _bld
    if _bld is None:
        d = ground_detail()
        _bld = False
        if d is not None:
            try:
                sh = rl.load_shader_from_memory(DETAIL_VS, BUILD_FS)
                if sh.id and sh.id != rl.rl_get_shader_id_default():
                    _sun_register(sh)
                    surfacepack.register(sh)
                    sh.locs[rl.SHADER_LOC_COLOR_SPECULAR] = rl.get_shader_location(sh, "colSpecular")
                    _bld = (sh, d[1])
            except Exception as e:  # noqa: BLE001
                print(f"[gfx] building detail off: {e}")
    return _bld or None


# Atlas rows for the baked facade and roof materials. A value of 255 skips glass and trim.
_BUILD_SURFACE_FAMILIES = (4, 7, 6, 255, 1, 4, 255, 5, 1, 1, 4, 5, 4, 1, 1, 5, 7, 255, 255, 255)
_EXPANDED_BUILD_FAMILIES = (4, 7, 6, 255, 23, 4, 255, 5, 23, 23, 4, 5, 4, 23, 12, 5, 7, 7, 7, 22)


def apply_building_detail(model, material):
    d = building_detail()
    if d is not None and model is not None:
        model.materials[0].shader = d[0]
        model.materials[0].maps[1].texture = d[1]
        model.materials[0].maps[rl.MATERIAL_MAP_SPECULAR].color = rl.Color(
            _BUILD_SURFACE_FAMILIES[material], _EXPANDED_BUILD_FAMILIES[material], 0, 255)
        if SHADOW_TEX is not None:
            model.materials[0].maps[3].texture = SHADOW_TEX


# ------------------------------------------------------------------ runtime trees (src/treegen.py): leaf sprites + wind
# One shader for trunk, limbs and sprites: vertex alpha carries the wind (bit 7 = sprite, low 7 bits = sway weight, see treegen.tree_mesh),
# the fragment shader cuts the sprite texture's alpha out and lights it like every other prop (sun + shadow map).
TREE_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp; uniform float time; uniform vec3 wind;
out vec2 fragTexCoord; out vec4 fragColor; out vec2 wpos; out vec3 wp;
flat out float leafCard;
void main(){
  fragTexCoord = vertexTexCoord; fragColor = vec4(vertexColor.rgb, 1.0);
  float a = vertexColor.a * 255.0; float leaf = step(127.5, a); float w = (a - 128.0 * leaf) / 127.0;
  leafCard = leaf;
  vec3 p = vertexPosition;
  float ph = p.x * 0.045 + p.z * 0.037;                                        // a gust front sweeping over the trees
  float gust = 0.65 + 0.35 * sin(time * 0.37 + ph * 0.5);
  float sway = sin(time * 1.15 + ph) + 0.5 * sin(time * 2.3 + ph * 1.7);
  p.xz += wind.xy * (sway * w * wind.z * gust);
  float f1 = sin(time * 5.1 + p.x * 3.7 + p.z * 2.9 + p.y * 3.3), f2 = sin(time * 4.3 + p.x * 2.3 - p.z * 3.1);
  p += vec3(f1, 0.4 * f1, f2) * (leaf * w * 0.035 * wind.z);                   // leaf shimmer
  wpos = vertexPosition.xz; wp = vertexPosition;
  gl_Position = mvp * vec4(p, 1.0); }"""
TREE_FS = DETAIL_FS[:DETAIL_FS.index("void main(){")] + """uniform float cut;       // leaves higher than this (model space) are gone: a tree shedding from the top down
flat in float leafCard;
void main(){
  vec4 base = texture(texture0, fragTexCoord);
  vec3 c = base.rgb * colDiffuse.rgb * fragColor.rgb;
  vec3 nrm = normalize(cross(dFdx(wp), dFdy(wp)));
  if (nrm.y < 0.0) nrm = -nrm;
  if (generatedSurfaces == 2){
    // Leaf cards carry an explicit flag. Solid crown LODs use green vertex colors.
    bool foliage = leafCard > 0.5 || fragColor.g > fragColor.r;
    float family = foliage ? 10.0 : 9.0;
    vec2 uv = surfaceProjection(wp, nrm) / (foliage ? 0.8 : 1.4);
    // Individual leaf sprites already depict a leaf; foliage tiles belong on crown lumps.
    float strength = leafCard > 0.5 ? 0.0 : (foliage ? 0.38 : 0.72);
    vec4 detail = surfaceSample(uv, wpos, family, strength);
    vec3 bumped = surfaceNormal(wp, nrm, detail.a, surfaceAmplitude(family));
    c = relight(c * detail.rgb * 2.0, nrm, bumped, 0.9, 0.7);
  }
  if (base.a < 0.45 || wp.y > cut) discard;
  c = shade(c, sunShadow(wp, nrm));
  finalColor = vec4(c, 1.0);
}"""
_tree = None


def tree_pack():
    """(shader, atlas texture, wind uniform location, time uniform location) for the runtime trees, or None when the GPU cannot do it."""
    global _tree
    if _tree is not None:
        return _tree or None
    _tree = False
    try:
        import treegen
        px = treegen.atlas()
        img = rl.gen_image_color(px.shape[1], px.shape[0], rl.BLACK)
        rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
        tex = rl.load_texture_from_image(img)
        rl.unload_image(img)
        rl.update_texture(tex, rl.ffi.new("unsigned char[]", px.tobytes()))
        rl.gen_texture_mipmaps(tex)
        rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
        rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_CLAMP)
        sh = rl.load_shader_from_memory(TREE_VS, TREE_FS)
        if not sh.id or sh.id == rl.rl_get_shader_id_default():
            raise RuntimeError("shader did not compile")
        _sun_register(sh)
        surfacepack.register(sh)
        _tree = (sh, tex, rl.get_shader_location(sh, "wind"), rl.get_shader_location(sh, "time"), rl.get_shader_location(sh, "cut"))
    except Exception as e:  # noqa: BLE001 - no runtime trees then (the world is built without baked ones)
        print(f"[gfx] runtime trees off: {e}")
    return _tree or None


def tree_model(pos, uv, col):
    """A runtime tree mesh (see tree_pack); None when trees are unavailable."""
    d = tree_pack()
    if d is None:
        return None
    m = make_model(pos, uv, col)
    if m is not None:
        m.materials[0].shader = d[0]
        m.materials[0].maps[0].texture = d[1]
        if SHADOW_TEX is not None:
            m.materials[0].maps[3].texture = SHADOW_TEX
        surfacepack.track(m)
    return m


def tree_cut(y):
    """Hide the leaves above model-space height y in the next tree draws (1e9: none)."""
    d = tree_pack()
    if d is not None and d[4] >= 0:
        rl.set_shader_value(d[0], d[4], rl.ffi.new("float *", float(y)), rl.SHADER_UNIFORM_FLOAT)


def tree_wind(t, amp=0.22, direction=(0.8, 0.6)):
    """Wind for this frame: t seconds, sway in metres at the very top of a tree (the leaves shimmer in proportion), horizontal direction."""
    d = tree_pack()
    if d is None:
        return
    rl.set_shader_value(d[0], d[2], rl.ffi.new("float[3]", [direction[0], direction[1], amp]), rl.SHADER_UNIFORM_VEC3)
    rl.set_shader_value(d[0], d[3], rl.ffi.new("float *", float(t)), rl.SHADER_UNIFORM_FLOAT)
    tree_cut(1e9)


_solid = None


def road_detail():
    """Wear shader for the 3D road meshes (needs the same textures as the ground detail); None when unavailable."""
    global _solid
    if _solid is None:
        d = ground_detail()
        _solid = False
        if d is not None:
            try:
                sh = rl.load_shader_from_memory(DETAIL_VS, SOLID_FS)
                if sh.id and sh.id != rl.rl_get_shader_id_default():
                    _sun_register(sh)
                    surfacepack.register(sh)
                    _solid = (sh, d[1], d[3])
            except Exception as e:  # noqa: BLE001
                print(f"[gfx] road detail off: {e}")
    return _solid or None


def apply_road_detail(model):
    d = road_detail()
    if d is not None and model is not None:
        model.materials[0].shader = d[0]
        model.materials[0].maps[1].texture = d[1]
        model.materials[0].maps[2].texture = d[2]
        if SHADOW_TEX is not None:
            model.materials[0].maps[3].texture = SHADOW_TEX


_detail = None


def _tileable_noise(n, rng, scale):
    f = np.fft.fftfreq(n)
    FX, FY = np.meshgrid(f, f)
    r = np.sqrt(FX ** 2 + FY ** 2) + 1e-6
    spec = np.fft.fft2(rng.standard_normal((n, n))) * np.exp(-(r * scale) ** 2) / r ** 0.5
    a = np.real(np.fft.ifft2(spec))
    return (a - a.min()) / (a.max() - a.min() + 1e-9)


def _upload(px, mip=True):
    n = px.shape[0]
    img = rl.gen_image_color(n, n, rl.BLACK)
    rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.update_texture(tex, rl.ffi.new("unsigned char[]", px.tobytes()))
    if mip:
        rl.gen_texture_mipmaps(tex)
        rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_REPEAT)
    return tex


def _crack_map(rng, n):
    """Tileable crack network (R: Voronoi cell borders, wobbly and broken) and patch blobs (G)."""
    pts = rng.random((14, 2)) * n
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    wob = (_tileable_noise(n, rng, 12) - 0.5) * 14
    xx, yy = xx + wob, yy + wob.T
    d1 = np.full((n, n), 1e9)
    d2 = np.full((n, n), 1e9)
    for px, py in pts:
        for ox in (-n, 0, n):
            for oy in (-n, 0, n):
                d = np.hypot(xx - px - ox, yy - py - oy)
                d2 = np.minimum(d2, np.maximum(d1, d))
                d1 = np.minimum(d1, d)
    edge = np.clip(1.0 - (d2 - d1) / 2.2, 0, 1)
    edge *= _tileable_noise(n, rng, 8) > 0.42                 # cracks are broken, not a full grid
    patch = (_tileable_noise(n, rng, 10) > 0.78).astype(np.float64)
    return (np.stack([edge, patch, np.zeros_like(edge), np.ones_like(edge)], -1) * 255).astype(np.uint8)


def ground_detail():
    """(shader, texture) for the ground chunks, or None when the GPU / driver cannot compile it."""
    global _detail
    if _detail is not None:
        return _detail or None
    try:
        rng = np.random.default_rng(7)
        n = 256
        h = 0.6 * _tileable_noise(n, rng, 6) + 0.4 * _tileable_noise(n, rng, 40)       # pebbles + fine grain
        g = _tileable_noise(n, rng, 3)
        b = _tileable_noise(n, rng, 2)
        a = (_tileable_noise(n, rng, 60) > 0.62).astype(np.float64)                   # blade specks
        px = (np.stack([h, g, b, a], -1) * 255).astype(np.uint8)
        img = rl.gen_image_color(n, n, rl.BLACK)
        rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
        tex = rl.load_texture_from_image(img)
        rl.unload_image(img)
        buf = rl.ffi.new("unsigned char[]", px.tobytes())
        rl.update_texture(tex, buf)
        rl.gen_texture_mipmaps(tex)
        rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
        rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_REPEAT)
        ctex = _upload(_crack_map(rng, 256), True)
        sh = rl.load_shader_from_memory(DETAIL_VS, DETAIL_FS)
        if not sh.id or sh.id == rl.rl_get_shader_id_default():
            raise RuntimeError("shader did not compile")
        _sun_register(sh)
        surfacepack.register(sh)
        _detail = (sh, tex, rl.get_shader_location(sh, "time"), ctex)
    except Exception as e:  # noqa: BLE001 - plain baked ground then
        print(f"[gfx] ground detail off: {e}")
        _detail = False
    return _detail or None


def apply_ground_detail(model):
    d = ground_detail()
    if d is not None and model is not None:
        model.materials[0].shader = d[0]
        model.materials[0].maps[1].texture = d[1]
        model.materials[0].maps[2].texture = d[3]
        if SHADOW_TEX is not None:
            model.materials[0].maps[3].texture = SHADOW_TEX


def ground_time(t):
    """Animate the water (once per frame)."""
    d = ground_detail()
    if d is not None and d[2] >= 0:
        rl.set_shader_value(d[0], d[2], rl.ffi.new("float *", t % 10000.0), rl.SHADER_UNIFORM_FLOAT)
