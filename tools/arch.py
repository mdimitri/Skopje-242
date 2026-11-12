"""Porta Macedonia (OSM way 239422349, wikidata Q3078453): a triumphal arch with an open passage, instead of a solid block.

arch_axes(ring, passages) -> frame; arch_piers(frame) -> the two collision footprints; arch_mesh(frame, box) -> [(material, pos, uv, col)]
(frame coordinates: n across the arch face, a along the passage; heights above the building's base).  ~1.1k vertices."""
import math

import numpy as np

WIKIDATA = "Q3078453"
H = 21.0                 # total height (real arch ~21 m)
PW = 5.4                 # passage width
SPRING, RISE = 6.8, 4.2  # springing height of the vault, rise of its (elliptical) crown
ORDER = 15.0             # top of the main order (cornice)
STONE = (232, 228, 216)
RELIEF = (206, 199, 184)
DARK = (150, 144, 132)


def is_arch(tags):
    return tags.get("wikidata") == WIKIDATA


def arch_frame(ring, passages):
    """ring: [(x,y)] outer ring (game metres); passages: point lists of building_passage ways.
    The frame is aligned with the footprint edge closest to the passage direction (a footprint edge when none crosses it)."""
    r = np.asarray(ring, float)
    c = r.mean(0)
    ang = None
    for pts in passages:
        p = np.asarray(pts, float)
        if len(p) > 1 and np.hypot(*(p.mean(0) - c)) < 20:
            d = p[-1] - p[0]
            ang = math.atan2(d[1], d[0])
            break
    segs = [(math.hypot(*(r[(i + 1) % len(r)] - r[i])), math.atan2(*(r[(i + 1) % len(r)] - r[i])[::-1])) for i in range(len(r) - 1)]
    a = max(segs)[1] if ang is None else max(segs, key=lambda q: abs(math.cos(q[1] - ang)) + 0.01 * q[0])[1]
    A = np.array([math.cos(a), math.sin(a)])
    N = np.array([-A[1], A[0]])
    u, v = (r - c) @ N, (r - c) @ A
    cn, ca = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
    return {"c": c + N * cn + A * ca, "A": A, "N": N, "W": float(u.max() - u.min()), "D": float(v.max() - v.min()), "yaw": float(math.atan2(N[1], N[0]))}


def _pt(f, n, a):
    return f["c"] + f["N"] * n + f["A"] * a


def arch_piers(f):
    """The two solid piers as footprint rings (the opening between them stays free for the occupancy / collision data)."""
    W, D = f["W"], f["D"]
    out = []
    for s in (-1, 1):
        n0, n1 = sorted((s * PW / 2, s * W / 2))
        out.append([tuple(_pt(f, n, a)) for n, a in ((n0, -D / 2), (n1, -D / 2), (n1, D / 2), (n0, D / 2))])
    return out


