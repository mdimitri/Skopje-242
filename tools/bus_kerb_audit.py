"""Bus kerb audit: drives the game's Sim with buses around a point and counts how long a bus's footprint (wheel corners)
stands on a raised pavement (world.kerb), i.e. where a lane change / widening / fork starts the sideways move too early.
Usage: python3 tools/bus_kerb_audit.py <world_dir> <osm_dir> <secs> <seed> cx,cy [cx,cy ...]      (prints one JSON line)"""
import collections
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


def run(world, osm_dir, cx, cy, secs=240, warm=20, seed=1):
    import signals
    import transit
    import vehicles
    from actors import Sim
    random.seed(seed)
    sim = Sim(world, random.Random(seed), 40, 0)
    sim.traffic.signals = sim.lights = signals.Signals(world)
    sim.transit = transit.Transit(sim, osm_dir)
    sim.clock.hour = 11.0
    sim.teleport(cx, cy)
    sim.exit_car()
    sim.bodies.remove(sim.car)
    inp = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 0.0), "run": False, "attack": False, "buy": None, "jump": False}
    dt, steps, on, mov, spots, seen = 0.05, 0, 0, 0, collections.Counter(), set()
    for k in range(int((warm + secs) / dt)):
        sim.update(dt, inp, 1)
        if k * dt < warm:
            continue
        for bus in sim.transit.buses:
            b = bus.body
            L, W = vehicles.DIMS[b.kind][:2]
            c, s = math.cos(b.h), math.sin(b.h)
            steps += 1
            seen.add(id(bus))
            if any(world.kerb(b.x + c * a - s * d, b.y + s * a + c * d) for a, d in ((L / 2, W / 2), (L / 2, -W / 2), (-L / 2, W / 2), (-L / 2, -W / 2))):
                on += 1
                mov += b.speed > 2.0
                spots[(round(b.x / 15) * 15, round(b.y / 15) * 15)] += 1
    return dict(buses=len(seen), bus_steps=steps, kerb_steps=on, kerb_moving=int(mov), kerb_pct=round(100.0 * on / max(steps, 1), 2), top=spots.most_common(6))


if __name__ == "__main__":
    from world import World
    wd, osm, secs, seed = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
    w = World(wd)
    tot = collections.Counter()
    for a in sys.argv[5:]:
        x, y = map(float, a.split(","))
        r = run(w, osm, x, y, secs, seed=seed)
        print(json.dumps(dict(at=a, **r)), flush=True)
