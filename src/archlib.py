"""Architectural elements of the photo-fitted buildings (src/photogram.py ДЕТАЛИ, tools/build_world.py photo_facade).

CATALOGUE lists the 3D elements a Skopje facade or roof can show, each with the parametric generator that builds it and the
cue the photo fit reads it from.  "fit" = measured from the photo by src/facade.py; "rule" = placed from fitted numbers by a
rule (e.g. downpipes at the eaves' corners); "gen" = the generator can build it but nothing detects it yet.
The generators: roof_mesh (any roof as the lowest of a set of planes: flat, shed, gable, hip, pyramid, mansard, gambrel,
half-hip, with eaves, fascia, gable walls, chimneys, housings, downpipes) and box / quad helpers.  numpy only.
"""
import math

import numpy as np

SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)

# (element, generator, cue, status)
CATALOGUE = [
    # --- wall plane and its depth
    ("wall plane at the OSM outline", "facade cell", "dominant wall plane", "fit"),
    ("risalit (projecting wall bay)", "depth step", "side face band, oblique view", "fit"),
    ("recessed wall bay", "depth step", "side face band, oblique view", "fit"),
    ("pilaster", "depth step", "narrow windowless column of its own colour", "fit"),
    ("pier / fin", "depth step", "narrow windowless column + side band", "fit"),
    ("stair core projecting from the wall", "depth step", "column breaking the period + side band", "fit"),
    ("lift shaft tower", "depth step", "windowless full-height column", "fit"),
    ("corner protrusion", "depth step + end face", "side band at a wall end", "fit"),
    ("inside corner notch", "depth step", "recessed end column", "fit"),
    ("bay window (erker)", "depth step per floor", "side band limited to upper floors", "gen"),
    ("cantilevered upper floors", "vertical depth step", "dark ground storey + soffit", "fit"),
    ("ground-floor recess", "vertical depth step", "dark ground storey", "fit"),
    ("arcade / colonnade", "vertical depth step + pillars", "dark ground storey with light pillars at a rhythm", "fit"),
    ("pilotis (columns under a raised block)", "vertical depth step + pillars", "as arcade", "fit"),
    ("shop front", "ground params", "ground storey breaks the column look", "fit"),
    ("set-back top floor (attic storey)", "vertical depth step", "roof line steps", "gen"),
    ("plinth / socle", "ledge box", "even band at the foot of the wall", "fit"),
    ("cornice", "ledge box", "even band under the roof line", "fit"),
    ("string course", "ledge box", "thin even band across the wall", "fit"),
    ("continuous balcony band", "ledge box", "even band across the wall at floor lines", "fit"),
    ("soffit under a protrusion", "horizontal cap", "depth change between floors", "fit"),
    ("terrace on a recessed floor", "horizontal cap", "depth change between floors", "fit"),
    ("top cap of a protrusion", "horizontal cap", "depth at the wall top", "fit"),
    ("corner end face", "vertical quad", "depth at a wall end", "fit"),
    # --- openings
    ("window opening with reveals", "cell window", "dark blob per bay column", "fit"),
    ("window glass", "cell window", "mid tones of the opening", "fit"),
    ("window frame", "cell window", "bright ring in the opening", "fit"),
    ("glazing bars / mullions", "cell window", "bright full-height columns in the opening", "fit"),
    ("transom", "cell window", "tall opening", "rule"),
    ("roller shutter / blind", "cell window", "light flat rows from the top of the opening", "fit"),
    ("window sill", "box", "opening without balcony", "rule"),
    ("balcony door", "cell window", "opening reaching the slab", "fit"),
    ("loggia", "cell recess", "wide dark opening", "fit"),
    ("curtain wall glazing", "glass cells", "glass surface class", "fit"),
    ("entrance door", "ground params", "ground storey cell", "fit"),
    ("garage door", "ground params", "ground storey cell, light flat", "fit"),
    ("lintel", "cell wall", "wall above the opening", "rule"),
    ("window surround / architrave", "frame", "frame ring", "fit"),
    ("shutters (louvred, side-hung)", "box", "coloured panels beside the opening", "gen"),
    ("window grille / bars", "posts", "bars in a ground-floor opening", "gen"),
    ("dormer window", "box + small roof", "dark blob in the roof band", "gen"),
    ("roof window (skylight)", "quad on slope", "dark blob in the roof band", "gen"),
    ("glass block wall", "glass cells", "surface class", "gen"),
    ("porthole window", "cell window", "round blob", "gen"),
    ("shop sign band", "ledge box", "even band over the ground storey", "fit"),
    # --- balconies and fixtures
    ("balcony slab", "box", "band at the foot of the cell differing from the wall", "fit"),
    ("solid balcony parapet", "box", "smooth band", "fit"),
    ("balcony railing with posts", "posts", "flickering band", "fit"),
    ("balcony side walls", "box", "solid parapet", "fit"),
    ("glazed-in balcony", "cell window", "glass in the balcony band", "fit"),
    ("French balcony", "posts", "rail across a door opening", "gen"),
    ("corner balcony", "box", "balcony in an end column", "fit"),
    ("air-conditioning unit", "box + grille", "compact light grey box", "fit"),
    ("satellite dish", "disc", "round light blob", "gen"),
    ("awning", "sloped quad", "coloured band over an opening", "gen"),
    ("canopy over the entrance", "slab", "soffit band over the ground storey", "gen"),
    ("flower boxes", "box", "green band at the sill", "gen"),
    ("laundry line", "lines", "-", "gen"),
    ("downpipe", "box", "eaves' corners", "rule"),
    ("gutter", "fascia", "eaves edge", "rule"),
    ("external stair", "steps", "diagonal band", "gen"),
    ("fire escape", "posts + slabs", "-", "gen"),
    ("drainpipe head", "box", "eaves' corners", "rule"),
    ("wall lamp", "box", "-", "gen"),
    ("house number plate", "quad", "-", "gen"),
    ("ventilation grille", "quad", "-", "gen"),
    ("intercom / mailboxes", "quad", "-", "gen"),
    ("graffiti", "decal", "colourful noise low on the wall", "gen"),
    # --- surfaces
    ("plaster", "texture", "smooth light wall", "fit"),
    ("bare concrete / prefab panels", "texture", "grey porous wall", "fit"),
    ("ceramic tiles", "texture", "periodic fine pattern", "fit"),
    ("brick", "texture", "red rough wall", "fit"),
    ("metal cladding", "texture", "light flat grey", "fit"),
    ("glass curtain wall", "texture", "dark bluish smooth", "fit"),
    ("stone cladding", "texture", "rough beige", "gen"),
    ("wood cladding", "texture", "brown striped", "gen"),
    ("per-cell paint (repainted flats)", "cell colour", "cell median colour", "fit"),
    # --- roofs
    ("flat roof", "roof planes", "level roof line, no roof band", "fit"),
    ("roof parapet / attic wall", "parapet", "flat roof", "rule"),
    ("shed (mono-pitch) roof", "roof planes", "roof line sloping one way", "fit"),
    ("gable roof", "roof planes", "triangle of the wall's colour", "fit"),
    ("gable wall infill", "roof walls", "wall under the gable", "fit"),
    ("hip roof", "roof planes", "level roof band / trapezoid", "fit"),
    ("pyramid roof", "roof planes", "hip on a square footprint", "fit"),
    ("mansard roof", "roof planes", "steep roof band on a block", "fit"),
    ("gambrel roof", "roof planes", "two-slope band", "gen"),
    ("half-hip (jerkinhead) roof", "roof planes", "clipped gable triangle", "gen"),
    ("hipped L / T roof with valleys", "roof heightfield", "hip on a non-convex footprint", "fit"),
    ("eaves overhang", "roof planes (offset outline)", "dark soffit band under the roof line", "fit"),
    ("roof underside (soffit)", "roof planes", "eaves overhang", "rule"),
    ("fascia board", "fascia", "eaves edge", "rule"),
    ("verge (gable overhang)", "roof planes", "gable roof with eaves", "rule"),
    ("chimney", "box + cap", "narrow spike on the roof line", "fit"),
    ("chimney cap", "slab", "chimney", "rule"),
    ("rooftop stair / lift housing", "box", "wide plateau on a flat roof line", "fit"),
    ("rooftop plant room", "box", "plateau", "fit"),
    ("water tank", "cylinder", "-", "gen"),
    ("solar panels", "quad on slope", "-", "gen"),
    ("antenna mast", "post", "thin spike", "gen"),
    ("barrel / vaulted roof", "roof planes (many)", "arched roof line", "gen"),
    ("dome", "roof planes (many)", "round roof line", "gen"),
    ("butterfly roof", "roof planes", "V roof line", "gen"),
    ("sawtooth roof", "roof planes", "zigzag roof line", "gen"),
    ("roof terrace railing", "posts", "-", "gen"),
    ("stepped section heights", "per-section top", "roof line steps", "gen"),
    ("ridge tiles", "ridge strip", "gable / hip ridge", "gen"),
]


