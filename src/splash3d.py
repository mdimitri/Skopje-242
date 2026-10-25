"""Loading screen, real 3D and endless: an infinitely scrolling street built with the game's own generators
(tools/build_world: facades with the game's window textures, roofs, parapets, trees, lamps; tools/furniture: benches,
bins, bus shelters) and the game's own car / character models.  Cars and characters appear in random order, each with a
joke or an unhinged quote; characters walk, fight, shoot, chase or rage.  Sun shadows are drawn like in the game.
The loader shows it as the big panel; progress is the small window beside it."""
from texts import TXT
import math
import os
import random
import sys

import numpy as np
import pyray as rl

import characters
import font
import gl3d
import showcase
import vehicles

V3 = rl.Vector3
UP = V3(0, 1, 0)
ONE = V3(1, 1, 1)
MSG = TXT("splash3d.0001")
SPEED = {"car": 9.0, "walk": 2.4, "fight": 0.0, "shoot": 0.0, "chase": 5.5, "rage": 0.0}
CH = 40.0                                     # street chunk length (m)
SHADOW = (0.5625, 0.5)                        # shadow shift per metre of height (the game's sun)
ASPH, PAVE, KERB = (96, 98, 104), (188, 182, 170), (160, 160, 164)
BUBBLES = [TXT("splash3d.0002"), TXT("splash3d.0003"), TXT("splash3d.0004"), TXT("splash3d.0005"),
           TXT("splash3d.0006"), TXT("splash3d.0007"), TXT("splash3d.0008"), TXT("splash3d.0009")]
HONKS = [TXT("splash3d.0010"), TXT("splash3d.0011"), TXT("splash3d.0012"), TXT("splash3d.0013"), TXT("splash3d.0014")]


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        h = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    lo, up = half(pts), half(pts[::-1])
    return lo[:-1] + up[:-1]


