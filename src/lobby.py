"""Multiplayer screens: username -> game list (LAN + internet) -> room (players, chat, spawn place, friendly fire, start).

run(prof, aud, music) -> mp.Session in state "playing" (host pressed Start), or None when the player backed out.
"""
import time

import pyray as rl

import font
import mp
import places
import mpprofile as profile
import present
import voice

GOLD = rl.Color(240, 200, 60, 255)
PINK = rl.Color(226, 32, 104, 255)
DIM = rl.Color(150, 150, 165, 255)
PLACES = [p[0] for p in places.FALLBACK]
L = {"title": "МУЛТИПЛЕЈЕР", "name": "Твоето корисничко име", "name_hint": "Внеси име и притисни Enter", "host": "Направи игра",
     "back": "Назад", "none": "Нема најдени игри... (бараме по мрежа и интернет)", "players": "Играчи", "chat": "Разговор",
     "say": "Напиши порака и Enter...", "spawn": "Почетна локација", "ff": "Пријателски оган", "on": "ВКЛ", "off": "ИСКЛ",
     "start": "ПОЧНИ", "wait": "Домаќинот ќе ја почне играта", "connecting": "Се поврзува...", "rename": "Смени име",
     "stats": "Игри %d · Убиства %d · Смрти %d", "color": "Боја", "join": "Приклучи се", "full": "полна", "offline": "интернет: нема врска",
     "mute": "Тивко", "unmute": "Звук", "mic": "Микрофон", "gain": "Засил.", "vmode": "Глас", "talk": "Држи за зборување"}
GREEN = rl.Color(90, 220, 110, 255)
RED = rl.Color(255, 120, 140, 255)


def ptt_held(cfg, typing=False):
    """Push-to-talk key from Поставки → Звук (a letter key is ignored while typing a chat message)."""
    k = (cfg or {}).get("voice_ptt", 0)
    if k == 0:
        return not typing and rl.is_key_down(rl.KEY_V)
    if k == 1:
        return rl.is_key_down(rl.KEY_LEFT_ALT)
    if k == 2:
        return rl.is_key_down(rl.KEY_CAPS_LOCK)
    return rl.is_mouse_button_down(rl.MOUSE_BUTTON_MIDDLE)


