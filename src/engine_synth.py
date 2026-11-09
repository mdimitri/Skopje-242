"""Engine sound synthesis (numpy only).

Built from a study of real recordings (idle/motor loops, diesel, damaged and cranking engines): firing pulses are
irregular (timing + strength jitter, cylinder pattern), each pulse is a low "pop" plus exhaust noise (and a bright knock for
diesels), then the whole thing goes through a fixed body/exhaust filter in the frequency domain and is mixed with intake roar
and mechanical noise.  A loop is rendered circularly so it wraps without a click; start/stop/stall are rendered from a rate curve.
"""
import numpy as np

SR = 22050

# profile: ncyl pattern strengths, timing jitter, strength jitter, body Hz, pop decay, noise level, knock level, roar, tick, tone peaks (Hz, gain)
PROFILES = {
    "i4":     dict(pat=(1.0, 0.92, 0.96, 0.9), tj=0.03, aj=0.072, body=77.9, dec=55, nz=0.198, knock=0.0, roar=0.267, tick=0.08, peaks=((320, 1.0), (900, 0.6)), tilt=1.465),
    "small":  dict(pat=(1.0, 0.7, 0.9), tj=0.10, aj=0.18, body=130, dec=70, nz=0.42, knock=0.15, roar=0.18, tick=0.15, peaks=((600, 1.0), (1500, 0.7)), tilt=0.9),
    "v8":     dict(pat=(1.0, 0.8, 0.95, 0.7, 1.0, 0.75, 0.9, 0.85), tj=0.07, aj=0.15, body=70, dec=38, nz=0.33, knock=0.0, roar=0.18, tick=0.05, peaks=((180, 1.0), (500, 0.7)), tilt=1.3),
    "diesel": dict(pat=(1.0, 0.95, 0.9, 0.97), tj=0.07, aj=0.089, body=91.3, dec=45, nz=0.195, knock=1.269, roar=0.12, tick=0.257, peaks=((400, 0.8), (1800, 0.8), (3200, 0.5)), tilt=0.94),
    "tdi":    dict(pat=(1.0, 0.93, 0.95, 0.9), tj=0.079, aj=0.135, body=119.0, dec=50, nz=0.258, knock=0.846, roar=0.245, tick=0.28, peaks=((450, 0.8), (2200, 0.9)), tilt=0.991),
    "bus":    dict(pat=(1.0, 0.9, 0.95, 0.85, 0.97, 0.92), tj=0.094, aj=0.181, body=75.3, dec=35, nz=0.387, knock=0.826, roar=0.236, tick=0.076, peaks=((250, 1.0), (1200, 0.7)), tilt=1.193),
    "truck":  dict(pat=(1.0, 0.85, 0.95, 0.9, 0.8, 0.97), tj=0.1, aj=0.135, body=56.5, dec=30, nz=0.32, knock=0.608, roar=0.204, tick=0.15, peaks=((200, 1.0), (900, 0.8), (2500, 0.5)), tilt=1.112),
    "moto":   dict(pat=(1.0, 0.6), tj=0.09, aj=0.2, body=180, dec=80, nz=0.48, knock=0.2, roar=0.24, tick=0.21, peaks=((900, 1.0), (2500, 0.9)), tilt=0.7),
}
FIRE = {"i4": 44.0, "small": 62.0, "v8": 28.0, "diesel": 36.0, "tdi": 40.0, "bus": 30.0, "truck": 24.0, "moto": 52.0}


def _shape(freqs, P, kind_hi):
    """Fixed body/exhaust transfer function: spectral tilt, resonant peaks, a roll-off (more open for the high-rev layer)."""
    f = np.maximum(freqs, 1.0)
    h = (f / 100.0) ** (-0.35 * P["tilt"]) * (1.0 / (1.0 + (f / (7000.0 if kind_hi else 4200.0)) ** 2))
    h = h * (1.0 - np.exp(-f / 90.0))
    for fc, g in P["peaks"]:
        h = h + g * 0.9 * np.exp(-0.5 * ((f - fc) / (fc * 0.18)) ** 2)
    return h


def _noise_band(rng, n, lo, hi):
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    spec *= ((f > lo) & (f < hi)) * (1.0 / np.sqrt(np.maximum(f, 50.0) / 200.0))
    return np.fft.irfft(spec, n)


