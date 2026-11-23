"""Road graph clean-up before the road mesh is built (run after lanefix): carriageways of a dual road never overlap
(lanes are cut so a median at least MEDIAN wide fits between them), and short stray segments take the lane count and
width of their longer neighbours (no narrow-then-widen bumps)."""
import collections
import math
import os

import numpy as np

from roadwidth import lane_count

MEDIAN = 3.5
LANE = 3.5


def _total(e):
    return lane_count(e) * (1 if e["ow"] else 2)


def _samples(e):
    P = np.asarray(e["pts"], float)
    out = []
    for k in range(len(P) - 1):
        v = P[k + 1] - P[k]
        ln = float(np.hypot(*v))
        if ln < 1e-6:
            continue
        for t in (0.25, 0.75):
            out.append((P[k] + v * t, v / ln))
    return out


def dual_carriageways(edges):
    ow = [i for i, e in enumerate(edges) if e["drive"] and e["ow"] and e["cls"] != "service" and not e["bridge"] and e["len"] > 8]
    cell = collections.defaultdict(list)
    S = {}
    for i in ow:
        S[i] = _samples(edges[i])
        for p, u in S[i]:
            cell[(int(p[0] // 30), int(p[1] // 30))].append((i, p, u))
    best = {}
    for i in ow:
        for p, u in S[i]:
            cx, cy = int(p[0] // 30), int(p[1] // 30)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j, q, w in cell.get((cx + dx, cy + dy), ()):
                        if j == i or float(u @ w) > -0.85:
                            continue
                        dist = float(np.hypot(*(q - p)))
                        if abs(float((q - p) @ u)) > dist * 0.5 or dist >= 40:
                            continue
                        best[i] = min(best.get(i, 99.0), dist)
    cut = 0
    for i, dd in best.items():
        e = edges[i]
        lanes = e["lanes"] or max(1, round(e["w"] / LANE))
        nl = max(1, min(lanes, int((dd - MEDIAN) // LANE)))
        if nl < lanes:
            e["lanes"], e["w"] = nl, nl * LANE
            e["turn"] = ("", "")
            cut += 1
    return cut


def harmonise(edges, short=150.0):
    at = collections.defaultdict(list)
    for i, e in enumerate(edges):
        if e["drive"] and not e["bridge"]:
            at[e["a"]].append(i)
            at[e["b"]].append(i)
    n = 0
    for _ in range(6):
        ch = 0
        for L in at.values():
            if len(L) != 2:
                continue
            a, b = edges[L[0]], edges[L[1]]
            if a["cls"] != b["cls"] or a["ow"] != b["ow"] or _total(a) == _total(b):
                continue
            s, l = (a, b) if a["len"] < b["len"] else (b, a)
            if s["len"] < short:
                for f in ("w", "lanes", "directional_lanes", "turn"):
                    if f in l:
                        s[f] = l[f]
                ch += 1
        n += ch
        if not ch:
            break
    return n


def bridge_lanes(edges):
    """A bridge carries as many lanes per direction as the road that continues onto it (never a 1-lane road turning
    into a 3-lane deck): every edge of a bridge takes the approach road's lane count.  -> number of edges changed."""
    import roadwidth
    at = {}
    for e in edges:
        if e["drive"] and not e["bridge"]:
            at.setdefault(e["a"], []).append(e)
            at.setdefault(e["b"], []).append(e)
    groups = {}
    for e in edges:
        if e["drive"] and e["bridge"]:
            groups.setdefault(e["road"], []).append(e)
    changed = 0
    for G in groups.values():
        cnt = {}
        for e in G:
            for n in (e["a"], e["b"]):
                cnt[n] = cnt.get(n, 0) + 1
        ends = [n for n, c in cnt.items() if c == 1]
        cand = [roadwidth.lane_count(a, 1) for n in ends for a in at.get(n, []) if a["ow"] == G[0]["ow"] and a["cls"] == G[0]["cls"]]
        if not cand:
            continue
        per = max(cand)
        for e in G:
            want = per if e["ow"] else 2 * per
            if e.get("lanes") != want or e.get("directional_lanes"):
                e["lanes"], e["directional_lanes"] = want, None
                changed += 1
    return changed


def _hw(e):
    return lane_count(e) * LANE / 2 if e["ow"] else lane_count(e) * LANE


def _cum_of(pts):
    cum = [0.0]
    for k in range(1, len(pts)):
        cum.append(cum[-1] + float(np.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])))
    return cum


def _ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def merge_junctions(edges, kerb=7.0):
    """Clusters of junction nodes joined by links shorter than the junction they form become one junction node.

    No fixed distance: a link merges when it is short compared with the paved area its junction covers anyway
    (the widest roads meeting at either end plus a kerb radius each), weighted smoothly (a logistic score, links
    on bridges never).  The arms are not snapped: each arm's centreline is pulled to the new centre with a weight
    that eases from 1 at the junction to 0 over a distance proportional to how far it moves, so every arm keeps a
    smooth line.  Walkways ending at a merged node follow the same way.  Lane counts, one-way flags and turn tags
    are untouched; the drivable links inside the cluster are removed (the cluster is one junction for traffic too).
    -> (clusters merged, links removed)."""
    at = collections.defaultdict(list)
    for i, e in enumerate(edges):
        if e["drive"]:
            at[e["a"]].append(i)
            at[e["b"]].append(i)
    J = {n for n, L in at.items() if len(L) >= 3}
    size = {n: max(_hw(edges[i]) for i in at[n]) for n in J}
    parent = {n: n for n in J}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n
    links = []
    chains, loops = [], []
    seen = set()
    for n0 in J:                                               # links: chains of edges through plain (2-edge) nodes
        for i0 in at[n0]:
            chain, n, i, L = [], n0, i0, 0.0
            while True:
                e = edges[i]
                if not e["drive"] or e["bridge"] or i in chain:
                    chain = None
                    break
                chain.append(i)
                L += e["len"]
                n = e["b"] if e["a"] == n else e["a"]
                if n in J or len(at[n]) != 2 or L > 120.0:
                    break
                i = at[n][0] if at[n][1] == i else at[n][1]
            if chain and n == n0 and L < 60.0:                    # a U-turn / slip loop back into the same junction
                links += chain
                loops.append((n0, chain))
                continue
            if not chain or n not in J or n == n0 or frozenset(chain) in seen:
                continue
            seen.add(frozenset(chain))
            reach = size[n0] + size[n] + 2 * kerb              # what the two junctions pave anyway
            score = 1.0 / (1.0 + np.exp((L - reach) / (0.15 * reach)))
            if score > 0.5:
                links += chain
                chains.append((n0, chain))
                parent[find(n0)] = find(n)
    groups = collections.defaultdict(list)
    for n in J:
        groups[find(n)].append(n)
    groups = {r: ns for r, ns in groups.items() if len(ns) > 1}
    if not groups:
        return 0, 0
    pos0 = {}
    for e in edges:
        pos0.setdefault(e["a"], e["pts"][0])
        pos0.setdefault(e["b"], e["pts"][-1])
    # a cluster whose members would have to move far to meet is not one junction (the arm pull would drag real
    # geometry): such groups stay as they were
    MOVE = float(os.environ.get("SK242_MOVE", 22.0))
    far = set()
    for r, ns in groups.items():
        wsum = sum(size[n] for n in ns)
        cx = sum(pos0[n][0] * size[n] for n in ns) / wsum
        cy = sum(pos0[n][1] * size[n] for n in ns) / wsum
        if max(np.hypot(pos0[n][0] - cx, pos0[n][1] - cy) for n in ns) > MOVE:
            far.add(r)
    groups = {r: ns for r, ns in groups.items() if r not in far}
    if not groups:
        return 0, 0
    root = {n: r for r, ns in groups.items() for n in ns}
    inner = {i for n0, ch in chains if n0 in root for i in ch} | {i for _n0, ch in loops for i in ch}
    # centre: node positions weighted by how much road meets there
    pos = {}
    for e in edges:
        pos.setdefault(e["a"], e["pts"][0])
        pos.setdefault(e["b"], e["pts"][-1])
    centre = {}
    for r, ns in groups.items():
        wsum = sum(size[n] for n in ns)
        centre[r] = (sum(pos[n][0] * size[n] for n in ns) / wsum, sum(pos[n][1] * size[n] for n in ns) / wsum)
    for i, e in enumerate(edges):
        if i in inner:
            continue
        pts = [tuple(p) for p in e["pts"]]
        moved = False
        for end in (0, 1):
            n = e["a"] if end == 0 else e["b"]
            if n not in root:
                continue
            r = root[n]
            c = centre[r]
            P = pts if end == 0 else pts[::-1]
            dx, dy = c[0] - P[0][0], c[1] - P[0][1]
            dist = float(np.hypot(dx, dy))
            span = min(0.8 * _cum_of(P)[-1], 4.0 * dist + 15.0)
            cum = _cum_of(P)
            P = [(p[0] + dx * (1 - _ease(s / span if span > 0 else 1)), p[1] + dy * (1 - _ease(s / span if span > 0 else 1))) for p, s in zip(P, cum)]
            pts = P if end == 0 else P[::-1]
            e["a" if end == 0 else "b"] = r
            moved = True
        if moved:
            e["pts"] = pts
            e["cum"] = _cum_of(pts)
            e["len"] = e["cum"][-1]
    span_of = {r: max(size[n] for n in ns) * 2 + 4 * kerb for r, ns in groups.items()}
    # a slip lane or U-turn link whose both ends fell into the same junction now lies inside it: gone with the rest
    keep = [e for i, e in enumerate(edges) if i not in inner and not (e["a"] == e["b"] and e["a"] in span_of and e["len"] < 2 * span_of[e["a"]])]
    edges[:] = keep
    return len(groups), len(inner)


def _resample(pts, step=2.0):
    cum = _cum_of(pts)
    L = cum[-1]
    n = max(2, int(L / step) + 1)
    P = np.asarray(pts, float)
    ss = np.linspace(0.0, L, n)
    x = np.interp(ss, cum, P[:, 0])
    y = np.interp(ss, cum, P[:, 1])
    return list(zip(x.tolist(), y.tolist())), ss


def _dir_at(P, S, look):
    j = int(np.searchsorted(S, look))
    j = min(max(1, j), len(P) - 1)
    u = P[j] - P[0]
    ln = float(np.hypot(*u))
    return (u / ln) if ln > 1e-6 else None


def straighten_arms(edges):
    """Every road leaves a junction on a straight approach (a real junction is built square to its arms): the first
    stretch of each arm is blended from a straight line along the arm's general direction back into the real line.
    The two carriageways of a dual road approach side by side at their real spacing, so the median runs right up to
    the junction box and only the last metres inside the box swing in to the junction point.  Weights ease smoothly;
    reach grows with the edge's length, never a cut-off.  Junction points do not move.  -> arm ends straightened."""
    deg = collections.Counter()
    at = collections.defaultdict(list)
    for i, e in enumerate(edges):
        if e["drive"]:
            deg[e["a"]] += 1
            deg[e["b"]] += 1
            at[e["a"]].append((i, 0))
            at[e["b"]].append((i, 1))
    rs = {}
    for i, e in enumerate(edges):
        if e["drive"] and not e["bridge"] and e["len"] >= 6:
            rs[i] = _resample([tuple(p) for p in e["pts"]])
    # lateral offset for dual-carriageway arms: (edge, end) -> (axis u, offset along v, box radius)
    lateral = {}
    for node, L in at.items():
        if deg[node] < 3:
            continue
        info = []
        for i, k in L:
            if i not in rs or not edges[i]["ow"]:
                continue
            P, ss = rs[i]
            Q = np.asarray(P, float)
            R = Q if k == 0 else Q[::-1]
            S = ss if k == 0 else (ss[-1] - ss)[::-1]
            u = _dir_at(R, S, min(30.0, 0.6 * S[-1]))
            if u is None:
                continue
            p30 = R[min(len(R) - 1, int(np.searchsorted(S, min(30.0, 0.6 * S[-1]))))]
            info.append((i, k, u, p30, "in" if k == 1 else "out"))
        box = max(_hw(edges[i]) for i, _k in L) + 6.0
        used = set()
        cand = []
        for x in range(len(info)):
            for y in range(x + 1, len(info)):
                a, b = info[x], info[y]
                if a[4] == b[4]:
                    continue
                cos = float(a[2] @ b[2])
                gap = float(np.hypot(*(a[3] - b[3])))
                cost = (1 - cos) * 20 + gap / 30.0
                if cost < 1.5:
                    cand.append((cost, x, y))
        for _c, x, y in sorted(cand):
            if x in used or y in used:
                continue
            used |= {x, y}
            a, b = info[x], info[y]
            u = a[2] + b[2]
            u = u / (float(np.hypot(*u)) or 1.0)
            v = np.array([-u[1], u[0]])
            node_p = np.asarray(edges[a[0]]["pts"][0 if a[1] == 0 else -1], float)
            for (i, k, _u, p30, _kind) in (a, b):
                off = float((p30 - node_p) @ v)
                lateral[(i, k)] = (u, v, off, box)
    n = 0
    for i, e in enumerate(edges):
        if i not in rs:
            continue
        ends = [k for k, node in ((0, e["a"]), (1, e["b"])) if deg[node] >= 3]
        if not ends:
            continue
        P, ss = rs[i]
        L = float(ss[-1])
        RS = float(os.environ.get("SK242_REACH", 45.0))
        reach = min(RS, 0.42 * L) if len(ends) == 2 else min(RS, 0.6 * L)
        Q = np.asarray(P, float)
        for k in ends:
            R = Q if k == 0 else Q[::-1]
            S = ss if k == 0 else (L - ss)[::-1]
            if (i, k) in lateral:
                u, v, off, box = lateral[(i, k)]
                swing = np.array([_ease(s / max(1.0, box)) for s in S])[:, None]       # 0 at the junction point -> 1 at the box edge
                straight = R[0] + u * S[:, None] + v * off * swing
            else:
                u = _dir_at(R, S, min(reach, 0.8 * L) * 0.8)
                if u is None:
                    continue
                straight = R[0] + u * S[:, None]
            w = np.array([_ease(s / reach) for s in S])[:, None]       # 0 at the junction -> 1 where the real line takes over
            R2 = straight * (1 - w) + R * w
            Q = R2 if k == 0 else R2[::-1]
            n += 1
        e["pts"] = [tuple(map(float, p)) for p in Q]
        e["cum"] = _cum_of(e["pts"])
        e["len"] = e["cum"][-1]
    return n


CAP = {"motorway": 3, "trunk": 3, "primary": 3, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1,
       "living_street": 1, "service": 1}
LW = 3.25


def boulevard_floor(edges, floor=int(os.environ.get("SK242_FLOOR", 3)), reach=45.0, min_len=60.0):
    """Realistic lane counts for dual carriageways: the two one-way halves of a boulevard (arterial class, an opposite
    one-way carriageway within `reach` metres running the other way) carry at least `floor` lanes each, where OSM
    tags only 1-2 (checked against satellite widths).  -> carriageways raised."""
    ow = [e for e in edges if e["drive"] and e["ow"] and not e["bridge"] and e["cls"].replace("_link", "") in ("tertiary", "secondary", "primary", "trunk") and not e["cls"].endswith("_link") and e["len"] >= min_len]
    if not ow:
        return 0
    cell = 60.0
    grid = {}
    for e in ow:
        m = e["pts"][len(e["pts"]) // 2]
        grid.setdefault((int(m[0] // cell), int(m[1] // cell)), []).append(e)

    def dirvec(e):
        a, b = e["pts"][0], e["pts"][-1]
        l = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return (b[0] - a[0]) / l, (b[1] - a[1]) / l
    n = 0
    for e in ow:
        m = e["pts"][len(e["pts"]) // 2]
        ux, uy = dirvec(e)
        gx, gy = int(m[0] // cell), int(m[1] // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid.get((gx + dx, gy + dy), ()):
                    if o is e:
                        continue
                    q = o["pts"][len(o["pts"]) // 2]
                    ox, oy = dirvec(o)
                    if math.hypot(q[0] - m[0], q[1] - m[1]) < reach and ux * ox + uy * oy < -0.8:
                        per = max(1, int(round(e["w"] / LW)))
                        if per < floor:
                            e["lanes"], e["w"] = floor, floor * LW
                            n += 1
                        break
                else:
                    continue
                break
            else:
                continue
            break
    return n


def standardise(edges):
    """One lane standard for the whole network: lanes per direction capped by class (links one lane, tertiary two),
    every lane LW wide, so ground roads, ramps and bridge decks all share the same lane width and join seamlessly.
    Only the count shrinks where OSM over-tags; OSM per-direction splits are kept when within the cap.  -> edges changed."""
    n = 0
    for e in edges:
        if not e["drive"]:
            continue
        cls = e["cls"].replace("_link", "")
        cap = 1 if e["cls"].endswith("_link") and cls not in ("motorway", "trunk") else CAP.get(cls, 1)
        if e["ow"]:
            per = max(1, min(lane_count(e), cap))
            want = (per, None, per * LW)
        else:
            dl = e.get("directional_lanes")
            if dl:
                f, b = max(1, min(dl[0], cap)), max(1, min(dl[1], cap))
                want = (f + b, (f, b), (f + b) * LW)
            else:
                per = max(1, min(lane_count(e), cap))
                want = (2 * per, None, 2 * per * LW)
        if (e.get("lanes"), e.get("directional_lanes"), e["w"]) != want:
            e["lanes"], e["directional_lanes"], e["w"] = want
            n += 1
    return n


def repair(edges):
    print(f"[build] lane standard applied to {standardise(edges)} edges")
    print(f"[build] boulevard carriageways raised to 3 lanes: {boulevard_floor(edges)}")
    cut = dual_carriageways(edges)
    bridge_lanes(edges)
    merged = merge_junctions(edges)
    print(f"[build] junction clusters merged: {merged[0]} ({merged[1]} inner links removed)")
    print(f"[build] arm approaches straightened: {straighten_arms(edges)}")
    return cut, harmonise(edges)
