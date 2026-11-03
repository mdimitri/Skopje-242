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


def radio_fx(seg, sr):
    """(n, ch) float -> mono AM-radio colour: 300-3400 Hz band, soft clipping, hiss, slow reception fades."""
    n = len(seg)
    x = seg.mean(axis=1)
    fq = np.fft.rfftfreq(n, 1.0 / sr)
    band = 1.0 / np.sqrt(1.0 + (300.0 / np.maximum(fq, 1.0)) ** 4) / np.sqrt(1.0 + (fq / 3400.0) ** 6)
    x = np.fft.irfft(np.fft.rfft(x) * band, n)
    x = np.tanh(x * 2.2) / np.tanh(2.2)                                  # gentle crunch of a small speaker
    t = np.arange(n) / sr
    rng = np.random.default_rng()
    x *= 0.82 + 0.18 * np.sin(2 * np.pi * (0.07 * t + rng.random()))     # reception drifting in and out
    hiss = rng.standard_normal(n)
    hiss -= np.convolve(hiss, np.ones(4) / 4, mode="same")               # high, thin hiss
    x = 0.85 * x + 0.035 * hiss * (1.0 + 0.6 * np.sin(2 * np.pi * 0.13 * t))
    x = x / max(1e-6, np.abs(x).max()) * 0.8
    return np.repeat(x[:, None], seg.shape[1], axis=1).astype(np.float32)


class LoadMusic:
    def __init__(self, mute=False, volume=0.7):
        self.ok = False
        self.volume = volume
        self.snd = None
        self.static = None
        self.job = None
        self.files = []
        self.hist = []                # songs played, newest last (◀ goes back through them)
        self.title = ""
        self.cur = None
        if mute or volume < 0.01:
            return
        try:
            stations, _ = radio.scan()
            self.files = [p for _name, ps in stations for p in ps]
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
        pool = [path] if path else random.sample(self.files, min(6, len(self.files)))
        if not path and self.cur in pool and len(pool) > 1:
            pool.remove(self.cur)

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
            if self.snd is not None and rl.is_sound_playing(self.snd):
                return
            if self.job is None:
                self._next()
                return
            if not self.job["done"]:
                return
            job, self.job = self.job, None
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
                self.title = os.path.splitext(os.path.basename(self.cur))[0].replace("_", " ")
                if job.get("back"):
                    self.hist.pop()
                else:
                    self.hist.append(self.cur)
                    del self.hist[:-30]
                self._next()                                     # decode the next song while this one plays
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def skip(self, back=False):
        """◀ / ▶: back to the previous song or on to the next one."""
        if not self.ok:
            return
        try:
            if back:
                if len(self.hist) < 2:
                    return
                self.job = None                                  # (a decode still running just finishes into its own file)
                self._next(self.hist[-2])
                self.job["back"] = True
            self._drop()
            self.title = "…"
            rl.set_sound_volume(self.static, 0.2 * self.volume)
            rl.play_sound(self.static)                           # the dial turns while the song decodes
        except Exception as e:  # noqa: BLE001
            print(f"[loadmusic] off: {e}", flush=True)
            self.ok = False

    def widget(self, x=12, y=10):
        """Top-left: the song playing now between ◀ ▶ buttons (mouse, or the Left / Right keys)."""
        if not self.ok:
            return
        sz = 18
        b = 30
        name = font.fit(self.title or "…", sz, 360, "cond")
        tw = font.measure_text(name, sz, "cond")
        w = b * 2 + tw + 30
        rl.draw_rectangle(x, y, w, b + 8, rl.Color(10, 8, 16, 170))
        m = rl.get_mouse_position()
        click = rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)
        for k, bx in ((0, x + 4), (1, x + w - b - 4)):
            by = y + 4
            over = bx <= m.x < bx + b and by <= m.y < by + b
            rl.draw_rectangle(bx, by, b, b, PINK if over else rl.Color(60, 40, 70, 230))
            cx, cy, r = bx + b / 2, by + b / 2, b * 0.28
            if k == 0:
                rl.draw_triangle(rl.Vector2(cx + r, cy - r), rl.Vector2(cx - r, cy), rl.Vector2(cx + r, cy + r), rl.WHITE)
            else:
                rl.draw_triangle(rl.Vector2(cx - r, cy - r), rl.Vector2(cx - r, cy + r), rl.Vector2(cx + r, cy), rl.WHITE)
            if over and click:
                self.skip(back=k == 0)
        font.draw_text(name, x + b + 15, y + (b + 8 - sz) // 2 - 2, sz, rl.WHITE, bold="cond")
        if rl.is_key_pressed(rl.KEY_LEFT):
            self.skip(back=True)
        elif rl.is_key_pressed(rl.KEY_RIGHT):
            self.skip()

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
