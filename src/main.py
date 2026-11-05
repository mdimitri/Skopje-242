"""Скопје 242 - top-down 3D driving sandbox built from OpenStreetMap data.  Start via run.bat."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # embedded Python (._pth) does not add the script folder
from texts import TXT  # noqa: E402
import argparse
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import gc
import time
import zlib
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import faulthandler   # noqa: E402 - a native crash (GPU / raylib) leaves a Python stack in logs/crash.log
try:
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    _crash_f = open(os.path.join(ROOT, "logs", "crash.log"), "a")
    _crash_f.write(time.strftime("--- start %Y-%m-%d %H:%M:%S\n"))
    _crash_f.flush()
    faulthandler.enable(_crash_f, all_threads=True)
except Exception:  # noqa: BLE001
    pass

import pyray as rl   # noqa: E402
import font   # noqa: E402


def _early_splash():
    """Open the window and paint one frame before the ~heavy module imports below, so the player sees the game at once."""
    if any(x.split("=")[0] in ("--test", "--sound-dry", "--size") for x in sys.argv[1:]):
        return                                                  # scripted / debug runs keep the normal path
    try:
        import settings as st
        cfg = st.Settings()
        W, H = st.RESOLUTIONS[cfg["res"]]
        rl.set_trace_log_level(rl.LOG_WARNING)
        rl.set_config_flags(rl.FLAG_VSYNC_HINT | rl.FLAG_WINDOW_RESIZABLE | (rl.FLAG_MSAA_4X_HINT if cfg["aa"] in (1, 3) else 0))
        rl.init_window(W, H, TXT("main.0002"))
        if not rl.is_window_ready():
            return
        font.load()
        rl.begin_drawing()
        import poster
        W, H = rl.get_screen_width(), rl.get_screen_height()
        poster.draw_splash(W, H)
        if poster.splash() is None:
            font.draw_text("Скопје 242", W // 2 - 150, H // 2 - 40, 56, rl.WHITE)
        font.draw_text("Се вчитува ...", W // 2 - 80, H - 60, 24, rl.Color(230, 226, 232, 255), bold="cond")
        rl.end_drawing()
        rl.poll_input_events()
    except Exception:  # noqa: BLE001 - the normal path in main() opens the window if this failed
        pass


_early_splash()

if rl.is_window_ready() and not any(x.split("=")[0] in ("--test", "--sound-dry", "--size", "--nomenu") for x in sys.argv[1:]):
    try:
        import updater
        if updater.check():          # new version installed -> start it and quit this process
            updater.restart()
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - the update check must never stop the game from starting
        pass

import strings as T   # noqa: E402
import audio as audio_mod   # noqa: E402
import radio as radio_mod   # noqa: E402
import menu as menu_mod   # noqa: E402
import savegame   # noqa: E402
import hero_lines   # noqa: E402
import characters   # noqa: E402
import talk   # noqa: E402
import settings as settings_mod   # noqa: E402
import geo as geo_mod   # noqa: E402
import gl3d          # noqa: E402
import present as present_mod   # noqa: E402
import slang         # noqa: E402
import vehicles      # noqa: E402
import works as works_mod   # noqa: E402
import soundlib   # noqa: E402
from actors import Body, Sim   # noqa: E402
from bake import PPM, Streamer, bake_overview   # noqa: E402
import fx as fx_mod   # noqa: E402
from fx import Particles, Popups   # noqa: E402
from night import Night   # noqa: E402
from places import Places   # noqa: E402
from speech import SpeechWorker   # noqa: E402
import smog   # noqa: E402
import poi as poi_mod   # noqa: E402
import selfie as selfie_mod   # noqa: E402
import signals   # noqa: E402
from hud import Hud, build_labels, draw_labels   # noqa: E402
from render import LOD_PPM, Renderer   # noqa: E402
from ui import Loader, fatal_screen   # noqa: E402
from world import World, WorldError   # noqa: E402

LOG_DIR = os.path.join(ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "game.log")


def log(msg):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:  # noqa: BLE001
        pass
    print(msg)


class Guard:
    """Runs a subsystem; repeated failures disable it instead of crashing the whole game."""

    def __init__(self, hud_msg):
        self.errors = {}
        self.disabled = set()
        self.msg = hud_msg
        self.ms = {}                                    # this frame's time per subsystem (for the hitch log)

    def run(self, name, fn, *a, **kw):
        if name in self.disabled:
            return None
        t0 = time.perf_counter()
        try:
            return fn(*a, **kw)
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001
            n = self.errors.get(name, 0) + 1
            self.errors[name] = n
            if n <= 3:
                log(f"[guard] {name} failed ({n}):\n" + traceback.format_exc())
            if n >= 8:
                self.disabled.add(name)
                self.msg((f'{name}' + TXT("main.0001")))
            return None
        finally:
            self.ms[name] = self.ms.get(name, 0.0) + (time.perf_counter() - t0) * 1000


# ----------------------------------------------------------------------- world loading with fallbacks
def run_tool(args, loader, stage, max_sec=3600):
    """Run a python tool in a subprocess; its `@@{json}` lines drive the splash screen (map, speed, bar).
    Returns the exit code (0 ok, 2 partial result, 124 killed because it overran `max_sec`)."""
    q = queue.Queue()
    env = dict(os.environ, SK242_EVENTS="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable] + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    def reader():
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                q.put(line)
        proc.stdout.close()

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        t0 = time.time()
        killed = False
        while True:
            try:
                line = q.get(timeout=0.05)
                at = line.find("@@")                  # a text progress bar may precede the event on the same line
                if at >= 0:
                    try:
                        loader.event(stage, json.loads(line[at + 2:]))
                    except ValueError:
                        pass
                else:
                    log("[tool] " + line)
            except queue.Empty:
                loader.draw()
            if proc.poll() is None and time.time() - t0 > max_sec and not killed:
                killed = True
                log(f"[tool] {args[0]} overran {max_sec}s - stopping it")
                proc.kill()
            if proc.poll() is not None and not th.is_alive() and q.empty():
                break
    finally:                                     # window closed / crash: never leave a downloader running behind
        if proc.poll() is None:
            proc.kill()
    rc = 124 if killed else proc.returncode
    log(f"[tool] {args[0]} exit {rc} after {time.time() - t0:.0f}s")
    return rc


def _stale(path, osm):
    """World out of date with its sources (OSM data, build tools)?  Per-stage fingerprints, see tools/stages.py."""
    if not os.path.exists(os.path.join(path, "manifest.json")):
        return True
    tools = os.path.join(ROOT, "tools")
    before = set(sys.modules)
    try:
        sys.path.insert(0, tools)
        import stages
        stale = stages.stale_stages(path, osm)
        if stale:
            log(f"[build] world is stale; stages to rebuild: {', '.join(stale)}")
        return stages.is_stale(path, osm)
    except Exception as e:  # noqa: BLE001 - cannot tell: rebuild
        log(f"[build] stage check failed ({e}); rebuilding")
        return True
    finally:
        # tools/ has modules named like src/ ones (stations); do not leave them shadowing the game's own
        if tools in sys.path:
            sys.path.remove(tools)
        for m in set(sys.modules) - before:
            sys.modules.pop(m, None)


def plan_needs(a):
    """What has to happen before the game can start? -> {'osm': bool, 'dem': bool, 'build': bool}"""
    if a.demo or a.world:
        return {}
    osm = os.path.join(ROOT, "data", "osm")
    real = os.path.join(ROOT, "data", "cache", "world")
    try:
        box = json.load(open(os.path.join(osm, "box.json")))
    except Exception:  # noqa: BLE001
        box = None
    have = os.path.exists(os.path.join(osm, "roads.json"))
    box_ok = bool(box) and box.get("hx") == geo_mod.HX and box.get("hy") == geo_mod.HY and box.get("fmt") == 2
    # a partial download is completed on the next start, but not on every start (the servers may be down)
    retry = bool(box) and not box.get("complete", True) and time.time() - box.get("t", 0) > 3600
    extras = all(os.path.exists(os.path.join(osm, f)) for f in ("rail.json", "signals.json"))   # trains + real lights
    n = {"osm": a.refresh or not have or not box_ok or retry or (not extras and bool(box) and box.get("complete", True)),
         "dem": not os.path.exists(os.path.join(osm, "terrain.npy"))}
    n["build"] = n["osm"] or n["dem"] or not os.path.isdir(real) or _stale(real, osm)
    return n


RADIO_PROC = []


def start_radio_fetch(loader):
    """Download the car-radio music in the background (splash shows progress; it keeps going during play)."""
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        proc = subprocess.Popen([sys.executable, "tools/fetch_radio.py"], cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env)
        RADIO_PROC.append(proc)
    except Exception as e:  # noqa: BLE001
        log(f"[radio] cannot start the downloader: {e}")
        return

    def reader():
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("@@"):
                try:
                    ev = json.loads(line[2:])
                except ValueError:
                    continue
                if ev.get("t") == "radio":
                    loader.radio_line = T.RADIO_DL.format(n=ev["n"], target=ev["target"], title=ev.get("title", ""))
            elif line:
                log("[radio] " + line)
        loader.radio_line = ""

    threading.Thread(target=reader, daemon=True).start()


def ensure_world(arg_world, loader, demo_only=False, refresh=False, need=None):
    """Load the world; download what is missing; on corruption rebuild; if that fails fall back to the demo city."""
    import shutil
    need = need or {}
    real = arg_world or os.path.join(ROOT, "data", "cache", "world")
    demo = os.path.join(ROOT, "data", "cache", "world_demo")
    osm = os.path.join(ROOT, "data", "osm")
    if refresh:
        loader.say("refresh")
        shutil.rmtree(real, ignore_errors=True)
        for fn in ("roads", "buildings", "areas", "pois", "places"):
            try:
                os.remove(os.path.join(osm, fn + ".json"))
            except OSError:
                pass
    if demo_only:
        osm = os.path.join(ROOT, "data", "osm_nonexistent")
        real = os.path.join(ROOT, "data", "cache", "nonexistent")

    def attempt(path):
        loader.begin("world")
        return World(path, lambda f, note="": loader.tick(f, note), loader.world_part)

    rebuild = bool(need.get("build"))
    if os.path.isdir(real) and (arg_world or not rebuild) and not demo_only:
        try:
            return attempt(real)
        except WorldError as e:
            loader.warn = f"{e}"
            log(f"[world] {e}")
            loader.ensure_stage("build", 30)
    if not demo_only:
        if need.get("osm"):
            loader.begin("osm")
            osm_src = os.environ.get("SK242_SOURCE") or settings_mod.MAP_SOURCE_IDS[settings_mod.Settings()["osm_source"] % 3]
            # the game needs the whole map: an incomplete download is resumed, switching routes, before anything is built
            order = [osm_src] + [s for s in ("geofabrik", "overpass", "auto") if s != osm_src]
            for k, route in enumerate(order):
                log(f"[osm] download round {k + 1} via {route}")
                rc = run_tool(["tools/fetch_osm.py", "--source", route], loader, "osm", max_sec=62 * 60)
                if rc == 0:
                    break
            if rc == 2:
                loader.warn = T.PARTIAL
            loader.f["osm"] = 1.0
        if need.get("dem") or (not os.path.exists(os.path.join(osm, "terrain.npy")) and need.get("osm")):
            loader.begin("dem")
            run_tool(["tools/fetch_terrain.py"], loader, "dem", max_sec=20 * 60)       # optional: flat terrain if it fails
            loader.f["dem"] = 1.0
        if os.path.exists(os.path.join(osm, "roads.json")):
            loader.ensure_stage("build", 30)
            loader.begin("build")
            if run_tool(["tools/build_world.py", "--src", osm, "--out", real], loader, "build", max_sec=3600) == 0:
                loader.build_finished()
                try:
                    return attempt(real)
                except WorldError as e:
                    log(f"[world] rebuild unusable: {e}")
    loader.warn = T.FALLBACK_DEMO
    log("[world] falling back to demo city")
    if not os.path.isdir(demo):
        loader.ensure_stage("build", 30)
        loader.begin("build")
        if run_tool(["tools/make_synthetic_osm.py"], loader, "build") != 0 or run_tool(
                ["tools/build_world.py", "--src", os.path.join(ROOT, "data", "osm_demo"), "--out", demo], loader, "build") != 0:
            raise WorldError("could not build any world (see logs/game.log)")
        loader.build_finished(record=False)
    return attempt(demo)


# ----------------------------------------------------------------------- main
def keep_window_alive(on):
    """While loading, one long Python/numpy step (several seconds) used to stop the window from polling OS events, so it
    froze and Alt+Tab / moving it hung.  A profile hook on the main thread polls events at least every 0.2 s, between any two
    calls, without drawing (so it is safe even inside a render-texture pass)."""
    if not on:
        sys.setprofile(None)
        return
    last = [time.perf_counter()]

    def hook(frame, event, arg):
        now = time.perf_counter()
        if now - last[0] > 0.2:
            last[0] = now
            sys.setprofile(None)
            try:
                rl.poll_input_events()
            finally:
                sys.setprofile(hook)
    sys.setprofile(hook)


def fit_window(w, h):
    """A windowed size that fits the monitor (the game scales its picture to the window, so it need not equal the resolution)."""
    mon = rl.get_current_monitor()
    mw, mh = rl.get_monitor_width(mon), rl.get_monitor_height(mon)
    if mw <= 0 or mh <= 0:
        return w, h
    k = min(1.0, (mw - 40) / w, (mh - 120) / h)
    return int(w * k), int(h * k)


def center_window(w, h):
    mon = rl.get_current_monitor()
    p = rl.get_monitor_position(mon)
    rl.set_window_position(int(p.x + max(0, (rl.get_monitor_width(mon) - w) // 2)), int(p.y + max(30, (rl.get_monitor_height(mon) - h) // 2 - 20)))


def is_borderless():
    return bool(rl.is_window_state(rl.FLAG_BORDERLESS_WINDOWED_MODE))


def set_borderless(on):
    """Fullscreen as a borderless window on the monitor.  Exclusive fullscreen (rl.toggle_fullscreen) changes the
    video mode and made Alt+Tab to other windows unreliable; a borderless window switches like any other window."""
    if is_borderless() != on:
        rl.toggle_borderless_windowed()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", help="world directory (default data/cache/world)")
    ap.add_argument("--size", default="")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--test", type=int, default=0, help="run N scripted frames, print stats, exit")
    ap.add_argument("--shot", default="", help="screenshot path prefix for --test")
    ap.add_argument("--cars", type=int, default=90)
    ap.add_argument("--peds", type=int, default=110)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--start", default="", help="x,y metres from centre (debug)")
    ap.add_argument("--hour", type=float, default=17.0, help="start time of day (0-24)")
    ap.add_argument("--fetch-radio", dest="fetch_radio", action="store_true", help="legacy: download CC music into assets/radio (not needed, put files in music/)")
    ap.add_argument("--mute", action="store_true", help="no sound")
    ap.add_argument("--sound-dry", action="store_true", help="run the sound logic without an audio device and print what would play (library vs fallback)")
    ap.add_argument("--demo", action="store_true", help="offline synthetic demo city")
    ap.add_argument("--refresh", action="store_true", help="re-download the OSM data and rebuild the world")
    ap.add_argument("--nomenu", action="store_true", help="skip the start menu")
    ap.add_argument("--car", action="store_true", help="start inside the car (default: on foot next to it)")
    ap.add_argument("--walker", action="store_true", help="start on foot next to the car even in --test runs")
    ap.add_argument("--foot", action="store_true", help="start on foot (with --start: at the nearest footpath)")
    ap.add_argument("--deck", action="store_true", help="with --start: stand on the bridge deck if there is one")
    a = ap.parse_args()
    cfg = settings_mod.Settings()
    W, H = (int(v) for v in a.size.lower().split("x")) if a.size else settings_mod.RESOLUTIONS[cfg["res"]]

    rl.set_trace_log_level(rl.LOG_WARNING)
    flags = rl.FLAG_VSYNC_HINT | rl.FLAG_WINDOW_RESIZABLE | (rl.FLAG_MSAA_4X_HINT if cfg["aa"] in (1, 3) else 0)
    rl.set_config_flags(flags)
    if not rl.is_window_ready():                       # (the early splash may have opened it already)
        rl.init_window(W, H, TXT("main.0002"))
    if not rl.is_window_ready():                       # fallback: no MSAA / vsync
        rl.set_config_flags(rl.FLAG_WINDOW_RESIZABLE)
        rl.init_window(W, H, TXT("main.0003"))
    if not a.size:                                     # a resolution bigger than the monitor: smaller window, the picture is scaled to it
        fw_, fh_ = fit_window(W, H)
        if (fw_, fh_) != (W, H):
            rl.set_window_size(fw_, fh_)
            center_window(fw_, fh_)
    rl.rl_disable_backface_culling()
    font.load()
    if font.ERR or not font._fonts:
        log("[font] Cyrillic font not loaded: " + "; ".join(font.ERR or ["files missing in assets/fonts"]))
    rl.set_exit_key(rl.KEY_NULL)
    if a.fullscreen or cfg["fullscreen"]:
        set_borderless(True)
    rl.set_target_fps(0 if a.test else 144)

    need = plan_needs(a)
    present = present_mod.Present()
    keep_window_alive(True)
    loader = Loader(([("osm", 40)] if need.get("osm") else []) + ([("dem", 8)] if need.get("dem") else []) +
                    ([("build", 30)] if need.get("build") else []) + [("world", 12), ("overview", 8), ("textures", 6), ("chunks", 14)])
    if not a.test:                                                     # quiet, "distant radio" music while loading and in the title menu
        import loadmusic
        loader.music = loadmusic.LoadMusic(mute=a.mute or cfg["vol_master"] < 0.01, volume=cfg["vol_master"] * cfg["vol_radio"])
    if a.fetch_radio or os.environ.get("SK242_FETCH_RADIO"):          # the old downloader is off by default: the radio plays music/
        start_radio_fetch(loader)
    world = ensure_world(a.world, loader, a.demo, a.refresh, need)
    log(f"[game] world: {len(world.buildings)} buildings, {len(world.roads)} roads, {len(world.edges)} edges, "
        f"{len(world.trees)} trees, {len(world.parked)} parked cars")

    loader.begin("overview")
    t0 = time.time()
    try:
        overview, ov_size = bake_overview(world, 5120, os.path.join(world.path, "overview"), lambda f, n="": loader.tick(f, n))
    except Exception:  # noqa: BLE001 - fallback: tiny blank map
        log("[game] overview failed:\n" + traceback.format_exc())
        img = rl.gen_image_color(512, int(512 * world.hy / world.hx), rl.Color(201, 196, 182, 255))
        overview, ov_size = rl.load_texture_from_image(img), 512
        rl.unload_image(img)
    log(f"[game] overview {ov_size}px in {time.time() - t0:.1f}s")

    loader.begin("textures")
    tex = {}
    loader.tick(0.01, "textures")
    try:
        tex = gl3d.build_textures(lambda f: loader.tick(0.01 + 0.13 * f, "textures"))
    except Exception:  # noqa: BLE001
        log("[game] textures failed:\n" + traceback.format_exc())
        img = rl.gen_image_color(4, 4, rl.WHITE)
        t = rl.load_texture_from_image(img)
        tex = {"A": t, "B": t, "roof": t, "white": t, "panel": t, "house": t, "graf": t, "brick": t, "conc": t, "concg": t, "cream": t, "mix": t}
    streamer = Streamer(world, tex)
    renderer = Renderer(world, streamer, overview)
    renderer.log = log
    loader.tick(0.15, "overview mesh")
    renderer.build_overview()
    loader.tick(0.25, "car & pedestrian models")
    renderer.BUILD_BUDGET = 10 ** 9
    for kind in range(vehicles.N):
        renderer.ai_model(kind, 0)
        loader.tick(0.25 + 0.25 * (kind + 1) / vehicles.N, f"car models {kind + 1}/{vehicles.N}")
    for a_ in range(vehicles.PED_COUNT):
        fr_list = [0, 1] + ([12, 20, 21, 22, 23, 24, 25, 26, 27] if a_ in vehicles.WALKERS else [])      # the walk cycle and the standing pose, so the first crowd never builds models in-frame
        for j_, fr_ in enumerate(fr_list):
            renderer.ped_model(a_, 0, fr_, 0)
            loader.tick(0.5 + 0.3 * (a_ + (j_ + 1) / len(fr_list)) / vehicles.PED_COUNT, f"pedestrian models {a_ + 1}/{vehicles.PED_COUNT}")
    own_ = (0, 2, 3, 4, 5, 12, 13) + tuple(range(20, 28)) + tuple(range(30, 38))
    for j_, fr_ in enumerate(own_):
        renderer.ped_model(100 + cfg["lik"] % len(characters.LIKOVI), 0, fr_, 3)        # the player's own avatar: every pose it can show
        loader.tick(0.8 + 0.1 * (j_ + 1) / len(own_), "your character")
    renderer.BUILD_BUDGET = type(renderer).BUILD_BUDGET
    renderer.pick_model("burek")
    renderer.pick_model("ajvar")
    renderer.pick_model("cash")
    for _k in ("pistol", "uzi", "shotgun", "kalash", "bat", "knuckles", "chain", "zolja", "fuel"):
        renderer.pick_model(_k)
    loader.tick(0.9, "pickups & weapons")

    rng = random.Random(a.seed)
    loader.tick(0.92, "simulation")
    sim = Sim(world, rng, a.cars, a.peds)
    loader.tick(0.95, "pavement grid")
    world.kerb(0.0, 0.0)                                  # builds the pavement grid now instead of in the first frames of play
    sim.car.color = -1                                   # the player's own car gets racing stripes
    sim.clock.hour = (a.hour if a.test or "--hour" in sys.argv else cfg["hour"]) % 24.0
    streamer.clock = sim.clock
    sim.auto_respawn = bool(a.test)
    lights = signals.Signals(world)
    sim.traffic.signals = sim.lights = lights
    loader.tick(0.97, "traffic lights")
    print(f"[game] traffic lights: {len(lights.items)} signal heads")                     # test runs have nobody to press R
    loader.tick(0.99, "sound")
    aud = audio_mod.Audio(mute=a.mute, root=ROOT, dry=a.sound_dry)
    print(f"[sound] library: {len(aud.lib)} sounds found, {aud.req[0]} new request files in sound_requests/ ({aud.req[2]} of {aud.req[1]} sounds done)")
    car_radio = radio_mod.Radio(aud)
    cabin_music = radio_mod.CabinMusic(aud, car_radio)
    spk = SpeechWorker()
    night = Night(world)
    places = Places(world)
    sim.places = places
    import transit
    _osm = os.environ.get("SK242_OSM_DIR") or os.path.join(ROOT, "data", "osm")
    if not (transit.current(_osm) and os.path.exists(os.path.join(_osm, "map_pois.json"))):
        try:                                               # bus lines + map POIs from the cached country file (once)
            import subprocess
            r_ = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "fetch_extras.py")], capture_output=True,
                                text=True, timeout=300)
            print((r_.stdout + r_.stderr).strip()[-600:])
        except Exception as e_:  # noqa: BLE001 - buses / markers are optional
            print(f"[game] extras skipped: {e_}")
    sim.transit = transit.Transit(sim, os.environ.get("SK242_OSM_DIR") or os.path.join(ROOT, "data", "osm"))
    log(f"[game] city buses: {len(sim.transit.lines)} JSP lines, {len(sim.transit.stops)} stops")
    import kids as kids_mod
    sim.kids = kids_mod.Kids(sim)
    log(f"[game] playgrounds / schools / pitches: {len(sim.kids.sites)}")
    import dogs as dogs_mod
    sim.dogs = dogs_mod.Dogs(sim)
    import birds as birds_mod
    sim.birds = birds_mod.Birds(sim)
    import rentals
    sim.rentals = rentals.Rentals(sim)
    log(f"[game] rental e-scooters: {len(sim.rentals.spots)}")
    sim.works = works_mod.Works(sim)
    log(f"[game] building sites: {len(sim.works.sites)}")
    pend_say = {}
    say_state = {"t": -9.0}
    flags = {"labels": True}

    def apply_cfg(c, first=False):
        """Push the menu settings into the running game."""
        aud.master = 0.0 if a.mute else c["vol_master"]
        aud.bus.update({"sfx": c["vol_sfx"], "engine": c["vol_engine"], "ambient": c["vol_ambient"], "speech": c["vol_speech"]})
        if not first:
            sim.clock.hour = c["hour"]
        sim.clock.speed = c.time_mult
        sim.dens_traffic, sim.dens_peds = c.traffic_mult, c.ped_mult
        sim.services.amb_on, sim.services.fire_on = c["ambulance"], c["fire"]
        spk.set_engine(c["voice"])
        spk.set_speed(settings_mod.SPEECH_SPEEDS[c["speech_speed"] % len(settings_mod.SPEECH_SPEEDS)])
        sim.aggro, sim.lang = c["aggro"], c["lang"]
        sim.speech_freq = settings_mod.SPEECH_FREQ[c["speech_freq"] % len(settings_mod.SPEECH_FREQ)]
        if getattr(sim, "places", None) is not None:
            sim.places.lang = c["lang"]
        d = c["detail"]
        renderer.shadows = d >= 1
        flags["labels"] = d >= 1 and c["labels"]
        particles.max = (250, 600, 900)[d]
        night.detail = d
        if not a.test:
            if is_borderless() != bool(c["fullscreen"]):
                set_borderless(bool(c["fullscreen"]))
            elif not c["fullscreen"] and not a.size:
                w_, h_ = fit_window(*settings_mod.RESOLUTIONS[c["res"]])
                if (rl.get_screen_width(), rl.get_screen_height()) != (w_, h_):
                    rl.set_window_size(w_, h_)
                    center_window(w_, h_)
    if a.start:
        q = world.nearest_drive_point(*(float(v) for v in a.start.split(",")))
        if q:
            sim.car.x, sim.car.y, sim.car.h = q
            sim.car.az = world.level(q[0], q[1], 1e9)          # on the bridge deck if there is one
            sim.car.lx, sim.car.ly = q[0], q[1]
            sim.safe = q
    if a.foot:
        sim.exit_car()
        if a.start:
            x_, y_ = (float(v) for v in a.start.split(","))
            nw = world.nearest_walk_point(x_, y_, 150)
            if nw:
                x_, y_, _dx, _dy = world.edge_point(world.edges[nw[0]], nw[1])
            wk_ = sim.walker
            wk_.x, wk_.y = x_, y_
            wk_.lx, wk_.ly = x_, y_
            wk_.az = world.level(x_, y_, 1e9) if a.deck else world.ground_y(x_, y_)
            sim.safe, sim.safe_z = (x_, y_, 0.0), wk_.az
    labels = build_labels(world)
    particles, popups = Particles(random.Random(5)), Popups()
    gains = fx_mod.Gains()
    fx_mod.GROUND = world.ground_y
    hud = Hud(world, overview, ov_size)
    try:                                                   # faint points of interest on the maps
        with open(os.path.join(os.environ.get("SK242_OSM_DIR") or os.path.join(ROOT, "data", "osm"), "map_pois.json"), encoding="utf-8") as f_:
            hud.pois = [p_ for p_ in json.load(f_) if isinstance(p_, list) and len(p_) == 4]
    except (OSError, ValueError):
        hud.pois = []
    print(f"[game] map points of interest: {len(hud.pois)}")
    sim.dogs.add_pois(hud.pois)
    log(f"[game] stray dog hubs (kiosks, food places): {sum(len(v) for v in sim.dogs.hubs.values())}")
    labels += [(nm_, x_, world.ground_y(x_, y_) + 3.2, y_, "poi:" + c_) for x_, y_, c_, nm_ in hud.pois if nm_]
    hud.markers = [(p[0], p[1], p[2]) for p in places.list]
    pois = poi_mod.Pois(hud.pois)                           # walk-in places with a 1-4 tooltip
    selfie = selfie_mod.Selfie(ROOT)
    guard = Guard(lambda m: hud.set_banner(m, 5))
    apply_cfg(cfg, True)

    S = world.chunk
    sx, sy = sim.car.x, sim.car.y

    def want_list(cx_, cz_, ppm_, sw_, sh_, pad):
        kk = 1.0 + (35.0 / ((sh_ / 2) / (ppm_ * math.tan(math.radians(38.0 / 2)))) if world.hilly else 0.0)
        hw, hh = sw_ / (2 * ppm_) * kk + pad, sh_ / (2 * ppm_) * kk + pad
        x0, x1 = math.floor((cx_ - hw) / S), math.floor((cx_ + hw) / S)
        y0, y1 = math.floor((cz_ - hh) / S), math.floor((cz_ + hh) / S)
        ks = [(cx, cy) for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1) if (cx, cy) in world.chunks or True]
        lx, ly = int(world.hx // S) + 1, int(world.hy // S) + 1
        ks = [k for k in ks if -lx <= k[0] < lx and -ly <= k[1] < ly]
        ks.sort(key=lambda c: (c[0] * S + S / 2 - cx_) ** 2 + (c[1] * S + S / 2 - cz_) ** 2)
        return ks

    loader.begin("chunks")
    first = want_list(sx, sy, 7.0, W, H, 30)[:40]
    for i, key in enumerate(first):
        loader.tick(i / len(first), f"chunk {i + 1}/{len(first)}  ({key[0]},{key[1]})")
        streamer.update([key], True, 1e9)
        loader.mark_rect(key[0] * S, key[1] * S, (key[0] + 1) * S, (key[1] + 1) * S)
        loader.tick((i + 1) / len(first), f"chunk {i + 1}/{len(first)}  ({key[0]},{key[1]})")
    loader.finish()
    keep_window_alive(False)
    gc.collect()
    gc.freeze()                                    # the world is ~half a million long-lived objects: a full collection of them froze the game for ~0.4 s
    gc.set_threshold(50000, 20, 100)
    res_ = ""
    log("[game] ready")
    if a.nomenu and loader.music is not None:
        loader.music.close()
    if not a.test and not a.nomenu:
        res_ = menu_mod.run(cfg, apply_cfg, False, aud=aud, music=loader.music)
        if loader.music is not None:
            loader.music.close()
        if res_ == "quit":
            rl.close_window()
            return
        apply_cfg(cfg, True)
        characters.apply(sim, cfg["lik"])
        sim.clock.hour = cfg["hour"] % 24.0
        if res_.startswith("load"):
            d_ = savegame.read(int(res_[4:]))
            if d_:
                sx, sy = savegame.restore(sim, cfg, d_)
                apply_cfg(cfg, True)
    if (a.walker or (not a.test and not a.car)) and not a.foot and sim.mode == "car" and not res_.startswith("load"):
        sim.exit_car()                                     # new game: you start as a walker standing next to the car
    hud.set_banner(rng.choice(slang.START), 4.0)
    popups.add(rng.choice(slang.TIPS), sx, sy, 6.0, 7.0, (200, 230, 255), 20)

    cam_x, cam_y, ppm = sx, sy, 9.0
    cam_h = world.ground_y(sx, sy)
    user_zoom = a.zoom
    show_map = False
    mouse_grab = False
    mouse_steer = 0.0
    show_dbg = a.test > 0
    shake = 0.0
    frame = 0
    t_game = 0.0
    ft_hist = []
    hitch_t0, hitch_n = time.perf_counter(), 0          # frames over 100 ms are written to logs/game.log with what took the time
    gc_t = [0.0, 0.0]

    def gc_cb(phase, info):
        if phase == "start":
            gc_t[0] = time.perf_counter()
        else:
            gc_t[1] += time.perf_counter() - gc_t[0]
    gc.callbacks.append(gc_cb)
    auto_q = 1.0
    last_crash_txt = 0.0
    tip_t = 25.0
    want_menu = False
    want_chars = False

    def hero_who():
        return characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][1]

    def hero_line():
        lines = hero_lines.LINES.get(characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][0])
        return rng.choice(talk.pool(lines, getattr(sim, "lang", 1))) if lines else None
    worst_bake = 0.0

    def say(text, x, y, who=None, prio=False):
        """Speak a line (Macedonian formant synth, background thread). Volume falls off with distance."""
        fx_, fy_, _, _ = sim.focus()
        vol = 1.0 if prio else max(0.0, 1.0 - math.hypot(x - fx_, y - fy_) / 32.0)
        if vol < 0.15 or len(text) > 90:
            return
        if not prio and t_game < pois.sup_until:
            return                                              # right after a POI visit / selfie only the avatar speaks
        for k_ in [k_ for k_, v_ in pend_say.items() if t_game - v_[2] > 4.0]:   # lost requests never block speech
            del pend_say[k_]
        if not prio and (t_game - say_state["t"] < 1.3 or aud.speaking() or pend_say):
            return                                              # one voice at a time
        say_state["t"] = t_game
        key = (text, who or "")
        if prio:
            pend_say.clear()
        pend_say[key] = (vol, prio, t_game)
        spk.request(key, text, who or "")

    def handle_events():
        nonlocal shake, last_crash_txt
        fxs, fys, _a, _b = sim.focus()

        def near(x, y, r=60.0):
            return math.hypot(x - fxs, y - fys) < r
        for kind, d in sim.events:
            if kind == "punch" or kind == "kick":
                aud.at(kind if d["hit"] else "swing", d["x"], d["y"], 0.8 if d["hit"] else 0.35)
                if d["hit"]:
                    particles.sparks(d["x"], d["y"], 5, 1.1)
                    shake = max(shake, 0.25)
            elif kind == "dog_bark":
                aud.at("bark_" + "abcd"[d["voice"]], d["x"], d["y"], 1.0, d["pitch"], maxd=110.0, ref=16.0)
                if d.get("text") and near(d["x"], d["y"], 30.0):
                    popups.add(d["text"], d["x"], d["y"], 1.4, 1.2, (255, 235, 200), 18)
            elif kind == "bird_call":
                aud.at(d["call"], d["x"], d["y"], 0.7, 1.0, maxd=70.0, ref=8.0)
            elif kind == "dog_yip":
                aud.at("yip", d["x"], d["y"], 0.9, d["pitch"], maxd=80.0, ref=12.0)
            elif kind == "dog_pet":
                aud.at("yip", d["x"], d["y"], 0.7, d["pitch"] * 0.8, maxd=50.0, ref=10.0)
                particles.emit("b", d["x"], d["y"], 0.9, 0, 0, 1.4, 6, 0.16, 1.1, (255, 120, 160), 1.0, 0.8, 0.0)
            elif kind == "hit":
                particles.emit("b", d["x"], d["y"], 1.0, 0, 0, 1.5, 4, 0.18, 0.5, (190, 20, 24), 2.0, 0.8, -6.0)
            elif kind == "ko":
                aud.play("body_fall", 0.8, 0.7)
                popups.add(TXT("main.0004"), d["x"], d["y"], 2.6, 1.8, (255, 230, 90), 26)
            elif kind == "gunfire":
                aud.at({"zolja": "rocket_launch", "pistol": "shot_pistol", "uzi": "shot_uzi", "shotgun": "shot_shotgun", "kalash": "shot_kalash"}.get(d["kind"], "shot")
                       if near(d["x"], d["y"], 70.0) else "shot_distant",
                       d["x"], d["y"], 0.6 if d["kind"] == "zolja" else 0.75, {"uzi": 1.25, "kalash": 0.9, "shotgun": 0.7}.get(d["kind"], 1.0), maxd=220.0)
            elif kind == "bullet_wall":                              # chips of plaster + dust puff
                aud.at("bullet_ricochet" if rng.random() < 0.4 else "bullet_wall", d["x"], d["y"], 0.5)
                particles.debris(d["x"], d["y"], (200, 194, 180), 4, 1.2)
                particles.smoke(d["x"] + d["nx"] * 0.3, d["y"] + d["ny"] * 0.3, 0.0, 1, 1.2, d["nx"] * 2, d["ny"] * 2, 0.4)
            elif kind == "bullet_car":
                aud.at("bullet_car_ping", d["x"], d["y"], 0.5)                               # metal: sparks
                particles.sparks(d["x"], d["y"], 6, 0.9)
            elif kind == "bullet_tree":
                aud.at("bullet_tree", d["x"], d["y"], 0.4)
                particles.leaves(d["x"], d["y"], 5)
            elif kind == "bullet_ground":
                aud.at("bullet_ground", d["x"], d["y"], 0.35)
                particles.smoke(d["x"], d["y"], 0.1, 1, 0.2, 0, 0, 0.35)
                particles.debris(d["x"], d["y"], (120, 112, 100), 3, 0.2)
            elif kind == "rocket_trail":
                if rng.random() < 0.7:
                    particles.smoke(d["x"], d["y"], 0.3, 1, 1.1, 0, 0, 0.5)
            elif kind == "weapons_new":
                hud.set_banner(TXT("main.0005"), 4.0)
            elif kind == "pay":
                gains.add(d["amount"], d["x"], d["y"])
                aud.play("cash", 0.35, 1.0 + min(0.5, d["amount"] / 80.0))
            elif kind == "board":
                aud.play("bus_air_brake", 0.5)
                aud.play("bus_door", 0.6)
                hud.set_banner((TXT("main.0006") + f"{d['fare']}" + TXT("main.0007")), 5.0)
            elif kind == "alight":
                aud.play("bus_door", 0.6)
                hud.set_banner(TXT("main.0008"), 2.0)
            elif kind == "ped_shot":
                aud.at("bullet_flesh", d["x"], d["y"], 0.6)
                streamer.add_decal(("d", d["x"], d["y"], 0.8, (150, 20, 24, 200)))
            elif kind == "shot":
                aud.play("shot", 0.7, 1.0)
                n = int(math.hypot(d["x1"] - d["x0"], d["y1"] - d["y0"]) / 1.5) + 1
                for i in range(n):
                    f = i / n
                    particles.emit("k", d["x0"] + (d["x1"] - d["x0"]) * f, d["y0"] + (d["y1"] - d["y0"]) * f, 1.0, 0, 0, 0, 1, 0.12, 0.12, (255, 240, 160), 0.1, 0.5, 0.0)
                particles.sparks(d["x1"], d["y1"], 6, 1.0)
                shake = max(shake, 0.3)
            elif kind == "hurt" or kind == "hurt_car":
                aud.play("hurt_thud", 0.9, 0.85)
                shake = max(shake, 0.5)
            elif kind == "knocked_out":
                hud.set_banner(rng.choice(slang.KO_SELF), 3.5)
                if d["lost"]:
                    popups.add((f"-{d['lost']}" + TXT("main.0009")), sim.walker.x, sim.walker.y, 3.0, 3.0, (255, 150, 140), 22)
            elif kind == "wake":
                hud.set_banner(TXT("main.0010"), 2.5)
            elif kind == "bought":
                aud.play("eat", 0.8)
                popups.add((f"{d['item']}  +{d['heal']}" + TXT("main.0011")), sim.walker.x, sim.walker.y, 2.8, 2.4, (255, 220, 120), 22)
                hud.set_banner(rng.choice(slang.BOUGHT), 2.0)
            elif kind == "rent":
                aud.play("cash", 0.35, 1.0)
                popups.add((f"{d['item']}  -{d['price']}" + TXT("main.0012")), sim.walker.x, sim.walker.y, 2.8, 2.0, (255, 220, 120), 20)
            elif kind == "broke":
                aud.play("denied_buzz", 0.6)
                popups.add((f"{d['item']} = {d['price']}" + TXT("main.0012")), sim.walker.x, sim.walker.y, 2.8, 2.0, (255, 150, 140), 20)
                hud.set_banner(rng.choice(slang.BROKE), 2.0)
            elif kind == "cash":
                aud.play("cash", 0.8)
                popups.add((f"+{d['amt']}" + TXT("main.0013")), d["x"], d["y"], 2.0, 1.8, (140, 255, 150), 22)
            elif kind == "gun":
                aud.play("weapon_pickup", 0.8, 1.4)
                hud.set_banner((d.get('name', TXT("main.0055")).upper() + TXT("main.0014")), 2.4)
            elif kind == "fuel":
                aud.play("fuel_pour", 0.6, 0.9)
                hud.set_banner((TXT("main.0015") + f"{int(d['f'] * 100)}%."), 2.0)
            elif kind == "station":                                  # petrol station / car wash service (stations.py)
                aud.play(d.get("snd", "cash"), 0.6, 0.9)
                hud.set_banner(d["text"], 3.0)
            elif kind == "fuel_low":
                aud.play("fuel_warning", 0.6, 0.9)
                hud.set_banner(TXT("main.0016"), 3.0)
            elif kind == "fuel_out":
                aud.play("engine_stall", 0.8)
                hud.set_banner(TXT("main.0017"), 3.5)
            elif kind == "teleport":
                aud.play("teleport_whoosh", 0.5, 0.7)
            elif kind == "spray":
                dxs, dys = d["x1"] - d["x0"], d["y1"] - d["y0"]
                ls = math.hypot(dxs, dys) or 1.0
                particles.emit("w", d["x0"], d["y0"], 1.3, dxs / ls * 9, dys / ls * 9, 1.5, 3, 0.22, 0.7, (170, 210, 255), 0.6, 0.8, -4.0)
            elif kind == "extinguished":
                aud.at("fire_out_hiss", d["x"], d["y"], 0.7)
                particles.smoke(d["x"], d["y"], 0.0, 6, 0.8, 0, 0, 1.6)
                popups.add(TXT("main.0018"), d["x"], d["y"], 3.0, 3.0, (170, 220, 255), 22)
            elif kind in ("revived", "revived_ped"):
                aud.play("revive", 0.9)
                aud.play("defib_zap", 0.6)
                if kind == "revived":
                    hud.set_banner(TXT("main.0019"), 3.0)
                else:
                    popups.add(TXT("main.0020"), d["x"], d["y"], 2.4, 2.0, (170, 255, 190), 24)
            if kind == "crash":
                if d["impact"] > 8:
                    aud.at("crash_glass", d["x"], d["y"], 0.6)
                aud.at("crash" if d["impact"] > 6 else "crash_light", d["x"], d["y"], min(1.0, d["impact"] / 14.0), 1.0 + rng.uniform(-0.1, 0.1))
            elif kind == "horn":
                aud.at(vehicles.HORN_SOUND[d["body"].kind], d["body"].x, d["body"].y, 0.6, 1.0 + (d["body"].kind % 3) * 0.04, maxd=160.0)
            elif kind == "explode":
                if near(d["body"].x, d["body"].y, 90):
                    aud.at("crowd_panic", d["body"].x, d["body"].y, 0.5, 1.0, "ambient", 140.0, 20.0)
                aud.at("boom" if near(d["body"].x, d["body"].y, 150) else "boom_distant", d["body"].x, d["body"].y, 1.0, maxd=450.0, ref=40.0)
            elif kind == "splash":
                aud.at("splash_big" if d.get("big") else "splash", d["x"], d["y"], 0.8 if not d.get("big") else 1.0, 0.8 if d.get("big") else 1.0)
            elif kind == "hurt_fall":
                aud.play("body_fall", 0.45, 1.5)
            elif kind == "fall":
                aud.at("crash", d["x"], d["y"], min(1.0, d["speed"] / 14.0), 0.8)
            elif kind in ("burek", "ajvar"):
                aud.play("eat" if kind == "burek" else "chime", 0.7)
            elif kind == "ped_hit":
                aud.at("body_hit_car", d["ped"].x, d["ped"].y, 0.6, 0.6)
            if kind == "shout":
                rb_ = getattr(sim, "riding", None)
                if rb_ is not None and d.get("who") == TXT("transit.0008") and math.hypot(d["x"] - fxs, d["y"] - fys) < 25:
                    car_radio.duck(3.5)                  # your bus calls out the stop: the radio drops to 25 % first
                    say(d["text"], fxs, fys, d.get("who"), True)
                else:
                    say(d["text"], d["x"], d["y"], d.get("who"))
            elif kind == "shout_self":
                ln_ = hero_line() or rng.choice((TXT("main.0021"), TXT("main.0022"), TXT("main.0023")))
                d["text"] = ln_
                say(ln_, fxs, fys, hero_who(), True)
        for kind, d in sim.events:
            if kind == "crash":
                b, imp = d["body"], d["impact"]
                if imp > 2.5:
                    particles.sparks(d["x"], d["y"], int(min(14, imp * 1.4)))
                if imp > 6:
                    c = gl3d.CAR_COLORS[b.color % 12]
                    particles.debris(d["x"], d["y"], c, int(min(10, imp)))
                if b.player_car and sim.mode == "car":
                    shake = max(shake, min(imp * 0.12, 1.8))
                if d["kind"] in ("break", "break_tree"):           # knocked it over: hide the mesh, throw bits
                    streamer.reload_near(d["x"], d["y"])
                    particles.debris(d["x"], d["y"], (120, 96, 70) if d["kind"] == "break_tree" else (150, 150, 156), 12, 0.6)
                    if d["kind"] == "break_tree":
                        particles.leaves(d["x"], d["y"], 24)
                    aud.at("tree_break" if d["kind"] == "break_tree" else "crash_metal", d["x"], d["y"], min(0.6, 0.2 + imp / 20.0), 0.8)
                if d["kind"] == "tree" and imp > 2:
                    particles.leaves(d["x"], d["y"], int(min(14, imp * 2)))
                    if t_game - last_crash_txt > 2.5 and b.player_car:
                        popups.add(rng.choice(slang.TREE), b.x, b.y, 3.0, 2.0, (160, 255, 160))
                        last_crash_txt = t_game
                elif imp > 5 and t_game - last_crash_txt > 2.5 and b.player_car:
                    popups.add(rng.choice(slang.CRASH), b.x, b.y, 3.0, 2.0, (255, 210, 120))
                    last_crash_txt = t_game
            elif kind == "ped_hit":
                p, b = d["ped"], d["body"]
                streamer.add_decal(("d", p.x, p.y, 0.9, (150, 20, 24, 200)))
                streamer.add_decal(("d", p.x + 0.4, p.y - 0.3, 0.5, (130, 16, 20, 180)))
                particles.emit("b", p.x, p.y, 0.8, 0, 0, 2.2, 10, 0.26, 0.9, (190, 20, 24), 3.0, 0.8, -6.0)
                popups.add(rng.choice(slang.PED_HIT), p.x, p.y, 2.6, 2.2, (255, 160, 150))
                sim.stats["peds"] += 1
                if b.player_car:
                    shake = max(shake, 0.5)
            elif kind == "shout":
                spk_ = next((p_ for p_ in sim.peds.list if abs(p_.x - d["x"]) < 0.01 and abs(p_.y - d["y"]) < 0.01), None)   # the bubble follows the speaker
                popups.add((d["who"] + ": " if d.get("who") else "") + d["text"], d["x"], d["y"], 2.6, 2.4, (255, 255, 255), 18, spk_)
            elif kind == "shout_self":
                if sim.walker and d.get("text"):
                    popups.add(d["text"], sim.walker.x, sim.walker.y, 2.6, 3.0, (160, 255, 200), 20, sim.walker, True)
            elif kind == "horn":
                b = d["body"]
                popups.add(rng.choice(slang.HORN), b.x, b.y, 3.2, 1.4, (255, 240, 120), 24, b)
            elif kind == "burek":
                popups.add(rng.choice(slang.BUREK), d["x"], d["y"], 2.5, 2.2, (255, 220, 110), 22)
                particles.emit("c", d["x"], d["y"], 0.8, 0, 0, 3, 10, 0.25, 0.9, (255, 210, 90), 3.0, 0.9, -6)
            elif kind == "ajvar":
                popups.add(rng.choice(slang.AJVAR), d["x"], d["y"], 2.5, 2.4, (255, 120, 100), 22)
                particles.emit("c", d["x"], d["y"], 0.8, 0, 0, 3, 14, 0.25, 0.9, (220, 40, 30), 3.0, 0.9, -6)
                hud.set_banner(TXT("main.0024"), 2.0)
            elif kind == "splash":
                popups.add(rng.choice(slang.SPLASH), d["x"], d["y"], 3.0, 2.8, (160, 210, 255), 22)
                particles.emit("w", d["x"], d["y"], 0.6, 0, 0, 4, 18, 0.35, 0.9, (140, 190, 240), 4.0, 0.9, -8)
                hud.set_banner(TXT("main.0025"), 1.6)
            elif kind == "hurt_fall":
                popups.add(rng.choice((TXT("main.0026"), TXT("main.0027"), TXT("main.0028"), TXT("main.0029"))), sim.walker.x, sim.walker.y, 3.0, 1.8, (255, 160, 160), 22)
            elif kind == "fall":
                b = d["body"]
                particles.debris(b.x, b.y, (120, 120, 120), 10, 0.4)
                popups.add(TXT("main.0030"), b.x, b.y, 3.2, 2.2, (255, 220, 160), 22)
            elif kind == "kerb":                                     # clunk over the kerb
                if d["body"].player_car:
                    aud.at("kerb_bump", d["body"].x, d["body"].y, min(0.35, d["speed"] / 40.0), 1.6)
            elif kind == "rocket":
                particles.explosion(d["x"], d["y"])
                aud.at("boom_rocket", d["x"], d["y"], 1.0, maxd=450.0, ref=40.0)
                streamer.add_decal(("d", d["x"], d["y"], 3.6, (20, 18, 16, 190)))
                shake = max(shake, 3.0)
            elif kind == "swing":
                _w = d.get("weapon")
                _snd = ("knuckles_hit" if d["hit"] else "swing") if _w == "knuckles" else (("chain_hit" if d["hit"] else "chain_swing") if _w == "chain" else ("bat_hit" if d["hit"] else "swing"))
                aud.at(_snd, d["x"], d["y"], 0.5 if d["hit"] else 0.2)
            elif kind == "prop_break":                              # a punched / blasted prop: hide its mesh, throw bits
                streamer.reload_near(d["x"], d["y"])
                big = d["kind"] in ("post", "tree")
                particles.debris(d["x"], d["y"], (120, 96, 70) if d["kind"] == "tree" else (150, 150, 156), 14 if big else 8, 0.6)
                if d["kind"] == "tree":
                    particles.leaves(d["x"], d["y"], 24)
                aud.at("tree_break" if d["kind"] == "tree" else ("crash_metal" if d["kind"] == "post" else "crash_wood"), d["x"], d["y"], 0.5, 1.3 if not big else 0.9)
            elif kind == "prop_thud":
                aud.at("prop_thud", d["x"], d["y"], 0.4, 0.7)
                if d.get("leaves"):
                    particles.leaves(d["x"], d["y"], 8)
            elif kind == "cpr":
                if t_game > sx["cpr"]:
                    sx["cpr"] = t_game + 3.0
                    aud.at("cpr_pump", d["x"], d["y"], 0.5)
                particles.emit("c", d["x"], d["y"], 1.2, 0, 0, 1.5, 1, 0.3, 0.9, (255, 110, 150), 2.0, 0.8, 0.6)
            elif kind == "car_ignite":
                b = d["body"]
                aud.at("fire_ignite", b.x, b.y, 0.7)
                popups.add(rng.choice((TXT("main.0031"), TXT("main.0032"), TXT("main.0033"))), b.x, b.y, 3.0, 2.2, (255, 170, 90))
            elif kind == "explode":
                b = d["body"]
                particles.explosion(b.x, b.y)
                streamer.add_decal(("d", b.x, b.y, 4.2, (20, 18, 16, 190)))
                streamer.add_decal(("d", b.x, b.y, 2.4, (8, 8, 8, 200)))
                shake = max(shake, 2.6 if math.hypot(b.x - cam_x, b.y - cam_y) < 80 else 0.6)
                popups.add(rng.choice(slang.EXPLODE), b.x, b.y, 4.5, 3.0, (255, 190, 80), 26)
            elif kind == "stolen":
                b = d["body"]
                aud.at("engine_start", b.x, b.y, 0.7)
                if rng.random() < 0.25:
                    aud.at("car_alarm", b.x, b.y, 0.6, 1.0, "sfx", 120.0, 12.0)
                popups.add(TXT("main.0034"), b.x, b.y, 3.4, 2.0, (255, 255, 120), 22)
            elif kind == "door" or kind == "door_shut":
                aud.at("car_door_open" if kind == "door" else "car_door_close", d["body"].x, d["body"].y, 0.5 if kind == "door" else 0.7, 0.6 if kind == "door" else 0.75)
            elif kind == "slam" or kind == "knock_off":
                aud.at("car_door_slam", d["x"], d["y"], 0.9, 0.8)
                particles.emit("c", d["x"], d["y"], 0.3, 0, 0, 1.2, 8, 0.3, 0.6, (150, 140, 120), 1.0, 0.6, 0.5)
            elif kind == "enter":
                b = d["body"]
                aud.at("engine_start", b.x, b.y, 0.7)
                popups.add(b.name, b.x, b.y, 3.4, 1.8, (200, 240, 255), 20)
            elif kind == "walker_dead":
                sim.stats["deaths"] += 1
                hud.set_banner(rng.choice(slang.DEATH), 3.0)
                if sim.walker:
                    streamer.add_decal(("d", sim.walker.x, sim.walker.y, 1.0, (150, 20, 24, 200)))
            elif kind == "respawn":
                hud.set_banner(TXT("main.0035"), 2.0)
            elif kind == "free_model":
                pass                      # the renderer owns the model and frees it in _free_orphans (freeing here too = double free, heap crash)
        sim.events.clear()

    def effects(dt):
        """skid marks, tyre smoke, damage smoke and fire."""
        for b in sim.bodies:
            sp = b.speed
            fx_, fy_ = math.cos(b.h), math.sin(b.h)
            if sp > 3.0 and b.alive:
                vl = abs(-b.vx * fy_ + b.vy * fx_)
                slipping = vl > 2.3 or (b.braking and sp > 9.0) or (b.empty is False and b.slip > 2.3)
                if slipping:
                    off, wd = vehicles.DIMS[b.kind][0] * 0.31, vehicles.DIMS[b.kind][1] / 2 - 0.12
                    pts = [(b.x - fx_ * off - fy_ * s * wd * -1, b.y - fy_ * off + fx_ * s * wd * -1) for s in (-1, 1)]
                    if b.skid:
                        for (px, py), (qx, qy) in zip(b.skid, pts):
                            if (px - qx) ** 2 + (py - qy) ** 2 < 25:
                                streamer.add_decal(("l", px, py, qx, qy, 0.13, (8, 8, 10, 110)))
                    b.skid = pts
                    if vl > 3.5 and rng.random() < 0.6:
                        particles.smoke(pts[0][0], pts[0][1], 0.0, 1, 0.3)
                else:
                    b.skid = None
            else:
                b.skid = None
            if b.out:
                if b.exploded and rng.random() < 0.05:
                    particles.smoke(b.x, b.y, 0.3, 1, 0.8)
            elif b.exploded:
                if rng.random() < 0.25:
                    particles.smoke(b.x, b.y, 0.9, 1, 1.0)
                if rng.random() < 0.45 * b.fire_lvl:                # the wreck keeps burning until the fire brigade gets there
                    particles.fire(b.x + rng.uniform(-1, 1), b.y + rng.uniform(-0.6, 0.6), 1, 0.7, 0.35 + 0.5 * b.fire_lvl)
            elif b.health <= 0:
                if rng.random() < b.fire_lvl:                      # the fire brigade turns the flames down
                    particles.fire(b.x + fx_ * 1.2, b.y + fy_ * 1.2, 2, 0.9, 0.4 + 0.6 * b.fire_lvl)
                particles.smoke(b.x + fx_, b.y + fy_, 0.9, 1, 1.2)
            elif b.health < 35 and rng.random() < 0.35:
                particles.smoke(b.x + fx_ * 1.4, b.y + fy_ * 1.4, 0.3 + (35 - b.health) / 50, 1, 1.0)

    def exhaust(dt):
        """Diesel smoke: city buses and big trucks puff dark smoke when pulling away, old cars a little."""
        fxs, fys = sim.focus()[:2]
        pol = cfg.get("pollution", 1.0)
        for b in sim.bodies:
            bus = getattr(b, "bus_line", None) is not None
            if not (bus or vehicles.LARGE[b.kind]) or b.exploded or (b.x - fxs) ** 2 + (b.y - fys) ** 2 > 90 ** 2:
                continue
            thr = b.ctl[0] if getattr(b, "ctl", None) else 0.0
            rate = (9.0 if thr > 0.3 and b.speed < 6 else 2.5) * dt * pol
            if rng.random() < rate:
                L = vehicles.DIMS[b.kind][0] / 2
                hx, hy = math.cos(b.h), math.sin(b.h)
                particles.smoke(b.x - hx * L, b.y - hy * L, 0.75, 1, 0.5, -hx * 2, -hy * 2, 0.8)
        for c in sim.traffic.cars:
            if (c.x - fxs) ** 2 + (c.y - fys) ** 2 > 70 ** 2:
                continue
            big = vehicles.LARGE[c.kind]
            if rng.random() < (5.0 if big else 0.35) * dt * (2.0 if c.v < 4 else 1.0) * pol:
                L = vehicles.DIMS[c.kind][0] / 2
                hx, hy = math.cos(c.h), math.sin(c.h)
                particles.smoke(c.x - hx * L, c.y - hy * L, 0.7 if big else 0.45, 1, 0.45, -hx * 2, -hy * 2, 0.7 if big else 0.45)

    def handle_places(fx_, fy_):
        r = places.update(fx_, fy_)
        first_call = not t_places["seen"]
        t_places["seen"] = True
        if r and not first_call:                            # the starting neighbourhood is not called out
            hud.set_place(r[0], r[1], 5.0)
            say(places.cur, fx_, fy_, TXT("main.0036"), True)      # spoken: just the name, the line stays on screen

    t_places = {"seen": False}
    amb_state = {"next": 8.0, "dens": 0.3}

    def density_at(x, y):
        """0 (open land) .. 1 (dense old-town blocks): buildings in this and the neighbouring chunks."""
        S_ = world.chunk
        cx, cy = int(x // S_), int(y // S_)
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                ch = world.chunks.get((cx + dx, cy + dy))
                if ch:
                    n += len(ch["b"])
        return max(0.0, min(1.0, n / 450.0))

    try:
        bio = soundlib.Biomes(world)                                 # v2.1: trees / parks / water around the listener
    except Exception as e_:  # noqa: BLE001
        print("[sound] no biome map:", e_)
        bio = None
    sx = {"env": {}, "chk": 0.0, "next": 6.0, "pass": {}, "wnext": 3.0, "swim": 0.0, "hour": -1, "place": "", "h0": None, "cpr": 0.0}
    # (weight, key, where it comes from): `where` picks a spot of that biome near the listener
    def wildlife(fx_, fy_, dn, dk):
        e, h = sx["env"], sim.clock.hour
        night, dawn = dk > 0.6, 4.5 <= h < 8.0
        wat, tre, par = min(1.0, e.get("water", 0) * 4), min(1.0, e.get("tree", 0) * 3), min(1.0, (e.get("park", 0) + e.get("tree", 0)) * 2)
        town, open_ = dn, 1.0 - dn
        if night:
            o = [(1.5 * tre, "bird_owl", "tree"), (0.8 * tre, "bird_owl_little", "tree"), (1.2 * par, "bird_nightingale", "park"), (1.5 * wat, "frog_croak", "water"),
                 (0.6 * town, "dog_pack_distant", None), (0.5 * town, "cat_fight", None), (0.6 * town, "cat_meow", None), (0.4, "dog_howl", None),
                 (0.5 * open_, "siren_distant", None),
                 (0.3 * town, "tv_apartment", None), (0.3 * town, "window_open", None), (0.3 * town, "door_slam", None), (0.2 * town, "rat_squeak", None),
                 (0.15, "fireworks_distant", None), (0.15 * open_, "wind_gust", None)]
        else:
            o = [(2.5 * wat, "bird_duck_flock", "water"), (2.0 * wat, "bird_duck", "water"), (0.8 * wat, "bird_goose", "water"), (0.5 * wat, "bird_heron", "water"),
                 (0.7 * wat, "bird_duck_takeoff", "water"), (0.3 * wat, "bird_swan", "water"), (0.4 * wat, "bird_seagull", "water"),
                 (2.0 * tre + 0.3, "bird_songbird_day", "tree"), (1.0 * tre, "bird_cuckoo", "tree"), (1.0 * tre, "bird_woodpecker", "tree"), (0.8 * tre, "bird_jay", "tree"),
                 (1.5 * par + 0.4, "bird_crow", "park"), (0.7 * par, "bird_crow_flock", "park"), (0.8 * par + 0.2, "bird_magpie", "park"), (1.4 * par + 0.5, "bird_dove", "park"),
                 (1.0 * par + 0.4, "bird_pigeon", "park"), (0.6 * par + 0.3, "bird_pigeon_flock_takeoff", "park"), (1.2 * par + 0.4, "bird_sparrow", "park"),
                 (0.8 * town, "bird_swallow", None), (0.5 * town if 17 <= h < 20.5 else 0.0, "bird_swift", None), (0.3 * open_, "bird_hawk", None),
                 (0.4 * town, "dog_small", None), (0.4 * town, "dog_big", None), (0.2 * town, "dog_growl", None), (0.4 * town, "cat_meow", None),
                 (1.5 * open_ if (dawn and open_ > 0.4) else 0.0, "bird_rooster", None), (0.5 * open_, "bird_hen", None), (0.4 * open_ * tre, "cow_bell", "tree"),
                 (0.3 * open_, "sheep_bleat", None), (0.2 * open_, "donkey", None), (0.15 * par, "bee_buzz", "park")]
            if dawn:
                o += [(3.0 * par + 0.6, "bird_blackbird", "park"), (2.0 * par, "bird_songbird_day", "tree")]
            o += [(0.5 * town, "kids_laugh", None), (0.3 * town, "coughing", None), (0.2 * town, "sneeze", None), (0.4 * town, "scooter_bell", None),
                  (0.4 * town, "bicycle_pass", None), (0.4 * town, "window_open", None), (0.4 * town if 8 <= h < 12 else 0.0, "shutter_roll", None),
                  (0.4 * town, "door_slam", None), (0.3 * town, "door_knock", None), (0.3 * town, "laundry_flap", None), (0.2 * town, "baby_cry", None),
                  (0.3 * town if 5 <= h < 10 else 0.0, "garbage_truck", None), (0.3 * town if 5 <= h < 10 else 0.0, "sweeper_machine", None),
                  (0.2 * town, "clap_hands", None), (0.2 * town, "glass_bottle", None), (0.2 * town, "bin_clang", None), (0.3 * par, "whistle_ref", "park"),
                  (0.15 * par, "crowd_football_roar", "park"), (0.3 * par, "crowd_laugh", "park"), (0.1 * par, "crowd_cheer", "park"), (0.1 * par, "crowd_applause", "park"),
                  (0.3 * tre, "bird_tit", "tree"), (0.2 * open_, "bird_hoopoe", None), (0.3 * open_, "bird_stork_clatter", None), (0.4 * par, "bird_wings_flap", "park"),
                  (0.15 * open_, "horse_neigh", None), (0.1 * town, "fly_buzz", None), (0.25 * open_, "wind_gust", None), (0.15 * open_, "train_horn_distant", None)]
        o = [q for q in o if q[0] > 0.01 and aud.has_lib(q[1])]
        if not o:
            return
        r_ = rng.uniform(0, sum(q[0] for q in o))
        for w_, key, where in o:
            r_ -= w_
            if r_ <= 0:
                break
        pt = bio.find(fx_, fy_, where, rng, 80.0) if (bio and where) else None
        if pt is None:
            if where:
                return                                              # nowhere of that kind around: say nothing rather than a duck in a street
            a_, d_ = rng.uniform(0, 6.283), rng.uniform(20, 70)
            pt = (fx_ + d_ * math.cos(a_), fy_ + d_ * math.sin(a_))
        aud.at(key, pt[0], pt[1], rng.uniform(0.45, 0.8), 1.0, "ambient", 110.0, 10.0)

    def steps_and_passby(fx_, fy_):
        """Footsteps of the player on foot (surface by what is under the feet) and a whoosh for traffic passing close by."""
        wk = sim.walker
        if sim.mode != "car":
            v = math.hypot(wk.vx, wk.vy)
            run_ = wk.speed > 6.0                                   # the same switch render.py uses for the run cycle
            n_ = int(wk.anim * 2.0 / (5.2 if run_ else 3.0))        # a foot lands every 4 of the 8 gait phases (render._gait)
            fresh = n_ != sx.get("stepn", n_)
            sx["stepn"] = n_
            air = wk.z > 0.05 or wk.duck_t > 0.0                    # no feet on the ground: jumping, or crawling under a vehicle
            landed = sx.get("air", False) and not air and wk.z < 0.3
            sx["air"] = air
            if not air and (landed or (v > 0.6 and wk.moving and fresh)):    # a jump ends with one step
                sf = world.surface(wk.x, wk.y)
                if world.wet(wk.x, wk.y, wk.az):
                    k_ = "puddle_step"
                elif sf == 2:
                    k_ = "step_wood"
                elif sf == 3 or sx["env"].get("park", 0) + sx["env"].get("tree", 0) < 0.25:
                    k_ = "step_run_asphalt" if run_ else "step_asphalt"
                else:
                    k_ = "step_grass" if sx["env"].get("park", 0) + sx["env"].get("tree", 0) > 0.5 else "step_dirt"
                if not aud.lib.get(k_):                      # synthesized fallback: three variants so no two steps in a row are identical
                    k_ += rng.choice(("", "_b", "_c"))
                aud.play(k_, 0.45 if run_ else 0.3, rng.uniform(0.9, 1.1), "sfx", rng.uniform(0.46, 0.54))
            if v > 0.6 and world.wet(wk.x, wk.y, wk.az) and t_game > sx["swim"]:
                sx["swim"] = t_game + 3.0
                aud.play("swim_stroke", 0.5, 1.0, "sfx")
        for c in sim.traffic.cars:
            if c.v > 3 and abs(c.x - fx_) < 14 and abs(c.y - fy_) < 14 and math.hypot(c.x - fx_, c.y - fy_) < 14 and sx["pass"].get(id(c), -9) < t_game - 9:
                sx["pass"][id(c)] = t_game
                prof = vehicles.ENGINE_SOUND[c.kind]
                aud.at("truck_passby" if prof == "engine_truck" else ("car_passby_fast" if c.v > 9 else "car_passby_slow"), c.x, c.y, 0.7, 1.0, "engine", 40.0, 6.0)
        if len(sx["pass"]) > 400:
            sx["pass"] = {k_: v_ for k_, v_ in sx["pass"].items() if v_ > t_game - 9}

    seeds = {"n": 0}
    eng_state = {}
    eng_gear = {}

    def car_seed(b):
        """A number that stays with this one car (the same object, so also after you leave it and get back in): picks its engine recording and pitch."""
        s_ = seeds.get(id(b))
        if s_ is None:
            seeds["n"] += 1
            s_ = seeds[id(b)] = zlib.crc32(f"{b.kind}/{getattr(b, 'color', 0)}/{seeds['n']}".encode()) % 100000
        return s_

    def engine_pitch(b, nm, fr, thr):
        """Revs follow the speed through five gears (rising, drop at each shift), a little higher under throttle, smoothed so shifts glide;
        every car gets its own base pitch, an electric motor just whines up with speed."""
        base = 1.0 + ((car_seed(b) // 7) % 13 - 6) * 0.012
        if nm == "engine_ev":
            tgt = 0.6 + 1.5 * fr
        else:
            g = min(4, int(fr * 5.0))
            rpm = 0.3 + 0.7 * min(1.0, fr * 5.0 - g) if g > 0 else 0.25 + 0.75 * min(1.0, fr * 5.0)
            tgt = 0.55 + 1.15 * rpm + 0.25 * thr - (0.1 if thr < 0.05 and fr > 0.1 else 0.0)        # throttle lift drops the revs (engine braking)
            if fr < 0.03:
                tgt = 0.55 + 0.02 * math.sin(time.time() * 54) + 0.015 * math.sin(time.time() * 138)           # uneven idle
            if g != eng_gear.get(id(b), g):
                tgt -= 0.15                                                                           # revs fall at each gear change
            eng_gear[id(b)] = g
        st = eng_state.get(id(b), tgt)
        st += (tgt - st) * (0.25 if tgt > st else 0.08)                                              # revs climb faster than they fall
        eng_state[id(b)] = st
        if len(eng_state) > 200:
            eng_state.clear()
            eng_gear.clear()
        return st * base

    def doppler(b, lx, ly):
        """Pitch shift of a moving source: higher while it comes towards you, lower once it passes."""
        dx, dy = b.x - lx, b.y - ly
        d_ = math.hypot(dx, dy) or 1.0
        vx_, vy_ = (b.vx, b.vy) if hasattr(b, "vx") else (b.v * math.cos(b.h), b.v * math.sin(b.h))
        vr = (vx_ * dx + vy_ * dy) / d_
        return max(0.85, min(1.15, 343.0 / (343.0 + vr)))

    def pan_of(x, lx, d):
        return 0.5 + 0.45 * max(-1.0, min(1.0, (x - lx) / max(d, 12.0)))

    def handle_audio(fx_, fy_):
        if not aud.ok or aud.muted:
            return
        aud.listener(fx_, fy_)
        aud.update()
        aud.set_zoom(max(0.0, min(1.0, (math.log(max(ppm, 1.0)) - math.log(3.0)) / (math.log(40.0) - math.log(3.0)))))        # camera height -> how much street / how much city bed
        tf = min(1.5, sim.clock.traffic) / 1.5
        if sim.mode == "car":
            c = sim.car
            fr = min(1.0, c.speed / vehicles.PERF[c.kind][0])
            prof = vehicles.ENGINE_SOUND[c.kind]
            for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev"):
                if nm == prof:                                       # this very car always uses the same recording, however often you leave and re-enter it
                    thr_ = abs(inp_last.get("throttle", 0))
                    aud.loop(nm, 0.15 + 0.35 * thr_ + 0.1 * fr, engine_pitch(c, nm, fr, thr_), "engine", 0.5, car_seed(c))
                else:
                    aud.loop(nm, 0.0, 1.0, "engine")
            aud.loop("screech", 0.35 if (c.slip > 3.0 and c.speed > 4) else 0.0, 0.9 + min(0.3, c.slip * 0.03), "sfx")
            hard_brake = inp_last.get("throttle", 0) < -0.5 and c.speed > 6
            aud.loop("screech", 0.12 if hard_brake else 0.0, 1.3, "sfx") if not (c.slip > 3.0 and c.speed > 4) else None   # brake squeal
            on_road = world.surface(c.x, c.y) in (2, 3)
            aud.loop("tyre_roll_asphalt", min(0.45, c.speed / 35.0) if on_road and c.speed > 2 else 0.0, 0.8 + c.speed / 60.0, "sfx")
            aud.loop("tyre_gravel", min(0.45, c.speed / 25.0) if not on_road and c.speed > 2 else 0.0, 0.8 + c.speed / 60.0, "sfx")
        else:
            for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev", "screech", "tyre_roll_asphalt", "tyre_gravel"):
                aud.loop(nm, 0.0)
        near_c, nd = None, 45.0                                  # engine hum of the closest moving traffic car (quiet, fades with distance)
        for c in sim.traffic.cars:
            if c.v > 0.5 and abs(c.x - fx_) < nd and abs(c.y - fy_) < nd:
                d_ = math.hypot(c.x - fx_, c.y - fy_)
                if d_ < nd:
                    near_c, nd = c, d_
        for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev"):
            if near_c is not None and vehicles.ENGINE_SOUND[near_c.kind] == nm:
                fr_ = min(1.0, near_c.v / max(1.0, vehicles.PERF[near_c.kind][0]))
                k_ = (1.0 - nd / 45.0) ** 2
                dop_ = doppler(near_c, fx_, fy_)
                aud.loop("ai_" + nm, 0.32 * k_ * (0.5 + 0.5 * fr_), engine_pitch(near_c, nm, fr_, 0.6) * dop_, "engine", pan_of(near_c.x, fx_, nd), car_seed(near_c))
            else:
                aud.loop("ai_" + nm, 0.0, 1.0, "engine")
        best, near_v = {}, {}
        for c in sim.traffic.cars:
            if c.kind in vehicles.SIREN_SOUND and c.v > 3:
                best[c.kind] = min(best.get(c.kind, 1e9), math.hypot(c.x - fx_, c.y - fy_))
                near_v[c.kind] = c if math.hypot(c.x - fx_, c.y - fy_) <= best[c.kind] else near_v.get(c.kind, c)
        for b in sim.bodies:
            if b.kind in vehicles.SIREN_SOUND and getattr(b, "siren", False) and b.alive:
                best[b.kind] = min(best.get(b.kind, 1e9), math.hypot(b.x - fx_, b.y - fy_))
                near_v[b.kind] = b if math.hypot(b.x - fx_, b.y - fy_) <= best[b.kind] else near_v.get(b.kind, b)
        for k, nm in vehicles.SIREN_SOUND.items():
            aud.loop(nm, max(0.0, 1.0 - best.get(k, 1e9) / 150.0) * 0.55, doppler(near_v[k], fx_, fy_) if k in near_v else 1.0, "sfx", pan_of(near_v[k].x, fx_, best[k]) if k in near_v else 0.5)
        spraying = any(j.kind == "fire" and j.state == "work" and j.work_t > 3.0 and math.hypot(j.x - fx_, j.y - fy_) < 60 for j in sim.services.jobs)
        aud.loop("spray", 0.4 if spraying else 0.0, 1.0, "sfx")
        aud.loop("construction", 0.55 * max(0.0, 1.0 - sim.works.nearest(fx_, fy_) / works_mod.HEAR) ** 1.5, 1.0, "ambient")
        dk = sim.clock.dark
        amb_state["dens"] += (density_at(fx_, fy_) - amb_state["dens"]) * 0.02
        dn = amb_state["dens"]
        near_peds = sum(1 for p in sim.peds.list if p.mode == "walk" and abs(p.x - fx_) < 40 and abs(p.y - fy_) < 40)
        aud.loop("city", 0.1 + 0.3 * dn * (0.4 + 0.6 * tf))
        aud.loop("traffic", 0.45 * dn * tf)
        aud.loop("crowd", min(0.5, near_peds * 0.03 + 0.25 * dn * sim.clock.peds / 1.5) * (1.0 - 0.6 * dk))
        aud.loop("wind", 0.28 * (1.0 - dn))
        if bio is not None and t_game >= sx["chk"]:
            sx["chk"] = t_game + 0.25
            pl_ = places.where(fx_, fy_)
            sx["place"] = (pl_ or "").lower()
            for k_, v_ in bio.at(fx_, fy_).items():
                sx["env"][k_] = sx["env"].get(k_, 0.0) + (v_ - sx["env"].get(k_, 0.0)) * 0.25
        e_ = sx["env"]
        green = min(1.0, (e_["park"] + e_["tree"]) * 2.5)
        day = max(0.0, 1.0 - dk * 1.6)
        aud.loop("birds", day * (0.5 * (1.0 - 0.7 * dn) + 0.3 * green))
        aud.loop("amb_park_day", 0.5 * day * min(1.0, e_["park"] * 3) * (1.0 - 0.5 * dn))
        aud.loop("amb_forest_day", 0.55 * day * min(1.0, e_["tree"] * 3))
        aud.loop("amb_forest_night", 0.5 * dk * min(1.0, e_["tree"] * 3))
        aud.loop("amb_dawn_chorus", 0.5 * green * (1.0 if 4.5 <= sim.clock.hour < 7.5 else 0.0))
        aud.loop("amb_river_vardar", 0.55 * min(1.0, e_["water"] * 5))
        aud.loop("amb_river_ducks", 0.45 * day * min(1.0, e_["water"] * 4))
        aud.loop("amb_street_night", 0.4 * dk * dn)
        aud.loop("amb_cafe_terrace", 0.4 * day * min(1.0, near_peds / 8.0) * dn)
        aud.loop("amb_bridge_traffic", 0.5 * (1.0 if world.surface(fx_, fy_) == 2 else 0.0) * tf)
        aud.loop("frog_chorus", 0.35 * dk * min(1.0, e_["water"] * 4))
        aud.loop("amb_industrial", 0.5 * min(1.0, e_.get("ind", 0) * 4))
        aud.loop("amb_square_day", 0.5 * day * min(1.0, e_.get("plaza", 0) * 5))
        aud.loop("amb_pigeons_square", 0.4 * day * min(1.0, e_.get("plaza", 0) * 5))
        aud.loop("amb_city_far", 0.55 * (1.0 - aud.zoom) ** 1.2 * (0.4 + 0.6 * dn))
        aud.loop("amb_wind_high", 0.5 * (1.0 - aud.zoom) ** 1.5)
        aud.loop("amb_playground", 0.5 * day * min(1.0, e_.get("play", 0) * 5))
        aud.loop("amb_football_pitch", 0.4 * day * min(1.0, e_.get("pitch", 0) * 5))
        aud.loop("amb_lake_shore", 0.5 * min(1.0, e_.get("lake", 0) * 5))
        aud.loop("amb_creek", 0.4 * min(1.0, e_.get("creek", 0) * 6))
        aud.loop("amb_railway", 0.45 * min(1.0, e_.get("rail", 0) * 8))
        aud.loop("amb_wind_trees", 0.4 * min(1.0, e_["tree"] * 3) * (1.0 - dn))
        aud.loop("amb_meadow_day", 0.4 * day * (1.0 - dn) * (1.0 if e_["park"] > 0.15 and e_["tree"] < 0.1 else 0.0))
        if sx["h0"] is None:
            sx["h0"] = world.ground_y(fx_, fy_)
        aud.loop("amb_hill_wind", 0.5 * max(0.0, min(1.0, (world.ground_y(fx_, fy_) - sx["h0"] - 40.0) / 80.0)))
        slow_n = sum(1 for c in sim.traffic.cars if c.v < 1.5 and abs(c.x - fx_) < 50 and abs(c.y - fy_) < 50)
        aud.loop("amb_traffic_jam", 0.55 * min(1.0, max(0.0, slow_n - 3) / 5.0))
        aud.loop("amb_street_quiet", 0.35 * day * (1.0 if 0.25 < dn < 0.8 and tf < 0.5 else 0.0))
        aud.loop("amb_courtyard", 0.3 * day * max(0.0, dn - 0.6) * 2.5)
        aud.loop("street_lamp_buzz", 0.2 * dk * dn)
        aud.loop("neon_buzz", 0.2 * dk * (1.0 if dn > 0.7 else 0.0))
        hz_ = zlib.crc32(f"{int(fx_ // 300)},{int(fy_ // 300)}".encode()) % 13               # a few city blocks get their own event: a party, a market, a wedding ...
        hr_ = sim.clock.hour
        aud.loop("amb_night_party", 0.3 * dk * (1.0 if hz_ == 1 and dn > 0.4 else 0.0))
        aud.loop("amb_market_morning", 0.4 * (1.0 if hz_ in (2, 3) and 6 <= hr_ < 13 and dn > 0.4 else 0.0))
        aud.loop("amb_wedding_distant", 0.35 * (1.0 if hz_ == 4 and 14 <= hr_ < 23 else 0.0))
        aud.loop("street_musician_accordion", 0.3 * day * (1.0 if hz_ == 5 and dn > 0.5 else 0.0))
        aud.loop("power_transformer_hum", 0.25 * (1.0 if hz_ == 6 else 0.0))
        aud.loop("amb_bazaar", 0.6 * day * (1.0 if "чаршија" in sx["place"] else 0.0))
        if int(hr_) != sx["hour"]:
            if sx["hour"] >= 0 and dn > 0.5:
                aud.play("clock_tower", 0.3, 1.0, "ambient")
            sx["hour"] = int(hr_)
        fire_d = min((math.hypot(b.x - fx_, b.y - fy_) for b in sim.bodies if b.burn > 0.5 and abs(b.x - fx_) < 70 and abs(b.y - fy_) < 70), default=99.0)
        aud.loop("fire_crackle", 0.6 * max(0.0, 1.0 - fire_d / 70.0), 1.0, "sfx")
        near_site = min(sim.works.sites, key=lambda s_: math.hypot(s_[0] - fx_, s_[1] - fy_), default=None) if sim.works.open() else None
        sd_ = math.hypot(near_site[0] - fx_, near_site[1] - fy_) if near_site else 1e9
        prox = max(0.0, 1.0 - sd_ / works_mod.HEAR)
        aud.loop("concrete_mixer", 0.5 * prox * prox, 1.0, "ambient")
        aud.loop("jackhammer", 0.5 * prox * prox * (1.0 if near_site and int(near_site[0] + near_site[1]) % 3 == 0 else 0.0), 1.0, "ambient")
        if near_site and t_game >= sx["wnext"] and sd_ < works_mod.HEAR:
            sx["wnext"] = t_game + rng.uniform(1.2, 4.0)
            aud.at(rng.choice(("hammer", "hammer", "hammer_steel", "drill", "metal_clank", "metal_clank", "angle_grinder", "shovel_gravel", "saw_wood",
                               "fence_rattle", "wheelbarrow", "tin_roof_bang", "truck_reverse_beep", "crane_hum")),
                   near_site[0] + rng.uniform(-8, 8), near_site[1] + rng.uniform(-8, 8), 0.7, 1.0, "ambient", works_mod.HEAR, 12.0)
        aud.loop("cicadas", 0.3 * day * (1.0 - dn) * min(1.0, 0.3 + green) * (1.0 if 5 <= (sim.clock.hour // 1) <= 19 else 0.0))
        steps_and_passby(fx_, fy_)
        sx["next"] -= 1 / 60.0
        if bio is not None and sx["next"] <= 0:
            sx["next"] = rng.uniform(2.5, 7.0) * (1.0 + 1.5 * dn)
            wildlife(fx_, fy_, dn, dk)
        aud.loop("crickets", 0.32 * max(0.0, dk * 1.4 - 0.3) * (1.0 - 0.5 * dn))
        amb_state["next"] -= 1 / 60.0
        if amb_state["next"] <= 0:
            amb_state["next"] = rng.uniform(14, 40)
            r_ = rng.random()
            if r_ < 0.3:
                aud.play("dog", 0.25 + 0.2 * (1 - dn), rng.uniform(0.8, 1.2), "ambient")
            elif r_ < 0.5 and dn > 0.3:
                aud.play("horn", 0.12, rng.uniform(0.8, 1.1), "ambient")
            elif r_ < 0.65:
                aud.play("bell", 0.25, rng.uniform(0.9, 1.1), "ambient")
            elif r_ < 0.68 and sim.clock.dark < 0.5:                # a distant siren now and then, not every minute
                aud.play("siren_police", 0.1, 1.0, "ambient")

    inp_last = {}

    # ------------------------------------------------------------------ main loop
    tp_idx = -1
    snap = False
    last_phase = None
    hitch_t0 = time.perf_counter()
    win_focus = True
    while not rl.window_should_close():
        dt_real = rl.get_frame_time()
        dt = 1 / 60 if a.test else min(dt_real, 0.05)
        if present_mod.pending_quit:                    # the exit button was pressed inside the frame buffer
            present_mod.pending_quit = False
            present_mod.off()
            if font.confirm_quit(True):
                break
        sw, sh = (int(v) for v in a.size.lower().split("x")) if a.size else settings_mod.RESOLUTIONS[cfg["res"]]
        present.activate(sw, sh)                        # the frame is drawn at the menu resolution and scaled to the window
        focused_now = bool(rl.is_window_focused())
        if focused_now != win_focus:
            win_focus = focused_now
            log(f"[window] {'focus gained' if focused_now else 'focus lost'} fullscreen={is_borderless()}")
        frame += 1
        t_game += dt
        # ------------------------------------------------ input
        enter_pressed = False
        if a.test:
            t = frame / 60.0
            thr = 1.0 if (frame // 400) % 2 == 0 else (-1.0 if frame % 400 > 330 else 0.0)
            inp = {"throttle": thr, "steer": 0.55 * math.sin(t * 0.7), "handbrake": (frame % 300) > 250, "horn": frame % 200 == 150,
                   "move": (0.5 * math.sin(t), 1.0), "run": frame % 120 > 60}
            if frame == 240:
                enter_pressed = True                       # step out
            if 245 < frame < 330:
                inp["move"] = (0.0, 0.0)
                inp["attack"] = frame % 14 == 0
                inp["jump"] = frame in (300, 322)
            if os.environ.get("SK242_TEST_BIRDS") and sim.walker is not None:      # one of each, right in front of the camera
                inp["move"], inp["run"] = (0.0, 0.0), False
                if frame == 60:
                    for k_, sp_ in enumerate(("pigeon", "crow", "pigeon", "crow", "pigeon", "crow")):
                        b_ = birds_mod.Bird(sim.walker.x + 3.0 + 1.6 * (k_ % 3), sim.walker.y - 3.0 + 3.0 * (k_ // 3), sp_, random.Random(k_))
                        b_.z = b_.gy = sim.w.ground_y(b_.x, b_.y)
                        b_.state, b_.t = "idle", 99.0
                        sim.birds.live.append(b_)
                sim.birds.spawn_t = 9.0
            if os.environ.get("SK242_TEST_DOGS") and sim.walker is not None:       # stand still beside the nearest stray and pet it
                inp["move"], inp["run"] = (0.0, 0.0), False
                if frame == 100:
                    wk_ = sim.walker
                    if not sim.dogs.live:                    # none spawned near here: put two beside the player
                        for k_ in range(2):
                            sim.dogs.live.append(dogs_mod.Dog(wk_.x + 3.0 + k_, wk_.y + 2.0 * k_, random.Random(k_), (wk_.x, wk_.y), ("test", k_, 0)))
                    q_ = min(sim.dogs.live, key=lambda q: (q.x - wk_.x) ** 2 + (q.y - wk_.y) ** 2)
                    wk_.x, wk_.y, wk_.h = q_.x - 1.0, q_.y, 0.0
                    q_.state, q_.t = "idle", 9.0
                if frame == 110:
                    sim.walker.atk_cd = 0.0
                    sim.attack()
            if frame == 30 and sim.mode == "car":          # emergency services: a dead pedestrian and a burning wreck
                from actors import Ped
                px_, py_ = sim.car.x, sim.car.y
                d_ = Ped()
                d_.x, d_.y, d_.mode, d_.t, d_.arch = px_ + 25, py_ + 3, "dead", 8.0, 0
                sim.peds.list.append(d_)
                wr = Body(px_ - 30, py_ + 8, 0.3, 1, 2)
                wr.health, wr.burn, wr.empty = 0.0, 1.0, True
                sim.bodies.append(wr)
            if frame == 2:                                 # decal check: a skid line and a blood blob next to the player
                fx_, fy_, _a, _b = sim.focus()
                streamer.add_decal(("l", fx_ - 6, fy_ + 3, fx_ + 6, fy_ + 4, 0.25, (8, 8, 10, 200)))
                streamer.add_decal(("d", fx_ + 3, fy_ + 6, 1.2, (150, 20, 24, 220)))
            if frame == 242 and sim.walker is not None and os.environ.get("SK242_TEST_WEAPON"):    # e.g. bat: check the swing
                sim.walker.weapon, sim.walker.ammo = os.environ["SK242_TEST_WEAPON"], 99
            if frame == 250 and sim.walker is not None:    # a volunteer for the fistfight
                from actors import Ped
                q_ = Ped()
                q_.x, q_.y, q_.h, q_.arch, q_.hp = sim.walker.x + 1.0 * math.cos(sim.walker.h), sim.walker.y + 1.0 * math.sin(sim.walker.h), 0.0, 0, 40.0
                q_.e, q_.mode, q_.t = 0, "rage", 999.0
                sim.peds.list.append(q_)
            if frame == 290 and sim.walker is not None and sim.kiosks:
                k_ = sim.kiosks[0]
                sim.walker.x, sim.walker.y = k_[0] + 1.6, k_[1]
                sim.walker.health = 40
            if frame == 292:
                inp["buy"] = 1
            if frame == 315 and sim.mode == "foot":
                sim.teleport(300.0, -200.0)
            if frame == 330 and sim.mode == "foot" and sim.traffic.cars:
                c = sim.traffic.cars[0]
                sim.walker.x, sim.walker.y = c.x + 2.0, c.y + 1.0
            if frame == 336:
                enter_pressed = True                       # hijack a traffic car
            if frame == 700 and sim.mode == "car":
                sim.car.health = 0                           # test: burn + explode
        else:
            down = rl.is_key_down
            inp = {
                "throttle": (down(rl.KEY_W) or down(rl.KEY_UP)) - (down(rl.KEY_S) or down(rl.KEY_DOWN)),
                "steer": (down(rl.KEY_D) or down(rl.KEY_RIGHT)) - (down(rl.KEY_A) or down(rl.KEY_LEFT)),
                "handbrake": down(rl.KEY_SPACE), "horn": rl.is_key_pressed(rl.KEY_H),
                "respawn": rl.is_key_pressed(rl.KEY_R),
                "move": (((down(rl.KEY_D) or down(rl.KEY_RIGHT)) - (down(rl.KEY_A) or down(rl.KEY_LEFT))),
                         ((down(rl.KEY_W) or down(rl.KEY_UP)) - (down(rl.KEY_S) or down(rl.KEY_DOWN)))),
                "run": down(rl.KEY_LEFT_SHIFT),
                "attack": down(rl.KEY_LEFT_CONTROL) or down(rl.KEY_RIGHT_CONTROL),
                "jump": rl.is_key_pressed(rl.KEY_SPACE),
                "buy": next((i for i, k in enumerate((rl.KEY_ONE, rl.KEY_TWO, rl.KEY_THREE, rl.KEY_FOUR)) if rl.is_key_pressed(k)), None),
            }
            if rl.is_key_pressed(rl.KEY_LEFT_BRACKET):
                sim.clock.shift(-1.0)
            if rl.is_key_pressed(rl.KEY_RIGHT_BRACKET):
                sim.clock.shift(1.0)
            if rl.is_key_pressed(rl.KEY_T):
                lst = places.list
                if lst:
                    step = -1 if (rl.is_key_down(rl.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KEY_RIGHT_SHIFT)) else 1
                    tp_idx = (tp_idx + step) % len(lst)
                    sim.teleport(lst[tp_idx][1], lst[tp_idx][2])
                    snap = True
            if rl.is_key_pressed(rl.KEY_N):
                aud.muted = not aud.muted
                if aud.muted:
                    for nm in list(aud._cur):
                        aud.loop(nm, 0.0)
            enter_pressed = rl.is_key_pressed(rl.KEY_F) or rl.is_key_pressed(rl.KEY_ENTER)
            if rl.is_key_pressed(rl.KEY_TAB) and (rl.is_key_down(rl.KEY_LEFT_ALT) or rl.is_key_down(rl.KEY_RIGHT_ALT)):
                log("[window] Alt+Tab reached the game (Windows did not switch) - minimising the window")
                rl.minimize_window()
            elif rl.is_key_pressed(rl.KEY_TAB) and sim.mode == "foot" and sim.walker is not None:   # Tab: next weapon
                import actors as _a
                wname = sim.walker.cycle()
                hud.set_banner(_a.WEAPONS[wname][0] if wname in _a.WEAPONS else TXT("main.0037"), 1.2)
            if rl.is_key_pressed(rl.KEY_M):
                show_map = not show_map
                aud.play("map_paper", 0.5)
            if rl.is_key_pressed(rl.KEY_F3):
                show_dbg = not show_dbg
            if rl.is_key_pressed(rl.KEY_F11):
                set_borderless(not is_borderless())
            if rl.is_key_pressed(rl.KEY_ESCAPE) or want_menu:
                want_menu = False
                if show_map:
                    show_map = False
                else:
                    rl.enable_cursor()
                    mouse_grab = False
                    res_ = menu_mod.run(cfg, apply_cfg, True, save_fn=lambda n_: savegame.save(sim, cfg, n_))
                    if res_ == "quit":
                        break
                    if res_ == "chars":
                        if menu_mod.pick_character(cfg, aud):
                            break
                        savegame.new_character(sim, cfg["lik"])
                        hud.set_banner(TXT("main.0038"), 3.0)
                    elif res_.startswith("load"):
                        d_ = savegame.read(int(res_[4:]))
                        if d_:
                            savegame.restore(sim, cfg, d_)
                            apply_cfg(cfg, True)
                            snap = True
                            hud.set_banner(TXT("main.0039"), 3.0)
            if rl.is_key_pressed(rl.KEY_L) or want_chars:                  # L: switch character without opening the menu
                want_chars = False
                if menu_mod.pick_character(cfg, aud):
                    break
                savegame.new_character(sim, cfg["lik"])
                hud.set_banner(TXT("main.0040"), 3.0)
            if rl.is_key_pressed(rl.KEY_R) and sim.mode == "car":
                p = world.nearest_drive_point(sim.car.x, sim.car.y)
                if p:
                    sim.car.x, sim.car.y, sim.car.h = p
                    sim.car.vx = sim.car.vy = 0.0
                    popups.add(TXT("main.0041"), p[0], p[1], 3, 2)
            user_zoom = max(0.35, min(2.4, user_zoom * (1.12 ** rl.get_mouse_wheel_move())))
        inp_last.clear()
        inp_last.update(inp)
        if show_map and not a.test:
            pick = hud.map_pick(sw, sh)
            if pick is not None:
                sim.teleport(pick[0], pick[1])
                show_map = False
                snap = True
        sf_due_ = False
        if a.test:
            pt_ = os.environ.get("SK242_TEST_POI")
            if pt_ and frame == int(pt_) and sim.walker is not None and pois.cells:
                q_ = next(iter(next(iter(pois.cells.values()))))
                sim.walker.x, sim.walker.y, sim.walker.az = q_[0] + 3.0, q_[1], None
            if pt_ and frame == int(pt_) + int(os.environ.get("SK242_TEST_POI_BUY", "3")):
                inp["buy"] = 0
        if sim.mode == "foot" and (rl.is_key_pressed(rl.KEY_P) or (a.test and frame == int(os.environ.get("SK242_TEST_SELFIE", "-1")))) and not pois.busy:
            if selfie.start(sim, characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][0],
                            lambda l_, x_, y_: say(l_, x_, y_, hero_who(), True)):
                pois.sup_until = t_game + selfie_mod.DUR + 4.0
        grab_ = cfg["debug_chase"] and (sim.walker is not None if sim.mode == "foot" else sim.mode == "car") and not selfie.active and not show_map and not a.test
        if grab_ != mouse_grab:                               # street view on foot: the mouse is captured and turns the avatar
            (rl.disable_cursor if grab_ else rl.enable_cursor)()
            mouse_grab = grab_
        if grab_ and sim.mode == "car":                      # the mouse steers like a wheel that slowly centres itself
            mouse_steer = max(-1.0, min(1.0, mouse_steer * max(0.0, 1.0 - 2.5 * dt) + rl.get_mouse_delta().x * 0.012 * cfg["mouse_sens"]))
            if not inp.get("steer"):
                inp["steer"] = mouse_steer
        elif grab_:
            if not inp.get("move", (0, 0))[0]:
                sim.walker.h += rl.get_mouse_delta().x * 0.003 * cfg["mouse_sens"]
            inp["attack"] = inp.get("attack") or rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT)
        busy_ = guard.run("poi", pois.update, dt, sim, t_game, inp.get("buy"), characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][0],
                          lambda l_, x_, y_: say(l_, x_, y_, hero_who(), True), popups) or selfie.active
        if busy_:                                            # inside a shop / posing: the controls are off
            inp["move"], inp["attack"], inp["buy"], inp["jump"] = (0, 0), False, None, False
            inp["throttle"] = inp["steer"] = 0
            enter_pressed = False
        if selfie.active:
            sf_due_ = selfie.advance(dt)
        if enter_pressed:
            if sim.mode == "car":
                sim.exit_car()
            else:
                guard.run("enter", sim.try_enter)
        # ------------------------------------------------ simulation
        if guard.run("sim", sim.update, dt, inp, 2) is None and "sim" in guard.disabled:
            hud.set_banner(TXT("main.0042"), 4)
        guard.run("events", handle_events)
        guard.run("effects", effects, dt)
        guard.run("exhaust", exhaust, dt)
        lights.update(dt)
        particles.update(dt)
        popups.update(dt)
        gains.update(dt)
        sim.money_pulse = gains.pulse
        hud.update(dt)
        shake *= math.exp(-6 * dt)
        tip_t -= dt
        if tip_t < 0:
            tip_t = 40.0
            fx0, fy0, _, _ = sim.focus()
            popups.add(rng.choice(slang.TIPS), fx0, fy0, 7.0, 6.0, (200, 230, 255), 20)
        # ------------------------------------------------ audio, speech, tooltips, clock banners
        fx, fy, fvx, fvy = sim.focus()
        guard.run("places", handle_places, fx, fy)
        guard.run("audio", handle_audio, fx, fy)
        if sim.mode == "car" and not a.test and not busy_:
            for k_, d_ in ((rl.KEY_E, 1), (rl.KEY_PERIOD, 1), (rl.KEY_Q, -1), (rl.KEY_COMMA, -1)):
                if rl.is_key_pressed(k_):
                    hud.set_banner(car_radio.step(d_), 2.0)
                    break
        hud.radio_line = car_radio.label() if sim.mode == "car" and car_radio.aud.ok else ""
        song = guard.run("radio", car_radio.update, dt, sim.mode == "car", cfg["vol_radio"])
        if song:
            hud.set_banner(TXT("main.0043") + song, 2.0)
        aud.cabin = sim.mode == "car"                            # inside a car: the world is muffled, your radio plays clearly
        guard.run("cabin", cabin_music.update, dt, sim.traffic.cars, fx, fy, not aud.muted and sim.mode != "car", cfg["vol_radio"])
        res = spk.poll()
        if res is not None:
            key, pcm, sr_ = res
            vol_, prio_, _t = pend_say.pop(key, (0.0, False, 0.0))
            if vol_ > 0 and (prio_ or not aud.speaking()):      # stale or overlapping lines are dropped
                aud.speak(pcm, vol_, sr_, muffle=aud.cabin and not prio_)
        aud.reap()
        ph_ = sim.clock.phase()
        if ph_ != last_phase:
            if last_phase is not None:
                if ph_ in ("rush_am", "rush_pm"):
                    hud.set_banner(rng.choice(slang.RUSH), 3.0)
                elif ph_ == "night":
                    hud.set_banner(rng.choice(slang.NIGHT), 3.0)
            last_phase = ph_
        # ------------------------------------------------ camera
        speed = math.hypot(fvx, fvy)
        if sim.mode == "car":
            tgt_ppm = 1.18 * (10.5 - 4.6 * min(speed / 32.0, 1.0)) * user_zoom * cfg["zoom_car"]
        else:
            tgt_ppm = 26.0 * user_zoom * cfg["zoom_walk"]
        tgt_ppm = max(tgt_ppm, (0.97 if sim.mode == "car" else 3.64) / 0.6)     # the farthest zoom-out is 60% of what it was (ppm floor = old floor / 0.6)
        ppm += (tgt_ppm - ppm) * min(1.0, 2.5 * dt)
        sim.view_r = max(150.0, min(300.0, 1250.0 / max(ppm, 1.0) + 60.0))      # parked cars are placed this far round the camera
        k = min(1.0, 6.0 * dt)
        if snap:                                   # teleported: jump the camera instead of flying across the city
            snap = False
            cam_x, cam_y, k = fx, fy, 1.0
            cam_h = None
        cam_x += (fx + fvx * 0.45 - cam_x) * k
        cam_y += (fy + fvy * 0.45 - cam_y) * k
        if sim.mode == "car":
            foc_h = sim.car.az if sim.car.az is not None else world.ground_y(fx, fy)
        else:
            foc_h = sim.walker.az if (sim.walker is not None and sim.walker.az is not None) else world.ground_y(fx, fy)
        cam_h = foc_h if cam_h is None else cam_h + (foc_h - cam_h) * min(1.0, 4.0 * dt)
        jx, jy = random.uniform(-shake, shake) * cfg["shake"], random.uniform(-shake, shake) * cfg["shake"]
        cam, Hc, rect = renderer.camera(cam_x + jx, cam_y + jy, ppm, sw, sh, cam_h)
        sf_on = selfie.active and sim.walker is not None
        ch_on = cfg["debug_chase"] and not sf_on and (sim.walker if sim.mode != "car" else sim.car) is not None
        if sf_on:
            cam, rect = selfie.camera(sim, world)
            Hc = 0.0
        elif ch_on:
            cam, rect = selfie.chase(sim, world, dt)
            Hc = 0.0
        sf_on = sf_on or ch_on
        popups.street = ch_on
        # ------------------------------------------------ streaming
        lod = ppm >= LOD_PPM
        lite_ = ()
        if ch_on:                                  # street view: chunks out to 2.25x the full-detail radius, the far ring at low quality
            o_ = sim.car if sim.mode == "car" else sim.walker
            far_, near_ = selfie_mod.VIEW * 2.25, selfie_mod.VIEW
            wanted = [k_ for k_ in want_list(o_.x, o_.y, 1.0, 2 * far_, 2 * far_, 0)]
            def gap_(k_):                          # distance from the avatar to the nearest point of the chunk
                return math.hypot(max(k_[0] * S - o_.x, 0, o_.x - (k_[0] + 1) * S), max(k_[1] * S - o_.y, 0, o_.y - (k_[1] + 1) * S))
            wanted = [k_ for k_ in wanted if gap_(k_) < far_]
            lite_ = {k_ for k_ in wanted if gap_(k_) >= near_}
            lod = True
        else:
            wanted = want_list(cam_x, cam_y, ppm, sw, sh, 70) if lod else []
        guard.run("stream", streamer.update, wanted, lod, 8.0, lite_)
        worst_bake = max(worst_bake, streamer.bake_ms)
        # ------------------------------------------------ draw
        rl.begin_drawing()
        present.begin()
        try:
            rl.clear_background(rl.Color(26, 28, 32, 255))
            if sf_on:
                sf_hy = selfie.sky(cam, sim.clock.dark, sim.clock.hour, t_game, sw, sh)
                guard.run("render", renderer.draw, cam, Hc, rect, 26.0, sim, particles, t_game, True, 0.1, True)
                if not ch_on:                          # the street view has the horizon near the top: the band read as a veil
                    selfie.haze(sf_hy, sim.clock.dark, sw)
            else:
                guard.run("render", renderer.draw, cam, Hc, rect, ppm, sim, particles, t_game)
            if lod:
                guard.run("night", night.draw, cam, rect, ppm, sim, sim.clock.dark, t_game, sw, sh, sf_on)
            if cfg.get("smog", 1) and not sf_on:
                guard.run("smog", smog.draw, cam, cam_x, cam_y, ppm, sw, sh, sim.clock.hour, t_game,
                          min(1.0, sim.clock.traffic * (0.5 + 0.5 * cfg.get("pollution", 1.0))), cfg.get("smog_level", 1.0), world.ground_y(cam_x, cam_y))
            if cfg.get("smog", 1) and not sf_on:
                guard.run("dust", sim.works.draw_dust, cam, cam_x, cam_y, sw, sh, t_game, world.ground_y(cam_x, cam_y), ppm)
            guard.run("popups", popups.draw, cam, (sim.car.x, sim.car.y) if ch_on and sim.mode == "car" else None)
            guard.run("gains", gains.draw, cam, (sw - 230, 26))
            if lod and ppm > 4.0 and flags["labels"] and not sf_on:
                guard.run("labels", draw_labels, labels, cam, fx, fy, sw, sh)
            prompt = ""
            if sim.mode == "foot" and sim.walker and sim.walker.health > 0:
                for b in sim.bodies:
                    if b.alive and math.hypot(b.x - fx, b.y - fy) < 4.0:
                        prompt = (TXT("main.0044") + f'{b.name}') + (TXT("main.0045") if b.parked_idx is not None else "")
                        break
                else:
                    for c in sim.traffic.cars:
                        if math.hypot(c.x - fx, c.y - fy) < 3.4:
                            prompt = (TXT("main.0046") + f'{vehicles.NAMES[c.kind]})')
                            break
            elif sim.mode == "car" and sim.car.speed < 2.0:
                prompt = TXT("main.0047")
            if sim.stations.prompt and sim.mode == "car":
                prompt = sim.stations.prompt
            if sim.mode == "foot" and sim.walker and sim.walker.health <= 0 and sim.walker.cause != "fight":
                prompt = TXT("main.0048")
            pending = sum(1 for k_ in wanted[:30] if k_ not in streamer.ground)
            if sf_on and selfie.active:
                selfie.overlay(sw, sh)
                if sf_due_:
                    selfie.take()
            else:
                pois.draw(sim, sw, sh)
            if not selfie.active:                       # the chase view keeps the HUD, so M opens the map there too
                guard.run("hud", hud.draw, sim, sw, sh, show_map, prompt, (len(wanted[:30]) - pending, len(wanted[:30])) if wanted else None, ppm)
            vs_ = spk.status()
            if vs_:
                font.draw_text(TXT("main.0049") + vs_, 16, 62, 16, rl.Color(255, 220, 150, 220))
            if not a.test:
                font.draw_text(TXT("main.0050"),
                             16, sh - 30 if False else 36, 16, rl.Color(255, 255, 255, 170))
            if show_dbg:
                font.draw_text(f"{rl.get_fps()} fps  {dt_real * 1000:.1f} ms | ground {renderer.drawn_chunks}/{len(streamer.ground)} "
                             f"meshes {renderer.drawn_meshes}/{len(streamer.meshes)} baked {streamer.baked} (last {streamer.bake_ms:.0f} ms) "
                             f"| cars {len(sim.traffic.cars)} bodies {len(sim.bodies)} peds {len(sim.peds.list)} "
                             f"parts {len(particles.p)} | ppm {ppm:.1f} err {sum(guard.errors.values())}", 12, 10, 16, rl.Color(255, 255, 255, 255))
            if not a.test:                                     # mouse buttons: options menu and exit, always on screen
                bx_ = sw - 300 - 112 * 3
                if font.button(TXT("main.0051"), bx_, 10, 104, 34):
                    want_chars = True
                if font.button(TXT("main.0052"), bx_ + 112, 10, 104, 34):
                    want_menu = True
                font.exit_button(bx_ + 224, 10)
        finally:
            present.end(cfg["scale"] == 0, cfg["aa"] >= 2)
            t_sw = time.perf_counter()
            rl.end_drawing()
        ft_hist.append(dt_real)
        t_now = time.perf_counter()
        if t_now - hitch_t0 > 0.1 and hitch_n < 300 and not a.test:
            hitch_n += 1
            parts = sorted(guard.ms.items(), key=lambda kv: -kv[1])[:6] + [("gc", gc_t[1] * 1000), ("swap", (t_now - t_sw) * 1000)]
            log(f"[hitch] {(t_now - hitch_t0) * 1000:.0f} ms ({sim.mode}): " + ", ".join(f"{k} {v:.0f}" for k, v in parts if v >= 1.0))
        hitch_t0 = t_now
        guard.ms.clear()
        gc_t[1] = 0.0
        if not a.test and len(ft_hist) >= 60:              # quality scaler: a slow PC thins the crowds a little instead of stuttering
            avg_ = sum(ft_hist[-60:]) / 60.0
            if avg_ > 1 / 40:
                auto_q = max(0.6, auto_q - 0.002)
            elif avg_ < 1 / 55:
                auto_q = min(1.0, auto_q + 0.002)
            sim.dens_traffic, sim.dens_peds = cfg.traffic_mult * auto_q, cfg.ped_mult * auto_q
        boom_ = int(os.environ.get("SK242_TEST_BOOM", "-1"))
        if a.test and boom_ > 0 and frame == boom_:       # test hook: blow something up in front of the camera, shots follow
            particles.explosion(cam_x, cam_y)
            for _ in range(6):
                particles.fire(cam_x + rng.uniform(-2, 2), cam_y + rng.uniform(-2, 2), 2, 0.9, 1.0)
        if a.test and a.shot and (frame in (5, 90, 200, 258, 266, 274, 306, 345, 800, 900, 930, a.test - 1) or (boom_ > 0 and frame - boom_ in (4, 12, 24, 45, 90))):
            img = rl.load_image_from_screen()
            rl.export_image(img, f"{a.shot}_{frame}.png")
            rl.unload_image(img)
        if a.test and frame >= a.test:
            break
    spk.dead = True
    if aud.dry:
        for (nm_, src_), n_ in sorted(aud.stats.items()):
            print(f"[sound-dry] {nm_:28s} {src_:22s} x{n_}")
    if aud.ok:
        cabin_music.close()
        car_radio.close()
        for p_ in RADIO_PROC:
            if p_.poll() is None:
                p_.kill()
        aud.close()
    if a.test:
        avg = sum(ft_hist) / len(ft_hist) * 1000
        print(f"[test] frames={frame} avg_frame={avg:.2f}ms worst={max(ft_hist) * 1000:.1f}ms ground={len(streamer.ground)} "
              f"meshes={len(streamer.meshes)} baked={streamer.baked} cars={len(sim.traffic.cars)} bodies={len(sim.bodies)} "
              f"peds={len(sim.peds.list)} jobs={[(j.kind, j.state) for j in sim.services.jobs]} stats={sim.stats} errors={guard.errors} stream_errors={streamer.errors}")
        from collections import Counter
        print("[test] birds", dict(Counter((b.species, b.state) for b in sim.birds.live)))
        print(f"[test] mode={sim.mode} focus={sim.focus()[:2]} health={sim.car.health:.0f} dents={len(sim.car.dents)}")
        import collections as _c
        print(f"[test] ped modes {dict(_c.Counter(p.mode for p in sim.peds.list))} queues {sum(len(q) for q in sim.transit.queue.values())} "
              f"buses {len(sim.transit.buses)} on/off {sim.transit.served} riding {sim.riding is not None} broken {len(getattr(world, 'broken', []))}")
    rl.close_window()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - last line of defence: log, show, exit non-zero
        tb = traceback.format_exc()
        log("[fatal]\n" + tb)
        try:
            if rl.is_window_ready():
                fatal_screen(TXT("main.0053"), tb.strip().splitlines()[-8:] + ["", (TXT("main.0054") + f'{LOG_FILE}')], 0)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
