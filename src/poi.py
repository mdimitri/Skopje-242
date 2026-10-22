"""Points of interest you can walk into: come close to a shop / bank / cafe ... and a tooltip offers 1-4 things to do.
Pressing a number walks the avatar in (hidden inside), then back out with a spoken line in the avatar's own voice;
all other speech is suppressed for a few seconds afterwards.  POIs come from data/osm/map_pois.json: [x, y, category, name]."""
import math
import random

import pyray as rl

import font
import poi_vendors

REACH = 7.0
CELL = 60.0

# category -> [(label, price, heal, gain, what the avatar says he did)]   price = ден. paid, gain = ден. received
MENU = {
    "cafe": [("Македонско кафе", 60, 8, 0, "Испив кафе"), ("Ладно пиво", 120, 12, 0, "Испив пиво"), ("Сок и вода", 80, 10, 0, "Испив сок"), ("Седи на тераса", 0, 4, 0, "Седнав на тераса")],
    "food": [("Ќебапи", 200, 30, 0, "Изедов ќебапи"), ("Пица парче", 120, 18, 0, "Изедов парче пица"), ("Салата", 90, 12, 0, "Изедов салата"), ("Само прашај за цена", 0, 0, 0, "Прашав за цена и излегов")],
    "school": [("Купи тетратка", 40, 0, 0, "Купив тетратка"), ("Прескокни час", 0, 3, 0, "Побегнав од час"), ("Прашај за оценки", 0, 0, 0, "Прашав за оценки"), ("Донирај за школо", 50, 0, 0, "Дадов за школото")],
    "health": [("Аспирин", 70, 15, 0, "Купив аспирин"), ("Витамини", 150, 25, 0, "Купив витамини"), ("Преглед", 300, 60, 0, "Одев на преглед"), ("Чекај ред", 0, 5, 0, "Чекав во ред")],
    "worship": [("Запали свеќа", 20, 5, 0, "Запалив свеќа"), ("Молитва", 0, 10, 0, "Се помолив"), ("Дај прилог", 100, 3, 0, "Дадов прилог"), ("Само седни", 0, 6, 0, "Се одморив внатре")],
    "fuel": [("Полни резервоар", 1200, 0, 0, "Наполнив гориво"), ("Грицки и кафе", 100, 10, 0, "Купив грицки"), ("Миење кола", 200, 0, 0, "Ја измив колата"), ("Прашај за цена", 0, 0, 0, "Видов колку е бензин и се исплашив")],
    "money": [("Подигни 500", 0, 0, 500, "Подигнав пари"), ("Подигни 1000", 0, 0, 1000, "Подигнав повеќе пари"), ("Провери сметка", 0, 0, 100, "Ја проверив сметката"), ("Побарај кредит", 0, 0, 300, "Побарав кредит")],
    "market": [("Домати и пиперки", 120, 15, 0, "Купив зеленчук"), ("Сирење", 180, 20, 0, "Купив сирење"), ("Ајвар", 220, 18, 0, "Купив ајвар"), ("Пазари се", 0, 5, 40, "Се пазарев и испадна добро")],
    "police": [("Пријави кражба", 0, 0, 0, "Пријавив нешто"), ("Прашај за пат", 0, 0, 0, "Прашав за пат"), ("Плати казна", 300, 0, 0, "Платив казна"), ("Донеси погача", 60, 0, 0, "Им однесов погача")],
    "public": [("Земи број", 0, 0, 0, "Чекав на шалтер"), ("Купи марки", 30, 0, 0, "Купив марки"), ("Печат", 50, 0, 0, "Добив печат"), ("Дојдете утре", 0, 0, 0, "Ми рекоа дојдете утре")],
    "culture": [("Билет", 150, 10, 0, "Гледав претстава"), ("Музеј", 100, 6, 0, "Разгледав музеј"), ("Сувенир", 200, 0, 0, "Купив сувенир"), ("Само погледни", 0, 2, 0, "Погледнав и излегов")],
    "night": [("Пиј на шанк", 250, 15, 0, "Пиев на шанк"), ("Танцувај", 0, 8, 0, "Танцував цела песна"), ("Дај бакшиш", 100, 0, 0, "Оставив бакшиш"), ("Играј лото", 100, 0, 250, "Играв лото")],
    "transport": [("Купи карта", 40, 0, 0, "Купив автобуска карта"), ("Прашај за ред", 0, 0, 0, "Прашав за возен ред"), ("Купи вода", 50, 8, 0, "Купив вода"), ("Седи и чекај", 0, 5, 0, "Чекав автобус")],
    "shop": [("Купи нешто мало", 100, 8, 0, "Купив нешто мало"), ("Купи облека", 400, 5, 0, "Купив облека"), ("Дуќан-ловец", 0, 0, 60, "Најдов попуст и заработив"), ("Само гледај", 0, 0, 0, "Гледав излози")],
    "hotel": [("Рецепција", 0, 0, 0, "Прашав за соба"), ("Тераса-кафе", 150, 12, 0, "Испив кафе на лобито"), ("Бања", 500, 40, 0, "Се одморив во бања"), ("Бакшиш", 100, 0, 0, "Дадов бакшиш")],
    "sight": [("Слика", 0, 2, 0, "Ја разгледав знаменитоста"), ("Гулаби", 20, 3, 0, "Ги нахранив гулабите"), ("Сувенир", 150, 0, 0, "Купив сувенир"), ("Прочитај плоча", 0, 0, 0, "Прочитав за историјата")],
    "sport": [("Вежбај", 150, 20, 0, "Одвежбав"), ("Тушира", 50, 10, 0, "Се истушнав"), ("Протеин", 250, 15, 0, "Испив протеин"), ("Тренер", 400, 35, 0, "Имав тренер")],
    "play": [("Лулашка", 0, 6, 0, "Се лулав"), ("Тобоган", 0, 6, 0, "Се лизгав"), ("Клупа", 0, 4, 0, "Седнав на клупа"), ("Топка", 20, 5, 0, "Играв топка")],
}
DEFAULT = [("Влези", 0, 3, 0, "Влегов да видам"), ("Купи нешто", 80, 5, 0, "Купив нешто"), ("Прашај", 0, 0, 0, "Прашав нешто"), ("Остани малку", 0, 5, 0, "Се одморив малку")]
TITLES = {"cafe": "Кафуле", "food": "Ресторан", "school": "Школо", "health": "Здравство", "worship": "Црква / џамија", "fuel": "Бензинска",
          "money": "Банка", "market": "Пазар", "police": "Полиција", "public": "Јавна установа", "culture": "Култура", "night": "Ноќен клуб",
          "transport": "Станица", "shop": "Продавница", "hotel": "Хотел", "sight": "Знаменитост", "sport": "Спорт", "play": "Игралиште"}

