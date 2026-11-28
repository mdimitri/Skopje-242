"""Bake the reviewed road-vault compiler into terrain-relative game tiles."""
import json
import math
import zlib
from collections import Counter
from pathlib import Path
from PIL import Image, ImageDraw

from shapely import STRtree
from shapely.affinity import translate
from shapely.geometry import LineString, Point, Polygon, box
from shapely.errors import GEOSException
from shapely.ops import substring, unary_union

from geo import project
from roadwidth import lane_count
from roadvault.mesh import Mesh, polys
from roadvault.road_candidate import Edge, compile_scene, crossing_span, road_edge
from roadvault.road_inference import at_grade, infer_layout, normalize_ways, road_arms, lane_transition_profiles, align_slip_forks
from roadvault.run_candidate import DRIVE, WALK, infer_site, read_elements, site_inputs
from roadvault.traffic_furniture import draw_device, draw_gantry

GLAVINOV = Path(__file__).with_name("roadvault") / "partizanski_glavinov.json"
REVIEWED_RADIUS = 88
MARGIN = 90
REFERENCE_SITES = ((41.99815, 21.42544, 95), (42.00547, 21.4169, 93),
                   (42.0038599, 21.3902603, 115), (42.0004324, 21.4270569, 115))


def osm_sections(elements):
    """Read the same ground-road sections consumed by the candidate builder."""
    sections, raw_ways, node_uses = {}, [], Counter()
    for way in elements:
        tags = way.get("tags", {})
        cls = tags.get("highway", "")
        if way.get("type") != "way" or cls.removesuffix("_link") not in DRIVE or not at_grade(tags):
            continue
        tags = dict(tags)
        if cls == "motorway" and "oneway" not in tags:
            tags["oneway"] = "yes"
        if tags.get("junction") == "roundabout" and tags.get("oneway") in {"no", "0", "false"}:
            tags.pop("junction")
        sections[way["id"]] = road_edge({"id": way["id"], "tags": tags, "nodes": [0, 1]},
                                        [(0, 0), (1, 0)]).section
        geometry, nodes = way.get("geometry", ()), way.get("nodes", ())
        if len(geometry) >= 2 and len(geometry) == len(nodes):
            raw_ways.append({**way, "tags": tags})
            node_uses.update(set(nodes))
    return sections, raw_ways, node_uses


def sync_graph_sections(edges, roads, elements):
    """Use the same OSM cross-sections for ground traffic and candidate asphalt."""
    sections, raw_ways, node_uses = osm_sections(elements)
    normalized, originals = normalize_ways(raw_ways, {n for n, count in node_uses.items() if count > 1})
    candidates, tags_by_edge = [], {}
    for way in normalized:
        points = _points(way)
        points = [point for i, point in enumerate(points) if not i or point != points[i - 1]]
        if len(points) < 2:
            continue
        item = road_edge(way, points)
        candidates.append(item)
        tags_by_edge[item.id] = way["tags"]
    arms = road_arms(candidates)
    profiles = lane_transition_profiles(arms, tags_by_edge, box(-1e9, -1e9, 1e9, 1e9), {})
    align_slip_forks(arms)
    by_way = {}
    for item in candidates:
        by_way.setdefault(originals[item.id], []).append(item)
    count = 0
    for edge in edges:
        if not edge["drive"] or edge["bridge"]:
            continue
        section = sections.get(roads[edge["road"]]["id"])
        if section is None or bool(section["ow"]) != bool(edge["ow"]):
            continue
        for key in ("w", "lanes", "directional_lanes"):
            edge[key] = section[key]
        first, last = Point(edge["pts"][0]), Point(edge["pts"][-1])
        choices = by_way.get(roads[edge["road"]]["id"], ())
        matches = [(item.line.distance(first) + item.line.distance(last), item) for item in choices]
        if matches:
            error, item = min(matches, key=lambda pair: pair[0])
            start, finish = item.line.project(first), item.line.project(last)
            if error < 3 and finish > start and edge["len"] > 0 and item.section.get("fork_shifts"):
                edge["candidate_shifts"] = (start, (finish - start) / edge["len"], item.line.length, item.section["fork_shifts"])
            if error < 0.4 and finish > start + 0.5:
                part = substring(item.line, start, finish)
                points = list(part.coords)
                points[0], points[-1] = edge["pts"][0], edge["pts"][-1]
                cum = [0.0]
                for a, b in zip(points, points[1:]):
                    cum.append(cum[-1] + math.dist(a, b))
                edge["pts"], edge["cum"], edge["len"] = points, cum, cum[-1]
            if item.id in profiles and error < 3 and finish > start and edge["len"] > 0:
                end, length, side = profiles[item.id]
                distance = start if end == "start" else item.line.length - finish
                if distance < length:
                    amount = item.section["tapers"][-1][2]
                    edge["candidate_taper"] = (end, length, start, (finish - start) / edge["len"], item.line.length, amount)
                    edge["taper"] = (None, None)
                    edge["lane_taper"] = (end, length, side)
        count += 1
    return count


