"""Apply the road candidate's signal hardware and controls across the city."""
import math
from collections import defaultdict

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from furniture import RANK, plan_lights
from driving import turn_angle
from geo import project
from roadwidth import lane_bounds, lane_count
from roadvault.mesh import Mesh
from roadvault.road_candidate import PAINT, frame, stroke
from roadvault.traffic_furniture import GANTRY_CLEARANCE, draw_device, draw_gantry


def nearby_stop(edges, inc, stops, ei, end, station):
    """Find another stop along the same directed through lane within 50 m."""
    direction = 1 if end else -1
    for downstream in (True, False):
        move = (ei, direction)
        offset = station
        remaining = 50.0
        seen = set()
        while remaining > 0 and move not in seen:
            seen.add(move)
            index, d = move
            current = edges[index]
            for at in stops.get(move, ()):
                gap = at - offset if downstream else offset - at
                if 0 <= gap < remaining:
                    return True
            node_end = int((d == 1) == downstream)
            remaining -= current["len"] - offset if downstream else offset
            options = []
            for candidate, candidate_end in inc[current["b" if node_end else "a"]]:
                road = edges[candidate]
                travel = (candidate, 1 if bool(candidate_end) != downstream else -1)
                if candidate == index or (road["ow"] and travel[1] == -1) or current["cls"].endswith("_link") != road["cls"].endswith("_link"):
                    continue
                bend = turn_angle(edges, move, travel) if downstream else turn_angle(edges, travel, move)
                if abs(bend) < 0.35:
                    options.append((abs(bend), travel))
            if not options:
                break
            move = min(options)[1]
            offset = 0.0 if downstream else edges[move[0]]["len"]
    return False


