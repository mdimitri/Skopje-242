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
from updater import GAME_VERSION

GOLD = rl.Color(240, 200, 60, 255)
PINK = rl.Color(226, 32, 104, 255)
# title menu (v3); new labels live here until they can be added to text/ (human-edited)
TITLE_ITEMS = [("new", "НОВА ИГРА"), ("cont", "ПРОДОЛЖИ"), ("multi", "МУЛТИПЛЕЈЕР"), ("settings", "ПОСТАВКИ"), ("quit", "ИЗЛЕЗ")]
NO_SAVE = "Нема зачувана игра"
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


TABS = [TXT("menu.0006"), "Градот", "Луѓето", "Графика", TXT("menu.0003"), "Дебаг"]   # Игра · Градот · Луѓето · Графика · Звук · Дебаг


def _rows(in_game, slots=(), settings_only=False):
    """-> list of (tab, Row)."""
    pct = lambda v: f"{int(v * 100)}%"
    xz = lambda v: f"{v:.2f}x".replace(".", ",")
    spd = [TXT("menu.0007"), "0,25x", "0,5x", "1x", "2x", "4x", "8x", "16x"]
    def mz(metres, floor):                     # "1,00x · 60×34 м": the ground the screen shows at this zoom (ppm as in main.py's camera, car standing still)
        def f(v):
            w, h = rl.get_screen_width(), rl.get_screen_height()
            ppm = max(w / metres * v, floor)
            return f"{v:.2f}x · {w / ppm:.0f}×{h / ppm:.0f} м".replace(".", ",")
        return f
    dens = [f"{d:g}x".replace(".", ",") for d in S.DENSITY]
    H = lambda t: Row("head", t)
    R = [
        # tabs: 0 Игра · 1 Градот · 2 Луѓето · 3 Графика · 4 Звук  (new labels live here until they can be added to text/)
        (1, H("Време")),
        (1, Row("slider", TXT("menu.0027"), "hour", lo=0.0, hi=23.99, fmt=lambda v: f"{int(v):02d}:{int((v % 1) * 60):02d}")),
        (1, Row("choice", TXT("menu.0028"), "time_speed", spd, bar=True, note=TXT("menu.0029"))),
        (1, H("Улица")),
        (1, Row("choice", TXT("menu.0030"), "traffic", dens, bar=True)),
        (2, H("Луѓе")),
        (2, Row("choice", TXT("menu.0031"), "peds", dens, bar=True)),
        (2, Row("choice", TXT("menu.0032"), "speech_freq", [f"{v:g}x".replace(".", ",") for v in S.SPEECH_FREQ], bar=True, note=TXT("menu.0033"))),
        (2, Row("choice", TXT("menu.0034"), "aggro", S.AGGRO, bar=True, note=TXT("menu.0035"))),
        (2, Row("choice", TXT("menu.0036"), "lang", S.LANGUAGE, bar=True, note=TXT("menu.0037"))),
        (1, H("Служби")),
        (1, Row("toggle", TXT("menu.0038"), "ambulance")),
        (1, Row("toggle", TXT("menu.0039"), "fire")),
        (3, H("Екран")),
        (3, Row("choice", TXT("menu.0008"), "resolution", [S.res_label(w, h) for w, h in S.RESOLUTIONS])),
        (3, Row("toggle", TXT("menu.0009"), "fullscreen")),
        # new labels live here until they can be added to text/ (human-edited)
        (3, Row("choice", "Скалирање на сликата", "scale", S.SCALE, note="кога прозорецот е поголем од избраната резолуција")),
        (3, Row("choice", "Anti-aliasing", "aa", S.AA, note="се применува по рестарт на играта")),
        (3, Row("choice", TXT("menu.0010"), "detail", S.DETAIL, note=TXT("menu.0011"))),
        (3, H("Камера")),
        (3, Row("slider", TXT("menu.0015"), "zoom_walk", lo=0.4, hi=2.4, fmt=mz(60.0, 3.64 / 0.6), note=TXT("menu.0016"))),
        (3, Row("slider", TXT("menu.0017"), "zoom_car", lo=0.4, hi=2.4, fmt=mz(100.0, 0.97 / 0.6))),
        (3, Row("slider", TXT("menu.0018"), "shake", lo=0.0, hi=2.0, fmt=pct)),
        (5, H("Дебаг")),
        (5, Row("toggle", "Гледна точка од улица", "debug_chase", note="камера зад аватарот, ниско на улица")),
        (5, Row("toggle", "Телепортирање на мапата", "debug", note="исклучено: на мапата се користи навигација (стрелка до целта)")),
        (3, Row("choice", "Глувче во трето лице", "mouse_mode", S.MOUSE_MODE, note="следење: камерата оди зад ликот/колата, глувчето не прави ништо; или управување/слободно гледање со глувчето")),
        (3, Row("slider", "Осетливост на глувчето", "mouse_sens", lo=0.2, hi=3.0, fmt=xz, note="вртење со глувчето во гледната точка од улица")),
        (3, H("Ознаки")),
        (3, Row("toggle", TXT("menu.0014"), "labels")),
        (3, H("Смог")),
        (3, Row("toggle", TXT("menu.0012"), "smog", note=TXT("menu.0013"))),
        (3, Row("slider", "Јачина на смог", "smog_level", lo=0.0, hi=3.0, fmt=pct, note="100% е нормално, над тоа е густ, тежок смог")),
        (3, Row("slider", "Загадување од возила", "pollution", lo=0.0, hi=3.0, fmt=pct, note="колку чадат автомобилите")),
        (4, H("Јачина")),
        (4, Row("slider", TXT("menu.0019"), "vol_master", fmt=pct)),
        (4, Row("slider", TXT("menu.0020"), "vol_sfx", fmt=pct)),
        (4, Row("slider", TXT("menu.0021"), "vol_engine", fmt=pct)),
        (4, Row("slider", TXT("menu.0022"), "vol_ambient", fmt=pct)),
        (4, Row("slider", TXT("menu.0023"), "vol_speech", fmt=pct)),
        (4, Row("slider", TXT("menu.0024"), "vol_radio", fmt=pct)),
        (4, H("Говор")),
        (4, Row("choice", TXT("menu.0025"), "voice", S.VOICES)),
        (4, Row("choice", TXT("menu.0026"), "speech_speed", [f"{v:g}x".replace(".", ",") for v in S.SPEECH_SPEEDS], bar=True)),
    ]
    MAPROW = (0, Row("choice", TXT("menu.0040"), "osm_source", S.MAP_SOURCES, note=TXT("menu.0041")))   # was the Мапа tab
    if settings_only:                    # opened from the title menu: only the options, and a way back
        return R + [MAPROW, (0, Row("action", BACK, "play"))]
    g = [Row("action", TXT("menu.0042") if in_game else TXT("menu.0043"), "play")]
    if in_game:
        g += [Row("head", TXT("menu.0044")), *[Row("action", (TXT("menu.0045") + f'{n}:  {slots[n - 1]}'), f"save{n}") for n in range(1, len(slots) + 1)]]
    g += [Row("head", TXT("menu.0046")), *[Row("action", (TXT("menu.0047") + f'{n}:  {slots[n - 1]}'), f"load{n}") for n in range(1, len(slots) + 1)]]
    if in_game:
        g += [Row("head", ""), Row("action", TXT("menu.0048"), "chars"), Row("action", "Назад на главното мени", "mainmenu")]
    g += [Row("action", TXT("menu.0049"), "quit")]
    return R + [(0, r) for r in g] + [MAPROW]


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
    top, bottom, label = 74, 128, 30
    for cols in range(3, 9):
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


