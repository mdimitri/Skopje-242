"""Plan Street View capture points for the buildings of Novo Lisice (Skopje).

Reads the Overpass dumps the world build uses (buildings.json, roads.json in --src), and for every building finds a
camera spot on a nearby drivable OSM road from which one of its facades is visible (road on the outward side of the
facade, no other building in the line of sight). Writes a JSON list: lat, lon, heading (deg from north), pitch, fov,
plus the OSM building id, the facade edge (lat/lon of both ends) and the facade midpoint / building centroid so the
returned JPEGs can be matched back to buildings.

    python3 tools/streetview/streetview_points.py --src data/osm_real --out tools/streetview/points_novo_lisice.json --n 100
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from geo import LAT0, LON0, M_LAT, M_LON, project

CENTER = (41.9843691, 21.4768374)   # OSM place=suburb "Ново Лисиче" (node 1929289631)
RADIUS = 1100.0                     # m around it
DRIVABLE = {"residential", "tertiary", "secondary", "unclassified", "living_street", "tertiary_link", "secondary_link", "primary", "service"}
CELL = 40.0


def unproject(x, y):
    return (LAT0 - y / M_LAT, LON0 + x / M_LON)


def seg_hit(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def area_sign(ring):
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/osm_real")
    ap.add_argument("--out", default="tools/streetview/points_novo_lisice.json")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--big-m2", type=float, default=450, help="buildings this large also get a second view (0 = off)")
    ap.add_argument("--diverse", action="store_true", help="spread picks over building types/sizes first")
    ap.add_argument("--whole", action="store_true", help="whole world box: all big buildings (2 views for the largest), houses thinned by distance from the centre")
    ap.add_argument("--min-sep", type=float, default=45.0, help="min distance between camera points (m)")
    a = ap.parse_args()
    cx, cy = project(*CENTER)
    radius = 1e9 if a.whole else RADIUS
    if a.whole:
        cx = cy = 0.0

    blds = []
    for e in json.load(open(os.path.join(a.src, "buildings.json")))["elements"]:
        g = e.get("geometry")
        if e["type"] != "way" or not g or len(g) < 4:
            continue
        ring = [project(p["lat"], p["lon"]) for p in g]
        if ring[0] != ring[-1]:
            continue
        mx = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        my = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
        if math.hypot(mx - cx, my - cy) > radius:
            continue
        ar = area_sign(ring)
        if abs(ar) < 60:
            continue
        t = e.get("tags", {})
        try:
            lv = float(t.get("building:levels", 0)) or 2
        except ValueError:
            lv = 2
        blds.append(dict(id=e["id"], ring=ring, area=abs(ar), ccw=ar > 0, c=(mx, my), h=min(lv * 3.0, 30.0), tag=t.get("building"), big=(abs(ar) >= 450 or lv >= 5 or t.get("building") in ("apartments", "commercial", "retail", "industrial", "office", "public", "school", "hospital", "university", "warehouse"))))
    grid = {}
    for i, b in enumerate(blds):
        xs = [p[0] for p in b["ring"]]; ys = [p[1] for p in b["ring"]]
        for gx in range(int(min(xs) // CELL), int(max(xs) // CELL) + 1):
            for gy in range(int(min(ys) // CELL), int(max(ys) // CELL) + 1):
                grid.setdefault((gx, gy), []).append(i)

    segs = []
    for e in json.load(open(os.path.join(a.src, "roads.json")))["elements"]:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("highway") not in DRIVABLE or t.get("tunnel") or t.get("access") == "private":
            continue
        if t.get("highway") == "service" and t.get("service") in ("driveway", "parking_aisle", "drive-through"):
            continue
        pts = [project(p["lat"], p["lon"]) for p in e.get("geometry", [])]
        for p, q in zip(pts, pts[1:]):
            if min(math.hypot(p[0] - cx, p[1] - cy), math.hypot(q[0] - cx, q[1] - cy)) < radius + 60:
                segs.append((p, q, e["id"], t.get("name", "")))
    print(f"buildings {len(blds)}, road segments {len(segs)}")
    sgrid = {}
    for sg in segs:
        (p, q) = sg[0], sg[1]
        for gx in range(int((min(p[0], q[0]) - 45) // CELL), int((max(p[0], q[0]) + 45) // CELL) + 1):
            for gy in range(int((min(p[1], q[1]) - 45) // CELL), int((max(p[1], q[1]) + 45) // CELL) + 1):
                sgrid.setdefault((gx, gy), []).append(sg)

    def blocked(p, m, own):
        for gx in range(int(min(p[0], m[0]) // CELL), int(max(p[0], m[0]) // CELL) + 1):
            for gy in range(int(min(p[1], m[1]) // CELL), int(max(p[1], m[1]) // CELL) + 1):
                for j in grid.get((gx, gy), ()):
                    if j == own:
                        continue
                    r = blds[j]["ring"]
                    if any(seg_hit(p, m, r[k], r[k + 1]) for k in range(len(r) - 1)):
                        return True
        return False

    cands = []
    for i, b in enumerate(blds):
        r = b["ring"]
        per_edge = []
        for k in range(len(r) - 1):
            p0, p1 = r[k], r[k + 1]
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < 6:
                continue
            ex, ey = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            # outward normal in the (x east, y south) frame; ring orientation computed in the same frame
            nx, ny = (ey, -ex) if b["ccw"] else (-ey, ex)
            m = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            best = None
            near = sgrid.get((int(m[0] // CELL), int(m[1] // CELL)), ())
            for p, q, rid, name in near:
                dx, dy = q[0] - p[0], q[1] - p[1]
                l2 = dx * dx + dy * dy
                if l2 == 0:
                    continue
                s = max(0, min(1, ((m[0] - p[0]) * dx + (m[1] - p[1]) * dy) / l2))
                c = (p[0] + s * dx, p[1] + s * dy)
                vx, vy = c[0] - m[0], c[1] - m[1]
                d = math.hypot(vx, vy)
                if d < 10 or d > 40:
                    continue
                cosang = (vx * nx + vy * ny) / d
                if cosang < 0.6:
                    continue
                if blocked(c, m, i):
                    continue
                # the sight line must not clip this building's other edges before the facade
                if any(seg_hit(c, (m[0] + nx * 0.3, m[1] + ny * 0.3), r[j], r[j + 1]) for j in range(len(r) - 1)):
                    continue
                score = L * b["h"] * cosang / (1 + d / 20)
                if best is None or score > best["score"]:
                    best = dict(score=score, i=i, c=c, m=m, p0=p0, p1=p1, L=L, d=d, rid=rid, name=name, n=(nx, ny))
            if best:
                best["score"] *= math.sqrt(b["area"])
                per_edge.append(best)
        per_edge.sort(key=lambda z: -z["score"])
        if per_edge:
            per_edge[0]["view"] = 1
            cands.append(per_edge[0])
            if b["area"] >= a.big_m2 or b["big"]:       # large building: a second view from a clearly different facade direction
                for z in per_edge[1:]:
                    if z["n"][0] * per_edge[0]["n"][0] + z["n"][1] * per_edge[0]["n"][1] < 0.7:
                        z["view"] = 2
                        z["score"] *= 0.8
                        cands.append(z)
                        break
    cands.sort(key=lambda z: -z["score"])
    print("buildings with a viewable facade:", len(cands))

    def bucket(cd):
        b = blds[cd["i"]]
        return (b["tag"], int(b["h"] // 6), int(math.log2(b["area"] / 60)))
    if a.diverse:                       # damp the score of buckets that are already represented
        cnt = {}
        for cd in cands:
            cnt[bucket(cd)] = cnt.get(bucket(cd), 0) + 1
        seen = {}
        for cd in sorted(cands, key=lambda z: -z["score"]):
            k = bucket(cd)
            cd["score"] /= (1 + 0.5 * seen.get(k, 0)) if cd.get("view") == 1 else 1
            seen[k] = seen.get(k, 0) + 1
        cands.sort(key=lambda z: -z["score"])
    chosen = []
    if a.whole:
        occ = {}
        def free(cd, sp):
            gx, gy, r = int(cd["c"][0] // 160), int(cd["c"][1] // 160), int(sp // 160) + 1
            return all(math.hypot(cd["c"][0] - o["c"][0], cd["c"][1] - o["c"][1]) >= sp
                       for ix in range(gx - r, gx + r + 1) for iy in range(gy - r, gy + r + 1) for o in occ.get((ix, iy), ()))
        def take(cd):
            chosen.append(cd); occ.setdefault((int(cd["c"][0] // 160), int(cd["c"][1] // 160)), []).append(cd)
        for cd in cands:                      # big / distinctive buildings first, close spacing
            if blds[cd["i"]]["big"] and free(cd, 18):
                take(cd)
        nb = len(chosen)
        for cd in cands:                      # houses: one sample per ~40 m in town, ~70 m further out, skipping spots near big-building cameras
            if blds[cd["i"]]["big"] or cd.get("view") != 1:
                continue
            d = math.hypot(*cd["c"])
            if free(cd, 40 if d < 3000 else 70):
                take(cd)
        print("big-building images:", nb, " house images:", len(chosen) - nb)
        a.n = 0
    sep = a.min_sep
    while len(chosen) < a.n and sep >= 15:
        for cd in cands:
            if len(chosen) >= a.n:
                break
            if cd in chosen:
                continue
            if all(math.hypot(cd["c"][0] - o["c"][0], cd["c"][1] - o["c"][1]) >= sep for o in chosen):
                chosen.append(cd)
        sep -= 10
    if a.whole:                           # capture order: from the centre outwards
        chosen.sort(key=lambda z: math.hypot(*z["c"]))
    out = []
    for n, cd in enumerate(chosen):
        b = blds[cd["i"]]
        hd = (math.degrees(math.atan2(cd["m"][0] - cd["c"][0], -(cd["m"][1] - cd["c"][1]))) + 360) % 360
        pitch = round(min(25.0, math.degrees(math.atan2(b["h"] / 2 - 2.5, cd["d"]))), 1)
        fov = round(max(40, min(90, 2 * math.degrees(math.atan(cd["L"] * 0.6 / cd["d"])))))
        lat, lon = unproject(*cd["c"])
        e0, e1, mm, cc = unproject(*cd["p0"]), unproject(*cd["p1"]), unproject(*cd["m"]), unproject(*b["c"])
        out.append({
            "idx": n, "dist_from_center_m": round(math.hypot(*cd["c"])), "view": cd["view"], "lat": round(lat, 7), "lon": round(lon, 7), "heading": round(hd, 1), "pitch": pitch, "fov": fov,
            "osm_building_id": b["id"], "building_type": b["tag"], "est_height_m": b["h"], "footprint_m2": round(b["area"]),
            "facade_edge": [{"lat": round(e0[0], 7), "lon": round(e0[1], 7)}, {"lat": round(e1[0], 7), "lon": round(e1[1], 7)}],
            "facade_length_m": round(cd["L"], 1), "facade_mid": {"lat": round(mm[0], 7), "lon": round(mm[1], 7)},
            "building_centroid": {"lat": round(cc[0], 7), "lon": round(cc[1], 7)},
            "camera_to_facade_m": round(cd["d"], 1), "osm_road_id": cd["rid"], "road_name": cd["name"],
        })
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump({"area": "whole map" if a.whole else "Novo Lisice, Skopje", "center": {"lat": CENTER[0], "lon": CENTER[1]}, "radius_m": RADIUS,
               "heading_note": "degrees clockwise from north, camera looks at facade_mid", "points": out},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    print("wrote", len(out), "points ->", a.out)


if __name__ == "__main__":
    main()
