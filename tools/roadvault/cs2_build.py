"""Cities-Skylines-2-style road builder from the OSM graph (no satellite fitting).
Rules: lane count from the OSM tag (class default otherwise), fixed lane widths, kerbed sidewalks on every road (narrow on
service ways), junction mouths rounded by a local closing of the asphalt, medians / islands = the gaps between carriageways,
flat-capped dead ends (no turnaround bulbs), zebra crossings on junction arms, lane / edge / centre paint outside junctions,
bridges as ramped decks with parapets and piers.  Plan frame (east, north) in metres from the site centre."""
import math, os, sys
import numpy as np
from shapely.geometry import LineString, Point, Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely import affinity
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from mesh import Mesh, polys
import sat_overlay as S

DRIVE = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street",
         "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
PATHS = {"footway", "path", "cycleway", "pedestrian", "steps"}
GROUND, ASPH, SIDEW, GRASS, KERB = (122, 158, 96), (62, 64, 70), (196, 194, 186), (104, 148, 84), (170, 168, 160)
WHITE, YELLOW = (236, 236, 232), (232, 196, 60)
DEF_LANES = {"secondary": 4, "tertiary": 2, "residential": 2, "unclassified": 2, "living_street": 1, "service": 1}
LANE_W = {"service": 2.7, "living_street": 3.0, "residential": 3.0, "unclassified": 3.0}
SIDEWALK = {"service": 1.2, "living_street": 1.8, "residential": 1.8}


def spec(r):
    cls = r["cls"].replace("_link", "")
    ow = bool(r.get("ow")) or r["cls"].endswith("_link")
    n = int(r.get("lanes") or 0) or DEF_LANES.get(cls, 2)
    if ow:
        n = max(1, n)
    else:
        n = max(2, n + (n % 2))
    lw = LANE_W.get(cls, 3.25)
    return dict(n=n, ow=ow, lw=lw, w=n * lw, sw=SIDEWALK.get(cls, 2.2), cls=cls)


def site_roads(path):
    lat, lng, mpp = S.parse(os.path.basename(path))
    from PIL import Image
    import geo
    W = Image.open(path).size[0]
    s = mpp if mpp else 150.0 / W
    cx, cy = geo.project(lat, lng)
    half = W * s * 0.5 + 40
    sel = []
    for r in S.roads():
        xs = [p[0] for p in r["pts"]]
        ys = [p[1] for p in r["pts"]]
        if max(xs) < cx - half or min(xs) > cx + half or max(ys) < cy - half or min(ys) > cy + half:
            continue
        if r["cls"] in DRIVE or r["cls"] in PATHS or r["cls"] == "track":
            sel.append(r)
    return sel, cx, cy, half, W * s, (lat, lng)


def pts_of(r, cx, cy):
    return np.array([(x - cx, -(y - cy)) for x, y in r["pts"]], float)


def dashes(ls, dash, gap, off0=0.0):
    out, s = [], off0
    L = ls.length
    while s < L:
        e = min(s + dash, L)
        if e - s > 0.3:
            seg = [ls.interpolate(t) for t in np.linspace(s, e, max(2, int((e - s) / 2) + 2))]
            out.append(LineString([(p.x, p.y) for p in seg]))
        s += dash + gap
    return out


def offs(ls, d):
    try:
        o = ls.offset_curve(d)
    except Exception:
        return None
    if o.is_empty:
        return None
    if o.geom_type == "MultiLineString":
        o = max(o.geoms, key=lambda g: g.length)
    return o if o.geom_type == "LineString" else None


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * t * (t * (6 * t - 15) + 10)


