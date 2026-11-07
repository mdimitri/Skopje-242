"""In-game multiplayer sync (host-authoritative world, each player owns their own character).

Host: simulates traffic, pedestrians, buses and everything else, and sends every guest what is near that guest.
Guest: runs its own Sim for its own player (Sim.client = True: no traffic / pedestrian / service AI) and draws the
host's cars, pedestrians and moving bodies as puppets, interpolated between snapshots.
Everyone: sends own state at STATE_HZ; remote players are drawn as a car body (in sim.bodies, flagged remote) or as a walker
(sim.remote_foot, drawn by render).  Packet = kind(1) tick(4) count(1) + entries.
"""
import math
import struct
import time

import actors
import vehicles

STATE_HZ, SNAP_HZ = 20.0, 15.0
R_CARS, R_PEDS, R_BODIES = 230.0, 130.0, 230.0
K_PLAYER, K_CARS, K_PEDS, K_BODIES, K_WORLD = 1, 2, 3, 4, 5
HDR = struct.Struct("!BIB")
PLAYER = struct.Struct("!BBBBfffffffBBBB")     # pid flags kind color x y h vx vy z aux hp weapon atk lik
CAR = struct.Struct("!HBBfffffhhh")            # id kind color x y h z v str*1000 pitch*1000 roll*1000
PED = struct.Struct("!HBBBBBBBBfffff")         # id mode arch shirt skin pose flags atk v*20 x y h(+spin) anim hy
BODY = struct.Struct("!HBBfffffhhhfBB")        # id kind color x y h z speed wheel*1000 pitch*1000 roll*1000 door flags health*2.55
WORLD = struct.Struct("!f")
MODES = ["walk", "dead", "flee", "rage", "air", "ko", "fight", "brawl", "queue", "board", "alight", "play", "sit"]
WLIST = ["fist"] + sorted(actors.WEAPONS)
POSES = [None, "spray", "work", "cpr"]
MAX_PKT = 1000


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _lerp_a(a, b, k):
    return a + _wrap(b - a) * k


