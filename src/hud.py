"""HUD: speed/health, stats, minimap, full map, floating slang labels, banners, streaming bar."""
import math
import random

import pyray as rl
import font   # noqa: E402

import slang
import weaponart
import vehicles
from actors import CAR_NAMES, WEAPONS
from geo import project

_A = 110                             # faint
POI_COL = {"shop": rl.Color(180, 90, 200, _A), "food": rl.Color(240, 140, 40, _A), "cafe": rl.Color(150, 100, 60, _A),
           "sight": rl.Color(220, 60, 120, _A), "money": rl.Color(60, 160, 80, _A), "health": rl.Color(230, 40, 40, _A),
           "school": rl.Color(60, 110, 220, _A), "hotel": rl.Color(90, 90, 160, _A), "play": rl.Color(120, 200, 80, _A),
           "worship": rl.Color(200, 170, 40, _A), "public": rl.Color(80, 80, 90, _A), "fuel": rl.Color(30, 30, 30, _A),
           "sport": rl.Color(40, 170, 170, _A), "culture": rl.Color(170, 40, 170, _A), "market": rl.Color(250, 200, 40, _A),
           "transport": rl.Color(40, 60, 200, _A), "night": rl.Color(140, 20, 160, _A), "police": rl.Color(20, 40, 140, _A)}


