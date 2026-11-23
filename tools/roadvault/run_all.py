"""Render the catalogue:  xvfb-run -a python tools/roadvault/run_all.py OUT_DIR [id-prefix ...]
Writes OUT/<id>.jpg (aerial view), OUT/specs/<id>.json (every tunable value) and OUT/mosaic_*.jpg."""
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import catalog  # noqa: E402
from render import Renderer, aerial  # noqa: E402


def main(out, prefixes):
    os.makedirs(os.path.join(out, "specs"), exist_ok=True)
    r = Renderer()
    ok, bad = [], []
    for cid in catalog.IDS:
        if prefixes and not any(cid.startswith(p) for p in prefixes):
            continue
        t = time.time()
        try:
            sc = catalog.make(cid)
            m = __import__("engine").build(sc)
            dist = {'S': 85, 'T': 105, 'X': 110, 'M': 115, 'R': 105, 'G': 150, 'L': 100, 'H': 105}[cid[0]]
            eye, tgt = aerial(dist=dist, az=215, el=38)
            png = os.path.join(out, cid + ".png")
            r.shot(m, png, eye, tgt)
            Image.open(png).convert("RGB").save(os.path.join(out, cid + ".jpg"), quality=92)
            os.remove(png)
            json.dump(catalog.spec(sc), open(os.path.join(out, "specs", cid + ".json"), "w"), indent=1, default=str)
            ok.append(cid)
            print(f"{cid}: {len(m.P) // 3} tris {time.time() - t:.1f}s", flush=True)
        except Exception:  # noqa: BLE001
            bad.append(cid)
            traceback.print_exc()
    r.close()
    print("ok", len(ok), "bad", bad)


def mosaic(out, cols=10, tw=480, th=300, per=50):
    ids = [i for i in catalog.IDS if os.path.exists(os.path.join(out, i + ".jpg"))]
    font = ImageFont.load_default()
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 15)
    except Exception:  # noqa: BLE001
        pass
    for part in range(0, len(ids), per):
        sub = ids[part:part + per]
        rows = (len(sub) + cols - 1) // cols
        im = Image.new("RGB", (cols * tw, rows * th), (30, 32, 36))
        for k, cid in enumerate(sub):
            t = Image.open(os.path.join(out, cid + ".jpg")).resize((tw - 4, th - 4), Image.LANCZOS)
            x, y = (k % cols) * tw + 2, (k // cols) * th + 2
            im.paste(t, (x, y))
            d = ImageDraw.Draw(im)
            d.rectangle([x, y, x + tw - 4, y + 22], fill=(20, 22, 26))
            d.text((x + 6, y + 3), f"{part + k + 1:03d} {cid[:34]}", fill=(255, 255, 255), font=font)
        im.save(os.path.join(out, f"mosaic_{part // per + 1}.jpg"), quality=90)


if __name__ == "__main__":
    out = sys.argv[1]
    if "--mosaic" in sys.argv:
        mosaic(out)
    else:
        main(out, sys.argv[2:])
