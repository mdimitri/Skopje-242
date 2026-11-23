"""Swept-path simulation of design vehicles along slip lanes + design-rule checks (TxDOT 13.9.1 / 13.10.1 / 4.10.5 values).
    run(scene, asphalt)  -> report dict (per slip: fit, spill area, clearance, rule checks)
    autofit(scene, vehicle) -> widens / enlarges slip lanes until the vehicle fits inside its band (the improve loop)."""
import math

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import slips as sl
from lanes import heading, taper_len, to_arm, widths

# length overall pieces (m): front overhang, wheelbase, rear overhang, width ; trailer: kingpin offset, kingpin-axle, rear overhang
VEH = {
    "P": dict(w=2.1, fo=0.9, wb=3.35, ro=1.5),
    "SU": dict(w=2.6, fo=1.2, wb=6.1, ro=1.8),
    "BUS": dict(w=2.6, fo=2.2, wb=7.6, ro=3.3),
    "WB-40": dict(w=2.6, fo=1.0, wb=3.7, ro=0.9, kp=0.0, tl=9.1, tro=1.4),
    "WB-62": dict(w=2.6, fo=1.0, wb=6.1, ro=0.8, kp=0.5, tl=12.2, tro=1.8),
}


def _resample(pts, step=0.25):
    pts = np.asarray(pts, float)
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    s = np.arange(0, d[-1], step)
    return np.stack([np.interp(s, d, pts[:, 0]), np.interp(s, d, pts[:, 1])], 1)


def rect_poly(a, b, w, ext_a=0.0, ext_b=0.0):
    """Rectangle of width w along a->b, extended beyond both ends."""
    u = b - a
    u = u / (np.linalg.norm(u) + 1e-9)
    n = np.array([-u[1], u[0]]) * w / 2
    a2, b2 = a - u * ext_a, b + u * ext_b
    return Polygon([tuple(a2 + n), tuple(b2 + n), tuple(b2 - n), tuple(a2 - n)])


def sweep(path, veh, lead=16.0, step=0.5, only_path=True):
    """Front axle follows `path`; returns (swept polygon, poses[(x,y,yaw)], parts per pose)."""
    v = VEH[veh]
    p = _resample(path, 0.25)
    d0 = p[1] - p[0]
    d0 /= np.linalg.norm(d0)
    d1 = p[-1] - p[-2]
    d1 /= np.linalg.norm(d1)
    lead_in = np.array([p[0] - d0 * (lead - k * 0.25) for k in range(int(lead / 0.25))])
    lead_out = np.array([p[-1] + d1 * (k * 0.25) for k in range(1, int(lead / 0.25))])
    path = np.vstack([lead_in, p, lead_out])
    wb = v["wb"]
    F = path[0]
    R = F - d0 * wb
    arti = "tl" in v
    if arti:
        K = R - d0 * v["kp"]
        T = K - d0 * v["tl"]
    polys, poses = [], []
    stride = int(step / 0.25)
    k0 = len(lead_in)
    k1 = len(lead_in) + len(p)
    for k in range(0, len(path), stride):
        F = path[k]
        dirv = F - R
        R = F - dirv / (np.linalg.norm(dirv) + 1e-9) * wb
        dirv = F - R
        dirv /= np.linalg.norm(dirv)
        body = rect_poly(R, F, v["w"], v["ro"], v["fo"])
        parts = [body]
        if arti:
            K = R - dirv * v["kp"]
            td = K - T
            T = K - td / (np.linalg.norm(td) + 1e-9) * v["tl"]
            parts.append(rect_poly(T, K, v["w"], v["tro"], 0.3))
        if only_path and not (k0 <= k < k1):
            continue
        polys.append(unary_union(parts))
        poses.append((float((F[0] + R[0]) / 2), float((F[1] + R[1]) / 2), math.atan2(dirv[1], dirv[0]), parts))
    return unary_union(polys), poses