def draw_voice_hud(ses, W, H):
    """In game: who is talking right now, and my microphone when it does not work."""
    v = getattr(ses, "voice", None) if ses is not None else None
    if v is None:
        return
    sz = max(16, H // 50)
    x, y = 20, H // 3
    if v.talking:
        font.draw_text("● " + ses.players.get(ses.pid, {}).get("name", ""), x, y, sz, GREEN, bold=True)
        y += sz * 1.3
    for pid, p in sorted(ses.players.items()):
        if pid != ses.pid and v.speaking(pid):
            font.draw_text("◄ " + p["name"], x, y, sz, rl.Color(*mp.COLORS[p["color"] % 4], 255), bold=True)
            y += sz * 1.3
    if v.ins is None and v.cfg.get("voice_on", True):
        font.draw_text(font.fit("Глас: " + v.mic_line(), sz * 4 // 5, W // 2), x, y, sz * 4 // 5, RED)


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
                a = g.get("addr") or ["?", 0]
                font.draw_text("%s:%s · %s · v%s" % (a[0], a[1], "LAN" if g.get("lan") else "интернет", g.get("ver", "?")),
                               x0 + 20, ry + sz * 1.25, sz * 3 // 5, DIM)
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


def _voice_cfg(cfg, v):
    v.apply(cfg)
    try:
        cfg.save()
    except AttributeError:
        pass


def _room(prof, ses, music, cfg=None):
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
        ph = H * 0.42
        v = ses.voice
        if v is not None:
            v.ptt = ptt_held(cfg, typing=True)
        _panel(40, top, pw, ph)
        font.draw_text(L["players"], 55, top + 8, sz, GOLD, bold=True)
        for i, (pid, p) in enumerate(sorted(ses.players.items())):
            y = top + 12 + sz * 1.6 * (i + 1)
            rl.draw_circle(70, int(y + sz / 2), sz // 2, rl.Color(*mp.COLORS[p["color"] % 4], 255))
            font.draw_text(p["name"] + ("  (домаќин)" if pid == 0 else ""), 95, y, sz, rl.WHITE, bold=(pid == ses.pid))
            if v is None:
                continue
            bx = 40 + pw - sz * 9.5
            if pid == ses.pid:                                     # my mic: level meter, green while sending
                lv = min(1.0, v.level * 3)
                rl.draw_rectangle(int(bx), int(y + sz * .25), int(sz * 9), int(sz * .5), rl.Color(40, 42, 56, 255))
                rl.draw_rectangle(int(bx), int(y + sz * .25), int(sz * 9 * lv), int(sz * .5), GREEN if v.talking else DIM)
                continue
            if v.speaking(pid):
                rl.draw_circle(int(bx - sz * .6), int(y + sz / 2), sz // 3, GREEN)
            vol = v.peer_vol.get(pid, 1.0)
            if font.button(L["unmute"] if vol == 0 else L["mute"], bx, y - sz * .1, sz * 3.4, sz * 1.25, sz * 3 // 5):
                v.peer_vol[pid] = 1.0 if vol == 0 else 0.0
            if font.button("-", bx + sz * 3.6, y - sz * .1, sz * 1.25, sz * 1.25, sz * 3 // 5):
                v.peer_vol[pid] = max(0.0, round(vol - .1, 2))
            font.draw_text("%d%%" % (vol * 100), bx + sz * 5, y, sz * 3 // 4, rl.WHITE)
            if font.button("+", bx + sz * 7.6, y - sz * .1, sz * 1.25, sz * 1.25, sz * 3 // 5):
                v.peer_vol[pid] = min(2.0, round(vol + .1, 2))
        if v is not None:                                        # voice diagnostics: my mic, quality, and both directions per player
            vl = [("Мој микрофон", v.mic_line()), ("Квалитет", v.quality_line())]
            if v.out_err:
                vl.append(("Звучници", v.out_err))
            for pid, p in sorted(ses.players.items()):
                if pid != ses.pid:
                    hear, them = ses.voice_report(pid)
                    vl += [("← " + p["name"], hear), ("→ " + p["name"], them)]
            isz = max(13, sz * 3 // 5)
            vy = top + 12 + sz * 1.6 * (len(ses.players) + 1) + sz * .4
            for k, val in vl:
                if vy > top + ph - sz * 2.6:
                    break
                bad = val.startswith(("нема", "НЕ", "микрофонот", "пристап", "изб", "излез", "PortAudio", "грешка")) or "НЕ ПРИМА" in val
                font.draw_text(k, 55, vy, isz, DIM)
                font.draw_text(font.fit(val, isz, pw - 150), 55 + isz * 8, vy, isz, RED if bad else rl.WHITE)
                vy += isz * 1.3

        font.draw_text(L["color"], 55, top + ph - sz * 1.9, sz * 4 // 5, DIM)
        taken = {p["color"] for p in ses.players.values()}
        for c in range(4):
            cx, cy = 55 + font.measure_text(L["color"], sz * 4 // 5) + 25 + c * sz * 1.6, top + ph - sz * 1.5
            m = rl.get_mouse_position()
            hot = (m.x - cx) ** 2 + (m.y - cy) ** 2 < (sz * 0.6) ** 2
            rl.draw_circle(int(cx), int(cy), int(sz * 0.55), rl.Color(*mp.COLORS[c], 255 if c not in taken else 70))
            if hot and c not in taken and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                ses.set_color(c)
        # settings
        sx = W // 2 + 10
        _panel(sx, top, W - sx - 40, ph)
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
        if v is not None and cfg is not None:                    # voice: microphone, gain, mode (also in Поставки → Звук)
            vy, bh, fs = top + 12 + sz * 7.4, sz * 1.5, sz * 3 // 4
            names = voice.input_names()
            cur = names.index(cfg["voice_mic"]) if cfg.get("voice_mic") in names else 0
            if font.button("%s: %s" % (L["mic"], font.fit(names[cur], fs, W - sx - 120)), sx + 15, vy, W - sx - 70, bh, fs):
                cfg["voice_mic"] = "" if (cur + 1) % len(names) == 0 else names[(cur + 1) % len(names)]
                _voice_cfg(cfg, v)
            vy += bh + 6
            g = cfg.get("voice_gain", 1.0)
            if font.button("-", sx + 15, vy, bh, bh, fs):
                cfg["voice_gain"] = max(0.0, round(g - .1, 2))
                _voice_cfg(cfg, v)
            font.draw_text("%s %d%%" % (L["gain"], g * 100), sx + 25 + bh, vy + bh * .2, fs, rl.WHITE)
            if font.button("+", sx + 25 + bh + sz * 6, vy, bh, bh, fs):
                cfg["voice_gain"] = min(4.0, round(g + .1, 2))
                _voice_cfg(cfg, v)
            mx = sx + 45 + bh * 2 + sz * 6
            if font.button("%s: %s" % (L["vmode"], font.fit(voice.MODES[cfg.get("voice_mode", 0) % 3], fs, W - mx - 70)), mx, vy, W - mx - 55, bh, fs):
                cfg["voice_mode"] = (cfg.get("voice_mode", 0) + 1) % 3
                _voice_cfg(cfg, v)
            if cfg.get("voice_mode", 0) == 1:
                hold = font.button(L["talk"] + " (" + voice.PTT_KEYS[cfg.get("voice_ptt", 0) % 4] + ")", sx + 15, vy + bh + 6, W - sx - 70, bh, fs)
                m = rl.get_mouse_position()
                v.ptt = v.ptt or (rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT) and sx + 15 <= m.x < W - 55 and vy + bh + 6 <= m.y < vy + bh * 2 + 6) or hold
        # chat
        cy0 = top + ph + 14
        ch = H - cy0 - H // 6
        _panel(40, cy0, W - 80, ch)
        lines = []
        for pid, t in ses.chat:
            nm = ses.players.get(pid, {"name": "?", "color": 0})
            lines.append((nm["color"], "%s: %s" % (nm["name"], t)))
        rows = max(1, int((ch - sz * 2.4) / (sz * 1.25)))
        for i, (col, t) in enumerate(lines[-rows:]):
            font.draw_text(font.fit(t, sz, W // 2 - 90), 55, cy0 + 8 + i * sz * 1.25, sz, rl.Color(*mp.COLORS[col % 4], 255))
        isz = max(14, sz * 3 // 4)
        info = ses.info()
        maxrows = max(1, int((ch - sz * 2.4) / (isz * 1.3)))
        for i, (k, val) in enumerate(info[:maxrows]):
            iy = cy0 + 8 + i * isz * 1.3
            font.draw_text(k, W // 2 + 10, iy, isz, DIM)
            font.draw_text(font.fit(val, isz, W // 2 - 60 - W // 6), W // 2 + W // 6 + 10, iy, isz, rl.WHITE)
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


def run(prof, aud=None, music=None, cfg=None):
    present.off()
    if not prof.name and not _ask_name(prof, music):
        return None
    vc = voice.Voice(cfg)
    vc.start()
    ses = mp.Session(prof)
    ses.voice = vc
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
            if _room(prof, ses, music, cfg):
                return ses
            if rl.window_should_close():
                return None
            ses.leave()
            ses = mp.Session(prof)
            ses.voice = vc
    finally:
        if ses.state != "playing":
            ses.leave()
            vc.close()
