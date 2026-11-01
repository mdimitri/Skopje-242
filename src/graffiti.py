"""Wall graffiti in Macedonian Cyrillic, painted once into one atlas texture (4 x 52 cells of 256 x 128).

tools/build_world.py puts alpha-keyed decal quads on walls, roofs and roof slopes (material 6, "graf") that pick cells from
this atlas: one extra texture and a few thousand quads, no per-frame cost.  The phrases are text/09_graffiti.txt
(graffiti.0001 ...); the look of every piece (effect, decoration, colour, tilt) comes from look(i).  Plain painted text,
no background plates.  COLS / ROWS / CELL_W / CELL_H / N_PIECES are mirrored in tools/build_world.py (GRAF_*).
"""
import math
import random

import pyray as rl

import font
from texts import TXT

COLS, ROWS, CELL_W, CELL_H = 4, 52, 256, 128
N_PIECES = 205                       # graffiti.0001 .. graffiti.0205

PALETTE = [(255, 214, 40), (80, 220, 255), (230, 40, 50), (255, 140, 30), (255, 90, 190), (120, 255, 120), (170, 120, 255),
           (255, 255, 255), (255, 235, 120), (60, 230, 150), (255, 70, 70), (90, 200, 255), (25, 25, 28), (255, 160, 60)]
STYLES = ("bubble", "tag", "scrawl", "wobble", "extrude", "neon", "stencil", "spray", "chalk", "outline2")
DECOR = ("none", "none", "none", "underline", "drips", "sparks", "heart", "crown", "star", "arrow", "wave")


def look(i):
    """Deterministic (style, decor, colour, tilt) of piece i."""
    r = random.Random(i * 7919 + 242)
    st = STYLES[i % len(STYLES)]
    col = r.choice(PALETTE)
    if st == "stencil":
        col = (25, 25, 28)
    return st, r.choice(DECOR), col, r.uniform(-8, 8)


def _f(bold=True):
    return font._f(bold)


def _text(s, cx, cy, size, rot, col, bold=True):
    """Centre the text at (cx, cy), rotated by rot degrees."""
    f = _f(bold)
    w = font.measure_text(s, size, bold)
    if f is None:
        rl.draw_text(s, int(cx - w / 2), int(cy - size / 2), int(size), col)
        return
    rl.draw_text_pro(f, s, rl.Vector2(float(cx), float(cy)), rl.Vector2(w / 2.0, size / 2.0), float(rot), float(size), size / 18.0, col)


def _fit(lines, maxw, maxh, cap=64):
    size = cap
    while size > 10 and (max(font.measure_text(s, size, True) for s in lines) > maxw or size * 1.15 * len(lines) > maxh):
        size -= 2
    return size


def _outlined(s, cx, cy, size, rot, col, out=(18, 18, 22), r=3):
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r + 1 and (dx or dy):
                _text(s, cx + dx, cy + dy, size, rot, rl.Color(*out, 255))
    _text(s, cx, cy, size, rot, rl.Color(*col, 255))


def _drips(rng, x0, x1, y, col):
    for _ in range(rng.randrange(2, 5)):
        x = rng.uniform(x0, x1)
        ln = rng.uniform(8, 26)
        rl.draw_line_ex(rl.Vector2(x, y), rl.Vector2(x, y + ln), 2.5, rl.Color(*col, 235))
        rl.draw_circle(int(x), int(y + ln), 2.6, rl.Color(*col, 235))


def _heart(cx, cy, r, col):
    c = rl.Color(*col, 255)
    rl.draw_circle(int(cx - r * 0.5), int(cy - r * 0.25), r * 0.55, c)
    rl.draw_circle(int(cx + r * 0.5), int(cy - r * 0.25), r * 0.55, c)
    rl.draw_triangle(rl.Vector2(cx + r * 1.02, cy - r * 0.05), rl.Vector2(cx - r * 1.02, cy - r * 0.05), rl.Vector2(cx, cy + r * 1.05), c)


