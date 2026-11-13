"""Repeatable frame profiler for the game (no game code is changed; everything is wrapped from outside).

  python tools/perf.py --mode car  --frames 600                                # driving (the --test autopilot), top-down view
  python tools/perf.py --mode car  --view chase                                # driving, 3rd-person (chase) view
  python tools/perf.py --mode foot --frames 600                                # on foot
  The game's own settings.json is used (resolution, detail, AA, ...); --size 1920x1080 overrides the window only.
  add --prof for a cProfile of the measured frames, --tag name for the output file

Vsync is switched off and the frame rate is not capped, so the numbers are what the machine can do.
Writes logs/perf_<tag>.json and prints a summary: frame ms (mean, median, p95, worst), fps, process CPU use
(cores busy = CPU seconds / wall seconds), per-subsystem ms, draw calls per frame and, with --prof, the top functions."""
import argparse
import cProfile
import json
import os
import pstats
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="car", choices=("car", "foot"))
ap.add_argument("--frames", type=int, default=600)
ap.add_argument("--warm", type=int, default=120, help="first frames left out of the statistics (loading, first streaming)")
ap.add_argument("--world", default="")
ap.add_argument("--size", default="", help="window size; default: the resolution in settings.json")
ap.add_argument("--view", default="top", choices=("top", "chase"), help="top-down or 3rd-person (chase) camera")
ap.add_argument("--hour", default="")
ap.add_argument("--prof", action="store_true")
ap.add_argument("--tag", default="")
ap.add_argument("extra", nargs="*", help="more arguments for main.py (after --)")
a = ap.parse_args()
tag = a.tag or (a.mode + ("_chase" if a.view == "chase" else ""))

game = ["main.py", "--test", str(a.frames), "--mute"] + (["--size", a.size] if a.size else [])
if a.world:
    game += ["--world", a.world]
if a.hour:
    game += ["--hour", a.hour]
if a.mode == "car":
    game += ["--car"]
else:
    game += ["--walker"]
game += a.extra
sys.argv = game
os.chdir(ROOT)

import pyray as rl  # noqa: E402
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
def _settings(self, *x, **kw):
    _sinit(self, *x, **kw)
    self["debug_chase"] = a.view == "chase"          # in memory only, settings.json is not written
settings_mod.Settings.__init__ = _settings

import main as M  # noqa: E402

frames, cur = [], {}
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
        return orig_run(self, nm, fn, *x, **kw)
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
    except Exception:  # noqa: BLE001 - an older tree without it
        return
    tagn = f"{modname}.{cls}.{meth}" if meth == "update" else f"{modname}.{meth}"
    def w(*x, **kw):
        t0, c0 = time.perf_counter(), calls["draw"]
        try:
            return f0(*x, **kw)
        finally:
            cur[tagn] = cur.get(tagn, 0.0) + (time.perf_counter() - t0) * 1000
            cur["calls_" + tagn] = cur.get("calls_" + tagn, 0) + calls["draw"] - c0
    setattr(C, meth, w)
for spec in (("render", "Renderer", "_actors"), ("render", "Renderer", "_decals"), ("render", "Renderer", "_overview"),
             ("bake", "Streamer", "_load_meshes"), ("bake", "Streamer", "_load_block"), ("bake", "Streamer", "_bake"),
             ("night", "Night", "draw"), ("sunshadow", "SunShadow", "_draw_depth"),
             ("actors", "Traffic", "update"), ("actors", "Peds", "update"), ("trafficproc", "TrafficProc", "step")):
    _sub(*spec)

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
state = {"n": 0, "t": None, "cpu": None, "w0": None, "c0": None, "ready": None, "f0": 0}
_log0 = M.log
def _log(msg):
    if "[game] ready" in str(msg) and state["ready"] is None:
        state["ready"] = state["n"]                  # --warm counts frames from here: the loading screen draws frames too
    return _log0(msg)
M.log = _log
_ed = rl.end_drawing
def end_drawing():
    t0 = time.perf_counter()
    r = _ed()
    t1 = time.perf_counter()
    cur["swap"] = (t1 - t0) * 1000
    if state["t"] is not None:
        cur["frame"] = (t1 - state["t"]) * 1000
        cur["calls"] = calls["draw"]
        frames.append(dict(cur))
    state["t"] = t1
    cur.clear()
    calls["draw"] = 0
    state["n"] += 1
    if state["ready"] is not None and state["n"] == state["ready"] + a.warm:
        state["f0"] = len(frames)
        state["w0"], state["c0"] = time.perf_counter(), time.process_time()
        if prof:
            prof.enable()
    return r
rl.end_drawing = end_drawing

def _no_hard_exit(code=0):
    raise SystemExit(code)                   # the game ends --test with os._exit, which would skip the summary below
os._exit = _no_hard_exit

t_start = time.time()
try:
    M.main()
except SystemExit:
    pass                                    # --test ends the game with sys.exit: still print the summary
finally:
    if prof:
        prof.disable()
wall = time.perf_counter() - (state["w0"] or time.perf_counter())
cpu = time.process_time() - (state["c0"] or time.process_time())
F = frames[state["f0"]:]
ft = [f["frame"] for f in F] or [0.0]
keys = sorted({k for f in F for k in f if k not in ("frame",)})
sub = {k: round(sum(f.get(k, 0.0) for f in F) / max(1, len(F)), 2) for k in keys}
q = sorted(ft)
out = dict(tag=tag, mode=a.mode, view=a.view, size=a.size or "settings",
           settings={k: M.settings_mod.Settings().get(k) for k in ("resolution", "scale", "aa", "detail", "fullscreen", "smog", "traffic", "peds") if k in M.settings_mod.Settings()}, world=a.world, frames=len(F),
           frame_ms=dict(mean=round(statistics.mean(ft), 2), median=round(statistics.median(ft), 2),
                         p95=round(q[int(len(q) * 0.95) - 1], 2), worst=round(q[-1], 2)),
           fps=round(1000.0 / statistics.mean(ft), 1), cores_busy=round(cpu / wall, 2) if wall > 0 else None,
           cpu_count=os.cpu_count(), errors=errors, per_frame=sub)
med = statistics.median(ft)
out["hitches"] = [dict(frame=i, ms=round(f["frame"], 1), top=sorted(((k, round(v, 1)) for k, v in f.items() if k != "frame" and not k.startswith("calls")), key=lambda kv: -kv[1])[:4])
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
