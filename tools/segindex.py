"""Which road segments can be near a point?  A fine grid holding each segment only in the cells it reaches, for the build's
"does this prop stand on a carriageway" tests, asked hundreds of thousands of times."""
import math

CELL = 8.0
REACH = 6.0                          # tests asking for more than a segment's half width + this fall back to every segment around


class SegIndex:
    def __init__(self, segments):
        """segments: [(ax, ay, bx, by, half width, ...)]"""
        self.fine, self.coarse = {}, {}
        half = CELL * 0.7072                                   # centre of a cell to its corners
        for s in segments:
            ax, ay, bx, by, hw = s[:5]
            r = hw + REACH
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            for gx in range(int((min(ax, bx) - r) // CELL), int((max(ax, bx) + r) // CELL) + 1):
                for gy in range(int((min(ay, by) - r) // CELL), int((max(ay, by) + r) // CELL) + 1):
                    x, y = (gx + 0.5) * CELL, (gy + 0.5) * CELL
                    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
                    if math.hypot(x - ax - dx * t, y - ay - dy * t) <= r + half:
                        self.fine.setdefault((gx, gy), []).append(s)
            for gx in range(int(min(ax, bx) // 20) - 1, int(max(ax, bx) // 20) + 2):
                for gy in range(int(min(ay, by) // 20) - 1, int(max(ay, by) // 20) + 2):
                    self.coarse.setdefault((gx, gy), []).append(s)

    def near(self, x, y, clear):
        """Every segment that can be closer to (x, y) than its half width + clear."""
        if clear <= REACH:
            return self.fine.get((int(x // CELL), int(y // CELL)), ())
        return self.coarse.get((int(x // 20), int(y // 20)), ())
