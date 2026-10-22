"""Neighbourhoods: tooltip when you enter one, and the teleport list. OSM `place` nodes are used when the map has them;
otherwise the approximate centres below (hand-placed, so treat the positions as rough)."""
import math
import random

from geo import project

# name, lat, lon, cynical one-liner
FALLBACK = [
    ("Центар", 41.9961, 21.4316, "Центар: статуи, гулаби и паркинг што не постои."),
    ("Стара Чаршија", 42.0007, 21.4375, "Стара Чаршија: бурек, ќебапи и цени како за туристи."),
    ("Кале", 42.0000, 21.4335, "Кале: најубав поглед на градот што никој не го поправи."),
    ("Дебар Маало", 41.9937, 21.4150, "Дебар Маало: повеќе кафулиња отколку луѓе."),
    ("Капиштец", 41.9915, 21.4262, "Капиштец: тука се гради сè, освен места за паркирање."),
    ("Зелен Пазар", 41.9993, 21.4300, "Зелен Пазар: свеж зеленчук и свежи цени."),
    ("Бит Пазар", 42.0012, 21.4392, "Бит Пазар: ако не го најдеш тука, не постои."),
    ("Чаир", 42.0165, 21.4420, "Чаир: градот во градот, со свој бурек."),
    ("Карпош", 42.0050, 21.3960, "Карпош: блокови, блокови и повеќе блокови."),
    ("Кисела Вода", 41.9790, 21.4400, "Кисела Вода: киселата вода ја нема, но градбата ја има."),
    ("Автокоманда", 41.9840, 21.4380, "Автокоманда: вечен собир на сообраќајни застои."),
    ("Гази Баба", 42.0030, 21.4520, "Гази Баба: далеку од центарот, блиску до гужвата."),
    ("Ѓорче Петров", 42.0060, 21.3820, "Ѓорче Петров: тишина, куќи и соседи."),
    ("Маџари", 41.9890, 21.4830, "Маџари: на крајот на булеварот, на почетокот на полето."),
]
GENERIC = ["Овде не се знае кој е газда на улицата.", "Познат реон, непознати паркинзи.", "Тука секој познава некој.",
           "Реон со бурек на секој агол (ако имаш врска)."]


_CYR = dict(zip("абвгдѓежзѕијклљмнњопрстќуфхцчџш", ["a", "b", "v", "g", "d", "gj", "e", "zh", "z", "dz", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p", "r", "s", "t", "kj", "u", "f", "h", "c", "ch", "dzh", "sh"]))


def translit(s):
    """Macedonian Cyrillic -> Latin (the built-in game font has no Cyrillic)."""
    out = []
    for ch in s:
        lo = ch.lower()
        if lo in _CYR:
            t = _CYR[lo]
            out.append(t.capitalize() if ch != lo else t)
        else:
            out.append(ch)
    return "".join(out)


def _area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2


def _inside(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


class Places:
    """Neighbourhoods straight from OpenStreetMap: place nodes plus place / administrative-boundary outlines.
    The smallest outline containing the player wins; otherwise the nearest place node within 600 m.
    Only if the map has no place data at all, the rough hand-placed FALLBACK list is used (and says so)."""

    def __init__(self, world):
        self.list = []                                    # (name, x, y, line)   - what the teleport list uses
        self.polys = []                                   # (area, name, poly)
        self.nodes = []                                   # (name, x, y)
        seen = set()
        for rec in getattr(world, "places", None) or []:
            if len(rec) < 7:                              # an older world file: (name, x, y)
                name_en, name, x, y, kind, poly = None, rec[0], rec[1], rec[2], "place", None
            else:
                name_en, name, x, y, kind, poly = rec[:6]
            label = name or name_en or "?"
            if poly and len(poly) >= 3:
                self.polys.append((_area(poly), label, poly))
            else:
                self.nodes.append((label, x, y))
            if (label, kind[:5]) not in seen and not kind.startswith("admin7"):
                seen.add((label, kind[:5]))
                self.list.append((label, x, y, None))
        self.approx = not self.list                       # no OSM places at all: rough fallback, clearly marked
        have = {p[0] for p in self.list}
        for name, lat, lon, line in FALLBACK:             # well-known places OSM has no node for (Чаршија, Кале ...)
            if name in have:
                continue
            x, y = project(lat, lon)
            if abs(x) < world.hx and abs(y) < world.hy:
                self.list.append((name, x, y, line))
                self.nodes.append((name, x, y))
        self.lang = 1                                     # language level (menu), set by main
        self.list.sort(key=lambda p: p[0])
        self.polys.sort(key=lambda p: p[0])
        self.cur = None
        self.rng = random.Random(77)

    def where(self, x, y):
        for _a, name, poly in self.polys:                 # smallest first
            if _inside(x, y, poly):
                return name
        best, bd = None, 600.0 ** 2
        for name, nx, ny in self.nodes:
            d = (nx - x) ** 2 + (ny - y) ** 2
            if d < bd:
                best, bd = name, d
        return best

    def line_for(self, name):
        import hood_lines
        return hood_lines.line(name, self.lang, self.rng)

    def update(self, x, y):
        """-> (name, line) the moment the player enters a new neighbourhood, else None."""
        name = self.where(x, y)
        if name != self.cur:
            self.cur = name
            if name:
                return name + (" (приближно)" if self.approx else ""), self.line_for(name)
        return None
