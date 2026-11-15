"""Measure every pedestrian kind (3 individuals each) and every hero: gender from styling, target and MEASURED median F0
and measured formant scale (best envelope warp vs. plain Suze).  Usage: verify_voices.py RAW_SUZE_WAV"""
import os, sys, numpy as np, soundfile as sf, pyworld as pw
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.stdout.reconfigure(encoding="utf-8")
import speech, voicelab as V, vehicles, hero_names
x, sr = sf.read(sys.argv[1]); x = x.astype(np.float64)
an = V.analyse(x, sr)
def env(y):
    f0, t = pw.harvest(y, sr, f0_floor=60, f0_ceil=600, frame_period=10); sp = pw.cheaptrick(y, f0, t, sr)
    v = f0 > 0
    return np.median(f0[v]), np.log(sp[v].mean(0) + 1e-12)
_, e0 = env(x)
fr = np.arange(len(e0)) * (sr / 2) / (len(e0) - 1); band = (fr > 250) & (fr < 4000)
def alpha_of(e):
    best = None
    for a in np.arange(.7, 1.4, .01):
        w = np.interp(fr / a, fr, e0)
        d = e[band] - w[band]; err = np.var(d)
        if best is None or err < best[0]: best = (err, a)
    return best[1]
rows, bad = [], 0
def check(who, label):
    global bad
    prof = speech.profile(who); vk = speech.voice_kind(who); g = vk[0] if vk else prof["g"]; old = vk[1] if vk else False
    p = V.params_for(who, prof)
    y = V.transform(x, p, sr, an).astype(np.float64)
    f0m, e = env(y); a = alpha_of(e)
    (flo, fhi), (alo, ahi) = (V.HERO_BAND.get((g, old)) if vk and vk[2] else None) or V.BAND[(g, old)]
    ok = flo * .93 <= f0m <= fhi * 1.07 and alo - .04 <= a <= ahi + .04
    bad += not ok
    print("%-34s %s%s  target f0 %5.0f a %.2f | measured f0 %5.0f a %.2f  %s" % (label, g, " old" if old else "    ", p["f0"], p["alpha"], f0m, a, "OK" if ok else "MISMATCH"))
print("plain Suze: measured f0 %.0f (formant scale 1.00 by definition)" % env(x)[0])
for full in hero_names.NAMES.values():
    check(full, "hero " + full)
for name in vehicles.PED_NAMES:
    for pid in (11, 222, 3333):
        check("%s#%d" % (name, pid), "%s #%d" % (name, pid))
print("mismatches:", bad)
