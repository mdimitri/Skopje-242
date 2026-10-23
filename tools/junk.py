"""Junk, garbage and debris that pollute the city (round 10): 200+ named object types on pavements, in empty lots,
by the containers and on flat roofs. Built from ~45 low-poly recipes (a few boxes / prisms each) with size and
colour variants, baked into the chunk meshes like the other street furniture, so the cost stays per chunk."""
import os as _os, sys as _sys
_sys.path.append(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "src"))
from texts import TXT  # noqa: E402
import math
import random

from furniture import G


def _prism(g, cx, y0, cz, r, h, n, col, rz=None):
    """Upright n-sided prism (barrels, tyres, pipes standing, tanks); rz squashes it along z."""
    rz = r if rz is None else rz
    pts = [(cx + r * math.cos(2 * math.pi * i / n), cz + rz * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        nx, nz = b[1] - a[1], -(b[0] - a[0])
        ln = math.hypot(nx, nz) or 1.0
        g.quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y0 + h, b[1]), (a[0], y0 + h, a[1]), col, (nx / ln, 0, nz / ln))
    for i in range(1, n - 1):
        g.tri((pts[0][0], y0 + h, pts[0][1]), (pts[i + 1][0], y0 + h, pts[i + 1][1]), (pts[i][0], y0 + h, pts[i][1]), col, (0, 1, 0))


def _rot(x, z, cx, cz, yaw):
    ca, sa = math.cos(yaw), math.sin(yaw)
    return cx + ca * x - sa * z, cz + sa * x + ca * z


# ------------------------------------------------------------------ recipes: f(g, x, z, yaw, s, cols, r)
def r_box(g, x, z, yaw, s, c, r):
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)


def r_box_lid(g, x, z, yaw, s, c, r):
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    g.box(x, s[1], z, s[0] * 1.04, 0.04, s[2] * 1.04, c[1], yaw)


def r_pile(g, x, z, yaw, s, c, r):
    for _ in range(int(3 + s[1] * 6)):
        a, d = r.uniform(0, 6.28), r.uniform(0, s[0] / 2)
        g.box(x + math.cos(a) * d, r.uniform(0, s[1] * 0.4), z + math.sin(a) * d, r.uniform(0.15, 0.5) * s[2],
              r.uniform(0.08, 0.3) * s[1] * 2, r.uniform(0.15, 0.5) * s[2], r.choice(c), r.uniform(0, 3))


def r_bags(g, x, z, yaw, s, c, r):
    for _ in range(int(2 + s[0] * 3)):
        a, d = r.uniform(0, 6.28), r.uniform(0, s[0] / 2)
        _prism(g, x + math.cos(a) * d, 0, z + math.sin(a) * d, r.uniform(0.2, 0.32) * s[2], r.uniform(0.3, 0.55) * s[1], 6, r.choice(c))


def r_barrel(g, x, z, yaw, s, c, r):
    _prism(g, x, 0, z, s[0] / 2, s[1], 8, c[0])
    _prism(g, x, s[1] * 0.3, z, s[0] / 2 + 0.01, 0.05, 8, c[1])
    _prism(g, x, s[1] * 0.7, z, s[0] / 2 + 0.01, 0.05, 8, c[1])


def r_tyres(g, x, z, yaw, s, c, r):
    for k in range(int(s[1])):
        _prism(g, x + r.uniform(-0.05, 0.05), k * 0.22, z + r.uniform(-0.05, 0.05), s[0] / 2, 0.21, 8, c[0])
        _prism(g, x, k * 0.22 + 0.2, z, s[0] / 4, 0.02, 8, (20, 20, 20))


def r_lying(g, x, z, yaw, s, c, r):                  # pipes, planks, poles, rolled carpet: long thin things on the ground
    for k in range(int(s[2])):
        g.box(x + r.uniform(-0.2, 0.2), k * s[1], z + r.uniform(-0.2, 0.2), s[0], s[1], s[1] * 1.2, r.choice(c), yaw + r.uniform(-0.2, 0.2))


def r_sofa(g, x, z, yaw, s, c, r):
    L, D = s[0], s[2]
    g.box(x, 0.0, z, L, 0.42, D, c[0], yaw)
    bx, bz = _rot(0, -D / 2 + 0.1, x, z, yaw)
    g.box(bx, 0.42, bz, L, 0.45, 0.2, c[0], yaw)
    for side in (-1, 1):
        ax, az = _rot(side * (L / 2 - 0.1), 0, x, z, yaw)
        g.box(ax, 0.42, az, 0.2, 0.22, D, c[1], yaw)


