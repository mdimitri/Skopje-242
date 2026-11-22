"""Multiplayer: a small animated face window per player (left edge of the screen).
Each face is cropped ONCE from the hero's caricature (assets/likovi) into a 128 px texture; animation is only source-rect panning,
a small tilt, a jaw drop and blinking, i.e. ~8 cheap draw calls per face and no 3D.  Idle: looks around, blinks.  Speaking (voice chat):
mouth opens with the loudness, head bobs, and the head turns towards where the speaker is relative to the view."""
import math
import random
import time

import pyray as rl
import font
import characters

SIZES = (56, 76, 100)
SIZE_NAMES = ["Мали", "Средни", "Големи"]
TEX = 128
MARGIN = 1.25                      # the baked crop is 25% larger than the face: room to pan
# hero id -> (face centre x, y as fraction of the picture, face width as fraction of picture width, mouth line 0..1 inside the face)
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
_tex = {}                          # hero index -> texture, or False when the picture is missing
_state = {}                        # player key -> animation state


def reserve(cfg, n):
    """Pixels of the left edge the face column uses (so other HUD text can move over)."""
    return 0 if not cfg.get("faces_on", True) or n <= 0 else SIZES[cfg.get("faces_size", 1) % 3] + 22


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
            side = min(int(s * img.width * 1.55 * MARGIN), img.width, img.height)   # head + hair + shoulders' top
            x = max(0, min(img.width - side, int(cx * img.width - side / 2)))
            y = max(0, min(img.height - side, int(cy * img.height - side / 2)))
            rl.image_crop(img, rl.Rectangle(x, y, side, side))
            rl.image_resize(img, TEX, TEX)
            t = rl.load_texture_from_image(img)
            rl.set_texture_filter(t, rl.TEXTURE_FILTER_BILINEAR)
        rl.unload_image(img)
    _tex[i] = t
    return t


class _Face:
    def __init__(self, key):
        self.r = random.Random(key * 7919 + 13)
        self.gx = self.gy = self.tx = self.ty = 0.0
        self.next_look = self.r.uniform(0.3, 2.0)
        self.next_blink = self.r.uniform(1.0, 4.0)
        self.blink = -1.0
        self.sp = self.m = 0.0
        self.t = self.r.uniform(0, 50)

    def update(self, dt, talk, lvl, bearing):
        r = self.r
        self.t += dt
        self.next_look -= dt
        if self.next_look <= 0:
            self.tx, self.ty = r.uniform(-1, 1), r.uniform(-0.6, 0.6)
            self.next_look = r.uniform(1.2, 3.5)
        self.next_blink -= dt
        if self.next_blink <= 0:
            self.blink, self.next_blink = 0.0, r.uniform(1.5, 5.0)
        if self.blink >= 0:
            self.blink += dt
            if self.blink > 0.16:
                self.blink = -1.0
        self.sp += ((1.0 if talk else 0.0) - self.sp) * min(1.0, dt * 8)
        goal = min(1.0, lvl * 3.5) if talk else 0.0
        self.m += (goal - self.m) * min(1.0, dt * (22 if goal > self.m else 9))
        tx, ty = (bearing[0], bearing[1] * 0.5) if talk and bearing else (self.tx, self.ty)
        k = min(1.0, dt * 5)
        self.gx += (tx - self.gx) * k
        self.gy += (ty - self.gy) * k


