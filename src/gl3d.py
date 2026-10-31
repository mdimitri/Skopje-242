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


def build_textures():
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
    # --- facade B (office ribbon)
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(236, 238, 240, 255))
    rl.draw_rectangle_gradient_v(0, 22, S, 84, rl.Color(40, 78, 96, 255), rl.Color(110, 160, 182, 255))
    for x in (0, 42, 84):
        rl.draw_rectangle(x, 22, 4, 84, rl.Color(214, 218, 222, 255))
    rl.draw_rectangle(0, 18, S, 5, rl.Color(200, 204, 208, 255))
    rl.draw_rectangle(0, 106, S, 4, rl.Color(190, 194, 198, 255))
    rl.draw_rectangle(10, 30, 26, 16, rl.Color(255, 255, 255, 40))
    rl.end_texture_mode()
    tex["B"] = _to_texture(rt)
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
    # --- Skopje socialist prefab block (Аеродром, Карпош): panel joints, loggia, odd closed-in balconies, AC unit
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(214, 210, 202, 255))
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
    rl.end_texture_mode()
    tex["panel"] = _to_texture(rt)
    # --- family house (Влае, Ѓорче, Butel): warm stucco, roller-shutter windows, a bit of bare brick
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(246, 236, 220, 255))
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
    rl.end_texture_mode()
    tex["house"] = _to_texture(rt)
    # --- residential mid-rise "A" gets balconies with railings and laundry, the Skopje classic
    rt = rl.load_render_texture(S, S)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(240, 234, 222, 255))
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
    rl.end_texture_mode()
    tex["A"] = _to_texture(rt)
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
    try:
        import graffiti
        tex["graf"] = graffiti.build_atlas()
    except Exception:  # noqa: BLE001 - no graffiti rather than no game
        pass
    img = rl.gen_image_color(4, 4, rl.WHITE)
    tex["white"] = rl.load_texture_from_image(img)
    rl.unload_image(img)
    return tex


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


def _extras(kind, st, ex, L, W, y0, belt, roof, top_h, cx, cl, cw, body_c, accent, parts, box, quad, cab_ref=None):
    """Body-specific add-ons: cargo boxes, sirens, ladders, luggage, logos. `box`/`quad` are car_arrays' helpers."""
    xb, xf = -L / 2, L / 2
    bar = lambda x, z, c1, c2: (box(x, top_h if st == "truck" else roof, z - 0.3, 0.3, 0.14, 0.55, c1),
                                box(x, top_h if st == "truck" else roof, z + 0.3, 0.3, 0.14, 0.55, c2))
    if st == "truck":                                                      # cargo box behind the cab
        x1 = cx - cl / 2 - 0.12
        cgl, cgx = x1 - xb, (x1 + xb) / 2
        col = tuple(body_c)
        if ex == "garbage":
            col = (40, 130, 70)
        if ex == "mixer":                                                  # rotating drum, built from stepped boxes
            for i, (dx, sh, wd) in enumerate(((0.0, 1.5, 1.1), (0.6, 1.8, 1.7), (1.4, 2.0, 2.0), (2.2, 1.8, 1.7), (2.8, 1.4, 1.2))):
                xx = xb + 0.5 + dx * 0.95
                box(xx, belt, 0, 1.0, sh, W * 0.9 * wd / 2.0 + 0.2, (236, 140, 40) if i % 2 == 0 else (210, 120, 30))
            quad((xb + 0.6, belt + 2.05, -0.5), (3.0, 0, 0), (0, 0, 1.0), (0, 1, 0), (240, 240, 240))
        else:
            from_h = top_h - belt if ex != "fire" else 1.5
            for name, (v, n) in box_faces(cgx, belt, 0, cgl, from_h, W * 0.96, 6, 3, 3).items():
                parts.append((v, np.tile(np.array(col, np.float32) * _shade(np.array(n, np.float32)), (len(v), 1)), True))
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


def _wheel_layout(st, L):
    """(x, radius, width) of every wheel pair, the front axle first."""
    if L > 11:
        return [(L * 0.34, 0.5, 0.3), (-L * 0.28, 0.5, 0.3), (-L * 0.38, 0.5, 0.3)]
    return {"bus": [(L * 0.32, 0.45, 0.26), (-L * 0.30, 0.45, 0.26)],
            "truck": [(L * 0.36, 0.5, 0.34), (-L * 0.22, 0.5, 0.34), (-L * 0.36, 0.5, 0.34)],
            "tractor": [(L * 0.36, 0.45, 0.28), (-L * 0.28, 0.85, 0.5)]}.get(st, [(L * 0.31, 0.34, 0.26), (-L * 0.31, 0.34, 0.26)])


