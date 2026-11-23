"""Ramp / merge / interchange families built with corridor.py.  Every family takes a parameter dict (all keys optional) and
`sample(family, rnd)` draws a full random parameter set, so every type differs in lane counts, taper / parallel-lane lengths,
ramp curvature, terminal position, flares, grades, medians and control."""
import math
import random

import numpy as np

import corridor as C
from corridor import Plan, Road, branch, seg_pts, hermite_pts, K, widen
from engine import WHITE, YELLOW

EXT = 480.0


def line_pts(x0, y0, x1, y1):
    return np.array([(x0, y0), (x1, y1)])


def carriageway(name, pts, n, lw=3.6, z=0.0, so=3.0, si=1.2, kind="main", prio=0, edge_w=0.2, dens=0.4, lamps=False, speed=100.0):
    r = Road(name, pts, lo=-n * lw / 2, hi=n * lw / 2, z=z, sh_lo=so, sh_hi=si, kind=kind, prio=prio, speed=speed, lamps=lamps)
    r.note.update(n=n, lw=lw)
    r.lines.append(dict(off=lambda s, r=r: r.lo(s) + 0.3, kind="solid", col=WHITE, w=edge_w))
    r.lines.append(dict(off=lambda s, r=r: r.hi(s) - 0.3, kind="solid", col=YELLOW if kind == "main" else WHITE, w=edge_w))
    for i in range(1, n):
        r.lines.append(dict(off=-n * lw / 2 + lw * i, kind="dash", col=WHITE, w=0.15))
    for i in range(n):
        r.cars.append((-n * lw / 2 + lw * (i + 0.5), dens, 0))
    return r


def freeway(n=2, lw=3.6, med=8.0, L=EXT, zk=0.0, so=3.0, si=1.2, lamps=True):
    xc = med / 2 + n * lw / 2
    nb = carriageway("NB", line_pts(xc, -L, xc, L), n, lw, zk, so, si, lamps=lamps)
    sb = carriageway("SB", line_pts(-xc, L, -xc, -L), n, lw, zk, so, si, lamps=lamps)
    nb.barrier_hi = sb.barrier_hi = True
    return nb, sb, xc


def over_z(L, half_flat, ramp_len, H):
    return [(0, 0.0), (L - half_flat - ramp_len, 0.0), (L - half_flat, H), (L + half_flat, H), (L + half_flat + ramp_len, 0.0), (2 * L, 0.0)]


def s_at_y(road, y):
    j = int(np.argmin(np.abs(road.pts[:, 1] - y)))
    return float(road.S[j])


def s_at_x(road, x):
    j = int(np.argmin(np.abs(road.pts[:, 0] - x)))
    return float(road.S[j])


def crossroad(n=2, lw=3.5, med=3.0, L=EXT, z=None, yc=None, so=1.0, si=0.0, med_kind="paint"):
    yc = yc if yc is not None else med / 2 + n * lw / 2
    eb = carriageway("EB", line_pts(-L, -yc, L, -yc), n, lw, z or 0.0, so, si, kind="cross", prio=1, dens=0.35, speed=60)
    wb = carriageway("WB", line_pts(L, yc, -L, yc), n, lw, z or 0.0, so, si, kind="cross", prio=1, dens=0.35, speed=60)
    eb.lines = [l for l in eb.lines if l.get("col") != YELLOW]
    wb.lines = [l for l in wb.lines if l.get("col") != YELLOW]
    for r in (eb, wb):
        r.lines.append(dict(off=lambda s, r=r: r.hi(s) - 0.2, kind="dbl" if med < 1.5 else "solid", col=YELLOW, w=0.12))
    if med >= 1.5 and med_kind != "paint":
        pass
    return eb, wb, yc


def pocket(road, xs, side=1, length=70.0, taper=25.0, w=3.3):
    """Widen the road's median-side edge (left-turn pocket) around position(s) along s."""
    ks = []
    for s0 in xs:
        ks += [(s0 - length - taper, 0.0), (s0 - length, w), (s0, w), (s0 + 4, 0.0)]
    ks.sort()
    base = float(road.hi(0))
    f = K([(s, base + v) for s, v in ks])
    road.hi = f


def add_report(plan, ramps):
    plan.sim = {r.name: C.ramp_report(r) for r in ramps}


# ------------------------------------------------------------------ shared pieces
def frame(p, flat_extra=0.0, xt=None):
    n = p.get("fw_n", 2)
    lw = p.get("fw_lw", 3.6)
    H = p.get("H", 7.0)
    fw_over = p.get("fw_over", False)
    nb, sb, xc = freeway(n, lw, p.get("fw_med", 8.0), zk=K(over_z(EXT, 100, 130, H)) if fw_over else 0.0)
    cn, clw = p.get("c_n", 2), p.get("c_lw", 3.5)
    flat = max(p.get("flat", 0.0), (xt or 0) + 35, 90) + flat_extra
    zc = 0.0 if fw_over else K(over_z(EXT, flat, 130, H))
    eb, wb, yc = crossroad(cn, clw, p.get("c_med", 3.0), z=zc, so=p.get("c_so", 1.0))
    yedge = yc + cn * clw / 2
    xe = xc + n * lw / 2
    return dict(nb=nb, sb=sb, xc=xc, eb=eb, wb=wb, yc=yc, yedge=yedge, xe=xe, H=0.0 if fw_over else H, n=n, lw=lw, cn=cn, clw=clw)


def rot(pts):
    return -np.asarray(pts)


def mirror_plan(plan, frm):
    plan.medians.append((frm["nb"], frm["sb"], "raised"))
    if frm["yc"] > 2.0:
        plan.medians.append((frm["eb"], frm["wb"], "raised"))


