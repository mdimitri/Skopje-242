"""Car radio: plays whatever the user drops into the music/ folder.
Stations = sub-folders of music/ (loose files are split into a few stations).  Every station "chops" into a random part
of a random song, plays a short fragment, a blip of static, then jumps into another song - like a real radio.
raylib streams mp3 / ogg / wav / flac (m4a, aac, opus, wma are NOT supported and are skipped)."""
import os
import random
import tempfile

import numpy as np

import audio as audio_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC = os.path.join(ROOT, "music")
LEGACY = os.path.join(ROOT, "assets", "radio")     # fallback: the old downloader's folder
EXTS = (".mp3", ".ogg", ".oga", ".wav", ".flac")
UNSUPPORTED = (".m4a", ".aac", ".opus", ".wma")
FRAG = (14.0, 40.0)                                # random fragment length (s) before the next chop
SPLIT = 4                                          # loose files in music/ become up to this many stations
NAMES = ["Радио Чаршија", "Радио Вардар", "Радио Кале", "Радио Каменик", "Радио Треска", "Радио Водно", "Радио Таксист"]
HINT = ("Тука стави своја музика (mp3, ogg, wav, flac) – играта ја вчитува целата.\n"
        "Put your own music here (mp3, ogg, wav, flac; m4a/aac/opus are not supported by the engine).\n"
        "Every sub-folder becomes a radio station named after the folder; loose files are shared out between a few stations.\n"
        "In a vehicle: Q / E (or , / .) change station, the last step is radio off.\n")


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


def scan(base=MUSIC):
    """-> (stations [(name, [paths])], skipped unsupported count).  Recursive; sub-folders are stations."""
    groups, loose, skipped = {}, [], 0
    for dp, _dn, fn in os.walk(base):
        rel = os.path.relpath(dp, base)
        for f in sorted(fn):
            ext = os.path.splitext(f)[1].lower()
            if ext in UNSUPPORTED:
                skipped += 1
            elif ext in EXTS:
                p = os.path.join(dp, f)
                (loose if rel == "." else groups.setdefault(rel.split(os.sep)[0], [])).append(p)
    st = [(k, v) for k, v in sorted(groups.items())]
    if loose:
        k = max(1, min(SPLIT, len(loose) // 3))
        random.Random(len(loose)).shuffle(loose)
        names = list(NAMES)
        for i in range(k):
            st.append((names[i % len(names)], loose[i::k]))
    return st, skipped


class Radio:
    def __init__(self, aud):
        self.aud = aud
        self.stations = []
        self.sel = 0                   # station index; == len(stations) means "radio off"
        self.music = None
        self.cur = None
        self.state = "off"             # off | static | play
        self.t = 0.0
        self.frag = 25.0
        self.now = ""                  # title of the current track (for the HUD)
        self.volume = 0.7
        self.static = None
        self.skipped = 0
        self.hint = ""
        self.user_off = False
        self._scan_t = 0.0
        if not aud.ok:
            return
        try:
            os.makedirs(MUSIC, exist_ok=True)
            hp = os.path.join(MUSIC, "README.txt")
            if not os.path.exists(hp):
                with open(hp, "w", encoding="utf-8") as f:
                    f.write(HINT)
            p = os.path.join(tempfile.mkdtemp(prefix="skopje_radio_"), "static.wav")
            audio_mod._save(p, _static())
            self.static = audio_mod.rl.load_sound(p)
        except Exception:  # noqa: BLE001
            pass
        self.rescan()

    def rescan(self):
        try:
            st, self.skipped = scan(MUSIC)
            if not st and os.path.isdir(LEGACY):
                st, sk = scan(LEGACY)
                self.skipped += sk
            self.stations = st
        except Exception:  # noqa: BLE001
            self.stations = []
        self.sel = min(self.sel, len(self.stations))
        self.hint = "" if self.stations else "Радио: тишина – ставај музика во папката music"

    def _rl(self):
        return audio_mod.rl

    @property
    def off(self):
        return self.user_off or not self.stations or self.sel >= len(self.stations)

    def label(self):
        """Persistent HUD line for the current station."""
        if self.hint:
            return self.hint
        if self.off:
            return "Радио: исклучено   [Q/E]"
        nm = self.stations[self.sel][0]
        return f"Радио: {nm}" + (f" – {self.now}" if self.now else "") + "   [Q/E]"

    def step(self, d):
        """Change station by d (wraps, with an 'off' slot at the end).  Returns a banner text."""
        if not self.stations:
            self.rescan()
            return self.hint
        n = len(self.stations) + 1
        self.sel = (self.sel + d) % n
        self.user_off = self.sel >= len(self.stations)
        if self.user_off:
            self._silence()
            return "Радио: исклучено"
        self._burst()
        return "Радио: " + self.stations[self.sel][0]

    def _next(self):
        """Chop into a random part of a random song of the current station."""
        rl = self._rl()
        self._stop_music()
        pool = list(self.stations[self.sel][1])
        random.shuffle(pool)
        if self.cur in pool and len(pool) > 1:
            pool.remove(self.cur)
        for p in pool:
            try:
                m = rl.load_music_stream(p)
                if not rl.is_music_valid(m):
                    continue
                self.music, self.cur, self.t = m, p, 0.0
                self.now = os.path.splitext(os.path.basename(p))[0].replace("_", " ")
                self.frag = random.uniform(*FRAG)
                rl.play_music_stream(m)
                ln = rl.get_music_time_length(m)
                if ln > self.frag + 6:
                    rl.seek_music_stream(m, random.uniform(0.0, ln - self.frag - 4))
                elif ln > 6:
                    self.frag = max(5.0, ln - 1.0)
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

    def _burst(self, dur=0.55):
        rl = self._rl()
        self._stop_music()
        self.state, self.t, self.now = "static", 0.0, ""
        self._burst_len = dur
        try:
            rl.set_sound_volume(self.static, 0.5 * self.volume * self.aud.master)
            rl.play_sound(self.static)
        except Exception:  # noqa: BLE001
            pass

    def _silence(self):
        self._stop_music()
        try:
            self._rl().stop_sound(self.static)
        except Exception:  # noqa: BLE001
            pass
        self.state, self.now = "off", ""

    def update(self, dt, in_vehicle, volume=0.7):
        """Call every frame.  Returns the new track title on the frame a track starts, else None."""
        if not self.aud.ok:
            return None
        rl = self._rl()
        self.volume = volume
        on = in_vehicle and not self.aud.muted and volume > 0.01 and not self.off
        if not on:
            if self.state != "off":
                self._silence()
            if in_vehicle and self.user_off is False and not self.stations:
                self._scan_t += dt
                if self._scan_t > 5.0:                       # music dropped in while playing
                    self._scan_t = 0.0
                    self.rescan()
            return None
        if self.state == "off":                      # just got in: rescan (files may have been added), tune in
            self.rescan()
            if not self.off:
                self._burst(0.4)
            return None
        self.t += dt
        if self.state == "static":
            if self.t > self._burst_len and self._next():
                return self.now
            return None
        try:
            rl.update_music_stream(self.music)
            fade = min(1.0, self.t / 0.3, max(0.0, (self.frag - self.t) / 0.8))
            rl.set_music_volume(self.music, volume * self.aud.master * fade)
            ended = (not rl.is_music_stream_playing(self.music)) or rl.get_music_time_played(self.music) >= rl.get_music_time_length(self.music) - 0.05
            if ended or self.t > self.frag:
                self._burst(random.uniform(0.2, 0.4))
        except Exception:  # noqa: BLE001
            self._burst()
        return None

    def close(self):
        self._stop_music()
