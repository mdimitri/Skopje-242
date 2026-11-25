"""Render a road candidate from the game's downloaded OSM inputs."""
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Polygon, box

from road_candidate import ROOT, compile_scene, road_edge, stroke

sys.path.insert(1, str(ROOT / "tools"))
from geo import project  # noqa: E402

HERE = Path(__file__).resolve().parent
DRIVE = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential",
         "unclassified", "service", "living_street"}
WALK = {"footway": 2.1, "path": 1.5, "steps": 1.6, "pedestrian": 3.2}
COLOURS = {"W-N": (247, 180, 87), "W-S": (247, 222, 120), "N-W": (118, 202, 164),
           "N-S": (106, 201, 240), "S-W": (231, 133, 173), "S-N": (185, 156, 245)}


def read_elements(path):
    return json.loads(path.read_text(encoding="utf-8"))["elements"]


def site_inputs(layout, osm, bounds):
    x0, y0 = project(*layout["origin"])

    def points(way):
        return [(x - x0, y - y0) for x, y in
                (project(p["lat"], p["lon"]) for p in way.get("geometry", []))]

    edges, walks, greens = [], [], []
    for way in read_elements(osm / "roads.json"):
        tags = way.get("tags", {})
        cls = tags.get("highway", "")
        if cls.removesuffix("_link") not in DRIVE and cls not in WALK:
            continue
        if any(tags.get(key, "no") != "no" for key in ("bridge", "tunnel")) or tags.get("layer", "0") != "0":
            continue
        xy = points(way)
        if len(xy) < 2:
            continue
        if not LineString(xy).intersects(bounds):
            continue
        if cls in WALK:
            if tags.get("footway") not in {"sidewalk", "crossing", "traffic_island"}:
                walks.append((LineString(xy), WALK[cls], cls))
        else:
            unique_xy = [point for i, point in enumerate(xy) if not i or point != xy[i - 1]]
            if len(unique_xy) >= 2:
                way_id = str(way["id"])
                edges.append(road_edge(way, unique_xy, layout.get("tapers", {}).get(way_id, ()),
                                       layout.get("left_lane_openings", {}).get(way_id)))
    for way in read_elements(osm / "areas.json"):
        tags = way.get("tags", {})
        if tags.get("landuse") != "grass" and tags.get("highway") != "traffic_island":
            continue
        xy = points(way)
        if len(xy) >= 4 and xy[0] == xy[-1]:
            polygon = Polygon(xy)
            if polygon.is_valid and polygon.intersects(bounds):
                greens.append(polygon)
    return edges, walks, greens


def render(mesh, routes, out):
    from render import Renderer

    renderer = Renderer((1500, 1200))
    try:
        top = dict(eye=(-1, 145, 5), tgt=(-1, 0, 5), up=(0, 0, -1), fov=146, orthographic=True)
        renderer.shot(mesh, str(out / "plan.png"), **top)
        renderer.shot(mesh, str(out / "oblique.png"), eye=(-67, 110, 83), tgt=(-1, 0, -6), fov=39)
        renderer.shot(mesh, str(out / "street-level.png"), eye=(8, 3.8, 43), tgt=(-1, 1.8, -12), fov=53)
        for spec, line in routes:
            colour = COLOURS.get(spec["id"][:3], (250, 199, 108))
            mesh.poly(stroke(line, 0.32), 0.18, colour, lit=False)
            p = np.array(line.interpolate(0.63, normalized=True).coords[0])
            front = np.array(line.interpolate(0.65, normalized=True).coords[0])
            direction = front - p
            direction /= math.hypot(*direction)
            right = np.array([-direction[1], direction[0]])
            mesh.poly(Polygon([p + direction, p - direction * 0.6 + right * 0.48,
                               p - direction * 0.6 - right * 0.48]), 0.185, colour, lit=False)
        path = out / "lane-movements.png"
        renderer.shot(mesh, str(path), **top)
    finally:
        renderer.close()
    if routes:
        with Image.open(path) as image:
            sheet = Image.new("RGB", (image.width, image.height + 60), (31, 37, 42))
            sheet.paste(image)
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=21)
        names = {"W": "West", "N": "North", "S": "South"}
        for i, (label, colour) in enumerate(COLOURS.items()):
            x = 39 + i * 244
            y = sheet.height - 30
            start, end = label.split("-")
            draw.line((x, y, x + 33, y), fill=colour, width=4)
            draw.text((x + 45, y), f"{names[start]} to {names[end]}", anchor="lm", font=font, fill=(237, 234, 225))
        sheet.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, default=HERE / "partizanski_glavinov.json")
    parser.add_argument("--osm", type=Path, default=ROOT / "data" / "osm")
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "road-candidate")
    parser.add_argument("--no-render", action="store_true", help="Export the compiled data without opening a graphics context")
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text(encoding="utf-8"))
    if layout["version"] != 1:
        parser.error("Unsupported layout version")
    radius = layout["radius"]
    bounds = box(-radius, -radius, radius, radius)
    edges, walks, greens = site_inputs(layout, args.osm, bounds)
    mesh, routes, conflicts, asphalt, furniture, pedestrian = compile_scene(edges, layout, walks, greens, bounds)
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / "mesh.npz", positions=np.array(mesh.P, dtype=np.float32),
                        colours=np.array(mesh.C, dtype=np.uint8))
    result = {
        "version": 1, "name": layout["name"], "origin_lat_lon": layout["origin"],
        "axes": "east, south (metres); mesh positions are east, up, south",
        "edges": [{"id": edge.id, "nodes": edge.nodes, "section": edge.section} for edge in edges],
        "movements": [{**spec, "path": list(line.coords), "length_m": round(line.length, 2)} for spec, line in routes],
        "potential_conflicts": conflicts,
        "pedestrian": pedestrian,
        "traffic_furniture": furniture,
        "asphalt_area_m2": round(asphalt.area, 2),
    }
    (args.out / "network.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not args.no_render:
        render(mesh, routes, args.out)
    print(f"{len(edges)} roads, {len(routes)} lane movements, {len(conflicts)} potential conflicts -> {args.out}")


if __name__ == "__main__":
    main()