def outer_off(f, R, par, ta, tb, nl, rlw, ell, side_sb=False, name="oo", speed=35.0):
    xe, ye, H = f["xe"], f["yedge"], f["H"]
    y0 = -ye - R - par
    pts, _ = seg_pts(xe, y0, math.pi / 2, [("L", par), ("A", math.pi / 2 * R, -R), ("L", ell)])
    L = seg_len(pts)
    if side_sb:
        pts = rot(pts)
    r = C.custom_ramp(name, pts, nl, rlw, -1, ta, tb, 0.0, H, z_rng=(8.0, L - 6.0), speed=speed)
    return r


def outer_on(f, R, par, ta, tb, nl, rlw, lead, side_sb=False, name="on", speed=35.0):
    xe, ye, H = f["xe"], f["yedge"], f["H"]
    pts, _ = seg_pts(xe + R + lead, ye, math.pi, [("L", lead), ("A", math.pi / 2 * R, -R), ("L", par)])
    L = seg_len(pts)
    if side_sb:
        pts = rot(pts)
    return C.custom_ramp(name, pts, nl, rlw, -1, ta, tb, H, 0.0, z_rng=(6.0, L - 8.0), speed=speed)


def loop_off(f, R, par, ta, tb, nl, rlw, ell, side_sb=False, name="lo", speed=40.0):
    xe, ye, H = f["xe"], f["yedge"], f["H"]
    y0 = ye + R - par
    pts, _ = seg_pts(xe, y0, math.pi / 2, [("L", par), ("A", 1.5 * math.pi * R, -R), ("L", ell)])
    L = seg_len(pts)
    if side_sb:
        pts = rot(pts)
    return C.custom_ramp(name, pts, nl, rlw, -1, ta, tb, 0.0, H, z_rng=(par, L), speed=speed)


def loop_on(f, R, par, ta, tb, nl, rlw, ell, side_sb=False, name="ln", speed=40.0):
    xe, ye, H = f["xe"], f["yedge"], f["H"]
    xs = xe + R - par
    pts, _ = seg_pts(xs, -ye, 0.0, [("L", par), ("A", 1.5 * math.pi * R, -R), ("L", ell)])
    L = seg_len(pts)
    if side_sb:
        pts = rot(pts)
    return C.custom_ramp(name, pts, nl, rlw, -1, ta, tb, H, 0.0, z_rng=(0.0, L - ell * 0.5), speed=speed)


def seg_len(pts):
    d = np.diff(pts, axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum())


def finish(plan, ramps, f, p):
    plan.roads = [f["nb"], f["sb"], f["eb"], f["wb"]] + list(ramps) + plan.roads
    mirror_plan(plan, f)
    add_report(plan, ramps)
    return plan


def signals_on_cross(plan, f, xs, state="r"):
    pass


# ------------------------------------------------------------------ diamond / SPUI / tight diamond
def diamond_once(p):
    xt = p.get("xt", 75.0)
    f = frame(p, xt=xt)
    nb, sb = f["nb"], f["sb"]
    ln = p.get("ramp_n", 1)
    rlw = p.get("ramp_lw", 3.8)
    par, taper, dist = p.get("par", 60.0), p.get("taper", 60.0), p.get("dist", 250.0)
    k0, k1 = p.get("k0", 0.6), p.get("k1", 0.6)
    flare = p.get("flare", 3.5)
    spui = p.get("spui", False)
    yedge, H = f["yedge"], f["H"]
    xtt = p.get("spui_x", 26.0) if spui else xt
    ramps = []
    for sgn, fw in ((1, nb), (-1, sb)):
        if sgn > 0:
            s_off, s_on = s_at_y(nb, -(yedge + dist)), s_at_y(nb, yedge + dist)
            oe, os_ = (xtt, -yedge + 0.5, math.pi / 2), (xtt, yedge - 0.5, math.pi / 2)
        else:
            s_off, s_on = s_at_y(sb, yedge + dist), s_at_y(sb, -(yedge + dist))
            oe, os_ = (-xtt, yedge - 0.5, -math.pi / 2), (-xtt, -yedge + 0.5, -math.pi / 2)
        if spui:
            a = math.radians(p.get("spui_angle", 38.0))
            oe = (oe[0], oe[1], oe[2] + sgn * a)
            os_ = (os_[0], os_[1], os_[2] + sgn * a)
        tag = "NB" if sgn > 0 else "SB"
        ramps.append(branch(fw, s_off, "off", oe, side=-1, nl=ln, lw=rlw, par=par, taper=taper, k0=k0, k1=k1, z_end=H, flare=flare,
                            speed=p.get("ramp_speed", 50), name="off_" + tag, curve="hermite" if spui else "auto"))
        ramps.append(branch(fw, s_on, "on", os_, side=-1, nl=ln, lw=rlw, par=par, taper=taper, k0=k0, k1=k1, z_end=H, flare=flare,
                            speed=p.get("ramp_speed", 50), name="on_" + tag, curve="hermite" if spui else "auto"))
    plan = Plan(p.get("name", "diamond"), [], extent=EXT, seed=p.get("seed", 1))
    plan.gantries = [(nb, s_at_y(nb, -(yedge + dist + 140)), 0), (sb, s_at_y(sb, yedge + dist + 140), 0)]
    if p.get("signals", True):
        for r in ramps:
            if r.note["kind"] == "off":
                plan.signals.append((r, r.L - 5.0, "r" if "NB" in r.name else "g"))
                plan.stops.append((r, r.L - 1.0, r.lo(r.L), r.hi(r.L)))
                if p.get("zebra", True):
                    plan.crossings.append((r, r.L - 9.0, r.lo(r.L), r.hi(r.L)))
    return finish(plan, ramps, f, p)


