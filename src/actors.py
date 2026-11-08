"""Simulation: car physics with damage, traffic, pedestrians, on-foot play, hijacking, pickups."""
from texts import TXT
import math
import random

import bible_lines
import bump_lines
import clock
import peds_lines
import talk
import trains
import projectiles
import slang
import vehicles

_LINES = {}

# weapons: key -> (Macedonian name, seconds between shots, damage, pellets, spread rad, range m, ammo per pickup)
WEAPONS = {"pistol": (TXT("actors.0001"), 0.28, 45, 1, 0.0, 40, 90), "uzi": (TXT("actors.0002"), 0.09, 22, 1, 0.06, 32, 300),
           "shotgun": (TXT("actors.0003"), 0.85, 30, 6, 0.16, 18, 60), "kalash": (TXT("actors.0004"), 0.12, 40, 1, 0.03, 60, 240),
           "bat": (TXT("actors.0005"), 0.55, 34, 1, 0.0, 1.9, 9999), "zolja": (TXT("actors.0006"), 1.6, 400, 1, 0.0, 90, 14),
           "knuckles": ("Боксирач", 0.3, 28, 1, 0.0, 1.2, 9999), "chain": ("Ланец", 0.5, 26, 1, 0.0, 2.6, 9999)}
MELEE = ("bat", "knuckles", "chain")                # swung, not fired: no tracer, no ammo used
SWING_T = 0.36                  # seconds of one bat swing (the renderer sweeps the bat across the body)
WEAPON_ORDER = ["fist", "knuckles", "chain", "bat", "pistol", "uzi", "shotgun", "kalash", "zolja"]
FUEL_KM = 14.0                 # a full tank of the player's car lasts about this many kilometres (NPC cars never run dry)


def lines(kind, arch):
    """What a pedestrian of type `arch` says while doing `kind` (idle / hit / panic / fight / ko); cached."""
    k = (kind, arch)
    if k not in _LINES:
        a = vehicles.PED_IDS[arch]
        _LINES[k] = {"idle": lambda: peds_lines.idle(a) + slang.PED_MUTTER, "hit": lambda: peds_lines.hit(a) + slang.PED_HIT,
                     "panic": lambda: peds_lines.panic(a) + slang.PED_PANIC, "fight": lambda: peds_lines.fight(a) + slang.FIGHT_BACK,
                     "ko": lambda: peds_lines.KO + slang.KO_PED}[kind]()
    return _LINES[k]

# collision circle layout per body kind: (offset along axis, radius)
CIRC = vehicles.CIRC
CAR_NAMES = vehicles.NAMES
PLAYER_NAME = TXT("actors.0007")


# ===================================================================== cars with physics & damage
class Body:
    """A car driven by physics: the player's car, abandoned/hijacked cars, parked cars, wrecks."""

    def __init__(self, x, y, h, kind=1, color=0):
        self.x, self.y, self.h = x, y, h
        self.vx = self.vy = self.w = 0.0
        self.steer = 0.0
        self.wheel = 0.0             # front-wheel angle drawn (rad)
        self.kind, self.color = kind, color
        self.health = 100.0
        self.dents = []              # (lx, lz, nx, nz, mag) in local space
        self.dirty = False           # model needs rebuilding
        self.model = None            # own (dented) model, else shared
        self.player_car = False
        self.empty = True
        self.burn = 0.0              # seconds on fire
        self.exploded = False
        self.drown = 0.0
        self.parked_idx = None
        self.rental = False          # rental e-scooter still standing at its spot (rentals.py)
        self.skid = None             # previous rear wheel positions
        self.slip = 0.0
        self.braking = False
        self.name = CAR_NAMES[kind]
        self.honk_t = 0.0
        self.age = 0.0
        self.ctl = None              # (throttle, steer, handbrake) when an AI (emergency service) drives it
        self.service = False
        self.fuel = random.uniform(0.35, 1.0)   # only the player's car uses it up
        self.siren = False
        self.out = False             # fire put out
        self.lx, self.ly = x, y
        self.az = None               # absolute height of the wheels (None -> ground, set on first update)
        self.vz = 0.0
        self.air = False             # between a deck and the ground
        self.pitch = 0.0             # tilt on slopes (rad): nose up > 0
        self.roll = 0.0
        self.ignite = 0.0            # 0..1: heat soaked up from burning neighbours (1 -> catches fire)
        self.fire_lvl = 1.0          # flames left (the fire brigade brings it down to 0)
        self.door = 0.0              # driver's door: 0 shut .. 1 wide open (carjack animation, drawn by the renderer)

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def alive(self):
        return self.health > 0 and not self.exploded


def offsets(kind):
    """Centres of the collision circles along the car: spaced at most one radius apart, so long buses and trucks
    have no gaps a wall corner or lamp post can slip into."""
    off, r = CIRC[kind]
    n = max(3, int(math.ceil(2 * off / (r * 0.9))) + 1)
    return [-off + 2 * off * i / (n - 1) for i in range(n)]


def circles(b):
    off, r = CIRC[b.kind]
    fx, fy = math.cos(b.h), math.sin(b.h)
    return [(b.x + fx * o, b.y + fy * o) for o in offsets(b.kind)], r


def bump(b, impact, wx, wy, nx, ny):
    """Apply damage + a dent. (nx,ny) is the normal pointing from the obstacle toward the car."""
    if impact < 1.2:
        return
    b.health -= max(0.0, impact - 2.0) * 3.4 / 1.33 * (0.3 if b.service else 0.5 if vehicles.LARGE[b.kind] else 1.0)   # sturdy builds
    mag = min(0.08 + impact * 0.04, 0.8)
    dx, dy = wx - b.x, wy - b.y
    c, s = math.cos(b.h), math.sin(b.h)
    lx, lz = dx * c + dy * s, -dx * s + dy * c
    b.dents.append((lx, lz, nx * c + ny * s, -nx * s + ny * c, mag))
    if len(b.dents) > 9:
        a, d = b.dents[0], b.dents[1]
        b.dents[:2] = [((a[0] + d[0]) / 2, (a[1] + d[1]) / 2, (a[2] + d[2]) / 2, (a[3] + d[3]) / 2, min(0.9, a[4] + d[4] * 0.6))]
    b.dirty = True


TURN = 0.67                  # turning radius of every vehicle relative to the bicycle model: 33 % tighter


def drive(p, throttle, steer_in, handbrake, dt, world):
    VMAX, ACC, STEER, GRIP, _M = vehicles.PERF[p.kind]
    if p.exploded or (p.health <= 0 and p.ctl is not None):   # a burnt-out wreck never drives again; a burning AI car stops
        throttle, steer_in, handbrake = 0.0, 0.0, True
    BRAKE, REV = 22.0 + ACC, 9.0
    L_ = vehicles.DIMS[p.kind][0]
    wb = L_ * 0.62 if L_ < 6 else 3.7 + (L_ - 6) * 0.35   # long vehicles: wheelbase, not length (articulated / rear-axle steer)
    dmg = 1.0 if p.health > 35 else 0.7           # a wrecked engine is slower
    fx, fy = math.cos(p.h), math.sin(p.h)
    vf = p.vx * fx + p.vy * fy
    p.steer += (steer_in - p.steer) * min(1.0, (9.0 if steer_in else 14.0) * dt)
    maxang = STEER / (1.0 + abs(vf) / (8.0 if L_ < 6 else 13.0))
    p.wheel = p.steer * maxang
    om = 0.0
    if abs(vf) > 0.15:
        om = vf / (wb * TURN) * math.tan(p.steer * maxang)
        if handbrake:
            om *= 1.4
        p.h += om * dt
    # the car turns about its rear axle (the front wheels steer): its middle, a little ahead of that, moves sideways into
    # the turn as it yaws -- without this it pivoted about its middle and the tail swung out as if the rear wheels steered
    vk = 0.0 if handbrake else om * L_ * (0.31 if L_ < 11 else 0.33)
    fx, fy = math.cos(p.h), math.sin(p.h)
    rx, ry = -fy, fx
    vf = p.vx * fx + p.vy * fy
    vl = p.vx * rx + p.vy * ry
    p.braking = False
    if throttle > 0:
        top = VMAX * dmg                          # thrust tapers off and just beats drag at the rated top speed
        vf += (ACC * dmg * max(0.0, 1 - (vf / top) ** 3) + (vf * vf * 0.00085 + 0.25) * min(1.0, vf / top) if vf >= 0 else BRAKE) * dt * throttle
        p.braking = vf < 0
    elif throttle < 0:
        if vf > 0.8:
            vf -= BRAKE * dt
            p.braking = True
        else:
            vf -= REV * max(0.0, 1 + vf / 11.0) * dt
    if world.hilly and not p.air:                                   # gravity along the slope: a = -g sin(angle)
        az = p.az if p.az is not None else world.ground_y(p.x, p.y)
        sl = world.slope_at(p.x, p.y, fx, fy, az, 1.4)
        vf -= world.G * sl / math.sqrt(1.0 + sl * sl) * dt
        if handbrake and throttle == 0 and abs(vf) < 1.5 and abs(world.G * sl) < 6.0:      # parking brake holds
            vf = 0.0
            vl = 0.0
    sf = world.surface(p.x, p.y)
    if sf == 0:
        vf *= math.exp(-0.45 * dt)
    lift = 1.25 if throttle == 0 else 1.0                           # off the gas the car slows 25 % faster
    vf -= (vf * abs(vf) * 0.00085 * dt + (0.25 * dt if vf > 0 else -0.25 * dt if vf < 0 else 0)) * lift
    if handbrake:
        vf *= math.exp(-1.1 * dt)
        p.braking = True
    grip = 1.8 if handbrake else (GRIP * 0.63 if sf == 0 else GRIP)
    p.slip = abs(vl - vk)
    vl = vk + (vl - vk) * math.exp(-grip * dt)
    p.vx, p.vy = fx * vf + rx * vl, fy * vf + ry * vl
    p.x += p.vx * dt
    p.y += p.vy * dt


def settle(b, w, dt, ev=None):
    """Put a car on the surface under it (terrain or bridge deck); drops it when that surface ends.  Sets pitch/roll."""
    if b.az is not None and (b.x - b.lx) ** 2 + (b.y - b.ly) ** 2 > 400.0:      # teleported
        b.az, b.vz = None, 0.0
    b.lx, b.ly = b.x, b.y
    if b.az is None:
        b.az = w.ground_y(b.x, b.y)
    tgt = w.level(b.x, b.y, b.az)
    if b.air or b.az > tgt + getattr(b, "lift", 0.0) + 0.12 or b.vz > 0.0:   # off the edge of a deck: falling
        b.air = True
        b.vz -= w.G * dt
        b.az += b.vz * dt
        if b.az <= tgt:
            imp = -b.vz
            b.az, b.vz, b.air = tgt, 0.0, False
            if imp > 5.0:
                b.health -= (imp - 5.0) * 5.0 / 1.33          # 33% sturdier cars
                b.dirty = True
                if ev:
                    ev("fall", body=b, speed=imp, x=b.x, y=b.y)
            if ev and w.wet(b.x, b.y, b.az):
                ev("splash", x=b.x, y=b.y)
        b.pitch *= 0.9
        b.roll *= 0.9
        return
    b.az = tgt
    b.vz = 0.0
    wb = vehicles.DIMS[b.kind][0] * 0.31
    fx, fy = math.cos(b.h), math.sin(b.h)
    rx, ry = -fy, fx
    pt = math.atan2(w.level(b.x + fx * wb, b.y + fy * wb, tgt) - w.level(b.x - fx * wb, b.y - fy * wb, tgt), 2 * wb)
    rl_ = math.atan2(w.level(b.x - rx * 0.85, b.y - ry * 0.85, tgt) - w.level(b.x + rx * 0.85, b.y + ry * 0.85, tgt), 1.7)
    lift = 0.0
    if math.hypot(b.vx, b.vy) > 0.8 and hasattr(w, "kerb"):    # wheels up on the pavement: bumpy, slower, tilted
        W2 = vehicles.DIMS[b.kind][1] * 0.42
        on = [w.kerb(b.x + fx * u + rx * v, b.y + fy * u + ry * v) for u, v in ((wb, W2), (wb, -W2), (-wb, W2), (-wb, -W2))]
        n = sum(on)
        if n:
            H = w.KERB_H
            pt += math.atan2(H * ((on[0] + on[1]) - (on[2] + on[3])) / 2, 2 * wb)
            rl_ += math.atan2(H * ((on[1] + on[3]) - (on[0] + on[2])) / 2, 2 * W2)
            lift = H * n / 4
            f = math.exp(-0.5 * n * dt)
            b.vx *= f
            b.vy *= f
        if n > getattr(b, "kerb_n", 0) and math.hypot(b.vx, b.vy) > 3.5:
            if ev:
                ev("kerb", body=b, speed=math.hypot(b.vx, b.vy), x=b.x, y=b.y)
            b.w += (0.5 - (hash((int(b.x), int(b.y))) & 1)) * 0.25     # the jolt kicks the steering a little
        b.kerb_n = n
    b.lift = getattr(b, "lift", 0.0) + (lift - getattr(b, "lift", 0.0)) * min(1.0, dt * 12)
    b.az = tgt + b.lift
    k = min(1.0, dt * 9)
    b.pitch += (pt - b.pitch) * k
    b.roll += (rl_ - b.roll) * k


def collide_static(p, world):
    """Walls, trees, lamp posts. Returns [(kind, impact, wx, wy, nx, ny)]."""
    events = []
    fx, fy = math.cos(p.h), math.sin(p.h)
    off, R = CIRC[p.kind]
    az = p.az if p.az is not None else 0.0
    high = p.az is not None and p.az - world.ground_y(p.x, p.y) > 4.0          # on a deck high above the buildings
    top = az + 1.5
    for _ in range(2):
        for o in offsets(p.kind):
            cx, cy = p.x + fx * o, p.y + fy * o
            for ax, ay, bx, by in (() if high else world.edges_near(cx, cy, R + 0.1)):
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((cx - ax) * dx + (cy - ay) * dy) / l2))
                qx, qy = ax + dx * t, ay + dy * t
                ex, ey = cx - qx, cy - qy
                d = math.hypot(ex, ey)
                if d >= R:
                    continue
                if d < 1e-6:
                    l = math.sqrt(l2) or 1.0
                    nx, ny = -dy / l, dx / l
                else:
                    nx, ny = ex / d, ey / d
                pen = R - d
                p.x += nx * pen
                p.y += ny * pen
                cx += nx * pen
                cy += ny * pen
                vn = p.vx * nx + p.vy * ny
                if vn < 0:
                    p.vx -= 1.3 * vn * nx
                    p.vy -= 1.3 * vn * ny
                    p.vx *= 0.97
                    p.vy *= 0.97
                    p.h += (o * (fx * ny - fy * nx)) * vn * 0.02
                    events.append(("wall", -vn, qx, qy, nx, ny))
            for tx, ty, tr, lo, hi in world.points_near(cx, cy, R + 0.8):
                if p.az is not None and (hi < az + 0.05 or lo > top):
                    continue
                ex, ey = cx - tx, cy - ty
                d = math.hypot(ex, ey)
                if d >= R + tr or d < 1e-6:
                    continue
                nx, ny = ex / d, ey / d
                pen = R + tr - d
                p.x += nx * pen
                p.y += ny * pen
                cx += nx * pen
                cy += ny * pen
                vn = p.vx * nx + p.vy * ny
                tree = tr >= 0.45 and hi - lo > 4.0
                light = hi - lo < 3.5                              # benches, bins, junk: knocked over by any real touch
                if -vn > (9.0 if tree else 1.2 if light else 2.5) and hasattr(world, "break_point"):   # everything breaks, the car pays
                    world.break_point((tx, ty, tr, lo, hi))
                    p.x -= nx * pen
                    p.y -= ny * pen
                    k = 0.55 if tree else (0.95 if light else 0.8 if tr > 0.3 else 0.88)
                    p.vx *= k
                    p.vy *= k
                    p.h += (o * (fx * ny - fy * nx)) * vn * 0.01
                    events.append(("break_tree" if tree else "break", -vn * (0.7 if tree else 0.45), tx, ty, nx, ny))
                    break
                if vn < 0:
                    p.vx -= 1.15 * vn * nx
                    p.vy -= 1.15 * vn * ny
                    p.vx *= 0.8
                    p.vy *= 0.8
                    p.h += (o * (fx * ny - fy * nx)) * vn * 0.03
                    events.append(("tree" if tr > 0.3 else "lamp", -vn, tx, ty, nx, ny))
    return events


def _rad(kind):
    L, W = vehicles.DIMS[kind][0] / 2, vehicles.DIMS[kind][1] / 2
    return math.hypot(L, W) + 0.05


_RAD = [_rad(k) for k in range(len(vehicles.DIMS))]          # radius of the circle around each car's 2D box


LOD_FAR2 = 100.0 ** 2          # beyond this distance from the player cars and walkers are simulated at a third of the rate
LOD_NEAR2 = 35.0 ** 2          # always full rate this close to the player, whatever the camera shows
_CELL = 10.0


def _lod_far(owner, x, y, d2):
    """True when (x, y) is off screen: outside the camera's ground rectangle (sim.view_rect) and not right beside the player.
    No rectangle (street / selfie / cine camera, which can look any way): the old 100 m circle."""
    sim = owner.sim
    vr = getattr(sim, "view_rect", None) if sim is not None else None
    if vr is None:
        return d2 > LOD_FAR2
    return d2 > LOD_NEAR2 and not (vr[0] < x < vr[2] and vr[1] < y < vr[3])


