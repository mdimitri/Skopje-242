"""Whole-city road network audit: every junction, bridge, overpass, underpass, tunnel, ramp / slip road, roundabout,
rail crossing, dead end and bridge end of the road network, with its defects classified on two tests:
  graph   - is the traffic grid linked and correct (pockets, traps, missed joins, crossings without a junction ...)
  visual  - does it look right in 3D (steps at bridge ends, headroom, pavements in a twin bridge's median ...)

It needs no world build: the road pipeline of tools/build_world.py runs up to the bridge decks and dumps its result
(about a minute for the whole city), then this reads the dump:

    SK242_ROADS_ONLY=dump.pkl python tools/build_world.py --src data/osm --out <any>
    python tools/road_audit.py dump.pkl out.json [--rail data/osm/rail.json] [--mesh] [--box x0,y0,x1,y1]

--mesh also builds the 3D road mesh (tools/roads3d.py) and rasterises every drivable junction for holes, pavement in the
lanes and z-fighting (the tools/sidewalk_audit.py tests).  out.json = {"inventory": {...}, "findings": [...], "counts": {...}}."""
import argparse
import collections
import json
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "src"))

CLEAR_STREET = 4.0              # headroom a street needs under a deck (m)
CLEAR_PATH = 2.4
SLAB = 0.9                      # terrain.SLAB
GAP_JOIN = 15.0                 # a dead end this close to another road, pointing at it, is a missed join
LINK = ("motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link")
FOOT = ("pedestrian", "footway", "path", "steps", "cycleway", "track")

# defect kinds: (test, short description)
KINDS = {
    "teleport": ("graph", "one junction node id used at two places far apart (the graph links streets that do not meet)"),
    "pocket": ("graph", "drivable streets not reachable from the main network (strongly connected pocket)"),
    "trap": ("graph", "one-way trap: a node a car can enter but never leave, or leave but never reach"),
    "gap": ("graph", "dead end that stops short of another road (missed junction)"),
    "flat_cross": ("graph", "two streets cross on the same level without a junction"),
    "split_node": ("graph", "two junction nodes on top of each other that are not joined"),
    "bridge_dangle": ("graph", "bridge or overpass end that leads nowhere"),
    "link_dead": ("graph", "ramp / slip road with a loose end"),
    "roundabout": ("graph", "roundabout ring broken or running both ways"),
    "tunnel_end": ("graph", "tunnel end that leads nowhere"),
    "tiny_edge": ("graph", "drivable edge shorter than 2 m between two junctions"),
    "sharp_merge": ("graph", "two streets meet at a knife angle (< 12 degrees): plates overlap, lanes cross"),
    "deck_step": ("visual", "height step between a bridge end and the road it joins"),
    "deck_joint": ("visual", "two bridge pieces meet at different heights"),
    "deck_grade": ("visual", "bridge deck steeper than 10 % (cars launch / scrape)"),
    "approach_grade": ("visual", "bridge approach ramp steeper than 12 %"),
    "headroom": ("visual", "road under a bridge has less headroom than it needs (drives into the girder)"),
    "deck_cross": ("visual", "two bridges cross at almost the same height (decks cut through each other)"),
    "median_pavement": ("visual", "pavement (and parapet) in the median between the two decks of a twin bridge"),
    "twin_mismatch": ("visual", "the two decks of a twin bridge differ in height"),
    "flat_bridge": ("visual", "bridge without a deck profile (drawn flat on the ground)"),
    "junction_on_deck": ("visual", "a side street joins in the middle of a bridge (deck pinned to the ground there)"),
    "median_overlap": ("visual", "pavements of a dual carriageway overlap in a narrow median (z-fighting)"),
    "rail_cross": ("graph", "street crosses a railway at grade without a level crossing"),
    "rail_headroom": ("visual", "street bridge over a railway too low for trains"),
    "mesh_hole": ("visual", "junction: ground shows through the road surface"),
    "mesh_inlane": ("visual", "junction: pavement inside the lanes"),
    "mesh_zfight": ("visual", "junction: pavement and asphalt in the same plane (flicker)"),
    "mesh_spike": ("visual", "junction: long thin mis-joined triangle"),
}


def seg_hit(a, b, c, d, lo=0.02):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if lo < t < 1 - lo and lo < u < 1 - lo:
        return a[0] + t * r[0], a[1] + t * r[1], t, u
    return None


def pdist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - dx * t, py - ay - dy * t), t


