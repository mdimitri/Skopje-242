"""Round 21: the railway as 3D - viaducts over the streets, level crossings and stations (rail.json from fetch_extras).

The city line runs on a viaduct for ~7.7 km (OSM bridge=yes): a concrete deck with parapets, rails and sleepers, 5.5 m
above the terrain so every street underneath stays open; the deck eases down to the ground over RAMP m at both ends
unless a street passes beneath.  Columns stand in pairs beside the track every ~22 m and are left out wherever they would
land on a carriageway.  Where a drivable street crosses a line at ground level the crossing gets rails over the asphalt,
two striped barrier posts and warning crosses.  The five stations get a platform, a canopy and a small building.
-> (posts, stations, track): breakable collision circles (x, y, r, lo, hi), (name, x, y, yaw), and for the trains
{"lines": [[(x, z, y_rail_top), ...] every ~8 m], "crossings": [(x, z, edge, s_from_edge_start, yaw_of_line)]}."""
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


G_RAIL = 0.025                       # steepest rail grade: the viaduct climbs and falls at this, never in steps
CURVE = 80.0                         # vertical curves: moving average over this many metres


def rail_profile(pcs, total, th, under, free=(True, True)):
    """Deck heights (underside) of the pieces of one bridge way: CLEAR over the ground where there is room to climb,
    always CLEAR over a street beneath, down to the ground at both ends, at no more than G_RAIL, with vertical curves.
    (Before: each piece took CLEAR or CLEAR * ramp on its own, so a street under the ramp made a 5.5 m step.)"""
    n = len(pcs)
    if not n:
        return []
    s = np.array([p[4] for p in pcs])
    low = []
    for x, z, yaw, _ln, _run in pcs:
        nx, nz = -math.sin(yaw), math.cos(yaw)
        low.append(min(th(x, z), th(x + nx * 3, z + nz * 3), th(x - nx * 3, z - nz * 3)))
    low = np.array(low)
    must = np.array([under(x, z) for x, z, *_r in pcs])
    full = low + CLEAR
    # from the ends (on the ground) upwards at G_RAIL, never above full clearance ...
    g0, g1 = float(th(*pcs[0][:2])) - 1.0, float(th(*pcs[-1][:2])) - 1.0   # rail top at the ends = the ground line's (th + 0.25)
    if not free[0]:
        g0 = 1e9                                             # a branch of the viaduct goes on here: stay up (full clearance)
        must[0] = True
    if not free[1]:
        g1 = 1e9
        must[-1] = True
    prof = np.minimum(full, np.minimum(g0 + s * G_RAIL, g1 + (total - s) * G_RAIL))
    # ... but a street beneath always gets its clearance, the climb to it at G_RAIL (steeper only if the ends are too near)
    for k in np.nonzero(must)[0]:
        prof = np.maximum(prof, full[k] - np.abs(s - s[k]) * G_RAIL)
    k_ = max(1, int(round(CURVE / STEP)))
    ext = np.concatenate([np.full(k_, prof[0]), prof, np.full(k_, prof[-1])])
    sm = np.convolve(ext, np.ones(k_) / k_, mode="same")[k_:k_ + n]
    sm[must] = np.maximum(sm[must], full[must])
    e = np.minimum(1.0, np.minimum(s if free[0] else 1e9, (total - s) if free[1] else 1e9) / 40.0)
    return list(np.maximum(sm, low - 1.0 + 1.3 * e))          # sunk into the ground at the ends, clear of it inside


