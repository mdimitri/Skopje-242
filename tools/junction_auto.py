"""Rule-based junction layouts for real OSM junctions: read the arms of a graph node (direction, class, lanes), replace the
raw data by clean lane counts / medians / kerb radii, and draw it with the junction_design pieces.

    SK242_DUMP=roads.pkl xvfb-run -a python tools/junction_auto.py dump.pkl out_dir x,y [x,y ...]
"""
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "src"))
import junction_design as jd  # noqa: E402
from junction_design import ASPH, KERB, KFACE, KTOP, SW, Arm, Mesh, arm_details  # noqa: E402

CAP = {"motorway": 3, "trunk": 3, "primary": 3, "secondary": 3, "tertiary": 3, "unclassified": 1, "residential": 1,
       "living_street": 1, "service": 1}
LN = 85.0


def _base(cls):
    return cls.replace("_link", "")


def arms_at(edges, node):
    """Merge the drive edges at a node into arms: (angle, class, lanes per direction, dual carriageway?)."""
    raw = []
    for e in edges:
        if not e["drive"] or e["bridge"]:
            continue
        P = e["pts"]
        if e["a"] == node:
            q = [pt for pt in P[1:] if math.hypot(pt[0] - P[0][0], pt[1] - P[0][1]) >= 12.0] or [P[-1]]
            o, f = P[0], q[0]
            leaving = True
        elif e["b"] == node:
            R = P[::-1]
            q = [pt for pt in R[1:] if math.hypot(pt[0] - R[0][0], pt[1] - R[0][1]) >= 12.0] or [R[-1]]
            o, f = R[0], q[0]
            leaving = False
        else:
            continue
        ang = math.atan2(f[1] - o[1], f[0] - o[0])
        raw.append({"ang": ang, "e": e, "leaving": leaving})
    raw.sort(key=lambda r: r["ang"])
    groups = []
    for r in raw:
        for g in groups:
            d = (r["ang"] - g[0]["ang"] + math.pi) % (2 * math.pi) - math.pi
            if abs(d) < math.radians(22):
                g.append(r)
                break
        else:
            groups.append([r])
    arms = []
    for g in groups:
        top = max(g, key=lambda r: (jd_rank(r["e"]["cls"]), r["e"]["w"]))
        e = top["e"]
        cls = _base(e["cls"])
        dual = len(g) >= 2 and all(r["e"]["ow"] for r in g) and len({r["leaving"] for r in g}) == 2
        if dual:
            per = max(max(1, r["e"]["lanes"] or round(r["e"]["w"] / 3.5)) for r in g)
        elif e["ow"]:
            per = max(1, e["lanes"] or round(e["w"] / 3.5))
        else:
            dl = e.get("directional_lanes")
            per = max(dl) if dl else max(1, (e["lanes"] or round(e["w"] / 3.5)) // 2)
        per = max(1, min(per, CAP.get(cls, 1) if (dual or cls not in ("tertiary",)) else 2))
        a = sum(r["ang"] for r in g) / len(g) if len(g) == 1 else math.atan2(sum(math.sin(r["ang"]) for r in g), sum(math.cos(r["ang"]) for r in g))
        arms.append({"ang": a, "cls": cls, "per": per, "dual": dual})
    arms.sort(key=lambda r: r["ang"])
    return arms


def jd_rank(c):
    return {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2}.get(_base(c), 1)


def _solve(u1, p1, o1, u2, p2, o2):
    """Intersection of  u1 t + p1 o1  and  u2 w + p2 o2 -> (t, w) or None."""
    a, b = u1[0], -u2[0]
    c, d = u1[1], -u2[1]
    det = a * d - b * c
    if abs(det) < 1e-3:
        return None
    rx = p2[0] * o2 - p1[0] * o1
    ry = p2[1] * o2 - p1[1] * o1
    return ((rx * d - b * ry) / det, (a * ry - c * rx) / det)


def build(specs, m, R=9.0):
    arms = []
    for i, sp in enumerate(specs):
        u = (math.cos(sp["ang"]), math.sin(sp["ang"]))
        med = 0.0
        if sp["dual"]:
            med = 5.0 if sp["per"] >= 2 else 3.0
        a = Arm("N" if i % 2 == 0 else "E", u, sp["per"], sp["per"], med, 0.0)
        a.cls = sp["cls"]
        arms.append(a)
    n = len(arms)
    corners = []
    for k in range(n):
        a, b = arms[k], arms[(k + 1) % n]
        sr, sl = a.s_out_out(), b.s_out_in()
        sol = _solve(a.u, a.p, sr + R, b.u, b.p, sl - R)
        if sol is None or sol[0] < 0 or sol[1] < 0 or sol[0] > 70 or sol[1] > 70:
            corners.append(None)
            continue
        t, w = sol
        C = (a.u[0] * t + a.p[0] * (sr + R), a.u[1] * t + a.p[1] * (sr + R))
        f1 = (a.u[0] * t + a.p[0] * sr, a.u[1] * t + a.p[1] * sr)
        f2 = (b.u[0] * w + b.p[0] * sl, b.u[1] * w + b.p[1] * sl)
        corners.append({"t": t, "w": w, "C": C, "f1": f1, "f2": f2})
    for k, a in enumerate(arms):
        prev, nxt = corners[k - 1], corners[k]
        a.h = max(prev["w"] if prev else 0.0, nxt["t"] if nxt else 0.0) + 2.0
    def arc(C, f1, f2, rad):
        a1 = math.atan2(f1[1] - C[1], f1[0] - C[0])
        a2 = math.atan2(f2[1] - C[1], f2[0] - C[0])
        d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        return [(C[0] + rad * math.cos(a1 + d * i / 12), C[1] + rad * math.sin(a1 + d * i / 12)) for i in range(13)]
    outline, runs = [], []
    far = lambda a, s: (a.u[0] * (a.h + LN) + a.p[0] * s, a.u[1] * (a.h + LN) + a.p[1] * s)
    for k, a in enumerate(arms):
        prev, nxt = corners[k - 1], corners[k]
        sl_, sr_ = a.s_out_in(), a.s_out_out()
        if prev:
            outline.append(prev["f2"])
        outline += [far(a, sl_), far(a, sr_)]
        # pavement along the left edge (from the corner foot to the far end) and the right edge
        for side, s_, foot in ((-1, sl_, prev["f2"] if prev else None), (1, sr_, nxt["f1"] if nxt else None)):
            fe = far(a, s_)
            fe_o = far(a, s_ + side * SW)
            if foot is None:
                foot = (a.u[0] * a.h + a.p[0] * s_, a.u[1] * a.h + a.p[1] * s_)
            foot_o = (foot[0] + a.p[0] * side * SW, foot[1] + a.p[1] * side * SW)
            if side == 1:
                runs.append(([foot, fe], [foot_o, fe_o]))
            else:
                runs.append(([foot, fe], [foot_o, fe_o]))
        if nxt:
            outline.append(nxt["f1"])
            pa, pb = arc(nxt["C"], nxt["f1"], nxt["f2"], R), arc(nxt["C"], nxt["f1"], nxt["f2"], R - SW)
            outline += pa
            runs.append((pa, pb))
    m.poly(outline, 0.0, ASPH)
    for inner, outer in runs:
        m.strip(inner, outer, KERB, KTOP)
        m.wall(inner, 0.0, KERB, KFACE)
    for a in arms:
        arm_details(a, m, signals=(a.cls in ("tertiary", "secondary", "primary", "trunk")), Ln=LN, trees=True)
    return arms


def add_buildings(m, dump, cx, cy, r, arms):
    for ring, h in dump.get("buildings", ()):
        if not ring or abs(ring[0][0] - cx) > r or abs(ring[0][1] - cy) > r:
            continue
        pts = [(x - cx, y - cy) for x, y in ring]
        mx = sum(p[0] for p in pts) / len(pts)
        mz = sum(p[1] for p in pts) / len(pts)
        ok = True
        for a in arms:
            # distance of the footprint centre from the arm's axis band
            d = mx * a.u[0] + mz * a.u[1]
            sl = mx * a.p[0] + mz * a.p[1]
            if d > a.h - 5 and a.s_out_in() - SW - 4 < sl < a.s_out_out() + SW + 4:
                ok = False
        if math.hypot(mx, mz) < 28:
            ok = False
        if not ok:
            continue
        top = min(float(h), 30.0)
        n = len(pts)
        for i in range(n):
            (ax, ay), (bx, by) = pts[i], pts[(i + 1) % n]
            m.quad((ax, 0.0, ay), (bx, 0.0, by), (bx, top, by), (ax, top, ay), (200, 194, 184))
        try:
            m.poly(pts, top, (170, 164, 156))
        except Exception:  # noqa: BLE001
            pass


def main():
    dump = pickle.load(open(sys.argv[1], "rb"))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    import junction_scenes as js
    pos = [tuple(float(v) for v in a.split(",")) for a in sys.argv[3:]]
    E = dump["edges"]
    for i, (x, y) in enumerate(pos):
        node, bd = None, 1e9
        for e in E:
            for nd, pt in ((e["a"], e["pts"][0]), (e["b"], e["pts"][-1])):
                d = math.hypot(pt[0] - x, pt[1] - y)
                if d < bd:
                    node, bd, c = nd, d, pt
        specs = arms_at(E, node)
        print(i, "node", node, "at", [round(float(v)) for v in c], "arms", [(round(math.degrees(s["ang"])), s["cls"], s["per"], s["dual"]) for s in specs])
        m = Mesh()
        arms = build(specs, m)
        m.quad((-300, -0.3, -300), (300, -0.3, -300), (300, -0.3, 300), (-300, -0.3, 300), jd.GROUND)
        add_buildings(m, dump, float(c[0]), float(c[1]), 120.0, arms)
        js.render(m, out, {"aerial": ((55, 95, -95), (0, 0, 0)), "top": ((0, 160, 1), (0, 0, 0))}, f"design{i}")
        open(os.path.join(out, f"design{i}.txt"), "w").write(f"{float(c[0])},{float(c[1])}")


if __name__ == "__main__":
    main()