def autofit(builder, p, vary):
    """Simulation-driven fit: rebuild until every ramp meets radius and grade rules (lengthen the ramp, pull terminals in)."""
    log = []
    for it in range(8):
        plan = builder(p)
        bad = [k for k, v in plan.sim.items() if not (v["ok_radius"] and v["ok_grade"])]
        log.append((it, len(bad)))
        if not bad:
            break
        p = vary(dict(p), plan, bad)
    plan.info["fit_log"] = log
    plan.info["params"] = {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool))}
    return plan


def _vary_diamond(p, plan, bad):
    p["dist"] = min(p.get("dist", 250) + 40, 400)
    p["xt"] = max(p.get("xt", 75) * 0.9, 48)
    if any(plan.sim[b]["max_grade_pct"] > 7 for b in bad):
        p["H"] = max(p.get("H", 7.0) - 0.4, 5.6)
    return p


def diamond(p):
    return autofit(diamond_once, p, _vary_diamond)


# ------------------------------------------------------------------ parclo A / B and cloverleaf
def clover_once(p):
    kind = p.get("kind", "clover")      # clover | parclo_a (loops exit after the crossing) | parclo_b (loops enter before)
    Ro = p.get("R_outer", 45.0)
    par = p.get("par", 34.0)
    Rl = p.get("R_loop", Ro + par + 40.0)
    xt = 2 * Rl + 40
    f = frame(p, xt=xt)
    ramps = []
    rl = p.get("ramp_lw", 3.8)
    ln = p.get("ramp_n", 1)
    ta, tb = p.get("taper_a", 60.0), p.get("taper_b", 60.0)
    has_lo = kind in ("clover", "parclo_a")
    has_ln = kind in ("clover", "parclo_b")
    aux = max(10.0, Rl - par - Ro + 10.0)
    for sb_ in (False, True):
        tag = "SB" if sb_ else "NB"
        ramps.append(outer_off(f, Ro, par, 0.0 if has_ln else ta, tb, ln, rl, p.get("ell", 70.0), sb_, "oo_" + tag))
        ramps.append(outer_on(f, Ro, aux if has_lo else 70.0, tb, 0.0 if has_lo else p.get("taper_on", 80.0), ln, rl, p.get("lead", 60.0), sb_, "on_" + tag))
        if has_lo:
            ramps.append(loop_off(f, Rl, par, 0.0, tb, p.get("loop_n", 1), rl, p.get("ell_l", 14.0), sb_, "lo_" + tag))
        if has_ln:
            ramps.append(loop_on(f, Rl, par, ta, 0.0 if True else 60.0, p.get("loop_n", 1), rl, aux, sb_, "ln_" + tag))
    plan = Plan(p.get("name", kind), [], extent=EXT, seed=p.get("seed", 1))
    return finish(plan, ramps, f, p)


def _vary_clover(p, plan, bad):
    p["ell"] = p.get("ell", 70.0) + 20
    p["lead"] = p.get("lead", 60.0) + 20
    if any(plan.sim[b]["max_grade_pct"] > 7 for b in bad):
        p["H"] = max(p.get("H", 7.0) - 0.3, 5.6)
    p["R_loop"] = min(p.get("R_loop", 100.0) + 8, 130)
    return p


def clover(p):
    return autofit(clover_once, p, _vary_clover)



def two_way(name, pts, n, lw=3.4, z=0.0, prio=1, speed=50.0):
    r = Road(name, pts, lo=-n * lw, hi=n * lw, z=z, sh_lo=1.0, sh_hi=1.0, kind="cross", prio=prio, speed=speed)
    r.lines.append(dict(off=lambda s, r=r: r.lo(s) + 0.3, kind="solid", col=WHITE))
    r.lines.append(dict(off=lambda s, r=r: r.hi(s) - 0.3, kind="solid", col=WHITE))
    r.lines.append(dict(off=0.0, kind="dbl", col=YELLOW, w=0.12))
    for i in range(1, n):
        r.lines.append(dict(off=-lw * i, kind="dash", col=WHITE))
        r.lines.append(dict(off=lw * i, kind="dash", col=WHITE))
    for i in range(n):
        r.cars.append((-lw * (i + 0.5), 0.3, 0))
        r.cars.append((lw * (i + 0.5), 0.3, 1))
    return r


