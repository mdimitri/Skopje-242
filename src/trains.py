"""Trains on the railway built by tools/rail.py: a few three-car trains run up and down the longest lines, wait at the
stations, and close the level crossings (barriers down, road traffic stops) while they pass."""
import math

import pyray as rl

SPEED = 16.0                     # m/s on open track (≈ 58 km/h)
CAR_L, GAP, CARS = 20.0, 1.2, 3  # carriage length, coupling gap, carriages
CLOSE = 140.0                    # a crossing is closed while the train is this close along the line
DWELL = 20.0                     # seconds at a station
# New in-game strings (Macedonian, not in text/ -- for the editor):
TXT_BOARD = "Во воз си (билет "                       # + fare +
TXT_BOARD2 = " ден.)  –  F: излези на станица"
TXT_ALIGHT = "Слезе од возот."
BODY = rl.Color(226, 228, 232, 255)
STRIPE = rl.Color(196, 40, 40, 255)
ROOF = rl.Color(70, 72, 80, 255)
GLASS = rl.Color(60, 90, 120, 255)
BAR = (rl.Color(236, 236, 236, 255), rl.Color(214, 36, 36, 255))


class Line:
    def __init__(self, pts):
        self.p = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.len = self.cum[-1]

    def at(self, s):
        """(x, z, y, heading) at distance s along the line."""
        s = min(max(s, 0.0), self.len)
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if self.cum[m] <= s:
                lo = m
            else:
                hi = m
        a, b = self.p[lo], self.p[hi]
        t = (s - self.cum[lo]) / ((self.cum[hi] - self.cum[lo]) or 1.0)
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, math.atan2(b[1] - a[1], b[0] - a[0])

    def project(self, x, z):
        """Distance along the line of the point nearest (x, z), and how far that point is."""
        best = (1e18, 0.0)
        for k, (a, b) in enumerate(zip(self.p, self.p[1:])):
            dx, dz = b[0] - a[0], b[1] - a[1]
            l2 = dx * dx + dz * dz or 1e-9
            t = max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dz) / l2))
            d = math.hypot(x - a[0] - dx * t, z - a[1] - dz * t)
            if d < best[0]:
                best = (d, self.cum[k] + t * math.sqrt(l2))
        return best[1], best[0]


class Train:
    def __init__(self, line, s, d):
        self.line, self.s, self.d = line, s, d
        self.v, self.wait, self.last_stop = SPEED, 0.0, None
        self.ended = False                                    # set at the end of the line (the train leaves the map)


