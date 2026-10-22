"""Vehicle and pedestrian catalogue: names, sizes, collision circles, spawn weights. Pure data (sim + renderer)."""

# per style: (y0 body bottom, belt, roof) defaults
_STYLE = {"hatch": (0.40, 0.95, 1.38), "sedan": (0.40, 0.98, 1.38), "taxi": (0.40, 0.98, 1.38), "mini": (0.38, 0.92, 1.36),
          "suv": (0.58, 1.10, 1.68), "van": (0.45, 1.00, 1.95), "pickup": (0.55, 1.10, 1.78), "bus": (0.50, 1.00, 3.10),
          "wagon": (0.40, 0.97, 1.42), "limo": (0.40, 0.98, 1.40), "truck": (0.55, 1.15, 3.0), "tractor": (0.55, 1.00, 2.5)}
BLACK, WHITE_, SILVER = (30, 30, 34), (236, 236, 240), (190, 192, 198)

# name, style, L, W, roof (None = style default), traffic weight, fixed colour (None = random paint), extra
_V = [
    ("Zastava Yugo", "hatch", 3.85, 1.60, None, 6, None, ""),
    ("Golf Dvojka", "hatch", 4.05, 1.68, 1.40, 7, None, ""),
    ("Kombi", "van", 4.50, 1.75, None, 3, None, ""),
    ("Lada Niva", "suv", 3.75, 1.68, None, 3, None, ""),
    ("Mercedes 190", "sedan", 4.40, 1.70, None, 5, None, ""),
    ("Taxi Zlatna Zolta", "taxi", 4.40, 1.70, None, 3, (238, 192, 28), ""),
    ("Gradski Avtobus", "bus", 9.60, 2.50, None, 1, (232, 232, 236), ""),
    ("Fico", "mini", 3.20, 1.40, None, 3, None, ""),
    ("Pikap Tovarnik", "pickup", 5.00, 1.80, None, 2, None, ""),
    # ---- 50 more
    ("Zastava 101 Skala", "hatch", 3.99, 1.62, None, 5, None, ""),
    ("Zastava Koral", "hatch", 3.70, 1.55, None, 4, None, ""),
    ("Lada Samara", "hatch", 4.00, 1.62, None, 4, None, ""),
    ("Lada 1500", "sedan", 4.10, 1.62, None, 3, None, ""),
    ("Moskvich 412", "sedan", 4.10, 1.55, None, 2, None, ""),
    ("Trabant 601", "mini", 3.55, 1.50, 1.45, 3, None, ""),
    ("Wartburg 353", "sedan", 4.20, 1.60, None, 2, None, ""),
    ("Skoda Octavia Karavan", "wagon", 4.60, 1.75, None, 4, None, ""),
    ("Pachuvka 2CV", "mini", 3.80, 1.50, 1.60, 2, None, ""),
    ("Renault 4 Katrca", "hatch", 3.70, 1.50, 1.55, 3, None, ""),
    ("Fiat 126 Peglica", "mini", 3.05, 1.38, None, 3, None, ""),
    ("Fiat Punto", "hatch", 3.85, 1.66, None, 4, None, ""),
    ("Fiat Uno", "hatch", 3.70, 1.55, None, 3, None, ""),
    ("Opel Kadett", "hatch", 4.00, 1.65, None, 4, None, ""),
    ("Opel Astra Karavan", "wagon", 4.50, 1.70, None, 3, None, ""),
    ("Audi 80 Bachok", "sedan", 4.50, 1.70, None, 3, None, ""),
    ("BMW E36 Bavarka", "sedan", 4.43, 1.70, None, 3, BLACK, "spoiler"),
    ("BMW X5 Chorbadzija", "suv", 4.70, 1.90, 1.75, 2, BLACK, ""),
    ("Mercedes 124 Taksist", "sedan", 4.70, 1.75, None, 3, (222, 214, 190), ""),
    ("Mercedes S Mafijash", "sedan", 5.20, 1.90, 1.45, 1, BLACK, ""),
    ("Mercedes G Politichar", "suv", 4.40, 1.80, 1.95, 1, BLACK, ""),
    ("Sprinter Gastarbajter", "van", 5.90, 2.00, 2.55, 2, None, "roofload"),
    ("Passat Dijaspora", "sedan", 4.60, 1.74, None, 4, None, "roofload"),
    ("Golf Trojka Gastarbajter", "hatch", 4.00, 1.70, None, 4, None, "roofload"),
    ("Caddy Dostava", "van", 4.40, 1.70, 1.85, 2, WHITE_, "logo"),
    ("Transporter Kombe", "van", 4.90, 1.90, 2.00, 2, None, ""),
    ("Renault Clio", "hatch", 3.80, 1.66, None, 4, None, ""),
    ("Toyota Corolla", "sedan", 4.40, 1.70, None, 4, None, ""),
    ("Land Cruiser Lovec", "suv", 4.80, 1.85, 1.85, 2, None, ""),
    ("Nissan Qashqai", "suv", 4.30, 1.80, 1.60, 3, None, ""),
    ("Dacia Duster", "suv", 4.30, 1.80, 1.68, 4, None, ""),
    ("Dacia Logan", "sedan", 4.35, 1.74, None, 4, None, ""),
    ("Kia Picanto", "mini", 3.60, 1.60, None, 3, None, ""),
    ("Tesla Elon", "sedan", 4.97, 1.96, 1.44, 1, WHITE_, ""),
    ("Hummer Patriot", "suv", 4.70, 2.20, 2.00, 1, (230, 190, 30), ""),
    ("Smart Sitnichka", "mini", 2.70, 1.55, 1.50, 2, None, ""),
    ("Cayenne od Germanija", "suv", 4.80, 1.95, 1.70, 1, SILVER, ""),
    ("Range Rover Ortak", "suv", 4.90, 1.95, 1.85, 1, (30, 56, 44), ""),
    ("Policiska Skoda", "sedan", 4.60, 1.75, None, 2, WHITE_, "police"),
    ("Brza Pomosh", "van", 5.60, 2.00, 2.55, 1, WHITE_, "ambulance"),
    ("Pozharna", "truck", 7.40, 2.50, 3.20, 1, (200, 30, 30), "fire"),
    ("Smetar Kamion", "truck", 7.20, 2.50, 3.20, 1, (40, 130, 70), "garbage"),
    ("Betonjerka", "truck", 7.50, 2.50, 3.40, 1, (230, 130, 30), "mixer"),
    ("Pajak Vlechna Sluzhba", "pickup", 5.60, 2.00, 1.90, 1, (240, 200, 30), "tow"),
    ("Burek Dostava", "van", 4.60, 1.80, 2.10, 2, (240, 200, 60), "burek"),
    ("Makedonska Posta", "van", 5.00, 1.95, 2.30, 1, (240, 200, 30), "post"),
    ("Traktor Belarus", "tractor", 4.00, 1.95, 2.60, 1, (50, 100, 170), ""),
    ("Svadbarska Limuzina", "limo", 6.60, 1.85, None, 1, WHITE_, "ribbons"),
    ("Avtobus Skopje-Ohrid", "bus", 12.0, 2.55, 3.40, 1, WHITE_, "coach"),
    ("Sladoled Kombe", "van", 4.30, 1.75, 2.10, 1, (240, 170, 200), "icecream"),
    # ---- round 7: second-hand imports from the west, 2000s-2010s, as Skopje knows them
    ("Golf Petka TDI", "hatch", 4.20, 1.76, None, 7, None, ""),
    ("Golf Shestka Uvezen", "hatch", 4.20, 1.78, None, 6, None, "spoiler"),
    ("Passat B5 Karavan", "wagon", 4.70, 1.74, None, 6, None, "roofload"),
    ("Passat B6 TDI", "sedan", 4.77, 1.82, None, 5, None, ""),
    ("Audi A4 Avant Shvajcarska", "wagon", 4.60, 1.77, None, 4, None, ""),
    ("Audi A6 Nemachka", "sedan", 4.92, 1.86, None, 3, BLACK, ""),
    ("BMW E46 Tjunirana", "sedan", 4.47, 1.74, None, 4, BLACK, "spoiler"),
    ("BMW E39 520d", "sedan", 4.78, 1.80, None, 3, SILVER, ""),
    ("Mercedes C Klasa W203", "sedan", 4.53, 1.73, None, 4, SILVER, ""),
    ("Mercedes E Klasa W211", "sedan", 4.82, 1.82, None, 3, BLACK, ""),
    ("Opel Astra G", "hatch", 4.11, 1.71, None, 5, None, ""),
    ("Opel Corsa C", "hatch", 3.82, 1.65, None, 5, None, ""),
    ("Opel Zafira Familijarna", "van", 4.32, 1.74, 1.68, 4, None, ""),
    ("Renault Megane Scenic", "van", 4.26, 1.75, 1.65, 4, None, ""),
    ("Peugeot 206", "hatch", 3.84, 1.65, None, 5, None, ""),
    ("Peugeot 307 SW", "wagon", 4.42, 1.76, None, 3, None, ""),
    ("Citroen Berlingo", "van", 4.14, 1.72, 1.80, 4, None, ""),
    ("Fiat Stilo", "hatch", 4.18, 1.76, None, 3, None, ""),
    ("Fiat Multipla", "van", 4.00, 1.87, 1.67, 2, (120, 170, 120), ""),
    ("Skoda Fabia", "hatch", 3.97, 1.65, None, 6, None, ""),
    ("Skoda Octavia Taksi", "taxi", 4.57, 1.77, None, 4, (238, 192, 28), ""),
    ("Seat Leon Kupra", "hatch", 4.32, 1.77, None, 3, (200, 30, 30), "spoiler"),
    ("Hyundai Getz", "hatch", 3.81, 1.67, None, 4, None, ""),
    ("Toyota Yaris", "hatch", 3.75, 1.66, None, 4, None, ""),
    ("Ford Focus Karavan", "wagon", 4.47, 1.84, None, 4, None, ""),
    ("Ford Transit Shverc", "van", 5.20, 1.97, 2.30, 2, WHITE_, "roofload"),
    ("Volvo V70 Dedov", "wagon", 4.71, 1.80, None, 2, SILVER, ""),
    ("Golf Chetvorka Bez Registracija", "hatch", 4.15, 1.73, None, 5, None, ""),
    ("JSP Dvokatnik", "bus", 10.8, 2.55, 4.30, 0, (200, 32, 36), "jsp"),
    ("JSP Zglobni", "bus", 12.0, 2.55, 3.10, 0, (200, 32, 36), "jsp"),
]
N = len(_V)
IDS = [v[0] for v in _V]
STYLE = [v[1] for v in _V]
DIMS = [(v[2], v[3], _STYLE[v[1]][0], _STYLE[v[1]][1], v[4] or _STYLE[v[1]][2]) for v in _V]   # L, W, y0, belt, roof
FIXED = [v[6] for v in _V]
EXTRA = [v[7] for v in _V]
BUS = 6
LARGE = [d[0] >= 6.4 for d in DIMS]                           # need a wide road
_SPEED = {"truck": 0.75, "tractor": 0.45, "bus": 0.8, "limo": 0.7}
SPEED = [_SPEED.get(s, 1.0) for s in STYLE]


