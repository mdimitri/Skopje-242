"""Round 13: breakable bushes, children's playgrounds, sports pitches and school yards.

Geometry is baked into the chunk meshes like the other street furniture; the game gets the sites (kind, x, y, radius)
so it can fill them with kids, and every bush / piece of equipment is a breakable collision post."""
import math
import random

from furniture import G
from progress import span
from junk import _prism

BUSH_G = ((62, 112, 50), (76, 126, 56), (54, 98, 46), (96, 130, 60), (70, 110, 70), (120, 120, 60))
STEEL, RED, YEL, BLUE, WOOD = (150, 150, 158), (200, 60, 50), (230, 190, 50), (60, 110, 190), (150, 110, 70)


def bush(g, x, z, r, seed):
    """A low, lumpy shrub: two stacked faceted rings plus a smaller side lump."""
    rr = random.Random(seed)
    c = BUSH_G[seed % len(BUSH_G)]
    h = r * rr.uniform(0.9, 1.4)
    _prism(g, x, 0.0, z, r, h * 0.55, 6, tuple(v * 0.85 for v in c))
    _prism(g, x, h * 0.55, z, r * 0.7, h * 0.35, 6, c)
    a = rr.uniform(0, 6.28)
    _prism(g, x + math.cos(a) * r * 0.7, 0.0, z + math.sin(a) * r * 0.7, r * 0.55, h * 0.6, 5, tuple(min(255, v * 1.1) for v in c))
    if rr.random() < 0.25:                                     # flowering
        g.box(x, h * 0.9, z, r * 0.5, 0.08, r * 0.5, rr.choice(((230, 120, 160), (240, 230, 120), (240, 240, 240))))