def _shade(n):
    return 0.52 + 0.55 * max(0.0, float(np.dot(n, SUN)))


def _col(c, k):
    return (*[int(min(255, max(0, v * k))) for v in c], 255)


def box(cx, cz, sx, sz, h, y0, col, yaw=0.0):
    """Closed-top box -> [(pos tris), (cols)] lists (same faces and winding as build_world.box)."""
    ca, sa = math.cos(yaw), math.sin(yaw)
    w = [(cx + ca * x - sa * z, cz + sa * x + ca * z) for x, z in ((-sx / 2, -sz / 2), (sx / 2, -sz / 2), (sx / 2, sz / 2), (-sx / 2, sz / 2))]
    pos, cols = [], []
    for i in range(4):
        a, b = w[i], w[(i + 1) % 4]
        nx, nz = b[1] - a[1], -(b[0] - a[0])
        ln = math.hypot(nx, nz) or 1.0
        c = _col(col, _shade(np.array([nx / ln, 0, nz / ln])))
        pos += [(a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + h, b[1]), (a[0], y0, a[1]), (b[0], y0 + h, b[1]), (a[0], y0 + h, a[1])]
        cols += [c] * 6
    c = _col(col, _shade(np.array([0, 1.0, 0])))
    pos += [(w[0][0], y0 + h, w[0][1]), (w[1][0], y0 + h, w[1][1]), (w[2][0], y0 + h, w[2][1]),
            (w[0][0], y0 + h, w[0][1]), (w[2][0], y0 + h, w[2][1]), (w[3][0], y0 + h, w[3][1])]
    cols += [c] * 6
    return pos, cols


