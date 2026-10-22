"""Options / pause menu.  Keyboard (arrows, Enter, Esc) and mouse (hover, click, drag sliders)."""
import os
import time

import pyray as rl
import font   # noqa: E402

import characters as C
import poster
import settings as S

GOLD = rl.Color(240, 200, 60, 255)
_T = {}


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


TABS = ["Приказ", "Камера", "Звук", "Свет", "Мапа", "Игра"]


def _rows(in_game, slots=()):
    """-> list of (tab, Row)."""
    pct = lambda v: f"{int(v * 100)}%"
    xz = lambda v: f"{v:.2f}x".replace(".", ",")
    spd = ["запрено", "0,25x", "0,5x", "1x", "2x", "4x", "8x", "16x"]
    dens = [f"{d:g}x".replace(".", ",") for d in S.DENSITY]
    R = [
        (0, Row("choice", "Големина на прозорецот", "res", [f"{w} x {h}" for w, h in S.RESOLUTIONS])),
        (0, Row("toggle", "Цел екран", "fullscreen")),
        (0, Row("choice", "Детали", "detail", S.DETAIL, note="сенки, натписи, честички, светла")),
        (0, Row("toggle", "Смог", "smog", note="скопскиот воздух, најгуст наутро и навечер")),
        (0, Row("toggle", "Имиња на улици и места", "labels")),
        (1, Row("slider", "Зум кога пешачиш", "zoom_walk", lo=0.4, hi=2.4, fmt=xz, note="колесцето на глувчето го менува привремено")),
        (1, Row("slider", "Зум кога возиш", "zoom_car", lo=0.4, hi=2.4, fmt=xz)),
        (1, Row("slider", "Тресење на екранот", "shake", lo=0.0, hi=2.0, fmt=pct)),
        (2, Row("slider", "Општа јачина", "vol_master", fmt=pct)),
        (2, Row("slider", "Ефекти", "vol_sfx", fmt=pct)),
        (2, Row("slider", "Мотори", "vol_engine", fmt=pct)),
        (2, Row("slider", "Амбиент", "vol_ambient", fmt=pct)),
        (2, Row("slider", "Говор", "vol_speech", fmt=pct)),
        (2, Row("slider", "Радио", "vol_radio", fmt=pct)),
        (2, Row("choice", "Гласовен мотор", "voice", S.VOICES)),
        (2, Row("choice", "Брзина на говорот", "speech_speed", [f"{v:g}x".replace(".", ",") for v in S.SPEECH_SPEEDS], bar=True)),
        (3, Row("slider", "Време од денот", "hour", lo=0.0, hi=23.99, fmt=lambda v: f"{int(v):02d}:{int((v % 1) * 60):02d}")),
        (3, Row("choice", "Брзина на времето", "time_speed", spd, bar=True, note="колку брзо тече денот")),
        (3, Row("choice", "Густина на сообраќај", "traffic", dens, bar=True)),
        (3, Row("choice", "Густина на пешаци", "peds", dens, bar=True)),
        (3, Row("choice", "Агресивност", "aggro", S.AGGRO, bar=True, note="колку брзо се караат и тепаат")),
        (3, Row("choice", "Јазик", "lang", S.LANGUAGE, bar=True, note="пцовки и груби зборови")),
        (3, Row("toggle", "Брзата помош ги оживува паднатите", "ambulance")),
        (3, Row("toggle", "Пожарникарите гаснат запалени коли", "fire")),
        (4, Row("choice", "Извор при преземање", "osm_source", S.MAP_SOURCES, note="важи за следното преземање")),
    ]
    g = [Row("action", "Продолжи" if in_game else "Играј", "play")]
    if in_game:
        g += [Row("head", "Зачувај"), *[Row("action", f"Слот {n}:  {slots[n - 1]}", f"save{n}") for n in range(1, len(slots) + 1)]]
    g += [Row("head", "Вчитај"), *[Row("action", f"Слот {n}:  {slots[n - 1]}", f"load{n}") for n in range(1, len(slots) + 1)]]
    if in_game:
        g += [Row("head", ""), Row("action", "Назад на избор на лик", "chars")]
    g += [Row("action", "Излез од играта", "quit")]
    return R + [(5, r) for r in g]


def _title_card(seconds=6.0):
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
            txt = "Притисни било кое копче"
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


