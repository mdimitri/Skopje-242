"""Per-character voice colour on top of Suze, using the WORLD vocoder (pyworld).

Suze speech -> WORLD analysis (F0, smooth spectral envelope, aperiodicity) -> independent edits -> WORLD synthesis:
  * F0: re-centred to the character's mean pitch (geometric), contour range scaled around the mean (intonation),
        optional vibrato / jitter (old, rough voices)
  * formants: the spectral envelope is warped along frequency (alpha > 1 = shorter vocal tract: child, small woman;
        alpha < 1 = longer tract: big man), independent from pitch, so no chipmunk / giant effect
  * spectral tilt (dB per octave-ish): bright vs. dark / soft voice
  * breathiness: aperiodicity raised in the upper bands; roughness: stronger jitter + shimmer
  * speaking rate: frames are re-timed (voiced stretched more than silence), no pitch change
Everything runs on the speech worker thread, never in the frame loop.
"""
import numpy as np
import pyworld as pw

SR = 24000
FP = 5.0  # ms frame period


def analyse(x, sr=SR):
    x = np.ascontiguousarray(x, np.float64)
    f0, t = pw.harvest(x, sr, f0_floor=70.0, f0_ceil=500.0, frame_period=FP)
    f0 = pw.stonemask(x, f0, t, sr)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    return f0, sp, ap


def _warp(sp, alpha, spread=0.0):
    """formant shift: new_envelope(f) = envelope(f / alpha(f)); spread > 0 moves high formants more than low ones
    (small mouth / bright) and spread < 0 the opposite (big throat)."""
    n = sp.shape[1]
    f = np.arange(n) * 12000.0 / (n - 1)
    u = np.clip(np.log(np.maximum(f, 300) / 300) / np.log(4000 / 300), 0, 1)
    a = alpha * (1 - spread / 2 + spread * u)
    src = np.clip(np.arange(n) / a, 0, n - 1)
    i0 = np.floor(src).astype(int)
    i1 = np.minimum(i0 + 1, n - 1)
    w = src - i0
    return sp[:, i0] * (1 - w) + sp[:, i1] * w


def _bumps(p):
    n, ch, pr = p.get("nasal", 0), p.get("chest", 0), p.get("pres", 0)
    return [(250, 110, 9 * n), (1000, 350, -9 * n), (2600, 600, -5 * n), (170, 140, 8 * ch), (450, 300, 3 * ch),
            (3200, 700, 9 * pr), (5500, 1200, 5 * pr)]


def retime(a, idx):
    i0 = np.floor(idx).astype(int)
    i0 = np.clip(i0, 0, len(a) - 1)
    i1 = np.minimum(i0 + 1, len(a) - 1)
    w = (idx - np.floor(idx)).reshape(-1, *([1] * (a.ndim - 1)))
    return a[i0] * (1 - w) + a[i1] * w


