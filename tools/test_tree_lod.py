"""Dev test: the tree level of detail follows the ring in both directions (approach: sprites at once, recede: blobs after a while),
also when a chunk upgrade is interrupted by the frame budget.   xvfb-run -a python tools/test_tree_lod.py <world dir>"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import pyray as rl  # noqa: E402

import bake  # noqa: E402
import world as world_mod  # noqa: E402

rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
rl.init_window(320, 200, "t")
img = rl.gen_image_color(4, 4, rl.WHITE)
tex = {"A": rl.load_texture_from_image(img)}
w = world_mod.World(sys.argv[1])
st = bake.Streamer(w, tex)
S = w.chunk
NEAR, FAR = 150.0, 337.0
keys_with_trees = [k for k, c in w.chunks.items() if c.get("t")]
ts = sorted(keys_with_trees, key=lambda k: (k[0], k[1]))
cx = sum(k[0] for k in ts) / len(ts) * S
cy = sum(k[1] for k in ts) / len(ts) * S


def ring(x, y):
    wanted, lite = [], set()
    for k in keys_with_trees:
        gx = max(k[0] * S - x, 0, x - (k[0] + 1) * S); gy = max(k[1] * S - y, 0, y - (k[1] + 1) * S)
        g = math.hypot(gx, gy)
        if g < FAR:
            wanted.append(k)
            if g >= NEAR:
                lite.add(k)
    wanted.sort(key=lambda k: (k[0] * S + S / 2 - x) ** 2 + (k[1] * S + S / 2 - y) ** 2)
    return wanted, lite


def settle(x, y, frames, budget):
    wanted, lite = ring(x, y)
    for _ in range(frames):
        st.update(wanted, True, budget, lite)
    return wanted, lite


def check(tag, x, y, frames=400, budget=2.0, far_pending_ok=False):
    wanted, lite = settle(x, y, frames, budget)
    bad = [(k, st.tree_lvl.get(k), "far" if k in lite else "near") for k in wanted if k in st.meshes
           and st.tree_lvl.get(k) is not None and st.tree_lvl[k] != (bake.TREE_FAR if k in lite else bake.TREE_NEAR)
           and not (far_pending_ok and k in lite)]                       # a chunk that just left the full ring keeps its sprites for a while
    miss = [k for k in wanted if k not in st.meshes]
    near_n = sum(1 for k in wanted if k not in lite)
    print(f"[{tag}] wanted {len(wanted)} (near {near_n}) loaded {len(wanted) - len(miss)} wrong-level {len(bad)} {bad[:3]}")
    assert not bad, f"{tag}: trees not at the level of their ring: {bad[:5]}"
    assert not miss, f"{tag}: chunks never loaded: {miss[:5]}"


x0, y0 = cx - 600, cy
check("start far west", x0, y0)                          # everything first loaded from far (blobs) or near
for i in range(1, 9):                                    # walk east 150 m at a time: chunks upgrade as they come close
    check(f"approach {i}", x0 + 150 * i, y0, frames=60, budget=1.0, far_pending_ok=True)
for i in range(8, -1, -1):                               # and back: they drop to blobs only after staying far
    check(f"recede {i}", x0 + 150 * i, y0, frames=400, budget=1.0)
print("tree level of detail follows the ring both ways: OK")