def _optional_elements(path):
    try:
        return read_elements(path)
    except FileNotFoundError:
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[road candidate] skipped {path.name}: {exc}", flush=True)
        return []


class TileMesh(Mesh):
    def __init__(self, bounds):
        super().__init__()
        self.bounds = bounds

    def poly(self, shape, y, col, lit=True):
        for part in polys(shape):
            clipped = part.intersection(self.bounds)
            super().poly(clipped, y, col, lit)
            if hasattr(self, "surface") and y in (0, 0.125, 0.145, 0.155):
                height = round((y + 0.06) * 100)
                ox, oy = self.surface_origin
                def pixels(ring):
                    return [(int((x - ox) * 2), int((z - oy) * 2)) for x, z in ring.coords]
                for polygon in polys(clipped):
                    outer = pixels(polygon.exterior)
                    x0, y0 = map(min, zip(*outer))
                    x1, y1 = map(max, zip(*outer))
                    mask = Image.new("1", (x1 - x0 + 1, y1 - y0 + 1))
                    draw = ImageDraw.Draw(mask)
                    draw.polygon([(x - x0, z - y0) for x, z in outer], fill=1)
                    for hole in polygon.interiors:
                        draw.polygon([(x - x0, z - y0) for x, z in pixels(hole)], fill=0)
                    self.surface.paste(height, (x0, y0, x1 + 1, y1 + 1), mask)

    def wall_ring(self, coords, y0, y1, col):
        cut = LineString(coords).intersection(self.bounds)
        for part in getattr(cut, "geoms", (cut,)):
            if part.geom_type == "LineString":
                super().wall_ring(part.coords, y0, y1, col)


