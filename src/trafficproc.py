"""AI traffic on its own CPU core.

The game loop is one Python thread (the GIL), and the traffic AI (actors.Traffic.update) is the biggest single piece of
the simulation.  Here it runs in a worker process that owns the cars.  The game keeps a Car "proxy" for every one of them
in sim.traffic.cars, so every reader (renderer, night lights, sound, peds, collisions, HUD...) works unchanged.

Every frame, at the point where Traffic.update used to run:
  1. the game sees what it changed itself since the last frame (cars removed: crashed, blown up, jacked; cars added:
     spawned on the game side),
  2. takes the worker's answer to the previous frame and copies it into the proxies,
  3. sends this frame's inputs (dt, focus, bodies, people on foot, signals, level crossings, clock) and goes on.
The worker computes while the game does pedestrians, rendering and the rest of the frame, so the cars it shows are one
frame (about 16 ms) behind the inputs, which nobody can see.

Anything the worker cannot do (it fails to start, raises, or dies) puts the cars back into the game process: the proxies
are ordinary Car objects with the full state, so Traffic.update simply takes over.
SK242_TRAFFIC_PROC=0 turns it off."""
import os
import random
import sys
import time
import traceback

import actors

ON = os.environ.get("SK242_TRAFFIC_PROC", "1") != "0"
SYNC = tuple(s for s in actors.Car.__slots__ if s not in ("blk", "uid"))      # blk points at another object: worker-side only
PED_MODES = ("walk", "flee", "rage", "brawl")                                 # the people Traffic.update brakes for


# ------------------------------------------------------------------------------------------------ worker side
class _Clock:
    SECONDS_PER_HOUR = 55.0

    def __init__(self):
        self.hour, self.speed = 12.0, 1.0


class _Trains:
    def __init__(self, by_edge):
        self.by_edge, self.closed = by_edge, set()

    def stop_at(self, ei, d, s, L):
        for es in self.by_edge.get(ei, ()):
            if (ei, es) in self.closed:
                ahead = (es if d == 1 else L - es) - s
                if -1.0 < ahead < 60.0:
                    return ahead - 5.0
        return None


class _Peds:
    def __init__(self):
        self.list = []


class _Sim:
    """The few things of actors.Sim that Traffic and Stations read."""

    def __init__(self, world, seed):
        import trains
        self.w = world
        self.rng = random.Random(seed)
        self.clock = _Clock()
        self.aggro = 1
        self.trains = _Trains(trains.Trains(world).by_edge)
        self.peds = _Peds()
        self.fx = self.fy = 0.0
        self.traffic = None

    def focus(self):
        return self.fx, self.fy, 0.0, 0.0


def _state(c):
    return tuple(getattr(c, s) for s in SYNC)


def _set(c, vals):
    for s, v in zip(SYNC, vals):
        setattr(c, s, v)