def _cells(objs):
    """Bucket objects with .x/.y into a _CELL grid (rebuilt every frame: cheap, objects move)."""
    g = {}
    for b in objs:
        g.setdefault((int(b.x // _CELL), int(b.y // _CELL)), []).append(b)
    return g


def _near(g, x, y):
    """Objects in the 3x3 cells around (x, y): everything within _CELL metres, plus some."""
    cx, cy = int(x // _CELL), int(y // _CELL)
    res = []
    for i in (cx - 1, cx, cx + 1):
        for j in (cy - 1, cy, cy + 1):
            c = g.get((i, j))
            if c:
                res.extend(c)
    return res


def body_pairs(bodies):
    """Broadphase: every pair of cars whose bounding circles overlap, found with a 16 m grid (cars are < 12 m long)."""
    grid = {}
    for i, b in enumerate(bodies):
        grid.setdefault((int(b.x // 16), int(b.y // 16)), []).append(i)
    out = []
    for (cx, cy), idx in grid.items():
        cand = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cand.extend(grid.get((cx + dx, cy + dy), ()))
        for i in idx:
            a = bodies[i]
            for j in cand:
                if j <= i:
                    continue
                b = bodies[j]
                r = _RAD[a.kind] + _RAD[b.kind]
                if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 < r * r:
                    out.append((i, j))
    return out


def push_from_box(b, px, py, r):
    """A circle (px, py, r) against the oriented box of car b: (nx, ny, penetration) pushing the circle out, or None."""
    L, W = vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2
    c, s_ = math.cos(b.h), math.sin(b.h)
    dx, dy = px - b.x, py - b.y
    u, v = dx * c + dy * s_, -dx * s_ + dy * c                        # circle centre in the car's frame
    qu, qv = max(-L, min(L, u)), max(-W, min(W, v))
    eu, ev_ = u - qu, v - qv
    d = math.hypot(eu, ev_)
    if d >= r:
        return None
    if d > 1e-6:
        nu, nv, pen = eu / d, ev_ / d, r - d
    else:                                                              # centre inside the box: leave by the nearest side
        gaps = (L - u, u + L, W - v, v + W)
        k = gaps.index(min(gaps))
        nu, nv = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))[k]
        pen = min(gaps) + r
    return nu * c - nv * s_, nu * s_ + nv * c, pen


class _At:
    """The car as it was |dt| seconds ago (dt < 0), for the swept walker test: only the fields push_from_box reads."""

    def __init__(self, b, dt):
        self.x, self.y, self.h, self.kind = b.x + b.vx * dt, b.y + b.vy * dt, b.h, b.kind


def _corners(b):
    L, W = vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2
    fx, fy = math.cos(b.h), math.sin(b.h)
    return [(b.x + fx * u - fy * v, b.y + fy * u + fx * v) for u, v in ((L, W), (L, -W), (-L, -W), (-L, W))]


def collide_bodies(a, b, ma=1.0, mb=1.0):
    """Oriented-box car/car collision (separating axis test) with a rigid-body impulse at the contact corner:
    a hit on the rear quarter spins the car, a head-on stops it. Returns (impact, wx, wy, nx, ny) or None,
    n pointing from a to b."""
    r_ = _RAD[a.kind] + _RAD[b.kind]
    if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 > r_ * r_:        # bounding circles apart: cannot touch at any angle
        return None
    pa, pb = _corners(a), _corners(b)
    best_pen, n_ = 1e9, None
    for h in (a.h, a.h + math.pi / 2, b.h, b.h + math.pi / 2):
        ax_, ay_ = math.cos(h), math.sin(h)
        A = [x * ax_ + y * ay_ for x, y in pa]
        B = [x * ax_ + y * ay_ for x, y in pb]
        pen = min(max(A), max(B)) - max(min(A), min(B))
        if pen <= 0:
            return None
        if pen < best_pen:
            best_pen, n_ = pen, (ax_, ay_)
    nx, ny = n_
    if (b.x - a.x) * nx + (b.y - a.y) * ny < 0:
        nx, ny = -nx, -ny
    # contact: the corner of one box that sits deepest inside the other
    da = max(pa, key=lambda c: (c[0] - a.x) * nx + (c[1] - a.y) * ny)
    db = min(pb, key=lambda c: (c[0] - b.x) * nx + (c[1] - b.y) * ny)
    wx, wy = (da[0] + db[0]) / 2, (da[1] + db[1]) / 2
    tot = ma + mb
    pen = min(best_pen, 1.5)
    a.x -= nx * pen * mb / tot
    a.y -= ny * pen * mb / tot
    b.x += nx * pen * ma / tot
    b.y += ny * pen * ma / tot
    rax, ray = wx - a.x, wy - a.y
    rbx, rby = wx - b.x, wy - b.y
    va = (a.vx - a.w * ray, a.vy + a.w * rax)
    vb = (b.vx - b.w * rby, b.vy + b.w * rbx)
    rv = (vb[0] - va[0]) * nx + (vb[1] - va[1]) * ny
    if rv >= 0:
        return None
    Ia = ma * (vehicles.DIMS[a.kind][0] ** 2 + vehicles.DIMS[a.kind][1] ** 2) / 12
    Ib = mb * (vehicles.DIMS[b.kind][0] ** 2 + vehicles.DIMS[b.kind][1] ** 2) / 12
    ca = rax * ny - ray * nx
    cb = rbx * ny - rby * nx
    j = -(1 + 0.3) * rv / (1 / ma + 1 / mb + ca * ca / Ia + cb * cb / Ib)
    a.vx -= j * nx / ma
    a.vy -= j * ny / ma
    b.vx += j * nx / mb
    b.vy += j * ny / mb
    a.w -= ca * j / Ia * 0.35                       # (damped: tyres resist the spin)
    b.w += cb * j / Ib * 0.35
    tx, ty = -ny, nx                                # scraping friction along the contact
    rt = (vb[0] - va[0]) * tx + (vb[1] - va[1]) * ty
    jt = max(-0.4 * j, min(0.4 * j, -rt / (1 / ma + 1 / mb)))
    a.vx -= jt * tx / ma
    a.vy -= jt * ty / ma
    b.vx += jt * tx / mb
    b.vy += jt * ty / mb
    imp = -rv
    bump(a, imp, wx, wy, -nx, -ny)
    bump(b, imp, wx, wy, nx, ny)
    return (imp, wx, wy, nx, ny)


# ===================================================================== pedestrians
CLEAR_GAME_MIN = 20.0             # bodies and burnt wrecks stay this many in-game minutes


def clear_secs(sim):
    """Real seconds that CLEAR_GAME_MIN in-game minutes take at the current clock speed."""
    c = getattr(sim, "clock", None)
    return CLEAR_GAME_MIN / 60.0 * (c.SECONDS_PER_HOUR / max(0.05, c.speed) if c else 55.0)


class Ped:
    def __init__(self):
        self.mode = "walk"           # walk | dead | flee | rage | air
        self.t = 0.0
        self.vx = self.vy = 0.0
        self.anim = 0.0
        self.hy = 0.0                # height above ground (when launched)
        self.hv = 0.0
        self.spin = 0.0
        self.skin = 0
        self.arch = 0                # archetype, see vehicles.PED_NAMES
        self.hp = 40.0
        self.atk_t = 0.0             # > 0 while a punch/kick animation plays
        self.atk_cd = 0.0
        self.atk_kind = 4
        self.looted = False
        self.foe = None              # the other pedestrian in a street brawl
        self.bumps = 0               # times the player walked into them (they cuss, then fight)
        self.bump_cd = 0.0
        self.bump_t = 0.0
        self.far_t = 0.0             # seconds spent far from the player while chasing them
        self.pose = None             # emergency crews: "spray" (hose out) / "cpr" (kneeling over a patient)
        self.say_t = random.uniform(4, 18)
        self.e = 0
        self.d = 1
        self.s = 0.0
        self.v = 1.3
        self.side = 1
        self.shirt = 0
        self.x = self.y = self.h = 0.0
        self.gz = None               # height of the surface they stand on (terrain or bridge deck)
        self.ko_land = False         # thrown out of a car / off a bike: lands unconscious instead of dead
        self.blk = 0.0               # seconds pressed against a standing vehicle
        self.vault = 0.0             # > 0: hopping over (hy arcs) or ducking under a vehicle that stands in the way
        self.vault_t = 1.0
        self.vault_up = True

    @property
    def dead(self):
        return self.mode in ("dead", "air")


class Walker:
    """The player on foot."""

    def __init__(self, x, y, h):
        self.x, self.y, self.h = x, y, h
        self.vx = self.vy = 0.0
        self.anim = 0.0
        self.health = 100.0
        self.moving = False
        self.run = False
        self.dead_t = 0.0
        self.z = 0.0                 # height above the surface under the feet (jumping / falling)
        self.duck_t = 0.0            # > 0: crawling under a big vehicle (slow, crouched)
        self.duck_b = None
        self.vz = 0.0
        self.az = None               # absolute feet height (None -> ground)
        self.land_v = 0.0            # vertical speed of the last landing (Sim turns hard ones into damage)
        self.grade = 0.0             # slope in the walking direction
        self.lx, self.ly = x, y
        self.weapon = "fist"
        self.guns = {}               # weapon -> ammo (Tab cycles through the ones with ammo)
        self.atk_t = 0.0
        self.atk_cd = 0.0
        self.atk_kind = 4
        self.combo = 0
        self.hurt_t = 0.0
        self.inv_t = 0.0
        self.cause = None            # "fight" -> knocked out, "car"/"explosion" -> dead

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def ammo(self):
        return self.guns.get(self.weapon, 0)

    @ammo.setter
    def ammo(self, v):
        if self.weapon != "fist":
            self.guns[self.weapon] = max(0, v)

    def give(self, kind):
        self.guns[kind] = self.guns.get(kind, 0) + WEAPONS[kind][6]
        self.weapon = kind

    def cycle(self):
        """Tab: next weapon that has ammo (fists always)."""
        have = [w for w in WEAPON_ORDER if w == "fist" or self.guns.get(w, 0) > 0]
        i = have.index(self.weapon) if self.weapon in have else 0
        self.weapon = have[(i + 1) % len(have)]
        return self.weapon

    def push_out(self, world):
        """Keep the player out of walls, trees and posts (also after a car shoved it)."""
        R = 0.38
        high = self.az - world.ground_y(self.x, self.y) > 4.0
        for ax, ay, bx, by in (() if high else world.edges_near(self.x, self.y, R + 0.1)):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((self.x - ax) * dx + (self.y - ay) * dy) / l2))
            ex, ey = self.x - (ax + dx * t), self.y - (ay + dy * t)
            d = math.hypot(ex, ey)
            if 1e-6 < d < R:
                self.x += ex / d * (R - d)
                self.y += ey / d * (R - d)
        for tx, ty, tr, lo, hi in world.points_near(self.x, self.y, R + 0.8):
            if hi < self.az + 0.1 or lo > self.az + 1.7:         # other level (deck above / ground below)
                continue
            ex, ey = self.x - tx, self.y - ty
            d = math.hypot(ex, ey)
            if 1e-6 < d < R + tr:
                self.x += ex / d * (R + tr - d)
                self.y += ey / d * (R + tr - d)

    def update(self, dt, turn, fwd, run, world, jump=False):
        """turn = A/D (-1..1) rotates, fwd = W/S (-1..1) walks forward/backward. SPACE jumps."""
        self.atk_t = max(0.0, self.atk_t - dt)
        self.atk_cd = max(0.0, self.atk_cd - dt)
        self.hurt_t = max(0.0, self.hurt_t - dt)
        self.inv_t = max(0.0, self.inv_t - dt)
        if self.az is not None and (self.x - self.lx) ** 2 + (self.y - self.ly) ** 2 > 400.0:      # teleported
            self.az, self.vz = None, 0.0
        if self.az is None:
            self.az = world.ground_y(self.x, self.y)
        if jump and self.z <= 0.001:
            self.vz = 6.4
            self.az += 0.02
        sp = 9.5 if run else 5.75
        self.h += turn * (3.4 if not run else 3.0) * dt
        k = min(1.0, 12 * dt)
        if world.hilly and self.z <= 0.001:                      # Tobler's hiking function: slow uphill, a little faster gently downhill
            gr = world.slope_at(self.x, self.y, math.cos(self.h) * (1 if fwd >= 0 else -1), math.sin(self.h) * (1 if fwd >= 0 else -1), self.az, 1.0)
            self.grade = gr
            sp *= max(0.15, min(1.25, math.exp(-3.5 * (abs(gr + 0.05) - 0.05))))
        tx, ty = math.cos(self.h) * fwd * (sp if fwd > 0 else sp * 0.6), math.sin(self.h) * fwd * (sp if fwd > 0 else sp * 0.6)
        self.vx += (tx - self.vx) * k
        self.vy += (ty - self.vy) * k
        self.moving = abs(fwd) > 0.01
        if self.moving:
            self.anim += self.speed * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.push_out(world)
        # ---- vertical: stand on the terrain / deck under the feet, fall when it ends
        sup = world.level(self.x, self.y, self.az)
        if self.az > sup + 0.05 or self.vz > 0.0:
            self.vz -= 16.0 * dt
            self.az += self.vz * dt
            if self.az <= sup and self.vz <= 0.0:
                self.land_v = max(self.land_v, -self.vz)
                self.az, self.vz = sup, 0.0
        else:
            self.az = sup
            self.vz = 0.0
        self.z = max(0.0, self.az - sup)
        self.lx, self.ly = self.x, self.y


def _PED_R(p):
    """Body radius of a pedestrian or road user (m)."""
    nm = vehicles.PED_IDS[p.arch] if 0 <= p.arch < len(vehicles.PED_IDS) else ""
    if nm == "Kocija":
        return 1.1
    if nm in vehicles.RIDERS:
        return 0.55
    return 0.32


class Peds:
    extra = ()                                     # multiplayer: other players this PC simulates the world for (x, y)

    def _d2(self, x, y, fx, fy):
        d = (x - fx) ** 2 + (y - fy) ** 2
        for ex, ey in self.extra:
            d = min(d, (x - ex) ** 2 + (y - ey) ** 2)
        return d

    def _focus(self, fx, fy):
        e = self.extra
        if e and self.rng.random() < len(e) / (len(e) + 1.0):
            return e[self.rng.randrange(len(e))]
        return fx, fy

    def __init__(self, world, rng, target=110):
        self.w = world
        self.rng = rng
        self.list = []
        self.target = target
        self.walker = None           # set by Sim each frame while the player is on foot (fighters chase it)
        self.sim = None              # the Sim (language / aggression settings, places, clock)

    def _place(self, p):
        e = self.w.edges[p.e]
        s = p.s if p.d == 1 else e["len"] - p.s
        x, y, dx, dy = self.w.edge_point(e, s)
        if p.d == -1:
            dx, dy = -dx, -dy
        off = (e["w"] / 2 + 1.0) * p.side if e["drive"] else 0.5 * p.side
        return x - dy * off, y + dx * off, math.atan2(dy, dx)

    def spawn(self, px, py, rmin=95, rmax=240):
        w, rng = self.w, self.rng
        a, r = rng.uniform(0, 6.283), rng.uniform(rmin, rmax)
        cell = (int((px + math.cos(a) * r) // w.sg), int((py + math.sin(a) * r) // w.sg))
        lst = w.walk_cells.get(cell)
        if not lst:
            return
        p = Ped()
        p.e = rng.choice(lst)
        e = w.edges[p.e]
        p.d = rng.choice((1, -1))
        p.s = rng.uniform(0, e["len"])
        p.side = rng.choice((-1, 1))
        p.arch = rng.choices(range(vehicles.PED_COUNT), vehicles.PED_W)[0]
        p.v = rng.uniform(1.0, 1.7) * vehicles.PED_SPEED[p.arch]
        p.shirt = rng.randrange(3)
        p.skin = rng.randrange(4)
        p.hp = float(vehicles.FIGHT[p.arch][0])
        p.x, p.y, p.h = self._place(p)
        if (p.x - px) ** 2 + (p.y - py) ** 2 < rmin * rmin * 0.7:
            return
        self.list.append(p)

    def adopt(self, p):
        """Make p (a bus passenger, ...) an ordinary passer-by on the nearest footway / pavement from where it stands."""
        w = self.w
        best = None
        cx, cy = int(p.x // w.sg), int(p.y // w.sg)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for ei in w.walk_cells.get((ix, iy), ()):
                    e = w.edges[ei]
                    pts, cum = e["pts"], e["cum"]
                    for k in range(len(pts) - 1):
                        (ax, ay), (bx, by) = pts[k], pts[k + 1]
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy or 1.0
                        t = max(0.0, min(1.0, ((p.x - ax) * dx + (p.y - ay) * dy) / l2))
                        d2 = (p.x - ax - dx * t) ** 2 + (p.y - ay - dy * t) ** 2
                        if best is None or d2 < best[0]:
                            best = (d2, ei, cum[k] + t * (cum[k + 1] - cum[k]), -dy * (p.x - ax) + dx * (p.y - ay))
        if best is None:
            return False
        _d, ei, s, lat = best
        e = w.edges[ei]
        p.e, p.d = ei, self.rng.choice((1, -1))
        p.s = s if p.d == 1 else e["len"] - s
        p.side = (1 if lat > 0 else -1) * p.d
        p.mode, p.t = "walk", 0.0
        p.v = self.rng.uniform(1.0, 1.7) * vehicles.PED_SPEED[p.arch]
        return True

    def eject(self, x, y, h, shirt=None, gz=None):
        """A driver pulled out of their car: angry, then runs away."""
        p = Ped()
        p.mode = "rage"
        p.t = 3.2
        p.x, p.y, p.h = x, y, h
        p.gz = gz
        p.arch = self.rng.choice(vehicles.WALKERS)
        p.shirt = self.rng.randrange(3) if shirt is None else shirt
        p.skin = self.rng.randrange(4)
        self.list.append(p)
        return p

    def _start_brawl(self, fx, fy, ev):
        """Two passers-by get into it with each other (more often in an aggressive city)."""
        rng = self.rng
        cand = [p for p in self.list if p.mode == "walk" and 12 < abs(p.x - fx) + abs(p.y - fy) < 150]
        if len(cand) < 2:
            return
        a = rng.choice(cand)
        b = min((q for q in cand if q is not a), key=lambda q: (q.x - a.x) ** 2 + (q.y - a.y) ** 2)
        if (b.x - a.x) ** 2 + (b.y - a.y) ** 2 > 30 ** 2:
            return
        for x, y in ((a, b), (b, a)):
            x.mode, x.t, x.foe, x.atk_cd = "brawl", rng.uniform(7, 14), y, rng.uniform(0.2, 0.9)
        ev("shout", text=talk.react("fight", a.arch, self.sim, lines("fight", a.arch), rng), x=a.x, y=a.y,
           who=vehicles.PED_NAMES[a.arch])

    _SOLID = ("walk", "flee", "rage", "brawl", "fight", "play")

    def _separate(self, dt, fx, fy):
        """People are solid to each other (cyclists, mopeds, scooters and the horse cart included): overlapping pairs are
        pushed apart.  A bigger road user (wider radius) shoves a pedestrian further than the pedestrian moves it."""
        grid = {}
        for p in self.list:
            if p.mode in self._SOLID and (p.x - fx) ** 2 + (p.y - fy) ** 2 < 140 ** 2:
                grid.setdefault((int(p.x // 2.0), int(p.y // 2.0)), []).append(p)
        k = min(1.0, dt * 9.0)
        for (cx, cy), lst in grid.items():
            for i, a in enumerate(lst):
                ra = _PED_R(a)
                for dx_ in (0, 1):
                    for dy_ in (-1, 0, 1):
                        if dx_ == 0 and dy_ < 0:
                            continue
                        o = grid.get((cx + dx_, cy + dy_))
                        if not o:
                            continue
                        for b in (lst[i + 1:] if (dx_, dy_) == (0, 0) else o):
                            if a.mode == "brawl" and b.mode == "brawl" and (a.foe is b or b.foe is a):
                                continue                                  # the two fighters stand toe to toe on purpose
                            if (a.gz is not None and b.gz is not None and abs(a.gz - b.gz) > 2.0):
                                continue                                  # different levels (bridge over street)
                            rb = _PED_R(b)
                            ex, ey = b.x - a.x, b.y - a.y
                            d2 = ex * ex + ey * ey
                            r = ra + rb
                            if d2 >= r * r:
                                continue
                            d = math.sqrt(d2)
                            if d < 1e-4:
                                ex, ey, d = math.cos(id(a) % 6.283), math.sin(id(a) % 6.283), 1.0
                            push = (r - d) * k
                            wa = rb / r                                   # the bigger one moves less
                            nx, ny = ex / d, ey / d
                            a.x -= nx * push * wa
                            a.y -= ny * push * wa
                            b.x += nx * push * (1.0 - wa)
                            b.y += ny * push * (1.0 - wa)
        wk = self.walker                                          # the player on foot is solid too: bump, bounce back, the other gets shoved
        if wk is not None and wk.health > 0 and wk.z < 0.5:
            for (cx, cy) in ((int(wk.x // 2.0) + i, int(wk.y // 2.0) + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
                for p in grid.get((cx, cy), ()):
                    r = _PED_R(p) + 0.38
                    ex, ey = p.x - wk.x, p.y - wk.y
                    d2 = ex * ex + ey * ey
                    if d2 >= r * r or (p.gz is not None and abs(p.gz - wk.az) > 2.0):
                        continue
                    d = math.sqrt(d2) or 1e-4
                    nx, ny = ex / d, ey / d
                    ov = r - d
                    wk.x -= nx * ov * 0.5
                    wk.y -= ny * ov * 0.5
                    p.x += nx * ov * 0.5
                    p.y += ny * ov * 0.5
                    vn = wk.vx * nx + wk.vy * ny
                    if vn > 0:                                    # walking into them: bounce off
                        wk.vx -= nx * vn * 1.6
                        wk.vy -= ny * vn * 1.6

    def _bumped(self, p, wk, ev):
        """The player shoved past p: first a grumble, then insults and threats; after a few bumps p goes for them."""
        rng = self.rng
        p.bumps += 1
        p.bump_cd, p.bump_t = 1.4, 0.0
        aggro = getattr(self.sim, "aggro", 1) if self.sim else 1
        lang = getattr(self.sim, "lang", 1) if self.sim else 1
        temper = vehicles.FIGHT[p.arch][1]
        limit = max(3, (5 if temper < 0.3 else 4) + (1, 0, -1, -1)[aggro % 4])
        kid = vehicles.FIGHT[p.arch][0] <= 16
        stage = min(2, p.bumps - 1) if p.bumps < limit else 3
        dx, dy = wk.x - p.x, wk.y - p.y
        d = math.hypot(dx, dy) or 1e-6
        p.h = math.atan2(dy, dx)                                  # turns on the player
        p.x -= dx / d * 0.12
        p.y -= dy / d * 0.12
        text = bible_lines.bump(vehicles.PED_IDS[p.arch], stage, lang, rng) or bump_lines.line(vehicles.PED_IDS[p.arch], stage, rng)
        if not talk.allowed(text, lang):
            text = bump_lines.line(vehicles.PED_IDS[p.arch], stage, rng)
        ev("shout", text=text, x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
        if stage == 3:
            if kid:                                               # children shout, then run to mama
                p.mode, p.t = "flee", 4.0
                p.vx, p.vy = -dx / d * 3.4, -dy / d * 3.4
            else:
                p.mode, p.t, p.atk_cd, p.far_t = "fight", 14.0, 0.4, 0.0
                p.bumps = 0

    def update(self, dt, fx, fy, bodies, ev):
        w, rng = self.w, self.rng
        out = []
        aggro = getattr(self.sim, "aggro", 1) if self.sim else 1
        tc = self.sim.traffic.cars if self.sim is not None else ()
        g_b, g_a = _cells(bodies), _cells((*bodies, *tc))          # 10 m grids: each person only checks the cars next to them
        dt0 = dt
        self._tick = getattr(self, "_tick", 0) + 1
        for pi, p in enumerate(self.list):
            dt = dt0
            if p.mode == "walk" and _lod_far(self, p.x, p.y, self._d2(p.x, p.y, fx, fy)):      # far from the player: one step in three, three times as long
                if (pi + self._tick) % 3:
                    out.append(p)
                    continue
                dt = dt0 * 3.0
            if p.mode == "svc":                                   # paramedic / fire fighter, moved by Services
                p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
                out.append(p)
                continue
            if p.mode != "walk":
                p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
            # ------------- ragdoll / dead
            if p.mode in ("dead", "air"):
                p.t -= dt
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.spin += (3.0 if p.mode == "air" else 0.0) * dt
                if p.mode == "air":
                    p.hy += p.hv * dt
                    p.hv -= 14.0 * dt
                    if p.hy <= 0 and p.ko_land:
                        p.hy, p.mode, p.t, p.ko_land = 0.0, "ko", rng.uniform(7.0, 11.0), False
                        p.vx *= 0.3
                        p.vy *= 0.3
                    elif p.hy <= 0:
                        p.hy, p.mode = 0.0, "dead"
                        p.vx *= 0.4
                        p.vy *= 0.4
                f = math.exp(-3.0 * dt)
                p.vx *= f
                p.vy *= f
                if p.t > 0:
                    out.append(p)
                continue
            # ------------- hit by a moving car?
            hit = None
            near_b = _near(g_b, p.x, p.y)
            for b in near_b:
                if abs(b.x - p.x) > 4 or abs(b.y - p.y) > 4:
                    continue
                sp = b.speed
                if sp > 2.2 and not b.exploded:
                    fxb, fyb = math.cos(b.h), math.sin(b.h)
                    rel = (p.x - b.x) * fxb + (p.y - b.y) * fyb
                    lat = abs(-(p.x - b.x) * fyb + (p.y - b.y) * fxb)
                    if abs(rel) < CIRC[b.kind][0] * 1.0 + 1.6 and lat < CIRC[b.kind][1] + 0.5:
                        hit = b
                        break
            if hit is not None:
                p.mode = "air" if hit.speed > 9 else "dead"
                p.t = clear_secs(self.sim)
                p.vx, p.vy = hit.vx * 0.9 + rng.uniform(-1, 1), hit.vy * 0.9 + rng.uniform(-1, 1)
                p.hv = 4 + hit.speed * 0.45
                p.hy = 0.2
                ev("ped_hit", ped=p, body=hit)
                if self.sim is not None and hit.player_car:
                    self.sim._pay(min(70, 25 + int(hit.speed * 2)), p.x, p.y)       # running people over pays (badly)
                out.append(p)
                continue
            if p.mode in ("queue", "board", "alight", "play"):       # moved by Transit / Kids (they can still be hit)
                out.append(p)
                continue
            if p.vault > 0.0:                                       # over / under the vehicle in the way: nothing pushes back for a moment
                p.vault -= dt
                u = max(0.0, 1.0 - p.vault / p.vault_t)
                p.hy = 0.95 * math.sin(math.pi * u) if p.vault_up else 0.0
                if p.vault <= 0.0:
                    p.vault, p.hy = 0.0, 0.0
            elif p.mode in ("walk", "flee", "rage", "brawl"):         # people are not ghosts: parked cars, wrecks and traffic push them out
                pressed = False
                for b in _near(g_a, p.x, p.y):
                    if abs(b.x - p.x) > 7 or abs(b.y - p.y) > 7:
                        continue
                    hit_ = push_from_box(b, p.x, p.y, 0.3)
                    if hit_ is not None and p.mode == "walk" and getattr(b, "speed", 9.0) < 1.0 and not getattr(b, "exploded", False):
                        pressed = True
                        p.blk += dt
                        if p.blk > 0.8:                             # stuck against it: hop over a small one, duck under a big one
                            small = vehicles.DIMS[b.kind][4] * 0.6 <= 1.15
                            p.vault, p.vault_up, p.blk = (0.8 if small else 1.7), small, 0.0
                            p.vault_t = p.vault
                            break
                    if hit_ is not None:
                        p.x += hit_[0] * hit_[2]
                        p.y += hit_[1] * hit_[2]
                        if p.mode == "walk" and getattr(b, "speed", 9.0) < 0.3 and p.bump_cd <= 0 and (p.x - fx) ** 2 + (p.y - fy) ** 2 < 40 ** 2:
                            p.bump_cd = 7.0                                   # squeezed past a parked car: a grumble (the first-stage line)
                            lang_ = getattr(self.sim, "lang", 1) if self.sim else 1
                            text_ = bible_lines.bump(vehicles.PED_IDS[p.arch], 0, lang_, rng) or bump_lines.line(vehicles.PED_IDS[p.arch], 0, rng)
                            if talk.allowed(text_, lang_):
                                ev("shout", text=text_, x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
                    elif p.mode == "walk" and getattr(b, "speed", 9.0) < 0.3:                  # steer round a standing car a step or two ahead
                        ah_ = push_from_box(b, p.x + math.cos(p.h) * 1.1, p.y + math.sin(p.h) * 1.1, 0.55)
                        if ah_ is not None:
                            p.x += ah_[0] * 1.6 * dt
                            p.y += ah_[1] * 1.6 * dt
                if not pressed:
                    p.blk = max(0.0, p.blk - dt)
            # ------------- panic near fast cars
            if p.mode == "walk":
                for b in near_b:
                    if b.speed > 6 and abs(b.x - p.x) < 9 and abs(b.y - p.y) < 9 and not b.empty:
                        d = math.hypot(b.x - p.x, b.y - p.y)
                        fxb, fyb = math.cos(b.h), math.sin(b.h)
                        if d < 9 and ((p.x - b.x) * fxb + (p.y - b.y) * fyb) > 0:
                            p.mode, p.t = "flee", 2.4
                            ax, ay = p.x - b.x, p.y - b.y
                            n = math.hypot(ax, ay) or 1.0
                            # run sideways out of the car's path
                            sx, sy = -fyb, fxb
                            side = 1 if (ax * sx + ay * sy) > 0 else -1
                            p.vx, p.vy = sx * side * 4.2, sy * side * 4.2
                            if rng.random() < 0.5:
                                ev("shout", text=talk.react("panic", p.arch, self.sim, lines("panic", p.arch), rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
                            break
            if p.mode == "walk":                                  # traffic cars too: step out of the way of one that is coming at us
                for b in _near(g_a, p.x, p.y):
                    if type(b) is Car and b.v > 3.0 and abs(b.x - p.x) < 14 and abs(b.y - p.y) < 14:
                        fxb, fyb = math.cos(b.h), math.sin(b.h)
                        ax, ay = p.x - b.x, p.y - b.y
                        fwd, lat = ax * fxb + ay * fyb, -ax * fyb + ay * fxb
                        if 0.0 < fwd < 4.0 + b.v * 1.4 and abs(lat) < 2.6:
                            side = 1 if lat >= 0 else -1
                            p.mode, p.t = "flee", 1.6
                            p.vx, p.vy = -fyb * side * 4.0, fxb * side * 4.0
                            break
            if p.mode == "ko":                                    # knocked out cold
                p.t -= dt
                f = math.exp(-6.0 * dt)
                p.vx *= f
                p.vy *= f
                p.x += p.vx * dt
                p.y += p.vy * dt
                if p.t <= 0:
                    p.hp = 30.0
                    p.mode, p.t = "flee", 3.5
                    d = math.hypot(p.x - fx, p.y - fy) or 1.0
                    p.vx, p.vy = (p.x - fx) / d * 3.2, (p.y - fy) / d * 3.2
                if self._d2(p.x, p.y, fx, fy) < 320 ** 2:
                    out.append(p)
                continue
            if p.mode == "brawl":                                 # fighting another pedestrian
                p.t -= dt
                p.atk_t = max(0.0, p.atk_t - dt)
                p.atk_cd -= dt
                o = getattr(p, "foe", None)
                if o is None or o.mode != "brawl" or p.t <= 0:
                    p.mode, p.foe = "walk", None
                    sn = w.nearest_walk_point(p.x, p.y)
                    if sn is not None:
                        p.e, p.s, p.d = sn[0], sn[1], rng.choice((1, -1))
                else:
                    dx, dy = o.x - p.x, o.y - p.y
                    d = math.hypot(dx, dy) or 1e-6
                    p.h = math.atan2(dy, dx)
                    p.anim += dt * 7
                    if d > 1.0:
                        p.x += dx / d * min(3.2 * dt, d - 0.9)
                        p.y += dy / d * min(3.2 * dt, d - 0.9)
                    elif p.atk_cd <= 0:
                        p.atk_cd, p.atk_t = rng.uniform(0.7, 1.4), 0.3
                        p.atk_kind = 4 if rng.random() < 0.65 else 5
                        o.hp -= vehicles.FIGHT[p.arch][2] * rng.uniform(0.6, 1.2)
                        o.vx, o.vy = dx / d * 1.5, dy / d * 1.5
                        if o.hp <= 0:
                            o.mode, o.t, o.foe = "ko", rng.uniform(5.0, 8.0), None
                            p.mode, p.t = "flee", 3.0
                            p.vx, p.vy = -dx / d * 3.0, -dy / d * 3.0
                            ev("shout", text=talk.react("ko", o.arch, self.sim, lines("ko", o.arch), rng), x=o.x, y=o.y, who=vehicles.PED_NAMES[o.arch])
                        elif rng.random() < 0.25:
                            ev("shout", text=talk.react("fight", p.arch, self.sim, lines("fight", p.arch), rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
                if self._d2(p.x, p.y, fx, fy) < 320 ** 2:
                    out.append(p)
                continue
            if p.mode == "fight":                                 # chasing the player
                p.t -= dt
                p.atk_t = max(0.0, p.atk_t - dt)
                p.atk_cd -= dt
                wk = self.walker
                if wk is None or wk.health <= 0 or p.t <= 0:
                    p.mode, p.t = "flee", 4.0
                    d = math.hypot(p.x - fx, p.y - fy) or 1.0
                    p.vx, p.vy = (p.x - fx) / d * 3.0, (p.y - fy) / d * 3.0
                else:
                    dist2 = (wk.x - p.x) ** 2 + (wk.y - p.y) ** 2
                    p.far_t = p.far_t + dt if dist2 > 22 ** 2 else 0.0
                    if p.far_t > 3.5 or dist2 > 45 ** 2:           # lost you: stops chasing and goes back to its business
                        p.far_t = 0.0
                        p.mode, p.t, p.vx, p.vy = "flee", 0.05, 0.0, 0.0
                        if rng.random() < 0.5:
                            ev("shout", text=rng.choice((TXT("actors.0008"), TXT("actors.0009"), TXT("actors.0010"), TXT("actors.0011"))),
                               x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
                        out.append(p)
                        continue
                    dx, dy = wk.x - p.x, wk.y - p.y
                    d = math.hypot(dx, dy) or 1e-6
                    p.h = math.atan2(dy, dx)
                    p.anim += dt * 9
                    if d > 1.1:
                        sp = 5.5
                        p.x += dx / d * sp * dt
                        p.y += dy / d * sp * dt
                        for ax, ay, bx, by in w.edges_near(p.x, p.y, 0.5):
                            ddx, ddy = bx - ax, by - ay
                            l2 = ddx * ddx + ddy * ddy or 1.0
                            t = max(0.0, min(1.0, ((p.x - ax) * ddx + (p.y - ay) * ddy) / l2))
                            ex, ey = p.x - (ax + ddx * t), p.y - (ay + ddy * t)
                            dd = math.hypot(ex, ey)
                            if 1e-6 < dd < 0.4:
                                p.x += ex / dd * (0.4 - dd)
                                p.y += ey / dd * (0.4 - dd)
                    elif p.atk_cd <= 0:
                        p.atk_cd, p.atk_t = rng.uniform(0.8, 1.2), 0.3
                        p.atk_kind = 4 if rng.random() < 0.65 else 5
                        if wk.z < 0.5 and wk.inv_t <= 0:
                            dmg = vehicles.FIGHT[p.arch][2] * rng.uniform(0.8, 1.3)
                            wk.health -= dmg
                            wk.hurt_t = 0.35
                            if wk.health <= 0:
                                wk.cause = "fight"
                            ev("hurt", ped=p, dmg=dmg)
                            if rng.random() < 0.3:
                                ev("shout", text=talk.react("fight", p.arch, self.sim, lines("fight", p.arch), rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
                if self._d2(p.x, p.y, fx, fy) < 320 ** 2:
                    out.append(p)
                continue
            if p.mode in ("flee", "rage"):
                p.t -= dt
                if p.mode == "rage":
                    p.anim += dt * 8
                    if p.t <= 0:
                        p.mode, p.t = "flee", 6.0
                        d = math.hypot(p.x - fx, p.y - fy) or 1.0
                        p.vx, p.vy = (p.x - fx) / d * 5.0, (p.y - fy) / d * 5.0
                else:
                    p.x += p.vx * dt
                    p.y += p.vy * dt
                    p.h = math.atan2(p.vy, p.vx)
                    p.anim += 4.2 * dt
                    for ax, ay, bx, by in w.edges_near(p.x, p.y, 0.5):
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy or 1.0
                        t = max(0.0, min(1.0, ((p.x - ax) * dx + (p.y - ay) * dy) / l2))
                        ex, ey = p.x - (ax + dx * t), p.y - (ay + dy * t)
                        d = math.hypot(ex, ey)
                        if 1e-6 < d < 0.4:
                            p.x += ex / d * (0.4 - d)
                            p.y += ey / d * (0.4 - d)
                    if p.t <= 0:
                        sn = w.nearest_walk_point(p.x, p.y)
                        if sn is None:
                            continue
                        p.mode, p.e, p.s, p.d = "walk", sn[0], sn[1], rng.choice((1, -1))
                if self._d2(p.x, p.y, fx, fy) < 320 ** 2:
                    out.append(p)
                continue
            # ------------- the player walks into them: grumble, insult, threaten, then fight
            wk_ = self.walker
            if p.mode == "walk" and wk_ is not None and wk_.health > 0:
                p.bump_cd = max(0.0, p.bump_cd - dt)
                if p.bumps:
                    p.bump_t += dt
                    if p.bump_t > 30.0:                           # calms down after a while
                        p.bumps = 0
                if p.bump_cd <= 0 and wk_.z < 0.5 and wk_.speed > 1.0 and (wk_.x - p.x) ** 2 + (wk_.y - p.y) ** 2 < 0.85 ** 2:
                    self._bumped(p, wk_, ev)
            # ------------- walking along the graph
            e = w.edges[p.e]
            vv = p.v * 1.25                                      # +25% walking pace
            if w.hilly:                                           # Tobler's hiking function
                gr = w.slope_at(p.x, p.y, math.cos(p.h), math.sin(p.h), p.gz if p.gz is not None else -1e9, 1.0)
                vv *= max(0.2, min(1.25, math.exp(-3.5 * (abs(gr + 0.05) - 0.05))))
            p.s += vv * dt
            p.anim += vv * dt
            if p.s >= e["len"]:
                p.s -= e["len"]
                node = e["b"] if p.d == 1 else e["a"]
                opts = [o for o in w.walk_out.get(node, ()) if o[0] != p.e] or list(w.walk_out.get(node, ()))
                if not opts:                                      # dead end: turn around, never vanish
                    p.d = -p.d
                else:
                    p.e, p.d = rng.choice(opts)
                if rng.random() < .35:
                    p.side = -p.side
            tx, ty, th = self._place(p)
            ex, ey = tx - p.x, ty - p.y                          # walk to the path point at walking pace: no sliding
            dd = math.hypot(ex, ey)
            mx = (vv * 1.5 + 0.6) * dt
            if dd > mx:
                ex, ey = ex / dd * mx, ey / dd * mx
            p.x += ex
            p.y += ey
            if dd > 0.6:                                         # face where it is actually going
                th = math.atan2(ey, ex)
            p.h += ((th - p.h + math.pi) % (2 * math.pi) - math.pi) * min(1.0, dt * 8)
            p.gz = w.level(p.x, p.y, 1e9 if e["bridge"] else -1e9)      # on the deck of a bridge edge, else on the ground
            p.say_t -= dt
            if p.say_t <= 0:
                p.say_t = rng.uniform(10, 28) / max(0.05, getattr(self.sim, "speech_freq", 1.0))
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 22 ** 2:
                    ev("shout", text=talk.say(p, self.sim, rng) if self.sim else rng.choice(lines("idle", p.arch)), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
            if self._d2(p.x, p.y, fx, fy) < 300 ** 2:
                out.append(p)
        self.list = out
        dt = dt0
        self._separate(dt, fx, fy)
        for _ in range(2):
            if len([q for q in self.list if q.mode == "walk"]) < self.target:
                self.spawn(*self._focus(fx, fy))


# ===================================================================== traffic
class Car:
    __slots__ = ("e", "d", "s", "v", "lane", "kind", "color", "pace", "x", "y", "h", "stuck", "ghost", "braking", "gz", "pitch", "roll", "cab", "lidx", "shift", "shift_t", "rev", "cool", "nxt", "avoid", "yld", "str", "turn", "arr", "blk", "rside", "man", "rq", "stn", "dwell", "stn_t", "trh")

    def __init__(self):
        self.cab = random.random() < 0.25       # one in four has its radio on (heard muffled from outside)
        self.stuck = 0.0
        self.ghost = 0.0
        self.braking = False
        self.gz = 0.0
        self.pitch = 0.0
        self.roll = 0.0
        self.lidx = 0              # which lane (of the ones in its direction) it drives in
        self.shift = 0.0           # extra sideways offset while it works its way out of a jam
        self.shift_t = 0.0
        self.rev = 0.0             # seconds of reversing left
        self.rq = None             # [delay, seconds, side]: queued reverse in a convoy backing out of a head-on knot
        self.cool = 0.0            # pause before it tries another jam manoeuvre
        self.nxt = None            # (edge, direction) it will take at the end of this one
        self.avoid = 0.0           # sideways swerve around curb-parked cars
        self.yld = 0.0             # sideways pull to the kerb to let an emergency vehicle pass
        self.str = 0.0             # front-wheel steering angle (rad)
        self.turn = 0.0            # heading change onto c.nxt (rad, > 0 = towards its own kerb, < 0 = across the oncoming lane)
        self.arr = None            # time it reached the approach to the junction ahead (first come, first served)
        self.blk = None            # what stood right in front of it last frame
        self.rside = 0.0           # while reversing: the lane offset it swings its nose towards, to go round next
        self.man = 0.0             # seconds left of making way for an oncoming car (it and that car turn tightest)
        self.stn = None            # petrol station / car wash (stations.py site index) it is heading for or standing at
        self.dwell = None          # seconds left standing at it (None: not there yet)
        self.stn_t = 0.0           # give up on the visit after this long
        self.trh = None            # semi: heading of the trailer, which follows the tractor round bends (None: straight behind)


RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1}   # as tools/roads3d


def _rank(cls):
    return RANK.get(cls.replace("_link", ""), 0)


class Traffic:
    extra = ()                                     # multiplayer: other players this PC simulates the world for (x, y)

    def _d2(self, x, y, fx, fy):
        d = (x - fx) ** 2 + (y - fy) ** 2
        for ex, ey in self.extra:
            d = min(d, (x - ex) ** 2 + (y - ey) ** 2)
        return d

    def _focus(self, fx, fy):
        e = self.extra
        if e and self.rng.random() < len(e) / (len(e) + 1.0):
            return e[self.rng.randrange(len(e))]
        return fx, fy

    def __init__(self, world, rng, target=90):
        self.w = world
        self.rng = rng
        self.cars = []
        self.target = target
        self.hash = {}
        self.hblk = {}
        self.signals = None          # signals.Signals, set by main: AI stops on red
        self.sim = None              # set by Sim (game clock for the junction jam timer)
        self.jam = {}                # junction node -> game minutes it has had >= 3 cars stuck waiting for it
        self.clogged = set()         # junctions jammed for CLOG_MIN game minutes: nothing new spawns into them
        self._jam_t = 0.0
        self.t = 0.0                 # seconds of traffic time (arrival order at junctions)
        self.occ = {}                # (edge, dir) -> distance from its start of the nearest slow car (junction exits)
        self.queue = {}              # (edge, dir) -> standing cars on it (route choice avoids queues)
        self.appr = {}               # junction node -> [(priority key, car, heading, eta)] of cars close to it
        self.lead = None
        self.despawned = 0
        self._tick = 0
        self.stn = None              # stations.Stations, set by Sim: cars pull into petrol stations and car washes

    @staticmethod
    def lanes_of(e):
        """Lateral centres of the lanes in the travel direction (positive = to the left of travel), matching the painted
        markings in tools/roads3d._markings: the OSM lanes count where the map has one, otherwise one-way roads split
        into round(w/3.5) lanes and two-way roads keep a lane in the middle of each half (two per direction from 13 m)."""
        w, n = e["w"], e.get("lanes", 0)
        if e["ow"]:
            n = n or max(1, int(round(w / 3.5)))
            return [-w / 2 + (k + 0.5) * w / n for k in range(n)]
        n = max(1, n // 2) if n else (2 if w >= 13.0 else 1)
        if n == 1:
            return [max(1.3, w / 4)]
        return [(k + 0.5) * w / 2 / n for k in range(n)]

    def _set_lane(self, c, e):
        ls = self.lanes_of(e)
        c.lidx = min(c.lidx, len(ls) - 1)
        c.lane = ls[c.lidx]

    def _ref(self, e, d, s, off):
        """Point `off` metres to the left of travel at distance s along edge e driven in direction d, and its heading."""
        x, y, dx, dy = self.w.edge_point(e, s if d == 1 else e["len"] - s)
        if d == -1:
            dx, dy = -dx, -dy
        return x - dy * off, y + dx * off, math.atan2(dy, dx)

    def _place(self, c):
        return self._ref(self.w.edges[c.e], c.d, c.s, c.lane + c.shift)

    def _head(self, e, d, at_end):
        """Heading of edge e driven in direction d, at its start or its end."""
        L = e["len"]
        s = (L - 0.5 if at_end else 0.5) if d == 1 else (0.5 if at_end else L - 0.5)
        _x, _y, dx, dy = self.w.edge_point(e, min(max(s, 0.0), L))
        return math.atan2(dy, dx) if d == 1 else math.atan2(-dy, -dx)

    def _pick(self, c):
        """Choose the edge a car takes after its current one (so its path can be followed round the corner): the bigger
        road and straight on are likelier, a queue ahead puts it off (more so in the rush hours, when drivers cut through
        side streets), and the connected network wins over a closed-off pocket."""
        w = self.w
        e = w.edges[c.e]
        opts = w.out.get(e["b"] if c.d == 1 else e["a"], [])
        good = [o for o in opts if o[0] != c.e] or opts
        if not good:
            c.nxt = None
            return
        main = [o for o in good if w.edges[o[0]]["a"] in w.main and w.edges[o[0]]["b"] in w.main]
        good = main or good
        h0 = self._head(e, c.d, True)
        hr = getattr(getattr(self.sim, "clock", None), "hour", 12.0) if self.sim else 12.0
        qk = 1.2 if (7.0 <= hr < 9.5 or 16.0 <= hr < 18.5) else 0.5
        turns, wts = [], []
        for o in good:
            e2 = w.edges[o[0]]
            t = (self._head(e2, o[1], False) - h0 + math.pi) % (2 * math.pi) - math.pi
            turns.append(t)
            wts.append((1.0 + _rank(e2["cls"])) * (1.6 if abs(t) < 0.35 else 1.0) / (1.0 + qk * self.queue.get(o, 0)))
        keep = [i for i in range(len(good)) if abs(turns[i]) <= self.UTURN]      # never choose a U-turn when there is any other way on
        if keep:
            good, turns, wts = [good[i] for i in keep], [turns[i] for i in keep], [wts[i] for i in keep]
        if c.kind in vehicles.HEAVY:                                  # lorries: big roads only, and no tight turns (they'd block the junction)
            for rk, tmax in ((3, 0.9), (2, 0.9), (2, 1.75)):
                ok = [i for i in range(len(good)) if _rank(w.edges[good[i][0]]["cls"]) >= rk and abs(turns[i]) < tmax]
                if ok:
                    good, turns, wts = [good[i] for i in ok], [turns[i] for i in ok], [wts[i] for i in ok]
                    break
            else:
                c.nxt = None                                          # nothing fit for it: _next_edge turns it round
                return
        k = self.rng.choices(range(len(good)), wts)[0]
        c.nxt, c.turn = good[k], turns[k]
        if self.stn is not None:
            self.stn.steer(c, good, turns)

    def _target(self, c, e, la):
        """Pure-pursuit aim point `la` metres ahead on the car's lane, continuing onto the next edge round a corner."""
        s2 = c.s + la
        off = c.lane + c.shift + c.avoid + c.yld
        if s2 <= e["len"] or c.nxt is None:
            return self._ref(e, c.d, min(s2, e["len"]), off)
        e2 = self.w.edges[c.nxt[0]]
        ls = self.lanes_of(e2)
        return self._ref(e2, c.nxt[1], min(s2 - e["len"], e2["len"]), ls[min(c.lidx, len(ls) - 1)] + c.shift)

    def spawn(self, px, py, rmin=170, rmax=380):
        w, rng = self.w, self.rng
        a, r = rng.uniform(0, 6.283), rng.uniform(rmin, rmax)
        cell = (int((px + math.cos(a) * r) // w.sg), int((py + math.sin(a) * r) // w.sg))
        lst = w.drive_cells.get(cell)
        if not lst:
            return
        ei = rng.choice(lst)
        e = w.edges[ei]
        if self.clogged and (e["a"] in self.clogged or e["b"] in self.clogged):
            return                                            # never feed a jammed junction
        c = Car()
        c.e = ei
        c.d = 1 if (e["ow"] or rng.random() < .5) else -1
        c.s = rng.uniform(0, e["len"])
        c.lidx = rng.randrange(len(self.lanes_of(e)))
        self._set_lane(c, e)
        c.kind = rng.choices(range(vehicles.N), vehicles.TRAFFIC_W)[0]
        if _rank(e["cls"]) >= 2 and e["w"] >= 7 and rng.random() < 0.12:
            c.kind = rng.choices(vehicles.HEAVY, vehicles.HEAVY_W)[0]       # lorries drive only the big roads (tertiary and up)
        if vehicles.LARGE[c.kind] and e["w"] < (7 if c.kind in vehicles.HEAVY else 8):
            c.kind = 1
        c.color = rng.randrange(vehicles.N_COLORS)
        c.pace = rng.uniform(0.85, 1.1) * vehicles.SPEED[c.kind]
        c.v = 0.0
        c.x, c.y, c.h = self._place(c)
        c.gz = w.level(c.x, c.y, 1e9 if e["bridge"] else -1e9)
        if (c.x - px) ** 2 + (c.y - py) ** 2 < rmin * rmin * .8:
            return
        for o in self.cars:
            if abs(o.x - c.x) < 8 and abs(o.y - c.y) < 8:
                return
        c.v = e["speed"] * c.pace * .6
        self.cars.append(c)

    def adopt(self, c):
        """Multiplayer: put a car that came from the other PC's snapshot onto the nearest road so this PC can drive it on."""
        w = self.w
        best = None
        cx, cy = int(c.x // w.sg), int(c.y // w.sg)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for ei in w.drive_cells.get((ix, iy), ()):
                    e = w.edges[ei]
                    pts, cum = e["pts"], e["cum"]
                    for k in range(len(pts) - 1):
                        (ax, ay), (bx, by) = pts[k], pts[k + 1]
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy or 1.0
                        t = max(0.0, min(1.0, ((c.x - ax) * dx + (c.y - ay) * dy) / l2))
                        d2 = (c.x - ax - dx * t) ** 2 + (c.y - ay - dy * t) ** 2
                        if best is None or d2 < best[0]:
                            best = (d2, ei, cum[k] + t * (cum[k + 1] - cum[k]), dx * math.cos(c.h) + dy * math.sin(c.h))
        if best is None or best[0] > 14.0 ** 2:
            return False
        _d, ei, s_, dot = best
        e = w.edges[ei]
        c.e, c.s = ei, s_
        c.d = 1 if (e["ow"] or dot >= 0) else -1
        c.lidx = 0
        self._set_lane(c, e)
        c.pace = self.rng.uniform(0.85, 1.1) * vehicles.SPEED[c.kind]
        c.nxt, c.blk, c.arr, c.rq, c.stn, c.dwell = None, None, None, None, None, None
        c.stuck = c.shift = c.shift_t = c.avoid = c.yld = 0.0
        c.x, c.y, c.h = self._place(c)
        return True

    def _next_edge(self, c):
        w = self.w
        e = w.edges[c.e]
        node = e["b"] if c.d == 1 else e["a"]
        opts = w.out.get(node, [])
        good = [o for o in opts if o[0] != c.e] or opts
        if not good:
            return False
        if c.nxt not in good:
            self._pick(c)                                         # the same choice as ever, so a stray pick can't be a U-turn either
            if c.nxt is None and c.kind in vehicles.HEAVY:
                return False                                          # a lorry with only side streets ahead turns back
        c.e, c.d = c.nxt if c.nxt in good else self.rng.choice(good)
        if abs(c.turn) > 2.6:
            c.man = 5.0                                           # a U-turn: full lock, as a driver would in a narrow street
        c.nxt, c.turn, c.arr = None, 0.0, None
        c.shift, c.shift_t = 0.0, 0.0
        self._set_lane(c, self.w.edges[c.e])
        return True

    def scan(self, c, rng_ahead, ox=0.0, oy=0.0, flip=False, back=-0.2):
        """Gap to the nearest thing in front of car c (or, moved by (ox, oy) / turned round, where it could go); the thing
        itself is left in self.lead."""
        hx, hy = math.cos(c.h), math.sin(c.h)
        if flip:
            hx, hy = -hx, -hy
        rx, ry = -hy, hx
        best = None
        cx, cy = c.x + ox, c.y + oy
        ex, ey = cx + hx * (rng_ahead + 7.5), cy + hy * (rng_ahead + 7.5)       # only the cells the look-ahead strip can touch (a car is < 7.5 m half-length / half-width)
        bx_, by_ = cx + hx * min(back, 0.0), cy + hy * min(back, 0.0)
        ch_ = c.h
        hwc, hlc = vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind]
        cos, sin = math.cos, math.sin
        hash_get = self.hash.get
        for ix in range(int((min(bx_, ex) - 8.0) // 16), int((max(bx_, ex) + 8.0) // 16) + 1):
            for iy in range(int((min(by_, ey) - 8.0) // 16), int((max(by_, ey) + 8.0) // 16) + 1):
                for o in hash_get((ix, iy), ()):
                    dx, dy = o[0] - cx, o[1] - cy
                    fwd = dx * hx + dy * hy
                    if fwd > rng_ahead + o[3] or o[4] is c:
                        continue
                    lat = abs(dx * rx + dy * ry)
                    oh = o[5]
                    if oh is None:                                    # a person: a thin upright post
                        if lat > o[2] or fwd < 0.3:
                            continue
                        hl = o[3]
                    else:                                             # the other car's box, seen from this car's heading:
                        if fwd < back or lat > (o[2] + o[3] + hwc) * 1.1:     # (cheap rejects before the trig: the box is never wider)
                            continue
                        ca, sa = abs(cos(oh - ch_)), abs(sin(oh - ch_))
                        if lat > (ca * o[2] + sa * o[3] + hwc) * 1.1:     # both widths + 10 % spare: no grazing (a car crossing sideways is wide)
                            continue
                        hl = ca * o[3] + sa * o[2]
                    gap = fwd - hlc - hl
                    if best is None or gap < best:
                        best, self.lead = gap, o
        return best

    def _ped_in_way(self, c):
        """Is a person inside the footprint car c is about to sweep (its box + 0.5 m at the sides, reaching ahead by its stopping room)?"""
        hx, hy = math.cos(c.h), math.sin(c.h)
        hl, hw = vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind] + 0.5
        ahead = hl + 0.8 + c.v * 0.6
        hash_get = self.hash.get
        for ix in range(int((c.x - 8.0) // 16), int((c.x + 8.0) // 16) + 1):
            for iy in range(int((c.y - 8.0) // 16), int((c.y + 8.0) // 16) + 1):
                for o in hash_get((ix, iy), ()):
                    if o[5] is not None:
                        continue
                    dx, dy = o[0] - c.x, o[1] - c.y
                    if dx * dx + dy * dy > 64.0:
                        continue
                    if -hl < dx * hx + dy * hy < ahead and abs(-dx * hy + dy * hx) < hw:
                        return True
        return False

    def _cross(self, c, horizon=3.5):
        """Look along the line of motion of everything moving nearby: if a crossing vehicle and car c would meet (their
        boxes, widths + 10 %, overlapping at the moment of closest approach within `horizon` s), the distance c may still
        drive before that point, else None.  Priority to the right; the player, sirens and buses are always let by."""
        v = c.v
        hx, hy = math.cos(c.h), math.sin(c.h)
        hwc, hlc = vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind]
        R = 8.0 + v * horizon
        best = None
        x0, x1 = int((c.x - R) // 16), int((c.x + R) // 16)       # the same 16 m cells as ever (vehicles only), found
        y0, y1 = int((c.y - R) // 16), int((c.y + R) // 16)       # through their 4 x 4 blocks
        blk_get = self.hblk.get
        for b in [blk_get((bx, by), ()) for bx in range(x0 >> 2, (x1 >> 2) + 1) for by in range(y0 >> 2, (y1 >> 2) + 1)]:
            for lst in [l_ for ix, iy, l_ in b if x0 <= ix <= x1 and y0 <= iy <= y1]:
                for o in lst:
                    ob = o[4]
                    if ob is c:
                        continue
                    dx, dy = o[0] - c.x, o[1] - c.y
                    boss = not isinstance(ob, Car)                # driven by the player or a script: it won't yield
                    if not boss and -dx * hy + dy * hx > 0:      # it comes from our left: it gives way to us
                        continue
                    ch = math.cos(o[5] - c.h)
                    if abs(ch) > 0.8:                             # same way or head-on: the lane scan handles those
                        continue
                    if boss:
                        ovx, ovy = ob.vx, ob.vy
                    else:
                        ovx, ovy = ob.v * math.cos(ob.h), ob.v * math.sin(ob.h)
                    rvx, rvy = ovx - v * hx, ovy - v * hy
                    vv = rvx * rvx + rvy * rvy
                    if vv < 0.04:
                        continue
                    t = -(dx * rvx + dy * rvy) / vv
                    if t <= 0.0 or t > horizon:
                        continue
                    px, py = dx + rvx * t, dy + rvy * t           # where it is, relative to us, when we are closest
                    sa = abs(math.sin(o[5] - c.h))
                    hw = abs(ch) * o[2] + sa * o[3]
                    hl = abs(ch) * o[3] + sa * o[2]
                    if abs(-px * hy + py * hx) < (hwc + hw) * 1.1 and abs(px * hx + py * hy) < (hlc + hl) * 1.1 + 0.5:
                        g = v * t - hlc
                        if best is None or g < best:
                            best = g
        return best

    WAIT = (6.0, 4.0, 2.5, 1.8)      # seconds a stopped car waits before trying to get out, by aggression setting
    LOCK_MAN = math.atan(1.5 * math.tan(0.55))   # front-wheel lock while manoeuvring: turns 50 % tighter than normal driving
    LOCK_WAY = math.atan(2.0 * math.tan(0.55))   # making way for an oncoming car: half the normal turning radius

    def _untangle(self, c, e, gap, dt, fx, fy):
        """A car that has been stuck behind something works its way out: back off, slip into another lane (even the
        oncoming one in a more aggressive city) and come back once the way is clear.  Every move is checked against the
        other vehicles' boxes first, so untangling never causes a crash."""
        ag = (getattr(self.sim, "aggro", 1) if self.sim else 1) % 4
        if c.cool > 0:
            c.cool -= dt
        if c.shift:
            c.shift_t += dt
            if c.shift_t > 1.5 and self._free(c, -c.shift, 14.0):     # the lane it came from is clear again
                c.shift, c.shift_t = 0.0, 0.0
            elif c.stuck > 2.0 and c.rev <= 0:                   # met someone head-on out there: it is the one that backs off
                if self.scan(c, 7.0, flip=True) is None:
                    c.rev = 2.0
                    self._make_way(c)
                elif self._free(c, -c.shift, 6.0):
                    c.shift, c.shift_t = 0.0, 0.0
            return
        if c.rev > 0 or c.cool > 0 or c.v > 0.3 or gap is None or gap > 4.0 or c.stuck < self.WAIT[ag]:
            return
        ls = self.lanes_of(e)
        opts = [l - c.lane for l in ls if abs(l - c.lane) > 0.5]             # other lanes the same way
        if not e["ow"] and ag >= 1:
            opts.append(-ls[0] - c.lane)       # the oncoming lane: not strictly legal
        for off in sorted(opts, key=abs):
            if self._free(c, off, 26.0 if (not e["ow"] and off < 0) else 14.0):
                c.shift, c.shift_t = off, 0.0
                return
        o = c.blk
        if isinstance(o, Car) and o.e == c.e and o.d != c.d and c.stuck > self.WAIT[ag] and self._convoy(c, o):
            return
        if self.rng.random() < dt * (0.6, 0.8, 1.2, 2.0)[ag] and self.scan(c, 7.0, flip=True) is None \
                and not any(o.rev > 0 and (o.x - c.x) ** 2 + (o.y - c.y) ** 2 < 400.0 for o in self.cars):
            c.rev = self.rng.uniform(1.2, 2.8)                             # nothing behind: back up to give way, one car
            c.rside = next((off for off in sorted(opts, key=abs) if self._free(c, off, 6.0)), opts[0] if opts else 0.0)   # of a knot at a time
            self._make_way(c)
        elif c.stuck > self.WAIT[ag] * 4:
            c.cool = 4.0

    def _convoy(self, c, o):
        """Two queues meet head-on in a street: instead of one car at a time, the smaller queue (the lower id when equal)
        backs out as a whole, rearmost car first and the rest 0.7 s apart so the gaps hold, while the other side waits."""
        def queue(a):
            return sorted((x for x in self.cars if x.e == a.e and x.d == a.d and x.v < 0.5 and x.rev <= 0 and x.rq is None
                           and 0.0 <= a.s - x.s < 40.0), key=lambda x: x.s)
        mine, theirs = queue(c), queue(o)
        if len(mine) > len(theirs) or (len(mine) == len(theirs) and id(c) > id(o)):
            return False
        for k, x in enumerate(mine):
            x.rq = [k * 0.7, self.rng.uniform(2.5, 3.5), 1.2]
        for x in theirs:
            x.cool = max(x.cool, 4.0 + 0.7 * len(mine))
        return True

    def _make_way(self, c):
        """c backs up to let the car facing it through (a narrow street, parked cars both sides): for the next few seconds
        both steer with the tightest lock, so they squeeze past each other."""
        o = c.blk
        if isinstance(o, Car) and abs((o.h - c.h + math.pi) % (2 * math.pi) - math.pi) > 2.4:
            c.man = o.man = 6.0

    def _courtesy(self, c, e, vlim, ems, ph, dt):
        """Swerve round kerb-parked cars and pull over for emergency vehicles.  Smooth sideways targets (c.avoid / c.yld);
        returns the speed limit, slowed while the room is tight."""
        hx, hy = math.cos(c.h), math.sin(c.h)
        rx, ry = -hy, hx
        hwc = vehicles.HALF_W[c.kind]
        ahead = 8.0 + c.v * 1.6
        tgt, near, bgap = 0.0, False, None
        tight = c.stuck > 2.0                                     # held up for a while: squeeze past with less spare room, up a kerb if need be
        if ph:
            m = 0.15 if tight else 0.45
            obs = []                                              # standing vehicles near the path: (lateral offset, half-width, gap ahead)
            gx, gy = int(c.x // 16), int(c.y // 16)
            n = int(ahead // 16) + 1
            for ix in range(gx - n, gx + n + 1):
                for iy in range(gy - n, gy + n + 1):
                    for ox, oy, ohw, ohl, oh in ph.get((ix, iy), ()):
                        dx, dy = ox - c.x, oy - c.y
                        fwd = dx * hx + dy * hy
                        if fwd > ahead + ohl or fwd < -(vehicles.HALF_L[c.kind] + ohl):
                            continue
                        ca, sa = abs(math.cos(oh - c.h)), abs(math.sin(oh - c.h))
                        wid = ca * ohw + sa * ohl
                        lat = dx * rx + dy * ry
                        if abs(lat) < hwc + wid + m + 0.6:
                            obs.append((lat, wid, fwd - vehicles.HALF_L[c.kind] - (ca * ohl + sa * ohw)))
            if obs:
                near = True
                base = c.lane + c.shift + c.avoid + c.yld
                ext = 0.8 if tight else 0.0                       # a kerb may be mounted a little when held up
                if e["ow"]:
                    tmin, tmax = -e["w"] / 2 + hwc + 0.2 - ext, e["w"] / 2 - hwc - 0.2 + ext
                else:                                             # may graze the middle of the road, or use the oncoming lane when it is clear
                    tmin = -e["w"] / 4 if self._free(c, -e["w"] / 4 - base, 30.0) else hwc - 0.6
                    tmax = e["w"] / 2 - hwc - 0.1 + ext
                dlo, dhi = tmin - base, tmax - base               # sideways moves that stay on the road (or its kerb)
                need = [(lat, hwc + wid + m) for lat, wid, _g in obs]
                cands = [0.0, dlo, dhi]
                for lat, r in need:
                    cands += [lat - r - 0.02, lat + r + 0.02]
                best = None
                for d_ in cands:
                    if dlo - 1e-6 <= d_ <= dhi + 1e-6 and all(abs(lat - d_) >= r - 0.01 for lat, r in need) and (best is None or abs(d_) < abs(best)):
                        best = d_
                block = [g for lat, wid, g in obs if abs(lat) < hwc + wid + m]
                gap0 = min(block) if block else min(g for _l, _w, g in obs)
                if best is None:                                  # no room to get round it: stop short
                    tgt, bgap = c.avoid, gap0
                    vlim = min(vlim, max(0.0, (bgap - 1.8) * 0.7))
                else:
                    tgt = c.avoid + best
                    if abs(best) > 0.25:                          # the swerve has not caught up yet: don't drive at the obstacle meanwhile
                        vlim = min(vlim, max(0.0, (gap0 - 1.5) * 0.7))
                vlim = min(vlim, 3.0 if tight else 7.0)
        c.avoid += max(-1.5 * dt, min(1.5 * dt, tgt - c.avoid))
        ytgt = 0.0
        for b in ems:
            dx, dy = c.x - b.x, c.y - b.y
            if dx * dx + dy * dy > 3600.0:
                continue
            ex, ey = math.cos(b.h), math.sin(b.h)
            fwd = dx * ex + dy * ey
            if 0.0 < fwd < 70.0 and abs(-dx * ey + dy * ex) < 8.0:
                side = 1.0 if c.lane > 0 else -1.0
                ytgt = side * (e["w"] / 2 - hwc - 0.25) - c.lane
                if abs(c.avoid) > 0.3:
                    ytgt = 0.0
                vlim = min(vlim, 4.5 if fwd > 14.0 else (1.0 if abs(c.yld - ytgt) > 0.4 else 0.0))
                break
        c.yld += max(-1.8 * dt, min(1.8 * dt, ytgt - c.yld))
        return vlim, bgap

    UTURN = 2.2                      # rad: a turn sharper than this (126 degrees) is a U-turn

    def _uturn_hold(self, c, e, rem, d2):
        """A U-turn (a dead end, the only way on) is only made on a single-lane road and when no other vehicle is within 30 m;
        until then the car waits at the end.  Returns the stopping distance to hold at, None to go ahead, or -1 to remove the car
        (a multi-lane road it cannot turn on, out of sight)."""
        multi = len(self.lanes_of(e)) >= 2 if e["ow"] else e["w"] >= 8.0
        if multi and d2 > 70 ** 2:
            return -1.0
        if multi:
            return rem - 2.0
        for ix in range(int((c.x - 34.0) // 16), int((c.x + 34.0) // 16) + 1):
            for iy in range(int((c.y - 34.0) // 16), int((c.y + 34.0) // 16) + 1):
                for o in self.hash.get((ix, iy), ()):
                    if o[4] is not c and o[5] is not None and (o[0] - c.x) ** 2 + (o[1] - c.y) ** 2 < 1089.0:       # 33 m: a margin over the 30 m rule so a car easing in cannot slip through
                        return rem - 2.0
        return None

    def _red_rem(self, c, L, sg):
        """Distance to the stop line of a red / yellow signal that applies to car c, or None: on its own edge, or on the next
        one when that is a short link into the junction (the signal sits at the end of the link, the car is still before it)."""
        if sg is None:
            return None
        st = sg.state_of(c.e, 1 if c.d == 1 else 0)
        rem = None
        hl = vehicles.HALF_L[c.kind]
        if st:
            rem = L - c.s - sg.stopd.get((c.e, 1 if c.d == 1 else 0), 10.0) - hl           # the front bumper stops at the pole
        elif c.nxt is not None:
            e2 = self.w.edges[c.nxt[0]]
            if e2["len"] < 60.0:
                st = sg.state_of(c.nxt[0], 1 if c.nxt[1] == 1 else 0)
                if st:
                    rem = L - c.s + e2["len"] - sg.stopd.get((c.nxt[0], 1 if c.nxt[1] == 1 else 0), 10.0) - hl
        if rem is None:
            return None
        if st == 1 and rem < c.v * c.v / 7.0 + 1.0:
            return None                                            # yellow and too close to stop comfortably: carries on through
        return rem

    APPR = 24.0                      # m before a junction where cars sort out who goes first

    def _give_way(self, c, rem, me):
        """Should car c wait at the line?  Major road before minor, then first come first served (one total order, so
        two cars never wait for each other); a car with green has priority over side streets without lights.  Oncoming
        traffic going straight or turning towards its own kerb does not cross.  Nor does it pull into a junction whose
        exit is blocked."""
        if rem < 6.0:
            return False                                      # already over the line
        node, (key, _c, h1, _eta), lit = me
        if c.stuck > 15.0:
            return False                                      # it has waited long enough to edge out
        if c.nxt is not None and self.occ.get(c.nxt, 1e9) < self.w.edges[c.e]["w"] * 0.5 + 6.0 + 2.0 * vehicles.HALF_L[c.kind] + 1.0:
            return True                                       # keep the box clear: do not enter unless the whole car fits on the far side
        e = self.w.edges[c.e]
        jx, jy = e["pts"][-1] if c.d == 1 else e["pts"][0]
        rj = e["w"] * 0.5 + 6.0                               # the junction box, about
        for ix in range(int((jx - rj) // 16), int((jx + rj) // 16) + 1):
            for iy in range(int((jy - rj) // 16), int((jy + rj) // 16) + 1):
                for o in self.hash.get((ix, iy), ()):
                    ob = o[4]
                    if ob is c or o[5] is None or (o[0] - jx) ** 2 + (o[1] - jy) ** 2 > rj * rj:
                        continue
                    if isinstance(ob, Car):
                        if (ob.e == c.e and ob.d == c.d) or (c.nxt is not None and (ob.e, ob.d) == c.nxt) or ob.stuck > 6.0:
                            continue                          # ahead of us on our way in or out: the lane scan follows it
                        dh = abs((o[5] - h1 + math.pi) % (2 * math.pi) - math.pi)
                        if dh > 2.6 and c.turn > -0.5 and ob.turn > -0.5:
                            continue                          # oncoming, nobody turns across
                    return True                               # someone is still crossing the box: let it clear first
        for key2, o, h2, eta2 in self.appr.get(node, ()):
            if o is c or (o.e == c.e and o.d == c.d) or o.blk is c or o.stuck > 6.0:
                continue                                      # (nor wait for a car that is not going to move soon)
            if lit:                                           # green: only a turn across waits for oncoming traffic
                if c.turn < -0.5 and o.turn > -0.5 and eta2 < 4.0 and abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi) > 2.6:
                    return True
                continue
            if key2 <= key:
                continue
            if eta2 > 4.0 and o.v > 1.0:
                continue                                      # far enough off: there is a gap to go
            dh = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
            if dh > 2.6 and c.turn > -0.5 and o.turn > -0.5:
                continue                                      # opposite directions, nobody turns across
            return True
        return False

    def _free(self, c, off, ahead):
        """Is the strip beside/in front of car c, moved sideways by `off` (to its left), empty for `ahead` metres?"""
        nx, ny = -math.sin(c.h) * off, math.cos(c.h) * off
        back = -(vehicles.HALF_L[c.kind] + 1.6)
        g = self.scan(c, ahead, nx, ny, back=back)
        return g is None or g > 6.0 + c.v * 1.0

    CLOG_MIN = 30.0                  # game minutes of standstill before a junction counts as clogged

    def _track_jams(self, dt):
        """Count cars that have been stopped for a while on the approach to each junction; a junction that keeps >= 3
        of them for CLOG_MIN game minutes is clogged and gets no new traffic until it clears."""
        w = self.w
        clk = getattr(self.sim, "clock", None)
        gm = dt * 60.0 * (clk.speed / clk.SECONDS_PER_HOUR if clk else 1.0 / 55.0)       # game minutes that passed
        cnt = {}
        for c in self.cars:
            if c.v < 0.3 and c.stuck > 6.0:
                e = w.edges[c.e]
                node = e["b"] if c.d == 1 else e["a"]
                cnt[node] = cnt.get(node, 0) + 1
        for node, n in cnt.items():
            if n >= 3:
                self.jam[node] = self.jam.get(node, 0.0) + gm
        for node in list(self.jam):
            if cnt.get(node, 0) < 3:
                self.jam[node] -= gm * 3.0                    # it moves again: the jam score drains fast
                if self.jam[node] <= 0:
                    del self.jam[node]
                    self.clogged.discard(node)
            elif self.jam[node] >= self.CLOG_MIN:
                self.clogged.add(node)

    def make_body(self, c):
        b = Body(c.x, c.y, c.h, c.kind, c.color)
        b.vx, b.vy = math.cos(c.h) * c.v, math.sin(c.h) * c.v
        b.az = c.gz
        return b

    def update(self, dt, fx, fy, bodies, peds, walker=None):
        w, rng = self.w, self.rng
        h = {}
        for c in self.cars:
            h.setdefault((int(c.x // 16), int(c.y // 16)), []).append((c.x, c.y, vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind], c, c.h))
        ph, ems = {}, []                                      # kerb-parked cars (for swerving) and emergency vehicles
        for b in bodies:
            if b.speed < 0.3 and not b.air:                     # standing cars (parked, wrecks, abandoned): drive round them
                ph.setdefault((int(b.x // 16), int(b.y // 16)), []).append((b.x, b.y, vehicles.HALF_W[b.kind], vehicles.HALF_L[b.kind], b.h))
                continue
            if b.service and not b.out:
                ems.append(b)
            h.setdefault((int(b.x // 16), int(b.y // 16)), []).append((b.x, b.y, vehicles.HALF_W[b.kind], vehicles.HALF_L[b.kind], b, b.h))
        for p in peds:
            if p.mode in ("walk", "flee", "rage", "brawl"):
                h.setdefault((int(p.x // 16), int(p.y // 16)), []).append((p.x, p.y, 1.7, 0.4, p, None))
        if walker is not None and walker.health > 0:          # traffic brakes for the player on foot too
            h.setdefault((int(walker.x // 16), int(walker.y // 16)), []).append((walker.x, walker.y, 1.7, 0.4, walker, None))
        self.hash, self.ph = h, ph
        blk = {}                                                  # the vehicles again, by 4 x 4 cells: the crossing check looks
        for (ix, iy), lst in h.items():                           # 50 m round, and most of its 16 m cells are empty
            v_ = [o for o in lst if o[5] is not None]
            if v_:
                blk.setdefault((ix >> 2, iy >> 2), []).append((ix, iy, v_))
        self.hblk = blk
        self.t += dt
        sg = self.signals
        if sg is not None:
            for b in ems:
                sg.preempt(b.x, b.y, b.h)                     # sirens get green at the lights ahead
        occ, queue, appr, mine = {}, {}, {}, {}
        for c in self.cars:                                   # who is where: junction exits, queues, junction approaches
            e = w.edges[c.e]
            k = (c.e, c.d)
            if c.v < 1.5:
                occ[k] = min(occ.get(k, 1e9), c.s)
                if c.v < 0.5:
                    queue[k] = queue.get(k, 0) + 1
            rem = e["len"] - c.s
            if rem < self.APPR:
                node = e["b"] if c.d == 1 else e["a"]
                if len(w.out.get(node, ())) < 3:
                    continue
                lit = sg is not None and (c.e, 1 if c.d == 1 else 0) in sg.by_edge
                if lit and sg.stop_for(c.e, 1 if c.d == 1 else 0):
                    continue                                  # waiting at red: no claim on the junction
                if c.arr is None:
                    c.arr = self.t
                eta = rem / max(c.v, 1.0)
                q = ((_rank(e["cls"]) + (10 if lit else 0), -c.arr, -rem), c, self._head(e, c.d, True), eta)
                appr.setdefault(node, []).append(q)
                mine[c] = (node, q, lit)
        self.occ, self.queue, self.appr, self._mine = occ, queue, appr, mine
        keep = []
        ag = (getattr(self.sim, "aggro", 1) if self.sim else 1) % 4
        dt0 = dt
        self._tick += 1
        tick = self._tick
        gy = w.ground_y
        gy3 = lambda x_, y_, _wy: gy(x_, y_)          # level() for a car off a bridge (wy = -1e9 never reaches a deck)
        for ci, c in enumerate(self.cars):
            if _lod_far(self, c.x, c.y, self._d2(c.x, c.y, fx, fy)):         # off screen: one step in three, three times as long (nobody sees it)
                if (ci + tick) % 3:
                    keep.append(c)
                    continue
                dt = dt0 * 3.0
            else:
                dt = dt0
            e = w.edges[c.e]
            L = e["len"]
            vmax = min(e["speed"] * c.pace * (1.05, 1.12, 1.2, 1.3)[ag], vehicles.PERF[c.kind][0] * 0.9)      # at about the limit, more in a nervous city
            if w.hilly:                                           # engines labour uphill, brakes hold downhill
                sl = c.pitch
                vmax *= max(0.4, 1.0 - 4.5 * sl) if sl > 0 else min(1.2, 1.0 - 1.2 * sl)
            end_node = e["b"] if c.d == 1 else e["a"]
            deg = len(w.out.get(end_node, ()))
            if deg >= 3:                                          # straight on is quick, a turn is slow
                t = abs(c.turn) if c.nxt is not None else 0.6
                vcorner = 9.0 if t < 0.35 else (6.5 if t < 0.9 else 4.5)
            else:
                vcorner = vmax if deg == 2 else 2.5
            vlim = min(vmax, math.sqrt(vcorner * vcorner + 2 * 3.5 * max(L - c.s - 1.5, 0.0)))
            hold = c in mine and self._give_way(c, L - c.s, mine[c])
            if hold:
                vlim = min(vlim, math.sqrt(2 * 3.5 * max(L - c.s - 7.0, 0.0)))
            red_rem = self._red_rem(c, L, sg)
            if red_rem is not None and -2.5 < red_rem < 45.0:
                vlim = min(vlim, math.sqrt(2 * 2.6 * max(red_rem - 1.0, 0.0)))     # eases off early and stops a metre short of the line
            wb = vehicles.DIMS[c.kind][0] * 0.6
            la = 3.0 + c.v * 0.55
            tx, ty, _th = self._target(c, e, la)
            err = (math.atan2(ty - c.y, tx - c.x) - c.h + math.pi) % (2 * math.pi) - math.pi
            vlim = min(vlim, max(2.0, math.sqrt(3.0 * la / max(2.0 * math.sin(min(abs(err), 1.5708)), 0.02))))      # slow for the bend it is steering into
            braking = False
            at_red = False
            if c.nxt is not None and abs(c.turn) > self.UTURN and L - c.s < 40.0:
                hold_at = self._uturn_hold(c, e, L - c.s, self._d2(c.x, c.y, fx, fy))
                if hold_at is not None:
                    if hold_at < 0:
                        self.despawned += 1
                        continue
                    vlim, at_red = min(vlim, math.sqrt(2 * 3.5 * max(hold_at, 0.0))), True
            if (red_rem is not None and -2.5 < red_rem < 150.0) or hold:
                at_red = True                                      # queueing for a red light / giving way is not a jam to escape
            tr = getattr(self.sim, "trains", None)
            if tr is not None and tr.closed:
                a = tr.stop_at(c.e, c.d, c.s, L)
                if a is not None:                                  # barriers down: wait for the train
                    vlim, at_red = min(vlim, math.sqrt(2 * 3.5 * max(a, 0.0))), True
            if c.nxt is None and L - c.s < 60.0:
                self._pick(c)
            vlim, bgap = self._courtesy(c, e, vlim, ems, ph, dt)
            self.lead = None
            gap = self.scan(c, 10.0 + c.v * 3.0) if c.ghost <= 0 else None
            lead = self.lead[4] if gap is not None and self.lead is not None else None
            if isinstance(lead, Car) and lead.blk is c and lead.v < 0.3 and c.v < 0.3 and c.stuck > 1.0:
                hx_, hy_ = math.cos(c.h), math.sin(c.h)          # two cars each standing in the other's way: the one already
                fa = (lead.x - c.x) * hx_ + (lead.y - c.y) * hy_  # further ahead goes (the other is more beside/behind it than in front)
                fb = (c.x - lead.x) * math.cos(lead.h) + (c.y - lead.y) * math.sin(lead.h)
                if fa < fb or (fa == fb and id(c) < id(lead)):
                    gap, lead = None, None
            if bgap is not None and (gap is None or bgap < gap):
                gap, lead = bgap, None                           # a standing car it can't get round counts as a blocker
            c.blk = lead if gap is not None and gap < 3.0 else None
            if c.stn is not None and self.stn is not None:
                vlim, waiting = self.stn.drive(c, e, vlim, dt)
                if waiting:
                    at_red, c.stuck = True, 0.0                       # standing at the pumps is not a jam
            if c.rev > 0:
                vlim = 0.0
            elif gap is not None:
                slack = 0.5 if c.stuck > self.WAIT[ag] else 1.8      # a stuck car inches up closer instead of waiting
                lv = 0.0                                         # follow a moving car at about a second's distance
                if isinstance(lead, Car):
                    lv = lead.v * math.cos(lead.h - c.h) * (0.6 if lead.braking else 1.0)     # its brake lights: ease off early
                elif isinstance(lead, Body):
                    lv = lead.vx * math.cos(c.h) + lead.vy * math.sin(c.h)
                lv = max(0.0, lv)
                vlim = min(vlim, max(0.0, (gap - slack) * 0.7, lv + 0.6 * (gap - slack - lv)))
                if c.shift and gap > 0.6:
                    vlim = max(vlim, 1.2)                          # edging round the blocker (the lane was checked)
                braking = True
            if c.ghost <= 0 and c.v > 0.1 and self._ped_in_way(c):      # someone on foot beside/ahead of the swinging body (the straight scan misses them)
                vlim, braking = 0.0, True
            cg = self._cross(c) if c.ghost <= 0 and c.v > 0.5 else None
            if cg is not None:                                     # someone will cut across our path: let them by
                vlim = min(vlim, max(0.0, (cg - 1.5) * 0.7))
                braking = True
            if not at_red:
                self._untangle(c, e, gap, dt, fx, fy)
            if c.v < vlim:
                c.v = min(vlim, c.v + min(3.2, vehicles.PERF[c.kind][1] * 0.4) * dt)
            else:
                c.v = max(vlim, c.v - 8.0 * dt)
            c.braking = braking or c.v < vlim - 0.5
            if c.v < 0.2:
                c.stuck += dt
            elif c.v > 1.0:                                       # creeping a metre at a time is still being stuck
                c.stuck = 0.0
            if c.stuck > 3.0 and c.ghost <= 0 and gap is not None and gap < 0.0 and isinstance(lead, Car) and lead.v < 0.3 and not at_red:
                c.ghost, c.stuck = 4.0, 0.0                       # two standing cars sit inside each other: neither can ever back out, so slip apart now
            if c.stuck > 5.0 and c.v < 0.5 and not at_red:
                d2 = self._d2(c.x, c.y, fx, fy)
                if d2 > 150 ** 2 and c.stuck > 8.0:
                    self.despawned += 1                           # hopelessly stuck out of sight: gone, a new car comes
                    continue
                if c.ghost <= 0 and (d2 > 90 ** 2 or (c.stuck > 20.0 and d2 > 45 ** 2) or (c.stuck > 35.0 and not isinstance(c.blk, Body))):
                    c.ghost, c.stuck = 4.0, 0.0                   # a knot nobody can undo (or out of sight): slips through it rather than blocking the street for ever
            if c.rq:
                c.rq[0] -= dt
                if c.rq[0] <= 0:
                    c.rev, c.rside, c.man, c.rq = c.rq[1], c.rq[2], 4.0, None
            if c.man > 0:
                c.man -= dt
            if c.ghost > 0:
                c.ghost -= dt
                if c.ghost <= 0 and (self.scan(c, 1.0, back=-vehicles.HALF_L[c.kind]) or 0.0) < 0.0:
                    c.ghost = 0.5                                 # still inside another car: slip on until clear
            if c.rev > 0 and abs((c.h - _th + math.pi) % (2 * math.pi) - math.pi) > 1.3:
                c.rev, c.rside, c.cool = 0.0, 0.0, 2.0           # facing across / against the road (mid U-turn): backing up would run it off its lane
            if c.rev > 0:                                         # backing out of a jam (the way behind was checked),
                c.rev -= dt                                       # swinging the nose towards the side it will pass on
                c.s = max(0.0, c.s - 2.2 * dt)
                if c.rside and abs((c.h - _th + math.pi) % (2 * math.pi) - math.pi) < 0.35:
                    yaw = math.copysign(2.2 * math.tan(self.LOCK_WAY if c.man > 0 else self.LOCK_MAN) / wb * dt, c.rside)
                    c.h += yaw                                    # about the rear axle, as when driving forwards
                    c.x -= math.sin(c.h) * yaw * wb * 0.52
                    c.y += math.cos(c.h) * yaw * wb * 0.52
                c.x -= math.cos(c.h) * 2.2 * dt
                c.y -= math.sin(c.h) * 2.2 * dt
                gb = self.scan(c, 4.0, flip=True)
                if c.rev <= 0 or c.s <= 0.5 or (gb is not None and gb < 1.0):
                    c.rev, c.cool, c.stuck = 0.0, 3.0, 0.0
                    if c.rside and self._free(c, c.rside, 10.0):         # room now: straight on round it
                        c.shift, c.shift_t = c.rside, 0.0
                    c.rside = 0.0
            else:
                c.s += c.v * dt * max(0.0, math.cos(c.h - _th))     # progress along the road, not along the clock
                if L - c.s < 10.0:                                  # a car swinging round a tight corner is turned away from the road by the time it is
                    ex_, ey_, eh_ = self._ref(e, c.d, L, 0.0)       # level with the junction: count how far it really is (else it circles for its
                    c.s = max(c.s, L - ((ex_ - c.x) * math.cos(eh_) + (ey_ - c.y) * math.sin(eh_)))   # turn instead of taking it)
                if c.s >= L:
                    c.s -= L
                    if not self._next_edge(c):                   # dead end: U-turn instead of vanishing
                        c.d, c.v = -c.d, 0.0
                    e = w.edges[c.e]
                # pure pursuit with a bicycle model: steer for a point ahead on the lane, limited front-wheel angle and
                # rate, so cars swing round bends and into other lanes along believable arcs instead of sliding
                lock = self.LOCK_WAY if c.man > 0 else self.LOCK_MAN if (c.shift or abs(c.avoid) > 0.3 or c.cool > 0) else 0.55     # going round / out of a jam:
                want = max(-lock, min(lock, math.atan2(2.0 * wb * math.sin(max(-1.5708, min(1.5708, err))), la)))  # tighter turns
                c.str += (want - c.str) * min(1.0, dt * 5.0)
                c.h += c.v * math.tan(c.str) / (wb * TURN) * dt
                slip = math.atan(0.52 * math.tan(c.str))           # about the rear axle: the middle moves a little into
                c.x += math.cos(c.h + slip) * c.v * dt              # the turn (rear axle 0.31 L behind it, wheelbase 0.6 L)
                c.y += math.sin(c.h + slip) * c.v * dt
                rx_, ry_, _rh = self._ref(e, c.d, c.s, c.lane + c.shift + c.avoid + c.yld)
                if (rx_ - c.x) ** 2 + (ry_ - c.y) ** 2 > 400.0 and (c.ghost > 0 or (self.scan(c, 0.5, rx_ - c.x, ry_ - c.y, back=-vehicles.HALF_L[c.kind]) or 1.0) >= 0.0):
                    c.x, c.y, c.h = rx_, ry_, _rh                   # lost (a 20 m detour is fine round corners) (spawned, or pushed): put it back, unless another car is there
            lv = w.level if e["bridge"] else gy3                 # off a bridge level() is just ground_y()
            c.gz = lv(c.x, c.y, 1e9)
            if (w.hilly or e["bridge"]) and ((ci + tick) & 1 == 0 or dt != dt0):      # tilt follows the ground: every other frame is plenty
                fx_, fy_ = math.cos(c.h), math.sin(c.h)
                wy_ = 1e9 if e["bridge"] else -1e9
                hb = vehicles.DIMS[c.kind][0] * 0.31
                pt = math.atan2(lv(c.x + fx_ * hb, c.y + fy_ * hb, wy_) - lv(c.x - fx_ * hb, c.y - fy_ * hb, wy_), 2 * hb)
                rl_ = math.atan2(lv(c.x + fy_ * 0.85, c.y - fx_ * 0.85, wy_) - lv(c.x - fy_ * 0.85, c.y + fx_ * 0.85, wy_), 1.7)
                kk = min(1.0, dt * 8) if dt != dt0 else min(1.0, dt * 16)
                c.pitch += (pt - c.pitch) * kk
                c.roll += (rl_ - c.roll) * kk
            if c.kind == vehicles.SEMI:                           # kingpin trailer: yaws towards the tractor's heading at v / axle-distance
                dh = (c.h - c.trh + math.pi) % math.tau - math.pi if c.trh is not None else 0.0
                if c.trh is None or abs(dh) > 1.2:
                    c.trh = c.h
                else:
                    c.trh += abs(c.v) * dt / vehicles.SEMI_AXLE * math.sin(dh)
            keep.append(c)
        self.cars = [c for c in keep if self._d2(c.x, c.y, fx, fy) < 460 ** 2]
        dt = dt0
        self._jam_t += dt
        if self._jam_t >= 1.0:
            self._track_jams(self._jam_t)
            self._jam_t = 0.0
        for _ in range(2):
            if len(self.cars) < self.target:
                self.spawn(*self._focus(fx, fy))


# ===================================================================== the whole game state
class Sim:
    def __init__(self, world, rng, n_cars, n_peds):
        self.w = world
        self.rng = rng
        self.events = []
        self.aggro, self.lang = 1, 1              # menu: how quarrelsome people are, how rude they talk
        self.client = False                       # multiplayer guest: traffic / pedestrians / services come from the host (mpgame.py)
        self.remote_foot = {}                     # multiplayer: other players on foot, drawn by render
        self.pvp = True                           # multiplayer: friendly fire (players can hurt each other)
        self.respawn_hint = None                  # multiplayer: where the nearest living other player is (you come back to life next to him)
        self.mp_view = None                       # multiplayer: what the HUD shows (other players, team money), set by mpgame
        self.mp_taken = []                        # multiplayer follower: puppet traffic cars I stole (the authority must drop them)
        self.last_exit = None                     # the car I got out of last (multiplayer shares it as a dropped car)
        self.pvp_out = []                         # (pid, kind, amount) hits this player landed on others; mpgame sends them
        sx, sy, sh = world.spawn
        self.car = Body(sx, sy, sh, 1, 0)
        self.car.fuel = 1.0
        self.car.player_car, self.car.empty, self.car.name = True, False, PLAYER_NAME
        self.bodies = [self.car]
        self.walker = None
        self.mode = "car"
        self.traffic = Traffic(world, rng, n_cars)
        self.peds = Peds(world, rng, n_peds)
        self.peds.sim = self
        import services
        self.services = services.Services(self)
        self.trains = trains.Trains(world)
        self.dens_traffic = self.dens_peds = 1.0
        self.parked = {}
        self.gone = set()
        self.stats = {"peds": 0, "burek": 0, "stolen": 0, "deaths": 0, "boom": 0, "ajvar": 0}
        self.safe = (sx, sy, sh)
        self.safe_z = None
        self.respawn_t = 0.0
        self.pickups = []
        self.money = 250
        self.jack = None                     # carjack in progress (see _start_jack)
        self.riding = None                   # the city bus you ride as a passenger (Ctrl takes it over)
        self.train_ride = None               # the trains.Train you ride on foot (F at a station boards / gets off)
        self.shots = projectiles.Projectiles(self)
        import chaos
        self.chaos = chaos.Chaos(self)       # breakable props, blast waves, chain fires
        self.traffic.sim = self
        import stations
        self.stations = self.traffic.stn = stations.Stations(self)
        self.clock = clock.GameClock(17.0)
        self.base_cars, self.base_peds = n_cars, n_peds
        self._cull_t = 0.0
        self.kiosks = []                  # (x, y, heading)
        self._make_pickups()
        self._make_kiosks()
        for _ in range(n_cars * 6):
            if len(self.traffic.cars) < n_cars:
                self.traffic.spawn(sx, sy, 60, 330)
        for _ in range(n_peds * 6):
            if len(self.peds.list) < n_peds:
                self.peds.spawn(sx, sy)

    # ---------------------------------------------------------------- helpers
    def ev(self, _kind, **kw):
        self.events.append((_kind, kw))

    def _pay(self, amount, x, y):
        """Денари for mayhem: destruction, car hits, run-over people, punches."""
        if amount > 0:
            amount *= 3                                   # crime pays triple
            self.money += int(amount)
            self.ev("pay", x=x, y=y, amount=int(amount))

    def focus(self):
        if self.mode == "car":
            c = self.car
            return c.x, c.y, c.vx, c.vy
        wk = self.walker
        return wk.x, wk.y, wk.vx, wk.vy

    WEAPON_PICKUPS = 70

    def _spawn_weapons(self, rng):
        """A fresh set of weapons in random places (called at start and every game morning)."""
        self.pickups = [pk for pk in self.pickups if pk[2] not in WEAPONS]
        walk = [e for e in self.w.edges if e.get("walk") and e["len"] > 25]
        for e in rng.sample(walk, min(self.WEAPON_PICKUPS, len(walk))):
            x, y, dx, dy = self.w.edge_point(e, rng.uniform(5, e["len"] - 5))
            self.pickups.append([x, y, rng.choice(("pistol", "pistol", "bat", "bat", "knuckles", "chain", "uzi", "uzi", "shotgun", "kalash",
                                                    "kalash", "zolja")), True, 0.0])

    def _make_pickups(self):
        rng = random.Random(99)
        drv = [e for e in self.w.edges if e["drive"] and e["len"] > 30 and e["cls"] not in ("service", "living_street")]
        if not drv:
            return
        for i in range(90):
            e = rng.choice(drv)
            x, y, dx, dy = self.w.edge_point(e, rng.uniform(5, e["len"] - 5))
            self.pickups.append([x, y, "ajvar" if i % 4 == 3 else "burek", True, 0.0])
        self._spawn_weapons(rng)
        for e in rng.sample(drv, min(45, len(drv))):           # jerry cans for the player's tank
            x, y, dx, dy = self.w.edge_point(e, rng.uniform(5, e["len"] - 5))
            self.pickups.append([x, y, "fuel", True, 0.0])

    def _make_kiosks(self):
        """Burek / tulumba kiosks along the pavements. Solid, so the player and peds cannot walk through."""
        w = self.w
        found = getattr(w, "kiosks", None)
        if found:
            self.kiosks = [tuple(k[:3]) for k in found]
        else:
            rng = random.Random(7)
            walk = [e for e in w.edges if e.get("walk") and e["len"] > 40]
            rng.shuffle(walk)
            for e in walk:
                x, y, dx, dy = w.edge_point(e, e["len"] * rng.uniform(0.3, 0.7))
                off = (e["w"] / 2 + 2.6) if e["drive"] else 2.2
                side = rng.choice((-1, 1))
                kx, ky = x - dy * off * side, y + dx * off * side
                if any((kx - a) ** 2 + (ky - b) ** 2 < 90 ** 2 for a, b, _h in self.kiosks):
                    continue
                if abs(kx) > w.hx - 30 or abs(ky) > w.hy - 30 or w.surface(kx, ky) == 1:
                    continue
                if any(True for _ in w.edges_near(kx, ky, 1.4)):
                    continue
                self.kiosks.append((kx, ky, math.atan2(dy, dx)))
                if len(self.kiosks) >= 50:
                    break
        cg = w.cg
        for kx, ky, _h in self.kiosks:
            w.pgrid.setdefault((int(kx // cg), int(ky // cg)), []).append((kx, ky, 1.15, w.th(kx, ky) - 1.0, w.th(kx, ky) + 3.0))

    def teleport(self, x, y):
        """Jump to (x, y) metres from the centre: snaps to the nearest road for the car, pavement for the player."""
        x = max(-self.w.hx + 20, min(self.w.hx - 20, x))
        y = max(-self.w.hy + 20, min(self.w.hy - 20, y))
        if self.mode == "car":
            p = self.w.nearest_drive_point(x, y)
            if p:
                c = self.car
                c.x, c.y, c.h = p
                c.vx = c.vy = c.w = 0.0
                self.safe = p
                self.safe_z = None
        else:
            p = self.w.nearest_walk_point(x, y, 120)
            wk = self.walker
            if p:
                px, py, _dx, _dy = self.w.edge_point(self.w.edges[p[0]], p[1])
                wk.x, wk.y = px, py
            else:
                wk.x, wk.y = x, y
            wk.vx = wk.vy = 0.0
            self.safe = (wk.x, wk.y, wk.h)
            self.safe_z = None
        self.ev("teleport")
        # forget what is around: agents near the old place get culled naturally

    def near_kiosk(self, x, y, r=3.4):
        for k in self.kiosks:
            if (k[0] - x) ** 2 + (k[1] - y) ** 2 < r * r:
                return k
        return None

    def buy(self, i):
        wk = self.walker
        if self.mode != "foot" or wk is None or wk.health <= 0 or self.near_kiosk(wk.x, wk.y) is None:
            return
        if not 0 <= i < len(vehicles.KIOSK_MENU):
            return
        name, price, heal = vehicles.KIOSK_MENU[i]
        if self.money < price:
            self.ev("broke", item=name, price=price)
            return
        self.money -= price
        wk.health = min(100.0, wk.health + heal)
        self.stats["food"] = self.stats.get("food", 0) + 1
        self.ev("bought", item=name, heal=heal, price=price)

    # ---------------------------------------------------------------- fighting
    def _pvp_hit(self, pid, kind, amt):
        if self.pvp:
            self.pvp_out.append((pid, kind, amt))

    def attack(self):
        wk = self.walker
        if self.mode != "foot" or wk is None or wk.health <= 0 or wk.atk_cd > 0 or wk.z > 0.3:
            return
        if wk.weapon in WEAPONS and wk.ammo > 0:
            return self._shoot()
        rng = self.rng
        kick = wk.combo >= 2
        wk.atk_kind = 5 if kick else 4
        wk.atk_t = 0.3
        wk.atk_cd = 0.62 if kick else 0.38
        wk.combo = 0 if kick else wk.combo + 1
        wk.combo_t = 1.1
        dmg = 26.0 if kick else 14.0
        reach = 1.9 if kick else 1.6
        fx, fy = math.cos(wk.h), math.sin(wk.h)
        best, bd = None, 1e9
        for p in self.peds.list:
            if p.mode in ("dead", "air", "ko"):
                continue
            dx, dy = p.x - wk.x, p.y - wk.y
            d = math.hypot(dx, dy)
            if d < reach and (d < 0.5 or (dx * fx + dy * fy) / d > 0.5) and d < bd:
                best, bd = p, d
        for rp in self.remote_foot.values():                       # another player: the hit is reported to him (mpgame)
            dx, dy = rp["x"] - wk.x, rp["y"] - wk.y
            d = math.hypot(dx, dy)
            if d < reach and (d < 0.5 or (dx * fx + dy * fy) / d > 0.5) and d < bd:
                self._pvp_hit(rp["pid"], "kick" if kick else "punch", dmg)
                self.ev("kick" if kick else "punch", x=wk.x + fx, y=wk.y + fy, hit=True)
                self.ev("hit", x=rp["x"], y=rp["y"], kick=kick)
                return
        dg = self.dogs.pettable(wk.x, wk.y, wk.h, 1.8) if getattr(self, "dogs", None) is not None else None
        if dg is not None and (best is None or dg[1] < bd):        # the strays are friendly: a "hit" at one pets it
            wk.atk_t, wk.atk_cd = 0.0, 0.5
            self.dogs.pet(dg[0])
            return
        self.ev("kick" if kick else "punch", x=wk.x + fx, y=wk.y + fy, hit=best is not None)
        if best is None:
            self.chaos.punch(wk, kick)                 # nobody there: street furniture takes it
            return
        p = best
        self._pay(rng.randint(6, 11) if kick else rng.randint(3, 6), p.x, p.y)
        p.hp -= dmg * rng.uniform(0.85, 1.15)
        kb = 5.5 if kick else 3.0
        p.vx, p.vy = fx * kb, fy * kb
        p.x += fx * 0.25
        p.y += fy * 0.25
        self.ev("hit", x=p.x, y=p.y, kick=kick)
        if p.hp <= 0:
            self._knock_out(p)
        elif p.mode in ("walk", "flee", "rage"):
            if rng.random() < (vehicles.FIGHT[p.arch][1] + 0.12) * (0.3, 1.0, 1.8, 3.0)[self.aggro % 4]:
                p.mode, p.t = "fight", 14.0
                self.ev("shout", text=talk.react("fight", p.arch, self, lines("fight", p.arch), rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
            else:
                p.mode, p.t = "flee", 3.0
                p.vx, p.vy = fx * 3.4, fy * 3.4
                self.ev("shout", text=talk.react("hit", p.arch, self, lines("hit", p.arch), rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])

    def _knock_out(self, p):
        p.mode, p.t = "ko", self.rng.uniform(6.0, 9.0)
        self.stats["ko"] = self.stats.get("ko", 0) + 1
        self.ev("ko", x=p.x, y=p.y)
        self.ev("shout", text=talk.react("ko", p.arch, self, lines("ko", p.arch), self.rng), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
        if not p.looted:
            p.looted = True
            self.pickups.append([p.x + self.rng.uniform(-0.4, 0.4), p.y + self.rng.uniform(-0.4, 0.4), "cash", True, 0.0])

    def _shoot(self):
        wk = self.walker
        name, cd, dmg, pellets, spread, rng_m, _per = WEAPONS[wk.weapon]
        if wk.weapon not in MELEE:
            wk.ammo -= 1
        wk.atk_cd, wk.atk_t, wk.atk_kind = cd, (SWING_T if wk.weapon in MELEE else 0.2), 4
        empty = wk.ammo <= 0
        fx, fy = math.cos(wk.h), math.sin(wk.h)
        if wk.weapon in MELEE:
            self._ray(wk, wk.h, dmg, rng_m, False)
            self.chaos.punch(wk, True)                      # a swung bat also smashes whatever stands in front of it
        else:
            kind = "rocket" if wk.weapon == "zolja" else ("pellet" if pellets > 1 else "bullet")
            for _ in range(pellets):
                self.shots.fire(wk.x + fx * 0.7, wk.y + fy * 0.7, wk.h + self.rng.uniform(-spread, spread), kind, dmg, rng_m)
            self.ev("gunfire", x=wk.x, y=wk.y, kind=wk.weapon)
            self.scare(wk.x, wk.y, 45.0 if kind != "rocket" else 70.0)
        if empty:
            wk.weapon = "fist"

    def clear_time(self):
        return clear_secs(self)

    def scare(self, x, y, r):
        """Gunfire / blasts: everyone walking nearby panics, runs away and some shout about it."""
        rng = self.rng
        n = 0
        if getattr(self, "dogs", None) is not None:
            self.dogs.scare(x, y, r)
        if getattr(self, "birds", None) is not None:
            self.birds.flush(x, y, r * 1.5)
        for p in self.peds.list:
            if p.mode in ("walk", "brawl") and (p.x - x) ** 2 + (p.y - y) ** 2 < r * r:
                d = math.hypot(p.x - x, p.y - y) or 1.0
                p.mode, p.t, p.foe = "flee", rng.uniform(4.0, 7.0), None
                p.vx, p.vy = (p.x - x) / d * 4.6, (p.y - y) / d * 4.6
                if n < 2 and rng.random() < 0.35:
                    n += 1
                    self.ev("shout", text=talk.react("gun", p.arch, self, talk.GUN_PANIC, rng), x=p.x, y=p.y,
                            who=vehicles.PED_NAMES[p.arch])

    def blast(self, x, y):
        """Rocket impact: burning wrecks, people thrown, a crater."""
        self.ev("rocket", x=x, y=y)
        self.chaos.blast(x, y, 9.0, peds=False)
        pay = 0
        for c in list(self.traffic.cars):                 # traffic in the blast becomes burning wrecks
            if (c.x - x) ** 2 + (c.y - y) ** 2 < 7 ** 2:
                b = self.traffic.make_body(c)
                self.traffic.cars.remove(c)
                b.empty = True
                self.bodies.append(b)
        for b in self.bodies:
            d = math.hypot(b.x - x, b.y - y)
            if d < 7 and b is not self.car:
                pay += 40 if b.health > 0 else 0
                b.health = min(b.health, -1.0)
                b.dirty = True
                b.vx += (b.x - x) / (d or 1) * 6
                b.vy += (b.y - y) / (d or 1) * 6
        for p in self.peds.list:
            d = math.hypot(p.x - x, p.y - y)
            if d < 6 and p.mode not in ("dead",):
                p.mode, p.t, p.hy, p.hv = "air", clear_secs(self), 0.2, 6.0
                p.vx, p.vy = (p.x - x) / (d or 1) * 9, (p.y - y) / (d or 1) * 9
                self.stats["peds"] += 1
                pay += 25
        if pay:
            pay *= 3                                       # crime pays triple
            self.money += pay
            self.ev("pay", x=x, y=y, amount=pay)
        for rp in self.remote_foot.values():
            if math.hypot(rp["x"] - x, rp["y"] - y) < 5:
                self._pvp_hit(rp["pid"], "boom", 60)
        wk = self.walker
        if self.mode == "foot" and wk is not None and math.hypot(wk.x - x, wk.y - y) < 5:
            wk.health -= 60
            if wk.health <= 0:
                wk.cause = "boom"
        self.scare(x, y, 80.0)

    def _ray(self, wk, ang, dmg, reach, tracer=True):
        fx, fy = math.cos(ang), math.sin(ang)
        ox, oy = wk.x + fx * 0.6, wk.y + fy * 0.6
        best, bt = None, float(reach)
        for p in self.peds.list:
            if p.mode in ("dead", "air"):
                continue
            dx, dy = p.x - ox, p.y - oy
            t = dx * fx + dy * fy
            if 0 < t < bt and abs(-dx * fy + dy * fx) < 0.5:
                best, bt = p, t
        hit_body = None
        for b in self.bodies:
            dx, dy = b.x - ox, b.y - oy
            t = dx * fx + dy * fy
            if 0 < t < bt and abs(-dx * fy + dy * fx) < CIRC[b.kind][1]:
                hit_body, bt = b, t
        foot = None
        for rp in self.remote_foot.values():                       # another player on foot
            dx, dy = rp["x"] - ox, rp["y"] - oy
            t = dx * fx + dy * fy
            if 0 < t < bt and abs(-dx * fy + dy * fx) < 0.5:
                foot, bt = rp, t
        if foot is not None:
            self._pvp_hit(foot["pid"], "swing", dmg)
            self.ev("hit", x=foot["x"], y=foot["y"], kick=True)
            best = hit_body = None
        if hit_body is not None and getattr(hit_body, "pid", None) is not None:
            self._pvp_hit(hit_body.pid, "car", 6)                  # another player's car
        if hit_body is not None and (best is None or (best.x - ox) * fx + (best.y - oy) * fy > bt):
            hit_body.health -= 6
            hit_body.dirty = True
            best = None
        ex, ey = ox + fx * bt, oy + fy * bt
        if tracer:
            self.ev("shot", x0=ox, y0=oy, x1=ex, y1=ey)
        else:
            self.ev("swing", x=ex, y=ey, hit=best is not None, weapon=self.walker.weapon)
        if best is not None:
            p = best
            p.hp -= dmg
            p.vx, p.vy = fx * 3, fy * 3
            self.ev("hit", x=p.x, y=p.y, kick=True)
            if p.hp <= 0:
                p.mode, p.t = "dead", clear_secs(self)
                self.stats["peds"] += 1
                self.ev("ped_shot", x=p.x, y=p.y)
            else:
                p.mode, p.t = "flee", 4.0
                p.vx, p.vy = fx * 4, fy * 4

    # ---------------------------------------------------------------- enter / exit / hijack
    def try_enter(self):
        if self.mode == "car":
            return
        wk = self.walker
        tr = self.train_ride
        if tr is not None:                                         # get off, only while the train stands in a station
            if tr.v < 0.1 and tr.wait > 0:
                self.train_ride = None
                self.ev("alight")
            return False
        for t in self.trains.trains:
            if t.v < 0.1 and t.wait > 0 and t.last_stop is not None:
                for k in range(trains.CARS):
                    x, y, _z, _h = t.line.at(t.s - t.d * (k * (trains.CAR_L + trains.GAP) + trains.CAR_L / 2))
                    if math.hypot(wk.x - x, wk.y - y) < 14.0:
                        fare = 40 if self.money >= 40 else 0
                        self.money -= fare
                        self.train_ride = t
                        self.ev("board", body=None, fare=fare)
                        return True
        best, bd, kind = None, 1e9, None
        for b in self.bodies:
            if not b.alive or b.burn > 0.5:
                continue
            if getattr(b, "remote", False) and getattr(b, "drop_pid", None) is None and not (getattr(b, "puppet", False) and getattr(b, "bus_line", None)):
                continue                                           # another player's occupied car, or a host puppet: not for the taking
            L = CIRC[b.kind][0]
            fx, fy = math.cos(b.h), math.sin(b.h)
            t = max(-L, min(L, (wk.x - b.x) * fx + (wk.y - b.y) * fy))
            d = math.hypot(wk.x - (b.x + fx * t), wk.y - (b.y + fy * t))
            if d < 2.5 and d < bd:
                best, bd, kind = b, d, "body"
        for c in self.traffic.cars:
            d = math.hypot(wk.x - c.x, wk.y - c.y)
            if d < 3.4 and d < bd:
                best, bd, kind = c, d, "ai"
        for p in self.peds.list:                                   # cyclists, mopeds, scooters
            if p.mode in ("walk", "flee") and p.arch in vehicles.JACK_KIND:
                d = math.hypot(wk.x - p.x, wk.y - p.y)
                if d < 2.6 and d < bd:
                    best, bd, kind = p, d, "rider"
        if best is None:
            return False
        if getattr(self, "jack", None) is not None:
            return False
        if kind == "rider":
            p = best
            p.mode, p.t, p.v, p.vx, p.vy = "svc", 999.0, 0.0, 0.0, 0.0      # brakes: the hero walks up and drags them off
            self.stats["stolen"] += 1
            self._start_jack(None, p, 0.9, True)
            return True
        if kind == "ai":
            c = best
            b = self.traffic.make_body(c)
            self.traffic.cars.remove(c)
            if self.client:
                self.mp_taken.append(c)
            self.bodies.append(b)
            self.stats["stolen"] += 1
            self._start_jack(b, "driver", 1.65)
            return True
        elif getattr(b_ := best, "bus_line", None) and not b_.empty and ((getattr(self, "transit", None) is not None
                and any(bus.body is b_ for bus in self.transit.buses)) or getattr(b_, "puppet", False)):
            self.riding = b_                                       # hop on as a passenger: the driver keeps driving
            self.car = b_
            self.mode = "car"
            self.walker = None
            fare = 40 if self.money >= 40 else 0
            self.money -= fare
            self.ev("board", body=b_, fare=fare)
            return True
        else:
            b = best
            if b.rental:                                           # rental e-scooter: pay first
                fare = __import__("rentals").FARE
                name = vehicles.NAMES[b.kind]
                if self.money < fare:
                    self.ev("broke", item=name, price=fare)
                    return False
                self.money -= fare
                b.rental = False
                self.ev("rent", item=name, price=fare)
            if b.parked_idx is not None:
                self.gone.add(b.parked_idx)
                b.parked_idx = None
            if getattr(b, "drop_pid", None) is not None:           # a car another player left standing: it is mine now (mpgame tells him)
                b.remote = False
            self._start_jack(b, None, 0.5 if b.kind in vehicles.BIKES else 1.0)
            return True
        self._board(b)
        return True

    # carjack: the door swings open, the driver is slammed out onto the asphalt (out cold), you get in, the door shuts
    def _start_jack(self, b, victim, dur, stolen=False):
        """victim: "driver" (an AI car: the hero yanks them out), a Ped on a two-wheeler, or None (empty vehicle)."""
        wk = self.walker
        if b is not None:
            b.empty, b.ctl = False, None
        self.jack = {"b": b, "t": 0.0, "dur": dur, "victim": victim, "x0": wk.x, "y0": wk.y, "in": False, "held": None,
                     "door": b is not None and b.kind not in vehicles.BIKES, "stolen": stolen or victim is not None}

    def _seat_point(self, b, out):
        L, W = CIRC[b.kind][0], CIRC[b.kind][1]
        lx, ly = math.sin(b.h), -math.cos(b.h)
        fx, fy = math.cos(b.h), math.sin(b.h)
        return b.x + lx * (W + out) + fx * L * 0.1, b.y + ly * (W + out) + fy * L * 0.1

    def _walk_to(self, wk, j, tx, ty, k, dt):
        wk.x, wk.y = j["x0"] + (tx - j["x0"]) * k, j["y0"] + (ty - j["y0"]) * k
        wk.vx = wk.vy = 0.0
        if 0 < k < 1:
            wk.moving = True
            wk.anim += dt * 3.0
            if (tx - j["x0"]) ** 2 + (ty - j["y0"]) ** 2 > 0.01:
                wk.h = math.atan2(ty - j["y0"], tx - j["x0"])
        else:
            wk.moving = False

    def _tick_jack(self, dt):
        """Carjack, step by step: walk to the door, open it, reach in, grab the driver, yank them out onto the asphalt
        (out cold), get in, door shuts. Two-wheelers: walk up, grab the rider, shove them off, hop on."""
        j = self.jack
        b, wk, v = j["b"], self.walker, j["victim"]
        rider = v is not None and v != "driver"
        if (b is not None and (b not in self.bodies or not b.alive)) or (wk is None and not j["in"]) or (wk is not None and wk.health <= 0) \
                or (rider and b is None and (v not in self.peds.list or v.mode != "svc")):
            if b is not None:
                b.door = 0.0
            if j["held"] is not None:
                j["held"].mode, j["held"].t = "ko", 6.0
            self.jack = None
            return
        j["t"] += dt
        t, T = j["t"], j["dur"]
        if j["in"]:
            if j["door"] and b.door > 0:
                b.door = max(0.0, b.door - dt / 0.3)
                if b.door <= 0:
                    self.ev("door_shut", body=b)
                return
            self.jack = None
            return
        if rider:                                                    # ---- two-wheeler
            if b is None:
                ang = v.h
                tx, ty = v.x - math.sin(ang) * 0.9, v.y + math.cos(ang) * 0.9        # beside the rider
                self._walk_to(wk, j, tx, ty, min(1.0, t / 0.3), dt)
                if t >= 0.3:
                    wk.h = math.atan2(v.y - wk.y, v.x - wk.x)
                    wk.atk_t, wk.atk_kind = 0.12, 4                  # arm out: grabs them by the collar
                if t >= 0.55:                                        # shove: rider off, bike stays
                    b = j["b"] = Body(v.x, v.y, v.h, vehicles.JACK_KIND[v.arch], 0)
                    b.az = v.gz
                    b.empty = False
                    self.bodies.append(b)
                    dx, dy = v.x - wk.x, v.y - wk.y
                    d = math.hypot(dx, dy) or 1.0
                    v.mode, v.t, v.hy, v.hv, v.ko_land, v.spin = "air", 5.0, 0.4, 3.0, True, 0.0
                    v.vx, v.vy = dx / d * 4.5, dy / d * 4.5
                    self.ev("shout", text=TXT("vehicles.%04d" % self.rng.randrange(310, 316)), x=v.x, y=v.y)
                    self.ev("knock_off", x=v.x, y=v.y)
                    j["x0"], j["y0"] = wk.x, wk.y
                return
            self._walk_to(wk, j, b.x, b.y, min(1.0, (t - 0.55) / 0.25), dt)
        elif v == "driver":                                          # ---- car with a driver
            dx_, dy_ = self._seat_point(b, 0.55)
            self._walk_to(wk, j, dx_, dy_, min(1.0, t / 0.35), dt)
            lx, ly = math.sin(b.h), -math.cos(b.h)
            if t >= 0.35:
                wk.h = math.atan2(-ly, -lx)                          # facing the car
                if b.door == 0:
                    self.ev("door", body=b)
                b.door = min(1.0, (t - 0.35) / 0.3)                  # the hero pulls the door open
            if 0.65 <= t < 1.25:
                wk.atk_t, wk.atk_kind = 0.12, 4                      # reaches in, grabs the driver
            if t >= 0.85 and j["held"] is None:                      # dragged out of the seat, still on their feet
                sx, sy = self._seat_point(b, -0.25)
                p = self.peds.eject(sx, sy, math.atan2(ly, lx), gz=b.az)
                p.mode, p.t, p.v = "svc", 999.0, 0.0
                j["held"] = p
                self.ev("shout", text=self.rng.choice(slang.DRIVER_RAGE), x=p.x, y=p.y)
            p = j["held"]
            if p is not None and p.mode == "svc":
                if t < 1.2:                                          # hauled across the sill toward the hero
                    k = (t - 0.85) / 0.35
                    sx, sy = self._seat_point(b, -0.25)
                    p.x, p.y = sx + (wk.x - sx) * k * 0.8, sy + (wk.y - sy) * k * 0.8
                    p.h = math.atan2(wk.y - p.y, wk.x - p.x)
                else:                                                # yanked past the hero and slammed onto the asphalt
                    p.mode, p.t, p.hy, p.hv, p.ko_land, p.spin = "air", 5.0, 0.6, 2.0, True, 0.0
                    bx, by = math.cos(b.h), math.sin(b.h)
                    p.vx, p.vy = lx * 5.5 - bx * 2.0, ly * 5.5 - by * 2.0
                    self.ev("slam", x=p.x, y=p.y)
                    j["x0"], j["y0"] = wk.x, wk.y
            if t >= 1.25:
                tx, ty = self._seat_point(b, 0.25)
                self._walk_to(wk, j, tx, ty, min(1.0, (t - 1.25) / max(0.1, T - 1.25)), dt)
        else:                                                        # ---- empty car / abandoned bike
            if j["door"]:
                tx, ty = self._seat_point(b, 0.35)
                self._walk_to(wk, j, tx, ty, min(1.0, t / 0.4), dt)
                if t >= 0.4:
                    if b.door == 0:
                        self.ev("door", body=b)
                    b.door = min(1.0, (t - 0.4) / 0.3)
            else:
                self._walk_to(wk, j, b.x, b.y, min(1.0, t / max(0.1, T)), dt)
        if t >= T:
            j["in"] = True
            wk.moving = False
            self.ev("stolen" if j["stolen"] else "enter", body=b)
            self._board(b)

    def _board(self, b):
        if self.car is not None and self.car is not b:
            self.car.player_car = False
        self.car = b
        b.player_car, b.empty = True, False
        b.skid = None
        self.mode = "car"
        self.walker = None

    def take_bus(self):
        """Ctrl while riding: throw the driver out and drive the bus yourself."""
        b = self.riding
        self.riding = None
        if b is None:
            return
        if getattr(self, "transit", None) is not None:
            self.transit.buses = [bus for bus in self.transit.buses if bus.body is not b]
        lx, ly = math.sin(b.h), -math.cos(b.h)
        p = self.peds.eject(b.x + lx * 2.4, b.y + ly * 2.4, b.h + math.pi / 2, gz=b.az)
        self.ev("shout", text=self.rng.choice(slang.DRIVER_RAGE), x=p.x, y=p.y)
        b.player_car, b.empty, b.ctl = True, False, None
        self.stats["stolen"] += 1
        self.ev("stolen", body=b)

    def _shore(self, x, y, fallback):
        """The nearest dry bank point to (x, y): rings of growing radius, first land that is not water or a bare bridge gap."""
        w = self.w
        for r in range(2, 90, 2):
            for k in range(max(8, r)):
                a = k * 2 * math.pi / max(8, r)
                px, py = x + math.cos(a) * r, y + math.sin(a) * r
                if w.surface(px, py) in (2, 3) and not w.wet(px, py, w.ground_y(px, py)):
                    return px, py
        return fallback[0], fallback[1]

    def exit_car(self):
        if self.mode != "car":
            return
        b = self.car
        if getattr(self, "riding", None) is not None:              # get off the bus; it carries on along its line
            self.riding = None
            L, W = CIRC[b.kind][0], CIRC[b.kind][1]
            fx, fy = math.cos(b.h), math.sin(b.h)
            x, y = b.x + fx * L * 0.5 - fy * (W + 1.0), b.y + fy * L * 0.5 + fx * (W + 1.0)
            self.walker = Walker(x, y, b.h)
            self.walker.az = b.az
            self.car = None
            self.mode = "foot"
            self.ev("alight")
            return
        b.empty = True
        b.player_car = False
        self.last_exit = b
        L, W = CIRC[b.kind][0], CIRC[b.kind][1]
        lx, ly = math.sin(b.h), -math.cos(b.h)
        for side in (1, -1):
            x, y = b.x + lx * side * (W + 0.9), b.y + ly * side * (W + 0.9)
            if not any(True for _ in self.w.edges_near(x, y, 0.5)):
                break
        self.walker = Walker(x, y, b.h)
        self.walker.az = b.az
        self.mode = "foot"

    # ---------------------------------------------------------------- per-frame update
    def update(self, dt, inp, steps):
        w, rng = self.w, self.rng
        HX, HY = w.hx, w.hy
        ev = self.ev
        self.clock.update(dt)
        inp = self.stations.update(dt, inp) or inp                # fill-up / car wash for the player's car
        self.traffic.target = max(6, int(self.base_cars * self.clock.traffic * self.dens_traffic))
        self.peds.target = max(6, int(self.base_peds * self.clock.peds * self.dens_peds))
        if getattr(self, "jack", None) is not None:              # the carjack plays out; the controls wait
            self._tick_jack(dt)
            inp = dict(inp, move=(0, 0), attack=False, jump=False)
        # ---------------- player
        if self.mode == "car" and getattr(self, "riding", None) is not None:
            if self.riding not in self.bodies or not self.riding.alive:
                self.riding = None
            elif inp.get("attack"):
                self.take_bus()
        if self.mode == "car":
            c = self.car
            ride = getattr(self, "riding", None) is not None
            for _ in range(steps):
                sdt = dt / steps
                if ride:
                    drive(c, *(c.ctl if c.ctl is not None else (0.0, 0.0, True)), sdt, w)
                    thr = 0.0
                else:
                    thr = inp["throttle"] if c.fuel > 0 or inp["throttle"] < 0 else 0.0     # empty tank: it only rolls
                    drive(c, thr, inp["steer"], inp["handbrake"], sdt, w)
                if thr > 0:
                    was = c.fuel
                    c.fuel = max(0.0, c.fuel - math.hypot(c.vx, c.vy) * sdt * (0.6 + 0.4 * thr) / (FUEL_KM * 1000.0))
                    if was > 0.15 >= c.fuel:
                        ev("fuel_low")
                    if was > 0 >= c.fuel:
                        ev("fuel_out")
                settle(c, w, sdt, ev)
                for e in collide_static(c, w):
                    ev("crash", body=c, kind=e[0], impact=e[1], x=e[2], y=e[3], nx=e[4], ny=e[5])
                    bump(c, e[1] * (0.6 if e[0] != "wall" else 1.0), e[2], e[3], e[4], e[5])
                if abs(c.x) > HX - 8:
                    c.x = math.copysign(HX - 8, c.x)
                    c.vx *= -0.2
                if abs(c.y) > HY - 8:
                    c.y = math.copysign(HY - 8, c.y)
                    c.vy *= -0.2
            c.honk_t -= dt
            if inp["horn"] and c.honk_t <= 0:
                c.honk_t = 1.2
                ev("horn", body=c)
                if c.kind in clock.EMERGENCY:
                    c.siren = not getattr(c, "siren", False)
            sf = w.surface(c.x, c.y)
            wet = w.wet(c.x, c.y, c.az if c.az is not None else 0.0) if sf != 3 else False
            if sf in (2, 3) and c.alive and c.health > 20 and not wet and not c.air:
                self.safe = (c.x, c.y, c.h)
                self.safe_z = c.az
            if wet:
                c.drown += dt
                c.vx *= math.exp(-2.5 * dt)
                c.vy *= math.exp(-2.5 * dt)
                if c.drown > 1.3 and c is self.car and self.mode == "car":
                    ev("splash", x=c.x, y=c.y, big=True)             # the car sinks with you in it
                    ev("walker_dead", cause="drown")
                    self.exit_car()
                    self.walker.health = 0
                    self.walker.cause = "drown"
                    c.drown = 0.0
                elif c.drown > 1.3:
                    ev("splash", x=c.x, y=c.y)
                    c.x, c.y, c.h = self.safe
                    c.az, c.vz = self.safe_z, 0.0
                    c.vx = c.vy = 0.0
                    c.drown = 0.0
                    c.health = max(c.health, 40)
            else:
                c.drown = 0.0
        else:
            wk = self.walker
            if self.train_ride is not None:                        # a passenger: the controls wait, the carriage carries you
                inp = dict(inp, move=(0, 0), attack=False, jump=False)
            if wk.health > 0:
                wk.combo_t = getattr(wk, "combo_t", 0.0) - dt
                if wk.combo_t <= 0:
                    wk.combo = 0
                px0, py0 = wk.x, wk.y
                wk.jump_t = 0.35 if inp.get("jump") else getattr(wk, "jump_t", 0.0) - dt     # Space: hop over small / crawl under big vehicles in the way
                if wk.duck_t > 0.0:
                    wk.duck_t -= dt
                    wk.update(dt, inp["move"][0], inp["move"][1] * 0.5, False, w, False)      # crawling: half speed, no running or jumping
                    wk.anim += abs(inp["move"][1]) * dt * 1.2
                else:
                    wk.update(dt, inp["move"][0], inp["move"][1], inp["run"], w, inp.get("jump", False))
                if inp.get("attack"):
                    self.attack()
                if inp.get("buy") is not None:
                    self.buy(inp["buy"])
                if inp["horn"]:
                    ev("shout_self", text="")                  # H: your own character says something (main.py picks the line)
                sf = w.surface(wk.x, wk.y)
                if wk.land_v > 0:                                  # landed: hard falls hurt, water cushions them
                    v, wk.land_v = wk.land_v, 0.0
                    if w.wet(wk.x, wk.y, wk.az):
                        ev("splash", x=wk.x, y=wk.y, big=v > 5.0)
                        v *= 0.3
                    if v > 8.5:
                        dmg = (v - 8.5) * 8.0
                        wk.health -= dmg
                        wk.hurt_t = 0.5
                        if wk.health <= 0:
                            wk.cause = "fall"
                            ev("walker_dead", cause="fall")
                        else:
                            ev("hurt_fall", dmg=dmg)
                if w.wet(wk.x, wk.y, wk.az) and sf != 3:
                    wk.dead_t += dt
                    if wk.dead_t > 1.0:
                        ev("splash", x=wk.x, y=wk.y)
                        wk.x, wk.y = self._shore(wk.x, wk.y, self.safe)      # you swim to the nearest bank
                        wk.az, wk.vz = w.ground_y(wk.x, wk.y), 0.0
                        wk.dead_t = 0
                elif sf in (2, 3) and wk.z < 0.3:
                    wk.dead_t = 0
                    self.safe = (wk.x, wk.y, wk.h)
                    self.safe_z = wk.az
                near_tc = []
                step_ = math.hypot(wk.x - px0, wk.y - py0)
                for c_ in self.traffic.cars:                       # AI traffic is solid too (it used to be walk-through)
                    rr_ = _RAD[c_.kind] + 0.5 + step_ + abs(c_.v) * dt
                    if (c_.x - wk.x) ** 2 + (c_.y - wk.y) ** 2 <= rr_ * rr_:
                        near_tc.append(self.traffic.make_body(c_))
                for b in self.bodies + near_tc:
                    rr_ = _RAD[b.kind] + 0.5 + step_ + math.hypot(b.vx, b.vy) * dt
                    if (b.x - wk.x) ** 2 + (b.y - wk.y) ** 2 > rr_ * rr_:
                        continue
                    top = vehicles.DIMS[b.kind][4] * 0.6
                    if wk.z > top:                         # jumped onto / over the car
                        continue
                    if wk.duck_t > 0.0 and getattr(wk, "duck_b", None) is b:
                        continue                           # crawling under it
                    hit = push_from_box(b, wk.x, wk.y, 0.38)
                    if hit is None:                        # swept: player and car moved a lot this frame (run, big dt): test the path
                        mv = step_ + math.hypot(b.vx, b.vy) * dt
                        for k in range(1, int(mv / 0.25) + 1):
                            f_ = k * 0.25 / mv
                            hit = push_from_box(_At(b, -dt * (1.0 - f_)), px0 + (wk.x - px0) * f_, py0 + (wk.y - py0) * f_, 0.38)
                            if hit is not None:
                                break
                        if hit is None:
                            continue
                    nx, ny, pen = hit
                    closing = -((b.vx - wk.vx) * nx + (b.vy - wk.vy) * ny)      # > 0 when the car moves into the player
                    if getattr(wk, "jump_t", 0.0) > 0 and wk.moving and inp["move"][1] > 0.3 and math.hypot(b.vx, b.vy) < 1.5 and wk.z < 0.3:
                        if top <= 1.15:                    # walking into a small vehicle: hop over it
                            wk.vz = 6.6
                            continue
                        wk.duck_t, wk.duck_b = 2.2, b      # a big one: crouch and crawl underneath
                        continue
                    wk.x += nx * pen
                    wk.y += ny * pen
                    wk.push_out(w)
                    if closing > 4.5 and wk.inv_t <= 0 and not b.empty and (self.pvp or not getattr(b, "remote", False)):
                        dmg = (closing - 3.0) * 5.5
                        wk.health -= dmg
                        wk.hurt_t, wk.inv_t = 0.5, 0.6
                        sp = math.hypot(b.vx, b.vy)
                        k = min(0.5, 6.0 / sp) if sp > 1e-3 else 0.0        # knocked aside, not launched across town
                        wk.vx += b.vx * k
                        wk.vy += b.vy * k
                        if wk.health <= 0:
                            wk.cause = "car"
                            ev("walker_dead", cause="car")
                        else:
                            ev("hurt_car", dmg=dmg)
                if wk.health > 0 and (abs(wk.x) > HX - 5 or abs(wk.y) > HY - 5):
                    wk.x = max(-HX + 5, min(HX - 5, wk.x))
                    wk.y = max(-HY + 5, min(HY - 5, wk.y))
            else:
                self.respawn_t += dt
                ko = wk.cause == "fight"
                if self.respawn_t == dt and ko:
                    lost = int(self.money * 0.4)
                    self.money -= lost
                    ev("knocked_out", lost=lost)
                waiting = (not ko) and self.services.amb_on and self.respawn_t < 50.0 and self.services.has_job_for(wk)
                again = inp.get("respawn") or getattr(self, "auto_respawn", False)   # dead: R to start again
                if (self.respawn_t > 4.5 if ko else (self.respawn_t > 1.0 and again)) and (not waiting or again):
                    self.respawn_t = 0
                    if not ko:
                        p = w.nearest_drive_point(*(self.respawn_hint or (wk.x, wk.y)))
                        if p:
                            wk.x, wk.y = p[0], p[1] + 2.0
                    wk.az, wk.vz = None, 0.0
                    wk.vx = wk.vy = 0
                    wk.health = 35 if ko else 100
                    wk.cause = None
                    wk.inv_t = 1.5
                    ev("wake" if ko else "respawn")
        # ---------------- other bodies
        fx, fy, fvx, fvy = self.focus()
        if not self.client:
            self._dispatch()
            self.services.update(dt)
        self.chaos.update(dt)
        if getattr(self, "transit", None) is not None and not self.client:
            self.transit.update(dt)
        if getattr(self, "kids", None) is not None and not self.client:
            self.kids.update(dt)
        if getattr(self, "dogs", None) is not None:
            self.dogs.update(dt)
        if getattr(self, "birds", None) is not None:
            self.birds.update(dt)
        if getattr(self, "rentals", None) is not None:
            self.rentals.update(dt)
        if getattr(self, "works", None) is not None:
            self.works.update(dt)
        self.shots.update(dt)
        for b in list(self.bodies):
            if getattr(b, "remote", False):                      # another player's car / a host puppet: placed by mpgame, not simulated here
                continue
            b.age += dt
            if b is not self.car or self.mode == "foot":
                if b.ctl is None and not b.player_car and not b.air and b.vx * b.vx + b.vy * b.vy < 1e-8 and abs(b.w) < 1e-4:
                    rp = getattr(b, "rest_pose", None)           # at rest: after a second of standing still it sleeps
                    if rp is not None and abs(rp[0] - b.x) + abs(rp[1] - b.y) + abs(rp[2] - b.h) < 1e-4:
                        b.rest_n = getattr(b, "rest_n", 0) + 1
                        if b.rest_n >= 60:
                            b.w = 0.0
                    else:
                        b.rest_pose, b.rest_n = (b.x, b.y, b.h), 0
                else:
                    b.rest_n = 0
                if getattr(b, "rest_n", 0) < 60:                  # (anything that moves it - a push, a hit, a blast - wakes it)
                    drive(b, *(b.ctl if b.ctl is not None and not b.player_car else (0.0, 0.0, True)), dt, w)
                    settle(b, w, dt, ev)
                    for e in collide_static(b, w):
                        ev("crash", body=b, kind=e[0], impact=e[1], x=e[2], y=e[3], nx=e[4], ny=e[5])
                        bump(b, e[1] * 0.6, e[2], e[3], e[4], e[5])
                    if w.wet(b.x, b.y, b.az if b.az is not None else 0.0) and w.surface(b.x, b.y) != 3:
                        b.vx *= 0.9
                        b.vy *= 0.9
            b.h += b.w * dt
            b.w *= math.exp(-2.0 * dt)
            if b.health <= 0 and not b.exploded:
                b.burn += dt
                if b.burn > 3.6:
                    b.exploded, b.age = True, 0.0             # age now counts the time since the blast
                    self.stats["boom"] += 1
                    ev("explode", body=b)
                    self.chaos.blast(b.x, b.y, 9.0)
                    if (b.x - fx) ** 2 + (b.y - fy) ** 2 < 120 ** 2:
                        self._pay(60 if not b.service else 0, b.x, b.y)
                    for o in self.bodies:
                        if o is not b:
                            d = math.hypot(o.x - b.x, o.y - b.y)
                            if d < 9:
                                o.health -= (9 - d) * 6
                                n = d or 1.0
                                o.vx += (o.x - b.x) / n * (9 - d) * 0.9
                                o.vy += (o.y - b.y) / n * (9 - d) * 0.9
                                o.dirty = True
                    if b is self.car and self.mode == "car":
                        ev("walker_dead", cause="explosion")
                        self.exit_car()
                        self.walker.health = 0
                    b.dirty = True
        # body <-> body
        for i, j in body_pairs(self.bodies):
            a, b = self.bodies[i], self.bodies[j]
            r = collide_bodies(a, b, vehicles.PERF[a.kind][4], vehicles.PERF[b.kind][4])
            if r and r[0] > 1.5:
                ev("crash", body=a if a.player_car else b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
                if (a.player_car or b.player_car) and r[0] > 3.0 and not (a.service or b.service) and self.mode == "car" \
                        and a.health > 0 and b.health > 0:            # (ramming a wreck again pays nothing)
                    self._pay(min(60, int(r[0] * 3)), r[1], r[2])             # smashing into things pays
        # ---------------- traffic <-> bodies (hits convert AI cars into drivable wrecks)
        bgrid = {}
        for b in self.bodies:
            bgrid.setdefault((int(b.x // 16), int(b.y // 16)), []).append(b)
        for c in list(self.traffic.cars):
            gx_, gy_ = int(c.x // 16), int(c.y // 16)
            near_ = [b for dx in (-1, 0, 1) for dy in (-1, 0, 1) for b in bgrid.get((gx_ + dx, gy_ + dy), ())]
            for b in near_:
                rr_ = _RAD[b.kind] + _RAD[c.kind]
                if (c.x - b.x) ** 2 + (c.y - b.y) ** 2 > rr_ * rr_:
                    continue
                tmp = self.traffic.make_body(c)
                tmp.parked_idx = None
                r = collide_bodies(b, tmp, vehicles.PERF[b.kind][4], vehicles.PERF[tmp.kind][4])
                if r and r[0] > (12.0 if b.service or vehicles.LARGE[c.kind] else 7.0):     # a real crash, not a knock
                    tmp.empty = True
                    self.bodies.append(tmp)
                    self.traffic.cars.remove(c)
                    lx, ly = math.sin(tmp.h), -math.cos(tmp.h)
                    p = self.peds.eject(tmp.x + lx * 2.0, tmp.y + ly * 2.0, tmp.h + math.pi / 2, gz=tmp.az)
                    if rng.random() < 0.7:
                        ev("shout", text=rng.choice(slang.PED_HIT + slang.DRIVER_RAGE[1:3]), x=p.x, y=p.y)
                    ev("crash", body=b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
                    if b.player_car and self.mode == "car" and b.health > 0:
                        self._pay(min(80, int(r[0] * 4)), r[1], r[2])
                    break
                elif r:                                  # light touch / small knock: shoved aside, it brakes and drives on
                    c.x, c.y, c.h = tmp.x, tmp.y, tmp.h
                    c.v = min(c.v, 1.0)
                    if r[0] > 2.0:
                        ev("crash", body=b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
                        if b.player_car and self.mode == "car" and b.health > 0:
                            self._pay(min(30, int(r[0] * 2)), r[1], r[2])
        self.trains.update(dt)
        tr = self.train_ride
        if tr is not None and self.mode == "foot" and self.walker is not None:
            if tr.ended:                                           # the train left the map: back to the nearest station
                tr.ended = False
                ex, ey, _z, _h = tr.line.at(tr.s)
                st = min(getattr(w, "stations", ()) or (), key=lambda q: math.hypot(q[1] - ex, q[2] - ey), default=None)
                self.train_ride = None
                if st is not None:
                    self.walker.x, self.walker.y, self.walker.vx, self.walker.vy = st[1], st[2], 0.0, 0.0
                    self.ev("alight")
            else:
                self.walker.x, self.walker.y, _z, _h = tr.line.at(tr.s - tr.d * (trains.CAR_L / 2))
        elif tr is not None:
            self.train_ride = None
        if not self.client:
            self.traffic.update(dt, fx, fy, self.bodies, self.peds.list, self.walker if self.mode == "foot" else None)
        self._cull_t -= dt
        if self._cull_t <= 0 and not self.client:                       # thin the crowd / traffic when the clock says it is quiet
            self._cull_t = 0.2
            cars = self.traffic.cars
            if len(cars) > self.traffic.target + 2:
                far = max(cars, key=lambda c: (c.x - fx) ** 2 + (c.y - fy) ** 2)
                if (far.x - fx) ** 2 + (far.y - fy) ** 2 > 130 ** 2:
                    cars.remove(far)
            walkers = [p for p in self.peds.list if p.mode == "walk"]
            if len(walkers) > self.peds.target + 3:
                far = max(walkers, key=lambda p: (p.x - fx) ** 2 + (p.y - fy) ** 2)
                if (far.x - fx) ** 2 + (far.y - fy) ** 2 > 110 ** 2:
                    self.peds.list.remove(far)
        self.peds.walker = self.walker if self.mode == "foot" else None
        if not self.client:
            self.peds.update(dt, fx, fy, self.bodies, self.ev)
        self._parked(fx, fy)
        # cleanup far away, burnt out or useless bodies
        keep = []
        for b in self.bodies:
            if b is self.car or getattr(b, "remote", False):
                keep.append(b)
                continue
            d2 = (b.x - fx) ** 2 + (b.y - fy) ** 2
            if d2 > 420 ** 2 or (b.exploded and b.age > clear_secs(self) and not self.services.has_job_for(b)):
                if b.model is not None:
                    self.ev("free_model", model=b.model)
                continue
            keep.append(b)
        self.bodies = keep
        # ---------------- pickups (weapons reshuffle every morning at 6)
        h_ = self.clock.hour
        if getattr(self, "_last_h", h_) < 6.0 <= h_:
            self._spawn_weapons(self.rng)
            ev("weapons_new")
        self._last_h = h_
        pr = 2.6 if self.mode == "car" else 1.5
        taken = []
        for pk in self.pickups:
            if pk[2] == "fuel":
                if self.mode == "car" and pk[3] and abs(pk[0] - fx) < 3.0 and abs(pk[1] - fy) < 3.0:
                    self.car.fuel = min(1.0, self.car.fuel + 0.5)
                    ev("fuel", x=pk[0], y=pk[1], f=self.car.fuel)
                    pk[3], pk[4] = False, 180.0
                elif not pk[3]:
                    pk[4] -= dt
                    if pk[4] <= 0:
                        pk[3] = True
                continue
            if pk[2] in ("cash",) + tuple(WEAPONS):
                if self.mode == "foot" and self.walker.health > 0 and pk[3] and abs(pk[0] - fx) < 1.3 and abs(pk[1] - fy) < 1.3:
                    if pk[2] == "cash":
                        amt = 30 + int(abs(pk[0] * 7 + pk[1] * 3)) % 90
                        self.money += amt
                        ev("cash", amt=amt, x=pk[0], y=pk[1])
                        taken.append(pk)
                    else:
                        self.walker.give(pk[2])
                        ev("gun", x=pk[0], y=pk[1], kind=pk[2], name=WEAPONS[pk[2]][0])
                        pk[3], pk[4] = False, 240.0
                    continue
                if not pk[3]:
                    pk[4] -= dt
                    if pk[4] <= 0:
                        pk[3] = True
                continue
            if not pk[3]:
                pk[4] -= dt
                if pk[4] <= 0:
                    pk[3] = True
                continue
            if abs(pk[0] - fx) < pr and abs(pk[1] - fy) < pr:
                if pk[2] == "burek":
                    self.stats["burek"] += 1
                    ev("burek", x=pk[0], y=pk[1])
                    pk[3], pk[4] = False, 180.0
                elif self.mode == "car":
                    self.car.health = 100.0
                    self.car.dents = []
                    self.car.burn = 0
                    self.car.dirty = True
                    self.stats["ajvar"] += 1
                    ev("ajvar", x=pk[0], y=pk[1])
                    pk[3], pk[4] = False, 180.0
        for pk in taken:
            self.pickups.remove(pk)

    def _dispatch(self):
        """Call the ambulance for dead people and the fire brigade for burning / burnt-out cars (near the player only)."""
        fx, fy, _a, _b = self.focus()
        sv = self.services
        if sv.amb_on:
            for p in self.peds.list:
                if p.mode in ("dead", "air") and not getattr(p, "svc", False) and (p.x - fx) ** 2 + (p.y - fy) ** 2 < 420 ** 2:
                    if sv.request("amb", p, p.x, p.y):
                        p.svc = True
                        p.t = max(p.t, 80.0)
            wk = self.walker
            if self.mode == "foot" and wk is not None and wk.health <= 0 and wk.cause != "fight" and not getattr(wk, "svc", False):
                wk.svc = True
                sv.request("amb", wk, wk.x, wk.y, 2.0)
            if wk is not None and wk.health > 0:
                wk.svc = False
        if sv.fire_on:
            for b in self.bodies:
                if not b.out and not b.service and b.health <= 0 and (b.burn > 0.4 or b.exploded) and (b.x - fx) ** 2 + (b.y - fy) ** 2 < 420 ** 2:
                    sv.request("fire", b, b.x, b.y, 1.5)

    def _parked(self, fx, fy):
        w = self.w
        P = w.parked
        R = getattr(self, "view_r", 150.0)                   # the camera sets how far the screen reaches (zoomed out: further)
        # despawn untouched parked cars that are far away
        for idx, b in list(self.parked.items()):
            if b.parked_idx is None or b not in self.bodies:
                del self.parked[idx]
            elif (b.x - fx) ** 2 + (b.y - fy) ** 2 > (R + 90) ** 2 and b.speed < 0.2 and not b.dents:
                self.bodies.remove(b)
                del self.parked[idx]
            elif b.speed > 0.4 or b.dents:
                self.gone.add(idx)
                b.parked_idx = None
                del self.parked[idx]
        if not len(P):
            return
        grid = getattr(self, "_pgrid", None)
        if grid is None:                                      # 48 m cells, built once: only the cells round the camera are looked at
            grid = self._pgrid = {}
            for i, q in enumerate(P):
                grid.setdefault((int(q[0] // 48), int(q[1] // 48)), []).append(i)
        r2, k0, n_new = R * R, int(R // 48) + 1, 0
        cx, cy = int(fx // 48), int(fy // 48)
        cells = sorted(((gx, gy) for gx in range(cx - k0, cx + k0 + 1) for gy in range(cy - k0, cy + k0 + 1) if (gx, gy) in grid),
                       key=lambda c: (c[0] * 48 + 24 - fx) ** 2 + (c[1] * 48 + 24 - fy) ** 2)       # nearest first: the street you look at fills first
        for c in cells:
            for idx in grid[c]:
                if idx in self.parked or idx in self.gone:
                    continue
                x, y, ang, col, kind = P[idx]
                if (x - fx) ** 2 + (y - fy) ** 2 < r2:
                    b = Body(x, y, ang, kind, col)
                    b.parked_idx = idx
                    self.bodies.append(b)
                    self.parked[idx] = b
                    n_new += 1
            if n_new >= 160:                                  # at most this many new bodies a frame, so a sudden zoom-out doesn't stall
                break
