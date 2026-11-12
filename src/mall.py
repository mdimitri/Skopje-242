"""ГТЦ (Градски трговски центар, OSM way 28212881): a walkable mall interior, made at run time (no world rebuild).

One long hall runs along the building's long axis: two walking lanes either side of a central opening through which the
lower and upper floors are seen (not reachable), six escalators in the opening (start / middle / end, one along each lane),
shops with window displays on the outer side of each lane.  Doors sit on the real footprint walls: west (ул. 11 Октомври,
the square), east (ул. Стив Наумов), north (Кеј 13 Ноември) and south (парк Жена Борец).

Walking through a door switches the walker to `indoor` (actors.Walker uses collide() / floor instead of the city walls) and
main.py to the street-level camera; walking out of a door switches back.  Local frame: a along the hall (east), n across
it (south); everything is drawn relative to the floor height F."""
import math

import numpy as np

C = (541.49, 298.69)                         # footprint centre (game metres)
ANG = math.radians(22.0)                     # long axis
CA, SA = math.cos(ANG), math.sin(ANG)
A0, A1 = -136.0, 129.0                       # hall ends (the walls at -139.8 / 132.4 are the building's own)
H0, H1 = -120.0, 115.0                       # the central opening
LANE_I, LANE_O, SHOP = 3.5, 8.5, 11.5        # |n| of the opening edge, the shopfronts, the shops' back walls
CEIL, UP, LOW = 4.5, 5.0, -5.0               # ceiling under the upper floor's slab, upper floor, lower floor
ROOF = 10.0
R = 0.38                                     # walker radius (as actors.Walker.push_out)
# doors: (name, axis 'a'|'n', wall coordinate, outward sign, centre along the wall, half width)
DOORS = (("west", "a", -139.8, -1, 0.0, 3.0), ("east", "a", 132.4, 1, 0.0, 3.0),
         ("north", "n", -44.6, -1, 0.0, 2.8), ("south", "n", 66.2, 1, 0.0, 2.8))
ESC_A = (-110.0, 0.0, 105.0)
SHOPS = ("Бутик Ана", "Обувки Чекор", "Златара Вардар", "Книжарница Мисла", "Парфимерија Роза", "Мобилни Хало",
         "Слаткарница Шеќерче", "Кафе Корзо", "Аптека Здравје", "Играчки Лула", "Спорт Маратон", "Оптика Поглед",
         "Часовници Тик-так", "Цвеќара Божур", "Пекара Бурек", "Фризер Стил", "Кожна галантерија", "Детска мода Мими",
         "Чанти и куфери", "Бижутерија Бисер", "Електроника Волт", "Текстил Охрид", "Сувенири Скопје", "Менувачница",
         "Чевлара Мајстор", "Козметика Лале", "Теписи Ориент", "Музика Звук", "Фото Блиц", "Вез и чипка")


def to_world(a, n):
    return C[0] + a * CA - n * SA, C[1] + a * SA + n * CA


def to_local(x, y):
    dx, dy = x - C[0], y - C[1]
    return dx * CA + dy * SA, -dx * SA + dy * CA


def _walk_rects():
    """Walkable rectangles (a0, a1, n0, n1), already shrunk by the walker radius."""
    r = [(A0, A1, -LANE_O, -LANE_I), (A0, A1, LANE_I, LANE_O),                     # the two lanes
         (A0, H0, -LANE_O, LANE_O), (H1, A1, -LANE_O, LANE_O),                    # the end halls joining them
         (-139.8 - 3.0, A0 + 1.0, -3.0, 3.0), (A1 - 1.0, 132.4 + 3.0, -3.0, 3.0), # west / east doors (out past the wall)
         (-2.8, 2.8, -44.6 - 3.0, -LANE_O + 1.0), (-2.8, 2.8, LANE_O - 1.0, 66.2 + 3.0)]   # north / south corridors
    return [(a0 + R, a1 - R, n0 + R, n1 - R) for a0, a1, n0, n1 in r]


