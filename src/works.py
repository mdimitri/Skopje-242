"""Round 20: building sites.  The world build (tools/construction.py) bakes the fence, the building and the parked concrete
mixer; this adds the people and the atmosphere: workers (the existing "Rabotnik" pedestrian) who walk between spots on the
site and hammer / dig / carry, construction noise that gets louder near a site, and dust drifting over it.

Sites come from props "works": (x, y, radius, stage, bx, by, bw, bd, gate_x, gate_y).  Workers are ordinary Ped objects in
mode "play" (like Kids): cars and fists can still hit them, then they are no longer ours."""
import math
import random

import pyray as rl

import vehicles

HOURS = (6.5, 18.5)
NEAR = 190.0                      # sites closer than this to the player have their crew on the site
HEAR = 110.0                      # the noise carries this far
DUST_CELL = 9.0


class Works:
    def __init__(self, sim):
        self.sim = sim
        self.sites = [tuple(s) for s in (getattr(sim.w, "works", None) or [])]
        self.live = {}
        self.rng = random.Random(2020)
        self.arch = [i for i, n in enumerate(vehicles.PED_IDS) if n == "Rabotnik"] or [0]

    def open(self):
        return HOURS[0] <= self.sim.clock.hour <= HOURS[1]

    def nearest(self, x, y):
        """Distance to the closest site that is working right now (for the noise)."""
        if not self.open():
            return 1e9
        return min((math.hypot(s[0] - x, s[1] - y) for s in self.sites), default=1e9)

    # ------------------------------------------------------------------ crews
    def update(self, dt):
        if not self.sites:
            return
        sim, rng = self.sim, self.rng
        fx, fy = sim.focus()[:2]
        peds = sim.peds.list
        open_ = self.open()
        for k, s in enumerate(self.sites):
            d = abs(s[0] - fx) + abs(s[1] - fy)
            lst = self.live.get(k)
            if d > NEAR * 1.3 or not open_:
                if lst is not None:
                    for p in lst:
                        if p in peds and p.mode == "play":
                            peds.remove(p)
                    del self.live[k]
                continue
            if lst is None and d <= NEAR:
                lst = self.live[k] = []
                stage = s[3]
                for _ in range(rng.randint(4, 6) if stage < 2 else rng.randint(3, 5)):
                    pt = self._spot(s)
                    if pt:
                        lst.append(self._worker(*pt))
            if lst is None:
                continue
            alive = []
            for p in lst:
                if p not in peds:
                    continue
                if p.mode != "play":                      # hit, scared, knocked out: no longer ours
                    p.pose = None
                    continue
                alive.append(p)
                self._move(p, s, dt)
            self.live[k] = alive

    def _spot(self, s, tries=14):
        """A random point on the site's bare ground: inside the fence, outside the building footprint."""
        x, y, r, _st, bx, by, bw, bd = s[:8]
        rng = self.rng
        for _ in range(tries):
            px, py = x + rng.uniform(-r, r), y + rng.uniform(-r * 0.8, r * 0.8)
            if abs(px - bx) < bw / 2 + 1.8 and abs(py - by) < bd / 2 + 1.8:
                continue
            if abs(px - x) > r * 1.0 or abs(py - y) > r * 0.85:
                continue
            return px, py
        return None

    def _worker(self, x, y):
        import actors
        rng = self.rng
        p = actors.Ped()
        p.arch = rng.choice(self.arch)
        p.shirt, p.skin = rng.randrange(3), rng.randrange(4)
        p.hp = 60.0
        p.x, p.y, p.h = x, y, rng.uniform(0, 6.28)
        p.mode, p.t = "play", rng.uniform(0.5, 4.0)
        p.v = 0.0
        p.vx = p.vy = 0.0
        p.tx, p.ty = x, y
        self.sim.peds.list.append(p)
        return p

    def _crosses(self, s, ax, ay, bx, by):
        """Does the straight walk a -> b cut through the building footprint?"""
        _x, _y, _r, _st, cx, cy, w, d = s[:8]
        for i in range(1, 8):
            t = i / 8.0
            if abs(ax + (bx - ax) * t - cx) < w / 2 + 1.2 and abs(ay + (by - ay) * t - cy) < d / 2 + 1.2:
                return True
        return False

    def _move(self, p, s, dt):
        rng, w = self.rng, self.sim.w
        p.t -= dt
        walking = (p.vx or p.vy)
        if walking:
            if math.hypot(p.tx - p.x, p.ty - p.y) < 0.6:
                p.vx = p.vy = 0.0
                p.v = 0.0
                p.pose = "work"                              # arrived: swing the hammer / shovel
                p.t = rng.uniform(4.0, 11.0)
                p.h = math.atan2(s[5] - p.y, s[4] - p.x) + rng.uniform(-0.6, 0.6)     # face the building (or the hole)
            else:
                nx, ny = p.x + p.vx * dt, p.y + p.vy * dt
                if not any(True for _ in w.edges_near(nx, ny, 0.4)):
                    p.x, p.y = nx, ny
                p.anim += dt * 3.0
        elif p.t <= 0:                                       # next errand
            for _ in range(6):
                pt = self._spot(s)
                if pt and not self._crosses(s, p.x, p.y, pt[0], pt[1]):
                    p.tx, p.ty = pt
                    a = math.atan2(pt[1] - p.y, pt[0] - p.x)
                    p.vx, p.vy = math.cos(a) * 1.5, math.sin(a) * 1.5
                    p.h, p.pose, p.v = a, None, 1.5
                    break
            else:
                p.t = rng.uniform(1.0, 3.0)
        else:
            p.anim += dt * 2.0
        p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)

    # ------------------------------------------------------------------ dust
    def draw_dust(self, cam, cam_x, cam_y, sw, sh, t, gy, ppm):
        """Brownish dust clouds drifting over every working site near the camera (2D soft circles, like the smog)."""
        if not self.sites or not self.open():
            return
        for s in self.sites:
            if abs(s[0] - cam_x) > 120 or abs(s[1] - cam_y) > 120:
                continue
            x, y, r, stage, bx, by = s[:6]
            k = 1.0 if stage <= 1 else 0.75               # digging and concrete raise the most dust
            for i in range(7):
                ph = t * 0.12 + i * 0.9
                wx = bx + math.sin(ph * 1.3 + i) * r * 0.9 + 3.0 * math.sin(t * 0.07 + i)
                wy = by + math.cos(ph + i * 2.0) * r * 0.7
                h = 1.5 + 2.5 * abs(math.sin(ph * 0.7 + i))
                v = rl.get_world_to_screen(rl.Vector3(wx, gy + h, wy), cam)
                a = int(60 * k * (0.5 + 0.5 * math.sin(t * 0.4 + i * 1.9)))
                rad = (9 + 5 * (i % 3)) * ppm
                rl.draw_circle_gradient(rl.Vector2(v.x, v.y), rad, rl.Color(168, 146, 112, a), rl.Color(168, 146, 112, 0))
