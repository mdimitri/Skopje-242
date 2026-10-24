"""v2.1 load-time quality control for the AI-generated library: reject broken versions, find trim points, clean and shape the rest.

analyse()  -> facts about one decoded file (or why it is rejected); results are cached in library/.soundcache.json
decide()   -> drops versions that do not look like their siblings
Processor  -> background thread that does both for the whole library, then publishes the good files to Audio.lib
prepare()  -> the per-load clean-up (rumble filter, trim, fades, loop crossfade, optional 'far' low-pass), numpy only"""
import json
import os
import threading
import time

import numpy as np
import pyray as rl

import soundcat

VER = 4                                          # bump to force a re-analysis of the whole library
CLIP_FRAC = 0.003                                # share of samples at full scale before a file counts as clipped
LOW_CUT = 25.0                                   # Hz, removes DC and sub-sonic rumble
FAR_CUT = 2800.0                                 # Hz, low-pass of the 'far' copy used for distant one-shots


def decode(path):
    """mp3/wav -> (float32 mono samples, sample rate) via raylib (no audio device needed)."""
    w = rl.load_wave(path)
    try:
        n = w.frameCount * w.channels
        if n <= 0 or w.sampleSize not in (16, 32):
            return None, 0
        a = np.frombuffer(rl.ffi.buffer(w.data, n * (4 if w.sampleSize == 32 else 2)), dtype=np.float32 if w.sampleSize == 32 else np.int16)
        x = a.astype(np.float32)
        if w.sampleSize == 16:
            x /= 32768.0
        if w.channels > 1:
            x = x.reshape(-1, w.channels).mean(axis=1)
        return x, w.sampleRate
    finally:
        rl.unload_wave(w)