def check_slip(scene, i, sp, info, pts, wid, asphalt, veh):
    band = sl.band_poly(pts, wid)
    swept, poses = sweep(info['veh_pts'], veh)
    ok_zone = asphalt.buffer(0.15)
    off_road = swept.difference(ok_zone).area
    spill_band = swept.difference(band.buffer(0.2)).area
    # island and kerb intrusion: swept area outside asphalt (islands and pavement are not asphalt)
    n_c = info["n_curve"]
    curve_len = float(np.sum(np.linalg.norm(np.diff(pts[info["n_entry"] - 1:info["n_entry"] + n_c], axis=0), axis=1)))
    k_z = int(info["n_entry"] + sp.zebra_at * n_c)
    k_y = int(info["n_entry"] + sp.yield_at * n_c)
    k_z, k_y = max(1, min(len(pts) - 2, k_z)), max(1, min(len(pts) - 2, k_y))
    zy = float(np.sum(np.linalg.norm(np.diff(pts[k_z:k_y + 1], axis=0), axis=1))) if k_y > k_z else 0.0
    b = scene.arms[info["to"]]
    t = pts[k_y + 1] - pts[k_y - 1]
    ang = math.degrees(abs(((math.atan2(t[1], t[0]) - heading(b, b.e + 15)) + math.pi) % (2 * math.pi) - math.pi))
    ang = min(ang, 180 - ang) if False else ang
    return dict(arm=i, vehicle=veh, fits_asphalt=off_road < 0.25, off_road_m2=round(off_road, 2), spill_outside_slip_m2=round(spill_band, 2),
                min_radius_m=sp.R, curve_len_m=round(curve_len, 1), zebra_to_yield_m=round(zy, 1), zebra_to_yield_ok=(zy >= 6.1 or not sp.zebra or sp.control == "none"),
                yield_approach_angle_deg=round(ang, 1), lane_w_ok=3.0 <= sp.w <= 5.6, turn_deg=round(info["defl_deg"], 1)), poses


def island_rules(islands):
    out = []
    for (g, i, j) in islands:
        mr = g.minimum_rotated_rectangle
        c = list(mr.exterior.coords)
        sides = sorted(math.hypot(c[k + 1][0] - c[k][0], c[k + 1][1] - c[k][1]) for k in range(4))
        out.append(dict(arm=i, area_m2=round(g.area, 1), long_side_m=round(sides[-1], 1), short_side_m=round(sides[0], 1), side_ok=sides[-1] >= 4.5, area_ok=g.area >= 6.0))
    return out


def taper_rules(scene):
    out = []
    for i, a in enumerate(scene.arms):
        for side, L in (("in", a.lanes_in), ("out", a.lanes_out)):
            for k, l in enumerate(L):
                for end, tl in (("far", l.t_far), ("near", l.t_near)):
                    if tl > 0:
                        need = taper_len(l.w, a.speed, "open" if (side == "in") == (end == "far") else "drop")
                        out.append(dict(arm=i, side=side, lane=k, end=end, taper_m=round(tl, 1), min_m=round(need, 1), ok=tl + 0.5 >= need))
    return out


def run(scene, asphalt, islands, vehicle="SU"):
    import slips as _s
    rep = dict(slips=[], islands=island_rules(islands), tapers=taper_rules(scene))
    poses_all = []
    for info in getattr(scene, "slip_info", []):
        i = info["arm"]
        sp = _s.as_slip(scene.arms[i].slip)
        res = _s.slip_path(scene, i, sp)
        if res is None:
            continue
        pts, wid, inf = res
        veh = getattr(sp, "vehicle", None) or vehicle
        r, poses = check_slip(scene, i, sp, inf, pts, wid, asphalt, veh)
        rep["slips"].append(r)
        poses_all.append((veh, poses))
    rep["all_ok"] = all(r["fits_asphalt"] and r["zebra_to_yield_ok"] and r["lane_w_ok"] for r in rep["slips"]) and all(x["side_ok"] for x in rep["islands"])
    return rep, poses_all


def autofit(scene, vehicle="SU", tol=0.25, max_iter=40):
    """Improve loop: enlarge the slip band (width, then radius) until the design vehicle's swept path sits inside its lane."""
    import slips as _s
    log = []
    for i, a in enumerate(scene.arms):
        if not a.slip:
            continue
        sp = _s.as_slip(a.slip)
        spill, it = 0.0, 0
        for it in range(max_iter):
            res = _s.slip_path(scene, i, sp)
            if res is None:
                break
            pts, wid, inf = res
            import engine as _e
            band = _s.band_poly(pts, wid)
            j = inf["to"]
            ok = unary_union([band.buffer(0.2), _e.strip_poly(scene.arms[i]), _e.strip_poly(scene.arms[j])])
            swept, _ = sweep(inf['veh_pts'], vehicle)
            spill = swept.difference(ok).area
            if spill <= tol:
                break
            if sp.w < 5.2:
                sp.w = round(sp.w + 0.25, 2)
            else:
                sp.R = round(sp.R + 1.5, 2)
        log.append(dict(arm=i, vehicle=vehicle, w=sp.w, R=sp.R, iterations=it, spill=round(spill, 2)))
        a.slip = sp
    return log
