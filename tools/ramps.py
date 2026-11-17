"""Bridge and overpass approaches: deck profiles that meet the roads smoothly.

make_deck() pins a deck's ends to the terrain and lifts its middle to clear what runs underneath, so a short OSM bridge
way (an overpass, a bridge over a quay) climbed 4-5 m within its first 24 m: 20-50 % grades and a grade break of the
same size at the joint, where traffic jolted and jumped (tools/joint_audit.py).  Real approaches are embankments on
the roads leading up to the bridge.  Here, per chain of deck pieces (a bridge split into several OSM ways is one
chain):

  * the elevated part of the deck (more than LIFT_MIN above the ground) is kept as a requirement,
  * from it the profile falls at no more than G_MAX towards both ends and on along the approach roads (walked through
    simple road continuations, up to A_MAX) until it meets the ground; where an approach runs out sooner (a junction)
    that side is steeper,
  * a moving average over W m turns every corner into a vertical curve,
  * the deck pieces take the new heights, and the approach roads are raised onto an embankment by a height overlay
    (the river quays' 1 m Overlay, tools/quays.py): full height over the carriageway, falling at 1:2 to the ground
    beside it, never under a building.  Everything that reads the terrain (roads3d, kerbs, physics, the ground mesh)
    follows.  -> stats dict."""
import math

import numpy as np

import quays

G_MAX = 0.07           # steepest approach / deck grade where there is room
BERM = 3.5             # the embankment's top runs this far past the carriageway edge: pavement + verge, level
G_SHORT = 0.10         # a way under a deck is cleared only if the deck can climb over it at most this steeply
A_MAX = 140.0          # longest approach embankment (m)
W = 24.0               # vertical curve: moving average window (m)
LIFT_MIN = 1.2         # a deck point this far above the ground is "elevated": its height is kept (clearance)
SIDE = 0.5             # embankment side slope (rise per metre)
ROAD_FLANK = 0.07      # ... where another street runs into it
SLAB = 0.9             # deck thickness (tools/terrain.py SLAB)
JOIN = 0.6             # deck ends / road vertices this close are the same point
END_TOL = 0.08         # a chain end further than this from the ground after the embankments ...
G_EASE = 0.10          # ... is eased down to it at this grade
G_APP = 0.10           # steepest grade the ground beyond a deck end may climb away from it (else the end is raised)
_DBG = tuple(float(v) for v in __import__("os").environ["RAMPS_DEBUG"].split(",")) if __import__("os").environ.get("RAMPS_DEBUG") else None


def _poly_len(P):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(P, P[1:]))


def _resample(P, step=1.0):
    """Polyline -> points every `step` m (the end exactly)."""
    out = [P[0]]
    for a, b in zip(P, P[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(math.ceil(L / step)))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


def _key(p):
    return (round(p[0] / JOIN), round(p[1] / JOIN))


def _near(index, p):
    kx, ky = _key(p)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield from index.get((kx + dx, ky + dy), ())


def _branches(roads, rindex, p, away, lo):
    """Unit directions of the drivable roads leaving point p no more than acos(lo) from `away`."""
    out = []
    for ri, vi in _near(rindex, p):
        P = roads[ri]["pts"]
        if math.hypot(P[vi][0] - p[0], P[vi][1] - p[1]) > JOIN:
            continue
        for step in (1, -1):
            j = vi + step
            if 0 <= j < len(P):
                dx, dy = P[j][0] - p[0], P[j][1] - p[1]
                L = math.hypot(dx, dy) or 1e-9
                if (dx * away[0] + dy * away[1]) / L > lo:
                    out.append((dx / L, dy / L))
    return out


def _approach(roads, rindex, p, away, limit, lo=0.3):
    """Polyline from deck end p along the non-bridge drivable road(s) leading away from the bridge (direction `away`),
    through simple continuations, up to `limit` m.  -> (points, half width) or (None, 0)."""
    best = None
    for ri, vi in _near(rindex, p):
        rd = roads[ri]
        P = rd["pts"]
        if math.hypot(P[vi][0] - p[0], P[vi][1] - p[1]) > JOIN:
            continue
        for step in (1, -1):
            j = vi + step
            if not (0 <= j < len(P)):
                continue
            dx, dy = P[j][0] - p[0], P[j][1] - p[1]
            L = math.hypot(dx, dy) or 1e-9
            c = (dx * away[0] + dy * away[1]) / L
            if c > lo and (best is None or c > best[0]):
                best = (c, ri, vi, step)
    if best is None:
        return None, 0.0
    _, ri, vi, step = best
    out, hw, used = [tuple(p)], roads[ri]["w"] / 2, {ri}
    tot = 0.0
    while tot < limit:
        P = roads[ri]["pts"]
        j = vi + step
        while 0 <= j < len(P) and tot < limit:
            tot += math.hypot(P[j][0] - out[-1][0], P[j][1] - out[-1][1])
            out.append(tuple(P[j]))
            j += step
        if tot >= limit:
            break
        end, prev = out[-1], out[-2]                    # road ended: go on along the straightest road (also through a
        ux, uy = end[0] - prev[0], end[1] - prev[1]     # junction: the side streets ramp up to it at ROAD_FLANK)
        ul = math.hypot(ux, uy) or 1e-9
        nxt = None
        for r_, v_ in _near(rindex, end):
            Q = roads[r_]["pts"]
            if r_ in used or len(Q) < 2 or math.hypot(Q[v_][0] - end[0], Q[v_][1] - end[1]) > JOIN:
                continue
            for st in (1, -1):
                if 0 <= v_ + st < len(Q):
                    dx, dy = Q[v_ + st][0] - end[0], Q[v_ + st][1] - end[1]
                    c = (dx * ux + dy * uy) / ul / (math.hypot(dx, dy) or 1e-9)
                    if c > 0.85 and (nxt is None or c > nxt[0]):
                        nxt = (c, r_, v_, st)
        if nxt is None:
            break
        _, ri, vi, step = nxt
        used.add(ri)
    return out, hw


def _chains(dlist):
    """Deck pieces joined end to end -> [[(deck, reversed?), ...]]."""
    ends = {}
    for i, d in enumerate(dlist):
        for e in (0, 1):
            ends.setdefault(_key(d.pts[0 if e == 0 else -1]), []).append((i, e))

    def partner(i, e):
        p = dlist[i].pts[0 if e == 0 else -1]
        for kx in (-1, 0, 1):
            for ky in (-1, 0, 1):
                k = _key(p)
                for j, f in ends.get((k[0] + kx, k[1] + ky), ()):
                    q = dlist[j].pts[0 if f == 0 else -1]
                    if j != i and math.hypot(p[0] - q[0], p[1] - q[1]) <= JOIN:
                        return j, f
        return None
    seen, out = set(), []
    for i in range(len(dlist)):
        if i in seen:
            continue
        a = i                                           # walk back to a free end
        e_in = 0
        guard = 0
        while guard < len(dlist):
            pr = partner(a, e_in)
            if pr is None or pr[0] == i and guard:
                break
            a, e_in = pr[0], 1 - pr[1]
            guard += 1
        chain, cur, e_start = [], a, e_in
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append((cur, e_start == 1))           # reversed when we enter at its end 1
            pr = partner(cur, 1 - e_start)
            if pr is None:
                break
            cur, e_start = pr
        if chain:
            out.append(chain)
    return out


def _lift_overlay(T, items, blocked, hx, hy, segs=None):
    """items: [(points (k, 2), lift (k,), half width)] -> merged into T.q (created if needed).  Lift is full within
    hw + BERM of the centreline (the pavements stay level) and falls at SIDE beyond; `blocked(x, y, v)`: True keeps the post as it is
    (buildings), a number caps its lift."""
    S = quays.QSTEP
    add = {}
    cut = []                                             # long runs in pieces of <= 16 points: small boxes, fast
    for P, lift, hw in items:
        for k in range(0, max(1, len(P) - 1), 15):
            cut.append((P[k:k + 16], lift[k:k + 16], hw))
    for P, lift, hw in cut:
        if len(P) < 2:
            continue
        if lift.max() < 0.03:
            continue
        reach = hw + BERM + float(lift.max()) / ROAD_FLANK + 1.0
        x0, y0 = P.min(0) - reach
        x1, y1 = P.max(0) + reach
        gx = np.arange(math.floor((x0 + hx) / S), math.ceil((x1 + hx) / S) + 1)
        gy = np.arange(math.floor((y0 + hy) / S), math.ceil((y1 + hy) / S) + 1)
        GX, GY = np.meshgrid(gx * S - hx, gy * S - hy)
        best = np.zeros(GX.shape)
        slope = np.full(GX.shape, SIDE)                  # the flank: 1:2 over open ground, but a street running into
        if segs is not None:                             # the embankment ramps up at ROAD_FLANK (no 30-50 % wall across it)
            near = {sg for cx in range(int(x0 // 64), int(x1 // 64) + 1) for cy in range(int(y0 // 64), int(y1 // 64) + 1)
                    for sg in segs.get((cx, cy), ())}
            for ax, ay, bx, by, hw_o in near:
                if max(ax, bx) < x0 or min(ax, bx) > x1 or max(ay, by) < y0 or min(ay, by) > y1:
                    continue
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy or 1e-9
                t = np.clip(((GX - ax) * dx + (GY - ay) * dy) / l2, 0.0, 1.0)
                d = np.hypot(GX - ax - dx * t, GY - ay - dy * t) - hw_o - 0.5
                slope = np.minimum(slope, ROAD_FLANK + (SIDE - ROAD_FLANK) * np.clip(d / 3.0, 0.0, 1.0))
        for k in range(len(P) - 1):
            ax, ay = P[k]
            bx, by = P[k + 1]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            t = np.clip(((GX - ax) * dx + (GY - ay) * dy) / l2, 0.0, 1.0)
            d = np.hypot(GX - ax - dx * t, GY - ay - dy * t)
            li = lift[k] + (lift[k + 1] - lift[k]) * t
            v = li - np.maximum(0.0, d - hw - BERM) * slope
            best = np.maximum(best, v)
        for (iy, ix) in zip(*np.nonzero(best > 0.005)):
            key = (int(gx[ix]), int(gy[iy]))
            add[key] = max(add.get(key, 0.0), float(best[iy, ix]))
    keep = {}
    for (px, py), v in add.items():
        x, y = px * S - hx, py * S - hy
        r = blocked(x, y, v)                             # True: stays as it is; a number: lifted at most that much
        if isinstance(r, (bool, np.bool_)):
            if r:
                continue
        else:
            v = min(v, float(r))
            if v < 0.005:
                continue
        keep[(px, py)] = v
    return merge_posts(T, keep, hx, hy)


def merge_posts(T, add, hx, hy):
    """{(post x index, post y index): height delta} added onto the fine overlay T.q (created if needed) -> posts."""
    S, Tl = quays.QSTEP, quays.TILE
    nty = int(math.ceil(2 * hy / (S * Tl))) + 1
    ntx = int(math.ceil(2 * hx / (S * Tl))) + 1
    tiles = {}
    ov = getattr(T, "q", None)
    if ov is not None:
        for ty, tx in zip(*np.nonzero(ov.idx >= 0)):
            k = int(ov.idx[ty, tx])
            tiles[(int(tx), int(ty))] = [ov.d[k].astype(np.float32).copy(), ov.cls[k].copy()]
        nty, ntx = max(nty, ov.idx.shape[0]), max(ntx, ov.idx.shape[1])
    n = 0
    for (px, py), v in add.items():
        tx, ty = px // Tl, py // Tl
        for ox in ((0, 1) if px % Tl == 0 and tx > 0 else (0,)):        # a post on a tile border lives in both tiles
            for oy in ((0, 1) if py % Tl == 0 and ty > 0 else (0,)):
                ttx, tty = tx - ox, ty - oy
                if not (0 <= ttx < ntx and 0 <= tty < nty):
                    continue
                t_ = tiles.get((ttx, tty))
                if t_ is None:
                    t_ = tiles[(ttx, tty)] = [np.zeros((Tl + 1, Tl + 1), np.float32), np.zeros((Tl + 1, Tl + 1), np.uint8)]
                t_[0][py - tty * Tl, px - ttx * Tl] += v
        n += 1
    if not tiles:
        return 0
    idx = np.full((nty, ntx), -1, np.int32)
    Ds, Cs = [], []
    for (tx, ty) in sorted(tiles):
        idx[ty, tx] = len(Ds)
        Ds.append(tiles[(tx, ty)][0])
        Cs.append(tiles[(tx, ty)][1])
    T.q = quays.Overlay(hx, hy, idx, np.stack(Ds), np.stack(Cs))
    return n


def _write(dlist, chain, P, own, newH):
    """A chain's 1 m profile back onto its deck pieces."""
    for ci, (i, rev) in enumerate(chain):
        d = dlist[i]
        m = np.array(own) == ci
        if ci > 0:                                        # the joint point belongs to the previous piece too
            m[np.argmax(m) - 1] = True
        Ps, hs_ = P[m], newH[m]
        sc = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(Ps, axis=0).T))])
        cum = np.array(d.cum)
        hd = np.interp(d.len - cum if rev else cum, sc, hs_)
        d.h = [float(v) for v in hd]


