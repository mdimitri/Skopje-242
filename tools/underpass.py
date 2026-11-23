"""Road underpasses: an OSM carriageway tagged tunnel=yes is dug into the ground instead of being drawn on it.

Before this the tunnel road lay on the surface: it drove straight into the buildings standing over it (the department
store over Бул. Гоце Делчев), and every street over it became a hump of a bridge.  Now, per chain of tunnel pieces:
  * the covered length runs DEPTH below the street level (4.6 m headroom + the roof), and the roads continuing from
    both mouths ramp down to it at G_RAMP (steeper, up to G_STEEP, when a junction comes sooner) in an open cutting,
    with vertical curves (a moving average of the floor),
  * the floor is written into the fine height overlay (quays.Overlay, retaining walls at the edge of the carriageway),
  * a concrete roof slab covers the tunnel at street level, with headwalls over the mouths; the roof is also a walkable
    deck (physics) so people and cars above stay on top,
  * the side walls are collision posts with a height band (only what is down in the cutting hits them), the open
    cutting has a parapet at the top, and the stretches of building walls over the tunnel stop only what is up on
    the roof (World reads "underpass" for that).

plan() runs before lift_over_tunnels (the deep part of an open cutting is crossed by bridges too), cut() after the
quays overlay exists; roof() adds the meshes / posts / decks."""
import math

import numpy as np

DEPTH = 5.4            # street level -> tunnel floor (4.4 m headroom, 1.0 m roof)
ROOF = 1.0
G_RAMP = 0.06          # ramp grade where the road allows it
G_STEEP = 0.10         # steepest ramp when a junction is close to the mouth
FULL = 12.0            # full depth continues this far out of the mouth (open cut before the ramp starts)
SMOOTH = 36            # metres of the moving average on the floor: the vertical curves at both ends of a ramp
SIDE = 1.6             # pavement / kerb either side of the carriageway inside the walls
BRIDGE_DEPTH = 3.5     # an open cutting at least this deep is crossed on a bridge (like the covered part)


def _key(p):
    return (round(p[0], 1), round(p[1], 1))


def _resample(pts, step=1.0):
    out = [tuple(pts[0])]
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(math.ceil(L / step)))
        for k in range(1, n + 1):
            out.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    return out


def _chains(tun):
    """Tunnel pieces joined end to end (shared end node) -> [[(road, reversed?), ...]]."""
    ends = {}
    for i, rd in enumerate(tun):
        ends.setdefault(rd["nodes"][0], []).append((i, 0))
        ends.setdefault(rd["nodes"][-1], []).append((i, 1))
    seen, out = set(), []
    for i in range(len(tun)):
        if i in seen:
            continue
        a, e_free = i, 0                                   # walk back to a free end
        for _ in range(len(tun)):
            nb = [q for q in ends.get(tun[a]["nodes"][0 if e_free == 0 else -1], ()) if q[0] != a]
            if len(nb) != 1 or nb[0][0] == i:
                break
            a, e_free = nb[0][0], 1 - nb[0][1]
        chain, cur, e_in = [], a, e_free
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append((tun[cur], e_in == 1))           # entered at its end 1: walk it reversed
            out_node = tun[cur]["nodes"][-1 if e_in == 0 else 0]
            nb = [q for q in ends.get(out_node, ()) if q[0] != cur and q[0] not in seen]
            cur, e_in = (nb[0][0], nb[0][1]) if len(nb) == 1 else (None, 0)
        out.append(chain)
    return out


def _ramp_road(roads, by_node, node, away, limit):
    """The road leaving a tunnel mouth (node) -> (points from the mouth, nodes, distance to the first junction)."""
    best = None
    for ri, vi in by_node.get(node, ()):
        rd = roads[ri]
        for st in (1, -1):
            j = vi + st
            if 0 <= j < len(rd["pts"]):
                dx, dy = rd["pts"][j][0] - rd["pts"][vi][0], rd["pts"][j][1] - rd["pts"][vi][1]
                c = (dx * away[0] + dy * away[1]) / (math.hypot(dx, dy) or 1e-9)
                if c > 0.5 and (best is None or c > best[0]):
                    best = (c, ri, vi, st)
    if best is None:
        return [], [], 0.0
    _, ri, vi, st = best
    pts, nds, used, tot, junction = [tuple(roads[ri]["pts"][vi])], [node], {ri}, 0.0, None
    while tot < limit:
        P, N = roads[ri]["pts"], roads[ri]["nodes"]
        j = vi + st
        while 0 <= j < len(P) and tot < limit:
            tot += math.hypot(P[j][0] - pts[-1][0], P[j][1] - pts[-1][1])
            pts.append(tuple(P[j]))
            nds.append(N[j])
            if junction is None and len(by_node.get(N[j], ())) > 2:
                junction = tot
            j += st
        if tot >= limit:
            break
        nxt = [(r_, v_) for r_, v_ in by_node.get(nds[-1], ()) if r_ not in used]
        if len(nxt) != 1:
            if junction is None:
                junction = tot
            break
        ri, vi = nxt[0]
        st = 1 if vi == 0 else -1
        used.add(ri)
    return pts, nds, tot if junction is None else junction


