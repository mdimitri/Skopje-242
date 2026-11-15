"""5 identity levels per character: python make_levels.py OUTDIR  (level 3 = the character, 1 mild ... 5 extreme)"""
import os, sys, subprocess, math, numpy as np, soundfile as sf
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
import voicelab as V
from make_samples import TEXT
from voicelab import NEU, K, LIM, ADD, level, B   # noqa: E402

if __name__ == "__main__":
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    raw = os.path.join(out, "raw.wav")
    subprocess.run(["/home/user/rhvoice/RHVoice/build/linux/test/RHVoice-test", "-o", raw], input=TEXT.encode(), check=True,
                   env=dict(os.environ, RHVOICE_DATA_PATH="/home/user/rhvoice/data"))
    x, sr = sf.read(raw); cache = V.analyse(x, sr)
    for i, (fn, (name, p)) in enumerate(B.items(), 1):
        for L, k in enumerate(K, 1):
            y = V.transform(x, level(p, k), sr, cache)
            sf.write(os.path.join(out, "%02d_%s_L%d.wav" % (i, fn, L)), y, sr)
    print("done")
