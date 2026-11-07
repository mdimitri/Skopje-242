"""Procedural "Warrior on a Horse" monument (Alexander the Great) in the fountain of Macedonia Square.

Stands at the centre of the OSM fountain basin (way 176160189, ~11.5 m radius): a stone plinth in the water, a lion-guarded
base tier, a relief pedestal, a tall column, and on top a bronze rearing horse with a sword-raising rider; a stone rim and
water jets ring the basin. Plain numpy triangles (material 'solid'), like furniture.py. x east, y up, z south.
"""
import math

import numpy as np

from furniture import G

CX, CZ = 287.3, 151.6          # basin centre in world metres (centroid of the OSM fountain polygon)
YAW = 0.35                      # statue faces east-north-east, towards the Vardar / Stone Bridge
STONE, STONE2, RELIEF = (206, 198, 182), (170, 164, 152), (120, 98, 62)
BRONZE, BRONZE2, STEEL = (150, 116, 58), (122, 94, 46), (200, 204, 208)
WATER = (196, 226, 246)


def _unit(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) or 1.0)


def ring_pts(c, ax, r, n, u, v):
    return [tuple(np.asarray(c) + r * (math.cos(2 * math.pi * i / n) * u + math.sin(2 * math.pi * i / n) * v)) for i in range(n)]


