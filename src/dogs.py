"""Round 23: friendly stray dogs.

Not pedestrians: they are not in sim.peds, so no bullet, blast, punch or car can hurt them.  They hang around kiosks, food
places and street bins, trot about, follow people (and cross the street with them), sleep on the pavement, and bark at and
chase cyclists, scooters, mopeds and the horse cart.  A fist "attack" in front of one pets it instead.  They run from gunfire
and blasts, step back from brawls, and always jump clear of cars.

Dogs only exist near the player (spawned at hubs 70-150 m away, dropped beyond 190 m); what is where is deterministic per hub."""
import math
import random

import vehicles

CAP = 22
SPAWN_MIN, SPAWN_MAX, DESPAWN = 70.0, 150.0, 190.0
CELL = 100.0
RIDER_ARCH = {i for i, n in enumerate(vehicles.PED_IDS) if n in vehicles.RIDERS}
WALK, TROT, RUN, FLEE = 1.5, 2.6, 6.6, 7.6
HUB_DOGS = {"kiosk": (1, 2, 2, 3, 4), "food": (0, 0, 1, 1, 2, 3), "bin": (0, 0, 0, 1, 1, 2)}
HUB_POIS = ("food", "market")


class Dog:
    __slots__ = ("x", "y", "h", "gz", "state", "pose", "t", "spd", "anim", "coat", "voice", "pitch", "hub", "tgt", "bark_cd", "cool",
                 "chaser", "friend", "curious", "happy", "thr", "gx", "gy", "dx", "dy", "key")

    def __init__(self, x, y, rng, hub, key):
        self.x, self.y, self.h, self.gz = x, y, rng.uniform(0, 6.28), None
        self.state, self.pose, self.t = "idle", "stand", rng.uniform(0.5, 3.0)
        self.spd, self.anim = 0.0, rng.uniform(0, 9)
        self.coat, self.voice, self.pitch = rng.randrange(4), rng.randrange(3), rng.uniform(0.85, 1.3)
        self.hub, self.tgt, self.key = hub, None, key
        self.bark_cd, self.cool, self.happy = 0.0, rng.uniform(0, 8), 0.0
        self.chaser, self.friend, self.curious = rng.random() < 0.45, rng.random() < 0.5, rng.random() < 0.3
        self.thr = None
        self.gx = self.gy = self.dx = self.dy = 0.0


