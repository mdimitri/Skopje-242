"""Headless traffic study on a built world (round 21): drives the game's own Sim around the centre of a district and measures
how traffic flows.  The idle player is hidden from the AI so it does not stand in the road as an obstacle.
Usage: python3 tools/traffic_study.py <world_dir> <out.jsonl> [series ...]      series: hood density hour aggro ems (default: all)
One JSON line per run: speed / limit, share of standing car-time and its causes, ghost time, overlaps, standing hot spots per
30 m cell and per edge, per-class and per-vehicle-type speeds, ambulance calls (served / aborted)."""
import collections
import json
import math
import multiprocessing as mp
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

HOODS = {"Центар": (186, 332), "Дебар Маало": (-657, -473), "Карпош": (-2132, 157), "Аеродром": (3038, 1451), "Кисела Вода": (987, 2095),
         "Чаир": (1461, -1814), "Гази Баба": (1426, -942), "Бутел": (1770, -2833), "Железара": (2548, -1860), "Автокоманда": (3066, -732),
         "Влае": (-4232, -1290), "Ново Лисиче": (4040, 1430), "Расадник": (1422, 2419), "Цементара": (2250, 2775), "Ѓорче Петров": (-3527, -2039),
         "Водно": (-1146, 1110), "Несреди (рид)": (-4085, -270), "Бардовци (село)": (-4293, -3278)}
RADIUS = 450.0


