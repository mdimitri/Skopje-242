"""Points of interest you can walk into: come close to a shop / bank / cafe ... and a tooltip offers 1-4 things to do.
Pressing a number walks the avatar in (hidden inside), then back out with a spoken line in the avatar's own voice;
all other speech is suppressed for a few seconds afterwards.  POIs come from data/osm/map_pois.json: [x, y, category, name]."""
from texts import TXT
import math
import random

import pyray as rl

import font
import poi_vendors

REACH = 7.0
CELL = 60.0

# category -> [(label, price, heal, gain, what the avatar says he did)]   price = ден. paid, gain = ден. received
MENU = {
    "cafe": [(TXT("poi.0001"), 60, 8, 0, TXT("poi.0002")), (TXT("poi.0003"), 120, 12, 0, TXT("poi.0004")), (TXT("poi.0005"), 80, 10, 0, TXT("poi.0006")), (TXT("poi.0007"), 0, 4, 0, TXT("poi.0008"))],
    "food": [(TXT("poi.0009"), 200, 30, 0, TXT("poi.0010")), (TXT("poi.0011"), 120, 18, 0, TXT("poi.0012")), (TXT("poi.0013"), 90, 12, 0, TXT("poi.0014")), (TXT("poi.0015"), 0, 0, 0, TXT("poi.0016"))],
    "school": [(TXT("poi.0017"), 40, 0, 0, TXT("poi.0018")), (TXT("poi.0019"), 0, 3, 0, TXT("poi.0020")), (TXT("poi.0021"), 0, 0, 0, TXT("poi.0022")), (TXT("poi.0023"), 50, 0, 0, TXT("poi.0024"))],
    "health": [(TXT("poi.0025"), 70, 15, 0, TXT("poi.0026")), (TXT("poi.0027"), 150, 25, 0, TXT("poi.0028")), (TXT("poi.0029"), 300, 60, 0, TXT("poi.0030")), (TXT("poi.0031"), 0, 5, 0, TXT("poi.0032"))],
    "worship": [(TXT("poi.0033"), 20, 5, 0, TXT("poi.0034")), (TXT("poi.0035"), 0, 10, 0, TXT("poi.0036")), (TXT("poi.0037"), 100, 3, 0, TXT("poi.0038")), (TXT("poi.0039"), 0, 6, 0, TXT("poi.0040"))],
    "fuel": [(TXT("poi.0041"), 1200, 0, 0, TXT("poi.0042")), (TXT("poi.0043"), 100, 10, 0, TXT("poi.0044")), (TXT("poi.0045"), 200, 0, 0, TXT("poi.0046")), (TXT("poi.0047"), 0, 0, 0, TXT("poi.0048"))],
    "money": [(TXT("poi.0049"), 0, 0, 500, TXT("poi.0050")), (TXT("poi.0051"), 0, 0, 1000, TXT("poi.0052")), (TXT("poi.0053"), 0, 0, 100, TXT("poi.0054")), (TXT("poi.0055"), 0, 0, 300, TXT("poi.0056"))],
    "market": [(TXT("poi.0057"), 120, 15, 0, TXT("poi.0058")), (TXT("poi.0059"), 180, 20, 0, TXT("poi.0060")), (TXT("poi.0061"), 220, 18, 0, TXT("poi.0062")), (TXT("poi.0063"), 0, 5, 40, TXT("poi.0064"))],
    "police": [(TXT("poi.0065"), 0, 0, 0, TXT("poi.0066")), (TXT("poi.0067"), 0, 0, 0, TXT("poi.0068")), (TXT("poi.0069"), 300, 0, 0, TXT("poi.0070")), (TXT("poi.0071"), 60, 0, 0, TXT("poi.0072"))],
    "public": [(TXT("poi.0073"), 0, 0, 0, TXT("poi.0074")), (TXT("poi.0075"), 30, 0, 0, TXT("poi.0076")), (TXT("poi.0077"), 50, 0, 0, TXT("poi.0078")), (TXT("poi.0079"), 0, 0, 0, TXT("poi.0080"))],
    "culture": [(TXT("poi.0081"), 150, 10, 0, TXT("poi.0082")), (TXT("poi.0083"), 100, 6, 0, TXT("poi.0084")), (TXT("poi.0085"), 200, 0, 0, TXT("poi.0086")), (TXT("poi.0087"), 0, 2, 0, TXT("poi.0088"))],
    "night": [(TXT("poi.0089"), 250, 15, 0, TXT("poi.0090")), (TXT("poi.0091"), 0, 8, 0, TXT("poi.0092")), (TXT("poi.0093"), 100, 0, 0, TXT("poi.0094")), (TXT("poi.0095"), 100, 0, 250, TXT("poi.0096"))],
    "transport": [(TXT("poi.0097"), 40, 0, 0, TXT("poi.0098")), (TXT("poi.0099"), 0, 0, 0, TXT("poi.0100")), (TXT("poi.0101"), 50, 8, 0, TXT("poi.0102")), (TXT("poi.0103"), 0, 5, 0, TXT("poi.0104"))],
    "shop": [(TXT("poi.0105"), 100, 8, 0, TXT("poi.0106")), (TXT("poi.0107"), 400, 5, 0, TXT("poi.0108")), (TXT("poi.0109"), 0, 0, 60, TXT("poi.0110")), (TXT("poi.0111"), 0, 0, 0, TXT("poi.0112"))],
    "hotel": [(TXT("poi.0113"), 0, 0, 0, TXT("poi.0114")), (TXT("poi.0115"), 150, 12, 0, TXT("poi.0116")), (TXT("poi.0117"), 500, 40, 0, TXT("poi.0118")), (TXT("poi.0119"), 100, 0, 0, TXT("poi.0120"))],
    "sight": [(TXT("poi.0121"), 0, 2, 0, TXT("poi.0122")), (TXT("poi.0123"), 20, 3, 0, TXT("poi.0124")), (TXT("poi.0125"), 150, 0, 0, TXT("poi.0126")), (TXT("poi.0127"), 0, 0, 0, TXT("poi.0128"))],
    "sport": [(TXT("poi.0129"), 150, 20, 0, TXT("poi.0130")), (TXT("poi.0131"), 50, 10, 0, TXT("poi.0132")), (TXT("poi.0133"), 250, 15, 0, TXT("poi.0134")), (TXT("poi.0135"), 400, 35, 0, TXT("poi.0136"))],
    "play": [(TXT("poi.0137"), 0, 6, 0, TXT("poi.0138")), (TXT("poi.0139"), 0, 6, 0, TXT("poi.0140")), (TXT("poi.0141"), 0, 4, 0, TXT("poi.0142")), (TXT("poi.0143"), 20, 5, 0, TXT("poi.0144"))],
}
DEFAULT = [(TXT("poi.0145"), 0, 3, 0, TXT("poi.0146")), (TXT("poi.0147"), 80, 5, 0, TXT("poi.0148")), (TXT("poi.0149"), 0, 0, 0, TXT("poi.0150")), (TXT("poi.0151"), 0, 5, 0, TXT("poi.0152"))]
TITLES = {"cafe": TXT("poi.0153"), "food": TXT("poi.0154"), "school": TXT("poi.0155"), "health": TXT("poi.0156"), "worship": TXT("poi.0157"), "fuel": TXT("poi.0158"),
          "money": TXT("poi.0159"), "market": TXT("poi.0160"), "police": TXT("poi.0161"), "public": TXT("poi.0162"), "culture": TXT("poi.0163"), "night": TXT("poi.0164"),
          "transport": TXT("poi.0165"), "shop": TXT("poi.0166"), "hotel": TXT("poi.0167"), "sight": TXT("poi.0168"), "sport": TXT("poi.0169"), "play": TXT("poi.0170")}

