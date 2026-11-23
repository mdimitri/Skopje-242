"""Corridor engine for ramps, merges, diverges and interchanges.  Every road is a reference path (plan x, y, heading) with
asphalt edges lo(s)/hi(s) (lateral offsets, left positive), shoulders, a vertical profile z(s), paint lines and cars.
Ramps hang off a parent road with `branch()` (taper + parallel lane + Hermite curve) so tapers, parallel lanes, radii and
gradients are all parameters.  Rules: AASHTO Green Book ch.10 / TxDOT RDM 3-3 (taper 50:1..., decel lengths), min radius
R = V^2 / (127 (e + f)).  Plan (x, y) -> world (x, height, y); traffic drives on the right (lateral offset < 0)."""
import math
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from engine import ASPH, ASPH2, CAR_COLS, CONC, GRASS_D, GROUND, HEAD, POLE, WHITE, YELLOW, lamp, signal_head, tree
from mesh import Mesh

OV = {}          # per-element overrides: {"off_NB": {"nl": 2, "R": 40, ...}, "NB": {"n": 3}, ...}
REG = {}         # every (element, key) the builder consulted, with its default value = the live tunable schema
USED = set()


def reset_ov(ov):
    global OV
    OV = ov or {}
    REG.clear()
    USED.clear()


def g(name, key, default):
    """Tunable lookup: the override for (name, key) when given, else the default; every lookup is recorded."""
    REG[(name, key)] = default
    o = OV.get(name)
    if o is not None and key in o:
        USED.add((name, key))
        return o[key]
    return default


SHOULDER = (96, 98, 102)
GUARD = (170, 174, 178)
PARAPET = (196, 194, 188)
FASCIA = (172, 170, 164)
GREEN_SIGN = (30, 110, 70)
ASPH_DARK = tuple(int(v * 0.66) for v in ASPH)


# ---------------------------------------------------------------- knots / paths
def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def lin_ease(t, e=0.1):
    t = max(0.0, min(1.0, t))
    if t < e:
        return t * t / (2 * e * (1 - e))
    if t > 1 - e:
        return 1 - (1 - t) ** 2 / (2 * e * (1 - e))
    return (t - e / 2) / (1 - e)


class K:
    """Smooth piecewise function of s from knots [(s, v), ...] (smoothstep between knots) or a constant."""

    def __init__(self, v):
        self.k = None if isinstance(v, (int, float)) else sorted(v)
        self.c = v if self.k is None else 0.0

    def __call__(self, s):
        if self.k is None:
            return self.c
        k = self.k
        if s <= k[0][0]:
            return k[0][1]
        if s >= k[-1][0]:
            return k[-1][1]
        for (s0, v0), (s1, v1) in zip(k, k[1:]):
            if s0 <= s <= s1:
                if s1 - s0 < 1e-9:
                    return v1
                return v0 + (v1 - v0) * smooth((s - s0) / (s1 - s0))
        return k[-1][1]


def resample(pts, ds=2.0):
    pts = np.asarray(pts, float)
    d = np.hypot(*np.diff(pts, axis=0).T)
    keep = np.concatenate([[True], d > 1e-6])
    pts = pts[keep]
    d = np.hypot(*np.diff(pts, axis=0).T)
    s = np.concatenate([[0], np.cumsum(d)])
    n = max(2, int(round(s[-1] / ds)) + 1)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], 1)


def seg_pts(x, y, h, segs, step=0.5):
    """Path from segments ('L', length) and ('A', length, signed radius; + = left turn).  Returns points and end pose."""
    pts = [(x, y)]
    for sg in segs:
        if sg[0] == "L":
            n = max(1, int(sg[1] / step))
            for i in range(1, n + 1):
                pts.append((x + math.cos(h) * sg[1] * i / n, y + math.sin(h) * sg[1] * i / n))
            x, y = pts[-1]
        else:
            L, R = sg[1], sg[2]
            n = max(2, int(L / step))
            cx, cy = x - math.sin(h) * R, y + math.cos(h) * R
            a0 = math.atan2(y - cy, x - cx)
            dth = L / R
            for i in range(1, n + 1):
                a = a0 + dth * i / n
                pts.append((cx + abs(R) * math.cos(a) * (1 if R > 0 else 1), cy + abs(R) * math.sin(a)))
            x, y = pts[-1]
            h += dth
    return np.array(pts), (x, y, h)


