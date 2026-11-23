"""The 10,000-type library.  Each type is (family, parameter dict); `scene_of(type)` builds it with the engine.
Families span lane counts, medians, controls, slips, flares, pockets, bike/bus lanes, skew angles, ring sizes, grade
separations, lane changes and 'dressing' packs of the 241 extra elements.  The types are a deterministic, stratified sample of
all valid parameter combinations (there are millions: every axis value below can be combined and overridden)."""
import itertools
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog as cat  # noqa: E402
from engine import Arm, Ring, Scene  # noqa: E402

DRESS = ["none", "urban", "green", "transit", "calm", "infra"]

AX = {
    "tee": dict(main=[1, 2, 3], minor=[1, 2], mmed=["none", "raised", "grass", "tram"], nmed=["none", "raised"], ctrl=["priority", "yield", "stop", "signal"],
                slip=[0, 1, 2, 3], flare=[0, 1], pocket=[0, 1], bike=[0, 1], bus=[0, 1], angle=[90, 70, 50], zebras=[0, 1], dress=DRESS),
    "cross": dict(main=[1, 2, 3], minor=[1, 2, 3], mmed=["none", "raised", "grass", "tram"], nmed=["none", "raised", "grass"], ctrl=["priority", "yield", "signal"],
                  slip=[0, 1, 2, 3, 4], flare=[0, 1, 2], pocket=[0, 1], pocket_minor=[0, 1], bike=[0, 1], bus=[0, 1], angle=[90, 80, 65], oneway=[0, 1], zebras=[0, 1],
                  corner_r=[4.0, 6.0, 9.0], dress=DRESS),
    "roundabout": dict(n=[3, 4, 5, 6], lanes=[1, 2, 3], approach=[1, 2, 3], entry=[1, 2, 3], center=["trees", "grass", "plain", "fountain", "monument"], splitter=[0, 2.5, 4.0],
                       slips=[0, 1, 2, 3, 4], zebra=[5.5, 9.0, 14.0], signal=[0, 1], bike=[0, 1], ro_extra=[0.0, 3.0, 6.0], offset=[0, 45, 30], dress=DRESS),
    "straight": dict(lanes=[1, 2, 3, 4], median=["none", "raised", "grass", "tram", "paint"], bike=[0, 1], bus=[0, 1], parking=[0, 1], oneway=[0, 1], crossing=[0, 5.5], signal=[0, 1],
                     trees=[0, 1], dress=DRESS),
    "grade": dict(kind=["over", "under"], angle=[90, 75, 60, 45, 30], ground_lanes=[1, 2, 3], ground_median=["none", "raised", "grass", "tram"], lanes=[1, 2, 3], median=[0.0, 2.0, 6.0],
                  oneway=[0, 1], h=[5.4, 6.4, 7.4], dress=DRESS),
    "lane_change": dict(a_in=[1, 2, 3, 4], b_in=[1, 2, 3, 4], med=["none", "raised", "grass"], at=[50.0, 70.0, 90.0], dress=DRESS),
    "star": dict(n=[3, 5, 6, 7], lanes=[(1,), (2, 1), (2, 1, 1), (2, 2, 1), (3, 1)], signal=[0, 1], median=["none", "raised"], flare=[0, 1], corner_r=[5.0, 7.0, 10.0], skew=[0, 1], dress=DRESS),
}