def front_wheel(kind):
    """(axle x, track half-width z, wheel model with its centre at the origin) of a car's front wheels, which the renderer
    turns by the steering angle (car_arrays(steer_wheels=True) leaves them out of the body)."""
    L, W = V.DIMS[kind % V.N][:2]
    wx, wr, wd = _wheel_layout(V.STYLE[kind % V.N], L)[0]
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
        return c * np.clip(0.72 + 0.4 * (v[:, 1:2] - y0) / (belt - y0), 0.6, 1.1)
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
    for s in (-1, 1):
        for k in range(nwin):
            xa = x_lo + k * (wl + gap)
            quad((xa, wy0, s * (cw / 2 + 0.012)), (wl, 0, 0), (0, wy1 - wy0, 0), (0, 0, s), gl((0, 0, s)), 2, 1, True, cab)
    if st != "pickup" or True:
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
    for v, c, d in cab:
        v = v.copy()
        t = np.clip((v[:, 1] - belt) / H, 0, 1.2)
        k = np.where(v[:, 0] > cx, ft, rt)
        v[:, 0] = cx + (v[:, 0] - cx) * (1 - k * t)
        v[:, 2] *= (1 - stp * t)
        parts.append((v, c, d))

    # ---- lower body details
    xf, xb = L / 2, -L / 2
    for s in (-1, 1):                                                       # headlights / taillights
        quad((xf + 0.006, belt - 0.34, s * 0.26 * W if s > 0 else -0.46 * W), (0, 0, 0.20 * W), (0, 0.22, 0), (1, 0, 0), (255, 244, 180))
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
                    quad((dx, y0 + 0.08, zz + 0.004), (1.1, 0, 0), (0, roof - y0 - 0.5, 0), (0, 0, 1), (58, 72, 96), 1, 2)
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

    return _finish_arrays(parts, dents, burnt, belt)


