"""Car radio: shuffled tracks from assets/radio, a burst of static between them, silent outside vehicles."""
import json
import os
import random
import tempfile

import numpy as np

import audio as audio_mod

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "radio")
EXTS = (".ogg", ".oga", ".mp3", ".wav", ".flac")
MAX_PLAY = 75.0                       # a fragment of each song (from a random point), then the next one


def _static(sr=audio_mod.SR, dur=0.7):
    """Tuning noise: hiss with a few whistles, fading in and out."""
    rng = np.random.default_rng(7)
    n = int(sr * dur)
    t = np.arange(n) / sr
    x = rng.standard_normal(n) * 0.5
    x = x - np.convolve(x, np.ones(6) / 6, mode="same") * 0.6                  # brighter hiss
    x *= 1.0 + 0.6 * np.sign(np.sin(2 * np.pi * 23 * t))                         # crackle gating
    x += 0.12 * np.sin(2 * np.pi * (900 + 1400 * t / dur) * t)
    x *= np.minimum(1.0, np.minimum(t, dur - t) * 30)
    return x / max(np.abs(x).max(), 1e-6) * 0.7


class Radio:
    def __init__(self, aud):
        self.aud = aud
        self.tracks = []
        self.titles = {}
        self.music = None
        self.cur = None
        self.state = "off"             # off | static | play
        self.t = 0.0
        self.now = ""                  # title of the current track (for the HUD)
        self.volume = 0.7
        self.static = None
        self.bag = []
        if not aud.ok:
            return
        try:
            self.tracks = sorted(os.path.join(DIR, f) for f in os.listdir(DIR) if f.lower().endswith(EXTS))
            try:
                with open(os.path.join(DIR, "index.json"), encoding="utf-8") as f:
                    self.titles = {t["file"]: t["title"] for t in json.load(f)}
            except Exception:  # noqa: BLE001
                pass
            p = os.path.join(tempfile.mkdtemp(prefix="skopje_radio_"), "static.wav")
            audio_mod._save(p, _static())
            self.static = audio_mod.rl.load_sound(p)
        except Exception:  # noqa: BLE001
            self.tracks = []

    def _rl(self):
        return audio_mod.rl

    def _next(self):
        rl = self._rl()
        self._stop_music()
        for _ in range(len(self.tracks)):
            if not self.bag:
                self.bag = list(self.tracks)
                random.shuffle(self.bag)
                if self.cur in self.bag and len(self.bag) > 1 and self.bag[-1] == self.cur:
                    self.bag.reverse()
            p = self.bag.pop()
            try:
                m = rl.load_music_stream(p)
                if rl.is_music_valid(m):
                    self.music, self.cur, self.t = m, p, 0.0
                    self.now = self.titles.get(os.path.basename(p), os.path.splitext(os.path.basename(p))[0].replace("_", " "))
                    rl.play_music_stream(m)
                    ln = rl.get_music_time_length(m)
                    if ln > MAX_PLAY + 20:                       # jump into the song like flipping stations
                        rl.seek_music_stream(m, random.uniform(10.0, ln - MAX_PLAY - 5))
                    self.state = "play"
                    return True
            except Exception:  # noqa: BLE001
                pass
        self.state = "off"
        return False

    def _stop_music(self):
        if self.music is not None:
            try:
                self._rl().stop_music_stream(self.music)
                self._rl().unload_music_stream(self.music)
            except Exception:  # noqa: BLE001
                pass
            self.music = None

    def _burst(self):
        rl = self._rl()
        self._stop_music()
        self.state, self.t, self.now = "static", 0.0, ""
        try:
            rl.set_sound_volume(self.static, 0.5 * self.volume * self.aud.master)
            rl.play_sound(self.static)
        except Exception:  # noqa: BLE001
            pass

    def update(self, dt, in_vehicle, volume=0.7):
        """Call every frame.  Returns the new track title on the frame a track starts, else None."""
        if not self.aud.ok:
            return None
        rl = self._rl()
        self.volume = volume
        on = in_vehicle and not self.aud.muted and volume > 0.01
        if not on:
            if self.state != "off":
                self._stop_music()
                try:
                    rl.stop_sound(self.static)
                except Exception:  # noqa: BLE001
                    pass
                self.state, self.now = "off", ""
            return None
        if self.state == "off":                      # just got in
            try:
                self.tracks = sorted(os.path.join(DIR, f) for f in os.listdir(DIR) if f.lower().endswith(EXTS))
            except OSError:
                pass
            if self.tracks:                          # a tuning burst, then music
                self._burst()
            return None
        self.t += dt
        if self.state == "static":
            if self.t > 0.7 and self._next():
                return self.now
            return None
        try:
            rl.update_music_stream(self.music)
            fade = min(1.0, max(0.0, (MAX_PLAY - self.t) / 2.0))
            rl.set_music_volume(self.music, volume * self.aud.master * fade)
            ended = (not rl.is_music_stream_playing(self.music)) or rl.get_music_time_played(self.music) >= rl.get_music_time_length(self.music) - 0.05
            if ended or self.t > MAX_PLAY:
                self._burst()
        except Exception:  # noqa: BLE001
            self._burst()
        return None

    def close(self):
        self._stop_music()
