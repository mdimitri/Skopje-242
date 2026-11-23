"""CS2 build from OSM + bounded satellite fit measured only inside the OSM road bands.
xvfb-run -a python run_fit.py IN OUT shard nshards ; python run_fit.py x OUT --sheets
Panel: satellite | satellite+OSM | CS2 top (fitted) | error heatmap (inside OSM bands) | CS2 oblique."""
import glob, json, os, sys, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image, ImageDraw
import run_sat

TILE = 700


def one(f, r, B, F, S):
    a, b, _ = S.overlay(f)
    W = a.size[0]
    lat, lng, mpp = S.parse(os.path.basename(f))
    s_img = mpp if mpp else 150.0 / W
    top0, _, info0 = B.render_views(f, r, want_obl=False)
    drive0 = info0["drive"]
    meas, (ref, tol) = F.measure(f, drive0, s_img)
    fit, log = {}, []
    for e in drive0:
        k = B.road_key(e["r"])
        if k is None or id(e) not in meas:
            continue
        mm = meas[id(e)]
        lg = F.legal(mm, e, e["sp"]["lw"])
        log.append(dict(key=[str(x) for x in k], cls=e["r"]["cls"], osm_n=e["sp"]["n"], osm_w=round(e["sp"]["w"], 2),
                        meas={q: (round(v, 2) if isinstance(v, float) else v) for q, v in mm.items()},
                        fit=lg))
        if lg:
            fit[k] = lg
    top1, obl1, info1 = B.render_views(f, r, fit=fit)
    N = top1.size[0]
    sat = a.resize((N, N), Image.LANCZOS)
    s_ren = info1["width_m"] / N
    M = F.band_mask(drive0, s_ren, N) | F.band_mask(info1["drive"], s_ren, N)
    m0, _, _, _ = F.metrics(sat, top0, M, ref, tol)
    m1, err, la, lb = F.metrics(sat, top1, M, ref, tol)
    hm = F.heat(sat, err, M, la, lb, s_ren)
    for mm in (m0, m1):
        mm["kerb_m"] = mm.pop("kerb_px") * s_ren
    import numpy as np
    res0 = [abs(x["osm_w"] - x["meas"]["w"]) for x in log if "w" in x["meas"]]
    res1 = [abs((x["fit"]["n"] * x["fit"]["lw"] if x["fit"] else x["osm_w"]) - x["meas"]["w"]) for x in log if "w" in x["meas"]]
    m0["wres_m"] = float(np.median(res0)) if res0 else float("nan")
    m1["wres_m"] = float(np.median(res1)) if res1 else float("nan")
    return a, b, top1, hm, obl1, info1, m0, m1, log, (ref, tol)


def main(inp, out, shard, nsh):
    import sat_overlay as S, cs2_build as B, bandfit as F
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
            a, b, top, hm, obl, info, m0, m1, log, (ref, tol) = one(f, r, B, F, S)
            im = Image.new("RGB", (TILE * 5, TILE + 36), (24, 26, 30))
            for j, p in enumerate([a, b, top, hm, obl]):
                im.paste(p.resize((TILE, TILE), Image.LANCZOS), (j * TILE, 36))
            d = ImageDraw.Draw(im)
            nf = sum(1 for x in log if x["fit"])
            d.text((8, 8), f"{name}   {info['width_m']:.0f} m   roads {info['n_drive']}   junctions {info['n_junc']}   fitted {nf}/{len(log)} ways   "
                   f"in OSM bands (before->after fit): SSIM {m0['ssim']:.3f}->{m1['ssim']:.3f}  PSNR {m0['psnr']:.1f}->{m1['psnr']:.1f} dB  kerb dist {m0['kerb_m']:.2f}->{m1['kerb_m']:.2f} m  "
                   f"edge orient {m0['orient']:.3f}->{m1['orient']:.3f}  width resid {m0['wres_m']:.2f}->{m1['wres_m']:.2f} m   "
                   f"asphalt ref RGB {int(ref[0])},{int(ref[1])},{int(ref[2])}", fill=(255, 255, 255), font=run_sat.font(17))
            for j, lab in enumerate(["satellite (reference)", "satellite + OSM", "CS2 from OSM, fitted widths", "error in OSM bands: tint 1-SSIM; satellite kerbs green<0.5m red>2m off ours (white)", "CS2 oblique"]):
                d.text((j * TILE + 8, 40), lab, fill=(255, 255, 160), font=run_sat.font(15))
            im.save(o, quality=88)
            with open(os.path.join(out, "fitlog.jsonl"), "a") as fh:
                fh.write(json.dumps(dict(site=name, before=m0, after=m1, ways=log)) + "\n")
            print(name, f"{time.time() - t:.1f}s", "SSIM %.3f->%.3f kerb %.2f->%.2f orient %.3f->%.3f wres %.2f->%.2f fitted %d/%d" % (m0["ssim"], m1["ssim"], m0["kerb_m"], m1["kerb_m"], m0["orient"], m1["orient"], m0["wres_m"], m1["wres_m"], nf, len(log)), flush=True)
        except Exception:
            print("FAIL", name, flush=True)
            traceback.print_exc()
    r.close()


def sheets(out, per=6):
    fs = sorted(f for f in glob.glob(os.path.join(out, "*.jpg")) if not os.path.basename(f).startswith("sheet_"))
    rh = int(2400 * (TILE + 36) / (TILE * 5))
    for k in range(0, len(fs), per):
        sub = fs[k:k + per]
        sh = Image.new("RGB", (2400, rh * len(sub)))
        for j, f in enumerate(sub):
            sh.paste(Image.open(f).resize((2400, rh), Image.LANCZOS), (0, j * rh))
        sh.save(os.path.join(out, f"sheet_{k // per + 1:02d}.jpg"), quality=86)


if __name__ == "__main__":
    if "--sheets" in sys.argv:
        sheets(sys.argv[2])
    else:
        main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
