"""Street waste containers and the garbage trucks that empty them.

* Containers: put along the kerbs of the road graph when the game starts (`make_sites`, deterministic, no world rebuild).
  Most of them are overflowing: lid up, bags piled on top and beside them, flies buzzing and a wavy green-yellow stink rising.
* Trucks: ordinary traffic cars (the "Smetar Kamion").  Each container is also a stop of the petrol-station mechanism
  (stations.py, site kind 2): a garbage truck turns into the street, stands with its rear next to the container and waits.
  `Garbage` (main process) watches the standing trucks and plays the job: the crew gets out of the cab, walks to the
  container, rolls it to the rear of the truck, it is lifted and dumped, rolled back empty, the crew gets in and the truck
  drives on.  Amber beacons turn on the cab roof all the time.

The text of this module is only data and animation: no in-game strings."""
import math
import random

import vehicles

KIND = 2                                   # stations.py site kind of a container stop
SPACING = (38.0, 85.0)                     # metres between containers along one kerb
EDGE_CLASSES = ("residential", "living_street", "unclassified", "tertiary", "secondary", "service")
MIN_W = 4.5                                # narrower roads have no space for a container
GRID = 32.0
DWELL = 34.0                               # seconds a truck stands for one container (the whole job)
FILL_T = 900.0                             # seconds an emptied container needs to fill up again
SERVICED_T = 1500.0                        # a truck does not come back for a container it just emptied within this time
BODY_W, BODY_D, BODY_H = 1.35, 1.05, 1.05  # container body (x along its width, z depth), lid on top
WALK_V = 1.5

_TRUCK = None


def truck_kind():
    global _TRUCK
    if _TRUCK is None:
        _TRUCK = vehicles.IDS.index("Smetar Kamion")
    return _TRUCK


def _half_width(e, s):
    import roadwidth
    return roadwidth.half_width(e, s)


# ------------------------------------------------------------------------------------------------- sites
def make_sites(w, seed=2411):
    """-> list of container sites.  Each is a dict:
    x, y     the container's position (on the kerb), yaw  the truck's travel heading (its front faces the road, its hinge side the houses)
    edge, d  road edge and the direction a truck drives to reach it with the container on its right hand
    s        stop of the truck's centre in the stored direction of the edge (stations.py convention)
    cap      how full it gets (1.0 = brim, above that it overflows)
    kind     = 2 (stations.py)"""
    sites = []
    L = vehicles.DIMS[truck_kind()][0]
    kerb = getattr(w, "kerb", None)
    for ei, e in enumerate(w.edges):
        if not e["drive"] or e["bridge"] or e.get("tunnel") or e["cls"].replace("_link", "") not in EDGE_CLASSES or e["w"] < MIN_W:
            continue
        if e["len"] < L + 14.0:
            continue
        r = random.Random(seed * 100003 + ei)
        dirs = (1,) if e["ow"] else (1, -1)
        for d in dirs:
            u = r.uniform(L / 2 + 6.0, L / 2 + 6.0 + SPACING[1] * 0.6)         # travel distance of the first container
            while u < e["len"] - 8.0:
                # travel distance u_c of the container; the truck's centre stops L/2 + 0.8 m further on
                s_c = u if d == 1 else e["len"] - u
                x, y, dx, dy = w.edge_point(e, s_c)
                dx, dy = dx * d, dy * d
                off = _half_width(e, s_c) + 0.75
                px, py = x - dy * off, y + dx * off
                ok = True
                if kerb is not None:
                    ok = kerb(x - dy * (off + 0.6), y + dx * (off + 0.6))
                if ok:
                    ut = u + L / 2 + 0.8                                           # the truck's rear is just past the container
                    if ut < e["len"] - 4.0:
                        s_stop = ut if d == 1 else e["len"] - ut
                        sites.append({"x": px, "y": py, "yaw": math.atan2(dy, dx), "edge": ei, "d": d, "s": s_stop,
                                      "cap": 0.5 + 1.1 * r.random(), "kind": KIND, "name": "", "ox": px, "oy": py, "u": u,
                                      "col": r.choice(((52, 112, 72), (52, 112, 72), (52, 112, 72), (46, 84, 148), (96, 100, 106))),
                                      "seed": r.randrange(1 << 20)})
                u += r.uniform(*SPACING)
    return sites


def site_for_worker(st):
    """The few fields the traffic worker needs of a site (it never draws)."""
    return {k: st[k] for k in ("x", "y", "edge", "d", "s", "kind", "name", "ox", "oy")}


