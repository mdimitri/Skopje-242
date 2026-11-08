"""Loading screen (v3): the splash art full screen; bottom right a live map of the city that fills with a pixel for
everything downloaded, generated or loaded (and where it sits); bottom left the verbose progress log in Macedonian, transfer
speed and warnings; along the very bottom the overall bar (full width) and just above it the bar of the step running now,
each with its text inside."""
import collections
import json
import os
import random
import re
import time

import numpy as np
import pyray as rl
import font   # noqa: E402

import geo
import poster as poster_mod
import slang
import strings as T

WHITE = rl.Color(235, 235, 235, 255)
GREY = rl.Color(150, 154, 165, 255)
DIM = rl.Color(100, 104, 114, 255)
ORANGE = rl.Color(255, 170, 60, 255)
RED = rl.Color(235, 85, 75, 255)
GREEN = rl.Color(95, 200, 125, 255)
BLUE = rl.Color(120, 190, 250, 255)
C_FAIL = rl.Color(220, 70, 60, 255)
C_SPLIT = rl.Color(185, 120, 235, 255)
PINK = rl.Color(226, 32, 104, 255)                # the title menu's highlight colour
CUR_BAR = rl.Color(150, 40, 110, 255)

# rough seconds of a full-city build per phase; used only until the first real build has recorded its own timings
BUILD_DEFAULT = {
    "read OSM files": 20, "buildings -> 3D meshes": 60, "areas / water / rails": 15, "roads": 25,
    "building meshes on terrain": 90, "graph": 10, "bridge decks": 5, "places": 2, "street furniture": 20,
    "procedural trees in parks/woods": 15, "street trees, lamps, parked cars": 25, "3D roads": 40, "ground rasters": 10,
    "tree meshes": 10, "lamp meshes": 5, "chunk index: areas": 10, "spawn point": 1, "write world": 2,
    "write mesh blob": 10, "write world parts": 10,
    "furniture": 30, "leisure": 5, "construction sites": 20, "fill: gardens, scrub, boulders": 260,
    "carriageway cleanup": 10, "railway": 3,
}
MK_LOG = "Тек на работата"
MK_LEG = {"roads": "Патишта", "buildings": "Згради", "areas": "Зеленило", "water": "Води", "pois": "Знаменитости", "places": "Населби",
          "trees": "Дрвја", "parked": "Паркирани коли", "chunk": "Делови на градот", "props": "Опрема"}
MK_PART = {"meta": "основни податоци", "areas": "површини и води", "roads": "патишта", "edges": "сообраќајни врски",
           "buildings": "згради", "props": "дрвја, лампи и коли", "chunks": "делови на градот", "surf": "површини на земјата",
           "terrain": "рељеф"}
MK_NOTE = {"textures": "Текстури", "overview mesh": "Мрежа за прегледната мапа", "car & pedestrian models": "Модели на возила и пешаци",
           "your character": "Те облекувам тебе, јунаку", "pickups & weapons": "Предмети и оружје", "simulation": "Го палам градот",
           "pavement grid": "Мрежа на тротоарите", "traffic lights": "Ги палам семафорите", "sound": "Го вклучувам озвучувањето", "collision ready": "Судирите се подготвени",
           "routing graph": "Сообраќајна мрежа", "cached": "од кешот", "land use & parks": "Паркови и површини", "rivers": "Реки",
           "roads": "Патишта", "bridges": "Мостови", "buildings": "Згради", "trees": "Дрвја", "saving the map": "Ја сеирам и зачувувам мапата"}
MK_RE = [(re.compile(r"^(\w+): reading (\d+)/(\d+) MB$"), lambda m: f"Читам {MK_PART.get(m[1], m[1])}: {m[2]}/{m[3]} {T.MB}"),
         (re.compile(r"^(\w+): unpacking$"), lambda m: f"Распакувам {MK_PART.get(m[1], m[1])}"),
         (re.compile(r"^(\w+): ok$"), lambda m: ""),
         (re.compile(r"^building collision (\d+)/(\d+)$"), lambda m: f"Судири со згради {m[1]}/{m[2]}"),
         (re.compile(r"^car models (\d+)/(\d+)$"), lambda m: f"Модели на возила {m[1]}/{m[2]}"),
         (re.compile(r"^pedestrian models (\d+)/(\d+)$"), lambda m: f"Модели на пешаци {m[1]}/{m[2]}"),
         (re.compile(r"^chunk (\d+)/(\d+)\s+\((-?\d+),(-?\d+)\)$"), lambda m: f"Дел од градот {m[1]}/{m[2]} ({m[3]}, {m[4]})")]
