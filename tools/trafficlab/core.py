"""The lab's simulation: the game's own actors.Sim, run headless around a study area, plus the measurements.

LabSim only observes the game: driving, routing, junction priority, signals, buses, emergency services, trains, level
crossings and pedestrians are the game's code.  What the lab adds is the experiment around it:
  * a study area (the game simulates a ~420 m bubble around the player, so the area is at most 800 x 800 m, centred on
    the hidden player; cars inside it step every frame, as if on screen)
  * edits: closed roads (taken out of the drive graph), obstacles (standing vehicles), per-junction signal changes
  * incidents: collapsing pedestrians (ambulance calls), burning wrecks (fire engine), breakdowns
  * measurements (Metrics): throughput, delay, level of service, queues, stuck cars, gridlock, collisions (the game's
    own box test on the game's own collision boxes), near misses (time to collision), red-light runs, emergency
    response times, the fundamental diagram and heatmaps."""
import collections
import math
import random

import traffic_tuning

from . import params

INP = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 0.0), "run": False, "attack": False,
       "buy": None, "jump": False}
MAX_HALF = 400.0              # bodies (buses, ambulances, wrecks) further than 420 m from the player are removed by Sim
CELL = 20.0                   # heatmap cell (m)
SAMPLE = 5                    # measure every 5th frame (0.25 s)
TTC_MAX = 1.5                 # s: near miss threshold (Hayward / SSAM convention)
LOS_SIG = ((10, "A"), (20, "B"), (35, "C"), (55, "D"), (80, "E"))       # HCM control delay (s/veh), signalised
LOS_UNS = ((10, "A"), (15, "B"), (25, "C"), (35, "D"), (50, "E"))       # unsignalised


def los(delay, signalised):
    for lim, letter in (LOS_SIG if signalised else LOS_UNS):
        if delay <= lim:
            return letter
    return "F"


def default_scenario(world):
    sx, sy, _h = world.spawn
    return {"name": "default", "area": [sx - 300.0, sy - 300.0, sx + 300.0, sy + 300.0], "closures": [], "obstacles": [],
            "junctions": [], "incidents": [], "settings": {}}
# closures: [[x, y]] (edge midpoints), junctions: [{"x", "y", "off", "offset", "green", "cycle"}], obstacles: [[x, y, h, kind]],
# incidents: [[seconds after warm-up, "amb" | "fire" | "breakdown", x, y]] -- the same coordinates the game's tuning file uses


TILE = 700.0                  # a bigger study rectangle is cut into tiles of at most this size, one simulation each


def clamp_area(a):
    """One simulation's area: at most 800 x 800 m (the game's bubble around the player), at least 120 x 120 m."""
    x0, y0, x1, y1 = min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = min(MAX_HALF, max(60.0, (x1 - x0) / 2)), min(MAX_HALF, max(60.0, (y1 - y0) / 2))
    return [cx - hx, cy - hy, cx + hx, cy + hy]


def norm_area(a):
    """The scenario's study rectangle (any size: a junction, a neighbourhood, the whole map)."""
    x0, y0, x1, y1 = min(a[0], a[2]), min(a[1], a[3]), max(a[0], a[2]), max(a[1], a[3])
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = max(60.0, (x1 - x0) / 2), max(60.0, (y1 - y0) / 2)
    return [cx - hx, cy - hy, cx + hx, cy + hy]


def tiles(a):
    """The study rectangle cut into equal tiles of at most TILE x TILE m: each tile is simulated on its own (the game
    only simulates around the player), all tiles x seeds run in parallel, and the report merges them."""
    x0, y0, x1, y1 = norm_area(a)
    nx, ny = max(1, math.ceil((x1 - x0) / TILE - 1e-6)), max(1, math.ceil((y1 - y0) / TILE - 1e-6))
    tw, th = (x1 - x0) / nx, (y1 - y0) / ny
    return [[x0 + i * tw, y0 + j * th, x0 + (i + 1) * tw, y0 + (j + 1) * th] for j in range(ny) for i in range(nx)]


def live_area(sc):
    """The tile this run simulates: scenario["tile"] (the UI's live tile, or a batch job's tile)."""
    ts = tiles(sc["area"])
    return clamp_area(ts[max(0, min(len(ts) - 1, int(sc.get("tile", 0))))])


