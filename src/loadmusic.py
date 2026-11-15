"""Music on the loading screen and the title menu: random songs from music/ (the same files as the car radio), shaped to
sound like a radio playing in another room (band-limited, slightly crunchy, faint hiss and fading reception) and kept
quiet so it never overpowers.  Fragments are decoded in a worker thread and played as in-memory sounds, so the long
loading steps that block the main thread cannot make it stutter."""
import os
import random
import tempfile
import threading

import numpy as np
import pyray as rl

import font
import radio

FRAG = (50.0, 110.0)          # seconds of one song before the "dial" moves to another
LEVEL = 0.38                  # relative to the radio volume setting
PINK = rl.Color(226, 32, 104, 255)


def _crackle(n, sr, rng):
    """Vinyl surface: sparse little ticks, now and then a louder pop, and a very faint dusty hiss under them."""
    out = np.zeros(n, np.float32)
    dur = n / sr
    for rate, lo, hi in ((9.0, 0.02, 0.09), (0.35, 0.12, 0.25)):         # ticks, pops
        k = rng.poisson(rate * dur)
        pos = rng.integers(0, max(1, n - 200), k)
        amp = rng.uniform(lo, hi, k) * rng.choice((-1.0, 1.0), k)
        np.add.at(out, pos, amp.astype(np.float32))
    tail = np.exp(-np.arange(int(sr * 0.0015)) / (sr * 0.0004)).astype(np.float32)
    out = np.convolve(out, tail, mode="same")                             # each tick rings for ~1 ms
    dust = rng.standard_normal(n).astype(np.float32)
    dust -= np.convolve(dust, np.ones(3) / 3, mode="same")
    return out + 0.0035 * dust


def radio_fx(seg, sr):
    """(n, ch) float -> an old radio playing a record: mono, 450-4500 Hz band (thin, no bass), a touch of speaker
    saturation, slow reception drift and vinyl crackle on top.  Almost no hiss."""
    n = len(seg)
    x = seg.mean(axis=1)
    fq = np.fft.rfftfreq(n, 1.0 / sr)
    band = 1.0 / np.sqrt(1.0 + (450.0 / np.maximum(fq, 1.0)) ** 6) / np.sqrt(1.0 + (fq / 4500.0) ** 6)
    x = np.fft.irfft(np.fft.rfft(x) * band, n)
    x = x / max(1e-6, np.abs(x).max())
    x = np.tanh(x * 1.3) / np.tanh(1.3)                                  # small speaker, gently pushed
    t = np.arange(n) / sr
    rng = np.random.default_rng()
    x *= 0.88 + 0.12 * np.sin(2 * np.pi * (0.06 * t + rng.random()))     # reception drifting a little
    x = 0.75 * x + _crackle(n, sr, rng)
    x = np.clip(x, -0.98, 0.98)
    return np.repeat(x[:, None], seg.shape[1], axis=1).astype(np.float32)