# ------------------------------------------------------------------ merge / diverge families on a straight freeway
def merge_scene(p):
    kind = p["kind"]
    n = p.get("fw_n", 3)
    lw = p.get("fw_lw", 3.6)
    LM = 620.0
    nb, sb, xc = freeway(n, lw, p.get("fw_med", 8.0), L=LM)
    xe = xc + n * lw / 2
    nl = p.get("nl", 1)
    rlw = p.get("ramp_lw", 3.8)
    par, taper = p.get("par", 120.0), p.get("taper", 80.0)
    dx, dy = p.get("dx", 70.0), p.get("dy", 300.0)
    dy = max(dy, par + max(taper, p.get("merge_taper", 100.0)) + 180.0 + abs(p.get("y_m", 0.0)), p.get("gap", 0.0) * 0.95 + 190.0)
    roads, plan_extra = [], []
    ramps = []
    s0 = LM                                           # event position along the freeway (y = 0)
    mt = p.get("merge_taper", 100.0)
    spd = p.get("ramp_speed", 60.0)

    def surf(y, xr, up=True):
        """Surface street crossing the ramp end."""
        pts = line_pts(xr - 140, y, xr + 140, y)
        return two_way("surf%.0f" % y, pts, p.get("surf_n", 1), 3.4)

    if kind in ("on_par", "on_taper", "on_laneadd", "on_laneadd_keep", "on_meter", "on_2lane"):
        par_ = 0.0 if kind == "on_taper" else par
        endp = (xe + dx, -dy, math.pi / 2)
        mtp = 0.0 if kind in ("on_laneadd", "on_laneadd_keep") else mt
        r = branch(nb, s0 + p.get("y_m", 0.0), "on", endp, side=-1, nl=nl, lw=rlw, par=par_, taper=taper, merge_taper=mtp, k0=0.6, k1=0.6, z_end=0.0,
                   flare=p.get("flare", 0.0), speed=spd, name="on")
        ramps.append(r)
        if kind == "on_laneadd":
            widen(nb, -1, s0 - par_ + p.get("y_m", 0.0), s0 + p.get("y_m", 0.0) + p.get("add_len", 300.0), rlw * nl if False else lw, 15.0, 90.0)
        if kind == "on_laneadd_keep":
            widen(nb, -1, s0 - par_ + p.get("y_m", 0.0), 5000.0, lw, 15.0, 90.0)
            nb.lines.append(dict(off=-n * lw / 2, kind="dash", col=WHITE, rng=(s0 + p.get("y_m", 0.0), 5000.0)))
        roads.append(surf(-dy - 8, xe + dx))
    elif kind in ("off_par", "off_taper", "off_2lane", "off_lanedrop", "off_option"):
        par_ = 0.0 if kind == "off_taper" else par
        endp = (xe + dx, dy, math.pi / 2)
        tp = 1.0 if kind in ("off_lanedrop", "off_option") else taper
        r = branch(nb, s0 + p.get("y_m", 0.0), "off", endp, side=-1, nl=nl, lw=rlw, par=par_, taper=tp, k0=0.6, k1=0.6, z_end=0.0,
                   flare=p.get("flare", 0.0), speed=spd, name="off")
        ramps.append(r)
        if kind in ("off_lanedrop", "off_option"):
            widen(nb, -1, s0 + p.get("y_m", 0.0) + par_ * 0.0 + 5, 9000.0, -(lw if kind == "off_lanedrop" else 0.0), 60.0, 1.0)
            if kind == "off_option":
                nb.lines.append(dict(off=-n * lw / 2 + lw, kind="solid", col=WHITE, rng=(s0 - 60, s0 + 40)))
        roads.append(surf(dy + 8, xe + dx))
        plan_extra.append((nb, s0 - 150))
    elif kind == "weave":
        gap = p.get("gap", 260.0)
        aux = lw
        on = branch(nb, s0 - gap / 2, "on", (xe + dx, -dy, math.pi / 2), side=-1, nl=1, lw=rlw, par=gap * 0.4, taper=taper, merge_taper=0.0, k0=0.6, k1=0.6, z_end=0.0, speed=spd, name="on")
        off = branch(nb, s0 + gap / 2, "off", (xe + dx, dy, math.pi / 2), side=-1, nl=1, lw=rlw, par=gap * 0.4, taper=0.0 + 1.0, k0=0.6, k1=0.6, z_end=0.0, speed=spd, name="off")
        widen(nb, -1, s0 - gap / 2 - 5, s0 + gap / 2 + 5, lw, 20.0, 20.0)
        ramps += [on, off]
        roads += [surf(-dy - 8, xe + dx), surf(dy + 8, xe + dx)]
    elif kind == "cd":
        gap = p.get("cd_gap", 18.0)
        ncd = p.get("nl", 2)
        y0, y1 = -p.get("cd_len", 340.0) / 2, p.get("cd_len", 340.0) / 2
        xcd = xe + gap
        cd = C.custom_ramp("CD", line_pts(xcd, y0, xcd, y1), ncd, rlw, -1, 0.0, 0.0, 0.0, 0.0, speed=70.0)
        cd.pts = C.resample(line_pts(xcd, y0, xcd, y1), 2.0)
        cd = Road("CD", line_pts(xcd, y0, xcd, y1), kind="ramp", speed=70.0, prio=2)
        cd.lo, cd.hi = K(-ncd * rlw), K(0.0)
        cd.sh_lo = K(1.5)
        cd.lines.append(dict(off=lambda s: cd.lo(s) + 0.25, kind="solid", col=WHITE))
        for i in range(1, ncd):
            cd.lines.append(dict(off=-rlw * i, kind="dash", col=WHITE))
        for i in range(ncd):
            cd.cars.append((-rlw * (i + 0.5), 0.4, 0))
        d_in = branch(nb, s0 + y0 - 120, "off", (xcd, y0 + 0.0, math.pi / 2), side=-1, nl=ncd, lw=rlw, par=40.0, taper=70.0, k0=0.6, k1=0.6, speed=40.0, name="cd_in")
        d_out = branch(nb, s0 + y1 + 140, "on", (xcd, y1 - 0.0, math.pi / 2), side=-1, nl=ncd, lw=rlw, par=40.0, taper=70.0, merge_taper=90.0, k0=0.6, k1=0.6, speed=40.0, name="cd_out")
        x1 = branch(cd, cd.L * 0.45, "off", (xcd + dx, y1 + 120, math.pi / 2), side=-1, nl=1, lw=rlw, par=30.0, taper=50.0, k0=0.6, k1=0.6, speed=50.0, name="cd_exit")
        e1 = branch(cd, cd.L * 0.2, "on", (xcd + dx, y0 - 140, math.pi / 2), side=-1, nl=1, lw=rlw, par=30.0, taper=50.0, merge_taper=60.0, k0=0.6, k1=0.6, speed=50.0, name="cd_entry")
        ramps += [cd, d_in, d_out, x1, e1]
        roads += [surf(y1 + 128, xcd + dx), surf(y0 - 148, xcd + dx)]
    elif kind in ("fork", "join"):
        n2 = p.get("n2", 1)
        yf = 0.0
        far = (xe + p.get("fork_dx", 90.0), 420.0, math.pi / 2) if kind == "fork" else (xe + p.get("fork_dx", 90.0), -420.0, math.pi / 2)
        if kind == "fork":
            r = branch(nb, s0, "off", far, side=-1, nl=n2, lw=lw, par=0.0, taper=1.0, k0=0.5, k1=0.5, speed=80.0, name="fork", curve="quintic")
            widen(nb, -1, s0 + 2, 9000.0, -n2 * lw, p.get("taper", 120.0), 1.0)
            r.sh_lo = K(3.0)
        else:
            r = branch(nb, s0, "on", far, side=-1, nl=n2, lw=lw, par=0.0, taper=1.0, merge_taper=0.0, k0=0.5, k1=0.5, speed=80.0, name="join", curve="quintic")
            widen(nb, -1, s0 - 4, 9000.0, n2 * lw, 4.0, 1.0)
            widen(nb, -1, -1.0, s0 - 4, 0.0, 1.0, 1.0)
            r.sh_lo = K(3.0)
        ramps.append(r)
    elif kind in ("meter",):
        pass
    plan = Plan(p.get("name", kind), [], extent=LM, seed=p.get("seed", 1))
    plan.roads = [nb, sb] + ramps + roads
    plan.medians.append((nb, sb, "raised"))
    for rr in ramps:
        if p.get("meter") and rr.note.get("kind") in ("on",):
            plan.stops.append((rr, rr.L * 0.5, rr.lo(rr.L * 0.5), rr.hi(rr.L * 0.5)))
            plan.signals.append((rr, rr.L * 0.5 - 4, "r"))
    for road, s in plan_extra:
        plan.gantries.append((road, s, 0))
    # opposite carriageway mirror: same event rotated 180 degrees about the origin (for visual balance)
    add_report(plan, [r for r in ramps if r.note.get("kind") in ("on", "off")])
    plan.info["params"] = {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool))}
    plan.info["focus"] = (xe + dx * 0.3, 0.0, 200.0)
    return plan


