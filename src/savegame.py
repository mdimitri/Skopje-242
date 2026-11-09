"""Save slots (saves/slot<N>.json): player, car, money, time of day, pickups, stats.  Traffic and pedestrians respawn."""
from texts import TXT
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "saves")
SLOTS = 5
VERSION = 1


def _path(n):
    return os.path.join(DIR, f"slot{n}.json")


def capture(sim, cfg):
    c, wk = sim.car, sim.walker
    d = {"v": VERSION, "t": time.time(), "mode": sim.mode, "lik": getattr(sim, "lik", 0), "money": sim.money,
         "hour": sim.clock.hour, "stats": dict(sim.stats), "gone": sorted(sim.gone),
         "pickups": [list(p) for p in sim.pickups],
         "car": {"x": c.x, "y": c.y, "h": c.h, "kind": c.kind, "color": c.color, "health": c.health,
                 "fuel": getattr(c, "fuel", 1.0)}}
    if wk is not None:
        d["walker"] = {"x": wk.x, "y": wk.y, "h": wk.h, "health": wk.health, "weapon": wk.weapon, "guns": dict(wk.guns)}
    return d


def save(sim, cfg, n):
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(_path(n) + ".tmp", "w", encoding="utf-8") as f:
            json.dump(capture(sim, cfg), f)
        os.replace(_path(n) + ".tmp", _path(n))
        return True
    except Exception:  # noqa: BLE001
        return False


def read(n):
    try:
        with open(_path(n), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if d.get("v") == VERSION else None
    except Exception:  # noqa: BLE001
        return None


def summary(n):
    """One line for the menu: 'dd.mm HH:MM  лик  пари  час' or 'празно'."""
    d = read(n)
    if not d:
        return TXT("savegame.0001")
    import characters
    h = d.get("hour", 0.0)
    return ((f"{time.strftime('%d.%m %H:%M', time.localtime(d['t']))}   {characters.LIKOVI[d['lik'] % len(characters.LIKOVI)][1]}   {d['money']}" + TXT("savegame.0002") + f'{int(h):02d}:{int(h % 1 * 60):02d}'))


def restore(sim, cfg, d):
    """Apply a save to a running Sim.  Returns (x, y) to snap the camera to."""
    import actors
    import characters
    sim.lik = d["lik"]
    characters.set_hero(sim.lik)
    sim.money = d["money"]
    sim.clock.hour = cfg["hour"] = float(d["hour"])
    sim.stats.update(d.get("stats", {}))
    sim.gone = set(d.get("gone", []))
    if d.get("pickups"):
        sim.pickups = [list(p) for p in d["pickups"]]
    for b in sim.bodies:
        b.player_car = False
    c = sim.car
    s = d["car"]
    c.x, c.y, c.h, c.vx, c.vy, c.w = s["x"], s["y"], s["h"], 0.0, 0.0, 0.0
    c.kind, c.color, c.health, c.fuel = s["kind"], s["color"], s["health"], s.get("fuel", 1.0)
    c.az = None
    c.burn, c.exploded, c.drown, c.skid = 0.0, False, 0.0, None
    c.dirty = True
    c.model = None
    c.name = actors.CAR_NAMES[c.kind]
    if d["mode"] == "foot" and d.get("walker"):
        w = d["walker"]
        wk = actors.Walker(w["x"], w["y"], w["h"])
        wk.health, wk.weapon, wk.guns = w["health"], w["weapon"], dict(w["guns"])
        sim.walker = wk
        sim.mode = "foot"
        c.empty, c.player_car = True, False
        sim.safe = (wk.x, wk.y, 0.0)
        return wk.x, wk.y
    sim.walker = None
    sim.mode = "car"
    c.empty, c.player_car = False, True
    sim.safe = (c.x, c.y, c.h)
    sim.safe_z = None
    return c.x, c.y


def new_character(sim, i):
    """Back at the character screen: a fresh start for the chosen character at the spawn, new random seed, no leftovers."""
    import characters
    import random
    characters.apply(sim, i)
    reset_world(sim, random.SystemRandom().randrange(1 << 30))
    for k in sim.stats:
        sim.stats[k] = 0
    if sim.walker is not None:
        sim.walker.health, sim.walker.guns, sim.walker.weapon = 100.0, {}, "fist"
    sim.car.health = 100.0


def reset_world(sim, seed):
    """Forget the old run: emergency calls and their vehicles, traffic, pedestrians, player position; reseed everything."""
    sv = sim.services
    for j in list(sv.jobs):
        sv._abort(j)
    sv.jobs.clear()
    sim.bodies[:] = [b for b in sim.bodies if b is sim.car or not (getattr(b, "siren", False) or getattr(b, "service", False) or b.ctl is not None)]
    sim.events.clear()
    sim.rng.seed(seed)
    sv.rng.seed(seed + 1)
    sx, sy, sh = sim.w.spawn
    c = sim.car
    c.x, c.y, c.h, c.vx, c.vy, c.w = sx, sy, sh, 0.0, 0.0, 0.0
    c.az, c.burn, c.exploded, c.drown, c.skid, c.dirty = None, 0.0, False, 0.0, None, True
    c.empty, c.player_car = False, True
    for b in sim.bodies:
        if b is not c:
            b.player_car = False
    sim.walker, sim.mode = None, "car"
    sim.jack = sim.riding = sim.train_ride = None
    sim.respawn_t = 0.0
    sim.safe, sim.safe_z = (sx, sy, sh), None
    sim.traffic.cars.clear()
    sim.peds.list.clear()
    for _ in range(sim.base_cars * 6):
        if len(sim.traffic.cars) < sim.base_cars:
            sim.traffic.spawn(sx, sy, 60, 330)
    for _ in range(sim.base_peds * 6):
        if len(sim.peds.list) < sim.base_peds:
            sim.peds.spawn(sx, sy)
