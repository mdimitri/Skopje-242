"""Places of worship as procedural models instead of plain boxes: Orthodox churches (body, east apse, gable / cross roofs,
drum + dome, west bell tower), Catholic churches (steep nave, tall campanile with spire), small Protestant halls, mosques
(prayer hall, octagonal drum + lead dome or hipped roof, domed portico, minaret with a balcony and pencil cap) and türbes.

kind(tags) -> spec or None; mesh(spec, ring, shade) -> (pos, uv, col) relative to the building's base, for MAT_SOLID.
Shapes come from the footprint's oriented box and the OSM tags; the notable Skopje buildings (by wikidata) get their real
layout: St. Clement's rotunda of domes and vaults, Mustafa Pasha's single big dome, Isa Bey's two domes, Sultan Murat's
hipped roof, the half-sunk St. Saviour. Every part but a minaret sits inside the oriented box, and no two faces share a plane."""
import math

import numpy as np

QIBLA = (math.sin(math.radians(137)), -math.cos(math.radians(137)))      # Skopje -> Mecca, +x east, +y south
EAST = (1.0, 0.0)
LEAD, COPPER, TILE = (128, 134, 142), (112, 150, 132), (176, 90, 60)
STONE, OCHRE, CREAM, WHITE = (200, 176, 146), (226, 204, 166), (236, 228, 212), (232, 230, 224)

LANDMARK = {                                     # wikidata -> overrides (looked up: Wikipedia / heritage pages)
    "Q1758749": {"k": "rotunda"},                # Soborna crkva Sv. Kliment Ohridski: 36 x 36 m rotunda of domes and great arches
                                                 # (street photos: honey stone and brick walls, green copper vaults with white rims)
    "Q1267418": {"k": "mosque", "dome": 1, "minaret": 47.0, "wall": (214, 192, 160)},   # Mustafa Pasha: 16.3 m dome, 47 m minaret
    "Q1509599": {"k": "mosque", "dome": 2},      # Isa Bey: two domes in a row (zaviye plan)
    "Q2121610": {"k": "mosque", "dome": 0, "minaret": 38.0},   # Sultan Murat (Hünkar): hipped tiled roof
    "Q3324875": {"k": "mosque", "dome": 0},      # Murat Pasha: hipped roof after the rebuild
    "Q1283775": {"k": "sunk"},                   # Sv. Spas: half sunk in the ground, low plain roof, no dome
    "Q11737299": {"k": "modcath"},               # Sacred Heart cathedral (1973-77, Mickovski): white modernist concrete, vertical
                                                 # fins, flat stepped roofs, a free-standing concrete bell tower
    "Q3406585": {"k": "orthodox", "tower": 1},   # Sv. Dimitrija: domed church with a bell tower
}


BY_ID = {175265102: {"k": "belfry", "h": 45.0, "wall": (196, 158, 118), "cap": (82, 122, 102)}}   # Sv. Kliment's 45 m belfry


def kind(t, oid=None):
    """The model kind of a building from its tags (and OSM id), or None (an ordinary building)."""
    lm = BY_ID.get(oid) or LANDMARK.get(t.get("wikidata", ""))
    if lm:
        return dict(lm)
    if t.get("tower:type") == "bell_tower":
        return {"k": "belfry"}
    b, rel, den = t.get("building", ""), t.get("religion", ""), t.get("denomination", "")
    name = t.get("name", "").lower()
    if "турбе" in name or b == "tomb":
        return {"k": "turbe"}
    if b == "mosque" or rel == "muslim" or "џамија" in name:
        return {"k": "mosque"}
    if "orthodox" in den or (not den and rel == "christian" and b in ("church", "yes") and ("св" in name or "црква" in name)):
        return {"k": "orthodox"}
    if den == "roman_catholic" or b == "cathedral":
        return {"k": "catholic"}
    if b in ("church", "chapel"):
        return {"k": "hall"}
    return None