def run(world, name, cx, cy, cars=90, hour=11.0, aggro=1, secs=150, warm=25, patients=False, seed=1):
    import signals
    import vehicles
    from actors import Sim
    sim = Sim(world, random.Random(seed), cars, 10)
    crashes = collections.Counter()
    sim.ev = lambda _k, **kw: crashes.update([str(kw.get("kind"))]) if _k == "crash" and getattr(kw.get("body"), "service", False) else None
    lights = signals.Signals(world)
    sim.traffic.signals = sim.lights = lights
    sim.clock.hour, sim.aggro = hour, aggro
    sim.teleport(cx, cy)
    sim.exit_car()
    inp = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 0.0), "run": False, "attack": False, "buy": None, "jump": False}
    dt, T = 0.05, sim.traffic
    upd = T.update
    T.update = lambda d, fx, fy, bodies, peds, walker=None: upd(d, fx, fy, bodies, peds, None)
    ratios, ncars, cause = [], [], collections.Counter()
    hot, hot_edge, ovpos = collections.Counter(), collections.Counter(), collections.Counter()
    by_cls, by_style = collections.defaultdict(lambda: [0.0, 0.0, 0]), collections.defaultdict(lambda: [0.0, 0.0, 0])
    stand, ghost_s, overlaps, real_overlaps, max_stand = collections.defaultdict(float), 0.0, 0, 0, 0.0
    seen, calls = {}, []
    for k in range(int((warm + secs) / dt)):
        lights.update(dt)
        sim.update(dt, inp, 1)
        cur = {id(j): j for j in sim.services.jobs}
        for i, j in cur.items():
            rec = seen.setdefault(i, {"t0": k * dt, "arr": None, "stuck": 0.0})
            if rec["arr"] is None and j.state in ("work", "treat"):
                rec["arr"] = k * dt - rec["t0"]
            if j.body is not None and j.body.speed < 0.5 and j.state == "drive":
                rec["stuck"] += dt
        for i in [i for i in seen if i not in cur]:
            r = seen.pop(i)
            calls.append((round(r["t0"], 1), r["arr"], round(r["stuck"], 1), "served" if r["arr"] is not None else "aborted"))
        if k * dt < warm:
            continue
        if patients and k % int(20 / dt) == 0 and k * dt >= warm + 10:      # a new dead pedestrian every 20 s, 80-300 m away
            for p in sim.peds.list:
                if p.mode not in ("dead", "air") and 80 < math.hypot(p.x - cx, p.y - cy) < 300:
                    p.mode, p.t = "dead", 80
                    break
        if k % 2:
            continue
        cs = [c for c in T.cars if math.hypot(c.x - cx, c.y - cy) < RADIUS]
        ncars.append(len(cs))
        for c in cs:
            e = world.edges[c.e]
            ratios.append(min(1.5, c.v / max(e["speed"], 1)))
            for tab, key in ((by_cls, e["cls"]), (by_style, vehicles.STYLE[c.kind])):
                tab[key][0] += c.v
                tab[key][1] += e["speed"]
                tab[key][2] += 1
            ghost_s += 2 * dt if c.ghost > 0 else 0.0
            if c.v < 0.5:
                end = (e["len"] - c.s) if c.d == 1 else c.s
                if vehicles.STYLE[c.kind] == "bus":
                    why = "bus stop/kerb"
                elif lights.stop_for(c.e, 1 if c.d == 1 else 0) and end < 50:
                    why = "red light queue"
                elif end < 20:
                    why = "junction conflict"
                else:
                    why = "mid-block (queue/obstacle)"
                cause[why] += 2 * dt
                stand[id(c)] += 2 * dt
                hot[(int(c.x // 30), int(c.y // 30))] += 2 * dt
                hot_edge[c.e] += 2 * dt
                max_stand = max(max_stand, stand[id(c)])
            else:
                stand[id(c)] = 0.0
        for ii, a in enumerate(cs):
            for b in cs[ii + 1:]:
                if math.hypot(a.x - b.x, a.y - b.y) < min(vehicles.HALF_W[a.kind], vehicles.HALF_W[b.kind]) * 1.2:
                    overlaps += 1
                    if a.ghost <= 0 and b.ghost <= 0:
                        real_overlaps += 1
                        ovpos[(int(a.x // 30), int(a.y // 30))] += 1
    for r in seen.values():
        calls.append((round(r["t0"], 1), r["arr"], round(r["stuck"], 1), "open"))
    return dict(name=name, cars=cars, hour=hour, aggro=aggro, mean_cars=sum(ncars) / max(1, len(ncars)), mean_ratio=sum(ratios) / max(1, len(ratios)),
                frac_stopped=sum(1 for r in ratios if r < 0.05) / max(1, len(ratios)), max_stand=max_stand, ghost_s=ghost_s, overlaps=overlaps,
                real_overlaps=real_overlaps, cause=dict(cause), hot=hot.most_common(40), hot_edge=hot_edge.most_common(25), ovpos=ovpos.most_common(15),
                cls={k: tuple(v) for k, v in by_cls.items()}, style={k: tuple(v) for k, v in by_style.items()}, calls=calls, crashes=dict(crashes))


_WORLD = {}


def _job(args):
    path, kw = args
    from world import World
    if path not in _WORLD:
        _WORLD[path] = World(path, lambda f, note="": None)
    return run(_WORLD[path], **kw)


def scenarios(only):
    out = []
    c = HOODS["Центар"]
    for n, (x, y) in HOODS.items():
        out.append(("hood", dict(name=n, cx=x, cy=y)))
        out.append(("ems", dict(name=n + " +ambulances", cx=x, cy=y, secs=240, patients=True)))
    for cars in (20, 45, 90, 150, 220, 320):
        out.append(("density", dict(name=f"Центар {cars} cars", cx=c[0], cy=c[1], cars=cars)))
    for h in (3, 6, 8, 12, 17, 22):
        out.append(("hour", dict(name=f"Центар {h}h", cx=c[0], cy=c[1], hour=float(h))))
    for ag in range(4):
        out.append(("aggro", dict(name=f"Центар mood {ag}", cx=c[0], cy=c[1], cars=120, aggro=ag)))
    return [(s, kw) for s, kw in out if not only or s in only]


if __name__ == "__main__":
    world_dir, out = sys.argv[1], sys.argv[2]
    todo = scenarios(set(sys.argv[3:]))
    with mp.Pool(4) as pool, open(out, "w", encoding="utf-8") as f:
        for (series, _kw), r in zip(todo, pool.imap(_job, [(world_dir, kw) for _s, kw in todo])):
            r["series"] = series
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(series, r["name"], f"{r['mean_ratio']:.2f}", flush=True)
