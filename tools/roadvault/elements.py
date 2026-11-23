"""Extra design elements (signs, furniture, barriers, markings, calming, transit, planting, utilities ...).  Each element is a
table row: id, category, generator, parameters and a layout (where along which arm and on which side it repeats).
Scene.elements = [{"id": "SG12_no_entry", "arm": 1, "d0": 14, "d1": 80, "step": 30, "side": -1, "off": 1.2}, ...]
Every parameter in the row can be overridden by the same keys in the scene entry."""
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import engine as E
from engine import (ASPH, KH, P, WHITE, YELLOW, Y_PAINT, rect, s_hi, s_lo, tree, U)

GREY = (140, 142, 146)
STEEL = (150, 156, 162)
DARK = (50, 52, 58)
BLUE = (30, 90, 190)
RED = (205, 38, 40)
GREEN = (38, 140, 76)
ORANGE = (236, 134, 30)
BRICK = (170, 96, 80)
WOOD = (150, 108, 70)
GLASS = (120, 160, 180)
TXT_W = (250, 250, 250)


def pos(a, d, side, off):
    s = {-1: s_lo(a, d) - off, 1: s_hi(a, d) + off, 0: off}[side]
    return P(a, d, s), s


def vface(m, x, y, z, yaw, pts, col):
    """Vertical polygon in the plane whose normal points along yaw; pts are (u, v) = (sideways, up) in metres."""
    c, s = math.cos(yaw + math.pi / 2), math.sin(yaw + math.pi / 2)
    q = [(x + c * u, y + v, z + s * u) for u, v in pts]
    for i in range(1, len(q) - 1):
        m.tri(q[0], q[i], q[i + 1], col)


def ngon(n, r, rot=0.0):
    return [(r * math.cos(rot + i * 2 * math.pi / n), r * math.sin(rot + i * 2 * math.pi / n)) for i in range(n)]


# ----------------------------------------------------------------- point generators
def g_post(c, a, x, z, yaw, p):
    m = c["m"]
    h, r, col = p.get("h", 1.0), p.get("r", 0.08), p.get("col", GREY)
    m.cyl(x, KH, KH + h, z, r, col, p.get("n", 8))
    if p.get("cap"):
        m.cyl(x, KH + h, KH + h + 0.05, z, r * 1.25, p["cap"], p.get("n", 8))
    if p.get("band"):
        m.cyl(x, KH + h * 0.7, KH + h * 0.82, z, r * 1.05, p["band"], p.get("n", 8))
    if p.get("lamp"):
        m.cyl(x, KH + h - 0.15, KH + h, z, r * 1.1, (255, 244, 200), p.get("n", 8))
    c["casters"].append((Point(x, z).buffer(max(r, 0.1)), h))


def g_box(c, a, x, z, yaw, p):
    m = c["m"]
    w, h, d = p.get("w", 1.0), p.get("h", 1.0), p.get("d", 1.0)
    m.box(x, KH, z, w, h, d, p.get("col", GREY), yaw, roof=p.get("roof"))
    if p.get("stripe"):
        m.box(x, KH + h * 0.55, z, w + 0.02, h * 0.12, d + 0.02, p["stripe"], yaw)
    c["casters"].append((Point(x, z).buffer(max(w, d) * 0.55), h))


def g_bench(c, a, x, z, yaw, p):
    m = c["m"]
    L = p.get("w", 1.8)
    m.box(x, KH, z, 0.12, 0.42, 0.4, DARK, yaw + math.pi / 2)
    m.box(x, KH + 0.42, z, L, 0.07, 0.5, p.get("col", WOOD), yaw)
    if p.get("back", True):
        fx, fz = -math.sin(yaw) * 0.22, math.cos(yaw) * 0.22
        m.box(x + fx, KH + 0.6, z + fz, L, 0.4, 0.05, p.get("col", WOOD), yaw)
    c["casters"].append((Point(x, z).buffer(0.9), 0.9))


def g_shelter(c, a, x, z, yaw, p):
    m = c["m"]
    L, D, H = p.get("w", 3.6), p.get("d", 1.6), p.get("h", 2.5)
    fx, fz = math.cos(yaw), math.sin(yaw)
    gx, gz = -fz, fx
    for sx in (-1, 1):
        for sz in (-1, 1):
            m.cyl(x + fx * sx * L / 2 + gx * sz * D / 2, KH, KH + H, z + fz * sx * L / 2 + gz * sz * D / 2, 0.05, STEEL, 6)
    m.box(x, KH + H, z, L + 0.3, 0.1, D + 0.3, p.get("roof", (70, 76, 84)), yaw)
    m.box(x - gx * D / 2, KH + 0.4, z - gz * D / 2, L, H - 0.5, 0.04, GLASS, yaw)
    for sx in (-1, 1):
        m.box(x + fx * sx * L / 2, KH + 0.4, z + fz * sx * L / 2, 0.04, H - 0.5, D, GLASS, yaw)
    m.box(x, KH, z - gz * D / 2 + gz * 0.3, 1.8, 0.45, 0.4, WOOD, yaw)
    c["casters"].append((Polygon([(x - fx * L / 2 - gx * D / 2, z - fz * L / 2 - gz * D / 2), (x + fx * L / 2 - gx * D / 2, z + fz * L / 2 - gz * D / 2),
                                  (x + fx * L / 2 + gx * D / 2, z + fz * L / 2 + gz * D / 2), (x - fx * L / 2 + gx * D / 2, z - fz * L / 2 + gz * D / 2)]), H))


def g_sign(c, a, x, z, yaw, p):
    """Post with a face: shape circle|triangle|diamond|rect|octagon|invtri, fill, border, bar (symbol stripe)."""
    m = c["m"]
    top = p.get("top", 2.5)
    m.cyl(x, KH, KH + top, z, 0.04, STEEL, 6)
    sh, R = p.get("shape", "circle"), p.get("r", 0.34)
    fill, border, bar = p.get("fill", TXT_W), p.get("border", RED), p.get("bar")
    cy = KH + top - 0.05
    ow = yaw + math.pi / 2                      # face looks back along the arm
    nx, nz = math.cos(yaw), math.sin(yaw)
    for off, col, k in ((0.0, border, 1.0), (0.012, fill, 0.74)):
        rr = R * k
        if sh == "circle":
            pts = ngon(20, rr)
        elif sh == "triangle":
            pts = [(-rr * 1.15, -rr * 0.7), (rr * 1.15, -rr * 0.7), (0, rr * 1.25)]
        elif sh == "invtri":
            pts = [(-rr * 1.15, rr * 0.7), (rr * 1.15, rr * 0.7), (0, -rr * 1.25)]
        elif sh == "diamond":
            pts = [(0, rr * 1.2), (rr * 1.2, 0), (0, -rr * 1.2), (-rr * 1.2, 0)]
        elif sh == "octagon":
            pts = ngon(8, rr, math.pi / 8)
        else:
            pts = [(-rr * 1.1, -rr * 0.8), (rr * 1.1, -rr * 0.8), (rr * 1.1, rr * 0.8), (-rr * 1.1, rr * 0.8)]
        vface(m, x + nx * off, cy, z + nz * off, yaw, pts, col)
    if bar:
        vface(m, x + nx * 0.025, cy, z + nz * 0.025, yaw, [(-R * 0.55, -R * 0.07), (R * 0.55, -R * 0.07), (R * 0.55, R * 0.07), (-R * 0.55, R * 0.07)], bar)
    if p.get("bar2"):
        vface(m, x + nx * 0.025, cy, z + nz * 0.025, yaw, [(-R * 0.07, -R * 0.5), (R * 0.07, -R * 0.5), (R * 0.07, R * 0.5), (-R * 0.07, R * 0.5)], p["bar2"])
    if p.get("plate"):
        vface(m, x + nx * 0.01, cy - R * 1.3, z + nz * 0.01, yaw, [(-R * 0.8, -0.14), (R * 0.8, -0.14), (R * 0.8, 0.14), (-R * 0.8, 0.14)], p["plate"])
    c["casters"].append((Point(x, z).buffer(0.1), top))


