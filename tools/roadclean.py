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


def repair(edges):
    cut = dual_carriageways(edges)
    return cut, harmonise(edges)