def build_labels(world, seed=5):
    """Shop signs and graffiti pinned to buildings + landmark names. -> [(text, x, y_height, z, kind)]"""
    rng = random.Random(seed)
    out = []
    B = world.buildings
    if B:
        idx = list(range(len(B)))
        rng.shuffle(idx)
        shops = graf = 0
        for i in idx:
            b = B[i]
            x0, y0, x1, y1 = b["bb"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if abs(cx) > world.hx - 30 or abs(cy) > world.hy - 30:
                continue
            if 120 < b["area"] < 2500 and shops < 420:
                out.append((rng.choice(slang.SHOP_NAMES), cx, b["h"] + 0.5, cy, "shop"))
                shops += 1
            elif b["area"] < 220 and graf < 260:
                out.append((rng.choice(slang.GRAFFITI), cx, b["h"] + 0.5, cy, "graf"))
                graf += 1
            if shops >= 420 and graf >= 260:
                break
    for name, lat, lon, note in slang.LANDMARKS:
        x, y = project(lat, lon)
        if abs(x) < world.hx and abs(y) < world.hy:
            out.append((name + " - " + note, x, 30.0, y, "land"))
    out.append(("Водно – крстот свети над градот", 0.0, 30.0, world.hy - 60, "land"))
    return out


def draw_labels(labels, cam, fx, fy, sw, sh):
    near = []
    for lb in labels:
        d2 = (lb[1] - fx) ** 2 + (lb[3] - fy) ** 2
        lim = 260 ** 2 if lb[4] == "land" else 75 ** 2
        if d2 < lim:
            near.append((d2, lb))
    near.sort(key=lambda a: a[0])
    used = []
    for d2, (text, x, y, z, kind) in near[:40]:
        sp = rl.get_world_to_screen(rl.Vector3(x, y, z), cam)
        if not (10 < sp.x < sw - 10 and 10 < sp.y < sh - 10):
            continue
        size = 22 if kind == "land" else (14 if kind.startswith("poi:") else 16)
        wpx = font.measure_text(text, size)
        r = (sp.x - wpx / 2, sp.y, wpx, size)
        if any(abs(r[0] - u[0]) < (r[2] + u[2]) / 2 + 4 and abs(r[1] - u[1]) < size + 4 for u in used):
            continue
        used.append(r)
        fade = 1.0 if kind == "land" else max(0.0, min(1.0, (75 - math.sqrt(d2)) / 30))
        a = int(235 * fade)
        px, py = int(r[0]), int(r[1])
        if kind == "shop":
            rl.draw_rectangle_rounded(rl.Rectangle(px - 6, py - 3, wpx + 12, size + 6), 0.3, 5, rl.Color(250, 214, 80, int(a * 0.92)))
            font.draw_text(text, px, py, size, rl.Color(40, 30, 10, a))
        elif kind.startswith("poi:"):                              # shop / café / school ... name tag
            c = POI_COL.get(kind[4:], POI_COL["shop"])
            rl.draw_rectangle_rounded(rl.Rectangle(px - 5, py - 2, wpx + 10, size + 4), 0.3, 5, rl.Color(250, 250, 246, int(a * 0.85)))
            rl.draw_rectangle(px - 5, py - 2, 4, size + 4, rl.Color(c.r, c.g, c.b, a))
            font.draw_text(text, px, py, size, rl.Color(30, 30, 34, a))
        elif kind == "graf":
            font.draw_text(text, px + 1, py + 1, size, rl.Color(0, 0, 0, int(a * 0.7)))
            font.draw_text(text, px, py, size, rl.Color(255, 90, 170, a))
        else:
            rl.draw_rectangle_rounded(rl.Rectangle(px - 8, py - 4, wpx + 16, size + 8), 0.3, 5, rl.Color(20, 40, 90, int(a * 0.85)))
            font.draw_text(text, px, py, size, rl.Color(255, 255, 255, a))


class Hud:
    def __init__(self, world, overview, ov_size):
        self.w = world
        self.ov = overview
        self.N = ov_size
        self.banner = ("", 0.0)
        self.tip_t = 0.0
        self.tip = ""
        self.markers = []            # (name, x, y) neighbourhoods drawn on the big map
        self.pois = []               # [x, y, category, name] faint points of interest (data/osm/map_pois.json)
        self.radio_line = ""          # car radio station / song, drawn in the vehicle panel
        self.place = ("", "", 0.0)   # neighbourhood tooltip: title, line, seconds left

    def set_banner(self, text, secs=3.0):
        self.banner = (text, max(secs * 1.3, 1.4 + len(text) * 0.075))

    def set_place(self, name, line, secs=5.0):
        self.place = (name, line, max(secs * 1.3, 1.6 + len(line or name) * 0.075))

    def update(self, dt):
        t, s = self.banner
        self.banner = (t, s - dt) if s > 0 else ("", 0.0)
        n, l, ps = self.place
        self.place = (n, l, ps - dt) if ps > 0 else ("", "", 0.0)

    def map_rect(self, sw, sh):
        """Big map rectangle (x, y, w, h), keeping the world's aspect ratio."""
        mw = sw - 80
        mh = int(mw * self.w.hy / self.w.hx)
        if mh > sh - 80:
            mh = sh - 80
            mw = int(mh * self.w.hx / self.w.hy)
        return (sw - mw) // 2, (sh - mh) // 2, mw, mh

    def map_pick(self, sw, sh):
        """Mouse click on the big map -> world (x, y) in metres, else None."""
        if not rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            return None
        mx, my, mw, mh = self.map_rect(sw, sh)
        m = rl.get_mouse_position()
        if mx <= m.x <= mx + mw and my <= m.y <= my + mh:
            return (m.x - mx) / mw * 2 * self.w.hx - self.w.hx, (m.y - my) / mh * 2 * self.w.hy - self.w.hy
        return None

    def draw(self, sim, sw, sh, show_map, prompt, streaming, ppm):
        W = self.w
        HX, HY = W.hx, W.hy
        st = sim.stats
        # ---- stats (right)
        x = sw - 270
        clk = sim.clock
        rl.draw_rectangle_rounded(rl.Rectangle(x - 10, 8, 268, 190), 0.1, 6, rl.Color(10, 10, 14, 150))
        font.draw_text(clk.label(), x + 150, 14, 26, rl.Color(255, 255, 255, 235))
        if clk.rush:
            font.draw_text("ШПИЦ", x + 150, 42, 18, rl.Color(255, 120, 90, 255))
        elif clk.dark > 0.5:
            font.draw_text("НОЌ", x + 150, 42, 18, rl.Color(150, 170, 255, 255))
        pz = getattr(sim, "money_pulse", 0.0)                          # swells when flying денари land
        font.draw_text(f"{sim.money} ден.", x, 14 - int(pz * 3), 24 + int(pz * 8), rl.Color(130 + int(pz * 120), 230, 140 - int(pz * 80), 255))
        for i, (lbl, val) in enumerate((("Бурек", st["burek"]), ("Удрени пешаци", st["peds"]), ("Нокаути", st.get("ko", 0)),
                                       ("Украдени коли", st["stolen"]), ("Експлозии", st["boom"]), ("Готов си", st["deaths"]))):
            i += 1.4
            font.draw_text(f"{lbl}: {val}", x, int(14 + i * 22), 20, rl.Color(250, 225, 120, 255) if i == 1.4 else rl.Color(235, 235, 235, 255))
        # ---- vehicle panel
        c = sim.car
        if sim.mode == "car":
            kmh = int(c.speed * 3.6)
            font.draw_text(f"{kmh}", sw - 190, sh - 78, 54, rl.Color(250, 220, 80, 255))
            font.draw_text("км/ч", sw - 78, sh - 52, 20, rl.Color(250, 220, 80, 255))
            if self.radio_line:
                font.draw_text(font.fit(self.radio_line, 17, 520), sw - 540, sh - 24, 17, rl.Color(190, 235, 255, 230))
            hp = max(0.0, c.health) / 100.0
            self._bar(sw - 260, sh - 106, 240, 16, hp, rl.Color(min(255, int(220 * (1 - hp) + 40)), min(255, int(200 * hp + 40)), 60, 255))
            font.draw_text(f"{c.name}  {int(max(0, c.health))}%", sw - 260, sh - 128, 18, rl.Color(255, 255, 255, 230))
            fu = max(0.0, getattr(c, "fuel", 1.0))
            self._bar(sw - 260, sh - 150, 240, 10, fu, rl.Color(230, 90, 60, 255) if fu < 0.15 else rl.Color(240, 170, 40, 255))
            font.draw_text(f"Гориво {int(fu * 100)}%" + ("  – ПРАЗНО!" if fu <= 0 else ""), sw - 260, sh - 170, 16,
                           rl.Color(255, 120, 90, 255) if fu < 0.15 else rl.Color(255, 255, 255, 220))
        else:
            wk = sim.walker
            font.draw_text("ПЕШКИ", sw - 190, sh - 60, 34, rl.Color(250, 220, 80, 255))
            if wk is not None:
                hp = max(0.0, wk.health) / 100.0
                self._bar(sw - 260, sh - 106, 240, 16, hp, rl.Color(min(255, int(220 * (1 - hp) + 40)), min(255, int(200 * hp + 40)), 60, 255))
                import actors as _a
                gun = ((_a.WEAPONS[wk.weapon][0] + ("" if wk.weapon in _a.MELEE else f" {wk.ammo}")) if wk.weapon in _a.WEAPONS and wk.ammo > 0 else "Тупаници [Ctrl]") + "  [Tab]"
                font.draw_text(f"Здравје {int(max(0, wk.health))}%   {gun}", sw - 260, sh - 130, 18, rl.Color(255, 255, 255, 230))
                self.weapon_icon(wk.weapon if wk.weapon in _a.WEAPONS and wk.ammo > 0 else "fist", sw - 260, sh - 196, 56)
                if wk.hurt_t > 0:
                    rl.draw_rectangle(0, 0, sw, sh, rl.Color(200, 20, 20, int(110 * min(1.0, wk.hurt_t / 0.35))))
                if wk.health <= 0 and wk.cause == "fight":
                    rl.draw_rectangle(0, 0, sw, sh, rl.Color(0, 0, 0, 170))
                    txt = "НОКАУТ..."
                    font.draw_text(txt, sw // 2 - font.measure_text(txt, 80) // 2, sh // 2 - 50, 80, rl.Color(255, 230, 90, 255))
                k = sim.near_kiosk(wk.x, wk.y) if wk.health > 0 else None
                if k is not None:
                    self._menu(sim, sw, sh)
        if prompt:
            wpx = font.measure_text(prompt, 24)
            rl.draw_rectangle_rounded(rl.Rectangle(sw // 2 - wpx // 2 - 14, sh - 120, wpx + 28, 40), 0.3, 6, rl.Color(10, 10, 14, 200))
            font.draw_text(prompt, sw // 2 - wpx // 2, sh - 112, 24, rl.Color(255, 240, 150, 255))
        t, s = self.banner
        if s > 0:
            a = int(255 * min(1.0, s / 0.5))
            wpx = font.measure_text(t, 40)
            font.draw_text(t, sw // 2 - wpx // 2 + 2, int(sh * 0.2) + 2, 40, rl.Color(0, 0, 0, a))
            font.draw_text(t, sw // 2 - wpx // 2, int(sh * 0.2), 40, rl.Color(255, 230, 90, a))
        pn, pl, ps = self.place
        if ps > 0:
            a = int(255 * min(1.0, ps / 0.6, (5.0 - ps) / 0.4 + 0.01))
            a = max(0, min(255, a))
            wn, wl = font.measure_text(pn, 34), font.measure_text(pl, 20)
            bw = max(wn, wl) + 40
            bx, by = sw // 2 - bw // 2, int(sh * 0.3)
            rl.draw_rectangle_rounded(rl.Rectangle(bx, by, bw, 78), 0.2, 6, rl.Color(14, 22, 52, int(a * 0.82)))
            font.draw_text(pn, sw // 2 - wn // 2, by + 8, 34, rl.Color(255, 230, 120, a))
            font.draw_text(pl, sw // 2 - wl // 2, by + 48, 20, rl.Color(225, 235, 255, a))
        if streaming:
            n, tot = streaming
            if tot > 0 and n < tot:
                bw = 220
                self._bar(sw // 2 - bw // 2, sh - 24, bw, 8, n / tot, rl.Color(120, 190, 250, 255))
                font.draw_text(f"Се вчитува мапата {n}/{tot}", sw // 2 - bw // 2, sh - 44, 14, rl.Color(200, 200, 200, 220))
        # ---- minimap / map
        fx, fy, _a, _b = sim.focus()
        N, NH = self.ov.width, self.ov.height
        k = N / (2 * HX)
        if not show_map:
            ms = 240
            mx, my = 16, sh - ms - 16
            span = 380
            half = span * k / 2
            cx = min(max((fx + HX) * k, half), N - half)
            cy = min(max((fy + HY) * k, half), NH - half)
            rl.draw_rectangle(mx - 3, my - 3, ms + 6, ms + 6, rl.Color(20, 20, 24, 255))
            rl.draw_texture_pro(self.ov, rl.Rectangle(cx - half, cy - half, half * 2, half * 2), rl.Rectangle(mx, my, ms, ms),
                                rl.Vector2(0, 0), 0.0, rl.WHITE)

            def to_mm(x, y):
                return mx + ((x + HX) * k - (cx - half)) / (half * 2) * ms, my + ((y + HY) * k - (cy - half)) / (half * 2) * ms

            for pk in sim.pickups:
                if pk[3]:
                    qx, qy = to_mm(pk[0], pk[1])
                    if mx < qx < mx + ms and my < qy < my + ms:
                        rl.draw_circle(int(qx), int(qy), 2.5, rl.Color(255, 200, 40, 255) if pk[2] == "burek" else rl.Color(230, 40, 40, 255))
            for x, y, cat, _nm in self.pois:
                if abs(x - fx) < 400 and abs(y - fy) < 400:
                    qx, qy = to_mm(x, y)
                    if mx < qx < mx + ms and my < qy < my + ms:
                        rl.draw_circle(int(qx), int(qy), 1.5, POI_COL.get(cat, POI_COL["shop"]))
            for cc in sim.traffic.cars:
                qx, qy = to_mm(cc.x, cc.y)
                if mx < qx < mx + ms and my < qy < my + ms:
                    rl.draw_rectangle(int(qx) - 1, int(qy) - 1, 3, 3, rl.Color(250, 250, 250, 230))
            for j in sim.services.jobs:
                if j.body is not None:
                    qx, qy = to_mm(j.body.x, j.body.y)
                    if mx < qx < mx + ms and my < qy < my + ms:
                        rl.draw_circle(int(qx), int(qy), 4, rl.Color(60, 120, 255, 255) if int(rl.get_time() * 4) & 1 else rl.Color(255, 50, 50, 255))
            qx, qy = to_mm(fx, fy)
            ang = c.h if sim.mode == "car" else sim.walker.h
            tip = rl.Vector2(qx + math.cos(ang) * 8, qy + math.sin(ang) * 8)
            l_ = rl.Vector2(qx + math.cos(ang + 2.5) * 6, qy + math.sin(ang + 2.5) * 6)
            r_ = rl.Vector2(qx + math.cos(ang - 2.5) * 6, qy + math.sin(ang - 2.5) * 6)
            rl.draw_triangle(tip, r_, l_, rl.Color(230, 40, 40, 255))
            rl.draw_triangle(tip, l_, r_, rl.Color(230, 40, 40, 255))
        else:
            mx, my, mw, mh = self.map_rect(sw, sh)
            rl.draw_rectangle(mx - 4, my - 4, mw + 8, mh + 8, rl.Color(20, 20, 24, 255))
            rl.draw_texture_pro(self.ov, rl.Rectangle(0, 0, N, NH), rl.Rectangle(mx, my, mw, mh), rl.Vector2(0, 0), 0.0, rl.WHITE)
            to_big = lambda x, y: (mx + (x + HX) / (2 * HX) * mw, my + (y + HY) / (2 * HY) * mh)
            for pk in sim.pickups:
                if pk[3] and pk[2] == "burek":
                    qx, qy = to_big(pk[0], pk[1])
                    rl.draw_circle(int(qx), int(qy), 3, rl.Color(255, 200, 40, 255))
                elif pk[3] and pk[2] in WEAPONS:                 # weapons: red dot + first letter (П, У, К, З ...)
                    qx, qy = to_big(pk[0], pk[1])
                    rl.draw_circle(int(qx), int(qy), 4, rl.Color(220, 30, 30, 255))
                    font.draw_text(WEAPONS[pk[2]][0][:1], int(qx) + 5, int(qy) - 9, 15, rl.Color(150, 10, 10, 255))
            for name, lat, lon, _n in slang.LANDMARKS:
                x, y = project(lat, lon)
                if abs(x) < HX and abs(y) < HY:
                    qx, qy = to_big(x, y)
                    font.draw_text(name, int(qx) + 6, int(qy) - 8, 16, rl.Color(20, 30, 90, 255))
                    rl.draw_circle(int(qx), int(qy), 4, rl.Color(20, 30, 90, 255))
            for x, y, cat, _nm in self.pois:                    # faint POI dots, coloured by kind
                qx, qy = to_big(x, y)
                rl.draw_circle(int(qx), int(qy), 1.6, POI_COL.get(cat, POI_COL["shop"]))
            for name, x, y in self.markers:
                qx, qy = to_big(x, y)
                rl.draw_circle(int(qx), int(qy), 4, rl.Color(120, 30, 30, 255))
                font.draw_text(name, int(qx) + 7, int(qy) - 8, 16, rl.Color(120, 30, 30, 255))
            qx, qy = to_big(fx, fy)
            rl.draw_circle(int(qx), int(qy), 7, rl.Color(230, 40, 40, 255))
            font.draw_text("Скопје – 11 x 7 км   КЛИКНИ за телепорт   (M за затворање)", mx, my - 30, 22, rl.Color(255, 255, 255, 255))

    def _menu(self, sim, sw, sh):
        items = vehicles.KIOSK_MENU
        w, h = 430, 40 + 30 * len(items)
        x, y = sw // 2 - w // 2, sh - h - 140
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.08, 6, rl.Color(10, 10, 14, 215))
        font.draw_text("КИОСК – скопски специјалитети", x + 14, y + 8, 22, rl.Color(250, 214, 80, 255))
        for i, (name, price, heal) in enumerate(items):
            ok = sim.money >= price
            col = rl.Color(235, 235, 235, 255) if ok else rl.Color(150, 150, 150, 255)
            font.draw_text(f"[{i + 1}] {name}", x + 14, y + 40 + i * 30, 20, col)
            font.draw_text(f"{price} ден.  +{heal}", x + w - 140, y + 40 + i * 30, 20, rl.Color(130, 230, 140, 255) if ok else col)

    @staticmethod
    def weapon_icon(kind, x, y, h):
        """Side-view icon of a weapon (same boxes as the 3D model) in a dark plate; x, y = top-left, h = plate height."""
        bx = weaponart.BOXES.get(kind)
        w = int(h * 2.6)
        rl.draw_rectangle(x, y, w, h, rl.Color(20, 20, 26, 190))
        rl.draw_rectangle_lines(x, y, w, h, rl.Color(250, 220, 80, 255))
        if kind == "fist":
            rl.draw_rectangle(x + w // 2 - h // 5, y + h // 4, h * 2 // 5, h // 2, rl.Color(226, 178, 140, 255))
            return
        if not bx:
            return
        x0 = min(b[0] for b in bx); x1 = max(b[0] + b[2] for b in bx)
        y0 = min(b[1] for b in bx); y1 = max(b[1] + b[3] for b in bx)
        k = min((w - 8) / (x1 - x0), (h - 8) / (y1 - y0))
        ox = x + (w - (x1 - x0) * k) / 2
        oy = y + (h - (y1 - y0) * k) / 2
        for bxx, byy, bw, bh, c in bx:
            rl.draw_rectangle(int(ox + (bxx - x0) * k), int(oy + (y1 - byy - bh) * k), max(1, int(bw * k)), max(1, int(bh * k)),
                              rl.Color(min(255, c[0] + 50), min(255, c[1] + 50), min(255, c[2] + 50), 255))

    @staticmethod
    def _bar(x, y, w, h, f, col):
        rl.draw_rectangle(x, y, w, h, rl.Color(30, 30, 36, 220))
        rl.draw_rectangle(x, y, int(w * max(0.0, min(1.0, f))), h, col)
        rl.draw_rectangle_lines(x, y, w, h, rl.Color(200, 200, 200, 160))
