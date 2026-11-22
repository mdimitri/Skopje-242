"""Headless: synthetic drives for the player's lane-centering assist.
Usage: python3 tools/test_lane_assist.py <world_dir>"""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from world import World
from actors import Sim, drive
from laneassist import LaneAssist
import vehicles

w = World(sys.argv[1], lambda f, note="": None)
sim = Sim(w, random.Random(3), 10, 0)
sim.ev = lambda *a, **k: None
tr = sim.traffic
# longest plain two-way drivable edge
cands = [(e["len"], i) for i, e in enumerate(w.edges) if e["drive"] and not e["bridge"] and not e.get("taper") and i not in tr.internal_links and e["len"] > 200]
cands.sort(reverse=True)
ok = True


def run(ei, off_extra, ang, steer_fn=None, t=6.0, on=True, speed=14.0):
    e = w.edges[ei]
    lane = tr.lanes_of(e, 1)[0]
    s = 15.0
    x, y, h = tr._ref(e, 1, s, lane + off_extra)
    car = sim.car
    car.x, car.y, car.h = x, y, h + ang
    car.vx, car.vy = math.cos(car.h) * speed, math.sin(car.h) * speed
    car.az = None; car.steer = 0.0; car.exploded = False
    la = LaneAssist()
    log = []
    for k in range(int(t / 0.02)):
        st = steer_fn(k * 0.02) if steer_fn else 0.0
        a = la.steer(car, w, tr, st, 0.3, False, on, 0.02)
        drive(car, 0.3, st + a, False, 0.02, w)
        log.append((a, la.strength))
    # final lateral error vs nearest-lane
    err = la._lane_error(w, tr, car.x, car.y, car.h)
    return log, err, car


for ei in [c[1] for c in cands[:3]]:
    log, err, car = run(ei, 0.6, 0.05)
    res = "none" if err is None else f"head {err[0]:+.3f} lat {err[1]:+.2f}"
    peak = max(abs(a) for a, _ in log)
    print(f"edge {ei}: start off+0.6 ang+0.05 -> end {res}, peak assist {peak:.3f}")
    if err is None or abs(err[0]) > 0.02 or abs(err[1]) > 0.35:
        ok = False; print("  NOT converged")
    log, err, car = run(ei, 0.6, 0.05, on=False)
    if max(abs(a) for a, _ in log) != 0:
        ok = False; print("  assist active though disabled")
    log, err, car = run(ei, 0.6, 0.05, steer_fn=lambda t: 0.5 if t > 1.0 else 0.0, t=2.0)
    if log[-1][0] != 0 or log[-1][1] != 0:
        ok = False; print("  assist did not cut instantly on steering")
    log, err, car = run(ei, 0.0, 0.3)
    if max(abs(a) for a, _ in log) != 0:
        ok = False; print("  assist active at 17 deg")
    log, err, car = run(ei, 0.0, 0.05, speed=3.0, t=1.0)
    if max(abs(a) for a, _ in log) != 0:
        ok = False; print("  assist active when slow")
print("PASS" if ok else "FAIL")