def hermite_pts(p0, h0, p1, h1, k0=1.0, k1=1.0, n=120):
    d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    m0 = np.array([math.cos(h0), math.sin(h0)]) * d * k0
    m1 = np.array([math.cos(h1), math.sin(h1)]) * d * k1
    p0, p1 = np.array(p0, float), np.array(p1, float)
    t = np.linspace(0, 1, n)[:, None]
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def shift_pts(p0, h0, p1, n=140, power=5):
    """Lateral transition between two parallel poses: v = dv * smootherstep(u/du) (zero curvature at both ends)."""
    ux, uy = math.cos(h0), math.sin(h0)
    vx, vy = -uy, ux
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    du, dv = dx * ux + dy * uy, dx * vx + dy * vy
    t = np.linspace(0, 1, n)
    if power == 5:
        f = t ** 3 * (t * (6 * t - 15) + 10)
    elif power == 3:
        f = t * t * (3 - 2 * t)
    else:
        f = 0.5 - 0.5 * np.cos(math.pi * t)
    u = du * t
    v = dv * f
    return np.stack([p0[0] + ux * u + vx * v, p0[1] + uy * u + vy * v], 1)


@dataclass
class Road:
    name: str
    pts: np.ndarray
    lo: object = -7.2
    hi: object = 0.0
    z: object = 0.0
    sh_lo: object = 0.0
    sh_hi: object = 0.0
    lines: list = field(default_factory=list)
    cars: list = field(default_factory=list)            # (lateral offset, density)
    prio: int = 0
    rail_lo: bool = False
    rail_hi: bool = False
    barrier_hi: bool = False
    lamps: bool = False
    kind: str = "ramp"
    speed: float = 50.0
    col: tuple = ASPH
    note: dict = field(default_factory=dict)

    def __post_init__(self):
        self.pts = resample(self.pts, 2.0)
        d = np.diff(self.pts, axis=0)
        self.S = np.concatenate([[0], np.cumsum(np.hypot(d[:, 0], d[:, 1]))])
        hh = np.arctan2(d[:, 1], d[:, 0])
        self.Hd = np.concatenate([hh, hh[-1:]])
        self.Hd = np.unwrap(self.Hd)
        # smooth heading a little
        if len(self.Hd) > 5:
            ker = np.ones(5) / 5
            pad = np.pad(self.Hd, 2, mode="edge")
            self.Hd = np.convolve(pad, ker, mode="valid")
        self.L = float(self.S[-1])
        for a in ("lo", "hi", "z", "sh_lo", "sh_hi"):
            v = getattr(self, a)
            setattr(self, a, v if callable(v) else K(v))

    def at(self, s, off=0.0):
        s = min(max(s, 0.0), self.L)
        x, y = np.interp(s, self.S, self.pts[:, 0]), np.interp(s, self.S, self.pts[:, 1])
        h = float(np.interp(s, self.S, self.Hd))
        return x - math.sin(h) * off, y + math.cos(h) * off, h

    def end(self):
        x, y, h = self.at(self.L)
        return x, y, h


def edge_pose(road, s, side):
    """World pose of the road's outer asphalt edge (side -1 right, +1 left) at s, with heading."""
    off = road.lo(s) if side < 0 else road.hi(s)
    return road.at(s, off)


# ---------------------------------------------------------------- ramps hanging off a parent road
def _curve(p0, h0, end, k0, k1, n, curve):
    dh = abs((end[2] - h0 + math.pi) % (2 * math.pi) - math.pi)
    if curve in ("auto", "quintic") and dh < math.radians(4):
        return shift_pts(p0, h0, end[:2], n)
    if curve == "cubic" and dh < math.radians(4):
        return shift_pts(p0, h0, end[:2], n, 3)
    return hermite_pts(p0, h0, end[:2], end[2], k0, k1, n)