def transform(x, p, sr=SR, cache=None):
    """x float mono; p dict: f0 (Hz target mean), rng (contour range factor), alpha (formant), tilt (dB at Nyquist),
    breath 0..1, rough 0..1, vib 0..1, rate (>1 faster), gain."""
    f0, sp, ap = cache or analyse(x, sr)
    f0 = f0.copy()
    v = f0 > 0
    if v.any():
        lf = np.log(f0[v])
        mu = np.median(lf)
        # slow intonation (phrase) part scaled by `rng`, fast part (word accents) kept
        out = np.log(p["f0"]) + p["rng"] * (lf - mu)
        f0[v] = np.exp(out)
        n = len(f0)
        tt = np.arange(n) * FP / 1000.0
        mod = np.zeros(n)
        if p.get("vib", 0):
            mod += 0.025 * p["vib"] * np.sin(2 * np.pi * 5.3 * tt)
        if p.get("rough", 0):
            rg = np.random.default_rng(3)
            mod += 0.02 * p["rough"] * rg.standard_normal(n)
        if p.get("wobble", 0):                       # slow random pitch wander (semitones): shaky / sing-song speech
            rg = np.random.default_rng(11)
            w = np.convolve(rg.standard_normal(n), np.hanning(40) / np.hanning(40).sum(), "same")
            mod += p["wobble"] * 0.0578 * w / (w.std() or 1)
        if p.get("decl", 0):                         # pitch declination over the phrase (+ falls, - rises)
            mod += p["decl"] * 0.25 * (0.5 - np.linspace(0, 1, n))
        f0[v] *= np.exp(mod[v])
    sp = sp.copy()
    if abs(p["alpha"] - 1) > 1e-3 or p.get("spread", 0):
        sp = _warp(sp, p["alpha"], p.get("spread", 0.0))
    nb = sp.shape[1]
    fr = np.arange(nb) / (nb - 1)
    sp *= (10 ** (p.get("tilt", 0.0) * fr / 10.0))[None, :]       # sp is a power spectrum
    hz = np.arange(nb) * (sr / 2) / (nb - 1)
    for c, w, g in _bumps(p):                                         # nasal / chest / presence colour (dB bumps)
        sp *= (10 ** (g * np.exp(-0.5 * ((hz - c) / w) ** 2) / 10.0))[None, :]
    ap = ap.copy()
    if p.get("breath", 0) or p.get("rough", 0):
        b = p.get("breath", 0) * 0.85 + p.get("rough", 0) * 0.25
        ap = np.clip(ap + b * (0.15 + 0.85 * fr)[None, :] * (1 - ap), 0, 1)
    rate = p.get("rate", 1.0)
    if abs(rate - 1) > 1e-3:
        n = len(f0)
        m = int(n / rate)
        idx = np.linspace(0, n - 1, m)
        f0 = retime(f0, idx) * 1.0
        f0[f0 < 20] = 0.0                                              # avoid interpolating across unvoiced gaps
        sp, ap = retime(sp, idx), retime(ap, idx)
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp), np.ascontiguousarray(ap), sr, FP)
    if p.get("fry", 0):                              # vocal fry / creak: every second glottal pulse weaker
        ff = np.interp(np.arange(len(y)) / sr, np.arange(len(f0)) * FP / 1000.0, f0)
        ph = np.cumsum(ff) / sr
        low = np.clip(1.0 - (ff - 90) / 110.0, 0.35, 1.0)    # creakier the lower the voice
        y = y * (1 - p["fry"] * low * 0.45 * (1 - np.cos(np.pi * ph)) * (ff > 20))
    if p.get("drive", 0):                            # throat / lung grit
        d = 1 + 4 * p["drive"]
        y = np.tanh(y / (np.max(np.abs(y)) or 1) * d) / np.tanh(d)
    if p.get("band"):                                # small speaker: radio / phone / megaphone
        from scipy.signal import butter, sosfilt
        lo, hi = p["band"]
        y = sosfilt(butter(3, [lo, hi], "bandpass", fs=sr, output="sos"), y)
        y = np.tanh(y * 2.5)
    y = y / (np.max(np.abs(y)) or 1.0)
    rms = np.sqrt(np.mean(y[np.abs(y) > 0.02] ** 2)) or 1.0                  # equal loudness across voices
    y = np.clip(y * 0.12 / rms, -1, 1)
    y = y / (np.max(np.abs(y)) or 1.0)                                       # peak 1: the caller scales by the speaker's volume
    return y.astype(np.float32)


# ------------------------------------------------------------------------------------------ characters and pedestrians
import math  # noqa: E402
import random  # noqa: E402
import zlib  # noqa: E402

NEU = dict(f0=189., alpha=1., rate=1., rng=1.)
K = (0.6, 0.9, 1.2, 1.5, 1.8, 2.1, 2.5, 2.9, 3.4, 4.0)   # identity strength; the game uses 1.2 for heroes
LIM = dict(f0=(45, 560), alpha=(.55, 1.65), rate=(.55, 1.6), rng=(.25, 3.0))
ADD = dict(tilt=(-16, 16), breath=(0, 1.), rough=(0, 1.6), vib=(0, 2.), nasal=(0, 2.), chest=(0, 2.), pres=(0, 2.),
           spread=(-.5, .5), wobble=(0, 4.), decl=(-2, 2), fry=(0, 1.), drive=(0, .9))
def level(p, k):
    q = {}
    for key, n in NEU.items():
        v = n * math.exp(k * math.log(p.get(key, n) / n)); lo, hi = LIM[key]; q[key] = min(hi, max(lo, v))
    for key, (lo, hi) in ADD.items():
        q[key] = min(hi, max(lo, p.get(key, 0) * k))
    for key in ("band",):
        pass
    if p.get("band") and k >= 1.5:
        q["band"] = p["band"]
    return q
