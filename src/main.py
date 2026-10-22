"""Skopje GTA - top-down 3D driving sandbox built from OpenStreetMap data.  Start via run.bat."""
import argparse
import json
import math
import os
import queue
import random
import subprocess
import sys
import threading
import time
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
import slang         # noqa: E402
import vehicles      # noqa: E402
from actors import Body, Sim   # noqa: E402
from bake import PPM, Streamer, bake_overview   # noqa: E402
import fx as fx_mod   # noqa: E402
from fx import Particles, Popups   # noqa: E402
from night import Night   # noqa: E402
from places import Places   # noqa: E402
from speech import SpeechWorker   # noqa: E402
import smog   # noqa: E402
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

    def run(self, name, fn, *a, **kw):
        if name in self.disabled:
            return None
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
                self.msg(f"{name}: исклучено по повторени грешки (види logs/game.log)")
            return None


# ----------------------------------------------------------------------- world loading with fallbacks
def run_tool(args, loader, stage, max_sec=3600):
    """Run a python tool in a subprocess; its `@@{json}` lines drive the splash screen (map, speed, bar).
    Returns the exit code (0 ok, 2 partial result, 124 killed because it overran `max_sec`)."""
    q = queue.Queue()
    env = dict(os.environ, GTA_EVENTS="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
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
                if line.startswith("@@"):
                    try:
                        loader.event(stage, json.loads(line[2:]))
                    except ValueError:
                        pass
                else:
                    log("[tool] " + line)
                    if not line.startswith(("[#", "[-", "[osm] cutting")):    # text progress bars: the bar shows those
                        loader.say(line.split("@@")[0].strip()[:160])
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
    """World older than its sources (OSM json or the build tools)?"""
    import glob
    man = os.path.join(path, "manifest.json")
    if not os.path.exists(man):
        return True
    t = os.path.getmtime(man)
    srcs = glob.glob(os.path.join(osm, "*.json")) + glob.glob(os.path.join(osm, "*.npy")) + [
        os.path.join(ROOT, "tools", n) for n in ("build_world.py", "furniture.py", "roads3d.py", "terrain.py")]
    return any(os.path.exists(p) and os.path.getmtime(p) > t for p in srcs)


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
    n = {"osm": a.refresh or not have or not box_ok or retry,
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
        return World(path, lambda f, note="": loader.tick(f, note))

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
            osm_src = os.environ.get("GTA_SOURCE") or settings_mod.MAP_SOURCE_IDS[settings_mod.Settings()["osm_source"] % 3]
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
    ap.add_argument("--mute", action="store_true", help="no sound")
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
    flags = rl.FLAG_VSYNC_HINT | rl.FLAG_WINDOW_RESIZABLE | rl.FLAG_MSAA_4X_HINT
    rl.set_config_flags(flags)
    rl.init_window(W, H, "Скопје GTA")
    if not rl.is_window_ready():                       # fallback: no MSAA / vsync
        rl.set_config_flags(rl.FLAG_WINDOW_RESIZABLE)
        rl.init_window(W, H, "Скопје GTA")
    rl.rl_disable_backface_culling()
    font.load()
    if font.ERR or not font._fonts:
        log("[font] Cyrillic font not loaded: " + "; ".join(font.ERR or ["files missing in assets/fonts"]))
    rl.set_exit_key(rl.KEY_NULL)
    if a.fullscreen or cfg["fullscreen"]:
        rl.toggle_fullscreen()
    rl.set_target_fps(0 if a.test else 144)

    need = plan_needs(a)
    loader = Loader(([("osm", 40)] if need.get("osm") else []) + ([("dem", 8)] if need.get("dem") else []) +
                    ([("build", 30)] if need.get("build") else []) + [("world", 12), ("overview", 8), ("textures", 6), ("chunks", 14)])
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
    try:
        tex = gl3d.build_textures()
    except Exception:  # noqa: BLE001
        log("[game] textures failed:\n" + traceback.format_exc())
        img = rl.gen_image_color(4, 4, rl.WHITE)
        t = rl.load_texture_from_image(img)
        tex = {"A": t, "B": t, "roof": t, "white": t, "panel": t, "house": t}
    streamer = Streamer(world, tex)
    renderer = Renderer(world, streamer, overview)
    loader.tick(0.4, "car & pedestrian models")
    renderer.BUILD_BUDGET = 10 ** 9
    for kind in range(vehicles.N):
        renderer.ai_model(kind, 0)
        loader.tick(0.4 + 0.3 * kind / vehicles.N, f"car models {kind + 1}/{vehicles.N}")
    for a_ in range(vehicles.PED_COUNT):
        renderer.ped_model(a_, 0, 0, 0)
        renderer.ped_model(a_, 0, 1, 0)
        loader.tick(0.7 + 0.3 * a_ / vehicles.PED_COUNT, f"pedestrian models {a_ + 1}/{vehicles.PED_COUNT}")
    renderer.BUILD_BUDGET = type(renderer).BUILD_BUDGET
    renderer.pick_model("burek")
    renderer.pick_model("ajvar")
    renderer.pick_model("cash")
    for _k in ("pistol", "uzi", "shotgun", "kalash", "bat", "zolja", "fuel"):
        renderer.pick_model(_k)
    loader.tick(1.0, "ready")

    rng = random.Random(a.seed)
    sim = Sim(world, rng, a.cars, a.peds)
    sim.car.color = -1                                   # the player's own car gets racing stripes
    sim.clock.hour = (a.hour if a.test or "--hour" in sys.argv else cfg["hour"]) % 24.0
    sim.auto_respawn = bool(a.test)
    lights = signals.Signals(world)
    sim.traffic.signals = sim.lights = lights
    print(f"[game] traffic lights: {len(lights.items)} signal heads")                     # test runs have nobody to press R
    loader.tick(1.0, "sound")
    aud = audio_mod.Audio(mute=a.mute)
    car_radio = radio_mod.Radio(aud)
    spk = SpeechWorker()
    night = Night(world)
    places = Places(world)
    sim.places = places
    import transit
    _osm = os.environ.get("GTA_OSM_DIR") or os.path.join(ROOT, "data", "osm")
    if not (os.path.exists(os.path.join(_osm, "transit.json")) and os.path.exists(os.path.join(_osm, "map_pois.json"))):
        try:                                               # bus lines + map POIs from the cached country file (once)
            import subprocess
            r_ = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "fetch_extras.py")], capture_output=True,
                                text=True, timeout=300)
            print((r_.stdout + r_.stderr).strip()[-600:])
        except Exception as e_:  # noqa: BLE001 - buses / markers are optional
            print(f"[game] extras skipped: {e_}")
    sim.transit = transit.Transit(sim, os.environ.get("GTA_OSM_DIR") or os.path.join(ROOT, "data", "osm"))
    log(f"[game] city buses: {len(sim.transit.lines)} JSP lines, {len(sim.transit.stops)} stops")
    import kids as kids_mod
    sim.kids = kids_mod.Kids(sim)
    log(f"[game] playgrounds / schools / pitches: {len(sim.kids.sites)}")
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
        if getattr(sim, "places", None) is not None:
            sim.places.lang = c["lang"]
        d = c["detail"]
        renderer.shadows = d >= 1
        flags["labels"] = d >= 1 and c["labels"]
        particles.max = (250, 600, 900)[d]
        night.detail = d
        if not a.test:
            if bool(rl.is_window_fullscreen()) != bool(c["fullscreen"]):
                rl.toggle_fullscreen()
            elif not c["fullscreen"] and not a.size:
                w_, h_ = settings_mod.RESOLUTIONS[c["res"]]
                if (rl.get_screen_width(), rl.get_screen_height()) != (w_, h_):
                    rl.set_window_size(w_, h_)
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
        with open(os.path.join(os.environ.get("GTA_OSM_DIR") or os.path.join(ROOT, "data", "osm"), "map_pois.json"), encoding="utf-8") as f_:
            hud.pois = [p_ for p_ in json.load(f_) if isinstance(p_, list) and len(p_) == 4]
    except (OSError, ValueError):
        hud.pois = []
    print(f"[game] map points of interest: {len(hud.pois)}")
    labels += [(nm_, x_, world.ground_y(x_, y_) + 3.2, y_, "poi:" + c_) for x_, y_, c_, nm_ in hud.pois if nm_]
    hud.markers = [(p[0], p[1], p[2]) for p in places.list]
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
        streamer.update([key], True, 1e9)
        loader.tick((i + 1) / len(first), f"chunk {i + 1}/{len(first)}  ({key[0]},{key[1]})")
    loader.finish()
    res_ = ""
    if not a.test and not a.nomenu:
        loader.hold()                              # let the showcase (cars / characters) play until a key press
    log("[game] ready")
    if not a.test and not a.nomenu:
        res_ = menu_mod.run(cfg, apply_cfg, False, aud=aud)
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
    show_dbg = a.test > 0
    shake = 0.0
    frame = 0
    t_game = 0.0
    ft_hist = []
    last_crash_txt = 0.0
    tip_t = 25.0
    hero_t = 14.0
    want_menu = False
    want_chars = False

    def hero_who():
        return characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][1]

    def hero_line():
        lines = hero_lines.LINES.get(characters.LIKOVI[getattr(sim, "lik", 0) % len(characters.LIKOVI)][0])
        return rng.choice(talk.pool(lines, getattr(sim, "lang", 1))) if lines else None
    acc = 0.0
    worst_bake = 0.0

    def say(text, x, y, who=None, prio=False):
        """Speak a line (Macedonian formant synth, background thread). Volume falls off with distance."""
        fx_, fy_, _, _ = sim.focus()
        vol = 1.0 if prio else max(0.0, 1.0 - math.hypot(x - fx_, y - fy_) / 32.0)
        if vol < 0.15 or len(text) > 90:
            return
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
                aud.play(kind, 0.8 if d["hit"] else 0.35, 1.0)
                if d["hit"]:
                    particles.sparks(d["x"], d["y"], 5, 1.1)
                    shake = max(shake, 0.25)
            elif kind == "hit":
                particles.emit("b", d["x"], d["y"], 1.0, 0, 0, 1.5, 4, 0.18, 0.5, (190, 20, 24), 2.0, 0.8, -6.0)
            elif kind == "ko":
                aud.play("punch", 0.8, 0.7)
                popups.add("НОКАУТ!", d["x"], d["y"], 2.6, 1.8, (255, 230, 90), 26)
            elif kind == "gunfire":
                aud.play("boom" if d["kind"] == "zolja" else "shot", 0.6 if d["kind"] == "zolja" else 0.75,
                         {"uzi": 1.25, "kalash": 0.9, "shotgun": 0.7}.get(d["kind"], 1.0))
            elif kind == "bullet_wall":                              # chips of plaster + dust puff
                particles.debris(d["x"], d["y"], (200, 194, 180), 4, 1.2)
                particles.smoke(d["x"] + d["nx"] * 0.3, d["y"] + d["ny"] * 0.3, 0.0, 1, 1.2, d["nx"] * 2, d["ny"] * 2, 0.4)
            elif kind == "bullet_car":                               # metal: sparks
                particles.sparks(d["x"], d["y"], 6, 0.9)
            elif kind == "bullet_tree":
                particles.leaves(d["x"], d["y"], 5)
            elif kind == "bullet_ground":
                particles.smoke(d["x"], d["y"], 0.1, 1, 0.2, 0, 0, 0.35)
                particles.debris(d["x"], d["y"], (120, 112, 100), 3, 0.2)
            elif kind == "rocket_trail":
                if rng.random() < 0.7:
                    particles.smoke(d["x"], d["y"], 0.3, 1, 1.1, 0, 0, 0.5)
            elif kind == "weapons_new":
                hud.set_banner("Ново утро, ново оружје на улиците (види мапа - M)", 4.0)
            elif kind == "pay":
                gains.add(d["amount"], d["x"], d["y"])
                aud.play("cash", 0.35, 1.0 + min(0.5, d["amount"] / 80.0))
            elif kind == "board":
                hud.set_banner(f"Во автобус си (билет {d['fare']} ден.)  –  Ctrl: преземи го воланот,  F: излези", 5.0)
            elif kind == "alight":
                hud.set_banner("Слезе од автобусот.", 2.0)
            elif kind == "ped_shot":
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
                aud.play("punch", 0.9, 0.85)
                shake = max(shake, 0.5)
            elif kind == "knocked_out":
                hud.set_banner(rng.choice(slang.KO_SELF), 3.5)
                if d["lost"]:
                    popups.add(f"-{d['lost']} ден. (некој ти ги зеде)", sim.walker.x, sim.walker.y, 3.0, 3.0, (255, 150, 140), 22)
            elif kind == "wake":
                hud.set_banner("Се разбуди. Главата боли.", 2.5)
            elif kind == "bought":
                aud.play("eat", 0.8)
                popups.add(f"{d['item']}  +{d['heal']} здравје", sim.walker.x, sim.walker.y, 2.8, 2.4, (255, 220, 120), 22)
                hud.set_banner(rng.choice(slang.BOUGHT), 2.0)
            elif kind == "broke":
                popups.add(f"{d['item']} = {d['price']} ден.", sim.walker.x, sim.walker.y, 2.8, 2.0, (255, 150, 140), 20)
                hud.set_banner(rng.choice(slang.BROKE), 2.0)
            elif kind == "cash":
                aud.play("cash", 0.8)
                popups.add(f"+{d['amt']} ден.", d["x"], d["y"], 2.0, 1.8, (140, 255, 150), 22)
            elif kind == "gun":
                aud.play("chime", 0.8, 1.4)
                hud.set_banner(f"{d.get('name', 'Пиштол').upper()}! Ctrl – пукај, Tab – смени оружје.", 2.4)
            elif kind == "fuel":
                aud.play("chime", 0.6, 0.9)
                hud.set_banner(f"Бензин! Резервоарот е {int(d['f'] * 100)}%.", 2.0)
            elif kind == "fuel_low":
                hud.set_banner("Бензинот е на резерва – барај канта!", 3.0)
            elif kind == "fuel_out":
                hud.set_banner("Нема бензин, брат! Барај канта или украдни друга кола.", 3.5)
            elif kind == "teleport":
                aud.play("chime", 0.5, 0.7)
            elif kind == "spray":
                dxs, dys = d["x1"] - d["x0"], d["y1"] - d["y0"]
                ls = math.hypot(dxs, dys) or 1.0
                particles.emit("w", d["x0"], d["y0"], 1.3, dxs / ls * 9, dys / ls * 9, 1.5, 3, 0.22, 0.7, (170, 210, 255), 0.6, 0.8, -4.0)
            elif kind == "extinguished":
                particles.smoke(d["x"], d["y"], 0.0, 6, 0.8, 0, 0, 1.6)
                popups.add("Изгаснато! Фала, пожарникари.", d["x"], d["y"], 3.0, 3.0, (170, 220, 255), 22)
            elif kind in ("revived", "revived_ped"):
                aud.play("revive", 0.9)
                if kind == "revived":
                    hud.set_banner("Брзата помош те врати! Пак си жив.", 3.0)
                else:
                    popups.add("Жив е!", d["x"], d["y"], 2.4, 2.0, (170, 255, 190), 24)
            if kind == "crash":
                aud.play("crash", min(1.0, d["impact"] / 14.0) * (1.0 if near(d["x"], d["y"]) else 0.0), 1.0 + rng.uniform(-0.1, 0.1))
            elif kind == "horn":
                aud.play(vehicles.HORN_SOUND[d["body"].kind], 0.6 if near(d["body"].x, d["body"].y) else 0.0, 1.0 + (d["body"].kind % 3) * 0.04)
            elif kind == "explode":
                aud.play("boom", 1.0 if near(d["body"].x, d["body"].y, 150) else 0.2)
            elif kind == "splash":
                aud.play("splash", 0.8 if not d.get("big") else 1.0, 0.8 if d.get("big") else 1.0)
            elif kind == "hurt_fall":
                aud.play("crash", 0.45, 1.5)
            elif kind == "fall":
                aud.play("crash", min(1.0, d["speed"] / 14.0), 0.8)
            elif kind in ("burek", "ajvar"):
                aud.play("eat" if kind == "burek" else "chime", 0.7)
            elif kind == "ped_hit":
                aud.play("punch", 0.6 if near(d["ped"].x, d["ped"].y) else 0.0, 0.6)
            if kind == "shout":
                say(d["text"], d["x"], d["y"], d.get("who"))
            elif kind == "shout_self":
                if rng.random() < 0.35:
                    d["text"] = hero_line() or d["text"]
                say(d["text"], fxs, fys, hero_who(), True)
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
                    aud.play("crash", min(0.6, 0.2 + imp / 20.0), 0.8)
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
                popups.add((d["who"] + ": " if d.get("who") else "") + d["text"], d["x"], d["y"], 2.6, 2.4, (255, 255, 255), 18)
            elif kind == "shout_self":
                if sim.walker:
                    popups.add(d["text"], sim.walker.x, sim.walker.y, 2.6, 1.6, (160, 255, 200), 20)
            elif kind == "horn":
                b = d["body"]
                popups.add(rng.choice(slang.HORN), b.x, b.y, 3.2, 1.4, (255, 240, 120), 24)
            elif kind == "burek":
                popups.add(rng.choice(slang.BUREK), d["x"], d["y"], 2.5, 2.2, (255, 220, 110), 22)
                particles.emit("c", d["x"], d["y"], 0.8, 0, 0, 3, 10, 0.25, 0.9, (255, 210, 90), 3.0, 0.9, -6)
            elif kind == "ajvar":
                popups.add(rng.choice(slang.AJVAR), d["x"], d["y"], 2.5, 2.4, (255, 120, 100), 22)
                particles.emit("c", d["x"], d["y"], 0.8, 0, 0, 3, 14, 0.25, 0.9, (220, 40, 30), 3.0, 0.9, -6)
                hud.set_banner("АЈВАР! Колата е како нова.", 2.0)
            elif kind == "splash":
                popups.add(rng.choice(slang.SPLASH), d["x"], d["y"], 3.0, 2.8, (160, 210, 255), 22)
                particles.emit("w", d["x"], d["y"], 0.6, 0, 0, 4, 18, 0.35, 0.9, (140, 190, 240), 4.0, 0.9, -8)
                hud.set_banner("ПЉУС!", 1.6)
            elif kind == "hurt_fall":
                popups.add(rng.choice(("Ај бре!", "Мајко моја!", "Грбот ми!", "Колено...")), sim.walker.x, sim.walker.y, 3.0, 1.8, (255, 160, 160), 22)
            elif kind == "fall":
                b = d["body"]
                particles.debris(b.x, b.y, (120, 120, 120), 10, 0.4)
                popups.add("БУМ! Слета од мостот", b.x, b.y, 3.2, 2.2, (255, 220, 160), 22)
            elif kind == "kerb":                                     # clunk over the kerb
                if d["body"].player_car:
                    aud.play("crash", min(0.35, d["speed"] / 40.0), 1.6)
            elif kind == "rocket":
                particles.explosion(d["x"], d["y"])
                aud.play("boom", 1.0)
                streamer.add_decal(("d", d["x"], d["y"], 3.6, (20, 18, 16, 190)))
                shake = max(shake, 3.0)
            elif kind == "swing":
                aud.play("punch", 0.5 if d["hit"] else 0.2)
            elif kind == "explode":
                b = d["body"]
                particles.explosion(b.x, b.y)
                streamer.add_decal(("d", b.x, b.y, 4.2, (20, 18, 16, 190)))
                streamer.add_decal(("d", b.x, b.y, 2.4, (8, 8, 8, 200)))
                shake = max(shake, 2.6 if math.hypot(b.x - cam_x, b.y - cam_y) < 80 else 0.6)
                popups.add(rng.choice(slang.EXPLODE), b.x, b.y, 4.5, 3.0, (255, 190, 80), 26)
            elif kind == "stolen":
                b = d["body"]
                popups.add("Украдена кола! +углед", b.x, b.y, 3.4, 2.0, (255, 255, 120), 22)
            elif kind == "enter":
                b = d["body"]
                popups.add(b.name, b.x, b.y, 3.4, 1.8, (200, 240, 255), 20)
            elif kind == "walker_dead":
                sim.stats["deaths"] += 1
                hud.set_banner(rng.choice(slang.DEATH), 3.0)
                if sim.walker:
                    streamer.add_decal(("d", sim.walker.x, sim.walker.y, 1.0, (150, 20, 24, 200)))
            elif kind == "respawn":
                hud.set_banner("Пак си тука. Нема фрка.", 2.0)
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
                particles.fire(b.x + fx_ * 1.2, b.y + fy_ * 1.2, 2, 0.9)
                particles.smoke(b.x + fx_, b.y + fy_, 0.9, 1, 1.2)
            elif b.health < 35 and rng.random() < 0.35:
                particles.smoke(b.x + fx_ * 1.4, b.y + fy_ * 1.4, 0.3 + (35 - b.health) / 50, 1, 1.0)

    def exhaust(dt):
        """Diesel smoke: city buses and big trucks puff dark smoke when pulling away, old cars a little."""
        fxs, fys = sim.focus()[:2]
        for b in sim.bodies:
            bus = getattr(b, "bus_line", None) is not None
            if not (bus or vehicles.LARGE[b.kind]) or b.exploded or (b.x - fxs) ** 2 + (b.y - fys) ** 2 > 90 ** 2:
                continue
            thr = b.ctl[0] if getattr(b, "ctl", None) else 0.0
            rate = (9.0 if thr > 0.3 and b.speed < 6 else 2.5) * dt
            if rng.random() < rate:
                L = vehicles.DIMS[b.kind][0] / 2
                hx, hy = math.cos(b.h), math.sin(b.h)
                particles.smoke(b.x - hx * L, b.y - hy * L, 0.75, 1, 0.5, -hx * 2, -hy * 2, 0.8)
        for c in sim.traffic.cars:
            if (c.x - fxs) ** 2 + (c.y - fys) ** 2 > 70 ** 2:
                continue
            big = vehicles.LARGE[c.kind]
            if rng.random() < (5.0 if big else 0.35) * dt * (2.0 if c.v < 4 else 1.0):
                L = vehicles.DIMS[c.kind][0] / 2
                hx, hy = math.cos(c.h), math.sin(c.h)
                particles.smoke(c.x - hx * L, c.y - hy * L, 0.7 if big else 0.45, 1, 0.45, -hx * 2, -hy * 2, 0.7 if big else 0.45)

    def handle_places(fx_, fy_):
        r = places.update(fx_, fy_)
        first_call = not t_places["seen"]
        t_places["seen"] = True
        if r and not first_call:                            # the starting neighbourhood is not called out
            hud.set_place(r[0], r[1], 5.0)
            say(r[1], fx_, fy_, "Водич", True)

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

    def handle_audio(fx_, fy_):
        if not aud.ok or aud.muted:
            return
        tf = min(1.5, sim.clock.traffic) / 1.5
        if sim.mode == "car":
            c = sim.car
            vmax = vehicles.PERF[c.kind][0]
            fr = min(1.0, c.speed / vmax)
            prof = vehicles.ENGINE_SOUND[c.kind]
            for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev"):
                if nm == prof:
                    aud.loop(nm, 0.2 + 0.3 * abs(inp_last.get("throttle", 0)) + 0.1 * fr, (0.55 + 1.7 * fr) if nm != "engine_ev" else (0.6 + 1.6 * fr), "engine")
                else:
                    aud.loop(nm, 0.0, 1.0, "engine")
            aud.loop("screech", 0.35 if (c.slip > 3.0 and c.speed > 4) else 0.0, 0.9 + min(0.3, c.slip * 0.03), "sfx")
        else:
            for nm in ("engine_i4", "engine_small", "engine_v8", "engine_diesel", "engine_truck", "engine_ev", "screech"):
                aud.loop(nm, 0.0)
        best = {}
        for c in sim.traffic.cars:
            if c.kind in vehicles.SIREN_SOUND and c.v > 3:
                best[c.kind] = min(best.get(c.kind, 1e9), math.hypot(c.x - fx_, c.y - fy_))
        spray = 1e9
        for b in sim.bodies:
            if b.kind in vehicles.SIREN_SOUND and getattr(b, "siren", False) and b.alive:
                best[b.kind] = min(best.get(b.kind, 1e9), math.hypot(b.x - fx_, b.y - fy_))
        for k, nm in vehicles.SIREN_SOUND.items():
            aud.loop(nm, max(0.0, 1.0 - best.get(k, 1e9) / 150.0) * 0.55, 1.0, "sfx")
        spraying = any(j.kind == "fire" and j.state == "work" and j.work_t > 3.0 and math.hypot(j.x - fx_, j.y - fy_) < 60 for j in sim.services.jobs)
        aud.loop("spray", 0.4 if spraying else 0.0, 1.0, "sfx")
        dk = sim.clock.dark
        amb_state["dens"] += (density_at(fx_, fy_) - amb_state["dens"]) * 0.02
        dn = amb_state["dens"]
        near_peds = sum(1 for p in sim.peds.list if p.mode == "walk" and abs(p.x - fx_) < 40 and abs(p.y - fy_) < 40)
        aud.loop("city", 0.1 + 0.3 * dn * (0.4 + 0.6 * tf))
        aud.loop("traffic", 0.45 * dn * tf)
        aud.loop("crowd", min(0.5, near_peds * 0.03 + 0.25 * dn * sim.clock.peds / 1.5) * (1.0 - 0.6 * dk))
        aud.loop("wind", 0.28 * (1.0 - dn))
        aud.loop("birds", max(0.0, 0.5 * (1 - dk * 1.6)) * (1.0 - 0.7 * dn))
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
    prev_enter = False
    tp_idx = -1
    snap = False
    last_phase = None
    while not rl.window_should_close():
        dt_real = rl.get_frame_time()
        dt = 1 / 60 if a.test else min(dt_real, 0.05)
        sw, sh = rl.get_screen_width(), rl.get_screen_height()
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
                    for nm in aud.LOOPS:
                        aud.loop(nm, 0.0)
            enter_pressed = rl.is_key_pressed(rl.KEY_F) or rl.is_key_pressed(rl.KEY_ENTER)
            if rl.is_key_pressed(rl.KEY_TAB) and sim.mode == "foot" and sim.walker is not None:   # Tab: next weapon
                import actors as _a
                wname = sim.walker.cycle()
                hud.set_banner(_a.WEAPONS[wname][0] if wname in _a.WEAPONS else "Тупаници", 1.2)
            if rl.is_key_pressed(rl.KEY_M):
                show_map = not show_map
            if rl.is_key_pressed(rl.KEY_F3):
                show_dbg = not show_dbg
            if rl.is_key_pressed(rl.KEY_F11):
                rl.toggle_fullscreen()
            if rl.is_key_pressed(rl.KEY_ESCAPE) or want_menu:
                want_menu = False
                if show_map:
                    show_map = False
                else:
                    res_ = menu_mod.run(cfg, apply_cfg, True, save_fn=lambda n_: savegame.save(sim, cfg, n_))
                    if res_ == "quit":
                        break
                    if res_ == "chars":
                        if menu_mod.pick_character(cfg, aud):
                            break
                        savegame.new_character(sim, cfg["lik"])
                        hud.set_banner("Нов лик, ист град.", 3.0)
                    elif res_.startswith("load"):
                        d_ = savegame.read(int(res_[4:]))
                        if d_:
                            savegame.restore(sim, cfg, d_)
                            apply_cfg(cfg, True)
                            snap = True
                            hud.set_banner("Играта е вчитана.", 3.0)
            if rl.is_key_pressed(rl.KEY_L) or want_chars:                  # L: switch character without opening the menu
                want_chars = False
                if menu_mod.pick_character(cfg, aud):
                    break
                savegame.new_character(sim, cfg["lik"])
                hud.set_banner("Нов лик, ист град.", 3.0)
            if rl.is_key_pressed(rl.KEY_R) and sim.mode == "car":
                p = world.nearest_drive_point(sim.car.x, sim.car.y)
                if p:
                    sim.car.x, sim.car.y, sim.car.h = p
                    sim.car.vx = sim.car.vy = 0.0
                    popups.add("Вратено на патот, брате.", p[0], p[1], 3, 2)
            user_zoom = max(0.35, min(2.4, user_zoom * (1.12 ** rl.get_mouse_wheel_move())))
        inp_last.clear()
        inp_last.update(inp)
        if show_map and not a.test:
            pick = hud.map_pick(sw, sh)
            if pick is not None:
                sim.teleport(pick[0], pick[1])
                show_map = False
                snap = True
        if enter_pressed:
            if sim.mode == "car":
                sim.exit_car()
            else:
                guard.run("enter", sim.try_enter)
        # ------------------------------------------------ simulation
        if guard.run("sim", sim.update, dt, inp, 2) is None and "sim" in guard.disabled:
            hud.set_banner("Симулацијата падна – види logs/game.log", 4)
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
        hero_t -= dt
        if hero_t < 0:
            hero_t = rng.uniform(20.0, 42.0)                 # your own character thinks out loud now and then
            ln_ = hero_line()
            if ln_:
                fx0, fy0, _, _ = sim.focus()
                say(ln_, fx0, fy0, hero_who(), False)
                popups.add(ln_, fx0, fy0, 2.8, 3.2, (160, 255, 200), 20)
        tip_t -= dt
        if tip_t < 0:
            tip_t = 40.0
            fx0, fy0, _, _ = sim.focus()
            popups.add(rng.choice(slang.TIPS), fx0, fy0, 7.0, 6.0, (200, 230, 255), 20)
        # ------------------------------------------------ audio, speech, tooltips, clock banners
        fx, fy, fvx, fvy = sim.focus()
        guard.run("places", handle_places, fx, fy)
        guard.run("audio", handle_audio, fx, fy)
        song = guard.run("radio", car_radio.update, dt, sim.mode == "car", cfg["vol_radio"])
        if song:
            hud.set_banner("Радио: " + song, 3.0)
        res = spk.poll()
        if res is not None:
            key, pcm, sr_ = res
            vol_, prio_, _t = pend_say.pop(key, (0.0, False, 0.0))
            if vol_ > 0 and (prio_ or not aud.speaking()):      # stale or overlapping lines are dropped
                aud.speak(pcm, vol_, sr_)
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
        ppm += (tgt_ppm - ppm) * min(1.0, 2.5 * dt)
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
        # ------------------------------------------------ streaming
        lod = ppm >= LOD_PPM
        wanted = want_list(cam_x, cam_y, ppm, sw, sh, 70) if lod else []
        guard.run("stream", streamer.update, wanted, lod)
        worst_bake = max(worst_bake, streamer.bake_ms)
        # ------------------------------------------------ draw
        rl.begin_drawing()
        try:
            rl.clear_background(rl.Color(26, 28, 32, 255))
            guard.run("render", renderer.draw, cam, Hc, rect, ppm, sim, particles, t_game)
            if lod:
                guard.run("night", night.draw, cam, rect, ppm, sim, sim.clock.dark, t_game, sw, sh)
            if cfg.get("smog", 1):
                guard.run("smog", smog.draw, cam, cam_x, cam_y, ppm, sw, sh, sim.clock.hour, t_game,
                          min(1.0, sim.clock.traffic), 1.0, world.ground_y(cam_x, cam_y))
            guard.run("popups", popups.draw, cam)
            guard.run("gains", gains.draw, cam, (sw - 230, 26))
            if lod and ppm > 4.0 and flags["labels"]:
                guard.run("labels", draw_labels, labels, cam, fx, fy, sw, sh)
            prompt = ""
            if sim.mode == "foot" and sim.walker and sim.walker.health > 0:
                for b in sim.bodies:
                    if b.alive and math.hypot(b.x - fx, b.y - fy) < 4.0:
                        prompt = f"[F] Влези во {b.name}" + (" (паркирано)" if b.parked_idx is not None else "")
                        break
                else:
                    for c in sim.traffic.cars:
                        if math.hypot(c.x - fx, c.y - fy) < 3.4:
                            prompt = f"[F] УКРАДИ ја колата! ({vehicles.NAMES[c.kind]})"
                            break
            elif sim.mode == "car" and sim.car.speed < 2.0:
                prompt = "[F] Излези"
            if sim.mode == "foot" and sim.walker and sim.walker.health <= 0 and sim.walker.cause != "fight":
                prompt = "[R] Почни одново"
            pending = sum(1 for k_ in wanted[:30] if k_ not in streamer.ground)
            guard.run("hud", hud.draw, sim, sw, sh, show_map, prompt, (len(wanted[:30]) - pending, len(wanted[:30])) if wanted else None, ppm)
            vs_ = spk.status()
            if vs_:
                font.draw_text("Глас: " + vs_, 16, 62, 16, rl.Color(255, 220, 150, 220))
            if not a.test:
                font.draw_text("WASD вози/оди  SPACE рачна/скок  CTRL удри/пукај  F влез/излез  H труба  1-4 киоск  M мапа (клик=телепорт)  T места  [ ] време  N тивко",
                             16, sh - 30 if False else 36, 16, rl.Color(255, 255, 255, 170))
            if show_dbg:
                font.draw_text(f"{rl.get_fps()} fps  {dt_real * 1000:.1f} ms | ground {renderer.drawn_chunks}/{len(streamer.ground)} "
                             f"meshes {renderer.drawn_meshes}/{len(streamer.meshes)} baked {streamer.baked} (last {streamer.bake_ms:.0f} ms) "
                             f"| cars {len(sim.traffic.cars)} bodies {len(sim.bodies)} peds {len(sim.peds.list)} "
                             f"parts {len(particles.p)} | ppm {ppm:.1f} err {sum(guard.errors.values())}", 12, 10, 16, rl.Color(255, 255, 255, 255))
            if not a.test:                                     # mouse buttons: options menu and exit, always on screen
                bx_ = sw - 300 - 112 * 3
                if font.button("Лик (L)", bx_, 10, 104, 34):
                    want_chars = True
                if font.button("Мени (Esc)", bx_ + 112, 10, 104, 34):
                    want_menu = True
                font.exit_button(bx_ + 224, 10)
        finally:
            rl.end_drawing()
        ft_hist.append(dt_real)
        if a.test and a.shot and frame in (5, 90, 200, 258, 266, 274, 306, 345, 800, 900, 930, a.test - 1):
            img = rl.load_image_from_screen()
            rl.export_image(img, f"{a.shot}_{frame}.png")
            rl.unload_image(img)
        if a.test and frame >= a.test:
            break
    spk.dead = True
    if aud.ok:
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
                fatal_screen("Скопје GTA падна", tb.strip().splitlines()[-8:] + ["", f"Целиот дневник: {LOG_FILE}"], 0)
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
