"""Екран за вчитување: приказна за возилата и ликовите.  Блок од возила што возат низ лажна улица (со шега за секое),
па сите ликови со лудни изјави, па пак возила од каде што запре, и така во круг.  Само црта (pyray), без состојба од играта."""
import math
import random
import time

import pyray as rl

import characters
import font
import poster as poster_mod
import showcase_lines as L
import vehicles

CAR_SECS, CHAR_SECS, BLOCK = 5.6, 6.4, 10
GOLD = rl.Color(240, 200, 60, 255)
PAINT = [(190, 50, 45), (50, 90, 160), (210, 210, 215), (60, 130, 85), (200, 160, 40), (110, 60, 130), (150, 150, 155), (40, 40, 46),
         (200, 110, 40), (130, 30, 40)]


def _c(t, a=255):
    return rl.Color(int(t[0]), int(t[1]), int(t[2]), a)


class Showcase:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.cars = list(range(vehicles.N))
        self.rng.shuffle(self.cars)
        self.car_pos = 0
        self.shown_cars = 0
        self.queue = []
        self.cur = None
        self.t0 = time.time()
        self.tex = {}
        self.now_fn = time.time
        self.hills = [(self.rng.uniform(0, 1), self.rng.uniform(0.12, 0.3), self.rng.uniform(0.08, 0.2)) for _ in range(9)]
        self.houses = [(self.rng.uniform(0, 1), self.rng.uniform(0.07, 0.2), self.rng.uniform(0.06, 0.12), self.rng.randrange(4)) for _ in range(12)]

    # ------------------------------------------------------------------ sequence
    def _refill(self):
        for _ in range(BLOCK):
            self.queue.append(("car", self.cars[self.car_pos % len(self.cars)]))
            self.car_pos += 1
        order = list(range(len(characters.LIKOVI)))
        self.rng.shuffle(order)
        self.queue += [("char", i) for i in order]

    def _next(self, now):
        if not self.queue:
            self._refill()
        kind, i = self.queue.pop(0)
        if kind == "car":
            name = vehicles.IDS[i]
            jokes = list(L.CAR.get(name) or L.STYLE.get(vehicles.STYLE[i], []))
            ex = L.EXTRA.get(vehicles.EXTRA[i])
            if ex:
                jokes.append(ex)
            text = self.rng.choice(jokes) if jokes else ""
            secs = CAR_SECS
            col = vehicles.FIXED[i] or PAINT[(i * 7 + 3) % len(PAINT)]
        else:
            q = L.QUOTE.get(characters.LIKOVI[i][0]) or [""]
            text, secs, col = self.rng.choice(q), CHAR_SECS, None
        self.shown_cars += kind == "car"
        self.cur = {"kind": kind, "i": i, "text": text, "t0": now, "secs": secs, "col": col, "k": (self.shown_cars - 1) % vehicles.N + 1}

    # ------------------------------------------------------------------ drawing helpers
    def _texture(self, i):
        if i not in self.tex:
            p = characters.image_path(i)
            t = None
            if p:
                try:
                    t = rl.load_texture(p)
                    rl.set_texture_filter(t, rl.TEXTURE_FILTER_BILINEAR)
                except Exception:  # noqa: BLE001
                    t = None
            self.tex[i] = t
        return self.tex[i]

    def _street(self, x, y, w, h, scroll):
        """Sky, hills, houses and a road that moves left (the dummy street).  Returns the y of the road surface."""
        gy = y + int(h * 0.74)
        rl.draw_rectangle_gradient_v(x, y, w, gy - y, rl.Color(120, 175, 225, 255), rl.Color(215, 225, 235, 255))
        for hx, hh, hw in self.hills:
            cx = x + ((hx - scroll * 0.01) % 1.2 - 0.1) * w
            rl.draw_triangle(rl.Vector2(cx - hw * w, gy), rl.Vector2(cx + hw * w, gy), rl.Vector2(cx, gy - hh * h), rl.Color(120, 150, 130, 255))
        for hx, hh, hw, k in self.houses:
            cx = x + ((hx - scroll * 0.03) % 1.2 - 0.1) * w
            col = [(185, 160, 140), (170, 175, 185), (200, 190, 150), (160, 140, 130)][k]
            bw, bh = int(hw * w), int(hh * h)
            rl.draw_rectangle(int(cx), gy - bh, bw, bh, _c(col))
            for wy in range(gy - bh + 8, gy - 12, 18):
                for wx in range(int(cx) + 6, int(cx) + bw - 10, 16):
                    rl.draw_rectangle(wx, wy, 7, 9, rl.Color(240, 235, 170, 200) if (wx + wy) % 3 else rl.Color(70, 85, 100, 255))
        rl.draw_rectangle(x, gy, w, int(h * 0.05), rl.Color(150, 150, 155, 255))              # pavement
        ry = gy + int(h * 0.05)
        rl.draw_rectangle(x, ry, w, y + h - ry, rl.Color(58, 60, 66, 255))                    # road
        dash = int(w * 0.07)
        off = int((scroll * w * 0.9) % (dash * 2))
        for dx in range(-dash * 2, w + dash * 2, dash * 2):
            rl.draw_rectangle(x + dx - off, ry + int((y + h - ry) * 0.55), dash, 5, rl.Color(230, 230, 235, 255))
        return ry + int((y + h - ry) * 0.5)

    def _car(self, i, cx, base, s, col, now):
        """Side view, drawn around centre cx with the wheels on y=base (px); s = pixels per metre."""
        Ln, Wd, y0, belt, roof = vehicles.DIMS[i]
        style = vehicles.STYLE[i]
        ex = vehicles.EXTRA[i]
        bw = Ln * s
        x = cx - bw / 2
        wr = max(5, 0.36 * s)
        yb = base - 0.28 * s                                       # body bottom
        top = base - roof * s
        beltY = base - belt * s
        body = _c(col)
        dark = _c([c * 0.55 for c in col])
        rl.draw_ellipse(int(cx), int(base + 2), bw * 0.55, 6, rl.Color(0, 0, 0, 90))
        rl.draw_rectangle_rounded(rl.Rectangle(x, beltY, bw, yb - beltY + 0.2 * s), 0.25, 6, body)
        cab0, cab1 = (0.12, 0.78) if style in ("hatch", "mini", "wagon") else (0.22, 0.7)
        if style in ("van", "bus", "truck"):
            cab0, cab1 = 0.04, 0.96 if style == "bus" else 0.5
        if style == "tractor":
            cab0, cab1 = 0.45, 0.8
        if style == "pickup":
            cab0, cab1 = 0.12, 0.5
        a, b = x + bw * cab0, x + bw * cab1
        sl = (b - a) * 0.16
        if style in ("bus", "van") and style != "truck":
            rl.draw_rectangle_rounded(rl.Rectangle(a, top, b - a, beltY - top + 4), 0.15, 6, body)
            n = max(1, int((b - a) / (1.5 * s)))
            for k in range(n):
                rl.draw_rectangle(int(a + 6 + k * (b - a - 12) / n), int(top + 0.15 * s), int((b - a - 12) / n - 5), int(max(6, beltY - top - 0.35 * s)), rl.Color(150, 195, 225, 255))
        else:
            rl.draw_triangle(rl.Vector2(a, beltY), rl.Vector2(a + sl, top), rl.Vector2(a + sl, beltY), body)
            rl.draw_rectangle(int(a + sl), int(top), int(b - a - 2 * sl), int(beltY - top), body)
            rl.draw_triangle(rl.Vector2(b - sl, beltY), rl.Vector2(b - sl, top), rl.Vector2(b, beltY), body)
            glass = rl.Color(150, 195, 225, 255)
            rl.draw_rectangle(int(a + sl + 3), int(top + 4), int(b - a - 2 * sl - 6), int(max(4, beltY - top - 6)), glass)
            rl.draw_line(int((a + b) / 2), int(top + 4), int((a + b) / 2), int(beltY - 2), dark)
        if ex in ("roofload",):
            rl.draw_rectangle(int(a + sl), int(top - 0.35 * s), int(b - a - 2 * sl), int(0.35 * s), rl.Color(160, 120, 70, 255))
        if ex == "police":
            rl.draw_rectangle(int(cx - 0.3 * s), int(top - 6), int(0.6 * s), 6, rl.Color(60, 90, 255, 255) if int(now * 6) % 2 else rl.RED)
        if ex in ("taxi",) or style == "taxi":
            rl.draw_rectangle(int(cx - 0.25 * s), int(top - 8), int(0.5 * s), 8, rl.Color(250, 230, 120, 255))
        if ex == "ambulance":
            rl.draw_rectangle(int(cx - 0.6 * s), int(beltY + 0.05 * s), int(1.2 * s), int(0.3 * s), rl.RED)
        rl.draw_rectangle(int(x + bw - 8), int(beltY + 0.18 * s), 8, 7, rl.Color(250, 240, 170, 255))      # headlight (front is right)
        rl.draw_rectangle(int(x), int(beltY + 0.18 * s), 6, 7, rl.Color(200, 40, 40, 255))
        for fx in (0.22, 0.76):
            wx = x + bw * fx
            rl.draw_circle(int(wx), int(base - wr), wr, rl.Color(20, 20, 22, 255))
            rl.draw_circle(int(wx), int(base - wr), wr * 0.5, rl.Color(170, 172, 178, 255))
            ang = now * 9
            rl.draw_line(int(wx), int(base - wr), int(wx + math.cos(ang) * wr * 0.5), int(base - wr + math.sin(ang) * wr * 0.5), dark)

    # ------------------------------------------------------------------ main
    def draw(self, x, y, w, h):
        now = self.now_fn()
        if self.cur is None or now - self.cur["t0"] > self.cur["secs"]:
            self._next(now)
        c = self.cur
        t = (now - c["t0"]) / c["secs"]
        sh = int(h * 0.62)
        rl.begin_scissor_mode(int(x), int(y), int(w), int(h))
        rl.draw_rectangle(int(x), int(y), int(w), int(h), rl.Color(24, 27, 34, 255))
        base = self._street(x, y, w, sh, now * 0.11)
        if c["kind"] == "car":
            u = t - 0.5
            f = 0.3 * (2 * u) + 0.7 * (2 * u) ** 3
            cx = x + w * (0.5 + 0.95 * f)
            s = min(w / 8.5, w * 0.62 / vehicles.DIMS[c["i"]][0])
            bob = math.sin(now * 14) * 1.2
            self._car(c["i"], cx, base + bob, s, c["col"], now)
            tag = f"{L_CARS}  {c['k']}/{vehicles.N}"
            name = vehicles.NAMES[c["i"]]
        else:
            self._chars_scene(c, t, x, y, w, sh, base, now)
            tag = L_CHARS
            name = characters.LIKOVI[c["i"]][1]
        # ---- caption area
        cy = y + sh + 12
        font.draw_text(tag, int(x + 14), int(cy), 14, rl.Color(150, 154, 165, 255), bold=True)
        cy += 24
        a = int(255 * min(1.0, t * 6, (1.0 - t) * 6))
        for ln in font.wrap(name, 24, int(w - 28), True)[:2]:
            font.draw_text(ln, int(x + 14), int(cy), 24, rl.Color(240, 200, 60, a), bold=True)
            cy += 30
        cy += 4
        sub = c["text"] if c["kind"] == "car" else characters.LIKOVI[c["i"]][2]
        for ln in font.wrap(sub, 20 if c["kind"] == "car" else 16, int(w - 28))[:4]:
            font.draw_text(ln, int(x + 14), int(cy), 20 if c["kind"] == "car" else 16, rl.Color(235, 235, 235, a))
            cy += 26 if c["kind"] == "car" else 21
        rl.end_scissor_mode()
        rl.draw_rectangle_lines(int(x), int(y), int(w), int(h), rl.Color(90, 92, 98, 255))

    def _chars_scene(self, c, t, x, y, w, sh, base, now):
        ph = int(sh * 0.86)
        slide = min(1.0, t * 5) * (1.0 - max(0.0, (t - 0.9) * 10))
        tex = self._texture(c["i"])
        px = x + int(w * 0.06) - int((1.0 - slide) * w * 0.4)
        py = y + sh - ph - 6 + int(math.sin(now * 3.2) * 3)
        if tex:
            sc = ph / tex.height
            pw = int(tex.width * sc)
            poster_mod.draw_fit(tex, px, py, pw, ph)
        else:
            pw = int(ph * 0.6)
            rl.draw_circle(px + pw // 2, py + ph // 2, ph // 3, rl.Color(120, 90, 60, 255))
        # speech bubble (the words themselves are in the caption below)
        bx, by, bw_, bh_ = px + pw + 22, py + int(ph * 0.08), int(w - pw - int(w * 0.06) - 36), int(ph * 0.5)
        if bw_ > 60:
            a = int(255 * slide)
            rl.draw_rectangle_rounded(rl.Rectangle(bx, by, bw_, bh_), 0.3, 8, rl.Color(250, 250, 245, a))
            rl.draw_triangle(rl.Vector2(bx, by + bh_ * 0.6), rl.Vector2(bx + 18, by + bh_ * 0.45), rl.Vector2(bx + 18, by + bh_ * 0.75), rl.Color(250, 250, 245, a))
            words = c["text"][:int(len(c["text"]) * min(1.0, t / 0.4 + 0.01))]
            ty = by + 12
            for ln in font.wrap(words, 20, bw_ - 32)[:6]:
                font.draw_text(ln, bx + 16, ty, 20, rl.Color(30, 30, 40, a), bold=True)
                ty += 25

L_CARS = "ВОЗИЛА"
L_CHARS = "ЛИКОВИ"
