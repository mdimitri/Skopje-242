"""Emergency services: an ambulance drives to a run-over / dead person (or the player) and revives them, a fire engine
drives to a burning or burnt-out car and puts it out. Routes are planned by travel time on the drivable road graph and the
vehicles are ordinary physics Bodies steered by a small pure-pursuit controller (their `ctl` = (throttle, steer, handbrake))."""
from texts import TXT
import heapq
import math
import random

import numpy as np

import actors
from driving import brake_speed, edge_seconds, fastest_route, follow_speed, road_control_speed, turn_indicator
from roadwidth import half_width, lane_count
import slang
import vehicles

AMBULANCE, FIRE_ENGINE = 48, 49
MAX_CALLS = 5                                  # emergencies one ambulance / fire engine serves per call-out


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
        self.work_t = 0.0
        self.spray_t = 0.0
        self.said = False
        self.cand = None                 # start nodes still to try, one route search per frame (None = not searched yet)
        self.queue = []                  # more emergencies on the same screen, served one by one before the crew drive off
        self.done = 0
        self.age = 0.0


class Services:
    def __init__(self, sim):
        self.sim = sim
        self.jobs = []
        self.rng = random.Random(404)
        self.amb_on = True
        self.fire_on = True
        self._nodes = None
        self._radj = None

    # ------------------------------------------------------------------ road graph
    def _graph(self):
        if self._radj is not None:
            return
        w = self.sim.w
        nodes, radj = {}, {}
        for i, e in enumerate(w.edges):
            if not e["drive"] or e["a"] not in w.main or e["b"] not in w.main:
                continue
            nodes[e["a"]] = e["pts"][0]
            nodes[e["b"]] = e["pts"][-1]
            radj.setdefault(e["b"], []).append((e["a"], i, 1))
            if not e["ow"]:
                radj.setdefault(e["a"], []).append((e["b"], i, -1))
        self._nodes, self._radj = nodes, radj
        self._node_ids = tuple(nodes)
        self._node_xy = np.asarray(tuple(nodes.values()), dtype=np.float64).reshape(-1, 2)
        self._route_costs = {}
        for entries in radj.values():
            for _, index, direction in entries:
                edge = w.edges[index]
                self._route_costs[index, direction] = (
                    edge_seconds(edge, direction, 13.0, 0),
                    lane_count(edge, direction),
                    3.0 if edge["cls"] == "service" else 0.0,
                )

    def _nearest_node(self, x, y):
        if not self._node_ids:
            return None
        delta = self._node_xy - (x, y)
        d2 = np.square(delta[:, 0]) + np.square(delta[:, 1])
        i = int(np.argmin(d2))
        return self._node_ids[i] if d2[i] < 1e18 else None

    def _route_delay(self, move):
        cost = self._route_costs.get(move)
        if cost is None:
            i, d = move
            edge = self.sim.w.edges[i]
            lanes = lane_count(edge, d)
            surcharge = 3.0 if edge["cls"] == "service" else 0.0
        else:
            _, lanes, surcharge = cost
        return 2.2 * self.sim.traffic.queue.get(move, 0) / lanes + surcharge

    def route(self, x0, y0, x1, y1):
        """Legal lane waypoints (x, y, speed) from the nearest network node to the call."""
        self._graph()
        if not self._nodes:
            return []
        w = self.sim.w
        a, b = self._nearest_node(x0, y0), self._nearest_node(x1, y1)
        if a is None or b is None:
            return []
        path = fastest_route(w, a, b, self._nodes[b], speed_cap=13.0, delay=self._route_delay, budget=3500, main_only=True)
        if not path:
            return []
        out = []
        for k, (ei, direction) in enumerate(path):
            e = w.edges[ei]
            length = e["len"]
            speed = min(13.0, e["speed"])
            lane = actors.Traffic.lanes_of(e, direction)[-1]
            # Keep the edge endpoint for turns and sample the lane in between, even on long straight edges.
            count = max(1, math.ceil(length / 7.0))
            for j in range(count + 1):
                if k and j == 0:
                    x, y, old_speed = out[-1]
                    out[-1] = (x, y, min(old_speed, speed))
                    continue
                distance = length * j / count
                s = distance if direction == 1 else length - distance
                x, y, dx, dy = w.edge_point(e, s)
                taper = min(1.0, distance / 6.0 if k else 1.0, (length - distance) / 6.0)
                hw = half_width(e, s)
                clear = max(0.0, hw - max(vehicles.HALF_W[AMBULANCE], vehicles.HALF_W[FIRE_ENGINE]) - 0.35)
                off = min(lane * 2.0 * hw / e["w"], clear) * direction * taper
                out.append((x - dy * off, y + dx * off, speed))
        return out

    def _to(self, x, y, limit=105.0):
        """Estimated driving seconds to the call from nearby dispatch nodes."""
        b = self._nearest_node(x, y)
        dist, pq = {b: 0.0}, [(0.0, b)]
        while pq:
            d, n = heapq.heappop(pq)
            if d > dist.get(n, 1e18) or d > limit:
                continue
            for m, ei, direction in self._radj.get(n, ()):
                move = ei, direction
                seconds, lanes, surcharge = self._route_costs[move]
                delay = 2.2 * self.sim.traffic.queue.get(move, 0) / lanes + surcharge
                nd = d + seconds + delay
                if nd <= limit and nd < dist.get(m, math.inf):
                    dist[m] = nd
                    heapq.heappush(pq, (nd, m))
        return dist

    def _spawn_node(self, x, y, lo=70.0, hi=150.0):
        self._graph()
        fx, fy, _, _ = self.sim.focus()
        c = [p for p in self._nodes.values() if lo < math.hypot(p[0] - x, p[1] - y) < hi and math.hypot(p[0] - fx, p[1] - fy) > 65.0]
        if not c:
            c = [p for p in self._nodes.values() if math.hypot(p[0] - x, p[1] - y) > 80.0]
        return self.rng.choice(c) if c else None

    # ------------------------------------------------------------------ requests
    def request(self, kind, target, x, y, delay=3.5):
        if (kind == "amb" and not self.amb_on) or (kind == "fire" and not self.fire_on):
            return False
        for j in self.jobs:                      # one call-out serves up to MAX_CALLS emergencies that are within one screen of the vehicle
            if j.kind == kind and j.state != "leave":
                if target in j.queue:
                    return True
                if j.target is not target and len(j.queue) + j.done + 1 < MAX_CALLS:
                    if self._on_screen(j, x, y):
                        j.queue.append(target)
                        return True
        for j in self.jobs:
            if j.kind == kind and (j.target is target or math.hypot(j.x - x, j.y - y) < 14.0) and j.state != "leave":
                return True
        if sum(1 for j in self.jobs if j.kind == kind) >= 3:
            return False
        self.jobs.append(Job(kind, target, x, y, delay + self.rng.uniform(0, 3)))
        return True

    def _on_screen(self, j, x, y):
        """(x, y) within one screen of the call-out: inside the camera's ground rectangle, or 90 m of the vehicle / first call."""
        cx, cy = (j.body.x, j.body.y) if j.body is not None else (j.x, j.y)
        vr = getattr(self.sim, "view_rect", None)
        if vr is not None and vr[0] <= x <= vr[2] and vr[1] <= y <= vr[3] and vr[0] <= cx <= vr[2] and vr[1] <= cy <= vr[3]:
            return True
        return math.hypot(cx - x, cy - y) < 90.0

    def has_job_for(self, target):
        return any((j.target is target or target in j.queue) and j.state != "leave" for j in self.jobs)

    # ------------------------------------------------------------------ per-frame
    def update(self, dt):
        sim = self.sim
        for j in list(self.jobs):
            j.age += dt
            try:
                self._step(j, dt)
            except Exception:  # noqa: BLE001 - a broken job must never take the game down
                self._abort(j)
            if j.age > 180 + 60 * j.done:
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
        while j.pi < len(j.path) - 1:
            tx, ty, _ = j.path[j.pi]
            qx, qy, _ = j.path[j.pi + 1]
            dist = math.hypot(tx - b.x, ty - b.y)
            if dist > 3.1 and (dist > 6.0 or (b.x - tx) * (qx - tx) + (b.y - ty) * (qy - ty) < 0.0):
                break
            j.pi += 1
        tx, ty, _ = j.path[j.pi]
        if math.hypot(tx - b.x, ty - b.y) > 30.0:         # missed the turn / pushed off the route: plan a new one from here, over roads
            j.lost = getattr(j, "lost", 0.0) + dt
            if j.lost > 2.0:
                j.lost = 0.0
                new = self.route(b.x, b.y, j.path[-1][0], j.path[-1][1])
                if len(new) > 1:
                    j.path, j.pi = new, 1
                    tx, ty, _ = j.path[1]
        else:
            j.lost = 0.0
        err = _wrap(math.atan2(ty - b.y, tx - b.x) - b.h)
        dend = math.hypot(j.path[-1][0] - b.x, j.path[-1][1] - b.y)
        vmax = vehicles.PERF[b.kind][0] * 0.55
        v = min(v_cruise, vmax, j.path[max(0, j.pi - 1)][2]) * (1.0 - min(0.8, abs(err) / 0.8))
        dist, px, py, signal = 0.0, b.x, b.y, 0
        for i in range(j.pi, min(j.pi + 9, len(j.path))):
            x, y, speed = j.path[i]
            dist += math.hypot(x - px, y - py)
            if 0 < i < len(j.path) - 1:
                ax, ay, _ = j.path[i - 1]
                nx, ny, _ = j.path[i + 1]
                turn = _wrap(math.atan2(ny - y, nx - x) - math.atan2(y - ay, x - ax))
                signal = signal or turn_indicator(turn, dist, vf)
                bend = abs(turn)
                if bend > 0.35:
                    speed = min(speed, 5.5 if bend < 0.85 else 3.8)
            v = min(v, brake_speed(dist - 1.0, 3.0, speed))
            px, py = x, y
        b.signal_turn(signal, dt)
        gap = self._gap(b, 10.0 + max(vf, 0.0) * 2.6)
        if gap is not None:
            v = min(v, follow_speed(*gap))
        v = min(v, road_control_speed(self.sim, b.x, b.y, b.h, vehicles.HALF_L[b.kind], vf))
        if stop_at_end:
            v = min(v, brake_speed(dend - 7.0, 2.5))
        thr = max(-1.0, min(1.0, (v - vf) * 0.7))
        b.ctl = (thr, max(-1.0, min(1.0, err * 1.8)), v < 0.3 and abs(vf) < 0.8)
        return dend < 9.0 and abs(vf) < 1.0

    def _gap(self, b, look):
        """Bumper gap and speed of the nearest obstacle ahead at the same road level."""
        sim = self.sim
        hx, hy = math.cos(b.h), math.sin(b.h)
        rx, ry = -hy, hx
        hw_b, hl_b = vehicles.HALF_W[b.kind] + 0.3, vehicles.HALF_L[b.kind]
        best = None

        def test(ox, oy, hw, hl, oh, height, speed=0.0):
            nonlocal best
            if height is not None and b.az is not None and abs(height - b.az) > 3.0:
                return
            dx, dy = ox - b.x, oy - b.y
            fwd = dx * hx + dy * hy
            if fwd < 0.3 or fwd > look + hl:
                return
            if oh is not None:
                ca, sa = abs(math.cos(oh - b.h)), abs(math.sin(oh - b.h))
                hw, hl = ca * hw + sa * hl, ca * hl + sa * hw
            if abs(dx * rx + dy * ry) > hw + hw_b:
                return
            g = fwd - hl_b - hl
            if best is None or g < best[0]:
                best = (g, max(0.0, speed))

        for o in sim.bodies:
            if o is not b and abs(o.x - b.x) < look + 8 and abs(o.y - b.y) < look + 8:
                test(o.x, o.y, vehicles.HALF_W[o.kind], vehicles.HALF_L[o.kind], o.h, o.az, o.vx * hx + o.vy * hy)
        for c in sim.traffic.cars:
            if abs(c.x - b.x) < look + 8 and abs(c.y - b.y) < look + 8:
                test(c.x, c.y, vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind], c.h, c.gz, c.v * math.cos(c.h - b.h))
        for p in sim.peds.list:
            if p.mode in ("walk", "flee", "rage", "brawl") and abs(p.x - b.x) < look + 4 and abs(p.y - b.y) < look + 4:
                test(p.x, p.y, 1.2, 0.4, None, p.gz)
        wk = sim.walker
        if wk is not None and sim.mode == "foot":
            test(wk.x, wk.y, 1.2, 0.4, None, wk.az)
        return best

    def _spawn_vehicle(self, j, kind, dest_x, dest_y):
        sim = self.sim
        self._graph()
        fx, fy, _, _ = sim.focus()
        if j.cand is None:                                    # frame 1: the one broad search; the route searches follow one per frame
            candidates = []
            for node, eta in self._to(dest_x, dest_y).items():
                if node not in self._nodes:
                    continue
                x, y = self._nodes[node]
                distance = math.hypot(x - dest_x, y - dest_y)
                if distance > 35.0 and math.hypot(x - fx, y - fy) > 65.0:
                    candidates.append((not 70.0 < distance < 150.0, eta, x, y))
            j.cand = heapq.nsmallest(12, candidates)
            return None
        if not j.cand:
            return False
        for _, _, x, y in [j.cand.pop(0)]:
            path = self.route(x, y, dest_x, dest_y)
            if len(path) < 2:
                continue
            h = math.atan2(path[1][1] - path[0][1], path[1][0] - path[0][0])
            b = actors.Body(path[0][0], path[0][1], h, kind, 0 if kind == AMBULANCE else 3)
            # A stationary probe uses the same collision circles as the vehicle and cannot break props.
            b.az = sim.w.ground_y(b.x, b.y)
            if actors._bld_top(sim.w, b.x, b.y) is not None:
                continue
            actors.collide_static(b, sim.w)
            if math.hypot(b.x - path[0][0], b.y - path[0][1]) > 0.05 or self._gap(b, 6.0) is not None:
                continue
            break
        else:
            return None if j.cand else False                  # this start failed: the next one is tried next frame
        b.empty = False
        b.service = True
        b.siren = self.rng.random() < 0.35                    # lights always, the siren only on some calls (less noise)
        b.ctl = (0.0, 0.0, True)
        sim.bodies.append(b)
        j.body, j.path, j.pi = b, path, 1
        sim.ev("siren_on", x=b.x, y=b.y, kind=kind)
        return True

    @staticmethod
    def _face(c, x, y):
        c.h = math.atan2(y - c.y, x - c.x)

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

    def _next(self, j):
        """Finished one emergency: walk on to the nearest waiting one (state 'work' again), or False if none is left."""
        j.queue = [t for t in j.queue if (t.mode in ("dead", "air") if isinstance(t, actors.Ped)
                                          else t.health <= 0 if isinstance(t, actors.Walker) else not t.out)]
        if not j.queue:
            return False
        j.queue.sort(key=lambda t: (t.x - j.target.x) ** 2 + (t.y - j.target.y) ** 2)
        j.target = j.queue.pop(0)
        j.done += 1
        j.work_t = j.spray_t = 0.0
        j.said = False
        j.state = "work"
        return True

    def _leave(self, j):
        sim = self.sim
        b = j.body
        for c in j.crew:
            c.mode, c.t = "dead", 0.0
        j.crew = []
        sp = self._spawn_node(b.x, b.y, 250, 400)
        path = self.route(b.x, b.y, sp[0], sp[1]) if sp else []
        j.state = "leave"
        j.path, j.pi = path if len(path) > 1 else [(b.x, b.y, 0.0)], 0
        j.age = 100.0 + 60 * j.done

    def _step(self, j, dt):
        sim = self.sim
        w = sim.w
        tgt = j.target
        if j.kind == "amb":
            j.x, j.y = tgt.x, tgt.y
        if j.state == "wait":
            j.t -= dt
            if j.t <= 0:
                ok = self._spawn_vehicle(j, AMBULANCE if j.kind == "amb" else FIRE_ENGINE, j.x, j.y)
                if ok is None:                                   # still searching: one step per frame
                    return
                if not ok:
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
        if b.exploded or b.health <= 0:                          # burning / burnt out: no more driving, siren off, crew gone
            b.siren, b.ctl = False, None
            for c in j.crew:
                c.mode, c.t = "dead", 0.0
            j.crew = []
            if j in self.jobs:
                self.jobs.remove(j)
            return
        if j.state == "drive":
            if self._ctl(j, dt, 13.0, True):
                j.state = "work"
                j.work_t = 0.0
                b.ctl = (0.0, 0.0, True)
                if j.kind == "amb":
                    self._crew(j, 2, 8, 0)
                    sim.ev("shout", text=self.rng.choice((TXT("services.0001"), TXT("services.0002"), TXT("services.0003"))), x=b.x, y=b.y, who=TXT("services.0004"))
                else:
                    self._crew(j, 3, 6, 0)
                    sim.ev("shout", text=self.rng.choice((TXT("services.0005"), TXT("services.0006"), TXT("services.0007"))), x=b.x, y=b.y, who=TXT("services.0008"))
        elif j.state == "work":
            j.work_t += dt
            b.ctl = (0.0, 0.0, True)
            if j.kind == "amb":
                for i, c in enumerate(j.crew):                        # one medic each side of the patient
                    side = 1 if i == 0 else -1
                    ang = math.atan2(b.y - tgt.y, b.x - tgt.x) + side * 1.25
                    self._walk_to(c, tgt.x + math.cos(ang) * 0.95, tgt.y + math.sin(ang) * 0.95, dt, 4.2)
                    c.pose = None
                    if math.hypot(c.x - tgt.x, c.y - tgt.y) < 1.5:
                        self._face(c, tgt.x, tgt.y)
                arrived = all(math.hypot(c.x - tgt.x, c.y - tgt.y) < 1.5 for c in j.crew)
                if arrived or j.work_t > 25 + math.hypot(b.x - tgt.x, b.y - tgt.y) / 3.0:
                    j.state = "treat"
                    j.work_t = 0.0
            else:
                tgt.fire_lvl = max(0.0, 1.0 - max(0.0, j.work_t - 2.5) / 7.0)      # the flames die down while they spray
                for i, c in enumerate(j.crew):
                    ang = math.atan2(b.y - tgt.y, b.x - tgt.x) + (i - 1) * 0.8
                    d = self._walk_to(c, tgt.x + math.cos(ang) * 6.5, tgt.y + math.sin(ang) * 6.5, dt, 4.4)
                    c.pose = None
                    if d < 0.8:
                        self._face(c, tgt.x, tgt.y)
                        c.pose = "spray"                                  # nozzle out, water on the flames
                        if i == 0 and j.work_t > 1.0:
                            pass
                        sim.ev("spray", x0=c.x, y0=c.y, x1=tgt.x, y1=tgt.y)
                spraying = [c for c in j.crew if c.pose == "spray"]
                if spraying:
                    j.spray_t += dt
                if j.spray_t > 8.0 or j.work_t > 40 + math.hypot(b.x - tgt.x, b.y - tgt.y) / 3.0:
                    tgt.out = True
                    tgt.fire_lvl = 0.0
                    if not tgt.exploded:
                        tgt.health = max(tgt.health, 12.0)
                        tgt.burn = 0.0
                        tgt.dirty = True
                    for c in j.crew:
                        c.pose = None
                    sim.stats["fires_out"] = sim.stats.get("fires_out", 0) + 1
                    sim.ev("extinguished", x=tgt.x, y=tgt.y)
                    if not self._next(j):
                        self._leave(j)
        elif j.state == "treat":
            j.work_t += dt
            for i, c in enumerate(j.crew):
                c.pose = "cpr"                                        # kneeling over the patient, pumping the chest
                c.anim = j.work_t * (2.0 + i * 0.3)
                self._face(c, tgt.x, tgt.y)
            if int(j.work_t * 2) != int((j.work_t - dt) * 2):
                sim.ev("cpr", x=tgt.x, y=tgt.y)
            if j.work_t > 0.6 and not j.said:
                j.said = True
                sim.ev("shout", text=self.rng.choice((TXT("services.0009"), TXT("services.0010"), TXT("services.0011"))), x=tgt.x, y=tgt.y, who=TXT("services.0012"))
            if j.work_t > 5.5:
                for c in j.crew:
                    c.pose = None
                self._revive(tgt)
                sim.ev("shout", text=self.rng.choice((TXT("services.0013"), TXT("services.0014"), TXT("services.0015"))), x=tgt.x, y=tgt.y, who=TXT("services.0016"))
                if not self._next(j):
                    self._leave(j)
        elif j.state == "leave":
            if self._ctl(j, dt, 13.0, False) or math.hypot(b.x - sim.focus()[0], b.y - sim.focus()[1]) > 330:
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
