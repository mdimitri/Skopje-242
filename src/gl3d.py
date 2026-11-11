"""3D helpers: mesh upload, procedural textures, procedural car / pedestrian / pickup models (with dents)."""
import math
import random

import numpy as np

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


def _cyl(cx, cy, cz, R, wd, tyre, hub, sides=8):
    """Wheel with its axis along z. Returns (verts, colours)."""
    vs, cs = [], []
    for i in range(sides):
        a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
        p0 = (cx + R * math.cos(a0), cy + R * math.sin(a0))
        p1 = (cx + R * math.cos(a1), cy + R * math.sin(a1))
        am = (a0 + a1) / 2
        sh = 0.55 + 0.5 * max(0.0, math.cos(am) * 0.4 + math.sin(am) * 0.9)
        za, zb = cz - wd / 2, cz + wd / 2
        vs += [(p0[0], p0[1], za), (p1[0], p1[1], za), (p1[0], p1[1], zb), (p0[0], p0[1], za), (p1[0], p1[1], zb), (p0[0], p0[1], zb)]
        cs += [tyre * sh] * 6
        for z, c, r in ((za, tyre * 0.8, R), (zb, tyre * 0.8, R), (zb + 0.012, hub, R * 0.58), (za - 0.012, hub, R * 0.58)):
            q0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
            q1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
            vs += [(cx, cy, z), (q0[0], q0[1], z), (q1[0], q1[1], z)]
            cs += [c] * 3
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
    for k in range(4):
        quad((xf + 0.016, yb + 0.3 + k * 0.1, -cw * 0.3), (0, 0, cw * 0.6), (0, 0.025, 0), (1, 0, 0), chrome)
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
        if ex == "tanker":
            col = (196, 200, 208)
        if ex == "mixer":                                                  # rotating drum, built from stepped boxes
            for i, (dx, sh, wd) in enumerate(((0.0, 1.5, 1.1), (0.6, 1.8, 1.7), (1.4, 2.0, 2.0), (2.2, 1.8, 1.7), (2.8, 1.4, 1.2))):
                xx = xb + 0.5 + dx * 0.95
                box(xx, belt, 0, 1.0, sh, W * 0.9 * wd / 2.0 + 0.2, (236, 140, 40) if i % 2 == 0 else (210, 120, 30))
            quad((xb + 0.6, belt + 2.05, -0.5), (3.0, 0, 0), (0, 0, 1.0), (0, 1, 0), (240, 240, 240))
        else:
            from_h = top_h - belt if ex != "fire" else 1.5
            for name, (v, n) in box_faces(cgx, belt, 0, cgl, from_h, W * 0.96, 6, 3, 3).items():
                parts.append((v, np.tile(np.array(col, np.float32) * _shade(np.array(n, np.float32)), (len(v), 1)), True))
            if ex in ("tanker", "semi"):                                  # livery stripe along the tank / trailer
                for sd in (-1, 1):
                    quad((xb + 0.5, belt + from_h * 0.4, sd * (W * 0.48 + 0.012)), (cgl - 1.0, 0, 0), (0, 0.4, 0), (0, 0, sd), (200, 40, 40) if ex == "tanker" else (40, 90, 170))
            if ex == "garbage":
                box(xb - 0.1, belt + 0.1, 0, 0.5, 1.6, W * 0.8, (30, 90, 50))
                for s in (-1, 1):
                    quad((xb + 0.4, belt + 0.8, s * (W * 0.48 + 0.01)), (cgl - 0.8, 0, 0), (0, 0.25, 0), (0, 0, s), (30, 100, 56))
            if ex == "fire":
                for s in (-1, 1):
                    box(cgx, belt + 1.5, s * 0.4, cgl * 0.9, 0.06, 0.08, (210, 210, 214))
                for k in range(6):
                    box(xb + 0.8 + k * (cgl - 1.2) / 5, belt + 1.5, 0, 0.06, 0.05, 0.8, (210, 210, 214))
                for s in (-1, 1):
                    for k in range(3):
                        quad((xb + 0.5 + k * cgl * 0.3, belt + 0.1, s * (W * 0.48 + 0.01)), (cgl * 0.27, 0, 0), (0, 1.1, 0), (0, 0, s), (176, 178, 184))
        if ex in ("fire", "garbage"):
            bar(cx, 0.0, (230, 40, 40), (240, 150, 30) if ex == "garbage" else (40, 90, 230))
        return
    if st == "tractor":
        box(xf - 0.8, belt + 0.5, 0, 0.12, 1.0, 0.12, (30, 30, 34))        # exhaust
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
                            cc = cI if sd == 1 else 3 - cI                  # the left side is read the other way round
                            quad((x0 + gi * (4 * cell + gap) + cc * cell, belt - 0.08 - (r + 1) * cell, sd * (W / 2 + 0.014)), (cell, 0, 0), (0, cell, 0), (0, 0, sd), (246, 246, 250))
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


def _bike_parts(ex, body_c, A, box, quad, parts):
    """Two-wheelers (x forward, y up, z right), no rider. ex = bike | moped | scooter | kick."""
    dark, steel, tyre, hub = (36, 36, 40), (150, 152, 158), A((24, 24, 26)), A((170, 170, 176))
    bc = tuple(body_c)

    def wheel(x, r, wd):
        v, c = _cyl(x, r, 0.0, r, wd, tyre, hub)
        parts.append((v, c, False))

    if ex == "bike":
        wheel(0.62, 0.34, 0.05)
        wheel(-0.62, 0.34, 0.05)
        box(0.0, 0.58, 0, 1.0, 0.045, 0.045, bc)                  # top tube
        box(-0.12, 0.34, 0, 0.95, 0.04, 0.04, bc)                 # down tube / chain stay
        box(-0.3, 0.34, 0, 0.04, 0.34, 0.04, bc)                  # seat tube
        box(0.46, 0.34, 0, 0.04, 0.30, 0.04, steel)               # fork
        box(0.5, 0.88, 0, 0.05, 0.05, 0.5, dark)                  # handlebar
        box(0.5, 0.64, 0, 0.04, 0.26, 0.04, steel)                # stem
        box(-0.3, 0.86, 0, 0.26, 0.07, 0.12, dark)                # saddle
        box(0.02, 0.28, 0, 0.18, 0.18, 0.05, steel)               # chainring
        box(0.6, 0.72, 0, 0.08, 0.1, 0.11, (236, 232, 210))       # lamp (one, on the centre line, like a real bike)
        quad((0.642, 0.73, -0.045), (0, 0, 0.09), (0, 0.08, 0), (1, 0, 0), (255, 244, 180))
        box(-0.44, 0.74, 0, 0.05, 0.06, 0.09, (210, 30, 30))      # rear reflector / tail light under the saddle
    elif ex == "kick":
        wheel(0.46, 0.14, 0.05)
        wheel(-0.46, 0.14, 0.05)
        box(0.0, 0.14, 0, 0.95, 0.07, 0.24, dark)                 # deck
        box(0.44, 0.60, 0, 0.05, 0.9, 0.05, steel)                # column
        box(0.44, 1.02, 0, 0.05, 0.05, 0.5, dark)                 # bars
        box(-0.5, 0.22, 0, 0.18, 0.04, 0.2, bc)                   # brake plate
        box(0.47, 0.9, 0, 0.05, 0.08, 0.1, (236, 232, 210))       # lamp on the column
        quad((0.497, 0.91, -0.04), (0, 0, 0.08), (0, 0.06, 0), (1, 0, 0), (255, 244, 180))
        box(-0.58, 0.18, 0, 0.03, 0.06, 0.14, (210, 30, 30))      # tail light on the brake plate
    else:
        mo = ex == "moped"
        r = 0.27 if mo else 0.24
        wheel(0.68, r, 0.1)
        wheel(-0.68, r, 0.1)
        box(-0.05, 0.28, 0, 1.0, 0.1, 0.34, dark)                 # floor / frame
        box(-0.5, 0.55, 0, 0.65, 0.34, 0.3, bc)                   # rear body
        box(0.5, 0.58, 0, 0.12, 0.55, 0.34, bc)                   # leg shield
        box(0.0, 0.76 if mo else 0.7, 0, 0.58, 0.1, 0.26, dark)   # seat
        box(0.55, 0.98, 0, 0.1, 0.07, 0.62, dark)                 # handlebar
        box(0.62, 0.96, 0, 0.12, 0.14, 0.2, bc)                   # headlight housing
        quad((0.685, 0.9, -0.08), (0, 0, 0.16), (0, 0.1, 0), (1, 0, 0), (255, 244, 180))
        quad((-0.835, 0.55, -0.1), (0, 0, 0.2), (0, 0.1, 0), (-1, 0, 0), (210, 30, 30))
        box(-0.82, 0.44, 0, 0.1, 0.12, 0.2, (236, 236, 230))      # plate
        if mo:
            box(0.0, 0.5, 0.26, 0.5, 0.2, 0.1, steel)              # engine cover
        else:
            box(-0.82, 0.84, 0, 0.3, 0.36, 0.38, bc)               # delivery box
            box(-0.82, 1.2, 0, 0.32, 0.05, 0.4, bc)


