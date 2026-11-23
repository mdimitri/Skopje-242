"""Road vault engine: a Scene (arms around a junction, optional roundabout ring, slip lanes, medians, crossings, signals)
turned into a triangle mesh.  Everything is a shapely polygon operation in plan view, then lifted: asphalt, kerbed
pavements, raised islands, paint clipped to the carriageway, furniture, cars, context buildings and sun shadows.

Plan coordinates (x, y) map to world (x, height, y).  Arm i leaves the junction along u=(cos a, sin a); d is the distance
along it, s the lateral offset (p = u rotated +90 deg).  Traffic drives on the right: inbound lanes sit at s < 0."""
import math
import random
from dataclasses import dataclass, field, replace
from typing import List, Optional

import numpy as np
from shapely.affinity import translate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from mesh import Mesh, polys

ASPH = (66, 68, 74)
ASPH2 = (74, 76, 82)
PAVE = (196, 192, 184)
PAVE_B = (188, 184, 176)
KERB_TOP = (218, 215, 208)
KERB_FACE = (170, 168, 162)
WHITE = (244, 244, 240)
YELLOW = (232, 196, 60)
GRASS = (108, 148, 84)
GRASS_D = (92, 132, 74)
GROUND = (126, 160, 98)
BIKE = (62, 142, 96)
BUSL = (160, 66, 58)
CONC = (178, 176, 170)
APRON = (200, 190, 170)
BALLAST = (132, 124, 112)
POLE = (70, 72, 78)
HEAD = (34, 35, 38)
KH = 0.15                                           # kerb height
Y_PAINT, Y_SURF = 0.022, 0.012
MED_W = {"none": 0.0, "paint": 1.6, "raised": 4.0, "grass": 6.0, "tram": 7.2}
CAR_COLS = [(176, 40, 38), (230, 230, 228), (36, 40, 46), (66, 98, 150), (150, 154, 158), (210, 180, 70), (72, 110, 84)]


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


@dataclass
class Arm:
    angle: float
    lin: int = 2                         # inbound lanes (towards the junction)
    lout: int = 2                        # outbound lanes
    lane_w: float = 3.25
    median: str = "none"                 # none | paint | raised | grass | tram
    med_w: Optional[float] = None
    flare_in: int = 0                    # extra inbound lanes on the approach
    flare_out: int = 0                   # extra outbound lanes on the exit
    flare_len: float = 42.0              # length of the widened stretch (from the junction edge)
    taper: float = 24.0
    pocket: int = 0                      # left-turn pocket carved out of the median (0 or 1)
    pocket_len: float = 40.0
    bike: bool = False
    bus: bool = False
    parking: bool = False
    walk: float = 3.0
    zebra: Optional[float] = 5.5         # distance from the junction edge to the crossing centre (None = no crossing)
    refuge: bool = True
    stop: str = "line"                   # line | yield | none
    signal: bool = False
    sign: Optional[str] = None           # priority | yield | stop
    arrows: Optional[list] = None        # per inbound lane, inner -> outer: T L R TL TR
    trees: bool = True
    lamps: bool = True
    L: float = 200.0
    start: float = 0.0
    slip: Optional[dict] = None          # right-turn bypass: {"R": 16, "w": 4.2, "merge": "yield", "zebra": True}
    traffic: float = 0.5                 # car density 0..1
    taper_in: float = 0.0                # lane drop/gain: inbound lane count changes by this many lanes at taper_at
    taper_at: float = 60.0
    e: float = 0.0                       # junction edge distance (computed)
    speed: float = 50.0                  # design speed (km/h): sets taper lengths
    offset: float = 0.0                  # lateral shift of the arm axis from the junction centre
    arcs: list = field(default_factory=list)       # curved arms: [(d_start, length, signed radius)]
    lanes_in: list = field(default_factory=list)   # explicit lane schedule (inner -> outer); empty = derived from lin/flare/bike/bus
    lanes_out: list = field(default_factory=list)
    solid_len: float = 30.0              # solid lane lines within this distance of the stop line
    dash: float = 3.0
    dash_gap: float = 9.0
    fillet: Optional[float] = None       # kerb radius where this arm meets the ring / its neighbours (None = scene.corner_r)

    @property
    def mw(self):
        if self.med_w is not None:
            return self.med_w
        return MED_W[self.median] if (self.lin and self.lout) else 0.0


@dataclass
class Ring:
    ro: float = 20.0
    ri: float = 11.0
    apron: float = 1.8
    lanes: int = 1
    center: str = "grass"                # grass | trees | fountain | monument | plain
    lane_w: float = 3.6                  # circulating lane width (lane lines inside the ring)
    aspect: float = 1.0                  # 1 = circle; >1 stretches the ring along x (elliptical roundabout)
    apron_h: float = 0.1                 # truck apron height
    island_h: float = 0.2                # central island kerb height above the road
    dashed: bool = True                  # dashed lane lines in a multi-lane ring


@dataclass
class Scene:
    name: str
    arms: List[Arm]
    ring: Optional[Ring] = None
    corner_r: float = 5.0
    context: bool = True
    cars: bool = True
    seed: int = 1
    grades: list = field(default_factory=list)      # grade-separated crossings: kwargs of grade.ribbon
    elements: list = field(default_factory=list)    # extra design elements (see elements.py)
    sky_extent: float = 140.0
    sim: Optional[str] = None                       # design vehicle simulated through the slip lanes and drawn (P SU BUS WB-40 WB-62)
    autofit: Optional[str] = None                   # enlarge slips until this vehicle fits (improve loop)