def frame(ring, axis):
    """Minimum-area oriented box of the ring, its long-ish axis A turned towards `axis` -> (c, A, N, L, W, fill ratio)."""
    r = np.asarray(ring, float)
    best = None
    for i in range(len(r)):
        d = r[(i + 1) % len(r)] - r[i]
        if np.hypot(*d) < 0.3:
            continue
        A = d / np.hypot(*d)
        N = np.array([-A[1], A[0]])
        u, v = r @ A, r @ N
        ar = (u.max() - u.min()) * (v.max() - v.min())
        if best is None or ar < best[0]:
            best = (ar, A, N, u, v)
    ar, A, N, u, v = best
    if abs(N @ axis) > abs(A @ axis):              # use the box axis closest to east / the qibla as A
        A, N, u, v = N, A, v, u
    if A @ axis < 0:
        A, u = -A, -u
    N = np.array([-A[1], A[0]])
    v = r @ N
    c = A * (u.max() + u.min()) / 2 + N * (v.max() + v.min()) / 2
    x, y = r[:, 0], r[:, 1]
    area = abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2
    return c, A, N, float(u.max() - u.min()), float(v.max() - v.min()), area / max(ar, 1e-6)


def tag_h(t):
    try:
        return float(str(t.get("height", "")).replace("m", "").strip())
    except ValueError:
        try:
            return float(t.get("building:levels")) * 3.1 + 1.0
        except (TypeError, ValueError):
            return None