def valid(fam, p):
    if fam in ("tee", "cross"):
        if p["main"] == 1 and p["mmed"] not in ("none",):
            return False
        if p["mmed"] == "tram" and p["main"] < 2:
            return False
        if p["pocket"] and not (p["mmed"] in ("raised", "grass", "tram") and p["ctrl"] == "signal"):
            return False
        if p["flare"] and not (p["ctrl"] == "signal" and p["main"] >= 2):
            return False
        if p["bus"] and p["main"] < 2:
            return False
        if p["ctrl"] == "stop" and fam == "cross":
            return False
        if p["nmed"] != "none" and p["minor"] < 2:
            return False
        if fam == "tee" and p["ctrl"] == "signal" and p["slip"] and p["main"] < 2:
            return False
        if fam == "cross":
            if p["pocket_minor"] and not (p["nmed"] != "none" and p["ctrl"] == "signal"):
                return False
            if p["oneway"] and p["nmed"] != "none":
                return False
            if p["slip"] and p["main"] < 2 and p["minor"] < 2:
                return False
            if p["angle"] != 90 and p["slip"]:
                return False
            if p["flare"] == 2 and p["main"] < 2:
                return False
        if fam == "tee" and p["angle"] != 90 and (p["slip"] or p["mmed"] == "tram"):
            return False
        if p["slip"] and p["main"] == 1 and p["ctrl"] != "signal":
            pass
    if fam == "roundabout":
        if p["entry"] < p["approach"] and False:
            return False
        if p["lanes"] < p["entry"] and p["lanes"] < p["approach"]:
            return False
        if p["lanes"] == 1 and p["entry"] > 2:
            return False
        if p["n"] == 3 and p["offset"] not in (0, 45):
            return False
        if p["signal"] and p["lanes"] < 2:
            return False
        if p["splitter"] == 0 and p["approach"] > 1:
            return False
        if p["slips"] > p["n"]:
            return False
        if p["lanes"] >= 3 and p["ro_extra"] == 0.0 and p["n"] > 5:
            return False
    if fam == "straight":
        if p["oneway"] and p["median"] != "none":
            return False
        if p["median"] == "tram" and p["lanes"] < 2:
            return False
        if p["bus"] and p["lanes"] < 2:
            return False
        if p["parking"] and p["lanes"] > 3:
            return False
        if p["signal"] and not p["crossing"]:
            return False
        if p["median"] in ("grass", "raised") and p["lanes"] < 2:
            return False
    if fam == "grade":
        if p["oneway"] and p["median"] > 0:
            return False
        if p["ground_median"] == "tram" and p["ground_lanes"] < 2:
            return False
        if p["kind"] == "under" and p["h"] > 6.4:
            return False
        if p["angle"] <= 45 and p["ground_lanes"] > 2:
            return False
    if fam == "lane_change":
        if p["a_in"] == p["b_in"]:
            return False
    if fam == "star":
        if p["n"] > len(p["lanes"]) + 4:
            return False
    return True


def dressing(sc, kind, rnd):
    """Adds element packs: indices of arms that carry them are picked from the scene."""
    E = []
    narm = len(sc.arms)
    if kind == "none":
        return
    if kind == "urban":
        for i in range(narm):
            E += [dict(id="SG05_no_entry" if False else "SG04_speed_80", arm=i, d0=40.0, d1=41.0, step=100.0, side=-1),
                  dict(id="SF05_bin_green", arm=i, d0=20.0, d1=60.0, step=40.0, side=1), dict(id="SF01_bench_wood", arm=i, d0=30.0, d1=31.0, step=100.0, side=1, off=1.6),
                  dict(id="BP01_fixed_bollard", arm=i, d0=14.0, d1=34.0, step=5.0, side=-1, off=0.45)]
    elif kind == "green":
        for i in range(narm):
            E += [dict(id=rnd.choice(["VG10_shrub_green", "VG12_flower_bed_pink", "VG13_flower_bed_orange"]), arm=i, d0=14.0, d1=70.0, step=6.0, side=2, off=3.0),
                  dict(id="SF18_planter_box_wood", arm=i, d0=24.0, d1=25.0, step=100.0, side=-1, off=1.6)]
    elif kind == "transit":
        E += [dict(id="PT01_bus_stop_full", arm=min(1, narm - 1), d0=32.0, d1=33.0, step=100.0, side=-1),
              dict(id="MK10_red_bus_lane", arm=min(1, narm - 1), d0=14.0, d1=90.0), dict(id="PT06_bike_dock_station", arm=0, d0=28.0, d1=29.0, step=100.0, side=1, off=1.4)]
    elif kind == "calm":
        for i in range(narm):
            E += [dict(id=rnd.choice(["TC01_speed_hump_round", "TC02_speed_table_brick", "TC03_raised_crossing_red"]), arm=i, d0=44.0, d1=45.0, step=100.0, side=-1)]
    elif kind == "infra":
        for i in range(narm):
            E += [dict(id="UT01_manhole_round", arm=i, d0=26.0, d1=60.0, step=22.0, side=-1), dict(id="UT05_utility_pole", arm=i, d0=40.0, d1=41.0, step=100.0, side=1, off=3.5),
                  dict(id="BR12_pedestrian_rail", arm=i, d0=14.0, d1=34.0, side=-1, off=0.1)]
    sc.elements = E


def slip_arms(code, fam, narms):
    """slip code -> arm indices that carry a right-turn bypass."""
    table = {"tee": {0: [], 1: [0], 2: [0, 2], 3: [1]}, "cross": {0: [], 1: [0], 2: [0, 1], 3: [2, 3], 4: [0, 1, 2, 3]}}
    return table[fam][code]