FOOT_JOIN = 6.0       # a way with a vertex this near a deck end starts at the junction there: it does not pass under


def _under(ugrid, p, tang, e0, e1, cleared=True, ways=None):
    """Headroom a way crossing under deck point p (deck direction `tang`) needs, or 0.  Ways running along the deck (the
    approach roads it joins, parallel streets) or touching the bridge's ends do not count.  Unless the deck already `cleared` the ground there by 2 m, paths and streets
    within 20 m of an end meet the road at grade (a junction at the bridge foot) and do not count either.  `ways`: a set
    that collects the road indices of the ways that count."""
    tl = math.hypot(tang[0], tang[1]) or 1.0
    tx, ty = tang[0] / tl, tang[1] / tl
    best = 0.0
    for ax, ay, bx, by, hw, c, ri in ugrid.get((int(p[0] // 16), int(p[1] // 16)), ()):
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
        if math.hypot(p[0] - ax - dx * t, p[1] - ay - dy * t) >= hw:
            continue
        if abs(dx * tx + dy * ty) / math.sqrt(l2) > 0.87:     # within 30 degrees of the deck: along it, not under it
            continue
        if not cleared and min(math.hypot(p[0] - e[0], p[1] - e[1]) for e in (e0, e1)) < 20.0:
            # near the foot of a deck still at grade: only a street that really passes under the deck's centreline here
            # counts (it crosses it, away from the deck's ends); a street running into the bridge foot is a junction
            cx_, cy_ = p[0] - tx * 3.0, p[1] - ty * 3.0
            ex_, ey_ = p[0] + tx * 3.0, p[1] + ty * 3.0
            den = (ex_ - cx_) * dy - (ey_ - cy_) * dx
            if abs(den) < 1e-9:
                continue
            u = ((ax - cx_) * dy - (ay - cy_) * dx) / den
            v = ((ax - cx_) * (ey_ - cy_) - (ay - cy_) * (ex_ - cx_)) / den
            if not (0.0 <= u <= 1.0 and 0.02 < v < 0.98):
                continue
        if any(math.hypot(q[0] - e[0], q[1] - e[1]) < FOOT_JOIN for q in ((ax, ay), (bx, by)) for e in (e0, e1)):
            continue                                       # (a street leaving the junction at the foot: not under it)
        best = max(best, c)
        if ways is not None:
            ways.add(ri)
    return best


def _arc(P, p):
    """Arc length along polyline P of the point nearest to p."""
    best, s0, out = None, 0.0, 0.0
    for a, b in zip(P, P[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l2 = dx * dx + dy * dy
        t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
        d = math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)
        if best is None or d < best:
            best, out = d, s0 + t * math.sqrt(l2)
        s0 += math.sqrt(l2)
    return out


def _components(dlist):
    """Deck pieces that share ends -> (node of each piece end {(i, e): node}, node points [p], groups of piece indices
    that meet three or more at some node: interchanges, solved as one network by _network)."""
    nodes, pos = {}, []
    grid = {}
    for i, d in enumerate(dlist):
        for e in (0, 1):
            p = d.pts[0 if e == 0 else -1]
            hit = None
            for kx in (-1, 0, 1):
                for ky in (-1, 0, 1):
                    k = _key(p)
                    for n in grid.get((k[0] + kx, k[1] + ky), ()):
                        if math.hypot(p[0] - pos[n][0], p[1] - pos[n][1]) <= JOIN:
                            hit = n
            if hit is None:
                hit = len(pos)
                pos.append(p)
                grid.setdefault(_key(p), []).append(hit)
            nodes[(i, e)] = hit
    par = list(range(len(dlist)))

    def root(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    at = {}
    for (i, e), n in nodes.items():
        at.setdefault(n, []).append(i)
    for n, lst in at.items():
        for j in lst[1:]:
            par[root(j)] = root(lst[0])
    branch = {root(lst[0]) for lst in at.values() if len(lst) >= 3}
    groups = {}
    for i in range(len(dlist)):
        if root(i) in branch:
            groups.setdefault(root(i), []).append(i)
    return nodes, pos, list(groups.values())


def _network(T, dlist, group, nodes, pos, roads, rindex, ugrid, stats):
    """An interchange (deck pieces meeting three or more at a node: ramps, a raised ring, a junction up on the
    structure) as one height plan, so every piece meeting at a node has the same height there (no joints), the
    clearance a way under any piece needs spreads over the whole network at <= G_MAX (G_SHORT where the approaches
    are short), and every ground road leaving the network climbs to it on an embankment.  -> (deck writes, approach
    items, eased ends)."""
    X, H, own = [], [], []                                # 1 m samples: position, old height, piece (or -1: approach)
    adj = []
    nid = {}

    def sample(p, h, o):
        X.append(p)
        H.append(h)
        own.append(o)
        adj.append([])
        return len(X) - 1

    def link(a, b):
        L = math.hypot(X[a][0] - X[b][0], X[a][1] - X[b][1])
        adj[a].append((b, L))
        adj[b].append((a, L))
    for n in {nodes[(i, e)] for i in group for e in (0, 1)}:
        d_, e_ = next((dlist[i], e) for i in group for e in (0, 1) if nodes[(i, e)] == n)
        nid[n] = sample(tuple(pos[n]), d_.h[0 if e_ == 0 else -1], -2)
    pieces = {}
    for i in group:
        d = dlist[i]
        R = _resample(d.pts, 1.0)
        s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff([p[0] for p in R]), np.diff([p[1] for p in R])))])
        h = np.interp(s, d.cum, d.h)
        ids = [nid[nodes[(i, 0)]]]
        for k in range(1, len(R) - 1):
            ids.append(sample(R[k], float(h[k]), i))
            link(ids[-2], ids[-1])
        ids.append(nid[nodes[(i, 1)]])
        link(ids[-2], ids[-1])
        pieces[i] = ids
    deck_n = len(X)
    apps, terms = [], []
    for n, k0 in nid.items():                             # every ground road leaving a node: an approach
        p = X[k0]
        for b in _branches(roads, rindex, p, (1.0, 0.0), -1.01):
            A, hw = _approach(roads, rindex, p, b, A_MAX, lo=0.9)
            if not A or len(A) < 2:
                continue
            R = _resample(A, 1.0)
            ids = [k0]
            for q in R[1:]:
                ids.append(sample(q, T.hs(*q), -1))
                link(ids[-2], ids[-1])
            apps.append((ids, hw))
            terms.append(ids[-1])
    Xa = np.array(X, np.float64)
    t = np.array([T.hs(x, y) for x, y in Xa])
    Ha = np.array(H)
    req = np.full(len(X), -1e9)
    t_ref = float(np.median(t[terms])) if terms else float(np.median(t))
    for i, ids in pieces.items():                         # clearance over the ways under each piece
        d = dlist[i]
        for j, k in enumerate(ids):
            a, b = ids[max(0, j - 2)], ids[min(len(ids) - 1, j + 2)]
            c = _under(ugrid, Xa[k], Xa[b] - Xa[a], d.pts[0], d.pts[-1], cleared=Ha[k] - t[k] >= 2.0)
            if c > 0:
                req[k] = max(req[k], t[k] + c + SLAB)
            elif Ha[k] - t[k] > LIFT_MIN and t[k] < t_ref - LIFT_MIN:     # over a dip (water, a gully): kept
                req[k] = max(req[k], Ha[k])
    ground_end = {nid[n] for n in nid if any(ids[0] == nid[n] for ids, _ in apps)}
    floor = t.copy()
    dist_g = _spread(adj, {k: 0.0 for k in ground_end}, len(X))
    floor[:deck_n] = np.where(dist_g[:deck_n] > 6.0, t[:deck_n] + 0.35, t[:deck_n])
    is_term = np.zeros(len(X), bool)
    is_term[terms] = True
    for g in (G_MAX, 0.085, G_SHORT, 0.12):               # the gentlest grade whose cones are down by the approach ends
        cone = _cone(adj, req, g)
        if not terms or np.all(cone[is_term] <= t[is_term] + 0.05):
            break
    stats["short"] += g > G_MAX + 1e-6
    prof = np.maximum(cone, floor)
    prof[is_term] = t[is_term]
    fixed = is_term.copy()
    for _ in range(int(W * W / 6)):                       # vertical curves: ~ a W m moving average along every road
        nb = np.array([sum(prof[b] for b, _ in a) / len(a) if a else prof[k] for k, a in enumerate(adj)])
        prof = np.where(fixed, prof, 0.5 * prof + 0.5 * nb)
    prof = np.maximum(prof, floor)
    lift = prof - t
    writes = [(i, Xa[ids], prof[ids]) for i, ids in pieces.items()]
    items = []
    for ids, hw in apps:
        items.append((Xa[ids], lift[ids], hw))
        stats["approaches"] += 1
        stats["lifted_m"] = max(stats["lifted_m"], float(lift[ids].max()))
    eased = {i: tuple(pieces[i][-e] in ground_end and len(adj[pieces[i][-e]]) <= 2 for e in (0, 1)) for i in pieces}
    stats["network_pieces"] = stats.get("network_pieces", 0) + len(group)
    return writes, items, eased


def _spread(adj, src, n):
    """Graph distance from the sources {sample: start distance}."""
    import heapq
    dist = np.full(n, 1e9)
    hp = [(v, k) for k, v in src.items()]
    for v, k in hp:
        dist[k] = v
    heapq.heapify(hp)
    while hp:
        v, k = heapq.heappop(hp)
        if v > dist[k]:
            continue
        for b, L in adj[k]:
            if v + L < dist[b]:
                dist[b] = v + L
                heapq.heappush(hp, (v + L, b))
    return dist


def _cone(adj, req, g):
    """max over requirements r of req_r - g * graph distance(r, .)."""
    import heapq
    h = req.copy()
    hp = [(-v, k) for k, v in enumerate(req) if v > -1e8]
    heapq.heapify(hp)
    while hp:
        v, k = heapq.heappop(hp)
        v = -v
        if v < h[k]:
            continue
        for b, L in adj[k]:
            if v - g * L > h[b]:
                h[b] = v - g * L
                heapq.heappush(hp, (-h[b], b))
    return h


def smooth(T, decks, roads, blocked, hx, hy, log=print, rail=()):
    """See the module docstring.  decks: {road index: terrain.Deck} (changed in place).  rail: ground railway lines
    ([(x, y), ...]) that a deck crossing them must clear by RAIL_CLEAR."""
    dlist = [d for d in decks.values() if d.hw >= 3.0]          # carriageways (footbridges keep their steps / grades)
    rindex = {}
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or not rd.get("drive") or len(rd["pts"]) < 2:
            continue
        for vi, p in enumerate(rd["pts"]):
            rindex.setdefault(_key(p), []).append((ri, vi))
    ugrid = {}                                                  # ways that may pass under a deck, by 16 m cell
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or rd.get("tunnel") or not (rd.get("drive") or rd.get("walk")) or len(rd["pts"]) < 2:
            continue
        hw_, c_ = rd["w"] / 2 + (1.5 if rd.get("drive") else 0.5), (4.4 if rd.get("drive") else 3.0)
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            for cx in range(int((min(a[0], b[0]) - hw_) // 16), int((max(a[0], b[0]) + hw_) // 16) + 1):
                for cy in range(int((min(a[1], b[1]) - hw_) // 16), int((max(a[1], b[1]) + hw_) // 16) + 1):
                    ugrid.setdefault((cx, cy), []).append((a[0], a[1], b[0], b[1], hw_, c_, ri))
    rail = [list(map(tuple, pts)) for pts in rail if len(pts) >= 2]
    for j, pts in enumerate(rail):                              # (index -1 - j: railway j, never embanked)
        for a, b in zip(pts, pts[1:]):
            for cx in range(int((min(a[0], b[0]) - 2.5) // 16), int((max(a[0], b[0]) + 2.5) // 16) + 1):
                for cy in range(int((min(a[1], b[1]) - 2.5) // 16), int((max(a[1], b[1]) + 2.5) // 16) + 1):
                    ugrid.setdefault((cx, cy), []).append((a[0], a[1], b[0], b[1], 2.5, RAIL_CLEAR, -1 - j))
    items, stats = [], {"chains": 0, "approaches": 0, "short": 0, "lifted_m": 0.0, "no_room": 0, "ends_eased": 0}
    done = []
    cnodes, cpos, groups = _components(dlist)
    in_net = {i for g_ in groups for i in g_}
    for g_ in groups:
        writes, its, eased = _network(T, dlist, g_, cnodes, cpos, roads, rindex, ugrid, stats)
        items += its
        for i, Pw, hw_ in writes:
            _write(dlist, [(i, False)], Pw, [0] * len(Pw), hw_)
            done.append(([(i, False)], Pw, [0] * len(Pw), hw_, eased[i]))
    for chain in _chains(dlist):
        if any(i in in_net for i, _ in chain):
            continue
        # the chain's centreline at 1 m, which piece / sample each point came from, and the old heights
        P, H, own = [], [], []
        for ci, (i, rev) in enumerate(chain):
            d = dlist[i]
            pts, hs, cum = (d.pts[::-1], d.h[::-1], [d.len - c for c in d.cum[::-1]]) if rev else (d.pts, d.h, d.cum)
            R = _resample(pts, 1.0)
            s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff([p[0] for p in R]), np.diff([p[1] for p in R])))])
            h = np.interp(s, cum, hs)
            if P:
                R, h, s = R[1:], h[1:], s[1:]
            P += R
            H += list(h)
            own += [ci] * len(R)
        P = np.array(P, np.float64)
        H = np.array(H, np.float64)
        Ld = len(P)
        if Ld < 4:
            continue
        tg = np.array([T.hs(x, y) for x, y in P])
        # approaches at both ends, walked away from the bridge
        app, side_app, loops = [], [], []
        for end in (0, 1):
            p = P[0] if end == 0 else P[-1]
            q = P[min(3, Ld - 1)] if end == 0 else P[max(0, Ld - 4)]
            away = (p[0] - q[0], p[1] - q[1])
            n_ = math.hypot(*away) or 1.0
            A, hw = _approach(roads, rindex, p, (away[0] / n_, away[1] / n_), A_MAX)
            if A is None:                                     # a junction right at the bridge foot, no road straight on: the
                br = _branches(roads, rindex, p, (away[0] / n_, away[1] / n_), -0.6)     # junction stands on the embankment and
                if br:                                        # every road leaving it climbs down (the straightest sets the profile)
                    A, hw = _approach(roads, rindex, p, (away[0] / n_, away[1] / n_), A_MAX, lo=-0.6)
                    first = (A[1][0] - p[0], A[1][1] - p[1]) if A and len(A) > 1 else (0.0, 0.0)
                    for b_ in br:
                        if b_[0] * first[0] + b_[1] * first[1] > 0.99 * math.hypot(*first):
                            continue
                        Ab, hwb = _approach(roads, rindex, p, b_, A_MAX, lo=0.9)
                        if Ab:
                            side_app.append((end, np.array(_resample(Ab, 1.0), np.float64), hwb))
            else:                                             # a loop ramp that dives under this deck and merges at its foot
                loops.append((end, p))                        # climbs back up with it (decided once the ways under are known)
            app.append((_resample(A, 1.0) if A else [tuple(p)], hw))
        A0 = np.array(app[0][0][::-1], np.float64)           # far end first
        A1 = np.array(app[1][0], np.float64)
        X = np.concatenate([A0[:-1], P, A1[1:]])
        n0 = len(A0) - 1
        t = np.array([T.hs(x, y) for x, y in X])
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(X, axis=0).T))])
        req = np.full(len(X), -1e9)
        el = H - tg > LIFT_MIN
        req[n0:n0 + Ld][el] = H[el]
        floor = t.copy()
        floor[n0 + 6:n0 + Ld - 6] = np.maximum(floor[n0 + 6:n0 + Ld - 6], t[n0 + 6:n0 + Ld - 6] + 0.35)
        if not el.any():                                      # a deck on the ground: just round it into the roads
            req[n0:n0 + Ld] = H
        for ke, rng in ((n0, range(n0 - 1, -1, -1)), (n0 + Ld - 1, range(n0 + Ld, len(X)))):
            for k in rng:                                     # ground rising steeply away from a deck end (a bridge at the
                dd = abs(s[k] - s[ke])                        # bottom of a gully, 10 m terrain): the end comes up to meet it
                if dd > 40.0:
                    break
                if t[k] - G_APP * dd > max(req[ke], t[ke]) + 0.05:
                    req[ke] = t[k] - G_APP * dd
        under_ = set()
        for k in range(n0, n0 + Ld):                          # a street / path crossing under the deck anywhere (also within 24 m
            c = _under(ugrid, X[k], X[min(k + 2, len(X) - 1)] - X[max(k - 2, 0)], P[0], P[-1],   # of an end, where make_deck
                       cleared=H[k - n0] - t[k] >= 2.0, ways=under_)      # kept no clearance): full headroom + the slab
            if c > 0:
                need = t[k] + c + SLAB
                if max((need - t[0]) / max(1.0, s[k] - s[0]), (need - t[-1]) / max(1.0, s[-1] - s[k])) > G_SHORT:
                    stats["no_room"] += 1                     # no room to climb over it (a bridge foot right at the
                    continue                                  # street, no approach road): left as OSM has it
                req[k] = max(req[k], need)
        # the grade each side needs: the requirement must come down to the ground by the end of the approach
        ri_ = np.nonzero(req > -1e8)[0]
        g0 = max(G_MAX, float(np.max((req[ri_] - t[0]) / np.maximum(1.0, s[ri_] - s[0]))))    # steepest need from the
        g1 = max(G_MAX, float(np.max((req[ri_] - t[-1]) / np.maximum(1.0, s[-1] - s[ri_]))))  # ends (any requirement)
        stats["short"] += (g0 > G_MAX + 1e-6) + (g1 > G_MAX + 1e-6)
        cone = np.full(len(X), -1e9)
        for k in ri_:
            dsk = s - s[k]
            cone = np.maximum(cone, req[k] - np.where(dsk < 0, -dsk * g0, dsk * g1))
        prof = np.maximum(cone, floor)
        prof[0], prof[-1] = t[0], t[-1]
        pad = int(W)                                          # moving average: the ground continues beyond both ends
        ext = np.concatenate([np.full(pad, t[0]), prof, np.full(pad, t[-1])])
        ker = np.ones(pad) / pad
        sm = np.convolve(ext, ker, mode="same")[pad:pad + len(prof)]
        prof = np.maximum(sm, floor)
        fade = np.ones(len(X))
        k3 = min(3, len(X) // 2)
        fade[:k3] = np.linspace(0, 1, k3, endpoint=False) if k3 else fade[:k3]
        fade[len(X) - k3:] = np.linspace(1, 0, k3) if k3 else fade[len(X) - k3:]
        lift = (prof - t) * fade
        prof = t + lift
        if _DBG and min(math.hypot(P[0][0] - _DBG[0], P[0][1] - _DBG[1]), math.hypot(P[-1][0] - _DBG[0], P[-1][1] - _DBG[1])) < 15:
            print(f"[ramps dbg] chain {[dlist[i].pts[0] for i, _ in chain]} n0={n0} Ld={Ld} len={len(X)} g0={g0:.3f} g1={g1:.3f}")
            for k in range(0, len(X), 4):
                print(f"   {k:4d} s={s[k]:6.1f} x={X[k][0]:7.1f},{X[k][1]:7.1f} t={t[k]:6.2f} req={req[k] if req[k] > -1e8 else float('nan'):6.2f} prof={prof[k]:6.2f} {'D' if n0 <= k < n0 + Ld else ' '}")
        # back to the deck pieces
        newH = prof[n0:n0 + Ld]
        _write(dlist, chain, P, own, newH)
        done.append((chain, P, own, newH, (True, True)))
        for A, lo, hi in ((A0, 0, n0 + 1), (A1, n0 + Ld - 1, len(X))):
            if len(A) >= 2:
                items.append((X[lo:hi], lift[lo:hi], app[0][1] if lo == 0 else app[1][1]))
                stats["approaches"] += 1
                stats["lifted_m"] = max(stats["lifted_m"], float(lift[lo:hi].max()))
        for end, p in loops:
            for ri, vi in _near(rindex, p):
                Q = roads[ri]["pts"]
                if ri not in under_ or math.hypot(Q[vi][0] - p[0], Q[vi][1] - p[1]) > JOIN:
                    continue
                nxt = Q[vi - 1] if vi > 0 else Q[min(1, len(Q) - 1)]
                d_ = (nxt[0] - p[0], nxt[1] - p[1])
                dl_ = math.hypot(*d_) or 1.0
                Ab, hwb = _approach(roads, rindex, p, (d_[0] / dl_, d_[1] / dl_), A_MAX, lo=0.9)
                if Ab:
                    side_app.append((end, np.array(_resample(Ab, 1.0), np.float64), hwb))
        for end, Ab, hwb in side_app:                         # the other roads leaving a junction at the bridge foot
            le = float(lift[n0] if end == 0 else lift[n0 + Ld - 1])
            sb = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(Ab, axis=0).T))])
            lb = np.maximum(0.0, le - sb * G_MAX)
            if le > 0.05:
                items.append((Ab, lb, hwb))
                stats["approaches"] += 1
        stats["chains"] += 1
    segs = {}                                                   # streets for the flanks, by 64 m cell
    for rd in roads:
        if rd.get("bridge") or not rd.get("drive"):
            continue
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            for cx in range(int(min(a[0], b[0]) // 64), int(max(a[0], b[0]) // 64) + 1):
                for cy in range(int(min(a[1], b[1]) // 64), int(max(a[1], b[1]) // 64) + 1):
                    segs.setdefault((cx, cy), []).append((a[0], a[1], b[0], b[1], rd["w"] / 2))
    kg = {}                                                     # ways passing beneath a deck stay down (in a cutting
    for d in decks.values():                                    # between retaining walls) and climb out of it at G_MAX
        for a, b, ha, hb in zip(d.pts, d.pts[1:], d.h, d.h[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            for k in range(int(L // 2) + 1):
                f = min(1.0, k * 2.0 / (L or 1.0))
                p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                ws = set()
                if _under(ugrid, p, (b[0] - a[0], b[1] - a[1]), d.pts[0], d.pts[-1],
                          cleared=ha + (hb - ha) * f - T.hs(*p) >= 2.0, ways=ws) <= 0.0:
                    continue
                for cx in range(int((p[0] - 160) // 32), int((p[0] + 160) // 32) + 1):
                    for cy in range(int((p[1] - 160) // 32), int((p[1] + 160) // 32) + 1):
                        for ri in (r_ for r_ in ws if r_ >= 0):
                            kg.setdefault((cx, cy), set()).add((p[0], p[1], ri, round(_arc(roads[ri]["pts"], p), 1)))

    def clogs(x, y, v):
        """Most a post may be raised: on a way that passes under a deck it stays down below the deck and climbs at
        G_MAX out of the cutting (the way may be another bridge's approach); False where nothing limits it."""
        cr = kg.get((int(x // 32), int(y // 32)))
        if v <= 0.0 or not cr:
            return False
        mine = set()
        for ax, ay, bx, by, hw, c, ri in ugrid.get((int(x // 16), int(y // 16)), ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / l2))
            if ri >= 0 and math.hypot(x - ax - dx * t, y - ay - dy * t) < hw:
                mine.add(ri)
        sp = {ri: _arc(roads[ri]["pts"], (x, y)) for ri in mine}
        dmin = min((abs(sp[ri] - sc) for px, py, ri, sc in cr if ri in mine), default=None)     # along the way (a loop
        return False if dmin is None else max(0.0, (dmin - 8.0) * G_MAX)                    # ramp climbs all its length)
    stats["posts"] = _lift_overlay(T, items, lambda x, y, v: True if blocked(x, y) else clogs(x, y, v), hx, hy, segs)
    for chain, P, own, newH, ease in done:                            # an embankment that could not be raised (a building, a way
        s_ = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])   # passing under another deck) leaves the deck
        L_ = s_[-1]                                             # end hanging over the road: ease the deck down to the ground there
        corr = np.zeros(len(P))
        dl = [newH[0] - T.hs(P[0][0], P[0][1]), newH[-1] - T.hs(P[-1][0], P[-1][1])]
        dl = [v if abs(v) > END_TOL and ease[e] else 0.0 for e, v in enumerate(dl)]
        R_ = [max(8.0, abs(v) / G_EASE) for v in dl]
        stats["ends_eased"] += sum(1 for v in dl if v)
        Lm = max(L_, 1e-6)                                      # (each easing ends by the other end: a short deck never
        corr = (dl[0] * np.clip(1.0 - s_ / min(R_[0], Lm), 0.0, 1.0)      # sinks below both its ends)
                + dl[1] * np.clip(1.0 - (L_ - s_) / min(R_[1], Lm), 0.0, 1.0))
        if corr.any():
            _write(dlist, chain, P, own, newH - corr)
    stats["dug"] = _dig_under(T, decks, roads, ugrid, hx, hy, rail)
    log(f"[ramps] {stats['chains']} bridge chains smoothed, {stats['approaches']} approach embankments "
        f"(highest {stats['lifted_m']:.1f} m, {stats['posts']} posts), {stats['short']} approaches too short for "
        f"{G_MAX:.0%} (steeper there), {stats['no_room']} deck points over a way left low (no room to climb), "
        f"{stats['ends_eased']} deck ends eased onto ground that could not be raised")
    return stats


RAIL_CLEAR = 5.3      # headroom over a railway (the trains' pantograph height + margin)
G_RAIL_DIG = 0.025    # ... and the grade a railway cutting under a low street bridge climbs out at
G_DIG = 0.08          # a way under a deck that still lacks headroom is dug down, its floor climbing back out at this grade


def _dig_under(T, decks, roads, ugrid, hx, hy, rail=()):
    """Last resort for headroom: where a deck could not climb high enough over a way passing under it (the ground falls
    away steeply, a junction holds the deck's foot down), the way is lowered into a cutting by what is missing, the
    floor climbing back out at G_DIG on both sides.  -> number of ways dug."""
    import underpass
    want = {}                                              # way -> [(arc s, metres missing)]
    for d in decks.values():
        if d.hw < 3.0:
            continue
        for a, b, ha, hb in zip(d.pts, d.pts[1:], d.h, d.h[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            for k in range(int(L // 1.5) + 1):
                f = min(1.0, k * 1.5 / (L or 1.0))
                p = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
                hd = ha + (hb - ha) * f
                ws = set()
                c = _under(ugrid, p, (b[0] - a[0], b[1] - a[1]), d.pts[0], d.pts[-1], cleared=hd - float(T.hs(*p)) >= 2.0, ways=ws)
                if c <= 0.0:
                    continue
                for ri in ws:
                    lack = float(T.hs(*p)) + c + SLAB - 0.3 - hd
                    if lack > 0.1:
                        want.setdefault(ri, []).append((_arc(roads[ri]["pts"] if ri >= 0 else rail[-1 - ri], p), lack))
    def on_road(x, y):
        """Under a street's or path's surface (+0.5 m)."""
        for ax, ay, bx, by, hw, c, ri in ugrid.get((int(x // 16), int(y // 16)), ()):
            if ri < 0:
                continue
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
            if math.hypot(x - ax - dx * t, y - ay - dy * t) < roads[ri]["w"] / 2 + 0.5:
                return True
        return False
    plans = []
    for ri, lst in want.items():
        rd = roads[ri] if ri >= 0 else {"pts": rail[-1 - ri], "w": 4.4}
        g_ = G_DIG if ri >= 0 else G_RAIL_DIG                  # (a railway's cutting climbs out at a train's grade)
        X = np.array(_resample(rd["pts"], 1.0), np.float64)
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(X, axis=0).T))])
        dig = np.zeros(len(X))
        for sk, lk in lst:
            dig = np.maximum(dig, lk + 0.5 - np.abs(s - sk) * g_)
        dig = np.clip(dig, 0.0, None)
        top = np.array([T.hs(x, y) for x, y in X])
        plans.append({"pts": X, "floor": top - dig, "hw": rd["w"] / 2 + 0.3, "keep": None if ri >= 0 else on_road})
    return underpass.cut(T, plans, hx, hy) and len(plans) if plans else 0


STAIR_MAX = 1.0        # steepest footbridge flight (45 degrees)
FOOT_CLEAR = 4.4       # headroom a street needs under a footbridge (+ SLAB)


def footbridges(T, decks, roads, log=print):
    """Footbridges over streets: the OSM way is just the span, so make_deck left a short one on the ground, drawn across the
    carriageway it should cross.  Here a chain of walk-only decks (with the pieces extend_footbridges added) that a street
    passes under gets a level top over the street(s) (FOOT_CLEAR + SLAB above it, 1.5 m beyond each kerb) and straight
    flights from it down to its two ends, as steep as the length allows (stairs: tools/roads3d.py draws treads on steep
    walk decks), at most STAIR_MAX.  -> stats."""
    st = {"footbridges": 0, "lifted": 0, "no_room": 0}
    streets, grid = _street_index(roads)
    walk = [ri for ri, d in decks.items() if not roads[ri].get("drive") and roads[ri].get("walk")]
    dlist = [decks[ri] for ri in walk]
    rof = {id(decks[ri]): ri for ri in walk}
    for chain in _chains(dlist):
        P, H, own = [], [], []
        ends = set()
        for ci, (i, rev) in enumerate(chain):
            d = dlist[i]
            nd = roads[rof[id(d)]].get("nodes") or []
            ends |= {nd[0], nd[-1]} if nd else set()
            pts, hs = (d.pts[::-1], d.h[::-1]) if rev else (d.pts, d.h)
            if P:
                pts, hs = pts[1:], hs[1:]
            P += list(pts)
            H += list(hs)
            own += [ci] * len(pts)
        if len(P) < 2:
            continue
        sp = _spans(P, ends, streets, grid)
        st["footbridges"] += 1
        if not sp:
            continue
        L = _poly_len(P)
        a_, b_ = max(0.0, min(q[0] for q in sp)), min(L, max(q[1] for q in sp))
        top = max(float(T.hs(*q[2])) for q in sp) + FOOT_CLEAR + SLAB
        h0, h1 = H[0], H[-1]
        if (top - h0) / max(a_, 0.5) > STAIR_MAX or (top - h1) / max(L - b_, 0.5) > STAIR_MAX:
            st["no_room"] += 1
            continue
        Pa = np.array(P, np.float64)
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(Pa, axis=0).T))])
        newH = np.where(cum < a_, h0 + (top - h0) * cum / max(a_, 1e-6),
                        np.where(cum > b_, h1 + (top - h1) * (L - cum) / max(L - b_, 1e-6), top))
        newH = np.maximum(newH, min(h0, h1))
        _write(dlist, chain, Pa, own, newH)
        st["lifted"] += 1
    log(f"[ramps] footbridges: {st['footbridges']} checked, {st['lifted']} lifted over the street with stairs, "
        f"{st['no_room']} too short for 45 degree flights (left on the ground)")
    return st


def _street_index(roads):
    streets, grid = [], {}
    for rd in roads:
        if rd.get("bridge") or rd.get("tunnel") or not rd.get("drive") or len(rd["pts"]) < 2:
            continue
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            k = len(streets)
            streets.append((a, b, rd["w"] / 2, set(rd.get("nodes") or ())))
            for cx in range(int(min(a[0], b[0]) // 32), int(max(a[0], b[0]) // 32) + 1):
                for cy in range(int(min(a[1], b[1]) // 32), int(max(a[1], b[1]) // 32) + 1):
                    grid.setdefault((cx, cy), []).append(k)
    return streets, grid


def _spans(P, ends, streets, grid):
    """Where along the polyline P the streets passing under it are: [(s from, s to, (x, y) of the crossing)]."""
    out, seen, s0 = [], set(), 0.0
    for (ax, ay), (bx, by) in zip(P, P[1:]):
        sl = math.hypot(bx - ax, by - ay) or 1e-9
        for cx in range(int(min(ax, bx) // 32), int(max(ax, bx) // 32) + 1):
            for cy in range(int(min(ay, by) // 32), int(max(ay, by) // 32) + 1):
                for k in grid.get((cx, cy), ()):
                    if k in seen:
                        continue
                    (px, py), (qx, qy), hw, nds = streets[k]
                    if nds & ends:
                        continue                         # the street the footbridge lands on
                    rx, ry, sx, sy = bx - ax, by - ay, qx - px, qy - py
                    den = rx * sy - ry * sx
                    if abs(den) < 1e-9:
                        continue
                    t = ((px - ax) * sy - (py - ay) * sx) / den
                    u = ((px - ax) * ry - (py - ay) * rx) / den
                    if not (0.0 <= t <= 1.0 and 0.0 <= u <= 1.0):
                        continue
                    seen.add(k)
                    sin = abs(den) / (sl * (math.hypot(sx, sy) or 1.0))
                    half = (hw + 1.5) / max(sin, 0.35)       # the street's width measured along the footbridge
                    sc = s0 + t * sl
                    out.append((sc - half, sc + half, (ax + rx * t, ay + ry * t)))
        s0 += sl
    return out


def extend_footbridges(roads, log=print):
    """A footbridge way in OSM often covers only the span over the street: its stairs are not mapped, or are mapped as the
    footway beyond.  Where the span leaves no room for 45 degree flights down to its ends, the footway continuing from
    that end (straight on) is cut that much further and the cut piece becomes part of the bridge.  -> roads (new list)."""
    streets, grid = _street_index(roads)
    need = (FOOT_CLEAR + SLAB) / STAIR_MAX + 0.5
    by_end = {}
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or rd.get("drive") or not rd.get("walk") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            continue
        by_end.setdefault(rd["nodes"][0], []).append((ri, 0))
        by_end.setdefault(rd["nodes"][-1], []).append((ri, 1))
    fresh = [-2_000_000_000]
    cut = {}                                             # walk road -> (end, metres) to cut off it into the bridge
    n_ext = 0
    for rd in roads:
        if not rd.get("bridge") or rd.get("drive") or not rd.get("walk") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            continue
        P = rd["pts"]
        L = _poly_len(P)
        sp = _spans(P, {rd["nodes"][0], rd["nodes"][-1]}, streets, grid)
        if not sp:
            continue
        a_, b_ = min(q[0] for q in sp), max(q[1] for q in sp)          # the street may reach past the span's end
        for end, room in ((0, a_), (1, L - b_)):
            if room >= need:
                continue
            node = rd["nodes"][0 if end == 0 else -1]
            p, q = (P[0], P[1]) if end == 0 else (P[-1], P[-2])
            ax, ay = p[0] - q[0], p[1] - q[1]
            al = math.hypot(ax, ay) or 1.0
            best = None
            for ri2, e2 in by_end.get(node, ()):
                W = roads[ri2]["pts"]
                nxt = W[1] if e2 == 0 else W[-2]
                c = ((nxt[0] - p[0]) * ax + (nxt[1] - p[1]) * ay) / al / (math.hypot(nxt[0] - p[0], nxt[1] - p[1]) or 1.0)
                if c > -0.2 and ri2 not in cut and (best is None or c > best[0]):      # straight on, or turning along the street
                    best = (c, ri2, e2)
            if best is not None:
                cut[best[1]] = (best[2], need - room + 1.0)
                n_ext += 1
    out = []
    for ri, rd in enumerate(roads):
        if ri not in cut:
            out.append(rd)
            continue
        end, m = cut[ri]
        P, N = (rd["pts"], rd["nodes"]) if end == 0 else (rd["pts"][::-1], rd["nodes"][::-1])
        L = _poly_len(P)
        if L <= m + 1.0:                                 # short: all of it is stairs
            out.append(dict(rd, bridge=True, layer=max(rd.get("layer", 0), 1)))
            continue
        acc, k = 0.0, 0
        while k < len(P) - 1:
            sl = math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1])
            if acc + sl >= m:
                break
            acc += sl
            k += 1
        t = (m - acc) / (math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) or 1.0)
        c_ = (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
        fresh[0] -= 1
        A_ = (list(P[:k + 1]) + [c_], list(N[:k + 1]) + [fresh[0]])
        B_ = ([c_] + list(P[k + 1:]), [fresh[0]] + list(N[k + 1:]))
        if end == 1:
            A_ = (A_[0][::-1], A_[1][::-1])
            B_ = (B_[0][::-1], B_[1][::-1])
        out.append(dict(rd, pts=A_[0], nodes=A_[1], bridge=True, layer=max(rd.get("layer", 0), 1)))
        out.append(dict(rd, pts=B_[0], nodes=B_[1]))
    log(f"[ramps] footbridges: {n_ext} ends carried on along the footway for their stairs")
    return out


PAST = 7.0             # a bridge end carried on along its road reaches this far past the way it must clear
NEAR_END = 16.0        # ... when that way crosses within this distance of the end (on the deck or on the road beyond)


def extend_bridges(roads, log=print):
    """A street bridge whose end lands right on a way passing under it (a quay path under a river bridge's end, a slip
    road under an overpass end): the deck has no room left to clear it, so either the way runs into the girder or the
    road beyond climbs in a step.  The road continuing straight on from that end is cut further on and the cut piece
    becomes part of the bridge, so the deck spans the way and comes down to the road after it.  -> roads (new list)."""
    _sync_fresh(roads)
    idx, grid = [], {}
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or rd.get("tunnel") or not (rd.get("drive") or rd.get("walk")) or len(rd["pts"]) < 2:
            continue
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            k = len(idx)
            idx.append((a, b, rd["w"] / 2 + (1.5 if rd.get("drive") else 0.5), set(rd.get("nodes") or ()), ri))
            for cx in range(int(min(a[0], b[0]) // 32), int(max(a[0], b[0]) // 32) + 1):
                for cy in range(int(min(a[1], b[1]) // 32), int(max(a[1], b[1]) // 32) + 1):
                    grid.setdefault((cx, cy), []).append(k)
    by_end = {}
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or rd.get("tunnel") or not rd.get("drive") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            continue
        by_end.setdefault(rd["nodes"][0], []).append((ri, 0))
        by_end.setdefault(rd["nodes"][-1], []).append((ri, 1))
    deg = {}
    for rd in roads:
        if (rd.get("drive") or rd.get("walk")) and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                deg[n] = deg.get(n, 0) + 1

    def crossings(P, skip_nodes, skip_ri):
        """[(s along P, half width of the crossing way)] of the ways crossing P (not those joining it)."""
        out, s0 = [], 0.0
        for (ax, ay), (bx, by) in zip(P, P[1:]):
            sl = math.hypot(bx - ax, by - ay) or 1e-9
            seen = set()
            for cx in range(int(min(ax, bx) // 32), int(max(ax, bx) // 32) + 1):
                for cy in range(int(min(ay, by) // 32), int(max(ay, by) // 32) + 1):
                    for k in grid.get((cx, cy), ()):
                        if k in seen:
                            continue
                        seen.add(k)
                        (px, py), (qx, qy), hw, nds, ri2 = idx[k]
                        if ri2 in skip_ri or nds & skip_nodes:
                            continue
                        rx, ry, sx, sy = bx - ax, by - ay, qx - px, qy - py
                        den = rx * sy - ry * sx
                        if abs(den) < 1e-9:
                            continue
                        t = ((px - ax) * sy - (py - ay) * sx) / den
                        u = ((px - ax) * ry - (py - ay) * rx) / den
                        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
                            sin = abs(den) / (sl * (math.hypot(sx, sy) or 1.0))
                            out.append((s0 + t * sl, hw / max(sin, 0.35)))
            s0 += sl
        return out

    cut, n_ext = {}, 0
    for rd in roads:
        if not rd.get("bridge") or not rd.get("drive") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            continue
        P = rd["pts"]
        L = _poly_len(P)
        for end in (0, 1):
            node = rd["nodes"][0 if end == 0 else -1]
            if deg.get(node, 0) > 2:
                continue                                  # a junction at the bridge foot: ramps lifts it with its branches
            cands = by_end.get(node, ())
            if len(cands) != 1 or cands[0][0] in cut:
                continue
            ri2, e2 = cands[0]
            W = roads[ri2]["pts"] if e2 == 0 else roads[ri2]["pts"][::-1]
            Wn = roads[ri2]["nodes"] if e2 == 0 else roads[ri2]["nodes"][::-1]
            # the deck's last NEAR_END m, walked from the end inwards (s < 0: on the deck), then the road beyond (s > 0)
            D = P[::-1] if end == 1 else P
            need = 0.0
            mine = set(rd["nodes"]) | set(Wn)                 # ways sharing a node with either cross at grade
            for s, hw in crossings(D, mine, {ri2}):
                if s < NEAR_END:
                    need = max(need, PAST + hw - s)       # past a way under the deck end: the end moves on beyond it
            Lw = _poly_len(W)
            for s, hw in crossings(W, mine, {ri2}):
                if s < NEAR_END:
                    need = max(need, s + hw + PAST)
            if need <= 0.0:
                continue                                  # nothing under the end
            need = max(need, 8.0)                         # (a deck piece needs some length to ramp over it)
            if need > Lw - 2.0:
                continue                                  # the road ends (a junction) too soon
            cw = [0.0]
            for a_, b_ in zip(W, W[1:]):
                cw.append(cw[-1] + math.hypot(b_[0] - a_[0], b_[1] - a_[1]))
            if any(deg.get(n, 0) > 2 and 0.0 < c < need + 2.0 for n, c in zip(Wn, cw)):
                continue                                  # a side street joins within it: it would land on the deck
            cut[ri2] = (e2, need)
            n_ext += 1
    log(f"[ramps] street bridges: {n_ext} ends carried on along their road over a way passing under them")
    return _carry(roads, cut, _FRESH)


def align_twins(roads, log=print):
    """The two decks of a dual carriageway's bridge often end at different places in OSM: the shorter one stops while
    its twin goes on, so the deck surface, median barrier and pavements end in a stagger across the road.  The shorter
    deck is carried on along its road to where its twin ends (when nothing joins it there)."""
    _sync_fresh(roads)
    ends, by_end, deg = _foot_roads(roads)
    br = [(ri, rd) for ri, rd in enumerate(roads) if rd.get("bridge") and rd.get("drive") and len(rd["pts"]) >= 2
          and len(rd["nodes"]) == len(rd["pts"])]
    cut = {}
    for ri, rd in br:
        P = rd["pts"]
        for end in (0, 1):
            node = rd["nodes"][0 if end == 0 else -1]
            if deg.get(node, 0) != 2 or len(by_end.get(node, ())) != 1:
                continue
            p, q = (P[0], P[min(1, len(P) - 1)]) if end == 0 else (P[-1], P[-2])
            ul = math.hypot(p[0] - q[0], p[1] - q[1]) or 1.0
            u = ((p[0] - q[0]) / ul, (p[1] - q[1]) / ul)
            best = 0.0
            for rj, rb in br:
                if rj == ri or set(rb["nodes"]) & set(rd["nodes"]):
                    continue
                Q = rb["pts"]
                for k in range(len(Q) - 1):          # parallel, beside this end
                    a, b = Q[k], Q[k + 1]
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    L = math.hypot(dx, dy) or 1e-9
                    if abs(dx * u[0] + dy * u[1]) / L < 0.94:
                        continue
                    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L ** 2))
                    lat = math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)
                    if lat > 16.0:
                        continue
                    for qe in (Q[0], Q[-1]):
                        d = (qe[0] - p[0]) * u[0] + (qe[1] - p[1]) * u[1]
                        if abs((qe[0] - p[0]) * -u[1] + (qe[1] - p[1]) * u[0]) < 18.0 and 0.8 < d < 40.0:
                            best = max(best, d)
                    break
            if best <= 0.0:
                continue
            ri2, e2 = by_end[node][0]
            if ri2 in cut:
                continue
            W = roads[ri2]["pts"] if e2 == 0 else roads[ri2]["pts"][::-1]
            Wn = roads[ri2]["nodes"] if e2 == 0 else roads[ri2]["nodes"][::-1]
            cw = [0.0]
            for a_, b_ in zip(W, W[1:]):
                cw.append(cw[-1] + math.hypot(b_[0] - a_[0], b_[1] - a_[1]))
            if best > cw[-1] - 2.0 or any(deg.get(n, 0) > 2 and 0.0 < c < best + 2.0 for n, c in zip(Wn, cw)):
                continue
            cut[ri2] = (e2, best)
    log(f"[ramps] twin bridges: {len(cut)} deck ends carried on to where their twin ends")
    return _carry(roads, cut, _FRESH)


SVC_REACH = 26.0       # a service road crossing under a bridge this close to a foot that is a junction ...
SVC_CLEAR = 4.0        # ... stops this far from the deck's edge on both sides (two dead ends, no way through)


def cut_service_under_feet(roads, log=print):
    """A service road (a yard access, a car park lane) mapped straight under an interchange ramp just before the ramp
    lands at a junction: the ramp has no room to clear it and a level crossing across a ramp is not how it is built, so
    it ran through the deck.  The service road stops short of the ramp on both sides.  -> roads (new list)."""
    _sync_fresh(roads)
    deg = {}
    for rd in roads:
        if (rd.get("drive") or rd.get("walk")) and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                deg[n] = deg.get(n, 0) + 1
    decks = []
    for rd in roads:
        if rd.get("bridge") and rd.get("drive") and len(rd["pts"]) >= 2 and len(rd["nodes"]) == len(rd["pts"]):
            feet = [rd["pts"][0 if e == 0 else -1] for e in (0, 1)
                    if deg.get(rd["nodes"][0 if e == 0 else -1], 0) > 2 or _junction_close(roads, rd["nodes"][0 if e == 0 else -1], deg)]
            if feet:
                decks.append((rd, feet))
    out, n_cut = [], 0
    for rd in roads:
        if (rd.get("cls") != "service" or rd.get("bridge") or rd.get("tunnel") or not rd.get("drive")
                or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"])):
            out.append(rd)
            continue
        P = rd["pts"]
        cum = [0.0]
        for a, b in zip(P, P[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        gaps = []
        for dk, feet in decks:
            if set(dk["nodes"]) & set(rd["nodes"]):
                continue
            Q = dk["pts"]
            for k in range(len(P) - 1):
                for j in range(len(Q) - 1):
                    r_ = _isect(P[k], P[k + 1], Q[j], Q[j + 1])
                    if not r_:
                        continue
                    x = (P[k][0] + (P[k + 1][0] - P[k][0]) * r_[0], P[k][1] + (P[k + 1][1] - P[k][1]) * r_[0])
                    if min(math.hypot(x[0] - f[0], x[1] - f[1]) for f in feet) > SVC_REACH:
                        continue
                    sv = cum[k] + (cum[k + 1] - cum[k]) * r_[0]
                    h = dk["w"] / 2 + 2.4 + SVC_CLEAR
                    gaps.append((sv - h, sv + h))
        if not gaps:
            out.append(rd)
            continue
        gaps.sort()
        L, keep, s0 = cum[-1], [], 0.0
        for g0, g1 in gaps:
            if g0 > s0:
                keep.append((s0, g0))
            s0 = max(s0, g1)
        if s0 < L:
            keep.append((s0, L))
        for a_, b_ in keep:
            if b_ - a_ < 6.0:
                continue
            pts, nds = [], []
            for s_, q, n in zip(cum, P, rd["nodes"]):
                if a_ < s_ < b_:
                    pts.append(q)
                    nds.append(n)
            for end_s, at_front in ((a_, True), (b_, False)):
                if (end_s <= 0.0 and at_front) or (end_s >= L and not at_front):
                    q, n = (P[0], rd["nodes"][0]) if at_front else (P[-1], rd["nodes"][-1])
                else:
                    k = max(0, min(len(P) - 2, next(i for i in range(len(cum) - 1) if cum[i + 1] >= end_s)))
                    t = (end_s - cum[k]) / ((cum[k + 1] - cum[k]) or 1.0)
                    q = (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
                    _FRESH[0] -= 1
                    n = _FRESH[0]
                if at_front:
                    pts.insert(0, q)
                    nds.insert(0, n)
                else:
                    pts.append(q)
                    nds.append(n)
            out.append(dict(rd, pts=pts, nodes=nds))
        n_cut += len(gaps)
    log(f"[ramps] interchanges: {n_cut} service roads under a ramp foot stopped short of it")
    return out


SINK_PAD = 4.0         # the covered stretch of a road sunk under an interchange reaches this far past the deck's edge


def sink_under_interchanges(roads, T=None, log=print):
    """An interchange mapped as a cluster of short ramp bridges (three or more meeting at a node: a raised ring, ramps
    splitting on the structure) over a boulevard: there is no room for the ramps to climb 5 m and come back down
    between their junctions, so the cluster became a tangle of steep, overlapping decks.  Built instead like the
    city's underpasses: the cluster's roads stay at street level (ordinary roads with ordinary junctions) and the
    boulevard passing under them is sunk in a short covered cutting (tunnel=True: tools/underpass.py digs it, with
    ramps, and lift_over_tunnels carries the streets over its roof).  -> roads (new list)."""
    _sync_fresh(roads)
    br = [ri for ri, rd in enumerate(roads) if rd.get("bridge") and rd.get("drive") and len(rd["pts"]) >= 2
          and len(rd["nodes"]) == len(rd["pts"]) and not rd.get("tunnel")]
    at = {}
    for ri in br:
        for n in (roads[ri]["nodes"][0], roads[ri]["nodes"][-1]):
            at.setdefault(n, []).append(ri)
    par = {ri: ri for ri in br}

    def root(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for lst in at.values():
        for j in lst[1:]:
            par[root(j)] = root(lst[0])
    hub = {root(lst[0]) for lst in at.values() if len(lst) >= 3}
    deg = {}
    for rd in roads:
        if rd.get("drive") and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                deg[n] = deg.get(n, 0) + 1
    comp = {}
    for ri in br:
        comp.setdefault(root(ri), []).append(ri)

    def dip(pieces):                                       # spans a river / gully: a real bridge, never brought down
        if T is None:
            return True
        feet = [T.hs(*roads[ri]["pts"][e]) for ri in pieces for e in (0, -1)]
        low = min(float(T.hs(*p)) for ri in pieces for p in _resample(roads[ri]["pts"], 3.0))
        return low < min(feet) - 2.0

    def near_foot(pieces, x):                              # a crossing this close to a foot that is a junction
        for ri in pieces:
            for e in (0, -1):
                n, p = roads[ri]["nodes"][e], roads[ri]["pts"][e]
                if deg.get(n, 0) > 2 and len(at.get(n, ())) == 1 and math.hypot(x[0] - p[0], x[1] - p[1]) < 20.0:
                    return True
        return False
    sink, flat = {}, set()                                 # road -> [(s0, s1)] to sink; bridge roads to bring down
    for rt, pieces in comp.items():
        if dip(pieces):
            continue
        nodes = {n for ri in pieces for n in roads[ri]["nodes"]}
        hits = []
        for rj, rd in enumerate(roads):
            if (rd.get("bridge") or rd.get("tunnel") or not rd.get("drive") or len(rd["pts"]) < 2
                    or len(rd["nodes"]) != len(rd["pts"]) or set(rd["nodes"]) & nodes or rd.get("cls") == "service"):
                continue
            P = rd["pts"]
            cum = [0.0]
            for a, b in zip(P, P[1:]):
                cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
            for ri in pieces:
                Q = roads[ri]["pts"]
                for k in range(len(P) - 1):
                    for j in range(len(Q) - 1):
                        r_ = _isect(P[k], P[k + 1], Q[j], Q[j + 1])
                        if not r_:
                            continue
                        dx, dy = Q[j + 1][0] - Q[j][0], Q[j + 1][1] - Q[j][1]
                        ex, ey = P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]
                        sin = abs(dx * ey - dy * ex) / ((math.hypot(dx, dy) * math.hypot(ex, ey)) or 1.0)
                        h = (roads[ri]["w"] / 2 + 2.4) / max(sin, 0.35) + SINK_PAD
                        sv = cum[k] + (cum[k + 1] - cum[k]) * r_[0]
                        x = (P[k][0] + ex * r_[0], P[k][1] + ey * r_[0])
                        hits.append((rj, sv - h, sv + h, near_foot(pieces, x)))
        if not hits or rt not in hub:
            continue                                       # (a plain overpass with room for its ramps stays a bridge)
        hits = [h[:3] for h in hits]
        for rj, a_, b_ in hits:
            sink.setdefault(rj, []).append((a_, b_))
        flat.update(pieces)
    if not sink:
        return roads
    out = []
    for ri, rd in enumerate(roads):
        if ri in flat:
            out.append(dict(rd, bridge=False, layer=0))
            continue
        if ri not in sink:
            out.append(rd)
            continue
        P, N = rd["pts"], rd["nodes"]
        cum = [0.0]
        for a, b in zip(P, P[1:]):
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        iv = sorted(sink[ri])
        merged = []
        for a_, b_ in iv:
            a_, b_ = max(0.0, a_), min(cum[-1], b_)
            if merged and a_ <= merged[-1][1] + 6.0:
                merged[-1][1] = max(merged[-1][1], b_)
            else:
                merged.append([a_, b_])
        marks = {}                                         # arc length -> (point, node) of the cut points
        for a_, b_ in merged:
            for s_ in (a_, b_):
                if 0.5 < s_ < cum[-1] - 0.5:
                    k = max(0, min(len(P) - 2, next(i for i in range(len(cum) - 1) if cum[i + 1] >= s_)))
                    t = (s_ - cum[k]) / ((cum[k + 1] - cum[k]) or 1.0)
                    _FRESH[0] -= 1
                    marks[s_] = ((P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t), _FRESH[0])
        seq = sorted([(c, p, n) for c, p, n in zip(cum, P, N)] + [(s_, p, n) for s_, (p, n) in marks.items()], key=lambda q: q[0])
        bounds = [0.0] + sorted(marks) + [cum[-1]]
        for a_, b_ in zip(bounds, bounds[1:]):
            part = [q for q in seq if a_ - 1e-6 <= q[0] <= b_ + 1e-6]
            if len(part) < 2:
                continue
            mid = (a_ + b_) / 2
            tun = any(m0 <= mid <= m1 for m0, m1 in merged)
            out.append(dict(rd, pts=[q[1] for q in part], nodes=[q[2] for q in part], tunnel=tun or rd.get("tunnel", False)))
    log(f"[ramps] interchanges: {len(flat)} ramp decks brought down to street level, "
        f"{sum(len(v) for v in sink.values())} crossings of the road under them sunk in a covered cutting")
    return out


def level_minor_bridges(roads, log=print):
    """A field track or yard lane mapped as a short bridge over a street, with no room for any ramp (it sat on the
    street, 0 m clear): it becomes a level crossing, a junction on both roads.  -> roads (changed in place)."""
    _sync_fresh(roads)
    n_lv = 0
    for rd in roads:                                       # a tunnel too short to dig (< 8 m: a culvert under a field track)
        if not (rd.get("tunnel") and rd.get("drive") and len(rd["pts"]) >= 2 and len(rd["nodes"]) == len(rd["pts"])
                and _poly_len(rd["pts"]) < 8.0):          # is a level crossing with whatever crosses it
            continue
        rd["tunnel"], rd["layer"] = False, 0
        for r2 in roads:
            if r2 is rd or not (r2.get("drive") or r2.get("walk")) or len(r2["pts"]) < 2 or len(r2["nodes"]) != len(r2["pts"]):
                continue
            hit = next(((k, j, r_) for k in range(len(rd["pts"]) - 1) for j in range(len(r2["pts"]) - 1)
                        for r_ in [_isect(rd["pts"][k], rd["pts"][k + 1], r2["pts"][j], r2["pts"][j + 1])]
                        if r_ and 0.02 < r_[0] < 0.98 and 0.02 < r_[1] < 0.98), None)
            if hit:
                k, j, (t, u) = hit
                _FRESH[0] -= 1
                _split_at(rd, k, t, _FRESH[0])
                _split_at(r2, j, u, _FRESH[0])
                r2["bridge"], r2["layer"] = False, 0
                n_lv += 1
    for rd in roads:
        if (not rd.get("bridge") or not rd.get("drive") or rd.get("cls") not in ("track", "service")
                or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]) or _poly_len(rd["pts"]) > 40.0):
            continue
        hit = None
        for r2 in roads:
            if (r2 is rd or r2.get("bridge") or (r2.get("tunnel") and _poly_len(r2["pts"]) > 12.0) or not r2.get("drive") or len(r2["pts"]) < 2
                    or len(r2["nodes"]) != len(r2["pts"]) or set(r2["nodes"]) & set(rd["nodes"])):
                continue
            for k in range(len(rd["pts"]) - 1):
                for j in range(len(r2["pts"]) - 1):
                    r_ = _isect(rd["pts"][k], rd["pts"][k + 1], r2["pts"][j], r2["pts"][j + 1])
                    if r_ and 0.02 < r_[0] < 0.98 and 0.02 < r_[1] < 0.98:
                        hit = (r2, k, j, r_)
                        break
                if hit:
                    break
            if hit:
                break
        if not hit:
            continue
        r2, k, j, (t, u) = hit
        _FRESH[0] -= 1
        _split_at(rd, k, t, _FRESH[0])
        _split_at(r2, j, u, _FRESH[0])
        rd["bridge"], rd["layer"] = False, 0
        if r2.get("layer", 0) < 0 or r2.get("tunnel"):
            r2["layer"], r2["tunnel"] = 0, False
        n_lv += 1
    log(f"[ramps] {n_lv} track / yard-lane bridges sitting on a street made level crossings")
    return roads


TAIL_MAX = 25.0       # longest bank tail of a bridge way made ordinary road (longer may span a street)


def ground_bridge_tails(roads, T, log=print):
    """OSM often draws a short bridge (a culvert, a stream) as a longer way running on along the bank, with a side road
    joining that bank part at grade: the deck was pinned to the ground at the join and stepped there.  The part of the
    bridge between such a join and its foot, over ground no lower than the join, becomes ordinary road.  -> roads."""
    joins = {}
    for rd in roads:
        if not rd.get("bridge") and not rd.get("tunnel") and rd.get("drive") and len(rd["nodes"]) >= 2:
            for n in (rd["nodes"][0], rd["nodes"][-1]):
                joins[n] = joins.get(n, 0) + 1
    out, n_tail = [], 0
    for rd in roads:
        P, N = rd["pts"], rd.get("nodes") or []
        if not rd.get("bridge") or not rd.get("drive") or len(P) < 3 or len(N) != len(P):
            out.append(rd)
            continue
        g = [float(T.hs(*p)) for p in P]
        lo, hi = 0, len(P) - 1                           # the span that stays a bridge
        for k in range(1, len(P) - 1):
            if N[k] in joins and min(g[:k + 1]) > g[k] - 1.5 and _poly_len(P[:k + 1]) < TAIL_MAX:
                lo = k                                   # nothing low between the start and this join
        for k in range(len(P) - 2, 0, -1):
            if N[k] in joins and min(g[k:]) > g[k] - 1.5 and _poly_len(P[k:]) < TAIL_MAX:
                hi = k
        if lo == 0 and hi == len(P) - 1 or hi - lo < 1:
            out.append(rd)
            continue
        if lo > 0:
            out.append(dict(rd, pts=P[:lo + 1], nodes=N[:lo + 1], bridge=False, layer=0))
            n_tail += 1
        out.append(dict(rd, pts=P[lo:hi + 1], nodes=N[lo:hi + 1]))
        if hi < len(P) - 1:
            out.append(dict(rd, pts=P[hi:], nodes=N[hi:], bridge=False, layer=0))
            n_tail += 1
    log(f"[ramps] {n_tail} bridge tails running on along the bank past a side road made ordinary road")
    return out


def detach_low_joins(roads, log=print):
    """A side road that OSM joins to a bridge in the middle of its span (after ground_bridge_tails took the bank tails
    off): the deck lifts over what it spans, so the junction stood under or on a cliff of it and cars stepped up.  The
    side road stops short of the bridge instead (a dead end beside it).  -> roads (changed in place)."""
    _sync_fresh(roads)
    br = [rd for rd in roads if rd.get("bridge") and rd.get("drive") and len(rd["pts"]) >= 2 and len(rd["nodes"]) == len(rd["pts"])]
    at_end = {}
    for i, rd in enumerate(br):
        for e in (0, -1):
            at_end.setdefault(rd["nodes"][e], []).append(i)
    seen, inner = set(), {}
    for i0 in range(len(br)):                              # bridges chained end to end (one OSM bridge in several ways)
        if i0 in seen:
            continue
        P, N, W = list(br[i0]["pts"]), list(br[i0]["nodes"]), br[i0]["w"]
        seen.add(i0)
        for fwd in (True, False):
            while True:
                n = N[-1] if fwd else N[0]
                nxt = [j for j in at_end.get(n, ()) if j not in seen]
                if len(at_end.get(n, ())) != 2 or len(nxt) != 1:
                    break
                j = nxt[0]
                q, m = br[j]["pts"], br[j]["nodes"]
                if (m[0] == n) != fwd:
                    q, m = q[::-1], m[::-1]
                a_, b_ = (P[-2], P[-1]) if fwd else (P[1], P[0])          # it must go straight on (not a fork / hairpin)
                c_ = q[1] if fwd else q[-2]
                u_, v_ = (b_[0] - a_[0], b_[1] - a_[1]), (c_[0] - b_[0], c_[1] - b_[1])
                if u_[0] * v_[0] + u_[1] * v_[1] < 0.5 * math.hypot(*u_) * math.hypot(*v_):
                    break
                seen.add(j)
                P, N = (P + list(q[1:]), N + list(m[1:])) if fwd else (list(q[:-1]) + P, list(m[:-1]) + N)
        for n in N[1:-1]:                                  # (any join mid-span: the deck climbs over what it spans and
            inner[n] = W / 2 + 2.4 + 1.0                   # treated the side road as passing under it, digging it down)
    n_det = 0
    for rd in roads:
        if rd.get("bridge") or not rd.get("drive") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            continue
        for e in (0, -1):
            n = rd["nodes"][e]
            if n not in inner:
                continue
            P = rd["pts"] if e == 0 else rd["pts"][::-1]
            N = rd["nodes"] if e == 0 else rd["nodes"][::-1]
            back, acc, k = inner[n], 0.0, 0
            while k < len(P) - 1 and acc + math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) < back:
                acc += math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1])
                k += 1
            if k >= len(P) - 1:
                continue
            t = (back - acc) / (math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) or 1.0)
            q = (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
            _FRESH[0] -= 1
            P2, N2 = [q] + list(P[k + 1:]), [_FRESH[0]] + list(N[k + 1:])
            rd["pts"], rd["nodes"] = (P2, N2) if e == 0 else (P2[::-1], N2[::-1])
            n_det += 1
    log(f"[ramps] {n_det} side roads joining a bridge mid-span stopped short of it")
    return roads


_FRESH = [-1_500_000_000]


def _sync_fresh(roads):
    """New node ids continue below every id already in the roads: the build's phases may each load this module afresh,
    and a counter restarting at its first value gave two far-apart junctions one id (the graph joined them)."""
    _FRESH[0] = min([_FRESH[0]] + [min(rd["nodes"]) for rd in roads if rd.get("nodes")])


def _carry(roads, cut, fresh):
    """{road index: (end, metres)}: that much of the road from that end becomes part of the bridge it continues."""
    out = []
    for ri, rd in enumerate(roads):
        if ri not in cut:
            out.append(rd)
            continue
        end, m = cut[ri]
        P, N = (rd["pts"], rd["nodes"]) if end == 0 else (rd["pts"][::-1], rd["nodes"][::-1])
        acc, k = 0.0, 0
        while k < len(P) - 1:
            sl = math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1])
            if acc + sl >= m:
                break
            acc += sl
            k += 1
        t = (m - acc) / (math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) or 1.0)
        c_ = (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
        fresh[0] -= 1
        A_ = (list(P[:k + 1]) + [c_], list(N[:k + 1]) + [fresh[0]])
        B_ = ([c_] + list(P[k + 1:]), [fresh[0]] + list(N[k + 1:]))
        if end == 1:
            A_ = (A_[0][::-1], A_[1][::-1])
            B_ = (B_[0][::-1], B_[1][::-1])
        out.append(dict(rd, pts=A_[0], nodes=A_[1], bridge=True, layer=max(rd.get("layer", 0), 1)))
        out.append(dict(rd, pts=B_[0], nodes=B_[1]))
    return out


def _foot_roads(roads):
    """Bridge-end node -> [(bridge road, end)], node -> the one drivable road leaving it, node degrees."""
    ends, by_end, deg = [], {}, {}
    for ri, rd in enumerate(roads):
        if (rd.get("drive") or rd.get("walk")) and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                deg[n] = deg.get(n, 0) + 1
        if len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]) or not rd.get("drive") or rd.get("tunnel"):
            continue
        if rd.get("bridge"):
            ends += [(ri, 0), (ri, 1)]
        else:
            by_end.setdefault(rd["nodes"][0], []).append((ri, 0))
            by_end.setdefault(rd["nodes"][-1], []).append((ri, 1))
    return ends, by_end, deg


BANK = 1.0             # road ground this much below the ground further on: still in the channel / gully under the bridge


def extend_to_banks(roads, T, log=print):
    """A street bridge over a stream or a gully whose OSM end stops short of the bank: the road beyond it starts down in
    the cut (the water / quay overlay digs the channel wider than the mapped bridge), so the deck end sits in the pit
    and the road climbs out of it in a cliff.  The road straight on is carried on as bridge to where its ground stops
    being lower than the bank ahead.  Runs after the quays overlay exists, before the graph.  -> roads (new list)."""
    _sync_fresh(roads)
    ends, by_end, deg = _foot_roads(roads)
    cut, n_ext = {}, 0
    for ri, end in ends:
        rd = roads[ri]
        node = rd["nodes"][0 if end == 0 else -1]
        cands = by_end.get(node, ())
        if deg.get(node, 0) > 2 or len(cands) != 1 or cands[0][0] in cut:
            continue
        ri2, e2 = cands[0]
        W = roads[ri2]["pts"] if e2 == 0 else roads[ri2]["pts"][::-1]
        Wn = roads[ri2]["nodes"] if e2 == 0 else roads[ri2]["nodes"][::-1]
        R = _resample(W, 1.0)
        if len(R) < 4:
            continue
        g = np.array([T.hs(x, y) for x, y in R])
        L = len(R) - 1
        last = -1
        for k in range(min(L, 40)):
            ahead = g[k + 1:min(L, k + 5) + 1]             # a cliff (> 20 %) climbing out of the cut, not a hill road
            if len(ahead) and ahead.max() - g[k] > BANK:
                last = k
        if last < 0:
            continue
        m = last + 8.0                                    # over the cliff and a little onto the bank
        cw = [0.0]
        for a_, b_ in zip(W, W[1:]):
            cw.append(cw[-1] + math.hypot(b_[0] - a_[0], b_[1] - a_[1]))
        if m > cw[-1] - 2.0 or any(deg.get(n, 0) > 2 and 0.0 < c < m + 2.0 for n, c in zip(Wn, cw)):
            continue
        cut[ri2] = (e2, m)
        n_ext += 1
    log(f"[ramps] street bridges: {n_ext} ends carried on to the bank of the cut they span")
    return _carry(roads, cut, _FRESH)


FOOT_TRIM = 14.0       # a path crossing a bridge this close to a foot that is a junction crosses that road at grade


def _isect(a, b, c, d):
    rx, ry, sx, sy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return (t, u) if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0 else None


def _split_at(rd, k, t, nid):
    """Insert node nid at fraction t of segment k of road rd (in place) -> the new vertex index."""
    a, b = rd["pts"][k], rd["pts"][k + 1]
    rd["pts"].insert(k + 1, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    rd["nodes"].insert(k + 1, nid)
    return k + 1


def _junction_close(roads, node, deg, reach=12.0):
    """The one road going on from a bridge foot reaches a junction within `reach` m (no room to carry the bridge on)."""
    for rd in roads:
        if rd.get("bridge") or not rd.get("drive") or len(rd["nodes"]) != len(rd["pts"]) or len(rd["pts"]) < 2:
            continue
        if node == rd["nodes"][0]:
            far = rd["nodes"][-1]
        elif node == rd["nodes"][-1]:
            far = rd["nodes"][0]
        else:
            continue
        return _poly_len(rd["pts"]) < reach and deg.get(far, 0) > 2
    return False


def trim_bridge_feet(roads, log=print):
    """A street bridge whose foot is a junction, with a footway / cycleway crossing it just before that foot: the deck
    cannot climb over the path there (the junction holds the end down), so the path ran into the girder.  In the
    city these paths cross the street at grade where the bridge has landed: the last metres of the bridge become
    ordinary road and the path gets a crossing node on it.  -> roads (new list)."""
    deg = {}
    for rd in roads:
        if (rd.get("drive") or rd.get("walk")) and len(rd["nodes"]) == len(rd["pts"]):
            for n in rd["nodes"]:
                deg[n] = deg.get(n, 0) + 1
    paths = [(ri, rd) for ri, rd in enumerate(roads) if rd.get("walk") and not rd.get("drive") and not rd.get("bridge")
             and not rd.get("tunnel") and len(rd["pts"]) >= 2 and len(rd["nodes"]) == len(rd["pts"])]
    grid = {}
    for ri, rd in paths:
        for k, (a, b) in enumerate(zip(rd["pts"], rd["pts"][1:])):
            for cx in range(int(min(a[0], b[0]) // 32), int(max(a[0], b[0]) // 32) + 1):
                for cy in range(int(min(a[1], b[1]) // 32), int(max(a[1], b[1]) // 32) + 1):
                    grid.setdefault((cx, cy), []).append((ri, k))
    out, n_trim = [], 0
    fresh = _FRESH
    for rd in roads:
        if not rd.get("bridge") or not rd.get("drive") or len(rd["pts"]) < 2 or len(rd["nodes"]) != len(rd["pts"]):
            out.append(rd)
            continue
        L = _poly_len(rd["pts"])
        cuts = []                                         # (s along the bridge of the trim, crossings to node)
        for end in (0, 1):
            node = rd["nodes"][0 if end == 0 else -1]
            if deg.get(node, 0) <= 2 and not _junction_close(roads, node, deg):
                continue
            P = rd["pts"] if end == 0 else rd["pts"][::-1]
            s0, hits = 0.0, []
            for k, (a, b) in enumerate(zip(P, P[1:])):
                sl = math.hypot(b[0] - a[0], b[1] - a[1])
                if s0 > FOOT_TRIM:
                    break
                seen = set()
                for cx in range(int(min(a[0], b[0]) // 32), int(max(a[0], b[0]) // 32) + 1):
                    for cy in range(int(min(a[1], b[1]) // 32), int(max(a[1], b[1]) // 32) + 1):
                        for ri2, k2 in grid.get((cx, cy), ()):
                            if (ri2, k2) in seen or set(roads[ri2]["nodes"]) & set(rd["nodes"]):
                                continue
                            seen.add((ri2, k2))
                            r_ = _isect(a, b, roads[ri2]["pts"][k2], roads[ri2]["pts"][k2 + 1])
                            if r_ and s0 + r_[0] * sl < FOOT_TRIM:
                                hits.append((s0 + r_[0] * sl, ri2, k2, r_[1], roads[ri2]["w"] / 2))
                s0 += sl
            if hits:
                s_cut = max(h[0] + h[4] + 2.0 for h in hits)
                if s_cut < L - 6.0:
                    cuts.append((end, s_cut, hits))
        if len(cuts) == 2 and cuts[0][1] + cuts[1][1] > L - 6.0:
            cuts = cuts[:1]                               # both feet: only if a bridge is left between them
        if not cuts:
            out.append(rd)
            continue
        # cut the bridge: ground pieces at the trimmed feet, the bridge in the middle
        pieces = [dict(rd, pts=list(rd["pts"]), nodes=list(rd["nodes"]))]
        for end, s_cut, hits in cuts:
            cur = pieces[0] if end == 0 else pieces[-1]
            P, N = (cur["pts"], cur["nodes"]) if end == 0 else (cur["pts"][::-1], cur["nodes"][::-1])
            acc, k = 0.0, 0
            while k < len(P) - 2 and acc + math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) < s_cut:
                acc += math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1])
                k += 1
            sl = math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) or 1.0
            t = min(0.99, max(0.01, (s_cut - acc) / sl))
            c_ = (P[k][0] + (P[k + 1][0] - P[k][0]) * t, P[k][1] + (P[k + 1][1] - P[k][1]) * t)
            fresh[0] -= 1
            foot = dict(rd, pts=list(P[:k + 1]) + [c_], nodes=list(N[:k + 1]) + [fresh[0]], bridge=False, layer=0)
            rest = dict(rd, pts=[c_] + list(P[k + 1:]), nodes=[fresh[0]] + list(N[k + 1:]))
            for s, ri2, k2, u, hw in hits:                # the path's crossing node, on the ground piece and on the path
                fp = foot["pts"]
                for j in range(len(fp) - 1):
                    w = roads[ri2]
                    seg = None
                    for kk in range(len(w["pts"]) - 1):
                        r_ = _isect(fp[j], fp[j + 1], w["pts"][kk], w["pts"][kk + 1])
                        if r_:
                            seg = (kk, r_)
                            break
                    if seg:
                        fresh[0] -= 1
                        _split_at(foot, j, seg[1][0], fresh[0])
                        _split_at(w, seg[0], seg[1][1], fresh[0])
                        break
            if end == 1:
                foot = dict(foot, pts=foot["pts"][::-1], nodes=foot["nodes"][::-1])
                rest = dict(rest, pts=rest["pts"][::-1], nodes=rest["nodes"][::-1])
                pieces = pieces[:-1] + [rest, foot]
            else:
                pieces = [foot, rest] + pieces[1:]
            n_trim += 1
        out += pieces
    log(f"[ramps] street bridges: {n_trim} feet at a junction trimmed back past a path that now crosses at grade")
    return out
