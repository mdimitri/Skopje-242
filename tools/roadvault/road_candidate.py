"""Compile a local at-grade road graph into a mesh and a lane-movement graph."""
from dataclasses import dataclass
from itertools import combinations
import math
from pathlib import Path
import sys

import numpy as np
from shapely import STRtree, make_valid
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.geometry.polygon import orient
from shapely.ops import substring, unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src"))
from roadwidth import lane_bounds, lane_count, lane_turns  # noqa: E402

from mesh import Mesh, polys
from traffic_furniture import GANTRY_CLEARANCE, draw_device, draw_gantry

LANE_WIDTH = 3.25
PAINT = (236, 233, 216)


def unit(vector):
    return vector / np.linalg.norm(vector)


def frame(line, station):
    p = np.array(line.interpolate(station).coords[0])
    a = np.array(line.interpolate(max(0, station - 0.45)).coords[0])
    b = np.array(line.interpolate(min(line.length, station + 0.45)).coords[0])
    heading = unit(b - a)
    return p, heading, np.array([-heading[1], heading[0]])


def cubic(a, b, c, d):
    t = np.linspace(0, 1, max(9, math.ceil(np.linalg.norm(d - a) * 2) + 1))[:, None]
    u = 1 - t
    return u**3 * a + 3 * u**2 * t * b + 3 * u * t**2 * c + t**3 * d


def spline(points):
    """Round mapped bends without moving the endpoints or losing the control points."""
    points = np.asarray(points, dtype=float)
    segments = np.diff(points, axis=0)
    lengths = np.linalg.norm(segments, axis=1)
    directions = segments / lengths[:, None]
    tangents = [directions[0]]
    for a, b in zip(directions, directions[1:]):
        average = a + b
        tangents.append(unit(average) if np.linalg.norm(average) > 1e-6 else b)
    tangents.append(directions[-1])
    return LineString(np.concatenate([
        cubic(a, a + ta * (length / 3), b - tb * (length / 3), b)[:-1]
        for a, b, ta, tb, length in zip(points, points[1:], tangents, tangents[1:], lengths)
    ] + [points[-1:]]))


def positive_int(value):
    return int(value) if value and value.isdecimal() and int(value) > 0 else 0


@dataclass
class Edge:
    id: int
    nodes: tuple
    line: LineString
    section: dict

    def cross_section(self, station):
        """Hold the section at a split or merge, then blend it over the taper distance."""
        offsets = np.array([-0.5, 0.5]) * self.section["w"]
        for end, length, left, right, *hold in self.section.get("tapers", []):
            distance = station if end == "start" else self.line.length - station
            distance = max(0, distance - (hold[0] if hold else 0))
            t = max(0, 1 - distance / length)
            offsets += np.array([left, right]) * t * t * (3 - 2 * t)
        if opening := self.section.get("left_lane_opening"):
            lane_width = self.section["w"] / self.section["lanes"]
            t = min(1, station / opening)
            offsets += np.array([lane_width * (1 - t * t * (3 - 2 * t)), 0]) - lane_width / 2
        return offsets

    def trace(self, fraction, stations, extra=0.0, lane_aligned=False):
        points = []
        for station in stations:
            p, _, right = frame(self.line, station)
            left_edge, right_edge = self.cross_section(station)
            offset = left_edge + fraction * (right_edge - left_edge)
            if lane_aligned and self.section.get("left_lane_opening"):
                lanes = self.section["lanes"]
                width = self.section["w"]
                divider = right_edge - width * (1 - 1 / lanes)
                offset = (left_edge + (divider - left_edge) * fraction * lanes if fraction < 1 / lanes
                          else right_edge - width * (1 - fraction))
            if lane_aligned and (taper := self.section.get("lane_taper")):
                _, _, side = taper
                lanes = self.section["lanes"]
                width = self.section["w"]
                if side == "left":
                    divider = right_edge - width * (1 - 1 / lanes)
                    offset = (left_edge + (divider - left_edge) * fraction * lanes if fraction < 1 / lanes
                              else right_edge - width * (1 - fraction))
                else:
                    divider = left_edge + width * (1 - 1 / lanes)
                    offset = (left_edge + width * fraction if fraction <= 1 - 1 / lanes
                              else right_edge - (right_edge - divider) * (1 - fraction) * lanes)
            points.append(p + right * (offset + extra))
        return LineString(points)

    def lane_fraction(self, lane, direction):
        lo, hi = lane_bounds(self.section, direction)
        nominal = lo + (lane + 0.5) * (hi - lo) / lane_count(self.section, direction)
        return 0.5 + nominal * direction / self.section["w"]

    def port(self, station, lane, direction):
        before, p, after = self.trace(self.lane_fraction(lane, direction), [
            max(0, station - 0.25), station, min(self.line.length, station + 0.25)
        ], lane_aligned=True).coords
        return np.array(p), unit(np.subtract(after, before)) * direction