_TYRE_R = {"mini": 0.27, "hatch": 0.30, "sedan": 0.31, "taxi": 0.31, "wagon": 0.31, "limo": 0.33, "van": 0.34,
           "suv": 0.38, "pickup": 0.38}


def _wheel_layout(st, L):
    """(x, radius, width) of every wheel pair, the front axle first."""
    if L > 11:
        return [(L * 0.34, 0.5, 0.3), (-L * 0.28, 0.5, 0.3), (-L * 0.38, 0.5, 0.3)]
    r = _TYRE_R.get(st, 0.34)                                      # real tyre radii: 13" Yugo ~0.28 m, SUV ~0.38 m
    return {"bus": [(L * 0.32, 0.50, 0.26), (-L * 0.30, 0.50, 0.26)],
            "truck": [(L * 0.36, 0.5, 0.34), (-L * 0.22, 0.5, 0.34), (-L * 0.36, 0.5, 0.34)],
            "tractor": [(L * 0.36, 0.45, 0.28), (-L * 0.28, 0.85, 0.5)]}.get(st, [(L * 0.31, r, 0.26), (-L * 0.31, r, 0.26)])


def front_wheel(kind):
    """(axle x, track half-width z, wheel model with its centre at the origin) of a car's front wheels, which the renderer
    turns by the steering angle (car_arrays(steer_wheels=True) leaves them out of the body)."""
    L, W = V.DIMS[kind % V.N][:2]
    semi = V.EXTRA[kind % V.N] == "semi"
    wx, wr, wd = _wheel_layout(V.STYLE[kind % V.N], V.SEMI_TRACTOR_L if semi else L)[0]
    wx += V.SEMI_SHIFT if semi else 0.0
    v, c = _cyl(0.0, 0.0, 0.0, wr, wd, np.array((26, 26, 28), np.float32), np.array((158, 158, 164), np.float32))
    rgba = np.empty((len(v), 4), np.uint8)
    rgba[:, :3] = np.clip(c, 0, 255)
    rgba[:, 3] = 255
    return wx, wr, W / 2 - 0.02, make_model(v, np.zeros((len(v), 2), np.float32), rgba)


def car_arrays(kind, color, dents=(), burnt=0.0, player=False, steer_wheels=False):
    """Vertices/colours of a car in local space (x forward, y up, z right); dents = [(lx, lz, nx, nz, mag)]."""
    kind = kind % V.N
    L, W, y0, belt, roof = V.DIMS[kind]
    st = V.STYLE[kind]
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
        _bike_parts(ex, body_c, A, box, quad, parts)
        return _finish_arrays(parts, dents, burnt, belt)

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
    addf(box_faces(0, y0, 0, L, add_box_h, BW, 8 if L < 7 else 14, 2, 4), body_col)

    cl_f, cx_f, ft, rt, stp, nwin = _CAB[st]
    if L > 11:
        nwin = 9
    era = _ERA.get(_ERA_OF.get(V.IDS[kind]))
    if era is not None:
        ft, rt, stp = max(0.0, ft + era[3]), max(0.0, rt + era[4]), stp + era[5]
    cl, cx = L * cl_f, L * cx_f
    if st == "truck":                                                      # forward-control cab, 2.3-2.5 m long, flush with the nose
        cl = min(2.45, 0.27 * L)
        cx = L / 2 - cl / 2
        roof = belt + 1.9
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
        quad((xf + 0.006, y0 + 0.05, -0.20 * W), (0, 0, 0.40 * W), (0, 0.35, 0), (1, 0, 0), (28, 28, 32))
    if st == "van":
        quad((xf + 0.006, belt - 0.5, -0.04), (0, 0, 0.08), (0, 0.42, 0), (1, 0, 0), (210, 210, 214))                       # VW "V"
    bump_c = (120, 122, 128) if st not in ("bus", "taxi") else (60, 62, 66)
    bh = 0.2 if st != "bus" else 0.3
    box(xf + 0.04, y0, 0, 0.12, bh, W * 1.0, bump_c)
    box(xb - 0.04, y0, 0, 0.12, bh, W * 1.0, bump_c)
    quad((xf + 0.106, y0 + 0.03, -0.2), (0, 0, 0.4), (0, 0.12, 0), (1, 0, 0), (236, 236, 226))
    quad((xb - 0.106, y0 + 0.03, -0.2), (0, 0, 0.4), (0, 0.12, 0), (-1, 0, 0), (236, 236, 226))
    wheels = _wheel_layout(st, L)
    wx_list = [w[0] for w in wheels]
    for s in (-1, 1):
        zz = s * (W / 2 + 0.008)
        for wx in wx_list:                                                  # wheel arches
            quad((wx - 0.42, y0, zz), (0.84, 0, 0), (0, 0.32, 0), (0, 0, s), (20, 20, 22))
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
    if st == "pickup":
        bx0 = cx - cl / 2 - 0.02
        quad((xb + 0.05, belt + 0.004, -W / 2 + 0.06), (bx0 - xb - 0.05, 0, 0), (0, 0, W - 0.12), (0, 1, 0), (46, 44, 42), 2, 2)
        for s in (-1, 1):
            box((xb + bx0) / 2, belt, s * (W / 2 - 0.05), bx0 - xb, 0.28, 0.08, tuple(body_c * 0.95))
        box(xb + 0.05, belt, 0, 0.08, 0.28, W - 0.1, tuple(body_c * 0.95))
        box(bx0 - 0.05, belt, 0, 0.08, 0.3, W - 0.1, tuple(body_c * 0.9))
    if st == "suv":
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
        quad((xb + 0.05, y0 - 0.02, zs), (xf - xb - 0.1, 0, 0), (0, 0.07, 0), (0, 0, s), (40, 40, 42))
        for wx, wr, _wd in wheels:
            quad((wx - wr - 0.06, y0 - 0.02, zs + s * 0.002), (2 * wr + 0.12, 0, 0), (0, wr * 0.5, 0), (0, 0, s), (22, 22, 24))
    _extras(kind, st, ex, L, W, y0, belt, roof, top_h, cx, cl, cw, body_c, accent, parts, box, quad, cab_ref=None)
    for wi, (wx, wr, wd_) in enumerate(wheels):                             # wheels (not deformable)
        if steer_wheels and wi == 0:
            continue                                                        # the front pair is drawn separately, turned
        for s in (-1, 1):
            v, c = _cyl(wx, wr, s * (W / 2 - 0.02), wr, wd_, A((26, 26, 28)), A((158, 158, 164)))
            parts.append((v, c, False))

    if semi:                                                                # move the short tractor to the front of the rig's footprint
        parts[:] = [(v + np.array((V.SEMI_SHIFT, 0, 0), np.float32), c, d) for v, c, d in parts]
    return _finish_arrays(parts, dents, burnt, belt)


def trailer_arrays():
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
        for k in range(1, 6):                                                        # panel ribs
            quad((-k * T / 6.0, y0 + 0.1, zs), (0.05, 0, 0), (0, top - y0 - 0.2, 0), (0, 0, sd), (176, 178, 184))
        box(-T + 0.15, y0 + 0.2, sd * (W / 2 - 0.2), 0.1, 0.18, 0.2, (210, 30, 30))      # tail lamps
        box(-T - 0.05, 0.62, sd * (W / 2 - 0.3), 0.04, 0.45, 0.5, (30, 30, 34))          # mudflaps
    quad((-T + 0.3 - 0.01, y0 + 0.1, -W / 2 + 0.05), (0, 0, W - 0.1), (0, top - y0 - 0.2, 0), (-1, 0, 0), (200, 202, 208))  # rear doors
    quad((-T + 0.3 - 0.012, y0 + 0.1, -0.015), (0, 0, 0.03), (0, top - y0 - 0.2, 0), (-1, 0, 0), (60, 62, 68))
    box(-T + 0.2, 0.62, 0, 0.1, 0.12, W * 0.92, (60, 62, 68))                         # underride bar
    for ax in (-T + 1.4, -T + 2.6, -T + 3.8):                                         # tri-axle
        for sd in (-1, 1):
            v, c = _cyl(ax, 0.5, sd * (W / 2 - 0.02), 0.5, 0.3, A((26, 26, 28)), A((158, 158, 164)))
            parts.append((v, c, False))
    return _finish_arrays(parts, (), 0.0, y0)