class Metrics:
    """Everything measured inside the study area.  summary() gives the numbers the report compares."""

    def __init__(self, lab):
        self.lab = lab
        self.t = 0.0                                     # measured seconds
        self.vkt = 0.0                                   # vehicle-metres travelled
        self.vht = 0.0                                   # vehicle-seconds in the area
        self.delay = 0.0                                 # vehicle-seconds lost against each driver's free speed
        self.samples = self.stopped = self.stuck4 = self.stuck4_nored = 0
        self.ratio_sum = 0.0
        self.speed_hist = [0] * 30                       # 2 m/s bins
        self.car = {}                                    # Car -> per-vehicle state (keyed by the object: ids are reused)
        self.trips = []                                  # (seconds in area, metres, delay) of cars that left
        self.jams = []                                   # (t, x, y, seconds) standing > 25 s outside a red queue
        self.passes = collections.Counter()              # junction node -> vehicles through it
        self.cdelay = collections.defaultdict(list)      # node -> control delays (s)
        self.queue_max = collections.defaultdict(float)  # (edge, dir) -> longest queue (m)
        self.queue_sum = collections.defaultdict(float)  # (edge, dir) -> sum of queue length over samples
        self.queue_node = {}                             # (edge, dir) -> junction it queues for
        self.nq = 0
        self.redruns = []                                # (t, x, y, node)
        self.collisions = []                             # (t, x, y, depth, kinds)
        self._ov = {}                                    # pair -> last time seen overlapping
        self.near = []                                   # (t, x, y, ttc)
        self._nm = {}
        self.ped_conf = []                               # (t, x, y, speed) car within 1 m of a walking pedestrian at speed
        self.crashes = []                                # the game's own crash events (impact > 2 m/s)
        self.ghost_s = 0.0
        self.gridlock = 0                                # samples with a deadlocked junction (>= 3 cars stuck 60 s in its box)
        self.clogged_max = 0
        self.ems = {}                                    # job -> {"t0", "arr", "stuck", "kind"}
        self.ems_done = []
        self.bus_v, self.bus_n = 0.0, 0
        self.xing_closed = 0                             # samples with a level crossing closed
        self.heat_stand = collections.Counter()          # cell -> standing vehicle-seconds
        self.heat_v = collections.Counter()              # cell -> sum of speed samples
        self.heat_n = collections.Counter()
        self.heat_conf = collections.Counter()           # cell -> collisions + near misses
        self.heat_pass = collections.Counter()
        self.fd = []                                     # (density veh/km/lane, flow veh/h/lane, speed km/h)
        self.series = []                                 # every 5 s: (t, cars, mean v, stopped share, passes, collisions, near misses)
        self._last_series = (0, 0, 0)
        self.edge_v = {}                                 # edge -> smoothed speed / limit (UI colouring)
        self.edge_k = {}                                 # edge -> smoothed density veh/km/lane
        self.spawned = 0
        self._q = {}                                     # (edge, dir) -> queue length this sample

    # ------------------------------------------------------------------ helpers
    def _in(self, x, y):
        a = self.lab.area
        return a[0] <= x <= a[2] and a[1] <= y <= a[3]

    def _cell(self, x, y):
        return int(x // CELL), int(y // CELL)

    def _free(self, c, e):
        import actors
        import vehicles
        return max(1.0, min(e["speed"] * min(c.pace, actors.TRAFFIC_SPEED_FACTOR), vehicles.PERF[c.kind][0] * 0.9))

    # ------------------------------------------------------------------ one sample (every SAMPLE frames)
    def sample(self, dts):
        import actors
        import vehicles
        lab, sim = self.lab, self.lab.sim
        T, w, sg = sim.traffic, sim.w, lab.lights
        self.t += dts
        now = lab.t
        alive = set()
        boxes = []                                       # (key, kind, parts, x, y, vx, vy, hw, moving, ghost)
        for c in T.cars:
            inside = self._in(c.x, c.y)
            st = self.car.get(c)
            e = w.edges[c.e]
            if st is None:
                if not inside:
                    continue
                st = self.car[c] = {"t0": now, "m": 0.0, "dl": 0.0, "stand": 0.0, "e": (c.e, c.d), "x": c.x, "y": c.y,
                                    "appr": None, "rem": None, "jam": False}
            alive.add(c)
            dm = math.hypot(c.x - st["x"], c.y - st["y"])
            st["x"], st["y"] = c.x, c.y
            if not inside:
                continue
            v = abs(c.v)
            free = self._free(c, e)
            self.vkt += min(dm, free * dts * 2)
            st["m"] += dm
            self.vht += dts
            lost = dts * max(0.0, 1.0 - v / free)
            self.delay += lost
            st["dl"] += lost
            self.samples += 1
            self.ratio_sum += min(1.5, v / max(1.0, e["speed"]))
            self.speed_hist[min(29, int(v / 2))] += 1
            cell = self._cell(c.x, c.y)
            self.heat_v[cell] += v
            self.heat_n[cell] += 1
            if c.ghost > 0:
                self.ghost_s += dts
            end = int(c.d == 1)
            node = e["b"] if c.d == 1 else e["a"]
            rem = (e["len"] - c.s) if c.d == 1 else c.s
            at_red = sg is not None and sg.stop_for(c.e, end) and rem < 60
            if v < 0.3:
                st["stand"] += dts
                self.stopped += 1
                self.heat_stand[cell] += dts
                if st["stand"] > 4.0:
                    self.stuck4 += 1
                    if not at_red:
                        self.stuck4_nored += 1
                if st["stand"] > 25.0 and not at_red and not st["jam"]:
                    st["jam"] = True
                    self.jams.append((round(now, 1), round(c.x), round(c.y), 25.0))
            else:
                st["stand"], st["jam"] = 0.0, False
            # control delay: from 60 m before a junction until the car is through it
            if node in T.junctions:
                if st["appr"] is None and rem < 60.0:
                    st["appr"] = (node, now, rem, free)
            # red-light runs: the front crosses the stop line while its own approach shows red
            stopd = sg.stopd.get((c.e, end)) if sg is not None else None
            if stopd is not None:
                line = rem - stopd - vehicles.HALF_L[c.kind]
                prev = st["rem"]
                if prev is not None and prev[0] == (c.e, c.d) and prev[1] > 0.0 >= line and v > 1.0 and sg.state_of(c.e, end) == 2:
                    self.redruns.append((round(now, 1), round(c.x), round(c.y), node))
                st["rem"] = ((c.e, c.d), line)
            # queues on junction approaches
            if v < 1.0 and node in T.junctions and rem < 150.0:
                key = (c.e, c.d)
                qlen = rem + vehicles.HALF_L[c.kind]
                self._q[key] = max(self._q.get(key, 0.0), qlen)
                self.queue_node[key] = node
            # junction passes (edge change)
            if (c.e, c.d) != st["e"]:
                pe, pd = st["e"]
                pn = w.edges[pe]["b"] if pd == 1 else w.edges[pe]["a"]
                if pn in T.junctions:
                    self.passes[pn] += 1
                    jx, jy = (w.edges[pe]["pts"][-1] if pd == 1 else w.edges[pe]["pts"][0])
                    self.heat_pass[self._cell(jx, jy)] += 1
                    ap = st["appr"]
                    if ap is not None and ap[0] == pn:
                        self.cdelay[pn].append(max(0.0, (now - ap[1]) - ap[2] / ap[3]))
                st["appr"] = None
                st["e"] = (c.e, c.d)
            boxes.append((c, c.kind, actors.parts(c), c.x, c.y, math.cos(c.h) * c.v, math.sin(c.h) * c.v,
                          vehicles.HALF_W[c.kind], v > 0.3, c.ghost > 0))
        for c in [c for c in self.car if c not in alive]:
            st = self.car.pop(c)
            self.trips.append((round(now - st["t0"], 1), round(st["m"]), round(st["dl"], 1)))
        # bodies: buses, emergency vehicles, wrecks, obstacles, kerb-parked cars (standing ones are obstacles only)
        bus_bodies = {bus.body for bus in getattr(sim.transit, "buses", ())} if sim.transit else set()
        for b in sim.bodies:
            if b is sim.car or b.exploded or not self._in(b.x, b.y) or b.kind in vehicles.FLY:
                continue
            sp = b.speed
            if b in bus_bodies:
                self.bus_v += sp
                self.bus_n += 1
            boxes.append((b, b.kind, actors.parts(b), b.x, b.y, b.vx, b.vy, vehicles.HALF_W[b.kind], sp > 0.3, False))
        self._safety(boxes, now)
        # pedestrians: a car passing within 1 m of a walking pedestrian at > 3 m/s
        grid = collections.defaultdict(list)
        for bx in boxes:
            if bx[8]:
                grid[(int(bx[3] // 10), int(bx[4] // 10))].append(bx)
        for p in sim.peds.list:
            if p.mode != "walk" or not self._in(p.x, p.y):
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for bx in grid.get((int(p.x // 10) + dx, int(p.y // 10) + dy), ()):
                        sp = math.hypot(bx[5], bx[6])
                        if sp > 3.0 and any(self._box_dist(pt, p.x, p.y) < 1.0 for pt in bx[2]):
                            k = ("p", id(p), id(bx[0]))
                            if now - self._nm.get(k, -99) > 5.0:
                                self.ped_conf.append((round(now, 1), round(p.x), round(p.y), round(sp, 1)))
                            self._nm[k] = now
        # queues
        for key, qlen in self._q.items():
            self.queue_max[key] = max(self.queue_max[key], qlen)
            self.queue_sum[key] += qlen
        self.nq += 1
        self._q = {}
        # gridlock: >= 3 cars standing > 60 s within a junction's box
        box_stuck = collections.Counter()
        for c, st in self.car.items():
            if st["stand"] > 60.0:
                e = w.edges[c.e]
                rem = (e["len"] - c.s) if c.d == 1 else c.s
                node = e["b"] if c.d == 1 else e["a"]
                if node in T.junctions and rem < T.junctions[node] + 12:
                    box_stuck[node] += 1
        if any(n >= 3 for n in box_stuck.values()):
            self.gridlock += 1
        self.clogged_max = max(self.clogged_max, len(T.clogged))
        if sim.trains.closed:
            self.xing_closed += 1
        # emergency jobs
        cur = set(sim.services.jobs)
        for j in cur:
            r = self.ems.setdefault(j, {"t0": now, "arr": None, "stuck": 0.0, "kind": j.kind})
            if r["arr"] is None and j.state in ("work", "treat"):
                r["arr"] = now - r["t0"]
            if j.body is not None and j.body.speed < 0.5 and j.state == "drive":
                r["stuck"] += dts
        for j in [j for j in self.ems if j not in cur]:
            r = self.ems.pop(j)
            self.ems_done.append((r["kind"], r["arr"], round(r["stuck"], 1)))
        # edge colouring + fundamental diagram (every 10 s)
        per_edge = collections.defaultdict(list)
        for c in self.car:
            if self._in(c.x, c.y):
                per_edge[c.e].append(abs(c.v))
        from roadwidth import lane_count
        tick10 = int(self.t / 10.0) != int((self.t - dts) / 10.0)
        for ei, vs in per_edge.items():
            e = w.edges[ei]
            lanes = max(1, lane_count(e, 1) + (0 if e["ow"] else lane_count(e, -1)))
            k = len(vs) / max(e["len"], 10.0) * 1000.0 / lanes
            vm = sum(vs) / len(vs)
            self.edge_v[ei] = 0.8 * self.edge_v.get(ei, vm / max(1.0, e["speed"])) + 0.2 * vm / max(1.0, e["speed"])
            self.edge_k[ei] = 0.8 * self.edge_k.get(ei, k) + 0.2 * k
            if tick10 and e["len"] > 40.0:
                self.fd.append((round(k, 1), round(k * vm * 3.6), round(vm * 3.6, 1)))
        for ei in [ei for ei in self.edge_k if ei not in per_edge]:
            self.edge_k[ei] *= 0.8
            if self.edge_k[ei] < 0.05:
                del self.edge_k[ei]
                self.edge_v.pop(ei, None)
        if int(self.t / 5.0) != int((self.t - dts) / 5.0):
            inside = [c for c in self.car if self._in(c.x, c.y)]
            p0, c0, n0 = self._last_series
            np_, nc, nn = sum(self.passes.values()), len(self.collisions), len(self.near)
            self.series.append((round(self.t), len(inside), round(sum(abs(c.v) for c in inside) / max(1, len(inside)), 2),
                                round(sum(1 for c in inside if abs(c.v) < 0.3) / max(1, len(inside)), 3), np_ - p0, nc - c0, nn - n0))
            self._last_series = (np_, nc, nn)

    @staticmethod
    def _box_dist(pt, x, y):
        cx, cy, h, hl, hw = pt
        dx, dy = x - cx, y - cy
        u, v = dx * math.cos(h) + dy * math.sin(h), -dx * math.sin(h) + dy * math.cos(h)
        return math.hypot(max(0.0, abs(u) - hl), max(0.0, abs(v) - hw))

    def _safety(self, boxes, now):
        """Collisions: the game's own separating-axis test (actors._sat) on the game's collision boxes (actors.parts),
        deeper than 5 cm, between vehicles of which at least one moves.  Near misses: time to collision < 1.5 s on
        straight-line extrapolation, both boxes' circles, at least one moving faster than 2 m/s."""
        import actors
        grid = collections.defaultdict(list)
        for i, bx in enumerate(boxes):
            grid[(int(bx[3] // 12), int(bx[4] // 12))].append(i)
        seen = set()
        for (gx, gy), idx in grid.items():
            cand = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((gx + dx, gy + dy), ())]
            for i in idx:
                a = boxes[i]
                for j in cand:
                    if j <= i or (i, j) in seen:
                        continue
                    seen.add((i, j))
                    b = boxes[j]
                    if not (a[8] or b[8]):
                        continue
                    dx, dy = b[3] - a[3], b[4] - a[4]
                    if dx * dx + dy * dy > 30.0 ** 2:
                        continue
                    key = (id(a[0]), id(b[0])) if id(a[0]) < id(b[0]) else (id(b[0]), id(a[0]))
                    depth = 0.0
                    if dx * dx + dy * dy < 22.0 ** 2:
                        for pa in a[2]:
                            ca = actors._corners(*pa)
                            for pb in b[2]:
                                r = actors._sat(ca, pa[2], actors._corners(*pb), pb[2])
                                if r is not None:
                                    depth = max(depth, r[0])
                    if depth > 0.05:
                        if now - self._ov.get(key, -99.0) > 2.0:
                            x, y = (a[3] + b[3]) / 2, (a[4] + b[4]) / 2
                            self.collisions.append((round(now, 1), round(x), round(y), round(depth, 2), "ghost" if (a[9] or b[9]) else "real"))
                            self.heat_conf[self._cell(x, y)] += 1
                        self._ov[key] = now
                        continue
                    ux, uy = b[5] - a[5], b[6] - a[6]
                    uu = ux * ux + uy * uy
                    if uu < 4.0 or max(math.hypot(a[5], a[6]), math.hypot(b[5], b[6])) < 2.0:
                        continue
                    tstar = -(dx * ux + dy * uy) / uu
                    if not 0.0 < tstar < TTC_MAX:
                        continue
                    miss = math.hypot(dx + ux * tstar, dy + uy * tstar)
                    if miss < a[7] + b[7] + 0.2:
                        if now - self._nm.get(key, -99.0) > 5.0:
                            x, y = (a[3] + b[3]) / 2, (a[4] + b[4]) / 2
                            self.near.append((round(now, 1), round(x), round(y), round(tstar, 2)))
                            self.heat_conf[self._cell(x, y)] += 1
                        self._nm[key] = now

    # ------------------------------------------------------------------ results
    def summary(self):
        lab = self.lab
        hours = max(self.t, 1e-6) / 3600.0
        km = self.vkt / 1000.0
        T = lab.sim.traffic
        sig_nodes = set(lab.lights.nodes) if lab.lights is not None else set()
        junctions = []
        for node, n in self.passes.most_common():
            cd = self.cdelay.get(node, [])
            d = sum(cd) / len(cd) if cd else 0.0
            sig = node in sig_nodes and not (lab.lights.all_off or lab.lights.ov.get(node, {}).get("off"))
            qs = [self.queue_max[k] for k, nn in self.queue_node.items() if nn == node]
            qm = [self.queue_sum[k] / max(1, self.nq) for k, nn in self.queue_node.items() if nn == node]
            x, y = lab.node_xy.get(node, (0, 0))
            junctions.append({"node": node, "x": round(x), "y": round(y), "veh_h": round(n / hours), "delay": round(d, 1),
                              "los": los(d, sig), "signal": sig, "queue_max": round(max(qs, default=0.0)),
                              "queue_mean": round(sum(qm), 1), "redruns": sum(1 for r in self.redruns if r[3] == node)})
        arrived = [a for _k, a, _s in self.ems_done if a is not None] + [r["arr"] for r in self.ems.values() if r["arr"] is not None]
        calls = len(self.ems_done) + len(self.ems)
        real = [c for c in self.collisions if c[4] == "real"]
        s = self.samples or 1
        out = {
            "seconds": round(self.t), "cars_mean": round(self.vht / max(self.t, 1e-6), 1),
            # speed
            "speed_kmh": round(self.vkt / max(self.vht, 1e-6) * 3.6, 2),
            "speed_ratio": round(self.ratio_sum / s, 3),
            "speed_hist": self.speed_hist,
            # efficiency
            "veh_km_h": round(km / hours, 1),
            "throughput_h": round(sum(self.passes.values()) / hours),
            "delay_s_km": round(self.delay / max(km, 1e-6), 1),
            "delay_share": round(self.delay / max(self.vht, 1e-6), 3),
            "stopped_share": round(self.stopped / s, 3),
            "stuck4_share": round(self.stuck4 / s, 3),
            "stuck4_nored_share": round(self.stuck4_nored / s, 3),
            "jams": len(self.jams),
            "gridlock_s": round(self.gridlock * SAMPLE * lab.dt, 1),
            "clogged_max": self.clogged_max,
            "ghost_share": round(self.ghost_s / max(self.vht, 1e-6), 4),
            "trips": len(self.trips),
            "trip_delay": round(sum(t[2] for t in self.trips) / max(1, len(self.trips)), 1),
            "despawned": T.despawned,
            # safety
            "collisions": len(real), "collisions_ghost": len(self.collisions) - len(real),
            "collisions_deep": sum(1 for c in real if c[3] > 0.3),
            "near_misses": len(self.near), "near_serious": sum(1 for n in self.near if n[3] < 0.75),
            "ped_conflicts": len(self.ped_conf), "redruns": len(self.redruns), "game_crashes": len(self.crashes),
            "conflicts_per_1000km": round((len(real) + len(self.near)) / max(km, 1e-6) * 1000.0, 1),
            # transit / emergency
            "bus_kmh": round(self.bus_v / max(1, self.bus_n) * 3.6, 1),
            "xing_closed_share": round(self.xing_closed / max(1, self.nq), 3),
            "ems_calls": calls, "ems_arrived": len(arrived),
            "ems_response": round(sum(arrived) / len(arrived), 1) if arrived else None,
            "ems_stuck": round(sum(s_ for _k, _a, s_ in self.ems_done) / max(1, len(self.ems_done)), 1),
            # detail
            "junctions": junctions[:60],
            "los_mix": dict(collections.Counter(j["los"] for j in junctions)),
            "fd": self.fd[-3000:],
            "series": self.series,
            "heat_stand": [(k[0], k[1], round(v, 1)) for k, v in self.heat_stand.items() if v >= 1.0],
            "heat_speed": [(k[0], k[1], round(self.heat_v[k] / n, 2)) for k, n in self.heat_n.items() if n >= 4],
            "heat_conf": [(k[0], k[1], v) for k, v in self.heat_conf.items()],
            "jam_list": self.jams[:200], "collision_list": self.collisions[:300], "near_list": self.near[:300],
            "redrun_list": self.redruns[:200],
        }
        out["score_efficiency"] = round(100.0 * max(0.0, 1.0 - out["delay_share"]), 1)
        out["score_safety"] = round(100.0 / (1.0 + out["conflicts_per_1000km"] / 50.0), 1)
        out["score_speed"] = round(100.0 * min(1.0, out["speed_ratio"]), 1)
        return out


class LabSim:
    """One run: the game's Sim on a world, with the lab's settings, edits and incidents."""

    def __init__(self, world, osm_dir, settings=None, scenario=None, seed=1):
        import actors
        import transit
        self.w = world
        self.st = dict(params.defaults())
        self.st.update(settings or {})
        self.sc = scenario or default_scenario(world)
        self.area = live_area(self.sc)
        self.dt = float(self.st["dt"])
        self.seed = seed
        self.t = 0.0
        self.frame = 0
        self.log = collections.deque(maxlen=200)            # (t, text) for the UI's event log
        self.tuning = params.tuning(self.st, self.sc)
        self._saved = traffic_tuning.apply_constants(self.tuning)      # the same code the game runs at startup
        self._undo = traffic_tuning.apply_world(world, self.tuning)
        self.closed = traffic_tuning.closed_edges(world, self.tuning)
        self._parked0 = None
        if not self.st["parked_on"]:
            self._parked0 = world.parked
            world.parked = world.parked[:0]
        random.seed(seed)
        rng = random.Random(seed)
        self.rng = random.Random(seed * 7919 + 13)
        cx, cy = (self.area[0] + self.area[2]) / 2, (self.area[1] + self.area[3]) / 2
        sim = self.sim = actors.Sim(world, rng, int(self.st["cars"]), int(self.st["peds"]))
        self.lights = traffic_tuning.make_signals_class()(world, self.tuning)
        sim.traffic.signals = sim.lights = self.lights
        sim.transit = transit.Transit(sim, osm_dir) if self.st["buses_on"] else None
        if not self.st["trains_on"]:
            sim.trains.trains = []
            sim.trains.xings = {}
        sim.services.amb_on, sim.services.fire_on = self.st["amb_on"], self.st["fire_on"]
        sim.clock.hour, sim.aggro = float(self.st["hour"]), int(self.st["aggro"])
        sim.base_cars, sim.base_peds = int(self.st["cars"]), int(self.st["peds"])
        self.hour0 = sim.clock.hour
        sim.teleport(cx, cy)
        sim.exit_car()
        if sim.car in sim.bodies:
            sim.bodies.remove(sim.car)          # the car the idle player left would stand in the road
        if self.st["full_rate"]:
            sim.view_rect = tuple(self.area)
        sim.view_r = min(260.0, max(self.area[2] - self.area[0], self.area[3] - self.area[1]) / 2)
        if self.st["hide_player"]:
            T = sim.traffic
            upd = T.update
            T.update = lambda d, fx, fy, bodies, peds, walker=None: upd(d, fx, fy, bodies, peds, None)
        self.node_xy = {}
        for e in world.edges:
            self.node_xy.setdefault(e["a"], tuple(e["pts"][0]))
            self.node_xy.setdefault(e["b"], tuple(e["pts"][-1]))
        self.obstacles = []
        for ob in self.sc.get("obstacles", ()):
            self.add_obstacle(*ob)
        self.incidents = sorted((r for r in self.sc.get("incidents", ()) if self.area[0] <= r[2] <= self.area[2]
                                 and self.area[1] <= r[3] <= self.area[3]), key=lambda r: r[0])
        self.broken = []                                    # (until t, body, car kind) breakdowns that will drive on
        self.m = Metrics(self)
        self.warm = float(self.st["warm"])
        self.duration = float(self.st["duration"])

    RESTART = ("buses_on", "trains_on", "dt", "full_rate", "hide_player", "parked_on")

    def retune(self, settings, scenario):
        """Apply changed settings / edits to the running simulation (the UI's sliders).  Returns the keys that only take
        effect after a restart (they change how the run is built)."""
        new = dict(params.defaults())
        new.update(settings or {})
        later = [k for k in self.RESTART if new.get(k) != self.st.get(k)]
        moved = live_area(scenario) != self.area
        if moved:
            later.append("area")
        for k in later:                                   # keep what the running sim was built with
            if k != "area":
                new[k] = self.st[k]
        self.st, self.sc = new, scenario
        self._undo()
        traffic_tuning.restore(self._saved)
        self.tuning = params.tuning(self.st, self.sc)
        self._saved = traffic_tuning.apply_constants(self.tuning)
        self._undo = traffic_tuning.apply_world(self.w, self.tuning)
        self.closed = traffic_tuning.closed_edges(self.w, self.tuning)
        old = self.lights
        lights = traffic_tuning.make_signals_class()(self.w, self.tuning)
        lights.t, lights.pre = old.t, old.pre
        self.lights = self.sim.traffic.signals = self.sim.lights = lights
        sim = self.sim
        sim.base_cars, sim.base_peds = int(self.st["cars"]), int(self.st["peds"])
        sim.aggro = int(self.st["aggro"])
        if float(self.st["hour"]) != self.hour0:
            self.hour0 = sim.clock.hour = float(self.st["hour"])
        sim.services.amb_on, sim.services.fire_on = self.st["amb_on"], self.st["fire_on"]
        self.warm, self.duration = float(self.st["warm"]), float(self.st["duration"])
        return later

    def close(self):
        """Put the world and the game constants back (the UI runs many scenarios in one process)."""
        self._undo()
        if self._parked0 is not None:
            self.w.parked = self._parked0
        traffic_tuning.restore(self._saved)

    # ------------------------------------------------------------------ edits / incidents during a run
    def lane_pose(self, x, y):
        """Nearest drivable edge point: (x, y, heading, edge) on its right-hand lane."""
        best = None
        w = self.w
        for ei in w.drive_cells.get((int(x // w.sg), int(y // w.sg)), ()):
            pts = w.edges[ei]["pts"]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                dx, dy = bx - ax, by - ay
                L2 = dx * dx + dy * dy or 1.0
                u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
                px, py = ax + dx * u, ay + dy * u
                d = (px - x) ** 2 + (py - y) ** 2
                if best is None or d < best[0]:
                    best = (d, px, py, math.atan2(dy, dx), ei)
        if best is None:
            return None
        _d, px, py, h, ei = best
        e = w.edges[ei]
        off = 0.0 if e["ow"] else min(e["w"] / 4, 3.0)
        return px - math.sin(h) * off, py + math.cos(h) * off, h, ei

    def add_obstacle(self, x, y, h=None, kind=1, log=True):
        import actors
        if h is None:
            p = self.lane_pose(x, y)
            if p is None:
                return None
            x, y, h, _ei = p
        b = actors.Body(x, y, h, int(kind), 3)
        b.empty = True
        b.az = self.w.level(x, y, -1e9)
        self.sim.bodies.append(b)
        self.obstacles.append(b)
        if log:
            self.log.append((self.t, f"obstacle at ({x:.0f}, {y:.0f})"))
        return b

    def collapse(self, near=None):
        """A pedestrian collapses (in the study area, or the nearest to `near`): the ambulance is called."""
        peds = [p for p in self.sim.peds.list if p.mode == "walk" and self.m._in(p.x, p.y)]
        if not peds:
            return False
        if near is not None:
            p = min(peds, key=lambda q: (q.x - near[0]) ** 2 + (q.y - near[1]) ** 2)
        else:
            p = self.rng.choice(peds)
        p.mode, p.t = "dead", 120.0
        p.svc = True
        self.sim.services.request("amb", p, p.x, p.y)
        self.log.append((self.t, f"pedestrian collapsed at ({p.x:.0f}, {p.y:.0f}): ambulance called"))
        return True

    def fire(self, x=None, y=None):
        """A burning wreck appears in a lane: an obstacle, and the fire brigade comes."""
        if x is None:
            x, y = self.rng.uniform(self.area[0], self.area[2]), self.rng.uniform(self.area[1], self.area[3])
        b = self.add_obstacle(x, y, kind=self.rng.choice((1, 4, 9, 20)), log=False)
        if b is None:
            return False
        b.health, b.burn = 0.0, 0.5
        self.sim.services.request("fire", b, b.x, b.y, 1.5)
        self.log.append((self.t, f"car fire at ({b.x:.0f}, {b.y:.0f}): fire brigade called"))
        return True

    def breakdown(self, x=None, y=None):
        """A moving car stops dead in its lane for breakdown_t seconds, then drives on (as a standing Body meanwhile)."""
        T = self.sim.traffic
        cand = [c for c in T.cars if self.m._in(c.x, c.y) and c.v > 3.0 and c.turnaround is None]
        if not cand:
            return False
        c = min(cand, key=lambda q: (q.x - x) ** 2 + (q.y - y) ** 2) if x is not None else self.rng.choice(cand)
        b = T.make_body(c)
        b.vx = b.vy = 0.0
        b.empty = True
        T.cars.remove(c)
        self.sim.bodies.append(b)
        self.broken.append((self.t + float(self.st["breakdown_t"]), b))
        self.log.append((self.t, f"breakdown at ({c.x:.0f}, {c.y:.0f}) for {self.st['breakdown_t']:.0f} s"))
        return True

    def remove_obstacle_near(self, x, y, r=6.0):
        for b in list(self.obstacles):
            if (b.x - x) ** 2 + (b.y - y) ** 2 < r * r:
                self.obstacles.remove(b)
                if b in self.sim.bodies:
                    self.sim.bodies.remove(b)
                return True
        return False

    # ------------------------------------------------------------------ stepping
    def step(self):
        sim, dt = self.sim, self.dt
        self.lights.update(dt)
        sim.update(dt, INP, 1)
        if self.st["freeze_clock"]:
            sim.clock.hour = self.hour0
        for kind, kw in sim.events:
            if kind == "crash" and self.t >= self.warm and self.m._in(kw.get("x", 1e9), kw.get("y", 1e9)):
                self.m.crashes.append((round(self.t, 1), round(kw.get("x", 0)), round(kw.get("y", 0)), round(kw.get("impact", 0), 1)))
        sim.events.clear()
        self.t += dt
        self.frame += 1
        for until, b in [r for r in self.broken if r[0] <= self.t]:
            self.broken.remove((until, b))
            if b in sim.bodies:
                sim.bodies.remove(b)               # towed away (the game has no way to hand a Body back to AI traffic)
        if self.t >= self.warm:
            hrs = dt / 3600.0
            r = self.rng.random
            if r() < self.st["amb_rate"] * hrs:
                self.collapse()
            if r() < self.st["fire_rate"] * hrs:
                self.fire()
            if r() < self.st["breakdown_rate"] * hrs:
                self.breakdown()
            while self.incidents and self.incidents[0][0] <= self.t - self.warm:
                _t, kind, x, y = self.incidents.pop(0)
                {"amb": lambda: self.collapse((x, y)), "fire": lambda: self.fire(x, y), "breakdown": lambda: self.breakdown(x, y)}.get(kind, lambda: None)()
            if self.frame % SAMPLE == 0:
                self.m.sample(dt * SAMPLE)

    @property
    def done(self):
        return self.t >= self.warm + self.duration

    def run(self, progress=None):
        n = int((self.warm + self.duration) / self.dt)
        for k in range(n):
            self.step()
            if progress is not None and k % 200 == 0:
                progress(k / n)
        return self.m.summary()
