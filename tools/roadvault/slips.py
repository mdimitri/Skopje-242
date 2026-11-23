"""Right-turn slip lanes as designed geometry: bay taper -> parallel auxiliary lane -> peel-off taper -> straight -> cubic
curve (asymmetric / compound via k1,k2,asym) -> straight -> accel/parallel lane -> exit taper.  Islands are the holes the
slip band leaves with the junction asphalt (nose-rounded).  Defaults follow TxDOT RDM 13.9.1 / 13.10.1 (entry angle 55-70 deg,
island side >= 4.5 m, crosswalk-yield >= 6.1 m, lane 3.0-3.4 m, radius 12-25 m)."""
import math
from dataclasses import dataclass, fields
from typing import Optional

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from lanes import P, heading, s_hi, s_lo, taper_len, ramp, to_arm


@dataclass
class Slip:
    R: float = 20.0                  # corner radius of the slip curve (m)
    asym: float = 1.0                # exit tangent length / entry tangent length (1 = symmetric, <1 or >1 = compound)
    k1: float = 0.56                 # curve fullness at the entry end (0.5523 = circular for 90 deg)
    k2: float = 0.56                 # ... at the exit end
    w: float = 4.0                   # slip lane width
    w_exit: Optional[float] = None
    gap: float = 1.2                 # clear gap between arm edge and slip lane on the straight run (island width there)
    gap_out: Optional[float] = None
    bay_taper: Optional[float] = None    # length of the taper opening the lane (None: from the taper rule)
    decel_len: float = 18.0          # parallel auxiliary lane length before the peel-off
    peel_len: float = 14.0           # length over which the lane shifts away from the arm edge
    straight_in: float = 4.0         # straight run between peel-off and the curve
    exit_taper: Optional[float] = None
    accel_len: float = 0.0           # parallel merge/acceleration lane length
    peel_out_len: float = 6.0
    straight_out: float = 3.0
    overlap: float = 0.08            # overlap with the arm at the lane ends so the asphalt joins
    nose_r: float = 0.9              # island nose radius at the diverge end
    nose_r_far: float = 0.9          # island nose radius at the corner end
    min_island_area: float = 6.0
    zebra: bool = True
    zebra_at: float = 0.55           # position along the curve (0..1)
    zebra_len: float = 3.2
    zebra_bar: float = 0.5
    zebra_gap: float = 0.5
    control: str = "yield"           # yield | stop | none
    yield_at: float = 0.86
    teeth_len: float = 0.9
    island_trees: bool = True
    shape: str = "smooth"
    vehicle: Optional[str] = None    # design vehicle for the simulation / autofit (P SU BUS WB-40 WB-62)
    curve_samples: int = 36


def as_slip(d):
    if isinstance(d, Slip):
        return d
    names = {f.name for f in fields(Slip)}
    return Slip(**{k: v for k, v in d.items() if k in names})


def neighbour_right(scene, i):
    ai = scene.arms[i].angle
    best, bj = 361.0, None
    for j, b in enumerate(scene.arms):
        if j == i:
            continue
        dlt = (ai - b.angle) % 360.0
        if 0 < dlt < best:
            best, bj = dlt, j
    return bj, best


def _meet(p, u, q, v):
    """Intersection of the lines p + t u and q + r v."""
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
    return (p[0] + u[0] * t, p[1] + u[1] * t)


