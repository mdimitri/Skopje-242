"""Multiplayer: a small animated face window per player (left edge of the screen), drawn from the real character head mesh.
facerig.Head renders the hero's head (deformed on the CPU: jaw, smile, eyelids, pupils, brows, tilt/squash) into a tiny render texture at
~24 Hz (slower when it costs too much); every frame is then one textured quad plus a few 2D props.  If the mesh cannot be built the
hero's caricature (assets/likovi) is cropped once and used instead (cheap fallback).
Moods: idle (looks around, blinks, random quirks), speaking (jaw follows the loudness, head turns towards the speaker), driving (speed,
crazy swerving, hard braking, crash), fighting (angry, punch jerks, being hit), low health, dead, cash."""
import math
import random
import time

import pyray as rl
import font
import characters

SIZES = (64, 88, 116)
SIZE_NAMES = ["Мали", "Средни", "Големи"]
RENDER_HZ, SLOW_HZ, SLOW_MS = 24.0, 12.0, 1.4
TEX = 128
MARGIN = 1.25
# ---- fallback sprites (hero caricature crop): hero id -> (face centre x, y, width as fractions of the picture, mouth line inside the face)
FACE = {
    "administratorka": (0.45, 0.32, 0.32, 0.64), "baba": (0.65, 0.29, 0.30, 0.68), "bilder": (0.53, 0.17, 0.30, 0.64),
    "boza": (0.50, 0.21, 0.34, 0.62), "burek": (0.55, 0.17, 0.34, 0.64), "dedo": (0.55, 0.20, 0.32, 0.64),
    "doktor": (0.50, 0.21, 0.32, 0.64), "fitka": (0.50, 0.24, 0.30, 0.64), "influenser": (0.53, 0.19, 0.30, 0.64),
    "influenserka": (0.50, 0.30, 0.38, 0.64), "kumplung": (0.55, 0.17, 0.40, 0.64), "maca": (0.52, 0.20, 0.30, 0.64),
    "mali": (0.50, 0.25, 0.40, 0.64), "mile": (0.55, 0.25, 0.42, 0.64), "nastavnica": (0.45, 0.22, 0.30, 0.64),
    "navivac": (0.50, 0.22, 0.30, 0.64), "palavko": (0.45, 0.22, 0.35, 0.64), "pandur": (0.55, 0.20, 0.35, 0.64),
    "radnik": (0.50, 0.20, 0.36, 0.64), "shmizla": (0.45, 0.25, 0.40, 0.64), "srednoskolec": (0.55, 0.20, 0.30, 0.64),
    "stojan": (0.45, 0.28, 0.30, 0.64), "tetkica": (0.50, 0.25, 0.40, 0.64), "vojnik": (0.55, 0.15, 0.33, 0.64),
}
_tex = {}                          # fallback sprites: hero index -> texture / False
_state = {}                        # player key -> _Face
_heads = {}                        # (hero index, render size) -> facerig.Head / False (mesh unavailable)
_cost = [0.0, 0]                   # EMA of the render cost per face (ms)

PARAMS = {"jaw": 0.0, "smile": .15, "eye": 1.0, "bulge": 1.0, "gx": 0.0, "gy": 0.0, "cross": 0.0, "dizzy_x": 0.0, "dizzy_y": 0.0,
          "brow": 0.0, "angry": 0.0, "worry": 0.0, "brow_l": 0.0, "brow_r": 0.0, "yaw": 0.0, "pitch": 0.0, "roll": 0.0,
          "sx": 1.0, "sy": 1.0, "tx": 0.0, "ty": 0.0, "tongue": 0.0, "body_y": 0.0, "sink": 0.0}
SPEED = {"jaw": 30, "eye": 28, "smile": 9, "tongue": 12}      # per-parameter smoothing rate (default 10)


def reserve(cfg, n):
    return 0 if not cfg.get("faces_on", True) or n <= 0 else SIZES[cfg.get("faces_size", 1) % 3] + 22