# character bases (level 3): pitch, range, formant, tilt, breath, rough, vib, rate + nasal/chest/presence
B = {
 "mile": ("Таксист Миле", dict(f0=112, rng=1.1, alpha=.88, tilt=-1, rough=.35, chest=.5, rate=1.12)),
 "doktor": ("Доктор Владимир", dict(f0=100, rng=.7, alpha=.84, tilt=-4, chest=.7, breath=.1, rate=.92)),
 "influenser": ("Инфлуенсер Давид", dict(f0=150, rng=1.6, alpha=1.0, tilt=4, pres=.8, nasal=.3, rate=1.25)),
 "influenserka": ("Инфлуенсерка Сара", dict(f0=250, rng=1.7, alpha=1.1, tilt=3, pres=.5, breath=.25, nasal=.2, rate=1.25)),
 "tetkica": ("Теткица Весна", dict(f0=215, rng=1.3, alpha=1.05, nasal=.7, vib=.3, pres=.3, rate=1.05)),
 "baba": ("Баба Велика", dict(f0=175, rng=.9, alpha=1.0, vib=1., rough=.5, tilt=-5, nasal=.5, rate=.78)),
 "dedo": ("Дедо Димче", dict(f0=90, rng=.85, alpha=.9, vib=.9, rough=.5, tilt=-5, chest=.5, nasal=.3, rate=.75)),
 "pandur": ("Пандур Бобан", dict(f0=82, rng=.6, alpha=.78, tilt=-3, rough=.5, chest=1., rate=.98)),
 "radnik": ("Работник Момчило", dict(f0=98, rng=.8, alpha=.88, rough=.6, chest=.6, tilt=-2, rate=1.0)),
 "burek": ("Бурек-мајстор Благоја", dict(f0=118, rng=1.5, alpha=.92, nasal=.4, pres=.4, rate=1.12)),
 "boza": ("Боза-мајстор Љупчо", dict(f0=128, rng=1.1, alpha=.96, nasal=.6, vib=.3, tilt=-1, rate=.95)),
 "fitka": ("Фит-женска Теа", dict(f0=235, rng=1.4, alpha=1.1, tilt=4, pres=.9, rate=1.2)),
 "bilder": ("Билдер Дарко", dict(f0=76, rng=.55, alpha=.75, tilt=-4, chest=1., rough=.3, rate=.92)),
 "shmizla": ("Шмизла Кики", dict(f0=275, rng=1.7, alpha=1.15, breath=.55, tilt=2, nasal=.4, rate=1.1)),
 "srednoskolec": ("Средношколец Михаил", dict(f0=160, rng=1.4, alpha=.98, rough=.2, nasal=.3, pres=.4, rate=1.25)),
 "vojnik": ("Војник Сашо", dict(f0=102, rng=.5, alpha=.88, tilt=2, pres=.7, rough=.2, rate=1.2)),
 "navivac": ("Навивач Дуле", dict(f0=124, rng=1.6, alpha=.88, rough=.8, pres=.6, chest=.4, rate=1.2)),
 "administratorka": ("Административка Славица", dict(f0=190, rng=.55, alpha=1.0, tilt=2, nasal=.6, pres=.3, rate=1.0)),
 "nastavnica": ("Наставничка Снежана", dict(f0=180, rng=1.2, alpha=.98, pres=.6, chest=.3, tilt=1, rate=.93)),
 "mali": ("Мали (дете)", dict(f0=320, rng=1.5, alpha=1.28, pres=.5, tilt=2, rate=1.12)),
 "kumplung": ("Чичко Кумплунг", dict(f0=88, rng=1.0, alpha=.84, rough=.5, vib=.4, chest=.6, nasal=.4, rate=.88)),
 "maca": ("Певаљка Маца", dict(f0=225, rng=1.8, alpha=1.06, breath=.5, vib=.7, chest=.3, pres=.3, rate=.92)),
 "stojan": ("Студент Стојан", dict(f0=130, rng=1.1, alpha=.96, nasal=.5, tilt=1, rate=1.1)),
 "palavko": ("Палавко", dict(f0=280, rng=1.8, alpha=1.18, nasal=.5, pres=.5, tilt=2, rate=1.3)),
}
# signature extras per character (scaled with the level through ADD): effects that make the voice type real
X = dict(mile=dict(fry=.5, drive=.2, spread=-.15), doktor=dict(fry=.3, spread=-.2, decl=.5), influenser=dict(wobble=1.5, spread=.2, decl=-.5),
 influenserka=dict(wobble=2., spread=.25, decl=-.6), tetkica=dict(wobble=1., spread=.1, vib=.5), baba=dict(wobble=1.5, fry=.4, spread=.2),
 dedo=dict(wobble=1.5, fry=.7, spread=-.15, decl=.6), pandur=dict(fry=.6, drive=.35, spread=-.3, band=(250, 4800)), radnik=dict(fry=.4, drive=.4, spread=-.2),
 burek=dict(wobble=1.2, spread=-.1, decl=-.3), boza=dict(wobble=.8, fry=.3, spread=-.1), fitka=dict(wobble=1., spread=.3, drive=.1, decl=-.3),
 bilder=dict(fry=.8, drive=.3, spread=-.35), shmizla=dict(wobble=2., spread=.3, decl=-.8), srednoskolec=dict(wobble=1.5, drive=.15, spread=.1),
 vojnik=dict(drive=.3, spread=-.1, decl=.8, band=(300, 4200)), navivac=dict(drive=.5, wobble=1.2, fry=.3, spread=-.1, band=(200, 6000)),
 administratorka=dict(wobble=.4, spread=.15, decl=.8), nastavnica=dict(wobble=.8, decl=.4), mali=dict(wobble=2.5, spread=.3, decl=-1.),
 kumplung=dict(fry=.6, wobble=1., spread=-.25, drive=.2), maca=dict(wobble=2., vib=1.2, spread=.1, decl=-.4), stojan=dict(wobble=1., spread=.05),
 palavko=dict(wobble=2.5, spread=.2, decl=-.6))
