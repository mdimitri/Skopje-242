"""Night / sun lighting harness.  Runs the real game headless (software GL is fine) at several hours in the top-down
and the street (third-person) view and asserts:
  * no sun shadow at all while it is dark: the shadow strength, the sun_k of the contact shadows and the shader's shd.x are 0
  * the sun strength function is sane over the whole day (finite, 0 at night, >0 at noon)
  * every frame is neither black (ambient floor) nor blown out (overexposed pixels)
  * no exceptions / [guard] failures in the log, also while the clock runs fast through dusk and dawn
  * night frames are not much slower than day frames in the same view, third person included (software-GL proxy; the real check is a GPU)
  * zoom sweep at night: brightness changes smoothly with zoom (no light layers popping in and out), nothing blown out
  * light map sprites are never long streaks, smoke is never a flat rectangle
Use a ~10% sample world, not the whole map:   python3 tools/test_night.py --world data/cache/world_sample
Internal:  python3 tools/test_night.py --child ... (one game run with probes; used by the runner)"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)


def child(a):
    import atexit
    import clock
    import gl3d
    import render
    import settings
    import sunshadow
    clock.GameClock.SECONDS_PER_HOUR = a.sph
    settings.DEFAULTS["debug_chase"] = a.view == "chase"
    rec = []
    state = {"hour": 0.0, "dark": 0.0}
    upd = sunshadow.SunShadow.update

    def update(self, hour, cx, cz, dark=0.0):
        r = upd(self, hour, cx, cz, dark)
        state["hour"], state["dark"] = hour, dark
        rec.append({"hour": hour, "dark": dark, "strength": self.strength, "shd": gl3d._sun_state["shd"][0]})
        return r
    sunshadow.SunShadow.update = update
    sb = render.Renderer._shadow_batch

    def shadow_batch(self, items):
        rec.append({"hour": state["hour"], "dark": state["dark"], "sun_k": self.sun_k})
        return sb(self, items)
    render.Renderer._shadow_batch = shadow_batch
    import lightmap
    lr = lightmap.LightMap.render

    def lm_render(self):
        asp = [max(ln, wd) / max(0.01, min(ln, wd)) for _x, _z, ln, wd, _d, _c, _k in self.sprites]
        rec.append({"hour": state["hour"], "dark": state["dark"], "sprites": len(self.sprites), "max_aspect": max(asp) if asp else 1.0})
        return lr(self)
    lightmap.LightMap.render = lm_render
    atexit.register(lambda: json.dump(rec, open(a.out, "w")))
    sys.argv = [os.path.join(SRC, "main.py"), "--world", a.world, "--test", str(a.frames), "--mute", "--hour", str(a.hour),
                "--shot", a.shot, "--zoom", str(a.zoom)]
    import runpy
    runpy.run_path(os.path.join(SRC, "main.py"), run_name="__main__")


def run(world, view, hour, frames=60, sph=None, tag="", zoom=1.0):
    shot = os.path.join(OUT, f"{view}_{hour}{tag}")
    out = shot + ".json"
    for f in glob.glob(shot + "_*.png"):
        os.remove(f)
    cmd = ["xvfb-run", "-a", sys.executable, os.path.abspath(__file__), "--child", "--world", world, "--view", view, "--hour", str(hour),
           "--frames", str(frames), "--shot", shot, "--out", out, "--sph", str(sph or 55.0), "--zoom", str(zoom)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    log = p.stdout + p.stderr
    m = re.search(r"avg_frame=([\d.]+)ms", log)
    shots = sorted(glob.glob(shot + "_*.png"), key=lambda f: int(f.rsplit("_", 1)[1][:-4]))
    rec = json.load(open(out)) if os.path.exists(out) else []
    return {"ms": float(m.group(1)) if m else None, "log": log, "shots": shots, "rec": rec}


def image_stats(path):
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    lum = a.mean(axis=2)
    h = a.shape[0]
    scene = a[: int(h * 0.75)]                        # leave the HUD strip at the bottom out
    blown = float((scene.min(axis=2) >= 250).mean())
    return float(lum.mean()), blown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=os.path.join(ROOT, "data", "cache", "world_sample"))
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--view", default="top")
    ap.add_argument("--hour", type=float, default=22.0)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--shot", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--sph", type=float, default=55.0)
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--quick", action="store_true", help="fewer hours")
    a = ap.parse_args()
    if a.child:
        return child(a)

    global OUT
    OUT = os.path.join(ROOT, "logs", "test_night")
    os.makedirs(OUT, exist_ok=True)
    fails = []

    def check(ok, msg):
        print(("  ok   " if ok else "  FAIL ") + msg)
        if not ok:
            fails.append(msg)

    print("sun strength over the day (no GL)")
    import math
    import sunshadow
    import clock
    gc = clock.GameClock(0.0)
    for q in range(0, 96):
        h = q / 4.0
        gc.hour = h
        s = sunshadow.strength_at(h, gc.dark)
        v, e = sunshadow.sun_at(h)
        if not (math.isfinite(s) and 0.0 <= s <= 0.93 and all(math.isfinite(x) for x in v) and abs(sum(x * x for x in v) - 1) < 1e-6):
            check(False, f"strength/vector sane at {h}")
        if gc.dark >= 0.5 and s != 0.0:
            check(False, f"sun shadow strength {s:.2f} at {h:.2f} h with dark {gc.dark:.2f}")
    check(sunshadow.strength_at(13.0, 0.0) > 0.8, "sun shadow at noon")
    check(all(sunshadow.strength_at(h, clock.GameClock(h).dark) == 0.0 for h in (21, 22, 23, 0, 1, 2, 3, 4)), "no sun shadow 21:00-04:00")

    hours = (12.0, 21.0, 23.0) if a.quick else (12.0, 19.5, 21.0, 23.0, 3.0, 6.5)
    ms = {}
    for view in ("top", "chase"):
        for h in hours:
            print(f"{view} view at {h:g} h")
            r = run(a.world, view, h)
            ms[(view, h)] = r["ms"]
            check("Traceback" not in r["log"] and "[guard]" not in r["log"], "no exceptions / guard failures")
            check(bool(r["shots"]), "screenshots written")
            if r["ms"] is not None:
                print(f"       avg frame {r['ms']:.0f} ms")
            for rec in r["rec"]:
                if rec["dark"] >= 0.5:
                    if rec.get("strength", 0) != 0 or rec.get("shd", 0) != 0 or rec.get("sun_k", 0) != 0:
                        check(False, f"{view} {h}: sun shadow active in the dark {rec}")
                        break
            else:
                check(True, "no sun shadow state while dark")
            if r["shots"]:
                lum, blown = image_stats(r["shots"][-1])
                night = h >= 20.5 or h < 5.5
                check(lum >= (22 if night else 50), f"not black (mean {lum:.0f})")
                check(blown < 0.04, f"not overexposed ({blown * 100:.1f}% blown)")
    for view in ("top", "chase"):
        day, night = ms.get((view, 12.0)), ms.get((view, 23.0))
        if day and night:
            check(night <= day * 1.4, f"{view}: night frame {night:.0f} ms vs day {day:.0f} ms (limit 1.4x)")

    import fx
    check(not any(fx.flat_quad("s", g) for g in (0.3, 1.0, 2.0)), "smoke is a soft puff, never a flat square")
    print("zoom sweep at night (top-down, 23 h)")
    lum = []
    for z in (0.5, 0.8, 1.2, 2.0, 3.0):
        r = run(a.world, "top", 23.0, frames=40, zoom=z, tag=f"_z{z}")
        check("Traceback" not in r["log"] and "[guard]" not in r["log"], f"zoom {z}: no exceptions")
        if r["shots"]:
            l, blown = image_stats(r["shots"][-1])
            lum.append(l)
            check(blown < 0.04, f"zoom {z}: not overexposed ({blown * 100:.1f}% blown)")
        sp = [x for x in r["rec"] if "max_aspect" in x]
        check(bool(sp) and max(x["max_aspect"] for x in sp) <= 4.0, f"zoom {z}: no streak-shaped light sprites")
    for u, v in zip(lum, lum[1:]):
        check(0.6 <= v / u <= 1.6, f"zoom sweep: brightness {u:.0f} -> {v:.0f} changes smoothly")
    print("fast forward through dusk and dawn (clock 0.12 s per hour)")
    for view in ("top", "chase"):
        r = run(a.world, view, 17.0, frames=300, sph=0.12, tag="_ff")
        check("Traceback" not in r["log"] and "[guard]" not in r["log"], f"{view}: no exceptions")
        lums = [image_stats(f)[0] for f in r["shots"]]
        check(bool(lums) and min(lums) >= 20, f"{view}: never black while time runs (min mean {min(lums) if lums else 0:.0f})")
        bad = [x for x in r["rec"] if x["dark"] >= 0.5 and (x.get("strength", 0) or x.get("sun_k", 0))]
        check(not bad, f"{view}: no sun shadow in the dark while time runs")
    print("FAILED: %d" % len(fails) if fails else "ALL OK")
    for f in fails:
        print("  -", f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