def render(kind, rate, n, seed=0, hi=False, circular=True, misfire=None):
    """rate: firing pulses per second (float, or an array of length n); misfire: optional array of dropout probability per sample."""
    P = PROFILES[kind]
    rng = np.random.default_rng(seed)
    r = np.full(n, float(rate), np.float64) if np.isscalar(rate) else np.asarray(rate, np.float64)
    ph = np.cumsum(r) / SR
    if circular:
        ph = ph * (round(ph[-1]) / ph[-1])
    k = int(ph[-1])
    idx = np.searchsorted(ph, np.arange(1, k + 1))
    x = np.zeros(n, np.float64)
    kn = np.zeros(n, np.float64)
    m = int(0.045 * SR)
    tt = np.arange(m) / SR
    rng_state = np.random.default_rng(seed + 1)
    for i, s in enumerate(idx):
        per = SR / max(r[min(s, n - 1)], 1.0)
        s = int(s + rng.normal(0, P["tj"] * per))
        a = P["pat"][i % len(P["pat"])] * (1 + rng.normal(0, P["aj"]))
        if misfire is not None and rng.random() < misfire[min(s % n, n - 1)]:
            a *= rng.uniform(0.0, 0.25)
        body = P["body"] * rng.uniform(0.92, 1.08)
        pop = np.sin(2 * np.pi * body * tt) * np.exp(-tt * P["dec"])
        bn = rng_state.standard_normal(m) * np.exp(-tt * 90) * P["nz"]
        pulse = (pop + bn) * a
        if hi:
            pulse = pulse * 0.8
        j = np.arange(m) + s
        if circular:
            x[j % n] += pulse
        else:
            ok = (j >= 0) & (j < n)
            x[j[ok]] += pulse[ok]
        if P["knock"]:
            kk = np.sin(2 * np.pi * rng.uniform(2200, 3300) * tt[:int(0.004 * SR)]) * np.exp(-tt[:int(0.004 * SR)] * 900) * P["knock"] * a * 0.8
            jj = np.arange(len(kk)) + s + int(0.002 * SR)
            if circular:
                kn[jj % n] += kk
            else:
                ok = (jj >= 0) & (jj < n)
                kn[jj[ok]] += kk[ok]
    # body / exhaust filter
    spec = np.fft.rfft(x) * _shape(np.fft.rfftfreq(n, 1.0 / SR), P, hi)
    y = np.fft.irfft(spec, n)
    y = y / (np.abs(y).max() + 1e-9)
    # pulse envelope for gating the noise layers
    env = np.abs(x)
    env = np.convolve(env, np.ones(int(0.008 * SR)) / (0.008 * SR), mode="same") if not circular else np.fft.irfft(np.fft.rfft(env) * np.fft.rfft(np.ones(int(0.008 * SR)) / (0.008 * SR), n), n)
    env = env / (env.max() + 1e-9)
    roar = _noise_band(rng, n, 150, 2600 if not hi else 4200)
    roar = roar / (np.abs(roar).max() + 1e-9) * P["roar"] * (1.5 if hi else 1.0) * (0.35 + 0.65 * env)
    tick = _noise_band(rng, n, 2500, 7500)
    tick = tick / (np.abs(tick).max() + 1e-9) * P["tick"] * (0.25 + 0.75 * env ** 2) * (1.4 if hi else 1.0)
    out = y + roar + tick + kn / (np.abs(kn).max() + 1e-9) * P["knock"] * 0.5
    return out


def loop(kind, hi=False, dur=1.6, seed=0):
    n = int(SR * dur)
    rate = FIRE[kind] * (1.6 if hi else 1.0)
    # a slow rev wobble over the loop (periodic, so it still wraps) keeps the idle from sounding like a machine
    t = np.arange(n) / SR
    wob = 1 + 0.012 * np.sin(2 * np.pi * (1.0 / dur) * t + seed) + 0.006 * np.sin(2 * np.pi * (3.0 / dur) * t + 2 * seed)
    x = render(kind, rate * wob, n, seed, hi)
    return (x / np.abs(x).max() * 0.55).astype(np.float32)


# long-term spectra (dB per band, 24 log-spaced bands 50 Hz..9 kHz) measured from two real damaged-engine recordings
_EDGES = np.geomspace(50, 9000, 25)
_DMG_SPEC = {
    "rough": [-18, -18, -19, 0, -4, -11, -9, -11, -16, -22, -18, -18, -22, -29, -30, -30, -32, -33, -38, -38, -44, -47, -52, -49],       # chugging, uneven firing
    "clunk": [-13, -8, -4, 0, -6, -10, -10, -12, -15, -9, -12, -13, -10, -13, -15, -17, -15, -14, -19, -18, -25, -30, -31, -35],         # heavy loose-metal clunks
}


