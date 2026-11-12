"""Procedural sound effects (numpy only).  Every key in soundcat that has no library recording is synthesised here from the
physics of the real thing: impacts = a sharp broadband transient + resonant modes that ring and die + a tail that gets darker
with time; voices = a harmonic source shaped by formants; birds = FM chirps; machines = pulse trains through resonances.
build() returns {key: float32 array at SR}.  Levels are NOT set here (loudness.level_all does that for every sound in the game),
only the shape; arrays are scaled to a peak of about 0.9.  Rendering everything takes well under a second."""
import numpy as np

SR = 22050
_R = np.random.default_rng(242)


# ------------------------------------------------------------------ toolkit
def T(d):
    return np.arange(int(d * SR), dtype=np.float64) / SR


def nz(n):
    return _R.standard_normal(n)


def filt(x, lo=None, hi=None, order=2):
    """Zero-phase band filter in the frequency domain (high-pass at lo, low-pass at hi); smooth skirts, no ringing."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    m = np.ones_like(f)
    if lo:
        m *= 1.0 - 1.0 / (1.0 + (f / lo) ** (2 * order))
    if hi:
        m /= 1.0 + (f / hi) ** (2 * order)
    return np.fft.irfft(X * m, len(x))


def sweep_lp(x, f0, f1, k=5):
    """A low-pass whose cutoff glides from f0 to f1 over the length of x (tails of shots and booms get dark)."""
    cs = np.geomspace(f0, f1, k)
    ys = [filt(x, hi=c, order=2) for c in cs]
    u = np.linspace(0, k - 1, len(x))
    i = np.clip(u.astype(int), 0, k - 2)
    w = u - i
    out = np.zeros(len(x))
    for j in range(k - 1):
        m = i == j
        out[m] = ys[j][m] * (1 - w[m]) + ys[j + 1][m] * w[m]
    return out


def E(t, a=0.002, d=0.1, p=1.0):
    """Attack / exponential decay envelope."""
    return np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-(np.maximum(t, 0) / d) ** p)


def modal(t, modes, t0=0.0):
    """Struck object: sum of decaying sinusoids, modes = [(Hz, decay s, amp)]."""
    tt = np.maximum(t - t0, 0)
    y = np.zeros_like(t)
    for f, d, a in modes:
        y += a * np.sin(2 * np.pi * f * tt + _R.uniform(0, 6.28)) * np.exp(-tt / d)
    return y * (t >= t0) * np.minimum(1.0, tt / 0.0008)


def put(out, x, t0):
    i = int(t0 * SR)
    if i < len(out):
        m = min(len(x), len(out) - i)
        out[i:i + m] += x[:m]
    return out


def reverb(x, rt=0.5, wet=0.3, lp=4000.0):
    n = int(rt * 1.6 * SR)
    t = np.arange(n) / SR
    ir = filt(nz(n), hi=lp) * np.exp(-t / (rt / 3.0))
    ir[0] = 0
    return x + wet * np.fft.irfft(np.fft.rfft(x, len(x) + n) * np.fft.rfft(ir, len(x) + n))[:len(x)] * (np.abs(x).max() / (np.abs(ir).max() * 20 + 1e-9)) * 8


def norm(x, peak=0.9):
    return (x / (np.abs(x).max() + 1e-9) * peak).astype(np.float32)


def loopify(x, fade=0.2):
    n = int(fade * SR)
    y = x.copy()
    r = np.linspace(0, 1, n)
    y[:n] = y[:n] * r + y[-n:] * (1 - r)
    return y[:-n]


def vox(dur, f0, formants, amp=None, breath=0.08, vib=(5.5, 0.012), jit=0.01, hmax=4200.0):
    """Voice: harmonics of a gliding f0 weighted by formant peaks [(Hz, bandwidth, gain)], plus formant-shaped breath noise."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    u = np.linspace(0, 1, n)
    f = np.interp(u, np.linspace(0, 1, len(f0)), f0) * (1 + vib[1] * np.sin(2 * np.pi * vib[0] * t))
    f = f * (1 + jit * np.interp(t, np.linspace(0, dur, max(2, int(dur * 40))), nz(max(2, int(dur * 40)))) * 0.7)
    ph = np.cumsum(2 * np.pi * f / SR)
    y = np.zeros(n)
    h = 1
    while h * f.min() < hmax and h < 60:
        fh = h * f
        fc = fh[::64]                                                           # the formant weight changes slowly: evaluate it on a coarse grid
        g = np.interp(np.arange(n), np.arange(0, n, 64), 0.05 + sum(G / (1 + ((fc - F) / B) ** 2) for F, B, G in formants))
        y += g * np.sin(h * ph + 1.3 * h)
        h += 1
    if breath:
        X = np.fft.rfft(nz(n))                                                  # breath: one noise, one FFT, shaped by all formants at once
        fq = np.fft.rfftfreq(n, 1.0 / SR)
        m = sum(G / (1 + ((fq - F) / B) ** 2) for F, B, G in formants)
        b = np.fft.irfft(X * m, n)
        y = y / (np.abs(y).max() + 1e-9) + breath * b / (np.abs(b).max() + 1e-9) * 0.7
    a = np.ones(n) if amp is None else np.interp(u, np.linspace(0, 1, len(amp)), amp)
    return y / (np.abs(y).max() + 1e-9) * a