def _darker(col, k=0.45):
    return tuple(int(c * k) for c in col)


def _star(cx, cy, r, col):
    c = rl.Color(*col, 255)
    pts = [(cx + math.cos(math.radians(-90 + 36 * k)) * (r if k % 2 == 0 else r * 0.42),
            cy + math.sin(math.radians(-90 + 36 * k)) * (r if k % 2 == 0 else r * 0.42)) for k in range(10)]
    for k in range(10):
        a, b = pts[k], pts[(k + 1) % 10]
        rl.draw_triangle(rl.Vector2(cx, cy), rl.Vector2(*b), rl.Vector2(*a), c)


def _crown(cx, cy, col):
    c = rl.Color(*col, 255)
    pts = [(cx - 28, cy + 10), (cx - 28, cy - 12), (cx - 14, cy), (cx, cy - 16), (cx + 14, cy), (cx + 28, cy - 12), (cx + 28, cy + 10)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), 4, c)
    for px, py in pts[1:6:2]:
        rl.draw_circle(int(px), int(py - 4), 4, c)


def _line(style, s, cx, cy, size, rot, col, rng):
    """One text line in the chosen painting style."""
    dk = _darker(col)
    if style == "bubble":
        _outlined(s, cx, cy, size, rot, col, r=4)
        _text(s, cx - 2, cy - 3, size, rot, rl.Color(255, 255, 255, 90))
    elif style == "tag":
        _text(s, cx + 3, cy + 3, size, rot, rl.Color(10, 10, 12, 200))
        _text(s, cx, cy, size, rot, rl.Color(*col, 255))
    elif style == "scrawl":
        _outlined(s, cx, cy, size, rot, col, r=1)
        for dx in (0, 1):
            _text(s, cx + dx, cy, size, rot, rl.Color(*col, 255), bold=False)
    elif style == "wobble":
        total = font.measure_text(s, size, True)
        x = cx - total / 2
        for ch in s:
            w = font.measure_text(ch, size, True)
            if ch != " ":
                _outlined(ch, x + w / 2, cy + rng.uniform(-6, 6), size, rot + rng.uniform(-14, 14), col, r=2)
            x += w
    elif style == "extrude":
        for k in range(7, 0, -1):
            _text(s, cx + k * 0.9, cy + k * 0.9, size, rot, rl.Color(*dk, 255))
        _outlined(s, cx, cy, size, rot, col, r=1)
    elif style == "neon":
        for r_, a in ((6, 60), (4, 110)):
            for dx in range(-r_, r_ + 1, 2):
                for dy in range(-r_, r_ + 1, 2):
                    if dx * dx + dy * dy <= r_ * r_:
                        _text(s, cx + dx, cy + dy, size, rot, rl.Color(*col, a))
        _text(s, cx, cy, size, rot, rl.Color(255, 255, 255, 255))
    elif style == "stencil":
        _outlined(s, cx, cy, size, rot, (22, 22, 26), out=(245, 245, 240), r=2)
    elif style == "spray":
        for _ in range(14):
            _text(s, cx + rng.uniform(-3, 3), cy + rng.uniform(-3, 3), size, rot, rl.Color(*col, 55))
        _text(s, cx, cy, size, rot, rl.Color(*col, 255))
        for _ in range(26):
            rl.draw_circle(int(cx + rng.uniform(-90, 90)), int(cy + rng.uniform(-size * 0.6, size * 0.7)), rng.uniform(0.8, 1.8), rl.Color(*col, 160))
    elif style == "chalk":
        _outlined(s, cx, cy, size, rot, (245, 245, 238), r=1, out=(40, 40, 44))
        for _ in range(30):
            rl.draw_circle(int(cx + rng.uniform(-100, 100)), int(cy + rng.uniform(-size * 0.5, size * 0.6)), 1, rl.Color(40, 40, 44, 130))
    else:                                                      # outline2
        _outlined(s, cx, cy, size, rot, col, out=(18, 18, 22), r=5)
        _outlined(s, cx, cy, size, rot, col, out=(250, 250, 250), r=3)