def _clampb(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


def _s16(v):
    return max(-32000, min(32000, int(v * 1000)))


class Game:
    def __init__(self, sim, session):
        self.sim, self.ses = sim, session
        self.host = session.role == "host"
        self.pid = session.pid
        sim.client = not self.host
        sim.remote_foot = {}
        self.tick = 0
        self.t_state = self.t_snap = 0.0
        self.ids, self.next_id = {}, 1                 # host: object id() -> wire id
        self.remote = {}                               # pid -> dict(target state, body)
        self.cars, self.peds, self.bods = {}, {}, {}   # guest: wire id -> puppet (+ target, seen)
        self.now = 0.0
        self.addr = {}                                 # host: pid -> addr

    # ------------------------------------------------------------------ own state
    def _my_state(self):
        s = self.sim
        if s.mode == "car" and s.car is not None:
            b = s.car
            return PLAYER.pack(self.pid, 0, _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h, b.vx, b.vy,
                               b.az if b.az is not None else 0.0, b.wheel, _clampb(b.health), 0, 0, _clampb(getattr(s, "lik", 0)))
        wk = s.walker
        wi = WLIST.index(wk.weapon) if wk.weapon in WLIST else 0
        fl = 1 | (2 if wk.health <= 0 else 0) | (4 if wk.speed > 6.0 else 0) | (8 if wk.moving else 0)
        return PLAYER.pack(self.pid, fl, 0, 0, wk.x, wk.y, wk.h, wk.vx, wk.vy, wk.az if wk.az is not None else 0.0, wk.anim,
                           _clampb(wk.health), wi, (wk.atk_kind + 1) if wk.atk_t > 0 else 0, _clampb(getattr(s, "lik", 0)))

    # ------------------------------------------------------------------ host: build snapshots
    def _wid(self, obj):
        k = id(obj)
        i = self.ids.get(k)
        if i is None:
            i = self.ids[k] = self.next_id
            self.next_id = self.next_id % 65000 + 1
        return i

    def _chunks(self, kind, entries, size):
        per = (MAX_PKT - HDR.size) // size
        for i in range(0, len(entries), per):
            part = entries[i:i + per]
            yield HDR.pack(kind, self.tick, len(part)) + b"".join(part)

    def _snapshot_for(self, gx, gy):
        s = self.sim
        out = []
        r2 = R_CARS ** 2
        ents = []
        for c in s.traffic.cars:
            if (c.x - gx) ** 2 + (c.y - gy) ** 2 < r2:
                ents.append(CAR.pack(self._wid(c), _clampb(c.kind), _clampb(c.color), c.x, c.y, c.h, c.gz, c.v,
                                     _s16(c.str), _s16(c.pitch), _s16(c.roll)))
        out += self._chunks(K_CARS, ents, CAR.size)
        ents, r2 = [], R_PEDS ** 2
        for p in s.peds.list:
            if (p.x - gx) ** 2 + (p.y - gy) ** 2 < r2:
                mode = MODES.index(p.mode) if p.mode in MODES else 0
                fl = (1 if p.vault > 0 else 0) | (2 if p.vault_up else 0) | (4 if p.atk_t > 0 else 0)
                pose = POSES.index(p.pose) if p.pose in POSES else 0
                ents.append(PED.pack(self._wid(p), mode, _clampb(p.arch), _clampb(p.shirt), _clampb(p.skin), pose, fl,
                                     _clampb(p.atk_kind), _clampb(abs(getattr(p, "v", 0.0)) * 20), p.x, p.y, p.h + p.spin, p.anim, p.hy))
        out += self._chunks(K_PEDS, ents, PED.size)
        ents, r2 = [], R_BODIES ** 2
        for b in s.bodies:
            if b.player_car or getattr(b, "remote", False):
                continue
            moving = b.vx * b.vx + b.vy * b.vy > 0.09
            if (moving or b.ctl is not None or b.service or b.burn > 0 or b.exploded) and (b.x - gx) ** 2 + (b.y - gy) ** 2 < r2:
                fl = (1 if b.exploded else 0) | (2 if b.siren else 0) | (4 if b.burn > 0 else 0) | (8 if b.braking else 0)
                ents.append(BODY.pack(self._wid(b), _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h,
                                      b.az if b.az is not None else 0.0, math.hypot(b.vx, b.vy), _s16(b.wheel), _s16(b.pitch),
                                      _s16(b.roll), b.door, fl, _clampb(b.health * 2.55)))
        out += self._chunks(K_BODIES, ents, BODY.size)
        return out

    # ------------------------------------------------------------------ per-frame
    def update(self, dt):
        """Call once per frame right after sim.update (before drawing)."""
        s, ses = self.sim, self.ses
        self.now += dt
        for kind, addr, body in ses.update():
            if kind == "unrel":
                self._rx(addr, body)
            elif kind == "gone" and self.host:
                for pid, a in list(self.addr.items()):
                    if a == addr:
                        self._drop_remote(pid)
        if ses.state != "playing" and not (self.host and ses.state == "lobby"):
            return
        self.tick = (self.tick + 1) & 0xFFFFFFFF
        peers = [(a, p) for a, p in ses.net.peers.items() if p.up]
        if self.now - self.t_state >= 1.0 / STATE_HZ:
            self.t_state = self.now
            mine = HDR.pack(K_PLAYER, self.tick, 1) + self._my_state()
            if self.host:
                states = [self._my_state()] + [r["raw"] for r in self.remote.values()]
                pk = HDR.pack(K_PLAYER, self.tick, len(states)) + b"".join(states)
                for a, _p in peers:
                    ses.net.send_unrel(a, pk)
            else:
                for a, _p in peers:
                    ses.net.send_unrel(a, mine)
        if self.host and self.now - self.t_snap >= 1.0 / SNAP_HZ:
            self.t_snap = self.now
            for pid, a in self.addr.items():
                r = self.remote.get(pid)
                if r is None or a not in ses.net.peers:
                    continue
                for pk in self._snapshot_for(r["x"], r["y"]):
                    ses.net.send_unrel(a, pk)
            hr = HDR.pack(K_WORLD, self.tick, 1) + WORLD.pack(s.clock.hour)
            for a, _p in peers:
                ses.net.send_unrel(a, hr)
        self._apply_remote(dt)
        if not self.host:
            self._apply_puppets(dt)

    # ------------------------------------------------------------------ receive
    def _rx(self, addr, data):
        if len(data) < HDR.size:
            return
        kind, _tick, n = HDR.unpack_from(data)
        off = HDR.size
        try:
            if kind == K_PLAYER:
                for _ in range(n):
                    raw = data[off:off + PLAYER.size]
                    off += PLAYER.size
                    t = PLAYER.unpack(raw)
                    pid = t[0]
                    if self.host:
                        owner = next((p for p, pl in self.ses.players.items() if pl["addr"] == addr), None)
                        if owner != pid:
                            continue                        # a guest may only speak for itself
                        self.addr[pid] = addr
                    elif pid == self.pid:
                        continue
                    r = self.remote.setdefault(pid, {"body": None})
                    r.update(raw=raw, flags=t[1], kind=t[2], color=t[3], tx=t[4], ty=t[5], th=t[6], vx=t[7], vy=t[8], z=t[9], aux=t[10],
                             hp=t[11], wi=t[12], atk=t[13], lik=t[14], seen=self.now)
                    if "x" not in r:
                        r["x"], r["y"], r["h"] = t[4], t[5], t[6]
            elif self.host:
                return
            elif kind == K_CARS:
                for _ in range(n):
                    t = CAR.unpack_from(data, off)
                    off += CAR.size
                    self._puppet(self.cars, t[0], t)
            elif kind == K_PEDS:
                for _ in range(n):
                    t = PED.unpack_from(data, off)
                    off += PED.size
                    self._puppet(self.peds, t[0], t)
            elif kind == K_BODIES:
                for _ in range(n):
                    t = BODY.unpack_from(data, off)
                    off += BODY.size
                    self._puppet(self.bods, t[0], t)
            elif kind == K_WORLD:
                self.sim.clock.hour = WORLD.unpack_from(data, off)[0] % 24.0
        except struct.error:
            pass

    def _puppet(self, store, wid, t):
        e = store.get(wid)
        if e is None:
            e = store[wid] = {"obj": None, "x": t[3 if store is not self.peds else 9], "y": t[4 if store is not self.peds else 10],
                              "h": t[5 if store is not self.peds else 11]}
        e["t"], e["seen"] = t, self.now

    # ------------------------------------------------------------------ remote players
    def _drop_remote(self, pid):
        r = self.remote.pop(pid, None)
        self.addr.pop(pid, None)
        if r and r.get("body") is not None and r["body"] in self.sim.bodies:
            self.sim.bodies.remove(r["body"])
        self.sim.remote_foot.pop(pid, None)

    def _apply_remote(self, dt):
        s, k = self.sim, min(1.0, dt * 14.0)
        for pid, r in list(self.remote.items()):
            if self.now - r["seen"] > 6.0 or pid not in self.ses.players:
                self._drop_remote(pid)
                continue
            r["x"] += (r["tx"] - r["x"]) * k
            r["y"] += (r["ty"] - r["y"]) * k
            r["h"] = _lerp_a(r["h"], r["th"], k)
            if r["flags"] & 1:                                           # on foot
                if r.get("body") is not None:
                    if r["body"] in s.bodies:
                        s.bodies.remove(r["body"])
                    r["body"] = None
                fl = r["flags"]
                frame = 2 if fl & 2 else (r["atk"] - 1 if r["atk"] else (None if fl & 8 else 12))
                s.remote_foot[pid] = dict(x=r["x"], y=r["y"], z=r["z"], h=r["h"], lik=r["lik"], anim=r["aux"], frame=frame,
                                          run=bool(fl & 4), weapon=WLIST[r["wi"] % len(WLIST)], pid=pid)
            else:
                s.remote_foot.pop(pid, None)
                b = r.get("body")
                if b is None or b.kind != r["kind"]:
                    if b is not None and b in s.bodies:
                        s.bodies.remove(b)
                    kind = r["kind"] % len(vehicles.HALF_L)
                    b = r["body"] = actors.Body(r["x"], r["y"], r["h"], kind, r["color"])
                    b.remote, b.empty, b.name = True, False, self.ses.players.get(pid, {}).get("name", "?")
                    s.bodies.append(b)
                elif b not in s.bodies:
                    s.bodies.append(b)
                b.x, b.y, b.h, b.vx, b.vy, b.wheel = r["x"], r["y"], r["h"], r["vx"], r["vy"], r["aux"]
                b.az = r["z"] or None
                b.health = float(r["hp"])
                b.w = 0.0

    # ------------------------------------------------------------------ guest: puppets for NPCs
    def _apply_puppets(self, dt):
        s, w = self.sim, self.sim.w
        k = min(1.0, dt * 14.0)
        cars = s.traffic.cars
        cars.clear()
        for wid in [i for i, e in self.cars.items() if self.now - e["seen"] > 1.0]:
            del self.cars[wid]
        for e in self.cars.values():
            t = e["t"]
            c = e["obj"]
            if c is None:
                c = e["obj"] = actors.Car()
                for sl in actors.Car.__slots__:
                    if not hasattr(c, sl):
                        setattr(c, sl, 0.0)
                c.kind, c.color = t[1], t[2]
                c.e, c.lane, c.lidx, c.nxt, c.blk, c.arr, c.stn, c.dwell, c.rq = 0, 0, 0, None, None, None, None, None, None
            e["x"] += (t[3] - e["x"]) * k
            e["y"] += (t[4] - e["y"]) * k
            e["h"] = _lerp_a(e["h"], t[5], k)
            c.x, c.y, c.h, c.gz, c.v, c.str, c.pitch, c.roll = e["x"], e["y"], e["h"], t[6], t[7], t[8] / 1000.0, t[9] / 1000.0, t[10] / 1000.0
            cars.append(c)
        plist = s.peds.list
        plist.clear()
        for wid in [i for i, e in self.peds.items() if self.now - e["seen"] > 1.0]:
            del self.peds[wid]
        for e in self.peds.values():
            t = e["t"]
            p = e["obj"]
            if p is None:
                p = e["obj"] = actors.Ped()
                p.say_t = 1e9                                           # puppets never speak: the host decides that
            e["x"] += (t[9] - e["x"]) * k
            e["y"] += (t[10] - e["y"]) * k
            e["h"] = _lerp_a(e["h"], t[11], k)
            p.mode = MODES[t[1] % len(MODES)]
            p.arch, p.shirt, p.skin, p.pose = t[2], t[3], t[4], POSES[t[5] % len(POSES)]
            p.vault, p.vault_up = (1.0 if t[6] & 1 else 0.0), bool(t[6] & 2)
            p.atk_t, p.atk_kind, p.v = (0.2 if t[6] & 4 else 0.0), t[7], t[8] / 20.0
            p.x, p.y, p.h, p.spin, p.anim, p.hy = e["x"], e["y"], e["h"], 0.0, t[12], t[13]
            plist.append(p)
        keep = [b for b in s.bodies if not getattr(b, "puppet", False)]
        for wid in [i for i, e in self.bods.items() if self.now - e["seen"] > 1.0]:
            del self.bods[wid]
        for e in self.bods.values():
            t = e["t"]
            b = e["obj"]
            if b is None:
                b = e["obj"] = actors.Body(t[3], t[4], t[5], t[1] % len(vehicles.HALF_L), t[2])
                b.remote = b.puppet = True
                b.empty = False
            e["x"] += (t[3] - e["x"]) * k
            e["y"] += (t[4] - e["y"]) * k
            e["h"] = _lerp_a(e["h"], t[5], k)
            b.x, b.y, b.h = e["x"], e["y"], e["h"]
            b.az = t[6] or None
            b.wheel, b.pitch, b.roll, b.door = t[8] / 1000.0, t[9] / 1000.0, t[10] / 1000.0, t[11]
            b.exploded, b.siren, b.braking = bool(t[12] & 1), bool(t[12] & 2), bool(t[12] & 8)
            b.burn = 1.0 if t[12] & 4 else 0.0
            b.health = t[13] / 2.55
            b.vx, b.vy = math.cos(b.h) * t[7], math.sin(b.h) * t[7]
            keep.append(b)
        s.bodies = keep


def spawn(sim, world, ses):
    """Everyone starts at the place the host chose, in a row along the road (called before the walker gets out of the car)."""
    import places
    from geo import project
    info = ses.start_info or {}
    pl = places.FALLBACK[int(info.get("spawn", 0)) % len(places.FALLBACK)]
    x, y = project(pl[1], pl[2])
    q = world.nearest_drive_point(x, y, 2000)
    if not q:
        return None
    x, y, h = q[0] + math.cos(q[2]) * 7.0 * ses.pid, q[1] + math.sin(q[2]) * 7.0 * ses.pid, q[2]
    sim.car.x, sim.car.y, sim.car.h = x, y, h
    sim.car.az = world.level(x, y, 1e9)
    sim.car.lx, sim.car.ly = x, y
    sim.safe = (x, y, h)
    return x, y
