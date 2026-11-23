"""Element gallery: every element on a standard test avenue.  xvfb-run -a python tools/roadvault/gallery.py OUT [prefix...]"""
import math
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import elements  # noqa: E402
from engine import Arm, Scene, build  # noqa: E402
from render import Renderer  # noqa: E402


def test_scene(eid, cat):
    kw = dict(lin=2, lout=2, median="none", zebra=None, trees=False, lamps=False, traffic=0.0)
    arms = [Arm(180, **kw), Arm(0, **kw)]
    return Scene("el_" + eid, arms, cars=False, context=False, sky_extent=90, elements=[{"id": eid, "arm": 1}])


def main(out, prefixes):
    os.makedirs(out, exist_ok=True)
    r = Renderer((960, 600))
    bad = []
    for eid, row in elements.EL.items():
        if prefixes and not any(eid.startswith(p) for p in prefixes):
            continue
        try:
            sc = test_scene(eid, row["cat"])
            m = build(sc)
            ln = row["lay"]
            pointy = row["cat"] in ("posts", "furniture", "signs", "lighting", "planting", "utilities", "transit", "pedestrian")
            a1 = sc.arms[1]
            d_t = 4.0 + (ln["d0"] + 3.0 if pointy and ln["d1"] > 1.5 else (ln["d0"] + ln["d1"]) / 2)
            if ln["d1"] <= 1.5:
                d_t = 4.0 + ln["d0"]
            tx, tz = d_t, (-4.5 if pointy and ln["side"] <= 0 else (4.5 if pointy else 0.0))
            dist, el = ({'posts': 5.5, 'furniture': 8.0, 'signs': 6.5, 'utilities': 10.0, 'lighting': 22.0, 'planting': 13.0, 'transit': 16.0, 'pedestrian': 16.0}.get(row['cat'], 15.0), 24.0) if pointy else (40.0, 34.0)
            if row["cat"] in ("gantries",) or row["gen"] in ("footbridge",):
                dist, tz = 36.0, 0.0
            az = math.radians(150 if (tz <= 0) else 30)
            eye = (tx + math.sin(az) * math.cos(math.radians(el)) * dist, math.sin(math.radians(el)) * dist, tz - math.cos(az) * math.cos(math.radians(el)) * dist)
            png = os.path.join(out, eid + ".png")
            r.shot(m, png, eye, (tx, {'lighting': 3.5, 'signs': 1.9, 'posts': 0.6}.get(row['cat'], 0.9), tz), fov=38.0)
            Image.open(png).convert("RGB").save(os.path.join(out, eid + ".jpg"), quality=90)
            os.remove(png)
        except Exception:  # noqa: BLE001
            bad.append(eid)
            traceback.print_exc()
    r.close()
    print("bad:", bad)


def sheet(out, cols=8, tw=400, th=250, per=64):
    ids = [i for i in elements.EL if os.path.exists(os.path.join(out, i + ".jpg"))]
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 13)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    for part in range(0, len(ids), per):
        sub = ids[part:part + per]
        rows = (len(sub) + cols - 1) // cols
        im = Image.new("RGB", (cols * tw, rows * th), (30, 32, 36))
        for k, eid in enumerate(sub):
            t = Image.open(os.path.join(out, eid + ".jpg")).resize((tw - 4, th - 4), Image.LANCZOS)
            x, y = (k % cols) * tw + 2, (k // cols) * th + 2
            im.paste(t, (x, y))
            d = ImageDraw.Draw(im)
            d.rectangle([x, y, x + tw - 4, y + 19], fill=(20, 22, 26))
            d.text((x + 5, y + 3), eid[:44], fill=(255, 255, 255), font=font)
        im.save(os.path.join(out, f"elements_sheet_{part // per + 1}.jpg"), quality=88)


if __name__ == "__main__":
    if "--sheet" in sys.argv:
        sheet(sys.argv[1])
    else:
        main(sys.argv[1], sys.argv[2:])
