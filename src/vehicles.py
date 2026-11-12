"""Vehicle and pedestrian catalogue: names, sizes, collision circles, spawn weights. Pure data (sim + renderer)."""

# per style: (y0 body bottom, belt, roof) defaults
from texts import TXT
_STYLE = {"hatch": (0.40, 0.95, 1.44), "sedan": (0.40, 0.98, 1.45), "taxi": (0.40, 0.98, 1.45), "mini": (0.38, 0.92, 1.36),
          "suv": (0.58, 1.10, 1.68), "van": (0.45, 1.00, 1.95), "pickup": (0.55, 1.10, 1.78), "bus": (0.50, 1.00, 3.10),
          "bike": (0.0, 0.55, 1.05), "wagon": (0.40, 0.97, 1.48), "limo": (0.40, 0.98, 1.40), "truck": (0.55, 1.15, 3.0), "tractor": (0.55, 1.00, 2.5)}
BLACK, WHITE_, SILVER = (30, 30, 34), (236, 236, 240), (190, 192, 198)

# name, style, L, W, roof (None = style default), traffic weight, fixed colour (None = random paint), extra
_V = [
    ("Zastava Yugo", "hatch", 3.85, 1.67, 1.38, 6, None, ""),
    ("Golf Dvojka", "hatch", 4.05, 1.83, 1.40, 7, None, ""),
    ("Kombi", "van", 4.50, 1.90, None, 3, None, ""),
    ("Lada Niva", "suv", 3.75, 1.83, 1.64, 3, None, ""),
    ("Mercedes 190", "sedan", 4.40, 1.85, 1.38, 5, None, ""),
    ("Taxi Zlatna Zolta", "taxi", 4.40, 1.85, None, 3, (238, 192, 28), ""),
    ("Gradski Avtobus", "bus", 9.60, 2.40, None, 1, (232, 232, 236), ""),
    ("Fico", "mini", 3.20, 1.75, 1.36, 3, None, ""),
    ("Pikap Tovarnik", "pickup", 5.00, 1.95, None, 2, None, ""),
    # ---- 50 more
    ("Zastava 101 Skala", "hatch", 3.99, 1.77, 1.4, 5, None, ""),
    ("Zastava Koral", "hatch", 3.70, 1.67, 1.38, 4, None, ""),
    ("Lada Samara", "hatch", 4.00, 1.77, 1.4, 4, None, ""),
    ("Lada 1500", "sedan", 4.10, 1.77, 1.4, 3, None, ""),
    ("Moskvich 412", "sedan", 4.10, 1.75, 1.45, 2, None, ""),
    ("Trabant 601", "mini", 3.55, 1.75, 1.45, 3, None, ""),
    ("Wartburg 353", "sedan", 4.20, 1.75, 1.47, 2, None, ""),
    ("Skoda Octavia Karavan", "wagon", 4.60, 1.90, 1.46, 4, None, ""),
    ("Pachuvka 2CV", "mini", 3.80, 1.75, 1.60, 2, None, ""),
    ("Renault 4 Katrca", "hatch", 3.70, 1.75, 1.55, 3, None, ""),
    ("Fiat 126 Peglica", "mini", 3.05, 1.75, 1.34, 3, None, ""),
    ("Fiat Punto", "hatch", 3.85, 1.81, 1.48, 4, None, ""),
    ("Fiat Uno", "hatch", 3.70, 1.75, 1.42, 3, None, ""),
    ("Opel Kadett", "hatch", 4.00, 1.80, 1.4, 4, None, ""),
    ("Opel Astra Karavan", "wagon", 4.50, 1.85, 1.5, 3, None, ""),
    ("Audi 80 Bachok", "sedan", 4.50, 1.85, 1.4, 3, None, ""),
    ("BMW E36 Bavarka", "sedan", 4.43, 1.85, 1.37, 3, BLACK, "spoiler"),
    ("BMW X5 Chorbadzija", "suv", 4.70, 2.00, 1.75, 2, BLACK, ""),
    ("Mercedes 124 Taksist", "sedan", 4.70, 1.90, None, 3, (222, 214, 190), ""),
    ("Mercedes S Mafijash", "sedan", 5.20, 2.00, 1.45, 1, BLACK, ""),
    ("Mercedes G Politichar", "suv", 4.40, 1.95, 1.95, 1, BLACK, ""),
    ("Sprinter Gastarbajter", "van", 5.90, 2.00, 2.55, 2, None, "roofload"),
    ("Passat Dijaspora", "sedan", 4.60, 1.89, 1.43, 4, None, "roofload"),
    ("Golf Trojka Gastarbajter", "hatch", 4.00, 1.85, 1.42, 4, None, "roofload"),
    ("Caddy Dostava", "van", 4.40, 1.85, 1.85, 2, WHITE_, "logo"),
    ("Transporter Kombe", "van", 4.90, 2.00, 2.00, 2, None, ""),
    ("Renault Clio", "hatch", 3.80, 1.81, 1.42, 4, None, ""),
    ("Toyota Corolla", "sedan", 4.40, 1.85, None, 4, None, ""),
    ("Land Cruiser Lovec", "suv", 4.80, 2.00, 1.85, 2, None, ""),
    ("Nissan Qashqai", "suv", 4.30, 1.95, 1.60, 3, None, ""),
    ("Dacia Duster", "suv", 4.30, 1.95, 1.68, 4, None, ""),
    ("Dacia Logan", "sedan", 4.35, 1.89, 1.53, 4, None, ""),
    ("Kia Picanto", "mini", 3.60, 1.75, 1.48, 3, None, ""),
    ("Tesla Elon", "sedan", 4.97, 2.00, 1.44, 1, WHITE_, ""),
    ("Hummer Patriot", "suv", 4.70, 2.00, 2.00, 1, (230, 190, 30), ""),
    ("Smart Sitnichka", "mini", 2.70, 1.75, 1.50, 2, None, ""),
    ("Cayenne od Germanija", "suv", 4.80, 2.00, 1.70, 1, SILVER, ""),
    ("Range Rover Ortak", "suv", 4.90, 2.00, 1.85, 1, (30, 56, 44), ""),
    ("Policiska Skoda", "sedan", 4.60, 1.90, None, 2, WHITE_, "police"),
    ("Brza Pomosh", "van", 5.60, 2.00, 2.55, 1, WHITE_, "ambulance"),
    ("Pozharna", "truck", 7.40, 2.40, 3.20, 1, (200, 30, 30), "fire"),
    ("Smetar Kamion", "truck", 7.20, 2.40, 3.20, 1, (40, 130, 70), "garbage"),
    ("Betonjerka", "truck", 7.50, 2.40, 3.40, 1, (230, 130, 30), "mixer"),
    ("Pajak Vlechna Sluzhba", "pickup", 5.60, 2.00, 1.90, 1, (240, 200, 30), "tow"),
    ("Burek Dostava", "van", 4.60, 1.95, 2.10, 2, (240, 200, 60), "burek"),
    ("Makedonska Posta", "van", 5.00, 2.00, 2.30, 1, (240, 200, 30), "post"),
    ("Traktor Belarus", "tractor", 4.00, 1.95, 2.60, 1, (50, 100, 170), ""),
    ("Svadbarska Limuzina", "limo", 6.60, 2.00, None, 1, WHITE_, "ribbons"),
    ("Avtobus Skopje-Ohrid", "bus", 12.0, 2.40, 3.40, 1, WHITE_, "coach"),
    ("Sladoled Kombe", "van", 4.30, 1.90, 2.10, 1, (240, 170, 200), "icecream"),
    # ---- round 7: second-hand imports from the west, 2000s-2010s, as Skopje knows them
    ("Golf Petka TDI", "hatch", 4.20, 1.91, None, 7, None, ""),
    ("Golf Shestka Uvezen", "hatch", 4.20, 1.93, None, 6, None, "spoiler"),
    ("Passat B5 Karavan", "wagon", 4.70, 1.89, None, 6, None, "roofload"),
    ("Passat B6 TDI", "sedan", 4.77, 1.97, None, 5, None, ""),
    ("Audi A4 Avant Shvajcarska", "wagon", 4.60, 1.92, None, 4, None, ""),
    ("Audi A6 Nemachka", "sedan", 4.92, 2.00, None, 3, BLACK, ""),
    ("BMW E46 Tjunirana", "sedan", 4.47, 1.89, 1.42, 4, BLACK, "spoiler"),
    ("BMW E39 520d", "sedan", 4.78, 1.95, None, 3, SILVER, ""),
    ("Mercedes C Klasa W203", "sedan", 4.53, 1.88, None, 4, SILVER, ""),
    ("Mercedes E Klasa W211", "sedan", 4.82, 1.97, None, 3, BLACK, ""),
    ("Opel Astra G", "hatch", 4.11, 1.86, None, 5, None, ""),
    ("Opel Corsa C", "hatch", 3.82, 1.80, None, 5, None, ""),
    ("Opel Zafira Familijarna", "van", 4.32, 1.89, 1.68, 4, None, ""),
    ("Renault Megane Scenic", "van", 4.26, 1.90, 1.65, 4, None, ""),
    ("Peugeot 206", "hatch", 3.84, 1.80, None, 5, None, ""),
    ("Peugeot 307 SW", "wagon", 4.42, 1.91, None, 3, None, ""),
    ("Citroen Berlingo", "van", 4.14, 1.87, 1.80, 4, None, ""),
    ("Fiat Stilo", "hatch", 4.18, 1.91, None, 3, None, ""),
    ("Fiat Multipla", "van", 4.00, 2.00, 1.67, 2, (120, 170, 120), ""),
    ("Skoda Fabia", "hatch", 3.97, 1.80, None, 6, None, ""),
    ("Skoda Octavia Taksi", "taxi", 4.57, 1.92, None, 4, (238, 192, 28), ""),
    ("Seat Leon Kupra", "hatch", 4.32, 1.92, None, 3, (200, 30, 30), "spoiler"),
    ("Hyundai Getz", "hatch", 3.81, 1.82, None, 4, None, ""),
    ("Toyota Yaris", "hatch", 3.75, 1.81, None, 4, None, ""),
    ("Ford Focus Karavan", "wagon", 4.47, 1.99, None, 4, None, ""),
    ("Ford Transit Shverc", "van", 5.20, 2.00, 2.30, 2, WHITE_, "roofload"),
    ("Volvo V70 Dedov", "wagon", 4.71, 1.95, None, 2, SILVER, ""),
    ("Golf Chetvorka Bez Registracija", "hatch", 4.15, 1.88, None, 5, None, ""),
    ("JSP Dvokatnik", "bus", 10.8, 2.40, 4.30, 0, (200, 32, 36), "jsp"),
    ("JSP Zglobni", "bus", 12.0, 2.40, 3.10, 0, (200, 32, 36), "jsp"),
    # ---- two-wheelers: only ever got by knocking an NPC rider off (traffic weight 0)
    ("Velosiped", "bike", 1.75, 0.55, 1.05, 0, (200, 40, 40), "bike"),
    ("Moped Tomos", "bike", 1.80, 0.65, 1.10, 0, (210, 90, 30), "moped"),
    ("Glovo Skuter", "bike", 1.85, 0.70, 1.10, 0, (255, 208, 0), "scooter"),
    ("E-Trotinet", "bike", 1.20, 0.50, 1.05, 0, (30, 30, 34), "kick"),
    # ---- round 30: the police van and the heavy lorries (traffic weight 0: see HEAVY / Traffic.spawn, they only drive the big roads)
    ("Maritsa", "van", 6.60, 2.10, 2.75, 1, (20, 38, 104), "marica"),
    ("Kamion Tovarnik", "truck", 8.60, 2.45, 3.60, 0, None, "cargo"),
    ("Tir Rinfuz", "truck", 15.80, 2.55, 4.05, 0, None, "semi"),
    ("Cisterna Gorivo", "truck", 11.50, 2.50, 3.30, 0, SILVER, "tanker"),
]
N = len(_V)
IDS = [v[0] for v in _V]
STYLE = [v[1] for v in _V]
DIMS = [(v[2], v[3] * 0.93, _STYLE[v[1]][0], _STYLE[v[1]][1], v[4] or _STYLE[v[1]][2]) for v in _V]   # L, W, y0, belt, roof
FIXED = [v[6] for v in _V]
EXTRA = [v[7] for v in _V]
BUS = 6
MARITSA = IDS.index("Maritsa")
HEAVY = [IDS.index(n) for n in ("Kamion Tovarnik", "Tir Rinfuz", "Cisterna Gorivo")]      # lorries: big roads only, no tight turns
SEMI = IDS.index("Tir Rinfuz")
SEMI_TRACTOR_L = 6.4                                          # the tractor unit's own length; the rest of the 15.8 m rig is the hinged trailer
SEMI_SHIFT = DIMS[SEMI][0] / 2 - SEMI_TRACTOR_L / 2           # tractor model centre ahead of the rig centre
SEMI_HITCH = SEMI_SHIFT - 1.8                                 # fifth wheel / kingpin, ahead of the rig centre (m)
SEMI_TRAILER_L = DIMS[SEMI][0] / 2 + SEMI_HITCH               # kingpin to the trailer's tail
SEMI_AXLE = SEMI_TRAILER_L - 2.6                              # kingpin to the trailer's axle group
SEMI_REAR = SEMI_SHIFT - SEMI_TRACTOR_L * 0.29                # the tractor's rear tandem (its pivot), ahead of the rig centre (m)
SEMI_WB = SEMI_SHIFT + SEMI_TRACTOR_L * 0.36 - SEMI_REAR      # the tractor's own wheelbase, front axle to rear tandem (~4.2 m)
SEMI_JACK = 1.45                                              # articulation stop: the trailer's nose hits the cab at ~83 deg
HEAVY_W = [5, 3, 2]                                                                       # share of the heavy traffic
LARGE = [d[0] >= 6.4 for d in DIMS]                           # need a wide road
_SPEED = {"truck": 0.75, "tractor": 0.45, "bus": 0.8, "limo": 0.7}
SPEED = [_SPEED.get(s, 1.0) for s in STYLE]


