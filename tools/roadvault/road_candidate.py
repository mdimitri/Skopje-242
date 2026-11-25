"""Compile a local at-grade road graph into a mesh and a lane-movement graph."""
from dataclasses import dataclass
from itertools import combinations
import math
from pathlib import Path
import sys

import numpy as np
from shapely import make_valid
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring, unary_union

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src"))
from roadwidth import lane_bounds, lane_count, lane_turns  # noqa: E402

from mesh import Mesh, polys

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
        """Blend signed left/right boundary changes over the authored taper distance."""
        offsets = np.array([-0.5, 0.5]) * self.section["w"]
        for end, length, left, right in self.section.get("tapers", []):
            distance = station if end == "start" else self.line.length - station
            t = max(0, 1 - distance / length)
            offsets += np.array([left, right]) * t * t * (3 - 2 * t)
        return offsets

    def trace(self, fraction, stations):
        points = []
        for station in stations:
            p, _, right = frame(self.line, station)
            left_edge, right_edge = self.cross_section(station)
            points.append(p + right * (left_edge + fraction * (right_edge - left_edge)))
        return LineString(points)

    def lane_fraction(self, lane, direction):
        lo, hi = lane_bounds(self.section, direction)
        nominal = lo + (lane + 0.5) * (hi - lo) / lane_count(self.section, direction)
        return 0.5 + nominal * direction / self.section["w"]

    def port(self, station, lane, direction):
        before, p, after = self.trace(self.lane_fraction(lane, direction), [
            max(0, station - 0.25), station, min(self.line.length, station + 0.25)
        ]).coords
        return np.array(p), unit(np.subtract(after, before)) * direction


def road_edge(way, points, tapers=()):
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


def compile_movements(edges, movements):
    groups, lines = {}, {}
    for spec in movements:
        a, da, d, dd = movement_ports(edges, spec)
        if spec.get("follow_via"):
            guide_id, = spec["via"]
            guide = edges[guide_id]
            source = edges[spec["from"]]
            direction = spec.get("from_direction", 1)
            setback = min(spec["setback"], source.line.length * 0.45)
            split = source.line.length if direction == 1 else 0
            stations = np.linspace(split - direction * setback, split, math.ceil(setback * 2) + 1)
            lane = spec["from_lane"]
            points = list(source.trace(source.lane_fraction(lane, direction), stations).coords[:-1])
            mouth, heading = source.port(split, lane, direction)

            # Keep the slip in the approach lane up to the split, then join the
            # guide beyond the start taper so that its offset does not pull us inward.
            length = guide.line.length
            taper = max((entry[1] for entry in guide.section.get("tapers", []) if entry[0] == "start"), default=0)
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
            lines[spec["id"]] = LineString(points)
            continue
        key = (spec["from"], spec["to"], tuple(spec["via"]), spec["setback"], spec.get("handle", 0.36),
               spec.get("from_direction", 1), spec.get("to_direction", 1))
        groups.setdefault(key, []).append((spec["id"], a, da, d, dd))

    for key, group in groups.items():
        a, da, d, dd = np.mean([entry[1:] for entry in group], axis=0)
        da, dd = unit(da), unit(dd)
        handle = np.linalg.norm(d - a) * key[4]
        points = cubic(a, a + da * handle, d - dd * handle, d)
        tangents = np.gradient(points, axis=0)
        tangents[0], tangents[-1] = da, dd
        normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
        normals /= np.linalg.norm(normals, axis=1)[:, None]
        t = np.linspace(0, 1, len(points))
        blend = t * t * (3 - 2 * t)
        for movement_id, start, _, end, _ in group:
            offset = (1 - blend) * ((start - a) @ normals[0]) + blend * ((end - d) @ normals[-1])
            lane = points + normals * offset[:, None]
            lane[0], lane[-1] = start, end
            lines[movement_id] = LineString(lane)
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
            shifted = edge.trace(0.5 + offset / section["w"], stations)
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
    return stroke(LineString([stem, elbow, base]), 0.17).union(
        Polygon([tip, base + normal * 0.31, base - normal * 0.31]))