def trailer_model():
    pos, uv, col = trailer_arrays()
    return make_model(pos, uv, col)


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
    """Driver's door: (hinge x, door length) in car-local space, from the cabin layout used by car_arrays."""
    L = V.DIMS[kind][0]
    cl_f, cx_f = _CAB[V.STYLE[kind]][:2]
    cl, cx = L * cl_f, L * cx_f
    front, rear = cx + cl * 0.30, cx - cl * 0.20
    if V.STYLE[kind] in ("bus", "truck", "tractor", "pickup"):
        rear = front - min(1.0, cl * 0.5)
    if V.EXTRA[kind] == "semi":
        front, rear = V.SEMI_SHIFT + V.SEMI_TRACTOR_L / 2 - 2.45 / 2 + 0.74, V.SEMI_SHIFT + V.SEMI_TRACTOR_L / 2 - 2.45 / 2 - 0.26
    return front, max(0.6, front - rear)


def door_model(kind, color):
    """The swinging door panel; hinge at the origin, panel along -x, outer face toward -z."""
    L, W, y0, belt, roof = V.DIMS[kind]
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
    return make_model(pos, np.zeros((len(pos), 2), np.float32), rgba)


def car_model(kind, color, dents=(), burnt=0.0, player=False, steer_wheels=False):
    pos, uv, col = car_arrays(kind, color, dents, burnt, player, steer_wheels)
    return make_model(pos, uv, col)


# ------------------------------------------------------------------ pedestrians
SKIN = [(236, 190, 160), (200, 150, 110), (150, 105, 80), (240, 205, 180)]
HAIR = [(50, 36, 28), (190, 150, 80), (20, 20, 22), (120, 70, 40)]


def _swing(parts, i0, px, py, ang):
    """Rotate the boxes parts[i0:] about the pivot (px, py) in the walking plane (x forward, y up): a limb swings from its joint."""
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


def _leg(parts, add, z, a, flex, hip, col, shin_col, shoe, feet, sole=None, heel=False, w=0.17, toe=0.28):
    """Thigh from the hip, shin from the knee, foot from the ankle (toes forward). The thigh swings by a, the shin
    bends back by flex at the knee; the boxes overlap at the joints so no gap opens when they bend.
    The foot boxes' indices go to feet (the caller plants the lowest one on the ground)."""
    k = hip / 2
    i0 = len(parts)
    add(0.0, k - 0.03, z, w + 0.02, hip - k + 0.05, w, col)                  # thigh: knee .. a little above the hip
    i1 = len(parts)
    add(0.0, 0.07, z, w, k - 0.03, w - 0.02, shin_col)                       # shin: ankle .. knee
    f0 = len(parts)
    add(0.06, 0.0, z, toe, 0.09, w, shoe)
    if sole:
        add(0.06, 0.0, z, toe + 0.01, 0.02, w + 0.01, sole)
    if heel:
        add(-0.06, 0.0, z, 0.04, 0.12, 0.05, shoe)
    feet.extend(range(f0, len(parts)))
    _swing(parts, i0, 0.0, hip, a)
    _swing(parts, i1, k * math.sin(a), hip - k * math.cos(a), -flex)


def _arm(parts, add, x, sh, z, a, bend, col, hand, u=0.34, f=0.3, w=0.13, fore=None, held=()):
    """Upper arm from the shoulder (x, sh), forearm from the elbow, hand; held = boxes (cx, y, cz, sx, sy, sz, col)
    gripped in the hand, which move with the forearm. The arm swings by a, the forearm bends forward by bend."""
    i0 = len(parts)
    add(x, sh - u - 0.02, z, w, u + 0.06, w - 0.01, col)                     # upper arm: elbow .. into the shoulder
    i1 = len(parts)
    add(x, sh - u - f + 0.02, z, w - 0.01, f, w - 0.02, fore if fore is not None else col)
    add(x, sh - u - f - 0.1, z, w - 0.02, 0.12, w - 0.03, hand)
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
        add(0.2, 1.24, 0.3, 0.36, 0.13, 0.13, arm)            # right upper arm, horizontal from the shoulder
        add(0.54, 1.24, 0.3, 0.34, 0.12, 0.12, arm)           # forearm
        add(0.72, 1.23, 0.3, 0.14, 0.14, 0.14, sk)            # fist
        add(0.06, 1.0, -0.34, 0.13, 0.38, 0.12, arm)          # left upper arm hangs from the shoulder to the elbow
        add(0.2, 1.0, -0.3, 0.3, 0.12, 0.12, arm)             # forearm raised forward (guard)
        add(0.38, 1.0, -0.3, 0.12, 0.13, 0.12, sk)
    else:
        add(0.28, 0.74, 0.11, 0.56, 0.18, 0.16, legc)         # thigh forward
        add(0.7, 0.8, 0.11, 0.34, 0.16, 0.15, legc)           # shin swinging up
        add(0.9, 0.8, 0.11, 0.26, 0.12, 0.18, shoe)           # foot


