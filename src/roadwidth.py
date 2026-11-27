"""The carriageway width profile shared by the road mesh and runtime."""

from functools import lru_cache

SIDEWALK = {"trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"}


def has_sidewalk(edge, side):
    """Whether the stored direction's left (-1) or right (+1) has a raised sidewalk."""
    sides = edge.get("sidewalk_sides")
    if sides is not None:
        return sides[int(side > 0)]
    return edge["cls"].replace("_link", "") in SIDEWALK


def lane_count(edge, direction=1):
    lanes, width = edge.get("lanes", 0), edge["w"]
    if edge["ow"]:
        return lanes or max(1, int(round(width / 3.5)))
    counts = edge.get("directional_lanes")
    if counts:
        return counts[0 if direction == 1 else 1]
    if lanes:
        return max(1, (lanes + (1 if direction == 1 else 0)) // 2)
    return 2 if width >= 13.0 else 1


def lane_bounds(edge, direction=1):
    """Left-to-right offset limits of the travel direction at nominal width."""
    hw = edge["w"] / 2
    if edge["ow"]:
        return -hw, hw
    own, other = lane_count(edge, direction), lane_count(edge, -direction)
    return hw * (other - own) / (own + other), hw


def lane_turns(edge, direction=1):
    tag = edge.get("turn", ("", ""))[0 if direction == 1 else 1]
    return _parse_turns(tag, lane_count(edge, direction)) if tag else ()


@lru_cache(maxsize=256)
def _parse_turns(tag, count):
    marked = tag.split("|")
    if len(marked) == count:
        return tuple(frozenset(lane.split(";")) - {"", "none"} for lane in marked)
    return ()


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def half_width(edge, distance):
    base = edge["w"] / 2
    if profile := edge.get("candidate_taper"):
        end, length, start, scale, total, amount = profile
        station = start + scale * distance
        remaining = station if end == "start" else total - station
        return base - amount * _ease(1.0 - max(0.0, remaining) / length)
    start, end = edge.get("taper", (None, None))
    width = base
    if start:
        length, target = start
        width += (target - base) * _ease(1.0 - max(0.0, distance) / length)
    if end:
        length, target = end
        width += (target - base) * _ease(1.0 - max(0.0, edge["len"] - distance) / length)
    return width


def center_shift(edge, direction, distance):
    shift = 0.0
    if direction == 1 and (profile := edge.get("candidate_shifts")):
        start, scale, total, shifts = profile
        station = start + scale * distance
        for end, length, amount in shifts:
            remaining = station if end == "start" else total - station
            shift += amount * _ease(1 - remaining / length)
    return shift


def lane_offset(edge, direction, distance, offset):
    """Follow the candidate's lane alignment as a one-way carriageway tapers."""
    shift = center_shift(edge, direction, distance)
    taper = edge.get("lane_taper")
    if not taper or not edge.get("taper") or direction != 1 or not edge["ow"]:
        return shift + (offset * (2 * half_width(edge, distance) / edge["w"]) if edge.get("taper") else offset)
    width, count = edge["w"], lane_count(edge, direction)
    half = half_width(edge, distance)
    left, right = -half, half
    fraction = 0.5 + offset / width
    side = taper[2]
    if side == "both":
        return shift + max(left, min(right, offset))
    if side == "left":
        divider = right - width * (1 - 1 / count)
        return shift + (left + (divider - left) * fraction * count if fraction < 1 / count else right - width * (1 - fraction))
    divider = left + width * (1 - 1 / count)
    return shift + (left + width * fraction if fraction <= 1 - 1 / count else divider + (right - divider) * (fraction - (1 - 1 / count)) * count)


def nominal_offset(edge, direction, distance, offset):
    if not edge.get("lane_taper") and not edge.get("candidate_shifts"):
        return offset * edge["w"] / (2 * half_width(edge, distance)) if edge.get("taper") else offset
    lo, hi = -edge["w"], edge["w"]
    for _ in range(24):
        mid = (lo + hi) / 2
        if lane_offset(edge, direction, distance, mid) < offset:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