def _finish_arrays(parts, dents, burnt, belt):
    """Join the parts, push the dents in, scorch the paint."""
    pos = np.concatenate([p[0] for p in parts])
    col = np.concatenate([p[1] for p in parts]).astype(np.float32)
    deform = np.concatenate([np.full(len(p[0]), p[2]) for p in parts])
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
    -> (base frame, leg swing angle, forward lean as a shear)."""
    if frame == 12:
        return 0, 0.0, 0.0
    if 20 <= frame < 38:
        run = frame >= 30
        amp = 0.75 if run else 0.5
        return 0, amp * math.cos(2 * math.pi * (frame % 10) / 8), (0.35 if run else 0.08)
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
    return frame, th, lean


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
        add(0.2, 1.1, 0.3, 0.36, 0.13, 0.13, arm)             # right upper arm, horizontal from the shoulder
        add(0.54, 1.1, 0.3, 0.34, 0.12, 0.12, arm)            # forearm
        add(0.72, 1.09, 0.3, 0.14, 0.14, 0.14, sk)            # fist
        add(0.06, 0.82, -0.34, 0.13, 0.36, 0.12, arm)         # left upper arm hangs
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
             belly=0.0, wide=0.0, shorts=False, arms_up=False, head_fwd=0.0, stride=1.0)
    hat = None
    held = []                         # (sx, sy, sz, col, y, z) hand-held boxes swinging with the right arm
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
        extra += [(0.85, 0.28, 0, 0.9, 0.1, 0.55, (230, 230, 236)), (0.85, 0.38, 0, 0.7, 0.4, 0.5, (240, 160, 190)),
                  (1.15, 0.38, 0, 0.1, 0.3, 0.4, (240, 160, 190))]
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
        extra += [(0.9, 1.5, 0.35, 1.9, 0.03, 0.03, (90, 66, 40)), (0.0, 0.0, -0.5, 0.25, 0.3, 0.25, (50, 90, 160))]
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
        D.update(torso=P3((60, 220, 120), (255, 90, 160), (60, 200, 240)), legs=(30, 30, 36), shorts=True, stride=1.6)
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
    frame, th, lean = _phase(frame)
    if strike:
        th = lean = 0.0
    th *= D["stride"]
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
    if sit:
        for s in (-1, 1):
            ph = 0.18 * (1 if (frame == 0) == (s > 0) else -1)
            add(0.3 if rider != "cart" else 0.15, 0.6, s * 0.11, 0.42, 0.15, 0.15, legc)
            add(0.5 + ph, 0.1, s * 0.11, 0.15, 0.55, 0.15, legc)
    elif D["skirt"]:
        for z_, sg in ((-0.09, 1), (0.09, -1)):
            if strike == 5 and sg < 0:
                continue
            i0 = len(parts)
            add(0.0, 0.0, z_, 0.14, 0.45, 0.12, sk)
            _swing(parts, i0, 0.0, 0.45, th * sg)
        add(0.0, 0.3, 0, 0.36, 0.6, 0.48, D["skirt"])
    else:
        lc2 = D["legs"]
        for s in (-1, 1):
            if strike == 5 and s > 0:
                continue
            o = 0.0
            i0 = len(parts)
            if D["shorts"]:
                add(o, 0.0, s * 0.11, 0.2, 0.5, 0.16, sk); add(o, 0.5, s * 0.11, 0.22, 0.32, 0.17, lc2)
            else:
                add(o, 0.0, s * 0.11, 0.2, 0.82, 0.16, lc2)
            add(o + 0.04, 0.0, s * 0.11, 0.26 + (0.1 if rider == "blades" else 0), 0.1, 0.17, D["shoe"])
            _swing(parts, i0, 0.0, 0.82, -s * th)
    # ---------------- torso, arms, head
    wd = 0.5 + D["wide"]
    add(bx, 0.8 + Y, 0, 0.26 + D["belly"], 0.62, wd, torso)
    asw = 0.0
    ac = A(torso) * 0.92 if not D["shorts"] or name == "Teretana Brat" else A(torso) * 0.92
    if frame == 3 or D["arms_up"]:
        add(0.0, 1.0 + Y, -0.36 - D["wide"] / 2, 0.14, 0.7, 0.12, sk)
        add(0.0, 1.0 + Y, 0.36 + D["wide"] / 2, 0.14, 0.7, 0.12, sk)
    elif sit or rider in ("kick", "escooter"):
        for s in (-1, 1):
            add(0.25, 0.95 + Y, s * 0.34, 0.5, 0.12, 0.12, ac)
            add(0.5, 0.95 + Y, s * 0.2, 0.1, 0.1, 0.1, sk)
    else:
        z = 0.34 + D["wide"] / 2
        for zz_, sg in ((-z, -1), (z, 1)):
            i0 = len(parts)
            if strike != 4:
                add(0.0, 0.8, zz_, 0.14, 0.6, 0.12, ac)
                add(0.0, 0.74, zz_, 0.12, 0.1, 0.1, sk)
            if sg > 0:
                for (sx, sy, sz, col, yy, zz) in held:                        # props carried in the right hand swing with the arm
                    add(0.02, yy if yy else 0.1, z + 0.08 + zz, sx, sy, sz, col)
            _swing(parts, i0, 0.0, 1.38, sg * th * 1.1)
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
        add(hx - 0.03 + bx, 1.5 + Y, 0, 0.27, 0.12, 0.26, hair)
    if strike:
        _strike(add, strike, sk, D["legs"], D["shoe"], ac)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    if not rider:
        _lean(pos, lean)
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
    frame, th, lean = _phase(frame)
    if strike:
        th = lean = 0.0
    # legs: thigh swings from the hip, shin from the knee (the knee bends when the leg trails), foot with a sole
    for sg, z in ((1, -0.11), (-1, 0.11)):
        if strike == 5 and z > 0:                       # this leg is the kicking one (drawn by _strike)
            continue
        a = th * sg
        i0 = len(parts)
        add(0.0, 0.42, z, 0.19, 0.42, 0.16, legc)
        _swing(parts, i0, 0.0, 0.84, a)
        i1 = len(parts)
        add(0.0, 0.06, z, 0.17, 0.38, 0.14, legc if d.get("legs") else sk)
        add(0.05, 0.0, z, 0.28, 0.08, 0.17, shoe)
        add(0.05, 0.0, z, 0.29, 0.02, 0.18, (24, 22, 22))
        if "heels" in ex:
            add(-0.06, 0.0, z, 0.04, 0.12, 0.05, shoe)
        _swing(parts, i1, 0.0, 0.84, a)
        flex = 0.9 * max(0.0, -a) + 0.15 * max(0.0, a)
        _swing(parts, i1, 0.4 * math.sin(a), 0.84 - 0.4 * math.cos(a), -flex)
    if d.get("skirt") or d.get("legs") is None:
        add(0.0, 0.5, 0, 0.36, 0.34, 0.44, d.get("skirt") or top)                 # skirt / dress
    # body: hips, belly, chest, shoulders, neck
    add(0.0, 0.78, 0, 0.26, 0.16, 0.44, legc if d.get("legs") else top)
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
    # arms: upper, forearm, hand; frame 3 = arms up
    asw = 0.0
    arm_c = A(top) * 0.92 if "coat" not in ex else A((240, 240, 240))
    hand = (24, 24, 26) if "gloves" in ex else sk
    holds_r = any(k in ex for k in ("mic", "selfie", "phone", "phones", "burek", "pin", "cane"))      # a held prop keeps that arm still
    holds_l = any(k in ex for k in ("bag", "paper", "bottle"))
    a_arm = {1: 0.0, -1: 0.0}
    for sg, z in ((-1, -0.34), (1, 0.34)):
        if strike == 4:                                 # punching: both arms are drawn by _strike
            continue
        if frame == 3:
            add(0.0, 1.32, z, 0.13, 0.5, 0.12, arm_c)
            add(0.0, 1.8, z, 0.12, 0.12, 0.11, hand)
        else:
            a = sg * th * (0.45 if (holds_r if sg > 0 else holds_l) else 1.1)      # an arm holding a prop swings less, the prop with it
            a_arm[sg] = a
            i0 = len(parts)
            add(-st, 1.0, z, 0.14, 0.36, 0.13, arm_c)
            _swing(parts, i0, -st, 1.36, a)
            i1 = len(parts)
            add(-st, 0.74, z, 0.13, 0.3, 0.12, arm_c if "crop" not in ex and i not in (1,) else sk)
            add(-st, 0.62, z, 0.12, 0.12, 0.1, hand)
            _swing(parts, i1, -st, 1.36, a)
            _swing(parts, i1, -st + 0.36 * math.sin(a), 1.36 - 0.36 * math.cos(a), 0.2 + 0.4 * abs(a))     # elbow bend
    if frame not in (2, 3):
        R = asw - st
        j0 = len(parts)
        if "mic" in ex:
            add(R + 0.12, 0.8, 0.34, 0.05, 0.22, 0.05, (30, 30, 34))
            add(R + 0.14, 1.0, 0.34, 0.08, 0.08, 0.08, (160, 160, 166))
        if "selfie" in ex:
            add(R + 0.3, 0.7, 0.36, 0.6, 0.03, 0.03, (30, 30, 34))
            add(R + 0.6, 0.7, 0.36, 0.04, 0.14, 0.08, (20, 20, 22))
        if "phone" in ex or "phones" in ex:
            add(R + 0.12, 0.7, 0.34, 0.02, 0.16, 0.09, (230, 200, 200) if i == 5 else (30, 30, 34))
        if "burek" in ex:
            add(R + 0.12, 0.66, 0.34, 0.16, 0.06, 0.16, (220, 180, 110))
        if "pin" in ex:
            add(R + 0.1, 0.66, 0.34, 0.08, 0.08, 0.5, (190, 140, 80))
        if "cane" in ex:
            add(R + 0.12, 0.0, 0.34, 0.04, 0.66, 0.04, (120, 80, 50))
        _swing(parts, j0, -st, 1.36, a_arm[1])
        j0 = len(parts)
        if "bag" in ex:
            add(-asw - st, 0.4, -0.38, 0.22, 0.24, 0.06, (240, 240, 240))
            add(-asw - st, 0.5, -0.385, 0.08, 0.08, 0.065, (40, 170, 70))
        if "paper" in ex:
            add(-asw - st + 0.06, 0.7, -0.4, 0.22, 0.3, 0.03, (226, 222, 210))
        if "bottle" in ex:
            add(-asw - st + 0.04, 0.6, -0.38, 0.06, 0.24, 0.06, (40, 110, 50))
        _swing(parts, j0, -st, 1.36, a_arm[-1])
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
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    _lean(pos, lean)
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
    if arch >= 100:
        if frame == 13:                                # riding a two-wheeler: knees forward, lowered onto the seat, leaning in
            pos, uv, rgba = _hero(arch - 100, 12)
            y = pos[:, 1].copy()
            low = np.clip((0.84 - y) / 0.84, 0, 1)
            pos[:, 0] += 0.5 * low + 0.12 * np.clip((y - 0.8) / 0.8, 0, 1)
            pos[:, 1] = np.where(y < 0.84, y * 0.55 + 0.34, y - 0.06)
            return pos, uv, rgba
        return _hero(arch - 100, frame)
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
    frame, th, lean = _phase(frame)
    if strike:
        th = lean = 0.0
    th *= 0.7 if arch == 1 else 1.0
    if arch in (1, 7):                                       # skirt / dress instead of legs
        for z_, sg in ((-0.09, 1), (0.09, -1)):
            if strike == 5 and sg < 0:
                continue
            i0 = len(parts)
            add(0.0, 0.0, z_, 0.14, 0.45, 0.12, sk)
            _swing(parts, i0, 0.0, 0.45, th * sg)
        add(0.0, 0.42, 0, 0.34, 0.46, 0.46, torso if arch == 7 else (90, 70, 60))
    else:
        for sg, z_ in ((1, -0.11), (-1, 0.11)):
            if strike == 5 and sg < 0:                       # (the kicking leg is drawn by _strike)
                continue
            i0 = len(parts)
            add(0.0, 0.0, z_, 0.2, 0.82, 0.16, legc)
            add(0.04, 0.0, z_, 0.26, 0.1, 0.17, shoe)
            _swing(parts, i0, 0.0, 0.82, th * sg)
    add(0, 0.8, 0, 0.26, 0.62, 0.5, torso)                    # torso
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
            i0 = len(parts)
            if strike != 4:                                   # (punching: both arms are drawn by _strike)
                add(0.0, 0.8, z_, 0.14, 0.6, 0.12, arms_c)
                add(0.0, 0.74, z_, 0.12, 0.1, 0.1, sk)
            if sg > 0 and arch == 2:
                add(0.0, 0.55, 0.40, 0.08, 0.22, 0.34, (110, 70, 40))                              # briefcase
            if sg > 0 and arch == 1:
                add(0.0, 0.5, 0.42, 0.18, 0.26, 0.2, (180, 60, 60))                                # shopping bag
            _swing(parts, i0, 0.0, 1.38, sg * th * 1.1)
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
        add(-0.03, 1.5, 0, 0.27, 0.12, 0.26, hair)
        if arch == 7:
            add(-0.1, 1.05, 0, 0.1, 0.55, 0.28, hair)                                                # long hair
    if arch in (3, 5):
        add(-0.2, 0.8, 0, 0.14, 0.5 if arch == 3 else 0.34, 0.34, (40, 70, 160) if tone != 1 else (190, 60, 40))   # backpack
    if strike:
        _strike(add, strike, sk, legc, shoe, arms_c)
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    col = np.concatenate([p[1] for p in parts])
    _lean(pos, lean)
    pos *= scale
    if frame == 2:                                          # lie on the back: rotate about z
        x, y = pos[:, 0].copy(), pos[:, 1].copy()
        pos[:, 0] = -y
        pos[:, 1] = x + 0.18
    rgba = np.empty((len(pos), 4), np.uint8)
    rgba[:, :3] = np.clip(col, 0, 255)
    rgba[:, 3] = 255
    return pos, np.zeros((len(pos), 2), np.float32), rgba


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


# ------------------------------------------------------------------ ground detail (cheap: one shader, one 256² texture)
DETAIL_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp;
out vec2 fragTexCoord; out vec4 fragColor; out vec2 wpos; out vec3 wp;
void main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; wpos = vertexPosition.xz; wp = vertexPosition;
             gl_Position = mvp * vec4(vertexPosition, 1.0); }"""
