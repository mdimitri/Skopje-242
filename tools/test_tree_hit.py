"""Dev test: a car hits a tree twice (leaves go, then the tree falls) and the streamer's tree meshes follow.
xvfb-run -a python tools/test_tree_hit.py <world dir>"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import pyray as rl  # noqa: E402

import actors  # noqa: E402
import bake  # noqa: E402
import gl3d  # noqa: E402
import world as world_mod  # noqa: E402

rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
rl.init_window(320, 200, "t")
img = rl.gen_image_color(4, 4, rl.WHITE)
tex = {"A": rl.load_texture_from_image(img)}
w = world_mod.World(sys.argv[1])
st = bake.Streamer(w, tex)
S = w.chunk
key = next(k for k, c in w.chunks.items() if c.get("t"))
x0, y0 = key[0] * S + S / 2, key[1] * S + S / 2
for _ in range(400):
    st.focus = (x0, y0)
    st.update([key], True, 50.0)
    if key in st.meshes and key not in st._part:
        break
assert key in st.meshes, "chunk never loaded"


def tree_verts():
    e = st.meshes[key][0]
    return sum(int(e[m].meshCount and e[m].meshes[0].vertexCount) for m in (20, 21) if m in e)


v0 = tree_verts()
pts = [p for c in w.pgrid.values() for p in c if p[2] >= 0.45 and p[4] - p[3] > 4 and key[0] * S <= p[0] < (key[0] + 1) * S and key[1] * S <= p[1] < (key[1] + 1) * S]
tx, ty, tr, lo, hi = pts[0]
car = actors.Car.__new__(actors.Car) if hasattr(actors, "Car") else None
print("tree at", tx, ty, "verts", v0)
e = (tx, ty, tr, lo, hi)
assert w.tree_hit(e, 1.0, 0, 1) is None
assert w.tree_hit(e, 4.0, 0, 1) == "shed"
st.tree_changed(tx, ty)
for _ in range(60):
    st.update([key], True, 50.0)
v1 = tree_verts()
print("after shed", v1)
assert v1 < v0, "leaves not removed"
assert w.tree_hit(e, 12.0, 0, 1) is None, "second hit inside the cooldown must not fell"
time.sleep(0.9)
assert w.tree_hit(e, 12.0, 0, 1) == "fall"
w.break_point(e, (0.0, -1.0))
st.tree_changed(tx, ty)
for _ in range(60):
    st.update([key], True, 50.0)
v2 = tree_verts()
print("after fall", v2, "fallen", len(w.fallen))
assert v2 <= v1 and len(w.fallen) == 1 and w.fallen[0][-1] is True
assert not any(p[0] == tx and p[1] == ty for c in w.pgrid.values() for p in c), "still solid"
print("OK")