def _serve(conn, path, seed):
    try:
        import world as world_mod
        import signals
        import stations
        w = world_mod.World(path)
        sim = _Sim(w, seed)
        tr = actors.Traffic(w, sim.rng, 0)
        tr.sim = sim
        sim.traffic = tr
        tr.signals = signals.Signals(w)
        tr.stn = stations.Stations(sim)
        conn.send(("ready", os.getpid()))
    except Exception:  # noqa: BLE001
        conn.send(("err", traceback.format_exc()))
        return
    by_uid = {}
    uid_next = 1                                                  # worker uids are odd, the game's even
    bodies, peds = {}, {}
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        try:
            t0 = time.perf_counter()
            kills, adds, pokes = msg["kill"], msg["add"], msg["poke"]
            if kills:
                tr.cars = [c for c in tr.cars if c.uid not in kills]
                for u in kills:
                    by_uid.pop(u, None)
            for u, vals in adds:
                c = actors.Car.__new__(actors.Car)
                _set(c, vals)
                c.uid, c.blk = u, None
                by_uid[u] = c
                tr.cars.append(c)
            for u, k, v in pokes:
                c = by_uid.get(u)
                if c is not None:
                    setattr(c, k, v)
            tr.target = msg["target"]
            sim.aggro = msg["aggro"]
            sim.clock.hour, sim.clock.speed = msg["hour"], msg["cspeed"]
            sim.trains.closed = msg["closed"]
            sim.fx, sim.fy = msg["fx"], msg["fy"]
            tr.signals.t, tr.signals.pre = msg["sig_t"], msg["sig_pre"]
            bl = []
            for k, (x, y, h, vx, vy, kind, trh, air, service, out) in enumerate(msg["bodies"]):
                b = bodies.get(k)
                if b is None:
                    b = bodies[k] = actors.Body.__new__(actors.Body)
                b.x, b.y, b.h, b.vx, b.vy, b.kind, b.trh, b.air, b.service, b.out = x, y, h, vx, vy, kind, trh, air, service, out
                bl.append(b)
            pl = []
            for k, (x, y, mode) in enumerate(msg["peds"]):
                p = peds.get(k)
                if p is None:
                    p = peds[k] = actors.Ped.__new__(actors.Ped)
                p.x, p.y, p.mode = x, y, mode
                pl.append(p)
            wk = None
            if msg["walker"] is not None:
                wk = actors.Walker.__new__(actors.Walker)
                wk.x, wk.y, wk.health = msg["walker"]
            tr.update(msg["dt"], msg["fx"], msg["fy"], bl, pl, wk)
            for c in tr.cars:
                if getattr(c, "uid", None) is None:
                    c.uid = uid_next
                    uid_next += 2
                    by_uid[c.uid] = c
            if len(by_uid) > len(tr.cars) + 64:                   # despawned cars: forget them
                live = {c.uid for c in tr.cars}
                for u in [u for u in by_uid if u not in live]:
                    del by_uid[u]
            shop = []
            for j in tr.stn.shoppers:                             # drivers who got out at a petrol station (Stations._shop)
                shop.append((j["car"].uid, j["ped"], {k: v for k, v in j.items() if k not in ("car", "ped")}))
            tr.stn.shoppers = []
            sim.peds.list.clear()
            conn.send(("ok", [(c.uid, _state(c)) for c in tr.cars], tr.signals.pre, shop, tr.despawned,
                       (time.perf_counter() - t0) * 1000.0))
        except Exception:  # noqa: BLE001
            conn.send(("err", traceback.format_exc()))
            return