# how each character ends the sentence (personality), picked at random
TAIL = {
    "kumplung": [TXT("poi.0171"), TXT("poi.0172"), TXT("poi.0173")], "maca": [TXT("poi.0174"), TXT("poi.0175"), TXT("poi.0176")],
    "mile": [TXT("poi.0177"), TXT("poi.0178"), TXT("poi.0179")], "stojan": [TXT("poi.0180"), TXT("poi.0181"), TXT("poi.0182")],
    "influenser": [TXT("poi.0183"), TXT("poi.0184"), TXT("poi.0185")], "influenserka": [TXT("poi.0186"), TXT("poi.0187"), TXT("poi.0188")],
    "tetkica": [TXT("poi.0189"), TXT("poi.0190"), TXT("poi.0191")], "baba": [TXT("poi.0192"), TXT("poi.0193"), TXT("poi.0194")],
    "dedo": [TXT("poi.0195"), TXT("poi.0196"), TXT("poi.0197")], "pandur": [TXT("poi.0198"), TXT("poi.0199"), TXT("poi.0200")],
    "doktor": [TXT("poi.0201"), TXT("poi.0202"), TXT("poi.0203")], "mali": [TXT("poi.0204"), TXT("poi.0205"), TXT("poi.0206")],
    "radnik": [TXT("poi.0207"), TXT("poi.0208"), TXT("poi.0209")], "burek": [TXT("poi.0210"), TXT("poi.0211"), TXT("poi.0212")],
    "boza": [TXT("poi.0213"), TXT("poi.0214"), TXT("poi.0215")], "fitka": [TXT("poi.0216"), TXT("poi.0217"), TXT("poi.0218")],
    "bilder": [TXT("poi.0219"), TXT("poi.0220"), TXT("poi.0221")], "shmizla": [TXT("poi.0222"), TXT("poi.0223"), TXT("poi.0224")],
    "palavko": [TXT("poi.0225"), TXT("poi.0226"), TXT("poi.0227")], "srednoskolec": [TXT("poi.0228"), TXT("poi.0229"), TXT("poi.0230")],
    "vojnik": [TXT("poi.0231"), TXT("poi.0232"), TXT("poi.0233")], "navivac": [TXT("poi.0234"), TXT("poi.0235"), TXT("poi.0236")],
    "administratorka": [TXT("poi.0237"), TXT("poi.0238"), TXT("poi.0239")], "nastavnica": [TXT("poi.0240"), TXT("poi.0241"), TXT("poi.0242")],
}
GENERIC_TAIL = [TXT("poi.0243"), TXT("poi.0244"), TXT("poi.0245")]