def r_chair(g, x, z, yaw, s, c, r):
    g.box(x, 0.42, z, 0.45, 0.05, 0.45, c[0], yaw)
    bx, bz = _rot(0, -0.2, x, z, yaw)
    g.box(bx, 0.47, bz, 0.45, 0.45 * s[1], 0.05, c[0], yaw)
    for dx, dz in ((-0.18, -0.18), (0.18, -0.18), (-0.18, 0.18), (0.18, 0.18)):
        lx, lz = _rot(dx, dz, x, z, yaw)
        g.box(lx, 0, lz, 0.04, 0.42, 0.04, c[1], yaw)


def r_table(g, x, z, yaw, s, c, r):
    g.box(x, s[1], z, s[0], 0.05, s[2], c[0], yaw)
    for dx, dz in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        lx, lz = _rot(dx * (s[0] / 2 - 0.05), dz * (s[2] / 2 - 0.05), x, z, yaw)
        g.box(lx, 0, lz, 0.05, s[1], 0.05, c[1], yaw)


def r_appliance(g, x, z, yaw, s, c, r):               # fridge, washing machine, stove, boiler: a box with a door / dial
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    fx, fz = _rot(0, s[2] / 2 + 0.005, x, z, yaw)
    g.box(fx, s[1] * 0.25, fz, s[0] * 0.6, s[1] * 0.5, 0.02, c[1], yaw)


def r_tv(g, x, z, yaw, s, c, r):
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    fx, fz = _rot(0, s[2] / 2 + 0.005, x, z, yaw)
    g.box(fx, s[1] * 0.12, fz, s[0] * 0.8, s[1] * 0.75, 0.02, (30, 36, 40), yaw)


def r_cart(g, x, z, yaw, s, c, r):                    # shopping cart / baby pram / wheelbarrow
    g.box(x, 0.35, z, s[0], s[1], s[2], c[0], yaw)
    for dx in (-1, 1):
        for dz in (-1, 1):
            lx, lz = _rot(dx * s[0] * 0.4, dz * s[2] * 0.4, x, z, yaw)
            g.box(lx, 0, lz, 0.06, 0.35, 0.06, c[1], yaw)


def r_dish(g, x, z, yaw, s, c, r):                    # satellite dish on a short pole
    g.box(x, 0, z, 0.06, s[1], 0.06, (110, 110, 116))
    fx, fz = math.cos(yaw), math.sin(yaw)
    g.vpoly(x, s[1] - s[0] / 2, z, fx, fz, [(s[0] / 2 * math.cos(2 * math.pi * i / 10), s[0] / 2 + s[0] / 2 * math.sin(2 * math.pi * i / 10)) for i in range(10)], c[0], 0.1)
    g.vpoly(x, s[1] - s[0] / 2, z, -fx, -fz, [(s[0] / 2 * math.cos(-2 * math.pi * i / 10), s[0] / 2 + s[0] / 2 * math.sin(-2 * math.pi * i / 10)) for i in range(10)], c[0], -0.1)


def r_antenna(g, x, z, yaw, s, c, r):
    g.box(x, 0, z, 0.05, s[1], 0.05, c[0])
    for k in range(int(s[2])):
        g.box(x, s[1] * (0.6 + 0.12 * k), z, s[0] * (1 - 0.15 * k), 0.03, 0.03, c[0], yaw)


def r_tank(g, x, z, yaw, s, c, r):                    # rooftop water / solar boiler tank on legs
    for dx in (-1, 1):
        lx, lz = _rot(dx * s[0] * 0.3, 0, x, z, yaw)
        g.box(lx, 0, lz, 0.08, s[1] * 0.4, s[2], (90, 90, 96), yaw)
    g.box(x, s[1] * 0.4, z, s[0], s[1] * 0.6, s[2], c[0], yaw)


def r_solar(g, x, z, yaw, s, c, r):
    g.box(x, 0.3, z, s[0], 0.06, s[2], c[0], yaw)
    g.box(x, 0, z, 0.08, 0.3, 0.08, (120, 120, 126))