class Grid:
    def __init__(self, cell=20.0):
        self.c, self.g = cell, collections.defaultdict(list)

    def add_seg(self, item, a, b, pad=0.0):
        c = self.c
        for cx in range(int((min(a[0], b[0]) - pad) // c), int((max(a[0], b[0]) + pad) // c) + 1):
            for cy in range(int((min(a[1], b[1]) - pad) // c), int((max(a[1], b[1]) + pad) // c) + 1):
                self.g[(cx, cy)].append(item)

    def near(self, x, y, r=0.0):
        c, seen = self.c, set()
        for cx in range(int((x - r) // c), int((x + r) // c) + 1):
            for cy in range(int((y - r) // c), int((y + r) // c) + 1):
                for it in self.g.get((cx, cy), ()):
                    if it not in seen:
                        seen.add(it)
                        yield it


def scc(nodes, out):
    """Iterative Tarjan -> {node: component id}."""
    idx, low, on, st, comp = {}, {}, set(), [], {}
    c = [0, 0]
    for s in nodes:
        if s in idx:
            continue
        work = [(s, iter(out.get(s, ())))]
        idx[s] = low[s] = c[0]
        c[0] += 1
        st.append(s)
        on.add(s)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in idx:
                    idx[w] = low[w] = c[0]
                    c[0] += 1
                    st.append(w)
                    on.add(w)
                    work.append((w, iter(out.get(w, ()))))
                    break
                if w in on:
                    low[v] = min(low[v], idx[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == idx[v]:
                    while True:
                        w = st.pop()
                        on.discard(w)
                        comp[w] = c[1]
                        if w == v:
                            break
                    c[1] += 1
    return comp


class Audit:
    def __init__(self, dump, rail=None, box=None):
        self.roads, self.edges, self.decks, self.upass, self.T = dump["roads"], dump["edges"], dump["decks"], dump["upass"], dump["T"]
        self.hx, self.hy = dump["hx"], dump["hy"]
        self.rail = rail or []
        self.box = box
        self.find = []
        self.inv = collections.Counter()
        E = self.edges
        self.pos = {}
        self.inc = collections.defaultdict(list)            # node -> [(edge, end)]
        for i, e in enumerate(E):
            if not (e["drive"] or e["walk"]):
                continue
            self.pos.setdefault(e["a"], tuple(e["pts"][0]))
            self.pos.setdefault(e["b"], tuple(e["pts"][-1]))
            self.inc[e["a"]].append((i, 0))
            self.inc[e["b"]].append((i, 1))
        self.ddeg = {n: sum(1 for i, _ in l if E[i]["drive"]) for n, l in self.inc.items()}
        self.tele = []
        for n, l in self.inc.items():
            ps = [E[i]["pts"][0] if end == 0 else E[i]["pts"][-1] for i, end in l]
            far = max(math.hypot(p[0] - ps[0][0], p[1] - ps[0][1]) for p in ps)
            if far > 1.0:
                self.tele.append((n, ps, far, [i for i, _ in l]))
        self.grid = Grid(20.0)
        for i, e in enumerate(E):
            if e["drive"] or e["walk"]:
                for k in range(len(e["pts"]) - 1):
                    self.grid.add_seg((i, k), e["pts"][k], e["pts"][k + 1])

    # ---------------------------------------------------------------- helpers
    def inside(self, x, y, m=30.0):
        if abs(x) > self.hx - m or abs(y) > self.hy - m:
            return False
        if self.box:
            return self.box[0] <= x <= self.box[2] and self.box[1] <= y <= self.box[3]
        return True

    def add(self, kind, x, y, sev, detail, **kw):
        if not self.inside(x, y, 10.0):
            return
        f = {"kind": kind, "test": KINDS[kind][0], "x": round(x, 1), "y": round(y, 1), "sev": round(float(sev), 2), "detail": detail}
        f.update(kw)
        self.find.append(f)

    def name(self, i):
        r = self.roads[self.edges[i]["road"]]
        return r.get("name") or r["cls"]

    def level(self, i):
        e = self.edges[i]
        r = self.roads[e["road"]]
        return (1 if e["bridge"] else 0) + (-1 if r.get("tunnel") else 0), r.get("layer", 0)

    def deck_of(self, i):
        e = self.edges[i]
        return self.decks.get(e["road"]) if e["bridge"] else None

    def surf(self, i, x, y):
        """Height of edge i's surface at (x, y): its deck, or the ground."""
        d = self.deck_of(i)
        if d is not None:
            return d.at(x, y)[0]
        return self.T.hs(x, y)

    def away(self, i, end, s=6.0):
        """Unit vector pointing out of edge i at its end (from the inside towards the end node)."""
        p = self.edges[i]["pts"]
        P = p if end == 1 else p[::-1]
        q = P[-1]
        acc = 0.0
        for k in range(len(P) - 2, -1, -1):
            acc += math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1])
            if acc >= s or k == 0:
                v = (q[0] - P[k][0], q[1] - P[k][1])
                n = math.hypot(*v) or 1.0
                return v[0] / n, v[1] / n

    # ---------------------------------------------------------------- inventory
    def inventory(self):
        E, inv = self.edges, self.inv
        for n, l in self.inc.items():
            x, y = self.pos[n]
            if not self.inside(x, y):
                continue
            dd = self.ddeg.get(n, 0)
            if dd >= 3:
                inv["junction (drivable, %s-way)" % (dd if dd < 5 else "5+")] += 1
            elif dd == 1 and len(l) == 1:
                inv["dead end (street)"] += 1
            if dd < 3 and len(l) >= 3:
                inv["junction (paths only / path meets street)"] += 1
        seen = set()
        for i, e in enumerate(E):
            r = self.roads[e["road"]]
            if not self.inside(*e["pts"][len(e["pts"]) // 2]):
                continue
            if e["road"] in seen:
                continue
            seen.add(e["road"])
            if e["bridge"]:
                over = self.crosses_under(i)
                if e["drive"]:
                    inv["bridge / overpass (street)" if over else "bridge (street, over water / ground)"] += 1
                else:
                    inv["footbridge"] += 1
            if r.get("tunnel"):
                inv["tunnel (street)"] += 1
            if e["cls"] in LINK:
                inv["ramp / slip road (_link)"] += 1
            if r.get("junction") in ("roundabout", "circular"):
                inv["roundabout pieces"] += 1
        inv["underpass (dug cutting)"] = len(self.upass)
        inv["bridge decks"] = len(self.decks)
        inv["bridge ends"] = 2 * len(self.decks)
        inv["rail level-crossing nodes (OSM)"] = sum(1 for r in self.rail if r[0][:2] == ["node", "level_crossing"] or (r[0] == "node" and r[1] == "level_crossing"))

    def crosses_under(self, i):
        e = self.edges[i]
        for k in range(len(e["pts"]) - 1):
            a, b = e["pts"][k], e["pts"][k + 1]
            for j, m in self.grid.near((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + 1):
                f = E_ = self.edges[j]
                if j == i or E_["bridge"] or not E_["drive"]:
                    continue
                if seg_hit(a, b, E_["pts"][m], E_["pts"][m + 1]):
                    return True
        return False

    # ---------------------------------------------------------------- graph tests
    def graph(self):
        E = self.edges
        for n, ps, far, lst in self.tele:
            self.add("teleport", ps[0][0], ps[0][1], far, f"node {n} joins {self.name(lst[0])} with {self.name(lst[-1])} {far:.0f} m away",
                     node=n, at=[list(map(float, p)) for p in ps])
        out = collections.defaultdict(set)
        nodes = set()
        for e in E:
            if e["drive"]:
                nodes.update((e["a"], e["b"]))
                out[e["a"]].add(e["b"])
                if not e["ow"]:
                    out[e["b"]].add(e["a"])
        comp = scc(nodes, out)
        size = collections.Counter()
        for i, e in enumerate(E):
            if e["drive"] and comp[e["a"]] == comp[e["b"]]:
                size[comp[e["a"]]] += e["len"]
        giant = size.most_common(1)[0][0]
        self.giant = giant
        self.comp = comp
        pockets = collections.defaultdict(list)
        for i, e in enumerate(E):
            if e["drive"] and not (comp[e["a"]] == giant and comp[e["b"]] == giant):
                pockets[comp[e["a"]] if comp[e["a"]] != giant else comp[e["b"]]].append(i)
        for c, lst in pockets.items():
            L = sum(E[i]["len"] for i in lst)
            pts = [p for i in lst for p in E[i]["pts"]]
            x, y = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            if L < 15:
                continue
            ins = {E[i]["a"] for i in lst} | {E[i]["b"] for i in lst}
            ind = {n for n in ins if any(n in out.get(m, ()) for m in ins if comp.get(m) == giant)}
            outd = {n for n in ins if any(comp.get(m) == giant for m in out.get(n, ()))}
            how = "can enter, cannot leave" if ind and not outd else ("can leave, cannot enter" if outd and not ind else "cut off")
            self.add("pocket", x, y, L, f"{len(lst)} edges, {L:.0f} m ({how}): {self.name(lst[0])}", edges=lst[:40], how=how)
        # one-way traps at single nodes
        inn = collections.Counter()
        for n, s in out.items():
            for m in s:
                inn[m] += 1
        for n in nodes:
            if self.ddeg.get(n, 0) < 1:
                continue
            o, ii = len(out.get(n, ())), inn.get(n, 0)
            if (o == 0) != (ii == 0):
                x, y = self.pos[n]
                i0 = next(i for i, _ in self.inc[n] if E[i]["drive"])
                self.add("trap", x, y, 1, f"{'no way out' if o == 0 else 'no way in'} at a one-way end ({self.name(i0)})", node=n)
        # dead ends next to a road: missed joins
        for n, l in self.inc.items():
            if len(l) != 1:
                continue
            i, end = l[0]
            e = E[i]
            if not e["drive"] or e["len"] < 3:
                continue
            x, y = self.pos[n]
            ax, ay = self.away(i, end)
            lv = self.level(i)
            best = None
            for j, k in self.grid.near(x, y, GAP_JOIN):
                f = E[j]
                if j == i or not f["drive"] or f["a"] == e["a"] or f["b"] == e["b"] or f["a"] == e["b"] or f["b"] == e["a"]:
                    continue
                d, t = pdist(x, y, *f["pts"][k], *f["pts"][k + 1])
                if d > GAP_JOIN or d < 0.3:
                    continue
                qx = f["pts"][k][0] + (f["pts"][k + 1][0] - f["pts"][k][0]) * t
                qy = f["pts"][k][1] + (f["pts"][k + 1][1] - f["pts"][k][1]) * t
                if (qx - x) * ax + (qy - y) * ay < 0.5 * d:
                    continue                                    # beside it, not pointing at it
                dh = abs(self.surf(i, x, y) - self.surf(j, qx, qy))
                if best is None or d < best[0]:
                    best = (d, j, dh, self.level(j) == lv)
            if best:
                d, j, dh, same = best
                if dh < 1.5:
                    self.add("gap", x, y, d, f"{self.name(i)} stops {d:.1f} m short of {self.name(j)} (height difference {dh:.1f} m)",
                             node=n, edge=i, other=j, d=round(d, 1), dh=round(dh, 2))
        # crossings without a node on the same level, deck crossings, headroom
        done = set()
        for i, e in enumerate(E):
            if not (e["drive"] or e["walk"]):
                continue
            for k in range(len(e["pts"]) - 1):
                a, b = e["pts"][k], e["pts"][k + 1]
                for j, m in self.grid.near((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + 1):
                    if j <= i or (i, j) in done:
                        continue
                    f = E[j]
                    if {e["a"], e["b"]} & {f["a"], f["b"]} and (e["len"] < 30 or f["len"] < 30):
                        pass
                    h = seg_hit(a, b, f["pts"][m], f["pts"][m + 1], 0.0)
                    if not h:
                        continue
                    x, y = h[0], h[1]
                    if min(math.hypot(x - self.pos[n][0], y - self.pos[n][1]) for n in (e["a"], e["b"], f["a"], f["b"])) < 1.0:
                        continue
                    done.add((i, j))
                    self._crossing(i, j, x, y)
        # near-coincident nodes, tiny edges, knife-angle merges
        ng = Grid(4.0)
        for n in self.inc:
            if self.ddeg.get(n, 0):
                ng.g[(int(self.pos[n][0] // 4), int(self.pos[n][1] // 4))].append(n)
        adj = collections.defaultdict(set)
        for e in E:
            if e["drive"]:
                adj[e["a"]].add(e["b"])
                adj[e["b"]].add(e["a"])
        for n in self.inc:
            if not self.ddeg.get(n, 0):
                continue
            x, y = self.pos[n]
            for m in ng.near(x, y, 1.5):
                if m <= n or m in adj[n]:
                    continue
                d = math.hypot(self.pos[m][0] - x, self.pos[m][1] - y)
                if d < 1.5:
                    li, lj = self.inc[n][0][0], self.inc[m][0][0]
                    if self.level(li) != self.level(lj) or abs(self.surf(li, x, y) - self.surf(lj, x, y)) > 1.5:
                        continue
                    self.add("split_node", x, y, 1.5 - d, f"{self.name(li)} / {self.name(lj)}: two nodes {d:.2f} m apart", nodes=[n, m])
        for i, e in enumerate(E):
            if e["drive"] and e["len"] < 2.0 and self.ddeg.get(e["a"], 0) >= 3 and self.ddeg.get(e["b"], 0) >= 3:
                p = e["pts"][0]
                self.add("tiny_edge", p[0], p[1], 2.0 - e["len"], f"{self.name(i)}: {e['len']:.2f} m between two junctions", edge=i)
        for n, l in self.inc.items():
            dl = [(i, end) for i, end in l if E[i]["drive"]]
            if len(dl) < 2:
                continue
            vs = [(i, self.away(i, end)) for i, end in dl]
            for p_ in range(len(vs)):
                for q_ in range(p_ + 1, len(vs)):
                    (i, u), (j, v) = vs[p_], vs[q_]
                    c = u[0] * v[0] + u[1] * v[1]              # both point into the node: the same way in = a knife between them
                    ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
                    if ang < 12 and len(dl) >= 3:
                        x, y = self.pos[n]
                        self.add("sharp_merge", x, y, 12 - ang, f"{self.name(i)} / {self.name(j)} meet at {ang:.0f} deg", node=n)
        # bridges / ramps / tunnels with loose ends, roundabouts
        for i, e in enumerate(E):
            if not e["drive"]:
                continue
            r = self.roads[e["road"]]
            for end, n in ((0, e["a"]), (1, e["b"])):
                if len(self.inc[n]) != 1:
                    continue
                x, y = self.pos[n]
                if e["bridge"]:
                    self.add("bridge_dangle", x, y, 1, f"{self.name(i)}: bridge end with no road beyond it", node=n, edge=i)
                elif e["cls"] in LINK:
                    self.add("link_dead", x, y, 1, f"{self.name(i)} ({e['cls']}) ends loose", node=n, edge=i)
                elif r.get("tunnel"):
                    self.add("tunnel_end", x, y, 1, f"{self.name(i)}: tunnel end with no road beyond it", node=n, edge=i)
        ring = [i for i, e in enumerate(E) if e["drive"] and self.roads[e["road"]].get("junction") in ("roundabout", "circular")]
        rn = collections.defaultdict(lambda: [0, 0])
        for i in ring:
            e = E[i]
            if not e["ow"]:
                p = e["pts"][len(e["pts"]) // 2]
                self.add("roundabout", p[0], p[1], 1, f"{self.name(i)}: roundabout piece open both ways", edge=i)
            rn[e["a"]][0] += 1                                # out of a
            rn[e["b"]][1] += 1                                # into b
        for n, (o, ii) in rn.items():
            if o != ii:
                x, y = self.pos[n]
                self.add("roundabout", x, y, 1, f"roundabout ring: {ii} piece(s) in, {o} out at this node", node=n)
        self.inv["roundabouts (rings)"] = self._rings(ring)

    def _rings(self, ring):
        par_ = {}

        def f(a):
            while par_.setdefault(a, a) != a:
                par_[a] = par_[par_[a]]
                a = par_[a]
            return a
        for i in ring:
            par_[f(self.edges[i]["a"])] = f(self.edges[i]["b"])
        return len({f(self.edges[i]["a"]) for i in ring})

    def _crossing(self, i, j, x, y):
        E = self.edges
        e, f = E[i], E[j]
        di, dj = self.deck_of(i), self.deck_of(j)
        li, lj = self.level(i), self.level(j)
        if e["bridge"] and f["bridge"]:
            hi_, hj = di.at(x, y)[0] if di else self.T.hs(x, y), dj.at(x, y)[0] if dj else self.T.hs(x, y)
            dh = abs(hi_ - hj)
            if 0.3 < dh < SLAB + (CLEAR_STREET if (e["drive"] and f["drive"]) else CLEAR_PATH):
                self.add("deck_cross", x, y, dh, f"{self.name(i)} over {self.name(j)}: decks {dh:.1f} m apart", edges=[i, j])
            return
        if e["bridge"] or f["bridge"]:
            top, low = (i, j) if e["bridge"] else (j, i)
            d = self.deck_of(top)
            if d is None:
                return
            h, s, lat = d.at(x, y)
            if s < 1.0 or s > d.len - 1.0:
                return                                       # at the very end of the deck: an at-grade joint
            under = self.surf(low, x, y)
            need = CLEAR_STREET if E[low]["drive"] else CLEAR_PATH
            cl = h - SLAB - under
            if cl < need and not (E[low]["walk"] and not E[low]["drive"] and cl < 0.3 and not E[top]["drive"]):
                if E[low]["drive"] or E[top]["drive"]:
                    self.add("headroom", x, y, need - cl, f"{self.name(low)} under {self.name(top)}: {max(cl, 0):.1f} m clear, needs {need:.1f}",
                             edges=[top, low], clear=round(cl, 2), need=need)
            return
        ri, rj = self.roads[e["road"]], self.roads[f["road"]]
        if ri.get("tunnel") or rj.get("tunnel"):
            return
        if not (e["drive"] and f["drive"]):
            return                                           # a path over a street: a crossing, drawn on the road
        self.add("flat_cross", x, y, 1, f"{self.name(i)} x {self.name(j)} (layers {li[1]}/{lj[1]})", edges=[i, j],
                 layers=[li[1], lj[1]])

    # ---------------------------------------------------------------- bridges
    def bridges(self):
        import roads3d
        E, T = self.edges, self.T
        by_road = collections.defaultdict(list)
        for i, e in enumerate(E):
            if e["bridge"] and (e["drive"] or e["walk"]):
                by_road[e["road"]].append(i)
        for ri, lst in by_road.items():
            r = self.roads[ri]
            if ri not in self.decks:
                if r["drive"]:
                    p = r["pts"][len(r["pts"]) // 2]
                    self.add("flat_bridge", p[0], p[1], 1, f"{r.get('name') or r['cls']}: no deck", road=ri)
                continue
            d = self.decks[ri]
            if not r["drive"] or d.len < 6:
                continue
            # ends: step to the ground / to the next deck, approach grade
            for end, (p, h) in enumerate(((d.pts[0], d.h[0]), (d.pts[-1], d.h[-1]))):
                g = T.hs(*p)
                nb = [q for q in self.decks_at(p) if q is not d]
                if nb:
                    hn = min(nb, key=lambda q: q.at(*p)[2]).at(*p)[0]
                    if abs(hn - h) > 0.15:
                        self.add("deck_joint", p[0], p[1], abs(hn - h), f"{r.get('name') or r['cls']}: deck pieces {abs(hn - h):.2f} m apart", road=ri)
                elif abs(h - g) > 0.15:
                    self.add("deck_step", p[0], p[1], abs(h - g), f"{r.get('name') or r['cls']}: {h - g:+.2f} m step to the road", road=ri)
                if not nb:
                    gr = self.approach_grade(ri, p, d, end)
                    if gr is not None and gr > 0.12:
                        self.add("approach_grade", p[0], p[1], gr, f"{r.get('name') or r['cls']}: approach {100 * gr:.0f} %", road=ri)
            worst = 0.0
            wk = 0
            for k in range(len(d.pts) - 3):
                L = d.cum[k + 3] - d.cum[k]
                if L > 4:
                    g_ = abs(d.h[k + 3] - d.h[k]) / L
                    if g_ > worst and g_ > self.hill(d.pts[k], d.pts[k + 3]) + 0.03:
                        worst, wk = g_, k
            if worst > 0.10:
                p = d.pts[wk]
                self.add("deck_grade", p[0], p[1], worst, f"{r.get('name') or r['cls']}: {100 * worst:.0f} % on the deck", road=ri)
            # side streets joining mid-deck
            for i in lst:
                for n in (E[i]["a"], E[i]["b"]):
                    p = self.pos[n]
                    _, s, _ = d.at(*p)
                    if 3.0 < s < d.len - 3.0 and self.ddeg.get(n, 0) >= 3 and any(not E[j]["bridge"] for j, _ in self.inc[n] if E[j]["drive"]):
                        self.add("junction_on_deck", p[0], p[1], abs(d.at(*p)[0] - T.hs(*p)), f"{r.get('name') or r['cls']}: side street joins the deck", node=n, road=ri)
        self.twins(by_road)

    def decks_at(self, p, r=1.5):
        out = []
        for j, m in self.grid.near(p[0], p[1], r):
            e = self.edges[j]
            d = self.decks.get(e["road"]) if e["bridge"] else None
            if d is not None and d not in out:
                for q in (d.pts[0], d.pts[-1]):
                    if math.hypot(q[0] - p[0], q[1] - p[1]) < r:
                        out.append(d)
                        break
        return out

    def hill(self, p, q):
        """Grade of the natural hillside (terrain grid without cuttings and embankments) from p to q."""
        T = self.T
        def raw(x, y):
            fx = min(max((x + T.hx) / 10.0, 0.0), T.nx - 1.001)
            fy = min(max((y + T.hy) / 10.0, 0.0), T.ny - 1.001)
            ix, iy, tx, ty = int(fx), int(fy), fx - int(fx), fy - int(fy)
            g = T.g
            return float((g[iy, ix] * (1 - tx) + g[iy, ix + 1] * tx) * (1 - ty) + (g[iy + 1, ix] * (1 - tx) + g[iy + 1, ix + 1] * tx) * ty)
        L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
        return abs(raw(*q) - raw(*p)) / L

    def approach_grade(self, ri, p, d, end):
        """Steepest 6 m grade of the ground over the 30 m of road beyond the deck end."""
        n = None
        for i, e in enumerate(self.edges):
            pass
        best = None
        for j, m in self.grid.near(p[0], p[1], 1.0):
            e = self.edges[j]
            if e["bridge"] or not e["drive"]:
                continue
            P = e["pts"]
            if math.hypot(P[0][0] - p[0], P[0][1] - p[1]) < 1.0:
                seq = P
            elif math.hypot(P[-1][0] - p[0], P[-1][1] - p[1]) < 1.0:
                seq = P[::-1]
            else:
                continue
            import terrain
            pts, cum = terrain.resample(seq, 2.0)
            hs = [self.T.hs(*q) for q in pts]
            for k in range(len(pts)):
                if cum[k] > 30:
                    break
                for k2 in range(k + 1, len(pts)):
                    if cum[k2] - cum[k] >= 6:
                        g = abs(hs[k2] - hs[k]) / (cum[k2] - cum[k])
                        if g > self.hill(pts[k], pts[k2]) + 0.03:          # (a hill street just as steep is no fault of the bridge)
                            best = max(best or 0.0, g)
                        break
        return best

    def twins(self, by_road):
        """Pairs of parallel drivable decks side by side (the two carriageways of a dual road)."""
        import roads3d
        SW = roads3d.BRIDGE_SW
        E = self.edges
        dg = Grid(25.0)
        items = [(ri, self.decks[ri]) for ri, lst in by_road.items() if ri in self.decks and self.roads[ri]["drive"]]
        for k, (ri, d) in enumerate(items):
            for a, b in zip(d.pts, d.pts[1:]):
                dg.add_seg(k, a, b, 20.0)
        self.twin_pairs = []
        for k, (ri, d) in enumerate(items):
            hw = self.roads[ri]["w"] / 2
            for k2 in set(dg.near(d.pts[len(d.pts) // 2][0], d.pts[len(d.pts) // 2][1], d.len / 2 + 20)):
                if k2 <= k:
                    continue
                rj, d2 = items[k2]
                hw2 = self.roads[rj]["w"] / 2
                n_tw = n_ov = 0
                mism = 0.0
                gaps = []
                samp = 0
                for q in range(0, len(d.pts) - 1):
                    (x, y), (x2, y2) = d.pts[q], d.pts[q + 1]
                    tx, ty = x2 - x, y2 - y
                    L = math.hypot(tx, ty) or 1.0
                    tx, ty = tx / L, ty / L
                    samp += 1
                    h2, s2, lat = d2.at(x, y)
                    if s2 <= 0.5 or s2 >= d2.len - 0.5:
                        continue
                    gap = lat - hw - hw2
                    if gap > 2 * SW + 4.0:
                        continue
                    # direction of d2 there
                    j_ = 0
                    while j_ < len(d2.cum) - 2 and d2.cum[j_ + 1] < s2:
                        j_ += 1
                    ux, uy = d2.pts[j_ + 1][0] - d2.pts[j_][0], d2.pts[j_ + 1][1] - d2.pts[j_][1]
                    ul = math.hypot(ux, uy) or 1.0
                    if abs(tx * ux / ul + ty * uy / ul) < 0.93:
                        continue
                    n_tw += 1
                    gaps.append(gap)
                    h1 = d.h[q]
                    g1, g2 = self.T.hs(x, y), self.T.hs(*d2.pts[j_])
                    if abs(h1 - g1) > 0.3 or abs(h2 - g2) > 0.3:      # (both landed on their own ground: the bank's slope)
                        mism = max(mism, abs(h1 - h2))
                if n_tw >= 3 and n_tw >= 0.3 * samp:
                    i0 = by_road[ri][0]
                    gm = sorted(gaps)[len(gaps) // 2]
                    p = d.pts[len(d.pts) // 2]
                    self.twin_pairs.append((ri, rj, gm))
                    self.add("median_pavement", p[0], p[1], 2 * SW, f"{self.name(i0)}: twin decks {gm:.1f} m apart, {2 * SW:.1f} m of pavement + 2 parapets in the median",
                             roads=[ri, rj], gap=round(gm, 2), share=round(n_tw / samp, 2))
                    if mism > 0.3:
                        self.add("twin_mismatch", p[0], p[1], mism, f"{self.name(i0)}: twin decks up to {mism:.2f} m apart in height", roads=[ri, rj])

    def medians(self):
        """Ground-level dual carriageways whose pavements overlap in a narrow median."""
        import roads3d
        E = self.edges
        SW = roads3d.SW_W
        seen = set()
        for i, e in enumerate(E):
            if not e["drive"] or not e["ow"] or e["bridge"] or roads3d._base(e["cls"]) not in {roads3d._base(c) for c in roads3d.SIDEWALK} or e["len"] < 20:
                continue
            hw = e["w"] / 2
            P = e["pts"]
            hits = collections.Counter()
            samp = 0
            for k in range(len(P) - 1):
                (x, y), (x2, y2) = P[k], P[k + 1]
                L = math.hypot(x2 - x, y2 - y)
                if L < 1:
                    continue
                tx, ty = (x2 - x) / L, (y2 - y) / L
                mx, my = (x + x2) / 2, (y + y2) / 2
                samp += 1
                for j, m in self.grid.near(mx, my, hw + 2 * SW + 8):
                    f = E[j]
                    if j == i or not f["drive"] or not f["ow"] or f["bridge"] or f["road"] == e["road"]:
                        continue
                    a, b = f["pts"][m], f["pts"][m + 1]
                    d, t = pdist(mx, my, *a, *b)
                    ul = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
                    if (tx * (b[0] - a[0]) + ty * (b[1] - a[1])) / ul > -0.95:
                        continue                                  # not running the other way alongside
                    gap = d - hw - f["w"] / 2
                    if 0.2 < gap < 2 * SW - 0.3:
                        hits[j] += 1
            for j, c in hits.items():
                if c >= 2 and (min(i, j), max(i, j)) not in seen:
                    seen.add((min(i, j), max(i, j)))
                    p = P[len(P) // 2]
                    self.add("median_overlap", p[0], p[1], c, f"{self.name(i)}: median narrower than two pavements", edges=[i, j])

    # ---------------------------------------------------------------- railway
    def railway(self):
        E = self.edges
        lc = [r[0][2:4] if isinstance(r[0], list) else r[2:4] for r in self.rail if (r[0] == "node" and r[1] in ("level_crossing", "crossing"))]
        lines = [r for r in self.rail if r[0] == "way" and r[1] == "rail"]
        n_lc = 0
        for r in lines:
            pts, br, tun = r[4], r[2], r[3]
            if tun:
                continue
            for k in range(len(pts) - 1):
                a, b = pts[k], pts[k + 1]
                for j, m in self.grid.near((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + 1):
                    f = E[j]
                    if not f["drive"]:
                        continue
                    h = seg_hit(a, b, f["pts"][m], f["pts"][m + 1], 0.0)
                    if not h:
                        continue
                    x, y = h[0], h[1]
                    if f["bridge"]:
                        d = self.deck_of(j)
                        if d is not None:
                            cl = d.at(x, y)[0] - SLAB - self.T.hs(x, y)
                            if cl < 5.0:
                                self.add("rail_headroom", x, y, 5.0 - cl, f"{self.name(j)} over the railway: {cl:.1f} m (estimate from the ground)", edge=j)
                        continue
                    if br or self.roads[f["road"]].get("tunnel"):
                        continue
                    n_lc += 1                   # tools/rail.py builds a level crossing (barriers, stop line) at every one
                    if not any(math.hypot(q[0] - x, q[1] - y) < 12 for q in lc):
                        self.inv["rail level crossings added (not tagged in OSM)"] = self.inv.get("rail level crossings added (not tagged in OSM)", 0) + 1
        self.inv["rail level crossings (street x track)"] = n_lc

    # ---------------------------------------------------------------- mesh (optional)
    def mesh(self, jobs=4):
        """3D road mesh of the whole city (tools/roads3d.py, real terrain and decks), every drivable junction rasterised."""
        import roads3d
        import sidewalk_audit as sa
        got = collections.defaultdict(list)
        CH = 120.0

        def chunk_of(x, z):
            return (int(math.floor(x / CH)), int(math.floor(z / CH)))
        roads3d.PIER_SKIP = lambda x, y, r: False
        roads3d.build(self.edges, [], lambda key, mat, pos, uv, col: got[key].append((pos, col)), chunk_of, 3, T=self.T, decks=self.decks)
        W = _MeshWorld(self.edges, got)
        wins = sa.junction_windows(W, False)
        bad = 0
        for node, x, y, deg, ang in wins:
            if not self.inside(x, y):
                continue
            r = _junction_mesh(sa, W, x, y)
            for kind, key, lim in (("mesh_hole", "hole", 2.0), ("mesh_inlane", "inlane", 2.0), ("mesh_zfight", "zfight", 2.0), ("mesh_spike", "spike", 0)):
                if r[key] > lim:
                    self.add(kind, x, y, r[key], f"{r[key]} {'triangles' if key == 'spike' else 'm2'} in the junction window (degree {deg}, sharpest {ang} deg)", node=node)
                    bad += 1
        self.inv["junction windows rasterised"] = len(wins)
        dump = {"edges": self.edges, "T": self.T, "decks": self.decks}
        for f in self.find:
            if f["kind"] not in ("median_pavement", "median_overlap"):
                continue
            if f["kind"] == "median_pavement":
                ea = [i for i, e in enumerate(self.edges) if e["road"] == f["roads"][0] and e["drive"]] or None
                eb = [i for i, e in enumerate(self.edges) if e["road"] == f["roads"][1] and e["drive"]] or None
            else:
                ea, eb = f["edges"]
            if ea is None or eb is None:
                continue
            a_, sep = _median_pavement(dump, ea, eb, f["x"], f["y"], overlap=f["kind"] == "median_overlap")
            f["mesh_pavement_m2"] = round(a_, 1)
        return W


def _junction_mesh(sa, world, cx, cy):
    """tools/sidewalk_audit.py's window test, made strict: a hole is ground showing inside the drivable lanes (a missing
    pavement beside a road is not a hole), and spikes count only asphalt / pavement triangles (not the long thin lane lines)."""
    import numpy as np
    R, PX = sa.R, sa.PX
    n = int(2 * R / PX)
    tris, cols = sa.load_tris(world, cx, cy, R + 4)
    res = dict(zfight=0.0, inlane=0.0, hole=0.0, spike=0)
    if not len(tris):
        return res
    H, HP, HA, cov, img = sa.raster(tris, cols, cx, cy, n)
    px2 = PX * PX
    both = (HP > -1e8) & (HA > -1e8) & (abs(HP - HA) < 0.04)
    lane, span = sa.corridor(world, cx, cy, n)
    inlane = (HP > -1e8) & lane & ~(HA > HP + 0.05)
    hole = lane & ~cov
    res["zfight"], res["inlane"], res["hole"] = round(float(both.sum() * px2), 1), round(float(inlane.sum() * px2), 1), round(float(hole.sum() * px2), 1)
    surf = sa.is_pavement(cols) | sa.is_asphalt(cols)
    ed = np.maximum.reduce([np.hypot(*(tris[:, i, [0, 2]] - tris[:, (i + 1) % 3, [0, 2]]).T) for i in range(3)])
    u, v = tris[:, 1, [0, 2]] - tris[:, 0, [0, 2]], tris[:, 2, [0, 2]] - tris[:, 0, [0, 2]]
    ar = 0.5 * abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
    inwin = (abs(tris[:, :, 0].mean(1) - cx) < R) & (abs(tris[:, :, 2].mean(1) - cy) < R)
    flat = abs(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])[:, 1]) > 1e-6
    thin = (ed > 6.0) & (2 * ar / np.maximum(ed, 1e-6) < 0.05)
    res["spike"] = int((inwin & surf & flat & ((ed > 25.0) | thin)).sum())
    return res


def _median_pavement(dump, ea, eb, x, y, r=30.0, overlap=False):
    """Area (m2) of raised pavement drawn between the two carriageways ea, eb (edges) near (x, y), and the area of the
    median itself there, from the real road mesh (tools/roads3d.py) of the window."""
    import numpy as np
    import road_shot
    import sidewalk_audit as sa
    pos, col = road_shot.road_mesh(dump, x, y, r)
    if not len(pos):
        return 0.0, 0.0
    t = pos.reshape(-1, 3, 3)
    c = col.reshape(-1, 3, 4)[:, 0, :3]
    up = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])[:, 1] > 1e-6
    cen = t.mean(1)
    near = (abs(cen[:, 0] - x) < r) & (abs(cen[:, 2] - y) < r)
    pav = sa.is_pavement(c) & up & near
    E = dump["edges"]

    ea, eb = ([e] if isinstance(e, int) else list(e) for e in (ea, eb))

    def dist(es, px, pz):
        best = np.full(len(px), 1e9)
        for (ax, ay), (bx, by) in ((s_, t_) for e in es for s_, t_ in zip(E[e]["pts"], E[e]["pts"][1:])):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            tt = ((px - ax) * dx + (pz - ay) * dy) / l2              # beside the way only (not past its ends)
            best = np.minimum(best, np.where((tt > 0) & (tt < 1), np.hypot(px - ax - dx * tt, pz - ay - dy * tt), 1e9))
        return best
    idx = np.nonzero(pav)[0]
    if not len(idx):
        return 0.0, 0.0
    da, db = dist(ea, cen[idx, 0], cen[idx, 2]), dist(eb, cen[idx, 0], cen[idx, 2])
    hwa, hwb = E[ea[0]]["w"] / 2, E[eb[0]]["w"] / 2
    qa = np.array([(a_[0] + (b_[0] - a_[0]) * f_, a_[1] + (b_[1] - a_[1]) * f_) for e in ea for a_, b_ in zip(E[e]["pts"], E[e]["pts"][1:])
                   for f_ in np.linspace(0.05, 0.95, 19)])
    sa_ = dist(eb, qa[:, 0], qa[:, 1])
    sa_ = sa_[sa_ < 1e8]
    if not len(sa_):
        return 0.0, 0.0
    sep = float(np.median(sa_))
    inside = (da > hwa - 0.2) & (db > hwb - 0.2) & (da + db < sep + 0.6)
    dk = [dump["decks"].get(E[e_[0]]["road"]) if E[e_[0]]["bridge"] else None for e_ in (ea, eb)]
    hs = []
    for q in idx:                                          # raised pavement: 8..35 cm above the carriageway it belongs to
        px, ph, pz = cen[q]
        ref = [d_.at(px, pz)[0] for d_ in dk if d_ is not None] or [float(dump["T"].hs(px, pz))]
        hs.append(min(abs(ph - v - 0.16) for v in ref))
    inside &= np.array(hs) < 0.14
    u, v = t[idx, 1] - t[idx, 0], t[idx, 2] - t[idx, 0]
    ar = 0.5 * abs(u[:, 0] * v[:, 2] - u[:, 2] * v[:, 0])
    if not overlap:
        return float(ar[inside].sum()), float(sep)
    PX = 0.2                                              # overlap: pavement drawn twice (two pavements on top of each other)
    n = int(2 * r / PX)
    cnt = np.zeros((n, n), np.int16)
    for q in idx[inside]:
        a, b, c3 = t[q]
        xs, zs = np.array([a[0], b[0], c3[0]]), np.array([a[2], b[2], c3[2]])
        x0, x1 = max(0, int((xs.min() - x + r) / PX)), min(n, int((xs.max() - x + r) / PX) + 1)
        z0, z1 = max(0, int((zs.min() - y + r) / PX)), min(n, int((zs.max() - y + r) / PX) + 1)
        if x1 <= x0 or z1 <= z0:
            continue
        gx, gz = np.meshgrid(x - r + (np.arange(x0, x1) + 0.5) * PX, y - r + (np.arange(z0, z1) + 0.5) * PX)
        d = (b[2] - c3[2]) * (a[0] - c3[0]) + (c3[0] - b[0]) * (a[2] - c3[2])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[2] - c3[2]) * (gx - c3[0]) + (c3[0] - b[0]) * (gz - c3[2])) / d
        l2 = ((c3[2] - a[2]) * (gx - c3[0]) + (a[0] - c3[0]) * (gz - c3[2])) / d
        cnt[z0:z1, x0:x1] += ((l1 >= 0) & (l2 >= 0) & (1 - l1 - l2 >= 0)).astype(np.int16)
    return float((cnt >= 2).sum() * PX * PX), float(sep)


class _MeshWorld:
    """Just enough of src/world.World for tools/sidewalk_audit.py: edges + chunked road triangles."""

    def __init__(self, edges, got):
        import numpy as np
        self.edges = edges
        self.chunks, self._a = {}, {}
        for k, lst in got.items():
            pos = np.concatenate([np.asarray(p, np.float32).reshape(-1, 3) for p, _ in lst])
            col = np.concatenate([np.asarray(c, np.uint8).reshape(-1, 4) for _, c in lst])
            self._a[k] = (pos, col)
            self.chunks[k] = {"m": {3: (k, len(pos) // 3)}}

    def mesh_arrays(self, off, n):
        pos, col = self._a[off]
        return pos, None, col


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("out")
    ap.add_argument("--rail", default="")
    ap.add_argument("--mesh", action="store_true")
    ap.add_argument("--box", default="")
    a = ap.parse_args()
    with open(a.dump, "rb") as f:
        dump = pickle.load(f)
    rail = json.load(open(a.rail)) if a.rail else []
    box = tuple(float(v) for v in a.box.split(",")) if a.box else None
    A = Audit(dump, rail, box)
    import time
    t0 = time.time()
    A.inventory()
    A.graph()
    print(f"[audit] graph {time.time() - t0:.0f}s")
    A.bridges()
    A.medians()
    A.railway()
    print(f"[audit] bridges / medians / rail {time.time() - t0:.0f}s")
    if a.mesh:
        A.mesh()
        print(f"[audit] mesh {time.time() - t0:.0f}s")
    counts = collections.Counter(f["kind"] for f in A.find)
    json.dump({"inventory": dict(A.inv), "findings": A.find, "counts": dict(counts), "kinds": KINDS}, open(a.out, "w"), ensure_ascii=False, indent=0)
    print("[audit] inventory:")
    for k, v in sorted(A.inv.items()):
        print(f"   {k:48s} {v}")
    print("[audit] findings:")
    for k in KINDS:
        if counts.get(k):
            print(f"   {k:18s} {counts[k]:6d}  {KINDS[k][1]}")


if __name__ == "__main__":
    main()