def arch_mesh(f, box, shade):
    W, D = f["W"], f["D"]
    P, U, C = [], [], []

    def quad(p, col):                                    # p: 4 (n, a, y) corners, emitted double sided
        w = [(*_pt(f, n, a), y) for n, a, y in p]
        w = [(q[0], q[2], q[1]) for q in w]                  # -> (x, y, z)
        v1, v2 = np.subtract(w[1], w[0]), np.subtract(w[3], w[0])
        nn = np.cross(v1, v2)
        nn = nn / (np.linalg.norm(nn) or 1)
        sh = shade(nn)
        for tri in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
            for i in tri:
                P.append(w[i])
                U.append((0.0, 0.0))
                C.append((*[min(255, c * sh) for c in col], 255))

    def bx(n0, n1, a0, a1, y0, y1, col):
        cn, ca = (n0 + n1) / 2, (a0 + a1) / 2
        c = _pt(f, cn, ca)
        p, u, c_ = box(c[0], c[1], n1 - n0, a1 - a0, y1 - y0, y0, col, f["yaw"])
        P.extend(p.tolist())
        U.extend(u.tolist())
        C.extend(c_.tolist())

    hw = PW / 2
    for s in (-1, 1):                                         # the piers
        n0, n1 = sorted((s * hw, s * W / 2))
        bx(n0, n1, -D / 2, D / 2, -0.4, ORDER, STONE)
        # engaged plinth + relief panels on both faces (a = +-D/2) and on the outer end
        pn = (n0 + n1) / 2
        pwid = (n1 - n0) - 1.6
        for sa in (-1, 1):
            a_out = sa * (D / 2 + 0.12)
            bx(pn - pwid / 2, pn + pwid / 2, min(a_out, sa * D / 2), max(a_out, sa * D / 2), 2.2, 11.8, RELIEF)
            bx(pn - pwid / 2 + 0.5, pn + pwid / 2 - 0.5, min(a_out + sa * 0.06, sa * D / 2), max(a_out + sa * 0.06, sa * D / 2), 5.4, 10.0, DARK)
        sn = s * (W / 2 + 0.12)
        bx(min(sn, s * W / 2), max(sn, s * W / 2), -D / 2 + 1.6, D / 2 - 1.6, 2.2, 11.8, RELIEF)
        bx(min(sn + s * 0.06, s * W / 2), max(sn + s * 0.06, s * W / 2), -D / 2 + 2.4, D / 2 - 2.4, 5.4, 10.0, DARK)
        bx(n0 - (0.15 if s < 0 else 0), n1 + (0.15 if s > 0 else 0), -D / 2 - 0.15, D / 2 + 0.15, -0.4, 0.7, STONE)   # plinth
    # the vault over the passage: elliptical intrados, spandrels above it up to the main order
    k = 12
    pts = [(hw * math.cos(math.pi * (1 - i / k)), SPRING + RISE * math.sin(math.pi * (1 - i / k))) for i in range(k + 1)]
    for i in range(k):
        (n0, y0), (n1, y1) = pts[i], pts[i + 1]
        quad([(n0, -D / 2, y0), (n1, -D / 2, y1), (n1, D / 2, y1), (n0, D / 2, y0)], (214, 208, 194))   # intrados
        for sa in (-1, 1):
            quad([(n0, sa * D / 2, y0), (n1, sa * D / 2, y1), (n1, sa * D / 2, ORDER), (n0, sa * D / 2, ORDER)], STONE)   # spandrel
    bx(-hw, hw, -D / 2, D / 2, SPRING + RISE, ORDER, STONE)       # keystone mass above the crown
    # cornice, attic with its frieze panels, roof terrace with a parapet
    bx(-W / 2 - 0.5, W / 2 + 0.5, -D / 2 - 0.5, D / 2 + 0.5, ORDER, ORDER + 0.8, STONE)
    bx(-W / 2 + 0.2, W / 2 - 0.2, -D / 2 + 0.2, D / 2 - 0.2, ORDER + 0.8, H - 1.1, STONE)
    for sa in (-1, 1):
        a_out = sa * (D / 2 - 0.2 + 0.1)
        bx(-W / 2 + 1.4, W / 2 - 1.4, min(a_out, sa * (D / 2 - 0.2)), max(a_out, sa * (D / 2 - 0.2)), ORDER + 1.6, H - 1.9, RELIEF)
        for j in (-1, 0, 1):                                  # three reliefs in the frieze
            bx(j * (W - 3.4) / 3 - 1.0, j * (W - 3.4) / 3 + 1.0, min(a_out, a_out + sa * 0.06), max(a_out, a_out + sa * 0.06), ORDER + 2.0, H - 2.3, DARK)
    bx(-W / 2 - 0.2, W / 2 + 0.2, -D / 2 - 0.2, D / 2 + 0.2, H - 1.1, H - 0.9, STONE)            # terrace slab edge
    t = 0.35
    bx(-W / 2 - 0.2, W / 2 + 0.2, -D / 2 - 0.2, -D / 2 - 0.2 + t, H - 0.9, H, STONE)
    bx(-W / 2 - 0.2, W / 2 + 0.2, D / 2 + 0.2 - t, D / 2 + 0.2, H - 0.9, H, STONE)
    bx(-W / 2 - 0.2, -W / 2 - 0.2 + t, -D / 2 - 0.2, D / 2 + 0.2, H - 0.9, H, STONE)
    bx(W / 2 + 0.2 - t, W / 2 + 0.2, -D / 2 - 0.2, D / 2 + 0.2, H - 0.9, H, STONE)
    return np.array(P, np.float32), np.array(U if len(U) == len(P) else np.zeros((len(P), 2)), np.float32), np.array(C, np.uint8)