def road_edge(way, points, tapers=(), left_lane=None):
    tags = way["tags"]
    reverse = tags.get("oneway") == "-1"
    oneway = reverse or tags.get("oneway") in {"yes", "1", "true"} or tags.get("junction") == "roundabout"
    forward, backward = (positive_int(tags.get("lanes:" + d)) for d in ("forward", "backward"))
    cls = tags["highway"]
    count = positive_int(tags.get("lanes"))
    if not oneway:
        count = max(2, count, forward + 1, backward + 1)
        forward = forward or (count - backward if backward else (count + 1) // 2)
        backward = backward or count - forward
        count = forward + backward
    else:
        count = (backward if reverse else forward) or count or 1
    raw_width = tags.get("width:carriageway", tags.get("width", "")).strip().lower()
    try:
        width = float(raw_width.removesuffix("m").strip().replace(",", "."))
    except ValueError:
        width = 0
    turns = tuple(tags.get("turn:lanes:" + d, "") for d in ("forward", "backward"))
    if reverse:
        points = points[::-1]
        turns = turns[::-1]
    if oneway:
        turns = (turns[0] or tags.get("turn:lanes", ""), "")
    default_width = 4.2 if cls == "service" and not tags.get("lanes") and not oneway else count * LANE_WIDTH
    section = dict(cls=cls, ow=oneway, lanes=count, directional_lanes=None if oneway else (forward, backward),
                   w=width if math.isfinite(width) and width > 0 else default_width, turn=turns)
    if tapers:
        section["tapers"] = tapers
    if left_lane:
        section["left_lane_opening"] = left_lane["length"]
        section["w"] += section["w"] / section["lanes"]
        section["lanes"] += 1
        section["turn"] = (left_lane["turns"], "")
    nodes = tuple(way["nodes"][::-1] if reverse else way["nodes"])
    return Edge(way["id"], nodes, spline(points), section)


def movement_ports(edges, spec):
    source, target = (edges[spec[key]] for key in ("from", "to"))
    via = [edges[edge_id] for edge_id in spec["via"]]
    directions = (spec.get("from_direction", 1), spec.get("to_direction", 1))
    for edge, direction, lane in zip((source, target), directions, (spec["from_lane"], spec["to_lane"])):
        if direction not in (1, -1) or (direction == -1 and edge.section["ow"]):
            raise ValueError(f"Wrong-way movement {spec['id']} on OSM way {edge.id}")
        if not 0 <= lane < lane_count(edge.section, direction):
            raise ValueError(f"Invalid lane in movement {spec['id']} on OSM way {edge.id}")
    turns = lane_turns(source.section, directions[0])
    if "turn" in spec and turns and turns[spec["from_lane"]] and spec["turn"] not in turns[spec["from_lane"]]:
        raise ValueError(f"Movement {spec['id']} conflicts with OSM turn lane markings")
    src_end = directions[0] == 1
    dst_start = directions[1] == 1
    exit_node = source.nodes[-1 if src_end else 0]
    for edge in via:
        if edge.nodes[0] != exit_node:
            raise ValueError(f"Disconnected movement {spec['id']} at OSM way {edge.id}")
        exit_node = edge.nodes[-1]
    if exit_node != target.nodes[0 if dst_start else -1]:
        raise ValueError(f"Disconnected movement {spec['id']} at OSM way {target.id}")

    lead, tail = (min(spec["setback"], edge.line.length * 0.45) for edge in (source, target))
    a, da = source.port(source.line.length - lead if src_end else lead, spec["from_lane"], directions[0])
    d, dd = target.port(tail if dst_start else target.line.length - tail, spec["to_lane"], directions[1])
    return a, da, d, dd


def source_approach(source, spec):
    direction = spec.get("from_direction", 1)
    setback = min(spec["setback"], source.line.length * 0.45)
    split = source.line.length if direction == 1 else 0
    stations = np.linspace(split - direction * setback, split, math.ceil(setback * 2) + 1)
    lane = spec["from_lane"]
    points = list(source.trace(source.lane_fraction(lane, direction), stations, lane_aligned=True).coords)
    mouth, heading = source.port(split, lane, direction)
    return points, mouth, heading


def smooth_connector(line, fixed_start, passes=5, blend_length=2.5):
    """Ease local curvature changes while pinning the approach and merge anchors."""
    count = math.ceil(line.length / 0.35)
    stations = np.linspace(0, line.length, count + 1)
    points = np.array([line.interpolate(station).coords[0] for station in stations])
    # Symmetric filtering in arclength keeps the guide shape and blends across splices.
    weights = np.array([1, 6, 15, 20, 15, 6, 1]) / 64
    pad = len(weights) // 2
    t = np.clip(np.minimum(stations - fixed_start, line.length - stations) / blend_length, 0, 1)
    blend = t * t * (3 - 2 * t)
    for _ in range(passes):
        window = np.pad(points, ((pad, pad), (0, 0)), mode="edge")
        average = np.column_stack([np.convolve(column, weights, mode="valid") for column in window.T])
        points += (average - points) * blend[:, None]
    return LineString(points)


def compile_movements(edges, movements):
    groups, lines = {}, {}
    for spec in movements:
        a, da, d, dd = movement_ports(edges, spec)
        if spec.get("follow_via"):
            guide_id, = spec["via"]
            guide = edges[guide_id]
            approach, mouth, heading = source_approach(edges[spec["from"]], spec)
            points = approach[:-1]

            # Keep the slip in the approach lane up to the split, then join the
            # guide beyond the start taper so that its offset does not pull us inward.
            length = guide.line.length
            taper = max((entry[1] + sum(entry[4:]) for entry in guide.section.get("tapers", [])
                         if entry[0] == "start"), default=0)
            start, end = min(length * 0.45, max(length * 0.18, taper)), length * 0.82
            b, db = guide.port(start, 0, 1)
            c, dc = guide.port(end, 0, 1)
            lead, tail = np.linalg.norm(b - mouth) / 3, np.linalg.norm(d - c) / 3
            normal = np.array([-heading[1], heading[0]])
            lateral = (b - mouth) @ normal
            heading_change = db @ normal
            finish = min(lead, abs(lateral / heading_change)) if lateral * heading_change > 0 else lead
            points += list(cubic(mouth, mouth + heading * lead, b - db * finish, b)[:-1])
            points += list(guide.trace(0.5, np.linspace(start, end, math.ceil((end - start) * 2) + 1)).coords)
            points += list(cubic(c, c + dc * tail, d - dd * tail, d)[1:])
            lines[spec["id"]] = smooth_connector(LineString(points), LineString(approach).length)
            continue
        prefix = []
        approach_length = spec.get("approach_length", 0)
        if approach_length:
            prefix, mouth, heading = source_approach(edges[spec["from"]], spec)
            guide = edges[spec["via"][0]]
            lane = spec["from_lane"]
            join = min(3.0, approach_length / 2)
            b, db = guide.port(join, lane, 1)
            reach = np.linalg.norm(b - mouth) / 3
            prefix += list(cubic(mouth, mouth + heading * reach, b - db * reach, b)[1:-1])
            stations = np.linspace(join, approach_length, math.ceil((approach_length - join) * 2) + 1)
            prefix += list(guide.trace(guide.lane_fraction(lane, 1), stations).coords[:-1])
            a, da = guide.port(approach_length, lane, 1)

        key = (spec["from"], spec["to"], tuple(spec["via"]), spec["setback"], spec.get("handle", 0.36),
               spec.get("from_direction", 1), spec.get("to_direction", 1), approach_length)
        groups.setdefault(key, []).append((spec["id"], prefix, a, da, d, dd))

    for key, group in groups.items():
        a, da, d, dd = np.mean([entry[2:] for entry in group], axis=0)
        da, dd = unit(da), unit(dd)
        handle = np.linalg.norm(d - a) * key[4]
        points = cubic(a, a + da * handle, d - dd * handle, d)
        tangents = np.gradient(points, axis=0)
        tangents[0], tangents[-1] = da, dd
        normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        t = np.linspace(0, 1, len(points))
        blend = t * t * (3 - 2 * t)
        for movement_id, prefix, start, _, end, _ in group:
            offset = (1 - blend) * ((start - a) @ normals[0]) + blend * ((end - d) @ normals[-1])
            lane = points + normals * offset[:, None]
            lane[0], lane[-1] = start, end
            lines[movement_id] = LineString(prefix + list(lane))
    return [(spec, lines[spec["id"]]) for spec in movements]


def footprint(edge):
    """Sweep the left and right section boundaries in the centerline's local frame."""
    line = edge.line
    stations = np.linspace(0, line.length, max(2, int(line.length * 2) + 1))
    left = list(edge.trace(0, stations).coords)
    right = list(edge.trace(1, stations).coords)
    return make_valid(Polygon(left + right[::-1]))


def dash(line, length=3, period=8):
    return [substring(line, start, min(line.length, start + length))
            for start in np.arange(0, line.length, period) if line.length - start > 0.2]


def stroke(line, width):
    return line.buffer(width / 2, cap_style="flat")


def approach_paint(edge, begin, end):
    section = edge.section
    if end - begin < 1 or section["cls"] in {"service", "living_street"}:
        return []
    stations = np.linspace(begin, end, math.ceil((end - begin) * 2) + 1)
    margin = 0.24 / section["w"]
    marks = [stroke(edge.trace(f, stations), 0.14) for f in (margin, 1 - margin)]
    for direction in ((1,) if section["ow"] else (1, -1)):
        n = lane_count(section, direction)
        lo, hi = lane_bounds(section, direction)
        for index in range(1, n):
            offset = (lo + (hi - lo) * index / n) * direction
            paint_stations = stations
            if index == 1 and (opening := section.get("left_lane_opening")):
                paint_stations = stations[stations >= opening * 0.34]
            if taper := section.get("lane_taper"):
                end_name, length, side = taper
                if index == (1 if side == "left" else n - 1):
                    distance = stations if end_name == "start" else edge.line.length - stations
                    paint_stations = stations[distance >= length * 0.33]
            if len(paint_stations) > 1:
                shifted = edge.trace(0.5 + offset / section["w"], paint_stations, lane_aligned=True)
                marks.extend(stroke(piece, 0.14) for piece in dash(shifted))
        if not section["ow"] and direction == 1:
            marks.append(stroke(edge.trace(0.5 + lo / section["w"], stations), 0.15))
    return marks


def turn_arrow(p, heading, turn):
    right = np.array([-heading[1], heading[0]])
    side = -1 if turn.endswith("left") else 1 if turn.endswith("right") else 0
    stem = p - 1.6 * heading
    elbow = p + 0.45 * heading
    tip = p + (elbow - p if side else heading * 1.65) + right * (side * 1.05)
    base = tip - unit(tip - elbow) * 0.59
    normal = right if not side else heading
    return stroke(LineString([stem, elbow, base]), 0.22).union(
        Polygon([tip, base + normal * 0.36, base - normal * 0.36]))


def approach_arrows(edge, station, movements):
    painted = lane_turns(edge.section)
    inferred = [set() for _ in range(lane_count(edge.section))]
    for movement in movements:
        if "turn" not in movement or movement.get("from_direction", 1) != 1:
            continue
        if edge.id == movement["from"]:
            inferred[movement["from_lane"]].add(movement["turn"])
        elif movement["via"] and edge.id == movement["via"][0]:
            lane = 0 if movement.get("follow_via") else movement["from_lane"]
            if lane < len(inferred):
                inferred[lane].add("through" if movement.get("follow_via") else movement["turn"])
    arrows = []
    for lane, fallback in enumerate(inferred):
        kinds = (painted[lane] if painted else frozenset()) or fallback
        p, heading = edge.port(station, lane, 1)
        arrows.extend(turn_arrow(p, heading, kind) for kind in sorted(kinds))
    return arrows


def yield_teeth(edge, station):
    p, heading, right = frame(edge.line, station)
    lo, hi = edge.cross_section(station)
    base = 0.43
    pitch = 0.66
    count = max(1, math.floor((hi - lo - 0.28 - base) / pitch) + 1)
    centers = (lo + hi) / 2 + (np.arange(count) - (count - 1) / 2) * pitch
    return [Polygon([p + right * (offset - base / 2), p + right * (offset + base / 2),
                     p + right * offset - heading * (base * 1.5)]) for offset in centers]


def edge_band(edge, side, width):
    stations = np.linspace(0, edge.line.length, math.ceil(edge.line.length * 2) + 1)
    fraction = 0 if side == "left" else 1
    inner = list(edge.trace(fraction, stations).coords)
    outer = list(edge.trace(fraction, stations, -width if side == "left" else width).coords)
    return make_valid(Polygon(inner + outer[::-1]))


def crossing_span(edge, station, asphalt):
    point, heading, right = frame(edge.line, station)
    lo, hi = edge.cross_section(station)
    probe = LineString([point + right * (lo - 3.5), point + right * (hi + 3.5)])
    surface = probe.intersection(asphalt)
    spans = [part for part in getattr(surface, "geoms", (surface,)) if part.geom_type == "LineString"]
    span = min(spans, key=lambda part: part.distance(Point(point)))
    lo, hi = sorted((np.array(span.coords[i]) - point) @ right for i in (0, -1))
    return point, heading, right, lo, hi


def slip_edge_arc(surfaces, edges, join):
    source, target, before, after = join[:4]
    first, last = edges[source], edges[target]
    start_station = first.line.length - before
    a = Point(first.trace(1, [start_station, start_station + 0.1]).coords[0])
    b = Point(last.trace(1, [after, after + 0.1]).coords[0])
    index = min(range(len(surfaces)), key=lambda i: surfaces[i].exterior.distance(a) + surfaces[i].exterior.distance(b))
    surface = orient(surfaces[index], sign=1)
    ring = LineString(surface.exterior.coords)
    start, end = sorted((ring.project(a), ring.project(b)))
    between = substring(ring, start, end)
    around = LineString(list(substring(ring, end, ring.length).coords)
                        + list(substring(ring, 0, start).coords)[1:])
    arc, remainder = (between, around) if between.length <= around.length else (around, between)
    return index, arc, remainder


def blend_slip_edges(asphalt, edges, joins, report=None):
    """Blend each continuous outer asphalt edge, returning its sidewalk replacement zone."""
    surfaces = polys(asphalt)
    patches = []
    for join in joins:
        index, arc, remainder = slip_edge_arc(surfaces, edges, join)
        if report is not None and len(join) > 4 and arc.length > join[4]:
            report.append(dict(kind="sidewalk_join_needs_layout", source=join[0], target=join[1]))
            continue
        smoothed = smooth_connector(arc, 0, passes=55, blend_length=6)
        rebuilt = Polygon(list(smoothed.coords) + list(remainder.coords)[1:], surfaces[index].interiors)
        if not rebuilt.is_valid:
            if report is None:
                raise ValueError(f"Invalid outer asphalt blend for OSM ways {join[0]} and {join[1]}")
            report.append(dict(kind="sidewalk_join_needs_layout", source=join[0], target=join[1]))
            continue
        surfaces[index] = rebuilt
        patches.append(arc.buffer(-3.65, single_sided=True).union(smoothed.buffer(-3.65, single_sided=True)))
    return unary_union(surfaces), patches


def median_cut_through(a, b):
    """A level crossing link with flared, rounded mouths at the carriageways."""
    direction = unit(b - a)
    walk = LineString([a - 0.45 * direction, b + 0.45 * direction]).buffer(1.35)
    mouths = unary_union([Point(a).buffer(1.65), Point(b).buffer(1.65)])
    return walk.union(mouths).buffer(0.4).buffer(-0.4)


def pedestrian_geometry(edges, layout, walks, asphalt, bounds, refuges, sidewalk_patches, divider):
    """Build road-owned walking surfaces, then admit only attached OSM path spurs."""
    sidewalks, curbs, links, zebras, crossing_areas = [], [], [], [], []
    for way, sides in layout["road_edges"].items():
        for side, feature in zip(("left", "right"), sides):
            if feature == "sidewalk":
                sidewalks.append(edge_band(edges[int(way)], side, 2.4))
            elif feature == "curb":
                curbs.append(edge_band(edges[int(way)], side, 0.32))
    sidewalk = unary_union(sidewalks).buffer(0.6).buffer(-0.6).intersection(bounds).difference(asphalt)
    sidewalk_outline = asphalt.buffer(2.4).difference(asphalt)
    for patch in sidewalk_patches:
        sidewalk = sidewalk.difference(patch).union(sidewalk_outline.intersection(patch)).intersection(bounds)
    if not divider.is_empty:
        sidewalk = sidewalk.difference(divider)
    # Follow the final asphalt where a road edge or a median nose calls for a curb.
    # The raw section bands only classify the edge and may be covered by the apron.
    returns = [Point(x, y).buffer(radius) for x, y, radius in layout.get("curb_returns", [])]
    curb_zone = unary_union([unary_union(curbs).buffer(0.9), refuges, *returns])
    if not divider.is_empty:
        curb_zone = curb_zone.union(divider)
    outline = asphalt.buffer(0.32).difference(asphalt)
    curb = outline.intersection(curb_zone).intersection(bounds).difference(sidewalk)

    terminals = {}
    cuts = []
    median_pairs = {frozenset((abs(a), abs(b))) for near, far in layout.get("median_corridors", [])
                    for a in near for b in far}
    for group in layout["crossings"]:
        last = None
        previous_way = None
        for way, station in group:
            point, heading, right, lo, hi = crossing_span(edges[way], station, asphalt)
            ends = (point + right * lo, point + right * hi)
            terminals[way] = ends
            strip = stroke(LineString(ends), 3.1)
            road = strip.intersection(asphalt)
            crossing_areas.append(road)
            for offset in np.arange(lo + 0.32, hi - 0.12, 0.82):
                p = point + right * offset
                zebras.append(stroke(LineString([p - heading * 1.55, p + heading * 1.55]), 0.44).intersection(road))
            links.append(stroke(LineString([point + right * (lo - 2.4), point + right * (hi + 2.4)]), 2.1))
            if last is not None:
                a, b = min(((a, b) for a in last for b in ends), key=lambda pair: np.linalg.norm(pair[1] - pair[0]))
                if frozenset((previous_way, way)) in median_pairs:
                    cuts.append(median_cut_through(a, b))
                else:
                    links.append(stroke(LineString([a, b]), 2.1))
            last = ends
            previous_way = way

    for a_way, a_side, b_way, b_side in layout.get("refuge_links", []):
        a = terminals[a_way][int(a_side == "right")]
        b = terminals[b_way][int(b_side == "right")]
        links.append(stroke(LineString([a, b]), 2.1))
    cut_throughs = unary_union(cuts).intersection(bounds).difference(asphalt)
    routes = unary_union(links).intersection(bounds).difference(asphalt)
    curb = curb.union(cut_throughs.buffer(0.32).difference(asphalt).difference(sidewalk))
    curb = unary_union(polys(curb.difference(routes).difference(cut_throughs)))
    active_refuges = unary_union([refuge for refuge in polys(refuges) if refuge.intersection(routes).area > 0.1])
    sidewalk_base = sidewalk.union(active_refuges).difference(asphalt).difference(curb)
    # On an existing sidewalk or refuge, only the curb ramp needs its own mesh.
    ramps = routes.intersection(asphalt.buffer(1.35))
    landings = routes.difference(sidewalk_base).union(ramps).difference(cut_throughs)
    paths = []
    for line, width, _ in walks:
        clipped = stroke(line, width).intersection(bounds).difference(asphalt)
        if not divider.is_empty:
            clipped = clipped.difference(divider)
        usable = unary_union(polys(clipped)).difference(curb)
        paths.extend(part for part in polys(usable) if part.intersection(sidewalk).area > 0.12)
    walking_links = landings.union(cut_throughs)
    footpaths = unary_union(paths).difference(sidewalk_base).difference(walking_links)
    return (sidewalk_base.difference(walking_links), curb, landings, cut_throughs,
            footpaths, unary_union(crossing_areas), zebras)


def median_corridors(edges, layout):
    for near, far in layout.get("median_corridors", []):
        sides = []
        for chain in (near, far):
            points = []
            for way in chain:
                coords = list(edges[abs(way)].line.coords)
                points.extend(coords if way > 0 else coords[::-1])
            sides.append(points)
        yield make_valid(Polygon(sides[0] + sides[1][::-1]))


def median_corridor_geometry(edges, layout):
    """Join adjoining mapped carriageway pairs across their OSM way seams."""
    return unary_union([poly for corridor in median_corridors(edges, layout) for poly in polys(corridor)]).buffer(
        0.8).buffer(-0.8)


def protected_median(edges, layout, raw_pavement, bounds):
    corridor = median_corridor_geometry(edges, layout).intersection(bounds)
    # Round out slivers at the caps of adjacent OSM ways. Keep the lengthwise divider
    # while allowing explicitly mapped transverse carriageways through it.
    return corridor.difference(raw_pavement.buffer(0.12).buffer(-0.12)).buffer(-0.26).buffer(0.26)


def median_landscape(edges, layout, greens, asphalt, bounds, reserved):
    """Use mapped grass to select planted medians; the carriageways set their shape."""
    mapped = unary_union(greens).intersection(bounds)
    planted = []
    corridors = (polys(median_corridor_geometry(edges, layout)) if layout.get("source") == "osm-topology"
                 else median_corridors(edges, layout))
    for corridor in corridors:
        median = unary_union(polys(corridor.intersection(bounds).difference(asphalt)))
        if mapped.intersection(median).area > 5:
            planted.append(median)
    return mapped.union(unary_union(planted)).difference(reserved)


def place_traffic_furniture(edges, layout, asphalt, landings, report=None):
    """Set poles beside the traffic lane or crosswalk, clear of the pedestrian entries."""
    stations = dict(item for group in layout["crossings"] for item in group)
    blocked = asphalt.buffer(0.22).union(landings.buffer(0.24))
    devices = []
    occupied = []

    def clear(position):
        return not blocked.covers(Point(position)) and all(
            np.linalg.norm(position - other) >= 0.62 for other in occupied
        )

    def roadside(kind, way, station, side):
        edge = edges[way]
        for shift in (0, -0.6, 0.6, -1.3, 1.3):
            p, heading, right, lo, hi = crossing_span(edge, station + shift, asphalt)
            for offset in (0.58, 0.9, 1.25, 1.7, 2.1):
                position = p + right * ((lo if side < 0 else hi) + side * offset)
                if not clear(position):
                    continue
                facing = right * -side if kind == "pedestrian_signal" else -heading
                devices.append(dict(kind=kind, way=way, station=round(station + shift, 2),
                                    side="left" if side < 0 else "right",
                                    position=position.tolist(), facing=facing.tolist()))
                occupied.append(position)
                return
        if report is not None:
            report.append(dict(kind="pole_location_needs_layout", device=kind, edge=way))
        else:
            raise ValueError(f"No clear pole location for {kind} on OSM way {way} at {station:.1f} m")

    def gantry(way, stop):
        edge = edges[way]
        for shift in (-1.2, -2.0, -3.0, -0.45):
            station = stop + shift
            p, heading, right, lo, hi = crossing_span(edge, station, asphalt)
            supports = [next((position for inset in (0.75, 1.05, 1.4, 1.85)
                              if clear(position := p + right * (lateral + side * inset))), None)
                        for lateral, side in ((lo, -1), (hi, 1))]
            if any(point is None for point in supports):
                continue
            heads = [dict(lane=i, position=edge.port(station, i, 1)[0].tolist())
                     for i in range(lane_count(edge.section))]
            devices.append(dict(kind="vehicle_gantry", way=way, station=station, facing=(-heading).tolist(),
                                supports=[point.tolist() for point in supports], heads=heads,
                                clearance_m=GANTRY_CLEARANCE))
            occupied.extend(supports)
            return
        if report is not None:
            report.append(dict(kind="gantry_location_needs_layout", edge=way))
            roadside("vehicle_signal", way, stop, 1)
        else:
            raise ValueError(f"No clear gantry supports for OSM way {way}")

    for way in layout["stop_lines"]:
        stop = stations[way] - 3.4
        if lane_count(edges[way].section) >= 2:
            gantry(way, stop)
        else:
            roadside("vehicle_signal", way, stop, 1)
        roadside("vehicle_signal", way, stations[way] + 3.3, -1)
    for way in layout.get("pedestrian_signals", []):
        for side in (-1, 1):
            roadside("pedestrian_signal", way, stations[way] + 2.45, side)
    for kind, way, at, side in layout.get("signs", []):
        station = edges[way].line.length + at if at < 0 else at
        roadside(kind, way, station, -1 if side == "left" else 1)
    return devices


def compile_scene(edges, layout, walks, greens, bounds, report=None):
    """Return mesh plus the compiled movements, their conflicts and the paved footprint."""
    by_id = {edge.id: edge for edge in edges}
    movements = layout["movements"]
    if len({spec["id"] for spec in movements}) != len(movements):
        raise ValueError("Movement IDs must be unique")
    routes = compile_movements(by_id, movements)
    road_footprints = [poly for edge in edges for poly in polys(footprint(edge))]
    asphalt = unary_union(road_footprints)
    inferred = layout.get("source") == "osm-topology"
    divider = (protected_median(by_id, layout, asphalt, bounds)
               if inferred else Polygon())
    # A routing mistake should fail review before it can pave an unmapped lot.
    safe_area = asphalt.buffer(3.5)
    for spec, line in routes:
        if not line.is_simple or not safe_area.covers(line) or not bounds.covers(line):
            raise ValueError(f"Invalid or off-road movement {spec['id']}")
    # Sweep the vehicle envelope through the actual lane connectors to form the
    # apron. This leaves unmapped gaps and medians outside the sweep intact.
    envelopes = {spec["id"]: line.buffer(spec.get("sweep_width", 2.94) / 2, cap_style="flat")
                 for spec, line in routes}
    asphalt = asphalt.union(unary_union(list(envelopes.values())))
    for x, y, radius in layout["corner_zones"]:
        zone = Point(x, y).buffer(radius)
        local = asphalt.intersection(zone.buffer(4))
        asphalt = asphalt.union(local.buffer(1.45).buffer(-1.45).intersection(zone))
    asphalt = asphalt.intersection(bounds).difference(divider) if inferred else asphalt.intersection(bounds)
    holes = [Polygon(ring) for poly in polys(asphalt) for ring in poly.interiors]
    fill = [hole for hole in holes if hole.area < 15 and hole.buffer(-0.65).area < 1]
    refuges = [hole for hole in holes if 15 <= hole.area < 190
               and (not inferred or hole.intersection(divider).area < hole.area * 0.2)]
    rounding = list(layout.get("refuge_rounding", []))
    rounded_tips = []
    if inferred:
        slip_inside = unary_union([edge_band(edge, "left", 0.55) for edge in edges
                                  if edge.section["cls"].endswith("_link") and edge.section["ow"]])
        for hole in holes:
            if (15 <= hole.area <= 420 and hole.intersection(divider).area < hole.area * 0.2
                    and hole.boundary.intersection(slip_inside.buffer(0.12)).length >= 5):
                seed = hole.representative_point()
                rounding.append([seed.x, seed.y, 1])
    for x, y, radius in rounding:
        seed = Point(x, y)
        hole = next((hole for hole in holes if hole.contains(seed)), None)
        if hole is None:
            raise ValueError(f"No enclosed refuge at ({x}, {y})")
        rounded = hole.buffer(-radius).buffer(radius).intersection(hole)
        refuges = [refuge for refuge in refuges if refuge is not hole] + [rounded]
        removed = hole.difference(rounded)
        fill.append(removed)
        if inferred:
            rounded_tips.append(removed)
    asphalt = asphalt.union(unary_union(fill))
    if inferred:
        asphalt = asphalt.difference(divider)
    blended, sidewalk_patches = blend_slip_edges(asphalt, by_id, layout.get("sidewalk_curves", []), report)
    if report is not None and sidewalk_patches and any(env.difference(blended).area > 0.01 for env in envelopes.values()):
        report.append(dict(kind="sidewalk_join_would_reduce_lane_clearance"))
        sidewalk_patches = []
    else:
        asphalt = blended
    refuges = unary_union(refuges)
    pavement, curb, landings, cut_throughs, paths, crossings, zebras = pedestrian_geometry(
        by_id, layout, walks, asphalt, bounds, refuges, sidewalk_patches, divider)
    reserved = unary_union([asphalt, pavement, curb, landings, cut_throughs, paths])
    grass = median_landscape(by_id, layout, greens, asphalt, bounds, reserved)
    marks = []
    clear = {}
    for way, start, end in layout["unmarked"]:
        edge = by_id[way]
        clear[way] = [start, end if end is not None else edge.line.length]
    for edge in edges:
        begin, end = clear.get(edge.id, [0.0, edge.line.length])
        marks.extend(approach_paint(edge, begin, end))
    if layout.get("source") == "osm-topology" and road_footprints:
        footprint_array = np.asarray(road_footprints, dtype=object)
        neighbors = STRtree(footprint_array).query(footprint_array, predicate="intersects")
        overlaps = [road_footprints[i].intersection(road_footprints[j])
                    for i, j in neighbors.T if i < j]
        shared_pavement = unary_union([overlap for overlap in overlaps if overlap.area > 0.35])
        painted = unary_union(marks).difference(shared_pavement.buffer(0.6))
        if rounded_tips:
            painted = painted.difference(unary_union(rounded_tips).buffer(0.5))
        marks = [painted]
    crossing_stations = dict(item for group in layout["crossings"] for item in group)
    for way in layout["stop_lines"]:
        edge = by_id[way]
        station = crossing_stations[way] - 3.4
        p, _, right = frame(edge.line, station)
        left_edge, right_edge = edge.cross_section(station)
        marks.append(stroke(LineString([p + right * (left_edge + 0.28), p + right * (right_edge - 0.28)]), 0.34))
        marks.extend(approach_arrows(edge, max(0, station - 4.5), movements))
    for way, station in layout.get("approach_arrows", []):
        edge = by_id[way]
        at = edge.line.length + station if station < 0 else station
        marks.extend(approach_arrows(edge, at, movements))
    for way, station in layout.get("yield_lines", []):
        marks.extend(yield_teeth(by_id[way], station))

    mesh = Mesh()
    mesh.poly(bounds, -0.075, (108, 123, 94))
    mesh.poly(asphalt, 0, (57, 61, 66))
    mesh.prism(grass, -0.065, 0.125, (111, 137, 82), (155, 150, 129))
    mesh.prism(pavement, -0.065, 0.145, (181, 175, 161), (143, 139, 128))
    mesh.prism(curb, -0.065, 0.155, (203, 197, 181), (154, 148, 136))
    mesh.prism(paths, -0.065, 0.145, (164, 157, 143), (136, 131, 121))
    mesh.poly(landings, lambda x, y: 0.145 * min(1, asphalt.distance(Point(x, y)) / 1.35),
              (181, 175, 161))
    mesh.poly(cut_throughs, 0, (181, 175, 161))
    paint = unary_union(marks).difference(crossings.buffer(0.25))
    mesh.poly(paint.union(unary_union(zebras)).intersection(asphalt.buffer(-0.08)), 0.011, PAINT, lit=False)
    furniture = place_traffic_furniture(by_id, layout, asphalt, landings.union(cut_throughs), report)
    for device in furniture:
        if device["kind"] == "vehicle_gantry":
            draw_gantry(mesh, device)
        else:
            draw_device(mesh, device["kind"], device["position"], device["facing"])

    conflicts = []
    for (a, _), (b, _) in combinations(routes, 2):
        ae, be = envelopes[a["id"]], envelopes[b["id"]]
        if ae.intersection(be).area > 0.5:
            conflicts.append([a["id"], b["id"]])
    pedestrian = {"sidewalks": mapping(pavement), "footpath_links": mapping(paths),
                  "crossing_landings": mapping(landings.union(cut_throughs)), "crosswalks": mapping(crossings),
                  "median_cut_throughs": mapping(cut_throughs),
                  "non_walkable_curbs": mapping(curb)}
    return mesh, routes, conflicts, asphalt, furniture, pedestrian