def _branch(parent, s, kind, end_pose, side=-1, nl=1, lw=3.6, par=60.0, taper=60.0, k0=1.0, k1=1.0, z_end=0.0,
           flare=0.0, flare_len=45.0, speed=60.0, curve='auto', end_taper=0.0, start_taper=0.0, name="ramp", hermite_n=140, merge_taper=None, lanes_end=None, extra=None):
    """Ramp leaving (kind 'off') or joining (kind 'on') `parent` on its right (side -1) or left (side +1) edge at arclength s.
    Reference line = the ramp edge next to the parent; asphalt lies away from the parent.  end_pose = (x, y, heading) of the
    far end (the terminal)."""
    sg = side                                                 # asphalt side relative to the reference line (+ left, - right)
    W = nl * lw
    if kind == "off":
        s0 = s
        x0, y0, h0 = edge_pose(parent, s0, side)
        px, py = x0 + math.cos(h0) * par, y0 + math.sin(h0) * par
        a = np.array([(x0 + math.cos(h0) * t, y0 + math.sin(h0) * t) for t in np.linspace(0, par, max(2, int(par / 2)))])
        c = _curve((px, py), h0, end_pose, k0, k1, hermite_n, curve)
        pts = np.vstack([a, c[1:]])
        z0 = parent.z(s0)
        z1 = z_end
        zk = [(0, z0), (par + 5, z0), (1e9, z1)]
        n_tap = taper
        lo_k = [(0, 0), (n_tap, W)]
    else:
        x1, y1, h1 = edge_pose(parent, s, side)
        qx, qy = x1 - math.cos(h1) * par, y1 - math.sin(h1) * par
        c = _curve(end_pose[:2], end_pose[2], (qx, qy, h1), k0, k1, hermite_n, curve)
        b = np.array([(qx + math.cos(h1) * t, qy + math.sin(h1) * t) for t in np.linspace(0, par, max(2, int(par / 2)))])
        pts = np.vstack([c, b[1:]])
        z0 = z_end
        z1 = parent.z(s)
        zk = None
    r = Road(name, pts, kind="ramp", speed=speed, prio=2)
    L = r.L
    if kind == "off":
        zs = [(0, z0), (par + 8, z0), (L, z1)]
        wk = [(0, 0.0), (min(taper, L * 0.5), W)] + ([(L - flare_len, W), (L, W + flare)] if flare > 0 else [])
    else:
        zs = [(0, z0), (L - par - 8, z1 if False else z0), (L - par, z0), (L, z1)] if False else [(0, z0), (max(L - par - 8, 1.0), z0 + (z1 - z0) * 0.0), (L, z1)]
        mt = merge_taper if merge_taper is not None else taper
        first = [(0, 0.0), (start_taper, W)] if start_taper > 0 else ([(0, W + flare), (flare_len, W)] if flare > 0 else [(0, W)])
        wk = first + [(L - mt, W), (L, 0.0)]
    # smooth vertical profile: ramps rise/fall over the curved part, flat while parallel to the parent
    if kind == "off":
        a_, b_ = par + 5, L
        zk2 = [(t, z0 + (z1 - z0) * lin_ease((t - a_) / max(1.0, b_ - a_))) for t in np.arange(0, L + 6, 6.0)]
    else:
        a_, b_ = 0.0, L - par - 5
        zk2 = [(t, z0 + (z1 - z0) * lin_ease((t - a_) / max(1.0, b_ - a_))) for t in np.arange(0, L + 6, 6.0)]
    r.z = K(zk2)
    if end_taper > 0:
        wk = [(a, b) for a, b in wk if a < L - end_taper] + [(L - end_taper, W), (L, 0.0)]
    if sg > 0:
        r.lo, r.hi = K(0.0), K(wk)
    else:
        r.lo, r.hi = K([(a, -b) for a, b in wk]), K(0.0)
    r.note.update(kind=kind, nl=nl, lw=lw, par=par, taper=taper, parent=parent.name, side=side)
    r.sh_lo = K(1.2 if sg < 0 else 0.0)
    r.sh_hi = K(1.2 if sg > 0 else 0.0)
    # paint: edge lines (outer edge solid), lane dividers dashed
    ou = (lambda s_, r=r: r.lo(s_) + 0.25) if sg < 0 else (lambda s_, r=r: r.hi(s_) - 0.25)
    fa = (lambda s_, r=r: r.hi(s_) - 0.25) if sg < 0 else (lambda s_, r=r: r.lo(s_) + 0.25)
    # edge line against the gore: solid; ends where the ramp meets the parent
    r.lines.append(dict(off=ou, kind="solid", col=WHITE, rng=(0, L - (mt if kind == "on" else 0) - 2) if kind == "on" else (0, L - 3)))
    if kind == "off":
        r.lines.append(dict(off=fa, kind="solid", col=WHITE, rng=(min(taper, L * 0.4), L)))
    for i in range(1, nl):
        o = (-lw * i) if sg < 0 else lw * i
        r.lines.append(dict(off=o, kind="dash", col=WHITE, rng=(min(taper, L * 0.4) if kind == "off" else 0, L - (mt if kind == "on" else 0))))
    for i in range(nl):
        o = (-lw * (i + 0.5)) if sg < 0 else lw * (i + 0.5)
        r.cars.append((o, 0.35, 0.0 if kind == "off" else 0.0))
    return r


# ---------------------------------------------------------------- drawing
def _strip(m, road, fa, fb, bias, col, s0, s1, step=2.0, minw=0.03):
    n = max(2, int((s1 - s0) / step) + 1)
    ss = np.linspace(s0, s1, n)
    prev = None
    for s in ss:
        a = fa(s)
        b = fb(s)
        xa, ya, _ = road.at(s, a)
        xb, yb, _ = road.at(s, b)
        y = road.z(s) + bias
        cur = (xa, ya, xb, yb, y, abs(a - b))
        if prev is not None and (cur[5] > minw or prev[5] > minw):
            m.quad((prev[0], prev[4], prev[1]), (cur[0], cur[4], cur[1]), (cur[2], cur[4], cur[3]), (prev[2], prev[4], prev[3]), col)
        prev = cur


