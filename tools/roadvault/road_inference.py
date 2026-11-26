"""Infer a road-candidate layout from local OSM topology and mapped controls."""
from collections import defaultdict
from dataclasses import dataclass
import math

import numpy as np
from shapely.errors import GEOSException
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

if __package__:
    from .road_candidate import compile_movements, crossing_span, edge_band, footprint, frame, lane_count, lane_turns, protected_median, polys
else:
    from road_candidate import compile_movements, crossing_span, edge_band, footprint, frame, lane_count, lane_turns, protected_median, polys

SIDEWALKS = {"primary", "secondary", "tertiary", "residential", "unclassified", "living_street", "trunk"}


def at_grade(tags):
    return tags.get("layer", "0") == "0" and all(tags.get(k, "no") == "no" for k in ("bridge", "tunnel"))


def normalize_ways(ways, shared_nodes):
    """Split shared interior nodes, keeping turn tags at the original travel ends."""
    normalized, originals = [], {}
    for way in sorted(ways, key=lambda way: way["id"]):
        nodes, geometry = way["nodes"], way["geometry"]
        start, last = 0, len(nodes) - 1
        shared = [i for i in range(1, last) if nodes[i] in shared_nodes]
        for end in [*shared, last]:
            tags = dict(way["tags"])
            if tags["highway"] == "motorway" and "oneway" not in tags:
                tags["oneway"] = "yes"
            if tags.get("junction") == "roundabout" and tags.get("oneway") in {"no", "0", "false"}:
                tags.pop("junction")
            if end != last:
                tags.pop("turn:lanes:forward", None)
                if tags.get("oneway") != "-1":
                    tags.pop("turn:lanes", None)
            if start != 0:
                tags.pop("turn:lanes:backward", None)
                if tags.get("oneway") == "-1":
                    tags.pop("turn:lanes", None)
            # Keep a stable segment identifier when the preview moves or is tiled.
            segment_id = way["id"] if not shared else 10_000_000_000_000 + way["id"] * 4096 + start
            normalized.append({**way, "id": segment_id, "nodes": nodes[start:end + 1],
                               "geometry": geometry[start:end + 1], "tags": tags})
            originals[segment_id] = way["id"]
            start = end
    return normalized, originals


@dataclass
class Arm:
    edge: object
    at_end: bool
    outward: np.ndarray

    @property
    def arrival(self):
        return 1 if self.at_end else -1

    @property
    def departure(self):
        return -self.arrival


def road_arms(edges):
    nodes = defaultdict(list)
    for edge in edges:
        for at_end in (False, True):
            station = edge.line.length if at_end else 0
            p, heading, _ = frame(edge.line, station)
            node = edge.nodes[-1 if at_end else 0]
            nodes[node].append((p, Arm(edge, at_end, -heading if at_end else heading)))
    return nodes


def restriction_rules(relations, originals_at_node, local_ways, report):
    """Apply direct via-node relations and withhold affected approaches for complex ones."""
    denied, allowed, withheld = defaultdict(set), defaultdict(set), set()
    for relation in relations:
        tags = relation.get("tags", {})
        if tags.get("type") not in {"restriction", "connectivity"}:
            continue
        roles = defaultdict(list)
        for member in relation.get("members", ()):
            roles[member["role"]].append((member["type"], member["ref"]))
        incoming = {ref for kind, ref in roles["from"] if kind == "way"} & local_ways
        if not incoming:
            continue
        restriction = tags.get("restriction", "")
        single = all(len(roles[k]) == 1 for k in ("from", "via", "to"))
        if single and restriction == "no_u_turn" and roles["from"] == roles["to"]:
            continue
        if (single and roles["via"][0][0] == "node" and roles["to"][0][0] == "way"
                and restriction.startswith(("no_", "only_"))
                and not any(key.startswith("restriction:") for key in tags)
                and not tags.get("except")):
            key = (roles["via"][0][1], next(iter(incoming)))
            rules = denied if restriction.startswith("no_") else allowed
            rules[key].add(roles["to"][0][1])
            continue
        report.append(dict(kind="unsupported_relation", relation=relation["id"], relation_type=tags["type"]))
        via_nodes = {ref for kind, ref in roles["via"] if kind == "node"}
        via_ways = {ref for kind, ref in roles["via"] if kind == "way"}
        for node, ways in originals_at_node.items():
            if node in via_nodes or ways & via_ways or not roles["via"]:
                withheld.update((node, way) for way in incoming & ways)
    return denied, allowed, withheld


