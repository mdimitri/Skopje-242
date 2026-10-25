"""Procedural street furniture: traffic lights, signs, crosswalks, bridge parapets, bus stops, benches, bins.

Called by build_world.py once the routing graph exists. Everything is derived from the road graph, so it also
works on the synthetic demo city. Geometry is plain numpy triangles (material 'solid', vertex colours).
"""
import bisect
import math
import random

import numpy as np

SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)
RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1,
        "living_street": 0, "service": 0}


def _sh(n):
    return 0.52 + 0.55 * max(0.0, float(np.dot(n, SUN)))


class G:
    """Triangle soup builder for one prop. x east, y up, z south."""

    def __init__(self):
        self.p, self.c = [], []

    def tri(self, a, b, c, col, n):
        s = _sh(np.array(n, float))
        self.p += [a, b, c]
        self.c += [(*[min(255, v * s) for v in col], 255)] * 3

    def quad(self, a, b, c, d, col, n):
        self.tri(a, b, c, col, n)
        self.tri(a, c, d, col, n)

    def box(self, cx, y0, cz, sx, sy, sz, col, yaw=0.0):
        ca, sa = math.cos(yaw), math.sin(yaw)
        hx, hz = sx / 2, sz / 2
        w = [(cx + ca * x - sa * z, cz + sa * x + ca * z) for x, z in ((-hx, -hz), (hx, -hz), (hx, hz), (-hx, hz))]
        for i in range(4):
            a, b = w[i], w[(i + 1) % 4]
            nx, nz = b[1] - a[1], -(b[0] - a[0])
            l = math.hypot(nx, nz) or 1.0
            self.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + sy, b[1]), (a[0], y0 + sy, a[1]), col, (nx / l, 0, nz / l))
        self.quad((w[0][0], y0 + sy, w[0][1]), (w[1][0], y0 + sy, w[1][1]), (w[2][0], y0 + sy, w[2][1]),
                  (w[3][0], y0 + sy, w[3][1]), col, (0, 1, 0))

    def vpoly(self, cx, cy, cz, fx, fz, pts, col, off=0.0):
        """Vertical polygon (fan) in the plane facing (fx, fz); pts are (u, v) with u along the plate's right."""
        tx, tz = -fz, fx
        n = (fx, 0, fz)
        P = [(cx + fx * off + tx * u, cy + v, cz + fz * off + tz * u) for u, v in pts]
        for i in range(1, len(P) - 1):
            self.tri(P[0], P[i], P[i + 1], col, n)

    def out(self):
        pos = np.array(self.p, np.float32)
        return pos, np.zeros((len(pos), 2), np.float32), np.array(self.c, np.uint8)


