"""The traffic lab's full-screen 2D map UI (raylib).

Left: the map (wheel = zoom at the cursor, right / middle drag or arrow keys = pan, left click = the active tool).
Right: tabs -- Live (charts, KPIs, event log), Inspect (the clicked car / junction / road), Edit (tools), Layers
(map colouring and overlays), Batch (variants, sweeps, presets, run), Report (batch results), Scenario (save / load,
Apply to game) and one tab per settings group (Run, Drivers, Junctions, Signals, Roads, Fleet, Transit, Emergency,
Advanced).  Top bar: play / pause, speed, restart, seed.  Bottom: live KPI strip.
Keys: Space play/pause, . one step, 1-6 speed, R restart, N new seed, F follow the selected vehicle, Home fit the
study area, F1 help, F11 full screen / window, Esc closes help or a dialog."""
import collections
import glob
import json
import math
import os
import threading
import time
import webbrowser

import pyray as rl

import font
import traffic_tuning
import vehicles
from . import OUT, ROOT, batch, core, explore, params

# ------------------------------------------------------------------ theme
def C(r, g, b, a=255):
    return rl.Color(r, g, b, a)


BG, MAPBG, PANEL, PANEL2, LINE = C(16, 18, 23), C(24, 27, 33), C(30, 34, 42), C(38, 43, 53), C(56, 62, 76)
FG, MUT, ACC, ACC2 = C(232, 235, 240), C(150, 158, 172), C(80, 150, 255), C(255, 170, 60)
GOOD, BAD, WARN = C(70, 200, 120), C(240, 80, 70), C(245, 200, 60)
CLS_COL = {"motorway": C(240, 130, 60), "trunk": C(235, 150, 70), "primary": C(230, 190, 90), "secondary": C(205, 200, 130),
           "tertiary": C(175, 180, 175), "unclassified": C(130, 136, 145), "residential": C(120, 126, 136),
           "service": C(90, 96, 106), "living_street": C(110, 120, 120)}
RANK = {"motorway": 6, "trunk": 5, "primary": 4, "secondary": 3, "tertiary": 2, "unclassified": 1, "residential": 1}
STYLE_COL = {"hatch": C(120, 170, 255), "sedan": C(100, 150, 240), "wagon": C(110, 160, 230), "suv": C(90, 130, 220),
             "mini": C(150, 190, 255), "taxi": C(250, 210, 60), "limo": C(200, 200, 220), "van": C(170, 130, 230),
             "pickup": C(160, 120, 200), "truck": C(230, 120, 60), "tractor": C(150, 110, 70), "bus": C(250, 200, 40),
             "bike": C(120, 230, 200), "heli": C(255, 255, 255), "apc": C(110, 130, 80)}
LOS_C = {"A": C(26, 152, 80), "B": C(145, 207, 96), "C": C(217, 239, 139), "D": C(254, 224, 139), "E": C(252, 141, 89), "F": C(215, 48, 39)}
SIG_C = {0: C(60, 235, 100), 1: C(250, 200, 40), 2: C(240, 50, 40), None: C(110, 110, 110)}
SERIES = [C(80, 150, 255), C(240, 100, 70), C(70, 200, 120), C(180, 110, 230), C(240, 190, 50), C(40, 190, 210)]

TOP, BOTTOM, RIGHT = 46, 112, 440
TABS_A = ("Live", "Inspect", "Edit", "Layers", "Batch", "Explore", "Report", "Scenario")
TABS_B = params.TABS
LAYERS = ("Road class", "Speed / limit", "Density", "Standing heat", "Conflicts", "Junction LOS", "Lanes")
VCOL = ("Type", "Speed", "Standing time", "Driver pace")
TOOLS = (("select", "Select / inspect", "click a vehicle, junction or road"),
         ("close", "Close / reopen road", "click a road: no car may enter it (removed from the drive graph)"),
         ("obstacle", "Place obstacle", "a standing vehicle in the nearest lane"),
         ("remove", "Remove obstacle", "click an obstacle you placed"),
         ("amb", "Ambulance call", "the pedestrian nearest the click collapses"),
         ("fire", "Car fire", "a burning wreck in the lane, the fire brigade comes"),
         ("breakdown", "Breakdown", "the moving car nearest the click stops for 'breakdown time'"),
         ("area", "Study area (any size)", "drag a rectangle: a junction, a neighbourhood or the whole map; it is cut into tiles of at most 700 m, each simulated on its own core in batches"),
         ("tile", "Choose live tile", "click a tile of a big study area: the live view simulates that one"),
         ("schedule", "Schedule incident", "adds the next click as a timed incident to the scenario (batch too)"))
SPEEDS = (1, 2, 4, 8, 16, 0)        # 0 = as fast as possible
PRESETS = (
    ("Lights on vs off", [{"name": "lights on", "settings": {}}, {"name": "lights off", "settings": {"signals_on": False}}], None),
    ("Calm vs furious drivers", [{"name": f"mood {a}", "settings": {"aggro": a}} for a in range(4)], None),
    ("Signal cycle sweep", [{"name": "game cycle", "settings": {}}], {"key": "cycle", "from": 30, "to": 100, "steps": 5}),
    ("Patience sweep", [{"name": "game WAIT", "settings": {}}], {"key": "wait_scale", "from": 0.5, "to": 3.0, "steps": 5}),
    ("Speed limits -20 % / +20 %", [{"name": "limits x1", "settings": {}},
                                    {"name": "limits x0.8", "settings": {"spd_" + c: 0.8 for c in params.ROAD_CLASSES}},
                                    {"name": "limits x1.2", "settings": {"spd_" + c: 1.2 for c in params.ROAD_CLASSES}}], None),
    ("Density sweep", [{"name": "game cars", "settings": {}}], {"key": "cars", "from": 40, "to": 320, "steps": 5}),
    ("Trucks: none / normal / x3", [{"name": "trucks x1", "settings": {}}, {"name": "no trucks", "settings": {"mix_trucks": 0.0}},
                                    {"name": "trucks x3", "settings": {"mix_trucks": 3.0}}], None),
    ("Emergencies: none vs many", [{"name": "no incidents", "settings": {"amb_rate": 0, "fire_rate": 0, "breakdown_rate": 0}},
                                   {"name": "many incidents", "settings": {"amb_rate": 60, "fire_rate": 30, "breakdown_rate": 30}}], None),
    ("Sirens preempt lights on/off", [{"name": "preempt on", "settings": {}}, {"name": "preempt off", "settings": {"preempt": False}}], None),
    ("Approach zone sweep", [{"name": "game APPR", "settings": {}}], {"key": "appr", "from": 12, "to": 48, "steps": 4}),
)


def ramp(f):
    """0 red .. 0.5 yellow .. 1 green."""
    f = max(0.0, min(1.0, f))
    if f < 0.5:
        return C(230, int(60 + 360 * f), 50)
    return C(int(230 - 360 * (f - 0.5)), 210, int(50 + 120 * (f - 0.5)))


def heat(f):
    f = max(0.0, min(1.0, f))
    return C(255, int(235 - 205 * f), int(90 * (1 - f)), int(110 + 140 * f))


def fmt(v, d=1):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{d}f}"
    return str(v)