def pick_character(cfg, aud=None, music=None):
    present.off()                         # menus draw straight to the window

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
    t_open = time.time()
    while True:
        armed = time.time() - t_open > 0.35 and not rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT) or getattr(pick_character, "_armed", False)
        pick_character._armed = armed                       # the click / key that closed the title card must not pick
        if rl.window_should_close():
            return True
        W, H = rl.get_screen_width(), rl.get_screen_height()
        cols, rows, cw, ch, gx, gy, top = _layout(n, W, H, aspect)
        x0 = (W - cols * cw - (cols - 1) * gx) // 2

        def pos(i):
            r, c = divmod(i, cols)
            in_row = min(cols, n - r * cols)                                # centre the last, shorter row
            xr = (W - in_row * cw - (in_row - 1) * gx) // 2
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
        if armed and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and W - 230 <= m.x < W - 20 and 56 <= m.y < 96:
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
        rl.draw_rectangle(0, 0, W, H, rl.Color(10, 12, 18, 215))
        font.seal(52, 40, 24)
        font.draw_text(TXT("menu.0051"), 90, 20, 40, GOLD, bold=True)
        for i, (_id, name, stats, money) in enumerate(C.LIKOVI):
            cx, cy = pos(i)
            on = i == sel
            g = 4 if on else 0                                              # the chosen card grows a little
            rl.draw_rectangle(cx - g, cy - g, cw + 2 * g, ch + 2 * g, rl.Color(48, 54, 72, 255) if on else rl.Color(26, 30, 40, 255))
            rl.draw_rectangle_lines_ex(rl.Rectangle(cx - g, cy - g, cw + 2 * g, ch + 2 * g), 3 if on else 1,
                                       GOLD if on else rl.Color(70, 76, 90, 255))
            t = _portrait(i)
            ih = ch - 42
            if t:
                poster.draw_fit(t, cx + 6 - g, cy + 6 - g, cw - 12 + 2 * g, ih + 2 * g)
            else:
                rl.draw_circle(cx + cw // 2, cy + ih // 2, min(cw, ih) // 4, rl.Color(90 + i * 12, 120, 160 - i * 9, 255))
                ini = name[0]
                font.draw_text(ini, cx + cw // 2 - font.measure_text(ini, 44, True) // 2, cy + ih // 2 - 26, 44, rl.WHITE, bold=True)
            fs = 18 if cw > 170 else 15
            nm = font.fit(name, fs, cw - 12, True)
            font.draw_text(nm, cx + (cw - font.measure_text(nm, fs, True)) // 2, cy + ch - 30 + g, fs,
                           GOLD if on else rl.Color(220, 220, 225, 255), bold=True)
        name, stats, money = C.LIKOVI[sel][1], C.LIKOVI[sel][2], C.LIKOVI[sel][3]
        by = H - 118
        rl.draw_rectangle(0, by - 8, W, 126, rl.Color(8, 10, 14, 200))
        font.draw_text((f'{name}  –  {money}' + TXT("menu.0052")), 24, by, 26, GOLD, bold=True)
        for k, ln in enumerate(font.wrap(stats, 19, W - 48)[:2]):
            font.draw_text(ln, 24, by + 36 + k * 25, 19, rl.Color(225, 225, 230, 255))
        rl.draw_rectangle_rounded(rl.Rectangle(W - 230, 56, 210, 40), 0.25, 6, rl.Color(48, 54, 72, 255))
        font.draw_text(TXT("menu.0053"), W - 214, 64, 22, GOLD, bold=True)
        font.draw_text(TXT("menu.0054"), 24, H - 26, 16, rl.Color(150, 150, 160, 255))
        if music is not None:
            music.update()
            music.widget(x=W // 2 - 200, y=20, keys=False)
        font.exit_button()
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
        rl.end_drawing()


def title_menu(aud=None, music=None):
    """Нова игра / Продолжи / Поставки / Излез over the splash art.  -> 'new' | 'cont<N>' | 'settings' | 'quit'"""
    present.off()
    latest = _latest_save()
    sel = 0
    flash_t = 0.0
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
        x0, y0 = (W - bw) // 2, int(H * 0.755)
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
        if go:
            k = TITLE_ITEMS[sel][0]
            if aud is not None:
                aud.play("ui_confirm", 0.6)
            if k == "cont":
                if latest:
                    n = _slot_picker(aud, music, latest)
                    if n:
                        return f"cont{n}"
                    t_open = time.time()                 # the Enter / click that closed the picker must not act here
                else:
                    flash_t = time.time()
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
            off = k == "cont" and not latest
            if i == sel:
                rl.draw_rectangle(x0, y + 2, bw, rh - 4, PINK)
                font.draw_text(label, tx, ty, sz, rl.WHITE, bold="cond")
            else:
                font.draw_text(label, tx + 2, ty + 2, sz, rl.Color(0, 0, 0, 170), bold="cond")    # drop shadow over the art
                font.draw_text(label, tx, ty, sz, rl.Color(150, 140, 150, 255) if off else rl.Color(232, 226, 232, 255), bold="cond")
        vt = "v" + GAME_VERSION
        font.draw_text(vt, W - font.measure_text(vt, 18, "cond") - 14, H - 30, 18, rl.Color(232, 226, 232, 200), bold="cond")
        if time.time() - flash_t < 2.0:
            fw = font.measure_text(NO_SAVE, sz * 3 // 4, "cond")
            font.draw_text(NO_SAVE, (W - fw) // 2, y0 + len(TITLE_ITEMS) * rh + 6, sz * 3 // 4, rl.Color(255, 150, 190, 255), bold="cond")
        if music is not None:
            music.widget()
        rl.end_drawing()


def run(cfg, apply, in_game=False, draw_bg=None, aud=None, save_fn=None, music=None, settings_only=False):
    present.off()                         # menus draw straight to the window

    """Blocks until the player resumes or quits. `apply(cfg)` is called after every change; `save_fn(slot)` saves the game.
    -> 'play' | 'quit' | 'chars' (back to the character screen) | 'load1'..'load5'"""
    import savegame
    tab, flash, flash_t = 0, "", 0.0
    if not in_game and not settings_only:     # start: the title menu over the splash art
        while True:
            ch = title_menu(aud, music)
            if ch == "quit":
                return "quit"
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
            cfg.save()
            if not pick_character.load:
                return "play"
            break                               # L on the character screen: the load slots below
    slots = [savegame.summary(n) for n in range(1, savegame.SLOTS + 1)]
    allrows = _rows(in_game, slots, settings_only)
    rows = [r for t, r in allrows if t == tab]
    sel = _first(rows)
    drag = None
    frames = 0
    while True:
        frames += 1
        if rl.window_should_close():
            return "quit"
        W, H = rl.get_screen_width(), rl.get_screen_height()
        pw = min(760, W - 40)
        x0 = (W - pw) // 2
        rh = max(24, min(34, (H - 220) // max(len(rows), 1)))
        y0 = 130
        m = rl.get_mouse_position()
        changed = False
        # ---- tabs: click, Tab / Shift+Tab, PgUp / PgDn
        tw = pw // len(TABS)
        new_tab = tab
        if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and 70 <= m.y < 108 and x0 <= m.x < x0 + tw * len(TABS):
            new_tab = int((m.x - x0) // tw)
        shift = rl.is_key_down(rl.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KEY_RIGHT_SHIFT)
        if rl.is_key_pressed(rl.KEY_PAGE_DOWN) or (rl.is_key_pressed(rl.KEY_TAB) and not shift):
            new_tab = (tab + 1) % len(TABS)
        if rl.is_key_pressed(rl.KEY_PAGE_UP) or (rl.is_key_pressed(rl.KEY_TAB) and shift):
            new_tab = (tab - 1) % len(TABS)
        if new_tab != tab:
            tab = new_tab
            rows = [r for t, r in allrows if t == tab]
            sel, drag = _first(rows), None
            continue
        # ---- mouse hover / click
        y = y0
        hover = None
        for i, r in enumerate(rows):
            if r.kind != "head" and x0 <= m.x <= x0 + pw and y <= m.y < y + rh:
                hover = i
            y += rh + (6 if r.kind == "head" else 0)
        if hover is not None and (m.x != getattr(run, "_mx", -1) or rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)):
            sel = hover
        run._mx = m.x
        bw = int(pw * 0.42)
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
            f = max(0.0, min(1.0, (m.x - (x0 + pw * 0.5)) / bw))
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
            apply(cfg)
        # ---- draw
        rl.begin_drawing()
        if draw_bg:
            draw_bg()
            rl.draw_rectangle(0, 0, W, H, rl.Color(10, 12, 18, 215))
        elif not in_game and _title() is not None:
            poster.draw_fit(_title(), 0, 0, W, H, 255, cover=True)
            rl.draw_rectangle(0, 0, W, H, rl.Color(10, 12, 18, 228))
        else:
            rl.clear_background(rl.Color(22, 24, 28, 255))
        rl.draw_rectangle_rounded(rl.Rectangle(x0 - 24, 6, pw + 48, H - 12), 0.02, 6, rl.Color(14, 16, 24, 235))
        rl.draw_rectangle(x0 - 24, 6, pw + 48, 4, GOLD)
        font.seal(x0 + 24, 40, 22)
        font.draw_text(TXT("menu.0058"), x0 + 60, 14, 30, GOLD, bold=True)
        font.draw_text(TXT("menu.0059"), x0 + 60, 48, 17, rl.Color(190, 190, 190, 255))
        for i, name in enumerate(TABS):
            tx = x0 + i * tw
            on_t = i == tab
            rl.draw_rectangle(tx + 2, 72, tw - 4, 34, rl.Color(48, 54, 72, 255) if on_t else rl.Color(26, 30, 40, 255))
            if on_t:
                rl.draw_rectangle(tx + 2, 104, tw - 4, 3, GOLD)
            sz = 20 if font.measure_text(name, 20, on_t) <= tw - 8 else 16
            lw = font.measure_text(name, sz, on_t)
            font.draw_text(name, tx + (tw - lw) // 2, 78, sz, GOLD if on_t else rl.Color(190, 190, 195, 255), bold=on_t)
        y = y0
        for i, r in enumerate(rows):
            if r.kind == "head":
                y += 6
                font.draw_text(r.label.upper(), x0, y + 4, 16, rl.Color(130, 170, 220, 255))
                if r.label:
                    rl.draw_line(x0 + 150, y + rh // 2, x0 + pw, y + rh // 2, rl.Color(60, 70, 90, 255))
                y += rh
                continue
            on = i == sel
            if on:
                rl.draw_rectangle(x0 - 8, y, pw + 16, rh, rl.Color(40, 46, 62, 255))
            col = rl.Color(255, 255, 255, 255) if on else rl.Color(205, 205, 205, 255)
            if r.kind == "action":
                font.draw_text(("> " if on else "  ") + r.label, x0, y + 4, 22 if r.key in ("play", "chars", "quit") else 20,
                               GOLD if r.key == "play" else col)
            else:
                font.draw_text(r.label, x0, y + 4, 20, col)
                vx = x0 + int(pw * 0.5)
                if r.kind == "choice" and not r.bar:
                    font.draw_text(f"<  {r.options[cfg[r.key]]}  >", vx, y + 4, 20, GOLD if on else col)
                elif r.kind == "toggle":
                    font.draw_text(TXT("menu.0060") if cfg[r.key] else TXT("menu.0061"), vx, y + 4, 20, rl.Color(120, 220, 120, 255) if cfg[r.key] else rl.Color(220, 120, 120, 255))
                else:
                    if r.kind == "choice":
                        f, txt = cfg[r.key] / max(1, len(r.options) - 1), r.options[cfg[r.key]]
                    else:
                        f, txt = (cfg[r.key] - r.lo) / (r.hi - r.lo), r.fmt(cfg[r.key])
                    rl.draw_rectangle(vx, y + 9, bw, 10, rl.Color(50, 52, 58, 255))
                    rl.draw_rectangle(vx, y + 9, int(bw * f), 10, GOLD if on else rl.Color(170, 150, 70, 255))
                    font.draw_text(txt, vx + bw + 10, y + 4, 18, col)
            y += rh
        if rows[sel].note:
            font.draw_text(rows[sel].note, x0, H - 84, 17, rl.Color(170, 190, 220, 255))
        if flash and time.time() - flash_t < 2.5:
            font.draw_text(flash, x0 + pw - font.measure_text(flash, 20, True), 24, 20, rl.Color(120, 220, 120, 255), bold=True)
        font.draw_text(TXT("menu.0062"),
                     x0, H - 30, 15, rl.Color(150, 150, 160, 255))
        label = "Зачувај и затвори" if in_game else (BACK if settings_only else "Играј")
        bwid, bx, by = font.measure_text(label, 20, True) + 40, x0 + pw - font.measure_text(label, 20, True) - 40, H - 62
        over = bx <= m.x < bx + bwid and by <= m.y < by + 30
        rl.draw_rectangle(bx, by, bwid, 30, GOLD if over else rl.Color(170, 140, 40, 255))
        font.draw_text(label, bx + 20, by + 4, 20, rl.Color(20, 20, 20, 255), bold=True)
        if over and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            cfg.save()
            return "play"
        if settings_only and music is not None and x0 - 24 - 110 > 60:      # beside the panel, if there is room
            music.widget(x=12, y=10, keys=False, room=min(360, x0 - 24 - 110))
        font.exit_button()
        rl.end_drawing()
