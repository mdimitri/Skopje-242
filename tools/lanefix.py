"""Lane-count continuity along through roads (shared by build_world, which repairs, and network_audit, which reports).
A boulevard that has 3 lanes a side, 2 between two junctions and 3 again looks wrong: lane counts come from per-way OSM
`lanes` tags that are often missing on the short pieces inside junctions.  `through_pairs` finds which edges continue each
other at a node; `repair` raises the dips."""
import math


def per_way(e):
    """Lanes in each travel direction (same rule as roads3d.lanes_per_way)."""
    n, w = e.get("lanes", 0), e["w"]
    if e["ow"]:
        return n if n else max(1, int(round(w / 3.5)))
    return max(1, n // 2) if n else (2 if w >= 13.0 else 1)


def _out_dir(e, node):
    p = e["pts"]
    (a, b) = (p[0], p[1]) if e["a"] == node else (p[-1], p[-2])
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] - a[0]) / d, (b[1] - a[1]) / d


def through_pairs(edges, min_cos=-0.82):
    """{(edge index, node): partner edge index}: at each node, the other drivable edge of the same kind (class group and
    one-way-ness) that continues straight on, mutually best."""
    inc = {}
    for i, e in enumerate(edges):
        if e["drive"] and not e["bridge"]:
            inc.setdefault(e["a"], []).append(i)
            inc.setdefault(e["b"], []).append(i)
    best = {}
    for n, ids in inc.items():
        if len(ids) < 2:
            continue
        for i in ids:
            di = _out_dir(edges[i], n)
            cand = None
            for j in ids:
                if j == i or edges[j]["ow"] != edges[i]["ow"] or edges[j]["a"] == edges[j]["b"]:
                    continue
                dj = _out_dir(edges[j], n)
                c = di[0] * dj[0] + di[1] * dj[1]
                if c < min_cos and (cand is None or c < cand[0]):
                    cand = (c, j)
            if cand:
                best[(i, n)] = cand[1]
    return {k: j for k, j in best.items() if best.get((j, k[1])) == k[0]}


def chains(edges, pairs):
    """Lists of edge indices that continue each other (each edge once)."""
    nb = {}
    for (i, n), j in pairs.items():
        nb.setdefault(i, []).append(j)
    seen, out = set(), []
    order = [i for i in nb if len(nb[i]) < 2] + list(nb)         # open ends first, then whatever is left (rings)
    for s in order:
        if s in seen:
            continue
        ch, cur = [s], s
        seen.add(s)
        while True:
            step = [j for j in nb.get(cur, ()) if j not in seen]
            if not step:
                break
            cur = step[0]
            seen.add(cur)
            ch.append(cur)
        out.append(ch)
    return out


def dips(edges, chain_list, max_len=250.0):
    """(first, last, level) index ranges inside chains where the lane count is below both neighbours."""
    found = []
    for ch in chain_list:
        c = [per_way(edges[i]) for i in ch]
        k = 0
        while k < len(ch):
            j = k
            while j + 1 < len(ch) and c[j + 1] == c[k]:
                j += 1
            if k > 0 and j < len(ch) - 1 and c[k - 1] > c[k] and c[j + 1] > c[k] and sum(edges[i]["len"] for i in ch[k:j + 1]) <= max_len:
                found.append((ch[k:j + 1], min(c[k - 1], c[j + 1])))
            k = j + 1
    return found


def repair(edges):
    """Raise lane dips to the lower of their two neighbours (width follows).  Returns the number of edges changed."""
    ch = chains(edges, through_pairs(edges))
    changed = 0
    for _ in range(3):
        d = dips(edges, ch)
        if not d:
            break
        for ids, lvl in d:
            for i in ids:
                e = edges[i]
                e["lanes"] = lvl if e["ow"] else lvl * 2
                e["w"] = max(e["w"], e["lanes"] * 3.5)
                changed += 1
    return changed


def steps(edges, chain_list):
    """Through pairs whose lane counts differ by one or more (excluding dips): [(edge a, edge b, lanes a, lanes b)]."""
    out = []
    for ch in chain_list:
        for a, b in zip(ch, ch[1:]):
            la, lb = per_way(edges[a]), per_way(edges[b])
            if la != lb:
                out.append((a, b, la, lb))
    return out