def g_light(c, a, x, z, yaw, p):
    m = c["m"]
    h, arms_, reach = p.get("h", 8.0), p.get("arms", 1), p.get("reach", 2.0)
    col = p.get("col", POLE)
    m.cyl(x, KH, KH + h, z, p.get("r", 0.09), col, 6)
    inward = (-math.sin(yaw), math.cos(yaw))
    for k in range(arms_):
        sg = 1 if k == 0 else -1
        tx, tz = x + inward[0] * reach * sg * p.get("dir", 1), z + inward[1] * reach * sg * p.get("dir", 1)
        if reach > 0.2:
            m.box((x + tx) / 2, KH + h - 0.1, (z + tz) / 2, reach, 0.1, 0.1, col, math.atan2(tz - z, tx - x))
        m.box(tx, KH + h - 0.25, tz, p.get("head", 0.7), 0.14, 0.3, (246, 238, 196), math.atan2(tz - z, tx - x))
    if p.get("globe"):
        m.blob(x, KH + h, z, 0.28, 0.5, (250, 244, 214), 8)
    if p.get("catenary"):
        m.box(x, KH + h - 0.4, z, 0.1, 0.1, 8.0, col, yaw)
    c["casters"].append((Point(x, z).buffer(0.1), h))


POLE = (70, 72, 78)


def g_tree(c, a, x, z, yaw, p):
    m = c["m"]
    kind = p.get("kind", "round")
    rnd = c["rnd"]
    h = p.get("h", 6.0)
    y = p.get("y", 0.0)
    if kind == "round":
        tree(m, x, z, rnd, y, p.get("k", 1.0))
    elif kind == "column":
        m.cyl(x, y, y + 1.2, z, 0.12, (92, 72, 56), 6)
        m.blob(x, y + 1.0, z, 0.9, h * 1.0, (62, 112, 62))
    elif kind == "pine":
        m.cyl(x, y, y + 1.5, z, 0.14, (84, 66, 50), 6)
        m.blob(x, y + 1.2, z, 1.7, h * 1.1, (44, 94, 62))
    elif kind == "palm":
        m.cyl(x, y, y + h, z, 0.14, (140, 112, 84), 6)
        for k in range(7):
            ang = k * 2 * math.pi / 7
            m.tri((x, y + h, z), (x + 1.8 * math.cos(ang) - 0.2, y + h - 0.7, z + 1.8 * math.sin(ang)), (x + 1.8 * math.cos(ang) + 0.2, y + h - 0.7, z + 1.8 * math.sin(ang) + 0.2), (74, 132, 70))
    elif kind == "birch":
        m.cyl(x, y, y + h * 0.6, z, 0.1, (226, 224, 216), 6)
        m.blob(x, y + h * 0.4, z, 1.5, h * 0.6, (122, 168, 84))
    elif kind == "olive":
        m.cyl(x, y, y + 1.2, z, 0.2, (110, 94, 80), 6)
        m.blob(x, y + 1.0, z, 1.9, 2.2, (128, 146, 112))
    elif kind == "autumn":
        m.cyl(x, y, y + h * 0.45, z, 0.15, (92, 72, 56), 6)
        m.blob(x, y + h * 0.35, z, 2.1, h * 0.7, (196, 128, 52))
    elif kind == "shrub":
        m.blob(x, y, z, 0.9, 1.0, p.get("col", (74, 126, 70)))
    elif kind == "flowers":
        m.blob(x, y, z, 0.8, 0.5, p.get("col", (214, 90, 130)))
        m.blob(x + 0.5, y, z + 0.3, 0.5, 0.4, (240, 200, 60))
    elif kind == "bamboo":
        for k in range(5):
            m.cyl(x + 0.2 * math.cos(k), y, y + h * 0.8, z + 0.2 * math.sin(k), 0.04, (150, 170, 80), 5)
    c["casters"].append((Point(x, z).buffer(1.6), h))


def g_gantry(c, a, x, z, yaw, p):
    """Portal over the whole carriageway: two posts and a beam with signs / cameras / lanterns."""
    m = c["m"]
    d = p["_d"]
    h = p.get("h", 6.2)
    lo, hi = s_lo(a, d) - 1.2, s_hi(a, d) + 1.2
    for s in (lo, hi):
        px, pz = P(a, d, s)
        m.cyl(px, 0, h + 0.3, pz, 0.2, STEEL, 8)
    ax, az = P(a, d, lo)
    bx, bz = P(a, d, hi)
    yawb = math.atan2(bz - az, bx - ax)
    m.box((ax + bx) / 2, h, (az + bz) / 2, math.hypot(bx - ax, bz - az), 0.4, 0.4, STEEL, yawb)
    kind = p.get("kind", "sign")
    n = max(1, a.lin + a.lout)
    for k in range(n):
        t = (k + 0.5) / n
        sx, sz = ax + (bx - ax) * t, az + (bz - az) * t
        ux, uz = U(a)
        if kind == "sign":
            m.box(sx, h - 1.6, sz, 0.1, 1.5, 3.0, GREEN, yawb + math.pi / 2)
        elif kind == "camera":
            m.box(sx, h - 0.6, sz, 0.5, 0.4, 0.7, DARK, yawb)
        elif kind == "toll":
            m.box(sx, h - 0.5, sz, 1.0, 0.5, 0.4, (36, 90, 170), yawb)
        elif kind == "signal":
            m.box(sx, h - 1.2, sz, 0.32, 0.95, 0.3, E.HEAD, yawb + math.pi / 2)
            m.box(sx + ux * 0.17, h - 0.85, sz + uz * 0.17, 0.06, 0.2, 0.2, (235, 45, 40), yawb + math.pi / 2)
        elif kind == "vms":
            m.box(sx, h - 1.3, sz, 0.3, 1.1, 3.2, (24, 26, 30), yawb + math.pi / 2)
            m.box(sx + ux * 0.16, h - 1.0, sz + uz * 0.16, 0.05, 0.4, 2.6, (255, 170, 40), yawb + math.pi / 2)
    c["casters"].append((LineString([(ax, az), (bx, bz)]).buffer(0.3), h))


def g_planter(c, a, x, z, yaw, p):
    m = c["m"]
    w, h, d = p.get("w", 1.4), p.get("h", 0.6), p.get("d", 1.4)
    m.box(x, KH, z, w, h, d, p.get("col", CONC_ := (176, 172, 164)), yaw)
    m.blob(x, KH + h - 0.05, z, min(w, d) * 0.5, 0.8, p.get("plant", (74, 126, 70)))
    c["casters"].append((Point(x, z).buffer(0.8), h + 0.7))


def g_manhole(c, a, x, z, yaw, p):
    pass


GEN = {"post": g_post, "box": g_box, "bench": g_bench, "shelter": g_shelter, "sign": g_sign, "light": g_light,
       "tree": g_tree, "gantry": g_gantry, "planter": g_planter}


