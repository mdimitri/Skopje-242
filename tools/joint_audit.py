"""Joint audit: how sharply do bridge / overpass decks meet the roads at their ends?

For every deck of a built world: the height step between the deck end and the road it joins, the grade break at
the joint (deck grade over its first 6 m minus the road grade over the 6 m beyond the end), the worst grade break
inside the deck (between consecutive 3 m pieces) and the steepest grade.  A vehicle at street speed takes a grade
break of more than ~6 % over one wheelbase as a jolt / jump.

    python tools/joint_audit.py data/cache/world [--limit 0.06]"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import world as world_mod  # noqa: E402


def _at(d, s):
    """Deck centreline point and height at distance s."""
    cum, pts, h = d["cum"], d["pts"], d["h"]
    s = max(0.0, min(cum[-1], s))
    k = 0
    while k < len(cum) - 2 and cum[k + 1] < s:
        k += 1
    t = (s - cum[k]) / ((cum[k + 1] - cum[k]) or 1.0)
    (ax, ay), (bx, by) = pts[k], pts[k + 1]
    return ax + (bx - ax) * t, ay + (by - ay) * t, h[k] + (h[k + 1] - h[k]) * t


def audit(w, limit):
    rows = []
    ends = [p for d in w.decks for p in (d["pts"][0], d["pts"][-1])]
    for di, d in enumerate(w.decks):
        L = d["cum"][-1]
        if L < 8 or d["hw"] < 3.0 or any(abs(x) > w.hx - 40 or abs(y) > w.hy - 40 for x, y in d["pts"]):
            continue                                       # roads only (footbridges may have steps), inside the box
        g_in = []
        for k in range(len(d["h"]) - 1):
            ds = d["cum"][k + 1] - d["cum"][k]
            if ds > 0.5:
                g_in.append((d["h"][k + 1] - d["h"][k]) / ds)
        brk_in = max((abs(b - a) for a, b in zip(g_in, g_in[1:])), default=0.0)
        steep = max((abs(g) for g in g_in), default=0.0)
        for end in (0, 1):
            s0, sgn = (0.0, 1.0) if end == 0 else (L, -1.0)
            x0, y0, h0 = _at(d, s0)
            if sum(1 for q in ends if math.hypot(q[0] - x0, q[1] - y0) < 0.6) > 1:
                continue                                   # a joint with the next piece of the bridge, not a road
            x1, y1, h1 = _at(d, s0 + sgn * 6.0)
            ux, uy = (x0 - x1) / 6.0, (y0 - y1) / 6.0          # outwards, along the road beyond the end
            g_deck = (h0 - h1) / 6.0                             # rising outwards > 0
            gr0 = w.ground_y(x0, y0)
            gr1 = w.ground_y(x0 + ux * 6.0, y0 + uy * 6.0)
            g_road = (gr1 - gr0) / 6.0
            rows.append({"deck": di, "end": end, "x": round(x0, 1), "y": round(y0, 1), "step": h0 - gr0,
                         "brk": abs(g_road - g_deck), "brk_in": brk_in, "steep": steep})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--limit", type=float, default=0.06)
    a = ap.parse_args()
    w = world_mod.World(a.world)
    rows = audit(w, a.limit)
    n = len(rows)
    over = [r for r in rows if r["brk"] > a.limit]
    step = [r for r in rows if abs(r["step"]) > 0.15]
    decks = {r["deck"]: r for r in rows}
    inner = [r for r in decks.values() if r["brk_in"] > a.limit]
    print(f"[joints] {len(decks)} decks, {n} ends")
    print(f"[joints] ends with a grade break > {a.limit:.0%}: {len(over)}   worst {max((r['brk'] for r in rows), default=0):.1%}")
    print(f"[joints] ends with a height step > 15 cm: {len(step)}   worst {max((abs(r['step']) for r in rows), default=0):.2f} m")
    print(f"[joints] decks with an inner grade break > {a.limit:.0%} (3 m pieces): {len(inner)}   worst "
          f"{max((r['brk_in'] for r in decks.values()), default=0):.1%}")
    print(f"[joints] steepest deck grade {max((r['steep'] for r in decks.values()), default=0):.1%}; decks over 10 %: "
          f"{sum(1 for r in decks.values() if r['steep'] > 0.10)}")
    for r in sorted(rows, key=lambda r: -r["brk"])[:8]:
        print(f"   deck {r['deck']:4d} end {r['end']} at ({r['x']}, {r['y']}): break {r['brk']:.1%}, step {r['step']:+.2f} m, "
              f"inner break {r['brk_in']:.1%}, steepest {r['steep']:.1%}")


if __name__ == "__main__":
    main()