def scene_of(t):
    fam, p, name = t["family"], t["params"], t["id"]
    rnd = random.Random(t["seed"])
    if fam == "tee":
        sc = cat.tee(name, main=p["main"], minor=p["minor"], main_median=p["mmed"], minor_median=p["nmed"], signal=(p["ctrl"] == "signal"),
                     sign=None if p["ctrl"] == "signal" else {"priority": "priority", "yield": "yield", "stop": "stop"}[p["ctrl"]], flare=p["flare"], pocket=p["pocket"],
                     angle=p["angle"], bike=bool(p["bike"]), bus=bool(p["bus"]), zebras=bool(p["zebras"]), seed=t["seed"], corner_r=5.0 if p["angle"] == 90 else 6.5)
        for k in slip_arms(p["slip"], "tee", 3):
            sc.arms[k].slip = {"R": 26.0}
    elif fam == "cross":
        sc = cat.cross(name, main=p["main"], minor=p["minor"], main_median=p["mmed"], minor_median=p["nmed"], signal=(p["ctrl"] == "signal"),
                       sign=None if p["ctrl"] == "signal" else p["ctrl"] if p["ctrl"] != "priority" else "priority", flare=p["flare"], pocket=p["pocket"], pocket_minor=p["pocket_minor"],
                       flare_minor=1 if p["flare"] and p["minor"] >= 2 and p["ctrl"] == "signal" else 0, angle=p["angle"], bike=bool(p["bike"]), bus=bool(p["bus"]),
                       zebras=bool(p["zebras"]), oneway=bool(p["oneway"]), corner_r=p["corner_r"], seed=t["seed"], slips=slip_arms(p["slip"], "cross", 4), med_w=5.0 if p["flare"] == 2 else None)
    elif fam == "roundabout":
        lanes = p["lanes"]
        sc = cat.roundabout(name, n=p["n"], lanes=lanes, entry=min(p["entry"], 3), approach_lanes=p["approach"], center=p["center"], splitter=p["splitter"],
                            slips=tuple(range(p["slips"])), zebra=p["zebra"], signal=bool(p["signal"]), bike=bool(p["bike"]), offset=p["offset"],
                            ro=18.0 + 4.0 * (lanes - 1) + p["ro_extra"], ri=10.0 + 2.5 * (lanes - 1) + p["ro_extra"] * 0.6, seed=t["seed"])
    elif fam == "straight":
        sc = cat.straight(name, lanes=p["lanes"], median="none" if p["median"] == "paint" else p["median"], paint=p["median"] == "paint", med_w=2.4 if p["median"] == "paint" else None,
                          bike=bool(p["bike"]), bus=bool(p["bus"]), parking=bool(p["parking"]), oneway=bool(p["oneway"]), trees=bool(p["trees"]),
                          crossing=p["crossing"] or None, signal=bool(p["signal"]), seed=t["seed"])
    elif fam == "grade":
        sc = cat.grade(name, p["kind"], angle=p["angle"], ground_lanes=p["ground_lanes"], ground_median=p["ground_median"], lanes=p["lanes"], median=p["median"], h=p["h"], oneway=bool(p["oneway"]))
        sc.seed = t["seed"]
    elif fam == "lane_change":
        sc = cat.lane_change(name, p["a_in"], p["b_in"], at=p["at"], med=p["med"], seed=t["seed"])
    elif fam == "star":
        n = p["n"]
        angles = None
        if p["skew"]:
            angles = [(i * 360.0 / n) + (14 if i % 2 else -9) for i in range(n)]
        sc = cat.star(name, n=n, lanes=p["lanes"], signal=bool(p["signal"]), median=p["median"], flare=p["flare"], angles=angles, corner_r=p["corner_r"], seed=t["seed"])
    dressing(sc, p["dress"], rnd)
    return sc


def generate(total=10000, seed=242):
    rnd = random.Random(seed)
    pools = {}
    for fam, ax in AX.items():
        keys = list(ax)
        vals = [ax[k] for k in keys]
        allv = []
        for combo in itertools.product(*vals):
            p = dict(zip(keys, combo))
            if valid(fam, p):
                allv.append(p)
        pools[fam] = allv
    share = {"tee": 0.17, "cross": 0.27, "roundabout": 0.17, "straight": 0.09, "grade": 0.13, "lane_change": 0.05, "star": 0.12}
    out, spill = [], 0
    for fam, w in share.items():
        want = int(total * w)
        allv = pools[fam]
        rnd.shuffle(allv)
        take = allv[:want]
        out += [(fam, p) for p in take]
    # top up from the biggest pools until the total is reached
    rest = [(f, p) for f, v in pools.items() for p in v[int(total * share[f]):]]
    rnd.shuffle(rest)
    out += rest[:max(0, total - len(out))]
    out = out[:total]
    rnd.shuffle(out)
    types = []
    for i, (fam, p) in enumerate(out):
        types.append(dict(id=f"{fam}_{i + 1:05d}", family=fam, seed=1000 + i, params={k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()}))
    return types, {f: len(v) for f, v in pools.items()}


if __name__ == "__main__":
    types, pools = generate()
    print("valid combinations per family:", pools, "sum", sum(pools.values()))
    print("types:", len(types))
    json.dump(types, open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/types_10000.json", "w"))
