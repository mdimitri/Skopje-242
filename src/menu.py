"""Options / pause menu.  Keyboard (arrows, Enter, Esc) and mouse (hover, click, drag sliders)."""
from texts import TXT
import os
import time

import pyray as rl
import font   # noqa: E402

import characters as C
import poster
import present
import settings as S

# ---- themes: comic-book UI (slanted tabs/buttons, offset shadows, halftone dots), 10 palettes chosen in Контроли > Дебаг
def _c(*v):
    return rl.Color(*v) if len(v) == 4 else rl.Color(v[0], v[1], v[2], 255)


# name, paper, ink, accent1, accent2, dot, dotmode, text, muted, highlight, frame, shadow, paper2, text on highlight, active tab, veil
THEMES = [
    ("Поп светло", _c(255, 250, 235), _c(0, 0, 0), _c(255, 60, 110), _c(255, 224, 40), _c(255, 60, 110, 50), "u", _c(0, 0, 0), _c(60, 60, 70), _c(255, 224, 40), "s", _c(0, 0, 0), _c(255, 255, 255), None, None, 150),
    ("Поп темно розова", _c(24, 14, 34), _c(246, 238, 220), _c(255, 60, 110), _c(255, 224, 40), _c(255, 60, 110, 70), "u", _c(246, 238, 220), _c(170, 150, 180), _c(120, 20, 64), "s", _c(226, 32, 104), _c(48, 30, 60), _c(246, 238, 220), _c(255, 60, 110), 150),
    ("Среднок цијан", _c(10, 18, 40), _c(0, 230, 255), _c(0, 200, 255), _c(255, 224, 40), _c(0, 200, 255, 60), "u", _c(230, 248, 255), _c(130, 160, 200), _c(0, 90, 140), "d", _c(0, 120, 160), _c(22, 36, 70), _c(255, 255, 255), _c(0, 150, 200), 170),
    ("Црн ноар црвено", _c(14, 12, 14), _c(255, 255, 255), _c(235, 40, 50), _c(255, 200, 60), _c(235, 40, 50, 200), "g", _c(255, 255, 255), _c(170, 160, 160), _c(120, 20, 28), "s", _c(120, 20, 28), _c(40, 34, 38), _c(255, 255, 255), _c(235, 40, 50), 190),
    ("Токсично зелено", _c(8, 16, 12), _c(80, 255, 140), _c(40, 200, 100), _c(230, 255, 60), _c(60, 255, 130, 70), "u", _c(225, 255, 235), _c(140, 180, 155), _c(20, 100, 55), "d", _c(20, 90, 50), _c(22, 40, 30), _c(255, 255, 255), _c(40, 200, 100), 180),
    ("Зајдисонце топло", _c(255, 236, 205), _c(50, 16, 40), _c(240, 60, 90), _c(255, 170, 40), _c(255, 90, 60, 90), "g", _c(50, 16, 40), _c(110, 70, 80), _c(255, 196, 100), "s", _c(50, 16, 40), _c(255, 255, 255), None, None, 110),
    ("Темен прскан раб", _c(30, 12, 40), _c(255, 214, 60), _c(255, 60, 110), _c(255, 214, 60), _c(255, 214, 60, 60), "u", _c(250, 240, 255), _c(180, 150, 190), _c(130, 24, 90), "b", _c(0, 0, 0, 200), _c(52, 28, 66), _c(255, 255, 255), _c(255, 60, 110), 150),
    ("Виолетово злато", _c(20, 12, 44), _c(255, 210, 90), _c(150, 70, 255), _c(255, 210, 90), _c(150, 70, 255, 190), "g", _c(250, 244, 255), _c(170, 155, 200), _c(80, 40, 150), "d", _c(10, 4, 30), _c(40, 28, 80), _c(255, 255, 255), _c(150, 70, 255), 175),
    ("Мента мастило", _c(12, 24, 30), _c(110, 255, 220), _c(30, 200, 170), _c(255, 120, 160), _c(110, 255, 220, 55), "u", _c(235, 255, 250), _c(140, 180, 180), _c(20, 100, 100), "d", _c(0, 60, 60), _c(26, 50, 58), _c(255, 255, 255), _c(30, 200, 170), 175),
    ("Јаглен со раб", _c(32, 32, 36), _c(255, 255, 255), _c(255, 150, 30), _c(255, 235, 120), _c(255, 150, 30, 60), "g", _c(245, 245, 245), _c(165, 165, 170), _c(110, 64, 10), "b", _c(0, 0, 0), _c(58, 58, 64), _c(255, 255, 255), _c(255, 150, 30), 190),
]
THEME_NAMES = [t[0] for t in THEMES]
DEFAULT_THEME = 5                       # Зајдисонце топло
INK_TXT = _c(20, 12, 28)
WHITE = _c(255, 255, 255)
CD = "cond"
_th = {"i": -1}
PINK = CREAM = MUTED = PLUM = TRACK = GOLD = None


def set_theme(i):
    """Pick the palette; the old PINK / CREAM / MUTED names (title menu, picker) follow the theme."""
    global PINK, CREAM, MUTED, PLUM, TRACK, GOLD
    i = max(0, min(len(THEMES) - 1, int(i)))
    if _th["i"] == i:
        return
    _th["i"] = i
    t = THEMES[i]
    _th.update(zip(("name", "paper", "ink", "a1", "a2", "dot", "dm", "fg", "mu", "hl", "frame", "shadow", "p2", "hlt", "tabon", "veil"), t))
    PINK, CREAM, MUTED, PLUM, TRACK = _th["a1"], _th["fg"], _th["mu"], _th["paper"], _th["p2"]
    GOLD = CREAM


set_theme(DEFAULT_THEME)


def _q(pts, c):
    v = [rl.Vector2(float(a), float(b)) for a, b in pts]
    for tri in ((0, 1, 2), (0, 2, 3)):
        rl.draw_triangle(v[tri[0]], v[tri[1]], v[tri[2]], c)
        rl.draw_triangle(v[tri[0]], v[tri[2]], v[tri[1]], c)


def _skew(x, y, w, h, k, c):
    _q([(x + k, y), (x + w + k, y), (x + w, y + h), (x, y + h)], c)


def _veil(W, H, a=None):
    rl.draw_rectangle(0, 0, W, H, rl.Color(10, 6, 18, _th["veil"] if a is None else a))


