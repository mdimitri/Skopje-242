"""Bake the police stations' and army barracks' layout (fences, gates, bunkers, parked vehicles) into a built world:
writes <world>/compounds.json, which the game loads instead of placing them itself, so every player has the same layout.

    python tools/bake_compounds.py [--world data/cache/world] [--src data/osm]
"""
import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=os.path.join(ROOT, "data", "cache", "world"))
    ap.add_argument("--src", default=os.path.join(ROOT, "data", "osm"))
    a = ap.parse_args()
    import world as world_mod, actors, compounds
    out = os.path.join(a.world, compounds.BAKED)
    if os.path.exists(out):
        os.remove(out)                                   # place them again from scratch
    w = world_mod.World(a.world)
    sim = actors.Sim(w, random.Random(1), 0, 0)
    pois_f = os.path.join(a.src, "map_pois.json")
    pois = json.load(open(pois_f, encoding="utf-8")) if os.path.exists(pois_f) else []
    cp = compounds.Compounds(sim, [p for p in pois if isinstance(p, list) and len(p) == 4], a.src)
    print(f"[bake] {len(cp.list)} compounds -> {out}")


if __name__ == "__main__":
    main()
