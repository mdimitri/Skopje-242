"""Bake the reviewed road-vault compiler into terrain-relative game tiles."""
import json
from pathlib import Path

from shapely import STRtree
from shapely.affinity import translate
from shapely.geometry import LineString, Point, box
from shapely.errors import GEOSException
from shapely.ops import unary_union

from geo import project
from roadvault.mesh import Mesh
from roadvault.road_candidate import Edge, compile_scene, crossing_span, lane_count
from roadvault.road_inference import infer_layout
from roadvault.run_candidate import WALK, infer_site, read_elements, site_inputs
from roadvault.traffic_furniture import draw_device, draw_gantry

GLAVINOV = Path(__file__).with_name("roadvault") / "partizanski_glavinov.json"
REVIEWED_RADIUS = 88
MARGIN = 90
REFERENCE_SITES = ((41.99815, 21.42544, 95), (42.00547, 21.4169, 93))


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
        super().poly(shape.intersection(self.bounds), y, col, lit)

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
        self.way_nodes = {e["id"]: set(e.get("nodes", ())) for e in raw if e.get("type") == "way"}
        self.relations = list({e["id"]: e for e in [*raw, *_optional_elements(osm / "restrictions.json")]
                               if e.get("type") == "relation" and e.get("tags", {}).get("type") == "restriction"}.values())
        self.features = []
        for e in raw:
            tags = e.get("tags", {})
            hw = tags.get("highway")
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
        if signal_path.is_file():
            with signal_path.open(encoding="utf-8") as stream:
                signals = json.load(stream)
            for point in signals:
                if isinstance(point, list) and len(point) == 2:
                    self.features.append(("signal", None, Point(point)))
        self.index = STRtree([shape for _, _, shape in self.features])
        self.references = []
        if raw:
            for lat, lon, radius in REFERENCE_SITES:
                ox, oy = project(lat, lon)
                window = box(ox - radius, oy - radius, ox + radius, oy + radius)
                if not any(window.intersects(shape) for kind, _, shape in self.features if kind in {"node", "crossing"}):
                    continue
                layout = {"origin": (lat, lon), "source": "osm-topology"}
                bounds = box(-radius, -radius, radius, radius)
                try:
                    edges, walks, greens, originals, report = infer_site(layout, osm, bounds)
                    if not layout["crossings"]:
                        continue
                    compile_scene(edges, layout, walks, greens, bounds, report, preview=False)
                except (KeyError, ValueError, GEOSException) as exc:
                    print(f"[road candidate] reference at {lat}, {lon} skipped: {exc}", flush=True)
                    continue
                core = window.buffer(-5, join_style="mitre")
                self.references.append((core, ox, oy, bounds, edges, layout, walks, greens, originals, report))

        self.reviewed = None
        layout = json.loads(GLAVINOV.read_text(encoding="utf-8"))
        if not all(way in self.tags for spec in layout["movements"] for way in (spec["from"], *spec["via"], spec["to"])):
            return
        ox, oy = project(*layout["origin"])
        radius = layout["radius"]
        bounds = box(-radius, -radius, radius, radius)
        core = box(ox - REVIEWED_RADIUS, oy - REVIEWED_RADIUS, ox + REVIEWED_RADIUS, oy + REVIEWED_RADIUS)
        try:
            edges, walks, greens = site_inputs(layout, osm, bounds, raw, areas)
            # Validate the complete reviewed layout once before replacing any inferred tiles.
            compile_scene(edges, layout, walks, greens, bounds, preview=False)
        except (KeyError, ValueError, GEOSException) as exc:
            print(f"[road candidate] reviewed Glavinov layout does not fit this OSM extract: {exc}", flush=True)
        else:
            self.reviewed = (core, ox, oy, bounds, edges, layout, walks, greens)


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