class LoadMusic:
    def __init__(self, mute=False, volume=0.7):
        self.ok = False
        self.volume = volume
        self.snd = None
        self.static = None
        self.job = None
        self.files = []
        self.stations = []            # [(name, [paths])]: one per genre folder, like the car radio
        self.sel = 0                  # station playing now
        self.menu_open = False        # station drop-down is open
        self.bag = []                 # songs of this station not yet played in the current shuffle
        self.logos = {}               # station name -> texture (or None)
        self.hist = []                # songs played, newest last (◀ goes back through them, ▶ forward again)
        self.pos = -1                 # index in hist of the song playing now
        self.paused = False
        self.stopped = False          # ■ pressed: silence until ▶ / the play button
        self.swap = False             # a ◀ / ▶ press is waiting for its song; the old one keeps playing until it is ready
        self.want = None              # index in hist being decoded after a ◀ / ▶ press (so quick double presses keep going)
        self.title = ""
        self.cur = None
        if mute or volume < 0.01:
            return
        try:
            stations, _ = radio.scan()
            self.stations = stations
            self.files = list(stations[0][1]) if stations else []
            if not self.files:
                return
            if not rl.is_audio_device_ready():
                rl.init_audio_device()
            if not rl.is_audio_device_ready():
                return
            self.dir = tempfile.mkdtemp(prefix="skopje_load_")
            sp = os.path.join(self.dir, "static.wav")
            radio.audio_mod._save(sp, radio._static(dur=0.6))
            self.static = rl.load_sound(sp)
            self.seq = 0
            self.ok = True
            self._next()
        except Exception as e:  # noqa: BLE001 - music is decoration
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def _next(self, path=None):
        self.seq += 1
        job = {"out": os.path.join(self.dir, f"m{self.seq}.wav"), "ok": False, "done": False, "path": None}
        if path:
            pool = [path]
        else:                                                    # a shuffled "bag": every song once, then a new shuffle (no immediate repeat)
            if not self.bag:
                self.bag = random.sample(self.files, len(self.files))
                if len(self.bag) > 1 and self.bag[-1] == self.cur:
                    self.bag[0], self.bag[-1] = self.bag[-1], self.bag[0]
            pool = self.bag[::-1][:3]                            # next up first; the others only if it will not decode

        def work():
            for p in pool:
                try:
                    if radio.cut_fragment(p, job["out"], random.uniform(*FRAG), fx=radio_fx):
                        job["ok"], job["path"] = True, p
                        break
                except Exception as e:  # noqa: BLE001
                    print(f"[loadmusic] cannot play {p}: {e}", flush=True)
            job["done"] = True
        self.job = job
        threading.Thread(target=work, daemon=True).start()

    def update(self):
        """Cheap; call from every loading frame.  Starts the next song when the current one has ended."""
        if not self.ok:
            return
        try:
            if self.stopped or (self.paused and not self.swap):
                return
            if self.snd is not None and rl.is_sound_playing(self.snd) and not self.swap:
                return
            if self.job is None:
                self._next()
                return
            if not self.job["done"]:
                return
            job, self.job = self.job, None
            if not job["ok"]:                                    # undecodable file: keep what plays now, try another one
                self.swap = False
                self.want = None
                if job.get("idx") is not None and job["idx"] < len(self.hist):
                    del self.hist[job["idx"]]                    # a song that will not decode leaves the history
                    if job["idx"] <= self.pos:
                        self.pos -= 1
                self._next()
                return
            self.swap = False
            self.paused = False
            self._drop()
            if job["ok"]:
                rl.set_sound_volume(self.static, 0.2 * self.volume)
                rl.play_sound(self.static)                       # turning the dial
                self.snd = rl.load_sound(job["out"])
                try:
                    os.remove(job["out"])
                except OSError:
                    pass
                rl.set_sound_volume(self.snd, LEVEL * self.volume)
                rl.play_sound(self.snd)
                self.cur = job["path"]
                if self.cur in self.bag:
                    self.bag.remove(self.cur)
                self.title = os.path.splitext(os.path.basename(self.cur))[0].replace("_", " ")
                if job.get("idx") is not None:
                    self.pos = job["idx"]
                else:
                    self.hist.append(self.cur)
                    if len(self.hist) > 30:
                        del self.hist[0]
                    self.pos = len(self.hist) - 1
                self.want = None
                self._next()                                     # decode the next song while this one plays
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def skip(self, back=False):
        """◀ / ▶: back to the previous song (and forward again through the ones already heard), else on to a new one.
        The song playing now keeps going until the next one is decoded, so a press never leaves silence."""
        if not self.ok:
            return
        try:
            if self.stopped:
                self.stopped = False                             # ◀ / ▶ after ■ starts music again
            cur = self.want if self.want is not None else self.pos
            idx = cur + (-1 if back else 1)
            if back and idx < 0:
                return
            if idx < len(self.hist):                             # a song we already heard
                self.job = None                                  # (a decode still running just finishes into its own file)
                self._next(self.hist[idx])
                self.job["idx"] = idx
                self.want = idx
            elif self.want is not None:
                return                                           # still fetching the earlier one
            elif self.job is None:
                self._next()
            self.swap = True
            rl.set_sound_volume(self.static, 0.2 * self.volume)
            rl.play_sound(self.static)                           # the dial turns while the song decodes
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def station(self, d):
        """Q / E: previous / next station (genre folder).  The old song plays on until the new station's first one is ready."""
        if not self.ok or len(self.stations) < 2:
            return
        try:
            self.sel = (self.sel + d) % len(self.stations)
            self.files = list(self.stations[self.sel][1])
            self.hist, self.pos, self.want, self.bag = [], -1, None, []
            self.stopped = False
            self.job = None
            self._next()
            self.swap = True
            rl.set_sound_volume(self.static, 0.2 * self.volume)
            rl.play_sound(self.static)
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def toggle(self):
        """Pause / resume (after ■ it starts a new song)."""
        if not self.ok:
            return
        try:
            if self.stopped:
                self.stopped = False
                if self.job is None:
                    self._next()
            elif self.paused:
                self.paused = False
                if self.snd is not None:
                    rl.resume_sound(self.snd)
            elif self.snd is not None:
                self.paused = True
                rl.pause_sound(self.snd)
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def stop(self):
        """■: kill the music until the player asks for it again."""
        if not self.ok:
            return
        self.stopped, self.paused, self.swap, self.want = True, False, False, None
        self._drop()
        self.title = ""

    def _symbol(self, x, y, S):
        """The radio symbol on the always-there button: a little set with an antenna, a dial and a speaker."""
        cx, cy = x + S / 2, y + S / 2
        u = S / 72.0 if S > 40 else 0.6
        col = rl.WHITE
        rl.draw_line_ex(rl.Vector2(cx - 8 * u, cy - 6 * u), rl.Vector2(cx + 14 * u, cy - 24 * u), 2.5, col)
        rl.draw_rectangle_lines_ex(rl.Rectangle(cx - 22 * u, cy - 8 * u, 44 * u, 28 * u), 2.5, col)
        rl.draw_circle_lines(int(cx - 9 * u), int(cy + 6 * u), 7 * u, col)
        for k in range(3):
            rl.draw_line_ex(rl.Vector2(cx + 6 * u, cy + (0 + 6 * k) * u), rl.Vector2(cx + 16 * u, cy + (0 + 6 * k) * u), 2.0, col)

    def widget(self, x=None, y=None, keys=True, room=9999, station_keys=True):
        """Always top left (12, 10): a radio-symbol button that is there on every screen.  It opens to the right after a hover (and
        for a few seconds at the start), showing the station drop-down and the song bar as two stripes of the same width, and folds
        back by itself when the mouse has been away for a while.  The button never moves; screens leave its corner free (see
        corner.py for the label under it)."""
        if not self.ok:
            return
        import time
        import corner
        sz = 27
        b = 30
        X, Y = 12, 10
        W, H = rl.get_screen_width(), rl.get_screen_height()
        multi = len(self.stations) > 1
        S = 72 if multi else 38                                  # the button: as high as the two stripes together
        SW = max(200, min(420, W - X - S - 8 - 12))              # both stripes, the same width
        now = time.time()
        if getattr(self, "_idle", None) is None:
            self._idle, self._exp = now, 1.0                      # open at first, so it is seen
        m = font.pointer()
        reach = S + (8 + SW) * self._exp
        if (X <= m.x < X + reach and Y <= m.y < Y + S) or self.menu_open:
            self._idle = now
        target = 1.0 if now - self._idle < 5.0 else 0.0
        self._exp += (target - self._exp) * min(1.0, rl.get_frame_time() * 9.0)
        if abs(self._exp - target) < 0.01:
            self._exp = target
        e = self._exp
        font.MUSIC_EXTRA = 0
        corner.set_box((X, Y, S, S))
        # ---- the button
        tex = self._logo() if (self.stations and e > 0.5) else None
        rl.draw_rectangle(X, Y, S, S, rl.Color(10, 8, 16, 200))
        if tex is not None and tex.width > 0:
            sc = min((S - 6) / tex.width, (S - 6) / tex.height)
            lw_, lh_ = tex.width * sc, tex.height * sc
            rl.draw_texture_pro(tex, rl.Rectangle(0, 0, tex.width, tex.height),
                                rl.Rectangle(X + (S - lw_) / 2, Y + (S - lh_) / 2, lw_, lh_), rl.Vector2(0, 0), 0.0, rl.WHITE)
        else:
            self._symbol(X, Y, S)
        rl.draw_rectangle_lines_ex(rl.Rectangle(X, Y, S, S), 2, PINK)
        click_in = font.clicked()
        live = e > 0.9
        if e > 0.01:                                             # ---- the stripes, revealed from the left
            sx = X + S + 8
            rl.begin_scissor_mode(sx, Y, int(SW * e) + 1, H - Y)
            head = None
            y2 = Y
            if multi:
                dh = 30
                head = (sx, Y, SW, dh)
                y2 = Y + dh + 4
            name = font.fit(self.title or ("■" if self.stopped else "…"), sz, max(40, SW - 156), "cond")
            w = SW
            rl.draw_rectangle(sx, y2, w, b + 8, rl.Color(10, 8, 16, 170))
            click = click_in and live and not self.menu_open     # an open list swallows the click
            tip = None
            for k, bx in ((0, sx + 4), (1, sx + 4 + b + 4), (2, sx + 4 + 2 * (b + 4)), (3, sx + w - b - 4)):
                by = y2 + 4
                over = live and bx <= m.x < bx + b and by <= m.y < by + b
                rl.draw_rectangle(bx, by, b, b, PINK if over else rl.Color(60, 40, 70, 230))
                cx, cy, r = bx + b / 2, by + b / 2, b * 0.28
                if k == 0:
                    rl.draw_triangle(rl.Vector2(cx + r, cy - r), rl.Vector2(cx - r, cy), rl.Vector2(cx + r, cy + r), rl.WHITE)
                elif k == 1:
                    if self.paused or self.stopped:              # shows what a click does: resume
                        rl.draw_triangle(rl.Vector2(cx - r, cy - r), rl.Vector2(cx - r, cy + r), rl.Vector2(cx + r, cy), rl.WHITE)
                    else:
                        rl.draw_rectangle(int(cx - r), int(cy - r), int(r * 0.7), int(2 * r), rl.WHITE)
                        rl.draw_rectangle(int(cx + r * 0.3), int(cy - r), int(r * 0.7), int(2 * r), rl.WHITE)
                elif k == 2:
                    rl.draw_rectangle(int(cx - r), int(cy - r), int(2 * r), int(2 * r), rl.WHITE)
                else:
                    rl.draw_triangle(rl.Vector2(cx - r, cy - r), rl.Vector2(cx - r, cy + r), rl.Vector2(cx + r, cy), rl.WHITE)
                if over:
                    tip = (bx, ("Претходна", "Продолжи" if (self.paused or self.stopped) else "Пауза", "Стоп", "Следна")[k])
                    if click:
                        (lambda: self.skip(back=True), self.toggle, self.stop, self.skip)[k]()
            font.draw_text(name, sx + 3 * (b + 4) + 12, y2 + (b + 8 - sz) // 2 - 2, sz, rl.WHITE, bold="cond")
            if tip and not self.menu_open:
                tx = font.measure_text(tip[1], 20, "cond")
                rl.draw_rectangle(tip[0], y2 + b + 10, tx + 12, 26, rl.Color(10, 8, 16, 220))
                font.draw_text(tip[1], tip[0] + 6, y2 + b + 12, 20, rl.WHITE, bold="cond")
            if head is not None:
                self._dropdown(head, station_keys and live, m, click_in and live)
            rl.end_scissor_mode()
        elif multi and station_keys:                             # folded: Q / E still change the station
            if rl.is_key_pressed(rl.KEY_E):
                self.station(1)
            elif rl.is_key_pressed(rl.KEY_Q):
                self.station(-1)
        if not keys:                                             # (screens where the arrows already move the selection)
            return
        if rl.is_key_pressed(rl.KEY_LEFT):
            self.skip(back=True)
        elif rl.is_key_pressed(rl.KEY_RIGHT):
            self.skip()

    def _logo(self):
        """Texture of the current station's logo image (music/<station>/logo.png ...), loaded once; None without one."""
        nm = self.stations[self.sel][0]
        if nm not in self.logos:
            tex = None
            try:
                p = radio.logo_for(nm)
                if p:
                    with open(p, "rb") as f:                     # from memory: raylib's own fopen mangles Cyrillic paths on Windows
                        raw = f.read()
                    img = rl.load_image_from_memory(os.path.splitext(p)[1].lower(), raw, len(raw))
                    tex = rl.load_texture_from_image(img)
                    rl.unload_image(img)
                    rl.set_texture_filter(tex, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
            except Exception as e:  # noqa: BLE001 - a bad image just means no logo
                print(f"[loadmusic] logo of {nm}: {e}", flush=True)
                tex = None
            self.logos[nm] = tex
        return self.logos[nm]

    def _dropdown(self, head, station_keys, m, click):
        """Closed: current station + arrow.  Open: the list of stations below it (drawn last, over the bar)."""
        hx, hy, hw, dh = head
        over = hx <= m.x < hx + hw and hy <= m.y < hy + dh
        rl.draw_rectangle(hx, hy, hw, dh, PINK if over else rl.Color(10, 8, 16, 190))
        rl.draw_rectangle_lines(hx, hy, hw, dh, rl.Color(226, 32, 104, 255))
        font.draw_text(font.fit(self.stations[self.sel][0], 22, hw - 44, "cond"), hx + 10, hy + 3, 22, rl.WHITE, bold="cond")
        cx, cy, r = hx + hw - 18, hy + dh / 2, 6
        if self.menu_open:
            rl.draw_triangle(rl.Vector2(cx - r, cy + r / 2), rl.Vector2(cx + r, cy + r / 2), rl.Vector2(cx, cy - r / 2), rl.WHITE)
        else:
            rl.draw_triangle(rl.Vector2(cx - r, cy - r / 2), rl.Vector2(cx, cy + r / 2), rl.Vector2(cx + r, cy - r / 2), rl.WHITE)
        if click and over:
            self.menu_open = not self.menu_open
        elif self.menu_open:
            rows = len(self.stations)
            rl.draw_rectangle(hx, hy + dh, hw, rows * dh, rl.Color(10, 8, 16, 245))
            hit = False
            for k, (nm, ps) in enumerate(self.stations):
                ry = hy + dh + k * dh
                ov = hx <= m.x < hx + hw and ry <= m.y < ry + dh
                if ov or k == self.sel:
                    rl.draw_rectangle(hx, ry, hw, dh, PINK if ov else rl.Color(60, 40, 70, 230))
                font.draw_text(font.fit(f"{nm}  ({len(ps)})", 22, hw - 20, "cond"), hx + 10, ry + 3, 22, rl.WHITE, bold="cond")
                if ov and click:
                    hit = True
                    if k != self.sel:
                        self.station(k - self.sel)
            if click:
                self.menu_open = False
                if hit:
                    font.clear_latch()
        if station_keys:
            if rl.is_key_pressed(rl.KEY_E):
                self.station(1)
            elif rl.is_key_pressed(rl.KEY_Q):
                self.station(-1)

    def _drop(self):
        if self.snd is not None:
            rl.stop_sound(self.snd)
            rl.unload_sound(self.snd)
            self.snd = None

    def close(self):
        if not self.ok:
            return
        self.ok = False
        try:
            self._drop()
            rl.stop_sound(self.static)
            rl.unload_sound(self.static)
        except Exception:  # noqa: BLE001
            pass
