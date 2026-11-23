"""More reference designs on top of junction_design: roundabout, underpass roundabout, overpass.

    xvfb-run -a python tools/junction_scenes.py out_dir
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import junction_design as jd  # noqa: E402
from junction_design import (ASPH, GRASS, GROUND, KERB, KFACE, KTOP, LW, SW, WHITE, Arm, Mesh, arm_details, smooth)  # noqa: E402

CONC = (186, 184, 178)
APRON = (190, 184, 172)


def lerp_ang(a0, a1, t):
    d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    return a0 + d * t


def roundabout(m, Ln_by_arm=None, ro=20.6, ri=12.0, f=10.0):
    """4-arm roundabout: ring with a planted island and apron, splitter islands, filleted kerb returns."""
    dirs = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
    arms = []
    probe = Arm("N", (0, -1), 1, 1, 3.0, 0.0)
    a_ = max(-probe.s_out_in(), probe.s_out_out())
    yc = math.sqrt((ro + f) ** 2 - (a_ + f) ** 2)
    tc = math.atan2(a_ + f, yc)
    for name, u in dirs.items():
        arms.append(Arm(name, u, 1, 1, 3.0, yc))
    arms.sort(key=lambda a: math.atan2(a.u[1], a.u[0]))
    Ln_by_arm = Ln_by_arm or {}

    def W(a, d, s):
        return a.at(d - a.h, s)                       # local (d from ring centre, s) -> world

    outline = []
    runs = []                                         # pavement strips (inner, outer)
    for k, a in enumerate(arms):
        ph = math.atan2(a.u[1], a.u[0])
        prv = arms[k - 1]
        php = math.atan2(prv.u[1], prv.u[0])
        far = yc + Ln_by_arm.get(a.name, 90.0)
        # circle arc from previous arm's +tc to this arm's -tc
        a0, a1 = php + tc, ph - tc
        if a1 < a0:
            a1 += 2 * math.pi
        for i in range(13):
            t = a0 + (a1 - a0) * i / 12
            outline.append((ro * math.cos(t), ro * math.sin(t)))
        ring_in = [(ro * math.cos(a0 + (a1 - a0) * i / 12), ro * math.sin(a0 + (a1 - a0) * i / 12)) for i in range(13)]
        ring_out = [((ro + SW) * math.cos(a0 + (a1 - a0) * i / 12), (ro + SW) * math.sin(a0 + (a1 - a0) * i / 12)) for i in range(13)]
        runs.append((ring_in, ring_out))
        for sig in (-1, 1):
            cf = (yc, sig * (a_ + f))                 # fillet centre (local d, s)
            dl = (0.0, -sig * f)                      # line tangent relative to centre
            n = math.hypot(*cf)
            dc = (-f * cf[0] / n, -f * cf[1] / n)
            al, ac = math.atan2(dl[1], dl[0]), math.atan2(dc[1], dc[0])
            def pts(rad):
                out = []
                for i in range(11):
                    t = i / 10
                    ang = lerp_ang(ac, al, t) if sig == -1 else lerp_ang(al, ac, t)
                    out.append(W(a, cf[0] + rad * math.cos(ang), cf[1] + rad * math.sin(ang)))
                return out
            inn, out_ = pts(f), pts(f - SW)
            if sig == -1:                             # leaving the ring along the left edge
                tail_in = [W(a, far, -a_)]
                tail_out = [W(a, far, -(a_ + SW))]
                outline += inn + tail_in
                runs.append((inn + tail_in, out_ + tail_out) if False else (inn + [tail_in[0]], out_ + [tail_out[0]]))
            else:                                     # coming back along the right edge
                tail_in = [W(a, far, a_)]
                tail_out = [W(a, far, a_ + SW)]
                outline += tail_in + inn
                runs.append(([tail_in[0]] + inn, [tail_out[0]] + out_))
            if sig == -1:
                outline += [W(a, far, a_)]            # across the far end
    m.poly(outline, 0.0, ASPH)
    for inner, outer in runs:
        m.strip(inner, outer, KERB, KTOP)
        m.wall(inner, 0.0, KERB, KFACE)
    # ring island with an apron and planted centre
    def disc(r, y, col, n=40):
        c = [(r * math.cos(i * 2 * math.pi / n), r * math.sin(i * 2 * math.pi / n)) for i in range(n + 1)]
        for i in range(n):
            m.tri((0, y, 0), (c[i][0], y, c[i][1]), (c[i + 1][0], y, c[i + 1][1]), col)
        return c
    disc(ri + 1.8, 0.06, APRON)
    rim = disc(ri, KERB, KTOP)
    m.wall(rim, 0.0, KERB, KFACE)
    disc(ri - 0.6, KERB + 0.06, GRASS)
    for k in range(5):
        ang = k * 2 * math.pi / 5
        x, z = 5.0 * math.cos(ang), 5.0 * math.sin(ang)
        m.cyl(x, KERB, 3.0, z, 0.15, (96, 76, 58), 6)
        m.octa(x, 2.7, z, 2.0, 2.6, (68, 122, 68))
    m.cyl(0, KERB, 0.6, 0, 1.3, CONC, 12)
    # ring markings: dashed lane line and solid inner edge
    n = 72
    for i in range(0, n, 2):
        a0, a1 = i * 2 * math.pi / n, (i + 1) * 2 * math.pi / n
        r = ri + 1.8 + 3.4
        w = 0.07
        m.quad(*[((r + dr) * math.cos(t), 0.05, (r + dr) * math.sin(t)) for t, dr in ((a0, -w), (a1, -w), (a1, w), (a0, w))], WHITE)
    for i in range(72):
        a0, a1 = i * 2 * math.pi / 72, (i + 1) * 2 * math.pi / 72
        r = ri + 1.8 + 0.12
        w = 0.07
        m.quad(*[((r + dr) * math.cos(t), 0.05, (r + dr) * math.sin(t)) for t, dr in ((a0, -w), (a1, -w), (a1, w), (a0, w))], WHITE)
    m.quad((-200, -0.3, -200), (200, -0.3, -200), (200, -0.3, 200), (-200, -0.3, 200), GROUND) if not getattr(m, "no_ground", False) else None
    for a in arms:
        arm_details(a, m, signals=False, yield_=True, island=(0.5, 34.0), trees=False, Ln=Ln_by_arm.get(a.name, 90.0))
    return arms, yc


def ped_ground(m, x0, x1, z0, z1):
    m.quad((x0, -0.3, z0), (x1, -0.3, z0), (x1, -0.3, z1), (x0, -0.3, z1), GROUND)


def underpass_roundabout(m):
    ro, D, Lr = 20.6, 6.0, 80.0
    m.no_ground = True
    yc = math.sqrt((ro + 10) ** 2 - (4.75 + 10) ** 2)
    z0 = ro + 26.0
    arms, yc = roundabout(m, Ln_by_arm={"N": z0 - yc - 6, "S": z0 - yc - 6, "E": 90.0, "W": 90.0})
    Wd = 9.0                                         # half width of the trench
    # ground: both sides full length, over the tunnel only
    ped_ground(m, -200, -Wd, -200, 200)
    ped_ground(m, Wd, 200, -200, 200)
    ped_ground(m, -Wd, Wd, -z0, z0)

    def fy(z):
        az = abs(z)
        if az <= z0:
            return -D
        if az >= z0 + Lr:
            return 0.0
        return -D * (1 - smooth((az - z0) / Lr))
    zs = [z0 + i * 2.0 for i in range(int((Lr + 60) / 2) + 1)]
    for sgn in (-1, 1):
        zz = [sgn * z for z in zs]
        # carriageway floor + lane paint + central barrier
        for lo, hi, col in ((-Wd, Wd, ASPH),):
            for i in range(len(zz) - 1):
                m.quad((lo, fy(zz[i]), zz[i]), (hi, fy(zz[i]), zz[i]), (hi, fy(zz[i + 1]), zz[i + 1]), (lo, fy(zz[i + 1]), zz[i + 1]), col)
        for sx in (-Wd + 0.4, Wd - 0.4):
            for i in range(len(zz) - 1):
                m.quad((sx - 0.07, fy(zz[i]) + 0.04, zz[i]), (sx + 0.07, fy(zz[i]) + 0.04, zz[i]), (sx + 0.07, fy(zz[i + 1]) + 0.04, zz[i + 1]), (sx - 0.07, fy(zz[i + 1]) + 0.04, zz[i + 1]), WHITE)
        for sx in (-Wd / 2 - 0.2, Wd / 2 + 0.2):
            for i in range(0, len(zz) - 1, 3):
                m.quad((sx - 0.07, fy(zz[i]) + 0.04, zz[i]), (sx + 0.07, fy(zz[i]) + 0.04, zz[i]), (sx + 0.07, fy(zz[i + 1]) + 0.04, zz[i + 1]), (sx - 0.07, fy(zz[i + 1]) + 0.04, zz[i + 1]), WHITE)
        for i in range(len(zz) - 1):                    # central concrete barrier
            for dx in (-0.4, 0.4):
                m.quad((dx, fy(zz[i]), zz[i]), (dx, fy(zz[i]) + 0.8, zz[i]), (dx, fy(zz[i + 1]) + 0.8, zz[i + 1]), (dx, fy(zz[i + 1]), zz[i + 1]), CONC)
            m.quad((-0.4, fy(zz[i]) + 0.8, zz[i]), (0.4, fy(zz[i]) + 0.8, zz[i]), (0.4, fy(zz[i + 1]) + 0.8, zz[i + 1]), (-0.4, fy(zz[i + 1]) + 0.8, zz[i + 1]), (210, 208, 202))
        for sx in (-Wd, Wd):                            # retaining walls + coping + railing
            for i in range(len(zz) - 1):
                m.quad((sx, fy(zz[i]), zz[i]), (sx, 0.0, zz[i]), (sx, 0.0, zz[i + 1]), (sx, fy(zz[i + 1]), zz[i + 1]), CONC)
                m.quad((sx - 0.3, 0.0, zz[i]), (sx + 0.3, 0.0, zz[i]), (sx + 0.3, 0.0, zz[i + 1]), (sx - 0.3, 0.0, zz[i + 1]), KTOP)
            for i in range(0, len(zz), 2):
                m.box(sx + (0.2 if sx > 0 else -0.2), 0.0, zz[i], 0.08, 1.1, 0.08, jd.POLE)
            m.box(sx + (0.2 if sx > 0 else -0.2), 1.05, (zz[0] + zz[-1]) / 2, 0.06, 0.06, abs(zz[-1] - zz[0]), jd.POLE)
    # portal frames
    for sgn in (-1, 1):
        z = sgn * z0
        m.quad((-Wd, -D, z), (Wd, -D, z), (Wd, -D + 4.8, z), (-Wd, -D + 4.8, z), (30, 30, 34))        # dark tunnel mouth
        m.quad((-Wd - 0.3, -D + 4.8, z), (Wd + 0.3, -D + 4.8, z), (Wd + 0.3, 0.0, z), (-Wd - 0.3, 0.0, z), CONC)   # lintel
        m.quad((-Wd - 0.3, 0.0, z), (Wd + 0.3, 0.0, z), (Wd + 0.3, 0.0, z - sgn * 3.0), (-Wd - 0.3, 0.0, z - sgn * 3.0), KTOP)
    return arms


def overpass(m):
    """E-W bridge (2+2, median barrier, pavements, parapets) rising over a N-S boulevard on embankment ramps."""
    H, xs, Lr = 6.5, 13.0, 100.0
    lane, med = 3.25, 1.2
    Wc = 2 * lane
    wd = med / 2 + Wc + 2.4 + 0.5                          # deck half width (z)

    def dy(x):
        ax = abs(x)
        if ax <= xs:
            return H
        if ax >= xs + Lr:
            return 0.0
        return H * (1 - smooth((ax - xs) / Lr))
    m.quad((-260, -0.3, -260), (260, -0.3, -260), (260, -0.3, 260), (-260, -0.3, 260), GROUND)
    xsamp = [-xs - Lr - 60 + i * 2.0 for i in range(int((2 * (xs + Lr + 60)) / 2) + 1)]

    def strip_z(z0, z1, y_off, col):
        for i in range(len(xsamp) - 1):
            x0, x1 = xsamp[i], xsamp[i + 1]
            m.quad((x0, dy(x0) + y_off, z0), (x1, dy(x1) + y_off, z0), (x1, dy(x1) + y_off, z1), (x0, dy(x0) + y_off, z1), col)

    strip_z(-wd, wd, 0.0, ASPH)
    # pavements + kerbs + parapets
    for sg in (-1, 1):
        a, b = sg * (wd - 0.5), sg * (wd - 0.5 - 2.4)
        strip_z(a, b, KERB, KTOP)
        for i in range(len(xsamp) - 1):
            x0, x1 = xsamp[i], xsamp[i + 1]
            zk = b
            m.quad((x0, dy(x0), zk), (x1, dy(x1), zk), (x1, dy(x1) + KERB, zk), (x0, dy(x0) + KERB, zk), KFACE)
            zp = sg * wd
            for zz_, c in ((zp, CONC), (zp - sg * 0.5, CONC)):
                m.quad((x0, dy(x0), zz_), (x1, dy(x1), zz_), (x1, dy(x1) + 1.05, zz_), (x0, dy(x0) + 1.05, zz_), c)
            m.quad((x0, dy(x0) + 1.05, zp), (x1, dy(x1) + 1.05, zp), (x1, dy(x1) + 1.05, zp - sg * 0.5), (x0, dy(x0) + 1.05, zp - sg * 0.5), (212, 210, 204))
            if dy(x0) > 0.4 and abs(x0) <= xs + 0.1:   # soffit + fascia over the boulevard
                m.quad((x0, dy(x0) - 1.1, zp), (x1, dy(x1) - 1.1, zp), (x1, dy(x1), zp), (x0, dy(x0), zp), CONC)
        for i in range(0, len(xsamp), 12):               # lamps
            x = xsamp[i]
            m.cyl(x, dy(x), dy(x) + 8.0, sg * (wd - 0.9), 0.1, jd.POLE, 6)
            m.box(x, dy(x) + 7.9, sg * (wd - 0.9 - sg * 1.2), 0.3, 0.12, 2.0, jd.POLE)
    # median barrier + lane paint
    for dz in (-med / 2, med / 2):
        for i in range(len(xsamp) - 1):
            x0, x1 = xsamp[i], xsamp[i + 1]
            m.quad((x0, dy(x0), dz), (x1, dy(x1), dz), (x1, dy(x1) + 0.8, dz), (x0, dy(x0) + 0.8, dz), CONC)
    for i in range(len(xsamp) - 1):
        x0, x1 = xsamp[i], xsamp[i + 1]
        m.quad((x0, dy(x0) + 0.8, -med / 2), (x1, dy(x1) + 0.8, -med / 2), (x1, dy(x1) + 0.8, med / 2), (x0, dy(x0) + 0.8, med / 2), (212, 210, 204))
    for sg in (-1, 1):
        for zc in (sg * (med / 2 + lane), ):
            for i in range(0, len(xsamp) - 1, 3):
                x0, x1 = xsamp[i], xsamp[i + 1]
                m.quad((x0, dy(x0) + 0.04, zc - 0.07), (x1, dy(x1) + 0.04, zc - 0.07), (x1, dy(x1) + 0.04, zc + 0.07), (x0, dy(x0) + 0.04, zc + 0.07), WHITE)
        ze = sg * (med / 2 + Wc - 0.3)
        for i in range(len(xsamp) - 1):
            x0, x1 = xsamp[i], xsamp[i + 1]
            m.quad((x0, dy(x0) + 0.04, ze - 0.07), (x1, dy(x1) + 0.04, ze - 0.07), (x1, dy(x1) + 0.04, ze + 0.07), (x0, dy(x0) + 0.04, ze + 0.07), WHITE)
    # embankment side slopes (1:2) down to the ground and abutment walls under the deck
    for sg in (-1, 1):
        for i in range(len(xsamp) - 1):
            x0, x1 = xsamp[i], xsamp[i + 1]
            if abs(x0) <= xs:
                continue
            h0, h1 = dy(x0), dy(x1)
            if h0 < 0.02 and h1 < 0.02:
                continue
            m.quad((x0, h0, sg * wd), (x1, h1, sg * wd), (x1, 0.0, sg * (wd + 2 * h1)), (x0, 0.0, sg * (wd + 2 * h0)), (104, 146, 84))
    Wns = 9.5
    for sx in (-1, 1):
        x = sx * xs
        m.quad((x, 0.0, -wd), (x, 0.0, wd), (x, H - 1.1, wd), (x, H - 1.1, -wd), CONC) if False else None
        # abutment faces (the N-S boulevard passes between them)
        m.quad((x, 0.0, -wd), (x, H - 1.1, -wd), (x, H - 1.1, wd), (x, 0.0, wd), CONC)
        for sz in (-1, 1):                                 # wing walls
            m.quad((x, 0.0, sz * wd), (x, H, sz * wd), (x + sx * 0.0, H, sz * wd), (x, 0.0, sz * wd), CONC)
    # N-S boulevard at grade under the bridge
    zl = [-170 + i * 2.0 for i in range(171)]
    mw = 1.5
    for sg in (-1, 1):
        a, b = sg * mw, sg * (mw + 2 * lane)
        for i in range(len(zl) - 1):
            pass
    for i in range(len(zl) - 1):
        z0_, z1_ = zl[i], zl[i + 1]
        if abs(z0_) <= wd + 0.1:
            pass
        m.quad((-(mw + 2 * lane + 0.6), 0.0, z0_), ((mw + 2 * lane + 0.6), 0.0, z0_), ((mw + 2 * lane + 0.6), 0.0, z1_), (-(mw + 2 * lane + 0.6), 0.0, z1_), ASPH)
        m.quad((-mw, KERB, z0_), (mw, KERB, z0_), (mw, KERB, z1_), (-mw, KERB, z1_), GRASS) if abs(z0_) > wd + 6 else None
        for sg in (-1, 1):
            for xx in (sg * (mw + lane),):
                if i % 3 == 0:
                    m.quad((xx - 0.07, 0.04, z0_), (xx + 0.07, 0.04, z0_), (xx + 0.07, 0.04, z1_), (xx - 0.07, 0.04, z1_), WHITE)
            xe = sg * (mw + 2 * lane + 0.15)
            m.quad((xe - 0.07, 0.04, z0_), (xe + 0.07, 0.04, z0_), (xe + 0.07, 0.04, z1_), (xe - 0.07, 0.04, z1_), WHITE)
    # the median barrier of the boulevard continues under the bridge as a concrete island
    for z0_ in range(-170, 170, 2):
        pass
    return None


def render(m, out_dir, views, prefix):
    import pyray as rl
    import road_shot as rs
    pos = np.array(m.P, np.float32)
    col = np.array(m.C, np.uint8)
    pos, col = rs.both_sides(pos, col)
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN | rl.FLAG_MSAA_4X_HINT)
    size = (1400, 900)
    rl.init_window(*size, "scene")
    rt = rl.load_render_texture(*size)
    models = rs.model(pos, col)
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
        rl.export_image(img, os.path.join(out_dir, f"{prefix}_{name}.png"))
        rl.unload_image(img)
    rl.close_window()


def main(out):
    os.makedirs(out, exist_ok=True)
    which = sys.argv[2] if len(sys.argv) > 2 else "all"
    if which in ("all", "round"):
        m = Mesh()
        roundabout(m)
        render(m, out, {"aerial": ((55, 105, -105), (0, 0, 0)), "top": ((0, 170, 1), (0, 0, 0)), "close": ((38, 20, 38), (8, 0, 8)),
                        "driver": ((3.2, 1.7, -88), (0, 1.2, 0))}, "roundabout")
    if which in ("all", "under"):
        m = Mesh()
        underpass_roundabout(m)
        render(m, out, {"aerial": ((70, 90, -150), (0, -2, 0)), "top": ((0, 210, 1), (0, 0, 0)), "portal": ((22, 9, -78), (0, -4, -48)),
                        "driver": ((-4.5, -3.5, -150), (0, -4, -60))}, "underpass")
    if which in ("all", "over"):
        m = Mesh()
        overpass(m)
        render(m, out, {"aerial": ((-95, 55, -140), (0, 0, 0)), "under": ((-6, 1.7, -90), (0, 2.5, 0)), "side": ((0, 8, -80), (40, 4, 0)),
                        "top": ((0, 260, 1), (0, 0, 0))}, "overpass")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "scenes_out")
