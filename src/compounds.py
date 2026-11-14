"""Guarded compounds: police stations (from the map's police POIs) and army barracks, Касарни (OSM landuse=military).

Everything is placed when the game starts, on top of the built world (no world rebuild): fences go into the wall
collision grid, guards are ordinary Ped objects in mode "guard", the parked vehicles are ordinary bodies.

Police station: a fenced yard round the station building with one gate, МВР / ПОЛИЦИЈА signs, patrol cars and a Марица.
Barracks: two fence lines with barbed wire (it hurts), gates with booths, КАСАРНА + name + АРМ signs, green army vehicles
and arch bunkers, each holding a БТР-80; only one of them per barracks can be taken (which one is random).

Walk in and a guard warns you; stay and they come to cuff you (Уапсен: weapons gone, half the cash, you are put out on
the street). Punch a guard and he cuffs you on the spot. Soldiers open fire at anyone who comes in by car or running."""
import json
import math
import os
import random

import vehicles

WARN_S = {"police": 4.0, "army": 3.5}           # seconds of warning before the guards come for you
CALM_S = 6.0                                     # out of the compound this long: the guards go back to their posts
NEAR = 300.0                                     # guards and vehicles appear within this distance of the compound
FAR = 430.0
BUST_S = 2.6                                     # hands up, cuffs on
BARB_DMG = 6.0
SOLDIER_DMG = 9.0                                # one soldier's Калаш round on you (or your car)
POLICE_TXT = {"warn": ["Стој! Полиција! Ова е забранет простор, излези веднаш!", "Хеј ти! Нема влез тука, назад!"],
              "arrest": ["Доста беше! Рацете горе!", "Сега те приведувам!"],
              "cuff": ["Уапсен си!", "Рацете на грб!"]}
ARMY_TXT = {"warn": ["Стој! Воен објект! Врати се или пукам!", "Стој! Забранета зона, назад!"],
            "arrest": ["Лези на земја! Рацете горе!", "Тревога! Натрапник!"],
            "cuff": ["Уапсен си!", "Не мрдај!"]}


def _seg_d2(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    qx, qy = ax + dx * t - px, ay + dy * t - py
    return qx * qx + qy * qy


def _inside(x, y, ring):
    inside = False
    xj, yj = ring[-1]
    for xi, yi in ring:
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        xj, yj = xi, yi
    return inside


def _area(ring):
    return 0.5 * sum(ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1] for i in range(len(ring)))


def _offset(ring, d):
    """The ring moved d metres inwards (mitred corners, clamped)."""
    n = len(ring)
    sgn = 1.0 if _area(ring) > 0 else -1.0
    out = []
    for i in range(n):
        (ax, ay), (bx, by), (cx, cy) = ring[i - 1], ring[i], ring[(i + 1) % n]
        e1 = (bx - ax, by - ay)
        e2 = (cx - bx, cy - by)
        l1, l2 = math.hypot(*e1) or 1.0, math.hypot(*e2) or 1.0
        n1 = (-e1[1] / l1 * sgn, e1[0] / l1 * sgn)                 # inward normals
        n2 = (-e2[1] / l2 * sgn, e2[0] / l2 * sgn)
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        ml = math.hypot(mx, my) or 1.0
        cos_h = max(0.35, (mx * n1[0] + my * n1[1]) / ml)
        k = d / cos_h
        out.append((bx + mx / ml * k, by + my / ml * k))
    return out


def _cross(p1, p2, p3, p4):
    """Intersection point of segments p1-p2 and p3-p4, or None (and the parameter along p1-p2)."""
    d = (p2[0] - p1[0]) * (p4[1] - p3[1]) - (p2[1] - p1[1]) * (p4[0] - p3[0])
    if abs(d) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * (p4[1] - p3[1]) - (p3[1] - p1[1]) * (p4[0] - p3[0])) / d
    u = ((p3[0] - p1[0]) * (p2[1] - p1[1]) - (p3[1] - p1[1]) * (p2[0] - p1[0])) / d
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t
    return None


class Compound:
    def __init__(self, kind, name, ring):
        self.kind, self.name, self.ring = kind, name, ring
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        self.bb = (min(xs), min(ys), max(xs), max(ys))
        self.fence = []            # (ax, ay, bx, by, height, barbed)
        self.gates = []            # (x, y, along angle, width, outward nx, ny)
        self.booths = []           # (x, y, heading)
        self.bunkers = []          # (x, y, heading): open at both ends along the heading
        self.spots = []            # [x, y, heading, kind, locked]
        self.posts = []            # guard posts (x, y, heading)
        self.route = []            # patrol loop
        self.signs = []            # (x, y, z, facing, width, height)
        self.flat = []             # emblems painted on the ground (x, y, size, heading)
        self.out_pt = None         # where a busted player is put back on the street
        self.state, self.warn_t, self.calm_t = "calm", 0.0, 0.0
        self.guards = []
        self.live = {}             # spot index -> Body
        self.taken = set()         # spot indices whose vehicle somebody drove away
        self.active = False
        self.building = None       # the main building's ring (police station)

    def near(self, x, y, r):
        x0, y0, x1, y1 = self.bb
        return x0 - r <= x <= x1 + r and y0 - r <= y <= y1 + r

    def dist(self, x, y):
        x0, y0, x1, y1 = self.bb
        return math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1))

    def inside(self, x, y):
        return self.near(x, y, 0.0) and _inside(x, y, self.ring)