class Mesh:
    def __init__(self, c, A, N, shade):
        self.c, self.A, self.N, self.shade = c, A, N, shade
        self.P, self.C = [], []

    def w(self, p):                                # frame (n, a, y) -> world (x, y, z)
        q = self.c + self.N * p[0] + self.A * p[1]
        return (q[0], p[2], q[1])

    def tri(self, a, b, c, col, out):
        """One triangle (frame points), wound like build_world.box (cross product points inside), shaded by its normal."""
        a, b, c = self.w(a), self.w(b), self.w(c)
        nn = np.cross(np.subtract(b, a), np.subtract(c, a))
        ln = np.linalg.norm(nn)
        if ln < 1e-9:
            return
        o = self.w(out)
        o = np.subtract(o, self.w((0, 0, 0)))
        if np.dot(nn, o) > 0:
            b, c = c, b
            nn = -nn
        sh = self.shade(-nn / ln)
        self.P += [a, b, c]
        self.C += [(*[min(255, int(v * sh)) for v in col], 255)] * 3

    def quad(self, a, b, c, d, col, out):
        self.tri(a, b, c, col, out)
        self.tri(a, c, d, col, out)

    def prism(self, pts, y0, y1, col, top=True):
        """Upright prism over a frame polygon [(n, a)]."""
        cn, ca = np.mean([p[0] for p in pts]), np.mean([p[1] for p in pts])
        for i in range(len(pts)):
            (n0, a0), (n1, a1) = pts[i], pts[(i + 1) % len(pts)]
            mn, ma = (n0 + n1) / 2 - cn, (a0 + a1) / 2 - ca
            self.quad((n0, a0, y0), (n1, a1, y0), (n1, a1, y1), (n0, a0, y1), col, (mn, ma, 0))
        if top:
            for i in range(1, len(pts) - 1):
                self.tri((*pts[0], y1), (*pts[i], y1), (*pts[i + 1], y1), col, (0, 0, 1))

    def rect(self, n0, n1, a0, a1, y0, y1, col, top=True):
        self.prism([(n0, a0), (n1, a0), (n1, a1), (n0, a1)], y0, y1, col, top)

    def ngon(self, cn, ca, r, k, a0=0.0, a1=2 * math.pi):
        full = abs(a1 - a0 - 2 * math.pi) < 1e-6
        m = k if full else k + 1
        return [(cn + r * math.cos(a0 + (a1 - a0) * i / k), ca + r * math.sin(a0 + (a1 - a0) * i / k)) for i in range(m)]

    def dome(self, cn, ca, y0, r, h, col, k=10, rings=4, a0=0.0, a1=2 * math.pi):
        """(Part of) a dome: rings of quads from the springing circle to the crown."""
        for j in range(rings):
            t0, t1 = math.pi / 2 * j / rings, math.pi / 2 * (j + 1) / rings
            r0, r1, y_0, y_1 = r * math.cos(t0), r * math.cos(t1), y0 + h * math.sin(t0), y0 + h * math.sin(t1)
            for i in range(k):
                b0, b1 = a0 + (a1 - a0) * i / k, a0 + (a1 - a0) * (i + 1) / k
                bm = (b0 + b1) / 2
                p = [(cn + rr * math.cos(b), ca + rr * math.sin(b), yy) for rr, yy, b in ((r0, y_0, b0), (r0, y_0, b1), (r1, y_1, b1), (r1, y_1, b0))]
                o = (math.cos(bm) * math.cos(t0), math.sin(bm) * math.cos(t0), math.sin((t0 + t1) / 2))
                if j == rings - 1:
                    self.tri(p[0], p[1], p[2], col, o)
                else:
                    self.quad(*p, col, o)

    def cone(self, cn, ca, y0, r, h, col, k=8):
        for i in range(k):
            b0, b1 = 2 * math.pi * i / k, 2 * math.pi * (i + 1) / k
            bm = (b0 + b1) / 2
            self.tri((cn + r * math.cos(b0), ca + r * math.sin(b0), y0), (cn + r * math.cos(b1), ca + r * math.sin(b1), y0),
                     (cn, ca, y0 + h), col, (math.cos(bm), math.sin(bm), 0.3))

    def gable(self, n0, n1, a0, a1, y0, rise, col, wall, along_a=True):
        """Pitched roof over a frame rectangle, ridge along A (or N), with gable-end triangles in the wall colour."""
        if along_a:
            m = (n0 + n1) / 2
            self.quad((n0, a0, y0), (n0, a1, y0), (m, a1, y0 + rise), (m, a0, y0 + rise), col, (-1, 0, 1))
            self.quad((n1, a0, y0), (n1, a1, y0), (m, a1, y0 + rise), (m, a0, y0 + rise), col, (1, 0, 1))
            self.tri((n0, a0, y0), (n1, a0, y0), (m, a0, y0 + rise), wall, (0, -1, 0))
            self.tri((n0, a1, y0), (n1, a1, y0), (m, a1, y0 + rise), wall, (0, 1, 0))
        else:
            m = (a0 + a1) / 2
            self.quad((n0, a0, y0), (n1, a0, y0), (n1, m, y0 + rise), (n0, m, y0 + rise), col, (0, -1, 1))
            self.quad((n0, a1, y0), (n1, a1, y0), (n1, m, y0 + rise), (n0, m, y0 + rise), col, (0, 1, 1))
            self.tri((n0, a0, y0), (n0, a1, y0), (n0, m, y0 + rise), wall, (-1, 0, 0))
            self.tri((n1, a0, y0), (n1, a1, y0), (n1, m, y0 + rise), wall, (1, 0, 0))

    def hip(self, n0, n1, a0, a1, y0, rise, col):
        """Hipped roof (a pyramid when square)."""
        cn, w, d = (n0 + n1) / 2, n1 - n0, a1 - a0
        r = max(0.0, (d - w) / 2) if d > w else 0.0
        q = max(0.0, (w - d) / 2) if w > d else 0.0
        ca = (a0 + a1) / 2
        t0, t1 = (cn - q, ca - r, y0 + rise), (cn + q, ca + r, y0 + rise)
        c = [(n0, a0, y0), (n1, a0, y0), (n1, a1, y0), (n0, a1, y0)]
        self.quad(c[0], c[1], (t1[0], t0[1], t0[2]) if q else t0, t0, col, (0, -1, 1)) if q else self.tri(c[0], c[1], t0, col, (0, -1, 1))
        self.quad(c[2], c[3], (t0[0], t1[1], t1[2]) if q else t1, t1, col, (0, 1, 1)) if q else self.tri(c[2], c[3], t1, col, (0, 1, 1))
        self.quad(c[1], c[2], t1, (t1[0], t0[1], t0[2]) if q else t0, col, (1, 0, 1)) if not q else self.tri(c[1], c[2], t1, col, (1, 0, 1))
        self.quad(c[3], c[0], t0, (t0[0], t1[1], t1[2]) if q else t1, col, (-1, 0, 1)) if not q else self.tri(c[3], c[0], t0, col, (-1, 0, 1))

    def barrel(self, n0, n1, a0, a1, y0, col, wall, along_a=True, k=6, rim=None):
        """Half-cylinder vault over a frame rectangle (axis along A or N), with semicircular end walls (and a rim band
        standing 6 cm proud of each end, like St. Clement's white arch edges)."""
        if rim:
            r, c0 = ((n1 - n0) / 2, (n0 + n1) / 2) if along_a else ((a1 - a0) / 2, (a0 + a1) / 2)
            for e, sg in ((a0, -1), (a1, 1)) if along_a else ((n0, -1), (n1, 1)):
                e2 = e + sg * 0.06
                for i in range(k):
                    t0, t1 = math.pi * i / k, math.pi * (i + 1) / k
                    q = [(c0 - rr * math.cos(t), y0 + rr * math.sin(t)) for rr, t in ((r * 0.97, t0), (r * 0.97, t1), (r + 0.45, t1), (r + 0.45, t0))]
                    pts = [(e2, u, y) if not along_a else (u, e2, y) for u, y in q]
                    self.quad(*pts, rim, (sg, 0, 0) if not along_a else (0, sg, 0))
        if along_a:
            cn, r = (n0 + n1) / 2, (n1 - n0) / 2
            pts = [(cn - r * math.cos(math.pi * i / k), y0 + r * math.sin(math.pi * i / k)) for i in range(k + 1)]
            for i in range(k):
                (p0, y_0), (p1, y_1) = pts[i], pts[i + 1]
                mo = math.pi * (i + 0.5) / k
                self.quad((p0, a0, y_0), (p1, a0, y_1), (p1, a1, y_1), (p0, a1, y_0), col, (-math.cos(mo), 0, math.sin(mo)))
                self.tri((cn, a0, y0), (p0, a0, y_0), (p1, a0, y_1), wall, (0, -1, 0))
                self.tri((cn, a1, y0), (p0, a1, y_0), (p1, a1, y_1), wall, (0, 1, 0))
        else:
            ca, r = (a0 + a1) / 2, (a1 - a0) / 2
            pts = [(ca - r * math.cos(math.pi * i / k), y0 + r * math.sin(math.pi * i / k)) for i in range(k + 1)]
            for i in range(k):
                (p0, y_0), (p1, y_1) = pts[i], pts[i + 1]
                mo = math.pi * (i + 0.5) / k
                self.quad((n0, p0, y_0), (n0, p1, y_1), (n1, p1, y_1), (n1, p0, y_0), col, (0, -math.cos(mo), math.sin(mo)))
                self.tri((n0, ca, y0), (n0, p0, y_0), (n0, p1, y_1), wall, (-1, 0, 0))
                self.tri((n1, ca, y0), (n1, p0, y_0), (n1, p1, y_1), wall, (1, 0, 0))

    def cross(self, cn, ca, y0, s=1.0, col=(214, 186, 90)):
        self.rect(cn - 0.06 * s, cn + 0.06 * s, ca - 0.06 * s, ca + 0.06 * s, y0, y0 + 1.6 * s, col)
        self.rect(cn - 0.45 * s, cn + 0.45 * s, ca - 0.05 * s, ca + 0.05 * s, y0 + 0.95 * s, y0 + 1.1 * s, col)

    def drum_dome(self, cn, ca, y0, r, hd, col_w, col_d, k=8, cross=True, alem=False):
        """Octagonal drum (y0 .. y0 + hd) with its dome and a cross / crescent finial."""
        self.prism(self.ngon(cn, ca, r, k, math.pi / k), y0, y0 + hd, col_w, top=False)
        self.dome(cn, ca, y0 + hd, r * 1.06, r * 0.95, col_d, k=max(8, k), rings=4)
        top = y0 + hd + r * 0.95
        if cross:
            self.cross(cn, ca, top - 0.05, 0.6 + r * 0.12)
        if alem:
            self.rect(cn - 0.07, cn + 0.07, ca - 0.07, ca + 0.07, top - 0.05, top + 1.4, (200, 176, 90))