# ------------------------------------------------------------------------------------------------- the main-process side
def _smooth(a):
    a = max(0.0, min(1.0, a))
    return a * a * (3.0 - 2.0 * a)


class Job:
    """One truck emptying one container."""

    def __init__(self, g, si, car):
        self.si, self.car, self.t = si, car, 0.0
        self.crew = []
        self.pose = None             # (x, y, yaw, lift, tilt) of the container while it is away from its place
        self.dumped = False
        self.snd = set()
        st = g.sites[si]
        self.home = (st["x"], st["y"], st["yaw"])
        self.fill0 = g.fill(si)


class Garbage:
    # job timeline (seconds from the truck standing still)
    T_WALK, T_PULL, T_DOCK, T_LIFT, T_DUMP, T_LOWER, T_BACK, T_RETURN, T_END = 0.0, 4.0, 9.5, 11.0, 15.5, 17.5, 20.5, 26.0, 31.0

    def __init__(self, sim, sites=None):
        self.sim = sim
        self.sites = sites if sites is not None else make_sites(sim.w)
        self.t = 0.0
        self.emptied = {}            # site index -> time of the last emptying
        self.grid = {}
        for i, st in enumerate(self.sites):
            self.grid.setdefault((int(st["x"] // GRID), int(st["y"] // GRID)), []).append(i)
        self.jobs = {}               # site index -> Job
        self.done = {}               # id(car) -> site index it has emptied (one job per stop)
        self.rng = random.Random(77)
        self.stink_t = 0.0

    # ------------------------------------------------------------------ container state
    def fill(self, i):
        st = self.sites[i]
        t0 = self.emptied.get(i)
        if t0 is None:
            return st["cap"]
        return min(st["cap"], max(0.0, (self.t - t0) / FILL_T) * st["cap"])

    def near(self, x0, y0, x1, y1):
        """Indices of the containers inside the rectangle."""
        out = []
        for cx in range(int(x0 // GRID), int(x1 // GRID) + 1):
            for cy in range(int(y0 // GRID), int(y1 // GRID) + 1):
                out.extend(self.grid.get((cx, cy), ()))
        return out

    # ------------------------------------------------------------------ update
    def update(self, dt):
        sim = self.sim
        self.t += dt
        fx, fy = sim.focus()[:2]
        cars = sim.traffic.cars
        stn = sim.stations
        trk = truck_kind()
        live = set()
        for c in cars:
            if c.kind != trk or c.stn is None or c.dwell is None:
                continue
            si = stn.garbage_index(c.stn)
            if si is None:
                continue
            live.add(si)
            job = self.jobs.get(si)
            if job is None:
                if self.done.get(id(c)) == si:
                    continue
                if (c.x - fx) ** 2 + (c.y - fy) ** 2 > 110.0 ** 2:
                    self.emptied[si] = self.t                         # unwatched: the bin is just emptied
                    self.done[id(c)] = si
                    continue
                if abs(c.v) > 0.5:
                    continue
                job = self.jobs[si] = Job(self, si, c)
                self._start(job)
            if job.car is c:
                self._step(job, dt)
        for si in [s for s, j in self.jobs.items() if s not in live or j.car not in cars or j.t > self.T_END + 0.5]:
            self._finish(self.jobs.pop(si), si)
        if len(self.done) > 200:
            self.done.clear()
        self._stink(dt, fx, fy)

    def _crew_ped(self, job, k):
        import actors
        sim = self.sim
        p = actors.Ped()
        p.arch = vehicles.PED_IDS.index("Komunalec")
        p.shirt, p.skin = sim.rng.randrange(3), sim.rng.randrange(4)
        c = job.car
        p.mode, p.v, p.t = "play", 0.0, 0.0
        p.gz = c.gz
        p.hp, p.work_role = 150.0, "garbage"
        p.x, p.y, p.h = c.x, c.y, c.h
        p.vx = p.vy = 0.0
        return p

    def _start(self, job):
        job.crew = [self._crew_ped(job, 0), self._crew_ped(job, 1)]
        self.sim.ev("gsfx", name="truck_reverse_beep", x=job.car.x, y=job.car.y, vol=0.5)

    def _finish(self, job, si):
        sim = self.sim
        peds = sim.peds.list
        for p in job.crew:
            if p in peds:
                peds.remove(p)
        job.crew = []
        if job.dumped or job.t > self.T_DUMP:
            self.emptied[si] = self.t
        self.done[id(job.car)] = si

    # truck geometry
    @staticmethod
    def _frame(c):
        L, W = vehicles.DIMS[c.kind][0], vehicles.DIMS[c.kind][1]
        fx_, fy_ = math.cos(c.h), math.sin(c.h)
        nx_, ny_ = -fy_, fx_                                           # towards the kerb side (the container's side)
        return L, W, fx_, fy_, nx_, ny_

    def _step(self, job, dt):
        sim = self.sim
        c = job.car
        st = self.sites[job.si]
        job.t += dt
        t = job.t
        L, W, fx_, fy_, nx_, ny_ = self._frame(c)
        rear = (c.x - fx_ * (L / 2 + 0.95), c.y - fy_ * (L / 2 + 0.95))     # where the lifter holds the container
        door = (c.x + fx_ * (L / 2 - 1.9) + nx_ * (W / 2 + 0.45), c.y + fy_ * (L / 2 - 1.9) + ny_ * (W / 2 + 0.45))
        hx, hy, hyaw = job.home
        ryaw = math.atan2(fy_, fx_) - math.pi / 2                          # at the lifter its hinge side faces the truck
        grip = (hx - nx_ * (BODY_D / 2 + 0.45), hy - ny_ * (BODY_D / 2 + 0.45))   # the loader's place on the road side of the container
        ctl = (rear[0] + nx_ * (W / 2 + 0.45), rear[1] + ny_ * (W / 2 + 0.45))
        a, b = job.crew
        lift = tilt = 0.0
        if t < self.T_PULL:
            k = _smooth((t - self.T_WALK) / (self.T_PULL - self.T_WALK))
            self._walk(a, door, grip, k, t)
            self._walk(b, door, ctl, k, t)
            cx_, cy_, cyaw = hx, hy, hyaw
        elif t < self.T_DOCK:                                              # A pulls the container to the lifter, walking beside it
            k = _smooth((t - self.T_PULL) / (self.T_DOCK - self.T_PULL))
            cx_, cy_ = hx + (rear[0] - hx) * k, hy + (rear[1] - hy) * k
            cyaw = hyaw + _angdiff(hyaw, ryaw) * k
            self._place(a, grip[0] + (rear[0] + nx_ * 0.9 - grip[0]) * k, grip[1] + (rear[1] + ny_ * 0.9 - grip[1]) * k, math.atan2(cy_ - a.y, cx_ - a.x), moving=True)
            self._place(b, *ctl, math.atan2(rear[1] - ctl[1], rear[0] - ctl[0]), moving=False)
        elif t < self.T_LIFT:
            cx_, cy_, cyaw = rear[0], rear[1], ryaw
            self._place(a, rear[0] + nx_ * 0.9, rear[1] + ny_ * 0.9, math.atan2(rear[1] - a.y, rear[0] - a.x), moving=False)
            self._place(b, *ctl, math.atan2(rear[1] - ctl[1], rear[0] - ctl[0]), moving=False)
            self._once(job, "lift", "garbage_truck", rear, 0.9)
        elif t < self.T_DUMP:                                              # up and over the hopper
            k = _smooth((t - self.T_LIFT) / (self.T_DUMP - self.T_LIFT))
            lift, tilt = k, k
            cx_, cy_, cyaw = rear[0], rear[1], ryaw
            self._place(a, rear[0] + nx_ * 0.9, rear[1] + ny_ * 0.9, a.h, moving=False)
            self._place(b, *ctl, b.h, moving=False)
        elif t < self.T_LOWER:                                             # shaking the rest out
            lift, tilt = 1.0, 1.0 + 0.05 * math.sin((t - self.T_DUMP) * 22.0)
            cx_, cy_, cyaw = rear[0], rear[1], ryaw
            if not job.dumped:
                job.dumped = True
                self.emptied[job.si] = self.t
                sim.ev("gsfx", name="bin_clang", x=rear[0], y=rear[1], vol=0.9)
                sim.ev("garbage_dump", x=rear[0], y=rear[1], z=2.6)
            self._place(a, rear[0] + nx_ * 0.9, rear[1] + ny_ * 0.9, a.h, moving=False)
            self._place(b, *ctl, b.h, moving=False)
        elif t < self.T_BACK:
            k = _smooth((t - self.T_LOWER) / (self.T_BACK - self.T_LOWER))
            lift = tilt = 1.0 - k
            cx_, cy_, cyaw = rear[0], rear[1], ryaw
            self._place(a, rear[0] + nx_ * 0.9, rear[1] + ny_ * 0.9, a.h, moving=False)
            self._place(b, *ctl, b.h, moving=False)
            if k > 0.9:
                self._once(job, "clang2", "bin_clang", rear, 0.7)
        elif t < self.T_RETURN:                                            # rolled back empty
            k = _smooth((t - self.T_BACK) / (self.T_RETURN - self.T_BACK))
            cx_, cy_ = rear[0] + (hx - rear[0]) * k, rear[1] + (hy - rear[1]) * k
            cyaw = ryaw + _angdiff(ryaw, hyaw) * k
            self._place(a, (rear[0] + nx_ * 0.9) + (grip[0] - rear[0] - nx_ * 0.9) * k, (rear[1] + ny_ * 0.9) + (grip[1] - rear[1] - ny_ * 0.9) * k,
                        math.atan2(cy_ - a.y, cx_ - a.x), moving=True)
            self._place(b, *ctl, b.h, moving=False)
        else:                                                              # back to the cab
            k = _smooth((t - self.T_RETURN) / (self.T_END - self.T_RETURN))
            cx_, cy_, cyaw = hx, hy, hyaw
            self._walk(a, grip, door, k, t)
            self._walk(b, ctl, door, k, t)
            if k > 0.97:
                peds = sim.peds.list
                for p in (a, b):
                    if p in peds:
                        peds.remove(p)
        peds = sim.peds.list
        if t > self.T_WALK + 0.3:
            for p in job.crew:
                if p not in peds and t < self.T_RETURN + (self.T_END - self.T_RETURN) * 0.97:
                    p.gz = c.gz
                    peds.append(p)
        fill = job.fill0 * (0.0 if job.dumped else 1.0)
        if self.T_LIFT < t < self.T_DUMP:
            fill = job.fill0 * (1.0 - _smooth((tilt - 0.45) / 0.5))
        job.pose = (cx_, cy_, cyaw, lift, tilt, fill)

    def _once(self, job, key, name, at, vol):
        if key not in job.snd:
            job.snd.add(key)
            self.sim.ev("gsfx", name=name, x=at[0], y=at[1], vol=vol)

    def _place(self, p, x, y, h, moving):
        if p.mode != "play":
            return
        sim = self.sim
        dx, dy = x - p.x, y - p.y
        p.x, p.y = x, y
        p.h = h
        p.v = WALK_V if moving else 0.0
        if moving:
            p.anim += 0.016 * 3.0
        p.gz = sim.w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
        p.vx = p.vy = 0.0

    def _walk(self, p, a, b, k, t):
        if p.mode != "play":
            return
        x, y = a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
        moving = 0.0 < k < 1.0
        self._place(p, x, y, math.atan2(b[1] - a[1], b[0] - a[0]) if (a[0] != b[0] or a[1] != b[1]) else p.h, moving)

    # ------------------------------------------------------------------ stink
    def _stink(self, dt, fx, fy):
        self.stink_t -= dt
        if self.stink_t > 0:
            return
        self.stink_t = 0.22
        sim = self.sim
        for i in self.near(fx - 42.0, fy - 42.0, fx + 42.0, fy + 42.0):
            st = self.sites[i]
            if (st["x"] - fx) ** 2 + (st["y"] - fy) ** 2 > 42.0 ** 2:
                continue
            f = self.fill(i)
            if f < 0.55 or self.rng.random() > 0.5 * min(1.5, f):
                continue
            sim.ev("stink", x=st["x"] + self.rng.uniform(-0.4, 0.4), y=st["y"] + self.rng.uniform(-0.3, 0.3), z=1.1 + 0.5 * min(1.0, f), n=1)

    # ------------------------------------------------------------------ drawing (renderer calls these)
    def draw(self, rl, V3, gy_of, rect, t, cam_xy):
        """Containers inside the rectangle, with their litter and flies."""
        pad = 4.0
        jobs_by_site = self.jobs
        for i in self.near(rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad):
            st = self.sites[i]
            if not (rect[0] - pad < st["x"] < rect[2] + pad and rect[1] - pad < st["y"] < rect[3] + pad):
                continue
            job = jobs_by_site.get(i)
            if job is not None and job.pose is not None:
                x, y, yaw, lift, tilt, fill = job.pose
            else:
                x, y, yaw, lift, tilt, fill = st["x"], st["y"], st["yaw"], 0.0, 0.0, self.fill(i)
            near = (x - cam_xy[0]) ** 2 + (y - cam_xy[1]) ** 2 < 55.0 ** 2
            self._draw_one(rl, V3, st, x, y, gy_of(x, y), yaw, lift, tilt, fill, t, near)
            if job is not None and job.pose is not None:
                self._draw_rails(rl, V3, job, gy_of)
            if near and fill > 0.7:
                self._flies(rl, V3, x, y, gy_of(x, y) + 1.7 + lift * 1.4, t, st["seed"], fill)

    def _draw_one(self, rl, V3, st, x, y, gy, yaw, lift, tilt, fill, t, near):
        col = st["col"]
        C = rl.Color
        body, dark = C(col[0], col[1], col[2], 255), C(int(col[0] * 0.6), int(col[1] * 0.6), int(col[2] * 0.6), 255)
        rl.rl_push_matrix()
        rl.rl_translatef(x, gy + lift * 1.7, y)
        rl.rl_rotatef(-math.degrees(yaw), 0.0, 1.0, 0.0)
        if tilt:                                                           # tip over the top rail at the back of the lifter
            rl.rl_translatef(0.0, BODY_H, BODY_D / 2)
            rl.rl_rotatef(math.degrees(tilt) * 128.0 / 57.2958, 1.0, 0.0, 0.0)
            rl.rl_translatef(0.0, -BODY_H, -BODY_D / 2)
        rl.draw_cube(V3(0, 0.18 + (BODY_H - 0.18) / 2, 0), BODY_W, BODY_H - 0.18, BODY_D, body)
        rl.draw_cube(V3(0, 0.12, 0), BODY_W * 0.94, 0.12, BODY_D * 0.9, C(40, 40, 42, 255))                 # chassis frame
        for sx in (-1, 1):
            rl.draw_cube(V3(sx * (BODY_W / 2 - 0.12), 0.09, BODY_D / 2 - 0.12), 0.1, 0.18, 0.1, C(20, 20, 22, 255))   # wheels
            rl.draw_cube(V3(sx * (BODY_W / 2 - 0.12), 0.09, -BODY_D / 2 + 0.12), 0.1, 0.18, 0.1, C(20, 20, 22, 255))
        rl.draw_cube(V3(0, BODY_H * 0.55, BODY_D / 2 + 0.01), BODY_W * 0.96, 0.05, 0.02, dark)               # rib
        overflow = fill > 1.0
        lid_open = fill > 0.75 and not (tilt and fill < 0.1)
        if lid_open:                                                       # lid propped up by the heap
            rl.rl_push_matrix()
            rl.rl_translatef(0.0, BODY_H, BODY_D / 2)
            rl.rl_rotatef(62.0 if overflow else 38.0, 1.0, 0.0, 0.0)
            rl.draw_cube(V3(0, 0.02, -BODY_D / 2 * 1.02), BODY_W * 1.02, 0.05, BODY_D * 1.02, dark)
            rl.rl_pop_matrix()
        else:
            rl.draw_cube(V3(0, BODY_H + 0.02, 0), BODY_W * 1.04, 0.06, BODY_D * 1.04, dark)
        if fill > 0.12:
            rng = random.Random(st["seed"])
            n = int(2 + 6 * min(fill, 1.6)) if near else int(2 + 3 * min(fill, 1.6))
            for k in range(n):                                             # the heap: bags, boxes, rubbish, higher the fuller
                cx_ = rng.uniform(-0.5, 0.5) * BODY_W
                cz_ = rng.uniform(-0.38, 0.38) * BODY_D
                hh = BODY_H - 0.08 + rng.uniform(0.0, 0.32) * min(1.0, fill) * (1.0 if fill > 0.8 else 0.0) + (fill - 1.0) * 0.5 * rng.random() * (fill > 1.0)
                kind = rng.random()
                c = (C(20, 22, 24, 255) if kind < 0.4 else C(214, 216, 210, 255) if kind < 0.6 else C(70, 100, 150, 255) if kind < 0.7
                     else C(170, 130, 84, 255) if kind < 0.9 else C(190, 70, 60, 255))
                sz = rng.uniform(0.22, 0.45)
                rl.draw_cube(V3(cx_, hh + sz / 2 * 0.8, cz_), sz, sz * 0.8, sz * rng.uniform(0.8, 1.2), c)
        rl.rl_pop_matrix()
        if overflow and not (tilt or lift):                                # bags and junk on the ground in front of the bin
            rng = random.Random(st["seed"] + 5)
            ca, sa = math.cos(yaw), math.sin(yaw)
            for k in range(2 + int((fill - 1.0) * 6) + (1 if near else 0)):
                lx, lz = rng.choice((-1, 1)) * rng.uniform(0.9, 1.7), rng.uniform(-0.3, 0.5)
                wx, wz = x + ca * lx - sa * lz, y + sa * lx + ca * lz
                sz = rng.uniform(0.25, 0.5)
                c = C(20, 22, 24, 255) if rng.random() < 0.5 else C(214, 216, 210, 255) if rng.random() < 0.6 else C(170, 130, 84, 255)
                rl.draw_cube(V3(wx, gy + sz * 0.35, wz), sz, sz * 0.7, sz * 0.9, c)

    def _draw_rails(self, rl, V3, job, gy_of):
        c = job.car
        L, W, fx_, fy_, nx_, ny_ = self._frame(c)
        gy = gy_of(c.x, c.y)
        x, y = c.x - fx_ * (L / 2 + 0.55), c.y - fy_ * (L / 2 + 0.55)
        lift = job.pose[3]
        C = rl.Color
        for s in (-0.8, 0.8):                                              # the lifter's arms: two vertical rails behind the truck
            rl.draw_cube(V3(x + nx_ * s, gy + 1.5, y + ny_ * s), 0.1, 3.0, 0.1, C(70, 72, 78, 255))

    def _flies(self, rl, V3, x, y, gy, t, seed, fill):
        C = rl.Color(12, 12, 12, 255)
        for k in range(3 + int(fill * 2)):
            ph = seed * 0.37 + k * 2.1
            a = t * (3.0 + k * 0.9) + ph
            r = 0.35 + 0.25 * math.sin(t * 2.3 + ph * 1.7)
            rl.draw_cube(V3(x + math.cos(a) * r, gy + 0.2 * math.sin(a * 2.4 + ph), y + math.sin(a * 1.3 + ph) * r), 0.05, 0.05, 0.05, C)

    def draw_beacons(self, rl, V3, cars, gy_of, rect, t, soft_id):
        """Rotating amber lights on the roofs of the garbage trucks: a bright flash sweeps round every 0.8 s."""
        trk = truck_kind()
        L = vehicles.DIMS[trk][0]
        roof = min(vehicles.DIMS[trk][4] - 0.06, vehicles.DIMS[trk][3] + 1.69)       # the cab roof, as gl3d builds it
        C = rl.Color
        flash = []
        for c in cars:
            if c.kind != trk or not (rect[0] - 6.0 < c.x < rect[2] + 6.0 and rect[1] - 6.0 < c.y < rect[3] + 6.0):
                continue
            fx_, fy_ = math.cos(c.h), math.sin(c.h)
            bx, by = c.x + fx_ * (L / 2 - 1.12), c.y + fy_ * (L / 2 - 1.12)
            gy = (c.gz if c.gz is not None else gy_of(c.x, c.y)) + roof - 0.04
            ph = (t * 7.5 + (id(c) % 7)) % 6.2832
            rl.draw_cube(V3(bx, gy, by), 0.34, 0.12, 0.34, C(120, 80, 10, 255))
            rl.draw_cube(V3(bx, gy + 0.16, by), 0.24, 0.2, 0.24, C(255, 176, 20, 255))
            for s in (0, 1):                                               # two opposite beams turn about the lamp
                a = ph + s * math.pi
                k = max(0.0, math.cos(a))
                if k > 0.05:
                    flash.append((bx + math.cos(a) * 0.6, gy + 0.26, by + math.sin(a) * 0.6, k))
        if not flash:
            return
        rl.rl_draw_render_batch_active()
        rl.rl_active_texture_slot(0)
        rl.rl_disable_depth_mask()
        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
        rl.rl_set_texture(soft_id)
        rl.rl_begin(rl.RL_QUADS)
        for x, y, z, k in flash:
            h = 0.55 + 1.5 * k
            rl.rl_color4ub(255, 170, 20, int(255 * k))
            for u, v, ox, oz in ((0, 0, -1, -1), (1, 0, 1, -1), (1, 1, 1, 1), (0, 1, -1, 1)):
                rl.rl_tex_coord2f(u, v)
                rl.rl_vertex3f(x + ox * h * 0.5, y, z + oz * h * 0.5)
        rl.rl_end()
        rl.end_blend_mode()
        rl.rl_set_texture(0)
        rl.rl_enable_depth_mask()


def _angdiff(a, b):
    d = (b - a + math.pi) % (2 * math.pi) - math.pi
    return d