# ----------------------------------------------------------------- line generators (barriers and strips)
def line_strip(c, a, p, d0, d1, side, off):
    """Continuous barrier: kind params h (height), t (thickness), col, post spacing, rail count, top colour."""
    m = c["m"]
    h, t, col = p.get("h", 0.8), p.get("t", 0.12), p.get("col", STEEL)
    step = 2.0
    ds = [d0 + i * step for i in range(int((d1 - d0) / step) + 1)]
    y0 = p.get("y0", KH)
    for i in range(len(ds) - 1):
        (xa, za), sa_ = pos(a, ds[i], side, off)
        (xb, zb), sb_ = pos(a, ds[i + 1], side, off)
        rails = p.get("rails", 0)
        if rails:
            for r in range(rails):
                yy = y0 + h * (r + 1) / (rails + 0.5)
                m.quad((xa, yy, za), (xb, yy, zb), (xb, yy + 0.07, zb), (xa, yy + 0.07, za), col)
        else:
            m.quad((xa, y0, za), (xb, y0, zb), (xb, y0 + h, zb), (xa, y0 + h, za), col)
            if t > 0.03:
                nx, nz = -(zb - za), (xb - xa)
                ln = math.hypot(nx, nz) or 1
                nx, nz = nx / ln * t, nz / ln * t
                m.quad((xa, y0 + h, za), (xb, y0 + h, zb), (xb + nx, y0 + h, zb + nz), (xa + nx, y0 + h, za + nz), p.get("top", col))
        if i % p.get("post_every", 2) == 0 and p.get("posts", True):
            m.cyl(xa, y0, y0 + h + 0.05, za, 0.05, p.get("post", STEEL), 5)
    c["casters"].append((LineString([pos(a, d0, side, off)[0], pos(a, d1, side, off)[0]]).buffer(max(t, 0.1)), h))


# ----------------------------------------------------------------- paint generators (clipped to asphalt)
def paint_gen(kind, a, d0, d1, p):
    """Returns [(polygon, colour)]."""
    out = []
    col = p.get("col", WHITE)
    lo = lambda d: s_lo(a, d) + p.get("pad", 0.0)
    hi = lambda d: s_hi(a, d) - p.get("pad", 0.0)
    if kind == "chevron":
        d = d0
        w_ = hi(d) - lo(d)
        while d + 1.4 < d1:
            for (sa, sb) in ((lo(d), 0.0), (hi(d), 0.0)):
                pass
            out.append((Polygon([P(a, d, lo(d)), P(a, d + 0.5, lo(d)), P(a, d + 0.5 + w_ * 0.5, 0.0), P(a, d + w_ * 0.5, 0.0)]), col))
            out.append((Polygon([P(a, d, hi(d)), P(a, d + 0.5, hi(d)), P(a, d + 0.5 + w_ * 0.5, 0.0), P(a, d + w_ * 0.5, 0.0)]), col))
            d += p.get("gap", 3.0)
    elif kind == "hatch":
        d = d0
        while d + 1.0 < d1:
            out.append((Polygon([P(a, d, lo(d)), P(a, d + 0.4, lo(d)), P(a, d + 0.4 + p.get("sl", 2.5), hi(d)), P(a, d + p.get("sl", 2.5), hi(d))]), col))
            d += p.get("gap", 1.6)
    elif kind == "box":
        out.append((Polygon([P(a, d0, lo(d0)), P(a, d1, lo(d1)), P(a, d1, hi(d1)), P(a, d0, hi(d0))]), p.get("fill", (0, 0, 0, 0))))
        out += [(rect(a, d0, d1, lo(d0), lo(d0) + 0.18), col), (rect(a, d0, d1, hi(d0) - 0.18, hi(d0)), col),
                (rect(a, d0, d0 + 0.18, lo(d0), hi(d0)), col), (rect(a, d1 - 0.18, d1, lo(d0), hi(d0)), col)]
        n = int((d1 - d0) / 1.8)
        for k in range(n + 1):
            dd = d0 + k * 1.8
            out.append((Polygon([P(a, dd, lo(dd)), P(a, dd + 0.18, lo(dd)), P(a, min(d1, dd + 0.18 + (hi(dd) - lo(dd))), hi(dd)), P(a, min(d1, dd + (hi(dd) - lo(dd))), hi(dd))]), col)) if p.get("cross", True) else None
    elif kind == "zigzag":
        d, up = d0, True
        while d + 1.0 < d1:
            s0, s1 = (lo(d) + 0.3, lo(d) + 0.9) if True else (0, 0)
            out.append((Polygon([P(a, d, lo(d) + 0.3), P(a, d + 1.0, lo(d) + 0.9), P(a, d + 1.0, lo(d) + 1.15), P(a, d, lo(d) + 0.55)]) if up else
                        Polygon([P(a, d, lo(d) + 0.9), P(a, d + 1.0, lo(d) + 0.3), P(a, d + 1.0, lo(d) + 0.55), P(a, d, lo(d) + 1.15)]), col))
            up = not up
            d += 1.0
    elif kind == "bars":
        d = d0
        while d < d1:
            out.append((rect(a, d, d + p.get("w", 0.5), lo(d), hi(d)), col))
            d += p.get("gap", 0.9)
    elif kind == "teeth":
        x = lo(d0) + 0.2
        while x < hi(d0) - 0.6:
            out.append((Polygon([P(a, d0, x), P(a, d0, x + 0.7), P(a, d0 + 0.9, x + 0.35)]), col))
            x += 1.0
    elif kind == "bayslines":
        d = d0
        sd = p.get("side", 1)
        while d < d1:
            s_in = hi(d) if sd > 0 else lo(d)
            depth = p.get("depth", 2.4) * sd
            sl = p.get("slant", 0.0)
            out.append((Polygon([P(a, d, s_in), P(a, d + 0.1, s_in), P(a, d + 0.1 + sl, s_in + depth), P(a, d + sl, s_in + depth)]), col))
            d += p.get("pitch", 5.5)
    elif kind == "fill":
        s_a = p.get("s0")
        sb = p.get("s1")
        out.append((Polygon([P(a, d0, lo(d0) + (s_a or 0)), P(a, d1, lo(d1) + (s_a or 0)), P(a, d1, lo(d1) + (sb or 1.9)), P(a, d0, lo(d0) + (sb or 1.9))]), col))
    elif kind == "symbol":
        d = d0
        while d < d1:
            cx, cz = P(a, d, p.get("s", (lo(d) + 1.0)))
            out.append((Point(cx, cz).buffer(0.55), col))
            out.append((Point(cx, cz).buffer(0.38), p.get("inner", p.get("under", (60, 62, 68)))))
            out.append((rect(a, d - 0.45, d + 0.45, p.get("s", lo(d) + 1.0) - 0.07, p.get("s", lo(d) + 1.0) + 0.07), col))
            d += p.get("pitch", 30.0)
    elif kind == "dots":
        d = d0
        while d < d1:
            for s in (lo(d) + 0.5, hi(d) - 0.5) if p.get("both") else (p.get("s", 0.0),):
                x, z = P(a, d, s)
                out.append((Point(x, z).buffer(0.09), col))
            d += p.get("gap", 4.0)
    elif kind == "block":
        d = d0
        while d + 1.2 < d1:
            out.append((rect(a, d, d + 1.2, lo(d) + 0.1, hi(d) - 0.1), col))
            d += 2.4
    elif kind == "line":
        s = p.get("s", 0.0)
        out.append((rect(a, d0, d1, s - p.get("w", 0.15) / 2, s + p.get("w", 0.15) / 2), col))
        if p.get("dash"):
            out.pop()
            d = d0
            while d + p["dash"] < d1:
                out.append((rect(a, d, d + p["dash"], s - p.get("w", 0.15) / 2, s + p.get("w", 0.15) / 2), col))
                d += p["dash"] + p.get("gap", 6.0)
    return out


# ----------------------------------------------------------------- the table
EL = {}          # id -> dict(cat, gen, p, lay)


def reg(id, cat, gen, p=None, **lay):
    EL[id] = dict(cat=cat, gen=gen, p=p or {}, lay=dict(dict(d0=14.0, d1=90.0, step=24.0, side=-1, off=1.2), **lay))


