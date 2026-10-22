"""Emergency services: an ambulance drives to a run-over / dead person (or the player) and revives them, a fire engine
drives to a burning or burnt-out car and puts it out.  Routes are planned on the drivable road graph (Dijkstra) and the
vehicles are ordinary physics Bodies steered by a small pure-pursuit controller (their `ctl` = (throttle, steer, handbrake))."""
import heapq
import math
import random

import actors
import slang
import vehicles

AMBULANCE, FIRE_ENGINE = 48, 49


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


class Job:
    def __init__(self, kind, target, x, y, delay):
        self.kind = kind                 # "amb" | "fire"
        self.target = target             # Ped / Walker / Body
        self.x, self.y = x, y
        self.state = "wait"
        self.t = delay
        self.body = None
        self.crew = []
        self.path = []
        self.pi = 0
        self.stuck = 0.0
        self.rev = 0.0
        self.work_t = 0.0
        self.age = 0.0


class Services:
    def __init__(self, sim):
        self.sim = sim
        self.jobs = []
        self.rng = random.Random(404)
        self.amb_on = True
        self.fire_on = True
        self._nodes = None
        self._adj = None

    # ------------------------------------------------------------------ road graph
    def _graph(self):
        if self._adj is not None:
            return
        w = self.sim.w
        nodes, adj = {}, {}
        for i, e in enumerate(w.edges):
            if not e["drive"] or e["len"] < 1:
                continue
            nodes[e["a"]] = e["pts"][0]
            nodes[e["b"]] = e["pts"][-1]
            adj.setdefault(e["a"], []).append((e["b"], i, 1))
            if not e["ow"]:
                adj.setdefault(e["b"], []).append((e["a"], i, -1))
        self._nodes, self._adj = nodes, adj

    def _nearest_node(self, x, y):
        best, bn = 1e18, None
        for n, p in self._nodes.items():
            d = (p[0] - x) ** 2 + (p[1] - y) ** 2
            if d < best:
                best, bn = d, n
        return bn

    def route(self, x0, y0, x1, y1):
        """Dijkstra from the node nearest (x0,y0) to the node nearest (x1,y1) -> list of (x, y) waypoints, or []"""
        self._graph()
        if not self._nodes:
            return []
        w = self.sim.w
        a, b = self._nearest_node(x0, y0), self._nearest_node(x1, y1)
        if a is None or b is None:
            return []
        dist, prev = {a: 0.0}, {}
        pq = [(0.0, a)]
        while pq:
            d, n = heapq.heappop(pq)
            if n == b:
                break
            if d > dist.get(n, 1e18):
                continue
            for m, ei, sgn in self._adj.get(n, ()):
                nd = d + w.edges[ei]["len"]
                if nd < dist.get(m, 1e18):
                    dist[m] = nd
                    prev[m] = (n, ei, sgn)
                    heapq.heappush(pq, (nd, m))
        if b not in dist:
            return []
        segs, n = [], b
        while n != a:
            p, ei, sgn = prev[n]
            pts = w.edges[ei]["pts"]
            segs.append(pts if sgn == 1 else pts[::-1])
            n = p
        out = []
        for s in reversed(segs):
            out.extend(s)
        # drop points closer than 3 m so the pursuit controller does not zig-zag
        res = [out[0]]
        for q in out[1:]:
            if math.hypot(q[0] - res[-1][0], q[1] - res[-1][1]) > 3.0:
                res.append(q)
        return res

    def _spawn_node(self, x, y, lo=240.0, hi=380.0):
        self._graph()
        c = [p for p in self._nodes.values() if lo < math.hypot(p[0] - x, p[1] - y) < hi]
        if not c:
            c = [p for p in self._nodes.values() if math.hypot(p[0] - x, p[1] - y) > 80.0]
        return self.rng.choice(c) if c else None

    # ------------------------------------------------------------------ requests
    def request(self, kind, target, x, y, delay=3.5):
        if (kind == "amb" and not self.amb_on) or (kind == "fire" and not self.fire_on):
            return False
        for j in self.jobs:
            if j.kind == kind and (j.target is target or math.hypot(j.x - x, j.y - y) < 14.0) and j.state != "leave":
                return True
        if sum(1 for j in self.jobs if j.kind == kind) >= 2:
            return False
        self.jobs.append(Job(kind, target, x, y, delay + self.rng.uniform(0, 3)))
        return True

    def has_job_for(self, target):
        return any(j.target is target and j.state != "leave" for j in self.jobs)

    # ------------------------------------------------------------------ per-frame
    def update(self, dt):
        sim = self.sim
        for j in list(self.jobs):
            j.age += dt
            try:
                self._step(j, dt)
            except Exception:  # noqa: BLE001 - a broken job must never take the game down
                self._abort(j)
            if j.age > 180:
                self._abort(j)

    def _abort(self, j):
        sim = self.sim
        for c in j.crew:
            c.mode, c.t = "dead", 0.0               # removed by the ped update next frame
        if j.body is not None and j.body in sim.bodies and not j.body.player_car:
            sim.bodies.remove(j.body)
        if j in self.jobs:
            self.jobs.remove(j)

    def _ctl(self, j, dt, v_cruise, stop_at_end):
        """Pure pursuit along j.path. Returns True when the end was reached."""
        b = j.body
        fx, fy = math.cos(b.h), math.sin(b.h)
        vf = b.vx * fx + b.vy * fy
        while j.pi < len(j.path) - 1 and math.hypot(j.path[j.pi][0] - b.x, j.path[j.pi][1] - b.y) < 7.0:
            j.pi += 1
        tx, ty = j.path[j.pi]
        err = _wrap(math.atan2(ty - b.y, tx - b.x) - b.h)
        dend = math.hypot(j.path[-1][0] - b.x, j.path[-1][1] - b.y)
        vmax = vehicles.PERF[b.kind][0] * 0.62
        v = min(v_cruise, vmax) * (1.0 - min(0.75, abs(err) / 1.1))
        if stop_at_end:
            v = min(v, max(0.0, (dend - 7.0) * 0.55))
        if j.rev > 0:                                 # reversing out of a jam
            j.rev -= dt
            b.ctl = (-1.0, -max(-1.0, min(1.0, err * 2)), False)
            return False
        thr = max(-1.0, min(1.0, (v - vf) * 0.7))
        b.ctl = (thr, max(-1.0, min(1.0, err * 1.8)), stop_at_end and dend < 9.0 and v < 0.5)
        if abs(vf) < 0.6 and v > 2.5:
            j.stuck += dt
            if j.stuck > 3.0:
                j.stuck, j.rev = 0.0, 1.6
            if j.age > 60 and j.stuck > 2.0:        # hopelessly jammed: skip ahead a bit
                j.pi = min(len(j.path) - 1, j.pi + 2)
                b.x, b.y = j.path[j.pi]
        else:
            j.stuck = 0.0
        return dend < 9.0 and abs(vf) < 1.0

    def _spawn_vehicle(self, j, kind, dest_x, dest_y):
        sim = self.sim
        fx, fy, _, _ = sim.focus()
        sp = self._spawn_node(dest_x, dest_y)
        if sp is None:
            return False
        path = self.route(sp[0], sp[1], dest_x, dest_y)
        if len(path) < 2:
            return False
        h = math.atan2(path[1][1] - path[0][1], path[1][0] - path[0][0])
        b = actors.Body(path[0][0], path[0][1], h, kind, 0 if kind == AMBULANCE else 3)
        b.empty = False
        b.service = True
        b.siren = self.rng.random() < 0.35                    # lights always, the siren only on some calls (less noise)
        b.ctl = (0.0, 0.0, True)
        sim.bodies.append(b)
        j.body, j.path, j.pi = b, path, 1
        sim.ev("siren_on", x=b.x, y=b.y, kind=kind)
        return True

    def _crew(self, j, n, arch, shirt):
        sim = self.sim
        b = j.body
        lx, ly = math.sin(b.h), -math.cos(b.h)
        for i in range(n):
            p = actors.Ped()
            p.mode, p.t = "svc", 999.0
            p.arch, p.shirt, p.skin = arch, shirt, self.rng.randrange(4)
            p.x, p.y = b.x + lx * 2.0 + math.cos(b.h) * (i * 1.1 - 0.5), b.y + ly * 2.0 + math.sin(b.h) * (i * 1.1 - 0.5)
            p.h = b.h
            sim.peds.list.append(p)
            j.crew.append(p)

    @staticmethod
    def _walk_to(p, gx, gy, dt, sp=3.2):
        dx, dy = gx - p.x, gy - p.y
        d = math.hypot(dx, dy)
        if d > 0.3:
            p.h = math.atan2(dy, dx)
            p.x += dx / d * min(sp * dt, d)
            p.y += dy / d * min(sp * dt, d)
            p.anim += sp * dt
        return d

    def _leave(self, j):
        sim = self.sim
        b = j.body
        for c in j.crew:
            c.mode, c.t = "dead", 0.0
        j.crew = []
        sp = self._spawn_node(b.x, b.y, 250, 400)
        path = self.route(b.x, b.y, sp[0], sp[1]) if sp else []
        j.state = "leave"
        j.path, j.pi = path if len(path) > 1 else [(b.x, b.y), (b.x + 400, b.y)], 0
        j.age = 100.0

    def _step(self, j, dt):
        sim = self.sim
        w = sim.w
        tgt = j.target
        if j.kind == "amb":
            j.x, j.y = tgt.x, tgt.y
        if j.state == "wait":
            j.t -= dt
            if j.t <= 0:
                if not self._spawn_vehicle(j, AMBULANCE if j.kind == "amb" else FIRE_ENGINE, j.x, j.y):
                    self.jobs.remove(j)
                    return
                j.state = "drive"
            return
        b = j.body
        if b is None or b not in sim.bodies or b.player_car:     # vanished or the player stole it
            if b is not None and b.player_car:
                b.service = False
                b.siren = False
            self._abort_light(j)
            return
        if j.state == "drive":
            if self._ctl(j, dt, 17.0, True):
                j.state = "work"
                j.work_t = 0.0
                b.ctl = (0.0, 0.0, True)
                if j.kind == "amb":
                    self._crew(j, 2, 8, 0)
                    sim.ev("shout", text=self.rng.choice(("Брза помош! Место!", "Тргнете се!", "Има ли пулс?")), x=b.x, y=b.y, who="Брза помош")
                else:
                    self._crew(j, 2, 6, 0)
                    sim.ev("shout", text=self.rng.choice(("Пожар! Тргнете се!", "Водата е на пат!", "Гаси го, брате!")), x=b.x, y=b.y, who="Пожарникар")
        elif j.state == "work":
            j.work_t += dt
            b.ctl = (0.0, 0.0, True)
            for i, c in enumerate(j.crew):
                if j.kind == "amb":
                    off = 0.9 + i * 0.6
                    d = self._walk_to(c, tgt.x - 0.3 * (1 - 2 * i) - 0.0, tgt.y + off * (1 if i else -1) * 0.5, dt)
                else:
                    ang = math.atan2(b.y - tgt.y, b.x - tgt.x) + (i - 0.5) * 0.7
                    self._walk_to(c, tgt.x + math.cos(ang) * 6.0, tgt.y + math.sin(ang) * 6.0, dt)
                    if j.work_t > 3.0:
                        c.h = math.atan2(tgt.y - c.y, tgt.x - c.x)
                        sim.ev("spray", x0=c.x, y0=c.y, x1=tgt.x, y1=tgt.y)
            if j.kind == "amb":
                arrived = all(math.hypot(c.x - tgt.x, c.y - tgt.y) < 1.8 for c in j.crew)
                if arrived and j.work_t > 8.0:
                    j.state = "treat"
                    j.work_t = 0.0
                if j.work_t > 25:
                    j.state = "treat"
                    j.work_t = 0.0
            elif j.work_t > 9.0:
                tgt.out = True
                if not tgt.exploded:
                    tgt.health = max(tgt.health, 12.0)
                    tgt.burn = 0.0
                    tgt.dirty = True
                sim.stats["fires_out"] = sim.stats.get("fires_out", 0) + 1
                sim.ev("extinguished", x=tgt.x, y=tgt.y)
                self._leave(j)
        elif j.state == "treat":
            j.work_t += dt
            for c in j.crew:
                c.anim = 0.0
            if j.work_t > 3.5:
                self._revive(tgt)
                sim.ev("shout", text=self.rng.choice(("Жив е! Ајде, стани.", "Пулсот е тука. Бурекот ќе го врати.", "Нема фрка, ќе поживее.")), x=tgt.x, y=tgt.y, who="Брза помош")
                self._leave(j)
        elif j.state == "leave":
            if self._ctl(j, dt, 18.0, False) or math.hypot(b.x - sim.focus()[0], b.y - sim.focus()[1]) > 330:
                self._abort_light(j)

    def _abort_light(self, j):
        sim = self.sim
        for c in j.crew:
            c.mode, c.t = "dead", 0.0
        b = j.body
        if b is not None and b in sim.bodies and not b.player_car:
            sim.bodies.remove(b)
            sim.ev("free_model", model=b.model) if b.model is not None else None
        if j in self.jobs:
            self.jobs.remove(j)

    def _revive(self, t):
        sim = self.sim
        if isinstance(t, actors.Walker):
            t.health = 60.0
            t.cause = None
            t.inv_t = 2.5
            sim.respawn_t = 0.0
            sim.stats["revived"] = sim.stats.get("revived", 0) + 1
            sim.ev("revived")
        else:
            t.hp = 30.0
            t.mode, t.t = "flee", 1.2
            t.vx = t.vy = 0.0
            t.hy = 0.0
            t.spin = 0.0
            sim.stats["revived"] = sim.stats.get("revived", 0) + 1
            sim.ev("revived_ped", x=t.x, y=t.y)
