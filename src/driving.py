"""Shared route costs and longitudinal speed limits for AI drivers."""
import heapq
import math

from roadwidth import lane_count, lane_turns

SIGNAL_STOP_BUFFER = 3.0


def brake_speed(distance, decel, end_speed=0.0):
    return math.sqrt(end_speed * end_speed + 2.0 * decel * max(0.0, distance))


def follow_speed(gap, lead_speed):
    """Close a gap smoothly while retaining room to brake after the leader."""
    gap = max(0.0, gap - 2.2)
    brake = 4.0
    reaction = 1.35
    safe = math.sqrt((brake * reaction) ** 2 + lead_speed ** 2 + 2.0 * brake * gap) - brake * reaction
    approach = lead_speed + (gap - reaction * lead_speed) / 2.2
    return max(0.0, min(safe, approach))


def road_control_speed(sim, x, y, heading, front, speed):
    """Brake for traffic lights and closed rail gates when following a waypoint route."""
    limit = math.inf
    lights = getattr(sim, "lights", None)
    if lights is not None:
        distance = lights.red_ahead(x, y, heading, front=front, speed=speed)
        if distance is not None:
            limit = brake_speed(distance, 2.8)
    trains = getattr(sim, "trains", None)
    if trains is not None and trains.closed:
        hx, hy = math.cos(heading), math.sin(heading)
        for ei, s in trains.closed:
            edge = sim.w.edges[ei]
            cx, cy, ax, ay = sim.w.edge_point(edge, s)
            dx, dy = cx - x, cy - y
            dot = ax * hx + ay * hy
            distance = dx * hx + dy * hy
            if (dot > 0.8 or (not edge["ow"] and dot < -0.8)) and -1.0 < distance < 65.0:
                if abs(dy * ax - dx * ay) < edge["w"] / 2 + 0.75:
                    limit = min(limit, brake_speed(distance - front - 5.5, 2.8))
    return limit


def turn_angle(edges, incoming, outgoing):
    headings = []
    for (ei, direction), arriving in ((incoming, True), (outgoing, False)):
        pts = edges[ei]["pts"]
        a, b = pts[-2:] if arriving == (direction == 1) else pts[:2]
        headings.append(math.atan2((b[1] - a[1]) * direction, (b[0] - a[0]) * direction))
    return (headings[1] - headings[0] + math.pi) % (2.0 * math.pi) - math.pi


def turn_lanes(edge, direction, angle):
    """Legal indices on a tagged approach, or None when its arrows are unspecified."""
    marked = lane_turns(edge, direction)
    if not any(marked):
        return None
    move = "reverse" if abs(angle) > 2.2 else "right" if angle >= 0.5 else "left" if angle <= -0.5 else "through"
    return [i for i, kinds in enumerate(marked) if not kinds or move in kinds or "slight_" + move in kinds
            or "sharp_" + move in kinds or (move == "through" and bool(kinds & {"merge_to_left", "merge_to_right"}))]


def edge_seconds(edge, direction, speed_cap, queue):
    speed = max(1.0, min(edge["speed"], speed_cap))
    return edge["len"] / speed + 4.0 * queue / lane_count(edge, direction)


def fastest_route(world, start, goal, goal_xy, *, incoming=None, delay=None, speed_cap=27.0, budget=None,
                  first=None, main_only=False):
    """A* in travel seconds over directed edges, retaining the approach for turn costs."""
    if start == goal:
        return ()
    initial = (start, incoming)
    best, prev = {initial: 0.0}, {}
    todo = [(0.0, 0.0, start, incoming or (-1, 0))]
    while todo:
        _, cost, node, approach = heapq.heappop(todo)
        state = (node, approach if approach[0] >= 0 else None)
        if cost != best.get(state):
            continue
        if node == goal:
            path = []
            while state != initial:
                path.append(state[1])
                state = prev[state]
            return tuple(reversed(path))
        if budget is not None:
            if not budget:
                break
            budget -= 1
        for move in world.out.get(node, ()):
            ei, direction = move
            if ei == approach[0] or (state == initial and first is not None and move not in first):
                continue
            e = world.edges[ei]
            end = e["b"] if direction == 1 else e["a"]
            if main_only and end not in world.main:
                continue
            angle = turn_angle(world.edges, approach, move) if approach[0] >= 0 else 0.0
            if abs(angle) > 2.2 or (approach[0] >= 0 and turn_lanes(world.edges[approach[0]], approach[1], angle) == []):
                continue
            wait = delay(move) if delay else 0.0
            nd = cost + edge_seconds(e, direction, speed_cap, 0) + wait + abs(angle) * 1.4 + (1.0 if angle < -0.5 else 0.0)
            nxt = (end, move)
            if nd >= best.get(nxt, math.inf):
                continue
            best[nxt], prev[nxt] = nd, state
            x, y = e["pts"][-1 if direction == 1 else 0]
            estimate = math.hypot(x - goal_xy[0], y - goal_xy[1]) / speed_cap
            heapq.heappush(todo, (nd + estimate, nd, end, move))
    return None