# ------------------------------------------------------------------ DDI, roundabout interchange, trumpet
def ddi(p):
    p = dict(p)
    xt = p.get("xt", 90.0)
    f = frame(p, xt=xt)
    nb, sb, yc, yedge, H = f["nb"], f["sb"], f["yc"], f["yedge"], f["H"]
    cn, clw = f["cn"], f["clw"]
    xcr = xt - p.get("cross_in", 28.0)             # crossover position
    sh = p.get("shift", 70.0)
    ramps = []
    # replace the straight crossroad by crossing carriageways
    def cross_pts(sgn):
        # sgn=+1: eastbound, starts south (-yc) and crosses to the north between -xcr..xcr
        a = line_pts(-EXT, -sgn * yc, -xcr - sh, -sgn * yc)
        b = C.shift_pts((-xcr - sh, -sgn * yc), 0.0, (-xcr + 0.0, sgn * yc), 40, 3)
        c = line_pts(-xcr, sgn * yc, xcr, sgn * yc)
        d = C.shift_pts((xcr, sgn * yc), 0.0, (xcr + sh, -sgn * yc), 40, 3)
        e = line_pts(xcr + sh, -sgn * yc, EXT, -sgn * yc)
        pts = np.vstack([a, b, c, d, e])
        return pts if sgn > 0 else pts[::-1] * np.array([1, 1])
    zc = K(over_z(EXT, xcr + sh + 20, 130, H)) if not p.get("fw_over") else 0.0
    eb = carriageway("EB", cross_pts(1), cn, clw, zc, 1.0, 0.0, kind="cross", prio=1, dens=0.35, speed=60)
    # WB: same shape rotated 180 degrees
    wb = carriageway("WB", -cross_pts(1), cn, clw, zc, 1.0, 0.0, kind="cross", prio=1, dens=0.35, speed=60)
    for rd in (eb, wb):
        rd.lines = [l for l in rd.lines if l.get("col") != YELLOW]
    dist = p.get("dist", 260.0)
    ln = p.get("ramp_n", 1)
    rlw = p.get("ramp_lw", 3.8)
    par, taper = p.get("par", 60.0), p.get("taper", 60.0)
    for sgn, fw in ((1, nb), (-1, sb)):
        if sgn > 0:
            s_off, s_on = s_at_y(nb, -(yedge + dist)), s_at_y(nb, yedge + dist)
            oe, os_ = (xt, -yedge + 0.5, math.pi / 2), (xt, yedge - 0.5, math.pi / 2)
        else:
            s_off, s_on = s_at_y(sb, yedge + dist), s_at_y(sb, -(yedge + dist))
            oe, os_ = (-xt, yedge - 0.5, -math.pi / 2), (-xt, -yedge + 0.5, -math.pi / 2)
        tag = "NB" if sgn > 0 else "SB"
        ramps.append(branch(fw, s_off, "off", oe, side=-1, nl=ln, lw=rlw, par=par, taper=taper, k0=0.6, k1=0.6, z_end=f["H"], flare=p.get("flare", 3.5), speed=50, name="off_" + tag))
        ramps.append(branch(fw, s_on, "on", os_, side=-1, nl=ln, lw=rlw, par=par, taper=taper, k0=0.6, k1=0.6, z_end=f["H"], flare=p.get("flare", 3.5), speed=50, name="on_" + tag))
    plan = Plan(p.get("name", "ddi"), [nb, sb, eb, wb] + ramps, extent=EXT, seed=p.get("seed", 1))
    plan.medians.append((nb, sb, "raised"))
    for sgn in (1, -1):
        for rd, xs in ((eb, sgn * xcr), (wb, -sgn * xcr)):
            pass
    plan.info["params"] = {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool))}
    add_report(plan, ramps)
    return plan