def slip_path(scene, i, sp: Slip):
    """-> (points Nx2, widths N, info dict) of the slip lane centre line."""
    a = scene.arms[i]
    j, gap_ang = neighbour_right(scene, i)
    if j is None or gap_ang > 172:
        return None
    b = scene.arms[j]
    w, wx = sp.w, sp.w_exit or sp.w
    g_in, g_out = sp.gap, sp.gap if sp.gap_out is None else sp.gap_out
    dref = a.e + a.flare_len + 4.0 if (a.flare_in or a.lanes_in and any(l.far is not None for l in a.lanes_in)) else a.e + 12.0
    drefb = b.e + b.flare_len + 4.0 if b.flare_out else b.e + 12.0
    pi0, pi1 = P(a, dref, s_lo(a, dref) - g_in - w / 2), P(a, dref + 10, s_lo(a, dref) - g_in - w / 2)
    pj0, pj1 = P(b, drefb, s_hi(b, drefb) + g_out + wx / 2), P(b, drefb + 10, s_hi(b, drefb) + g_out + wx / 2)
    ui = np.array(pi1) - np.array(pi0)
    ui /= np.linalg.norm(ui)
    uj = np.array(pj1) - np.array(pj0)
    uj /= np.linalg.norm(uj)
    X = _meet(pi0, ui, pj0, uj)
    if X is None:
        return None
    X = np.array(X)
    defl = math.acos(max(-1.0, min(1.0, float((-ui) @ uj))))        # turn angle between travel directions
    t1 = sp.R * math.tan(defl / 2)
    t2 = t1 * sp.asym
    T1, T2 = X + ui * t1, X + uj * t2
    dT1, _ = to_arm(a, *T1)
    dT2, _ = to_arm(b, *T2)
    dT1 = max(dT1, a.e + 1.0)
    dT2 = max(dT2, b.e + 1.0)
    bay = sp.bay_taper if sp.bay_taper is not None else taper_len(w, a.speed, "open")
    ext = sp.exit_taper if sp.exit_taper is not None else taper_len(wx, b.speed, "open")
    d_pe = dT1 + sp.straight_in
    d_ps = d_pe + sp.peel_len
    d_dec = d_ps + sp.decel_len
    d_bay = d_dec + bay
    pts, wid, vpts = [], [], []
    n_in = max(2, int((d_bay - dT1) / 1.0))
    for k in range(n_in + 1):
        d = d_bay - (d_bay - dT1) * k / n_in
        width = w * ramp((d_bay - d) / max(bay, 1e-6), sp.shape) if d > d_dec else w
        if d >= d_ps:
            g = 0.0
        elif d >= d_pe:
            g = g_in * ramp((d_ps - d) / max(sp.peel_len, 1e-6), sp.shape)
        else:
            g = g_in
        s = s_lo(a, d) - g - width / 2 + (sp.overlap if g < 0.05 else 0.0)
        pts.append(P(a, d, s))
        f = ramp(width / w, "smooth")
        vpts.append(P(a, d, (1 - f) * (s_lo(a, d) + a.lane_w / 2) + f * (s_lo(a, d) - g - width / 2)))
        wid.append(max(width, 0.01))
    # curve between the last entry sample and the first exit sample
    d_ex_pe = dT2 + sp.straight_out
    d_ex_ps = d_ex_pe + sp.peel_out_len
    d_acc = d_ex_ps + sp.accel_len
    d_end = d_acc + ext
    exit_pts, exit_w, exit_v = [], [], []
    n_out = max(2, int((d_end - dT2) / 1.0))
    for k in range(n_out + 1):
        d = dT2 + (d_end - dT2) * k / n_out
        width = wx * ramp((d_end - d) / max(ext, 1e-6), sp.shape) if d > d_acc else wx
        if d >= d_ex_ps:
            g = 0.0
        elif d >= d_ex_pe:
            g = g_out * ramp((d_ex_ps - d) / max(sp.peel_out_len, 1e-6), sp.shape)
        else:
            g = g_out
        s = s_hi(b, d) + g + width / 2 - (sp.overlap if g < 0.05 else 0.0)
        exit_pts.append(P(b, d, s))
        f = ramp(width / wx, "smooth")
        exit_v.append(P(b, d, (1 - f) * (s_hi(b, d) - b.lane_w / 2) + f * (s_hi(b, d) + g + width / 2)))
        exit_w.append(max(width, 0.01))
    p0, p3 = np.array(pts[-1]), np.array(exit_pts[0])
    p1 = p0 + (X - p0) * sp.k1
    p2 = p3 + (X - p3) * sp.k2
    cur, cw = [], []
    for k in range(1, sp.curve_samples):
        t = k / sp.curve_samples
        q = (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3
        cur.append(tuple(q))
        cw.append(w + (wx - w) * t)
    info = dict(veh_pts=np.array(vpts + cur + exit_v), arm=i, to=j, defl_deg=math.degrees(defl), t1=t1, t2=t2, dT1=dT1, dT2=dT2, n_entry=len(pts), n_curve=len(cur), X=tuple(X))
    return np.array(pts + cur + exit_pts), np.array(wid + cw + exit_w), info


def band_poly(pts, wid):
    n = len(pts)
    tang = np.zeros((n, 2))
    tang[1:-1] = pts[2:] - pts[:-2]
    tang[0] = pts[1] - pts[0]
    tang[-1] = pts[-1] - pts[-2]
    tang /= (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9)
    nor = np.stack([-tang[:, 1], tang[:, 0]], 1)
    L = pts + nor * (wid[:, None] / 2)
    R = pts - nor * (wid[:, None] / 2)
    return Polygon(list(map(tuple, L)) + list(map(tuple, R[::-1]))).buffer(0)


def build_slips(scene, strips, main):
    """-> (asphalt incl. slip bands, islands [(poly, i, j)], paint polygons, info list)"""
    bands, infos, specs = [], [], []
    for i, a in enumerate(scene.arms):
        if not a.slip:
            continue
        sp = as_slip(a.slip)
        res = slip_path(scene, i, sp)
        if res is None:
            continue
        pts, wid, info = res
        bands.append(band_poly(pts, wid))
        infos.append(info)
        specs.append((i, sp, pts, wid, info))
    if not bands:
        return main, [], [], []
    union = unary_union([main] + bands)
    # islands = holes of the union that the main asphalt alone did not have
    def holes(g):
        out = []
        for p in (g.geoms if hasattr(g, "geoms") else [g]):
            if p.is_empty:
                continue
            for r in p.interiors:
                out.append(Polygon(r))
        return out
    h0 = unary_union(holes(main)) if holes(main) else Polygon()
    hs = unary_union(holes(union)) if holes(union) else Polygon()
    isl_all = hs.difference(h0.buffer(0.05)) if not h0.is_empty else hs
    islands = []
    for (i, sp, pts, wid, info) in specs:
        a = scene.arms[i]
        for p in (isl_all.geoms if hasattr(isl_all, "geoms") else [isl_all]):
            if p.is_empty or p.area < sp.min_island_area:
                continue
            ca = Point(*pts[len(pts) // 2])
            if p.distance(ca) < 4.0 + sp.w:
                r = min(sp.nose_r, 2.0)
                q = p.buffer(-r).buffer(r).buffer(r * 0.6).buffer(-r * 0.6) if r > 0.05 else p
                if not q.is_empty:
                    islands.append((q, i, info["to"]))
    asph = union
    if islands:
        asph = union.union(unary_union([p for p, _, _ in islands]).buffer(0.0)).difference(unary_union([p for p, _, _ in islands]))
    paint = []
    for (i, sp, pts, wid, info) in specs:
        n = len(pts)
        # crosswalk across the slip
        if sp.zebra:
            k = int(info["n_entry"] + sp.zebra_at * info["n_curve"])
            k = max(1, min(n - 2, k))
            t = pts[k + 1] - pts[k - 1]
            t = t / (np.linalg.norm(t) + 1e-9)
            nrm = np.array([-t[1], t[0]])
            half = wid[k] / 2
            x = -half + 0.3
            while x + sp.zebra_bar < half - 0.1:
                c = pts[k] + nrm * (x + sp.zebra_bar / 2)
                paint.append(Polygon([tuple(c - t * sp.zebra_len / 2 - nrm * sp.zebra_bar / 2), tuple(c + t * sp.zebra_len / 2 - nrm * sp.zebra_bar / 2),
                                      tuple(c + t * sp.zebra_len / 2 + nrm * sp.zebra_bar / 2), tuple(c - t * sp.zebra_len / 2 + nrm * sp.zebra_bar / 2)]))
                x += sp.zebra_bar + sp.zebra_gap
        # yield teeth / stop line before the merge
        if sp.control != "none":
            k = int(info["n_entry"] + sp.yield_at * info["n_curve"])
            k = max(1, min(n - 2, k))
            t = pts[k + 1] - pts[k - 1]
            t = t / (np.linalg.norm(t) + 1e-9)
            nrm = np.array([-t[1], t[0]])
            half = wid[k] / 2
            if sp.control == "stop":
                c = pts[k]
                paint.append(Polygon([tuple(c - nrm * half - t * 0.22), tuple(c + nrm * half - t * 0.22), tuple(c + nrm * half + t * 0.22), tuple(c - nrm * half + t * 0.22)]))
            else:
                x = -half + 0.2
                while x < half - 0.6:
                    c = pts[k] + nrm * x
                    paint.append(Polygon([tuple(c), tuple(c + nrm * 0.7), tuple(c + nrm * 0.35 + t * sp.teeth_len)]))
                    x += 1.0
    return asph, islands, paint, [dict(info, spec=sp.__dict__) for (_, sp, _, _, info) in specs]