def _ped_special(arch, tone, frame, skin):
    """The 30 extra road users (arch 10..39): walkers with props, plus cyclists, mopeds, scooters, skaters and a horse cart."""
    A = lambda c: np.array(c, np.float32)
    strike = frame if frame in (4, 5) else 0
    if strike:
        frame = 0
    name = V.PED_IDS[arch]
    sk = A(SKIN[skin % 4])
    hair = A(HAIR[(skin + tone) % 4])
    parts = []

    def add(cx, y, cz, sx, sy, sz, col, pitch=0.0):
        for nm, (v, n) in box_faces(cx, y, cz, sx, sy, sz).items():
            parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1))))

    def wheel(x, y, z, r, wd, col=(26, 26, 28), hub=(170, 170, 176)):
        v, c = _cyl(x, y, z, r, wd, A(col), A(hub))
        parts.append((v, c))

    # (scale, torso colours, legs, shoes, skirt?, hat kind)
    D = dict(scale=1.0, torso=(120, 120, 130), legs=(52, 66, 104), shoe=(30, 28, 28), skirt=None, rider=None,
             belly=0.0, wide=0.0, shorts=False, arms_up=False, head_fwd=0.0, stride=1.0, grip=None)
    hat = None
    held = []                         # (sx, sy, sz, col, y, z) hand-held boxes swinging with the right arm
    held_l = []                       # ... and with the left
    extra = []                        # static boxes (x, y, z, sx, sy, sz, col) in body space
    P3 = lambda a, b, c: [a, b, c][tone % 3]
    if name == "Pandur":
        D.update(torso=(70, 92, 134), legs=(44, 54, 86)); hat = ("cap", (40, 54, 94))
        extra += [(0, 0.84, 0, 0.3, 0.06, 0.54, (240, 240, 240))]
        held = [(0.06, 0.5, 0.06, (240, 240, 240), 0.55, 0.0)]
    elif name == "Parkingar":
        D.update(torso=(255, 150, 0), legs=(60, 60, 72)); hat = ("cap", (250, 220, 40))
        extra += [(0.0, 0.95, 0, 0.3, 0.06, 0.54, (240, 240, 120)), (0.16, 0.8, 0.0, 0.02, 0.6, 0.12, (240, 240, 120))]
        held = [(0.2, 0.03, 0.15, (240, 240, 240), 0.7, 0.0)]
    elif name == "Pop":
        D.update(torso=(22, 22, 26), legs=(22, 22, 26), skirt=(22, 22, 26), scale=1.04); hat = ("tall", (22, 22, 26))
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
        D.update(torso=(130, 100, 70), legs=(60, 60, 72), scale=0.95); hat = ("flat", (110, 102, 92))
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
        extra += [(0.98, 0.28, 0, 0.75, 0.1, 0.55, (230, 230, 236)), (0.98, 0.38, 0, 0.6, 0.4, 0.5, (240, 160, 190)),
                  (0.64, 0.38, 0, 0.06, 0.62, 0.42, (60, 60, 66))]                # pram, its push bar in both hands
        D["grip"] = (0.62, 0.98)
    elif name == "Partiski Aktivist":
        D.update(torso=(50, 90, 200), legs=(36, 40, 60)); hat = None
        extra += [(0.14, 0.9, 0, 0.03, 0.4, 0.05, (210, 30, 40)), (0.0, 0.62, -0.4, 0.1, 0.3, 0.3, (240, 240, 240))]
        held = [(0.03, 1.5, 0.03, (170, 150, 120), 0.2, 0.0), (0.02, 0.45, 0.7, (210, 30, 40), 1.6, 0.0)]
    elif name == "Advokat":
        D.update(torso=(30, 32, 40), legs=(30, 32, 40), scale=1.03); hat = None
        extra += [(0.14, 0.9, 0, 0.02, 0.5, 0.14, (236, 236, 236)), (0.14, 1.46, 0, 0.1, 0.05, 0.24, (14, 14, 16))]
        held = [(0.1, 0.28, 0.42, (190, 192, 198), 0.2, 0.0)]
    elif name == "Teretana Brat":
        D.update(torso=(232, 232, 236), legs=(30, 30, 36), scale=1.1, wide=0.22, shorts=True); hat = None
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
        D.update(torso=(120, 110, 100), legs=(70, 66, 60), scale=0.93); hat = ("scarf", (150, 70, 90))
        extra += [(0.3, 0.0, 0.2, 0.14, 0.12, 0.1, (130, 130, 138)), (0.5, 0.0, -0.2, 0.14, 0.12, 0.1, (110, 110, 120)),
                  (0.25, 0.0, -0.4, 0.14, 0.12, 0.1, (150, 150, 156)), (0.12, 0.7, 0.4, 0.2, 0.22, 0.14, (230, 220, 190))]
    elif name == "Komunalec":
        D.update(torso=(150, 180, 220), legs=(40, 44, 58)); hat = ("flat", (30, 44, 80))
        extra += [(0.14, 0.9, 0, 0.02, 0.45, 0.06, (160, 30, 40))]
        held = [(0.2, 0.03, 0.26, (200, 40, 40), 0.7, 0.0)]
    elif name == "Nevesta":
        D.update(torso=(248, 248, 250), legs=(248, 248, 250), skirt=(248, 248, 250)); hat = ("long", tuple(hair))
        extra += [(0.0, 0.1, 0, 0.7, 0.55, 0.8, (248, 248, 250)), (-0.18, 0.7, 0, 0.03, 0.95, 0.42, (240, 240, 246))]
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
        D.update(torso=(120, 100, 70), legs=(70, 64, 56), scale=0.95, rider="old"); hat = ("flat", (110, 102, 92))
    elif name == "Moped Tomos":
        D.update(torso=(90, 60, 40), legs=(40, 50, 80), rider="moped"); hat = None
    elif name == "Glovo Skuter":
        D.update(torso=(255, 208, 0), legs=(36, 40, 50), rider="courier"); hat = ("helmet", (240, 240, 240))
    elif name == "Trotinet Dete":
        D.update(torso=P3((240, 80, 80), (60, 180, 240), (250, 200, 40)), legs=(52, 66, 104), scale=0.64, rider="kick"); hat = ("helmet", (240, 120, 40))
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
    scale, torso, legc = D["scale"], D["torso"], D["legs"]
    rider = D["rider"]
    frame, th, lean, ph, run = _phase(frame)
    if strike:
        th = lean = 0.0
        ph = None
    th = max(-1.1, min(1.1, th * D["stride"]))             # (a long-striding jogger still keeps the hips together)
    sw = {0: 0.28, 1: -0.28, 2: 0.0, 3: 0.0}[frame] * D["stride"]          # (riders: pedalling / horse legs)
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
            add(1.7, 0.7, 0, 1.3, 0.6, 0.5, horse); add(2.5, 1.0, 0, 0.5, 0.5, 0.32, horse); add(2.8, 1.1, 0, 0.3, 0.2, 0.2, (90, 56, 34))
            add(2.1, 1.35, 0, 0.5, 0.1, 0.1, (40, 28, 20))
            for k, (lx, lz) in enumerate(((2.2, -0.15), (2.2, 0.15), (1.2, -0.15), (1.2, 0.15))):
                off = 0.18 * (1 if (k + frame) % 2 else -1)
                add(lx + off, 0.0, lz, 0.12, 0.7, 0.1, (90, 56, 34))
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
            add(hx0 + 0.22, 0.6, s * 0.11, 0.48, 0.15, 0.15, legc)
            i1 = len(parts)
            add(hx0 + 0.42, 0.06, s * 0.11, 0.15, 0.6, 0.15, legc)
            add(hx0 + 0.47, 0.0, s * 0.11, 0.26, 0.09, 0.16, D["shoe"])
            _swing(parts, i0, hx0, 0.67, 0.5 * pd)           # pedalling: the knee rises and falls ...
            _swing(parts, i1, hx0 + 0.42 * math.cos(0.5 * pd), 0.67 + 0.42 * math.sin(0.5 * pd), -0.6 * pd)   # ... the shin follows it
    else:
        skirt = D["skirt"] is not None
        lc2 = D["legs"]
        for s in (-1, 1):
            if strike == 5 and s > 0:
                continue
            _leg(parts, add, s * 0.11, -s * th, _knee(-s, th, ph, run), 0.82, sk if skirt else lc2, sk if (skirt or D["shorts"]) else lc2,
                 D["shoe"], feet, w=0.15 if skirt else 0.17, toe=0.38 if rider == "blades" else 0.28)
        if skirt:
            add(0.0, 0.3, 0, 0.4, 0.6, 0.48, D["skirt"])
        else:
            add(bx, 0.7, 0, 0.27, 0.16, 0.44, lc2)                # hips: cover the tops of the thighs as they swing
    # ---------------- torso, arms, head
    wd = 0.5 + D["wide"]
    add(bx, 0.8 + Y, 0, 0.26 + D["belly"], 0.62, wd, torso)
    add(bx, 1.3 + Y, 0, 0.24, 0.1, wd + 0.08, torso)          # shoulders: the arms hang from them, no gap to the chest
    asw = 0.0
    ac = A(torso) * 0.92 if not D["shorts"] or name == "Teretana Brat" else A(torso) * 0.92
    if frame == 3 or D["arms_up"]:
        add(0.0, 1.0 + Y, -0.36 - D["wide"] / 2, 0.14, 0.7, 0.12, sk)
        add(0.0, 1.0 + Y, 0.36 + D["wide"] / 2, 0.14, 0.7, 0.12, sk)
    elif sit or rider in ("kick", "escooter"):
        grip = {"road": (0.5, 0.88), "old": (0.5, 1.0), "moped": (0.55, 1.0), "courier": (0.55, 1.0), "cart": (0.75, 0.75),
                "kick": (0.4, 0.92), "escooter": (0.5, 1.15)}[rider]
        for s in (-1, 1):                                    # both hands on the handlebar (the reins), the elbows bent to reach it
            a, bend = _reach(bx, 1.36 + Y, *grip, 0.34, 0.34)
            _arm(parts, add, bx, 1.36 + Y, s * 0.34, a, bend, ac, sk)
    else:
        z = 0.34 + D["wide"] / 2
        for zz_, sg in ((-z, -1), (z, 1)):
            if strike == 4:                                  # (punching: both arms are drawn by _strike)
                continue
            hb = [(0.02, yy - 0.74 + 0.64 if yy else 0.0, sg * (z + 0.08 + zz), sx, sy, sz, col)   # props carried in that hand
                  for (sx, sy, sz, col, yy, zz) in (held if sg > 0 else held_l)]
            if D["grip"]:                                    # both hands on a push bar in front
                a, bend = _reach(0.0, 1.38, *D["grip"], 0.34, 0.34)
            else:
                a = sg * th * (0.5 if hb else 0.9)
                bend = 0.15 if hb else _elbow(a, run)
            _arm(parts, add, 0.0, 1.38, zz_, a, bend, ac, sk, held=hb)
    for (x, y, z, sx, sy, sz, col) in extra:
        if frame == 2 and y < 0.3:
            continue
        add(bx + x, y + Y + (0.0 if y < 0.3 else 0.0), z, sx, sy, sz, col)
    hx = 0.02 + D["head_fwd"]
    add(hx + bx, 1.42 + Y, 0, 0.26, 0.26, 0.24, sk)
    if hat:
        k, col = hat
        if k == "cap":
            add(hx + bx, 1.62 + Y, 0, 0.3, 0.08, 0.3, col); add(hx + 0.14 + bx, 1.6 + Y, 0, 0.14, 0.03, 0.26, col)
        elif k == "tall":
            add(hx + bx, 1.62 + Y, 0, 0.3, 0.26, 0.3, col)
        elif k in ("beanie", "hood", "scarf", "bun", "helmet", "band"):
            add(hx + bx, 1.6 + Y, 0, 0.31, 0.14, 0.3, col)
            if k == "bun":
                add(hx - 0.14 + bx, 1.64 + Y, 0, 0.12, 0.12, 0.12, col)
            if k == "helmet":
                add(hx - 0.1 + bx, 1.56 + Y, 0, 0.14, 0.1, 0.3, col)
        elif k == "flat":
            add(hx + bx, 1.62 + Y, 0, 0.32, 0.07, 0.32, col)
        elif k == "brim":
            add(hx + bx, 1.62 + Y, 0, 0.5, 0.05, 0.5, col); add(hx + bx, 1.65 + Y, 0, 0.28, 0.1, 0.28, col)
        elif k == "long":
            add(hx - 0.03 + bx, 1.5 + Y, 0, 0.27, 0.12, 0.26, col); add(hx - 0.12 + bx, 1.0 + Y, 0, 0.1, 0.55, 0.28, col)
    else:
        add(hx - 0.03 + bx, 1.54 + Y, 0, 0.27, 0.15, 0.26, hair)
    if strike:
        _strike(add, strike, sk, D["legs"], D["shoe"], ac)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    if not rider:
        _lean(pos, lean)
        if ph is not None:
            pos[:, 1] = np.maximum(pos[:, 1] - _ground(parts, feet), 0.0)   # the standing foot stays planted (the body bobs), nothing carried sinks in
    pos *= scale
    if frame == 2:
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return pos, np.zeros((len(pos), 2), np.float32), rgba


