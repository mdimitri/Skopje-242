"""Simulation: car physics with damage, traffic, pedestrians, on-foot play, hijacking, pickups."""
import math
import random

import clock
import peds_lines
import talk
import projectiles
import slang
import vehicles

_LINES = {}

# weapons: key -> (Macedonian name, seconds between shots, damage, pellets, spread rad, range m, ammo per pickup)
WEAPONS = {"pistol": ("Пиштол", 0.28, 45, 1, 0.0, 40, 36), "uzi": ("Узи", 0.09, 22, 1, 0.06, 32, 120),
           "shotgun": ("Пумпарица", 0.85, 30, 6, 0.16, 18, 24), "kalash": ("Калаш", 0.12, 40, 1, 0.03, 60, 90),
           "bat": ("Палка", 0.55, 34, 1, 0.0, 1.9, 9999), "zolja": ("Зоља", 1.6, 400, 1, 0.0, 90, 6)}
MELEE = ("bat",)                # swung, not fired: no tracer, no ammo used
WEAPON_ORDER = ["fist", "bat", "pistol", "uzi", "shotgun", "kalash", "zolja"]
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
PLAYER_NAME = "Црвена молња"


# ===================================================================== cars with physics & damage
class Body:
    """A car driven by physics: the player's car, abandoned/hijacked cars, parked cars, wrecks."""

    def __init__(self, x, y, h, kind=1, color=0):
        self.x, self.y, self.h = x, y, h
        self.vx = self.vy = self.w = 0.0
        self.steer = 0.0
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
    b.health -= max(0.0, impact - 2.0) * 3.4
    mag = min(0.08 + impact * 0.04, 0.8)
    dx, dy = wx - b.x, wy - b.y
    c, s = math.cos(b.h), math.sin(b.h)
    lx, lz = dx * c + dy * s, -dx * s + dy * c
    b.dents.append((lx, lz, nx * c + ny * s, -nx * s + ny * c, mag))
    if len(b.dents) > 9:
        a, d = b.dents[0], b.dents[1]
        b.dents[:2] = [((a[0] + d[0]) / 2, (a[1] + d[1]) / 2, (a[2] + d[2]) / 2, (a[3] + d[3]) / 2, min(0.9, a[4] + d[4] * 0.6))]
    b.dirty = True


def drive(p, throttle, steer_in, handbrake, dt, world):
    VMAX, ACC, STEER, GRIP, _M = vehicles.PERF[p.kind]
    BRAKE, REV = 22.0 + ACC, 9.0
    L_ = vehicles.DIMS[p.kind][0]
    wb = L_ * 0.62 if L_ < 6 else 3.7 + (L_ - 6) * 0.35   # long vehicles: wheelbase, not length (articulated / rear-axle steer)
    dmg = 1.0 if p.health > 35 else 0.7           # a wrecked engine is slower
    fx, fy = math.cos(p.h), math.sin(p.h)
    vf = p.vx * fx + p.vy * fy
    p.steer += (steer_in - p.steer) * min(1.0, (9.0 if steer_in else 14.0) * dt)
    maxang = STEER / (1.0 + abs(vf) / (8.0 if L_ < 6 else 13.0))
    if abs(vf) > 0.15:
        om = vf / wb * math.tan(p.steer * maxang)
        if handbrake:
            om *= 1.4
        p.h += om * dt
    fx, fy = math.cos(p.h), math.sin(p.h)
    rx, ry = -fy, fx
    vf = p.vx * fx + p.vy * fy
    vl = p.vx * rx + p.vy * ry
    p.braking = False
    if throttle > 0:
        vf += (ACC * dmg * max(0.0, 1 - vf / (VMAX * dmg)) if vf >= 0 else BRAKE) * dt * throttle
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
    vf -= vf * abs(vf) * 0.00085 * dt + (0.25 * dt if vf > 0 else -0.25 * dt if vf < 0 else 0)
    if handbrake:
        vf *= math.exp(-1.1 * dt)
        p.braking = True
    grip = 1.8 if handbrake else (GRIP * 0.63 if sf == 0 else GRIP)
    p.slip = abs(vl)
    vl *= math.exp(-grip * dt)
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
                b.health -= (imp - 5.0) * 5.0
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
                tree = tr >= 0.45
                if -vn > (9.0 if tree else 2.5) and hasattr(world, "break_point"):   # everything breaks, the car pays
                    world.break_point((tx, ty, tr, lo, hi))
                    p.x -= nx * pen
                    p.y -= ny * pen
                    k = 0.55 if tree else (0.8 if tr > 0.3 else 0.88)
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


