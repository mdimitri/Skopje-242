"""Photogrammetry in the background while the game runs (settings: "photogram_bg", stays on until switched off).

A separate low-priority process (tools/photogram_full.py --bg) fits the buildings from every capture folder under
<game>/Photogrametry, SegFormer included, while you play.  Every photo's result is stored as soon as it is done, so quitting the
game stops the run and the next start continues it.  Every fitted building is saved the moment it is done; at the next start
apply_pending() puts them into data/osm/photogram.json and the world is rebuilt with them (about as long as any rebuild).
line() is the progress text for the title menu and the loading screen.
"""
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PHOTOS = os.path.join(ROOT, "Photogrametry")
OSM = os.path.join(ROOT, "data", "osm")
CACHE = "_photogram"                     # photogram.CACHE (not imported here: photogram pulls in numpy / PIL / the build tools)

_proc = None
_ready = False                           # the world is loaded: the run may start (never during the game's own build)
_finished = False                        # the run ended by itself this session (all photos done): not started again
ENABLED = False                          # the setting, as last seen (the loading screen has no settings at hand)
_line = ("", 0.0)
_mark = [None]                           # the applied fits' hash, until the world has been built with them


def _log(s):
    print("[photobg] " + s, flush=True)


def have_photos():
    if not os.path.isdir(PHOTOS):
        return False
    for d, subs, files in os.walk(PHOTOS):
        subs[:] = [x for x in subs if x != CACHE]
        if any(f.lower().endswith(".csv") for f in files):
            return True
    return False


def _hash_fits(d):
    return hashlib.md5(json.dumps(d.get("buildings", {}), sort_keys=True).encode("utf-8")).hexdigest()


def read_fits():
    """-> (fit file dict, buildings from the journal not in it yet).  Read only: the viewer shows them while the run goes on."""
    src = os.path.join(PHOTOS, CACHE, "fit_detail.json")
    journal = os.path.join(PHOTOS, CACHE, "fit_detail.new.jsonl")
    try:
        with open(src, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {"version": 1, "algo": "detail", "buildings": {}}
    n_new = 0
    try:                                  # buildings fitted since the fit file was written (each saved the moment it was done)
        with open(journal, encoding="utf-8") as f:
            for ln in f:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue              # the last line of a run killed mid-write (or still being written)
                d["buildings"][e["id"]] = e["fit"]
                n_new += 1
    except OSError:
        pass
    return d, n_new


def running():
    return _proc is not None and _proc.poll() is None


def apply_pending(log=_log):
    """At the start, before the world is checked: newer background fits than the game has -> data/osm/photogram.json.
    -> True when it changed (the caller then rebuilds the world)."""
    src = os.path.join(PHOTOS, CACHE, "fit_detail.json")
    journal = os.path.join(PHOTOS, CACHE, "fit_detail.new.jsonl")
    mark = os.path.join(OSM, "photogram.src.md5")
    d, n_new = read_fits()
    if not d["buildings"]:
        return False
    if n_new:
        d["made"] = time.strftime("%Y-%m-%d %H:%M")
        try:
            with open(src + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, indent=0)
            os.replace(src + ".tmp", src)
            os.remove(journal)
        except OSError as e:
            log(f"could not merge the new buildings into the fit file: {e}")
    h = _hash_fits(d)
    try:
        with open(mark, encoding="utf-8") as f:
            if f.read().strip() == h and os.path.exists(os.path.join(OSM, "photogram.json")):
                return False
    except OSError:
        pass
    try:
        import photogram as pg
        _st, op = pg.load_settings(PHOTOS)
        pg.apply_to_game(PHOTOS, "detail", OSM, op)
        _mark[0] = h                      # written once the world build with them has finished (mark_built), not before
    except Exception as e:  # noqa: BLE001 - never stop the game for it: the old buildings stay
        log(f"could not apply the fitted buildings: {type(e).__name__}: {e}")
        return False
    log(f"{len(d.get('buildings', {}))} fitted buildings applied: the world is rebuilt with them")
    return True


def mark_built():
    """The world build finished: the applied fits are in it, the next start need not build again.  A build cut short (the game
    closed during it) leaves no mark, so the next start applies and builds again."""
    if _mark[0] is None:
        return
    try:
        with open(os.path.join(OSM, "photogram.src.md5"), "w", encoding="utf-8") as f:
            f.write(_mark[0])
        _mark[0] = None
    except OSError:
        pass


def set_ready():
    global _ready
    _ready = True


def sync(cfg):
    """Every frame (menu and game): start / stop the run to match the setting.  Cheap when nothing changes."""
    global _proc, _finished, ENABLED
    on = ENABLED = bool(cfg and cfg.get("photogram_bg"))
    if _proc is not None and _proc.poll() is not None:     # finished (or failed) on its own
        _log(f"background run ended (exit {_proc.returncode})")
        _proc, _finished = None, True
    if on and _ready and _proc is None and not _finished:
        start()
    elif not on and _proc is not None:
        stop()


def start():
    global _proc
    if _proc is not None or not have_photos():
        return
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    for f in ("stop", "progress.json"):                  # a fresh progress line, not the last run's end or error
        try:
            os.remove(os.path.join(PHOTOS, CACHE, f))
        except OSError:
            pass
    kw = {}
    if os.name == "nt":                                   # below normal priority, no console window; children inherit it
        kw["creationflags"] = 0x00004000 | 0x08000000
    else:
        kw["start_new_session"] = True
        kw["preexec_fn"] = lambda: os.nice(10)
    try:
        lf = open(os.path.join(ROOT, "logs", "photogram_bg.log"), "w", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", SK242_NO_INSTALL=os.environ.get("SK242_NO_INSTALL", "0"))
        _proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "photogram_full.py"), PHOTOS, "--bg", "--osm", OSM], cwd=ROOT,
                                 stdout=lf, stderr=subprocess.STDOUT, env=env, **kw)
        _log(f"background run started (pid {_proc.pid})")
        import atexit
        atexit.register(stop)                             # whatever way the game ends, the run and its workers end with it
    except Exception as e:  # noqa: BLE001
        _log(f"cannot start the background run: {e}")
        _proc = None


