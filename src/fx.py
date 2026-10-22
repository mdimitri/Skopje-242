"""Visual effects: particles (smoke, sparks, fire, debris, leaves), floating text pop-ups, speech bubbles."""
import math
import random

import pyray as rl
import font   # noqa: E402

QUADS = rl.RL_QUADS
GROUND = None            # callable (x, z) -> terrain height; set by main so effects sit on the hill, not inside it


def _gy(x, z):
    return GROUND(x, z) if GROUND else 0.0


class Particles:
    """Flat camera-facing quads (the camera is top-down). One immediate-mode batch per frame."""
    __slots__ = ("p", "rng", "max")

    def __init__(self, rng=None, max_particles=900):
        self.p = []
        self.rng = rng or random.Random(3)
        self.max = max_particles

    def emit(self, kind, x, z, y=0.6, vx=0.0, vz=0.0, vy=0.0, n=1, size=0.5, life=1.0, col=(255, 255, 255), spread=1.0, grow=1.0, grav=0.0):
        r = self.rng
        for _ in range(n):
            if len(self.p) >= self.max:
                self.p.pop(0)
            self.p.append([x + r.uniform(-spread, spread) * 0.3, y + _gy(x, z), z + r.uniform(-spread, spread) * 0.3,
                           vx + r.uniform(-spread, spread), vy + r.uniform(0, spread * 0.5) if vy == 0 else vy + r.uniform(-.3, .3),
                           vz + r.uniform(-spread, spread), life * r.uniform(0.7, 1.2), life, size * r.uniform(0.7, 1.3), col, grow, grav, r.uniform(0, 6.28)])

    def smoke(self, x, z, dark=0.0, n=1, y=0.8, vx=0, vz=0, big=1.0):
        c = int(210 - 170 * dark)
        self.emit("s", x, z, y, vx * 0.2, vz * 0.2, 1.2, n, 0.7 * big, 1.6 + dark, (c, c, c), 0.6, 2.4)

    def sparks(self, x, z, n=8, y=0.8):
        self.emit("k", x, z, y, 0, 0, 2.5, n, 0.14, 0.45, (255, 220, 120), 5.0, 0.6, -9.0)

    def fire(self, x, z, n=2, y=1.0, big=1.0):
        self.emit("f", x, z, y, 0, 0, 2.2, n, 0.9 * big, 0.8, (255, 150, 30), 0.9, 1.6)

    def debris(self, x, z, col, n=6, y=0.6):
        self.emit("d", x, z, y, 0, 0, 4.0, n, 0.26, 1.4, col, 6.0, 0.9, -9.0)

    def leaves(self, x, z, n=8):
        self.emit("l", x, z, 3.0, 0, 0, 1.0, n, 0.22, 1.3, (84, 140, 60), 3.5, 1.0, -2.2)

    def explosion(self, x, z):
        self.emit("f", x, z, 1.0, 0, 0, 3.0, 36, 1.6, 1.0, (255, 170, 40), 7.0, 1.8, -0.5)
        self.emit("s", x, z, 1.5, 0, 0, 2.0, 22, 1.8, 2.6, (60, 60, 60), 6.0, 2.2)
        self.emit("k", x, z, 1.5, 0, 0, 5.0, 24, 0.16, 1.2, (255, 230, 140), 10.0, 0.7, -9.0)

    def update(self, dt):
        out = []
        for q in self.p:
            q[6] -= dt
            if q[6] <= 0:
                continue
            q[0] += q[3] * dt
            q[1] += q[4] * dt
            q[2] += q[5] * dt
            q[4] += q[11] * dt
            q[3] *= (1 - 1.2 * dt)
            q[5] *= (1 - 1.2 * dt)
            g0 = _gy(q[0], q[2]) + 0.05
            if q[1] < g0:
                q[1] = g0
                q[4] = 0
            q[8] += q[10] * dt * 0.5
            out.append(q)
        self.p = out

    def draw(self):
        if not self.p:
            return
        rl.rl_disable_depth_mask()
        rl.rl_begin(QUADS)
        for x, y, z, _vx, _vy, _vz, life, life0, size, col, _g, _gr, rot in self.p:
            f = max(0.0, life / life0)
            a = int(255 * min(1.0, f * 1.6) * (0.85 if col[0] > 200 and col[1] < 200 else 0.7))
            rl.rl_color4ub(int(col[0]), int(col[1]), int(col[2]), a)
            h = size * 0.5
            c, s = math.cos(rot) * h, math.sin(rot) * h
            rl.rl_vertex3f(x - c - s, y, z - s + c)
            rl.rl_vertex3f(x + c - s, y, z + s + c)
            rl.rl_vertex3f(x + c + s, y, z + s - c)
            rl.rl_vertex3f(x - c + s, y, z - s - c)
        rl.rl_end()
        rl.rl_enable_depth_mask()