def _corners(b):
    L, W = vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2
    fx, fy = math.cos(b.h), math.sin(b.h)
    return [(b.x + fx * u - fy * v, b.y + fy * u + fx * v) for u, v in ((L, W), (L, -W), (-L, -W), (-L, W))]


def collide_bodies(a, b, ma=1.0, mb=1.0):
    """Oriented-box car/car collision (separating axis test) with a rigid-body impulse at the contact corner:
    a hit on the rear quarter spins the car, a head-on stops it. Returns (impact, wx, wy, nx, ny) or None,
    n pointing from a to b."""
    if abs(a.x - b.x) > 9 or abs(a.y - b.y) > 9:
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
        self.say_t = random.uniform(4, 18)
        self.e = 0
        self.d = 1
        self.s = 0.0
        self.v = 1.3
        self.side = 1
        self.shirt = 0
        self.x = self.y = self.h = 0.0
        self.gz = None               # height of the surface they stand on (terrain or bridge deck)

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
        """GTA-1 style: turn = A/D (-1..1) rotates, fwd = W/S (-1..1) walks forward/backward. SPACE jumps."""
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
        sp = 7.6 if run else 4.6
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


class Peds:
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

    def update(self, dt, fx, fy, bodies, ev):
        w, rng = self.w, self.rng
        out = []
        aggro = getattr(self.sim, "aggro", 1) if self.sim else 1
        if rng.random() < dt * (0.01, 0.03, 0.06, 0.12)[aggro % 4]:
            self._start_brawl(fx, fy, ev)
        for p in self.list:
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
                    if p.hy <= 0:
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
            for b in bodies:
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
                out.append(p)
                continue
            if p.mode in ("queue", "board", "alight", "play"):       # moved by Transit / Kids (they can still be hit)
                out.append(p)
                continue
            # ------------- panic near fast cars
            if p.mode == "walk":
                for b in bodies:
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
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 320 ** 2:
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
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 320 ** 2:
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
                    dx, dy = wk.x - p.x, wk.y - p.y
                    d = math.hypot(dx, dy) or 1e-6
                    p.h = math.atan2(dy, dx)
                    p.anim += dt * 9
                    if d > 1.1:
                        sp = 4.4
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
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 320 ** 2:
                    out.append(p)
                continue
            if p.mode in ("flee", "rage"):
                p.t -= dt
                if p.mode == "rage":
                    p.anim += dt * 8
                    if p.t <= 0:
                        p.mode, p.t = "flee", 6.0
                        d = math.hypot(p.x - fx, p.y - fy) or 1.0
                        p.vx, p.vy = (p.x - fx) / d * 4.0, (p.y - fy) / d * 4.0
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
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 320 ** 2:
                    out.append(p)
                continue
            # ------------- walking along the graph
            e = w.edges[p.e]
            vv = p.v
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
                p.say_t = rng.uniform(10, 28)
                if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 22 ** 2:
                    ev("shout", text=talk.say(p, self.sim, rng) if self.sim else rng.choice(lines("idle", p.arch)), x=p.x, y=p.y, who=vehicles.PED_NAMES[p.arch])
            if (p.x - fx) ** 2 + (p.y - fy) ** 2 < 300 ** 2:
                out.append(p)
        self.list = out
        for _ in range(2):
            if len([q for q in self.list if q.mode == "walk"]) < self.target:
                self.spawn(fx, fy)


# ===================================================================== traffic
class Car:
    __slots__ = ("e", "d", "s", "v", "lane", "kind", "color", "pace", "x", "y", "h", "stuck", "ghost", "braking", "gz", "pitch", "roll")

    def __init__(self):
        self.stuck = 0.0
        self.ghost = 0.0
        self.braking = False
        self.gz = 0.0
        self.pitch = 0.0
        self.roll = 0.0