# ------------------------------------------------------------------ the player's own character (from likovi.png)
# per character: skin, hair (colour, style), top, legs, shoes, scale, belly, headwear, extras
_HERO = [
    dict(sk=(232, 178, 150), hair=((60, 44, 34), "bald"), top=(110, 84, 52), legs=(60, 56, 52), shoe=(40, 30, 24), belly=0.12, scale=1.02, extras=("moustache", "gloves")),
    dict(sk=(240, 196, 170), hair=((246, 232, 170), "long"), top=(236, 90, 170), legs=None, shoe=(236, 60, 160), scale=0.95, extras=("heels", "mic", "lips")),
    dict(sk=(214, 160, 126), hair=((34, 28, 24), "short"), top=(28, 28, 30), legs=(48, 56, 84), shoe=(30, 28, 28), belly=0.06, extras=("chain", "stubble")),
    dict(sk=(232, 186, 156), hair=((80, 56, 36), "messy"), top=(170, 40, 50), vest=(48, 64, 104), legs=(52, 76, 130), shoe=(120, 100, 80), extras=("backpack", "partyhat", "burek")),
    dict(sk=(236, 190, 160), hair=((110, 70, 40), "quiff"), top=(186, 188, 192), legs=(60, 62, 66), shoe=(236, 236, 240), extras=("shades", "selfie", "backpack")),
    dict(sk=(222, 170, 136), hair=((120, 84, 50), "long"), top=(200, 200, 204), legs=(28, 28, 32), shoe=(28, 28, 32), scale=0.96, extras=("shades", "phone", "lips", "crop")),
    dict(sk=(230, 176, 146), hair=((70, 50, 36), "scarf"), scarf=(70, 80, 150), top=(140, 150, 200), legs=None, skirt=(110, 80, 120), shoe=(50, 40, 36), belly=0.1, scale=0.92, extras=("pin",)),
    dict(sk=(220, 180, 160), hair=((190, 190, 190), "scarf"), scarf=(120, 110, 140), top=(70, 70, 74), legs=None, skirt=(100, 84, 70), shoe=(40, 36, 34), scale=0.86, stoop=0.08, extras=("glasses", "cane", "bag")),
    dict(sk=(222, 176, 150), hair=((180, 180, 180), "cap"), cap=(90, 90, 94), top=(110, 76, 50), legs=(60, 60, 64), shoe=(36, 30, 26), scale=0.94, stoop=0.05, extras=("paper",)),
    dict(sk=(226, 172, 140), hair=((40, 34, 30), "police"), top=(34, 48, 110), legs=(28, 36, 80), shoe=(20, 20, 22), belly=0.12, scale=1.04, extras=("belt", "phones")),
    dict(sk=(230, 184, 154), hair=((24, 22, 22), "short"), top=(244, 244, 244), legs=(50, 50, 56), shoe=(20, 20, 22), extras=("shades", "coat", "tie", "stetho")),
    dict(sk=(240, 196, 170), hair=((120, 80, 44), "short"), top=(40, 110, 110), legs=(40, 40, 70), shoe=(40, 40, 46), scale=0.68, belly=0.04, extras=("puffer",)),
    dict(sk=(214, 164, 132), hair=((70, 56, 40), "hardhat"), top=(130, 110, 80), legs=(56, 74, 110), shoe=(70, 54, 40), extras=("overalls", "bottle", "stubble")),
    # ---- likovi2: the 11 added characters (own look instead of wrapping onto the first 13)
    dict(sk=(240, 214, 190), hair=((70, 50, 38), "short"), top=(240, 240, 236), legs=(60, 60, 66), shoe=(40, 30, 24), belly=0.18, extras=("pin", "stubble")),
    dict(sk=(226, 176, 146), hair=((230, 230, 230), "cap"), cap=(245, 245, 245), top=(245, 245, 245), legs=(50, 50, 56), shoe=(40, 30, 24), belly=0.2, extras=("bottle", "moustache")),
    dict(sk=(232, 184, 152), hair=((200, 150, 80), "long"), top=(240, 70, 150), legs=(28, 28, 34), shoe=(244, 244, 248), scale=0.96, extras=("phone", "crop", "lips")),
    dict(sk=(214, 166, 134), hair=((30, 26, 24), "short"), top=(240, 240, 240), legs=(40, 40, 46), shoe=(30, 30, 34), scale=1.1, belly=0.1, extras=("stubble", "shades", "chain")),
    dict(sk=(236, 184, 154), hair=((235, 215, 150), "long"), top=(30, 30, 34), legs=(30, 30, 34), shoe=(250, 250, 250), scale=0.97, extras=("lips", "phone", "shades")),
    dict(sk=(240, 196, 170), hair=((90, 60, 36), "messy"), top=(230, 170, 40), legs=(70, 90, 140), shoe=(230, 230, 230), scale=0.72, extras=("backpack",)),
    dict(sk=(232, 186, 156), hair=((40, 30, 24), "quiff"), top=(60, 60, 70), legs=(50, 60, 100), shoe=(240, 240, 240), scale=0.92, extras=("backpack", "phones")),
    dict(sk=(222, 172, 142), hair=((34, 28, 24), "cap"), cap=(70, 90, 50), top=(84, 100, 60), legs=(70, 84, 50), shoe=(30, 26, 22), belly=0.04, extras=("belt",)),
    dict(sk=(226, 172, 140), hair=((60, 44, 34), "short"), top=(200, 30, 40), legs=(30, 30, 34), shoe=(240, 240, 240), extras=("bottle", "stubble")),
    dict(sk=(236, 186, 160), hair=((90, 60, 40), "short"), top=(210, 210, 226), legs=None, skirt=(90, 90, 110), shoe=(60, 50, 50), extras=("glasses", "paper", "lips")),
    dict(sk=(230, 180, 150), hair=((150, 140, 130), "short"), top=(70, 60, 100), legs=None, skirt=(60, 50, 70), shoe=(40, 34, 34), extras=("glasses", "paper")),
]


