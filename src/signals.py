"""Traffic lights that actually work: every signalised junction runs one 30 s cycle (two groups of approaches,
green / yellow / all-red), and neighbouring junctions are offset into a green wave along the city's main
east-west axis, so a car driving at ~45 km/h meets green after green. AI traffic stops on red and yellow."""
import pyray as rl

CYCLE = 30.0
GREEN, YELLOW, CLEAR = 12.0, 2.5, 0.5          # per group; the two groups share one cycle
WAVE = 12.5                                     # m/s: speed of the green wave (≈ 45 km/h)
COLS = {0: rl.Color(60, 235, 100, 255), 1: rl.Color(250, 200, 40, 255), 2: rl.Color(240, 50, 40, 255)}


class Signals:
    def __init__(self, world):
        self.items = list(getattr(world, "signals", []) or [])
        self.by_edge = {}
        for i, (node, ei, end, grp, lx, lz, jx, jz) in enumerate(self.items):
            self.by_edge[(ei, end)] = i
        self.t = 0.0

    def update(self, dt):
        self.t += dt

    def state(self, i):
        """0 green, 1 yellow, 2 red for signal i."""
        _n, _e, _end, grp, _lx, _lz, jx, _jz = self.items[i]
        ph = (self.t - jx / WAVE + grp * CYCLE / 2) % CYCLE
        if ph < GREEN:
            return 0
        if ph < GREEN + YELLOW:
            return 1
        return 2

    def stop_for(self, ei, end):
        """True when a car on edge ei heading to its end (0 = a, 1 = b) must stop at the line."""
        i = self.by_edge.get((ei, end))
        return i is not None and self.state(i) != 0

    def draw(self, rect, ground_y):
        """The live lamp of every visible signal (the poles themselves are baked meshes)."""
        x0, y0, x1, y1 = rect
        for i, it in enumerate(self.items):
            lx, lz = it[4], it[5]
            if x0 - 5 < lx < x1 + 5 and y0 - 5 < lz < y1 + 5:
                st = self.state(i)
                y = ground_y(lx, lz)
                rl.draw_cube(rl.Vector3(lx, y + 3.12 + 0.30 * (2 - (2, 1, 0)[st]), lz), 0.38, 0.22, 0.38, COLS[st])
                rl.draw_cube(rl.Vector3(lx, y + 4.03, lz), 0.4, 0.05, 0.4, COLS[st])
