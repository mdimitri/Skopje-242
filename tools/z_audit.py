"""Z-fighting audit of building meshes: parallel faces that overlap on the ground within a few cm of each other.

    python3 tools/z_audit.py data/cache/world_s [--frac 0.1] [--tol 0.03] [--top 10]

The game draws without backface culling, so two faces of ANY facing that are parallel, overlap in 2D and lie closer than the
depth buffer can separate flicker.  Every non-road material (walls, roofs, facade relief, clutter, decals) is sampled on a
10 cm grid in its plane; a cell hit by two different triangles whose plane offsets differ by less than --tol (default 3 cm)
is a z-fight cell.  Output: overlap area m2 by gap bucket and by material pair, and the worst chunks.  Target: 0.
Exempt: decals meant to sit on a surface are listed separately (material 6 graffiti, 18/19 kit layers) so the numbers show who flickers.
"""
import argparse
import collections
import os
import pickle
import sys

import numpy as np

G = 0.1
SKIP = {3}                                                  # roads / pavements: tools/mesh_audit.py
DETAIL = (17, 18, 19)                                       # drawn with glPolygonOffset (src/render.py DETAIL_MATS)
BUCKETS = [0.0005, 0.002, 0.01, 0.03, 0.10]                 # gap (m) edges


def samples(t, tri_id, mat, col=None):
    """Grid samples of triangles t (n,3,3) on their plane -> (key, cu, cv, d, tri) arrays."""
    e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
    nrm = np.cross(e1, e2)
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-6
    nrm = nrm[ok] / ln[ok, None]
    t, tri_id, mat = t[ok], tri_id[ok], mat[ok]
    col = np.zeros(len(t), np.int64) if col is None else col[ok]
    sg = np.where(nrm[:, 0] < -1e-6, -1.0, np.where(np.abs(nrm[:, 0]) <= 1e-6, np.where(nrm[:, 1] < -1e-6, -1.0, np.where(np.abs(nrm[:, 1]) <= 1e-6, np.where(nrm[:, 2] < 0, -1.0, 1.0), 1.0)), 1.0))
    nc = nrm * sg[:, None]                                  # canonical (sign-free) normal
    q = np.round(nc * 60).astype(np.int64)                  # ~1 degree bins
    keys = q[:, 0] * 1_000_003 + q[:, 1] * 1_009 + q[:, 2]
    out = []
    for i in range(len(t)):
        n = nc[i]
        a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
        u = np.cross(n, a); u /= np.linalg.norm(u)
        v = np.cross(n, u)
        p = t[i]
        uv = np.stack([p @ u, p @ v], 1)
        lo, hi = uv.min(0), uv.max(0)
        gu, gv = np.meshgrid(np.arange(np.floor(lo[0] / G), np.floor(hi[0] / G) + 1) + 0.5, np.arange(np.floor(lo[1] / G), np.floor(hi[1] / G) + 1) + 0.5)
        gu, gv = gu.ravel() * G, gv.ravel() * G
        a_, b_, c_ = uv
        d = (b_[1] - c_[1]) * (a_[0] - c_[0]) + (c_[0] - b_[0]) * (a_[1] - c_[1])
        if abs(d) < 1e-12:
            continue
        l1 = ((b_[1] - c_[1]) * (gu - c_[0]) + (c_[0] - b_[0]) * (gv - c_[1])) / d
        l2 = ((c_[1] - a_[1]) * (gu - c_[0]) + (a_[0] - c_[0]) * (gv - c_[1])) / d
        m = (l1 > 0.05) & (l2 > 0.05) & (1 - l1 - l2 > 0.05)
        k = int(m.sum())
        if k:
            off = float(p[0] @ n)
            out.append((np.full(k, keys[i]), np.round(gu[m] / G).astype(np.int64), np.round(gv[m] / G).astype(np.int64), np.full(k, off), np.full(k, tri_id[i]), np.full(k, mat[i]), np.full(k, sg[i]), np.full(k, col[i])))
    if not out:
        return None
    return [np.concatenate(c) for c in zip(*out)]


