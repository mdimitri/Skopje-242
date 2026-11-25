"""Apply the road candidate's signal hardware and controls across the city."""
import math
from collections import defaultdict

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from furniture import RANK, plan_lights
from roadwidth import lane_bounds, lane_count
from roadvault.mesh import Mesh
from roadvault.road_candidate import PAINT, frame, stroke
from roadvault.traffic_furniture import GANTRY_CLEARANCE, draw_device, draw_gantry


def build(edges, mapped, controls, add, chunk_of, material, terrain, clear):
    """Fill the gaps in the candidate plan using mapped lights and junction topology."""
    if not controls:
        return
    inc = defaultdict(list)
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
    existing = {(item[1], item[2]) for item in original}
    reviewed = [(item[6], item[7]) for item in original if item[0] == ("candidate", "glavinov")]
    reserved = {clusters.get(edges[ei]["b" if end else "a"], edges[ei]["b" if end else "a"])
                for ei, end in existing}
    crossings = controls["crossings"]
    cross_points = [Point(c[:2]) for c in crossings]
    cross_index = STRtree(cross_points)
    used_crossings = set()
    approaches = warnings = blocked = 0
    for node in sorted(lit):
        group = clusters.get(node, node)
        if group in reserved:
            continue
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
            point, heading, right = frame(line, stop)
            mesh = Mesh()
            mesh.poly(stroke(LineString([point + right * (lo + 0.2), point + right * (hi - 0.2)]), 0.34),
                      0.011, PAINT, lit=False)
            count = lane_count(edge, direction)
            supports = [point + right * (side * (width / 2 + 1.05)) for side in (-1, 1)]
            if count >= 2 and all(clear(*p) for p in supports):
                heads = [point + right * (lo + (hi - lo) * (lane + 0.5) / count) for lane in range(count)]
                draw_gantry(mesh, dict(supports=supports, heads=[{"position": p} for p in heads],
                                       clearance_m=GANTRY_CLEARANCE, facing=-heading), live=True)
                height = GANTRY_CLEARANCE
            else:
                back, _, back_right = frame(line, max(0.35, stop - 3))
                shoulders = [point + right * (width / 2 + 2.05), back + back_right * (width / 2 + 1.05)]
                side = next((p for p in (supports[1], *shoulders, supports[0]) if clear(*p)), None)
                heads = [] if side is None else [side]
                if side is not None:
                    draw_device(mesh, "vehicle_signal", side, -heading, live=True)
                else:
                    blocked += 1
                height = 2.78
            controls["signals"].append((phase_node, ei, end, ei * 2 + end, math.nan, math.nan,
                                        jx, jz, 0, line.length - stop))
            for x, z in heads:
                controls["heads"].append((phase_node, (ei, end), x, z, height, *(-heading)))
            if stop >= 12:
                p, h, r = frame(line, stop - min(18, stop - 1))
                sign = p + r * (width / 2 + 1.1)
                if clear(*sign):
                    draw_device(mesh, "signal_ahead", sign, -h)
                    warnings += 1
            # Preserve existing paint when a crossing matches. Add paint and runtime geometry together elsewhere.
            if width >= 4.5 and (cross or line.length >= 12):
                key = cross[1] if cross else (ei, round(zebra if end else line.length - zebra))
                if key not in used_crossings:
                    center, axis, right = frame(line, zebra)
                    pads = [center + right * (side * (width / 2 + 0.8)) for side in (-1, 1)]
                    if all(clear(*p) for p in pads):
                        if cross:
                            crossings[cross[1]] = (*crossings[cross[1]][:7], phase_node)
                        else:
                            for offset in np.arange(-width / 2 + 0.4, width / 2 - 0.2, 0.82):
                                p = center + right * offset
                                mesh.poly(stroke(LineString([p - axis * 1.55, p + axis * 1.55]), 0.44),
                                          0.011, PAINT, lit=False)
                            crossings.append((*center, *axis, width, 0, 0.0, phase_node))
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