DETAIL_FS = """#version 330
in vec2 fragTexCoord; in vec4 fragColor; in vec2 wpos;
uniform sampler2D texture0; uniform sampler2D texture1; uniform sampler2D texture2; uniform vec4 colDiffuse; uniform float time;
out vec4 finalColor;
const vec3 WATER = vec3(0.337, 0.573, 0.776);
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
  float warp = texture(texture1, wpos / 53.0 + 0.31).b;          // large-scale warp + scale drift: the 3.5 m grain tile never lines up twice
  vec2 uv = wpos / (3.5 + 1.6 * warp) + (texture(texture1, wpos / 19.0).gb - 0.5) * 1.3;
  vec4 d = texture(texture1, uv);
  vec4 d2 = texture(texture1, mat2(0.8, 0.6, -0.6, 0.8) * wpos / 5.9 + 0.17);
  d.g = mix(d.g, d2.g, 0.5); d.a = max(d.a * 0.8, d2.a);
  float e = 1.0 / 256.0;
  float hx = texture(texture1, uv + vec2(e, 0.0)).r - d.r;      // bump: height gradient -> normal, fixed sun
  float hz = texture(texture1, uv + vec2(0.0, e)).r - d.r;
  vec3 n = normalize(vec3(-hx * 7.0, 1.0, -hz * 7.0));
  float lit = clamp(dot(n, normalize(vec3(-0.45, 0.8, -0.4))) / 0.8, 0.6, 1.25);
  float big = texture(texture1, wpos / 41.0).b;                  // large patches of dirt / worn ground
  float ground = 1.0 - smoothstep(0.05, 0.16, distance(base.rgb, GROUND));
  float grass = clamp((base.g - max(base.r, base.b)) * 8.0, 0.0, 1.0);
  float k = max(max(ground, grass), 0.3);                          // roads keep a light asphalt grain
  vec3 c = base.rgb * mix(1.0, lit * (0.88 + 0.24 * d.g), k);
  float big2 = texture(texture1, mat2(0.8, -0.6, 0.6, 0.8) * wpos / 67.3 + 0.5).b;   // incommensurate scales: no visible repeat
  float macro = texture(texture1, mat2(0.6, 0.8, -0.8, 0.6) * wpos / 211.0 + 0.3).b * 0.6 + texture(texture1, wpos / 577.0 + 0.7).b * 0.4;
  c = mix(c, c * vec3(0.93, 0.88, 0.8), ground * smoothstep(0.55, 0.8, big * 0.55 + big2 * 0.45) * 0.8);   // dirt patches
  c *= mix(vec3(1.0), mix(vec3(1.08, 0.97, 0.78), vec3(0.84, 1.04, 0.82), smoothstep(0.3, 0.7, macro)), ground * 0.85);   // dry ochre ... fresh green stretches
  c = mix(c, c * vec3(0.8, 0.95, 0.75), grass * d.a * 0.6);                           // grass blades
  float lum = dot(base.rgb, vec3(0.333));
  float grey = 1.0 - clamp((max(base.r, max(base.g, base.b)) - min(base.r, min(base.g, base.b))) * 9.0, 0.0, 1.0);
  float paved = grey * (1.0 - grass) * (1.0 - ground);                                 // asphalt and concrete: cracks and patches
  vec4 cr = texture(texture2, wpos / 7.0);
  float crack = cr.r * smoothstep(0.45, 0.75, texture(texture1, wpos / 29.0).b + 0.25);   // cracks come in worn zones
  c *= 1.0 - paved * crack * (lum > 0.5 ? 0.35 : 0.55);
  c = mix(c, c * 0.82, paved * cr.g * 0.7);                            // tar patches / potholes
  float road = paved * (1.0 - smoothstep(0.38, 0.52, lum));
  c = wear(c, road, crack);
  float wet = 1.0 - smoothstep(0.04, 0.12, distance(base.rgb, WATER));   // rivers / lakes: moving ripples
  if (wet > 0.0) {
    float r1 = texture(texture1, wpos / 9.0 + vec2(time * 0.031, time * 0.012)).r;
    float r2 = texture(texture1, wpos / 6.0 - vec2(time * 0.019, -time * 0.027)).r;
    float wave = r1 + r2 - 1.0;
    vec3 wc = base.rgb * (1.0 + wave * 0.22) + vec3(0.9, 0.95, 1.0) * smoothstep(0.38, 0.5, wave) * 0.25;
    c = mix(c, wc, wet);
  }
  finalColor = vec4(c, base.a);
}"""
# the road / prop mesh (one material for both): only flat dark-grey surfaces get the road wear, walls and trees stay as baked
SOLID_FS = DETAIL_FS[:DETAIL_FS.index("void main(){")].replace("in vec2 wpos;", "in vec2 wpos; in vec3 wp;", 1) + """void main(){
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
  finalColor = vec4(c, base.a);
}"""
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


def ground_time(t):
    """Animate the water (once per frame)."""
    d = ground_detail()
    if d is not None and d[2] >= 0:
        rl.set_shader_value(d[0], d[2], rl.ffi.new("float *", t % 10000.0), rl.SHADER_UNIFORM_FLOAT)
