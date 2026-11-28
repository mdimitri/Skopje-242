"""A small square of the map around the centre, for quick builds: `build_world.py --tile 1000` builds 1 x 1 km.

Cuts the downloaded data (OSM elements, side lists, terrain grid) to the box into a folder of its own, which the build
then reads like any other --src.  tools/geo.py takes the box size from SK242_TILE (build_world sets it)."""
import glob
import json
import os

import numpy as np

import terrain
from geo import HX, HY, project

EDGE = 60.0                          # elements this far outside still belong (as in the download of the full box)


def _hits(pts):
    if not pts:
        return False
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) >= -HX - EDGE and min(xs) <= HX + EDGE and max(ys) >= -HY - EDGE and min(ys) <= HY + EDGE


def _points(element):
    if element.get("type") == "node":
        return [project(element["lat"], element["lon"])] if "lat" in element else []
    found = list(element.get("geometry") or [])
    for member in element.get("members") or []:
        found += member.get("geometry") or []
        if "lat" in member:
            found.append(member)
    return [project(p["lat"], p["lon"]) for p in found if p]


def _inside(x, y):
    return abs(x) < HX and abs(y) < HY


def _cut(name, data):
    if isinstance(data, dict) and "elements" in data:
        return dict(data, elements=[e for e in data["elements"] if _hits(_points(e))])
    if name in ("bus_stops.json", "map_pois.json", "signals.json"):
        return [row for row in data if _inside(row[0], row[1])]
    if name == "rail.json":
        return [row for row in data if (_hits(row[4]) if row[0] == "way" else _inside(row[2], row[3]))]
    if name == "transit.json":
        return [r for r in data if any(_hits([project(p["lat"], p["lon"]) for p in way]) for way in r["ways"])]
    return data


def crop(src, out):
    """Write the cut copy of `src` to `out` (files that are already newer than their source are kept) -> out."""
    os.makedirs(out, exist_ok=True)
    for path in glob.glob(os.path.join(src, "*.json")) + [os.path.join(src, "terrain.npy")]:
        name = os.path.basename(path)
        dest = os.path.join(out, name)
        if not os.path.exists(path) or (os.path.exists(dest) and os.path.getmtime(dest) >= os.path.getmtime(path)):
            continue
        if name == "terrain.npy":
            grid = np.load(path)
            ny, nx = terrain.grid_shape(HX, HY)
            y0, x0 = (grid.shape[0] - ny) // 2, (grid.shape[1] - nx) // 2
            np.save(dest, grid[y0:y0 + ny, x0:x0 + nx])
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(_cut(name, data), f, ensure_ascii=False)
    return out
