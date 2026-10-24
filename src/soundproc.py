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

VER = 1                                          # bump to force a re-analysis of the whole library
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


def analyse(x, sr, secs, loop):
    """-> dict(ok, reason, t0, t1, rms_db, cent) for one decoded file; t0/t1 are the kept range in seconds."""
    n = len(x)
    if n < sr * 0.2:
        return {"ok": False, "reason": "too short"}
    if not np.isfinite(x).all():
        return {"ok": False, "reason": "corrupt samples"}
    if n / sr < 0.4 * secs:
        return {"ok": False, "reason": f"truncated ({n / sr:.1f}s of {secs}s)"}
    x = x - x.mean()
    pk = float(np.abs(x).max())
    if pk < 0.005:
        return {"ok": False, "reason": "silent"}
    if float((np.abs(x) >= 0.99).mean()) > CLIP_FRAC:
        return {"ok": False, "reason": "clipped"}
    hop = max(1, int(sr * 0.05))
    m = n // hop
    fr = np.sqrt((x[:m * hop].reshape(m, hop) ** 2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(fr)
    act = db > 20 * np.log10(pk) - (50 if loop else 42)                    # active = within 42 (loops 50) dB of the peak
    if act.mean() < (0.3 if loop else 0.02):
        return {"ok": False, "reason": "mostly silence"}
    i0, i1 = int(np.argmax(act)), len(act) - int(np.argmax(act[::-1]))
    t0 = 0.0 if loop else max(0, i0 - 1) * hop / sr
    t1 = n / sr if loop else min(n, (i1 + 1) * hop) / sr
    if t1 - t0 < 0.12:
        return {"ok": False, "reason": "too short after trimming"}
    seg = x[int(t0 * sr):int(t1 * sr)][:1 << 17]
    mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    fq = np.fft.rfftfreq(len(seg), 1.0 / sr)
    cent = float((fq * mag).sum() / (mag.sum() + 1e-9))
    return {"ok": True, "reason": "", "t0": round(t0, 3), "t1": round(t1, 3), "rms_db": round(float(db[act].mean()), 1), "cent": round(cent, 1)}


def decide(infos):
    """infos: {path: analyse() dict}.  Marks versions that are far from the rest of their key (loudness > 10 dB or timbre > 3.5x)."""
    good = [p for p, i in infos.items() if i["ok"]]
    if len(good) >= 4:
        med_db = float(np.median([infos[p]["rms_db"] for p in good]))
        med_c = float(np.median([infos[p]["cent"] for p in good]))
        for p in good:
            i = infos[p]
            if abs(i["rms_db"] - med_db) > 10.0:
                infos[p] = {"ok": False, "reason": f"loudness outlier ({i['rms_db'] - med_db:+.0f} dB)"}
            elif med_c > 0 and not (1 / 3.5 < i["cent"] / med_c < 3.5):
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
                    infos[p] = analyse(x, sr, row[3], row[2]) if x is not None else {"ok": False, "reason": "undecodable"}
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
