"""Map legend sites: a few shaded areas / icons (hospitals, police, barracks, stations) replace the thousands of faint POI dots."""
import math

import pyray as rl

HOSP_WORDS = ("болниц", "hospital", "клинич", "клиничл")
# kind -> (legend label, fill colour, outline colour)
KINDS = {"hospital": ("Болница", (230, 40, 40), (180, 20, 20)),
         "police": ("Полиција", (30, 60, 200), (20, 40, 140)),
         "army": ("Касарна", (90, 120, 40), (60, 85, 25)),
         "station": ("Станица", (150, 40, 40), (110, 30, 30))}


def build(sim, pois, compounds):
    """[(kind, x, y, name, ring_or_None, radius)]: one entry per site."""
    out = []
    import geo
    hs = [(p[0], p[1], p[3]) for p in pois if p[2] == "health" and any(w in p[3].lower() for w in HOSP_WORDS)]
    try:
        import actors
        hs += [(*geo.project(la, lo), n) for la, lo, n in actors.HELI_PADS]
    except Exception:  # noqa: BLE001
        pass
    cl = []                                                   # greedy clusters within 300 m
    for x, y, n in hs:
        for c in cl:
            if math.hypot(c[0] / c[2] - x, c[1] / c[2] - y) < 300:
                c[0] += x; c[1] += y; c[2] += 1
                break
        else:
            cl.append([x, y, 1, n])
    out += [("hospital", c[0] / c[2], c[1] / c[2], c[3], None, 110.0) for c in cl]
    out += [("police", p[0], p[1], p[3], None, 0.0) for p in pois if p[2] == "police"]
    for c in getattr(compounds, "list", ()) or ():
        if c.kind == "army":
            out.append(("army", (c.bb[0] + c.bb[2]) / 2, (c.bb[1] + c.bb[3]) / 2, c.name, c.ring, 0.0))
    for name, x, y, _yaw in getattr(sim.w, "stations", ()) or ():
        out.append(("station", x, y, name, None, 0.0))
    out += [("station", p[0], p[1], p[3], None, 0.0) for p in pois if p[2] == "transport" and "автобуска станица" in p[3].lower()]
    return out


def _col(c, a):
    return rl.Color(c[0], c[1], c[2], a)


def _outline(pts, col, w, ok=lambda q: True):
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        if ok(a) and ok(b):
            rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), w, col)


def _circle_pts(x, y, r, to):
    return [to(x + math.cos(i * math.tau / 24) * r, y + math.sin(i * math.tau / 24) * r) for i in range(24)]


def _icon(kind, qx, qy, s):
    """Small badge: white disc, coloured ring, glyph."""
    _l, f, o = KINDS[kind]
    rl.draw_circle(int(qx), int(qy), s + 1.5, rl.WHITE)
    rl.draw_circle(int(qx), int(qy), s, _col(f, 255))
    w = max(2.0, s * 0.3)
    if kind == "hospital":
        rl.draw_rectangle(int(qx - s * .6), int(qy - w / 2), int(s * 1.2), int(w), rl.WHITE)
        rl.draw_rectangle(int(qx - w / 2), int(qy - s * .6), int(w), int(s * 1.2), rl.WHITE)
    elif kind == "police":
        rl.draw_poly(rl.Vector2(qx, qy), 5, s * .55, -90, rl.WHITE)
    elif kind == "army":
        rl.draw_poly(rl.Vector2(qx, qy), 4, s * .6, 0, rl.WHITE)
    else:
        rl.draw_rectangle(int(qx - s * .55), int(qy - s * .35), int(s * 1.1), int(s * .7), rl.WHITE)


def draw(sites, to, big, ok=lambda q: True):
    """Areas first (fill + outline), then icons. `to` maps world -> screen; big=False is the minimap (outlines only, clipped by ok)."""
    for kind, x, y, _n, ring, r in sites:
        _l, f, o = KINDS[kind]
        pts = [to(px, py) for px, py in ring] if ring else (_circle_pts(x, y, r, to) if r else None)
        if pts is None:
            continue
        if big:
            c = to(x, y)
            for i in range(len(pts)):
                rl.draw_triangle(rl.Vector2(*c), rl.Vector2(*pts[i]), rl.Vector2(*pts[(i + 1) % len(pts)]), _col(f, 70))
                rl.draw_triangle(rl.Vector2(*c), rl.Vector2(*pts[(i + 1) % len(pts)]), rl.Vector2(*pts[i]), _col(f, 70))
        _outline(pts, _col(o, 230), 2.0 if big else 1.5, ok)
    s = 7 if big else 5
    for kind, x, y, _n, ring, r in sites:
        q = to(x, y)
        if ok(q):
            _icon(kind, q[0], q[1], s)


def draw_legend(font, sw, sh, x, y):
    rows = list(KINDS.items())
    w, h = 150, 12 + 24 * len(rows)
    rl.draw_rectangle(x, y, w, h, rl.Color(20, 20, 24, 215))
    for i, (k, (lab, _f, _o)) in enumerate(rows):
        _icon(k, x + 18, y + 18 + i * 24, 8)
        font.draw_text(lab, x + 36, y + 9 + i * 24, 18, rl.Color(240, 240, 235, 255))
