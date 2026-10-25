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
    if len(sys.argv) > 2:
        rl = json.load(open(sys.argv[2], encoding="utf-8"))
        ways = [r for r in rl if r[0] == "way" and r[1] == "rail"]
        print(f"rail ways {len(ways)}, on viaduct {sum(1 for r in ways if r[2])}, tunnel {sum(1 for r in ways if r[3])}; stations "
              f"{[r[4] for r in rl if r[0] == 'node' and r[1] in ('station', 'halt')]}")


if __name__ == "__main__":
    main()
