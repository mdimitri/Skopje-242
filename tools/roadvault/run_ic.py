"""Render the 400 interchange / ramp / merge types:  xvfb-run -a python run_ic.py OUT [shard nshards]   then  python run_ic.py OUT --mosaic
Writes OUT/<id>.jpg and OUT/specs/<id>.json (every parameter, ramp radius / grade / design-speed report, fit log)."""
import json, os, random, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
import interchanges as I

PLAN = [("diamond", 36), ("tight_diamond", 16), ("spui", 20), ("ddi", 20), ("rbt_ic", 20), ("clover", 28), ("parclo_a", 24), ("parclo_b", 24), ("trumpet", 24)]
MERGES = I.MERGE_KINDS
LIST = []
for fam, n in PLAN:
    LIST += [(fam, k) for k in range(1, n + 1)]
rest = 400 - len(LIST)
cnt = {k: 0 for k in MERGES}
for i in range(rest):
    k = MERGES[i % len(MERGES)]
    cnt[k] += 1
    LIST.append(("m_" + k, cnt[k]))
IDS = [f"IC{i + 1:03d}_{fam}_{k:02d}" for i, (fam, k) in enumerate(LIST)]


def spec_for(i):
    fam, k = LIST[i]
    rnd = random.Random(1000 * (i + 1) + 7)
    p = I.sample(fam, rnd)
    p["seed"] = i + 1
    if fam in ("clover", "parclo_a", "parclo_b"):
        p["kind"] = fam
    return fam, p


def main(out, shard, nsh):
    from render import Renderer, aerial
    import corridor as C
    os.makedirs(os.path.join(out, "specs"), exist_ok=True)
    r = Renderer()
    bad = []
    for i, cid in enumerate(IDS):
        if i % nsh != shard:
            continue
        t = time.time()
        try:
            fam, p = spec_for(i)
            pl = I.build_family(fam, p)
            m = C.build_plan(pl)
            fo = pl.info.get("focus")
            eye, tgt = aerial(dist=fo[2] if fo else I.DIST.get(fam, 330), az=215, el=40)
            if fo:
                eye = (eye[0] + fo[0], eye[1], eye[2] + fo[1])
                tgt = (fo[0], 0, fo[1])
            png = os.path.join(out, cid + ".png")
            r.shot(m, png, eye, tgt)
            Image.open(png).convert("RGB").save(os.path.join(out, cid + ".jpg"), quality=92)
            os.remove(png)
            json.dump(dict(id=cid, family=fam, params=p, fitted=pl.info.get("params"), fit_log=pl.info.get("fit_log"), ramps=pl.sim),
                      open(os.path.join(out, "specs", cid + ".json"), "w"), indent=1, default=str)
            print(f"{cid}: {len(m.P) // 3} tris {time.time() - t:.1f}s", flush=True)
        except Exception:
            bad.append(cid)
            traceback.print_exc()
    r.close()
    print("shard", shard, "bad", bad)


def mosaic(out, cols=10, tw=480, th=300, per=50):
    ids = [c for c in IDS if os.path.exists(os.path.join(out, c + ".jpg"))]
    font = ImageFont.load_default()
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 15)
    except Exception:
        pass
    for part in range(0, len(ids), per):
        sub = ids[part:part + per]
        rows = (len(sub) + cols - 1) // cols
        im = Image.new("RGB", (cols * tw, rows * th), (30, 32, 36))
        d = ImageDraw.Draw(im)
        for k, cid in enumerate(sub):
            t = Image.open(os.path.join(out, cid + ".jpg")).resize((tw - 4, th - 4), Image.LANCZOS)
            x, y = (k % cols) * tw + 2, (k // cols) * th + 2
            im.paste(t, (x, y))
            d.rectangle([x, y, x + tw - 4, y + 22], fill=(20, 22, 26))
            d.text((x + 6, y + 3), cid[:42], fill=(255, 255, 255), font=font)
        im.save(os.path.join(out, f"mosaic_{part // per + 1}.jpg"), quality=90)


if __name__ == "__main__":
    out = sys.argv[1]
    if "--mosaic" in sys.argv:
        mosaic(out)
    else:
        sh, ns = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 1)
        main(out, sh, ns)