def _circ(L, W):
    r = W / 2 + 0.05
    return (L / 2 - r + 0.1, r)


CIRC = {i: _circ(d[0], d[1]) for i, d in enumerate(DIMS)}
HALF_L = [d[0] / 2 + 0.25 for d in DIMS]                       # following distance / shadows
HALF_W = [d[1] / 2 + 0.1 for d in DIMS]
TRAFFIC_W = [v[5] for v in _V]
PARKED_KINDS = [i for i in range(N) if not LARGE[i] and STYLE[i] != "tractor" for _ in range(_V[i][5])]
N_COLORS = 16

# ---------------------------------------------------------------------------- road users (0-8 classic, 9 = you)
# name, speed multiplier, spawn weight, one-liners
# какво гледа играчот (внатрешните имена горе остануваат за табелите со перформанси)
MK_CAR = {
    "Zastava Yugo": "Застава Југо", "Golf Dvojka": "Голф Двојка", "Kombi": "Комби", "Lada Niva": "Лада Нива", "Mercedes 190": "Мерцедес 190",
    "Taxi Zlatna Zolta": "Такси „Златна жолта“", "Gradski Avtobus": "Градски автобус", "Fico": "Фичо", "Pikap Tovarnik": "Пикап товарник",
    "Zastava 101 Skala": "Застава 101 Скала", "Zastava Koral": "Застава Корал", "Lada Samara": "Лада Самара", "Lada 1500": "Лада 1500",
    "Moskvich 412": "Москвич 412", "Trabant 601": "Трабант 601", "Wartburg 353": "Вартбург 353", "Skoda Octavia Karavan": "Шкода Октавија Караван",
    "Pachuvka 2CV": "Ситроен 2CV", "Renault 4 Katrca": "Рено 4 „Катрца“", "Fiat 126 Peglica": "Фиат 126 „Пеглица“", "Fiat Punto": "Фиат Пунто",
    "Fiat Uno": "Фиат Уно", "Opel Kadett": "Опел Кадет", "Opel Astra Karavan": "Опел Астра Караван", "Audi 80 Bachok": "Ауди 80",
    "BMW E36 Bavarka": "БМВ Е36 „Баварка“", "BMW X5 Chorbadzija": "БМВ Х5 „Чорбаџија“", "Mercedes 124 Taksist": "Мерцедес 124 „Таксист“",
    "Mercedes S Mafijash": "Мерцедес S „Мафијаш“", "Mercedes G Politichar": "Мерцедес G „Политичар“", "Sprinter Gastarbajter": "Спринтер „Гастарбајтер“",
    "Passat Dijaspora": "Пасат „Дијаспора“", "Golf Trojka Gastarbajter": "Голф Тројка „Гастарбајтер“", "Caddy Dostava": "Кади „Достава“",
    "Transporter Kombe": "Транспортер комбе", "Renault Clio": "Рено Клио", "Toyota Corolla": "Тојота Королa", "Land Cruiser Lovec": "Ленд Крузер „Ловец“",
    "Nissan Qashqai": "Нисан Кашкај", "Dacia Duster": "Дачиа Дастер", "Dacia Logan": "Дачиа Логан", "Kia Picanto": "Киа Пиканто",
    "Tesla Elon": "Тесла „Илон“", "Hummer Patriot": "Хамер „Патриот“", "Smart Sitnichka": "Смарт „Ситничка“", "Cayenne od Germanija": "Кајен од Германија",
    "Range Rover Ortak": "Ренџ Ровер „Ортак“", "Policiska Skoda": "Полициско возило", "Brza Pomosh": "Брза помош", "Pozharna": "Пожарна",
    "Smetar Kamion": "Комунален камион", "Betonjerka": "Бетоњерка", "Pajak Vlechna Sluzhba": "Влечна служба", "Burek Dostava": "Бурек достава",
    "Makedonska Posta": "Македонска пошта", "Traktor Belarus": "Трактор Беларус", "Svadbarska Limuzina": "Свадбарска лимузина",
    "Avtobus Skopje-Ohrid": "Автобус Скопје–Охрид", "Sladoled Kombe": "Сладолед комбе",
    "Golf Petka TDI": "Голф Петка TDI „Само 180 илјади“", "Golf Shestka Uvezen": "Голф Шестка „Увезен, од доктор“",
    "Passat B5 Karavan": "Пасат Б5 Караван „Тркалото на семејството“", "Passat B6 TDI": "Пасат Б6 „Со германски таблички“",
    "Audi A4 Avant Shvajcarska": "Ауди А4 Авант „Од Швајцарија, не е возен“", "Audi A6 Nemachka": "Ауди А6 „Германецот ја возеше само недела“",
    "BMW E46 Tjunirana": "БМВ Е46 „Тјунирана, со ксенони“", "BMW E39 520d": "БМВ Е39 „Дизелче, троши 5 литри, тврди газдата“",
    "Mercedes C Klasa W203": "Мерцедес C „Увоз од Италија“", "Mercedes E Klasa W211": "Мерцедес E „Кумот ја донесе“",
    "Opel Astra G": "Опел Астра G „Со нова лимарија“", "Opel Corsa C": "Опел Корса „Прва кола на ќерката“",
    "Opel Zafira Familijarna": "Опел Зафира „Седум седишта, пет деца“", "Renault Megane Scenic": "Рено Сценик „Чека делови од Бугарија“",
    "Peugeot 206": "Пежо 206 „Светлото за мотор секогаш свети“", "Peugeot 307 SW": "Пежо 307 Караван",
    "Citroen Berlingo": "Ситроен Берлинго „Мајстор на повик“", "Fiat Stilo": "Фиат Стило „Ретка птица“",
    "Fiat Multipla": "Фиат Мултипла „Најгрдата, најверната“", "Skoda Fabia": "Шкода Фабија „Од баба во Германија“",
    "Skoda Octavia Taksi": "Шкода Октавија Такси", "Seat Leon Kupra": "Сеат Леон „Купра, со дупнат ауспух“",
    "Hyundai Getz": "Хјундаи Гец „Не се расипува, не се продава“", "Toyota Yaris": "Тојота Јарис",
    "Ford Focus Karavan": "Форд Фокус Караван „Километражата е вратена“", "Ford Transit Shverc": "Форд Транзит „Шверц линија Скопје–Минхен“",
    "Volvo V70 Dedov": "Волво V70 „Дедото на сите кола“", "Golf Chetvorka Bez Registracija": "Голф Четворка „Регистрацијата истече лани“",
    "JSP Dvokatnik": "ЈСП двокатен автобус", "JSP Zglobni": "ЈСП зглобен автобус",
}
MK_PED = {
    "Chichko": "Чичко", "Baba": "Баба", "Biznismen": "Бизнисмен", "Student": "Студент", "Navivach": "Навивач", "Dete": "Дете", "Rabotnik": "Работник",
    "Devojka": "Девојка", "Buregdzija": "Бурегџија", "Ti": "Ти", "Pandur": "Пандур", "Parkingar": "Паркинг-чувар", "Pop": "Поп", "Hipster": "Хипстер",
    "Influenser": "Инфлуенсер", "Telefonash": "Со телефон", "Penzioner": "Пензионер", "Kafana Chicko": "Кафеански чичко", "Turist": "Турист",
    "Gastarbajter": "Гастарбајтер", "Majka so Kolichka": "Мајка со количка", "Partiski Aktivist": "Партиски активист", "Advokat": "Адвокат",
    "Teretana Brat": "Теретанец", "Kiosk Chika": "Продавач од киоск", "Ribar": "Рибар", "Golabar": "Гулабар", "Komunalec": "Комунален инспектор",
    "Nevesta": "Невеста", "Dostavuvach": "Доставувач", "Velosipedist": "Велосипедист", "Dedo na Kolo": "Дедо на велосипед", "Moped Tomos": "Мопед Томос",
    "Glovo Skuter": "Скутер за достава", "Trotinet Dete": "Дете на тротинет", "E-Trotinet Hipster": "Хипстер на тротинет", "Skejter": "Скејтер",
    "Rolerash": "Ролер", "Kocija": "Кочијаш", "Jogger": "Џогер",
}
MK_LINES = {
    "Chichko": ["Ех, кафе би ми дошло добро.", "Пазарот е скап, брате."],
    "Baba": ["Внук ми не ја носи кесата!", "Не во моево време, бре!", "Ајварот не се купува, се прави!"],
    "Biznismen": ["Имам состанок, бре!", "Времето е пари.", "Каде ми е такситото?"],
    "Student": ["Утре имам испит...", "Нема Wi-Fi, брате.", "Ајде на кафе пред предавање."],
    "Navivach": ["ВАРДАР! ВАРДАР!", "Ајде, Вардаре!", "Судијата е купен!"],
    "Dete": ["Мамо, бурек!", "Ајде да трчаме!", "Гледај, кола!"],
    "Rabotnik": ["Пауза е до десет.", "Оваа дупка ја копав вчера.", "Не ми смета, работам!"],
    "Devojka": ["Ајде бре, доцнам.", "Каде е ова кафе?", "Што си толку брз, бре!"],
    "Buregdzija": ["Бурек врел! Врел бурек!", "Имам и со сирење, и со месо!", "Јогурт бесплатно до десет!"],
    "Pandur": ["Документи, бре!", "Паркирањето е забрането. Освен за мене.", "Нема казна... ако има бурек."],
    "Parkingar": ["Дај 50 денари, бре!", "Ова е мое место, ортак.", "Има место. За 200."],
    "Pop": ["Бог да прости. Дај донација.", "Амин. Паркингот е грев.", "Светецот ти помага, не GPS."],
    "Hipster": ["Ова кафе е премногу мејнстрим.", "Морам да имам Wi-Fi.", "Брате, ова е винтиџ."],
    "Influenser": ["Ајде, лајкни бре!", "Денешна дестинација: Плоштад!", "Не гледај, снимам!"],
    "Telefonash": ["Секунда, пишувам...", "Гледам, гледам... (не гледам).", "Ај, не ме туркај, бре!"],
    "Penzioner": ["Во моево време...", "Ова не е Југославија.", "Пензијата не стигнува ни за кафе."],
    "Kafana Chicko": ["Ортак, седни на кафе.", "Ракија пред ручек е здравје.", "Сè време имаме, бре."],
    "Turist": ["Каде е Скопје 2014?!", "И ова е статуа?", "Зошто толку многу статуи?"],
    "Gastarbajter": ["Во Германија е поинаку.", "Овде сè е евтино!", "Мерцедесот остана дома."],
    "Majka so Kolichka": ["Не вози брзо, има бебе!", "Полека, бре, лудак!", "Тротоарот не е патиште!"],
    "Partiski Aktivist": ["Гласај за нас! Има бурек!", "Ветуваме сè. Сè!", "Мостот ќе го изградиме... пак."],
    "Advokat": ["Имам врска.", "Ќе те тужам, бре!", "Без адвокат не зборувам."],
    "Teretana Brat": ["Сила, бре!", "Протеинот е живот.", "Не е дебело, е маса."],
    "Kiosk Chika": ["Цигари, весници, лото!", "Добитна комбинација, само кај мене!", "Нема кусур, бре."],
    "Ribar": ["Тука има риба... тврдат.", "Вардар е чист. Скоро.", "Не ми ги плаши рибите!"],
    "Golabar": ["Гу-гу, мили мои.", "Гулабите ги знаат сите.", "Плоштадот е нивни."],
    "Komunalec": ["Казна! 5000 денари.", "Имате ли дозвола за ова дишење?", "Пријави, ќе гледаме."],
    "Nevesta": ["Здраво за младоженецот!", "Каде е кумот, бре?!", "Фотограф, брзо!"],
    "Dostavuvach": ["Достава за 30 минути, гарантирано!", "Каде е влезот? Пак.", "Бурекот е студен, грев мој."],
    "Velosipedist": ["Ѕвонче, бре! Ѕвонче!", "Има ли велоалеја? Нема.", "Ајде, на тротоар, бре!"],
    "Dedo na Kolo": ["Овој велосипед е од 1974.", "Не ми треба бензин, бре.", "Ѕвонче нема, има глас!"],
    "Moped Tomos": ["Без кацига, без фрка!", "Томос живее вечно!", "Брм-брм, дај пат!"],
    "Glovo Skuter": ["Нарачка на Плоштад, брзо!", "Пет ѕвезди или ништо!", "Бурекот е топол... беше."],
    "Trotinet Dete": ["Возам брзо како тато!", "Мамо, гледај, без раце!", "Ајде, стигни ме!"],
    "E-Trotinet Hipster": ["Еко-мобилност, брате.", "Без паркирање, без фрка.", "Батеријата ми е 3%."],
    "Skejter": ["Кикфлип! (скоро)", "Ова е парк, не е тротоар.", "Внимавај, паѓам!"],
    "Rolerash": ["Да ги имав сопирачките...", "Ај, пази се, немам стоп!", "Ретро е крал."],
    "Kocija": ["Ајде, Шаро, ајде!", "Коњот не троши гориво.", "Свежа зелка, свежа!"],
    "Jogger": ["Петти круг, петти!", "Не зборувај, трчам.", "Овој воздух е... загаден."],
}