from lanes import (Lane, P, U, heading, to_arm, in_w, out_w, s_lo, s_hi, boundary, lane_spans, widths, ramp, taper_len)  # noqa: E402
import lanes as _lanes  # noqa: E402


def band(a, ds, f0, f1):
    """Polygon between lateral curves s=f0(d) and s=f1(d) over the distances ds."""
    L = [P(a, d, f0(d)) for d in ds]
    R = [P(a, d, f1(d)) for d in ds]
    return Polygon(L + R[::-1]).buffer(0)


def rect(a, d0, d1, s0, s1):
    if not a.arcs:
        return Polygon([P(a, d0, s0), P(a, d1, s0), P(a, d1, s1), P(a, d0, s1)])
    n = max(1, int(abs(d1 - d0) / 1.5))
    ds = [d0 + (d1 - d0) * i / n for i in range(n + 1)]
    return band(a, ds, lambda d: s0, lambda d: s1)


def in_n(a, d):
    return sum(w for w in _lanes.widths(a, d, True)) / max(a.lane_w, 1e-6)


def out_n(a, d):
    return sum(w for w in _lanes.widths(a, d, False)) / max(a.lane_w, 1e-6)


def extra_w(a):
    return 0.0


def pocket_edge(a, d):
    """Inner edge of the inbound carriageway: the left-turn pocket eats into the median near the junction."""
    return -a.mw / 2 + (a.pocket * a.lane_w * smooth((a.pocket_len - (d - a.e)) / 18.0) if a.pocket else 0.0)


def samples(a, step=2.0):
    ds = list(np.arange(a.start, a.L, step)) + [a.L]
    for k in (a.e, a.e + a.flare_len, a.e + a.flare_len - a.taper, a.e + a.pocket_len, a.taper_at, a.taper_at + 30):
        ds.append(k)
    return sorted(set(round(d, 3) for d in ds if a.start <= d <= a.L))


def strip_poly(a):
    return band(a, samples(a), lambda d: s_lo(a, d), lambda d: s_hi(a, d))


def compute_edges(scene):
    """e (distance from the centre to where the arm's own carriageway begins) for every arm."""
    for a in scene.arms:
        a.e = 0.0
        _lanes.clear_auto(a)
        _lanes.ensure(a)
    if scene.ring:
        for a in scene.arms:
            a.e = scene.ring.ro
            _lanes.clear_auto(a)
            _lanes.ensure(a)
        return
    base = []
    for a in scene.arms:
        b = replace(a, flare_in=0, flare_out=0, pocket=0, taper_in=0, lanes_in=[] if getattr(a, '_auto_lanes', False) else a.lanes_in, lanes_out=[] if getattr(a, '_auto_lanes', False) else a.lanes_out)
        _lanes.ensure(b)
        base.append(strip_poly(b))
    for i, a in enumerate(scene.arms):
        others = unary_union([base[j] for j in range(len(base)) if j != i])
        clip = rect(a, 0, a.L * 0.35, s_lo(a, 0) - 0.5, s_hi(a, 0) + 0.5)
        x = others.intersection(clip)
        e = 0.0
        ua = U(a)
        for p in polys(x):
            for c in p.exterior.coords:
                e = max(e, c[0] * ua[0] + c[1] * ua[1])
        a.e = max(e, 4.0)
    for a in scene.arms:
        _lanes.clear_auto(a)
        _lanes.ensure(a)


# ---------------------------------------------------------------- junction assembly
def neighbour_right(scene, i):
    """Arm met first when turning right out of arm i (rotating u by -90 deg)."""
    ai = scene.arms[i].angle
    best, bj = 361.0, None
    for j, b in enumerate(scene.arms):
        if j == i:
            continue
        dlt = (ai - b.angle) % 360.0
        if 0 < dlt < best:
            best, bj = dlt, j
    return bj, best


def build_core(scene, strips):
    parts = list(strips)
    if scene.ring:
        r = scene.ring
        from shapely.affinity import scale as _sc
        disc_o = _sc(Point(0, 0).buffer(r.ro, 64), r.aspect, 1.0)
        disc_i = _sc(Point(0, 0).buffer(r.ri + r.apron, 64), r.aspect, 1.0)
        ring = disc_o.difference(disc_i)
        parts.append(ring)
        union = unary_union(parts).difference(disc_i)
    else:
        mx = max(max(abs(s_lo(a, a.e)), abs(s_hi(a, a.e))) for a in scene.arms)
        parts.append(Point(0, 0).buffer(mx * 0.95, 32))
        union = unary_union(parts)
    cr = scene.corner_r
    out = union.buffer(cr, 24).buffer(-cr, 24).buffer(0)
    for a, st in zip(scene.arms, strips):
        if a.fillet and abs(a.fillet - cr) > 0.05:
            f = a.fillet
            extra = unary_union([st, ring]) if scene.ring else st
            out = unary_union([out, extra.buffer(f, 24).buffer(-f, 24).difference(disc_i if scene.ring else Polygon())])
    return out


