"""Wall graffiti in Macedonian Cyrillic, painted once into one atlas texture (4 x 12 cells of 256 x 128).

tools/build_world.py puts a few alpha-keyed decal quads on building walls (material 6, "graf") that pick cells from this
atlas: one extra texture and a few thousand quads, no per-frame cost.  The phrases come from docs/Skopje_slang_bible.txt.
COLS / ROWS / CELL_W / CELL_H are mirrored in tools/build_world.py (GRAF_COLS / GRAF_ROWS).
"""
import math
import random

import pyray as rl

import font
from texts import TXT

COLS, ROWS, CELL_W, CELL_H = 4, 12, 256, 128

# (style, lines, colour) - style: bubble | tag | stencil | scrawl | sticker | heart | crown
# (style, colour) per piece; the phrases are text/09_graffiti.txt (graffiti.0001 ...)
STYLES = [
    ('bubble', (255, 214, 40)),
    ('bubble', (80, 220, 255)),
    ('tag', (230, 40, 50)),
    ('crown', (255, 200, 40)),
    ('scrawl', (250, 250, 250)),
    ('stencil', (20, 20, 22)),
    ('bubble', (255, 90, 190)),
    ('scrawl', (255, 235, 120)),
    ('tag', (120, 255, 120)),
    ('bubble', (255, 140, 30)),
    ('stencil', (20, 20, 22)),
    ('sticker', (255, 60, 60)),
    ('scrawl', (255, 255, 255)),
    ('tag', (170, 120, 255)),
    ('stencil', (30, 30, 34)),
    ('scrawl', (255, 190, 90)),
    ('tag', (255, 120, 40)),
    ('bubble', (60, 230, 150)),
    ('bubble', (255, 70, 70)),
    ('scrawl', (240, 240, 240)),
    ('sticker', (60, 140, 255)),
    ('sticker', (255, 190, 40)),
    ('tag', (255, 255, 90)),
    ('bubble', (255, 60, 150)),
    ('scrawl', (255, 120, 200)),
    ('stencil', (25, 25, 28)),
    ('sticker', (110, 220, 110)),
    ('heart', (255, 50, 90)),
    ('bubble', (90, 200, 255)),
    ('tag', (255, 230, 60)),
    ('scrawl', (230, 230, 255)),
    ('heart', (255, 70, 70)),
    ('stencil', (20, 20, 22)),
    ('sticker', (255, 170, 40)),
    ('scrawl', (250, 250, 250)),
    ('stencil', (25, 25, 28)),
    ('bubble', (255, 200, 60)),
    ('scrawl', (255, 235, 120)),
    ('sticker', (200, 60, 200)),
    ('scrawl', (230, 230, 255)),
    ('stencil', (30, 30, 34)),
    ('tag', (255, 150, 50)),
    ('bubble', (120, 230, 120)),
    ('scrawl', (255, 160, 160)),
    ('sticker', (80, 170, 255)),
    ('stencil', (20, 20, 22)),
    ('scrawl', (255, 210, 90)),
    ('tag', (90, 230, 255)),
]


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