def r_coop(g, x, z, yaw, s, c, r):                    # pigeon coop / shed / dog house
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    g.box(x, s[1], z, s[0] * 1.1, 0.08, s[2] * 1.1, c[1], yaw)
    fx, fz = _rot(0, s[2] / 2 + 0.01, x, z, yaw)
    g.box(fx, s[1] * 0.3, fz, s[0] * 0.3, s[1] * 0.4, 0.02, (30, 28, 26), yaw)


def r_rack(g, x, z, yaw, s, c, r):                    # laundry rack with clothes
    for dx in (-1, 1):
        lx, lz = _rot(dx * s[0] / 2, 0, x, z, yaw)
        g.box(lx, 0, lz, 0.04, s[1], 0.5, (150, 150, 156), yaw)
    for k in range(4):
        cx_, cz_ = _rot(r.uniform(-s[0] / 2.5, s[0] / 2.5), 0, x, z, yaw)
        g.box(cx_, s[1] * 0.5, cz_, 0.3, s[1] * 0.45, 0.03, r.choice(c), yaw)


def r_bike(g, x, z, yaw, s, c, r):                    # bike / scooter / moped wreck lying or standing
    for dx in (-1, 1):
        wx, wz = _rot(dx * s[0] * 0.38, 0, x, z, yaw)
        g.vpoly(wx, s[1], wz, -math.sin(yaw), math.cos(yaw), [(s[1] * math.cos(2 * math.pi * i / 8), s[1] * math.sin(2 * math.pi * i / 8)) for i in range(8)], (26, 26, 28))
    g.box(x, s[1], z, s[0] * 0.7, 0.06, 0.06, c[0], yaw)
    g.box(x, s[1], z, 0.06, s[1] * 0.9, 0.06, c[0], yaw)


def r_flat(g, x, z, yaw, s, c, r):                    # doors, car bonnets, signs, mattresses, carpets lying flat
    g.box(x, 0.0, z, s[0], s[1], s[2], c[0], yaw + r.uniform(-0.4, 0.4))
    if len(c) > 1:
        g.box(x, s[1], z, s[0] * 0.6, 0.01, s[2] * 0.6, c[1], yaw)


def r_leaning(g, x, z, yaw, s, c, r):                 # boards / doors / mattress leaning on a wall
    fx, fz = math.cos(yaw + math.pi / 2), math.sin(yaw + math.pi / 2)
    g.vpoly(x, 0, z, fx, fz, [(-s[0] / 2, 0), (s[0] / 2, 0), (s[0] / 2, s[1]), (-s[0] / 2, s[1])], c[0], 0.0)
    g.vpoly(x, 0, z, -fx, -fz, [(s[0] / 2, 0), (-s[0] / 2, 0), (-s[0] / 2, s[1]), (s[0] / 2, s[1])], c[-1], 0.02)


def r_cone(g, x, z, yaw, s, c, r):
    _prism(g, x, 0, z, s[0] / 2, 0.06, 4, c[0])
    for k in range(4):
        _prism(g, x, 0.06 + k * s[1] / 4, z, s[0] / 2 * (1 - k / 4.5) * 0.7, s[1] / 4, 6, c[k % 2])


def r_tree_xmas(g, x, z, yaw, s, c, r):               # thrown-out christmas tree, dry plant, bush in a pot
    _prism(g, x, 0, z, 0.2, 0.3, 6, c[1])
    for k in range(3):
        _prism(g, x, 0.3 + k * s[1] / 3, z, s[0] / 2 * (1 - k / 3.5), s[1] / 3, 6, c[0])


def r_crates(g, x, z, yaw, s, c, r):                  # stacked crates / pallets / beer crates
    n = int(s[1])
    for k in range(n):
        g.box(x + r.uniform(-0.04, 0.04), k * s[2], z + r.uniform(-0.04, 0.04), s[0], s[2] * 0.95, s[0] * 0.8, c[k % len(c)], yaw + r.uniform(-0.15, 0.15))


def r_toilet(g, x, z, yaw, s, c, r):
    _prism(g, x, 0, z, 0.2, 0.4, 8, c[0], 0.26)
    bx, bz = _rot(0, -0.25, x, z, yaw)
    g.box(bx, 0.4, bz, 0.4, 0.35, 0.18, c[0], yaw)


def r_bathtub(g, x, z, yaw, s, c, r):
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    g.box(x, s[1] - 0.02, z, s[0] * 0.85, 0.03, s[2] * 0.7, c[1], yaw)


