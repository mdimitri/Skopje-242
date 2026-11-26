"""Shared route costs and longitudinal speed limits for AI drivers."""
import heapq
import math

from roadwidth import lane_count, lane_turns

SIGNAL_STOP_BUFFER = 3.0
TRAFFIC_SPEED_FACTOR = 1.10


def corridor_entry(x, y, vx, vy, half_length, half_width, horizon):
    """First intersection of relative linear motion with an axis-aligned box."""
    lo, hi = 0.0, horizon
    for pos, speed, half in ((x, vx, half_length), (y, vy, half_width)):
        if abs(speed) < 1e-6:
            if abs(pos) > half:
                return None
            continue
        a, b = (-half - pos) / speed, (half - pos) / speed
        lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
        if lo > hi:
            return None
    return lo


def turn_indicator(angle, distance, speed):
    """Signal a meaningful upcoming turn within a few seconds of reaching it."""
    if abs(angle) >= 0.45 and 0.0 <= distance <= max(13.0, min(40.0, speed * 3.0)):
        return 1 if angle > 0.0 else -1
    return 0


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


def _heading(edges, move, arriving):
    ei, direction = move
    pts = edges[ei]["pts"]
    a, b = (pts[-2], pts[-1]) if arriving == (direction == 1) else (pts[0], pts[1])
    return math.atan2((b[1] - a[1]) * direction, (b[0] - a[0]) * direction)


def turn_angle(edges, incoming, outgoing):
    return (_heading(edges, outgoing, False) - _heading(edges, incoming, True) + math.pi) % (2.0 * math.pi) - math.pi


def turn_lanes(edge, direction, angle):
    """Legal indices on a tagged approach, or None when its arrows are unspecified."""
    marked = lane_turns(edge, direction)
    if not any(marked):
        return None
    move = "reverse" if abs(angle) > 2.2 else "right" if angle >= 0.5 else "left" if angle <= -0.5 else "through"
    lanes = [i for i, kinds in enumerate(marked) if not kinds or move in kinds or "slight_" + move in kinds
             or "sharp_" + move in kinds or (move == "through" and bool(kinds & {"merge_to_left", "merge_to_right"}))]
    if move == "through" and 0 not in lanes and marked[0] <= {"left", "slight_left", "sharp_left", "reverse"}:
        lanes.insert(0, 0)                    # the leftmost lane may turn left and still carries on straight: it keeps its lane
    return lanes


def _slip_bypasses(world):
    """Find right turns duplicated by a short one-way link around the junction."""
    edges, out = world.edges, world.out
    slips = {i for i, e in enumerate(edges) if e["drive"] and e["ow"] and e["cls"].endswith("_link")}
    forks = {}
    for i in slips:
        e = edges[i]
        start, end, length = e["a"], e["b"], e["len"]
        if not any(j not in slips for j, _ in out.get(start, ())):
            continue
        last = i
        visited = {start}
        while end not in visited and length <= 105.0:
            visited.add(end)
            exits = out.get(end, ())
            if any(j not in slips for j, _ in exits):
                forks.setdefault(start, []).append((i, last, end))
                break
            if len(exits) != 1:
                break
            last, _ = exits[0]
            length += edges[last]["len"]
            end = edges[last]["b"]

    banned = set()
    for i, edge in enumerate(edges):
        if not edge["drive"] or i in slips:
            continue
        for d, node in ((1, edge["b"]), (-1, edge["a"])):
            if d == -1 and edge["ow"]:
                continue
            incoming = (i, d)
            heading = _heading(edges, incoming, True)
            for slip, last, merge in forks.get(node, ()):
                bearing = turn_angle(edges, incoming, (slip, 1))
                bend = math.remainder(_heading(edges, (last, 1), True) - heading, math.tau)
                if not (0.20 < bearing < 1.7 and 0.55 < bend < 2.2):
                    continue
                todo = [(0.0, node, incoming, ())]
                seen = set()
                while todo:
                    cost, at, prev, path = heapq.heappop(todo)
                    if at == merge:
                        banned.update((a, b) for a, b in zip((incoming,) + path, path)
                                      if turn_angle(edges, a, b) >= 0.5)
                        break
                    if prev in seen or len(path) >= 8:
                        continue
                    seen.add(prev)
                    for move in out.get(at, ()):
                        j, direction = move
                        road = edges[j]
                        length = cost + road["len"]
                        if j == prev[0] or j in slips or length > 115.0 or road["cls"] == "service":
                            continue
                        if -0.5 < turn_angle(edges, prev, move) < 2.2:
                            heapq.heappush(todo, (length, road["b" if direction == 1 else "a"], move, path + (move,)))
    return banned


