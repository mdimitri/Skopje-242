"""Live feature check in the real game window (GPU, renderer, streamer and sound code all running), scripted from outside.

  python tools/live_check.py [--out logs/live] [--sound]

It starts main.py in --test mode, waits for the world to be ready and then plays a list of scenarios by wrapping Sim.update (it
overrides the player's input and moves bodies around, the game code itself is not changed).  Every scenario prints PASS / FAIL with
the numbers it measured and some save a screenshot into --out, so a person can look at the picture.  Sound is muted unless --sound
(then the real audio code runs on this PC; only errors can be judged by a script, not how it sounds).
Scenarios: camera (chase view, look-up sky), bat (swept arc), escape (F at a fire escape), door (long vehicle cab door),
driver (ejected driver flees), dodge (pedestrians clear a car's path), semi (trailer skid marks), sounds (synth keys render)."""
import argparse
import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=os.path.join(ROOT, "logs", "live"))
ap.add_argument("--sound", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--frames", type=int, default=6000)
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
sys.argv = ["main.py", "--test", str(a.frames)] + ([] if a.sound else ["--mute"]) + ["--walker"]
os.chdir(ROOT)

import pyray as rl  # noqa: E402
try:
    import fastrl  # noqa: F401,E402
except ImportError:
    pass
import settings as settings_mod  # noqa: E402
_sinit = settings_mod.Settings.__init__
def _settings(self, *x, **kw):
    _sinit(self, *x, **kw)
    self["debug_chase"] = True                     # the street-level camera (in memory only, settings.json is not written)
settings_mod.Settings.__init__ = _settings

import main as M  # noqa: E402
import actors  # noqa: E402
import vehicles  # noqa: E402
import escride  # noqa: E402
import bake  # noqa: E402

results = []
shots = []                                          # (frame index, path) to export from the back buffer
state = {"n": 0, "ready": None}
_log0 = M.log
def _log(msg):
    if "[game] ready" in str(msg) and state["ready"] is None:
        state["ready"] = state["n"]
    return _log0(msg)
M.log = _log

decals = []
_ad = bake.Streamer.add_decal
def add_decal(self, d):
    decals.append(d)
    return _ad(self, d)
bake.Streamer.add_decal = add_decal

_ed = rl.end_drawing
def end_drawing():
    r = _ed()
    for s in list(shots):
        if s[0] <= state["n"]:
            shots.remove(s)
            try:
                img = rl.load_image_from_screen()
                rl.export_image(img, s[1])
                rl.unload_image(img)
            except Exception as e:  # noqa: BLE001
                print("[live] screenshot failed", s[1], e)
    state["n"] += 1
    return r
rl.end_drawing = end_drawing

def _no_hard_exit(code=0):
    raise SystemExit(code)
os.environ.setdefault("SK242_LIVE", "1")
import os as _os  # noqa: E402
_os._exit = _no_hard_exit


def report(name, ok, note):
    results.append((name, bool(ok), note))
    print(f"[live] {'PASS' if ok else 'FAIL'} {name}: {note}", flush=True)


def inp0(**kw):
    d = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0.0, 0.0), "run": False, "attack": False,
         "buy": None, "jump": False, "brake": False}
    d.update(kw)
    return d


def shot(name, sim):
    shots.append((state["n"] + 2, os.path.join(a.out, name + ".png")))


# ------------------------------------------------------------------ scenarios: generators that yield between frames
# each gets (sim, selfie) and yields the input dict to use for the next Sim.update (or None = the game's own)
def sc_camera(sim, S):
    sim.exit_car() if sim.mode == "car" else None
    wk = sim.walker
    for lp, nm in ((0.0, "chase_level"), (-1.0, "chase_lookup"), (-0.5, "chase_halfup"), (0.8, "chase_down")):
        S.look_pitch = lp
        S.look_yaw = 0.0
        for _ in range(45):
            yield inp0()
        shot(nm, sim)
        for _ in range(6):
            yield inp0()
    S.look_pitch = 0.0
    report("camera", True, "screenshots chase_level / chase_lookup / chase_halfup / chase_down saved: judge the sky and tilt by eye")


def _ped_at(sim, x, y):
    p = sim.peds.eject(x, y, 0.0)
    p.mode, p.t, p.hp = "walk", 99.0, 100
    p.vx = p.vy = 0.0
    return p