def build_slips(scene, strips, main):
    asph, islands = main, []
    for i, a in enumerate(scene.arms):
        if not a.slip:
            continue
        j, gap = neighbour_right(scene, i)
        if j is None or gap > 172:
            continue
        sp = a.slip
        R, w = sp.get("R", 26.0), sp.get("w", 4.4)
        pair = unary_union([strips[i], strips[j]])
        big = pair.buffer(R, 32).buffer(-R, 32)
        wedge = big.difference(pair).difference(main)
        wedge = wedge.buffer(-0.05).buffer(0.05)
        isl = wedge.intersection(big.buffer(-w, 16)).difference(main.buffer(0.0))
        isl = isl.buffer(-1.2).buffer(1.2).buffer(0.9).buffer(-0.9)
        isl = MultiPolygon([p for p in polys(isl) if p.area > 6.0]) if not isl.is_empty else isl
        asph = unary_union([asph, wedge.difference(isl)])
        if not isl.is_empty:
            islands.append((isl, i, j))
    return asph, islands


def medians(scene, strips):
    """Raised/grass/tram median polygons per arm (with the crossing cut-through)."""
    out = []
    for a in scene.arms:
        if a.median in ("none", "paint") or not (a.lin and a.lout) or a.mw < 1.0:
            continue
        ds = [d for d in samples(a, 2.0) if d >= a.e + 0.8]
        if len(ds) < 3:
            continue
        m = band(a, ds, lambda d: pocket_edge(a, d), lambda d: a.mw / 2)
        r = min(a.mw / 2 * 0.96, 2.4)
        m = m.buffer(-r).buffer(r)
        if a.zebra is not None and a.refuge:
            zc = a.e + a.zebra
            m = m.difference(rect(a, zc - 1.7, zc + 1.7, -a.mw, a.mw))
            m = MultiPolygon([p for p in polys(m) if p.area > 2.0])
        elif a.zebra is not None:
            m = m.difference(rect(a, a.e, a.e + a.zebra + 1.7, -a.mw, a.mw))
        out.append((m, a))
    return out


# ---------------------------------------------------------------- paint
def arrow_polys(a, d, s, kind):
    """Lane arrow for an inbound lane (vehicle travels towards the junction = -u).  Returns polygons in plan."""
    ua = U(a, d)
    fwd = (-ua[0], -ua[1])
    right = (ua[1], -ua[0])                           # right of travel

    def Q(f, r):
        c = P(a, d, s)
        return (c[0] + fwd[0] * f + right[0] * r, c[1] + fwd[1] * f + right[1] * r)

    def path(pts, w=0.28):
        return LineString([Q(*p) for p in pts]).buffer(w / 2, cap_style=2, join_style=2)

    def head(f, r, tf, tr, wid=0.6, ln=1.0):
        n = math.hypot(tf, tr)
        tf, tr = tf / n, tr / n
        nf, nr = -tr, tf
        return Polygon([Q(f + nf * wid, r + nr * wid), Q(f + tf * ln, r + tr * ln), Q(f - nf * wid, r - nr * wid)])
    out = []
    if "T" in kind or kind in ("TL", "TR"):
        out += [path([(-1.7, 0), (0.6, 0)]), head(0.6, 0, 1, 0)]
    if "L" in kind or "R" in kind:
        sg = -1 if "L" in kind else 1
        if kind in ("L", "R"):
            out += [path([(-1.7, 0), (-0.2, 0), (0.6, sg * 0.9)]), head(0.6, sg * 0.9, 0.9, sg * 0.9)]
        else:
            out += [path([(-0.2, 0), (0.45, sg * 0.75)]), head(0.45, sg * 0.75, 0.9, sg * 0.9, 0.5, 0.8)]
    return out


def default_arrows(a):
    n = a.lin + a.flare_in
    base = {1: ["T"], 2: ["T", "TR"], 3: ["L", "T", "TR"], 4: ["L", "T", "T", "TR"]}.get(n, ["T"] * n)
    if a.pocket:
        base = ["L"] + base[1:] if n > 1 else ["L"]
    return base


def line_along(a, d0, d1, fn, w=0.15, style="solid", dash=3.0, gap=9.0, step=1.0):
    """Paint along a lateral curve s=fn(d) from d0 to d1; dashes follow distance along the arm."""
    out = []
    n = max(1, int((d1 - d0) / step))
    cyc = dash + gap
    for i in range(n):
        da, db = d0 + (d1 - d0) * i / n, d0 + (d1 - d0) * (i + 1) / n
        if style == "dashed":
            ph = (da - d0) % cyc
            if ph > dash:
                continue
        sa, sb = fn(da), fn(db)
        if sa is None or sb is None:
            continue
        out.append(Polygon([P(a, da, sa - w / 2), P(a, db, sb - w / 2), P(a, db, sb + w / 2), P(a, da, sa + w / 2)]))
    return out