# what the running build step is making now (progress.span / Bar notes of the build tools)
MK_SUB = {"roads joined": "спојувам улици", "junctions": "крстосници", "edges": "сообраќајни врски", "rounded corners": "заоблени агли",
          "ways under bridges": "патишта под мостовите", "decks": "палуби на мостовите", "neighbourhoods": "населби",
          "trees and lamps from the map": "дрвја и светилки од мапата", "lane grid": "мрежа на лентите", "lamps": "светилки",
          "trees": "дрвја", "posts": "столбчиња", "pavements": "тротоари", "asphalt": "асфалт", "collision posts": "судири со столбчиња",
          "areas": "површини", "rivers and rails": "реки и пруги", "road grid": "мрежа на улиците",
          "traffic lights plan": "план на семафорите", "traffic lights, signs, crossings": "семафори, знаци, пешачки премини",
          "benches, bins, signs along streets": "клупи, корпи и знаци по улиците", "bridge parapets": "огради на мостовите",
          "junk and garbage": "отпадоци и ѓубре", "kept off the roadway": "тргам опрема од коловозот", "bus stops": "автобуски постојки",
          "empty lots": "празни плацеви", "building sites": "градилишта", "playgrounds, pitches, bushes": "игралишта, терени, грмушки",
          "school yards": "школски дворови", "hedges along streets": "живи огради", "cover grid": "мрежа на покриеност",
          "joints": "споеви", "junction plates": "плочи на крстосниците", "streets": "улици", "corners": "агли",
          "crossings": "пешачки премини", "mesh": "мрежа", "parks and squares": "паркови и плоштади", "trees on the lots": "дрвја на плацевите",
          "replacing the old world": "го заменувам стариот свет", "meta": "основни податоци", "props": "дрвја, лампи и коли",
          "buildings": "згради", "chunks": "делови на градот", "surf": "површини на земјата", "terrain": "рељеф", "roads": "патишта"}
# map pixel colours per kind of thing
MAP_COL = {"roads": (225, 225, 230), "buildings": (240, 200, 60), "areas": (70, 160, 90), "water": (86, 146, 198), "pois": (235, 90, 80),
           "places": (255, 255, 255), "trees": (45, 110, 60), "parked": (255, 140, 50), "chunk": (120, 220, 255),
           "bmesh": (255, 240, 170), "graph": (120, 190, 250), "bridge": (200, 160, 255), "road3d": (255, 255, 255), "props": (190, 120, 255)}
# last line of defence: the loading screen never shows Latin letters; anything not translated above is written in Cyrillic
_LAT = {"sh": "ш", "zh": "ж", "ch": "ч", "dj": "ѓ", "gj": "ѓ", "kj": "ќ", "dz": "ѕ", "lj": "љ", "nj": "њ", "dh": "д", "th": "т", "ph": "ф",
        "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х", "i": "и", "j": "ј", "k": "к", "l": "л", "m": "м",
        "n": "н", "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс", "y": "и", "z": "з"}
_LAT_RE = re.compile(r"sh|zh|ch|dj|gj|kj|dz|lj|nj|dh|th|ph|[a-z]", re.I)


def mk(text):
    """Same text with every Latin letter turned into its Macedonian Cyrillic counterpart (no-op for Cyrillic text)."""
    def one(m):
        c = _LAT[m[0].lower()]
        return c.upper() if m[0][0].isupper() else c
    if not text or not re.search(r"[A-Za-z]", str(text)):
        return text
    text = str(text).replace("OpenStreetMap", "ОпенСтритМап").replace("OSM", "ОСМ").replace("3D", "3Д")
    return _LAT_RE.sub(one, text)


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMES = os.path.join(ROOT, "data", "cache", "build_times.json")


def _fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


def _size(n):
    return f"{n / 1e6:.1f} {T.MB}" if n >= 1e6 else f"{n / 1e3:.0f} {T.KB}"


def _col(c, a):
    return rl.Color(c.r, c.g, c.b, a)