def build(edges, mapped, controls, add, chunk_of, material, terrain, clear, roads=(), ways=()):
    """Fill the gaps in the candidate plan using mapped lights and junction topology."""
    if not controls:
        return
    inc = defaultdict(list)
    original_lines = {}
    for way in ways:
        if way.get("type") != "way" or len(way.get("geometry", ())) < 2:
            continue
        points = [project(point["lat"], point["lon"]) for point in way["geometry"]]
        if len(set(points)) >= 2:
            original_lines[way["id"]] = LineString(points)

    def placement(line, station, original):
        point, heading, right = frame(line, station)
        if original is None:
            return point, heading, right
        at = original.project(Point(point))
        raw_point, raw_heading, _ = frame(original, at)
        if np.linalg.norm(raw_point - point) > 4 or abs(raw_heading @ heading) < 0.85:
            return point, heading, right
        if raw_heading @ heading < 0:
            raw_heading = -raw_heading
        return raw_point, raw_heading, np.array([-raw_heading[1], raw_heading[0]])
    for ei, edge in enumerate(edges):
        if edge["drive"] and not edge["bridge"] and edge["w"] > 0 and edge["cls"] in RANK:
            inc[edge["a"]].append((ei, 0))
            inc[edge["b"]].append((ei, 1))
    lit, clusters = plan_lights(edges, inc)
    locations = {node: edges[arms[0][0]]["pts"][-1 if arms[0][1] else 0]
                 for node, arms in inc.items() if len(arms) >= 3}
    nodes = list(locations)
    index = STRtree([Point(locations[node]) for node in nodes])
    mapped_clusters = set()
    for xy in mapped:
        if not isinstance(xy, (list, tuple)) or len(xy) != 2 or not nodes:
            continue
        point = Point(xy)
        near = nodes[index.nearest(point)]
        if point.distance(Point(locations[near])) <= 38:
            mapped_clusters.add(clusters.get(near, near))
    lit.update(node for node in nodes if clusters.get(node, node) in mapped_clusters)

    original = tuple(controls["signals"])
    stops = defaultdict(list)
    for record in original:
        ei, end = record[1:3]
        stops[ei, 1 if end else -1].append(edges[ei]["len"] - record[9])
    existing = {(item[1], item[2]) for item in original}
    reviewed = [(item[6], item[7]) for item in original if item[0] == ("candidate", "glavinov")]
    node_map = {}
    for item in original:
        node, ei, end = item[:3]
        if node == ("candidate", "glavinov"):
            continue
        graph_node = edges[ei]["b" if end else "a"]
        node_map[node] = ("candidate", "city", clusters.get(graph_node, graph_node))
    controls["signals"] = [(node_map.get(item[0], item[0]), item[1], item[2],
                            item[1] * 2 + item[2] if item[0] in node_map else item[3], *item[4:])
                           for item in controls["signals"]]
    controls["heads"] = [(node_map.get(item[0], item[0]), *item[1:]) for item in controls["heads"]]
    controls["crossings"] = [(*item[:7], node_map.get(item[7], item[7]), *item[8:]) if len(item) > 7 else item
                             for item in controls["crossings"]]
    crossings = controls["crossings"]
    cross_points = [Point(c[:2]) for c in crossings]
    cross_index = STRtree(cross_points)
    zebra_areas = []
    for x, z, dx, dz, width, *_ in crossings:
        center = np.array([x, z])
        across = np.array([-dz, dx]) * (width / 2 + 0.25)
        zebra_areas.append(stroke(LineString([center - across, center + across]), 3.5))
    zebra_index = STRtree(zebra_areas)
    used_crossings = set()
    approaches = warnings = blocked = 0
    for node in sorted(lit):
        group = clusters.get(node, node)
        jx, jz = locations[node]
        if any(math.hypot(x - jx, z - jz) < 55 for x, z in reviewed):
            continue
        phase_node = ("candidate", "city", group)
        junction_width = max(edges[ei]["w"] for ei, _ in inc[node])
        near = cross_index.query(Point(jx, jz).buffer(37), predicate="intersects")
        for ei, end in inc[node]:
            edge = edges[ei]
            if edge["ow"] and not end:
                continue
            other = edge["a" if end else "b"]
            if other in lit and clusters.get(other) == group and edge["len"] < 45:
                continue
            line = LineString(edge["pts"] if end else edge["pts"][::-1])
            if line.length < 4 or (ei, end) in existing:
                continue
            width = edge["w"]
            original = original_lines.get(roads[edge["road"]]["id"]) if roads else None
            direction = 1 if end else -1
            lo, hi = lane_bounds(edge, direction)
            choices = []
            for i in near:
                station = line.project(cross_points[i])
                _, heading, _ = frame(line, station)
                if (4.5 <= line.length - station <= 35 and line.distance(cross_points[i]) <= 2.0
                        and abs(heading @ crossings[i][2:4]) >= 0.85):
                    choices.append((line.length - station, int(i), station))
            cross = min(choices, default=None)
            zebra = cross[2] if cross else line.length - min(junction_width / 2 + 3.2, line.length * 0.45)
            stop = max(0.35, zebra - 3.4)
            if nearby_stop(edges, inc, stops, ei, end, stop):
                continue
            point, heading, right = placement(line, stop, original)
            mesh = Mesh()
            stop_line = stroke(LineString([point + right * (lo + 0.2), point + right * (hi - 0.2)]), 0.34)
            if not len(zebra_index.query(stop_line, predicate="intersects")):
                mesh.poly(stop_line, 0.011, PAINT, lit=False)
            count = lane_count(edge, direction)
            gantry = None
            if count >= 2:
                supports = [next((pad for inset in (0.75, 1.05, 1.55, 2.05, 2.55, 3.05)
                                  if clear(*(pad := point + right * (side * (width / 2 + inset))))), None)
                            for side in (-1, 1)]
                if all(p is not None for p in supports):
                    gantry = (point, heading, right, supports)
            if gantry:
                anchor, heading, normal, supports = gantry
                heads = [anchor + normal * (lo + (hi - lo) * (lane + 0.5) / count) for lane in range(count)]
                draw_gantry(mesh, dict(supports=supports, heads=[{"position": p} for p in heads],
                                       clearance_m=GANTRY_CLEARANCE, facing=-heading), live=True)
                height = GANTRY_CLEARANCE
            else:
                side = None
                for station in (stop, max(0.35, stop - 3), max(0.35, stop - 6),
                                min(line.length - 0.35, stop + 3)):
                    anchor, signal_heading, normal = placement(line, station, original)
                    shoulders = (anchor + normal * (sign * (width / 2 + offset))
                                 for sign in (1, -1) for offset in (1.05, 1.55, 2.05))
                    side = next((p for p in shoulders if clear(*p)), None)
                    if side is not None:
                        break
                heads = [] if side is None else [side]
                if side is not None:
                    heading = signal_heading
                    draw_device(mesh, "vehicle_signal", side, -heading, live=True)
                else:
                    blocked += 1
                height = 2.78
            controls["signals"].append((phase_node, ei, end, ei * 2 + end, math.nan, math.nan,
                                        jx, jz, 0, line.length - stop))
            stops[ei, direction].append(stop)
            for x, z in heads:
                controls["heads"].append((phase_node, (ei, end), x, z, height, *(-heading)))
            if stop >= 12:
                p, h, r = placement(line, stop - min(18, stop - 1), original)
                sign = p + r * (width / 2 + 1.1)
                if clear(*sign):
                    draw_device(mesh, "signal_ahead", sign, -h)
                    warnings += 1
            # The road compiler has already checked both walkable landings.
            if width >= 4.5 and cross:
                key = cross[1]
                if key not in used_crossings:
                    center, axis, right = placement(line, zebra, original)
                    pads = [center + right * (side * (width / 2 + 0.8)) for side in (-1, 1)]
                    if all(clear(*p) for p in pads):
                        crossings[cross[1]] = (*crossings[cross[1]][:7], phase_node)
                        for side, pad in zip((-1, 1), pads):
                            facing = -side * right
                            draw_device(mesh, "pedestrian_signal", pad, facing, live=True)
                            controls["heads"].append((phase_node, None, *pad, 2.20, *facing))
                        used_crossings.add(key)
            _bake(mesh, terrain, add, chunk_of, material)
            approaches += 1
    print(f"[road controls] {approaches} city approaches added to {len(existing)} candidate approaches"
          f" with {warnings} warning signs and {len(used_crossings)} pedestrian signals"
          f" ({blocked} approaches with no clear pole site)")


def _bake(mesh, terrain, add, chunk_of, material):
    pos = np.asarray(mesh.P, dtype=np.float32)
    if not len(pos):
        return
    pos[:, 1] += terrain.h(pos[:, 0], pos[:, 2]) + 0.06
    color = np.asarray(mesh.C, dtype=np.uint8)
    chunks = defaultdict(list)
    for i, center in enumerate(pos.reshape(-1, 3, 3).mean(axis=1)):
        chunks[chunk_of(center[0], center[2])].extend((3 * i, 3 * i + 1, 3 * i + 2))
    for key, ids in chunks.items():
        add(key, material, pos[ids], np.zeros((len(ids), 2), np.float32), color[ids])