def plan(roads, T, log=print):
    """-> [{"pts": (k, 2), "top": street level (k,), "floor": (k,), "cover": bool (k,), "hw": .., "nodes": set}]"""
    tun = [rd for rd in roads if rd.get("tunnel") and rd["drive"] and len(rd["pts"]) >= 2 and len(rd["nodes"]) == len(rd["pts"])]
    if not tun:
        return []
    by_node = {}
    for ri, rd in enumerate(roads):
        if rd.get("tunnel") or rd["bridge"] or not rd["drive"] or len(rd["nodes"]) != len(rd["pts"]):
            continue
        for vi, nd in enumerate(rd["nodes"]):
            by_node.setdefault(nd, []).append((ri, vi))
    out = []
    for chain in _chains(tun):
        C, nodes = [], set()
        for rd, rev in chain:
            pts = rd["pts"][::-1] if rev else rd["pts"]
            C += pts if not C else pts[1:]
            nodes.update(rd["nodes"])
        n_in = (chain[0][0]["nodes"][-1] if chain[0][1] else chain[0][0]["nodes"][0],
                chain[-1][0]["nodes"][0] if chain[-1][1] else chain[-1][0]["nodes"][-1])
        hw = max(rd["w"] for rd, _ in chain) / 2 + SIDE
        Pc = _resample(C)
        Lc = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(Pc, Pc[1:]))
        if Lc < 8:
            continue
        ramps = []
        for end in (0, 1):
            p, q = (Pc[0], Pc[min(3, len(Pc) - 1)]) if end == 0 else (Pc[-1], Pc[max(0, len(Pc) - 4)])
            n_ = math.hypot(p[0] - q[0], p[1] - q[1]) or 1.0
            A, An, room = _ramp_road(roads, by_node, n_in[end], ((p[0] - q[0]) / n_, (p[1] - q[1]) / n_),
                                     FULL + DEPTH / G_RAMP + SMOOTH)
            g = min(G_STEEP, max(G_RAMP, DEPTH / max(1.0, room - FULL))) if A else G_STEEP
            ramps.append((_resample(A) if len(A) >= 2 else [tuple(p)], An, g))
            nodes.update(An)
        A0 = ramps[0][0][::-1]
        X = np.array(A0[:-1] + Pc + ramps[1][0][1:], np.float64)
        n0, n1 = len(A0) - 1, len(A0) - 1 + len(Pc) - 1          # mouths
        s = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(X, axis=0).T))])
        top = np.array([T.hs(x, y) for x, y in X])
        d_out = np.where(np.arange(len(X)) < n0, s[n0] - s, np.where(np.arange(len(X)) > n1, s - s[n1], 0.0))
        g = np.where(np.arange(len(X)) < n0, ramps[0][2], ramps[1][2])
        depth = np.clip(DEPTH - np.maximum(0.0, d_out - FULL) * g, 0.0, DEPTH)
        pad = SMOOTH
        ext = np.concatenate([np.full(pad, depth[0]), depth, np.full(pad, depth[-1])])
        depth = np.convolve(ext, np.ones(pad) / pad, mode="same")[pad:pad + len(depth)]
        depth[n0:n1 + 1] = DEPTH
        floor = top - depth
        fl = np.concatenate([np.full(pad, floor[0]), floor, np.full(pad, floor[-1])])   # smooth the floor along its length
        floor = np.minimum(np.convolve(fl, np.ones(8) / 8, mode="same")[pad:pad + len(floor)], top)
        cover = np.zeros(len(X), bool)
        cover[n0:n1 + 1] = True
        out.append({"pts": X, "top": top, "floor": floor, "cover": cover, "hw": hw, "nodes": nodes})
    log(f"[underpass] {len(out)} road tunnels dug in: "
        + ", ".join(f"{int(p['cover'].sum())} m covered, {len(p['pts']) - int(p['cover'].sum())} m of ramps" for p in out[:6]))
    return out


