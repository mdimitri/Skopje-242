"""Simulation: car physics with damage, traffic, pedestrians, on-foot play, hijacking, pickups."""
from texts import TXT
import math
import random
from types import SimpleNamespace

import bible_lines
import bump_lines
import clock
from crosswalks import begin_frame, crosses_wall, over_budget, walk_path
from driving import (SIGNAL_STOP_BUFFER, TRAFFIC_SPEED_FACTOR, brake_speed, corridor_entry, fastest_route,
                     follow_speed, movement_lanes, turn_angle, turn_indicator, turn_lanes)
import escride
import garbage
from hero_profiles import DEFAULT_STARTING_CASH
from laneassist import LaneAssist
import peds_lines
import talk
import trains
import projectiles
from roadwidth import half_width, lane_bounds, lane_count
import slang
import vehicles

_LINES = {}

# weapons: key -> (Macedonian name, seconds between shots, damage, pellets, spread rad, range m, ammo per pickup)
WEAPONS = {"pistol": (TXT("actors.0001"), 0.28, 45, 1, 0.0, 40, 90), "uzi": (TXT("actors.0002"), 0.09, 22, 1, 0.06, 32, 300),
           "shotgun": (TXT("actors.0003"), 0.85, 30, 6, 0.16, 18, 60), "kalash": (TXT("actors.0004"), 0.12, 40, 1, 0.03, 60, 240),
           "bat": (TXT("actors.0005"), 0.55, 34, 1, 0.0, 1.9, 9999), "zolja": (TXT("actors.0006"), 1.6, 400, 1, 0.0, 90, 14),
           "knuckles": ("Боксирач", 0.3, 28, 1, 0.0, 1.2, 9999), "chain": ("Ланец", 0.5, 26, 1, 0.0, 2.6, 9999),
           "machete": ("Мачета", 0.45, 48, 1, 0.0, 1.8, 9999), "revolver": ("Револвер", 0.6, 70, 1, 0.01, 45, 36),
           "smg": ("Ингрем", 0.07, 16, 1, 0.09, 26, 400), "cutters": ("Макази", 0.9, 6, 1, 0.0, 1.4, 9999)}
MELEE = ("bat", "knuckles", "chain", "machete", "cutters")                # swung, not fired: no tracer, no ammo used
from weaponart import swing_az   # noqa: E402
SWINGERS = ("bat", "chain")                          # two-handed swings: swept arc hits, arms follow (render swing frames 60..67)
SWING_T = 0.36                  # seconds of one bat swing (the renderer sweeps the bat across the body)
WEAPON_ORDER = ["fist", "cutters", "knuckles", "chain", "bat", "machete", "pistol", "revolver", "uzi", "smg", "shotgun", "kalash", "zolja"]

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
        self.indicator = 0          # -1 left, +1 right
        self.indicator_t = 0.0
        self.trh = None              # articulated vehicle's rear heading (None: straight behind its front section)
        self.tra = None              # semi: where the trailer's axle group is (x, y)
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
        self.rotor = 0.0             # helicopter: main rotor angle (rad)
        self.rpm = 0.0               # helicopter: rotor speed 0..1 (spins up while someone sits in it)
        self.door = 0.0              # driver's door: 0 shut .. 1 wide open (carjack animation, drawn by the renderer)

    def signal_turn(self, signal, dt):
        if signal:
            self.indicator, self.indicator_t = signal, 1.25
        else:
            self.indicator_t = max(0.0, self.indicator_t - dt)
            if not self.indicator_t:
                self.indicator = 0

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    @property
    def alive(self):
        return self.health > 0 and not self.exploded


class Heli(Body):
    """Helicopter body: an armoured airframe, it takes a third of the damage a car would (same 0..100 health scale)."""
    ARMOR = 0.33

    @property
    def health(self):
        return self.__dict__.get("_hp", 100.0)

    @health.setter
    def health(self, v):
        old = self.__dict__.get("_hp")
        self.__dict__["_hp"] = v if old is None or v >= old else old - (old - v) * self.ARMOR


class Apc(Body):
    """БТР-80: crashes and blasts barely scratch it (2 %); 100 small-arms hits or one direct Зоља hit finish it (Martin: 2x the hit points)."""
    ARMOR = 0.02

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.turret = 0.0            # turret angle relative to the hull (rad)
        self.ammo = 300              # 30 mm rounds
        self.gun_cd = 0.0
        self.locked = False          # True: the crew keeps it shut (only one per barracks can be taken)

    @property
    def health(self):
        return self.__dict__.get("_hp", 100.0)

    @health.setter
    def health(self, v):
        old = self.__dict__.get("_hp")
        self.__dict__["_hp"] = v if old is None or v >= old else old - (old - v) * self.ARMOR

    def shot(self, kind):
        """A projectile hit: bullets and pellets chip it (50 rounds kill it), a 30 mm shell does five times that."""
        self.__dict__["_hp"] = self.health - {"bullet": 1.0, "pellet": 0.35, "shell30": 5.0}.get(kind, 2.0)
        self.dirty = True

    def wreck(self):
        self.__dict__["_hp"] = -1.0
        self.dirty = True


def offsets(kind):
    """Centres of the collision circles along the car: spaced at most one radius apart, so long buses and trucks
    have no gaps a wall corner or lamp post can slip into."""
    off, r = CIRC[kind]
    n = max(3, int(math.ceil(2 * off / (r * 0.9))) + 1)
    return [-off + 2 * off * i / (n - 1) for i in range(n)]


def parts(b):
    """Collision boxes (cx, cy, heading, half length, half width), one per rigid section."""
    L, W = vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2
    if b.kind == vehicles.ARTIC_BUS:
        hinge = vehicles.ARTIC_HINGE
        h, rear = b.h, b.h if b.trh is None else b.trh
        hx, hy = b.x + math.cos(h) * hinge, b.y + math.sin(h) * hinge
        front_mid = rear_half = (L + hinge) / 2
        return ((b.x + math.cos(h) * front_mid, b.y + math.sin(h) * front_mid, h, (L - hinge) / 2, W),
                (hx - math.cos(rear) * rear_half, hy - math.sin(rear) * rear_half, rear, rear_half, W))
    if b.kind != vehicles.SEMI:
        return ((b.x, b.y, b.h, L, W),)
    c, s = math.cos(b.h), math.sin(b.h)
    th = b.trh if b.trh is not None else b.h
    m = vehicles.SEMI_TRAILER_L / 2 - 0.3                        # trailer box: from 0.3 m ahead of the kingpin to its tail
    hx, hy = b.x + c * vehicles.SEMI_HITCH, b.y + s * vehicles.SEMI_HITCH
    return ((b.x + c * vehicles.SEMI_SHIFT, b.y + s * vehicles.SEMI_SHIFT, b.h, vehicles.SEMI_TRACTOR_L / 2, W),
            (hx - math.cos(th) * m, hy - math.sin(th) * m, th, vehicles.SEMI_TRAILER_L / 2, W))


def _line_pts(x, y, h, half, r):
    """Circle centres along a box's axis, at most 0.9 r apart (as offsets())."""
    off = max(0.0, half - r + 0.1)
    n = max(3, int(math.ceil(2 * off / (r * 0.9))) + 1)
    c, s = math.cos(h), math.sin(h)
    return [(x + c * (-off + 2 * off * i / (n - 1)), y + s * (-off + 2 * off * i / (n - 1))) for i in range(n)]


def static_pts(p):
    """Collision circle centres for walls / posts: (x, y, lever along the heading for the knock-on spin, or None)."""
    if p.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS):
        fx, fy = math.cos(p.h), math.sin(p.h)
        return [(p.x + fx * o, p.y + fy * o, o) for o in offsets(p.kind)]
    r = CIRC[p.kind][1]
    (ax, ay, ah, al, _w), (tx, ty, th, tl, _w2) = parts(p)
    fx, fy = math.cos(p.h), math.sin(p.h)
    cab = [(x, y, (x - p.x) * fx + (y - p.y) * fy) for x, y in _line_pts(ax, ay, ah, al, r)]
    return cab + [(x, y, None) for x, y in _line_pts(tx, ty, th, tl, r)]     # the trailer shoves the rig, no cab spin


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
    if isinstance(b, Apc):                            # armour plate: a БТР barely creases
        mag *= 0.2
    dx, dy = wx - b.x, wy - b.y
    c, s = math.cos(b.h), math.sin(b.h)
    lx, lz = dx * c + dy * s, -dx * s + dy * c
    b.dents.append((lx, lz, nx * c + ny * s, -nx * s + ny * c, mag))
    if len(b.dents) > 9:
        a, d = b.dents[0], b.dents[1]
        b.dents[:2] = [((a[0] + d[0]) / 2, (a[1] + d[1]) / 2, (a[2] + d[2]) / 2, (a[3] + d[3]) / 2, min(0.9, a[4] + d[4] * 0.6))]
    b.dirty = True


TURN = 0.67                  # turning radius of every vehicle relative to the bicycle model: 33 % tighter


def turn_radius_factor(speed, kind=None):
    slow = max(0.0, 1.0 - abs(speed) / 8.0)
    base = 0.9 if kind == vehicles.ARTIC_BUS else TURN * 0.75 * (1.0 - 0.25 * slow)
    return base * 0.75 * (0.9 if kind is not None and vehicles.STYLE[kind] == "bus" else 1.0)


def pivot_x(kind):
    """x of the point a vehicle turns about (m, front +): its driven rear axle as the model is really drawn (the middle of
    axles 3-4 for the БТР-80, whose front pair steers); a semi's rear tandem."""
    if kind == vehicles.SEMI:
        return vehicles.SEMI_REAR
    if kind == vehicles.ARTIC_BUS:
        return vehicles.ARTIC_MIDDLE_AXLE
    return axles(kind)[1]


def articulated_steer_limit(speed):
    return 0.90 / (1.0 + (abs(speed) / 7.5) ** 2)


TRAFFIC_PED_MODES = ("walk", "flee", "rage", "brawl", "fight", "board", "alight", "crew")


def door_point(b, out, side=1):
    """The spot `out` metres outside the driver's door of body b (where the door really is: a lorry's or a bus's is far forward)."""
    hx, dl = vehicles.door_geom(b.kind)
    W = CIRC[b.kind][1]
    lx, ly = math.sin(b.h), -math.cos(b.h)
    fx, fy = math.cos(b.h), math.sin(b.h)
    d = hx - dl * 0.5
    return b.x + lx * side * (W + out) + fx * d, b.y + ly * side * (W + out) + fy * d


def reach(b, x, y):
    """How far (x, y) is from the way into vehicle b: along the side of a car, but at the cab door for a long vehicle (a semi, a
    bus, a lorry), whose middle is nowhere near its door."""
    if vehicles.HALF_L[b.kind] > 3.5:
        dx_, dy_ = door_point(b, 0.4)
        return math.hypot(x - dx_, y - dy_) - 0.5
    L = CIRC[b.kind][0]
    fx, fy = math.cos(b.h), math.sin(b.h)
    t = max(-L, min(L, (x - b.x) * fx + (y - b.y) * fy))
    return math.hypot(x - (b.x + fx * t), y - (b.y + fy * t))


def tow(b):
    """Make the rear axle follow the joint without sideways slip, with a stop at full articulation."""
    if b.kind == vehicles.ARTIC_BUS:
        hitch, La, stop = vehicles.ARTIC_HINGE, vehicles.ARTIC_HINGE - vehicles.ARTIC_REAR_AXLE, vehicles.ARTIC_JACK
    else:
        hitch, La, stop = vehicles.SEMI_HITCH, vehicles.SEMI_AXLE, vehicles.SEMI_JACK
    c, s = math.cos(b.h), math.sin(b.h)
    hx, hy = b.x + c * hitch, b.y + s * hitch
    if b.tra is None:
        th = b.trh if b.trh is not None else b.h
        b.tra = (hx - math.cos(th) * La, hy - math.sin(th) * La)
    dx, dy = hx - b.tra[0], hy - b.tra[1]
    d = math.hypot(dx, dy)
    if d < 1e-6 or abs(d - La) > 6.0:                # spawned / teleported / put back on its lane: start straight
        th = b.h
    else:
        th = math.atan2(dy, dx)
        dh = (b.h - th + math.pi) % math.tau - math.pi
        if abs(dh) > stop:
            th = b.h - math.copysign(stop, dh)
    b.trh = th
    b.tra = (hx - math.cos(th) * La, hy - math.sin(th) * La)


STEER_TWITCH_CUT = 0.35                                                    # player-driven vehicles: steering response rate is this much slower (less twitchy)
CLUTCH_FLARE, CLUTCH_BITE, CLUTCH_SETTLE = 0.2, 0.24, 0.62               # clutch launch: revs flare (s), then the clutch bites (s); main.engine_pitch plays the same timing


def drive(p, throttle, steer_in, handbrake, dt, world):
    VMAX, ACC, STEER, GRIP, _M = vehicles.PERF[p.kind]
    VMAX = min(VMAX, vehicles.MAX_ROAD_SPEED)
    if p.player_car:                                   # the chosen hero's driving skill: top speed and pull-away
        VMAX *= HERO["top"]
        ACC *= HERO["acc"]
    VMAX = min(VMAX, vehicles.MAX_ROAD_SPEED)
    if p.exploded or (p.health <= 0 and p.ctl is not None):   # a burnt-out wreck never drives again; a burning AI car stops
        throttle, steer_in, handbrake = 0.0, 0.0, True
    BRAKE, REV = (22.0 + ACC) * 1.3, 9.0                  # brakes (and braking with reverse) stop 30 % harder
    L_ = vehicles.DIMS[p.kind][0]
    semi = p.kind == vehicles.SEMI
    artic = p.kind == vehicles.ARTIC_BUS
    wb = vehicles.SEMI_WB if semi else L_ * 0.62 if L_ < 6 else 3.7 + (L_ - 6) * 0.35   # long vehicles: wheelbase, not length; a semi: the tractor's own
    if p.kind == vehicles.BTR:
        wb = 3.74                                 # БТР-80: axles 1-2 steer, it turns about the middle of axles 3-4
    elif artic:
        wb = vehicles.ARTIC_WB
    dmg = 1.0 if p.health > 35 else 0.7           # a wrecked engine is slower
    speed_before = math.hypot(p.vx, p.vy)
    fx, fy = math.cos(p.h), math.sin(p.h)
    old_vf = p.vx * fx + p.vy * fy
    vf = old_vf
    p.signal_turn(0, dt)                               # the car you drive never blinks (only AI traffic uses indicators)
    response = HERO["drv"] if p.player_car else 1.0
    if p.player_car and p.ctl is None:
        response *= 0.8 * (1.0 - STEER_TWITCH_CUT)
    p.steer += (steer_in - p.steer) * min(1.0, (9.0 if steer_in else 14.0) * dt * response * (0.7 if p.kind == vehicles.BTR else 1.0))
    maxang = STEER / (1.0 + abs(vf) / (8.0 if L_ < 6 else 13.0))
    if artic:
        maxang = articulated_steer_limit(vf)
    p.wheel = p.steer * maxang
    om = 0.0
    if abs(vf) > 0.15:
        radius_factor = turn_radius_factor(vf, p.kind)
        om = vf / (wb * radius_factor) * math.tan(p.steer * maxang)
        if handbrake:
            om *= 1.4
        p.h += om * dt
    # the car turns about its rear axle (the front wheels steer): its middle, a little ahead of that, moves sideways into
    # the turn as it yaws -- without this it pivoted about its middle and the tail swung out as if the rear wheels steered
    rear = pivot_x(p.kind)
    vk = 0.0 if handbrake else -om * rear
    fx, fy = math.cos(p.h), math.sin(p.h)
    rx, ry = -fy, fx
    vf = p.vx * fx + p.vy * fy
    vl = p.vx * rx + p.vy * ry
    speed_reference = vf
    p.braking = False
    ct = getattr(p, "clutch_t", None)             # clutch launch (gas from under 10 km/h): little pull while the revs flare, then it builds as the clutch bites
    if throttle > 0.2:
        ct = 0.0 if ct is None and 0.0 <= vf < 10 / 3.6 else (ct + dt if ct is not None else None)
    else:
        ct = None
    p.clutch_t = ct
    cl = 1.0
    if ct is not None and ct < CLUTCH_FLARE + CLUTCH_BITE:
        u_ = max(0.0, (ct - CLUTCH_FLARE) / CLUTCH_BITE)
        cl = 1.3 * (0.15 + 0.85 * u_ * u_ * (3 - 2 * u_))         # the bite pulls 30 % harder ...
    elif ct is not None and ct < CLUTCH_FLARE + CLUTCH_BITE + CLUTCH_SETTLE:
        cl = 1.3 - 0.3 * (ct - CLUTCH_FLARE - CLUTCH_BITE) / CLUTCH_SETTLE    # ... and eases back to the normal pull as the revs rejoin the road speed
    if throttle > 0:
        top = VMAX * dmg                          # thrust tapers off and just beats drag at the rated top speed
        xr = min(1.0, max(0.0, vf / top))                    # gearing: pull fades with speed, and the last gear (above ~65 % of top) only creeps
        vf += (ACC * dmg * cl * max(0.0, 1 - xr ** 3) * (0.3 + 0.7 * (1 - xr) ** 1.5) + (vf * vf * 0.00085 + 0.25) * min(1.0, vf / top) if vf >= 0 else BRAKE) * dt * throttle
        p.braking = vf < 0
    elif throttle < 0:
        if vf > 0.8:
            vf -= BRAKE * dt
            p.braking = True
        else:
            rt = 0.6 * VMAX * dmg                  # reverse: half the forward top speed and half the forward pull
            xr = min(1.0, max(0.0, -vf / rt))
            vf -= 0.5 * ACC * dmg * max(0.0, 1 - xr ** 3) * (0.3 + 0.7 * (1 - xr) ** 1.5) * dt
    if world.hilly and not p.air:                                   # gravity along the slope: a = -g sin(angle)
        az = p.az if p.az is not None else world.ground_y(p.x, p.y)
        sl = world.slope_at(p.x, p.y, fx, fy, az, 1.4)
        vf -= world.G * sl / math.sqrt(1.0 + sl * sl) * dt
        if handbrake and throttle == 0 and abs(vf) < 1.5 and abs(world.G * sl) < 6.0:      # parking brake holds
            vf = 0.0
            vl = 0.0
    sf = world.surface(p.x, p.y)
    offr = vehicles.STYLE[p.kind] in ("suv", "pickup", "tractor", "apc", "truck")       # terrain vehicles cope with grass and dirt
    if sf == 0:
        vf *= math.exp((-0.08 if offr else -0.2) * dt)
    lift = 1.25 if throttle == 0 else 1.0                           # off the gas the car slows 25 % faster
    vf -= (vf * abs(vf) * 0.00085 * dt + (0.25 * dt if vf > 0 else -0.25 * dt if vf < 0 else 0)) * lift
    if handbrake:
        vf *= math.exp(-1.43 * dt)
        p.braking = True
    vf = min(vf, vehicles.MAX_ROAD_SPEED)
    grip = 1.8 if handbrake else (GRIP * (0.9 if offr else 0.75) if sf == 0 else GRIP)
    p.slip = abs(vl - vk)
    vl = vk + (vl - vk) * math.exp(-grip * dt)
    direction = 1.0 if speed_reference >= 0.1 else -1.0 if speed_reference <= -0.1 else (1.0 if vf >= 0.0 else -1.0)
    speed_budget = min(vehicles.MAX_ROAD_SPEED, max(0.0, speed_before + direction * (vf - speed_reference)))
    speed_now = math.hypot(vf, vl)
    if speed_now > speed_budget and speed_now > 0.0:
        scale = speed_budget / speed_now
        vf, vl = vf * scale, vl * scale
    p.vx, p.vy = fx * vf + rx * vl, fy * vf + ry * vl
    p.x += p.vx * dt
    p.y += p.vy * dt
    if semi or artic:
        tow(p)


_AXLES = {}


def axles(kind):
    """(front axle x, rear axle(s) x, track half-width) of a vehicle in its model frame (the rig centre for a semi)."""
    a = _AXLES.get(kind)
    if a is None:
        L, W = vehicles.DIMS[kind][:2]
        if kind == vehicles.ARTIC_BUS:
            return vehicles.ARTIC_FRONT_AXLE, vehicles.ARTIC_MIDDLE_AXLE, W / 2 - 0.15
        a = (L * 0.31, -L * 0.31, max(0.3, W / 2 - 0.15))
        try:
            import gl3d                                      # the wheels the model is drawn with
            semi = kind == vehicles.SEMI
            lay = gl3d._wheel_layout(vehicles.STYLE[kind], vehicles.SEMI_TRACTOR_L if semi else L, vehicles.IDS[kind])
            sh = vehicles.SEMI_SHIFT if semi else 0.0
            xr = sum(q[0] for q in lay[1:]) / max(1, len(lay) - 1)
            if lay[0][0] - xr > 0.5:
                a = (lay[0][0] + sh, xr + sh, a[2])
        except Exception:  # noqa: BLE001 - headless tools without raylib: the old +-31 % of the length
            pass
        _AXLES[kind] = a
    return a


def ride(b, s, x, y, h, dt, rate=9.0, dp=0.0, dr=0.0):
    """Pose a vehicle on the surface s(x, y): pitch / roll from its real axles and tyre tracks (smoothed at `rate`),
    and the height at which, with the tilt as drawn, no wheel and no part of the underside (between the axles, the
    bumpers) is below the surface -- on a slope change, a crest or while the tilt is still catching up.  Also poses
    a semi's trailer (b.tgz / b.tpitch / b.troll at the kingpin).  dp / dr: extra pitch / roll (kerbs).  -> height."""
    xf, xr, tw = axles(b.kind)
    c, sn = math.cos(h), math.sin(h)
    lx, ly = -sn, c                                          # +v: to the left

    def at(u, v):
        return s(x + c * u + lx * v, y + sn * u + ly * v)
    fl, fr_, rl_, rr = at(xf, tw), at(xf, -tw), at(xr, tw), at(xr, -tw)
    pt = math.atan2((fl + fr_) - (rl_ + rr), 2 * (xf - xr)) + dp
    ro = math.atan2((fr_ + rr) - (fl + rl_), 4 * tw) + dr   # > 0: right side up (the renderer's sign)
    k = min(1.0, dt * rate)
    b.pitch += (pt - b.pitch) * k
    b.roll += (ro - b.roll) * k
    sp, sr = math.sin(b.pitch), math.sin(b.roll)
    gz = max(fl - xf * sp + tw * sr, fr_ - xf * sp - tw * sr, rl_ - xr * sp + tw * sr, rr - xr * sp - tw * sr)
    L, _W, y0 = vehicles.DIMS[b.kind][:3]
    if y0 > 0.1:                                             # the underside: middle and both ends
        clr = 0.8 * y0
        semi = b.kind == vehicles.SEMI
        nose = vehicles.SEMI_SHIFT + vehicles.SEMI_TRACTOR_L / 2 if semi else L / 2
        tail = vehicles.SEMI_REAR - 0.8 if semi else vehicles.ARTIC_HINGE if b.kind == vehicles.ARTIC_BUS else -L / 2
        for u in ((xf + xr) / 2, nose, tail):
            g = at(u, 0.0) - u * sp - clr
            if g > gz:
                gz = g
    if b.kind == vehicles.SEMI:                              # the trailer hangs on the fifth wheel; its axles sit on the road
        th = b.trh if getattr(b, "trh", None) is not None else h
        hx, hy = x + c * vehicles.SEMI_HITCH, y + sn * vehicles.SEMI_HITCH
        hk = gz + vehicles.SEMI_HITCH * sp
        ct, st = math.cos(th), math.sin(th)
        tl, tv = -st, ct                             # the trailer's own left
        T_ = vehicles.SEMI_TRAILER_L
        tw_ = 1.1                                           # its tyre tracks (gl3d.trailer_arrays: tri-axle at -T+1.4 .. -T+3.8)
        con = [(u, v, s(hx + ct * u + tl * v, hy + st * u + tv * v)) for u in (-T_ + 1.4, -T_ + 3.8) for v in (tw_, -tw_)]
        tr = math.atan2((con[1][2] + con[3][2]) - (con[0][2] + con[2][2]), 4 * tw_)
        sr_ = math.sin(tr)
        q = min((hk - z - v * sr_) / -u for u, v, z in con)            # every trailer wheel on (not in) the road
        zm = s(hx - ct * T_ * 0.5, hy - st * T_ * 0.5)
        q = min(q, (hk + 0.76 - zm) / (T_ * 0.5))           # the floor (0.95 m up) clears a crest under the middle
        b.tpitch = math.asin(max(-0.5, min(0.5, q)))
        b.tgz, b.troll = hk, tr
    return gz


HELI_PADS = [   # (lat, lon, name): hospital helipads, one medical helicopter each (Sim._make_helis)
    (41.9885, 21.4240, "Клинички центар Мајка Тереза"), (41.9927, 21.4343, "Градска болница 8 Септември"),
    (42.0041, 21.4034, "Клиничка болница Жан Митрев"), (42.0140, 21.4045, "Аџибадем Систина"), (41.9902, 21.4047, "Детска болница Козле")]


def fly(p, inp, dt, w):
    """Helicopter: W/S speed, A/D turn, Space climb, Shift descend. Unpiloted ones settle onto the ground."""
    VMAX, ACC, STEER, _G, _M = vehicles.PERF[p.kind]
    VMAX = min(VMAX, vehicles.MAX_HELI_SPEED)
    ground = _heli_floor(p, w)
    if p.az is None:
        p.az, p.vz = ground, 0.0
    pilot = p.player_car and inp is not None and p.alive
    p.rpm += ((1.0 if pilot else 0.0) - p.rpm) * min(1.0, 0.7 * dt)
    p.rotor = (p.rotor + p.rpm * 38.0 * dt) % 6.2831853
    alt = p.az - ground
    lift = pilot and p.rpm > 0.85
    want = 0.0
    if lift:
        want = 14.0 * ((1 if inp.get("handbrake") else 0) - (1 if inp.get("run") else 0))
    elif alt > 0.05:
        want = -8.0                                             # autorotates down
    p.vz += (want - p.vz) * min(1.0, 2.0 * dt)
    p.az += p.vz * dt
    if p.az <= ground:
        p.az, p.vz = ground, 0.0
    alt = p.az - ground
    fx, fy = math.cos(p.h), math.sin(p.h)
    vf = p.vx * fx + p.vy * fy
    thr = inp.get("throttle", 0) if lift else 0.0
    steer = inp.get("steer", 0) if lift else 0.0
    if alt > 0.5:
        vf += (thr * VMAX - vf) * min(1.0, (ACC / VMAX) * 1.5 * dt) if thr else -vf * min(1.0, 0.6 * dt)
        p.h += steer * 1.1 * dt
        p.steer += (steer - p.steer) * min(1.0, 5 * dt)
    else:
        vf *= math.exp(-3.0 * dt)
    vf = max(-VMAX, min(VMAX, vf))
    p.vx, p.vy = math.cos(p.h) * vf, math.sin(p.h) * vf
    ox, oy = p.x, p.y
    p.x += p.vx * dt
    p.y += p.vy * dt
    hit = 0.0
    if abs(vf) > 0.01:                                          # a building taller than the skids: it stops dead
        L = vehicles.HALF_L[p.kind]
        c, s_ = math.cos(p.h), math.sin(p.h)
        if any((_bld_top(w, p.x + c * k, p.y + s_ * k) or -1e9) > p.az + 0.3 for k in (L * 0.55, 0.0, -L * 0.85)):
            p.x, p.y = ox, oy
            hit = abs(vf)
            p.vx = p.vy = 0.0
    p.pitch += (-0.22 * vf / VMAX - p.pitch) * min(1.0, 3 * dt)
    p.roll += (p.steer * 0.3 * min(1.0, abs(vf) / 20.0) - p.roll) * min(1.0, 3 * dt)
    p.air = alt > 0.5
    return hit


def _apart(a, za, b, zb):
    """A helicopter and something else at clearly different heights (flying over it): they do not touch."""
    if a.kind not in vehicles.FLY and getattr(b, "kind", -1) not in vehicles.FLY:
        return False
    return za is not None and zb is not None and abs(za - zb) > 2.2


def _heli_floor(p, w):
    """Ground, roof or raised helipad under the helicopter."""
    g = w.ground_y(p.x, p.y)
    r = _bld_top(w, p.x, p.y)
    if r is not None and p.az is not None and g < r <= p.az + 0.7:
        g = r
    if p.az is not None and getattr(w, "pg2", None):
        h = w.plat_h(p.x, p.y, p.az)
        if h is not None:
            g = max(g, h)
    return g


