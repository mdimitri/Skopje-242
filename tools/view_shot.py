"""Dev tool: a quick software render of a built world's meshes from any camera (no GPU, no game), to look at bridges,
underpasses and joints.  Flat shading from vertex colours, painter's order, so it is a sketch, not the game's look.

    python tools/view_shot.py <world> out.png  eye_x,eye_y,eye_h  look_x,look_y,look_h  [--r 160] [--fov 60] [--size 1200x700]

Coordinates are the world's (x east, y south, h up, metres).  Heights may be given relative to the ground with a
leading '+', e.g. +2 (the ground under that point plus 2 m)."""
import argparse
import math
import os
import pickle
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import world as world_mod  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("out")
    ap.add_argument("eye")
    ap.add_argument("look")
    ap.add_argument("--r", type=float, default=160.0)
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--size", default="1200x700")
    a = ap.parse_args()
    w = world_mod.World(a.world)

    def pt(s):
        x, y, h = s.split(",")
        x, y = float(x), float(y)
        h = w.ground_y(x, y) + float(h[1:]) if h.startswith("+") else float(h)
        return np.array([x, h, y])

    E, L = pt(a.eye), pt(a.look)
    W_, H_ = (int(v) for v in a.size.split("x"))
    with open(os.path.join(a.world, "chunks.pkl"), "rb") as f:
        ch = pickle.load(f)
    ch = ch.get("chunks", ch)
    mm = np.memmap(os.path.join(a.world, "meshes.bin"), dtype=np.uint8, mode="r")
    C = w.chunk
    P, K = [], []
    for (cx, cy), c in ch.items():
        if abs((cx + 0.5) * C - E[0]) > a.r + C or abs((cy + 0.5) * C - E[2]) > a.r + C:
            continue
        for mat, (off, n) in c["m"].items():
            pos = np.frombuffer(mm[off: off + n * 12], dtype=np.float32).reshape(-1, 3, 3)
            col = np.frombuffer(mm[off + n * 20: off + n * 24], dtype=np.uint8).reshape(-1, 3, 4)
            P.append(pos.astype(np.float64))
            K.append(col[:, :, :3].mean(1))
    st = 2.0                                                    # the ground the game draws at runtime (terrain + overlay)
    gx = np.arange(E[0] - a.r, E[0] + a.r + st, st)
    gy = np.arange(E[2] - a.r, E[2] + a.r + st, st)
    G = np.array([[w.ground_y(x, y) for x in gx] for y in gy])
    X_, Y_ = np.meshgrid(gx, gy)
    V = np.stack([X_, G, Y_], -1)
    q = np.stack([V[:-1, :-1], V[:-1, 1:], V[1:, 1:], V[:-1, :-1], V[1:, 1:], V[1:, :-1]], 2).reshape(-1, 3, 3)
    nq = len(q)
    P.insert(0, q)
    K.insert(0, np.tile([[128.0, 140.0, 104.0]], (nq, 1)))
    P = np.concatenate(P)
    K = np.concatenate(K)
    m = (np.abs(P[:, :, 0].mean(1) - E[0]) < a.r) & (np.abs(P[:, :, 2].mean(1) - E[2]) < a.r)
    m[:nq] = True
    P, K = P[m], K[m]
    ground = np.zeros(len(P), bool)
    ground[:nq] = True
    fw = L - E
    fw /= np.linalg.norm(fw)
    rt = np.cross(fw, [0, 1, 0])
    rt /= np.linalg.norm(rt)
    up = np.cross(rt, fw)
    rel = P - E
    cz = rel @ fw
    cx = rel @ rt
    cy = rel @ up
    keep = (cz > 0.3).all(1)
    f = (W_ / 2) / math.tan(math.radians(a.fov) / 2)
    sx = W_ / 2 + f * cx / np.maximum(cz, 0.3)
    sy = H_ / 2 - f * cy / np.maximum(cz, 0.3)
    keep &= ~(((sx < 0).all(1)) | ((sx > W_).all(1)) | ((sy < 0).all(1)) | ((sy > H_).all(1)))
    nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    sun = np.array([0.4, 0.8, 0.45])
    sun /= np.linalg.norm(sun)
    shade = 0.45 + 0.55 * np.abs(nrm @ sun)
    dep = cz.mean(1) + np.where(ground, 1e6, 0.0)               # the ground first (it lies under everything), then far to near
    order = np.argsort(-dep[keep])
    idx = np.nonzero(keep)[0][order]
    img = Image.new("RGB", (W_, H_), (170, 200, 230))
    dr = ImageDraw.Draw(img)
    for i in idx:
        c = tuple(int(v) for v in np.clip(K[i] * shade[i], 0, 255))
        dr.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=c)
    img.save(a.out)
    print(f"[view] {len(idx)} triangles -> {a.out}")


if __name__ == "__main__":
    main()
