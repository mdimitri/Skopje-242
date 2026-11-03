"""Posters for the loading screen and the title menu: PNG files in assets/posters/ described by posters.json
([{"file": "...", "text": "...caption/joke..."}, ...]); picked at random, shown with a cross-fade."""
import json
import os
import random
import time

import pyray as rl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "posters")
TITLE = "title.png"
SPLASH = ("Skopje 242_ Rooftop Noir.png", "splash.png")     # loading screen / title menu background, in assets/
_splash = []


def splash():
    """The loading-screen art (assets/Skopje 242_ Rooftop Noir.png), loaded once; None if it is missing."""
    if not _splash:
        _splash.append(None)
        for fn in SPLASH:
            p = os.path.join(ROOT, "assets", fn)
            if os.path.exists(p):
                try:
                    with open(p, "rb") as f:                # from memory: raylib's fopen mangles Cyrillic paths on Windows
                        raw = f.read()
                    img = rl.load_image_from_memory(os.path.splitext(fn)[1].lower(), raw, len(raw))
                    t = rl.load_texture_from_image(img)
                    rl.unload_image(img)
                    rl.gen_texture_mipmaps(t)
                    rl.set_texture_filter(t, rl.TEXTURE_FILTER_TRILINEAR)
                    _splash[0] = t
                    break
                except Exception:  # noqa: BLE001
                    pass
    return _splash[0]


def draw_splash(W, H):
    """Full-window splash art (cover-fit), or a dark background with the title when the image is missing."""
    t = splash()
    if t is not None:
        draw_fit(t, 0, 0, W, H, 255, cover=True)
    else:
        rl.clear_background(rl.Color(24, 16, 30, 255))


class Posters:
    def __init__(self):
        self.items = []
        data = []
        for fn in ("posters.json", "plan.json"):          # drawn ones + the planned AI-generated set (used when the PNG exists)
            try:
                data += json.load(open(os.path.join(DIR, fn), encoding="utf-8"))
            except Exception:  # noqa: BLE001 - no posters is fine, the screens just stay plain
                pass
        seen = set()
        for d in data:
            if d["file"] not in seen and d["file"] != TITLE and os.path.exists(os.path.join(DIR, d["file"])):
                seen.add(d["file"])
                self.items.append(d)
        self.tex = {}
        self.bag = []
        self.cur = None            # (file, text)
        self.prev = None
        self.t_switch = 0.0

    def texture(self, fn):
        t = self.tex.get(fn)
        if t is None:
            try:
                t = rl.load_texture(os.path.join(DIR, fn))
                rl.set_texture_filter(t, rl.TEXTURE_FILTER_BILINEAR)
            except Exception:  # noqa: BLE001
                t = False
            self.tex[fn] = t
        return t or None

    def title(self):
        return self.texture(TITLE) if os.path.exists(os.path.join(DIR, TITLE)) else None

    def next(self):
        """Choose another poster (never the same twice in a row; every poster once before any repeats)."""
        if not self.items:
            return None
        if not self.bag:
            self.bag = self.items[:]
            random.shuffle(self.bag)
            if self.cur and self.bag[-1]["file"] == self.cur[0] and len(self.bag) > 1:
                self.bag.reverse()
        d = self.bag.pop()
        self.prev, self.cur = self.cur, (d["file"], d["text"])
        self.t_switch = time.time()
        return self.cur

    def draw(self, x, y, w, h, fade=0.6):
        """Draw the current poster (fit inside the rectangle, centred), cross-fading from the previous one."""
        if not self.cur:
            return
        k = min(1.0, (time.time() - self.t_switch) / fade)
        for item, a in ((self.prev, 1.0 - k), (self.cur, k)):
            if not item or a <= 0.01:
                continue
            t = self.texture(item[0])
            if t:
                draw_fit(t, x, y, w, h, int(255 * a))
        rl.draw_rectangle_lines(x, y, w, h, rl.Color(90, 92, 98, 255))


def draw_fit(t, x, y, w, h, alpha=255, cover=False):
    s = max(w / t.width, h / t.height) if cover else min(w / t.width, h / t.height)
    dw, dh = t.width * s, t.height * s
    dx, dy = x + (w - dw) / 2, y + (h - dh) / 2
    if cover:
        rl.begin_scissor_mode(int(x), int(y), int(w), int(h))
    rl.draw_texture_pro(t, rl.Rectangle(0, 0, t.width, t.height), rl.Rectangle(dx, dy, dw, dh), rl.Vector2(0, 0), 0.0,
                        rl.Color(255, 255, 255, alpha))
    if cover:
        rl.end_scissor_mode()
