"""Procedural sound: every effect is synthesised with numpy at start-up (no asset files), played through raylib.
If there is no audio device (or anything fails) every call quietly does nothing."""
import math
import os
import random
import tempfile
import wave
from collections import OrderedDict

import numpy as np
import pyray as rl

import soundcat
import soundlib

SR = 22050


def _save(path, x, sr=SR):
    x = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32000).astype(np.int16).tobytes())


def _t(d):
    return np.arange(int(d * SR), dtype=np.float32) / SR


def _lp(x, k):
    """crude one-pole-ish low-pass via moving average"""
    k = max(1, int(k))
    return np.convolve(x, np.ones(k, np.float32) / k, mode="same")


def _env(n, a=0.005, d=0.3):
    t = np.arange(n, dtype=np.float32) / SR
    return np.minimum(1, t / a) * np.exp(-t / d)


def build():
    rng = np.random.default_rng(4)
    S = {}
    # engine loops (whole number of cycles so they loop cleanly): one per engine character
    n = int(SR * 0.5)
    t = np.arange(n, dtype=np.float32) / SR

    def eng(f, nh, decay, am_hz, am_depth, noise=0.0, clatter=0.0):
        x = sum(np.sin(2 * np.pi * f * k * t + k) * (1.0 / k ** decay) for k in range(1, nh)) * (1 + am_depth * np.sin(2 * np.pi * am_hz * t))
        if clatter:
            pulse = (np.sin(2 * np.pi * 20 * t) > 0.85).astype(np.float32)
            x = x + _lp(rng.standard_normal(n).astype(np.float32), 5) * pulse * clatter * 6
        if noise:
            x = x + _lp(rng.standard_normal(n).astype(np.float32), 8) * noise
        return x / np.abs(x).max() * 0.55
    S["engine_i4"] = eng(44.0, 14, 0.8, 8, 0.25)
    S["engine_small"] = eng(70.0, 11, 0.55, 30, 0.45, 0.05)                 # buzzy two-cylinder: Fico, Trabant, Yugo
    S["engine_v8"] = eng(28.0, 18, 0.95, 14, 0.4, 0.04)                     # burbling V8: Mafijash, Hummer, Bavarka
    S["engine_diesel"] = eng(36.0, 16, 0.7, 6, 0.2, 0.03, 1.0)              # clattering diesel: vans, buses, Land Cruiser
    S["engine_truck"] = eng(24.0, 20, 0.85, 4, 0.3, 0.05, 1.3)              # heavy truck / tractor
    ev = np.sin(2 * np.pi * 400 * t) * 0.6 + np.sin(2 * np.pi * 800 * t) * 0.25 + np.sin(2 * np.pi * 1200 * t) * 0.1
    S["engine_ev"] = ev / np.abs(ev).max() * 0.35                           # electric whine: Tesla
    S["engine"] = S["engine_i4"]
    for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev"):
        S["ai_" + nm] = S[nm]                                                # traffic engines: own sound instance so the player's engine is not shared
    # horn
    t = _t(0.55)
    x = (np.sin(2 * np.pi * 415 * t) + 0.6 * np.sin(2 * np.pi * 523 * t) + 0.3 * np.sign(np.sin(2 * np.pi * 415 * t))) * np.minimum(1, t / 0.02) * np.minimum(1, (0.55 - t) / 0.05)
    S["horn"] = x / np.abs(x).max() * 0.5
    # crash: noise burst + low thump
    t = _t(0.7)
    nz = rng.standard_normal(len(t)).astype(np.float32)
    x = _lp(nz, 3) * np.exp(-t / 0.12) + np.sin(2 * np.pi * 70 * t) * np.exp(-t / 0.18) * 1.2
    S["crash"] = x / np.abs(x).max() * 0.8
    # fist and kick
    t = _t(0.16)
    x = np.sin(2 * np.pi * (120 - 380 * t) * t) * np.exp(-t / 0.05) + _lp(rng.standard_normal(len(t)).astype(np.float32), 6) * np.exp(-t / 0.03) * 0.8
    S["punch"] = x / np.abs(x).max() * 0.8
    t = _t(0.22)
    x = np.sin(2 * np.pi * (90 - 200 * t) * t) * np.exp(-t / 0.08) * 1.2 + _lp(rng.standard_normal(len(t)).astype(np.float32), 4) * np.exp(-t / 0.05)
    S["kick"] = x / np.abs(x).max() * 0.85
    # gun
    t = _t(0.35)
    x = rng.standard_normal(len(t)).astype(np.float32) * np.exp(-t / 0.05) + np.sin(2 * np.pi * 120 * t) * np.exp(-t / 0.1)
    S["shot"] = x / np.abs(x).max() * 0.8
    # explosion
    t = _t(1.6)
    x = _lp(rng.standard_normal(len(t)).astype(np.float32), 18) * np.exp(-t / 0.45) * 3 + np.sin(2 * np.pi * 45 * t) * np.exp(-t / 0.5)
    S["boom"] = x / np.abs(x).max() * 0.9
    # splash
    t = _t(0.6)
    x = _lp(rng.standard_normal(len(t)).astype(np.float32), 5) * np.exp(-t / 0.2) * (1 + np.sin(2 * np.pi * 14 * t) * 0.4)
    S["splash"] = x / np.abs(x).max() * 0.6
    # pickup chimes
    t = _t(0.3)
    S["chime"] = (np.sin(2 * np.pi * 660 * t) * np.minimum(1, t / 0.005) + np.sin(2 * np.pi * 990 * np.maximum(t - 0.07, 0)) * (t > 0.07)) * np.exp(-t / 0.12) * 0.45
    t = _t(0.25)
    tk = _t(0.05)
    S["tick"] = (np.sin(2 * np.pi * 1800 * tk) * np.exp(-tk / 0.012) * 0.35).astype(np.float32)
    tw = _t(0.6)
    S["pick"] = ((np.sin(2 * np.pi * (330 + 500 * tw) * tw) + 0.6 * np.sin(2 * np.pi * (495 + 750 * tw) * tw))
                 * np.minimum(1, tw / 0.02) * np.exp(-tw / 0.22) * 0.4).astype(np.float32)
    S["cash"] = (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 1980 * t)) * np.exp(-t / 0.07) * 0.4
    # crunch (eating)
    t = _t(0.4)
    gate = (np.sin(2 * np.pi * 13 * t) > 0.2).astype(np.float32)
    S["eat"] = _lp(rng.standard_normal(len(t)).astype(np.float32), 3) * gate * np.exp(-t / 0.25) * 1.2
    # sirens: police yelp, ambulance hi-lo, fire engine slow wail (each seamless)
    def sweep(period, f0, f1, shape):
        t = _t(period)
        u = shape(t / period)
        fr = f0 + (f1 - f0) * u
        ph = np.cumsum(2 * np.pi * fr / SR)
        x = np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.1 * np.sin(3 * ph)
        return x / np.abs(x).max() * 0.35
    S["siren_police"] = sweep(1.0, 700, 1500, lambda u: 0.5 - 0.5 * np.cos(2 * np.pi * u * 2))
    S["siren_amb"] = sweep(1.2, 700, 950, lambda u: (np.floor(u * 2) % 2).astype(np.float32))
    S["siren_fire"] = sweep(3.2, 380, 820, lambda u: 0.5 - 0.5 * np.cos(2 * np.pi * u))
    S["siren"] = S["siren_police"]
    # horns
    t = _t(0.35)
    x = (np.sin(2 * np.pi * 540 * t) + 0.5 * np.sin(2 * np.pi * 680 * t)) * np.minimum(1, t / 0.01) * np.minimum(1, (0.35 - t) / 0.04)
    S["horn_small"] = x / np.abs(x).max() * 0.45
    t = _t(0.9)
    x = (np.sin(2 * np.pi * 196 * t) + 0.7 * np.sin(2 * np.pi * 247 * t) + 0.4 * np.sign(np.sin(2 * np.pi * 196 * t))) * np.minimum(1, t / 0.03) * np.minimum(1, (0.9 - t) / 0.1)
    S["horn_truck"] = x / np.abs(x).max() * 0.6
    notes = (392, 392, 392, 523, 659)                                       # wedding / ice-cream-van jingle
    x = np.concatenate([np.sin(2 * np.pi * f * _t(0.16)) * np.minimum(1, _t(0.16) / 0.01) * np.minimum(1, (0.16 - _t(0.16)) / 0.03) for f in notes])
    S["horn_jingle"] = x * 0.4
    # tyre screech (loop, modulated band noise)
    t = _t(1.0)
    nz = rng.standard_normal(len(t)).astype(np.float32)
    x = (nz - _lp(nz, 14)) * 0.5 * (1 + 0.3 * np.sin(2 * np.pi * 9 * t))
    S["screech"] = _loopify(x / np.abs(x).max() * 0.4, 0.1)
    # water spray (loop)
    t = _t(1.0)
    x = _lp(rng.standard_normal(len(t)).astype(np.float32), 3) * (1 + 0.3 * np.sin(2 * np.pi * 13 * t))
    S["spray"] = _loopify(x / np.abs(x).max() * 0.4, 0.1)
    # building site (loop 6 s): diesel mixer drum rumble, irregular hammer blows, a drill burst and a metal clank
    t = _t(6.0)
    nz = rng.standard_normal(len(t)).astype(np.float32)
    x = _lp(nz, 50) * 5 * (1 + 0.3 * np.sin(2 * np.pi * 1.6 * t)) + 0.5 * np.sin(2 * np.pi * 46 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.8 * t))
    for st in (0.4, 0.95, 1.5, 2.4, 2.8, 3.3, 4.3, 4.65, 5.3):                         # hammer: sharp tick + short ring
        i0 = int(st * SR)
        tt = _t(0.18)
        blow = (np.sin(2 * np.pi * 1100 * tt) * 0.5 + rng.standard_normal(len(tt)).astype(np.float32) * 0.6) * np.exp(-tt / 0.012)
        x[i0:i0 + len(tt)] += blow * 3.0
    tt = _t(0.9)
    drill = np.sign(np.sin(2 * np.pi * 170 * tt)) * 0.5 * (np.sin(2 * np.pi * 14 * tt) > -0.2) * np.minimum(1, tt / 0.05) * np.minimum(1, (0.9 - tt) / 0.1)
    i0 = int(3.5 * SR)
    x[i0:i0 + len(tt)] += drill * 1.6
    tt = _t(0.7)
    i0 = int(1.9 * SR)
    x[i0:i0 + len(tt)] += (np.sin(2 * np.pi * 1850 * tt) + 0.6 * np.sin(2 * np.pi * 2610 * tt)) * np.exp(-tt / 0.15) * 1.2        # steel clank
    S["construction"] = _loopify(x / np.abs(x).max() * 0.45)
    # ambience: crowd murmur, traffic roar, wind, dog bark, church bell
    t = _t(6.0)
    nz = rng.standard_normal(len(t)).astype(np.float32)
    voice = _lp(nz, 9) - _lp(nz, 30)
    syl = 0.55 + 0.45 * np.sin(2 * np.pi * 3.7 * t + 3 * np.sin(2 * np.pi * 0.3 * t)) * np.sin(2 * np.pi * 5.3 * t)
    x = voice * syl
    S["crowd"] = _loopify(x / np.abs(x).max() * 0.4)
    x = _lp(nz, 40) * 5 * (1 + 0.25 * np.sin(2 * np.pi * t / 2.0)) + _lp(nz, 8) * 0.5
    S["traffic"] = _loopify(x / np.abs(x).max() * 0.4)
    x = _lp(nz, 120) * 8 * (0.6 + 0.4 * np.sin(2 * np.pi * t / 6.0 + 1))
    S["wind"] = _loopify(x / np.abs(x).max() * 0.35)
    t = _t(0.5)
    x = np.zeros(len(t), np.float32)
    for st in (0.0, 0.2):
        i0 = int(st * SR)
        tt = _t(0.12)
        fr = 520 - 700 * tt
        x[i0:i0 + len(tt)] += (np.sin(np.cumsum(2 * np.pi * fr / SR)) + 0.4 * _lp(rng.standard_normal(len(tt)).astype(np.float32), 4)) * np.exp(-tt / 0.06)
    S["dog"] = x / np.abs(x).max() * 0.5
    t = _t(3.0)
    x = sum(np.sin(2 * np.pi * f * t) * a for f, a in ((196, 1.0), (392, 0.5), (588, 0.3), (237, 0.4))) * np.exp(-t / 0.9)
    S["bell"] = x / np.abs(x).max() * 0.5
    t = _t(0.5)
    S["revive"] = (np.sin(2 * np.pi * 523 * t) * (t < 0.15) + np.sin(2 * np.pi * 659 * t) * ((t >= 0.15) & (t < 0.3)) + np.sin(2 * np.pi * 784 * t) * (t >= 0.3)) * np.exp(-(t % 0.15) / 0.2) * 0.4
    # city ambience: rumble + distant hiss (loop 6 s, faded ends)
    t = _t(6.0)
    nz = rng.standard_normal(len(t)).astype(np.float32)
    x = _lp(nz, 60) * 6 + _lp(nz, 6) * 0.4
    x *= 1 + 0.15 * np.sin(2 * np.pi * t / 3.0)
    S["city"] = _loopify(x / np.abs(x).max() * 0.35)
    # birds: sparse chirps
    t = _t(8.0)
    x = np.zeros(len(t), np.float32)
    for _ in range(9):
        st = rng.uniform(0.2, 7.2)
        i0 = int(st * SR)
        tt = _t(0.16)
        fr = 3000 + rng.uniform(0, 1200) + 900 * np.sin(2 * np.pi * rng.uniform(14, 26) * tt)
        x[i0:i0 + len(tt)] += np.sin(np.cumsum(2 * np.pi * fr / SR)) * np.exp(-tt / 0.07) * 0.5
    S["birds"] = _loopify(x)
    # crickets
    t = _t(4.0)
    carr = np.sin(2 * np.pi * 4300 * t)
    gate = (np.sin(2 * np.pi * 36 * t) > 0.4) * (np.sin(2 * np.pi * 2.0 * t) > -0.3)
    S["crickets"] = _loopify((carr * gate * 0.25).astype(np.float32))
    return S


