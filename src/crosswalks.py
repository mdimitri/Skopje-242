"""Spatial queries shared by the road mesh and the pedestrian simulation."""
import heapq
import math
import time

_BUDGET_MS = 3.0            # route searches per frame (all pedestrians together) and per single search
_frame_end = 0.0


def begin_frame():
    """Called once per pedestrian update: opens this frame's route-search budget."""
    global _frame_end
    _frame_end = time.perf_counter() + _BUDGET_MS / 1000.0


def over_budget():
    return time.perf_counter() >= _frame_end


class CrossingMap:
    CELL = 24

    def __init__(self, zebras=(), cores=()):
        self.zebras, self.cores = {}, {}
        for x, y, dx, dy, width, *details in zebras:
            r = width / 2 + 2
            node = details[2] if len(details) > 2 else None
            self._add(self.zebras, (x, y, dx, dy, width / 2, node), x - r, y - r, x + r, y + r)
        for ring in cores:
            xs, ys = zip(*ring)
            self._add(self.cores, ring, min(xs), min(ys), max(xs), max(ys))

    def _add(self, grid, value, x0, y0, x1, y1):
        for ix in range(int(x0 // self.CELL), int(x1 // self.CELL) + 1):
            for iy in range(int(y0 // self.CELL), int(y1 // self.CELL) + 1):
                grid.setdefault((ix, iy), []).append(value)

    def _zebras_at(self, x, y):
        for px, py, dx, dy, half, node in self.zebras.get((int(x // self.CELL), int(y // self.CELL)), ()):
            ox, oy = x - px, y - py
            if abs(ox * dx + oy * dy) <= 1.55 and abs(oy * dx - ox * dy) <= half + 1.0:
                yield px, py, node

    def zebra(self, x, y):
        return next(self._zebras_at(x, y), None) is not None

    def wait_for_signal(self, x, y, tx, ty, lights):
        if lights is None or self.zebra(x, y):
            return False
        return any(node in lights.candidate_groups and not lights.pedestrian_green(node)
                   for _, _, node in self._zebras_at(tx, ty))

    def core(self, x, y):
        for ring in self.cores.get((int(x // self.CELL), int(y // self.CELL)), ()):
            if all((bx - ax) * (y - ay) >= (by - ay) * (x - ax)
                   for (ax, ay), (bx, by) in zip(ring, (*ring[1:], ring[0]))):
                return True
        return False


def crosses_wall(world, x, y, tx, ty):
    if not hasattr(world, "edges_near"):
        return False
    dx, dy = tx - x, ty - y
    for ax, ay, bx, by in world.edges_near((x + tx) / 2, (y + ty) / 2, math.hypot(dx, dy) / 2 + 0.3):
        wx, wy = bx - ax, by - ay
        cross = dx * wy - dy * wx
        if abs(cross) < 1e-6:
            continue
        ox, oy = ax - x, ay - y
        t, u = (ox * wy - oy * wx) / cross, (ox * dy - oy * dx) / cross
        if 0.0 < t <= 1.0 and 0.0 <= u <= 1.0:
            return True
    return False


def walk_path(world, start, goal):
    """Find a short route around an asphalt core, crossing roads only at marked crossings."""
    def clear(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        steps = max(1, math.ceil(math.hypot(dx, dy) / 0.65))
        return (all(world.pedestrian_ground(a[0] + dx * i / steps, a[1] + dy * i / steps)
                    for i in range(1, steps + 1))
                and not crosses_wall(world, *a, *b))

    if clear(start, goal):
        return [goal]
    step = 1.2
    origin = round(start[0] / step), round(start[1] / step)
    finish = round(goal[0] / step), round(goal[1] / step)
    todo = [(math.dist(origin, finish), 0.0, origin)]
    best, links = {origin: 0.0}, {}
    stop = min(_frame_end, time.perf_counter() + _BUDGET_MS / 1000.0) if _frame_end else 0.0
    while todo and len(best) < 950:
        if stop and time.perf_counter() > stop:       # out of time: give up like "no route" (the caller retries later)
            return None
        _, cost, cell = heapq.heappop(todo)
        if cost != best[cell]:
            continue
        point = start if cell == origin else (cell[0] * step, cell[1] * step)
        if math.dist(point, goal) <= 2.2 and clear(point, goal):
            path = [goal]
            while cell != origin:
                path.append((cell[0] * step, cell[1] * step))
                cell = links[cell]
            return list(reversed(path))
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            cell2 = cell[0] + dx, cell[1] + dy
            target = cell2[0] * step, cell2[1] * step
            new = cost + math.hypot(dx, dy)
            if new < best.get(cell2, math.inf) and clear(point, target):
                best[cell2], links[cell2] = new, cell
                heapq.heappush(todo, (new + math.dist(cell2, finish), new, cell2))
    return None
