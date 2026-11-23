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


class _Abs:
    """Stand-in deck for roads3d.Out: triangles that already carry absolute heights (the designer's decks)."""

    def at(self, x, z):
        return (0.0, 0.0, 0.0)


ABS = _Abs()


def _init(edges, ctx, decks=None, T=None):
    _G["edges"], _G["ctx"], _G["decks"], _G["T"] = edges, ctx, decks, T
    jn.RANGE = TILE / 2


def deck_feet(edges, decks, T, lift=0.12):
    """Where a driven deck still lies on the ground at a ground node, that stretch is ground road (drawn with the
    junction it belongs to, kerbs and pavements continuing); the deck proper starts where it lifts off.  Sets
    e["span"] = (s0, s1) on every driven bridge edge and -> the foot edges (ground copies, flat-capped at the lift-off)."""
    from shapely.geometry import LineString
    from shapely.ops import substring
    gn = {n for e in edges if e["drive"] and not e["bridge"] for n in (e["a"], e["b"])}
    feet = []
    for i, e in enumerate(edges):
        if not (e["drive"] and e["bridge"]) or len(e["pts"]) < 2 or decks is None or decks.get(e["road"]) is None:
            continue
        dk = decks[e["road"]]
        ln = LineString(e["pts"])
        L = ln.length
        S = np.append(np.arange(0.0, L, 1.0), L)
        xy = np.array([ln.interpolate(s).coords[0] for s in S])
        dh = np.array([dk.at(x, y)[0] for x, y in xy]) - np.asarray(T.h(xy[:, 0], xy[:, 1]), float)
        s0, s1 = 0.0, L
        if e["a"] in gn:
            k = 0
            while k + 1 < len(S) and dh[k + 1] < lift and S[k + 1] < 0.4 * L:
                k += 1
            s0 = min(max(S[k], 2.0), 0.4 * L)
        if e["b"] in gn:
            k = len(S) - 1
            while k - 1 >= 0 and dh[k - 1] < lift and S[k - 1] > 0.6 * L:
                k -= 1
            s1 = max(min(S[k], L - 2.0), 0.6 * L)
        if s1 - s0 < 1.0:
            continue
        e["span"] = (float(s0), float(s1))
        for a_, b_, na, nb in ((0.0, s0, e["a"], ("foot", i, 0)), (s1, L, ("foot", i, 1), e["b"])):
            if b_ - a_ < 0.5 or (na not in gn and nb not in gn):
                continue
            f = dict(e)
            f.update(pts=[tuple(c) for c in substring(ln, a_, b_).coords], bridge=False, flat=True, a=na, b=nb, len=b_ - a_)
            f.pop("span", None)
            feet.append(f)
    return feet


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


def _decks_job(tx, ty, sub, own):
    """Decks whose middle lies in this tile, absolute heights -> [(chunk key, positions, colours)]."""
    if not own or _G.get("decks") is None:
        return []
    B = []
    for e in sub:
        if e["drive"] and e["bridge"] and len(e["pts"]) >= 2:
            nb = _G["ctx"]["BL"].get(e["road"], jn.per_dir(e))
            B.append({"e": e, "ln": jn.LineString([(p[0] - tx, p[1] - ty) for p in e["pts"]]),
                      "hw": nb * jn.LW / 2 if e["ow"] else nb * jn.LW, "per": nb})
    mine = [d for d in B if any(d["e"] is _G["edges"][i] for i in own)]
    m = jn.port_decks(B, mine, tx, ty, _G["decks"], _G["T"])
    if not m.P:
        return []
    P = np.array(m.P, np.float32).reshape(-1, 3, 3)
    C = np.array(m.C, np.uint8).reshape(-1, 3, 4)[:, 0]
    P[:, :, 0] += tx
    P[:, :, 2] += ty
    return _by_chunk(P, C)


def _by_chunk(P, C):
    ix = np.floor(P[:, :, 0].mean(1) / CH).astype(np.int64)
    iz = np.floor(P[:, :, 2].mean(1) / CH).astype(np.int64)
    out = []
    for key in set(zip(ix.tolist(), iz.tolist())):
        sel = (ix == key[0]) & (iz == key[1])
        out.append((key, P[sel].reshape(-1, 3), np.repeat(C[sel], 3, 0)))
    return out


def _tile_job(job):
    (tx, ty), idx, own = job
    edges = _G["edges"]
    sub = [edges[i] for i in idx]
    dk = _decks_job(tx, ty, sub, own)
    m = jn.build(sub, tx, ty, port=True, ctx=_G["ctx"])
    if not m.P:
        return [], dk
    P = np.array(m.P, np.float32).reshape(-1, 3, 3)
    C = np.array(m.C, np.uint8).reshape(-1, 3, 4)[:, 0]
    P, C = _split(P, C)
    P[:, :, 1] += 0.06                                    # the game lifts its asphalt Y_BASE above the terrain
    P[:, :, 0] += tx
    P[:, :, 2] += ty
    return _by_chunk(P, C), dk


def tiles(edges):
    """-> [((tile centre x, y), [edge indices within the tile + margin])] for every tile holding a ground road."""
    ids = [i for i, e in enumerate(edges) if e["drive"] and len(e["pts"]) >= 2]        # decks too: they shape what meets them
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


def add_tiles(out, edges, prog=None, decks=None, T=None):
    """Adds the designer's ground-road triangles to roads3d.Out `out` (heights relative to the terrain) and, with
    decks and T, its driven decks (absolute heights)."""
    feet = deck_feet(edges, decks, T) if decks is not None and T is not None else []
    edges = list(edges) + feet
    ctx = jn.context(edges)
    for f in feet:                                       # the lift-off point continues onto the deck: not a dead end
        for nd in (f["a"], f["b"]):
            if isinstance(nd, tuple) and nd[:1] == ("foot",):
                ctx["gdeg"][nd] = 2
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
    own = {}                                             # each deck is drawn once, by the tile holding its middle
    for i, e in enumerate(edges):
        if e["drive"] and e["bridge"] and "span" in e:
            mx, my = e["pts"][len(e["pts"]) // 2]
            own.setdefault((int(math.floor(mx / TILE)), int(math.floor(my / TILE))), []).append(i)
    jobs = [(c, idx, own.get((int(math.floor(c[0] / TILE)), int(math.floor(c[1] / TILE))), [])) for c, idx in jobs]
    n = 0
    for k, (res, dres) in enumerate(par.pmap(_tile_job, jobs, init=(_init, (edges, ctx, decks, T)), chunk=1)):
        if prog and k % 10 == 0:
            prog(k / max(1, len(jobs)))
        for key, pos, col in res:
            e = out.d.setdefault((key, id(None)), ([], [], None, []))
            e[3].append((pos, col))
            n += len(pos)
        for key, pos, col in dres:
            e = out.d.setdefault((key, id(ABS)), ([], [], ABS, []))
            e[3].append((pos, col))
            n += len(pos)
    out.n += n
    print(f"[designer] {len(jobs)} tiles, {n // 3} triangles")