def _paint(i, lines, rng):
    """Draw piece i into a CELL_W x CELL_H area with its origin at (0, 0); a 6 px border stays transparent."""
    style, decor, col, rot = look(i)
    W, H = CELL_W, CELL_H
    cx = W / 2
    top = 14
    icon = decor in ("heart", "crown", "star")
    if icon:
        top = 44
    mw, mh = W - 30, H - 14 - top - (16 if decor in ("underline", "drips", "arrow", "wave") else 0)
    n = len(lines)
    size = _fit(lines, mw, mh, 54 if style in ("scrawl", "chalk") else 62)
    cy0 = top + mh / 2
    for k, s in enumerate(lines):
        _line(style, s, cx, cy0 + (k - (n - 1) / 2) * size * 1.12, size, rot, col, rng)
    base = cy0 + n * size * 0.56 + 4
    dc = rl.Color(*col, 255)
    if decor == "underline":
        rl.draw_line_ex(rl.Vector2(cx - mw / 2.4, base + 6), rl.Vector2(cx + mw / 2.4, base - 3 + rot * 0.6), 3.5, dc)
    elif decor == "drips":
        _drips(rng, cx - mw / 2.6, cx + mw / 2.6, base - 4, col)
    elif decor == "sparks":
        for sx, sy in ((cx + mw / 2.2, top + 4), (cx - mw / 2.3, top + 10), (cx + mw / 2.6, H - 26)):
            rl.draw_line_ex(rl.Vector2(sx - 6, sy), rl.Vector2(sx + 6, sy), 2.2, dc)
            rl.draw_line_ex(rl.Vector2(sx, sy - 6), rl.Vector2(sx, sy + 6), 2.2, dc)
    elif decor == "arrow":
        y = min(H - 12, base + 4)
        rl.draw_line_ex(rl.Vector2(cx - 40, y), rl.Vector2(cx + 36, y), 3.5, dc)
        rl.draw_triangle(rl.Vector2(cx + 46, y), rl.Vector2(cx + 30, y - 8), rl.Vector2(cx + 30, y + 8), dc)
    elif decor == "wave":
        y = min(H - 14, base + 4)
        for k in range(10):
            rl.draw_line_ex(rl.Vector2(cx - 60 + k * 12, y + (4 if k % 2 else -4)), rl.Vector2(cx - 48 + k * 12, y + (-4 if k % 2 else 4)), 3, dc)
    elif decor == "heart":
        _heart(cx, 24, 13, (255, 50, 90))
    elif decor == "crown":
        _crown(cx, 24, (255, 200, 40))
    elif decor == "star":
        _star(cx, 24, 14, (255, 220, 60))


def build_atlas():
    """-> the atlas Texture2D (transparent background, trilinear, clamped)."""
    rng = random.Random(242)
    rt = rl.load_render_texture(CELL_W * COLS, CELL_H * ROWS)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(0, 0, 0, 0))
    for i in range(min(N_PIECES, COLS * ROWS)):
        try:
            lines = TXT(f"graffiti.{i + 1:04d}").split("\n")
        except Exception:  # noqa: BLE001 - a missing text just leaves an empty cell
            continue
        rl.rl_push_matrix()
        rl.rl_translatef(float((i % COLS) * CELL_W), float((i // COLS) * CELL_H), 0.0)
        try:
            _paint(i, lines, rng)
        finally:
            rl.rl_pop_matrix()
    rl.end_texture_mode()
    img = rl.load_image_from_texture(rt.texture)
    rl.image_flip_vertical(img)
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.unload_render_texture(rt)
    rl.gen_texture_mipmaps(tex)
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_CLAMP)
    return tex