# how each character ends the sentence (personality), picked at random
TAIL = {
    "kumplung": ["Е па добро, чичко.", "Не ми се лути.", "Фала му на Бога."], "maca": ["Дарлинг!", "Минич и штикла, сѐ е во ред.", "Ај, пеам за љубов."],
    "mile": ["Најдолгата рута, нели.", "Таксиметарот си тече.", "Странец да ми се најде."], "stojan": ["Студентски цени, молам.", "Штедам за бурек.", "Нема пари, ама има волја."],
    "influenser": ["Лајкајте и следете!", "Ова оди на сторис.", "Следбеници, гледате ли?"], "influenserka": ["Тоа е за сторито!", "Хаштаг благословена.", "Ова е толку естетски."],
    "tetkica": ["Бог да чува.", "Да не се разболиш.", "Ќе падне дожд, видов."], "baba": ["Пензијата уште не стигна.", "Ќе ве проколнам, ако не.", "Во мое време беше поевтино."],
    "dedo": ["Во мое време беше подобро.", "Сето ова е политика.", "Дај шамија, дожд иде."], "pandur": ["Само опомена.", "Тоа е по закон.", "Слушам техно додека работам."],
    "doktor": ["Како што и очекував.", "Пациентите ме чекаат.", "Богат сум, но скромен."], "mali": ["Брзо, пред мама да види.", "Дај уште едно!", "Јас сум голем веќе."],
    "radnik": ["Работам по 15 саати.", "Фала, шефе.", "Комбинезонот е прљав, ама срцето чисто."], "burek": ["Со малку фил, исто.", "Мирисам на маргарин.", "Ноќна смена, брате."],
    "boza": ["Без грутки, секако.", "Гласно и јасно!", "Бела капа, чиста совест."], "fitka": ["Калории, броиме!", "Слика за сторито, фитнес.", "Хеланките издржаа."],
    "bilder": ["Протеини, брат.", "Воспален сум, а тоа е добро.", "Кавасаки чека надвор."], "shmizla": ["Спонзор, каде си?", "Трепките се лажни, ама сјајот не е.", "Мастика и мир."],
    "palavko": ["Бегам пред да ме фатат!", "Колена скинати, дух чист.", "Ѕвонец, па трчање."], "srednoskolec": ["Не кажувај на татко.", "Нема да платам за автобус.", "Пушам, не од чија било причина."],
    "vojnik": ["Викенд-отсуство, слободен сум.", "Бара девојка, ако има.", "Подготвен за секој задача."], "navivac": ["Ајде Вардаре!", "Шалот е со мене.", "Пеам и на улица!"],
    "administratorka": ["Дојдете утре.", "Уште еден печат.", "Пауза за кафе од десет."], "nastavnica": ["Тишина, ве молам.", "Црвено пенкало е готово.", "Строг поглед, милост нема."],
}
GENERIC_TAIL = ["Ех, Скопје.", "Нема фрка.", "Тоа беше тоа."]


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
                popups.add(f"{lab} = {price} ден.", wk.x, wk.y, 2.8, 2.0, (255, 150, 140), 20)
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
                popups.add(line + (f"  (+{gain - price} ден.)" if gain > price else f"  (-{price} ден.)" if price else ""), px, py, 4.5, 3.4, col, 22)
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
        title = f"{self.cur[3]}  ·  {vt or TITLES.get(self.cur[2], 'Место')}"
        w, h = 470, 44 + 28 * len(menu)
        x, y = sw // 2 - w // 2, sh - h - 150
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.08, 6, rl.Color(10, 10, 14, 215))
        font.draw_text(title[:40], x + 14, y + 8, 22, rl.Color(250, 214, 80, 255))
        for i, (lab, price, heal, gain, _w) in enumerate(menu):
            ok = sim.money >= price
            col = rl.Color(235, 235, 235, 255) if ok else rl.Color(150, 150, 150, 255)
            font.draw_text(f"[{i + 1}] {lab}", x + 14, y + 40 + i * 28, 20, col)
            tag = (f"+{gain} ден." if gain and not price else f"-{price} ден." if price else "бесплатно")
            font.draw_text(tag, x + w - 120, y + 40 + i * 28, 20, rl.Color(130, 230, 140, 255) if ok else col)
