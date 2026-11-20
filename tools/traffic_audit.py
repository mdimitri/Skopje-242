"""Traffic audit on a built world: drives the game's own Sim (traffic + buses + lights + pedestrians) around a district and
counts the faults a player would notice, only for vehicles within VIEW m of the centre that have not ghosted for GHOST_QUIET s.
  overlap   two vehicles' true boxes (no padding) interpenetrate by more than 0.05 m (car/car, car/bus)
  redrun    a vehicle crosses the stop line (9 m before the junction centre) while its approach shows red, at >= 1 m/s
  runover   a vehicle moving at >= 1.5 m/s drives through a walking pedestrian
  jam       a vehicle stands (< 0.3 m/s) for more than 25 s outside a red-light queue
  uturn     a U-turn (turn > 126 degrees) at a junction; 'legal' only on a single-lane road with nothing within 30 m
  loop      a car's heading sweeps more than 240 degrees within 12 s (circling to come back)
  wrongway  a car faces against its lane's direction for 3 s at > 2 m/s outside a manoeuvre
  oncoming  a car drives in the oncoming half of a two-way road for 4 s at > 3 m/s
  speeding  more than 1.4 x the limit
  tailgate  closer than 1 m behind another car at > 6 m/s
  boxblock  standing still inside a junction for more than 6 s
  boxstop   standing inside any junction for more than 2 s, with the active braking reason
  openstop  standing for more than 3 s with no visible lead or traffic control, with the active braking reason
Usage: python3 tools/traffic_audit.py <world_dir> <osm_dir> <out.jsonl> [hood ...]      (one JSON line per hood)"""
import collections
import json
import math
import multiprocessing as mp
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from traffic_study import HOODS      # noqa: E402  (same hoods as the study)

VIEW, GHOST_QUIET = 85.0, 10.0
PARTIZANSKI = {"Franklin Ruzvelt": (-1219, -368), "8-mi Septemvri": (-1930, -500),
               "Kliment Ohridski": (-211, -93), "Ljubljanska": (-3124, -718)}


def _box(x, y, h, hw, hl):
    c, s = math.cos(h), math.sin(h)
    return [(x + c * a - s * b, y + s * a + c * b) for a, b in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]


def _pen(a, b):
    """Penetration depth of two convex quads (0 when apart): SAT, smallest overlap over the four edge normals."""
    best = 1e9
    for poly in (a, b):
        for i in range(4):
            nx, ny = poly[i][1] - poly[i - 1][1], poly[i - 1][0] - poly[i][0]
            n = math.hypot(nx, ny) or 1.0
            nx, ny = nx / n, ny / n
            pa = [p[0] * nx + p[1] * ny for p in a]
            pb = [p[0] * nx + p[1] * ny for p in b]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 0:
                return 0.0
            best = min(best, o)
    return best


_KEEP = {}


def _aid(o):
    """A key that stays unique: holding every object seen keeps id() from being reused by a later one (Car has __slots__)."""
    _KEEP[id(o)] = o
    return id(o)


