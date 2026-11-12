"""Mesh audit of a built world's road/solid geometry (material 3: asphalt, pavements, kerbs, markings, crossings).

    python3 tools/mesh_audit.py data/cache/world_s [--frac 0.1] [--top 8]

Measures, per sampled chunk and in total:
  * degenerate triangles (area < 1e-5 m2)
  * exact duplicate triangles (same three vertices to 1 mm, any order)
  * up / down facing flat triangles (a flat triangle facing against the majority winding is a backface / flipped one)
  * coplanar overlap: horizontal triangles that cover the same ground at the same height (+-3 mm) as another one: m2,
    the number of triangles that are completely redundant (all interior cells already covered) and partially overlapped.
Lower is better; the target is 0 for every line.  --frac picks a deterministic sample of chunks (default all).
"""
import argparse
import os
import pickle
import sys

import numpy as np

MAT_SOLID = 3
G = 0.2                                                    # raster cell (m)
EPS_Y = 0.003


def tri_raster(a, b, c, shrink=0.12):
    """Interior cell centres of triangle a,b,c (x,z in cell units) -> (x0, y0, mask)."""
    x0, x1 = int(min(a[0], b[0], c[0])), int(max(a[0], b[0], c[0])) + 1
    y0, y1 = int(min(a[1], b[1], c[1])), int(max(a[1], b[1], c[1])) + 1
    gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    if abs(d) < 1e-9:
        return x0, y0, None
    l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / d
    l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / d
    return x0, y0, (l1 > shrink) & (l2 > shrink) & (1 - l1 - l2 > shrink)


