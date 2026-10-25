"""Round 21: the railway as 3D - viaducts over the streets, level crossings and stations (rail.json from fetch_extras).

The city line runs on a viaduct for ~7.7 km (OSM bridge=yes): a concrete deck with parapets, rails and sleepers, 5.5 m
above the terrain so every street underneath stays open; the deck eases down to the ground over RAMP m at both ends
unless a street passes beneath.  Columns stand in pairs beside the track every ~22 m and are left out wherever they would
land on a carriageway.  Where a drivable street crosses a line at ground level the crossing gets rails over the asphalt,
two striped barrier posts and warning crosses.  The five stations get a platform, a canopy and a small building.
-> (posts, stations): breakable collision circles (x, y, r, lo, hi) and (name, x, y, yaw) for later use."""
import math

import numpy as np

from furniture import G

CLEAR = 5.5                          # deck underside above the terrain
RAMP = 60.0                          # m over which the deck rises from the ground
STEP = 8.0                           # deck piece length
CONC, CONC_D, BALLAST = (176, 174, 168), (140, 138, 132), (110, 104, 96)
STEEL, SLEEPER = (96, 98, 106), (74, 60, 48)
STRIPE = ((236, 236, 236), (214, 36, 36))


def _seg_hit(a, b, c, d):
    r, s = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    return (a[0] + t * r[0], a[1] + t * r[1]) if 0 <= t <= 1 and 0 <= u <= 1 else None


def _pieces(pts):
    """Resample a polyline into ~STEP m pieces -> [(x, z, yaw, length, dist_from_start)]."""
    out, run = [], 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        ln = math.hypot(bx - ax, by - ay)
        if ln < 0.5:
            continue
        n = max(1, int(round(ln / STEP)))
        yaw = math.atan2(by - ay, bx - ax)
        for k in range(n):
            t0, t1 = k / n, (k + 1) / n
            out.append(((ax + (bx - ax) * (t0 + t1) / 2), (ay + (by - ay) * (t0 + t1) / 2), yaw, ln / n, run + ln * (t0 + t1) / 2))
        run += ln
    return out, run


def viaduct(g_list, pts, th, in_lane, under):
    """Deck, parapets, rails and columns along one bridge way.  -> [(x, z, y_abs, G)], posts"""
    pcs, total = _pieces(pts)
    parts, posts = [], []
    for i, (x, z, yaw, ln, run) in enumerate(pcs):
        ramp = min(1.0, min(run, total - run) / RAMP)
        ramp = ramp * ramp * (3 - 2 * ramp)
        ca, sa = math.cos(yaw), math.sin(yaw)
        nx, nz = -sa, ca
        low = min(th(x, z), th(x + nx * 3, z + nz * 3), th(x - nx * 3, z - nz * 3))
        c = CLEAR if under(x, z) else CLEAR * ramp
        y = low + c
        g = G()
        g.box(x, y, z, ln + 0.05, 0.9, 6.0, CONC, yaw)                                    # deck slab
        g.box(x, y + 0.9, z, ln + 0.05, 0.28, 4.2, BALLAST, yaw)                          # ballast bed
        for s in (-1, 1):
            g.box(x + nx * 2.85 * s, y + 0.9, z + nz * 2.85 * s, ln + 0.05, 0.9, 0.3, CONC_D, yaw)       # parapets
            g.box(x + nx * 0.72 * s, y + 1.18, z + nz * 0.72 * s, ln + 0.05, 0.16, 0.08, STEEL, yaw)     # rails
        for k in (-0.5, 0.0, 0.5):                                                        # sleepers
            g.box(x + ca * ln * k, y + 1.12, z + sa * ln * k, 0.28, 0.07, 2.5, SLEEPER, yaw)
        parts.append((x, z, 0.0, g))
        if c > 2.0 and i % 3 == 1:                                                        # a pair of columns
            for s in (-1, 1):
                px, pz = x + nx * 2.2 * s, z + nz * 2.2 * s
                if not in_lane(px, pz, -1.0):                                         # a column stands clear of every street
                    h = th(px, pz)
                    gc = G()
                    gc.box(px, h - 0.5, pz, 1.1, y - h + 0.5, 1.1, CONC_D, yaw)
                    parts.append((px, pz, 0.0, gc))
                    posts.append((px, pz, 0.7, h - 1.0, y))
    return parts, posts


def crossing(x, z, yaw, ryaw, w):
    """Rails across the asphalt plus a striped post with a warning cross on the right kerb of both approaches.
    yaw = direction of the line, ryaw = direction of the street."""
    g = G()
    ca, sa = math.cos(yaw), math.sin(yaw)
    nx, nz = -sa, ca
    rx, rz = math.cos(ryaw), math.sin(ryaw)
    g.box(x, 0.1, z, w + 3.0, 0.05, 3.4, (156, 152, 144), yaw)                    # concrete crossing panel over the asphalt
    for s in (-0.72, 0.72):
        g.box(x + nx * s, 0.15, z + nz * s, w + 3.0, 0.07, 0.16, (170, 172, 182), yaw)
    for s in (-1, 1):
        px, pz = x + rx * 3.6 * s - rz * (w / 2 + 1.0) * s, z + rz * 3.6 * s + rx * (w / 2 + 1.0) * s
        for k in range(5):
            g.box(px, 0.5 * k, pz, 0.14, 0.5, 0.14, STRIPE[k % 2])
        g.box(px, 2.5, pz, 0.9, 0.9, 0.06, (232, 232, 232), yaw + math.pi / 4)
        g.box(px, 2.6, pz, 0.7, 0.7, 0.08, (214, 36, 36), yaw + math.pi / 4)
    return g