def deck(m, pts, sp, layer, rnd_seed=0):
    ls = LineString(pts)
    L = ls.length
    if L < 8:
        return
    h = 6.2 * max(1, layer)
    rl = min(85.0, 0.46 * L)
    ss = np.linspace(0, L, max(3, int(L / 2.5)))
    P = np.array([ls.interpolate(s).coords[0] for s in ss])
    T = np.gradient(P, axis=0)
    T /= np.hypot(T[:, 0], T[:, 1])[:, None] + 1e-9
    N = np.c_[-T[:, 1], T[:, 0]]
    Z = np.array([h * smooth(s / rl) * smooth((L - s) / rl) for s in ss])
    hw, sw = sp["w"] / 2, 1.6

    def pt(i, d, dz=0.0):
        return (P[i, 0] + N[i, 0] * d, Z[i] + dz, P[i, 1] + N[i, 1] * d)
    for i in range(len(ss) - 1):
        j = i + 1
        m.quad(pt(i, -hw, 0.02), pt(i, hw, 0.02), pt(j, hw, 0.02), pt(j, -hw, 0.02), ASPH)
        for sg in (-1, 1):
            a, b = sg * hw, sg * (hw + sw)
            m.quad(pt(i, a, 0.18), pt(i, b, 0.18), pt(j, b, 0.18), pt(j, a, 0.18), SIDEW)
            m.quad(pt(i, a, 0.0), pt(i, a, 0.18), pt(j, a, 0.18), pt(j, a, 0.0), KERB)
            m.quad(pt(i, b, 0.18), pt(i, b, 1.1), pt(j, b, 1.1), pt(j, b, 0.18), (176, 174, 168))        # parapet
            m.quad(pt(i, b, -0.9), pt(i, b, 1.1), pt(j, b, 1.1), pt(j, b, -0.9), (158, 156, 150))        # fascia
        if (i // 2) % 2 == 0 and not sp["ow"]:
            m.quad(pt(i, -0.08, 0.04), pt(i, 0.08, 0.04), pt(j, 0.08, 0.04), pt(j, -0.08, 0.04), WHITE)
        for k in range(1, sp["n"]):
            if sp["ow"] and (i // 2) % 2 == 0:
                d = -hw + k * sp["lw"]
                m.quad(pt(i, d - 0.07, 0.04), pt(i, d + 0.07, 0.04), pt(j, d + 0.07, 0.04), pt(j, d - 0.07, 0.04), WHITE)
        if i % 10 == 5 and Z[i] > 2.0:
            m.cyl(P[i, 0], 0.0, Z[i] - 0.9, P[i, 1], 0.7, (150, 148, 142), 10)


BIG = {"motorway", "trunk", "primary", "secondary", "tertiary"}


def rot(poly, ang, c):
    return affinity.translate(affinity.rotate(poly, ang, origin=(0, 0), use_radians=True), c[0], c[1])


def arrow_poly(c, t, right, path, w=0.26):
    """Lane arrow: local path (x to the right, y forward) -> polygon (stem + triangular head)."""
    def w2(p):
        return (c[0] + p[0] * right[0] + p[1] * t[0], c[1] + p[0] * right[1] + p[1] * t[1])
    pts = [w2(p) for p in path]
    stem = LineString(pts).buffer(w / 2, cap_style=2, join_style=2)
    a, b = np.array(pts[-2]), np.array(pts[-1])
    d = (b - a) / (np.hypot(*(b - a)) + 1e-9)
    n = np.array([-d[1], d[0]])
    head = Polygon([tuple(b + n * 0.45), tuple(b + d * 0.8), tuple(b - n * 0.45)])
    return unary_union([stem, head])


def head(m, x, y0, z, ang, lit):
    """Signal head facing direction ang (plan frame): housing + three lamps, lit = 0 red, 1 amber, 2 green."""
    c, s = math.cos(ang), math.sin(ang)
    m.box(x, y0, z, 0.3, 1.0, 0.35, (34, 34, 38), yaw=ang)
    for k, col in enumerate([(235, 50, 40), (240, 190, 40), (60, 215, 90)]):
        on = (k == lit)
        cc = col if on else tuple(int(v * 0.25) for v in col)
        m.box(x + c * 0.17, y0 + 0.72 - 0.3 * k, z + s * 0.17, 0.04, 0.2, 0.2, cc, yaw=ang)


def plate(m, x, y0, z, ang, w, h, col):
    m.box(x, y0, z, 0.05, h, w, col, yaw=ang)


def giveway(m, x, z, ang):
    c, s = math.cos(ang), math.sin(ang)
    wx, wz = -s, c
    top = 2.5

    def v(dw, y):
        return (x + wx * dw + c * 0.05, y, z + wz * dw + s * 0.05)
    m.cyl(x, 0.0, 2.1, z, 0.04, (90, 92, 96), 6)
    m.tri(v(-0.62, 2.9), v(0.62, 2.9), v(0, 1.8), (215, 40, 40), lit=False)
    m.tri(v(-0.40, 2.8), v(0.40, 2.8), v(0, 2.1), (245, 245, 245), lit=False)


def bus_stop(m, x, z, ang, out):
    """ang = direction of travel (plan), out = unit vector from the road towards the pavement."""
    c, s = math.cos(ang), math.sin(ang)
    bx, bz = x + out[0] * 0.6, z + out[1] * 0.6
    m.box(bx, 2.35, bz, 1.5, 0.12, 3.2, (60, 70, 80), yaw=ang)                                    # roof
    for sg in (-1, 1):
        m.cyl(bx - s * sg * 1.5 - c * 0.6 * 0, 0.0, 2.35, bz + c * sg * 1.5, 0.05, (90, 92, 96), 6)
    m.box(bx + out[0] * 0.55, 0.3, bz + out[1] * 0.55, 0.05, 2.0, 3.0, (150, 195, 210), yaw=ang)     # glass back
    px, pz = x - out[0] * -0.2 + c * 2.6, z + s * 2.6
    m.cyl(px, 0.0, 2.6, pz, 0.04, (90, 92, 96), 6)
    plate(m, px, 2.0, pz, ang + math.pi / 2, 0.55, 0.55, (40, 100, 190))
    plate(m, px, 2.12, pz, ang + math.pi / 2, 0.3, 0.12, (245, 245, 245))


def build(sel, cx, cy, half):
    """Return (mesh, info).  sel: raw OSM road dicts."""
    m = Mesh()
    big = half * 3
    m.poly(box(-big, -big, big, big), -0.05, GROUND)
    drive, bridges, paths, tracks = [], [], [], []
    for r in sel:
        p = pts_of(r, cx, cy)
        if len(p) < 2:
            continue
        if r["cls"] in DRIVE:
            sp = spec(r)
            ent = dict(r=r, pts=p, sp=sp, ls=LineString(p))
            if r.get("tunnel"):
                continue
            if r.get("bridge") or (r.get("layer") or 0) > 0:
                bridges.append(ent)
            else:
                drive.append(ent)
        elif r["cls"] == "track":
            tracks.append(LineString(p))
        else:
            paths.append((LineString(p), 4.0 if r["cls"] == "pedestrian" else 1.6))
    # ---- junction nodes (graph degree >= 3 on at-grade drive roads)
    inc = {}
    for e in drive:
        nodes = e["r"]["nodes"]
        for k, nid in enumerate(nodes):
            inc.setdefault(nid, []).append((e, k))
    junc = []
    for nid, lst in inc.items():
        deg = sum(1 if k in (0, len(e["pts"]) - 1) else 2 for e, k in lst)
        if deg >= 3:
            p = lst[0][0]["pts"][lst[0][1]]
            rj = max(e["sp"]["w"] for e, _ in lst) / 2 + 7.0
            junc.append((nid, p, rj, lst))
    # ---- asphalt
    asph = unary_union([e["ls"].buffer(e["sp"]["w"] / 2, cap_style=2, join_style=1) for e in drive]) if drive else Polygon()
    discs = []
    for nid, p, rj, lst in junc:
        D = Point(p).buffer(rj)
        discs.append(D)
        part = asph.intersection(D)
        if not part.is_empty:
            asph = asph.union(part.buffer(5.0).buffer(-5.0))
    discs_u = unary_union(discs) if discs else Polygon()
    # verges: medians and islands = gaps between carriageways
    closed = asph.buffer(7.0).buffer(-7.0)
    verge = closed.difference(asph).buffer(-0.3).buffer(0.3)
    verge = unary_union([g for g in polys(verge) if g.area > 5.0]) if not verge.is_empty else Polygon()
    # sidewalks
    sws = [e["ls"].buffer(e["sp"]["w"] / 2 + e["sp"]["sw"], cap_style=2, join_style=1) for e in drive]
    asph, verge = asph.buffer(0), verge.buffer(0)
    sw = unary_union(sws).buffer(0).difference(asph).difference(verge).buffer(0) if sws else Polygon()
    for t in tracks:
        g = t.buffer(1.5, cap_style=2)
        m.poly(g.difference(asph), 0.01, (168, 150, 112))
    for ls, w in paths:
        g = ls.buffer(w / 2, cap_style=2).difference(asph).difference(sw)
        m.poly(g, 0.05, (206, 202, 192))
    m.poly(asph, 0.02, ASPH)
    if not verge.is_empty:
        m.prism(verge, 0.0, 0.16, GRASS, KERB)
    if not sw.is_empty:
        m.prism(sw, 0.0, 0.16, SIDEW, KERB)
    # ---- paint
    white, yellow = [], []
    for e in drive:
        sp, ls = e["sp"], e["ls"]
        hw = sp["w"] / 2
        big_road = sp["cls"] in ("secondary", "tertiary", "primary", "trunk", "motorway")
        if big_road or sp["n"] >= 3:
            for sg in (-1, 1):
                o = offs(ls, sg * (hw - 0.25))
                if o is not None:
                    white.append(o.buffer(0.075, cap_style=2))
        if not sp["ow"]:
            if sp["n"] >= 4 or big_road:
                for sg in (-1, 1):
                    o = offs(ls, sg * 0.12)
                    if o is not None:
                        yellow.append(o.buffer(0.06, cap_style=2))
            else:
                white += [d.buffer(0.07, cap_style=2) for d in dashes(ls, 3.0, 5.0)]
            per = sp["n"] // 2
            for k in range(1, per):
                for sg in (-1, 1):
                    o = offs(ls, sg * k * sp["lw"])
                    if o is not None:
                        white += [d.buffer(0.07, cap_style=2) for d in dashes(o, 3.0, 5.0)]
        else:
            for k in range(1, sp["n"]):
                o = offs(ls, -hw + k * sp["lw"])
                if o is not None:
                    white += [d.buffer(0.07, cap_style=2) for d in dashes(o, 3.0, 5.0)]
    clip = asph.buffer(-0.15).difference(discs_u.buffer(-1.5)) if not discs_u.is_empty else asph.buffer(-0.15)
    if white:
        m.poly(unary_union(white).intersection(clip), 0.04, WHITE, lit=False)
    if yellow:
        m.poly(unary_union(yellow).intersection(clip), 0.045, YELLOW, lit=False)
    # ---- junction arms: zebras, stop / give-way lines, lane arrows, signals, signs, splitter islands
    zeb, wl, islands, furn, bays = [], [], [], [], []
    cnt = dict(signal=0, giveway=0, arrows=0, busstops=0, islands=0)
    for nid, p, rj, lst in junc:
        arms = []
        for e, k in lst:
            ls = e["ls"]
            s0 = ls.project(Point(p))
            for sgn in (-1, 1):
                if (sgn < 0 and s0 < rj + 3) or (sgn > 0 and s0 > ls.length - rj - 3):
                    continue
                a, b = ls.interpolate(s0 + sgn * 6.0), ls.interpolate(s0 + sgn * 12.0)
                u = np.array([b.x - a.x, b.y - a.y])
                u /= np.hypot(*u) + 1e-9
                inbound = (not e["sp"]["ow"]) or (bool(e["r"].get("ow")) and sgn < 0)    # traffic heads towards the node on this arm
                arms.append(dict(e=e, sgn=sgn, s0=s0, u=u, inb=inbound))
        if len(arms) < 3:
            continue
        ring = any((x["e"]["r"].get("junction") or "") in ("roundabout", "circular") for x in arms)
        major = [x for x in arms if x["e"]["sp"]["cls"] in BIG and not x["e"]["r"]["cls"].endswith("_link")]
        signal = (not ring) and ((len(arms) >= 3 and len(major) >= 3) or (len(arms) >= 4 and len(major) >= 2))
        # priority axis for unsignalised junctions: the two most collinear arms of the highest class
        prio = set()
        if not signal and not ring:
            best, bs = None, -9
            for x in range(len(arms)):
                for y in range(x + 1, len(arms)):
                    col = -float(arms[x]["u"] @ arms[y]["u"])
                    sc = col + 0.5 * (arms[x]["e"]["sp"]["n"] + arms[y]["e"]["sp"]["n"]) + (2 if arms[x]["e"]["sp"]["cls"] in BIG else 0)
                    if sc > bs:
                        bs, best = sc, (x, y)
            prio = set(best) if best else set()
        a0 = math.atan2(arms[0]["u"][1], arms[0]["u"][0])
        for ai, A in enumerate(arms):
            e, sp, u = A["e"], A["e"]["sp"], A["u"]
            ls = e["ls"]
            t = -u                                                        # approaching traffic heads along t
            right = np.array([t[1], -t[0]])                               # right of travel (north-up plan)
            ang_u = math.atan2(u[1], u[0])

            def at(d, lat=0.0):
                c = ls.interpolate(A["s0"] + A["sgn"] * d)
                return np.array([c.x, c.y]) + right * lat
            if sp["w"] >= 4.5 and sp["sw"] >= 1.8:
                c = at(rj - 1.0)
                n = int(sp["w"] / 1.0) - 1
                for q in range(n):
                    d = -sp["w"] / 2 + 0.7 + q * 1.0
                    zeb.append(rot(box(-1.6, d - 0.25, 1.6, d + 0.25), ang_u + math.pi / 2, c))
            nin = sp["n"] if sp["ow"] else sp["n"] // 2
            if A["inb"] and sp["w"] >= 4.5:
                # stop line (signals / stop) or dashed give-way line, across the approach lanes
                c = at(rj + 1.8, 0.0)
                if sp["ow"]:
                    lo_, hi_ = -sp["w"] / 2, sp["w"] / 2
                else:
                    lo_, hi_ = 0.0, sp["w"] / 2
                lat0, lat1 = lo_, hi_
                p0, p1 = at(rj + 1.8, lat0), at(rj + 1.8, lat1)
                ln = LineString([tuple(p0), tuple(p1)])
                if signal or (ai not in prio and not ring):
                    if signal:
                        wl.append(ln.buffer(0.25, cap_style=2))
                    else:
                        wl += [d.buffer(0.18, cap_style=2) for d in dashes(ln, 0.6, 0.5)]
                if ring:
                    wl += [d.buffer(0.18, cap_style=2) for d in dashes(ln, 0.6, 0.5)]
                # lane arrows
                if nin >= 2 and sp["w"] >= 6.0:
                    lanes = [(i + 0.5) * sp["lw"] + (lo_ if sp["ow"] else 0.0) for i in range(nin)]
                    turns = {"L": False, "R": False}
                    for B in arms:
                        if B is A:
                            continue
                        v = B["u"]
                        ang = math.atan2(t[0] * v[1] - t[1] * v[0], float(t @ v))
                        if 0.5 < ang < 2.6:
                            turns["L"] = True
                        elif -2.6 < ang < -0.5:
                            turns["R"] = True
                    for i, lat in enumerate(lanes):
                        cc = at(rj + 10.0, lat)
                        if i == 0 and turns["L"]:
                            path = [(0, -1.4), (0, 0.0), (-0.9, 0.9)]
                        elif i == nin - 1 and turns["R"]:
                            path = [(0, -1.4), (0, 0.0), (0.9, 0.9)]
                        else:
                            path = [(0, -1.4), (0, 0.9)]
                        cnt["arrows"] += 1
                        wl.append(arrow_poly(cc, t, right, path))
                # signs / signals
                if signal:
                    wr = sp["w"] if sp["ow"] else sp["w"] / 2
                    cnt["signal"] += 1
                    base = at(rj + 3.5, hi_ + sp["sw"] * 0.5)
                    m.cyl(base[0], 0.0, 5.2 if sp["w"] >= 6 else 3.6, base[1], 0.09, (90, 92, 96), 8)
                    face = math.atan2(u[1], u[0])
                    state = 2 if abs(math.sin(ang_u - a0)) < 0.5 else 0
                    if sp["w"] >= 6:
                        tip = at(rj + 3.5, lo_ + 1.0)
                        arm_len = math.hypot(*(tip - base))
                        mid = (tip + base) / 2
                        m.box(mid[0], 5.1, mid[1], arm_len, 0.12, 0.12, (90, 92, 96), yaw=math.atan2(tip[1] - base[1], tip[0] - base[0]))
                        for i in range(min(nin, 3)):
                            hx = at(rj + 3.5, lo_ + (i + 0.5) * sp["lw"] * (nin / min(nin, 3)) if sp["ow"] else (i + 0.5) * sp["lw"])
                            head(m, hx[0], 4.1, hx[1], face, state)
                    head(m, base[0], 2.6, base[1], face, state)
                elif ai not in prio:
                    base = at(rj + 3.0, hi_ + sp["sw"] * 0.5)
                    cnt["giveway"] += 1
                    giveway(m, base[0], base[1], math.atan2(u[1], u[0]))
            # splitter island on wide two-way arms
            if (not sp["ow"]) and sp["w"] >= 9.0 and not ring:
                d1, d2 = rj + 3.0, rj + 17.0
                pa, pb = at(d1), at(d2)
                nrm = np.array([-u[1], u[0]])
                cnt["islands"] += 1
                islands.append(Polygon([tuple(pa + nrm * 1.3), tuple(pb + nrm * 0.2), tuple(pb - nrm * 0.2), tuple(pa - nrm * 1.3)]))
        if signal:
            furn.append(p)
    # mid-block bus stops and zebra on secondary / tertiary blocks
    for e in drive:
        sp, ls = e["sp"], e["ls"]
        if sp["cls"] not in ("secondary", "tertiary") or sp["w"] < 6.0:
            continue
        cuts = sorted([(ls.project(Point(p)), rj) for _n, p, rj, lst in junc for ee, _k in lst if ee is e])
        bounds = [(0.0, 0.0)] + cuts + [(ls.length, 0.0)]
        for (sa, ra), (sb, rb) in zip(bounds[:-1], bounds[1:]):
            lo_s, hi_s = sa + ra + 4.0, sb - rb - 4.0
            if hi_s - lo_s < 130.0:
                continue
            for s_, sgn_ in ((lo_s + 22.0, 1), (hi_s - 22.0, -1)):
                if sgn_ < 0 and sp["ow"]:
                    continue
                a, b = ls.interpolate(max(0, s_ - 1.0)), ls.interpolate(min(ls.length, s_ + 1.0))
                tv = np.array([b.x - a.x, b.y - a.y])
                tv = tv / (np.hypot(*tv) + 1e-9) * sgn_
                rt = np.array([tv[1], -tv[0]])
                c = ls.interpolate(s_)
                off = sp["w"] / 2 + sp["sw"] * 0.5
                pos = np.array([c.x, c.y]) + rt * off
                cnt["busstops"] += 1
                bus_stop(m, pos[0], pos[1], math.atan2(tv[1], tv[0]), rt)
                bay = LineString([tuple(np.array([c.x, c.y]) + rt * (sp["w"] / 2 - 0.4) - tv * 7), tuple(np.array([c.x, c.y]) + rt * (sp["w"] / 2 - 0.4) + tv * 7)]).buffer(0.1, cap_style=2)
                bays.append(bay)
            mid = (lo_s + hi_s) / 2
            a, b = ls.interpolate(mid - 1.0), ls.interpolate(mid + 1.0)
            tv = np.array([b.x - a.x, b.y - a.y])
            tv /= np.hypot(*tv) + 1e-9
            c = ls.interpolate(mid)
            an = math.atan2(tv[1], tv[0])
            for q in range(int(sp["w"] / 1.0) - 1):
                d = -sp["w"] / 2 + 0.7 + q * 1.0
                zeb.append(rot(box(-1.6, d - 0.25, 1.6, d + 0.25), an + math.pi / 2, (c.x, c.y)))
            for sg in (-1, 1):
                pp = np.array([c.x, c.y]) + np.array([-tv[1], tv[0]]) * sg * (sp["w"] / 2 + sp["sw"] * 0.5) - tv * 3.0 * sg
                m.cyl(pp[0], 0.0, 2.4, pp[1], 0.04, (90, 92, 96), 6)
                plate(m, pp[0], 1.8, pp[1], an + (0 if sg > 0 else math.pi), 0.6, 0.6, (40, 100, 190))
    if zeb:
        m.poly(unary_union(zeb).intersection(asph), 0.05, WHITE, lit=False)
    if wl:
        m.poly(unary_union(wl).intersection(asph), 0.05, WHITE, lit=False)
    if bays:
        m.poly(unary_union(bays).intersection(asph), 0.046, YELLOW, lit=False)
    if islands:
        isl = unary_union(islands).intersection(asph)
        m.prism(isl, 0.0, 0.16, GRASS, KERB)
    for e in bridges:
        deck(m, e["pts"], e["sp"], max(1, int(e["r"].get("layer") or 1)))
    info = dict(cnt, n_drive=len(drive), n_bridge=len(bridges), n_junc=len(junc), n_verge=len(polys(verge)) if not verge.is_empty else 0)
    return m, info, drive


def render_views(path, r, zoom=None):
    """(top PIL, oblique PIL, info) for the CS2-style build of the OSM around the screenshot."""
    import pyray as rl
    from PIL import Image
    sel, cx, cy, half, wm, site = site_roads(path)
    m, info, drive = build(sel, cx, cy, half)
    P = np.array(m.P, np.float32)
    P[:, 2] *= -1.0
    m.P = [p for p in P]
    best, bl = None, 0
    for e in drive:
        d = float(np.hypot(*(e["pts"]).T).min())
        if d < 35 and e["ls"].length * (1 + e["sp"]["n"]) > bl:
            best, bl = e, e["ls"].length * (1 + e["sp"]["n"])
    ang = 0.0
    if best is not None:
        i = int(np.argmin(np.hypot(*best["pts"].T)))
        v = best["pts"][min(i + 1, len(best["pts"]) - 1)] - best["pts"][max(i - 1, 0)]
        ang = math.atan2(v[1], v[0])
    import road_shot as rs
    fov = 35.0
    zoom = zoom or float(os.environ.get('CS2_ZOOM', '1'))
    wm = wm / zoom
    out = []
    for kind in ("top", "obl"):
        if kind == "top":
            eye, up = (0.0, (wm / 2) / math.tan(math.radians(fov / 2)), 0.0), (0.0, 0.0, -1.0)
            tgt = (0.0, 0.0, 0.0)
        else:
            nx, ny = -math.sin(ang), math.cos(ang)
            dist = wm * 1.0
            el = math.radians(32)
            eye = (nx * dist * math.cos(el), dist * math.sin(el), -ny * dist * math.cos(el))
            tgt, up = (0.0, 2.0, 0.0), (0.0, 1.0, 0.0)
        models = rs.model(np.array(m.P, np.float32), np.array(m.C, np.uint8))
        cam = rl.Camera3D(eye, tgt, up, fov if kind == "top" else 40.0, rl.CAMERA_PERSPECTIVE)
        rl.rl_set_clip_planes(1.0, 3000.0)
        rl.begin_texture_mode(r.rt)
        rl.clear_background((190, 212, 236, 255))
        rl.begin_mode_3d(cam)
        rl.rl_disable_backface_culling()
        for mo in models:
            rl.draw_model(mo, (0, 0, 0), 1.0, rl.WHITE)
        rl.end_mode_3d()
        rl.end_texture_mode()
        img = rl.load_image_from_texture(r.rt.texture)
        rl.image_flip_vertical(img)
        tmp = f"/tmp/_cs2_{os.getpid()}.png"
        rl.export_image(img, tmp)
        rl.unload_image(img)
        for mo in models:
            rl.unload_model(mo)
        out.append(Image.open(tmp).convert("RGB"))
    return out[0], out[1], dict(info, site=site, width_m=wm)