class Source:
    def __init__(self, src, road_ids, node_ids):
        osm = Path(src)
        raw = _optional_elements(osm / "roads.json")
        areas = _optional_elements(osm / "areas.json")
        self.road_ids = road_ids
        self.node_ids = node_ids
        self.tags = {e["id"]: e.get("tags", {}) for e in raw if e.get("type") == "way"}
        self.relations = list({e["id"]: e for e in [*raw, *_optional_elements(osm / "restrictions.json")]
                               if e.get("type") == "relation" and e.get("tags", {}).get("type") == "restriction"}.values())
        self.features = []
        road_ways = []
        node_uses = Counter()
        for element in raw:
            tags = element.get("tags", {})
            cls = tags.get("highway", "")
            geometry, nodes = element.get("geometry") or [], element.get("nodes") or []
            if (element.get("type") == "way" and cls.removesuffix("_link") in DRIVE
                    and at_grade(tags) and len(geometry) >= 2 and len(geometry) == len(nodes)):
                road_ways.append(element)
                node_uses.update(set(nodes))
        normalized, self.originals = normalize_ways(road_ways, {n for n, count in node_uses.items() if count > 1})
        for way in normalized:
            xy = _points(way)
            if len(set(xy)) >= 2:
                self.features.append(("road", way, LineString(xy)))
        for e in raw:
            tags = e.get("tags", {})
            hw = tags.get("highway")
            if (e.get("type") == "way" and hw in WALK and at_grade(tags)
                    and tags.get("footway") not in {"sidewalk", "crossing", "traffic_island"}
                    and len(e.get("geometry", ())) >= 2):
                self.features.append(("walk", (WALK[hw], hw), LineString(_points(e))))
            if (e.get("type") == "node" and hw in {"crossing", "traffic_signals", "stop", "give_way"}
                    and "lat" in e and "lon" in e):
                self.features.append(("node", (e["id"], tags), Point(project(e["lat"], e["lon"]))))
            if (e.get("type") == "way" and tags.get("footway") == "crossing"
                    and tags.get("crossing") not in {"unmarked", "no"} and len(e.get("geometry", ())) >= 2):
                self.features.append(("crossing", None, LineString(_points(e))))
        for e in areas:
            tags = e.get("tags", {})
            if tags.get("landuse") == "grass" or tags.get("highway") == "traffic_island":
                xy = _points(e)
                if len(xy) >= 4 and xy[0] == xy[-1] and (poly := Polygon(xy)).is_valid:
                    self.features.append(("green", None, poly))
        signal_path = osm / "signals.json"
        try:
            with signal_path.open(encoding="utf-8") as stream:
                signals = json.load(stream)
        except (OSError, ValueError):
            signals = []
        if isinstance(signals, list):
            for point in signals:
                if isinstance(point, list) and len(point) == 2:
                    self.features.append(("signal", None, Point(point)))
        self.index = STRtree([shape for _, _, shape in self.features])
        # The reviewed junction windows: only their descriptions here, each is compiled once by its own job (build_site).
        self.osm = osm
        self.sites = []
        if raw:
            for lat, lon, radius in REFERENCE_SITES:
                ox, oy = project(lat, lon)
                window = box(ox - radius, oy - radius, ox + radius, oy + radius)
                self.sites.append(dict(kind="reference", origin=(lat, lon), radius=radius,
                                       core=window.buffer(-5, join_style="mitre")))
        layout = json.loads(GLAVINOV.read_text(encoding="utf-8"))
        if all(way in self.tags for spec in layout["movements"] for way in (spec["from"], *spec["via"], spec["to"])):
            ox, oy = project(*layout["origin"])
            self.sites.append(dict(kind="reviewed", origin=layout["origin"], radius=layout["radius"],
                                   core=box(ox - REVIEWED_RADIUS, oy - REVIEWED_RADIUS, ox + REVIEWED_RADIUS, oy + REVIEWED_RADIUS)))


def _points(element):
    return [project(p["lat"], p["lon"]) for p in element.get("geometry", ())]


def _furniture_sink(mesh, graph, offset, controls, owns, junction=None):
    def emit(devices, edges, layout, asphalt):
        ox, oy = offset
        furniture = Mesh()
        stations = dict(item for group in layout["crossings"] for item in group)
        bindings = {}
        for way in layout["stop_lines"]:
            line = edges[way].line
            stop = line.interpolate(stations[way] - 3.4)
            choices = graph.get(way, ())
            if not choices:
                continue
            target = translate(stop, ox, oy)
            ei, edge, path = min(choices, key=lambda item: item[2].distance(target))
            end = edge["pts"][-1]
            node = junction or ("candidate", edge["b"])
            bindings[way] = (node, ei)
            if owns(stop):
                controls["signals"].append((node, ei, 1, ei, float("nan"), float("nan"),
                                            *end, 0, max(0, edge["len"] - path.project(target))))
        for way, station in stations.items():
            center, heading, right, lo, hi = crossing_span(edges[way], station, asphalt)
            center = center + right * ((lo + hi) / 2)
            if owns(Point(center)):
                node = (junction or bindings.get(way, (None, None))[0]) if way in layout.get("pedestrian_signals", ()) else None
                controls["crossings"].append((float(center[0] + ox), float(center[1] + oy),
                                              *map(float, heading), float(hi - lo), 0, 0.0, node))
        for device in devices:
            kind, way = device["kind"], device["way"]
            points = device.get("heads") if kind == "vehicle_gantry" else None
            position = points[0]["position"] if points else device["position"]
            if not owns(Point(position)):
                continue
            if kind == "vehicle_gantry":
                draw_gantry(furniture, device, live=True)
            else:
                draw_device(furniture, kind, position, device["facing"], live=True)
            facing = tuple(device["facing"])
            if kind == "pedestrian_signal":
                node = junction or bindings.get(way, (None, None))[0]
                if node is not None:
                    controls["heads"].append((node, None, position[0] + ox, position[1] + oy, 2.20, *facing))
            elif kind in {"vehicle_gantry", "vehicle_signal"} and way in bindings:
                node, ei = bindings[way]
                height = device.get("clearance_m", 2.78)
                for head in points or [{"position": position}]:
                    x, y = head["position"]
                    controls["heads"].append((node, ei, x + ox, y + oy, height, *facing))
        mesh.P.extend(furniture.P)
        mesh.C.extend(furniture.C)
    return emit


