"""Procedural Macedonian-ish speech: a small formant synthesiser driven by the Latin-script text the game shows.

Text -> phoneme list (letters / digraphs map one-to-one in Macedonian) -> per-sample formant, voicing and noise
tracks -> harmonic source shaped by three formant resonances plus band-shaped noise for fricatives and bursts.
It is deliberately robotic; it only needs to be recognisably 'someone saying this'.  numpy only.
"""
import os
import hashlib
import queue
import threading

import numpy as np

SR = 22050

# phoneme -> kind, formants (F1,F2,F3), duration (s), voiced amp, noise amp, noise band weights (lo, mid, hi)
_V = {"a": (800, 1250, 2600), "e": (520, 1800, 2500), "i": (300, 2250, 3000), "o": (520, 900, 2500), "u": (330, 850, 2300)}
PH = {}
for _k, _f in _V.items():
    PH[_k] = (_f, 0.115, 1.0, 0.0, (0, 0, 0))
PH.update({
    "j": ((290, 2200, 3000), 0.06, 0.7, 0.0, (0, 0, 0)),
    "l": ((380, 1100, 2700), 0.07, 0.65, 0.0, (0, 0, 0)),
    "r": ((450, 1300, 2400), 0.07, 0.6, 0.0, (0, 0, 0)),
    "m": ((260, 1100, 2200), 0.08, 0.5, 0.0, (0, 0, 0)),
    "n": ((260, 1500, 2500), 0.075, 0.5, 0.0, (0, 0, 0)),
    "v": ((300, 1100, 2300), 0.065, 0.35, 0.22, (0, 1, 2)),
    "z": ((260, 1800, 2600), 0.08, 0.3, 0.45, (0, 1, 3)),
    "zh": ((260, 1700, 2500), 0.09, 0.3, 0.5, (1, 3, 1)),
    "s": ((300, 1800, 2600), 0.1, 0.0, 0.8, (0, 1, 4)),
    "sh": ((300, 1800, 2600), 0.11, 0.0, 0.8, (1, 4, 1)),
    "f": ((300, 1800, 2600), 0.09, 0.0, 0.35, (1, 2, 2)),
    "h": ((500, 1500, 2500), 0.08, 0.0, 0.3, (3, 2, 1)),
    "b": ((250, 1000, 2200), 0.05, 0.35, 0.2, (1, 1, 0)),
    "d": ((250, 1700, 2600), 0.05, 0.35, 0.25, (0, 2, 2)),
    "g": ((250, 1300, 2200), 0.055, 0.35, 0.25, (1, 2, 0)),
    "p": ((250, 1000, 2200), 0.06, 0.0, 0.55, (1, 1, 0)),
    "t": ((250, 1700, 2600), 0.06, 0.0, 0.6, (0, 2, 3)),
    "k": ((250, 1300, 2200), 0.065, 0.0, 0.6, (1, 3, 1)),
    "c": ((250, 1700, 2600), 0.09, 0.0, 0.6, (0, 2, 4)),       # ts
    "ch": ((250, 1700, 2600), 0.1, 0.0, 0.65, (1, 4, 2)),
    "dz": ((250, 1700, 2600), 0.08, 0.25, 0.5, (0, 2, 3)),
    "dj": ((250, 2000, 2800), 0.08, 0.3, 0.4, (0, 2, 2)),
})
_DIGRAPH = {"sh": "sh", "ch": "ch", "zh": "zh", "dz": "dz", "dj": "dj", "gj": "dj", "kj": "ch"}
_PAUSE = {",": 0.14, ".": 0.26, "!": 0.3, "?": 0.3, "-": 0.1, ":": 0.14, ";": 0.14, " ": 0.04}
_FOLD = str.maketrans({"é": "e", "è": "e", "á": "a", "à": "a", "ć": "ch", "č": "ch", "š": "sh", "ž": "zh", "ѓ": "dj", "ќ": "ch"})


# Cyrillic (the game's own script) -> the Latin spelling the formant synthesiser works with
_C2L = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ѓ": "dj", "е": "e", "ѐ": "e", "ж": "zh", "з": "z", "ѕ": "dz", "и": "i", "ѝ": "i",
        "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "ќ": "kj",
        "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "џ": "dj", "ш": "sh"}