# -- posts and bollards (12)
for i, (n, p) in enumerate([("fixed_bollard", dict(h=0.9, r=0.08, col=GREY)), ("steel_bollard_band", dict(h=1.0, r=0.07, col=STEEL, band=YELLOW)),
                            ("stone_sphere_bollard", dict(h=0.6, r=0.2, col=(170, 166, 158), n=10)), ("flexi_post_white", dict(h=1.0, r=0.04, col=WHITE, band=RED)),
                            ("kerb_delineator", dict(h=0.8, r=0.05, col=(240, 240, 236), band=(30, 30, 34))), ("parking_meter", dict(h=1.35, r=0.06, col=(60, 70, 90), cap=(120, 130, 150))),
                            ("fire_hydrant", dict(h=0.75, r=0.12, col=RED, cap=RED)), ("bike_lock_post", dict(h=0.95, r=0.04, col=STEEL, cap=ORANGE)),
                            ("light_bollard", dict(h=0.9, r=0.1, col=GREY, lamp=True)), ("concrete_bollard_big", dict(h=0.8, r=0.22, col=(176, 172, 164), n=8)),
                            ("street_name_post", dict(h=2.4, r=0.04, col=STEEL, cap=BLUE)), ("delineator_red_white", dict(h=1.2, r=0.05, col=(236, 236, 232), band=RED))]):
    reg(f"BP{i + 1:02d}_{n}", "posts", "post", p, step=7.0, off=0.5)

# -- street furniture (24)
FURN = [("bench_wood", "bench", dict(w=1.8)), ("bench_steel", "bench", dict(w=1.6, col=STEEL)), ("bench_long", "bench", dict(w=3.0)), ("bench_no_back", "bench", dict(back=False)),
        ("bin_green", "box", dict(w=0.5, h=0.9, d=0.5, col=(50, 120, 70))), ("bin_grey", "box", dict(w=0.5, h=0.9, d=0.5, col=(110, 112, 116))), ("recycling_trio", "box", dict(w=1.5, h=1.0, d=0.6, col=(70, 140, 90), stripe=YELLOW)),
        ("bike_rack_u", "box", dict(w=1.6, h=0.8, d=0.1, col=STEEL)), ("bike_shelter", "shelter", dict(w=3.0, d=1.2, h=2.2)), ("bike_share_dock", "box", dict(w=3.0, h=1.0, d=0.5, col=(60, 140, 200), stripe=WHITE)),
        ("kiosk_news", "box", dict(w=2.4, h=2.5, d=2.0, col=(190, 90, 70), roof=(80, 60, 50))), ("phone_booth", "box", dict(w=0.9, h=2.3, d=0.9, col=RED, roof=RED)), ("atm_cabinet", "box", dict(w=1.0, h=2.0, d=0.8, col=(60, 66, 80))),
        ("vending_machine", "box", dict(w=1.0, h=1.9, d=0.8, col=(200, 40, 50), stripe=WHITE)), ("info_panel", "box", dict(w=1.3, h=2.2, d=0.2, col=(40, 90, 170))), ("billboard_small", "box", dict(w=3.0, h=3.0, d=0.2, col=(236, 226, 190))),
        ("flag_pole", "post", dict(h=9.0, r=0.07, col=STEEL, cap=RED)), ("planter_box_wood", "planter", dict(col=WOOD)), ("planter_box_conc", "planter", dict()), ("planter_big_round", "planter", dict(w=2.0, d=2.0, h=0.8, plant=(60, 118, 66))),
        ("flower_planter", "planter", dict(w=1.2, d=1.2, h=0.5, plant=(214, 90, 130))), ("drinking_fountain", "box", dict(w=0.4, h=1.0, d=0.4, col=(150, 150, 154))), ("public_toilet", "box", dict(w=2.2, h=2.6, d=2.2, col=(120, 150, 130))), ("sculpture_cube", "box", dict(w=1.6, h=1.6, d=1.6, col=(170, 150, 120)))]
for i, (n, g, p) in enumerate(FURN):
    reg(f"SF{i + 1:02d}_{n}", "furniture", g, p, step=18.0, off=1.4)

# -- signs (36)
SIGNS = [("speed_30", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK)), ("speed_50", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK, bar2=DARK)), ("speed_60", dict(shape="circle", fill=TXT_W, border=RED)),
         ("speed_80", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK)), ("no_entry", dict(shape="circle", fill=RED, border=RED, bar=TXT_W)), ("one_way", dict(shape="rect", fill=BLUE, border=BLUE, bar=TXT_W, r=0.4)),
         ("no_parking", dict(shape="circle", fill=BLUE, border=RED, bar2=RED)), ("no_stopping", dict(shape="circle", fill=BLUE, border=RED, bar=RED, bar2=RED)), ("school_zone", dict(shape="triangle", fill=YELLOW, border=RED)),
         ("pedestrian_crossing", dict(shape="rect", fill=BLUE, border=TXT_W, bar=TXT_W, r=0.36)), ("cyclists_ahead", dict(shape="triangle", fill=TXT_W, border=RED, bar=DARK)), ("bus_stop_sign", dict(shape="rect", fill=YELLOW, border=DARK, bar=DARK, r=0.34)),
         ("hospital", dict(shape="rect", fill=BLUE, border=TXT_W, bar=RED, bar2=RED, r=0.34)), ("priority_road", dict(shape="diamond", fill=YELLOW, border=TXT_W)), ("end_priority", dict(shape="diamond", fill=TXT_W, border=DARK, bar=DARK)),
         ("roundabout_ahead", dict(shape="circle", fill=BLUE, border=BLUE, bar=TXT_W)), ("give_way", dict(shape="invtri", fill=TXT_W, border=RED)), ("stop_sign", dict(shape="octagon", fill=RED, border=TXT_W, bar=TXT_W)),
         ("no_left_turn", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK)), ("no_right_turn", dict(shape="circle", fill=TXT_W, border=RED, bar2=DARK)), ("no_u_turn", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK, bar2=DARK)),
         ("mandatory_ahead", dict(shape="circle", fill=BLUE, border=BLUE, bar2=TXT_W)), ("mandatory_right", dict(shape="circle", fill=BLUE, border=BLUE, bar=TXT_W)), ("mandatory_left", dict(shape="circle", fill=BLUE, border=BLUE, bar=TXT_W, bar2=TXT_W)),
         ("parking_sign", dict(shape="rect", fill=BLUE, border=BLUE, bar=TXT_W, bar2=TXT_W, r=0.34)), ("height_limit", dict(shape="circle", fill=TXT_W, border=RED, bar=DARK, plate=TXT_W)), ("weight_limit", dict(shape="circle", fill=TXT_W, border=RED, bar2=DARK, plate=TXT_W)),
         ("road_works", dict(shape="triangle", fill=YELLOW, border=RED, bar=DARK)), ("slippery", dict(shape="triangle", fill=YELLOW, border=RED, bar2=DARK)), ("animals", dict(shape="triangle", fill=YELLOW, border=RED, bar=DARK, bar2=DARK)),
         ("tram_ahead", dict(shape="triangle", fill=YELLOW, border=RED, bar=DARK)), ("zebra_ahead_yellow", dict(shape="rect", fill=YELLOW, border=DARK, bar=DARK, r=0.34)), ("direction_blue", dict(shape="rect", fill=BLUE, border=TXT_W, bar=TXT_W, r=0.5, top=2.8)),
         ("direction_green", dict(shape="rect", fill=GREEN, border=TXT_W, bar=TXT_W, r=0.5, top=2.8)), ("speed_camera_ahead", dict(shape="triangle", fill=TXT_W, border=RED, bar=DARK)), ("low_emission_zone", dict(shape="circle", fill=GREEN, border=GREEN, bar=TXT_W))]