def _rect_axes(ring):
    """Centre, unit long axis, half length, half width of a polygon (long axis = its longest edge direction)."""
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    best = max(zip(ring, ring[1:] + ring[:1]), key=lambda ab: math.dist(*ab))
    ux, uy = best[1][0] - best[0][0], best[1][1] - best[0][1]
    ln = math.hypot(ux, uy) or 1.0
    ux, uy = ux / ln, uy / ln
    us = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in ring]
    vs = [-(p[0] - cx) * uy + (p[1] - cy) * ux for p in ring]
    cx += ux * (max(us) + min(us)) / 2 - uy * (max(vs) + min(vs)) / 2
    cy += uy * (max(us) + min(us)) / 2 + ux * (max(vs) + min(vs)) / 2
    return cx, cy, ux, uy, (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2


def swing(g, x, z, yaw):
    for s in (-1, 1):
        for t in (-1, 1):
            px, pz = x + math.cos(yaw) * s * 1.2 + -math.sin(yaw) * t * 0.6, z + math.sin(yaw) * s * 1.2 + math.cos(yaw) * t * 0.6
            g.box(px, 0, pz, 0.08, 2.2, 0.08, STEEL)
    g.box(x, 2.15, z, 2.6, 0.1, 0.1, RED, yaw)
    for s in (-0.6, 0.6):
        px, pz = x + math.cos(yaw) * s, z + math.sin(yaw) * s
        g.box(px, 0.45, pz, 0.45, 0.05, 0.22, YEL, yaw)
        g.box(px, 0.5, pz, 0.03, 1.65, 0.03, (80, 80, 84), yaw)


def slide(g, x, z, yaw):
    ca, sa = math.cos(yaw), math.sin(yaw)
    g.box(x - ca * 1.2, 0, z - sa * 1.2, 0.9, 1.6, 0.9, BLUE, yaw)                 # tower
    g.box(x - ca * 1.2, 1.6, z - sa * 1.2, 1.0, 0.06, 1.0, RED, yaw)
    for i in range(6):                                                            # chute steps down the slope
        t = i / 6.0
        g.box(x - ca * (0.7 - t * 2.6), 1.45 * (1 - t), z - sa * (0.7 - t * 2.6), 0.48, 0.08, 0.55, YEL, yaw)


def sandbox(g, x, z, yaw):
    g.box(x, 0, z, 2.6, 0.08, 2.6, (214, 196, 150), yaw)
    for s in (-1, 1):
        g.box(x + math.cos(yaw) * s * 1.3, 0, z + math.sin(yaw) * s * 1.3, 0.12, 0.25, 2.7, WOOD, yaw)
        g.box(x - math.sin(yaw) * s * 1.3, 0, z + math.cos(yaw) * s * 1.3, 2.7, 0.25, 0.12, WOOD, yaw)


def seesaw(g, x, z, yaw):
    g.box(x, 0, z, 0.2, 0.45, 0.3, STEEL, yaw)
    g.box(x, 0.45, z, 3.0, 0.08, 0.25, RED, yaw)


def climber(g, x, z, yaw):
    for s in (-1, 1):
        for t in (-1, 1):
            g.box(x + s * 0.8, 0, z + t * 0.8, 0.07, 1.8, 0.07, YEL)
    for y in (0.6, 1.2, 1.8):
        g.box(x, y, z - 0.8, 1.7, 0.06, 0.06, BLUE)
        g.box(x, y, z + 0.8, 1.7, 0.06, 0.06, BLUE)
        g.box(x - 0.8, y, z, 0.06, 0.06, 1.7, BLUE)
        g.box(x + 0.8, y, z, 0.06, 0.06, 1.7, BLUE)


def carousel(g, x, z, yaw):
    _prism(g, x, 0.0, z, 1.3, 0.18, 10, RED)
    g.box(x, 0.18, z, 0.1, 0.9, 0.1, STEEL)
    g.box(x, 0.95, z, 1.9, 0.06, 0.06, YEL, yaw)
    g.box(x, 0.95, z, 0.06, 0.06, 1.9, YEL, yaw)


PLAY = (swing, slide, sandbox, seesaw, climber, carousel)


def goal(g, x, z, yaw, w=7.3, h=2.44):
    ca, sa = math.cos(yaw), math.sin(yaw)                   # yaw = direction the goal mouth faces
    rx, rz = -sa, ca
    for s in (-1, 1):
        g.box(x + rx * s * w / 2, 0, z + rz * s * w / 2, 0.12, h, 0.12, (240, 240, 240))
        g.box(x + rx * s * w / 2 - ca * 1.0, 0, z + rz * s * w / 2 - sa * 1.0, 0.06, h * 0.6, 0.06, (200, 200, 200))
    g.box(x, h, z, 0.12, 0.12, w, (240, 240, 240), yaw)
    g.box(x - ca * 0.6, h * 0.55, z - sa * 0.6, 1.0, 0.02, w, (226, 226, 226), yaw)    # net roof hint


def hoop(g, x, z, yaw):
    ca, sa = math.cos(yaw), math.sin(yaw)
    g.box(x - ca * 0.9, 0, z - sa * 0.9, 0.14, 3.2, 0.14, (70, 72, 80))
    g.box(x - ca * 0.6, 2.9, z - sa * 0.6, 0.06, 1.05, 1.8, (240, 240, 240), yaw)
    g.box(x - ca * 0.3, 3.0, z - sa * 0.3, 0.45, 0.04, 0.45, (230, 100, 30), yaw)


def flagpole(g, x, z):
    g.box(x, 0, z, 0.1, 7.0, 0.1, STEEL)
    g.box(x + 0.6, 6.0, z, 1.2, 0.8, 0.03, (210, 30, 30))
    g.box(x + 0.6, 6.25, z, 0.3, 0.3, 0.035, (250, 220, 40))


def build(areas, pois, edges, add, chunk_of, ok, free, not_building, inside, log=print):
    """-> (posts, sites).  posts: breakable collision circles; sites: (kind, x, y, radius) for the kids."""
    posts, sites = [], []
    n_bush = n_play = n_pitch = n_school = 0

    def put(g, x, z):
        pos, uv, col = g.out()
        if len(pos):
            add(chunk_of(x, z), 3, pos, uv, col)

    for ar in span(areas, 0.0, 0.6, "playgrounds, pitches, bushes"):
        kind, ring = ar["kind"], ar["outer"]
        if len(ring) < 3:
            continue
        r = random.Random(ar["id"] * 7 + 3)
        cx, cy, ux, uy, hl, hw = _rect_axes(list(ring))
        if not ok(cx, cy):
            continue
        yaw = math.atan2(uy, ux)
        if kind == "playground" and hl < 80:
            n = max(2, min(7, int(hl * hw / 40)))
            for k in range(n):
                for _try in range(8):
                    px, py = cx + ux * r.uniform(-hl, hl) * 0.7 - uy * r.uniform(-hw, hw) * 0.7, cy + uy * r.uniform(-hl, hl) * 0.7 + ux * r.uniform(-hw, hw) * 0.7
                    if inside(px, py, ring) and free(px, py):
                        g = G()
                        PLAY[(k + ar["id"]) % len(PLAY)](g, px, py, yaw + r.choice((0, math.pi / 2)))
                        put(g, px, py)
                        posts.append((px, py, 0.9))
                        break
            sites.append(("playground", round(cx, 1), round(cy, 1), round(max(4.0, min(hl, hw, 18)), 1)))
            n_play += 1
        elif kind == "pitch" and 8 < hl < 70 and hw > 4:
            if hl > 18:                                                  # football / handball: goals at both ends
                w = 7.3 if hl > 35 else 3.0
                for s in (-1, 1):
                    gx, gy = cx + ux * s * (hl - 1.0), cy + uy * s * (hl - 1.0)
                    g = G()
                    goal(g, gx, gy, yaw + (math.pi if s > 0 else 0.0), w, 2.44 if w > 4 else 2.0)
                    put(g, gx, gy)
                    for t in (-1, 1):
                        posts.append((gx - uy * t * w / 2, gy + ux * t * w / 2, 0.2))
            else:                                                        # basketball court
                for s in (-1, 1):
                    gx, gy = cx + ux * s * (hl - 0.8), cy + uy * s * (hl - 0.8)
                    g = G()
                    hoop(g, gx, gy, yaw + (math.pi if s > 0 else 0.0))
                    put(g, gx, gy)
                    posts.append((gx, gy, 0.2))
            sites.append(("pitch", round(cx, 1), round(cy, 1), round(max(5.0, min(hl, hw) * 0.9), 1)))
            n_pitch += 1
        elif kind in ("park", "cemetery", "grass"):                        # bushes among the park trees
            sp = 13.0 if kind == "park" else 22.0
            x0, y0, x1, y1 = ar["bb"]
            if (x1 - x0) * (y1 - y0) > 4e6:
                continue
            gy = y0 + r.uniform(0, sp)
            while gy < y1:
                gx = x0 + r.uniform(0, sp)
                while gx < x1:
                    px, py = gx + r.uniform(-4, 4), gy + r.uniform(-4, 4)
                    if inside(px, py, ring) and free(px, py) and ok(px, py):
                        g = G()
                        rb = r.uniform(0.6, 1.2)
                        bush(g, px, py, rb, n_bush)
                        put(g, px, py)
                        posts.append((px, py, rb * 0.75))
                        n_bush += 1
                    gx += sp
                gy += sp
    for x, y, cat, _nm in span(pois, 0.6, 0.7, "school yards"):                                          # school yards: flag, hoop, kids
        if cat != "school" or not ok(x, y):
            continue
        r = random.Random(int(x * 13 + y * 7))
        for _try in range(12):
            a, d = r.uniform(0, 6.28), r.uniform(12, 30)
            px, py = x + math.cos(a) * d, y + math.sin(a) * d
            if not_building(px, py) and free(px, py):
                g = G()
                flagpole(g, px, py)
                hoop(g, px + 6, py, 0.0)
                put(g, px, py)
                posts += [(px, py, 0.15), (px + 5.1, py, 0.2)]
                sites.append(("school", round(px, 1), round(py, 1), 12.0))
                n_school += 1
                break
    for e in span(edges, 0.7, 1.0, "hedges along streets"):            # hedges / shrubs along residential streets
        if not e["drive"] or e["bridge"] or e["cls"] not in ("residential", "living_street", "tertiary", "unclassified"):
            continue
        r = random.Random(e["a"] * 31 + e["b"])
        s = r.uniform(4, 20)
        pts, cum, L = e["pts"], e["cum"], e["len"]
        i = 0
        while s < L - 4:
            while i < len(pts) - 2 and cum[i + 1] < s:
                i += 1
            seg = cum[i + 1] - cum[i] or 1.0
            t = (s - cum[i]) / seg
            dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            ln = math.hypot(dx, dy) or 1.0
            side = r.choice((1, -1))
            off = e["w"] / 2 + 2.0 + r.uniform(1.0, 2.6)
            px = pts[i][0] + dx * t + dy / ln * side * off
            py = pts[i][1] + dy * t - dx / ln * side * off
            if ok(px, py) and not_building(px, py) and not_building(px + dy / ln * side * 1.3, py - dx / ln * side * 1.3) and free(px, py):
                g = G()
                rb = r.uniform(0.5, 1.0)
                bush(g, px, py, rb, n_bush)
                put(g, px, py)
                posts.append((px, py, rb * 0.75))
                n_bush += 1
            s += r.uniform(8, 26)
    log(f"[build] leisure: {n_bush} bushes, {n_play} playgrounds, {n_pitch} pitches, {n_school} school yards")
    return posts, sites