def arm_paint(scene, a, asphalt):
    """-> (white polygons, colour surface polygons [(poly, col)])"""
    w, surf = [], []
    ze = a.zebra is not None
    zc = a.e + (a.zebra or 0)
    dst = (zc + 1.7 + 1.1) if ze else a.e + 2.2
    ds_all = samples(a)
    far = a.L - 1
    d0 = dst + 0.8
    pk = a.lane_w if a.pocket else 0.0
    # stop line / yield teeth
    if a.lin and a.stop != "none":
        s0, s1 = s_lo(a, dst) + 0.1, (-a.mw / 2 + pk)
        if a.stop == "line":
            w.append(rect(a, dst - 0.22, dst + 0.22, s0, s1))
        else:
            x = s0 + 0.2
            while x < s1 - 0.6:
                w.append(Polygon([P(a, dst - 0.1, x), P(a, dst - 0.1, x + 0.7), P(a, dst + 0.9, x + 0.35)]))
                x += 1.0
    # crossing
    if ze:
        lo, hi = s_lo(a, zc), s_hi(a, zc)
        x = lo + 0.35
        while x + 0.55 < hi - 0.2:
            w.append(rect(a, zc - 1.75, zc + 1.75, x, x + 0.55))
            x += 1.1
    # lane lines from the lane schedule: every boundary follows the (possibly tapering) lane widths
    for inbound in (True, False):
        L = a.lanes_in if inbound else a.lanes_out
        if not L:
            continue
        sg = -1.0 if inbound else 1.0
        for k in range(1, len(L)):
            lk0, lk1 = L[k - 1], L[k]
            kinds = (lk0.kind, lk1.kind)
            fn = lambda d, k=k, inbound=inbound: (boundary(a, k, d, inbound) if min(widths(a, d, inbound)[k - 1], widths(a, d, inbound)[k]) > 0.35 else None)
            mk = lk1.marking_in if lk1.marking_in != "auto" else "auto"
            if mk == "none":
                continue
            if "bike" in kinds:
                w += line_along(a, d0, far, fn, 0.12, "dashed", 1.2, 0.8)
            elif "bus" in kinds or mk == "solid":
                w += line_along(a, d0, far, fn, 0.15, "solid")
            elif inbound:
                solid_to = a.e + max(a.solid_len, a.flare_len if a.flare_in else 0)
                w += line_along(a, d0, solid_to, fn, 0.15, "solid")
                w += line_along(a, solid_to, far, fn, 0.15, "dashed", a.dash, a.dash_gap)
            else:
                w += line_along(a, d0 + 6.0, far, fn, 0.15, "dashed", a.dash, a.dash_gap)
        # carriageway edge line
        edge = (lambda d, inbound=inbound: (s_lo(a, d) + 0.22) if (inbound and widths(a, d, True) and widths(a, d, True)[-1] > 0.35 and a.lanes_in[-1].kind != "bike") else (s_hi(a, d) - 0.22) if (not inbound and widths(a, d, False) and widths(a, d, False)[-1] > 0.35 and a.lanes_out[-1].kind != "bike") else None)
        w += line_along(a, d0, far, edge, 0.15, "solid")
        # coloured lanes
        for k, lk in enumerate(L):
            if lk.kind in ("bike", "bus") or lk.colour:
                col = tuple(lk.colour) if lk.colour else (BIKE if lk.kind == "bike" else BUSL)
                dsx = [d for d in ds_all if d >= d0 - 1]
                surf.append((band(a, dsx, lambda d, k=k, inbound=inbound: boundary(a, k, d, inbound), lambda d, k=k, inbound=inbound: boundary(a, k + 1, d, inbound)), col))
    if a.pocket:
        s = -a.mw / 2
        w.append(rect(a, d0, a.e + a.pocket_len * 0.55, s - 0.075, s + 0.075))
        dd = a.e + a.pocket_len * 0.55
        while dd + 2.0 < a.e + a.pocket_len:
            w.append(rect(a, dd, dd + 2.0, s - 0.075, s + 0.075))
            dd += 5.0
    # centre of two-way roads with no physical median
    if a.lin and a.lout and a.median == "none":
        w.append(rect(a, d0, a.e + a.solid_len + 4.0, -0.28, -0.13))
        w.append(rect(a, d0, a.e + a.solid_len + 4.0, 0.13, 0.28))
        dd = a.e + a.solid_len + 4.0
        while dd + a.dash < far:
            w.append(rect(a, dd, dd + a.dash, -0.075, 0.075))
            dd += a.dash + a.dash_gap + 3.0
    if a.median == "paint" and a.lin and a.lout:
        for sx in (-a.mw / 2, a.mw / 2):
            w.append(rect(a, d0, far, sx - 0.075, sx + 0.075))
        dd = d0 + 1.0
        while dd + 1.0 < min(far, a.e + 60):
            w.append(Polygon([P(a, dd, -a.mw / 2), P(a, dd + 0.35, -a.mw / 2), P(a, dd + 0.35 + a.mw * 0.9, a.mw / 2), P(a, dd + a.mw * 0.9, a.mw / 2)]))
            dd += 2.4
    # arrows on the drive lanes that are wide enough at the arrow position
    if a.lin and a.arrows != []:
        dar = dst + 7.0
        spans = [(l, s0_, s1_, wd) for (l, s0_, s1_, wd) in lane_spans(a, dar, True) if l.kind in ("drive", "bus", "turn") and wd > 2.6]
        centres = [(s0_ + s1_) / 2 for (_, s0_, s1_, _) in spans]
        if a.pocket:
            centres.insert(0, -a.mw / 2 + a.lane_w / 2)
        kinds = list(a.arrows or [])
        if not kinds:
            n = len(centres)
            kinds = {1: ["T"], 2: ["T", "TR"], 3: ["L", "T", "TR"], 4: ["L", "T", "T", "TR"]}.get(n, ["T"] * n)
            if a.pocket and n > 1:
                kinds = ["L"] + kinds[1:]
        lanes_here = [None] * (1 if a.pocket else 0) + [sp[0] for sp in spans]
        kinds = list(kinds) + ["T"] * max(0, len(centres) - len(kinds))
        kinds = [(l_.arrow if (l_ is not None and l_.arrow) else kd) for l_, kd in zip(lanes_here, kinds)]
        if len(kinds) < len(centres):
            kinds = kinds + ["T"] * (len(centres) - len(kinds))
        for dd in (dst + 7.0, dst + 24.0):
            for s, kd in zip(centres, kinds):
                w += arrow_polys(a, dd, s, kd)
    return w, surf