def _damage(kind, mean_iv, sd_iv, thump, seed, dur=1.6):
    """Irregular heavy pulses (spacing mean/sd as measured on the recordings); each is noise shaped by the measured spectrum plus a low thump."""
    n = int(SR * dur)
    rng = np.random.default_rng(seed)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    db = np.interp(np.log(np.maximum(f, 1.0)), np.log(np.sqrt(_EDGES[:-1] * _EDGES[1:])), _DMG_SPEC[kind])
    h = 10 ** (db / 20.0) * (1 - np.exp(-f / 60.0))
    m = int(0.09 * SR)
    tt = np.arange(m) / SR
    x = np.zeros(n)
    t = rng.uniform(0, mean_iv)
    while t < dur:
        s = int(t * SR)
        a = rng.gamma(3.0, 1 / 3.0)
        burst = np.fft.irfft(np.fft.rfft(rng.standard_normal(m)) * np.interp(np.fft.rfftfreq(m, 1.0 / SR), f, h), m)
        pulse = (burst / (np.abs(burst).max() + 1e-9) + np.sin(2 * np.pi * thump * rng.uniform(0.9, 1.1) * tt) * 0.8) * np.exp(-tt * 40) * a
        x[(np.arange(m) + s) % n] += pulse
        t += max(0.02, rng.normal(mean_iv, sd_iv))
    return (np.tanh(x / np.abs(x).max() * 1.5) * 0.7).astype(np.float32)


def misfire_loop(seed=3, dur=1.6):
    """Rough chugging (reference: pulses about every 67 ms, +-20 %)."""
    return _damage("rough", 0.067, 0.014, 115, seed, dur)


def knock_loop(seed=5, dur=1.6):
    """Heavy loose-metal clunking (reference: pulses about every 50 ms, +-44 %)."""
    return _damage("clunk", 0.050, 0.022, 100, seed, dur)


def _env_ramp(n, pts):
    xs = np.array([p[0] for p in pts]) * SR
    ys = np.array([p[1] for p in pts])
    return np.interp(np.arange(n), xs, ys)


def start(kind="i4", dur=3.2, seed=7, diesel=False):
    """Starter cranking (ratcheting compression strokes, motor whirr), then the engine catches, overshoots and settles to idle."""
    n = int(SR * dur)
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    catch = 1.1 if not diesel else 1.9
    crank_hz = 6.5 if not diesel else 4.2
    rate = np.where(t < catch, crank_hz * 2.0, 0.0)
    r_run = _env_ramp(n, [(0, 0), (catch, 0), (catch + 0.08, 1.0), (catch + 0.45, 1.65), (catch + 1.0, 1.0), (dur, 0.97)])
    rate = rate + FIRE[kind] * r_run
    eng = render(kind, np.maximum(rate, 1.0), n, seed, False, False)
    eng *= _env_ramp(n, [(0, 0.5), (catch, 0.55), (catch + 0.06, 1.0), (dur, 1.0)])
    # starter motor: buzzy whirr at ~130 Hz with brush noise, labouring on each compression stroke
    ph = np.cumsum(np.full(n, 120.0) * (1 + 0.25 * np.sin(2 * np.pi * crank_hz * t))) / SR
    whirr = (np.sin(2 * np.pi * ph) + 0.5 * np.sign(np.sin(2 * np.pi * ph * 3))) * 0.18
    whirr += _noise_band(rng, n, 800, 4500) * 0.06
    whirr *= (t < catch + 0.25) * np.minimum(1, t / 0.03) * np.where(t > catch, np.exp(-(t - catch) * 12), 1.0)
    x = eng / (np.abs(eng).max() + 1e-9) * 0.75 + whirr
    return (x / np.abs(x).max() * 0.6).astype(np.float32)


def stall(kind="i4", dur=2.4, seed=11):
    """Cough and stall: lumpy slowing pulses with dropouts, a last half-hearted pop and silence."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    rate = FIRE[kind] * 0.5 * np.exp(-t * 0.9) * (1 + 0.3 * np.sin(2 * np.pi * 4 * t))
    drop = 0.15 + 0.5 * np.clip(t / 1.6, 0, 1)
    x = render(kind, np.maximum(rate, 2.0), n, seed, False, False, drop) * np.clip(1 - t / 1.9, 0, 1)
    return (x / (np.abs(x).max() + 1e-9) * 0.6).astype(np.float32)
