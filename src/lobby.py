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
import joinwords

GOLD = rl.Color(240, 200, 60, 255)
PINK = rl.Color(226, 32, 104, 255)
DIM = rl.Color(150, 150, 165, 255)
GOOD = rl.Color(90, 210, 110, 255)
PLACES = [p[0] for p in places.FALLBACK]
L = {"title": "МУЛТИПЛЕЈЕР", "name": "Твоето корисничко име", "name_hint": "Внеси име и притисни Enter", "host": "Направи игра",
     "back": "Назад", "none": "Нема најдени игри... (бараме по мрежа и интернет)", "players": "Играчи", "chat": "Разговор",
     "say": "Напиши порака и Enter...", "spawn": "Почетна локација", "ff": "Пријателски оган", "on": "ВКЛ", "off": "ИСКЛ",
     "start": "ПОЧНИ", "wait": "Домаќинот ќе ја почне играта", "connecting": "Се поврзува...", "rename": "Смени име",
     "stats": "Игри %d · Убиства %d · Смрти %d", "color": "Боја", "join": "Приклучи се", "full": "полна", "offline": "интернет: нема врска",
     "code": "Внеси код", "code_t": "Код за поврзување", "copy": "Копирај код", "copy_long": "Копирај долг код", "copied": "Копирано! Испрати го (WhatsApp, Viber...)",
     "code_hint": "Залепи го кодот од домаќинот (Ctrl+V) или внеси IP:порта, па Enter", "paste": "Залепи", "code_wait": "кодот се прави (се бара јавна адреса)…",
     "ready": "Спремен", "notready": "Не е спремен", "unready": "Откажи", "readybtn": "СПРЕМЕН", "waitfor": "Чека: %s",
     "lock": "Заклучи собата", "unlock": "Отклучи собата", "locked": "заклучена", "running": "игра во тек", "ingame": "во игра",
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


def draw_voice_hud(ses, W, H, x0=20):
    """In game: who is talking right now, and my microphone when it does not work."""
    v = getattr(ses, "voice", None) if ses is not None else None
    if v is None:
        return
    sz = max(16, H // 50)
    x, y = x0, H // 3
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
                full = g.get("n", 0) >= g.get("max", 4) or bool(g.get("lock"))
                font.draw_text("%s%s   %d/%d" % (g.get("name", "?"), ("  [LAN]" if g.get("lan") else "") + ("  [%s]" % L["locked"] if g.get("lock") else "") + ("  [%s]" % L["running"] if g.get("st") == "playing" else ""), g.get("n", 0), g.get("max", 4)),
                               x0 + 20, ry + sz * 0.3, sz, DIM if full else rl.WHITE, bold=True)
                a = g.get("addr") or ["?", 0]
                font.draw_text("%s:%s · %s · v%s" % (a[0], a[1], "LAN" if g.get("lan") else "интернет", g.get("ver", "?")),
                               x0 + 20, ry + sz * 1.25, sz * 3 // 5, DIM)
                if not full and font.button(L["join"], x0 + pw - 220, ry, 200, sz * 1.9, sz * 4 // 5):
                    ses.error = ""
                    ses.join(g)
        by = H - H // 7
        out = False
        last = getattr(prof, "last", None) or {}
        if ses.state != "connecting" and (last.get("word") or last.get("code")):     # quick join of the last game
            lab = "Последна игра: %s %s" % (last.get("name", ""), ("· " + last["word"].upper()) if last.get("word") else "")
            ly = y0 + H * 0.5 + 10
            font.draw_text(lab, x0 + 4, ly + sz * .35, sz * 4 // 5, DIM)
            if font.button("Брзо приклучување", x0 + pw - 330, ly, 330, sz * 1.8, sz * 4 // 5):
                out = "quick"
        bw5 = (W - 80 - 4 * 14) / 5
        bx5 = [40 + i * (bw5 + 14) for i in range(5)]
        if font.button(L["host"], bx5[0], by, bw5, sz * 2.4, sz):
            out = "host"
        if font.button(L["rename"], bx5[1], by, bw5, sz * 2.4, sz):
            out = "rename"
        if ses.state != "connecting" and font.button(L["code"], bx5[2], by, bw5, sz * 2.4, sz):
            out = "code"
        if ses.state != "connecting" and font.button("Тест на врската", bx5[3], by, bw5, sz * 2.4, sz * 4 // 5):
            out = "test"
        if font.button(L["back"], bx5[4], by, bw5, sz * 2.4, sz) or rl.is_key_pressed(rl.KEY_ESCAPE):
            out = None
        rl.end_drawing()
        if out == "quick":
            g = None
            if last.get("word"):
                g, why = _find_word(ses, joinwords.slug(last["word"]), last["word"], music)
            if not g and last.get("code"):            # the word is gone (new game, new word): try the long code
                try:
                    g = mp.parse_code(last["code"])
                except ValueError:
                    g = None
            if g:
                ses.error = ""
                ses.join(g)
            else:
                ses.error = "Последната игра не е отворена сега (домаќинот мора да е во собата)"
            continue
        if out == "test":
            _selftest(ses, music)
            continue
        if out == "code":
            g = _enter_code(ses, music)
            if g:
                ses.error = ""
                ses.join(g)
            continue
        if out is not False:
            return out
        if ses.state == "closed" and ses.net:        # a failed join: tidy up, stay on this screen, keep the message
            err = ses.error
            ses.net.close()
            ses.net, ses.state = None, "idle"
            ses.error = err


def _enter_code(ses, music):
    """Text box for a join code shared privately; -> game dict, or None. The reason a code is wrong shows as you type."""
    buf, err = "", ""
    while True:
        if rl.window_should_close():
            return None
        if music:
            music.update()
        ses.update()
        ctrl = rl.is_key_down(rl.KEY_LEFT_CONTROL) or rl.is_key_down(rl.KEY_RIGHT_CONTROL)
        if ctrl and rl.is_key_pressed(rl.KEY_V):
            buf = (buf + _clip())[:120]
            while rl.get_char_pressed():
                pass
        else:
            buf = _text_input(buf, 120)
        W, H = _frame(L["title"])
        sz = max(22, H // 32)
        font.draw_text(L["code"], W // 2 - 420, H // 3 - sz * 2, sz, rl.WHITE, bold=True)
        _panel(W // 2 - 420, H // 3, 840, sz * 2)
        font.draw_text(font.fit(buf, sz, 800) + ("_" if int(time.time() * 2) % 2 else ""), W // 2 - 405, H // 3 + sz // 2, sz, rl.WHITE)
        font.draw_text(L["code_hint"], W // 2 - 420, H // 3 + sz * 2.4, sz * 3 // 4, DIM)
        ok_code = None
        word = joinwords.slug(buf)
        if word:
            err = ""
            font.draw_text("✓ краток код: Enter за да се најде домаќинот", W // 2 - 420, H // 3 + sz * 3.6, sz * 4 // 5, GREEN, bold=True)
        elif buf.strip():
            try:
                ok_code = mp.parse_code(buf)
                err = ""
            except ValueError as e:
                err = str(e)
        if err:
            font.draw_text(err, W // 2 - 420, H // 3 + sz * 3.6, sz * 4 // 5, RED, bold=True)
        elif ok_code:
            a = ok_code["addr"]
            font.draw_text("✓ %s:%s%s" % (a[0], a[1], "  · реле" if ok_code.get("rid") else ""), W // 2 - 420, H // 3 + sz * 3.6, sz * 4 // 5, GREEN, bold=True)
        y = H // 3 + sz * 5.2
        paste = font.button(L["paste"], W // 2 - 420, y, 260, sz * 2, sz)
        go = font.button(L["join"], W // 2 - 140, y, 260, sz * 2, sz)
        bk = font.button(L["back"], W // 2 + 160, y, 260, sz * 2, sz)
        rl.end_drawing()
        if paste:
            buf = (buf + _clip())[:120]
        if bk or rl.is_key_pressed(rl.KEY_ESCAPE):
            return None
        if (go or rl.is_key_pressed(rl.KEY_ENTER)) and word:
            g, why = _find_word(ses, word, buf.strip(), music)
            if g:
                return g
            err, buf = why, buf
            if why == "back":
                err = ""
            else:
                _show_error(why, music)
        elif (go or rl.is_key_pressed(rl.KEY_ENTER)) and ok_code:
            return ok_code


def _find_word(ses, word, shown, music):
    """Wait for the host with this short code on the notice board. -> (game, "") or (None, reason)."""
    ses.lookup(word)
    t0 = time.time()
    while True:
        if rl.window_should_close():
            return None, "back"
        if music:
            music.update()
        ses.update()
        g = ses.code_hits.get(word)
        if g:
            if g.get("ver") != mp.VER:
                return None, "Домаќинот со „%s“ има друга верзија на играта (v%s, ти v%d): ажурирајте ја" % (shown, g.get("ver"), mp.VER)
            return g, ""
        el = time.time() - t0
        if el > 3 and not (ses.mqtt and ses.mqtt.connected):
            return None, "Интернет-таблата (MQTT) не е достапна: краткиот код не може да се најде. Побарај го долгиот код S242-… од домаќинот"
        if el > 12:
            return None, "Нема игра со кодот „%s“: провери го зборот и бројот; домаќинот мора да е во собата (не во игра)" % shown
        W, H = _frame(L["title"])
        sz = max(22, H // 32)
        font.draw_text("Се бара „%s“ ... %d s" % (shown, el), W // 2 - 420, H // 3, sz, GOLD, bold=True)
        bk = font.button(L["back"], W // 2 - 420, H // 3 + sz * 3, 260, sz * 2, sz)
        rl.end_drawing()
        if bk or rl.is_key_pressed(rl.KEY_ESCAPE):
            return None, "back"


def _show_error(why, music):
    t0 = time.time()
    while time.time() - t0 < 30 and not rl.window_should_close():
        if music:
            music.update()
        W, H = _frame(L["title"])
        sz = max(20, H // 36)
        words, line, y = why.split(" "), "", H // 3
        for w in words:                                  # wrap
            if font.measure_text(line + " " + w, sz) > W - 160:
                font.draw_text(line, 80, y, sz, RED, bold=True)
                line, y = w, y + sz * 1.4
            else:
                line = (line + " " + w).strip()
        font.draw_text(line, 80, y, sz, RED, bold=True)
        ok = font.button("OK", 80, y + sz * 2.5, 260, sz * 2, sz)
        rl.end_drawing()
        if ok or rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_ESCAPE):
            return


def _selftest(ses, music):
    """Connection test: network, DNS, UDP/STUN, NAT type, notice boards, port, microphone and speakers, green / red with tips."""
    import discovery
    import threading
    rows = []
    threading.Thread(target=discovery.selftest, args=(rows,), daemon=True).start()
    while True:
        if rl.window_should_close():
            return
        if music:
            music.update()
        W, H = _frame(L["title"] + " · тест на врската")
        sz = max(18, H // 42)
        y = H // 7
        done = rows and rows[-1] is None
        v = ses.voice
        extra = []
        if v is not None:
            extra = [("Микрофон", v.ins is not None and v.mic_state() == "ok", v.mic_line()),
                     ("Звучници", v.outs is not None, v.out_err or "во ред, %d Hz" % v.out_rate)]
        for r in [r for r in rows if r] + extra:
            label, ok, detail = r
            col = GREEN if ok else (RED if ok is False else GOLD)
            rl.draw_circle(60, int(y + sz / 2), sz // 3, col)
            font.draw_text(label, 80, y, sz, rl.WHITE, bold=True)
            font.draw_text(font.fit(detail, sz * 4 // 5, W - 480), 420, y + sz * .1, sz * 4 // 5, col)
            y += sz * 1.6
        if not done:
            font.draw_text("се проверува" + "." * (int(time.time() * 3) % 4), 80, y, sz, DIM)
        bk = font.button(L["back"], W - 290, H - H // 7, 250, sz * 2.4, sz)
        rl.end_drawing()
        if bk or rl.is_key_pressed(rl.KEY_ESCAPE):
            return


def _clip():
    try:
        t = rl.get_clipboard_text()
        t = t.decode("utf-8", "replace") if isinstance(t, bytes) else (t or "")
        return t.strip().replace("\r", " ").replace("\n", " ")
    except Exception:      # noqa: BLE001 - no clipboard
        return ""


def _voice_cfg(cfg, v):
    v.apply(cfg)
    try:
        cfg.save()
    except AttributeError:
        pass


def _room(prof, ses, music, cfg=None, aud=None):
    """-> True when the game starts."""
    chat, copied = "", 0.0
    while True:
        if rl.window_should_close():
            return False
        if music:
            music.update()
        ses.update()
        ses.chime(aud)
        if ses.state == "playing":
            if ses.voice is not None:
                ses.voice.monitor = False
            return True
        if ses.state == "closed":
            return False
        chat = _text_input(chat, 100)
        host = ses.role == "host"
        W, H = _frame(L["title"] + (" · " + prof.name))
        sz = max(20, H // 38)
        top, pw = H // 7, W // 2 - 50
        info, per = ses.link_info()
        ph = H * 0.42
        v = ses.voice
        if v is not None:
            v.ptt = ptt_held(cfg, typing=True)
        _panel(40, top, pw, ph)
        font.draw_text(L["players"], 55, top + 8, sz, GOLD, bold=True)
        for i, (pid, p) in enumerate(sorted(ses.players.items())):
            y = top + 12 + sz * 1.6 * (i + 1)
            rdy = bool(p.get("ready"))
            bxs = int(sz * 1.0)
            rl.draw_rectangle(52, int(y + sz * .05), bxs, bxs, rl.Color(30, 90, 45, 255) if rdy else rl.Color(40, 42, 56, 255))
            rl.draw_rectangle_lines(52, int(y + sz * .05), bxs, bxs, GREEN if rdy else DIM)
            if rdy:                                                  # drawn check mark (the font has no ✓)
                ck = [(52 + bxs * .2, y + sz * .55), (52 + bxs * .42, y + sz * .8), (52 + bxs * .82, y + sz * .25)]
                for (x1, y1), (x2, y2) in ((ck[0], ck[1]), (ck[1], ck[2])):
                    rl.draw_line_ex(rl.Vector2(x1, y1), rl.Vector2(x2, y2), max(2, sz // 7), GREEN)
            cx_ = 52 + bxs + sz * .9
            rl.draw_circle(int(cx_), int(y + sz / 2), sz // 2, rl.Color(*mp.COLORS[p["color"] % 4], 255))
            nx_ = int(cx_ + sz * .8)
            font.draw_text(p["name"] + ("  (домаќин)" if pid == 0 else ""), nx_, y - sz * .12, sz, GREEN if rdy else rl.WHITE, bold=(pid == ses.pid))
            font.draw_text(L["ready"] if rdy else L["notready"], nx_, y + sz * .82, max(11, sz * 2 // 5), GREEN if rdy else RED)
            if pid in per:                                           # link ping (and the peer address, host only)
                ms, ad = per[pid]
                tag = ("%d ms" % round(ms)) if ms is not None else "… ms"
                isz_ = max(11, sz * 2 // 5)
                font.draw_text(tag + ("  " + ad if host else ""), nx_ + sz * 4.5, y + sz * .82, isz_,
                               DIM if ms is None else (GOOD if ms < 80 else GOLD if ms < 160 else PINK))
            if v is None:
                continue
            bx = 40 + pw - sz * 9.5
            if pid == ses.pid:                                     # my mic: level meter, green while sending
                lv = min(1.0, v.level * 3)
                rl.draw_rectangle(int(bx), int(y + sz * .25), int(sz * 9), int(sz * .5), rl.Color(40, 42, 56, 255))
                rl.draw_rectangle(int(bx), int(y + sz * .25), int(sz * 9 * lv), int(sz * .5), GREEN if v.talking else DIM)
                if cfg is not None and cfg.get("voice_mode", 0) == 0:       # voice activation threshold (rms ~ peak / 3)
                    tx_ = bx + sz * 9 * min(1.0, cfg.get("voice_vad", .02) * 3 * 3)
                    rl.draw_line(int(tx_), int(y), int(tx_), int(y + sz), GOLD)
                if font.button("Слушни се" if not v.monitor else "Стоп тест", bx - sz * 5.2, y - sz * .1, sz * 4.8, sz * 1.25, sz * 3 // 5):
                    v.monitor = not v.monitor
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
        me_rdy = bool(ses.players.get(ses.pid, {}).get("ready"))
        if font.button(L["unready"] if me_rdy else L["readybtn"], 40 + pw - sz * 9.5, top + ph - sz * 2.1, sz * 9, sz * 1.8, sz * 4 // 5):
            ses.set_ready(not me_rdy)
        # settings
        sx = W // 2 + 10
        _panel(sx, top, W - sx - 40, ph)
        font.draw_text(L["spawn"], sx + 15, top + 8, sz, GOLD, bold=True)
        sp = ses.cfg["spawn"] % len(PLACES)
        font.draw_text(PLACES[sp], sx + 15, top + 12 + sz * 1.7, sz * 6 // 5, rl.WHITE, bold=True)
        font.draw_text("%s: %s" % (L["ff"], L["on"] if ses.cfg["ff"] else L["off"]), sx + 15, top + 12 + sz * 3.6, sz, rl.WHITE, bold=True)
        if host:
            lk = bool(ses.cfg.get("lock"))
            if font.button(L["unlock"] if lk else L["lock"], W - 40 - sz * 10.5, top + 6, sz * 10, sz * 1.4, sz * 3 // 5):
                ses.set_lock(not lk)
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
        ly = top + ph + 10
        lh = sz * 0.95 * (len(info) + 0.7)
        _panel(40, ly, W - 80, lh)
        for i, t in enumerate(info):
            font.draw_text(font.fit(t, sz * 4 // 5, W - 110), 55, ly + sz * 0.3 + i * sz * 0.95, sz * 4 // 5, DIM)
        cy0 = ly + lh + 10
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
            ses.start()                                          # only works when everybody is ready
        wt = ses.waiting()
        if wt and ses.players:
            font.draw_text(font.fit(L["waitfor"] % ", ".join(wt), sz * 3 // 5, W - 340), 40, cy0 + ch + 4, sz * 3 // 5, RED)
        if host:                                                 # join code to share privately
            ready = not ses._busy and ses.net is not None
            code = mp.make_code(ses._info()) if ready else ""
            word = ses.word if ses.mqtt and ses.mqtt.connected else ""
            font.draw_text(L["code_t"], 360, by - sz * .2, sz * 3 // 5, DIM)
            if word:
                font.draw_text(word.upper(), 360, by + sz * .4, sz * 6 // 5, GOLD, bold=True)
                wx = 380 + font.measure_text(word.upper(), sz * 6 // 5, True)
                font.draw_text(font.fit("или долг код: " + code, sz // 2, max(40, W - 360 - wx)), wx, by + sz * .7, sz // 2, DIM)
            else:
                font.draw_text(code or L["code_wait"], 360, by + sz * .6, sz * 4 // 5 if code else sz * 3 // 5, GOLD if code else DIM, bold=True)
            bw2 = (W - 740) // 3
            if (word or code) and font.button(L["copied"] if time.time() - copied < 3 else L["copy"], 360, by + sz * 1.8, bw2, sz * 1.3, sz * 3 // 5):
                rl.set_clipboard_text(word or code)
                copied = time.time()
            if word and code and font.button(L["copy_long"], 370 + bw2, by + sz * 1.8, bw2, sz * 1.3, sz * 3 // 5):
                rl.set_clipboard_text(code)
                copied = time.time()
            link = invite_link(word, code)
            if link and font.button("Копирај линк", 380 + 2 * bw2, by + sz * 1.8, bw2, sz * 1.3, sz * 3 // 5):
                rl.set_clipboard_text(link + "  (ако линкот не се отвора: код " + (word.upper() if word else code) + ")")
                copied = time.time()
        leave = font.button(L["back"], W - 290, by, 250, sz * 2.4, sz) or rl.is_key_pressed(rl.KEY_ESCAPE)
        rl.end_drawing()
        if leave:
            return False


def invite_link(word, code):
    """skopje242://join/<word slug>  (or skopje242://code/<long code> when there is no short word)."""
    if word and joinwords.slug(word):
        return "skopje242://join/%s" % joinwords.slug(word)
    return "skopje242://code/%s" % code if code else ""


def parse_invite(url):
    """-> ("word", slug) | ("code", text) | (None, reason)"""
    import urllib.parse
    t = urllib.parse.unquote(str(url or "")).strip().strip("\"'")
    low = t.lower()
    if not low.startswith("skopje242:"):
        return None, "не е линк за Skopje 242"
    rest = t.split(":", 1)[1].lstrip("/")
    kind, _, val = rest.partition("/")
    val = val.strip("/ ")
    if kind.lower() == "join" and joinwords.slug(val):
        return "word", joinwords.slug(val)
    if kind.lower() == "code" and val:
        return "code", val
    return None, "линкот е оштетен (%s)" % rest[:40]


def register_invite_links():
    """Windows: make skopje242:// links open this game (per user, no admin). Safe to call every start."""
    import os
    import sys
    if os.name != "nt":
        return
    import winreg
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bat = os.path.join(root, "run.bat")
    cmd = '"%s" "%%1"' % bat if os.path.exists(bat) else '"%s" "%s" "%%1"' % (sys.executable, os.path.join(root, "src", "main.py"))
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\skopje242") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Skopje 242")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\skopje242\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)


def run(prof, aud=None, music=None, cfg=None, invite=None):
    present.off()
    if not prof.name and not _ask_name(prof, music):
        return None
    vc = voice.Voice(cfg)
    vc.start()
    ses = mp.Session(prof)
    ses.voice = vc
    if invite:                                         # opened from an invite link: find the host and join right away
        kind, val = parse_invite(invite)
        g, why = None, val if kind is None else ""
        ses.browse()
        if kind == "word":
            g, why = _find_word(ses, val, val, music)
        elif kind == "code":
            try:
                g = mp.parse_code(val)
            except ValueError as e:
                why = str(e)
        if g:
            ses.join(g)
        elif why and why != "back":
            _show_error("Линк за покана: " + why, music)
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
            if _room(prof, ses, music, cfg, aud):
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
