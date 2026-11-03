"""Car radio: plays whatever the user drops into the music/ folder.
Stations = sub-folders of music/ (loose files are split into a few stations).  Every station "chops" into a random part
of a random song, plays a short fragment, a blip of static, then jumps into another song - like a real radio.
raylib streams mp3 / ogg / wav / flac (m4a, aac, opus, wma are NOT supported and are skipped)."""
from texts import TXT
import os
import random
import tempfile
import threading
import wave

import numpy as np

import audio as audio_mod

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC = os.path.join(ROOT, "music")
LEGACY = os.path.join(ROOT, "assets", "radio")     # fallback: the old downloader's folder
EXTS = (".mp3", ".ogg", ".oga", ".wav", ".flac")
UNSUPPORTED = (".m4a", ".aac", ".opus", ".wma")
FRAG = (14.0, 40.0)                                # random fragment length (s) before the next chop
SPLIT = 4                                          # loose files in music/ become up to this many stations
NAMES = [TXT("radio.0001"), TXT("radio.0002"), TXT("radio.0003"), TXT("radio.0004"), TXT("radio.0005"), TXT("radio.0006"), TXT("radio.0007")]
HINT = (TXT("radio.0008"))


def _static(sr=audio_mod.SR, dur=0.3):
    """Short, quiet tuning blip: soft hiss fading in and out."""
    rng = np.random.default_rng(7)
    n = int(sr * dur)
    t = np.arange(n) / sr
    x = rng.standard_normal(n) * 0.5
    x = x - np.convolve(x, np.ones(6) / 6, mode="same") * 0.6
    x *= np.minimum(1.0, np.minimum(t, dur - t) * 30)
    return x / max(np.abs(x).max(), 1e-6) * 0.5


