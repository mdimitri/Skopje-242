"""Render a road candidate from the game's downloaded OSM inputs."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box

if __package__:
    from .road_candidate import ROOT, compile_scene, road_edge, stroke
else:
    from road_candidate import ROOT, compile_scene, road_edge, stroke

if not __package__:
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


def site_inputs(layout, osm, bounds, road_elements=None, area_elements=None):
    x0, y0 = project(*layout["origin"])

    def points(way):
        return [(x - x0, y - y0) for x, y in
                (project(p["lat"], p["lon"]) for p in way.get("geometry", []))]

    edges, walks, greens = [], [], []
    for way in read_elements(osm / "roads.json") if road_elements is None else road_elements:
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
                edge = road_edge(way, unique_xy, layout.get("tapers", {}).get(way_id, ()),
                                 layout.get("left_lane_openings", {}).get(way_id))
                if taper := layout.get("lane_tapers", {}).get(way_id):
                    edge.section["lane_taper"] = taper
                edges.append(edge)
    areas = osm / "areas.json"
    if area_elements is None:
        area_elements = read_elements(areas) if road_elements is None or areas.exists() else []
    for way in area_elements:
        tags = way.get("tags", {})
        if tags.get("landuse") != "grass" and tags.get("highway") != "traffic_island":
            continue
        xy = points(way)
        if len(xy) >= 4 and xy[0] == xy[-1]:
            polygon = Polygon(xy)
            if polygon.is_valid and polygon.intersects(bounds):
                greens.append(polygon)
    return edges, walks, greens


def infer_site(layout, osm, bounds, replay=False):
    if __package__:
        from .road_inference import at_grade, infer_layout, normalize_ways
    else:
        from road_inference import at_grade, infer_layout, normalize_ways

    origin_x, origin_y = project(*layout["origin"])
    elements = read_elements(osm / "roads.json")
    relations = [element for element in elements if element.get("type") == "relation"]
    restrictions = osm / "restrictions.json"
    if restrictions.exists():
        relations.extend(read_elements(restrictions))
    relations = list({relation["id"]: relation for relation in relations if relation.get("type") == "relation"}.values())
    report = []
    if not relations and not restrictions.exists():
        report.append(dict(kind="no_relation_data", message="The extract supplies no turn restriction relations"))
    ways, walkways, crossing_guides, node_tags = {}, [], [], {}
    node_uses = Counter()

    def xy(lat, lon):
        x, y = project(lat, lon)
        return x - origin_x, y - origin_y

    for element in elements:
        tags = element.get("tags", {})
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            point = Point(xy(element["lat"], element["lon"]))
            if bounds.covers(point):
                node_tags[element["id"]] = {**tags, "point": point}
        if element.get("type") != "way":
            continue
        cls = tags.get("highway", "")
        if cls.removesuffix("_link") not in DRIVE and cls not in WALK:
            continue
        geometry = element.get("geometry") or []
        nodes = element.get("nodes") or []
        if len(geometry) < 2 or len(geometry) != len(nodes):
            report.append(dict(kind="invalid_way_geometry", way=element["id"]))
            continue
        line = LineString([xy(p["lat"], p["lon"]) for p in geometry])
        grade = at_grade(tags)
        if grade and cls not in WALK:
            node_uses.update(set(nodes))
        if not line.intersects(bounds):
            continue
        if not grade:
            report.append(dict(kind="grade_separated_way", way=element["id"]))
        elif cls in WALK:
            walkways.append(element)
            if tags.get("footway") == "crossing" and tags.get("crossing") not in {"unmarked", "no"}:
                crossing_guides.append(line)
        else:
            ways[element["id"]] = element
    shared = {node for node, count in node_uses.items() if count > 1}
    signals = osm / "signals.json"
    if not replay and signals.exists():
        mapped_signals = json.loads(signals.read_text(encoding="utf-8"))
        if isinstance(mapped_signals, list):
            for point in mapped_signals:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                signal = Point(point[0] - origin_x, point[1] - origin_y)
                if bounds.covers(signal) and not any(tags["point"].distance(signal) < 4
                                                    for tags in node_tags.values() if tags.get("highway") == "traffic_signals"):
                    report.append(dict(kind="signal_position_needs_layout", position=[signal.x, signal.y]))
    normalized, originals = normalize_ways(ways.values(), shared)
    edges, walks, greens = site_inputs(layout, osm, bounds, normalized + walkways)
    if replay:
        report = [item for item in layout.get("inference_diagnostics", [])
                  if item["kind"] not in {"gantry_location_needs_layout", "pole_location_needs_layout",
                                          "sidewalk_join_needs_layout", "sidewalk_join_would_reduce_lane_clearance"}]
    else:
        infer_layout(layout, edges, normalized, originals, node_tags, relations, crossing_guides, bounds, report)
    return edges, walks, greens, originals, report


def render(mesh, routes, out, inferred=False, radius=112):
    from PIL import Image, ImageDraw, ImageFont
    from render import Renderer

    turn_colors = {"left": (247, 180, 87), "through": (106, 201, 240), "right": (118, 202, 164)}
    renderer = Renderer((1500, 1200))
    try:
        top = dict(eye=(-1, 145, 5), tgt=(-1, 0, 5), up=(0, 0, -1), fov=146, orthographic=True)
        if inferred:
            top.update(eye=(0, max(180, radius), 0), tgt=(0, 0, 0), fov=radius * 1.55)
            renderer.shot(mesh, str(out / "oblique.png"), eye=(-0.64 * radius, 1.55 * radius, radius),
                          tgt=(0, 0, 0), fov=48)
        else:
            renderer.shot(mesh, str(out / "oblique.png"), eye=(-67, 110, 83), tgt=(-1, 0, -6), fov=39)
            renderer.shot(mesh, str(out / "street-level.png"), eye=(8, 3.8, 43), tgt=(-1, 1.8, -12), fov=53)
        renderer.shot(mesh, str(out / "plan.png"), **top)
        for spec, line in routes:
            if inferred:
                turn = spec["turn"]
                colour = next((value for key, value in turn_colors.items() if turn.endswith(key)), (250, 199, 108))
            else:
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
        colors = turn_colors if inferred else COLOURS
        for i, (label, colour) in enumerate(colors.items()):
            x = 39 + i * 244
            y = sheet.height - 30
            if inferred:
                caption = label.title()
            else:
                start, end = label.split("-")
                caption = f"{names[start]} to {names[end]}"
            draw.line((x, y, x + 33, y), fill=colour, width=4)
            draw.text((x + 45, y), caption, anchor="lm", font=font, fill=(237, 234, 225))
        sheet.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--layout", type=Path, help="Build an authored layout (default: Partizanski / Glavinov)")
    mode.add_argument("--infer", type=float, nargs=2, metavar=("LAT", "LON"), help="Infer an OSM layout around this point")
    parser.add_argument("--radius", type=float, default=112, help="Half-width in metres for inferred sites")
    parser.add_argument("--osm", type=Path, default=ROOT / "data" / "osm")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-render", action="store_true", help="Export the compiled data without opening a graphics context")
    args = parser.parse_args()
    if args.infer:
        lat, lon = args.infer
        if not (-90 <= lat <= 90 and -180 <= lon <= 180 and 10 <= args.radius <= 500):
            parser.error("Inference needs valid coordinates and a radius from 10 to 500 m")
        layout = dict(version=1, source="osm-topology", name=f"OSM candidate at {lat:.6f}, {lon:.6f}",
                      origin=args.infer, radius=args.radius)
    else:
        path = args.layout or HERE / "partizanski_glavinov.json"
        layout = json.loads(path.read_text(encoding="utf-8"))
    if layout["version"] != 1:
        parser.error("Unsupported layout version")
    radius = layout["radius"]
    bounds = box(-radius, -radius, radius, radius)
    inferred = layout.get("source") == "osm-topology"
    if inferred:
        edges, walks, greens, originals, report = infer_site(layout, args.osm, bounds, replay=not args.infer)
    else:
        edges, walks, greens = site_inputs(layout, args.osm, bounds)
        report = None
    if args.out is None:
        args.out = ROOT / "output" / ("road-candidate-inferred" if inferred else "road-candidate")
    mesh, routes, conflicts, asphalt, furniture, pedestrian = compile_scene(edges, layout, walks, greens, bounds, report)
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
    if inferred:
        for edge in result["edges"]:
            edge["osm_way"] = originals[edge["id"]]
        result["inference_diagnostics"] = report
        layout["inference_diagnostics"] = report
        (args.out / "layout.json").write_text(json.dumps(layout, indent=2) + "\n", encoding="utf-8")
    (args.out / "network.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if not args.no_render:
        render(mesh, routes, args.out, inferred=inferred, radius=radius)
    print(f"{len(edges)} roads, {len(routes)} lane movements, {len(conflicts)} potential conflicts -> {args.out}")


if __name__ == "__main__":
    main()
