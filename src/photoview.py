"""The photogrammetric builder's screen (title menu -> ФОТОГРАМЕТРИЈА): pick the photo folder, watch src/photogram.py fit the
buildings in 3D, compare algorithms, send the result to the game.

Mouse: right drag = turn, middle drag / Shift + right drag = pan, wheel = zoom, left click on a camera = pick that capture.
Keys:  WASD / QE = move, F = frustums, T = photos on the frustums, G = current / fitted look, 1-3 = algorithm, R = build,
       V = stand in the picked capture's camera (photo over the scene; [ ] = how see-through), M = photo / labels / game view
       in the side panel, Tab = next capture, Esc = back.
"""
import math
import os
import time

import numpy as np
import pyray as rl
from PIL import Image

import font
import gl3d
import photogram as pg

ROOT = pg.ROOT
LAST = os.path.join(ROOT, "data", "photogram_folder.txt")
PINK = rl.Color(226, 32, 104, 255)
INK = rl.Color(232, 226, 232, 255)
DIM = rl.Color(150, 140, 150, 255)
PANEL = rl.Color(16, 12, 20, 210)
LOOK_COL = {"photo": rl.Color(80, 230, 120, 255), "inferred": rl.Color(90, 160, 255, 255)}
LABEL_RGB = np.array([[120, 120, 120], [230, 200, 60], [90, 170, 255], [40, 200, 70], [230, 60, 60], [150, 110, 80]], np.uint8)


def _has_manifest(d):
    return os.path.isfile(os.path.join(d, "manifest.csv"))        # one stat, not a listing of every subfolder


def _subdirs(d):
    try:
        return sorted((e.name for e in os.scandir(d) if e.is_dir() and not e.name.startswith((".", "$"))), key=str.lower)
    except OSError:
        return []


