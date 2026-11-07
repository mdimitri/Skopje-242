"""Multiplayer screens: username -> game list (LAN + internet) -> room (players, chat, spawn place, friendly fire, start).

run(prof, aud, music) -> mp.Session in state "playing" (host pressed Start), or None when the player backed out.
"""
import time

import pyray as rl

import font
import mp
import places
import profile
import present

GOLD = rl.Color(240, 200, 60, 255)
PINK = rl.Color(226, 32, 104, 255)
DIM = rl.Color(150, 150, 165, 255)
PLACES = [p[0] for p in places.FALLBACK]
L = {"title": "МУЛТИПЛЕЈЕР", "name": "Твоето корисничко име", "name_hint": "Внеси име и притисни Enter", "host": "ДОМАЌИНИ ИГРА",
     "back": "Назад", "none": "Нема најдени игри... (бараме по мрежа и интернет)", "players": "Играчи", "chat": "Разговор",
     "say": "Напиши порака и Enter...", "spawn": "Почетна локација", "ff": "Пријателски оган", "on": "ВКЛ", "off": "ИСКЛ",
     "start": "ПОЧНИ", "wait": "Домаќинот ќе ја почне играта", "connecting": "Се поврзува...", "rename": "Смени име",
     "stats": "Игри %d · Убиства %d · Смрти %d", "color": "Боја", "join": "Приклучи се", "full": "полна", "offline": "интернет: нема врска"}


def _text_input(buf, maxlen):
    while True:
        c = rl.get_char_pressed()
        if not c:
            break
        if c >= 32 and len(buf) < maxlen:
            buf += chr(c)
    if rl.is_key_pressed(rl.KEY_BACKSPACE) or rl.is_key_pressed_repeat(rl.KEY_BACKSPACE):
        buf = buf[:-1]
    return buf


def _panel(x, y, w, h):
    rl.draw_rectangle(int(x), int(y), int(w), int(h), rl.Color(22, 24, 34, 235))
    rl.draw_rectangle_lines(int(x), int(y), int(w), int(h), rl.Color(110, 112, 128, 255))


