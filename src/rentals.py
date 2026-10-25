"""Rental e-scooters: a few stand on the pavement beside every other bus stop; F pays the fare and you ride off.

They are ordinary physics bodies (kind "E-Trotinet") with b.rental set, spawned near the player and removed again
far away while nobody has moved them."""
import math

import vehicles

FARE = 30
KIND = vehicles.IDS.index("E-Trotinet")


class Rentals:
    def __init__(self, sim):
        self.sim = sim
        self.spots = []           # (x, y, heading)
        for i, st in enumerate(getattr(sim.w, "bus_stops", None) or []):
            if i % 2:
                continue
            px, py, dx, dy = st[:4]
            for k in range(2 + i % 3):                 # 2-4 in a row along the kerb, a few metres past the shelter
                self.spots.append((px + dx * (4.5 + 0.9 * k), py + dy * (4.5 + 0.9 * k), math.atan2(dy, dx) + 0.5))
        self.live = {}            # spot index -> Body

    def update(self, dt):
        import actors
        sim = self.sim
        fx, fy = sim.focus()[:2]
        for i, (x, y, h) in enumerate(self.spots):
            b = self.live.get(i)
            near = (x - fx) ** 2 + (y - fy) ** 2 < 140 ** 2
            if b is not None:
                if b not in sim.bodies or not b.rental:     # ridden away or wrecked: the spot fills again later
                    del self.live[i]
                elif not near and math.hypot(b.x - x, b.y - y) < 1.0:
                    sim.bodies.remove(b)
                    del self.live[i]
            elif near:
                b = actors.Body(x, y, h, KIND, 0)
                b.rental = True
                sim.bodies.append(b)
                self.live[i] = b