def _hero(i, frame):
    d = _HERO[i % len(_HERO)]
    A = lambda c: np.array(c, np.float32)
    strike = frame if frame in (4, 5) else 0
    if strike:
        frame = 0
    parts = []

    def add(cx, y, cz, sx, sy, sz, col):
        for name, (v, n) in box_faces(cx, y, cz, sx, sy, sz).items():
            parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1))))

    sk, top, ex = d["sk"], d["top"], d["extras"]
    hc, hs = d["hair"]
    legc = d.get("legs") or sk
    shoe, belly, st = d["shoe"], d.get("belly", 0.0), d.get("stoop", 0.0)
    jump = frame == 16                                   # airborne: arms up, both knees tucked, body upright
    ride = frame == 13                                   # seated on a two-wheeler: feet on the pedals, hands on the bars
    frame, th, lean, ph, run = _phase(3 if jump else (12 if ride else frame))
    if strike:
        th = lean = 0.0
        ph = None
    # legs: thigh swings from the hip, shin from the knee (the swinging leg folds), foot with a sole
    feet = []
    for sg, z in ((1, -0.11), (-1, 0.11)):
        if strike == 5 and z > 0:                       # this leg is the kicking one (drawn by _strike)
            continue
        if jump:
            a, flex = -0.45, 1.0
        elif ride:                                      # knee forward and up, the foot on the pedal (one up, one down)
            t_, b_ = _reach(0.0, 0.84, 0.32 + 0.08 * sg, 0.36 + 0.06 * sg, 0.42, 0.42)
            a, flex = 2 * math.atan2(0.32 + 0.08 * sg, 0.48 - 0.06 * sg) - t_, b_
        else:
            a, flex = th * sg, _knee(sg, th, ph, run)
        _leg(parts, add, z, a, flex, 0.84, legc, legc if d.get("legs") else sk, shoe, feet, sole=(24, 22, 22),
             heel="heels" in ex, w=0.17)
    if d.get("skirt") or d.get("legs") is None:
        add(0.0, 0.5, 0, 0.36, 0.34, 0.44, d.get("skirt") or top)                 # skirt / dress
    # body: hips, belly, chest, shoulders, neck
    add(0.0, 0.7, 0, 0.26, 0.24, 0.44, legc if d.get("legs") else top)
    add(0.02 + belly * 0.5, 0.86, 0, 0.26 + belly, 0.3, 0.46 + belly * 0.6, top)
    add(-st, 1.1, 0, 0.27, 0.3, 0.5, top)
    add(-st, 1.34, 0, 0.24, 0.07, 0.56, top)
    add(-st + 0.02, 1.38, 0, 0.12, 0.08, 0.12, sk)
    if "crop" in ex:
        add(0.02 + belly * 0.5, 0.86, 0, 0.27, 0.12, 0.47, sk)
    if "belt" in ex:
        add(0.0, 0.86, 0, 0.3, 0.07, 0.48, (24, 24, 26))
        add(0.0, 0.84, 0.24, 0.14, 0.16, 0.06, (20, 20, 22))
    if "vest" in d:
        add(-st, 0.88, 0, 0.29, 0.5, 0.36, d["vest"])
    if "coat" in ex:
        add(0.0, 0.4, 0, 0.29, 0.98, 0.5, (246, 246, 246))
    if "overalls" in ex:
        add(0.0, 0.8, 0, 0.29, 0.5, 0.44, legc)
        for z in (-0.13, 0.13):
            add(0.14, 1.1, z, 0.02, 0.3, 0.05, legc)
    if "puffer" in ex:
        for y in (0.86, 1.02, 1.18):
            add(0.0, y, 0, 0.3, 0.09, 0.52, tuple(A(top) * 1.15))
    if "tie" in ex:
        add(0.15, 0.92, 0, 0.02, 0.42, 0.1, (20, 20, 22))
    if "chain" in ex:
        add(0.15, 1.24, 0, 0.02, 0.04, 0.22, (240, 200, 60))
    if "stetho" in ex:
        add(0.15, 1.1, 0, 0.02, 0.26, 0.03, (30, 30, 34))
    if "backpack" in ex:
        add(-0.24, 0.9, 0, 0.16, 0.44, 0.36, (70, 60, 50) if i == 3 else (30, 30, 34))
    # arms: upper, forearm, hand (props gripped in it move with the forearm); frame 3 = arms up
    arm_c = A(top) * 0.92 if "coat" not in ex else A((240, 240, 240))
    hand = (24, 24, 26) if "gloves" in ex else sk
    fore = sk if ("crop" in ex or i == 1) else arm_c
    R, props = -st, {1: [], -1: []}
    if frame not in (2, 3) and not ride:
        if "mic" in ex:
            props[1] += [(R + 0.12, 0.8, 0.34, 0.05, 0.22, 0.05, (30, 30, 34)), (R + 0.14, 1.0, 0.34, 0.08, 0.08, 0.08, (160, 160, 166))]
        if "selfie" in ex:
            props[1] += [(R + 0.3, 0.7, 0.36, 0.6, 0.03, 0.03, (30, 30, 34)), (R + 0.6, 0.7, 0.36, 0.04, 0.14, 0.08, (20, 20, 22))]
        if "phone" in ex or "phones" in ex:
            props[1] += [(R + 0.12, 0.7, 0.34, 0.02, 0.16, 0.09, (230, 200, 200) if i == 5 else (30, 30, 34))]
        if "burek" in ex:
            props[1] += [(R + 0.12, 0.66, 0.34, 0.16, 0.06, 0.16, (220, 180, 110))]
        if "pin" in ex:
            props[1] += [(R + 0.1, 0.66, 0.34, 0.08, 0.08, 0.5, (190, 140, 80))]
        if "cane" in ex:
            props[1] += [(R + 0.12, 0.0, 0.34, 0.04, 0.66, 0.04, (120, 80, 50))]
        if "bag" in ex:
            props[-1] += [(R, 0.4, -0.38, 0.22, 0.24, 0.06, (240, 240, 240)), (R, 0.5, -0.385, 0.08, 0.08, 0.065, (40, 170, 70))]
        if "paper" in ex:
            props[-1] += [(R + 0.06, 0.7, -0.4, 0.22, 0.3, 0.03, (226, 222, 210))]
        if "bottle" in ex:
            props[-1] += [(R + 0.04, 0.6, -0.38, 0.06, 0.24, 0.06, (40, 110, 50))]
    for sg, z in ((-1, -0.34), (1, 0.34)):
        if strike == 4 or ride:                         # punching: both arms are drawn by _strike; riding: added below
            continue
        if frame == 3:
            add(0.0, 1.32, z, 0.13, 0.5, 0.12, arm_c)
            add(0.0, 1.8, z, 0.12, 0.12, 0.11, hand)
        else:
            a = sg * th * (0.45 if props[sg] else 0.9)  # an arm holding a prop swings less, the prop with it
            bend = (0.2 + 0.4 * abs(a)) if props[sg] else _elbow(a, run)
            _arm(parts, add, -st, 1.36, z, a, bend, arm_c, hand, u=0.36, f=0.28, fore=fore, held=props[sg])
    # head: skull, nose, ears, eyes, brows, mouth
    hx, hy = 0.02 - st * 1.6, 1.46
    add(hx, hy, 0, 0.28, 0.3, 0.27, sk)
    add(hx + 0.16, hy + 0.08, 0, 0.08, 0.08, 0.07, tuple(A(sk) * 0.92))               # big caricature nose
    for z in (-0.145, 0.145):
        add(hx - 0.01, hy + 0.1, z, 0.06, 0.09, 0.03, tuple(A(sk) * 0.9))             # ears
        add(hx + 0.141, hy + 0.17, z * 0.5, 0.01, 0.04, 0.05, (250, 250, 250))
        add(hx + 0.145, hy + 0.17, z * 0.5, 0.01, 0.03, 0.025, (30, 26, 24))          # eyes
        add(hx + 0.142, hy + 0.22, z * 0.5, 0.02, 0.02, 0.07, tuple(A(hc) * 0.7))     # brows
    add(hx + 0.142, hy + 0.04, 0, 0.01, 0.025, 0.1, (200, 60, 70) if "lips" in ex else (130, 70, 60))
    if "lips" in ex:
        add(hx + 0.145, hy + 0.035, 0, 0.02, 0.04, 0.12, (220, 60, 90))
    if "moustache" in ex:
        add(hx + 0.15, hy + 0.06, 0, 0.04, 0.05, 0.2, (40, 30, 24))
    if "stubble" in ex:
        add(hx + 0.12, hy - 0.005, 0, 0.05, 0.06, 0.24, tuple(A(sk) * 0.7))
    if "shades" in ex:
        add(hx + 0.15, hy + 0.15, 0, 0.02, 0.06, 0.24, (16, 16, 18))
    if "glasses" in ex:
        add(hx + 0.15, hy + 0.15, 0, 0.01, 0.06, 0.22, (110, 80, 60))
    # hair / headwear
    if hs == "bald":
        for z in (-0.13, 0.13):
            add(hx - 0.06, hy + 0.12, z, 0.14, 0.1, 0.03, hc)
    elif hs in ("short", "messy", "quiff"):
        add(hx - 0.03, hy + 0.24, 0, 0.29, 0.08, 0.28, hc)
        add(hx - 0.12, hy + 0.08, 0, 0.06, 0.2, 0.28, hc)
        if hs == "quiff":
            add(hx + 0.08, hy + 0.3, 0, 0.12, 0.08, 0.2, hc)
        if hs == "messy":
            add(hx + 0.0, hy + 0.3, 0.06, 0.1, 0.05, 0.1, hc)
    elif hs == "long":
        add(hx - 0.03, hy + 0.24, 0, 0.3, 0.09, 0.3, hc)
        add(hx - 0.12, hy - 0.36, 0, 0.08, 0.62, 0.32, hc)
        for z in (-0.15, 0.15):
            add(hx - 0.02, hy - 0.2, z, 0.18, 0.44, 0.03, hc)
    elif hs == "scarf":
        sc = d.get("scarf", (120, 100, 140))
        add(hx - 0.02, hy + 0.12, 0, 0.3, 0.2, 0.31, sc)
        add(hx - 0.12, hy - 0.1, 0, 0.08, 0.3, 0.2, sc)
    elif hs == "cap":
        add(hx - 0.02, hy + 0.25, 0, 0.3, 0.08, 0.3, d.get("cap", (90, 90, 94)))
        add(hx + 0.14, hy + 0.25, 0, 0.1, 0.03, 0.26, d.get("cap", (90, 90, 94)))
    elif hs == "police":
        add(hx - 0.02, hy + 0.26, 0, 0.32, 0.1, 0.32, (24, 32, 80))
        add(hx + 0.16, hy + 0.26, 0, 0.1, 0.03, 0.28, (16, 16, 18))
        add(hx + 0.15, hy + 0.3, 0, 0.02, 0.05, 0.06, (230, 200, 60))
        if "phones" in ex:
            for z in (-0.15, 0.15):
                add(hx, hy + 0.08, z, 0.1, 0.12, 0.04, (20, 20, 22))
    elif hs == "hardhat":
        add(hx - 0.02, hy + 0.24, 0, 0.36, 0.12, 0.36, (240, 200, 30))
        add(hx + 0.0, hy + 0.36, 0, 0.2, 0.04, 0.26, (240, 200, 30))
    if "partyhat" in ex:
        add(hx - 0.02, hy + 0.32, 0, 0.12, 0.1, 0.12, (220, 50, 60))
        add(hx - 0.02, hy + 0.42, 0, 0.06, 0.1, 0.06, (240, 220, 60))
    if strike:
        _strike(add, strike, A(sk), legc, shoe, arm_c)
    if ride:                                            # lean the seated body over the bars, then reach both hands to them
        rl_ = 0.45
        for k, (v, c) in enumerate(parts):
            v = np.array(v, np.float32)
            v[:, 0] += np.maximum(v[:, 1] - 0.8, 0.0) * rl_
            parts[k] = (v, c)
        sx_ = -st + rl_ * 0.56
        for z in (-0.3, 0.3):
            a, bend = _reach(sx_, 1.36, 0.8, 0.95, 0.36, 0.32)
            _arm(parts, add, sx_, 1.36, z, a, bend, arm_c, hand, u=0.36, f=0.28, fore=fore)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    _lean(pos, lean)
    if ph is not None:
        pos[:, 1] = np.maximum(pos[:, 1] - _ground(parts, feet), 0.0)   # the standing foot stays planted (the body bobs), nothing carried sinks in
    pos *= d.get("scale", 1.0)
    if frame == 2:
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return pos, np.zeros((len(pos), 2), np.float32), rgba


