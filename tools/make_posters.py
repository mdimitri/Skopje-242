"""Draws the loading-screen posters (flat retro style, Pillow only) and writes assets/posters/posters.json.

Run once by the developer:  python tools/make_posters.py      (the game itself only loads the PNG files)
Each poster illustrates one joke; the Macedonian text of the joke is the caption the game shows beside it.
Facts the jokes lean on are listed in docs/TEXT_SOURCES.md.  Pillow is the only dependency."""
import json
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "posters")
FB = os.path.join(ROOT, "assets", "fonts", "DejaVuSans-Bold.ttf")
S = 2                                   # supersampling
W, H = 960, 600

INK = (24, 26, 40)
NAVY = (36, 40, 66)
PLUM = (92, 58, 110)
ROSE = (214, 98, 96)
ORANGE = (244, 150, 72)
SAND = (248, 214, 140)
CREAM = (250, 238, 206)
GOLD = (240, 200, 60)
TEAL = (62, 140, 150)
GREEN = (92, 150, 96)
BRICK = (170, 74, 58)
STONE = (186, 176, 154)
SMOG = (176, 166, 160)


class P:
    """Tiny drawing helper: coordinates are poster pixels (960x600), drawn at S times the size."""

    def __init__(self, top=ORANGE, bottom=PLUM, size=(W, H)):
        self.w, self.h = size
        self.im = Image.new("RGB", (self.w * S, self.h * S))
        self.d = ImageDraw.Draw(self.im)
        self.gradient(top, bottom)

    def gradient(self, top, bottom, y0=0, y1=None):
        y1 = self.h if y1 is None else y1
        for y in range(int(y0 * S), int(y1 * S)):
            t = (y - y0 * S) / max(1, (y1 - y0) * S)
            self.d.line([(0, y), (self.w * S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))

    def _p(self, pts):
        return [(x * S, y * S) for x, y in pts]

    def poly(self, pts, fill, outline=None):
        self.d.polygon(self._p(pts), fill=fill, outline=outline)

    def rect(self, x0, y0, x1, y1, fill, r=0):
        if r:
            self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S, fill=fill)
        else:
            self.d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)

    def ell(self, x0, y0, x1, y1, fill, outline=None, width=1):
        self.d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill, outline=outline, width=width * S)

    def circ(self, cx, cy, r, fill, outline=None, width=1):
        self.ell(cx - r, cy - r, cx + r, cy + r, fill, outline, width)

    def line(self, pts, fill, width=2):
        self.d.line(self._p(pts), fill=fill, width=int(width * S), joint="curve")

    def arc(self, box, a0, a1, fill, width=2):
        self.d.arc([v * S for v in box], a0, a1, fill=fill, width=int(width * S))

    def text(self, x, y, s, size, fill, anchor="la"):
        self.d.text((x * S, y * S), s, font=ImageFont.truetype(FB, int(size * S)), fill=fill, anchor=anchor)

    def haze(self, col, alpha, y0, y1, top_alpha=0):
        """Vertical fog band: alpha grows from top_alpha at y0 to alpha at y1."""
        ov = Image.new("RGBA", self.im.size, col + (0,))
        od = ImageDraw.Draw(ov)
        for y in range(int(y0 * S), int(y1 * S)):
            t = (y - y0 * S) / max(1, (y1 - y0) * S)
            od.line([(0, y), (self.w * S, y)], fill=col + (int(top_alpha + (alpha - top_alpha) * t),))
        self.im = Image.alpha_composite(self.im.convert("RGBA"), ov).convert("RGB")
        self.d = ImageDraw.Draw(self.im)

    def glow(self, cx, cy, r, col, alpha=120):
        ov = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(ov).ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=col + (alpha,))
        ov = ov.filter(ImageFilter.GaussianBlur(r * S / 3))
        self.im = Image.alpha_composite(self.im.convert("RGBA"), ov).convert("RGB")
        self.d = ImageDraw.Draw(self.im)

    def save(self, path, seed=1):
        im = self.im.resize((self.w, self.h), Image.LANCZOS)
        rnd = random.Random(seed)
        noise = Image.effect_noise((self.w, self.h), 12).convert("RGB")      # film grain
        im = ImageChops.add(im, ImageChops.subtract(noise, Image.new("RGB", noise.size, (128, 128, 128))), 1.0, 0)
        vig = Image.new("L", (self.w, self.h), 0)
        vd = ImageDraw.Draw(vig)
        vd.ellipse([-self.w * 0.15, -self.h * 0.25, self.w * 1.15, self.h * 1.25], fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(70))
        im = Image.composite(im, Image.new("RGB", im.size, (10, 10, 18)), vig.point(lambda v: 160 + v * 95 // 255))
        rnd.random()
        im.save(path, optimize=True)


# ------------------------------------------------------------------------------------------ building blocks
def sun(p, cx, cy, r, col=SAND, rays=0):
    p.glow(cx, cy, r * 2.2, col, 90)
    p.circ(cx, cy, r, col)
    for i in range(rays):
        a = i * 2 * math.pi / rays
        p.line([(cx + math.cos(a) * r * 1.2, cy + math.sin(a) * r * 1.2), (cx + math.cos(a) * r * 1.6, cy + math.sin(a) * r * 1.6)], col, 3)


def mountain(p, base, peak_x, peak_y, width, col):
    p.poly([(peak_x - width, base), (peak_x - width * 0.45, peak_y + (base - peak_y) * 0.35), (peak_x - width * 0.12, peak_y + 10),
            (peak_x, peak_y), (peak_x + width * 0.25, peak_y + (base - peak_y) * 0.22), (peak_x + width * 0.6, peak_y + (base - peak_y) * 0.55),
            (peak_x + width, base)], col)


def skyline(p, y, col, seed=1, x0=0, x1=W, hmin=40, hmax=150, wmin=26, wmax=62, windows=None):
    rnd = random.Random(seed)
    x = x0
    while x < x1:
        bw = rnd.randint(wmin, wmax)
        bh = rnd.randint(hmin, hmax)
        p.rect(x, y - bh, x + bw, y + 4, col)
        if windows:
            for wy in range(int(y - bh + 8), int(y - 6), 12):
                for wx in range(int(x + 5), int(x + bw - 8), 11):
                    if rnd.random() < 0.55:
                        p.rect(wx, wy, wx + 5, wy + 6, windows)
        x += bw + rnd.randint(0, 6)


def crane(p, x, base, h, col=INK, jib=120, flip=False):
    sgn = -1 if flip else 1
    p.rect(x - 4, base - h, x + 4, base, col)
    for i in range(0, h, 16):                                             # lattice
        p.line([(x - 4, base - i), (x + 4, base - i - 16)], col, 1.5)
        p.line([(x + 4, base - i), (x - 4, base - i - 16)], col, 1.5)
    top = base - h
    p.rect(min(x, x + sgn * jib), top - 6, max(x, x + sgn * jib), top, col)
    p.rect(min(x, x - sgn * 34), top - 6, max(x, x - sgn * 34), top + 6, col)
    p.poly([(x - 5, top - 6), (x + 5, top - 6), (x, top - 30)], col)
    p.line([(x, top - 30), (x + sgn * jib, top - 6)], col, 1.2)
    p.line([(x, top - 30), (x - sgn * 34, top - 6)], col, 1.2)
    hx = x + sgn * jib * 0.8
    p.line([(hx, top), (hx, top + h * 0.45)], col, 1.5)
    p.rect(hx - 7, top + h * 0.45, hx + 7, top + h * 0.45 + 8, col)


def river(p, y0, y1, col1, col2, seed=3):
    p.gradient(col1, col2, y0, y1)
    rnd = random.Random(seed)
    for _ in range(40):
        x, y = rnd.randint(0, W), rnd.randint(int(y0) + 4, int(y1) - 2)
        p.line([(x, y), (x + rnd.randint(20, 60), y)], tuple(min(255, c + 40) for c in col1), 1.5)


def cloud(p, x, y, s=1.0, col=(255, 255, 255)):
    for dx, dy, r in ((0, 0, 22), (24, -8, 28), (52, 0, 22), (26, 6, 24)):
        p.circ(x + dx * s, y + dy * s, r * s, col)


def bridge_stone(p, y, x0, x1, arches=5, col=STONE, dark=(120, 112, 98)):
    p.rect(x0, y - 26, x1, y, col)
    p.rect(x0, y - 30, x1, y - 24, dark)
    aw = (x1 - x0) / arches
    for i in range(arches):
        cx = x0 + aw * (i + 0.5)
        r = aw * 0.38
        p.ell(cx - r, y - r * 0.5, cx + r, y + r * 1.5, dark)
        p.rect(cx - r, y + r * 0.5, cx + r, y + r * 1.6, dark)
    for i in range(arches + 1):                                           # piers
        p.rect(x0 + aw * i - 6, y, x0 + aw * i + 6, y + 44, col)


def burek(p, cx, cy, r=70):
    p.ell(cx - r * 1.1, cy - r * 0.35 + 8, cx + r * 1.1, cy + r * 0.45 + 8, (130, 90, 60))      # plate shadow
    p.ell(cx - r * 1.05, cy - r * 0.4, cx + r * 1.05, cy + r * 0.4, CREAM)
    for k in range(5, 0, -1):                                                                    # spiral
        rr = r * k / 5
        p.ell(cx - rr, cy - rr * 0.34 - (5 - k) * 1.5, cx + rr, cy + rr * 0.34 - (5 - k) * 1.5, (196, 130, 56) if k % 2 else (218, 160, 78))
    p.ell(cx - 10, cy - 8, cx + 10, cy + 4, (150, 96, 44))


def glass_yogurt(p, x, y, w=46, h=86):
    p.poly([(x, y), (x + w, y), (x + w - 6, y + h), (x + 6, y + h)], (236, 238, 242))
    p.poly([(x + 3, y + 14), (x + w - 3, y + 14), (x + w - 7, y + h - 3), (x + 7, y + h - 3)], (255, 255, 255))
    p.line([(x + 10, y + 20), (x + 14, y + h - 12)], (214, 218, 226), 3)


def car(p, x, y, col, s=1.0, tilt=0.0):
    p.rect(x, y - 24 * s, x + 110 * s, y, col, 6)
    p.poly([(x + 22 * s, y - 24 * s), (x + 40 * s, y - 44 * s), (x + 82 * s, y - 44 * s), (x + 98 * s, y - 24 * s)], col)
    p.poly([(x + 30 * s, y - 26 * s), (x + 44 * s, y - 40 * s), (x + 60 * s, y - 40 * s), (x + 60 * s, y - 26 * s)], (200, 228, 240))
    p.poly([(x + 64 * s, y - 26 * s), (x + 64 * s, y - 40 * s), (x + 80 * s, y - 40 * s), (x + 91 * s, y - 26 * s)], (200, 228, 240))
    for wx in (x + 26 * s, x + 86 * s):
        p.circ(wx, y + 1 * s, 11 * s, INK)
        p.circ(wx, y + 1 * s, 5 * s, (150, 150, 160))


def person(p, x, y, col, s=1.0, step=0):
    p.circ(x, y - 46 * s, 7 * s, (230, 190, 150))
    p.rect(x - 7 * s, y - 38 * s, x + 7 * s, y - 14 * s, col, 3)
    p.line([(x - 3 * s, y - 14 * s), (x - 3 * s - step, y)], INK, 3 * s)
    p.line([(x + 3 * s, y - 14 * s), (x + 3 * s + step, y)], INK, 3 * s)


def pigeon(p, x, y, s=1.0, col=(150, 156, 172)):
    p.ell(x - 18 * s, y - 10 * s, x + 14 * s, y + 10 * s, col)
    p.circ(x + 15 * s, y - 10 * s, 7 * s, col)
    p.poly([(x + 21 * s, y - 11 * s), (x + 29 * s, y - 9 * s), (x + 21 * s, y - 7 * s)], (230, 170, 60))
    p.circ(x + 17 * s, y - 12 * s, 1.6 * s, INK)
    p.poly([(x - 16 * s, y - 2 * s), (x - 34 * s, y + 6 * s), (x - 14 * s, y + 8 * s)], tuple(c - 25 for c in col))
    p.line([(x - 2 * s, y + 10 * s), (x - 2 * s, y + 18 * s)], (230, 140, 90), 2)
    p.line([(x + 6 * s, y + 10 * s), (x + 6 * s, y + 18 * s)], (230, 140, 90), 2)


def statue_horse(p, x, y, s=1.0, col=(196, 152, 70)):
    """Rider on a rearing horse (silhouette) with its feet at (x, y)."""
    p.ell(x - 34 * s, y - 70 * s, x + 26 * s, y - 36 * s, col)                                  # body
    p.poly([(x + 10 * s, y - 62 * s), (x + 34 * s, y - 100 * s), (x + 46 * s, y - 94 * s), (x + 30 * s, y - 50 * s)], col)  # neck
    p.poly([(x + 34 * s, y - 100 * s), (x + 58 * s, y - 92 * s), (x + 56 * s, y - 84 * s), (x + 40 * s, y - 86 * s)], col)  # head
    p.poly([(x + 20 * s, y - 46 * s), (x + 50 * s, y - 62 * s), (x + 54 * s, y - 56 * s), (x + 28 * s, y - 36 * s)], col)    # front leg up
    p.poly([(x + 8 * s, y - 40 * s), (x + 24 * s, y - 14 * s), (x + 30 * s, y - 18 * s), (x + 20 * s, y - 42 * s)], col)
    p.poly([(x - 28 * s, y - 44 * s), (x - 30 * s, y - 2 * s), (x - 22 * s, y - 2 * s), (x - 16 * s, y - 40 * s)], col)    # hind legs
    p.poly([(x - 34 * s, y - 56 * s), (x - 56 * s, y - 38 * s), (x - 54 * s, y - 30 * s), (x - 30 * s, y - 46 * s)], col)    # tail
    p.rect(x - 8 * s, y - 100 * s, x + 6 * s, y - 68 * s, col, 3)                               # rider
    p.circ(x - 1 * s, y - 108 * s, 8 * s, col)
    p.line([(x + 4 * s, y - 92 * s), (x + 34 * s, y - 130 * s)], col, 3 * s)                    # raised arm
    p.line([(x + 34 * s, y - 130 * s), (x + 34 * s, y - 70 * s)], col, 2 * s)                   # spear


def cross(p, x, y, h, col=(236, 236, 240)):
    p.rect(x - h * 0.05, y - h, x + h * 0.05, y, col)
    p.rect(x - h * 0.3, y - h * 0.75, x + h * 0.3, y - h * 0.65, col)


def lion(p, cx, cy, s=1.0):
    mane = (130, 84, 40)
    for i in range(16):
        a = i * math.pi / 8
        p.poly([(cx + math.cos(a - 0.2) * 40 * s, cy + math.sin(a - 0.2) * 40 * s), (cx + math.cos(a) * 62 * s, cy + math.sin(a) * 62 * s),
                (cx + math.cos(a + 0.2) * 40 * s, cy + math.sin(a + 0.2) * 40 * s)], mane)
    p.circ(cx, cy, 44 * s, (150, 96, 46))
    p.circ(cx, cy + 4 * s, 30 * s, (214, 166, 92))
    p.ell(cx - 11 * s, cy - 2 * s, cx + 11 * s, cy + 12 * s, (90, 56, 40))
    p.circ(cx - 15 * s, cy - 14 * s, 4 * s, INK)
    p.circ(cx + 15 * s, cy - 14 * s, 4 * s, INK)
    p.line([(cx, cy + 12 * s), (cx, cy + 24 * s)], INK, 2)
    p.arc((cx - 14 * s, cy + 14 * s, cx, cy + 30 * s), 0, 180, INK, 2)
    p.arc((cx, cy + 14 * s, cx + 14 * s, cy + 30 * s), 0, 180, INK, 2)


def speech(p, x, y, w, h, s, size=26, tail=(0, 0)):
    p.rect(x, y, x + w, y + h, (255, 255, 255), 14)
    p.poly([(x + w * 0.3, y + h - 2), (x + w * 0.3 + 18, y + h - 2), (x + w * 0.3 + tail[0], y + h + tail[1])], (255, 255, 255))
    p.text(x + w / 2, y + h / 2, s, size, INK, "mm")


def clock_face(p, cx, cy, r, hour=5, minute=17, col=CREAM):
    p.circ(cx, cy, r + 8, INK)
    p.circ(cx, cy, r, col)
    for i in range(12):
        a = math.radians(i * 30 - 90)
        p.line([(cx + math.cos(a) * r * 0.86, cy + math.sin(a) * r * 0.86), (cx + math.cos(a) * r * 0.97, cy + math.sin(a) * r * 0.97)], INK, 3)
    ha = math.radians((hour % 12 + minute / 60) * 30 - 90)
    ma = math.radians(minute * 6 - 90)
    p.line([(cx, cy), (cx + math.cos(ha) * r * 0.52, cy + math.sin(ha) * r * 0.52)], INK, 6)
    p.line([(cx, cy), (cx + math.cos(ma) * r * 0.82, cy + math.sin(ma) * r * 0.82)], INK, 4)
    p.circ(cx, cy, 6, BRICK)


def tree(p, x, y, s=1.0, col=GREEN):
    p.rect(x - 3 * s, y - 20 * s, x + 3 * s, y, (90, 64, 46))
    p.circ(x, y - 32 * s, 18 * s, col)
    p.circ(x - 11 * s, y - 24 * s, 12 * s, col)
    p.circ(x + 11 * s, y - 24 * s, 12 * s, col)


def hill(p, y, col, amp=40, seed=2, x0=0, x1=W):
    rnd = random.Random(seed)
    pts = [(x0, p.h)]
    ph = [rnd.random() * 6 for _ in range(3)]
    for x in range(x0, x1 + 1, 12):
        pts.append((x, y - amp * (0.5 + 0.3 * math.sin(x / 130 + ph[0]) + 0.2 * math.sin(x / 57 + ph[1]))))
    pts.append((x1, p.h))
    p.poly(pts, col)


# ------------------------------------------------------------------------------------------ the posters
def p_clock():
    p = P((60, 52, 96), (214, 110, 90))
    sun(p, 780, 190, 56, SAND)
    skyline(p, 430, (46, 40, 78), 3, hmin=60, hmax=190, windows=(250, 214, 120))
    crane(p, 130, 430, 280, INK, 150)
    crane(p, 840, 430, 230, INK, 120, flip=True)
    p.rect(0, 430, W, H, (38, 34, 52))
    p.rect(260, 220, 700, 440, STONE)                                    # the ruined station
    p.poly([(260, 220), (700, 220), (640, 180), (320, 180)], (150, 140, 124))
    p.poly([(560, 220), (700, 220), (700, 440), (610, 440), (640, 330)], (38, 34, 52))   # broken corner
    for i in range(5):
        p.rect(290 + i * 60, 270, 320 + i * 60, 340, (40, 36, 54))
    clock_face(p, 480, 250, 78)
    p.text(480, 500, "5:17", 70, GOLD, "mm")
    p.save(os.path.join(OUT, "clock.png"), 1)


def p_lions():
    p = P((250, 170, 100), (140, 70, 100))
    sun(p, 480, 250, 80, SAND, 24)
    hill(p, 380, (120, 60, 96), 60, 4)
    bridge_stone(p, 430, 40, 920, 6)
    river(p, 474, H, (60, 100, 130), (30, 50, 90))
    for x in (130, 830):
        p.rect(x - 38, 336, x + 38, 408, STONE)
        lion(p, x, 296, 0.95)
    speech(p, 300, 70, 360, 70, "Хакуна матата!", 34, (-40, 36))
    # Timon (meerkat, upright) and Pumbaa (warthog) on the bridge rail between the lions
    p.ell(352, 352, 388, 412, (196, 150, 98))
    p.circ(370, 338, 16, (206, 160, 106))
    p.circ(364, 334, 4, INK)
    p.circ(376, 334, 4, INK)
    p.ell(364, 342, 376, 350, (90, 60, 44))
    p.line([(352, 372), (338, 388)], (196, 150, 98), 6)
    p.line([(388, 372), (402, 388)], (196, 150, 98), 6)
    p.ell(560, 372, 660, 408, (120, 96, 90))
    p.circ(668, 380, 18, (130, 104, 98))
    p.poly([(676, 388), (700, 394), (678, 398)], (120, 96, 90))
    p.poly([(668, 392), (682, 378), (674, 396)], (240, 236, 220))
    p.circ(664, 374, 3.5, INK)
    p.poly([(560, 380), (544, 366), (566, 376)], (90, 70, 66))
    p.rect(572, 404, 584, 418, (120, 96, 90))
    p.rect(640, 404, 652, 418, (120, 96, 90))
    p.save(os.path.join(OUT, "lions.png"), 2)


def p_warrior():
    p = P((255, 196, 120), (150, 86, 100))
    sun(p, 200, 150, 50, SAND, 18)
    skyline(p, 400, (120, 74, 104), 5, hmin=40, hmax=130)
    p.rect(0, 400, W, H, (210, 190, 160))
    p.ell(300, 470, 660, 560, (96, 160, 190))                            # fountain basin
    p.ell(316, 478, 644, 548, (130, 196, 220))
    p.rect(450, 230, 510, 500, STONE)                                    # column
    p.rect(430, 220, 530, 240, (150, 140, 120))
    statue_horse(p, 480, 222, 1.15)
    p.rect(150, 90, 400, 160, CREAM, 6)                                  # museum-style label
    p.text(275, 114, "Воин на коњ", 30, INK, "mm")
    p.text(275, 142, "(и сите знаат кој е)", 16, BRICK, "mm")
    for x in (120, 800, 860):
        person(p, x, 560, (80, 100, 140), 1.2)
    p.save(os.path.join(OUT, "warrior.png"), 3)


def p_smog():
    p = P((190, 182, 176), (120, 112, 112))
    mountain(p, 420, 700, 130, 520, (150, 144, 148))
    cross(p, 700, 150, 60, (200, 196, 200))
    skyline(p, 470, (92, 86, 96), 6, hmin=50, hmax=170, windows=(210, 190, 120))
    p.haze((190, 180, 172), 235, 120, 480, 120)
    skyline(p, 520, (60, 56, 70), 9, hmin=40, hmax=120, windows=(240, 210, 120))
    p.rect(0, 520, W, H, (52, 48, 60))
    for x in (120, 340, 600):
        p.circ(x, 120, 24, (222, 216, 200))                              # the sun trying its best
    p.haze((200, 192, 184), 120, 0, 400)
    p.text(480, 560, "ВИДЛИВОСТ: 20 м", 36, GOLD, "mm")
    p.save(os.path.join(OUT, "smog.png"), 4)


def p_burek():
    p = P((250, 190, 110), (170, 90, 80))
    p.rect(0, 400, W, H, (140, 90, 70))
    for i in range(0, W, 120):
        p.rect(i, 400, i + 60, H, (150, 98, 76))
    burek(p, 420, 430, 120)
    glass_yogurt(p, 600, 360, 70, 130)
    bridge_stone(p, 270, 40, 920, 7, (220, 196, 150), (170, 140, 100))
    p.text(480, 60, "бурек", 70, CREAM, "mm")
    p.text(560, 570, "+ јогурт", 32, CREAM, "mm")
    p.save(os.path.join(OUT, "burek.png"), 5)


def p_kale():
    p = P((70, 60, 110), (240, 140, 90))
    sun(p, 480, 330, 70, SAND)
    hill(p, 400, (80, 60, 96), 60, 7)
    skyline(p, 520, (36, 32, 56), 11, hmin=40, hmax=140, windows=(250, 210, 110))
    p.rect(0, 520, W, H, (30, 28, 44))
    p.rect(300, 250, 660, 420, (120, 100, 90))                           # fortress wall
    for i in range(300, 660, 28):
        p.rect(i, 232, i + 16, 252, (120, 100, 90))
    for x in (330, 480, 640):
        p.rect(x - 22, 190, x + 22, 420, (136, 112, 98))
        for i in range(-22, 22, 14):
            p.rect(x + i, 172, x + i + 8, 192, (136, 112, 98))
    crane(p, 770, 430, 250, INK, 120, flip=True)
    p.save(os.path.join(OUT, "kale.png"), 6)


def p_vardar():
    p = P((120, 190, 210), (240, 220, 170))
    sun(p, 780, 150, 46, (255, 244, 200))
    hill(p, 330, (98, 150, 120), 50, 12)
    skyline(p, 360, (150, 130, 130), 13, hmin=30, hmax=100)
    river(p, 360, H, (70, 150, 190), (30, 80, 130))
    p.rect(0, 336, W, 372, (205, 190, 160))
    p.line([(0, 372), (W, 372)], (120, 110, 90), 3)
    for x in (80, 240, 600, 820):
        tree(p, x, 336, 1.4)
    p.poly([(120, 520), (180, 500), (260, 500), (300, 520), (260, 540), (180, 540)], (230, 130, 70))      # a small boat on the plan
    p.line([(212, 500), (212, 450)], INK, 3)
    p.poly([(212, 450), (212, 490), (250, 490)], CREAM)
    p.save(os.path.join(OUT, "vardar.png"), 7)


def p_parking():
    p = P((200, 220, 240), (240, 200, 160))
    skyline(p, 330, (140, 130, 150), 14, hmin=60, hmax=180, windows=(255, 230, 150))
    p.rect(0, 330, W, 400, (190, 184, 176))                              # pavement
    for i in range(0, W, 80):
        p.line([(i, 330), (i, 400)], (170, 164, 156), 2)
    p.rect(0, 400, W, H, (74, 74, 84))                                   # road
    for i in range(0, W, 140):
        p.rect(i, 490, i + 70, 498, CREAM)
    car(p, 300, 394, (220, 70, 60), 2.0)
    p.rect(120, 220, 126, 400, INK)                                      # "P" sign
    p.rect(80, 190, 166, 250, (40, 90, 200), 6)
    p.text(123, 220, "P", 48, (255, 255, 255), "mm")
    speech(p, 560, 120, 330, 66, "Само пет минути!", 30, (-20, 40))
    car(p, 700, 530, (240, 200, 60), 1.4)
    p.save(os.path.join(OUT, "parking.png"), 8)


def p_coffee():
    p = P((60, 44, 56), (140, 80, 70))
    p.rect(0, 420, W, H, (86, 56, 52))
    crane(p, 760, 420, 330, (20, 18, 24), 160, flip=True)
    p.ell(300, 380, 560, 440, (210, 200, 190))                            # saucer
    p.rect(330, 290, 530, 410, CREAM, 18)                                 # cup
    p.arc((510, 310, 590, 390), -90, 90, CREAM, 14)
    p.ell(334, 288, 526, 322, (70, 40, 30))
    for k, dx in enumerate((-30, 10, 50)):
        p.line([(400 + dx, 270), (390 + dx, 240), (410 + dx, 210), (398 + dx, 180)], (230, 220, 214), 5)
    clock_face(p, 180, 190, 70)
    p.text(180, 290, "∞", 70, GOLD, "mm")
    p.save(os.path.join(OUT, "coffee.png"), 9)


def p_tavce():
    p = P((250, 200, 130), (176, 96, 70))
    p.rect(0, 380, W, H, (120, 76, 60))
    p.ell(220, 330, 740, 470, (150, 70, 46))                              # earthenware dish
    p.ell(236, 340, 724, 450, (206, 120, 60))
    rnd = random.Random(21)
    for _ in range(90):
        x, y = rnd.randint(260, 700), rnd.randint(352, 436)
        if ((x - 480) / 230) ** 2 + ((y - 395) / 50) ** 2 < 1:
            p.ell(x - 7, y - 4, x + 7, y + 4, (240, 232, 214), (150, 130, 100))
    for x in (300, 420, 560, 660):
        p.circ(x, 394 + (x % 7), 9, (200, 60, 40))
    p.rect(700, 360, 880, 380, (150, 100, 70), 6)                         # handle
    p.rect(300, 90, 660, 150, CREAM, 8)
    p.text(480, 120, "ПЛАНИРАНО: 20 мин", 28, INK, "mm")
    p.text(480, 200, "ГОТОВО: 20 мин", 34, GREEN, "mm")
    for dx in (-80, 0, 80):
        p.line([(480 + dx, 320), (470 + dx, 290), (490 + dx, 262)], (250, 240, 230), 5)
    p.save(os.path.join(OUT, "tavce.png"), 10)


def p_cross():
    p = P((90, 140, 200), (250, 220, 170))
    sun(p, 200, 130, 46, (255, 244, 210))
    mountain(p, 440, 560, 170, 640, (86, 120, 110))
    mountain(p, 440, 260, 260, 420, (110, 146, 126))
    cross(p, 560, 190, 120, (250, 250, 252))
    p.glow(560, 150, 80, (255, 250, 220), 70)
    skyline(p, 500, (110, 100, 124), 15, hmin=30, hmax=100)
    p.rect(0, 500, W, H, (70, 66, 80))
    for x in range(60, 900, 150):
        cloud(p, x, 60 + (x % 5) * 8, 0.8)
    p.haze((200, 190, 184), 150, 300, 500, 0)
    p.text(480, 560, "Милениумски крст", 28, CREAM, "mm")
    p.save(os.path.join(OUT, "cross.png"), 11)


def p_ajvar():
    p = P((230, 120, 90), (110, 50, 70))
    p.rect(0, 410, W, H, (90, 56, 50))
    for x in (300, 480, 660):
        p.rect(x - 70, 250, x + 70, 420, (190, 40, 30), 22)
        p.rect(x - 80, 226, x + 80, 262, (210, 180, 90), 10)
        p.rect(x - 58, 300, x + 58, 372, CREAM, 8)
        p.text(x, 336, "ајвар", 30, BRICK, "mm")
        p.line([(x - 56, 270), (x - 56, 400)], (240, 120, 100), 5)
    for x in range(80, 900, 150):                                         # peppers
        p.ell(x - 22, 470, x + 22, 540, (210, 50, 36))
        p.line([(x, 470), (x + 6, 450)], GREEN, 5)
    p.text(480, 80, "есен → пролет", 46, CREAM, "mm")
    p.text(480, 150, "ветувања → ∞", 46, GOLD, "mm")
    p.save(os.path.join(OUT, "ajvar.png"), 12)


def p_bridge():
    p = P((250, 214, 150), (120, 90, 120))
    sun(p, 480, 240, 64, (255, 240, 200), 20)
    hill(p, 330, (110, 94, 120), 40, 5)
    skyline(p, 360, (150, 116, 130), 16, hmin=30, hmax=100)
    river(p, 440, H, (96, 130, 160), (50, 76, 118))
    bridge_stone(p, 420, 20, 940, 7, STONE, (110, 102, 92))
    p.text(480, 560, "XV век", 40, CREAM, "mm")
    for x, c in ((220, (120, 60, 60)), (420, (70, 100, 150)), (700, (80, 130, 90))):
        person(p, x, 394, c, 1.0, 5)
    p.save(os.path.join(OUT, "bridge.png"), 13)


def p_pigeon():
    p = P((140, 190, 230), (250, 226, 190))
    cloud(p, 160, 90, 1.2)
    cloud(p, 700, 140, 1.0)
    p.rect(0, 470, W, H, (210, 196, 170))
    for i in range(0, W, 90):
        p.rect(i, 470, i + 45, H, (200, 186, 160))
    p.rect(420, 230, 540, 480, STONE)
    p.rect(396, 214, 564, 240, (150, 140, 124))
    statue_horse(p, 480, 216, 1.3)
    for x, y, s, f in ((420, 140, 1.4, 1), (580, 230, 1.2, 1), (340, 520, 1.5, 1), (620, 540, 1.3, 1), (180, 500, 1.2, 1), (780, 510, 1.6, 1)):
        pigeon(p, x, y, s * f)
    p.rect(120, 330, 300, 400, CREAM, 6)
    p.text(210, 352, "ГРАДЕЖНА ДОЗВОЛА", 15, INK, "mm")
    p.text(210, 380, "не е потребна", 18, BRICK, "mm")
    p.save(os.path.join(OUT, "pigeons.png"), 14)


def p_permit():
    p = P((70, 90, 130), (180, 150, 130))
    p.rect(0, 470, W, H, (96, 84, 80))
    p.rect(180, 80, 780, 500, CREAM, 8)                                   # a form
    for i in range(7):
        p.rect(220, 130 + i * 44, 740 - (i % 3) * 90, 138 + i * 44, (190, 184, 170))
    p.text(480, 104, "ГРАДЕЖНА ДОЗВОЛА", 28, INK, "mm")
    p.ell(560, 300, 800, 420, None, BRICK, 8)
    p.text(680, 360, "ВО ТЕК", 42, BRICK, "mm")
    p.line([(560, 300), (800, 420)], (0, 0, 0, 0), 1)
    # hourglass
    p.poly([(60, 140), (150, 140), (105, 230)], (240, 220, 160))
    p.poly([(60, 320), (150, 320), (105, 230)], (240, 220, 160))
    p.rect(50, 130, 160, 142, INK)
    p.rect(50, 318, 160, 330, INK)
    p.poly([(88, 316), (122, 316), (105, 280)], GOLD)
    crane(p, 860, 470, 300, INK, 110, flip=True)
    p.save(os.path.join(OUT, "permit.png"), 15)


def p_rush():
    p = P((250, 170, 110), (120, 70, 100))
    skyline(p, 300, (120, 80, 110), 17, hmin=60, hmax=180, windows=(255, 230, 150))
    p.rect(0, 300, W, 360, (190, 184, 176))
    p.rect(0, 360, W, H, (72, 72, 84))
    for i in range(0, W, 140):
        p.rect(i, 470, i + 70, 478, CREAM)
    cols = [(220, 70, 60), (60, 120, 200), (240, 200, 60), (100, 170, 100), (200, 200, 210), (170, 80, 160)]
    for i in range(6):
        car(p, 20 + i * 155, 450, cols[i], 1.0)
    for i in range(5):
        car(p, 60 + i * 175, 560, cols[(i + 2) % 6], 1.0)
    for i in range(7):                                                    # the pedestrian overtakes everybody
        person(p, 60 + i * 130, 335, (50, 60, 90), 1.15, 6 if i % 2 else -6)
    p.text(480, 60, "ШПИЦ", 70, GOLD, "mm")
    p.save(os.path.join(OUT, "rush.png"), 16)


def p_wedding():
    p = P((20, 22, 54), (84, 44, 100))
    for i in range(80):
        r = random.Random(i)
        p.circ(r.randint(0, W), r.randint(0, 260), r.choice((1, 1, 2)), (255, 250, 220))
    p.circ(820, 100, 34, (250, 244, 214))
    p.circ(836, 92, 30, (28, 28, 60))
    skyline(p, 400, (20, 20, 44), 18, hmin=60, hmax=170, windows=(250, 210, 110))
    p.rect(0, 400, W, H, (30, 28, 50))
    p.glow(480, 470, 260, (255, 190, 80), 80)
    p.poly([(250, 490), (350, 410), (390, 420), (290, 500)], (210, 150, 60))                       # zurla
    p.poly([(350, 410), (410, 396), (400, 440), (390, 420)], (230, 190, 90))
    p.ell(480, 440, 640, 540, (150, 80, 50))                                                        # tapan
    p.ell(480, 430, 640, 520, (240, 220, 180))
    p.line([(660, 430), (700, 400)], CREAM, 4)
    p.circ(706, 396, 9, CREAM)
    for x, y, c in ((140, 520, (200, 60, 90)), (760, 520, (60, 150, 200)), (860, 500, (230, 180, 60))):
        person(p, x, y, c, 1.5, 8)
    for x, y in ((420, 330), (520, 300), (600, 340), (350, 280)):
        p.text(x, y, "♪", 54, GOLD, "mm")
    p.save(os.path.join(OUT, "wedding.png"), 17)


# (file, drawing function, Macedonian caption = the joke)
POSTERS = [
    ("clock.png", p_clock, "Часовникот на старата железничка станица во Скопје е запрен на 5:17 од 1963 година. Градежните кранови, за разлика од него, не застануваат."),
    ("lions.png", p_lions, "Лавовите на мостот ги чекаат Тимон и Пумба. Хакуна матата, ортак!"),
    ("warrior.png", p_warrior, "Ајде бре, не прашувај кој е – официјално тоа е „Воин на коњ“."),
    ("smog.png", p_smog, "Зимата во Скопје: Водно постои, ветуваме – само не се гледа од смогот."),
    ("burek.png", p_burek, "Бурек без јогурт е како Вардар без Камен мост – може, ама нема смисла."),
    ("kale.png", p_kale, "Од Кале се гледа целиот град – и сѐ што сѐ уште не е завршено."),
    ("vardar.png", p_vardar, "Вардар е единствениот во Скопје што секогаш тече по план."),
    ("parking.png", p_parking, "„Само пет минути!“ – последни зборови пред паркирање на тротоар."),
    ("coffee.png", p_coffee, "Едно кафе во Скопје трае колку градежен проект: подолго од планираното."),
    ("tavce.png", p_tavce, "Тавче гравче – националното јадење и единствениот проект што секогаш се завршува навреме."),
    ("cross.png", p_cross, "Милениумскиот крст на Водно се гледа од секаде – освен кога го крие смогот."),
    ("ajvar.png", p_ajvar, "Ајварот се вари наесен и трае до пролет. Ветувањата траат уште подолго."),
    ("bridge.png", p_bridge, "Камен мост е постар од сите наши планови заедно."),
    ("pigeons.png", p_pigeon, "Гулабите на Плоштад не бараат градежна дозвола. Едноставно се качуваат на статуата."),
    ("permit.png", p_permit, "Градежна дозвола: статус „во тек“ од памтивек."),
    ("rush.png", p_rush, "Во шпиц, најбрз во Скопје е пешакот."),
    ("wedding.png", p_wedding, "Скопје ноќе е тивко само додека не помине свадба со зурли и тапан."),
]


# ------------------------------------------------------------------------------------------ title poster
def title_poster():
    w, h = 1920, 1080
    p = P((26, 22, 58), (232, 120, 84), (w, h))
    rnd = random.Random(5)
    for _ in range(140):
        p.circ(rnd.randint(0, w), rnd.randint(0, 420), rnd.choice((1, 1, 2)), (255, 248, 220))
    sun(p, 1500, 520, 150, SAND, 28)
    mountain(p, 780, 560, 380, 900, (70, 44, 92))
    mountain(p, 780, 1480, 430, 700, (84, 52, 98))
    cross(p, 1480, 430, 110, (250, 246, 240))
    skyline(p, 840, (44, 30, 66), 21, 0, w, hmin=80, hmax=300, wmin=40, wmax=100, windows=(250, 208, 110))
    p.rect(0, 840, w, h, (22, 18, 34))
    for k, (x, hh, jb, fl) in enumerate(((140, 560, 300, False), (420, 460, 240, True), (1260, 620, 320, True), (1700, 500, 260, False), (1860, 420, 160, True))):
        crane(p, x, 860, hh, (12, 10, 20), jb, fl)
    for y in range(870, h, 36):                                                                      # streets grid, top-down feel
        p.line([(0, y), (w, y)], (46, 38, 62), 2)
    for x in range(0, w, 110):
        p.line([(x, 870), (x - 160, h)], (46, 38, 62), 2)
    car(p, 360, 960, (230, 64, 56), 2.4)
    car(p, 1260, 1000, GOLD, 2.0)
    p.haze((12, 8, 24), 0, 0, 560, 190)
    p.text(w // 2, 150, "Скопје:", 230, GOLD, "mm")
    p.text(w // 2, 340, "проектот никогаш не завршува", 100, CREAM, "mm")
    p.line([(480, 430), (1440, 430)], ROSE, 8)
    p.save_big = True
    im = p.im.resize((1920, 1080), Image.LANCZOS)
    vig = Image.new("L", im.size, 0)
    ImageDraw.Draw(vig).ellipse([-300, -300, 2220, 1380], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    im = Image.composite(im, Image.new("RGB", im.size, (8, 6, 14)), vig.point(lambda v: 150 + v * 105 // 255))
    im.save(os.path.join(OUT, "title.png"), optimize=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    only = set(sys.argv[1:])
    meta = []
    for fn, fnc, text in POSTERS:
        if not only or fn in only:
            fnc()
            print("poster", fn)
        meta.append({"file": fn, "text": text})
    if not only or "title.png" in only:
        title_poster()
        print("poster title.png")
    with open(os.path.join(OUT, "posters.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