def _graph_records(edges, edge_ids, source):
    """OSM way -> [(edge index, graph edge, its line)] for the one-way edges that signals can bind to."""
    records = {}
    for i, edge in zip(edge_ids, edges):
        foot = edge.get("flat") and any(isinstance(n, tuple) and n[:1] == ("foot",) for n in (edge["a"], edge["b"]))
        if edge["drive"] and edge["ow"] and not edge["bridge"] and not foot and len(edge["pts"]) >= 2 and isinstance(edge["b"], int):
            records.setdefault(source.road_ids[edge["road"]], []).append((i, edge, LineString(edge["pts"])))
    return records


def build_site(source, index, edges, edge_ids):
    """Compile one reviewed junction window -> (mesh in site coordinates, (ox, oy)), or None when it does not fit this
    OSM extract (the road tiles then pave it themselves).  mesh.surface is a half-metre height map whose first pixel is
    mesh.surface_pixel on the global half-metre grid."""
    site = source.sites[index]
    ox, oy = project(*site["origin"])
    radius = site["radius"]
    bounds = box(-radius, -radius, radius, radius)
    originals = report = None
    try:
        if site["kind"] == "reference":
            layout = {"origin": site["origin"], "source": "osm-topology"}
            site_edges, walks, greens, originals, report = infer_site(layout, source.osm, bounds)
            if not site_edges:
                return None
        else:
            layout = json.loads(GLAVINOV.read_text(encoding="utf-8"))
            site_edges, walks, greens = site_inputs(layout, source.osm, bounds, _optional_elements(source.osm / "roads.json"),
                                                    _optional_elements(source.osm / "areas.json"))
        mesh = TileMesh(translate(site["core"], -ox, -oy))
        mesh.controls = {"signals": [], "heads": [], "crossings": []}
        x0, y0, x1, y1 = site["core"].bounds
        px, py = math.floor(x0 * 2), math.floor(y0 * 2)
        mesh.surface = Image.new("L", (math.ceil(x1 * 2) - px + 1, math.ceil(y1 * 2) - py + 1))
        mesh.surface_origin = (px / 2 - ox, py / 2 - oy)
        mesh.surface_pixel = (px, py)
        graph = _graph_records(edges, edge_ids, source)
        bindings = ({way: graph.get(osm_way, ()) for way, osm_way in originals.items()} if originals is not None else graph)
        junction = ("candidate", "glavinov") if originals is None else None
        sink = _furniture_sink(mesh, bindings, (ox, oy), mesh.controls, lambda p: mesh.bounds.covers(p), junction)
        compile_scene(site_edges, layout, walks, greens, bounds, None if report is None else list(report),
                      mesh=mesh, preview=False, furniture_sink=sink)
    except (KeyError, ValueError, GEOSException) as exc:
        print(f"[road candidate] {site['kind']} layout at {site['origin']} skipped: {exc}", flush=True)
        return None
    return mesh, (ox, oy)