def audit_chunk(pos, col):
    n = len(pos) // 3
    t = pos[:n * 3].reshape(n, 3, 3).astype(np.float64)
    e1, e2 = t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
    nrm = np.cross(e1, e2)
    area = np.linalg.norm(nrm, axis=1) * 0.5
    degen = area < 1e-5
    seen, dup, pair = set(), 0, 0
    for k in range(n):
        vs = [tuple(v) for v in np.round(t[k] * 1000).astype(np.int64).tolist()]
        i0 = vs.index(min(vs))
        cyc = tuple(vs[i0:] + vs[:i0])                         # same winding, any starting vertex
        if cyc in seen:
            dup += 1
        else:
            seen.add(cyc)
    for k in range(n):                                          # opposite winding of an existing triangle: a deliberate double-sided face
        vs = [tuple(v) for v in np.round(t[k] * 1000).astype(np.int64).tolist()][::-1]
        i0 = vs.index(min(vs))
        if tuple(vs[i0:] + vs[:i0]) in seen:
            pair += 1
    ny = np.where(area > 1e-9, nrm[:, 1] / np.maximum(2 * area, 1e-12), 0.0)
    flat = (np.abs(ny) > 0.999) & ~degen
    up, down = int((flat & (ny > 0)).sum()), int((flat & (ny < 0)).sum())
    ov_m2, full, part, flat_m2 = 0.0, 0, 0, 0.0
    fi = np.nonzero(flat)[0]
    worst = None
    if len(fi) > 1:
        xs, zs = t[fi][:, :, 0], t[fi][:, :, 2]
        X0, Z0 = float(xs.min()) - 1, float(zs.min()) - 1
        W, H = int((xs.max() - X0) / G) + 3, int((zs.max() - Z0) / G) + 3
        if W * H <= 6_000_000:
            yg = {1: np.full((H, W), np.nan, np.float32), -1: np.full((H, W), np.nan, np.float32)}   # per facing: a double-sided pair is not an overlap
            for k in fi:
                a, b, c = [((t[k, j, 0] - X0) / G, (t[k, j, 2] - Z0) / G) for j in range(3)]
                x0, y0, m = tri_raster(a, b, c)
                if m is None or not m.any():
                    continue
                y = float(t[k, :, 1].mean())
                sub = yg[1 if ny[k] > 0 else -1][y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
                m = m[:sub.shape[0], :sub.shape[1]]
                hit = m & (np.abs(sub - y) < EPS_Y)
                nh = int(hit.sum())
                if nh:
                    ov_m2 += nh * G * G
                    if nh == int(m.sum()):
                        full += 1
                    else:
                        part += 1
                    if worst is None or nh > worst[0]:
                        worst = (nh, float(t[k, :, 0].mean()), float(t[k, :, 2].mean()))
                sub[m & ~hit] = y
            flat_m2 = float(area[fi].sum())
    # pavement slabs over asphalt: pavement-coloured up-facing triangle with an asphalt-coloured one 4-25 cm below
    pav_over = 0.0
    c0 = col[:n * 3].reshape(n, 3, 4)[:, 0, :3].astype(int)
    is_pav = (c0[:, 0] >= 168) & (c0[:, 0] <= 190) & (np.abs(c0[:, 0] - c0[:, 1] - 4) <= 2) & (np.abs(c0[:, 0] - c0[:, 2] - 12) <= 3)
    is_asp = (c0[:, 0] <= 135) & (c0[:, 2] >= c0[:, 0])
    pi, ai = np.nonzero(flat & (ny > 0) & is_pav)[0], np.nonzero(flat & (ny > 0) & is_asp)[0]
    if len(pi) and len(ai):
        xs, zs = t[np.concatenate([pi, ai])][:, :, 0], t[np.concatenate([pi, ai])][:, :, 2]
        X0, Z0 = float(xs.min()) - 1, float(zs.min()) - 1
        W, H = int((xs.max() - X0) / G) + 3, int((zs.max() - Z0) / G) + 3
        if W * H <= 6_000_000:
            asp = np.full((H, W), np.nan, np.float32)
            for k in ai:
                a, b, c = [((t[k, j, 0] - X0) / G, (t[k, j, 2] - Z0) / G) for j in range(3)]
                x0, y0, m = tri_raster(a, b, c)
                if m is not None:
                    sub = asp[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
                    sub[m[:sub.shape[0], :sub.shape[1]]] = float(t[k, :, 1].mean())
            for k in pi:
                a, b, c = [((t[k, j, 0] - X0) / G, (t[k, j, 2] - Z0) / G) for j in range(3)]
                x0, y0, m = tri_raster(a, b, c)
                if m is not None:
                    sub = asp[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
                    m = m[:sub.shape[0], :sub.shape[1]]
                    gap = float(t[k, :, 1].mean()) - sub
                    pav_over += int((m & (gap > 0.04) & (gap < 0.25)).sum()) * G * G
    return dict(pav_over=pav_over, tris=n, degen=int(degen.sum()), dup=dup, pair=pair, up=up, down=down, ov_m2=ov_m2, full=full, part=part,
                flat_m2=flat_m2, worst=worst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("world")
    ap.add_argument("--frac", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    with open(os.path.join(a.world, "chunks.pkl"), "rb") as f:
        chunks = pickle.load(f)
    chunks = chunks.get("chunks", chunks)
    mm = np.memmap(os.path.join(a.world, "meshes.bin"), dtype=np.uint8, mode="r")
    tot = dict(pav_over=0.0, tris=0, degen=0, dup=0, pair=0, up=0, down=0, ov_m2=0.0, full=0, part=0, flat_m2=0.0)
    bad, used = [], 0
    for key, ch in chunks.items():
        if not ch or MAT_SOLID not in ch.get("m", {}):
            continue
        kx, ky = key if isinstance(key, tuple) else (0, 0)
        if a.frac < 1.0 and ((kx * 7919 + ky * 104729) % 1000) >= a.frac * 1000:
            continue
        off, n = ch["m"][MAT_SOLID]
        pos = np.frombuffer(mm[off: off + n * 12], dtype=np.float32).reshape(n, 3)
        r = audit_chunk(pos, np.frombuffer(mm[off + n * 20: off + n * 24], dtype=np.uint8).reshape(n, 4))
        used += 1
        for k in tot:
            tot[k] += r[k]
        if r["worst"]:
            bad.append((r["ov_m2"], key, r["worst"]))
    print(f"chunks audited: {used}   solid triangles: {tot['tris']}")
    print(f"degenerate triangles:            {tot['degen']}")
    print(f"duplicate triangles:             {tot['dup']}")
    print(f"double-sided (reverse-winding) pairs: {tot['pair']}")
    print(f"flat triangles facing up / down: {tot['up']} / {tot['down']}   (minority = backfaces)")
    pct = 100.0 * tot['ov_m2'] / max(tot['flat_m2'], 1e-9)
    print(f"coplanar overlap area:           {tot['ov_m2']:.0f} m2 of {tot['flat_m2']:.0f} m2 flat ({pct:.2f} %)")
    print(f"pavement drawn over asphalt:     {tot['pav_over']:.0f} m2")
    print(f"  fully redundant triangles:     {tot['full']}")
    print(f"  partially overlapped:          {tot['part']}")
    for ov, key, (nh, x, z) in sorted(bad, reverse=True)[:a.top]:
        print(f"  worst chunk {key}: {ov:.0f} m2, e.g. near x={x:.0f} z={z:.0f}")


if __name__ == "__main__":
    sys.exit(main())
