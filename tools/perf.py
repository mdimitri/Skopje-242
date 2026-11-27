"""Repeatable frame profiler for the game (no game code is changed; everything is wrapped from outside).

  python tools/perf.py --mode car  --frames 600                                # driving (the --test autopilot), top-down view
  python tools/perf.py --mode car  --view chase                                # driving, 3rd-person (chase) view
  python tools/perf.py --mode foot --frames 600                                # on foot
  The game's own settings.json is used (resolution, detail, AA, ...); --size 1920x1080 overrides the window only.
  add --prof for a cProfile of the measured frames, --audio to include audio, --tag name for the output file

Add --trace for exclusive frame-level spans and --gpu for an OpenGL timestamp diagnostic.

Vsync is switched off and the frame rate is not capped, so the numbers are what the machine can do.
Writes logs/perf_<tag>.json and prints a summary: frame ms (mean, median, p95, worst), fps, process CPU use
(cores busy = CPU seconds / wall seconds), per-subsystem ms, draw calls per frame and, with --prof, the top functions."""
import argparse
from contextlib import contextmanager
import cProfile
import json
import os
import pstats
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.append(os.path.join(ROOT, "tools"))

ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="car", choices=("car", "foot"))
ap.add_argument("--frames", type=int, default=600)
ap.add_argument("--warm", type=int, default=120, help="first frames left out of the statistics (loading, first streaming)")
ap.add_argument("--world", default="")
ap.add_argument("--size", default="", help="window size; default: the resolution in settings.json")
ap.add_argument("--view", default="top", choices=("top", "chase", "heli"), help="top-down, chase, or airborne helicopter")
ap.add_argument("--stress", action="store_true", help="1080p by default, maximum traffic and pedestrians, widest zoom, explosion during capture")
ap.add_argument("--hour", default="")
ap.add_argument("--dof", type=float, default=0.0, help="depth of field strength (1 = 100%%) in the chase view; 0 = off")
ap.add_argument("--no-dof", action="store_true", help="turn off depth of field for a matched graphics diagnostic")
ap.add_argument("--prof", action="store_true")
ap.add_argument("--trace", action="store_true", help="save frame-level exclusive timings and worker telemetry")
ap.add_argument("--gpu", action="store_true", help="record a separate OpenGL timestamp diagnostic (adds batch flushes)")
ap.add_argument("--windowed", action="store_true", help="force windowed mode for comparable captures")
ap.add_argument("--audio", action="store_true", help="include audio device and mixer work")
ap.add_argument("--tag", default="")
ap.add_argument("extra", nargs="*", help="more arguments for main.py (after --)")
a = ap.parse_args()
a.trace = a.trace or a.gpu
if not 1 <= a.warm < a.frames:
    ap.error("--warm must be at least 1 and smaller than --frames")