def ask_folder(music=None):
    """In-game folder browser (drives, folders; the ones with a manifest marked) -> path or None (Esc).  Starts at the last folder
    used, else <game>/Photogrametry, else the game folder."""
    cur = ""
    try:
        cur = open(LAST, encoding="utf-8").read().strip()
    except OSError:
        pass
    if not os.path.isdir(cur):
        cur = os.path.join(ROOT, "Photogrametry") if os.path.isdir(os.path.join(ROOT, "Photogrametry")) else ROOT
    cur = os.path.abspath(cur)
    drives = []
    if os.name == "nt":                     # the drive bitmask: probing letters stalls on network / card-reader drives
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [f"{c}:\\" for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if mask >> i & 1 and c not in "AB"]
    typed, editing = cur, False
    listing, scroll, sel, t_open = None, 0, 0, time.time()
    while not rl.window_should_close():
        if music is not None:
            music.update()
        if listing is None:
            listing = [".."] + _subdirs(cur)
            marks = {n for n in listing[1:] if _has_manifest(os.path.join(cur, n))}
            here = _has_manifest(cur)
            try:
                n_img = sum(1 for e in os.scandir(cur) if e.name.lower().endswith((".png", ".jpg", ".jpeg")))
            except OSError:
                n_img = 0
            scroll, sel, typed = 0, 0, cur
        W, H = rl.get_screen_width(), rl.get_screen_height()
        pw, ph = min(W - 40, 1100), min(H - 40, 760)
        px, py = (W - pw) // 2, (H - ph) // 2
        rh = 30
        ly = py + 150
        rows = max(3, (ph - 150 - 80) // rh)
        m = rl.get_mouse_position()
        armed = time.time() - t_open > 0.25
        go_to, pick = None, False
        # keyboard: arrows / Enter / Backspace = up a level; typing edits the path (Enter goes there)
        if editing:
            while True:
                c = rl.get_char_pressed()
                if not c:
                    break
                if c >= 32:
                    typed += chr(c)
            if rl.is_key_pressed(rl.KEY_BACKSPACE) or rl.is_key_pressed_repeat(rl.KEY_BACKSPACE):
                typed = typed[:-1]
            if rl.is_key_pressed(rl.KEY_ENTER):
                editing = False
                if os.path.isdir(typed):
                    go_to = typed
            if rl.is_key_pressed(rl.KEY_ESCAPE):
                editing, typed = False, cur
        else:
            if rl.is_key_pressed(rl.KEY_ESCAPE):
                return None
            if rl.is_key_pressed(rl.KEY_DOWN) or rl.is_key_pressed_repeat(rl.KEY_DOWN):
                sel = min(len(listing) - 1, sel + 1)
            if rl.is_key_pressed(rl.KEY_UP) or rl.is_key_pressed_repeat(rl.KEY_UP):
                sel = max(0, sel - 1)
            if rl.is_key_pressed(rl.KEY_BACKSPACE):
                go_to = ".."
            if rl.is_key_pressed(rl.KEY_ENTER) and armed:
                go_to = listing[sel]
            if rl.is_key_pressed(rl.KEY_SPACE) and here:
                pick = True
            if sel < scroll:
                scroll = sel
            if sel >= scroll + rows:
                scroll = sel - rows + 1
        w = rl.get_mouse_wheel_move()
        if w:
            scroll = int(max(0, min(max(0, len(listing) - rows), scroll - w * 3)))
        rl.begin_drawing()
        rl.clear_background(rl.Color(12, 10, 16, 255))
        rl.draw_rectangle(px, py, pw, ph, PANEL)
        rl.draw_rectangle(px, py, pw, 4, PINK)
        font.draw_text("ФОТОГРАМЕТРИЈА: ИЗБЕРИ ПАПКА СО СНИМКИ", px + 20, py + 16, 28, PINK, bold="cond")
        # drives
        dx = px + 20
        for d in drives:
            if _button(dx, py + 58, 54, 28, d[:2], cur.upper().startswith(d[:2].upper()), 16) and armed:
                go_to = d
            dx += 60
        # path field (click to type)
        fy = py + 96
        over_f = px + 20 <= m.x < px + pw - 20 and fy <= m.y < fy + 34
        if over_f and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            editing = True
        rl.draw_rectangle(px + 20, fy, pw - 40, 34, rl.Color(40, 28, 44, 255) if not editing else rl.Color(70, 40, 70, 255))
        shown = typed + ("_" if editing and int(time.time() * 2) % 2 else "")
        while len(shown) > 8 and font.measure_text(shown, 18) > pw - 60:
            shown = "…" + shown[2:]
        font.draw_text(shown, px + 30, fy + 7, 18, rl.WHITE)
        # folders
        for i in range(scroll, min(len(listing), scroll + rows)):
            n = listing[i]
            y = ly + (i - scroll) * rh
            hot = px + 20 <= m.x < px + pw - 20 and y <= m.y < y + rh
            if hot and (rl.get_mouse_delta().x or rl.get_mouse_delta().y):
                sel = i
            if i == sel:
                rl.draw_rectangle(px + 20, y, pw - 40, rh - 2, rl.Color(70, 40, 70, 255))
            ok = n in marks
            font.draw_text(("↑  " if n == ".." else "▶  ") + n, px + 30, y + 5, 18, LOOK_COL["photo"] if ok else INK)
            if ok:
                font.draw_text("manifest ✓", px + pw - 140, y + 6, 15, LOOK_COL["photo"])
            if hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and armed:
                go_to = n
        if len(listing) > rows:
            font.draw_text(f"{scroll + 1}-{min(len(listing), scroll + rows)} / {len(listing)}  (тркало)", px + 20, ly + rows * rh + 2, 14, DIM)
        # status + buttons
        by = py + ph - 56
        st = (f"оваа папка: manifest ✓, {n_img} слики" if here else f"оваа папка нема manifest.csv ({n_img} слики)")
        font.draw_text(st, px + 20, by - 26, 16, LOOK_COL["photo"] if here else DIM)
        if _button(px + pw - 440, by, 260, 40, "ИЗБЕРИ ОВАА ПАПКА", here, 20) and armed and here:
            pick = True
        if _button(px + pw - 170, by, 150, 40, "НАЗАД (Esc)", False, 20) and armed:
            rl.end_drawing()
            return None
        font.draw_text("клик/Enter влези · Backspace горе · Space избери · клик на патеката за пишување", px + 20, by + 12, 14, DIM)
        rl.end_drawing()
        if pick:
            try:
                os.makedirs(os.path.dirname(LAST), exist_ok=True)
                with open(LAST, "w", encoding="utf-8") as f:
                    f.write(cur)
            except OSError:
                pass
            return cur
        if go_to is not None:
            nxt = os.path.dirname(cur) if go_to == ".." else os.path.abspath(os.path.join(cur, go_to))
            if os.path.isdir(nxt):
                cur, listing, t_open = nxt, None, time.time() - 0.2
    return None


def game_textures():
    """gl3d's facade textures -> ({name: Texture}, {name: (128,128,3) uint8}) - the fitter compares photos with the very tiles
    the game draws."""
    tex = gl3d.build_textures()
    arr = {}
    for name in set(pg.MATS.values()):
        t = tex.get(name)
        if t is None:
            continue
        img = rl.load_image_from_texture(t)
        rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
        a = np.frombuffer(rl.ffi.buffer(img.data, img.width * img.height * 4), np.uint8).reshape(img.height, img.width, 4)
        arr[name] = a[..., :3].copy()
        rl.unload_image(img)
    return tex, arr


def _v3(p):
    return rl.Vector3(float(p[0]), float(p[1]), float(p[2]))


class Scene:
    """Per-material models of all loaded buildings in one look (current, or one algorithm's fit).
    Each building's mesh parts are kept with the key they were made for (look, fit version, element switches), so a change
    rebuilds only the buildings it touches; the rebuild runs a slice per frame (step) and the old models stay up meanwhile."""

    def __init__(self, tex):
        self.tex = tex
        self.models = []
        self.parts = {}                      # building id -> (key, [(mat, pos, uv, col)])
        self.todo = []
        self.want = None
        self.stats = {"verts": 0, "blds": 0, "ms": 0.0, "rebuilt": 0}
        self.busy = 0.0                      # 0..1 while a rebuild runs
        self.focus, self.radius = None, 1e9
        self.shown_ids = None
        self.detail = 2                      # preview of the game's ДЕТАЛИ setting (0 low .. 2 high)

    def free(self):
        for m in self.models:
            gl3d.free_model(m)
        self.models = []

    def _parts(self, b, algo, opts, near=True):
        bw = pg.tools()
        lk = b.look(algo)
        if opts is not None:
            lk["opts"] = dict(opts, kit_on=False) if b.id in (opts.get("kit_off") or ()) else opts
        h = float(lk["h"])
        ring = [tuple(p) for p in b.ring]
        parts = []
        proc = bw.photo_facade(ring, h, lk, 0.0) if near and bw.photo_on(lk) else []   # far: the fitted box only
        tiles = bool(proc)
        if proc:
            parts += [(m_, tuple(g)) for m_, *g in proc]
        else:
            w = bw.walls(ring, h, lk["wallc"], None, lk.get("floor", 3.2), lk.get("bay", 3.4))
            if w:
                parts.append((lk["mat"], w))
            if near and bw.OSM_KIT and h >= 4:                 # the default world's element kit, as the world build makes it
                import archkit
                small = bool(lk.get("small"))
                ids = archkit.osm_ids(archkit.osm_archetype(lk["mat"], h, b.area, small, b.tags),
                                      ((int(b.c[0] * 13.7) * 92821) ^ int(b.c[1] * 7.3)) & 0x7FFFFFFF)
                parts += [(m_, tuple(g)) for m_, *g in bw.osm_kit(ring, h, lk["mat"], lk["wallc"], lk.get("floor", 3.2), lk.get("bay", 3.4),
                                                                  0.0, 0, b.area, small, ids)]
        roof = lk.get("roof") if tiles else None
        if not hasattr(b, "_tri"):
            try:
                b._tri = bw.triangulate(ring, [])
            except Exception:  # noqa: BLE001
                b._tri = ([], [])
        verts, tri = b._tri
        proof = bw.photo_roof(ring, h, lk, lk["roofc"], lk["wallc"]) if roof else None
        if proof:
            parts += [(m_, tuple(g)) for m_, *g in proof]
        if proof is not None and roof.get("kind") != "flat":
            pass
        elif lk.get("small") and lk.get("pitched", True) and h < 11:
            parts.append((bw.MAT_ROOF, bw.pyramid(ring, h, 1.8 + math.sqrt(b.area) * 0.12, lk["roofc"])))
        else:
            fp = bw.flat_poly(verts, tri, h, 6.0, [c * 1.02 for c in lk["roofc"]])
            if fp:
                parts.append((bw.MAT_ROOF, fp))
        out = []
        for mat, (pos, uv, col) in parts:
            pos = np.asarray(pos, np.float32).copy()
            pos[:, 1] += b.base
            out.append((mat, pos, np.asarray(uv, np.float32), np.asarray(col, np.uint8)))
        return out

    def _near(self, b):
        return self.focus is None or math.hypot(b.c[0] - self.focus[0], b.c[1] - self.focus[1]) < self.radius

    def _key(self, b, algo, opts, only):
        a = algo if (only is None or b.id in only) else None
        f = b.fits.get(a) if a else None
        near = self._near(b)
        ko = opts is not None and b.id in (opts.get("kit_off") or ())
        return (a, id(f), b.version, repr(sorted((k, v) for k, v in opts.items() if k != "kit_off")) if (opts is not None and f and near) else None,
                near, ko)

    def request(self, blds, algo, opts=None, only=None, focus=None, radius=1e9, view=None):
        """Ask for this look; step() does the work.  only: building ids that show the fit (proof), the rest the current look.
        focus / radius: buildings further away are plain fitted boxes; view: further than that nothing is built or drawn."""
        if focus is not None and view:
            blds = {k: b for k, b in blds.items() if math.hypot(b.c[0] - focus[0], b.c[1] - focus[1]) <= view}
        self.want = (blds, algo, opts, only)
        self.focus, self.radius = focus, radius
        todo = [b for b in blds.values() if self.parts.get(b.id, (None,))[0] != self._key(b, algo, opts, only)]
        if focus is not None:                       # nearest first
            todo.sort(key=lambda b: -math.hypot(b.c[0] - focus[0], b.c[1] - focus[1]))
        self.todo = todo
        self.t0, self.n0 = time.time(), len(self.todo)
        self.stats["rebuilt"] = 0
        if not self.todo:
            self._upload()

    def step(self, budget=0.025):
        """Rebuild for at most `budget` seconds; -> True when the models changed."""
        if self.want is None:
            return False
        blds, algo, opts, only = self.want
        t = time.time()
        while self.todo and time.time() - t < budget:
            b = self.todo.pop()
            self.parts[b.id] = (self._key(b, algo, opts, only), self._parts(b, algo if (only is None or b.id in only) else None, opts, self._near(b)))
            self.stats["rebuilt"] += 1
        self.busy = 1.0 - len(self.todo) / max(1, self.n0) if self.todo else 0.0
        if self.todo:
            return False
        self._upload()
        return True

    def rebuild_one(self, b, blds, algo, opts):
        """One building again, now (the ОЦЕНИ guard tries it with and without its kit)."""
        self.focus = self.focus if hasattr(self, "focus") else None
        self.parts[b.id] = (self._key(b, algo, opts, None), self._parts(b, algo, opts, self._near(b)))
        self.want, self.t0 = (getattr(self, "cur", None) or blds, algo, opts, None), time.time()
        self._upload()

    def build(self, blds, algo, opts=None, only=None):
        """All at once (tests)."""
        self.request(blds, algo, opts, only)
        while not self.step(10.0):
            pass

    def _upload(self):
        blds = self.cur = self.want[0]
        self.shown_ids = set(blds)
        acc = {}
        nv = 0
        skip = {18, 19} if self.detail < 1 else ({19} if self.detail < 2 else set())     # as the game's ДЕТАЛИ setting
        for bid in blds:
            for mat, pos, uv, col in self.parts.get(bid, (None, []))[1]:
                if mat in skip:
                    continue
                e = acc.setdefault(mat, ([], [], []))
                e[0].append(pos); e[1].append(uv); e[2].append(col)
                nv += len(pos)
        self.free()
        bw = pg.tools()
        names = {**pg.MATS, bw.MAT_ROOF: "roof", bw.MAT_SOLID: "white", **{m_: k for k, m_ in bw.MAT_SURF.items()},
                 bw.MAT_KIT2: "glaz", bw.MAT_KIT3: "glaz"}
        for mat, (P, U, C) in acc.items():
            m = gl3d.make_model(np.concatenate(P), np.concatenate(U), np.concatenate(C))
            if m is not None:
                gl3d.set_texture(m, self.tex.get(names.get(mat, "A"), self.tex["white"]))
                self.models.append(m)
        self.stats.update(verts=nv, blds=len(blds), ms=(time.time() - self.t0) * 1000)
        self.want = None
        self.busy = 0.0

    def draw(self):
        for m in self.models:
            rl.draw_model(m, rl.Vector3(0, 0, 0), 1.0, rl.WHITE)


class Orbit:
    def __init__(self, target):
        self.t = np.array(target, np.float64)
        self.yaw, self.pitch, self.dist = 0.6, 0.75, 220.0
        self.free = None                         # a capture: stand in its camera

    def cam(self):
        if self.free is not None:
            c = self.free
            fwd, _r, up = c.basis()
            e = c.eye()
            return rl.Camera3D(_v3(e), _v3(e + fwd * 10), _v3(up), float(c.fov), rl.CAMERA_PERSPECTIVE)
        cp = math.cos(self.pitch)
        e = self.t + self.dist * np.array([cp * math.sin(self.yaw), math.sin(self.pitch), cp * math.cos(self.yaw)])
        return rl.Camera3D(_v3(e), _v3(self.t), rl.Vector3(0, 1, 0), 50.0, rl.CAMERA_PERSPECTIVE)

    def update(self, over_ui):
        dt = rl.get_frame_time()
        d = rl.get_mouse_delta()
        shift = rl.is_key_down(rl.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KEY_RIGHT_SHIFT)
        moved = False
        if not over_ui and rl.is_mouse_button_down(rl.MOUSE_BUTTON_RIGHT) and not shift:
            self.yaw -= d.x * 0.006
            self.pitch = min(1.5, max(0.05, self.pitch + d.y * 0.006))
            moved = True
        fx, fz = -math.sin(self.yaw), -math.cos(self.yaw)          # forward on the ground
        rx, rz = math.cos(self.yaw), -math.sin(self.yaw)
        if not over_ui and (rl.is_mouse_button_down(rl.MOUSE_BUTTON_MIDDLE) or (shift and rl.is_mouse_button_down(rl.MOUSE_BUTTON_RIGHT))):
            k = self.dist * 0.0016
            self.t += np.array([-rx * d.x + fx * d.y, 0, -rz * d.x + fz * d.y]) * k
            moved = True
        w = rl.get_mouse_wheel_move()
        if w and not over_ui:
            self.dist = min(3000.0, max(8.0, self.dist * (0.88 ** w)))
            moved = True
        sp = self.dist * 0.9 * dt * (3 if shift else 1)
        for key, v in ((rl.KEY_W, (fx, 0, fz)), (rl.KEY_S, (-fx, 0, -fz)), (rl.KEY_D, (rx, 0, rz)), (rl.KEY_A, (-rx, 0, -rz)),
                       (rl.KEY_E, (0, 1, 0)), (rl.KEY_Q, (0, -1, 0))):
            if rl.is_key_down(key):
                self.t += np.array(v) * sp
                moved = True
        if moved:
            self.free = None


def _frustum(c, depth=14.0):
    fwd, right, up = c.basis()
    f = c.focal()
    e = c.eye()
    pts = [e + depth * (fwd + right * sx * c.W / 2 / f + up * sy * c.H / 2 / f) for sx, sy in ((-1, 1), (1, 1), (1, -1), (-1, -1))]
    return e, pts


def _quad_model(c, tex, depth=14.0):
    e, (tl, tr, br, bl) = _frustum(c, depth)
    pos = np.array([tl, bl, br, tl, br, tr], np.float32)
    uv = np.array([(0, 0), (0, 1), (1, 1), (0, 0), (1, 1), (1, 0)], np.float32)
    col = np.full((6, 4), 255, np.uint8)
    m = gl3d.make_model(np.concatenate([pos, pos[::-1]]), np.concatenate([uv, uv[::-1]]), np.concatenate([col, col]))
    gl3d.set_texture(m, tex)
    return m


def _button(x, y, w, h, label, on=False, sz=18):
    m = rl.get_mouse_position()
    hot = x <= m.x < x + w and y <= m.y < y + h
    rl.draw_rectangle(x, y, w, h, PINK if on else (rl.Color(70, 40, 70, 255) if hot else rl.Color(40, 28, 44, 255)))
    font.draw_text(label, x + (w - font.measure_text(label, sz, "cond")) // 2, y + (h - sz) // 2, sz, rl.WHITE, bold="cond")
    return hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT)


def _hot(x, y, w, h):
    m = rl.get_mouse_position()
    return x <= m.x < x + w and y <= m.y < y + h


def _toggle(x, y, w, label, val, sz=15, tip=None):
    """A tick box row -> the (maybe flipped) value."""
    hot = _hot(x, y, w, 22)
    if hot:
        rl.draw_rectangle(x, y, w, 22, rl.Color(60, 36, 62, 255))
    rl.draw_rectangle_lines(x + 2, y + 3, 16, 16, INK)
    if val:
        rl.draw_rectangle(x + 5, y + 6, 10, 10, PINK)
    font.draw_text(_fit(label, sz, w - 28), x + 24, y + 3, sz, INK if val else DIM)
    return (not val) if hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) else val


