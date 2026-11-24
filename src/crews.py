"""Road-marking crews: a convoy that repaints the lane lines of a real street.

A convoy (the paint truck in front, the cone truck, the arrow-board truck at the back; a cone-placing worker ahead of it, a
cone-collecting worker behind it) works along one marked street at walking pace.  Workers put traffic cones out in front along
the lane line and pick them up behind.  The truck first blacks out the old line (so it is really covered), then lays the new
one, which starts out wet and glossy and dries over about a minute and a half.

Traffic: the three trucks are ordinary `Body` vehicles (moved here, not by the physics loop) and every cone is a small `Body` that
only the traffic AI sees (`obstacles()`, passed on to the AI process next to `sim.bodies`), so the cars and the people on foot treat the
work zone like any other obstacle: they queue behind the arrow truck or go round it.  The crew simulation exists only near the
player; a convoy that falls behind or is turned off just disappears (the paint stays).

Settings: `road_crews` (menu, on by default).  Debug: F9 with the debug setting on, or `--crew` on the command line, starts one
next to the player.  Drawing: Renderer._crews -> Crews.draw3d (immediate mode, like the skid marks)."""
import math
import os
import random

import actors
import vehicles
from roadwidth import lane_bounds, lane_count

HOURS = (6.5, 17.5)               # the working day (game clock)
MAX_ACTIVE = 5                    # convoys at once
RING = (70.0, 380.0)             # a convoy starts this far from the player (not in view, not out of reach)
LOSE = 460.0                      # ... and goes away when the player is farther than this
PAINT_SPEED = 1.3                 # m/s the paint truck advances
CONE_GAP = 7.0                    # m between cones along the lane line
AHEAD = 28.0                      # cones go out this far in front of the paint truck
SPACING = (0.0, -17.0)            # paint truck, cone truck (arrow board on its tail), behind the leader (m)
PICKUP_AT = -32.0                 # cones behind this (relative to the paint truck) are collected
SPEED_UP = float(os.environ.get("SK242_CREW_SPEED") or 1.0)          # test harness: run the crew faster than real time
DEBUG_COLOURS = bool(os.environ.get("SK242_CREW_DEBUG"))      # test harness: blue black-out bands, red lines
LIFT = float(os.environ.get("SK242_CREW_LIFT") or 0.05)       # m above ground_y (the asphalt top)
GUN = 3.6                         # the spray gun hangs this far behind the paint truck's centre
DRY_T = 100.0                     # s the paint stays wet
LEAVE_SPEED = 8.0
MARKED = {"primary", "secondary", "tertiary", "trunk", "unclassified", "residential"}
BLACK_WET, BLACK_DRY = (26, 26, 30, 255), (50, 50, 53, 236)       # a black-out band dries to dark grey, nearly opaque
WHITE_WET, WHITE_DRY = (255, 255, 252), (247, 247, 241)


def spray_on(now):
    """The gun fires in bursts: on 0.6 s of every 1.1 s."""
    return (now % 1.1) < 0.6


def _base(cls):
    return cls.replace("_link", "")


class _Cone:
    __slots__ = ("s", "x", "y", "body")

    def __init__(self, s, x, y, body):
        self.s, self.x, self.y, self.body = s, x, y, body