NAMES = [MK_CAR.get(v[0], v[0]) for v in _V]                          # what the player reads

_P = [
    ("Chichko", 1.0, 3, ["Eh, kafe bi mi dobro dojde.", "Pazar e skap, brate."]),
    ("Baba", 0.8, 3, ["Vnuk mi ne ja nosi kesata!", "Ne vo moe vreme, bre!", "Ajvarot ne se kupuva, se pravi!"]),
    ("Biznismen", 1.2, 3, ["Imam sostanok, bre!", "Vreme e pari.", "Kade mi e taksito?"]),
    ("Student", 1.1, 3, ["Imam ispit utre...", "Nema wifi, brate.", "Ajde na kafe pred predavanje."]),
    ("Navivach", 1.1, 3, ["VARDAR! VARDAR!", "Ajde Vardare!", "Sudijata e kupena!"]),
    ("Dete", 1.2, 2, ["Mamo, burek!", "Ajde da trcame!", "Gledaj, kola!"]),
    ("Rabotnik", 1.0, 3, ["Pauza e do deset.", "Ovaa dupka ja kopav juche.", "Ne mi smetaj, rabotam!"]),
    ("Devojka", 1.1, 3, ["Ajde bre, zakasnuvam.", "Kade e ova kafe?", "Sho si taka brz, bre!"]),
    ("Buregdzija", 1.0, 2, ["Burek vreli! Vreli burek!", "Imam i so sirenje, i so meso!", "Jogurt gratis do desette!"]),
    ("Ti", 1.0, 0, []),
    # ---- 30 more
    ("Pandur", 0.9, 1.5, ["Dokumenti, bre!", "Parkiranje zabraneto. Osven za mene.", "Nema kazna... ako ima burek."]),
    ("Parkingar", 1.0, 1.5, ["Daj 50 denari, bre!", "Ova e moe mesto, ortak.", "Ima mesto. Za 200."]),
    ("Pop", 0.9, 1, ["Bog da prosti. Daj donacija.", "Amin. Parkingot e greshen.", "Svetec ti pomaga, ne GPS."]),
    ("Hipster", 1.0, 1.5, ["Ova kafe e premnogu mainstream.", "Moram da imam wifi.", "Brate, ova e vintage."]),
    ("Influenser", 1.0, 1.5, ["Ajde lajkni bre!", "Segashen sted: Plostad! #blessed", "Ne gledaj, snimam!"]),
    ("Telefonash", 0.6, 2, ["Sekunda, pisham...", "Gledam, gledam... (ne gledam).", "Ae ne me tepaj, bre!"]),
    ("Penzioner", 0.6, 2, ["Vo moe vreme...", "Ova ne e Jugoslavija.", "Penzijata ne dostiga ni za kafe."]),
    ("Kafana Chicko", 0.8, 1.5, ["Ortak, sedni na kafe.", "Rakija pred rucek e zdravje.", "Sé vreme imame, bre."]),
    ("Turist", 0.9, 1.5, ["Where is Skopje 2014?!", "Is this a statue too?", "Why so many statues?"]),
    ("Gastarbajter", 0.8, 1.5, ["Vo Germanija e poinaku.", "Ovde sé e evtino!", "Mercedes ostana doma."]),
    ("Majka so Kolichka", 0.9, 1.5, ["Ne vozi brzo, ima bebe!", "Sporo, bre ludak!", "Trotoarot ne e patishte!"]),
    ("Partiski Aktivist", 1.0, 1, ["Glasaj za nas! Ima burek!", "Obecuvame sé. Sé!", "Mostot ke go gradime... pak."]),
    ("Advokat", 1.1, 1, ["Imam vrska.", "Ke te tozham, bre!", "Bez advokat ne zboruvam."]),
    ("Teretana Brat", 1.0, 1.5, ["Sila bre!", "Protein e zivot.", "Ne e debelo, e masa."]),
    ("Kiosk Chika", 0.9, 1.5, ["Cigari, vesti, loto!", "Dobitna kombinacija, samo kaj mene!", "Nema kusur, bre."]),
    ("Ribar", 0.8, 1, ["Ovde ima riba... tvrdi.", "Vardar e cista. Skoro.", "Ne mi gi plasi ribite!"]),
    ("Golabar", 0.7, 1, ["Gu-gu, mili moi.", "Golabite gi znaat site.", "Plostad e nivni."]),
    ("Komunalec", 1.0, 1, ["Kazna! 5000 denari.", "Imate li dozvola za ova disenje?", "Prijavi, ke gledame."]),
    ("Nevesta", 0.8, 0.8, ["Zdravo za mladozhenecot!", "Kade e kumot, bre?!", "Fotograf, brzo!"]),
    ("Dostavuvach", 1.6, 1.5, ["Dostava za 30 minuti, garantirano!", "Kade e ulazot? Pak.", "Burek studen, gresh moj."]),
    ("Velosipedist", 4.0, 1.2, ["Zvonche, bre! Zvonche!", "Ima li veloaleja? Nema.", "Ajde, lug, na trotoar!"]),
    ("Dedo na Kolo", 2.2, 1.2, ["Ova kolo e od 1974.", "Ne mi treba benzin, bre.", "Dzvonce nema, ima glas!"]),
    ("Moped Tomos", 5.0, 1.0, ["Bez kaciga, bez frka!", "Tomos zhivee veke!", "Brm brm, daj pat!"]),
    ("Glovo Skuter", 5.4, 1.2, ["Narachka na Plostad, brzo!", "Pet zvezdi ili nishto!", "Burek e topol... bilo."]),
    ("Trotinet Dete", 2.8, 1.0, ["Vozam brzo kako tatko!", "Mamo, gledaj, bez race!", "Ajde, trkaj me!"]),
    ("E-Trotinet Hipster", 4.5, 1.0, ["Eko-mobilnost, brate.", "Bez parkiranje, bez frka.", "Baterijata mi e 3%."]),
    ("Skejter", 2.8, 1.0, ["Kickflip! (skoro)", "Ova e park, ne trotoar.", "Pazi, padnuvam!"]),
    ("Rolerash", 3.6, 1.0, ["Ako gi imav kocnicite...", "Ae pazi se, nemam stop!", "Retro e kral."]),
    ("Kocija", 1.8, 0.6, ["Hajde, Sharo, ajde!", "Konj ne troshi gorivo.", "Sveze zelka, sveze!"]),
    ("Jogger", 3.2, 1.2, ["Petti krug, petti!", "Ne zboruvaj, trcam.", "Ovoj vozduh e ... zagaden."]),
]
PED_IDS = [p[0] for p in _P]                                      # internal keys (models, fight table)
PED_NAMES = [MK_PED.get(p[0], p[0]) for p in _P]                    # what the player reads
PED_SPEED = [p[1] for p in _P]
PED_W = [p[2] for p in _P]
PED_LINES = {i: MK_LINES.get(p[0], []) for i, p in enumerate(_P)}
PED_COUNT = len(_P)
PLAYER = 9
RIDERS = {"Velosipedist", "Dedo na Kolo", "Moped Tomos", "Glovo Skuter", "Trotinet Dete", "E-Trotinet Hipster", "Skejter",
          "Rolerash", "Kocija"}