class UI:
    def __init__(self, args):
        self.a = args
        self.W, self.H = rl.get_screen_width(), rl.get_screen_height()
        self.world = None
        self.lab = None
        self.settings = params.defaults()
        self.scenario = None
        self.tab = args.tab if args.tab in TABS_A + TABS_B else "Live"
        self.layer = args.layer if args.layer in LAYERS else "Road class"
        self.vcol = "Type"
        self.ov = {"vehicles": True, "boxes": True, "signals": True, "peds": True, "trains": True, "stops": True, "buildings": True,
                   "names": True, "area": True, "intent": False, "stuck": True, "ems": True, "events": True, "parked": True}
        self.tool = "select"
        self.play, self.speed = True, 1
        self.scroll = collections.defaultdict(float)
        self.sel = None
        self.follow = False
        self.drag = None
        self.slider_id = None
        self.focus_field = None
        self.name_field = ""
        self.help = False
        self.toast, self.toast_t = "", 0.0
        self.pending_restart = []
        self.variants = [{"name": "A current settings", "settings": {}}]
        self.sweep = None
        self.batch_state = None                     # {"done", "total", "text", "out", "thread", "cancel"}
        self.report = None                          # (summary, out_dir)
        self.kpi, self.kpi_t = {}, 0.0
        self.ex = None                              # explore.Explorer while / after it runs
        self.ex_keys = set(explore.default_keys())
        self.ex_opt = {"population": 16, "generations": 6, "elite": 4, "seeds": 2, "validate_seeds": 6, "finalists": 5,
                       "w_eff": 0.4, "w_safe": 0.4, "w_speed": 0.2, "informed": True}
        self.mouse_used = False
        self.confirm = None
        self.cam = rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(0, 0), 0.0, 1.0)

    # ================================================================== loading
    def load(self):
        from world import World

        def prog(f, note=""):
            rl.begin_drawing()
            rl.clear_background(BG)
            t = "Loading the game's world ..."
            font.draw_text(t, self.W / 2 - font.measure_text(t, 28) / 2, self.H / 2 - 50, 28, FG, bold=True)
            rl.draw_rectangle(int(self.W / 2 - 300), int(self.H / 2), 600, 14, PANEL2)
            rl.draw_rectangle(int(self.W / 2 - 300), int(self.H / 2), int(600 * f), 14, ACC)
            font.draw_text(str(note)[:80], self.W / 2 - 300, self.H / 2 + 24, 16, MUT)
            rl.end_drawing()
        self.world = World(self.a.world, prog)
        w = self.world
        prog(1.0, "preparing the map")
        self.scenario = core.default_scenario(w)
        if self.a.scenario:
            self._load_scenario(self.a.scenario)
        self.cells = collections.defaultdict(list)              # 100 m cell -> edges / buildings for drawing
        for ei, e in enumerate(w.edges):
            xs, ys = [p[0] for p in e["pts"]], [p[1] for p in e["pts"]]
            for cx in range(int(min(xs) // 100), int(max(xs) // 100) + 1):
                for cy in range(int(min(ys) // 100), int(max(ys) // 100) + 1):
                    self.cells[(cx, cy)].append(("e", ei))
        self.bld = []
        for b in w.buildings:
            ring = b.get("ring") if isinstance(b, dict) else None
            if ring and len(ring) >= 3:
                self.bld.append(ring)
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                self.cells[(int(sum(xs) / len(xs) // 100), int(sum(ys) / len(ys) // 100))].append(("b", len(self.bld) - 1))
        self.names = []
        seen = set()
        for e in w.edges:
            r = w.roads[e["road"]] if 0 <= e.get("road", -1) < len(w.roads) else {}
            nm = r.get("name") if isinstance(r, dict) else None
            if nm and e["len"] > 60 and (nm, int(e["pts"][0][0] // 250), int(e["pts"][0][1] // 250)) not in seen:
                seen.add((nm, int(e["pts"][0][0] // 250), int(e["pts"][0][1] // 250)))
                p0, p1 = e["pts"][0], e["pts"][-1]
                self.names.append(((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, math.atan2(p1[1] - p0[1], p1[0] - p0[0]), nm, RANK.get(e["cls"].replace("_link", ""), 0)))
        self.restart()
        self.fit_area()

    def restart(self, seed=None):
        if self.lab is not None:
            self.lab.close()
        self.settings["seed0"] = int(seed if seed is not None else self.settings.get("seed0", 1))
        self.lab = core.LabSim(self.world, self.a.osm, self.settings, self.scenario, int(self.settings["seed0"]))
        self.pending_restart = []
        self.sel = None
        self.kpi_t = 0.0

    def retune(self):
        later = self.lab.retune(self.settings, self.scenario)
        self.pending_restart = later
        self.kpi_t = 0.0

    def fit_area(self):
        a = core.norm_area(self.scenario["area"])
        mw, mh = self.W - RIGHT, self.H - TOP - BOTTOM
        z = min(mw / (a[2] - a[0]), mh / (a[3] - a[1])) * 0.92
        self.cam.zoom = z
        self.cam.offset = rl.Vector2(mw / 2, TOP + mh / 2)
        self.cam.target = rl.Vector2((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)

    # ================================================================== widgets
    def text(self, s, x, y, size=16, col=FG, bold=False):
        font.draw_text(str(s), x, y, size, col, bold=bold)

    def tw(self, s, size=16, bold=False):
        return font.measure_text(str(s), size, bold=bold)

    def over(self, x, y, w, h):
        m = rl.get_mouse_position()
        return x <= m.x < x + w and y <= m.y < y + h

    def clicked(self, x, y, w, h):
        if self.over(x, y, w, h) and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and not self.mouse_used:
            self.mouse_used = True
            return True
        return False

    def button(self, label, x, y, w, h=28, active=False, col=None, size=15, enabled=True):
        hot = self.over(x, y, w, h) and enabled
        bg = col if col is not None else (ACC if active else (PANEL2 if not hot else LINE))
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.25, 6, bg)
        tc = FG if enabled else MUT
        self.text(label, x + (w - self.tw(label, size)) / 2, y + (h - size) / 2 - 1, size, tc)
        return enabled and self.clicked(x, y, w, h)

    def toggle(self, label, x, y, value, w=380, help=""):
        h = 24
        rl.draw_rectangle_rounded(rl.Rectangle(x, y + 3, 36, 18), 0.9, 8, ACC if value else LINE)
        rl.draw_circle(int(x + (27 if value else 9)), int(y + 12), 7, FG)
        self.text(label, x + 46, y + 3, 15, FG)
        if help and self.over(x, y, w, h):
            self.hint = help
        if self.clicked(x, y, w, h):
            return not value
        return value

    def slider(self, key, label, x, y, w, value, lo, hi, step, default=None, help="", integer=False):
        """Label + value on one line, the bar under it.  Drag or wheel to change; right click resets."""
        self.text(label, x, y, 14, FG if value == default or default is None else ACC2)
        vs = fmt(value, 0 if integer else (2 if step < 0.1 else 1 if step < 1 else 0))
        self.text(vs, x + w - self.tw(vs, 14), y, 14, FG)
        by = y + 20
        rl.draw_rectangle_rounded(rl.Rectangle(x, by, w, 6), 1.0, 6, LINE)
        f = 0.0 if hi == lo else (value - lo) / (hi - lo)
        f = max(0.0, min(1.0, f))
        rl.draw_rectangle_rounded(rl.Rectangle(x, by, w * f, 6), 1.0, 6, ACC)
        if default is not None and hi != lo:
            fd = max(0.0, min(1.0, (default - lo) / (hi - lo)))
            rl.draw_rectangle(int(x + w * fd) - 1, int(by - 3), 2, 12, MUT)
        rl.draw_circle(int(x + w * f), int(by + 3), 7, FG)
        hot = self.over(x, y, w, 32)
        if hot and help:
            self.hint = help
        m = rl.get_mouse_position()
        if hot and rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT) and not self.mouse_used:
            self.slider_id = key
            self.mouse_used = True
        nv = value
        if self.slider_id == key:
            if rl.is_mouse_button_down(rl.MOUSE_BUTTON_LEFT):
                f = max(0.0, min(1.0, (m.x - x) / w))
                nv = lo + f * (hi - lo)
            else:
                self.slider_id = None
                self.changed_end = True
        elif hot:
            wh = rl.get_mouse_wheel_move()
            if wh:
                nv = value + step * (1 if wh > 0 else -1)
                self.wheel_used = True
                self.changed_end = True
            if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_RIGHT) and default is not None:
                nv = default
                self.changed_end = True
        if nv != value:
            nv = max(lo, min(hi, round(nv / step) * step if step else nv))
            if integer:
                nv = int(round(nv))
        return nv

    # ================================================================== the frame
    def frame(self):
        self.mouse_used = False
        self.wheel_used = False
        self.changed_end = False
        self.hint = ""
        self.W, self.H = rl.get_screen_width(), rl.get_screen_height()
        self.keys()
        self.advance()
        rl.begin_drawing()
        rl.clear_background(BG)
        # panel first for input priority (it owns its rectangle), then map
        self.draw_map()
        self.draw_top()
        self.draw_bottom()
        self.draw_panel()
        self.map_input()
        if self.help:
            self.draw_help()
        if self.confirm:
            self.draw_confirm()
        if self.hint:
            m = rl.get_mouse_position()
            lines = font.wrap(self.hint, 14, 360)
            hh = 8 + 18 * len(lines)
            x = min(m.x + 14, self.W - 380)
            y = min(m.y + 14, self.H - hh - 4)
            rl.draw_rectangle_rounded(rl.Rectangle(x, y, 372, hh), 0.15, 6, C(10, 12, 16, 235))
            for i, ln in enumerate(lines):
                self.text(ln, x + 8, y + 4 + i * 18, 14, FG)
        if self.toast and time.time() < self.toast_t:
            tw = self.tw(self.toast, 16) + 30
            rl.draw_rectangle_rounded(rl.Rectangle((self.W - RIGHT - tw) / 2, TOP + 12, tw, 32), 0.4, 8, C(10, 12, 16, 230))
            self.text(self.toast, (self.W - RIGHT - tw) / 2 + 15, TOP + 19, 16, FG)
        rl.end_drawing()

    def say(self, s, secs=3.0):
        self.toast, self.toast_t = s, time.time() + secs

    def keys(self):
        if self.focus_field is not None:
            ch = rl.get_char_pressed()
            while ch:
                if 32 <= ch < 0x500 and len(self.name_field) < 40:
                    self.name_field += chr(ch)
                ch = rl.get_char_pressed()
            if rl.is_key_pressed(rl.KEY_BACKSPACE):
                self.name_field = self.name_field[:-1]
            if rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_ESCAPE):
                self.focus_field = None
            return
        if rl.is_key_pressed(rl.KEY_SPACE):
            self.play = not self.play
        if rl.is_key_pressed(rl.KEY_PERIOD):
            self.play = False
            for _ in range(4):
                self.lab.step()
        for i, k in enumerate((rl.KEY_ONE, rl.KEY_TWO, rl.KEY_THREE, rl.KEY_FOUR, rl.KEY_FIVE, rl.KEY_SIX)):
            if rl.is_key_pressed(k):
                self.speed = SPEEDS[i]
        if rl.is_key_pressed(rl.KEY_R):
            self.restart()
        if rl.is_key_pressed(rl.KEY_N):
            self.restart(int(self.settings["seed0"]) + 1)
        if rl.is_key_pressed(rl.KEY_F):
            self.follow = not self.follow
        if rl.is_key_pressed(rl.KEY_HOME):
            self.fit_area()
        if rl.is_key_pressed(rl.KEY_F1) or rl.is_key_pressed(rl.KEY_H):
            self.help = not self.help
        if rl.is_key_pressed(rl.KEY_ESCAPE):
            self.help, self.confirm = False, None
        if rl.is_key_pressed(rl.KEY_F11):
            rl.toggle_borderless_windowed()
        pan = 600.0 / self.cam.zoom * rl.get_frame_time()
        for k, dx, dy in ((rl.KEY_LEFT, -1, 0), (rl.KEY_RIGHT, 1, 0), (rl.KEY_UP, 0, -1), (rl.KEY_DOWN, 0, 1)):
            if rl.is_key_down(k):
                self.cam.target = rl.Vector2(self.cam.target.x + dx * pan, self.cam.target.y + dy * pan)
                self.follow = False

    def advance(self):
        lab = self.lab
        if self.play:
            budget = 0.030
            t0 = time.perf_counter()
            if self.speed == 0:
                while time.perf_counter() - t0 < budget:
                    lab.step()
            else:
                want = rl.get_frame_time() * self.speed
                n = max(0, int(round(want / lab.dt + getattr(self, "_carry", 0.0))))
                self._carry = getattr(self, "_carry", 0.0) + want / lab.dt - n
                for _ in range(min(n, 64)):
                    lab.step()
                    if time.perf_counter() - t0 > budget * 2:
                        self._carry = 0.0
                        break
        if self.follow and self.sel and self.sel[0] in ("car", "body"):
            o = self.sel[1]
            self.cam.target = rl.Vector2(o.x, o.y)
        now = time.time()
        if now - self.kpi_t > 0.5:
            self.kpi_t = now
            self.kpi = lab.m.summary() if lab.m.samples else {}

    # ================================================================== map
    def to_world(self, x, y):
        v = rl.get_screen_to_world_2d(rl.Vector2(x, y), self.cam)
        return v.x, v.y

    def view_rect(self):
        x0, y0 = self.to_world(0, TOP)
        x1, y1 = self.to_world(self.W - RIGHT, self.H - BOTTOM)
        return x0, y0, x1, y1

    def draw_map(self):
        lab, w = self.lab, self.world
        mw, mh = self.W - RIGHT, self.H - TOP - BOTTOM
        rl.draw_rectangle(0, TOP, mw, mh, MAPBG)
        rl.begin_scissor_mode(0, TOP, mw, mh)
        rl.begin_mode_2d(self.cam)
        z = self.cam.zoom
        x0, y0, x1, y1 = self.view_rect()
        px = 1.0 / z                                          # one screen pixel in metres
        edges, blds = set(), set()
        for cx in range(int(x0 // 100) - 1, int(x1 // 100) + 1):
            for cy in range(int(y0 // 100) - 1, int(y1 // 100) + 1):
                for kind, i in self.cells.get((cx, cy), ()):
                    (edges if kind == "e" else blds).add(i)
        if self.ov["buildings"] and z > 0.35:
            bc = C(44, 48, 57)
            for i in blds:
                ring = self.bld[i]
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    rl.draw_line_v(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), bc)
        m = lab.m
        live_v, live_k = m.edge_v, m.edge_k
        minrank = 0 if z > 0.25 else (2 if z > 0.1 else 3)
        layer = self.layer
        for ei in edges:
            e = w.edges[ei]
            if not e["drive"]:
                continue
            cls = e["cls"].replace("_link", "")
            if RANK.get(cls, 0) < minrank:
                continue
            col = CLS_COL.get(cls, C(100, 105, 115))
            if layer == "Speed / limit":
                col = ramp(live_v[ei] / 1.0) if ei in live_v else C(70, 75, 85)
            elif layer == "Density":
                col = heat(live_k[ei] / 80.0) if ei in live_k else C(70, 75, 85)
            elif layer in ("Standing heat", "Conflicts", "Junction LOS"):
                col = C(78, 84, 96)
            width = max(e["w"], 2.5 * px)
            pts = e["pts"]
            for a, b in zip(pts, pts[1:]):
                rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), width, col)
            if ei in lab.closed:
                for a, b in zip(pts, pts[1:]):
                    rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), max(2.0, e["w"] * 0.35), C(230, 40, 40, 220))
                mx, my = traffic_tuning.edge_mid(w, ei)
                s = max(3.0, 7 * px)
                rl.draw_line_ex(rl.Vector2(mx - s, my - s), rl.Vector2(mx + s, my + s), 3 * px, FG)
                rl.draw_line_ex(rl.Vector2(mx - s, my + s), rl.Vector2(mx + s, my - s), 3 * px, FG)
            if layer == "Lanes" and z > 1.2:
                import actors
                for d in ((1,) if e["ow"] else (1, -1)):
                    for off in actors.Traffic.lanes_of(e, d):
                        o = off * d
                        for a, b in zip(pts, pts[1:]):
                            hx, hy = b[0] - a[0], b[1] - a[1]
                            L = math.hypot(hx, hy) or 1.0
                            nx, ny = -hy / L, hx / L
                            rl.draw_line_ex(rl.Vector2(a[0] - nx * o, a[1] - ny * o), rl.Vector2(b[0] - nx * o, b[1] - ny * o),
                                            1.2 * px, C(240, 240, 240, 120) if d == 1 else C(255, 200, 120, 120))
        if layer in ("Standing heat", "Conflicts"):
            src = m.heat_stand if layer == "Standing heat" else m.heat_conf
            top = max(src.values(), default=1.0) or 1.0
            for (cx, cy), v in src.items():
                if x0 - 20 < cx * core.CELL < x1 and y0 - 20 < cy * core.CELL < y1:
                    rl.draw_rectangle_rec(rl.Rectangle(cx * core.CELL, cy * core.CELL, core.CELL, core.CELL), heat(math.sqrt(v / top)))
        if layer == "Conflicts":
            for t, x, y, d, kind in m.collisions[-300:]:
                rl.draw_circle_lines(int(x), int(y), max(3.0, 6 * px), BAD)
            for t, x, y, ttc in m.near[-300:]:
                rl.draw_circle_lines(int(x), int(y), max(2.0, 4 * px), WARN)
        if layer == "Junction LOS" or self.tab == "Inspect":
            sig = set(lab.lights.nodes)
            for node, n in m.passes.items():
                x, y = lab.node_xy.get(node, (0, 0))
                if not (x0 < x < x1 and y0 < y < y1):
                    continue
                cd = m.cdelay.get(node)
                d = sum(cd) / len(cd) if cd else 0.0
                L = core.los(d, node in sig)
                if layer == "Junction LOS":
                    r = max(4.0, min(16.0, 3 + math.sqrt(n) * 1.2))
                    rl.draw_circle_v(rl.Vector2(x, y), r, LOS_C[L])
                    if z > 0.9:
                        self._wtext(L, x - 3 * px, y - 7 * px, 13, C(15, 15, 15))
        # rail, crossings, stations, bus stops
        tr = lab.sim.trains
        if self.ov["trains"]:
            for ln in getattr(w, "track", {}).get("lines", ()) if getattr(w, "track", None) else ():
                for a, b in zip(ln, ln[1:]):
                    if x0 - 50 < a[0] < x1 + 50 and y0 - 50 < a[1] < y1 + 50:
                        rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), max(1.5, 2 * px), C(150, 120, 100))
            for key, (ln, s, x, y, yaw) in tr.xings.items():
                closed = key in tr.closed
                rl.draw_circle_v(rl.Vector2(x, y), max(3.0, 5 * px), BAD if closed else C(240, 240, 240))
            import trains as trains_mod
            for t in tr.trains:
                for k in range(trains_mod.CARS):
                    s = t.s - t.d * (k * (trains_mod.CAR_L + trains_mod.GAP) + trains_mod.CAR_L / 2)
                    x, y, _gz, h = t.line.at(s)
                    if x0 - 30 < x < x1 + 30 and y0 - 30 < y < y1 + 30:
                        self._box(x, y, h, trains_mod.CAR_L / 2, 1.5, C(226, 228, 232), C(196, 40, 40))
        if self.ov["stops"] and lab.sim.transit is not None and z > 0.3:
            for st in lab.sim.transit.stops:
                if x0 < st[0] < x1 and y0 < st[1] < y1:
                    rl.draw_rectangle_rec(rl.Rectangle(st[0] - 2, st[1] - 2, 4, 4), C(250, 200, 40))
        # signals
        if self.ov["signals"] and z > 0.25:
            lg = lab.lights
            for i, it in enumerate(lg.items):
                lx, lz, jx, jz = it[4], it[5], it[6], it[7]
                if lx != lx or not (x0 < lx < x1 and y0 < lz < y1):
                    continue
                st = lg.state_of(it[1], it[2])
                rl.draw_circle_v(rl.Vector2(lx, lz), max(1.2, 3.2 * px), SIG_C[st])
                if z > 1.4:
                    rl.draw_line_ex(rl.Vector2(lx, lz), rl.Vector2(lx + (jx - lx) * 0.25, lz + (jz - lz) * 0.25), 1.0 * px * 2, SIG_C[st])
        # vehicles
        import actors
        sim = lab.sim
        if self.ov["parked"] and z > 0.5:
            for b in sim.bodies:
                if b.parked_idx is not None and x0 < b.x < x1 and y0 < b.y < y1:
                    for p in actors.parts(b):
                        self._box(p[0], p[1], p[2], p[3], p[4], C(72, 78, 92), None)
        if self.ov["vehicles"]:
            T = sim.traffic
            stmap = m.car
            for c in T.cars:
                if not (x0 - 20 < c.x < x1 + 20 and y0 - 20 < c.y < y1 + 20):
                    continue
                col = self._vcol(c, stmap.get(c))
                if c.ghost > 0:
                    col = C(col.r, col.g, col.b, 90)
                for p in actors.parts(c):
                    self._box(p[0], p[1], p[2], p[3], p[4], col, FG if self.ov["boxes"] and z > 2.0 else None)
                if z > 1.0:
                    self._marks(c, col, px, stmap.get(c))
            bus_bodies = {bus.body for bus in getattr(sim.transit, "buses", ())} if sim.transit else set()
            t = time.time()
            for b in sim.bodies:
                if b.parked_idx is not None or not (x0 - 20 < b.x < x1 + 20 and y0 - 20 < b.y < y1 + 20):
                    continue
                if b in bus_bodies:
                    col = C(250, 200, 40)
                elif b.service:
                    col = (C(240, 60, 60) if int(t * 4) % 2 else C(70, 120, 255)) if b.siren else C(240, 240, 240)
                elif b.health <= 0 or b.exploded:
                    col = C(255, 110, 30) if b.burn > 0 and not b.out else C(60, 60, 60)
                elif b in lab.obstacles or any(b is r[1] for r in lab.broken):
                    col = C(255, 60, 200)
                else:
                    col = C(170, 175, 185)
                for p in actors.parts(b):
                    self._box(p[0], p[1], p[2], p[3], p[4], col, FG if z > 2.0 else None)
        if self.ov["ems"]:
            for j in sim.services.jobs:
                rl.draw_circle_lines(int(j.x), int(j.y), max(5.0, 9 * px), C(240, 60, 60))
                path = j.path
                if path and j.pi < len(path):
                    for a, b in zip(path[j.pi:], path[j.pi + 1:]):
                        rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), 2 * px, C(240, 60, 60, 160))
        if self.ov["peds"] and z > 0.4:
            for p in sim.peds.list:
                if x0 < p.x < x1 and y0 < p.y < y1:
                    col = C(120, 230, 140) if p.mode == "walk" else (BAD if p.mode in ("dead", "air") else C(255, 170, 60))
                    rl.draw_circle_v(rl.Vector2(p.x, p.y), max(0.35, 1.6 * px), col)
        if self.ov["events"]:
            now = lab.t
            for t, x, y, d, kind in m.collisions[-60:]:
                if now - t < 20:
                    rl.draw_circle_lines(int(x), int(y), max(4.0, 10 * px) * (1 + (now - t) / 10), C(255, 60, 60, int(255 * (1 - (now - t) / 20))))
            for t, x, y, node in m.redruns[-40:]:
                if now - t < 15:
                    rl.draw_circle_lines(int(x), int(y), max(4.0, 9 * px), C(255, 40, 200))
        # study area
        a = core.norm_area(self.scenario["area"])
        if self.ov["area"]:
            ts = core.tiles(self.scenario["area"])
            if len(ts) > 1:
                for t in ts:
                    rl.draw_rectangle_lines_ex(rl.Rectangle(t[0], t[1], t[2] - t[0], t[3] - t[1]), 1 * px, C(80, 150, 255, 90))
            la = lab.area
            rl.draw_rectangle_lines_ex(rl.Rectangle(la[0], la[1], la[2] - la[0], la[3] - la[1]), 2.5 * px, ACC2 if len(ts) > 1 else ACC)
            rl.draw_rectangle_lines_ex(rl.Rectangle(a[0], a[1], a[2] - a[0], a[3] - a[1]), 2 * px, ACC)
            dim = C(0, 0, 0, 80)
            big = 2.0 * max(x1 - x0, y1 - y0) + 2000.0
            rl.draw_rectangle_rec(rl.Rectangle(a[0] - big, a[1] - big, big * 2 + a[2] - a[0], big), dim)
            rl.draw_rectangle_rec(rl.Rectangle(a[0] - big, a[3], big * 2 + a[2] - a[0], big), dim)
            rl.draw_rectangle_rec(rl.Rectangle(a[0] - big, a[1], big, a[3] - a[1]), dim)
            rl.draw_rectangle_rec(rl.Rectangle(a[2], a[1], big, a[3] - a[1]), dim)
        if self.drag and self.drag[0] == "area":
            sx, sy = self.drag[1]
            mx, my = self.to_world(*self._mouse())
            rl.draw_rectangle_lines_ex(rl.Rectangle(min(sx, mx), min(sy, my), abs(mx - sx), abs(my - sy)), 2 * px, ACC2)
        for inc in self.scenario.get("incidents", ()):
            rl.draw_circle_lines(int(inc[2]), int(inc[3]), max(4.0, 8 * px), ACC2)
        self._draw_selection(px)
        rl.end_mode_2d()
        # screen-space labels
        if self.ov["names"] and z > 0.45:
            used = []
            for x, y, h, nm, rank in self.names:
                if rank < (0 if z > 1.2 else 2) or not (x0 < x < x1 and y0 < y < y1):
                    continue
                v = rl.get_world_to_screen_2d(rl.Vector2(x, y), self.cam)
                if any(abs(v.x - ux) < 120 and abs(v.y - uy) < 18 for ux, uy in used):
                    continue
                used.append((v.x, v.y))
                tw = self.tw(nm, 13)
                rl.draw_rectangle(int(v.x - tw / 2 - 3), int(v.y - 8), int(tw + 6), 17, C(16, 18, 23, 170))
                self.text(nm, v.x - tw / 2, v.y - 8, 13, C(220, 224, 232))
        rl.end_scissor_mode()
        # scale bar + legend
        self._scale_bar(mw, TOP + mh)
        self._legend(mw)

    def _wtext(self, s, x, y, size, col):
        v = rl.get_world_to_screen_2d(rl.Vector2(x, y), self.cam)
        rl.end_mode_2d()
        self.text(s, v.x, v.y, size, col, bold=True)
        rl.begin_mode_2d(self.cam)

    def _box(self, x, y, h, hl, hw, col, outline):
        rl.draw_rectangle_pro(rl.Rectangle(x, y, hl * 2, hw * 2), rl.Vector2(hl, hw), math.degrees(h), col)
        if outline is not None:
            c, s = math.cos(h), math.sin(h)
            pts = [(x + c * u - s * v, y + s * u + c * v) for u, v in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                rl.draw_line_v(rl.Vector2(*a), rl.Vector2(*b), C(outline.r, outline.g, outline.b, 150))

    def _vcol(self, c, st):
        mode = self.vcol
        if mode == "Speed":
            e = self.world.edges[c.e]
            return ramp(abs(c.v) / max(1.0, e["speed"]))
        if mode == "Standing time":
            s = st["stand"] if st else 0.0
            return C(90, 200, 120) if s < 1 else heat(min(1.0, s / 40.0))
        if mode == "Driver pace":
            return ramp((c.pace - 0.6) / 0.6)
        return STYLE_COL.get(vehicles.STYLE[c.kind], C(150, 160, 180))

    def _marks(self, c, col, px, st):
        hl = vehicles.HALF_L[c.kind]
        ch, sh = math.cos(c.h), math.sin(c.h)
        fx, fy = c.x + ch * hl, c.y + sh * hl
        rl.draw_line_ex(rl.Vector2(fx - sh * 0.6, fy + ch * 0.6), rl.Vector2(fx + sh * 0.6, fy - ch * 0.6), 0.35, C(255, 255, 230))
        if c.braking or abs(c.v) < 0.3:
            bx, by = c.x - ch * hl, c.y - sh * hl
            rl.draw_line_ex(rl.Vector2(bx - sh * 0.7, by + ch * 0.7), rl.Vector2(bx + sh * 0.7, by - ch * 0.7), 0.4, C(255, 40, 40))
        if c.indicator and int(time.time() * 3) % 2:
            side = 1 if c.indicator > 0 else -1
            ix, iy = c.x + ch * hl * 0.8 + sh * side * 1.0, c.y + sh * hl * 0.8 - ch * side * 1.0
            rl.draw_circle_v(rl.Vector2(ix, iy), 0.4, C(255, 170, 30))
        if self.ov["stuck"] and st and st["stand"] > 25:
            rl.draw_circle_lines(int(c.x), int(c.y), 3.5, C(255, 60, 200))
        if self.ov["intent"] and c.nxt is not None:
            ne = self.world.edges[c.nxt[0]]
            p = ne["pts"][min(2, len(ne["pts"]) - 1)] if c.nxt[1] == 1 else ne["pts"][max(-3, -len(ne["pts"]))]
            rl.draw_line_ex(rl.Vector2(c.x, c.y), rl.Vector2(p[0], p[1]), 1.5 * px, C(col.r, col.g, col.b, 110))

    def _draw_selection(self, px):
        if not self.sel:
            return
        kind, o = self.sel
        w = self.world
        if kind in ("car", "body"):
            rl.draw_circle_lines(int(o.x), int(o.y), max(4.0, 14 * px), ACC2)
            if kind == "car":
                e = w.edges[o.e]
                for a, b in zip(e["pts"], e["pts"][1:]):
                    rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), 2 * px, C(255, 170, 60, 140))
        elif kind == "node":
            x, y = self.lab.node_xy.get(o, (0, 0))
            rl.draw_circle_lines(int(x), int(y), max(8.0, 16 * px), ACC2)
            for i in self.lab.lights.nodes.get(o, (None, ()))[1]:
                it = self.lab.lights.items[i]
                rl.draw_circle_lines(int(it[4]), int(it[5]), max(2.0, 6 * px), ACC2)
        elif kind == "edge":
            e = w.edges[o]
            for a, b in zip(e["pts"], e["pts"][1:]):
                rl.draw_line_ex(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], b[1]), max(e["w"] + 2, 4 * px), C(255, 170, 60, 110))

    def _scale_bar(self, mw, ybot):
        z = self.cam.zoom
        target = 120 / z
        nice = min((10, 20, 50, 100, 200, 500, 1000, 2000, 5000), key=lambda v: abs(v - target))
        L = nice * z
        x, y = 14, ybot - 26
        rl.draw_rectangle(int(x - 4), int(y - 18), int(L + 60), 30, C(16, 18, 23, 180))
        rl.draw_line_ex(rl.Vector2(x, y), rl.Vector2(x + L, y), 3, FG)
        self.text(f"{nice} m", x + L + 6, y - 9, 14, FG)
        wx, wy = self.to_world(*self._mouse())
        self.text(f"({wx:.0f}, {wy:.0f})   zoom {z:.2f} px/m", x, y - 18, 12, MUT)

    def _legend(self, mw):
        items = []
        if self.layer == "Road class":
            items = [(CLS_COL[k], k) for k in ("motorway", "trunk", "primary", "secondary", "tertiary", "residential", "service")]
        elif self.layer == "Speed / limit":
            items = [(ramp(0), "standing"), (ramp(0.5), "half the limit"), (ramp(1), "at the limit")]
        elif self.layer == "Density":
            items = [(heat(0.1), "8 veh/km/lane"), (heat(0.5), "40"), (heat(1), "80+")]
        elif self.layer in ("Standing heat", "Conflicts"):
            items = [(heat(0.1), "low"), (heat(1), "high")] + ([(BAD, "collision"), (WARN, "near miss")] if self.layer == "Conflicts" else [])
        elif self.layer == "Junction LOS":
            items = [(LOS_C[k], "LOS " + k) for k in "ABCDEF"]
        if self.vcol == "Type":
            items += [(STYLE_COL["hatch"], "car"), (STYLE_COL["van"], "van"), (STYLE_COL["truck"], "truck"), (STYLE_COL["bus"], "bus"),
                      (C(240, 60, 60), "emergency"), (C(255, 60, 200), "obstacle")]
        x, y = mw - 170, TOP + 10
        rl.draw_rectangle_rounded(rl.Rectangle(x - 8, y - 6, 166, 12 + 18 * len(items)), 0.1, 6, C(16, 18, 23, 200))
        for i, (col, label) in enumerate(items):
            rl.draw_rectangle(int(x), int(y + i * 18 + 3), 12, 10, col)
            self.text(label, x + 18, y + i * 18, 13, FG)

    def _mouse(self):
        m = rl.get_mouse_position()
        return m.x, m.y

    # ------------------------------------------------------------------ map input
    def map_input(self):
        mx, my = self._mouse()
        mw = self.W - RIGHT
        inside = 0 <= mx < mw and TOP <= my < self.H - BOTTOM and not self.help and not self.confirm
        if inside and not self.wheel_used:
            wh = rl.get_mouse_wheel_move()
            if wh:
                before = rl.get_screen_to_world_2d(rl.Vector2(mx, my), self.cam)
                self.cam.zoom = max(0.03, min(30.0, self.cam.zoom * (1.18 ** wh)))
                after = rl.get_screen_to_world_2d(rl.Vector2(mx, my), self.cam)
                self.cam.target = rl.Vector2(self.cam.target.x + before.x - after.x, self.cam.target.y + before.y - after.y)
        if inside and (rl.is_mouse_button_down(rl.MOUSE_BUTTON_RIGHT) or rl.is_mouse_button_down(rl.MOUSE_BUTTON_MIDDLE)):
            d = rl.get_mouse_delta()
            self.cam.target = rl.Vector2(self.cam.target.x - d.x / self.cam.zoom, self.cam.target.y - d.y / self.cam.zoom)
            self.follow = False
        wx, wy = self.to_world(mx, my)
        if inside and not self.mouse_used:
            self._hover(wx, wy)
        if self.drag and self.drag[0] == "area" and rl.is_mouse_button_released(rl.MOUSE_BUTTON_LEFT):
            sx, sy = self.drag[1]
            self.drag = None
            if abs(wx - sx) > 20 and abs(wy - sy) > 20:
                self.scenario["area"] = [round(v, 1) for v in core.norm_area([sx, sy, wx, wy])]
                ts = core.tiles(self.scenario["area"])
                cx, cy = (sx + wx) / 2, (sy + wy) / 2
                self.scenario["tile"] = min(range(len(ts)), key=lambda i: ((ts[i][0] + ts[i][2]) / 2 - cx) ** 2 + ((ts[i][1] + ts[i][3]) / 2 - cy) ** 2)
                self.restart()
                self.fit_area()
                self.say(f"study area set: {len(ts)} tile(s); live view runs the highlighted one, batches run them all", 5)
            return
        if not inside or self.mouse_used or not rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            return
        lab = self.lab
        tool = self.tool
        if tool == "select":
            self.sel = self.pick(wx, wy)
            if self.sel:
                self.tab = "Inspect"
        elif tool == "close":
            ei = self.pick_edge(wx, wy)
            if ei is not None:
                mid = traffic_tuning.edge_mid(self.world, ei)
                cl = self.scenario.setdefault("closures", [])
                hit = [c for c in cl if math.hypot(c[0] - mid[0], c[1] - mid[1]) < 1.0]
                if hit:
                    cl.remove(hit[0])
                    self.say("road reopened")
                else:
                    cl.append([round(mid[0], 1), round(mid[1], 1)])
                    self.say("road closed")
                self.retune()
        elif tool == "obstacle":
            p = lab.lane_pose(wx, wy)
            if p:
                self.scenario.setdefault("obstacles", []).append([round(p[0], 1), round(p[1], 1), round(p[2], 3), 1])
                lab.add_obstacle(p[0], p[1], p[2], 1)
        elif tool == "remove":
            if lab.remove_obstacle_near(wx, wy):
                obs = self.scenario.get("obstacles", [])
                for o in list(obs):
                    if math.hypot(o[0] - wx, o[1] - wy) < 6:
                        obs.remove(o)
                self.say("obstacle removed")
        elif tool == "amb":
            self.say("ambulance called" if lab.collapse((wx, wy)) else "no walking pedestrian in the study area")
        elif tool == "fire":
            self.say("car fire: fire brigade called" if lab.fire(wx, wy) else "no road there")
        elif tool == "breakdown":
            self.say("breakdown" if lab.breakdown(wx, wy) else "no moving car in the study area")
        elif tool == "area":
            self.drag = ("area", (wx, wy))
        elif tool == "tile":
            ts = core.tiles(self.scenario["area"])
            for i, t in enumerate(ts):
                if t[0] <= wx <= t[2] and t[1] <= wy <= t[3]:
                    self.scenario["tile"] = i
                    self.restart()
                    self.say(f"live view now simulates tile {i + 1} of {len(ts)}")
        elif tool == "schedule":
            kind = getattr(self, "sched_kind", "fire")
            at = max(0.0, lab.t - lab.warm)
            self.scenario.setdefault("incidents", []).append([round(at, 1), kind, round(wx, 1), round(wy, 1)])
            self.say(f"{kind} scheduled at +{at:.0f} s after warm-up (every run of this scenario)")

    def pick(self, x, y):
        import actors
        lab = self.lab
        best, bd = None, 4.0
        for c in lab.sim.traffic.cars:
            for p in actors.parts(c):
                d = core.Metrics._box_dist(p, x, y)
                if d < bd:
                    best, bd = ("car", c), d
        for b in lab.sim.bodies:
            if b is lab.sim.car:
                continue
            for p in actors.parts(b):
                d = core.Metrics._box_dist(p, x, y)
                if d < bd:
                    best, bd = ("body", b), d
        if best:
            return best
        T = lab.sim.traffic
        bn, bd = None, 1e9
        for n, r in T.junctions.items():
            nx, ny = lab.node_xy.get(n, (1e9, 1e9))
            d = math.hypot(nx - x, ny - y)
            if d < max(6.0, r + 2) and d < bd:
                bn, bd = n, d
        if bn is not None:
            return ("node", bn)
        ei = self.pick_edge(x, y)
        return ("edge", ei) if ei is not None else None

    def pick_edge(self, x, y):
        w = self.world
        best, bd = None, 1e9
        for kind, ei in self.cells.get((int(x // 100), int(y // 100)), ()):
            if kind != "e" or not w.edges[ei]["drive"]:
                continue
            e = w.edges[ei]
            for a, b in zip(e["pts"], e["pts"][1:]):
                dx, dy = b[0] - a[0], b[1] - a[1]
                L2 = dx * dx + dy * dy or 1.0
                u = max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
                d = math.hypot(a[0] + dx * u - x, a[1] + dy * u - y)
                if d < bd and d < e["w"] / 2 + 3:
                    best, bd = ei, d
        return best

    def _hover(self, wx, wy):
        if self.cam.zoom < 0.5:
            return
        s = self.pick(wx, wy) if self.tool == "select" else None
        if s and s[0] == "car":
            c = s[1]
            e = self.world.edges[c.e]
            st = self.lab.m.car.get(c)
            self.hint = (f"{vehicles.IDS[c.kind]} ({vehicles.STYLE[c.kind]})  {abs(c.v) * 3.6:.0f} km/h of {e['speed'] * 3.6:.0f}  "
                         f"standing {st['stand'] if st else 0:.0f} s  {e['cls']}")
        elif s and s[0] == "node":
            m = self.lab.m
            cd = m.cdelay.get(s[1])
            self.hint = f"junction {s[1]}: {m.passes.get(s[1], 0)} through, delay {sum(cd) / len(cd) if cd else 0:.1f} s"

    # ================================================================== top bar
    def draw_top(self):
        rl.draw_rectangle(0, 0, self.W, TOP, PANEL)
        rl.draw_line(0, TOP - 1, self.W, TOP - 1, LINE)
        self.text("Skopje 242  ·  Traffic Lab", 14, 12, 19, FG, bold=True)
        x = 270
        if self.button("Pause" if self.play else "Play", x, 9, 70, active=self.play):
            self.play = not self.play
        x += 76
        if self.button("Step", x, 9, 52):
            self.play = False
            for _ in range(4):
                self.lab.step()
        x += 62
        for s in SPEEDS:
            if self.button("max" if s == 0 else f"x{s}", x, 9, 44, active=self.speed == s):
                self.speed = s
            x += 48
        x += 10
        if self.button("Restart", x, 9, 72, col=C(150, 90, 30) if self.pending_restart else None):
            self.restart()
        x += 78
        if self.button("New seed", x, 9, 82):
            self.restart(int(self.settings["seed0"]) + 1)
        x += 90
        lab = self.lab
        phase = "warm-up" if lab.t < lab.warm else ("measuring" if not lab.done else "past duration")
        self.text(f"t = {lab.t:6.1f} s  ({phase})   seed {self.settings['seed0']}   hour {lab.sim.clock.hour:4.1f}", x, 14, 15, FG)
        x += 380
        if self.pending_restart:
            self.text("restart to apply: " + ", ".join(self.pending_restart), x, 14, 14, ACC2)
        if self.button("Help (F1)", self.W - 190, 9, 90):
            self.help = True
        if self.button("Quit", self.W - 92, 9, 80, col=C(120, 40, 40)):
            self.quit = True

    # ================================================================== KPI strip
    def draw_bottom(self):
        y0 = self.H - BOTTOM
        mw = self.W - RIGHT
        rl.draw_rectangle(0, y0, mw, BOTTOM, PANEL)
        rl.draw_line(0, y0, mw, y0, LINE)
        k = self.kpi
        lab = self.lab
        inside = sum(1 for c in lab.sim.traffic.cars if lab.m._in(c.x, c.y))
        tiles = [
            ("Cars in area", f"{inside}", f"target {lab.sim.traffic.target}", None),
            ("Mean speed", fmt(k.get("speed_kmh")), "km/h", None),
            ("Speed / limit", fmt(k.get("speed_ratio"), 2), "", None),
            ("Standing", fmt((k.get("stopped_share") or 0) * 100, 0) + " %", f"> 4 s: {fmt((k.get('stuck4_share') or 0) * 100, 0)} %", None),
            ("Throughput", fmt(k.get("throughput_h")), "junction passes/h", None),
            ("Delay", fmt(k.get("delay_s_km"), 0), "s per km", None),
            ("Jams / gridlock", f"{k.get('jams', 0)} / {fmt(k.get('gridlock_s'), 0)}", "> 25 s / s", None),
            ("Collisions", f"{k.get('collisions', 0)}", f"ghost {k.get('collisions_ghost', 0)}", BAD if k.get("collisions") else None),
            ("Near misses", f"{k.get('near_misses', 0)}", f"serious {k.get('near_serious', 0)}", WARN if k.get("near_misses") else None),
            ("Red runs / peds", f"{k.get('redruns', 0)} / {k.get('ped_conflicts', 0)}", "", None),
            ("Emergency", f"{k.get('ems_arrived', 0)}/{k.get('ems_calls', 0)}", f"resp {fmt(k.get('ems_response'), 0)} s", None),
            ("Scores E/S/V", f"{fmt(k.get('score_efficiency'), 0)}/{fmt(k.get('score_safety'), 0)}/{fmt(k.get('score_speed'), 0)}", "efficiency safety speed", None),
        ]
        n = len(tiles)
        tw = (mw - 16) / n
        for i, (label, val, sub, col) in enumerate(tiles):
            x = 8 + i * tw
            rl.draw_rectangle_rounded(rl.Rectangle(x + 2, y0 + 10, tw - 4, BOTTOM - 20), 0.12, 6, PANEL2)
            self.text(label, x + 10, y0 + 18, 13, MUT)
            vs = 24
            while vs > 14 and self.tw(val, vs, bold=True) > tw - 20:
                vs -= 2
            self.text(val, x + 10, y0 + 38 + (24 - vs) / 2, vs, col or FG, bold=True)
            self.text(font.fit(sub, 12, tw - 18), x + 10, y0 + 72, 12, MUT)
        if not k:
            self.text("measuring starts after the warm-up", 12, y0 - 22, 14, MUT)

    # ================================================================== right panel
    def draw_panel(self):
        x0 = self.W - RIGHT
        rl.draw_rectangle(x0, TOP, RIGHT, self.H - TOP, PANEL)
        rl.draw_line(x0, TOP, x0, self.H, LINE)
        y = TOP + 8
        for row in (TABS_A, TABS_B):
            bw = (RIGHT - 16) / len(row)
            for i, t in enumerate(row):
                label = t if self.tw(t, 13) < bw - 6 else t[:5]
                if self.button(label, x0 + 8 + i * bw, y, bw - 3, 26, active=self.tab == t, size=13):
                    self.tab = t
            y += 30
        y += 4
        top = y
        h = self.H - top - 8
        rl.begin_scissor_mode(x0, top, RIGHT, h)
        sy = top - self.scroll[self.tab]
        end = getattr(self, "tab_" + self.tab.lower(), self.tab_settings)(x0 + 14, sy, RIGHT - 28)
        rl.end_scissor_mode()
        content = end - sy
        if self.over(x0, top, RIGHT, h) and not self.wheel_used and self.slider_id is None:
            wh = rl.get_mouse_wheel_move()
            if wh:
                self.scroll[self.tab] = max(0.0, min(max(0.0, content - h + 20), self.scroll[self.tab] - wh * 50))
        if content > h:
            f = h / content
            rl.draw_rectangle(int(self.W - 6), int(top + self.scroll[self.tab] / content * h), 4, int(h * f), LINE)

    def head(self, s, x, y, w):
        self.text(s, x, y, 16, FG, bold=True)
        rl.draw_line(int(x), int(y + 22), int(x + w), int(y + 22), LINE)
        return y + 30

    # ---------------------------------------------------------- settings tabs
    def tab_settings(self, x, y, w):
        tab = self.tab
        y = self.head(f"{tab} settings", x, y, w)
        notes = {
            "Run": "The run itself. Cars/pedestrians are the game's base counts (the game scales them by the hour). "
                   "Settings marked orange differ from the game's current value; right-click a slider to reset it.",
            "Drivers": "actors.Traffic constants: how drivers behave. Applied live to the running simulation.",
            "Junctions": "Junction priority / approach constants of actors.Traffic. Per-junction signal changes: click a junction (Inspect).",
            "Signals": "signals.py: every lit junction runs this cycle; neighbours are offset into a green wave.",
            "Roads": "Speed-limit scale per road class. Close roads with the Edit tab.",
            "Fleet": "The vehicle mix: scales vehicles.TRAFFIC_W per style group (the collision boxes stay the game's).",
            "Transit": "City buses (JSP lines) and trains with level crossings.",
            "Emergency": "Random incidents inside the study area during the measured time; place them by hand on the Edit tab.",
            "Advanced": "Every other numeric actors.Traffic constant, found in the game code itself: a rule added to the game "
                        "appears here and can be compared in a batch.",
        }
        for ln in font.wrap(notes.get(tab, ""), 13, w):
            self.text(ln, x, y, 13, MUT)
            y += 17
        y += 8
        changed = False
        for p in params.all_params():
            if p.tab != tab:
                continue
            v = self.settings.get(p.key, p.default)
            if p.kind == "bool":
                nv = self.toggle(p.label, x, y, v, w, p.help)
                y += 30
            else:
                nv = self.slider(p.key, p.label, x, y, w, v, p.lo, p.hi, p.step, p.default, p.help, p.kind == "int")
                y += 40
            if nv != v:
                self.settings[p.key] = nv
                self.last_key = p.key
                changed = True
        if changed:
            self._dirty = True
        if getattr(self, "_dirty", False) and self.slider_id is None:
            self._dirty = False
            self.retune()
        y += 6
        if self.button("Reset this tab to the game's values", x, y, w):
            for p in params.all_params():
                if p.tab == tab:
                    self.settings[p.key] = p.default
            self.retune()
        return y + 40

    # ---------------------------------------------------------- Live
    def tab_live(self, x, y, w):
        lab, m = self.lab, self.lab.m
        y = self.head("Live measurements (study area)", x, y, w)
        ser = m.series
        for idx, title, scale, unit in ((2, "Mean speed", 3.6, "km/h"), (3, "Standing share", 100, "%"), (4, "Junction passes / 5 s", 1, ""),
                                        (1, "Cars in area", 1, "")):
            y = self.chart(x, y, w, 70, title, [[(r[0], r[idx] * scale) for r in ser]], unit)
        y = self.chart(x, y, w, 70, "Collisions (red) and near misses (yellow) / 5 s",
                       [[(r[0], r[5]) for r in ser], [(r[0], r[6]) for r in ser]], "", cols=[BAD, WARN])
        y = self.scatter(x, y, w, 150, "Fundamental diagram: flow vs density (per road, 10 s)", [(k, q) for k, q, _s in m.fd],
                         "veh/km/lane", "veh/h/lane")
        y = self.hist(x, y, w, 70, "Speed distribution (2 m/s bins)", m.speed_hist)
        k = self.kpi
        mix = k.get("los_mix", {})
        y = self.head("Junction level of service", x, y + 4, w)
        tot = sum(mix.values()) or 1
        xx = x
        for L in "ABCDEF":
            n = mix.get(L, 0)
            ww = w * n / tot
            if ww > 0:
                rl.draw_rectangle(int(xx), int(y), int(ww), 18, LOS_C[L])
                if ww > 18:
                    self.text(f"{L}{n}", xx + 3, y + 1, 13, C(15, 15, 15), bold=True)
            xx += ww
        y += 28
        y = self.head("Worst junctions (control delay)", x, y, w)
        for j in sorted(k.get("junctions", []), key=lambda j: -j["delay"])[:8]:
            self.text(f"{'lit ' if j['signal'] else ''}({j['x']}, {j['y']})", x, y, 13, FG)
            self.text(f"{j['veh_h']} veh/h   {j['delay']} s   q {j['queue_max']} m", x + 150, y, 13, MUT)
            rl.draw_rectangle(int(x + w - 22), int(y), 20, 16, LOS_C[j["los"]])
            self.text(j["los"], x + w - 17, y, 13, C(15, 15, 15), bold=True)
            if self.clicked(x, y, w, 18):
                self.sel = ("node", j["node"])
                self.cam.target = rl.Vector2(j["x"], j["y"])
                self.tab = "Inspect"
            y += 20
        y = self.head("Event log", x, y + 6, w)
        ev = [(t, s, FG) for t, s in lab.log] + [(t, f"collision {d} m at ({cx}, {cy}){' (ghost)' if kind == 'ghost' else ''}", BAD)
                                                 for t, cx, cy, d, kind in m.collisions[-30:]] + \
             [(t, f"red-light run at ({cx}, {cy})", C(255, 90, 210)) for t, cx, cy, _n in m.redruns[-20:]] + \
             [(t, f"jam > 25 s at ({cx}, {cy})", ACC2) for t, cx, cy, _s in m.jams[-20:]]
        for t, s, col in sorted(ev, key=lambda r: -r[0])[:30]:
            self.text(f"{t:6.1f}  {s}"[:60], x, y, 13, col)
            y += 17
        return y + 10

    def chart(self, x, y, w, h, title, lines, unit="", cols=None):
        self.text(title, x, y, 13, MUT)
        y += 18
        rl.draw_rectangle(int(x), int(y), int(w), h, PANEL2)
        pts = [p for ln in lines for p in ln]
        if pts:
            t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts) or 1
            top = max(p[1] for p in pts) * 1.1 or 1
            for li, ln in enumerate(lines):
                col = (cols or SERIES)[li % len(cols or SERIES)]
                prev = None
                for t, v in ln:
                    pt = rl.Vector2(x + (t - t0) / max(1e-6, t1 - t0) * w, y + h - v / top * h)
                    if prev is not None:
                        rl.draw_line_ex(prev, pt, 2, col)
                    prev = pt
            last = lines[0][-1][1] if lines[0] else 0
            self.text(f"{last:.1f} {unit}   max {top / 1.1:.1f}", x + 6, y + 4, 12, FG)
        else:
            self.text("(after the warm-up)", x + 6, y + 4, 12, MUT)
        return y + h + 10

    def scatter(self, x, y, w, h, title, pts, xl, yl):
        self.text(title, x, y, 13, MUT)
        y += 18
        rl.draw_rectangle(int(x), int(y), int(w), h, PANEL2)
        if pts:
            kx = max(p[0] for p in pts) * 1.05 or 1
            qy = max(p[1] for p in pts) * 1.1 or 1
            for k, q in pts[-1500:]:
                rl.draw_circle_v(rl.Vector2(x + k / kx * w, y + h - q / qy * h), 1.6, C(80, 150, 255, 120))
            bins = collections.defaultdict(list)
            for k, q in pts:
                bins[int(k / kx * 12)].append(q)
            prev = None
            for b in sorted(bins):
                if len(bins[b]) >= 3:
                    pt = rl.Vector2(x + (b + 0.5) / 12 * w, y + h - sum(bins[b]) / len(bins[b]) / qy * h)
                    if prev:
                        rl.draw_line_ex(prev, pt, 2.5, ACC2)
                    prev = pt
            self.text(f"x: {xl} (max {kx:.0f})   y: {yl} (max {qy:.0f})", x + 6, y + 4, 12, FG)
        return y + h + 10

    def hist(self, x, y, w, h, title, hist):
        self.text(title, x, y, 13, MUT)
        y += 18
        rl.draw_rectangle(int(x), int(y), int(w), h, PANEL2)
        n = len(hist)
        top = max(hist) or 1
        for i, v in enumerate(hist):
            bh = v / top * (h - 4)
            rl.draw_rectangle(int(x + i * w / n + 1), int(y + h - bh), int(w / n - 2), int(bh), ACC)
        self.text("0", x + 2, y + h + 1, 11, MUT)
        self.text(f"{n * 2 * 3.6:.0f} km/h", x + w - 50, y + h + 1, 11, MUT)
        return y + h + 18

    # ---------------------------------------------------------- Inspect
    def tab_inspect(self, x, y, w):
        if not self.sel:
            y = self.head("Inspect", x, y, w)
            for ln in font.wrap("Pick the Select tool (Edit tab) and click a vehicle, a junction or a road on the map. "
                                "Junctions show their throughput, delay, level of service, queues and signal controls.", 14, w):
                self.text(ln, x, y, 14, MUT)
                y += 19
            return y
        kind, o = self.sel
        lab, w_ = self.lab, self.world
        rows = []
        if kind == "car":
            e = w_.edges[o.e]
            st = lab.m.car.get(o)
            if o not in lab.sim.traffic.cars:
                self.sel = None
                return y
            y = self.head(f"{vehicles.IDS[o.kind]}", x, y, w)
            L, W_ = vehicles.DIMS[o.kind][0], vehicles.DIMS[o.kind][1]
            rows = [("style", vehicles.STYLE[o.kind]), ("collision box", f"{L:.2f} x {W_:.2f} m ({len(__import__('actors').parts(o))} part(s))"),
                    ("speed", f"{abs(o.v) * 3.6:.1f} km/h  (limit {e['speed'] * 3.6:.0f})"), ("pace", f"{o.pace:.2f} x limit"),
                    ("road", f"{e['cls']}  edge {o.e}  dir {o.d}  lane {o.lidx}"), ("standing", f"{st['stand']:.1f} s" if st else "-"),
                    ("stuck timer", f"{o.stuck:.1f} s"), ("ghosting", f"{o.ghost:.1f} s"), ("blocked by", type(o.blk).__name__ if o.blk is not None else "-"),
                    ("next turn", f"{math.degrees(o.turn):.0f} deg" if o.nxt else "-"), ("reversing", f"{o.rev:.1f} s"),
                    ("swerve / yield", f"{o.avoid:.2f} / {o.yld:.2f} m"), ("in area since", f"{lab.t - st['t0']:.0f} s" if st else "-"),
                    ("distance", f"{st['m']:.0f} m" if st else "-"), ("delay", f"{st['dl']:.1f} s" if st else "-")]
            for k, v in rows:
                self.text(k, x, y, 14, MUT)
                self.text(v, x + 130, y, 14, FG)
                y += 20
            if self.button("Unfollow (F)" if self.follow else "Follow (F)", x, y + 6, 140):
                self.follow = not self.follow
            if self.button("Break down here", x + 150, y + 6, 150):
                lab.breakdown(o.x, o.y)
            return y + 50
        if kind == "body":
            y = self.head(f"{vehicles.IDS[o.kind]} (physics body)", x, y, w)
            what = "service vehicle" + (" (siren)" if o.siren else "") if o.service else (
                "kerb-parked" if o.parked_idx is not None else "obstacle / wreck" if o.health <= 0 or o in lab.obstacles else "body")
            for k, v in (("what", what), ("speed", f"{o.speed * 3.6:.1f} km/h"), ("health", f"{o.health:.0f}"),
                         ("burning", f"{o.burn:.0f} s" if o.burn and not o.out else "no")):
                self.text(k, x, y, 14, MUT)
                self.text(v, x + 130, y, 14, FG)
                y += 20
            if self.button("Follow (F)", x, y + 6, 140):
                self.follow = not self.follow
            return y + 50
        if kind == "edge":
            e = w_.edges[o]
            r = w_.roads[e["road"]] if 0 <= e.get("road", -1) < len(w_.roads) else {}
            y = self.head(r.get("name") or f"road edge {o}", x, y, w)
            from roadwidth import lane_count
            rows = [("class", e["cls"]), ("length", f"{e['len']:.0f} m"), ("width", f"{e['w']:.1f} m"),
                    ("lanes", f"{lane_count(e, 1)}" + ("" if e["ow"] else f" + {lane_count(e, -1)}")), ("one-way", "yes" if e["ow"] else "no"),
                    ("limit", f"{e['speed'] * 3.6:.0f} km/h (lab scale applied)"), ("bridge", "yes" if e["bridge"] else "no"),
                    ("live speed / limit", fmt(lab.m.edge_v.get(o), 2)), ("live density", f"{fmt(lab.m.edge_k.get(o))} veh/km/lane"),
                    ("closed", "YES" if o in lab.closed else "no")]
            for k, v in rows:
                self.text(k, x, y, 14, MUT)
                self.text(v, x + 150, y, 14, FG)
                y += 20
            if self.button("Reopen road" if o in lab.closed else "Close road", x, y + 6, 160):
                mid = traffic_tuning.edge_mid(w_, o)
                cl = self.scenario.setdefault("closures", [])
                hit = [c for c in cl if math.hypot(c[0] - mid[0], c[1] - mid[1]) < 1.0]
                if hit:
                    cl.remove(hit[0])
                else:
                    cl.append([round(mid[0], 1), round(mid[1], 1)])
                self.retune()
            return y + 50
        # junction
        node = o
        m = lab.m
        jx, jy = lab.node_xy.get(node, (0, 0))
        lg = lab.lights
        lit = node in lg.nodes
        y = self.head(f"Junction {node}  ({jx:.0f}, {jy:.0f})", x, y, w)
        cd = m.cdelay.get(node, [])
        d = sum(cd) / len(cd) if cd else 0.0
        hours = max(m.t, 1e-6) / 3600
        qs = [(k, m.queue_max[k], m.queue_sum[k] / max(1, m.nq)) for k, n in m.queue_node.items() if n == node]
        arms = [ei for ei, e in enumerate(w_.edges) if e["drive"] and node in (e["a"], e["b"])]
        rows = [("arms", f"{len(arms)}"), ("signalised", "yes" if lit else "no"), ("box half-width", f"{lab.sim.traffic.junctions.get(node, 0):.1f} m"),
                ("vehicles through", f"{m.passes.get(node, 0)}  ({m.passes.get(node, 0) / hours:.0f} veh/h)"),
                ("control delay", f"{d:.1f} s/veh  (n={len(cd)})"), ("level of service", core.los(d, lit)),
                ("red-light runs", f"{sum(1 for r in m.redruns if r[3] == node)}")]
        for k, v in rows:
            self.text(k, x, y, 14, MUT)
            self.text(v, x + 150, y, 14, FG)
            y += 20
        y = self.head("Approach queues", x, y + 6, w)
        for (ei, d_), qm, qa in sorted(qs, key=lambda r: -r[1]):
            nm = (w_.roads[w_.edges[ei]["road"]].get("name") if 0 <= w_.edges[ei].get("road", -1) < len(w_.roads) else "") or w_.edges[ei]["cls"]
            st = lg.state_of(ei, int(d_ == 1))
            rl.draw_circle(int(x + 6), int(y + 8), 5, SIG_C[st])
            self.text(f"{nm}"[:26], x + 16, y, 13, FG)
            self.text(f"max {qm:.0f} m  mean {qa:.0f} m", x + 230, y, 13, MUT)
            y += 18
        if lit:
            y = self.head("Signal plan for this crossing", x, y + 8, w)
            jl = self.scenario.setdefault("junctions", [])
            cx, cy = lg.nodes[node][0]
            cur = next((j for j in jl if math.hypot(j["x"] - cx, j["y"] - cy) < 1.0), None)
            import signals as sigmod
            base = {"off": False, "offset": 0.0, "green": float(sigmod.GREEN), "cycle": float(sigmod.CYCLE)}
            v = dict(base)
            v.update(cur or {})
            nv = dict(v)
            nv["off"] = self.toggle("Lights off (priority rules instead)", x, y, v["off"], w)
            y += 30
            nv["offset"] = self.slider("j_off", "Offset (s)", x, y, w, v["offset"], 0.0, 150.0, 1.0, 0.0)
            y += 40
            nv["green"] = self.slider("j_green", "Major green (s)", x, y, w, v["green"], 5.0, 100.0, 1.0, base["green"])
            y += 40
            nv["cycle"] = self.slider("j_cycle", "Cycle (s)", x, y, w, v["cycle"], 20.0, 150.0, 1.0, base["cycle"])
            y += 40
            if nv != v:
                if cur is None:
                    cur = {"x": round(cx, 1), "y": round(cy, 1)}
                    jl.append(cur)
                cur.update(nv)
                self._jdirty = True
            if getattr(self, "_jdirty", False) and self.slider_id is None:
                self._jdirty = False
                self.retune()
            if cur is not None and self.button("Back to the game's plan", x, y, 200):
                jl.remove(cur)
                self.retune()
            y += 34
            st0 = [lg.state(i) for i in lg.nodes[node][1]]
            self.text("heads now: " + " ".join("GYR"[s] for s in st0), x, y, 13, MUT)
            y += 20
        return y + 10

    # ---------------------------------------------------------- Edit
    def tab_edit(self, x, y, w):
        y = self.head("Map tools", x, y, w)
        for key, label, help in TOOLS:
            if self.button(label, x, y, w, 28, active=self.tool == key):
                self.tool = key
            if self.over(x, y, w, 28):
                self.hint = help
            y += 32
        if self.tool == "schedule":
            self.text("kind of scheduled incident:", x, y + 4, 13, MUT)
            y += 22
            for i, k in enumerate(("amb", "fire", "breakdown")):
                if self.button(k, x + i * 100, y, 94, 24, active=getattr(self, "sched_kind", "fire") == k):
                    self.sched_kind = k
            y += 32
        sc = self.scenario
        y = self.head("Scenario edits", x, y + 8, w)
        for label, n, key in (("closed roads", len(sc.get("closures", ())), "closures"), ("obstacles", len(sc.get("obstacles", ())), "obstacles"),
                              ("junction signal changes", len(sc.get("junctions", ())), "junctions"),
                              ("scheduled incidents", len(sc.get("incidents", ())), "incidents")):
            self.text(f"{n}  {label}", x, y + 4, 14, FG)
            if n and self.button("clear", x + w - 70, y, 70, 24):
                sc[key] = []
                if key == "obstacles":
                    for b in list(self.lab.obstacles):
                        self.lab.remove_obstacle_near(b.x, b.y, 0.5)
                self.retune()
            y += 30
        a = core.norm_area(self.scenario["area"])
        nt = len(core.tiles(self.scenario["area"]))
        self.text(f"study area {a[2] - a[0]:.0f} x {a[3] - a[1]:.0f} m, {nt} tile(s), centre ({(a[0] + a[2]) / 2:.0f}, {(a[1] + a[3]) / 2:.0f})", x, y + 6, 13, MUT)
        y += 26
        if self.button("Whole map", x, y, w / 2 - 4, 26):
            wd = self.world
            self.scenario["area"] = [-wd.hx + 50, -wd.hy + 50, wd.hx - 50, wd.hy - 50]
            self.scenario["tile"] = len(core.tiles(self.scenario["area"])) // 2
            self.restart()
            self.fit_area()
        if self.button("Back to one tile here", x + w / 2, y, w / 2, 26):
            cx, cy = self.cam.target.x, self.cam.target.y
            self.scenario["area"], self.scenario["tile"] = [cx - 300, cy - 300, cx + 300, cy + 300], 0
            self.restart()
            self.fit_area()
        y += 34
        for ln in font.wrap("The game simulates traffic only in a ~420 m bubble around the player, so a big study area is cut into "
                            "tiles of at most 700 m: the live view runs one tile (orange), batches and Explore run every tile x seed "
                            "on its own core and the report adds them up, with a per-tile table of the problem spots. "
                            "Batches run the scenario as it is; Apply to game writes the closures and signal changes.", 13, w):
            self.text(ln, x, y, 13, MUT)
            y += 17
        return y + 10

    # ---------------------------------------------------------- Layers
    def tab_layers(self, x, y, w):
        y = self.head("Map colouring", x, y, w)
        for i, L in enumerate(LAYERS):
            if self.button(L, x + (i % 2) * (w / 2), y, w / 2 - 4, 26, active=self.layer == L, size=14):
                self.layer = L
            if i % 2:
                y += 30
        y += 34
        y = self.head("Vehicle colouring", x, y, w)
        for i, L in enumerate(VCOL):
            if self.button(L, x + (i % 2) * (w / 2), y, w / 2 - 4, 26, active=self.vcol == L, size=14):
                self.vcol = L
            if i % 2:
                y += 30
        y += 6
        y = self.head("Overlays", x, y, w)
        labels = {"vehicles": "Vehicles", "boxes": "Collision box outlines (zoomed in)", "signals": "Signal heads", "peds": "Pedestrians",
                  "trains": "Rail, trains, level crossings", "stops": "Bus stops", "buildings": "Building outlines", "names": "Street names",
                  "area": "Study area", "intent": "Turn intentions (next edge)", "stuck": "Jam markers (> 25 s)",
                  "ems": "Emergency jobs and routes", "events": "Collision / red-run flashes", "parked": "Kerb-parked cars"}
        for k, label in labels.items():
            self.ov[k] = self.toggle(label, x, y, self.ov[k], w)
            y += 28
        return y + 10

    # ---------------------------------------------------------- Batch
    def tab_batch(self, x, y, w):
        y = self.head("Variants (each runs every seed)", x, y, w)
        for i, v in enumerate(list(self.variants)):
            col = SERIES[i % len(SERIES)]
            rl.draw_rectangle(int(x), int(y + 4), 10, 18, col)
            self.text(v["name"][:34], x + 16, y + 4, 14, FG)
            d = ", ".join(f"{k}={val}" for k, val in v["settings"].items()) or "(the current settings)"
            self.text(font.fit(d, 12, w - 90), x + 16, y + 22, 12, MUT)
            if i and self.button("x", x + w - 30, y + 4, 26, 24):
                self.variants.pop(i)
            y += 44
        if self.sweep:
            p = params.BY_KEY[self.sweep["key"]]
            self.text(f"+ sweep {p.label}: {self.sweep['from']:g} .. {self.sweep['to']:g} in {self.sweep['steps']} steps", x, y, 13, ACC2)
            if self.button("x", x + w - 30, y - 2, 26, 22):
                self.sweep = None
            y += 26
        if self.button("Add variant = current settings", x, y, w):
            diff = {k: v for k, v in self.settings.items() if k in params.BY_KEY and params.BY_KEY[k].tab not in ("Run",)
                    and v != params.BY_KEY[k].default}
            self.variants.append({"name": f"{chr(65 + len(self.variants))} " + (", ".join(f"{k}={v}" for k, v in diff.items())[:30] or "same"),
                                  "settings": diff})
        y += 34
        if self.button("Reset to one baseline", x, y, w / 2 - 4):
            self.variants, self.sweep = [{"name": "A current settings", "settings": {}}], None
        if self.button("Sweep last slider", x + w / 2, y, w / 2):
            key = getattr(self, "last_key", None) or "cycle"
            p = params.BY_KEY.get(key)
            if p and p.kind != "bool":
                self.sweep = {"key": key, "from": p.lo + (p.hi - p.lo) * 0.2, "to": p.lo + (p.hi - p.lo) * 0.8, "steps": 5}
        y += 40
        y = self.head("Comparison presets", x, y, w)
        for i, (name, vs, sw) in enumerate(PRESETS):
            if self.button(name, x + (i % 2) * (w / 2), y, w / 2 - 4, 26, size=13):
                self.variants = [dict(v) for v in vs]
                self.sweep = dict(sw) if sw else None
            if i % 2:
                y += 30
        y += 36
        y = self.head("Batch settings", x, y, w)
        for key in ("seeds", "duration", "warm", "workers"):
            p = params.BY_KEY[key]
            self.settings[key] = self.slider("b_" + key, p.label, x, y, w, self.settings[key], p.lo, p.hi, p.step, p.default, p.help, p.kind == "int")
            y += 40
        nvar = len(self.variants) + (self.sweep["steps"] if self.sweep else 0)
        runs = nvar * int(self.settings["seeds"]) * len(core.tiles(self.scenario["area"]))
        nw = batch.auto_workers(self.a.world, int(self.settings["workers"]), runs)
        est = runs * (self.settings["duration"] + self.settings["warm"]) / 3.0 / nw / 60
        self.text(f"{nvar} variants x {int(self.settings['seeds'])} seeds x {len(core.tiles(self.scenario['area']))} tiles = {runs} runs on {nw} processes, ~{est:.0f} min", x, y, 13, MUT)
        y += 24
        bs = self.batch_state
        if bs and bs["thread"].is_alive():
            f = bs["done"] / max(1, bs["total"])
            rl.draw_rectangle(int(x), int(y), int(w), 16, PANEL2)
            rl.draw_rectangle(int(x), int(y), int(w * f), 16, ACC)
            self.text(f"{bs['done']}/{bs['total']}", x + 6, y, 13, FG)
            y += 22
            for ln in font.wrap(bs["text"], 12, w):
                self.text(ln, x, y, 12, MUT)
                y += 16
            if self.button("Cancel", x, y + 4, 100):
                bs["cancel"] = True
            y += 40
        else:
            if self.button("Run batch", x, y, w, 34, col=C(40, 120, 70)):
                self.start_batch()
            y += 42
            if bs and bs.get("error"):
                for ln in font.wrap("Batch failed: " + bs["error"], 12, w):
                    self.text(ln, x, y, 12, BAD)
                    y += 16
        for ln in font.wrap("Every run starts the game's simulation from scratch in its own process with seed = first seed + k (the game also orders some "
                            "cars by memory address, so a repeat differs slightly: that is what the seeds and intervals are for). The study area, closures, obstacles, junction changes and "
                            "scheduled incidents of the current scenario apply to every variant.", 12, w):
            self.text(ln, x, y, 12, MUT)
            y += 16
        return y + 10

    def start_batch(self):
        spec = {"world": self.a.world, "osm": self.a.osm, "scenario": json.loads(json.dumps(self.scenario)),
                "base": {k: v for k, v in self.settings.items()}, "seeds": int(self.settings["seeds"]),
                "seed0": int(self.settings["seed0"]), "workers": int(self.settings["workers"]),
                "variants": self.variants, "sweep": self.sweep}
        bs = {"done": 0, "total": 1, "text": "starting worker processes ...", "cancel": False, "error": None}

        def work():
            try:
                summary, out = batch.run(spec, progress=lambda d, n, t: bs.update(done=d, total=n, text=t), cancel=lambda: bs["cancel"])
                self.report = (summary, out)
                bs["text"] = "done: " + out
                self.tab = "Report"
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                bs["error"] = repr(e)
        bs["thread"] = threading.Thread(target=work, daemon=True)
        self.batch_state = bs
        bs["thread"].start()

    # ---------------------------------------------------------- Explore
    def tab_explore(self, x, y, w):
        y = self.head("Explore rules and constants", x, y, w)
        for ln in font.wrap("Random search, then evolution around the best (mutation, crossover, random newcomers), every candidate on "
                            "the same seeds across all cores. The best are re-tested on fresh seeds against the game's own settings "
                            "before they count: the leaderboard ranks by that validation.", 13, w):
            self.text(ln, x, y, 13, MUT)
            y += 17
        ex = self.ex
        running = ex is not None and getattr(self, "ex_thread", None) is not None and self.ex_thread.is_alive()
        y += 6
        if running:
            if self.button("Stop (then validate the best so far)", x, y, w, 32, col=C(150, 60, 40)):
                self.ex_cancel = True
            y += 40
            self.text(getattr(self, "ex_text", ""), x, y, 13, ACC2)
            y += 22
        else:
            if self.button("Start exploring", x, y, w, 34, col=C(40, 120, 70)):
                self.start_explore()
            y += 44
        if ex is not None:
            y = self.head("Leaderboard" + (" (validated on fresh seeds)" if ex.leader else " (search score)"), x, y, w)
            rows = ex.leader or sorted((c for c in ex.cands if c["score"] is not None), key=lambda c: -c["score"])[:10]
            base = ex.cands[0] if ex.cands else None
            if base is not None and base.get("score") is not None:
                bs = base.get("vscore") if ex.leader else base["score"]
                self.text(f"game settings: {fmt(bs)}", x, y, 13, MUT)
                y += 20
            for i, c in enumerate(rows):
                sc_ = c.get("vscore") if ex.leader else c["score"]
                ci = c.get("vci") if ex.leader else c["ci"]
                col = FG
                if ex.leader and c.get("vp") is not None:
                    col = GOOD if (c["vp"] < 0.05 and (c.get("vdiff") or 0) > 0) else (BAD if c["vp"] < 0.05 else FG)
                self.text(f"#{i + 1}  {fmt(sc_)} ± {fmt(ci)}", x, y, 15, col, bold=True)
                tag = f"c{c['id']} gen {c['gen'] + 1} {c['how']}"
                if ex.leader and c.get("vdiff") is not None:
                    tag += f"  {c['vdiff']:+.1f} vs game (p={c['vp']:.3f})"
                self.text(tag, x + 140, y + 2, 12, MUT)
                y += 20
                diff = [f"{k}={v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k}={v}"
                        for k, v in c["settings"].items() if v != params.BY_KEY[k].default]
                for ln in font.wrap(", ".join(diff) or "(game settings)", 12, w):
                    self.text(ln, x, y, 12, MUT)
                    y += 15
                if self.button("Load into lab", x, y + 2, 120, 22, size=12):
                    self.settings.update(c["settings"])
                    self.retune()
                    self.say(f"c{c['id']} loaded: watch it on the map")
                if self.button("Apply to game ...", x + 128, y + 2, 140, 22, size=12):
                    st = dict(self.settings)
                    st.update(c["settings"])
                    self.confirm = ("apply", params.tuning(st, self.scenario))
                y += 32
            rd = getattr(ex, "report_dir", None)
            if rd and self.button("Open the validation report", x, y, w, 28, col=C(40, 90, 160)):
                webbrowser.open("file://" + os.path.abspath(os.path.join(rd, "report.html")))
            y += 36
        y = self.head("Objective weights", x, y + 4, w)
        o = self.ex_opt
        for key, label in (("w_eff", "Efficiency"), ("w_safe", "Safety"), ("w_speed", "Speed")):
            o[key] = self.slider("ex_" + key, label, x, y, w, o[key], 0.0, 1.0, 0.05, None)
            y += 40
        y = self.head("Search", x, y, w)
        for key, label, lo, hi in (("population", "Candidates per generation", 4, 128), ("generations", "Generations", 1, 50),
                                   ("elite", "Elite kept", 2, 16), ("seeds", "Seeds per candidate", 1, 8),
                                   ("validate_seeds", "Fresh validation seeds", 2, 32), ("finalists", "Finalists validated", 1, 10)):
            o[key] = self.slider("ex_" + key, label, x, y, w, o[key], lo, hi, 1, None, integer=True)
            y += 40
        o["informed"] = self.toggle("Informed start (around the game's values)", x, y, o["informed"], w,
                                    "off: uniform over each slider's whole range (wilder ideas)")
        y += 30
        runs = (o["population"] * o["generations"] * o["seeds"] + (o["finalists"] + 1) * o["validate_seeds"]) * len(core.tiles(self.scenario["area"]))
        nw = batch.auto_workers(self.a.world, int(self.settings["workers"]), o["population"] * o["seeds"])
        est = runs * (self.settings["duration"] + self.settings["warm"]) / 3.0 / nw / 60
        self.text(f"{runs} runs on {nw} processes, ~{est:.0f} min (run length from the Run tab)", x, y, 13, MUT)
        y += 26
        y = self.head(f"What may change ({len(self.ex_keys)} chosen)", x, y, w)
        for tab in ("Drivers", "Junctions", "Signals", "Roads", "Fleet", "Transit", "Emergency", "Advanced"):
            ps = [p for p in params.all_params() if p.tab == tab and p.key not in ("amb_on", "fire_on")]
            if not ps:
                continue
            self.text(tab, x, y + 4, 14, ACC, bold=True)
            if self.button("all", x + w - 110, y, 50, 22, size=12):
                self.ex_keys |= {p.key for p in ps}
            if self.button("none", x + w - 56, y, 56, 22, size=12):
                self.ex_keys -= {p.key for p in ps}
            y += 28
            for p in ps:
                on = self.toggle(p.label, x, y, p.key in self.ex_keys, w, p.help)
                if on != (p.key in self.ex_keys):
                    (self.ex_keys.add if on else self.ex_keys.discard)(p.key)
                y += 26
        return y + 10

    def start_explore(self):
        o = self.ex_opt
        spec = {"world": self.a.world, "osm": self.a.osm, "scenario": json.loads(json.dumps(self.scenario)),
                "base": dict(self.settings), "keys": sorted(self.ex_keys), "weights": [o["w_eff"], o["w_safe"], o["w_speed"]],
                "population": o["population"], "generations": o["generations"], "elite": o["elite"], "seeds": o["seeds"],
                "validate_seeds": o["validate_seeds"], "finalists": o["finalists"], "informed": o["informed"],
                "seed0": int(self.settings["seed0"]), "workers": int(self.settings["workers"])}
        self.ex_cancel = False
        self.ex_text = "starting worker processes ..."

        def prog(_e, t):
            self.ex_text = t
        self.ex = explore.Explorer(spec, progress=prog, cancel=lambda: self.ex_cancel)

        def work():
            try:
                self.ex.run()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self.ex_text = "failed: " + repr(e)
        self.ex_thread = threading.Thread(target=work, daemon=True)
        self.ex_thread.start()

    # ---------------------------------------------------------- Report
    def tab_report(self, x, y, w):
        if self.report is None:
            y = self.head("Batch report", x, y, w)
            self.text("Run a batch (Batch tab) or open an earlier one:", x, y, 14, MUT)
            y += 26
        else:
            summary, out = self.report
            y = self.head(os.path.basename(out), x, y, w)
            if self.button("Open the full HTML report", x, y, w, 30, col=C(40, 90, 160)):
                webbrowser.open("file://" + os.path.abspath(os.path.join(out, "report.html")))
            y += 38
            vs = summary["variants"]
            colw = (w - 150) / max(1, len(vs))
            for i, v in enumerate(vs):
                rl.draw_rectangle(int(x + 150 + i * colw), int(y + 3), 10, 12, SERIES[i % len(SERIES)])
                self.text(font.fit(v["name"], 12, colw - 14), x + 164 + i * colw, y, 12, FG)
            y += 20
            group = None
            for key, label, unit, better, g in batch.HEADLINE:
                if g != group:
                    group = g
                    self.text(g, x, y + 4, 14, ACC, bold=True)
                    y += 24
                self.text(font.fit(label, 12, 146), x, y, 12, MUT)
                for i, v in enumerate(vs):
                    s = v["metrics"][key]
                    col = FG if s.get("better") is None else (GOOD if s["better"] else BAD)
                    self.text(f"{fmt(s['mean'], 2 if (s['mean'] or 0) < 1 else 1)}±{fmt(s['ci'], 1)}", x + 150 + i * colw, y, 12, col)
                y += 17
            y += 10
            for ln in font.wrap("± is the 95 % confidence interval over seeds. Green / red: significantly better / worse than the "
                                "first variant (Welch t-test, p < 0.05).", 12, w):
                self.text(ln, x, y, 12, MUT)
                y += 16
            y += 8
        y = self.head("Earlier batches", x, y, w)
        for d in sorted(glob.glob(os.path.join(OUT, "batches", "*", "summary.json")), reverse=True)[:12]:
            folder = os.path.dirname(d)
            if self.button(os.path.basename(folder), x, y, w, 24, size=13):
                with open(d, encoding="utf-8") as f:
                    self.report = (json.load(f), folder)
            y += 28
        return y + 10

    # ---------------------------------------------------------- Scenario
    def tab_scenario(self, x, y, w):
        sc = self.scenario
        y = self.head("Scenario", x, y, w)
        self.text("name", x, y + 6, 14, MUT)
        fx = x + 60
        rl.draw_rectangle_rounded(rl.Rectangle(fx, y, w - 60, 28), 0.2, 6, PANEL2 if self.focus_field is None else LINE)
        shown = self.name_field if self.focus_field is not None else sc.get("name", "")
        self.text(shown + ("|" if self.focus_field is not None and int(time.time() * 2) % 2 else ""), fx + 8, y + 6, 15, FG)
        if self.clicked(fx, y, w - 60, 28):
            self.focus_field = "name"
            self.name_field = sc.get("name", "")
        if self.focus_field is None and self.name_field and self.name_field != sc.get("name"):
            sc["name"] = self.name_field
        y += 38
        if self.button("Save scenario", x, y, w / 2 - 4):
            os.makedirs(os.path.join(OUT, "scenarios"), exist_ok=True)
            safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in sc.get("name", "scenario")).strip() or "scenario"
            sc["settings"] = {k: v for k, v in self.settings.items() if k in params.BY_KEY and v != params.BY_KEY[k].default}
            sc["variants"], sc["sweep"] = self.variants, self.sweep
            p = os.path.join(OUT, "scenarios", safe + ".json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(sc, f, ensure_ascii=False, indent=1)
            self.say("saved " + p)
        if self.button("New (game defaults)", x + w / 2, y, w / 2):
            self.scenario = core.default_scenario(self.world)
            self.settings = params.defaults()
            self.restart()
        y += 40
        y = self.head("Open", x, y, w)
        files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "presets", "*.json"))) + \
            sorted(glob.glob(os.path.join(OUT, "scenarios", "*.json")))
        for p in files:
            tag = "preset" if "presets" in p else "saved"
            if self.button(f"{os.path.basename(p)[:-5]}  ({tag})", x, y, w, 24, size=13):
                self._load_scenario(p)
                self.restart()
                self.fit_area()
            y += 28
        y = self.head("Apply to the real game", x, y + 8, w)
        cur = traffic_tuning.load()
        t = params.tuning(self.settings, self.scenario)
        n = len(t["constants"]) + len(t["mix"]) + len(t["edge_speed"])
        for ln in font.wrap(f"Writes traffic_tuning.json in the game folder: {n} changed settings, {len(t['closures'])} closed roads, "
                            f"{len(t['junctions'])} junction signal changes{', lights off' if not t['signals_on'] else ''}. "
                            "The game and its traffic worker load it at start (src/traffic_tuning.py), the same code this lab runs. "
                            "Run-only options (cars, duration, incidents, study area) are not written; obstacles are lab-only.", 13, w):
            self.text(ln, x, y, 13, MUT)
            y += 17
        y += 6
        if self.button("Apply to game ...", x, y, w / 2 - 4, 30, col=C(40, 120, 70)):
            self.confirm = ("apply", t)
        if self.button("Remove game tuning", x + w / 2, y, w / 2, 30, col=C(120, 50, 40), enabled=cur is not None):
            self.confirm = ("remove", None)
        y += 40
        self.text("game now: " + ("tuned (" + str(len((cur or {}).get("constants", {}))) + " constants, "
                                  + str(len((cur or {}).get("closures", []))) + " closures)" if cur else "game defaults"), x, y, 13, FG)
        y += 24
        if cur and self.button("Load the game's current tuning into the lab", x, y, w, 26, size=13):
            self._from_tuning(cur)
            self.retune()
        return y + 40

    def _from_tuning(self, t):
        for p in params.all_params():
            if p.target in (t.get("constants") or {}):
                how = t["constants"][p.target]
                self.settings[p.key] = how.get("scale", how.get("set"))
            if p.how == "mix" and p.key[4:] in (t.get("mix") or {}):
                self.settings[p.key] = t["mix"][p.key[4:]]
            if p.how == "edge" and p.key[4:] in (t.get("edge_speed") or {}):
                self.settings[p.key] = t["edge_speed"][p.key[4:]]
        self.settings["signals_on"] = t.get("signals_on", True)
        self.settings["preempt"] = t.get("preempt", True)
        self.scenario["closures"] = [list(c) for c in t.get("closures", ())]
        self.scenario["junctions"] = [dict(j) for j in t.get("junctions", ())]

    def _load_scenario(self, path):
        with open(path, encoding="utf-8") as f:
            sc = json.load(f)
        base = core.default_scenario(self.world)
        base.update(sc)
        if not sc.get("area"):
            base["area"] = core.default_scenario(self.world)["area"]
        self.scenario = base
        self.settings = params.defaults()
        self.settings.update(sc.get("settings") or {})
        if sc.get("variants"):
            self.variants = sc["variants"]
        self.sweep = sc.get("sweep")
        self.say("opened " + os.path.basename(path))

    def draw_confirm(self):
        kind, t = self.confirm
        w, h = 560, 230
        x, y = (self.W - w) / 2, (self.H - h) / 2
        rl.draw_rectangle(0, 0, self.W, self.H, C(0, 0, 0, 140))
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.06, 8, PANEL)
        title = "Apply this tuning to the real game?" if kind == "apply" else "Remove the game tuning?"
        self.text(title, x + 20, y + 18, 19, FG, bold=True)
        body = (f"Writes {traffic_tuning.PATH}. The game uses it the next time it starts. Delete it (or press Remove) to go back "
                "to the game's own values." if kind == "apply" else f"Deletes {traffic_tuning.PATH}; the game starts with its own values again.")
        yy = y + 54
        for ln in font.wrap(body, 14, w - 40):
            self.text(ln, x + 20, yy, 14, MUT)
            yy += 19
        if self.button("Yes", x + w - 220, y + h - 50, 90, 32, col=C(40, 120, 70)):
            if kind == "apply":
                traffic_tuning.save(t)
                self.say("traffic_tuning.json written: the game will use it on its next start", 5)
            elif os.path.exists(traffic_tuning.PATH):
                os.remove(traffic_tuning.PATH)
                self.say("game tuning removed", 4)
            self.confirm = None
        if self.button("Cancel", x + w - 120, y + h - 50, 100, 32):
            self.confirm = None
        self.mouse_used = True

    def draw_help(self):
        w, h = 760, 520
        x, y = (self.W - w) / 2, (self.H - h) / 2
        rl.draw_rectangle(0, 0, self.W, self.H, C(0, 0, 0, 140))
        rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.04, 8, PANEL)
        self.text("Traffic Lab: help", x + 20, y + 16, 20, FG, bold=True)
        lines = [
            "Mouse wheel: zoom at the cursor.   Right / middle drag or arrow keys: pan.   Left click: the active tool (Edit tab).",
            "Space: play / pause.   . : one step.   1-6: speed x1 x2 x4 x8 x16 max.   R: restart.   N: new seed.",
            "F: follow the selected vehicle.   Home: fit the study area.   F11: full screen / window.   Esc: close this.",
            "",
            "The simulation is the game's own code (AI traffic, buses, ambulances and fire engines, trains, pedestrians, signals)",
            "on the game's built world. Sliders change the game's own constants live; orange = differs from the game.",
            "Right-click a slider to reset it. Some switches (buses, trains, parked cars, time step) apply after Restart.",
            "",
            "Edit: close roads, place obstacles, call ambulances, start car fires, break cars down, set the study area,",
            "schedule incidents for every run. Inspect: click a junction for its stats and its own signal plan.",
            "Batch: variants x seeds, sweeps, presets; the Report tab compares them with 95 % confidence intervals.",
            "Scenario: save / open, and Apply to game writes traffic_tuning.json for the real game.",
            "",
            "Collisions use the game's collision boxes and box test. Near miss = time to collision < 1.5 s.",
            "Level of service: HCM control delay thresholds. The study area is at most 800 x 800 m because the game",
            "simulates a ~420 m bubble around the (hidden) player.",
        ]
        for i, ln in enumerate(lines):
            self.text(ln, x + 20, y + 56 + i * 24, 15, FG if ln else MUT)
        if self.button("Close", x + w - 110, y + h - 46, 90, 30):
            self.help = False
        self.mouse_used = True

    # ------------------------------------------------------------------ loop
    def loop(self, shot=None, frames=0):
        self.quit = False
        k = 0
        while not rl.window_should_close() and not self.quit:
            self.frame()
            k += 1
            if shot and k >= frames:
                rl.take_screenshot(os.path.basename(shot))
                if os.path.abspath(os.path.basename(shot)) != os.path.abspath(shot):
                    os.replace(os.path.basename(shot), shot)
                break
        if self.lab is not None:
            self.lab.close()


