"""Text drawing with a Cyrillic-capable font (DejaVu Sans, free licence: assets/fonts/LICENSE_DEJAVU).

raylib's built-in font only has Latin glyphs, so every text call of the game goes through here:
    font.draw_text(text, x, y, size, color)      font.measure_text(text, size)
Call font.load() once after the window exists; before that (or if the file is missing) it falls back to the default font.
"""
from texts import TXT
import os

import pyray as rl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "fonts")
BASE = 40                                   # glyph raster size; drawn scaled (bilinear)
_fonts = {}
_default = True
ERR = []                                    # why a font could not be loaded (the game logs it)


def _codepoints():
    cps = list(range(32, 127)) + list(range(0xA0, 0x180)) + list(range(0x400, 0x500))
    cps += [0x2013, 0x2014, 0x2018, 0x2019, 0x201A, 0x201C, 0x201D, 0x201E, 0x2022, 0x2026, 0x2190, 0x2191, 0x2192, 0x2193,
            0x20AC, 0x2116, 0x25B6, 0x2713, 0x2717, 0x00D7]
    return cps


def load():
    """Load regular and bold (idempotent)."""
    global _default
    if _fonts:
        return True
    cps = _codepoints()
    arr = rl.ffi.new("int[]", cps)
    rl.set_trace_log_level(rl.LOG_ERROR)                       # silence "glyph taller than the font size" notes
    for key, fn in (("r", "DejaVuSans.ttf"), ("b", "DejaVuSans-Bold.ttf")):
        path = os.path.join(DIR, fn)
        if not os.path.exists(path):
            continue
        try:
            f = rl.load_font_ex(path, BASE, rl.ffi.cast("int *", arr), len(cps))
            if rl.is_font_valid(f):
                rl.set_texture_filter(f.texture, rl.TEXTURE_FILTER_BILINEAR)
                _fonts[key] = f
        except Exception as e:  # noqa: BLE001 - fall back to raylib's font
            ERR.append(f"{fn}: {e}")
    rl.set_trace_log_level(rl.LOG_WARNING)
    _default = "r" not in _fonts
    return not _default


def _f(bold):
    return _fonts.get("b" if bold else "r") or _fonts.get("r")


def draw_text(text, x, y, size, color, bold=False):
    f = _f(bold)
    if f is None:
        rl.draw_text(text, int(x), int(y), int(size), color)
    else:
        rl.draw_text_ex(f, text, rl.Vector2(float(x), float(y)), float(size), size / 18.0, color)


def measure_text(text, size, bold=False):
    f = _f(bold)
    if f is None:
        return rl.measure_text(text, int(size))
    return int(rl.measure_text_ex(f, text, float(size), size / 18.0).x)


def fit(text, size, width, bold=False):
    """Shorten `text` with an ellipsis so it is at most `width` pixels wide."""
    if measure_text(text, size, bold) <= width:
        return text
    while len(text) > 1 and measure_text(text + "…", size, bold) > width:
        text = text[:-1]
    return text + "…"


def wrap(text, size, width, bold=False):
    """Greedy word wrap -> list of lines."""
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if measure_text(t, size, bold) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ---------------------------------------------------------------------------- clickable buttons (menu / exit)
def button(label, x, y, w, h, size=18):
    """Draw a button; True on the frame it is clicked."""
    m = rl.get_mouse_position()
    on = x <= m.x < x + w and y <= m.y < y + h
    rl.draw_rectangle(int(x), int(y), int(w), int(h), rl.Color(60, 40, 40, 235) if on else rl.Color(20, 22, 30, 215))
    rl.draw_rectangle_lines(int(x), int(y), int(w), int(h), rl.Color(255, 205, 90, 255) if on else rl.Color(120, 120, 130, 255))
    draw_text(label, int(x + (w - measure_text(label, size, True)) / 2), int(y + (h - size) / 2 - 1), size, rl.WHITE, bold=True)
    return on and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)


def confirm_quit(in_frame=False):
    """Modal "really quit?" card.  -> True when the player confirms.  `in_frame`: the caller is between begin/end_drawing."""
    import time
    if in_frame:
        rl.end_drawing()
    t0 = time.time()
    ans = None
    while ans is None:
        if rl.window_should_close():
            ans = True
            break
        W, H = rl.get_screen_width(), rl.get_screen_height()
        rl.begin_drawing()
        rl.clear_background(rl.Color(12, 14, 20, 255))
        bw, bh = min(520, W - 40), 190
        bx, by = (W - bw) // 2, (H - bh) // 2
        rl.draw_rectangle(bx, by, bw, bh, rl.Color(28, 30, 40, 250))
        rl.draw_rectangle_lines(bx, by, bw, bh, rl.Color(255, 205, 90, 255))
        q = TXT("font.0001")
        draw_text(q, bx + (bw - measure_text(q, 24, True)) // 2, by + 34, 24, rl.WHITE, bold=True)
        hint = TXT("font.0002")
        draw_text(hint, bx + (bw - measure_text(hint, 16)) // 2, by + 76, 16, rl.Color(170, 174, 185, 255))
        stay = button(TXT("font.0003"), bx + 30, by + 116, bw // 2 - 40, 44, 20)
        leave = button(TXT("font.0004"), bx + bw // 2 + 10, by + 116, bw // 2 - 40, 44, 20)
        rl.end_drawing()
        if time.time() - t0 > 0.25:                      # the click that opened the card must not answer it
            if leave or rl.is_key_pressed(rl.KEY_Y) or rl.is_key_pressed(rl.KEY_ENTER):
                ans = True
            elif stay or rl.is_key_pressed(rl.KEY_N) or rl.is_key_pressed(rl.KEY_ESCAPE):
                ans = False
    if in_frame:
        rl.begin_drawing()
    return ans


def exit_button(x=None, y=10):
    """The always-there "× Излез" button: asks first, then closes the game."""
    if x is None:
        x = rl.get_screen_width() - 120
    if button(TXT("font.0005"), x, y, 108, 34) and confirm_quit(True):
        try:
            rl.close_window()
        finally:
            import os
            os._exit(0)
