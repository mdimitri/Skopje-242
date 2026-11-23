"""Posters for the loading screen and the title menu: PNG files in assets/posters/ described by posters.json
([{"file": "...", "text": "...caption/joke..."}, ...]); picked at random, shown with a cross-fade."""
import json
import os
import random
import threading
import time

import pyray as rl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "posters")
TITLE = "title.png"
SPLASH_DIR = os.path.join(ROOT, "assets", "splash")          # each JPEG here joins the slideshow
HERO = "01_bazaar_baba_boza.jpg"                            # README hero image; one of the random splash images
SPLASH_EXT = (".jpg", ".jpeg")
SPLASH_HOLD = 20.0                                          # seconds per image
TEAR = 1.6                                                  # seconds of the torn-poster change
_S = {"files": None, "tex": {}, "i": 0, "t0": None, "old": None, "tear": None, "job": None, "failed": set()}


def _splash_files():
    try:
        fs = sorted(os.path.join(SPLASH_DIR, f) for f in os.listdir(SPLASH_DIR) if f.lower().endswith(SPLASH_EXT))
    except OSError:
        return []
    random.shuffle(fs)                                    # random first image, random order (HERO stays in the pool)
    return fs


def _queue_poster(path):
    job = {"path": path, "done": False, "image": None}

    def decode():
        try:
            from PIL import Image
            with Image.open(path) as photo:
                rgb = photo.convert("RGB")
                job["image"] = (rgb.tobytes(), rgb.width, rgb.height)
        except (OSError, ValueError):
            pass
        finally:
            job["done"] = True

    _S["job"] = job
    threading.Thread(target=decode, daemon=True).start()


def splash():
    """The splash image on screen now (the hero image first); None if there is none."""
    fs = _S["files"]
    return _S["tex"].get(fs[_S["i"]]) if fs else None


def tearing():
    return _S["tear"] is not None


def _cover(t, W, H):
    s = max(W / t.width, H / t.height)
    return s, (W - t.width * s) / 2, (H - t.height * s) / 2


def _tear_strips():
    n = 9
    edges = [0.0] + sorted(random.uniform(0.07, 0.93) for _ in range(n - 1)) + [1.0]
    return [(edges[i], edges[i + 1], random.uniform(0.0, 0.45), random.uniform(-14, 14)) for i in range(n)]


def _tear(t, W, H, k, strips):
    """Draw the old poster with fixed trajectories for the duration of the tear."""
    s, dx, dy = _cover(t, W, H)
    for left, right, start, tilt in strips:
        x0, x1 = left * W, right * W
        f = max(0.0, (k - start) / (1.0 - start))
        if f >= 1.0:
            continue
        drop = (f ** 2) * (H * 1.25)                                 # accelerating fall
        ang = (f ** 1.5) * tilt
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
    """Preload the next poster during the hold and keep uploads out of the tear."""
    if _S["files"] is None:
        _S["files"] = _splash_files()
    fs, textures, failed = _S["files"], _S["tex"], _S["failed"]
    now = time.monotonic()
    if _S["tear"] is not None:
        last, elapsed, strips = _S["tear"]
        elapsed += min(now - last, 1 / 30)           # a delayed frame must not skip a large part of the peel
        if elapsed >= TEAR:
            rl.unload_texture(textures.pop(_S["old"]))
            _S["old"] = _S["tear"] = None
        else:
            _S["tear"] = now, elapsed, strips
    job = _S["job"]
    if job is not None and job["done"] and _S["tear"] is None:
        _S["job"] = None
        path, image = job["path"], job["image"]
        if image is not None:
            pixels, width, height = image
            data = rl.ffi.from_buffer(pixels)
            img = rl.Image(data, width, height, 1, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8)
            tex = rl.load_texture_from_image(img)
            if rl.is_texture_valid(tex):
                rl.set_texture_filter(tex, rl.TEXTURE_FILTER_BILINEAR)
                textures[path] = tex
        if path not in textures:
            failed.add(path)
        now = time.monotonic()
    if len(failed) == len(fs):
        rl.clear_background(rl.Color(24, 16, 30, 255))
        return
    while fs[_S["i"]] in failed:
        _S["i"] = (_S["i"] + 1) % len(fs)
    current = fs[_S["i"]]
    if current not in textures:
        if _S["job"] is None:
            _queue_poster(current)
        rl.clear_background(rl.Color(24, 16, 30, 255))
        return
    if _S["t0"] is None:
        _S["t0"] = now
    if _S["tear"] is None and len(fs) - len(failed) > 1:
        nxt = _S.get("next")
        if nxt is None or nxt == _S["i"] or fs[nxt] in failed:
            nxt = random.choice([k for k in range(len(fs)) if k != _S["i"] and fs[k] not in failed])
            _S["next"] = nxt
        path = fs[nxt]
        if path not in textures and _S["job"] is None:
            _queue_poster(path)
        if path in textures and now - _S["t0"] >= SPLASH_HOLD:
            _S["old"], _S["tear"] = current, (now, 0.0, _tear_strips())
            _S["i"], _S["t0"], _S["next"] = nxt, now, None
            current = path
    draw_fit(textures[current], 0, 0, W, H, 255, cover=True)
    if _S["tear"] is not None:
        _, elapsed, strips = _S["tear"]
        _tear(textures[_S["old"]], W, H, elapsed / TEAR, strips)


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
