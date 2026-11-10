"""In-game multiplayer sync: every PC simulates the world around its own player; players who come close share one simulation.

Players closer than JOIN_D form a group (they leave it again beyond LEAVE_D).  The host works the groups out and tells everybody
who the group's authority is (the lowest-numbered member, kept while it stays in the group).  The authority simulates traffic,
pedestrians and buses round every member (Traffic/Peds.extra) and sends each follower what is near that follower; followers run
with Sim.client = True and draw those as puppets.  A player alone is simply his own authority.  When a follower leaves, the
puppets are adopted into real cars / pedestrians (Traffic.adopt / Peds.adopt) so nothing pops.  All traffic goes through the host
(star network; the host forwards packets addressed to another guest).
Everyone sends own state at STATE_HZ; other players are a car body (sim.bodies, flagged remote) or a walker (sim.remote_foot).
Packet = kind(1) tick(4) count(1) src(1) dst(1) + entries; dst 255 = everybody.
"""
import math
import struct
import time

import actors
import mp
import vehicles

STATE_HZ, SNAP_HZ = 20.0, 15.0
R_CARS, R_PEDS, R_BODIES = 320.0, 140.0, 320.0
JOIN_D, LEAVE_D = 560.0, 700.0                  # two players see the same part of the world when closer than 2 x max view (300 m); hysteresis
ALL = 255
K_PLAYER, K_CARS, K_PEDS, K_BODIES, K_WORLD = 1, 2, 3, 4, 5
HDR = struct.Struct("!BIBBB")
PLAYER = struct.Struct("!BBBBfffffffBBBBI")    # pid flags kind color x y h vx vy z aux hp weapon atk lik money
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
        sim.client = False
        sim.remote_foot = {}
        self.tick = 0
        self.t_state = self.t_snap = 0.0
        self.ids, self.next_id = {}, 1                 # host: object id() -> wire id
        self.remote = {}                               # pid -> dict(target state, body)
        self.cars, self.peds, self.bods = {}, {}, {}   # guest: wire id -> puppet (+ target, seen)
        self.now = 0.0
        self.addr = {}                                 # host: pid -> addr
        self.auth = {}                                 # pid -> pid of the authority of that player's group
        self.t_grp = 0.0
        self.alive, self.last_hit = True, None            # my own death tracking (stats, kill credit)
        sim.pvp = bool((session.start_info or {}).get("ff", False))
        self.deaths = self.kills = 0
        self.byid = {}                                    # authority: wire id -> object (to drop a car a follower stole)
        self.drop_body = None                             # the car I left standing (shared as a dropped car)
        self._gone_seen = set(sim.gone)
        self.over = False                                 # the session closed under us (handled once in update)
        self.t_ids = 0.0

    # ------------------------------------------------------------------ own state
    def _my_state(self):
        s = self.sim
        if s.mode == "car" and s.car is not None:
            b = s.car
            return PLAYER.pack(self.pid, 32 if getattr(s, "riding", None) is not None else 0, _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h, b.vx, b.vy,
                               b.az if b.az is not None else 0.0, b.wheel, _clampb(b.health), 0, 0, _clampb(getattr(s, "lik", 0)), max(0, int(s.money)))
        wk = s.walker
        wi = WLIST.index(wk.weapon) if wk.weapon in WLIST else 0
        fl = 1 | (2 if wk.health <= 0 else 0) | (4 if wk.speed > 6.0 else 0) | (8 if wk.moving else 0)
        return PLAYER.pack(self.pid, fl, 0, 0, wk.x, wk.y, wk.h, wk.vx, wk.vy, wk.az if wk.az is not None else 0.0, wk.anim,
                           _clampb(wk.health), wi, (wk.atk_kind + 1) if wk.atk_t > 0 else 0, _clampb(getattr(s, "lik", 0)), max(0, int(s.money)))

    # ------------------------------------------------------------------ host: build snapshots
    def _wid(self, obj):
        k = id(obj)
        i = self.ids.get(k)
        if i is None:
            i = self.ids[k] = self.next_id
            self.byid[i] = obj
            self.next_id = self.next_id % 65000 + 1
            while self.next_id in self.byid:               # after the counter wraps: never hand out an id still in use
                self.next_id = self.next_id % 65000 + 1
        return i

    def _prune_ids(self):
        """Forget the wire ids of cars / pedestrians / bodies that left the world (they were kept, and kept alive, for ever)."""
        s = self.sim
        live = {id(o) for o in s.traffic.cars} | {id(o) for o in s.peds.list} | {id(o) for o in s.bodies}
        self.byid = {i: o for i, o in self.byid.items() if id(o) in live}
        self.ids = {id(o): i for i, o in self.byid.items()}

    def _chunks(self, kind, entries, size, dst):
        per = (MAX_PKT - HDR.size) // size
        for i in range(0, len(entries), per):
            part = entries[i:i + per]
            yield HDR.pack(kind, self.tick, len(part), self.pid, dst) + b"".join(part)

    def _snapshot_for(self, gx, gy, dst):
        s = self.sim
        out = []
        r2 = R_CARS ** 2
        ents = []
        for c in s.traffic.cars:
            if (c.x - gx) ** 2 + (c.y - gy) ** 2 < r2:
                ents.append(CAR.pack(self._wid(c), _clampb(c.kind), _clampb(c.color), c.x, c.y, c.h, c.gz, c.v,
                                     _s16(c.str), _s16(c.pitch), _s16(c.roll)))
        out += self._chunks(K_CARS, ents, CAR.size, dst)
        ents, r2 = [], R_PEDS ** 2
        for p in s.peds.list:
            if (p.x - gx) ** 2 + (p.y - gy) ** 2 < r2:
                mode = MODES.index(p.mode) if p.mode in MODES else 0
                fl = (1 if p.vault > 0 else 0) | (2 if p.vault_up else 0) | (4 if p.atk_t > 0 else 0)
                pose = POSES.index(p.pose) if p.pose in POSES else 0
                ents.append(PED.pack(self._wid(p), mode, _clampb(p.arch), _clampb(p.shirt), _clampb(p.skin), pose, fl,
                                     _clampb(p.atk_kind), _clampb(abs(getattr(p, "v", 0.0)) * 20), p.x, p.y, p.h + p.spin, p.anim, p.hy))
        out += self._chunks(K_PEDS, ents, PED.size, dst)
        ents, r2 = [], R_BODIES ** 2
        for b in s.bodies:
            if b.player_car or getattr(b, "remote", False):
                continue
            moving = b.vx * b.vx + b.vy * b.vy > 0.09
            if (moving or b.ctl is not None or b.service or b.burn > 0 or b.exploded) and (b.x - gx) ** 2 + (b.y - gy) ** 2 < r2:
                fl = (1 if b.exploded else 0) | (2 if b.siren else 0) | (4 if b.burn > 0 else 0) | (8 if b.braking else 0) | (16 if (b.ctl is not None or b.service) else 0) | (32 if getattr(b, "bus_line", None) else 0)
                ents.append(BODY.pack(self._wid(b), _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h,
                                      b.az if b.az is not None else 0.0, math.hypot(b.vx, b.vy), _s16(b.wheel), _s16(b.pitch),
                                      _s16(b.roll), b.door, fl, _clampb(b.health * 2.55)))
        out += self._chunks(K_BODIES, ents, BODY.size, dst)
        return out

    # ------------------------------------------------------------------ per-frame
    def update(self, dt):
        """Call once per frame right after sim.update (before drawing)."""
        s, ses = self.sim, self.ses
        self.now += dt
        for kind, addr, body in ses.update():
            if kind == "unrel":
                self._rx(addr, body)
            elif kind == "rel" and isinstance(body, dict):
                self._rel(body, addr)
            elif kind == "gone" and self.host:
                for pid, a in list(self.addr.items()):
                    if a == addr:
                        self._drop_remote(pid)
        if ses.state == "closed" and not self.over:                 # the host left / the line dropped: carry on alone, nothing frozen
            self.over = True
            for pid in list(self.remote):
                self._drop_remote(pid)
            if s.client:
                self._to_authority()
            s.traffic.extra = s.peds.extra = []
            self._view()
            s.ev("mp_closed", why=ses.error)
        if ses.state != "playing" and not (self.host and ses.state == "lobby"):
            return
        if not self.auth:
            self.auth = {pid: pid for pid in ses.players}          # everybody starts on his own
        self._pvp(s)
        self._shared(s)
        self.tick = (self.tick + 1) & 0xFFFFFFFF
        if self.now - self.t_state >= 1.0 / STATE_HZ:
            self.t_state = self.now
            if self.host:
                states = [self._my_state()] + [r["raw"] for r in self.remote.values()]
                ses.net.broadcast_unrel(HDR.pack(K_PLAYER, self.tick, len(states), 0, ALL) + b"".join(states))
            else:
                ses.net.broadcast_unrel(HDR.pack(K_PLAYER, self.tick, 1, self.pid, 0) + self._my_state())
        if self.host and self.now - self.t_grp >= 0.5:
            self.t_grp = self.now
            self._regroup()
        fol = self._followers()
        s.traffic.extra = s.peds.extra = [(self.remote[p]["x"], self.remote[p]["y"]) for p in fol]     # simulate round them too
        if self.now - self.t_snap >= 1.0 / SNAP_HZ:
            self.t_snap = self.now
            for f in fol:
                for pk in self._snapshot_for(self.remote[f]["x"], self.remote[f]["y"], f):
                    self._send_to(f, pk)
            if self.host:
                ses.net.broadcast_unrel(HDR.pack(K_WORLD, self.tick, 1, 0, ALL) + WORLD.pack(s.clock.hour))
        if self.now - self.t_ids >= 10.0:
            self.t_ids = self.now
            self._prune_ids()
        self._apply_remote(dt)
        self._view()
        if s.client:
            self._apply_puppets(dt)

    def _view(self):
        """What the HUD / map / name labels need: the other players, and the team's money (everybody's added up)."""
        s = self.sim
        pl = []
        for pid, r in self.remote.items():
            p = self.ses.players.get(pid)
            if p is not None:
                pl.append({"pid": pid, "name": p["name"], "color": mp.COLORS[p["color"] % 4], "x": r["x"], "y": r["y"], "h": r["h"],
                           "hp": r["hp"], "foot": bool(r["flags"] & 1)})
        me = self.ses.players.get(self.pid, {"color": 0})
        near = [q for q in pl if q["hp"] > 0]
        if near:
            q = min(near, key=lambda q: (q["x"] - s.focus()[0]) ** 2 + (q["y"] - s.focus()[1]) ** 2)
            s.respawn_hint = (q["x"], q["y"])
        else:
            s.respawn_hint = None
        s.mp_view = {"players": pl, "me_color": mp.COLORS[me["color"] % 4],
                     "team": int(s.money) + sum(r.get("money", 0) for r in self.remote.values())}

    # ------------------------------------------------------------------ shared things: parked cars taken, stolen traffic cars, dropped cars
    def _bcast(self, obj, skip=None):
        """Reliable message for everybody else (through the host)."""
        obj = dict(obj, all=1)
        net = self.ses.net
        if self.host:
            net.broadcast_rel(obj, skip=skip)
        else:
            net.send_rel(self.ses._target, obj)

    def _shared(self, s):
        new = set(s.gone) - self._gone_seen
        for i in new:
            self._bcast({"t": "gone", "i": i})
        self._gone_seen |= new
        for c in s.mp_taken:
            wid = next((i for i, e in self.cars.items() if e["obj"] is c), None)
            au = self.auth.get(self.pid, self.pid)
            if wid is not None and au != self.pid:
                self._route(au, {"t": "take", "to": au, "i": wid})
        s.mp_taken = []
        lb = getattr(s, "last_exit", None)
        want = lb if (s.mode == "foot" and lb is not None and lb in s.bodies and lb.empty and lb.alive) else None
        if want is not self.drop_body:
            if self.drop_body is not None:
                self._bcast({"t": "undrop", "p": self.pid})
            if want is not None:
                self._bcast({"t": "drop", "p": self.pid, "k": want.kind, "c": want.color, "x": round(want.x, 2), "y": round(want.y, 2),
                             "h": round(want.h, 3), "hp": round(want.health)})
            self.drop_body = want
        for b in s.bodies:                                           # somebody else's dropped car that I took: tell its owner
            if getattr(b, "drop_pid", None) is not None and not b.remote:
                self._route(b.drop_pid, {"t": "claim", "to": b.drop_pid})
                b.drop_pid = None

    def _drop_of(self, pid):
        for b in self.sim.bodies:
            if getattr(b, "drop_pid", None) == pid and b.remote:
                self.sim.bodies.remove(b)
                return

    # ------------------------------------------------------------------ player vs player
    def _route(self, to, obj):
        """Reliable message for player `to`: the host handles it itself or passes it on."""
        net = self.ses.net
        if to == self.pid:
            self._rel(obj)
        elif self.host:
            a = self.ses.players.get(to, {}).get("addr")
            if a is not None and a in net.peers:
                net.send_rel(a, obj)
        else:
            net.send_rel(self.ses._target, obj)

    def _pvp(self, s):
        """Hits I landed on other players go out; my own death is noticed (stats + credit for whoever hit me last)."""
        out, s.pvp_out = s.pvp_out, []
        for pid, kind, amt in out:
            self._route(pid, {"t": "dmg", "to": pid, "k": kind, "a": round(amt, 1), "f": self.pid})
        hp = (s.walker.health if s.mode == "foot" else s.car.health) if (s.walker or s.car) else 100
        if self.alive and hp <= 0:
            self.alive = False
            self.deaths += 1
            self.ses.prof.add(deaths=1)
            if self.last_hit and self.now - self.last_hit[1] < 8.0:
                self._route(self.last_hit[0], {"t": "kill", "to": self.last_hit[0], "v": self.pid})
        elif not self.alive and hp > 0:
            self.alive = True

    def _rel(self, m, addr=None):
        t = m.get("t")
        if m.get("all") and self.host and addr is not None:
            self.ses.net.broadcast_rel(m, skip=addr)                 # for everybody: pass it on
        to = m.get("to")
        if to is not None and to != self.pid:                        # for another player (take / claim / dmg / kill): the host passes it on
            if self.host and addr is not None:
                self._route(to, m)
            return
        s = self.sim
        if t == "gone":
            i = m.get("i")
            if isinstance(i, int):
                s.gone.add(i)
                self._gone_seen.add(i)
                s.bodies = [b for b in s.bodies if not (b.parked_idx == i and b.empty and b is not s.car)]
        elif t == "drop":
            p = m.get("p")
            if p != self.pid and p in self.ses.players:
                self._drop_of(p)
                try:
                    b = actors.Body(float(m["x"]), float(m["y"]), float(m["h"]), int(m["k"]) % len(vehicles.HALF_L), int(m["c"]))
                except (KeyError, TypeError, ValueError):
                    return
                b.remote, b.drop_pid, b.empty, b.health = True, p, True, float(m.get("hp", 100))
                b.name = self.ses.players[p]["name"] + "'s " + b.name
                s.bodies.append(b)
        elif t == "undrop":
            self._drop_of(m.get("p"))
        elif t == "claim" and m.get("to") == self.pid:
            if self.drop_body is not None and self.drop_body in s.bodies and self.drop_body.empty:
                s.bodies.remove(self.drop_body)
            self.drop_body = None
            self._bcast({"t": "undrop", "p": self.pid})
        elif t == "take" and m.get("to") == self.pid:
            c = self.byid.get(m.get("i"))
            if c is not None and c in s.traffic.cars:
                s.traffic.cars.remove(c)
        if t == "grp" and not self.host:
            self._set_auth({int(k): int(v) for k, v in m["a"].items()})
        elif t in ("dmg", "kill"):
            to = m.get("to")
            if to != self.pid:
                self._route(to, m)                                 # host: for another guest
            elif t == "dmg":
                self.take_hit(int(m.get("f", -1)), str(m.get("k", "")), float(m.get("a", 0)))
            else:
                self.kills += 1
                self.ses.prof.add(kills=1)
                self.sim.ev("pvp_kill", victim=m.get("v"))

    def take_hit(self, frm, kind, amt):
        """Somebody hit me. Each player owns his own health: the attacker only reports."""
        s = self.sim
        if not s.pvp or amt <= 0 or amt > 200:
            return
        self.last_hit = (frm, self.now)
        if s.mode == "foot":
            wk = s.walker
            if wk.health <= 0:
                return
            wk.health -= amt
            wk.hurt_t = 0.4
            if wk.health <= 0:
                wk.cause = "fight" if kind in ("punch", "kick") else ("boom" if kind == "boom" else "car" if kind == "car" else "shot")
        elif s.car is not None and s.car.health > 0:
            s.car.health -= amt * (0.5 if kind != "boom" else 1.0)
            s.car.dirty = True
        s.ev("hit", x=s.focus()[0], y=s.focus()[1], kick=kind in ("kick", "boom"))

    def _send_to(self, pid, pk):
        net = self.ses.net
        if self.host:
            a = self.ses.players.get(pid, {}).get("addr")
            if a is not None:
                net.send_unrel(a, pk)
        else:
            net.send_unrel(self.ses._target, pk)             # the host passes it on

    # ------------------------------------------------------------------ groups
    def _followers(self):
        return [p for p, a in self.auth.items() if a == self.pid and p != self.pid and p in self.remote]

    def _regroup(self):
        """Host: players closer than JOIN_D share a world (LEAVE_D to part again); the lowest-numbered authority keeps the group."""
        fx, fy = self.sim.focus()[:2]
        pos = {0: (fx, fy)}
        for pid, r in self.remote.items():
            pos[pid] = (r["x"], r["y"])
        pids = sorted(pos)
        par = {p: p for p in pids}

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for i, a in enumerate(pids):
            for b in pids[i + 1:]:
                same = self.auth.get(a) is not None and self.auth.get(a) == self.auth.get(b)
                if math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) < (LEAVE_D if same else JOIN_D):
                    par[find(a)] = find(b)
        groups = {}
        for p in pids:
            groups.setdefault(find(p), []).append(p)
        new = {}
        for m in groups.values():
            prev = [p for p in m if self.auth.get(p) == p]
            au = min(prev) if prev else min(m)
            for p in m:
                new[p] = au
        if new != {p: self.auth.get(p) for p in new}:
            self._set_auth(new)
            self.ses.net.broadcast_rel({"t": "grp", "a": {str(k): v for k, v in new.items()}})

    def _set_auth(self, new):
        old = self.auth.get(self.pid, self.pid)
        self.auth = new
        nw = new.get(self.pid, self.pid)
        if nw == old:
            return
        if nw != self.pid:
            self._to_follower()
        elif self.sim.client:
            self._to_authority()

    def _reset_puppets(self):
        self.cars, self.peds, self.bods = {}, {}, {}

    def _to_follower(self):
        """Joined (or switched) a group: my own cars / pedestrians go, the authority's take their place."""
        s = self.sim
        s.client = True
        s.traffic.cars.clear()
        s.peds.list.clear()
        s.bodies = [b for b in s.bodies if b is s.car or getattr(b, "remote", False) and not getattr(b, "puppet", False)
                    or (b.speed < 0.3 and b.ctl is None and not b.service)]
        self._reset_puppets()

    def _to_authority(self):
        """Left the group (or became its authority): the puppets turn into real cars, pedestrians and bodies, so nothing pops."""
        s = self.sim
        cars = [e["obj"] for e in self.cars.values() if e["obj"] is not None]
        peds = [e["obj"] for e in self.peds.values() if e["obj"] is not None]
        s.traffic.cars.clear()
        s.peds.list.clear()
        for c in cars:
            if s.traffic.adopt(c):
                s.traffic.cars.append(c)
        for p in peds:
            if p.mode in ("queue", "board", "alight", "play", "sit"):
                p.mode = "walk"
            if p.say_t > 1e8:
                p.say_t = 10.0
            if p.dead or s.peds.adopt(p):
                s.peds.list.append(p)
        keep = []
        for b in s.bodies:
            if getattr(b, "puppet", False):
                ctl = next((e["t"][12] & 16 for e in self.bods.values() if e["obj"] is b), 0)
                if ctl:
                    continue                                    # a bus / emergency vehicle needs the host's dispatcher: gone
                b.remote = b.puppet = False
            keep.append(b)
        s.bodies = keep
        s.client = False
        self._reset_puppets()

    # ------------------------------------------------------------------ receive
    def _rx(self, addr, data):
        if len(data) < HDR.size:
            return
        kind, _tick, n, src, dst = HDR.unpack_from(data)
        off = HDR.size
        if self.host and dst not in (0, ALL):                       # a guest's packet for another guest: pass it on
            a = self.ses.players.get(dst, {}).get("addr")
            if a is not None and a in self.ses.net.peers:
                self.ses.net.send_unrel(a, data)
            return
        if kind in (K_CARS, K_PEDS, K_BODIES) and not (self.sim.client and src == self.auth.get(self.pid)):
            return                                                  # only the authority of my group may tell me about the world
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
                             hp=t[11], wi=t[12], atk=t[13], lik=t[14], money=t[15], seen=self.now)
                    if "x" not in r:
                        r["x"], r["y"], r["h"] = t[4], t[5], t[6]
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
            elif kind == K_WORLD and not self.host:
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
        self._drop_of(pid)

    def _apply_remote(self, dt):
        s, k = self.sim, min(1.0, dt * 14.0)
        for pid, r in list(self.remote.items()):
            if self.now - r["seen"] > 6.0 or pid not in self.ses.players:
                self._drop_remote(pid)
                continue
            r["x"] += (r["tx"] - r["x"]) * k
            r["y"] += (r["ty"] - r["y"]) * k
            r["h"] = _lerp_a(r["h"], r["th"], k)
            if r["flags"] & 32:                                          # riding a bus: nothing to draw (the bus is drawn anyway)
                if r.get("body") is not None:
                    if r["body"] in s.bodies:
                        s.bodies.remove(r["body"])
                    r["body"] = None
                s.remote_foot.pop(pid, None)
            elif r["flags"] & 1:                                         # on foot
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
                    b.remote, b.empty, b.pid, b.name = True, False, pid, self.ses.players.get(pid, {}).get("name", "?")
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
        if s.car is not None and getattr(s.car, "puppet", False) and s.car not in keep:
            keep.append(s.car)                                       # the bus I ride on stays in the world
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
            b.bus_line = "mp" if t[12] & 32 else None
            b.health = t[13] / 2.55
            b.vx, b.vy = math.cos(b.h) * t[7], math.sin(b.h) * t[7]
            if b is not s.car:
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
