"""Compare the game-built road layout with a satellite screenshot (reusable for any place).

    python3 tools/sat_metric.py <roads dump.pkl> <satellite.jpg> <lat> <lng> <width_m> <out prefix>

The screenshot is north-up with the place at its centre and `width_m` metres across.  The game's road mesh (roads3d with
the junction designer) is rendered top-down at the same position and scale; asphalt pixels of both are compared inside a
corridor around the drivable network (satellite roofs and fields outside it do not count).

Metrics (all printed and returned): iou, precision, recall of asphalt, chamfer = mean distance (m) from each generated
asphalt edge pixel to the nearest satellite asphalt edge pixel and back."""
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "src")]


def sat_asphalt(rgb):
    """Boolean mask of asphalt-looking pixels: grey, low saturation, mid brightness (cars, markings and shadows included
    by closing; vegetation and red roofs excluded)."""
    f = rgb.astype(np.float32)
    mx, mn = f.max(2), f.min(2)
    sat = (mx - mn) / np.maximum(mx, 1)
    return (sat < 0.16) & (mx > 40) & (mx < 175)


def render_top(dump, x, y, width_m, size=800):
    """Top-down render of the game road mesh -> RGB uint8 (size x size), north up."""
    import pyray as rl
    import road_shot
    rp, rc = road_shot.road_mesh(dump, x, y, width_m * 0.75)
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
    rl.init_window(size, size, "sat_metric")
    rt = rl.load_render_texture(size, size)
    rp, rc = road_shot.both_sides(rp, rc)
    models = road_shot.model(rp, rc)
    fov = 30.0
    dist = (width_m / 2) / math.tan(math.radians(fov / 2))
    g = float(dump["T"].hs(x, y))
    # north-up: the camera looks down with screen-up = -y (north)
    cam = rl.Camera3D((x, g + dist, y + 0.001), (x, g, y), (0, 0, -1), fov, rl.CAMERA_PERSPECTIVE)
    rl.begin_texture_mode(rt)
    rl.clear_background((255, 0, 255, 255))
    rl.rl_set_clip_planes(0.5, 4000.0)
    rl.begin_mode_3d(cam)
    for m in models:
        rl.draw_model(m, (0, 0, 0), 1.0, rl.WHITE)
    rl.end_mode_3d()
    rl.end_texture_mode()
    img = rl.load_image_from_texture(rt.texture)
    rl.image_flip_vertical(img)
    fn = f"/tmp/_sat_metric_{os.getpid()}.png"
    rl.export_image(img, fn)
    rl.unload_image(img)
    for m in models:
        rl.unload_model(m)
    rl.close_window()
    from PIL import Image
    return np.asarray(Image.open(fn).convert("RGB"))


def gen_asphalt(rgb):
    """Asphalt of the game render: dark neutral grey (paint and kerbs are lighter, grass green, pavement light grey)."""
    f = rgb.astype(np.float32)
    mx = f.max(2)
    sat = (mx - f.min(2)) / np.maximum(mx, 1)
    return (mx < 90) & (sat < 0.2) & ~((f[:, :, 0] > 200) & (f[:, :, 2] > 200))


def _edges(m):
    from scipy import ndimage
    return m & ~ndimage.binary_erosion(m)


def compare(sat_rgb, gen_rgb, corridor, mpp):
    """sat_rgb, gen_rgb: (n, n, 3); corridor: boolean mask of where roads are expected (from the OSM network)."""
    from scipy import ndimage
    s = ndimage.binary_closing(sat_asphalt(sat_rgb), iterations=3)
    s = ndimage.binary_opening(s, iterations=2)
    g = ndimage.binary_closing(gen_asphalt(gen_rgb), iterations=1)
    s, g = s & corridor, g & corridor
    inter, union = (s & g).sum(), (s | g).sum()
    out = {"iou": inter / max(1, union), "precision": inter / max(1, g.sum()), "recall": inter / max(1, s.sum())}
    es, eg = _edges(s), _edges(g)
    if es.any() and eg.any():
        ds, dg = ndimage.distance_transform_edt(~es), ndimage.distance_transform_edt(~eg)
        out["chamfer_m"] = float((dg[es].mean() + ds[eg].mean()) / 2 * mpp)
    return out, s, g