def cut_fragment(path, out_wav, frag, muffle=False, fx=None):
    """Decode path completely (raylib's decoder, verified bit-exact against ffmpeg), cut `frag` s from a random point,
    fade the ends and write a 16-bit wav.  Runs in a worker thread.  Returns True on success."""
    rl = audio_mod.rl
    with open(path, "rb") as f:                        # from memory: raylib's own fopen mangles Cyrillic paths on Windows
        raw = f.read()
    w = rl.load_wave_from_memory(os.path.splitext(path)[1].lower(), raw, len(raw))
    try:
        if w.frameCount <= 0:
            return False
        if w.sampleSize not in (16, 32):
            rl.wave_format(w, 48000, 16, w.channels)
        ch, sr, n_all = w.channels, w.sampleRate, w.frameCount
        if w.sampleSize == 32:
            a = np.frombuffer(rl.ffi.buffer(rl.ffi.cast("float *", w.data), n_all * ch * 4), dtype=np.float32)
        else:
            a = np.frombuffer(rl.ffi.buffer(rl.ffi.cast("short *", w.data), n_all * ch * 2), dtype=np.int16).astype(np.float32) / 32768.0
        n = min(n_all, int(frag * sr))
        if n_all > 20 * sr:                            # at most 60 % of the song, so the cut can start anywhere in it
            n = min(n, int(n_all * 0.6))
        st = random.randint(0, max(0, n_all - n - sr)) if n_all > n + sr else 0
        seg = np.array(a[st * ch:(st + n) * ch], dtype=np.float32).reshape(n, ch)
        fi, fo = min(n // 2, int(0.25 * sr)), min(n // 2, int(0.9 * sr))
        seg[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)[:, None]
        seg[n - fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]
        if muffle:                                     # heard through a closed car body: low-pass ~500 Hz, quieter
            fq = np.fft.rfftfreq(n, 1.0 / sr)
            gain = 1.0 / np.sqrt(1.0 + (fq / 500.0) ** 6)
            for c_ in range(ch):
                seg[:, c_] = np.fft.irfft(np.fft.rfft(seg[:, c_]) * gain, n)
            seg *= 0.7
        if fx is not None:                             # extra shaping, e.g. the loading screen's distant-radio sound
            seg = fx(seg, sr)
        pcm = (np.clip(seg, -1, 1) * 32000).astype("<i2")
        with wave.open(out_wav, "wb") as f:
            f.setnchannels(ch)
            f.setsampwidth(2)
            f.setframerate(sr)
            f.writeframes(pcm.tobytes())
        return True
    finally:
        rl.unload_wave(w)


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
    """Plays pre-cut fragments as in-memory sounds (no streaming: streamed mp3 under a slow frame rate underran and
    crackled).  A worker thread prepares the next fragment while the current one plays."""

    def __init__(self, aud):
        self.aud = aud
        self.stations = []
        self.sel = 0                   # station index; == len(stations) means "radio off"
        self.snd = None
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
        self._dir = None
        self._job = None               # running worker: dict(station, thread, out, title, path, ok)
        self._ready = None             # finished job for the current station
        self._seq = 0
        self._burst_len = 0.3
        if not aud.ok:
            return
        try:
            os.makedirs(MUSIC, exist_ok=True)
            hp = os.path.join(MUSIC, "README.txt")
            if not os.path.exists(hp):
                with open(hp, "w", encoding="utf-8") as f:
                    f.write(HINT)
            self._dir = tempfile.mkdtemp(prefix="skopje_radio_")
            p = os.path.join(self._dir, "static.wav")
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
        self.hint = "" if self.stations else TXT("radio.0009")

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
            return TXT("radio.0010")
        nm = self.stations[self.sel][0]
        return (TXT("radio.0011") + f'{nm}') + (f" – {self.now}" if self.now else "") + "   [Q/E]"

    def step(self, d):
        """Change station by d (wraps, with an 'off' slot at the end).  Returns a banner text."""
        if not self.stations:
            self.rescan()
            return self.hint
        n = len(self.stations) + 1
        self.sel = (self.sel + d) % n
        self.user_off = self.sel >= len(self.stations)
        self._ready = None
        if self.user_off:
            self._silence()
            return TXT("radio.0012")
        self._burst()
        return TXT("radio.0013") + self.stations[self.sel][0]

    # ---- fragment preparation (worker thread)
    def _prepare(self):
        """Start cutting the next fragment for the current station unless one is ready / running."""
        if self._ready is not None or self._job is not None or self.off or not self._dir:
            return
        pool = list(self.stations[self.sel][1])
        random.shuffle(pool)
        if self.cur in pool and len(pool) > 1:
            pool.remove(self.cur)
        self._seq += 1
        job = {"station": self.sel, "out": os.path.join(self._dir, f"frag{self._seq % 3}.wav"), "ok": False, "done": False, "path": None}

        def work():
            for p in pool[:6]:
                try:
                    if cut_fragment(p, job["out"], random.uniform(*FRAG)):
                        job["ok"], job["path"] = True, p
                        print(f"[radio] playing a part of {p}", flush=True)
                        break
                except Exception as e:  # noqa: BLE001
                    print(f"[radio] FAILED {p}: {e}", flush=True)
                    continue
                print(f"[radio] cannot decode {p}", flush=True)
            job["done"] = True

        job["thread"] = threading.Thread(target=work, daemon=True)
        self._job = job
        job["thread"].start()

    def _collect(self):
        j = self._job
        if j is not None and j["done"]:
            self._job = None
            if j["station"] == self.sel and not self.off:
                if j["ok"]:
                    self._ready = j
                else:
                    self.rescan()
                    self._ready = None

    def _start_play(self):
        rl = self._rl()
        j, self._ready = self._ready, None
        try:
            snd = rl.load_sound(j["out"])
            if not rl.is_sound_valid(snd):
                return False
            self.snd, self.cur, self.t = snd, j["path"], 0.0
            self.now = os.path.splitext(os.path.basename(j["path"]))[0].replace("_", " ")
            rl.set_sound_volume(snd, self.volume * self.aud.master)
            rl.play_sound(snd)
            self.state = "play"
            return True
        except Exception:  # noqa: BLE001
            return False

    def _stop_music(self):
        if self.snd is not None:
            try:
                self._rl().stop_sound(self.snd)
                self._rl().unload_sound(self.snd)
            except Exception:  # noqa: BLE001
                pass
            self.snd = None

    def _burst(self, dur=0.3):
        rl = self._rl()
        self._stop_music()
        self.state, self.t, self.now = "static", 0.0, ""
        self._burst_len = dur
        try:
            rl.set_sound_volume(self.static, 0.25 * self.volume * self.aud.master)
            rl.play_sound(self.static)
        except Exception:  # noqa: BLE001
            pass

    def _silence(self):
        self._stop_music()
        self._ready = None
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
            if in_vehicle and not self.stations:
                self._scan_t += dt
                if self._scan_t > 5.0:                       # music dropped in while playing
                    self._scan_t = 0.0
                    self.rescan()
            return None
        if self.state == "off":                      # just got in: rescan (files may have been added), tune in
            self.rescan()
            if not self.off:
                self._burst(0.3)
            return None
        self.t += dt
        self._collect()
        self._prepare()
        if self.state == "static":
            if self.t > self._burst_len and self._ready is not None and self._start_play():
                return self.now
            if self.t > self._burst_len and not rl.is_sound_playing(self.static) and self.t < 30:
                if self._ready is None:                       # still decoding: keep a faint hiss going
                    rl.set_sound_volume(self.static, 0.12 * volume * self.aud.master)
                    rl.play_sound(self.static)
            return None
        try:
            rl.set_sound_volume(self.snd, volume * self.aud.master)
            if not rl.is_sound_playing(self.snd):
                self._burst(random.uniform(0.15, 0.3))
        except Exception:  # noqa: BLE001
            self._burst()
        return None

    def close(self):
        self._stop_music()


class CabinMusic:
    """Some traffic cars (about 1 in 4, up to three near you at once) play the radio inside: heard from outside only as a
    quiet, muffled (low-passed) thump that swells as they pass.  Fragments are cut ahead by a worker thread from music/."""

    RANGE = 38.0
    MAX = 3

    def __init__(self, aud, radio):
        self.aud, self.radio = aud, radio
        self.play = []                     # [(sound, car)]
        self.ready = []                    # paths of finished muffled fragments, not loaded yet
        self.job = None
        self.n = 0
        self.t = 0.0

    def _rl(self):
        return audio_mod.rl

    def _prepare(self):
        if len(self.ready) >= 2 or self.job is not None or not self.radio._dir:
            return
        files = [p for _n, ps in self.radio.stations for p in ps]
        if not files:
            return
        self.n += 1
        job = {"out": os.path.join(self.radio._dir, f"cab{self.n % 5}.wav"), "ok": False, "done": False}
        pick = random.sample(files, min(4, len(files)))

        def work():
            for p in pick:
                try:
                    if cut_fragment(p, job["out"], random.uniform(20.0, 38.0), muffle=True):
                        job["ok"] = True
                        break
                except Exception:  # noqa: BLE001
                    continue
            job["done"] = True

        self.job = job
        threading.Thread(target=work, daemon=True).start()

    def _stop_one(self, snd):
        try:
            self._rl().stop_sound(snd)
            self._rl().unload_sound(snd)
        except Exception:  # noqa: BLE001
            pass

    def _stop(self):
        for snd, _c in self.play:
            self._stop_one(snd)
        self.play = []

    def update(self, dt, cars, fx, fy, active, volume):
        """cars: traffic cars; active: False while you sit in a car yourself or the game is muted."""
        if not self.aud.ok or not active or volume <= 0.01 or not self.radio.stations:
            if self.play:
                self._stop()
            return
        rl = self._rl()
        if self.job is not None and self.job["done"]:
            if self.job["ok"]:
                self.ready.append(self.job["out"])
            else:
                self.t = -30.0             # decoding failed: do not hammer the disk
            self.job = None
        self.t += dt
        if self.t >= 0:
            self._prepare()
        keep = []
        for snd, c in self.play:           # the playing ones: louder as the car comes close, gone when it is far
            d = ((c.x - fx) ** 2 + (c.y - fy) ** 2) ** 0.5
            try:
                if c not in cars or d > self.RANGE or not rl.is_sound_playing(snd):
                    self._stop_one(snd)
                    continue
                k = 1.0 - d / self.RANGE
                rl.set_sound_volume(snd, 0.5 * k * k * volume * self.aud.master)
                rl.set_sound_pan(snd, 0.5 + 0.4 * max(-1.0, min(1.0, (c.x - fx) / max(d, 8.0))))
                keep.append((snd, c))
            except Exception:  # noqa: BLE001
                self._stop_one(snd)
        self.play = keep
        if not self.ready or len(self.play) >= self.MAX:
            return
        busy = {id(c) for _s, c in self.play}
        best, bd = None, self.RANGE * 0.8
        for c in cars:
            if c.cab and id(c) not in busy and abs(c.x - fx) < bd and abs(c.y - fy) < bd:
                d = ((c.x - fx) ** 2 + (c.y - fy) ** 2) ** 0.5
                if d < bd:
                    best, bd = c, d
        if best is None:
            return
        try:
            snd = rl.load_sound(self.ready.pop(0))
            if not rl.is_sound_valid(snd):
                return
            best.cab = False               # one song per car
            rl.set_sound_volume(snd, 0.0)
            rl.play_sound(snd)
            self.play.append((snd, best))
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        self._stop()