for i, (n, p) in enumerate(SIGNS):
    reg(f"SG{i + 1:02d}_{n}", "signs", "sign", p, step=40.0, off=0.7)

# -- lighting (14)
LIGHTS = [("cobra_head", dict(h=8.5, reach=2.2)), ("double_arm", dict(h=8.5, reach=2.2, arms=2)), ("high_mast", dict(h=18.0, reach=0.5, arms=2, head=1.4, r=0.16)), ("post_top_classic", dict(h=4.5, reach=0.0, globe=True)),
          ("tram_catenary_pole", dict(h=8.0, reach=1.0, catenary=True)), ("low_pedestrian", dict(h=3.8, reach=0.5, globe=True, col=(40, 90, 70))), ("long_arm_10m", dict(h=10.0, reach=3.6)),
          ("decorative_double_globe", dict(h=5.0, reach=1.5, arms=2, globe=True)), ("slim_led_post", dict(h=7.0, reach=1.6, col=(200, 204, 210))), ("black_heritage", dict(h=5.5, reach=1.0, globe=True, col=(26, 28, 32))),
          ("bridge_rail_light", dict(h=2.2, reach=0.0, globe=True)), ("tunnel_wall_light", dict(h=4.0, reach=0.4)), ("pole_with_banner", dict(h=8.5, reach=2.2, col=(70, 90, 80))), ("solar_post", dict(h=6.0, reach=1.5, col=(90, 96, 104)))]
for i, (n, p) in enumerate(LIGHTS):
    reg(f"LT{i + 1:02d}_{n}", "lighting", "light", p, step=32.0, off=0.7, d0=14.0)

# -- trees and planting (16)
TREES = [("round", {}), ("column", dict(h=7.0)), ("pine", dict(h=8.0)), ("palm", dict(h=7.0)), ("birch", dict(h=6.5)), ("olive", {}), ("autumn", dict(h=6.5)), ("big_plane", dict(kind="round", k=1.4)),
         ("small_ornamental", dict(kind="round", k=0.7)), ("shrub_green", dict(kind="shrub")), ("shrub_dark", dict(kind="shrub", col=(52, 98, 60))), ("flower_bed_pink", dict(kind="flowers")), ("flower_bed_orange", dict(kind="flowers", col=(230, 140, 40))),
         ("bamboo_clump", dict(kind="bamboo", h=5.0)), ("young_trees", dict(kind="round", k=0.5)), ("tall_poplar", dict(kind="column", h=11.0))]
for i, (n, p) in enumerate(TREES):
    p = dict(p)
    p.setdefault("kind", n if n in ("round", "column", "pine", "palm", "birch", "olive", "autumn") else p.get("kind", "round"))
    reg(f"VG{i + 1:02d}_{n}", "planting", "tree", p, step=11.0, off=2.2)

# -- gantries (10)
for i, (n, p) in enumerate([("sign_gantry", dict(kind="sign")), ("camera_gantry", dict(kind="camera")), ("toll_gantry", dict(kind="toll")), ("signal_portal", dict(kind="signal")), ("vms_gantry", dict(kind="vms")),
                            ("tall_sign_gantry", dict(kind="sign", h=7.4)), ("low_camera_portal", dict(kind="camera", h=5.2)), ("toll_big", dict(kind="toll", h=7.0)), ("signal_portal_low", dict(kind="signal", h=5.4)), ("vms_tall", dict(kind="vms", h=7.2))]):
    reg(f"GA{i + 1:02d}_{n}", "gantries", "gantry", p, d0=40.0, d1=41.0, step=100.0)

# -- barriers and fences (24): continuous strips
BAR = [("guardrail_w_beam", dict(h=0.75, rails=2, col=STEEL)), ("jersey_concrete", dict(h=0.8, t=0.4, col=(176, 172, 166), posts=False)), ("cable_barrier", dict(h=1.0, rails=3, col=(120, 124, 130))),
       ("steel_fence", dict(h=1.2, rails=4, col=(40, 44, 50))), ("wood_fence", dict(h=1.1, t=0.05, col=WOOD, posts=True)), ("hedge_low", dict(h=0.9, t=0.6, col=(66, 118, 64), posts=False)), ("hedge_high", dict(h=1.8, t=0.8, col=(58, 108, 58), posts=False)),
       ("wall_low_stone", dict(h=0.6, t=0.35, col=(186, 180, 168), posts=False)), ("wall_high_brick", dict(h=2.2, t=0.3, col=BRICK, posts=False)), ("noise_wall_conc", dict(h=3.5, t=0.3, col=(170, 170, 168), posts=False)),
       ("noise_wall_glass", dict(h=3.2, t=0.1, col=(150, 190, 206), posts=True)), ("pedestrian_rail", dict(h=1.05, rails=2, col=STEEL)), ("bollard_chain", dict(h=0.7, rails=1, col=(60, 60, 64))), ("chain_link", dict(h=2.0, t=0.03, col=(160, 166, 170))),
       ("parapet_bridge", dict(h=1.1, t=0.25, col=(196, 194, 188), posts=False)), ("balustrade", dict(h=1.0, rails=3, col=(210, 208, 202))), ("crash_barrier_yellow", dict(h=0.9, t=0.4, col=YELLOW, posts=False)), ("tram_fence_green", dict(h=1.0, rails=3, col=(50, 120, 80))),
       ("cycle_wand", dict(h=0.9, rails=1, col=WHITE, post_every=1)), ("kerb_separator", dict(h=0.18, t=0.3, col=(200, 198, 192), posts=False)), ("planter_wall", dict(h=0.8, t=0.7, col=(176, 172, 164), posts=False)), ("temporary_barrier", dict(h=0.9, t=0.4, col=ORANGE, posts=False)),
       ("sand_wall", dict(h=1.4, t=0.8, col=(206, 188, 140), posts=False)), ("gabion_wall", dict(h=1.2, t=0.6, col=(150, 140, 126), posts=False))]
for i, (n, p) in enumerate(BAR):
    reg(f"BR{i + 1:02d}_{n}", "barriers", "line", p, d0=14.0, d1=70.0, step=2.0, off=0.2)