def _wall(m, road, off_f, h, w, col, s0, s1, step=3.0, z_extra=0.0, topcol=None):
    ss = np.linspace(s0, s1, max(2, int((s1 - s0) / step) + 1))
    prev = None
    for s in ss:
        o = off_f(s)
        x1, y1, _ = road.at(s, o - w / 2)
        x2, y2, _ = road.at(s, o + w / 2)
        z = road.z(s) + z_extra
        cur = (x1, y1, x2, y2, z)
        if prev is not None:
            m.quad((prev[0], prev[4] + h, prev[1]), (cur[0], cur[4] + h, cur[1]), (cur[2], cur[4] + h, cur[3]), (prev[2], prev[4] + h, prev[3]), topcol or col)
            m.quad((prev[0], prev[4], prev[1]), (cur[0], cur[4], cur[1]), (cur[0], cur[4] + h, cur[1]), (prev[0], prev[4] + h, prev[1]), col)
            m.quad((prev[2], prev[4], prev[3]), (cur[2], cur[4], cur[3]), (cur[2], cur[4] + h, cur[3]), (prev[2], prev[4] + h, prev[3]), col)
        prev = cur


def footprint(road, pad=0.0):
    ss = np.linspace(0, road.L, max(3, int(road.L / 4) + 1))
    L = [road.at(s, road.hi(s) + road.sh_hi(s) + pad)[:2] for s in ss]
    R = [road.at(s, road.lo(s) - road.sh_lo(s) - pad)[:2] for s in ss]
    p = Polygon(L + R[::-1])
    return p if p.is_valid else p.buffer(0)