class Convoy:
    """One working crew on one directed street, see the module doc."""

    def __init__(self, crews, ei, d, s0, s1):
        self.cr = crews
        sim = crews.sim
        self.w = sim.w
        self.ei, self.d = ei, d
        e = self.e = self.w.edges[ei]
        self.route = [(ei, d)]
        self.s0, self.s1 = s0, s1
        lanes = actors.Traffic.lanes_of(e, d)
        self.lane = lanes[-1]                                     # the kerb-side lane
        n = len(lanes)
        lo, hi = lane_bounds(e, d)
        lw = (hi - lo) / n
        self.cone_lat = self.lane - lw / 2 + 0.3                  # cones stand just inside the lane, on its centre-side line
        self.sp = s0                                              # paint truck's distance along the street (in the direction of travel)
        self.state = "work"                                       # work -> pack (collect the cones) -> leave
        self.t = 0.0
        self.cones = []
        self.last_cone = s0
        self.painted = s0 - 1.0                                   # how far the truck has laid paint (s along the travel direction)
        self.done = False
        self.stripes = self._stripes()
        self.veh = []                                             # [body, gap behind the leader, route index, own s]
        rng = crews.rng
        for kind, gap in zip(vehicles.CREW_TRUCKS, SPACING):
            x, y, h = self.pose(0, s0 + gap, self.lane)
            b = actors.Body(x, y, h, kind, 0)
            b.locked, b.empty, b.crew, b.ctl = True, False, self, (0.0, 0.0, True)
            b.health = 100.0
            sim.bodies.append(b)
            self.veh.append([b, gap, 0, s0 + gap])
        self.workers = []                                         # [ped, role, route index, own s, lateral, state timer]
        for role, gap, lat in (("place", AHEAD + 2.0, self.cone_lat - 0.5), ("pick", PICKUP_AT - 2.0, self.cone_lat - 0.5),
                               ("spot", -3.0, self.lane + 1.9)):
            self.workers.append(self._worker(role, s0 + gap, lat))
        for k in range(int((AHEAD - PICKUP_AT) / CONE_GAP) + 1):  # the cones are already out when the crew comes into view
            self._put(s0 + PICKUP_AT + 3.0 + k * CONE_GAP)
        self.last_cone = max((c.s for c in self.cones), default=s0)
        self.pace = 0.0
        self.beep = 0.0

    # ------------------------------------------------------------------ geometry
    def pose(self, ridx, s, lat):
        """(x, y, heading) at distance s along route piece ridx (distance in the direction of travel), lateral offset to the right."""
        ei, d = self.route[min(ridx, len(self.route) - 1)]
        e = self.w.edges[ei]
        L = e["len"]
        along = min(max(s if d == 1 else L - s, 0.0), L)
        x, y, dx, dy = self.w.edge_point(e, along)
        if d == -1:
            dx, dy = -dx, -dy
        return x - dy * lat, y + dx * lat, math.atan2(dy, dx)

    def _stripes(self):
        """The lines this crew paints, as (lateral offset in the stored direction of the edge, width, dashed): the centre line (double
        on wide streets), the lane lines of its own side and its own edge line; the same arrangement tools/roads3d paints."""
        e, w = self.e, self.e["w"]
        hw = w / 2
        out = []
        sg = 1 if self.d == 1 else -1                             # which side of the stored edge this crew's lane is on
        if e["ow"]:
            n = lane_count(e)
            out += [(hw * (2 * k / n - 1), 0.16, True) for k in range(1, n)]
        else:
            lo = lane_bounds(e, 1)[0]
            if w >= 8.0:
                out += [(lo + 0.14, 0.11, False), (lo - 0.14, 0.11, False)]
            else:
                out.append((lo, 0.13, True))
            n = lane_count(e, sg)
            out += [(lo + (sg * hw - lo) * k / n, 0.15, True) for k in range(1, n)]
        if w >= 7.0:
            out.append((sg * (hw - 0.45), 0.14, False))
        return out

    def _lat_xy(self, s, lat):
        """Point on the stored line of the edge at distance s (along the stored direction) and lateral offset lat."""
        e = self.e
        x, y, dx, dy = self.w.edge_point(e, min(max(s, 0.0), e["len"]))
        return x - dy * lat, y + dx * lat

    def _paint(self, a, b):
        """Lay down paint between a and b (distances along the travel direction)."""
        L = self.e["len"]
        if self.d == -1:
            a, b = L - b, L - a
        if b - a < 0.05:
            return
        cr = self.cr
        for lat, width, dashed in self.stripes:
            if dashed:
                spans = []
                k = int((a - self.s0 - 1.2) // 9.0) if self.d == 1 else int((a - (L - self.s0) - 1.2) // 9.0)
                while True:
                    base = (self.s0 if self.d == 1 else L - self.s0) + 1.2 + k * 9.0
                    if base > b:
                        break
                    lo_, hi_ = max(a, base), min(b, base + 3.0)
                    if hi_ - lo_ > 0.02:
                        spans.append((lo_, hi_))
                    k += 1
                cr.add_paint(*self._lat_xy(a, lat), *self._lat_xy(b, lat), width + 0.16, 0)         # the old dashes disappear under a black band
            else:
                spans = [(a, b)]
            for lo_, hi_ in spans:
                cr.add_paint(*self._lat_xy(lo_, lat), *self._lat_xy(hi_, lat), width + 0.04, 1)

    # ------------------------------------------------------------------ people and cones
    def _worker(self, role, s, lat):
        p = actors.Ped()
        p.arch = vehicles.PATAR
        p.shirt, p.skin = self.cr.rng.randrange(3), self.cr.rng.randrange(4)
        p.hp = 60.0
        p.mode, p.v, p.pose = "crew", 0.0, None
        x, y, h = self.pose(0, s, lat)
        p.x, p.y, p.h = x, y, h
        p.tx, p.ty = x, y
        self.cr.sim.peds.list.append(p)
        return [p, role, 0, s, lat, 0.0]

    def _put(self, s):
        x, y, _h = self.pose(0, s, self.cone_lat)
        b = actors.Body(x, y, 0.0, vehicles.CONE, 0)
        b.az = None
        self.cones.append(_Cone(s, x, y, b))
        self.cr.events.append((x, y, "put"))
        self.cr.cone_bodies.append(b)

    def _take(self, c):
        self.cr.events.append((c.x, c.y, "take"))
        self.cones.remove(c)
        if c.body in self.cr.cone_bodies:
            self.cr.cone_bodies.remove(c.body)

    # ------------------------------------------------------------------ update
    def update(self, dt):
        cr = self.cr
        self.t += dt
        w = self.w
        if self.state == "work":
            speed = PAINT_SPEED
            if self.sp >= self.s1:
                self.state, speed = "pack", 0.0
            self.sp = min(self.s1, self.sp + speed * dt)
            self.pace = speed
            self._paint(self.painted, self.sp - GUN)
            self.painted = max(self.painted, self.sp - GUN)
        elif self.state == "pack":
            self.pace = 0.0
            if self.painted < self.s1 - GUN:
                self._paint(self.painted, self.s1 - GUN)
                self.painted = self.s1 - GUN
            if not self.cones or self.t > 600.0:
                for c in list(self.cones):
                    self._take(c)
                self._begin_leave()
        elif self.state == "leave":
            self.pace = LEAVE_SPEED
        for v in self.veh:
            self._drive(v, dt)
        for wk in self.workers:
            self._walk(wk, dt)
        if self.state == "leave" and not self.veh:
            self.done = True

    def _begin_leave(self):
        """Extend the route over the junction ahead (the straightest street on) so the trucks drive away instead of vanishing."""
        self.state = "leave"
        tr = self.cr.sim.traffic
        ei, d = self.route[-1]
        for _ in range(3):
            e = self.w.edges[ei]
            node = e["b"] if d == 1 else e["a"]
            head = tr._head(e, d, True)
            best, bd = None, 0.9
            for ej in tr._node_edges.get(node, ()):
                if ej == ei:
                    continue
                f = self.w.edges[ej]
                dd = 1 if f["a"] == node else -1
                if f["ow"] and dd == -1:
                    continue
                turn = abs((tr._head(f, dd, False) - head + math.pi) % (2 * math.pi) - math.pi)
                if turn < bd:
                    best, bd = (ej, dd), turn
            if best is None:
                break
            self.route.append(best)
            ei, d = best
        for wk in self.workers:                                    # the crew gets on the trucks: they leave the road
            self._drop_worker(wk)
        self.workers = []

    def _drop_worker(self, wk):
        p = wk[0]
        if p in self.cr.sim.peds.list:
            self.cr.sim.peds.list.remove(p)

    def _drive(self, v, dt):
        b, gap, ridx, s = v
        target = self.sp + gap if self.state != "leave" else s + LEAVE_SPEED * dt
        if self.state != "leave":
            s = target
        else:
            s = target
            ei, d = self.route[ridx]
            L = self.w.edges[ei]["len"]
            if s > L:
                if ridx + 1 >= len(self.route):
                    self._remove_vehicle(v)
                    return
                s -= L
                ridx += 1
        v[2], v[3] = ridx, s
        ei, d = self.route[ridx]
        lat = actors.Traffic.lanes_of(self.w.edges[ei], d)[-1] if ridx else self.lane
        x, y, h = self.pose(ridx, s, lat)
        k = 1.0 - math.exp(-8.0 * dt)
        if b.age < 0.05 or math.hypot(x - b.x, y - b.y) > 12.0:
            k = 1.0
        nx, ny = b.x + (x - b.x) * k, b.y + (y - b.y) * k
        nh = b.h + ((h - b.h + math.pi) % (2 * math.pi) - math.pi) * k
        speed = self.pace
        b.vx, b.vy = math.cos(nh) * speed, math.sin(nh) * speed
        b.x, b.y, b.h = nx, ny, nh
        b.age += dt
        actors.settle(b, self.w, dt, self.cr.sim.ev)
        b.vx, b.vy = math.cos(nh) * speed, math.sin(nh) * speed
        b.braking = speed < 0.1
        b.health = 100.0

    def _remove_vehicle(self, v):
        b = v[0]
        sim = self.cr.sim
        if b in sim.bodies:
            sim.bodies.remove(b)
            if b.model is not None:
                sim.ev("free_model", model=b.model)
        self.veh.remove(v)

    def _walk(self, wk, dt):
        p, role = wk[0], wk[1]
        if p.mode != "crew":                                       # hit, knocked out, scared: not ours any more
            p.pose = None
            self.workers.remove(wk)
            return
        wk[5] -= dt
        working = self.state == "work"
        if role == "place":                                        # puts a cone out every CONE_GAP, just ahead of the paint truck
            nxt = self.last_cone + CONE_GAP
            if working and nxt <= min(self.s1, self.sp + AHEAD):
                goal = nxt - 1.0
                if wk[3] < goal - 0.2:
                    wk[3] = min(goal, wk[3] + 3.0 * dt)
                    p.pose, p.v = None, 3.0
                elif p.pose != "work":
                    p.pose, p.v, wk[5] = "work", 0.0, 1.2
                elif wk[5] <= 0.0:
                    self._put(nxt)
                    self.last_cone = nxt
                    p.pose = None
            elif self.state == "pack":
                self._collect(wk, dt, p)
            else:
                goal = self.sp + AHEAD + 2.0
                wk[3] += max(-3.0 * dt, min(3.0 * dt, goal - wk[3]))
                p.pose, p.v = None, PAINT_SPEED
        elif role == "pick":                                       # collects the cones the convoy has left behind
            behind = [c for c in self.cones if c.s < self.sp + PICKUP_AT + 6.0 or self.state == "pack"]
            if behind:
                self._collect(wk, dt, p)
            else:
                goal = self.sp + PICKUP_AT - 2.0
                wk[3] += max(-3.0 * dt, min(3.0 * dt, goal - wk[3]))
                p.pose, p.v = None, PAINT_SPEED
        else:                                                      # spotter: walks beside the paint truck, doing a bit of hand work
            goal = self.sp - 3.0
            wk[3] += max(-1.5 * dt, min(1.5 * dt, goal - wk[3]))
            if working and int(self.t / 6.0) % 3 == 2:
                p.pose, p.v = "work", 0.0
            else:
                p.pose, p.v = None, PAINT_SPEED
        x, y, h = self.pose(0, wk[3], wk[4])
        if p.pose == "work" or p.v < 0.1:
            p.vx = p.vy = 0.0
        else:
            p.vx, p.vy = (x - p.x) / max(dt, 1e-3), (y - p.y) / max(dt, 1e-3)
            sp_ = math.hypot(p.vx, p.vy)
            if sp_ > 4.0:
                p.vx, p.vy = p.vx * 4.0 / sp_, p.vy * 4.0 / sp_
            p.anim += dt * 3.0
        p.x, p.y, p.h = x, y, h
        p.t = 5.0
        p.gz = self.w.level(x, y, p.gz if p.gz is not None else -1e9)

    def _collect(self, wk, dt, p):
        """Walk to the nearest cone (the rearmost while the convoy works), bend over it, take it away, repeat."""
        if not self.cones:
            p.pose, p.v = None, 0.0
            return
        c = min(self.cones, key=(lambda c_: abs(c_.s - wk[3])) if self.state == "pack" else (lambda c_: c_.s))
        goal = c.s - 0.9
        if abs(wk[3] - goal) > 0.3:
            wk[3] += max(-3.2 * dt, min(3.2 * dt, goal - wk[3]))
            p.pose, p.v, wk[5] = None, 3.2, 0.9
        else:
            p.pose, p.v = "work", 0.0
            if wk[5] <= 0.0:
                self._take(c)
                wk[5] = 0.9

    def remove_all(self):
        sim = self.cr.sim
        for v in list(self.veh):
            self._remove_vehicle(v)
        for c in list(self.cones):
            self._take(c)
        for wk in self.workers:
            self._drop_worker(wk)
        self.workers = []
        self.done = True

    def near(self, x, y):
        b = self.veh[0][0] if self.veh else None
        if b is None:
            return 1e9
        return math.hypot(b.x - x, b.y - y)


class Crews:
    def __init__(self, sim):
        self.sim = sim
        self.rng = random.Random(4242)
        self.convoys = []
        self.cone_bodies = []                  # what the traffic AI is told about besides sim.bodies
        self.paint = {}                        # (cx, cy) -> [(x1, y1, x2, y2, half width, kind, t0)]
        self.n_paint = 0
        self.now = 0.0
        self.drawn = 0
        self.cool = 1.0
        self.events = []                       # (x, y, 'put' | 'take') cone sounds for sound()
        self.stats = {"queue_max": 0, "slow_cars": 0, "jam_s": 0.0}
        self._mon = 0.0
        self.enabled = lambda: True
        self._cands = None

    # ------------------------------------------------------------------ queries
    def open(self):
        return True                                                # crews work round the clock (at night under their own lights)

    def obstacles(self):
        """The cones as bodies for Traffic.update / the traffic process."""
        return self.cone_bodies

    def night_items(self, rect):
        """Lights of the work zones inside rect: ground pools (x, y, radius m, colour, strength) from the trucks' floodlights and
        glows (x, y, height m, radius m, colour, alpha) of the amber beacons, the flashing arrow board, the cones and the hi-vis vests."""
        pools, glows = [], []
        t = self.now
        for cv in self.convoys:
            for b, _g, _r, _s in cv.veh:
                if not (rect[0] - 30 < b.x < rect[2] + 30 and rect[1] - 30 < b.y < rect[3] + 30):
                    continue
                ca, sa = math.cos(b.h), math.sin(b.h)
                k = b.kind
                pools.append((b.x - ca * 2.0, b.y - sa * 2.0, 11.0, (255, 245, 220), 0.8))        # work lights on a mast over the bed
                glows.append((b.x - ca * 1.5, b.y - sa * 1.5, 4.6, 1.8, (255, 250, 230), 150))
                if (int(t * 2.5) & 1) == (id(b) & 1):                                             # rotating beacon on the cab, two phases
                    glows.append((b.x + ca * 2.0, b.y + sa * 2.0, vehicles.DIMS[k][4] + 0.2, 2.4, (255, 170, 20), 235))
                if k == vehicles.CREW_TRUCKS[1] and int(t * 1.5) % 3:                             # arrow board: the arrow flashes
                    rx, ry = -sa, ca
                    for i in range(-3, 4):
                        glows.append((b.x - ca * 3.4 + rx * i * 0.28, b.y - sa * 3.4 + ry * i * 0.28, 3.0, 0.55, (255, 176, 30), 255))
        for cv in self.convoys:
            for c in cv.cones:
                if rect[0] < c.x < rect[2] and rect[1] < c.y < rect[3]:
                    glows.append((c.x, c.y, 0.5, 0.9, (255, 120, 40), 130))
            for wk in cv.workers:
                p = wk[0]
                if rect[0] < p.x < rect[2] and rect[1] < p.y < rect[3]:
                    glows.append((p.x, p.y, 1.2, 1.1, (220, 255, 80), 110))
        return pools, glows

    def nearest(self, x, y):
        return min((cv.near(x, y) for cv in self.convoys), default=1e9)

    # ------------------------------------------------------------------ candidates
    def _candidates(self):
        """Streets a crew may work on: marked, two or more lanes' width, long and straight enough, no bridge, tunnel or junction link."""
        if self._cands is None:
            w = self.sim.w
            tr = self.sim.traffic
            out = []
            for ei, e in enumerate(w.edges):
                if (not e["drive"] or e.get("bridge") or e.get("tunnel") or e.get("taper") or ei in tr.internal_links
                        or _base(e["cls"]) not in MARKED or e["w"] < 6.0 or e["len"] < 85.0):
                    continue
                out.append(ei)
            self._cands = out
        return self._cands

    def _stretch(self, ei, d):
        """(s0, s1): where along the street (travel direction d) the paint truck starts and stops; None when it is not straight enough."""
        e = self.sim.w.edges[ei]
        L = e["len"]
        s0 = 38.0
        s1 = min(L - 14.0, s0 + 150.0)
        if s1 - s0 < 30.0:
            return None
        pts = [self.sim.w.edge_point(e, (s if d == 1 else L - s))[:2] for s in (s0 - 40.0, s0, (s0 + s1) / 2, s1)]
        ax, ay, bx, by = pts[0][0], pts[0][1], pts[-1][0], pts[-1][1]
        ln = math.hypot(bx - ax, by - ay) or 1.0
        for x, y in pts[1:-1]:
            if abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) / ln > 1.2:
                return None
        stops = getattr(self.sim.w, "bus_stops", None) or ()         # never on top of a bus stop: the buses keep stopping where they always did
        if stops:
            n = int((s1 - (s0 - 50.0)) // 10) + 1
            for k in range(n):
                s = s0 - 50.0 + 10.0 * k
                x, y = self.sim.w.edge_point(e, (s if d == 1 else L - s))[:2]
                if any(abs(st[0] - x) < 40.0 and abs(st[1] - y) < 40.0 for st in stops):
                    return None
        return s0, s1

    def start(self, ei, d, stretch=None):
        st = stretch or self._stretch(ei, d)
        if st is None:
            return None
        cv = Convoy(self, ei, d, *st)
        self.convoys.append(cv)
        return cv

    def _try_spawn(self, fx, fy, ring=RING, nearest=False):
        w = self.sim.w
        busy = {cv.ei for cv in self.convoys}
        best = []
        for ei in self._candidates():
            if ei in busy:
                continue
            e = w.edges[ei]
            x, y = w.edge_point(e, e["len"] / 2)[:2]
            dist = math.hypot(x - fx, y - fy)
            if ring[0] <= dist <= ring[1]:
                best.append((dist, ei))
        if not best:
            return None
        if nearest:
            best.sort()
        else:
            self.rng.shuffle(best)
        for _dist, ei in best[:12]:
            d = self.rng.choice((1, -1)) if not w.edges[ei]["ow"] else 1
            cv = self.start(ei, d)
            if cv is not None:
                return cv
        return None

    def spawn_near(self, fx, fy):
        """Debug (F9 / --crew): a crew on the nearest suitable street, as close to the player as the ring allows."""
        return self._try_spawn(fx, fy, ring=(25.0, 600.0), nearest=True)

    # ------------------------------------------------------------------ update
    def update(self, dt):
        sim = self.sim
        if getattr(sim, "client", False):
            return
        if not self.enabled():
            for cv in self.convoys:
                cv.remove_all()
            self.convoys = []
            return
        dt *= SPEED_UP
        self.now += dt
        fx, fy = sim.focus()[:2]
        self.cool -= dt
        if self.cool <= 0.0 and len(self.convoys) < MAX_ACTIVE and self.open() and sim.mode is not None:
            self.cool = self.rng.uniform(6.0, 16.0)
            self._try_spawn(fx, fy)
        self._monitor(dt)
        for cv in list(self.convoys):
            cv.update(dt)
            if cv.done or cv.near(fx, fy) > LOSE or not self.open() and cv.state == "work":
                cv.remove_all()
                self.convoys.remove(cv)
        if self.n_paint > 14000:                                   # keep the long-ago paint of faraway streets out of memory
            far = [(k, v) for k, v in self.paint.items() if abs(k[0] * 48 - fx) > 900 or abs(k[1] * 48 - fy) > 900]
            for k, v in far:
                self.n_paint -= len(v)
                del self.paint[k]

    def sound(self, aud, fx, fy, rng):
        """Compressor and spray hiss at the paint truck, the cone truck's reversing beeper, now and then a clank of cones."""
        cv = min(self.convoys, key=lambda c: c.near(fx, fy), default=None)
        d = cv.near(fx, fy) if cv else 1e9
        spraying = cv is not None and cv.state == "work" and d < 90.0 and spray_on(self.now)
        aud.loop("spray", 0.55 * (1.0 - d / 90.0) if spraying else 0.0, 0.9, "sfx")          # hiss in bursts, in step with the mist
        for x, y, kind in self.events:
            if abs(x - fx) < 100 and abs(y - fy) < 100:
                aud.at("metal_clank", x, y, 0.8, 1.0 if kind == "put" else 1.25, "ambient", 100.0, 8.0)
        self.events.clear()
        if cv is not None and d < 90.0 and rng.random() < 0.012:
            b = cv.veh[1][0] if len(cv.veh) > 1 else cv.veh[0][0]
            aud.at(rng.choice(("truck_reverse_beep", "metal_clank", "metal_clank")), b.x, b.y, 0.6, 1.0, "ambient", 90.0, 10.0)

    def _monitor(self, dt):
        """Once a second: how many cars stand (< 0.5 m/s) on a street with a working convoy, and for how long the worst queue lasted."""
        self._mon -= dt
        if self._mon > 0.0 or not self.convoys:
            return
        self._mon = 1.0
        for cv in self.convoys:                                    # a loaded save drops the AI-driven bodies: put the trucks back
            for v in cv.veh:
                if v[0] not in self.sim.bodies:
                    self.sim.bodies.append(v[0])
        ours = {(cv.ei, cv.d) for cv in self.convoys}
        n = sum(1 for c in self.sim.traffic.cars if (c.e, c.d) in ours and c.v < 0.5)
        self.stats["queue_max"] = max(self.stats["queue_max"], n)
        if n >= 3:
            self.stats["jam_s"] += 1.0

    # ------------------------------------------------------------------ paint
    def add_paint(self, x1, y1, x2, y2, width, kind):
        k = (int(((x1 + x2) / 2) // 48), int(((y1 + y2) / 2) // 48))
        self.paint.setdefault(k, []).append((x1, y1, x2, y2, width / 2, kind, self.now))
        self.n_paint += 1

    def draw3d(self, rect, ground_y, rl):
        """Fresh paint (black-out bands and wet-to-dry lines) and the cones, as flat quads / small cones just above the road."""
        if not self.paint and not self.cone_bodies:
            return
        now = self.now
        rl.rl_disable_depth_mask()
        rl.rl_begin(rl.RL_TRIANGLES)
        x0, x1 = int(rect[0] // 48) - 1, int(rect[2] // 48) + 1
        y0, y1 = int(rect[1] // 48) - 1, int(rect[3] // 48) + 1
        for black in (0, 1):                                       # the black-out bands first, then the lines on top of them
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    for sx, sy, ex, ey, hw, kind, t0 in self.paint.get((cx, cy), ()):
                        if kind != black:
                            continue
                        self.drawn += 1
                        dry = min(1.0, (now - t0) / DRY_T)
                        if kind == 0:
                            c = tuple(int(a + (b - a) * dry) for a, b in zip(BLACK_WET, BLACK_DRY))
                        else:
                            c = tuple(int(a + (b - a) * dry) for a, b in zip(WHITE_WET, WHITE_DRY)) + (255,)
                        dx, dy = ex - sx, ey - sy
                        ln = math.hypot(dx, dy) or 1.0
                        nx, ny = -dy / ln * hw, dx / ln * hw
                        y_a = ground_y(sx, sy) + LIFT + 0.012 * kind
                        y_b = ground_y(ex, ey) + LIFT + 0.012 * kind
                        if DEBUG_COLOURS:
                            c = (60, 90, 255, 255) if kind == 0 else (255, 40, 40, 255)
                        rl.rl_color4ub(c[0], c[1], c[2], c[3])
                        p0, p1 = (sx + nx, y_a, sy + ny), (ex + nx, y_b, ey + ny)
                        p2, p3 = (ex - nx, y_b, ey - ny), (sx - nx, y_a, sy - ny)
                        for q in (p0, p1, p2, p0, p2, p3):
                            rl.rl_vertex3f(*q)
        rl.rl_end()
        rl.rl_enable_depth_mask()
        if spray_on(now):
            rl.rl_disable_depth_mask()
            rl.rl_begin(rl.RL_TRIANGLES)
            for cv in self.convoys:
                if cv.state != "work" or not cv.veh:
                    continue
                b = cv.veh[0][0]
                if not (rect[0] - 6 < b.x < rect[2] + 6 and rect[1] - 6 < b.y < rect[3] + 6):
                    continue
                ca, sa = math.cos(b.h), math.sin(b.h)
                gx, gz = b.x - ca * GUN - (-sa) * 2.45, b.y - sa * GUN - ca * 2.45     # the gun hangs out on the left
                gy = ground_y(gx, gz)
                ph = (now % 1.1) / 0.6
                for k in range(7):                                                   # a cone of mist from the nozzle to the line, jittering
                    a0 = 2 * math.pi * k / 7 + now * 9.0
                    a1 = a0 + 0.9
                    r = 0.22 + 0.16 * ph + 0.05 * math.sin(now * 40 + k)
                    rl.rl_color4ub(255, 255, 255, 190)
                    rl.rl_vertex3f(gx, gy + 0.62, gz)
                    rl.rl_color4ub(250, 250, 250, 50)
                    rl.rl_vertex3f(gx + r * math.cos(a0), gy + 0.07, gz + r * math.sin(a0))
                    rl.rl_vertex3f(gx + r * math.cos(a1), gy + 0.07, gz + r * math.sin(a1))
            rl.rl_end()
            rl.rl_enable_depth_mask()
        if self.cone_bodies:
            rl.rl_begin(rl.RL_TRIANGLES)
            for b in self.cone_bodies:
                if not (rect[0] - 4 < b.x < rect[2] + 4 and rect[1] - 4 < b.y < rect[3] + 4):
                    continue
                gy = ground_y(b.x, b.y)
                self._cone(rl, b.x, gy, b.y)
            rl.rl_end()

    @staticmethod
    def _cone(rl, x, gy, z):
        """One traffic cone: a black square foot, an orange cone with a white reflective band, 6 sides."""
        n = 6
        r0, r1, r2 = 0.16, 0.115, 0.04
        y1, y2, y3 = 0.30, 0.42, 0.70
        for i in range(n):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            lit = 0.72 + 0.28 * math.cos((a0 + a1) / 2 - 0.9)
            c_o = (int(244 * lit), int(104 * lit), int(26 * lit), 255)
            c_w = (int(238 * lit), int(238 * lit), int(232 * lit), 255)
            for ra, rb, ya, yb, col in ((r0, r1, 0.03, y1, c_o), (r1, 0.098, y1, y2, c_w), (0.098, r2, y2, y3, c_o)):
                rl.rl_color4ub(*col)
                p = ((x + ra * math.cos(a0), gy + ya, z + ra * math.sin(a0)), (x + ra * math.cos(a1), gy + ya, z + ra * math.sin(a1)),
                     (x + rb * math.cos(a1), gy + yb, z + rb * math.sin(a1)), (x + rb * math.cos(a0), gy + yb, z + rb * math.sin(a0)))
                for k in (0, 1, 2, 0, 2, 3):
                    rl.rl_vertex3f(*p[k])
        f = 0.2                                                    # the foot
        rl.rl_color4ub(30, 30, 34, 255)
        for k in (0, 1, 2, 0, 2, 3):
            px, pz = ((-f, -f), (f, -f), (f, f), (-f, f))[k]
            rl.rl_vertex3f(x + px, gy + 0.035, z + pz)