def _wrap(a):
    return (a + math.pi) % math.tau - math.pi


def _clip(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


class _Face:
    def __init__(self, key):
        self.r = random.Random(key * 7919 + 13)
        self.t = self.r.uniform(0, 50)
        self.e = dict(PARAMS)
        self.next_look, self.tx, self.ty = self.r.uniform(.3, 2.0), 0.0, 0.0
        self.next_blink, self.blink = self.r.uniform(1.0, 4.0), -1.0
        self.next_quirk, self.quirk, self.qt = self.r.uniform(3.0, 8.0), None, 0.0
        self.sp = self.m = self.lvl_s = 0.0
        self.spd = self.yr = self.dec = 0.0
        self.prev = None
        self.ev = {"crash": 0.0, "hit": 0.0, "punch": 0.0, "fight": 0.0, "cash": 0.0, "stun": 0.0}
        self.vowel = 0.0
        self.next_vowel = 0.0
        self.last_draw = 0.0
        self.phase = self.r.random() / RENDER_HZ
        self.mood = "idle"

    # ---------------------------------------------------------------- state -> expression targets
    def update(self, dt, q, bearing):
        r, ev = self.r, self.ev
        self.t += dt
        for k in ev:
            ev[k] = max(0.0, ev[k] - dt)
        talk, lvl = bool(q.get("talk")), q.get("lvl", 0.0)
        hp, dead, foot = q.get("hp", 100), bool(q.get("dead")) or q.get("hp", 100) <= 0, bool(q.get("foot", True))
        vx, vy, h = q.get("vx", 0.0), q.get("vy", 0.0), q.get("h", 0.0)
        speed = math.hypot(vx, vy)
        if self.prev is not None and dt > 0:
            p = self.prev
            self.yr += (_wrap(h - p["h"]) / dt - self.yr) * min(1.0, dt * 6)
            drop = (p["speed"] - speed) / dt
            self.dec += (drop - self.dec) * min(1.0, dt * 8)
            if p["foot"] == foot:
                if not foot and ((p["speed"] > 9 and p["speed"] - speed > 7 and drop > 25) or p["hp"] - hp > 6):
                    ev["crash"] = 2.2
                if foot and p["hp"] - hp > 1.5 and not dead:
                    ev["hit"] = .7
                    ev["fight"] = 4.0
                    ev["stun"] = max(ev["stun"], .9 if p["hp"] - hp > 12 else 0.0)
            if foot and q.get("atk", 0) and not p["atk"]:
                ev["punch"] = .4
                ev["fight"] = 4.0
            if q.get("money", 0) > p["money"] + 0 and q.get("money", 0) - p["money"] < 100000:
                ev["cash"] = 1.7
        self.prev = {"h": h, "speed": speed, "foot": foot, "hp": hp, "atk": q.get("atk", 0), "money": q.get("money", 0)}
        self.spd += (speed - self.spd) * min(1.0, dt * 4)
        lat = abs(self.yr) * self.spd
        crazy = 0.0 if foot else _clip((self.spd - 16) / 16) * .55 + _clip((lat - 7) / 14) * .8
        crazy = _clip(crazy)
        # blinking, looking around
        self.next_look -= dt
        if self.next_look <= 0:
            self.tx, self.ty = r.uniform(-1, 1), r.uniform(-.6, .6)
            self.next_look = r.uniform(1.0, 3.2) if foot else r.uniform(2.0, 4.0)
        self.next_blink -= dt
        if self.next_blink <= 0:
            self.blink, self.next_blink = 0.0, r.uniform(1.5, 5.0) * (.5 if crazy > .5 else 1.0)
        if self.blink >= 0:
            self.blink += dt
            if self.blink > .17:
                self.blink = -1.0
        # speaking
        self.sp += ((1.0 if talk else 0.0) - self.sp) * min(1.0, dt * 8)
        goal = _clip(lvl * 3.6) if talk else 0.0
        self.m += (goal - self.m) * min(1.0, dt * (26 if goal > self.m else 11))
        self.next_vowel -= dt
        if talk and self.next_vowel <= 0:
            self.vowel, self.next_vowel = r.uniform(-.4, 1.0), r.uniform(.08, .22)        # mouth shape: -O ... +E (wide)
        m, sp = self.m, self.sp
        # random idle quirks
        busy = talk or dead or crazy > .2 or ev["fight"] > 0 or ev["crash"] > 0 or ev["cash"] > 0 or hp < 30
        self.next_quirk -= dt
        if self.quirk:
            self.qt += dt
            if self.qt > self.quirk[1] or busy:
                self.quirk = None
                self.next_quirk = r.uniform(4.0, 9.0)
        elif self.next_quirk <= 0 and not busy:
            self.quirk = (r.choice(("yawn", "wink", "grin", "tongue", "cross", "brows", "whistle", "sleepy", "sneeze", "stare", "chew", "bigeyes")), r.uniform(1.4, 2.6))
            self.qt = 0.0
        # ---- targets
        T = dict(PARAMS)
        T["gx"], T["gy"] = self.tx, self.ty
        T["yaw"], T["pitch"] = self.tx * .22 + math.sin(self.t * .7) * .05, self.ty * .12
        T["roll"] = math.sin(self.t * .9) * .03
        T["smile"] = .12
        T["body_y"] = math.sin(self.t * 1.4) * .002
        self.mood = "idle"
        qn, qt = (self.quirk[0], self.qt / self.quirk[1]) if self.quirk else (None, 0.0)
        env = math.sin(math.pi * _clip(qt))
        if qn == "yawn":
            T["jaw"], T["eye"], T["pitch"], T["brow"], T["sy"] = env, 1 - .85 * env, -.25 * env, .8 * env, 1 + .05 * env
        elif qn == "wink":
            T["brow_r"], T["smile"] = .8 * env, .7 * env
            if env > .5:
                T["eye"] = 1.0
            T["roll"] = .1 * env
        elif qn == "grin":
            T["smile"], T["jaw"], T["brow"], T["sx"] = 1.0 * env, .18 * env, .5 * env, 1 + .06 * env
        elif qn == "tongue":
            T["tongue"], T["jaw"], T["cross"], T["roll"], T["smile"] = env, .3 * env, .9 * env, .18 * math.sin(self.t * 6) * env, .6 * env
        elif qn == "cross":
            T["cross"], T["bulge"], T["dizzy_x"] = env, 1 + .15 * env, 0.0
            T["smile"], T["roll"] = .5 * env, -.12 * env
        elif qn == "brows":
            w = math.sin(self.t * 16)
            T["brow_l"], T["brow_r"], T["smile"] = .9 * env * (w > 0), .9 * env * (w <= 0), .8 * env
        elif qn == "whistle":
            T["jaw"], T["smile"], T["roll"], T["gy"] = .16 * env, -.7 * env, .1 * math.sin(self.t * 5) * env, .4 * env
        elif qn == "sleepy":
            T["eye"], T["pitch"], T["roll"], T["jaw"] = .18 + .8 * (1 - env), .3 * env + .1 * math.sin(self.t * 3) * env, .12 * env, .08 * env
            T["worry"] = .4 * env
        elif qn == "sneeze":
            a = _clip(qt * 1.25)
            if a < .6:
                T["pitch"], T["jaw"], T["eye"], T["sy"] = -.35 * a / .6, .5 * a / .6, 1 - .3 * a, 1.04
            else:
                k = (a - .6) / .4
                T["pitch"], T["eye"], T["jaw"], T["sy"], T["tx"] = .4 * (1 - k), .04, .9 * (1 - k * .5), .94, math.sin(self.t * 60) * .01
        elif qn == "stare":
            T["bulge"], T["eye"], T["gx"], T["gy"], T["yaw"], T["pitch"] = 1.12, 1.0, 0.0, 0.0, 0.0, 0.0
            T["worry"] = .35 * env
        elif qn == "chew":
            T["jaw"], T["smile"] = .2 + .2 * math.sin(self.t * 12), .2
        elif qn == "bigeyes":
            T["bulge"], T["brow"], T["sx"], T["sy"] = 1 + .3 * env, 1.0 * env, 1 + .05 * env, 1 + .05 * env
        if qn:
            self.mood = qn
        # ---- driving
        if not foot and not dead:
            fast = _clip((self.spd - 8) / 22)
            T["gx"], T["gy"] = T["gx"] * (1 - fast) * .5, 0.0
            T["yaw"] *= (1 - fast)
            T["pitch"] = -.1 * fast + _clip(-self.dec / 40) * .5 + T["pitch"] * (1 - fast)
            T["roll"] += _clip(self.yr * self.spd / 40, -1, 1) * .35
            T["tx"] = _clip(self.yr * self.spd / 40, -1, 1) * .012
            T["bulge"] = max(T["bulge"], 1 + .22 * fast + .2 * crazy)
            T["brow"] = max(T["brow"], .3 * fast + .5 * crazy)
            T["tx"] += math.sin(self.t * 40) * .004 * fast
            T["smile"] = max(T["smile"], .25 + .75 * crazy)
            T["jaw"] = max(T["jaw"], .1 * fast + .4 * crazy * (.5 + .5 * math.sin(self.t * 9)))
            T["sx"], T["sy"] = 1 + .05 * crazy, 1 - .03 * crazy
            if crazy > .35:
                T["cross"] = 0.0
                T["gx"] = math.sin(self.t * 9) * .6 * crazy
                T["brow_l"] = max(T["brow_l"], .5 * crazy * (math.sin(self.t * 7) > 0))
                T["tongue"] = .5 * crazy * (math.sin(self.t * 5) > .3)
                self.mood = "crazy"
            elif fast > .4:
                self.mood = "fast"
            if self.dec > 22 and self.spd > 6:                      # hard braking: head thrown forward, eyes and mouth round
                T["jaw"], T["bulge"], T["pitch"], T["brow"], T["smile"] = .7, 1.35, .45, 1.0, -.6
                self.mood = "brake"
        # ---- fighting
        if foot and ev["fight"] > 0 and not dead:
            f = _clip(ev["fight"] / 1.5)
            T["angry"], T["brow"], T["smile"], T["jaw"], T["eye"] = 1.0 * f, -.3 * f, -.6 * f, max(T["jaw"], .22 * f), 1 - .25 * f
            T["tx"] = math.sin(self.t * 45) * .005 * f
            T["gx"], T["gy"] = 0.0, 0.0
            T["yaw"] = T["pitch"] = 0.0
            self.mood = "fight"
            if ev["punch"] > 0:                                          # punch: head lunges, mouth roars
                k = _clip(ev["punch"] / .4)
                T["pitch"], T["jaw"], T["sx"], T["sy"], T["ty"] = .3 * k, .9 * k, 1 + .1 * k, 1 - .06 * k, -.01 * k
        if ev["hit"] > 0 and not dead:                                   # hit: recoil, squash, eyes squeezed, stars when it was hard
            k = _clip(ev["hit"] / .7)
            T["pitch"], T["roll"], T["eye"], T["jaw"], T["sx"], T["sy"] = -.45 * k, .35 * k * (1 if int(self.t * 9) % 2 else -1), .08, .6 * k, 1 + .15 * k, 1 - .12 * k
            T["brow"], T["smile"], T["worry"], T["angry"] = 0.0, -1.0, 1.0, 0.0
            T["tx"] = .03 * k * math.sin(self.t * 50)
            self.mood = "hit"
        if ev["crash"] > 0 and not dead:                                 # crash: dazed, eyes spinning, head wobbles, tongue out
            k = _clip(ev["crash"] / 2.2)
            ph = self.t * 8
            T["dizzy_x"], T["dizzy_y"], T["cross"] = math.cos(ph) * k, math.sin(ph) * k, .0
            T["eye"], T["bulge"] = 1.0, 1.2
            T["roll"], T["pitch"] = .3 * math.sin(self.t * 5) * k, .2 * math.sin(self.t * 3 + 1) * k
            T["jaw"], T["tongue"], T["smile"], T["worry"] = .35 * k, k, -.4, .7 * k
            T["sx"], T["sy"] = 1 + .12 * math.sin(self.t * 14) * k, 1 - .1 * math.sin(self.t * 14) * k
            self.mood = "crash"
        if ev["cash"] > 0 and not dead:
            k = _clip(ev["cash"] / 1.7)
            T["smile"], T["jaw"], T["brow"], T["bulge"], T["sy"], T["roll"] = 1.0, .45 * (.5 + .5 * math.sin(self.t * 14)), 1.0, 1.15, 1 + .06 * math.sin(self.t * 14) * k, .1 * math.sin(self.t * 8)
            self.mood = "cash"
        if hp < 30 and not dead and ev["crash"] <= 0 and ev["hit"] <= 0:                         # almost dead: scared, trembling
            T["worry"], T["brow"], T["smile"], T["bulge"], T["eye"] = 1.0, .6, -.8, 1.2, 1.0
            T["tx"] = math.sin(self.t * 33) * .004
            T["jaw"] = max(T["jaw"], .15 + .1 * math.sin(self.t * 21))
            self.mood = "scared"
        # ---- speaking overrides the mouth, and the head turns towards the speaker
        if sp > .02:
            wide = self.vowel
            T["jaw"] = max(T["jaw"] * (1 - sp), m * (.5 + .5 * (1 - abs(wide))) * 1.1) if sp > .5 else T["jaw"]
            T["smile"] = T["smile"] * (1 - sp) + sp * (wide * .5 + .1)
            T["brow"] = max(T["brow"], sp * m * .9)
            T["bulge"] = max(T["bulge"], 1 + .25 * sp * _clip(m - .5, 0, 1))
            T["sx"] *= 1 - .03 * m * sp
            T["sy"] *= 1 + .05 * m * sp
            T["ty"] += abs(math.sin(self.t * 12)) * .008 * m * sp
            T["pitch"] += math.sin(self.t * 11) * .08 * m * sp
            T["roll"] += math.sin(self.t * 7) * .06 * sp
            if bearing is not None:
                T["yaw"] = T["yaw"] * (1 - sp) + sp * bearing[0] * .55
                T["pitch"] = T["pitch"] + sp * bearing[1] * .2
                T["gx"], T["gy"] = T["gx"] * (1 - sp) + sp * bearing[0], T["gy"] * (1 - sp) - sp * bearing[1] * .7
            if self.mood in ("idle",) or (self.quirk and qn):
                self.mood = "talk"
        if dead:
            T.update({"eye": .04, "jaw": .25, "tongue": 1.0, "smile": -.8, "roll": .22, "pitch": .25, "worry": .6, "bulge": 1.0, "cross": 0.0,
                      "dizzy_x": 0.0, "dizzy_y": 0.0, "gx": 0.0, "gy": 0.0, "tx": 0.0, "yaw": 0.0, "brow": 0.0})
            self.mood = "dead"
        # blink overlay (not while the lid state is forced by a mood)
        if self.blink >= 0 and T["eye"] > .5:
            T["eye"] = max(.05, 1 - math.sin(math.pi * self.blink / .17) * .97)
        e = self.e
        for k, v in T.items():
            a = e[k]
            e[k] = a + (v - a) * min(1.0, dt * SPEED.get(k, 10))
        if self.blink >= 0 and T["eye"] < .5:
            pass
        if self.blink >= 0 and self.mood not in ("dead", "hit"):
            e["eye"] = T["eye"]                     # blinks are quick: no smoothing
        return crazy


# ------------------------------------------------------------------ rendering
def _head(i, S):
    key = (i, S * 2)
    h = _heads.get(key)
    if h is None:
        try:
            import facerig
            h = facerig.Head(i, S * 2)
        except Exception:                          # noqa: BLE001 - no mesh: the caricature fallback is used
            h = False
        _heads[key] = h
    return h


def _bake(i):
    t = _tex.get(i)
    if t is not None:
        return t
    t = False
    p = characters.image_path(i)
    if p:
        img = rl.load_image(p)
        if img.width:
            cx, cy, s, _ = FACE.get(characters.LIKOVI[i][0], (0.5, 0.25, 0.35, 0.64))
            side = min(int(s * img.width * 1.55 * MARGIN), img.width, img.height)
            x = max(0, min(img.width - side, int(cx * img.width - side / 2)))
            y = max(0, min(img.height - side, int(cy * img.height - side / 2)))
            rl.image_crop(img, rl.Rectangle(x, y, side, side))
            rl.image_resize(img, TEX, TEX)
            t = rl.load_texture_from_image(img)
            rl.set_texture_filter(t, rl.TEXTURE_FILTER_BILINEAR)
        rl.unload_image(img)
    _tex[i] = t
    return t


def _star(cx, cy, r, rot, col):
    rl.draw_poly(rl.Vector2(cx, cy), 4, r, rot, col)
    rl.draw_poly(rl.Vector2(cx, cy), 4, r * .55, rot + 45, col)


def _props(f, head, x, y, S, color):
    """2D props over the head for the funny moods."""
    m, t, e = f.mood, f.t, f.e
    if m in ("crash", "hit", "dead") or (m == "brake" and False):
        n = 3
        for k in range(n):
            a = t * (5 if m != "dead" else 2.5) + k * math.tau / n
            _star(x + S * (.5 + .34 * math.cos(a)), y + S * (.1 + .07 * math.sin(a)), S * .075, t * 90, rl.Color(255, 220, 60, 255))
    if m == "dead":
        rl.draw_ellipse_lines(int(x + S * .5), int(y + S * .03), S * .27, S * .06, rl.Color(255, 235, 90, 255))
        rl.draw_ellipse_lines(int(x + S * .5), int(y + S * .035), S * .27, S * .06, rl.Color(255, 235, 90, 255))
    if head and m in ("dead", "cash"):
        for s in (-1, 1):
            u, v = head.project((s * .06 if True else 0, head.eye_y, .135), e) if head.eye_c else (.5, .4)
            u, v = head.project(tuple(head.eye_c[s]), e)
            px, py = x + u * S, y + v * S
            if m == "dead":
                d = S * .07
                rl.draw_line_ex(rl.Vector2(px - d, py - d), rl.Vector2(px + d, py + d), 3, rl.Color(20, 20, 20, 255))
                rl.draw_line_ex(rl.Vector2(px - d, py + d), rl.Vector2(px + d, py - d), 3, rl.Color(20, 20, 20, 255))
            else:
                font.draw_text("$", int(px - S * .06), int(py - S * .11), int(S * .22), rl.Color(40, 190, 70, 255), bold=True)
    if m == "scared" or (m == "hit"):
        sx_, sy_ = x + S * .82, y + S * (.25 + (t * .6) % .3)
        rl.draw_circle(int(sx_), int(sy_ + S * .03), S * .04, rl.Color(120, 190, 255, 230))
        rl.draw_triangle(rl.Vector2(sx_, sy_ - S * .06), rl.Vector2(sx_ - S * .035, sy_ + S * .02), rl.Vector2(sx_ + S * .035, sy_ + S * .02), rl.Color(120, 190, 255, 230))
    if m == "fight":
        c = rl.Color(235, 40, 40, 255)
        px, py, d = x + S * .18, y + S * .12, S * .07
        for a in (0, 90, 180, 270):
            ca_, sa_ = math.cos(math.radians(a + 45 + math.sin(t * 20) * 8)), math.sin(math.radians(a + 45 + math.sin(t * 20) * 8))
            rl.draw_line_ex(rl.Vector2(px + ca_ * d * .3, py + sa_ * d * .3), rl.Vector2(px + ca_ * d, py + sa_ * d), 3, c)
    if m == "sleepy":
        for k in range(3):
            ph = (t * .8 + k / 3) % 1
            font.draw_text("z", int(x + S * (.7 + ph * .18)), int(y + S * (.3 - ph * .3)), int(S * (.14 + .1 * ph)), rl.Color(210, 225, 255, int(255 * (1 - ph))), bold=True)
    if m == "whistle":
        for k in range(2):
            ph = (t * 1.2 + k / 2) % 1
            px, py = x + S * (.62 + ph * .3), y + S * (.62 - ph * .35)
            rl.draw_circle(int(px), int(py), S * .035, rl.Color(240, 240, 255, int(255 * (1 - ph))))
            rl.draw_line_ex(rl.Vector2(px + S * .03, py), rl.Vector2(px + S * .03, py - S * .12), 2, rl.Color(240, 240, 255, int(255 * (1 - ph))))
    if m in ("fast", "crazy"):                                               # speed lines
        for k in range(5):
            ph = (t * (3 + k * .4) + k * .37) % 1
            ly = y + S * (.12 + k * .17)
            lx = x + S * (1.0 - ph * 1.0)
            rl.draw_line_ex(rl.Vector2(lx, ly), rl.Vector2(min(x + S, lx + S * .25), ly), 2, rl.Color(255, 255, 255, int(150 * (1 - ph))))
    if m == "brake":
        font.draw_text("!", int(x + S * .06), int(y + S * .02), int(S * .3), rl.Color(255, 60, 40, 255), bold=True)


def _draw(f, i, x, y, S, color, name, me, ctx):
    spk = f.sp > .3
    head = _head(i, S) if ctx["mesh"] else False
    rl.draw_rectangle(x - 3, y - 3, S + 6, S + 6, rl.Color(10, 10, 14, 190))
    if head:
        now = ctx["now"]
        if now - f.last_draw >= ctx["interval"] or f.last_draw == 0:
            f.last_draw = now - f.phase if f.last_draw == 0 else now
            a = time.perf_counter()
            bg = rl.Color(color[0] // 6 + 22, color[1] // 6 + 24, color[2] // 6 + 30, 255)
            head.render(f.e, bg)
            ctx["spent"] += time.perf_counter() - a
            ctx["n"] += 1
        rl.draw_texture_pro(head.rt.texture, rl.Rectangle(0, 0, head.size, -head.size), rl.Rectangle(x, y, S, S), rl.Vector2(0, 0), 0, rl.WHITE)
    else:
        _sprite(f, i, x, y, S, color, name)
    _props(f, head, x, y, S, color)
    col = rl.Color(90, 230, 120, 255) if spk else rl.Color(*color, 255)
    rl.draw_rectangle_lines_ex(rl.Rectangle(x - 1, y - 1, S + 2, S + 2), 3 if spk else 2, col)
    if spk:
        pulse = .5 + .5 * math.sin(f.t * 10)
        rl.draw_rectangle_lines_ex(rl.Rectangle(x - 4, y - 4, S + 8, S + 8), 2, rl.Color(90, 230, 120, int(70 + 110 * pulse)))
    nm = name if len(name) <= 9 else name[:8] + "…"
    sz = max(12, S // 5)
    font.draw_text(nm, x + 1, y + S + 3, sz, rl.Color(0, 0, 0, 170))
    font.draw_text(nm, x, y + S + 2, sz, rl.Color(*color, 255), bold=me)


def _sprite(f, i, x, y, S, color, name):
    """Fallback: the caricature crop with a jaw drop (no mesh available)."""
    tex = _bake(i)
    e = f.e
    if not tex:
        rl.draw_rectangle(x, y, S, S, rl.Color(60, 60, 70, 255))
        font.draw_text(name[:1], x + S // 2 - 8, y + S // 2 - 14, 28, rl.Color(*color, 255), bold=True)
        return
    w = TEX / MARGIN
    mouth = FACE.get(characters.LIKOVI[i][0], (0, 0, 0, .64))[3]
    pan_x = (TEX - w) / 2 + e["gx"] * .09 * TEX
    pan_y = (TEX - w) / 2 - e["gy"] * .06 * TEX
    split = mouth * w
    Z = S * 1.1
    up = Z * mouth
    drop = e["jaw"] * .1 * S
    rl.begin_scissor_mode(x, y, S, S)
    rl.rl_push_matrix()
    rl.rl_translatef(x + S / 2, y + S / 2, 0)
    rl.rl_rotatef(math.degrees(e["roll"]) * 2, 0, 0, 1)
    rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y, w, split), rl.Rectangle(-Z / 2, -Z / 2, Z, up), rl.Vector2(0, 0), 0, rl.WHITE)
    if drop > .6:
        rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y + split - 1, w, 1), rl.Rectangle(-Z / 2, -Z / 2 + up, Z, drop + 1), rl.Vector2(0, 0), 0, rl.WHITE)
        rl.draw_ellipse(0, int(-Z / 2 + up + drop / 2 - 1), S * .17, drop / 2 + 1, rl.Color(70, 10, 20, 255))
    rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y + split, w, w - split), rl.Rectangle(-Z / 2, -Z / 2 + up + drop, Z, Z - up), rl.Vector2(0, 0), 0, rl.WHITE)
    rl.rl_pop_matrix()
    rl.end_scissor_mode()