def rbt_interchange(p):
    p = dict(p)
    xr = p.get("xr", 105.0)
    R = p.get("R", 38.0)
    f = frame(p, xt=xr + R)
    nb, sb, H = f["nb"], f["sb"], f["H"]
    n_ring = p.get("ring_n", 2)
    wr = n_ring * 4.2
    cn = p.get("c_n", 2)
    clw = p.get("c_lw", 3.4)
    ramps, roads = [], []
    ang = np.linspace(0, 2 * math.pi, 120)
    rings = []
    for sg in (1, -1):
        cx = sg * xr
        pts = np.stack([cx + (R + wr / 2) * np.cos(ang + math.pi), (R + wr / 2) * np.sin(ang + math.pi)], 1)
        ring = Road("ring%d" % sg, pts, lo=-wr / 2, hi=wr / 2, z=H, sh_lo=1.0, sh_hi=0.0, kind="cross", prio=1, speed=40)
        ring.lines.append(dict(off=-wr / 2 + 0.3, kind="solid", col=WHITE))
        ring.lines.append(dict(off=wr / 2 - 0.3, kind="solid", col=WHITE))
        if n_ring > 1:
            ring.lines.append(dict(off=0.0, kind="dash", col=WHITE))
        for i in range(n_ring):
            ring.cars.append((-wr / 2 + 4.2 * (i + 0.5), 0.12, 0))
        ring.rail_hi = True
        roads.append(ring)
        rings.append((cx, 0.0, R - wr / 2 + 0.0, H, "trees"))
    # radial legs
    legs = []
    xo = R + wr + 0.0
    legs.append(two_way("leg_w", line_pts(-EXT, 0, -xr - R - wr + 1.0, 0), cn, clw, K([(0, 0.0), (EXT - xr - R - wr - 140.0, 0.0), (EXT - xr - R - wr, H)]), 1))
    legs.append(two_way("leg_e", line_pts(xr + R + wr - 1.0, 0, EXT, 0), cn, clw, K([(0, H), (140.0, 0.0), (EXT, 0.0)]), 1))
    legs.append(two_way("leg_mid", line_pts(-xr + R + wr - 1.0, 0, xr - R - wr + 1.0, 0), cn, clw, H, 1))
    roads += legs
    ye = f["xe"]
    dist = p.get("dist", 250.0)
    ln = p.get("ramp_n", 1)
    rlw = p.get("ramp_lw", 3.8)
    for sgn, fw in ((1, nb), (-1, sb)):
        cx = sgn * xr
        if sgn > 0:
            s_off, s_on = s_at_y(nb, -dist), s_at_y(nb, dist)
            oe, os_ = (cx, -(R + wr) + 0.5, math.pi / 2), (cx, (R + wr) - 0.5, math.pi / 2)
        else:
            s_off, s_on = s_at_y(sb, dist), s_at_y(sb, -dist)
            oe, os_ = (cx, (R + wr) - 0.5, -math.pi / 2), (cx, -(R + wr) + 0.5, -math.pi / 2)
        tag = "NB" if sgn > 0 else "SB"
        ramps.append(branch(fw, s_off, "off", oe, side=-1, nl=ln, lw=rlw, par=p.get("par", 60.0), taper=p.get("taper", 60.0), k0=0.6, k1=0.6, z_end=H, speed=40, name="off_" + tag))
        ramps.append(branch(fw, s_on, "on", os_, side=-1, nl=ln, lw=rlw, par=p.get("par", 60.0), taper=p.get("taper", 60.0), k0=0.6, k1=0.6, z_end=H, speed=40, name="on_" + tag))
    plan = Plan(p.get("name", "rbt_ic"), [nb, sb] + roads + ramps, extent=EXT, seed=p.get("seed", 1))
    plan.rings = rings
    plan.medians.append((nb, sb, "raised"))
    plan.info["params"] = {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool))}
    add_report(plan, ramps)
    return plan


