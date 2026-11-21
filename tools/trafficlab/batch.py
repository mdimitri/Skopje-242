"""Seeded stochastic batches: every variant x every seed is one run of LabSim in a fresh worker process (fresh
interpreter, PYTHONHASHSEED=0, the same random streams for the same seed; repeats still differ a little because the game
iterates some sets of cars in memory-address order), then statistics per
variant (mean, 95 % confidence interval) and a Welch t-test of every variant against the first one (the baseline).

Spec (JSON, also what the UI's Batch tab builds):
  {"world": dir, "osm": dir, "scenario": {...}, "base": {settings}, "seeds": 6, "seed0": 1, "workers": 0,
   "variants": [{"name": "A game default", "settings": {}}, {"name": "B patient", "settings": {"wait_scale": 2.0}}],
   "sweep": {"key": "cycle", "from": 40, "to": 90, "steps": 6}}           (optional: adds one variant per value)
Command line:  python tools/traffic_lab.py --batch spec.json [--out dir]"""
import json
import math
import multiprocessing as mp
import os
import time

from . import OUT, params

HEADLINE = [  # key, label, unit, better ("hi" / "lo"), group
    ("throughput_h", "Junction throughput", "veh/h", "hi", "Efficiency"),
    ("veh_km_h", "Vehicle-km per hour", "veh-km/h", "hi", "Efficiency"),
    ("delay_s_km", "Delay per km", "s/km", "lo", "Efficiency"),
    ("delay_share", "Time lost (share)", "", "lo", "Efficiency"),
    ("stopped_share", "Standing (share)", "", "lo", "Efficiency"),
    ("stuck4_share", "Standing > 4 s (share)", "", "lo", "Efficiency"),
    ("stuck4_nored_share", "Standing > 4 s, not at red", "", "lo", "Efficiency"),
    ("jams", "Jams (> 25 s, not at red)", "", "lo", "Efficiency"),
    ("gridlock_s", "Gridlock time", "s", "lo", "Efficiency"),
    ("trip_delay", "Delay per trip", "s", "lo", "Efficiency"),
    ("speed_kmh", "Space-mean speed", "km/h", "hi", "Speed"),
    ("speed_ratio", "Speed / limit", "", "hi", "Speed"),
    ("bus_kmh", "Bus speed", "km/h", "hi", "Speed"),
    ("ems_response", "Emergency response", "s", "lo", "Speed"),
    ("collisions", "Collisions", "", "lo", "Safety"),
    ("collisions_deep", "Collisions > 0.3 m", "", "lo", "Safety"),
    ("near_misses", "Near misses (TTC < 1.5 s)", "", "lo", "Safety"),
    ("near_serious", "Serious near misses (TTC < 0.75 s)", "", "lo", "Safety"),
    ("ped_conflicts", "Pedestrian conflicts", "", "lo", "Safety"),
    ("redruns", "Red-light runs", "", "lo", "Safety"),
    ("game_crashes", "Game crash events", "", "lo", "Safety"),
    ("ghost_share", "Ghosting (share)", "", "lo", "Safety"),
    ("conflicts_per_1000km", "Conflicts per 1000 veh-km", "", "lo", "Safety"),
    ("score_efficiency", "Efficiency score", "/100", "hi", "Scores"),
    ("score_safety", "Safety score", "/100", "hi", "Scores"),
    ("score_speed", "Speed score", "/100", "hi", "Scores"),
]


# ------------------------------------------------------------------ statistics (no scipy needed)
def _betacf(a, b, x):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(c) > 1e-30 else 1e30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c if abs(c) > 1e-30 else 1e30
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-12:
            break
    return h


def _ibeta(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t, df):
    return _ibeta(df / 2.0, 0.5, df / (df + t * t)) if df > 0 else 1.0


def t_crit(df, alpha=0.05):
    lo, hi = 0.0, 50.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if t_two_sided_p(mid, df) > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def stats(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if not n:
        return {"n": 0, "mean": None, "sd": None, "ci": None}
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    ci = t_crit(n - 1) * sd / math.sqrt(n) if n > 1 else 0.0
    return {"n": n, "mean": m, "sd": sd, "ci": ci, "min": min(xs), "max": max(xs)}


def welch(a, b):
    """(difference b - a, two-sided p) of two samples."""
    a, b = [x for x in a if x is not None], [x for x in b if x is not None]
    if len(a) < 2 or len(b) < 2:
        return None, None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1) / len(a)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1) / len(b)
    if va + vb <= 0:
        return mb - ma, (1.0 if mb == ma else 0.0)
    t = (mb - ma) / math.sqrt(va + vb)
    df = (va + vb) ** 2 / ((va * va) / (len(a) - 1) + (vb * vb) / (len(b) - 1))
    return mb - ma, t_two_sided_p(abs(t), df)


