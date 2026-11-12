"""Launch-time update check against the public GitHub repo (mdimitri/skopje-242, branch main).

Compares the commit id stored in `.version` next to run.bat with the latest commit on GitHub.  If they differ the
player chooses: update (download the repo zip, overwrite game files, restart) or keep the version on disk.
Offline / slow network / any error -> silently skip.  User data (settings, saves, built world, logs, music, .runtime)
and the .bat files (cmd may be reading run.bat right now) are never touched; files are only overwritten, never deleted.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import zipfile

import pyray as rl

import font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(ROOT, ".version")       # commit sha of the installed copy (what the update check compares)
MAJOR = "3"


def _minor():
    """Minor version = commit count on main, written into src/build.txt by .github/workflows/build-number.yml on every push."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build.txt"), "r", encoding="utf-8") as f:
            return f.read().strip() or "0"
    except OSError:
        return "0"


GAME_VERSION = MAJOR + "." + _minor()               # the player-facing major.minor version (splash and every menu)
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


GIT = shutil.which("git")
REPO_URL = f"https://github.com/{REPO}.git"


def _git(*args, timeout=30):
    """Run git in the game folder; returns (exit code, stdout).  Never prompts for credentials (the repo is public)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([GIT, *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return r.returncode, (r.stdout.strip() or r.stderr.strip())


def is_git_checkout():
    """True when the game folder is a git checkout on branch main with a usable git executable: then git does the update."""
    if not GIT or not os.path.exists(os.path.join(ROOT, ".git")):
        return False
    try:
        return _git("symbolic-ref", "--short", "-q", "HEAD", timeout=10) == (0, "main")
    except Exception:  # noqa: BLE001
        return False


def git_versions():
    """(local, remote) shas for a git checkout.  Fetches main from the public URL (config untouched, no sign-in needed).
    remote == local when nothing new upstream, also when the checkout is AHEAD of GitHub (local commits) or has diverged
    (cannot be fast-forwarded safely, so it is never offered).  ('', '') on any error."""
    try:
        if _git("fetch", "--quiet", REPO_URL, "main", timeout=CHECK_TIMEOUT + 6)[0] != 0:
            return "", ""
        _, local = _git("rev-parse", "HEAD", timeout=10)
        _, remote = _git("rev-parse", "FETCH_HEAD", timeout=10)
        if len(local) != 40 or len(remote) != 40:
            return "", ""
        if _git("merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD", timeout=10)[0] != 0:
            return local, local          # ahead of / diverged from GitHub: nothing safe to apply
        return local, remote
    except Exception:  # noqa: BLE001
        return "", ""


def install_git(sha, prog):
    """Fast-forward main to the fetched commit.  Git itself refuses (and changes nothing) if an uncommitted edit or an
    untracked file would be overwritten; other local changes, text/ included, are left exactly as they are."""
    prog["phase"] = "git"
    try:
        code, out = _git("merge", "--ff-only", "--quiet", sha, timeout=120)
        if code != 0:
            raise RuntimeError(out.splitlines()[0] if out else "git merge failed")
        with open(VERSION_FILE, "w", encoding="utf-8") as f:
            f.write(sha)
    except Exception as e:  # noqa: BLE001
        prog["err"] = str(e) or e.__class__.__name__
    finally:
        prog["finished"] = True


def _keep(rel):
    parts = rel.replace("\\", "/").split("/")
    return parts[0] in KEEP_DIRS or rel in KEEP_FILES or (len(parts) == 1 and rel.lower().endswith(".bat"))


def install_delta(base, sha, prog):
    """Fetch only the files that changed between commits `base` and `sha` (GitHub compare API + raw files).
    Raises when that is not possible (unknown base, >= 300 changed files, network error) so the caller falls back to the zip."""
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/compare/{base}...{sha}", headers={"User-Agent": "skopje-242"})
    with urllib.request.urlopen(req, timeout=15) as r:
        cmp_ = json.loads(r.read().decode("utf-8"))
    files = cmp_.get("files") or []
    if cmp_.get("status") not in ("ahead",) or not files or len(files) >= 300:
        raise ValueError("delta not usable")
    todo = [f for f in files if f.get("status") != "removed" and not _keep(f["filename"])]   # deletions are never applied (see module doc)
    prog["phase"], prog["n"], prog["nn"] = "extract", 0, len(todo)
    for f in todo:
        rel = f["filename"]
        if ".." in rel.split("/"):
            raise ValueError("unexpected path: " + rel)
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{urllib.parse.quote(rel)}"
        dest = os.path.join(ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "skopje-242"}), timeout=30) as r, open(dest + ".new", "wb") as out:
            shutil.copyfileobj(r, out)
        os.replace(dest + ".new", dest)
        prog["n"] += 1


def install(sha, prog):
    """Download the zip of `sha` and overwrite game files. prog = dict(done, total, err)."""
    base = local_version()
    if len(base) == 40:
        try:
            install_delta(base, sha, prog)
            with open(VERSION_FILE, "w", encoding="utf-8") as f:
                f.write(sha)
            prog["finished"] = True
            return
        except Exception:  # noqa: BLE001 - fall back to the full zip below
            prog["phase"], prog["n"], prog["done"] = "", 0, 0
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
            prog["phase"], prog["n"] = "extract", 0
            for n in names:
                prog["n"] += 1
                prog["nn"] = len(names)
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
    """Progress / error screen in the same comic panel as the update question."""
    import menu
    th = menu._th
    w, h = rl.get_screen_width(), rl.get_screen_height()
    pw, ph = min(w - 40, 880), 300
    px, py = (w - pw) // 2, (h - ph) // 2
    rl.begin_drawing()
    rl.clear_background(th["paper"])
    menu._panel(px, py, pw, ph)
    y = py + 34
    for i, (text, size, _c) in enumerate(lines):
        text = font.fit(text, size, pw - 60, "cond")
        col = th["fg"] if i == 0 else th["mu"]
        font.draw_text(text, px + (pw - font.measure_text(text, size, "cond")) // 2, y, size, col, bold="cond")
        y += size + 30
    if bar is not None:
        bw = pw - 80
        bx, by = px + 40, py + ph - 70
        rl.draw_rectangle(bx, by, bw, 28, th["p2"])
        menu._skew(bx, by, max(2, int(bw * bar)), 28, -8, th["a1"])
        rl.draw_rectangle_lines_ex(rl.Rectangle(bx, by, bw, 28), 3, th["ink"])
    rl.end_drawing()


def _prompt(local, remote):
    """Themed update question: comic panel + the menus' skewed buttons, mouse hover / click or Enter / Esc."""
    import menu
    t0 = rl.get_time()
    sel = 0
    last = None
    while not rl.window_should_close():
        W, H = rl.get_screen_width(), rl.get_screen_height()
        th = menu._th
        pw, ph = min(W - 40, 880), 300
        px, py = (W - pw) // 2, (H - ph) // 2
        bw, bh, gap = (pw - 90) // 2, 56, 30
        by = py + ph - bh - 36
        rects = [(px + 30, by), (px + 60 + bw, by)]
        m = rl.get_mouse_position()
        if last is not None and (m.x, m.y) != last:
            for i, (bx, byy) in enumerate(rects):
                if bx <= m.x < bx + bw and byy <= m.y < byy + bh:
                    sel = i
        last = (m.x, m.y)
        hit = next((i for i, (bx, byy) in enumerate(rects) if bx <= m.x < bx + bw and byy <= m.y < byy + bh), None)
        if rl.is_key_pressed(rl.KEY_LEFT) or rl.is_key_pressed(rl.KEY_RIGHT) or rl.is_key_pressed(rl.KEY_TAB):
            sel = 1 - sel
        if rl.get_time() - t0 > 0.3:
            if rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_KP_ENTER) or rl.is_key_pressed(rl.KEY_SPACE):
                return sel == 0
            if rl.is_key_pressed(rl.KEY_ESCAPE):
                return False
            if hit is not None and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                return hit == 0
        rl.begin_drawing()
        rl.clear_background(th["paper"])
        menu._panel(px, py, pw, ph)
        for txt, sz, y, col in (("Достапна е нова верзија на Скопје 242", 36, py + 34, th["fg"]),
                                (f"Тековна: {local[:7] or 'непозната'}   Нова: {remote[:7]}", 24, py + 100, th["mu"])):
            font.draw_text(txt, px + (pw - font.measure_text(txt, sz, "cond")) // 2, y, sz, col, bold="cond")
        for i, (lab, (bx, byy)) in enumerate(zip(("Преземи и ажурирај", "Продолжи со тековната"), rects)):
            menu._btn(bx, byy, bw, bh, lab, sel == i, 26)
        rl.end_drawing()
    return False


def check():
    """Call once at launch with the window open. Returns True when the game was updated and must restart."""
    if not rl.is_window_ready():
        return False
    use_git = is_git_checkout()
    local, remote = git_versions() if use_git else (local_version(), remote_version())
    if not remote or remote == local:
        return False
    white, grey = rl.WHITE, rl.Color(170, 174, 184, 255)
    if not _prompt(local, remote):
        return False
    prog = {"done": 0, "total": 0, "err": "", "finished": False}
    th = threading.Thread(target=install_git if use_git else install, args=(remote, prog), daemon=True)
    th.start()
    while not prog["finished"]:
        rl.poll_input_events()
        if prog.get("phase") == "git":
            frac, what = 0.5, "Се ажурира преку git"
        elif prog.get("phase") == "extract":                      # download = first 70 %, unpacking files = the rest
            frac, what = 0.7 + 0.3 * prog["n"] / max(1, prog.get("nn", 1)), f"Се ажурира: {prog['n']} / {prog.get('nn', 0)} датотеки"
        else:
            mb = prog["done"] / 1048576
            # codeload sends no Content-Length (chunked zip): fall back to a typical zip size so the bar still moves
            frac, what = 0.7 * min(0.99, prog["done"] / (prog["total"] or 60 * 1048576)), f"Се презема: {mb:.1f} MB"
        _screen([("Се презема и ажурира ...", 30, white), (what, 20, grey)], frac)
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
