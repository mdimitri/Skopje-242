"""ЈСП city buses on the real lines from OpenStreetMap (data/osm/transit.json, written by the Geofabrik download).

Each line's ways are chained into one polyline; a few buses drive near the player with the same car physics as every
other vehicle (pure-pursuit steering along the line in its rightmost lane, never teleported while visible), stop at the real stops and announce
the line. Without transit.json (Overpass download, demo city) there are simply no city buses.
"""
from texts import TXT
import json
import math
import os
import random

import actors
import vehicles
from geo import project

MAX_BUSES = 5
SPAWN_MIN, SPAWN_MAX, DESPAWN = 220.0, 420.0, 650.0


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _chain(ways):
    """Join the member ways in order (flipping each to continue from the previous end) into gap-free runs, so a bus
    never has to cross a hole in the relation; every run can carry buses of its own."""
    runs, out = [], []
    ps = [pts for pts in ([project(p["lat"], p["lon"]) for p in g] for g in ways) if pts]
    for k, pts in enumerate(ps):
        if out:
            e = out[-1]
            if math.dist(e, pts[-1]) < math.dist(e, pts[0]):
                pts = pts[::-1]
            if math.dist(e, pts[0]) > 30:            # a hole in the relation: start a new run
                runs.append(out)
                out = []
        if not out and k + 1 < len(ps):              # a run's first way has no predecessor: point it towards the way that follows,
            n0, n1 = ps[k + 1][0], ps[k + 1][-1]     # else the whole run is driven backwards (against the carriageway)
            if min(math.dist(pts[0], n0), math.dist(pts[0], n1)) < min(math.dist(pts[-1], n0), math.dist(pts[-1], n1)):
                pts = pts[::-1]
        out.extend(pts)
    runs.append(out)
    res = []
    for run in runs:
        r = run[:1]
        for q in run[1:]:                           # thin to >= 4 m so the steering does not zig-zag
            if math.dist(q, r[-1]) >= 4.0:
                r.append(q)
        res.append(r)
    return res


class Line:
    def __init__(self, rec, pts):
        self.ref = rec.get("ref") or "?"
        name = (rec.get("name") or "").replace(TXT("transit.0001"), "").replace(TXT("transit.0002"), "").strip()
        dest = rec.get("to") or ""
        for sep in (TXT("transit.0003"), " - ", "-", "→"):
            if not dest and sep in name:
                dest = name.split(sep)[-1].strip()
        self.dest = (dest if dest and dest != self.ref else TXT("transit.0004"))[:28]
        self.pts = pts
        self.rel_stops = [project(p["lat"], p["lon"]) for p in rec.get("stops") or []]   # the route's own stops (OSM relation)
        self.lane = {}                                  # vertex -> offset of the rightmost lane (filled while driving)
        self.cum = [0.0]
        for a, b in zip(self.pts, self.pts[1:]):
            self.cum.append(self.cum[-1] + math.dist(a, b))

    @property
    def length(self):
        return self.cum[-1] if self.cum else 0.0


def current(osm_dir):
    """transit.json exists and carries every line's own stops (v 2, see tools/fetch_extras.current_transit)."""
    try:
        with open(os.path.join(osm_dir, "transit.json"), encoding="utf-8") as f:
            recs = json.load(f)
    except (OSError, ValueError):
        return False
    return not recs or recs[0].get("v") == 2


def load(osm_dir):
    p = os.path.join(osm_dir, "transit.json")
    try:
        with open(p, encoding="utf-8") as f:
            recs = json.load(f)
    except Exception:  # noqa: BLE001 - no bus data: no buses
        return []
    lines = []
    for r in recs:
        op = (r.get("operator") or "").lower()
        if not ("jsp" in op or TXT("transit.0005") in op or "skopje:local" in op) or not r.get("ref"):
            continue
        for part, pts in enumerate(_chain(r.get("ways", []))):
            ln = Line(r, pts)
            ln.rid, ln.part = id(r), part
            if len(ln.pts) >= 2:
                lines.append(ln)                 # short runs too: join_runs() stitches the holes of a relation, then the short ones go
    return lines