def chirp(dur, fc, amp=(0, 1, 0.6, 0), fm=(0.0, 0.0), harm=(1.0, 0.25, 0.08)):
    """Bird-style whistle: f contour fc (Hz points), optional FM (rate Hz, depth Hz), a few harmonics."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    u = np.linspace(0, 1, n)
    f = np.interp(u, np.linspace(0, 1, len(fc)), fc) + fm[1] * np.sin(2 * np.pi * fm[0] * t)
    ph = np.cumsum(2 * np.pi * f / SR)
    y = sum(a * np.sin((k + 1) * ph) for k, a in enumerate(harm))
    return y * np.interp(u, np.linspace(0, 1, len(amp)), amp)


VOW = {"a": [(800, 110, 1.0), (1250, 140, 0.6), (2600, 200, 0.25)], "o": [(500, 90, 1.0), (900, 110, 0.6), (2500, 200, 0.15)],
       "e": [(520, 90, 1.0), (1800, 140, 0.5), (2500, 200, 0.25)], "i": [(300, 70, 1.0), (2250, 160, 0.5), (3000, 220, 0.3)],
       "u": [(330, 80, 1.0), (850, 120, 0.4), (2300, 200, 0.1)]}


def crowd(dur, n_voices, f_lo, f_hi, vowels="aoe", swell=1.0, bursts=None, rough=0.0, babble=0.25):
    """Many voices: a few rendered voices (the expensive part) are resampled to other pitches and laid on top of each other at random times."""
    out = np.zeros(int(dur * SR))
    vd = 0.35 if bursts is not None else dur * 0.55
    pool = []
    for _ in range(5):
        f = _R.uniform(f_lo, f_hi)
        pool.append(vox(vd, [f, f * _R.uniform(1.0, 1.25), f * _R.uniform(0.9, 1.1)], VOW[_R.choice(list(vowels))], amp=[0, 1, 1, 0.5, 0], breath=0.2 + rough, jit=0.03 + rough))
    for _ in range(n_voices):
        v = pool[_R.integers(len(pool))]
        r = _R.uniform(0.82, 1.22)
        v = np.interp(np.arange(int(len(v) / r)) * r, np.arange(len(v)), v)
        if bursts is not None:
            v = v[:int(0.18 * SR)] * np.hanning(min(len(v), int(0.18 * SR)))
            t0 = _R.choice(bursts) + _R.uniform(0, 0.12)
        else:
            t0 = _R.uniform(0, dur - len(v) / SR)
        put(out, v * _R.uniform(0.5, 1.0), max(0.0, min(t0, dur - len(v) / SR)))
    out += babble * filt(nz(len(out)), 300, 3500) * np.interp(np.linspace(0, 1, len(out)), [0, 0.3, 0.7, 1], [0.2, 1, 1, 0.3]) * np.std(out) * 2
    return out * np.interp(np.linspace(0, 1, len(out)), [0, 0.25, 0.8, 1], [0.15, 1, 0.9, 0.15]) ** swell


# ------------------------------------------------------------------ weapons and explosions
def gunshot(body_f, crack_f, tail, boom=1.0, dur=0.9, crack=1.0, echo=0.0):
    t = T(dur)
    n = len(t)
    click = np.zeros(n)
    click[:int(0.0015 * SR)] = nz(int(0.0015 * SR)) * 3
    crk = filt(nz(n), crack_f[0], crack_f[1]) * E(t, 0.0004, 0.010) * 2.5 * crack
    body = filt(nz(n), 60, body_f * 1.5) * E(t, 0.0008, 0.05) * 1.6
    thump = np.sin(2 * np.pi * (body_f * 0.5 * (1 + 1.5 * np.exp(-t / 0.02))) * t) * E(t, 0.001, 0.07) * boom
    rum = sweep_lp(filt(nz(n), 40, 3000), 1800, 150) * E(t, 0.005, tail) * 0.8
    y = click + crk + body + thump + rum
    if echo:
        y = y + 0.5 * np.roll(y, int(echo * SR)) * np.exp(-echo * 3) * (t > echo)
    return y


def explosion(dur=2.2, power=1.0, far=False):
    t = T(dur)
    n = len(t)
    crack = filt(nz(n), 300, 8000) * E(t, 0.0005, 0.02) * 2
    sub = np.sin(2 * np.pi * np.cumsum(60 * np.exp(-t / 0.9) + 24) / SR) * E(t, 0.008, 0.75) * 1.6 * power
    rum = sweep_lp(filt(nz(n), 30, 4000), 2200, 110, 6) * E(t, 0.015, 0.7) * 1.8
    deb = np.zeros(n)
    for _ in range(int(40 * dur)):                                              # debris pattering down afterwards
        c = _R.uniform(0.25, dur * 0.9)
        k = int(0.004 * SR)
        put(deb, nz(k) * np.hanning(k) * _R.uniform(0.05, 0.3) * np.exp(-c / 1.3), c)
    y = crack + sub + rum + filt(deb, 600, 6000) * 1.5
    y = reverb(y, 0.9, 0.35, 2500)
    return filt(y, hi=700, order=3) * 1.4 if far else y


# ------------------------------------------------------------------ vehicles and machines
def car_horn(dur, f1, f2, buzz=0.5):
    t = T(dur)
    y = 0
    for f, a in ((f1, 1.0), (f2, 0.85)):
        ph = 2 * np.pi * f * t * (1 + 0.002 * np.sin(2 * np.pi * 3.1 * t))
        y = y + a * (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.35 * np.sin(3 * ph + 0.5) + buzz * np.sign(np.sin(ph)) * 0.25 + 0.2 * np.sin(5 * ph))
    y = filt(y, 150, 4500)
    return y * np.minimum(1, t / 0.025) * np.minimum(1, (dur - t) / 0.03) * (1 + 0.04 * filt(nz(len(t)), hi=60) * 8)


def passby(dur, speed, f_eng, noise=1.0, heavy=False):
    """Vehicle passing a microphone: harmonic engine tone with doppler glide + tyre noise, both swelling and fading with distance."""
    t = T(dur)
    n = len(t)
    tc = dur * 0.5
    d = np.sqrt(4.0 ** 2 + (speed * (t - tc)) ** 2)                      # distance, closest approach 4 m
    vr = speed * (speed * (t - tc)) / np.maximum(d, 1e-3) / np.maximum(speed, 1e-3)
    dop = 343.0 / (343.0 + vr)                                          # approaching (t<tc): vr<0 -> higher pitch
    gain = 1.0 / np.maximum(d, 4.0) * 4.0
    f = f_eng * dop
    ph = np.cumsum(2 * np.pi * f / SR)
    y = sum(np.sin(k * ph + k) / k ** 1.1 for k in range(1, 14 if not heavy else 22)) * (1 + 0.25 * np.sin(2 * np.pi * f_eng / 3 * t))
    tyre = filt(nz(n), 400, 3200) * (0.4 + 0.7 * (speed / 30.0))
    y = (y * 0.5 + tyre * 0.8 * noise) * gain
    return y * np.minimum(1, t / 0.15) * np.minimum(1, (dur - t) / 0.2)


def pulses(dur, rate, f_lo, f_hi, decay=0.01, jitter=0.1, seed_f=None):
    """Irregular train of short noisy / resonant pulses (hammering, drilling, rattling)."""
    out = np.zeros(int(dur * SR))
    t = rate ** -1
    c = 0.0
    while c < dur - 0.05:
        k = int(max(0.02, decay * 6) * SR)
        tt = np.arange(k) / SR
        put(out, filt(nz(k), f_lo, f_hi) * np.exp(-tt / decay) * _R.uniform(0.6, 1.0), c)
        c += t * (1 + _R.uniform(-jitter, jitter))
    return out


def hum(dur, f, harm=(1, 0.5, 0.25, 0.12), wob=0.0, noise=0.05):
    t = T(dur)
    y = sum(a * np.sin(2 * np.pi * f * (k + 1) * t + k) for k, a in enumerate(harm)) * (1 + wob * np.sin(2 * np.pi * 0.7 * t))
    return y + noise * filt(nz(len(t)), 200, 4000)


# ------------------------------------------------------------------ the catalogue
def build():
    S = {}
    # ---- doors, handles, foley
    t = T(0.5); y = modal(t, [(95, 0.07, 1.0), (190, 0.05, 0.5), (420, 0.03, 0.3)]) + filt(nz(len(t)), 300, 4000) * E(t, 0.0005, 0.012) * 1.2
    y = put(y, filt(nz(200), 1500, 5000) * np.exp(-np.arange(200) / 25), 0.07)
    S["car_door_close"] = norm(y)
    t = T(0.6); y = filt(nz(len(t)), 1200, 6000) * E(t, 0.0003, 0.004) * 1.5 + modal(t, [(2800, 0.02, 0.4), (4100, 0.012, 0.3)])
    y = y + modal(t, [(70, 0.05, 0.5)], 0.22) + 0.35 * filt(nz(len(t)), 300, 900) * np.exp(-((t - 0.1) / 0.06) ** 2) * (1 + 0.5 * np.sin(2 * np.pi * 38 * t))
    S["car_door_open"] = norm(y)
    t = T(0.9); y = modal(t, [(70, 0.14, 1.0), (140, 0.09, 0.6), (310, 0.06, 0.4), (610, 0.04, 0.25)]) + filt(nz(len(t)), 150, 5000) * E(t, 0.0004, 0.02) * 2
    y = sweep_lp(reverb(y, 0.3, 0.2), 6000, 600)
    S["car_door_slam"] = norm(y)
    t = T(0.55); y = np.zeros(len(t))                                           # handbrake ratchet: a run of clicks that slows
    for i, c in enumerate(np.cumsum([0.02, 0.05, 0.06, 0.07, 0.085, 0.1, 0.12])):
        put(y, modal(T(0.04), [(2300 - 100 * i, 0.006, 1.0), (900, 0.01, 0.6)]) + filt(nz(int(0.04 * SR)), 1500, 6000) * E(T(0.04), 0.0003, 0.004), c)
    S["handbrake"] = norm(y)
    t = T(0.9); y = filt(nz(len(t)), 200, 2500) * E(t, 0.0005, 0.05) * 1.4 + modal(t, [(110, 0.08, 0.9), (230, 0.06, 0.5)])
    S["door"] = norm(reverb(y, 0.25, 0.15))
    t = T(0.75); y = modal(t, [(120, 0.1, 1.0), (260, 0.08, 0.5)]) + filt(nz(len(t)), 150, 3500) * E(t, 0.0004, 0.025) * 2.0
    y = y + 0.6 * np.roll(y, int(0.05 * SR)) * (t > 0.05) * 0.5
    S["door_slam"] = norm(reverb(y, 0.3, 0.2))
    t = T(0.8); y = np.zeros(len(t))
    for c in (0.05, 0.28, 0.49):
        put(y, modal(T(0.12), [(180 + 40 * _R.random(), 0.03, 1.0), (420, 0.02, 0.5)]) + filt(nz(int(0.12 * SR)), 300, 2500) * E(T(0.12), 0.0004, 0.01), c)
    S["door_knock"] = norm(y)
    t = T(0.7); y = filt(nz(len(t)), 80, 900) * np.exp(-((t - 0.25) / 0.2) ** 2) * (1 + 0.6 * np.sin(2 * np.pi * 22 * t)) + modal(t, [(190, 0.15, 0.5)], 0.0) * 0.3
    S["window_open"] = norm(y + 0.25 * filt(nz(len(t)), 2000, 6000) * E(t, 0.01, 0.06))
    t = T(1.4); y = filt(nz(len(t)), 600, 5000) * (1 + 0.7 * np.sign(np.sin(2 * np.pi * 42 * t))) * np.minimum(1, t / 0.1) * np.minimum(1, (1.4 - t) / 0.2) \
        + modal(t, [(900, 0.5, 0.15), (1500, 0.4, 0.1)], 0)
    S["shutter_roll"] = norm(y)
    t = T(0.8); y = np.zeros(len(t)); w = 0.0
    while w < 0.7:
        k = int(_R.uniform(0.03, 0.09) * SR); put(y, filt(nz(k), 2500, 9000) * np.hanning(k) * _R.uniform(0.3, 1.0), w); w += _R.uniform(0.04, 0.1)
    S["map_paper"] = norm(y)
    t = T(0.9); y = filt(nz(len(t)), 100, 1800) * np.exp(-((t - 0.3) / 0.22) ** 2) * (1 + 0.3 * np.sin(2 * np.pi * 9 * t))
    S["laundry_flap"] = norm(y + 0.4 * filt(nz(len(t)), 60, 400) * E(t, 0.002, 0.08))
    # ---- bus
    t = T(1.3); y = filt(nz(len(t)), 2000, 9000) * E(t, 0.01, 0.38) * 1.5 + filt(nz(len(t)), 400, 2000) * E(t, 0.02, 0.5) * 0.5
    S["bus_air_brake"] = norm(y * np.minimum(1, (1.3 - t) / 0.2))
    t = T(1.1); y = filt(nz(len(t)), 1500, 8000) * E(t, 0.01, 0.15) * 0.8 + modal(t, [(85, 0.12, 0.9), (160, 0.07, 0.5)], 0.35) + 0.4 * filt(nz(len(t)), 100, 600) * np.exp(-((t - 0.25) / 0.15) ** 2)
    S["bus_door"] = norm(y)
    # ---- metal, glass, wood
    t = T(1.6); y = modal(t, [(f, d, a) for f, d, a in ((310, 0.45, 1.0), (527, 0.38, 0.8), (845, 0.3, 0.7), (1210, 0.22, 0.5), (1760, 0.15, 0.4), (2430, 0.1, 0.3))]) \
        + filt(nz(len(t)), 800, 7000) * E(t, 0.0003, 0.01) * 1.2
    S["bin_clang"] = norm(y)
    t = T(1.0); y = modal(t, [(f, d, a) for f, d, a in ((830, 0.5, 1.0), (1530, 0.35, 0.8), (2490, 0.25, 0.7), (3720, 0.15, 0.5), (5100, 0.1, 0.3))]) + filt(nz(len(t)), 2000, 8000) * E(t, 0.0003, 0.004)
    S["glass_bottle"] = norm(y)
    t = T(1.1); y = modal(t, [(f, d, a) for f, d, a in ((520, 0.3, 1.0), (910, 0.25, 0.7), (1340, 0.18, 0.5), (2100, 0.12, 0.4))]) + filt(nz(len(t)), 600, 6000) * E(t, 0.0003, 0.008) * 1.5
    S["metal_clank"] = norm(y)
    t = T(1.0); y = filt(nz(len(t)), 300, 3500) * E(t, 0.0008, 0.12) * 0.8 + modal(t, [(210, 0.25, 0.6), (390, 0.2, 0.5), (770, 0.15, 0.4), (1100, 0.12, 0.3)]) * (1 + 0.6 * np.sin(2 * np.pi * 14 * t))
    S["tin_roof_bang"] = norm(y)
    t = T(1.4); y = np.zeros(len(t))                                           # fence rattle: loose wire / sheet shaking
    y = put(y, pulses(1.2, 28, 800, 5000, 0.012, 0.5), 0.0) * np.exp(-t / 0.5)
    S["fence_rattle"] = norm(y + modal(t, [(1200, 0.4, 0.15), (2400, 0.3, 0.1)]) * np.exp(-t / 0.4))
    # hammers
    t = T(0.6); y = filt(nz(len(t)), 800, 5000) * E(t, 0.0003, 0.006) * 1.5 + modal(t, [(1100, 0.04, 0.5), (230, 0.06, 0.8), (460, 0.05, 0.5)])
    y = put(y, y[:int(0.3 * SR)] * 0.7, 0.3)
    S["hammer"] = norm(y)
    t = T(0.8); y = filt(nz(len(t)), 1500, 8000) * E(t, 0.0002, 0.004) * 1.5 + modal(t, [(1600, 0.25, 0.9), (2650, 0.18, 0.6), (4100, 0.12, 0.4), (780, 0.3, 0.7)])
    y = put(y, y[:int(0.4 * SR)] * 0.8, 0.38)
    S["hammer_steel"] = norm(y)
    t = T(1.2); y = np.zeros(len(t))                                           # drill: a strong motor tone plus rattling hammer action
    ph = 2 * np.pi * np.cumsum(np.interp(t, [0, 0.12, 0.25, 1.1, 1.2], [200, 560, 620, 600, 280])) / SR
    y = sum(np.sin(k * ph) / k for k in range(1, 8)) * 0.6 * np.minimum(1, t / 0.05) * np.minimum(1, (1.2 - t) / 0.12) + 0.4 * filt(nz(len(t)), 800, 5000) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 55 * t))) * np.minimum(1, t / 0.1) * np.minimum(1, (1.2 - t) / 0.1)
    S["drill"] = norm(y)
    t = T(1.5); ph = 2 * np.pi * np.cumsum(np.interp(t, [0, 0.2, 0.35, 1.3, 1.5], [150, 480, 620, 600, 300])) / SR       # angle grinder: whining disc + abrasive rasp
    y = (np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.3 * np.sin(3 * ph)) * 0.4 + filt(nz(len(t)), 2000, 9000) * (0.6 + 0.4 * np.sin(2 * np.pi * 90 * t)) * np.interp(t, [0, 0.3, 1.2, 1.5], [0.1, 1, 0.9, 0])
    S["angle_grinder"] = norm(y * np.minimum(1, t / 0.05) * np.minimum(1, (1.5 - t) / 0.12))
    t = T(1.6); y = np.zeros(len(t)); c = 0.1                                   # hand saw: rasp strokes forward and back
    while c < 1.4:
        k = int(0.3 * SR); tt = np.arange(k) / SR
        put(y, (filt(nz(k), 600, 4500) * (0.6 + 0.4 * np.sign(np.sin(2 * np.pi * 85 * tt))) * np.hanning(k)) * (0.8 if int(c / 0.3) % 2 else 1.0), c); c += 0.28
    S["saw_wood"] = norm(y)
    t = T(1.0); y = np.zeros(len(t))                                            # shovelling gravel: a scoop (crunch), a swish, a spill
    y = filt(nz(len(t)), 700, 6000) * (np.exp(-((t - 0.12) / 0.09) ** 2) + 0.7 * np.exp(-((t - 0.6) / 0.14) ** 2)) * (0.5 + 0.5 * (nz(len(t)) > 0.3))
    S["shovel_gravel"] = norm(y + pulses(1.0, 60, 1500, 7000, 0.004, 0.8) * np.exp(-((t - 0.6) / 0.25) ** 2) * 0.5)
    t = T(1.5); y = filt(nz(len(t)), 120, 900) * (0.7 + 0.3 * np.sin(2 * np.pi * 7 * t)) * 0.5 + modal(t, [(850, 1.0, 0.1), (1700, 0.7, 0.05)]) * (1 + 0.6 * np.sin(2 * np.pi * 2.5 * t)) + pulses(1.5, 8, 200, 1000, 0.03, 0.5) * 0.4
    S["wheelbarrow"] = norm(y * np.minimum(1, t / 0.2) * np.minimum(1, (1.5 - t) / 0.2))
    t = T(2.0); y = np.sin(2 * np.pi * 1000 * t) * ((t % 1.0) < 0.5) * np.minimum(1, (t % 1.0) / 0.01) * np.minimum(1, (0.5 - (t % 1.0)) / 0.01).clip(0, 1) + 0.4 * np.sin(2 * np.pi * 3000 * t) * ((t % 1.0) < 0.5)
    S["truck_reverse_beep"] = norm(y)
    S["crane_hum"] = norm(hum(2.5, 110, (1, 0.6, 0.3, 0.15), 0.1, 0.12) * np.minimum(1, T(2.5) / 0.3) * np.minimum(1, (2.5 - T(2.5)) / 0.3))
    t = T(2.5); y = filt(nz(len(t)), 150, 2800) * (0.8 + 0.2 * np.sin(2 * np.pi * 11 * t)) + 0.4 * hum(2.5, 62, (1, 0.5, 0.3), 0, 0.05)
    S["sweeper_machine"] = norm(y * np.minimum(1, t / 0.4) * np.minimum(1, (2.5 - t) / 0.4))
    t = T(3.0); y = filt(nz(len(t)), 40, 400) * (1 + 0.5 * np.sin(2 * np.pi * 14 * t)) * 1.5 + hum(3.0, 38, (1, 0.7, 0.5, 0.3, 0.2), 0, 0.03)
    y = y + 0.5 * filt(nz(len(t)), 1800, 5000) * E(t - 1.7, 0.01, 0.5) * (t > 1.7) * (1 + 0.5 * np.sin(2 * np.pi * 90 * t))                  # hydraulic whine as the bin lifts
    y = y + modal(t, [(900, 0.5, 0.2), (1900, 0.3, 0.1)], 2.5) + 0.6 * modal(t, [(110, 0.12, 0.8)], 2.5)
    S["garbage_truck"] = norm(y * np.minimum(1, t / 0.4) * np.minimum(1, (3.0 - t) / 0.3))
    t = T(1.2); y = modal(t, [(f, d, a) for f, d, a in ((2500, 0.55, 1.0), (3910, 0.4, 0.6), (5560, 0.25, 0.4))]) + modal(t, [(2500, 0.55, 0.6), (3910, 0.4, 0.5)], 0.14) + filt(nz(len(t)), 3000, 8000) * E(t, 0.0003, 0.004)
    S["scooter_bell"] = norm(y)
    t = T(1.8); d = np.sqrt(3 ** 2 + (5.5 * (t - 0.9)) ** 2); y = (pulses(1.8, 24, 2500, 6000, 0.002, 0.3) * 0.7 + filt(nz(len(t)), 300, 2000) * 0.3) * (3.0 / np.maximum(d, 3))
    S["bicycle_pass"] = norm(y * np.minimum(1, t / 0.2) * np.minimum(1, (1.8 - t) / 0.3))
    # ---- weapons
    S["shot_pistol"] = norm(gunshot(380, (1800, 7000), 0.28, 0.9, 0.9, 1.0))
    S["shot"] = S["shot_pistol"]
    shots = np.zeros(int(1.2 * SR))
    for i, c in enumerate((0.0, 0.085, 0.172, 0.255, 0.34)):
        put(shots, gunshot(520, (2500, 8000), 0.1, 0.5, 0.45, 0.9) * (1 - 0.04 * i), c + _R.uniform(0, 0.008))
    S["shot_uzi"] = norm(reverb(shots, 0.5, 0.2, 3500))
    S["shot_shotgun"] = norm(gunshot(200, (800, 5000), 0.5, 1.5, 1.2, 0.8, 0.07))
    S["shot_kalash"] = norm(gunshot(250, (1200, 6500), 0.4, 1.3, 1.1, 1.3, 0.05))
    d = gunshot(300, (1500, 6000), 0.5, 1.0, 1.6, 1.0, 0.0)
    S["shot_distant"] = norm(reverb(sweep_lp(filt(d, hi=1100, order=3), 1100, 200), 1.0, 0.7, 1500) * np.minimum(1, T(1.6) / 0.01))
    S["boom"] = norm(explosion(2.2, 1.0))
    S["boom_rocket"] = norm(explosion(2.2, 1.3))
    S["boom_distant"] = norm(explosion(2.4, 0.9, True))
    t = T(1.8); y = sweep_lp(filt(nz(len(t)), 200, 7000), 6000, 500) * np.interp(t, [0, 0.05, 0.5, 1.8], [0, 1, 0.8, 0]) + 0.8 * filt(nz(len(t)), 40, 300) * E(t, 0.02, 0.5)
    S["rocket_launch"] = norm(reverb(y + 0.6 * explosion(1.8, 0.6)[:len(t)] * E(t, 0.001, 0.4), 0.6, 0.2))
    t = T(0.7); f = 3500 * np.exp(-t / 0.25) + 700                               # ricochet: the ping slides down, a tiny noise burst at the hit
    S["bullet_ricochet"] = norm(np.sin(2 * np.pi * np.cumsum(f) / SR) * E(t, 0.002, 0.15) + 0.3 * np.sin(4 * np.pi * np.cumsum(f) / SR) * E(t, 0.002, 0.08) + filt(nz(len(t)), 2000, 8000) * E(t, 0.0003, 0.006))
    t = T(0.3); S["bullet_wall"] = norm(filt(nz(len(t)), 600, 7000) * E(t, 0.0003, 0.008) * 1.5 + modal(t, [(900, 0.03, 0.4), (1700, 0.02, 0.3)]) + 0.5 * filt(nz(len(t)), 100, 900) * E(t, 0.001, 0.03))
    t = T(0.6); S["bullet_car_ping"] = norm(modal(t, [(1700, 0.18, 1.0), (2900, 0.12, 0.6), (4300, 0.08, 0.4), (860, 0.2, 0.5)]) + filt(nz(len(t)), 1500, 8000) * E(t, 0.0003, 0.004))
    t = T(0.35); S["bullet_tree"] = norm(modal(t, [(280, 0.05, 1.0), (560, 0.03, 0.5)]) + filt(nz(len(t)), 300, 3000) * E(t, 0.0005, 0.012) * 1.2)
    t = T(0.35); S["bullet_ground"] = norm(filt(nz(len(t)), 100, 1500) * E(t, 0.001, 0.04) * 1.3 + 0.4 * np.sin(2 * np.pi * 70 * t) * E(t, 0.001, 0.04))
    t = T(0.35); S["bullet_flesh"] = norm(filt(nz(len(t)), 80, 900) * E(t, 0.001, 0.03) * 1.2 + np.sin(2 * np.pi * 90 * t) * E(t, 0.001, 0.05))
    # ---- impacts
    t = T(1.4); n = len(t)                                                      # crash: crumple transient, metal modes, glass tinkle, tail
    y = filt(nz(n), 150, 6000) * E(t, 0.0005, 0.07) * 2.2 + modal(t, [(60, 0.18, 1.2), (130, 0.14, 0.8), (260, 0.12, 0.5)])
    y += modal(t, [(f, 0.25 + 0.1 * _R.random(), 0.25) for f in (420, 740, 1130, 1800, 2750)], 0.01) + modal(t, [(f, 0.2, 0.15) for f in _R.uniform(3500, 7500, 8)], 0.05)
    for c in np.sort(_R.uniform(0.06, 0.6, 12)):                                  # bits of glass and trim falling
        put(y, modal(T(0.12), [(_R.uniform(2500, 6500), 0.04, 0.2)]) , c)
    S["crash"] = norm(reverb(sweep_lp(y, 7000, 1500), 0.5, 0.2))
    t = T(0.7); n = len(t); y = filt(nz(n), 200, 5000) * E(t, 0.0005, 0.05) * 1.6 + modal(t, [(90, 0.1, 1.0), (220, 0.07, 0.5), (800, 0.08, 0.2)])
    S["crash_light"] = norm(y)
    t = T(1.6); n = len(t); y = filt(nz(n), 1500, 9000) * E(t, 0.0003, 0.03) * 2
    for c in np.sort(_R.uniform(0.0, 1.0, 55)):                                    # shards bouncing and tinkling
        put(y, modal(T(0.2), [(_R.uniform(2200, 8000), _R.uniform(0.02, 0.09), _R.uniform(0.1, 0.5)), (_R.uniform(1200, 3000), 0.05, 0.2)]), c)
    S["crash_glass"] = norm(y * np.exp(-t / 0.7))
    t = T(1.2); y = filt(nz(len(t)), 200, 6000) * E(t, 0.0004, 0.04) * 1.2 + modal(t, [(f, d, a) for f, d, a in ((180, 0.3, 1.0), (330, 0.28, 0.8), (610, 0.22, 0.7), (1020, 0.2, 0.5), (1650, 0.15, 0.3))]) \
        + 0.25 * filt(nz(len(t)), 800, 3500) * np.exp(-((t - 0.25) / 0.2) ** 2) * (1 + 0.8 * np.sin(2 * np.pi * 70 * t))              # a scrape of metal on metal
    S["crash_metal"] = norm(y)
    t = T(0.9); n = len(t); y = filt(nz(n), 300, 5000) * E(t, 0.0003, 0.012) * 2 + modal(t, [(150, 0.08, 1.0), (330, 0.06, 0.5), (700, 0.04, 0.3)])
    for c in (0.06, 0.13, 0.22, 0.34):
        put(y, modal(T(0.15), [(_R.uniform(300, 900), 0.04, 0.4)]) + filt(nz(int(0.15 * SR)), 400, 4000) * E(T(0.15), 0.0004, 0.01), c)
    S["crash_wood"] = norm(y)
    t = T(1.6); n = len(t); y = filt(nz(n), 200, 3500) * (np.exp(-((t - 0.25) / 0.2) ** 2) * (0.6 + 0.4 * np.sin(2 * np.pi * 36 * t)))          # creak and splintering crack, then leaves
    y += filt(nz(n), 200, 5000) * E(t - 0.3, 0.0005, 0.03) * 2 * (t > 0.3) + modal(t, [(110, 0.15, 0.8), (250, 0.1, 0.4)], 0.3)
    y += filt(nz(n), 3000, 9000) * np.interp(t, [0, 0.35, 0.7, 1.6], [0, 0.6, 0.3, 0]) * (0.5 + 0.5 * (nz(n) > 0)) * 0.5
    S["tree_break"] = norm(y)
    t = T(0.5); S["prop_thud"] = norm(np.sin(2 * np.pi * 85 * t * (1 + 0.5 * np.exp(-t / 0.03))) * E(t, 0.001, 0.07) + filt(nz(len(t)), 100, 1800) * E(t, 0.0006, 0.02) * 1.1)
    t = T(0.45); S["kerb_bump"] = norm(np.sin(2 * np.pi * 75 * t) * E(t, 0.002, 0.06) + 0.7 * np.sin(2 * np.pi * 62 * np.maximum(t - 0.13, 0)) * E(t - 0.13, 0.002, 0.08) * (t > 0.13) + filt(nz(len(t)), 100, 1200) * (E(t, 0.001, 0.015) + 0.6 * E(t - 0.13, 0.001, 0.015) * (t > 0.13)))
    # fight and body
    t = T(0.3); S["punch"] = norm(filt(nz(len(t)), 150, 2500) * E(t, 0.0006, 0.018) * 1.3 + np.sin(2 * np.pi * (110 * (1 + 0.6 * np.exp(-t / 0.02))) * t) * E(t, 0.001, 0.05))
    t = T(0.35); S["kick"] = norm(filt(nz(len(t)), 100, 1800) * E(t, 0.0008, 0.03) * 1.1 + np.sin(2 * np.pi * (80 * (1 + 0.8 * np.exp(-t / 0.03))) * t) * E(t, 0.001, 0.08) * 1.2)
    t = T(0.4); S["body_fall"] = norm(filt(nz(len(t)), 80, 700) * E(t, 0.002, 0.05) * 1.2 + np.sin(2 * np.pi * 60 * t) * E(t, 0.003, 0.1) + filt(nz(len(t)), 150, 600) * E(t - 0.08, 0.004, 0.06) * (t > 0.08) * 0.5)
    t = T(0.4); S["body_hit_car"] = norm(filt(nz(len(t)), 100, 1500) * E(t, 0.001, 0.03) + np.sin(2 * np.pi * 70 * t) * E(t, 0.002, 0.08) + modal(t, [(310, 0.1, 0.3), (590, 0.07, 0.2)]))
    t = T(0.35); S["hurt_thud"] = norm(filt(nz(len(t)), 80, 900) * E(t, 0.0015, 0.03) + np.sin(2 * np.pi * 95 * (1 + 0.3 * np.exp(-t / 0.04)) * t) * E(t, 0.002, 0.06))
    t = T(0.35); S["bat_hit"] = norm(modal(t, [(1100, 0.03, 1.0), (2200, 0.02, 0.5), (420, 0.04, 0.6)]) + filt(nz(len(t)), 500, 5000) * E(t, 0.0003, 0.008) * 1.5 + np.sin(2 * np.pi * 120 * t) * E(t, 0.001, 0.04) * 0.6)
    t = T(0.4); S["swing"] = norm(filt(nz(len(t)), 300, 3500) * np.sin(np.pi * t / 0.4) ** 2 * (0.4 + 0.6 * t / 0.4))
    t = T(0.8); S["cpr_pump"] = norm(sum(np.sin(2 * np.pi * 70 * np.maximum(t - c, 0)) * E(t - c, 0.003, 0.05) * (t > c) + 0.3 * filt(nz(len(t)), 200, 1500) * E(t - c, 0.002, 0.02) * (t > c) for c in (0.0, 0.4)))
    t = T(0.8); f = 200 + 4000 * np.clip((t - 0.0) / 0.55, 0, 1) ** 2; z = 0.5 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.interp(t, [0, 0.55, 0.57, 0.8], [0, 0.6, 0, 0]) + filt(nz(len(t)), 1000, 9000) * E(t - 0.57, 0.0002, 0.05) * (t > 0.57) * 2 + modal(t, [(90, 0.12, 1.0)], 0.57)
    S["defib_zap"] = norm(z)
    # ---- fire and water
    t = T(1.0); S["fire_ignite"] = norm(sweep_lp(filt(nz(len(t)), 50, 5000), 4000, 400) * E(t, 0.04, 0.3) * 1.6 + np.sin(2 * np.pi * 55 * t) * E(t, 0.03, 0.3) + pulses(1.0, 30, 600, 5000, 0.005, 0.8) * 0.4)
    t = T(1.8); S["fire_out_hiss"] = norm(filt(nz(len(t)), 3000, 10000) * E(t, 0.05, 0.6) * (0.8 + 0.2 * np.sin(2 * np.pi * 8 * t)) + 0.4 * filt(nz(len(t)), 400, 2500) * E(t, 0.05, 0.3))
    t = T(4.0); S["fire_crackle"] = norm(loopify(0.35 * filt(nz(len(t)), 80, 800) * (0.7 + 0.3 * filt(nz(len(t)), hi=6) * 6) + pulses(4.0, 38, 800, 7000, 0.003, 1.0) * 1.2 + 0.4 * filt(nz(len(t)), 1500, 6000) * (nz(len(t)) > 1.6)))
    t = T(0.9); S["splash"] = norm(sweep_lp(filt(nz(len(t)), 200, 9000), 7000, 800) * E(t, 0.004, 0.18) * 1.5 + sum(modal(T(0.9), [(_R.uniform(500, 1500) * (1 + 0.5 * k), 0.04, 0.2)], 0.03 + 0.06 * k) for k in range(6)))
    t = T(1.5); S["splash_big"] = norm(sweep_lp(filt(nz(len(t)), 100, 8000), 6000, 500) * E(t, 0.006, 0.4) * 1.5 + 0.7 * np.sin(2 * np.pi * 60 * t) * E(t, 0.01, 0.2) + filt(nz(len(t)), 600, 5000) * E(t - 0.25, 0.04, 0.4) * (t > 0.25) * 0.4)
    t = T(0.9); S["swim_stroke"] = norm(filt(nz(len(t)), 300, 4500) * np.exp(-((t - 0.3) / 0.17) ** 2) * (1 + 0.5 * np.sin(2 * np.pi * 30 * t)) + sum(modal(T(0.9), [(_R.uniform(700, 1900), 0.03, 0.2)], c) for c in _R.uniform(0.1, 0.6, 7)))
    t = T(1.5); f = 400 + 150 * np.sin(2 * np.pi * 5.5 * t)                      # liquid glugging out of a can
    S["fuel_pour"] = norm(np.sin(2 * np.pi * np.cumsum(f * (1 + 0.5 * (np.sin(2 * np.pi * 3 * t) > 0.3))) / SR) * 0.5 * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t) ** 2) + filt(nz(len(t)), 500, 4500) * 0.5 * np.minimum(1, t / 0.1) * np.minimum(1, (1.5 - t) / 0.1))
    t = T(0.45); b = (np.sin(2 * np.pi * 1320 * t) + 0.3 * np.sin(2 * np.pi * 2640 * t)) * ((t % 0.225) < 0.11) * np.minimum(1, (t % 0.225) / 0.005)
    S["fuel_warning"] = norm(b)
    # ---- vehicles
    t = T(2.6); r = np.interp(t, [0, 0.3, 0.9, 1.0, 1.4, 2.6], [0, 7, 9, 22, 13, 12.5])                      # cranking: slow starter chug, then the engine fires and catches
    ph = np.cumsum(2 * np.pi * r * 1.0 / SR); starter = np.maximum(0, np.sin(ph * 2)) ** 3 * filt(nz(len(t)), 40, 700) * 3 * (t < 1.0)
    f_e = np.interp(t, [0.9, 1.1, 1.6, 2.6], [0, 38, 24, 24]); pe = np.cumsum(2 * np.pi * f_e / SR)
    eng = sum(np.sin(k * pe) / k ** 0.9 * (0.6 + 0.4 * np.sin(k * pe * 0.5 + k)) for k in range(1, 14)) * np.minimum(1, np.maximum(t - 0.9, 0) / 0.15)
    S["engine_start"] = norm(starter * 0.9 + eng + filt(nz(len(t)), 100, 1500) * np.interp(t, [0.9, 1.0, 1.6, 2.6], [0, 0.6, 0.15, 0.1]))
    S["car_passby_slow"] = norm(passby(5.0, 8.0, 38.0, 0.6))
    S["car_passby_fast"] = norm(passby(4.2, 22.0, 80.0, 1.0))
    S["truck_passby"] = norm(passby(6.0, 12.0, 28.0, 0.8, True) + 0.25 * filt(nz(int(6 * SR)), 60, 500) * np.exp(-((T(6.0) - 3.0) / 1.0) ** 2) + 0.3 * filt(nz(int(6 * SR)), 3000, 9000) * E(T(6.0) - 3.8, 0.03, 0.5) * (T(6.0) > 3.8))
    t = T(8.0); y = filt(nz(len(t)), 300, 1800, 3) * (0.8 + 0.2 * filt(nz(len(t)), hi=3) * 6) + 0.35 * hum(8.0, 150, (1, 0.4), 0, 0) * 0.2
    S["tyre_roll_asphalt"] = norm(loopify(y, 0.4))
    t = T(8.0); y = filt(nz(len(t)), 500, 6000) * (0.5 + 0.5 * (nz(len(t)) > 0.2)) * (0.8 + 0.2 * filt(nz(len(t)), hi=8) * 6) + pulses(8.0, 90, 800, 5000, 0.003, 1.0) * 0.5
    S["tyre_gravel"] = norm(loopify(y, 0.4))
    t = T(8.0); alt = ((t * 3.6) % 2) < 1; seg = np.where(alt, 1, 0)                                         # car alarm: classic alternating sweep patterns
    f = np.where(((t * 0.45) % 1.0) < 0.5, 1100 + 700 * ((t * 7) % 1.0), 1700 - 800 * ((t * 3.4) % 1.0))
    S["car_alarm"] = norm(loopify((np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.35 * np.sin(4 * np.pi * np.cumsum(f) / SR) + 0.15 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR))) * (0.75 + 0.25 * seg), 0.1))
    sir = _SIREN(); S["siren_distant"] = norm(reverb(filt(sir, 300, 1600), 1.2, 0.8, 1500))
    t = T(2.4); a = car_horn(2.4, 311, 369, 0.1); S["train_horn_distant"] = norm(reverb(filt(a * np.minimum(1, t / 0.1) * np.minimum(1, (2.4 - t) / 0.3), hi=1500), 1.2, 0.5, 1800))
    # horns (reed-like pairs of tones)
    S["horn"] = norm(car_horn(0.6, 410, 510, 0.5))
    S["horn_small"] = norm(car_horn(0.4, 520, 650, 0.4))
    S["horn_truck"] = norm(car_horn(1.0, 190, 245, 0.7) + 0.4 * car_horn(1.0, 380, 490, 0.3))
    nt = (392, 392, 392, 523, 659); y = np.concatenate([filt(np.sin(2 * np.pi * f * T(0.16)) + 0.3 * np.sin(4 * np.pi * f * T(0.16)), 200, 4000) * np.minimum(1, T(0.16) / 0.008) * np.minimum(1, (0.16 - T(0.16)) / 0.03) for f in nt])
    S["horn_jingle"] = norm(y)
    # ---- ambient machines (loops)
    t = T(6.0); y = filt(nz(len(t)), 40, 280) * 1.2 * (1 + 0.3 * np.sin(2 * np.pi * 1.4 * t)) + hum(6.0, 24, (1, 0.7, 0.4, 0.3, 0.2), 0, 0.02) + 0.3 * filt(nz(len(t)), 300, 1200) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))
    S["concrete_mixer"] = norm(loopify(y, 0.4))
    t = T(4.0); y = pulses(4.0, 26, 100, 1800, 0.012, 0.03) * 1.2 + filt(nz(len(t)), 800, 6000) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 26 * t))) * 0.5 + hum(4.0, 52, (1, 0.5, 0.3), 0, 0)
    S["jackhammer"] = norm(loopify(y, 0.15))
    t = T(4.0); S["street_lamp_buzz"] = norm(loopify(hum(4.0, 100, (1, 0.7, 0.4, 0.3, 0.2, 0.1), 0.05, 0.04), 0.2))
    t = T(4.0); S["power_transformer_hum"] = norm(loopify(hum(4.0, 100, (1, 0.5, 0.7, 0.2, 0.35, 0.1), 0.02, 0.02) + 0.3 * hum(4.0, 50, (1, 0.3), 0, 0), 0.2))
    t = T(4.0); S["neon_buzz"] = norm(loopify(hum(4.0, 100, (1, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15), 0.1, 0.05) * (1 + 0.2 * np.sign(np.sin(2 * np.pi * 0.6 * t))) + 0.3 * filt(nz(len(t)), 2500, 8000), 0.2))
    t = T(2.4); S["tv_apartment"] = norm(sum(filt(nz(len(t)), 300 + 150 * k, 1200 + 500 * k) * (np.interp(t, np.cumsum(_R.uniform(0.1, 0.3, 14)), _R.uniform(0, 1, 14)) ** 1.5) for k in range(3)) * np.where(t < 2.2, 1, 0))
    # ---- clock tower and bell: inharmonic partials of a real bell (hum, prime, tierce, quint, nominal ...)
    def bell(dur, f0, d0):
        t = T(dur)
        return modal(t, [(f0 * r, d0 / (1 + 0.5 * i), a) for i, (r, a) in enumerate(((0.5, 0.6), (1.0, 1.0), (1.2, 0.7), (1.5, 0.5), (2.0, 0.6), (2.5, 0.35), (3.0, 0.25), (4.1, 0.15)))]) + filt(nz(len(t)), 800, 6000) * E(t, 0.0004, 0.01) * 0.6
    S["bell"] = norm(bell(3.0, 420.0, 2.2))
    t = T(4.0); y = np.zeros(len(t))
    for c in (0.0, 1.2, 2.4):
        put(y, bell(3.0, 262.0, 1.6) * 0.9, c)
    S["clock_tower"] = norm(y)
    # ---- UI
    t = T(0.15); S["ui_click"] = norm(np.sin(2 * np.pi * 1600 * t) * E(t, 0.0005, 0.012) + 0.4 * np.sin(2 * np.pi * 3200 * t) * E(t, 0.0005, 0.006) + filt(nz(len(t)), 1500, 6000) * E(t, 0.0003, 0.003) * 0.5)
    t = T(0.4); S["ui_confirm"] = norm(sum(np.sin(2 * np.pi * f * np.maximum(t - c, 0)) * E(t - c, 0.004, 0.1) * (t > c) * a for f, c, a in ((880, 0.0, 0.8), (1320, 0.08, 1.0))))
    t = T(0.35); b = (np.sin(2 * np.pi * 150 * t) + np.sign(np.sin(2 * np.pi * 150 * t)) * 0.4 + 0.5 * np.sin(2 * np.pi * 232 * t)) * ((t % 0.17) < 0.14); S["denied_buzz"] = norm(filt(b, 100, 2500) * np.minimum(1, (t % 0.17) / 0.005))
    t = T(0.8); S["teleport_whoosh"] = norm(filt(nz(len(t)), 500, 9000) * np.sin(np.pi * t / 0.8) ** 1.5 * (0.5 + t / 1.6) + 0.3 * np.sin(2 * np.pi * np.cumsum(300 + 1500 * (t / 0.8) ** 2) / SR) * np.sin(np.pi * t / 0.8))
    S["weapon_pickup"] = norm(np.concatenate([modal(T(0.07), [(2500, 0.01, 1.0), (4800, 0.008, 0.5)]) + filt(nz(int(0.07 * SR)), 1500, 6000) * E(T(0.07), 0.0003, 0.005) * 1.4,
                                                modal(T(0.09), [(1900, 0.015, 1.0), (3700, 0.01, 0.5), (500, 0.03, 0.6)]) + filt(nz(int(0.09 * SR)), 1000, 5000) * E(T(0.09), 0.0003, 0.006), np.zeros(int(0.01 * SR))]))
    t = T(0.45); S["eat"] = norm(sum(filt(nz(len(t)), 800, 6000) * E(t - c, 0.0004, 0.012) * (t > c) * _R.uniform(0.5, 1) + 0.4 * np.sin(2 * np.pi * _R.uniform(150, 280) * t) * E(t - c, 0.001, 0.02) * (t > c) for c in (0.0, 0.1, 0.22, 0.32)))
    # ---- crowds and human noises
    S["crowd_cheer"] = norm(crowd(3.0, 14, 110, 330, "aoe", 1.0, rough=0.1))
    S["crowd_laugh"] = norm(crowd(2.6, 10, 120, 360, "aeo", 0.8, bursts=[0.1 + 0.19 * i for i in range(9)], rough=0.05))
    S["crowd_panic"] = norm(crowd(3.0, 12, 220, 520, "aei", 1.0, rough=0.3, babble=0.3))
    S["crowd_football_roar"] = norm(crowd(3.5, 26, 100, 260, "aoe", 0.7, rough=0.2, babble=0.5))
    t = T(3.0); ap = np.zeros(len(t))
    ens = np.interp(t, [0, 0.4, 2.2, 3.0], [0.1, 1, 0.8, 0.0])
    cl = _R.random(len(t)) < (230.0 / SR) * ens * 1.0
    idx = np.nonzero(cl)[0]
    for i in idx[:900]:
        k = int(_R.uniform(0.003, 0.012) * SR); ap[i:i + k] += (filt(nz(k), 1200, 5000) * np.exp(-np.arange(k) / (0.003 * SR)) * _R.uniform(0.2, 1))[:len(ap) - i]
    S["crowd_applause"] = norm(ap + 0.15 * filt(nz(len(t)), 600, 3000) * ens * np.std(ap) * 3)
    S["kids_laugh"] = norm(crowd(2.2, 7, 330, 520, "aei", 0.8, bursts=[0.1 + 0.2 * i for i in range(9)], rough=0.03))
    S["baby_cry"] = norm(np.concatenate([vox(0.75, [420, 520, 470, 400], [(900, 150, 1.0), (2200, 300, 0.6), (3300, 300, 0.3)], [0, 1, 0.9, 0], breath=0.15, vib=(7, 0.03)), np.zeros(int(0.12 * SR)), vox(0.6, [450, 530, 400], [(900, 150, 1.0), (2200, 300, 0.6)], [0, 1, 0], breath=0.15, vib=(7, 0.03))]))
    t = T(0.9); S["whistle_ref"] = norm(np.sin(2 * np.pi * np.cumsum(2900 + 120 * np.sin(2 * np.pi * 28 * t)) / SR) * 0.5 * np.minimum(1, t / 0.02) * np.minimum(1, (0.9 - t) / 0.05) + filt(nz(len(t)), 2400, 4000) * 0.08)
    S["coughing"] = norm(np.concatenate([vox(0.13, [260, 200], VOW["a"], [0, 1, 0], breath=0.9, jit=0.15) , np.zeros(int(0.06 * SR)), vox(0.12, [240, 190], VOW["a"], [0, 1, 0], breath=0.9, jit=0.15)]))
    S["sneeze"] = norm(np.concatenate([filt(nz(int(0.3 * SR)), 1000, 6000) * np.linspace(0, 0.25, int(0.3 * SR)), filt(nz(int(0.18 * SR)), 1500, 8000) * E(T(0.18), 0.003, 0.05) * 1.5 + vox(0.18, [300, 220], VOW["e"], [0, 1, 0], breath=0.7, jit=0.1) * 0.4]))
    t = T(0.55); S["clap_hands"] = norm(sum(filt(nz(len(t)), 700, 5500) * E(t - c, 0.0004, 0.014) * (t > c) * a + modal(t, [(1300, 0.03, 0.2)], c) for c, a in ((0.0, 1.0), (0.3, 0.8))))
    # ---- animals and birds
    S.update(_animals())
    S.update(_birds())
    return S


def _SIREN():
    t = T(2.4)
    f = 800 + 500 * (0.5 - 0.5 * np.cos(2 * np.pi * t / 1.2))
    ph = np.cumsum(2 * np.pi * f / SR)
    return np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.1 * np.sin(3 * ph)


def _animals():
    A = {}
    A["cow_bell"] = norm(np.concatenate([modal(T(0.9), [(f, d, a) for f, d, a in ((880, 0.4, 1.0), (1500, 0.3, 0.7), (2300, 0.2, 0.5), (3400, 0.1, 0.3))]) + filt(nz(int(0.9 * SR)), 1500, 6000) * E(T(0.9), 0.0003, 0.005), np.zeros(1)]))
    A["sheep_bleat"] = norm(vox(1.1, [380, 430, 300, 330, 260], [(650, 120, 1.0), (1500, 200, 0.5), (2500, 300, 0.3)], [0, 1, 0.8, 0.9, 0], breath=0.1, vib=(24, 0.08), jit=0.04))
    A["donkey"] = norm(np.concatenate([vox(0.9, [450, 600, 550, 700], [(700, 150, 1), (1800, 250, 0.5)], [0, 1, 1, 0.8], breath=0.12, jit=0.05), vox(0.9, [420, 260, 450, 250], [(600, 140, 1), (1500, 250, 0.5)], [0.9, 0.2, 0.9, 0.1], breath=0.15, jit=0.07)]))
    A["horse_neigh"] = norm(vox(1.6, [500, 1150, 1300, 900, 600, 350], [(900, 200, 1), (2300, 350, 0.5), (3600, 400, 0.3)], [0, 1, 1, 0.8, 0.5, 0], breath=0.2, vib=(9, 0.04), jit=0.06))
    A["cat_meow"] = norm(vox(0.9, [450, 700, 850, 600, 380], [(900, 120, 1), (2400, 250, 0.6), (3300, 250, 0.3)], [0, 0.8, 1, 0.6, 0], breath=0.08, vib=(5, 0.02)))
    A["cat_fight"] = norm(np.concatenate([vox(0.9, [500, 800, 700, 850, 650], [(1000, 200, 1), (2500, 400, 0.8)], [0, 1, 0.8, 1, 0], breath=0.5, jit=0.15), np.zeros(int(0.1 * SR)), vox(0.7, [600, 400], [(1000, 200, 1), (2500, 400, 0.8)], [0, 1, 0], breath=0.6, jit=0.2)]))
    A["frog_croak"] = norm(np.concatenate([vox(0.11, [260, 190], [(500, 100, 1), (1400, 300, 0.5)], [0, 1, 0.5, 0], breath=0.05, vib=(90, 0.12), jit=0.08), np.zeros(int(0.05 * SR)), vox(0.11, [250, 180], [(500, 100, 1), (1400, 300, 0.5)], [0, 1, 0.5, 0], breath=0.05, vib=(90, 0.12), jit=0.08)]))
    A["rat_squeak"] = norm(chirp(0.25, [5200, 6800, 5800], (0, 1, 0.7, 0), (40, 300)))
    t = T(2.0); A["bee_buzz"] = norm(hum(2.0, 190, (1, 0.8, 0.6, 0.4, 0.3), 0, 0.1) * (1 + 0.3 * np.sin(2 * np.pi * 5 * t)) * np.minimum(1, t / 0.2) * np.minimum(1, (2 - t) / 0.2))
    t = T(1.6); fz = 330 + 80 * filt(nz(len(t)), hi=6) * 8; A["fly_buzz"] = norm(np.sin(2 * np.pi * np.cumsum(fz) / SR) * (1 + 0.5 * np.sin(2 * np.pi * 7 * t)) * np.exp(-((t - 0.8) / 0.5) ** 2) + 0.2 * filt(nz(len(t)), 500, 3000) * np.exp(-((t - 0.8) / 0.5) ** 2))
    # dogs from the existing four fitted barks are handled in audio.py; variants of size and mood here
    t = T(1.0); A["dog_growl"] = norm(sum(np.sin(2 * np.pi * np.cumsum(110 * (1 + 0.04 * np.sin(2 * np.pi * 5 * t))) * k / SR) / k for k in range(1, 12)) * (0.6 + 0.4 * np.sign(np.sin(2 * np.pi * 28 * t))) * np.minimum(1, t / 0.1) * np.minimum(1, (1 - t) / 0.2) * (0.8 + 0.2 * filt(nz(len(t)), hi=30) * 5) + 0.3 * filt(nz(len(t)), 200, 1500) * np.exp(-((t - 0.5) / 0.4) ** 2))
    A["dog_howl"] = norm(vox(2.4, [330, 520, 600, 580, 500, 380], [(900, 150, 1), (1800, 250, 0.4)], [0, 0.8, 1, 1, 0.8, 0], breath=0.05, vib=(5.5, 0.025), jit=0.01))
    return A


def _birds():
    B = {}

    def seq(parts, gap=0.04):
        return np.concatenate([np.concatenate([p, np.zeros(int(gap * SR))]) for p in parts])

    B["bird_crow"] = norm(seq([vox(0.28, [650, 520], [(900, 160, 1), (1700, 250, 0.7), (3000, 400, 0.3)], [0, 1, 0.8, 0], breath=0.35, jit=0.08) for _ in range(3)], 0.12))
    B["bird_crow_flock"] = norm(_flock(B["bird_crow"], 2.8, 5, 0.9, 0.85, 1.15))
    B["bird_magpie"] = norm(seq([vox(0.05, [1500, 1100], [(1500, 300, 1), (3000, 500, 0.5)], [0, 1, 0], breath=0.5, jit=0.1) for _ in range(11)], 0.02))
    B["bird_dove"] = norm(seq([chirp(0.28, [520, 600, 520], (0, 1, 0.7, 0), (0, 0), (1, 0.3, 0.05)), chirp(0.2, [560, 520], (0, 1, 0), (0, 0), (1, 0.3)), chirp(0.2, [520, 480], (0, 1, 0), (0, 0), (1, 0.3)), chirp(0.45, [520, 450], (0, 1, 0.7, 0), (0, 0), (1, 0.3))], 0.07))
    B["bird_pigeon"] = norm(seq([chirp(0.18, [400, 470, 420], (0, 1, 0), (0, 0), (1, 0.4)), chirp(0.18, [420, 380], (0, 1, 0), (0, 0), (1, 0.4)), chirp(0.5, [430, 500, 380], (0, 1, 0.8, 0), (12, 25), (1, 0.4))], 0.05))
    B["bird_pigeon_flock_takeoff"] = norm(sum(pulses(1.6, 11, 500, 3000, 0.03, 0.4) * np.exp(-T(1.6) / 0.8) * 1.0 for _ in range(1)) + 0.3 * filt(nz(int(1.6 * SR)), 1500, 6000) * np.sin(np.pi * T(1.6) / 1.6))
    B["bird_sparrow"] = norm(seq([chirp(0.07, [3600 + 300 * _R.random(), 3000], (0, 1, 0), (0, 0), (1, 0.2)) for _ in range(7)], 0.05))
    B["bird_swallow"] = norm(seq([chirp(0.09, [3500, 5200, 3800], (0, 1, 0.4, 0), (60, 400)) for _ in range(9)], 0.025))
    B["bird_swift"] = norm(chirp(1.1, [6500, 8000, 7000, 8200, 6800], (0, 1, 0.9, 1, 0), (30, 400)))
    B["bird_blackbird"] = norm(seq([chirp(0.18, [1800, 2600, 2000], (0, 1, 0), (0, 0), (1, 0.15)), chirp(0.3, [2200, 3000, 2400, 1900], (0, 1, 1, 0), (0, 0), (1, 0.15)), chirp(0.14, [3000, 2200], (0, 1, 0)), chirp(0.4, [1900, 2800, 2100], (0, 1, 1, 0), (9, 150)), chirp(0.12, [2600, 3200], (0, 1, 0))], 0.06))
    B["bird_nightingale"] = norm(seq([chirp(0.1, [1800 + 300 * _R.random(), 3600], (0, 1, 0), (0, 0)) for _ in range(5)] + [chirp(0.7, [2900, 3300], (0, 1, 1, 0), (28, 700))] + [chirp(0.4, [2000, 2600], (0, 1, 1, 0), (0, 0)) for _ in range(2)], 0.05))
    B["bird_songbird_day"] = norm(seq([chirp(_R.uniform(0.08, 0.2), [_R.uniform(2800, 4200), _R.uniform(3000, 5200), _R.uniform(2500, 4200)], (0, 1, 0.7, 0), (0, 0)) for _ in range(10)], 0.04))
    B["bird_tit"] = norm(seq([chirp(0.1, [4100, 5200], (0, 1, 0)), chirp(0.1, [4100, 5200], (0, 1, 0)), chirp(0.1, [3900, 5000], (0, 1, 0)), chirp(0.1, [3900, 5000], (0, 1, 0))], 0.12))
    B["bird_cuckoo"] = norm(seq([chirp(0.28, [770, 640], (0, 1, 0.8, 0.0), (0, 0), (1, 0.4, 0.1)), chirp(0.4, [640, 560], (0, 1, 0.9, 0), (0, 0), (1, 0.4, 0.1))], 0.04) * 1.0)
    B["bird_woodpecker"] = norm(sum(_hit(1.2, c) for c in np.arange(0.0, 0.8, 0.058)))
    B["bird_owl"] = norm(seq([chirp(0.35, [420, 400], (0, 1, 0.7, 0), (0, 0), (1, 0.3)), chirp(0.2, [400, 380], (0, 1, 0), (0, 0), (1, 0.3)), chirp(0.9, [430, 340], (0, 1, 1, 0), (0, 0), (1, 0.3))], 0.15))
    B["bird_owl_little"] = norm(seq([chirp(0.18, [850, 900, 700], (0, 1, 0)) for _ in range(3)], 0.28))
    B["bird_duck"] = norm(seq([vox(0.2, [600, 440], [(700, 100, 1), (1800, 200, 0.7), (2800, 300, 0.4)], [0, 1, 0.5, 0], breath=0.25, jit=0.06) for _ in range(3)], 0.07))
    B["bird_duck_flock"] = norm(_flock(B["bird_duck"], 3.0, 6, 0.8, 0.85, 1.2))
    B["bird_duck_takeoff"] = norm(pulses(1.5, 14, 600, 3500, 0.025, 0.2) + put(np.zeros(int(1.5 * SR)), B["bird_duck"][:int(0.7 * SR)] * 0.4, 0.5))
    B["bird_goose"] = norm(seq([vox(0.4, [450, 600, 520], [(800, 120, 1), (1700, 250, 0.6)], [0, 1, 0.7, 0], breath=0.2, jit=0.04) for _ in range(2)], 0.1))
    B["bird_swan"] = norm(vox(0.7, [500, 700, 600], [(900, 130, 1), (2000, 250, 0.5)], [0, 1, 0.9, 0], breath=0.25, jit=0.03))
    B["bird_seagull"] = norm(seq([vox(0.3, [1100, 1700, 1300], [(1500, 200, 1), (3000, 400, 0.6)], [0, 1, 0.7, 0], breath=0.2, jit=0.04), vox(0.4, [1500, 1150, 900], [(1400, 200, 1), (2800, 400, 0.5)], [0, 1, 0.8, 0], breath=0.2, jit=0.04), vox(0.3, [1400, 1000], [(1400, 200, 1), (2800, 400, 0.5)], [0, 1, 0], breath=0.2)], 0.08))
    B["bird_heron"] = norm(vox(0.7, [320, 260, 200], [(500, 100, 1), (1200, 200, 0.7), (2400, 350, 0.4)], [0, 1, 0.8, 0], breath=0.6, jit=0.12))
    t = T(1.6); B["bird_stork_clatter"] = norm(sum(modal(t, [(f, 0.04, a) for f, a in ((900, 1.0), (1700, 0.6), (2700, 0.3))], c) + filt(nz(len(t)), 600, 4000) * E(t - c, 0.0003, 0.006) * (t > c) for c in np.cumsum(np.concatenate([[0.0], 0.065 * np.exp(-np.arange(16) / 11.0)]))))
    B["bird_rooster"] = norm(np.concatenate([vox(0.35, [550, 900], [(900, 150, 1), (2400, 300, 0.5)], [0, 1, 0.9, 0], breath=0.1, jit=0.04), np.zeros(int(0.05 * SR)), vox(0.2, [900, 1000], [(1000, 150, 1)], [0, 1, 0], breath=0.1), vox(0.2, [1000, 1050], [(1000, 150, 1), (2500, 300, 0.4)], [0, 1, 0], breath=0.1), vox(0.9, [800, 1150, 1000, 650, 350], [(1000, 160, 1), (2500, 300, 0.5)], [0, 1, 1, 0.8, 0], breath=0.1, vib=(9, 0.04))]))
    B["bird_hen"] = norm(seq([vox(0.12, [500, 560, 450], [(800, 150, 1), (1800, 300, 0.5)], [0, 1, 0], breath=0.2, jit=0.05) for _ in range(4)], 0.06))
    B["bird_jay"] = norm(seq([vox(0.28, [1700, 1400, 1550], [(1500, 250, 1), (3000, 500, 0.6)], [0, 1, 0.7, 0], breath=0.7, jit=0.2) for _ in range(2)], 0.1))
    B["bird_hoopoe"] = norm(seq([chirp(0.14, [530, 480], (0, 1, 0), (0, 0), (1, 0.3)) for _ in range(3)], 0.12))
    B["bird_wings_flap"] = norm(pulses(1.2, 9, 250, 2000, 0.03, 0.2) * np.sin(np.pi * T(1.2) / 1.2) + 0.2 * filt(nz(int(1.2 * SR)), 1000, 5000) * np.sin(np.pi * T(1.2) / 1.2))
    B["bird_hawk"] = norm(chirp(1.2, [2200, 3800, 3000, 2200], (0, 1, 0.9, 0.5, 0), (0, 0), (1, 0.4, 0.2)) + 0.15 * filt(nz(int(1.2 * SR)), 1500, 5000))
    return B


def _hit(dur, c):
    k = int(0.05 * SR)
    out = np.zeros(int(dur * SR))
    put(out, modal(T(0.05), [(1200, 0.01, 1.0), (500, 0.015, 0.6)]) + filt(nz(k), 600, 4000) * E(T(0.05), 0.0003, 0.004), c)
    return out


def _flock(x, dur, n, lo, hi_a, hi_b):
    out = np.zeros(int(dur * SR))
    for _ in range(n):
        s = _R.uniform(hi_a, hi_b)
        idx = (np.arange(int(len(x) / s)) * s).astype(int)
        put(out, x[idx] * _R.uniform(0.4, 1.0), _R.uniform(0, dur * 0.5))
    return out
