"""Crossing audit: where do two drivable ways cross without meeting, and does the 3D make sense there?

For every pair of drivable edges of a built world whose centrelines cross away from a shared node:
  * over  - one is a bridge: clearance from the road below to the deck underside (deck surface - 0.9 m slab);
            under 4.0 m the lower road drives into the bridge,
  * flat  - neither is a bridge: both are drawn on the ground through each other (an underpass that was never cut,
            or a missing bridge tag),
  * decks - both are bridges: their decks should differ by a slab + headroom, or be the same height (same level).

    python tools/crossing_audit.py data/cache/world"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import world as world_mod  # noqa: E402


def _hit(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0.02 < t < 0.98 and 0.02 < u < 0.98:
        return a[0] + t * r[0], a[1] + t * r[1]
    return None


def audit(w):
    E = [(i, e) for i, e in enumerate(w.edges) if e["drive"] and len(e["pts"]) >= 2
         and all(abs(x) < w.hx - 40 and abs(y) < w.hy - 40 for x, y in e["pts"])]
    grid = {}
    for i, e in E:
        for k, (a, b) in enumerate(zip(e["pts"], e["pts"][1:])):
            for cx in range(int(min(a[0], b[0]) // 32), int(max(a[0], b[0]) // 32) + 1):
                for cy in range(int(min(a[1], b[1]) // 32), int(max(a[1], b[1]) // 32) + 1):
                    grid.setdefault((cx, cy), []).append((i, k))
    seen, rows = set(), []
    for cell, segs in grid.items():
        for n1, (i, k) in enumerate(segs):
            for j, m in segs[n1 + 1:]:
                if i == j or (min(i, j), max(i, j)) in seen:
                    continue
                ei, ej = w.edges[i], w.edges[j]
                if {ei["a"], ei["b"]} & {ej["a"], ej["b"]}:
                    continue
                p = _hit(ei["pts"][k], ei["pts"][k + 1], ej["pts"][m], ej["pts"][m + 1])
                if p is None:
                    continue
                seen.add((min(i, j), max(i, j)))
                bi, bj = ei["bridge"], ej["bridge"]
                g = w.ground_y(*p)
                d = w.deck_h(*p)
                if bi != bj:
                    kind = "over"
                    clear = (d - 0.9 - g) if d is not None else 0.0
                elif not bi:
                    kind, clear = "flat", 0.0
                else:
                    kind, clear = "decks", 0.0
                rows.append({"kind": kind, "x": round(p[0], 1), "y": round(p[1], 1), "clear": clear,
                             "cls": (ei["cls"], ej["cls"])})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    a = ap.parse_args()
    w = world_mod.World(a.world)
    rows = audit(w)
    over = [r for r in rows if r["kind"] == "over"]
    low = [r for r in over if r["clear"] < 4.0]
    flat = [r for r in rows if r["kind"] == "flat"]
    print(f"[crossings] {len(rows)} drivable ways crossing without a junction: {len(over)} bridge over road, "
          f"{len(flat)} both on the ground, {len(rows) - len(over) - len(flat)} bridge over bridge")
    print(f"[crossings] bridge over road with less than 4.0 m headroom: {len(low)}   "
          f"(worst {min((r['clear'] for r in over), default=0):.1f} m)")
    for r in sorted(low, key=lambda r: r["clear"])[:6]:
        print(f"   low   ({r['x']}, {r['y']}) {r['cls']} clearance {r['clear']:.1f} m")
    for r in flat[:6]:
        print(f"   flat  ({r['x']}, {r['y']}) {r['cls']}")


if __name__ == "__main__":
    main()
