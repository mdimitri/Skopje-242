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
        self.setup = None
        self.early_skips = []
        self.files = []
        self.stations = []            # [(name, [paths])]: one per genre folder, like the car radio
        self.sel = 0                  # station playing now
        self.menu_open = False        # station drop-down is open
        self.logos = {}               # station name -> texture (or None)
        self.pos = None               # index of the track playing in this station
        self.paused = False
        self.stopped = False          # ■ pressed: silence until ▶ / the play button
        self.want = None              # target of the latest manual selection
        self.direction = 1
        self.title = ""
        self.cur = None
        if mute or volume < 0.01:
            return
        try:
            if not rl.is_audio_device_ready():
                rl.init_audio_device()
            if not rl.is_audio_device_ready():
                return
            self.ok = True
            self.setup = {}
            threading.Thread(target=self._scan, args=(self.setup,), daemon=True).start()
        except Exception as e:  # noqa: BLE001 - music is decoration
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    @staticmethod
    def _scan(setup):
        """Find stations and prepare the tuning sound while the opening cue plays."""
        try:
            stations, _ = radio.scan()
            if stations:
                directory = tempfile.mkdtemp(prefix="skopje_load_")
                radio.audio_mod._save(os.path.join(directory, "static.wav"), radio._static(dur=0.6))
                setup["result"] = stations, directory
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] cannot prepare stations: {e}", flush=True)
        finally:
            setup["done"] = True

    def _prepare(self, path):
        job = {"out": os.path.join(self.dir, "fragment.wav"), "ok": False, "done": False, "path": path}
        def work():
            try:
                job["ok"] = radio.cut_fragment(path, job["out"], random.uniform(*FRAG), fx=radio_fx)
            except Exception as e:  # noqa: BLE001
                print(f"[loadmusic] cannot play {path}: {e}", flush=True)
            finally:
                job["done"] = True
        self.job = job
        threading.Thread(target=work, daemon=True).start()

    def update(self):
        """Cheap; call from every loading frame.  Starts the next song when the current one has ended."""
        if not self.ok:
            return
        try:
            if self.setup is not None:
                if not self.setup.get("done"):
                    return
                setup, self.setup = self.setup, None
                if "result" in setup:
                    self.stations, self.dir = setup["result"]
                    rap = [i for i, (name, _) in enumerate(self.stations) if "рап" in name.lower()]
                    if rap:                                   # the loader plays the rap station, a random song
                        self.sel = random.choice(rap)
                    self.files = list(self.stations[self.sel][1])
                    random.shuffle(self.files)
                    if self.cur is not None:
                        self.pos = self.files.index(self.cur)
                    self.static = rl.load_sound(os.path.join(self.dir, "static.wav"))
                    for back in self.early_skips:
                        self.skip(back)
                self.early_skips.clear()
            if not self.files:
                if not self.stations and (self.snd is None or (not self.paused and not rl.is_sound_playing(self.snd))):
                    self.close()
                return
            idx = self.want if self.want is not None else (0 if self.pos is None else (self.pos + 1) % len(self.files))
            path = self.files[idx]
            job = self.job
            if job is not None and not job["done"]:
                return
            if job is None or job["path"] != path:
                self._prepare(path)
                return
            if self.stopped or (self.want is None and
                                (self.paused or (self.snd is not None and rl.is_sound_playing(self.snd)))):
                return
            self.job = None
            snd = None
            if job["ok"]:
                snd = rl.load_sound(job["out"])
                try:
                    os.remove(job["out"])
                except OSError:
                    pass
            if snd is None or not rl.is_sound_valid(snd):
                del self.files[idx]
                if self.pos is not None and self.pos >= idx:
                    self.pos = self.pos - 1 if self.pos != idx else None
                if self.want is not None:
                    self.want = (idx - (self.direction < 0)) % len(self.files) if self.files else None
                return
            if self.want is None and self.snd is not None:
                self._tune()
            self._drop()
            self.snd = snd
            rl.set_sound_volume(snd, LEVEL * self.volume)
            rl.play_sound(snd)
            self.cur, self.pos = path, idx
            self.title = os.path.splitext(os.path.basename(path))[0].replace("_", " ")
            self.want, self.paused = None, False
            self._prepare(self.files[(idx + 1) % len(self.files)])
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def skip(self, back=False):
        """Step through the station's shuffle, counting repeated presses during decoding."""
        if not self.ok:
            return
        if not self.files:
            if self.setup is not None:
                self.early_skips.append(back)
            return
        self.direction = -1 if back else 1
        cur = self.want if self.want is not None else self.pos
        index = (-1 if back else 0) if cur is None else cur + self.direction
        index %= len(self.files)
        if self.want is not None and index == self.pos and self.snd is not None:
            self.want = None
            return
        if self.want is None:
            self._tune()
        self.want = index
        self.stopped = False

    def _tune(self):
        if self.static is not None:
            rl.set_sound_volume(self.static, 0.2 * self.volume)
            rl.play_sound(self.static)

    def station(self, d):
        """Q / E: previous / next station (genre folder).  The old song plays on until the new station's first one is ready."""
        if not self.ok or len(self.stations) < 2:
            return
        try:
            self.sel = (self.sel + d) % len(self.stations)
            self.files = list(self.stations[self.sel][1])
            random.shuffle(self.files)
            self.pos, self.want, self.direction = None, 0, 1
            self.stopped = False
            self._tune()
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
        self.stopped, self.paused, self.want = True, False, None
        self.early_skips.clear()
        self._drop()
        if self.static is not None:
            rl.stop_sound(self.static)
        self.title = ""

    def poke(self, sec=1.6):
        """Keep the bar open for a moment (a hotkey changed the station / song)."""
        import time
        self._idle = time.time() + sec

    @property
    def display_title(self):
        if self.want is not None and self.files:
            pending = os.path.splitext(os.path.basename(self.files[self.want]))[0].replace("_", " ")
            return "… " + pending
        return self.title

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
            self._idle, self._exp = now + 2.6, 1.0                # open for ~3 s at first, so it is seen
        m = font.pointer()
        reach = S + (8 + SW) * self._exp
        if (X <= m.x < X + reach and Y <= m.y < Y + S) or self.menu_open:
            self._idle = now
        target = 1.0 if now - self._idle < 0.4 else 0.0           # folds right after the mouse has left
        self._exp += (target - self._exp) * min(1.0, rl.get_frame_time() * 14.0)
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
            visible = int(SW * e) + 1
            rl.begin_scissor_mode(sx, Y, visible, H - Y)
            head = None
            y2 = Y
            if multi:
                dh = 30
                head = (sx, Y, SW, dh)
                y2 = Y + dh + 4
            name = font.fit(self.display_title or ("■" if self.stopped else "…"), sz, max(40, SW - 156), "cond")
            w = SW
            rl.draw_rectangle(sx, y2, w, b + 8, rl.Color(10, 8, 16, 170))
            click = click_in and not self.menu_open
            tip = None
            for k, bx in ((0, sx + 4), (1, sx + 4 + b + 4), (2, sx + 4 + 2 * (b + 4)), (3, sx + w - b - 4)):
                by = y2 + 4
                over = bx <= m.x < min(bx + b, sx + visible) and by <= m.y < by + b
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
            if font.key_pressed(rl.KEY_E):
                self.station(1)
            elif font.key_pressed(rl.KEY_Q):
                self.station(-1)
        if not keys:                                             # (screens where the arrows already move the selection)
            return
        if font.key_pressed(rl.KEY_LEFT):
            self.skip(back=True)
        elif font.key_pressed(rl.KEY_RIGHT):
            self.skip()

    def _logo(self):
        """Texture of the current station's logo image (music/<station>/logo.png ...), loaded once; None without one."""
        nm = self.stations[self.sel][0]
        if nm not in self.logos:
            tex = None
            try:
                tex = radio.load_logo(nm)
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
            if font.key_pressed(rl.KEY_E):
                self.station(1)
            elif font.key_pressed(rl.KEY_Q):
                self.station(-1)

    def _drop(self):
        if self.snd is not None:
            rl.stop_sound(self.snd)
            rl.unload_sound(self.snd)
            self.snd = None

    def close(self):
        self.ok = False
        try:
            self._drop()
            if self.static is not None:
                rl.stop_sound(self.static)
                rl.unload_sound(self.static)
                self.static = None
            for tex in self.logos.values():
                if tex is not None:
                    rl.unload_texture(tex)
            self.logos.clear()
        except Exception:  # noqa: BLE001
            pass


class CarRadioView:
    """The in-game car radio (radio.Radio) shown through the same button: LoadMusic's interface, driving the radio's own station / track."""

    menu_open = False

    def __init__(self, r):
        self.r = r

    @property
    def ok(self):
        return bool(self.r.aud.ok and self.r.stations)

    @property
    def stations(self):
        return self.r.stations

    @property
    def sel(self):
        return min(self.r.sel, len(self.r.stations) - 1)

    @property
    def title(self):
        return "" if self.r.off else (self.r.now or "")

    display_title = title

    paused = False

    def update(self):
        pass

    @property
    def stopped(self):
        return self.r.off

    def skip(self, back=False):
        self.r.skip(-1 if back else 1)

    def toggle(self):
        self.r.step(1 if self.r.off else len(self.r.stations) - self.r.sel)      # off -> the first station / playing -> the "off" slot

    def stop(self):
        if not self.r.off:
            self.r.step(len(self.r.stations) - self.r.sel)

    def station(self, d):
        self.r.step(d)

    def _logo(self):
        return self.r.logo()

    widget = LoadMusic.widget
    _symbol = LoadMusic._symbol
    _dropdown = LoadMusic._dropdown
    poke = LoadMusic.poke
