"""Round 30: petrol stations and car washes, placed where OpenStreetMap has them.

Fuel stations: map_pois.json ("fuel" points) and buildings tagged amenity=fuel (merged when within 30 m).
Car washes: buildings tagged amenity=car_wash.
Each one is tied to the nearest drivable road within 45 m (nearly all petrol stations are mapped with a service road
through the forecourt), so the traffic can enter it from the street grid.  A fuel station gets two pump islands beside
that road (a canopy over them when the ground is free), a price pylon and breakable pumps; a car wash gets a pylon.
Some fuel stations also get a parked lorry.

-> (posts, sites, parked).  site = [x, y, kind, edge, s, visit, name, ox, oy]   (ox, oy: the OSM point, i.e. the shop)   kind 0 = fuel, 1 = car wash; (x, y) = where the car
stops (on the road next to the pumps / in front of the wash bay); edge, s = that point on the road graph; visit = 1 when
the road is a low-class one (service, residential ...) where a visitor can stand without blocking a main road."""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from furniture import G  # noqa: E402
from geo import project  # noqa: E402

RED, WHITE, GREY, DARK = (200, 36, 40), (236, 236, 238), (150, 152, 158), (50, 52, 58)
BRAND = {"макпетрол": ((20, 70, 160), (230, 200, 30)), "makpetrol": ((20, 70, 160), (230, 200, 30)),
         "лукоил": ((200, 30, 36), WHITE), "лукoил": ((200, 30, 36), WHITE), "okta": ((220, 90, 30), WHITE), "окта": ((220, 90, 30), WHITE)}
VISIT_CLS = ("service", "living_street", "residential", "unclassified")
MAX_SNAP = 45.0


def _centroid(geom):
    pts = [project(g["lat"], g["lon"]) for g in geom or [] if g]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), pts


def load(src, hx, hy):
    """-> [(kind, x, y, name)] from the OSM files in src, fuel stations de-duplicated."""
    out = []
    try:
        for p in json.load(open(os.path.join(src, "map_pois.json"), encoding="utf-8")):
            if p[2] == "fuel":
                out.append((0, p[0], p[1], p[3] or ""))
    except (OSError, ValueError):
        pass
    try:
        for el in json.load(open(os.path.join(src, "buildings.json"), encoding="utf-8")).get("elements", []):
            t = el.get("tags", {})
            am = t.get("amenity")
            if am not in ("fuel", "car_wash"):
                continue
            c = _centroid(el.get("geometry"))
            if c is None:
                continue
            nm = t.get("name") or t.get("operator") or ""
            if am == "fuel":
                if not any(k == 0 and (x - c[0]) ** 2 + (y - c[1]) ** 2 < 900 for k, x, y, _ in out):
                    out.append((0, c[0], c[1], nm))
            else:
                out.append((1, c[0], c[1], nm))
    except (OSError, ValueError):
        pass
    return [o for o in out if abs(o[1]) < hx - 40 and abs(o[2]) < hy - 40]


