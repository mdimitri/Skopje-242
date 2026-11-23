"""Satellite vs the GAME's own road build:  xvfb-run -a python run_game.py IN_DIR OUT_DIR shard nshards DUMP.pkl
Panel = satellite | satellite + OSM | game top view (tools/roads3d.py + designer, north up, as sat_metric.py) | game oblique view
(road mesh + terrain + plain buildings, tools/road_shot.py).  DUMP = roads dump after roadclean.repair (see /tmp/roads_game.pkl recipe)."""
import glob, math, os, pickle, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, ".."), os.path.join(HERE, "..", "..", "src")]
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def font(n):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", n)
    except Exception:
        return ImageFont.load_default()


def main(inp, out, shard, nsh, dump_path):
    import sat_overlay as S, geo, sat_metric, road_shot
    dump = pickle.load(open(dump_path, "rb"))
    os.makedirs(out, exist_ok=True)
    fs = sorted(glob.glob(os.path.join(inp, "*.jpg")))
    for i, f in enumerate(fs):
        if i % nsh != shard:
            continue
        name = os.path.basename(f).split("_z19")[0].replace("id_", "")
        o = os.path.join(out, name + ".jpg")
        if os.path.exists(o):
            continue
        t = time.time()
        try:
            lat, lng, mpp = S.parse(os.path.basename(f))
            W = Image.open(f).size[0]
            wm = (mpp if mpp else 150.0 / W) * W
            x, y = geo.project(lat, lng)
            a, b, _ = S.overlay(f)
            ta = sat_metric.render_top(dump, x, y, wm).copy()
            ta[(ta[..., 0] > 240) & (ta[..., 1] < 20) & (ta[..., 2] > 240)] = (150, 172, 112)      # empty ground (no terrain in this view)
            top = Image.fromarray(ta)
            # oblique: look along the nearest drive edge's normal, from 28 deg up
            best, bd = None, 1e9
            for e in dump["edges"]:
                if not e["drive"]:
                    continue
                P = np.asarray(e["pts"], float)
                d = np.hypot(P[:, 0] - x, P[:, 1] - y)
                if d.min() < bd:
                    bd, best = d.min(), (P, int(d.argmin()))
            az = 180.0
            if best is not None:
                P, k = best
                v = P[min(k + 1, len(P) - 1)] - P[max(k - 1, 0)]
                az = (math.degrees(math.atan2(v[0], -v[1])) + 90.0) % 360.0       # bearing of the edge's normal
            tmp = f"/tmp/_gshot_{os.getpid()}"
            road_shot.render(dump, [dict(name="g", x=x, y=y, r=wm * 0.5, views=[[az, 28, wm * 0.9]], fov=40)], tmp, size=(900, 900))
            obl = Image.open(os.path.join(tmp, "g_0.png")).convert("RGB")
            tile = 700
            im = Image.new("RGB", (tile * 4, tile + 36), (24, 26, 30))
            for j, p in enumerate([a, b, top, obl]):
                im.paste(p.resize((tile, tile), Image.LANCZOS), (j * tile, 36))
            d = ImageDraw.Draw(im)
            d.text((8, 8), f"{name}   {lat:.5f}, {lng:.5f}   {wm:.0f} m wide", fill=(255, 255, 255), font=font(18))
            for j, lab in enumerate(["satellite", "satellite + OSM", "game build: top view", "game build: oblique (road mesh + terrain)"]):
                d.text((j * tile + tile - 8 - 9 * len(lab), 8), lab, fill=(180, 200, 255), font=font(15))
            im.save(o, quality=88)
            print(name, f"{time.time() - t:.1f}s", flush=True)
        except Exception:
            print("FAIL", name, flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
