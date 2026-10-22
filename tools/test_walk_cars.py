"""Headless: walk/run the player into parked, moving, braking and burning cars from all angles/speeds/dt.
Usage: python3 tools/test_walk_cars.py <world_dir> [trials]"""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from world import World
from actors import Sim, push_from_box

path = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
world = World(path, lambda f, note="": None)
rng = random.Random(7)
res = {}


def vehicles_of(sim):
    return list(sim.bodies) + list(sim.traffic.cars)


def fresh():
    sim = Sim(world, random.Random(rng.random()), 60, 20)
    sim.ev = lambda *a, **k: None
    sim.exit_car()
    return sim


def inp(sim, run):
    return {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 1.0), "run": run,
            "attack": False, "buy": None, "jump": False}


SIMS = {}


def trial(kind, dt, run):
    if kind not in SIMS:
        sim = SIMS[kind] = fresh()
        for _ in range(int(25 / 0.05)):                   # let traffic and parked cars spawn around the walker
            sim.update(0.05, {**inp(sim, False), "move": (0, 0)}, 1)
    sim = SIMS[kind]
    sim.walker.health = 1e9
    for _ in range(20):
        sim.update(0.05, {**inp(sim, False), "move": (0, 0)}, 1)
    cands = []
    if kind == "traffic":
        cands = list(sim.traffic.cars)
    elif kind == "parked":
        cands = [b for b in sim.bodies if b.parked_idx is not None and b is not sim.car]
    elif kind in ("wreck", "burning"):
        for b in sim.bodies:
            if b is not sim.car:
                b.health = -1.0
                if kind == "wreck":
                    b.burn = 99
        cands = [b for b in sim.bodies if b is not sim.car]
    if not cands:
        return None
    tgt = rng.choice(cands)
    wk = sim.walker
    ang = rng.uniform(0, 2 * math.pi)
    d0 = rng.uniform(6, 12)
    wk.x, wk.y = tgt.x + math.cos(ang) * d0, tgt.y + math.sin(ang) * d0
    wk.az = sim.w.ground_y(wk.x, wk.y)
    worst, frames = 0.0, 0
    t = 0.0
    while t < 4.0:
        aim = math.atan2(tgt.y - wk.y, tgt.x - wk.x) + (rng.uniform(-0.3, 0.3) if frames == 0 else 0)
        wk.h = aim
        if tgt not in sim.bodies and tgt not in sim.traffic.cars:
            break
        sim.update(dt, inp(sim, run), 1)
        t += dt
        frames += 1
        for v in vehicles_of(sim):
            hit = push_from_box(v, wk.x, wk.y, 1e-3)          # centre of the player inside any car box?
            if hit is not None and wk.z < 0.3:
                worst = max(worst, hit[2])
    return worst


for kind in ("parked", "traffic", "wreck", "burning"):
    for dt in (1 / 60, 0.05, 0.1, 0.2):
        for run in (False, True):
            bad = tot = 0
            mx = 0.0
            for _ in range(N):
                r = trial(kind, dt, run)
                if r is None:
                    continue
                tot += 1
                if r > 0.05:
                    bad += 1
                mx = max(mx, r)
            print(f"{kind:8s} dt={dt:.3f} {'run ' if run else 'walk'}  inside-box {bad}/{tot}  worst depth {mx:.2f} m", flush=True)
