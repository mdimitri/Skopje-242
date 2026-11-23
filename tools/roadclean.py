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


def repair(edges):
    cut = dual_carriageways(edges)
    bridge_lanes(edges)
    return cut, harmonise(edges)