class Compounds:
    def __init__(self, sim, pois, osm_dir=None, seed=None):
        self.sim, self.w = sim, sim.w
        self.rng = random.Random(seed)
        self.list = []
        self._models = {}          # render cache (compound index -> [(bounds, model)])
        self.tex = {}
        self.barb_cd = 0.0
        self.bust = None
        self.bust_screen = 0.0
        self.btr_tip = None
        self._chk = 0.0
        pol = [p for p in (pois or ()) if len(p) >= 4 and p[2] == "police"]
        for x, y, _c, nm in pol:
            try:
                c = self._police(float(x), float(y), nm)
            except Exception as e:  # noqa: BLE001 - a strange footprint never stops the game
                print(f"[compounds] police '{nm}' skipped: {e}")
                c = None
            if c is not None:
                self.list.append(c)
        for nm, ring in self._military(osm_dir):
            try:
                c = self._army(nm, ring)
            except Exception as e:  # noqa: BLE001
                print(f"[compounds] barracks '{nm}' skipped: {e}")
                c = None
            if c is not None:
                self.list.append(c)
        w = self.w
        for c in self.list:                                    # fences and bunker walls are walls for cars, people and bullets
            for ax, ay, bx, by, *_r in c.fence + self._solid(c):
                self._add_wall(ax, ay, bx, by)
            for sx, sy, _h, _k, _l in c.spots:
                self._clear(sx, sy, 4.5)
            for bx_, by_, _h in c.bunkers:
                self._clear(bx_, by_, 9.0)
        self._barb = {}
        for ci, c in enumerate(self.list):
            for f in c.fence:
                if f[5]:
                    ax, ay, bx, by = f[:4]
                    for gx in range(int(min(ax, bx) // 16), int(max(ax, bx) // 16) + 1):
                        for gy in range(int(min(ay, by) // 16), int(max(ay, by) // 16) + 1):
                            self._barb.setdefault((gx, gy), []).append(f)
        print(f"[compounds] {sum(1 for c in self.list if c.kind == 'police')} police stations, "
              f"{sum(1 for c in self.list if c.kind == 'army')} barracks, {sum(len(c.bunkers) for c in self.list)} bunkers")

    # ------------------------------------------------------------------ placing
    def _add_wall(self, ax, ay, bx, by):
        w = self.w
        cg = w.cg
        for cx in range(int(min(ax, bx) // cg), int(max(ax, bx) // cg) + 1):
            for cy in range(int(min(ay, by) // cg), int(max(ay, by) // cg) + 1):
                w.cgrid.setdefault((cx, cy), []).append((ax, ay, bx, by))

    def _clear(self, x, y, r):
        """Trees and props where a vehicle or bunker stands go (hidden, no collision)."""
        w = self.w
        cg = w.cg
        hit = False
        for e in list(w.points_near(x, y, r)):
            if (e[0] - x) ** 2 + (e[1] - y) ** 2 > r * r:
                continue
            cell = w.pgrid.get((int(e[0] // cg), int(e[1] // cg)))
            if cell and e in cell:
                cell.remove(e)
                g0 = w.ground_y(e[0], e[1])
                w.broken_extra.append((e[0], e[1], max(4.5, e[2] + 0.6), g0 - 2.0, e[4] + 8.0))
                hit = True
        if hit:
            w.broken_ver += 1
        for i, q in enumerate(getattr(w, "parked", ()) or ()):
            if (q[0] - x) ** 2 + (q[1] - y) ** 2 < (r + 4) ** 2:
                self.sim.gone.add(i)

    def _solid(self, c):
        """Bunker side walls and booths as wall segments."""
        out = []
        for x, y, h in c.bunkers:
            ux, uy, vx, vy = math.cos(h), math.sin(h), -math.sin(h), math.cos(h)
            for s in (-1, 1):
                ox, oy = x + vx * s * 3.0, y + vy * s * 3.0
                out.append((ox - ux * 7.0, oy - uy * 7.0, ox + ux * 7.0, oy + uy * 7.0))
        for x, y, h in c.booths:
            ux, uy, vx, vy = math.cos(h), math.sin(h), -math.sin(h), math.cos(h)
            pts = [(x + ux * a + vx * b, y + uy * a + vy * b) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            out += [(pts[i][0], pts[i][1], pts[(i + 1) % 4][0], pts[(i + 1) % 4][1]) for i in range(4)]
        return out

    def _road(self, x, y):
        return self.w.surface(x, y) == 3

    def _bld_near(self, x, y, r):
        """Buildings whose box is within r of (x, y): [(ring, h, bb)]."""
        out = []
        for b in getattr(self.w, "buildings", ()):
            x0, y0, x1, y1 = b["bb"]
            if x0 - r <= x <= x1 + r and y0 - r <= y <= y1 + r:
                out.append((b["ring"], b["h"], b["bb"]))
        return out

    def _police(self, x, y, name):
        w = self.w
        if abs(x) > w.hx - 60 or abs(y) > w.hy - 60:
            return None
        if any(c.near(x, y, 25.0) for c in self.list):
            return None
        cand = self._bld_near(x, y, 45.0)
        best = None
        for ring, h, bb in cand:
            if _inside(x, y, ring):
                best = (0.0, ring, h)
                break
            d = min(_seg_d2(x, y, *ring[i - 1], *ring[i]) for i in range(len(ring)))
            if best is None or d < best[0]:
                best = (d, ring, h)
        if best is None:
            ring = [(x - 7, y - 6), (x + 7, y - 6), (x + 7, y + 6), (x - 7, y + 6)]
            h = 8.0
        else:
            ring, h = best[1], best[2]
        # main axis: the longest wall
        k = max(range(len(ring)), key=lambda i: math.hypot(ring[i][0] - ring[i - 1][0], ring[i][1] - ring[i - 1][1]))
        ang = math.atan2(ring[k][1] - ring[k - 1][1], ring[k][0] - ring[k - 1][0])
        ux, uy, vx, vy = math.cos(ang), math.sin(ang), -math.sin(ang), math.cos(ang)
        cx_, cy_ = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
        us = [(p[0] - cx_) * ux + (p[1] - cy_) * uy for p in ring]
        vs = [(p[0] - cx_) * vx + (p[1] - cy_) * vy for p in ring]
        if max(us) - min(us) > 90 or max(vs) - min(vs) > 90:          # a huge block: not a station building, use a small yard
            us, vs = [-8, 8], [-6, 6]
        m = [14.0, 14.0, 14.0, 14.0]                                   # margins: -u, +u, -v, +v

        def P(u, v):
            return cx_ + ux * u + vx * v, cy_ + uy * u + vy * v

        def side(i):
            u0, u1, v0, v1 = min(us) - m[0], max(us) + m[1], min(vs) - m[2], max(vs) + m[3]
            return [(P(u0, v0), P(u0, v1)), (P(u1, v0), P(u1, v1)), (P(u0, v0), P(u1, v0)), (P(u0, v1), P(u1, v1))][i]

        def blocked(i):
            (ax, ay), (bx, by) = side(i)
            n = max(2, int(math.hypot(bx - ax, by - ay) / 2.0))
            return any(self._road(ax + (bx - ax) * j / n, ay + (by - ay) * j / n) for j in range(n + 1))
        for i in range(4):
            while m[i] > 3.0 and blocked(i):
                m[i] -= 1.0
        u0, u1, v0, v1 = min(us) - m[0], max(us) + m[1], min(vs) - m[2], max(vs) + m[3]
        rect = [P(u0, v0), P(u1, v0), P(u1, v1), P(u0, v1)]
        c = Compound("police", name or "Полициска станица", rect)
        c.building = ring
        if any(o.near(sum(p[0] for p in rect) / 4, sum(p[1] for p in rect) / 4, 5.0) and o is not c for o in self.list):
            return None
        # the gate: on the side closest to a road
        sides = [((u0, v0), (u0, v1), (-1, 0)), ((u1, v0), (u1, v1), (1, 0)), ((u0, v0), (u1, v0), (0, -1)), ((u0, v1), (u1, v1), (0, 1))]

        def road_dist(s):
            (a, b), (c_, d), (nu, nv) = s
            mu, mv = (a + c_) / 2, (b + d) / 2
            for r in range(0, 60, 2):
                if self._road(*P(mu + nu * r, mv + nv * r)):
                    return r
            return 99
        gs = min(sides, key=road_dist)
        (a, b), (c2, d), (nu, nv) = gs
        mu, mv = (a + c2) / 2, (b + d) / 2
        gx, gy = P(mu, mv)
        onx, ony = ux * nu + vx * nv, uy * nu + vy * nv               # outward
        gw = 6.5
        along = math.atan2(ony, onx) + math.pi / 2
        c.gates.append((gx, gy, along, gw, onx, ony))
        self._fence_ring(c, rect, 2.4, False, [(gx, gy, gw)])
        bx_, by_ = gx - onx * 2.5 + math.cos(along) * (gw / 2 + 1.6), gy - ony * 2.5 + math.sin(along) * (gw / 2 + 1.6)
        c.booths.append((bx_, by_, along))
        c.posts += [(gx - onx * 1.2 - math.cos(along) * (gw / 2 + 0.8), gy - ony * 1.2 - math.sin(along) * (gw / 2 + 0.8), math.atan2(ony, onx)),
                    (gx - onx * 4.5 + math.cos(along) * (gw / 2 - 0.5), gy - ony * 4.5 + math.sin(along) * (gw / 2 - 0.5), math.atan2(ony, onx))]
        ins = _offset(rect, 2.0)
        c.route = ins
        # signs: a board over the gate (both faces) and one on the station wall facing the gate
        c.signs.append((gx + onx * 0.3, gy + ony * 0.3, w.ground_y(gx, gy) + 3.3, math.atan2(ony, onx), 5.6, 1.4))
        wall = self._wall_facing(ring, gx, gy)
        if wall is not None:
            wx, wy, wn = wall
            z = w.ground_y(wx, wy) + max(3.0, min(h - 1.8, 6.0))
            c.signs.append((wx + math.cos(wn) * 0.15, wy + math.sin(wn) * 0.15, z, wn, 4.2, 1.05))
        c.flat.append((gx - onx * 7.0, gy - ony * 7.0, 3.2, math.atan2(ony, onx)))   # МВР emblem painted on the yard
        # vehicles: patrol cars and at least one Марица
        kinds = [vehicles.MARITSA, 47, 47, 47, 47]
        c.spots = self._park(c, rect, ring, kinds, (gx, gy))
        c.out_pt = self._street(gx + onx * 18.0, gy + ony * 18.0, c)
        return c

    def _wall_facing(self, ring, gx, gy):
        """Middle of the building wall that faces the point (gx, gy) and its outward heading."""
        best = None
        sgn = 1.0 if _area(ring) > 0 else -1.0
        for i in range(len(ring)):
            (ax, ay), (bx, by) = ring[i - 1], ring[i]
            L = math.hypot(bx - ax, by - ay)
            if L < 4.0:
                continue
            mx, my = (ax + bx) / 2, (ay + by) / 2
            nx, ny = (by - ay) / L * sgn, -(bx - ax) / L * sgn         # outward
            if (gx - mx) * nx + (gy - my) * ny <= 0:
                continue
            d = math.hypot(gx - mx, gy - my)
            if best is None or d < best[0]:
                best = (d, mx, my, math.atan2(ny, nx))
        return best[1:] if best else None

    def _street(self, x, y, c):
        """A pavement / road point outside the compound near (x, y)."""
        w = self.w
        p = w.nearest_walk_point(x, y, 120)
        if p:
            px, py, _dx, _dy = w.edge_point(w.edges[p[0]], p[1])
            if not c.inside(px, py):
                return (px, py)
        p = w.nearest_drive_point(x, y)
        if p and not c.inside(p[0], p[1]):
            return (p[0], p[1])
        return (x, y)

    def _fence_ring(self, c, ring, h, barbed, gaps):
        """Fence segments along a ring, with openings (x, y, width) where the gates are."""
        n = len(ring)
        for i in range(n):
            (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
            L = math.hypot(bx - ax, by - ay)
            if L < 0.2:
                continue
            cuts = []
            for gx, gy, gw in gaps:
                t = ((gx - ax) * (bx - ax) + (gy - ay) * (by - ay)) / (L * L)
                if -0.05 <= t <= 1.05 and _seg_d2(gx, gy, ax, ay, bx, by) < 4.0:
                    cuts.append((t - gw / 2 / L, t + gw / 2 / L))
            t0 = 0.0
            for g0, g1 in sorted(cuts) + [(1.0, 1.0)]:
                if g0 > t0:
                    c.fence.append((ax + (bx - ax) * t0, ay + (by - ay) * t0, ax + (bx - ax) * min(1.0, g0), ay + (by - ay) * min(1.0, g0), h, barbed))
                t0 = max(t0, g1)

    def _park(self, c, ring, bld, kinds, gate, avoid=(), ang=None):
        """Greedy parking: each vehicle on a free spot inside `ring`, clear of the building, the fence, the gate lane and the others."""
        w = self.w
        x0, y0, x1, y1 = (min(p[0] for p in ring), min(p[1] for p in ring), max(p[0] for p in ring), max(p[1] for p in ring))
        if ang is None:
            ang = math.atan2(ring[1][1] - ring[0][1], ring[1][0] - ring[0][0])
        out = []
        blds = self._bld_near((x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2 + 10)
        cand = []
        st = 1.5
        gx_, gy_ = gate
        for i in range(int((x1 - x0) / st) + 1):
            for j in range(int((y1 - y0) / st) + 1):
                x, y = x0 + i * st, y0 + j * st
                if not _inside(x, y, ring):
                    continue
                edge = min(_seg_d2(x, y, *ring[k - 1], *ring[k]) for k in range(len(ring)))
                cand.append((math.sqrt(edge) + 0.25 * math.hypot(x - gx_, y - gy_), x, y))   # along the fence, near the gate
        cand.sort()
        for kind in kinds:
            L, W = vehicles.DIMS[kind][0], vehicles.DIMS[kind][1]
            for _e, x, y in cand:
                ok = None
                for h in (ang, ang + math.pi / 2):
                    ux, uy, vx, vy = math.cos(h), math.sin(h), -math.sin(h), math.cos(h)
                    pts = [(x + ux * a * (L / 2 + 0.6) + vx * b * (W / 2 + 0.6), y + uy * a * (L / 2 + 0.6) + vy * b * (W / 2 + 0.6))
                           for a in (-1, 0, 1) for b in (-1, 0, 1)]
                    if not all(_inside(px, py, ring) for px, py in pts):
                        continue
                    if any(_inside(px, py, r) for px, py in pts for r, _h, _b in blds):
                        continue
                    if any(True for _ in w.edges_near(x, y, max(L, W) / 2 + 0.4)
                           if _seg_d2(x, y, _[0], _[1], _[2], _[3]) < (W / 2 + 0.5) ** 2):
                        continue
                    if (x - gx_) ** 2 + (y - gy_) ** 2 < 9.0 ** 2:
                        continue
                    if any((x - q[0]) ** 2 + (y - q[1]) ** 2 < ((L + vehicles.DIMS[q[3]][0]) / 2 + 0.8) ** 2 for q in out):
                        continue
                    if any((x - ax) ** 2 + (y - ay) ** 2 < ar * ar for ax, ay, ar in avoid):
                        continue
                    if any(_seg_d2(x, y, f[0], f[1], f[2], f[3]) < (W / 2 + 1.0) ** 2 for f in c.fence):
                        continue
                    ok = h
                    break
                if ok is not None:
                    out.append([x, y, ok, kind, False])
                    break
        return out

    def _military(self, osm_dir):
        """[(name, ring)] of the landuse=military areas in the map's areas.json."""
        import geo
        d = osm_dir or os.environ.get("SK242_OSM_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "osm")
        fn = os.path.join(d, "areas.json")
        try:
            with open(fn, encoding="utf-8") as f:
                els = json.load(f).get("elements", [])
        except (OSError, ValueError) as e:
            print(f"[compounds] no military areas ({e})")
            return []
        out = []
        for e in els:
            t = e.get("tags", {})
            if t.get("landuse") != "military" and t.get("military") not in ("barracks", "base"):
                continue
            g = e.get("geometry") or []
            if not g and e.get("members"):
                g = max((m.get("geometry") or [] for m in e["members"] if m.get("role") == "outer"), key=len, default=[])
            ring = [geo.project(q["lat"], q["lon"]) for q in g if q]
            if len(ring) > 3 and ring[0] == ring[-1]:
                ring = ring[:-1]
            simp = []
            for p in ring:
                if not simp or math.hypot(p[0] - simp[-1][0], p[1] - simp[-1][1]) > 3.0:
                    simp.append(p)
            if len(simp) >= 3 and abs(_area(simp)) > 4000:
                nm = (t.get("name:mk") or t.get("name") or "").replace("АРСМ", "АРМ")
                out.append((nm, simp))
        return out

    def _army(self, name, ring):
        w = self.w
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        if max(xs) < -w.hx + 30 or min(xs) > w.hx - 30 or max(ys) < -w.hy + 30 or min(ys) > w.hy - 30:
            return None
        c = Compound("army", name, ring)
        inner = _offset(ring, 3.5)
        # gates where drive roads cross the perimeter
        hits = []
        n = len(ring)
        for e in w.edges:
            if not e["drive"]:
                continue
            pts = e["pts"]
            if not any(c.near(px, py, 5.0) for px, py in (pts[0], pts[-1], pts[len(pts) // 2])) and \
                    not any(c.near(px, py, 5.0) for px, py in pts):
                continue
            for k in range(len(pts) - 1):
                for i in range(n):
                    t = _cross(pts[k], pts[k + 1], ring[i], ring[(i + 1) % n])
                    if t is not None:
                        x = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * t
                        y = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * t
                        hits.append((-vehicles_rank(e["cls"]), x, y, max(6.0, e.get("w", 6.0) + 3.0), i))
        hits.sort()
        gates = []
        for _r, x, y, gw, i in hits:
            if all(math.hypot(x - g[0], y - g[1]) > 40 for g in gates):
                gates.append((x, y, gw, i))
            if len(gates) >= 4:
                break
        if not gates:                                              # no road in: a gate where the nearest road is
            cx_, cy_ = sum(xs) / len(xs), sum(ys) / len(ys)
            p = w.nearest_drive_point(cx_, cy_, 900)
            tx, ty = (p[0], p[1]) if p else (cx_, cy_)
            i = min(range(n), key=lambda i: _seg_d2(tx, ty, *ring[i], *ring[(i + 1) % n]))
            (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
            L2 = (bx - ax) ** 2 + (by - ay) ** 2 or 1.0
            t = max(0.15, min(0.85, ((tx - ax) * (bx - ax) + (ty - ay) * (by - ay)) / L2))
            gates.append((ax + (bx - ax) * t, ay + (by - ay) * t, 7.0, i))
        sgn = 1.0 if _area(ring) > 0 else -1.0
        gap_o, gap_i = [], []
        for gi, (x, y, gw, i) in enumerate(gates):
            (ax, ay), (bx, by) = ring[i], ring[(i + 1) % n]
            L = math.hypot(bx - ax, by - ay) or 1.0
            onx, ony = (by - ay) / L * sgn, -(bx - ax) / L * sgn      # outward
            along = math.atan2(by - ay, bx - ax)
            c.gates.append((x, y, along, gw, onx, ony))
            gap_o.append((x, y, gw))
            gap_i.append((x - onx * 3.5, y - ony * 3.5, gw))
            out = math.atan2(ony, onx)
            bx_, by_ = x - onx * 1.75 + math.cos(along) * (gw / 2 + 1.4), y - ony * 1.75 + math.sin(along) * (gw / 2 + 1.4)
            c.booths.append((bx_, by_, along))
            c.posts += [(x - onx * 1.75 - math.cos(along) * (gw / 2 + 0.6), y - ony * 1.75 - math.sin(along) * (gw / 2 + 0.6), out),
                        (x - onx * 6.0 + math.cos(along) * (gw / 2 - 0.4), y - ony * 6.0 + math.sin(along) * (gw / 2 - 0.4), out)]
            z = w.ground_y(x, y)
            c.signs.append((x + onx * 0.4, y + ony * 0.4, z + 3.6, out, 6.4, 1.6))
            if gi == 0:
                c.flat.append((x - onx * 12.0, y - ony * 12.0, 4.0, out))
                c.out_pt = self._street(x + onx * 20.0, y + ony * 20.0, c)
        self._fence_ring(c, ring, 2.7, True, gap_o)
        self._fence_ring(c, inner, 2.7, True, gap_i)
        c.route = _offset(ring, 6.5)
        # bunkers: a row of arch shelters facing the main gate, then the motor pool
        area = abs(_area(ring))
        nb = 2 if area < 45000 else (3 if area < 250000 else 4)
        g0 = c.gates[0]
        deep = _offset(ring, 14.0)
        if abs(_area(deep)) < 1000 or (_area(deep) > 0) != (_area(ring) > 0):
            deep = _offset(ring, 9.0)
        blds = self._bld_near((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 10)
        cands = []
        for i in range(int((max(xs) - min(xs)) / 6) + 1):
            for j in range(int((max(ys) - min(ys)) / 6) + 1):
                x, y = min(xs) + i * 6.0, min(ys) + j * 6.0
                if _inside(x, y, deep):
                    cands.append((math.hypot(x - g0[0], y - g0[1]), x, y))
        cands.sort()
        rng = self.rng

        def clear_box(x, y, h, L, W):
            ux, uy, vx, vy = math.cos(h), math.sin(h), -math.sin(h), math.cos(h)
            pts = [(x + ux * a * L / 2 + vx * b * W / 2, y + uy * a * L / 2 + vy * b * W / 2) for a in (-1, -0.5, 0, 0.5, 1) for b in (-1, 0, 1)]
            if not all(_inside(px, py, deep) for px, py in pts):
                return False
            if sum(self._road(px, py) for px, py in pts) > 3:
                return False
            if any(_inside(px, py, r) for px, py in pts for r, _h, _b in blds):
                return False
            if any(_seg_d2(x, y, *e_[:4]) < (max(L, W) / 2 + 1.0) ** 2 for e_ in w.edges_near(x, y, max(L, W) / 2 + 2.0)):
                return False
            return all(math.hypot(x - bx, y - by) > 12.0 for bx, by, _h in c.bunkers)
        for _d, x, y in cands:
            if len(c.bunkers) >= nb or _d < 25.0:
                if len(c.bunkers) >= nb:
                    break
                continue
            h = math.atan2(g0[1] - y, g0[0] - x)                    # open end towards the main gate
            if not clear_box(x, y, h, 16.0, 8.0):
                continue
            c.bunkers.append((x, y, h))
            vx, vy = -math.sin(h), math.cos(h)
            for k in (1, -1, 2, -2):                                 # neighbours side by side
                if len(c.bunkers) >= nb:
                    break
                nx_, ny_ = x + vx * 9.0 * k, y + vy * 9.0 * k
                if clear_box(nx_, ny_, h, 16.0, 8.0):
                    c.bunkers.append((nx_, ny_, h))
        lucky = rng.randrange(len(c.bunkers)) if c.bunkers else -1
        for i, (x, y, h) in enumerate(c.bunkers):
            c.spots.append([x, y, h, vehicles.BTR, i != lucky])
            c.posts.append((x + math.cos(h) * 9.5 + math.sin(h) * 3.5, y + math.sin(h) * 9.5 - math.cos(h) * 3.5, h))
        H, N, T = vehicles.ARMY_CARS
        kinds = [H, N, T, H, N, T] if area > 45000 else [H, N, T]
        av = [(x, y, 10.0) for x, y, _h in c.bunkers]
        c.spots += self._park(c, deep, None, kinds, (g0[0], g0[1]), av, math.atan2(g0[5], g0[4]) + math.pi / 2)
        # a wall sign on the biggest building near the main gate
        best = None
        for r_, h_, bb_ in blds:
            cx_, cy_ = (bb_[0] + bb_[2]) / 2, (bb_[1] + bb_[3]) / 2
            if _inside(cx_, cy_, ring):
                score = (bb_[2] - bb_[0]) * (bb_[3] - bb_[1]) / (1.0 + math.hypot(cx_ - g0[0], cy_ - g0[1]) / 60.0)
                if best is None or score > best[0]:
                    best = (score, r_, h_)
        if best is not None:
            wall = self._wall_facing(best[1], g0[0], g0[1])
            if wall is not None:
                wx, wy, wn = wall
                c.signs.append((wx + math.cos(wn) * 0.15, wy + math.sin(wn) * 0.15, w.ground_y(wx, wy) + max(3.0, min(best[2] - 1.8, 6.0)), wn, 4.8, 1.2))
        return c

    # ------------------------------------------------------------------ per frame
    def update(self, dt):
        sim = self.sim
        if sim.client:
            return
        fx, fy = sim.focus()[:2]
        self.bust_screen = max(0.0, self.bust_screen - dt)
        self.barb_cd = max(0.0, self.barb_cd - dt)
        if self.bust is not None:
            self._tick_bust(dt)
        self._chk -= dt
        check = self._chk <= 0
        if check:
            self._chk = 0.5
        for c in self.list:
            d = c.dist(fx, fy)
            if check:
                if not c.active and d < NEAR:
                    self._spawn(c, fx, fy)
                elif c.active and d > FAR:
                    self._despawn(c)
                elif c.active:
                    self._respawn_cars(c, fx, fy)
            if c.active:
                self._guards(c, dt, fx, fy)
        self._barbs(dt)
        car = sim.car
        if sim.mode == "car" and car is not None and car.kind == vehicles.BTR and self.btr_tip is not car:
            self.btr_tip = car
            sim.ev("btr_board")

    def _spawn(self, c, fx, fy):
        c.active = True
        c.state, c.warn_t, c.calm_t = "calm", 0.0, 0.0
        self._respawn_cars(c, fx, fy)
        import actors
        rng, sim = self.rng, self.sim
        arch = vehicles.SOLDIER if c.kind == "army" else vehicles.COP
        roles = [("post", p) for p in c.posts]
        npat = 2 if c.kind == "police" else min(6, 2 + len(c.route) // 8)
        for k in range(npat):
            roles.append(("patrol", k * len(c.route) // max(1, npat)))
        for role, arg in roles:
            p = actors.Ped()
            p.arch = arch
            p.shirt, p.skin = rng.randrange(3), rng.randrange(4)
            p.hp = 260.0 if c.kind == "army" else 220.0
            if role == "post":
                p.x, p.y, p.h = arg
                p.post = arg
                p.rk = None
            else:
                p.x, p.y = c.route[arg]
                p.h = 0.0
                p.post = None
                p.rk = arg
            p.home = (p.x, p.y, p.h)
            p.mode, p.t, p.v = "guard", 0.0, 0.0
            p.cmp, p.gcd, p.ghp, p.said = c, 0.0, p.hp, 0.0
            p.gz = self.w.level(p.x, p.y, -1e9)
            sim.peds.list.append(p)
            c.guards.append(p)

    def _despawn(self, c):
        c.active = False
        peds = self.sim.peds.list
        for p in c.guards:
            if p in peds and p.mode == "guard":
                peds.remove(p)
        c.guards = []
        c.live = {}
        c.taken = set()

    def _respawn_cars(self, c, fx, fy):
        sim = self.sim
        import actors
        for i, (x, y, h, kind, locked) in enumerate(c.spots):
            b = c.live.get(i)
            if b is not None:
                if b in sim.bodies and b.alive and math.hypot(b.x - x, b.y - y) < 4.0:
                    continue
                if b in sim.bodies or (b is sim.car):
                    c.taken.add(i)                                  # driven off / wrecked: not replaced while we are here
                    continue
                if i in c.taken:
                    continue
            if i in c.taken or math.hypot(x - fx, y - fy) > NEAR or math.hypot(x - fx, y - fy) < 8.0:
                continue
            nb = (actors.Apc if kind == vehicles.BTR else actors.Body)(x, y, h, kind, 0)
            nb.locked = bool(locked)
            nb.fuel = 1.0 if kind == vehicles.BTR else self.rng.uniform(0.5, 1.0)
            nb.az = self.w.ground_y(x, y)
            sim.bodies.append(nb)
            c.live[i] = nb

    # ------------------------------------------------------------------ guards
    def _player(self):
        sim = self.sim
        if sim.mode == "car" and sim.car is not None:
            return sim.car.x, sim.car.y, True
        wk = sim.walker
        if wk is None:
            return None
        return wk.x, wk.y, False

    def _shout(self, c, p, key):
        lines = (ARMY_TXT if c.kind == "army" else POLICE_TXT)[key]
        txt = self.rng.choice(lines)
        self.sim.ev("shout", text=txt, x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
        return txt

    def _guards(self, c, dt, fx, fy):
        sim, w = self.sim, self.w
        live = [p for p in c.guards if p in sim.peds.list and p.mode == "guard"]
        c.guards = live
        pl = self._player()
        wk = sim.walker
        alive = pl is not None and (sim.mode == "car" or (wk is not None and wk.health > 0))
        inside = alive and self.bust is None and c.inside(pl[0], pl[1])
        # a guard who got hit: the gloves are off (and if you punched him from up close, he cuffs you there and then)
        for p in live:
            if p.hp < p.ghp - 0.01:
                p.ghp = p.hp
                if c.state != "arrest":
                    c.state = "arrest"
                    self._shout(c, p, "arrest")
                if alive and sim.mode == "foot" and wk is not None and math.hypot(wk.x - p.x, wk.y - p.y) < 2.4 and self.bust is None:
                    self._start_bust(c, p)
                    return
        if inside:
            c.calm_t = 0.0
            if c.state == "calm":
                c.state, c.warn_t = "warn", WARN_S[c.kind]
                g = min(live, key=lambda q: (q.x - pl[0]) ** 2 + (q.y - pl[1]) ** 2, default=None)
                if g is not None:
                    sim.ev("compound_warn", kind=c.kind, text=self._shout(c, g, "warn"), x=g.x, y=g.y)
            elif c.state == "warn":
                c.warn_t -= dt
                if c.warn_t <= 0:
                    c.state = "arrest"
                    g = min(live, key=lambda q: (q.x - pl[0]) ** 2 + (q.y - pl[1]) ** 2, default=None)
                    if g is not None:
                        self._shout(c, g, "arrest")
                    sim.ev("compound_alarm", kind=c.kind)
        elif c.state != "calm":
            c.calm_t += dt
            if c.calm_t > CALM_S or not alive:
                c.state = "calm"
        near = sorted(live, key=lambda q: (q.x - fx) ** 2 + (q.y - fy) ** 2)
        chasers = set(id(q) for q in near[: (2 if c.state == "warn" else 6)]) if c.state != "calm" else set()
        shooting = 0
        for p in live:
            p.gcd = max(0.0, p.gcd - dt)
            p.said = max(0.0, p.said - dt)
            tx, ty, sp = None, None, 0.0
            if self.bust is not None and self.bust.get("g") is p:
                continue
            if id(p) in chasers and pl is not None and alive:
                d = math.hypot(pl[0] - p.x, pl[1] - p.y)
                face = math.atan2(pl[1] - p.y, pl[0] - p.x)
                if c.state == "warn":
                    tx, ty, sp = pl[0], pl[1], 1.6 if d > 3.0 else 0.0
                else:
                    in_car = sim.mode == "car"
                    running = (not in_car) and wk is not None and wk.speed > 7.0
                    if c.kind == "army" and (in_car or running) and d < 55.0 and shooting < 3:
                        shooting += 1
                        sp, tx, ty = 0.0, None, None
                        p.h = face
                        if p.gcd <= 0:
                            p.gcd = self.rng.uniform(0.25, 0.5)
                            self._fire(p, face, d)
                    else:
                        lim = c.inside(pl[0], pl[1]) or d < 6.0
                        tx, ty, sp = (pl[0], pl[1], 5.2) if lim else (None, None, 0.0)
                        if not in_car and wk is not None and d < 1.15 and self.bust is None:
                            self._start_bust(c, p)
                            return
                        if in_car and sim.car.kind != vehicles.BTR and sim.car.speed < 1.5 and d < 4.2 and self.bust is None:   # nobody pulls you out of a БТР
                            import actors
                            if actors.reach(sim.car, p.x, p.y) < 2.6:
                                self._start_bust(c, p)
                                return
                if tx is None:
                    p.h = face
            else:
                if p.post is not None:
                    tx, ty = p.post[0], p.post[1]
                    sp = 1.4 if math.hypot(tx - p.x, ty - p.y) > 0.4 else 0.0
                    if sp == 0.0:
                        p.h += ((p.post[2] - p.h + math.pi) % (2 * math.pi) - math.pi) * min(1.0, dt * 3)
                elif c.route:
                    q = c.route[p.rk % len(c.route)]
                    if math.hypot(q[0] - p.x, q[1] - p.y) < 1.0:
                        p.rk = (p.rk + 1) % len(c.route)
                        q = c.route[p.rk]
                    tx, ty, sp = q[0], q[1], 1.3
            if tx is not None and sp > 0:
                dx, dy = tx - p.x, ty - p.y
                dd = math.hypot(dx, dy)
                if dd > 1e-3:
                    st = min(dd, sp * dt)
                    nx, ny = p.x + dx / dd * st, p.y + dy / dd * st
                    if c.kind != "army" or c.inside(nx, ny) or not c.inside(p.x, p.y):
                        p.x, p.y = nx, ny
                    p.h = math.atan2(dy, dx)
                    p.anim += st
                    p.v = sp
                else:
                    p.v = 0.0
            else:
                p.v = 0.0
            p.vx = p.vy = 0.0
            p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)

    def _fire(self, p, ang, d):
        """A soldier's Калаш burst at the player (the bullets hit you, your car, or whatever is in the way)."""
        sim = self.sim
        spread = 0.035 + min(0.05, d / 1500.0)
        a = ang + self.rng.uniform(-spread, spread)
        gz = p.gz if p.gz is not None else self.w.ground_y(p.x, p.y)
        sim.shots.fire(p.x + math.cos(a) * 0.7, p.y + math.sin(a) * 0.7, a, "bullet", SOLDIER_DMG, 70.0, gz + 1.15, src=p)
        sim.ev("gunfire", x=p.x, y=p.y, kind="kalash")

    # ------------------------------------------------------------------ arrest
    def _start_bust(self, c, g):
        sim = self.sim
        if sim.mode == "car":
            if sim.car is not None:
                sim.car.vx = sim.car.vy = sim.car.w = 0.0
            sim.exit_car()
            if sim.mode != "foot":
                return
        wk = sim.walker
        if wk is None:
            return
        wk.vx = wk.vy = 0.0
        self.bust = {"t": 0.0, "g": g, "c": c}
        sim.jack = None
        sim.ev("shout", text=self.rng.choice((ARMY_TXT if c.kind == "army" else POLICE_TXT)["cuff"]), x=g.x, y=g.y, who=vehicles.PED_NAMES[g.arch])
        sim.ev("cuffs", x=wk.x, y=wk.y)

    def _tick_bust(self, dt):
        sim = self.sim
        b = self.bust
        wk = sim.walker
        if wk is None or sim.mode != "foot":
            self.bust = None
            return
        b["t"] += dt
        g = b["g"]
        bx, by = wk.x - math.cos(wk.h) * 0.75, wk.y - math.sin(wk.h) * 0.75     # the guard steps in behind you
        dx, dy = bx - g.x, by - g.y
        dd = math.hypot(dx, dy)
        if dd > 0.05:
            st = min(dd, 3.0 * dt)
            g.x += dx / dd * st
            g.y += dy / dd * st
            g.anim += st
            g.v = 1.0
        else:
            g.v = 0.0
        g.h = wk.h
        if b["t"] >= BUST_S:
            self._busted(b["c"])

    def _busted(self, c):
        sim = self.sim
        wk = sim.walker
        lost = sim.money - sim.money // 2
        sim.money //= 2
        guns = sum(1 for k, v in wk.guns.items() if v > 0)
        wk.guns = {}
        wk.weapon = "fist"
        x, y = c.out_pt or (c.ring[0][0], c.ring[0][1])
        wk.x, wk.y = x, y
        wk.az, wk.vz, wk.vx, wk.vy = None, 0.0, 0.0, 0.0
        wk.inv_t = 3.0
        wk.health = max(wk.health, 25.0)
        sim.safe = (x, y, wk.h)
        sim.safe_z = None
        self.bust = None
        self.bust_screen = 4.5
        c.state, c.calm_t = "calm", 0.0
        for p in c.guards:
            p.x, p.y, p.h = p.home
            p.ghp = p.hp
        sim.stats["busted"] = sim.stats.get("busted", 0) + 1
        sim.ev("busted", lost=lost, guns=guns, kind=c.kind)

    def busted_pose(self):
        """0 = not arrested, 1 = hands up, 2 = cuffed (for the renderer)."""
        if self.bust is None:
            return 0
        return 1 if self.bust["t"] < 0.9 else 2

    # ------------------------------------------------------------------ barbed wire
    def _barbs(self, dt):
        sim = self.sim
        if not self._barb or self.barb_cd > 0:
            return
        if sim.mode == "foot" and sim.walker is not None and sim.walker.health > 0:
            wk = sim.walker
            r2 = 0.62 ** 2
            for f in self._barb.get((int(wk.x // 16), int(wk.y // 16)), ()):
                if _seg_d2(wk.x, wk.y, *f[:4]) < r2:
                    self.barb_cd = 0.8
                    wk.health -= BARB_DMG
                    wk.hurt_t = 0.4
                    if wk.health <= 0:
                        wk.cause = "barbed"
                        sim.ev("walker_dead", cause="barbed")
                    sim.ev("barbed", x=wk.x, y=wk.y)
                    return
        elif sim.mode == "car" and sim.car is not None:
            b = sim.car
            import actors
            off, R = vehicles.CIRC[b.kind]
            for f in self._barb.get((int(b.x // 16), int(b.y // 16)), ()):
                for cx, cy, _o in actors.static_pts(b):
                    if _seg_d2(cx, cy, *f[:4]) < (R + 0.3) ** 2:
                        self.barb_cd = 0.8
                        b.health -= 3.0
                        b.dirty = True
                        sim.ev("barbed", x=cx, y=cy, car=True)
                        return

    # ------------------------------------------------------------------ drawing data
    def emblem_points(self):
        return [(c, f) for c in self.list for f in c.flat]


def vehicles_rank(cls):
    return {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1, "service": 0}.get(cls, 0)