def trumpet(p):
    """Through freeway E-W, terminating road from the south.  The S road splits into the right-turn merge (S->EB), the exit
    ramp (EB->S) and the loop with flyover (WB->S)."""
    p = dict(p)
    n = p.get("fw_n", 2)
    lw = p.get("fw_lw", 3.6)
    med = p.get("fw_med", 8.0)
    H = p.get("H", 7.0)
    yc = med / 2 + n * lw / 2
    ye = yc + n * lw / 2
    eb = carriageway("EB", line_pts(-EXT, -yc, EXT, -yc), n, lw, 0.0, 3.0, 1.2)
    wb = carriageway("WB", line_pts(EXT, yc, -EXT, yc), n, lw, 0.0, 3.0, 1.2)
    eb.barrier_hi = wb.barrier_hi = True
    tn = p.get("t_n", 1)
    tlw = p.get("t_lw", 3.6)
    rlw = tlw
    R = p.get("R", 85.0)
    Rl = p.get("R_loop", 70.0)
    par = p.get("par", 70.0)
    ta, tb = p.get("taper_a", 70.0), p.get("taper_b", 90.0)
    y0 = -ye - R
    sroad = two_way("S_road", line_pts(0.0, -EXT, 0.0, y0 + 2.0), tn, tlw, 0.0, 1)
    # S -> EB (right turn, merges on the south edge of EB)
    pa, _ = seg_pts(0.0, y0, math.pi / 2, [("A", math.pi / 2 * R, -R), ("L", p.get("ell", 140.0))])
    r_a = C.custom_ramp("S_to_EB", pa, tn, rlw, -1, 0.0, tb, 0.0, 0.0, speed=50.0)
    # EB -> S (exit, right turn onto the S road's southbound side)
    pb, _ = seg_pts(-par - R, -ye, 0.0, [("L", par), ("A", math.pi / 2 * R, -R)])
    r_b = C.custom_ramp("EB_to_S", pb, tn, rlw, -1, ta, 0.0, 0.0, 0.0, speed=50.0)
    # WB -> S loop: exits right (north side), 270 deg loop, flyover across the freeway, lands on the S road
    xa = par - Rl
    pc, _ = seg_pts(xa, ye, math.pi, [("L", par), ("A", 1.5 * math.pi * Rl, -Rl), ("L", 2 * ye + Rl + R)])
    r_c = C.custom_ramp("WB_to_S_loop", pc, tn, rlw, -1, ta, 0.0, 0.0, 0.0, speed=40.0)
    Lc = r_c.L
    r_c.z = K([(0, 0.0), (par + 20, 0.0), (par + 20 + H / 0.045, H), (Lc - 60 - H / 0.045, H), (Lc - 8, 0.0)])
    ramps = [r_a, r_b, r_c]
    roads = [eb, wb, sroad] + ramps
    plan = Plan(p.get("name", "trumpet"), roads, extent=EXT, seed=p.get("seed", 1))
    plan.medians.append((eb, wb, "raised"))
    plan.info["params"] = {k: v for k, v in p.items() if isinstance(v, (int, float, str, bool))}
    plan.info["focus"] = (0.0, 0.0, 380.0)
    add_report(plan, ramps)
    return plan


def _vary_generic(p, plan, bad):
    """Simulation-driven repair: lengthen / flatten whatever geometry the failing ramps depend on."""
    if "dy" in p or p.get("kind") in MERGE_KINDS:
        p["dy"] = min(p.get("dy", 300.0) + 60, 560)
        p["dx"] = max(p.get("dx", 70.0) * 0.88, 30.0)
        if "gap" in p:
            p["gap"] = p["gap"] + 20
        if p.get("fork_dx"):
            p["fork_dx"] = max(p["fork_dx"] * 0.85, 40.0)
        if p.get("cd_gap"):
            p["cd_len"] = p.get("cd_len", 340.0) + 60
    if "xr" in p:
        p["dist"] = min(p.get("dist", 250.0) + 40, 420)
        p["xr"] = max(p["xr"] * 0.92, 70.0)
        p["R"] = p.get("R", 38.0) + 3
    if "R_loop" in p and "xr" not in p and "kind" not in p:
        p["R_loop"] = p["R_loop"] + 10
        p["R"] = p.get("R", 85.0) + 10
    if "shift" in p:
        p["dist"] = min(p.get("dist", 260.0) + 40, 420)
        p["xt"] = max(p.get("xt", 100.0) * 0.95, 70.0)
        p["shift"] = max(p["shift"] * 0.9, 40.0)
    return p


def fitted(builder):
    return lambda p: autofit(builder, p, _vary_generic)


def _vary_spui(p, plan, bad):
    p["spui_angle"] = max(p.get("spui_angle", 38.0) - 4, 15.0)
    return _vary_diamond(p, plan, bad)


def spui(p):
    p = dict(p, ramp_speed=min(p.get("ramp_speed", 40), 40))
    return autofit(diamond_once, p, _vary_spui)


FAMS = {"diamond": diamond, "spui": diamond, "tight_diamond": diamond, "clover": clover, "parclo_a": clover, "parclo_b": clover,
        "ddi": fitted(ddi), "rbt_ic": fitted(rbt_interchange), "trumpet": fitted(trumpet)}
FAMS["spui"] = spui
MERGE_KINDS = ["on_par", "on_taper", "on_laneadd", "on_laneadd_keep", "on_meter", "on_2lane", "off_par", "off_taper", "off_2lane", "off_lanedrop",
               "off_option", "weave", "cd", "fork", "join"]
for _k in MERGE_KINDS:
    FAMS["m_" + _k] = fitted(merge_scene)
DIST = {"m_": 250, "diamond": 330, "spui": 330, "tight_diamond": 300, "clover": 430, "parclo_a": 430, "parclo_b": 430, "ddi": 330, "rbt_ic": 330, "trumpet": 360}


def build_family(fam, p):
    if fam.startswith("m_"):
        p = dict(p, kind=fam[2:])
    return FAMS[fam](p)