def _circ(L, W):
    r = W / 2 + 0.05
    return (L / 2 - r + 0.1, r)


CIRC = {i: _circ(d[0], d[1]) for i, d in enumerate(DIMS)}
_DOOR_CAB = {"bus": (0.985, 0.0), "truck": (0.24, 0.38), "pickup": (0.36, 0.10), "tractor": (0.32, -0.12)}


def door_geom(kind):
    """(hinge x, door length) of the driver's door along the body (m, front +): where the door is drawn, where people get in and out."""
    import carbody
    L = DIMS[kind][0]
    if STYLE[kind] in carbody.LOFT_STYLES and carbody.has(IDS[kind]):
        lay = carbody.layout(IDS[kind], L)
        return lay["hinge"], lay["door"]
    if EXTRA[kind] == "semi":
        front = SEMI_SHIFT + SEMI_TRACTOR_L / 2 - 2.45 / 2 + 0.74
        return front, 1.0
    cl_f, cx_f = _DOOR_CAB.get(STYLE[kind], (0.5, 0.0))
    cl, cx = L * cl_f, L * cx_f
    front, rear = cx + cl * 0.30, cx - cl * 0.20
    if STYLE[kind] in ("bus", "truck", "tractor", "pickup"):
        rear = front - min(1.0, cl * 0.5)
    return front, max(0.6, front - rear)


