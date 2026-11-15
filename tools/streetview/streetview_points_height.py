"""Plan EXTRA Street View capture points that help the photogrammetry fitter get building heights and roofs right.

Complements an existing points file (same JSON format, read by streetview_capture.py --batch).  For every building it
looks for camera spots on streets / pedestrian ways / squares from which
  * "full"   - one facade is seen frontally with its WHOLE height and the roofline in frame (pitch and fov are computed
               from the estimated height and the distance, so the top edge and the foot are both inside the picture),
  * "corner" - a corner is seen obliquely, so two facades and the roof edges that join them are in one picture
               (this is what makes roofs connect to the facades),
  * "far"    - tall buildings from 1.5-2.5x their height away (lower buildings in between don't block the roofline),
  * "back"   - the opposite side of a big building, from a different street.
The line of sight is checked against the HEIGHT of intervening buildings (a low house does not hide a tall roofline).
Facades / cameras that the existing file already covers are penalised, so the new points repeat the old ones as little as
possible.  Output keys are exactly those of the existing file.

    python3 tools/streetview/streetview_points_height.py --src data/osm --existing tools/streetview/points_skopje_thorough.json \
        --out points_skopje_height_10k.json --n 10000
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from geo import LAT0, LON0, M_LAT, M_LON, project

CENTER = (41.9843691, 21.4768374)
CAM_H = 2.5                         # Street View camera height above ground (m)
CELL = 40.0
DRIVE = {"residential", "tertiary", "secondary", "unclassified", "living_street", "tertiary_link", "secondary_link", "primary",
         "primary_link", "trunk", "trunk_link", "service", "pedestrian", "road"}
BIG_TYPES = {"apartments", "commercial", "retail", "industrial", "office", "public", "school", "hospital", "university", "warehouse"}
SAMPLE_STEP = 9.0                   # camera candidates along every street every N metres


def unproject(x, y):
    return (LAT0 - y / M_LAT, LON0 + x / M_LON)


def ccw_sign(ring):
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def seg_t(a, b, c, d):
    """parameter t along a->b where it crosses c->d, or None"""
    rx, ry, sx, sy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if den == 0:
        return None
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return t if 0 <= t <= 1 and 0 <= u <= 1 else None


def height_of(tags, area):
    try:
        if tags.get("height"):
            return max(3.0, min(150.0, float(str(tags["height"]).split()[0].replace(",", "."))))
        if tags.get("building:levels"):
            return max(3.0, min(150.0, float(str(tags["building:levels"]).replace(",", ".")) * 3.0 + 1.0))
    except ValueError:
        pass
    t = tags.get("building")
    if t == "apartments":
        return 16.0
    if t in ("office", "hospital", "university"):
        return 14.0
    if t in ("commercial", "retail", "public", "school"):
        return 10.0
    if t in ("industrial", "warehouse", "garage", "garages", "shed", "roof"):
        return 7.0
    return 11.0 if area > 900 else 8.0 if area > 200 else 6.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/osm")
    ap.add_argument("--existing", default="tools/streetview/points_skopje_thorough.json")
    ap.add_argument("--out", default="points_skopje_height_10k.json")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--min-area", type=float, default=45.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    # ---- existing coverage ------------------------------------------------------------------------------------------
    old = json.load(open(a.existing))["points"]
    old_by_b, old_cams = {}, {}
    for p in old:
        old_by_b.setdefault(p["osm_building_id"], []).append(p)
        old_cams.setdefault((int(p["lat"] * 6000), int(p["lon"] * 6000)), []).append((p["lat"], p["lon"], p["heading"]))
    print("existing points:", len(old), "buildings:", len(old_by_b))

    # ---- buildings --------------------------------------------------------------------------------------------------
    blds = []
    for e in json.load(open(os.path.join(a.src, "buildings.json")))["elements"]:
        g = e.get("geometry")
        if e["type"] != "way" or not g or len(g) < 4:
            continue
        ring = [project(p["lat"], p["lon"]) for p in g]
        if ring[0] != ring[-1]:
            continue
        ar = ccw_sign(ring)
        if abs(ar) < a.min_area:
            continue
        t = e.get("tags", {})
        if t.get("building") in ("shed", "roof", "garage", "garages", "carport", "kiosk", "hut", "cabin", "service", "greenhouse") and abs(ar) < 120:
            continue
        mx = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        my = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
        blds.append(dict(id=e["id"], ring=ring, area=abs(ar), ccw=ar > 0, c=(mx, my), tag=t.get("building"), h=height_of(t, abs(ar))))
    print("buildings:", len(blds))
    grid = {}
    for i, b in enumerate(blds):
        xs = [p[0] for p in b["ring"]]; ys = [p[1] for p in b["ring"]]
        b["bb"] = (min(xs), min(ys), max(xs), max(ys))
        for gx in range(int(b["bb"][0] // CELL), int(b["bb"][2] // CELL) + 1):
            for gy in range(int(b["bb"][1] // CELL), int(b["bb"][3] // CELL) + 1):
                grid.setdefault((gx, gy), []).append(i)

    def visible(cam, tgt, th, own):
        """Is the point tgt (at height th) seen from cam (CAM_H high)?  A building in between blocks only if it is taller
        than the sight line where it crosses it."""
        seen = set()
        for gx in range(int(min(cam[0], tgt[0]) // CELL), int(max(cam[0], tgt[0]) // CELL) + 1):
            for gy in range(int(min(cam[1], tgt[1]) // CELL), int(max(cam[1], tgt[1]) // CELL) + 1):
                for j in grid.get((gx, gy), ()):
                    if j == own or j in seen:
                        continue
                    seen.add(j)
                    bj = blds[j]
                    r = bj["ring"]
                    ts = [seg_t(cam, tgt, r[k], r[k + 1]) for k in range(len(r) - 1)]
                    ts = [t for t in ts if t is not None]
                    if not ts:
                        continue
                    t_exit = max(ts)                     # the sight line leaves the blocker here: it must clear it there
                    if bj["h"] > CAM_H + t_exit * (th - CAM_H) - 0.3:
                        return False
        return True

    # ---- camera spots: street samples + pedestrian squares ----------------------------------------------------------
    cams = []
    for e in json.load(open(os.path.join(a.src, "roads.json")))["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("highway") not in DRIVE or t.get("tunnel") or t.get("access") in ("private", "no"):
            continue
        if t.get("highway") == "service" and t.get("service") in ("driveway", "parking_aisle", "drive-through"):
            continue
        pts = [project(p["lat"], p["lon"]) for p in e.get("geometry", [])]
        carry = 0.0
        for p, q in zip(pts, pts[1:]):
            L = math.hypot(q[0] - p[0], q[1] - p[1])
            s = carry
            while s < L:
                cams.append((p[0] + (q[0] - p[0]) * s / L, p[1] + (q[1] - p[1]) * s / L, e["id"], t.get("name", ""), bool(t.get("bridge"))))
                s += SAMPLE_STEP
            carry = s - L
    for e in json.load(open(os.path.join(a.src, "areas.json")))["elements"]:
        t = e.get("tags", {})
        if (t.get("highway") == "pedestrian" or t.get("place") == "square") and e.get("geometry"):
            ring = [project(p["lat"], p["lon"]) for p in e["geometry"]]
            x0, x1 = min(p[0] for p in ring), max(p[0] for p in ring)
            y0, y1 = min(p[1] for p in ring), max(p[1] for p in ring)
            x = x0
            while x <= x1:
                y = y0
                while y <= y1:
                    inside = False
                    for k in range(len(ring) - 1):
                        (ax, ay), (bx, by) = ring[k], ring[k + 1]
                        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                            inside = not inside
                    if inside:
                        cams.append((x, y, e["id"], t.get("name", "square"), False))
                    y += 14.0
                x += 14.0
    print("camera spots:", len(cams))
    cgrid = {}
    for c in cams:
        cgrid.setdefault((int(c[0] // CELL), int(c[1] // CELL)), []).append(c)

    def inside_any(pt):
        for j in grid.get((int(pt[0] // CELL), int(pt[1] // CELL)), ()):
            bj = blds[j]
            if bj["bb"][0] <= pt[0] <= bj["bb"][2] and bj["bb"][1] <= pt[1] <= bj["bb"][3]:
                r = bj["ring"]; ins = False
                for k in range(len(r) - 1):
                    if (r[k][1] > pt[1]) != (r[k + 1][1] > pt[1]) and pt[0] < (r[k + 1][0] - r[k][0]) * (pt[1] - r[k][1]) / (r[k + 1][1] - r[k][1]) + r[k][0]:
                        ins = not ins
                if ins:
                    return True
        return False

    def old_near(cam, hd, rad=7.0):
        lat, lon = unproject(*cam)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for (la, lo, h2) in old_cams.get((int(lat * 6000) + dx, int(lon * 6000) + dy), ()):
                    if math.hypot((la - lat) * M_LAT, (lo - lon) * M_LON) < rad and abs((h2 - hd + 180) % 360 - 180) < 25:
                        return True
        return False

    def cams_near(pt, dmin, dmax):
        r = int(dmax // CELL) + 1
        gx, gy = int(pt[0] // CELL), int(pt[1] // CELL)
        for ix in range(gx - r, gx + r + 1):
            for iy in range(gy - r, gy + r + 1):
                for c in cgrid.get((ix, iy), ()):
                    d = math.hypot(c[0] - pt[0], c[1] - pt[1])
                    if dmin <= d <= dmax:
                        yield c, d

    def frame(H, d, width):
        """pitch + vertical fov (deg) so the roofline (H+1.5) and the foot are inside, and `width` m fit horizontally"""
        top = math.degrees(math.atan((H + 1.5 - CAM_H) / d))
        bot = -math.degrees(math.atan(CAM_H / d))
        pitch = (top + bot) / 2
        vf = (top - bot) * 1.2 + 6
        hneed = 2 * math.degrees(math.atan(width * 0.6 / d))
        vneed = 2 * math.degrees(math.atan(math.tan(math.radians(hneed / 2)) * 9 / 16))
        vf = max(vf, vneed, 40)
        if vf > 100 or pitch > 50:
            return None
        return round(max(-10, min(50, pitch)), 1), round(vf)

    # ---- candidates per building ------------------------------------------------------------------------------------
    cands = []
    for i, b in enumerate(blds):
        r, H = b["ring"], b["h"]
        ex = old_by_b.get(b["id"], [])
        n_old = len(ex)
        wgt = (min(max(H, 4), 60) / 6.0) ** 0.8 * (b["area"] / 150.0) ** 0.25 / (1 + 0.6 * n_old)
        big = b["area"] >= 450 or H >= 14 or b["tag"] in BIG_TYPES
        edges = []
        for k in range(len(r) - 1):
            p0, p1 = r[k], r[k + 1]
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < 5:
                continue
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            nx, ny = (uy, -ux) if b["ccw"] else (-uy, ux)
            edges.append(dict(k=k, p0=p0, p1=p1, L=L, n=(nx, ny), m=((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)))
        edges.sort(key=lambda z: -z["L"])
        edges = edges[:6]
        found = []

        def try_cam(kind, aim, edge, n_vec, dmin, dmax, mincos, need_two=None):
            scored = []
            for c, d in cams_near(aim, dmin, dmax):
                vx, vy = c[0] - aim[0], c[1] - aim[1]
                cosang = (vx * n_vec[0] + vy * n_vec[1]) / d
                if cosang < mincos:
                    continue
                if need_two and (vx * need_two[0] + vy * need_two[1]) / d < 0.25:
                    continue
                scored.append((cosang / (1 + abs(d - (dmin + dmax) / 2) / 25) + (0.15 if c[4] else 0.0), c, d, cosang))
            scored.sort(key=lambda z: -z[0])
            tries = 0
            for sc, c, d, cosang in scored:
                if tries >= 5:
                    break
                cam = (c[0], c[1])
                hd = (math.degrees(math.atan2(aim[0] - cam[0], -(aim[1] - cam[1]))) + 360) % 360
                if old_near(cam, hd) or inside_any(cam):
                    continue
                tries += 1
                tgt = (aim[0] + n_vec[0] * 0.3, aim[1] + n_vec[1] * 0.3)
                if not (visible(cam, tgt, H, i) and visible(cam, tgt, H * 0.5, i)):
                    continue
                fr = frame(H, d, edge["L"] if kind != "corner" else min(edge["L"], 14.0) * 1.6)
                if fr is None:
                    continue
                same_edge = any(abs(q["facade_length_m"] - edge["L"]) < 0.2 for q in ex)
                found.append(dict(kind=kind, i=i, cam=cam, aim=aim, edge=edge, d=d, hd=hd, pitch=fr[0], fov=fr[1], c=c,
                                  val=wgt * cosang * (0.5 if same_edge else 1.0) * {"full": 1.0, "corner": 1.1, "far": 0.9, "back": 0.75}[kind],
                                  nrm=n_vec))
                return

        d_lo = max(14.0, 0.8 * H)
        d_hi = min(70.0, max(32.0, 2.2 * H))
        # full: best-scoring facades, frontal
        for e in edges[:3]:
            try_cam("full", e["m"], e, e["n"], d_lo, d_hi, 0.75)
        # corner: vertex between two long edges, camera on the bisector side
        for k in range(len(edges)):
            for l in range(len(edges)):
                e1, e2 = edges[k], edges[l]
                if k >= l:
                    continue
                for v in (e1["p0"], e1["p1"]):
                    if math.hypot(v[0] - e2["p0"][0], v[1] - e2["p0"][1]) < 0.3 or math.hypot(v[0] - e2["p1"][0], v[1] - e2["p1"][1]) < 0.3:
                        bx, by = e1["n"][0] + e2["n"][0], e1["n"][1] + e2["n"][1]
                        bl = math.hypot(bx, by)
                        if bl < 0.5:        # nearly flat wall: not a real corner
                            continue
                        try_cam("corner", v, e1, (bx / bl, by / bl), d_lo, d_hi, 0.6, need_two=e2["n"])
        # far: tall buildings from further away
        if H >= 15:
            e = edges[0] if edges else None
            if e:
                try_cam("far", e["m"], e, e["n"], max(1.5 * H, 28.0), min(2.6 * H, 95.0), 0.6)
        # back: big building, side opposite to the facade the first file used
        if big and edges:
            ref = ex[0]["facade_mid"] if ex else None
            for e in edges:
                if ref is None:
                    break
                rm = project(ref["lat"], ref["lon"])
                refn = (rm[0] - b["c"][0], rm[1] - b["c"][1])
                rl = math.hypot(*refn) or 1
                if (e["n"][0] * refn[0] + e["n"][1] * refn[1]) / rl < -0.3:
                    try_cam("back", e["m"], e, e["n"], d_lo, d_hi, 0.7)
                    break
        # keep the best few per building, tier by size; successive views are worth less
        found.sort(key=lambda z: -z["val"])
        cap = 4 if H >= 24 else 3 if (big or H >= 12) else 2
        keep = []
        for f in found:
            if len(keep) >= cap:
                break
            if all(f["kind"] != g["kind"] or math.hypot(f["cam"][0] - g["cam"][0], f["cam"][1] - g["cam"][1]) > 15 for g in keep):
                if all(math.hypot(f["cam"][0] - g["cam"][0], f["cam"][1] - g["cam"][1]) > 5 or abs((f["hd"] - g["hd"] + 180) % 360 - 180) > 25 for g in keep):
                    f["val"] *= 0.7 ** len(keep)
                    keep.append(f)
        cands.extend(keep)
        if i % 2000 == 0:
            print(f"  {i}/{len(blds)} buildings, candidates {len(cands)}", flush=True)

    print("candidates:", len(cands), "buildings with a candidate:", len({c["i"] for c in cands}))
    import collections
    print("by kind:", collections.Counter(c["kind"] for c in cands))
    # quotas so one kind does not swamp the file: corner views are the most numerous candidates
    share = {"full": 0.42, "corner": 0.46, "far": 1.0, "back": 1.0}
    cands.sort(key=lambda z: -z["val"])
    chosen, occ, cnt = [], {}, collections.Counter()

    def pick(f):
        key = (int(f["cam"][0] // 12), int(f["cam"][1] // 12))
        for ix in (-1, 0, 1):
            for iy in (-1, 0, 1):
                for g in occ.get((key[0] + ix, key[1] + iy), ()):
                    if math.hypot(f["cam"][0] - g["cam"][0], f["cam"][1] - g["cam"][1]) < 6 and abs((f["hd"] - g["hd"] + 180) % 360 - 180) < 20:
                        return False
        chosen.append(f)
        cnt[f["kind"]] += 1
        occ.setdefault(key, []).append(f)
        return True
    for limit in (share, {k: 1.0 for k in share}):               # second pass tops up with whatever is left
        for f in cands:
            if len(chosen) >= a.n:
                break
            if f in chosen or cnt[f["kind"]] >= limit[f["kind"]] * a.n:
                continue
            pick(f)
    chosen.sort(key=lambda z: math.hypot(*z["cam"]))                       # capture order: centre outwards, like the first file
    out = []
    for n, f in enumerate(chosen):
        b = blds[f["i"]]
        e = f["edge"]
        lat, lon = unproject(*f["cam"])
        e0, e1, mm, cc = unproject(*e["p0"]), unproject(*e["p1"]), unproject(*f["aim"]), unproject(*b["c"])
        out.append({
            "idx": n, "dist_from_center_m": round(math.hypot(*f["cam"])), "view": {"full": 1, "corner": 3, "far": 4, "back": 2}[f["kind"]],
            "lat": round(lat, 7), "lon": round(lon, 7), "heading": round(f["hd"], 1), "pitch": f["pitch"], "fov": f["fov"],
            "osm_building_id": b["id"], "building_type": b["tag"], "est_height_m": round(b["h"], 1), "footprint_m2": round(b["area"]),
            "facade_edge": [{"lat": round(e0[0], 7), "lon": round(e0[1], 7)}, {"lat": round(e1[0], 7), "lon": round(e1[1], 7)}],
            "facade_length_m": round(e["L"], 1), "facade_mid": {"lat": round(mm[0], 7), "lon": round(mm[1], 7)},
            "building_centroid": {"lat": round(cc[0], 7), "lon": round(cc[1], 7)},
            "camera_to_facade_m": round(f["d"], 1), "osm_road_id": f["c"][2], "road_name": f["c"][3],
        })
    kinds = collections.Counter(f["kind"] for f in chosen)
    print("chosen", len(out), kinds, "buildings", len({f["i"] for f in chosen}),
          "new buildings (not in old file):", len({blds[f["i"]]["id"] for f in chosen} - set(old_by_b)))
    json.dump({"area": "whole map, height/roof pass", "center": {"lat": CENTER[0], "lon": CENTER[1]}, "radius_m": 1e9,
               "heading_note": "degrees clockwise from north, camera looks at facade_mid; view 1=full height frontal, 2=back side, 3=corner (two facades + roof edge), 4=far view of a tall building",
               "points": out}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print("wrote", len(out), "points ->", a.out)


if __name__ == "__main__":
    main()