class Trains:
    def __init__(self, world):
        tr = getattr(world, "track", None) or {}
        self.lines = [Line(p) for p in tr.get("lines", ()) if len(p) >= 2]
        self.lines = [ln for ln in self.lines if ln.len > 600.0]
        self.trains = []
        for i, ln in enumerate(self.lines[:3]):                 # one train per long line, two on the longest
            self.trains.append(Train(ln, ln.len * 0.2, 1))
            if i == 0 and ln.len > 3000:
                self.trains.append(Train(ln, ln.len * 0.75, -1))
        self.stops = {}                                       # line -> [s of each station on it]
        for _name, x, z, _yaw in getattr(world, "stations", ()) or ():
            for ln in self.lines:
                s, d = ln.project(x, z)
                if d < 40.0:
                    self.stops.setdefault(id(ln), []).append(s)
        self.xings = {}                                       # (edge, s on the edge) -> (line, s on the line, x, z, yaw)
        self.by_edge = {}
        for x, z, ei, es, yaw in tr.get("crossings", ()):
            for ln in self.lines:
                s, d = ln.project(x, z)
                if d < 6.0:
                    self.xings[(ei, es)] = (ln, s, x, z, yaw)
                    self.by_edge.setdefault(ei, []).append(es)
                    break
        self.closed = set()

    def update(self, dt):
        for t in self.trains:
            if t.wait > 0:
                t.wait -= dt
                continue
            span = CARS * (CAR_L + GAP)
            stop = None                                       # the next station within braking distance ahead
            for s in self.stops.get(id(t.line), ()):
                if 0.0 < (s - t.s) * t.d < 120.0 and s != t.last_stop:
                    stop = s
                    break
            want = SPEED
            if stop is not None:
                want = max(2.0, math.sqrt(2 * 0.9 * max(abs(stop - t.s) - 1.0, 0.0)))
            end = t.line.len - span if t.d == 1 else span
            rem = (end - t.s) * t.d
            want = min(want, max(2.0, math.sqrt(2 * 0.9 * max(rem, 0.0))))
            t.v += max(-1.2 * dt, min(0.6 * dt, want - t.v))
            t.s += t.d * t.v * dt
            if stop is not None and abs(stop - t.s) < 1.5:
                t.wait, t.last_stop, t.v = DWELL, stop, 0.0
            if rem <= 0.5:                                    # end of the line: wait, then back the other way
                t.s, t.d, t.wait, t.v, t.last_stop = end, -t.d, DWELL, 0.0, None
                t.ended = True
        closed = set()
        for key, (ln, s, _x, _z, _yaw) in self.xings.items():
            for t in self.trains:
                if t.line is ln:
                    tail = t.s - t.d * CARS * (CAR_L + GAP)
                    if min(abs(s - t.s), abs(s - tail)) < CLOSE or min(t.s, tail) <= s <= max(t.s, tail):
                        closed.add(key)
        self.closed = closed

    def stop_at(self, ei, d, s, L):
        """Distance ahead (along the car's travel) to the stop line of a closed crossing on edge ei, or None."""
        for es in self.by_edge.get(ei, ()):
            if (ei, es) in self.closed:
                ahead = (es if d == 1 else L - es) - s
                if -1.0 < ahead < 60.0:
                    return ahead - 5.0
        return None

    def draw(self, rect, ground_y):
        x0, z0, x1, z1 = rect
        for t in self.trains:
            for k in range(CARS):
                s = t.s - t.d * (k * (CAR_L + GAP) + CAR_L / 2)
                x, z, y, h = t.line.at(s)
                if not (x0 - 30 < x < x1 + 30 and z0 - 30 < z < z1 + 30):
                    continue
                rl.rl_push_matrix()
                rl.rl_translatef(x, y, z)
                rl.rl_rotatef(-math.degrees(h), 0.0, 1.0, 0.0)
                rl.draw_cube(rl.Vector3(0, 0.6, 0), CAR_L, 0.5, 2.9, ROOF)              # underframe
                rl.draw_cube(rl.Vector3(0, 2.1, 0), CAR_L, 2.5, 3.0, BODY)
                rl.draw_cube(rl.Vector3(0, 2.4, 0), CAR_L - 1.0, 0.9, 3.04, GLASS)      # window band
                rl.draw_cube(rl.Vector3(0, 3.5, 0), CAR_L - 0.4, 0.3, 2.8, ROOF)
                rl.draw_cube(rl.Vector3(0, 1.55, 0), CAR_L + 0.02, 0.45, 3.04, STRIPE)   # livery stripe
                for e in ((t.d,) if k == 0 else ()) + ((-t.d,) if k == CARS - 1 else ()):
                    rl.draw_cube(rl.Vector3(e * (CAR_L / 2 + 0.05), 2.0, 0), 0.2, 2.6, 2.9, GLASS)      # cab front
                rl.rl_pop_matrix()
        for (ei, es), (_ln, _s, x, z, yaw) in self.xings.items():
            if not (x0 - 5 < x < x1 + 5 and z0 - 5 < z < z1 + 5):
                continue
            down = (ei, es) in self.closed
            for sgn in (-1, 1):                               # a barrier arm each side of the line
                ox, oz = -math.sin(yaw) * 4.2 * sgn, math.cos(yaw) * 4.2 * sgn
                rl.rl_push_matrix()
                rl.rl_translatef(x + ox, ground_y(x + ox, z + oz) + 1.0, z + oz)
                rl.rl_rotatef(-math.degrees(yaw), 0.0, 1.0, 0.0)
                if down:
                    rl.draw_cube(rl.Vector3(0, 0, 0), 8.0, 0.14, 0.14, BAR[int(rl.get_time() * 2) & 1])
                else:
                    rl.draw_cube(rl.Vector3(sgn * 3.6, 2.5, 0), 0.14, 5.0, 0.14, BAR[0])
                rl.rl_pop_matrix()