tag = a.tag or (a.mode + ("_" + a.view if a.view != "top" else ""))
if a.stress:
    a.size = a.size or "1920x1080"
    os.environ["SK242_TEST_BOOM"] = str(a.warm + max(1, (a.frames - a.warm) // 3))

game = ["main.py", "--test", str(a.frames)]
if not a.audio:
    game.append("--mute")
if a.size:
    game += ["--size", a.size]
if a.world:
    game += ["--world", a.world]
if a.hour:
    game += ["--hour", a.hour]
if a.mode == "car" or a.view == "heli":
    game += ["--car"]
else:
    game += ["--walker"]
if a.stress:
    game += ["--zoom", "0.35"]
game += a.extra
sys.argv = game
os.chdir(ROOT)

import pyray as rl  # noqa: E402
from perf_gl import GpuTimeline  # noqa: E402
try:
    import fastrl  # noqa: F401,E402  (the game swaps pyray functions for raw ones on import: wrap after that)
except ImportError:
    pass

_scf = rl.set_config_flags
rl.set_config_flags = lambda f: _scf(f & ~rl.FLAG_VSYNC_HINT)   # never wait for the monitor
_stf = rl.set_target_fps
rl.set_target_fps = lambda n: _stf(0)

import settings as settings_mod  # noqa: E402
_sinit = settings_mod.Settings.__init__
effective_settings = {}
def _settings(self, *x, **kw):
    _sinit(self, *x, **kw)
    self["debug_chase"] = a.view in ("chase", "heli")  # in memory only, settings.json is not written
    if a.stress:
        self["traffic"] = self["peds"] = len(settings_mod.DENSITY) - 1
    if a.windowed:
        self["fullscreen"] = False
    if a.no_dof:
        self["dof"] = False
    elif a.dof > 0:
        self["dof"], self["dof_k"] = True, a.dof
    if not effective_settings:
        effective_settings.update({k: self[k] for k in ("resolution", "scale", "aa", "detail", "fullscreen",
                                                        "smog", "traffic", "peds", "dof", "dof_k", "time_speed")})
settings_mod.Settings.__init__ = _settings

import main as M  # noqa: E402

if a.view == "heli":
    from vehicles import HELI
    _sim_update = M.Sim.update
    def _heli_update(self, dt, inp, steps):
        if self.mode == "car" and self.car.kind != HELI:
            car = self.car
            car.kind = HELI
            car.az = self.w.ground_y(car.x, car.y) + 85
            car.vz, car.rpm = 0.0, 1.0
        return _sim_update(self, dt, dict(inp, throttle=0.35, steer=0.1, run=False, handbrake=False), steps)
    M.Sim.update = _heli_update

frames, cur = [], {}
exclusive, span_path, scopes = {}, [], []
worker = {}
gpu = None
gpu_error = None


@contextmanager
def span(name):
    if not a.trace:
        yield
        return
    span_path.append(name)
    key = "/".join(span_path)
    scope = [time.perf_counter_ns(), 0]
    scopes.append(scope)
    try:
        yield
    finally:
        elapsed = time.perf_counter_ns() - scope[0]
        exclusive[key] = exclusive.get(key, 0) + elapsed - scope[1]
        scopes.pop()
        span_path.pop()
        if scopes:
            scopes[-1][1] += elapsed


calls = {"draw": 0}
import raylib  # noqa: E402  (hot loops call the raw cffi functions directly)
for mod, names in ((rl, ("draw_model", "draw_mesh", "draw_model_ex", "draw_mesh_instanced")), (raylib, ("DrawModel", "DrawMesh", "DrawModelEx", "DrawMeshInstanced"))):
    for nm in names:
        f0 = getattr(mod, nm)
        def wrap(*x, _f=f0):
            calls["draw"] += 1
            return _f(*x)
        setattr(mod, nm, wrap)

orig_run = M.Guard.run
errors = {}
def run(self, nm, fn, *x, **kw):
    t0 = time.perf_counter()
    e0 = self.errors.get(nm, 0)
    c0 = calls["draw"]
    try:
        if a.gpu and nm in ("stream", "sun", "nightprep"):
            timeline = gpu_timeline()
            if timeline is not None:
                timeline.mark("before " + nm)
        with span(nm):
            result = orig_run(self, nm, fn, *x, **kw)
        if gpu is not None and nm in ("stream", "sun", "nightprep", "render"):
            gpu.mark("scene" if nm == "render" else nm)
        return result
    finally:
        cur[nm] = cur.get(nm, 0.0) + (time.perf_counter() - t0) * 1000
        if calls["draw"] != c0:
            cur["calls_" + nm] = cur.get("calls_" + nm, 0) + calls["draw"] - c0
        if self.errors.get(nm, 0) != e0:
            errors[nm] = errors.get(nm, 0) + 1          # a subsystem raised: the numbers are not valid (see logs/game.log)
M.Guard.run = run

def _sub(modname, cls, meth):
    """Time one method as its own row ('render._actors' ...), draw calls included."""
    try:
        C = getattr(__import__(modname), cls)
        f0 = getattr(C, meth)
    except (ImportError, AttributeError):
        if a.trace:
            raise
        return
    tagn = f"{modname}.{cls}.{meth}" if meth == "update" else f"{modname}.{meth}"
    def w(*x, **kw):
        t0, c0 = time.perf_counter(), calls["draw"]
        try:
            if gpu is not None and modname == "present" and meth == "end":
                gpu.mark("overlays")
            with span(tagn):
                result = f0(*x, **kw)
            if a.trace and modname == "trafficproc" and x[0].ok:
                worker.update(compute_ms=x[0].ms, wait_ms=x[0].wait_ms)
            return result
        finally:
            cur[tagn] = cur.get(tagn, 0.0) + (time.perf_counter() - t0) * 1000
            cur["calls_" + tagn] = cur.get("calls_" + tagn, 0) + calls["draw"] - c0
    setattr(C, meth, w)
for spec in (("render", "Renderer", "_actors"), ("render", "Renderer", "_decals"), ("render", "Renderer", "_overview"),
             ("bake", "Streamer", "_load_meshes"), ("bake", "Streamer", "_bake"),
             ("night", "Night", "draw"), ("sunshadow", "SunShadow", "_draw_depth"),
             ("actors", "Traffic", "update"), ("actors", "Peds", "update"), ("trafficproc", "TrafficProc", "step")):
    _sub(*spec)

if a.trace:
    for module, cls, methods in (
        ("render", "Renderer", "_collect_models _visible_meshes _shadow_batch _proj_shadow _shots _balls"),
        ("present", "Present", "activate begin ui_layer end"),
        ("selfie", "Selfie", "sky haze overlay"),
        ("poi", "Pois", "draw"), ("fx", "Particles", "draw update"),
        ("bake", "Streamer", "_evict _flush_decals"),
        ("actors", "Sim", "_dispatch _parked _traffic_crashes _swing_tick"),
        ("actors", "Walker", "update"), ("clock", "GameClock", "update"),
        ("stations", "Stations", "update"), ("services", "Services", "update"),
        ("services", "Services", "_graph _nearest_node _to route _spawn_vehicle"),
        ("night", "Night", "_beam _glow _seen"),
        ("lightmap", "LightMap", "render overlay windows"),
        ("render", "Batch", "flush"),
        ("render", "Renderer", "_draw_vehicle_models _draw_ped_models"),
        ("chaos", "Chaos", "update"), ("transit", "Transit", "update"),
        ("compounds", "Compounds", "update"), ("kids", "Kids", "update"),
        ("dogs", "Dogs", "update"), ("birds", "Birds", "update"),
        ("rentals", "Rentals", "update"), ("works", "Works", "update"),
        ("projectiles", "Projectiles", "update"), ("trains", "Trains", "update draw"),
        ("signals", "Signals", "update draw"), ("audio", "Audio", "update"),
    ):
        for method in methods.split():
            _sub(module, cls, method)

import gc  # noqa: E402
_gc_t = [0.0]
def _gccb(phase, info):
    if phase == "start":
        _gc_t[0] = time.perf_counter()
    else:
        k = f"gc{info['generation']}"
        cur[k] = cur.get(k, 0.0) + (time.perf_counter() - _gc_t[0]) * 1000      # (also counted inside the subsystem it hit)
gc.callbacks.append(_gccb)

prof = cProfile.Profile() if a.prof else None
state = {"n": 0, "t": None, "w0": None, "c0": None, "c1": None, "ready": None, "f0": 0}
_log0 = M.log
def _log(msg):
    if "[game] ready" in str(msg) and state["ready"] is None:
        state["ready"] = state["n"]                  # --warm counts frames from here: the loading screen draws frames too
        state["startup_s"] = time.perf_counter() - t_start
    return _log0(msg)
M.log = _log
_bd = rl.begin_drawing
_close = rl.close_window


def gpu_timeline():
    global gpu, gpu_error
    if a.gpu and state["ready"] is not None and state["w0"] is not None:
        if gpu is None and gpu_error is None:
            try:
                from perf_gl import GpuTimeline
                gpu = GpuTimeline()
            except RuntimeError as exc:
                gpu_error = str(exc)
        if gpu is not None and gpu.marks is None:
            gpu.collect()
            gpu.start()
        return gpu
    return None


def begin_drawing():
    timeline = gpu_timeline()
    if timeline is not None:
        timeline.mark("before scene")
    return _bd()


def close_window():
    if gpu is not None:
        gpu.collect(wait=True)
    if prof:
        prof.disable()
    return _close()


rl.begin_drawing = begin_drawing
rl.close_window = close_window
_ed = rl.end_drawing
def end_drawing():
    global cur
    t0 = time.perf_counter()
    if gpu is not None:
        gpu.finish(cur)
    with span("swap"):
        r = _ed()
    t1 = time.perf_counter()
    cur["swap"] = (t1 - t0) * 1000
    if state["t"] is not None:
        cur["frame"] = (t1 - state["t"]) * 1000
        cur["calls"] = calls["draw"]
        if a.trace:
            cur["exclusive_ms"] = {k: v / 1e6 for k, v in exclusive.items()}
            cur["worker_ms"] = dict(worker)
        frames.append(cur)
    state["t"] = t1
    cur = {}
    exclusive.clear()
    worker.clear()
    calls["draw"] = 0
    state["n"] += 1
    if state["ready"] is not None and state["n"] == state["ready"] + a.warm:
        state["f0"] = len(frames)
        state["w0"], state["c0"] = time.perf_counter(), time.process_time()
        if prof:
            prof.enable()
    elif state["w0"] is not None:
        state["c1"] = time.process_time()
    return r
rl.end_drawing = end_drawing

def _no_hard_exit(code=0):
    raise SystemExit(code)                   # the game ends --test with os._exit, which would skip the summary below
os._exit = _no_hard_exit

t_start = time.perf_counter()
exit_code = 0
try:
    M.main()
except SystemExit as exc:
    exit_code = exc.code or 0                # still print what was measured on an early exit
finally:
    if prof:
        prof.disable()
F = frames[state["f0"]:] if state["w0"] is not None else []
if not F:
    raise SystemExit(f"[perf] no gameplay frames measured after warm-up (game exit: {exit_code})")
ft = [f["frame"] for f in F]
wall = sum(ft) / 1000.0
cpu = state["c1"] - state["c0"]
keys = sorted({k for f in F for k in f if isinstance(f[k], (int, float)) and k != "frame"})
sub = {k: round(sum(f.get(k, 0.0) for f in F) / max(1, len(F)), 2) for k in keys}
q = sorted(ft)
out = dict(tag=tag, mode=a.mode, view=a.view, size=a.size or "settings",
           settings=effective_settings, world=a.world, frames=len(F), hour=a.hour, audio=a.audio,
           startup_s=round(state["startup_s"], 2), complete=len(F) >= a.frames - a.warm and not exit_code,
           frame_ms=dict(mean=round(statistics.mean(ft), 2), median=round(statistics.median(ft), 2),
                         p95=round(q[int(len(q) * 0.95) - 1], 2), worst=round(q[-1], 2)),
           fps=round(1000.0 / statistics.mean(ft), 1), cores_busy=round(cpu / wall, 2) if wall > 0 else None,
           cpu_count=os.cpu_count(), errors=errors, per_frame=sub)
if a.trace or a.gpu:
    out.update(warm=a.warm, arguments=game[1:], gpu_error=gpu_error, samples=F)
med = statistics.median(ft)
out["hitches"] = [dict(frame=i, ms=round(f["frame"], 1), top=sorted(((k, round(v, 1)) for k, v in f.items() if isinstance(v, (float, int)) and k != "frame" and not k.startswith("calls")), key=lambda kv: -kv[1])[:4])
                  for i, f in enumerate(F) if f["frame"] > max(2.5 * med, med + 25.0)][:40]
if prof:
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    prof.dump_stats(os.path.join(ROOT, "logs", f"perf_{tag}.prof"))      # for pstats / snakeviz: callers, call graph
    st = pstats.Stats(prof)
    rows = sorted(st.stats.items(), key=lambda kv: -kv[1][2])[:45]
    out["top_tottime"] = [(f"{os.path.basename(k[0])}:{k[1]} {k[2]}", v[1], round(v[2] * 1000 / max(1, len(F)), 3), round(v[3] * 1000 / max(1, len(F)), 3)) for k, v in rows]
os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
path = os.path.join(ROOT, "logs", f"perf_{tag}.json")
json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
print(f"[perf] {tag}: {out['frames']} frames  mean {out['frame_ms']['mean']} ms  median {out['frame_ms']['median']}  "
      f"p95 {out['frame_ms']['p95']}  worst {out['frame_ms']['worst']}  = {out['fps']} fps  cores busy {out['cores_busy']} of {os.cpu_count()}")
print("[perf] per frame (ms, calls = draw calls):", ", ".join(f"{k} {v}" for k, v in sorted(sub.items(), key=lambda kv: -kv[1]) if v >= 0.05))
if prof:
    print("[perf] top functions (calls, own ms/frame, total ms/frame):")
    for r in out["top_tottime"][:30]:
        print(f"   {r[2]:8.3f} {r[3]:8.3f} {r[1]:8d}  {r[0]}")
for h in out["hitches"][:8]:
    print(f"[perf] hitch frame {h['frame']}: {h['ms']} ms  " + ", ".join(f"{k} {v}" for k, v in h["top"]))
if errors:
    print(f"[perf] WARNING: subsystems failed during the run {errors} - see logs/game.log; these numbers are NOT valid")
print("[perf] wrote", path)
if errors or not out["complete"]:
    raise SystemExit(1)
