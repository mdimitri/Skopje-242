"""Fire escapes and rooftop bike jumps.

build() picks flat-roofed buildings that get a zig-zag fire escape (walkable / rideable from the ground to the roof),
then links nearby equipped roofs with launch ramps (one on each side, so a jump always has a way back; every equipped
roof also has the stairs down).  Returns the walkable surfaces for the game (`World.plat_h`) and emits the meshes.

Surfaces ("plats"):  (0, cx, cy, ux, uy, hl, hw, ha, hb)  oriented rectangle, height ha -> hb along (ux, uy), half length hl, half width hw
                     (1, ring, h)                         a flat roof at absolute height h
"""
import math
import random

import numpy as np

import par
from progress import frac, span
from furniture import G

FW = 1.4                    # flight width
LD = 2.0                    # landing length
V0 = 0.5                    # gap between wall and stairs
SLOPE = 0.62                # rise per metre of flight
FLOOR = 3.2
STEEL, STEEL_D, RAIL = (104, 88, 78), (70, 62, 58), (62, 66, 74)
RAMP, RAMP_E = (214, 138, 42), (236, 232, 222)
RAMP_LEN, RAMP_HW, RAMP_RISE = 4.0, 1.3, 1.3
JUMP_V, GRAV = 9.0, 9.81    # the speed a rider is assumed to bring, and gravity (World.G)


def _pip(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _solid(g, pts, col, ref):
    """Convex planar polygon (fan), wound and lit as seen from outside (away from `ref`)."""
    a, b, c = np.array(pts[0], float), np.array(pts[1], float), np.array(pts[2], float)
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n)
    if ln < 1e-9:
        return
    n /= ln
    ctr = np.mean(np.array(pts, float), axis=0)
    if np.dot(n, ctr - np.array(ref, float)) < 0:
        n = -n
        pts = pts[::-1]
    for i in range(1, len(pts) - 1):
        g.tri(pts[0], pts[i], pts[i + 1], col, tuple(n))


def _prism(g, a, b, hw, th, col, up=(0.0, 1.0, 0.0)):
    """Bar from a to b (x, y, z), `hw` half wide, `th` thick (hangs below the line)."""
    a, b = np.array(a, float), np.array(b, float)
    d = b - a
    w = np.cross(d, up)
    ln = np.linalg.norm(w)
    if ln < 1e-9:
        return
    w = w / ln * hw
    dn = np.array(up, float) * th
    ref = (a + b) / 2 - dn / 2
    top = [a - w, a + w, b + w, b - w]
    bot = [p - dn for p in top]
    _solid(g, top, col, ref)
    _solid(g, bot, col, ref)
    for i in range(4):
        _solid(g, [top[i], top[(i + 1) % 4], bot[(i + 1) % 4], bot[i]], col, ref)


def _slab(g, cx, y0, cz, ux, uz, hl, hw, th, col):
    """Flat horizontal rectangle slab with its top at y0, half length hl along (ux, uz), half width hw."""
    vx, vz = -uz, ux
    c = [(cx + ux * s + vx * t, cz + uz * s + vz * t) for s, t in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw))]
    top = [(x, y0, z) for x, z in c]
    bot = [(x, y0 - th, z) for x, z in c]
    ref = (cx, y0 - th / 2, cz)
    _solid(g, top, col, ref)
    _solid(g, bot, col, ref)
    for i in range(4):
        _solid(g, [top[i], top[(i + 1) % 4], bot[(i + 1) % 4], bot[i]], col, ref)


def jump_ok(gap, rise, dh, v=JUMP_V):
    """A rider leaving a ramp lip of height `rise` at speed v: clears the far lip (dh higher) and lands on the far roof."""
    vz = v * rise / RAMP_LEN
    t = gap / v
    if rise + vz * t - 0.5 * GRAV * t * t < dh + 0.2:
        return False
    t2 = (vz + math.sqrt(vz * vz + 2 * GRAV * (rise - dh))) / GRAV
    return gap + 0.8 <= v * t2 <= gap + 6.5