# ---------------------------------------------------------------- furniture
def signal_head(m, x, y0, z, yaw, state):
    fx, fz = math.cos(yaw), math.sin(yaw)
    m.box(x, y0, z, 0.32, 0.95, 0.3, HEAD, yaw)
    cols = [(235, 45, 40) if state == "r" else (88, 50, 50), (230, 170, 40) if state == "y" else (100, 90, 40),
            (60, 205, 100) if state == "g" else (46, 82, 56)]
    for k, c in enumerate(cols):
        m.box(x + fx * 0.17, y0 + 0.68 - k * 0.3, z + fz * 0.17, 0.06, 0.2, 0.2, c, yaw)


def lamp(m, x, z, tx, tz, h=8.0):
    m.cyl(x, 0, h, z, 0.09, POLE, 6)
    ln = math.hypot(tx - x, tz - z) or 1
    yaw = math.atan2(tz - z, tx - x)
    m.box((x + tx) / 2, h - 0.1, (z + tz) / 2, ln, 0.1, 0.1, POLE, yaw)
    m.box(tx, h - 0.25, tz, 0.7, 0.14, 0.3, (246, 238, 196), yaw)


def tree(m, x, z, rnd, y=0.0, big=1.0):
    h = rnd.uniform(5.0, 7.0) * big
    m.cyl(x, y, y + h * 0.45, z, 0.16 * big, (92, 72, 56), 6)
    g = rnd.choice([(70, 124, 66), (82, 134, 70), (62, 112, 62), (96, 142, 72)])
    m.blob(x, y + h * 0.35, z, rnd.uniform(1.9, 2.5) * big, h * 0.7, g)


def sign_post(m, x, z, kind, yaw):
    m.cyl(x, 0.15, 2.6, z, 0.04, POLE, 5)
    if kind == "priority":
        m.box(x, 2.1, z, 0.62, 0.62, 0.05, (250, 250, 250), yaw + math.pi / 4)
        m.box(x, 2.12, z, 0.5, 0.5, 0.06, (242, 196, 40), yaw + math.pi / 4)
    elif kind == "stop":
        m.box(x, 2.1, z, 0.62, 0.62, 0.05, (200, 30, 36), yaw + math.pi / 8)
        m.box(x, 2.12, z, 0.44, 0.44, 0.06, (200, 30, 36), yaw + math.pi / 8)
    elif kind == "yield":
        m.box(x, 2.1, z, 0.7, 0.62, 0.05, (210, 36, 40), yaw)
        m.box(x, 2.12, z, 0.46, 0.4, 0.06, (250, 250, 250), yaw)
    elif kind == "zebra":
        m.box(x, 2.1, z, 0.6, 0.6, 0.05, (30, 90, 190), yaw)
        m.box(x, 2.12, z, 0.34, 0.34, 0.06, (240, 244, 250), yaw)


