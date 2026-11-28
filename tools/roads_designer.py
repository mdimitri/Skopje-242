"""Tile the candidate road mesh, retain raised decks and hand both to roads3d.Out."""
import math
import os
import zlib

import numpy as np
from shapely import intersects_xy
from shapely.geometry import LineString

import junction_net as jn
import par
import road_cache
import roads_candidate

TILE = 300.0
CH = 120.0                                               # roads3d.CHUNK
_G = {}


class _Abs:
    """Stand-in deck for roads3d.Out: triangles that already carry absolute heights (the designer's decks)."""

    def at(self, x, z):
        return (0.0, 0.0, 0.0)


ABS = _Abs()


def _init(edges, ctx, decks=None, T=None, source=None, cache=None):
    _G["edges"], _G["ctx"], _G["decks"], _G["T"] = edges, ctx, decks, T
    _G["source"], _G["cache"] = source, cache
    jn.RANGE = TILE / 2


def deck_feet(edges, decks, T, lift=0.02):
    """Where a driven deck still lies on the ground at a ground node, that stretch is ground road (drawn with the
    junction it belongs to, kerbs and pavements continuing). Retain at least a short portal at each ground
    junction; drape_feet follows the deck there if it already rises. Sets e["span"] = (s0, s1) and returns
    the approach copies, flat-capped at the deck seam."""
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
            s0 = min(max(float(S[k]), 2.0), 0.4 * L)
        if e["b"] in gn:
            k = len(S) - 1
            while k - 1 >= 0 and dh[k - 1] < lift and S[k - 1] > 0.6 * L:
                k -= 1
            s1 = max(min(float(S[k]), L - 2.0), 0.6 * L)
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


def drape_feet(P, edges, decks, T, tx, ty):
    """Keep candidate bridge mouths on their deck profile, including rising portals."""
    if decks is None or T is None:
        return
    points = P.reshape(-1, 3)
    x, y = points[:, 0] + tx, points[:, 2] + ty
    rise = np.zeros(len(points))
    for edge in edges:
        if not edge.get("flat") or not any(isinstance(n, tuple) and n[:1] == ("foot",) for n in (edge["a"], edge["b"])):
            continue
        deck = decks.get(edge["road"])
        if deck is None:
            continue
        mouth = LineString(edge["pts"]).buffer(edge["w"] / 2 + 2.4, cap_style="flat")
        ids = np.flatnonzero(intersects_xy(mouth, x, y))
        heights = np.array([deck.at(x[i], y[i])[0] for i in ids])
        rise[ids] = np.maximum(rise[ids], heights - T.h(x[ids], y[ids]))
    points[:, 1] += rise


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
                      "hw": e["w"] / 2, "per": nb})
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


def _tracked_tile_job(job):
    from progress import tile_state
    tx, ty = job[0]
    key = math.floor(tx / TILE), math.floor(ty / TILE)
    tile_state(key, "active")
    result = _tile_job(job)
    tile_state(key, "done")
    return result


def _tile_job(job):
    (tx, ty), idx, own = job
    edges = _G["edges"]
    sub = [edges[i] for i in idx]
    dk = _decks_job(tx, ty, sub, own)
    fallback = False
    controls = {}
    m = jn.build(sub, tx, ty, port=True, ctx=_G["ctx"])
    if not m.P:
        return [], dk, fallback, controls
    return _ground(m, sub, tx, ty, 6.0, 7), dk, fallback, controls


def _ground(m, sub, tx, ty, maxlen, rounds):
    """A ground mesh around (tx, ty) -> [(chunk key, positions, colours)] in world coordinates."""
    P = np.array(m.P, np.float32).reshape(-1, 3, 3)
    C = np.array(m.C, np.uint8).reshape(-1, 3, 4)[:, 0]
    P, C = _split(P, C, maxlen=maxlen, rounds=rounds)
    drape_feet(P, sub, _G["decks"], _G["T"], tx, ty)
    P[:, :, 1] += 0.06                                    # the game lifts its asphalt Y_BASE above the terrain
    P[:, :, 0] += tx
    P[:, :, 2] += ty
    return _by_chunk(P, C)


