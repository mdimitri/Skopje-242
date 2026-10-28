"""Terrain poking through road polygons: samples inside every asphalt triangle of the road mesh (centroid, edge midpoints and
the points half way to the corners) and counts those where the terrain surface is higher than the road face there.
Usage: python3 tools/terrain_poke_audit.py <world_dir> [--max-chunks N]   (prints the totals and the worst places)"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from sidewalk_audit import is_asphalt  # noqa: E402


def audit(world, limit=None):
    th = np.vectorize(world.th)
    bad, tot, worst = 0, 0, []
    for n_, (key, ch) in enumerate(world.chunks.items()):
        if limit and n_ >= limit:
            break
        if not ch or 3 not in ch["m"]:
            continue
        off, n = ch["m"][3]
        pos, _uv, col = world.mesh_arrays(off, n)
        T = np.array(pos).reshape(-1, 3, 3)
        C = np.array(col).reshape(-1, 3, 4)[:, 0, :3]
        T = T[is_asphalt(C)]
        if not len(T):
            continue
        a, b, c = T[:, 0], T[:, 1], T[:, 2]
        pts = [(a + b + c) / 3, (a + b) / 2, (b + c) / 2, (a + c) / 2, (a * 2 + b + c) / 4, (b * 2 + a + c) / 4, (c * 2 + a + b) / 4]
        for p in pts:
            g = th(p[:, 0], p[:, 2])
            poke = g > p[:, 1] - 0.01
            tot += len(p)
            bad += int(poke.sum())
            for i in np.nonzero(poke)[0][:3]:
                worst.append((float(g[i] - p[i, 1]), round(float(p[i, 0])), round(float(p[i, 2]))))
    worst.sort(reverse=True)
    return bad, tot, worst[:12]


if __name__ == "__main__":
    from world import World
    w = World(sys.argv[1], lambda f, note="": None)
    lim = int(sys.argv[sys.argv.index("--max-chunks") + 1]) if "--max-chunks" in sys.argv else None
    bad, tot, worst = audit(w, lim)
    print(f"{bad} of {tot} samples inside asphalt triangles have terrain above the road ({100.0 * bad / max(tot, 1):.2f} %)")
    for x in worst:
        print("  poke %.2f m at (%d, %d)" % x)