class Splash3D(showcase.Showcase):
    def __init__(self, seed=None):
        super().__init__(seed)
        self.rt = None
        self.models = {}
        self.wx = 0.0
        self.last = None
        self.cam = rl.Camera3D(V3(0, 3, 11), V3(0, 1, 0), UP, 38.0, rl.CAMERA_PERSPECTIVE)
        self.failed = False
        self.chunks = {}
        self.tex = None
        self.car_bag, self.char_bag = [], []
        self.amb = []                         # ambient road users: dicts (kind 'car'/'ped')
        self.talk = None                      # (until, text, world point provider)
        self.talk_t = 3.0
        self.ready = False
        try:
            tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
            if tools not in sys.path:
                sys.path.insert(0, tools)
            import build_world as BW
            import furniture as FU
            self.BW, self.FU = BW, FU
        except Exception:  # noqa: BLE001 - the flat showcase is the fallback
            self.failed = True

    # ------------------------------------------------------------------ sequence: random cars and characters
    def _next(self, now):
        want_char = self.rng.random() < 0.5
        if want_char:
            if not self.char_bag:
                self.char_bag = list(range(len(characters.LIKOVI))) + [showcase.NPC + a for a in vehicles.WALKERS if showcase.peds_lines.TOPICS.get(vehicles.PED_IDS[a])] + [showcase.PERS + k for k in range(len(showcase.PERSONAS))]
                self.rng.shuffle(self.char_bag)
            kind, i = "char", self.char_bag.pop()
            q = showcase.PERSONAS[i - showcase.PERS][2] if i >= showcase.PERS else showcase.peds_lines.idle(vehicles.PED_IDS[i - showcase.NPC]) if i >= showcase.NPC else showcase.L.QUOTE.get(characters.LIKOVI[i][0]) or [""]
            text, secs = self.rng.choice(q), showcase.CHAR_SECS
            act = self.rng.choice(("walk", "fight", "shoot", "chase", "rage"))
            extra = {"act": act, "dummy": self.rng.randrange(9)}
        else:
            if not self.car_bag:
                self.car_bag = list(range(vehicles.N))
                self.rng.shuffle(self.car_bag)
            kind, i = "car", self.car_bag.pop()
            jokes = list(showcase.L.CAR.get(vehicles.IDS[i]) or showcase.L.STYLE.get(vehicles.STYLE[i], []))
            ex = showcase.L.EXTRA.get(vehicles.EXTRA[i])
            if ex:
                jokes.append(ex)
            text, secs = (self.rng.choice(jokes) if jokes else ""), showcase.CAR_SECS
            self.shown_cars += 1
            extra = {"act": "car"}
        self.cur = {"kind": kind, "i": i, "text": text, "t0": now, "secs": secs, "col": None,
                    "k": (self.shown_cars - 1) % vehicles.N + 1, **extra}

    # ------------------------------------------------------------------ models
    def _car_model(self, i, color=None):
        k = ("c", i, color)
        if k not in self.models:
            self.models[k] = gl3d.car_model(i, (i * 5 + 3) % 12 if color is None else color)
        return self.models[k]

    def _ped_model(self, arch, frame):
        k = ("p", arch, frame)
        if k not in self.models:
            self.models[k] = gl3d.ped_model(arch, 0, frame, 3 if arch >= 100 else (arch * 3) % 4)
        return self.models[k]

    # ------------------------------------------------------------------ street chunks (the game's generators)
    def _chunk(self, n):
        BW, FU = self.BW, self.FU
        r = random.Random(n * 7777 + 13)
        x0, xc = n * CH, n * CH + CH / 2
        acc, shadows = {}, []

        def add(mat, pos, uv, col):
            if pos is not None and len(pos):
                acc.setdefault(mat, []).append((np.asarray(pos, np.float32), np.asarray(uv, np.float32), np.asarray(col, np.uint8)))

        def addbox(cx, cz, sx, sz, h, y0, col):
            add(BW.MAT_SOLID, *BW.box(cx, cz, sx, sz, h, y0, col))

        def addg(g):
            add(BW.MAT_SOLID, *g.out())

        W = (240, 240, 244)
        addbox(xc, 0, CH + 0.5, 9.0, 0.04, -0.04, ASPH)                                   # road
        for zc in (6.0, -6.0):
            addbox(xc, zc, CH + 0.5, 3.0, 0.08, 0.0, PAVE)                                # pavements
        for zc in (4.6, -4.6):
            addbox(xc, zc, CH + 0.5, 0.2, 0.1, 0.0, KERB)                                 # kerbs
        addbox(xc, 15.0, CH + 0.5, 15.0, 0.02, -0.03, (140, 182, 108))                    # grass, near side
        addbox(xc, -9.5, CH + 0.5, 4.0, 0.02, -0.03, (176, 172, 160))
        addbox(xc, -33.0, CH + 0.5, 52.0, 0.02, -0.03, (150, 186, 118))                   # grass behind the houses
        for k in range(0, int(CH), 6):
            addbox(x0 + k + 1.5, 0, 3.0, 0.16, 0.012, 0.0, W)                             # dashed centre line
        for zc in (-4.0, 4.0):
            addbox(xc, zc, CH + 0.5, 0.12, 0.012, 0.0, W)
        if n % 4 == 0:                                                                    # zebra crossing
            for k in range(-4, 5):
                addbox(x0 + 20, k * 1.0, 3.2, 0.5, 0.012, 0.0, W)
        # ---- buildings, far side: the game's own wall / roof / parapet generators with its facade textures
        for row, (zf, depth_rng) in enumerate(((-8.2, (9, 15)), (-26.0, (12, 20)))):
            x = x0 + r.uniform(1.5, 4)
            while x < x0 + CH - 11:
                w = min(r.uniform(9, 21), x0 + CH - 2.5 - x)      # never reach into the next chunk
                d = r.uniform(*depth_rng)
                typ = r.choices(("house", "panel", "office", "block"), (3, 3, 2, 4))[0]
                if row == 1:
                    typ = r.choices(("panel", "office", "block"), (4, 2, 3))[0]
                h = {"house": r.uniform(5.5, 9), "panel": r.uniform(16, 30), "office": r.uniform(10, 24), "block": r.uniform(9, 19)}[typ]
                if typ == "house":
                    w = min(w, 13)
                mat = {"house": BW.MAT_HOUSE, "panel": BW.MAT_PANEL, "office": BW.MAT_FACADE_B, "block": BW.MAT_FACADE_A}[typ]
                wallc = BW.vary(r.choice(BW.WALLS), r, 6)
                roofc = BW.vary(r.choice(BW.ROOFS), r, 6)
                zb, zt = zf - d, zf
                ring = [(x, zb), (x + w, zb), (x + w, zt), (x, zt)]
                add(mat, *BW.walls(ring, h, wallc))
                if typ == "house":
                    add(BW.MAT_ROOF, *BW.pyramid(ring, h, 1.8 + math.sqrt(w * d) * 0.12, roofc))
                else:
                    add(BW.MAT_ROOF, *BW.flat_poly(ring, [0, 1, 2, 0, 2, 3], h, 6.0, [c * 1.02 for c in roofc]))
                    pr = BW._parapet(ring, h, 0.55 if h > 8 else 0.35, [c * 0.82 for c in wallc])
                    if pr:
                        add(BW.MAT_SOLID, *pr)
                    for _ in range(r.randint(1, 3)):                                      # stairwell / AC boxes on the roof
                        add(BW.MAT_SOLID, *BW.box(x + r.uniform(2, w - 2), zb + r.uniform(2, d - 2), r.uniform(1.5, 3.2), r.uniform(1.5, 3.2),
                                                  r.uniform(1.0, 2.4), h, (150, 150, 156)))
                kx, kz = SHADOW[0] * min(h, 9.0), SHADOW[1] * min(h, 9.0)             # (capped: a 30 m block would black out the whole street)
                shadows.append(_hull([(px, pz) for px, pz in ring] + [(px + kx, pz + kz) for px, pz in ring]))
                x += w + r.uniform(4.0, 8.0)                                  # real gaps: no touching walls (z-fight flicker)
        # ---- street furniture and trees, near and far pavement
        x = x0 + r.uniform(2, 8)
        while x < x0 + CH - 2:
            z = r.choice((6.6, -6.4, -6.0))
            roll = r.random()
            if z > 0 and roll < 0.5:                                                     # the near pavement stays low: no view-blocking trees
                roll = 0.6 + 0.2 * r.random()
            if roll < 0.5:
                rad = r.uniform(2.0, 3.0)
                add(BW.MAT_SOLID, *BW.tree_geo(x, z, rad, r.randrange(6), n * 100 + int(x)))
                sx_, sz_ = SHADOW[0] * 3.6, SHADOW[1] * 3.6
                shadows.append(_hull([(x + sx_ + rad * 0.9 * math.cos(a), z + sz_ + rad * 0.9 * math.sin(a)) for a in np.linspace(0, 6.28, 9)[:-1]]))
            elif roll < 0.68:
                addg(FU.bench(x, z, 0.0 if z > 0 else math.pi))
                shadows.append(_hull([(x - 0.8 + dx, z - 0.3 + dz) for dx in (0, 1.6, 0.5, 2.1) for dz in (0, 0.6, 0.4, 1.0)]))
            elif roll < 0.8:
                addg(FU.bin_geo(x, z))
            elif roll < 0.88 and z < 0:
                addg(FU.bus_shelter(x, z, 0.0))
                shadows.append(_hull([(x - 1.5 + dx, z - 0.7 + dz) for dx in (0, 3.0, 1.2, 4.2) for dz in (0, 1.5, 1.1, 2.6)]))
            x += r.uniform(7, 15)
        for lx in (x0 + 8, x0 + 28):
            for zl in (-4.9,):
                add(BW.MAT_SOLID, *BW.lamp_geo(lx, zl))
                shadows.append(_hull([(lx + dx, zl + dz) for dx, dz in ((0, 0), (0.15, 0.1), (3.6, 3.2), (3.8, 3.3))]))
        names = ("A", "B", "roof", "white", "panel", "house")
        models = {}
        for mat, parts in acc.items():
            m = gl3d.make_model(np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts]))
            if m is not None:
                gl3d.set_texture(m, self.tex.get(names[mat]) or self.tex["A"])
                models[mat] = m
        return {"models": models, "shadows": shadows}

    def _free(self, ch):
        for m in ch["models"].values():
            gl3d.free_model(m)

    def _world(self, wx, burst):
        n_lo, n_hi = int(math.floor((wx - 40) / CH)), int(math.floor((wx + 70) / CH))
        built = 0
        for n in range(n_lo, n_hi + 1):
            if n not in self.chunks and (burst or built < 1):
                self.chunks[n] = self._chunk(n)
                built += 1
        for n in [k for k in self.chunks if k < n_lo - 1]:
            self._free(self.chunks.pop(n))
        rl.draw_cube(V3(wx, -0.08, -60), 400, 0.1, 300, rl.Color(150, 186, 118, 255))
        for k in range(int(math.floor((wx - 200) / 70)), int(math.floor((wx - 200) / 70)) + 8):            # far hills
            rr = random.Random(k * 31)
            rl.draw_cylinder(V3(k * 70 + rr.uniform(0, 30), 0, -150), 0.0, rr.uniform(35, 60), rr.uniform(25, 45), 8, rl.Color(112, 146, 128, 255))
        for n in range(n_lo, n_hi + 1):
            ch = self.chunks.get(n)
            if ch:
                for m in ch["models"].values():
                    rl.draw_model(m, V3(0, 0, 0), 1.0, rl.WHITE)

    # ------------------------------------------------------------------ shadows (same look as the game's: soft dark polygons)
    def _shadows(self, wx, dyn):
        rl.rl_disable_depth_mask()
        polys = []
        for n, ch in self.chunks.items():
            if abs(n * CH - wx) < 90:
                polys += ch["shadows"]
        polys += dyn
        col = rl.Color(10, 10, 24, 80)
        for hull in polys:
            for a, b in zip(hull[1:], hull[2:]):
                p0, p1, p2 = V3(hull[0][0], 0.11, hull[0][1]), V3(a[0], 0.11, a[1]), V3(b[0], 0.11, b[1])
                rl.draw_triangle_3d(p0, p1, p2, col) if (p1.x - p0.x) * (p2.z - p0.z) - (p1.z - p0.z) * (p2.x - p0.x) < 0 else rl.draw_triangle_3d(p0, p2, p1, col)
        rl.rl_enable_depth_mask()

    @staticmethod
    def _foot(x, z, hl, hw, hgt, yaw=0.0):
        ca, sa = math.cos(yaw), math.sin(yaw)
        pts = [(x + ca * sx * hl - sa * sz * hw, z + sa * sx * hl + ca * sz * hw) for sx in (-1, 1) for sz in (-1, 1)]
        kx, kz = SHADOW[0] * hgt, SHADOW[1] * hgt
        return _hull(pts + [(px + kx, pz + kz) for px, pz in pts])

    # ------------------------------------------------------------------ one frame
    def draw(self, x, y, w, h):
        now = self.now_fn()
        if self.failed:
            return super().draw(x, y, w, h)
        try:
            self._draw3d(now, x, y, w, h)
        except Exception:  # noqa: BLE001 - never break loading because of decoration: fall back to the flat version
            self.failed = True
            if os.environ.get("SK242_DEBUG"):
                import traceback
                traceback.print_exc()
            for fn in (rl.rl_enable_depth_mask, rl.end_mode_3d, rl.end_texture_mode):
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    pass

    def _ambient(self, wx, now, dt, dyn):
        """Background road users: oncoming cars in the far lane and pedestrians on the far pavement."""
        self.amb = []                                   # clean stage: only the avatar or the car in focus, no extra road users
        return
        r = self.rng
        self.amb = [a for a in self.amb if a["x"] > wx - 45 and a["x"] < wx + 90]
        if len(self.amb) < 7 and r.random() < 0.05:
            if r.random() < 0.5:
                self.amb.append({"k": "car", "x": wx + 70, "v": -r.uniform(7, 12), "i": r.randrange(vehicles.N), "z": -2.0})
            else:
                dirn = r.choice((-1, 1))
                self.amb.append({"k": "ped", "x": wx + r.uniform(-20, 35), "v": 1.3 * dirn, "i": r.randrange(9), "z": -5.4 if dirn < 0 else -6.4})
        for a in self.amb:
            a["x"] += (a["v"] + (0 if a["k"] == "car" else 0)) * dt
            if a["k"] == "car":
                m = self._car_model(a["i"], (a["i"] * 3) % 12)
                if m is not None:
                    rl.draw_model_ex(m, V3(a["x"], 0.0, a["z"]), UP, 180.0, ONE, rl.WHITE)
                dyn.append(self._foot(a["x"], a["z"], vehicles.DIMS[a["i"]][0] / 2, vehicles.DIMS[a["i"]][1] / 2, 1.5))
            else:
                m = self._ped_model(a["i"], int(now * 3.5 + a["x"]) % 2)
                if m is not None:
                    rl.draw_model_ex(m, V3(a["x"], 0.08, a["z"]), UP, 0.0 if a["v"] > 0 else 180.0, ONE, rl.WHITE)
                dyn.append(self._foot(a["x"], a["z"], 0.25, 0.25, 1.8))
        if now > self.talk_t:                                                           # a background voice with a problem
            vis = [a for a in self.amb if abs(a["x"] - wx) < 9]
            if vis:
                a = r.choice(vis)
                self.talk = (now + 3.6, r.choice(HONKS if a["k"] == "car" else BUBBLES), a)
            self.talk_t = now + r.uniform(5, 8)

    def _draw3d(self, now, x, y, w, h):
        if not self.ready:
            self.tex = gl3d.build_textures()
            self.ready = True
        if self.cur is None or now - self.cur["t0"] > self.cur["secs"]:
            self._next(now)
        c = self.cur
        t = (now - c["t0"]) / c["secs"]
        dt = 0.0 if self.last is None else min(0.1, max(0.0, now - self.last))
        first = self.last is None
        self.last = now
        self.wx += SPEED[c["act"]] * dt
        if self.rt is None or self.rt.texture.width != int(w) or self.rt.texture.height != int(h):
            self.rt = rl.load_render_texture(int(w), int(h))
        sh = int(h)
        rl.begin_texture_mode(self.rt)
        rl.clear_background(rl.Color(150, 195, 235, 255))
        rl.draw_rectangle_gradient_v(0, 0, int(w), int(h * 0.7), rl.Color(96, 156, 226, 255), rl.Color(228, 234, 240, 255))
        wx = self.wx
        carv = c["act"] == "car"
        sway = math.sin(now * 0.35)
        self.cam.position = V3(wx + 1.5 + 3.0 * sway, 4.2 + 0.4 * sway, 18.0 if carv else 11.5)
        self.cam.target = V3(wx + 0.5, 1.7 if carv else 1.4, 0)
        rl.begin_mode_3d(self.cam)
        rl.rl_disable_backface_culling()
        self._world(wx, first)
        dyn = []
        ease = lambda v: 1 - (1 - min(1.0, max(0.0, v))) ** 3
        if carv:
            off = -13 * (1 - ease(t * 5)) + 30 * max(0.0, (t - 0.82) / 0.18) ** 2
            m = self._car_model(c["i"])
            L_, W_, roof = vehicles.DIMS[c["i"]][0], vehicles.DIMS[c["i"]][1], vehicles.DIMS[c["i"]][4]
            cx_ = wx + 1.0 + off
            if m is not None:
                rl.draw_model_ex(m, V3(cx_, 0.02 * math.sin(now * 17), 1.9), UP, 0.0, ONE, rl.WHITE)
            dyn.append(self._foot(cx_, 1.9, L_ / 2, W_ / 2, roof))
            head = V3(cx_, roof + 0.8, 1.9)
        else:
            head = self._char_act(c, t, now, wx, dyn)
        self._ambient(wx, now, dt, dyn)
        self._shadows(wx, dyn)
        rl.rl_disable_backface_culling()      # the game renders its 2D bake passes with culling off
        rl.end_mode_3d()
        # ---- 2D overlay in the texture
        font.draw_text(MSG, 22, 18, 34, rl.Color(0, 0, 0, 120), bold=True)
        font.draw_text(MSG, 20, 16, 34, rl.WHITE, bold=True)
        a = int(255 * min(1.0, t * 6, (1.0 - t) * 6))
        if c["kind"] == "char" and head is not None:
            sp = rl.get_world_to_screen_ex(head, self.cam, int(w), int(h))
            words = c["text"][:int(len(c["text"]) * min(1.0, t / 0.4 + 0.01))]
            bw = int(min(w * 0.55, 440))
            lines = font.wrap(words, 20, bw - 24)[:6]
            bh = 18 + 26 * max(1, len(lines))
            bx = int(max(12, min(w - bw - 12, sp.x - bw * 0.25)))
            by = int(max(60, sp.y - bh - 24))
            rl.draw_rectangle_rounded(rl.Rectangle(bx, by, bw, bh), 0.25, 8, rl.Color(250, 250, 245, a))
            rl.draw_triangle(rl.Vector2(bx + bw * 0.25 - 10, by + bh - 2), rl.Vector2(sp.x, sp.y - 6), rl.Vector2(bx + bw * 0.25 + 22, by + bh - 2), rl.Color(250, 250, 245, a))
            for k, ln in enumerate(lines):
                font.draw_text(ln, bx + 12, by + 9 + 26 * k, 20, rl.Color(30, 30, 40, a), bold=True)
        if self.talk and now < self.talk[0]:                                            # small bubble from a bystander
            ag = self.talk[2]
            sp = rl.get_world_to_screen_ex(V3(ag["x"], 2.3 if ag["k"] == "ped" else 2.0, ag["z"]), self.cam, int(w), int(h))
            tw = font.measure_text(self.talk[1], 16, True) + 20
            bx = int(max(8, min(w - tw - 8, sp.x - tw / 2)))
            rl.draw_rectangle_rounded(rl.Rectangle(bx, sp.y - 34, tw, 28), 0.4, 6, rl.Color(255, 250, 215, 235))
            font.draw_text(self.talk[1], bx + 10, int(sp.y - 30), 16, rl.Color(50, 40, 30, 255), bold=True)
        band = int(sh * 0.2)
        rl.draw_rectangle(0, sh - band, int(w), band, rl.Color(10, 12, 18, 190))
        if c["kind"] == "car":
            tag, name, sub = f"{showcase.L_CARS}  {c['k']}/{vehicles.N}", vehicles.NAMES[c["i"]], c["text"]
        else:
            if c["i"] >= showcase.PERS:
                tag, name, sub = showcase.L_CHARS, showcase.PERSONAS[c["i"] - showcase.PERS][0], ""
            elif c["i"] >= showcase.NPC:
                tag, name, sub = showcase.L_CHARS, vehicles.PED_NAMES[c["i"] - showcase.NPC], ""
            else:
                lk = characters.LIKOVI[c["i"]]
                tag, name, sub = showcase.L_CHARS, lk[1], lk[2]
        up = int((1.0 - min(1.0, t * 6)) * 14)
        font.draw_text(tag, 20, sh - band + 8 + up, 14, rl.Color(150, 154, 165, a), bold=True)
        font.draw_text(font.fit(name, 26, int(w - 40), True), 20, sh - band + 26 + up, 26, rl.Color(240, 200, 60, a), bold=True)
        for k, ln in enumerate(font.wrap(sub, 18, int(w - 40))[:2]):
            font.draw_text(ln, 20, sh - band + 60 + 22 * k + up, 18, rl.Color(235, 235, 235, a))
        rl.end_texture_mode()
        rl.draw_texture_pro(self.rt.texture, rl.Rectangle(0, 0, self.rt.texture.width, -self.rt.texture.height), rl.Rectangle(x, y, w, h),
                            V2_0, 0.0, rl.WHITE)
        rl.draw_rectangle_lines(int(x), int(y), int(w), int(h), rl.Color(90, 92, 98, 255))

    def _char_act(self, c, t, now, wx, dyn):
        """Walk / fight / shoot / chase / rage with the character's in-game model; returns the point above the head."""
        arch, act, Z = (showcase._arch(c["i"]) if c["i"] >= showcase.NPC else 100 + c["i"]), c["act"], 1.9
        d = c["dummy"]
        if act == "walk":
            px = wx - 2.5 + 5.0 * t
            self._put(arch, int(now * 4.5) % 2, px, Z, dyn)
            return V3(px, 2.15, Z)
        if act == "fight":
            hit = int((now - c["t0"]) / 0.32)
            self._put(arch, 4 if hit % 2 == 0 else 5, wx, Z, dyn)
            ko = t > 0.6
            jit = 0.0 if ko else (0.12 * math.sin(now * 40) if hit >= 1 else 0.0)
            self._put(d, 2 if ko else 0, wx + 1.25 + jit + (0.3 if ko else 0.0), Z, dyn, math.pi)
            return V3(wx, 2.15, Z)
        if act == "shoot":
            px, tgt = wx - 2.2, wx + 2.8
            self._put(arch, 4, px, Z, dyn)
            ko = t > 0.55
            self._put(d, 2 if ko else 0, tgt + (0.5 if ko else 0.0), Z, dyn, math.pi)
            shot = (now - c["t0"]) % 0.9
            if shot < 0.12:
                bx = px + 0.9 + (tgt - px - 0.9) * (shot / 0.12)
                rl.draw_sphere(V3(bx, 1.08, Z + 0.3), 0.07, rl.Color(255, 230, 90, 255))
                rl.draw_sphere(V3(px + 0.85, 1.08, Z + 0.3), 0.22 * (1 - shot / 0.12), rl.Color(255, 190, 60, 255))
            return V3(px, 2.15, Z)
        if act == "chase":
            fr = int(now * 7) % 2
            self._put(arch, fr, wx - 0.5, Z, dyn)
            trip = t > 0.88
            self._put(d, 2 if trip else fr, wx + 2.8 + (0.6 if trip else 0.0), Z, dyn, 0.0)
            return V3(wx - 0.5, 2.15, Z)
        jump = abs(math.sin(now * 5.0)) * 0.5                                           # rage: arms up, jumping, cussing
        self._put(arch, 3 if int(now * 3) % 2 == 0 else 0, wx, Z, dyn, 0.0, jump)
        return V3(wx, 2.15 + jump, Z)

    def _put(self, arch, frame, px, pz, dyn, h=0.0, py=0.0):
        m = self._ped_model(arch, frame)
        if m is not None:
            rl.draw_model_ex(m, V3(px, py + 0.08, pz), UP, -math.degrees(h), ONE, rl.WHITE)
        dyn.append(self._foot(px, pz, 0.3 if frame != 2 else 0.9, 0.3, 1.9 if frame != 2 else 0.4))


V2_0 = rl.Vector2(0, 0)