for _k, _v in X.items():
    B[_k][1].update(_v)



HERO_K = 0.9      # = level L2
PED_K = 0.6       # = level L1 for the generic pedestrian voice (each pedestrian then varies around it)


# natural ranges of median pitch (Hz) and formant scale vs. Suze (an adult woman) per gender / age
BAND = {("m", False): ((95, 145), (.83, .91)), ("m", True): ((95, 135), (.85, .93)),
        ("f", False): ((180, 250), (.98, 1.10)), ("f", True): ((160, 200), (.96, 1.04)),
        ("c", False): ((250, 340), (1.12, 1.30)), ("c", True): ((250, 340), (1.12, 1.30))}
HERO_BAND = {("m", False): ((75, 150), (.74, .92))}           # heroes may be deeper (Билдер, Пандур)


def _clamp(p, g, old, hero=False):
    (f_lo, f_hi), (a_lo, a_hi) = (HERO_BAND.get((g, old)) if hero else None) or BAND[(g, old)]
    p["f0"] = min(f_hi, max(f_lo, p["f0"]))
    p["alpha"] = min(a_hi, max(a_lo, p["alpha"]))
    lim = {"m": (-.2, .04), "f": (-.1, .06), "c": (-.1, .1)}[g]   # mouth/throat split must not push a voice out of its gender
    p["spread"] = min(lim[1], max(lim[0], p.get("spread", 0.0)))
    return p


def params_for(who, prof):
    """Voice parameters for a speaker: heroes get their signature voice; every pedestrian ('Name#id') gets its own
    variation of the voice for its kind.  Gender/age come from the model styling (speech.voice_kind), and pitch and
    formants are always kept inside the natural range for that gender/age."""
    import speech
    vk = speech.voice_kind(who)
    g, old = (vk[0], vk[1]) if vk else (prof.get("g", "m"), bool(prof.get("vib")))
    if vk and vk[2] in B:
        return _clamp(level(B[vk[2]][1], HERO_K), g, old, hero=True)
    rg = random.Random(zlib.crc32(who.encode("utf-8")))
    p = {("m", False): dict(f0=118., alpha=.87, chest=.3), ("m", True): dict(f0=112., alpha=.89, vib=.8, rate=.88, tilt=-3, fry=.3),
         ("f", False): dict(f0=210., alpha=1.03), ("f", True): dict(f0=180., alpha=1.0, vib=.8, rate=.88, tilt=-3),
         ("c", False): dict(f0=290., alpha=1.2), ("c", True): dict(f0=290., alpha=1.2)}[(g, old)]
    p.setdefault("rate", 1.0)
    p["rng"] = 1.0
    if prof.get("rough") and g == "m":
        p.update(rough=.4, fry=max(p.get("fry", 0), .3), drive=.15)
    if prof.get("soft"):
        p.update(breath=.25, tilt=p.get("tilt", 0) - 1.5)
    q = level(dict(p, f0=189., alpha=1.0), PED_K)      # colour effects at L1 strength; pitch/formants stay natural
    q["f0"], q["alpha"], q["rate"] = p["f0"], p["alpha"], p["rate"]
    p = q
    u = rg.uniform
    p["f0"] *= math.exp(rg.gauss(0, .08))
    p["alpha"] *= math.exp(rg.gauss(0, .025))
    p["rng"] *= u(.85, 1.25)
    p["rate"] *= u(.92, 1.08)
    p["tilt"] += rg.gauss(0, 1.5)
    p["nasal"] = max(p["nasal"], u(0, .5) if rg.random() < .4 else 0)
    p["pres"] = u(0, .4)
    p["wobble"] = u(0, 1.0)
    p["spread"] += rg.gauss(0, .06)
    if g == "m":
        p["chest"] = max(p["chest"], u(0, .5))
        if rg.random() < .3:
            p["fry"] = max(p["fry"], u(.2, .4))
    else:
        p["breath"] = max(p["breath"], u(0, .2))
    return _clamp(p, g, old)