def _inward_normals(r):
    n = len(r)
    out = []
    for i in range(n):
        d = r[(i + 1) % n] - r[i]
        out.append(np.array([-d[1], d[0]]) / (math.hypot(*d) or 1.0))       # positive-shoelace ring: left of the edge is inside
    return out


def _offset(r, nin, e):
    """The outline pushed out by e (mitred corners, capped)."""
    q = []
    n = len(r)
    for i in range(n):
        m = nin[i - 1] + nin[i]
        den = 1.0 + float(nin[i - 1] @ nin[i])
        v = m / den if den > 0.2 else nin[i]
        q.append(r[i] - v * e)
    return np.array(q)


def _clip(poly, A, B, C):
    """Sutherland-Hodgman: the part of polygon `poly` (k, 2) where A x + B z + C <= 0."""
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        fp, fq = A * p[0] + B * p[1] + C, A * q[0] + B * q[1] + C
        if fp <= 0:
            out.append(p)
        if (fp < 0) != (fq < 0) and abs(fp - fq) > 1e-12:
            t = fp / (fp - fq)
            out.append(p + (q - p) * t)
    return out


def _area(p):
    p = np.asarray(p)
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def _seg_dist(P, r):
    """Unsigned distance of points P (m, 2) to the ring's edges."""
    d = np.full(len(P), np.inf)
    n = len(r)
    for i in range(n):
        a, b = r[i], r[(i + 1) % n]
        ab = b - a
        t = np.clip(((P - a) @ ab) / max(1e-12, ab @ ab), 0, 1)
        d = np.minimum(d, np.hypot(*(P - (a + t[:, None] * ab)).T))
    return d


def _inside(P, r):
    x, z = P[:, 0], P[:, 1]
    ins = np.zeros(len(P), bool)
    n = len(r)
    for i in range(n):
        (x1, z1), (x2, z2) = r[i], r[(i + 1) % n]
        c = ((z1 > z) != (z2 > z)) & (x < (x2 - x1) * (z - z1) / np.where(z2 != z1, z2 - z1, 1e-12) + x1)
        ins ^= c
    return ins


