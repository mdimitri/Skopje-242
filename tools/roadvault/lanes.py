"""Lane schedule and arm frame (curved centrelines).  Design rules follow public manuals (TxDOT RDM 4.10.5 / 13.9 / 13.10,
Iowa DOT 6C-1, FHWA roundabout guide): taper length L = W*S^2/155 (S km/h <= 70) or 0.62*W*S, lane opening = L/2 or 15:1."""
import math
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ramp(t, shape="smooth"):
    t = max(0.0, min(1.0, t))
    if shape == "linear":
        return t
    if shape == "cos":
        return 0.5 - 0.5 * math.cos(math.pi * t)
    if shape == "cubic":
        return t * t * t * (t * (6 * t - 15) + 10)
    if shape == "ease_in":
        return t * t
    if shape == "ease_out":
        return 1 - (1 - t) ** 2
    return t * t * (3 - 2 * t)


def taper_len(w, speed_kmh, kind="drop", ratio=None):
    """Minimum taper (m) for a lane of width w: drop = L, opening = L/2, ratio => w*ratio."""
    if ratio:
        return w * ratio
    S = max(speed_kmh, 20.0)
    L = 0.62 * S * w if S >= 70 else w * S * S / 155.0
    return L if kind == "drop" else L * 0.5


@dataclass
class Lane:
    kind: str = "drive"                 # drive | turn | bus | bike | tram | shoulder
    w: float = 3.25
    near: Optional[float] = None        # distance from the junction edge where full width begins (None: always)
    far: Optional[float] = None         # ... where full width ends
    t_near: float = 0.0                 # ramp length towards the junction side
    t_far: float = 0.0                  # ramp length towards the far side
    shape: str = "smooth"
    keys: Optional[list] = None         # [(d_rel, width)] explicit width profile (narrowing / widening)
    marking_in: str = "auto"            # line towards the median: auto | solid | dashed | none | double
    colour: Optional[list] = None
    arrow: Optional[str] = None         # T L R TL TR ...


def lane_width(l: Lane, dd: float) -> float:
    w = l.w
    if l.keys:
        ks = sorted(l.keys)
        if dd <= ks[0][0]:
            w = ks[0][1]
        elif dd >= ks[-1][0]:
            w = ks[-1][1]
        else:
            for (d0, w0), (d1, w1) in zip(ks, ks[1:]):
                if d0 <= dd <= d1:
                    w = w0 + (w1 - w0) * ramp((dd - d0) / max(1e-6, d1 - d0), l.shape)
                    break
    f = 1.0
    if l.near is not None:
        f *= ramp((dd - (l.near - l.t_near)) / l.t_near, l.shape) if l.t_near > 0 else (1.0 if dd >= l.near else 0.0)
    if l.far is not None:
        f *= ramp(((l.far + l.t_far) - dd) / l.t_far, l.shape) if l.t_far > 0 else (1.0 if dd <= l.far else 0.0)
    return w * f


def ensure(a, force=False):
    """Fills a.lanes_in / a.lanes_out from the simple fields unless the user supplied explicit lane lists."""
    if getattr(a, "_custom_lanes", False):
        return
    if a.lanes_in or a.lanes_out:
        a._custom_lanes = True
        return
    def side(n, flare, extra_gain, bike, bus, inbound):
        L = []
        for k in range(int(n)):
            L.append(Lane("drive", a.lane_w))
        if inbound and a.taper_in < 0:
            for l in L[len(L) + int(a.taper_in):]:
                l.far, l.t_far = a.taper_at - a.e, 30.0
        for k in range(int(flare)):
            L.append(Lane("drive", a.lane_w, far=a.flare_len - a.taper, t_far=a.taper))
        if inbound and a.taper_in > 0:
            for k in range(int(a.taper_in)):
                L.append(Lane("drive", a.lane_w, near=a.taper_at - a.e + 30.0, t_near=30.0))
        if bus and L:
            L[-1].kind = "bus"
        if bike:
            L.append(Lane("bike", 1.9))
        return L
    a.lanes_in = side(a.lin, a.flare_in, 0, a.bike and a.lin, a.bus and a.lin, True) if a.lin else []
    a.lanes_out = side(a.lout, a.flare_out, 0, a.bike and a.lout, False, False) if a.lout else []
    a._auto_lanes = True