# ------------------------------------------------------------------------------------------------ game side
class TrafficProc:
    def __init__(self, sim, world):
        import multiprocessing as mp
        self.sim, self.tr = sim, sim.traffic
        self.by_uid = {}
        self.uid_next = 2
        self.published = set()
        self.pokes = []
        self.pending = False
        self.ok = False
        self.ms = 0.0                       # the worker's own time for the last frame (ms)
        self.wait_ms = 0.0                  # how long the game waited for it in the last frame
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        main = sys.modules.get("__main__")
        mf = getattr(main, "__file__", None)
        try:
            if mf is not None:
                del main.__file__                              # the spawned worker must not re-run main.py (it opens a window)
            self.proc = ctx.Process(target=_serve, args=(child, world.path, random.randrange(1 << 30)), daemon=True,
                                    name="sk242-traffic")
            self.proc.start()
        finally:
            if mf is not None:
                main.__file__ = mf
        child.close()

    def wait_ready(self, timeout=120.0):
        """Block (while loading) until the worker has its world; False -> stay in-process."""
        if self.conn.poll(timeout):
            try:
                r = self.conn.recv()
            except (EOFError, OSError):
                r = ("err", "the worker exited")
            if r[0] == "ready":
                self.ok = True
                print(f"[traffic] AI traffic runs in its own process (pid {r[1]})")
                return True
            print(f"[traffic] worker failed, traffic stays in the game process:\n{r[1]}")
        else:
            print("[traffic] worker did not start in time, traffic stays in the game process")
        self.stop()
        return False

    def stop(self):
        self.ok = False
        try:
            self.conn.send(None)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.join(0.5)
            if self.proc.is_alive():
                self.proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def poke(self, c, field, value):
        """The game changed one field of a traffic car (the worker owns the state): pass it on."""
        setattr(c, field, value)
        u = getattr(c, "uid", None)
        if self.ok and u is not None:
            self.pokes.append((u, field, value))

    def _fail(self, why):
        print(f"[traffic] worker lost ({why}); traffic is back in the game process")
        self.stop()

    def step(self, dt, fx, fy, bodies, peds, walker):
        """In place of Traffic.update.  -> False when the worker is gone (the caller runs Traffic.update itself)."""
        if not self.ok:
            return False
        tr, sim = self.tr, self.sim
        cur = tr.cars
        live = set()
        adds = []
        for c in cur:                                             # what the game itself changed since the last frame
            u = getattr(c, "uid", None)
            if u is None or u not in self.by_uid:
                if u is None:
                    u = c.uid = self.uid_next
                    self.uid_next += 2
                c.blk = None
                self.by_uid[u] = c
                adds.append((u, _state(c)))
            live.add(u)
        kills = self.published - live
        for u in kills:
            self.by_uid.pop(u, None)
        if self.pending:                                          # the worker's answer to the last frame
            t0 = time.perf_counter()
            try:
                r = self.conn.recv()
            except (EOFError, OSError) as e:
                self._fail(e)
                return False
            self.wait_ms = (time.perf_counter() - t0) * 1000.0
            self.pending = False
            if r[0] != "ok":
                self._fail(r[1])
                return False
            _ok, states, pre, shop, despawned, self.ms = r
            new_ids = {u for u, _v in states}
            keep = []
            for u, vals in states:
                if u in kills:
                    continue                                      # removed by the game meanwhile
                c = self.by_uid.get(u)
                if c is None:
                    c = actors.Car.__new__(actors.Car)
                    c.uid, c.blk = u, None
                    self.by_uid[u] = c
                _set(c, vals)
                keep.append(c)
            for u, _vals in adds:
                if u not in new_ids:
                    keep.append(self.by_uid[u])                   # added this frame: the worker hears of it now
            gone = [u for u in self.by_uid if u not in new_ids and u not in {a[0] for a in adds}]
            for u in gone:
                del self.by_uid[u]
            tr.cars[:] = keep                                     # same list object: anyone holding it sees the new cars
            tr.despawned = despawned
            if getattr(sim, "lights", None) is not None:
                sim.lights.pre = pre
            stn = getattr(sim, "stations", None)
            for u, p, j in shop:                                  # drivers walking to the petrol station shop
                c = self.by_uid.get(u)
                if c is not None and stn is not None:
                    sim.peds.list.append(p)
                    j.update(ped=p, car=c)
                    stn.shoppers.append(j)
        self.published = {c.uid for c in tr.cars}
        lights, trn = getattr(sim, "lights", None), getattr(sim, "trains", None)
        bl = [(b.x, b.y, b.h, b.vx, b.vy, b.kind, b.trh, b.air, b.service, b.out) for b in bodies]
        pl = [(p.x, p.y, p.mode) for p in peds if p.mode in PED_MODES]
        wk = (walker.x, walker.y, walker.health) if walker is not None else None
        msg = {"dt": dt, "fx": fx, "fy": fy, "kill": kills, "add": adds, "poke": self.pokes,
               "target": tr.target, "aggro": getattr(sim, "aggro", 1),
               "hour": sim.clock.hour, "cspeed": sim.clock.speed,
               "closed": trn.closed if trn is not None else set(),
               "sig_t": lights.t if lights is not None else 0.0, "sig_pre": lights.pre if lights is not None else {},
               "bodies": bl, "peds": pl, "walker": wk}
        self.pokes = []
        try:
            self.conn.send(msg)
        except (EOFError, OSError) as e:
            self._fail(e)
            return True                                           # this frame's cars are already in place
        self.pending = True
        return True


def start(sim, world):
    """Start the worker while loading (a process start must not land inside a frame).  -> TrafficProc or None."""
    if not ON or getattr(sim, "client", False) or (getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS")):
        return None
    try:
        return TrafficProc(sim, world)
    except Exception as e:  # noqa: BLE001
        print(f"[traffic] no worker process: {e}")
        return None