def _node_near(w, x, y, r=60.0):
    """Nearest drivable junction node to (x, y) within r m: (node, x, y) or None."""
    sg, best = w.sg, None
    for cx in range(int((x - r) // sg), int((x + r) // sg) + 1):
        for cy in range(int((y - r) // sg), int((y + r) // sg) + 1):
            for ei in w.drive_cells.get((cx, cy), ()):
                e = w.edges[ei]
                for n, p in ((e["a"], e["pts"][0]), (e["b"], e["pts"][-1])):
                    d = math.hypot(p[0] - x, p[1] - y)
                    if d < r and (best is None or d < best[0]):
                        best = (d, n, p[0], p[1])
    return best and best[1:]


def _road_path(w, n0, n1, limit=1500.0):
    """Shortest drivable route (one-ways respected) from node n0 to n1 as a polyline, or None beyond `limit` metres."""
    import heapq
    dist, prev, h = {n0: 0.0}, {}, [(0.0, n0)]
    while h:
        d, n = heapq.heappop(h)
        if n == n1:
            break
        if d > dist.get(n, 1e18) or d > limit:
            continue
        for ei, dr in w.out.get(n, ()):
            e = w.edges[ei]
            m = e["b"] if dr == 1 else e["a"]
            nd = d + e["len"]
            if nd < dist.get(m, 1e18):
                dist[m], prev[m] = nd, (n, ei, dr)
                heapq.heappush(h, (nd, m))
    if n1 not in prev and n0 != n1:
        return None
    pts, n = [], n1
    while n != n0:
        n, ei, dr = prev[n]
        seg = w.edges[ei]["pts"]
        pts = (list(seg) if dr == 1 else list(seg[::-1])) + pts
    return pts


def join_runs(lines, w):
    """A relation's ways have holes (missing members, platforms), which split a route into runs that end in the middle of town:
    the bus then stood at the end until it was out of sight and 'respawned'.  Stitch consecutive runs of one route with the
    road graph's own shortest drivable path from where one ends to where the next begins, so every route flows end to end."""
    out, groups = [], {}
    for ln in lines:
        groups.setdefault(ln.rid, []).append(ln)
    for runs in groups.values():
        runs.sort(key=lambda l: l.part)
        cur = runs[0]
        for nxt in runs[1:]:
            e0 = cur.pts[-1]
            if math.dist(e0, nxt.pts[-1]) < math.dist(e0, nxt.pts[0]):
                nxt.pts.reverse()
            a = _node_near(w, *cur.pts[-1])
            b = _node_near(w, *nxt.pts[0])
            path = _road_path(w, a[0], b[0]) if a and b and math.dist(cur.pts[-1], nxt.pts[0]) < 1500.0 else None
            if path is None:
                out.append(cur)
                cur = nxt
                continue
            pts = cur.pts + path + nxt.pts
            thin = pts[:1]
            for q in pts[1:]:
                if math.dist(q, thin[-1]) >= 4.0:
                    thin.append(q)
            cur.pts = thin
            cur.rel_stops += nxt.rel_stops
        out.append(cur)
    res = []
    for ln in out:
        ln.cum = [0.0]
        for a_, b_ in zip(ln.pts, ln.pts[1:]):
            ln.cum.append(ln.cum[-1] + math.dist(a_, b_))
        if len(ln.pts) > 10 and ln.length > 1500:
            _finish(ln, w)
            res.append(ln)
    return res


def _finish(ln, w, closed=False):
    """Give the line its laps: a terminus is not the end of the road, so the bus carries on back to the start and round again
    (stops are attached to every lap).  closed: the points already make one full lap there and back."""
    ln.cyc = None
    a_, b_ = _node_near(w, *ln.pts[-1]), _node_near(w, *ln.pts[0])
    back = None if closed else (_road_path(w, a_[0], b_[0], 3000.0) if a_ and b_ and a_[0] != b_[0] else None)
    if closed or back is not None or (a_ and b_ and a_[0] == b_[0]):
        one = ln.pts + (back or [])
        cyc = 3 if ln.length < 6000 else 2
        pts = [one[0]]
        for _ in range(cyc):
            for q in one:
                if math.dist(q, pts[-1]) >= 4.0:
                    pts.append(q)
        ln.cyc = sum(math.dist(x_, y_) for x_, y_ in zip(one, one[1:]))
        ln.pts = pts
        ln.cum = [0.0]
        for x_, y_ in zip(pts, pts[1:]):
            ln.cum.append(ln.cum[-1] + math.dist(x_, y_))


def match_route(runs, w):
    """The route of one relation, rebuilt from the road graph.  A relation's members are an unordered, patchy heap of ways (both
    directions, platforms, holes), so chaining them gives spaghetti.  Instead: find the graph edges the ways lie on, take the two ends of
    that stretch as the termini, and drive the shortest legal path there (cheap on the mapped edges, dear elsewhere) and back.
    Returns the closed lap (there and back) as a polyline, or None."""
    import heapq
    sg = 4.0
    grid = {}
    for ln in runs:
        for a, b in zip(ln.pts, ln.pts[1:]):
            n = max(1, int(math.dist(a, b) // sg))
            for k in range(n + 1):
                x, y = a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n
                grid.setdefault((int(x // 8), int(y // 8)), []).append((x, y))

    def near(x, y, r):
        r2 = r * r
        cx, cy = int(x // 8), int(y // 8)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for q in grid.get((cx + i, cy + j), ()):
                    if (q[0] - x) ** 2 + (q[1] - y) ** 2 < r2:
                        return True
        return False
    cand = set()
    for (cx, cy) in list(grid):
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                cand.update(w.drive_cells.get((cx * 8 // w.sg + i, cy * 8 // w.sg + j), ()))
    mapped = set()
    for ei in cand:
        e = w.edges[ei]
        pts = e["pts"]
        n = max(2, int(e["len"] // 6))
        ok = tot = 0
        for k in range(n + 1):
            s_ = e["len"] * k / n
            for t in range(len(pts) - 1):
                if e["cum"][t + 1] >= s_ or t == len(pts) - 2:
                    seg = e["cum"][t + 1] - e["cum"][t] or 1.0
                    f = min(1.0, max(0.0, (s_ - e["cum"][t]) / seg))
                    x, y = pts[t][0] + (pts[t + 1][0] - pts[t][0]) * f, pts[t][1] + (pts[t + 1][1] - pts[t][1]) * f
                    break
            tot += 1
            ok += near(x, y, 7.0)
        if ok >= 0.8 * tot:
            mapped.add(ei)
    if len(mapped) < 5:
        return None
    pos = {}
    for ei in mapped:                                           # the ways leave holes, so the stretch's two ends are the two mapped nodes farthest apart
        e = w.edges[ei]
        pos[e["a"]], pos[e["b"]] = e["pts"][0], e["pts"][-1]

    def far(src):
        p0 = pos[src]
        return max(pos, key=lambda n: (pos[n][0] - p0[0]) ** 2 + (pos[n][1] - p0[1]) ** 2)
    S = far(next(iter(pos)))
    T = far(S)
    if math.dist(pos[S], pos[T]) < 1200.0:
        return None

    def path(a, b):
        dist, prev, h = {a: 0.0}, {}, [(0.0, a)]
        while h:
            d, n = heapq.heappop(h)
            if n == b:
                break
            if d > dist[n]:
                continue
            for ei, dr in w.out.get(n, ()):
                e = w.edges[ei]
                m = e["b"] if dr == 1 else e["a"]
                nd = d + e["len"] * (1.0 if ei in mapped else 6.0)
                if nd < dist.get(m, 1e18):
                    dist[m], prev[m] = nd, (n, ei, dr)
                    heapq.heappush(h, (nd, m))
        if b not in prev:
            return None
        pts, n = [], b
        while n != a:
            n, ei, dr = prev[n]
            seg = w.edges[ei]["pts"]
            pts = (list(seg) if dr == 1 else list(seg[::-1])) + pts
        return pts
    go, back = path(S, T), path(T, S)
    if go is None or back is None:
        return None
    lap = go + back
    out = [lap[0]]
    for q in lap[1:]:
        if math.dist(q, out[-1]) >= 4.0:
            out.append(q)
    return out


def orient_to_traffic(lines, w):
    """A relation's ways carry no travel direction, so a whole run can come out driven backwards (against the one-way
    carriageways it runs on).  Count the segments that agree / disagree with the road graph's one-way edges and turn a
    run round when it mostly disagrees."""
    sg = w.sg
    for ln in lines:
        ag = dg = 0
        for (ax, ay), (bx, by) in zip(ln.pts, ln.pts[1:]):
            dx, dy = bx - ax, by - ay
            hl = math.hypot(dx, dy)
            if hl < 1.0:
                continue
            mx, my = (ax + bx) / 2, (ay + by) / 2
            best = None
            for ei in {ei for cx in (int(mx // sg) - 1, int(mx // sg), int(mx // sg) + 1)
                       for cy in (int(my // sg) - 1, int(my // sg), int(my // sg) + 1) for ei in w.drive_cells.get((cx, cy), ())}:
                e = w.edges[ei]
                if not e["ow"]:
                    continue
                for (px, py), (qx, qy) in zip(e["pts"], e["pts"][1:]):
                    ex, ey = qx - px, qy - py
                    l2 = ex * ex + ey * ey or 1e-9
                    t = max(0.0, min(1.0, ((mx - px) * ex + (my - py) * ey) / l2))
                    d = math.hypot(mx - px - ex * t, my - py - ey * t)
                    dot = (ex * dx + ey * dy) / (math.sqrt(l2) * hl)
                    if d < 6.0 and abs(dot) > 0.7 and (best is None or d < best[0]):
                        best = (d, dot)
            if best:
                if best[1] > 0:
                    ag += 1
                else:
                    dg += 1
        if dg >= 10 and dg > 2 * ag:
            ln.pts.reverse()
            ln.cum = [0.0]
            for a_, b_ in zip(ln.pts, ln.pts[1:]):
                ln.cum.append(ln.cum[-1] + math.dist(a_, b_))
            ln.lane = {}


def attach_stops(lines, stops):
    """For every line: the real stops along it as [(distance along the line, stop index)], sorted.  A stop counts when
    the shelter stands beside a segment of the line on its right-hand side (the one across the road is the other
    direction's); the stops the route relation itself lists are always taken."""
    grid = {}
    for k, st in enumerate(stops):
        grid.setdefault((int(st[0] // 40), int(st[1] // 40)), []).append(k)
    R = 25.0
    for ln in lines:
        best, segs = {}, []
        for j in range(len(ln.pts) - 1):
            (ax, ay), (bx, by) = ln.pts[j], ln.pts[j + 1]
            sl = ln.cum[j + 1] - ln.cum[j]
            if sl <= 0:
                continue
            ux, uy = (bx - ax) / sl, (by - ay) / sl
            segs.append((ax, ay, ux, uy, sl, ln.cum[j]))
            for gx in range(int((min(ax, bx) - R) // 40), int((max(ax, bx) + R) // 40) + 1):
                for gy in range(int((min(ay, by) - R) // 40), int((max(ay, by) + R) // 40) + 1):
                    for k in grid.get((gx, gy), ()):
                        rx, ry = stops[k][0] - ax, stops[k][1] - ay
                        t = rx * ux + ry * uy
                        lat = -rx * uy + ry * ux
                        cc = ln.cum[j] + max(0.0, min(sl, t))
                        kk = (k, int(cc // ln.cyc) if getattr(ln, "cyc", None) else 0)
                        if -2.0 < t < sl + 2.0 and -2.0 < lat < R and (kk not in best or lat < best[kk][0]):
                            best[kk] = (lat, cc)
        for x, y in ln.rel_stops:
            near = [k for gx in (int(x // 40) - 1, int(x // 40), int(x // 40) + 1)
                    for gy in (int(y // 40) - 1, int(y // 40), int(y // 40) + 1) for k in grid.get((gx, gy), ())]
            near = [k for k in near if math.hypot(stops[k][0] - x, stops[k][1] - y) < 35.0]
            if not near or not segs:
                continue
            k = min(near, key=lambda k: math.hypot(stops[k][0] - x, stops[k][1] - y))
            if (k, 0) in best:
                continue
            d, c = min((math.hypot(x - ax - ux * t, y - ay - uy * t), c0 + t) for ax, ay, ux, uy, sl, c0 in segs
                       for t in (max(0.0, min(sl, (x - ax) * ux + (y - ay) * uy)),))
            if d < 30.0:
                best[(k, int(c // ln.cyc) if getattr(ln, "cyc", None) else 0)] = (d, c)
        ln.stops = sorted((c, k) for (k, _cy), (d, c) in best.items())


class Bus:
    def __init__(self, line, body, i):
        self.line, self.body, self.i = line, body, i
        self.stop_k = None
        self.next_stop = math.inf                 # past the last stop of the line: drive on to the end
        for c, k in getattr(line, "stops", ()):
            if c > line.cum[max(0, i - 1)] + 15:
                self.next_stop, self.stop_k = c, k
                break
        self.wait = 0.0
        self.dodge = 0.0                         # sideways step (to the left, < 0) round a car standing in the lane
        self.s, self.lat = line.cum[i], 0.0     # where it is along / across its line
        self.stuck = 0.0
        self.rev = 0.0


class Transit:
    def __init__(self, sim, osm_dir):
        self.sim = sim
        self.lines = load(osm_dir)
        self.buses = []
        self.rng = random.Random(22)
        self.t = 0.0
        self.kinds = [i for i, n in enumerate(vehicles.IDS) if n.startswith("JSP ")] or [vehicles.BUS]
        self.stops = list(getattr(sim.w, "bus_stops", None) or [])
        groups = {}
        for ln in self.lines:
            groups.setdefault(ln.rid, []).append(ln)
        rebuilt, rest = [], []
        for runs in groups.values():
            runs.sort(key=lambda l: l.part)
            lap = match_route(runs, sim.w)
            if lap is None:
                rest += runs                                    # no usable route from the graph: chain the ways as before
                continue
            ln = runs[0]
            ln.pts = lap
            ln.cum = [0.0]
            for a_, b_ in zip(lap, lap[1:]):
                ln.cum.append(ln.cum[-1] + math.dist(a_, b_))
            _finish(ln, sim.w, closed=True)
            rebuilt.append(ln)
        orient_to_traffic(rest, sim.w)
        self.lines = rebuilt + join_runs(rest, sim.w)
        attach_stops(self.lines, self.stops)
        self.queue = {}                   # stop index -> [ped]  (people waiting at the shelter)
        self.refill = {}                  # stop index -> seconds until new people turn up
        self.served = [0, 0]              # people who got on / off (stats, tests)
        self.movers = []                  # peds walking to a bus door ("board") or away from it ("alight")

    def update(self, dt):
        if not self.lines:
            return
        self._acc = getattr(self, "_acc", 0.0) + dt                 # buses and stops think every other frame: the physics keeps using the last controls
        self._skip = not getattr(self, "_skip", False)
        if self._skip:
            return
        dt, self._acc = self._acc, 0.0
        sim = self.sim
        fx, fy = sim.focus()[:2]
        self.t -= dt
        for bus in list(self.buses):
            b = bus.body
            far = math.hypot(b.x - fx, b.y - fy) > DESPAWN
            if b not in sim.bodies or b.player_car:               # destroyed / removed, or the player took it
                self.buses.remove(bus)
                continue
            if far or bus.i >= len(bus.line.pts) - 2 or getattr(bus, "off", 0) > 45:              # out of sight (or end of the line): leave quietly
                if math.hypot(b.x - fx, b.y - fy) > 120:
                    sim.bodies.remove(b)
                    if b.model is not None:
                        sim.ev("free_model", model=b.model)
                    self.buses.remove(bus)
                    continue
                b.ctl = (0.0, 0.0, True)
                continue
            self._drive(bus, dt)
        self._people(dt, fx, fy)
        if self.t <= 0 and len(self.buses) < MAX_BUSES:
            self.t = 2.0
            self._spawn(fx, fy)

    def _spawn(self, fx, fy):
        sim = self.sim
        cand = []
        for ln in self.lines:
            for k in range(0, len(ln.pts) - 3, 6):
                d = math.hypot(ln.pts[k][0] - fx, ln.pts[k][1] - fy)
                if SPAWN_MIN < d < SPAWN_MAX:
                    cand.append((ln, k))
        if not cand:
            return
        ln, k = self.rng.choice(cand)
        x, y = ln.pts[k]
        h = math.atan2(ln.pts[k + 1][1] - y, ln.pts[k + 1][0] - x)
        right = self._lane(ln, k)[0]                                         # in its lane, not on the road's centre line
        x, y = x - math.sin(h) * right, y + math.cos(h) * right
        if any(math.hypot(o.x - x, o.y - y) < 14 for o in sim.bodies):       # never on top of another vehicle
            return
        b = actors.Body(x, y, h, self.rng.choice(self.kinds), 0)
        b.empty = False
        b.ctl = (0.0, 0.0, True)
        b.name = (TXT("transit.0006") + f'{ln.ref} → {ln.dest}')[:60]
        b.bus_line = ln.ref
        sim.bodies.append(b)
        self.buses.append(Bus(ln, b, k + 1))

    def _drive(self, bus, dt):
        """Pure pursuit along the line, slowing for curves and stops; physics does the rest."""
        b, ln = bus.body, bus.line
        fx, fy = math.cos(b.h), math.sin(b.h)
        vf = b.vx * fx + b.vy * fy
        best, bi = 1e9, bus.i
        for k in range(max(0, bus.i - 3), min(len(ln.pts) - 1, bus.i + 25)):   # progress = closest vertex nearby
            if ln.cum[k] - getattr(bus, "s", ln.cum[bus.i]) > 60.0:   # lines double back on themselves: never skip ahead
                break
            d = math.hypot(ln.pts[k][0] - b.x, ln.pts[k][1] - b.y)
            if d < best:
                best, bi = d, k
        bus.i = max(bus.i, bi)
        bus.off = best
        s_bus, bus.off = ln.cum[bus.i], best                     # exact distance along the line (vertices can be far apart)
        seg = min(bus.i, len(ln.pts) - 2)
        for i0 in (bus.i - 1, bus.i):
            if 0 <= i0 < len(ln.pts) - 1:
                ax, ay = ln.pts[i0]
                bx_, by_ = ln.pts[i0 + 1]
                sl = ln.cum[i0 + 1] - ln.cum[i0]
                tt = 0.0 if sl <= 0 else max(0.0, min(1.0, ((b.x - ax) * (bx_ - ax) + (b.y - ay) * (by_ - ay)) / (sl * sl)))
                dd = math.hypot(b.x - ax - (bx_ - ax) * tt, b.y - ay - (by_ - ay) * tt)
                if dd < bus.off + 1e-6:
                    s_bus, bus.off, seg = ln.cum[i0] + tt * sl, dd, i0
        bus.s = s_bus
        j = bus.i
        while j < len(ln.pts) - 1 and ln.cum[j] - s_bus < 10.0 + abs(vf) * 0.8:   # look-ahead point (from the true position)
            j += 1
        tx, ty = ln.pts[j]
        pj = max(j - 1, 0)                                          # the line is the road's centre: keep to the right lane,
        ddx, ddy = tx - ln.pts[pj][0], ty - ln.pts[pj][1]           # and pull in to the kerb for a stop
        dd = math.hypot(ddx, ddy) or 1.0
        nx, ny = -ddy / dd, ddx / dd
        w = self.sim.w
        right, hw = self._lane(ln, j)                               # centre of the rightmost lane, half the road
        off = max(right, hw - vehicles.DIMS[b.kind][1] / 2 - 0.4) if bus.next_stop - s_bus < 40.0 else right
        while off > 0.5 and hasattr(w, "kerb") and w.kerb(tx + nx * (off + 1.3), ty + ny * (off + 1.3)):
            off -= 0.5                                              # narrow street: don't scrape the pavement
        bus.lane_off = off
        # follow the lane line itself (heading of the road a little ahead + a pull towards the lane), not a far-off point
        # that cuts across the markings: pure pursuit from the centre line left the buses half a lane out
        (ax, ay), (bx_, by_) = ln.pts[seg], ln.pts[seg + 1]
        sl = math.hypot(bx_ - ax, by_ - ay) or 1.0
        lat = (-(b.x - ax) * (by_ - ay) + (b.y - ay) * (bx_ - ax)) / sl     # where the bus is, across the line
        k2 = bus.i
        while k2 < len(ln.pts) - 1 and ln.cum[k2] - s_bus < 4.0 + abs(vf) * 0.4:
            k2 += 1
        h_road = math.atan2(ln.pts[k2][1] - ln.pts[max(k2 - 1, 0)][1], ln.pts[k2][0] - ln.pts[max(k2 - 1, 0)][0])
        bus.lat = lat
        want = self._squeeze(bus)                                   # round a parked car: just as far out as it takes,
        if want < 0 and self._blocked(bus, want, moving=True):      # starting early, and only into a free lane
            want = 0.0
        bus.dodge += max(-1.5 * dt, min(1.5 * dt, want - bus.dodge))
        off += bus.dodge
        err = _wrap(h_road - b.h) + math.atan2(1.2 * (off - lat), abs(vf) + 3.0)
        if bus.wait > 0:                                            # at a stop: doors open
            bus.wait -= dt
            b.ctl = (0.0, 0.0, True)
            return
        if s_bus >= bus.next_stop - 3.0 and abs(vf) < 6:
            k = bus.stop_k
            bus.next_stop, bus.stop_k = math.inf, None
            for c, k2 in getattr(ln, "stops", ()):
                if c > s_bus + 15:
                    bus.next_stop, bus.stop_k = c, k2
                    break
            bus.wait = self.rng.uniform(6.0, 10.0)
            nm = self.stops[k][6] if k is not None and self.stops[k][6] else ln.dest
            self.sim.ev("shout", text=(TXT("transit.0007") + f'{ln.ref} – {nm}.')[:80], x=b.x, y=b.y, who=TXT("transit.0008"))
            self._at_stop(bus, k)
            return
        to_stop = bus.next_stop - s_bus
        v = 13.5 * (1.0 - min(0.8, abs(err) / 1.0))                # 45-50 km/h on the open road
        v = min(v, max(2.0, to_stop * 0.25))
        g = self._gap(bus)                                          # cautious: brakes gently for anything in its path
        if g is not None:
            v = min(v, math.sqrt(2.0 * 1.8 * max(0.0, g - 2.0)))
        sg = getattr(self.sim, "lights", None)
        if sg is not None:                                          # red or yellow ahead: stop at the line like every other vehicle
            rem = sg.red_ahead(b.x, b.y, b.h)
            if rem is not None:
                rem -= vehicles.DIMS[b.kind][0] / 2
                v = min(v, math.sqrt(2.0 * 2.5 * max(rem, 0.0)) if rem > -2.5 else v)
        ahead = self._blocked(bus)
        if ahead:
            v = 0.0
        if bus.rev > 0:
            bus.rev -= dt
            b.ctl = (-0.6, -max(-1.0, min(1.0, err * 2)), False)
            return
        thr = max(-1.0, min(1.0, (v - vf) * 0.5))
        b.ctl = (thr, max(-1.0, min(1.0, err * 1.6)), v < 0.5 and abs(vf) < 1.0)
        if abs(vf) < 0.5 and v > 2.0 and not ahead:
            bus.stuck += dt
            if bus.stuck > 4.0:
                bus.stuck, bus.rev = 0.0, 1.5
        else:
            bus.stuck = 0.0

    # ------------------------------------------------------------------ people at the stops
    def door(self, b):
        """Front door on the kerb side (right side of the bus)."""
        fx, fy = math.cos(b.h), math.sin(b.h)
        L, W = vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2
        return b.x + fx * L * 0.55 - fy * (W + 0.5), b.y + fy * L * 0.55 + fx * (W + 0.5)

    def _new_ped(self, x, y, h, mode):
        import actors as A
        p = A.Ped()
        rng = self.rng
        p.arch = rng.choice(vehicles.WALKERS)
        p.shirt, p.skin = rng.randrange(3), rng.randrange(4)
        p.hp = float(vehicles.FIGHT[p.arch][0])
        p.x, p.y, p.h, p.mode = x, y, h, mode
        p.v = rng.uniform(1.0, 1.5)
        self.sim.peds.list.append(p)
        return p

    def _crowd(self):
        """How busy the stops are: morning and afternoon rush hours, a quiet night (round 31)."""
        h = getattr(getattr(self.sim, "clock", None), "hour", 12.0)
        for lo, hi, f in ((7.0, 9.5, 2.0), (12.0, 14.0, 1.3), (15.5, 18.5, 2.0), (21.0, 24.0, 0.35), (0.0, 5.5, 0.15)):
            if lo <= h < hi:
                return f
        return 1.0

    def _at_stop(self, bus, k):
        """Doors open: the queue walks to the door, a few people get off."""
        b = bus.body
        dx_, dy_ = self.door(b)
        for _ in range(int(round(self.rng.choice((0, 1, 1, 2, 3, 4, 5)) * self._crowd() * self.rng.uniform(0.6, 1.4)))):
            p = self._new_ped(dx_ + self.rng.uniform(-0.6, 0.6), dy_ + self.rng.uniform(-0.6, 0.6), b.h - math.pi / 2, "alight")
            p.t = self.rng.uniform(5.0, 9.0)
            fx, fy = math.cos(b.h), math.sin(b.h)
            a = math.atan2(fx, -fy) + self.rng.uniform(-0.9, 0.9)          # away from the road, spread out
            p.vx, p.vy = math.cos(a) * p.v, math.sin(a) * p.v
            p.h = a
            if not self.sim.peds.adopt(p):                          # off the bus: an ordinary passer-by from here on
                self.movers.append(p)
            self.served[1] += 1
        if k is not None and math.hypot(self.stops[k][0] - b.x, self.stops[k][1] - b.y) < 25:
            for p in self.queue.pop(k, []):
                if p in self.sim.peds.list and p.mode == "queue":
                    p.mode, p.bus, p.goal, p.bus_obj = "board", b, None, bus
                    self.movers.append(p)
            self.refill[k] = self.rng.uniform(25.0, 70.0)

    def _people(self, dt, fx, fy):
        sim, rng = self.sim, self.rng
        if not self.stops:
            return
        alive = set(map(id, sim.peds.list))
        for k, st in enumerate(self.stops):                    # queues at the stops near the player
            d = math.hypot(st[0] - fx, st[1] - fy)
            q = self.queue.get(k)
            if d > 160:
                if q:
                    for p in q:
                        if p in sim.peds.list:
                            sim.peds.list.remove(p)
                    del self.queue[k]
                continue
            if q is not None:
                q[:] = [p for p in q if id(p) in alive and (p.mode == "queue" or getattr(p, "goal", None))]
            if q is None or (not q and self.refill.get(k, 0) <= 0):
                q = self.queue.setdefault(k, [])
                if not q:
                    n_q = max(0, int(round(rng.randint(1, 5) * self._crowd() * rng.uniform(0.6, 1.4))))
                    for j in range(n_q):
                        u = (j - (n_q - 1) / 2.0) * min(1.1, 3.8 / max(n_q, 1)) + rng.uniform(-0.25, 0.25)
                        x, y = st[0] + st[2] * u + (st[4] - st[0]) * 0.25, st[1] + st[3] * u + (st[5] - st[1]) * 0.25
                        face = math.atan2(st[5] - st[1], st[4] - st[0])
                        if d > 60:                              # out of sight: already waiting when you arrive
                            p = self._new_ped(x, y, face, "queue")
                        else:                                   # in sight: they walk up to the stop
                            a = rng.uniform(0, 6.28)
                            p = self._new_ped(x - (st[4] - st[0]) * 4 + math.cos(a) * 9, y - (st[5] - st[1]) * 4 + math.sin(a) * 9, a, "board")
                            p.goal, p.face, p.bus = (x, y), face, None
                            self.movers.append(p)
                        q.append(p)
                self.refill[k] = rng.uniform(30.0, 80.0)
            self.refill[k] = self.refill.get(k, 0) - dt
            for p in q:                                          # fidget while waiting
                p.anim = 0.0
                p.gz = sim.w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
        alive = set(map(id, sim.peds.list))                     # again: includes the people just added
        keep = []
        for p in self.movers:
            if id(p) not in alive or p.mode not in ("board", "alight"):
                continue
            p.gz = sim.w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
            if p.mode == "board" and getattr(p, "goal", None):      # walking up to the stop to queue
                dx, dy = p.goal[0] - p.x, p.goal[1] - p.y
                dd = math.hypot(dx, dy)
                if dd < 0.4:
                    p.mode, p.h, p.goal = "queue", p.face, None
                    continue
                p.h = math.atan2(dy, dx)
                p.x += dx / dd * p.v * dt
                p.y += dy / dd * p.v * dt
                p.anim += dt * 2.5
                keep.append(p)
                continue
            if p.mode == "board":
                b = p.bus
                if b not in sim.bodies or (getattr(p, "bus_obj", None) is not None and p.bus_obj.wait <= 0 and b.speed > 1.5):   # missed it
                    p.t = 8.0
                    p.vx, p.vy = math.cos(p.h) * -1.0, math.sin(p.h) * -1.0
                    p.mode = "alight"
                    if not sim.peds.adopt(p):                      # walks on like anyone else
                        keep.append(p)
                    continue
                tx, ty = self.door(b)
                dx, dy = tx - p.x, ty - p.y
                dd = math.hypot(dx, dy)
                if dd < 0.8:
                    sim.peds.list.remove(p)                        # on board
                    self.served[0] += 1
                    continue
                p.h = math.atan2(dy, dx)
                p.x += dx / dd * p.v * 1.2 * dt
                p.y += dy / dd * p.v * 1.2 * dt
                p.anim += dt * 2.5
                keep.append(p)
            else:
                p.t -= dt
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.anim += dt * 2.5
                if p.t <= 0 or math.hypot(p.x - fx, p.y - fy) > 170:
                    if p.t <= 0 and math.hypot(p.x - fx, p.y - fy) < 60:
                        p.t = 4.0                                    # still in view: keep strolling
                        a = p.h + rng.uniform(-0.6, 0.6)
                        p.vx, p.vy, p.h = math.cos(a) * p.v, math.sin(a) * p.v, a
                        keep.append(p)
                    else:
                        sim.peds.list.remove(p)
                    continue
                keep.append(p)
        self.movers = keep

    def _lane(self, ln, j):
        """(offset of the rightmost lane's centre, half width) of the road under vertex j of the line, from the road
        graph's lane layout (the same one the cars and the painted markings use)."""
        r = ln.lane.get(j)
        if r is None:
            r = (1.8, 3.5)
            w = self.sim.w
            x, y = ln.pts[j]
            a, b_ = ln.pts[max(j - 1, 0)], ln.pts[min(j + 1, len(ln.pts) - 1)]
            hx, hy = b_[0] - a[0], b_[1] - a[1]
            hl = math.hypot(hx, hy) or 1.0
            sg, bd = w.sg, 6.0
            for ei in {ei for cx in (int(x // sg) - 1, int(x // sg), int(x // sg) + 1)
                       for cy in (int(y // sg) - 1, int(y // sg), int(y // sg) + 1) for ei in w.drive_cells.get((cx, cy), ())}:
                e = w.edges[ei]
                for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy or 1e-9
                    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
                    d = math.hypot(x - ax - dx * t, y - ay - dy * t)
                    if d < bd and abs(dx * hx + dy * hy) / (math.sqrt(l2) * hl) > 0.7:     # the road the line runs along
                        bd, r = d, (max(actors.Traffic.lanes_of(e)), e["w"] / 2)
            ln.lane[j] = r
        return r

    def _near(self, bus, standing=False, moving=False, reach=40.0):
        """Things on the road ahead of the bus, measured along its line: [(distance of their rear past the bus front,
        across the line, half width across the line)] -- along the line, so a bend does not hide or invent anything."""
        sim, b, ln = self.sim, bus.body, bus.line
        L = vehicles.DIMS[b.kind][0] / 2
        objs = [(o.x, o.y, o.h, vehicles.HALF_W[o.kind], vehicles.HALF_L[o.kind]) for o in sim.bodies
                if o is not b and not (moving and o.speed < 0.3) and not (standing and o.speed >= 0.3)]
        if not standing:
            objs += [(c.x, c.y, c.h, vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind]) for c in sim.traffic.cars]
            if sim.mode == "foot" and sim.walker is not None:
                objs.append((sim.walker.x, sim.walker.y, 0.0, 0.4, 0.3))
        r2 = (reach + L + 8.0) ** 2
        out = []
        for x, y, h, hw, hl in objs:
            if (x - b.x) ** 2 + (y - b.y) ** 2 > r2:
                continue
            best = None
            k = max(0, bus.i - 2)
            while k < len(ln.pts) - 1 and ln.cum[k] < bus.s + reach + L + hl:
                (ax, ay), (bx_, by_) = ln.pts[k], ln.pts[k + 1]
                sl = ln.cum[k + 1] - ln.cum[k]
                if sl > 0:
                    ux, uy = (bx_ - ax) / sl, (by_ - ay) / sl
                    t = (x - ax) * ux + (y - ay) * uy
                    if -1.0 <= t <= sl + 1.0:
                        lt = -(x - ax) * uy + (y - ay) * ux
                        if best is None or abs(lt) < abs(best[1]):
                            ca, sa = abs(math.cos(h) * ux + math.sin(h) * uy), abs(-math.sin(h) * ux + math.cos(h) * uy)
                            best = (ln.cum[k] + t, lt, ca * hw + sa * hl, ca * hl + sa * hw)
                k += 1
            if best is not None and best[0] + best[3] > bus.s - L:          # not yet wholly behind the bus
                out.append((best[0] - best[3] - bus.s - L, best[1], best[2]))
        return out

    def _blocked(self, bus, extra=0.0, standing=False, moving=False):
        """Something (car, the player, a pedestrian) in the bus's own path just ahead: wait instead of ramming it.  The
        path is the bus's width along its line, where the bus is now (close by) or will be (further on); `extra` moves it
        sideways (to the left, < 0); `standing` only counts things that stand still, `moving` only moving ones."""
        b = bus.body
        vf = max(0.0, b.vx * math.cos(b.h) + b.vy * math.sin(b.h))
        look = 4.0 + vf * 1.6                                       # free road wanted: more the faster it goes (it brakes slowly)
        hw_b = vehicles.HALF_W[b.kind]
        tgt = getattr(bus, "lane_off", 0.0) + bus.dodge + extra
        for gap, lat, hw in self._near(bus, standing, moving, look + 2.0):
            if -1.0 < gap < look:
                at = (bus.lat + extra) if gap < 3.0 else tgt
                if abs(lat - at) < (hw_b + hw) * 1.1:                     # its width and the other's, 10 % spare
                    return True
        return False

    def _gap(self, bus, reach=45.0):
        """Free road ahead along the bus's path (as wide as the bus and the other thing, 10 % spare), or None."""
        hw_b = vehicles.HALF_W[bus.body.kind]
        tgt = getattr(bus, "lane_off", 0.0) + bus.dodge
        best = None
        for gap, lat, hw in self._near(bus, reach=reach):
            at = bus.lat if gap < 3.0 else tgt
            if -1.0 < gap and abs(lat - at) < (hw_b + hw) * 1.1 and (best is None or gap < best):
                best = gap
        return best

    def _squeeze(self, bus):
        """How far (< 0, to the left) the bus must step out of its lane to pass a car standing in it (a parked or
        abandoned one), with a hand's width spare; 0 when there is none ahead."""
        b = bus.body
        hw_b, off = vehicles.HALF_W[b.kind], getattr(bus, "lane_off", 0.0)
        need = 0.0
        for gap, lat, hw in self._near(bus, standing=True, reach=30.0):
            spare = (hw_b + hw) * 0.15                                 # a little more than the 10 % the brakes look for
            if gap > -vehicles.DIMS[b.kind][0] and abs(lat - off) < hw_b + hw + spare:    # in the way, or still beside it
                need = min(need, lat - hw - hw_b - spare - off)
        lo = -self._lane(bus.line, bus.i)[1] + hw_b + 0.3 - off       # as far as the far edge of the road (one-ways: the
        return need if need >= lo else 0.0                          # other lanes) -- no way round at all: wait
