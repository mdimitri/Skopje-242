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


def ask_folder():
    """The OS folder picker (tkinter), starting at the last folder used -> path or None."""
    start = ""
    try:
        start = open(LAST, encoding="utf-8").read().strip()
    except OSError:
        pass
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Папка со фотограметриски снимки (manifest.csv)", initialdir=start or ROOT, parent=root)
        root.destroy()
    except Exception as e:  # noqa: BLE001 - no tkinter: the last folder, if any
        print(f"[photogram] folder picker failed: {e}")
        path = start
    if path:
        try:
            os.makedirs(os.path.dirname(LAST), exist_ok=True)
            with open(LAST, "w", encoding="utf-8") as f:
                f.write(path)
        except OSError:
            pass
    return path or None


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
    """Per-material models of all loaded buildings in one look (current, or one algorithm's fit)."""

    def __init__(self, tex):
        self.tex = tex
        self.models = []
        self.key = None

    def free(self):
        for m in self.models:
            gl3d.free_model(m)
        self.models = []

    def build(self, blds, algo):
        bw = pg.tools()
        acc = {}
        for b in blds.values():
            lk = b.look(algo)
            h = float(lk["h"])
            ring = [tuple(p) for p in b.ring]
            w = bw.walls(ring, h, lk["wallc"], None, lk.get("floor", 3.2), lk.get("bay", 3.4))
            parts = []
            if w:
                parts.append((lk["mat"], w))
            if not hasattr(b, "_tri"):
                try:
                    b._tri = bw.triangulate(ring, [])
                except Exception:  # noqa: BLE001
                    b._tri = ([], [])
            verts, tri = b._tri
            if lk.get("small") and lk.get("pitched", True) and h < 11:
                parts.append((bw.MAT_ROOF, bw.pyramid(ring, h, 1.8 + math.sqrt(b.area) * 0.12, lk["roofc"])))
            else:
                fp = bw.flat_poly(verts, tri, h, 6.0, [c * 1.02 for c in lk["roofc"]])
                if fp:
                    parts.append((bw.MAT_ROOF, fp))
            for mat, (pos, uv, col) in parts:
                pos = np.asarray(pos, np.float32).copy()
                pos[:, 1] += b.base
                e = acc.setdefault(mat, ([], [], []))
                e[0].append(pos); e[1].append(np.asarray(uv, np.float32)); e[2].append(np.asarray(col, np.uint8))
        self.free()
        names = {**pg.MATS, bw.MAT_ROOF: "roof"}
        for mat, (P, U, C) in acc.items():
            m = gl3d.make_model(np.concatenate(P), np.concatenate(U), np.concatenate(C))
            if m is not None:
                gl3d.set_texture(m, self.tex.get(names.get(mat, "A"), self.tex["white"]))
                self.models.append(m)

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


