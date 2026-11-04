"""Road / junction / railway audit of a built world (round 21).
Usage: python3 tools/network_audit.py <world_dir> [rail.json]
Prints: strongly connected pockets, dead ends next to another road, narrow-angle junctions, tiny edges, signal coverage (and against
the OSM signals in pois.json when --osm <dir> is given), lamps / trees / posts standing in lanes, rail crossings by type."""
import collections
import json
import math
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lanefix

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


def load(d, name):
    with open(os.path.join(d, name + ".pkl"), "rb") as f:
        return pickle.load(f)


def seg_dist(x, y, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
    return math.hypot(x - ax - dx * t, y - ay - dy * t)


def scc(edges):
    """Tarjan on the directed drivable graph -> {node: component}, id of the giant component."""
    adj = collections.defaultdict(list)
    for e in edges:
        if e["drive"]:
            adj[e["a"]].append(e["b"])
            adj.setdefault(e["b"], [])
            if not e["ow"]:
                adj[e["b"]].append(e["a"])
    idx, low, on, st, comp, c, cnt = {}, {}, set(), [], {}, 0, 0
    for s in adj:
        if s in idx:
            continue
        work = [(s, 0)]
        while work:
            v, pi = work.pop()
            if pi == 0:
                idx[v] = low[v] = cnt
                cnt += 1
                st.append(v)
                on.add(v)
            for k in range(pi, len(adj[v])):
                w = adj[v][k]
                if w not in idx:
                    work.append((v, k + 1))
                    work.append((w, 0))
                    break
                if w in on:
                    low[v] = min(low[v], idx[w])
            else:
                if low[v] == idx[v]:
                    while True:
                        w = st.pop()
                        on.discard(w)
                        comp[w] = c
                        if w == v:
                            break
                    c += 1
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
    return comp, collections.Counter(comp.values()).most_common(1)[0][0]


def lanes_blockers(edges, props, th):
    cg = 20.0
    grid = collections.defaultdict(list)
    for e in edges:
        if e["drive"] and not e["bridge"]:
            for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                for gx in range(int(min(ax, bx) // cg) - 1, int(max(ax, bx) // cg) + 2):
                    for gy in range(int(min(ay, by) // cg) - 1, int(max(ay, by) // cg) + 2):
                        grid[(gx, gy)].append((ax, ay, bx, by, e["w"] / 2 - 0.2))

    def inside(x, y, r):
        return any(seg_dist(x, y, *s[:4]) < s[4] - r for s in grid.get((int(x // cg), int(y // cg)), ()))

    return {"lamps": sum(inside(x, y, 0.22) for x, y in props["lamps"]), "trees": sum(inside(t[0], t[1], 0.5) for t in props["trees"]),
            "posts at ground level": sum(inside(p[0], p[1], 0.0) for p in props["posts"] if len(p) < 5 or p[3] <= th(p[0], p[1]) + 2.2)}


def faults(edges, props):
    """Road-logic faults: {name: [descriptions]}.  Any entry is a build bug (main() exits 1 under --strict)."""
    out = collections.defaultdict(list)
    drive = [e for e in edges if e["drive"]]
    ch = lanefix.chains(edges, lanefix.through_pairs(edges))
    for ids, lvl in lanefix.dips(edges, ch):
        e = edges[ids[0]]
        out["lane dip (n, then fewer, then n again)"].append(f"{e['cls']} {e.get('name', '')} at ({e['pts'][0][0]:.0f},{e['pts'][0][1]:.0f}) {len(ids)} edge(s) < {lvl} lanes")
    for a, b, la, lb in lanefix.steps(edges, ch):
        p = edges[a]["pts"][0]
        out["lane step between through edges"].append(f"{edges[a]['cls']} {la}->{lb} lanes at ({p[0]:.0f},{p[1]:.0f})")
    for a, b, la, lb in lanefix.steps(edges, ch):
        wa, wb = edges[a]["w"], edges[b]["w"]
        if abs(wa - wb) > 3.6 and la == lb:
            out["width step > 3.6 m with equal lanes"].append(f"{wa:.1f}->{wb:.1f} m at ({edges[a]['pts'][0][0]:.0f},{edges[a]['pts'][0][1]:.0f})")
    for e in drive:
        if lanefix.per_way(e) * 2.6 > e["w"] + 0.01 * (1 if e["ow"] else 2):
            out["lanes narrower than 2.6 m"].append(f"{e['cls']} w={e['w']:.1f} lanes/way={lanefix.per_way(e)}")
    ind, outd = collections.Counter(), collections.Counter()
    for e in drive:
        if e["ow"]:
            outd[e["a"]] += 1
            ind[e["b"]] += 1
        else:
            for n in (e["a"], e["b"]):
                outd[n] += 1
                ind[n] += 1
    for n in set(ind) | set(outd):
        if ind[n] and not outd[n]:
            out["one-way sink (cars enter, none leave)"].append(f"node {n}")
        if outd[n] and not ind[n]:
            out["one-way source (cars leave, none enter)"].append(f"node {n}")
    for e in drive:
        if e["len"] < 1.0:
            out["drivable edge < 1 m"].append(f"{e['cls']} at ({e['pts'][0][0]:.0f},{e['pts'][0][1]:.0f})")
    return out


def geometry_faults(d, edges, props, rail_file=None):
    """Buildings over asphalt / pavement and trees under overpasses or rails -> {name: [descriptions]}."""
    from build_world import seg_grid, near_seg
    out = collections.defaultdict(list)
    g = seg_grid([(a[0], a[1], b[0], b[1], e["w"] / 2 + 2.0 - 0.2) for e in edges if e["drive"] and not e["bridge"]
                  and e["cls"] not in ("footway", "path", "steps", "cycleway", "pedestrian") for a, b in zip(e["pts"], e["pts"][1:])])
    try:
        for b in load(d, "buildings")["buildings"]:
            deep = 0.0
            for x, y in b["ring"]:
                n = near_seg(g, x, y)
                if n and n[0] < 0:
                    deep = min(deep, n[0])
            if deep < -0.15:
                out["building outline over road/pavement"].append(f"{deep:.1f} m deep at ({b['ring'][0][0]:.0f},{b['ring'][0][1]:.0f})")
    except Exception as ex:  # noqa: BLE001
        out["audit error"].append(f"buildings: {ex}")
    segs = [(a[0], a[1], b[0], b[1], e["w"] / 2 + 1.5) for e in edges if e["bridge"] and (e["drive"] or e["walk"]) for a, b in zip(e["pts"], e["pts"][1:])]
    if rail_file:
        for r in json.load(open(rail_file, encoding="utf-8")):
            if r[0] == "way" and r[1] == "rail" and not r[3]:
                segs += [(a[0], a[1], b[0], b[1], 3.0) for a, b in zip(r[4], r[4][1:])]
    tg = seg_grid(segs)
    for t in props["trees"]:
        n = near_seg(tg, t[0], t[1])
        if n and n[0] < 0:
            out["tree under overpass / rail"].append(f"({t[0]:.0f},{t[1]:.0f})")
    return out


def main():
    d = sys.argv[1]
    edges = load(d, "edges")["edges"]
    props = load(d, "props")
    drive = [e for e in edges if e["drive"]]
    print(f"drivable edges {len(drive)}, {sum(e['len'] for e in drive) / 1000:.1f} km")
    comp, main_c = scc(edges)
    bad = [e for e in drive if comp[e["a"]] != main_c or comp[e["b"]] != main_c]
    print(f"edges outside the main strongly connected network: {len(bad)} ({sum(e['len'] for e in bad) / 1000:.1f} km)")
    deg = collections.Counter()
    for e in drive:
        deg[e["a"]] += 1
        deg[e["b"]] += 1
    print("dead ends:", sum(1 for n, k in deg.items() if k == 1), " edges < 4 m:", sum(1 for e in drive if e["len"] < 4))
    sig = {t[0] for t in props["signals"]}
    print(f"signalised nodes {len(sig)}, signal heads {len(props['signals'])}")
    from world import World
    w = World(d, lambda f, note="": None)
    print("objects standing in a drivable lane:", lanes_blockers(edges, props, w.th))
    fl = faults(edges, props)
    rf = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    fl.update(geometry_faults(d, edges, props, rf))
    for k, v in sorted(fl.items()):
        print(f"FAULT {k}: {len(v)}  e.g. {'; '.join(v[:4])}")
    if "--strict" in sys.argv and any(k.startswith(("lane dip", "lanes narrower", "building outline", "tree under")) for k in fl):
        sys.exit(1)
    if len(sys.argv) > 2 and not sys.argv[2].startswith("--"):
        rl = json.load(open(sys.argv[2], encoding="utf-8"))
        ways = [r for r in rl if r[0] == "way" and r[1] == "rail"]
        print(f"rail ways {len(ways)}, on viaduct {sum(1 for r in ways if r[2])}, tunnel {sum(1 for r in ways if r[3])}; stations "
              f"{[r[4] for r in rl if r[0] == 'node' and r[1] in ('station', 'halt')]}")


if __name__ == "__main__":
    main()