def _stairs(g, M, u, n, nf, fh, hg0, L):
    """Mesh of one fire escape.  P(s, v) = M + u*s + n*v on the plan (M on the wall at s = 0); heights absolute."""
    def P(s, v, h):
        return (M[0] + u[0] * s + n[0] * v, h, M[1] + u[1] * s + n[1] * v)
    for j in range(nf):
        z0, z1 = hg0 + j * fh, hg0 + (j + 1) * fh
        vc = V0 + FW / 2 + (FW if j % 2 else 0.0)
        s0, s1 = (L, 0.0) if j % 2 else (0.0, L)
        a, b = P(s0, vc, z0), P(s1, vc, z1)
        _prism(g, a, b, FW / 2, 0.07, STEEL)
        for sd in (-1, 1):                                         # stringer, rail and a post at each end of the flight
            off = sd * (FW / 2 - 0.04)
            pa, pb = P(s0, vc + off, z0), P(s1, vc + off, z1)
            _prism(g, pa, pb, 0.03, 0.28, STEEL_D)
            ra, rb = (pa[0], pa[1] + 0.95, pa[2]), (pb[0], pb[1] + 0.95, pb[2])
            _prism(g, ra, rb, 0.025, 0.05, RAIL)
            for q in (pa, pb):
                _prism(g, (q[0], q[1], q[2]), (q[0], q[1] + 0.95, q[2]), 0.025, 0.05, RAIL, up=(1.0, 0.0, 0.0))
        # the landing at the top of this flight
        top = j == nf - 1
        sl = (L + LD / 2) if j % 2 == 0 else -LD / 2
        v_lo = 0.0 if top else V0
        vmid, hv = (v_lo + V0 + 2 * FW) / 2, (V0 + 2 * FW - v_lo) / 2
        c = P(sl, vmid, z1)
        _slab(g, c[0], z1, c[2], u[0], u[1], LD / 2, hv, 0.1, STEEL)
        far = V0 + 2 * FW
        outer = 1 if j % 2 == 0 else -1
        for (s_a, v_a, s_b, v_b) in ((sl - LD / 2, far, sl + LD / 2, far), (sl + outer * LD / 2, V0 if not top else 0.0, sl + outer * LD / 2, far)):
            pa, pb = P(s_a, v_a, z1 + 0.95), P(s_b, v_b, z1 + 0.95)
            _prism(g, pa, pb, 0.025, 0.05, RAIL)
            for q in (pa, pb):
                _prism(g, (q[0], q[1] - 0.95, q[2]), (q[0], q[1], q[2]), 0.025, 0.05, RAIL, up=(1.0, 0.0, 0.0))
        for s_c in (sl - outer * LD / 2 * 0.9, sl + outer * LD / 2 * 0.9):   # legs down to the ground
            q = P(s_c, far - 0.1, z1 - 0.1)
            _prism(g, (q[0], hg0 - 0.2, q[2]), (q[0], q[1], q[2]), 0.05, 0.1, STEEL_D, up=(1.0, 0.0, 0.0))