def run(aud=None, music=None, folder=None, osm_dir=None, frames=None, shot=None, test=""):
    """-> 'changed' when the game's choice of buildings changed (the world has to be built again), else None.
    frames / shot: headless test (run that many frames, save the last one)."""
    folder = folder or ask_folder()
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
    algo_i = 2
    look = True                                     # show the fitted look (else the current one)
    job = None
    scene = Scene(tex)
    scene.build(blds, None)
    shown = (None, -1)
    thumbs, quads = {}, {}
    cache = os.path.join(folder, pg.CACHE)
    os.makedirs(cache, exist_ok=True)
    for c in caps:
        if not c.exists:
            continue
        p = os.path.join(cache, os.path.splitext(c.file)[0] + ".thumb.jpg")
        if not os.path.exists(p):
            Image.open(c.path).convert("RGB").resize((480, int(480 * c.H / max(1, c.W)))).save(p, quality=85)
        thumbs[c.file] = rl.load_texture(p)
    cen = np.mean([[c.x, 0, c.z] for c in caps], 0)
    orb = Orbit(cen)
    sel = next((c for c in caps if c.exists), None)
    show_fr, show_ph, panel_mode, alpha = True, True, 0, 0.55
    for c in caps:                                  # headless test: --test "sel=0043,panel=2,free"
        if c.exists and ("sel=" + c.file[:4]) in test:
            sel = c
    if "panel=" in test:
        panel_mode = int(test.split("panel=")[1][0])
    if "free" in test and sel is not None:
        orb.free = sel
    rt = rl.load_render_texture(480, 270)
    lab_tex = {}
    msg, msg_t = "", 0.0
    changed = False
    n = 0
    while not rl.window_should_close():
        n += 1
        if music is not None:
            music.update()
        W, H = rl.get_screen_width(), rl.get_screen_height()
        lw, pw = 330, 500                                       # left / right panel widths
        m = rl.get_mouse_position()
        over_ui = m.x < lw or (sel is not None and m.x > W - pw)
        if rl.is_key_pressed(rl.KEY_ESCAPE):
            if orb.free is not None:
                orb.free = None
            else:
                break
        algo = pg.ALGOS[algo_i][0]
        running = job is not None and not job.done
        for i, k in enumerate((rl.KEY_ONE, rl.KEY_TWO, rl.KEY_THREE)):
            if rl.is_key_pressed(k):
                algo_i = i
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
        if rl.is_key_pressed(rl.KEY_TAB) and caps:
            ok_caps = [c for c in caps if c.exists]
            sel = ok_caps[(ok_caps.index(sel) + 1) % len(ok_caps)] if sel in ok_caps else ok_caps[0]
            orb.t = np.array([sel.x, sel.y, sel.z])
        if sel is not None and rl.is_key_pressed(rl.KEY_V):
            orb.free = None if orb.free is sel else sel
        start = rl.is_key_pressed(rl.KEY_R)
        orb.update(over_ui)
        cam = orb.cam()
        # pick a capture: the nearest camera apex / photo centre on screen
        if not over_ui and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and show_fr:
            best = (24.0, None)
            for c in caps:
                if not c.exists:
                    continue
                e, pts = _frustum(c)
                for p in (e, np.mean(pts, 0)):
                    s = rl.get_world_to_screen(_v3(p), cam)
                    dd = math.hypot(s.x - m.x, s.y - m.y)
                    if dd < best[0]:
                        best = (dd, c)
            if best[1] is not None:
                sel = best[1]
        # the meshes follow the job (at most twice a second) and the look switch
        want = (algo if look else None, (job.version if job else 0) + sum(b.version for b in blds.values()) if look else 0)
        if want != shown and (n % 30 == 0 or want[0] != shown[0] or not running):
            scene.build(blds, want[0])
            shown = want
        if sel is not None and sel.file in quads and quads[sel.file][1] != (sel.dyaw, sel.dpitch):
            gl3d.free_model(quads.pop(sel.file)[0])
        # ---- draw
        rl.begin_drawing()
        rl.clear_background(rl.Color(150, 172, 196, 255))
        rl.begin_mode_3d(cam)
        rl.draw_plane(_v3(cen), rl.Vector2(1600, 1600), rl.Color(120, 126, 112, 255))
        scene.draw()
        for b in blds.values():                                   # fitted outlines: green = from photos, blue = from neighbours
            f = b.fits.get(algo) if look else None
            if not f:
                continue
            col = LOOK_COL["photo" if f.get("src") == "photo" else "inferred"]
            if f.get("src") != "photo" and orb.dist > 900:
                continue
            hh = b.base + float(b.look(algo)["h"]) + 0.3
            r = b.ring
            for i in range(len(r)):
                rl.draw_line_3d(rl.Vector3(r[i][0], hh, r[i][1]), rl.Vector3(r[(i + 1) % len(r)][0], hh, r[(i + 1) % len(r)][1]), col)
        if show_fr:
            for c in caps:
                if not c.exists:
                    continue
                e, pts = _frustum(c)
                col = rl.YELLOW if c is sel else (rl.Color(255, 120, 200, 255) if c.status else rl.Color(255, 255, 255, 200))
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
        # ---- left panel: algorithms, actions, progress, log
        rl.draw_rectangle(0, 0, lw, H, PANEL)
        y = 14
        font.draw_text("ФОТОГРАМЕТРИЈА", 16, y, 30, PINK, bold="cond")
        y += 40
        font.draw_text(os.path.basename(folder.rstrip("/\\"))[:34], 16, y, 16, DIM)
        y += 26
        font.draw_text("АЛГОРИТАМ (1-3)", 16, y, 18, INK, bold="cond")
        y += 26
        for i, (k, name, note) in enumerate(pg.ALGOS):
            have = sum(1 for b in blds.values() if k in b.fits)
            if _button(16, y, lw - 32, 30, f"{i + 1}  {name}" + (f"  ({have})" if have else ""), i == algo_i):
                algo_i = i
            y += 32
            if i == algo_i:
                font.draw_text(note[:44], 20, y, 14, DIM)
                y += 18
        y += 8
        if _button(16, y, lw - 32, 38, "ГРАДИ ПРЕКУ ВЕТЕ (R)" if algo in {k for b in blds.values() for k in b.fits} else "ИЗГРАДИ (R)", running, 22) or start:
            if not running:
                job = pg.Job(folder, algo, tex_np, osm_dir, state=(caps, blds))
                job.start()
                look = True
        y += 46
        if _button(16, y, (lw - 40) // 2, 30, "ПРИКАЖИ: " + ("ФОТО" if look else "ТЕКОВНИ") + " (G)", look):
            look = not look
        if _button(24 + (lw - 40) // 2, y, (lw - 40) // 2, 30, "ПРИМЕНИ ВО ИГРАТА", False):
            try:
                pg.apply_to_game(folder, algo, osm_dir)
                msg, changed = f"photogram.json <- {algo}: важи по следното градење", True
            except OSError as e:
                msg = f"нема готов резултат за {algo} ({e.strerror})"
            msg_t = time.time()
        y += 36
        st = pg.enabled(osm_dir)
        lab = "ЗГРАДИ ВО ИГРАТА: " + {None: "ТЕКОВНИ (нема фото)", True: "ФОТО", False: "ТЕКОВНИ"}[st]
        if _button(16, y, lw - 32, 30, lab, bool(st)) and st is not None:
            pg.set_enabled(not st, osm_dir)
            changed, msg, msg_t = True, "се менува по следното градење на светот", time.time()
        y += 44
        if job is not None:
            rl.draw_rectangle(16, y, lw - 32, 8, rl.Color(60, 50, 64, 255))
            rl.draw_rectangle(16, y, int((lw - 32) * (1.0 if job.done else job.frac)), 8, PINK)
            y += 14
            font.draw_text((job.error or job.step)[:40], 16, y, 16, INK)
            y += 24
            lines = job.log_lines[-max(4, (H - y - 120) // 17):]
            for ln in lines:
                font.draw_text(ln[:46], 16, y, 14, DIM)
                y += 17
        nphoto = sum(1 for b in blds.values() if b.fits.get(algo, {}).get("src") == "photo")
        ninf = sum(1 for b in blds.values() if b.fits.get(algo, {}).get("src") == "inferred")
        font.draw_text(f"згради {len(blds)}  ·  од фото {nphoto}  ·  од соседи {ninf}", 16, H - 70, 15, INK)
        font.draw_text("десно влечи вртење · средно/Shift поместување · тркало зум", 16, H - 48, 13, DIM)
        font.draw_text("WASD/QE · F рамки · T слики · V од камерата · Tab · Esc", 16, H - 30, 13, DIM)
        # ---- right panel: the picked capture
        if sel is not None:
            x0 = W - pw
            rl.draw_rectangle(x0, 0, pw, H, PANEL)
            yy = 14
            font.draw_text(sel.file[:44], x0 + 10, yy, 16, PINK, bold="cond")
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
                    rl.draw_plane(_v3(cen), rl.Vector2(1600, 1600), rl.Color(120, 126, 112, 255))
                    scene.draw()
                    rl.end_mode_3d()
                    rl.end_texture_mode()
                    rl.draw_texture_pro(rt.texture, rl.Rectangle(0, 0, 480, -270), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0, rl.WHITE)
                    rl.draw_texture_pro(th, rl.Rectangle(0, 0, th.width, th.height), rl.Rectangle(x0 + 10, yy, iw, ih), rl.Vector2(0, 0), 0,
                                        rl.Color(255, 255, 255, int(255 * alpha * 0.6)))
            yy += ih + 8
            font.draw_text(sel.status or "уште не е обработена", x0 + 10, yy, 15, INK)
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
            yy += 6
            font.draw_text("M прикажи · V застани во камерата · [ ] провидност", x0 + 10, H - 30, 13, DIM)
        if time.time() - msg_t < 4:
            tw = font.measure_text(msg, 20)
            rl.draw_rectangle((W - tw) // 2 - 12, H - 60, tw + 24, 34, rl.Color(0, 0, 0, 200))
            font.draw_text(msg, (W - tw) // 2, H - 54, 20, rl.WHITE)
        if music is not None:
            music.widget()
        rl.end_drawing()
        if frames is not None:
            if n == 3 and job is None:
                job = pg.Job(folder, algo, tex_np, osm_dir, state=(caps, blds), seg=os.environ.get("SK242_SEG", "auto"))
                job.start()
            if job is not None and job.done and frames > 0:
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
