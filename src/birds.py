"""Round 26: ducks, pigeons and crows.

Not pedestrians: nothing can hurt them.  Ducks swim on the river and lakes and waddle about on the banks, pigeons peck about
on squares and in parks (in little flocks), crows strut around parks and green patches.  Anything fast or loud (the player on
foot or in a car, a shot or blast) flushes them: they flap up, circle a bit and land somewhere of the same kind of place.
Birds only exist near the player, placed from the sound map's land-use layers, so ducks are never in a street."""
import math
import random

import soundlib

CAP = 36
SPAWN_MIN, SPAWN_MAX, DESPAWN = 25.0, 95.0, 140.0
# kind -> (layers it likes in order of preference, flock size range, walk speed, flee distance)
SPECIES = {"duck": (("water", "water", "park"), (2, 5), 0.9, 7.0), "pigeon": (("plaza", "plaza", "park"), (3, 8), 1.0, 5.5),
           "crow": (("park", "tree", "park"), (1, 3), 1.3, 8.0)}
ART = {"duck": (0, 1), "pigeon": (2, 3), "crow": (4,)}
CALLS = {"duck": "bird_duck", "pigeon": "bird_pigeon", "crow": "bird_crow"}


class Bird:
    __slots__ = ("x", "y", "z", "h", "sp", "art", "species", "state", "t", "anim", "tx", "ty", "call", "gy", "sw")

    def __init__(self, x, y, species, rng):
        self.x, self.y, self.z, self.h = x, y, 0.0, rng.uniform(0, 6.28)
        self.species, self.art = species, rng.choice(ART[species])
        self.state, self.t, self.anim, self.sp = "idle", rng.uniform(0.5, 4.0), rng.uniform(0, 9), 0.0
        self.tx = self.ty = 0.0
        self.call, self.gy, self.sw = rng.uniform(8, 40), 0.0, False