def _ramp(g, pA, d, base, rise):
    """Wedge ending at the lip pA, going up along d from height `base`."""
    ex, ez = -d[1], d[0]
    x1, z1 = pA[0] - d[0] * 0.3, pA[1] - d[1] * 0.3
    x0, z0 = x1 - d[0] * RAMP_LEN, z1 - d[1] * RAMP_LEN
    lo = [(x0 + ex * RAMP_HW, base, z0 + ez * RAMP_HW), (x0 - ex * RAMP_HW, base, z0 - ez * RAMP_HW)]
    hi = [(x1 - ex * RAMP_HW, base + rise, z1 - ez * RAMP_HW), (x1 + ex * RAMP_HW, base + rise, z1 + ez * RAMP_HW)]
    ref = ((x0 + x1) / 2, base + rise / 3, (z0 + z1) / 2)
    _solid(g, lo + hi, RAMP, ref)
    for sd, i in ((1, 0), (-1, 1)):                                        # the two side triangles
        _solid(g, [lo[i], (x1 + ex * RAMP_HW * sd, base, z1 + ez * RAMP_HW * sd), hi[1 - i]], RAMP, ref)
    _solid(g, [(x1 + ex * RAMP_HW, base, z1 + ez * RAMP_HW), (x1 - ex * RAMP_HW, base, z1 - ez * RAMP_HW), hi[0], hi[1]], RAMP, ref)   # the face below the lip
    for sd in (-1, 1):                                                     # white edge lines
        a = (x0 + ex * (RAMP_HW - 0.1) * sd, base + 0.02, z0 + ez * (RAMP_HW - 0.1) * sd)
        b = (x1 + ex * (RAMP_HW - 0.1) * sd, base + rise + 0.02, z1 + ez * (RAMP_HW - 0.1) * sd)
        _prism(g, a, b, 0.05, 0.02, RAMP_E)