def _fft_filter(x, sr, lo=None, hi=None):
    """Zero-phase band limit with soft edges (no scipy needed)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    g = np.ones_like(f)
    if lo:
        g *= np.clip((f - lo * 0.5) / (lo * 0.5), 0.0, 1.0)              # 0 below lo/2, full at lo
    if hi:
        g *= np.clip((hi * 2.0 - f) / hi, 0.0, 1.0) ** 2               # full at hi, closed by 2*hi
    return np.fft.irfft(X * g, len(x)).astype(np.float32)


# ---------------------------------------------------------------- what each catalogue entry is expected to sound like
_TONAL_LOOPS = ("engine_", "screech", "siren_", "street_lamp", "power_transformer", "neon_", "crane_hum", "car_alarm", "amb_wedding", "street_musician", "crickets", "cicadas", "frog")
_TONAL_SHOTS = ("horn", "bell", "clock_tower", "chime", "tick", "pick", "revive", "ui_", "teleport", "denied", "fuel_warning", "whistle", "scooter_bell", "siren_", "train_horn",
                "car_lock", "defib", "truck_reverse", "bird_", "dog", "cat_", "cow_", "sheep", "donkey", "horse", "frog", "baby_cry", "kids_", "crowd_", "coughing", "sneeze", "clap")


_HISSY = ("spray", "angle_grinder", "jackhammer", "fire_crackle", "bullet_ricochet", "handbrake", "wind_gust", "thunder", "sweeper", "garbage", "amb_lake", "amb_creek",
          "amb_river", "bus_air_brake", "fire_out", "fuel_pour", "splash", "swim", "crowd", "swing", "fireworks", "tin_roof", "laundry", "car_hood", "boom", "crash_glass", "saw_wood", "screech")
_CLEAN_LOOPS = ("city", "traffic", "wind", "amb_street", "amb_wind", "amb_forest", "amb_park", "amb_meadow", "amb_hill", "amb_dawn", "amb_courtyard", "amb_traffic", "amb_railway")
_UI = ("tick", "pick", "chime", "revive", "ui_click", "ui_confirm", "teleport_whoosh", "denied_buzz", "fuel_warning", "cash", "map_paper")
_HIT_FOLDERS = ("weapons", "explosions", "impacts", "fight", "steps")


def profile(row):
    """Expected look of one catalogue entry -> the limits analyse() holds a sample to.  Calibrated on real MOSS output (536 files): the limits only
    catch gross failures - noise/hiss, tones, silence, reversed or endless one-shots, glitches, repetition - not taste.
    Keys: loop, tonal (a steady tone is fine), hissy (broadband noise is fine), cent (Hz range of the spectral centroid), hf (max share of energy
    above 5 kHz), steady (max std of the level in dB, loops), onset / decay (hits only: latest peak position, least fall of the tail in dB; None = not
    checked), crest (min peak/rms), clicks (max sample glitches for clean loops, None = not checked), dur (seconds of useful sound)."""
    key, folder, loop, _secs, _n, _p, _l, _fb = row
    top = folder.split("/")[0]
    P = {"loop": bool(loop), "tonal": any(key.startswith(k) for k in (_TONAL_LOOPS if loop else _TONAL_SHOTS)), "hissy": any(key.startswith(k) for k in _HISSY),
         "flatout": False, "cent": (20, 12000), "hf": 0.97, "steady": 13.0, "onset": None, "decay": None, "crest": 1.4, "clicks": None, "dur": (0.08, 31.0)}
    if P["hissy"]:
        P["cent"] = (20, 16000)
    if loop:
        if key.startswith("engine_"):
            P.update(steady=10.0)
        elif key.startswith("siren_"):
            P.update(cent=(150, 6000), steady=10.0)
        elif key in ("birds", "construction", "crowd") or top in ("construction",) or key.startswith(("amb_playground", "amb_football", "amb_cafe", "amb_bazaar", "amb_market", "amb_industrial")):
            P.update(steady=16.0)
        if any(key.startswith(k) for k in _CLEAN_LOOPS):
            P["clicks"] = 15
        return P
    P.update(steady=99.0, flatout=top in ("birds", "animals"))
    if (top in _HIT_FOLDERS and key != "cpr_pump") or key in ("kerb_bump", "door_slam", "prop_thud", "car_door_close", "car_door_slam", "bin_clang", "metal_clank"):
        P.update(onset=0.85, decay=5.0, crest=1.6, tonal=P["tonal"] or key in ("bin_clang", "metal_clank"))
        if key.startswith("step_") or key == "puddle_step":
            P["dur"] = (0.04, 2.0)
    if key in _UI:
        P.update(hf=0.35, cent=(150, 5500))                           # menu / pickup sounds must be clean: a bright hissy tick is not a click
    if any(key.startswith(k) for k in ("horn", "siren_", "train_horn", "car_alarm", "truck_reverse", "whistle", "bell", "clock_tower", "defib", "fuel_warning")):
        P.update(onset=None, decay=None, crest=1.1)
    for pre, need in (("horn", 14), ("whistle", 10), ("clock_tower", 12), ("truck_reverse", 10)):
        if key.startswith(pre):
            P["need_tone"] = need                                    # a horn / whistle that is only noise is wrong
    return P


def _welch(x, sr, nfft=2048):
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    st = np.linspace(0, len(x) - nfft, min(400, max(1, (len(x) - nfft) // (nfft // 2) + 1))).astype(int)
    P = np.abs(np.fft.rfft(x[st[:, None] + np.arange(nfft)[None, :]] * np.hanning(nfft), axis=1)) ** 2
    return P, np.fft.rfftfreq(nfft, 1.0 / sr)


def features(x, sr):
    """Measurements of the part of the sound that is not silence (x already DC-free)."""
    P, f = _welch(x, sr)
    psd = P.mean(axis=0)
    band = (f >= 60) & (f <= min(0.45 * sr, 16000))
    pb = psd[band] + 1e-20
    flat = float(np.exp(np.log(pb).mean()) / pb.mean())
    sl = (f >= 100) & (f <= min(8000, 0.45 * sr))
    slope = float(np.polyfit(np.log2(f[sl]), 10 * np.log10(psd[sl] + 1e-20), 1)[0])
    hf = float(psd[f >= 5000].sum() / (psd[f >= 60].sum() + 1e-20))
    cb = f >= 40
    cent = float((f[cb] * psd[cb]).sum() / (psd[cb].sum() + 1e-20))
    # a steady tone: a bin far above its neighbours that stays there in most frames
    w = 41
    loc = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(psd, (w // 2, w // 2), mode="edge"), w), axis=1) + 1e-20
    r = np.where(band, psd / loc, 0.0)
    k = int(np.argmax(r))
    tone_db = float(10 * np.log10(r[k] + 1e-20))
    persist = float((P[:, k] > 5 * loc[k]).mean())
    # envelope in 10 ms frames
    hop = max(1, int(sr * 0.01))
    m = max(1, len(x) // hop)
    fr = np.sqrt((x[:m * hop].reshape(m, hop) ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(fr)
    db_fr = db
    pk = float(db.max())
    act = db > pk - 40
    std_db = float(db[act].std()) if act.sum() > 2 else 0.0
    pw = fr ** 2
    sm = 10 * np.log10(np.convolve(pw, np.ones(10) / 10, mode="same") + 1e-18)          # level smoothed over 100 ms: single noisy frames do not count as the peak
    tail = 10 * np.log10(pw[-max(1, m // 5):].mean() + 1e-18) - sm.max()
    rises = np.flatnonzero((db[3:] - db[:-3] > 10) & (db[3:] > pk - 25)) + 3 if m > 4 else np.array([], int)
    onsets = int(1 + (np.diff(rises) > 8).sum()) if len(rises) else 1
    crest = float(np.abs(x).max() / (np.sqrt((x * x).mean()) + 1e-9))
    # digital dropouts (runs of exact silence inside the sound) and clicks (isolated sample jumps)
    dead = (fr < 4e-4) & (db_fr < db_fr.max() - 50)
    run = best = 0
    for d in dead:
        run = run + 1 if d else 0
        best = max(best, run)
    dd = np.abs(np.diff(x))
    mm = max(1, len(dd) // hop)
    dm = dd[:mm * hop].reshape(mm, hop).max(axis=1)
    dr = np.sqrt((dd[:mm * hop].reshape(mm, hop) ** 2).mean(axis=1)) + 1e-9
    clicks = int(((dm > 25 * np.median(dr)) & (dm > 0.15 * np.abs(x).max())).sum()) if mm > 10 else 0
    # repetition: the waveform matching itself at some lag (digital looping / stutter)
    seg = x[:min(len(x), 20 * sr)]
    ac = np.fft.irfft(np.abs(np.fft.rfft(seg, 2 * len(seg))) ** 2)[:len(seg)]
    ac = ac / (ac[0] + 1e-20)
    lo_, hi_ = int(0.2 * sr), min(len(seg) // 2, int(8 * sr))
    rep = float(ac[lo_:hi_].max()) if hi_ > lo_ else 0.0
    return {"flat": flat, "slope": slope, "hf": hf, "cent": cent, "tone_db": tone_db, "persist": persist, "std": std_db, "tail": float(tail),
            "onset_pos": float(np.argmax(sm) / m), "onsets": onsets, "crest": crest, "dead_s": best * 0.01, "clicks": clicks, "rep": rep,
            "rms_db": float(db[act].mean())}


def analyse(x, sr, secs, loop, row=None):
    """-> dict(ok, reason, t0, t1, rms_db, cent) for one decoded file; t0/t1 are the kept range in seconds.  Never raises."""
    try:
        return _analyse(x, sr, secs, loop, row)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"analysis error: {type(e).__name__}"}


def _analyse(x, sr, secs, loop, row):
    def no(why):
        return {"ok": False, "reason": why}
    if x is None or len(x) == 0:
        return no("empty file")
    if not (16000 <= sr <= 192000):
        return no(f"bad sample rate ({sr} Hz)")
    n = len(x)
    if n < sr * 0.2:
        return no("too short")
    if not np.isfinite(x).all():
        return no("corrupt samples (NaN/Inf)")
    if n / sr < 0.4 * secs:
        return no(f"truncated ({n / sr:.1f}s of {secs}s)")
    if n / sr > 2.0 * secs + 2.0:
        return no(f"too long ({n / sr:.1f}s of {secs}s)")
    pk0 = float(np.abs(x).max())
    if pk0 < 0.005:
        return no("silent")
    if abs(float(x.mean())) > 0.2 * pk0 and pk0 < 0.5:
        return no("DC offset instead of sound")
    x = x - x.mean()
    pk = float(np.abs(x).max())
    if float((np.abs(x) >= 0.99).mean()) > CLIP_FRAC:
        return no("clipped")
    hop = max(1, int(sr * 0.05))
    m = n // hop
    fr = np.sqrt((x[:m * hop].reshape(m, hop) ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(fr)
    act = db > 20 * np.log10(pk) - (50 if loop else 42)
    if act.mean() < (0.12 if loop else 0.02):
        return no("mostly silence")
    i0, i1 = int(np.argmax(act)), len(act) - int(np.argmax(act[::-1]))
    t0 = 0.0 if loop else max(0, i0 - 1) * hop / sr
    t1 = n / sr if loop else min(n, (i1 + 1) * hop) / sr
    if t1 - t0 < 0.12:
        return no("too short after trimming")
    seg = x[int(t0 * sr):int(t1 * sr)]
    fe = features(seg, sr)
    info = {"ok": True, "reason": "", "t0": round(t0, 3), "t1": round(t1, 3), "rms_db": round(fe["rms_db"], 1), "cent": round(fe["cent"], 1)}
    if row is None:
        return info
    P = profile(row)
    dur = t1 - t0
    why = None
    if not P["dur"][0] <= dur <= P["dur"][1]:
        why = f"wrong duration for this sound ({dur:.2f}s)"
    elif fe["dead_s"] >= (0.08 if loop else 1.5):
        why = f"dropout ({fe['dead_s'] * 1000:.0f} ms of digital silence)"
    elif not P["cent"][0] <= fe["cent"] <= P["cent"][1]:
        why = f"wrong brightness (centroid {fe['cent']:.0f} Hz, expected {P['cent'][0]}-{P['cent'][1]})"
    elif fe["hf"] > P["hf"] and not P["hissy"]:
        why = f"hiss ({fe['hf'] * 100:.0f}% of energy above 5 kHz)"
    elif fe["flat"] > 0.5 and fe["slope"] > -1.5 and not P["hissy"]:
        why = f"white noise / hiss (flatness {fe['flat']:.2f}, slope {fe['slope']:.1f} dB/oct)"
    elif fe["flat"] > 0.75 and fe["slope"] > -1.5:
        why = f"pure white noise (flatness {fe['flat']:.2f})"
    elif not P["tonal"] and fe["tone_db"] > 38 and fe["persist"] > 0.8:
        why = f"unexpected steady tone / whistle ({fe['tone_db']:.0f} dB peak)"
    elif fe["tone_db"] < P.get("need_tone", 0):
        why = f"no tone where one is expected ({fe['tone_db']:.0f} dB)"
    elif not P["loop"] and P["flatout"] and fe["std"] < 2.0 and dur > 1.0:
        why = f"steady noise instead of a one-shot (level varies only {fe['std']:.1f} dB)"
    elif P["loop"] and fe["std"] > P["steady"]:
        why = f"not steady enough for a loop (level varies {fe['std']:.1f} dB)"
    elif P["loop"] and P["clicks"] is not None and fe["clicks"] >= P["clicks"]:
        why = f"clicks / glitches ({fe['clicks']})"
    elif P["loop"] and not P["tonal"] and dur > 3.0 and fe["rep"] > 0.95:
        why = f"stutter / digital repetition (self-match {fe['rep']:.2f})"
    elif P["onset"] is not None and fe["onset_pos"] > P["onset"]:
        why = f"no clear onset (peak at {fe['onset_pos'] * 100:.0f}% of the sound)"
    elif P["decay"] is not None and fe["tail"] > -P["decay"] and dur > 0.5:
        why = f"does not decay (end only {-fe['tail']:.0f} dB below the peak)"
    elif not P["loop"] and fe["crest"] < P["crest"]:
        why = f"too flat/steady for a one-shot (crest {fe['crest']:.1f})"
    if why:
        return no(why)
    return info


def decide(infos):
    """infos: {path: analyse() dict}.  Marks versions that are far from the rest of their key (loudness > 20 dB or timbre > 6x)."""
    good = [p for p, i in infos.items() if i["ok"]]
    if len(good) >= 4:
        med_db = float(np.median([infos[p]["rms_db"] for p in good]))
        med_c = float(np.median([infos[p]["cent"] for p in good]))
        for p in good:
            i = infos[p]
            if abs(i["rms_db"] - med_db) > 20.0:
                infos[p] = {"ok": False, "reason": f"loudness outlier ({i['rms_db'] - med_db:+.0f} dB)"}
            elif med_c > 0 and not (1 / 6.0 < i["cent"] / med_c < 6.0):
                infos[p] = {"ok": False, "reason": f"timbre outlier (centroid {i['cent']:.0f} vs {med_c:.0f} Hz)"}
    return infos


def prepare(x, sr, info, loop, far=False):
    """Clean one accepted file: rumble filter, trim, loop crossfade or short fades, optional 'far' low-pass."""
    x = _fft_filter(x - x.mean(), sr, lo=LOW_CUT, hi=FAR_CUT if far else None)
    x = x[int(info.get("t0", 0) * sr):int(info.get("t1", len(x) / sr) * sr)]
    if loop:
        f = int(min(0.5 * sr, len(x) * 0.25))
        if f > 8:
            t = np.linspace(0, np.pi / 2, f, dtype=np.float32)              # equal-power crossfade of the tail into the head
            y = x[:-f].copy()
            y[:f] = x[:f] * np.sin(t) + x[-f:] * np.cos(t)
            return y
        return x
    a, b = min(len(x) // 4, int(0.004 * sr)), min(len(x) // 3, int(0.04 * sr))
    x = x.copy()
    if a:
        x[:a] *= np.linspace(0, 1, a, dtype=np.float32)
    if b:
        x[-b:] *= np.linspace(1, 0, b, dtype=np.float32)
    return x


class Processor:
    """Analyses every library file once (cached by size+mtime), then hands the good ones to audio.lib key by key."""

    def __init__(self, audio, lib_root, raw, log_dir):
        self.a, self.root, self.raw, self.log = audio, lib_root, raw, log_dir
        self.cache_fn = os.path.join(lib_root, ".soundcache.json")
        self.done = False

    def start(self, wait=False):
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        if wait:
            t.join()

    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            print(f"[sound] library check failed ({type(e).__name__}: {e}); the procedural sounds stay in use")
            self.done = True

    def _run(self):
        t0 = time.time()
        try:
            cache = json.load(open(self.cache_fn, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}
        rejects, n_ok, fresh = [], 0, 0
        for key, paths in self.raw.items():
            row = soundcat.BY_KEY.get(key)
            if not row:
                continue
            infos = {}
            for p in paths:
                try:
                    st = os.stat(p)
                    ck = os.path.relpath(p, self.root)
                    c = cache.get(ck)
                    if c and c.get("v") == VER and c.get("mt") == st.st_mtime_ns and c.get("sz") == st.st_size:
                        infos[p] = c["i"]
                        continue
                    x, sr = decode(p)
                    infos[p] = analyse(x, sr, row[3], row[2], row) if x is not None else {"ok": False, "reason": "undecodable"}
                    cache[ck] = {"v": VER, "mt": st.st_mtime_ns, "sz": st.st_size, "i": infos[p]}
                    fresh += 1
                except Exception as e:  # noqa: BLE001
                    infos[p] = {"ok": False, "reason": f"error: {e}"}
            decide(infos)
            good = [p for p, i in infos.items() if i["ok"]]
            for p, i in infos.items():
                if not i["ok"]:
                    rejects.append(f"{key}  {os.path.basename(p)}  {i['reason']}")
            n_ok += len(good)
            self.a.info.update({p: infos[p] for p in good})
            if good:
                self.a.lib[key] = good                                   # published: the game switches to it from now on
        try:
            tmp = self.cache_fn + ".tmp"
            json.dump(cache, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, self.cache_fn)
            os.makedirs(self.log, exist_ok=True)
            with open(os.path.join(self.log, "sound_rejects.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(rejects) + "\n")
        except Exception:  # noqa: BLE001
            pass
        self.done = True
        print(f"[sound] library checked in {time.time() - t0:.1f}s: {n_ok} versions accepted, {len(rejects)} rejected "
              f"({fresh} newly analysed){' - see logs/sound_rejects.txt' if rejects else ''}")
