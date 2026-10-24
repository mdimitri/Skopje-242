"""Corpus test of the library quality check (src/soundproc.py): the game's own synthetic sounds as GOOD samples (round-tripped through mp3),
and one deliberately broken sample per failure mode and category as BAD ones.  Prints the false-rejection and rejection rates.
Needs ffmpeg.  Usage: python tools/test_soundproc.py [-v]"""
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import audio  # noqa: E402
import soundcat  # noqa: E402
import soundproc  # noqa: E402

SR = 48000
rng = np.random.default_rng(5)
TMP = tempfile.mkdtemp(prefix="sp_test_")


def wav(path, x, sr=SR, ch=1):
    x = np.asarray(x, np.float32)
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32000).astype(np.int16).tobytes())


def to_mp3(name, x, sr=SR, ch=1):
    w, m = os.path.join(TMP, name + ".wav"), os.path.join(TMP, name + ".mp3")
    wav(w, x, sr, ch)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", w, "-ar", str(sr), "-ac", str(ch), "-b:a", "128k", m], check=True)
    return m


def verdict(path, key, secs=None):
    row = soundcat.BY_KEY[key]
    if secs:
        row = row[:3] + (secs,) + row[4:]
    x, sr = soundproc.decode(path)
    return soundproc.analyse(x, sr, row[3], row[2], row) if x is not None else {"ok": False, "reason": "undecodable"}


def resample(x, sr0):
    return np.interp(np.arange(0, len(x), sr0 / SR), np.arange(len(x)), x).astype(np.float32)


