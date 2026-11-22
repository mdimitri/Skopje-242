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
from collections import deque
import math
import struct
import time

import actors
import mp
import vehicles

STATE_HZ, SNAP_HZ = 20.0, 15.0
NET_RATE_PERIOD, NET_RATE_WINDOW = 0.25, 10.0
R_CARS, R_PEDS, R_BODIES = 320.0, 140.0, 320.0
JOIN_D, LEAVE_D = 560.0, 700.0                  # two players see the same part of the world when closer than 2 x max view (300 m); hysteresis
REGION_TIMEOUT = 0.9                            # resume local simulation before any individual puppet expires
REGION_EDGE = R_PEDS / 2                         # stay local if the authority's coverage is too far behind our position
PUPPET_TIMEOUT = 2.0                            # one lost chunk must not erase all its entities
ALL = 255
K_PLAYER, K_CARS, K_PEDS, K_BODIES, K_WORLD, K_REGION = 1, 2, 3, 4, 5, 6
REGION_KINDS = (K_CARS, K_PEDS, K_BODIES)
HDR = struct.Struct("!BIBBB")
PLAYER = struct.Struct("!BBBBfffffffBBBBI")    # pid flags kind color x y h vx vy z aux hp weapon atk lik money
CAR = struct.Struct("!HBBfffffhhh")            # id kind color x y h z v str*1000 pitch*1000 roll*1000
PED = struct.Struct("!HBBBBBBBBfffff")         # id mode arch shirt skin pose flags atk v*20 x y h(+spin) anim hy
BODY = struct.Struct("!HBBfffffhhhfBB")        # id kind color x y h z speed wheel*1000 pitch*1000 roll*1000 door flags health*2.55
WORLD = struct.Struct("!f")
REGION = struct.Struct("!ffHHH")               # interest center and entity counts by kind, including empty sets
ENTITY_LAYOUT = {K_CARS: CAR, K_PEDS: PED, K_BODIES: BODY}
MODES = ["walk", "dead", "flee", "rage", "air", "ko", "fight", "brawl", "queue", "board", "alight", "play", "sit"]
WLIST = ["fist"] + sorted(actors.WEAPONS)
POSES = [None, "spray", "work", "cpr"]
MAX_PKT = 1000


PED_HIT_MODES = ("ko", "dead", "air", "flee", "fight")


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _lerp_a(a, b, k):
    return a + _wrap(b - a) * k


def _newer(tick, previous):
    return previous is None or 0 < ((tick - previous) & 0xFFFFFFFF) < 0x80000000


def _motion(e, x, y, h, vx, vy, now, k):
    lead = min(0.14, max(0.0, now - e["seen"]) + 0.035)
    e["x"] += (x + vx * lead - e["x"]) * k
    e["y"] += (y + vy * lead - e["y"]) * k
    e["h"] = _lerp_a(e["h"], h, k)


def _clampb(v, lo=0, hi=255):
    return max(lo, min(hi, int(v)))


def _s16(v):
    return max(-32000, min(32000, int(v * 1000)))


def _signal_bits(side):
    return 64 if side < 0 else 128 if side > 0 else 0


def _signal_side(bits):
    return -1 if bits & 64 else 1 if bits & 128 else 0


def _myhp(s):
    return s.car.health if s.mode == "car" and s.car is not None else s.walker.health


def _myh(s):
    return s.car.h if s.mode == "car" and s.car is not None else s.walker.h