def compile_scene(edges, layout, walks, greens, bounds):
    """Return mesh plus the compiled movements, their conflicts and the paved footprint."""
    by_id = {edge.id: edge for edge in edges}
    movements = layout["movements"]
    if len({spec["id"] for spec in movements}) != len(movements):
        raise ValueError("Movement IDs must be unique")
    routes = compile_movements(by_id, movements)
    asphalt = unary_union([poly for edge in edges for poly in polys(footprint(edge))])
    # A routing mistake should fail review before it can pave an unmapped lot.
    safe_area = asphalt.buffer(3.5)
    for spec, line in routes:
        if not line.is_simple or not safe_area.covers(line) or not bounds.covers(line):
            raise ValueError(f"Invalid or off-road movement {spec['id']}")
    # Sweep the vehicle envelope through the actual lane connectors to form the
    # apron. This leaves unmapped gaps and medians outside the sweep intact.
    envelopes = {spec["id"]: line.buffer(1.47, cap_style="flat") for spec, line in routes}
    asphalt = asphalt.union(unary_union(list(envelopes.values())))
    for x, y, radius in layout["corner_zones"]:
        zone = Point(x, y).buffer(radius)
        local = asphalt.intersection(zone.buffer(4))
        asphalt = asphalt.union(local.buffer(1.45).buffer(-1.45).intersection(zone))
    asphalt = asphalt.intersection(bounds)
    grass = unary_union(greens).intersection(bounds).difference(asphalt)
    refuges = unary_union([
        Polygon(ring) for poly in polys(asphalt) for ring in poly.interiors
        if 12 < Polygon(ring).area < 190
    ])
    pavement = unary_union([stroke(line, width) for line, width, _ in walks])
    pavement = pavement.union(refuges).intersection(bounds).difference(asphalt).difference(grass)
    marks = []
    clear = {}
    for way, start, end in layout["unmarked"]:
        edge = by_id[way]
        clear[way] = [start, end if end is not None else edge.line.length]
    for edge in edges:
        begin, end = clear.get(edge.id, [0.0, edge.line.length])
        marks.extend(approach_paint(edge, begin, end))
    poles = []
    for way, setback in layout["stop_lines"]:
        edge = by_id[way]
        station = edge.line.length - setback
        p, heading, right = frame(edge.line, station)
        left_edge, right_edge = edge.cross_section(station)
        marks.append(stroke(LineString([p + right * (left_edge + 0.28), p + right * (right_edge - 0.28)]), 0.34))
        pole = p + right * (right_edge + 0.65)
        if not asphalt.covers(Point(pole)):
            poles.append((pole, heading))
        for lane, turns in enumerate(lane_turns(edge.section)):
            for turn in sorted(turns):
                pos, heading = edge.port(max(0, station - 4.5), lane, 1)
                marks.append(turn_arrow(pos, heading, turn))
    for crossing in layout["crossings"]:
        line = LineString(crossing)
        p, across, along = frame(line, line.length / 2)
        for distance in np.arange(-line.length / 2 + 0.35, line.length / 2, 0.82):
            centre = p + across * distance
            marks.append(stroke(LineString([centre - along * 1.55, centre + along * 1.55]), 0.43))

    mesh = Mesh()
    mesh.poly(bounds, -0.075, (108, 123, 94))
    mesh.poly(asphalt, 0, (57, 61, 66))
    mesh.prism(grass, -0.065, 0.125, (111, 137, 82), (155, 150, 129))
    mesh.prism(pavement, -0.065, 0.145, (181, 175, 161), (143, 139, 128))
    for line, width, kind in walks:
        if kind == "cycleway":
            mesh.poly(stroke(line, width).intersection(pavement), 0.148, (139, 157, 150))
    mesh.poly(unary_union(marks).intersection(asphalt.buffer(-0.1)), 0.011, PAINT, lit=False)
    for (x, y), heading in poles:
        mesh.cyl(x, 0.1, 3.1, y, 0.09, (126, 130, 128))
        mesh.box(x, 2.72, y, 0.27, 0.79, 0.3, (45, 47, 45))
        face = np.array([x, y]) - heading * 0.17
        angle = math.atan2(heading[1], heading[0])
        for height, colour in [(3.27, (220, 65, 57)), (3.04, (100, 84, 42)), (2.81, (51, 79, 55))]:
            mesh.box(face[0], height, face[1], 0.045, 0.14, 0.14, colour, yaw=angle)

    conflicts = []
    for (a, _), (b, _) in combinations(routes, 2):
        ae, be = envelopes[a["id"]], envelopes[b["id"]]
        if ae.intersection(be).area > 0.5:
            conflicts.append([a["id"], b["id"]])
    return mesh, routes, conflicts, asphalt