def _ngon(r, n, rot=0.0, cy=0.0):
    return [(r * math.cos(rot + 2 * math.pi * i / n), cy + r * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]


def signal_pole(x, z, fx, fz, rx, rz, lit, arm=0.75, mast=False):
    """Kerb pole with a head hanging over the road; mast=True: a tall pole whose arm reaches `arm` m over the lanes and carries the head."""
    g = G()
    col = (62, 64, 70)
    hb = 4.75 if mast else 2.95                                 # underside of the housing
    g.box(x, 0, z, 0.2 if mast else 0.14, 6.1 if mast else 3.9, 0.2 if mast else 0.14, col)
    hx, hz = x - rx * arm, z - rz * arm                         # housing hangs over the road
    if mast:
        g.box(x - rx * arm / 2, 5.75, z - rz * arm / 2, 0.14 + abs(rx) * arm, 0.12, 0.14 + abs(rz) * arm, col)
    else:
        g.box(x - rx * 0.38, 3.55, z - rz * 0.38, 0.1 + abs(rx) * 0.7, 0.07, 0.1 + abs(rz) * 0.7, col)
    g.box(hx, hb, hz, 0.34, 1.05, 0.34, (28, 28, 32))
    cols = ((230, 40, 40), (240, 190, 30), (50, 220, 90))
    for k, c in enumerate(cols):
        on = (k == lit)                                         # lit = -1: all dark, the game draws the live lamp
        cc = c if on else tuple(int(v * 0.22) for v in c)
        g.vpoly(hx, hb + 0.05 + 0.30 * (2 - k) + 0.12, hz, fx, fz, _ngon(0.1, 8, 0.4), cc, 0.18)
    if lit >= 0:
        g.box(hx, hb + 1.05, hz, 0.38, 0.05, 0.38, tuple(cols[lit]))    # lit lamp is also visible from above
    return g


_BUS_GLYPHS = {"B": ("110", "101", "110", "101", "110"), "U": ("101", "101", "101", "101", "111"),
               "S": ("111", "100", "111", "001", "111")}


def bus_text(x, z, tx, tz, hs=None):
    """White BUS painted on the road at (x, z) for traffic driving along (tx, tz): the first letter nearest the driver, tops pointing ahead; hs(x, z) = terrain height, so the letters follow a sloping road."""
    g = G()
    h0 = hs(x, z) if hs else 0.0
    rx, rz = -tz, tx                                           # across the lane
    cw, ch, gap = 0.3, 0.42, 0.7
    for li, ch_ in enumerate("SUB"):                            # read top to bottom, so the word's first letter is the farthest one
        base = (li - 1) * (5 * ch + gap)
        for row, bits in enumerate(_BUS_GLYPHS[ch_]):
            along = base + (2 - row) * ch
            for col in range(3):
                if bits[col] == "1":
                    across = (col - 1) * cw
                    bx, bz = x + tx * along + rx * across, z + tz * along + rz * across
                    y_ = 0.15 + (hs(bx, bz) - h0 if hs else 0.0)             # a flat quad facing up (a box's own top faces down seen from above)
                    c_ = [(bx + tx * du + rx * dv, y_, bz + tz * du + rz * dv) for du, dv in ((-ch / 2, -cw / 2), (ch / 2, -cw / 2), (ch / 2, cw / 2), (-ch / 2, cw / 2))]
                    g.quad(c_[0], c_[3], c_[2], c_[1], (236, 234, 224), (0, 1, 0))
    return g


def sign(x, z, fx, fz, kind):
    g = G()
    g.box(x, 0, z, 0.08, 2.5, 0.08, (150, 152, 158))
    cy = 2.75
    if kind == "stop":
        g.vpoly(x, cy, z, fx, fz, _ngon(0.42, 8, math.pi / 8), (200, 28, 30), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.30, -0.06), (0.30, -0.06), (0.30, 0.06), (-0.30, 0.06)], (240, 240, 240), 0.07)
    elif kind == "yield":
        g.vpoly(x, cy, z, fx, fz, [(-0.5, 0.42), (0.5, 0.42), (0.0, -0.4)], (200, 28, 30), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.3, 0.32), (0.3, 0.32), (0.0, -0.12)], (245, 245, 245), 0.07)
    elif kind == "priority":
        g.vpoly(x, cy, z, fx, fz, [(0, 0.5), (0.5, 0), (0, -0.5), (-0.5, 0)], (245, 245, 245), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(0, 0.4), (0.4, 0), (0, -0.4), (-0.4, 0)], (240, 190, 20), 0.07)
    elif kind.startswith("speed"):
        g.vpoly(x, cy, z, fx, fz, _ngon(0.4, 12), (200, 28, 30), 0.06)
        g.vpoly(x, cy, z, fx, fz, _ngon(0.30, 12), (245, 245, 245), 0.07)
        g.vpoly(x, cy, z, fx, fz, [(-0.16, -0.08), (0.16, -0.08), (0.16, 0.08), (-0.16, 0.08)], (30, 30, 34), 0.08)
    elif kind == "cross":
        g.vpoly(x, cy, z, fx, fz, [(-0.4, -0.4), (0.4, -0.4), (0.4, 0.4), (-0.4, 0.4)], (30, 90, 190), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(0, 0.28), (0.28, -0.26), (-0.28, -0.26)], (245, 245, 245), 0.07)
    elif kind == "oneway":
        g.vpoly(x, cy, z, fx, fz, [(-0.4, -0.4), (0.4, -0.4), (0.4, 0.4), (-0.4, 0.4)], (30, 90, 190), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.07, -0.3), (0.07, -0.3), (0.07, 0.05), (-0.07, 0.05)], (245, 245, 245), 0.07)
        g.vpoly(x, cy, z, fx, fz, [(-0.24, 0.05), (0.24, 0.05), (0.0, 0.32)], (245, 245, 245), 0.07)
    elif kind == "noentry":
        g.vpoly(x, cy, z, fx, fz, _ngon(0.4, 12), (200, 28, 30), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.3, -0.07), (0.3, -0.07), (0.3, 0.07), (-0.3, 0.07)], (245, 245, 245), 0.07)
    elif kind == "rail":
        g.vpoly(x, cy, z, fx, fz, [(-0.5, 0.42), (0.5, 0.42), (0.0, -0.4)], (200, 28, 30), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.3, 0.32), (0.3, 0.32), (0.0, -0.12)], (245, 245, 245), 0.07)
        for sg in (1, -1):
            g.vpoly(x, cy, z, fx, fz, [(-0.2, 0.2 * sg + 0.04), (0.2, -0.2 * sg + 0.04), (0.2, -0.2 * sg + 0.1), (-0.2, 0.2 * sg + 0.1)], (30, 30, 34), 0.08)
    elif kind == "bus":
        g.vpoly(x, cy, z, fx, fz, _ngon(0.4, 12), (30, 90, 190), 0.06)
        g.vpoly(x, cy, z, fx, fz, [(-0.24, -0.16), (0.24, -0.16), (0.24, 0.16), (-0.24, 0.16)], (245, 245, 245), 0.07)
    return g