def station(x, z, yaw, name):
    """-> (platform + canopy, building).  Platform (60 m) and canopy beside the line, a small building further out; the
    platform goes up with the deck when the line is on the viaduct.  yaw = direction of the line."""
    g, h = G(), G()
    ca, sa = math.cos(yaw), math.sin(yaw)
    nx, nz = -sa, ca
    g.box(x + nx * 4.2, 0.0, z + nz * 4.2, 60.0, 0.95, 3.6, CONC, yaw)
    g.box(x + nx * 4.2, 0.95, z + nz * 4.2, 60.0, 0.05, 3.6, CONC_D, yaw)
    for k in (-24, -8, 8, 24):
        g.box(x + nx * 5.4 + ca * k, 0.95, z + nz * 5.4 + sa * k, 0.18, 3.0, 0.18, STEEL, yaw)
    g.box(x + nx * 4.6, 3.95, z + nz * 4.6, 52.0, 0.2, 4.2, (150, 40, 40), yaw)
    h.box(x + nx * 12.5, 0.0, z + nz * 12.5, 22.0, 4.2, 8.0, (214, 196, 150), yaw)
    h.box(x + nx * 12.5, 4.2, z + nz * 12.5, 23.0, 0.5, 9.0, (150, 60, 50), yaw)
    for k in range(-4, 5):
        h.box(x + nx * 8.45 + ca * k * 2.4, 1.1, z + nz * 8.45 + sa * k * 2.4, 1.2, 1.6, 0.1, (60, 90, 120), yaw)
    return g, h


def build(rl, edges, add_c, add_abs, chunk_of, th, in_lane, log=print):
    """rl: rail.json rows.  th(x, z): terrain height.  in_lane(x, z, r): inside a drivable carriageway."""
    ways = [r for r in rl if r[0] == "way" and r[1] == "rail"]
    nodes = [r for r in rl if r[0] == "node"]
    posts, stations = [], []
    mat = 3                                                      # MAT_SOLID

    # streets as segments in a 30 m grid, for "is a street beneath this piece" and the ground crossings
    grid = {}
    for e in edges:
        if e["drive"] and not e["bridge"]:
            for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
                for gx in range(int(min(ax, bx) // 30), int(max(ax, bx) // 30) + 1):
                    for gy in range(int(min(ay, by) // 30), int(max(ay, by) // 30) + 1):
                        grid.setdefault((gx, gy), []).append((ax, ay, bx, by, e["w"] / 2 + 3.0, e["w"]))

    def under(x, z):
        for ax, ay, bx, by, hw, _w in grid.get((int(x // 30), int(z // 30)), ()):
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (z - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
            if math.hypot(x - ax - dx * t, z - ay - dy * t) < hw + STEP / 2:
                return True
        return False

    nv = nd = nc = 0
    for _k, _kind, bridge, tunnel, pts in ways:
        if tunnel or len(pts) < 2:
            continue
        if bridge:
            parts, pp = viaduct(None, pts, th, in_lane, under)
            for x, z, _y, g in parts:
                pos, uv, col = g.out()
                add_abs(chunk_of(x, z), mat, pos, uv, col)
            posts += pp
            nd += 1
        else:                                                    # ground line: rails across the streets it meets
            for a, b in zip(pts, pts[1:]):
                seen = set()
                for gx in range(int(min(a[0], b[0]) // 30), int(max(a[0], b[0]) // 30) + 1):
                    for gy in range(int(min(a[1], b[1]) // 30), int(max(a[1], b[1]) // 30) + 1):
                        for ax, ay, bx, by, _hw, w in grid.get((gx, gy), ()):
                            if (ax, ay, bx, by) in seen:
                                continue
                            seen.add((ax, ay, bx, by))
                            p = _seg_hit(a, b, (ax, ay), (bx, by))
                            if p:
                                g = crossing(p[0], p[1], math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(by - ay, bx - ax), w)
                                add_c(chunk_of(*p), mat, *g.out())
                                nc += 1
    for _k, kind, x, z, name in nodes:
        if kind not in ("station", "halt"):
            continue
        best = None                                              # the nearest line gives the platform its direction
        for _w, _kind, br, tu, pts in ways:
            if tu:
                continue
            for a, b in zip(pts, pts[1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                t = max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dy) / (dx * dx + dy * dy or 1e-9)))
                d = math.hypot(x - a[0] - dx * t, z - a[1] - dy * t)
                if best is None or d < best[0]:
                    best = (d, math.atan2(dy, dx), br)
        if best and best[0] < 40:
            gp, gb = station(x, z, best[1], name)
            if best[2]:                                          # on the viaduct: platform at deck level
                pos, uv, col = gp.out()
                pos = pos.copy()
                pos[:, 1] += th(x, z) + CLEAR + 0.9
                add_abs(chunk_of(x, z), mat, pos, uv, col)
            else:
                add_c(chunk_of(x, z), mat, *gp.out())
            add_c(chunk_of(x, z), mat, *gb.out())
            stations.append((name, x, z, best[1]))
            for k in (-7.0, 0.0, 7.0):                          # the building is 22 m long: three collision circles
                posts.append((x + math.cos(best[1]) * k - math.sin(best[1]) * 12.5, z + math.sin(best[1]) * k + math.cos(best[1]) * 12.5,
                              4.2, th(x, z) - 1.0, th(x, z) + 4.5))
    log(f"[build] railway: {nd} viaduct sections, {nc} ground crossings, {len(stations)} stations")
    return posts, stations