def turn_kind(angle):
    if abs(angle) <= 35:
        return "through"
    return "right" if angle > 0 else "left"


def mapped_kind(turn):
    return "left" if turn.endswith("left") else "right" if turn.endswith("right") else turn


def lane_pairs(source, target, turn, continuation, fork_lanes=None):
    incoming = lane_count(source.edge.section, source.arrival)
    outgoing = lane_count(target.edge.section, target.departure)
    tags = lane_turns(source.edge.section, source.arrival)
    default = range(incoming) if turn == "through" or continuation else (0,) if turn == "left" else (incoming - 1,)
    if fork_lanes is not None:
        default = fork_lanes
    choices = []
    for i in range(incoming):
        marked = tags[i] if tags else ()
        match = sorted(tag for tag in marked if mapped_kind(tag) == turn)
        if match or (not marked and i in default):
            choices.append((i, match[0] if match else turn))
    # Preserve lane order. Use the inside lane for a left turn and the outside lane
    # for a right turn when the receiving section has spare lanes.
    base = max(0, outgoing - len(choices)) if turn == "right" else 0
    taper = target.edge.section.get("lane_taper")
    if (turn == "through" and taper and taper[0] == "start" and taper[2] == "left"
            and target.departure == 1 and outgoing == incoming + 1):
        base = 1
    for rank, (i, indication) in enumerate(choices):
        j = min(outgoing - 1, base + rank * min(len(choices), outgoing) // len(choices))
        yield i, j, indication


def sidewalk_sides(tags):
    sidewalk = tags.get("sidewalk", "")
    sides = {
        "both": ("sidewalk", "sidewalk"), "yes": ("sidewalk", "sidewalk"),
        "left": ("sidewalk", "curb"), "right": ("curb", "sidewalk"),
        "no": ("curb", "curb"), "none": ("curb", "curb"),
    }
    result = list(sides.get(sidewalk, ("sidewalk", "sidewalk") if tags["highway"] in SIDEWALKS else (None, None)))
    for i, side in enumerate(("left", "right")):
        flag = tags.get("sidewalk:" + side, tags.get("sidewalk:both"))
        if flag in {"yes", "separate", "no", "none"}:
            result[i] = "sidewalk" if flag in {"yes", "separate"} else "curb"
    return result[::-1] if tags.get("oneway") == "-1" else result


def paired_medians(edges, tags_by_edge, road_edges):
    """Recognize opposite, same-corridor one-ways with room for a median between them."""
    corridors = defaultdict(list)
    for edge in edges:
        tags = tags_by_edge[edge.id]
        identity = (tags.get("ref") or tags.get("name") or "").strip().casefold()
        if identity and edge.section["ow"] and edge.line.length >= 20:
            corridors[identity].append(edge)
    pairs = []
    for group in corridors.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                short, long = sorted((a, b), key=lambda edge: edge.line.length)
                good = 0
                for fraction in (0.2, 0.5, 0.8):
                    point, heading, right = frame(short.line, short.line.length * fraction)
                    s = long.line.project(Point(point))
                    if not 1 < s < long.line.length - 1:
                        continue
                    opposite, other_heading, other_right = frame(long.line, s)
                    delta = opposite - point
                    separation = np.linalg.norm(delta)
                    median = separation - (short.section["w"] + long.section["w"]) / 2
                    if (heading @ other_heading < -0.9 and delta @ right < -0.85 * separation
                            and delta @ other_right > 0.85 * separation and 1.1 <= median <= 16):
                        good += 1
                if good >= 2:
                    pairs.append([[a.id], [-b.id]])
                    road_edges[str(a.id)][0] = road_edges[str(b.id)][0] = "curb"
    return pairs


def fork_allocations(source, targets):
    """Reserve a separate lane for a mapped link when the lane counts balance."""
    if len(targets) != 2 or not source.edge.section["ow"]:
        return {}
    links = [(angle, arm) for angle, arm in targets if arm.edge.section["cls"].endswith("_link")]
    if len(links) != 1:
        return {}
    angle, slip = links[0]
    main_angle, main = next(item for item in targets if item[1] is not slip)
    slip_count = lane_count(slip.edge.section, slip.departure)
    main_count = lane_count(main.edge.section, main.departure)
    if slip_count + main_count != lane_count(source.edge.section, source.arrival):
        return {}
    if angle < main_angle:
        return {slip.edge.id: range(slip_count), main.edge.id: range(slip_count, slip_count + main_count)}
    return {main.edge.id: range(main_count), slip.edge.id: range(main_count, main_count + slip_count)}


def slip_sidewalk_curves(edges, node_arms, road_edges):
    """Apply the shared outer-edge blend to unambiguous right-hand slip lanes."""
    curves = []
    for edge in edges:
        if not edge.section["ow"] or not edge.section["cls"].endswith("_link") or edge.line.length < 15:
            continue
        split = [arm for _, arm in node_arms[edge.nodes[0]] if arm.edge is not edge]
        merge = [arm for _, arm in node_arms[edge.nodes[-1]] if arm.edge is not edge]
        incoming = [arm for arm in split if arm.at_end and arm.edge.section["ow"]]
        continuing = [arm for arm in split if not arm.at_end and arm.edge.section["ow"]]
        feeding = [arm for arm in merge if arm.at_end and arm.edge.section["ow"]]
        receiving = [arm for arm in merge if not arm.at_end and arm.edge.section["ow"]]
        if any(len(arms) != 1 for arms in (incoming, continuing, feeding, receiving)):
            continue
        source, main, feed, target = (arms[0].edge for arms in (incoming, continuing, feeding, receiving))
        _, _, right = frame(source.line, source.line.length)
        if (np.array(edge.line.interpolate(6).coords[0]) - np.array(main.line.interpolate(6).coords[0])) @ right <= 0:
            continue
        _, _, right = frame(target.line, 0)
        if (np.array(edge.line.interpolate(edge.line.length - 6).coords[0])
                - np.array(feed.line.interpolate(feed.line.length - 6).coords[0])) @ right <= 0:
            continue
        if any(road_edges[str(way.id)][1] != "sidewalk" for way in (source, target)):
            continue
        before, after = min(12, source.line.length / 4), min(16, target.line.length / 4)
        if min(before, after) < 5:
            continue
        road_edges[str(edge.id)] = ["curb", "sidewalk"]
        curves.append([source.id, target.id, before, after, 1.35 * (edge.line.length + before + after)])
    return curves


def lane_transition_profiles(node_arms, tags_by_edge, bounds, layout):
    """Taper a single-lane change on a straight continuation of the same road."""
    profiles = {}
    for hits in node_arms.values():
        if not 2 <= len(hits) <= 3 or not bounds.covers(Point(hits[0][0])):
            continue
        main = [arm for _, arm in hits if not arm.edge.section["cls"].endswith("_link")]
        if len(main) != 2:
            continue
        narrow, wide = sorted(main, key=lambda arm: arm.edge.section["lanes"])
        if len(hits) == 3:
            branch = next(arm for _, arm in hits if arm.edge.section["cls"].endswith("_link"))
            # The extra lane in a balanced split or merge already belongs to the link.
            if branch.at_end != wide.at_end:
                continue
        a, b = narrow.edge, wide.edge
        name = tags_by_edge[a.id].get("name")
        if (not name or name != tags_by_edge[b.id].get("name") or not a.section["ow"] or not b.section["ow"]
                or narrow.at_end == wide.at_end or narrow.outward @ wide.outward > -0.94
                or b.section["lanes"] - a.section["lanes"] not in (1, 2) or b.id in profiles):
            continue
        extra = b.section["w"] - a.section["w"]
        if not 2 <= extra <= 7 or b.line.length < 7:
            continue
        end = "end" if wide.at_end else "start"
        length = min(25, b.line.length - 1)
        entry = [end, length, extra / 2, -extra / 2]
        b.section.setdefault("tapers", []).append(entry)
        turns = lane_turns(b.section)
        side = "right" if turns and any(t.endswith("right") for t in turns[-1]) and not (
            turns[0] and any(t.endswith("left") for t in turns[0])) else "left"
        if b.section["lanes"] - a.section["lanes"] == 2:
            side = "both"
        b.section["lane_taper"] = [end, length, side]
        profiles[b.id] = [end, length, side]
        layout.setdefault("tapers", {}).setdefault(str(b.id), []).append(entry)
    layout["lane_tapers"] = {str(edge): profile for edge, profile in profiles.items()}
    return profiles


def align_paired_zebras(layout, by_id):
    pairs = {frozenset((abs(a), abs(b))) for near, far in layout["median_corridors"] for a in near for b in far}
    for group in layout["crossings"]:
        for first, second in zip(group, group[1:]):
            if frozenset((first[0], second[0])) not in pairs:
                continue
            a, b = by_id[first[0]], by_id[second[0]]
            p, da, _ = frame(a.line, first[1])
            q, db, _ = frame(b.line, second[1])
            if da @ db > -0.85:
                continue
            center = Point((p + q) / 2)
            new = (a.line.project(center), b.line.project(center))
            if all(3 <= station <= edge.line.length - 3 and abs(station - old[1]) <= 6
                   for edge, station, old in zip((a, b), new, (first, second))):
                first[1], second[1] = (round(station, 3) for station in new)


def append_crossings(layout, edges, node_tags, crossing_guides, bounds, report):
    """Use mapped crossing nodes/ways with enough road run on both sides for a zebra."""
    used = set()
    mapped = set()
    for node, tags in node_tags.items():
        crossing = tags.get("crossing")
        if (tags.get("highway") == "crossing" and crossing not in {"unmarked", "no"}
                and tags.get("crossing:markings") != "no"):
            mapped.add(node)
    for guide in (*crossing_guides, *sorted(mapped)):
        touches = []
        for edge in edges:
            if isinstance(guide, int):
                if guide not in edge.nodes[1:-1]:
                    continue
                points = [node_tags[guide]["point"]]
            else:
                hit = edge.line.intersection(guide)
                points = [point for point in getattr(hit, "geoms", (hit,)) if point.geom_type == "Point"]
            for point in points:
                at = edge.line.project(point)
                if (3 <= at <= edge.line.length - 3 and edge.id not in used
                        and bounds.buffer(-2).covers(edge.line.interpolate(at))):
                    touches.append((edge.id, at, guide.project(point) if not isinstance(guide, int) else 0))
        group = []
        for edge, at, _ in sorted(touches, key=lambda item: item[2]):
            if edge not in used:
                used.add(edge)
                group.append([edge, round(at, 3)])
        if group:
            layout["crossings"].append(group)
        else:
            report.append(dict(kind="crossing_needs_review", node=guide if isinstance(guide, int) else None))


def infer_layout(layout, edges, ways, originals, node_tags, relations, crossing_guides, bounds, report):
    """Compile local topology into the same layout consumed by the authored junction."""
    by_id = {edge.id: edge for edge in edges}
    tags_by_edge = {way["id"]: way["tags"] for way in ways if way["id"] in by_id}
    layout.update(source="osm-topology", road_edges={str(edge): sidewalk_sides(tags) for edge, tags in tags_by_edge.items()},
                  corner_zones=[], unmarked=[], crossings=[], stop_lines=[], movements=[])
    relevant_nodes = road_arms(edges)
    profiles = lane_transition_profiles(relevant_nodes, tags_by_edge, bounds, layout)
    layout["median_corridors"] = paired_medians(edges, tags_by_edge, layout["road_edges"])
    for edge, tags in tags_by_edge.items():
        if tags["highway"] in {"primary_link", "secondary_link", "tertiary_link"} and by_id[edge].section["ow"]:
            if tags.get("sidewalk", "") not in {"no", "none"}:
                layout["road_edges"][str(edge)] = ["curb", "sidewalk"]
    layout["sidewalk_curves"] = slip_sidewalk_curves(edges, relevant_nodes, layout["road_edges"])
    ways_at_node = {node: {originals[arm.edge.id] for _, arm in hits} for node, hits in relevant_nodes.items()}
    denied, allowed, withheld = restriction_rules(relations, ways_at_node, set(originals.values()), report)
    restricted_edges = set()
    for edge, tags in tags_by_edge.items():
        access = tags.get("motor_vehicle", tags.get("vehicle", tags.get("access")))
        if (tags.get("lanes:both_ways") or tags.get("oneway") in {"reversible", "alternating"}
                or (tags.get("lanes") == "1" and not by_id[edge].section["ow"])
                or access in {"no", "private"}):
            restricted_edges.add(edge)
            report.append(dict(kind="unmodeled_lane_or_access", way=originals[edge]))
    raw_pavement = unary_union([poly for edge in edges for poly in polys(footprint(edge))])
    frontage = raw_pavement.buffer(3.5)
    divider = protected_median(by_id, layout, raw_pavement, bounds)
    trim = defaultdict(lambda: [0.0, 0.0])
    control_nodes = []
    for node, hits in sorted(relevant_nodes.items()):
        center = Point(hits[0][0])
        if not bounds.covers(center):
            continue
        arms = [arm for _, arm in hits if arm.edge.id not in restricted_edges]
        if len(arms) < 2:
            continue
        if node_tags.get(node, {}).get("highway") in {"traffic_signals", "stop", "give_way"}:
            control_nodes.append((node, node_tags[node]["highway"], arms))
        setback = max(4.5, max(arm.edge.section["w"] for arm in arms) * 0.65)
        if len(arms) >= 3:
            layout["corner_zones"].append([center.x, center.y, setback * 1.4])
            for arm in arms:
                trim[arm.edge.id][int(arm.at_end)] = min(setback, arm.edge.line.length * 0.45)
        for source in arms:
            if source.arrival == -1 and source.edge.section["ow"]:
                continue
            key = node, originals[source.edge.id]
            if key in withheld:
                continue
            targets = []
            for target in arms:
                if target is source or (target.departure == -1 and target.edge.section["ow"]):
                    continue
                target_way = originals[target.edge.id]
                if target_way in denied[key] or (key in allowed and target_way not in allowed[key]):
                    continue
                incoming = -source.outward
                outgoing = target.outward
                angle = math.degrees(math.atan2(incoming[0] * outgoing[1] - incoming[1] * outgoing[0],
                                                incoming @ outgoing))
                if abs(angle) < 155:
                    targets.append((angle, target))
            straight = min(targets, default=None, key=lambda target: abs(target[0]))
            allocations = fork_allocations(source, targets)
            for angle, target in targets:
                same_way = originals[source.edge.id] == originals[target.edge.id]
                continuation = len(arms) == 2 and not lane_turns(source.edge.section, source.arrival)
                turn = "through" if continuation or same_way else turn_kind(angle)
                if not same_way and turn == "through" and target is not straight[1]:
                    turn = "right" if angle > 0 else "left"
                pairs = list(lane_pairs(source, target, turn, continuation, allocations.get(target.edge.id)))
                if (continuation and lane_count(source.edge.section, source.arrival)
                        != lane_count(target.edge.section, target.departure)
                        and source.edge.id not in profiles and target.edge.id not in profiles):
                    report.append(dict(kind="lane_transition_needs_review", node=node, source=source.edge.id,
                                       target=target.edge.id))
                lane_width = min(source.edge.section["w"] / source.edge.section["lanes"],
                                 target.edge.section["w"] / target.edge.section["lanes"])
                specs = [dict(id=f"{node}/{source.edge.id}/{source.arrival}/{i}/{target.edge.id}/{target.departure}/{j}",
                              node=node, **{"from": source.edge.id, "to": target.edge.id},
                              from_direction=source.arrival, to_direction=target.departure,
                              from_lane=i, to_lane=j, via=[], turn=indication, setback=setback,
                              sweep_width=max(0.5, min(2.94, lane_width - 0.2)), control="inferred")
                         for i, j, indication in pairs]
                if not specs:
                    continue
                for handle in (0.36, 0.26, 0.46):
                    candidate = [{**spec, "handle": handle} for spec in specs]
                    try:
                        paths = compile_movements(by_id, candidate)
                        fits = all(line.is_simple and bounds.covers(line) and frontage.covers(line)
                                   and line.buffer(spec["sweep_width"] / 2, cap_style="flat").intersection(divider).area < 0.01
                                   for spec, line in paths)
                    except (ValueError, GEOSException):
                        fits = False
                    if fits:
                        layout["movements"].extend(candidate)
                        break
                else:
                    report.append(dict(kind="connector_needs_review", node=node, source=source.edge.id, target=target.edge.id))
    layout["unmarked"] = [[edge, start, by_id[edge].line.length - end] for edge, (start, end) in trim.items()]
    append_crossings(layout, edges, node_tags, crossing_guides, bounds, report)
    # At substantial junctions, connect the road-owned sidewalks even where OSM
    # contains no explicitly mapped crossing node or crossing footway.
    used = {way for group in layout["crossings"] for way, _ in group}
    mapped_ways = set(used)
    crossing_points = [frame(by_id[way].line, station)[:2]
                       for group in layout["crossings"] for way, station in group]
    holes = [Polygon(ring) for polygon in polys(raw_pavement) for ring in polygon.interiors
             if Polygon(ring).area >= 15]
    slip_islands = []
    for island in holes:
        candidates = []
        for edge in edges:
            if (not edge.section["ow"] or edge.section["cls"] not in {"primary_link", "secondary_link", "tertiary_link"}
                    or layout["road_edges"].get(str(edge.id), (None, None))[1] != "sidewalk"):
                continue
            boundary = island.boundary.intersection(edge_band(edge, "left", 0.55).buffer(1))
            segments = [part for part in getattr(boundary, "geoms", (boundary,))
                        if part.geom_type == "LineString" and part.length >= 3]
            if segments:
                segment = max(segments, key=lambda part: part.length)
                at = edge.line.project(segment.interpolate(0.5, normalized=True))
                if 3 <= at <= edge.line.length - 3:
                    candidates.append((segment.length, edge, at))
        if not candidates:
            continue
        slip_islands.append(island)
        if any(edge.id in used and any(way == edge.id and island.distance(edge.line.interpolate(at)) <= edge.section["w"]
                                      for group in layout["crossings"] for way, at in group)
               for _, edge, _ in candidates):
            continue
        for _, edge, station in sorted(candidates, key=lambda item: -item[0]):
            if edge.id not in used and bounds.buffer(-2).covers(edge.line.interpolate(station)):
                layout["crossings"].append([[edge.id, round(station, 3)]])
                used.add(edge.id)
                crossing_points.append(frame(edge.line, station)[:2])
                break
    for node, hits in sorted(relevant_nodes.items()):
        arms = [arm for _, arm in hits if arm.edge.id not in restricted_edges]
        if len(arms) < 3 or not bounds.buffer(-8).covers(Point(hits[0][0])):
            continue
        if sum(arm.edge.section["cls"].removesuffix("_link") in SIDEWALKS for arm in arms) < 2:
            continue
        for arm in arms:
            edge = arm.edge
            tags = tags_by_edge[edge.id]
            if (edge.id in used or edge.line.length < 16
                    or tags.get("crossing") in {"no", "unmarked"}
                    or tags.get("foot") in {"no", "private"}
                    or edge.section["cls"].removesuffix("_link") not in SIDEWALKS):
                continue
            distance = max(12, edge.section["w"] * 0.9)
            station = edge.line.length - distance if arm.at_end else distance
            point, heading, _ = frame(edge.line, station)
            junction = hits[0][0]
            def clear_crossing(other, direction):
                delta = point - other
                distance = np.linalg.norm(delta)
                opposite_sides = (point - junction) @ (other - junction) < 0
                return distance >= 8 and (distance >= 25 or opposite_sides or abs(heading @ direction) < 0.85
                                           or abs(delta @ heading) < 4)
            if (3 <= station <= edge.line.length - 3 and bounds.buffer(-2).covers(Point(point))
                    and all(clear_crossing(other, direction) for other, direction in crossing_points)):
                layout["crossings"].append([[edge.id, round(station, 3)]])
                used.add(edge.id)
                crossing_points.append((point, heading))
    # A crossing of a divided boulevard should continue across the opposing
    # carriageway and cut through the median as one pedestrian route.
    removed_groups = set()
    for group_index, group in enumerate(layout["crossings"]):
        if group_index in removed_groups:
            continue
        if len(group) != 1:
            continue
        way, station = group[0]
        partner_ids = []
        for near, far in layout["median_corridors"]:
            if way in map(abs, near):
                partner_ids.extend(map(abs, far))
            elif way in map(abs, far):
                partner_ids.extend(map(abs, near))
        edge = by_id[way]
        point, heading, _ = frame(edge.line, station)
        for partner_id in partner_ids:
            partner = by_id[partner_id]
            at = partner.line.project(Point(point))
            other, direction, _ = frame(partner.line, at)
            if (3 <= at <= partner.line.length - 3 and heading @ direction < -0.85
                    and np.linalg.norm(other - point) < 35
                    and bounds.buffer(-2).covers(Point(other))):
                if partner_id in used:
                    match = next((i for i, other_group in enumerate(layout["crossings"])
                                  if i != group_index and i not in removed_groups and len(other_group) == 1
                                  and other_group[0][0] == partner_id and abs(other_group[0][1] - at) <= 8), None)
                    if match is None:
                        continue
                    removed_groups.add(match)
                group.append([partner_id, round(at, 3)])
                used.add(partner_id)
                break
    layout["crossings"] = [group for i, group in enumerate(layout["crossings"]) if i not in removed_groups]
    sidewalk_bands = [edge_band(by_id[int(way)], side, 2.4)
                      for way, sides in layout["road_edges"].items()
                      for side, feature in zip(("left", "right"), sides) if feature == "sidewalk"]
    walkable = unary_union([*sidewalk_bands, *[hole for hole in holes if hole.area < 190],
                            *slip_islands]).difference(raw_pavement)
    connected = []
    for group in layout["crossings"]:
        valid = True
        for item in group:
            way, station = item
            edge = by_id[way]
            direction = 1 if station < edge.line.length / 2 else -1
            shifts = (0,) if len(group) > 1 else (0, 2, -2, 4, -4) if way in mapped_ways else (0, 3, -3, 6, -6, 9, -9, 12, 15)
            if edge.section["cls"].endswith("_link"):
                shifts = (0, 1, -1, 2, -2, 3, -3, 4, -4)
            found = None
            for shift in shifts:
                at = station + direction * shift
                if not 3 <= at <= edge.line.length - 3 or not bounds.buffer(-2).covers(edge.line.interpolate(at)):
                    continue
                try:
                    point, _, right, lo, hi = crossing_span(edge, at, raw_pavement)
                except ValueError:
                    continue
                landings = [Point(point + right * lateral) for lateral in (lo - 0.25, hi + 0.25)]
                if all(walkable.distance(landing) <= 1.5 or
                       (len(group) > 1 and divider.distance(landing) <= 2) for landing in landings):
                    found = round(at, 3)
                    break
            if found is None:
                valid = False
                break
            item[1] = found
        if valid:
            connected.append(group)
        else:
            report.append(dict(kind="crossing_without_walkable_landing", ways=[way for way, _ in group]))
    layout["crossings"] = connected
    align_paired_zebras(layout, by_id)
    stations = dict(item for group in layout["crossings"] for item in group)
    layout["pedestrian_signals"] = []
    for node, control, arms in control_nodes:
        approaches = [arm for arm in arms if arm.arrival == 1 or not arm.edge.section["ow"]]
        covered = []
        if control == "traffic_signals":
            for arm in approaches:
                edge = arm.edge
                if (edge.section["ow"] and arm.at_end and edge.id in stations
                        and 7 <= stations[edge.id] <= edge.line.length - 4
                        and edge.line.length - stations[edge.id] <= 35):
                    layout["stop_lines"].append(edge.id)
                    layout["pedestrian_signals"].append(edge.id)
                    covered.append(edge.id)
        if len(covered) != len(approaches) or not covered:
            report.append(dict(kind="control_needs_layout", node=node, control=control))
    layout["approach_arrows"] = []
    layout["yield_lines"] = []
    layout["signs"] = []
    seen = set()
    for node, hits in sorted(relevant_nodes.items()):
        arms = [arm for _, arm in hits if arm.edge.id not in restricted_edges]
        if len(arms) < 3 or not bounds.buffer(-8).covers(Point(hits[0][0])):
            continue
        for arm in arms:
            edge, direction = arm.edge, arm.arrival
            if (edge.section["ow"] and direction != 1) or edge.line.length < 12:
                continue
            key = edge.id, direction
            if key in seen:
                continue
            seen.add(key)
            crossing = stations.get(edge.id)
            setback = max(7, edge.section["w"] * 0.65)
            station = (crossing - 8 if direction == 1 else crossing + 8) if crossing is not None else (
                edge.line.length - setback - 5 if direction == 1 else setback + 5)
            if 2.5 <= station <= edge.line.length - 2.5 and edge.id not in layout["stop_lines"]:
                layout["approach_arrows"].append([edge.id, round(station, 3), direction])
            if edge.section["cls"].endswith("_link") and edge.section["ow"] and arm.at_end:
                at = edge.line.length - min(3, edge.line.length * 0.2)
                layout["yield_lines"].append([edge.id, round(at, 3)])
                layout["signs"].append(["give_way", edge.id, round(at, 3), "right"])
        for arm in arms:
            if arm.edge.id in stations and arm.edge.section["ow"] and arm.at_end:
                layout["signs"].append(["crossing", arm.edge.id, round(max(1, stations[arm.edge.id] - 4), 3), "right"])
    for edge in edges:
        if edge.line.length >= 16:
            for side in edge.section.get("cycle_sides", ()):
                layout["signs"].append(["cycleway", edge.id, 5, side])
    return layout