def _loopify(x, fade=0.25):
    n = int(fade * SR)
    x = x.copy()
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    x[:n] = x[:n] * ramp + x[-n:] * (1 - ramp)
    return x[:-n]


class Audio:
    LOOPS = ("ai_engine_i4", "ai_engine_small", "ai_engine_v8", "ai_engine_diesel", "ai_engine_truck", "ai_engine_ev", "engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev", "siren_police", "siren_amb",
             "siren_fire", "screech", "spray", "construction", "city", "birds", "crickets", "crowd", "traffic", "wind")

    CACHE_MB = 300                                      # decoded library sounds kept in memory (least recently used go first)

    def __init__(self, mute=False, root=None, dry=False):
        self.ok = False
        self.snd = {}
        self.dyn = []                                   # (sound, path) for speech clips, unloaded when finished
        self.master = 0.8
        self.bus = {"sfx": 1.0, "ambient": 1.0, "speech": 1.0, "engine": 1.0}
        self.muted = False
        self._tmp = None
        self.lib, self.req = {}, (0, 0, 0)              # v2.1 artist library: key -> mp3 paths; (requests written, catalogue size, done)
        self._ls, self._ls_mb, self._cur, self._last, self._vol = OrderedDict(), 0.0, {}, {}, {}
        self.lx = self.ly = 0.0
        self.dry, self.stats = dry, {}                 # dry run (cloud tests, no audio device): count what would play, library vs fallback
        self.rng = random.Random(21)
        if root:
            try:
                lib_root = os.environ.get("SK242_LIBRARY") or os.path.join(root, soundlib.LIB_DIR)
                self.lib = soundlib.scan(lib_root)
                self.req = soundlib.write_requests(root, self.lib)
            except Exception:  # noqa: BLE001
                pass
        if dry:
            self.snd = dict.fromkeys(build())
            self.ok = True
            return
        if mute:
            self.muted = True
            return
        try:
            rl.init_audio_device()
            if not rl.is_audio_device_ready():
                return
            self._tmp = tempfile.mkdtemp(prefix="skopje_snd_")
            for name, x in build().items():
                p = os.path.join(self._tmp, name + ".wav")
                _save(p, x)
                self.snd[name] = rl.load_sound(p)
            self.ok = True
        except Exception:  # noqa: BLE001
            self.ok = False

    # ---- v2.1 library: pick a version, balance its loudness, place it in space
    def listener(self, x, y):
        self.lx, self.ly = x, y

    def has_lib(self, name):
        return soundcat.ALIAS.get(name, name) in self.lib

    def _lib_load(self, name, path, row):
        """Decode an mp3 once, level it (loops by RMS, one-shots by peak, scaled by the catalogue level) and keep it cached."""
        k = (name, path)
        if k in self._ls:
            self._ls.move_to_end(k)
            return self._ls[k][0]
        w = rl.load_wave(path)
        try:
            n = w.frameCount * w.channels
            if n <= 0 or w.sampleSize not in (16, 32):
                return None
            f32 = w.sampleSize == 32                                 # raylib decodes mp3 to 32-bit float, wav to 16-bit
            a = np.frombuffer(rl.ffi.buffer(w.data, n * (4 if f32 else 2)), dtype=np.float32 if f32 else np.int16)
            x = a if f32 else a.astype(np.float32) / 32768.0
            pk = float(np.abs(x).max()) or 1e-4
            g = (0.02 + 0.10 * row[6]) / (float(np.sqrt((x * x).mean())) + 1e-5) if row[2] else (0.35 + 0.6 * row[6]) / pk
            g = min(g, 0.98 / pk)
            a[:] = x * g if f32 else np.clip(x * g * 32767.0, -32767, 32767).astype(np.int16)
            s = rl.load_sound_from_wave(w)
        finally:
            rl.unload_wave(w)
        mb = n * (4 if f32 else 2) / 1e6
        self._ls[k] = (s, mb)
        self._ls_mb += mb
        for _ in range(len(self._ls)):
            if self._ls_mb <= self.CACHE_MB or len(self._ls) < 2:
                break
            (k0, (s0, mb0)) = next(iter(self._ls.items()))
            if k0 == k or any(c is s0 for c in self._cur.values()):
                self._ls.move_to_end(k0)
                continue
            del self._ls[k0]
            rl.unload_sound(s0)
            self._ls_mb -= mb0
        return s

    def _pick(self, name):
        """(sound, from_library, row): a random library version (never the one played last) or the procedural fallback."""
        key = soundcat.ALIAS.get(name, name)
        row = soundcat.BY_KEY.get(key)
        paths = self.lib.get(key)
        if self.dry:
            fb = name if name in self.snd else (row[7] if row and row[7] in self.snd else None)
            src = "lib" if paths and row else ("fallback:" + fb if fb else None)
            if src:
                self.stats[(name, src)] = self.stats.get((name, src), 0) + 1
            return (self if src else None), bool(paths), row
        if paths and row:
            for _ in range(len(paths)):
                last = self._last.get(name)
                p = self.rng.choice(paths) if len(paths) < 2 else self.rng.choice([q for q in paths if q != last])
                self._last[name] = p
                try:
                    s = self._lib_load(name, p, row)
                except Exception:  # noqa: BLE001
                    s = None
                if s is not None:
                    return s, True, row
                paths = [q for q in paths if q != p]
                if not paths:
                    break
        fb = name if name in self.snd else (row[7] if row and row[7] in self.snd else None)
        return (self.snd[fb] if fb else None), False, row

    def at(self, name, x, y, vol=1.0, pitch=1.0, bus="sfx", maxd=140.0, ref=8.0):
        """One-shot placed in the world: quieter with distance (silent beyond maxd), panned by where it is from the listener."""
        d = math.hypot(x - self.lx, y - self.ly)
        if d >= maxd:
            return
        k = (ref / max(d, ref)) * (1.0 - (d / maxd) ** 2)
        self.play(name, vol * k, pitch, bus, 0.5 + 0.45 * max(-1.0, min(1.0, (x - self.lx) / max(d, 12.0))))

    def _set(self, s, vol, pitch, bus, pan):
        rl.set_sound_volume(s, min(1.0, vol) * self.master * self.bus.get(bus, 1.0))
        rl.set_sound_pitch(s, pitch)
        rl.set_sound_pan(s, pan)

    def play(self, name, vol=1.0, pitch=1.0, bus="sfx", pan=0.5):
        if not self.ok or self.muted or vol <= 0.01:
            return
        try:
            s, lib, row = self._pick(name)
            if s is None:
                return
            if self.dry:
                return
            if lib and not row[2]:
                pitch = 1.0 + self.rng.uniform(-0.04, 0.04)         # real recordings already vary; only a touch of detune
            self._set(s, vol, pitch, bus, pan)
            rl.play_sound(s)
        except Exception:  # noqa: BLE001
            pass

    def loop(self, name, vol, pitch=1.0, bus="ambient", pan=0.5):
        """Keep a looping sound going at the given volume (0 stops it).  A library loop starts another version each time it wraps."""
        if not self.ok:
            return
        try:
            if self.dry:
                if vol > 0.01:
                    self._pick(name)
                return
            s = self._cur.get(name)
            if self.muted:
                vol = self._vol[name] = 0.0
            elif bus == "ambient":                                  # ambience eases in and out instead of jumping with the place
                v0 = self._vol.get(name, 0.0)
                vol = self._vol[name] = v0 + (vol - v0) * 0.05 if abs(vol - v0) > 0.004 else vol
            if vol <= 0.01 or self.muted:
                if s is not None and rl.is_sound_playing(s):
                    rl.stop_sound(s)
                return
            if s is None or not rl.is_sound_playing(s):
                s = self._pick(name)[0]
                if s is None:
                    return
                self._cur[name] = s
                self._set(s, vol, pitch, bus, pan)
                rl.play_sound(s)
                return
            self._set(s, vol, pitch, bus, pan)
        except Exception:  # noqa: BLE001
            pass

    def speak(self, pcm, vol, sr=SR):
        if not self.ok or self.muted:
            return
        try:
            p = os.path.join(self._tmp, f"sp{len(self.dyn) % 8}_{id(pcm) & 0xffff}.wav")
            _save(p, pcm.astype(np.float32) / 32768.0, sr)
            for o, _p in self.dyn:                     # never two voices at once
                rl.stop_sound(o)
            s = rl.load_sound(p)
            rl.set_sound_volume(s, min(1.0, vol) * self.master * self.bus.get("speech", 1.0))
            rl.play_sound(s)
            self.dyn.append((s, p))
        except Exception:  # noqa: BLE001
            pass

    def speaking(self):
        return any(rl.is_sound_playing(s) for s, _p in self.dyn)

    def reap(self):
        keep = []
        for s, p in self.dyn:
            try:
                if rl.is_sound_playing(s):
                    keep.append((s, p))
                else:
                    rl.unload_sound(s)
                    os.remove(p)
            except Exception:  # noqa: BLE001
                pass
        self.dyn = keep

    def close(self):
        try:
            for s in self.snd.values():
                rl.unload_sound(s)
            for s, _mb in self._ls.values():
                rl.unload_sound(s)
            rl.close_audio_device()
        except Exception:  # noqa: BLE001
            pass