def _inradius(r, use=None):
    """Largest distance from the included edges' lines inside the footprint (sampled) -> m."""
    lo, hi = r.min(0), r.max(0)
    g = np.stack(np.meshgrid(np.linspace(lo[0], hi[0], 24), np.linspace(lo[1], hi[1], 24)), -1).reshape(-1, 2)
    g = g[_inside(g, r)]
    if not len(g):
        return 2.0
    nin = _inward_normals(r)
    idx = range(len(r)) if use is None else use
    d = np.min([(g - r[i]) @ nin[i] for i in idx], 0)
    return float(max(0.5, d.max()))


def planes(r, kind, rise, axis=None, high=None):
    """Roof planes (A, B, C: y = A x + B z + C over the wall top) and the cap height (None = no cap).
    -> ([(A, B, C)], cap, gable: the edges without a plane (walls rise under the roof there))."""
    n = len(r)
    nin = _inward_normals(r)
    use = list(range(n))
    if kind in ("gable", "gambrel", "halfhip") and axis is not None:
        ax = np.asarray(axis, float) / (np.hypot(*axis) or 1.0)
        par = [i for i in range(n) if abs((r[(i + 1) % n] - r[i]) @ ax) / (np.hypot(*(r[(i + 1) % n] - r[i])) or 1) > 0.7]
        if len(par) >= 2:
            use = par
    if kind == "shed" and high is not None:
        hv = np.asarray(high, float)
        low = max(range(n), key=lambda i: float(nin[i] @ hv) * np.hypot(*(r[(i + 1) % n] - r[i])))
        use = [low]
    if kind == "mansard":
        inset = min(rise * 0.55, 0.3 * min(np.ptp(r[:, 0]), np.ptp(r[:, 1])))
        k = rise / max(0.3, inset)
    elif kind == "shed":
        hv = np.asarray(high if high is not None else nin[use[0]], float)
        ext = float(np.ptp(r @ (hv / (np.hypot(*hv) or 1.0)))) or 1.0
        k = rise / ext
    else:
        k = rise / _inradius(r, use)
    pl = []
    for i in use:
        c0 = float(r[i] @ nin[i])
        pl.append((k * nin[i][0], k * nin[i][1], -k * c0))
        if kind == "gambrel":                                   # second, flatter pitch above 60 % of the rise
            k2 = k * 0.45
            pl.append((k2 * nin[i][0], k2 * nin[i][1], -k2 * c0 + 0.6 * rise * (1 - 0.45)))
    if kind == "halfhip":                                        # the gable ends clipped by a hip from 60 % of the rise
        for i in range(n):
            if i not in use:
                c0 = float(r[i] @ nin[i])
                pl.append((k * nin[i][0], k * nin[i][1], -k * c0 + 0.6 * rise))
    cap = rise if kind in ("mansard", "hip", "pyramid", "gable", "gambrel", "halfhip") else None
    gable = [i for i in range(n) if i not in use]
    return pl, cap, gable


def _height(P, pl, cap):
    h = np.min([A * P[:, 0] + B * P[:, 1] + C for A, B, C in pl], 0)
    return np.minimum(h, cap) if cap is not None else h


def _tri(pos, cols, p0, p1, p2, col, up=True):
    """One triangle with its front face up (or down) and the sun shading of its normal."""
    a, b, c = (np.array(p, float) for p in (p0, p1, p2))
    nrm = np.cross(c - a, b - a)                               # the world build's front face: (p2 - p0) x (p1 - p0)
    if (nrm[1] < 0) == up:
        b, c = c, b
        nrm = -nrm
    ln = np.linalg.norm(nrm)
    if ln < 1e-9:
        return
    pos += [tuple(a), tuple(b), tuple(c)]
    cols += [_col(col, max(0.5, min(1.15, _shade(nrm / ln) * 1.05)))] * 3