def _draw(f, i, x, y, S, color, name, me):
    tex = _bake(i)
    spk = f.sp > 0.3
    rl.draw_rectangle(x - 3, y - 3, S + 6, S + 6, rl.Color(10, 10, 14, 190))
    if not tex:
        rl.draw_rectangle(x, y, S, S, rl.Color(60, 60, 70, 255))
        font.draw_text(name[:1], x + S // 2 - 8, y + S // 2 - 14, 28, rl.Color(*color, 255), bold=True)
    else:
        w = TEX / MARGIN
        mouth = characters_mouth(i)
        pan_x = (TEX - w) / 2 + f.gx * 0.09 * TEX
        pan_y = (TEX - w) / 2 + f.gy * 0.06 * TEX + math.sin(f.t * 14) * f.sp * (0.3 + f.m) * 0.02 * TEX
        split = mouth * w                                     # source rows above the mouth line
        up = S * mouth * 1.1                                 # destination zoom 1.1 hides the tilt corners
        Z = S * 1.1
        drop = f.m * 0.1 * S
        tilt = f.gx * 5 + f.sp * math.sin(f.t * 9) * 3
        rl.begin_scissor_mode(x, y, S, S)
        rl.rl_push_matrix()
        rl.rl_translatef(x + S / 2, y + S / 2 + f.gy * 2, 0)
        rl.rl_rotatef(tilt, 0, 0, 1)
        rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y, w, split), rl.Rectangle(-Z / 2, -Z / 2, Z, up), rl.Vector2(0, 0), 0, rl.WHITE)
        if drop > 0.6:                                         # fill the gap with the skin row at the mouth line, then the open mouth
            rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y + split - 1, w, 1), rl.Rectangle(-Z / 2, -Z / 2 + up, Z, drop + 1), rl.Vector2(0, 0), 0, rl.WHITE)
            rl.draw_ellipse(0, int(-Z / 2 + up + drop / 2 - 1), S * 0.17, drop / 2 + 1, rl.Color(70, 10, 20, 255))
        rl.draw_texture_pro(tex, rl.Rectangle(pan_x, pan_y + split, w, w - split), rl.Rectangle(-Z / 2, -Z / 2 + up + drop, Z, Z - up), rl.Vector2(0, 0), 0, rl.WHITE)
        if f.blink >= 0:                                       # blink: eyelid lines on the eye row
            c = 1 - abs(f.blink / 0.08 - 1)
            if c > 0.2:
                ey = -Z / 2 + Z * 0.40
                rl.draw_rectangle(int(-Z * 0.30), int(ey), int(Z * 0.24), max(1, int(S * 0.05 * c)), rl.Color(40, 28, 24, 215))
                rl.draw_rectangle(int(Z * 0.06), int(ey), int(Z * 0.24), max(1, int(S * 0.05 * c)), rl.Color(40, 28, 24, 215))
        rl.rl_pop_matrix()
        rl.end_scissor_mode()
    col = rl.Color(90, 230, 120, 255) if spk else rl.Color(*color, 255)
    rl.draw_rectangle_lines_ex(rl.Rectangle(x - 1, y - 1, S + 2, S + 2), 3 if spk else 2, col)
    if spk:
        pulse = 0.5 + 0.5 * math.sin(f.t * 10)
        rl.draw_rectangle_lines_ex(rl.Rectangle(x - 4, y - 4, S + 8, S + 8), 2, rl.Color(90, 230, 120, int(70 + 110 * pulse)))
    nm = name if len(name) <= 9 else name[:8] + "…"
    sz = max(12, S // 5)
    font.draw_text(nm, x + 1, y + S + 3, sz, rl.Color(0, 0, 0, 170))
    font.draw_text(nm, x, y + S + 2, sz, rl.Color(*color, 255), bold=me)


def characters_mouth(i):
    return FACE.get(characters.LIKOVI[i][0], (0, 0, 0, 0.64))[3]


def _bearing(sim, cam, q, sw, sh):
    sp = rl.get_world_to_screen(rl.Vector3(q["x"], sim.w.ground_y(q["x"], q["y"]) + 1.7, q["y"]), cam)
    dx, dy = sp.x - sw / 2, sp.y - sh / 2
    n = math.hypot(dx, dy)
    if not (math.isfinite(n) and n > 1):
        return (0.0, 0.0)
    return (dx / n, dy / n)


def draw(sim, cam, sw, sh, cfg, dt):
    """Call once per frame while playing."""
    mpv = getattr(sim, "mp_view", None)
    if not mpv or not cfg.get("faces_on", True):
        return
    S = SIZES[cfg.get("faces_size", 1) % 3]
    me = mpv.get("me")
    rows = ([me] if me else []) + list(mpv["players"])
    n = len(characters.LIKOVI)
    x, y = 14, 70
    live = set()
    for q in rows:
        key = q.get("pid", -1)
        live.add(key)
        f = _state.get(key)
        if f is None:
            f = _state[key] = _Face(key + 2)
        talk = bool(q.get("talk"))
        bearing = _bearing(sim, cam, q, sw, sh) if talk and key != -1 else None
        f.update(dt, talk, q.get("lvl", 0.0), bearing)
        _draw(f, q.get("lik", 0) % n, x, y, S, q["color"], q["name"], key == -1)
        y += S + max(12, S // 5) + 10
    if len(_state) > len(live):
        for k in [k for k in _state if k not in live]:
            del _state[k]