def _paint(i, style, lines, col, rng):
    """Draw one piece in a CELL_W x CELL_H area with its origin at (0, 0); the 6 px border stays transparent."""
    W, H = CELL_W, CELL_H
    mw, mh = W - 28, H - 28
    cx, cy = W / 2, H / 2
    n = len(lines)
    rot = rng.uniform(-7, 7)
    if style == "bubble":
        size = _fit(lines, mw, mh - 18)
        for k, s in enumerate(lines):
            y = cy - 8 + (k - (n - 1) / 2) * size * 1.05
            _outlined(s, cx, y, size, rot, col, r=4)
            _text(s, cx - 2, y - 3, size, rot, rl.Color(255, 255, 255, 90))            # glossy highlight
        _drips(rng, cx - mw / 2.6, cx + mw / 2.6, cy - 8 + (n - 1) * size * 0.55 + size * 0.45, col)
    elif style == "tag":
        size = _fit(lines, mw, mh - 14)
        for k, s in enumerate(lines):
            y = cy - 4 + (k - (n - 1) / 2) * size * 1.1
            _text(s, cx + 3, y + 3, size, rot - 3, rl.Color(10, 10, 12, 190))             # drop shadow
            _text(s, cx, y, size, rot - 3, rl.Color(*col, 255))
        y_ = cy + size * 0.55 * n + 4
        rl.draw_line_ex(rl.Vector2(cx - mw / 2.5, y_ + 6), rl.Vector2(cx + mw / 2.5, y_ - 4 + rot), 3.5, rl.Color(*col, 255))   # underline swoosh
        for sx, sy in ((cx + mw / 2.3, cy - mh / 2.6), (cx - mw / 2.4, cy - mh / 3.2)):
            rl.draw_line_ex(rl.Vector2(sx - 6, sy), rl.Vector2(sx + 6, sy), 2.0, rl.Color(*col, 255))
            rl.draw_line_ex(rl.Vector2(sx, sy - 6), rl.Vector2(sx, sy + 6), 2.0, rl.Color(*col, 255))
    elif style == "stencil":
        size = _fit(lines, mw - 20, mh - 34)
        h = size * 1.2 * n + 16
        rl.draw_rectangle(int(cx - mw / 2), int(cy - h / 2), int(mw), int(h), rl.Color(236, 232, 222, 215))
        for k, s in enumerate(lines):
            _text(s, cx, cy + (k - (n - 1) / 2) * size * 1.15, size, 0, rl.Color(*col, 255))
        for bx in (cx - mw / 2, cx + mw / 2 - 6):                                       # spray-paper edge ticks
            for t in range(int(cy - h / 2), int(cy + h / 2), 9):
                rl.draw_rectangle(int(bx), t, 6, 4, rl.Color(30, 30, 34, 200))
    elif style == "scrawl":
        size = _fit([s.strip("~") for s in lines], mw, mh - 10, 44)
        for k, s in enumerate(lines):
            struck = s.startswith("~")
            s = s.strip("~")
            y = cy + (k - (n - 1) / 2) * size * 1.25
            _text(s, cx, y, size, rot, rl.Color(*col, 235), bold=False)
            if struck:
                w = font.measure_text(s, size)
                rl.draw_line_ex(rl.Vector2(cx - w / 2 - 6, y + 2), rl.Vector2(cx + w / 2 + 6, y - 5), 4.0, rl.Color(230, 40, 40, 255))
                rl.draw_line_ex(rl.Vector2(cx - w / 2 - 4, y - 8), rl.Vector2(cx + w / 2 + 4, y + 9), 3.0, rl.Color(230, 40, 40, 255))
    elif style == "sticker":
        size = _fit(lines, mw - 24, mh - 36, 40)
        h = size * 1.2 * n + 18
        r_ = rl.Rectangle(cx - mw / 2 + 4, cy - h / 2, mw - 8, h)
        rl.draw_rectangle_rec(rl.Rectangle(r_.x + 3, r_.y + 3, r_.width, r_.height), rl.Color(0, 0, 0, 110))
        rl.draw_rectangle_rec(r_, rl.Color(*col, 255))
        rl.draw_rectangle_lines_ex(r_, 3, rl.Color(250, 250, 250, 255))
        for k, s in enumerate(lines):
            _text(s, cx, cy + (k - (n - 1) / 2) * size * 1.15, size, 0, rl.Color(255, 255, 255, 255))
    elif style == "heart":
        _heart(cx, cy - 20, 30, col)
        rl.draw_circle(int(cx - 18), int(cy - 34), 6, rl.Color(255, 255, 255, 110))
        size = _fit(lines, mw, 34, 32)
        _outlined(lines[0], cx, cy + 36, size, rot, (250, 250, 250), r=2)
    elif style == "crown":
        c = rl.Color(*col, 255)
        base_y = cy - 6
        pts = [(cx - 44, base_y), (cx - 44, base_y - 30), (cx - 22, base_y - 12), (cx, base_y - 38), (cx + 22, base_y - 12), (cx + 44, base_y - 30), (cx + 44, base_y)]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), 5, c)
        for px, py in pts[1:6:2]:
            rl.draw_circle(int(px), int(py - 5), 5, c)
        size = _fit(lines, mw, 48, 52)
        _outlined(lines[0], cx, cy + 36, size, rot, col, r=3)


def build_atlas():
    """-> the atlas Texture2D (transparent background, trilinear, clamped)."""
    rng = random.Random(242)
    rt = rl.load_render_texture(CELL_W * COLS, CELL_H * ROWS)
    rl.begin_texture_mode(rt)
    rl.clear_background(rl.Color(0, 0, 0, 0))
    for i, (style, col) in enumerate(STYLES[: COLS * ROWS]):
        lines = TXT(f"graffiti.{i + 1:04d}").split("\n")
        rl.rl_push_matrix()
        rl.rl_translatef(float((i % COLS) * CELL_W), float((i // COLS) * CELL_H), 0.0)
        try:
            _paint(i, style, lines, col, rng)
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