# -- road markings and surface treatments (52): painted on the carriageway
MARK = [("gore_chevrons", "chevron", dict(), dict(d0=16.0, d1=40.0)), ("hatch_diagonal", "hatch", dict(), dict(d0=16.0, d1=40.0)), ("box_junction_yellow", "box", dict(col=YELLOW, cross=True), dict(d0=14.0, d1=22.0)),
        ("school_zigzag", "zigzag", dict(col=YELLOW), dict(d0=16.0, d1=40.0)), ("rumble_strips", "bars", dict(w=0.3, gap=0.7), dict(d0=30.0, d1=36.0)), ("speed_hump_markings", "teeth", dict(), dict(d0=26.0, d1=27.0)),
        ("bike_symbols", "symbol", dict(), dict(d0=18.0, d1=90.0)), ("bus_only_bar", "bars", dict(w=0.4, gap=3.0, col=WHITE), dict(d0=18.0, d1=70.0)), ("yield_teeth", "teeth", dict(), dict(d0=16.0, d1=17.0)),
        ("red_bus_lane", "fill", dict(col=(160, 66, 58), s0=0.0, s1=3.25), dict(d0=14.0, d1=90.0)), ("green_bike_lane", "fill", dict(col=(62, 142, 96), s0=0.0, s1=1.9), dict(d0=14.0, d1=90.0)), ("blue_shared_path", "fill", dict(col=(60, 110, 176), s0=0.0, s1=2.2), dict(d0=14.0, d1=90.0)),
        ("red_bike_lane", "fill", dict(col=(176, 84, 72), s0=0.0, s1=1.9), dict(d0=14.0, d1=90.0)), ("yellow_no_stop_edge", "line", dict(col=YELLOW, s=0.0, w=0.12), dict(d0=14.0, d1=90.0)), ("parking_parallel_lines", "bayslines", dict(side=1, pitch=6.0, depth=2.0), dict(d0=24.0, d1=80.0)),
        ("parking_angled_45", "bayslines", dict(side=1, pitch=3.2, depth=4.6, slant=4.0), dict(d0=24.0, d1=80.0)), ("parking_perpendicular", "bayslines", dict(side=1, pitch=2.6, depth=5.0), dict(d0=24.0, d1=80.0)),
        ("disabled_bay_blue", "fill", dict(col=(60, 110, 176), s0=0.0, s1=2.4), dict(d0=30.0, d1=36.0)), ("ev_bay_green", "fill", dict(col=(70, 160, 100), s0=0.0, s1=2.4), dict(d0=30.0, d1=36.0)), ("loading_zone_yellow", "fill", dict(col=YELLOW, s0=0.0, s1=2.4), dict(d0=30.0, d1=40.0)),
        ("taxi_rank_fill", "fill", dict(col=(220, 190, 60), s0=0.0, s1=2.4), dict(d0=30.0, d1=44.0)), ("keep_clear_block", "block", dict(col=YELLOW), dict(d0=14.0, d1=24.0)), ("cat_eyes_centre", "dots", dict(col=(240, 240, 120), s=0.0, gap=5.0), dict(d0=14.0, d1=90.0)),
        ("edge_cat_eyes", "dots", dict(col=(240, 240, 120), both=True, gap=5.0, pad=0.3), dict(d0=14.0, d1=90.0)), ("tactile_dots_crossing", "dots", dict(col=(240, 210, 60), both=True, gap=1.0), dict(d0=12.0, d1=18.0)),
        ("stop_box_cyclists", "fill", dict(col=(62, 142, 96), s0=0.0, s1=7.0), dict(d0=11.0, d1=14.0)), ("solid_double_line", "line", dict(col=WHITE, s=0.0, w=0.3), dict(d0=14.0, d1=90.0)), ("dashed_centre_long", "line", dict(col=WHITE, s=0.0, w=0.15, dash=3.0, gap=9.0), dict(d0=14.0, d1=90.0)),
        ("dashed_short_lane", "line", dict(col=WHITE, s=-3.25, w=0.15, dash=1.0, gap=1.0), dict(d0=14.0, d1=60.0)), ("red_zone_pedestrian", "fill", dict(col=(176, 84, 72), s0=0.0, s1=5.0), dict(d0=14.0, d1=40.0)), ("yellow_hatch_island", "hatch", dict(col=YELLOW), dict(d0=16.0, d1=40.0)),
        ("white_bars_crossing_wide", "bars", dict(w=0.7, gap=1.4), dict(d0=10.0, d1=13.0)), ("ladder_crossing", "bars", dict(w=0.45, gap=0.9), dict(d0=10.0, d1=13.0)), ("blue_bus_stop_bay", "fill", dict(col=(60, 110, 176), s0=0.0, s1=3.0), dict(d0=30.0, d1=45.0)),
        ("orange_work_zone", "fill", dict(col=ORANGE, s0=0.0, s1=3.25), dict(d0=30.0, d1=50.0)), ("coloured_asphalt_plaza", "fill", dict(col=(176, 150, 128), s0=0.0, s1=7.0), dict(d0=14.0, d1=40.0)),
        ("stop_line_wide", "bars", dict(w=0.6, gap=100.0), dict(d0=10.0, d1=11.0)), ("sharrow_symbols", "symbol", dict(pitch=18.0), dict(d0=18.0, d1=90.0)), ("lane_arrows_wide", "symbol", dict(col=(250, 250, 250), pitch=40.0), dict(d0=18.0, d1=90.0)),
        ("edge_line_thick", "line", dict(col=WHITE, s=0.2, w=0.3), dict(d0=14.0, d1=90.0)), ("yellow_centre_line", "line", dict(col=YELLOW, s=0.0, w=0.15), dict(d0=14.0, d1=90.0)), ("double_yellow", "line", dict(col=YELLOW, s=0.0, w=0.4), dict(d0=14.0, d1=90.0)),
        ("red_edge_no_stopping", "line", dict(col=RED, s=0.15, w=0.15), dict(d0=14.0, d1=90.0)), ("speed_table_stripes", "bars", dict(w=0.5, gap=1.0), dict(d0=26.0, d1=34.0)), ("zebra_continental_long", "bars", dict(w=0.5, gap=1.0), dict(d0=10.0, d1=14.0)),
        ("tram_track_zone_red", "fill", dict(col=(150, 70, 62), s0=0.0, s1=3.0), dict(d0=14.0, d1=90.0)), ("slow_text_block", "block", dict(col=WHITE), dict(d0=40.0, d1=46.0)), ("bike_box_lead", "fill", dict(col=(62, 142, 96), s0=0.0, s1=3.0), dict(d0=10.0, d1=13.0)),
        ("chevron_wide_gore", "chevron", dict(gap=4.0, col=YELLOW), dict(d0=16.0, d1=44.0)), ("hatch_buffer_bike", "hatch", dict(sl=1.0, gap=1.2), dict(d0=16.0, d1=80.0)), ("diagonal_parking_hatch", "hatch", dict(sl=2.0, gap=1.4, col=YELLOW), dict(d0=16.0, d1=40.0))]
for i, (n, kind, p, lay) in enumerate(MARK):
    reg(f"MK{i + 1:02d}_{n}", "markings", "paint:" + kind, p, **lay)


# ----------------------------------------------------------------- slabs / combos / pedestrian structures
def slab_geom(a, d, p, side):
    """Polygon of a raised or painted patch: `len` along the arm, spanning lateral s0..s1 (from the arm axis) or the whole carriageway."""
    ln = p.get("len", 4.0)
    if p.get("full"):
        s0, s1 = s_lo(a, d), s_hi(a, d)
    else:
        w = p.get("w", 1.8)
        s0, s1 = (s_lo(a, d), s_lo(a, d) + w) if side < 0 else (s_hi(a, d) - w, s_hi(a, d))
    return rect(a, d - ln / 2, d + ln / 2, s0, s1)


def g_footbridge(c, a, d, p):
    m = c["m"]
    H, W = p.get("h", 5.6), p.get("w", 3.0)
    lo, hi = s_lo(a, d) - 3.0, s_hi(a, d) + 3.0
    A_, B_ = P(a, d, lo), P(a, d, hi)
    yaw = math.atan2(B_[1] - A_[1], B_[0] - A_[0])
    ln = math.hypot(B_[0] - A_[0], B_[1] - A_[1])
    cx, cz = (A_[0] + B_[0]) / 2, (A_[1] + B_[1]) / 2
    m.box(cx, H, cz, ln, 0.35, W, (186, 184, 178), yaw)
    for sg in (-1, 1):
        m.box(cx - math.sin(yaw) * sg * (W / 2 - 0.05), H + 0.35, cz + math.cos(yaw) * sg * (W / 2 - 0.05), ln, 1.0, 0.06, (170, 200, 214), yaw)
    for end, s in ((0, lo), (1, hi)):
        sg = -1 if end == 0 else 1
        for k in range(int(H / 0.18)):
            x, z = P(a, d, s + sg * (-0.2 + k * 0.42) * -1)
            m.box(x, k * 0.18, z, 0.45, 0.18 * (1), W - 0.4, (190, 188, 182), yaw + math.pi / 2)
        px, pz = P(a, d, s)
        m.box(px, 0, pz, 1.0, H, 1.0, (176, 172, 166), yaw + math.pi / 2)
    for s in (lo + 1.0, hi - 1.0):
        pass
    c["casters"].append((Polygon([P(a, d - W / 2, lo), P(a, d + W / 2, lo), P(a, d + W / 2, hi), P(a, d - W / 2, hi)]), H))


