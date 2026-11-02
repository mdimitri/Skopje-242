"""Launch-time update check against the public GitHub repo (mdimitri/skopje-242, branch main).

Compares the commit id stored in `.version` next to run.bat with the latest commit on GitHub.  If they differ the
player chooses: update (download the repo zip, overwrite game files, restart) or keep the version on disk.
Offline / slow network / any error -> silently skip.  User data (settings, saves, built world, logs, music, .runtime)
and the .bat files (cmd may be reading run.bat right now) are never touched; files are only overwritten, never deleted.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile

import pyray as rl

import font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, ".version")
REPO = "mdimitri/skopje-242"
API_URL = f"https://api.github.com/repos/{REPO}/commits/main"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"
CHECK_TIMEOUT = 4          # seconds: an offline launch must not hang
KEEP_DIRS = {"data", "logs", ".runtime", "library", "music", "saves", "sound_requests", ".crlf", ".git"}
KEEP_FILES = {"settings.json", ".version"}


def local_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def remote_version():
    """Latest commit sha on main, or '' when it cannot be fetched."""
    try:
        req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github.sha", "User-Agent": "skopje-242"})
        with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as r:
            sha = r.read().decode("ascii", "ignore").strip()
        return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else ""
    except Exception:  # noqa: BLE001 - offline, rate limited, ...
        return ""


def _keep(rel):
    parts = rel.replace("\\", "/").split("/")
    return parts[0] in KEEP_DIRS or rel in KEEP_FILES or (len(parts) == 1 and rel.lower().endswith(".bat"))


def install(sha, prog):
    """Download the zip of `sha` and overwrite game files. prog = dict(done, total, err)."""
    tmp = tempfile.mkdtemp(prefix="sk242_upd_")
    try:
        zpath = os.path.join(tmp, "repo.zip")
        req = urllib.request.Request(f"https://codeload.github.com/{REPO}/zip/{sha}", headers={"User-Agent": "skopje-242"})
        with urllib.request.urlopen(req, timeout=30) as r, open(zpath, "wb") as out:
            prog["total"] = int(r.headers.get("Content-Length") or 0)
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                out.write(b)
                prog["done"] += len(b)
        with zipfile.ZipFile(zpath) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            top = names[0].split("/")[0] + "/"
            for n in names:                                   # check everything before touching the game
                if not n.startswith(top) or ".." in n.split("/"):
                    raise ValueError("unexpected path in zip: " + n)
            for n in names:
                rel = n[len(top):]
                if _keep(rel):
                    continue
                dest = os.path.join(ROOT, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(n) as src, open(dest + ".new", "wb") as out:
                    shutil.copyfileobj(src, out)
                os.replace(dest + ".new", dest)
        with open(VERSION_FILE, "w", encoding="utf-8") as f:    # last: a failed update is offered again next launch
            f.write(sha)
    except Exception as e:  # noqa: BLE001
        prog["err"] = str(e) or e.__class__.__name__
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        prog["finished"] = True


def _screen(lines, bar=None):
    w, h = rl.get_screen_width(), rl.get_screen_height()
    rl.begin_drawing()
    rl.clear_background(rl.Color(18, 20, 26, 255))
    y = h // 2 - 70
    for text, size, col in lines:
        font.draw_text(text, w // 2 - int(len(text) * size * 0.28), y, size, col)
        y += size + 22
    if bar is not None:
        bw = min(480, w - 80)
        rl.draw_rectangle(w // 2 - bw // 2, y + 10, bw, 10, rl.Color(50, 54, 64, 255))
        rl.draw_rectangle(w // 2 - bw // 2, y + 10, int(bw * bar), 10, rl.Color(120, 200, 120, 255))
    rl.end_drawing()


def check():
    """Call once at launch with the window open. Returns True when the game was updated and must restart."""
    if not rl.is_window_ready():
        return False
    remote = remote_version()
    local = local_version()
    if not remote or remote == local:
        return False
    white, grey = rl.WHITE, rl.Color(170, 174, 184, 255)
    while not rl.window_should_close():
        _screen([("Достапна е нова верзија на Скопје 242", 34, white),
                 (f"Тековна: {local[:7] or 'непозната'}   Нова: {remote[:7]}", 22, grey),
                 ("[Enter] Преземи и ажурирај      [Esc] Продолжи со тековната", 24, white)])
        if rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_KP_ENTER):
            break
        if rl.is_key_pressed(rl.KEY_ESCAPE):
            return False
    else:
        return False
    prog = {"done": 0, "total": 0, "err": "", "finished": False}
    th = threading.Thread(target=install, args=(remote, prog), daemon=True)
    th.start()
    while not prog["finished"]:
        rl.poll_input_events()
        _screen([("Се презема и ажурира ...", 30, white)], (prog["done"] / prog["total"]) if prog["total"] else 0.0)
    if prog["err"]:
        t0 = rl.get_time()
        while rl.get_time() - t0 < 4 and not rl.window_should_close():
            _screen([("Ажурирањето не успеа - продолжува тековната верзија", 26, white), (prog["err"][:90], 18, grey)])
        return False
    return True


def restart():
    """Start the game again through run.bat (it re-runs setup if requirements changed) and let this process end."""
    bat = os.path.join(ROOT, "run.bat")
    args = sys.argv[1:]
    if os.name == "nt" and os.path.exists(bat):
        subprocess.Popen(["cmd", "/c", "start", "", "/min", bat] + args, cwd=ROOT)
    else:
        subprocess.Popen([sys.executable] + sys.argv, cwd=ROOT)