def pick_character(cfg, aud=None):
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
        if armed and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and W - 230 <= m.x < W - 20 and 20 <= m.y < 60:
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
        font.draw_text("Избери лик", 24, 20, 40, GOLD, bold=True)
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
        font.draw_text(f"{name}  –  {money} ден. на старт", 24, by, 26, GOLD, bold=True)
        for k, ln in enumerate(font.wrap(stats, 19, W - 48)[:2]):
            font.draw_text(ln, 24, by + 36 + k * 25, 19, rl.Color(225, 225, 230, 255))
        rl.draw_rectangle(W - 230, 20, 210, 40, rl.Color(48, 54, 72, 255))
        font.draw_text("L  Вчитај игра", W - 214, 28, 22, GOLD, bold=True)
        font.draw_text("Стрелки / глушец избери   Enter потврди   L вчитај зачувана игра", 24, H - 26, 16, rl.Color(150, 150, 160, 255))
        font.exit_button()
        rl.end_drawing()


def _first(rows):
    return next((i for i, r in enumerate(rows) if r.kind != "head"), 0)


def run(cfg, apply, in_game=False, draw_bg=None, aud=None, save_fn=None):
    """Blocks until the player resumes or quits. `apply(cfg)` is called after every change; `save_fn(slot)` saves the game.
    -> 'play' | 'quit' | 'chars' (back to the character screen) | 'load1'..'load5'"""
    import savegame
    tab, flash, flash_t = 0, "", 0.0
    # (the poster title card is gone: the 3D loading showcase is the only splash)
    if not in_game:                      # start: title card + character choice, then straight into the game
        pick_character.load = False
        if pick_character(cfg, aud):
            return "quit"
        cfg.save()
        if not pick_character.load:
            return "play"
        tab = len(TABS) - 1
    slots = [savegame.summary(n) for n in range(1, savegame.SLOTS + 1)]
    allrows = _rows(in_game, slots)
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
        rh = max(24, min(34, (H - 190) // max(len(rows), 1)))
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
            if k in ("quit", "chars"):
                cfg.save()
                return k
            if k.startswith("load"):
                if savegame.read(int(k[4:])):
                    cfg.save()
                    return k
                flash, flash_t = "Слотот е празен.", time.time()
            elif k.startswith("save") and save_fn is not None:
                n = int(k[4:])
                ok = save_fn(n)
                flash, flash_t = ("Зачувано во слот %d." % n) if ok else "Не успеав да зачувам.", time.time()
                slots = [savegame.summary(i) for i in range(1, savegame.SLOTS + 1)]
                allrows = _rows(in_game, slots)
                rows = [x for t, x in allrows if t == tab]
        if rl.is_key_pressed(rl.KEY_ESCAPE) and in_game and frames > 1:   # the Esc that opened the menu must not close it
            cfg.save()
            return "play"
        if changed:
            apply(cfg)
        # ---- draw
        rl.begin_drawing()
        if not in_game and _title() is not None:
            poster.draw_fit(_title(), 0, 0, W, H, 255, cover=True)
            rl.draw_rectangle(0, 0, W, H, rl.Color(10, 12, 18, 228))
        elif draw_bg:
            draw_bg()
            rl.draw_rectangle(0, 0, W, H, rl.Color(10, 12, 18, 215))
        else:
            rl.clear_background(rl.Color(22, 24, 28, 255))
        font.draw_text("СКОПЈЕ GTA", x0, 20, 40, GOLD, bold=True)
        font.draw_text("Опции", x0 + 310, 34, 24, rl.Color(190, 190, 190, 255))
        for i, name in enumerate(TABS):
            tx = x0 + i * tw
            on_t = i == tab
            rl.draw_rectangle(tx + 2, 72, tw - 4, 34, rl.Color(48, 54, 72, 255) if on_t else rl.Color(26, 30, 40, 255))
            if on_t:
                rl.draw_rectangle(tx + 2, 104, tw - 4, 3, GOLD)
            lw = font.measure_text(name, 20, on_t)
            font.draw_text(name, tx + (tw - lw) // 2, 78, 20, GOLD if on_t else rl.Color(190, 190, 195, 255), bold=on_t)
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
                    font.draw_text("ВКЛ" if cfg[r.key] else "ИСКЛ", vx, y + 4, 20, rl.Color(120, 220, 120, 255) if cfg[r.key] else rl.Color(220, 120, 120, 255))
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
            font.draw_text(rows[sel].note, x0, H - 56, 17, rl.Color(170, 190, 220, 255))
        if flash and time.time() - flash_t < 2.5:
            font.draw_text(flash, x0 + pw - font.measure_text(flash, 20, True), 24, 20, rl.Color(120, 220, 120, 255), bold=True)
        font.draw_text("Tab табови   Горе/Долу избери   Лево/Десно промени   Enter потврди   глувче   Esc продолжи",
                     x0, H - 30, 15, rl.Color(150, 150, 160, 255))
        font.exit_button()
        rl.end_drawing()