def viaduct(g_list, pts, th, in_lane, under, free=(True, True)):
    """Deck, parapets, rails and columns along one bridge way.  -> [(x, z, y_abs, G)], posts, [(x, z, rail top)]
    Every piece is sheared to the grade between its neighbours, so the deck is one sloping ribbon, not flat steps."""
    pcs, total = _pieces(pts)
    parts, posts, top = [], [], []
    ys = rail_profile(pcs, total, th, under, free)
    for i, (x, z, yaw, ln, run) in enumerate(pcs):
        ca, sa = math.cos(yaw), math.sin(yaw)
        nx, nz = -sa, ca
        y = ys[i]
        ya = (ys[i - 1] + y) / 2 if i > 0 else y                  # heights at the piece's two ends
        yb = (ys[i + 1] + y) / 2 if i + 1 < len(ys) else y
        slope = (yb - ya) / max(ln, 0.1)
        c = y - min(th(x, z), th(x + nx * 3, z + nz * 3), th(x - nx * 3, z - nz * 3))
        g = G()
        g.box(x, y, z, ln + 0.05, 0.9, 6.0, CONC, yaw)                                    # deck slab
        g.box(x, y + 0.9, z, ln + 0.05, 0.28, 4.2, BALLAST, yaw)                          # ballast bed
        for s in (-1, 1):
            g.box(x + nx * 2.85 * s, y + 0.9, z + nz * 2.85 * s, ln + 0.05, 0.9, 0.3, CONC_D, yaw)       # parapets
            g.box(x + nx * 0.72 * s, y + 1.18, z + nz * 0.72 * s, ln + 0.05, 0.16, 0.08, STEEL, yaw)     # rails
        for k in (-0.5, 0.0, 0.5):                                                        # sleepers
            g.box(x + ca * ln * k, y + 1.12, z + sa * ln * k, 0.28, 0.07, 2.5, SLEEPER, yaw)
        g.shear = (x, z, ca, sa, slope)
        parts.append((x, z, 0.0, g))
        top.append((round(x, 1), round(z, 1), round(y + 1.26, 2)))
        if c > 2.0 and i % 3 == 1:                                                        # a pair of columns
            for s in (-1, 1):
                px, pz = x + nx * 2.2 * s, z + nz * 2.2 * s
                if not in_lane(px, pz, -1.0):                                         # a column stands clear of every street
                    h = th(px, pz)
                    gc = G()
                    gc.box(px, h - 0.5, pz, 1.1, y - h + 0.5, 1.1, CONC_D, yaw)
                    parts.append((px, pz, 0.0, gc))
                    posts.append((px, pz, 0.7, h - 1.0, y))
    return parts, posts, top


def _out(g):
    """G.out() with the piece's grade applied (a shear along the track)."""
    pos, uv, col = g.out()
    sh = getattr(g, "shear", None)
    if sh is not None and sh[4]:
        x, z, ca, sa, slope = sh
        pos = pos.copy()
        pos[:, 1] += ((pos[:, 0] - x) * ca + (pos[:, 2] - z) * sa) * slope
    return pos, uv, col


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


def _join_bridges(ways, tol=1.0):
    """The viaduct is mapped as many short bridge ways: join the ones that meet end to end (two-way, no branch) into
    one polyline, so the rail profile runs on over the joints instead of dipping to the ground at every one."""
    br = [list(w[4]) for w in ways if w[2] and not w[3] and len(w[4]) >= 2]
    rest = [w for w in ways if not (w[2] and not w[3] and len(w[4]) >= 2)]
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    ends = {}
    for i, P in enumerate(br):
        for e in (0, -1):
            ends.setdefault(key(P[e]), []).append(i)
    used, out = set(), []
    for i in range(len(br)):
        if i in used:
            continue
        used.add(i)
        P = list(br[i])
        for side in (1, 0):                                  # grow at the end, then at the start
            while True:
                p = P[-1] if side else P[0]
                nb = [j for j in ends.get(key(p), ()) if j not in used]
                if len(nb) != 1 or len(ends.get(key(p), ())) > 2:
                    break
                j = nb[0]
                used.add(j)
                if side:
                    Q = br[j] if key(br[j][0]) == key(p) else br[j][::-1]
                    P = P + Q[1:]
                else:
                    Q = br[j] if key(br[j][-1]) == key(p) else br[j][::-1]
                    P = Q[:-1] + P
        out.append(P)
    res = []
    for ci, P in enumerate(out):                           # an end where another viaduct track goes on (a switch, a parallel
        free = []                                          # track ending a few metres off) is no ramp end: it stays up
        for q in (P[0], P[-1]):
            free.append(not any(math.hypot(o_[0] - q[0], o_[1] - q[1]) < 10.0 for cj, Q in enumerate(out) if cj != ci for o_ in _dense(Q)))
        res.append(("way", "rail", True, False, P, tuple(free)))
    return rest + res