class Dogs:
    def __init__(self, sim):
        self.sim = sim
        self.rng = random.Random(23)
        self.live = []
        self.hubs = {}            # grid cell -> [(x, y, kind)]
        self.hub_live = {}        # (kind, x, y) -> [Dog] (empty list: rolled for no dogs)
        self.road_memo = {}       # 1 m cell -> on a carriageway
        self.snap = {}            # food place (x, y) -> pavement point in front of it
        self.bin_cells = {}       # grid cell -> [(x, y)] street bins found in the collision points
        self.spawn_t = 0.0
        self.watch_t = 0.0
        self.riders = []
        self.walkers = []
        self.fighters = []
        self.cars = []
        self.player = None
        for k in getattr(sim, "kiosks", None) or []:
            self._add_hub(k[0], k[1], "kiosk")

    def add_pois(self, pois):
        """Food places and markets from the map points of interest: [x, y, category, name]."""
        for p in pois:
            if p[2] in HUB_POIS:
                self._add_hub(p[0], p[1], "food")

    def _add_hub(self, x, y, kind):
        self.hubs.setdefault((int(x // CELL), int(y // CELL)), []).append((x, y, kind))

    # ------------------------------------------------------------------ placing
    def _bins(self, cx, cy):
        b = self.bin_cells.get((cx, cy))
        if b is None:
            w = self.sim.w
            x0, y0 = (cx + 0.5) * CELL, (cy + 0.5) * CELL
            b = self.bin_cells[(cx, cy)] = [(pt[0], pt[1]) for pt in w.points_near(x0, y0, CELL * 0.75)
                                            if cx * CELL <= pt[0] < (cx + 1) * CELL and cy * CELL <= pt[1] < (cy + 1) * CELL
                                            and abs(pt[2] - 0.25) < 0.005]            # (only the street bins have this radius)
        return b

    def _road(self, x, y):
        """On a carriageway of a driving road (the surface mask also marks pavements and paths as paved, so it cannot tell)."""
        k = (int(x), int(y))
        r = self.road_memo.get(k)
        if r is None:
            w = self.sim.w
            sg = w.sg
            cx, cy = int(x // sg), int(y // sg)
            r = False
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for ei in w.drive_cells.get((gx, gy), ()):
                        e = w.edges[ei]
                        hw = e["w"] / 2 + 0.2
                        pts = e["pts"]
                        for i in range(len(pts) - 1):
                            ax, ay = pts[i]
                            dx, dy = pts[i + 1][0] - ax, pts[i + 1][1] - ay
                            L2 = dx * dx + dy * dy or 1.0
                            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
                            if (ax + dx * t - x) ** 2 + (ay + dy * t - y) ** 2 < hw * hw:
                                r = True
                                break
                        if r:
                            break
                    if r:
                        break
                if r:
                    break
            if len(self.road_memo) > 40000:
                self.road_memo.clear()
            self.road_memo[k] = r
        return r

    def _free(self, x, y, road_ok=False):
        w = self.sim.w
        if w.surface(x, y) == 1 or (not road_ok and self._road(x, y)):
            return False
        if abs(x) > w.hx - 8 or abs(y) > w.hy - 8:
            return False
        for _ in w.edges_near(x, y, 0.35):
            return False
        for tx, ty, tr, _lo, _hi in w.points_near(x, y, 0.7):
            if (tx - x) ** 2 + (ty - y) ** 2 < (tr + 0.2) ** 2:
                return False
        return True

    def _pavement(self, x, y):
        """Food places sit inside buildings: the pavement point in front of them (None when no path is near)."""
        key = (x, y)
        if key not in self.snap:
            w = self.sim.w
            nw = w.nearest_walk_point(x, y, 30)
            pt = None
            if nw is not None:
                e = w.edges[nw[0]]
                px, py, dx, dy = w.edge_point(e, nw[1])
                side = 1.0 if (x - px) * -dy + (y - py) * dx >= 0 else -1.0
                off = (e["w"] / 2 + 1.5) * side if e["drive"] else 1.0 * side
                pt = (px - dy * off, py + dx * off)
                if (pt[0] - x) ** 2 + (pt[1] - y) ** 2 > 20.0 ** 2:
                    pt = None
            self.snap[key] = pt
        return self.snap[key]

    def _spawn(self, fx, fy):
        sim = self.sim
        gx, gy = int(fx // CELL), int(fy // CELL)
        for key in [k for k in self.hub_live if (k[1] - fx) ** 2 + (k[2] - fy) ** 2 > DESPAWN ** 2]:
            for d in self.hub_live.pop(key):
                if d in self.live:
                    self.live.remove(d)
        for cx in range(gx - 2, gx + 3):
            for cy in range(gy - 2, gy + 3):
                hubs = list(self.hubs.get((cx, cy), ())) + [(x, y, "bin") for x, y in self._bins(cx, cy)]
                for x, y, kind in hubs:
                    key = (kind, x, y)
                    d2 = (x - fx) ** 2 + (y - fy) ** 2
                    if key in self.hub_live or not SPAWN_MIN ** 2 < d2 < SPAWN_MAX ** 2 or len(self.live) >= CAP:
                        continue
                    r = random.Random(int(x * 73.0 + y * 131.0) & 0xFFFFFF)           # the same vendors always keep the same strays
                    n = r.choice(HUB_DOGS[kind])
                    pack = self.hub_live[key] = []
                    hx, hy = (x, y) if kind != "food" else (self._pavement(x, y) or (x, y))
                    for _ in range(n if kind != "food" or hx != x else 0):
                        for _try in range(6):
                            px, py = hx + r.uniform(-3.0, 3.0), hy + r.uniform(-3.0, 3.0)
                            if self._free(px, py):
                                d = Dog(px, py, r, (hx, hy), key)
                                d.gz = sim.w.level(px, py, -1e9)
                                pack.append(d)
                                self.live.append(d)
                                break

    # ------------------------------------------------------------------ what is around
    def _watch(self, fx, fy):
        sim = self.sim
        self.riders, self.walkers, self.fighters = [], [], []
        for p in sim.peds.list:
            if abs(p.x - fx) > 110 or abs(p.y - fy) > 110:
                continue
            if p.mode == "walk":
                (self.riders if p.arch in RIDER_ARCH else self.walkers).append(p)
            elif p.mode in ("fight", "brawl", "rage"):
                self.fighters.append(p)
        wk = sim.walker
        self.player = wk if sim.mode == "foot" and wk is not None and wk.health > 0 else None
        c = sim.car
        if sim.mode == "car" and c is not None and c.kind in vehicles.BIKES:
            self.riders.append(c)                                       # you on a bike or a scooter

    def _cars(self, fx, fy):
        sim = self.sim
        out = []
        for c in sim.traffic.cars:
            if abs(c.x - fx) < 130 and abs(c.y - fy) < 130 and c.v > 0.8:
                out.append((c.x, c.y, math.cos(c.h) * c.v, math.sin(c.h) * c.v, c.v))
        for b in sim.bodies:
            sp = math.hypot(b.vx, b.vy)
            if sp > 0.8 and abs(b.x - fx) < 130 and abs(b.y - fy) < 130 and b.kind not in vehicles.BIKES:
                out.append((b.x, b.y, b.vx, b.vy, sp))
        self.cars = out

    def _danger(self, d):
        """(ex, ey) unit vector to jump away along, when a moving car is about to reach the dog; None otherwise."""
        for cx, cy, vx, vy, sp in self.cars:
            dx, dy = d.x - cx, d.y - cy
            reach = 6.0 + sp * 0.9
            if dx * dx + dy * dy > reach * reach:
                continue
            ux, uy = vx / sp, vy / sp
            along, lat = dx * ux + dy * uy, -dx * uy + dy * ux
            if -1.5 < along < reach and abs(lat) < 2.8:
                s = 1.0 if lat >= 0 else -1.0
                return -uy * s, ux * s
        return None

    def _busy(self, d):
        """A moving car close enough that a dog waits at the kerb instead of stepping out."""
        for cx, cy, _vx, _vy, sp in self.cars:
            r = 10.0 + sp * 1.6
            if (cx - d.x) ** 2 + (cy - d.y) ** 2 < r * r:
                return True
        return False

    # ------------------------------------------------------------------ events from the game
    def scare(self, x, y, r):
        """Gunfire / blasts: every dog nearby bolts away from the spot."""
        rng = self.rng
        for d in self.live:
            if (d.x - x) ** 2 + (d.y - y) ** 2 < r * r:
                d.state, d.thr, d.t, d.tgt = "flee", (x, y), rng.uniform(4.0, 7.0), None
                if rng.random() < 0.4:
                    self.sim.ev("dog_yip", x=d.x, y=d.y, pitch=d.pitch * 1.15)

    def pettable(self, x, y, h, reach):
        """(dog, distance) of the nearest dog within reach in front of (x, y) facing h."""
        fx, fy = math.cos(h), math.sin(h)
        best = None
        for d in self.live:
            dx, dy = d.x - x, d.y - y
            dist = math.hypot(dx, dy)
            if dist < reach and (dist < 0.6 or (dx * fx + dy * fy) / dist > 0.4) and (best is None or dist < best[1]):
                best = (d, dist)
        return best

    def pet(self, d):
        d.state, d.pose, d.t, d.tgt, d.spd, d.happy = "pet", "sit", 4.0, None, 0.0, 6.0
        d.friend = True
        self.sim.ev("dog_pet", x=d.x, y=d.y, pitch=d.pitch)

    # ------------------------------------------------------------------ per frame
    def update(self, dt):
        sim = self.sim
        fx, fy = sim.focus()[:2]
        self.spawn_t -= dt
        if self.spawn_t <= 0:
            self.spawn_t = 1.0
            self._spawn(fx, fy)
        if not self.live:
            return
        self.watch_t -= dt
        if self.watch_t <= 0:
            self.watch_t = 0.3
            self._watch(fx, fy)
        self._cars(fx, fy)
        for d in list(self.live):
            if (d.x - fx) ** 2 + (d.y - fy) ** 2 > (DESPAWN + 60) ** 2:
                self.live.remove(d)
                continue
            self._tick(d, dt)

    def _tick(self, d, dt):
        w = self.sim.w
        d.t -= dt
        d.bark_cd -= dt
        d.cool -= dt
        d.happy = max(0.0, d.happy - dt)
        d.spd = 0.0
        run = self._danger(d)
        if run is not None and d.state != "flee":
            d.state, d.dx, d.dy, d.t = "dodge", run[0], run[1], 0.9            # jump clear of the car
        if d.state == "dodge":
            if d.t <= 0:
                d.state, d.t = "idle", 0.5
            else:
                self._step(d, d.x + d.dx * 5, d.y + d.dy * 5, FLEE, dt, True)
        elif d.state == "flee":
            tx, ty = d.thr
            n = math.hypot(d.x - tx, d.y - ty) or 1.0
            if d.t <= 0 or n > 90:
                d.state, d.t, d.pose = "idle", 1.0, "stand"
            else:
                self._step(d, d.x + (d.x - tx) / n * 6, d.y + (d.y - ty) / n * 6, FLEE, dt, self._on_road(d))
        elif d.state == "sleep":
            d.pose = "sleep"
            if d.t <= 0 or any((p.x - d.x) ** 2 + (p.y - d.y) ** 2 < 4.0 and p.vx * p.vx + p.vy * p.vy > 9.0 for p in self.riders):
                d.state, d.t, d.pose = "idle", 1.0, "stand"
        elif d.state == "pet":
            d.pose = "sit"
            self._face(d, self.player, dt)
            if d.t <= 0:
                d.state, d.t, d.pose = "idle", 0.5, "sit"
                if d.friend and self.player is not None:
                    d.state, d.tgt, d.t = "follow", self.player, self.rng.uniform(25, 50)
        elif d.state == "idle":
            if self._near_fight(d):
                return
            if d.t <= 0:
                self._choose(d)
        elif d.state == "wander":
            if self._near_fight(d):
                return
            if d.t <= 0 or math.hypot(d.gx - d.x, d.gy - d.y) < 0.6:
                d.state, d.t, d.pose = "idle", self.rng.uniform(2.0, 7.0), self.rng.choice(("stand", "sit", "sniff", "sniff"))
            else:
                self._step(d, d.gx, d.gy, WALK if d.t > 3 else TROT, dt, self._on_road(d))
                if d.spd == 0.0:
                    d.t = 0.0
        elif d.state == "follow":
            t = d.tgt
            if d.t <= 0 or t is None or not (t is self.player or t in self.walkers) or self._near_fight(d):
                if d.state == "follow":
                    d.state, d.t, d.pose = "idle", 1.0, "sit"
            else:
                dist = math.hypot(t.x - d.x, t.y - d.y)
                ts = math.hypot(t.vx, t.vy)
                if dist > 2.0:
                    sp = min(RUN * 0.8, ts + 1.3 * (dist - 2.0) + 0.6)
                    self._step(d, t.x - t.vx * 0.3, t.y - t.vy * 0.3, sp, dt, self._on_road(d) or not self._busy(d))
                else:
                    d.pose = "sit" if ts < 0.3 else "stand"
                    d.happy = 1.0
        elif d.state == "chase":
            t = d.tgt
            if d.t <= 0 or t is None or t not in self.riders or math.hypot(t.x - d.x, t.y - d.y) > 38:
                d.state, d.t, d.cool, d.pose = "idle", 1.5, self.rng.uniform(18, 35), "stand"
            else:
                dist = math.hypot(t.x - d.x, t.y - d.y)
                ts = math.hypot(t.vx, t.vy)
                self._step(d, t.x + t.vx * 0.4, t.y + t.vy * 0.4, RUN if dist > 3.0 else max(2.0, min(RUN, ts * 1.1)), dt,
                           self._on_road(d) or not self._busy(d))
                if d.bark_cd <= 0 and dist < 30:
                    d.bark_cd = self.rng.uniform(0.5, 0.9)
                    self.sim.ev("dog_bark", x=d.x, y=d.y, voice=d.voice, pitch=d.pitch)
        elif d.state == "come":
            p = self.player
            if d.t <= 0 or p is None or math.hypot(p.x - d.x, p.y - d.y) < 1.7:
                d.state, d.t, d.pose, d.happy = "idle", self.rng.uniform(4, 8), "sit", 5.0
            else:
                self._step(d, p.x, p.y, TROT, dt, False)
        d.gz = w.level(d.x, d.y, d.gz if d.gz is not None else -1e9)

    # ------------------------------------------------------------------ choosing what to do
    def _near_fight(self, d):
        for p in self.fighters:
            if (p.x - d.x) ** 2 + (p.y - d.y) ** 2 < 100.0:
                d.state, d.thr, d.t = "flee", (p.x, p.y), self.rng.uniform(2.5, 4.0)
                return True
        return False

    def _choose(self, d):
        rng, sim = self.rng, self.sim
        near = lambda o, r: (o.x - d.x) ** 2 + (o.y - d.y) ** 2 < r * r  # noqa: E731
        if d.chaser and d.cool <= 0:
            rs = [r for r in self.riders if near(r, 24) and r.vx * r.vx + r.vy * r.vy > 0.5]
            if rs and rng.random() < 0.7:
                d.state, d.tgt, d.t = "chase", min(rs, key=lambda r: (r.x - d.x) ** 2 + (r.y - d.y) ** 2), rng.uniform(7, 14)
                return
        p = self.player
        if p is not None and d.curious and near(p, 8) and p.vx * p.vx + p.vy * p.vy < 0.5 and rng.random() < 0.5:
            d.state, d.t = "come", 8.0
            return
        if d.friend and rng.random() < 0.35:
            ws = [q for q in self.walkers if near(q, 14)] + ([p] if p is not None and near(p, 14) else [])
            if ws:
                d.state, d.tgt, d.t = "follow", rng.choice(ws), rng.uniform(12, 35)
                return
        h = sim.clock.hour
        if not self._on_road(d) and rng.random() < (0.5 if h >= 23 or h < 6 else 0.1 if 13 <= h < 16 else 0.04):
            d.state, d.pose, d.t = "sleep", "sleep", rng.uniform(25, 70)
            return
        hx, hy = d.hub
        a = rng.uniform(0, 6.28)
        r = rng.uniform(1.0, 3.5) if rng.random() < 0.8 else rng.uniform(6, 16)           # mostly pottering around the vendor
        d.gx, d.gy = hx + math.cos(a) * r, hy + math.sin(a) * r
        d.state, d.t = "wander", rng.uniform(4, 9)

    # ------------------------------------------------------------------ moving
    def _on_road(self, d):
        return self._road(d.x, d.y)

    def _face(self, d, p, dt):
        if p is not None:
            self._turn(d, math.atan2(p.y - d.y, p.x - d.x), dt)

    def _turn(self, d, a, dt):
        diff = (a - d.h + math.pi) % (2 * math.pi) - math.pi
        d.h += max(-10.0 * dt, min(10.0 * dt, diff))
        return diff

    def _step(self, d, tx, ty, sp, dt, road_ok):
        diff = self._turn(d, math.atan2(ty - d.y, tx - d.x), dt)
        sp *= max(0.3, 1.0 - abs(diff) / 2.2)
        nx, ny = d.x + math.cos(d.h) * sp * dt, d.y + math.sin(d.h) * sp * dt
        if self._free(nx, ny, road_ok):
            d.x, d.y = nx, ny
        elif self._free(nx, d.y, road_ok):
            d.x = nx
        elif self._free(d.x, ny, road_ok):
            d.y = ny
        else:
            return
        d.spd = sp
        d.anim += sp * dt

    def frame(self, d, t):
        """Model frame for the renderer (see dogart)."""
        if d.spd > 0.15:
            return 4 + (int(d.anim * 1.8) & 3) if d.spd > 4.2 else int(d.anim * 4.4) & 3
        if d.pose == "sleep":
            return 10
        if d.pose == "sit":
            return 8 + (int(t * 4.0) & 1 if d.happy > 0 else 0)
        if d.pose == "sniff":
            return 12
        return 11 + (2 if d.happy > 0 and int(t * 5.0) & 1 else 0)