def sample(fam, rnd):
    if fam == "diamond":
        d = dict(fw_n=rnd.choice([2, 2, 3, 4]), fw_lw=rnd.choice([3.5, 3.6, 3.75]), fw_med=rnd.choice([4.0, 8.0, 12.0, 18.0]),
                 c_n=rnd.choice([1, 2, 2, 3]), c_lw=rnd.choice([3.25, 3.5, 3.75]), H=rnd.choice([6.2, 7.0, 7.8]),
                 xt=rnd.choice([60, 75, 90, 110, 130]), ramp_n=rnd.choice([1, 1, 2]), ramp_lw=rnd.choice([3.5, 3.8, 4.2]),
                 par=rnd.choice([30, 60, 90, 120]), taper=rnd.choice([40, 60, 80, 100]), dist=rnd.choice([210, 250, 290, 330]),
                 k0=rnd.choice([0.5, 0.6, 0.75]), k1=rnd.choice([0.5, 0.6, 0.75]), flare=rnd.choice([0.0, 3.5, 7.0]),
                 c_med=rnd.choice([0.5, 3.0, 6.0]), fw_over=rnd.random() < 0.15, ramp_speed=rnd.choice([40, 50, 60]))
        return d
    if fam in ("clover", "parclo_a", "parclo_b"):
        return dict(kind=fam, fw_n=rnd.choice([2, 3, 4]), fw_lw=rnd.choice([3.5, 3.6, 3.75]), fw_med=rnd.choice([4.0, 8.0, 12.0]),
                    c_n=rnd.choice([1, 2, 2, 3]), c_lw=rnd.choice([3.25, 3.5, 3.75]), H=rnd.choice([6.2, 7.0, 7.8]),
                    R_outer=rnd.choice([42, 48, 55]), R_loop=rnd.choice([85, 95, 105, 118]), ramp_n=rnd.choice([1, 1, 2]), ramp_lw=rnd.choice([3.6, 3.8, 4.2]),
                    par=rnd.choice([26, 34, 42]), taper_a=rnd.choice([50, 60, 80]), taper_b=rnd.choice([40, 60, 80]), c_med=rnd.choice([0.5, 3.0, 6.0]),
                    fw_over=rnd.random() < 0.1)
    if fam in ("spui", "tight_diamond"):
        d = sample("diamond", rnd)
        if fam == "spui":
            d.update(spui=True, spui_x=rnd.choice([20, 26, 32]), spui_angle=rnd.choice([30, 38, 45]), c_n=rnd.choice([2, 3]), dist=rnd.choice([250, 290, 330]))
        else:
            d.update(xt=rnd.choice([42, 48, 55]), taper=rnd.choice([40, 50]), par=rnd.choice([20, 40]), dist=rnd.choice([250, 290]))
        return d
    if fam == "ddi":
        return dict(fw_n=rnd.choice([2, 3]), fw_med=rnd.choice([6.0, 10.0, 14.0]), c_n=rnd.choice([1, 2, 2]), c_lw=rnd.choice([3.4, 3.5, 3.75]),
                    H=rnd.choice([6.2, 7.0]), xt=rnd.choice([95, 110, 125]), shift=rnd.choice([55, 70, 85]), cross_in=rnd.choice([22, 28, 36]), ramp_n=rnd.choice([1, 2]),
                    dist=rnd.choice([260, 300, 340]), par=rnd.choice([40, 70]), taper=rnd.choice([50, 70]), flare=rnd.choice([0.0, 3.5]))
    if fam == "rbt_ic":
        return dict(fw_n=rnd.choice([2, 3]), fw_med=rnd.choice([6.0, 10.0]), H=rnd.choice([6.2, 7.0]), xr=rnd.choice([100, 120, 140]), R=rnd.choice([30, 36, 44]),
                    ring_n=rnd.choice([1, 2, 2]), c_n=rnd.choice([1, 2]), c_lw=rnd.choice([3.4, 3.6]), dist=rnd.choice([220, 260, 300]), ramp_n=rnd.choice([1, 1, 2]),
                    par=rnd.choice([40, 60, 90]), taper=rnd.choice([50, 70]))
    if fam == "trumpet":
        return dict(fw_n=rnd.choice([2, 3]), fw_med=rnd.choice([6.0, 10.0]), H=rnd.choice([6.2, 7.0]), R=rnd.choice([70, 85, 100]), R_loop=rnd.choice([60, 70, 85]), t_n=rnd.choice([1, 2]), par=rnd.choice([50, 70, 90]), ell=rnd.choice([100, 140, 180]))
    if fam.startswith("m_"):
        k = fam[2:]
        d = dict(fw_n=rnd.choice([2, 3, 4]), fw_lw=rnd.choice([3.5, 3.6, 3.75]), fw_med=rnd.choice([4.0, 8.0, 12.0]), nl=rnd.choice([1, 1, 2]), ramp_lw=rnd.choice([3.6, 3.8, 4.2]),
                 par=rnd.choice([60, 100, 150, 220]), taper=rnd.choice([60, 80, 100, 140]), merge_taper=rnd.choice([70, 100, 140, 180]),
                 dx=rnd.choice([70, 100, 130, 170]), dy=rnd.choice([240, 300, 360]), ramp_speed=rnd.choice([40, 50, 60]), surf_n=rnd.choice([1, 2]),
                 flare=rnd.choice([0.0, 3.0]), add_len=rnd.choice([200, 320, 480]), y_m=rnd.choice([-60.0, 0.0, 60.0]), meter=(k == "on_meter"))
        if k == "on_2lane":
            d["nl"] = 2
        if k == "weave":
            d.update(gap=rnd.choice([220, 280, 340]), nl=1)
        if k == "cd":
            d.update(cd_gap=rnd.choice([14.0, 20.0, 28.0]), cd_len=rnd.choice([320, 420, 520]), nl=rnd.choice([1, 2]), dx=rnd.choice([50, 80]))
        if k in ("fork", "join"):
            d.update(n2=rnd.choice([1, 2]), fork_dx=rnd.choice([70, 100, 140]), taper=rnd.choice([100, 140, 200]), fw_n=rnd.choice([3, 4]))
        return d
    raise KeyError(fam)