def bus_shelter(x, z, yaw):
    g = G()
    ca, sa = math.cos(yaw), math.sin(yaw)          # along the road
    nx, nz = -sa, ca                                # towards the road side is +n or -n; we put the back wall on -n
    g.box(x, 2.35, z, 3.0, 0.1, 1.5, (50, 110, 130), yaw)
    for s in (-1, 1):
        g.box(x + ca * 1.4 * s, 0, z + sa * 1.4 * s, 0.1, 2.4, 0.1, (60, 62, 68))
    g.box(x - nx * 0.6, 0.4, z - nz * 0.6, 2.8, 1.8, 0.05, (150, 200, 215), yaw)             # glass back wall
    g.box(x - nx * 0.3, 0.0, z - nz * 0.3, 1.8, 0.45, 0.4, (120, 84, 56), yaw)               # bench
    return g


def bench(x, z, yaw):
    g = G()
    g.box(x, 0.4, z, 1.6, 0.07, 0.45, (130, 90, 56), yaw)
    ca, sa = math.cos(yaw), math.sin(yaw)
    g.box(x - sa * 0.22, 0.6, z + ca * 0.22, 1.6, 0.3, 0.06, (120, 82, 50), yaw)
    for s in (-0.7, 0.7):
        g.box(x + ca * s, 0.0, z + sa * s, 0.08, 0.4, 0.4, (60, 62, 66), yaw)
    return g


def bin_geo(x, z):
    g = G()
    g.box(x, 0, z, 0.42, 0.9, 0.42, (44, 100, 64))
    g.box(x, 0.9, z, 0.46, 0.06, 0.46, (30, 34, 34))
    return g


def parapet(x, z, yaw, length):
    g = G()
    g.box(x, 0, z, length, 0.95, 0.5, (192, 184, 166), yaw)
    g.box(x, 0.95, z, length, 0.08, 0.62, (146, 142, 130), yaw)
    return g