class Traffic:
    def __init__(self, world, rng, target=90):
        self.w = world
        self.rng = rng
        self.cars = []
        self.target = target
        self.hash = {}
        self.signals = None          # signals.Signals, set by main: AI stops on red

    def _place(self, c):
        e = self.w.edges[c.e]
        s = c.s if c.d == 1 else e["len"] - c.s
        x, y, dx, dy = self.w.edge_point(e, s)
        if c.d == -1:
            dx, dy = -dx, -dy
        x += -dy * c.lane
        y += dx * c.lane
        return x, y, math.atan2(dy, dx)

    def spawn(self, px, py, rmin=170, rmax=380):
        w, rng = self.w, self.rng
        a, r = rng.uniform(0, 6.283), rng.uniform(rmin, rmax)
        cell = (int((px + math.cos(a) * r) // w.sg), int((py + math.sin(a) * r) // w.sg))
        lst = w.drive_cells.get(cell)
        if not lst:
            return
        ei = rng.choice(lst)
        e = w.edges[ei]
        c = Car()
        c.e = ei
        c.d = 1 if (e["ow"] or rng.random() < .5) else -1
        c.s = rng.uniform(0, e["len"])
        c.lane = rng.choice((-1, 1)) * e["w"] / 6 if e["ow"] else max(1.3, e["w"] / 4)
        c.kind = rng.choices(range(vehicles.N), vehicles.TRAFFIC_W)[0]
        if vehicles.LARGE[c.kind] and e["w"] < 8:
            c.kind = 1
        c.color = rng.randrange(vehicles.N_COLORS)
        c.pace = rng.uniform(0.75, 1.0) * vehicles.SPEED[c.kind]
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

    def _next_edge(self, c):
        w = self.w
        e = w.edges[c.e]
        node = e["b"] if c.d == 1 else e["a"]
        opts = w.out.get(node, [])
        good = [o for o in opts if o[0] != c.e] or opts
        if not good:
            return False
        c.e, c.d = self.rng.choice(good)
        return True

    def scan(self, c, rng_ahead):
        hx, hy = math.cos(c.h), math.sin(c.h)
        rx, ry = -hy, hx
        best = None
        gx, gy = int(c.x // 16), int(c.y // 16)
        n = int(rng_ahead // 16) + 1
        for ix in range(gx - n, gx + n + 1):
            for iy in range(gy - n, gy + n + 1):
                for o in self.hash.get((ix, iy), ()):
                    if o[4] is c:
                        continue
                    dx, dy = o[0] - c.x, o[1] - c.y
                    fwd = dx * hx + dy * hy
                    if fwd < 0.3 or fwd > rng_ahead:
                        continue
                    if abs(dx * rx + dy * ry) > o[2]:
                        continue
                    gap = fwd - vehicles.HALF_L[c.kind] - o[3]
                    if best is None or gap < best:
                        best = gap
        return best

    def make_body(self, c):
        b = Body(c.x, c.y, c.h, c.kind, c.color)
        b.vx, b.vy = math.cos(c.h) * c.v, math.sin(c.h) * c.v
        b.az = c.gz
        return b

    def update(self, dt, fx, fy, bodies, peds, walker=None):
        w, rng = self.w, self.rng
        h = {}
        for c in self.cars:
            h.setdefault((int(c.x // 16), int(c.y // 16)), []).append((c.x, c.y, vehicles.HALF_W[c.kind], vehicles.HALF_L[c.kind], c))
        for b in bodies:
            if b.parked_idx is not None and b.speed < 0.3:
                continue
            h.setdefault((int(b.x // 16), int(b.y // 16)), []).append((b.x, b.y, vehicles.HALF_W[b.kind], vehicles.HALF_L[b.kind], b))
        for p in peds:
            if p.mode in ("walk", "flee", "rage", "brawl"):
                h.setdefault((int(p.x // 16), int(p.y // 16)), []).append((p.x, p.y, 1.7, 0.4, p))
        if walker is not None and walker.health > 0:          # traffic brakes for the player on foot too
            h.setdefault((int(walker.x // 16), int(walker.y // 16)), []).append((walker.x, walker.y, 1.7, 0.4, walker))
        self.hash = h
        keep = []
        for c in self.cars:
            e = w.edges[c.e]
            L = e["len"]
            vmax = min(e["speed"] * c.pace, vehicles.PERF[c.kind][0] * 0.85)
            if w.hilly:                                           # engines labour uphill, brakes hold downhill
                sl = c.pitch
                vmax *= max(0.4, 1.0 - 4.5 * sl) if sl > 0 else min(1.2, 1.0 - 1.2 * sl)
            end_node = e["b"] if c.d == 1 else e["a"]
            deg = len(w.out.get(end_node, ()))
            vcorner = 6.0 if deg >= 3 else (vmax if deg == 2 else 2.5)
            vlim = min(vmax, math.sqrt(vcorner * vcorner + 2 * 3.5 * max(L - c.s - 1.5, 0.0)))
            sg = self.signals
            if sg is not None and sg.stop_for(c.e, 1 if c.d == 1 else 0):
                rem = L - c.s - 9.0                                # stop line before the junction
                if -2.5 < rem < 45.0:
                    vlim = min(vlim, math.sqrt(2 * 3.5 * max(rem, 0.0)))
            braking = False
            if c.ghost <= 0:
                gap = self.scan(c, 7.0 + c.v * 1.7)
                if gap is not None:
                    vlim = min(vlim, max(0.0, (gap - 1.0) * 0.8))
                    braking = True
            else:
                c.ghost -= dt
            if c.v < vlim:
                c.v = min(vlim, c.v + min(3.2, vehicles.PERF[c.kind][1] * 0.4) * dt)
            else:
                c.v = max(vlim, c.v - 8.0 * dt)
            c.braking = braking or c.v < vlim - 0.5
            if c.v < 0.2:
                c.stuck += dt
                if c.stuck > 5.0 and (c.x - fx) ** 2 + (c.y - fy) ** 2 > 90 ** 2:
                    c.ghost, c.stuck = 4.0, 0.0                   # only out of sight: never drive through cars on screen
            else:
                c.stuck = 0.0
            c.s += c.v * dt
            if c.s >= L:
                c.s -= L
                if not self._next_edge(c):                       # dead end: U-turn instead of vanishing
                    c.d, c.v = -c.d, 0.0
            tx, ty, th = self._place(c)
            ex, ey = tx - c.x, ty - c.y                          # follow the lane at driving speed: no jumps
            dd = math.hypot(ex, ey)
            mx = (c.v * 1.3 + 1.5) * dt
            if dd > mx:
                ex, ey = ex / dd * mx, ey / dd * mx
            c.x += ex
            c.y += ey
            dh = (th - c.h + math.pi) % (2 * math.pi) - math.pi
            c.h += dh * min(1.0, dt * 9)
            c.gz = w.level(c.x, c.y, 1e9 if e["bridge"] else -1e9)
            if w.hilly or e["bridge"]:
                fx_, fy_ = math.cos(c.h), math.sin(c.h)
                wy_ = 1e9 if e["bridge"] else -1e9
                hb = vehicles.DIMS[c.kind][0] * 0.31
                pt = math.atan2(w.level(c.x + fx_ * hb, c.y + fy_ * hb, wy_) - w.level(c.x - fx_ * hb, c.y - fy_ * hb, wy_), 2 * hb)
                rl_ = math.atan2(w.level(c.x + fy_ * 0.85, c.y - fx_ * 0.85, wy_) - w.level(c.x - fy_ * 0.85, c.y + fx_ * 0.85, wy_), 1.7)
                kk = min(1.0, dt * 8)
                c.pitch += (pt - c.pitch) * kk
                c.roll += (rl_ - c.roll) * kk
            keep.append(c)
        self.cars = [c for c in keep if (c.x - fx) ** 2 + (c.y - fy) ** 2 < 460 ** 2]
        for _ in range(2):
            if len(self.cars) < self.target:
                self.spawn(fx, fy)


# ===================================================================== the whole game state
class Sim:
    def __init__(self, world, rng, n_cars, n_peds):
        self.w = world
        self.rng = rng
        self.events = []
        self.aggro, self.lang = 1, 1              # menu: how quarrelsome people are, how rude they talk
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
        self.dens_traffic = self.dens_peds = 1.0
        self.parked = {}
        self.gone = set()
        self.stats = {"peds": 0, "burek": 0, "stolen": 0, "deaths": 0, "boom": 0, "ajvar": 0}
        self.safe = (sx, sy, sh)
        self.safe_z = None
        self.respawn_t = 0.0
        self.pickups = []
        self.money = 250
        self.riding = None                   # the city bus you ride as a passenger (Ctrl takes it over)
        self.shots = projectiles.Projectiles(self)
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
            self.pickups.append([x, y, rng.choice(("pistol", "pistol", "bat", "bat", "uzi", "uzi", "shotgun", "kalash",
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
        self.ev("kick" if kick else "punch", x=wk.x + fx, y=wk.y + fy, hit=best is not None)
        if best is None:
            return
        p = best
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
        if rng.random() < 0.35:
            self.ev("shout_self", text=rng.choice(slang.KICK if kick else slang.PUNCH))

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
        wk.atk_cd, wk.atk_t, wk.atk_kind = cd, 0.2, 4
        empty = wk.ammo <= 0
        fx, fy = math.cos(wk.h), math.sin(wk.h)
        if wk.weapon in MELEE:
            self._ray(wk, wk.h, dmg, rng_m, False)
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
            self.money += pay
            self.ev("pay", x=x, y=y, amount=pay)
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
        if hit_body is not None and (best is None or (best.x - ox) * fx + (best.y - oy) * fy > bt):
            hit_body.health -= 6
            hit_body.dirty = True
            best = None
        ex, ey = ox + fx * bt, oy + fy * bt
        if tracer:
            self.ev("shot", x0=ox, y0=oy, x1=ex, y1=ey)
        else:
            self.ev("swing", x=ex, y=ey, hit=best is not None)
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
        best, bd, kind = None, 1e9, None
        for b in self.bodies:
            if not b.alive or b.burn > 0.5:
                continue
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
        if best is None:
            return False
        if kind == "ai":
            c = best
            b = self.traffic.make_body(c)
            self.traffic.cars.remove(c)
            self.bodies.append(b)
            lx, ly = math.sin(b.h), -math.cos(b.h)
            p = self.peds.eject(b.x + lx * 1.9, b.y + ly * 1.9, b.h + math.pi / 2, gz=b.az)
            self.ev("shout", text=self.rng.choice(slang.DRIVER_RAGE), x=p.x, y=p.y)
            self.stats["stolen"] += 1
            self.ev("stolen", body=b)
        elif getattr(b_ := best, "bus_line", None) and not b_.empty and getattr(self, "transit", None) is not None \
                and any(bus.body is b_ for bus in self.transit.buses):
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
            if b.parked_idx is not None:
                self.gone.add(b.parked_idx)
                b.parked_idx = None
            self.ev("enter", body=b)
        if self.car is not None and self.car is not b:
            self.car.player_car = False
        self.car = b
        b.player_car, b.empty = True, False
        b.skid = None
        self.mode = "car"
        self.walker = None
        return True

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
        self.traffic.target = max(6, int(self.base_cars * self.clock.traffic * self.dens_traffic))
        self.peds.target = max(6, int(self.base_peds * self.clock.peds * self.dens_peds))
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
                if c.drown > 1.3:
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
            if wk.health > 0:
                wk.combo_t = getattr(wk, "combo_t", 0.0) - dt
                if wk.combo_t <= 0:
                    wk.combo = 0
                wk.update(dt, inp["move"][0], inp["move"][1], inp["run"], w, inp.get("jump", False))
                if inp.get("attack"):
                    self.attack()
                if inp.get("buy") is not None:
                    self.buy(inp["buy"])
                if inp["horn"]:
                    ev("shout_self", text=rng.choice(("Ајде бре!", "Нема фрка.", "Брате!")))
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
                        wk.x, wk.y = self.safe[0], self.safe[1]
                        wk.az, wk.vz = self.safe_z, 0.0
                        wk.dead_t = 0
                elif sf in (2, 3) and wk.z < 0.3:
                    wk.dead_t = 0
                    self.safe = (wk.x, wk.y, wk.h)
                    self.safe_z = wk.az
                for b in self.bodies:
                    if abs(b.x - wk.x) > 6 or abs(b.y - wk.y) > 6:
                        continue
                    top = vehicles.DIMS[b.kind][4] * 0.6
                    cs, r = circles(b)
                    r += 0.38
                    for x, y in cs:
                        dx, dy = wk.x - x, wk.y - y
                        d = math.hypot(dx, dy)
                        if d >= r:
                            continue
                        if wk.z > top:                     # jumped onto / over the car
                            continue
                        nx, ny = (dx / d, dy / d) if d > 1e-6 else (1.0, 0.0)
                        closing = (b.vx - wk.vx) * nx + (b.vy - wk.vy) * ny
                        closing = -closing                  # > 0 when the car moves into the player
                        wk.x += nx * (r - d)
                        wk.y += ny * (r - d)
                        wk.push_out(w)
                        if closing > 4.5 and wk.inv_t <= 0 and not b.empty:
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
                        break
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
                        p = w.nearest_drive_point(wk.x, wk.y)
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
        self._dispatch()
        self.services.update(dt)
        if getattr(self, "transit", None) is not None:
            self.transit.update(dt)
        if getattr(self, "kids", None) is not None:
            self.kids.update(dt)
        self.shots.update(dt)
        for b in list(self.bodies):
            b.age += dt
            if b is not self.car or self.mode == "foot":
                if b is not self.car or self.mode == "foot":
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
        n = len(self.bodies)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = self.bodies[i], self.bodies[j]
                r = collide_bodies(a, b, vehicles.PERF[a.kind][4], vehicles.PERF[b.kind][4])
                if r and r[0] > 1.5:
                    ev("crash", body=a if a.player_car else b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
        # ---------------- traffic <-> bodies (hits convert AI cars into drivable wrecks)
        for c in list(self.traffic.cars):
            for b in self.bodies:
                if abs(c.x - b.x) > 6 or abs(c.y - b.y) > 6:
                    continue
                tmp = self.traffic.make_body(c)
                tmp.parked_idx = None
                r = collide_bodies(b, tmp, vehicles.PERF[b.kind][4], vehicles.PERF[tmp.kind][4])
                if r and r[0] > 2.0:
                    tmp.empty = True
                    self.bodies.append(tmp)
                    self.traffic.cars.remove(c)
                    lx, ly = math.sin(tmp.h), -math.cos(tmp.h)
                    p = self.peds.eject(tmp.x + lx * 2.0, tmp.y + ly * 2.0, tmp.h + math.pi / 2, gz=tmp.az)
                    if rng.random() < 0.7:
                        ev("shout", text=rng.choice(slang.PED_HIT + slang.DRIVER_RAGE[1:3]), x=p.x, y=p.y)
                    ev("crash", body=b, kind="car", impact=r[0], x=r[1], y=r[2], nx=r[3], ny=r[4])
                    break
                elif r:                                  # light touch: the AI car is pushed out too and stops
                    c.x, c.y, c.h = tmp.x, tmp.y, tmp.h
                    c.v = 0.0
        self.traffic.update(dt, fx, fy, self.bodies, self.peds.list, self.walker if self.mode == "foot" else None)
        self._cull_t -= dt
        if self._cull_t <= 0:                       # thin the crowd / traffic when the clock says it is quiet
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
        self.peds.update(dt, fx, fy, self.bodies, self.ev)
        self._parked(fx, fy)
        # cleanup far away, burnt out or useless bodies
        keep = []
        for b in self.bodies:
            if b is self.car:
                keep.append(b)
                continue
            d2 = (b.x - fx) ** 2 + (b.y - fy) ** 2
            if d2 > 420 ** 2 or (b.exploded and b.age > clear_secs(self)):
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
                if p.mode in ("dead", "air") and not getattr(p, "svc", False) and (p.x - fx) ** 2 + (p.y - fy) ** 2 < 260 ** 2:
                    p.svc = True
                    if self.rng.random() < 0.9 and sv.request("amb", p, p.x, p.y):
                        p.t = max(p.t, 80.0)
            wk = self.walker
            if self.mode == "foot" and wk is not None and wk.health <= 0 and wk.cause != "fight" and not getattr(wk, "svc", False):
                wk.svc = True
                sv.request("amb", wk, wk.x, wk.y, 2.0)
            if wk is not None and wk.health > 0:
                wk.svc = False
        if sv.fire_on:
            for b in self.bodies:
                if not b.out and not b.service and b.health <= 0 and (b.burn > 0.4 or b.exploded) and (b.x - fx) ** 2 + (b.y - fy) ** 2 < 260 ** 2:
                    sv.request("fire", b, b.x, b.y, 2.0)

    def _parked(self, fx, fy):
        w = self.w
        P = w.parked
        # despawn untouched parked cars that are far away
        for idx, b in list(self.parked.items()):
            if b.parked_idx is None or b not in self.bodies:
                del self.parked[idx]
            elif (b.x - fx) ** 2 + (b.y - fy) ** 2 > 230 ** 2 and b.speed < 0.2 and not b.dents:
                self.bodies.remove(b)
                del self.parked[idx]
            elif b.speed > 0.4 or b.dents:
                self.gone.add(idx)
                b.parked_idx = None
                del self.parked[idx]
        # spawn near ones (a slice of the list each frame keeps this cheap)
        n = len(P)
        if not n:
            return
        self._pi = getattr(self, "_pi", 0)
        for _ in range(min(n, 600)):
            self._pi = (self._pi + 1) % n
            idx = self._pi
            if idx in self.parked or idx in self.gone:
                continue
            x, y, ang, col, kind = P[idx]
            if (x - fx) ** 2 + (y - fy) ** 2 < 140 ** 2:
                b = Body(x, y, ang, kind, col)
                b.parked_idx = idx
                self.bodies.append(b)
                self.parked[idx] = b