def run(world, osm_dir, name, cx, cy, cars=90, hour=11.0, aggro=1, secs=240, warm=25, seed=1):
    import signals
    import transit
    import vehicles
    from actors import Car, Sim, _RAD, parts
    random.seed(seed)
    if os.environ.get("NOPARK"):
        world.parked = world.parked[:0]              # diagnostic: no kerb-parked cars at all
    sim = Sim(world, random.Random(seed), cars, 40)
    lights = signals.Signals(world)
    sim.traffic.signals = sim.lights = lights
    sim.transit = transit.Transit(sim, osm_dir)
    sim.clock.hour, sim.aggro = hour, aggro
    sim.teleport(cx, cy)
    sim.exit_car()
    sim.bodies.remove(sim.car)          # the car the idle player left would stand in the road and jam it
    inp = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 0.0), "run": False, "attack": False, "buy": None, "jump": False}
    dt, T = 0.05, sim.traffic
    T.audit_stops = {}
    upd = T.update
    T.update = lambda d, fx, fy, bodies, peds, walker=None: upd(d, fx, fy, bodies, peds, None)      # the idle player is no obstacle
    ghost_at = {}                      # id(car) -> last time it was ghosting
    ov_open, rr_state, ro_open = {}, {}, {}
    standing = collections.defaultdict(float)
    out = dict(overlap=[], redrun=[], runover=[], jam=[], uturn=[], loop=[], wrongway=[], oncoming=[], speeding=[],
               tailgate=[], boxblock=[], boxstop=[], openstop=[])
    yaw = collections.defaultdict(lambda: collections.deque(maxlen=48))        # unwrapped heading, every 0.25 s for 12 s
    flagged = collections.defaultdict(float)                                   # (kind, car) -> time of the last report
    state = collections.defaultdict(float)                                     # seconds a condition has held
    clock = [0.0]
    orig_next = T._next_edge

    def next_edge(c):
        e0 = world.edges[c.e]
        turn, x, y = c.turn, c.x, c.y
        ok = orig_next(c)
        if abs(turn) > T.UTURN and math.hypot(x - cx, y - cy) < VIEW and clock[0] > warm:
            near = [o for o in T.cars if o is not c and math.hypot(o.x - x, o.y - y) < 30.0] + \
                   [b for b in sim.bodies if b.speed >= 0.3 and math.hypot(b.x - x, b.y - y) < 30.0]    # parked cars do not move into the turn
            multi = len(T.lanes_of(e0)) >= 2 if e0["ow"] else e0["w"] >= 8.0
            if not (not multi and not near) and os.environ.get("UDBG"):
                print("UT", clock[0], c.stuck, c.ghost, c.v, [(round(math.hypot(o.x - x, o.y - y)), round(getattr(o, "v", 0), 1)) for o in near][:6], flush=True)
            out["uturn"].append(dict(t=round(clock[0], 1), x=round(x), y=round(y), cls=e0["cls"], w=e0["w"], multi=multi, others=len(near),
                                     legal=(not multi and not near)))
        return ok
    T._next_edge = next_edge
    trail = collections.defaultdict(lambda: collections.deque(maxlen=80))
    last_sample = {}
    nodes = [(n, jx, jz, idx) for n, ((jx, jz), idx) in lights.nodes.items()]
    junctions = {}
    for e in world.edges:
        if e["drive"]:
            for n, (x, y) in ((e["a"], e["pts"][0]), (e["b"], e["pts"][-1])):
                if n in T.junctions and math.hypot(x - cx, y - cy) <= VIEW + 15.0:
                    junctions[n] = (x, y, min(10.0, max(4.0, T.junctions[n] * 0.65)))
    for k in range(int((warm + secs) / dt)):
        t = k * dt
        lights.update(dt)
        clock[0] = t
        sim.update(dt, inp, 1)
        if t < warm:
            continue
        veh = []                                         # (key, kind, x, y, h, v, label)
        for c in T.cars:
            if c.ghost > 0:
                ghost_at[_aid(c)] = t
            if math.hypot(c.x - cx, c.y - cy) < VIEW and t - ghost_at.get(_aid(c), -99.0) > GHOST_QUIET:
                veh.append((_aid(c), c.kind, c.x, c.y, c.h, c.v, "car", c))
        for b in sim.bodies:
            if b.exploded or math.hypot(b.x - cx, b.y - cy) > VIEW:
                continue
            if b.speed > 0.3 or any(bus.body is b for bus in sim.transit.buses):
                veh.append((_aid(b), b.kind, b.x, b.y, b.h, b.speed, "bus" if any(bus.body is b for bus in sim.transit.buses) else "body", b))
        if k % 5 == 0:
            for v in veh:
                c = v[7]
                key = v[0]
                if key in last_sample and k - last_sample[key] > 5:
                    standing[key] = 0.0
                    trail[key].clear()
                    yaw[key].clear()
                    for tag in ("bb", "boxstop", "openstop", "ww", "oc"):
                        state.pop((tag, key), None)
                last_sample[key] = k
                trail[v[0]].append((round(t, 1), round(v[2], 1), round(v[3], 1), round(v[4], 2), round(v[5], 1), getattr(c, "e", 0), getattr(c, "d", 0),
                                    round(getattr(c, "s", 0), 1), round(getattr(c, "rev", 0), 1), round(getattr(c, "shift", 0), 1), round(getattr(c, "avoid", 0), 1),
                                    round(getattr(c, "man", 0), 1), round(getattr(c, "stuck", 0), 1)))
        boxes = [(v, [_box(x, y, h, hw, hl) for x, y, h, hl, hw in parts(v[7])]) for v in veh]
        now = set()
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if math.hypot(a[0][2] - b[0][2], a[0][3] - b[0][3]) > _RAD[a[0][1]] + _RAD[b[0][1]]:
                    continue
                p = max(_pen(pa, pb) for pa in a[1] for pb in b[1])
                if p > 0.05:
                    key = (a[0][0], b[0][0])
                    now.add(key)
                    if key not in ov_open:
                        ea, eb = a[0][7], b[0][7]
                        ov_open[key] = 1
                        out["overlap"].append(dict(t=round(t, 1), x=round(a[0][2]), y=round(a[0][3]), a=a[0][6], b=b[0][6], pen=round(p, 2),
                                                   va=round(a[0][5], 1), vb=round(b[0][5], 1),
                                                   cls=world.edges[ea.e]["cls"] if a[0][6] == "car" else "-",
                                                   rev=[getattr(x[0][7], "rev", 0) > 0 for x in (a, b)],
                                                   rel=[round((b[0][2] - a[0][2]) * math.cos(a[0][4]) + (b[0][3] - a[0][3]) * math.sin(a[0][4]), 1),
                                                        round(-(b[0][2] - a[0][2]) * math.sin(a[0][4]) + (b[0][3] - a[0][3]) * math.cos(a[0][4]), 1)],
                                                   dh=round(abs((a[0][4] - b[0][4] + math.pi) % (2 * math.pi) - math.pi), 1), aggro=aggro, seed=seed,
                                                   ed=[(getattr(x[0][7], "e", None), getattr(x[0][7], "d", None), round(getattr(x[0][7], "s", 0)), round(getattr(x[0][7], "ghost", 0), 1),
                                                        round(getattr(x[0][7], "stuck", 0), 1)) for x in (a, b)],
                                                   trail=[list(trail[x[0][0]])[-14::2] for x in (a, b)] if p > 0.3 else None,
                                                   waitbus=[bool(x[0][6] == "bus" and any(bs.body is x[0][7] and bs.wait > 0 for bs in sim.transit.buses)) for x in (a, b)],
                                                   shift=[round(getattr(x[0][7], "shift", 0), 1) for x in (a, b)]))
        for key in list(ov_open):
            if key not in now:
                del ov_open[key]
        # Red lights: track each approach's fixed stop plane with the vehicle's front bumper.
        for v in veh:
            hx, hy = math.cos(v[4]), math.sin(v[4])
            c_ = v[7]
            moves = {(c_.e, c_.d), c_.nxt, *(move for move, _ in (c_.nx2 or ()))} if v[6] == "car" else None
            hl = vehicles.HALF_L[v[1]]
            for n, jx, jz, idx in nodes:
                if abs(jx - v[2]) > 45 or abs(jz - v[3]) > 45:
                    continue
                for i in idx:
                    ax, ay = lights._axis(i)
                    ie, end = lights.items[i][1:3]
                    if lights.by_edge[(ie, end)] != i:
                        continue                                      # multiple lamp heads control the same approach
                    if ((moves is not None and (ie, 1 if end else -1) not in moves) or ax * hx + ay * hy < 0.8
                            or abs((jx - v[2]) * ay - (jz - v[3]) * ax) > world.edges[ie]["w"] * 0.5 + 1.2):
                        continue
                    distance = (jx - v[2] - hx * hl) * ax + (jz - v[3] - hy * hl) * ay
                    sl = lights.stopd.get((ie, end), 9.0)
                    key = (v[0], i)
                    old = rr_state.get(key, (k, distance))
                    rr_state[key] = (k, distance)
                    if old[0] == k - 1 and old[1] > sl >= distance and v[5] >= 0.8 and lights.state(i) == 2:
                        out["redrun"].append(dict(node=n, item=i, ie=ie, t=round(t, 1), x=round(v[2]), y=round(v[3]), who=v[6], v=round(v[5], 1),
                                                  stuck=round(getattr(v[7], "stuck", 0), 1), e=getattr(v[7], "e", None), d=getattr(v[7], "d", None), s=round(getattr(v[7], "s", 0)),
                                                  nxt=str(getattr(v[7], "nxt", None)), trail=list(trail[v[0]])[-16::3]))
        # pedestrians
        for p in sim.peds.list:
            if p.mode not in ("walk", "flee", "rage", "brawl") or math.hypot(p.x - cx, p.y - cy) > VIEW:
                continue
            for v in veh:
                if v[5] < 1.5 or abs(v[2] - p.x) > 8 or abs(v[3] - p.y) > 8:
                    continue
                c_, s_ = math.cos(v[4]), math.sin(v[4])
                rel, lat = (p.x - v[2]) * c_ + (p.y - v[3]) * s_, -(p.x - v[2]) * s_ + (p.y - v[3]) * c_
                if abs(rel) < vehicles.HALF_L[v[1]] and abs(lat) < vehicles.HALF_W[v[1]]:
                    key = (_aid(p), v[0])
                    if key not in ro_open:
                        out["runover"].append(dict(t=round(t, 1), x=round(p.x), y=round(p.y), who=v[6], v=round(v[5], 1), ped=p.mode, rel=round(rel, 1), lat=round(lat, 1), pv=round(math.hypot(p.vx, p.vy), 1),
                                                     pcos=round(((p.vx * c_ + p.vy * s_) / (math.hypot(p.vx, p.vy) or 1)), 1), cls=world.edges[v[7].e]["cls"] if v[6] == "car" else "-",
                                                     blk=type(getattr(v[7], "blk", None)).__name__))
                    ro_open[key] = t
        for key in [k_ for k_, tt in ro_open.items() if t - tt > 3.0]:
            del ro_open[key]
        # jams: standing for long, not queueing at a red light / giving way
        if k % 20 == 0:
            for v in veh:
                if v[6] != "car":
                    continue
                c = v[7]
                e = world.edges[c.e]
                red_distance = T._red_rem(c, e["len"], lights)
                red = red_distance is not None and -2.5 < red_distance < 45.0
                if v[5] < 0.3 and not red:
                    standing[v[0]] += 1.0
                    if standing[v[0]] == 25.0:
                        out["jam"].append(dict(t=round(t, 1), x=round(c.x), y=round(c.y), cls=e["cls"], rem=round(e["len"] - c.s), edge=c.e,
                                               reason=T.audit_stops.get(c), next=c.nxt,
                                               blk=type(c.blk).__name__ if c.blk is not None else None, rev=c.rev > 0))
                else:
                    if standing[v[0]] >= 25.0:
                        out["jam"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), freed_after=standing[v[0]]))      # how long it took to get going again
                    standing[v[0]] = 0.0
        # --- traffic law checks, one pass per 0.25 s
        if k % 5 == 0:
            for v in veh:
                if v[6] != "car":
                    continue
                c = v[7]
                e = world.edges[c.e]
                key = v[0]
                h = yaw[key]
                prev = h[-1] if h else v[4]
                h.append(prev + (v[4] - prev + math.pi) % (2 * math.pi) - math.pi)
                if len(h) >= 48 and max(h) - min(h) > 4.2 and t - flagged[("loop", key)] > 30:
                    flagged[("loop", key)] = t
                    out["loop"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), cls=e["cls"], edge=c.e, turn=round(max(h) - min(h), 1), trail=list(trail[key])[-48::4]))
                rh = T._ref(e, c.d, c.s, c.lane)[2]
                against = abs((c.h - rh + math.pi) % (2 * math.pi) - math.pi) > 2.3 and v[5] > 2.0 and c.man <= 0 and c.rev <= 0
                state[("ww", key)] = state[("ww", key)] + 0.25 if against else 0.0
                if state[("ww", key)] > 3.0 and t - flagged[("ww", key)] > 20:
                    flagged[("ww", key)] = t
                    out["wrongway"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), cls=e["cls"], edge=c.e, v=round(v[5], 1)))
                onc = (not e["ow"]) and (c.lane + c.shift + c.avoid) * c.lane < 0 and abs(c.lane + c.shift + c.avoid) > 0.9 and v[5] > 3.0
                state[("oc", key)] = state[("oc", key)] + 0.25 if onc else 0.0
                if state[("oc", key)] > 4.0 and t - flagged[("oc", key)] > 20:
                    flagged[("oc", key)] = t
                    out["oncoming"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), cls=e["cls"], edge=c.e, v=round(v[5], 1), blk=type(c.blk).__name__))
                if v[5] > max(e["speed"] * 1.4, e["speed"] + 4.0) and t - flagged[("sp", key)] > 20:
                    flagged[("sp", key)] = t
                    out["speeding"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), cls=e["cls"], v=round(v[5], 1), limit=round(e["speed"], 1)))
                T.lead = None
                g = T.scan(c, 6.0)
                if g is not None and g < 1.0 and v[5] > 6.0 and isinstance(T.lead[4] if T.lead else None, type(c)) and t - flagged[("tg", key)] > 20:
                    flagged[("tg", key)] = t
                    out["tailgate"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), v=round(v[5], 1), gap=round(g, 2)))
                inbox = any((jx - v[2]) ** 2 + (jz - v[3]) ** 2 < radius ** 2 for jx, jz, radius in junctions.values())
                state[("bb", key)] = state[("bb", key)] + 0.25 if (inbox and v[5] < 0.3) else 0.0
                if state[("bb", key)] > 6.0 and t - flagged[("bb", key)] > 30:
                    flagged[("bb", key)] = t
                    out["boxblock"].append(dict(t=round(t, 1), x=round(v[2]), y=round(v[3]), cls=e["cls"]))
                reason = T.audit_stops.get(c)
                for tag, condition, threshold in (
                    ("boxstop", inbox, 2.0),
                    ("openstop", reason in ("open lane", "clearance", "borrowed lane", "crossing"), 3.0),
                ):
                    state[(tag, key)] = state[(tag, key)] + 0.25 if v[5] < 0.3 and condition else 0.0
                    if state[(tag, key)] == threshold:
                        out[tag].append(dict(t=round(t, 1), x=round(v[2], 1), y=round(v[3], 1), edge=c.e, direction=c.d,
                                             rem=round(e["len"] - c.s, 1), reason=reason, next=c.nxt, turn=round(c.turn, 2)))
    return dict(name=name, cars=cars, secs=secs, counts={k: len(v) for k, v in out.items()}, **out)


_W = {}


def _job(a):
    wd, od, kw = a
    from world import World
    if wd not in _W:
        _W[wd] = World(wd, lambda f, note="": None)
    return run(_W[wd], od, **kw)


if __name__ == "__main__":
    wd, od, outp = sys.argv[1:4]
    names = list(PARTIZANSKI) if sys.argv[4:] == ["partizanski"] else sys.argv[4:] or list(HOODS)
    sites = {**HOODS, **PARTIZANSKI}
    jobs = [(wd, od, dict(name=n, cx=sites[n][0], cy=sites[n][1], seed=sd, hour=hr, aggro=ag))
            for sd, hr, ag in ((1, 11.0, 1), (2, 17.0, 2), (3, 8.0, 3)) for n in names]
    with mp.Pool(4) as pool, open(outp, "w", encoding="utf-8") as f:
        for r in pool.imap(_job, jobs):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(r["name"], r["counts"], flush=True)
