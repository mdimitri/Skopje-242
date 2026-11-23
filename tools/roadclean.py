"""Road graph clean-up before the road mesh is built (run after lanefix): carriageways of a dual road never overlap
(lanes are cut so a median at least MEDIAN wide fits between them), and short stray segments take the lane count and
width of their longer neighbours (no narrow-then-widen bumps)."""
import collections

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
    for i, e in enumerate(edges):
        if not e["drive"] or e["bridge"] or e["a"] not in J or e["b"] not in J or e["a"] == e["b"]:
            continue
        reach = size[e["a"]] + size[e["b"]] + 2 * kerb          # what the two junctions pave anyway
        score = 1.0 / (1.0 + np.exp((e["len"] - reach) / (0.15 * reach)))
        if score > 0.5:
            links.append(i)
            parent[find(e["a"])] = find(e["b"])
    groups = collections.defaultdict(list)
    for n in J:
        groups[find(n)].append(n)
    groups = {r: ns for r, ns in groups.items() if len(ns) > 1}
    if not groups:
        return 0, 0
    root = {n: r for r, ns in groups.items() for n in ns}
    inner = {i for i in links if find(edges[i]["a"]) == find(edges[i]["b"])}
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


def repair(edges):
    cut = dual_carriageways(edges)
    bridge_lanes(edges)
    merged = merge_junctions(edges)
    print(f"[build] junction clusters merged: {merged[0]} ({merged[1]} inner links removed)")
    return cut, harmonise(edges)