def _bearing(sim, cam, q, sw, sh):
    sp = rl.get_world_to_screen(rl.Vector3(q["x"], sim.w.ground_y(q["x"], q["y"]) + 1.7, q["y"]), cam)
    dx, dy = sp.x - sw / 2, sp.y - sh / 2
    n = math.hypot(dx, dy)
    if not (math.isfinite(n) and n > 1):
        return (0.0, 0.0)
    return (dx / n, dy / n)


_slow = [False]


def draw(sim, cam, sw, sh, cfg, dt):
    """Call once per frame while playing."""
    mpv = getattr(sim, "mp_view", None)
    if not mpv or not cfg.get("faces_on", True):
        return
    S = SIZES[cfg.get("faces_size", 1) % 3]
    me = mpv.get("me")
    rows = ([me] if me else []) + list(mpv["players"])
    n = len(characters.LIKOVI)
    x, y = 14, (92 if sim.mode == "car" else 12)
    ctx = {"now": time.monotonic(), "interval": 1.0 / (SLOW_HZ if _slow[0] else RENDER_HZ), "spent": 0.0, "n": 0, "mesh": cfg.get("faces_mesh", True)}
    live = set()
    for q in rows:
        key = q.get("pid", -1)
        live.add(key)
        f = _state.get(key)
        if f is None:
            f = _state[key] = _Face(key + 2)
        talk = bool(q.get("talk"))
        bearing = _bearing(sim, cam, q, sw, sh) if talk and key != -1 else None
        f.update(dt, q, bearing)
        _draw(f, q.get("lik", 0) % n, x, y, S, q["color"], q["name"], key == -1, ctx)
        y += S + max(12, S // 5) + 10
    if ctx["n"]:                                       # adaptive: if rendering the heads costs too much, update them less often
        c = ctx["spent"] * 1000 / ctx["n"]
        _cost[0] += (c - _cost[0]) * .1
        _slow[0] = _cost[0] > SLOW_MS if not _slow[0] else _cost[0] > SLOW_MS * .6
    if len(_state) > len(live):
        for k in [k for k in _state if k not in live]:
            del _state[k]