def draw_road(m, road, rnd, casters, others):
    L = road.L
    prio = road.prio
    b0 = 0.003 * prio
    # shoulders then asphalt
    _strip(m, road, lambda s: road.lo(s) - road.sh_lo(s), road.lo, b0 - 0.002 + 0.0, SHOULDER, 0, L)
    _strip(m, road, road.hi, lambda s: road.hi(s) + road.sh_hi(s), b0 - 0.002, SHOULDER, 0, L)
    _strip(m, road, road.lo, road.hi, b0, road.col, 0, L)
    # paint
    for ln in road.lines:
        off = ln["off"]
        f = off if callable(off) else (lambda s, o=off: o)
        r0, r1 = ln.get("rng") or (0, L)
        r0, r1 = max(0, r0), min(L, r1)
        if r1 - r0 < 1:
            continue
        w = ln.get("w", 0.15)
        col = ln.get("col", WHITE)
        k = ln.get("kind", "solid")
        if k == "solid":
            _strip(m, road, lambda s: f(s) - w / 2, lambda s: f(s) + w / 2, 0.06, col, r0, r1, step=2.0, minw=0.0)
        elif k == "dbl":
            for dd in (-0.15, 0.15):
                _strip(m, road, lambda s, dd=dd: f(s) + dd - w / 2, lambda s, dd=dd: f(s) + dd + w / 2, 0.06, col, r0, r1, step=2.0, minw=0.0)
        else:
            dash, gap = (3.0, 9.0) if k == "dash" else (1.5, 3.0)
            s = r0
            while s < r1:
                e = min(r1, s + dash)
                _strip(m, road, lambda q: f(q) - w / 2, lambda q: f(q) + w / 2, 0.06, col, s, e, step=1.5, minw=0.0)
                s += dash + gap
    # vertical structure
    gstep = 2.0
    ss = np.arange(0, L + gstep, gstep)
    prev = None
    for s in ss:
        s = min(s, L)
        z = road.z(s)
        lo_e, hi_e = road.lo(s) - road.sh_lo(s), road.hi(s) + road.sh_hi(s)
        xl, yl, _ = road.at(s, hi_e)
        xr, yr, _ = road.at(s, lo_e)
        cur = (xl, yl, xr, yr, z, s)
        if prev is not None:
            zm = (z + prev[4]) / 2
            if zm > 0.35:
                for (a, b, sg) in ((0, 1, 1), (2, 3, -1)):
                    px, py = prev[a], prev[b]
                    cx, cy = cur[a], cur[b]
                    h = prev[5]
                    _, _, hd = road.at(s)
                    nx, ny = -math.sin(hd) * sg, math.cos(hd) * sg
                    if zm <= 4.6:
                        d = zm * 2.0
                        m.quad((px, prev[4], py), (cx, z, cy), (cx + nx * d, 0.0, cy + ny * d), (px + nx * d, 0.0, py + ny * d), GRASS_D)
                    else:
                        m.quad((px, prev[4], py), (cx, z, cy), (cx, z - 1.3, cy), (px, prev[4] - 1.3, py), FASCIA)
                        m.quad((px, prev[4] - 1.3, py), (cx, z - 1.3, cy), (cx - nx * 2.5, z - 1.8, cy - ny * 2.5), (px - nx * 2.5, prev[4] - 1.8, py - ny * 2.5), (150, 148, 142))
        prev = cur
    if road.rail_lo or road.rail_hi or True:
        ssr = np.arange(0, L, 3.0)
        for s in ssr:
            z = road.z(s)
            if z < 0.4 and not (road.rail_lo or road.rail_hi):
                continue
            col = PARAPET if z > 0.4 else GUARD
            for side, fl in ((-1, road.rail_lo or z > 0.4), (1, road.rail_hi or z > 0.4)):
                if not fl:
                    continue
                if side < 0:
                    o = road.lo(s) - road.sh_lo(s) + 0.2
                else:
                    o = road.hi(s) + road.sh_hi(s) - 0.2
                _wall(m, road, lambda q, side=side: (road.lo(q) - road.sh_lo(q) + 0.2) if side < 0 else (road.hi(q) + road.sh_hi(q) - 0.2),
                      1.0 if z > 0.4 else 0.6, 0.25, col, s, min(L, s + 3.0), step=3.0, z_extra=0.0)
                break
    # piers
    s = 8.0
    while s < L - 4:
        z = road.z(s)
        if z > 4.6:
            wd = road.hi(s) - road.lo(s) + road.sh_lo(s) + road.sh_hi(s)
            cx, cy, hd = road.at(s, (road.lo(s) + road.hi(s)) / 2)
            ok = True
            for o in others:
                if o is not road and o.z(0) < z - 3 and o.fp.contains(Point(cx, cy)):
                    ok = False
            if ok:
                cols = 1 if wd < 11 else 2
                for k in range(cols):
                    off = (road.lo(s) + road.hi(s)) / 2 + ((k - (cols - 1) / 2) * wd * 0.5)
                    x, y, _ = road.at(s, off)
                    m.box(x, 0, y, 1.7, z - 1.3, 1.7, CONC, hd)
                if cols == 2:
                    x, y, _ = road.at(s, (road.lo(s) + road.hi(s)) / 2)
                    m.box(x, z - 2.6, y, 1.4, 1.3, wd * 0.95, CONC, hd + math.pi / 2)
                casters.append((Point(cx, cy).buffer(wd / 2), z))
        s += 26.0
    if road.lamps:
        s = 30.0
        while s < L - 10:
            z = road.z(s)
            o = road.hi(s) + road.sh_hi(s) - 0.2 if road.barrier_hi else road.lo(s) - road.sh_lo(s) + 0.3
            x, y, hd = road.at(s, o)
            tx, ty, _ = road.at(s, o + (3.0 if road.barrier_hi else -3.0) * -1)
            m.cyl(x, z, z + 9.0, y, 0.09, POLE, 6)
            m.box(x + (tx - x) * 0.4, z + 8.9, y + (ty - y) * 0.4, 0.5, 0.12, 0.3, POLE, hd)
            s += 55.0


def zebra(m, road, s, lo, hi, z, bar=0.5, gap=0.5, ln=3.2):
    x0, off = lo, lo
    while off + bar <= hi:
        _strip(m, road, lambda q, o=off: o, lambda q, o=off: o + bar, 0.062, WHITE, s - ln / 2, s + ln / 2, step=1.6, minw=0.0)
        off += bar + gap


def stopline(m, road, s, lo, hi):
    _strip(m, road, lambda q: lo, lambda q: hi, 0.062, WHITE, s - 0.2, s + 0.2, step=0.4, minw=0.0)


def gantry(m, x, y, z, h, w, rnd):
    dx, dy = math.cos(h + math.pi / 2), math.sin(h + math.pi / 2)
    for sg in (-1, 1):
        m.cyl(x + dx * w * sg / 2, z, z + 7.4, y + dy * w * sg / 2, 0.22, POLE, 8)
    m.box(x, z + 6.6, y, 0.5, 0.5, w + 1.0, POLE, h + math.pi / 2 * 0 - math.pi / 2 * 0, roof=POLE)
    m.box(x, z + 4.8, y, 0.15, 1.8, w * 0.55, GREEN_SIGN, h + math.pi / 2 - math.pi / 2, roof=GREEN_SIGN)


