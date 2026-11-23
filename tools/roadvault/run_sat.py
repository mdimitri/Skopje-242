"""Panels for satellite screenshots:  xvfb-run -a python run_sat.py IN_DIR OUT_DIR shard nshards  then  python run_sat.py IN_DIR OUT_DIR --sheets
Panel = satellite | satellite + OSM overlay | top view of the OSM through the vault engine | side view across the main road."""
import glob, json, os, sys, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont


def font(n):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", n)
    except Exception:
        return ImageFont.load_default()


def panel(f, r, S, O, tile=560):
    a, b, _ = S.overlay(f)
    t0, _s0, _p0 = O.render_views(f, r)
    t, sd, pl = O.render_views(f, r, fitted=True)
    name = os.path.basename(f).split("_z19")[0].replace("id_", "")
    im = Image.new("RGB", (tile * 5, tile + 36), (24, 26, 30))
    for i, x in enumerate([a, b, t0, t, sd]):
        im.paste(x.resize((tile, tile), Image.LANCZOS), (i * tile, 36))
    d = ImageDraw.Draw(im)
    lat, lng = pl.info["site"]
    fl = pl.info["fit_log"]
    d.text((8, 8), f"{name}   {lat:.5f}, {lng:.5f}   {pl.info['width_m']:.0f} m wide   {pl.info['n_roads']} roads   fit rules fired: {len(fl)}", fill=(255, 255, 255), font=font(18))
    for i, lab in enumerate(["satellite", "satellite + OSM", "top: raw OSM", "top: fitted", "side: fitted"]):
        d.text((i * tile + tile - 8 - 10 * len(lab), 8), lab, fill=(180, 200, 255), font=font(15))
    with open(os.path.join(os.path.dirname(f) if False else OUTDIR[0], "fitlog.jsonl"), "a") as fh:
        fh.write(json.dumps(dict(site=name, log=fl)) + "\n")
    return im


OUTDIR = [""]


def main(inp, out, shard, nsh):
    import sat_overlay as S, osm_render as O
    from render import Renderer
    os.makedirs(out, exist_ok=True)
    OUTDIR[0] = out
    r = Renderer((900, 900))
    fs = sorted(glob.glob(os.path.join(inp, "*.jpg")))
    for i, f in enumerate(fs):
        if i % nsh != shard:
            continue
        o = os.path.join(out, os.path.basename(f).split("_z19")[0].replace("id_", "") + ".jpg")
        if os.path.exists(o):
            continue
        t = time.time()
        try:
            panel(f, r, S, O).save(o, quality=88)
            print(os.path.basename(o), f"{time.time() - t:.1f}s", flush=True)
        except Exception:
            traceback.print_exc()
    r.close()


def sheets(out, per=6):
    fs = sorted(glob.glob(os.path.join(out, "*.jpg")))
    fs = [f for f in fs if not os.path.basename(f).startswith("sheet_")]
    for k in range(0, len(fs), per):
        sub = fs[k:k + per]
        sh = Image.new("RGB", (2000, 536 * len(sub)))
        for j, f in enumerate(sub):
            sh.paste(Image.open(f).resize((2000, 536), Image.LANCZOS), (0, j * 536))
        sh.save(os.path.join(out, f"sheet_{k // per + 1:02d}.jpg"), quality=86)


if __name__ == "__main__":
    inp, out = sys.argv[1], sys.argv[2]
    if "--sheets" in sys.argv:
        sheets(out)
    else:
        main(inp, out, int(sys.argv[3]), int(sys.argv[4]))