def main():
    verbose = "-v" in sys.argv
    # ---- GOOD: every procedural sound of the game that has a catalogue row, as it would come from the artist (mp3, trimmed to the requested length)
    good = []
    for name, x in audio.build().items():
        key = soundcat.ALIAS.get(name, name)
        if key in soundcat.BY_KEY and name == key:
            row = soundcat.BY_KEY[key]
            y = resample(x, audio.SR)
            if not row[2]:                                           # one-shots arrive padded with silence to the requested length
                y = np.concatenate([np.zeros(int(0.15 * SR), np.float32), y])
                y = np.concatenate([y, np.zeros(max(int(0.4 * SR), int(row[3] * SR) - len(y)), np.float32)])
            good.append((key, to_mp3("good_" + key, y * 0.5), len(y) / SR if row[2] else None))
    fa = [(k, verdict(p, k, s)) for k, p, s in good]
    false_rej = [(k, v["reason"]) for k, v in fa if not v["ok"]]
    # ---- BAD: every case is built at the length the catalogue asks for and must be rejected for the matching reason
    def noise(n, tilt=0.0):                                          # tilt: dB/octave of the spectrum (0 white, -3 pink)
        X = np.fft.rfft(rng.standard_normal(n))
        f = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 20.0)
        y = np.fft.irfft(X * f ** (tilt / 6.02), n).astype(np.float32)
        return y / (np.abs(y).max() + 1e-9)
    LOOPS = ["city", "traffic", "wind", "amb_forest_day", "engine_i4", "siren_police", "amb_river_vardar"]
    HITS = ["shot_pistol", "crash", "punch", "step_asphalt", "boom"]
    ANIM = ["bird_crow", "dog", "horn"]

    def L(row, n=None):
        return int((n or row[3]) * SR)

    def burst(n, decay=0.25):
        tt = np.arange(n) / SR
        return noise(n, -4.0) * np.exp(-tt / decay) * (tt > 0.05)

    def with_clicks(n):
        x = noise(n, -6.0) * 0.3
        x[(np.arange(0, n - 1, int(0.4 * SR)))] += 0.9
        return x

    def stutter(n):
        c = noise(int(0.6 * SR), -6.0) * 0.4
        return np.tile(c, n // len(c) + 1)[:n]

    def gaps(n):
        x = noise(n, -6.0) * 0.4
        for i in range(0, n // SR):
            x[int((i + 0.3) * SR):int((i + 0.7) * SR)] = 0
        return x
    tone = lambda n, f=1000: (np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.3).astype(np.float32)   # noqa: E731
    cases = [  # (label, builder(row)->signal, keys, regex of acceptable reasons)
        ("white noise", lambda r: noise(L(r)) * 0.3, LOOPS + HITS + ANIM, "white|hiss|brightness|decay|onset"),
        ("pink noise, steady", lambda r: noise(L(r), -3.0) * 0.3, HITS + ["bird_crow", "dog"], "decay|onset|noise|crest|hiss"),
        ("hiss (HF noise)", lambda r: noise(L(r)) * 0.3 - np.roll(noise(L(r)) * 0.3, 1) * 0 + np.diff(np.concatenate([[0], noise(L(r))])) * 0.2, LOOPS + HITS + ANIM, "hiss|white|brightness|decay|onset|tone"),
        ("digital silence", lambda r: np.zeros(L(r)), LOOPS + HITS + ANIM, "silent"),
        ("near silence (-75 dB)", lambda r: noise(L(r)) * 0.0003, LOOPS + HITS + ANIM, "silent"),
        ("DC offset", lambda r: np.full(L(r), 0.4, np.float32) + noise(L(r)) * 0.002, LOOPS + HITS + ANIM, "DC|silent"),
        ("pure sine tone", lambda r: tone(L(r)), ["city", "traffic", "wind", "amb_forest_day", "amb_river_vardar", "shot_pistol", "crash", "punch", "step_asphalt", "boom"], "tone|decay|onset|steady"),
        ("hard clipping", lambda r: np.clip(noise(L(r)) * 30, -1, 1), LOOPS + HITS + ANIM, "clipped"),
        ("clicks in a steady loop", lambda r: with_clicks(L(r)), ["city", "traffic", "wind", "amb_forest_day"], "click|steady"),
        ("dropouts", lambda r: gaps(L(r)), LOOPS[:4] + ["amb_river_vardar"], "dropout|steady"),
        ("stutter / repetition", lambda r: stutter(L(r)), ["city", "traffic", "wind", "amb_river_vardar"], "stutter|steady"),
        ("one-shot that never decays", lambda r: noise(L(r), -4.0) * 0.3, HITS, "decay|noise|onset"),
        ("reversed one-shot", lambda r: burst(L(r), 0.3)[::-1].copy(), HITS, "onset|decay"),
        ("far too long", lambda r: noise(L(r, r[3] * 3 + 3), -4.0) * 0.3, HITS + ANIM, "too long|decay"),
        ("truncated (0.3 s)", lambda r: noise(L(r, 0.3), -4.0) * 0.3, LOOPS + HITS + ANIM, "truncated|short"),
        ("horn that is only noise", lambda r: burst(L(r), 0.4) + 0.0, ["horn", "horn_small", "horn_truck"], "tone|noise|hiss|white"),
    ]
    results = []
    for label, build, keys, ok_re in cases:
        for key in keys:
            row = soundcat.BY_KEY[key]
            sig = np.asarray(build(row), np.float32)
            v = verdict(to_mp3(f"bad_{abs(hash(label)) % 9999}_{key}", sig), key)
            if not v["ok"] and not re.search(ok_re, v["reason"]):
                v = dict(v, wrong_reason=True)
            results.append((label, key, v))
    # ---- wrong container / sample rate / channels / garbage
    for label, builder in (("8 kHz sample rate", lambda: to_mp3("sr8", noise(SR * 4, -4.0) * 0.2, sr=8000)),
                           ("stereo file", lambda: to_mp3("stereo", np.stack([noise(SR * 4, -4.0)] * 2, 1).reshape(-1) * 0.2, ch=2)),
                           ("0-byte file", lambda: open(os.path.join(TMP, "z.mp3"), "wb").close() or os.path.join(TMP, "z.mp3")),
                           ("garbage bytes", lambda: (open(os.path.join(TMP, "g.mp3"), "wb").write(os.urandom(5000)), os.path.join(TMP, "g.mp3"))[1]),
                           ("missing file", lambda: os.path.join(TMP, "nope.mp3"))):
        try:
            p = builder()
            v = verdict(p, "city")
        except Exception as e:  # noqa: BLE001
            v = {"ok": True, "reason": f"CRASH {type(e).__name__}: {e}"}
        results.append((label, "city", v))
    for label, arr in (("NaN samples", np.full(SR * 3, np.nan, np.float32)), ("Inf samples", np.full(SR * 3, np.inf, np.float32)),
                       ("zero-length decode", np.zeros(0, np.float32))):
        v = soundproc.analyse(arr, SR, 6, True, soundcat.BY_KEY["city"])
        results.append((label, "city", v))
    # ---- end to end: corrupt sidecars, path tricks, an all-bad sound (must fall back to the procedural sound), a good one
    import json
    import soundlib
    lib = os.path.join(TMP, "e2e", "library", "birds")
    os.makedirs(lib)
    good_mp3 = to_mp3("e2e_good", burst(int(4 * SR), 0.5) * 0.4)
    bad_mp3 = to_mp3("e2e_bad", noise(4 * SR) * 0.3)
    for i in range(4):
        for src, dst in ((good_mp3, f"bird_crow_aaaaaa_v0{i + 1}_seed{i}.mp3"), (bad_mp3, f"bird_dove_bbbbbb_v0{i + 1}_seed{i}.mp3")):
            open(os.path.join(lib, dst), "wb").write(open(src, "rb").read())
    for key, rid in (("bird_crow", "bird_crow_aaaaaa"), ("bird_dove", "bird_dove_bbbbbb")):
        json.dump({"id": rid, "meta": {"key": key}, "files": [{"version": i + 1, "seed": i, "file": f"{rid}_v0{i + 1}_seed{i}.mp3"} for i in range(4)] +
                   [{"file": "../../../../etc/passwd.mp3"}, {"file": 5}, "junk"]}, open(os.path.join(lib, rid + ".json"), "w"))
    open(os.path.join(lib, "broken.json"), "w").write("{not json")
    open(os.path.join(lib, "list.json"), "w").write("[1, 2, 3]")
    json.dump({"id": 7, "files": None}, open(os.path.join(lib, "weird.json"), "w"))
    au = audio.Audio(mute=True, root=os.path.join(TMP, "e2e"), dry=True)
    e2e_ok = "bird_crow" in au.lib and "bird_dove" not in au.lib and all(os.path.dirname(p).startswith(lib) for v in au.lib.values() for p in v)
    au._pick("bird_dove")
    fell_back = au.stats.get(("bird_dove", "fallback:None")) is None and not any(k[0] == "bird_dove" and k[1] == "lib" for k in au.stats)
    print(f"END TO END: good sound published={'bird_crow' in au.lib}, all-bad sound withheld={'bird_dove' not in au.lib}, corrupt sidecars survived, path trick ignored: {e2e_ok and fell_back}")
    accepted = [(l, k, v) for l, k, v in results if v["ok"] and l not in ("stereo file",)]
    wrong = [(l, k, v) for l, k, v in results if v.get("wrong_reason")]
    n_bad = len([1 for l, k, v in results if l != "stereo file"])
    print(f"GOOD samples: {len(good)}   false rejections: {len(false_rej)} ({100 * len(false_rej) / max(1, len(good)):.0f} %)")
    for k, r in false_rej:
        print(f"   FALSE REJECT {k}: {r}")
    print(f"BAD samples: {n_bad}   correctly rejected: {n_bad - len(accepted)} ({100 * (n_bad - len(accepted)) / max(1, n_bad):.0f} %)")
    for l, k, v in accepted:
        print(f"   MISSED {l} as {k}")
    print(f"   rejected for an unexpected reason: {len(wrong)}")
    for l, k, v in wrong:
        print(f"   WRONG REASON {l} as {k}: {v['reason']}")
    if verbose:
        for l, k, v in results:
            print(f"   {l:28s} {k:18s} {'OK  ' if v['ok'] else 'REJ '} {v.get('reason', '')}")
    return len(false_rej), len(accepted)


if __name__ == "__main__":
    main()