def cyr_to_latin(text):
    return "".join(_C2L.get(ch, ch) for ch in text.lower())


def _parse(text):
    """-> list of (phoneme | None, extra) with None meaning a pause of `extra` seconds; also word starts and the final mark."""
    s = cyr_to_latin(text).translate(_FOLD)
    out = []
    i = 0
    word_start = True
    while i < len(s):
        c = s[i]
        two = s[i:i + 2]
        if two in _DIGRAPH and not (two == "dz" and False):
            out.append((_DIGRAPH[two], word_start))
            word_start = False
            i += 2
        elif c in PH:
            out.append((c, word_start))
            word_start = False
            i += 1
        elif c in ("q", "x", "w", "y"):
            out.append(({"q": "k", "x": "k", "w": "v", "y": "i"}[c], word_start))
            word_start = False
            i += 1
        elif c in _PAUSE:
            out.append((None, _PAUSE[c]))
            word_start = True
            i += 1
        else:
            i += 1
    return out


def _smooth(a, n):
    k = np.ones(n, np.float32) / n
    return np.convolve(np.pad(a, (n, n), mode="edge"), k, mode="same")[n:-n]


def _band_noise(n, rng):
    spec = np.fft.rfft(rng.standard_normal(n).astype(np.float32))
    fr = np.fft.rfftfreq(n, 1.0 / SR)
    bands = []
    for lo, hi in ((600, 2200), (2200, 5200), (5200, 10000)):
        m = ((fr >= lo) & (fr <= hi)).astype(np.float32)
        bands.append(np.fft.irfft(spec * m, n).astype(np.float32))
    return bands