def run(a):
    rl.set_trace_log_level(rl.LOG_WARNING)
    flags = rl.FLAG_MSAA_4X_HINT | rl.FLAG_WINDOW_RESIZABLE | rl.FLAG_VSYNC_HINT
    if a.windowed or a.shot:
        W, H = (int(v) for v in a.size.lower().split("x"))
        rl.set_config_flags(flags)
        rl.init_window(W, H, "Skopje 242 - Traffic Lab")
    else:
        rl.set_config_flags(flags | rl.FLAG_WINDOW_UNDECORATED)
        rl.init_window(0, 0, "Skopje 242 - Traffic Lab")
        mon = rl.get_current_monitor()
        rl.set_window_size(rl.get_monitor_width(mon), rl.get_monitor_height(mon))
        rl.set_window_position(0, 0)
    icon = os.path.join(ROOT, "assets", "icon.png")
    if os.path.exists(icon):
        img = rl.load_image(icon)
        rl.set_window_icon(img)
    rl.set_exit_key(0)
    rl.set_target_fps(60)
    font.load()
    ui = UI(a)
    ui.load()
    if a.report:
        with open(os.path.join(a.report, "summary.json"), encoding="utf-8") as f:
            ui.report = (json.load(f), a.report)
    if a.shot:
        ui.speed = 0
    ui.loop(a.shot, a.frames)
    rl.close_window()
    return 0
