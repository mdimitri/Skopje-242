"""Lane-centering for the car the player drives: steering that fades in after a moment of steady straight driving on an ordinary road lane
and vanishes the instant the player does anything of their own. Strength level 0/1/2 (gentle/medium/strong, menu Контроли → Возење)."""
import math

import vehicles
from roadwidth import lane_bounds, lane_count

# per strength level (0 gentle, 1 medium, 2 strong): min speed m/s, capture angle rad, capture offset m,
# fade-in s, max steering command (of 1.0 lock), heading gain, offset gain
LEVELS = ((8.0, 0.09, 1.3, 1.2, 0.09, 1.0, 0.045),
          (6.0, 0.17, 1.7, 0.6, 0.20, 1.4, 0.09),
          (5.0, 0.26, 2.0, 0.3, 0.32, 1.8, 0.14))
MAX_SLIDE = 1.2          # m/s sideways speed: more is a drift
END_MARGIN = 10.0        # m from either end of the edge: junction mouths are left alone
INPUT_CUT = 0.05         # any steering input above this ends the assist at once
SKIP_KINDS = (vehicles.BTR, vehicles.SEMI, vehicles.ARTIC_BUS)


class LaneAssist:
    def __init__(self):
        self.strength = 0.0
        self.level = 2

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
        """Extra steering command (-max_cmd..max_cmd) to add to the player's own input."""
        min_speed, max_angle, max_offset, ramp, max_cmd, k_head, k_off = LEVELS[max(0, min(2, self.level))]
        vf = car.vx * math.cos(car.h) + car.vy * math.sin(car.h)
        vl = -car.vx * math.sin(car.h) + car.vy * math.cos(car.h)
        ok = (enabled and car.kind not in SKIP_KINDS and not car.air and not handbrake and car.alive
              and abs(steer_in) <= INPUT_CUT and abs(car.steer) <= max_cmd + 0.05 and throttle >= -0.2
              and vf >= min_speed and abs(vl) <= MAX_SLIDE and car.exploded is False
              and (car.az is None or abs(car.az - w.ground_y(car.x, car.y)) < 0.8))
        err = self._lane_error(w, traffic, car.x, car.y, car.h) if ok else None
        if err is None or abs(err[0]) > max_angle or abs(err[1]) > max_offset:
            self.strength = 0.0                       # drops at once, never eased out
            return 0.0
        self.strength = min(1.0, self.strength + dt / ramp)
        cmd = k_head * err[0] + k_off * err[1]
        return max(-max_cmd, min(max_cmd, cmd)) * self.strength
