"""Reference junction designer: a 4-arm signalised intersection drawn from clean, made-up lane data.

This is the target look for the city build.  Every OSM junction should be replaced by a design like this (lane counts,
median, kerb radii, crossings, stop lines, arrows, signals, lamps, signs and trees all decided by rules, not by raw OSM).

    xvfb-run -a python tools/junction_design.py out_dir
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mapbox_earcut as earcut  # noqa: E402

SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)

LW = 3.25              # lane width (m)
SW = 3.0               # pavement width
KERB = 0.15
R = 9.0                # corner kerb radius
L = 95.0               # arm length drawn
ASPH, KTOP, KFACE = (58, 60, 66), (206, 204, 198), (228, 226, 220)
WHITE, GRASS, GROUND = (250, 250, 246), (112, 150, 88), (138, 168, 104)
POLE, HEAD = (66, 68, 72), (34, 35, 38)


class Mesh:
    def __init__(self):
        self.P, self.C = [], []

    def tri(self, a, b, c, col, lit=True):
        a, b, c = np.array(a, float), np.array(b, float), np.array(c, float)
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        k = 1.0
        if lit and ln > 1e-12:
            n = n / ln
            if n[1] < 0:
                n = -n
            k = 0.55 + 0.45 * max(0.0, float(n @ SUN))
        cc = [min(255, int(v * k)) for v in col] + [255]
        self.P += [a, b, c]
        self.C += [cc] * 3

    def quad(self, a, b, c, d, col):
        self.tri(a, b, c, col)
        self.tri(a, c, d, col)

    def poly(self, pts, y, col):
        v = np.array(pts, np.float64)
        for t in np.array(earcut.triangulate_float64(v, np.array([len(v)], np.uint32))).reshape(-1, 3):
            self.tri((v[t[0]][0], y, v[t[0]][1]), (v[t[1]][0], y, v[t[1]][1]), (v[t[2]][0], y, v[t[2]][1]), col)

    def strip(self, A, B, y, col):
        for i in range(len(A) - 1):
            self.quad((A[i][0], y, A[i][1]), (A[i + 1][0], y, A[i + 1][1]), (B[i + 1][0], y, B[i + 1][1]), (B[i][0], y, B[i][1]), col)

    def wall(self, A, y0, y1, col):
        for i in range(len(A) - 1):
            self.quad((A[i][0], y0, A[i][1]), (A[i + 1][0], y0, A[i + 1][1]), (A[i + 1][0], y1, A[i + 1][1]), (A[i][0], y1, A[i][1]), col)

    def box(self, x, y0, z, sx, sy, sz, col, yaw=0.0):
        c, s = math.cos(yaw), math.sin(yaw)

        def q(dx, dz):
            return (x + dx * c - dz * s, z + dx * s + dz * c)
        base = [q(-sx / 2, -sz / 2), q(sx / 2, -sz / 2), q(sx / 2, sz / 2), q(-sx / 2, sz / 2)]
        for i in range(4):
            a, b = base[i], base[(i + 1) % 4]
            self.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + sy, b[1]), (a[0], y0 + sy, a[1]), col)
        self.quad(*[(p[0], y0 + sy, p[1]) for p in base], col)

    def cyl(self, x, y0, y1, z, r, col, n=8):
        pts = [(x + r * math.cos(a * 2 * math.pi / n), z + r * math.sin(a * 2 * math.pi / n)) for a in range(n + 1)]
        self.wall(pts, y0, y1, col)

    def octa(self, x, y, z, r, h, col):
        ring = [(x + r * math.cos(a * math.pi / 3), z + r * math.sin(a * math.pi / 3)) for a in range(7)]
        for i in range(6):
            a, b = ring[i], ring[i + 1]
            self.tri((a[0], y, a[1]), (b[0], y, b[1]), (x, y + h, z), col)
            self.tri((b[0], y, b[1]), (a[0], y, a[1]), (x, y - h * 0.5, z), col)


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


class Arm:
    """One approach: u = unit vector pointing away from the junction; p = u rotated; inbound lanes are at s < 0."""

    def __init__(self, name, u, thru, nout, med, h):
        self.name, self.u, self.p = name, u, (-u[1], u[0])
        self.thru, self.nout, self.med, self.h = thru, nout, med, h
        self.left_pocket = med >= LW + 1.5

    def at(self, d, s):
        return (self.u[0] * (self.h + d) + self.p[0] * s, self.u[1] * (self.h + d) + self.p[1] * s)

    def pocket(self, d):
        return smooth((60.0 - d) / 20.0) if self.left_pocket else 0.0

    def s_out_in(self):
        return -(self.med / 2 + self.thru * LW)

    def s_med_in(self, d):
        return -self.med / 2 + self.pocket(d) * LW

    def s_out_out(self):
        return self.med / 2 + self.nout * LW


def build(arms, m):
    ex = max(max(-a.s_out_in(), a.s_out_out()) for a in arms if a.name in "NS")
    ez = max(max(-a.s_out_in(), a.s_out_out()) for a in arms if a.name in "EW")
    # asphalt outline with filleted corners (counter-clockwise N, W, S, E)
    def arc(sx, sz):
        X, Z = sx * ex, sz * ez
        return [(X - sx * R * math.cos(t * math.pi / 2) + sx * R, Z - sz * R * math.sin(t * math.pi / 2) + sz * R) for t in [k / 10 for k in range(11)]]
    out = [(-ex, -L - ez)]
    nw = arc(-1, -1)                                   # from the N arm edge round to the W arm edge
    out += [(nw[0][0], nw[0][1])] + nw + [(-L - ex, nw[-1][1]), (-L - ex, ez)]
    sw = arc(-1, 1)[::-1]
    out += sw + [(sw[-1][0], L + ez + R), (ex, L + ez + R)]
    se = arc(1, 1)
    out += se + [(L + ex + R, se[-1][1]), (L + ex + R, -ez)]
    ne = arc(1, -1)[::-1]
    out += ne + [(ne[-1][0], -L - ez)]
    m.poly(out, 0.0, ASPH)
    # pavements + kerbs: offset the straight runs outward and the arcs to radius R + SW
    def corner_runs():
        for sx, sz in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
            X, Z = sx * ex, sz * ez
            cx, cz = X + sx * R, Z + sz * R
            inner, outer = [], []
            inner.append((X, sz * (L + ez + R)))
            outer.append((X + sx * SW, sz * (L + ez + R)))
            for k in range(11):
                a = k / 10 * math.pi / 2
                vx, vz = -sx * math.cos(a), -sz * math.sin(a)
                inner.append((cx + vx * R, cz + vz * R))
                outer.append((cx + vx * (R - SW), cz + vz * (R - SW)))
            inner.append((sx * (L + ex + R), Z))
            outer.append((sx * (L + ex + R), Z + sz * SW))
            yield inner, outer
    for inner, outer in corner_runs():
        m.strip(inner, outer, KERB, KTOP)
        m.wall(inner, 0.0, KERB, KFACE)
    # outer ground
    m.quad((-L - 40, -0.3, -L - 40), (L + 40, -0.3, -L - 40), (L + 40, -0.3, L + 40), (-L - 40, -0.3, L + 40), GROUND)
    for a in arms:
        arm_details(a, m)


def lane_centres(a, d):
    c = [a.s_out_in() + LW * (k + 0.5) for k in range(a.thru)]
    pk = a.pocket(d)
    if pk > 0.02:
        c.append(a.s_out_in() + a.thru * LW + pk * LW / 2)
    return c


def line(m, a, s0, s1, d0, d1, w, y=0.05, col=WHITE):
    """Painted line along the arm from d0 to d1 at lateral s (may vary linearly s0 -> s1), width w."""
    n = max(1, int((d1 - d0) / 2))
    for i in range(n):
        da, db = d0 + (d1 - d0) * i / n, d0 + (d1 - d0) * (i + 1) / n
        sa, sb = s0 + (s1 - s0) * i / n, s0 + (s1 - s0) * (i + 1) / n
        m.quad(*[(q[0], y, q[1]) for q in (a.at(da, sa - w / 2), a.at(db, sb - w / 2), a.at(db, sb + w / 2), a.at(da, sa + w / 2))], col)


def dashed(m, a, s, d0, d1, w=0.15, dash=3.0, gap=6.0):
    d = d0
    while d + dash <= d1 + 1e-6:
        line(m, a, s, s, d, d + dash, w)
        d += dash + gap


def arrow(m, a, d, s, kind):
    """Lane arrow for an inbound lane; the car travels towards the junction (-u); right of travel is -p."""
    fwd, right = (-a.u[0], -a.u[1]), (-a.p[0], -a.p[1])
    cx, cz = a.at(d, s)

    def P(f, r):
        return (cx + fwd[0] * f + right[0] * r, cz + fwd[1] * f + right[1] * r)
    y = 0.05
    sg = {"left": -1.0, "right": 1.0}.get(kind, 0.0)
    pts = [(-1.8, 0.0), (-0.3, 0.0)] if sg == 0 else [(-1.8, 0.0), (-0.2, 0.0), (0.8, 1.0 * sg)]
    for i in range(len(pts) - 1):
        (f0, r0), (f1, r1) = pts[i], pts[i + 1]
        dx, dz = f1 - f0, r1 - r0
        ln = math.hypot(dx, dz)
        nf, nr = -dz / ln * 0.14, dx / ln * 0.14
        m.quad(*[(q[0], y, q[1]) for q in (P(f0 + nf, r0 + nr), P(f1 + nf, r1 + nr), P(f1 - nf, r1 - nr), P(f0 - nf, r0 - nr))], WHITE)
    (f0, r0), (f1, r1) = pts[-2], pts[-1]
    dx, dz = f1 - f0, r1 - r0
    ln = math.hypot(dx, dz)
    tf, tr = dx / ln, dz / ln
    nf, nr = -tr, tf
    tip = (f1 + tf * 1.0, r1 + tr * 1.0)
    m.tri(*[(q[0], y, q[1]) for q in (P(f1 + nf * 0.55, r1 + nr * 0.55), P(*tip), P(f1 - nf * 0.55, r1 - nr * 0.55))], WHITE)


def signal_head(m, x, z, yaw, red):
    m.box(x, 3.4, z, 0.35, 1.0, 0.3, HEAD, yaw)
    fx, fz = -math.sin(yaw), math.cos(yaw)
    for k, c in enumerate(((235, 45, 40) if red else (90, 50, 50), (110, 100, 40), (60, 200, 95) if not red else (40, 80, 50))):
        m.box(x + fx * 0.17, 4.2 - k * 0.3 - 0.0, z + fz * 0.17, 0.22, 0.2, 0.06, c, yaw)


def arm_details(a, m, signals=True, yield_=False, island=None, trees=True, Ln=None, lamps=True):
    Ln = Ln or L
    out_e, out_o = a.s_out_in(), a.s_out_out()
    sl = 6.0                                   # stop line distance from the arm start
    y = 0.05
    # zebra across the whole arm, stripes along the travel direction
    s = out_e + 0.4
    while s < out_o - 0.3:
        line(m, a, s, s, 1.4, 4.6, 0.5, y=y)
        s += 1.0
    # stop line over the inbound lanes
    top = -a.med / 2 if a.med else 0
    if yield_:
        sx_ = out_e + 0.4
        while sx_ < (a.s_med_in(0) if a.med else -0.1) - 0.5:
            m.tri(*[(q[0], y, q[1]) for q in (a.at(sl, sx_), a.at(sl, sx_ + 0.6), a.at(sl + 0.8, sx_ + 0.3))], WHITE)
            sx_ += 0.9
    else:
      m.quad(*[(q[0], y, q[1]) for q in (a.at(sl - 0.25, out_e + 0.2), a.at(sl + 0.25, out_e + 0.2), a.at(sl + 0.25, a.s_med_in(0) if a.med else -0.1), a.at(sl - 0.25, a.s_med_in(0) if a.med else -0.1))], WHITE)
    # edge lines
    line(m, a, out_e + 0.35, out_e + 0.35, sl + 0.6, Ln, 0.15)
    line(m, a, out_o - 0.35, out_o - 0.35, sl + 0.6, Ln, 0.15)
    # lane dividers
    for k in range(1, a.thru):
        s_ = out_e + LW * k
        line(m, a, s_, s_, sl + 0.6, 35.0, 0.15)
        dashed(m, a, s_, 35.0, Ln)
    if a.left_pocket:
        s_ = out_e + a.thru * LW
        line(m, a, s_, s_, sl + 0.6, 40.0, 0.15)
        dashed(m, a, s_, 40.0, 62.0, dash=2.0, gap=3.0)
    for k in range(1, a.nout):
        dashed(m, a, a.med / 2 + LW * k, 12.0, Ln)
    if not a.med:
        line(m, a, 0.0, 0.0, sl + 0.6, Ln, 0.15)
    # arrows
    cs = lane_centres(a, 0.0)
    for d in (10.0, 26.0):
        if d > Ln - 3.0:
            continue
        for i, s_ in enumerate(cs):
            kind = "left" if (a.left_pocket and i == len(cs) - 1) else ("right" if i == 0 and len(cs) > 1 and d == 10.0 else "thru")
            if a.thru == 1 and not a.left_pocket:
                kind = "thru"
            arrow(m, a, d, s_, kind)
    # median island with rounded nose, grass and a kerb
    if a.med:
        d0 = island[0] if island else 8.0
        d1 = island[1] if island else Ln
        ds = [d0 + 1.2 * i for i in range(int((d1 - d0) / 1.2) + 1)]
        ends = []
        # rounded nose first
        nose_w = (a.med / 2 - a.s_med_in(d0)) / 2
        cx_s = (a.med / 2 + a.s_med_in(d0)) / 2
        left = [a.at(d, a.s_med_in(d)) for d in ds]
        right = [a.at(d, a.med / 2) for d in ds]
        m.strip(left, right, KERB, KTOP)
        L2 = [a.at(d, a.s_med_in(d) + 0.35) for d in ds]
        R2 = [a.at(d, a.med / 2 - 0.35) for d in ds]
        m.strip(L2, R2, KERB + 0.02, GRASS)
        m.wall(left, 0.0, KERB, KFACE)
        m.wall(right, 0.0, KERB, KFACE)
        # nose cap: a half circle of kerb + grass
        arc = [a.at(d0 - nose_w * math.sin(math.pi * k / 16), cx_s - nose_w * math.cos(math.pi * k / 16)) for k in range(17)]
        for i in range(16):
            c0 = a.at(d0, cx_s)
            m.tri((c0[0], KERB, c0[1]), (arc[i][0], KERB, arc[i][1]), (arc[i + 1][0], KERB, arc[i + 1][1]), KTOP)
        m.wall(arc, 0.0, KERB, KFACE)
        if island:                                      # tail nose
            arc2 = [a.at(ds[-1] + nose_w * math.sin(math.pi * k / 16), cx_s - nose_w * math.cos(math.pi * k / 16)) for k in range(17)]
            c1 = a.at(ds[-1], cx_s)
            for i in range(16):
                m.tri((c1[0], KERB, c1[1]), (arc2[i][0], KERB, arc2[i][1]), (arc2[i + 1][0], KERB, arc2[i + 1][1]), KTOP)
            m.wall(arc2, 0.0, KERB, KFACE)
        for d in (range(16, int(Ln), 14) if trees else ()):                 # median trees
            x, z = a.at(d, (a.s_med_in(d) + a.med / 2) / 2)
            m.cyl(x, KERB, 2.6, z, 0.12, (96, 76, 58), 6)
            m.octa(x, 2.4, z, 1.7, 2.2, (66, 120, 66))
    # street furniture on the outer pavement
    for side, s_edge in ((-1, out_e), (1, out_o)):
        sp = s_edge + side * (SW - 0.7)
        for d in (range(14, int(Ln), 30) if lamps else ()):                 # lamps
            x, z = a.at(d, sp)
            m.cyl(x, KERB, 8.0, z, 0.1, POLE, 6)
            ax_, az_ = -a.p[0] * side * -1, -a.p[1] * side * -1
            tx, tz = a.at(d, sp - side * 1.8)
            m.box((x + tx) / 2, 7.9, (z + tz) / 2, 1.9, 0.1, 0.1, POLE, math.atan2(tz - z, tx - x))
            m.box(tx, 7.8, tz, 0.5, 0.15, 0.25, (240, 232, 190), math.atan2(tz - z, tx - x))
        for d in range(22, int(Ln), 15):                 # pavement trees
            if (d // 15) % 2:
                continue
            x, z = a.at(d, s_edge + side * (SW + 1.2))
            m.cyl(x, 0, 2.4, z, 0.12, (96, 76, 58), 6)
            m.octa(x, 2.1, z, 1.6, 2.1, (78, 130, 70))
        # pedestrian crossing sign + speed sign
        x, z = a.at(5.0, sp)
        m.cyl(x, KERB, 2.6, z, 0.045, POLE, 6)
        m.box(x, 2.6, z, 0.6, 0.6, 0.04, (30, 90, 190), math.atan2(a.u[1], a.u[0]) + math.pi / 2)
        if side == 1:
            x, z = a.at(48.0, sp)
            m.cyl(x, KERB, 2.4, z, 0.045, POLE, 6)
            m.cyl(x, 2.4, 2.46, z, 0.32, (210, 40, 40), 12)
            m.cyl(x, 2.46, 2.47, z, 0.24, (250, 250, 250), 12)
    # signals: pole behind the stop line on the inbound kerb, mast arm on boulevards
    red = a.name in "NS"
    if not signals:
        return
    x, z = a.at(sl + 2.0, out_e - SW + 0.9)
    m.cyl(x, KERB, 4.2, z, 0.1, POLE, 8)
    yaw = math.atan2(a.u[1], a.u[0]) + math.pi / 2
    signal_head(m, x, z, yaw, red)
    if a.med:
        x, z = a.at(sl + 2.0, out_e - SW + 0.9)
        m.cyl(x, 4.2, 7.0, z, 0.12, POLE, 8)
        tx, tz = a.at(sl + 2.0, a.s_med_in(sl) - 0.5)
        m.box((x + tx) / 2, 6.8, (z + tz) / 2, math.hypot(tx - x, tz - z), 0.15, 0.15, POLE, math.atan2(tz - z, tx - x))
        for t in (0.5, 0.9):
            hx, hz = x + (tx - x) * t, z + (tz - z) * t
            signal_head(m, hx, hz, yaw, red)
    # pedestrian signal heads at the zebra ends
    for side, s_edge in ((-1, out_e), (1, out_o)):
        x, z = a.at(0.6, s_edge + side * 0.9)
        m.cyl(x, KERB, 2.8, z, 0.05, POLE, 6)
        m.box(x, 2.1, z, 0.3, 0.5, 0.2, HEAD, math.atan2(a.u[1], a.u[0]))
        m.box(x, 2.4, z, 0.18, 0.16, 0.05, (235, 45, 40) if red else (60, 200, 95), math.atan2(a.u[1], a.u[0]))


def design():
    m = Mesh()
    N = Arm("N", (0, -1), thru=2, nout=2, med=5.0, h=0.0)
    S = Arm("S", (0, 1), thru=2, nout=2, med=5.0, h=0.0)
    E = Arm("E", (1, 0), thru=1, nout=1, med=0.0, h=0.0)
    W = Arm("W", (-1, 0), thru=1, nout=1, med=0.0, h=0.0)
    ex = max(max(-a.s_out_in(), a.s_out_out()) for a in (N, S))
    ez = max(max(-a.s_out_in(), a.s_out_out()) for a in (E, W))
    for a in (N, S):
        a.h = ez + R
    for a in (E, W):
        a.h = ex + R
    # the arms start at the tangent point of the corner arcs; the outline above shifts by the same amount
    build([N, S, E, W], m)
    return m


def render(m, out_dir):
    import pyray as rl
    import road_shot as rs
    os.makedirs(out_dir, exist_ok=True)
    pos = np.array(m.P, np.float32)
    col = np.array(m.C, np.uint8)
    pos, col = rs.both_sides(pos, col)
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN | rl.FLAG_MSAA_4X_HINT)
    size = (1400, 900)
    rl.init_window(size[0], size[1], "junction")
    rt = rl.load_render_texture(*size)
    models = rs.model(pos, col)
    views = {"aerial": ((60, 120, -120), (0, 0, 0)), "top": ((0, 190, 1), (0, 0, 0)), "corner": ((40, 22, -40), (14, 0, -14)),
             "driver": ((-3.2, 1.7, -95), (0, 1.0, 0)), "side": ((70, 30, 60), (0, 0, 20))}
    for name, (eye, tgt) in views.items():
        cam = rl.Camera3D(eye, tgt, (0, 1, 0), 45.0, rl.CAMERA_PERSPECTIVE)
        rl.begin_texture_mode(rt)
        rl.clear_background((196, 214, 232, 255))
        rl.begin_mode_3d(cam)
        for mo in models:
            rl.draw_model(mo, (0, 0, 0), 1.0, rl.WHITE)
        rl.end_mode_3d()
        rl.end_texture_mode()
        img = rl.load_image_from_texture(rt.texture)
        rl.image_flip_vertical(img)
        rl.export_image(img, os.path.join(out_dir, f"{name}.png"))
        rl.unload_image(img)
    rl.close_window()


if __name__ == "__main__":
    render(design(), sys.argv[1] if len(sys.argv) > 1 else "junction_out")
