"""Round 13: children at playgrounds and school yards; on the pitches the same children kick a ball around.

Sites come from the world build (props "sites": kind, x, y, radius).  Kids are ordinary Ped objects in mode "play":
they run around inside their site, stop, chase each other, jump; cars can still knock them over."""
import math
import random

import vehicles

HOURS = {"playground": (8.5, 20.5), "school": (7.5, 14.5), "pitch": (9.0, 21.5)}


class Kids:
    def __init__(self, sim):
        self.sim = sim
        self.sites = [tuple(s) for s in (getattr(sim.w, "sites", None) or [])]
        self.live = {}            # site index -> [ped]
        self.balls = {}           # pitch site index -> [x, y, vx, vy, z, vz]
        self.rng = random.Random(77)
        kid = [i for i, n in enumerate(vehicles.PED_IDS) if n == "Dete"]
        self.kid = kid or [5]

    def update(self, dt):
        if not self.sites:
            return
        sim, rng = self.sim, self.rng
        fx, fy = sim.focus()[:2]
        hour = sim.clock.hour
        peds = sim.peds.list
        for k, (kind, x, y, r) in enumerate(self.sites):
            d = abs(x - fx) + abs(y - fy)
            lst = self.live.get(k)
            lo, hi = HOURS.get(kind, (8, 20))
            open_ = lo <= hour <= hi
            if d > 230 or not open_:
                if lst:
                    for p in lst:
                        if p in peds and p.mode == "play":
                            peds.remove(p)
                    del self.live[k]
                self.balls.pop(k, None)
                continue
            if lst is None:
                n = {"playground": rng.randint(3, 7), "school": rng.randint(6, 12), "pitch": rng.randint(4, 10)}.get(kind, 4)
                lst = self.live[k] = []
                for _ in range(n):
                    p = self._kid(kind, x + rng.uniform(-r, r) * 0.7, y + rng.uniform(-r, r) * 0.7)
                    lst.append(p)
            ball = None
            if kind == "pitch":
                ball = self.balls.get(k)
                if ball is None:
                    ball = self.balls[k] = [x, y, 0.0, 0.0, 0.0, 0.0]
                self._roll(ball, x, y, r, dt)
            alive = []
            for p in lst:
                if p not in peds:
                    continue
                if p.mode != "play":                    # hit, scared, knocked out: no longer ours
                    continue
                alive.append(p)
                self._move(p, x, y, r, dt, ball)
            self.live[k] = alive

    def _kid(self, kind, x, y):
        import actors
        rng = self.rng
        p = actors.Ped()
        p.arch = rng.choice(self.kid)
        p.shirt, p.skin = rng.randrange(3), rng.randrange(4)
        p.hp = 20.0
        p.x, p.y, p.h = x, y, rng.uniform(0, 6.28)
        p.mode, p.t = "play", rng.uniform(0.5, 3.0)
        p.v = rng.uniform(1.6, 3.2)
        p.vx = p.vy = 0.0
        self.sim.peds.list.append(p)
        return p

    def _roll(self, b, cx, cy, r, dt):
        """The ball rolls, slows down on the grass, bounces, and is turned back at the edge of the pitch."""
        k = max(0.0, 1.0 - 0.9 * dt)
        b[2] *= k
        b[3] *= k
        nx, ny = b[0] + b[2] * dt, b[1] + b[3] * dt
        if math.hypot(nx - cx, ny - cy) > r or any(True for _ in self.sim.w.edges_near(nx, ny, 0.3)):
            b[2], b[3] = -b[2] * 0.5, -b[3] * 0.5
        else:
            b[0], b[1] = nx, ny
        if b[4] > 0 or b[5]:
            b[4] += b[5] * dt
            b[5] -= 9.8 * dt
            if b[4] <= 0:
                b[4], b[5] = 0.0, (-b[5] * 0.45 if b[5] < -1.5 else 0.0)

    def _move(self, p, cx, cy, r, dt, ball=None):
        rng, w = self.rng, self.sim.w
        p.t -= dt
        if ball is not None:
            d = math.hypot(ball[0] - p.x, ball[1] - p.y)
            if d < 0.7 and ball[4] < 0.5:                 # kick it: toward somewhere else on the pitch
                a = math.atan2(cy - ball[1], cx - ball[0]) + rng.uniform(-1.2, 1.2)
                s = rng.uniform(5.0, 11.0)
                ball[2], ball[3] = math.cos(a) * s, math.sin(a) * s
                if rng.random() < 0.3:
                    ball[5] = rng.uniform(2.0, 5.0)       # a lob
                p.vx = p.vy = 0.0
                p.t = rng.uniform(0.6, 1.4)
            elif p.t <= 0 and rng.random() < 0.6:          # run after the ball
                a = math.atan2(ball[1] - p.y, ball[0] - p.x)
                p.vx, p.vy = math.cos(a) * p.v, math.sin(a) * p.v
                p.h = a
                p.t = rng.uniform(0.3, 0.8)
        if p.t <= 0:
            p.t = rng.uniform(0.8, 3.5)
            if rng.random() < 0.25:                     # stand and catch breath
                p.vx = p.vy = 0.0
            else:
                a = rng.uniform(0, 6.28)
                if math.hypot(p.x - cx, p.y - cy) > r * 0.7:       # back toward the middle
                    a = math.atan2(cy - p.y, cx - p.x) + rng.uniform(-0.7, 0.7)
                p.vx, p.vy = math.cos(a) * p.v, math.sin(a) * p.v
                p.h = a
            if rng.random() < 0.15:
                p.hv = 3.0                              # a little jump
        nx, ny = p.x + p.vx * dt, p.y + p.vy * dt
        if not any(True for _ in w.edges_near(nx, ny, 0.4)):    # never through a wall
            p.x, p.y = nx, ny
        else:
            p.t = 0.0
        if p.hv or p.hy > 0:
            p.hy = max(0.0, p.hy + p.hv * dt)
            p.hv = p.hv - 12.0 * dt if p.hy > 0 else 0.0
        if p.vx or p.vy:
            p.anim += dt * 3.2
        p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