def roof_mesh(ring, y0, spec, roofc, wallc, triangulate=None):
    """A whole roof from its fitted spec (kind, rise, axis, high, eave, chim, hous) on the wall top y0 ->
    {"roof": (pos, cols), "wall": (pos, cols), "solid": (pos, cols)} (lists; the caller adds uv and its materials).
    Convex outlines: exact plane pieces (each plane clipped to where it is the lowest).  Other outlines: a fine heightfield of
    the distance to the outline (a hipped roof with valleys)."""
    r = np.asarray(ring, float)
    if _area(r) < 0:
        r = r[::-1]
    kind, rise = spec.get("kind", "hip"), float(spec.get("rise", 2.0))
    eave = float(np.clip(spec.get("eave", 0.0), 0.0, 1.2))
    out = {"roof": ([], []), "wall": ([], []), "solid": ([], [])}
    if kind == "flat" or rise < 0.3:                             # the flat roof itself is the world build's; only what stands on it
        _on_roof(out["solid"], spec, lambda P: np.full(len(np.atleast_2d(P)), y0), y0, wallc)
        return out
    hull = _hull(r)
    convex = _area(r) > 0.97 * _area(hull)
    if not convex and kind in ("gable", "gambrel", "halfhip", "shed"):
        kind = "hip"
    nin = _inward_normals(r)
    pl, cap, gable = planes(r, kind, rise, spec.get("axis"), spec.get("high"))
    pl = [(A, B, C + y0) for A, B, C in pl]
    capy = y0 + cap if cap is not None else None
    ro = _offset(r, nin, eave) if eave > 0 else r
    rpos, rcol = out["roof"]
    under = []
    if convex:
        for i, (A, B, C) in enumerate(pl):
            poly = [np.array(p) for p in ro]
            for j, (A2, B2, C2) in enumerate(pl):
                if j != i and poly:
                    poly = _clip(poly, A - A2, B - B2, C - C2)
            if capy is not None and poly:
                poly = _clip(poly, A, B, C - capy)
            if len(poly) >= 3 and abs(_area(poly)) > 1e-3:
                ys = [A * p[0] + B * p[1] + C for p in poly]
                for k in range(1, len(poly) - 1):
                    tri = [(poly[0][0], ys[0], poly[0][1]), (poly[k][0], ys[k], poly[k][1]), (poly[k + 1][0], ys[k + 1], poly[k + 1][1])]
                    _tri(rpos, rcol, *tri, roofc)
                    under.append(tri)
        if capy is not None:
            poly = [np.array(p) for p in ro]
            for A, B, C in pl:
                if poly:
                    poly = _clip(poly, -A, -B, capy - C)
            if len(poly) >= 3 and abs(_area(poly)) > 1e-3:
                for k in range(1, len(poly) - 1):
                    _tri(rpos, rcol, (poly[0][0], capy, poly[0][1]), (poly[k][0], capy, poly[k][1]), (poly[k + 1][0], capy, poly[k + 1][1]), roofc)
    else:
        if triangulate is None:
            return None
        verts, idx = triangulate([tuple(p) for p in ro], [])
        V = np.asarray(verts, float)
        tris = [V[idx[k:k + 3]] for k in range(0, len(idx), 3)]
        fine = []
        while tris:
            t = tris.pop()
            e = [np.hypot(*(t[(m + 1) % 3] - t[m])) for m in range(3)]
            m = int(np.argmax(e))
            if e[m] > 0.9 and len(fine) + len(tris) < 6000:
                a_, b_, c_ = t[m], t[(m + 1) % 3], t[(m + 2) % 3]
                mid = (a_ + b_) / 2
                tris += [np.array([a_, mid, c_]), np.array([mid, b_, c_])]
            else:
                fine.append(t)
        k = rise / (cap if cap else rise) * (pl[0][0] ** 2 + pl[0][1] ** 2) ** 0.5 if pl else 1.0
        for t in fine:
            sd = _seg_dist(t, r) * np.where(_inside(t, r), 1.0, -1.0)
            ys = y0 + np.minimum(k * sd, cap if cap is not None else 1e9)
            tri = [(t[m][0], ys[m], t[m][1]) for m in range(3)]
            _tri(rpos, rcol, *tri, roofc)
            under.append(tri)
    if eave > 0:                                                 # the overhang's underside, in shade
        for tri in under:
            _tri(rpos, rcol, *tri, [c * 0.6 for c in roofc], up=False)
    H = (lambda P: _height(np.atleast_2d(P), pl, capy)) if convex else \
        (lambda P: y0 + np.minimum(k * _seg_dist(np.atleast_2d(P), r) * np.where(_inside(np.atleast_2d(P), r), 1.0, -1.0),
                                   cap if cap is not None else 1e9))
    # gable walls: the wall goes on up to the roof wherever the roof is above the wall top on the outline
    wpos, wcol = out["wall"]
    n = len(r)
    for i in range(n):
        a, b = r[i], r[(i + 1) % n]
        ln = float(np.hypot(*(b - a)))
        m = max(1, int(math.ceil(ln / 0.4)))
        P = a + (b - a) * (np.arange(m + 1) / m)[:, None]
        hs = H(P)
        if hs.max() < y0 + 0.05:
            continue
        nrm = np.array([(b - a)[1], 0, -(b - a)[0]]) / max(ln, 1e-6)
        c = _col(wallc, _shade(nrm))
        for q in range(m):
            h0, h1 = max(y0, hs[q]), max(y0, hs[q + 1])
            if h0 - y0 < 0.01 and h1 - y0 < 0.01:
                continue
            p0, p1 = P[q], P[q + 1]
            wpos += [(p0[0], y0, p0[1]), (p1[0], y0, p1[1]), (p1[0], h1, p1[1]), (p0[0], y0, p0[1]), (p1[0], h1, p1[1]), (p0[0], h0, p0[1])]
            wcol += [c] * 6
    spos, scol = out["solid"]
    trim = [min(255, v * 0.95) for v in (236, 234, 228)] if np.mean(wallc) < 150 else [v * 0.8 for v in roofc]
    if eave > 0:                                                 # fascia / gutter board round the overhang
        no = len(ro)
        for i in range(no):
            a, b = ro[i], ro[(i + 1) % no]
            ln = float(np.hypot(*(b - a)))
            m = max(1, int(math.ceil(ln / 0.6)))
            P = a + (b - a) * (np.arange(m + 1) / m)[:, None]
            hs = H(P)
            nrm = np.array([(b - a)[1], 0, -(b - a)[0]]) / max(ln, 1e-6)
            c = _col(trim, _shade(nrm))
            for q in range(m):
                p0, p1 = P[q], P[q + 1]
                spos += [(p0[0], hs[q] - 0.18, p0[1]), (p1[0], hs[q + 1] - 0.18, p1[1]), (p1[0], hs[q + 1], p1[1]),
                         (p0[0], hs[q] - 0.18, p0[1]), (p1[0], hs[q + 1], p1[1]), (p0[0], hs[q], p0[1])]
                scol += [c] * 6
        if n <= 8:                                               # downpipes at the outline's corners under the eaves
            for i in range(n):
                p = r[i] - (nin[i - 1] + nin[i]) * 0.08
                hp, cl = box(p[0], p[1], 0.09, 0.09, float(H(r[i])[0]) - 0.15 + 0.3, -0.3, trim)
                spos += hp
                scol += cl
    _on_roof(out["solid"], spec, H, y0, wallc)
    return out


def _on_roof(solid, spec, H, y0, wallc):
    spos, scol = solid
    for x, z, w, top in spec.get("chim", []):                    # chimneys with a cap slab
        hr = float(H(np.array([x, z]))[0])
        t = min(max(top, hr + 0.8), hr + 2.5)
        hp, cl = box(x, z, max(0.35, w), max(0.35, w), t - hr + 0.3, hr - 0.3, [v * 0.95 for v in wallc])
        spos += hp
        scol += cl
        hp, cl = box(x, z, max(0.35, w) + 0.12, max(0.35, w) + 0.12, 0.08, t, (90, 90, 92))
        spos += hp
        scol += cl
    for x, z, sx, sz, top, yaw in spec.get("hous", []):         # rooftop stair / lift housings
        hp, cl = box(x, z, sx, sz, max(1.5, top - y0), y0, [v * 0.97 for v in wallc], yaw)
        spos += hp
        scol += cl


def _hull(r):
    p = sorted(map(tuple, r))
    if len(p) < 3:
        return np.array(p)

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for q in p:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    for q in reversed(p):
        while len(up) >= 2 and cr(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return np.array(lo[:-1] + up[:-1])
