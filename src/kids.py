"""Round 13: children at playgrounds and school yards, teenagers kicking a ball around on the pitches.

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
        self.rng = random.Random(77)
        kid = [i for i, n in enumerate(vehicles.PED_IDS) if n == "Dete"]
        teen = [i for i, n in enumerate(vehicles.PED_IDS) if n in ("Student", "Navivach")]
        self.kid, self.teen = kid or [5], teen or [3]

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
                continue
            if lst is None:
                n = {"playground": rng.randint(3, 7), "school": rng.randint(6, 12), "pitch": rng.randint(4, 10)}.get(kind, 4)
                lst = self.live[k] = []
                for _ in range(n):
                    p = self._kid(kind, x + rng.uniform(-r, r) * 0.7, y + rng.uniform(-r, r) * 0.7)
                    lst.append(p)
            alive = []
            for p in lst:
                if p not in peds:
                    continue
                if p.mode != "play":                    # hit, scared, knocked out: no longer ours
                    continue
                alive.append(p)
                self._move(p, x, y, r, dt)
            self.live[k] = alive

    def _kid(self, kind, x, y):
        import actors
        rng = self.rng
        p = actors.Ped()
        p.arch = rng.choice(self.teen if kind == "pitch" else self.kid)
        p.shirt, p.skin = rng.randrange(3), rng.randrange(4)
        p.hp = 20.0
        p.x, p.y, p.h = x, y, rng.uniform(0, 6.28)
        p.mode, p.t = "play", rng.uniform(0.5, 3.0)
        p.v = rng.uniform(1.6, 3.2)
        p.vx = p.vy = 0.0
        self.sim.peds.list.append(p)
        return p

    def _move(self, p, cx, cy, r, dt):
        rng, w = self.rng, self.sim.w
        p.t -= dt
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