def ped_arrays(arch, tone, frame, skin=0):
    """arch = archetype (see vehicles.PED_NAMES), tone 0..2 = colour variant, frame 0/1 walk, 2 lying, 3 arms up, 4 punch, 5 kick."""
    if frame >= 40:                                    # 40..47: crawling on all fours, face down, the walk cycle drives the limbs
        pos, uv, rgba = ped_arrays(arch, tone, frame - 20, skin)
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos = pos.copy()
        c = np.clip(x, -0.15, 0.3)                     # the body's own depth: front (chest) down, back up
        hx = c + (x - c) * np.where(x < c, 0.12, 0.35)
        pos[:, 0] = y * 0.55 - 0.1 + (x - c) * 0.7     # on all fours: head forward, body shortened; a limb swung forward
        pos[:, 1] = (0.3 - hx) * 0.8 + 0.22 + np.abs(np.sin(math.pi * (frame % 10) / 4)) * 0.03   # reaches along the body, not up
        return pos, uv, rgba
    if arch >= 100:
        return _hero(arch - 100, frame)                # (13 = seated on a two-wheeler)
    if arch >= 10:
        return _ped_special(arch, tone, frame, skin)
    A = lambda c: np.array(c, np.float32)
    strike = frame if frame in (4, 5) else 0
    if strike:
        frame = 0
    sk = A(SKIN[skin % 4])
    hair = A(HAIR[(skin + tone) % 4])
    parts = []

    def add(cx, y, cz, sx, sy, sz, col):
        for name, (v, n) in box_faces(cx, y, cz, sx, sy, sz).items():
            parts.append((v, np.tile(A(col) * _shade(A(n)), (len(v), 1))))

    jeans, dark = (52, 66, 104), (34, 36, 44)
    scale, legc, torso, arm, shoe = 1.0, jeans, (200, 60, 60), None, (30, 28, 28)
    pal = [[(200, 60, 60), (60, 90, 190), (70, 150, 90)], [(100, 60, 90), (70, 84, 70), (120, 100, 60)],
           [(40, 44, 60), (60, 60, 66), (34, 50, 70)], [(80, 90, 120), (150, 70, 50), (60, 110, 100)],
           [(200, 30, 30), (200, 30, 30), (220, 220, 220)], [(240, 200, 40), (60, 160, 220), (230, 100, 140)],
           [(240, 120, 20), (240, 120, 20), (230, 200, 30)], [(220, 90, 140), (90, 150, 220), (240, 220, 100)],
           [(236, 236, 232), (236, 236, 232), (236, 236, 232)], [(60, 130, 60)] * 3]
    torso = pal[arch][tone % 3]
    if arch == 1:
        scale = 0.88
    elif arch == 5:
        scale = 0.64
    elif arch == 7:
        scale = 0.95
    if arch == 2:
        legc = (36, 38, 50)
    elif arch == 6:
        legc = (70, 72, 84)
    elif arch == 3:
        legc = (60, 70, 100) if tone != 1 else (50, 50, 54)
    elif arch == 9:
        legc = (46, 52, 78)
    frame, th, lean, ph, run = _phase(frame)
    if strike:
        th = lean = 0.0
        ph = None
    th *= 0.7 if arch == 1 else 1.0
    skirt = arch in (1, 7)                                   # skirt / dress: bare legs under it
    feet = []
    for sg, z_ in ((1, -0.11), (-1, 0.11)):
        if strike == 5 and sg < 0:                           # (the kicking leg is drawn by _strike)
            continue
        _leg(parts, add, z_, th * sg, _knee(sg, th, ph, run), 0.82, sk if skirt else legc, sk if skirt else legc, shoe, feet,
             w=0.15 if skirt else 0.17)
    if skirt:
        add(0.0, 0.42, 0, 0.38, 0.46, 0.46, torso if arch == 7 else (90, 70, 60))
    else:
        add(0.0, 0.7, 0, 0.27, 0.16, 0.44, legc)             # hips: cover the tops of the thighs as they swing
    add(0, 0.8, 0, 0.26, 0.62, 0.5, torso)                    # torso
    add(0, 1.3, 0, 0.24, 0.1, 0.58, torso)                    # shoulders: the arms hang from them, no gap to the chest
    asw = 0.0
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
        add(0.0, 1.0, -0.36, 0.14, 0.7, 0.12, sk)
        add(0.0, 1.0, 0.36, 0.14, 0.7, 0.12, sk)
    else:
        for z_, sg in ((-0.34, -1), (0.34, 1)):
            if strike == 4:                                   # (punching: both arms are drawn by _strike)
                continue
            held = ()
            if sg > 0 and arch == 2:
                held = ((0.0, 0.42, 0.40, 0.08, 0.22, 0.34, (110, 70, 40)),)                       # briefcase
            if sg > 0 and arch == 1:
                held = ((0.0, 0.4, 0.42, 0.18, 0.26, 0.2, (180, 60, 60)),)                         # shopping bag
            a = sg * th * (0.5 if held else 0.9)              # a loaded hand swings less
            _arm(parts, add, 0.0, 1.38, z_, a, 0.1 if held else _elbow(a, run), arms_c, sk, held=held)
        if arch == 8:
            add(0.16, 0.9, 0, 0.3, 0.05, 0.5, (210, 170, 110))                                     # burek tray
    add(0.02, 1.42, 0, 0.26, 0.26, 0.24, sk)                  # head
    add(0.15, 1.48, 0, 0.02, 0.03, 0.08, (60, 40, 30))        # eyebrows hint
    for z in (-0.06, 0.06):
        add(0.151, 1.53, z, 0.01, 0.03, 0.03, (24, 22, 22))   # eyes
    add(0.16, 1.47, 0, 0.05, 0.06, 0.05, sk * 0.92)          # nose
    add(0.02, 1.38, 0, 0.12, 0.05, 0.12, sk)                 # neck
    if arch not in (1, 7):
        add(0.0, 0.8, 0, 0.27, 0.06, 0.51, (30, 28, 30))      # belt
    if arch == 0 and tone != 2:
        add(0.145, 1.44, 0, 0.03, 0.04, 0.16, hair * 0.8)       # moustache
    if arch == 1:
        add(-0.0, 1.44, 0, 0.30, 0.22, 0.30, (130, 60, 80) if tone != 1 else (60, 80, 120))        # headscarf
    elif arch == 6:
        add(0.0, 1.62, 0, 0.32, 0.12, 0.32, (240, 210, 30))                                          # hard hat
    elif arch == 8:
        add(0.0, 1.62, 0, 0.26, 0.26, 0.26, (248, 248, 246))                                         # chef hat
    elif arch == 4:
        add(0.0, 1.62, 0, 0.30, 0.1, 0.30, (20, 20, 22))                                             # cap
    elif arch == 9:
        add(0.0, 1.62, 0, 0.32, 0.08, 0.30, (40, 90, 40))
    else:
        add(-0.03, 1.54, 0, 0.27, 0.15, 0.26, hair)
        if arch == 7:
            add(-0.1, 1.05, 0, 0.1, 0.55, 0.28, hair)                                                # long hair
    if arch in (3, 5):
        add(-0.2, 0.8, 0, 0.14, 0.5 if arch == 3 else 0.34, 0.34, (40, 70, 160) if tone != 1 else (190, 60, 40))   # backpack
    if strike:
        _strike(add, strike, sk, legc, shoe, arms_c)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    _lean(pos, lean)
    if ph is not None:
        pos[:, 1] = np.maximum(pos[:, 1] - _ground(parts, feet), 0.0)   # the standing foot stays planted (the body bobs), nothing carried sinks in
    pos *= scale
    if frame == 2:                                          # lie on the back: rotate about z
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return pos, np.zeros((len(pos), 2), np.float32), rgba