def _candidate_job(job):
    """One job of the candidate builder: ("road", centre, edge indices, skipped sites) | ("site", index, edge indices)
    | ("deck", centre, edge indices, own deck edges).  -> (result, name of its cache entry or None)."""
    if job[0] == "deck" or not _G["cache"]:
        return _compile_job(job), None
    k = road_cache.key(job, _G, TILE, roads_candidate.MARGIN)
    result = road_cache.load(_G["cache"], k, job, _G)
    if result is None:
        result = _compile_job(job)
        if result is not None:
            road_cache.save(_G["cache"], k, job, _G, result)
    elif job[0] == "road":
        from progress import tile_state
        tile_state((math.floor(job[1][0] / TILE), math.floor(job[1][1] / TILE)), "done")
    return result, k


def _compile_job(job):
    edges = _G["edges"]
    if job[0] == "deck":
        (tx, ty), idx, own = job[1:]
        return _decks_job(tx, ty, [edges[i] for i in idx], own)
    if job[0] == "site":
        index, idx = job[1:]
        sub = [edges[i] for i in idx]
        built = roads_candidate.build_site(_G["source"], index, sub, idx)
        if built is None:
            return None
        m, (ox, oy) = built
        surface = np.asarray(m.surface, np.uint8)
        blocks = _ground(m, sub, ox, oy, 18, 4) if m.P else []
        return blocks, m.controls, (m.surface_pixel, surface.shape, zlib.compress(surface.tobytes(), 1))
    (tx, ty), idx, skip = job[1:]
    sub = [edges[i] for i in idx]
    from progress import tile_state
    key = math.floor(tx / TILE), math.floor(ty / TILE)
    tile_state(key, "active")
    m = roads_candidate.build_tile(_G["source"], sub, tx, ty, TILE / 2, idx, skip)
    blocks = _ground(m, sub, tx, ty, 18, 4) if m.P else []
    tile_state(key, "done")
    return blocks, m.controls


def tiles(edges, padding=0.0, size=TILE):
    """-> [((tile centre x, y), [edge indices within the tile + margin])] for every tile holding a ground road."""
    ids = [i for i, e in enumerate(edges) if e["drive"] and len(e["pts"]) >= 2]        # decks too: they shape what meets them
    if not ids:
        return []
    lo = np.array([[min(p[0] for p in edges[i]["pts"]), min(p[1] for p in edges[i]["pts"])] for i in ids])
    hi = np.array([[max(p[0] for p in edges[i]["pts"]), max(p[1] for p in edges[i]["pts"])] for i in ids])
    ids = np.array(ids)
    reach = size / 2 + jn.MARGIN + 30
    cells = set()
    for a, b in zip(lo - padding, hi + padding):
        for gx in range(int(math.floor(a[0] / size)), int(math.floor(b[0] / size)) + 1):
            for gy in range(int(math.floor(a[1] / size)), int(math.floor(b[1] / size)) + 1):
                cells.add((gx, gy))
    jobs = []
    for gx, gy in sorted(cells):
        tx, ty = (gx + 0.5) * size, (gy + 0.5) * size
        sel = (hi[:, 0] > tx - reach) & (lo[:, 0] < tx + reach) & (hi[:, 1] > ty - reach) & (lo[:, 1] < ty + reach)
        if sel.any():
            jobs.append(((tx, ty), ids[sel].tolist() + [i for i, e in enumerate(edges) if False]))
    return jobs


