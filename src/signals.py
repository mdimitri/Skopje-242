"""Traffic lights that actually work: every signalised junction runs one 32 s cycle (two groups of approaches,
green / yellow / all-red; the group on the bigger road gets the longer green), and neighbouring junctions are offset
into a green wave along the city's main east-west axis, so a car driving at ~45 km/h meets green after green.  AI
traffic stops on red and yellow.  An emergency vehicle with its siren on turns the lights ahead of it green for itself."""
import math

import pyray as rl

CYCLE = 32.0
GREEN, YELLOW, CLEAR = 15.0, 2.5, 0.5          # green of the major group; the minor one gets the rest of the cycle
WAVE = 12.5                                     # m/s: speed of the green wave (≈ 45 km/h)
RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1}
COLS = {0: rl.Color(60, 235, 100, 255), 1: rl.Color(250, 200, 40, 255), 2: rl.Color(240, 50, 40, 255)}


class Signals:
    def __init__(self, world):
        self.edges = getattr(world, "edges", [])
        self.items = list(getattr(world, "signals", []) or [])
        self.by_edge = {}
        self.nodes = {}                                  # junction -> [(x, y), [signal indices]]
        rank = {}
        for i, (node, ei, end, grp, lx, lz, jx, jz, *_h) in enumerate(self.items):
            self.by_edge[(ei, end)] = i
            self.nodes.setdefault(node, [(jx, jz), []])[1].append(i)
            r = RANK.get(world.edges[ei]["cls"].replace("_link", ""), 0) if hasattr(world, "edges") else 0
            rank[(node, grp)] = max(rank.get((node, grp), 0), r)
        self.major = {n: (1 if rank.get((n, 1), 0) > rank.get((n, 0), 0) else 0) for n in self.nodes}
        self.pre = {}                                    # junction -> (group held green, until)
        self.t = 0.0

    def update(self, dt):
        self.t += dt

    def state(self, i):
        """0 green, 1 yellow, 2 red for signal i."""
        node, _e, _end, grp, _lx, _lz, jx, _jz, *_h = self.items[i]
        p = self.pre.get(node)
        if p is not None and p[1] > self.t:
            return 0 if grp == p[0] else 2
        ph = (self.t - jx / WAVE) % CYCLE
        g1 = GREEN + YELLOW + CLEAR                      # the major group runs first, the minor one after it
        if grp == self.major.get(node, 0):
            return 0 if ph < GREEN else (1 if ph < GREEN + YELLOW else 2)
        g2 = CYCLE - g1 - YELLOW - CLEAR
        return 0 if g1 <= ph < g1 + g2 else (1 if g1 + g2 <= ph < g1 + g2 + YELLOW else 2)

    def preempt(self, x, y, h, reach=90.0):
        """Hold green for the approach an emergency vehicle at (x, y) heading h is driving up to (within reach m)."""
        hx, hy = math.cos(h), math.sin(h)
        for node, ((jx, jz), idx) in self.nodes.items():
            dx, dy = jx - x, jz - y
            if abs(dx) > reach or abs(dy) > reach:
                continue
            fwd = dx * hx + dy * hy
            if not 0.0 < fwd < reach or abs(dy * hx - dx * hy) > 20.0:
                continue
            best, grp = -2.0, None
            for i in idx:                                # the approach it comes along points the same way as it drives
                _n, _e, _end, g, lx, lz, _jx, _jz, *_h = self.items[i]
                ax, ay = self._axis(i)
                d = ax * hx + ay * hy
                if d > best:
                    best, grp = d, g
            if grp is not None and best > 0.5:
                self.pre[node] = (grp, self.t + 2.0)

    def _axis(self, i):
        """Unit direction in which traffic on signal i's approach drives into the junction."""
        a = self.__dict__.setdefault("_ax", {})
        if i not in a:
            _n, ei, end, _g, _lx, _lz, jx, jz, *_h = self.items[i]
            p = self.edges[ei]["pts"]
            q = p[-2] if end == 1 else p[1]              # the vertex before the junction end
            dx, dy = jx - q[0], jz - q[1]
            d = math.hypot(dx, dy) or 1.0
            a[i] = (dx / d, dy / d)
        return a[i]

    def stop_for(self, ei, end):
        """True when a car on edge ei heading to its end (0 = a, 1 = b) must stop at the line."""
        i = self.by_edge.get((ei, end))
        return i is not None and self.state(i) != 0

    def draw(self, rect, ground_y):
        """The live lamp of every visible signal (the poles themselves are baked meshes)."""
        x0, y0, x1, y1 = rect
        for i, it in enumerate(self.items):
            lx, lz = it[4], it[5]
            hb = it[8] if len(it) > 8 else 2.95
            if x0 - 5 < lx < x1 + 5 and y0 - 5 < lz < y1 + 5:
                st = self.state(i)
                y = ground_y(lx, lz)
                ax, ay = self._axis(i)                      # the head faces the approaching traffic, so its lamps sit on that side
                ly = y + hb + 0.17 + 0.30 * (2 - (2, 1, 0)[st])
                a = rl.Vector3(lx - ax * 0.135, ly, lz - ay * 0.135)
                rl.draw_cylinder_ex(a, rl.Vector3(a.x - ax * 0.03, ly, a.z - ay * 0.03), 0.105, 0.105, 10, COLS[st])
                rl.draw_cube(rl.Vector3(lx, y + hb + 1.08, lz), 0.24, 0.05, 0.22, COLS[st])
