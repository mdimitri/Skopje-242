"""Game integration of the junction designer (tools/junction_net.py): rebuilds the ground-road surfaces of the whole
network tile by tile (asphalt with tapered splits, kerbs, pavements, islands, lane paint, zebras) and hands the
triangles to roads3d.Out, whose flush() then drapes them on the 10 m terrain grid like every other road piece.

Tiles are clipped to their square and carry a 60 m margin of neighbouring roads, so neighbouring tiles agree on the
shared border.  Switched on with SK242_DESIGNER=1 (roads3d.build)."""
import math

import numpy as np

import junction_net as jn
import par

TILE = 300.0
CH = 120.0                                               # roads3d.CHUNK
_G = {}


def _init(edges, ctx):
    _G["edges"], _G["ctx"] = edges, ctx
    jn.RANGE = TILE / 2


def _split(P, C, maxlen=6.0, rounds=7):
    """Halve every triangle across its longest (horizontal) edge until all edges are <= maxlen, so the flush's terrain
    draping can follow the ground instead of cutting through it with long thin triangles."""
    for _ in range(rounds):
        e = np.stack([np.hypot(P[:, 1, 0] - P[:, 0, 0], P[:, 1, 2] - P[:, 0, 2]),
                      np.hypot(P[:, 2, 0] - P[:, 1, 0], P[:, 2, 2] - P[:, 1, 2]),
                      np.hypot(P[:, 0, 0] - P[:, 2, 0], P[:, 0, 2] - P[:, 2, 2])], 1)
        k = e.argmax(1)
        big = e[np.arange(len(P)), k] > maxlen
        if not big.any():
            break
        Pb, Cb, kb = P[big], C[big], k[big]
        i = np.arange(len(Pb))
        a, b, c = Pb[i, kb], Pb[i, (kb + 1) % 3], Pb[i, (kb + 2) % 3]
        mid = (a + b) / 2
        t1, t2 = np.stack([a, mid, c], 1), np.stack([mid, b, c], 1)
        P = np.concatenate([P[~big], t1, t2])
        C = np.concatenate([C[~big], Cb, Cb])
    return P, C


def _tile_job(job):
    (tx, ty), idx = job
    edges = _G["edges"]
    sub = [edges[i] for i in idx]
    m = jn.build(sub, tx, ty, port=True, ctx=_G["ctx"])
    if not m.P:
        return []
    P = np.array(m.P, np.float32).reshape(-1, 3, 3)
    C = np.array(m.C, np.uint8).reshape(-1, 3, 4)[:, 0]
    P, C = _split(P, C)
    P[:, :, 1] += 0.06                                    # the game lifts its asphalt Y_BASE above the terrain
    P[:, :, 0] += tx
    P[:, :, 2] += ty
    ix = np.floor(P[:, :, 0].mean(1) / CH).astype(np.int64)
    iz = np.floor(P[:, :, 2].mean(1) / CH).astype(np.int64)
    out = []
    for key in set(zip(ix.tolist(), iz.tolist())):
        sel = (ix == key[0]) & (iz == key[1])
        out.append((key, P[sel].reshape(-1, 3), np.repeat(C[sel], 3, 0)))
    return out


def tiles(edges):
    """-> [((tile centre x, y), [edge indices within the tile + margin])] for every tile holding a ground road."""
    ids = [i for i, e in enumerate(edges) if e["drive"] and not e["bridge"] and len(e["pts"]) >= 2]
    lo = np.array([[min(p[0] for p in edges[i]["pts"]), min(p[1] for p in edges[i]["pts"])] for i in ids])
    hi = np.array([[max(p[0] for p in edges[i]["pts"]), max(p[1] for p in edges[i]["pts"])] for i in ids])
    ids = np.array(ids)
    reach = TILE / 2 + jn.MARGIN + 30
    cells = set()
    for a, b in zip(lo, hi):
        for gx in range(int(math.floor(a[0] / TILE)), int(math.floor(b[0] / TILE)) + 1):
            for gy in range(int(math.floor(a[1] / TILE)), int(math.floor(b[1] / TILE)) + 1):
                cells.add((gx, gy))
    jobs = []
    for gx, gy in sorted(cells):
        tx, ty = (gx + 0.5) * TILE, (gy + 0.5) * TILE
        sel = (hi[:, 0] > tx - reach) & (lo[:, 0] < tx + reach) & (hi[:, 1] > ty - reach) & (lo[:, 1] < ty + reach)
        if sel.any():
            jobs.append(((tx, ty), ids[sel].tolist() + [i for i, e in enumerate(edges) if False]))
    return jobs


def add_tiles(out, edges, prog=None):
    """Adds the designer's ground-road triangles to roads3d.Out `out` (heights relative to the terrain)."""
    ctx = jn.context(edges)
    jobs = tiles(edges)
    # footways take part too (zebras where they cross a carriageway)
    walk = [i for i, e in enumerate(edges) if not e["drive"] and not e["bridge"] and e["cls"] in jn.WALK_W and len(e["pts"]) >= 2]
    if walk:
        wl = np.array([[min(p[0] for p in edges[i]["pts"]), min(p[1] for p in edges[i]["pts"]),
                        max(p[0] for p in edges[i]["pts"]), max(p[1] for p in edges[i]["pts"])] for i in walk])
        reach = TILE / 2 + jn.MARGIN + 30
        walk = np.array(walk)
        jobs = [((c, idx + walk[(wl[:, 2] > c[0] - reach) & (wl[:, 0] < c[0] + reach) & (wl[:, 3] > c[1] - reach) & (wl[:, 1] < c[1] + reach)].tolist()))
                for c, idx in jobs]
    n = 0
    for k, res in enumerate(par.pmap(_tile_job, jobs, init=(_init, (edges, ctx)), chunk=1)):
        if prog and k % 10 == 0:
            prog(k / max(1, len(jobs)))
        for key, pos, col in res:
            e = out.d.setdefault((key, id(None)), ([], [], None, []))
            e[3].append((pos, col))
            n += len(pos)
    out.n += n
    print(f"[designer] {len(jobs)} tiles, {n // 3} triangles")