def _dense(P, step=4.0):
    for a, b in zip(P, P[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        for k in range(n + 1):
            yield (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)


def build(rl, edges, add_c, add_abs, chunk_of, th, in_lane, log=print, lift=None):
    """rl: rail.json rows.  th(x, z): terrain height.  in_lane(x, z, r): inside a drivable carriageway.
    lift(items): raise the terrain along [(points (k, 2), lift (k,), half width)] (tools/ramps.py overlay), for the
    embankments where the ground track has to climb to a viaduct end."""
    ways = [r for r in rl if r[0] == "way" and r[1] == "rail"]
    nodes = [r for r in rl if r[0] == "node"]
    posts, stations, runs, xings = [], [], [], []
    mat = 3                                                      # MAT_SOLID

    # streets as segments in a 30 m grid, for "is a street beneath this piece" and the ground crossings
    grid = {}
    for ei, e in enumerate(edges):
        if e["drive"] and not e["bridge"]:
            for k, ((ax, ay), (bx, by)) in enumerate(zip(e["pts"], e["pts"][1:])):
                for gx in range(int(min(ax, bx) // 30), int(max(ax, bx) // 30) + 1):
                    for gy in range(int(min(ay, by) // 30), int(max(ay, by) // 30) + 1):
                        grid.setdefault((gx, gy), []).append((ax, ay, bx, by, e["w"] / 2 + 3.0, e["w"], ei, e["cum"][k]))

    def under(x, z):
        for ax, ay, bx, by, hw, _w, _ei, _s in grid.get((int(x // 30), int(z // 30)), ()):
            dx, dy = bx - ax, by - ay
            t = max(0.0, min(1.0, ((x - ax) * dx + (z - ay) * dy) / (dx * dx + dy * dy or 1e-9)))
            if math.hypot(x - ax - dx * t, z - ay - dy * t) < hw + STEP / 2:
                return True
        return False

    nv = nd = nc = 0
    via = set()
    for _k, _kind, bridge, tunnel, pts, *fr_ in _join_bridges(ways):
        if tunnel or len(pts) < 2:
            continue
        if bridge:
            parts, pp, top = viaduct(None, pts, th, in_lane, under, fr_[0] if fr_ else (True, True))
            for x, z, _y, g in parts:
                pos, uv, col = _out(g)
                add_abs(chunk_of(x, z), mat, pos, uv, col)
            posts += pp
            runs.append(top)
            via.update((p_[0], p_[1]) for p_ in top)
            nd += 1
        else:                                                    # ground line: rails across the streets it meets
            runs.append([(round(x, 1), round(z, 1), round(th(x, z) + 0.25, 2)) for x, z, _yw, _l, _r in _pieces(pts)[0]])
            for a, b in zip(pts, pts[1:]):
                seen = set()
                for gx in range(int(min(a[0], b[0]) // 30), int(max(a[0], b[0]) // 30) + 1):
                    for gy in range(int(min(a[1], b[1]) // 30), int(max(a[1], b[1]) // 30) + 1):
                        for ax, ay, bx, by, _hw, w, ei, s0 in grid.get((gx, gy), ()):
                            if (ax, ay, bx, by) in seen:
                                continue
                            seen.add((ax, ay, bx, by))
                            p = _seg_hit(a, b, (ax, ay), (bx, by))
                            if p:
                                g = crossing(p[0], p[1], math.atan2(b[1] - a[1], b[0] - a[0]), math.atan2(by - ay, bx - ax), w)
                                add_c(chunk_of(*p), mat, *g.out())
                                xings.append((round(p[0], 1), round(p[1], 1), ei, round(s0 + math.hypot(p[0] - ax, p[1] - ay), 1),
                                              round(math.atan2(b[1] - a[1], b[0] - a[0]), 3)))
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
            if best[2]:                                          # on the viaduct: platform at deck level (the rail profile's, nearest piece)
                pos, uv, col = gp.out()
                pos = pos.copy()
                near = min((p_ for r_ in runs for p_ in r_), key=lambda p_: (p_[0] - x) ** 2 + (p_[1] - z) ** 2, default=None)
                pos[:, 1] += (near[2] - 1.26 + 0.9) if near else th(x, z) + CLEAR + 0.9
                add_abs(chunk_of(x, z), mat, pos, uv, col)
            else:
                add_c(chunk_of(x, z), mat, *gp.out())
            add_c(chunk_of(x, z), mat, *gb.out())
            stations.append((name, x, z, best[1]))
            for k in (-7.0, 0.0, 7.0):                          # the building is 22 m long: three collision circles
                posts.append((x + math.cos(best[1]) * k - math.sin(best[1]) * 12.5, z + math.sin(best[1]) * k + math.cos(best[1]) * 12.5,
                              4.2, th(x, z) - 1.0, th(x, z) + 4.5))
    lines = _chain([r for r in runs if len(r) >= 2])
    vg = {}
    for x_, z_ in via:
        vg.setdefault((int(x_ // 8), int(z_ // 8)), []).append((x_, z_))

    def keep_down(x, z):                                     # never raise a street, or the ground under the viaduct
        if in_lane(x, z, -1.0):
            return True
        return any(math.hypot(x - a, z - b) < 5.0 for cx in (-1, 0, 1) for cy in (-1, 0, 1)
                   for a, b in vg.get((int(x // 8) + cx, int(z // 8) + cy), ()))
    lines, nlift = _embank(lines, via, (lambda items: lift(items, keep_down)) if lift else None)
    log(f"[build] railway: {nlift} ground track points raised onto approach embankments; {nd} viaduct sections, {nc} ground crossings, {len(stations)} stations, {len(lines)} train lines")
    return posts, stations, {"lines": lines, "crossings": xings}


def _embank(lines, via, lift):
    """Where a viaduct ends high (a street right under its end) the ground track beside it used to stay on the ground: a
    jump of up to 6.5 m.  Raise the ground track to fall from the viaduct at G_RAIL (forward and backward pass over each
    line, viaduct points fixed), and the terrain under it with it.  -> (lines, points raised)."""
    out, items, n = [], [], 0
    for ln in lines:
        P = np.array([(p[0], p[1]) for p in ln], np.float64)
        h = np.array([p[2] for p in ln], np.float64)
        isv = np.array([(p[0], p[1]) in via for p in ln])
        if not isv.any() or isv.all():
            out.append(ln)
            continue
        ds = np.concatenate([[0.0], np.hypot(*np.diff(P, axis=0).T)])
        f = np.where(isv, h, -1e9)
        for i in range(1, len(h)):
            f[i] = max(f[i], f[i - 1] - G_RAIL * ds[i])
        for i in range(len(h) - 2, -1, -1):
            f[i] = max(f[i], f[i + 1] - G_RAIL * ds[i + 1])
        new = np.where(isv, h, np.maximum(h, f))
        up = (new - h > 0.05) & ~isv
        n += int(up.sum())
        k = 0
        while k < len(h):                                    # runs of raised ground points -> embankment pieces
            if not up[k]:
                k += 1
                continue
            j = k
            while j + 1 < len(h) and up[j + 1]:
                j += 1
            a, b = max(0, k - 1), min(len(h) - 1, j + 1)
            items.append((P[a:b + 1], np.maximum(0.0, new[a:b + 1] - h[a:b + 1]), 2.5))
            k = j + 1
        out.append([(p[0], p[1], round(float(v), 2)) for p, v in zip(ln, new)])
    if lift is not None and items:
        lift(items)
    return out, n


def _chain(runs):
    """Join way pieces that meet end to end (within 12 m) into long lines a train can run along, longest first."""
    runs = [list(r) for r in runs]
    out = []
    while runs:
        cur = runs.pop(0)
        grown = True
        while grown:
            grown = False
            for i, r in enumerate(runs):
                for rr in (r, r[::-1]):
                    if math.hypot(rr[0][0] - cur[-1][0], rr[0][1] - cur[-1][1]) < 12.0:
                        cur += rr[1:]
                    elif math.hypot(rr[-1][0] - cur[0][0], rr[-1][1] - cur[0][1]) < 12.0:
                        cur = rr[:-1] + cur
                    else:
                        continue
                    runs.pop(i)
                    grown = True
                    break
                if grown:
                    break
        out.append(cur)
    out.sort(key=lambda r: -len(r))
    return [r for r in out if len(r) >= 25]                    # at least ~200 m of track