class Loader:
    """stages = [(key, weight), ...] with keys of strings.STAGE.  The overall bar is the weighted sum of the stage
    fractions and never moves backwards; every fraction comes from real counts (cells downloaded, build phases
    measured on earlier runs, chunks baked), never from a timer."""

    def __init__(self, stages):
        self.keys = [k for k, _ in stages]
        self.w = dict(stages)
        self.f = {k: 0.0 for k in self.keys}
        self.cur = None
        self.note = ""
        self.t0 = time.time()
        self.stage_t0 = {}
        self.shown = 0.0
        self.last_draw = 0.0
        self.log = []
        self.radio_line = ""                # progress of the background radio download
        self.warn = ""                      # a fixed information line set by the caller
        self.cells = {}
        self.box = [-geo.HX, -geo.HY, geo.HX, geo.HY]
        self.bytes_by_id = {}
        self.bps = 0.0
        self.mirror = ""
        self.last_net = 0.0
        self.waiting = None                 # (why, seconds left, time of the event)
        self.alert = None                   # (text, colour, until)
        self.active_id = ""
        self.net_state = ""
        self.wait_sec = 0
        self.build_times = dict(BUILD_DEFAULT)
        try:
            self.build_times.update({k: float(v) for k, v in json.load(open(TIMES)).items() if v > 0})
        except Exception:  # noqa: BLE001
            pass
        self.measured = {}
        self.mq = collections.deque()       # map work: (layer, "pts" | "lines", array / polylines), painted a time slice per frame
        self.cv = None                      # RGBA canvas of the whole box; one pixel per thing that arrived
        self.cv_tex = None
        self.cv_dirty = False
        self.fresh = []                     # (rows, cols, colour) painted white by the last slices; they settle to their layer colour
        self.fresh_t = 0.0
        self.last_note = ("", 0.0)
        self.rng = np.random.default_rng(242)
        self.rate_hist = collections.deque()
        self.b_label = None
        self.b_t0 = 0.0
        self.b_done = set()
        self.b_frac = 0.0
        self.music = None                   # loadmusic.LoadMusic, set by main; kept going on every frame
        self.quip = random.choice(slang.LOADING_QUIPS)
        self.quip_t = time.time()

    # ---------------------------------------------------------------- stage control
    def say(self, text):
        self.log.append(f"[{_fmt(time.time() - self.t0)}] {mk(text)}")
        del self.log[:-200]

    def begin(self, key, note=""):
        if self.cur and self.cur != key:
            self.f[self.cur] = 1.0
        self.cur = key
        self.note = note
        if key not in self.stage_t0:
            self.say(f"▶ {T.STAGE.get(key, key)}")
        self.stage_t0.setdefault(key, time.time())
        self.draw(force=True)

    def ensure_stage(self, key, weight):
        """A stage nobody planned for (the world turned out to need a rebuild, or the demo fallback)."""
        if key not in self.f:
            self.keys.insert(max(0, self.keys.index("world")) if "world" in self.keys else len(self.keys), key)
            self.w[key] = weight
            self.f[key] = 0.0

    def skip(self, key):
        if key in self.f:
            self.f[key] = 1.0

    def finish(self):
        for k in self.keys:
            self.f[k] = 1.0
        self.say("✓ " + T.TITLE)
        self.draw(force=True)

    def tick(self, frac, note=None):
        if self.cur:
            self.f[self.cur] = max(self.f[self.cur], max(0.0, min(1.0, frac)))
        if note is not None:
            self.note = self._tr(note)
            if self.note and self.note != self.last_note[0] and time.time() - self.last_note[1] > 0.3:
                self.last_note = (self.note, time.time())
                self.say("· " + self.note)
        self.draw()

    @staticmethod
    def _tr(note):
        """Notes of world.py / bake.py / main.py are English; the player reads Macedonian."""
        if note in MK_NOTE:
            return MK_NOTE[note]
        for rx_, fn in MK_RE:
            m = rx_.match(note)
            if m:
                return fn(m)
        return mk(note)

    def overall(self):
        tot = sum(self.w.values()) or 1.0
        v = sum(self.w[k] * self.f[k] for k in self.keys) / tot
        self.shown = max(self.shown, min(1.0, v))                 # never backwards
        return self.shown

    # ---------------------------------------------------------------- events from the download / build tools
    def event(self, key, ev):
        t = ev.get("t")
        now = time.time()
        if t == "plan":
            for c in ev.get("cells", []):
                self.cells[c["id"]] = {"layer": c["layer"], "r": c["r"], "st": "pending", "kids": 0, "key": key}
            if ev.get("box"):
                self.box = ev["box"]
        elif t == "cell":
            cid, st = ev.get("id", ""), ev.get("state", "")
            c = self.cells.get(cid)
            if c is None:
                par = cid.rsplit(".", 1)[0]
                if par in self.cells and st == "done":
                    self.cells[par]["kids"] += 1
                return
            prev = c["st"]
            c["st"] = "cached" if st == "done" and ev.get("cached") else st
            c["t"] = now
            if "n" in ev:
                c["n"] = ev["n"]
            nm = f"{T.LAYER.get(c['layer'], c['layer'])} {cid.split(':', 1)[-1]}"
            where = self._where(c["r"])
            if st == "active":
                self.active_id = cid
                if prev != "active":
                    self.say(f"↓ {nm} {where}")
            elif st == "done":
                self.say(f"✓ {nm} {where}: {ev.get('n', 0)} {T.OBJECTS}" + (f" ({T.LEG_CACHED.lower()})" if ev.get("cached") else ""))
            elif st == "fail":
                self.say(f"✗ {nm} {where}: {T.WARN.get(ev.get('kind', 'net'), T.WARN['net'])}")
            elif st == "split":
                self.say(f"+ {nm} {where}: {T.LEG_SPLIT.lower()}")
        elif t == "net":
            cid = ev.get("id", "")
            self.last_net = now
            self.mirror = "•" if ev.get("mirror") or self.mirror else ""
            st = ev.get("state", "")
            self.net_state = st
            if st == "rest":
                self.waiting = (ev.get("why", ""), ev.get("left", 0), now)
            else:
                self.waiting = None
                self.bytes_by_id[cid] = max(self.bytes_by_id.get(cid, 0), ev.get("bytes", 0))
                self.bps = float(ev.get("bps", 0))
                self.wait_sec = ev.get("sec", 0)
        elif t == "warn":
            kind = ev.get("kind", "net")
            txt = T.WARN.get(kind, T.WARN["net"])
            if ev.get("attempt"):
                txt += f"  ({T.ATTEMPT} {ev['attempt']})"
            col = RED if kind in ("offline", "exhausted") else ORANGE
            self.alert = (txt, col, now + 14)
            self.say(txt)
        elif t == "note":
            txt = T.NOTE.get(ev.get("kind", ""), "")
            if ev.get("left"):
                txt += f" {ev['left']}"
            if txt:
                self.alert = (txt, ORANGE, now + 20)
                self.say(txt)
        elif t == "cut":                                     # Geofabrik route: cutting the city out of the country file
            self.cut = ev
            self.last_net = 0
            self.f[key] = max(self.f[key], min(0.97, float(ev.get("frac", 0))))
            if now - getattr(self, "cut_said", 0) > 3:
                self.cut_said = now
                self.say(f"» {T.CUTTING}: {ev.get('nodes', 0):,} {T.C_NODES}, {ev.get('ways', 0):,} {T.C_WAYS}, "
                         f"{ev.get('found', 0):,} {T.C_FOUND}".replace(",", " "))
        elif t == "geo":
            layer, lines = ev.get("layer", ""), ev.get("lines", [])
            pls = [np.asarray(fl, np.float64).reshape(-1, 2) for fl in lines if len(fl) >= 2]
            if layer in ("buildings", "bmesh", "pois", "places", "trees", "parked", "props", "chunk"):
                self.plot(layer, [p[0] for p in pls])
            else:
                self.plot_lines(layer, pls)
            return
        elif t == "prog":
            self._build_event(ev, now)
        elif t == "done":
            self.f[key] = 1.0
        self._recount(key)
        self.draw()

    def _where(self, r):
        """Tile position in plain words: km east/west and north/south of the centre (Плоштад)."""
        cx, cy = (r[0] + r[2]) / 2000.0, (r[1] + r[3]) / 2000.0
        ew = f"{abs(cx):.0f} {T.KM} {T.EAST if cx >= 0 else T.WEST}" if abs(cx) >= 0.5 else T.CENTRE
        ns = f"{abs(cy):.0f} {T.KM} {T.SOUTH if cy >= 0 else T.NORTH}" if abs(cy) >= 0.5 else ""
        return f"[{ew}{', ' + ns if ns else ''}]"

    def _recount(self, key):
        mine = [c for c in self.cells.values() if c["key"] == key]
        if mine:
            s = 0.0
            for c in mine:
                if c["st"] in ("done", "cached", "fail"):
                    s += 1.0
                elif c["st"] == "split":
                    s += min(0.95, c["kids"] / 4.0)
            self.f[key] = max(self.f[key], s / len(mine))

    def _build_event(self, ev, now):
        lab = ev.get("label", "")
        if lab != self.b_label:
            if self.b_label:
                self.b_done.add(self.b_label)
                self.measured[self.b_label] = now - self.b_t0
            self.b_label, self.b_t0 = lab, now
            self.say(f"▶ {T.BUILD.get(lab, lab)}")
            self.build_times.setdefault(lab, 3.0)
        total, n = ev.get("total", 0), ev.get("n", 0)
        part = (n / total) if total else 0.0
        if ev.get("done"):
            part = 1.0
        bt = self.build_times
        den = sum(bt.values()) or 1.0
        num = sum(bt[k] for k in self.b_done if k in bt) + bt.get(lab, 3.0) * min(1.0, part)
        self.b_frac = max(self.b_frac, min(0.99, num / den))
        self.f["build"] = max(self.f["build"], self.b_frac)
        sub = ev.get("sub", "")
        sub = mk(MK_SUB.get(sub, sub))
        cnt = (f"{n * 100 // total}%" if total == 1000 else f"{n}/{total}  ({n * 100 // total}%)") if total else ""
        self.note = mk(T.BUILD.get(lab, lab)) + (f"  ·  {sub}" if sub else "") + (f"   {cnt}" if cnt else "")

    def build_finished(self, record=True):
        """Tool exited fine: remember how long each phase really took (next run's weights; not for the small demo city)."""
        now = time.time()
        if self.b_label:
            self.measured[self.b_label] = now - self.b_t0
        if self.measured and record:
            try:
                old = {}
                try:
                    old = json.load(open(TIMES))
                except Exception:  # noqa: BLE001
                    pass
                old.update({k: round(v, 2) for k, v in self.measured.items()})
                os.makedirs(os.path.dirname(TIMES), exist_ok=True)
                json.dump(old, open(TIMES, "w"))
            except OSError:
                pass
        self.f["build"] = 1.0

    # ---------------------------------------------------------------- drawing
    def draw(self, force=False):
        now = time.time()
        if self.music is not None:
            self.music.update()
        if not force and now - self.last_draw < 0.04:
            return
        self.last_draw = now
        if rl.window_should_close():
            raise SystemExit(0)
        if now - self.quip_t > 9.0:
            self.quip_t = now
            self.quip = random.choice(slang.LOADING_QUIPS)
        W, H = rl.get_screen_width(), rl.get_screen_height()
        m = max(12, W // 80)
        th = max(22, H // 34)                                         # overall bar: the very bottom, full width
        ch = max(18, th - 4)                                          # the running step, slightly above it
        ty, cy = H - th, H - th - 6 - ch
        asp = (self.box[3] - self.box[1]) / (self.box[2] - self.box[0])
        self.map_w = max(120, min(int(W * 0.30), int(H * 0.42 / asp)))
        self.GEO_W = 2 * self.map_w                                   # painted at twice the size, shown at half with bilinear filtering
        self._paint()
        rl.begin_drawing()
        poster_mod.draw_splash(W, H)
        panel_h = int(self.map_w * asp) + 50
        top = cy - m - panel_h
        rl.draw_rectangle_gradient_v(0, top - 60, W, H - top + 60, rl.Color(8, 6, 14, 0), rl.Color(8, 6, 14, 225))
        # ---- bottom right: the live map
        mx = W - m - self.map_w
        rl.draw_rectangle(mx - 8, top - 8, self.map_w + 16, panel_h + 8, rl.Color(10, 8, 16, 170))
        self._map(mx, top, self.map_w, 0)
        # ---- bottom left: what is happening, in detail
        lw = mx - 3 * m
        y = top
        for ln in font.wrap(self.quip, 18, lw)[:1]:
            font.draw_text(ln, m, y, 18, rl.Color(255, 205, 225, 255), bold="cond")
            y += 26
        y = self._net_lines(m, y, lw, now)
        lines = max(0, (cy - m - y) // 17)
        if lines > 0 and self.log:
            for ln in self.log[-lines:]:
                c = GREEN if "✓" in ln else (RED if "✗" in ln else (rl.Color(255, 220, 90, 255) if "↓" in ln or "▶" in ln else rl.Color(205, 205, 212, 255)))
                font.draw_text(font.fit(ln, 13, lw), m, y, 13, c)
                y += 17
        # ---- the two bars
        if self.cur:
            fr = self.f[self.cur]
            what = mk(T.STAGE.get(self.cur, self.cur)) + (f"  ·  {mk(self.note)}" if self.note else "")
            self._tbar(m, cy, W - 2 * m, ch, fr, CUR_BAR, what, f"{fr * 100:3.0f}%")
        ov = self.overall()
        el = now - self.t0
        eta = (el / ov - el) if ov > 0.05 else 0
        right = f"{T.L_ELAPSED} {_fmt(el)}" + (f"   {T.L_LEFT} {_fmt(eta)}" if eta else "")
        self._tbar(0, ty, W, th, ov, PINK, f"{T.L_TOTAL.upper()}  {ov * 100:3.0f}%", right)
        if self.music is not None:
            self.music.widget()
        font.exit_button()
        rl.end_drawing()

    @staticmethod
    def _tbar(x, y, w, h, f, col, left, right):
        """A progress bar with its text inside (left: what, right: numbers)."""
        rl.draw_rectangle(x, y, w, h, rl.Color(20, 16, 26, 230))
        rl.draw_rectangle(x, y, int(w * max(0.0, min(1.0, f))), h, col)
        sz = h - 6
        rt = font.measure_text(right, sz, "cond")
        font.draw_text(font.fit(left, sz, w - rt - 40, "cond"), x + 12, y + 2, sz, rl.WHITE, bold="cond")
        font.draw_text(right, x + w - rt - 12, y + 2, sz, rl.WHITE, bold="cond")

    def _map(self, x, y, w, h_avail):
        bx = self.box
        aspect = (bx[3] - bx[1]) / (bx[2] - bx[0])
        mw = self.map_w
        mh = int(mw * aspect)
        sx, sy = mw / (bx[2] - bx[0]), mh / (bx[3] - bx[1])
        rl.draw_rectangle(x, y, mw, mh, rl.Color(26, 29, 36, 255))
        if self.cv_tex is not None:                                     # everything that has arrived so far, one pixel each
            rl.draw_texture_pro(self.cv_tex, rl.Rectangle(0, 0, self.cv_tex.width, self.cv_tex.height), rl.Rectangle(x, y, mw, mh),
                                rl.Vector2(0, 0), 0.0, rl.WHITE)
        pulse = 0.5 + 0.5 * ((time.time() * 2.2) % 1.0)
        for c in self.cells.values():                                   # download tiles: only the ones in flight or in trouble are framed
            if c["st"] in ("done", "cached"):
                continue
            x0, y0, x1, y1 = c["r"]
            x0, y0, x1, y1 = max(x0, bx[0]), max(y0, bx[1]), min(x1, bx[2]), min(y1, bx[3])   # elevation tiles overhang the box: clip to it
            if x1 <= x0 or y1 <= y0:
                continue
            col = {"active": rl.Color(255, int(170 + 60 * pulse), 60, 255), "fail": C_FAIL, "split": C_SPLIT}.get(c["st"], rl.Color(60, 64, 76, 255))
            rl.draw_rectangle_lines_ex(rl.Rectangle(x + (x0 - bx[0]) * sx + 1, y + (y0 - bx[1]) * sy + 1,
                                                    (x1 - x0) * sx - 2, (y1 - y0) * sy - 2), 1 if c["st"] == "pending" else 2, col)
        rl.draw_rectangle_lines(x, y, mw, mh, rl.Color(90, 92, 98, 255))
        taken = []
        for name, lat, lon, _n in slang.LANDMARKS:                      # orientation: well-known places
            lx, ly = geo.project(lat, lon)
            if bx[0] <= lx <= bx[2] and bx[1] <= ly <= bx[3]:
                px, py = int(x + (lx - bx[0]) * sx), int(y + (ly - bx[1]) * sy)
                rl.draw_circle(px, py, 2, WHITE)
                if mw > 300 and all(abs(px - qx) > 70 or abs(py - qy) > 12 for qx, qy in taken):
                    taken.append((px, py))
                    font.draw_text(name, px + 5, py - 6, 11, rl.Color(255, 255, 255, 215))
        ly = y + mh + 4                                                 # legend: what each colour is
        lx = x
        for k in ("roads", "buildings", "areas", "water", "trees", "parked", "props", "pois"):
            c = MAP_COL[k]
            wd = font.measure_text(MK_LEG[k], 12) + 24
            if lx + wd > x + w:
                lx, ly = x, ly + 16
            rl.draw_rectangle(lx, ly + 3, 9, 9, rl.Color(c[0], c[1], c[2], 255))
            font.draw_text(MK_LEG[k], lx + 13, ly, 12, GREY)
            lx += wd
        return ly + 22

    # ---------------------------------------------------------------- the live map: one pixel per thing that arrived
    GEO_W = 1000
    map_w = 500

    def set_box(self, hx, hy):
        """The map covers the world box; called once the real extent is known (a different box starts the picture afresh)."""
        nb = [-hx, -hy, hx, hy]
        if nb != self.box:
            self.box = nb
            self.cv = None

    def plot(self, layer, pts):
        """Things placed at points (x, y in world metres): buildings, trees, parked cars, places."""
        if len(pts):
            self.mq.append((layer, "pts", np.asarray(pts, np.float64).reshape(-1, 2)))

    def plot_lines(self, layer, polylines):
        """Roads, rivers, outlines: a list of (N, 2) polylines (or lists of points), sampled along their length when painted."""
        if len(polylines):
            self.mq.append((layer, "lines", polylines))

    def mark_rect(self, x0, y0, x1, y1):
        """A baked / streamed city chunk: its outline on the map."""
        self._canvas()
        bx = self.box
        h, w = self.cv.shape[:2]
        c0, r0 = int((x0 - bx[0]) / (bx[2] - bx[0]) * w), int((y0 - bx[1]) / (bx[3] - bx[1]) * h)
        c1, r1 = int((x1 - bx[0]) / (bx[2] - bx[0]) * w), int((y1 - bx[1]) / (bx[3] - bx[1]) * h)
        c0, c1, r0, r1 = max(0, c0), min(w - 1, c1), max(0, r0), min(h - 1, r1)
        col = (*MAP_COL["chunk"], 255)
        self.cv[r0, c0:c1 + 1] = self.cv[r1, c0:c1 + 1] = col
        self.cv[r0:r1 + 1, c0] = self.cv[r0:r1 + 1, c1] = col
        self.cv_dirty = True

    def world_part(self, name, d):
        """World.__init__ read one part of the baked world: put what it contains on the map."""
        hx = d.get("hx", d.get("half"))
        if hx:
            self.set_box(float(hx), float(d.get("hy", hx)))
        if "areas" in d:
            self.plot_lines("areas", [a["v"] for a in d["areas"]])
        if "wlines" in d:
            self.plot_lines("water", [w["pts"] for w in d["wlines"]])
        if "roads" in d:
            self.plot_lines("roads", [r["pts"] for r in d["roads"]])
        if "buildings" in d:
            self.plot("buildings", [b["ring"][0] for b in d["buildings"]])
        if len(d.get("trees", ())):
            self.plot("trees", np.asarray(d["trees"], np.float64).reshape(-1, 4)[::2, :2])
        if len(d.get("parked", ())):
            self.plot("parked", [p[:2] for p in d["parked"]])
        self.say("✓ " + MK_PART.get(name, name).capitalize())

    def _canvas(self):
        if self.cv is None:
            if self.cv_tex is not None:
                rl.unload_texture(self.cv_tex)
                self.cv_tex = None
            bx = self.box
            h = max(8, int(self.GEO_W * (bx[3] - bx[1]) / (bx[2] - bx[0])))
            self.cv = np.zeros((h, self.GEO_W, 4), np.uint8)
            img = rl.gen_image_color(self.GEO_W, h, rl.Color(0, 0, 0, 0))
            self.cv_tex = rl.load_texture_from_image(img)
            rl.set_texture_filter(self.cv_tex, rl.TEXTURE_FILTER_BILINEAR)
            rl.unload_image(img)
            self.cv_dirty = True
            self.fresh = []

    def _paint(self, budget=0.012):
        """Paint queued map work for about `budget` seconds and upload the canvas.  New pixels flash white, then settle."""
        if not self.mq and not self.fresh and not self.cv_dirty:
            return
        try:
            self._canvas()
            h, w = self.cv.shape[:2]
            bx = self.box
            kx, ky = w / (bx[2] - bx[0]), h / (bx[3] - bx[1])
            now = time.time()
            if self.fresh and (self.mq or now - self.fresh_t > 0.25):   # settle the white flash into the layer colours
                for rr, cc, col in self.fresh:
                    self.cv[rr, cc] = col
                self.fresh = []
                self.cv_dirty = True
            t0 = time.perf_counter()
            done = 0                                                     # a few hundred pixels a frame: the map keeps filling in between events
            while self.mq and time.perf_counter() - t0 < budget and done < 900:
                layer, kind, data = self.mq.popleft()
                col = (*MAP_COL.get(layer, (255, 255, 255)), 255)
                if kind == "lines":
                    if len(data) > 25:                                   # a long list is painted in small slices, in random order
                        data = list(data)
                        self.rng.shuffle(data)
                        self.mq.appendleft((layer, "lines", data[25:]))
                        data = data[:25]
                    parts = []
                    for p in data:
                        p = np.asarray(p, np.float64).reshape(-1, 2)
                        if len(p) < 2:
                            parts.append(p)
                            continue
                        seg = np.hypot(*np.diff(p, axis=0).T)
                        n = np.maximum(1, np.ceil(seg * kx / 0.7)).astype(int)    # a sample about every 0.7 pixel
                        i0 = np.repeat(np.arange(len(seg)), n)
                        t = np.concatenate([np.arange(k) / k for k in n])
                        parts.append(p[i0] + (p[i0 + 1] - p[i0]) * t[:, None])
                    pts = np.concatenate(parts) if parts else np.zeros((0, 2))
                else:
                    pts = data
                    if len(pts) > 500:
                        idx = self.rng.permutation(len(pts))
                        self.mq.appendleft((layer, "pts", pts[idx[500:]]))
                        pts = pts[idx[:500]]
                cc = ((pts[:, 0] - bx[0]) * kx).astype(int)
                rr = ((pts[:, 1] - bx[1]) * ky).astype(int)
                ok = (cc >= 0) & (cc < w) & (rr >= 0) & (rr < h)
                rr, cc = rr[ok], cc[ok]
                done += max(1, len(rr) // 4)
                self.cv[rr, cc] = (255, 255, 255, 255)
                self.fresh.append((rr, cc, col))
                self.fresh_t = time.time()
                self.cv_dirty = True
            if self.cv_dirty:
                rl.update_texture(self.cv_tex, rl.ffi.cast("void *", rl.ffi.from_buffer(self.cv)))
                self.cv_dirty = False
        except Exception:  # noqa: BLE001 - the picture is decoration; never break loading for it
            self.mq.clear()
            self.fresh = []

    def _net_lines(self, x, y, w, now):
        active = any(c["st"] in ("active", "split") for c in self.cells.values())
        if active or self.bytes_by_id:
            total = sum(self.bytes_by_id.values())
            quiet = now - self.last_net if self.last_net else 0
            self.rate_hist.append((now, total))                     # real throughput: all parallel tiles over ~5 s
            while len(self.rate_hist) > 2 and now - self.rate_hist[0][0] > 5:
                self.rate_hist.popleft()
            t0_, b0_ = self.rate_hist[0]
            bps = (total - b0_) / (now - t0_) if now - t0_ > 0.5 else self.bps
            col = GREEN if bps > 20e3 else (ORANGE if bps > 0 else RED)
            sp = f"{bps / 1e6:.2f} {T.MB}{T.PER_S}" if bps >= 1e6 else f"{bps / 1e3:.0f} {T.KB}{T.PER_S}"
            if self.waiting or (getattr(self, "cut", None) and self.cut.get("pass", 3) < 3):
                col, sp = GREY, "–"
            font.draw_text(f"{T.L_SPEED}  {sp}", x, y, 17, col, bold=True)
            font.draw_text(f"{T.L_GOT}  {_size(total)}", x + int(w * 0.42), y, 17, WHITE)
            y += 22
            if self.mirror:
                cid = self.active_id
                what = T.LAYER.get(self.cells.get(cid, {}).get("layer", ""), "") if cid else ""
                line = f"{T.L_SERVER}" + (f"   {what}" if what else "") + (f"   {T.L_WAIT} {self.wait_sec} {T.SEC}" if self.net_state == "wait" else "")
                font.draw_text(font.fit(line, 14, w), x, y, 14, GREY)
                y += 20
            cut = getattr(self, "cut", None)
            if cut and cut.get("pass", 3) < 3:
                font.draw_text(font.fit(f"» {T.CUTTING} {cut.get('frac', 0) * 100:3.0f}%  –  {cut.get('found', 0):,} {T.C_FOUND}".replace(",", " "),
                                        15, w), x, y, 15, rl.Color(255, 220, 90, 255))
                y += 20
            elif active and self.last_net and quiet > 4 and not self.waiting:
                self.alert = (f"{T.NO_DATA} {int(quiet)} {T.SEC} – {T.WARN['stall']}", RED if quiet > 15 else ORANGE, now + 2)
        if self.waiting:
            why, left, t = self.waiting
            left = max(0, left - int(now - t))
            font.draw_text(font.fit(f"{T.REST} {left} {T.SEC}: {T.WARN.get(why, '')}", 15, w), x, y, 15, ORANGE)
            y += 22
        elif self.alert and now < self.alert[2]:
            for ln in font.wrap(mk(self.alert[0]), 15, w)[:2]:
                font.draw_text(ln, x, y, 15, self.alert[1])
                y += 20
        if self.warn:
            font.draw_text(font.fit(mk(self.warn), 15, w), x, y, 15, ORANGE)
            y += 22
        if self.radio_line:
            font.draw_text(font.fit(mk(self.radio_line), 14, w), x, y, 14, GREY)
            y += 20
        return y


def fatal_screen(title, lines, seconds=0):
    """Show an error until the window is closed (or for `seconds`)."""
    t0 = time.time()
    while not rl.window_should_close():
        rl.begin_drawing()
        rl.clear_background(rl.Color(40, 18, 18, 255))
        font.draw_text(mk(title), 60, 60, 36, rl.Color(255, 120, 100, 255))
        y = 120
        for ln in lines:
            font.draw_text(mk(ln)[:130], 60, y, 18, rl.Color(230, 230, 230, 255))
            y += 26
        font.draw_text(T.CLOSE_TO_EXIT, 60, y + 20, 18, rl.Color(200, 200, 200, 255))
        font.exit_button()
        rl.end_drawing()
        if seconds and time.time() - t0 > seconds:
            break


def retry_screen(title, lines):
    """An error with a way out: Enter = try again (True), Esc / closing the window = quit (False)."""
    while not rl.window_should_close():
        rl.begin_drawing()
        rl.clear_background(rl.Color(40, 18, 18, 255))
        font.draw_text(mk(title), 60, 60, 36, rl.Color(255, 120, 100, 255))
        y = 120
        for ln in lines:
            for part in font.wrap(mk(ln), 18, 1100):
                font.draw_text(part, 60, y, 18, rl.Color(230, 230, 230, 255))
                y += 26
        font.draw_text(T.DL_RETRY_KEYS, 60, y + 20, 18, rl.Color(200, 200, 200, 255))
        rl.end_drawing()
        if rl.is_key_pressed(rl.KEY_ENTER) or rl.is_key_pressed(rl.KEY_KP_ENTER):
            return True
        if rl.is_key_pressed(rl.KEY_ESCAPE):
            return False
    return False