class Birds:
    def __init__(self, sim):
        self.sim = sim
        self.rng = random.Random(26)
        self.live = []
        self.bio = None
        self.spawn_t = 0.0
        try:
            self.bio = soundlib.Biomes(sim.w)
        except Exception as e_:  # noqa: BLE001
            print("[birds] no biome map:", e_)

    # ------------------------------------------------------------------ helpers
    def _ok(self, b, x, y):
        w = self.sim.w
        if abs(x) > w.hx - 8 or abs(y) > w.hy - 8:
            return False
        s = w.surface(x, y)
        if s in (2, 3):
            return False
        if s == 1:
            return b.species == "duck"
        for _ in w.edges_near(x, y, 0.3):
            return False
        return True

    def _ground(self, b, x, y):
        w = self.sim.w
        if w.surface(x, y) == 1:
            return w.th(x, y) - 0.04
        return w.ground_y(x, y)

    def _spawn(self, fx, fy):
        rng, bio, sim = self.rng, self.bio, self.sim
        if bio is None or len(self.live) >= CAP - 8:
            return
        sp = rng.choice(list(SPECIES))
        layers, (n0, n1), _w, _f = SPECIES[sp]
        pt = bio.find(fx, fy, rng.choice(layers), rng, SPAWN_MAX, 10)
        if pt is None or (pt[0] - fx) ** 2 + (pt[1] - fy) ** 2 < SPAWN_MIN ** 2:
            return
        for _ in range(rng.randint(n0, n1)):
            for _t in range(5):
                x, y = pt[0] + rng.uniform(-3, 3), pt[1] + rng.uniform(-3, 3)
                b = Bird(x, y, sp, rng)
                if self._ok(b, x, y):
                    b.gy = self._ground(b, x, y)
                    b.z = b.gy
                    b.sw = sim.w.surface(x, y) == 1
                    self.live.append(b)
                    break

    def flush(self, x, y, r):
        """Gunfire / blasts / anything big and fast: every bird within r takes off away from (x, y)."""
        for b in self.live:
            if b.state != "fly" and (b.x - x) ** 2 + (b.y - y) ** 2 < r * r:
                self._takeoff(b, x, y)

    def _takeoff(self, b, ax, ay):
        rng = self.rng
        b.state, b.t = "fly", rng.uniform(3.0, 7.0)
        a = math.atan2(b.y - ay, b.x - ax) + rng.uniform(-0.7, 0.7)
        b.h = a
        b.tx, b.ty = b.x + math.cos(a) * 30, b.y + math.sin(a) * 30
        if rng.random() < 0.25:
            self.sim.ev("bird_call", x=b.x, y=b.y, call=CALLS[b.species])

    def _land(self, b):
        rng = self.rng
        layers = SPECIES[b.species][0]
        pt = self.bio.find(b.x, b.y, rng.choice(layers), rng, 40.0, 8) if self.bio else None
        if pt and self._ok(b, *pt):
            b.tx, b.ty, b.state = pt[0], pt[1], "land"
        else:
            b.t = 2.0                                         # nowhere good near: keep circling a little longer

    # ------------------------------------------------------------------ update
    def update(self, dt):
        sim = self.sim
        fx, fy, vx, vy = sim.focus()
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = 0.7
            for _ in range(3):
                self._spawn(fx, fy)
        if not self.live:
            return
        cars = [(c.x, c.y, c.v) for c in sim.traffic.cars if abs(c.x - fx) < 120 and abs(c.y - fy) < 120 and c.v > 2.0]
        spd = math.hypot(vx, vy)
        rng = self.rng
        for b in list(self.live):
            if (b.x - fx) ** 2 + (b.y - fy) ** 2 > DESPAWN ** 2:
                self.live.remove(b)
                continue
            b.anim += dt * (14 if b.state in ("fly", "land") else 6 if b.sp > 0.3 else 0)
            if b.state not in ("fly", "land"):
                fd = SPECIES[b.species][3]
                dd = (b.x - fx) ** 2 + (b.y - fy) ** 2
                if dd < (fd * (1.0 if spd > 1.0 else 0.6)) ** 2 and (spd > 0.8 or dd < 4.0):
                    self._takeoff(b, fx, fy)
                else:
                    for cx, cy, cv in cars:
                        if (b.x - cx) ** 2 + (b.y - cy) ** 2 < (8 + cv) ** 2:
                            self._takeoff(b, cx, cy)
                            break
            if b.state == "fly":
                b.z += min(3.0, (self._ground(b, b.x, b.y) + 5.5 - b.z) * 1.5) * dt
                self._move(b, dt, 7.0, True)
                b.t -= dt
                if b.t <= 0:
                    self._land(b)
            elif b.state == "land":
                self._move(b, dt, 5.0, True)
                gy = self._ground(b, b.x, b.y)
                b.z = max(gy, b.z - 3.0 * dt)
                if (b.x - b.tx) ** 2 + (b.y - b.ty) ** 2 < 4.0 or b.z <= gy + 0.01:
                    b.state, b.t, b.sp = "idle", rng.uniform(1.0, 4.0), 0.0
                    b.z = gy
                    b.sw = sim.w.surface(b.x, b.y) == 1
            else:
                self._ground_tick(b, dt)
            b.call -= dt
            if b.call <= 0:
                b.call = rng.uniform(15, 45)
                if b.state != "fly" and (b.x - fx) ** 2 + (b.y - fy) ** 2 < 60 ** 2:
                    sim.ev("bird_call", x=b.x, y=b.y, call=CALLS[b.species])

    def _move(self, b, dt, sp, air):
        want = math.atan2(b.ty - b.y, b.tx - b.x)
        d = (want - b.h + math.pi) % (2 * math.pi) - math.pi
        b.h += max(-3.0 * dt, min(3.0 * dt, d))
        b.sp = sp
        b.x += math.cos(b.h) * sp * dt
        b.y += math.sin(b.h) * sp * dt

    def _ground_tick(self, b, dt):
        rng = self.rng
        b.t -= dt
        gy = self._ground(b, b.x, b.y)
        b.z = gy
        if b.state == "idle":
            b.sp = 0.0
            if b.t <= 0:
                if rng.random() < 0.55:
                    a = rng.uniform(0, 6.28)
                    r = rng.uniform(1.5, 5.0)
                    b.tx, b.ty, b.state, b.t = b.x + math.cos(a) * r, b.y + math.sin(a) * r, "walk", 6.0
                else:
                    b.t = rng.uniform(1.0, 3.5)
                    b.state = "peck" if rng.random() < 0.6 and not b.sw else "idle"
        elif b.state == "peck":
            b.sp = 0.0
            if b.t <= 0:
                b.state, b.t = "idle", rng.uniform(0.5, 2.0)
        else:                                               # walk (or swim)
            sp = SPECIES[b.species][2] * (0.7 if b.sw else 1.0)
            ox, oy = b.x, b.y
            self._move(b, dt, sp, False)
            if not self._ok(b, b.x, b.y) or (b.x - b.tx) ** 2 + (b.y - b.ty) ** 2 < 0.25 or b.t <= 0:
                if not self._ok(b, b.x, b.y):
                    b.x, b.y = ox, oy
                b.state, b.t, b.sp = "idle", rng.uniform(1.0, 4.0), 0.0
            b.sw = self.sim.w.surface(b.x, b.y) == 1
            b.z = self._ground(b, b.x, b.y)

    def frame(self, b):
        if b.state == "fly" or b.state == "land":
            return 4 + (int(b.anim) & 1)
        if b.sw:
            return 6
        if b.state == "peck":
            return 3 if int(b.anim * 0.5 + b.t * 3) & 1 else 0
        if b.sp > 0.1:
            return 1 + (int(b.anim) & 1)
        return 0