def tail_for(lik_id, rng):
    return rng.choice(TAIL.get(lik_id) or GENERIC_TAIL)


class Pois:
    IN, STAY, OUT = 1.0, 1.4, 1.0                  # seconds of each phase

    def __init__(self, pois, rng=None):
        self.cells = {}
        for p in pois:
            if p[3] and p[2] != "bench":
                self.cells.setdefault((int(p[0] // CELL), int(p[1] // CELL)), []).append(tuple(p))
        self.rng = rng or random.Random(11)
        self._menus = {}                            # (x, y) -> (vendor title or None, menu), guessed once per place
        self.state = None                           # None | "in" | "stay" | "out"
        self.t = 0.0
        self.cur = None                             # (x, y, cat, name) we are near / inside
        self.choice = None
        self.start = (0.0, 0.0)
        self.sup_until = 0.0                        # speech suppressed until this game time
        self.cool = 0.0

    @property
    def busy(self):
        return self.state is not None

    def near(self, x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        best, bd = None, REACH * REACH
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for p in self.cells.get((cx + i, cy + j), ()):
                    d = (p[0] - x) ** 2 + (p[1] - y) ** 2
                    if d < bd:
                        best, bd = p, d
        return best

    @staticmethod
    def menu(cat):
        return MENU.get(cat, DEFAULT)

    def menu_of(self, p):
        """(vendor title or None, menu) for place p = (x, y, cat, name): witty guess of what this vendor sells."""
        k = (p[0], p[1])
        m = self._menus.get(k)
        if m is None:
            m = self._menus[k] = poi_vendors.menu_for(p[2], p[3], self.menu(p[2]), p[0], p[1])
        return m

    def update(self, dt, sim, t_game, pick, lik_id, say, popups):
        """pick: 0..3 or None.  Returns True while the avatar is inside the animation (the caller blocks controls)."""
        wk = sim.walker
        self.cool -= dt
        ok = sim.mode == "foot" and wk is not None and wk.health > 0
        if self.state is None:
            self.cur = self.near(wk.x, wk.y) if ok and self.cool <= 0 else None
            if self.cur is None or pick is None or sim.near_kiosk(wk.x, wk.y) is not None:
                return False
            menu = self.menu_of(self.cur)[1]
            if not 0 <= pick < len(menu):
                return False
            lab, price, heal, gain, what = menu[pick]
            if sim.money < price:
                popups.add((f'{lab} = {price}' + TXT("poi.0246")), wk.x, wk.y, 2.8, 2.0, (255, 150, 140), 20)
                self.cool = 0.6
                return False
            self.choice = menu[pick]
            self.state, self.t = "in", 0.0
            self.start = (wk.x, wk.y)
            return True
        if not ok:                                   # died / left the walker: abort cleanly
            if wk is not None:
                wk.hidden = False
            self.state = None
            return False
        self.t += dt
        wk.inv_t = max(wk.inv_t, 0.5)
        wk.lx, wk.ly = wk.x, wk.y
        px, py = self.cur[0], self.cur[1]
        if self.state == "in":
            k = min(1.0, self.t / self.IN)
            wk.x, wk.y = self.start[0] + (px - self.start[0]) * k, self.start[1] + (py - self.start[1]) * k
            wk.h = math.atan2(py - self.start[1], px - self.start[0])
            wk.moving, wk.anim = True, wk.anim + dt * 7.0
            if self.t >= self.IN:
                self.state, self.t = "stay", 0.0
                wk.hidden = True
        elif self.state == "stay":
            wk.hidden = True
            if self.t >= self.STAY:
                lab, price, heal, gain, what = self.choice
                sim.money += gain - price
                wk.health = min(100.0, wk.health + heal)
                sim.stats["poi"] = sim.stats.get("poi", 0) + 1
                self.state, self.t = "out", 0.0
                wk.hidden = False
                line = f"{what}. {tail_for(lik_id, self.rng)}"
                self.sup_until = t_game + 6.5
                say(line, wk.x, wk.y)
                col = (140, 255, 150) if gain > price else (255, 220, 120)
                popups.add(line + ((f'  (+{gain - price}' + TXT("poi.0247")) if gain > price else (f'  (-{price}' + TXT("poi.0248")) if price else ""), px, py, 4.5, 3.4, col, 22)
        else:
            k = min(1.0, self.t / self.OUT)
            wk.x, wk.y = px + (self.start[0] - px) * k, py + (self.start[1] - py) * k
            wk.h = math.atan2(self.start[1] - py, self.start[0] - px)
            wk.moving, wk.anim = True, wk.anim + dt * 7.0
            if self.t >= self.OUT:
                self.state = None
                wk.moving = False
                self.cool = 2.0
                return False
        return True

    def draw(self, sim, sw, sh):
        if self.state is not None or self.cur is None or sim.walker is None:
            return
        vt, menu = self.menu_of(self.cur)
        title = f"{self.cur[3]}  ·  {vt or TITLES.get(self.cur[2], TXT("poi.0252"))}"
        w, h = 470, 44 + 28 * len(menu)
        x, y = sw // 2 - w // 2, sh - h - 150
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.08, 6, rl.Color(10, 10, 14, 215))
        font.draw_text(title[:40], x + 14, y + 8, 22, rl.Color(250, 214, 80, 255))
        for i, (lab, price, heal, gain, _w) in enumerate(menu):
            ok = sim.money >= price
            col = rl.Color(235, 235, 235, 255) if ok else rl.Color(150, 150, 150, 255)
            font.draw_text(f"[{i + 1}] {lab}", x + 14, y + 40 + i * 28, 20, col)
            tag = ((f'+{gain}' + TXT("poi.0249")) if gain and not price else (f'-{price}' + TXT("poi.0250")) if price else TXT("poi.0251"))
            font.draw_text(tag, x + w - 120, y + 40 + i * 28, 20, rl.Color(130, 230, 140, 255) if ok else col)