def _panel(x, y, w, h):
    """Comic card: offset shadow, halftone dots (even or growing from a corner), heavy ink frame."""
    t = _th
    rl.draw_rectangle(x + 10, y + 10, w, h, t["shadow"])
    rl.draw_rectangle(x, y, w, h, t["paper"])
    dc = t["dot"]
    dc = rl.Color(dc.r, dc.g, dc.b, int(dc.a * 0.4))      # subtler: lower contrast
    for yy in range(y + 8, y + h - 8, 18):
        for xx in range(x + 8 + ((yy - y) // 18 % 2) * 9, x + w - 8, 18):
            if t["dm"] == "u":
                r = 1.5
            else:
                d = ((xx - x) / w + (1 - (yy - y) / h)) / 2
                r = max(0, min(3, int(4 * d * d * 1.4)))
            if r > 0:
                rl.draw_circle(xx, yy, r, dc)
    rl.draw_rectangle_lines_ex(rl.Rectangle(x, y, w, h), 5, t["ink"])
    if t["frame"] == "d":
        rl.draw_rectangle_lines_ex(rl.Rectangle(x + 9, y + 9, w - 18, h - 18), 2, t["a1"])
    elif t["frame"] == "b":
        for i in range(0, w - 40, 24):
            _q([(x + 20 + i, y), (x + 32 + i, y - 12), (x + 44 + i, y), (x + 32 + i, y + 2)], t["a1"])


def _tab(x, y, w, h, label, on, sz=22):
    t = _th
    _skew(x + 3, y + 3, w - 8, h, -10, t["shadow"] if t["frame"] != "d" else t["ink"])
    _skew(x, y, w - 8, h, -10, (t["tabon"] or t["a2"]) if on else t["p2"])
    col = (t["ink"] if t["tabon"] is None else t["fg"]) if on else (t["hlt"] or t["fg"])
    font.draw_text(label, x + (w - 8 - font.measure_text(label, sz, CD)) // 2, y + 4, sz, col, bold=CD)


def _head(x, y, w, label):
    t = _th
    tw = font.measure_text(label, 30, CD) + 30
    _skew(x + 4, y + 4, tw, 36, -8, t["shadow"])
    _skew(x, y, tw, 36, -8, t["a1"])
    font.draw_text(label, x + 15, y + 2, 30, WHITE, bold=CD)


def _rowhl(x, y, w, h):
    _skew(x - 8 + 3, y + 3, w + 16, h, -8, _th["shadow"])
    _skew(x - 8, y, w + 16, h, -8, _th["hl"])


def _slider(x, y, w, f):
    t = _th
    rl.draw_rectangle(x, y + 6, w, 18, t["ink"])
    rl.draw_rectangle(x + 4, y + 10, int((w - 8) * f), 10, t["a1"])
    for i in range(0, int((w - 8) * f), 10):
        rl.draw_rectangle(x + 4 + i, y + 10, 3, 10, t["a2"])
    rl.draw_circle(int(x + w * f), y + 15, 16, t["a2"])
    rl.draw_circle_lines(int(x + w * f), y + 15, 16, t["fg"] if t["ink"].r < 60 else t["ink"])


def _toggle(x, y, on, labels):
    t = _th
    _skew(x + 4, y + 4, 170, 36, -8, t["shadow"])
    _skew(x, y, 170, 36, -8, t["a1"] if on else t["p2"])
    lab = labels[0] if on else labels[1]
    font.draw_text(lab, x + 4 + (166 - font.measure_text(lab, 28, CD)) // 2, y + 3, 28, WHITE if on else t["mu"], bold=CD)


def _bar(x, y, w, h, n, col):
    for b in range(8):
        _skew(x + b * (w // 8), y, w // 8 - 4, h, -4, col if b < n else _th["p2"])


def _btn(x, y, w, h, label, hot, sz=22):
    t = _th
    _skew(x + 4, y + 4, w, h, -8, t["shadow"])
    _skew(x, y, w, h, -8, t["a1"] if hot else t["a2"])
    font.draw_text(label, x + (w - font.measure_text(label, sz, CD)) // 2, y + (h - sz) // 2 - sz // 10, sz, WHITE if hot else INK_TXT, bold=CD)


def _logo(x, y, sz):
    font.draw_text("СКОПЈЕ", x + 2, y + 2, sz, rl.Color(0, 0, 0, 180), bold=CD)
    font.draw_text("СКОПЈЕ", x, y, sz, _th["fg"], bold=CD)
    x2 = x + font.measure_text("СКОПЈЕ ", sz, CD)
    font.draw_text("242", x2 + 2, y + 2, sz, rl.Color(0, 0, 0, 180), bold=CD)
    font.draw_text("242", x2, y, sz, _th["a1"], bold=CD)


# title menu (v3); new labels live here until they can be added to text/ (human-edited)
TITLE_ITEMS = [("new", "НОВА ИГРА"), ("cont", "ПРОДОЛЖИ"), ("multi", "МУЛТИПЛЕЈЕР"), ("settings", "ПОСТАВКИ"), ("quit", "ИЗЛЕЗ")]
NO_SAVE = "Нема зачувана игра"
NO_WORLD = "Прво изгради го светот (копчето горе десно)"
WORLD = {"built": True}     # main sets False when there is no built world yet: play / continue / multiplayer wait for a build
BACK = "Назад"
_T = {}
MP = {"session": None}     # set by the multiplayer lobby when the host pressed Start (the game itself joins in the next step)


def _title():
    """The title poster (assets/posters/title.png), loaded once; None if it is missing."""
    if "t" not in _T:
        _T["t"] = poster.Posters().title()
    return _T["t"]


class Row:
    def __init__(self, kind, label, key=None, options=None, lo=0.0, hi=1.0, fmt=None, note="", bar=False):
        self.kind, self.label, self.key, self.options = kind, label, key, options
        self.bar = bar                       # a "choice" drawn (and dragged) as a slider
        self.lo, self.hi, self.fmt, self.note = lo, hi, fmt, note


TABS = [TXT("menu.0006"), "Градот", "Луѓето", "Графика", "Контроли", TXT("menu.0003")]   # Игра · Градот · Луѓето · Графика · Контроли · Звук


_cfg = None


def _rows(in_game, slots=(), settings_only=False):
    """-> list of (tab, Row)."""
    pct = lambda v: f"{int(v * 100)}%"
    xz = lambda v: f"{v:.2f}x".replace(".", ",")
    spd = [TXT("menu.0007"), "0,25x", "0,5x", "1x", "2x", "4x", "8x", "16x"]
    def mz(metres, floor):                     # "1,00x · 60×34 м": the ground the screen shows at this zoom (ppm as in main.py's camera, car standing still)
        def f(v):
            w, h = S.RESOLUTIONS[_cfg["resolution"]] if _cfg is not None else (rl.get_screen_width(), rl.get_screen_height())   # the frame is drawn at the chosen resolution
            ppm = max(w / metres * v, floor)
            return f"{v:.2f}x · {w / ppm:.0f}×{h / ppm:.0f} м".replace(".", ",")
        return f
    dens = [f"{d:g}x".replace(".", ",") for d in S.DENSITY]
    H = lambda t: Row("head", t)
    R = [
        # tabs: 0 Игра · 1 Градот · 2 Луѓето · 3 Графика · 4 Контроли · 5 Звук  (new labels live here until they can be added to text/)
        (1, H("Време")),
        (1, Row("slider", TXT("menu.0027"), "hour", lo=0.0, hi=23.99, fmt=lambda v: f"{int(v):02d}:{int((v % 1) * 60):02d}")),
        (1, Row("choice", TXT("menu.0028"), "time_speed", spd, bar=True, note=TXT("menu.0029"))),
        (1, H("Сообраќај и служби")),
        (1, Row("choice", TXT("menu.0030"), "traffic", dens, bar=True)),
        (1, Row("toggle", TXT("menu.0038"), "ambulance")),
        (1, Row("toggle", TXT("menu.0039"), "fire")),
        (1, H("Податоци за мапата")),
        (1, Row("choice", TXT("menu.0040"), "osm_source", S.MAP_SOURCES, note=TXT("menu.0041"))),
        (2, H("Население")),
        (2, Row("choice", TXT("menu.0031"), "peds", dens, bar=True)),
        (2, H("Однесување")),
        (2, Row("choice", TXT("menu.0034"), "aggro", S.AGGRO, bar=True, note=TXT("menu.0035"))),
        (2, H("Разговори")),
        (2, Row("choice", TXT("menu.0032"), "speech_freq", [f"{v:g}x".replace(".", ",") for v in S.SPEECH_FREQ], bar=True, note=TXT("menu.0033"))),
        (2, Row("choice", TXT("menu.0036"), "lang", S.LANGUAGE, note=TXT("menu.0037"))),
        (3, H("Екран")),
        (3, Row("choice", TXT("menu.0008"), "resolution", [S.res_label(w, h) for w, h in S.RESOLUTIONS])),
        (3, Row("toggle", TXT("menu.0009"), "fullscreen")),
        # new labels live here until they can be added to text/ (human-edited)
        (3, Row("choice", "Скалирање на сликата", "scale", S.SCALE, note="кога прозорецот е поголем од избраната резолуција")),
        (3, H("Квалитет")),
        (3, Row("choice", TXT("menu.0010"), "detail", S.DETAIL, note=TXT("menu.0011"))),
        (3, Row("choice", "Измазнување на рабови", "aa", S.AA, note="се применува по рестарт на играта")),
        (3, H("Околина")),
        (3, Row("toggle", TXT("menu.0014"), "labels")),
        (3, Row("toggle", TXT("menu.0012"), "smog", note=TXT("menu.0013"))),
        (3, Row("slider", "Јачина на смог", "smog_level", lo=0.0, hi=3.0, fmt=pct, note="100% е нормално, над тоа е густ, тежок смог")),
        (3, Row("slider", "Загадување од возила", "pollution", lo=0.0, hi=3.0, fmt=pct, note="колку чадат автомобилите")),
        (4, H("Камера")),
        (4, Row("slider", TXT("menu.0015"), "zoom_walk", lo=0.4, hi=2.4, fmt=mz(60.0, 3.64 / 0.6), note=TXT("menu.0016"))),
        (4, Row("slider", TXT("menu.0017"), "zoom_car", lo=0.4, hi=2.4, fmt=mz(100.0, 0.97 / 0.6))),
        (4, Row("slider", TXT("menu.0018"), "shake", lo=0.0, hi=2.0, fmt=pct)),
        (4, H("Глувче")),
        (4, Row("choice", "Глувче во трето лице", "mouse_mode", S.MOUSE_MODE, note="следење: камерата оди зад ликот/колата, глувчето не прави ништо; или управување/слободно гледање со глувчето")),
        (4, Row("slider", "Осетливост на глувчето", "mouse_sens", lo=0.2, hi=3.0, fmt=xz, note="вртење со глувчето во гледната точка од улица")),
        (4, H("Дебаг")),
        (4, Row("choice", "Тема на менијата", "theme", THEME_NAMES, note="изглед на менијата (стрип стил), се менува веднаш")),
        (4, Row("toggle", "Гледна точка од улица", "debug_chase", note="камера зад аватарот, ниско на улица")),
        (4, Row("toggle", "Телепортирање на мапата", "debug", note="исклучено: на мапата се користи навигација (стрелка до целта)")),
        (5, H("Јачина")),
        (5, Row("slider", TXT("menu.0019"), "vol_master", fmt=pct)),
        (5, Row("slider", TXT("menu.0020"), "vol_sfx", fmt=pct)),
        (5, Row("slider", TXT("menu.0021"), "vol_engine", fmt=pct)),
        (5, Row("slider", TXT("menu.0022"), "vol_ambient", fmt=pct)),
        (5, Row("slider", TXT("menu.0023"), "vol_speech", fmt=pct)),
        (5, Row("slider", TXT("menu.0024"), "vol_radio", fmt=pct)),
        (5, H("Говор")),
        (5, Row("choice", TXT("menu.0025"), "voice", S.VOICES)),
        (5, Row("choice", TXT("menu.0026"), "speech_speed", [f"{v:g}x".replace(".", ",") for v in S.SPEECH_SPEEDS], bar=True)),
    ]
    if settings_only:                    # opened from the title menu: only the options, and a way back
        return R + [(0, Row("action", BACK, "play"))]
    g = [Row("action", TXT("menu.0042") if in_game else TXT("menu.0043"), "play")]
    if in_game:
        g += [Row("head", TXT("menu.0044")), *[Row("action", (TXT("menu.0045") + f'{n}:  {slots[n - 1]}'), f"save{n}") for n in range(1, len(slots) + 1)]]
    g += [Row("head", TXT("menu.0046")), *[Row("action", (TXT("menu.0047") + f'{n}:  {slots[n - 1]}'), f"load{n}") for n in range(1, len(slots) + 1)]]
    if in_game:
        g += [Row("head", ""), Row("action", TXT("menu.0048"), "chars"), Row("action", "Назад на главното мени", "mainmenu")]
    g += [Row("action", TXT("menu.0049"), "quit")]
    return R + [(0, r) for r in g]


def _title_card(seconds=6.0):
    present.off()                         # menus draw straight to the window

    """The title poster full screen until a key / click (or `seconds`).  -> True if the window was closed."""
    t0 = time.time()
    while True:
        if rl.window_should_close():
            return True
        W, H = rl.get_screen_width(), rl.get_screen_height()
        rl.begin_drawing()
        rl.clear_background(rl.Color(10, 12, 18, 255))
        poster.draw_fit(_title(), 0, 0, W, H, 255, cover=True)
        if (time.time() - t0) % 1.6 < 1.1:
            txt = TXT("menu.0050")
            font.draw_text(txt, (W - font.measure_text(txt, 22)) // 2, H - 48, 22, rl.Color(255, 245, 210, 235))
        font.exit_button()
        font.draw_version(W, H)
        rl.end_drawing()
        if time.time() - t0 > 0.4 and (rl.get_key_pressed() or rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)):
            return False
        if time.time() - t0 > seconds:
            return False


_TEX = {}
_P0 = poster.Posters()


def _portrait(i):
    if i not in _TEX:
        p = C.image_path(i)
        _TEX[i] = rl.load_texture(p) if p else None
    return _TEX[i]


def _layout(n, W, H, aspect):
    """Columns / card size that make the portrait cards as big as the screen allows (cards keep the image aspect)."""
    best = None
    top, bottom, label = 90, 70, 62
    for cols in range(3, 13):
        rows = (n + cols - 1) // cols
        cw = (W - 40) / cols
        ih = min((cw - 12) / aspect, (H - top - bottom) / rows - label - 12)
        if ih < 40:
            continue
        iw = ih * aspect
        if best is None or ih * iw > best[0]:
            best = (ih * iw, cols, rows, int(iw + 12), int(ih + label + 12))
    _a, cols, rows, cw, ch = best
    gx = max(6, (W - 40 - cols * cw) // max(1, cols))                  # spread the spare width as gaps
    gy = max(6, (H - top - bottom - rows * ch) // max(1, rows))
    return cols, rows, cw, ch, gx, gy, top


LOW_GOOD = {"somnitelnost"}          # stats where a LOW value is the good one (less police attention)


def _grad(t):
    """Red (t=0) -> orange -> yellow (0.5) -> green (1)."""
    stops = ((0.0, (214, 52, 48)), (0.25, (232, 128, 46)), (0.5, (238, 208, 56)), (0.75, (150, 205, 70)), (1.0, (62, 196, 104)))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return rl.Color(*(int(a + (b - a) * f) for a, b in zip(c0, c1)), 255)
    return rl.Color(*stops[-1][1], 255)


def _panel_rect(W, H):
    pw = int(W * 0.5)
    return W - pw - 16, 124, pw, H - 124 - 46


_hero_scroll = {"sel": -1, "y": 0, "max": 0}


def _hero_panel(sel, W, H, wheel=0):
    """Fixed window on the right for the chosen hero: portrait, name, tagline, role, 8 stat bars (n/8 blocks); below them the
    quote, story, goal, ability and weakness in a scrolling area (mouse wheel / PgUp PgDn) so the large text never clips."""
    import hero_profiles as HP
    hid, name = C.LIKOVI[sel][0], C.LIKOVI[sel][1]
    pr = HP.profile(hid)
    px, py, pw, ph = _panel_rect(W, H)
    fs = max(19, min(30, H // 32))
    gray, white = _th["mu"], _th["fg"]
    _panel(px, py, pw, ph)
    tw = int(pw * 0.30)
    t = _portrait(sel)
    pic_h = int(ph * 0.36)
    if t:
        poster.draw_fit(t, px + 10, py + 14, tw - 10, pic_h)
    x2, w2 = px + tw + 16, pw - tw - 30
    y = py + 12
    font.draw_text(font.fit(name, fs + 8, w2, CD), x2, y, fs + 8, _th["a1"], bold=CD)
    y += fs + 12
    tag = pr["title"].split(" — ", 1)[-1]
    for ln in font.wrap(tag[:1].upper() + tag[1:], fs, w2, CD)[:2]:
        font.draw_text(ln, x2, y, fs, white, bold=CD)
        y += fs + 3
    font.draw_text(font.fit(f"{pr['role']}  ·  {pr['money']} ден.", fs, w2, CD), x2, y + 2, fs, gray, bold=CD)
    y += fs + 12
    lw = max(font.measure_text(nm + (" *" if k in LOW_GOOD else ""), fs, CD) for k, nm in zip(HP.STAT_KEYS, HP.STAT_NAMES)) + 12
    bw = max(8, (w2 - lw - 52) // 8 - 3)
    rowh = fs + 6
    for key, nm in zip(HP.STAT_KEYS, HP.STAT_NAMES):
        v = pr["stats"][key]
        n = max(1, -(-v * 8 // 100))                                      # 0..100 -> 1..8 blocks (rounded up, never empty)
        good = (8 - n) / 7.0 if key in LOW_GOOD else (n - 1) / 7.0        # colour = how GOOD it is, not how big: low Сомнителност is green
        col = _grad(good)
        font.draw_text(nm + (" *" if key in LOW_GOOD else ""), x2, y, fs, white, bold=CD)
        _bar(x2 + lw, y + 2, 8 * (bw + 3), fs, n, col)
        font.draw_text(str(v), x2 + lw + 8 * (bw + 3) + 8, y, fs, white, bold=CD)
        y += rowh
    font.draw_text("зелено = добро · црвено = лошо · * помалку е подобро", x2, y, max(14, fs - 6), gray, bold=CD)
    y = max(y + fs, py + pic_h + 24) + 8
    # scrolling prose
    tx, tw2 = px + 16, pw - 32
    items = [("", f"„{pr['quote']}“")] + [(lb, tx_) for lb, tx_ in (("Приказна", pr["story"]), ("Цел", pr["goal"]),
                                                                    (pr["ability_name"], pr["ability"]), ("Слабост", pr["weakness"]))]
    lines = []
    for label, txt in items:
        if label:
            lines.append((label.upper() + ":", _th["a1"]))
        for ln in font.wrap(txt, fs, tw2 - 8):
            lines.append((ln, _th["a1"] if not label else white))
        lines.append(("", white))
    lh = fs + 4
    view = py + ph - 10 - y
    hs = _hero_scroll
    if hs["sel"] != sel:
        hs.update(sel=sel, y=0)
    hs["max"] = max(0, len(lines) * lh - view)
    hs["y"] = max(0, min(hs["max"], hs["y"] - wheel * lh * 2))
    rl.begin_scissor_mode(px + 4, y, pw - 8, view)
    for i, (ln, col) in enumerate(lines):
        yy = y + i * lh - hs["y"]
        if ln and -lh < yy - y < view:
            font.draw_text(ln, tx, yy, fs, col, bold=CD if ln.endswith(":") and ln.isupper() else False)
    rl.end_scissor_mode()
    if hs["max"] > 0:                         # scroll bar
        bh = max(20, int(view * view / (view + hs["max"])))
        rl.draw_rectangle(px + pw - 12, y, 6, view, _th["p2"])
        rl.draw_rectangle(px + pw - 12, y + int((view - bh) * hs["y"] / hs["max"]), 6, bh, _th["a1"])


def pick_character(cfg, aud=None, music=None):
    present.off()                         # menus draw straight to the window
    set_theme(cfg["theme"])

    """Избор на лик (стрелки / глушец, Enter). -> True ако е затворен прозорецот."""
    n = len(C.LIKOVI)
    sel = min(cfg["lik"], n - 1)
    t0 = _portrait(0)
    aspect = (t0.width / t0.height) if t0 else 0.75

    def snd(name, pitch=1.0, vol=0.7):
        if aud is not None:
            aud.play(name, vol, pitch)

    def done(i):
        cfg["lik"] = i
        cfg.save()
        snd("pick", 0.9 + 0.03 * (i % 7), 0.9)
        snd("cash", 1.0, 0.5)
        t = time.time()
        while time.time() - t < 0.45 and not rl.window_should_close():     # let the confirm sound ring
            rl.begin_drawing()
            rl.end_drawing()
        return False

    last = sel
    pick_character._armed = False
    pick_character.back = False
    t_open = time.time()
    while True:
        armed = time.time() - t_open > 0.35 and not rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT) or getattr(pick_character, "_armed", False)
        pick_character._armed = armed                       # the click / key that closed the title card must not pick
        if rl.window_should_close():
            return True
        W, H = rl.get_screen_width(), rl.get_screen_height()
        Wl = _panel_rect(W, H)[0] - 10                                  # cards use the left part; the panel is fixed on the right
        cols, rows, cw, ch, gx, gy, top = _layout(n, Wl, H, aspect)

        def pos(i):
            r, c = divmod(i, cols)
            in_row = min(cols, n - r * cols)                                # centre the last, shorter row
            xr = (Wl - in_row * cw - (in_row - 1) * gx) // 2 + 6
            return xr + c * (cw + gx), top + r * (ch + gy)

        m = rl.get_mouse_position()
        for i in range(n):
            cx, cy = pos(i)
            if cx <= m.x < cx + cw and cy <= m.y < cy + ch:
                if rl.get_mouse_delta().x or rl.get_mouse_delta().y:
                    sel = i
                if armed and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                    return done(i)
        if rl.is_key_pressed(rl.KEY_RIGHT):
            sel = (sel + 1) % n
        if rl.is_key_pressed(rl.KEY_LEFT):
            sel = (sel - 1) % n
        if rl.is_key_pressed(rl.KEY_DOWN):
            sel = (sel + cols) % n
        if rl.is_key_pressed(rl.KEY_UP):
            sel = (sel - cols) % n
        if sel != last:
            snd("tick", 0.9 + 0.05 * (sel % 5), 0.6)
            last = sel
        if armed and rl.is_key_pressed(rl.KEY_L):
            pick_character.load = True
            return done(sel)
        if armed and (rl.is_key_pressed(rl.KEY_BACKSPACE) or rl.is_key_pressed(rl.KEY_ESCAPE)
                      or (rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and W - 640 <= m.x < W - 340 and 56 <= m.y < 114)):
            pick_character.back = True                                  # back to the main menu: nothing is chosen or saved
            return False
        if armed and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and W - 330 <= m.x < W - 20 and 56 <= m.y < 114:
            pick_character.load = True
            return done(sel)
        if armed and (rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_SPACE)):
            return done(sel)
        rl.begin_drawing()
        bg = poster.Posters.texture(_P0, "menu_bg.png") if os.path.exists(os.path.join(poster.DIR, "menu_bg.png")) else _title()
        if bg is not None:
            poster.draw_fit(bg, 0, 0, W, H, 255, cover=True)
        else:
            rl.clear_background(rl.Color(22, 24, 28, 255))
        _veil(W, H)
        font.draw_text(TXT("menu.0051").upper(), 96, 8, 66, WHITE, bold=CD)
        rl.draw_rectangle(96, 80, 140, 6, _th["a1"])
        for i, (_id, name, stats, money) in enumerate(C.LIKOVI):
            cx, cy = pos(i)
            on = i == sel
            g = 4 if on else 0                                              # the chosen card grows a little
            rl.draw_rectangle(cx - g, cy - g, cw + 2 * g, ch + 2 * g, _th["hl"] if on else _th["paper"])
            rl.draw_rectangle_lines_ex(rl.Rectangle(cx - g, cy - g, cw + 2 * g, ch + 2 * g), 3 if on else 1,
                                       _th["a1"] if on else _th["ink"])
            t = _portrait(i)
            ih = ch - 74
            if t:
                poster.draw_fit(t, cx + 6 - g, cy + 6 - g, cw - 12 + 2 * g, ih + 2 * g)
            else:
                rl.draw_circle(cx + cw // 2, cy + ih // 2, min(cw, ih) // 4, rl.Color(90 + i * 12, 120, 160 - i * 9, 255))
                ini = name[0]
                font.draw_text(ini, cx + cw // 2 - font.measure_text(ini, 44, True) // 2, cy + ih // 2 - 26, 44, rl.WHITE, bold=True)
            fs = max(13, min(28, cw // 4))
            lines = font.wrap(name, fs, cw - 6, CD)[:2]
            while fs > 9 and any(font.measure_text(ln, fs, CD) > cw - 6 for ln in lines):     # a long word shrinks the label, never overflows
                fs -= 1
                lines = font.wrap(name, fs, cw - 6, CD)[:2]
            for k, ln in enumerate(lines):
                font.draw_text(ln, cx + (cw - font.measure_text(ln, fs, CD)) // 2, cy + ch - 58 + g + k * (fs + 2), fs,
                               (_th["hlt"] or _th["fg"]) if on else _th["fg"], bold=CD)
        _hero_panel(sel, W, H, int(rl.get_mouse_wheel_move()) + (1 if rl.is_key_pressed(rl.KEY_PAGE_UP) else 0) - (1 if rl.is_key_pressed(rl.KEY_PAGE_DOWN) else 0))
        _btn(W - 640, 56, 300, 58, "< " + BACK, W - 640 <= m.x < W - 340 and 56 <= m.y < 114, 30)
        _btn(W - 330, 56, 310, 58, TXT("menu.0053"), W - 330 <= m.x < W - 20 and 56 <= m.y < 114, 30)
        font.draw_text(TXT("menu.0054"), 24, H - 36, 25, rl.Color(240, 232, 240, 255), bold=CD)
        if music is not None:
            music.update()
            music.widget(x=W // 2 - 200, y=20, keys=False)
        font.exit_button()
        font.draw_version(W, H)
        rl.end_drawing()


def _first(rows):
    return next((i for i, r in enumerate(rows) if r.kind != "head"), 0)


def _latest_save():
    """Slot number of the newest save, or 0."""
    import savegame
    best = (0.0, 0)
    for n in range(1, savegame.SLOTS + 1):
        d = savegame.read(n)
        if d and d.get("t", 0) > best[0]:
            best = (d["t"], n)
    return best[1]


def _slot_picker(aud=None, music=None, latest=0):
    """Продолжи: which saved game?  The slots over the splash art in the title-menu style.  -> slot number, or 0 (back)."""
    import savegame
    slots = [(n, savegame.read(n)) for n in range(1, savegame.SLOTS + 1)]
    rows = [(n, savegame.summary(n), d is not None) for n, d in slots] + [(0, BACK.upper(), True)]
    sel = next((i for i, r in enumerate(rows) if r[0] == latest), len(rows) - 1)
    t_open = time.time()
    last_m = None
    while True:
        if rl.window_should_close():
            return 0
        if music is not None:
            music.update()
        W, H = rl.get_screen_width(), rl.get_screen_height()
        sz = max(16, H // 38)
        rh = int(sz * 1.45)
        bw = min(W - 40, max(font.measure_text(r[1], sz, "cond") for r in rows) + 5 * sz)
        x0 = (W - bw) // 2
        y0 = H - len(rows) * rh - 40                     # below the logo of the splash art
        armed = time.time() - t_open > 0.3
        m = rl.get_mouse_position()
        moved = last_m is not None and (m.x, m.y) != last_m
        last_m = (m.x, m.y)
        hover = next((i for i in range(len(rows)) if x0 <= m.x < x0 + bw and y0 + i * rh <= m.y < y0 + (i + 1) * rh), None)
        old = sel
        if hover is not None and moved:
            sel = hover
        if rl.is_key_pressed(rl.KEY_DOWN) or rl.is_key_pressed(rl.KEY_S):
            sel = (sel + 1) % len(rows)
        if rl.is_key_pressed(rl.KEY_UP) or rl.is_key_pressed(rl.KEY_W):
            sel = (sel - 1) % len(rows)
        if sel != old and aud is not None:
            aud.play("tick", 0.6, 0.9 + 0.05 * (sel % 5))      # the same tone clicks as the character screen
        if armed and rl.is_key_pressed(rl.KEY_ESCAPE):
            return 0
        go = armed and (rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_SPACE) or
                        (hover is not None and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)))
        if go and rows[sel][2]:
            if aud is not None:
                aud.play("ui_confirm", 0.6)
            return rows[sel][0]
        rl.begin_drawing()
        poster.draw_splash(W, H)
        rl.draw_rectangle(x0 - 20, y0 - rh - 14, bw + 40, (len(rows) + 1) * rh + 28, rl.Color(10, 8, 16, 190))
        t = "КОЈА ИГРА?"
        font.draw_text(t, (W - font.measure_text(t, sz, "cond")) // 2, y0 - rh, sz, rl.Color(255, 150, 190, 255), bold="cond")
        for i, (n, label, ok) in enumerate(rows):
            y = y0 + i * rh
            txt = (f"{n}.  " if n else "") + label
            tw = font.measure_text(txt, sz, "cond")
            tx, ty = x0 + (bw - tw) // 2, y + (rh - sz) // 2 - sz // 10
            if i == sel:
                rl.draw_rectangle(x0, y + 2, bw, rh - 4, PINK if ok else rl.Color(90, 60, 80, 255))
            col = rl.WHITE if i == sel else (rl.Color(232, 226, 232, 255) if ok else rl.Color(140, 130, 140, 255))
            font.draw_text(txt, tx, ty, sz, col, bold="cond")
        if music is not None:
            music.widget()
        font.draw_version(W, H)
        rl.end_drawing()


def _confirm_rebuild():
    """Themed warning card before a rebuild of an existing world.  -> True to go on."""
    t0 = time.time()
    sel = 1
    while not rl.window_should_close():
        W, H = rl.get_screen_width(), rl.get_screen_height()
        pw, ph = min(W - 40, 980), 400
        px, py = (W - pw) // 2, (H - ph) // 2
        bw, bh = (pw - 90) // 2, 66
        by = py + ph - bh - 36
        rects = [(px + 30, by), (px + 60 + bw, by)]
        m = rl.get_mouse_position()
        hit = next((i for i, (bx, byy) in enumerate(rects) if bx <= m.x < bx + bw and byy <= m.y < byy + bh), None)
        if hit is not None:
            sel = hit
        if rl.is_key_pressed(rl.KEY_LEFT) or rl.is_key_pressed(rl.KEY_RIGHT) or rl.is_key_pressed(rl.KEY_TAB):
            sel = 1 - sel
        if time.time() - t0 > 0.3:
            if rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_SPACE):
                return sel == 0
            if rl.is_key_pressed(rl.KEY_ESCAPE):
                return False
            if hit is not None and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                return hit == 0
        rl.begin_drawing()
        poster.draw_splash(W, H)
        _veil(W, H)
        _panel(px, py, pw, ph)
        y = py + 30
        for txt, sz, col in (("Повторно градење на светот", 48, _th["fg"]),
                             ("Ова трае долго (од неколку минути до половина час).", 32, _th["mu"]),
                             ("Светот ќе се изгради од почеток, па играта продолжува.", 32, _th["mu"])):
            txt = font.fit(txt, sz, pw - 60, "cond")
            font.draw_text(txt, px + (pw - font.measure_text(txt, sz, "cond")) // 2, y, sz, col, bold="cond")
            y += sz + 22
        for i, (lab, (bx, byy)) in enumerate(zip(("Изгради повторно", "Откажи"), rects)):
            _btn(bx, byy, bw, bh, lab, sel == i, 32)
        rl.end_drawing()
    return False


def title_menu(aud=None, music=None):
    """Нова игра / Продолжи / Поставки / Излез over the splash art.  -> 'new' | 'cont<N>' | 'settings' | 'quit'"""
    present.off()
    latest = _latest_save()
    sel = 0
    flash_t, flash_msg = 0.0, NO_SAVE
    t_open = time.time()
    last_m = None
    while True:
        if rl.window_should_close():
            return "quit"
        if music is not None:
            music.update()
        W, H = rl.get_screen_width(), rl.get_screen_height()
        sz = max(20, H // 28)
        rh = int(sz * 1.45)
        bw = max(font.measure_text(t, sz, "cond") for _k, t in TITLE_ITEMS) + 4 * sz
        x0, y0 = (W - bw) // 2, min(int(H * 0.755), H - len(TITLE_ITEMS) * rh - 14)      # (the last row stays on a small window)
        armed = time.time() - t_open > 0.3
        m = rl.get_mouse_position()
        moved = last_m is not None and (m.x, m.y) != last_m
        last_m = (m.x, m.y)
        hover = None
        for i in range(len(TITLE_ITEMS)):
            if x0 <= m.x < x0 + bw and y0 + i * rh <= m.y < y0 + (i + 1) * rh:
                hover = i
        old = sel
        if hover is not None and moved:
            sel = hover
        if rl.is_key_pressed(rl.KEY_DOWN) or rl.is_key_pressed(rl.KEY_S):
            sel = (sel + 1) % len(TITLE_ITEMS)
        if rl.is_key_pressed(rl.KEY_UP) or rl.is_key_pressed(rl.KEY_W):
            sel = (sel - 1) % len(TITLE_ITEMS)
        if sel != old and aud is not None:
            aud.play("tick", 0.6, 0.9 + 0.05 * (sel % 5))      # the same tone clicks as the character screen
        go = armed and (rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_SPACE) or
                        (hover is not None and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)))
        if armed and rl.is_key_pressed(rl.KEY_ESCAPE):
            sel, go = len(TITLE_ITEMS) - 1, True
        # the world build: its own button top right, outside the list (B on the keyboard)
        blab = "ИЗГРАДИ ПОВТОРНО" if WORLD["built"] else "ИЗГРАДИ ГО СВЕТОТ"
        bsz = max(22, H // 32)
        bbw, bbh = font.measure_text(blab, bsz, "cond") + 3 * bsz, int(bsz * 2.0)
        bbx, bby = W - bbw - 16, 56
        over_b = bbx <= m.x < bbx + bbw and bby <= m.y < bby + bbh
        if armed and ((over_b and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)) or rl.is_key_pressed(rl.KEY_B)):
            go = False
            if not WORLD["built"] or _confirm_rebuild():
                return "rebuild"
            t_open = time.time()
        if go:
            k = TITLE_ITEMS[sel][0]
            if aud is not None:
                aud.play("ui_confirm", 0.6)
            if k in ("new", "cont", "multi") and not WORLD["built"]:
                flash_t, flash_msg = time.time(), NO_WORLD
            elif k == "cont":
                if latest:
                    n = _slot_picker(aud, music, latest)
                    if n:
                        return f"cont{n}"
                    t_open = time.time()                 # the Enter / click that closed the picker must not act here
                else:
                    flash_t, flash_msg = time.time(), NO_SAVE
            elif k == "quit":
                if font.confirm_quit():
                    return "quit"
            elif k == "multi":
                import lobby
                import mpprofile as profile
                MP["session"] = lobby.run(profile.Profile(), aud, music)
                if MP["session"]:
                    return "multi"
                t_open = time.time()
            else:
                return k
        rl.begin_drawing()
        poster.draw_splash(W, H)
        for i, (k, label) in enumerate(TITLE_ITEMS):
            y = y0 + i * rh
            tw = font.measure_text(label, sz, "cond")
            tx = x0 + (bw - tw) // 2
            ty = y + (rh - sz) // 2 - sz // 10
            off = (k == "cont" and not latest) or (k in ("new", "cont", "multi") and not WORLD["built"])
            if i == sel:
                rl.draw_rectangle(x0, y + 2, bw, rh - 4, PINK)
                font.draw_text(label, tx, ty, sz, rl.WHITE, bold="cond")
            else:
                font.draw_text(label, tx + 2, ty + 2, sz, rl.Color(0, 0, 0, 170), bold="cond")    # drop shadow over the art
                font.draw_text(label, tx, ty, sz, rl.Color(150, 140, 150, 255) if off else rl.Color(232, 226, 232, 255), bold="cond")
        _btn(bbx, bby, bbw, bbh, blab, over_b or (not WORLD["built"] and int(time.time() * 2) % 2 == 0), bsz)   # blinks while there is no world
        font.draw_version(W, H)
        if time.time() - flash_t < 2.0:
            fw = font.measure_text(flash_msg, sz * 3 // 4, "cond")
            font.draw_text(flash_msg, (W - fw) // 2, y0 + len(TITLE_ITEMS) * rh + 6, sz * 3 // 4, rl.Color(255, 150, 190, 255), bold="cond")
        if music is not None:
            music.widget()
        rl.end_drawing()


def run(cfg, apply, in_game=False, draw_bg=None, aud=None, save_fn=None, music=None, settings_only=False):
    present.off()                         # menus draw straight to the window

    """Blocks until the player resumes or quits. `apply(cfg)` is called after every change; `save_fn(slot)` saves the game.
    -> 'play' | 'quit' | 'chars' (back to the character screen) | 'load1'..'load5'"""
    import savegame
    tab, flash, flash_t = getattr(run, "tab0", 0), "", 0.0
    if not in_game and not settings_only:     # start: the title menu over the splash art
        while True:
            ch = title_menu(aud, music)
            if ch in ("quit", "rebuild"):
                return ch
            if ch.startswith("cont"):
                cfg.save()
                return "load" + ch[4:]
            if ch == "settings":
                def bg():
                    if music is not None:
                        music.update()
                    poster.draw_splash(rl.get_screen_width(), rl.get_screen_height())
                if run(cfg, apply, False, bg, aud, music=music, settings_only=True) == "quit":
                    return "quit"
                continue
            pick_character.load = False         # new game: choose who you are
            if pick_character(cfg, aud, music):
                return "quit"
            if pick_character.back:
                continue                        # Назад: the title menu again
            cfg.save()
            if not pick_character.load:
                return "play"
            break                               # L on the character screen: the load slots below
    slots = [savegame.summary(n) for n in range(1, savegame.SLOTS + 1)]
    global _cfg
    _cfg = cfg
    set_theme(cfg["theme"])
    allrows = _rows(in_game, slots, settings_only)
    rows = [r for t, r in allrows if t == tab]
    sel = _first(rows)
    drag = None
    scr = 0
    frames = 0
    while True:
        frames += 1
        if rl.window_should_close():
            return "quit"
        W, H = rl.get_screen_width(), rl.get_screen_height()
        pw = min(1140, W - 40)
        x0 = (W - pw) // 2
        rh = 50
        y0 = 176
        avail = H - 150 - y0                                   # rows scroll inside this window
        m = rl.get_mouse_position()
        changed = False
        # ---- tabs: click, Tab / Shift+Tab, PgUp / PgDn
        tw = pw // len(TABS)
        new_tab = tab
        if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and 100 <= m.y < 152 and x0 <= m.x < x0 + tw * len(TABS):
            new_tab = int((m.x - x0) // tw)
        shift = rl.is_key_down(rl.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KEY_RIGHT_SHIFT)
        if rl.is_key_pressed(rl.KEY_PAGE_DOWN) or (rl.is_key_pressed(rl.KEY_TAB) and not shift):
            new_tab = (tab + 1) % len(TABS)
        if rl.is_key_pressed(rl.KEY_PAGE_UP) or (rl.is_key_pressed(rl.KEY_TAB) and shift):
            new_tab = (tab - 1) % len(TABS)
        if new_tab != tab:
            tab = new_tab
            rows = [r for t, r in allrows if t == tab]
            sel, drag, scr = _first(rows), None, 0
            continue
        # ---- scrolling: the rows are large, so the list moves inside its window (wheel, or keeps the selected row in view)
        offs, yy = [], 0
        for r in rows:
            if r.kind == "head":
                yy += 6
            offs.append(yy)
            yy += rh
        scr -= int(rl.get_mouse_wheel_move()) * rh * 2
        top_i = offs[sel] - (rh + 6 if sel > 0 and rows[sel - 1].kind == "head" else 0)
        scr = min(scr, top_i) if top_i < scr else scr
        scr = max(scr, offs[sel] + rh - avail)
        scr = max(0, min(scr, max(0, yy - avail)))
        # ---- mouse hover / click
        hover = None
        for i, r in enumerate(rows):
            y = y0 - scr + offs[i]
            if r.kind != "head" and x0 <= m.x <= x0 + pw and y <= m.y < y + rh and y0 <= m.y < y0 + avail:
                hover = i
        if hover is not None and (m.x != getattr(run, "_mx", -1) or rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)):
            sel = hover
        run._mx = m.x
        bw = int(pw * 0.28)
        vx = x0 + int(pw * 0.46)
        # ---- keys
        def step(d):
            r = rows[sel]
            if r.kind == "choice":
                cfg[r.key] = (cfg[r.key] + d) % len(r.options) if not r.bar else max(0, min(len(r.options) - 1, cfg[r.key] + d))
            elif r.kind == "toggle":
                cfg[r.key] = not cfg[r.key]
            elif r.kind == "slider":
                span = r.hi - r.lo
                cfg[r.key] = max(r.lo, min(r.hi, cfg[r.key] + d * span * (0.05 if r.key != "hour" else 0.0417)))
            return True
        if aud is not None and (rl.is_key_pressed(rl.KEY_DOWN) or rl.is_key_pressed(rl.KEY_UP)):
            aud.play("ui_click", 0.5)
        if rl.is_key_pressed(rl.KEY_DOWN):
            sel = (sel + 1) % len(rows)
            while rows[sel].kind == "head":
                sel = (sel + 1) % len(rows)
        if rl.is_key_pressed(rl.KEY_UP):
            sel = (sel - 1) % len(rows)
            while rows[sel].kind == "head":
                sel = (sel - 1) % len(rows)
        if rl.is_key_pressed(rl.KEY_LEFT) or rl.is_key_pressed_repeat(rl.KEY_LEFT):
            changed = step(-1)
        if rl.is_key_pressed(rl.KEY_RIGHT) or rl.is_key_pressed_repeat(rl.KEY_RIGHT):
            changed = step(1)
        act = rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_SPACE)
        if aud is not None and act:
            aud.play("ui_confirm", 0.6)
        clicked = rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and hover is not None
        r = rows[sel]
        slider_like = r.kind == "slider" or (r.kind == "choice" and r.bar)
        if clicked and slider_like:
            drag = sel
        if not rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT):
            drag = None
        if drag is not None:
            rr = rows[drag]
            f = max(0.0, min(1.0, (m.x - vx) / bw))
            if rr.kind == "slider":
                cfg[rr.key] = rr.lo + (rr.hi - rr.lo) * f
            else:
                cfg[rr.key] = int(round(f * (len(rr.options) - 1)))
            changed = True
        elif clicked and r.kind in ("choice", "toggle"):
            step(1)
            changed = True
        if (act or clicked) and r.kind == "action":
            k = r.key
            if k == "play":
                cfg.save()
                return "play"
            if k == "quit" and not font.confirm_quit():
                continue
            if k == "mainmenu":
                ans = font.confirm_leave()
                if ans is None:
                    continue
                if ans == "save" and save_fn is not None:
                    n = next((i for i in range(1, savegame.SLOTS + 1) if savegame.read(i) is None), 1)   # first empty slot, else slot 1
                    if not save_fn(n):
                        flash, flash_t = TXT("menu.0057"), time.time()
                        continue
                cfg.save()
                return k
            if k in ("quit", "chars"):
                cfg.save()
                return k
            if k.startswith("load"):
                if savegame.read(int(k[4:])):
                    cfg.save()
                    return k
                flash, flash_t = TXT("menu.0055"), time.time()
            elif k.startswith("save") and save_fn is not None:
                n = int(k[4:])
                ok = save_fn(n)
                flash, flash_t = (TXT("menu.0056") % n) if ok else TXT("menu.0057"), time.time()
                slots = [savegame.summary(i) for i in range(1, savegame.SLOTS + 1)]
                allrows = _rows(in_game, slots, settings_only)
                rows = [x for t, x in allrows if t == tab]
        if rl.is_key_pressed(rl.KEY_ESCAPE) and (in_game or settings_only) and frames > 1:   # the Esc that opened the menu must not close it
            cfg.save()
            return "play"
        if changed:
            set_theme(cfg["theme"])
            apply(cfg)
        # ---- draw (splash style: plum card, pink accents, Oswald condensed)
        rl.begin_drawing()
        if draw_bg:
            draw_bg()
            _veil(W, H, None if not in_game else 190)
        elif not in_game and _title() is not None:
            poster.draw_fit(_title(), 0, 0, W, H, 255, cover=True)
            _veil(W, H)
        else:
            rl.clear_background(rl.Color(16, 10, 24, 255))
        _panel(x0 - 24, 6, pw + 48, H - 12)
        _logo(x0, 4, 60)
        font.draw_text(TXT("menu.0059").upper(), x0 + 6, 70, 22, _th["mu"], bold=CD)
        for i, name in enumerate(TABS):
            tx = x0 + i * tw
            on_t = i == tab
            name = name.upper()
            _tab(tx + 2, 100, tw, 48, name, on_t, 30 if font.measure_text(name, 30, CD) <= tw - 24 else 22)
        rl.begin_scissor_mode(x0 - 20, y0, pw + 40, avail)
        for i, r in enumerate(rows):
            y = y0 - scr + offs[i]
            if y + rh < y0 or y > y0 + avail:
                continue
            if r.kind == "head":
                if r.label:
                    _head(x0, y, pw, r.label.upper())
                continue
            on = i == sel
            if on:
                _rowhl(x0, y, pw, rh)
            col = (_th["hlt"] or _th["fg"]) if on else _th["fg"]
            if r.kind == "action":
                big = r.key in ("play", "chars", "quit")
                font.draw_text(r.label.upper() if big else r.label, x0 + 6, y + 5, 36 if big else 33, _th["a1"] if (r.key == "play" and not on) else col, bold=CD)
            else:
                font.draw_text(r.label, x0 + 6, y + 5, 33, col, bold=CD)
                if r.kind == "choice" and not r.bar:
                    font.draw_text(f"<  {r.options[cfg[r.key]]}  >" if on else r.options[cfg[r.key]], vx, y + 5, 33, _th["a1"] if on else _th["fg"], bold=CD)
                elif r.kind == "toggle":
                    _toggle(vx, y + 4, cfg[r.key], (TXT("menu.0060"), TXT("menu.0061")))
                else:
                    if r.kind == "choice":
                        f, txt = cfg[r.key] / max(1, len(r.options) - 1), r.options[cfg[r.key]]
                    else:
                        f, txt = (cfg[r.key] - r.lo) / (r.hi - r.lo), r.fmt(cfg[r.key])
                    _slider(vx, y + rh // 2 - 15, bw, f)
                    font.draw_text(txt, vx + bw + 18, y + 6, 30, col, bold=CD)
        rl.end_scissor_mode()
        if yy > avail:                                          # scroll bar
            bh = max(24, int(avail * avail / yy))
            rl.draw_rectangle(x0 + pw + 8, y0, 6, avail, _th["p2"])
            rl.draw_rectangle(x0 + pw + 8, y0 + int((avail - bh) * scr / max(1, yy - avail)), 6, bh, _th["a1"])
        if rows[sel].note:
            font.draw_text(font.fit(rows[sel].note, 26, pw, CD), x0, H - 134, 26, _th["a1"], bold=CD)
        if flash and time.time() - flash_t < 2.5:
            font.draw_text(flash, x0 + pw - font.measure_text(flash, 30, CD), 24, 30, _th["a1"], bold=CD)
        font.draw_text(TXT("menu.0062"), x0, H - 38, 24, _th["mu"], bold=CD)
        label = ("Зачувај и затвори" if in_game else (BACK if settings_only else "Играј")).upper()
        bwid = font.measure_text(label, 30, CD) + 64
        bx, by = x0 + pw - bwid, H - 100
        over = bx <= m.x < bx + bwid and by <= m.y < by + 52
        _btn(bx, by, bwid, 52, label, over, 30)
        if over and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            cfg.save()
            return "play"
        if settings_only and music is not None and x0 - 24 - 150 > 60:      # beside the panel, if there is room
            music.widget(x=12, y=10, keys=False, room=min(360, x0 - 24 - 150))
        font.exit_button()
        if x0 - 24 >= 80:
            font.draw_version(W, H)
        else:                                                   # the panel covers the corner: the label goes in its top right, under the exit button
            from updater import GAME_VERSION
            vt = "v" + GAME_VERSION
            font.draw_text(vt, x0 + pw - font.measure_text(vt, 22, CD), 70, 22, _th["mu"], bold=CD)
        rl.end_drawing()
