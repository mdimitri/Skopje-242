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
        if not cleared and c < 4.0:
            continue                                          # a path near a deck still at grade: the quays handle those
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
        if any(math.hypot(q[0] - e[0], q[1] - e[1]) < 3.0 for q in ((ax, ay), (bx, by)) for e in (e0, e1)):
            continue
        best = max(best, c)
        if ways is not None:
            ways.add(ri)
    return best


def smooth(T, decks, roads, blocked, hx, hy, log=print):
    """See the module docstring.  decks: {road index: terrain.Deck} (changed in place)."""
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
    items, stats = [], {"chains": 0, "approaches": 0, "short": 0, "lifted_m": 0.0, "no_room": 0, "ends_eased": 0}
    done = []
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
        app, side_app = [], []
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
        for k in range(n0, n0 + Ld):                          # a street / path crossing under the deck anywhere (also within 24 m
            c = _under(ugrid, X[k], X[min(k + 2, len(X) - 1)] - X[max(k - 2, 0)], P[0], P[-1],   # of an end, where make_deck
                       cleared=H[k - n0] - t[k] >= 2.0)      # kept no clearance): full headroom + the slab
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
        done.append((chain, P, own, newH))
        for A, lo, hi in ((A0, 0, n0 + 1), (A1, n0 + Ld - 1, len(X))):
            if len(A) >= 2:
                items.append((X[lo:hi], lift[lo:hi], app[0][1] if lo == 0 else app[1][1]))
                stats["approaches"] += 1
                stats["lifted_m"] = max(stats["lifted_m"], float(lift[lo:hi].max()))
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
                        for ri in ws:
                            kg.setdefault((cx, cy), set()).add((p[0], p[1], ri))

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
            if math.hypot(x - ax - dx * t, y - ay - dy * t) < hw:
                mine.add(ri)
        dmin = min((math.hypot(x - px, y - py) for px, py, ri in cr if ri in mine), default=None)
        return False if dmin is None else max(0.0, (dmin - 8.0) * G_MAX)
    stats["posts"] = _lift_overlay(T, items, lambda x, y, v: True if blocked(x, y) else clogs(x, y, v), hx, hy, segs)
    for chain, P, own, newH in done:                            # an embankment that could not be raised (a building, a way
        s_ = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])   # passing under another deck) leaves the deck
        L_ = s_[-1]                                             # end hanging over the road: ease the deck down to the ground there
        corr = np.zeros(len(P))
        for end, q in ((0, P[0]), (1, P[-1])):
            dlt = (newH[0] if end == 0 else newH[-1]) - T.hs(q[0], q[1])
            if abs(dlt) <= END_TOL:
                continue
            R_ = max(8.0, abs(dlt) / G_EASE)
            dist = s_ if end == 0 else L_ - s_
            corr += dlt * np.clip(1.0 - dist / R_, 0.0, 1.0)
            stats["ends_eased"] += 1
        if corr.any():
            _write(dlist, chain, P, own, newH - corr)
    log(f"[ramps] {stats['chains']} bridge chains smoothed, {stats['approaches']} approach embankments "
        f"(highest {stats['lifted_m']:.1f} m, {stats['posts']} posts), {stats['short']} approaches too short for "
        f"{G_MAX:.0%} (steeper there), {stats['no_room']} deck points over a way left low (no room to climb), "
        f"{stats['ends_eased']} deck ends eased onto ground that could not be raised")
    return stats


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
