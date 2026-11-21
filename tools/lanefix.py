"""Lane-count continuity along through roads (shared by build_world, which repairs, and network_audit, which reports).
A boulevard that has 3 lanes a side, 2 between two junctions and 3 again looks wrong: lane counts come from per-way OSM
`lanes` tags that are often missing on the short pieces inside junctions.  `through_pairs` finds which edges continue each
other at a node; `repair` raises the dips."""
import math
from roadwidth import lane_count as per_way


def _out_dir(e, node):
    p = e["pts"]
    (a, b) = (p[0], p[1]) if e["a"] == node else (p[-1], p[-2])
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return (b[0] - a[0]) / d, (b[1] - a[1]) / d


def through_pairs(edges, min_cos=-0.82):
    """Find mutually best straight continuations with compatible directions at the shared node."""
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
                if edges[i]["ow"] and (edges[i]["a"] == n) == (edges[j]["a"] == n):
                    continue                                     # two arrivals or two departures cannot form a through road
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
            if k > 0 and j < len(ch) - 1 and c[k - 1] > c[k] and c[j + 1] > c[k] and sum(edges[i]["len"] for i in ch[k:j + 1]) <= max_len \
                    and not any(edges[i].get("directional_lanes") for i in ch[k - 1:j + 2]):
                found.append((ch[k:j + 1], min(c[k - 1], c[j + 1])))
            k = j + 1
    return found


def _oriented(edges, ch):
    """For every edge of a chain: True when its stored direction runs along the chain (a -> b)."""
    fwd = []
    for k, i in enumerate(ch):
        e = edges[i]
        if len(ch) == 1:
            fwd.append(True)
        elif k + 1 < len(ch):
            o = edges[ch[k + 1]]
            fwd.append(e["b"] in (o["a"], o["b"]))
        else:
            p = edges[ch[k - 1]]
            fwd.append(e["a"] in (p["a"], p["b"]))
    return fwd


def _copy_profile(edges, dst, src, same_way):
    """Give edge dst the lane layout of edge src (carriageway width, lane counts; the turn tag no longer fits)."""
    d, s = edges[dst], edges[src]
    d["w"], d["lanes"] = s["w"], s.get("lanes", 0)
    dl = s.get("directional_lanes")
    d["directional_lanes"] = (dl if same_way else dl[::-1]) if dl else None
    d["turn"] = ("", "")


def harmonize(edges, short=300.0):
    """A through road keeps its carriageway: a stretch of at most `short` m that is narrower than both neighbours takes
    the narrower neighbour's layout; a stretch that is wider than both neighbours, with no turn lanes marked, takes the
    wider one's.  Class changes bound a chain.  Returns the number of edges changed."""
    changed = 0
    for _ in range(4):
        moved = 0
        for ch in chains(edges, through_pairs(edges)):
            fwd = _oriented(edges, ch)
            k = 0
            while k < len(ch):
                j = k
                while j + 1 < len(ch) and abs(edges[ch[j + 1]]["w"] - edges[ch[k]]["w"]) < 0.5 \
                        and edges[ch[j + 1]]["cls"] == edges[ch[k]]["cls"]:
                    j += 1
                if 0 < k and j < len(ch) - 1:
                    a, b, run = ch[k - 1], ch[j + 1], ch[k:j + 1]
                    wa, wb, w = edges[a]["w"], edges[b]["w"], edges[ch[k]]["w"]
                    base = lambda q: edges[q]["cls"].replace("_link", "")
                    if base(a) == base(run[0]) == base(b) and sum(edges[i]["len"] for i in run) <= short:
                        src = None
                        if wa > w + 0.5 and wb > w + 0.5:
                            src = (a, k - 1) if wa <= wb else (b, j + 1)
                        elif wa < w - 0.5 and wb < w - 0.5 and not any(any(edges[i].get("turn", ("", ""))) for i in run):
                            src = (a, k - 1) if wa >= wb else (b, j + 1)
                        if src:
                            for q, i in enumerate(run):
                                _copy_profile(edges, i, src[0], fwd[k + q] == fwd[src[1]])
                            moved += len(run)
                k = j + 1
        changed += moved
        if not moved:
            break
    return changed


def repair(edges):
    """Level the lane count along through roads (see harmonize), then raise any lane dips left.  Returns the number of
    edges changed."""
    changed = harmonize(edges)
    ch = chains(edges, through_pairs(edges))
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