@dataclass
class Plan:
    name: str
    roads: List[Road]
    extent: float = 450.0
    seed: int = 1
    cars: bool = True
    gantries: list = field(default_factory=list)       # (road, s, width)
    signals: list = field(default_factory=list)        # (road, s, side offsets list, state)
    crossings: list = field(default_factory=list)      # (road, s, lo, hi)
    stops: list = field(default_factory=list)
    medians: list = field(default_factory=list)        # (road_a, road_b, kind)
    rings: list = field(default_factory=list)          # (cx, cy, r_in, z, kind)
    info: dict = field(default_factory=dict)
    sim: dict = field(default_factory=dict)


def draw_median(m, ra, rb, kind, rnd):
    """Raised median between two roads running side by side (ra left edge hi vs rb right edge lo along ra)."""
    L = ra.L
    ss = np.linspace(0, L, max(3, int(L / 3) + 1))
    prev = None
    for s in ss:
        x, y, h = ra.at(s, ra.hi(s))
        # nearest point on rb
        d = np.hypot(rb.pts[:, 0] - x, rb.pts[:, 1] - y)
        j = int(np.argmin(d))
        sb = rb.S[j]
        x2, y2, _ = rb.at(sb, rb.hi(sb))
        cur = (x, y, x2, y2, ra.z(s))
        if prev is not None and math.hypot(x2 - x, y2 - y) > 0.4:
            top = (150, 180, 120) if kind in ("grass", "raised") else CONC
            m.quad((prev[0], prev[4] + 0.15, prev[1]), (cur[0], cur[4] + 0.15, cur[1]), (cur[2], cur[4] + 0.15, cur[3]), (prev[2], prev[4] + 0.15, prev[3]), top)
            for (a, b) in ((0, 1), (2, 3)):
                m.quad((prev[a], prev[4], prev[b]), (cur[a], cur[4], cur[b]), (cur[a], cur[4] + 0.15, cur[b]), (prev[a], prev[4] + 0.15, prev[b]), CONC)
        prev = cur


def build_plan(plan: Plan) -> Mesh:
    rnd = random.Random(plan.seed)
    m = Mesh()
    roads = plan.roads
    for r in roads:
        r.fp = footprint(r, 1.0)
    big = plan.extent * 3
    m.poly(box(-big, -big, big, big), -0.05, GROUND)
    casters = []
    for r in sorted(roads, key=lambda r: r.prio):
        draw_road(m, r, rnd, casters, roads)
    for a, b, kind in plan.medians:
        draw_median(m, a, b, kind, rnd)
    for road, s, w in plan.gantries:
        x, y, h = road.at(s, (road.lo(s) + road.hi(s)) / 2)
        gantry(m, x, y, road.z(s), h, (road.hi(s) - road.lo(s)) + 1.0, rnd)
        casters.append((Point(x, y).buffer(0.6), 7.0))
    for road, s, lo, hi in plan.crossings:
        zebra(m, road, s, lo, hi, road.z(s))
    for road, s, lo, hi in plan.stops:
        stopline(m, road, s, lo, hi)
    for road, s, state in plan.signals:
        z = road.z(s)
        o = road.lo(s) - road.sh_lo(s) - 0.4
        x, y, h = road.at(s, o)
        m.cyl(x, z, z + 4.6, y, 0.1, POLE, 8)
        mx, my, _ = road.at(s, (road.lo(s) + road.hi(s)) / 2)
        m.box((x + mx) / 2, z + 4.5, (y + my) / 2, math.hypot(mx - x, my - y), 0.14, 0.14, POLE, math.atan2(my - y, mx - x))
        yaw = h + math.pi
        signal_head(m, mx, z + 4.0, my, yaw, state)
        signal_head(m, x, z + 3.0, y, yaw, state)
    # roundabout rings
    for (cx, cy, rr, z, kind) in plan.rings:
        d = Point(cx, cy).buffer(rr, 48)
        m.prism(d, z - 0.1, z + 0.18, CONC, CONC)
        m.poly(d.buffer(-0.5), z + 0.19, (118, 156, 92))
        for q in range(int(rr * 0.5)):
            a = q * 2 * math.pi / max(1, int(rr * 0.5))
            if kind == 'trees' and rr > 8:
                tree(m, cx + (rr - 4) * math.cos(a), cy + (rr - 4) * math.sin(a), rnd, z + 0.2)
    # cars
    if plan.cars:
        for r in roads:
            for off, dens, _ in r.cars:
                s = rnd.uniform(6, 24)
                while s < r.L - 8:
                    if rnd.random() < dens and r.lo(s) - 0.5 < off < r.hi(s) + 0.5 or (rnd.random() < dens and r.lo(s) < off < r.hi(s)):
                        # keep inside the asphalt at this s
                        x, y, h = r.at(s, off)
                        if r.lo(s) + 1.0 < off < r.hi(s) - 1.0:
                            m.car(x, y, h + (math.pi if _ else 0.0), rnd.choice(CAR_COLS), y=r.z(s) + 0.01)
                            casters.append((Point(x, y).buffer(1.0), 1.5))
                    s += rnd.uniform(14, 40)
    # context: trees in the free land
    fp_all = unary_union([r.fp for r in roads])
    ext = plan.extent
    for _ in range(0 if plan.info.get('notrees') else int(ext * 0.9)):
        x, y = rnd.uniform(-ext, ext), rnd.uniform(-ext, ext)
        if not fp_all.buffer(8).contains(Point(x, y)):
            tree(m, x, y, rnd, 0.0, rnd.uniform(0.8, 1.3))
            casters.append((Point(x, y).buffer(2.2), 6.0))
    # sun shadows of decks and trees on the ground and on lower roads
    from shapely.affinity import translate
    sh = []
    for fp, h in casters:
        v = (0.56 * h, 0.50 * h)
        sh.append(unary_union([fp, translate(fp, *v)]).convex_hull)
    for r in roads:
        zz = r.z(r.L / 2)
        if max(r.z(s) for s in np.linspace(0, r.L, 12)) > 2.5:
            ps = []
            for a, b in zip(np.linspace(0, r.L, 40)[:-1], np.linspace(0, r.L, 40)[1:]):
                za = r.z((a + b) / 2)
                if za > 2.5:
                    seg = Polygon([r.at(a, r.hi(a))[:2], r.at(b, r.hi(b))[:2], r.at(b, r.lo(b))[:2], r.at(a, r.lo(a))[:2]]).buffer(0)
                    ps.append(translate(seg, 0.56 * za, 0.50 * za))
            if ps:
                sh.append(unary_union(ps))
    if sh:
        S = unary_union(sh)
        ground_asph = unary_union([r.fp for r in roads if r.z(0) < 0.3 and r.z(r.L) < 0.3 and max(r.z(s) for s in np.linspace(0, r.L, 8)) < 0.5]) if roads else Polygon()
        m.poly(S.difference(fp_all).intersection(box(-big, -big, big, big)), -0.04, tuple(int(v * 0.68) for v in GROUND))
        m.poly(S.intersection(ground_asph), 0.045, ASPH_DARK)
    return m