# ------------------------------------------------------------------ memory / workers
def free_memory():
    """Bytes of physical memory available now (Windows and Linux), or None."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullAvailPhys
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:  # noqa: BLE001
        return None
    return None


def worker_estimate(world_dir):
    """Rough memory of one worker: the loaded world (~1.3 x its pickles) plus the simulation."""
    pk = sum(os.path.getsize(os.path.join(world_dir, f)) for f in os.listdir(world_dir) if f.endswith(".pkl"))
    return int(pk * 1.3 + 250e6)


def auto_workers(world_dir, want=0, jobs=1):
    cpu = max(1, (os.cpu_count() or 2) - 1)
    n = want if want > 0 else cpu
    free = free_memory()
    if free:
        n = min(n, max(1, int(free * 0.8 // worker_estimate(world_dir))))
    return max(1, min(n, jobs))


# ------------------------------------------------------------------ the runs
_W = {}


def _job(args):
    world_dir, osm_dir, settings, scenario, seed, variant = args
    import trafficlab  # noqa: F401  (sys.path)
    from world import World
    from . import core
    if world_dir not in _W:
        _W[world_dir] = World(world_dir)
    t0 = time.time()
    lab = core.LabSim(_W[world_dir], osm_dir, settings, scenario, seed)
    try:
        r = lab.run()
    finally:
        lab.close()
    r.update(variant=variant, seed=seed, wall=round(time.time() - t0, 1), tile=scenario.get("tile", 0), area=[round(v) for v in lab.area])
    return r


def expand(spec):
    base = dict(params.defaults())
    base.update(spec.get("base") or {})
    variants = [dict(v) for v in (spec.get("variants") or [{"name": "A current settings", "settings": {}}])]
    sw = spec.get("sweep")
    if sw:
        p = params.BY_KEY[sw["key"]]
        n = max(2, int(sw.get("steps", 5)))
        for i in range(n):
            v = params.clamp(p, sw["from"] + (sw["to"] - sw["from"]) * i / (n - 1))
            variants.append({"name": f"{p.label} = {v:g}" if not isinstance(v, bool) else f"{p.label} = {v}", "settings": {sw["key"]: v}})
    seeds = int(spec.get("seeds") or base["seeds"])
    s0 = int(spec.get("seed0") if spec.get("seed0") is not None else base["seed0"])
    jobs = []
    from . import core
    ntiles = len(core.tiles(spec["scenario"]["area"]))
    for v in variants:
        st = dict(base)
        st.update(v.get("settings") or {})
        for k in range(seeds):
            for ti in range(ntiles):
                jobs.append((spec["world"], spec["osm"], st, dict(spec["scenario"], tile=ti), s0 + k, v["name"]))
    return variants, jobs


SUM = ("throughput_h", "veh_km_h", "jams", "gridlock_s", "trips", "despawned", "collisions", "collisions_ghost", "collisions_deep",
       "near_misses", "near_serious", "ped_conflicts", "redruns", "game_crashes", "ems_calls", "ems_arrived", "cars_mean")
WEIGHTED = ("speed_ratio", "delay_share", "stopped_share", "stuck4_share", "stuck4_nored_share", "ghost_share", "xing_closed_share",
            "trip_delay", "ems_stuck")
CONCAT = ("junctions", "fd", "heat_stand", "heat_speed", "heat_conf", "jam_list", "collision_list", "near_list", "redrun_list")


def merge_tiles(results):
    """One result per (variant, seed): the tiles of a big study rectangle added up (counts summed, shares weighted by
    vehicles in each tile, speed = vehicle-km / vehicle-hours).  Each merged result keeps its per-tile rows in "tiles"."""
    groups = {}
    for r in results:
        groups.setdefault((r["variant"], r["seed"]), []).append(r)
    out = []
    for (variant, seed), rs in groups.items():
        if len(rs) == 1 and "tile" not in rs[0]:
            out.append(rs[0])
            continue
        rs.sort(key=lambda r: r.get("tile", 0))
        m = {"variant": variant, "seed": seed, "seconds": rs[0]["seconds"], "wall": sum(r.get("wall", 0) for r in rs)}
        wsum = sum(r["cars_mean"] for r in rs) or 1.0
        for k in SUM:
            m[k] = sum(r.get(k) or 0 for r in rs)
        for k in WEIGHTED:
            m[k] = round(sum((r.get(k) or 0) * r["cars_mean"] for r in rs) / wsum, 4)
        vh = sum(r["cars_mean"] for r in rs) or 1e-6                     # vehicle-hours per hour
        m["speed_kmh"] = round(m["veh_km_h"] / vh, 2)
        m["delay_s_km"] = round(m["delay_share"] * vh * 3600 / max(m["veh_km_h"], 1e-6), 1)
        arr = [(r["ems_response"], r["ems_arrived"]) for r in rs if r.get("ems_response") is not None]
        m["ems_response"] = round(sum(a * n for a, n in arr) / max(1, sum(n for _a, n in arr)), 1) if arr else None
        m["bus_kmh"] = round(sum(r["bus_kmh"] for r in rs if r.get("bus_kmh")) / max(1, sum(1 for r in rs if r.get("bus_kmh"))), 1)
        km = m["veh_km_h"] * m["seconds"] / 3600
        m["conflicts_per_1000km"] = round((m["collisions"] + m["near_misses"]) / max(km, 1e-6) * 1000, 1)
        for k in CONCAT:
            m[k] = [x for r in rs for x in r.get(k, ())]
        m["junctions"].sort(key=lambda j: -j["veh_h"])
        hist = [0] * 30
        for r in rs:
            for i, n in enumerate(r.get("speed_hist", ())):
                hist[i] += n
        m["speed_hist"] = hist
        ser = {}
        for r in rs:
            for row in r.get("series", ()):
                a = ser.setdefault(row[0], [row[0], 0, 0.0, 0.0, 0, 0, 0, 0])
                a[1] += row[1]
                a[2] += row[2] * row[1]
                a[3] += row[3] * row[1]
                a[4] += row[4]
                a[5] += row[5]
                a[6] += row[6]
        m["series"] = [(t, a[1], round(a[2] / max(1, a[1]), 2), round(a[3] / max(1, a[1]), 3), a[4], a[5], a[6]) for t, a in sorted(ser.items())]
        m["los_mix"] = {}
        for j in m["junctions"]:
            m["los_mix"][j["los"]] = m["los_mix"].get(j["los"], 0) + 1
        m["score_efficiency"] = round(100.0 * max(0.0, 1.0 - m["delay_share"]), 1)
        m["score_safety"] = round(100.0 / (1.0 + m["conflicts_per_1000km"] / 50.0), 1)
        m["score_speed"] = round(100.0 * min(1.0, m["speed_ratio"]), 1)
        m["tiles"] = [{"tile": r.get("tile", 0), "area": r.get("area"), "speed_kmh": r["speed_kmh"], "stuck4_share": r["stuck4_share"],
                       "jams": r["jams"], "collisions": r["collisions"], "near_misses": r["near_misses"], "cars_mean": r["cars_mean"],
                       "delay_s_km": r["delay_s_km"], "score_efficiency": r["score_efficiency"], "score_safety": r["score_safety"],
                       "score_speed": r["score_speed"]} for r in rs]
        out.append(m)
    return out


def pool_map(jobs, n, on_result, cancel=None):
    """Runs jobs (see _job) on n fresh worker processes (one process per run: PYTHONHASHSEED=0 and nothing left over
    from an earlier run).  on_result(r) is called here as runs finish."""
    os.environ["PYTHONHASHSEED"] = "0"                        # string-keyed sets iterate in the same order in every run
    ctx = mp.get_context("spawn")
    with ctx.Pool(n, maxtasksperchild=1) as pool:
        for r in pool.imap_unordered(_job, jobs):
            on_result(r)
            if cancel is not None and cancel():
                pool.terminate()
                return False
    return True


def run(spec, out_dir=None, progress=None, cancel=None):
    """Runs the batch; writes runs.jsonl, summary.json and report.html into out_dir.  Returns (summary, out_dir).
    progress(done, total, text) is called from this thread; cancel() -> True stops after the running jobs."""
    variants, jobs = expand(spec)
    out_dir = out_dir or os.path.join(OUT, "batches", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    n = auto_workers(spec["world"], int(spec.get("workers") or 0), len(jobs))
    results = []
    t0 = time.time()
    if progress:
        progress(0, len(jobs), f"{len(jobs)} runs on {n} worker processes")
    with open(os.path.join(out_dir, "runs.jsonl"), "w", encoding="utf-8") as f:
        def got(r):
            results.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if progress:
                el = time.time() - t0
                eta = el / len(results) * (len(jobs) - len(results))
                progress(len(results), len(jobs), f"{r['variant']} seed {r['seed']}: {r['speed_kmh']} km/h, "
                                                  f"{r['collisions']} collisions  (ETA {eta / 60:.1f} min)")
        pool_map(jobs, n, got, cancel)
    results = merge_tiles(results)
    summary = summarize(variants, results, spec)
    summary["tiles"] = len(core_tiles(spec))
    summary["wall_s"] = round(time.time() - t0)
    summary["workers"] = n
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False)
    from . import report
    report.write(summary, results, spec, os.path.join(out_dir, "report.html"))
    return summary, out_dir


def core_tiles(spec):
    from . import core
    return core.tiles(spec["scenario"]["area"])


def summarize(variants, results, spec):
    by = {v["name"]: [r for r in results if r["variant"] == v["name"]] for v in variants}
    base_name = variants[0]["name"]
    out = {"variants": [], "baseline": base_name, "seeds": int(spec.get("seeds") or 0)}
    for v in variants:
        rs = by[v["name"]]
        row = {"name": v["name"], "settings": v.get("settings") or {}, "runs": len(rs), "metrics": {}}
        for key, _label, _unit, better, _g in HEADLINE:
            s = stats([r.get(key) for r in rs])
            d, p = welch([r.get(key) for r in by[base_name]], [r.get(key) for r in rs]) if v["name"] != base_name else (None, None)
            s.update(diff=d, p=p, better=None if d is None or p is None or p > 0.05 or d == 0 else ((d > 0) == (better == "hi")))
            row["metrics"][key] = s
        out["variants"].append(row)
    return out
