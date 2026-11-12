"""Scripted orbit near walls: counts frames where the chase camera is inside a building (below its roof) or the avatar is hidden
behind a wall / tree, with and without Selfie.clip.  Usage: python3 tools/cam_audit.py <world dir> [n_buildings]"""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np  # noqa: F401
from world import World
from selfie import Selfie

def inside(ring, x, y):
    c = False
    for i in range(len(ring)):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % len(ring)]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            c = not c
    return c

def main():
    w = World(sys.argv[1])
    nb = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    sf = Selfie.__new__(Selfie)
    rng = random.Random(7)
    bl = [(b, w.th(*b["ring"][0]) + b.get("h", 8.0)) for b in w.buildings]
    def bad(hx, hy, hz, cx, cy, cz):
        ins = hid = 0
        for b, top in bl_near(hx, hy):
            ring = b["ring"]
            if cz < top and inside(ring, cx, cy):
                ins = 1
            for i in range(len(ring)):
                (ax, ay), (bx, by) = ring[i], ring[(i + 1) % len(ring)]
                dx, dy, ex, ey = cx - hx, cy - hy, bx - ax, by - ay
                den = dx * ey - dy * ex
                if abs(den) < 1e-9:
                    continue
                t = ((ax - hx) * ey - (ay - hy) * ex) / den
                u = ((ax - hx) * dy - (ay - hy) * dx) / den
                if 0.02 < t < 0.98 and 0 <= u <= 1 and hz + (cz - hz) * t < top:
                    hid = 1
        return ins, hid
    cache = {}
    def bl_near(x, y):
        k = (int(x // 40), int(y // 40))
        if k not in cache:
            cache[k] = [(b, t) for b, t in bl if any(abs(q[0] - (k[0] * 40 + 20)) < 90 and abs(q[1] - (k[1] * 40 + 20)) < 90 for q in b["ring"])]
        return cache[k]
    pts = []
    for b, top in rng.sample(bl, min(nb, len(bl))):
        r = b["ring"]
        i = rng.randrange(len(r)); (ax, ay), (bx, by) = r[i], r[(i + 1) % len(r)]
        L = math.hypot(bx - ax, by - ay)
        if L < 3:
            continue
        nx, ny = (by - ay) / L, -(bx - ax) / L
        mx, my = (ax + bx) / 2, (ay + by) / 2
        d = rng.uniform(1.2, 3.0)
        for sgn in (1, -1):
            x, y = mx + sgn * nx * d, my + sgn * ny * d
            if not any(inside(bb["ring"], x, y) for bb, _ in bl_near(x, y)):
                pts.append((x, y)); break
    res = {}
    for mode, (back, up) in (("walk", (4.5, 3.6)), ("car", (8.0, 5.5))):
        tot = {"before": [0, 0, 0], "after": [0, 0, 0]}
        for hx, hy in pts:
            az = w.ground_y(hx, hy)
            for k in range(72):
                h = k * math.tau / 72
                px, pz, py = hx - math.cos(h) * back, hy - math.sin(h) * back, az + up
                for name in ("before", "after"):
                    cx, cy, cz = px, pz, py
                    if name == "after":
                        s = max(sf.clip(w, (hx, hy, az + 1.2), (px, pz, py)), 0.04)
                        cx, cy, cz = hx + (px - hx) * s, hy + (pz - hy) * s, az + 1.2 + (py - az - 1.2) * s + (1 - s) * 3.5
                    i, hd = bad(hx, hy, az + 1.2, cx, cy, cz)
                    t = tot[name]; t[0] += 1; t[1] += i; t[2] += hd
        for n, t in tot.items():
            print(f"{mode} {n}: frames {t[0]}  camera-inside {t[1]} ({100*t[1]/t[0]:.1f}%)  avatar-hidden {t[2]} ({100*t[2]/t[0]:.1f}%)")

main()