# ---------------------------------------------------------------- simulation / design checks for ramps
def friction(v):
    """Max side friction by design speed (AASHTO Green Book table 3-6): tight, slow curves allow much more than fast ones."""
    tab = [(20, 0.18), (30, 0.28), (40, 0.23), (50, 0.19), (60, 0.17), (80, 0.14), (100, 0.12), (120, 0.09)]
    if v <= tab[0][0]:
        return tab[0][1]
    for (a, fa), (b, fb) in zip(tab, tab[1:]):
        if v <= b:
            return fa + (fb - fa) * (v - a) / (b - a)
    return tab[-1][1]


def ramp_report(r: Road, lat_f=None, e=0.06):
    """Gradient, minimum curve radius and implied design speed (R = V^2 / (127 (e+f)) ), taper checks."""
    pts = r.pts
    lat_f = friction(r.speed) if lat_f is None else lat_f
    d1 = np.diff(pts, axis=0)
    hh = np.unwrap(np.arctan2(d1[:, 1], d1[:, 0]))
    ds = np.hypot(d1[:, 0], d1[:, 1])
    k = np.abs(np.diff(hh)) / np.maximum(1e-6, (ds[:-1] + ds[1:]) / 2)
    k = np.convolve(k, np.ones(5) / 5, mode="same") if len(k) > 5 else k
    rmin = float(1.0 / max(1e-6, k.max())) if len(k) else 1e9
    zs = np.array([r.z(s) for s in r.S])
    grade = np.abs(np.diff(zs)) / np.maximum(1e-6, np.diff(r.S))
    v = math.sqrt(127.0 * min(rmin, 2000.0) * (e + lat_f))
    return dict(length=round(r.L, 1), min_radius=round(min(rmin, 9999.0), 1), design_speed_kmh=round(min(v, 130), 0),
                max_grade_pct=round(float(grade.max()) * 100, 1), ok_radius=bool(rmin * 1.0 >= r.speed ** 2 / (127 * (e + lat_f)) * 0.8),
                ok_grade=bool(grade.max() <= 0.08))