def _rand(ring):
    r = np.asarray(ring, float).mean(0)
    return (int(abs(r[0]) * 31.7) * 7919 ^ int(abs(r[1]) * 13.1)) & 0xFFFF


def build(spec, ring, t):
    """Fill the spec's numbers from the footprint and tags (runs in the main process) -> spec, or None when the footprint does
    not suit a model (sprawling / very thin / huge ones stay ordinary buildings)."""
    k = spec["k"]
    c, A, N, L, W, fill = frame(ring, QIBLA if k == "mosque" else EAST)
    if k == "mosque" and (fill < 0.55 or L * W > 4500) and L * W > 1500:   # a big or irregular site (Голема Турска Џамија): a square mosque on its middle
        r = np.asarray(ring, float)
        c = r.mean(0)
        L = W = math.sqrt(fill * L * W) * 0.8
        spec.setdefault("minarets", 2)
        spec.setdefault("minaret", 45.0)
        fill = 1.0
    if fill < 0.55 or L * W > 4500 or min(L, W) < 3.5:
        return None
    spec.update(c=c.tolist(), A=A.tolist(), L=L, W=W, th=tag_h(t), seed=_rand(ring))
    return spec


def height(spec):
    """Collision / occupancy height (the walls' eave) of a spec."""
    k, L, W, th = spec["k"], spec["L"], spec["W"], spec.get("th")
    if k == "mosque":
        return min(13.0, max(5.0, 0.55 * min(W, L)))
    if k == "turbe":
        return 4.0
    if k == "sunk":
        return 3.2
    if k == "rotunda":
        return 0.33 * min(L, W)
    if k == "belfry":
        return spec.get("h") or th or 16.0
    if k == "modcath":
        return 9.0
    return min(12.0, max(4.5, (th * 0.55) if th else 3.2 + 0.22 * W))