def _bld_top(w, x, y):
    """Absolute roof height of the building at (x, y), or None."""
    h = _bld_at(w, x, y)
    return h[1] if h is not None else None


def _bld_at(w, x, y):
    """(ring, absolute roof height) of the tallest building at (x, y), or None. A 16 m grid of footprints, built once per world."""
    g = getattr(w, "_heli_bg", None)
    if g is None:
        g = w._heli_bg = {}
        for b in getattr(w, "buildings", ()):
            x0, y0, x1, y1 = b["bb"]
            top = w.ground_y((x0 + x1) / 2, (y0 + y1) / 2) + b["h"]
            for cx in range(int(x0 // 16), int(x1 // 16) + 1):
                for cy in range(int(y0 // 16), int(y1 // 16) + 1):
                    g.setdefault((cx, cy), []).append((b["bb"], b["ring"], top))
    best = None
    for (x0, y0, x1, y1), ring, top in g.get((int(x // 16), int(y // 16)), ()):
        if x0 <= x <= x1 and y0 <= y <= y1 and (best is None or top > best[1]) and w._in_ring(x, y, ring):
            best = (ring, top)
    return best


def _mesh_top(w, x, y, r, cap):
    """Highest vertex of the built world meshes within r of (x, y) (photogrammetric roofs have relief, parapets, ridges),
    ignoring anything above `cap` (masts, antennas). None when the world has no chunk meshes."""
    S = getattr(w, "chunk", None)
    chs = getattr(w, "chunks", None)
    if not S or not chs:
        return None
    best = None
    for cx in range(int((x - r) // S) - 1, int((x + r) // S) + 2):
        for cy in range(int((y - r) // S) - 1, int((y + r) // S) + 2):
            ch = chs.get((cx, cy))
            for _mat, (off, n) in (ch["m"].items() if ch else ()):
                if not n:
                    continue
                pos = w.mesh_arrays(off, n)[0]
                m = ((pos[:, 0] - x) ** 2 + (pos[:, 2] - y) ** 2 < r * r) & (pos[:, 1] < cap)
                if m.any():
                    t = float(pos[m, 1].max())
                    best = t if best is None or t > best else best
    return best


def _pg2_add(w, pl, x0, y0, x1, y1):
    if not hasattr(w, "pg2") or w.pg2 is None:
        w.pg2 = {}
    for cx in range(int(x0 // 8), int(x1 // 8) + 1):
        for cy in range(int(y0 // 8), int(y1 // 8) + 1):
            w.pg2.setdefault((cx, cy), []).append(pl)


def _roof_stairs(w, ring, top):
    """A zigzag steel stair up the outside of one wall, on the side facing away from the street (the player has to look for it).
    Adds walkable ramps + the roof to w.pg2 (feet and bikes use it, see world.plat_h); returns the flights for the renderer."""
    m = len(ring)
    inside = lambda px, py: w._in_ring(px, py, ring)
    best = None
    Lmin = 6.0 if any(math.hypot(ring[(i + 1) % m][0] - ring[i][0], ring[(i + 1) % m][1] - ring[i][1]) >= 6.0 for i in range(m)) else 2.0   # (a tiny footprint: the stair runs past the wall's ends)
    for i in range(m):
        (ax, ay), (bx, by) = ring[i], ring[(i + 1) % m]
        L = math.hypot(bx - ax, by - ay)
        if L < Lmin:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        nx, ny = uy, -ux
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if inside(mx + nx * 1.5, my + ny * 1.5):
            nx, ny = -nx, -ny
        r = w.nearest_drive_point(mx + nx * 3, my + ny * 3, 120)
        d = math.hypot(r[0] - mx, r[1] - my) if r else 999.0
        if best is None or d > best[0]:
            best = (d, ax, ay, ux, uy, nx, ny, L)
    if best is None:
        return []
    _d, ax, ay, ux, uy, nx, ny, L = best
    Lf = min(L - 2.0, 9.0) if L >= 6.0 else 6.0
    s0 = (L - Lf) / 2
    off = 1.3                                                   # stair centre line out from the wall
    g0 = w.ground_y(ax + ux * (s0 + Lf / 2) + nx * off, ay + uy * (s0 + Lf / 2) + ny * off)
    rise = top - g0
    if rise < 1.0:
        return []
    n = max(1, math.ceil(rise / (Lf * 0.75)))
    dh = rise / n
    flights = []
    for k in range(n):
        fwd = k % 2 == 0
        cx = ax + ux * (s0 + Lf / 2) + nx * off
        cy = ay + uy * (s0 + Lf / 2) + ny * off
        sx, sy = (ux, uy) if fwd else (-ux, -uy)
        h0, h1 = g0 + k * dh, g0 + (k + 1) * dh
        pl = (0, cx, cy, sx, sy, Lf / 2, 0.65, h0, h1)
        rr = math.hypot(Lf / 2, 0.65)
        _pg2_add(w, pl, cx - rr, cy - rr, cx + rr, cy + rr)
        flights.append(pl)
        ex, ey = cx + sx * (Lf / 2 + 0.6), cy + sy * (Lf / 2 + 0.6)  # landing at the top end of the flight
        land = (0, ex, ey, sx, sy, 0.6, 0.65, h1, h1)
        _pg2_add(w, land, ex - 1, ey - 1, ex + 1, ey + 1)
        flights.append(land)
    # the last landing reaches over to the roof edge
    ex, ey = flights[-1][1] - nx * 0.9, flights[-1][2] - ny * 0.9
    br = (0, ex, ey, nx, ny, 1.0, 0.65, top, top)
    _pg2_add(w, br, ex - 1.2, ey - 1.2, ex + 1.2, ey + 1.2)
    flights.append(br)
    xs, ys = [q[0] for q in ring], [q[1] for q in ring]
    _pg2_add(w, (1, ring, top, (min(xs), min(ys), max(xs), max(ys))), min(xs), min(ys), max(xs), max(ys))
    return flights


def settle(b, w, dt, ev=None):
    """Put a car on the surface under it (terrain or bridge deck); drops it when that surface ends.  Sets pitch/roll."""
    if b.az is not None and (b.x - b.lx) ** 2 + (b.y - b.ly) ** 2 > 400.0:      # teleported
        b.az, b.vz = None, 0.0
    plat = b.kind in vehicles.BIKES and w.pg2                # bikes and scooters may ride fire escapes, roofs and jump ramps
    ground = w.ground_y(b.x, b.y) if plat or b.az is None else None
    if b.az is None:
        b.az = ground
    if plat and b.az - ground > 0.5 and w.plat_wall(b.x, b.y, b.az):      # a taller roof is a wall
        b.x, b.y = b.lx, b.ly
        b.vx *= -0.2
        b.vy *= -0.2
        ground = None
    b.lx, b.ly = b.x, b.y
    tgt = w.level(b.x, b.y, b.az, plat) if ground is None else w.level(b.x, b.y, b.az, plat, ground=ground)
    if plat and not b.air and b.vz <= 0.0 and b.az > tgt + getattr(b, "lift", 0.0) + getattr(b, "rlift", 0.0) + 0.12:   # left a ramp lip: keep its upward speed
        b.vz = max(0.0, min(7.0, getattr(b, "vzg", 0.0)))
    if b.air or b.az > tgt + getattr(b, "lift", 0.0) + getattr(b, "rlift", 0.0) + 0.12 or b.vz > 0.0:   # off the edge of a deck: falling
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
    if plat:
        b.vzg = (tgt - b.az) / max(dt, 1e-3) if b.az < 1e8 else 0.0
    b.az = tgt
    b.vz = 0.0
    wb = vehicles.DIMS[b.kind][0] * 0.31
    fx, fy = math.cos(b.h), math.sin(b.h)
    rx, ry = -fy, fx
    pt = rl_ = 0.0
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
    gz = ride(b, lambda x_, y_: w.level(x_, y_, tgt, plat), b.x, b.y, b.h, dt, 9.0, pt, rl_)
    b.rlift = max(0.0, gz - tgt)                             # up on its wheels over a slope change / crest (not a fall)
    b.az = max(tgt, gz) + b.lift


def collide_static(p, world):
    """Walls, trees, lamp posts. Returns [(kind, impact, wx, wy, nx, ny)]."""
    events = []
    fx, fy = math.cos(p.h), math.sin(p.h)
    off, R = CIRC[p.kind]
    az = p.az if p.az is not None else 0.0
    high = p.az is not None and p.az - world.ground_y(p.x, p.y) > 4.0          # on a deck high above the buildings
    top = az + 1.5
    for _ in range(2):
        x0, y0 = p.x, p.y
        for cx, cy, o in static_pts(p):
            cx, cy = cx + p.x - x0, cy + p.y - y0                 # earlier circles may have pushed the car already
            o = o or 0.0
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
                stage = world.tree_hit((tx, ty, tr, lo, hi), -vn, nx, ny) if tree and vn < 0 and hasattr(world, "tree_hit") else None   # 1st hit strips the leaves, a later hard one fells the tree
                if stage == "shed":
                    events.append(("tree_shed", -vn, tx, ty, nx, ny))
                if (stage == "fall" if tree and hasattr(world, "tree_hit") else -vn > (9.0 if tree else 1.2 if light else 2.5)) and hasattr(world, "break_point"):   # everything breaks, the car pays
                    if tree:
                        world.break_point((tx, ty, tr, lo, hi), (-nx, -ny))
                    else:
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
    if kind == vehicles.SEMI:                                    # the trailer's tail corner, folded to the jackknife stop
        j = vehicles.SEMI_JACK
        tx = vehicles.SEMI_HITCH - math.cos(j) * vehicles.SEMI_TRAILER_L + math.sin(j) * W
        ty = math.sin(j) * vehicles.SEMI_TRAILER_L + math.cos(j) * W
        return max(math.hypot(L, W), math.hypot(tx, ty)) + 0.05
    if kind == vehicles.ARTIC_BUS:
        return abs(vehicles.ARTIC_HINGE) + math.hypot(L + vehicles.ARTIC_HINGE, W) + 0.05
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
        row = g.setdefault(int(b.x // _CELL), {})
        row.setdefault(int(b.y // _CELL), []).append(b)
    return g


def _near(g, x, y, rings=1):
    """Objects in the surrounding grid cells."""
    cx, cy = int(x // _CELL), int(y // _CELL)
    res = []
    columns = range(cy - rings, cy + rings + 1)
    for i in range(cx - rings, cx + rings + 1):
        row = g.get(i)
        if row is not None:
            for j in columns:
                cell = row.get(j)
                if cell:
                    res.extend(cell)
    return res


def body_pairs(bodies):
    """Broadphase: every pair of cars whose bounding circles overlap, found with a 20 m grid (bounding radii <= ~11 m)."""
    grid = {}
    for i, b in enumerate(bodies):
        grid.setdefault((int(b.x // 20), int(b.y // 20)), []).append(i)
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
    """A circle (px, py, r) against the oriented box(es) of car b: (nx, ny, penetration) pushing the circle out, or None."""
    best = None
    for bx, by, bh, L, W in parts(b):
        hit = _push_box(bx, by, bh, L, W, px, py, r)
        if hit is not None and (best is None or hit[2] > best[2]):
            best = hit
    return best


def _push_box(bx, by, bh, L, W, px, py, r):
    c, s_ = math.cos(bh), math.sin(bh)
    dx, dy = px - bx, py - by
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
        self.x, self.y, self.h, self.kind, self.trh = b.x + b.vx * dt, b.y + b.vy * dt, b.h, b.kind, b.trh


def _corners(x, y, h, L, W):
    fx, fy = math.cos(h), math.sin(h)
    return [(x + fx * u - fy * v, y + fy * u + fx * v) for u, v in ((L, W), (L, -W), (-L, -W), (-L, W))]


def _sat(pa, ha, pb, hb):
    """Separating axis test of two boxes (corner lists, headings): (penetration, axis) or None."""
    best_pen, n_ = 1e9, None
    for h in (ha, ha + math.pi / 2, hb, hb + math.pi / 2):
        ax_, ay_ = math.cos(h), math.sin(h)
        A = [x * ax_ + y * ay_ for x, y in pa]
        B = [x * ax_ + y * ay_ for x, y in pb]
        pen = min(max(A), max(B)) - max(min(A), min(B))
        if pen <= 0:
            return None
        if pen < best_pen:
            best_pen, n_ = pen, (ax_, ay_)
    return best_pen, n_


def collide_bodies(a, b, ma=1.0, mb=1.0):
    """Oriented-box car/car collision (separating axis test) with a rigid-body impulse at the contact corner:
    a hit on the rear quarter spins the car, a head-on stops it. Returns (impact, wx, wy, nx, ny) or None,
    n pointing from a to b."""
    r_ = _RAD[a.kind] + _RAD[b.kind]
    if (a.x - b.x) ** 2 + (a.y - b.y) ** 2 > r_ * r_:        # bounding circles apart: cannot touch at any angle
        return None
    hit = None                                    # semis have two boxes (tractor, trailer): the deepest overlapping pair counts
    for qa in parts(a):
        pa = _corners(*qa)
        for qb in parts(b):
            pb = _corners(*qb)
            r_ = _sat(pa, qa[2], pb, qb[2])
            if r_ is not None and (hit is None or r_[0] > hit[0]):
                hit = (r_[0], r_[1], pa, pb, qa, qb)
    if hit is None:
        return None
    best_pen, (nx, ny), pa, pb, qa, qb = hit
    if (qb[0] - qa[0]) * nx + (qb[1] - qa[1]) * ny < 0:
        nx, ny = -nx, -ny
    # contact: the corner of one box that sits deepest inside the other
    da = max(pa, key=lambda c: (c[0] - qa[0]) * nx + (c[1] - qa[1]) * ny)
    db = min(pb, key=lambda c: (c[0] - qb[0]) * nx + (c[1] - qb[1]) * ny)
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
    _n = 0

    def __init__(self):
        Ped._n += 1
        self.pid = Ped._n            # identity for the voice colour (each pedestrian speaks a little differently)
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
        self.work_role = None        # role-specific combat behavior for service, garbage and road-work crews
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
        self.vault = 0.0             # seconds left in a committed vault
        self.vault_t = 1.0
        self.vault_up = True
        self.vault_path = None
        self.walk_route = []
        self.traffic_target = None
        self.traffic_wait = 0.0
        self.traffic_stall = 0.0
        self.traffic_waypoint = None
        self.traffic_run = False

    @property
    def dead(self):
        return self.mode in ("dead", "air")


# multipliers of the chosen hero (set by characters.set_hero from hero_profiles stats); 1.0 = average
HERO = {"spd": 1.0, "str": 1.0, "end": 1.0, "drv": 1.0, "top": 1.0, "acc": 1.0}


class Walker:
    """The player on foot."""

    def __init__(self, x, y, h):
        self.x, self.y, self.h = x, y, h
        self.vx = self.vy = 0.0
        self.anim = 0.0
        self.health = 100.0
        self.moving = False
        self.esc_on = False          # climbing a fire escape (escride.py): legs and arms play the walk cycle
        self.run = False
        self.stair = False           # on a stair flight: runs (faster, running cycle)
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
        self.indoor = None           # inside the GTC mall (mall.Mall): its walls and floor replace the city's

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
        sp = (9.5 if run else 5.75) * HERO["spd"]
        self.h += turn * (math.radians(300.0) if not run else 3.0) * dt
        k = min(1.0, 12 * dt)
        if world.hilly and self.z <= 0.001 and not (world.pg2 and self.az - world.ground_y(self.x, self.y) > 0.3):   # Tobler's (not on stairs / roofs) hiking function: slow uphill, a little faster gently downhill
            gr = world.slope_at(self.x, self.y, math.cos(self.h) * (1 if fwd >= 0 else -1), math.sin(self.h) * (1 if fwd >= 0 else -1), self.az, 1.0)
            self.grade = gr
            sp *= max(0.15, min(1.25, math.exp(-3.5 * (abs(gr + 0.05) - 0.05))))
        self.stair = bool(world.pg2) and self.z <= 0.001 and world.on_ramp(self.x, self.y, self.az)
        if self.stair:
            sp = max(sp, 8.0 * HERO["spd"])                      # stairs are taken at a run, up and down
        tx, ty = math.cos(self.h) * fwd * (sp if fwd > 0 else sp * 0.6), math.sin(self.h) * fwd * (sp if fwd > 0 else sp * 0.6)
        self.vx += (tx - self.vx) * k
        self.vy += (ty - self.vy) * k
        self.moving = abs(fwd) > 0.01 or self.esc_on             # (a fire-escape climb is driven by escride, not by input)
        if self.moving:
            self.anim += self.speed * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.indoor is not None:                              # in the mall: its own walls and one level floor
            self.indoor.collide(self)
            sup = self.indoor.floor
        else:
            if world.pg2 and self.az - world.ground_y(self.x, self.y) > 0.5 and world.plat_wall(self.x, self.y, self.az):    # a taller roof is a wall
                self.x, self.y = self.lx, self.ly
                self.vx = self.vy = 0.0
            if world.pg2 and self.z <= 0.05 and self.vz <= 0.0 and self.az - world.ground_y(self.x, self.y) > 1.0 and world.plat_h(self.lx, self.ly, self.az) is not None:   # roof-edge barrier: only a jump gets over it
                if self.az - world.level(self.x, self.y, self.az, True) > 1.0:
                    if self.az - world.level(self.x, self.ly, self.az, True) <= 1.0:
                        self.y = self.ly
                    elif self.az - world.level(self.lx, self.y, self.az, True) <= 1.0:
                        self.x = self.lx
                    else:
                        self.x, self.y = self.lx, self.ly
                    self.vx = self.vy = 0.0
            self.push_out(world)
            # ---- vertical: stand on the terrain / deck under the feet, fall when it ends
            sup = world.level(self.x, self.y, self.az, True)
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
    arch = getattr(p, "arch", -1)
    nm = vehicles.PED_IDS[arch] if 0 <= arch < len(vehicles.PED_IDS) else ""
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
        self.hall = None             # f(x, y) -> True inside the GTC mall (mall.Mall.in_hall), set by main

    def _place(self, p):
        e = self.w.edges[p.e]
        s = p.s if p.d == 1 else e["len"] - p.s
        x, y, dx, dy = self.w.edge_point(e, s)
        if p.d == -1:
            dx, dy = -dx, -dy
        side = p.side
        sides = e.get("sidewalk_sides")
        if sides is not None and sides[0] != sides[1]:
            side = p.d if sides[1] else -p.d
        off = (half_width(e, s) + 1.0) * side if e["drive"] else 0.5 * side
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
        if hasattr(w, "pedestrian_ground") and not e["bridge"] and not w.pedestrian_ground(p.x, p.y):
            return
        if (p.x - px) ** 2 + (p.y - py) ** 2 < rmin * rmin * 0.7:
            return
        self.list.append(p)

    def adopt(self, p, keep_heading=False):
        """Make p (a bus passenger, ...) an ordinary passer-by on the nearest footway / pavement from where it stands."""
        w = self.w
        best, checked = None, set()
        hx, hy = math.cos(p.h), math.sin(p.h)
        cx, cy = int(p.x // w.sg), int(p.y // w.sg)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for ei in w.walk_cells.get((ix, iy), ()):
                    if ei in checked:
                        continue
                    checked.add(ei)
                    e = w.edges[ei]
                    pts, cum = e["pts"], e["cum"]
                    for k in range(len(pts) - 1):
                        (ax, ay), (bx, by) = pts[k], pts[k + 1]
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy or 1.0
                        t = max(0.0, min(1.0, ((p.x - ax) * dx + (p.y - ay) * dy) / l2))
                        d2 = (p.x - ax - dx * t) ** 2 + (p.y - ay - dy * t) ** 2
                        if best is None or d2 < best[0]:
                            best = (d2, ei, cum[k] + t * (cum[k + 1] - cum[k]), -dy * (p.x - ax) + dx * (p.y - ay), dx * hx + dy * hy)
        if best is None:
            return False
        _d, ei, s, lat, dot = best
        e = w.edges[ei]
        p.e = ei
        p.d = (1 if dot >= 0 else -1) if keep_heading else self.rng.choice((1, -1))
        p.s = s if p.d == 1 else e["len"] - s
        p.side = (1 if lat > 0 else -1) * p.d
        p.mode, p.t = "walk", 0.0
        p.v = self.rng.uniform(1.0, 1.7) * vehicles.PED_SPEED[p.arch]
        return True

    def eject(self, x, y, h, shirt=None, gz=None, flee=None):
        """A driver pulled out of their car: angry, then runs away; flee=(vx, vy) (a shot-at driver) runs for their life at once."""
        p = Ped()
        p.mode = "rage"
        p.t = 3.2
        p.x, p.y, p.h = x, y, h
        if flee is not None:
            p.mode, p.t, p.vx, p.vy = "flee", 8.0, flee[0], flee[1]
        p.gz = gz
        p.arch = self.rng.choice(vehicles.WALKERS)
        p.shirt = self.rng.randrange(3) if shirt is None else shirt
        p.skin = self.rng.randrange(4)
        self.list.append(p)
        return p

    def _start_brawl(self, fx, fy, ev):
        """Two passers-by get into it with each other (more often in an aggressive city)."""
        rng = self.rng
        cand = [p for p in self.list if p.mode == "walk" and 12 < abs(p.x - fx) + abs(p.y - fy) < 150
                and self.w.kerb(p.x, p.y)]
        if len(cand) < 2:
            return
        a = rng.choice(cand)
        b = min((q for q in cand if q is not a), key=lambda q: (q.x - a.x) ** 2 + (q.y - a.y) ** 2)
        if (b.x - a.x) ** 2 + (b.y - a.y) ** 2 > 14 ** 2 or self.w.surface((a.x + b.x) * 0.5, (a.y + b.y) * 0.5) == 3:
            return
        for x, y in ((a, b), (b, a)):
            x.mode, x.t, x.foe, x.atk_cd = "brawl", rng.uniform(7, 14), y, rng.uniform(0.2, 0.9)
        ev("shout", text=talk.react("fight", a.arch, self.sim, lines("fight", a.arch), rng), x=a.x, y=a.y,
           who=vehicles.ped_who(a))

    _SOLID = ("walk", "flee", "rage", "brawl", "fight", "play", "crew")

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
        ev("shout", text=text, x=p.x, y=p.y, who=vehicles.ped_who(p))
        if stage == 3:
            if kid:                                               # children shout, then run to mama
                p.mode, p.t = "flee", 4.0
                p.vx, p.vy = -dx / d * 3.4, -dy / d * 3.4
            else:
                p.mode, p.t, p.atk_cd, p.far_t = "fight", 14.0, 0.4, 0.0
                p.bumps = 0

    def _traffic_danger(self, p, nearby):
        best = None
        forecasts = getattr(self, "traffic_forecasts", {})
        for b in nearby:
            if isinstance(b, Car):
                speed = -2.2 if b.rev > 0 else b.v
                vx, vy = speed * math.cos(b.h), speed * math.sin(b.h)
                z = b.gz
            else:
                if b.exploded:
                    continue
                vx, vy, z = b.vx, b.vy, b.az
            if z is not None and p.gz is not None and abs(z - p.gz) > 2.2:
                continue
            for t, footprint in forecasts.get(b, ()):
                if best is not None and best[0] <= t:
                    break
                for x, y, heading, length, width in footprint:
                    hx, hy = math.cos(heading), math.sin(heading)
                    dx, dy = p.x + p.vx * t - x, p.y + p.vy * t - y
                    side = dy * hx - dx * hy
                    half = width + _PED_R(p) + 0.35
                    if abs(dx * hx + dy * hy) < length + 0.6 and abs(side) < half:
                        exposed = abs((p.y - y) * hx - (p.x - x) * hy) < half
                        best = (t, -hy, hx, side, exposed, None)
                        break
            speed = math.hypot(vx, vy)
            slow = speed < 1.4
            hx, hy = (math.cos(b.h), math.sin(b.h)) if slow else (vx / speed, vy / speed)
            dx, dy = p.x - b.x, p.y - b.y
            fwd, side = dx * hx + dy * hy, -dx * hy + dy * hx
            hl, hw = vehicles.HALF_L[b.kind], vehicles.HALF_W[b.kind]
            half = hw + _PED_R(p) + 0.3
            if slow:
                driven = isinstance(b, Car) or b.ctl is not None or b.player_car
                if driven and (best is None or best[0] > 1.3):
                    road = self.w.surface(p.x, p.y) in (2, 3) and not self.w.kerb(p.x, p.y)
                    for x, y, heading, length, width in parts(b):
                        hx, hy = math.cos(heading), math.sin(heading)
                        dx, dy = p.x - x, p.y - y
                        forward, lateral = dx * hx + dy * hy, -dx * hy + dy * hx
                        if (-length - 0.45 < forward < length + (3.0 if road else 0.55)
                                and abs(lateral) < width + _PED_R(p) + 0.3):
                            best = (1.3, -hy, hx, lateral, True, b)
                            break
                continue
            if fwd < -hl - 0.6 or fwd > hl + 2.5 * speed:
                continue
            t = corridor_entry(fwd, side, p.vx * hx + p.vy * hy - speed, -p.vx * hy + p.vy * hx,
                               hl + 0.6, half, 2.5)
            if t is not None and (best is None or t < best[0]):
                best = (t, -hy, hx, side, abs(side) <= half, None)
        return best

    def _escape_clear(self, p, nearby, tx, ty, speed, over=None, origin=None):
        px, py = (p.x, p.y) if origin is None else origin
        dx, dy = tx - px, ty - py
        duration = math.hypot(dx, dy) / speed
        for b in nearby:
            if b is over:
                continue
            if isinstance(b, Car):
                v = -2.2 if b.rev > 0 else b.v
                vx, vy, z = v * math.cos(b.h), v * math.sin(b.h), b.gz
            else:
                vx, vy, z = b.vx, b.vy, b.az
            if z is not None and p.gz is not None and abs(z - p.gz) > 2.2:
                continue
            for t, footprint in getattr(self, "traffic_forecasts", {}).get(b, ()):
                progress = min(1.0, t / max(0.01, duration))
                for x, y, h, hl, hw in footprint:
                    ux, uy = px + dx * progress - x, py + dy * progress - y
                    if abs(ux * math.cos(h) + uy * math.sin(h)) < hl + 0.3 and abs(uy * math.cos(h) - ux * math.sin(h)) < hw + 0.3:
                        return False
            for x, y, h, hl, hw in parts(b):
                c, s = math.cos(h), math.sin(h)
                x, y = px - x, py - y
                u, v = dx - vx * duration, dy - vy * duration
                # Intersect the proposed motion with the moving footprint in the car's frame.
                along, side = x * c + y * s, -x * s + y * c
                end_along, end_side = u * c + v * s, -u * s + v * c
                length, width = hl + 0.23, hw + 0.23
                hit = corridor_entry(along, side, end_along, end_side, length, width, 1.0)
                if hit is not None:
                    # A foot already inside the padded corner may move out through its nearest face.
                    along_gap, side_gap = length - abs(along), width - abs(side)
                    outward = end_along * (1 if along >= 0 else -1) if along_gap < side_gap else end_side * (1 if side >= 0 else -1)
                    gap = min(along_gap, side_gap)
                    if hit > 0.0 or outward <= gap:
                        return False
        return not crosses_wall(self.w, px, py, tx, ty)

    @staticmethod
    def _clear_of_waiting_vehicle(b, x, y, radius):
        for bx, by, h, length, width in parts(b):
            hx, hy = math.cos(h), math.sin(h)
            dx, dy = x - bx, y - by
            if (-length - 0.75 < dx * hx + dy * hy < length + 3.2
                    and abs(-dx * hy + dy * hx) < width + radius + 0.5):
                return False
        return True

    def _around_vehicle(self, p, blocker, nearby, exits, speed):
        """Try a clear corner around a vehicle when the direct escape lines are blocked."""
        corners = []
        for b in nearby:
            if math.hypot(b.x - p.x, b.y - p.y) > 9.0:
                continue
            for x, y, h, length, width in parts(b):
                corners.extend(_corners(x, y, h, length + 0.65, width + 0.65))
        for wx, wy in sorted(corners, key=lambda xy: math.hypot(xy[0] - p.x, xy[1] - p.y)):
            if self.w.surface(wx, wy) == 1 or not self._escape_clear(p, nearby, wx, wy, speed):
                continue
            if self._clear_of_waiting_vehicle(blocker, wx, wy, _PED_R(p)):
                return (wx, wy), None
            for tx, ty in exits:
                if self._escape_clear(p, nearby, tx, ty, speed, origin=(wx, wy)):
                    return (tx, ty), (wx, wy)
        return None, None

    def _vault_escape(self, p, blocked, nearby):
        if blocked is None or not hasattr(self.w, "edges_near"):
            return False
        b = blocked
        speed = b.v if isinstance(b, Car) else b.speed
        roof = vehicles.DIMS[b.kind][4]
        if speed > 0.8 or roof > 1.75 or (isinstance(b, Car) and b.rev > 0):
            return False
        hx, hy = math.cos(b.h), math.sin(b.h)
        dx, dy = p.x - b.x, p.y - b.y
        fwd, side = dx * hx + dy * hy, -dx * hy + dy * hx
        hw, hl = vehicles.HALF_W[b.kind], vehicles.HALF_L[b.kind]
        if abs(fwd) > hl or abs(side) > hw + 1.0:
            return False
        landing = -math.copysign(hw + 1.0, side)
        tx, ty = b.x + hx * fwd - hy * landing, b.y + hy * fwd + hx * landing
        if (abs(self.w.level(tx, ty, p.gz if p.gz is not None else -1e9)
                       - self.w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)) > 0.55
                or not self._escape_clear(p, nearby, tx, ty, 2.8, over=b)):
            return False
        p.traffic_target = None
        p.traffic_waypoint = None
        p.vault_path = p.x, p.y, tx, ty, roof + 0.35
        p.vault, p.vault_t, p.vault_up = 0.95, 0.95, True
        return True

    def _advance_vault(self, p, dt):
        x, y, tx, ty, height = p.vault_path
        p.vault = max(0.0, p.vault - dt)
        u = 1.0 - p.vault / p.vault_t
        travel = u if p.vault_t < 0.5 else 0.5 - 0.5 * math.cos(math.pi * u)
        nx, ny = x + (tx - x) * travel, y + (ty - y) * travel
        p.vx, p.vy = (nx - p.x) / dt, (ny - p.y) / dt
        p.x, p.y, p.h = nx, ny, math.atan2(ty - y, tx - x)
        p.hy = height * math.sin(math.pi * u)
        p.anim += 4.0 * dt
        if p.vault == 0.0:
            p.vault_path, p.hy = None, 0.0
            p.walk_route.clear()
            p.traffic_wait = 0.65
            self.adopt(p, keep_heading=True)
            run = getattr(p, "vault_run", None)
            p.vault_run = None
            if run is not None:                                   # landed: keep sprinting the same way for a few metres, no standing around
                p.traffic_target, p.traffic_waypoint = run, None
                p.traffic_run, p.traffic_wait = True, 0.0

    def _avoid_traffic(self, p, nearby, dt, blocked=None):
        danger = self._traffic_danger(p, nearby)
        waiting = danger[5] if danger is not None else None
        if waiting is None and blocked is not None and self.w.surface(p.x, p.y) in (2, 3) and not self.w.kerb(p.x, p.y):
            waiting = blocked
        p.traffic_stall = p.traffic_stall + dt if waiting is not None else 0.0
        if p.mode not in ("walk", "flee") and waiting is None and p.traffic_target is None:
            return False
        if danger is not None or blocked is not None:
            time = danger[0] if danger is not None else 1.0
            p.traffic_run = time < 1.5
        speed = 4.0 if p.traffic_run else 2.0
        aim = p.traffic_waypoint or p.traffic_target
        if aim is not None and not self._escape_clear(p, nearby, *aim, speed):
            p.traffic_target = p.traffic_waypoint = None
        if danger is not None or blocked is not None:
            _, nx, ny, side, exposed = danger[:5] if danger is not None else (1.0, 0.0, 0.0, 1.0, True)
            p.traffic_wait = max(p.traffic_wait, 0.8)
            if (exposed or waiting is not None) and p.traffic_target is None:
                sign = 1.0 if side >= 0.0 else -1.0
                nx, ny = nx * sign, ny * sign
                if blocked is not None and danger is None:
                    hit = push_from_box(blocked, p.x, p.y, 1.5)
                    if hit is not None:
                        nx, ny = hit[:2]
                fallback, exits = None, []
                for distance in (1.2, 2.3, 3.5, 5.0, 6.5):
                    for off in (0.0, -0.65, 0.65, -1.3, 1.3, math.pi):
                        dx = nx * math.cos(off) - ny * math.sin(off)
                        dy = ny * math.cos(off) + nx * math.sin(off)
                        tx, ty = p.x + distance * dx, p.y + distance * dy
                        if self.w.surface(tx, ty) == 1 or (waiting is not None
                                and not self._clear_of_waiting_vehicle(waiting, tx, ty, _PED_R(p))):
                            continue
                        exits.append((tx, ty))
                        if not self._escape_clear(p, nearby, tx, ty, speed):
                            continue
                        if self.w.kerb(tx, ty) or self.w.surface(tx, ty) == 0:
                            p.traffic_target = tx, ty
                            break
                        if (time < 1.0 or blocked is not None or waiting is not None) and fallback is None:
                            fallback = tx, ty
                    if p.traffic_target is not None:
                        break
                if p.traffic_target is None:
                    if (fallback is None or time < 0.9) and self._vault_escape(p, blocked or waiting, nearby):
                        self._advance_vault(p, dt)
                        return True
                    p.traffic_target = fallback
                    if (fallback is None and waiting is not None
                            and int(p.traffic_stall * 4) > int((p.traffic_stall - dt) * 4)):
                        p.traffic_target, p.traffic_waypoint = self._around_vehicle(p, waiting, nearby, exits, speed)
        if p.traffic_target is not None:
            tx, ty = p.traffic_waypoint or p.traffic_target
            dx, dy = tx - p.x, ty - p.y
            distance = math.hypot(dx, dy)
            if distance > 0.14:
                zebra = getattr(self.w, "on_zebra", None)
                if (zebra is not None and danger is not None and danger[0] < 0.85 and danger[4]
                        and not zebra(p.x, p.y) and distance > 0.75):
                    leap = min(3.0, max(distance, 2.2))                  # a real dive forward in the escape direction, then on running
                    ux, uy = dx / distance, dy / distance
                    lx, ly = p.x + ux * leap, p.y + uy * leap
                    if self.w.surface(lx, ly) == 1 or not self._escape_clear(p, nearby, lx, ly, 5.0):
                        leap = min(2.2, distance)
                        lx, ly = p.x + ux * leap, p.y + uy * leap
                    if self._escape_clear(p, nearby, lx, ly, 5.0):
                        p.vault_path = p.x, p.y, lx, ly, 0.75
                        p.vault, p.vault_t, p.vault_up = 0.5, 0.5, True
                        rx, ry = lx + ux * 3.5, ly + uy * 3.5
                        p.vault_run = (rx, ry) if self.w.surface(rx, ry) != 1 and self._escape_clear(p, nearby, rx, ry, 4.0, origin=(lx, ly)) else None
                        p.walk_route.clear()
                        self._advance_vault(p, dt)
                        return True
                speed = min(speed, distance / dt)
                p.vx, p.vy = dx / distance * speed, dy / distance * speed
                p.x, p.y = p.x + p.vx * dt, p.y + p.vy * dt
                p.h = math.atan2(dy, dx)
                p.anim += speed * dt
                return True
            if p.traffic_waypoint is not None:
                p.traffic_waypoint = None
                return True
            p.traffic_target = None
            p.walk_route.clear()
            self.adopt(p, keep_heading=True)
        if p.traffic_wait > 0.0:
            p.traffic_wait = max(0.0, p.traffic_wait - dt)
            p.vx = p.vy = 0.0
            return True
        return False

    def _walk_corner(self, p, opts):
        """Keep the closest sidewalk through a junction whenever the graph offers one."""
        if not opts:
            p.d, p.side = -p.d, -p.side
            return
        candidates = []
        for ei, direction in opts:
            e = self.w.edges[ei]
            along = min(e["len"], p.s + 1.5)
            along = along if direction == 1 else e["len"] - along
            tx, ty, dx, dy = self.w.edge_point(e, along)
            for side in (-1, 1):
                sides = e.get("sidewalk_sides")
                if e["drive"] and sides and any(sides) and not sides[int(side * direction > 0)]:
                    continue
                offset = (half_width(e, along) + 1.0) * side * direction if e["drive"] else 0.5 * side * direction
                x, y = tx - dy * offset, ty + dx * offset
                road_steps = sum(self.w.surface(p.x + (x - p.x) * f, p.y + (y - p.y) * f) == 3 for f in (0.25, 0.5, 0.75))
                score = math.hypot(x - p.x, y - p.y) + 2.6 * road_steps + self.rng.uniform(0.0, 0.8)
                candidates.append((score, ei, direction, side, x, y))
        route_aware = hasattr(self.w, "pedestrian_ground") and not self.w.edges[p.e]["bridge"]
        for _, ei, direction, side, x, y in sorted(candidates):
            if route_aware and not self.w.edges[ei]["bridge"]:
                route = walk_path(self.w, (p.x, p.y), (x, y))
                if route is None:
                    continue
                p.walk_route = route
                p.s = min(self.w.edges[ei]["len"], p.s + 1.5)
            p.e, p.d, p.side = ei, direction, side
            return
        p.d, p.side = -p.d, -p.side

    def _follow_walk_route(self, p, dt):
        x, y = p.walk_route[0]
        dx, dy = x - p.x, y - p.y
        distance = math.hypot(dx, dy)
        move = min(distance, p.v * 1.45 * dt)
        if distance > 1e-4:
            tx, ty = p.x + dx * move / distance, p.y + dy * move / distance
            crossings = getattr(self.w, "crossings", None)
            if crossings is not None and crossings.wait_for_signal(
                    p.x, p.y, tx, ty, getattr(getattr(self, "sim", None), "lights", None)):
                p.vx = p.vy = 0.0
                return
            p.vx, p.vy = dx * move / (distance * dt), dy * move / (distance * dt)
            p.x, p.y = tx, ty
            p.h = math.atan2(dy, dx)
            p.anim += move
        else:
            p.vx = p.vy = 0.0
        if distance <= move + 1e-4:
            p.walk_route.pop(0)

    def _recover_walk_route(self, p, e):
        """Reconnect to a reachable point rather than flipping direction at the same spot."""
        original = p.s, p.d, p.side
        for distance in (2.5, -2.5, 5.0, -5.0):
            along = max(0.0, min(e["len"], original[0] + distance))
            p.s, p.d, p.side = (along, original[1], original[2]) if distance > 0 else (
                e["len"] - along, -original[1], -original[2])
            tx, ty, _ = self._place(p)
            if math.hypot(tx - p.x, ty - p.y) < 0.6 or not self.w.pedestrian_ground(tx, ty):
                continue
            route = walk_path(self.w, (p.x, p.y), (tx, ty))
            if route:
                p.walk_route, p.walk_blocked = route, 0.0
                return True
        p.s, p.d, p.side = original
        return False

    def update(self, dt, fx, fy, bodies, ev):
        w, rng = self.w, self.rng
        out = []
        aggro = getattr(self.sim, "aggro", 1) if self.sim else 1
        tc = self.sim.traffic.cars if self.sim is not None else ()
        self.traffic_forecasts = Traffic.turn_forecasts((*bodies, *tc))
        g_b, g_a = _cells(bodies), _cells((*bodies, *tc))          # 10 m grids: each person only checks the cars next to them
        dt0 = dt
        self._tick = getattr(self, "_tick", 0) + 1
        begin_frame()                                             # route searches share a few ms per frame
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
                if b.az is not None and p.gz is not None and abs(b.az - p.gz) > 2.2:
                    continue
                sp = b.speed
                if sp > 2.2 and not b.exploded and p.hy < vehicles.DIMS[b.kind][4] and push_from_box(b, p.x, p.y, 0.34):
                    hit = b
                    break
            if hit is not None:
                p.vault, p.vault_path = 0.0, None
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
            if p.mode in ("queue", "board", "play", "guard", "crew"):       # moved by Transit / Kids / Compounds / Crews (they can still be hit)
                out.append(p)
                continue
            if p.vault_path is not None:
                self._advance_vault(p, dt)
                p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
                out.append(p)
                continue
            blocked = None
            if p.mode in ("walk", "flee", "rage", "brawl", "fight", "alight"):
                for b in _near(g_a, p.x, p.y):
                    if abs(b.x - p.x) > 7 or abs(b.y - p.y) > 7:
                        continue
                    z = b.gz if isinstance(b, Car) else b.az
                    if z is not None and p.gz is not None and abs(z - p.gz) > 2.2:
                        continue
                    hit_ = push_from_box(b, p.x, p.y, 0.3)
                    speed = b.v if isinstance(b, Car) else b.speed
                    if hit_ is not None:
                        p.x += hit_[0] * hit_[2]
                        p.y += hit_[1] * hit_[2]
                        blocked = b
                        if p.mode == "walk" and speed < 0.3 and p.bump_cd <= 0 and (p.x - fx) ** 2 + (p.y - fy) ** 2 < 40 ** 2:
                            p.bump_cd = 7.0                                   # squeezed past a parked car: a grumble (the first-stage line)
                            lang_ = getattr(self.sim, "lang", 1) if self.sim else 1
                            text_ = bible_lines.bump(vehicles.PED_IDS[p.arch], 0, lang_, rng) or bump_lines.line(vehicles.PED_IDS[p.arch], 0, rng)
                            if talk.allowed(text_, lang_):
                                ev("shout", text=text_, x=p.x, y=p.y, who=vehicles.ped_who(p))
                    elif blocked is None and p.mode in ("walk", "flee") and speed < 1.4:
                        if push_from_box(b, p.x + math.cos(p.h) * 0.85, p.y + math.sin(p.h) * 0.85, 0.4):
                            blocked = b
            if p.mode in ("walk", "flee", "rage", "brawl", "fight", "alight") and self._avoid_traffic(
                    p, _near(g_a, p.x, p.y, rings=2), dt, blocked):
                # An ambient pedestrian sealed in by traffic and walls must eventually release the lane.
                if p.traffic_stall >= (6.0 if p.traffic_target is not None or p.vault_path is not None else 3.0):
                    continue
                p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
                if self._d2(p.x, p.y, fx, fy) < 300 ** 2:
                    out.append(p)
                continue
            p.traffic_run = False
            if p.mode == "alight":                             # resume the transit controller when the lane is clear
                out.append(p)
                continue
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
                            ev("shout", text=talk.react("ko", o.arch, self.sim, lines("ko", o.arch), rng), x=o.x, y=o.y, who=vehicles.ped_who(o))
                        elif rng.random() < 0.25:
                            text = rng.choice(peds_lines.work(p.work_role, "fight")) if p.work_role else talk.react("fight", p.arch, self.sim, lines("fight", p.arch), rng)
                            ev("shout", text=text, x=p.x, y=p.y, who=vehicles.ped_who(p))
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
                               x=p.x, y=p.y, who=vehicles.ped_who(p))
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
                        p.atk_kind = 4 if p.work_role or rng.random() < 0.65 else 5
                        if wk.z < 0.5 and wk.inv_t <= 0:
                            dmg = vehicles.FIGHT[p.arch][2] * rng.uniform(0.8, 1.3) * HERO["end"]
                            wk.health -= dmg
                            wk.hurt_t = 0.35
                            if wk.health <= 0:
                                wk.cause = "fight"
                            ev("hurt", ped=p, dmg=dmg)
                            if rng.random() < 0.3:
                                ev("shout", text=talk.react("fight", p.arch, self.sim, lines("fight", p.arch), rng), x=p.x, y=p.y, who=vehicles.ped_who(p))
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
                        if not self.adopt(p):
                            continue
                        p.vx = p.vy = 0.0
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
            if p.walk_route:
                self._follow_walk_route(p, dt)
                p.gz = w.level(p.x, p.y, p.gz if p.gz is not None else -1e9)
                if self._d2(p.x, p.y, fx, fy) < 300 ** 2:
                    out.append(p)
                continue
            vv = p.v * 1.25                                      # +25% walking pace
            if w.hilly:                                           # Tobler's hiking function
                p.gr_t = getattr(p, "gr_t", (id(p) >> 4) % 33 * 0.01) - dt
                if p.gr_t <= 0.0 or not hasattr(p, "gr_k"):       # the slope under a walker changes slowly: look it up 3 times a second
                    p.gr_t = 0.33
                    gr = w.slope_at(p.x, p.y, math.cos(p.h), math.sin(p.h), p.gz if p.gz is not None else -1e9, 1.0)
                    p.gr_k = max(0.2, min(1.25, math.exp(-3.5 * (abs(gr + 0.05) - 0.05))))
                vv *= p.gr_k
            p.s += vv * dt
            if p.s >= e["len"]:
                p.s -= e["len"]
                node = e["b"] if p.d == 1 else e["a"]
                opts = [o for o in w.walk_out.get(node, ()) if o[0] != p.e] or list(w.walk_out.get(node, ()))
                if over_budget():
                    p.s = e["len"]                                # route budget spent this frame: wait at the corner
                else:
                    self._walk_corner(p, opts)
                e = w.edges[p.e]
                if p.walk_route:
                    out.append(p)
                    continue
            tx, ty, th = self._place(p)
            ex, ey = tx - p.x, ty - p.y                          # walk to the path point at walking pace: no sliding
            dd = math.hypot(ex, ey)
            mx = (vv * 1.5 + 0.6) * dt
            if dd > mx:
                ex, ey = ex / dd * mx, ey / dd * mx
            if (not e["bridge"] and getattr(w, "crossings", None) is not None
                    and w.crossings.wait_for_signal(p.x, p.y, p.x + ex, p.y + ey,
                                                    getattr(getattr(self, "sim", None), "lights", None))):
                p.s = max(0.0, p.s - vv * dt)
                p.vx = p.vy = 0.0
                out.append(p)
                continue
            if (hasattr(w, "pedestrian_ground") and not e["bridge"]
                    and (not w.pedestrian_ground(p.x + ex, p.y + ey)
                         or crosses_wall(w, p.x, p.y, p.x + ex, p.y + ey))):
                blocked = getattr(p, "walk_blocked", 0.0)
                p.s = max(0.0, p.s - vv * dt)
                if (blocked == 0.0 or int(blocked) != int(blocked + dt)) and not over_budget():
                    self._recover_walk_route(p, e)
                if not p.walk_route:
                    p.walk_blocked = blocked + dt
                    if p.walk_blocked >= 2.0:
                        continue
                p.vx = p.vy = 0.0
                out.append(p)
                continue
            p.x += ex
            p.y += ey
            p.walk_blocked = 0.0
            p.anim += math.hypot(ex, ey)
            p.vx, p.vy = ex / dt, ey / dt
            if dd > 0.6:                                         # face where it is actually going
                th = math.atan2(ey, ex)
            p.h += ((th - p.h + math.pi) % (2 * math.pi) - math.pi) * min(1.0, dt * 8)
            p.gz = w.level(p.x, p.y, 1e9 if e["bridge"] else -1e9)      # on the deck of a bridge edge, else on the ground
            p.say_t -= dt
            if p.say_t <= 0:
                p.say_t = rng.uniform(10, 28) / max(0.05, getattr(self.sim, "speech_freq", 1.0))
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 22 ** 2:
                    ev("shout", text=talk.say(p, self.sim, rng) if self.sim else rng.choice(lines("idle", p.arch)), x=p.x, y=p.y, who=vehicles.ped_who(p))
            if self._d2(p.x, p.y, fx, fy) < 300 ** 2:
                out.append(p)
        if self.hall is not None:                  # people who wander into the GTC hall leave: they would ignore its walls
            out = [p for p in out if p.mode == "svc" or not self.hall(p.x, p.y)]
        self.list = out
        dt = dt0
        self._separate(dt, fx, fy)
        for _ in range(2):
            if len([q for q in self.list if q.mode == "walk"]) < self.target:
                self.spawn(*self._focus(fx, fy))


# ===================================================================== traffic
def _seg_dist(p, q, r, t):
    """Smallest distance between segments pq and rt."""
    def cross(ax, ay, bx, by):
        return ax * by - ay * bx
    d1, d2 = (q[0] - p[0], q[1] - p[1]), (t[0] - r[0], t[1] - r[1])
    den = cross(d1[0], d1[1], d2[0], d2[1])
    if abs(den) > 1e-9:
        u = cross(r[0] - p[0], r[1] - p[1], d2[0], d2[1]) / den
        v = cross(r[0] - p[0], r[1] - p[1], d1[0], d1[1]) / den
        if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0:
            return 0.0
    def pt(a, b, c_):
        dx, dy = c_[0] - b[0], c_[1] - b[1]
        l2 = dx * dx + dy * dy or 1.0
        k = max(0.0, min(1.0, ((a[0] - b[0]) * dx + (a[1] - b[1]) * dy) / l2))
        return math.hypot(a[0] - b[0] - dx * k, a[1] - b[1] - dy * k)
    return min(pt(p, r, t), pt(q, r, t), pt(r, p, q), pt(t, p, q))


class Car:
    __slots__ = ("e", "d", "s", "v", "lane", "kind", "color", "pace", "x", "y", "h", "stuck", "ghost", "braking", "gz", "pitch", "roll", "cab", "lidx", "shift", "shift_t", "rev", "cool", "nxt", "avoid", "yld", "str", "turn", "arr", "blk", "rside", "man", "stn", "dwell", "stn_t", "trh", "tra", "lcd", "nx2", "goff", "tgz", "tpitch", "troll", "uid", "goal", "rerouted", "turnaround", "indicator", "indicator_t", "health", "honk_t", "rev_box", "creep")
    def __init__(self):
        self.cab = random.random() < 0.25       # one in four has its radio on (heard muffled from outside)
        self.stuck = 0.0
        self.creep = -1            # edge on which this car, standing at the line, may edge into the junction with a tighter exit gap
        self.ghost = 0.0
        self.braking = False
        self.indicator, self.indicator_t = 0, 0.0
        self.gz = 0.0
        self.goff = 0.0            # ride height above the surface under its centre (slope changes, crests: see ride())
        self.tgz = self.tpitch = self.troll = None     # a semi's trailer pose at the kingpin
        self.pitch = 0.0
        self.roll = 0.0
        self.lidx = 0              # which lane (of the ones in its direction) it drives in
        self.nx2 = None            # the choice after a short link c.nxt: ((edge, dir), turn)
        self.goal, self.rerouted = None, 0.0
        self.health, self.honk_t = 100.0, 0.0
        self.turnaround = None     # start pose, signed radius, angle swept during a midblock U-turn
        self.lcd = 0.0             # seconds until it may change lane again for its coming turn
        self.shift = 0.0           # extra sideways offset while it works its way out of a jam
        self.shift_t = 0.0
        self.rev = 0.0             # seconds of reversing left
        self.rev_box = False
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
        self.tra = None            # semi: the trailer's axle group (x, y), see tow()
        self.uid = None            # its number in the traffic worker process (trafficproc.py)


RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1}   # as tools/roads3d


def _rank(cls):
    return RANK.get(cls.replace("_link", ""), 0)


class Traffic:
    extra = ()                                     # multiplayer: other players this PC simulates the world for (x, y)

    @staticmethod
    def turn_forecasts(vehicles_nearby):
        """Publish short swept turns once per frame for nearby pedestrians to share."""
        forecasts = {}
        for b in vehicles_nearby:
            ambient = isinstance(b, Car)
            speed = (-2.2 if b.rev > 0 else b.v) if ambient else b.vx * math.cos(b.h) + b.vy * math.sin(b.h)
            angle = b.str if ambient else b.wheel
            arc = b.turnaround if ambient else None
            if arc is None and (abs(speed) < 1.0 or abs(angle) < 0.16):
                continue
            length = vehicles.DIMS[b.kind][0]
            wb = vehicles.ARTIC_WB if b.kind == vehicles.ARTIC_BUS else (
                vehicles.SEMI_WB if b.kind == vehicles.SEMI else length * 0.6)
            if not ambient and b.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS):
                wb = length * 0.62 if length < 6.0 else 3.7 + (length - 6.0) * 0.35
            yaw = speed * math.tan(angle) / (wb * turn_radius_factor(speed, b.kind))
            probe = SimpleNamespace(x=b.x, y=b.y, h=b.h, kind=b.kind, trh=b.trh, tra=b.tra)
            poses = []
            for i in range(1, 5):
                t = i * 0.35
                if arc is not None:
                    probe.x, probe.y, probe.h = Traffic._arc_pose(arc, min(math.pi, arc[-1] + 2.2 * t / abs(arc[3])))
                else:
                    mid = probe.h + yaw * 0.175
                    probe.x += math.cos(mid) * speed * 0.35
                    probe.y += math.sin(mid) * speed * 0.35
                    probe.h += yaw * 0.35
                if b.kind in (vehicles.ARTIC_BUS, vehicles.SEMI):
                    tow(probe)
                poses.append((t, parts(probe)))
            forecasts[b] = poses
        return forecasts

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
        self.occ = {}                # (edge, dir, lane) -> rear bumper of the nearest slow car
        self.queue = {}              # (edge, dir) -> standing cars on it (route choice avoids queues)
        self.queue_history = {}      # recent stopped traffic by directed edge
        self.route_demand = {}       # planned arrivals, used to spread detours
        self.exit_claims = {}        # car -> reserved exit lanes until it clears the junction
        self.audit_stops = None      # populated only by the traffic audit
        self._blocked_exits = set()
        self.passing = {}            # narrow edge -> (driver going first, driver pulling over, s, offset)
        self.narrow_arrivals = {}
        self.narrow_wait = set()
        self.appr = {}               # junction node -> [(priority key, car, heading, eta)] of cars close to it
        self.lead = None
        self.despawned = 0
        self._tick = 0
        self.stn = None              # stations.Stations, set by Sim: cars pull into petrol stations and car washes
        arms, half_widths = {}, {}
        for e in world.edges:
            if e["drive"]:
                for node in {e["a"], e["b"]}:
                    arms[node] = arms.get(node, 0) + 1
                    half_widths[node] = max(half_widths.get(node, 0.0), e["w"] / 2)
        self.junctions = {node: half_widths[node] for node, count in arms.items() if count >= 3}
        self._clear_cache = {}
        self._node_edges = {}
        for ei_, e_ in enumerate(world.edges):
            if not e_["drive"]:
                continue
            self._node_edges.setdefault(e_["a"], []).append(ei_)
            self._node_edges.setdefault(e_["b"], []).append(ei_)
        signal_nodes = {signal[0] for signal in getattr(world, "signals", ()) if signal[0] in self.junctions}
        components = {node: node for node in signal_nodes}

        def root(node):
            while components[node] != node:
                node = components[node]
            return node

        for e in world.edges:
            a, b = e["a"], e["b"]
            if (e["drive"] and a in signal_nodes and b in signal_nodes
                    and e["len"] < min(25.0, self.junctions[a] + self.junctions[b] + 5.0)):
                ra, rb = root(a), root(b)
                components[max(ra, rb)] = min(ra, rb)
        groups = {}
        for node in signal_nodes:
            groups.setdefault(root(node), []).append(node)
        self.junction_complex = {node: group for group, nodes in groups.items() if len(nodes) > 1 for node in nodes}
        self.internal_links = {}
        for i, e in enumerate(world.edges):
            group = self.junction_complex.get(e["a"])
            if e["drive"] and group is not None and group == self.junction_complex.get(e["b"]) and e["len"] < 30.0:
                self.internal_links[i] = group
        self.single_file = {i: width for i, e in enumerate(world.edges)
                            if e["drive"] and (width := self._single_file_width(e)) < 5.0}

    @staticmethod
    def lanes_of(e, direction=1):
        """Nominal lateral lane centres, in order from the driver's left to right."""
        n = lane_count(e, direction)
        lo, hi = lane_bounds(e, direction)
        if n == 1 and not e["ow"] and not e.get("directional_lanes"):
            return [max(1.3, hi / 2)]
        return [lo + (k + 0.5) * (hi - lo) / n for k in range(n)]

    def _set_lane(self, c, e):
        ls = self.lanes_of(e, c.d)
        c.lidx = min(c.lidx, len(ls) - 1)
        c.lane = ls[c.lidx]

    def _ref(self, e, d, s, off):
        """Point at distance s along the edge and lateral offset in its nominal cross-section, plus heading."""
        along = s if d == 1 else e["len"] - s
        x, y, dx, dy = self.w.edge_point(e, along)
        if e.get("taper"):
            off *= 2 * half_width(e, along) / e["w"]
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
        """Choose the edge a car takes after its current one (so its path can be followed round the corner), and when that
        edge is only a short link, the one after it too (c.nx2), so the lane for the turn can be taken before the link."""
        r = self._choose(c, c.e, c.d)
        c.nx2 = None
        if r is None:
            c.nxt = None
            return
        good, turns, k = r
        c.nxt, c.turn = good[k], turns[k]
        if self.stn is not None:
            self.stn.steer(c, good, turns)
        if c.stn is None and c.kind not in vehicles.HEAVY and (c.goal is not None or len(good) > 1):
            streets = [o for o in good if self.w.edges[o[0]]["cls"] != "service"]
            if self._plan_trip(c, streets or good):
                return
        c.goal = None
        plan, cur, dist, t = [], c.nxt, self.w.edges[c.nxt[0]]["len"], c.turn
        while dist < self.PLAN_M and abs(t) < self.TURN_LANE and len(plan) < 4:      # straight on over short links: plan up to the next real turn
            r2 = self._choose(c, cur[0], cur[1])
            if r2 is None:
                break
            cur, t = r2[0][r2[2]], r2[1][r2[2]]
            plan.append((cur, t))
            dist += self.w.edges[cur[0]]["len"]
        c.nx2 = plan or None

    def _plan_trip(self, c, first):
        w = self.w
        e = w.edges[c.e]
        start = e["b" if c.d == 1 else "a"]
        x, y = e["pts"][-1 if c.d == 1 else 0]
        goal = c.goal
        if goal is None or goal[0] == start:
            for _ in range(5):
                h = self.rng.uniform(0.0, math.tau)
                r = self.rng.uniform(155.0, 300.0)
                choices = w.drive_cells.get((int((x + math.cos(h) * r) // w.sg), int((y + math.sin(h) * r) // w.sg)))
                if choices:
                    dest = w.edges[self.rng.choice(choices)]
                    goal = (dest["b"], dest["pts"][-1])
                    break
        if goal is None or goal[0] == start:
            return False
        def delay(move):
            ei, d = move
            road = w.edges[ei]
            return (4.0 * self._queue_pressure(move) + 1.6 * self.route_demand.get(move, 0) / lane_count(road, d)
                    + (4.0 if self.signals is not None and (ei, int(d == 1)) in self.signals.by_edge else 0.0)
                    + (12.0 if road["cls"] == "service" else 0.0))

        incoming = (c.e, c.d)
        def route_delay(move):
            ei, d = move
            road = w.edges[ei]
            node = road["b"] if d == 1 else road["a"]
            return delay(move) + (45.0 if node in self.clogged else 0.0)

        path = fastest_route(w, start, *goal, incoming=incoming, first=first, delay=route_delay,
                             speed_cap=min(27.0, vehicles.PERF[c.kind][0] * 0.9), budget=230, main_only=True)
        if not path:
            return False
        plan = [(o, turn_angle(w.edges, i, o)) for i, o in zip((incoming,) + path, path)]
        group, rotation = None, 0.0
        for i, (move, angle) in zip((incoming,) + path, plan):
            edge = w.edges[i[0]]
            junction = self.junction_complex.get(edge["b" if i[1] == 1 else "a"])
            rotation = rotation + angle if junction is not None and junction == group else angle
            group = junction
            if group is not None and abs(rotation) > self.UTURN:
                return False                        # don't route a trip back around a large junction
        c.nxt, c.turn = plan[0]
        c.nx2, c.goal = plan[1:] or None, goal
        return True

    PLAN_M = 130.0                   # m of path ahead whose turns are planned together (lane choice has to start before short links)

    def _major_junction(self, node):
        return node in self.junction_complex or self.junctions.get(node, 0.0) >= 5.0

    def _choose(self, c, ei, d):
        """Pick the edge after edge ei driven in direction d: the bigger road and straight on are likelier, a queue ahead
        puts it off (more so in the rush hours, when drivers cut through side streets), and the connected network wins over
        a closed-off pocket.  Returns (options, turns, index chosen) or None."""
        w = self.w
        e = w.edges[ei]
        node = e["b"] if d == 1 else e["a"]
        opts = w.out.get(node, [])
        major = self._major_junction(node)
        allowed = [(o, turn_angle(w.edges, (ei, d), o)) for o in opts]
        if major:
            allowed = [(o, angle) for o, angle in allowed if abs(angle) <= self.UTURN]
            claim = self.exit_claims.get(c)
            if claim is not None and ei in self.internal_links and self.internal_links[ei] == self.junction_complex.get(claim[1]):
                entry, direction = claim[0]
                heading = self._head(w.edges[entry], direction, True)
                allowed = [(o, angle) for o, angle in allowed
                           if abs(math.remainder(self._head(w.edges[o[0]], o[1], False) - heading, math.tau)) <= self.UTURN]
        good = [o for o, angle in allowed if o[0] != ei and movement_lanes(w, (ei, d), o, angle) != []]
        if not good and not major:
            good = [o for o in opts if o[0] == ei]
        if not good:
            return None
        onward = [o for o in good if any(k[0] != o[0] for k in w.out.get(w.edges[o[0]]["b" if o[1] == 1 else "a"], ()))]
        good = onward or good
        main = [o for o in good if w.edges[o[0]]["a"] in w.main and w.edges[o[0]]["b"] in w.main]
        good = main or good
        h0 = self._head(e, d, True)
        hr = getattr(getattr(self.sim, "clock", None), "hour", 12.0) if self.sim else 12.0
        qk = 1.2 if (7.0 <= hr < 9.5 or 16.0 <= hr < 18.5) else 0.5
        turns, wts = [], []
        inside_complex = ei in self.internal_links
        for o in good:
            e2 = w.edges[o[0]]
            t = (self._head(e2, o[1], False) - h0 + math.pi) % (2 * math.pi) - math.pi
            turns.append(t)
            congested = self.clogged and (e2["a"] in self.clogged or e2["b"] in self.clogged)
            wts.append(0.12 if congested else (1.0 + _rank(e2["cls"])) * (1.6 if abs(t) < 0.35 else 1.0)
                       / (1.0 + 1.6 * qk * self._queue_pressure(o)))
            if inside_complex and o[0] in self.internal_links:
                wts[-1] *= 0.2
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
                return None                                           # nothing fit for it: _next_edge turns it round
        late = (ei, d) == (c.e, c.d) and e["len"] - c.s < 22.0
        legal = []
        for i, t in enumerate(turns):
            lanes = movement_lanes(w, (ei, d), good[i], t)
            if lanes is None or (c.lidx in lanes if late else bool(lanes)):
                legal.append(i)
        if legal:
            good, turns, wts = [good[i] for i in legal], [turns[i] for i in legal], [wts[i] for i in legal]
        if self.clogged:
            open_moves = [i for i, o in enumerate(good) if not ({w.edges[o[0]]["a"], w.edges[o[0]]["b"]} & self.clogged)]
            if open_moves:
                good, turns, wts = [good[i] for i in open_moves], [turns[i] for i in open_moves], [wts[i] for i in open_moves]
        if inside_complex and (ei, d) == (c.e, c.d) and c.nxt is None:
            through = [i for i, angle in enumerate(turns) if abs(angle) < 0.35]
            if through:
                good, turns, wts = [good[i] for i in through], [turns[i] for i in through], [wts[i] for i in through]
        regular = [w.edges[edge]["cls"] != "service" or w.edges[edge]["w"] >= 5.5 for edge, _ in good]
        if any(regular):
            # Ambient traffic stays on the street network. Stations can still choose an access road from good.
            wts = [weight if street else 0.0 for weight, street in zip(wts, regular)]
        k = self.rng.choices(range(len(good)), wts)[0]
        return good, turns, k

    TURN_LANE = 0.5                  # heading change (rad) from which a turn wants the kerb lane (right) or the centre lane (left)

    def _lane_for_turn(self, c, e, rem, dt):
        """Well before a junction a car that will turn right moves over to the kerb-side lane and one that will turn left to
        the lane beside the centre line (index 0 is the leftmost, as in the painted arrows), one lane at a time and only
        into a gap, so a right turn is never cut across the lanes of the cars going straight on."""
        c.lcd -= dt
        ls = self.lanes_of(e, c.d)
        k = min(c.lidx, len(ls) - 1)
        if c.lane != ls[k]:                                       # slide over to the chosen lane rather than jump
            delta = ls[k] - c.lane
            step = min(abs(delta), max(0.35, min(self.LANE_V, abs(delta) * 0.8)) * dt)
            c.lane += math.copysign(step, delta)
            return
        if c.lcd > 0 or len(ls) < 2:
            return
        if c.e in self.internal_links or (c.s < self.LANE_HOLD and e["a" if c.d == 1 else "b"] in self.junctions):
            return                                                # a lane is kept right through a junction (no weaving inside the box)
        t = c.turn
        if abs(t) < self.TURN_LANE and c.nx2 is not None:
            distance = self.w.edges[c.nxt[0]]["len"]
            for move, angle in c.nx2:
                if distance > self.PLAN_M:
                    break
                if abs(angle) >= self.TURN_LANE or (angle > 0.20 and self.w.edges[move[0]]["cls"].endswith("_link")):
                    t = max(angle, self.TURN_LANE) if angle > 0.0 else angle
                    break
                distance += self.w.edges[move[0]]["len"]
        want = len(ls) - 1 if t >= self.TURN_LANE else 0 if t <= -self.TURN_LANE else k
        if abs(c.turn) < self.TURN_LANE:
            want = min(want, lane_count(self.w.edges[c.nxt[0]], c.nxt[1]) - 1)
        permitted = movement_lanes(self.w, (c.e, c.d), c.nxt, c.turn)
        if permitted:
            if abs(c.turn) >= self.TURN_LANE and k in permitted:
                want = k                       # parallel marked turns keep their own lanes
            else:
                want = min(permitted, key=lambda i: (abs(i - want), abs(i - k)))
        if k == want or (rem < 20.0 and (permitted is None or k in permitted)):
            return
        k2 = k + (1 if want > k else -1)
        if self._lane_room(c, e, ls[k2], 12.0, behind=7.0 + c.v):
            c.lidx = k2
        c.lcd = 1.0

    LANE_V = 1.3                     # m/s sideways while changing lane
    LANE_HOLD = 14.0                 # m after a junction in which no new lane change starts
    CLAIM_LEAD = 1.4                 # s of extra look-ahead for asking for the junction: the car with priority is let in before it has to brake

    def _mapped_lane(self, previous, lane, move, angle, following=0.0):
        ei, direction = move
        road = self.w.edges[ei]
        n = lane_count(road, direction)
        if angle >= self.TURN_LANE or (angle > 0.20 and road["cls"].endswith("_link")):
            lane += n - lane_count(self.w.edges[previous[0]], previous[1])
        if abs(angle) > self.UTURN:
            lane = 0
        lane = max(0, min(n - 1, lane))
        if ei in self.internal_links:
            permitted = turn_lanes(road, direction, following)
            if permitted:
                lane = min(permitted, key=lambda idx: abs(idx - lane))
            elif permitted is None and abs(following) >= self.TURN_LANE:
                lane = 0 if following < 0.0 else n - 1
        return lane

    def _exit_lane(self, c, e, e2):
        following = c.nx2[0][1] if c.nx2 else 0.0
        return self._mapped_lane((c.e, c.d), c.lidx, c.nxt, c.turn, following)

    def _target(self, c, e, la):
        """Pure-pursuit aim point `la` metres ahead on the car's lane, continuing onto the next edge round a corner."""
        s2 = c.s + la
        if s2 <= e["len"] or c.nxt is None:
            return self._ref(e, c.d, min(s2, e["len"]), c.lane + c.shift + c.avoid + c.yld)
        remaining = s2 - e["len"]
        prev = (c.e, c.d)
        moves = [(c.nxt, c.turn)] + list(c.nx2 or ())
        lane_idx = c.lidx
        for i, (move, angle) in enumerate(moves):
            ei, direction = move
            road = self.w.edges[ei]
            following = moves[i + 1][1] if i + 1 < len(moves) else 0.0
            lane_idx = self._mapped_lane(prev, lane_idx, move, angle, following)
            lane = self.lanes_of(road, direction)[lane_idx]
            if remaining <= road["len"]:
                return self._ref(road, direction, min(remaining, road["len"]), lane)
            remaining -= road["len"]
            prev = move
        return self._ref(road, direction, road["len"], lane)

    def _corner_target(self, c, e, look):
        """Aim ahead of the car's projection on the exit lane, even after it cuts the corner."""
        ei, direction = c.nxt
        road = self.w.edges[ei]
        lane = self.lanes_of(road, direction)[self._exit_lane(c, e, road)]
        x, y, h = self._ref(road, direction, 0.0, lane)
        progress = (c.x - x) * math.cos(h) + (c.y - y) * math.sin(h)
        aim = min(road["len"], max(look + 2.0, progress + look))
        return self._ref(road, direction, aim, lane)

    def spawn(self, px, py, rmin=170, rmax=380):
        w, rng = self.w, self.rng
        a, r = rng.uniform(0, 6.283), rng.uniform(rmin, rmax)
        cell = (int((px + math.cos(a) * r) // w.sg), int((py + math.sin(a) * r) // w.sg))
        lst = w.drive_cells.get(cell)
        if not lst:
            return
        ei = rng.choice(lst)
        e = w.edges[ei]
        if ei in self.internal_links:
            return
        if self.clogged and (e["a"] in self.clogged or e["b"] in self.clogged):
            return                                            # never feed a jammed junction
        c = Car()
        c.e = ei
        c.d = 1 if (e["ow"] or rng.random() < .5) else -1
        c.s = rng.uniform(0, e["len"])
        c.lidx = rng.randrange(lane_count(e, c.d))
        self._set_lane(c, e)
        c.kind = rng.choices(range(vehicles.N), vehicles.TRAFFIC_W)[0]
        if _rank(e["cls"]) >= 2 and e["w"] >= 7 and rng.random() < 0.12:
            c.kind = rng.choices(vehicles.HEAVY, vehicles.HEAVY_W)[0]       # lorries drive only the big roads (tertiary and up)
        if e["w"] >= 5.5 and e["cls"] in ("residential", "living_street", "unclassified", "tertiary", "secondary") and rng.random() < 0.03:
            c.kind = garbage.truck_kind()                                   # garbage trucks go round the streets that have containers
        if vehicles.LARGE[c.kind] and e["w"] < (7 if c.kind in vehicles.HEAVY else 5.5 if c.kind == garbage.truck_kind() else 8):
            c.kind = 1
        c.color = rng.randrange(vehicles.N_COLORS)
        c.pace = rng.uniform(0.85, TRAFFIC_SPEED_FACTOR) * vehicles.SPEED[c.kind]
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
        best, checked = None, set()
        hx, hy = math.cos(c.h), math.sin(c.h)
        cx, cy = int(c.x // w.sg), int(c.y // w.sg)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for ei in w.drive_cells.get((ix, iy), ()):
                    if ei in checked:
                        continue
                    checked.add(ei)
                    e = w.edges[ei]
                    pts, cum = e["pts"], e["cum"]
                    for k in range(len(pts) - 1):
                        (ax, ay), (bx, by) = pts[k], pts[k + 1]
                        dx, dy = bx - ax, by - ay
                        l2 = dx * dx + dy * dy or 1.0
                        t = max(0.0, min(1.0, ((c.x - ax) * dx + (c.y - ay) * dy) / l2))
                        d2 = (c.x - ax - dx * t) ** 2 + (c.y - ay - dy * t) ** 2
                        dot = (dx * hx + dy * hy) / math.sqrt(l2)
                        alignment = dot if e["ow"] else abs(dot)
                        score = d2 + 16.0 * (1.0 - alignment)
                        if d2 <= 14.0 ** 2 and (best is None or score < best[0]):
                            best = score, ei, cum[k] + t * (cum[k + 1] - cum[k]), dot
        if best is None:
            return False
        _d, ei, s_, dot = best
        e = w.edges[ei]
        c.e = ei
        c.d = 1 if (e["ow"] or dot >= 0) else -1
        c.s = s_ if c.d == 1 else e["len"] - s_
        x, y, dx, dy = w.edge_point(e, s_)
        off = c.d * (-dy * (c.x - x) + dx * (c.y - y))
        if e.get("taper"):
            off *= e["w"] / (2 * half_width(e, s_))
        lanes = self.lanes_of(e, c.d)
        c.lidx = min(range(len(lanes)), key=lambda i: abs(lanes[i] - off))
        lane = lanes[c.lidx]
        c.lane = max(lane - 1.5, min(lane + 1.5, off))
        c.pace = self.rng.uniform(0.85, TRAFFIC_SPEED_FACTOR) * vehicles.SPEED[c.kind]
        c.nxt = c.blk = c.arr = c.stn = c.dwell = None
        c.nx2, c.goal, c.rerouted = None, None, 0.0
        c.turnaround = None
        c.rev_box = False
        c.stuck = c.shift = c.shift_t = c.avoid = c.yld = 0.0
        c.x, c.y, c.h = self._place(c)
        return True

    def _next_edge(self, c):
        w = self.w
        e = w.edges[c.e]
        node = e["b"] if c.d == 1 else e["a"]
        opts = w.out.get(node, [])
        if not opts:
            return False
        if (c.nxt not in opts or movement_lanes(w, (c.e, c.d), c.nxt, c.turn) == []
                or (abs(c.turn) > self.UTURN and self._major_junction(node))):
            self._pick(c)
            if c.nxt is None:
                return False
        plan = c.nx2
        c.lidx = self._exit_lane(c, e, w.edges[c.nxt[0]])
        if c.indicator:
            c.indicator_t = 1.4
        c.e, c.d = c.nxt
        if abs(c.turn) > 2.6:
            c.man = 5.0                                           # a U-turn: full lock, as a driver would in a narrow street
        c.nxt, c.turn, c.arr = None, 0.0, None
        c.nx2 = None
        c.rerouted = 0.0
        if plan and plan[0][0] in w.out.get(self.w.edges[c.e]["b"] if c.d == 1 else self.w.edges[c.e]["a"], ()):
            (c.nxt, c.turn), c.nx2 = plan[0], plan[1:] or None    # the turns along the path were already planned
        c.shift, c.shift_t = 0.0, 0.0
        e2 = self.w.edges[c.e]
        self._set_lane(c, e2)
        return True

    SQUEEZE_V = 3.0
    CREEP = True                                   # stopped cars may edge into a junction once their body fits clear of the box
    CLEAR_LINE = False                             # OFF: made blocking worse in the lab; a car waiting at a junction stops far enough back that its body is clear of the other roads' lanes (shallow slip-road merges)
    YIELD_BACKOFF = False                          # a waiting car that blocks a priority car from another road backs off to let it pass
    EXIT_ETA = 0.5                                 # s: a waiting car counts exit-lane cars as gone once they will have moved on by the time it arrives (0.5 = only those already clear)
    BRAKE_DECEL = 5.0                              # m/s2: hardest slowing a car applies towards its speed limit
    EXIT_PATH_ETA = 1.0                            # 0..1: how much of the car's own arrival time the exit-path check lets moving cars cover first (0 = judge by where they are now)
    LANE_PICK = True                               # a car approaching a junction whose exit lane is occupied moves to a neighbouring lane whose exit is free
    CLAIM_GEOM = False                             # junction exit claims are shared by movements whose paths do not come within a car's width of each other (not one movement at a time)
    CLAIM_MARGIN = 1.9                             # m: closest two movement paths may come and still count as compatible
    DODGE = True                                   # a car held up by a standing car that is itself waiting (not a queue) takes a free neighbouring lane at once

    def scan(self, c, rng_ahead, ox=0.0, oy=0.0, flip=False, back=-0.2, heading=None, include_cars=True):
        """Gap to the nearest thing in front of car c (or, moved by (ox, oy) / turned round, where it could go); the thing
        itself is left in self.lead."""
        ch_ = c.h if heading is None else heading
        hx, hy = math.cos(ch_), math.sin(ch_)
        if flip:
            hx, hy = -hx, -hy
        rx, ry = -hy, hx
        best = None
        cx, cy = c.x + ox, c.y + oy
        ex, ey = cx + hx * (rng_ahead + 7.5), cy + hy * (rng_ahead + 7.5)       # only the cells the look-ahead strip can touch (a car is < 7.5 m half-length / half-width)
        bx_, by_ = cx + hx * min(back, 0.0), cy + hy * min(back, 0.0)
        hwc, hlc = vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind]
        cos, sin = math.cos, math.sin
        hash_get = self.hash.get
        for ix in range(int((min(bx_, ex) - 8.0) // 16), int((max(bx_, ex) + 8.0) // 16) + 1):
            for iy in range(int((min(by_, ey) - 8.0) // 16), int((max(by_, ey) + 8.0) // 16) + 1):
                for o in hash_get((ix, iy), ()):
                    ob = o[4]
                    if ob is c or (not include_cars and isinstance(ob, Car)) or (o[6] is not None and abs(o[6] - c.gz) > 3.0):
                        continue
                    ox, oy, oh = o[0], o[1], o[5]
                    if isinstance(ob, (Car, Body)) and getattr(ob, "kind", None) not in (vehicles.SEMI, vehicles.ARTIC_BUS):
                        ox, oy, oh = getattr(ob, "x", ox), getattr(ob, "y", oy), getattr(ob, "h", oh)
                    dx, dy = ox - cx, oy - cy
                    fwd = dx * hx + dy * hy
                    if fwd > rng_ahead + o[3]:
                        continue
                    lat = abs(dx * rx + dy * ry)
                    if oh is None:                                    # a person: a thin upright post
                        if lat > hwc + o[2] + 0.15 or fwd < 0.3:
                            continue
                        hl = o[3]
                    else:                                             # the other car's box, seen from this car's heading:
                        if fwd < back or lat > o[2] + o[3] + hwc:             # (cheap rejects before the trig: the box is never wider)
                            continue
                        angle = oh - ch_ - (math.pi if flip else 0.0)
                        ca, sa = abs(cos(angle)), abs(sin(angle))
                        if lat > ca * o[2] + sa * o[3] + hwc + 0.25:
                            continue
                        hl = ca * o[3] + sa * o[2]
                        if lat > hwc and sa > 0.12:
                            # On an adjacent lane the nearest corner may sit outside our path.
                            width = hwc + 0.25
                            corners = _corners(fwd, dx * rx + dy * ry, angle, o[3], o[2])
                            ends = [u for u, v in corners if -width <= v <= width]
                            for (a, va), (b, vb) in zip(corners, corners[1:] + corners[:1]):
                                for boundary in (-width, width):
                                    if min(va, vb) < boundary < max(va, vb):
                                        ends.append(a + (b - a) * (boundary - va) / (vb - va))
                            if not ends:
                                continue
                            hl = fwd - min(ends)
                    gap = fwd - hlc - hl
                    if best is None or gap < best:
                        best, self.lead = gap, o
        return best

    def _route_gap(self, c, e, reach, on_edge):
        """Follow the connected lane through a junction, rather than a ray aimed across its other arms."""
        moves = [((c.e, c.d), 0.0)]
        if c.nxt is not None:
            moves.extend([(c.nxt, c.turn), *(c.nx2 or ())])
        along = -c.s
        lane, best, lead = c.lidx, None, None
        previous = (c.e, c.d)
        for i, (move, angle) in enumerate(moves):
            if along > reach or (i and move[0] == c.e):
                break
            road = self.w.edges[move[0]]
            if i:
                following = moves[i + 1][1] if i + 1 < len(moves) else 0.0
                lane = self._mapped_lane(previous, lane, move, angle, following)
            offset = c.lane + c.shift + c.avoid if i == 0 else self.lanes_of(road, move[1])[lane]
            for o in on_edge.get(move, ()):
                forward = along + o.s
                if o is c or (o.e, o.d) != move or not 0.0 < forward < reach or abs(o.gz - c.gz) > 3.0:
                    continue
                x, y, h = self._ref(road, move[1], o.s, offset)
                lateral = abs((x - o.x) * math.sin(h) + (o.y - y) * math.cos(h))
                if lateral > vehicles.HALF_W[c.kind] + vehicles.HALF_W[o.kind] + 0.18:
                    continue
                ahead = forward - vehicles.HALF_L[c.kind] - vehicles.HALF_L[o.kind]
                if best is None or ahead < best:
                    best, lead = ahead, o
            along += road["len"]
            previous = move
        return best, lead

    def _ped_gap(self, c):
        """Distance to an occupied crossing of the car's actual motion corridor."""
        hx, hy = math.cos(c.h), math.sin(c.h)
        hl, hw = vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind]
        cvx, cvy = c.v * hx, c.v * hy
        horizon = min(2.4, max(0.8, c.v / 3.0 + 0.8))
        zebra = getattr(getattr(self, "w", None), "on_zebra", None)
        hash_get = self.hash.get
        radius = 5.0 + (c.v + 5.0) * horizon
        gap = None
        for ix in range(int((c.x - radius) // 16), int((c.x + radius) // 16) + 1):
            for iy in range(int((c.y - radius) // 16), int((c.y + radius) // 16) + 1):
                for o in hash_get((ix, iy), ()):
                    if o[5] is not None or (o[6] is not None and abs(o[6] - c.gz) > 3.0):
                        continue
                    dx, dy = o[0] - c.x, o[1] - c.y
                    if dx * dx + dy * dy > radius * radius:
                        continue
                    ped = o[4]
                    rvx, rvy = getattr(ped, "vx", 0.0) - cvx, getattr(ped, "vy", 0.0) - cvy
                    fwd, lat = dx * hx + dy * hy, -dx * hy + dy * hx
                    t = corridor_entry(fwd, lat, rvx * hx + rvy * hy, -rvx * hy + rvy * hx,
                                       hl + 0.45, hw + o[2] + 0.18, horizon)
                    if t is not None and (fwd > -hl or t > 0.0):
                        if (zebra is not None and not isinstance(ped, Walker) and t > 0.55
                                and not zebra(o[0] + getattr(ped, "vx", 0.0) * t, o[1] + getattr(ped, "vy", 0.0) * t)
                                and not zebra(o[0], o[1])):
                            continue                    # forecast a yield at zebras, brake elsewhere only for imminent contact
                        d = max(0.0, fwd - hl - 0.4) if t == 0.0 else c.v * t
                        gap = d if gap is None else min(gap, d)
        return gap

    def _ped_in_way(self, c):
        return self._ped_gap(c) is not None

    def _cross(self, c, horizon=3.5):
        """Look along the line of motion of everything moving nearby: if a crossing vehicle and car c would meet (their
        boxes overlapping at the moment of closest approach within `horizon` s), the distance c may still
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
                    if ob is c or (o[6] is not None and abs(o[6] - c.gz) > 3.0):
                        continue
                    dx, dy = o[0] - c.x, o[1] - c.y
                    boss = not isinstance(ob, Car)                # driven by the player or a script: it won't yield
                    if not boss and -dx * hy + dy * hx < 0:      # it comes from our left: it gives way to us
                        continue
                    ch = math.cos(o[5] - c.h)
                    if abs(ch) > 0.8:                             # same way or head-on: the lane scan handles those
                        continue
                    if boss:
                        ovx, ovy = ob.vx, ob.vy
                    else:
                        ospeed = -2.2 if ob.rev > 0 else ob.v
                        ovx, ovy = ospeed * math.cos(ob.h), ospeed * math.sin(ob.h)
                    if ovx * ovx + ovy * ovy < 0.36:
                        continue                               # standing beside the junction cannot cross into our path
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
                    if abs(-px * hy + py * hx) < hwc + hw and abs(px * hx + py * hy) < hlc + hl + 0.5:
                        g = v * t - hlc
                        if best is None or g < best:
                            best = g
        return best

    WAIT = (6.0, 4.0, 2.5, 1.8)      # seconds a stopped car waits before trying to get out, by aggression setting
    LOCK_MAN = math.atan(1.5 * math.tan(0.55))   # front-wheel lock while manoeuvring: turns 50 % tighter than normal driving
    LOCK_WAY = math.atan(2.0 * math.tan(0.55))   # making way for an oncoming car: half the normal turning radius

    def _step_clear(self, c, x, y, h):
        self.step_blocker = None
        if c.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS):
            return self._path_clear(c, [(x, y, h, 0.0)], escaping=True, track_blocker=True)
        probe = SimpleNamespace(kind=c.kind, x=x, y=y, h=h, trh=c.trh, tra=c.tra)
        tow(probe)
        return all(self._path_clear(c, [(px, py, ph, 0.0)], escaping=True, section=old, track_blocker=True)
                   for old, (px, py, ph, _, _) in zip(parts(c), parts(probe)))

    def _path_clear(self, c, poses, escaping=False, parked_only=False, reserved_exit=False, section=None, track_blocker=False):
        """Check the car's footprint along a proposed path, including approaching traffic."""
        ox0, oy0, oh0, hl, hw = section or (c.x, c.y, c.h, vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind])
        old = _corners(ox0, oy0, oh0, hl + 0.08, hw + 0.08) if escaping else None
        zebra = getattr(self.w, "on_zebra", None) if reserved_exit else None
        for x, y, h, eta in poses:
            box = _corners(x, y, h, hl + 0.08, hw + 0.08)
            reach = hl + hw + 8.0 + 26.0 * eta
            for ix in range(int((x - reach) // 16), int((x + reach) // 16) + 1):
                for iy in range(int((y - reach) // 16), int((y + reach) // 16) + 1):
                    for ox, oy, ow, ol, ob, oh, oz in (() if parked_only else self.hash.get((ix, iy), ())):
                        if ob is c or (oz is not None and abs(oz - c.gz) > 3.0):
                            continue
                        if isinstance(ob, Car):
                            if ob.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS):
                                ox, oy, oh = ob.x, ob.y, ob.h
                            speed = -2.2 if ob.rev > 0 else ob.v
                            if eta and ob.turnaround is not None:
                                arc = ob.turnaround
                                ox, oy, oh = self._arc_pose(arc, min(math.pi, arc[-1] + 2.2 * eta / abs(arc[3])))
                            elif eta:
                                ox += math.cos(oh) * speed * eta
                                oy += math.sin(oh) * speed * eta
                                if ob.shift or ob.lcd > 0 or ob.man > 0 or ob.avoid:
                                    road = self.w.edges[ob.e]
                                    tx, ty, th = self._ref(road, ob.d, ob.s, ob.lane + ob.shift + ob.avoid + ob.yld)
                                    side = (ob.x - tx) * math.sin(th) + (ty - ob.y) * math.cos(th)
                                    side = max(-1.4 * eta, min(1.4 * eta, side))
                                    ox -= math.sin(th) * side
                                    oy += math.cos(th) * side
                        elif isinstance(ob, Body):
                            ox += ob.vx * eta
                            oy += ob.vy * eta
                        elif oh is None:
                            ox += getattr(ob, 'vx', 0.0) * eta
                            oy += getattr(ob, 'vy', 0.0) * eta
                            if zebra is not None and not isinstance(ob, Walker) and not zebra(ox, oy):
                                continue
                            oh, ol = 0.0, ow
                        if self._obstructs(box, h, old, oh0, x, y, ox, oy, oh, ol, ow, hl + hw):
                            if track_blocker:
                                self.step_blocker = ob
                            return False
                    for ox, oy, ow, ol, oh, oz in self.ph.get((ix, iy), ()):
                        if (oz is None or abs(oz - c.gz) <= 3.0) and self._obstructs(
                                box, h, old, oh0, x, y, ox, oy, oh, ol, ow, hl + hw):
                            return False
        return True

    @staticmethod
    def _obstructs(box, h, old, old_h, x, y, ox, oy, oh, ol, ow, radius):
        if (x - ox) ** 2 + (y - oy) ** 2 > (radius + ol + ow + 0.2) ** 2:
            return False
        other = _corners(ox, oy, oh, ol, ow)
        hit = _sat(box, h, other, oh)
        if hit is None:
            return False
        # If physics has already pushed the cars together, let them separate.
        previous = _sat(old, old_h, other, oh) if old is not None else None
        if previous is None:
            return True
        return hit[0] > previous[0] + 1e-5

    def _lane_room(self, c, e, lane, ahead, behind=3.0, opposing=False):
        """Sample a lane in road coordinates; include the approach behind and any oncoming closing speed."""
        poses = []
        lo, hi = max(0.0, c.s - behind), min(e["len"], c.s + ahead)
        n = max(1, math.ceil((hi - lo) / 2.0))
        for i in range(n + 1):
            s = lo + (hi - lo) * i / n
            pose = self._ref(e, c.d, s, lane)
            poses.append((*pose, 0.0))
            if opposing or abs(s - c.s) < 8.0:
                poses.append((*pose, 1.6))
        return self._path_clear(c, poses)

    @staticmethod
    def _arc_pose(arc, a):
        x, y, h, radius, _ = arc
        nh = h + math.copysign(a, radius)
        return x + radius * (math.sin(nh) - math.sin(h)), y - radius * (math.cos(nh) - math.cos(h)), nh

    def _start_turnaround(self, c, e, wb):
        if e["ow"] or e.get("taper") or e["bridge"] or c.kind in vehicles.HEAVY or c.stn is not None \
                or c.lidx != 0 or min(c.s, e["len"] - c.s) < self.APPR:
            return False
        x, y, h = self._ref(e, c.d, c.s, 0.0)
        if math.cos(c.h - h) < 0.995:
            return False
        side = (x - c.x) * math.sin(h) + (c.y - y) * math.cos(h)
        lo, hi = lane_bounds(e, -c.d)
        width = e["w"] * 0.5
        # Try the opposite lane centre first, then the widest arc that still lands inside its kerb.
        for goal in (-self.lanes_of(e, -c.d)[-1], -hi + vehicles.HALF_W[c.kind] + 0.2):
            if -goal < lo + vehicles.HALF_W[c.kind]:
                continue
            r = (goal - side) * 0.5
            if r > -wb * turn_radius_factor(2.2, c.kind) / math.tan(self.LOCK_WAY):
                continue
            arc = (c.x, c.y, c.h, r, 0.0)
            room = []
            for i in range(1, 17):
                a = math.pi * i / 16
                px, py, ph = self._arc_pose(arc, a)
                for bx, by in _corners(px, py, ph, vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind]):
                    lateral = (x - bx) * math.sin(h) + (by - y) * math.cos(h)
                    along = c.s + (bx - x) * math.cos(h) + (by - y) * math.sin(h)
                    if abs(lateral) > width - 0.08 or not 2.0 < along < e["len"] - 2.0:
                        break
                    rx, ry, _ = self._ref(e, c.d, along, 0.0)
                    if (rx - x - (along - c.s) * math.cos(h)) ** 2 + (ry - y - (along - c.s) * math.sin(h)) ** 2 > 0.15 ** 2:
                        break
                else:
                    room.extend(((px, py, ph, 0.0), (px, py, ph, a * abs(r) / 2.2)))
                    continue
                break
            else:
                if self._path_clear(c, room):
                    c.turnaround = arc
                    c.shift = c.avoid = c.yld = 0.0
                    c.nxt = c.nx2 = c.goal = c.arr = None
                    return True
        return False

    def _junction_turnaround(self, c, e, wb, remaining):
        """Fit a left-hand U-turn between the two lane centers before advancing past the node."""
        if c.lidx != 0 or c.kind in vehicles.HEAVY or c.kind == vehicles.ARTIC_BUS or c.shift or c.v > 3.5:
            return False
        ei, direction = c.nxt
        road = self.w.edges[ei]
        x, y, h = self._ref(e, c.d, c.s, 0.0)
        hx, hy = math.cos(h), math.sin(h)
        if math.cos(c.h - h) < 0.995 or abs((c.x - x) * -hy + (c.y - y) * hx - c.lane) > 0.4:
            return False
        minimum = wb * turn_radius_factor(2.2, c.kind) / math.tan(self.LOCK_WAY)
        hl, hw = vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind]
        blocked = False
        for lane in self.lanes_of(road, direction):
            tx, ty, th = self._ref(road, direction, 0.0, lane)
            if math.cos(th - c.h) > -0.997:
                continue
            radius = ((ty - c.y) * math.cos(c.h) - (tx - c.x) * math.sin(c.h)) * 0.5
            if radius > -minimum:
                continue
            # Begin as soon as the nose can sweep around the end of the approach.
            edge_allowance = 0.6 if ei == c.e else min(e["w"], road["w"]) * 0.5
            if remaining > abs(radius) + hl + 0.8 or remaining < abs(radius) + hl - edge_allowance:
                continue
            arc = (c.x, c.y, c.h, radius, 0.0)
            poses = []
            for i in range(1, 13):
                angle = math.pi * i / 12
                px, py, ph = self._arc_pose(arc, angle)
                if any(abs((by - y) * hx - (bx - x) * hy) > max(e["w"], road["w"]) * 0.5 - 0.03
                       for bx, by in _corners(px, py, ph, hl, hw)):
                    break
                poses.extend(((px, py, ph, 0.0), (px, py, ph, angle * abs(radius) / 2.2)))
            else:
                if self._path_clear(c, poses):
                    c.turnaround = arc
                    c.avoid = c.yld = 0.0
                    return True
                blocked = True
        return None if blocked else False

    def _advance_turnaround(self, c, e, dt):
        arc = c.turnaround
        speed = min(2.2, c.v + 3.2 * dt)
        a = min(math.pi, arc[-1] + speed * dt / abs(arc[3]))
        pose = self._arc_pose(arc, a)
        if not self._path_clear(c, [(*pose, 0.0)], escaping=True):
            c.braking, c.v = True, 0.0
            return
        c.x, c.y, c.h = pose
        c.gz = self.w.level(c.x, c.y, c.gz)
        c.v, c.braking = speed, False
        if a < math.pi:
            c.turnaround = (*arc[:4], a)
            return
        if c.nxt is None:
            c.d, c.s = -c.d, e["len"] - c.s
            c.lidx = len(self.lanes_of(e, c.d)) - 1
        else:
            self._next_edge(c)
            e = self.w.edges[c.e]
            x, y, h = self._ref(e, c.d, 0.0, 0.0)
            side = (c.y - y) * math.cos(h) - (c.x - x) * math.sin(h)
            c.s = max(0.0, min(e["len"], (c.x - x) * math.cos(h) + (c.y - y) * math.sin(h)))
            c.lidx = min(range(lane_count(e, c.d)), key=lambda i: abs(self.lanes_of(e, c.d)[i] - side))
        self._set_lane(c, e)
        c.turnaround, c.str = None, 0.0
        c.stuck, c.cool, c.man = 0.0, 3.0, 2.0
        c.rerouted = 0.0

    def _back_up(self, c, e, wb, dt):
        tx, ty, road_h = self._ref(e, c.d, max(0.0, c.s - 3.6), c.rside)
        error = (math.atan2(c.y - ty, c.x - tx) - c.h + math.pi) % (2 * math.pi) - math.pi
        steer = max(-0.6, min(0.6, -math.atan2(2.0 * wb * math.sin(error), 3.6)))
        distance = 2.2 * dt
        for angle in (0.0,) if c.rev_box else (steer, 0.0):
            heading = c.h - distance * math.tan(angle) / wb
            travel = (c.h + heading) * 0.5 + math.atan(0.52 * math.tan(angle))
            x, y = c.x - distance * math.cos(travel), c.y - distance * math.sin(travel)
            if (c.rev_box or c.s > 2.5) and self._path_clear(c, [(x, y, heading, 0.0)], escaping=True):
                c.x, c.y, c.h, c.str = x, y, heading, angle
                c.s = max(0.0, c.s - distance * max(0.0, math.cos(travel - road_h)))
                c.rev -= dt
                break
        else:
            c.rev = 0.0
        c.v = 0.0
        if c.rev <= 0:
            c.rev, c.cool, c.stuck = 0.0, 3.0 if c.rev_box else 0.8, 0.8
            c.rev_box = False
            c.man = max(c.man, 2.0)
            c.rside = 0.0

    def _request_reverse(self, c, side):
        if any(isinstance(other, Car) and other is not c and (other.rev > 0 or other.turnaround)
               and (other.x - c.x) ** 2 + (other.y - c.y) ** 2 < 28.0 ** 2
               for ix in range(int((c.x - 28) // 16), int((c.x + 28) // 16) + 1)
               for iy in range(int((c.y - 28) // 16), int((c.y + 28) // 16) + 1)
               for _, _, _, _, other, _, _ in self.hash.get((ix, iy), ())):
            return False
        vx, vy = math.cos(c.h), math.sin(c.h)
        poses = [(c.x - n * vx, c.y - n * vy, c.h, n / 2.2) for n in (0.7, 1.6, 2.5)]
        if not self._path_clear(c, poses, escaping=True):
            return False
        c.rev, c.rside, c.man = 2.2, side, 3.0
        return True

    def _retreat_in_box(self, c):
        """Back up a car with a blocked nose only if the swept rear path stays on the road."""
        vx, vy = math.cos(c.h), math.sin(c.h)
        poses = [(c.x - n * vx, c.y - n * vy, c.h, n / 2.2) for n in (0.7, 1.6, 2.5)]
        if c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or any(
                self.w.surface(x, y) not in (2, 3) or self.w.kerb(x, y) for x, y, _, _ in poses):
            return False
        if not self._path_clear(c, poses, escaping=True):
            return False
        c.rev, c.rev_box = 2.5 / 2.2, True
        return True

    def _restore_lane(self, c, e, dt):
        if c.shift:
            c.shift_t += dt
            if c.shift_t > 1.5 and self._lane_room(c, e, c.lane, 10.0):
                c.shift = c.shift_t = 0.0
                c.man = max(c.man, 2.0)
                return True
        return False

    def _untangle(self, c, e, gap, lead, dt, wb):
        """Choose a way out of a physical blockage and commit until there is room to resume the route."""
        ag = (getattr(self.sim, "aggro", 1) if self.sim else 1) % 4
        if c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or c.stn is not None or c.rev > 0 or c.cool > 0:
            return
        x, y, h = self._ref(e, c.d, c.s, 0.0)
        side = (x - c.x) * math.sin(h) + (c.y - y) * math.cos(h)
        lo, hi = lane_bounds(e, c.d)
        own_side = side >= lo + vehicles.HALF_W[c.kind] - 0.15
        head_on = (not e["ow"] and isinstance(lead, Car) and lead.e == c.e and lead.d != c.d
                   and math.cos(lead.h - c.h) < -0.65 and gap is not None and gap < 9.0)
        if not head_on and self._restore_lane(c, e, dt):
            return
        if c.s < 4.0 or e["len"] - c.s < 6.0:
            return
        if head_on and c.v < 2.5 and (c.stuck >= 0.6 or c.shift or not own_side):
            refuge = hi - vehicles.HALF_W[c.kind] - 0.14
            if refuge > side + 0.18 and self._lane_room(c, e, refuge, 5.0, behind=0.0):
                if abs(c.lane + c.shift - refuge) > 0.15:
                    c.shift, c.shift_t = refuge - c.lane, 0.0
                    c.stuck = min(c.stuck, 0.6)        # give this steering attempt time to work
                c.man = max(c.man, 2.0)
            if c.stuck < 2.0 or lead.turnaround is not None:
                return
            # Give the encroaching driver first choice to retreat. An equally placed pair uses list order.
            lx, ly, lh = self._ref(e, lead.d, lead.s, 0.0)
            lead_side = (lx - lead.x) * math.sin(lh) + (lead.y - ly) * math.cos(lh)
            lead_own = lead_side >= lane_bounds(e, lead.d)[0] + vehicles.HALF_W[lead.kind] - 0.15
            if (own_side, self._order[c]) > (lead_own, self._order[lead]) and lead.stuck < 5.0:
                return
            if any(o.e == c.e and o.rev > 0 and (o.x - c.x) ** 2 + (o.y - c.y) ** 2 < 30.0 ** 2 for o in self.cars):
                return
            driver = c
            while driver.s >= 6.0 and c.s - driver.s <= 24.0:
                if driver.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or driver.turnaround:
                    break
                if self._request_reverse(driver, refuge if driver is c else driver.lane + driver.shift):
                    return
                back_gap = self.scan(driver, 6.0, flip=True)
                behind = self.lead[4] if back_gap is not None else None
                if not isinstance(behind, Car) or behind.e != c.e or behind.d != c.d or behind.v >= 0.35 \
                        or behind.s >= driver.s or back_gap >= 2.7:
                    break
                driver = behind
        if not head_on and not c.shift and own_side and self._dodge(c, e, gap, lead, side):
            return
        if c.v > 0.35 or c.stuck < self.WAIT[ag] or gap is None or gap > 4.0:
            return
        if not head_on and not c.shift and own_side:
            for lane in sorted(self.lanes_of(e, c.d), key=lambda lane: abs(lane - side)):
                if abs(lane - side) > 0.65 and self._lane_room(c, e, lane, 14.0, behind=7.0):
                    c.shift, c.shift_t, c.man, c.stuck = lane - c.lane, 0.0, 3.0, 0.0
                    c.avoid = 0.0
                    return
            if (not e["ow"] and c.s > 14.0 and e["len"] - c.s > 45.0 and c.stuck > self.WAIT[ag] + 1.0
                    and (lead is None or isinstance(lead, Body) or (isinstance(lead, Car) and lead.stuck > 3.0))):
                lane = -self.lanes_of(e, -c.d)[0]
                if self._lane_room(c, e, lane, 38.0, behind=7.0, opposing=True):
                    c.shift, c.shift_t, c.man, c.stuck = lane - c.lane, 0.0, 3.0, 0.0
                    c.avoid = 0.0
                    return
        if lead is None and c.stuck > self.WAIT[ag] + 1.0 and self._request_reverse(c, c.lane):
            return                                      # make steering room when boxed against a stationary vehicle
        if c.stuck > 3.0 * self.WAIT[ag] and self._start_turnaround(c, e, wb):
            return
        if not head_on and (c.shift or not own_side) and c.stuck > self.WAIT[ag] + 2.0:
            if self._request_reverse(c, c.lane):
                c.shift, c.shift_t = 0.0, 0.0
        c.cool = max(c.cool, 0.35)

    def _dodge(self, c, e, gap, lead, side):
        """Space-based: the car ahead stands still and is not itself held by anything in front (a side-street car waiting
        at its line, a slip-road car, a breakdown), so waiting behind it gains nothing.  Take a neighbouring lane the moment
        that lane is free, no timer.  The shift is undone by _restore_lane once the own lane is clear again."""
        if not self.DODGE or gap is None or not isinstance(lead, Car) or c.v > 7.0 or gap > 6.0 + c.v * 1.2:
            return False
        if lead.v > 0.5 or lead.rev > 0 or lead.turnaround or c.rev > 0 or c.man > 0:
            return False                                     # moving or reversing
        if lead.blk is not None and (lead.e, lead.d) == (c.e, c.d):
            return False                                     # one car of a queue in our own lane (a car from another road is no queue)
        if c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or e["len"] - c.s < 10.0:
            return False
        lanes = self.lanes_of(e, c.d)
        permitted = movement_lanes(self.w, (c.e, c.d), c.nxt, c.turn) if c.nxt is not None else None
        for idx in sorted(range(len(lanes)), key=lambda i: abs(lanes[i] - side)):
            lane = lanes[idx]
            if abs(lane - side) <= 0.65 or abs(lane - side) > 4.2 or (permitted is not None and idx not in permitted):
                continue
            if self._lane_room(c, e, lane, 14.0 + c.v * 1.5, behind=7.0):
                c.shift, c.shift_t, c.man = lane - c.lane, 0.0, 3.0
                c.avoid = 0.0
                return True
        return False

    OVERTAKE = True                                # swerve into the oncoming lane (or half over the line) round a standing obstruction when it is clear

    def _overtake(self, c, e, obs, base, dhi, hwc, committed, ahead):
        """Lateral move (relative to the car's lane) that passes standing obstacles by crossing the centre line, or None.
        Only on a straight, long-enough, two-way road, and only while the oncoming lane is clear for the whole pass.  A car
        already across the line carries on (the oncoming cars brake for it, a stop half way would block both lanes)."""
        L = e["len"]
        span = max([g for _, _, g in obs if g < 1e8] + [0.0]) + 24.0 + c.v * 1.0
        if c.s < 4.0 or L - c.s < span + 8.0:
            return None
        if not committed and min([g for _, _, g in obs if g < 1e8] + [1e9]) < 4.0:
            return None                                      # too close to start a swerve: the stuck-recovery logic handles it
        _x, _y, h1 = self._ref(e, c.d, c.s + span, 0.0)
        if math.cos(h1 - self._ref(e, c.d, c.s, 0.0)[2]) < 0.985:
            return None
        lo = -e["w"] / 2 + hwc + 0.2
        for m in (0.55, 0.3):
            need = [(lat, hwc + wid + m) for lat, wid, _g in obs]
            cands = [0.0, lo - base, dhi]
            for lat, r in need:
                cands += [lat - r - 0.02, lat + r + 0.02]
            best = None
            for d_ in cands:
                if lo - base - 1e-6 <= d_ <= dhi + 1e-6 and all(abs(lat - d_) >= r - 0.01 for lat, r in need) \
                        and (best is None or abs(d_) < abs(best)):
                    best = d_
            if best is not None:
                break
        if best is None:
            return None
        if not committed and not self._lane_room(c, e, base + best, span, behind=0.0, opposing=True):
            return None                                      # oncoming traffic: wait behind the obstruction
        return best

    def _courtesy(self, c, e, vlim, ems, ph, dt):
        """Swerve round kerb-parked cars and pull over for emergency vehicles.  Smooth sideways targets (c.avoid / c.yld);
        returns the speed limit, slowed while the room is tight."""
        bx, by, road_h = self._ref(e, c.d, c.s, 0.0) if ph or ems else (c.x, c.y, c.h)
        hx, hy = math.cos(road_h), math.sin(road_h)
        rx, ry = -hy, hx
        hwc = vehicles.HALF_W[c.kind]
        ahead = 8.0 + c.v * 1.6
        tgt, bgap = 0.0, None
        tight = c.stuck > 2.0                                     # held up for a while: squeeze past with less spare room, up a kerb if need be
        if ph:
            m = 0.15 if tight else 0.45
            obs = []                                              # standing vehicles near the path: (lateral offset, half-width, gap ahead)
            hl_c = vehicles.HALF_L[c.kind]
            passing = self.OVERTAKE and abs(c.avoid) > 0.3
            gx, gy = int(c.x // 16), int(c.y // 16)
            n = int(ahead // 16) + 1
            for ix in range(gx - n, gx + n + 1):
                for iy in range(gy - n, gy + n + 1):
                    for ox, oy, ohw, ohl, oh, oz in ph.get((ix, iy), ()):
                        if oz is not None and abs(oz - c.gz) > 3.0:
                            continue
                        dx, dy = ox - c.x, oy - c.y
                        fwd = dx * hx + dy * hy
                        if fwd > ahead + ohl or fwd <= (-(hl_c + ohl + 0.5) if passing else 0.1):
                            continue
                        ca, sa = abs(math.cos(oh - road_h)), abs(math.sin(oh - road_h))
                        wid = ca * ohw + sa * ohl
                        lat = dx * rx + dy * ry
                        if abs(lat) < hwc + wid + m + 0.6:
                            g_ = fwd - hl_c - (ca * ohl + sa * ohw)
                            obs.append((lat, wid, g_ if fwd > 0.1 else 1e9))   # beside us already: keeps the lateral room, no braking
            if obs:
                base = (bx - c.x) * math.sin(road_h) + (c.y - by) * math.cos(road_h)
                ext = 0.8 if tight else 0.0                       # a kerb may be mounted a little when held up
                if c.shift:                                      # keep the lane chosen by recovery until it can merge back
                    tmin = tmax = c.lane + c.shift
                elif e["ow"]:
                    tmin, tmax = -e["w"] / 2 + hwc + 0.2 - ext, e["w"] / 2 - hwc - 0.2 + ext
                else:
                    divider, _ = lane_bounds(e, c.d)
                    tmin = divider + hwc + 0.15
                    tmax = e["w"] / 2 - hwc - 0.1 + ext
                dlo, dhi = tmin - base, tmax - base               # sideways moves that stay on the road (or its kerb)
                for m in (m, 0.0):                                # with some spare room if there is any, else body to body: what fits may pass
                    need = [(lat, hwc + wid + m) for lat, wid, _g in obs]
                    cands = [0.0, dlo, dhi]
                    for lat, r in need:
                        cands += [lat - r - 0.02, lat + r + 0.02]
                    best = None
                    for d_ in cands:
                        if dlo - 1e-6 <= d_ <= dhi + 1e-6 and all(abs(lat - d_) >= r - 0.01 for lat, r in need) and (best is None or abs(d_) < abs(best)):
                            best = d_
                    if best is not None:
                        break
                if best is None and self.OVERTAKE and not e["ow"] and not e["bridge"] and not c.shift and c.stn is None \
                        and c.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS) and not c.rev and c.turnaround is None:
                    best = self._overtake(c, e, obs, base, dhi, hwc, passing, ahead)
                block = [g for lat, wid, g in obs if abs(lat) < hwc + wid + m and g < 1e8]
                gap0 = min(block) if block else None
                if best is None:                                  # no room to get round it: stop short
                    tgt, bgap = c.avoid, gap0
                else:
                    nominal = c.lane + c.shift + c.yld
                    if all(abs(lat - (nominal - base)) >= hwc + wid + m for lat, wid, _ in obs):
                        best, tgt = nominal - base, 0.0
                    else:
                        tgt = base + best - nominal
                    bgap = gap0
                if bgap is not None:
                    vlim = min(vlim, max(0.0, (bgap - 1.5) * 0.7))
                elif abs(tgt) > 0.2:
                    vlim = min(vlim, 5.0)
        c.avoid += max(-1.5 * dt, min(1.5 * dt, tgt - c.avoid))
        ytgt = 0.0
        for b in ems:
            dx, dy = c.x - b.x, c.y - b.y
            if dx * dx + dy * dy > 3600.0:
                continue
            ex, ey = math.cos(b.h), math.sin(b.h)
            fwd = dx * ex + dy * ey
            if b.vx * ex + b.vy * ey > 1.0 and hx * ex + hy * ey > 0.7 \
                    and 0.0 < fwd < 45.0 and abs(-dx * ey + dy * ex) < 5.0:
                side = 1.0 if c.lane > 0 else -1.0
                ytgt = side * (e["w"] / 2 - hwc - 0.25) - c.lane
                if abs(c.avoid) > 0.3:
                    ytgt = 0.0
                vlim = min(vlim, 4.5 if fwd > 14.0 else (1.0 if abs(c.yld - ytgt) > 0.4 else 0.0))
                break
        c.yld += max(-1.8 * dt, min(1.8 * dt, ytgt - c.yld))
        return vlim, bgap

    UTURN = 2.2                      # rad: a turn sharper than this (126 degrees) is a U-turn

    def _uturn_hold(self, c, e, rem):
        """Hold for an occupied turn or exit lane, using the real path near the turnaround."""
        if rem > 12.0:
            return None
        ei, direction = c.nxt
        road = self.w.edges[ei]
        lane = self.lanes_of(road, direction)[self._exit_lane(c, e, road)]
        poses = [(*self._ref(e, c.d, e["len"] - 0.5, c.lane), 0.0)]
        for s in (1.5, 4.0, 7.0):
            poses.extend((*self._ref(road, direction, min(s, road["len"]), lane), eta) for eta in (0.0, 1.4))
        if not self._path_clear(c, poses):
            return max(0.0, rem - 2.0)
        return None

    def _red_rem(self, c, L, sg):
        """Distance to a red stop line on the planned approach, including upstream pieces of short links."""
        if sg is None:
            return None
        hl = vehicles.HALF_L[c.kind]
        distance = -c.s
        route = [((c.e, c.d), 0.0)]
        if c.nxt is not None:
            route.extend([(c.nxt, c.turn), *(c.nx2 or ())])
        for i, ((ei, d), angle) in enumerate(route):
            if i and (ei == c.e or distance > 55.0 or abs(angle) > 0.5):
                break
            distance += L if i == 0 else self.w.edges[ei]["len"]
            end = int(d == 1)
            st = sg.state_of(ei, end)
            if st is None:
                continue
            rem = distance - sg.stopd.get((ei, end), 10.0) - hl - SIGNAL_STOP_BUFFER
            if rem < -2.5:
                continue
            if st == 0 or (st == 1 and c.v > 2.0 and rem + SIGNAL_STOP_BUFFER < c.v * c.v / 7.0 + 0.5):
                return None
            return rem
        return None

    APPR = 24.0                      # m before a junction where cars sort out who goes first

    def _yield_line(self, c, node):
        clearance = self.junctions[node] + vehicles.HALF_L[c.kind] + 2.2
        line = min(self.w.edges[c.e]["len"] * 0.7, max(11.0, clearance))
        if self.signals is not None:
            stopd = self.signals.stopd.get((c.e, int(c.d == 1)))
            if stopd is not None:
                line = max(line, min(self.w.edges[c.e]["len"], stopd + vehicles.HALF_L[c.kind] + SIGNAL_STOP_BUFFER))
        if self.CLEAR_LINE:
            key = (c.e, c.d, vehicles.HALF_W[c.kind], round(line, 1))
            hit = self._clear_cache.get(key)
            if hit is None:
                hit = self._clear_cache[key] = self._clear_line(c, node, line)
            line = hit
        return line

    def _clear_line(self, c, node, line):
        """Move the waiting point back along the own road until the car's body is clear of every other road meeting at
        the node (a slip road merging at a shallow angle runs inside the boulevard's right lane for many metres)."""
        w = self.w
        e = w.edges[c.e]
        others = []
        for ei in self._node_edges.get(node, ()):
            o = w.edges[ei]
            if ei == c.e or o["cls"] in ("footway", "path", "cycleway", "pedestrian", "steps"):
                continue
            if c.nxt is not None and ei == c.nxt[0]:
                continue
            pts = o["pts"] if o["b"] == node else o["pts"][::-1]      # towards the node
            near, acc = [], 0.0
            for i in range(len(pts) - 1, 0, -1):
                near.append(pts[i])
                acc += math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                if acc > 60.0:
                    break
            near.append(pts[max(0, i - 1)])
            others.append((near, o["w"] * 0.5))
        if not others:
            return line
        hw = vehicles.HALF_W[c.kind] + 0.2
        best = line
        d = line
        top = min(e["len"] * 0.7, line + 25.0)
        while d <= top:
            s = e["len"] - d if c.d == 1 else d
            px, py = w.edge_point(e, s)[:2]
            ok = True
            for near, half in others:
                for k in range(len(near) - 1):
                    ax, ay = near[k]
                    bx, by = near[k + 1]
                    dx, dy = bx - ax, by - ay
                    l2 = dx * dx + dy * dy or 1.0
                    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                    if (px - ax - dx * t) ** 2 + (py - ay - dy * t) ** 2 < (half + hw) ** 2 * 0.64:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                return d
            d += 1.5
        return best

    def _exit_clearance(self, c):
        incoming, outgoing = self.w.edges[c.e], self.w.edges[c.nxt[0]]
        start = outgoing["a" if c.nxt[1] == 1 else "b"]
        box = max(incoming["w"] * 0.5, self.junctions.get(start, 0.0))
        if c.creep == c.e:                                      # standing at the line: the body only has to fit clear of the junction box itself (cross flow is checked separately)
            return box + vehicles.HALF_L[c.kind] + 0.5
        return box + 2.0 * vehicles.HALF_L[c.kind] + 1.0

    def _exit_slots(self, c):
        """Directed lanes and distances needed to get the whole vehicle out of the junction."""
        if c.nxt is None:
            return []
        lane, previous = c.lidx, (c.e, c.d)
        clearance = self._exit_clearance(c)
        approach = self.w.edges[c.e]
        group = self.junction_complex.get(approach["b" if c.d == 1 else "a"])
        slots = []
        moves = [(c.nxt, c.turn), *(c.nx2 or ())]
        for i, (move, angle) in enumerate(moves):
            road = self.w.edges[move[0]]
            following = moves[i + 1][1] if i + 1 < len(moves) else 0.0
            lane = self._mapped_lane(previous, lane, move, angle, following)
            interior = group is not None and self.internal_links.get(move[0]) == group
            slots.append(((*move, lane), road["len"] if interior else min(road["len"], clearance)))
            if not interior:
                clearance -= road["len"]
            if clearance <= 0:
                break
            previous = move
        return slots

    def _exit_complete(self, c, slots):
        if not slots:
            return False
        e = self.w.edges[c.e]
        group = self.junction_complex.get(e["b" if c.d == 1 else "a"])
        return sum(end for (ei, _, _), end in slots
                   if group is None or self.internal_links.get(ei) != group) + 1e-6 >= self._exit_clearance(c)

    def _exit_blocked(self, c, eta=0.0):
        return any(rear + (speed * max(0.0, eta - 0.5) if moving else 0.0) < clearance
                   for lane, clearance in self._exit_slots(c)
                   for rear, speed, moving in self.occ.get(lane, ()))

    def _carrying_exit(self, c):
        """A short link can still lie inside the junction the car has already entered."""
        claim = self.exit_claims.get(c)
        if claim is None or (c.e, c.d) == claim[0] or c.nxt is None:
            return False
        return any(lane[:2] == c.nxt for lane, _ in claim[2])

    def _complex_movement(self, approach, slots, group):
        """Entry heading and net turn through the crossing, independent of the intermediate edges."""
        entry = self._head(self.w.edges[approach[0]], approach[1], True)
        for (ei, direction, _), _end in slots:
            if self.internal_links.get(ei) != group:
                exit_heading = self._head(self.w.edges[ei], direction, False)
                return entry, abs(math.remainder(exit_heading - entry, math.tau))
        return entry, math.pi

    def _reserve_exits(self, mine):
        """Grant space before the stop line, then keep it while the car crosses."""
        occupied, pending, complex_paths = set(), {}, {}
        for c, (approach, node, slots, deadline) in list(self.exit_claims.items()):
            on_approach = (c.e, c.d) == approach
            committed = on_approach and self.w.edges[c.e]["len"] - c.s < self._yield_line(c, node) - 0.2
            if c not in self._order or (c.rev > 0 and not c.rev_box) or (c.turnaround and c.nxt is None) or (on_approach and not committed
                    and (c not in mine or c in self.narrow_wait or self.t > deadline or self._exit_slots(c) != slots)):
                del self.exit_claims[c]
                continue
            if not on_approach:
                progress = next((i for i, (lane, _) in enumerate(slots) if lane[:2] == (c.e, c.d)), None)
                if progress is None or (progress == len(slots) - 1 and c.s >= slots[-1][1]):
                    del self.exit_claims[c]
                    continue
            occupied.update(lane for lane, _ in slots)
            if on_approach:
                pending.setdefault(node, []).append(c)
            group = self.junction_complex.get(node)
            if group is not None:
                complex_paths.setdefault(group, []).append(self._complex_movement(approach, slots, group))
        blocked, candidates = set(), []
        for c, me in mine.items():
            node, _, _ = me
            rem = self.w.edges[c.e]["len"] - c.s
            line = self._yield_line(c, node)
            if c in self.exit_claims or c in self.narrow_wait or not line - 0.2 <= rem <= line + max(5.0, c.v * c.v / 7.0 + 2.0 + self.CLAIM_LEAD * c.v) \
                    or c.rev > 0 or c.turnaround:
                continue
            if isinstance(c.blk, Car) and (c.blk.e, c.blk.d) == (c.e, c.d):
                continue
            red = self._red_rem(c, self.w.edges[c.e]["len"], self.signals)
            if c.nxt is None or (red is not None and -2.5 < red < rem):
                continue
            if self.CREEP and c.v < 0.5 and c.creep != c.e and (red is None or red < -2.5 or red > 60.0):     # stopped at the line (no timer): may edge in if the body fits
                c.creep = c.e
            slots = self._exit_slots(c)
            if not self._exit_complete(c, slots):
                planned = list(c.nx2 or ())
                move = planned[-1][0] if planned else c.nxt
                seen = {(c.e, c.d), c.nxt, *(move for move, _ in planned)}
                while not self._exit_complete(c, slots) and len(planned) < 7:
                    pick = self._choose(c, *move)
                    if pick is None:
                        break
                    moves, angles, preferred = pick
                    available = [i for i, item in enumerate(moves) if item not in seen and abs(angles[i]) <= self.UTURN]
                    if not available:
                        break
                    j = preferred if preferred in available else min(available, key=lambda i: abs(angles[i]))
                    move, angle = moves[j], angles[j]
                    seen.add(move)
                    planned.append((move, angle))
                    c.nx2 = planned
                    slots = self._exit_slots(c)
            sg = self.signals
            signal_blocks_exit = sg is not None and any(
                self.w.edges[ei]["len"] - sg.stopd.get((ei, int(direction == 1)), 10.0) - SIGNAL_STOP_BUFFER < end
                and sg.state_of(ei, int(direction == 1)) in (1, 2)
                for (ei, direction, _), end in slots)
            if not self._exit_complete(c, slots) or self._exit_blocked(c, self.EXIT_ETA) or signal_blocks_exit:
                blocked.add(c)
                continue
            poses = []
            hl = vehicles.HALF_L[c.kind]
            arrive = min(3.0, (rem + self.junctions.get(node, 0.0)) / max(c.v, 3.0)) * self.EXIT_PATH_ETA
            for (edge, direction, idx), end in slots:
                road = self.w.edges[edge]
                lane = self.lanes_of(road, direction)[idx]
                front = max(0.0, end - hl)
                rear = min(hl, front)
                poses.append((*self._ref(road, direction, rear, lane), arrive))
                if front - rear > 0.1:
                    poses.append((*self._ref(road, direction, front, lane), arrive))
            if not self._path_clear(c, poses, reserved_exit=True):
                blocked.add(c)
                continue
            candidates.append((me[1][0], c, me, rem, slots))
        self._blocked_exits = blocked
        ready = {request[1] for request in candidates}
        for _, c, me, rem, slots in sorted(
                candidates, key=lambda request: (request[0][0], abs(request[1].turn) < 0.5, request[0][1:]), reverse=True):
            node, (_, _, heading, _), _ = me
            if any(lane in occupied for lane, _ in slots) or self._give_way(c, rem, me, ready):
                continue
            if self.CLAIM_GEOM:
                mine_path = self._claim_path(c, slots)
                if any(self._paths_conflict(mine_path, self._claim_path(o, self.exit_claims[o][2]))
                       for o in pending.get(node, ()) if o in self.exit_claims):
                    continue
            elif any(not ((o.e, o.d) == (c.e, c.d) and o.lidx != c.lidx and max(abs(o.turn), abs(c.turn)) < 0.35)
                       and not (min(c.turn, o.turn) > -0.5 and math.cos(heading - self._head(self.w.edges[o.e], o.d, True)) < -0.86)
                       for o in pending.get(node, ())):
                continue
            group = self.junction_complex.get(node)
            if group is not None:
                whole_heading, bend = self._complex_movement((c.e, c.d), slots, group)
                if bend > self.UTURN:
                    self._blocked_exits.add(c)
                    continue
                through = bend < 0.45
                active = complex_paths.setdefault(group, [])
                if any(not (through and other_bend < 0.45 and abs(math.cos(whole_heading - other_heading)) > 0.88)
                       for other_heading, other_bend in active):
                    continue
                active.append((whole_heading, bend))
            self.exit_claims[c] = ((c.e, c.d), node, slots, self.t + 3.0)
            occupied.update(lane for lane, _ in slots)
            pending.setdefault(node, []).append(c)

    def _claim_path(self, c, slots):
        """Where the car goes through a junction: its position, then the centre of every exit lane it needs."""
        pts = [(c.x, c.y)]
        for (edge, direction, idx), end in slots:
            road = self.w.edges[edge]
            lane = self.lanes_of(road, direction)[idx]
            x, y, _ = self._ref(road, direction, min(max(0.0, end - vehicles.HALF_L[c.kind]), road["len"]), lane)
            pts.append((x, y))
        return pts

    def _paths_conflict(self, a, b):
        m = self.CLAIM_MARGIN
        for i in range(len(a) - 1):
            for j in range(len(b) - 1):
                if _seg_dist(a[i], a[i + 1], b[j], b[j + 1]) < m:
                    return True
        if len(a) == 1 or len(b) == 1:
            return any(math.hypot(p[0] - q[0], p[1] - q[1]) < m for p in a for q in b)
        return False

    def _review_turn(self, c, e, node, remaining):
        if c.nxt is None or c.stn is not None or remaining >= 22.0:
            return
        lanes = movement_lanes(self.w, (c.e, c.d), c.nxt, c.turn)
        wrong_lane = lanes is not None and c.lidx not in lanes and abs(self.lanes_of(e, c.d)[c.lidx] - c.lane) < 0.2
        before_line = remaining >= self._entry_line(c, node) - 0.4
        blocked = c.rerouted <= self.t and before_line and node in self.junctions and c.stuck > 7.0 and (c in self._blocked_exits or self._exit_blocked(c))
        if not (wrong_lane or blocked):
            return
        c.rerouted = self.t + 5.0
        result = self._choose(c, c.e, c.d)
        if result is None:
            return
        good, turns, _ = result
        alternatives = []
        previous, previous_turn, previous_path = c.nxt, c.turn, c.nx2
        for o, angle in zip(good, turns):
            valid = movement_lanes(self.w, (c.e, c.d), o, angle)
            if o != previous and abs(angle) <= self.UTURN and (valid is None or c.lidx in valid):
                c.nxt, c.turn, c.nx2 = o, angle, None
                if wrong_lane or not self._exit_blocked(c):
                    alternatives.append((o, angle))
        c.nxt, c.turn, c.nx2 = previous, previous_turn, previous_path
        if not alternatives:
            return
        if c.goal is not None and self._plan_trip(c, [o for o, _ in alternatives]):
            return
        if wrong_lane or blocked:
            c.nxt, c.turn = min(alternatives, key=lambda pair: (self.queue.get(pair[0], 0), abs(pair[1])))
            c.nx2 = None
            if blocked:
                c.goal = None                       # start a new trip if the old destination has no open route

    def _clear_blocked_corner(self, c, e, node):
        """A stopped car already in the junction may take a clear forward exit."""
        if c.nxt is None or abs(c.turn) < 0.5 or c.stuck < 1.5 or c.rerouted > self.t or c.stn is not None:
            return
        c.rerouted = self.t + 2.0
        incoming = (c.e, c.d)
        old = c.nxt, c.turn, c.nx2, c.lidx
        claim = self.exit_claims.get(c)
        for move in self.w.out.get(node, ()):
            angle = turn_angle(self.w.edges, incoming, move)
            if abs(angle) >= 0.35:
                continue
            lanes = movement_lanes(self.w, incoming, move, angle)
            if lanes is not None and c.lidx not in lanes:
                adjacent = [i for i in lanes if abs(i - c.lidx) == 1]
                if not adjacent or not self._lane_room(c, e, self.lanes_of(e, c.d)[adjacent[0]], 8.0, behind=4.0):
                    continue
                c.lidx = adjacent[0]
            road = self.w.edges[move[0]]
            c.nxt, c.turn, c.nx2 = move, angle, None
            lane = self.lanes_of(road, move[1])[self._exit_lane(c, e, road)]
            slots = self._exit_slots(c)
            plan, previous = [], move
            while not self._exit_complete(c, slots) and len(plan) < 3:
                segment = self.w.edges[previous[0]]
                end = segment["b" if previous[1] == 1 else "a"]
                ahead = [(nxt, turn_angle(self.w.edges, previous, nxt)) for nxt in self.w.out.get(end, ())
                         if nxt != incoming and nxt != move and all(nxt != planned for planned, _ in plan)]
                straight = [(nxt, bend) for nxt, bend in ahead
                            if abs(bend) < 0.35 and movement_lanes(self.w, previous, nxt, bend) != []]
                if not straight:
                    break
                previous, bend = min(straight, key=lambda item: abs(item[1]))
                plan.append((previous, bend))
                c.nx2 = plan
                slots = self._exit_slots(c)
            poses = [(*self._ref(road, move[1], min(road["len"], distance), lane), eta)
                     for distance, eta in ((1.0, 0.0), (4.0, 0.6), (7.0, 1.1))]
            if (self._exit_complete(c, slots) and not self._exit_blocked(c)
                    and self._red_rem(c, e["len"], self.signals) is None
                    and self._path_clear(c, poses, escaping=True)):
                occupied = {slot for other, (_, _, reserved, _) in self.exit_claims.items()
                            if other is not c and not any(slot[:2] == incoming for slot, _ in reserved)
                            for slot, _ in reserved}    # a following car's claim must let its leader leave first
                if all(slot not in occupied for slot, _ in slots):
                    if claim is not None:
                        self.exit_claims[c] = (claim[0], claim[1], slots, claim[3])
                    c.goal = None
                    return
            c.nxt, c.turn, c.nx2, c.lidx = old

    def _coordinate_jams(self, on_edge):
        """Use the shared traffic snapshot to free a usable lane or assign one driver to make room."""
        reversing = [(c.x, c.y) for c in self.cars if c.rev > 0 or c.turnaround]
        if self.LANE_PICK:
            for c in self.cars:
                if (c.nxt is None or c.rev or c.turnaround or c.stn is not None or c.shift or c.lcd > 0 or c.cool > 0
                        or c in self.exit_claims or c in self.narrow_wait or c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS)
                        or c.e in self.internal_links):
                    continue
                e = self.w.edges[c.e]
                node = e["b" if c.d == 1 else "a"]
                rem = e["len"] - c.s if c.d == 1 else c.s
                if rem < 16.0 or rem > 120.0 or (node in self.junctions and rem < self._entry_line(c, node) + 1.0):
                    continue
                lanes = self.lanes_of(e, c.d)
                if len(lanes) < 2:
                    continue
                cars_on = on_edge.get((c.e, c.d), ())

                def ahead(idx):
                    best = None
                    for o in cars_on:
                        if o is not c and o.lidx == idx:
                            ds = (o.s - c.s) * c.d
                            if 0.0 < ds < 50.0 and (best is None or ds < best[0]):
                                best = (ds, o.v)
                    return best
                own = ahead(c.lidx)
                eta = rem / max(c.v, 3.0)
                exit_blocked = node in self.junctions and self._exit_blocked(c, eta)
                queued = own is not None and own[1] < 2.0 and own[0] < 45.0
                if not (exit_blocked or queued):
                    continue
                permitted = movement_lanes(self.w, (c.e, c.d), c.nxt, c.turn)
                old = c.lidx
                best = None
                for idx in (old - 1, old + 1):
                    if not 0 <= idx < len(lanes) or (permitted is not None and idx not in permitted):
                        continue
                    other = ahead(idx)
                    free = 60.0 if other is None else other[0] + (8.0 * other[1] if other[1] > 2.0 else 0.0)
                    if other is not None and own is not None and free < own[0] + 14.0:
                        continue
                    if any(o is not c and o.lidx == idx and -7.0 < (o.s - c.s) * c.d < 0.0 for o in cars_on):
                        continue
                    c.lidx = idx
                    ok = (not (node in self.junctions and self._exit_blocked(c, eta))
                          and self._lane_room(c, e, lanes[idx], 15.0, behind=7.0))
                    c.lidx = old
                    if ok and (best is None or free > best[0]):
                        best = (free, idx)
                if best is not None:
                    c.lidx = best[1]
                    c.lcd = 2.5
        if self.YIELD_BACKOFF:
            for c in self.cars:                       # a priority car held up by a waiting car from another road: the waiter backs off
                lead = c.blk
                if (isinstance(lead, Car) and (lead.e, lead.d) != (c.e, c.d) and c.v < 0.6 and lead.v < 0.2
                        and lead.stuck >= 3.0 and lead.blk is None and lead.rev <= 0 and not lead.turnaround
                        and lead.cool <= 0 and lead.stn is None and lead.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS)
                        and not any((x - lead.x) ** 2 + (y - lead.y) ** 2 < 28.0 ** 2 for x, y in reversing)):
                    if self._retreat_in_box(lead) if lead in self.exit_claims else self._request_reverse(lead, lead.lane):
                        reversing.append((lead.x, lead.y))
        for c in self.cars:
            if c.stuck < 3.0 or c.v >= 0.35 or c.rev or c.turnaround or c.stn is not None or c.cool > 0:
                continue
            lead = c.blk
            if c not in self._blocked_exits and not (isinstance(lead, Car) and lead.stuck >= 3.0):
                continue
            e = self.w.edges[c.e]
            node = e["b" if c.d == 1 else "a"]
            rem = e["len"] - c.s
            red = self._red_rem(c, e["len"], self.signals)
            if (red is not None and 0.0 <= red < 18.0) or c in self.narrow_wait:
                continue
            trains = getattr(self.sim, "trains", None)
            if trains is not None and trains.closed and trains.stop_at(c.e, c.d, c.s, e["len"]) is not None:
                continue
            if c.nxt is not None and c not in self.exit_claims and self.t >= c.rerouted \
                    and rem > self._entry_line(c, node) + 5.0 and not c.shift:
                lanes = self.lanes_of(e, c.d)
                permitted = movement_lanes(self.w, (c.e, c.d), c.nxt, c.turn)
                for idx in (c.lidx - 1, c.lidx + 1):
                    if not 0 <= idx < len(lanes) or (permitted is not None and idx not in permitted):
                        continue
                    # The lane must be clear in both the road snapshot and the swept merge.
                    if any(o is not c and o.lidx == idx and -7.0 < o.s - c.s < 20.0
                           for o in on_edge.get((c.e, c.d), ())):
                        continue
                    old = c.lidx
                    c.lidx = idx
                    if not self._exit_blocked(c) and self._lane_room(c, e, lanes[idx], 15.0, behind=7.0):
                        c.rerouted, c.lcd = self.t + 4.0, 2.5
                        break
                    c.lidx = old
            if (not isinstance(lead, Car) or lead.stuck < 3.0 or lead.blk is not c
                    or c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or c.s < 7.0
                    or any((x - c.x) ** 2 + (y - c.y) ** 2 < 28.0 ** 2 for x, y in reversing)):
                continue
            if c in self.exit_claims or c.e in self.internal_links or rem < self._entry_line(c, node):
                if not self._retreat_in_box(c):
                    continue
            elif not self._request_reverse(c, c.lane):
                continue
            reversing.append((c.x, c.y))

    def _give_way(self, c, rem, me, ready):
        """Should car c wait at the line?  Major road before minor, then first come first served (one total order, so
        two cars never wait for each other); a car with green has priority over side streets without lights.  Oncoming
        traffic going straight or turning towards its own kerb does not cross.  Nor does it pull into a junction whose
        exit is blocked."""
        node, (key, _c, h1, _eta), lit = me
        eta = rem / max(c.v, 1.5)
        if self._exit_blocked(c, eta):
            if rem > self.junctions[node] + vehicles.HALF_L[c.kind]:
                return True                                   # hold outside the box if the far lane will still be occupied
            return False                                      # once committed to the box, clear it
        if rem < self._yield_line(c, node) - 0.2:
            return False                                      # already over the line
        e = self.w.edges[c.e]
        jx, jy = e["pts"][-1] if c.d == 1 else e["pts"][0]
        rj = self.junctions[node] + 6.0                        # use the same box from every approach
        for ix in range(int((jx - rj) // 16), int((jx + rj) // 16) + 1):
            for iy in range(int((jy - rj) // 16), int((jy + rj) // 16) + 1):
                for o in self.hash.get((ix, iy), ()):
                    ob = o[4]
                    if ob is c or o[5] is None or (o[0] - jx) ** 2 + (o[1] - jy) ** 2 > rj * rj:
                        continue
                    if o[6] is not None and abs(o[6] - c.gz) > 3.0:
                        continue
                    if isinstance(ob, Car):
                        if (ob.e == c.e and ob.d == c.d) or (c.nxt is not None and (ob.e, ob.d) == c.nxt):
                            continue                          # ahead of us on our way in or out: the lane scan follows it
                        oe = self.w.edges[ob.e]
                        if ob.nxt == (c.e, c.d) and math.cos(ob.h - c.h) > 0.7 and (
                                (ob.x - c.x) * math.cos(c.h) + (ob.y - c.y) * math.sin(c.h) < 0):
                            continue                          # our follower can be on the previous piece of a split approach
                        if oe["a" if ob.d == 1 else "b"] == node and ob.s - vehicles.HALF_L[ob.kind] > self.junctions[node]:
                            continue                          # the rear has already cleared this junction
                        if (ob.e not in self.internal_links and oe["b" if ob.d == 1 else "a"] == node
                                and oe["len"] - ob.s >= self._yield_line(ob, node) - 0.2):
                            continue                          # still on its own approach; priority is decided below
                        dh = abs((o[5] - h1 + math.pi) % (2 * math.pi) - math.pi)
                        if dh > 2.6 and c.turn > -0.5 and ob.turn > -0.5:
                            continue                          # oncoming, nobody turns across
                    return True                               # someone is still crossing the box: let it clear first
        for key2, o, h2, eta2 in self.appr.get(node, ()):
            if (o is c or (o.e == c.e and o.d == c.d) or o.blk is c or o in self.narrow_wait
                    or (o.v < 0.5 and o not in ready) or o in self._blocked_exits or self._exit_blocked(o, eta2)):
                continue                                      # (nor wait for a car that is not going to move soon)
            dh = abs(math.remainder(h2 - h1, math.tau))
            if dh > 2.6 and (c.turn < -0.5) != (o.turn < -0.5):
                if c.turn < -0.5 and (eta2 < 4.0 or o in ready):
                    return True
                continue
            if lit:                                           # green: only a turn across waits for oncoming traffic
                continue
            if key2 <= key:
                continue
            if eta2 > 4.0 and o.v > 1.0:
                continue                                      # far enough off: there is a gap to go
            if dh > 2.6 and c.turn > -0.5 and o.turn > -0.5:
                continue                                      # opposite directions, nobody turns across
            return True
        return False

    def _queue_pressure(self, move):
        """Standing cars per lane, with a memory that survives a brief burst of movement."""
        ei, direction = move
        return max(self.queue.get(move, 0), self.queue_history.get(move, 0.0)) / lane_count(self.w.edges[ei], direction)

    def _remember_queues(self, dt):
        decay = math.exp(-dt / 8.0)
        for move in self.queue_history.keys() | self.queue.keys():
            count = self.queue.get(move, 0)
            old = self.queue_history.get(move, 0.0)
            history = old * decay + count * (1.0 - decay)
            if history > 0.15:
                self.queue_history[move] = history
            else:
                self.queue_history.pop(move, None)

    def _review_route(self, c, e, rem):
        """Reconsider a congested route while there is still time to line up for the detour."""
        if not 25.0 < rem < 105.0 or c.nxt is None or c.stn is not None or c.rerouted > self.t:
            return
        if c.rev or c.shift or c.turnaround or c.kind in vehicles.HEAVY:
            return
        planned = [c.nxt] + [move for move, _ in (c.nx2 or ())[:1]]
        pressure = max(self.queue_history.get(move, 0.0) / lane_count(self.w.edges[move[0]], move[1]) for move in planned)
        if pressure < 1.6:
            return
        c.rerouted = self.t + self.rng.uniform(5.0, 9.0)
        result = self._choose(c, c.e, c.d)
        if result is None:
            return
        old = c.nxt
        moves, turns, _ = result
        options = [(move, angle) for move, angle in zip(moves, turns)
                   if abs(angle) <= self.UTURN and self.w.edges[move[0]]["cls"] != "service"
                   and turn_lanes(e, c.d, angle) != []]
        if not any(move != old for move, _ in options):
            return
        if c.goal is not None:
            self._plan_trip(c, [move for move, _ in options])
        else:
            def cost(option):
                move, angle = option
                road = self.w.edges[move[0]]
                arrivals = self.route_demand.get(move, 0) - int(move == old)
                queued_ahead = 3.0 * max(0.0, pressure - self._queue_pressure(old)) if move == old else 0.0
                return (4.0 * self._queue_pressure(move) + 1.6 * max(0, arrivals) / lane_count(road, move[1])
                        + abs(angle) * 2.0 + queued_ahead)

            best = min(options, key=cost)
            if best[0] != old and cost(best) + 2.0 < cost((old, c.turn)):
                c.nxt, c.turn = best
                c.nx2 = None
        if old != c.nxt:
            self.route_demand[old] = max(0, self.route_demand.get(old, 0) - 1)
            self.route_demand[c.nxt] = self.route_demand.get(c.nxt, 0) + 1

    @staticmethod
    def _single_file_width(e):
        if e["ow"] or lane_count(e, 1) != 1 or lane_count(e, -1) != 1:
            return math.inf
        return 2 * min(half_width(e, s) for s in (0.0, e["len"] * 0.5, e["len"]))

    def _entry_line(self, c, node):
        return self._yield_line(c, node) if node in self.junctions else min(
            self.w.edges[c.e]["len"] * 0.7, max(4.0, vehicles.HALF_L[c.kind] + 1.5))

    def _coordinate_narrow_roads(self, occupants):
        """Hold arrivals outside a single-file road and give waiting traffic a turn when it drains."""
        waiting, arrivals, held = {}, {}, set()
        for c in self.cars:
            if c.nxt is None or c.nxt[0] == c.e or c.nxt[0] not in self.single_file:
                continue
            e = self.w.edges[c.e]
            node = e["b" if c.d == 1 else "a"]
            rem = e["len"] - c.s
            line = self._entry_line(c, node)
            if rem > line + max(12.0, c.v * c.v / 7.0 + 3.0):
                continue
            if rem < line - 0.2:
                occupants.setdefault(c.nxt[0], []).append((c.nxt[1], c))
                continue
            red = self._red_rem(c, e["len"], self.signals)
            if red is not None and -2.5 < red < rem:
                continue
            arrived = arrivals[c] = self.narrow_arrivals.get(c, self.t)
            waiting.setdefault(c.nxt[0], []).append((arrived, rem - line, self._order[c], c))
        for ei, requests in waiting.items():
            requests.sort(key=lambda request: request[:3])
            oldest = requests[0][3].nxt[1]
            present = occupants.get(ei, ())
            approaching = [(c.nxt[1], c) for _, _, _, c in requests]
            widths = {}
            for direction, c in [*present, *approaching]:
                widths[direction] = max(widths.get(direction, 0.0), 2 * vehicles.HALF_W[c.kind])
            if len(widths) < 2 or sum(widths.values()) + 0.85 <= self.single_file[ei]:
                continue
            directions = {direction for direction, _ in present}
            if directions and directions != {oldest}:
                held.update(request[3] for request in requests)
            else:
                held.update(request[3] for request in requests if request[3].nxt[1] != oldest)
        self.narrow_arrivals, self.narrow_wait = arrivals, held

    def _pick_pullout(self, a, b, e, gap):
        """Find the closest reachable widening where the yielding driver can fit beside the through lane."""
        choices = []
        for c, other in ((a, b), (b, a)):
            hl, hw = vehicles.HALF_L[c.kind], vehicles.HALF_W[c.kind]
            room = hl + vehicles.HALF_L[other.kind] + 3.0
            for distance in range(4, min(23, int(gap - room)), 2):
                s = c.s + distance
                if s > e["len"] - hl - 1.0:
                    break
                along = s if c.d == 1 else e["len"] - s
                half = min(half_width(e, along - hl), half_width(e, along + hl))
                if half * 2 < (hw + vehicles.HALF_W[other.kind]) * 2 + 0.65:
                    continue
                off = e["w"] * 0.5 * (1.0 - (hw + 0.18) / half)
                pose = self._ref(e, c.d, s, off)
                opposite = self._ref(e, other.d, e["len"] - s, self.lanes_of(e, other.d)[0])
                lateral = math.dist(pose[:2], opposite[:2])
                if lateral > hw + vehicles.HALF_W[other.kind] + 0.35 and self._path_clear(c, [(*pose, 0.0)]) \
                        and self._path_clear(other, [(*opposite, 0.0)]):
                    choices.append((distance, self._order[c], other, c, s, off))
                    break
        return min(choices, key=lambda choice: choice[:2])[2:] if choices else None

    def _coordinate_pullouts(self, narrow_cars):
        for ei, (winner, yielder, _, _, deadline) in list(self.passing.items()):
            edge = self.w.edges[ei]
            gap = edge["len"] - winner.s - yielder.s
            if (winner not in self._order or yielder not in self._order or winner.e != ei or yielder.e != ei
                    or winner.d == yielder.d or gap < -vehicles.HALF_L[winner.kind] - vehicles.HALF_L[yielder.kind] - 1.0
                    or self.t > deadline):
                del self.passing[ei]
                yielder.shift_t = max(yielder.shift_t, 1.5)
        for ei, cars in narrow_cars.items():
            if ei in self.passing:
                continue
            e = self.w.edges[ei]
            east = sorted((c for c in cars if c.d == 1), key=lambda c: -c.s)
            west = [c for c in cars if c.d == -1]
            for a in east:
                b = max((b for b in west if 12.0 < e["len"] - a.s - b.s <= 42.0), key=lambda b: b.s, default=None)
                if b is None or a.shift or b.shift or a.rev or b.rev or a.turnaround or b.turnaround:
                    continue
                gap = e["len"] - a.s - b.s
                width = 2 * (vehicles.HALF_W[a.kind] + vehicles.HALF_W[b.kind]) + 0.85
                if self.single_file[ei] >= width and all(self._path_clear(c,
                        [(*self._ref(e, c.d, c.s + gap * f, c.lane), 0.0) for f in (0.25, 0.5, 0.75)],
                        parked_only=True) for c in (a, b)):
                    continue
                plan = self._pick_pullout(a, b, e, gap)
                if plan is not None:
                    self.passing[ei] = (*plan, self.t + 18.0)
                    break

    def _pullout_stop(self, c, e):
        plan = self.passing.get(c.e)
        if plan is None:
            return None
        winner, yielder, s, off, _ = plan
        if c not in (winner, yielder):
            return None
        if c is yielder:
            c.shift = off - c.lane
            c.man = max(c.man, 1.0)
            return s - c.s
        tx, ty, _ = self._ref(e, yielder.d, yielder.s, off)
        if yielder.s >= s - 1.0 and math.hypot(yielder.x - tx, yielder.y - ty) < 0.45:
            return None
        return e["len"] - s - c.s - vehicles.HALF_L[c.kind] - vehicles.HALF_L[yielder.kind] - 2.0

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
        speed = -2.2 if c.rev > 0.0 else c.v
        b.vx, b.vy = math.cos(c.h) * speed, math.sin(c.h) * speed
        b.az = c.gz
        b.health = c.health
        b.trh, b.tra = c.trh, c.tra                    # a hijacked semi keeps its trailer's angle
        return b

    def update(self, dt, fx, fy, bodies, peds, walker=None):
        w, rng = self.w, self.rng
        if self.audit_stops is not None:
            self.audit_stops.clear()
        h = {}
        for c in self.cars:
            if c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS):
                for x_, y_, h_, l_, w_ in parts(c):
                    h.setdefault((int(x_ // 16), int(y_ // 16)), []).append((x_, y_, w_, l_, c, h_, c.gz))
                continue
            h.setdefault((int(c.x // 16), int(c.y // 16)), []).append((c.x, c.y, vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind], c, c.h, c.gz))
        ph, ems = {}, []                                      # kerb-parked cars (for swerving) and emergency vehicles
        for b in bodies:
            if b.speed < 0.3 and not b.air:                     # standing cars (parked, wrecks, abandoned): drive round them
                for x_, y_, h_, l_, w_ in parts(b):
                    ph.setdefault((int(x_ // 16), int(y_ // 16)), []).append((x_, y_, w_, l_, h_, b.az))
                continue
            if b.service and not b.out:
                ems.append(b)
            for x_, y_, h_, l_, w_ in parts(b):
                h.setdefault((int(x_ // 16), int(y_ // 16)), []).append((x_, y_, w_, l_, b, h_, b.az))
        for p in peds:
            if p.mode in TRAFFIC_PED_MODES:
                h.setdefault((int(p.x // 16), int(p.y // 16)), []).append((p.x, p.y, _PED_R(p), 0.3, p, None, p.gz))
        if walker is not None and walker.health > 0:          # traffic brakes for the player on foot too
            h.setdefault((int(walker.x // 16), int(walker.y // 16)), []).append((walker.x, walker.y, 0.38, 0.3, walker, None, walker.az))
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
        occ, queue, appr, mine, on_edge, narrow_cars, narrow_occupants = {}, {}, {}, {}, {}, {}, {}
        for i, c in enumerate(self.cars):                      # who is where: junction exits, queues, junction approaches
            e = w.edges[c.e]
            if c.e in self.single_file:
                narrow_cars.setdefault(c.e, []).append(c)
                narrow_occupants.setdefault(c.e, []).append((c.d, c))
            k = (c.e, c.d)
            on_edge.setdefault(k, []).append(c)
            lk = (*k, c.lidx)
            rear = c.s - vehicles.HALF_L[c.kind]
            occ.setdefault(lk, []).append((rear, c.v, c.v >= 1.5 and c.blk is None))
            if c.v < 0.5:
                queue[k] = queue.get(k, 0) + 1
            rem = e["len"] - c.s
            node = e["b"] if c.d == 1 else e["a"]
            if (c.e not in self.internal_links and node in self.junctions
                    and rem < max(self.APPR, self._yield_line(c, node) + c.v * c.v / 7.0 + 6.0 + self.CLAIM_LEAD * c.v)):
                lit = sg is not None and (c.e, 1 if c.d == 1 else 0) in sg.by_edge
                if lit and sg.stop_for(c.e, 1 if c.d == 1 else 0):
                    continue                                  # waiting at red: no claim on the junction
                if c.arr is None:
                    c.arr = self.t
                eta = rem / max(c.v, 1.0)
                rank = 10 if lit else _rank(e["cls"]) + min(10, int((self.t - c.arr) / 2.5))
                q = ((rank, -c.arr, -rem, -i), c, self._head(e, c.d, True), eta)
                appr.setdefault(node, []).append(q)
                mine[c] = (node, q, lit)
        for vehicles_on_lane in occ.values():
            vehicles_on_lane.sort(key=lambda vehicle: vehicle[0])
        self.occ, self.queue, self.appr, self._mine = occ, queue, appr, mine
        self._order = {c: i for i, c in enumerate(self.cars)}
        self._tick += 1
        tick = self._tick
        self.route_demand = {}
        for c in self.cars:
            if c.nxt is not None and w.edges[c.e]["len"] - c.s < self.PLAN_M:
                self.route_demand[c.nxt] = self.route_demand.get(c.nxt, 0) + 1
        for ci, c in enumerate(self.cars):
            if c.turnaround is not None:
                continue
            e = w.edges[c.e]
            rem = e["len"] - c.s
            if c.nxt is None and rem < self.PLAN_M:
                self._pick(c)
                if c.nxt is not None:
                    self.route_demand[c.nxt] = self.route_demand.get(c.nxt, 0) + 1
            if (tick + ci) % 15 == 0:
                self._review_route(c, e, rem)
            node = e["b" if c.d == 1 else "a"]
            if c.nxt is not None and abs(c.turn) > self.UTURN and self._major_junction(node):
                c.nxt, c.nx2 = None, None
                self._pick(c)
            if c.e in self.internal_links or self._carrying_exit(c):
                self._clear_blocked_corner(c, e, node)
            else:
                self._review_turn(c, e, node, rem)
        self._coordinate_narrow_roads(narrow_occupants)
        self._coordinate_pullouts(narrow_cars)
        self._coordinate_jams(on_edge)
        self._reserve_exits(mine)
        retreating = {self.internal_links.get(c.e) for c in self.cars if c.rev_box}
        keep = []
        dt0 = dt
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
            c.cool = max(0.0, c.cool - dt)
            c.honk_t = max(0.0, c.honk_t - dt)
            c.indicator_t = max(0.0, c.indicator_t - dt)
            if c.turnaround is not None:
                c.indicator = -1
                self._advance_turnaround(c, e, dt)
                keep.append(c)
                continue
            planned_signal = 0
            if c.nxt is not None:
                angle = c.turn
                if abs(angle) > self.UTURN:
                    angle = -abs(angle)
                elif angle > 0.20 and w.edges[c.nxt[0]]["cls"].endswith("_link"):
                    angle = max(0.5, angle)
                planned_signal = turn_indicator(angle, L - c.s, c.v)
            c.indicator = planned_signal or (c.indicator if c.indicator_t else 0)
            vmax = min(e["speed"] * min(c.pace, TRAFFIC_SPEED_FACTOR), vehicles.PERF[c.kind][0] * 0.9, vehicles.MAX_ROAD_SPEED * 0.9)
            if w.hilly:                                           # engines labour uphill, brakes hold downhill
                sl = c.pitch
                vmax *= max(0.4, 1.0 - 4.5 * sl) if sl > 0 else 1.0
            end_node = e["b"] if c.d == 1 else e["a"]
            if e["ow"] and not w.out.get(end_node) and L - c.s < self.APPR:
                if self._d2(c.x, c.y, fx, fy) > 90 ** 2:
                    self.despawned += 1
                    continue
                vmax = min(vmax, math.sqrt(7.0 * max(0.0, L - c.s - vehicles.HALF_L[c.kind] - 1.0)))
            vcorner = 2.5
            if c.nxt is not None:
                next_speed = w.edges[c.nxt[0]]["speed"] * TRAFFIC_SPEED_FACTOR
                t = abs(c.turn)
                turn_speed = 5.7 if t < 0.9 else 4.4 if t < 1.6 else 3.0
                if vehicles.LARGE[c.kind]:
                    turn_speed = min(turn_speed, 3.8)
                through = 15.0 if c in self.exit_claims else 12.0           # straight on with the way granted: momentum is kept
                vcorner = (min(next_speed, through) if end_node in self.junctions else next_speed) if t < 0.35 else min(next_speed, turn_speed)
            uturn = c.nxt is not None and abs(c.turn) > self.UTURN
            vlim = min(vmax, brake_speed(L - c.s - (8.0 if uturn else 1.5), 3.5, vcorner))
            stop = self._pullout_stop(c, e)
            carried = c.e in self.internal_links or self._carrying_exit(c)
            if sg is not None and c.nxt is not None and abs(c.turn) < 0.35 and c not in self.narrow_wait:
                # A stop plane can lie upstream of the entire signal edge. Entering
                # that edge already crossed the line, so keep clearing the box.
                carried = carried or sg.stopd.get((c.e, int(c.d == 1)), 0.0) >= L
            if not carried and (c in self.narrow_wait or (c in mine and L - c.s >= self._yield_line(c, end_node) - 0.2
                    and c not in self.exit_claims)):
                line_gap = L - c.s - self._entry_line(c, end_node)
                stop = line_gap if stop is None else min(stop, line_gap)
            if stop is not None:
                vlim = min(vlim, brake_speed(stop, 3.5))
            red_rem = self._red_rem(c, L, sg)
            if red_rem is not None and -2.5 < red_rem < 45.0:
                vlim = min(vlim, math.sqrt(2 * 2.6 * max(red_rem, 0.0)))
                stop = red_rem if stop is None else min(stop, red_rem)
            wb = vehicles.SEMI_WB if c.kind == vehicles.SEMI else vehicles.DIMS[c.kind][0] * 0.6
            if c.kind == vehicles.ARTIC_BUS:
                wb = vehicles.ARTIC_WB
            previous_speed = c.v
            at_red = False
            hold_at = None
            if c.nxt is not None and abs(c.turn) > self.UTURN and L - c.s < 40.0:
                hold_at = self._uturn_hold(c, e, L - c.s)
                if hold_at is not None:
                    vlim, at_red = min(vlim, math.sqrt(2 * 3.5 * max(hold_at, 0.0))), True
            if (red_rem is not None and -2.5 < red_rem < 150.0) or stop is not None:
                at_red = True                                      # queueing for a red light / giving way is not a jam to escape
            tr = getattr(self.sim, "trains", None)
            rail_stop = None
            if tr is not None and tr.closed:
                a = tr.stop_at(c.e, c.d, c.s, L)
                if a is not None:                                  # barriers down: wait for the train
                    rail_stop = a
                    vlim, at_red = min(vlim, brake_speed(a - vehicles.HALF_L[c.kind] - 0.5, 3.5)), True
            if at_red and (not c.rev_box or red_rem is not None or rail_stop is not None or hold_at is not None):
                c.rev = 0.0
                c.rev_box = False
            if c.nxt is not None and L - c.s < 120.0 and c.rev <= 0 and not c.shift:
                self._lane_for_turn(c, e, L - c.s, dt)
            remaining = L - c.s
            lane_stop = None
            if c.nxt is not None and not carried and remaining < 25.0:
                lanes = movement_lanes(w, (c.e, c.d), c.nxt, c.turn)
                if lanes is not None and not any(abs(c.lane - lane) < 0.4
                                                for i, lane in enumerate(self.lanes_of(e, c.d)) if i in lanes):
                    lane_stop = remaining - 1.0
                    stop = lane_stop if stop is None else min(stop, lane_stop)
                    vlim = min(vlim, 3.2, brake_speed(stop, 3.5))
            if uturn and 0.0 < remaining < 12.0 and not at_red and stop is None:
                started = self._junction_turnaround(c, e, wb, remaining)
                if started:
                    c.indicator = -1
                    self._advance_turnaround(c, e, dt)
                    keep.append(c)
                    continue
                if started is None:
                    stop, vlim, at_red = 0.0, 0.0, True
                if remaining < 5.0:
                    c.man = max(c.man, 2.0)
            traffic_limit = vlim
            vlim, bgap = self._courtesy(c, e, vlim, ems, ph, dt)
            self.lead = None
            turn_in_box = c.nxt is not None and abs(c.turn) > 0.4 and L - c.s < 10.0 and stop is None
            follow_route = carried or turn_in_box or (c in self.exit_claims and stop is None and L - c.s < 10.0)
            scan_h, scan_dist = None, 10.0 + c.v * 3.0
            if turn_in_box:
                ax, ay, _ = (self._corner_target(c, e, 4.0) if c.nxt[0] != c.e
                             else self._target(c, e, max(4.0, L - c.s + 2.0)))
                arc = math.remainder(math.atan2(ay - c.y, ax - c.x) - c.h, math.tau)
                scan_h, scan_dist = c.h + max(-0.65, min(0.65, arc)), min(scan_dist, 9.0)
            gap = self.scan(c, scan_dist, heading=scan_h, include_cars=not follow_route) if c.ghost <= 0 else None
            lead = self.lead[4] if gap is not None and self.lead is not None else None
            if follow_route and c.ghost <= 0:
                route_gap, route_lead = self._route_gap(c, e, max(scan_dist, 12.0), on_edge)
                if route_gap is not None and (gap is None or route_gap < gap):
                    gap, lead = route_gap, route_lead
            if bgap is not None and (gap is None or bgap < gap):
                gap, lead = bgap, None                           # a standing car it can't get round counts as a blocker
            c.blk = lead if gap is not None and gap < 3.0 else None
            if c.stn is not None and self.stn is not None:
                vlim, waiting = self.stn.drive(c, e, vlim, dt)
                if waiting:
                    at_red, c.stuck = True, 0.0                       # standing at the pumps is not a jam
            if (bgap is not None and lead is None and red_rem is not None and red_rem > 20.0
                    and stop in (None, red_rem) and rail_stop is None and hold_at is None and c.stn is None):
                at_red = False                                     # pass a parked obstruction well upstream of the stop line
            if not at_red:
                self._untangle(c, e, gap, lead, dt, wb)
            elif c.e not in self.passing and c.shift and not e["ow"] and c.lane + c.shift < lane_bounds(e, c.d)[0]:
                self._restore_lane(c, e, dt)
            if c.turnaround is not None:
                c.indicator = -1
                self._advance_turnaround(c, e, dt)
                keep.append(c)
                continue
            if bgap is not None and c.stuck > 2.0 and abs(c.avoid) > 0.3 and not at_red:
                c.man = max(c.man, 2.5)
            recovering = c.kind not in (vehicles.SEMI, vehicles.ARTIC_BUS) and (c.shift or c.man > 0 or (c.stuck > 2.0 and abs(c.avoid) > 0.3))
            tight = recovering and not at_red and (lead is None or isinstance(lead, (Car, Body)))
            la = (2.2 if c.man > 0 else 3.0) + c.v * 0.55
            if not recovering and abs(c.lane - self.lanes_of(e, c.d)[c.lidx]) > 0.05:
                la += 2.0
            if uturn and 3.0 < remaining < 12.0 and not recovering:
                tx, ty, _th = self._ref(e, c.d, min(L, c.s + la), c.lane)
            elif turn_in_box and c.nxt[0] != c.e and L - c.s < max(6.0, la + 2.0):
                tx, ty, _th = self._corner_target(c, e, la)
            else:
                tx, ty, _th = self._target(c, e, la)
            err = (math.atan2(ty - c.y, tx - c.x) - c.h + math.pi) % (2 * math.pi) - math.pi
            vlim = min(vlim, max(2.0, math.sqrt(3.0 * la / max(2.0 * math.sin(min(abs(err), 1.5708)), 0.02))))
            if tight and abs(c.yld) < 0.1:
                vlim = min(traffic_limit, 1.65 if gap is not None and gap < 5.0 else self.SQUEEZE_V)
            borrowed = c.shift and not e["ow"] and c.lane + c.shift < lane_bounds(e, c.d)[0]
            if borrowed:
                vlim = min(vlim, brake_speed(L - c.s - self.APPR * 0.5, 3.5))
            if c.rev > 0:
                vlim = 0.0
            lv = 0.0
            if c.rev <= 0 and gap is not None:
                if isinstance(lead, Car):
                    lv = (-2.2 if lead.rev > 0 else lead.v) * (1.0 if follow_route else math.cos(lead.h - c.h))
                    lv *= 0.6 if lv > 0.0 and lead.braking else 1.0
                elif isinstance(lead, Body):
                    lv = lead.vx * math.cos(c.h) + lead.vy * math.sin(c.h)
                if not tight:
                    vlim = min(vlim, follow_speed(gap, max(0.0, lv)), max(0.0, brake_speed(gap - 1.4, 4.0) + min(0.0, lv)))
            ped_gap = self._ped_gap(c) if c.ghost <= 0 else None
            if ped_gap is not None:
                vlim = min(vlim, brake_speed(ped_gap - 0.55, 3.0))
            cg = self._cross(c) if c.ghost <= 0 and c.v > 0.5 else None
            if cg is not None:                                     # someone will cut across our path: let them by
                vlim = min(vlim, max(0.0, (cg - 1.5) * 0.7))
            if c.v < vlim:
                entry_boost = 1.2 if follow_route and not at_red else 1.0
                c.v = min(vlim, c.v + entry_boost * min(3.2, vehicles.PERF[c.kind][1] * 0.4) * dt)
            else:
                c.v = max(vlim, c.v - self.BRAKE_DECEL * dt)
            if gap is not None and c.rev <= 0 and not tight:
                # If a blocker cuts in within braking distance, never integrate through its bumper.
                c.v = min(c.v, max(0.0, gap - 0.4 + lv * dt) / dt)
            if stop is not None:
                c.v = min(c.v, max(0.0, stop) / dt)
            c.braking = c.v < previous_speed - 0.25 * dt
            if c.v < 0.2:
                c.stuck += dt
            elif c.v > 1.0:                                       # creeping a metre at a time is still being stuck
                c.stuck = 0.0
            if c.stuck > 5.0 and c.v < 0.5 and not at_red:
                d2 = self._d2(c.x, c.y, fx, fy)
                if d2 > 150 ** 2 and c.stuck > 8.0 and _lod_far(self, c.x, c.y, d2):
                    self.despawned += 1                           # hopelessly stuck out of sight: gone, a new car comes
                    continue
            if c.man > 0:
                c.man -= dt
            if c.ghost > 0:
                c.ghost -= dt
                if c.ghost <= 0 and (self.scan(c, 1.0, back=-vehicles.HALF_L[c.kind]) or 0.0) < 0.0:
                    c.ghost = 0.5                                 # still inside another car: slip on until clear
            if c.rev > 0 and not c.rev_box and abs((c.h - _th + math.pi) % (2 * math.pi) - math.pi) > 1.3:
                c.rev, c.rside, c.cool = 0.0, 0.0, 2.0           # facing across / against the road (mid U-turn): backing up would run it off its lane
            blocked_step = False
            if c.rev > 0:
                self._back_up(c, e, wb, dt)
            else:
                lock = self.LOCK_WAY if c.man > 0 else self.LOCK_MAN if (c.shift or abs(c.avoid) > 0.3 or c.cool > 0) else 0.55
                if c.kind == vehicles.ARTIC_BUS:
                    lock = articulated_steer_limit(c.v)
                radius_factor = turn_radius_factor(c.v, c.kind)
                gain = 0.75 * (0.9 if vehicles.STYLE[c.kind] == "bus" else 1.0)
                want = max(-lock, min(lock, math.atan2(2.0 * wb * gain * math.sin(max(-1.5708, min(1.5708, err))), la)))
                steering = c.str + (want - c.str) * min(1.0, dt * (9.0 if c.man > 0 else 5.0))
                heading = c.h + c.v * math.tan(steering) / (wb * radius_factor) * dt
                arm = -pivot_x(c.kind) / wb               # the car's centre slips sideways by this much of the steer: its distance ahead of the rear axle
                slip = math.atan(arm * math.tan(steering))
                x = c.x + math.cos(heading + slip) * c.v * dt
                y = c.y + math.sin(heading + slip) * c.v * dt
                check_turn = c.ghost <= 0 and (c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS) or c.lcd > 0)
                if (follow_route or recovering or check_turn or (isinstance(lead, Car) and (lead.rev > 0 or lead.turnaround))) and c.v > 0 \
                        and not self._step_clear(c, x, y, heading):
                    blocker = self.step_blocker
                    alternatives = (steering * 0.5, 0.0, -steering * 0.5) if c.e in self.internal_links else (steering * 0.5, 0.0)
                    for alternative in alternatives if follow_route and abs(steering) > 0.12 and c.v < 1.4 else ():
                        h2 = c.h + c.v * math.tan(alternative) / (wb * radius_factor) * dt
                        slip2 = math.atan(arm * math.tan(alternative))
                        x2, y2 = c.x + math.cos(h2 + slip2) * c.v * dt, c.y + math.sin(h2 + slip2) * c.v * dt
                        if self._step_clear(c, x2, y2, h2):
                            x, y, heading, steering = x2, y2, h2, alternative
                            break
                    else:
                        blocked_step = True
                        if isinstance(blocker, Car):
                            c.blk = blocker
                        x, y, heading = c.x, c.y, c.h
                        c.v, c.braking = 0.0, True
                        c.stuck += dt
                        group = self.internal_links.get(c.e)
                        if (group is not None and group not in retreating and not at_red and c.cool <= 0.0
                                and c.stuck >= 2.2 and self._retreat_in_box(c)):
                            retreating.add(group)
                road_h = self._ref(e, c.d, c.s, 0.0)[2]
                c.s += max(0.0, (x - c.x) * math.cos(road_h) + (y - c.y) * math.sin(road_h))
                if L - c.s < 10.0:                                  # a car swinging round a tight corner is turned away from the road by the time it is
                    ex_, ey_, eh_ = self._ref(e, c.d, L, 0.0)       # level with the junction: count how far it really is (else it circles for its
                    c.s = max(c.s, L - ((ex_ - x) * math.cos(eh_) + (ey_ - y) * math.sin(eh_)))
                    if turn_in_box and stop is None and c.v > 0.0 and (c.nxt[0] != c.e or uturn):
                        target_edge = w.edges[c.nxt[0]]
                        tx_, ty_, th_ = self._ref(target_edge, c.nxt[1], 0.0, 0.0)
                        advance = (x - tx_) * math.cos(th_) + (y - ty_) * math.sin(th_)
                        lateral = abs((tx_ - x) * math.sin(th_) + (y - ty_) * math.cos(th_))
                        if (0.25 < advance < 12.0 and lateral < target_edge["w"] * 0.65
                                and math.cos(heading - th_) > max(0.5, math.cos(heading - road_h))):
                            c.s = max(c.s, L + min(advance, target_edge["len"] * 0.75))
                if c.s >= L:
                    c.s -= L
                    if not self._next_edge(c):                   # dead end: U-turn instead of vanishing
                        if e["ow"] or self._major_junction(end_node):  # no legal reverse movement
                            c.s, c.v = L, 0.0
                            keep.append(c)
                            continue
                        c.d, c.v = -c.d, 0.0
                    e = w.edges[c.e]
                # pure pursuit with a bicycle model: steer for a point ahead on the lane, limited front-wheel angle and
                # rate, so cars swing round bends and into other lanes along believable arcs instead of sliding
                c.x, c.y, c.h, c.str = x, y, heading, steering
                rx_, ry_, _rh = self._ref(e, c.d, c.s, c.lane + c.shift + c.avoid + c.yld)
                if (rx_ - c.x) ** 2 + (ry_ - c.y) ** 2 > 400.0 and (c.ghost > 0 or (self.scan(c, 0.5, rx_ - c.x, ry_ - c.y, back=-vehicles.HALF_L[c.kind]) or 1.0) >= 0.0):
                    c.x, c.y, c.h = rx_, ry_, _rh                   # lost (a 20 m detour is fine round corners) (spawned, or pushed): put it back, unless another car is there
            if self.audit_stops is not None and c.v < 0.45 and c.rev <= 0:
                if red_rem is not None and -2.5 < red_rem < 1.5:
                    why = "signal"
                elif rail_stop is not None:
                    why = "rail"
                elif c.stn is not None and c.dwell is not None:
                    why = "station"
                elif lane_stop is not None and lane_stop < 1.5:
                    why = "lane alignment"
                elif stop is not None and stop < 1.5:
                    why = "pullout" if c.e in self.passing else "single-file" if c in self.narrow_wait else "reservation"
                elif hold_at is not None:
                    why = "u-turn"
                elif ped_gap is not None and ped_gap < 1.8:
                    why = "pedestrian"
                elif gap is not None and gap < 3.0:
                    why = "parked" if lead is None else type(lead).__name__
                elif cg is not None:
                    why = "crossing"
                elif borrowed:
                    why = "borrowed lane"
                elif blocked_step:
                    why = "clearance"
                elif e["ow"] and not w.out.get(end_node):
                    why = "dead-end"
                else:
                    why = "open lane"
                self.audit_stops[c] = why
            lv = w.level
            wy_ = 1e9 if e["bridge"] else c.gz - c.goff           # off a bridge its own height decides: a link joining a deck end drives up onto
            c.gz = lv(c.x, c.y, wy_)                              # the deck where it is drawn over the link, a street underneath stays below
            if c.kind in (vehicles.SEMI, vehicles.ARTIC_BUS):
                tow(c)
            if (w.hilly or e["bridge"]) and ((ci + tick) & 1 == 0 or dt != dt0):      # tilt and ride height follow the ground: every other frame is plenty
                g_ = ride(c, lambda x_, y_: lv(x_, y_, wy_), c.x, c.y, c.h, dt, 8.0 if dt != dt0 else 16.0)
                c.goff = max(0.0, g_ - c.gz)
            c.gz += c.goff
            keep.append(c)
        self.cars = [c for c in keep if self._d2(c.x, c.y, fx, fy) < 460 ** 2
                     or not _lod_far(self, c.x, c.y, self._d2(c.x, c.y, fx, fy))]
        dt = dt0
        self._jam_t += dt
        if self._jam_t >= 1.0:
            self._track_jams(self._jam_t)
            self._remember_queues(self._jam_t)
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
        self.lane_assist, self.lane_assist_on = LaneAssist(), True
        self.parked = {}
        self.gone = set()
        self.stats = {"peds": 0, "burek": 0, "stolen": 0, "deaths": 0, "boom": 0, "ajvar": 0}
        self.safe = (sx, sy, sh)
        self.safe_z = None
        self.respawn_t = 0.0
        self.pickups = []
        self.money = DEFAULT_STARTING_CASH
        self.jack = None                     # carjack in progress (see _start_jack)
        self.esc = None                      # fire-escape ride in progress (escride.py)
        self.esc_prompt = ""
        self.riding = None                   # the city bus you ride as a passenger (Ctrl takes it over)
        self.train_ride = None               # the trains.Train you ride on foot (F at a station boards / gets off)
        self.shots = projectiles.Projectiles(self)
        import chaos
        self.chaos = chaos.Chaos(self)       # breakable props, blast waves, chain fires
        self.traffic.sim = self
        import stations
        import garbage
        if getattr(world, "garbage_sites", None) is None:
            world.garbage_sites = garbage.make_sites(world)          # waste containers along the kerbs (and the trucks' stops at them)
        self.stations = self.traffic.stn = stations.Stations(self)
        self.garbage = garbage.Garbage(self, world.garbage_sites)
        self.clock = clock.GameClock(17.0)
        self.base_cars, self.base_peds = n_cars, n_peds
        self._cull_t = 0.0
        self.kiosks = []                  # (x, y, heading)
        self._make_pickups()
        self._make_kiosks()
        self._make_helis()
        for _ in range(n_cars * 6):
            if len(self.traffic.cars) < n_cars:
                self.traffic.spawn(sx, sy, 60, 330)
        for _ in range(n_peds * 6):
            if len(self.peds.list) < n_peds:
                self.peds.spawn(sx, sy)

    def _make_helis(self):
        """One medical helicopter on each hospital helipad (works for the OSM and the photogrammetric world alike)."""
        import geo
        self.helipads = []
        self.heli_stairs = []
        for lat, lon, _n in HELI_PADS:
            x, y = geo.project(lat, lon)
            if abs(x) > self.w.hx - 30 or abs(y) > self.w.hy - 30:
                continue
            hit = _bld_at(self.w, x, y)                        # inside a hospital footprint: the pad is on its roof, on a raised deck
            g = self.w.ground_y(x, y)
            roof = hit is not None and hit[1] > g + 1.0
            z = hit[1] + 0.5 if roof else g
            if roof:                                          # clear of every roof polygon under the deck (relief, parapets, ridges)
                mt = _mesh_top(self.w, x, y, 8.6, hit[1] + 9.0)
                if mt is not None and mt + 0.4 > z:
                    z = mt + 0.4
                elif mt is None:                              # no roof mesh to measure: stand well clear of any roof shape
                    z = hit[1] + 2.5
            self.helipads.append((x, y, z, hit[1] if roof else None))
            surface = z + 0.18                                # top of the H marking in render.py; solid for landing and feet
            pad = [(x + 8.0 * math.cos(i * math.tau / 28), y + 8.0 * math.sin(i * math.tau / 28)) for i in range(28)]
            _pg2_add(self.w, (1, pad, surface, (x - 8, y - 8, x + 8, y + 8)), x - 8, y - 8, x + 8, y + 8)
            if roof:
                deck = [(x - 8.5, y - 8.5), (x + 8.5, y - 8.5), (x + 8.5, y + 8.5), (x - 8.5, y + 8.5)]
                _pg2_add(self.w, (1, deck, z, (x - 8.5, y - 8.5, x + 8.5, y + 8.5)), x - 8.5, y - 8.5, x + 8.5, y + 8.5)
                fl_ = _roof_stairs(self.w, hit[0], hit[1])
                self.heli_stairs.extend(fl_)
                pts_ = []                                       # the ride line for escride (the yellow F prompt at both ends): toe -> flights -> roof edge -> deck
                for q_ in fl_:
                    if not pts_:
                        pts_.append([q_[1] - q_[3] * q_[5], q_[2] - q_[4] * q_[5], q_[7]])
                    pts_.append([q_[1] + q_[3] * q_[5], q_[2] + q_[4] * q_[5], q_[8]])
                if z - hit[1] > 0.6:                          # deck well above the roof: a short stair up onto it
                    L = max(2.0, (z - hit[1]) / 0.6)
                    up = (0, x + 8.5 + L / 2, y, -1.0, 0.0, L / 2, 0.65, hit[1], z)
                    _pg2_add(self.w, up, x + 8.5, y - 1, x + 8.5 + L, y + 1)
                    self.heli_stairs.append(up)
                    if pts_:
                        pts_ += [[up[1] - up[3] * up[5], up[2] - up[4] * up[5], up[7]], [up[1] + up[3] * up[5], up[2] + up[4] * up[5], up[8]]]
                elif pts_:
                    pts_.append([x, y, z])
                if len(pts_) >= 2:
                    esc_ = getattr(self.w, "esc", None)
                    if not isinstance(esc_, dict):
                        esc_ = self.w.esc = {}
                    esc_.setdefault("stairs", []).append({"path": pts_, "heli": True})
                    self.__dict__.pop("_esc_grid", None)
            self._clear_pad(x, y)
            b = Heli(x, y, -math.pi / 2, vehicles.HELI, 0)
            b.az = surface
            b.fuel = 1.0
            self.bodies.append(b)

    def _clear_pad(self, x, y, r=15.0):
        """Nothing right next to a helipad: trees and props there are hidden (no collision), parked cars never spawn."""
        w = self.w
        cg = w.cg
        for e in list(w.points_near(x, y, r)):
            if (e[0] - x) ** 2 + (e[1] - y) ** 2 > r * r:
                continue
            cell = w.pgrid.get((int(e[0] // cg), int(e[1] // cg)))
            if cell and e in cell:
                cell.remove(e)
            g0 = w.ground_y(e[0], e[1])
            w.broken_extra.append((e[0], e[1], max(4.5, e[2] + 0.6), g0 - 2.0, e[4] + 8.0))
        w.broken_ver += 1
        for i, q in enumerate(getattr(w, "parked", ()) or ()):
            if (q[0] - x) ** 2 + (q[1] - y) ** 2 < (r + 3) ** 2:
                self.gone.add(i)

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

    WEAPON_PICKUPS = 158                  # was 105; +50%

    def _spawn_weapons(self, rng):
        """A fresh set of weapons in random places (called at start and every game morning)."""
        self.pickups = [pk for pk in self.pickups if pk[2] not in WEAPONS]
        walk = [e for e in self.w.edges if e.get("walk") and e["len"] > 25]
        for e in rng.sample(walk, min(self.WEAPON_PICKUPS, len(walk))):
            x, y, dx, dy = self.w.edge_point(e, rng.uniform(5, e["len"] - 5))
            self.pickups.append([x, y, rng.choice(("pistol", "pistol", "bat", "bat", "knuckles", "chain", "uzi", "uzi", "shotgun", "kalash",
                                                    "kalash", "zolja", "machete", "revolver", "smg", "cutters")), True, 0.0])
        if getattr(self, "compounds", None):
            self.compounds.drop_cutters()

    def _make_pickups(self):
        rng = random.Random(99)
        drv = [e for e in self.w.edges if e["drive"] and e["len"] > 30 and e["cls"] not in ("service", "living_street")]
        if not drv:
            return
        for i in range(90):
            e = rng.choice(drv)
            x, y, dx, dy = self.w.edge_point(e, rng.uniform(5, e["len"] - 5))
            if i % 4 != 3:                                       # (every 4th was an ajvar car repair: garages do that now)
                self.pickups.append([x, y, "burek", True, 0.0])
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
            wk.indoor, wk.az = None, None            # out of the GTC mall too (its walls would pull the player back in)
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
        dmg = (26.0 if kick else 14.0) * HERO["str"]
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
        elif p.work_role:
            p.mode, p.t, p.far_t = "fight", 14.0, 0.0
            self.ev("shout", text=rng.choice(peds_lines.work(p.work_role, "hit")), x=p.x, y=p.y, who=vehicles.ped_who(p))
        elif p.mode in ("walk", "flee", "rage"):
            if rng.random() < (vehicles.FIGHT[p.arch][1] + 0.12) * (0.3, 1.0, 1.8, 3.0)[self.aggro % 4]:
                p.mode, p.t = "fight", 14.0
                self.ev("shout", text=talk.react("fight", p.arch, self, lines("fight", p.arch), rng), x=p.x, y=p.y, who=vehicles.ped_who(p))
            else:
                p.mode, p.t = "flee", 3.0
                p.vx, p.vy = fx * 3.4, fy * 3.4
                self.ev("shout", text=talk.react("hit", p.arch, self, lines("hit", p.arch), rng), x=p.x, y=p.y, who=vehicles.ped_who(p))

    def _knock_out(self, p):
        p.mode, p.t = "ko", self.rng.uniform(6.0, 9.0)
        self.stats["ko"] = self.stats.get("ko", 0) + 1
        self.ev("ko", x=p.x, y=p.y)
        text = self.rng.choice(peds_lines.work(p.work_role, "ko")) if p.work_role else talk.react("ko", p.arch, self, lines("ko", p.arch), self.rng)
        self.ev("shout", text=text, x=p.x, y=p.y, who=vehicles.ped_who(p))
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
        if wk.weapon in SWINGERS:                           # hits are found along the swept arc by _swing_tick over the next 0.36 s
            wk.sw_hit, wk.sw_u, wk.sw_k = set(), 0.0, -1
            self.ev("swing", x=wk.x + fx, y=wk.y + fy, hit=False, weapon=wk.weapon)
        elif wk.weapon == "cutters" and getattr(self, "compounds", None) and self.compounds.cut(wk.x, wk.y, wk.h):
            pass                                            # wire cutters on a compound fence: a quiet hole to slip through
        elif wk.weapon in MELEE:
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

    def _swing_tick(self):
        """Everything the bat passes through since the last tick is hit once: people, vehicles, other players, breakables."""
        wk = self.walker
        if wk is None or getattr(wk, "sw_hit", None) is None:
            return
        u = 1.0 if wk.atk_t <= 0 else min(1.0, 1.0 - wk.atk_t / SWING_T)
        a0, a1 = swing_az(wk.sw_u), swing_az(u)
        k_prev = wk.sw_k
        wk.sw_u = u
        hit = wk.sw_hit
        if u >= 1.0 or wk.health <= 0:
            wk.sw_hit = None
        lo, hi = min(a0, a1), min(max(a0, a1), 1.6)            # (nothing is hit while the bat is still behind the batter)
        if lo > hi:
            return
        _name, _cd, dmg, _p, _s, reach, _pe = WEAPONS[wk.weapon]

        def in_arc(x, y, rad):
            dx, dy = x - wk.x, y - wk.y
            d = math.hypot(dx, dy)
            if d < 0.2 or d > reach + rad:
                return None
            rel = (math.atan2(dy, dx) - wk.h + math.pi) % math.tau - math.pi
            pad = math.atan2(rad, d)
            return math.atan2(dy, dx) if lo - pad <= rel <= hi + pad else None
        for p in self.peds.list:
            if id(p) in hit or p.mode in ("dead", "air"):
                continue
            ang = in_arc(p.x, p.y, 0.45)
            if ang is None:
                continue
            hit.add(id(p))
            fx, fy = math.cos(ang), math.sin(ang)
            p.hp -= dmg
            p.vx, p.vy = fx * 3, fy * 3
            self.ev("hit", x=p.x, y=p.y, kick=True)
            self.ev("swing", x=p.x, y=p.y, hit=True, weapon=wk.weapon)
            if p.hp <= 0:
                p.mode, p.t = "dead", clear_secs(self)
                self.stats["peds"] += 1
                self.ev("ped_shot", x=p.x, y=p.y)
            elif p.mode != "guard":
                p.mode, p.t = "flee", 4.0
                p.vx, p.vy = fx * 4, fy * 4
        for b in self.bodies:
            if id(b) in hit or not b.alive:
                continue
            ang = in_arc(b.x, b.y, CIRC[b.kind][1] * 1.6)
            if ang is None:
                continue
            hit.add(id(b))
            if getattr(b, "pid", None) is not None:
                self._pvp_hit(b.pid, "car", 6)
            b.health -= 6
            b.dirty = True
            self.ev("swing", x=b.x, y=b.y, hit=True, weapon=wk.weapon)
        for rp in self.remote_foot.values():
            if id(rp) in hit:
                continue
            ang = in_arc(rp["x"], rp["y"], 0.45)
            if ang is not None:
                hit.add(id(rp))
                self._pvp_hit(rp["pid"], "swing", dmg)
                self.ev("hit", x=rp["x"], y=rp["y"], kick=True)
        k = int(u * 6)
        if k != k_prev:                                           # props along the arc, six looks per swing
            wk.sw_k = k
            mid = (lo + hi) * 0.5
            self.chaos.punch(wk, True, ang=wk.h + mid, dist=1.2)

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
                            who=vehicles.ped_who(p))

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
            elif p.mode != "guard":
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
                self.ev("alight", train=True)
            return False
        for t in self.trains.trains:
            if t.v < 0.1 and t.wait > 0 and t.last_stop is not None:
                for k in range(trains.CARS):
                    x, y, _z, _h = t.line.at(t.s - t.d * (k * (trains.CAR_L + trains.GAP) + trains.CAR_L / 2))
                    if math.hypot(wk.x - x, wk.y - y) < 14.0:
                        fare = 40 if self.money >= 40 else 0
                        self.money -= fare
                        self.train_ride = t
                        t.ended = False
                        self.ev("board", body=None, fare=fare, train=True)
                        return True
        best, bd, kind = None, 1e9, None
        for b in self.bodies:
            if not b.alive or b.burn > 0.5 or getattr(b, "locked", False):
                continue
            if getattr(b, "remote", False) and getattr(b, "drop_pid", None) is None and not (getattr(b, "puppet", False) and getattr(b, "bus_line", None)):
                continue                                           # another player's occupied car, or a host puppet: not for the taking
            d = reach(b, wk.x, wk.y)
            if d < 2.5 and d < bd:
                best, bd, kind = b, d, "body"
        for c in self.traffic.cars:
            d = reach(c, wk.x, wk.y) if vehicles.HALF_L[c.kind] > 3.5 else math.hypot(wk.x - c.x, wk.y - c.y)
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
            if b.kind in vehicles.FLY:                             # no door scene: climb straight into the cockpit
                self._board(b)
                self.ev("heli_board")
                return True
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
        return door_point(b, out)

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
        dx_, dy_ = door_point(b, 1.4)
        p = self.peds.eject(dx_, dy_, b.h + math.pi / 2, gz=b.az)
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

    def _btr(self, c, inp, dt):
        """БТР-80: Shift + A/D turns the turret, Ctrl fires the 30 mm cannon (2x a Калаш round's speed, 6x its damage, splash)."""
        if inp.get("run"):
            c.turret = (c.turret + inp.get("steer", 0.0) * 1.5 * dt + math.pi) % math.tau - math.pi
        c.gun_cd = max(0.0, c.gun_cd - dt)
        if inp.get("attack") and c.gun_cd <= 0 and c.ammo > 0 and c.alive:
            c.gun_cd = 0.2 / 1.5                                       # Martin: 50 % faster
            c.ammo -= 1
            a = c.h + c.turret
            import gl3d
            tx_, ty_ = c.x + math.cos(c.h) * gl3d.APC_TURRET[0], c.y + math.sin(c.h) * gl3d.APC_TURRET[0]
            g0 = self.w.ground_y(c.x, c.y)
            gz = (c.az - g0 if c.az is not None else 0.0) + gl3d.APC_TURRET[1] + 0.28   # bore height above the ground (projectile z is relative)
            dmg = WEAPONS["kalash"][2] * 6
            self.shots.fire(tx_ + math.cos(a) * 3.1, ty_ + math.sin(a) * 3.1, a + self.rng.uniform(-0.004, 0.004), "shell30", dmg, 220.0, gz, src=c)
            self.ev("gunfire", x=tx_, y=ty_, kind="btr")
            self.ev("muzzle", x=tx_ + math.cos(a) * 3.1, y=ty_ + math.sin(a) * 3.1, z=gz, ex=tx_ + math.cos(a) * 0.5, ey=ty_ + math.sin(a) * 0.5, ea=a,
                    ez=gz - 0.15)
            self.scare(c.x, c.y, 60.0)
            if c.ammo == 0:
                self.ev("btr_empty")

    def exit_car(self):
        if self.mode != "car":
            return
        b = self.car
        if getattr(self, "riding", None) is not None:              # get off the bus; it carries on along its line
            self.riding = None
            x, y = door_point(b, 1.0, -1)
            self.walker = Walker(x, y, b.h)
            self.walker.az = b.az
            self.car = None
            self.mode = "foot"
            self.ev("alight")
            return
        if b.kind in vehicles.FLY and b.az is not None and b.az - self.w.ground_y(b.x, b.y) > 1.0:
            self.ev("heli_land")                                   # not in mid-air: land first
            return
        b.empty = True
        b.player_car = False
        self.last_exit = b
        L, W = CIRC[b.kind][0], CIRC[b.kind][1]
        lx, ly = math.sin(b.h), -math.cos(b.h)
        for side in (1, -1):
            x, y = door_point(b, 0.9, side)
            if not any(True for _ in self.w.edges_near(x, y, 0.5)):
                break
        self.walker = Walker(x, y, b.h)
        self.walker.az = b.az
        self.mode = "foot"

    def _traffic_crashes(self):
        ev, rng = self.ev, self.rng
        tp = getattr(self, "tproc", None)
        poke = tp.poke if tp is not None else setattr
        bgrid = {}
        for b in self.bodies:
            bgrid.setdefault((int(b.x // 20), int(b.y // 20)), []).append(b)
        for c in list(self.traffic.cars):
            gx_, gy_ = int(c.x // 20), int(c.y // 20)
            near_ = [b for dx in (-1, 0, 1) for dy in (-1, 0, 1) for b in bgrid.get((gx_ + dx, gy_ + dy), ())]
            for b in near_:
                rr_ = _RAD[b.kind] + _RAD[c.kind]
                if (c.x - b.x) ** 2 + (c.y - b.y) ** 2 > rr_ * rr_:
                    continue
                if b.az is not None and abs(b.az - c.gz) > 2.2:
                    continue
                tmp = self.traffic.make_body(c)
                tmp.parked_idx = None
                r = collide_bodies(b, tmp, vehicles.PERF[b.kind][4], vehicles.PERF[tmp.kind][4])
                if r is None:
                    continue
                impact = r[0]
                if impact > 2.0:
                    ev("crash", body=b, kind="car", impact=impact, x=r[1], y=r[2], nx=r[3], ny=r[4])
                    if b.player_car and self.mode == "car" and b.health > 0:
                        self._pay(min(80, int(impact * 4)) if tmp.health <= 50.0 else min(30, int(impact * 2)), r[1], r[2])
                if tmp.health <= 50.0:
                    tmp.empty = True
                    self.bodies.append(tmp)
                    self.traffic.cars.remove(c)
                    dx_, dy_ = door_point(tmp, 1.0)
                    p = self.peds.eject(dx_, dy_, tmp.h + math.pi / 2, gz=tmp.az)
                    if rng.random() < 0.7:
                        ev("shout", text=rng.choice(slang.PED_HIT + slang.DRIVER_RAGE[1:3]), x=p.x, y=p.y)
                    break
                poke(c, "x", tmp.x)
                poke(c, "y", tmp.y)
                speed = tmp.vx * math.cos(c.h) + tmp.vy * math.sin(c.h)
                poke(c, "v", max(0.0, min(c.v, speed)))
                if c.turnaround is not None:
                    poke(c, "turnaround", None)
                if impact > 2.0:
                    poke(c, "health", tmp.health)
                    if c.rev > 0.0:
                        poke(c, "rev", 0.0)
                        if c.rev_box:
                            poke(c, "rev_box", False)
                    if c.honk_t <= 0.0:
                        poke(c, "honk_t", 1.2)
                        ev("horn", body=c)

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
        cmp_ = getattr(self, "compounds", None)
        if cmp_ is not None and cmp_.bust is not None:            # being arrested: hands up, cuffs on
            inp = dict(inp, move=(0, 0), attack=False, jump=False, throttle=0.0, steer=0.0)
        inp = escride.tick(self, dt, inp)                        # F at a fire escape: automatic climb (and its prompt)
        # ---------------- player
        if self.mode == "car" and getattr(self, "riding", None) is not None:
            if self.riding not in self.bodies or not self.riding.alive:
                self.riding = None
            elif inp.get("attack"):
                self.take_bus()
        if self.mode == "car":
            c = self.car
            ride = getattr(self, "riding", None) is not None
            if c.kind == vehicles.BTR and not ride:
                self._btr(c, inp, dt)
                if inp.get("run"):                                    # Shift: the steering keys turn the turret, not the wheels
                    inp = dict(inp, steer=0.0)
            for _ in range(steps):
                sdt = dt / steps
                if c.kind in vehicles.FLY:
                    hit = fly(c, inp, sdt, w)
                    thr = 0.0
                    if hit > 2.0:
                        ev("crash", body=c, kind="wall", impact=hit, x=c.x, y=c.y, nx=-math.cos(c.h), ny=-math.sin(c.h))
                        bump(c, hit, c.x + math.cos(c.h) * vehicles.HALF_L[c.kind], c.y + math.sin(c.h) * vehicles.HALF_L[c.kind], -math.cos(c.h), -math.sin(c.h))
                elif ride:
                    controls = c.ctl if c.ctl is not None else (0.0, 0.0, True)
                    if getattr(self, "transit", None) is not None:
                        self.transit.drive_body(c, controls, sdt)
                    else:
                        drive(c, *controls, sdt, w)
                    thr = 0.0
                else:
                    thr = inp["throttle"] if c.fuel > 0 or inp["throttle"] < 0 else 0.0     # empty tank: it only rolls
                    assist = self.lane_assist.steer(c, w, self.traffic, inp["steer"], inp["throttle"], inp["handbrake"],
                                                    self.lane_assist_on, sdt) if c.ctl is None else 0.0
                    drive(c, thr, inp["steer"] + assist, inp["handbrake"], sdt, w)
                if thr > 0:
                    was = c.fuel
                    c.fuel = max(0.0, c.fuel - math.hypot(c.vx, c.vy) * sdt * (0.6 + 0.4 * thr) / (FUEL_KM * 1000.0 * vehicles.FUEL_MULT.get(c.kind, 1.0)))
                    if was > 0.15 >= c.fuel:
                        ev("fuel_low")
                    if was > 0 >= c.fuel:
                        ev("fuel_out")
                if c.kind not in vehicles.FLY:
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
                    n_ = 2 if dt > 0.03 else 1                 # under ~33 fps a running step is longer than the body is wide:
                    for _ in range(n_):                        # two half steps, or the walker passes straight through walls
                        wk.update(dt / n_, inp["move"][0], inp["move"][1], inp["run"], w, inp.get("jump", False))
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
                    if b.kind in vehicles.FLY and b.az is not None and wk.az is not None and abs(b.az - wk.az) > 2.2:
                        continue                           # a helicopter above you / you on a roof above it
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
        if not self.client:
            self.garbage.update(dt)
        if getattr(self, "compounds", None) is not None:
            self.compounds.update(dt)
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
        if getattr(self, "crews", None) is not None:
            self.crews.update(dt)
        self.shots.update(dt)
        for b in list(self.bodies):
            if getattr(b, "remote", False):                      # another player's car / a host puppet: placed by mpgame, not simulated here
                continue
            if getattr(b, "crew", None) is not None:                 # a road crew's truck: placed by crews.py, no physics
                continue
            b.age += dt
            if b is not self.car or self.mode == "foot":
                if b.ctl is None and not b.player_car and not b.air and b.vx * b.vx + b.vy * b.vy < 1e-8 and abs(b.w) < 1e-4:
                    rp = getattr(b, "rest_pose", None)           # at rest: after a second of standing still it sleeps
                    if rp is not None and abs(rp[0] - b.x) + abs(rp[1] - b.y) + abs(rp[2] - b.h) < 1e-4:
                        b.rest_n = getattr(b, "rest_n", 0) + 1
                        if b.rest_n >= 60:
                            b.w = 0.0
                            b.indicator = 0
                    else:
                        b.rest_pose, b.rest_n = (b.x, b.y, b.h), 0
                else:
                    b.rest_n = 0
                if getattr(b, "rest_n", 0) < 60:                  # (anything that moves it - a push, a hit, a blast - wakes it)
                    if b.kind in vehicles.FLY:
                        fly(b, None, dt, w)
                    else:
                        controls = b.ctl if b.ctl is not None and not b.player_car else (0.0, 0.0, True)
                        if (b.ctl is not None and not b.player_car and getattr(b, "bus_line", None)
                                and getattr(self, "transit", None) is not None):
                            self.transit.drive_body(b, controls, dt)
                        else:
                            drive(b, *controls, dt, w)
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
            if _apart(a, a.az, b, b.az):
                continue
            r = collide_bodies(a, b, vehicles.PERF[a.kind][4], vehicles.PERF[b.kind][4])
            if r and r[0] > 1.5:
                ev("crash", body=a if a.player_car else b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
                if (a.player_car or b.player_car) and r[0] > 3.0 and not (a.service or b.service) and self.mode == "car" \
                        and a.health > 0 and b.health > 0:            # (ramming a wreck again pays nothing)
                    self._pay(min(60, int(r[0] * 3)), r[1], r[2])             # smashing into things pays
        self._traffic_crashes()
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
                    self.ev("alight", train=True)
            else:
                wk_ = self.walker
                wk_.x, wk_.y, gz_, _h = tr.line.at(tr.s - tr.d * (trains.CAR_L / 2))
                wk_.vx = wk_.vy = wk_.vz = 0.0
                wk_.az, wk_.z = gz_ + 0.9, 0.0                         # carried at the floor height of the carriage, on bridges too
                wk_.lx, wk_.ly = wk_.x, wk_.y
        elif tr is not None:
            self.train_ride = None
        if not self.client:
            tp = getattr(self, "tproc", None)                              # AI traffic in its own process (trafficproc.py)
            wk_ = self.walker if self.mode == "foot" else None
            obst = self.bodies + self.crews.obstacles() if getattr(self, "crews", None) is not None and self.crews.cone_bodies else self.bodies
            if tp is None or not tp.step(dt, fx, fy, obst, self.peds.list, wk_):
                self.traffic.update(dt, fx, fy, obst, self.peds.list, wk_)
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
            if b is self.car or getattr(b, "remote", False) or (b.kind in vehicles.FLY and not b.exploded):   # helicopters stay on their pads
                keep.append(b)
                continue
            d2 = (b.x - fx) ** 2 + (b.y - fy) ** 2
            if d2 > 420 ** 2 or (b.exploded and b.age > clear_secs(self) and not self.services.has_job_for(b)):
                if b.model is not None:
                    self.ev("free_model", model=b.model)
                continue
            keep.append(b)
        self.bodies = keep
        self._swing_tick()
        if self.mode == "foot" and self.walker is not None and 0 < self.walker.health < 100:
            self.walker.health = min(100.0, self.walker.health + dt * 10.0 / 60.0)      # slow healing: 10 % a minute
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