STOPS = []          # real bus stops placed by build(): (x, y, road dir x, road dir y, kerb x, kerb y, name)
def lanes_n(e):
    """Lanes per travel direction (same rule as roads3d.lanes_per_way)."""
    n, w = e.get("lanes", 0), e["w"]
    if e["ow"]:
        return n if n else max(1, int(round(w / 3.2)))
    return max(1, n // 2) if n else (2 if w >= 11.0 else 1)


SIGNALS = []        # (node, edge, end 0=a/1=b, group 0/1, lamp x, lamp z, junction x, junction z, housing height) - filled by build()


def build(edges, roads, is_water, not_building, add, chunk_of, half, to_cell=None, log=print, decks=None, add_abs=None, terrain_h=None,
          bus_stops=None, signals=None):
    """Returns (xwalks, posts, lamps). add(chunk, mat, pos, uv, col) puts geometry in the mesh accumulator."""
    rr = random.Random(2024)
    SIGNALS.clear()
    STOPS.clear()
    MAT = 3
    xw, posts, lamps = [], [], []
    counts = {"masts": 0, "lights": 0, "signs": 0, "cross": 0, "bridges": 0, "stops": 0, "benches": 0, "bins": 0, "junk": 0}

    # every ground-level drive road as segments in a 20 m grid: props never stand on a carriageway
    seg_grid = {}
    for e in edges:
        if e["drive"] and not e["bridge"]:
            hw = e["w"] / 2
            for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                for gx in range(int(min(ax, bx) // 20) - 1, int(max(ax, bx) // 20) + 2):
                    for gy in range(int(min(ay, by) // 20) - 1, int(max(ay, by) // 20) + 2):
                        seg_grid.setdefault((gx, gy), []).append((ax, ay, bx, by, hw))

    def on_road(x, z, clear=0.35):
        for ax, ay, bx, by, hw in seg_grid.get((int(x // 20), int(z // 20)), ()):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((x - ax) * dx + (z - ay) * dy) / l2))
            if (x - ax - dx * t) ** 2 + (z - ay - dy * t) ** 2 < (hw + clear) ** 2:
                return True
        return False

    skipped = [0]

    def put(g, x, z, check=True):
        if check and on_road(x, z):
            skipped[0] += 1
            return False
        pos, uv, col = g.out()
        if len(pos):
            add(chunk_of(x, z), MAT, pos, uv, col)
        return True

    def tz(x, z):
        return float(terrain_h(x, z)) if terrain_h else 0.0

    def put_abs(g, x, z, y):
        """Prop at an absolute height (bridge parapets follow the deck)."""
        pos, uv, col = g.out()
        if len(pos):
            pos = pos.copy()
            pos[:, 1] += y
            (add_abs or add)(chunk_of(x, z), MAT, pos, uv, col)

    def ok(x, z, margin=8):
        hx_, hy_ = half if isinstance(half, tuple) else (half, half)
        return abs(x) < hx_ - margin and abs(z) < hy_ - margin

    def at(e, s):
        pts, cum = e["pts"], e["cum"]
        s = min(max(s, 0.0), e["len"])
        i = min(max(bisect.bisect_right(cum, s) - 1, 0), len(pts) - 2)
        seg = cum[i + 1] - cum[i] or 1.0
        t = (s - cum[i]) / seg
        dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
        d = math.hypot(dx, dy) or 1.0
        return pts[i][0] + dx * t, pts[i][1] + dy * t, dx / d, dy / d

    # ---------------------------------------------------------------- junctions
    inc = {}
    for ei, e in enumerate(edges):
        if e["drive"] and not e["bridge"] and e["cls"] in RANK:
            inc.setdefault(e["a"], []).append((ei, 0))
            inc.setdefault(e["b"], []).append((ei, 1))
    light_cells = set()
    osm_sig = {}                                          # real traffic_signals nodes (fetch_extras), in a 40 m grid
    for sx, sy in signals or ():
        osm_sig.setdefault((int(sx // 40), int(sy // 40)), []).append((sx, sy))

    def osm_lit(x, y):
        return any((sx - x) ** 2 + (sy - y) ** 2 < 35.0 ** 2 for a in (-1, 0, 1) for b in (-1, 0, 1)
                   for sx, sy in osm_sig.get((int(x // 40) + a, int(y // 40) + b), ()))

    lit_osm = {n for n, lst in inc.items() if osm_sig and len(lst) >= 3 and osm_lit(
        *(edges[lst[0][0]]["pts"][0] if lst[0][1] == 0 else edges[lst[0][0]]["pts"][-1]))}

    lit_pts = []                                          # positions of every lit junction so far (real ones first)
    for n_ in lit_osm:
        _e, _end = inc[n_][0]
        lit_pts.append(edges[_e]["pts"][0] if _end == 0 else edges[_e]["pts"][-1])

    def inner(ei, end):
        """A short link between two lit nodes of one big junction: no lights inside the junction itself."""
        e = edges[ei]
        return e["len"] < 40.0 and (e["b"] if end == 0 else e["a"]) in lit_osm

    for node, lst in inc.items():
        if len(lst) < 3:
            continue
        e0, end0 = lst[0]
        nx_, ny_ = edges[e0]["pts"][0] if end0 == 0 else edges[e0]["pts"][-1]
        if not ok(nx_, ny_, 20):
            continue
        ranks = [RANK[edges[ei]["cls"]] for ei, _ in lst]
        top = max(ranks)
        maxw = max(edges[ei]["w"] for ei, _ in lst)
        cell = (int(nx_ // 70), int(ny_ // 70))
        if osm_sig:                                       # the real lights where the map has them, plus main junctions the map left out
            want_light = node in lit_osm or (len(lst) >= 3 and sum(1 for r in ranks if r >= 3) >= 2 and not any(
                (nx_ - qx_) ** 2 + (ny_ - qy_) ** 2 < 110.0 ** 2 for qx_, qy_ in lit_pts))
            if want_light and node not in lit_osm:
                lit_pts.append((nx_, ny_))
        else:
            want_light = sum(1 for r in ranks if r >= 2) >= 2 and not any(
                (cell[0] + a, cell[1] + b) in light_cells for a in (-1, 0, 1) for b in (-1, 0, 1))
        if want_light:
            light_cells.add(cell)
        phase = rr.randint(0, 1)
        e_a, end_a = max(lst, key=lambda q: RANK[edges[q[0]]["cls"]])           # the biggest road sets signal group 0
        _x, _y, ux0, uy0 = at(edges[e_a], 0.0 if end_a == 0 else edges[e_a]["len"])

        def head_only(ei, end):
            """A signal without a pole of its own (short approach, no room at the kerb): the lights still apply."""
            if inner(ei, end):
                return
            e = edges[ei]
            _p, _q, dx, dy = at(e, 0.0 if end == 0 else e["len"])
            grp = 0 if abs(dx * ux0 + dy * uy0) > 0.7 else 1
            SIGNALS.append((node, ei, end, grp, float("nan"), float("nan"), round(nx_, 1), round(ny_, 1), 2.95))

        for (ei, end), rk in zip(lst, ranks):
            e = edges[ei]
            if e["len"] < 16:
                if want_light:
                    head_only(ei, end)
                continue
            s0 = 0.0 if end == 0 else e["len"]
            sgn = 1 if end == 0 else -1
            d = maxw / 2 + 3.2
            px, py, dx, dy = at(e, s0 + sgn * d)
            ax, ay = dx * sgn, dy * sgn                   # unit vector pointing away from the junction
            rx, ry = ay, -ax                              # right-hand side for traffic approaching the junction
            w = e["w"]
            if not ok(px, py):
                if want_light:
                    head_only(ei, end)
                continue
            has_x = w >= 6.0 and e["len"] >= 30 and rr.random() < (0.9 if (want_light and rk >= 2) else 0.5 if rk >= 2 else 0.3)
            if has_x:
                xw.append((px, py, ax, ay, w, 1))
                counts["cross"] += 1
            fx, fy = ax, ay                               # signs face the approaching traffic
            lx, ly = px + ax * 3.8 + rx * (w / 2 + 1.0), py + ay * 3.8 + ry * (w / 2 + 1.0)
            if want_light and inner(ei, end):
                pass
            elif want_light:                              # right kerb, further back, else the left kerb; lamps lit live
                mast = w >= 9.0 and rk >= 2                  # wide main road: the head hangs from an arm over the lanes
                arm = min(w * 0.55, 8.0) if mast else 0.75
                for back, side in ((3.8, 1), (9.0, 1), (3.8, -1), (9.0, -1)):
                    qx, qy = px + ax * back + rx * (w / 2 + 1.0) * side, py + ay * back + ry * (w / 2 + 1.0) * side
                    if back < e["len"] - d and not_building(qx, qy) and ok(qx, qy) and put(
                            signal_pole(qx, qy, fx, fy, rx * side, ry * side, -1, arm, mast), qx, qy):
                        posts.append((qx, qy, 0.22))
                        counts["lights"] += 1
                        counts["masts"] += mast
                        grp = 0 if abs(ax * ux0 + ay * uy0) > 0.7 else 1
                        SIGNALS.append((node, ei, end, grp, round(qx - rx * side * arm, 2), round(qy - ry * side * arm, 2),
                                        round(nx_, 1), round(ny_, 1), 4.75 if mast else 2.95))
                        break
                else:
                    head_only(ei, end)                    # every approach of a lit junction gets its lights
            if not_building(lx, ly) and ok(lx, ly) and not want_light:
                if rk < top:
                    put(sign(lx, ly, fx, fy, "stop" if rr.random() < 0.55 else "yield"), lx, ly)
                    posts.append((lx, ly, 0.16))
                    counts["signs"] += 1
                elif rk == top and len(lst) >= 4 and rr.random() < 0.5:
                    put(sign(lx, ly, fx, fy, "priority"), lx, ly)
                    posts.append((lx, ly, 0.16))
                    counts["signs"] += 1
            if has_x:
                cx2, cy2 = px + ax * 1.6 + rx * (w / 2 + 1.0), py + ay * 1.6 + ry * (w / 2 + 1.0)
                if not_building(cx2, cy2) and ok(cx2, cy2) and rr.random() < 0.7:
                    put(sign(cx2, cy2, fx, fy, "cross"), cx2, cy2)
                    posts.append((cx2, cy2, 0.16))
                    counts["signs"] += 1

    # ---------------------------------------------------------------- along roads
    for ei, e in enumerate(edges):
        cls, L, w = e["cls"], e["len"], e["w"]
        r = random.Random(e["a"] * 7919 + e["b"] * 31)
        if e["drive"] and not e["bridge"] and cls in ("primary", "secondary", "tertiary", "trunk") and L > 70:
            s = r.uniform(25, 70)                          # speed limit signs
            while s < L - 30:
                x, y, dx, dy = at(e, s)
                rx, ry = dy, -dx
                px, py = x + rx * (w / 2 + 1.1), y + ry * (w / 2 + 1.1)
                if ok(px, py) and not_building(px, py) and r.random() < 0.5:
                    put(sign(px, py, -dx, -dy, "speed"), px, py)
                    posts.append((px, py, 0.16))
                    counts["signs"] += 1
                s += r.uniform(140, 260)
            s = r.uniform(60, 140) if not bus_stops else 1e18  # bus stops (random only when the map has none)
            while s < L - 40:
                if r.random() < 0.7:
                    x, y, dx, dy = at(e, s)
                    side = r.choice((1, -1))
                    rx, ry = dy * side, -dx * side
                    off = w / 2 + 2.3
                    px, py = x + rx * off, y + ry * off
                    if ok(px, py) and not_building(px, py) and not_building(px + rx * 1.2, py + ry * 1.2):
                        put(bus_shelter(px, py, math.atan2(dy, dx)), px, py)
                        put(sign(px + dx * 2.2, py + dy * 2.2, rx, ry, "bus"), px + dx * 2.2, py + dy * 2.2)
                        posts += [(px + dx * 1.4, py + dy * 1.4, 0.25), (px - dx * 1.4, py - dy * 1.4, 0.25)]
                        counts["stops"] += 1
                s += r.uniform(110, 200)
        if e["drive"] and not e["bridge"] and L > 30 and cls in RANK:      # one-way streets: the sign where they start, no entry where they end
            for end_, kind_ in ((0, "oneway"), (1, "noentry")):
                if e["ow"] and len(inc.get(e["a"] if end_ == 0 else e["b"], ())) >= 3:
                    s_ = 6.0 if end_ == 0 else L - 6.0
                    x, y, dx, dy = at(e, s_)
                    sd = 1 if end_ == 0 else -1                # entrance: right kerb, facing back to the approach; exit: left kerb, facing the wrong-way driver
                    px, py = x + dy * sd * (w / 2 + 1.1), y - dx * sd * (w / 2 + 1.1)
                    if ok(px, py) and not_building(px, py):
                        put(sign(px, py, -dx * sd, -dy * sd, kind_), px, py)
                        posts.append((px, py, 0.16))
                        counts["signs"] += 1
        if e["drive"] and not e["bridge"] and L > 120 and lanes_n(e) >= 3 and cls in RANK:      # bus lane along the right kerb lane
            s_ = r.uniform(30, 60)
            while s_ < L - 30:
                x, y, dx, dy = at(e, s_)
                px, py = x + dy * (w / 2 + 1.1), y - dx * (w / 2 + 1.1)
                if ok(px, py) and not_building(px, py):
                    put(sign(px, py, -dx, -dy, "bus"), px, py)
                    posts.append((px, py, 0.16))
                    counts["signs"] += 1
                s_ += r.uniform(180, 300)
        if e["drive"] and cls in ("primary", "secondary", "tertiary", "residential", "living_street") and L > 40:
            s = r.uniform(15, 40)                          # round 8: benches / bins on the pavement of city streets
            while s < L - 15:
                x, y, dx, dy = at(e, s)
                side = r.choice((1, -1))
                off = w / 2 + 1.9
                px, py = x + dy * side * off, y - dx * side * off
                if ok(px, py) and not_building(px, py):
                    if r.random() < 0.55:
                        put(bench(px, py, math.atan2(dy, dx) + (math.pi if side > 0 else 0.0)), px, py)
                        posts.append((px, py, 0.45))
                        counts["benches"] += 1
                    else:
                        put(bin_geo(px, py), px, py)
                        posts.append((px, py, 0.25))
                        counts["bins"] += 1
                s += r.uniform(30, 60)
        if not e["drive"] and e["walk"] and cls in ("footway", "pedestrian", "path", "cycleway") and L > 30:
            s = r.uniform(12, 30)
            while s < L - 10:
                x, y, dx, dy = at(e, s)
                side = r.choice((1, -1))
                px, py = x + dy * side * (w / 2 + 0.8), y - dx * side * (w / 2 + 0.8)
                if ok(px, py) and not_building(px, py):
                    if r.random() < 0.7:
                        put(bench(px, py, math.atan2(dy, dx)), px, py)
                        posts.append((px, py, 0.45))
                        counts["benches"] += 1
                    else:
                        put(bin_geo(px, py), px, py)
                        posts.append((px, py, 0.25))
                        counts["bins"] += 1
                s += r.uniform(9, 18)                       # round 8: 4x benches and bins

    # ---------------------------------------------------------------- bridges: parapets along the deck
    for ri, rd in enumerate(roads):
        if not rd["bridge"] or not (rd["drive"] or rd["walk"]):
            continue
        deck = (decks or {}).get(ri)
        pts, w = rd["pts"], rd["w"]
        hw = w / 2 + 0.55
        carried = False
        walked = 0.0
        for k in range(len(pts) - 1):
            (x1, y1), (x2, y2) = pts[k], pts[k + 1]
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 0.5:
                continue
            dx, dy = (x2 - x1) / L, (y2 - y1) / L
            n = max(1, int(L // 2.0))
            step = L / n
            for i in range(n):
                t = (i + 0.5) * step
                cx, cy = x1 + dx * t, y1 + dy * t
                walked += step
                for side in (-1, 1):
                    ox, oy = cx - dy * side * (w / 2 + 3.0), cy + dx * side * (w / 2 + 3.0)
                    px, py = cx - dy * side * hw, cy + dx * side * hw
                    if deck is not None:
                        dh = deck.at(px, py)[0]
                        high = dh - tz(px, py) > 0.6
                    else:
                        dh, high = 0.0, False
                    if not (is_water(ox, oy) or high) or not ok(cx, cy, 4):
                        continue
                    g = parapet(px, py, math.atan2(dy, dx), step + 0.08)
                    if deck is not None:
                        put_abs(g, px, py, dh)
                        posts.append((px, py, 0.5, dh - 0.3, dh + 1.0))
                    else:
                        put(g, px, py, False)
                        posts.append((px, py, 0.5))
                    carried = True
                    if rd["walk"] and int(walked / step) % 14 == 0:
                        lamps.append((px, py))
        if carried:
            counts["bridges"] += 1
    log(f"[build] furniture: {counts}")
    # ---------------------------------------------------------------- junk and garbage (round 10)
    import junk
    nj = 0
    for e in edges:
        cls, L, w = e["cls"], e["len"], e["w"]
        if e["bridge"] or L < 20 or cls in ("motorway", "trunk"):
            continue
        dens = {"residential": 0.5, "service": 0.6, "living_street": 0.6, "unclassified": 0.45, "footway": 0.35,
                "path": 0.4, "track": 0.5, "tertiary": 0.3, "secondary": 0.22, "primary": 0.15}.get(cls, 0.2)
        r = random.Random(e["a"] * 7919 + e["b"] * 31 + 5)
        s = r.uniform(4, 20)
        while s < L - 4:
            if r.random() < dens:
                x, y, dx, dy = at(e, s)
                side = r.choice((1, -1))
                off = w / 2 + r.uniform(1.4, 4.5)
                px, py = x + dy * side * off, y - dx * side * off
                i = r.choice(junk.STREET)
                if ok(px, py) and not_building(px, py) and not on_road(px, py, junk.footprint(i) + 0.3):
                    g = junk.make(i, px, py, r.uniform(0, 6.283), nj)
                    if put(g, px, py, False):
                        nj += 1
                        if junk.footprint(i) > 0.55:
                            posts.append((px, py, min(1.2, junk.footprint(i) * 0.8)))
            s += r.uniform(1.4, 2.6)
    counts["junk"] = nj

    n0 = len(posts)
    posts = [p for p in posts if len(p) > 3 or p[2] >= 0.5 or not on_road(p[0], p[1])]
    log(f"[build] junk and garbage: {nj} pieces; furniture kept off the roadway: {skipped[0]} props, {n0 - len(posts)} posts")
    if bus_stops:                                          # real bus stops from the map, on the kerb of the nearest road
        grid = {}
        for e in edges:
            if e["drive"] and not e["bridge"] and e["cls"] not in ("service", "track"):
                for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                    for gx in range(int(min(ax, bx) // 40) - 1, int(max(ax, bx) // 40) + 2):
                        for gy in range(int(min(ay, by) // 40) - 1, int(max(ay, by) // 40) + 2):
                            grid.setdefault((gx, gy), []).append((e, ax, ay, bx, by))
        for sx_, sy_, nm in bus_stops:
            best = None
            for e, ax, ay, bx, by in grid.get((int(sx_ // 40), int(sy_ // 40)), ()):
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy or 1.0
                t = max(0.0, min(1.0, ((sx_ - ax) * dx + (sy_ - ay) * dy) / l2))
                qx, qy = ax + dx * t, ay + dy * t
                d = math.hypot(sx_ - qx, sy_ - qy)
                if d < 30 and (best is None or d < best[0]):
                    best = (d, e, qx, qy, dx, dy)
            if best is None or not ok(sx_, sy_):
                continue
            d, e, qx, qy, dx, dy = best
            ln = math.hypot(dx, dy) or 1.0
            dx, dy = dx / ln, dy / ln
            rx, ry = dy, -dx
            side = 1 if (sx_ - qx) * rx + (sy_ - qy) * ry >= 0 else -1
            rx, ry = rx * side, ry * side
            off = e["w"] / 2 + 2.3
            px, py = qx + rx * off, qy + ry * off
            if not_building(px, py) and not is_water(px, py):
                put(bus_shelter(px, py, math.atan2(dy, dx)), px, py, False)
                put(sign(px + dx * 2.2, py + dy * 2.2, rx, ry, "bus"), px + dx * 2.2, py + dy * 2.2, False)
                posts += [(px + dx * 1.4, py + dy * 1.4, 0.25), (px - dx * 1.4, py - dy * 1.4, 0.25)]
                bx_, by_ = qx + rx * (e["w"] / 2 - 1.2), qy + ry * (e["w"] / 2 - 1.2)
                far = min(math.hypot(bx_ - e["pts"][0][0], by_ - e["pts"][0][1]), math.hypot(bx_ - e["pts"][-1][0], by_ - e["pts"][-1][1]))
                if e["w"] >= 5.5 and far > 12.0:
                    put(bus_text(bx_, by_, ry, -rx, tz), bx_, by_, False)      # traffic drives with the shelter on its right
                STOPS.append((round(px, 1), round(py, 1), round(dx, 3), round(dy, 3), round(qx + rx * (e["w"] / 2 - 1.2), 1),
                              round(qy + ry * (e["w"] / 2 - 1.2), 1), nm))
                counts["stops"] += 1
    return xw, posts, lamps