def clear_auto(a):
    if getattr(a, "_auto_lanes", False):
        a.lanes_in, a.lanes_out = [], []
        a._auto_lanes = False


def widths(a, d, inbound=True):
    dd = d - a.e
    return [lane_width(l, dd) for l in (a.lanes_in if inbound else a.lanes_out)]


def in_w(a, d):
    return sum(widths(a, d, True))


def out_w(a, d):
    return sum(widths(a, d, False))


def s_lo(a, d):
    return -(a.mw / 2 + in_w(a, d)) if a.lanes_in else -(a.mw / 2)


def s_hi(a, d):
    return a.mw / 2 + out_w(a, d) if a.lanes_out else a.mw / 2


def boundary(a, k, d, inbound=True):
    """Lateral position of the line between lane k-1 and k (k=0: carriageway edge next to the median)."""
    ws = widths(a, d, inbound)
    c = sum(ws[:k])
    return -(a.mw / 2 + c) if inbound else a.mw / 2 + c


def lane_spans(a, d, inbound=True):
    """[(lane, s_inner, s_outer, width)] at distance d."""
    out = []
    ws = widths(a, d, inbound)
    c = 0.0
    for l, w in zip(a.lanes_in if inbound else a.lanes_out, ws):
        s0 = -(a.mw / 2 + c) if inbound else a.mw / 2 + c
        s1 = -(a.mw / 2 + c + w) if inbound else a.mw / 2 + c + w
        out.append((l, s0, s1, w))
        c += w
    return out


# ---------------------------------------------------------------- frame (curved arms)
def _frame(a):
    fr = getattr(a, "_fr", None)
    key = (a.angle, a.offset, tuple(map(tuple, a.arcs)), a.L)
    if fr is not None and fr[0] == key:
        return fr[1]
    step = 0.5
    ds = np.arange(-20.0, a.L + 40.0, step)
    ang0 = math.radians(a.angle)
    x0, y0 = -math.sin(ang0) * a.offset, math.cos(ang0) * a.offset
    h = np.full(len(ds), ang0)
    for (d0, ln, R) in a.arcs:
        t = np.clip((ds - d0) / max(ln, 1e-6), 0, 1)
        h = h + t * (ln / R) if R else h
        # after the arc the heading stays turned: handled by the clip (t saturates at 1)
    x = np.zeros(len(ds))
    y = np.zeros(len(ds))
    i0 = int(np.searchsorted(ds, 0.0))
    x[i0], y[i0] = x0, y0
    for i in range(i0 + 1, len(ds)):
        hm = 0.5 * (h[i] + h[i - 1])
        x[i] = x[i - 1] + math.cos(hm) * step
        y[i] = y[i - 1] + math.sin(hm) * step
    for i in range(i0 - 1, -1, -1):
        hm = 0.5 * (h[i] + h[i + 1])
        x[i] = x[i + 1] - math.cos(hm) * step
        y[i] = y[i + 1] - math.sin(hm) * step
    fr = (ds, x, y, h)
    a._fr = (key, fr)
    return fr


def P(a, d, s):
    if not a.arcs:
        ua = math.radians(a.angle)
        ux, uy = math.cos(ua), math.sin(ua)
        s = s + a.offset
        return (ux * d - uy * s, uy * d + ux * s)
    ds, x, y, h = _frame(a)
    xx, yy, hh = np.interp(d, ds, x), np.interp(d, ds, y), np.interp(d, ds, h)
    return (float(xx - math.sin(hh) * s), float(yy + math.cos(hh) * s))


def heading(a, d):
    if not a.arcs:
        return math.radians(a.angle)
    ds, x, y, h = _frame(a)
    return float(np.interp(d, ds, h))


def U(a, d=None):
    h = heading(a, a.e + 20.0 if d is None else d)
    return math.cos(h), math.sin(h)


def to_arm(a, x, y):
    """Plan point -> (d, s) in the arm's frame (nearest frame sample, refined)."""
    ds, fx, fy, fh = _frame(a)
    i = int(np.argmin((fx - x) ** 2 + (fy - y) ** 2))
    h = fh[i]
    dx, dy = x - fx[i], y - fy[i]
    return float(ds[i] + dx * math.cos(h) + dy * math.sin(h)), float(-dx * math.sin(h) + dy * math.cos(h))