WALK = _walk_rects()
CAMR = [(A0 + 0.3, A1 - 0.3, -LANE_O + 0.3, LANE_O - 0.3)] + [(a0 - R + 0.3, a1 + R - 0.3, n0 - R + 0.3, n1 + R - 0.3) for a0, a1, n0, n1 in WALK[4:]]


def _inside(rects, a, n):
    return any(a0 <= a <= a1 and n0 <= n <= n1 for a0, a1, n0, n1 in rects)


def _outside_door(a, n):
    """The door this local point has walked out of (past its wall by 1.45 m: beyond where walking in starts), else None."""
    for nm, ax, w, s, c, hw in DOORS:
        u, v = (a, n) if ax == "a" else (n, a)
        if (u - w) * s > 1.45 and abs(v - c) < hw + 1.0:
            return nm
    return None


class Mall:
    def __init__(self, world):
        self.w = world
        gs = []
        for nm, ax, w, s, c, hw in DOORS:
            a, n = (w + s, c) if ax == "a" else (c, w + s)
            gs.append(world.ground_y(*to_world(a, n)))
        self.floor = float(sum(gs) / len(gs))                   # one level floor: the mean ground height at the doors
        self.model = None
        self.signs = []                                         # (x, y, z, name)
        hx, hy = getattr(world, "hx", 0.0), getattr(world, "hy", getattr(world, "hx", 0.0))
        self.enabled = abs(C[0]) + 150 < hx and abs(C[1]) + 80 < hy and not getattr(world, "demo", False)   # the GTC is in the box

    # ---------------------------------------------------------------- walking
    def update(self, sim):
        """Per frame, after the simulation: walking in at a door switches the walker indoors, walking out switches back."""
        wk = sim.walker if sim.mode == "foot" else None
        if wk is None or not self.enabled:
            return
        a, n = to_local(wk.x, wk.y)
        if getattr(wk, "indoor", None) is self:
            if _outside_door(a, n) or not (A0 - 12 < a < A1 + 12 and -52 < n < 74):
                wk.indoor = None                                 # walked out (or teleported away)
                wk.az = None
            return
        if wk.health <= 0:
            return
        va, vn = wk.vx * CA + wk.vy * SA, -wk.vx * SA + wk.vy * CA
        for nm, ax, w, s, c, hw in DOORS:
            u, v, vu = (a, n, va) if ax == "a" else (n, a, vn)
            if 0.0 <= (u - w) * s < 1.3 and abs(v - c) < hw - 0.3 and vu * s < -0.3:
                wk.indoor = self
                wk.az = self.floor
                return

    def collide(self, wk):
        """Keep the walker on the floor of the mall: slide along walls, the opening's balustrade and the shopfronts."""
        a, n = to_local(wk.x, wk.y)
        if _inside(WALK, a, n):
            return
        la, ln = to_local(wk.lx, wk.ly)
        for ta, tn in ((a, ln), (la, n), (la, ln)):
            if _inside(WALK, ta, tn) or (ta, tn) == (la, ln):
                wk.x, wk.y = to_world(ta, tn)
                break

    def cam_clip(self, f, p):
        """Fraction of the way from the focus f (x, y) to the camera p (x, y) that stays inside the hall."""
        fa, fn = to_local(*f)
        pa, pn = to_local(*p)
        for i in range(1, 21):
            t = i / 20.0
            if not _inside(CAMR, fa + (pa - fa) * t, fn + (pn - fn) * t):
                return max(0.0, (i - 1) / 20.0 - 0.03)
        return 1.0

    def in_hall(self, x, y):
        """Inside the mall's hall or its corridors (up to the building's walls)."""
        a, n = to_local(x, y)
        return (-139.8 < a < 132.4 and abs(n) < SHOP + 1.5) or (abs(a) < 4.5 and -44.6 < n < 66.2)

    # ---------------------------------------------------------------- geometry
    def build(self):
        import gl3d
        P, K = [], []
        rng = np.random.default_rng(242)
        lightdir = np.array([0.3, 0.8, 0.5])
        lightdir /= np.linalg.norm(lightdir)

        def quad(p0, du, dv, col, nrm):
            p0, du, dv = np.array(p0, float), np.array(du, float), np.array(dv, float)
            P.extend((p0, p0 + du, p0 + du + dv, p0, p0 + du + dv, p0 + dv))
            k = 0.72 + 0.32 * abs(float(np.dot(nrm, lightdir)))
            K.extend([tuple(min(255, int(c * k)) for c in col)] * 6)

        def box(a0, a1, y0, y1, n0, n1, col, faces="tbaAnN"):
            """Axis-aligned box in the local frame (a, y, n)."""
            da, dy, dn = a1 - a0, y1 - y0, n1 - n0
            if "t" in faces: quad((a0, y1, n0), (da, 0, 0), (0, 0, dn), col, (0, 1, 0))
            if "b" in faces: quad((a0, y0, n0), (da, 0, 0), (0, 0, dn), col, (0, 1, 0))
            if "a" in faces: quad((a0, y0, n0), (0, 0, dn), (0, dy, 0), col, (1, 0, 0))
            if "A" in faces: quad((a1, y0, n0), (0, 0, dn), (0, dy, 0), col, (1, 0, 0))
            if "n" in faces: quad((a0, y0, n0), (da, 0, 0), (0, dy, 0), col, (0, 0, 1))
            if "N" in faces: quad((a0, y0, n1), (da, 0, 0), (0, dy, 0), col, (0, 0, 1))

        def tiles(a0, a1, n0, n1, y, c1, c2, s=2.0):
            ia = max(1, int(round((a1 - a0) / s)))
            jn = max(1, int(round((n1 - n0) / s)))
            sa, sn = (a1 - a0) / ia, (n1 - n0) / jn
            for i in range(ia):
                for j in range(jn):
                    quad((a0 + i * sa, y, n0 + j * sn), (sa, 0, 0), (0, 0, sn), c1 if (i + j) % 2 else c2, (0, 1, 0))

        WALL, PIL, SLAB, CEILC = (226, 220, 206), (92, 88, 84), (200, 196, 188), (238, 236, 230)
        GLASS, RAIL = (150, 190, 205), (70, 74, 80)
        # ---- walking floor: lanes, end halls, corridors
        for a0, a1, n0, n1 in ((A0, A1, -LANE_O, -LANE_I), (A0, A1, LANE_I, LANE_O), (A0, H0, -LANE_I, LANE_I), (H1, A1, -LANE_I, LANE_I)):
            tiles(a0, a1, n0, n1, 0.0, (214, 206, 190), (178, 170, 156))
        for a0, a1, n0, n1 in ((-139.8, A0, -3, 3), (A1, 132.4, -3, 3), (-2.8, 2.8, -44.6, -LANE_O), (-2.8, 2.8, LANE_O, 66.2)):
            tiles(a0, a1, n0, n1, 0.0, (190, 182, 168), (160, 152, 140))
        # ---- shopfronts: three levels, both sides, along the hall
        names = list(SHOPS)
        rng.shuffle(names)
        ni = 0

        def shopfront(a0, a1, side, y0, h, named):
            """One shop between a0 and a1 on side (-1 north / +1 south), front at |n| = LANE_O, floor at y0."""
            nonlocal ni
            f, b = side * LANE_O, side * SHOP
            lo, hi = min(f, b), max(f, b)
            col = tuple(int(c) for c in rng.integers(40, 230, 3))
            inner = tuple(int(c * 0.35 + 150) for c in col)
            box(a0, a1, y0, y0 + h, b - side * 0.1, b, inner, "nN")                                   # back wall
            box(a0, a1, y0 + 0.01, y0 + 0.02, lo, hi, (120, 112, 104), "t")                           # shop floor
            box(a0, a1, y0 + h - 0.05, y0 + h, lo, hi, (235, 232, 225), "b")                          # shop ceiling
            for s_ in (a0, a1 - 0.4):                                                                 # pilasters
                box(s_, s_ + 0.4, y0, y0 + h, lo, hi, PIL, "aAnN")
            box(a0, a1, y0 + h - 1.1, y0 + h, f - side * 0.15, f + side * 0.05, col, "nNb")           # sign band
            box(a0 + 0.4, a1 - 0.4, y0, y0 + 0.45, f - side * 0.05, f + side * 0.35, (60, 58, 56), "tnN")   # window sill
            for s_ in np.linspace(a0 + 0.4, a1 - 0.4, 4):                                            # glazing bars
                box(s_ - 0.03, s_ + 0.03, y0 + 0.45, y0 + h - 1.1, f - side * 0.03, f + side * 0.03, RAIL, "aAnN")
            kind = int(rng.integers(0, 3))                                                            # the display
            for k in range(int((a1 - a0) // 1.3)):
                x = a0 + 0.9 + k * 1.3
                if x > a1 - 0.9:
                    break
                d = f + side * (0.9 + 0.6 * (k % 2))
                if kind == 0:                                                                         # mannequins
                    c2 = tuple(int(c) for c in rng.integers(30, 240, 3))
                    box(x - 0.08, x + 0.08, y0 + 0.45, y0 + 1.25, d - 0.08, d + 0.08, (225, 220, 215))
                    box(x - 0.24, x + 0.24, y0 + 1.15, y0 + 1.85, d - 0.14, d + 0.14, c2)
                    box(x - 0.11, x + 0.11, y0 + 1.9, y0 + 2.15, d - 0.11, d + 0.11, (232, 226, 218))
                elif kind == 1:                                                                       # shelves of goods
                    for sy in (0.9, 1.5, 2.1):
                        box(x - 0.6, x + 0.6, y0 + sy - 0.04, y0 + sy, d - 0.25, d + 0.25, (150, 120, 90))
                        for g in range(3):
                            c2 = tuple(int(c) for c in rng.integers(40, 250, 3))
                            gx = x - 0.4 + g * 0.4
                            box(gx - 0.14, gx + 0.14, y0 + sy, y0 + sy + float(rng.uniform(0.15, 0.4)), d - 0.15, d + 0.15, c2)
                else:                                                                                 # plinths with one piece each
                    box(x - 0.3, x + 0.3, y0 + 0.45, y0 + 1.05, d - 0.3, d + 0.3, (238, 236, 232))
                    c2 = tuple(int(c) for c in rng.integers(60, 250, 3))
                    box(x - 0.16, x + 0.16, y0 + 1.05, y0 + 1.35, d - 0.16, d + 0.16, c2)
            if named:
                x, z = to_world((a0 + a1) / 2, f - side * 0.2)
                self.signs.append((x, self.floor + y0 + h - 0.55, z, names[ni % len(names)]))
                ni += 1

        for side in (-1, 1):
            for y0, h, named in ((0.0, CEIL, True), (UP, 4.0, False), (LOW, 4.5, False)):
                a = A0
                while a < A1 - 3:
                    w = float(rng.choice((7.0, 8.0, 9.0, 10.0)))
                    a1 = min(A1, a + w)
                    if y0 == 0.0 and a1 > -3.2 and a < 3.2:              # the north / south corridor opens here
                        if a < -3.2:
                            shopfront(a, -3.2, side, y0, h, named)
                        a = 3.2
                        continue
                    if not (y0 == LOW and (a1 < H0 or a > H1)):        # the lower floor only under the opening
                        shopfront(a, a1, side, y0, h, named)
                    a = a1
        # ---- the slab between the levels at the opening edge, the upper floor, ceilings
        for side in (-1, 1):
            lo, hi = sorted((side * LANE_I, side * SHOP))
            box(A0, A1, CEIL, UP, lo, hi, SLAB, "b")                                               # our ceiling
            u0, u1 = sorted((side * LANE_I, side * LANE_O))
            tiles(A0, A1, u0, u1, UP, (205, 200, 190), (185, 178, 168))                             # the upper gallery
            box(H0, H1, CEIL, UP, side * LANE_I - 0.01, side * LANE_I + 0.01, SLAB, "nN")          # slab edge at the opening
            box(H0, H1, LOW + CEIL, 0.0, side * LANE_I - 0.01, side * LANE_I + 0.01, SLAB, "nN")   # our floor's edge, seen from below
            box(H0, H1, LOW + CEIL, LOW + CEIL + 0.01, lo, hi, SLAB, "b")                          # lower floor ceiling
            for y in (0.0, UP):                                                                      # balustrades: glass + handrail
                box(H0, H1, y, y + 1.05, side * LANE_I - 0.02, side * LANE_I + 0.02, GLASS, "nN")
                box(H0, H1, y + 1.05, y + 1.12, side * LANE_I - 0.06, side * LANE_I + 0.06, RAIL)
            for i in range(int((A1 - A0) // 6)):                                                     # ceiling lights
                la = A0 + 3 + i * 6
                ln = side * (LANE_I + LANE_O) / 2
                box(la - 0.8, la + 0.8, CEIL - 0.04, CEIL, ln - 0.6, ln + 0.6, (255, 252, 240), "b")
            for i in range(int((H1 - H0) // 12) + 1):                                                # columns at the opening
                ca = H0 + i * 12
                box(ca - 0.25, ca + 0.25, LOW, ROOF, side * (LANE_I + 0.3) - 0.25, side * (LANE_I + 0.3) + 0.25, (210, 206, 198))
        for a0, a1 in ((A0, H0), (H1, A1)):                                                        # end halls: ceiling + upper floor
            box(a0, a1, CEIL, UP, -LANE_I, LANE_I, SLAB, "b")
            tiles(a0, a1, -LANE_I, LANE_I, UP, (205, 200, 190), (185, 178, 168))
        tiles(H0, H1, -LANE_O, LANE_O, LOW, (196, 186, 170), (150, 142, 132))                      # the lower floor
        for i in range(int((H1 - H0) // 10)):                                                       # benches / planters down there
            pa = H0 + 5 + i * 10
            box(pa - 1.2, pa + 1.2, LOW, LOW + 0.5, -0.6, 0.6, (90, 120, 70) if i % 2 else (140, 100, 70))
            if i % 2:
                box(pa - 0.2, pa + 0.2, LOW + 0.5, LOW + 2.2, -0.2, 0.2, (60, 130, 60))
        box(A0, A1, ROOF, ROOF + 0.1, -SHOP, SHOP, CEILC, "b")                                     # roof, skylight over the opening
        for i in range(int((H1 - H0) // 4)):
            box(H0 + i * 4, H0 + i * 4 + 3.6, ROOF - 0.05, ROOF, -LANE_I + 0.4, LANE_I - 0.4, (205, 228, 245), "b")
        # ---- end walls, the opening's end walls, corridor walls
        for a_ in (A0, A1):
            for n0, n1 in ((-SHOP, -3.0), (3.0, SHOP)):
                box(a_, a_ + 0.01, 0.0, ROOF, n0, n1, WALL, "aA")
            box(a_, a_ + 0.01, 3.2, ROOF, -3.0, 3.0, WALL, "aA")
            box(a_, a_ + 0.01, UP, ROOF, -SHOP, SHOP, WALL, "aA")
        for a_ in (H0, H1):
            box(a_, a_ + 0.01, LOW, 0.0, -LANE_O, LANE_O, WALL, "aA")
            box(a_ - 0.02, a_ + 0.02, 0.0, 1.05, -LANE_I, LANE_I, GLASS, "aA")                     # balustrade across the end
            box(a_ - 0.02, a_ + 0.02, UP, UP + 1.05, -LANE_I, LANE_I, GLASS, "aA")
        for (n0, n1) in ((-44.6, -LANE_O), (LANE_O, 66.2)):
            for a_ in (-2.8, 2.8):
                box(a_, a_ + 0.01, 0.0, 3.6, n0, n1, (205, 196, 182), "aA")
            box(-2.8, 2.8, 3.6, 3.65, n0, n1, CEILC, "b")
            for i in range(int((n1 - n0) // 5)):
                box(-0.6, 0.6, 3.56, 3.6, n0 + 2 + i * 5, n0 + 3 + i * 5, (255, 252, 240), "b")
            for i in range(int((n1 - n0) // 7)):                                                  # posters along the corridor
                c2 = tuple(int(c) for c in rng.integers(40, 250, 3))
                for a_ in (-2.79, 2.78):
                    box(a_, a_ + 0.01, 1.0, 2.6, n0 + 2 + i * 7, n0 + 3.2 + i * 7, c2, "aA")
        # ---- doors: glass with the bright street behind
        for nm, ax, w, s, c, hw in DOORS:
            if ax == "a":
                box(w - s * 0.05, w, 0.0, 3.2, c - hw, c + hw, (232, 240, 248), "aA")
                box(w - s * 0.1, w - s * 0.05, 2.9, 3.2, c - hw, c + hw, RAIL, "aA")
            else:
                box(c - hw, c + hw, 0.0, 3.6, w - s * 0.05, w, (232, 240, 248), "nN")
        # ---- escalators: in the opening, one along each lane at each place; the north ones go up, the south ones down
        for ea in ESC_A:
            for side, y1 in ((-1, UP), (1, LOW)):
                n0, n1 = sorted((side * (LANE_I - 0.15), side * (LANE_I - 1.65)))
                L, steps = 12.0, 24
                for i in range(steps):
                    a0 = ea - L / 2 + i * L / steps
                    yy = y1 * (i + 0.5) / steps
                    box(a0, a0 + L / steps, yy - 0.18, yy, n0 + 0.1, n1 - 0.1, (80, 82, 88), "tA")
                for sn in (n0, n1 - 0.12):                                                         # side panels (glass) + rails
                    for i in range(steps):
                        a0 = ea - L / 2 + i * L / steps
                        yy = y1 * (i + 0.5) / steps
                        box(a0, a0 + L / steps, yy - 0.5, yy + 0.95, sn, sn + 0.12, GLASS if i % 2 else (140, 175, 190), "nN")
                        box(a0, a0 + L / steps, yy + 0.95, yy + 1.05, sn - 0.02, sn + 0.14, (30, 30, 34), "tnN")
        pos = np.asarray(P, np.float64)
        wx = C[0] + pos[:, 0] * CA - pos[:, 2] * SA
        wz = C[1] + pos[:, 0] * SA + pos[:, 2] * CA
        out = np.stack((wx, pos[:, 1] + self.floor, wz), 1).astype(np.float32)
        col = np.concatenate([np.asarray(K, np.uint8), np.full((len(K), 1), 255, np.uint8)], 1)
        self.model = gl3d.make_model(out, np.zeros((len(out), 2), np.float32), col)

    def draw(self, cam):
        """Inside a 3D pass with the mall camera."""
        import pyray as rl
        if self.model is None:
            self.build()
        if self.model is not None:
            rl.draw_model(self.model, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)

    def labels(self, cam, sw, sh):
        """Shop names on their sign bands (2D, after the 3D pass)."""
        import pyray as rl
        import font
        px, pz = cam.position.x, cam.position.z
        fx, fz = cam.target.x - px, cam.target.z - pz
        fl = math.hypot(fx, fz) or 1.0
        for x, y, z, nm in self.signs:
            dx, dz = x - px, z - pz
            d = math.hypot(dx, dz)
            if d > 32.0 or (dx * fx + dz * fz) / fl < 1.0:
                continue
            s = rl.get_world_to_screen(rl.Vector3(x, y, z), cam)
            size = int(max(12, min(30, 360 / max(d, 1.0))))
            wpx = font.measure_text(nm, size)
            a = int(255 * min(1.0, (32.0 - d) / 8.0))
            font.draw_text(nm, int(s.x - wpx / 2) + 1, int(s.y - size / 2) + 1, size, rl.Color(0, 0, 0, a))
            font.draw_text(nm, int(s.x - wpx / 2), int(s.y - size / 2), size, rl.Color(255, 250, 230, a))