def stop(wait=4.0):
    """Ask the run to stop (it stores what it has), then end it and its worker processes for sure."""
    global _proc
    p, _proc = _proc, None
    if p is None:
        return
    try:
        os.makedirs(os.path.join(PHOTOS, CACHE), exist_ok=True)
        open(os.path.join(PHOTOS, CACHE, "stop"), "w").close()
    except OSError:
        pass
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < wait:
        time.sleep(0.1)
    if p.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=0x08000000)
            else:
                import signal
                os.killpg(p.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            p.kill()
    _log("background run stopped")


def line():
    """'23% готово, работи со слика: 0412_....jpg #1412/6148' (or '' when off / nothing to say).  Read at most once a second."""
    global _line
    if not ENABLED:
        return ""
    now = time.time()
    if now - _line[1] < 1.0:
        return _line[0]
    txt = ""
    try:
        with open(os.path.join(PHOTOS, CACHE, "progress.json"), encoding="utf-8") as f:
            p = json.load(f)
        pct = int(p.get("frac", 0) * 100)
        if p.get("error"):
            txt = f"Фотограметрија: грешка ({p['error'][:60]})"
        elif p.get("done"):
            txt = "Фотограметрија: 100% готово" if _proc is None else ""
        elif _proc is not None and p.get("file"):
            txt = f"Фотограметрија {pct}% готово, работи со слика: {os.path.basename(p['file'])} #{p['n']}/{p['N']}"
        elif _proc is not None:
            txt = f"Фотограметрија {pct}% готово" + (f", {p['step']}" if p.get("step") else ", се подготвува")
        elif pct:
            txt = f"Фотограметрија {pct}% готово (продолжува кога ќе се вклучи)"
    except (OSError, ValueError, KeyError, TypeError):
        txt = "Фотограметрија: се подготвува" if _proc is not None else ""
    _line = (txt, now)
    return txt