def r_carwreck(g, x, z, yaw, s, c, r):                # abandoned car shell on blocks: lower box + cabin, no wheels
    for dx in (-1, 1):
        for dz in (-1, 1):
            bx, bz = _rot(dx * s[0] * 0.33, dz * s[2] * 0.35, x, z, yaw)
            g.box(bx, 0, bz, 0.3, 0.22, 0.3, (130, 120, 110), yaw)
    g.box(x, 0.22, z, s[0], 0.55, s[2], c[0], yaw)
    cx_, cz_ = _rot(-s[0] * 0.05, 0, x, z, yaw)
    g.box(cx_, 0.77, cz_, s[0] * 0.5, 0.45, s[2] * 0.9, c[1], yaw)


def r_container(g, x, z, yaw, s, c, r):               # overflowing bin with bags around
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    g.box(x, s[1], z, s[0] * 1.02, 0.05, s[2] * 1.02, c[1], yaw)
    for _ in range(4):
        a = r.uniform(0, 6.28)
        _prism(g, x + math.cos(a) * s[0] * 0.8, 0, z + math.sin(a) * s[2] * 0.9, 0.25, 0.4, 6, r.choice(((30, 30, 32), (60, 60, 64), (200, 200, 190))))


def r_scaffold(g, x, z, yaw, s, c, r):                # leftover scaffolding / rebar cage
    for dx in (-1, 1):
        for dz in (-1, 1):
            px, pz = _rot(dx * s[0] / 2, dz * s[2] / 2, x, z, yaw)
            g.box(px, 0, pz, 0.05, s[1], 0.05, c[0], yaw)
    for k in range(1, 3):
        g.box(x, s[1] * k / 3, z, s[0], 0.05, s[2], c[1], yaw)


def r_ac(g, x, z, yaw, s, c, r):                      # air-conditioner outdoor unit
    g.box(x, 0, z, s[0], s[1], s[2], c[0], yaw)
    fx, fz = _rot(0, s[2] / 2 + 0.005, x, z, yaw)
    g.box(fx, s[1] * 0.15, fz, s[1] * 0.7, s[1] * 0.7, 0.02, (60, 60, 64), yaw)


def r_chimney(g, x, z, yaw, s, c, r):                 # stove pipes / vents sticking out of roofs
    _prism(g, x, 0, z, s[0] / 2, s[1], 6, c[0])
    _prism(g, x, s[1], z, s[0] * 0.7, 0.06, 6, c[-1])


def r_sign(g, x, z, yaw, s, c, r):                    # fallen / leaning billboard, "ПРОДАВАМ" sign, old shop sign
    g.box(x, 0, z, 0.06, s[1] * 0.6, 0.06, (100, 100, 104))
    fx, fz = math.cos(yaw), math.sin(yaw)
    g.vpoly(x, s[1] * 0.6, z, fx, fz, [(-s[0] / 2, 0), (s[0] / 2, 0), (s[0] / 2, s[1] * 0.4), (-s[0] / 2, s[1] * 0.4)], c[0], 0.04)
    g.vpoly(x, s[1] * 0.6, z, -fx, -fz, [(s[0] / 2, 0), (-s[0] / 2, 0), (-s[0] / 2, s[1] * 0.4), (s[0] / 2, s[1] * 0.4)], c[-1], 0.04)


def r_bottles(g, x, z, yaw, s, c, r):                 # bottles / cans / pet bottles scattered
    for _ in range(int(s[2])):
        a, d = r.uniform(0, 6.28), r.uniform(0, s[0])
        if r.random() < 0.5:
            _prism(g, x + math.cos(a) * d, 0, z + math.sin(a) * d, 0.04, s[1], 5, r.choice(c))
        else:
            g.box(x + math.cos(a) * d, 0, z + math.sin(a) * d, s[1], 0.07, 0.07, r.choice(c), r.uniform(0, 3))


R = {k[2:]: v for k, v in globals().items() if k.startswith("r_")}