def _frame(title):
    W, H = rl.get_screen_width(), rl.get_screen_height()
    rl.begin_drawing()
    rl.clear_background(rl.Color(12, 14, 20, 255))
    font.draw_text(title, 40, 28, max(28, H // 20), GOLD, bold=True)
    font.seal(W - 70, 60)
    return W, H


def _ask_name(prof, music):
    buf = prof.name
    while True:
        if rl.window_should_close():
            return False
        if music:
            music.update()
        buf = _text_input(buf, 16)
        W, H = _frame(L["title"])
        sz = max(22, H // 32)
        font.draw_text(L["name"], W // 2 - 260, H // 3, sz, rl.WHITE, bold=True)
        _panel(W // 2 - 260, H // 3 + sz * 2, 520, sz * 2)
        font.draw_text(buf + ("_" if int(time.time() * 2) % 2 else ""), W // 2 - 245, H // 3 + sz * 2 + sz // 2, sz, rl.WHITE)
        font.draw_text(L["name_hint"], W // 2 - 260, H // 3 + sz * 4.4, sz * 3 // 4, DIM)
        ok = font.button("OK", W // 2 - 260, H // 3 + sz * 6, 250, sz * 2, sz)
        bk = font.button(L["back"], W // 2 + 10, H // 3 + sz * 6, 250, sz * 2, sz)
        rl.end_drawing()
        if bk or rl.is_key_pressed(rl.KEY_ESCAPE):
            return False
        if (ok or rl.is_key_pressed(rl.KEY_ENTER)) and profile.clean(buf):
            prof.name = profile.clean(buf)
            prof.save()
            return True


def _browser(prof, ses, music):
    """-> 'host' | 'joined' | 'rename' | None"""
    ses.browse()
    while True:
        if rl.window_should_close():
            return None
        if music:
            music.update()
        ses.update()
        if ses.state == "connecting" or ses.state == "lobby":
            if ses.state == "lobby":
                return "joined"
        W, H = _frame(L["title"])
        sz = max(20, H // 38)
        font.draw_text("%s: %s" % (L["name"], prof.name), 40, 28 + H // 14, sz, rl.WHITE, bold=True)
        font.draw_text(L["stats"] % (prof.stats["games"], prof.stats["kills"], prof.stats["deaths"]), 40, 28 + H // 14 + sz * 1.4, sz * 4 // 5, DIM)
        x0, y0, pw = 40, H // 4, W - 80
        _panel(x0, y0, pw, H * 0.5)
        games = sorted(ses.games().values(), key=lambda g: g.get("name", ""))
        if ses.state == "connecting":
            font.draw_text(L["connecting"], x0 + 20, y0 + 20, sz, GOLD, bold=True)
        elif not games:
            font.draw_text(L["none"], x0 + 20, y0 + 20, sz, DIM)
        if ses.error:
            font.draw_text(ses.error, x0 + 20, y0 + H * 0.5 - sz * 2, sz, rl.Color(255, 120, 140, 255), bold=True)
        if ses.state != "connecting":
            if ses.mqtt and not ses.mqtt.connected:
                font.draw_text(L["offline"], x0 + pw - font.measure_text(L["offline"], sz * 4 // 5) - 10, y0 + H * 0.5 - sz * 1.6, sz * 4 // 5, DIM)
            for i, g in enumerate(games[:8]):
                ry = y0 + 12 + i * sz * 2.1
                full = g.get("n", 0) >= g.get("max", 4)
                font.draw_text("%s%s   %d/%d" % (g.get("name", "?"), "  [LAN]" if g.get("lan") else "", g.get("n", 0), g.get("max", 4)),
                               x0 + 20, ry + sz * 0.3, sz, DIM if full else rl.WHITE, bold=True)
                if not full and font.button(L["join"], x0 + pw - 220, ry, 200, sz * 1.9, sz * 4 // 5):
                    ses.error = ""
                    ses.join(g)
        by = H - H // 7
        out = False
        if font.button(L["host"], 40, by, 340, sz * 2.4, sz):
            out = "host"
        if font.button(L["rename"], 400, by, 250, sz * 2.4, sz):
            out = "rename"
        if font.button(L["back"], W - 290, by, 250, sz * 2.4, sz) or rl.is_key_pressed(rl.KEY_ESCAPE):
            out = None
        rl.end_drawing()
        if out is not False:
            return out
        if ses.state == "closed" and ses.net:        # a failed join: tidy up, stay on this screen, keep the message
            err = ses.error
            ses.net.close()
            ses.net, ses.state = None, "idle"
            ses.error = err


def _room(prof, ses, music):
    """-> True when the game starts."""
    chat = ""
    while True:
        if rl.window_should_close():
            return False
        if music:
            music.update()
        ses.update()
        if ses.state == "playing":
            return True
        if ses.state == "closed":
            return False
        chat = _text_input(chat, 100)
        host = ses.role == "host"
        W, H = _frame(L["title"] + (" · " + prof.name))
        sz = max(20, H // 38)
        top, pw = H // 7, W // 2 - 50
        _panel(40, top, pw, H * 0.34)
        font.draw_text(L["players"], 55, top + 8, sz, GOLD, bold=True)
        for i, (pid, p) in enumerate(sorted(ses.players.items())):
            y = top + 12 + sz * 1.6 * (i + 1)
            rl.draw_circle(70, int(y + sz / 2), sz // 2, rl.Color(*mp.COLORS[p["color"] % 4], 255))
            font.draw_text(p["name"] + ("  (домаќин)" if pid == 0 else ""), 95, y, sz, rl.WHITE, bold=(pid == ses.pid))
        # colour picker (click a free colour)
        font.draw_text(L["color"], 55, top + H * 0.34 - sz * 1.9, sz * 4 // 5, DIM)
        taken = {p["color"] for p in ses.players.values()}
        for c in range(4):
            cx, cy = 55 + font.measure_text(L["color"], sz * 4 // 5) + 25 + c * sz * 1.6, top + H * 0.34 - sz * 1.5
            m = rl.get_mouse_position()
            hot = (m.x - cx) ** 2 + (m.y - cy) ** 2 < (sz * 0.6) ** 2
            rl.draw_circle(int(cx), int(cy), int(sz * 0.55), rl.Color(*mp.COLORS[c], 255 if c not in taken else 70))
            if hot and c not in taken and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                ses.set_color(c)
        # settings
        sx = W // 2 + 10
        _panel(sx, top, W - sx - 40, H * 0.34)
        font.draw_text(L["spawn"], sx + 15, top + 8, sz, GOLD, bold=True)
        sp = ses.cfg["spawn"] % len(PLACES)
        font.draw_text(PLACES[sp], sx + 15, top + 12 + sz * 1.7, sz * 6 // 5, rl.WHITE, bold=True)
        font.draw_text("%s: %s" % (L["ff"], L["on"] if ses.cfg["ff"] else L["off"]), sx + 15, top + 12 + sz * 3.6, sz, rl.WHITE, bold=True)
        if host:
            bw = sz * 2.2
            if font.button("<", sx + 15, top + 12 + sz * 5.2, bw, sz * 1.8, sz):
                ses.set_cfg(spawn=(sp - 1) % len(PLACES))
            if font.button(">", sx + 25 + bw, top + 12 + sz * 5.2, bw, sz * 1.8, sz):
                ses.set_cfg(spawn=(sp + 1) % len(PLACES))
            if font.button(L["ff"], sx + 45 + bw * 2, top + 12 + sz * 5.2, sz * 9, sz * 1.8, sz * 4 // 5):
                ses.set_cfg(ff=not ses.cfg["ff"])
        else:
            font.draw_text(L["wait"], sx + 15, top + 12 + sz * 5.4, sz * 4 // 5, DIM)
        # chat
        cy0 = top + H * 0.34 + 14
        ch = H - cy0 - H // 6
        _panel(40, cy0, W - 80, ch)
        lines = []
        for pid, t in ses.chat:
            nm = ses.players.get(pid, {"name": "?", "color": 0})
            lines.append((nm["color"], "%s: %s" % (nm["name"], t)))
        rows = max(1, int((ch - sz * 2.4) / (sz * 1.25)))
        for i, (col, t) in enumerate(lines[-rows:]):
            font.draw_text(font.fit(t, sz, W - 120), 55, cy0 + 8 + i * sz * 1.25, sz, rl.Color(*mp.COLORS[col % 4], 255))
        rl.draw_rectangle(48, int(cy0 + ch - sz * 1.9), W - 96, int(sz * 1.6), rl.Color(40, 42, 56, 255))
        font.draw_text(chat + ("_" if int(time.time() * 2) % 2 else "") if chat else L["say"], 58, cy0 + ch - sz * 1.75, sz, rl.WHITE if chat else DIM)
        if rl.is_key_pressed(rl.KEY_ENTER) and chat.strip():
            ses.send_chat(chat)
            chat = ""
        by = H - H // 7 + 10
        if host and font.button(L["start"], 40, by, 300, sz * 2.4, sz):
            ses.start()
        leave = font.button(L["back"], W - 290, by, 250, sz * 2.4, sz) or rl.is_key_pressed(rl.KEY_ESCAPE)
        rl.end_drawing()
        if leave:
            return False


def run(prof, aud=None, music=None):
    present.off()
    if not prof.name and not _ask_name(prof, music):
        return None
    ses = mp.Session(prof)
    try:
        while True:
            go = _browser(prof, ses, music)
            if go == "rename":
                _ask_name(prof, music)
                continue
            if go is None:
                return None
            if go == "host":
                ses.host()
            if _room(prof, ses, music):
                return ses
            if rl.window_should_close():
                return None
            ses.leave()
            ses = mp.Session(prof)
    finally:
        if ses.state != "playing":
            ses.leave()