def audit_chunk(tris, mats, tol, cols=None):
    """tris (n,3,3), mats (n,), cols (n,) packed rgb -> (area by bucket, area by material pair, total sampled area, visible area).
    Visible: the two faces differ in material or colour (same-looking coincident faces flicker invisibly)."""
    s = samples(tris, np.arange(len(tris)), mats, cols)
    if s is None:
        return None
    key, cu, cv, d, tid, mt, sg, cl = s
    o = np.lexsort((d, cv, cu, key))
    key, cu, cv, d, tid, mt, sg, cl = (x[o] for x in (key, cu, cv, d, tid, mt, sg, cl))
    res = np.zeros(len(BUCKETS) + 1)
    pairs = collections.Counter()
    same = (key[1:] == key[:-1]) & (cu[1:] == cu[:-1]) & (cv[1:] == cv[:-1])
    # chains of cells: compare each sample with the next one in the cell (adjacent d); good enough to flag the clusters
    gap = np.abs(d[1:] - d[:-1])
    hit = same & (tid[1:] != tid[:-1]) & (gap < tol)
    idx = np.nonzero(hit)[0]
    dc = np.abs((cl[1:] >> 16) - (cl[:-1] >> 16)) + np.abs(((cl[1:] >> 8) & 255) - ((cl[:-1] >> 8) & 255)) + np.abs((cl[1:] & 255) - (cl[:-1] & 255))
    vh = hit & ((mt[1:] != mt[:-1]) | (dc > 12))
    vis = float(vh.sum()) * G * G
    off = np.isin(mt, DETAIL)                                   # src/render.py draws these with a polygon offset: they win
    vis_r = float((vh & (off[1:] == off[:-1])).sum()) * G * G
    if len(idx):
        b = np.searchsorted(BUCKETS, gap[idx])
        np.add.at(res, b, G * G)
        for i in idx:
            pairs[(int(min(mt[i], mt[i + 1])), int(max(mt[i], mt[i + 1])), "same" if sg[i] == sg[i + 1] else "opp")] += 1
    return res, pairs, len(d) * G * G, vis, vis_r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--frac", type=float, default=1.0)
    ap.add_argument("--tol", type=float, default=0.03)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    with open(os.path.join(a.world, "chunks.pkl"), "rb") as f:
        chunks = pickle.load(f)
    chunks = chunks.get("chunks", chunks)
    mm = np.memmap(os.path.join(a.world, "meshes.bin"), dtype=np.uint8, mode="r")
    vis = vis_r = 0.0
    tot, pairs, area, used, tris, worst = np.zeros(len(BUCKETS) + 1), collections.Counter(), 0.0, 0, 0, []
    for key, ch in chunks.items():
        if not ch or not ch.get("m"):
            continue
        kx, ky = key if isinstance(key, tuple) else (0, 0)
        if a.frac < 1.0 and ((kx * 7919 + ky * 104729) % 1000) >= a.frac * 1000:
            continue
        T, M, C = [], [], []
        for mat, (off, n) in ch["m"].items():
            if mat in SKIP:
                continue
            pos = np.frombuffer(mm[off: off + n * 12], dtype=np.float32).reshape(n, 3).astype(np.float64)
            T.append(pos[: n // 3 * 3].reshape(-1, 3, 3)); M.append(np.full(n // 3, mat))
            c = np.frombuffer(mm[off + n * 20: off + n * 24], dtype=np.uint8).reshape(n, 4)[: n // 3 * 3: 3].astype(np.int64)
            C.append(c[:, 0] << 16 | c[:, 1] << 8 | c[:, 2])
        if not T:
            continue
        T, M, C = np.concatenate(T), np.concatenate(M), np.concatenate(C)
        r = audit_chunk(T, M, a.tol, C)
        used += 1; tris += len(T)
        if r is None:
            continue
        tot += r[0]; area += r[2]; pairs.update(r[1]); vis += r[3]; vis_r += r[4]
        worst.append((r[0].sum(), key))
    names = ["<0.5 mm", "0.5-2 mm", "2-10 mm", "1-3 cm", "3-10 cm", ">10 cm"]
    print(f"chunks audited: {used}   triangles (non-road): {tris}   sampled surface: {area:.0f} m2")
    print(f"z-fight area (parallel faces overlapping within {a.tol*100:.0f} cm): {tot.sum():.0f} m2 = {100*tot.sum()/max(area,1e-9):.2f} % of surface")
    print(f"  of which visible (different material or colour): {vis:.0f} m2")
    print(f"  still fighting with the detail polygon offset:     {vis_r:.0f} m2")
    for n_, v in zip(names, tot):
        if n_ != names[-1] or v:
            print(f"  gap {n_:>9}: {v:9.0f} m2")
    print("  by material pair (cells, lo mat, hi mat, facing):")
    for (m1, m2, f), c in pairs.most_common(a.top):
        print(f"    {m1:>2} x {m2:<2} {f:<4} {c * G * G:9.0f} m2")
    for v, key in sorted(worst, reverse=True)[:a.top // 2]:
        print(f"  worst chunk {key}: {v:.0f} m2")


if __name__ == "__main__":
    sys.exit(main())
