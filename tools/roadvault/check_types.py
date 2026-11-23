"""Build (no render) a stratified sample of the 10,000 types and report failures / empty geometry."""
import json, os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import typelib
from engine import build

def one(t):
    try:
        sc = typelib.scene_of(t)
        m = build(sc)
        return (t["id"], len(m.P) // 3, None)
    except Exception:
        return (t["id"], 0, traceback.format_exc().splitlines()[-1])

if __name__ == "__main__":
    types = json.load(open(sys.argv[1]))
    n = int(sys.argv[2])
    rnd = random.Random(7)
    sample = rnd.sample(types, n)
    with Pool(4) as p:
        res = p.map(one, sample, chunksize=2)
    bad = [r for r in res if r[2] or r[1] < 2000]
    print("built", len(res), "bad", len(bad))
    from collections import Counter
    print(Counter(r[2] for r in bad).most_common(8))
    print([r[0] for r in bad][:20])