class Game:
    def __init__(self, sim, session):
        self.sim, self.ses = sim, session
        session.net.unrel_reorder = True
        session.net.probe_rtt = True
        session.net.start_heartbeat()
        self.net_at = time.monotonic()
        self.net_bytes = session.net.bytes_rx, session.net.bytes_tx
        self.net_rates = deque([(self.net_at, 0.0, 0.0)])
        self.net_ping = None
        self.host = session.role == "host"
        self.pid = session.pid
        sim.client = False
        sim.remote_foot = {}
        self.tick = 0
        self.t_state = self.t_snap = 0.0
        self.ids, self.next_id = {}, 1                 # host: object id() -> wire id
        self.remote = {}                               # pid -> dict(target state, body)
        self.now = 0.0
        self._reset_puppets()
        self.player_tick, self.world_tick = None, None
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
        self._mig = session.migrated
        sim.w.mp_out = []                                 # props broken here (world.break_point) go to the others

    # ------------------------------------------------------------------ own state
    def _my_state(self):
        s = self.sim
        if s.mode == "car" and s.car is not None:
            b = s.car
            flags = ((32 if getattr(s, "riding", None) is not None else 0) | _signal_bits(b.indicator)
                     | (2 if getattr(b, "siren", False) else 0) | (4 if b.honk_t > 1.0 else 0))
            return PLAYER.pack(self.pid, flags, _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h, b.vx, b.vy,
                               b.az if b.az is not None else 0.0, b.wheel, _clampb(b.health), 0, 0, _clampb(getattr(s, "lik", 0)), max(0, int(s.money)))
        wk = s.walker
        wi = WLIST.index(wk.weapon) if wk.weapon in WLIST else 0
        fl = 1 | (2 if wk.health <= 0 else 0) | (4 if wk.speed > 6.0 else 0) | (8 if wk.moving else 0)
        return PLAYER.pack(self.pid, fl, 0, 0, wk.x, wk.y, wk.h, wk.vx, wk.vy, wk.az if wk.az is not None else 0.0, wk.anim,
                           _clampb(wk.health), wi, self._atk_byte(wk), _clampb(getattr(s, "lik", 0)), max(0, int(s.money)))

    @staticmethod
    def _atk_byte(wk):
        """0 idle; 1 + kind for a punch / kick; 64 + 0..7 for the frames of a bat / chain swing."""
        if wk.atk_t <= 0:
            return 0
        if wk.weapon in actors.SWINGERS and wk.ammo > 0:
            return 64 + min(7, int((1.0 - wk.atk_t / actors.SWING_T) * 8))
        return wk.atk_kind + 1

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
                ents.append(CAR.pack(self._wid(c), _clampb(c.kind), _clampb(c.color, 0, 63) | _signal_bits(c.indicator), c.x, c.y, c.h, c.gz, c.v,
                                     _s16(c.str), _s16(c.pitch), _s16(c.roll)))
        out += self._chunks(K_CARS, ents, CAR.size, dst)
        nc = len(ents)
        ents, r2 = [], R_PEDS ** 2
        for p in s.peds.list:
            if (p.x - gx) ** 2 + (p.y - gy) ** 2 < r2:
                mode = MODES.index(p.mode) if p.mode in MODES else 0
                fl = (1 if p.vault > 0 else 0) | (2 if p.vault_up else 0) | (4 if p.atk_t > 0 else 0) | (8 if p.traffic_run else 0)
                pose = POSES.index(p.pose) if p.pose in POSES else 0
                ents.append(PED.pack(self._wid(p), mode, _clampb(p.arch), _clampb(p.shirt), _clampb(p.skin), pose, fl,
                                     _clampb(p.atk_kind), _clampb((math.hypot(p.vx, p.vy) if p.traffic_run else abs(p.v)) * 20),
                                     p.x, p.y, p.h + p.spin, p.anim, p.hy))
        out += self._chunks(K_PEDS, ents, PED.size, dst)
        np = len(ents)
        ents, r2 = [], R_BODIES ** 2
        for b in s.bodies:
            if b.player_car or getattr(b, "remote", False):
                continue
            moving = b.vx * b.vx + b.vy * b.vy > 0.09
            if (moving or b.ctl is not None or b.service or b.burn > 0 or b.exploded) and (b.x - gx) ** 2 + (b.y - gy) ** 2 < r2:
                fl = (1 if b.exploded else 0) | (2 if b.siren else 0) | (4 if b.burn > 0 else 0) | (8 if b.braking else 0) | (16 if (b.ctl is not None or b.service) else 0) | (32 if getattr(b, "bus_line", None) else 0)
                fl |= _signal_bits(b.indicator)
                ents.append(BODY.pack(self._wid(b), _clampb(b.kind), _clampb(b.color), b.x, b.y, b.h,
                                      b.az if b.az is not None else 0.0, math.hypot(b.vx, b.vy), _s16(b.wheel), _s16(b.pitch),
                                      _s16(b.roll), b.door, fl, _clampb(b.health * 2.55)))
        out += self._chunks(K_BODIES, ents, BODY.size, dst)
        out.append(HDR.pack(K_REGION, self.tick, 1, self.pid, dst) + REGION.pack(gx, gy, nc, np, len(ents)))
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
        while self.host and ses.late:                               # somebody joined the running game: give him what is already broken / taken
            self._late_sync(ses.late.pop())
        if ses.migrated != self._mig:                               # the host left mid-game and somebody took over: re-sync
            self._mig = ses.migrated
            for pid in list(self.remote):
                self._drop_remote(pid)
            if s.client:
                self._to_authority()
            s.traffic.extra = s.peds.extra = []
            self.host, self.pid = ses.role == "host", ses.pid
            self.ids, self.next_id, self.addr, self.auth, self.byid = {}, 1, {}, {}, {}
            self.player_tick, self.world_tick = None, None
            self._reset_puppets()
            self._view()
        if ses.state == "closed" and not self.over:                 # the host left / the line dropped: carry on alone, nothing frozen
            self.over = True
            if ses.net is not None:
                ses.net.stop_heartbeat()
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
        self._props(s)
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
        self._update_region()
        fol = self._followers()
        foci = {p: (self.remote[p]["tx"], self.remote[p]["ty"]) for p in fol}
        s.traffic.extra = s.peds.extra = list(foci.values())
        if self.now - self.t_snap >= 1.0 / SNAP_HZ:
            self.t_snap = self.now
            for f, (gx, gy) in foci.items():
                for pk in self._snapshot_for(gx, gy, f):
                    self._send_to(f, pk)
            if self.host:
                ses.net.broadcast_unrel(HDR.pack(K_WORLD, self.tick, 1, 0, ALL) + WORLD.pack(s.clock.hour))
        if self.now - self.t_ids >= 1.0:
            self.t_ids = self.now
            self._prune_ids()
        self._apply_remote(dt)
        self._sample_network(ses.net)
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
                           "hp": r["hp"], "foot": bool(r["flags"] & 1),
                           "talk": self.ses.voice is not None and self.ses.voice.speaking(pid),
                           "lik": r.get("lik", 0), "vx": r.get("vx", 0.0), "vy": r.get("vy", 0.0), "atk": r.get("atk", 0), "money": r.get("money", 0),
                           "dead": bool(r["flags"] & 2), "wi": r.get("wi", 0), "lvl": self.ses.voice.level_of(pid) if self.ses.voice is not None else 0.0})
        me = self.ses.players.get(self.pid, {"color": 0})
        near = [q for q in pl if q["hp"] > 0]
        if near:
            q = min(near, key=lambda q: (q["x"] - s.focus()[0]) ** 2 + (q["y"] - s.focus()[1]) ** 2)
            s.respawn_hint = (q["x"], q["y"])
        else:
            s.respawn_hint = None
        v = self.ses.voice
        mine = {"pid": -1, "name": me.get("name", ""), "color": mp.COLORS[me["color"] % 4], "lik": getattr(s, "lik", 0),
                "hp": _myhp(s), "foot": s.mode != "car", "h": _myh(s), "vx": s.focus()[2], "vy": s.focus()[3], "x": s.focus()[0], "y": s.focus()[1],
                "atk": 1 if (s.mode != "car" and s.walker.atk_t > 0) else 0, "money": int(s.money), "dead": s.mode != "car" and s.walker.health <= 0,
                "talk": bool(v is not None and v.talking), "lvl": float(v.level) if v is not None else 0.0}
        s.mp_view = {"players": pl, "me": mine, "me_color": mp.COLORS[me["color"] % 4],
                     "team": int(s.money) + sum(r.get("money", 0) for r in self.remote.values()),
                     "network": None if self.over else (self.net_rates, NET_RATE_WINDOW, self.net_ping)}

    def _sample_network(self, net):
        now = time.monotonic()
        elapsed = now - self.net_at
        if elapsed >= NET_RATE_PERIOD:
            rx, tx = net.bytes_rx, net.bytes_tx
            self.net_rates.append((now, (rx - self.net_bytes[0]) / (1000 * elapsed),
                                   (tx - self.net_bytes[1]) / (1000 * elapsed)))
            self.net_at, self.net_bytes = now, (rx, tx)
            addresses = (p["addr"] for p in self.ses.players.values()) if self.host else (self.ses._target,)
            self.net_ping = net.ping_ms(now, addresses)
            cutoff = now - NET_RATE_WINDOW
            while len(self.net_rates) > 1 and self.net_rates[1][0] <= cutoff:
                self.net_rates.popleft()

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
                self.cars[wid]["taken"] = True
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

    def _late_sync(self, pid):
        """Host: a player joined after the start. He gets the stolen parked cars (gone) and the broken props so far, in chunks."""
        a = self.ses.players.get(pid, {}).get("addr")
        if a is None:
            return
        s = self.sim
        gone = sorted(i for i in s.gone if isinstance(i, int))
        brk = [[b[0], b[1]] for b in s.w.broken]
        for k in range(0, len(gone), 150):
            self.ses.net.send_rel(a, {"t": "late", "g": gone[k:k + 150]})
        for k in range(0, len(brk), 80):
            self.ses.net.send_rel(a, {"t": "late", "b": brk[k:k + 80]})

    def _apply_late(self, m):
        s = self.sim
        for i in m.get("g", ())[:150]:
            if isinstance(i, int):
                s.gone.add(i)
                self._gone_seen.add(i)
                s.bodies = [b for b in s.bodies if not (b.parked_idx == i and b.empty and b is not s.car)]
        for xy in m.get("b", ())[:80]:
            if isinstance(xy, list) and len(xy) == 2:
                self._apply_brk({"x": xy[0], "y": xy[1]})

    def _props(self, s):
        """Trees, posts and street furniture I knocked over are broken on every other PC as well."""
        out = s.w.mp_out
        if out:
            for x, y in out[:20]:
                self._bcast({"t": "brk", "x": x, "y": y})
            del out[:]

    def _apply_brk(self, m):
        w = self.sim.w
        try:
            x, y = float(m["x"]), float(m["y"])
        except (KeyError, TypeError, ValueError):
            return
        for e in w.points_near(x, y, 0.05):
            if e[0] == x and e[1] == y:
                keep, w.mp_out = w.mp_out, None                     # do not send it back
                try:
                    w.break_point(e)
                finally:
                    w.mp_out = keep
                self.sim.ev("prop_break", x=x, y=y, kind="mid", fly=False)
                return

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
        elif t == "brk":
            self._apply_brk(m)
        elif t == "late" and not self.host:
            self._apply_late(m)
        elif t == "cwreck" and m.get("to") == self.pid:
            self._apply_car_wreck(m)
        elif t == "phit" and m.get("to") == self.pid:
            self._apply_ped_hit(m)
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

    def _report_ped(self, wid, e, p):
        """Follower: whatever this PC's player did to a puppet pedestrian (punch, bullet, blast) goes to the authority, which owns the real one."""
        au = self.auth.get(self.pid, self.pid)
        d, m = 40.0 - p.hp, p.mode
        if au == self.pid or e["obj"] is not p or "mode" not in e:
            return
        if d > 0.01 or (m != e["mode"] and m in PED_HIT_MODES):
            self._route(au, {"t": "phit", "to": au, "i": wid, "d": round(max(d, 0.0), 1), "m": m,
                             "vx": round(p.vx, 1), "vy": round(p.vy, 1)})

    def _report_cars(self, cars):
        """Follower: a puppet traffic car that this PC wrecked (rammed, shot, blasted) is wrecked on the authority too."""
        au = self.auth.get(self.pid, self.pid)
        if au == self.pid:
            return
        now = set(map(id, cars))
        for wid, e in self.cars.items():
            c = e["obj"]
            if c is not None and id(c) not in now and not e.get("lost"):
                e["lost"] = True
                if not e.get("taken"):
                    self._route(au, {"t": "cwreck", "to": au, "i": wid})

    def _apply_car_wreck(self, m):
        s = self.sim
        c = self.byid.get(m.get("i"))
        if c is None or c not in s.traffic.cars:
            return
        b = s.traffic.make_body(c)
        s.traffic.cars.remove(c)
        b.empty = True
        b.health = min(b.health, 30.0)
        b.dirty = True
        s.bodies.append(b)

    def _apply_ped_hit(self, m):
        """Authority: a follower hurt one of my pedestrians."""
        s = self.sim
        p = self.byid.get(m.get("i"))
        try:
            d, vx, vy, mode = float(m["d"]), float(m["vx"]), float(m["vy"]), str(m["m"])
        except (KeyError, TypeError, ValueError):
            return
        if p is None or p not in s.peds.list or p.mode in ("dead", "air", "ko") or not 0 <= d <= 400:
            return                                                   # late or duplicate report: ignore
        p.hp -= d
        p.vx, p.vy = max(-12.0, min(12.0, vx)), max(-12.0, min(12.0, vy))
        if mode == "ko" or (mode == "dead" and p.hp > 0):
            p.hp = min(p.hp, 0.0)
            s._knock_out(p)
        elif mode == "dead" or p.hp <= 0:
            p.mode, p.t = "dead", actors.clear_secs(s)
            s.stats["peds"] += 1
            s.ev("ped_shot", x=p.x, y=p.y)
        elif mode == "air":
            p.mode, p.t, p.hy, p.hv = "air", actors.clear_secs(s), 0.2, 6.0
        elif mode in ("flee", "fight") and p.mode in ("walk", "flee", "rage"):
            p.mode, p.t = mode, 4.0
        s.ev("hit", x=p.x, y=p.y, kick=True)

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
            if pid in self.ses.players:
                pos[pid] = (r["tx"], r["ty"])
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
            au = 0 if 0 in m else min(prev or m)
            for p in m:
                new[p] = au
        if new != self.auth:
            self._set_auth(new)
            self.ses.net.broadcast_rel({"t": "grp", "a": {str(k): v for k, v in new.items()}})

    def _set_auth(self, new):
        old = self.auth.get(self.pid, self.pid)
        self.auth = new
        if new.get(self.pid, self.pid) != old:
            if self.sim.client:
                self._to_authority()
            else:
                self._reset_puppets()

    def _reset_puppets(self):
        self.cars, self.peds, self.bods = {}, {}, {}
        self.region_frames = {}
        self.region_complete = {}
        self.region_center = None
        self.region_tick = None
        self.region_seen = -math.inf
        self.region_activity = {}

    def _update_region(self):
        leader = self.auth.get(self.pid, self.pid)
        if leader == self.pid:
            return
        x, y = self.sim.focus()[:2]
        nearby = any(self.auth.get(p) == leader and self.now - r["seen"] < 2 * REGION_TIMEOUT
                     and (r["tx"] - x) ** 2 + (r["ty"] - y) ** 2 < LEAVE_D ** 2
                     for p, r in self.remote.items())
        covered = (self.region_center is None or
                   (self.region_center[0] - x) ** 2 + (self.region_center[1] - y) ** 2 < REGION_EDGE ** 2)
        fresh = self.now - self.region_seen <= REGION_TIMEOUT
        if self.region_center is not None:
            fresh = fresh and all(self.now - self.region_activity.get(k, -math.inf) <= REGION_TIMEOUT
                                  for k in (K_CARS, K_PEDS))
        if self.sim.client:
            if not (nearby and covered and fresh):
                self._to_authority()
        elif nearby and covered and fresh:
            if self.region_center is None:
                ready = bool(self.cars and self.peds)   # older peers send entity packets without a region manifest
            else:
                ready = all(k in self.region_complete and self.now - self.region_complete[k][1] <= REGION_TIMEOUT
                            and (self.region_complete[k][2] - x) ** 2 + (self.region_complete[k][3] - y) ** 2 < REGION_EDGE ** 2
                            for k in (K_CARS, K_PEDS))
            if ready:
                self._to_follower()

    def _to_follower(self):
        """Switch once replacement state is available, blending similar nearby actors from their local poses."""
        s = self.sim
        self._seed_poses(self.cars, s.traffic.cars, lambda t: (t[1], t[2] & 63), lambda c: (c.kind, c.color), 8)
        self._seed_poses(self.peds, s.peds.list, lambda t: (t[2], t[3], t[4]), lambda p: (p.arch, p.shirt, p.skin), 5)
        s.client = True
        s.traffic.cars.clear()
        s.peds.list.clear()
        s.bodies = [b for b in s.bodies if b is s.car or getattr(b, "remote", False) and not getattr(b, "puppet", False)
                    or (b.speed < 0.3 and b.ctl is None and not b.service)]

    @staticmethod
    def _seed_poses(store, local, wire_appearance, appearance, radius):
        by_appearance = {}
        for obj in local:
            by_appearance.setdefault(appearance(obj), []).append(obj)
        for e in store.values():
            candidates = by_appearance.get(wire_appearance(e["t"]), [])
            best = min(candidates, key=lambda o: (o.x - e["x"]) ** 2 + (o.y - e["y"]) ** 2, default=None)
            if best is not None and (best.x - e["x"]) ** 2 + (best.y - e["y"]) ** 2 < radius ** 2:
                e["x"], e["y"], e["h"] = best.x, best.y, best.h
                candidates.remove(best)

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
            if p.vault > 0 and p.vault_path is None:
                p.vault = p.hy = 0.0
            if p.say_t > 1e8:
                p.say_t = 10.0
            if p.dead or s.peds.adopt(p, keep_heading=True):
                s.peds.list.append(p)
        controlled = {id(e["obj"]) for e in self.bods.values() if e["t"][12] & 16}
        keep = []
        for b in s.bodies:
            if getattr(b, "puppet", False):
                if b is s.riding:
                    s.exit_car()
                    continue
                if id(b) in controlled:
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
        kind, tick, n, src, dst = HDR.unpack_from(data)
        off = HDR.size
        if self.host and dst not in (0, ALL):                       # a guest's packet for another guest: pass it on
            a = self.ses.players.get(dst, {}).get("addr")
            if a is not None and a in self.ses.net.peers:
                self.ses.net.send_unrel(a, data)
            return
        if kind in ENTITY_LAYOUT or kind == K_REGION:
            if dst == self.pid and src != self.pid and src == self.auth.get(self.pid):
                self._region_packet(kind, tick, n, data)
            return
        try:
            if kind == K_PLAYER:
                if not self.host:
                    if not _newer(tick, self.player_tick):
                        return
                    self.player_tick = tick
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
                    if self.host and not _newer(tick, r.get("tick")):
                        continue
                    r.update(raw=raw, flags=t[1], kind=t[2], color=t[3], tx=t[4], ty=t[5], th=t[6], vx=t[7], vy=t[8], z=t[9], aux=t[10],
                             hp=t[11], wi=t[12], atk=t[13], lik=t[14], money=t[15], seen=self.now, tick=tick)
                    if "x" not in r or (r["x"] - t[4]) ** 2 + (r["y"] - t[5]) ** 2 > REGION_EDGE ** 2:
                        r["x"], r["y"], r["h"] = t[4], t[5], t[6]
            elif kind == K_WORLD and not self.host and _newer(tick, self.world_tick):
                self.sim.clock.hour = WORLD.unpack_from(data, off)[0] % 24.0
                self.world_tick = tick
        except struct.error:
            pass

    def _region_packet(self, kind, tick, n, data):
        stores = (self.cars, self.peds, self.bods)
        if kind == K_REGION:
            if len(data) != HDR.size + REGION.size:
                return
            x, y, *counts = REGION.unpack_from(data, HDR.size)
            if _newer(tick, self.region_tick):
                self.region_tick, self.region_center = tick, (x, y)
                for k, count in zip(REGION_KINDS, counts):
                    if count == 0:
                        self.region_activity[k] = self.now
        else:
            layout = ENTITY_LAYOUT[kind]
            if len(data) != HDR.size + n * layout.size:
                return
            last = self.region_complete.get(kind)
            if last is not None and not _newer(tick, last[0]):
                return
            self.region_activity[kind] = self.now
        self.region_seen = self.now
        frame = self.region_frames.setdefault(tick, {})
        if len(self.region_frames) > 12:
            del self.region_frames[next(iter(self.region_frames))]
        if kind == K_REGION:
            frame[K_REGION] = x, y, counts
        else:
            store = stores[kind - K_CARS]
            ids = frame.setdefault(kind, set())
            for i in range(n):
                t = layout.unpack_from(data, HDR.size + i * layout.size)
                ids.add(t[0])
                self._puppet(store, t, tick, 9 if kind == K_PEDS else 3)
        if K_REGION in frame:
            x, y, counts = frame[K_REGION]
            for k, store, count in zip(REGION_KINDS, stores, counts):
                last = self.region_complete.get(k)
                ids = frame.get(k, ())
                if len(ids) == count and (last is None or _newer(tick, last[0])):
                    self.region_complete[k] = tick, self.now, x, y
                    for wid, e in list(store.items()):
                        if wid not in ids and not _newer(e["tick"], tick):
                            del store[wid]

    def _puppet(self, store, t, tick, pos):
        wid = t[0]
        e = store.get(wid)
        if e is None:
            e = store[wid] = {"obj": None, "x": t[pos], "y": t[pos + 1], "h": t[pos + 2], "tick": None}
        if _newer(tick, e["tick"]):
            e["t"], e["seen"], e["tick"] = t, self.now, tick

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
            _motion(r, r["tx"], r["ty"], r["th"], r["vx"], r["vy"], self.now, k)
            fl = r["flags"]
            if fl & 32:                                                 # riding a bus: nothing to draw (the bus is drawn anyway)
                if r.get("body") is not None:
                    if r["body"] in s.bodies:
                        s.bodies.remove(r["body"])
                    r["body"] = None
                s.remote_foot.pop(pid, None)
            elif fl & 1:                                                # on foot
                if r.get("body") is not None:
                    if r["body"] in s.bodies:
                        s.bodies.remove(r["body"])
                    r["body"] = None
                a = r["atk"]
                frame = 2 if fl & 2 else ((60 + (a - 64) % 8 if a >= 64 else a - 1) if a else (None if fl & 8 else 12))
                wn = WLIST[r["wi"] % len(WLIST)]
                if a and not r.get("atk_prev") and not fl & 2 and wn in actors.WEAPONS:           # a shot: the muzzle noise
                    s.ev("gunfire", x=r["x"], y=r["y"], kind=wn)
                if a and not r.get("atk_prev") and not fl & 2 and (wn == "fist" or wn in actors.MELEE):   # a swing just started: this PC hears it too
                    s.ev("kick" if a == 6 else "punch" if wn == "fist" else "swing", x=r["x"], y=r["y"], hit=False, weapon=wn)
                r["atk_prev"] = a
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
                b.indicator = _signal_side(fl)
                b.siren = bool(fl & 2)
                if fl & 4 and not r.get("honk_prev"):                  # he just pressed the horn: this PC hears it
                    s.ev("horn", body=b)
                r["honk_prev"] = bool(fl & 4)
                if b.kind == vehicles.ARTIC_BUS:
                    actors.tow(b)
                b.az = r["z"] or None
                b.health = float(r["hp"])
                b.w = 0.0

    # ------------------------------------------------------------------ guest: puppets for NPCs
    def _apply_puppets(self, dt):
        s = self.sim
        k = min(1.0, dt * 14.0)
        cars = s.traffic.cars
        self._report_cars(cars)
        cars.clear()
        for wid in [i for i, e in self.cars.items() if self.now - e["seen"] > PUPPET_TIMEOUT]:
            del self.cars[wid]
        for e in self.cars.values():
            t = e["t"]
            c = e["obj"]
            if c is None:
                c = e["obj"] = actors.Car()
                for sl in actors.Car.__slots__:
                    if not hasattr(c, sl):
                        setattr(c, sl, 0.0)
                c.kind, c.color = t[1], t[2] & 63
                c.e, c.lane, c.lidx = 0, 0, 0
                c.nxt = c.blk = c.arr = c.stn = c.dwell = None
            if e.get("lost"):
                continue                                              # wrecked on this PC; waiting for the authority to drop it
            _motion(e, t[3], t[4], t[5], math.cos(t[5]) * t[7], math.sin(t[5]) * t[7], self.now, k)
            c.x, c.y, c.h, c.gz, c.v, c.str, c.pitch, c.roll = e["x"], e["y"], e["h"], t[6], t[7], t[8] / 1000.0, t[9] / 1000.0, t[10] / 1000.0
            c.indicator = _signal_side(t[2])
            cars.append(c)
        plist = s.peds.list
        plist.clear()
        for wid in [i for i, e in self.peds.items() if self.now - e["seen"] > PUPPET_TIMEOUT]:
            del self.peds[wid]
        for wid, e in self.peds.items():
            t = e["t"]
            p = e["obj"]
            if p is None:
                p = e["obj"] = actors.Ped()
                p.say_t = 1e9                                           # puppets never speak: the host decides that
            self._report_ped(wid, e, p)
            p.mode = MODES[t[1] % len(MODES)]
            e["mode"] = p.mode
            p.hp, p.vx, p.vy = 40.0, 0.0, 0.0
            p.arch, p.shirt, p.skin, p.pose = t[2], t[3], t[4], POSES[t[5] % len(POSES)]
            p.vault, p.vault_up = (1.0 if t[6] & 1 else 0.0), bool(t[6] & 2)
            p.traffic_run = bool(t[6] & 8)
            p.atk_t, p.atk_kind, p.v = (0.2 if t[6] & 4 else 0.0), t[7], t[8] / 20.0
            v = p.v if p.mode in ("walk", "flee") else 0.0
            _motion(e, t[9], t[10], t[11], math.cos(t[11]) * v, math.sin(t[11]) * v, self.now, k)
            p.x, p.y, p.h, p.spin, p.anim, p.hy = e["x"], e["y"], e["h"], 0.0, t[12], t[13]
            plist.append(p)
        keep = [b for b in s.bodies if not getattr(b, "puppet", False)]
        if s.car is not None and getattr(s.car, "puppet", False) and s.car not in keep:
            keep.append(s.car)                                       # the bus I ride on stays in the world
        for wid in [i for i, e in self.bods.items() if self.now - e["seen"] > PUPPET_TIMEOUT]:
            del self.bods[wid]
        for e in self.bods.values():
            t = e["t"]
            b = e["obj"]
            if b is None:
                b = e["obj"] = actors.Body(t[3], t[4], t[5], t[1] % len(vehicles.HALF_L), t[2])
                b.remote = b.puppet = True
                b.empty = False
            _motion(e, t[3], t[4], t[5], math.cos(t[5]) * t[7], math.sin(t[5]) * t[7], self.now, k)
            b.x, b.y, b.h = e["x"], e["y"], e["h"]
            b.az = t[6] or None
            b.wheel, b.pitch, b.roll, b.door = t[8] / 1000.0, t[9] / 1000.0, t[10] / 1000.0, t[11]
            b.exploded, b.siren, b.braking = bool(t[12] & 1), bool(t[12] & 2), bool(t[12] & 8)
            b.indicator = _signal_side(t[12])
            b.burn = 1.0 if t[12] & 4 else 0.0
            b.bus_line = "mp" if t[12] & 32 else None
            b.health = t[13] / 2.55
            b.vx, b.vy = math.cos(b.h) * t[7], math.sin(b.h) * t[7]
            if b.kind == vehicles.ARTIC_BUS:
                actors.tow(b)
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