class _Roads:
    """Nearest drivable edge point, with a 64 m grid over the edge segments."""

    def __init__(self, edges):
        self.edges = edges
        self.g = {}
        for i, e in enumerate(edges):
            if not e["drive"] or e["bridge"]:
                continue
            p = e["pts"]
            for k in range(len(p) - 1):
                for cx in range(int(min(p[k][0], p[k + 1][0]) // 64), int(max(p[k][0], p[k + 1][0]) // 64) + 1):
                    for cy in range(int(min(p[k][1], p[k + 1][1]) // 64), int(max(p[k][1], p[k + 1][1]) // 64) + 1):
                        self.g.setdefault((cx, cy), []).append((i, k))

    def nearest(self, x, y, r=MAX_SNAP):
        """-> (dist, edge, s along edge, px, py, tx, ty) of the closest road point within r, or None."""
        best = None
        n = int(r // 64) + 1
        for cx in range(int(x // 64) - n, int(x // 64) + n + 1):
            for cy in range(int(y // 64) - n, int(y // 64) + n + 1):
                for i, k in self.g.get((cx, cy), ()):
                    e = self.edges[i]
                    (ax, ay), (bx, by) = e["pts"][k], e["pts"][k + 1]
                    dx, dy = bx - ax, by - ay
                    L2 = dx * dx + dy * dy or 1.0
                    u = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
                    px, py = ax + u * dx, ay + u * dy
                    d = math.hypot(x - px, y - py)
                    if d < r and (best is None or d < best[0]):
                        L = math.sqrt(L2)
                        best = (d, i, e["cum"][k] + u * L, px, py, dx / L, dy / L)
        return best


def _pump(g, x, z, yaw, col):
    g.box(x, 0.0, z, 0.55, 0.25, 0.9, GREY, yaw)                         # plinth
    g.box(x, 0.25, z, 0.5, 1.35, 0.7, col, yaw)
    g.box(x, 1.05, z, 0.52, 0.32, 0.72, WHITE, yaw)                      # display band
    g.box(x, 1.6, z, 0.56, 0.06, 0.76, DARK, yaw)


def _fuel_site(g, px, pz, tx, tz, nx, nz, half_w, col, canopy, yaw):
    """Pump islands beside the road at (px, pz): tangent (tx, tz), normal (nx, nz) towards the station."""
    off = half_w + 3.4
    cx, cz = px + nx * off, pz + nz * off
    if canopy:
        for a in (-4.0, 4.0):
            for b in (-2.4, 2.4):
                g.box(cx + tx * a + nx * b, 0.0, cz + tz * a + nz * b, 0.28, 4.4, 0.28, GREY, yaw)
        g.box(cx, 4.4, cz, 9.6, 0.5, 6.0, WHITE, yaw)
        g.box(cx, 4.9, cz, 9.7, 0.18, 6.1, col, yaw)
    for a in (-2.6, 2.6):
        _pump(g, cx + tx * a, cz + tz * a, yaw, RED)


def _pylon(g, x, z, yaw, top, h=6.5):
    g.box(x, 0.0, z, 0.35, h, 0.35, GREY, yaw)
    g.box(x, h, z, 0.3, 2.4, 1.7, top[0], yaw)
    g.box(x, h + 1.6, z, 0.34, 0.5, 1.5, top[1], yaw)


def build(src, edges, add, chunk_of, th, free, hx, hy, log=print):
    """edges: the world graph; add(chunk, mat, pos, uv, col); th(x, y): terrain height; free(x, y): ground free of buildings
    and paved surfaces.  -> (posts, sites, parked)."""
    import vehicles
    heavy = vehicles.HEAVY
    heavy_w = vehicles.HEAVY_W
    sites, posts, parked = [], [], []
    roads = _Roads(edges)
    found = load(src, hx, hy)
    dropped = 0
    for kind, x, y, name in found:
        hit = roads.nearest(x, y)
        if hit is None:
            dropped += 1
            continue
        d, ei, s, px, py, tx, ty = hit
        e = edges[ei]
        nx, ny = -ty, tx                                                   # left of travel
        if (x - px) * nx + (y - py) * ny < 0:                              # the station lies on the right: flip so that n points at it
            nx, ny = -nx, -ny
        yaw = math.atan2(ty, tx)                                           # G.box rotates in (x, z) = (east, south)
        hw = e["w"] / 2
        r = random.Random(int(x * 7 + y * 13))
        t0 = th(px, py)
        g = G()
        brand = BRAND.get(name.lower().split()[0], None) if name else None
        top = brand or r.choice(tuple(BRAND.values()))
        if kind == 0:
            cx, cz = px + nx * (hw + 3.4), py + ny * (hw + 3.4)
            canopy = all(free(cx + tx * a + nx * b, cz + ty * a + ny * b) for a in (-4, 0, 4) for b in (-3, 0, 3))
            _fuel_site(g, px, py, tx, ty, nx, ny, hw, top[0], canopy, yaw)
            if free(px + nx * (hw + 9) + tx * 8, py + ny * (hw + 9) + ty * 8):
                _pylon(g, px + nx * (hw + 9) + tx * 8, py + ny * (hw + 9) + ty * 8, yaw, top)
            for a in (-2.6, 2.6):                                          # the pumps break like the other posts
                posts.append((cx + tx * a, cz + ty * a, 0.45, t0, t0 + 1.7))
        else:
            if free(px + nx * (hw + 2.0), py + ny * (hw + 2.0)):
                _pylon(g, px + nx * (hw + 2.0), py + ny * (hw + 2.0), yaw, ((40, 150, 210), WHITE), 4.5)
        pos, uv, col = g.out()
        if len(pos):
            add(chunk_of(px, py), 3, pos, uv, col)
        visit = 1 if (e["cls"] in VISIT_CLS and e["len"] >= 14) else 0
        sites.append([round(px, 1), round(py, 1), kind, ei, round(s, 1), visit, name, round(x, 1), round(y, 1)])
        if kind == 0 and visit and e["len"] >= 30 and r.random() < 0.3:        # a lorry parked at the kerb of the forecourt road
            k = r.choices(heavy, heavy_w)[0]
            L = vehicles.DIMS[k][0]
            for sgn in (-1, 1):
                for sd in (-1, 1):
                    ss = s + sgn * (L / 2 + 9)
                    if not 3 < ss < e["len"] - 3:
                        continue
                    from_x, from_y = _along(e, ss)
                    qx, qy = from_x + sd * (-ty) * (hw + vehicles.DIMS[k][1] / 2 + 0.5), from_y + sd * tx * (hw + vehicles.DIMS[k][1] / 2 + 0.5)
                    if all(free(qx + tx * a, qy + ty * a) for a in (-L / 2, 0, L / 2)) and not any((qx - q[0]) ** 2 + (qy - q[1]) ** 2 < 400 for q in parked):
                        parked.append((qx, qy, math.atan2(ty, tx), r.randint(0, 15), k))
                        break
                else:
                    continue
                break
    log(f"[build] stations: {sum(1 for s_ in sites if s_[2] == 0)} fuel, {sum(1 for s_ in sites if s_[2] == 1)} car washes "
        f"({sum(s_[5] for s_ in sites)} open to visitors), {dropped} too far from a road, {len(parked)} parked lorries")
    return posts, sites, parked


def _along(e, s):
    """Point at distance s along edge e's polyline."""
    cum, p = e["cum"], e["pts"]
    for k in range(len(p) - 1):
        if s <= cum[k + 1] or k == len(p) - 2:
            u = (s - cum[k]) / ((cum[k + 1] - cum[k]) or 1.0)
            return p[k][0] + u * (p[k + 1][0] - p[k][0]), p[k][1] + u * (p[k + 1][1] - p[k][1])