def read_time(text, secs):
    """Show time grows with the text length: about 14 characters a second plus a pause, never shorter than asked, a bit longer in general."""
    return max(secs * 1.3, 1.4 + len(text) * 0.075)


class Popups:
    """Floating comic text at world positions (speech bubbles, +1 burek, KABOOM ...)."""

    def __init__(self):
        self.items = []     # [text, x, y(height), z, ttl, color, size]

    def add(self, text, x, z, y=3.0, ttl=2.4, color=(255, 255, 255), size=22):
        ttl = read_time(text, ttl)
        # avoid piling identical text on one spot
        for it in self.items:
            if it[0] == text and abs(it[1] - x) < 3 and abs(it[3] - z) < 3:
                return
        self.items.append([text, x, y + _gy(x, z), z, ttl, ttl, color, size])
        if len(self.items) > 24:
            self.items.pop(0)

    def update(self, dt):
        for it in self.items:
            it[4] -= dt
            it[2] += dt * 0.6
        self.items = [i for i in self.items if i[4] > 0]

    def draw(self, cam):
        for text, x, y, z, ttl, ttl0, col, size in self.items:
            sp = rl.get_world_to_screen(rl.Vector3(x, y, z), cam)
            a = int(255 * min(1.0, ttl / 0.5, (ttl0 - ttl) / 0.12 + 0.2))
            w = font.measure_text(text, size)
            px, py = int(sp.x - w / 2), int(sp.y)
            rl.draw_rectangle_rounded(rl.Rectangle(px - 8, py - 5, w + 16, size + 10), 0.4, 6, rl.Color(20, 20, 24, int(a * 0.72)))
            font.draw_text(text, px, py, size, rl.Color(col[0], col[1], col[2], a))


class Gains:
    """+N ден. numbers that pop up where you earned them, wiggle, then fly into the money counter with a coin trail."""

    def __init__(self):
        self.items = []     # [amount, world x, world z, age, screen start (x, y) or None, seed]
        self.pulse = 0.0    # the counter swells when money lands

    def add(self, amount, x, z):
        for it in self.items:                      # merge rapid gains at the same spot (machine-gun fire)
            if it[3] < 0.35 and abs(it[1] - x) < 4 and abs(it[2] - z) < 4:
                it[0] += amount
                return
        self.items.append([amount, x, z, 0.0, None, random.random() * 6.28])
        if len(self.items) > 30:
            self.items.pop(0)

    def update(self, dt):
        for it in self.items:
            it[3] += dt
        n0 = len(self.items)
        self.items = [i for i in self.items if i[3] < 1.6]
        if len(self.items) < n0:
            self.pulse = 1.0
        self.pulse = max(0.0, self.pulse - dt * 2.5)

    def draw(self, cam, target):
        tx, ty = target
        for it in self.items:
            amt, x, z, age, start, seed = it
            if start is None:
                sp = rl.get_world_to_screen(rl.Vector3(x, 2.0 + _gy(x, z), z), cam)
                start = it[4] = (sp.x, sp.y)
            if age < 0.55:                               # pop + wiggle on the spot
                k = age / 0.55
                px = start[0] + math.sin(age * 38 + seed) * 6 * (1 - k)
                py = start[1] - 34 * math.sin(k * 1.57)
                size = int(20 + 18 * math.sin(min(1.0, age / 0.18) * 1.57) - 6 * k)
            else:                                        # swoop into the counter on a curve
                k = min(1.0, (age - 0.55) / 1.0)
                e = k * k * (3 - 2 * k)
                sx, sy = start[0], start[1] - 34
                cx, cy = (sx + tx) / 2 + 120 * math.sin(seed), min(sy, ty) - 80
                px = (1 - e) ** 2 * sx + 2 * (1 - e) * e * cx + e * e * tx
                py = (1 - e) ** 2 * sy + 2 * (1 - e) * e * cy + e * e * ty
                py += math.sin(age * 22 + seed) * 4 * (1 - e)
                size = int(30 - 14 * e)
                for j in range(1, 4):                    # coin trail
                    e2 = max(0.0, e - j * 0.06)
                    qx = (1 - e2) ** 2 * sx + 2 * (1 - e2) * e2 * cx + e2 * e2 * tx
                    qy = (1 - e2) ** 2 * sy + 2 * (1 - e2) * e2 * cy + e2 * e2 * ty
                    rl.draw_circle(int(qx), int(qy), 6 - j, rl.Color(250, 210, 60, 200 - j * 50))
            txt = f"+{amt} ден."
            w = font.measure_text(txt, size, True)
            a = 255 if age < 1.4 else int(255 * (1.6 - age) / 0.2)
            font.draw_text(txt, int(px - w / 2) + 2, int(py) + 2, size, rl.Color(0, 0, 0, a // 2), bold=True)
            font.draw_text(txt, int(px - w / 2), int(py), size, rl.Color(250, 215, 70, a), bold=True)
