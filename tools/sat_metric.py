"""Compare the game-built road layout with a satellite screenshot, without any image segmentation.

    python3 tools/sat_metric.py roads_dump.pkl satellite.jpg lat lng width_m out_prefix [trace.json]

Writes out_prefix_cmp.png: the screenshot, the game render at the same position / scale (north up), and the OSM lanes
drawn over the screenshot.  The screenshot is only ever looked at, never classified.

Measured numbers come from a hand trace (trace.json) made by reading the screenshot: a list of
    {"kind": "road", "pts": [[px, py], ...], "lanes": n}      (px, py in screenshot pixels of the 800 px image)
Each traced road is compared with the nearest drivable graph edge: lateral offset (m) between the traced line and the
graph centreline, and lane count difference.  Reusable for any batch: write a trace per screenshot."""
import json
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "src")]


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


def osm_overlay(img, dump, x, y, width_m):
    """The screenshot with the graph's drivable edges drawn over it (width to scale, lane count at the midpoint)."""
    from PIL import ImageDraw
    im = img.copy()
    size = im.size[0]
    mpp = width_m / size
    dr = ImageDraw.Draw(im, "RGBA")
    for e in dump["edges"]:
        if not e["drive"] or len(e["pts"]) < 2:
            continue
        P = [(size / 2 + (px - x) / mpp, size / 2 + (py - y) / mpp) for px, py in e["pts"]]
        if not any(-40 < a < size + 40 and -40 < b < size + 40 for a, b in P):
            continue
        col = (60, 160, 255) if e["ow"] else (255, 60, 60)
        dr.line(P, fill=col + (70,), width=int(max(2, e["w"] / mpp)))
        dr.line(P, fill=col + (230,), width=2)
        m = P[len(P) // 2]
        dr.text((m[0] + 4, m[1] + 4), f"{e['lanes']}", fill=(255, 255, 0, 255))
    return im


def trace_report(dump, trace, x, y, width_m, size=800):
    """Compare hand-traced roads with the graph.  -> [{lat_off_m, lanes_traced, lanes_graph, cls}]"""
    from shapely.geometry import LineString, Point
    mpp = width_m / size
    lines = [(i, LineString(e["pts"])) for i, e in enumerate(dump["edges"]) if e["drive"] and len(e["pts"]) >= 2]
    out = []
    for t in trace:
        P = [(x + (px - size / 2) * mpp, y + (py - size / 2) * mpp) for px, py in t["pts"]]
        ln = LineString(P)
        best = None
        for i, g in lines:
            if g.distance(ln) > 40:
                continue
            d = np.mean([g.distance(Point(ln.interpolate(s, normalized=True))) for s in np.linspace(0, 1, 9)])
            if best is None or d < best[0]:
                best = (d, i)
        if best:
            e = dump["edges"][best[1]]
            per = e["lanes"] if e["ow"] else e["lanes"] / 2
            out.append({"offset_m": round(float(best[0]), 1), "lanes_traced": t.get("lanes"), "lanes_graph_per_dir_or_oneway": per,
                        "cls": e["cls"], "name": t.get("name", "")})
    return out


def main():
    from PIL import Image
    import geo
    dump = pickle.load(open(sys.argv[1], "rb"))
    img = Image.open(sys.argv[2]).convert("RGB").resize((800, 800))
    lat, lng, width, prefix = float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
    x, y = geo.project(lat, lng)
    gen = render_top(dump, x, y, width, 800)
    ov = osm_overlay(img, dump, x, y, width)
    Image.fromarray(np.concatenate([np.asarray(img), gen, np.asarray(ov)], 1)).save(prefix + "_cmp.png")
    if len(sys.argv) > 7:
        for r in trace_report(dump, json.load(open(sys.argv[7])), x, y, width):
            print(r)


if __name__ == "__main__":
    main()
