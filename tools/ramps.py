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
A_MAX = 140.0          # longest approach embankment (m)
W = 24.0               # vertical curve: moving average window (m)
LIFT_MIN = 1.2         # a deck point this far above the ground is "elevated": its height is kept (clearance)
SIDE = 0.5             # embankment side slope (rise per metre)
ROAD_FLANK = 0.07      # ... where another street runs into it
JOIN = 0.6             # deck ends / road vertices this close are the same point


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


def _approach(roads, rindex, p, away, limit):
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
            if c > 0.5 and (best is None or c > best[0]):
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
        end = out[-1]                                   # road ended: go on only if exactly one other road continues here
        nxt = [(r_, v_) for r_, v_ in _near(rindex, end) if r_ not in used and (v_ == 0 or v_ == len(roads[r_]["pts"]) - 1)
               and math.hypot(roads[r_]["pts"][v_][0] - end[0], roads[r_]["pts"][v_][1] - end[1]) <= JOIN]
        if len(nxt) != 1:
            break
        ri, vi = nxt[0]
        step = 1 if vi == 0 else -1
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
    hw + 1 m of the centreline and falls at SIDE beyond; `blocked(x, y)` (buildings) posts stay as they are."""
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
    add = {}
    for P, lift, hw in items:
        if lift.max() < 0.03:
            continue
        reach = hw + 1.0 + float(lift.max()) / ROAD_FLANK + 1.0
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
            v = li - np.maximum(0.0, d - hw - 1.0) * slope
            best = np.maximum(best, v)
        for (iy, ix) in zip(*np.nonzero(best > 0.005)):
            key = (int(gx[ix]), int(gy[iy]))
            add[key] = max(add.get(key, 0.0), float(best[iy, ix]))
    n = 0
    for (px, py), v in add.items():
        x, y = px * S - hx, py * S - hy
        if blocked(x, y):
            continue
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


def smooth(T, decks, roads, blocked, hx, hy, log=print):
    """See the module docstring.  decks: {road index: terrain.Deck} (changed in place)."""
    dlist = [d for d in decks.values() if d.hw >= 3.0]          # carriageways (footbridges keep their steps / grades)
    rindex = {}
    for ri, rd in enumerate(roads):
        if rd.get("bridge") or not rd.get("drive") or len(rd["pts"]) < 2:
            continue
        for vi, p in enumerate(rd["pts"]):
            rindex.setdefault(_key(p), []).append((ri, vi))
    items, stats = [], {"chains": 0, "approaches": 0, "short": 0, "lifted_m": 0.0}
    for chain in _chains(dlist):
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
        app = []
        for end in (0, 1):
            p = P[0] if end == 0 else P[-1]
            q = P[min(3, Ld - 1)] if end == 0 else P[max(0, Ld - 4)]
            away = (p[0] - q[0], p[1] - q[1])
            n_ = math.hypot(*away) or 1.0
            A, hw = _approach(roads, rindex, p, (away[0] / n_, away[1] / n_), A_MAX)
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
        # the grade each side needs: the requirement must come down to the ground by the end of the approach
        ri_ = np.nonzero(req > -1e8)[0]
        first, last = ri_[0], ri_[-1]
        g0 = max(G_MAX, (req[first] - t[0]) / max(1.0, s[first] - s[0]))
        g1 = max(G_MAX, (req[last] - t[-1]) / max(1.0, s[-1] - s[last]))
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
        # back to the deck pieces
        newH = prof[n0:n0 + Ld]
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
        for A, lo, hi in ((A0, 0, n0 + 1), (A1, n0 + Ld - 1, len(X))):
            if len(A) >= 2:
                items.append((X[lo:hi], lift[lo:hi], app[0][1] if lo == 0 else app[1][1]))
                stats["approaches"] += 1
                stats["lifted_m"] = max(stats["lifted_m"], float(lift[lo:hi].max()))
        stats["chains"] += 1
    segs = {}                                                   # streets for the flanks, by 64 m cell
    for rd in roads:
        if rd.get("bridge") or not rd.get("drive"):
            continue
        for a, b in zip(rd["pts"], rd["pts"][1:]):
            for cx in range(int(min(a[0], b[0]) // 64), int(max(a[0], b[0]) // 64) + 1):
                for cy in range(int(min(a[1], b[1]) // 64), int(max(a[1], b[1]) // 64) + 1):
                    segs.setdefault((cx, cy), []).append((a[0], a[1], b[0], b[1], rd["w"] / 2))
    stats["posts"] = _lift_overlay(T, items, blocked, hx, hy, segs)
    log(f"[ramps] {stats['chains']} bridge chains smoothed, {stats['approaches']} approach embankments "
        f"(highest {stats['lifted_m']:.1f} m, {stats['posts']} posts), {stats['short']} approaches too short for "
        f"{G_MAX:.0%} (steeper there)")
    return stats