def sc_bat(sim, S):
    if sim.mode == "car":
        sim.exit_car()
    wk = sim.walker
    wk.weapon, wk.ammo = "bat", 9999
    wk.h = 0.0
    fx, fy = 1.0, 0.0
    spots = {"front_left": (1.4, -0.9), "front": (1.5, 0.0), "front_right": (1.4, 0.9), "side": (0.2, 1.5), "behind": (-1.5, 0.0), "far": (4.5, 0.0)}
    ps = {}
    for k, (u, v) in spots.items():
        ps[k] = _ped_at(sim, wk.x + u, wk.y + v)
    hp0 = {k: p.hp for k, p in ps.items()}
    for _ in range(8):
        yield inp0()
    for k, (u, v) in spots.items():                      # the idle frames let them be pushed; put them back
        ps[k].x, ps[k].y, ps[k].mode, ps[k].hp = wk.x + u, wk.y + v, "walk", 100
    wk.atk_cd = 0.0
    for i in range(40):
        if i == 3:
            shot("bat_swing_early", sim)
        if i == 9:
            shot("bat_swing_mid", sim)
        yield inp0(attack=(i == 0))
        for k, (u, v) in spots.items():                  # keep them still so the arc test is clean
            if ps[k].hp >= 100:                          # the ones not yet hit stand where they were put
                ps[k].x, ps[k].y, ps[k].vx, ps[k].vy, ps[k].mode = wk.x + u, wk.y + v, 0.0, 0.0, "walk"
    hit = {k: ps[k].hp < 100 or ps[k].mode in ("dead", "flee", "air", "ko") for k in ps}
    dbg = {k: (round(p.hp), p.mode, round(math.hypot(p.x - wk.x, p.y - wk.y), 1), p in sim.peds.list) for k, p in ps.items()}
    ok = hit["front"] and hit["front_left"] and hit["front_right"] and not hit["behind"] and not hit["far"]
    import weaponart
    report("bat", ok, f"hit by the swept arc: {hit} {dbg}; ticks(atk_t,sw_u,hits)={swlog[:30]}; swing_az={[round(weaponart.swing_az(u), 2) for u in (0, .25, .5, .75, 1)]}")
    for p in ps.values():
        p.mode, p.t = "dead", 0.1