PED_ARCH_N = PED_COUNT                                          # kept for compatibility
WALKERS = [i for i in range(PED_COUNT) if i != PLAYER and PED_IDS[i] not in RIDERS]

# ---------------------------------------------------------------------------- handling: (top speed m/s, accel m/s2, steering, grip, mass)
_PERF_STYLE = {"hatch": (35, 10.5, 0.68, 9.5, 1.0), "sedan": (40, 12.0, 0.62, 9.5, 1.1), "taxi": (38, 11.0, 0.62, 9.5, 1.1),
               "mini": (28, 8.0, 0.75, 9.0, 0.7), "suv": (36, 10.0, 0.56, 8.5, 1.5), "van": (31, 8.0, 0.62, 8.5, 1.6),
               "pickup": (33, 9.0, 0.60, 8.5, 1.5), "bus": (24, 4.5, 0.66, 8.0, 5.0), "wagon": (36, 10.5, 0.60, 9.5, 1.2),
               "limo": (34, 8.0, 0.58, 8.5, 1.8), "truck": (26, 5.5, 0.62, 8.0, 4.0), "tractor": (11, 3.0, 0.50, 7.5, 2.5)}
_PERF_NAME = {
    "Zastava Yugo": (29, 7.5), "Golf Dvojka": (37, 11), "Mercedes 190": (44, 13), "Fico": (24, 6, 0.80), "Zastava 101 Skala": (32, 9),
    "Zastava Koral": (30, 8.5), "Lada Samara": (33, 9), "Lada 1500": (32, 8.5), "Moskvich 412": (29, 7), "Trabant 601": (25, 5.5),
    "Wartburg 353": (31, 7), "Pachuvka 2CV": (24, 4.5, 0.7), "Renault 4 Katrca": (27, 6), "Fiat 126 Peglica": (22, 4.5, 0.8),
    "Golf Trojka Gastarbajter": (41, 12.5), "Passat Dijaspora": (42, 12), "Audi 80 Bachok": (42, 12), "BMW E36 Bavarka": (50, 17, 0.70, 11),
    "BMW X5 Chorbadzija": (52, 15), "Mercedes 124 Taksist": (41, 11), "Mercedes S Mafijash": (52, 14), "Mercedes G Politichar": (40, 10, 0.5),
    "Tesla Elon": (58, 24, 0.66, 11), "Hummer Patriot": (38, 9, 0.45), "Cayenne od Germanija": (55, 18, 0.64, 11),
    "Range Rover Ortak": (46, 12), "Policiska Skoda": (48, 16, 0.66, 10.5), "Brza Pomosh": (40, 11), "Smart Sitnichka": (27, 7, 0.9),
    "Lada Niva": (32, 9, 0.6, 10), "Land Cruiser Lovec": (40, 10), "Pajak Vlechna Sluzhba": (34, 9),
}
PERF = []
for _i, _v in enumerate(_V):
    _b = list(_PERF_STYLE[_v[1]])
    _o = _PERF_NAME.get(_v[0])
    if _o:
        for _k, _x in enumerate(_o):
            _b[_k] = _x
    PERF.append(tuple(_b))

