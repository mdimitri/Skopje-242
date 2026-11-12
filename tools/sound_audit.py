"""Loudness audit of the procedural sounds (audio.build): K-weighted loudness of the active part + sample peak, per sound and per category.
Run: python3 tools/sound_audit.py [--csv out.csv] [--wav dir]   (needs numpy only; pyray is stubbed)"""
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.modules.setdefault("pyray", types.ModuleType("pyray"))
import audio  # noqa: E402
import loudness  # noqa: E402


def kweight(x, sr):
    """BS.1770 K-weighting applied in the frequency domain (analytic biquad responses)."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    w = 2 * np.pi * f / sr
    z = np.exp(-1j * w)

    def bq(b, a):
        return (b[0] + b[1] * z + b[2] * z ** 2) / (a[0] + a[1] * z + a[2] * z ** 2)
    # stage coefficients are defined at 48 kHz; recompute for sr via the same analog prototypes
    def shelf(fs):
        G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.9744509555319
        K = np.tan(np.pi * fc / fs); Vh = 10 ** (G / 20); Vb = Vh ** 0.4996667741545416
        a0 = 1 + K / Q + K * K
        return [(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0]

    def hp(fs):
        Q, fc = 0.5003270373238773, 38.13547087613982
        K = np.tan(np.pi * fc / fs)
        return [1, -2, 1], [1, 2 * (K * K - 1) / (1 + K / Q + K * K), (1 - K / Q + K * K) / (1 + K / Q + K * K)]
    H = bq(*shelf(sr)) * bq(*hp(sr))
    return np.fft.irfft(np.fft.rfft(x) * H, n)


def lufs(x, sr, loop=False):
    """Loudness (LUFS-like) of the whole signal for loops, of the active part (100 ms blocks within 25 dB of the loudest) for one-shots."""
    x = np.asarray(x, np.float64)
    if len(x) < 64 or not np.abs(x).max() > 1e-6:
        return -99.0
    pad = max(0, int(0.4 * sr) - len(x))
    w = kweight(np.concatenate([x, np.zeros(pad)]), sr)
    if loop:
        ms = float((w[:len(x)] ** 2).mean())
    else:
        hop = max(1, sr // 10)
        m = max(1, len(w) // hop)
        e = np.array([(w[i * hop:(i + 1) * hop] ** 2).mean() for i in range(m)])
        e = e[e > e.max() * 10 ** (-2.5)]
        ms = float(e.mean())
    return -0.691 + 10 * np.log10(ms + 1e-12)


def category(k):
    for p, c in (("ai_engine", "engine"), ("engine", "engine"), ("step", "foot"), ("land", "foot"), ("jump", "foot"), ("vault", "foot"), ("puddle", "foot"),
                 ("bark", "animal"), ("yip", "animal"), ("birds", "ambient"), ("crickets", "ambient"), ("city", "ambient"), ("crowd", "ambient"),
                 ("traffic", "ambient"), ("wind", "ambient"), ("siren", "siren"), ("horn", "horn"), ("chime", "ui"), ("tick", "ui"), ("pick", "ui"),
                 ("cash", "ui"), ("revive", "ui"), ("bell", "ui"), ("wpn", "ui")):
        if k.startswith(p):
            return c
    return "impact"


LOOPS = set(audio.LOOP_KEYS)


def library():
    """Raw loudness of the artist library (decoded with ffmpeg) against the target of its key: how much gain the game applies."""
    import glob
    import json
    import subprocess
    import soundcat
    rows = {}
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "library")
    for js in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
        try:
            key = json.load(open(js))["meta"]["key"]
        except Exception:
            continue
        for f in glob.glob(js[:-5] + "_v*.mp3"):
            sr = 24000
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True).stdout
            x = np.frombuffer(raw, np.float32)
            row = soundcat.BY_KEY.get(key)
            rows.setdefault(key, []).append((lufs(x, sr, bool(row and row[2])), 20 * np.log10(np.abs(x).max() + 1e-9), loudness.ref(key, row[6] if row else None)))
    print("== library (raw, before the game's gain)")
    for k, v in sorted(rows.items()):
        print(f"   {k:28s} files {len(v):2d}  raw {min(a[0] for a in v):6.1f}..{max(a[0] for a in v):6.1f} LUFS  peak {max(a[1] for a in v):5.1f} dB  game target {v[0][2]:5.1f}")


def main():
    S = audio.build()
    rows = []
    for k, x in sorted(S.items()):
        rows.append((category(k), k, lufs(x, audio.SR, k in LOOPS or k.startswith("amb")), 20 * np.log10(np.abs(x).max() + 1e-9), len(x) / audio.SR, loudness.ref(k)))
    if "--wav" in sys.argv:
        d = sys.argv[sys.argv.index("--wav") + 1]
        os.makedirs(d, exist_ok=True)
        for k, x in S.items():
            audio._save(os.path.join(d, k + ".wav"), x)
    for c in sorted({r[0] for r in rows}):
        rs = [r for r in rows if r[0] == c]
        print(f"== {c}: n={len(rs)} LUFS min {min(r[2] for r in rs):.1f} max {max(r[2] for r in rs):.1f}")
        for r in rs:
            print(f"   {r[1]:28s} {r[2]:7.1f} LUFS (target {r[5]:5.1f}, off {r[2] - r[5]:+.1f})  peak {r[3]:6.1f} dB  {r[4]:.2f}s")


if __name__ == "__main__":
    main()
    if "--library" in sys.argv:
        library()
