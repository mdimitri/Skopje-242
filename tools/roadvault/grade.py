"""Grade-separated roads: a ribbon along a straight line through the scene centre with a height profile.
kind 'over'  : ramps up on grass embankments with wing walls, deck on piers across the span, parapets
kind 'under' : trench with vertical retaining walls and coping, the ground road passes over it on a slab."""
import math

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.affinity import rotate, translate
from shapely.ops import unary_union as unary_union_

from engine import (ASPH, BALLAST, CONC, GRASS, KERB_FACE, KERB_TOP, KH, PAVE, POLE, WHITE, Y_PAINT, CAR_COLS, smooth, tree, lamp)


def smoothstep(t):
    return smooth(t)


def ribbon(angle=0.0, kind="over", lanes=2, lane_w=3.25, median=1.2, h=6.4, span=24.0, ramp=70.0, half=190.0,
           walk=2.4, deck=1.3, cars=True, oneway=False, bike=False, rail="parapet", name=None, offset=0.0, extra_lanes=0):
    """Returns a Scene.extra callback.  `lanes` per direction; `offset` shifts the ribbon along its own normal."""
    sgn = 1.0 if kind == "over" else -1.0
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    nsd = 1 if oneway else 2
    W = lanes * lane_w * (1 if oneway else 1) + (0 if oneway else median / 2)     # half-width of asphalt

    def prof(s):
        a = abs(s)
        if a <= span:
            return sgn * h
        return sgn * h * smoothstep(1 - (a - span) / ramp)

    def pt(s, t):                                   # ribbon coords -> plan
        return (ca * s - sa * (t + offset), sa * s + ca * (t + offset))

    Wl = W if not oneway else W / 1.0
    tl, tr = (-W, W) if not oneway else (-W, W)

    Wp0 = W + walk
    line = LineString([pt(-half, 0), pt(half, 0)])
    foot = line.buffer(Wp0 + 1.2 + (1.55 * h if kind == "over" else 0.6), cap_style=2)
    holeg = None
    if kind == "under":
        holeg = LineString([pt(-half, 0), pt(half, 0)]).buffer(Wp0 + 0.2, cap_style=2)

    def fn(scene, m, loc):
        rnd = loc["rnd"]
        ss = sorted(set(list(np.arange(-half, half + 0.1, 2.5)) + [-span, span, -span - 4, span + 4]))
        H = [prof(s) for s in ss]
        casters = loc["casters"]

        def surf(t0, t1, dy, col, s_lo=-1e9, s_hi=1e9):
            for i in range(len(ss) - 1):
                if ss[i] < s_lo - 1e-6 or ss[i + 1] > s_hi + 1e-6:
                    continue
                a, b = ss[i], ss[i + 1]
                m.quad((*pt(a, t0)[:1], H[i] + dy, pt(a, t0)[1]), (pt(b, t0)[0], H[i + 1] + dy, pt(b, t0)[1]),
                       (pt(b, t1)[0], H[i + 1] + dy, pt(b, t1)[1]), (pt(a, t1)[0], H[i] + dy, pt(a, t1)[1]), col)

        def wall(t, y0off, y1off, col, s_lo=-1e9, s_hi=1e9, down=False):
            for i in range(len(ss) - 1):
                if ss[i] < s_lo - 1e-6 or ss[i + 1] > s_hi + 1e-6:
                    continue
                a, b = ss[i], ss[i + 1]
                A, B = pt(a, t), pt(b, t)
                m.quad((A[0], H[i] + y0off, A[1]), (B[0], H[i + 1] + y0off, B[1]), (B[0], H[i + 1] + y1off, B[1]), (A[0], H[i] + y1off, A[1]), col)
        Wp = W + walk
        # carriageway + median + pavements
        surf(-W, W, 0.0, ASPH)
        if not oneway and median > 0.3:
            surf(-median / 2, median / 2, 0.02, (120, 120, 118))
            surf(-median / 2 + 0.2, median / 2 - 0.2, 0.04, (140, 138, 132))
        surf(-Wp, -W, KH, PAVE)
        surf(W, Wp, KH, PAVE)
        wall(-W, 0.0, KH, KERB_FACE)
        wall(W, 0.0, KH, KERB_FACE)
        # paint
        lane_lines = []
        for k in range(1, lanes):
            lane_lines += [(-W + k * lane_w * 1.0, "dash"), (W - k * lane_w, "dash")] if oneway else [(median / 2 + k * lane_w, "dash"), (-median / 2 - k * lane_w, "dash")]
        for tcen in [t for t, _ in lane_lines]:
            s = -half
            while s < half:
                if True:
                    i0 = int((s + half) / 2.5)
                    for q in (0.0,):
                        A, B = pt(s, tcen - 0.075), pt(s + 3.0, tcen - 0.075)
                        C, D = pt(s + 3.0, tcen + 0.075), pt(s, tcen + 0.075)
                        hA, hB = prof(s), prof(s + 3.0)
                        m.quad((A[0], hA + Y_PAINT, A[1]), (B[0], hB + Y_PAINT, B[1]), (C[0], hB + Y_PAINT, C[1]), (D[0], hA + Y_PAINT, D[1]), WHITE)
                s += 9.0
        for t in (-W + 0.25, W - 0.25):
            for i in range(len(ss) - 1):
                A, B = pt(ss[i], t - 0.075), pt(ss[i + 1], t - 0.075)
                C, D = pt(ss[i + 1], t + 0.075), pt(ss[i], t + 0.075)
                m.quad((A[0], H[i] + Y_PAINT, A[1]), (B[0], H[i + 1] + Y_PAINT, B[1]), (C[0], H[i + 1] + Y_PAINT, C[1]), (D[0], H[i] + Y_PAINT, D[1]), WHITE)
        if not oneway:
            for tc in ((-0.0,) if median <= 0.3 else (-median / 2 + 0.1, median / 2 - 0.1)):
                for i in range(len(ss) - 1):
                    A, B = pt(ss[i], tc - 0.075), pt(ss[i + 1], tc - 0.075)
                    C, D = pt(ss[i + 1], tc + 0.075), pt(ss[i], tc + 0.075)
                    m.quad((A[0], H[i] + Y_PAINT, A[1]), (B[0], H[i + 1] + Y_PAINT, B[1]), (C[0], H[i + 1] + Y_PAINT, C[1]), (D[0], H[i] + Y_PAINT, D[1]), WHITE)
        # cars
        if cars:
            for dirn, tcen_base in ((1, -1), (-1, 1)):
                for k in range(lanes):
                    t = (tcen_base * (median / 2 + (k + 0.5) * lane_w)) if not oneway else (-W + (k + 0.5) * lane_w)
                    if oneway and dirn == -1:
                        continue
                    s = -half + rnd.uniform(5, 20)
                    while s < half - 10:
                        x, z = pt(s, t)
                        m.car(x, z, math.atan2(sa, ca) + (0 if dirn == 1 else math.pi), rnd.choice(CAR_COLS), y=prof(s))
                        s += rnd.uniform(12, 30)
        # structure
        if kind == "over":
            for sd in (-1, 1):
                t = sd * Wp
                # parapet / barrier
                wall(t, KH, KH + 1.0, (196, 194, 188))
                wall(t, KH + 1.0, KH + 1.08, (120, 120, 124))
                # fascia + underside on the span
                for i in range(len(ss) - 1):
                    if abs(ss[i]) <= span + 2:
                        pass
                wall(t, -deck, KH, (176, 172, 166), s_lo=-span - 4, s_hi=span + 4)
                # ramp zones: embankment slope down to the ground + wing wall
                for i in range(len(ss) - 1):
                    a, b = ss[i], ss[i + 1]
                    if abs(a) < span + 3.9 and abs(b) < span + 3.9:
                        continue
                    ha, hb = H[i], H[i + 1]
                    oa, ob = ha * 1.5, hb * 1.5
                    A, B = pt(a, t), pt(b, t)
                    A2, B2 = pt(a, t + sd * oa), pt(b, t + sd * ob)
                    m.quad((A[0], ha, A[1]), (B[0], hb, B[1]), (B2[0], 0.0, B2[1]), (A2[0], 0.0, A2[1]), (104, 142, 80))
            # piers under the span
            for sx in (-span + 0.5, span - 0.5):
                for tt in (-W * 0.55, W * 0.55):
                    x, z = pt(sx, tt)
                    m.box(x, 0.0, z, 1.2, h - deck, 1.6, (186, 184, 178), math.atan2(sa, ca))
            # cap beam
            for sx in (-span + 0.5, span - 0.5):
                x, z = pt(sx, 0.0)
                m.box(x, h - deck - 0.5, z, 1.6, 0.5, 2 * Wp, (176, 172, 166), math.atan2(sa, ca))
            casters.append((Polygon([pt(-span, -Wp), pt(span, -Wp), pt(span, Wp), pt(-span, Wp)]), h))
        else:
            # trench: vertical retaining walls with coping
            for sd in (-1, 1):
                t = sd * (Wp + 0.2)
                wall(t, 0.0, KH, (172, 170, 164))
                for i in range(len(ss) - 1):
                    A, B = pt(ss[i], t), pt(ss[i + 1], t)
                    m.quad((A[0], H[i], A[1]), (B[0], H[i + 1], B[1]), (B[0], 0.0, B[1]), (A[0], 0.0, A[1]), (170, 168, 160))
                    A2, B2 = pt(ss[i], t + sd * 0.5), pt(ss[i + 1], t + sd * 0.5)
                    if H[i] < -0.2 or H[i + 1] < -0.2:
                        m.quad((A[0], 0.12, A[1]), (B[0], 0.12, B[1]), (B2[0], 0.12, B2[1]), (A2[0], 0.12, A2[1]), (205, 202, 196))
            # pavement edge inside the trench raised walls are the pavement; underside slab for the crossing road
            casters.append((Polygon([pt(-half, -Wp), pt(half, -Wp), pt(half, Wp), pt(-half, Wp)]).intersection(box(-1, -1, 1, 1).buffer(1)), 0.1))
        # lamps along ramps
        for sdir in (-1, 1):
            for s in np.arange(-half + 20, half - 10, 36):
                if kind == "under" and abs(s) < span + 30:
                    pass
                x, z = pt(s, sdir * (Wp - 0.5))
                tx, tz = pt(s, sdir * (Wp - 2.8))
                y = prof(s)
                if kind == "over" or y > -0.5:
                    m.cyl(x, y + KH, y + KH + 7.0, z, 0.08, POLE, 6)
                    ln = math.hypot(tx - x, tz - z)
                    m.box((x + tx) / 2, y + KH + 6.9, (z + tz) / 2, ln, 0.1, 0.1, POLE, math.atan2(tz - z, tx - x))
                    m.box(tx, y + KH + 6.8, tz, 0.7, 0.14, 0.3, (246, 238, 196), math.atan2(tz - z, tx - x))
        # hole for the trench in the ground plane, drawn later by the engine through scene.hole
        if kind == "under":
            slab = unary_union_([loc["asphalt"], loc["pavement"]]).intersection(holeg)
            m.prism(slab, -1.5, -0.02, (150, 150, 146), (176, 172, 166))

    class R:
        pass
    r = R()
    r.fn, r.footprint, r.hole = fn, foot, holeg
    r.__call__ = fn
    return r