def tube(g, a, b, r0, r1, col, n=8):
    """Tapered tube from a to b (radius r0 at a, r1 at b), open ends."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ax = _unit(b - a)
    u = _unit(np.cross(ax, (0, 1, 0)) if abs(ax[1]) < 0.95 else np.cross(ax, (1, 0, 0)))
    v = np.cross(ax, u)
    A, B = ring_pts(a, ax, r0, n, u, v), ring_pts(b, ax, r1, n, u, v)
    for i in range(n):
        j = (i + 1) % n
        m = math.pi * (i + 0.5) * 2 / n
        nrm = math.cos(m) * u + math.sin(m) * v
        g.quad(A[i], A[j], B[j], B[i], col, tuple(nrm))


def blob(g, c, ax, rx, ry, rz, col, st=5, sl=9):
    """Ellipsoid centred at c; ax = unit direction of the first (rx) axis, ry along world-up-ish, rz sideways."""
    c = np.asarray(c, float)
    e1 = _unit(ax)
    e3 = _unit(np.cross(e1, (0, 1, 0)))
    e2 = np.cross(e3, e1)
    def P(i, j):
        th, ph = math.pi * i / st, 2 * math.pi * j / sl
        return c + rx * math.cos(th) * e1 + math.sin(th) * (ry * math.cos(ph) * e2 + rz * math.sin(ph) * e3)
    for i in range(st):
        for j in range(sl):
            p = [P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)]
            n = _unit(np.cross(p[1] - p[0], p[3] - p[0]) if i else np.cross(p[2] - p[0], p[3] - p[0]))
            if np.dot(n, p[0] - c) < 0:
                n = -n
            g.quad(*[tuple(q) for q in p], col, tuple(n))


def disc(g, cx, y, cz, r0, r1, h, col, n=24):
    """Stepped cylinder / frustum from y to y+h."""
    c0, c1 = (cx, y, cz), (cx, y + h, cz)
    tube(g, c0, c1, r0, r1, col, n)
    top = [(cx + r1 * math.cos(2 * math.pi * i / n), y + h, cz + r1 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(1, n - 1):
        g.tri(top[0], top[i + 1], top[i], col, (0, 1, 0))


def build_statue():
    g = G()
    x0, z0 = CX, CZ
    fx, fz = math.cos(YAW), math.sin(YAW)
    sx, sz = -fz, fx

    def W(f, h, s=0.0, base=0.0):
        return (x0 + fx * f + sx * s, base + h, z0 + fz * f + sz * s)

    def L(f, s):                                 # horizontal direction for a local (fwd, side) offset
        return fx * f + sx * s, fz * f + sz * s

    # ---- plinth in the water, base tier with lions, relief pedestal, column ----
    disc(g, x0, 0.0, z0, 5.6, 5.4, 0.9, STONE2)
    disc(g, x0, 0.9, z0, 4.6, 4.4, 0.5, STONE)
    yb = 1.4
    g.box(x0, yb, z0, 6.4, 1.2, 6.4, STONE, YAW)
    g.box(x0, yb + 1.2, z0, 5.4, 0.25, 5.4, STONE2, YAW)
    for fa, sa in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        lion(g, x0 + fx * fa * 3.4 + sx * sa * 3.4, z0 + fz * fa * 3.4 + sz * sa * 3.4, YAW + math.atan2(sa, fa), yb)
    yp = yb + 1.45
    g.box(x0, yp, z0, 4.4, 3.0, 4.4, STONE, YAW)                           # relief pedestal
    for k in range(4):                                                      # bronze relief panels on the four faces
        a = YAW + k * math.pi / 2
        px, pz = math.cos(a), math.sin(a)
        for t in (-0.95, 0.95):
            g.box(x0 + px * 2.23 - pz * t, yp + 0.4, z0 + pz * 2.23 + px * t, 0.12, 2.2, 1.4, RELIEF, a)
    g.box(x0, yp + 3.0, z0, 5.0, 0.3, 5.0, STONE2, YAW)
    yc = yp + 3.3
    disc(g, x0, yc, z0, 1.9, 1.5, 0.6, STONE)
    disc(g, x0, yc + 0.6, z0, 1.3, 1.15, 7.2, STONE)                        # the column
    for h in (2.2, 4.4, 6.4):
        disc(g, x0, yc + 0.6 + h, z0, 1.38, 1.38, 0.18, STONE2)
    disc(g, x0, yc + 7.8, z0, 1.15, 1.9, 0.7, STONE2)                       # capital
    g.box(x0, yc + 8.5, z0, 3.4, 0.35, 3.4, STONE, YAW)                     # abacus
    top = yc + 8.85

    # ---- horse (local f = forward, h = up above the abacus, s = side) ----
    def T(f, h, s=0.0):
        return W(f, h, s, top)

    ax = (fx * 0.62, 0.78, fz * 0.62)
    blob(g, T(-0.2, 3.5), ax, 2.4, 0.95, 0.85, BRONZE)                     # barrel, rearing ~50 deg
    blob(g, T(0.9, 4.5), ax, 1.0, 1.0, 0.95, BRONZE)                        # chest
    blob(g, T(-1.4, 2.7), ax, 1.0, 1.0, 0.95, BRONZE)                       # rump
    tube(g, T(1.0, 4.7), T(2.3, 6.6), 0.62, 0.38, BRONZE, 8)                # neck
    tube(g, T(2.3, 6.6), T(3.5, 6.05), 0.40, 0.26, BRONZE, 8)               # head
    tube(g, T(3.5, 6.05), T(3.75, 5.9), 0.26, 0.2, BRONZE2, 8)              # muzzle
    for s in (-0.28, 0.28):
        tube(g, T(2.45, 6.95, s), T(2.3, 7.35, s), 0.1, 0.02, BRONZE2, 5)   # ears
        tube(g, T(1.0, 4.4, s * 1.6), T(2.2, 5.5, s * 1.6), 0.3, 0.2, BRONZE, 7)       # raised forelegs: upper
        tube(g, T(2.2, 5.5, s * 1.6), T(3.1, 5.0, s * 1.6), 0.2, 0.13, BRONZE, 7)      # lower (bent)
        tube(g, T(3.1, 5.0, s * 1.6), T(3.35, 4.7, s * 1.6), 0.13, 0.17, BRONZE2, 6)   # hoof
        tube(g, T(-1.6, 2.7, s * 1.6), T(-2.4, 1.6, s * 1.6), 0.42, 0.24, BRONZE, 7)   # hind: thigh
        tube(g, T(-2.4, 1.6, s * 1.6), T(-1.7, 0.18, s * 1.6), 0.22, 0.14, BRONZE, 7)  # cannon
        hx_, hy_, hz_ = T(-1.7, 0.0, s * 1.6)
        g.box(hx_, hy_, hz_, 0.45, 0.2, 0.45, BRONZE2, YAW)
    tube(g, T(-2.0, 3.2), T(-3.2, 2.4), 0.2, 0.12, BRONZE2, 6)             # tail
    tube(g, T(-3.2, 2.4), T(-3.4, 1.0), 0.12, 0.05, BRONZE2, 6)
    tube(g, T(1.2, 5.4), T(2.1, 6.9), 0.12, 0.1, BRONZE2, 5)
    # ---- rider ----
    tube(g, T(-0.3, 4.55), T(0.15, 6.15), 0.5, 0.42, BRONZE, 8)             # torso
    blob(g, T(0.2, 6.85), (0, 1, 0), 0.3, 0.3, 0.3, BRONZE)                  # head
    tube(g, T(0.2, 6.9), T(0.2, 7.35), 0.3, 0.16, STEEL, 8)                  # helmet
    tube(g, T(0.2, 7.3), T(-0.25, 7.55), 0.06, 0.18, BRONZE2, 5)             # crest
    for s in (-0.55, 0.55):                                                  # thighs and shins either side of the horse
        tube(g, T(-0.2, 4.55, s * 0.5), T(0.35, 4.3, s * 1.2), 0.25, 0.2, BRONZE, 6)
        tube(g, T(0.35, 4.3, s * 1.2), T(0.1, 3.0, s * 1.3), 0.2, 0.12, BRONZE, 6)
    tube(g, T(0.0, 6.0, 0.35), T(0.85, 7.4, 0.65), 0.17, 0.12, BRONZE, 6)  # sword arm raised
    tube(g, T(0.85, 7.4, 0.65), T(1.2, 9.6, 0.8), 0.045, 0.01, STEEL, 5)    # sword blade
    tube(g, T(0.0, 6.0, -0.35), T(0.7, 5.3, -0.7), 0.17, 0.12, BRONZE, 6)  # shield arm
    blob(g, T(0.8, 5.3, -0.85), (0, 1, 0), 0.08, 0.5, 0.5, BRONZE2, 4, 8)   # shield
    cape = [T(-0.4, 6.1, 0.0), T(-0.4, 6.1, 0.5), T(-1.7, 3.9, 0.7), T(-1.7, 3.9, -0.4)]
    g.quad(*cape, BRONZE2, (-fz, 0, fx))
    g.quad(*cape[::-1], BRONZE2, (fz, 0, -fx))
    return g


def lion(g, x, z, yaw, y):
    """Seated bronze lion on a corner of the base tier, facing along yaw."""
    fx, fz = math.cos(yaw), math.sin(yaw)

    def T(f, h, s=0.0):
        return (x + fx * f - fz * s, y + 1.2 + h, z + fz * f + fx * s)

    blob(g, T(-0.2, 0.55), (fx, 0, fz), 0.75, 0.42, 0.4, BRONZE)
    blob(g, T(0.35, 1.15), (fx, 0.6, fz), 0.35, 0.45, 0.35, BRONZE)           # chest, raised
    blob(g, T(0.7, 1.55), (fx, 0, fz), 0.3, 0.3, 0.28, BRONZE2)               # mane
    blob(g, T(0.9, 1.5), (fx, 0, fz), 0.2, 0.2, 0.2, BRONZE)                  # head
    for s in (-0.22, 0.22):
        tube(g, T(0.45, 0.8, s), T(0.55, 0.0, s), 0.1, 0.09, BRONZE, 6)       # forelegs
        tube(g, T(-0.6, 0.3, s * 1.3), T(-0.2, 0.0, s * 1.3), 0.17, 0.1, BRONZE, 6)
    tube(g, T(-0.9, 0.4), T(-1.2, 0.05), 0.06, 0.03, BRONZE2, 5)


def build_basin():
    """Stone rim ring and water jets. Returns a list of (centre x, centre z, G)."""
    out = []
    n, R0, R1, hh = 48, 11.1, 12.5, 0.55
    for k in range(8):                                                    # rim in 8 arcs so each lands in its own chunk
        g = G()
        for i in range(k * n // 8, (k + 1) * n // 8):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            am = (a0 + a1) / 2
            p = lambda r, a, y: (CX + r * math.cos(a), y, CZ + r * math.sin(a))
            g.quad(p(R1, a0, 0), p(R1, a1, 0), p(R1, a1, hh), p(R1, a0, hh), STONE, (math.cos(am), 0, math.sin(am)))
            g.quad(p(R0, a1, 0), p(R0, a0, 0), p(R0, a0, hh), p(R0, a1, hh), STONE2, (-math.cos(am), 0, -math.sin(am)))
            g.quad(p(R0, a0, hh), p(R0, a1, hh), p(R1, a1, hh), p(R1, a0, hh), STONE, (0, 1, 0))
        out.append(g)
    g = G()                                                                 # water jets: arcs from the rim towards the centre
    for i in range(16):
        a = 2 * math.pi * i / 16 + 0.1
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        for t in range(7):
            u = t / 6
            r = 10.2 - 4.2 * u
            pts.append((CX + ca * r, 0.4 + 4.0 * 4 * u * (1 - u) * (0.65 if i % 2 else 1.0), CZ + sa * r))
        for q in range(6):
            tube(g, pts[q], pts[q + 1], 0.07, 0.07, WATER, 4)
    for i in range(8):                                                      # short jets around the plinth
        a = 2 * math.pi * i / 8
        r = 6.2
        tube(g, (CX + math.cos(a) * r, 0.3, CZ + math.sin(a) * r), (CX + math.cos(a) * (r + 0.6), 2.6, CZ + math.sin(a) * (r + 0.6)), 0.09, 0.03, WATER, 4)
    out.append(g)
    return out


def build(add, chunk_of, terrain_h=None):
    """Places the monument; returns collision posts [(x, z, r, y_bottom, y_top)] for the plinth."""
    for g in [build_statue()] + build_basin():
        pos, uv, col = g.out()
        if len(pos):
            add(chunk_of(float(pos[:, 0].mean()), float(pos[:, 2].mean())), 3, pos, uv, col)
    t = float(terrain_h(CX, CZ)) if terrain_h else 0.0
    return [(CX, CZ, 3.3, t - 1.0, t + 30.0)]
