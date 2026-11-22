"""Gentle lane-centering for the car the player drives: a few percent of steering that fades in after a second of
steady straight driving on a ordinary road lane and vanishes the instant the player does anything of their own."""
import math

import vehicles
from roadwidth import lane_bounds, lane_count

MIN_SPEED = 8.0          # m/s (~29 km/h)
MAX_ANGLE = 0.09         # rad off the lane direction (~5 deg)
MAX_OFFSET = 1.3         # m from the nearest lane centre
MAX_SLIDE = 1.2          # m/s sideways speed: more is a drift
END_MARGIN = 10.0        # m from either end of the edge: junction mouths are left alone
INPUT_CUT = 0.05         # any steering input above this ends the assist at once
RAMP = 1.2               # s to fade in
MAX_CMD = 0.09           # strongest steering command added (of 1.0 full lock)
K_HEADING, K_OFFSET = 1.0, 0.045
SKIP_KINDS = (vehicles.BTR, vehicles.SEMI, vehicles.ARTIC_BUS)


class LaneAssist:
    def __init__(self):
        self.strength = 0.0

    @staticmethod
    def _cells(w):
        """Grid of the plain drivable edges that also holds every cell a long straight segment crosses (World.drive_cells
        only knows each segment's ends and middle)."""
        cells = getattr(w, "_lane_cells", None)
        if cells is None:
            cells = w._lane_cells = {}
            sg = w.sg
            for i, e in enumerate(w.edges):
                if not e["drive"] or e["bridge"] or e.get("taper") or e["len"] < 2 * END_MARGIN + 6.0 or e["cls"] in ("service", "living_street"):
                    continue
                keys = set()
                for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                    n = max(1, int(math.hypot(bx - ax, by - ay) / (sg * 0.5)))
                    keys.update((int((ax + (bx - ax) * k / n) // sg), int((ay + (by - ay) * k / n) // sg)) for k in range(n + 1))
                for key in keys:
                    cells.setdefault(key, []).append(i)
        return cells

    def _lane_error(self, w, traffic, x, y, h):
        """(heading error, lateral error) towards the nearest lane centre of the road under the car, or None."""
        sg, grid = w.sg, self._cells(w)
        best = None
        for cx in range(int((x - 8) // sg), int((x + 8) // sg) + 1):
            for cy in range(int((y - 8) // sg), int((y + 8) // sg) + 1):
                for ei in grid.get((cx, cy), ()):
                    e = w.edges[ei]
                    if ei in traffic.internal_links:
                        continue
                    pts, s0 = e["pts"], 0.0
                    for k in range(len(pts) - 1):
                        ax, ay = pts[k]
                        bx, by = pts[k + 1]
                        sx, sy = bx - ax, by - ay
                        sl = math.hypot(sx, sy)
                        if sl < 1e-6:
                            continue
                        ux, uy = sx / sl, sy / sl
                        t = (x - ax) * ux + (y - ay) * uy
                        if 0.0 <= t <= sl and abs(math.cos(h) * ux + math.sin(h) * uy) > 0.9:     # only roads running the way the car points
                            lat = -(x - ax) * uy + (y - ay) * ux          # left of the segment direction
                            if best is None or abs(lat) < best[0]:
                                best = (abs(lat), ei, lat, ux, uy, s0 + t)
                        s0 += sl
        if best is None:
            return None
        _d, ei, lat, ux, uy, s = best
        e = w.edges[ei]
        if s < END_MARGIN or e["len"] - s < END_MARGIN or abs(lat) > e["w"] / 2:
            return None
        d = 1 if math.cos(h) * ux + math.sin(h) * uy > 0 else -1
        road_h = math.atan2(uy, ux) if d == 1 else math.atan2(-uy, -ux)
        # lateral offset in the direction of travel's own left-hand frame (what Traffic.lanes_of is measured in)
        off = lat if d == 1 else -lat
        n = lane_count(e, d)
        lo, hi = lane_bounds(e, d)
        if n == 1 and not e["ow"] and not e.get("directional_lanes"):
            lanes = [max(1.3, hi / 2)]
        else:
            lanes = [lo + (k + 0.5) * (hi - lo) / n for k in range(n)]
        goal = min(lanes, key=lambda v: abs(v - off))
        return math.remainder(road_h - h, math.tau), goal - off

    def steer(self, car, w, traffic, steer_in, throttle, handbrake, enabled, dt):
        """Extra steering command (-MAX_CMD..MAX_CMD) to add to the player's own input."""
        vf = car.vx * math.cos(car.h) + car.vy * math.sin(car.h)
        vl = -car.vx * math.sin(car.h) + car.vy * math.cos(car.h)
        ok = (enabled and car.kind not in SKIP_KINDS and not car.air and not handbrake and car.alive
              and abs(steer_in) <= INPUT_CUT and abs(car.steer) <= 0.12 and throttle >= -0.2
              and vf >= MIN_SPEED and abs(vl) <= MAX_SLIDE and car.exploded is False
              and (car.az is None or abs(car.az - w.ground_y(car.x, car.y)) < 0.8))
        err = self._lane_error(w, traffic, car.x, car.y, car.h) if ok else None
        if err is None or abs(err[0]) > MAX_ANGLE or abs(err[1]) > MAX_OFFSET:
            self.strength = 0.0                       # drops at once, never eased out
            return 0.0
        self.strength = min(1.0, self.strength + dt / RAMP)
        cmd = K_HEADING * err[0] + K_OFFSET * err[1]
        return max(-MAX_CMD, min(MAX_CMD, cmd)) * self.strength
