"""Overlay the OSM road network (game dump roads_raw.pkl) on a satellite screenshot named ..._lat_<lat>_lng_<lng>_z19_w_150m_... or ..._mpp_<m/px>_...
Image is north-up and centred on the lat/lng; scale = 150 m / width, or the stated metres per pixel."""
import math, os, pickle, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from PIL import Image, ImageDraw

import geo  # noqa: E402

COL = {"motorway": (230, 60, 60), "trunk": (230, 100, 50), "primary": (240, 150, 40), "secondary": (240, 200, 50), "tertiary": (250, 235, 120),
       "residential": (255, 255, 255), "service": (200, 200, 255), "motorway_link": (230, 90, 90), "trunk_link": (230, 120, 80), "primary_link": (240, 170, 80),
       "secondary_link": (240, 210, 90), "tertiary_link": (250, 240, 150), "footway": (90, 220, 255), "cycleway": (90, 255, 170), "path": (90, 220, 255), "steps": (90, 220, 255)}
_D = {}


def roads():
    if "r" not in _D:
        d = pickle.load(open(os.environ.get("ROADS_PKL", "/mnt/project-files/road-restyle-cs2/data/roads_raw.pkl"), "rb"))
        _D["r"] = d["roads"]
    return _D["r"]


def parse(name):
    m = re.search(r"lat_(\d+)_(\d+)_lng_(\d+)_(\d+)_", name)
    lat = float(f"{m.group(1)}.{m.group(2)}")
    lng = float(f"{m.group(3)}.{m.group(4)}")
    mp = re.search(r"mpp_([0-9.]+)", name)
    return lat, lng, (float(mp.group(1)) if mp else None)


def overlay(path, out=None, alpha=0.9):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    lat, lng, mpp = parse(os.path.basename(path))
    s = mpp if mpp else 150.0 / W
    cx, cy = geo.project(lat, lng)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    half = max(W, H) * s * 0.75
    for r in roads():
        pts = r["pts"]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) < cx - half or min(xs) > cx + half or max(ys) < cy - half or min(ys) > cy + half:
            continue
        px = [((x - cx) / s + W / 2, (y - cy) / s + H / 2) for x, y in pts]
        c = COL.get(r["cls"], (255, 255, 255))
        wpx = max(2, int(r["w"] / s))
        if r.get("bridge") or r.get("layer", 0) > 0:
            d.line(px, fill=(170, 60, 255, 170), width=wpx + 4, joint="curve")
        d.line(px, fill=c + (int(255 * 0.45),), width=wpx, joint="curve")
        d.line(px, fill=(20, 20, 20, 255), width=1)
    res = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
    if out:
        res.save(out, quality=92)
    return im, res, (cx, cy, s)


if __name__ == "__main__":
    overlay(sys.argv[1], sys.argv[2])