def ped_scale(arch):
    """Body size of a person model (its stride scales with it)."""
    if arch >= 100:
        return _HERO[(arch - 100) % len(_HERO)].get("scale", 1.0)
    return {1: 0.88, 5: 0.64, 7: 0.95}.get(arch, 1.0)


def ped_model(arch, tone, frame, skin=0):
    return make_model(*ped_arrays(arch, tone, frame, skin))


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
    return _boxes_model([(x + w / 2, y, 0.0, w, h, d, c) for x, y, w, h, c in weaponart.BOXES[kind]])


def dog_model(coat, frame):
    import dogart
    return _boxes_model(dogart.boxes(coat, frame))


def bird_model(art, frame):
    import birdart
    return _boxes_model(birdart.boxes(art, frame))


def wreck_model(kind, seed):
    """What is left of a broken tree / post / prop: a charred stump, a bent pole lying down, a crumpled heap."""
    rg = random.Random(seed)
    if kind == "tree":
        return _boxes_model([(0, 0, 0, 0.5, 0.9, 0.5, (52, 40, 30)), (0.1, 0.9, 0.05, 0.3, 0.4, 0.25, (36, 30, 26)),
                             (1.6, 0.0, 0.5, 2.8, 0.34, 0.34, (66, 50, 36)), (3.6, 0.0, 0.7, 1.2, 0.5, 0.9, (46, 70, 38))])
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
        return make_model(*prism_arrays(0.55, 0.42, 9, (240, 200, 90), (196, 130, 60)))
    if kind == "cash":
        return make_model(*prism_arrays(0.42, 0.14, 6, (120, 200, 110), (60, 140, 70)))
    if kind in weaponart.BOXES:                          # the weapon itself, barrel along +x (spun in the world, held by the avatar)
        return weapon_model(kind)
    if kind == "fuel":                                   # red jerry can
        return make_model(*prism_arrays(0.45, 0.6, 4, (210, 40, 30), (150, 20, 20)))
    return make_model(*prism_arrays(0.32, 0.7, 8, (240, 240, 240), (190, 36, 30)))      # ajvar jar


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
""" + BUMP_FN + """const vec3 WATER = vec3(0.337, 0.573, 0.776);
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
    vec3 nb = bumpN(wp, n0, hb, strg * 1.25);
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
  float sw = step(0.55, lum) * step(lum, 0.8) * grey * step(0.92, abs(nrm.y));   // pale flat concrete = pavement: slabs, tone, grit
  if (sw > 0.0) {
    vec2 sp = wpos / vec2(0.95, 0.62) + vec2(0.0, 0.0);
    vec2 cell = floor(sp);
    float tone = h21(cell + 3.7);
    vec2 f = abs(fract(sp) - 0.5);
    float fw = fwidth(wpos.x) + fwidth(wpos.y);
    float seam = smoothstep(0.455, 0.485, max(f.x, f.y)) * (1.0 - smoothstep(0.05, 0.2, fw));
    float grit = texture(texture1, wpos / 1.7).r - 0.5;
    float stain = smoothstep(0.55, 0.8, texture(texture1, wpos / 23.0).b);
    c *= 1.0 + sw * ((tone - 0.5) * 0.09 + grit * 0.1 - stain * 0.07 - seam * 0.16);
  }
  {
    float fadeb = 1.0 - smoothstep(35.0, 110.0, gl_FragCoord.z / gl_FragCoord.w);
    float sat = max(c.r, max(c.g, c.b)) - min(c.r, min(c.g, c.b));
    float flat_ = step(0.92, abs(nrm.y));
    float hb = texture(texture1, (flat_ > 0.5 ? wpos : vec2(wp.x + wp.z, wp.y)) / 1.3).r + 0.6 * texture(texture2, wpos / 7.0).r * road;   // grain, cracks sunk in
    vec3 nb = bumpN(wp, nrm, hb, road > 0.5 ? 0.15 : (sw > 0.5 ? 0.1 : 0.0));
    float rough = mix(0.62, 0.9, flat_);                                                     // poles, signs, car bodies of the mesh: semi-gloss; ground-level slabs: matt
    rough = mix(rough, 0.95, road + sw);                                                     // asphalt, pavement: matt
    rough = mix(rough, 0.3, (1.0 - road) * (1.0 - sw) * (1.0 - flat_));                  // upright props (signs, billboards, lamp poles): smooth painted metal, no relief
    c = relight(c, nrm, nb, rough, fadeb);
  }
  c = shade(c, sunShadow(wp, nrm));
  finalColor = vec4(c, base.a);
}"""
# facades and roofs: texture emboss towards the fixed sun (window frames, bricks, tiles get relief), fine grit and weathering streaks
BUILD_FS = """#version 330
in vec2 fragTexCoord; in vec4 fragColor; in vec2 wpos; in vec3 wp;
uniform sampler2D texture0; uniform sampler2D texture1; uniform vec4 colDiffuse;
out vec4 finalColor;
""" + BUMP_FN + """float hh(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
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
  {
    // normal map from the facade texture: dark mortar / frames / sills sit low, glazing is smooth and glossy, plaster and brick chalky
    float sat = max(base.r, max(base.g, base.b)) - min(base.r, min(base.g, base.b));
    float glass = (1.0 - smoothstep(0.16, 0.30, l0)) * wall;                              // dark glazing
    float hb = l0 + 0.5 * grit * 0.16;
    vec3 nb = bumpN(wp, nrm, hb, 0.45 * (1.0 - glass));
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
                    _bld = (sh, d[1])
            except Exception as e:  # noqa: BLE001
                print(f"[gfx] building detail off: {e}")
    return _bld or None


def apply_building_detail(model):
    d = building_detail()
    if d is not None and model is not None:
        model.materials[0].shader = d[0]
        model.materials[0].maps[1].texture = d[1]
        if SHADOW_TEX is not None:
            model.materials[0].maps[3].texture = SHADOW_TEX


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