def _choice(x, y, w, label, options, val, names=None, sz=15, mark=False):
    """'label: value' button; left click = next option, right click = previous -> the value."""
    i = options.index(val) if val in options else 0
    nm = (names or {}).get(options[i], str(options[i]))
    hot = _hot(x, y, w, 24)
    rl.draw_rectangle(x, y, w, 24, rl.Color(70, 40, 70, 255) if hot else rl.Color(40, 28, 44, 255))
    font.draw_text(label, x + 8, y + 4, sz, PINK if mark else DIM)
    tw = font.measure_text(nm, sz, "cond")
    font.draw_text(nm, x + w - tw - 10, y + 4, sz, rl.WHITE, bold="cond")
    if hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
        return options[(i + 1) % len(options)]
    if hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_RIGHT):
        return options[(i - 1) % len(options)]
    return options[i]


def _fit(s, sz, w):
    while len(s) > 3 and font.measure_text(s, sz) > w:
        s = s[:-2] + "…" if not s.endswith("…") else s[:-2] + "…"
    return s


def _hms(s):
    s = int(max(0, s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


TABS = ["ГРАДИ", "ПОСТАВКИ", "ЕЛЕМЕНТИ", "ПРОБА", "ДНЕВНИК"]
SHOW = [("relief", "релјеф (испусти / вовлекувања)"), ("windows", "прозорци"), ("frames", "рамки и пречки"),
        ("blinds", "ролетни"), ("sills", "подпрозорници"), ("balconies", "балкони"), ("ac", "клима уреди"),
        ("bands", "венци и ленти"), ("ground", "приземје (свој изглед)"), ("steps", "повлечени катови"),
        ("opp", "спротивен ѕид од видениот"), ("cells", "бои по стан"), ("roofs", "покриви од сликата"),
        ("roof_extras", "оџаци и кабини"), ("eaves", "стреи")]


def run(aud=None, music=None, folder=None, osm_dir=None, frames=None, shot=None, test=""):
    """-> 'changed' when the game's choice of buildings changed (the world has to be built again), else None.
    frames / shot: headless test (run that many frames, save the last one)."""
    import archkit
    folder = folder or ask_folder(music)
    if not folder:
        return None
    osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
    W, H = rl.get_screen_width(), rl.get_screen_height()
    rl.rl_disable_backface_culling()                # walls are single quads (as in the game)

    def splash(msg):
        rl.begin_drawing()
        rl.clear_background(rl.Color(12, 10, 16, 255))
        font.draw_text(msg, 40, H // 2, 28, INK, bold="cond")
        rl.end_drawing()
    splash("ФОТОГРАМЕТРИЈА: текстури ...")
    tex, tex_np = game_textures()
    try:
        caps = pg.read_manifest(folder)
    except Exception as e:  # noqa: BLE001
        t0 = time.time()
        while time.time() - t0 < 4 and not rl.window_should_close():
            splash(f"Нема manifest.csv во {folder} ({e})")
        return None
    splash(f"ФОТОГРАМЕТРИЈА: {len(caps)} снимки, згради околу нив ...")
    blds = pg.load_city(osm_dir, caps)
    st, op = pg.load_settings(folder)                # engine settings + element switches, kept with the photo folder
    algo_i = 3                                     # ДЕТАЛИ: procedural windows, balconies, AC, roofs, surfaces
    look = True                                     # show the fitted look (else the current one)
    job, t_job = None, 0.0
    scene = Scene(tex)
    shown = None
    thumbs, quads = {}, {}
    cache = os.path.join(folder, pg.CACHE)
    os.makedirs(cache, exist_ok=True)
    thumb_q = [c for c in caps if c.exists]          # photo thumbnails load a few per frame: the window is up at once
    ok_caps = [c for c in caps if c.exists]
    cen = np.mean([[c.x, 0, c.z] for c in caps], 0)
    orb = Orbit(cen)
    sel = next((c for c in caps if c.exists), None)
    show_fr, show_ph, panel_mode, alpha = True, True, 0, 0.55
    tab, scr = 0, [0, 0, 0, 0, 10 ** 9]              # the left panel's tab and each tab's scroll
    proof = set()                                   # photos ticked for a proof run
    group = "сè"
    groups = ["сè"] + sorted({e[3] for e in archkit.ELEMENTS})
    opt_t = None                                     # an element switch changed: the scene follows a moment later
    focus = None                                     # full detail round this point (op["lod"] metres), boxes further out
    status, status_t = (0, True), 0.0
    for c in caps:                                  # headless test: --test "sel=0043,panel=2,free,tab=2,style=3,proof"
        if c.exists and ("sel=" + c.file[:4]) in test:
            sel = c
    if "panel=" in test:
        panel_mode = int(test.split("panel=")[1][0])
    if "tab=" in test:
        tab = int(test.split("tab=")[1][0])
    if "style=" in test:
        nm_ = list(archkit.STYLES)[int(test.split("style=")[1].split(",")[0])]
        op.update(style=nm_, kit=list(archkit.STYLES[nm_]), kit_scope="all")
    if "free" in test and sel is not None:
        orb.free = sel
    if "alpha=" in test:
        alpha = float(test.split("alpha=")[1].split(",")[0])
    rt = rl.load_render_texture(480, 270)
    lab_tex = {}
    msg, msg_t = "", 0.0
    changed = False
    n = 0

    def say(s):
        nonlocal msg, msg_t
        msg, msg_t = s, time.time()

    def start_job(only=None):
        nonlocal job, t_job, look
        pg.save_settings(folder, st, op)
        job = pg.Job(folder, algo, tex_np, osm_dir, state=(caps, blds), settings=st, only=only)
        job.start()
        t_job, look = time.time(), True
        say(("ПРОБА на " + str(len(only)) + " снимки" if only else "ГРАДЕЊЕ на сите снимки") + f" · {algo} · поставки зачувани")

    def opts_changed():
        nonlocal opt_t
        pg.save_settings(folder, st, op)
        opt_t = time.time()

    ev_log = []                                      # the ОЦЕНИ results (the log tab shows them with the job's)

    def elog(s_):
        ev_log.append(s_)
        if job is not None:
            job.log(s_)

    def grab(c):
        """The scene from the capture's own camera -> (270, 480, 3) uint8."""
        rl.begin_texture_mode(rt)
        rl.clear_background(rl.Color(150, 172, 196, 255))
        fwd, _r, up = c.basis()
        e = c.eye()
        rl.begin_mode_3d(rl.Camera3D(_v3(e), _v3(e + fwd * 10), _v3(up), float(c.fov), rl.CAMERA_PERSPECTIVE))
        scene.draw()
        rl.end_mode_3d()
        rl.end_texture_mode()
        im = rl.load_image_from_texture(rt.texture)
        rl.image_format(im, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
        a_ = np.frombuffer(rl.ffi.buffer(im.data, im.width * im.height * 4), np.uint8).reshape(im.height, im.width, 4)[::-1, :, :3].copy()
        rl.unload_image(im)
        return a_

    def photo_and_mask(c):
        """The photo (thumbnail) and the building pixels at the render's size, or None (no labels yet)."""
        import glob as glob_
        import segment
        labs = job.labels.get(c.file) if job is not None else None
        if labs is None:
            for lp in glob_.glob(os.path.join(cache, glob_.escape(os.path.splitext(c.file)[0]) + ".*.png")):
                if lp.endswith((".thumb.jpg", ".labels.png")):
                    continue
                labs = segment._cached(lp)
                if labs is not None:
                    break
        tp = os.path.join(cache, os.path.splitext(c.file)[0] + ".thumb.jpg")
        if labs is None or not os.path.exists(tp):
            return None
        ph = np.asarray(Image.open(tp).convert("RGB").resize((480, 270)), np.float64)
        mk = (labs == pg.L_BUILDING) & ~c.ui_mask()
        mk = np.asarray(Image.fromarray(mk.astype(np.uint8) * 255).resize((480, 270), Image.NEAREST)) > 127
        return ph, mk

    def target_mask(c, b, mk):
        """The building pixels inside the target building's projected box (its own pixels, not the neighbours')."""
        fwd, _r, up = c.basis()
        e = c.eye()
        cam_ = rl.Camera3D(_v3(e), _v3(e + fwd * 10), _v3(up), float(c.fov), rl.CAMERA_PERSPECTIVE)
        h_ = float(b.look(algo)["h"]) + 3.0
        xs, ys = [], []
        for x_, z_ in b.ring:
            for y_ in (b.base - 1.0, b.base + h_):
                q = np.array([x_, y_, z_]) - e
                if q @ fwd < 0.5:                          # behind the camera: the box reaches the image edge
                    continue
                p_ = rl.get_world_to_screen_ex(_v3((x_, y_, z_)), cam_, 480, 270)
                xs.append(p_.x)
                ys.append(p_.y)
        if not xs:
            return mk & False
        m2 = np.zeros_like(mk)
        x0, x1 = int(max(0, min(xs))), int(min(480, max(xs) + 1))
        y0, y1 = int(max(0, min(ys))), int(min(270, max(ys) + 1))
        m2[y0:y1, x0:x1] = True
        return mk & m2

    def tune(which):
        """Fit tuning by analysis-by-synthesis: for each photographed building, small changes of its height, storey height and
        floor-line phase, each kept only when the mean SSIM over its photos (own pixels, colour-matched) goes up.  The result goes
        to _photogram/tune.json (a new run applies it) and to the fit file (ПРИМЕНИ ВО ИГРАТА takes it)."""
        import json as json_
        import imgcmp
        if not look or algo != "detail":
            say("дотерувањето е за ДЕТАЛИ, фото изглед")
            return
        while scene.want is not None:
            scene.step(1.0)
        by_b = {}
        for c in which:
            b = blds.get(c.bid)
            if b is not None and (b.fits.get(algo) or {}).get("src") == "photo":
                by_b.setdefault(b.id, []).append(c)
        tp = os.path.join(cache, "tune.json")
        try:
            tj = json_.load(open(tp, encoding="utf-8"))
        except (OSError, ValueError):
            tj = {}
        tt = tj.setdefault(algo, {})
        gains = []
        for k_, (bid, cs) in enumerate(by_b.items()):
            b = blds[bid]
            views = []
            for c in cs:
                pm = photo_and_mask(c)
                if pm is not None:
                    mk = target_mask(c, b, pm[1])
                    if mk.sum() >= 400:
                        views.append((c, pm[0], mk))
            if not views:
                elog(f"зграда {bid}: нема доволно нејзини пиксели во сликите")
                continue
            base_f = b.fits[algo]

            def score_with(d):
                b.fits[algo] = pg.tuned(base_f, d) if d else base_f
                b.version += 1
                scene.rebuild_one(b, blds, algo, op)
                sc = [imgcmp.score(grab(c), ph, mk) for c, ph, mk in views]
                return float(np.mean([s_[1] for s_ in sc])), float(np.mean([s_[0] for s_ in sc]))
            s0, p0 = score_with(None)
            best, cur = (s0, p0), {"dh": 0.0, "kfh": 1.0, "dpv": 0.0}
            h0 = float(base_f.get("h", b.gen["h"]))
            steps = {"dh": 0.05 * h0, "kfh": 0.04, "dpv": 0.4}
            n_ev = 1
            for rnd_ in range(3):
                for key_ in ("dh", "kfh", "dpv"):
                    for sgn in (1, -1):
                        tr_ = dict(cur)
                        tr_[key_] = cur[key_] + sgn * steps[key_]
                        if abs(tr_["dh"]) > 0.2 * h0 or not 0.85 <= tr_["kfh"] <= 1.15:
                            continue
                        splash(f"ДОТЕРУВАЊЕ {k_ + 1}/{len(by_b)}: зграда {bid}, круг {rnd_ + 1}, {key_} {tr_[key_]:+.2f}  ·  SSIM {best[0]:.3f}")
                        sc = score_with(tr_)
                        n_ev += 1
                        if sc[0] > best[0] + 0.002:
                            best, cur = sc, tr_
                            break
                for key_ in steps:
                    steps[key_] /= 2
            if best[0] > s0 + 0.003:
                old = tt.get(str(bid)) or {}
                tot = {"dh": old.get("dh", 0.0) + cur["dh"], "kfh": old.get("kfh", 1.0) * cur["kfh"], "dpv": old.get("dpv", 0.0) + cur["dpv"]}
                tt[str(bid)] = {k2: round(v2, 3) for k2, v2 in tot.items()}
                b.fits[algo] = pg.tuned(base_f, cur)
                gains.append(best[0] - s0)
                elog(f"зграда {bid}: SSIM {s0:.3f} -> {best[0]:.3f}, PSNR {p0:.1f} -> {best[1]:.1f} dB  (висина {cur['dh']:+.2f} м, кат ×{cur['kfh']:.3f}, "
                     f"линии {cur['dpv']:+.2f} м; {n_ev} рендери, {len(views)} снимки)")
            else:
                b.fits[algo] = base_f
                elog(f"зграда {bid}: веќе најдобро (SSIM {s0:.3f}, {n_ev} рендери)")
            b.version += 1
            scene.rebuild_one(b, blds, algo, op)
        try:
            with open(tp + ".tmp", "w", encoding="utf-8") as f_:
                json_.dump(tj, f_, indent=1)
            os.replace(tp + ".tmp", tp)
            out_ = os.path.join(cache, f"fit_{algo}.json")
            if os.path.exists(out_) and gains:
                pg.write_fits(blds, algo, out_)
        except OSError as e:
            elog(f"дотерувањето не се зачува ({e})")
        elog(f"ДОТЕРУВАЊЕ: {len(by_b)} згради, подобрени {len(gains)}" + (f", просечно +{np.mean(gains):.3f} SSIM" if gains else ""))
        say(f"дотерани {len(gains)} од {len(by_b)} згради")

    def evaluate(which):
        """PSNR / SSIM of the render from each capture's camera against its colour-matched photo, building pixels only; the guard
        switches a building's kit off when the kit makes it less like its photos."""
        import archkit
        import imgcmp
        algo_ = algo if look else None
        while scene.want is not None:                 # the scene as it is set now
            scene.step(1.0)
        res = []
        for k_, c in enumerate(which):
            splash(f"ОЦЕНИ {k_ + 1}/{len(which)}: {c.file[:40]}")
            pm = photo_and_mask(c)
            if pm is None:
                elog(f"{c.file[:4]}: нема ознаки (прво изгради)")
                continue
            ph, mk = pm
            if mk.sum() < 500:
                elog(f"{c.file[:4]}: премалку згради во сликата")
                continue
            p0, s0, rm_ = imgcmp.score(grab(c), ph, mk)
            if os.environ.get("SK242_EVDBG"):              # debug: photo | matched render | mask
                Image.fromarray(np.concatenate([ph, rm_, np.repeat(mk[..., None] * 255.0, 3, 2)], 1).astype(np.uint8)).save(
                    os.path.join(os.environ["SK242_EVDBG"], c.file[:4] + "_ev.png"))
            note = ""
            b = blds.get(c.bid)
            f = b.fits.get(algo_) if (b is not None and algo_) else None
            if op.get("guard", True) and f and op.get("kit_on", True) and b.id not in op["kit_off"] \
                    and archkit.kit_ids(dict(f, h=b.look(algo_)["h"]), op):
                op["kit_off"].append(b.id)
                scene.rebuild_one(b, blds, algo_, op)
                p1, s1, _ = imgcmp.score(grab(c), ph, mk)
                if s1 > s0 + 0.005:
                    note = f" · стилот ја влошуваше ({s1:.3f} без него): исклучен за зградата"
                    p0, s0 = p1, s1
                else:
                    op["kit_off"].remove(b.id)
                    scene.rebuild_one(b, blds, algo_, op)
                    note = f" · стилот останува (без него {s1:.3f})"
            c.score = (p0, s0)
            res.append((p0, s0))
            elog(f"{c.file[:4]}: PSNR {p0:.1f} dB · SSIM {s0:.3f}" + (" · СЛАБО" if s0 < 0.25 else "") + note)
        if res:
            elog(f"ОЦЕНА: {len(res)} снимки · просек PSNR {np.mean([r_[0] for r_ in res]):.1f} dB · SSIM {np.mean([r_[1] for r_ in res]):.3f}"
                 f" · слаби {sum(1 for r_ in res if r_[1] < 0.25)} · стил исклучен на {len(op['kit_off'])} згради")
            pg.save_settings(folder, st, op)
        say(f"оценети {len(res)} снимки" + (f" · SSIM {np.mean([r_[1] for r_ in res]):.3f}" if res else ""))

    while not rl.window_should_close():
        n += 1
        if music is not None:
            music.update()
        t_q = time.time()
        while thumb_q and time.time() - t_q < 0.012:
            c = thumb_q.pop(0)
            p = os.path.join(cache, os.path.splitext(c.file)[0] + ".thumb.jpg")
            try:
                if not os.path.exists(p):
                    Image.open(c.path).convert("RGB").resize((480, int(480 * c.H / max(1, c.W)))).save(p, quality=85)
                thumbs[c.file] = rl.load_texture(p)
            except OSError:
                pass
        W, H = rl.get_screen_width(), rl.get_screen_height()
        lw, pw = 390, 500                                       # left / right panel widths
        m = rl.get_mouse_position()
        over_ui = m.x < lw or (sel is not None and m.x > W - pw)
        if rl.is_key_pressed(rl.KEY_ESCAPE):
            if orb.free is not None:
                orb.free = None
            else:
                break
        algo = pg.ALGOS[algo_i][0]
        running = job is not None and not job.done
        shift = rl.is_key_down(rl.KEY_LEFT_SHIFT) or rl.is_key_down(rl.KEY_RIGHT_SHIFT)
        for i, k in enumerate((rl.KEY_ONE, rl.KEY_TWO, rl.KEY_THREE, rl.KEY_FOUR)):
            if rl.is_key_pressed(k) and i < len(pg.ALGOS):
                algo_i = i
        for i, k in enumerate((rl.KEY_F1, rl.KEY_F2, rl.KEY_F3, rl.KEY_F4, rl.KEY_F5)):
            if rl.is_key_pressed(k):
                tab = i
        if rl.is_key_pressed(rl.KEY_F):
            show_fr = not show_fr
        if rl.is_key_pressed(rl.KEY_T):
            show_ph = not show_ph
        if rl.is_key_pressed(rl.KEY_G):
            look = not look
        if rl.is_key_pressed(rl.KEY_M):
            panel_mode = (panel_mode + 1) % 3
        if rl.is_key_pressed(rl.KEY_LEFT_BRACKET):
            alpha = max(0.0, alpha - 0.1)
        if rl.is_key_pressed(rl.KEY_RIGHT_BRACKET):
            alpha = min(1.0, alpha + 0.1)
        if rl.is_key_pressed(rl.KEY_TAB) and ok_caps:
            sel = ok_caps[(ok_caps.index(sel) + 1) % len(ok_caps)] if sel in ok_caps else ok_caps[0]
            orb.t = np.array([sel.x, sel.y, sel.z])
        if sel is not None and rl.is_key_pressed(rl.KEY_V):
            orb.free = None if orb.free is sel else sel
        if sel is not None and rl.is_key_pressed(rl.KEY_K):
            proof ^= {sel.file}
        if rl.is_key_pressed(rl.KEY_R) and not running:
            start_job(set(proof) if shift and proof else None)
        if running and rl.is_key_pressed(rl.KEY_SPACE):
            job.pause = not job.pause
        orb.update(over_ui)
        cam = orb.cam()
        # pick a capture: the nearest camera apex / photo centre on screen (Shift = tick it for a proof run)
        if not over_ui and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and show_fr:
            best = (24.0, None)
            for c in ok_caps:
                e, pts = _frustum(c)
                for p in (e, np.mean(pts, 0)):
                    s = rl.get_world_to_screen(_v3(p), cam)
                    dd = math.hypot(s.x - m.x, s.y - m.y)
                    if dd < best[0]:
                        best = (dd, c)
            if best[1] is not None:
                sel = best[1]
                if shift:
                    proof ^= {sel.file}
        # the meshes follow the job (twice a second), the look switch and the element switches (a slice per frame)
        lod, view = op.get("lod", 400.0), op.get("view", 500.0)
        here = orb.free.eye() if orb.free is not None else orb.t          # where the camera is / looks
        if focus is None or math.hypot(here[0] - focus[0], here[2] - focus[1]) > min(lod, view, 1e6) / 4:
            focus = (float(here[0]), float(here[2]))
        want = (algo if look else None, job.version if job else 0, id(job), focus, lod, view)
        if opt_t is not None and time.time() - opt_t > 0.25:
            opt_t, shown = None, None
        if want != shown and (n % 30 == 0 or want[0] != (shown or (None,))[0] or not running) and opt_t is None:
            scene.request(blds, want[0], op, None, focus, lod, view if view < 1e8 else None)
            shown = want
        scene.step(0.02)
        if sel is not None and sel.file in quads and quads[sel.file][1] != (sel.dyaw, sel.dpitch):
            gl3d.free_model(quads.pop(sel.file)[0])
        if time.time() - status_t > 1.0:                   # the stored job (resume / settings changed), once a second
            status, status_t = pg.job_status(folder, algo, st), time.time()
        # ---- draw
        rl.begin_drawing()
        rl.clear_background(rl.Color(150, 172, 196, 255))
        rl.begin_mode_3d(cam)
        scene.draw()
        vis = scene.shown_ids
        for b in blds.values():                                   # fitted outlines: green = from photos, blue = from neighbours
            f = b.fits.get(algo) if look else None
            if not f or (vis is not None and b.id not in vis):
                continue
            col = LOOK_COL["photo" if f.get("src") == "photo" else "inferred"]
            if f.get("src") != "photo" and orb.dist > 900:
                continue
            hh = b.base + float(b.look(algo)["h"]) + 0.3
            r = b.ring
            for i in range(len(r)):
                rl.draw_line_3d(rl.Vector3(r[i][0], hh, r[i][1]), rl.Vector3(r[(i + 1) % len(r)][0], hh, r[(i + 1) % len(r)][1]), col)
        if show_fr:
            for c in ok_caps:
                if focus is not None and c is not sel and math.hypot(c.x - focus[0], c.z - focus[1]) > op.get("view", 500.0):
                    continue
                e, pts = _frustum(c)
                col = rl.YELLOW if c is sel else (rl.Color(60, 230, 255, 255) if c.file in proof else
                                                  (rl.Color(255, 120, 200, 255) if c.status else rl.Color(255, 255, 255, 200)))
                for p in pts:
                    rl.draw_line_3d(_v3(e), _v3(p), col)
                for i in range(4):
                    rl.draw_line_3d(_v3(pts[i]), _v3(pts[(i + 1) % 4]), col)
                if show_ph and c.file in thumbs and orb.free is not c:
                    if c.file not in quads:
                        quads[c.file] = (_quad_model(c, thumbs[c.file]), (c.dyaw, c.dpitch))
                    rl.draw_model(quads[c.file][0], rl.Vector3(0, 0, 0), 1.0, rl.WHITE)
                if c is sel and c.bid in blds:                       # line to its target building
                    b = blds[c.bid]
                    rl.draw_line_3d(_v3(e), rl.Vector3(b.c[0], b.base + 2, b.c[1]), rl.YELLOW)
        rl.end_mode_3d()
        if orb.free is not None and orb.free.file in thumbs:        # the photo over the scene seen from its own camera
            c = orb.free
            t = thumbs[c.file]
            sw = min(W, H * c.W / c.H)
            sh = sw * c.H / c.W
            rl.draw_texture_pro(t, rl.Rectangle(0, 0, t.width, t.height), rl.Rectangle((W - sw) / 2, (H - sh) / 2, sw, sh),
                                rl.Vector2(0, 0), 0, rl.Color(255, 255, 255, int(255 * alpha)))
        # ---- left panel: tabs
        rl.draw_rectangle(0, 0, lw, H, PANEL)
        y = 10
        font.draw_text("ФОТОГРАМЕТРИЈА", 16, y, 28, PINK, bold="cond")
        font.draw_text(_fit(os.path.basename(folder.rstrip("/\\")), 14, 150), lw - 166, y + 10, 14, DIM)
        y += 38
        tw_ = (lw - 16) // len(TABS)
        for i, tn in enumerate(TABS):
            if _button(8 + i * tw_, y, tw_ - 3, 26, tn, i == tab, 13):
                tab = i
        y += 34
        wheel = rl.get_mouse_wheel_move() if m.x < lw else 0.0
        bottom = H - 118                                         # the always-there progress block starts here
        changed_res = not status[1]
        if tab == 0:                                            # ---- build
            font.draw_text("АЛГОРИТАМ (1-4)", 16, y, 16, INK, bold="cond")
            y += 22
            for i, (k, name, note) in enumerate(pg.ALGOS):
                have = sum(1 for b in blds.values() if k in b.fits)
                if _button(16, y, lw - 32, 28, f"{i + 1}  {name}" + (f"  ({have})" if have else ""), i == algo_i, 17):
                    algo_i = i
                y += 30
                if i == algo_i:
                    font.draw_text(_fit(note, 13, lw - 40), 20, y, 13, DIM)
                    y += 17
            y += 6
            hw = (lw - 40) // 2
            if not running:
                if _button(16, y, hw, 38, "ИЗГРАДИ СЕ (R)", False, 18):
                    start_job()
                if _button(24 + hw, y, hw, 38, f"ПРОБА ({len(proof)}) Shift+R", bool(proof), 16) and proof:
                    start_job(set(proof))
            else:
                if _button(16, y, hw, 38, "ПРОДОЛЖИ (Space)" if job.pause else "ПАУЗА (Space)", job.pause, 16):
                    job.pause = not job.pause
                if _button(24 + hw, y, hw, 38, "СТОП (се чува)" if not job.stop else "ЗАСТАНУВА ...", job.stop, 16):
                    job.stop, job.pause = True, False
            y += 44
            nst, same = status
            if nst:
                font.draw_text((f"зачувани {nst} снимки: следното градење продолжува" if same else
                                f"зачувани {nst} снимки, но поставките се сменети: почнува одново"), 16, y, 13,
                               LOOK_COL["photo"] if same else PINK)
            else:
                font.draw_text("нема зачувано: градењето почнува од почеток", 16, y, 13, DIM)
            y += 18
            if nst and _button(16, y, lw - 32, 26, "ИСЧИСТИ ЗАЧУВАНО (пресметај сè одново)", False, 14) and not running:
                pg.clear_job(folder, algo, poses=False)
                status_t = 0.0
                say("зачуваните резултати се избришани (позициите на камерите остануваат)")
            y += 32
            if _button(16, y, hw, 28, "ПРИКАЖИ: " + ("ФОТО" if look else "ТЕКОВНИ") + " (G)", look, 14):
                look = not look
            if _button(24 + hw, y, hw, 28, "ПРИМЕНИ ВО ИГРАТА", False, 14):
                try:
                    pg.apply_to_game(folder, algo, osm_dir, op)
                    say(f"photogram.json <- {algo} + елементи ({len(op['kit'])} во комплетот): важи по следното градење")
                    changed = True
                except OSError as e:
                    say(f"нема готов резултат за {algo} ({e.strerror})")
            y += 34
            if _button(16, y, hw, 28, "ОЦЕНИ СЛИЧНОСТ", False, 14) and not running:
                evaluate([c for c in ok_caps if c.status or c.file in proof])
            if _button(24 + hw, y, hw, 28, "ДОТЕРАЈ ПО СЛИКИТЕ", False, 14) and not running:
                tune([c for c in ok_caps if c.file in proof] or [c for c in ok_caps if c.status])
                evaluate([c for c in ok_caps if c.file in proof] or [c for c in ok_caps if c.status])
            y += 32
            v = _toggle(16, y, lw - 32, "чувар: исклучи стил што ја влошува сличноста", op["guard"], 13)
            if v != op["guard"]:
                op["guard"] = v
                pg.save_settings(folder, st, op)
            v = op.get("autotune", True)
            v2 = _toggle(16, y + 22, lw - 32, "по проба: дотерај висина / катови по сликите", v, 13)
            if v2 != v:
                op["autotune"] = v2
                pg.save_settings(folder, st, op)
            y += 50
            stg = pg.enabled(osm_dir)
            lab = "ЗГРАДИ ВО ИГРАТА: " + {None: "ТЕКОВНИ (нема фото)", True: "ФОТО", False: "ТЕКОВНИ"}[stg]
            if _button(16, y, lw - 32, 28, lab, bool(stg), 14) and stg is not None:
                pg.set_enabled(not stg, osm_dir)
                changed = True
                say("се менува по следното градење на светот")
            y += 38
            nphoto = sum(1 for b in blds.values() if b.fits.get(algo, {}).get("src") == "photo")
            ninf = sum(1 for b in blds.values() if b.fits.get(algo, {}).get("src") == "inferred")
            for ln in (f"згради {len(blds)} · од фото {nphoto} · од соседи {ninf}",
                       f"снимки {len(ok_caps)} · обработени {sum(1 for c in ok_caps if c.status)} · за проба {len(proof)}",
                       f"сцена: {scene.stats['verts'] / 1e6:.2f} M темиња, {scene.stats['ms'] / 1000:.1f} с"
                       + (f" · обновува {int(scene.busy * 100)}%" if scene.want is not None else ""),
                       f"комплет: {len(op['kit'])} елементи · {op['style']}" + (" · авто" if op["kit_auto"] else "")):
                font.draw_text(ln, 16, y, 14, INK)
                y += 19
            if job is not None:
                y += 6
                for ln in job.log_lines[-max(0, (bottom - y) // 16):]:
                    font.draw_text(_fit(ln, 13, lw - 32), 16, y, 13, DIM)
                    y += 16
        elif tab == 1:                                          # ---- engine settings
            nst, same = status
            font.draw_text("ПОСТАВКИ НА ПРЕСМЕТКАТА", 16, y, 16, INK, bold="cond")
            y += 22
            font.draw_text("* = менува резултати (зачуваното не важи)", 16, y, 13, PINK if changed_res else DIM)
            y += 20
            hw3 = (lw - 44) // 3
            for i, (pn, pv_) in enumerate((("БРЗО", dict(res=8.0, dist=120.0, pose="file", priors=True, sym=True, fuse=False, min_px=3000)),
                                           ("УРАМНОТЕЖЕНО", dict(res=12.0, dist=200.0, pose="fast", priors=True, sym=True, fuse=True, min_px=1500)),
                                           ("НАЈДОБРО", dict(res=16.0, dist=300.0, pose="full", priors=True, sym=True, fuse=True, min_px=600)))):
                cur = all(st.get(k) == v for k, v in pv_.items())
                if _button(16 + i * (hw3 + 6), y, hw3, 26, pn, cur, 13) and not running:
                    st.update(pv_)
                    pg.save_settings(folder, st, op)
                    status_t = 0.0
                    say(f"поставки: {pn}")
            y += 32
            ncpu = os.cpu_count() or 2
            rows = [("res", "резолуција на фасадата", [8.0, 10.0, 12.0, 16.0], {8.0: "8 px/м брзо", 10.0: "10 px/м", 12.0: "12 px/м", 16.0: "16 px/м фино"}),
                    ("dist", "ѕидови до", [80.0, 120.0, 160.0, 200.0, 300.0], {v: f"{v:.0f} м" for v in (80.0, 120.0, 160.0, 200.0, 300.0)}),
                    ("workers", "процеси", [0, 1, 2, 4, 6, 8, 12, 16], {0: f"авто ({max(1, min(12, ncpu - 1))})", **{v: str(v) for v in (1, 2, 4, 6, 8, 12, 16)}}),
                    ("pose", "позиција на камерата", ["fast", "full", "file"], {"fast": "брзо барање", "full": "целосна мрежа (бавно)", "file": "од фајлот"}),
                    ("seg", "сегментација", ["auto", "segformer", "simple"], {"auto": "авто", "segformer": "SegFormer (GPU)", "simple": "едноставна (брза)"}),
                    ("min_px", "најмалку пиксели на ѕид", [600, 1500, 3000, 6000], {v: str(v) for v in (600, 1500, 3000, 6000)})]
            for k, lab, opts_, names in rows:
                v = _choice(16, y, lw - 32, lab + (" *" if k in pg.RESULT_KEYS else ""), opts_, st[k], names, 14, k in pg.RESULT_KEYS and changed_res)
                if v != st[k] and not running:
                    st[k] = v
                    pg.save_settings(folder, st, op)
                    status_t = 0.0
                y += 28
            for k, lab in (("priors", "длабочина од вообичаениот ред (кога не се гледа) *"), ("sym", "симетрија / повторување за невидените колони *"),
                           ("fuse", "спој ги сите погледи на ѕидот")):
                v = _toggle(16, y, lw - 32, lab, st[k], 14)
                if v != st[k] and not running:
                    st[k] = v
                    pg.save_settings(folder, st, op)
                    status_t = 0.0
                y += 24
            y += 8
            font.draw_text((f"зачувани {nst} снимки · " + ("исти поставки: продолжува" if same else "сменети поставки: почнува одново")) if nst
                           else "нема зачувано", 16, y, 14, LOOK_COL["photo"] if (same and nst) else (PINK if nst else DIM))
            y += 22
            hw = (lw - 40) // 2
            if _button(16, y, hw, 28, "ИСЧИСТИ ЗАЧУВАНО", False, 14) and not running:
                pg.clear_job(folder, algo, poses=False)
                status_t = 0.0
                say("зачуваното е избришано")
            if _button(24 + hw, y, hw, 28, "+ ПОЗИЦИИ НА КАМЕРИ", False, 14) and not running:
                pg.clear_job(folder, algo, poses=True)
                status_t = 0.0
                say("зачуваното и позициите на камерите се избришани")
            y += 34
            if _button(16, y, lw - 32, 28, "ВРАТИ ПОЧЕТНИ ПОСТАВКИ", False, 14) and not running:
                st = dict(pg.SETTINGS)
                pg.save_settings(folder, st, op)
                status_t = 0.0
            y += 36
            if running:
                font.draw_text("за време на градењето поставките се заклучени", 16, y, 13, PINK)
        elif tab == 2:                                          # ---- elements: what the numbers become (no new fit needed)
            font.draw_text("ПРИКАЗ (важи веднаш, без ново градење)", 16, y, 15, INK, bold="cond")
            y += 22
            cw2 = (lw - 32) // 2
            for j, (k, lab) in enumerate(SHOW):
                v = _toggle(16 + (j % 2) * cw2, y + (j // 2) * 22, cw2 - 4, lab, op[k], 13)
                if v != op[k]:
                    op[k] = v
                    opts_changed()
            y += (len(SHOW) + 1) // 2 * 22 + 6
            v = _choice(16, y, cw2 - 4, "без слика", ["full", "lite", "none"], op["inferred"], {"full": "сè", "lite": "лесно", "none": "обични"}, 13)
            if v != op["inferred"]:
                op["inferred"] = v
                opts_changed()
            v = _choice(16, y + 56, lw - 32, "приказ како во играта (ДЕТАЛИ)", [0, 1, 2], scene.detail, {0: "ниско", 1: "средно", 2: "високо"}, 13)
            if v != scene.detail:
                scene.detail = v
                if scene.want is None:
                    scene.want = (getattr(scene, "cur", None) or blds, None, None, None)
                    scene.t0 = time.time()
                    scene._upload()
            views = [250.0, 500.0, 800.0, 1500.0, 1e9]
            v = _choice(16, y + 84, lw - 32, "вчитај згради до (од камерата)", views, min(views, key=lambda s_: abs(s_ - op["view"])),
                        {v_: (f"{v_:.0f} м" if v_ < 1e8 else "сите") for v_ in views}, 13)
            if v != op["view"]:
                op["view"] = v
                opts_changed()
            lods = [150.0, 250.0, 400.0, 700.0, 1e9]
            v = _choice(16, y + 28, lw - 32, "детали до (подалеку само кутии)", lods, min(lods, key=lambda s_: abs(s_ - op["lod"])),
                        {v_: (f"{v_:.0f} м" if v_ < 1e8 else "секаде") for v_ in lods}, 13)
            if v != op["lod"]:
                op["lod"] = v
                opts_changed()
            sats = [0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0]
            v = _choice(20 + cw2, y, cw2 - 4, "бои", sats, min(sats, key=lambda s_: abs(s_ - op["sat"])), {s_: f"×{s_:.1f}" for s_ in sats}, 13)
            if abs(v - op["sat"]) > 1e-6:
                op["sat"] = v
                opts_changed()
            y += 114
            font.draw_text(f"КОМПЛЕТ ЕЛЕМЕНТИ ({len(archkit.ELEMENTS)})", 16, y, 15, INK, bold="cond")
            y += 22
            v = _toggle(16, y, cw2 - 4, "комплетот вклучен", op["kit_on"], 13)
            if v != op["kit_on"]:
                op["kit_on"] = v
                opts_changed()
            v = _toggle(20 + cw2, y, cw2 - 4, "авто од сликата", op["kit_auto"], 13)
            if v != op["kit_auto"]:
                op["kit_auto"] = v
                opts_changed()
            y += 24
            styles = list(archkit.STYLES)
            v = _choice(16, y, lw - 32, "стил", styles, op["style"] if op["style"] in styles else styles[0], None, 13)
            if v != op["style"]:
                op["style"], op["kit"] = v, list(archkit.STYLES[v])
                opts_changed()
            y += 28
            scopes = ["blocks", "houses", "flat", "photo", "all"] + list(archkit.ARCHETYPES)
            v = _choice(16, y, cw2 - 4, "на", scopes, op["kit_scope"], {"blocks": "блокови 4+", "houses": "куќи", "flat": "рамни покриви",
                                                                         "photo": "само од фото", "all": "сите", **archkit.ARCHETYPES}, 13)
            if v != op["kit_scope"]:
                op["kit_scope"] = v
                opts_changed()
            group = _choice(20 + cw2, y, cw2 - 4, "група", groups, group, None, 13)
            y += 28
            items = [e for e in archkit.ELEMENTS if group == "сè" or e[3] == group]
            font.draw_text(f"избрани {len(op['kit'])} · прикажани {len(items)} · 0-3 ниво", 16, y, 13, DIM)
            if _button(lw - 96, y - 2, 80, 20, "ИСЧИСТИ", False, 12) and op["kit"]:
                op["kit"] = []
                opts_changed()
            y += 20
            rows_ = max(1, (bottom - y) // 21)
            scr[2] = int(max(0, min(max(0, len(items) - rows_), scr[2] - wheel * 4)))
            for e in items[scr[2]:scr[2] + rows_]:
                on_ = e[0] in op["kit"]
                v = _toggle(16, y, lw - 32, f"{archkit.TIER[e[1]]}· " + e[2], on_, 13)
                if v != on_:
                    op["kit"] = [i for i in op["kit"] if i != e[0]] + ([e[0]] if v else [])
                    opts_changed()
                y += 21
        elif tab == 3:                                          # ---- proof: tick photos, run only those
            font.draw_text("ПРОБА НА ИЗБРАНИ СНИМКИ", 16, y, 16, INK, bold="cond")
            y += 22
            for ln in ("штиклирај снимки (K / Shift+клик на рамката / тука),", "па ПРОБА: се градат само зградите што тие ги гледаат.",
                       "Резултатите се чуваат и целото градење ги користи."):
                font.draw_text(ln, 16, y, 13, DIM)
                y += 16
            y += 4
            hw = (lw - 44) // 3
            if _button(16, y, hw, 26, "ВИДЛИВИ", False, 13):
                for c in ok_caps:
                    s = rl.get_world_to_screen(_v3(c.eye()), cam)
                    if lw < s.x < W - pw and 0 < s.y < H:
                        proof.add(c.file)
            if _button(22 + hw, y, hw, 26, "НЕОБРАБОТЕНИ", False, 13):
                proof |= {c.file for c in ok_caps if not c.status}
            if _button(28 + 2 * hw, y, hw, 26, "ИСЧИСТИ", False, 13):
                proof = set()
            y += 32
            if _button(16, y, lw - 32, 34, f"ПРОБАЈ НА {len(proof)} СНИМКИ (Shift+R)", bool(proof), 17) and proof and not running:
                start_job(set(proof))
            y += 40
            if _button(16, y, lw - 32, 26, f"ОЦЕНИ ГИ ИЗБРАНИТЕ (PSNR / SSIM со сликата)", False, 13) and proof and not running:
                evaluate([c for c in ok_caps if c.file in proof])
            y += 32
            rows_ = max(1, (bottom - y) // 21)
            scr[3] = int(max(0, min(max(0, len(ok_caps) - rows_), scr[3] - wheel * 4)))
            for c in ok_caps[scr[3]:scr[3] + rows_]:
                on_ = c.file in proof
                if c is sel:
                    rl.draw_rectangle(14, y, lw - 28, 21, rl.Color(80, 70, 20, 255))
                v = _toggle(16, y, 190, _fit(c.file, 13, 160), on_, 13)
                if v != on_:
                    proof ^= {c.file}
                if _hot(210, y, lw - 226, 21) and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
                    sel = c
                    orb.t = np.array([c.x, c.y, c.z])
                sc_ = getattr(c, "score", None)
                font.draw_text(_fit((f"SSIM {sc_[1]:.2f} · {sc_[0]:.1f} dB" if sc_ else c.status) or "—", 12, lw - 230), 212, y + 4, 12,
                               (PINK if sc_[1] < 0.25 else LOOK_COL["photo"]) if sc_ else (LOOK_COL["photo"] if c.status else DIM))
                y += 21
        else:                                                   # ---- log + timings
            font.draw_text("ДНЕВНИК", 16, y, 16, INK, bold="cond")
            y += 22
            if job is not None and job.stats:
                s_ = job.stats
                tt = sum(s_.get(k, 0.0) for k in ("colour", "pose", "walls", "analyse")) or 1.0
                font.draw_text(f"нови {s_.get('fresh', 0)} · од зачуваното {s_.get('stored', 0)} · сегментација {s_.get('seg', 0.0):.1f} с"
                               + (f" · вкупно {s_['total']:.1f} с" if "total" in s_ else ""), 16, y, 13, INK)
                y += 17
                x_ = 16
                for k, nm_ in (("colour", "боја"), ("pose", "камера"), ("walls", "ѕидови"), ("analyse", "анализа")):
                    v_ = s_.get(k, 0.0)
                    wbar = int((lw - 32) * v_ / tt)
                    rl.draw_rectangle(x_, y, max(1, wbar), 12, {"colour": rl.Color(230, 200, 60, 255), "pose": PINK, "walls": rl.Color(90, 170, 255, 255),
                                                               "analyse": LOOK_COL["photo"]}[k])
                    x_ += wbar
                y += 15
                font.draw_text("  ".join(f"{nm_} {s_.get(k, 0.0):.1f} с" for k, nm_ in (("colour", "боја"), ("pose", "камера"), ("walls", "ѕидови"),
                                                                                        ("analyse", "анализа"))) + "  (процесорско време)", 16, y, 12, DIM)
                y += 18
            lines = job.log_lines if job is not None else ev_log
            rows_ = max(1, (bottom - y) // 15)
            follow = scr[4] >= max(0, len(lines) - rows_) - 1
            scr[4] = int(max(0, min(max(0, len(lines) - rows_), scr[4] - wheel * 5)))
            if follow and not wheel:
                scr[4] = max(0, len(lines) - rows_)
            for ln in lines[scr[4]:scr[4] + rows_]:
                font.draw_text(_fit(ln, 12, lw - 30), 14, y, 12, DIM)
                y += 15
            if not lines:
                font.draw_text("уште нема градење во оваа сесија", 16, y, 13, DIM)
        # ---- always: progress, ETA, keys
        y = bottom + 6
        if job is not None:
            frac = 1.0 if job.done else job.frac
            rl.draw_rectangle(16, y, lw - 32, 10, rl.Color(60, 50, 64, 255))
            rl.draw_rectangle(16, y, int((lw - 32) * frac), 10, PINK if not job.error else rl.RED)
            el = (time.time() - t_job) if not job.done else job.stats.get("total", 0.0)
            eta = el * (1 - frac) / frac if 0.02 < frac < 1 and not job.pause else None
            font.draw_text(f"{int(frac * 100)}%  · {_hms(el)}" + (f" · остануваат ~{_hms(eta)}" if eta else "")
                           + (" · ПРОБА" if job.only else ""), 16, y + 14, 13, INK)
            font.draw_text(_fit(job.error or job.step, 14, lw - 32), 16, y + 32, 14, rl.RED if job.error else INK)
        if scene.want is not None:
            rl.draw_rectangle(16, y + 52, int((lw - 32) * scene.busy), 4, LOOK_COL["inferred"])
        font.draw_text("десно влечи · средно/Shift поместување · тркало зум · WASD/QE", 16, H - 46, 12, DIM)
        font.draw_text("F рамки · T слики · V камера · K проба · R гради · F1-F5 табови", 16, H - 28, 12, DIM)
        # ---- right panel: the picked capture
        if sel is not None:
            x0 = W - pw
            rl.draw_rectangle(x0, 0, pw, H, PANEL)
            yy = 14
            font.draw_text(sel.file[:44] + ("  [ПРОБА]" if sel.file in proof else ""), x0 + 10, yy, 16, PINK, bold="cond")
            yy += 22
            font.draw_text(f"зграда {sel.bid}  ·  {sel.yaw:.0f}° / {sel.pitch:+.0f}° / fov {sel.fov:.0f}°"
                           + (f"  ·  поправка {sel.dyaw:+.1f}° {sel.dpitch:+.1f}°" if sel.dyaw or sel.dpitch else ""), x0 + 10, yy, 14, DIM)
            yy += 22
            th = thumbs.get(sel.file)
            iw = pw - 20
            ih = int(iw * 9 / 16) if th is None else int(iw * th.height / th.width)
            modes = ["СЛИКА", "ОЗНАКИ", "ИГРА ОД ИСТАТА ТОЧКА"]
            for i, md in enumerate(modes):
                if _button(x0 + 10 + i * (iw // 3), yy, iw // 3 - 4, 24, md, panel_mode == i, 14):
                    panel_mode = i
            yy += 30
            if th is not None:
                if panel_mode == 0:
                    rl.draw_texture_pro(th, rl.Rectangle(0, 0, th.width, th.height), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0, rl.WHITE)
                elif panel_mode == 1:
                    labs = job.labels.get(sel.file) if job else None
                    if labs is not None and sel.file not in lab_tex:
                        small = LABEL_RGB[np.minimum(labs[::4, ::4], 5)]
                        p = os.path.join(cache, os.path.splitext(sel.file)[0] + ".labels.png")
                        Image.fromarray(small).save(p)
                        lab_tex[sel.file] = rl.load_texture(p)
                    t = lab_tex.get(sel.file)
                    rl.draw_texture_pro(th, rl.Rectangle(0, 0, th.width, th.height), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0, rl.WHITE)
                    if t is not None:
                        rl.draw_texture_pro(t, rl.Rectangle(0, 0, t.width, t.height), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0, rl.Color(255, 255, 255, 170))
                    else:
                        font.draw_text("ознаките се појавуваат по градењето", x0 + 20, yy + ih // 2, 16, rl.WHITE)
                else:
                    rl.begin_texture_mode(rt)
                    rl.clear_background(rl.Color(150, 172, 196, 255))
                    fwd, _r, up = sel.basis()
                    e = sel.eye()
                    rl.begin_mode_3d(rl.Camera3D(_v3(e), _v3(e + fwd * 10), _v3(up), float(sel.fov), rl.CAMERA_PERSPECTIVE))
                    scene.draw()
                    rl.end_mode_3d()
                    rl.end_texture_mode()
                    rl.draw_texture_pro(rt.texture, rl.Rectangle(0, 0, 480, -270), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0, rl.WHITE)
                    rl.draw_texture_pro(th, rl.Rectangle(0, 0, th.width, th.height), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0,
                                        rl.Color(255, 255, 255, int(255 * alpha * 0.6)))
            yy += ih + 8
            sc_ = getattr(sel, "score", None)
            font.draw_text((sel.status or "уште не е обработена") + (f"   ·   SSIM {sc_[1]:.3f} · PSNR {sc_[0]:.1f} dB" if sc_ else ""),
                           x0 + 10, yy, 15, INK)
            yy += 24
            b = blds.get(sel.bid)
            if b is not None:
                font.draw_text(f"тековна:  {b.gen['h']:.1f} м, {pg.MATS.get(b.gen['mat'], '?')}, ѕид {tuple(b.gen['wallc'])}", x0 + 10, yy, 15, DIM)
                yy += 20
                for k, name, _ in pg.ALGOS:
                    f = b.fits.get(k)
                    if not f:
                        continue
                    lk = b.look(k)
                    font.draw_text(f"{name[:14]}: {lk['h']:.1f} м, {pg.MATS.get(lk['mat'], '?')}, кат {lk.get('floor', 3.2):.2f}, "
                                   f"пр {lk.get('bay', 3.4):.2f}" + (f", разл {f['loss']:.2f}" if "loss" in f else ""), x0 + 10, yy, 14,
                                   LOOK_COL["photo"] if k == algo else DIM)
                    yy += 18
                    wc = lk.get("wallc")
                    if wc:
                        rl.draw_rectangle(x0 + pw - 34, yy - 18, 20, 14, rl.Color(int(wc[0]), int(wc[1]), int(wc[2]), 255))
                f = b.fits.get(algo)
                if f and algo == "detail":                       # what was measured for this building, in words
                    rf = f.get("roof") or {}
                    ws = f.get("walls") or []
                    pr_ = f.get("params") or []
                    for ln in (f"покрив: {rf.get('kind', '—')}" + (f", {rf.get('rise', 0):.1f} м" if rf.get("rise") else "")
                               + f", оџаци {len(rf.get('chim', []))}, кабини {len(rf.get('hous', []))}, стреа {rf.get('eave', 0):.2f} м",
                               f"видени ѕидови {len(ws)}, колони {len(pr_)}, површина {f.get('surf', '?')}",
                               f"балкони {sum(1 for q in pr_ if q.get('balc'))}, ролетни {sum(1 for q in pr_ if q.get('blind'))}, "
                               f"клими {sum(len(q.get('ac', [])) for q in pr_)}",
                               f"тип: {archkit.ARCHETYPES[archkit.archetype(dict(f, h=lk['h']))]}",
                               "комплет: " + _fit(", ".join(archkit.BY_ID[i][2].split(':')[0] for i in archkit.kit_ids(dict(f, h=lk['h']), op)) or "—", 13, pw - 90)):
                        font.draw_text(ln, x0 + 10, yy, 13, INK)
                        yy += 17
            font.draw_text("M прикажи · V застани во камерата · [ ] провидност · K проба", x0 + 10, H - 30, 13, DIM)
        if time.time() - msg_t < 4:
            tw = font.measure_text(msg, 20)
            rl.draw_rectangle((W - tw) // 2 - 12, H - 60, tw + 24, 34, rl.Color(0, 0, 0, 200))
            font.draw_text(msg, (W - tw) // 2, H - 54, 20, rl.WHITE)
        if music is not None:
            music.widget(station_keys=False)
        rl.end_drawing()
        if job is not None and job.done and not getattr(job, "_evaluated", False) and scene.want is None:
            job._evaluated = True
            if job.only and not job.error:                # a proof run: tune it (if on) and judge it at once
                if op.get("autotune", True):
                    tune([c for c in ok_caps if c.file in job.only])
                evaluate([c for c in ok_caps if c.file in job.only])
        if frames is not None:
            if n == 3 and job is None:
                if "proof" in test and sel is not None:
                    proof = {sel.file}
                st["seg"] = os.environ.get("SK242_SEG", st["seg"])
                start_job(set(proof) if proof else None)
            if job is not None and job.done and scene.want is None and frames > 0:
                frames -= 1
            if frames == 0 or (job is not None and job.done and frames <= 0):
                if shot:
                    rl.take_screenshot(shot)
                break
    if job is not None:
        job.stop = True
    scene.free()
    for mm, _ in quads.values():
        gl3d.free_model(mm)
    for t in list(thumbs.values()) + list(lab_tex.values()):
        rl.unload_texture(t)
    rl.unload_render_texture(rt)
    for t in tex.values():
        try:
            rl.unload_texture(t)
        except Exception:  # noqa: BLE001 - not a texture
            pass
    return "changed" if changed else None


if __name__ == "__main__":                       # python src/photoview.py <folder> [--frames N --shot out.png]
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--osm")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--shot")
    ap.add_argument("--test", default="")
    a = ap.parse_args()
    rl.set_config_flags(rl.FLAG_MSAA_4X_HINT | rl.FLAG_WINDOW_RESIZABLE)
    rl.init_window(1600, 900, "Skopje 242 - photogrammetry")
    rl.set_target_fps(60)
    rl.set_exit_key(0)
    rl.rl_disable_backface_culling()
    font.load()
    run(folder=a.folder, osm_dir=a.osm, frames=a.frames, shot=a.shot, test=a.test)
    rl.close_window()