def build(buildings, T, bld_a, occ_a, surf_a, hg_a, cell, hx, hy, add, chunk_of, mat, share=1.0, log=print, seed=2420):
    """-> (plats, info).  share: chance that an eligible building gets an escape (when a free wall exists)."""
    ncy, ncx = bld_a.shape

    def free_pt(x, y):
        ix, iy = int((x + hx) / cell), int((y + hy) / cell)
        return 0 <= ix < ncx and 0 <= iy < ncy and not bld_a[iy, ix] and not occ_a[iy, ix] and (surf_a[iy, ix] == 0 or (surf_a[iy, ix] == 3 and (hg_a[iy, ix] & 3) == 2))

    def inside_all(pts, ring):
        return all(_pip(x, y, ring) for x, y in pts)

    rr = random.Random(seed)
    plats, info = [], {"stairs": [], "jumps": []}
    import collections
    rej = collections.Counter()
    eq = []                                                     # equipped buildings
    cand = [i for i, b in enumerate(buildings)
            if b["tri"] and 7.0 <= b["h"] <= 28.0 and (b["area"] >= 240 or b["h"] >= 11.0) and len(b["ring"]) >= 4]
    for i in span(cand, 0.0, 0.6, "fire escapes"):
        b = buildings[i]
        ring = [tuple(p) for p in b["ring"]]
        if rr.random() > share:
            continue
        r_ = np.asarray(ring, float)
        base = float(np.mean(T.h(r_[:, 0], r_[:, 1])))
        roof = base + b["h"]
        edges = []
        for k in range(len(ring)):
            ax, ay = ring[k]
            bx, by = ring[(k + 1) % len(ring)]
            ln = math.hypot(bx - ax, by - ay)
            if ln >= 6.5:
                edges.append((ln, k))
        rr.shuffle(edges)
        for ln, k in edges:
            ax, ay = ring[k]
            bx, by = ring[(k + 1) % len(ring)]
            e = ((bx - ax) / ln, (by - ay) / ln)
            n = (e[1], -e[0])
            mx, my = (ax + bx) / 2, (ay + by) / 2
            if _pip(mx + n[0] * 0.6, my + n[1] * 0.6, ring):
                n = (-n[0], -n[1])
            u = e if rr.random() < 0.5 else (-e[0], -e[1])
            hg0 = float(T.hs(mx + n[0] * (V0 + FW / 2), my + n[1] * (V0 + FW / 2)))
            nf = max(2, int(round((roof - hg0) / FLOOR)))
            fh = (roof - hg0) / nf
            if not 2.6 <= fh <= 3.8:
                rej['fh'] += 1
                continue
            L = fh / SLOPE
            M = (mx - u[0] * (L / 2), my - u[1] * (L / 2))              # s = 0 at the toe, the run centred on the wall
            ok = True
            why = ''
            for s in np.arange(-LD - 0.3, L + LD + 0.31, 1.0):
                for v in np.arange(0.2, V0 + 2 * FW + 0.6, 0.9):
                    x, y = M[0] + u[0] * s + n[0] * v, M[1] + u[1] * s + n[1] * v
                    if (v > 1.0 and not free_pt(x, y)) or _pip(x, y, ring):
                        why = 'pip' if _pip(x, y, ring) else 'bld' if bld_a[int((y + hy) / cell), int((x + hx) / cell)] else 'occ' if occ_a[int((y + hy) / cell), int((x + hx) / cell)] else 'surf'
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                rej['free:' + why] += 1
                continue
            g = G()
            _stairs(g, M, u, n, nf, fh, hg0, L)
            add(chunk_of(mx, my), mat, *g.out())
            for j in range(nf):                                            # walkable surfaces
                vc = V0 + FW / 2 + (FW if j % 2 else 0.0)
                du = -1.0 if j % 2 else 1.0
                cx = M[0] + u[0] * L / 2 + n[0] * vc
                cy = M[1] + u[1] * L / 2 + n[1] * vc
                plats.append((0, cx, cy, u[0] * du, u[1] * du, L / 2, FW / 2, hg0 + j * fh, hg0 + (j + 1) * fh))
                top = j == nf - 1
                sl = (L + LD / 2) if j % 2 == 0 else -LD / 2
                v_lo = 0.0 if top else V0
                vmid, hv = (v_lo + V0 + 2 * FW) / 2, (V0 + 2 * FW - v_lo) / 2
                plats.append((0, M[0] + u[0] * sl + n[0] * vmid, M[1] + u[1] * sl + n[1] * vmid, u[0], u[1], LD / 2, hv,
                              hg0 + (j + 1) * fh, hg0 + (j + 1) * fh))
            top_s = (L + LD / 2) if (nf - 1) % 2 == 0 else -LD / 2
            att = (M[0] + u[0] * top_s, M[1] + u[1] * top_s)
            eq.append((i, ring, roof, att))
            plats.append((1, [(float(x), float(y)) for x, y in ring], float(roof)))
            info["stairs"].append({"toe": [M[0] + n[0] * (V0 + FW / 2), M[1] + n[1] * (V0 + FW / 2)], "floors": nf, "roof": roof,
                                   "u": list(u), "n": list(n), "b": i})
            break
    log(f"[build] fire escapes: {len(eq)} of {len(cand)} eligible buildings ({len(buildings)} total)")

    # ---- jumps between equipped roofs ----------------------------------------------------------------
    def samples(ring):
        pts, nrm = [], []
        for k in range(len(ring)):
            ax, ay = ring[k]
            bx, by = ring[(k + 1) % len(ring)]
            ln = math.hypot(bx - ax, by - ay)
            if ln < 1.0:
                continue
            e = ((bx - ax) / ln, (by - ay) / ln)
            n = (e[1], -e[0])
            if _pip((ax + bx) / 2 + n[0] * 0.5, (ay + by) / 2 + n[1] * 0.5, ring):
                n = (-n[0], -n[1])
            for t in np.arange(1.0, ln - 0.9, 1.5):
                pts.append((ax + e[0] * t, ay + e[1] * t))
                nrm.append(n)
        return np.array(pts).reshape(-1, 2), np.array(nrm).reshape(-1, 2)

    gridb = {}
    for q, (i, ring, roof, att) in enumerate(eq):
        c = np.mean(np.asarray(ring, float), axis=0)
        gridb.setdefault((int(c[0] // 40), int(c[1] // 40)), []).append(q)
    smp = {}
    used = {}
    njump = 0
    st = {'near': 0, 'gap': 0}
    for q, (i, ring, roof, att) in enumerate(span(eq, 0.6, 1.0, "roof jumps")):
        c = np.mean(np.asarray(ring, float), axis=0)
        near = [o for dx in (-1, 0, 1) for dy in (-1, 0, 1) for o in gridb.get((int(c[0] // 40) + dx, int(c[1] // 40) + dy), ()) if o > q]
        for o in near:
            if used.get(q, 0) >= 2 or used.get(o, 0) >= 2:
                continue
            _, ringB, roofB, attB = eq[o]
            if q not in smp:
                smp[q] = samples(ring)
            if o not in smp:
                smp[o] = samples(ringB)
            pa, na = smp[q]
            pb, nb = smp[o]
            if not len(pa) or not len(pb):
                continue
            dv = pb[None, :, :] - pa[:, None, :]
            dist = np.hypot(dv[..., 0], dv[..., 1])
            dd = dv / np.maximum(dist[..., None], 1e-6)
            ok = (dist >= 2.0) & (dist <= 8.0) & ((dd * na[:, None, :]).sum(-1) >= 0.8) & ((-dd * nb[None, :, :]).sum(-1) >= 0.8)
            dh = roofB - roof
            st['near'] += 1
            st['gap'] += int(ok.any())
            if dh > 1.5 or dh < -2.0 or not ok.any():
                continue
            for ia, ib in zip(*np.nonzero(ok)):
                pA, pB, d, gap = pa[ia], pb[ib], dd[ia, ib], dist[ia, ib]
                riseA = RAMP_RISE + min(1.5, max(0.0, dh))
                riseB = RAMP_RISE + min(1.5, max(0.0, -dh))
                if not (jump_ok(gap, riseA, dh) and jump_ok(gap, riseB, -dh)):
                    st['phys'] = st.get('phys', 0) + 1
                    continue
                if math.hypot(pA[0] - att[0], pA[1] - att[1]) < 6 or math.hypot(pB[0] - attB[0], pB[1] - attB[1]) < 6:
                    continue
                e = (-d[1], d[0])
                run_a = [(pA[0] - d[0] * k + e[0] * s, pA[1] - d[1] * k + e[1] * s) for k in (1.0, 2.5, 4.0) for s in (-1.0, 1.0)]
                run_b = [(pB[0] + d[0] * k + e[0] * s, pB[1] + d[1] * k + e[1] * s) for k in (1.0, 3.0, 4.8) for s in (-1.0, 1.0)]
                if not (inside_all(run_a, ring) and inside_all(run_b, ringB)):
                    st['run'] = st.get('run', 0) + 1
                    continue
                mid = [(pA[0] + d[0] * t, pA[1] + d[1] * t) for t in np.arange(0.8, gap - 0.7, 1.0)]
                if any(not free_pt(x, y) and bld_a[min(ncy - 1, max(0, int((y + hy) / cell))), min(ncx - 1, max(0, int((x + hx) / cell)))] for x, y in mid):
                    continue
                for (p_, dd_, base_, rise_, ring_) in ((pA, d, roof, riseA, ring), (pB, -d, roofB, riseB, ringB)):
                    g = G()
                    _ramp(g, p_, dd_, base_, rise_)
                    add(chunk_of(float(p_[0]), float(p_[1])), mat, *g.out())
                    cx_, cy_ = p_[0] - dd_[0] * (0.3 + RAMP_LEN / 2), p_[1] - dd_[1] * (0.3 + RAMP_LEN / 2)
                    plats.append((0, float(cx_), float(cy_), float(dd_[0]), float(dd_[1]), RAMP_LEN / 2, RAMP_HW, base_, base_ + rise_))
                used[q] = used.get(q, 0) + 1
                used[o] = used.get(o, 0) + 1
                njump += 1
                info["jumps"].append({"a": [float(pA[0]), float(pA[1])], "b": [float(pB[0]), float(pB[1])], "d": [float(d[0]), float(d[1])],
                                      "gap": float(gap), "ha": roof, "hb": roofB, "ra": riseA, "rb": riseB})
                break
    log(f"[build] escape rejections: {dict(rej)}")
    log(f"[build] jump search: {len(eq)} equipped, near pairs {st['near']}, with a gap match {st['gap']}, {st}")
    log(f"[build] roof jumps: {njump} pairs (two ramps each)")
    return plats, info
