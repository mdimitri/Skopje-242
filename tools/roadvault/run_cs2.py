"""CS2-style build from OSM vs satellite (reference only):  xvfb-run -a python run_cs2.py IN OUT shard nshards ; --sheets"""
import glob, os, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw
import run_sat


def main(inp, out, shard, nsh):
    import sat_overlay as S, cs2_build as B
    from render import Renderer
    os.makedirs(out, exist_ok=True)
    r = Renderer((900, 900))
    for i, f in enumerate(sorted(glob.glob(os.path.join(inp, "*.jpg")))):
        if i % nsh != shard:
            continue
        name = os.path.basename(f).split("_z19")[0].replace("id_", "")
        o = os.path.join(out, name + ".jpg")
        if os.path.exists(o):
            continue
        t = time.time()
        try:
            a, b, _ = S.overlay(f)
            top, obl, info = B.render_views(f, r)
            tile = 700
            im = Image.new("RGB", (tile * 4, tile + 36), (24, 26, 30))
            for j, p in enumerate([a, b, top, obl]):
                im.paste(p.resize((tile, tile), Image.LANCZOS), (j * tile, 36))
            d = ImageDraw.Draw(im)
            d.text((8, 8), f"{name}   {info['site'][0]:.5f}, {info['site'][1]:.5f}   {info['width_m']:.0f} m   roads {info['n_drive']}+{info['n_bridge']} bridges   junctions {info['n_junc']}   built from OSM only", fill=(255, 255, 255), font=run_sat.font(18))
            for j, lab in enumerate(["satellite (reference)", "satellite + OSM (reference)", "CS2-style from OSM: top", "CS2-style from OSM: oblique"]):
                d.text((j * tile + tile - 8 - 9 * len(lab), 8), lab, fill=(180, 200, 255), font=run_sat.font(15))
            im.save(o, quality=88)
            print(name, f"{time.time() - t:.1f}s", flush=True)
        except Exception:
            print("FAIL", name, flush=True)
            traceback.print_exc()
    r.close()


if __name__ == "__main__":
    if "--sheets" in sys.argv:
        run_sat.sheets(sys.argv[2])
    else:
        main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