def build_tile(source, edges, tx, ty, radius, edge_ids=None):
    tile = box(-radius, -radius, radius, radius)
    bounds = tile.buffer(MARGIN, join_style="mitre")
    node_tags, guides, greens, walks, signals = {}, [], [], [], []
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
        else:
            greens.append(local)

    candidates, ways, originals, cooked, reviewed_graph = [], [], {}, {}, {}
    crossing_nodes = [(key, tags["point"]) for key, tags in node_tags.items() if tags["highway"] == "crossing"]
    for i, edge in enumerate(edges, 1):
        if edge["bridge"] or len(edge["pts"]) < 2:
            continue
        line = LineString([(x - tx, y - ty) for x, y in edge["pts"]])
        if not line.intersects(bounds):
            continue
        way = source.road_ids[edge["road"]]
        tags = source.tags.get(way, {}).copy()
        if not edge["drive"]:
            if edge["cls"] in WALK and tags.get("footway") not in {"sidewalk", "crossing", "traffic_island"}:
                walks.append((line, WALK[edge["cls"]], edge["cls"]))
            continue
        nodes = [source.node_ids.get(node, -10**15 - node) if isinstance(node, int)
                 else -10**16 - node[1] * 2 - node[2] for node in (edge["a"], edge["b"])]
        mapped_nodes = source.way_nodes.get(way, ())
        interior = [key for key, point in crossing_nodes
                    if key in mapped_nodes and key not in nodes and line.distance(point) < 0.85]
        section = {key: edge[key] for key in ("cls", "ow", "w", "turn", "directional_lanes")}
        section["lanes"] = lane_count(edge) + (0 if edge["ow"] else lane_count(edge, -1))
        tags["highway"] = edge["cls"]
        if tags.get("oneway") == "-1" and tags.get("sidewalk") in {"left", "right"}:
            tags["sidewalk"] = {"left": "right", "right": "left"}[tags["sidewalk"]]
        candidates.append(Edge(i, (nodes[0], *interior, nodes[1]), line, section))
        ways.append({"id": i, "tags": tags})
        originals[i] = way
        if edge_ids is not None and isinstance(edge["b"], int) and edge["ow"]:
            record = (edge_ids[i - 1], edge, translate(line, tx, ty))
            cooked[i] = [record]
            reviewed_graph.setdefault(way, []).append(record)
        if edge["ow"]:
            end = Point(line.coords[-1])
            if any(end.distance(signal) <= 35 and line.distance(signal) <= 3 for signal in signals):
                node_tags[nodes[1]] = {"highway": "traffic_signals", "point": end}

    sites = list(source.references)
    if source.reviewed:
        sites.append((*source.reviewed, None, None))
    patches = [(translate(site[0], -tx, -ty).intersection(tile), site) for site in sites]
    covered = unary_union([patch for patch, _ in patches])
    mesh = TileMesh(tile.difference(covered))
    mesh.controls = {"signals": [], "heads": [], "crossings": []}

    def owns(point, x=0, y=0):
        return -radius <= point.x + x < radius and -radius <= point.y + y < radius

    if candidates:
        layout, report = {}, []
        infer_layout(layout, candidates, ways, originals, node_tags, source.relations, guides, bounds, report)
        sink = _furniture_sink(mesh, cooked, (tx, ty), mesh.controls,
                               lambda p: owns(p) and not covered.covers(p))
        compile_scene(candidates, layout, walks, greens, bounds, report, mesh=mesh, preview=False, furniture_sink=sink)
    for patch, site in patches:
        if patch.is_empty:
            continue
        _, ox, oy, review_bounds, review_edges, layout, review_walks, review_greens, originals, report = site
        reviewed_mesh = TileMesh(translate(patch, tx - ox, ty - oy))
        bindings = ({way: reviewed_graph.get(osm_way, ()) for way, osm_way in originals.items()}
                    if originals is not None else reviewed_graph)
        junction = ("candidate", "glavinov") if originals is None else None
        sink = _furniture_sink(reviewed_mesh, bindings, (ox, oy), mesh.controls,
                               lambda p: owns(p, ox - tx, oy - ty) and reviewed_mesh.bounds.covers(p), junction)
        compile_scene(review_edges, layout, review_walks, review_greens, review_bounds,
                      None if report is None else list(report),
                      mesh=reviewed_mesh, preview=False, furniture_sink=sink)
        for point in reviewed_mesh.P:
            point[0] += ox - tx
            point[2] += oy - ty
        mesh.P.extend(reviewed_mesh.P)
        mesh.C.extend(reviewed_mesh.C)
    return mesh