def branch(parent, s, kind, end_pose, k0=None, k1=None, fit=True, **kw):
    """Ramp with automatic curve fitting: lowers the Hermite tension until the minimum radius meets the ramp speed."""
    name = kw.get("name", "ramp")
    dflt = dict(nl=1, lw=3.6, par=60.0, taper=60.0, flare=0.0, flare_len=45.0, speed=60.0, merge_taper=kw.get("taper", 60.0), end_taper=0.0,
                start_taper=0.0, z_end=0.0, curve="auto", side=-1)
    for key, dv in dflt.items():
        kw[key] = g(name, key, kw.get(key, dv))
    kw["nl"] = int(kw["nl"])
    k0 = g(name, "k0", k0 or 0.6)
    k1 = g(name, "k1", k1 or k0)
    s = s + g(name, "s_shift", 0.0)
    end_pose = (end_pose[0] + g(name, "end_dx", 0.0), end_pose[1] + g(name, "end_dy", 0.0), end_pose[2] + math.radians(g(name, "end_dh", 0.0)))
    sp = kw.get("speed", 60.0)
    rreq = sp ** 2 / (127 * (0.06 + friction(sp))) * 0.75
    ks = [k0 or 0.6] if not fit else sorted({k0 or 0.6, 0.6, 0.5, 0.42, 0.35, 0.3, 0.26}, reverse=True)
    best = None
    for k in ks:
        r = _branch(parent, s, kind, end_pose, k0=k, k1=k1 or k, **kw)
        rep = ramp_report(r)
        r.note["k"] = k
        if best is None or rep["min_radius"] > best[1]:
            best = (r, rep["min_radius"])
        if rep["min_radius"] >= rreq:
            return r
    return best[0]


def widen(road, side, s0, s1, dw, ramp_in=40.0, ramp_out=40.0):
    """Move an asphalt edge outwards by dw between s0 and s1 (auxiliary / added lane), smooth in and out."""
    old = road.lo if side < 0 else road.hi
    sg = -1 if side < 0 else 1

    def f(s, old=old):
        a = smooth((s - s0) / max(1e-6, ramp_in)) if s < s1 else smooth((s1 + ramp_out - s) / max(1e-6, ramp_out))
        return old(s) + sg * dw * (a if s0 - 1e-6 <= s <= s1 + ramp_out else 0.0)
    if side < 0:
        road.lo = f
    else:
        road.hi = f
    return road


def custom_ramp(name, pts, nl=1, lw=3.8, side=-1, taper_a=0.0, taper_b=0.0, za=0.0, zb=0.0, z_rng=None, speed=50.0, cars=0.35,
                edge_a=True, edge_b=True):
    """Ramp from an explicit centre/reference polyline; asphalt to the right (side -1) or left (+1) of the reference line."""
    nl = int(g(name, "nl", nl))
    lw = g(name, "lw", lw)
    taper_a, taper_b = g(name, "taper_a", taper_a), g(name, "taper_b", taper_b)
    za, zb = g(name, "za", za), g(name, "zb", zb)
    speed = g(name, "speed", speed)
    cars = g(name, "traffic", cars)
    r = Road(name, pts, kind="ramp", speed=speed, prio=2)
    L = r.L
    W = nl * lw
    wk = [(0.0, 0.0 if taper_a > 0 else W), (max(taper_a, 0.1), W), (max(L - taper_b, taper_a + 0.2), W), (L, 0.0 if taper_b > 0 else W)]
    r.lo, r.hi = (K([(a, -b) for a, b in wk]), K(0.0)) if side < 0 else (K(0.0), K(wk))
    a_, b_ = z_rng if z_rng else (0.0, L)
    r.z = K([(t, za + (zb - za) * lin_ease((t - a_) / max(1.0, b_ - a_))) for t in np.arange(0, L + 6, 6.0)])
    r.sh_lo = K(1.2 if side < 0 else 0.0)
    r.sh_hi = K(1.2 if side > 0 else 0.0)
    ou = (lambda s_, r=r: r.lo(s_) + 0.25) if side < 0 else (lambda s_, r=r: r.hi(s_) - 0.25)
    fa = (lambda s_, r=r: r.hi(s_) - 0.25) if side < 0 else (lambda s_, r=r: r.lo(s_) + 0.25)
    r.lines.append(dict(off=ou, kind="solid", col=WHITE, rng=(0, L - max(taper_b, 0) - 1)))
    r.lines.append(dict(off=fa, kind="solid", col=WHITE, rng=(max(taper_a, 0) + 1, L - 1)))
    for i in range(1, nl):
        o = (-lw * i) if side < 0 else lw * i
        r.lines.append(dict(off=o, kind="dash", col=WHITE, rng=(taper_a, L - taper_b)))
    for i in range(nl):
        o = (-lw * (i + 0.5)) if side < 0 else lw * (i + 0.5)
        r.cars.append((o, cars, 0.0))
    r.note.update(kind="custom", nl=nl, lw=lw)
    return r