def g_stairs(c, a, x, z, yaw, p):
    m = c["m"]
    n = p.get("n", 8)
    fx, fz = math.cos(yaw), math.sin(yaw)
    for k in range(n):
        m.box(x + fx * k * 0.32, KH, z + fz * k * 0.32, 0.34, 0.15 * (k + 1), p.get("w", 2.4), (190, 188, 182), yaw)


def g_disc(c, a, x, z, yaw, p):
    m = c["m"]
    m.cyl(x, KH, KH + p.get("h", 0.15), z, p.get("r", 0.4), p.get("col", (60, 62, 68)), 14)


def g_pole_util(c, a, x, z, yaw, p):
    m = c["m"]
    h = p.get("h", 9.0)
    m.cyl(x, KH, KH + h, z, 0.14, (110, 90, 70), 6)
    m.box(x, KH + h - 0.5, z, 0.1, 0.1, 2.2, (110, 90, 70), yaw)
    m.box(x, KH + h - 1.2, z, 0.1, 0.1, 1.6, (110, 90, 70), yaw)
    c["casters"].append((Point(x, z).buffer(0.15), h))


def g_fountain(c, a, x, z, yaw, p):
    m = c["m"]
    m.cyl(x, KH, KH + 0.5, z, p.get("r", 2.2), (170, 170, 168), 18)
    m.cyl(x, KH + 0.5, KH + 0.55, z, p.get("r", 2.2) - 0.25, (80, 140, 190), 18)
    m.cyl(x, KH + 0.5, KH + 2.0, z, 0.2, (200, 204, 210), 8)


def g_monument(c, a, x, z, yaw, p):
    m = c["m"]
    m.box(x, KH, z, 2.0, 0.8, 2.0, (186, 182, 174), yaw)
    m.cyl(x, KH + 0.8, KH + p.get("h", 6.0), z, 0.45, p.get("col", (206, 200, 190)), 8)
    c["casters"].append((Point(x, z).buffer(1.0), p.get("h", 6.0)))


def g_pergola(c, a, x, z, yaw, p):
    m = c["m"]
    fx, fz = math.cos(yaw), math.sin(yaw)
    gx, gz = -fz, fx
    for sx in (-1, 1):
        for sz in (-1, 1):
            m.cyl(x + fx * sx * 1.6 + gx * sz * 1.6, KH, KH + 2.6, z + fz * sx * 1.6 + gz * sz * 1.6, 0.08, WOOD, 6)
    for k in range(7):
        m.box(x - fx * 1.6 + fx * k * 0.53, KH + 2.6, z - fz * 1.6 + fz * k * 0.53, 0.1, 0.1, 3.8, WOOD, yaw)
    c["casters"].append((Point(x, z).buffer(2.0), 2.6))


GEN.update({"stairs": g_stairs, "disc": g_disc, "util_pole": g_pole_util, "fountain": g_fountain, "monument": g_monument, "pergola": g_pergola})

# -- traffic calming (14): slabs on the carriageway
CALM = [("speed_hump_round", dict(len=3.6, full=True, h=0.08, col=(78, 80, 86), stripe=True)), ("speed_table_brick", dict(len=7.0, full=True, h=0.1, col=BRICK)), ("raised_crossing_red", dict(len=3.6, full=True, h=0.1, col=(176, 84, 72), stripe=True)),
        ("speed_cushion_pair", dict(len=3.0, w=1.8, h=0.08, col=(78, 80, 86))), ("pinch_point_both", dict(len=6.0, w=1.8, h=KH, col=(196, 192, 184), both=True)), ("chicane_buildout", dict(len=6.0, w=1.9, h=KH, col=(196, 192, 184))),
        ("kerb_extension_crossing", dict(len=5.0, w=2.2, h=KH, col=(196, 192, 184), both=True)), ("bulb_out_tree", dict(len=5.0, w=2.0, h=KH, col=(196, 192, 184), tree=True)), ("diverter_planter", dict(len=3.0, w=2.5, h=0.7, col=(176, 172, 164))),
        ("raised_junction_plateau", dict(len=12.0, full=True, h=0.1, col=(150, 142, 134))), ("rumble_raised", dict(len=0.4, full=True, h=0.04, col=WHITE)), ("coloured_island_nose", dict(len=3.0, w=1.4, h=KH, col=(196, 192, 184))),
        ("road_narrowing_islands", dict(len=8.0, w=2.0, h=KH, col=(196, 192, 184), both=True)), ("mini_rb_disc", dict(len=3.6, w=3.6, h=0.08, col=WHITE, disc=True))]
for i, (n, p) in enumerate(CALM):
    reg(f"TC{i + 1:02d}_{n}", "calming", "slab", p, d0=22.0, d1=60.0, step=40.0, side=-1)

# -- public transport (14)
TRANSIT = [("bus_stop_full", dict(parts=[("shelter", 0, 1.0, dict()), ("sign", 5, 0.5, dict(shape="rect", fill=YELLOW, border=DARK, bar=DARK)), ("bench", -4, 1.0, {})], slab=dict(len=14.0, w=2.8, h=0.2))),
           ("bus_stop_pole", dict(parts=[("sign", 0, 0.5, dict(shape="rect", fill=YELLOW, border=DARK, bar=DARK))])), ("tram_platform", dict(parts=[("shelter", 0, 1.4, dict(w=5.0))], slab=dict(len=30.0, w=2.6, h=0.3))),
           ("tram_stop_double", dict(parts=[("shelter", -6, 1.4, dict(w=4.0)), ("shelter", 6, 1.4, dict(w=4.0))], slab=dict(len=32.0, w=2.6, h=0.3))), ("taxi_rank", dict(parts=[("sign", 0, 0.5, dict(shape="rect", fill=BLUE, border=TXT_W, bar=YELLOW))], slab=dict(len=0.1, w=0.1, h=0.0))),
           ("bike_dock_station", dict(parts=[("box", 0, 1.2, dict(w=3.0, h=1.0, d=0.5, col=(60, 140, 200), stripe=WHITE)), ("box", 4, 1.2, dict(w=3.0, h=1.0, d=0.5, col=(60, 140, 200)))])),
           ("scooter_parking_row", dict(parts=[("box", i * 1.0, 1.0, dict(w=0.4, h=1.0, d=1.2, col=(70, 190, 130))) for i in range(5)])), ("park_ride_sign", dict(parts=[("sign", 0, 0.5, dict(shape="rect", fill=BLUE, border=TXT_W, bar=TXT_W, top=3.2, r=0.55))])),
           ("bus_gate_sign", dict(parts=[("sign", 0, 0.5, dict(shape="circle", fill=TXT_W, border=RED, bar=DARK, plate=TXT_W))])), ("pickup_bay", dict(parts=[("sign", 0, 0.5, dict(shape="rect", fill=BLUE, border=TXT_W, bar=TXT_W))], slab=dict(len=10.0, w=2.4, h=0.0))),
           ("bus_stop_island", dict(parts=[("shelter", 0, 0.0, dict())], slab=dict(len=14.0, w=3.0, h=0.2))), ("trolley_pole_pair", dict(parts=[("light", 0, 0.7, dict(h=8.0, reach=1.0, catenary=True)), ("light", 30, 0.7, dict(h=8.0, reach=1.0, catenary=True))])),
           ("rail_crossing_gate", dict(parts=[("box", 0, 0.8, dict(w=0.4, h=2.4, d=0.4, col=RED, stripe=WHITE))])), ("tram_signal_post", dict(parts=[("light", 0, 0.7, dict(h=4.0, reach=0.5, globe=True, col=(40, 40, 46)))]))]