def build_tile(source, edges, tx, ty, radius, edge_ids=None, skip_sites=()):
    tile = box(-radius, -radius, radius, radius)
    bounds = tile.buffer(MARGIN, join_style="mitre")
    node_tags, guides, greens, walks, signals, raw_ways = {}, [], [], [], [], []
    for i in sorted(source.index.query(translate(bounds, tx, ty), predicate="intersects")):
        kind, data, shape = source.features[i]
        local = translate(shape, -tx, -ty)
        if kind == "node":
            node_id, tags = data
            node_tags[node_id] = {**tags, "point": local}
        elif kind == "crossing":
            guides.append(local)
        elif kind == "signal":
            signals.append(local)
        elif kind == "road":
            raw_ways.append((data, local))
        elif kind == "walk":
            walks.append((local, *data))
        else:
            greens.append(local)

    candidates, ways, originals, cooked, reviewed_graph = [], [], {}, {}, {}
    for i, edge in enumerate(edges, 1):
        if edge["bridge"] or len(edge["pts"]) < 2 or not math.isfinite(edge["w"]) or edge["w"] <= 0:
            continue
        line = LineString([(x - tx, y - ty) for x, y in edge["pts"]])
        if not line.length or not line.intersects(bounds):
            continue
        way = source.road_ids[edge["road"]]
        tags = source.tags.get(way, {}).copy()
        if not edge["drive"]:
            continue
        if edge.get("flat") and any(isinstance(n, tuple) and n[:1] == ("foot",) for n in (edge["a"], edge["b"])):
            # These grounded bridge tails were removed from the raised deck. Keep their
            # cooked geometry, but use OSM node IDs to join the original ground roads.
            key = 10**15 + i
            nodes = tuple(-10**15 - 2 * n[1] - n[2] if isinstance(n, tuple) and n[:1] == ("foot",)
                          else source.node_ids.get(n, n) for n in (edge["a"], edge["b"]))
            section = dict(edge)
            section["lanes"] = lane_count(edge, 1) + (0 if edge["ow"] else lane_count(edge, -1))
            candidates.append(Edge(key, nodes, line, section))
            ways.append({"id": key, "nodes": nodes, "tags": tags})
            originals[key] = way
            continue
        if edge_ids is not None and isinstance(edge["b"], int) and edge["ow"]:
            record = (edge_ids[i - 1], edge, translate(line, tx, ty))
            reviewed_graph.setdefault(way, []).append(record)
        if edge["ow"]:
            end = Point(line.coords[-1])
            if any(end.distance(signal) <= 35 and line.distance(signal) <= 3 for signal in signals):
                node = source.node_ids.get(edge["b"])
                if node is not None:
                    node_tags[node] = {"highway": "traffic_signals", "point": end}

    bridge_ways = {source.road_ids[edge["road"]] for edge in edges if edge["bridge"]}
    for way, line in raw_ways:
        if source.originals[way["id"]] in bridge_ways:
            continue
        xy = [point for i, point in enumerate(line.coords) if not i or point != line.coords[i - 1]]
        if len(xy) < 2:
            continue
        edge = road_edge(way, xy)
        candidates.append(edge)
        ways.append(way)
        originals[edge.id] = source.originals[edge.id]
        cooked[edge.id] = reviewed_graph.get(originals[edge.id], ())

    # the reviewed windows are paved by their own jobs
    covered = unary_union([translate(site["core"], -tx, -ty).intersection(tile)
                           for i, site in enumerate(source.sites) if i not in skip_sites])
    mesh = TileMesh(tile.difference(covered))
    mesh.controls = {"signals": [], "heads": [], "crossings": []}
    size = round(radius * 4)
    mesh.surface = Image.new("L", (size, size))
    mesh.surface_origin = (-radius, -radius)

    def owns(point, x=0, y=0):
        return -radius <= point.x + x < radius and -radius <= point.y + y < radius

    if candidates:
        layout, report = {}, []
        infer_layout(layout, candidates, ways, originals, node_tags, source.relations, guides, bounds, report)
        sink = _furniture_sink(mesh, cooked, (tx, ty), mesh.controls,
                               lambda p: owns(p) and not covered.covers(p))
        compile_scene(candidates, layout, walks, greens, bounds, report, mesh=mesh, preview=False, furniture_sink=sink)
    mesh.controls["surface_tiles"] = [((math.floor(tx / (2 * radius)), math.floor(ty / (2 * radius))),
                                       zlib.compress(mesh.surface.tobytes(), 1))]
    return mesh
