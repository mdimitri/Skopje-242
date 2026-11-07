"""Skopje 2014 style bronze statues on stone pedestals (Macedonia Square and the Vardar banks).

All positions are APPROXIMATE (placed from memory of the layout, no OSM nodes exist for them): edit SPOTS to move one. Each spot is
nudged to the nearest free ground (not building, not water) within 15 m. x east, z south, metres from the city centre.
"""
import math

from furniture import G
from monument import tube, blob, disc, STONE, STONE2, BRONZE, BRONZE2, STEEL

# name: (x, z, facing yaw, kind, pedestal height m, bronze figure height m)
SPOTS = {
    "Филип II Македонски": (372, 205, 3.3, "king", 4.5, 4.2),
    "Мајка Тереза": (262, 372, 1.6, "robe", 1.2, 2.3),
    "Гоце Делчев": (318, 208, 4.7, "civil", 3.0, 3.4),
    "Даме Груев": (330, 228, 4.7, "civil", 3.0, 3.4),
    "Питу Гули": (250, 222, 1.6, "fighter", 3.0, 3.4),
    "Јане Сандански": (232, 198, 1.6, "fighter", 3.0, 3.4),
    "Тодор Александров": (342, 250, 4.7, "civil", 3.0, 3.4),
    "Никола Карев": (214, 172, 1.6, "civil", 3.0, 3.4),
    "Ѓорче Петров": (205, 132, 1.6, "civil", 3.0, 3.4),
    "Воин (Гладијатор)": (402, 98, 5.5, "warrior", 3.5, 3.6),
}


def figure(g, x, z, yaw, y, kind, h):
    """Standing bronze figure of height h on top of ground level y, facing yaw."""
    fx, fz = math.cos(yaw), math.sin(yaw)

    def T(f, up, s=0.0):
        return (x + fx * f - fz * s, y + up * h / 3.4, z + fz * f + fx * s)

    k = h / 3.4
    if kind == "robe":                                              # Mother Teresa: long sari and veil
        tube(g, T(0, 0), T(0, 1.9), 0.55 * k, 0.3 * k, BRONZE, 10)
        blob(g, T(0.05, 2.15), (fx, 0.3, fz), 0.3 * k, 0.32 * k, 0.28 * k, BRONZE2)
        tube(g, T(0.1, 1.8, 0.28), T(0.45, 1.25, 0.12), 0.1 * k, 0.07 * k, BRONZE, 6)
        tube(g, T(0.1, 1.8, -0.28), T(0.45, 1.25, -0.12), 0.1 * k, 0.07 * k, BRONZE, 6)
        return
    for s in (-0.18, 0.18):                                         # legs
        tube(g, T(0, 0, s), T(0.05, 1.5, s), 0.15 * k, 0.12 * k, BRONZE2 if kind != "king" else BRONZE, 7)
    tube(g, T(0, 1.5), T(0, 2.45), 0.36 * k, 0.32 * k, BRONZE, 8)                  # torso / coat
    if kind in ("civil", "king"):
        tube(g, T(0, 0.9), T(0, 1.55), 0.42 * k, 0.37 * k, BRONZE2, 8)             # frock coat skirt / robe
    blob(g, T(0.05, 2.75), (fx, 0, fz), 0.2 * k, 0.24 * k, 0.2 * k, BRONZE)       # head
    if kind == "king":
        tube(g, T(0.05, 2.9), T(0.05, 3.05), 0.22 * k, 0.2 * k, STEEL, 8)          # diadem / crown
        tube(g, T(0.3, 2.3, 0.5), T(0.5, 3.9, 0.55), 0.07 * k, 0.07 * k, BRONZE2, 5)   # spear
    if kind == "warrior":
        tube(g, T(0.05, 2.9), T(0.05, 3.2), 0.24 * k, 0.12 * k, STEEL, 8)          # helmet
        tube(g, T(0.1, 2.4, 0.4), T(0.6, 3.6, 0.6), 0.07 * k, 0.05 * k, STEEL, 5)  # raised sword
        blob(g, T(0.3, 1.9, -0.5), (fx, 0, fz), 0.06 * k, 0.45 * k, 0.45 * k, BRONZE2, 4, 8)   # shield
    if kind == "fighter":
        tube(g, T(0.1, 2.3, 0.4), T(0.7, 3.2, 0.5), 0.1 * k, 0.07 * k, BRONZE, 6)  # arm with rifle raised
        tube(g, T(0.5, 2.5, 0.5), T(0.8, 3.7, 0.55), 0.05 * k, 0.04 * k, BRONZE2, 5)
    for s in (-1, 1):
        if kind in ("civil", "king"):
            tube(g, T(0, 2.3, 0.38 * s), T(0.25, 1.5, 0.45 * s), 0.1 * k, 0.07 * k, BRONZE, 6)


def statue(x, z, yaw, kind, ph, h):
    """One statue, ground-relative geometry (the caller lifts by terrain)."""
    g = G()
    disc(g, x, 0.0, z, 1.7, 1.55, 0.35, STONE2, 12)
    g.box(x, 0.35, z, 2.0, ph, 2.0, STONE, yaw)
    g.box(x, 0.35 + ph, z, 2.3, 0.2, 2.3, STONE2, yaw)
    figure(g, x, z, yaw, 0.55 + ph, kind, h)
    return g


def build(add, chunk_of, free, terrain_h=None):
    posts, placed = [], {}
    for name, (x, z, yaw, kind, ph, h) in SPOTS.items():
        best = None
        for r in [0] + list(range(2, 16, 2)):
            for k in range(1 if r == 0 else 12):
                a = 2 * math.pi * k / 12
                px, pz = x + r * math.cos(a), z + r * math.sin(a)
                if all(free(px + dx, pz + dz) for dx in (-1.6, 1.6) for dz in (-1.6, 1.6)):
                    best = (px, pz)
                    break
            if best:
                break
        if not best:
            continue
        g = statue(best[0], best[1], yaw, kind, ph, h)
        pos, uv, col = g.out()
        add(chunk_of(best[0], best[1]), 3, pos, uv, col)
        t = float(terrain_h(*best)) if terrain_h else 0.0
        posts.append((best[0], best[1], 1.1, t - 1.0, t + 0.6 + ph + h))
        placed[name] = tuple(round(v, 1) for v in best)
    return posts, placed