for i, (n, p) in enumerate(TRANSIT):
    reg(f"PT{i + 1:02d}_{n}", "transit", "combo", p, d0=30.0, d1=31.0, step=100.0, off=1.0)

# -- pedestrian infrastructure and plazas (14)
PED = [("footbridge_stairs", "footbridge", dict(h=5.6)), ("footbridge_high", "footbridge", dict(h=6.4, w=3.4)), ("stair_run", "stairs", dict(n=8)), ("stair_run_wide", "stairs", dict(n=10, w=4.0)),
       ("fountain_round", "fountain", dict(r=2.2)), ("fountain_big", "fountain", dict(r=3.4)), ("monument_column", "monument", dict(h=7.0)), ("monument_obelisk", "monument", dict(h=10.0, col=(190, 184, 170))),
       ("pergola_shade", "pergola", dict()), ("pedestrian_island_planted", "planter", dict(w=3.0, d=1.6, h=0.2, plant=(74, 126, 70))), ("pavers_planter_big", "planter", dict(w=2.6, d=2.6, h=0.45)),
       ("art_cube", "box", dict(w=1.2, h=2.4, d=1.2, col=(210, 120, 60))), ("sun_umbrella", "post", dict(h=2.6, r=0.04, col=STEEL, cap=(200, 70, 60))), ("lookout_post", "post", dict(h=1.2, r=0.15, col=(150, 146, 138), cap=(176, 172, 164)))]
for i, (n, g, p) in enumerate(PED):
    reg(f"PD{i + 1:02d}_{n}", "pedestrian", g, p, d0=20.0, d1=70.0, step=40.0, off=2.0)

# -- utilities (12)
UTIL = [("manhole_round", "disc", dict(r=0.38, h=0.012, col=(80, 82, 86), road=True)), ("manhole_pair", "disc", dict(r=0.3, h=0.012, col=(70, 72, 76), road=True)), ("drain_grate", "disc", dict(r=0.5, h=0.012, col=(50, 52, 58), road=True)),
        ("valve_cover", "disc", dict(r=0.2, h=0.01, col=(90, 94, 98), road=False)), ("utility_pole", "util_pole", dict()), ("utility_pole_tall", "util_pole", dict(h=12.0)), ("power_cabinet", "box", dict(w=1.2, h=1.5, d=0.8, col=(120, 140, 130))),
        ("transformer_box", "box", dict(w=2.2, h=2.2, d=1.8, col=(130, 134, 122))), ("mail_box", "box", dict(w=0.5, h=1.3, d=0.4, col=(240, 200, 40))), ("telecom_cabinet", "box", dict(w=1.0, h=1.4, d=0.5, col=(110, 112, 116))),
        ("gas_marker_post", "post", dict(h=1.3, r=0.05, col=YELLOW, cap=RED)), ("water_meter_box", "disc", dict(r=0.25, h=0.01, col=(100, 100, 104), road=False))]
for i, (n, g, p) in enumerate(UTIL):
    reg(f"UT{i + 1:02d}_{n}", "utilities", g, p, d0=18.0, d1=88.0, step=22.0, off=1.0)


# ----------------------------------------------------------------- applying
def apply(scene, loc):
    """Draw every Scene.elements entry:  {"id", "arm", optional d0 d1 step side off + any generator parameter}."""
    from shapely.geometry import box as sbox
    m, asphalt, pavement = loc["m"], loc["asphalt"], loc["pavement"]
    c = {"m": m, "rnd": loc["rnd"], "casters": loc["casters"], "asphalt": asphalt}
    for ent in scene.elements:
        row = EL[ent["id"]]
        a = scene.arms[ent.get("arm", 0)]
        p = dict(row["p"])
        lay = dict(row["lay"])
        for k, v in ent.items():
            if k in lay:
                lay[k] = v
            elif k not in ("id", "arm"):
                p[k] = v
        gen = row["gen"]
        d0, d1, step, off = lay["d0"] + a.e, lay["d1"] + a.e if lay["d1"] > 1.0 else lay["d1"], lay["step"], lay["off"]
        sides = (-1, 1) if lay["side"] == 2 else (lay["side"],)
        ua = U(a)
        yaw_u = math.atan2(ua[1], ua[0])
        if gen.startswith("paint:"):
            for g, col in paint_gen(gen[6:], a, d0, d1, p):
                if len(col) == 4 and col[3] == 0:
                    continue
                y = E.Y_SURF + 0.004 if gen.endswith("fill") else Y_PAINT + 0.004
                m.poly(g.intersection(asphalt), y, col)
            continue
        if gen == "line":
            for sd in sides:
                line_strip(c, a, p, d0, d1, sd, off)
            continue
        if gen == "footbridge":
            g_footbridge(c, a, d0, p)
            continue
        if gen == "gantry":
            p["_d"] = d0
            g_gantry(c, a, 0, 0, 0, p)
            continue
        d = d0
        while d <= d1 + 1e-6:
            for sd in sides:
                (x, z), s = pos(a, d, sd, off)
                yaw = yaw_u if sd <= 0 else yaw_u + math.pi
                if gen == "slab":
                    pol = slab_geom(a, d, p, sd if sd else -1)
                    cols = [p.get("col", (78, 80, 86))]
                    if p.get("disc"):
                        pol = Point(*P(a, d, 0.0)).buffer(1.8)
                    parts = [pol]
                    if p.get("both"):
                        parts.append(slab_geom(a, d, p, 1))
                    for pl in parts:
                        h = p.get("h", 0.08)
                        on = pl.intersection(asphalt.buffer(0.4)) if h < KH else pl
                        m.prism(on, 0.0, h if h > 0 else 0.01, cols[0], KERB_FACE_) if h > 0.02 else m.poly(on, E.Y_SURF + 0.004, cols[0])
                        if p.get("stripe") and h > 0.02:
                            n = int(p.get("len", 3.6) / 0.7)
                            for k in range(0, n, 2):
                                dd = d - p.get("len", 3.6) / 2 + k * 0.7
                                m.poly(rect(a, dd, dd + 0.35, s_lo(a, d), s_hi(a, d)).intersection(asphalt), h + 0.004, WHITE)
                    if p.get("tree"):
                        tree(m, *P(a, d, s_lo(a, d) - 1.0), c["rnd"], KH)
                elif gen == "combo":
                    sl = p.get("slab")
                    if sl and sl.get("h", 0) > 0:
                        pl = slab_geom(a, d, dict(sl), sd)
                        m.prism(pl.difference(asphalt).intersection(sbox(-250, -250, 250, 250)), 0.0, sl["h"] + KH * 0.0, (206, 202, 192), KERB_FACE_) if sl["h"] > 0 else None
                    for (g2, dd, lat, pp) in p["parts"]:
                        (x2, z2), s2 = pos(a, d + dd, sd, off + lat - 1.0 + 1.0)
                        GEN[g2](c, a, x2, z2, yaw, pp)
                elif gen in GEN:
                    if p.get("road"):
                        x, z = P(a, d, (s_lo(a, d) + s_hi(a, d)) / 2 + (0.0 if sd < 0 else 1.0))
                        if not asphalt.contains(Point(x, z)):
                            continue
                        m.cyl(x, 0.0, p.get("h", 0.012), z, p.get("r", 0.4), p.get("col", (80, 82, 86)), 14)
                        continue
                    if asphalt.contains(Point(x, z)) and gen not in ("sign",):
                        pass
                    GEN[gen](c, a, x, z, yaw, p)
            d += step
            if step >= 100:
                break


KERB_FACE_ = (170, 168, 162)