# ---------------------------------------------------------------------------- fighting: (hit points, chance to fight back, punch damage)
_FIGHT_NAME = {"Chichko": (45, 0.45, 7), "Baba": (28, 0.2, 5), "Biznismen": (40, 0.3, 6), "Student": (38, 0.35, 6), "Navivach": (60, 0.9, 9),
               "Dete": (16, 0.0, 2), "Rabotnik": (60, 0.6, 9), "Devojka": (34, 0.3, 5), "Buregdzija": (50, 0.5, 7),
               "Pandur": (75, 0.85, 10), "Parkingar": (50, 0.6, 7), "Pop": (45, 0.15, 5), "Hipster": (35, 0.2, 5), "Influenser": (32, 0.1, 4),
               "Telefonash": (36, 0.1, 4), "Penzioner": (30, 0.5, 6), "Kafana Chicko": (55, 0.55, 8), "Turist": (38, 0.1, 4),
               "Gastarbajter": (52, 0.6, 8), "Majka so Kolichka": (36, 0.2, 5), "Partiski Aktivist": (42, 0.4, 6), "Advokat": (40, 0.15, 5),
               "Teretana Brat": (100, 0.95, 14), "Kiosk Chika": (38, 0.5, 6), "Ribar": (42, 0.4, 6), "Golabar": (26, 0.1, 4),
               "Komunalec": (46, 0.35, 6), "Nevesta": (32, 0.3, 5), "Dostavuvach": (40, 0.2, 5), "Jogger": (40, 0.2, 5)}