def right_slip(world, incoming, outgoing, angle):
    """A right-hand link can leave at a shallow angle beside the main road."""
    edge = world.edges[outgoing[0]]
    if not edge["ow"] or not edge["cls"].endswith("_link"):
        return False
    if angle > 0.20:
        return True
    source = world.edges[incoming[0]]
    node = source["b" if incoming[1] == 1 else "a"]
    other = [turn_angle(world.edges, incoming, move) for move in world.out.get(node, ())
             if move[0] not in (incoming[0], outgoing[0])
             and not world.edges[move[0]]["cls"].endswith("_link")]
    return -0.35 < angle <= 0.20 and any(abs(a) < 0.35 and angle - a > 0.05 for a in other)


def movement_lanes(world, incoming, outgoing, angle):
    """Legal lane indices for a graph movement, including the slip-road bypass rule."""
    edge, direction = world.edges[incoming[0]], incoming[1]
    next_edge = world.edges[outgoing[0]]
    slip = right_slip(world, incoming, outgoing, angle)
    if abs(angle) > 2.2:
        return [0]
    if angle >= 0.5 or slip:
        bypasses = getattr(world, "_slip_bypasses", None)
        if bypasses is None:
            bypasses = world._slip_bypasses = _slip_bypasses(world)
        if (incoming, outgoing) in bypasses:
            return []
        lanes = turn_lanes(edge, direction, max(0.5, angle))
        curb = lane_count(edge, direction) - 1
        if lanes is None:
            return [curb]
        return [curb] if slip else lanes
    lanes = turn_lanes(edge, direction, angle)
    if angle <= -0.5:
        return [0] if lanes is None else lanes
    if lanes is None or abs(angle) >= 0.35 or next_edge["cls"] != edge["cls"]:
        return lanes
    # Paint can describe the next junction even when an intermediate graph node splits the approach.
    node = edge["b" if direction == 1 else "a"]
    options = [turn_angle(world.edges, incoming, move) for move in world.out.get(node, ()) if move[0] != incoming[0]]
    for i, kinds in enumerate(lane_turns(edge, direction)):
        if i in lanes or not kinds:
            continue
        if (kinds <= {"left", "slight_left", "sharp_left"} and not any(-2.2 <= a <= -0.5 for a in options)
                or kinds <= {"right", "slight_right", "sharp_right"} and not any(0.5 <= a <= 2.2 for a in options)):
            lanes.append(i)
    return sorted(lanes)


def edge_seconds(edge, direction, speed_cap, queue):
    speed = max(1.0, min(edge["speed"], speed_cap))
    base = edge["len"] / speed
    return base + 4.0 * queue / lane_count(edge, direction) if queue else base


def fastest_route(world, start, goal, goal_xy, *, incoming=None, delay=None, speed_cap=27.0, budget=None,
                  first=None, main_only=False, outgoing=None):
    """A* in travel seconds over directed edges, retaining the approach for turn costs."""
    if start == goal and outgoing is None:
        return ()
    initial = (start, incoming)
    best, prev = {initial: 0.0}, {}
    todo = [(0.0, 0.0, start, incoming or (-1, 0))]
    while todo:
        _, cost, node, approach = heapq.heappop(todo)
        state = (node, approach if approach[0] >= 0 else None)
        if cost != best.get(state):
            continue
        arrived = node == goal
        if arrived and outgoing is not None and approach[0] >= 0:
            angle = turn_angle(world.edges, approach, outgoing)
            arrived = approach[0] != outgoing[0] and abs(angle) <= 2.2 and movement_lanes(world, approach, outgoing, angle) != []
        if arrived:
            path = []
            while state != initial:
                path.append(state[1])
                state = prev[state]
            return tuple(reversed(path))
        if budget is not None:
            if not budget:
                break
            budget -= 1
        arrival = _heading(world.edges, approach, True) if approach[0] >= 0 else None
        for move in world.out.get(node, ()):
            ei, direction = move
            if ei == approach[0] or (state == initial and first is not None and move not in first):
                continue
            e = world.edges[ei]
            end = e["b"] if direction == 1 else e["a"]
            if main_only and end not in world.main:
                continue
            angle = (_heading(world.edges, move, False) - arrival + math.pi) % (2.0 * math.pi) - math.pi if arrival is not None else 0.0
            if abs(angle) > 2.2 or (approach[0] >= 0 and movement_lanes(world, approach, move, angle) == []):
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
