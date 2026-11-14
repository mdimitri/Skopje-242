"""Looks of the police stations and army barracks (compounds.py): fences with barbed wire, gates, booths, flags, arch
bunkers, and the МВР / ПОЛИЦИЈА and КАСАРНА / АРМ signs (textures drawn with PIL in the game's own Cyrillic font)."""
import math
import os

import numpy as np
import pyray as rl

import gl3d

FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "DejaVuSans-Bold.ttf")
CELL = 160.0                                   # the static geometry of a compound is cut into cells this big (view culling)
SUN = (0.88, 0.94, 1.0)


class _B:
    """Triangle soup in world space: x east, y up, z = the map's y."""

    def __init__(self):
        self.p, self.c = [], []

    def tri(self, a, b, c, col):
        self.p += [a, b, c]
        n = np.cross(np.subtract(b, a), np.subtract(c, a))
        ln = float(np.linalg.norm(n)) or 1.0
        n = n / ln
        k = max(float(gl3d._shade(n)), float(gl3d._shade(-n)))
        self.c += [tuple(min(255, int(v * k)) for v in col)] * 3

    def quad(self, a, b, c, d, col):
        self.tri(a, b, c, col)
        self.tri(a, c, d, col)

    def box(self, x, y, z, h, L, W, H, col, camo=False):
        """Box centred on (x, z) at base height y, heading h (length L along it, width W, height H)."""
        cu, su = math.cos(h), math.sin(h)

        def P(u, v, t):
            return (x + u * cu - v * su, y + t, z + u * su + v * cu)
        a, b = L / 2, W / 2
        c8 = [P(-a, -b, 0), P(a, -b, 0), P(a, b, 0), P(-a, b, 0), P(-a, -b, H), P(a, -b, H), P(a, b, H), P(-a, b, H)]
        faces = ((4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
        for f in faces:
            cc = col
            if camo:
                q = np.mean([c8[i] for i in f], axis=0)
                j = gl3d._camo_n(q[0] * 0.8, q[1], q[2] * 0.8)
                cc = col if j < 0 else gl3d._CAMO[j]
            self.quad(c8[f[0]], c8[f[1]], c8[f[2]], c8[f[3]], cc)

    def line(self, p0, p1, w, col):
        """A thin wire: two crossed ribbons (seen from the side and from above)."""
        d = np.subtract(p1, p0)
        ln = float(np.linalg.norm(d)) or 1.0
        d = d / ln
        up = np.array((0, 1, 0)) if abs(d[1]) < 0.9 else np.array((1, 0, 0))
        s1 = np.cross(d, up)
        s1 = s1 / (np.linalg.norm(s1) or 1.0) * w / 2
        s2 = np.cross(d, s1)
        s2 = s2 / (np.linalg.norm(s2) or 1.0) * w / 2
        p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
        for s in (s1, s2):
            self.quad(tuple(p0 - s), tuple(p1 - s), tuple(p1 + s), tuple(p0 + s), col)

    def model(self):
        if not self.p:
            return None
        pos = np.asarray(self.p, np.float32)
        rgba = np.empty((len(pos), 4), np.uint8)
        rgba[:, :3] = np.clip(np.asarray(self.c, np.float32), 0, 255)
        rgba[:, 3] = 255
        return gl3d.make_model(pos, np.zeros((len(pos), 2), np.float32), rgba)


def _gy(w, x, y):
    return w.ground_y(x, y)


def _fence(B, w, f, army):
    ax, ay, bx, by, H, barbed = f
    L = math.hypot(bx - ax, by - ay)
    if L < 0.05:
        return
    n = max(1, int(math.ceil(L / 3.0)))
    h = math.atan2(by - ay, bx - ax)
    post = (58, 68, 42) if army else (64, 72, 92)
    wire = (132, 136, 128) if army else (86, 96, 118)
    nx, ny = -math.sin(h), math.cos(h)
    for k in range(n + 1):
        x, y = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
        g = _gy(w, x, y)
        B.box(x, g, y, h, 0.12, 0.12, H + (0.35 if barbed else 0.1), post)
        if barbed:                                                     # outrigger arm with three strands
            B.line((x, g + H + 0.3, y), (x + nx * 0.45, g + H + 0.7, y + ny * 0.45), 0.05, post)
    for k in range(n):
        x0, y0 = ax + (bx - ax) * k / n, ay + (by - ay) * k / n
        x1, y1 = ax + (bx - ax) * (k + 1) / n, ay + (by - ay) * (k + 1) / n
        g0, g1 = _gy(w, x0, y0), _gy(w, x1, y1)
        B.line((x0, g0 + H, y0), (x1, g1 + H, y1), 0.07, post)                 # top rail
        B.line((x0, g0 + 0.15, y0), (x1, g1 + 0.15, y1), 0.05, post)
        if army:                                                       # chain-link: a coarse wire grid
            for j in range(1, 5):
                t = j / 5.0
                B.line((x0, g0 + H * t, y0), (x1, g1 + H * t, y1), 0.025, wire)
            m = 6
            for j in range(m + 1):
                t = j / m
                xx, yy, gg = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, g0 + (g1 - g0) * t
                B.line((xx, gg + 0.15, yy), (xx, gg + H, yy), 0.025, wire)
        else:                                                          # steel bars
            m = max(2, int(math.hypot(x1 - x0, y1 - y0) / 0.28))
            for j in range(1, m):
                t = j / m
                xx, yy, gg = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, g0 + (g1 - g0) * t
                B.line((xx, gg + 0.15, yy), (xx, gg + H, yy), 0.035, wire)
        if barbed:                                                     # concertina coil on top, strands on the arm
            seg = math.hypot(x1 - x0, y1 - y0)
            turns = max(2, int(seg / 0.75))
            pts = []
            for j in range(turns * 4 + 1):
                t = j / (turns * 4)
                a = j * math.pi / 2
                cx, cy, gg = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, g0 + (g1 - g0) * t
                pts.append((cx + nx * 0.28 * math.cos(a), gg + H + 0.35 + 0.28 * math.sin(a), cy + ny * 0.28 * math.cos(a)))
            for p, q in zip(pts, pts[1:]):
                B.line(p, q, 0.022, (176, 178, 182))
            for s in (0.45, 0.58, 0.7):
                B.line((x0 + nx * (s - 0.25) * 1.6, g0 + H + s, y0 + ny * (s - 0.25) * 1.6),
                       (x1 + nx * (s - 0.25) * 1.6, g1 + H + s, y1 + ny * (s - 0.25) * 1.6), 0.02, (150, 152, 156))


def _booth(B, w, x, y, h, army):
    g = _gy(w, x, y)
    if army:
        B.box(x, g, y, h, 2.0, 2.0, 2.5, (78, 92, 52), camo=True)
        B.box(x, g + 2.5, y, h, 2.4, 2.4, 0.18, (52, 62, 36))
        for s in (-1, 1):                                              # sandbag walls round it
            hx, hy = x + math.cos(h + math.pi / 2) * s * 1.55, y + math.sin(h + math.pi / 2) * s * 1.55
            for k in range(3):
                B.box(hx, g + k * 0.3, hy, h + 0.04 * k, 2.6, 0.55, 0.3, (178, 162, 120) if k % 2 else (164, 150, 110))
    else:
        B.box(x, g, y, h, 2.0, 2.0, 2.6, (236, 236, 240))
        B.box(x, g + 1.0, y, h, 2.02, 2.02, 0.9, (40, 52, 64))         # windows all round
        B.box(x, g + 2.0, y, h, 2.04, 2.04, 0.25, (30, 60, 160))        # blue band
        B.box(x, g + 2.6, y, h, 2.4, 2.4, 0.14, (60, 66, 80))


def _gate(B, w, gate, army, sign_h):
    x, y, along, gw, onx, ony = gate
    g = _gy(w, x, y)
    ux, uy = math.cos(along), math.sin(along)
    for s in (-1, 1):
        px, py = x + ux * s * (gw / 2 + 0.3), y + uy * s * (gw / 2 + 0.3)
        if army:
            B.box(px, _gy(w, px, py), py, along, 0.6, 0.6, sign_h + 1.6, (82, 94, 58), camo=True)
        else:
            B.box(px, _gy(w, px, py), py, along, 0.6, 0.6, sign_h + 1.6, (230, 232, 236))
            B.box(px, _gy(w, px, py) + sign_h + 1.2, py, along, 0.64, 0.64, 0.3, (30, 60, 160))
    # sign board between the pillars (the textures are drawn on both faces by the renderer)
    B.box(x, g + sign_h - 0.75, y, along, gw * 0.86, 0.14, 1.5, (40, 44, 40) if army else (24, 40, 110))
    # raised boom barrier: post beside the opening, red / white striped arm pointing up
    bx, by = x - onx * 0.8 - ux * (gw / 2 - 0.2), y - ony * 0.8 - uy * (gw / 2 - 0.2)
    gb = _gy(w, bx, by)
    B.box(bx, gb, by, along, 0.4, 0.4, 1.1, (220, 220, 40) if army else (230, 230, 230))
    for k in range(6):
        y0, y1 = gb + 1.1 + k * 0.7, gb + 1.1 + (k + 1) * 0.7
        B.line((bx + ux * 0.03 * k, y0, by + uy * 0.03 * k), (bx + ux * 0.03 * (k + 1), y1, by + uy * 0.03 * (k + 1)), 0.12,
               (210, 30, 30) if k % 2 == 0 else (240, 240, 240))
    # flag pole with the national flag
    fx, fy = x - onx * 2.5 + ux * (gw / 2 + 4.0), y - ony * 2.5 + uy * (gw / 2 + 4.0)
    gf = _gy(w, fx, fy)
    B.line((fx, gf, fy), (fx, gf + 7.5, fy), 0.1, (200, 200, 204))
    fl = [(fx + ux * 0.05, gf + 7.4, fy + uy * 0.05), (fx + ux * 1.9, gf + 7.4, fy + uy * 1.9),
          (fx + ux * 1.9, gf + 6.4, fy + uy * 1.9), (fx + ux * 0.05, gf + 6.4, fy + uy * 0.05)]
    B.quad(*fl, (206, 26, 30))
    cx, cy = fx + ux * 0.97, fy + uy * 0.97
    B.quad((cx - ux * 0.2, gf + 7.1, cy - uy * 0.2), (cx + ux * 0.2, gf + 7.1, cy + uy * 0.2),
           (cx + ux * 0.2, gf + 6.7, cy + uy * 0.2), (cx - ux * 0.2, gf + 6.7, cy - uy * 0.2), (252, 214, 30))


def build(c, w):
    """[(x0, y0, x1, y1, model)] of a compound's static geometry, cut into CELL-sized pieces."""
    army = c.kind == "army"
    cells = {}

    def B(x, y):
        k = (int(x // CELL), int(y // CELL))
        if k not in cells:
            cells[k] = _B()
        return cells[k]
    for f in c.fence:
        _fence(B((f[0] + f[2]) / 2, (f[1] + f[3]) / 2), w, f, army)
    for x, y, h in c.booths:
        _booth(B(x, y), w, x, y, h, army)
    for g in c.gates:
        _gate(B(g[0], g[1]), w, g, army, 4.4 if army else 4.1)
    for x, y, z, h, wd, ht in c.signs[len(c.gates):]:                 # wall signs: a board on the wall
        b = B(x, y)
        b.box(x - math.cos(h) * 0.02, z - 0.08, y - math.sin(h) * 0.02, h + math.pi / 2, wd + 0.16, 0.1, ht + 0.16, (40, 44, 40) if army else (24, 40, 110))
    out = []
    for (kx, ky), b in cells.items():
        m = b.model()
        if m is not None:
            out.append((kx * CELL - 10, ky * CELL - 10, (kx + 1) * CELL + 10, (ky + 1) * CELL + 10, m))
    return out


def bunker_models():
    """(shell, roof) of the arch shelter in local space (x along the open axis, 14 m long, 6 m span): the roof (net and arch top)
    is drawn apart so it can be left out while the player is inside."""
    shell, roof = _B(), _B()
    L, R, T, k = 14.0, 3.0, 0.35, 14
    for i in range(k):
        a0, a1 = math.pi * i / k, math.pi * (i + 1) / k
        top = 0.25 < a0 < math.pi - 0.45
        b = roof if top else shell
        for r_, col in ((R + T, (150, 148, 140)), (R, (118, 116, 110))):
            p = [(-L / 2, r_ * math.sin(a0), r_ * math.cos(a0)), (L / 2, r_ * math.sin(a0), r_ * math.cos(a0)),
                 (L / 2, r_ * math.sin(a1), r_ * math.cos(a1)), (-L / 2, r_ * math.sin(a1), r_ * math.cos(a1))]
            b.quad(*p, col)
        for xe in (-L / 2, L / 2):                                     # the arch's front and back edges
            b.quad((xe, R * math.sin(a0), R * math.cos(a0)), (xe, (R + T) * math.sin(a0), (R + T) * math.cos(a0)),
                   (xe, (R + T) * math.sin(a1), (R + T) * math.cos(a1)), (xe, R * math.sin(a1), R * math.cos(a1)), (136, 134, 126))
        if top:                                                        # camouflage net draped over the top
            rn = R + T + 0.08
            for j in range(7):
                x0, x1 = -L / 2 - 0.3 + j * (L + 0.6) / 7, -L / 2 - 0.3 + (j + 1) * (L + 0.6) / 7
                q = ((x0 + x1) / 2, rn * math.sin((a0 + a1) / 2), rn * math.cos((a0 + a1) / 2))
                jj = gl3d._camo_n(q[0] * 1.3, q[1] * 2, q[2] * 1.3)
                col = (70, 84, 46) if jj < 0 else gl3d._CAMO[jj]
                roof.quad((x0, rn * math.sin(a0), rn * math.cos(a0)), (x1, rn * math.sin(a0), rn * math.cos(a0)),
                          (x1, rn * math.sin(a1), rn * math.cos(a1)), (x0, rn * math.sin(a1), rn * math.cos(a1)), col)
    for s in (-1, 1):                                                  # concrete footing and sandbag ends
        shell.box(0, -0.4, s * (R + T / 2), 0, L + 0.4, T + 0.4, 0.5, (140, 138, 130))
        for e in (-1, 1):
            for kk in range(3):
                shell.box(e * (L / 2 + 0.5), kk * 0.32, s * (R + 0.9), 0, 0.6, 1.6, 0.32, (178, 162, 120) if kk % 2 else (164, 150, 110))
    return shell.model(), roof.model()


# ---------------------------------------------------------------------------- sign textures
def _pil_font(size):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def _sun(d, cx, cy, r, red=(206, 26, 30), gold=(252, 214, 30)):
    """The Macedonian flag's sun: eight widening rays and a disc."""
    for i in range(8):
        a = i * math.pi / 4
        w_ = 0.22
        d.polygon([(cx + math.cos(a - w_) * r * 0.25, cy + math.sin(a - w_) * r * 0.25), (cx + math.cos(a - w_ * 0.6) * r, cy + math.sin(a - w_ * 0.6) * r),
                   (cx + math.cos(a + w_ * 0.6) * r, cy + math.sin(a + w_ * 0.6) * r), (cx + math.cos(a + w_) * r * 0.25, cy + math.sin(a + w_) * r * 0.25)], fill=gold)
    d.ellipse((cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3), fill=gold, outline=red, width=max(1, int(r * 0.05)))


def _emblem(d, cx, cy, r, army):
    """Round badge: МВР (blue, white star) or АРМ (green, gold ring, the sun on red)."""
    if army:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(214, 176, 60))
        d.ellipse((cx - r * 0.9, cy - r * 0.9, cx + r * 0.9, cy + r * 0.9), fill=(52, 66, 36))
        d.ellipse((cx - r * 0.6, cy - r * 0.62, cx + r * 0.6, cy + r * 0.58), fill=(206, 26, 30))
        _sun(d, cx, cy - r * 0.02, r * 0.55)
        f = _pil_font(int(r * 0.34))
        t = "АРМ"
        tw = d.textlength(t, font=f)
        d.text((cx - tw / 2, cy + r * 0.56), t, font=f, fill=(250, 226, 120))
    else:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(236, 236, 240))
        d.ellipse((cx - r * 0.9, cy - r * 0.9, cx + r * 0.9, cy + r * 0.9), fill=(22, 46, 130))
        pts = []                                                       # gold six-pointed star
        for i in range(12):
            a = -math.pi / 2 + i * math.pi / 6
            rr = r * (0.5 if i % 2 == 0 else 0.25)
            pts.append((cx + math.cos(a) * rr, cy - r * 0.12 + math.sin(a) * rr))
        d.polygon(pts, fill=(240, 196, 50))
        f = _pil_font(int(r * 0.36))
        t = "МВР"
        tw = d.textlength(t, font=f)
        d.text((cx - tw / 2, cy + r * 0.4), t, font=f, fill=(255, 255, 255))


def sign_image(c):
    """1024 x 256 board: emblem on the left, the words on the right."""
    from PIL import Image, ImageDraw
    army = c.kind == "army"
    W, H = 1024, 256
    im = Image.new("RGB", (W, H), (44, 56, 32) if army else (22, 46, 130))
    d = ImageDraw.Draw(im)
    d.rectangle((6, 6, W - 7, H - 7), outline=(214, 176, 60) if army else (240, 240, 244), width=8)
    _emblem(d, 140, 128, 104, army)
    if army:
        nm = (c.name or "").strip()
        low = nm.lower()
        if low.startswith("касарна"):
            nm = nm[len("касарна"):].strip()
        line1, line2 = ("КАСАРНА", nm or "АРМ") if (not c.name or low.startswith("касарна") or not nm) else (nm.upper(), "АРМ")
        if line1 != "КАСАРНА" and "КАСАРНА" not in line1:
            line1, line2 = "КАСАРНА", nm
        col1, col2 = (250, 226, 120), (236, 236, 226)
        sub = "Армија на Република Македонија"
    else:
        line1, line2 = "ПОЛИЦИЈА", "МВР"
        col1, col2 = (255, 255, 255), (236, 236, 240)
        sub = "Министерство за внатрешни работи"
    x0 = 270
    for size in (110, 96, 84, 72, 60):
        f1 = _pil_font(size)
        if d.textlength(line1, font=f1) < W - x0 - 30:
            break
    d.text((x0, 18), line1, font=f1, fill=col1)
    for size in (64, 56, 48, 40, 34, 28):
        f2 = _pil_font(size)
        if d.textlength(line2, font=f2) < W - x0 - 30:
            break
    d.text((x0, 136), line2, font=f2, fill=col2)
    f3 = _pil_font(26)
    d.text((x0, 208), sub, font=f3, fill=col2)
    return im


def emblem_image(army):
    """256 x 256 badge with a transparent corner (painted flat on the ground inside the gate)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    _emblem(d, 128, 128, 124, army)
    return im


def to_texture(im):
    arr = np.asarray(im.convert("RGBA"), np.uint8)
    rgba = np.ascontiguousarray(arr)
    img = rl.Image(rl.ffi.from_buffer(rgba), arr.shape[1], arr.shape[0], 1, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    t = rl.load_texture_from_image(img)
    rl.gen_texture_mipmaps(t)
    rl.set_texture_filter(t, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(t, rl.TEXTURE_WRAP_CLAMP)
    return t, rgba


def board(tex, x, y, z, h, wd, ht, off):
    """A vertical textured quad facing heading h (both faces readable)."""
    nx, ny = math.cos(h), math.sin(h)
    ux, uy = -ny, nx                                                   # right along the board, as seen from the front
    rl.rl_set_texture(tex.id)
    rl.rl_begin(rl.RL_QUADS)
    rl.rl_color4ub(255, 255, 255, 255)
    for s in (1, -1):                                                  # front, then back (mirrored so it reads right)
        bx, by = x + nx * off * s, y + ny * off * s
        k = 1 if s > 0 else -1
        a = (bx - ux * wd / 2 * k, by - uy * wd / 2 * k)
        b = (bx + ux * wd / 2 * k, by + uy * wd / 2 * k)
        rl.rl_tex_coord2f(0.0, 0.0); rl.rl_vertex3f(a[0], z + ht, a[1])
        rl.rl_tex_coord2f(0.0, 1.0); rl.rl_vertex3f(a[0], z, a[1])
        rl.rl_tex_coord2f(1.0, 1.0); rl.rl_vertex3f(b[0], z, b[1])
        rl.rl_tex_coord2f(1.0, 0.0); rl.rl_vertex3f(b[0], z + ht, b[1])
    rl.rl_end()
    rl.rl_set_texture(0)


def flat(tex, x, y, z, size, h):
    """A textured square lying on the ground, its top towards heading h."""
    ux, uy = math.cos(h), math.sin(h)
    vx, vy = -uy, ux
    s = size / 2
    rl.rl_set_texture(tex.id)
    rl.rl_begin(rl.RL_QUADS)
    rl.rl_color4ub(255, 255, 255, 255)
    for (tu, tv), (a, b) in (((0, 0), (1, -1)), ((0, 1), (-1, -1)), ((1, 1), (-1, 1)), ((1, 0), (1, 1))):
        rl.rl_tex_coord2f(tu, tv)
        rl.rl_vertex3f(x + ux * a * s + vx * b * s, z, y + uy * a * s + vy * b * s)
    rl.rl_end()
    rl.rl_set_texture(0)


class Art:
    """Per-renderer cache of the compound models and textures; draw() is called from Renderer._actors."""

    def __init__(self):
        self.cells = {}
        self.tex = {}
        self.bunker = None
        self.keep = []

    def _sign(self, c):
        t = self.tex.get(id(c))
        if t is None:
            t, buf = to_texture(sign_image(c))
            self.keep.append(buf)
            self.tex[id(c)] = t
        return t

    def _emb(self, army):
        t = self.tex.get(("emb", army))
        if t is None:
            t, buf = to_texture(emblem_image(army))
            self.keep.append(buf)
            self.tex[("emb", army)] = t
        return t

    def draw(self, cmp, sim, w, inr, fx, fy):
        """inr(x, y, pad) -> on screen."""
        for c in cmp.list:
            x0, y0, x1, y1 = c.bb
            if not inr((x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2 + 20):
                continue
            pieces = self.cells.get(id(c))
            if pieces is None:
                pieces = self.cells[id(c)] = build(c, w)
            for a, b, c2, d, m in pieces:
                if inr((a + c2) / 2, (b + d) / 2, (c2 - a) / 2 + 10):
                    rl.draw_model(m, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)
            if c.bunkers:
                if self.bunker is None:
                    self.bunker = bunker_models()
                shell, roof = self.bunker
                for bx, by, h in c.bunkers:
                    if not inr(bx, by, 10):
                        continue
                    g = w.ground_y(bx, by)
                    for m, part in ((shell, 0), (roof, 1)):
                        if m is None:
                            continue
                        if part == 1:                                  # the player under the arch: no roof, so you can see in
                            lx, ly = (fx - bx) * math.cos(h) + (fy - by) * math.sin(h), -(fx - bx) * math.sin(h) + (fy - by) * math.cos(h)
                            if abs(lx) < 8.5 and abs(ly) < 4.0:
                                continue
                        rl.draw_model_ex(m, rl.Vector3(bx, g, by), rl.Vector3(0, 1, 0), -math.degrees(h), rl.Vector3(1, 1, 1), rl.WHITE)
            tex = self._sign(c)
            for i, (x, y, z, h, wd, ht) in enumerate(c.signs):
                if inr(x, y, 8):
                    if i < len(c.gates):                               # over the gate, on the board between the pillars
                        gx, gy = c.gates[i][0], c.gates[i][1]
                        board(tex, gx, gy, w.ground_y(gx, gy) + (4.4 if c.kind == "army" else 4.1) - 0.7, h, 5.6, 1.4, 0.09)
                    else:
                        board(tex, x, y, z, h, wd, wd / 4.0, 0.08)
            et = self._emb(c.kind == "army")
            for x, y, size, h in c.flat:
                if inr(x, y, size):
                    flat(et, x, y, w.ground_y(x, y) + 0.09, size, h)