def corridor_mask(dump, x, y, width_m, size, margin=14.0):
    from PIL import Image, ImageDraw
    mpp = width_m / size
    im = Image.new("L", (size, size), 0)
    dr = ImageDraw.Draw(im)
    for e in dump["edges"]:
        if not e["drive"] or len(e["pts"]) < 2:
            continue
        P = [(size / 2 + (px - x) / mpp, size / 2 + (py - y) / mpp) for px, py in e["pts"]]
        dr.line(P, fill=255, width=int(max(2, (e["w"] + 2 * margin) / mpp)))
    return np.asarray(im) > 0


def main():
    from PIL import Image
    import geo
    dump = pickle.load(open(sys.argv[1], "rb"))
    img = Image.open(sys.argv[2]).convert("RGB")
    lat, lng, width, prefix = float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
    size = 800
    img = img.resize((size, size))
    x, y = geo.project(lat, lng)
    gen = render_top(dump, x, y, width, size)
    cor = corridor_mask(dump, x, y, width, size)
    res, s, g = compare(np.asarray(img), gen, cor, width / size)
    vis = np.zeros((size, size, 3), np.uint8)
    vis[s & g] = (255, 255, 255)
    vis[s & ~g] = (255, 60, 60)          # satellite asphalt the game lacks
    vis[g & ~s] = (60, 140, 255)         # game asphalt the satellite lacks
    row = np.concatenate([np.asarray(img), gen, vis], 1)
    Image.fromarray(row).save(prefix + "_cmp.png")
    print({k: round(float(v), 3) for k, v in res.items()})
    from scipy import ndimage
    sm = ndimage.binary_opening(ndimage.binary_closing(sat_asphalt(np.asarray(img)), iterations=3), iterations=2)
    for r in width_ratios(dump, sm, x, y, width, size):
        print("width", r[0], "ow" if r[1] else "tw", "graph %.1f sat %.1f" % (r[2], r[3]))



def width_ratios(dump, sat_mask, x, y, width_m, size, step=12.0):
    """Per drivable edge: asphalt width seen in the satellite mask across the centreline (metres) vs the edge's width in
    the graph.  -> [(class, one_way, graph_width, sat_width)] (samples where the centre pixel is asphalt)."""
    mpp = width_m / size
    out = []
    for e in dump["edges"]:
        if not e["drive"] or len(e["pts"]) < 2 or e["bridge"]:
            continue
        P = np.asarray(e["pts"], float)
        cum = np.r_[0, np.cumsum(np.hypot(*np.diff(P, axis=0).T))]
        ws = []
        for s in np.arange(step, cum[-1] - step, step):
            px, py = np.interp(s, cum, P[:, 0]), np.interp(s, cum, P[:, 1])
            tx, ty = np.interp(s + 2, cum, P[:, 0]) - px, np.interp(s + 2, cum, P[:, 1]) - py
            l = math.hypot(tx, ty) or 1.0
            nx, ny = -ty / l, tx / l
            def at(o):
                i = int(round(size / 2 + (px + nx * o - x) / mpp))
                j = int(round(size / 2 + (py + ny * o - y) / mpp))
                return 0 <= i < size and 0 <= j < size and sat_mask[j, i]
            if not at(0.0):
                continue
            lo = hi = 0.0
            while lo > -30 and at(lo - 0.3):
                lo -= 0.3
            while hi < 30 and at(hi + 0.3):
                hi += 0.3
            ws.append(hi - lo)
        if ws:
            out.append((e["cls"], bool(e["ow"]), float(e["w"]), float(np.median(ws))))
    return out


if __name__ == "__main__":
    main()