# name, recipe, size (3 numbers, meaning per recipe), colours, where ("s" street, "r" roof, "b" both)
_BROWN, _GREY, _WHITE, _BLACK = (150, 110, 70), (130, 130, 134), (232, 232, 228), (34, 34, 36)
_BASE = [
    (TXT("junk_tool.0001"), "box", (0.5, 0.4, 0.4), [(176, 136, 90)], "b"),
    (TXT("junk_tool.0002"), "crates", (0.55, 3, 0.25), [(190, 150, 90), (170, 130, 80)], "s"),
    (TXT("junk_tool.0003"), "crates", (0.45, 2, 0.3), [(200, 40, 40), (40, 90, 180), (230, 190, 40)], "b"),
    (TXT("junk_tool.0004"), "crates", (0.42, 4, 0.3), [(30, 110, 60), (200, 40, 40)], "s"),
    (TXT("junk_tool.0005"), "flat", (1.2, 0.14, 0.8), [(170, 130, 80)], "b"),
    (TXT("junk_tool.0006"), "crates", (1.2, 5, 0.14), [(170, 130, 80), (150, 112, 70)], "s"),
    (TXT("junk_tool.0007"), "bags", (1.0, 1.0, 1.0), [(30, 30, 32), (60, 60, 64), (230, 230, 230), (40, 90, 50)], "s"),
    (TXT("junk_tool.0008"), "pile", (1.6, 0.6, 1.0), [(170, 160, 150), (140, 130, 120), (190, 110, 80)], "s"),
    (TXT("junk_tool.0009"), "pile", (1.2, 0.4, 0.6), [(190, 100, 70), (170, 90, 60)], "b"),
    (TXT("junk_tool.0010"), "pile", (1.8, 0.5, 1.4), [(214, 190, 140), (200, 176, 130)], "s"),
    (TXT("junk_tool.0011"), "tyres", (0.7, 3, 0), [_BLACK], "b"),
    (TXT("junk_tool.0012"), "tyres", (0.65, 1, 0), [_BLACK], "b"),
    (TXT("junk_tool.0013"), "barrel", (0.58, 0.88, 0), [(40, 80, 140), (30, 30, 34)], "b"),
    (TXT("junk_tool.0014"), "barrel", (0.5, 0.8, 0), [(40, 110, 200), (30, 80, 160)], "b"),
    (TXT("junk_tool.0015"), "container", (1.4, 1.2, 1.0), [(60, 110, 70), (40, 70, 45)], "s"),
    (TXT("junk_tool.0016"), "sofa", (1.9, 0, 0.85), [(120, 70, 50), (100, 60, 40)], "s"),
    (TXT("junk_tool.0017"), "sofa", (0.9, 0, 0.85), [(150, 120, 80), (120, 90, 60)], "b"),
    (TXT("junk_tool.0018"), "chair", (0, 1.0, 0), [_WHITE, _WHITE], "b"),
    (TXT("junk_tool.0019"), "chair", (0, 1.0, 0), [(140, 96, 60), (120, 80, 50)], "b"),
    (TXT("junk_tool.0020"), "table", (0.8, 0.72, 0.8), [(200, 200, 196), (90, 90, 94)], "b"),
    (TXT("junk_tool.0021"), "table", (1.2, 0.75, 0.8), [(170, 130, 90), (140, 100, 70)], "s"),
    (TXT("junk_tool.0022"), "appliance", (0.6, 1.6, 0.6), [_WHITE, (210, 210, 210)], "b"),
    (TXT("junk_tool.0023"), "appliance", (0.6, 0.85, 0.6), [_WHITE, (100, 110, 120)], "b"),
    (TXT("junk_tool.0024"), "appliance", (0.6, 0.85, 0.6), [_WHITE, _BLACK], "s"),
    (TXT("junk_tool.0025"), "appliance", (0.45, 0.8, 0.45), [_WHITE, (190, 190, 190)], "r"),
    (TXT("junk_tool.0026"), "tv", (0.6, 0.5, 0.5), [(60, 50, 44)], "b"),
    (TXT("junk_tool.0027"), "tv", (0.45, 0.38, 0.3), [(200, 196, 186)], "s"),
    (TXT("junk_tool.0028"), "cart", (0.9, 0.5, 0.55), [(170, 170, 176), (80, 80, 84)], "s"),
    (TXT("junk_tool.0029"), "cart", (0.8, 0.45, 0.5), [(60, 70, 120), (40, 40, 44)], "s"),
    (TXT("junk_tool.0030"), "cart", (1.0, 0.3, 0.5), [(200, 60, 40), (60, 60, 64)], "s"),
    (TXT("junk_tool.0031"), "dish", (0.8, 1.1, 0), [(220, 220, 220)], "r"),
    (TXT("junk_tool.0032"), "dish", (0.55, 0.8, 0), [(200, 200, 204)], "b"),
    (TXT("junk_tool.0033"), "antenna", (1.0, 2.4, 4), [(150, 150, 156)], "r"),
    (TXT("junk_tool.0034"), "antenna", (1.4, 3.0, 5), [(120, 120, 126)], "r"),
    (TXT("junk_tool.0035"), "tank", (1.4, 1.4, 1.0), [(40, 90, 170)], "r"),
    (TXT("junk_tool.0036"), "tank", (1.8, 1.2, 0.6), [(200, 200, 204)], "r"),
    (TXT("junk_tool.0037"), "solar", (1.6, 0.06, 1.0), [(30, 50, 90)], "r"),
    (TXT("junk_tool.0038"), "coop", (1.6, 1.2, 1.0), [(150, 120, 80), (120, 120, 126)], "r"),
    (TXT("junk_tool.0039"), "coop", (2.2, 2.0, 1.8), [(150, 150, 156), (110, 110, 116)], "b"),
    (TXT("junk_tool.0040"), "coop", (0.8, 0.7, 0.9), [(150, 100, 60), (110, 70, 40)], "s"),
    (TXT("junk_tool.0041"), "rack", (1.4, 1.2, 0), [(200, 50, 50), (60, 100, 200), _WHITE, (230, 200, 60)], "r"),
    (TXT("junk_tool.0042"), "bike", (1.6, 0.34, 0), [(40, 100, 180)], "s"),
    (TXT("junk_tool.0043"), "bike", (1.7, 0.3, 0), [(190, 50, 40)], "s"),
    (TXT("junk_tool.0044"), "bike", (1.0, 0.1, 0), [(20, 20, 22)], "s"),
    (TXT("junk_tool.0045"), "leaning", (0.9, 2.0, 0), [(140, 100, 60), (120, 84, 50)], "s"),
    (TXT("junk_tool.0046"), "leaning", (0.9, 1.9, 0), [(200, 190, 170), (180, 170, 150)], "s"),
    (TXT("junk_tool.0047"), "leaning", (1.2, 1.4, 0), [(150, 150, 156), (120, 120, 126)], "b"),
    (TXT("junk_tool.0048"), "flat", (2.0, 0.03, 1.4), [(150, 50, 50), (190, 140, 60)], "s"),
    (TXT("junk_tool.0049"), "flat", (1.3, 0.05, 1.1), [(200, 40, 40)], "s"),
    (TXT("junk_tool.0050"), "flat", (1.1, 0.06, 0.9), [(40, 90, 170)], "s"),
    (TXT("junk_tool.0051"), "box", (1.0, 0.2, 0.6), [(240, 240, 236)], "b"),
    (TXT("junk_tool.0052"), "lying", (3.0, 0.12, 3), [(170, 170, 176), (200, 120, 60)], "b"),
    (TXT("junk_tool.0053"), "lying", (2.5, 0.05, 6), [(170, 130, 80), (150, 112, 70)], "b"),
    (TXT("junk_tool.0054"), "lying", (4.0, 0.03, 8), [(110, 70, 50)], "b"),
    (TXT("junk_tool.0055"), "lying", (4.5, 0.25, 1), [_GREY], "s"),
    (TXT("junk_tool.0056"), "cone", (0.4, 0.7, 0), [(240, 110, 30), _WHITE], "s"),
    (TXT("junk_tool.0057"), "tree_xmas", (0.8, 1.6, 0), [(110, 100, 50), (120, 90, 60)], "s"),
    (TXT("junk_tool.0058"), "tree_xmas", (0.5, 0.6, 0), [(100, 110, 60), (190, 100, 60)], "r"),
    (TXT("junk_tool.0059"), "toilet", (0, 0, 0), [_WHITE], "s"),
    (TXT("junk_tool.0060"), "bathtub", (1.7, 0.55, 0.75), [_WHITE, (200, 210, 214)], "s"),
    (TXT("junk_tool.0061"), "carwreck", (3.6, 0, 1.55), [(150, 60, 40), (120, 50, 30)], "s"),
    (TXT("junk_tool.0062"), "carwreck", (3.9, 0, 1.65), [(90, 90, 96), (70, 70, 76)], "s"),
    (TXT("junk_tool.0063"), "scaffold", (2.0, 2.6, 1.0), [(150, 150, 156), (170, 130, 80)], "b"),
    (TXT("junk_tool.0064"), "ac", (0.8, 0.55, 0.3), [(236, 236, 236)], "r"),
    (TXT("junk_tool.0065"), "ac", (1.0, 0.8, 0.8), [(170, 170, 176)], "r"),
    (TXT("junk_tool.0066"), "chimney", (0.18, 1.2, 0), [(110, 110, 116), (60, 60, 64)], "r"),
    (TXT("junk_tool.0067"), "chimney", (0.4, 0.9, 0), [(170, 170, 176), (120, 120, 126)], "r"),
    (TXT("junk_tool.0068"), "sign", (2.4, 2.2, 0), [(240, 220, 60), (60, 60, 64)], "s"),
    (TXT("junk_tool.0069"), "sign", (0.9, 1.4, 0), [(240, 240, 230), (200, 40, 40)], "b"),
    (TXT("junk_tool.0070"), "bottles", (0.9, 0.24, 9), [(40, 120, 60), (200, 40, 40), (230, 230, 230), (190, 150, 60)], "s"),
    (TXT("junk_tool.0071"), "bottles", (1.2, 0.28, 12), [(200, 230, 240), (60, 140, 200)], "b"),
    (TXT("junk_tool.0072"), "lying", (2.8, 0.09, 4), [(96, 72, 50), (80, 60, 42)], "s"),
    (TXT("junk_tool.0073"), "lying", (2.0, 0.06, 9), [(110, 84, 56), (90, 70, 46)], "s"),
    (TXT("junk_tool.0074"), "lying", (5.0, 0.22, 1), [(100, 76, 52)], "s"),
    (TXT("junk_tool.0075"), "barrel", (0.42, 0.35, 0), [(120, 92, 60), (96, 72, 50)], "s"),
    (TXT("junk_tool.0076"), "pile", (1.4, 0.3, 1.1), [(160, 120, 40), (140, 90, 30), (110, 110, 40)], "s"),
    (TXT("junk_tool.0077"), "pile", (2.0, 0.35, 1.5), [(170, 110, 50), (190, 140, 60)], "s"),
    (TXT("junk_tool.0078"), "tree_xmas", (0.9, 0.9, 0), [(110, 84, 56), (90, 100, 50)], "s"),
    (TXT("junk_tool.0079"), "crates", (0.5, 4, 0.3), [(140, 104, 66), (120, 88, 56)], "s"),
    (TXT("junk_tool.0080"), "bottles", (1.6, 0.2, 10), [(230, 230, 230), (30, 30, 32), (60, 140, 200)], "s"),
    (TXT("junk_tool.0081"), "bottles", (1.8, 0.02, 14), [(236, 236, 230), (200, 196, 180)], "s"),
]
_VARIANTS = [("", 1.0, None), (TXT("junk_tool.0082"), 1.35, None), (TXT("junk_tool.0083"), 0.7, None), (TXT("junk_tool.0084"), 1.0, 0.75),
             (TXT("junk_tool.0085"), 0.95, 0.35)]