FIGHT = [_FIGHT_NAME.get(n, (30, 0.0, 3)) for n in PED_IDS]       # riders and the player fall back to the default
KIOSK_MENU = [("Бурек со јогурт", 70, 30), ("Тулумба", 40, 15), ("Ќебапи", 130, 50), ("Сендвич со ајвар", 90, 35)]


# ---------------------------------------------------------------- sound profiles (see audio.py)
_ENGINE = {}
for _i in (6, 8, 30, 33, 34, 37, 48, 52, 53, 54, 57, 58):
    _ENGINE[_i] = "engine_diesel"
for _i in (49, 50, 51, 55):
    _ENGINE[_i] = "engine_truck"
for _i in (25, 26, 28, 29, 43, 45, 46):
    _ENGINE[_i] = "engine_v8"
for _i in (0, 7, 9, 10, 14, 15, 17, 18, 19, 41, 44):
    _ENGINE[_i] = "engine_small"
_ENGINE[42] = "engine_ev"
ENGINE_SOUND = [_ENGINE.get(i, "engine_i4") for i in range(N)]
_HORN = {56: "horn_jingle", 58: "horn_jingle"}
for _i in (6, 49, 50, 51, 55, 57, 30, 34):
    _HORN[_i] = "horn_truck"
for _i in (7, 14, 19, 41, 44, 0, 17):
    _HORN[_i] = "horn_small"
HORN_SOUND = [_HORN.get(i, "horn") for i in range(N)]
SIREN_SOUND = {47: "siren_police", 48: "siren_amb", 49: "siren_fire"}