def synth(text, f0=125.0, speed=1.0, formant=1.0):
    """-> int16 numpy array of mono speech at SR."""
    seq = _parse(text)
    if not seq:
        return np.zeros(SR // 10, np.int16)
    rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
    segs = []        # (dur, F, av, an, bands, stress, plosive_gap)
    for ph, extra in seq:
        if ph is None:
            segs.append((extra, (500, 1500, 2500), 0.0, 0.0, (0, 0, 0), False, 0.0))
            continue
        F, d, av, an, bw = PH[ph]
        gap = 0.035 if ph in "pbtdkgc" or ph in ("ch", "dz", "dj") else 0.0
        segs.append((d / speed, F, av, an, bw, bool(extra) and ph in _V, gap / speed))
    q = text.strip()[-1:] if text.strip() else "."
    # --- lay the segments out in time
    tot = sum(s[0] + s[6] for s in segs)
    n = int(tot * SR) + int(0.05 * SR)
    F = np.zeros((3, n), np.float32)
    av = np.zeros(n, np.float32)
    an = np.zeros(n, np.float32)
    bw = np.zeros((3, n), np.float32)
    stress = np.zeros(n, np.float32)
    pos = 0
    last = (500, 1500, 2500)
    for d, f, v, nz, b, st, gap in segs:
        pos += int(gap * SR)
        m = int(d * SR)
        sl = slice(pos, pos + m)
        for k in range(3):
            F[k, sl] = f[k]
        av[sl] = v
        an[sl] = nz
        for k in range(3):
            bw[k, sl] = b[k] / (sum(b) or 1)
        if st:
            stress[sl] = 1.0
        if v > 0.0 and v < 1.0 and an[sl].mean() > 0:
            pass
        last = f
        pos += m
    # coarticulation: smooth every track over ~30 ms
    w = int(0.03 * SR)
    for k in range(3):
        F[k] = _smooth(F[k], w)
        bw[k] = _smooth(bw[k], w)
    av = _smooth(av, int(0.02 * SR))
    an = _smooth(an, int(0.008 * SR))
    stress = _smooth(stress, int(0.04 * SR))
    F *= formant
    # --- pitch contour: declination, stress accent, question rise
    t = np.linspace(0, 1, n, dtype=np.float32)
    f0t = f0 * (1.08 - 0.2 * t) * (1 + 0.1 * stress)
    if q == "?":
        f0t *= 1 + 0.35 * np.clip((t - 0.7) / 0.3, 0, 1)
    elif q == "!":
        f0t *= 1 + 0.12 * np.sin(np.pi * np.clip(t * 1.4, 0, 1))
    f0t *= 1 + 0.012 * np.sin(2 * np.pi * 5.0 * np.arange(n) / SR)          # vibrato = less buzzy
    phase = np.cumsum(2 * np.pi * f0t / SR).astype(np.float32)
    # --- voiced source: harmonics weighted by three formant gaussians
    voiced = np.zeros(n, np.float32)
    K = int(min(5200.0, SR / 2 - 200) / (f0 * 0.9))
    BW = (80.0, 110.0, 170.0)
    G = (1.0, 0.7, 0.35)
    for k in range(1, K + 1):
        fr = k * f0t
        a = np.zeros(n, np.float32)
        for i in range(3):
            a += G[i] * np.exp(-0.5 * ((fr - F[i]) / BW[i]) ** 2)
        a += 0.05 * np.exp(-fr / 900.0)                                            # glottal tilt floor
        voiced += a * np.sin(k * phase) / (k ** 0.35)
    voiced *= av
    nb = _band_noise(n, rng)
    noise = (nb[0] * bw[0] + nb[1] * bw[1] + nb[2] * bw[2]) * an * 1.4
    sig = voiced * 0.22 + noise
    # fade in/out and normalise
    fade = np.minimum(1.0, np.minimum(np.arange(n), n - np.arange(n)) / (0.01 * SR)).astype(np.float32)
    sig *= fade
    pk = float(np.max(np.abs(sig))) or 1.0
    return (sig / pk * 0.85 * 32767).astype(np.int16)


# --- who speaks: gender, age and temper decide pitch / tempo / loudness / roughness (names are the ones the game shows)
_FEMALE = ("баба", "мајка", "девојка", "невеста", "инфлуенсерка", "киоск", "маца", "теткица", "туристка", "продавачка", "дама", "комшика",
           "студентка", "фитка", "шмизла", "административка", "наставничка", "baba", "majka", "devojka", "nevesta", "maca", "tetkica")
_CHILD = ("дете", "мали", "палавко", "dete", "mali")
_ROUGH = ("чичко", "кумплунг", "работник", "пандур", "навивач", "теретанец", "рибар", "дедо", "кочијаш", "гастарбајтер", "паркинг", "комунален",
          "мафија", "таксист", "бизнисмен", "бурегџија", "скејтер", "доставувач", "велосипедист", "пензионер", "џогер", "ролер", "стојан", "билдер", "војник", "бурек-мајстор", "боза-мајстор", "средношколец")
_SOFT = ("поп", "студент", "хипстер", "инфлуенс", "доктор", "девојка", "невеста", "мајка", "теткица", "туристка", "водич", "маца",
         "адвокат", "голубар", "гулабар", "фитка", "шмизла", "административка")
_OLD = ("баба", "дедо", "пензионер", "чичко", "поп", "кафеански", "боза-мајстор", "baba", "dedo")


def profile(who):
    """-> dict: gender 'f'/'m'/'c', k pitch factor of the (female) Suze voice, rate delta, vol, rough 0..1, soft 0..1, vib."""
    w = (who or "").lower()
    h = int(hashlib.md5(w.encode("utf-8")).hexdigest()[:8], 16)
    j = ((h % 1000) / 1000.0 - 0.5) * 0.1                          # every speaker a little different
    child = any(k in w for k in _CHILD)
    female = not child and any(k in w for k in _FEMALE)
    old = any(k in w for k in _OLD)
    rough = any(k in w for k in _ROUGH) and not female
    soft = any(k in w for k in _SOFT) and not rough
    if child:
        p = dict(g="c", k=1.28 + j, rate=2, vol=0.95, rough=0.0, soft=0.0)
    elif female:
        p = dict(g="f", k=1.0 + j * 0.6, rate=0, vol=0.9, rough=0.0, soft=0.0)
        if "баба" in w or "baba" in w or "теткица" in w:
            p["k"] -= 0.06
    else:
        p = dict(g="m", k=0.8 + j * 0.7, rate=0, vol=0.95, rough=0.0, soft=0.0)
    if rough:
        p.update(k=p["k"] * 0.93, rate=p["rate"] - 1, vol=1.0, rough=0.6 if not child else 0.0)
    if soft:
        p.update(k=p["k"] * 1.04, rate=p["rate"] - 1, vol=0.85, soft=0.7)
    if old:
        p.update(rate=p["rate"] - 2, vib=1.0)
    p.setdefault("vib", 0.0)
    p["k"] = max(0.68, min(1.5, p["k"]))
    return p


def voice_for(who):
    """Formant-voice fallback: (f0, speed, formant scale) from the same profile."""
    p = profile(who)
    f0 = {"m": 118.0, "f": 205.0, "c": 290.0}[p["g"]] * (p["k"] / {"m": 0.8, "f": 1.0, "c": 1.28}[p["g"]])
    speed = 1.2 + 0.05 * p["rate"]
    form = {"m": 0.92, "f": 1.08, "c": 1.2}[p["g"]]
    return float(f0), speed, form


# ----------------------------------------------------------------------------------- Suze (RHVoice) voice
_MK_DI = (("dzh", "џ"), ("dz", "ѕ"), ("lj", "љ"), ("nj", "њ"), ("gj", "ѓ"), ("kj", "ќ"), ("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("dj", "ѓ"))
_MK_1 = {"a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "ј", "k": "к", "l": "л",
         "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "z": "з", "q": "к", "w": "в",
         "x": "кс", "y": "и"}


def latin_to_mk(text):
    """Latin-script Macedonian (as the game writes it) -> Cyrillic, which the neural model expects."""
    if any("\u0400" <= ch <= "\u04ff" for ch in text):          # already Cyrillic: keep letters and pauses
        return "".join(ch for ch in text.lower() if ("\u0430" <= ch <= "\u045f") or ch in " ,.!?-:;").strip()
    s = text.lower().translate(_FOLD)
    out, i = [], 0
    while i < len(s):
        for dg, cy in _MK_DI:
            if s.startswith(dg, i):
                out.append(cy)
                i += len(dg)
                break
        else:
            c = s[i]
            out.append(_MK_1.get(c, c if c in " ,.!?-:;" else ""))
            i += 1
    return "".join(out).strip()


class SuzeVoice:
    """Suze - the Macedonian RHVoice voice (FEEIT UKIM / UNICEF, CC BY-NC-ND 4.0), used through Windows speech (SAPI).
    setup.ps1 installs the RHVoice engine + Suze; the game only talks to SAPI (comtypes). All COM calls happen on the
    speech worker thread. If Suze is missing the built-in formant voice speaks instead."""

    NAME = "Suze"

    def __init__(self):
        self.state = "idle"            # idle | ready | missing | error
        self.note = ""
        self._v = self._cc = None

    def load(self):
        """Call on the thread that will synthesise (COM is per thread)."""
        if self.state in ("ready", "missing", "error"):
            return
        try:
            import comtypes
            import comtypes.client as cc
            comtypes.CoInitialize()
            v = cc.CreateObject("SAPI.SpVoice")
            toks = v.GetVoices()
            tok = next((toks.Item(i) for i in range(toks.Count) if self.NAME.lower() in toks.Item(i).GetDescription().lower()), None)
            if tok is None:
                self.state, self.note = "missing", "Сузе не е инсталирана - стартувај run.bat повторно"
                return
            v.Voice = tok
            self._v, self._cc = v, cc
            self.state, self.note = "ready", "Сузе (RHVoice) е подготвена"
        except Exception as e:  # noqa: BLE001 - not Windows / no SAPI: formant voice
            self.state, self.note = "error", f"Сузе не работи: {str(e)[:80]}"

    def synth(self, text, who="", speed=1.0):
        """-> (int16 array, sample rate) or None.  Suze is a female voice: males are pitched down, children up, and
        rough / soft / old speakers get rate, loudness, grit or a tremble from `profile`."""
        if self.state != "ready":
            return None
        p = profile(who)
        self._v.Rate = max(-10, min(10, int(round((speed - 1.0) * 10)) + p["rate"] + int(round((1.0 - p["k"]) * 10))))
        text = text.strip()
        if not text:
            return None
        cc = self._cc
        ms = cc.CreateObject("SAPI.SpMemoryStream")
        fmt = cc.CreateObject("SAPI.SpAudioFormat")
        fmt.Type = 22                                     # SAFT22kHz16BitMono
        ms.Format = fmt
        self._v.AudioOutputStream = ms
        self._v.Speak(text, 0)
        wav = np.frombuffer(bytes(ms.GetData()), dtype=np.int16).astype(np.float32)
        if wav.size < 100:
            return None
        return shape(wav, p), 22050


def shape(wav, p):
    """Pitch (resampling), grit, softness, tremble and loudness of one clip according to the speaker profile."""
    k = p["k"]
    if abs(k - 1.0) > 0.02:
        n = int(len(wav) / k)
        wav = np.interp(np.linspace(0, len(wav) - 1, n), np.arange(len(wav)), wav)
    wav = wav / (float(np.max(np.abs(wav))) or 1.0)
    if p["rough"] > 0:                                    # grit: drive into a soft clip + a little breath noise
        wav = np.tanh(wav * (1.0 + 2.2 * p["rough"])) / np.tanh(1.0 + 2.2 * p["rough"])
        wav = wav + np.random.default_rng(7).normal(0, 0.03 * p["rough"], len(wav))
    if p["soft"] > 0:                                     # softer: dull the top end
        a = 0.35 * p["soft"]
        wav = np.convolve(wav, [a, 1 - 2 * a, a], mode="same")
    if p.get("vib"):                                      # old voices wobble
        tt = np.arange(len(wav)) / 22050.0
        wav = wav * (1.0 + 0.12 * np.sin(2 * np.pi * 5.5 * tt))
    wav = wav / (float(np.max(np.abs(wav))) or 1.0)
    return (wav * p["vol"] * 32767).astype(np.int16)


class SpeechWorker:
    """Synthesises on a background thread; the main thread polls for finished clips -> (key, pcm int16, sample rate)."""

    def __init__(self):
        self.q = queue.Queue(maxsize=6)
        self.done = queue.Queue()
        self.cache = {}
        self.dead = False
        self.speed = 1.3               # talking speed (menu); Suze via SAPI rate, the formant voice directly
        self.engine = 1                # 0 formant, 1 Suze (falls back to the formant voice when Suze is missing)
        self.neural = SuzeVoice()
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def set_engine(self, e):
        self.engine = e

    def set_speed(self, mult):
        if abs(mult - getattr(self, "speed", 1.0)) > 1e-3:
            self.speed = mult
            self.cache.clear()

    def status(self):
        return self.neural.note if self.engine == 1 else ""

    def request(self, key, text, who):
        eff = 1 if (self.engine == 1 and self.neural.state in ("ready", "idle")) else 0
        ck = (key, eff)
        if ck in self.cache:
            pcm, sr = self.cache[ck]
            self.done.put((key, pcm, sr))
            return
        try:
            self.q.put_nowait((key, text, who, eff))
        except queue.Full:
            pass

    def _run(self):
        self.neural.load()                          # COM objects live on this thread
        while not self.dead:
            try:
                key, text, who, eff = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            eff = 1 if eff and self.neural.state == "ready" else 0
            try:
                res = self.neural.synth(text, who, self.speed) if eff else None
                if res is None:
                    f0, sp, fm = voice_for(who)
                    res = (synth(text, f0, sp * self.speed, fm), SR)
                self.cache[(key, eff)] = res
                if len(self.cache) > 120:
                    self.cache.pop(next(iter(self.cache)))
                self.done.put((key, res[0], res[1]))
            except Exception:  # noqa: BLE001 - speech is decoration, never fatal
                pass

    def poll(self):
        try:
            return self.done.get_nowait()
        except queue.Empty:
            return None


if __name__ == "__main__":                       # setup.ps1: prove that Suze speaks
    import sys
    import wave
    sv = SuzeVoice()
    sv.load()
    print("[voice]", sv.state, sv.note)
    if sv.state != "ready":
        sys.exit(1)
    pcm, sr = sv.synth("Добредојде во Скопје, брате! Ајде, вози.", "test")
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "voice_test.wav")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes(pcm.tobytes())
    print(f"[voice] OK: {len(pcm) / sr:.1f} s of speech -> {out}")