def _vary(c, k):
    return [tuple(int(min(255, v * k)) for v in col) for col in c]


CATALOG = []                                          # (name, recipe, size, colours, where)
for _name, _rec, _s, _c, _w in _BASE:
    for _suf, _k, _cm in _VARIANTS:
        sz = tuple(v * _k if i != 2 or _rec not in ("crates", "lying", "bottles") else v for i, v in enumerate(_s))
        if _rec in ("tyres", "crates", "lying", "bottles", "antenna") and _suf == TXT("junk_tool.0086"):
            continue                                  # counts of things don't shrink nicely
        CATALOG.append((_name + _suf, _rec, sz, _vary(_c, _cm) if _cm else _c, _w))
STREET = [i for i, c in enumerate(CATALOG) if c[4] in ("s", "b")]
ROOF = [i for i, c in enumerate(CATALOG) if c[4] in ("r", "b") and c[1] not in ("carwreck", "container", "cart")]


def make(i, x, z, yaw, seed):
    """Geometry (G) of catalogue item i at ground (y = 0)."""
    name, rec, s, c, _w = CATALOG[i]
    g = G()
    R[rec](g, x, z, yaw, s, c, random.Random(seed))
    return g


def footprint(i):
    s = CATALOG[i][2]
    return max(0.4, s[0] / 2)