def minarets(spec):
    """[(n, a, base half-width, height)] of a mosque's minarets: by the front right corner of the hall (and the left one)."""
    L, W = spec["L"], spec["W"]
    E, S = height(spec), min(W, L)
    pd = min(L - S, 0.32 * S)
    a_h = -L / 2 + pd if pd > 2.5 else -L / 2
    hm = spec.get("minaret") or min(45.0, max(16.0, 2.8 * E))
    rm = min(1.8, max(1.0, 0.06 * S + 0.7))
    sides = (1, -1) if spec.get("minarets", 1) > 1 else (1,)
    return [(sg * (W / 2 + rm + 0.25), a_h + rm + 0.4, rm, hm) for sg in sides]


def solids(spec):
    """Extra collision footprints outside the building's own ring (the minarets' square bases) -> [(world ring, height)]."""
    if spec["k"] != "mosque":
        return []
    c, A = np.array(spec["c"]), np.array(spec["A"])
    N = np.array([-A[1], A[0]])
    out = []
    for mn, ma, rm, hm in minarets(spec):
        out.append(([tuple((c + N * (mn + dn) + A * (ma + da)).tolist()) for dn, da in ((-rm, -rm), (rm, -rm), (rm, rm), (-rm, rm))], hm))
    return out


def mesh(spec, shade):
    c, A = np.array(spec["c"]), np.array(spec["A"])
    N = np.array([-A[1], A[0]])
    m = Mesh(c, A, N, shade)
    k, L, W, th, sd = spec["k"], spec["L"], spec["W"], spec.get("th"), spec["seed"]
    E = height(spec)
    hw, hl = W / 2, L / 2
    pick = lambda xs, s=0: xs[(sd >> s) % len(xs)]          # noqa: E731
    if k in ("orthodox", "sunk"):
        wall = pick((OCHRE, CREAM, STONE, (210, 170, 140)))
        dome_c = pick((LEAD, COPPER, TILE, LEAD), 3)
        y0 = -1.4 if k == "sunk" else 0.0                   # Sv. Spas stands half below the street level
        ra = min(0.3 * W, 0.2 * L)
        m.rect(-hw, hw, -hl, hl - ra, y0 - 0.4, E, wall, top=False)
        m.prism(m.ngon(0, hl - ra, ra * 0.98, 6, -math.pi / 2, math.pi / 2), y0 - 0.4, E * 0.82, wall, top=False)   # east apse
        m.dome(0, hl - ra, E * 0.82, ra * 1.04, ra * 0.55, TILE, k=6, rings=2, a0=-math.pi / 2, a1=math.pi / 2)
        rise = (0.18 if k == "sunk" else 0.3) * W
        m.gable(-hw - 0.35, hw + 0.35, -hl - 0.35, hl - ra + 0.02, E, rise, TILE, wall)
        ac = -ra * 0.5
        if k == "orthodox" and L > 1.25 * W:                    # cross-in-square: the transept roof
            m.gable(-hw - 0.35, hw + 0.35, ac - 0.17 * L, ac + 0.17 * L, E, rise * 0.97, TILE, wall, along_a=False)
        if k == "orthodox":
            rd = min(5.0, max(1.4, 0.2 * W))
            m.drum_dome(0, ac, E + rise * 0.6, rd, rise * 0.4 + 1.3 * rd, wall, dome_c)
            if W >= 14:                                           # five domes: four small ones on the corners of the square
                for sn in (-1, 1):
                    for sa in (-1, 1):
                        m.drum_dome(sn * W * 0.27, ac + sa * W * 0.27, E + rise * 0.25, rd * 0.5, rise * 0.4 + rd * 0.6, wall, dome_c, cross=False)
            if spec.get("tower") or (L >= 1.5 * W and L >= 14):  # bell tower over the west narthex
                s = min(0.45 * W, 6.0)
                tt = E + rise + 1.8 * s
                m.rect(-s / 2, s / 2, -hl, -hl + s, 0.0, tt, wall, top=False)
                m.rect(-s / 2 - 0.2, s / 2 + 0.2, -hl - 0.2, -hl + s + 0.2, tt - 1.2, tt - 0.9, CREAM)         # cornice band
                m.hip(-s / 2 - 0.25, s / 2 + 0.25, -hl - 0.25, -hl + s + 0.25, tt, s * 0.7, dome_c)
                m.cross(0, -hl + s / 2, tt + s * 0.7 - 0.05, 0.9)
        else:
            m.cross(0, -hl - 0.1, E + rise - 0.1, 0.7)
    elif k == "rotunda":                                          # Sv. Kliment: central dome ringed by vaults and smaller domes
        S = min(L, W) / 2
        wall, dome_c = (196, 158, 118), (82, 122, 102)
        core = S * 0.5
        m.prism(m.ngon(0, 0, S * 0.98, 16, math.pi / 16), -0.4, E * 0.6, wall, top=True)
        for sn, sa in ((1, 0), (-1, 0), (0, 1), (0, -1)):        # the four arms: great copper vaults whose arched ends show white rims
            if sn:
                m.prism([(-S * 0.98 if sn < 0 else core * 0.6, -S * 0.4), (-core * 0.6 if sn < 0 else S * 0.98, -S * 0.4),
                         (-core * 0.6 if sn < 0 else S * 0.98, S * 0.4), (-S * 0.98 if sn < 0 else core * 0.6, S * 0.4)], E * 0.6 - 0.1, E * 0.6 + 0.3, wall, top=False)
                m.barrel(-S * 0.98 if sn < 0 else core * 0.6, -core * 0.6 if sn < 0 else S * 0.98, -S * 0.4, S * 0.4, E * 0.6 + 0.3, dome_c, wall, along_a=False, k=8, rim=WHITE)
            else:
                m.prism([(-S * 0.4, -S * 0.98 if sa < 0 else core * 0.6), (S * 0.4, -S * 0.98 if sa < 0 else core * 0.6),
                         (S * 0.4, -core * 0.6 if sa < 0 else S * 0.98), (-S * 0.4, -core * 0.6 if sa < 0 else S * 0.98)], E * 0.6 - 0.1, E * 0.6 + 0.3, wall, top=False)
                m.barrel(-S * 0.4, S * 0.4, -S * 0.98 if sa < 0 else core * 0.6, -core * 0.6 if sa < 0 else S * 0.98, E * 0.6 + 0.3, dome_c, wall, k=8, rim=WHITE)
        for i in range(4):                                         # four domes between the arms
            b = math.pi / 4 + i * math.pi / 2
            m.drum_dome(S * 0.66 * math.cos(b), S * 0.66 * math.sin(b), E * 0.6 - 0.2, S * 0.16, S * 0.3, wall, dome_c, k=12)
        yd = E * 0.6 + 0.4 * S                                     # the drum rises from the crowns of the vaults
        m.prism(m.ngon(0, 0, core, 16, math.pi / 16), E * 0.6, yd + S * 0.25, wall, top=False)   # the drum, then the big dome
        m.dome(0, 0, yd + S * 0.25, core * 1.04, core * 0.75, dome_c, k=16, rings=5)
        m.cross(0, 0, yd + S * 0.25 + core * 0.75 - 0.05, 1.6)
    elif k == "catholic":
        wall = pick((CREAM, WHITE, (222, 214, 200)))
        rise = 0.45 * W
        s = min(7.0, max(3.5, 0.3 * W))
        m.rect(-hw, hw, -hl + s * 0.0, hl, -0.4, E, wall, top=False)
        m.gable(-hw - 0.3, hw + 0.3, -hl + s + 0.02, hl + 0.3, E, rise, (150, 150, 152) if sd & 1 else TILE, wall)
        tt = spec.get("tower") or max(2.6 * E, E + rise + 8.0)
        m.rect(-s / 2, s / 2, -hl, -hl + s, -0.4, tt, wall, top=False)          # the campanile on the west front
        m.cone(0, -hl + s / 2, tt, s * 0.72, s * 1.6, (110, 114, 120), k=4)
        m.cross(0, -hl + s / 2, tt + s * 1.6 - 0.05, 1.0)
    elif k == "belfry":                                           # a free-standing bell tower: shaft, open bell stage, cap, cross
        wall = spec.get("wall") or pick((CREAM, STONE, OCHRE))
        cap = spec.get("cap") or pick((TILE, LEAD, COPPER), 2)
        s = min(L, W) * 0.98
        yb = E * 0.78
        m.rect(-s / 2, s / 2, -s / 2, s / 2, -0.4, yb, wall)
        p = max(0.5, s * 0.2)
        for sn in (-1, 1):                                        # four corner piers frame the arched openings
            for sa in (-1, 1):
                m.rect(sn * s / 2 - (p if sn > 0 else 0), sn * s / 2 + (p if sn < 0 else 0), sa * s / 2 - (p if sa > 0 else 0),
                       sa * s / 2 + (p if sa < 0 else 0), yb, E, wall, top=False)
        m.rect(-s / 2 - 0.15, s / 2 + 0.15, -s / 2 - 0.15, s / 2 + 0.15, E, E + 0.6, wall)
        if spec.get("cap"):
            m.prism(m.ngon(0, 0, s * 0.42, 8, math.pi / 8), E + 0.6, E + 0.6 + s * 0.25, wall, top=False)
            m.dome(0, 0, E + 0.6 + s * 0.25, s * 0.45, s * 0.42, cap, k=8, rings=3)
            m.cross(0, 0, E + 0.6 + s * 0.67 - 0.05, 1.0)
        else:
            m.hip(-s / 2 - 0.2, s / 2 + 0.2, -s / 2 - 0.2, s / 2 + 0.2, E + 0.6, s * 0.6, cap)
            m.cross(0, 0, E + 0.6 + s * 0.6 - 0.05, 0.8)
    elif k == "modcath":                                          # Sacred Heart: white modernist concrete with vertical fins
        wall, fin, trim = (236, 234, 228), (246, 245, 242), (150, 150, 148)
        m.rect(-hw, hw, -hl, hl, -0.4, E, wall)
        nf = max(2, int(L / 3.0))
        for sn in (-1, 1):                                        # tall fins along both long walls (they start inside the wall)
            for i in range(nf):
                a_ = -hl + 1.0 + (L - 2.0) * i / (nf - 1)
                m.rect(min(sn * (hw - 0.1), sn * (hw + 0.55)), max(sn * (hw - 0.1), sn * (hw + 0.55)), a_ - 0.2, a_ + 0.2, -0.4, E + 0.8, fin)
        m.rect(-hw * 0.55, hw * 0.55, -hl * 0.6, hl * 0.75, E, E + 4.5, wall)       # the raised middle volume over the nave
        m.rect(-hw * 0.55 - 0.3, hw * 0.55 + 0.3, -hl * 0.6 - 0.3, hl * 0.75 + 0.3, E + 4.5, E + 5.0, trim)
        tx, ta = hw - 1.6, -hl + 2.6                              # the slender concrete bell tower at the front corner: two blades
        for d in (-1, 1):
            m.rect(tx - 1.2, tx + 1.2, ta + d * 1.0 - 0.35, ta + d * 1.0 + 0.35, -0.4, 26.0, wall, top=True)
        m.rect(tx - 1.3, tx + 1.3, ta - 1.45, ta + 1.45, 20.5, 21.0, trim)
        m.rect(tx - 1.3, tx + 1.3, ta - 1.45, ta + 1.45, 26.0, 26.6, wall)
        m.cross(tx, ta, 26.55, 1.4)
    elif k == "hall":
        wall = pick((CREAM, WHITE, OCHRE))
        rise = 0.3 * W
        m.rect(-hw, hw, -hl, hl, -0.4, E, wall, top=False)
        m.gable(-hw - 0.3, hw + 0.3, -hl - 0.3, hl + 0.3, E, rise, TILE, wall)
        m.rect(-0.6, 0.6, -hl + 0.6, -hl + 1.8, E + rise * 0.5, E + rise + 1.6, wall, top=False)   # small bell turret
        m.hip(-0.75, 0.75, -hl + 0.45, -hl + 1.95, E + rise + 1.6, 1.0, LEAD)
        m.cross(0, -hl + 1.2, E + rise + 2.55, 0.5)
    elif k == "turbe":
        r = min(L, W) / 2 * 0.98
        m.prism(m.ngon(0, 0, r, 8, math.pi / 8), -0.4, E, pick((STONE, CREAM)), top=False)
        m.dome(0, 0, E, r * 1.02, r * 0.85, LEAD, k=8, rings=3)
    elif k == "mosque":
        wall = spec.get("wall") or pick((CREAM, (214, 192, 160), WHITE, (226, 214, 190)))
        S = min(W, L)                                             # the square prayer hall at the qibla end
        pd = min(L - S, 0.32 * S)                                 # portico depth (long footprints: a longer hall, not a deep porch)
        a_h = -hl + pd if pd > 2.5 else -hl                       # front wall of the hall
        ndome = spec.get("dome", 1 if S >= 6 else 0)
        m.rect(-hw, hw, a_h, hl, -0.4, E, wall, top=ndome != 0)      # flat roof under the drum(s)
        if ndome == 0:
            m.hip(-hw - 0.4, hw + 0.4, a_h - 0.4, hl + 0.4, E, 0.3 * S, TILE)
        elif ndome == 2:                                          # two domes in a row along the qibla axis
            d2 = (hl - a_h) / 2
            for j in (0, 1):
                ca = a_h + d2 * (j + 0.5)
                rr = min(d2, hw) * 0.88
                m.drum_dome(0, ca, E, rr, 0.9, wall, LEAD, cross=False, alem=True)
        else:
            rr = S * 0.46
            ca = (a_h + hl) / 2
            if spec.get("minarets", 1) > 1:                       # a big modern mosque: the main dome raised over four corner domes
                for sn in (-1, 1):
                    for sa in (-1, 1):
                        m.drum_dome(sn * hw * 0.62, ca + sa * (hl - a_h) * 0.31, E, S * 0.13, 0.6, wall, LEAD, cross=False, alem=True)
                rr = S * 0.3
            m.drum_dome(0, ca, E, rr, 0.8 + 0.06 * S, wall, LEAD, cross=False, alem=True)
        if a_h > -hl + 0.5:                                       # domed portico on columns in front of the hall
            d = a_h - (-hl) - 0.25
            ph = E * 0.62
            ncol = max(2, min(6, int(W / 3.2)))
            for i in range(ncol):
                n_ = -hw + 0.45 + (W - 0.9) * i / (ncol - 1)
                m.rect(n_ - 0.25, n_ + 0.25, -hl + 0.2, -hl + 0.7, -0.4, ph, (226, 222, 214), top=False)
            m.rect(-hw, hw, -hl, a_h - 0.25, ph, ph + 0.5, wall)
            nd = max(1, min(5, int(W / max(d, 2.5))))
            if ndome == 0:                                        # a tiled porch roof (Sultan Murat's wooden sundurma)
                m.hip(-hw - 0.3, hw + 0.3, -hl - 0.3, a_h - 0.25, ph + 0.5, 0.25 * d, TILE)
                nd = 0
            for i in range(nd):
                n_ = -hw + W * (i + 0.5) / nd
                m.dome(n_, -hl + d / 2, ph + 0.5, min(W / nd, d) * 0.42, min(W / nd, d) * 0.36, LEAD, k=8, rings=2)
        # the minaret: square base by the front right corner of the hall, octagonal shaft, balcony, pencil cap
        for mn, ma, rm, hm in minarets(spec):
            m.rect(mn - rm, mn + rm, ma - rm, ma + rm, -0.4, E * 0.7, wall)
            m.prism(m.ngon(mn, ma, rm * 0.9, 8, math.pi / 8), E * 0.7, hm * 0.8, wall, top=False)
            m.prism(m.ngon(mn, ma, rm * 1.45, 8, math.pi / 8), hm * 0.8, hm * 0.8 + 0.5, wall)
            m.prism(m.ngon(mn, ma, rm * 0.75, 8, math.pi / 8), hm * 0.8 + 0.5, hm * 0.9, wall, top=False)
            m.cone(mn, ma, hm * 0.9, rm * 0.95, hm * 0.1 + 2.5, LEAD)
            m.rect(mn - 0.06, mn + 0.06, ma - 0.06, ma + 0.06, hm + 2.4, hm + 3.6, (200, 176, 90))
    P = np.array(m.P, np.float32).reshape(-1, 3)
    return P, np.zeros((len(P), 2), np.float32), np.array(m.C, np.uint8).reshape(-1, 4)
