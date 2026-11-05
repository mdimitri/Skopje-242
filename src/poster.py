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
SPLASH_DIR = os.path.join(ROOT, "assets", "splash")       # more splash art: every image here joins the slideshow
SPLASH_EXT = (".png", ".jpg", ".jpeg", ".bmp")
SPLASH_HOLD = 20.0                                          # seconds per image
TEAR = 1.6                                                  # seconds of the torn-poster change
_S = {"files": None, "tex": {}, "i": 0, "t0": 0.0, "old": None, "tear": None}


def _splash_files():
    fs = [os.path.join(ROOT, "assets", fn) for fn in SPLASH if os.path.exists(os.path.join(ROOT, "assets", fn))][:1]
    try:
        fs += sorted(os.path.join(SPLASH_DIR, f) for f in os.listdir(SPLASH_DIR) if f.lower().endswith(SPLASH_EXT))
    except OSError:
        pass
    return fs


def _load(path):
    if path not in _S["tex"]:
        _S["tex"][path] = None
        try:
            with open(path, "rb") as f:                     # from memory: raylib's fopen mangles Cyrillic paths on Windows
                raw = f.read()
            ext = os.path.splitext(path)[1].lower()
            img = rl.load_image_from_memory(".jpg" if ext == ".jpeg" else ext, raw, len(raw))
            if img.width > 0:
                t = rl.load_texture_from_image(img)
                rl.gen_texture_mipmaps(t)
                rl.set_texture_filter(t, rl.TEXTURE_FILTER_TRILINEAR)
                _S["tex"][path] = t
            rl.unload_image(img)
        except Exception:  # noqa: BLE001
            pass
    return _S["tex"][path]


def splash():
    """The splash image on screen now (a random one first); None if there is none."""
    if _S["files"] is None:
        _S["files"] = _splash_files()
        _S["i"] = random.randrange(len(_S["files"])) if _S["files"] else 0
        _S["t0"] = time.time()
    fs = _S["files"]
    return _load(fs[_S["i"]]) if fs else None


def _cover(t, W, H):
    s = max(W / t.width, H / t.height)
    return s, (W - t.width * s) / 2, (H - t.height * s) / 2


def _tear(t, W, H, k, seed):
    """The old poster torn off in vertical strips: each strip starts at its own moment, sags, tilts and falls away."""
    r = random.Random(seed)
    n = 9
    s, dx, dy = _cover(t, W, H)
    edges = [0.0] + sorted(r.uniform(0.07, 0.93) for _ in range(n - 1)) + [1.0]
    for i in range(n):
        x0, x1 = edges[i] * W, edges[i + 1] * W
        start = r.uniform(0.0, 0.45)
        f = max(0.0, (k - start) / (1.0 - start))
        if f >= 1.0:
            continue
        drop = (f ** 2) * (H * 1.25)                                 # accelerating fall
        ang = (f ** 1.5) * r.uniform(-14, 14)
        sw = x1 - x0
        src = rl.Rectangle((x0 - dx) / s, (0 - dy) / s, sw / s, H / s)
        dst = rl.Rectangle(x0 + sw / 2, drop, sw, H)
        if f > 0:                                                    # a shadow line where the strip lifts off
            rl.draw_rectangle(int(x0), 0, int(sw), int(min(H, drop + 6)), rl.Color(0, 0, 0, int(90 * (1 - f))))
        rl.draw_texture_pro(t, src, dst, rl.Vector2(sw / 2, 0), ang, rl.WHITE)
        if f > 0:                                                    # torn white paper edges
            for ex in (x0, x1 - 3):
                rl.draw_rectangle_pro(rl.Rectangle(ex + 1.5, drop, 3, H), rl.Vector2(1.5, 0), ang, rl.Color(235, 228, 215, 200))


def draw_splash(W, H):
    """Full-window splash art (cover-fit), changing every SPLASH_HOLD s with a torn-poster effect; a dark background
    when there is no image."""
    cur = splash()
    if cur is None:
        rl.clear_background(rl.Color(24, 16, 30, 255))
        return
    now = time.time()
    fs = _S["files"]
    if len(fs) > 1 and now - _S["t0"] > SPLASH_HOLD:
        nxt = (_S["i"] + 1) % len(fs)
        if _load(fs[nxt]) is not None:
            _S["old"], _S["tear"] = cur, (now, random.randrange(1 << 30))
            _S["i"], _S["t0"] = nxt, now
            cur = _load(fs[nxt])
        else:
            _S["t0"] = now
    draw_fit(cur, 0, 0, W, H, 255, cover=True)
    if _S["tear"]:
        k = (now - _S["tear"][0]) / TEAR
        if k >= 1.0:
            _S["old"] = _S["tear"] = None
        else:
            _tear(_S["old"], W, H, k, _S["tear"][1])


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
