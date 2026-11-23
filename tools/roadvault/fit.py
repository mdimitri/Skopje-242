"""Rule-based clean-up of the raw OSM roads of one site before they go through the vault engine (see FITTING_RULES.md).
Each rule is deterministic and logged so a site's fit can be audited.  Input/outputs: lists of road dicts (pts in metres, x east, y south)."""
import math
import numpy as np

_B = {}


def _bld():
    if "t" not in _B:
        import sat_overlay as S, pickle, os
        d = pickle.load(open(os.environ.get("ROADS_PKL", "/mnt/project-files/road-restyle-cs2/data/roads_raw.pkl"), "rb"))
        c = np.array([np.mean(f, axis=0) for f, h in d["buildings"]])
        _B["t"] = c
    return _B["t"]


def _resample(p, step=3.0):
    p = np.asarray(p, float)
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(p, axis=0).T))]
    s = np.arange(0, d[-1], step)
    s = np.r_[s, d[-1]]
    return np.c_[np.interp(s, d, p[:, 0]), np.interp(s, d, p[:, 1])]


def fit(roads, log, cx, cy, half):
    from corridor import hermite_pts
    out = []
    drive_nonlink = [r for r in roads if r["cls"] in ("tertiary", "secondary", "primary", "trunk", "motorway", "residential", "unclassified")]
    tree = _bld()
    for r in roads:
        r = dict(r)
        pts = np.array(r["pts"], float)
        # F1 lane floor: width at least lanes x 3.25 m
        ln = r.get("lanes")
        if r["cls"] in ("tertiary", "secondary", "primary", "trunk", "motorway") or r["cls"].endswith("_link"):
            if ln and (r.get("w") or 0) < ln * 3.25 - 0.3:
                log.append(f"F1 lanes: {r['cls']} {r.get('w')} m -> {ln*3.25:.1f} m for {ln} lanes")
                r["w"] = ln * 3.25
        # F2 unpaved demotion: low-class way far from every building
        if r["cls"] in ("service", "unclassified", "track") and len(pts) > 1:
            sp = _resample(pts, 6.0)
            sp = sp[(abs(sp[:, 0] - cx) < half) & (abs(sp[:, 1] - cy) < half)]
            if len(sp) < 4:
                out.append(r)
                continue
            dd = np.hypot(sp[:, None, 0] - tree[None, :, 0], sp[:, None, 1] - tree[None, :, 1]).min(axis=1)
            if (dd < 20).mean() < 0.12 and not r.get("bridge") and not r.get("layer"):
                if r["cls"] != "track":
                    log.append(f"F2 unpaved: {r['cls']} ({len(sp)*6:.0f} m in frame, no buildings within 20 m) -> track")
                r["cls"] = "track"
                r["w"] = 3.2
        # F3 link ends: tangent join to the parent road
        if r["cls"].endswith("_link") and len(pts) >= 2:
            for end in (0, 1):
                e = pts[-1] if end else pts[0]
                best = None
                for q in drive_nonlink:
                    qp = np.array(q["pts"], float)
                    dd = np.hypot(qp[:, 0] - e[0], qp[:, 1] - e[1])
                    i = int(dd.argmin())
                    if dd[i] < 8 and (best is None or dd[i] < best[0]):
                        a, b = qp[max(i - 1, 0)], qp[min(i + 1, len(qp) - 1)]
                        v = (b - a) / (np.hypot(*(b - a)) or 1)
                        best = (dd[i], v)
                if best is None:
                    continue
                rp = _resample(pts, 3.0)
                if end == 0:
                    rp = rp[::-1]
                if len(rp) < 22:
                    continue
                k = max(1, len(rp) - 1 - 20)
                v_l = rp[-1] - rp[-8]
                v_l /= np.hypot(*v_l) or 1
                v_p = best[1] if np.dot(best[1], v_l) >= 0 else -best[1]
                ang = math.degrees(math.acos(max(-1, min(1, float(np.dot(v_l, v_p))))))
                if ang < 12 or ang > 80:
                    continue
                p0 = rp[k]
                h0 = math.atan2(*(rp[k] - rp[k - 3])[::-1])
                h1 = math.atan2(v_p[1], v_p[0])
                hp = hermite_pts(p0, h0, rp[-1], h1, n=24)
                new = np.vstack([rp[:k], hp])
                pts = new[::-1] if end == 0 else new
                log.append(f"F3 link end {'start' if end == 0 else 'end'}: {ang:.0f} deg to parent -> tangent taper over 60 m")
            r["pts"] = [tuple(p) for p in pts]
        # F4 deck ramps 90 m
        if r.get("bridge") or (r.get("layer") or 0) > 0:
            r["_rl"] = 90.0
        out.append(r)
    return out