HALF_L = [d[0] / 2 for d in DIMS]                              # the body itself, no padding: what fits physically may pass
HALF_W = [d[1] / 2 for d in DIMS]
TRAFFIC_W = [v[5] for v in _V]
PARKED_KINDS = [i for i in range(N) if not LARGE[i] and STYLE[i] != "tractor" for _ in range(_V[i][5])]
N_COLORS = 16

# ---------------------------------------------------------------------------- road users (0-8 classic, 9 = you)
# name, speed multiplier, spawn weight, one-liners
# какво гледа играчот (внатрешните имена горе остануваат за табелите со перформанси)
MK_CAR = {
    "Velosiped": TXT("vehicles.0300"), "Moped Tomos": TXT("vehicles.0301"), "Glovo Skuter": TXT("vehicles.0302"), "E-Trotinet": TXT("vehicles.0303"),
    "Zastava Yugo": TXT("vehicles.0001"), "Golf Dvojka": TXT("vehicles.0002"), "Kombi": TXT("vehicles.0003"), "Lada Niva": TXT("vehicles.0004"), "Mercedes 190": TXT("vehicles.0005"),
    "Taxi Zlatna Zolta": TXT("vehicles.0006"), "Gradski Avtobus": TXT("vehicles.0007"), "Fico": TXT("vehicles.0008"), "Pikap Tovarnik": TXT("vehicles.0009"),
    "Zastava 101 Skala": TXT("vehicles.0010"), "Zastava Koral": TXT("vehicles.0011"), "Lada Samara": TXT("vehicles.0012"), "Lada 1500": TXT("vehicles.0013"),
    "Moskvich 412": TXT("vehicles.0014"), "Trabant 601": TXT("vehicles.0015"), "Wartburg 353": TXT("vehicles.0016"), "Skoda Octavia Karavan": TXT("vehicles.0017"),
    "Pachuvka 2CV": TXT("vehicles.0018"), "Renault 4 Katrca": TXT("vehicles.0019"), "Fiat 126 Peglica": TXT("vehicles.0020"), "Fiat Punto": TXT("vehicles.0021"),
    "Fiat Uno": TXT("vehicles.0022"), "Opel Kadett": TXT("vehicles.0023"), "Opel Astra Karavan": TXT("vehicles.0024"), "Audi 80 Bachok": TXT("vehicles.0025"),
    "BMW E36 Bavarka": TXT("vehicles.0026"), "BMW X5 Chorbadzija": TXT("vehicles.0027"), "Mercedes 124 Taksist": TXT("vehicles.0028"),
    "Mercedes S Mafijash": TXT("vehicles.0029"), "Mercedes G Politichar": TXT("vehicles.0030"), "Sprinter Gastarbajter": TXT("vehicles.0031"),
    "Passat Dijaspora": TXT("vehicles.0032"), "Golf Trojka Gastarbajter": TXT("vehicles.0033"), "Caddy Dostava": TXT("vehicles.0034"),
    "Transporter Kombe": TXT("vehicles.0035"), "Renault Clio": TXT("vehicles.0036"), "Toyota Corolla": TXT("vehicles.0037"), "Land Cruiser Lovec": TXT("vehicles.0038"),
    "Nissan Qashqai": TXT("vehicles.0039"), "Dacia Duster": TXT("vehicles.0040"), "Dacia Logan": TXT("vehicles.0041"), "Kia Picanto": TXT("vehicles.0042"),
    "Tesla Elon": TXT("vehicles.0043"), "Hummer Patriot": TXT("vehicles.0044"), "Smart Sitnichka": TXT("vehicles.0045"), "Cayenne od Germanija": TXT("vehicles.0046"),
    "Range Rover Ortak": TXT("vehicles.0047"), "Policiska Skoda": TXT("vehicles.0048"), "Brza Pomosh": TXT("vehicles.0049"), "Pozharna": TXT("vehicles.0050"),
    "Smetar Kamion": TXT("vehicles.0051"), "Betonjerka": TXT("vehicles.0052"), "Pajak Vlechna Sluzhba": TXT("vehicles.0053"), "Burek Dostava": TXT("vehicles.0054"),
    "Makedonska Posta": TXT("vehicles.0055"), "Traktor Belarus": TXT("vehicles.0056"), "Svadbarska Limuzina": TXT("vehicles.0057"),
    "Avtobus Skopje-Ohrid": TXT("vehicles.0058"), "Sladoled Kombe": TXT("vehicles.0059"),
    "Golf Petka TDI": TXT("vehicles.0060"), "Golf Shestka Uvezen": TXT("vehicles.0061"),
    "Passat B5 Karavan": TXT("vehicles.0062"), "Passat B6 TDI": TXT("vehicles.0063"),
    "Audi A4 Avant Shvajcarska": TXT("vehicles.0064"), "Audi A6 Nemachka": TXT("vehicles.0065"),
    "BMW E46 Tjunirana": TXT("vehicles.0066"), "BMW E39 520d": TXT("vehicles.0067"),
    "Mercedes C Klasa W203": TXT("vehicles.0068"), "Mercedes E Klasa W211": TXT("vehicles.0069"),
    "Opel Astra G": TXT("vehicles.0070"), "Opel Corsa C": TXT("vehicles.0071"),
    "Opel Zafira Familijarna": TXT("vehicles.0072"), "Renault Megane Scenic": TXT("vehicles.0073"),
    "Peugeot 206": TXT("vehicles.0074"), "Peugeot 307 SW": TXT("vehicles.0075"),
    "Citroen Berlingo": TXT("vehicles.0076"), "Fiat Stilo": TXT("vehicles.0077"),
    "Fiat Multipla": TXT("vehicles.0078"), "Skoda Fabia": TXT("vehicles.0079"),
    "Skoda Octavia Taksi": TXT("vehicles.0080"), "Seat Leon Kupra": TXT("vehicles.0081"),
    "Hyundai Getz": TXT("vehicles.0082"), "Toyota Yaris": TXT("vehicles.0083"),
    "Ford Focus Karavan": TXT("vehicles.0084"), "Ford Transit Shverc": TXT("vehicles.0085"),
    "Volvo V70 Dedov": TXT("vehicles.0086"), "Golf Chetvorka Bez Registracija": TXT("vehicles.0087"),
    "JSP Dvokatnik": TXT("vehicles.0088"), "JSP Zglobni": TXT("vehicles.0089"),
    # round 30: not in text/ yet (the text folder is hand-edited): move these into text/02 when the editor is ready
    "Maritsa": "Марица", "Kamion Tovarnik": "Товарен камион", "Tir Rinfuz": "Шлепер", "Cisterna Gorivo": "Цистерна за гориво",
}
MK_PED = {
    "Chichko": TXT("vehicles.0090"), "Baba": TXT("vehicles.0091"), "Biznismen": TXT("vehicles.0092"), "Student": TXT("vehicles.0093"), "Navivach": TXT("vehicles.0094"), "Dete": TXT("vehicles.0095"), "Rabotnik": TXT("vehicles.0096"),
    "Devojka": TXT("vehicles.0097"), "Buregdzija": TXT("vehicles.0098"), "Ti": TXT("vehicles.0099"), "Pandur": TXT("vehicles.0100"), "Parkingar": TXT("vehicles.0101"), "Pop": TXT("vehicles.0102"), "Hipster": TXT("vehicles.0103"),
    "Influenser": TXT("vehicles.0104"), "Telefonash": TXT("vehicles.0105"), "Penzioner": TXT("vehicles.0106"), "Kafana Chicko": TXT("vehicles.0107"), "Turist": TXT("vehicles.0108"),
    "Gastarbajter": TXT("vehicles.0109"), "Majka so Kolichka": TXT("vehicles.0110"), "Partiski Aktivist": TXT("vehicles.0111"), "Advokat": TXT("vehicles.0112"),
    "Teretana Brat": TXT("vehicles.0113"), "Kiosk Chika": TXT("vehicles.0114"), "Ribar": TXT("vehicles.0115"), "Golabar": TXT("vehicles.0116"), "Komunalec": TXT("vehicles.0117"),
    "Nevesta": TXT("vehicles.0118"), "Dostavuvach": TXT("vehicles.0119"), "Velosipedist": TXT("vehicles.0120"), "Dedo na Kolo": TXT("vehicles.0121"), "Moped Tomos": TXT("vehicles.0122"),
    "Glovo Skuter": TXT("vehicles.0123"), "Trotinet Dete": TXT("vehicles.0124"), "E-Trotinet Hipster": TXT("vehicles.0125"), "Skejter": TXT("vehicles.0126"),
    "Rolerash": TXT("vehicles.0127"), "Kocija": TXT("vehicles.0128"), "Jogger": TXT("vehicles.0129"),
}
MK_LINES = {
    "Chichko": [TXT("vehicles.0130"), TXT("vehicles.0131")],
    "Baba": [TXT("vehicles.0132"), TXT("vehicles.0133"), TXT("vehicles.0134")],
    "Biznismen": [TXT("vehicles.0135"), TXT("vehicles.0136"), TXT("vehicles.0137")],
    "Student": [TXT("vehicles.0138"), TXT("vehicles.0139"), TXT("vehicles.0140")],
    "Navivach": [TXT("vehicles.0141"), TXT("vehicles.0142"), TXT("vehicles.0143")],
    "Dete": [TXT("vehicles.0144"), TXT("vehicles.0145"), TXT("vehicles.0146")],
    "Rabotnik": [TXT("vehicles.0147"), TXT("vehicles.0148"), TXT("vehicles.0149")],
    "Devojka": [TXT("vehicles.0150"), TXT("vehicles.0151"), TXT("vehicles.0152")],
    "Buregdzija": [TXT("vehicles.0153"), TXT("vehicles.0154"), TXT("vehicles.0155")],
    "Pandur": [TXT("vehicles.0156"), TXT("vehicles.0157"), TXT("vehicles.0158")],
    "Parkingar": [TXT("vehicles.0159"), TXT("vehicles.0160"), TXT("vehicles.0161")],
    "Pop": [TXT("vehicles.0162"), TXT("vehicles.0163"), TXT("vehicles.0164")],
    "Hipster": [TXT("vehicles.0165"), TXT("vehicles.0166"), TXT("vehicles.0167")],
    "Influenser": [TXT("vehicles.0168"), TXT("vehicles.0169"), TXT("vehicles.0170")],
    "Telefonash": [TXT("vehicles.0171"), TXT("vehicles.0172"), TXT("vehicles.0173")],
    "Penzioner": [TXT("vehicles.0174"), TXT("vehicles.0175"), TXT("vehicles.0176")],
    "Kafana Chicko": [TXT("vehicles.0177"), TXT("vehicles.0178"), TXT("vehicles.0179")],
    "Turist": [TXT("vehicles.0180"), TXT("vehicles.0181"), TXT("vehicles.0182")],
    "Gastarbajter": [TXT("vehicles.0183"), TXT("vehicles.0184"), TXT("vehicles.0185")],
    "Majka so Kolichka": [TXT("vehicles.0186"), TXT("vehicles.0187"), TXT("vehicles.0188")],
    "Partiski Aktivist": [TXT("vehicles.0189"), TXT("vehicles.0190"), TXT("vehicles.0191")],
    "Advokat": [TXT("vehicles.0192"), TXT("vehicles.0193"), TXT("vehicles.0194")],
    "Teretana Brat": [TXT("vehicles.0195"), TXT("vehicles.0196"), TXT("vehicles.0197")],
    "Kiosk Chika": [TXT("vehicles.0198"), TXT("vehicles.0199"), TXT("vehicles.0200")],
    "Ribar": [TXT("vehicles.0201"), TXT("vehicles.0202"), TXT("vehicles.0203")],
    "Golabar": [TXT("vehicles.0204"), TXT("vehicles.0205"), TXT("vehicles.0206")],
    "Komunalec": [TXT("vehicles.0207"), TXT("vehicles.0208"), TXT("vehicles.0209")],
    "Nevesta": [TXT("vehicles.0210"), TXT("vehicles.0211"), TXT("vehicles.0212")],
    "Dostavuvach": [TXT("vehicles.0213"), TXT("vehicles.0214"), TXT("vehicles.0215")],
    "Velosipedist": [TXT("vehicles.0216"), TXT("vehicles.0217"), TXT("vehicles.0218")],
    "Dedo na Kolo": [TXT("vehicles.0219"), TXT("vehicles.0220"), TXT("vehicles.0221")],
    "Moped Tomos": [TXT("vehicles.0222"), TXT("vehicles.0223"), TXT("vehicles.0224")],
    "Glovo Skuter": [TXT("vehicles.0225"), TXT("vehicles.0226"), TXT("vehicles.0227")],
    "Trotinet Dete": [TXT("vehicles.0228"), TXT("vehicles.0229"), TXT("vehicles.0230")],
    "E-Trotinet Hipster": [TXT("vehicles.0231"), TXT("vehicles.0232"), TXT("vehicles.0233")],
    "Skejter": [TXT("vehicles.0234"), TXT("vehicles.0235"), TXT("vehicles.0236")],
    "Rolerash": [TXT("vehicles.0237"), TXT("vehicles.0238"), TXT("vehicles.0239")],
    "Kocija": [TXT("vehicles.0240"), TXT("vehicles.0241"), TXT("vehicles.0242")],
    "Jogger": [TXT("vehicles.0243"), TXT("vehicles.0244"), TXT("vehicles.0245")],
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
# NPC riders you can knock off and ride away on: ped name -> two-wheeler vehicle name
JACK_BIKE = {"Velosipedist": "Velosiped", "Dedo na Kolo": "Velosiped", "Moped Tomos": "Moped Tomos", "Glovo Skuter": "Glovo Skuter",
             "E-Trotinet Hipster": "E-Trotinet"}
JACK_KIND = {i: IDS.index(JACK_BIKE[n]) for i, n in enumerate(PED_IDS) if n in JACK_BIKE}
BIKES = {i for i in range(N) if STYLE[i] == "bike"}
PED_ARCH_N = PED_COUNT                                          # kept for compatibility
WALKERS = [i for i in range(PED_COUNT) if i != PLAYER and PED_IDS[i] not in RIDERS]

# ---------------------------------------------------------------------------- handling: (top speed m/s, accel m/s2, steering, grip, mass)
_PERF_STYLE = {"hatch": (35, 10.5, 0.68, 9.5, 1.0), "sedan": (40, 12.0, 0.62, 9.5, 1.1), "taxi": (38, 11.0, 0.62, 9.5, 1.1),
               "mini": (28, 8.0, 0.75, 9.0, 0.7), "suv": (36, 10.0, 0.56, 8.5, 1.5), "van": (31, 8.0, 0.62, 8.5, 1.6),
               "pickup": (33, 9.0, 0.60, 8.5, 1.5), "bus": (24, 4.5, 0.66, 8.0, 5.0), "wagon": (36, 10.5, 0.60, 9.5, 1.2),
               "limo": (34, 8.0, 0.58, 8.5, 1.8), "truck": (26, 5.5, 0.62, 8.0, 4.0), "tractor": (11, 3.0, 0.50, 7.5, 2.5), "bike": (9, 5.0, 0.95, 8.0, 0.2)}
_PERF_NAME = {
    "Zastava Yugo": (29, 7.5), "Golf Dvojka": (37, 11), "Mercedes 190": (44, 13), "Fico": (24, 6, 0.80), "Zastava 101 Skala": (32, 9),
    "Zastava Koral": (30, 8.5), "Lada Samara": (33, 9), "Lada 1500": (32, 8.5), "Moskvich 412": (29, 7), "Trabant 601": (25, 5.5),
    "Wartburg 353": (31, 7), "Pachuvka 2CV": (24, 4.5, 0.7), "Renault 4 Katrca": (27, 6), "Fiat 126 Peglica": (22, 4.5, 0.8),
    "Golf Trojka Gastarbajter": (41, 12.5), "Passat Dijaspora": (42, 12), "Audi 80 Bachok": (42, 12), "BMW E36 Bavarka": (50, 17, 0.70, 11),
    "BMW X5 Chorbadzija": (52, 15), "Mercedes 124 Taksist": (41, 11), "Mercedes S Mafijash": (52, 14), "Mercedes G Politichar": (40, 10, 0.5),
    "Tesla Elon": (58, 24, 0.66, 11), "Hummer Patriot": (38, 9, 0.45), "Cayenne od Germanija": (55, 18, 0.64, 11),
    "Range Rover Ortak": (46, 12), "Policiska Skoda": (48, 16, 0.66, 10.5), "Brza Pomosh": (40, 11), "Smart Sitnichka": (27, 7, 0.9),
    "Moped Tomos": (17, 7.5, 0.90, 8.5, 0.3), "Glovo Skuter": (21, 9, 0.90, 9.0, 0.35), "E-Trotinet": (11, 6, 0.95, 8.0, 0.2),
    "Lada Niva": (32, 9, 0.6, 10), "Land Cruiser Lovec": (40, 10), "Pajak Vlechna Sluzhba": (34, 9),
    "Maritsa": (38, 8.5, 0.54, 9.0, 2.0), "Tir Rinfuz": (24, 4.0, 0.62, 8.0, 7.0), "Cisterna Gorivo": (24, 4.5, 0.55, 8.0, 6.0),
}
PERF = []
for _i, _v in enumerate(_V):
    _b = list(_PERF_STYLE[_v[1]])
    _o = _PERF_NAME.get(_v[0])
    if _o:
        for _k, _x in enumerate(_o):
            _b[_k] = _x
    _b[0] *= 0.75                     # Martin: 25% lower top speed and acceleration all round
    _b[1] *= 0.75
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
KIOSK_MENU = [(TXT("vehicles.0246"), 70, 30), (TXT("vehicles.0247"), 40, 15), (TXT("vehicles.0248"), 130, 50), (TXT("vehicles.0249"), 90, 35)]


# ---------------------------------------------------------------- sound profiles (see audio.py)
_ENGINE = {}
for _i in (8, 30, 33, 34, 37, 48, 52, 53, 54, 58, MARITSA):
    _ENGINE[_i] = "engine_diesel"
for _i in (6, 57, 87, 88):
    _ENGINE[_i] = "engine_bus"
for _i in (59, 66, 75, 84):
    _ENGINE[_i] = "engine_tdi"                                               # light turbodiesel cars and vans: tighter, harder knock than the big diesels
_ENGINE[90] = _ENGINE[91] = "engine_moto"
_ENGINE[92] = "engine_ev"
for _i in (49, 50, 51, 55, *HEAVY):
    _ENGINE[_i] = "engine_truck"
for _i in (25, 26, 28, 29, 43, 45, 46):
    _ENGINE[_i] = "engine_v8"
for _i in (0, 7, 9, 10, 14, 15, 17, 18, 19, 41, 44):
    _ENGINE[_i] = "engine_small"
_ENGINE[42] = "engine_ev"
ENGINE_SOUND = [_ENGINE.get(i, "engine_i4") for i in range(N)]
_HORN = {56: "horn_jingle", 58: "horn_jingle"}
for _i in (6, 49, 50, 51, 55, 57, 30, 34, *HEAVY):
    _HORN[_i] = "horn_truck"
for _i in (7, 14, 19, 41, 44, 0, 17):
    _HORN[_i] = "horn_small"
HORN_SOUND = [_HORN.get(i, "horn") for i in range(N)]
SIREN_SOUND = {47: "siren_police", 48: "siren_amb", 49: "siren_fire", MARITSA: "siren_police"}