def bridge_lines(plans):
    """The deep open parts of the cuttings, as pseudo tunnel roads for lift_over_tunnels (crossings there become bridges)."""
    out = []
    for p in plans:
        deep = (~p["cover"]) & (p["top"] - p["floor"] >= BRIDGE_DEPTH)
        k = 0
        while k < len(deep):
            if deep[k]:
                j = k
                while j + 1 < len(deep) and deep[j + 1]:
                    j += 1
                if j > k:
                    out.append({"pts": [tuple(v) for v in p["pts"][k:j + 1]], "nodes": list(p["nodes"]), "w": 2 * p["hw"]})
                k = j + 1
            else:
                k += 1
    return out


def grid(plans, cell=16.0):
    """8 m-ish lookup of the cutting corridors (where the ground is dug down at least 1 m)."""
    g = {}
    for p in plans:
        X, hw = p["pts"], p["hw"]
        dug = p["top"] - p["floor"] >= 1.0
        for k in range(len(X) - 1):
            if not (dug[k] or dug[k + 1]):
                continue
            (ax, ay), (bx, by) = X[k], X[k + 1]
            for cx in range(int((min(ax, bx) - hw) // cell), int((max(ax, bx) + hw) // cell) + 1):
                for cy in range(int((min(ay, by) - hw) // cell), int((max(ay, by) + hw) // cell) + 1):
                    g.setdefault((cx, cy), []).append((ax, ay, bx, by, hw))
    return g


def inside(g, x, y, cell=16.0):
    for ax, ay, bx, by, hw in g.get((int(x // cell), int(y // cell)), ()):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
        if math.hypot(x - ax - dx * t, y - ay - dy * t) <= hw + 0.5:
            return True
    return False


def street_grid(plans, cell=16.0):
    """Lookup of the covered stretches (the roof slab) with the street level over them: cell -> [(ax, ay, bx, by, hw, top_a, top_b)]."""
    g = {}
    for p in plans:
        X, hw, top, cov = p["pts"], p["hw"] + 1.5, p["top"], p["cover"]       # + the dug margin outside the retaining walls
        for k in range(len(X) - 1):
            if not (cov[k] and cov[k + 1]):
                continue
            (ax, ay), (bx, by) = X[k], X[k + 1]
            for cx in range(int((min(ax, bx) - hw) // cell), int((max(ax, bx) + hw) // cell) + 1):
                for cy in range(int((min(ay, by) - hw) // cell), int((max(ay, by) + hw) // cell) + 1):
                    g.setdefault((cx, cy), []).append((ax, ay, bx, by, hw + 0.3, float(top[k]), float(top[k + 1])))
    return g


def street(g, x, y, cell=16.0):
    """Street level over a covered stretch at (x, y), or None when (x, y) is not over one."""
    for ax, ay, bx, by, hw, ta, tb in g.get((int(x // cell), int(y // cell)), ()):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
        if math.hypot(x - ax - dx * t, y - ay - dy * t) <= hw:
            return ta + (tb - ta) * t
    return None


class StreetTerrain:
    """The terrain as buildings see it: over a covered underpass the ground is the roof slab (the street), not the dug floor, so a
    building standing over the road sits on the slab and leaves the road open below it instead of walling it in."""

    def __init__(self, T, g):
        self._T, self._g = T, g

    def __getattr__(self, name):
        if name in ("_T", "_g"):                  # not set yet (unpickling in a worker)
            raise AttributeError(name)
        return getattr(self._T, name)

    def hs(self, x, y):
        v = self._T.hs(x, y)
        st = street(self._g, x, y)
        return v if st is None else st

    def h(self, x, y):
        v = self._T.h(x, y)
        if np.ndim(v) == 0:
            return self.hs(x, y) if street(self._g, x, y) is not None else v
        v = np.array(v, np.float64)
        for i, (px, py) in enumerate(zip(np.ravel(x), np.ravel(y))):
            st = street(self._g, px, py)
            if st is not None:
                v.flat[i] = st
        return v


def open_under_decks(plans, edges, extra=2.5, min_run=8.0):
    """A covered stretch that is only a street crossing over the cutting is carried by that street's deck: the roof
    slab is dropped where a driven deck passes (its footprint + `extra`), and so are covered leftovers shorter than
    `min_run`.  -> metres opened."""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    feet = [LineString(e["pts"]).buffer(e["w"] / 2 + 2.4 + extra) for e in edges
            if e["drive"] and e["bridge"] and len(e["pts"]) >= 2]
    if not feet:
        return 0.0
    U = unary_union(feet)
    opened = 0.0
    for p in plans:
        X, cov = np.asarray(p["pts"]), np.asarray(p["cover"], bool).copy()
        under = np.zeros(len(cov), bool)
        for k in np.nonzero(cov)[0]:
            if U.contains(Point(X[k][0], X[k][1])):
                cov[k] = False
                under[k] = True
                opened += 1.0
        k = 0
        while k < len(cov):                                   # leftovers too short to be a tunnel
            if cov[k]:
                j = k
                while j < len(cov) and cov[j]:
                    j += 1
                if np.hypot(*(X[j - 1] - X[k])) < min_run:
                    cov[k:j] = False
                    under[k:j] = True
                    opened += j - k
                k = j
            else:
                k += 1
        p["cover"], p["under_deck"] = cov, under             # walls there stop under the deck slab, no parapet
    return opened


def cut(T, plans, hx, hy):
    """Dig the floors into T's fine overlay (vertical walls at hw).  -> posts changed."""
    import quays
    import ramps
    S = quays.QSTEP
    want = {}
    for p in plans:
        X, fl, hw = p["pts"], p["floor"], p["hw"]
        for k in range(len(X) - 1):
            (ax, ay), (bx, by) = X[k], X[k + 1]
            x0, x1 = min(ax, bx) - hw - 3, max(ax, bx) + hw + 3
            y0, y1 = min(ay, by) - hw - 3, max(ay, by) + hw + 3
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            for px in range(int(math.floor((x0 + hx) / S)), int(math.ceil((x1 + hx) / S)) + 1):
                x = px * S - hx
                for py in range(int(math.floor((y0 + hy) / S)), int(math.ceil((y1 + hy) / S)) + 1):
                    y = py * S - hy
                    t = ((x - ax) * dx + (y - ay) * dy) / l2
                    tc = min(1.0, max(0.0, t))
                    if math.hypot(x - ax - dx * tc, y - ay - dy * tc) > hw + 1.2:          # the floor runs under the retaining wall (at hw + 0.3)
                        continue
                    if p.get("keep") and p["keep"](x, y):            # (a railway's cutting stops at the street beside it)
                        continue
                    f = fl[k] + (fl[k + 1] - fl[k]) * tc
                    if f < want.get((px, py), 1e9):
                        want[(px, py)] = f
    add = {}
    for (px, py), f in want.items():
        v = f - T.hs(px * S - hx, py * S - hy)
        if v < -0.02:
            add[(px, py)] = v
    return ramps.merge_posts(T, add, hx, hy) if add else 0


def _slab(pos, a, b, c, d):
    pos += [a, b, c, a, c, d]


def roof(plans, add_abs, chunk_of, mat, T=None):
    """Roof slabs, headwalls and wall posts.  -> (posts, decks, underpass records for the World)."""
    posts, decks, recs = [], [], []
    for p in plans:
        X, top, fl, cov, hw = p["pts"], p["top"], p["floor"], p["cover"], p["hw"]
        n = len(X)
        tang = np.gradient(X, axis=0)
        tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
        nrm = np.stack([-tang[:, 1], tang[:, 0]], 1)
        L_, R_ = X + nrm * (hw + 0.3), X - nrm * (hw + 0.3)
        cov = np.asarray(cov, bool)
        ud = np.asarray(p.get("under_deck", np.zeros(n, bool)), bool)
        runs, k = [], 0                                        # covered runs (open_under_decks may leave none, or split one)
        while k < n:
            if cov[k]:
                j = k
                while j + 1 < n and cov[j + 1]:
                    j += 1
                runs.append((k, j))
                k = j + 1
            else:
                k += 1
        # with T: a wall whose outside is dug as well (two carriageways in one cutting) is left out, and the others
        # get a coping strip over the 1-2 m the fine grid needs to climb back to the ground behind the wall
        sides = []
        for S_, sg in ((L_, 1.0), (R_, -1.0)):
            if T is None:
                sides.append((S_, np.zeros(n, bool), None))
                continue
            far = S_ + nrm * sg * 1.6
            ground = S_ + nrm * sg * 2.6
            hout = np.array([T.hs(x, y) for x, y in far])
            hgr = np.array([T.hs(x, y) for x, y in ground])
            sides.append((S_, (np.asarray(top) - hout) > 1.0, (S_ + nrm * sg * 2.2, hgr)))
        by_chunk = {}
        for k in (k for k0, k1 in runs for k in range(k0, k1)):    # roof: top at street level, underside ROOF lower
            for (ya, yb, up) in ((top[k], top[k + 1], True), (top[k] - ROOF, top[k + 1] - ROOF, False)):
                a = (L_[k][0], ya, L_[k][1])
                b = (R_[k][0], ya, R_[k][1])
                c = (R_[k + 1][0], yb, R_[k + 1][1])
                d = (L_[k + 1][0], yb, L_[k + 1][1])
                _slab(by_chunk.setdefault(chunk_of(X[k][0], X[k][1]), []), *((a, b, c, d) if up else (a, d, c, b)))
        for k in range(n - 1):                                 # retaining walls along both sides (+ a parapet on the open part)
            if min(top[k] - fl[k], top[k + 1] - fl[k + 1]) < 0.25:
                continue
            q = by_chunk.setdefault(chunk_of(X[k][0], X[k][1]), [])
            ya0, yb0 = fl[k] - 0.3, fl[k + 1] - 0.3
            ya1 = top[k] - (ROOF if cov[k] or ud[k] else -1.0)
            yb1 = top[k + 1] - (ROOF if cov[k + 1] or ud[k + 1] else -1.0)
            for S_, opn, cap in sides:
                if opn[k] and opn[k + 1]:
                    continue
                a_ = (S_[k][0], ya0, S_[k][1])
                b_ = (S_[k + 1][0], yb0, S_[k + 1][1])
                c_ = (S_[k + 1][0], yb1, S_[k + 1][1])
                d_ = (S_[k][0], ya1, S_[k][1])
                _slab(q, a_, b_, c_, d_)
                _slab(q, a_, d_, c_, b_)
                if cap is not None and not cov[k]:
                    C_, hg = cap
                    ya2, yb2 = max(top[k], hg[k]) + 0.03, max(top[k + 1], hg[k + 1]) + 0.03
                    a2, b2 = (S_[k][0], ya2, S_[k][1]), (S_[k + 1][0], yb2, S_[k + 1][1])
                    c2, d2 = (C_[k + 1][0], yb2, C_[k + 1][1]), (C_[k][0], ya2, C_[k][1])
                    _slab(q, a2, b2, c2, d2)
                    _slab(q, a2, d2, c2, b2)
        for k in (k for r in runs for k in r):                # headwalls over the mouths: roof underside -> street level
            q = by_chunk.setdefault(chunk_of(X[k][0], X[k][1]), [])
            for (y0, y1) in ((top[k] - ROOF, top[k] + 0.9),):
                a = (L_[k][0], y0, L_[k][1])
                b = (R_[k][0], y0, R_[k][1])
                _slab(q, a, b, (b[0], y1, b[2]), (a[0], y1, a[2]))
                _slab(q, b, a, (a[0], y1, a[2]), (b[0], y1, b[2]))
        for key, tri in by_chunk.items():
            pos = np.array(tri, np.float32)
            nr = np.cross(pos[1::3] - pos[0::3], pos[2::3] - pos[0::3])
            nr /= np.linalg.norm(nr, axis=1, keepdims=True) + 1e-9
            lum = np.repeat(0.62 + 0.38 * np.abs(nr[:, 1]), 3)
            col = np.zeros((len(pos), 4), np.uint8)
            col[:, 0] = (150 * lum).astype(np.uint8)
            col[:, 1] = (148 * lum).astype(np.uint8)
            col[:, 2] = (142 * lum).astype(np.uint8)
            col[:, 3] = 255
            uv = np.zeros((len(pos), 2), np.float32)
            add_abs(key, mat, pos, uv, col)
        # the roof is a walkable deck; the cutting's walls stop what is down in it, a parapet guards the open part
        for k0, k1 in runs:
            decks.append({"pts": [(float(x), float(y)) for x, y in X[k0:k1 + 1]], "h": [float(v) for v in top[k0:k1 + 1]],
                          "hw": float(hw + 0.3)})
        for k in range(n):
            depth = top[k] - fl[k]
            if depth < 0.8:
                continue
            for side, opn, _cap in sides:
                if opn[k]:
                    continue
                x, y = float(side[k][0]), float(side[k][1])
                if cov[k] or ud[k]:
                    posts.append((x, y, 0.35, float(fl[k] - 1.0), float(top[k] - ROOF)))
                else:
                    posts.append((x, y, 0.35, float(fl[k] - 1.0), float(top[k] + 1.1)))
        for k0, k1 in runs:
            recs.append({"pts": [(float(x), float(y)) for x, y in X[k0:k1 + 1]], "hw": float(hw + 0.3),
                         "roof": [float(v) for v in top[k0:k1 + 1]]})
    return posts, decks, recs