def add_tiles(out, edges, prog=None, decks=None, T=None, source=None, controls=None):
    """Adds the designer's ground-road triangles to roads3d.Out `out` (heights relative to the terrain) and, with
    decks and T, its driven decks (absolute heights)."""
    feet = deck_feet(edges, decks, T) if decks is not None and T is not None else []
    edges = list(edges) + feet
    ctx = jn.context(edges)
    for f in feet:                                       # the lift-off point continues onto the deck: not a dead end
        for nd in (f["a"], f["b"]):
            if isinstance(nd, tuple) and nd[:1] == ("foot",):
                ctx["gdeg"][nd] = 2
    padding = max((e["w"] / 2 + 3 for e in edges if e["drive"]), default=0) if source is not None else 0
    walk = [i for i, e in enumerate(edges) if not e["drive"] and not e["bridge"] and e["cls"] in jn.WALK_W and len(e["pts"]) >= 2]
    wl = np.array([[min(p[0] for p in edges[i]["pts"]), min(p[1] for p in edges[i]["pts"]),
                    max(p[0] for p in edges[i]["pts"]), max(p[1] for p in edges[i]["pts"])] for i in walk]).reshape(-1, 4)
    walk = np.array(walk, int)

    def with_walks(size, found):
        """Footways take part too (zebras where they cross a carriageway)."""
        reach = size / 2 + jn.MARGIN + 30
        return [(c, idx + walk[(wl[:, 2] > c[0] - reach) & (wl[:, 0] < c[0] + reach) & (wl[:, 3] > c[1] - reach) & (wl[:, 1] < c[1] + reach)].tolist())
                for c, idx in found]

    own = {}                                             # each deck is drawn once, by the tile holding its middle
    for i, e in enumerate(edges):
        if e["drive"] and e["bridge"] and "span" in e:
            mx, my = e["pts"][len(e["pts"]) // 2]
            own.setdefault((int(math.floor(mx / TILE)), int(math.floor(my / TILE))), []).append(i)
    big = [(c, idx, own.get((int(math.floor(c[0] / TILE)), int(math.floor(c[1] / TILE))), []))
           for c, idx in with_walks(TILE, tiles(edges, padding))]
    cache = os.environ.get("SK242_ROAD_CACHE") if source is not None else None
    init = (_init, (edges, ctx, decks, T, source, cache))
    from progress import EVENTS, tile_plan
    on = (lambda done, total: prog(done / total) if done % 10 == 0 else None) if prog else None
    n = 0

    def ground(blocks, deck=None):
        nonlocal n
        for key, pos, col in blocks:
            e = out.d.setdefault((key, id(deck)), ([], [], deck, []))
            e[3].append((pos, col))
            n += len(pos)

    if source is None:
        tile_plan("3D roads", TILE, [(math.floor(c[0] / TILE), math.floor(c[1] / TILE)) for c, _, _ in big])
        job = _tracked_tile_job if EVENTS else _tile_job
        fallback_count = 0
        for res, dres, fallback, _ in par.pmap(job, big, init=init, chunk=1, on=on):
            fallback_count += fallback
            ground(res)
            ground(dres, ABS)
        out.n += n
        print(f"[designer] {len(big)} tiles, {fallback_count} fallback tiles, {n // 3} triangles")
        return

    road = [("road", c, idx, ()) for c, idx in with_walks(TILE, tiles(edges, padding))]
    tile_plan("3D roads", TILE, [(math.floor(j[1][0] / TILE), math.floor(j[1][1] / TILE)) for j in road])
    sites = []                                           # a site job gets every edge near its window
    for k, site in enumerate(source.sites):
        x0, y0, x1, y1 = site["core"].bounds
        m = roads_candidate.MARGIN + site["radius"] - (x1 - x0) / 2
        near = [i for i, e in enumerate(edges) if len(e["pts"]) >= 2
                and max(p[0] for p in e["pts"]) > x0 - m and min(p[0] for p in e["pts"]) < x1 + m
                and max(p[1] for p in e["pts"]) > y0 - m and min(p[1] for p in e["pts"]) < y1 + m]
        sites.append(("site", k, near))
    jobs = sites + road + [("deck", c, idx, o) for c, idx, o in big if o]
    # the longest jobs first, so no core waits at the end for one that started late
    cost = [1e9 if j[0] == "site" else _cost(source, j) for j in jobs]
    order = sorted(range(len(jobs)), key=lambda k: -cost[k])
    done = par.pmap(_candidate_job, [jobs[k] for k in order], init=init, chunk=1, on=on)
    results, used = [None] * len(jobs), set()
    for k, (r, entry) in zip(order, done):
        results[k] = r
        used.add(entry)
    failed = tuple(j[1] for j, r in zip(jobs, results) if j[0] == "site" and r is None)
    if failed:                                           # pave a window that did not compile with ordinary tiles
        again = [k for k, j in enumerate(jobs) if j[0] == "road" and any(
            source.sites[f]["core"].intersects(roads_candidate.box(j[1][0] - TILE / 2, j[1][1] - TILE / 2,
                                                                   j[1][0] + TILE / 2, j[1][1] + TILE / 2)) for f in failed)]
        for k, (r, entry) in zip(again, par.pmap(_candidate_job, [("road", *jobs[k][1:3], failed) for k in again], init=init, chunk=1)):
            results[k] = r
            used.add(entry)
    if cache:
        road_cache.prune(cache, used)
    surfaces = {}                                        # 300 m height maps (600 x 600 half-metre pixels), the game's layout
    found = {}
    for j, r in sorted(zip(jobs, results), key=lambda q: {"road": 0, "site": 1, "deck": 2}[q[0][0]]):
        if j[0] == "deck":
            ground(r, ABS)
            continue
        if r is None:
            continue
        ground(r[0])
        for kind, records in r[1].items():
            if kind != "surface_tiles":
                found.setdefault(kind, []).extend(records)
        if j[0] == "road":
            for (kx, ky), data in r[1]["surface_tiles"]:
                _paint(surfaces, kx * 600, ky * 600, np.frombuffer(zlib.decompress(data), np.uint8).reshape(600, 600))
        else:
            (px, py), shape, data = r[2]
            _paint(surfaces, px, py, np.frombuffer(zlib.decompress(data), np.uint8).reshape(shape))
    if controls is not None:
        for kind, records in found.items():
            controls.setdefault(kind, []).extend(records)
        controls["surface_tiles"] = [(key, zlib.compress(a.tobytes(), 1)) for key, a in sorted(surfaces.items())]
    out.n += n
    print(f"[road candidate] {len(road)} tiles, {len(sites) - len(failed)} reviewed windows, {n // 3} triangles")


def _cost(source, job):
    """Rough work of a road or deck job: the source features near it."""
    if job[0] == "deck":
        return len(job[3])
    (tx, ty), reach = job[1], TILE / 2 + roads_candidate.MARGIN
    return len(source.index.query(roads_candidate.box(tx - reach, ty - reach, tx + reach, ty + reach)))


def _paint(surfaces, px, py, a):
    """Lay the painted pixels of height map `a`, whose first pixel is (px, py) on the half-metre grid, onto the tiles."""
    h, w = a.shape
    for ky in range(py // 600, (py + h - 1) // 600 + 1):
        for kx in range(px // 600, (px + w - 1) // 600 + 1):
            dst = surfaces.get((kx, ky))
            if dst is None:
                dst = surfaces[(kx, ky)] = np.zeros((600, 600), np.uint8)
            x0, y0 = max(px, kx * 600), max(py, ky * 600)
            x1, y1 = min(px + w, kx * 600 + 600), min(py + h, ky * 600 + 600)
            src = a[y0 - py:y1 - py, x0 - px:x1 - px]
            view = dst[y0 - ky * 600:y1 - ky * 600, x0 - kx * 600:x1 - kx * 600]
            np.copyto(view, src, where=src > 0)