def build(scene: Scene) -> Mesh:
    rnd = random.Random(scene.seed)
    m = Mesh()
    compute_edges(scene)
    if scene.autofit:
        import simulate as _sim
        scene.fit_log = _sim.autofit(scene, scene.autofit)
    arms = scene.arms
    strips = [strip_poly(a) for a in arms]
    main = build_core(scene, strips)
    # parking strips
    for a in arms:
        if a.parking:
            for sgn in (-1, 1):
                if (sgn < 0 and not a.lin) or (sgn > 0 and not a.lout):
                    continue
                d0, d1 = a.e + 24.0, a.L
                s_edge = (lambda d: s_lo(a, d) - 2.4) if sgn < 0 else (lambda d: s_hi(a, d))
                s_edge2 = (lambda d: s_lo(a, d)) if sgn < 0 else (lambda d: s_hi(a, d) + 2.4)
                pk = band(a, [d0, d1], s_edge, s_edge2).buffer(-0.5).buffer(0.5)
                main = unary_union([main, pk])
    import slips as _slips
    asph_slip, islands, slip_paint, slip_info = _slips.build_slips(scene, strips, main)
    scene.slip_info = slip_info
    meds = medians(scene, strips)
    med_union = unary_union([g for g, _ in meds]) if meds else Polygon()
    isl_union = unary_union([g for g, _, _ in islands]) if islands else Polygon()
    asphalt = asph_slip.difference(med_union).difference(isl_union).buffer(0)
    walkarms = [strip_poly(a).buffer(a.walk, 16) for a in arms]
    pave_out = unary_union(walkarms + [asph_slip.buffer(min(a.walk for a in arms), 16)])
    pavement = pave_out.difference(asphalt).difference(med_union).difference(isl_union).buffer(0)
    clipbox = box(-scene.sky_extent - 70, -scene.sky_extent - 70, scene.sky_extent + 70, scene.sky_extent + 70)
    asphalt, pavement = asphalt.intersection(clipbox), pavement.intersection(clipbox)

    # ground + surfaces
    big = scene.sky_extent + 120
    import grade
    casters = []                                           # (footprint polygon, height) for the sun shadows
    grades = [grade.ribbon(**g) for g in scene.grades]
    scene.extra = grades
    hole = unary_union([g.hole for g in grades if g.hole is not None]) if any(g.hole is not None for g in grades) else Polygon()
    occ = unary_union([g.footprint for g in grades]) if grades else Polygon()
    m.poly(box(-big, -big, big, big).difference(hole), -0.04, GROUND)
    m.poly(asphalt, 0.0, ASPH)
    paint_w, surfs = [], []
    for a in arms:
        w, s = arm_paint(scene, a, asphalt)
        paint_w += w
        surfs += s
    for g, c in surfs:
        m.poly(g.intersection(asphalt), Y_SURF, c)
    # pavement slab, kerb lip
    m.prism(pavement, -0.02, KH, PAVE, KERB_FACE)
    lip = pavement.intersection(asphalt.buffer(0.3))
    m.poly(lip, KH + 0.004, KERB_TOP)
    # medians / islands: kerbed slab with planted top
    def planted(g, kind):
        if g.is_empty:
            return
        m.prism(g, -0.02, KH, CONC, KERB_FACE)
        inner = g.buffer(-0.45)
        col = {"tram": BALLAST, "raised": GRASS, "grass": GRASS}.get(kind, GRASS)
        m.poly(inner, KH + 0.008, col)
    for g, a in meds:
        planted(g, a.median)
        if a.median == "tram":
            for sgn in (-1, 1):
                m.poly(band(a, [a.e + 2, a.L], lambda d, s=sgn: s * 0.72 - 0.05, lambda d, s=sgn: s * 0.72 + 0.05).intersection(g), KH + 0.02, (150, 150, 156))
    for g, i, j in islands:
        planted(g, "island")
        sp_ = _slips.as_slip(arms[i].slip)
        if sp_.island_trees and g.area > 40:
            rp = g.representative_point()
            tree(m, rp.x, rp.y, rnd, KH + 0.01, 0.9)
            casters.append((Point(rp.x, rp.y).buffer(2.0), 5.5))
    # ring centre
    ctx_pts = []
    if scene.ring:
        r = scene.ring
        from shapely.affinity import scale as _sc2
        _e = lambda g: _sc2(g, r.aspect, 1.0)
        m.prism(_e(Point(0, 0).buffer(r.ri + r.apron, 48).difference(Point(0, 0).buffer(r.ri, 48))), -0.02, r.apron_h, APRON, KERB_FACE)
        m.prism(_e(Point(0, 0).buffer(r.ri, 48)), -0.02, r.island_h, CONC, KERB_FACE)
        m.poly(_e(Point(0, 0).buffer(r.ri - 0.5, 48)), r.island_h + 0.01, GRASS)
        for k in range(int(r.ri * 1.0)):
            ang = k * 2 * math.pi / max(1, int(r.ri * 1.0))
            rr = r.ri - 2.2
            if r.center in ("trees", "grass") and rnd.random() < 0.8 and r.ri > 8:
                tree(m, rr * math.cos(ang), rr * math.sin(ang), rnd, KH + 0.05)
        if r.center == "fountain":
            m.cyl(0, KH + 0.05, KH + 0.6, 0, 3.6, (150, 160, 170), 20)
            m.cyl(0, KH + 0.6, KH + 0.65, 0, 3.0, (80, 140, 190), 20)
            m.cyl(0, KH + 0.6, KH + 2.4, 0, 0.3, (190, 196, 200), 8)
        if r.center == "monument":
            m.box(0, KH + 0.05, 0, 3.6, 1.0, 3.6, (186, 182, 174))
            m.cyl(0, KH + 1.0, KH + 11.0, 0, 0.8, (200, 196, 188), 8)
        if r.center in ("trees", "grass"):
            tree(m, 0, 0, rnd, KH + 0.05, 1.2)
    # paint
    paint_w = list(paint_w) + list(slip_paint)
    allw = unary_union([p.buffer(0) for p in paint_w if not p.is_empty]) if paint_w else Polygon()
    allw = allw.intersection(asphalt.buffer(-0.02))
    m.poly(allw, Y_PAINT, WHITE)
    if scene.ring:
        r = scene.ring
        rr = r.ro - 0.6
        ring_p = Point(0, 0).buffer(rr + 0.075, 64).difference(Point(0, 0).buffer(rr - 0.075, 64))
        for k in range(1, r.lanes):
            rk = r.ro - k * r.lane_w - 0.2
            n = int(2 * math.pi * rk / 9)
            for q in range(n):
                a0, a1 = q * 2 * math.pi / n, (q + 0.45) * 2 * math.pi / n
                seg = LineString([(r.aspect * rk * math.cos(a0 + t * (a1 - a0)), rk * math.sin(a0 + t * (a1 - a0))) for t in np.linspace(0, 1, 5)]).buffer(0.075, cap_style=2)
                if r.dashed:
                    m.poly(seg.intersection(asphalt), Y_PAINT, WHITE)
    # furniture
    free = unary_union([asphalt, pavement, med_union, isl_union])

    def on_ground(x, z, pad=0.0):
        return not free.buffer(pad).intersects(Point(x, z)) and not occ.intersects(Point(x, z))
    for ai, a in enumerate(arms):
        ua = U(a)
        yaw_in = math.atan2(ua[1], ua[0])
        for sgn in (-1, 1):
            if (sgn < 0 and not a.lin) or (sgn > 0 and not a.lout):
                continue
            dd = a.e + 16 + (0 if sgn < 0 else 14)
            while dd < min(a.L, scene.sky_extent + 20):
                sd = (s_lo(a, dd) - 2.4 * a.parking - a.walk + 0.7) if sgn < 0 else (s_hi(a, dd) + 2.4 * a.parking + a.walk - 0.7)
                if a.lamps:
                    x, z = P(a, dd, sd)
                    tx, tz = P(a, dd, sd + sgn * -2.0)
                    if free.buffer(0.3).intersects(Point(x, z)) and not occ.intersects(Point(x, z)):
                        lamp(m, x, z, tx, tz, 8.0)
                        casters.append((LineString([(x, z), (tx, tz)]).buffer(0.1), 8.0))
                dd += 32.0
            if a.trees:
                dd = a.e + 12 + (0 if sgn < 0 else 7)
                while dd < min(a.L, scene.sky_extent + 20):
                    sd = (s_lo(a, dd) - 2.4 * a.parking - a.walk - 1.3) if sgn < 0 else (s_hi(a, dd) + 2.4 * a.parking + a.walk + 1.3)
                    x, z = P(a, dd, sd)
                    if on_ground(x, z, 1.0):
                        tree(m, x, z, rnd)
                        casters.append((Point(x, z).buffer(2.2), 6.0))
                    dd += 13.0
        if a.median in ("grass", "tram", "raised") and a.mw >= 3.5:
            dd = a.e + 14
            while dd < min(a.L, scene.sky_extent + 20):
                x, z = P(a, dd, 0.0 if a.median != "tram" else 0.0)
                if a.median != "tram" and med_union.buffer(-1).intersects(Point(x, z)):
                    tree(m, x, z, rnd, KH, 0.9)
                    casters.append((Point(x, z).buffer(2.0), 5.5))
                dd += 12.0
        ze = a.zebra is not None
        zc = a.e + (a.zebra or 0)
        dst = (zc + 1.7 + 1.1) if ze else a.e + 2.2
        if a.signal and a.lin:
            red = (ai % 2 == 0)
            for inbound_side in (-1,):
                sx = s_lo(a, dst) - 0.8
                x, z = P(a, dst + 1.6, sx)
                m.cyl(x, 0, 4.4, z, 0.1, POLE, 8)
                casters.append((Point(x, z).buffer(0.2), 4.4))
                sol = -a.mw / 2 + (a.lane_w if a.pocket else 0)
                tx, tz = P(a, dst + 1.6, sol - 0.3)
                if a.mw > 1.0 or a.lin > 1:
                    m.cyl(x, 4.4, 6.9, z, 0.12, POLE, 8)
                    m.box((x + tx) / 2, 6.8, (z + tz) / 2, math.hypot(tx - x, tz - z), 0.14, 0.14, POLE, math.atan2(tz - z, tx - x))
                    casters.append((LineString([(x, z), (tx, tz)]).buffer(0.2), 6.9))
                    for q in range(a.lin):
                        hx, hz = P(a, dst + 1.6, -a.mw / 2 - (q + 0.5) * a.lane_w)
                        signal_head(m, hx, 5.6, hz, yaw_in, "r" if red else "g")
                signal_head(m, x, 2.9, z, yaw_in, "r" if red else "g")
                # pedestrian signal on the far side of the crossing
                px, pz = P(a, zc, s_lo(a, zc) - 0.7)
                m.cyl(px, 0, 2.5, pz, 0.05, POLE, 6)
                m.box(px, 2.0, pz, 0.28, 0.45, 0.2, HEAD, yaw_in)
        elif a.sign and a.lin:
            x, z = P(a, dst + 2.0, s_lo(a, dst) - 0.8)
            sign_post(m, x, z, a.sign, yaw_in + math.pi / 2)
            casters.append((Point(x, z).buffer(0.2), 2.6))
        if ze:
            for sd in (s_lo(a, zc) - 0.8, s_hi(a, zc) + 0.8):
                x, z = P(a, zc - 2.2, sd)
                if free.buffer(0.2).intersects(Point(x, z)) and not asphalt.intersects(Point(x, z)):
                    sign_post(m, x, z, "zebra", yaw_in + math.pi / 2)
    # cars
    if scene.cars:
        for a in arms:
            if not (a.traffic > 0):
                continue
            ze = a.zebra is not None
            zc = a.e + (a.zebra or 0)
            dst = (zc + 1.7 + 1.1) if ze else a.e + 2.2
            for sgn in (-1, 1):
                if not (a.lin if sgn < 0 else a.lout):
                    continue
                nl = len(a.lanes_in if sgn < 0 else a.lanes_out)
                for k in range(nl):
                    dd = dst + 4.0 + rnd.uniform(0, 8) if sgn < 0 else a.e + 14 + rnd.uniform(0, 10)
                    while dd < min(a.L, scene.sky_extent) - 4:
                        sp = lane_spans(a, dd, sgn < 0)
                        if k < len(sp) and sp[k][3] > 2.8 and sp[k][0].kind in ("drive", "bus", "turn") and rnd.random() < a.traffic:
                            s = (sp[k][1] + sp[k][2]) / 2
                            x, z = P(a, dd, s)
                            hd = heading(a, dd)
                            yaw = hd + math.pi if sgn < 0 else hd
                            if asphalt.buffer(-0.5).contains(Point(x, z)):
                                m.car(x, z, yaw, rnd.choice(CAR_COLS))
                                casters.append((Point(x, z).buffer(1.0), 1.5))
                        dd += rnd.uniform(9, 22)
    if scene.ring:
        r = scene.ring
        for k in range(rnd.randint(1, 3)):
            ang = rnd.uniform(0, 2 * math.pi)
            rr = r.ro - 1.8
            m.car(rr * math.cos(ang), rr * math.sin(ang), ang - math.pi / 2, rnd.choice(CAR_COLS))
    # context buildings
    if scene.context:
        e = scene.sky_extent
        lots = box(-e - 20, -e - 20, e + 20, e + 20).difference(unary_union([asphalt, pavement, occ.buffer(6.0)]).buffer(7.0))
        cell = 26.0
        gx = int(-e // cell)
        while gx * cell < e:
            gy = int(-e // cell)
            while gy * cell < e:
                c = box(gx * cell + 2, gy * cell + 2, (gx + 1) * cell - 2, (gy + 1) * cell - 2)
                if lots.contains(c):
                    t = rnd.random()
                    if t < 0.68:
                        fp = box(c.bounds[0] + rnd.uniform(0, 3), c.bounds[1] + rnd.uniform(0, 3), c.bounds[2] - rnd.uniform(0, 3), c.bounds[3] - rnd.uniform(0, 3))
                        h = rnd.choice([9.6, 12.8, 16.0, 19.2, 22.4, 28.8])
                        col = rnd.choice([(224, 216, 200), (206, 200, 190), (198, 172, 152), (232, 228, 216), (188, 196, 202), (214, 190, 160)])
                        x0, y0, x1, y1 = fp.bounds
                        nfl = int(h / 3.2)
                        for f in range(nfl):
                            cc = col if f else tuple(int(v * 0.86) for v in col)
                            win = tuple(int(v * 0.72) for v in col)
                            m.box((x0 + x1) / 2, f * 3.2, (y0 + y1) / 2, x1 - x0, 3.2 - 0.0, y1 - y0, cc if f % 1 == 0 else win)
                        m.box((x0 + x1) / 2, nfl * 3.2, (y0 + y1) / 2, x1 - x0 - 0.4, 0.5, y1 - y0 - 0.4, (150, 146, 140))
                        wc = (74, 92, 108)
                        for f in range(1, nfl):
                            for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
                                ln = math.hypot(bx - ax, by - ay)
                                nw = int(ln // 3.4)
                                ox, oy = (by - ay) / ln, -(bx - ax) / ln
                                ox, oy = (-ox, -oy) if False else (ox, oy)
                                for q in range(nw):
                                    t0 = (q + 0.18) / nw
                                    t1 = (q + 0.82) / nw
                                    pa = (ax + (bx - ax) * t0 - ox * 0.0, ay + (by - ay) * t0)
                                    pb = (ax + (bx - ax) * t1, ay + (by - ay) * t1)
                                    # outward normal: away from the building centre
                                    cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2
                                    mx_, my_ = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
                                    sg = 1 if (mx_ - cx_) * ox + (my_ - cy_) * oy > 0 else -1
                                    e_ = 0.04 * sg
                                    y_a, y_b = f * 3.2 - 2.2, f * 3.2 - 0.8
                                    m.quad((pa[0] + ox * e_, y_a, pa[1] + oy * e_), (pb[0] + ox * e_, y_a, pb[1] + oy * e_), (pb[0] + ox * e_, y_b, pb[1] + oy * e_), (pa[0] + ox * e_, y_b, pa[1] + oy * e_), wc)
                        casters.append((fp, nfl * 3.2))
                    else:
                        m.poly(c.buffer(-0.5), -0.03, GRASS_D)
                        for _ in range(3):
                            x = rnd.uniform(c.bounds[0] + 3, c.bounds[2] - 3)
                            z = rnd.uniform(c.bounds[1] + 3, c.bounds[3] - 3)
                            tree(m, x, z, rnd, 0.0)
                            casters.append((Point(x, z).buffer(2.2), 6.0))
                gy += 1
            gx += 1
    import elements
    elements.apply(scene, locals())
    if scene.sim:
        import simulate as _sim
        rep, poses_all = _sim.run(scene, asphalt, islands, scene.sim)
        scene.sim_report = rep
        for veh, poses in poses_all:
            for q in (0.3, 0.5, 0.7):
                if not poses:
                    continue
                x_, z_, yaw_, parts_ = poses[int(q * (len(poses) - 1))]
                for k, pol in enumerate(parts_):
                    m.prism(pol, 0.3, 3.3 if veh in ("BUS", "SU") else 3.0, (236, 200, 60) if k == 0 else (232, 232, 228), (200, 168, 50) if k == 0 else (200, 200, 196))
                    casters.append((pol, 3.2))
    # sun shadows: project every caster along the sun's horizontal direction, darken what lies under it
    sh = []
    for fp, h in casters:
        v = (0.56 * h, 0.50 * h)
        sh.append(unary_union([fp, translate(fp, *v)]).convex_hull)
    if sh:
        S = unary_union(sh)
        dk = lambda c: tuple(int(x * 0.66) for x in c)
        m.poly(S.intersection(asphalt), Y_SURF + 0.003, dk(ASPH))
        m.poly(S.intersection(allw), Y_PAINT + 0.003, dk(WHITE))
        m.poly(S.intersection(pavement), KH + 0.006, dk(PAVE))
        m.poly(S.intersection(box(-big, -big, big, big)).difference(unary_union([asphalt, pavement, med_union, isl_union])).intersection(clipbox), -0.025, dk(GROUND))
    for g in scene.extra:
        g.fn(scene, m, locals())
    return m