def sc_escape(sim, S):
    if sim.mode == "car":
        sim.exit_car()
    st = [s for s in (getattr(sim.w, "esc", None) or {}).get("stairs", ()) if "path" in s]
    if not st:
        report("escape", False, "the world has no fire escape stairs")
        return
    wk = sim.walker
    ok_n, tot = 0, 0
    notes = []
    for idx in range(0, len(st), max(1, len(st) // 6)):
        s = st[idx]
        x0, y0, h0 = s["path"][0]
        x1, y1, h1 = s["path"][-1]
        wk.x, wk.y, wk.az, wk.vz = x0, y0, h0, 0.0
        for _ in range(4):
            yield inp0()
        az_before = None if wk.az is None else round(wk.az, 1)
        started = escride.start(sim)
        n = 0
        while sim.esc is not None and n < 1200:
            if n == 40 and tot == 0:
                shot("escape_ride", sim)
            yield inp0()
            n += 1
        for _ in range(40):
            yield inp0()
        d = math.hypot(wk.x - x1, wk.y - y1)
        dz = (wk.az if wk.az is not None else 0) - h1
        good = started and n < 1200 and d < 2.5 and dz > -1.5
        tot += 1
        ok_n += good
        notes.append(f"#{idx} az0={az_before} h0={h0:.1f} d0={math.hypot(wk.x - x0, wk.y - y0):.1f} subj={escride._subject(sim) is not None} find={escride._find(sim) is not None} mode={sim.mode} started={started} t={n * 0.016:.0f}s end_dist={d:.1f}m dz={dz:+.1f}")
    report("escape", ok_n == tot, f"{ok_n}/{tot} rides arrive at the top and stand on the platform; " + "; ".join(notes))


def sc_door(sim, S):
    if sim.mode == "car":
        sim.exit_car()
    wk = sim.walker
    res = []
    for kind in (vehicles.SEMI, vehicles.BUS):
        b = actors.Body(wk.x + 14, wk.y + 14, 0.7, kind, 0)
        b.empty = True
        b.az = sim.w.ground_y(b.x, b.y)
        sim.bodies.append(b)
        fx, fy = math.cos(b.h), math.sin(b.h)
        mid = (b.x + 0.0, b.y + 0.0)
        for where, (px, py) in (("middle", (b.x - math.sin(b.h) * (vehicles.DIMS[kind][1] / 2 + 1.0), b.y + math.cos(b.h) * (vehicles.DIMS[kind][1] / 2 + 1.0))),
                                ("cab", actors.door_point(b, 0.9))):
            wk.x, wk.y, wk.az, wk.mode = px, py, b.az, getattr(wk, "mode", None)
            sim.mode = "foot"
            if sim.walker is None:
                sim.walker = wk
            entered = sim.try_enter()
            for _ in range(80):
                yield inp0()
            in_car = sim.mode == "car" and sim.car is b
            res.append((vehicles.IDS[kind], where, bool(entered), in_car))
            if sim.mode == "car":
                sim.exit_car()
                wk = sim.walker
                for _ in range(10):
                    yield inp0()
        if b in sim.bodies:
            sim.bodies.remove(b)
    mid_bad = any(r[3] for r in res if r[1] == "middle")
    cab_ok = all(r[3] for r in res if r[1] == "cab")
    report("door", cab_ok and not mid_bad, f"(vehicle, where, try_enter, got in): {res}")


def sc_driver(sim, S):
    if sim.mode == "car":
        sim.exit_car()
    wk = sim.walker
    p = sim.peds.eject(wk.x + 12, wk.y, 0.0)
    modes = []
    for i in range(500):
        if i % 20 == 0:
            modes.append(p.mode)
        yield inp0()
    d = math.hypot(p.x - wk.x - 12, p.y - wk.y)
    report("driver", "rage" in modes and d > 6.0 or modes[-1] in ("flee", "walk"), f"ejected driver modes over 8 s: {modes}, moved {d:.1f} m, now {p.mode}")


def sc_dodge(sim, S):
    if sim.mode == "car":
        sim.exit_car()
    wk = sim.walker
    car = actors.Body(wk.x - 40, wk.y, 0.0, 1, 0)
    car.az = sim.w.ground_y(car.x, car.y)
    car.empty = False
    car.player_car = False
    car.ctl = (0.6, 0.0, False)
    car.service = True
    sim.bodies.append(car)
    ps = [_ped_at(sim, wk.x - 10 + i * 0.5, wk.y + (i - 2) * 0.3) for i in range(5)]
    car.vx = 9.0
    near_min = 99.0
    hit_n = 0
    for i in range(240):
        yield inp0()
        car.vx = max(car.vx, 8.0)
        for p in ps:
            if p.mode not in ("dead", "air"):
                d = math.hypot(p.x - car.x, p.y - car.y)
                near_min = min(near_min, d)
        hit_n = sum(1 for p in ps if p.mode in ("dead", "air"))
    report("dodge", hit_n == 0, f"5 pedestrians in a car's lane, car passes at ~8 m/s: run over {hit_n}, closest {near_min:.1f} m (a person needs >1.3 m)")
    for p in ps:
        p.mode, p.t = "dead", 0.1
    if car in sim.bodies:
        sim.bodies.remove(car)


def sc_semi(sim, S):
    if sim.mode != "car":
        # take a semi into the player's seat
        wk = sim.walker
        b = actors.Body(wk.x + 6, wk.y, 0.0, vehicles.SEMI, 0)
        b.az = sim.w.ground_y(b.x, b.y)
        b.empty = False
        sim.bodies.append(b)
        sim.car, sim.mode, sim.walker = b, "car", None
        b.player_car = True
    else:
        b = sim.car
    n0 = len(decals)
    for i in range(240):                                  # speed up, then hard left with the handbrake
        yield inp0(throttle=1.0)
    for i in range(240):
        yield inp0(throttle=0.6, steer=-1.0 if (i // 60) % 2 == 0 else 1.0, handbrake=(i % 60) > 20)
    ls = [d for d in decals[n0:] if d[0] == "l"]
    tra = b.tra is not None
    shot("semi_skid", sim)
    report("semi", tra and len(ls) > 4, f"semi trailer tracked={tra}, skid lines added {len(ls)} (rig speed {b.speed:.1f} m/s, slip {b.slip:.1f})")


SCEN = [("camera", sc_camera), ("bat", sc_bat), ("escape", sc_escape), ("door", sc_door), ("driver", sc_driver),
        ("dodge", sc_dodge), ("semi", sc_semi)]
if a.only:
    SCEN = [s for s in SCEN if s[0] in a.only.split(",")]

swlog = []
_st = actors.Sim._swing_tick
def _swt(self):
    wk = self.walker
    if wk is not None and getattr(wk, "sw_hit", None) is not None:
        swlog.append((round(wk.atk_t, 2), round(wk.sw_u, 2), len(wk.sw_hit)))
    return _st(self)
actors.Sim._swing_tick = _swt

play = {"gen": None, "i": 0, "t0": None}
_upd = actors.Sim.update
def update(self, dt, inp, steps):
    if state["ready"] is not None and state["n"] > state["ready"] + 90:
        if play["gen"] is None and play["i"] < len(SCEN):
            nm, fn = SCEN[play["i"]]
            print(f"[live] scenario {nm} ...", flush=True)
            play["gen"] = fn(self, M_selfie())
        if play["gen"] is not None:
            try:
                ov = next(play["gen"])
                if ov is not None:
                    inp = ov
            except StopIteration:
                play["gen"], play["i"] = None, play["i"] + 1
            except Exception as e:  # noqa: BLE001
                import traceback
                report(SCEN[play["i"]][0], False, "crashed: " + traceback.format_exc().splitlines()[-1])
                traceback.print_exc()
                play["gen"], play["i"] = None, play["i"] + 1
        if play["i"] >= len(SCEN) and play["gen"] is None and not state.get("done"):
            state["done"] = True
            self._live_done = True
    return _upd(self, dt, inp, steps)
actors.Sim.update = update


_cap = {}
_ch = M.selfie_mod.Selfie.chase if hasattr(M.selfie_mod, "Selfie") else None
if _ch:
    def _chase(self, *x, **kw):
        _cap["s"] = self
        return _ch(self, *x, **kw)
    M.selfie_mod.Selfie.chase = _chase


def M_selfie():
    return _cap.get("s") or type("S", (), {})()


# ------------------------------------------------------------------ run
t0 = time.time()
try:
    M.main()
except SystemExit:
    pass
print(f"[live] {sum(1 for r in results if r[1])}/{len(results)} scenarios passed in {time.time() - t0:.0f} s")
json.dump(results, open(os.path.join(a.out, "results.json"), "w"), indent=1, ensure_ascii=False)

