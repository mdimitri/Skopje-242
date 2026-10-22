"""Loading screen: one monotone overall bar, a map of what is being downloaded and where it goes, the real transfer
speed, warnings when a server stalls or rejects, and a random poster that illustrates the joke under the bar."""
import collections
import json
import os
import random
import time

import pyray as rl
import font   # noqa: E402

import geo
import poster as poster_mod
import showcase as showcase_mod
import slang
import strings as T

GOLD = rl.Color(240, 200, 60, 255)
WHITE = rl.Color(235, 235, 235, 255)
GREY = rl.Color(150, 154, 165, 255)
DIM = rl.Color(100, 104, 114, 255)
ORANGE = rl.Color(255, 170, 60, 255)
RED = rl.Color(235, 85, 75, 255)
GREEN = rl.Color(95, 200, 125, 255)
BLUE = rl.Color(120, 190, 250, 255)
C_PENDING = rl.Color(52, 56, 68, 255)
C_ACTIVE = rl.Color(255, 205, 70, 255)
C_DONE = rl.Color(70, 185, 110, 255)
C_CACHED = rl.Color(60, 140, 120, 255)
C_FAIL = rl.Color(220, 70, 60, 255)
C_SPLIT = rl.Color(185, 120, 235, 255)
LAYER_ORDER = ["roads", "buildings", "areas", "pois", "places"]

# rough seconds of a full-city build per phase; used only until the first real build has recorded its own timings
BUILD_DEFAULT = {
    "read OSM files": 20, "buildings -> 3D meshes": 60, "areas / water / rails": 15, "roads": 25,
    "building meshes on terrain": 90, "graph": 10, "bridge decks": 5, "places": 2, "street furniture": 20,
    "procedural trees in parks/woods": 15, "street trees, lamps, parked cars": 25, "3D roads": 40, "ground rasters": 10,
    "tree meshes": 10, "lamp meshes": 5, "chunk index: areas": 10, "spawn point": 1, "write world": 2,
    "write mesh blob": 10, "write world parts": 10,
}
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
        self.geo_pending = []               # sketches of downloaded tiles, drawn into geo_rt (a texture of the whole box)
        self.geo_rt = None
        self.rate_hist = collections.deque()
        self.b_label = None
        self.b_t0 = 0.0
        self.b_done = set()
        self.b_frac = 0.0
        self.posters = poster_mod.Posters()
        self.show = showcase_mod.Showcase()
        self.title_until = time.time() + 5.0 if self.posters.title() else 0.0
        self.quip = random.choice(slang.LOADING_QUIPS)
        self.quip_t = self.title_until or time.time()
        if self.posters.title():
            self.quip = T.TAGLINE                      # the title poster comes first, then the jokes
        elif self.posters.items:
            self.quip = self.posters.next()[1]

    # ---------------------------------------------------------------- stage control
    def say(self, text):
        self.log.append(f"[{_fmt(time.time() - self.t0)}] {text}")
        del self.log[:-200]

    def begin(self, key, note=""):
        if self.cur and self.cur != key:
            self.f[self.cur] = 1.0
        self.cur = key
        self.note = note
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
        self.draw(force=True)

    def tick(self, frac, note=None):
        if self.cur:
            self.f[self.cur] = max(self.f[self.cur], max(0.0, min(1.0, frac)))
        if note is not None:
            self.note = note
        self.draw()

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
                    self.say(f"↓ {nm} {where}" + (f" – {self.mirror}" if self.mirror else ""))
            elif st == "done":
                self.say(f"✓ {nm} {where}: {ev.get('n', 0)} {T.OBJECTS}" + (f" ({T.LEG_CACHED.lower()})" if ev.get("cached") else ""))
            elif st == "fail":
                self.say(f"✗ {nm} {where}: {T.WARN.get(ev.get('kind', 'net'), T.WARN['net'])}")
            elif st == "split":
                self.say(f"+ {nm} {where}: {T.LEG_SPLIT.lower()}")
        elif t == "net":
            cid = ev.get("id", "")
            self.last_net = now
            self.mirror = ev.get("mirror", self.mirror)
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
            self.say(f"{ev.get('mirror', '')}: {txt}")
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
            self.geo_pending.append((ev.get("layer", ""), ev.get("lines", [])))
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
        self.note = T.BUILD.get(lab, lab)

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
        if not force and now - self.last_draw < 0.04:
            return
        self.last_draw = now
        if rl.window_should_close():
            raise SystemExit(0)
        if now - self.quip_t > 7.0 and now > self.title_until:
            self.quip_t = now
            self.quip = random.choice(slang.LOADING_QUIPS)
        W, H = rl.get_screen_width(), rl.get_screen_height()
        self._flush_geo()
        rl.begin_drawing()
        rl.clear_background(rl.Color(18, 20, 25, 255))
        m = max(16, W // 60)
        lw = int(W * 0.44)
        rx = m + lw + (m if lw else 0)
        rw = W - rx - m
        if lw:
            if now < self.title_until and self.posters.title():
                ph = min(int(lw * 0.625), H - 2 * m)
                py = (H - ph) // 2
                poster_mod.draw_fit(self.posters.title(), m, py, lw, ph)
                rl.draw_rectangle_lines(m, py, lw, ph, rl.Color(90, 92, 98, 255))
            else:
                try:
                    self.show.draw(m, m, lw, H - 2 * m)
                except Exception:  # noqa: BLE001 - decoration only; loading must never fail because of it
                    try:
                        rl.end_scissor_mode()
                    except Exception:  # noqa: BLE001
                        pass
        y = m
        font.draw_text(T.TITLE, rx, y, 34, GOLD, bold=True)
        y += 46
        ov = self.overall()
        el = now - self.t0
        eta = (el / ov - el) if ov > 0.05 else 0
        font.draw_text(f"{T.L_TOTAL}  {ov * 100:3.0f}%", rx, y, 20, WHITE, bold=True)
        right = f"{T.L_ELAPSED} {_fmt(el)}" + (f"   {T.L_LEFT} {_fmt(eta)}" if eta else "")
        font.draw_text(right, rx + rw - font.measure_text(right, 16), y + 3, 16, GREY)
        self._bar(rx, y + 26, rw, 14, ov, GOLD)
        y += 48
        for ln in font.wrap(self.quip, 17, rw)[:2]:
            font.draw_text(ln, rx, y, 17, rl.Color(215, 200, 150, 255))
            y += 22
        y += 6
        # ---- stages (compact)
        for k in self.keys:
            if self.f[k] >= 0.999:
                font.draw_text("✓ " + T.STAGE[k], rx, y, 15, GREEN)
            elif k == self.cur:
                font.draw_text("▶ " + T.STAGE[k], rx, y, 15, WHITE, bold=True)
                pc = f"{self.f[k] * 100:3.0f}%"
                font.draw_text(pc, rx + rw - font.measure_text(pc, 15), y, 15, WHITE)
                self._bar(rx, y + 19, rw, 6, self.f[k], BLUE)
                y += 10
            else:
                font.draw_text("· " + T.STAGE[k], rx, y, 15, DIM)
            y += 21
        if self.note:
            font.draw_text(font.fit(self.note, 15, rw), rx + 14, y, 15, GREY)
            y += 22
        # ---- the download map
        if self.cells:
            y = self._map(rx, y + 4, rw, H - y - 4 - m - 150)
        # ---- speed / alerts
        y = self._net_lines(rx, y + 4, rw, now)
        # ---- live activity log: every tile, server, retry and step as it happens
        lines = (H - m - y - 4) // 17
        if lines > 0 and self.log:
            for ln in self.log[-lines:]:
                c = GREEN if "✓" in ln else (RED if "✗" in ln else (rl.Color(255, 220, 90, 255) if "↓" in ln else GREY))
                font.draw_text(font.fit(ln, 13, rw), rx, y + 4, 13, c)
                y += 17
        font.exit_button()
        rl.end_drawing()

    def _map(self, x, y, w, h_avail):
        mw = min(w, int(max(120, h_avail - 40) * (self.box[2] - self.box[0]) / (self.box[3] - self.box[1])))
        mh = int(mw * (self.box[3] - self.box[1]) / (self.box[2] - self.box[0]))
        if h_avail < 90:
            return y
        sx = mw / (self.box[2] - self.box[0])
        sy = mh / (self.box[3] - self.box[1])
        font.draw_text(T.L_MAP, x, y, 15, GREY, bold=True)
        y += 22
        rl.draw_rectangle(x, y, mw, mh, rl.Color(26, 29, 36, 255))
        pulse = 0.5 + 0.5 * ((time.time() * 2.2) % 1.0)
        cells = list(self.cells.values())
        layers = [l for l in LAYER_ORDER if any(c["layer"] == l for c in cells)]
        for c in cells:
            x0, y0, x1, y1 = c["r"]
            px, py = x + (x0 - self.box[0]) * sx, y + (y0 - self.box[1]) * sy
            pw_, ph_ = (x1 - x0) * sx, (y1 - y0) * sy
            col = self._cell_col(c, pulse)
            if c["layer"] == "dem":                                     # heights: a tinted frame over the whole tile
                rl.draw_rectangle(int(px), int(py), int(pw_), int(ph_), _col(col, 38))
                rl.draw_rectangle_lines_ex(rl.Rectangle(px + 1, py + 1, pw_ - 2, ph_ - 2), 2, _col(col, 200))
                continue
            n = max(1, len(layers))
            idx = layers.index(c["layer"]) if c["layer"] in layers else 0
            sh = ph_ / n
            r = rl.Rectangle(px + 2, py + sh * idx + 1, pw_ - 4, max(2, sh - 2))
            rl.draw_rectangle_rec(r, col)
            age = time.time() - c.get("t", 0)
            if c["st"] in ("done", "cached") and age < 2.0:             # just landed: white flash fading out
                rl.draw_rectangle_rec(r, rl.Color(255, 255, 255, int(200 * (1 - age / 2.0))))
            elif c["st"] == "active":
                rl.draw_rectangle_lines_ex(rl.Rectangle(px + 1, py + 1, pw_ - 2, ph_ - 2), 2, rl.Color(255, 220, 90, 255))
            if sh >= 14 and c["r"][0] <= self.box[0] + 1 and mw > 300:       # name the stripes once, on the western tiles
                font.draw_text(T.LAYER[c["layer"]], int(r.x) + 5, int(r.y) + int(sh / 2) - 7, 11, rl.Color(10, 12, 16, 230))
            if c["st"] == "split":                                      # quarters done so far
                for q in range(c["kids"]):
                    qx = r.x + (q % 2) * r.width / 2
                    rl.draw_rectangle_rec(rl.Rectangle(qx, r.y, r.width / 2 - 1, r.height), C_DONE)
        if self.geo_rt is not None:                                     # what has arrived so far, drawn as a map
            t = self.geo_rt.texture
            rl.draw_rectangle(x, y, mw, mh, rl.Color(14, 16, 22, 150))
            rl.draw_texture_pro(t, rl.Rectangle(0, 0, t.width, -t.height), rl.Rectangle(x, y, mw, mh), rl.Vector2(0, 0), 0.0,
                                rl.Color(255, 255, 255, 235))
        for ln in range(1, 4):                                          # a light grid: kilometres
            gx = x + mw * ln / 4
            rl.draw_line(int(gx), y, int(gx), y + mh, rl.Color(255, 255, 255, 14))
        rl.draw_rectangle_lines(x, y, mw, mh, rl.Color(90, 92, 98, 255))
        taken = []
        for name, lat, lon, _n in slang.LANDMARKS:                      # orientation: well-known places
            lx, ly = geo.project(lat, lon)
            if self.box[0] <= lx <= self.box[2] and self.box[1] <= ly <= self.box[3]:
                px, py = int(x + (lx - self.box[0]) * sx), int(y + (ly - self.box[1]) * sy)
                rl.draw_circle(px, py, 3, WHITE)
                if mw > 300 and all(abs(px - qx) > 70 or abs(py - qy) > 12 for qx, qy in taken):
                    taken.append((px, py))
                    font.draw_text(name, px + 5, py - 6, 11, rl.Color(255, 255, 255, 215))
        # ---- legend + per-layer counters on the right / below
        lx = x + mw + 12
        ly = y
        if lx + 150 < x + w:
            for l in layers + (["dem"] if any(c["layer"] == "dem" for c in cells) else []):
                mine = [c for c in cells if c["layer"] == l]
                done = sum(1 for c in mine if c["st"] in ("done", "cached"))
                font.draw_text(f"{T.LAYER[l]}  {done}/{len(mine)}", lx, ly, 14, WHITE if done < len(mine) else GREEN)
                ly += 19
            ly += 8
            for col, txt in ((C_PENDING, T.LEG_PENDING), (C_ACTIVE, T.LEG_ACTIVE), (C_DONE, T.LEG_DONE),
                             (C_CACHED, T.LEG_CACHED), (C_SPLIT, T.LEG_SPLIT), (C_FAIL, T.LEG_FAIL)):
                rl.draw_rectangle(lx, ly + 2, 12, 10, col)
                font.draw_text(txt, lx + 18, ly, 13, GREY)
                ly += 17
        return max(y + mh, ly)

    GEO_W, GEO_H = 1100, 700
    GEO_COL = {"roads": rl.Color(225, 225, 230, 255), "buildings": rl.Color(240, 200, 60, 255), "areas": rl.Color(90, 190, 110, 255),
               "pois": rl.Color(235, 90, 80, 255), "places": rl.Color(255, 255, 255, 255)}

    def _flush_geo(self):
        if not self.geo_pending:
            return
        try:
            if self.geo_rt is None:
                self.geo_rt = rl.load_render_texture(self.GEO_W, self.GEO_H)
                rl.begin_texture_mode(self.geo_rt)
                rl.clear_background(rl.Color(0, 0, 0, 0))
                rl.end_texture_mode()
            sx = self.GEO_W / (self.box[2] - self.box[0])
            sy = self.GEO_H / (self.box[3] - self.box[1])
            rl.begin_texture_mode(self.geo_rt)
            for layer, lines in self.geo_pending[:40]:          # a few tiles per frame keeps the screen fluid
                col = self.GEO_COL.get(layer, rl.WHITE)
                for fl in lines:
                    pts = [((fl[k] - self.box[0]) * sx, (fl[k + 1] - self.box[1]) * sy) for k in range(0, len(fl) - 1, 2)]
                    if len(pts) == 1 or layer in ("buildings", "pois", "places"):
                        rl.draw_rectangle(int(pts[0][0]), int(pts[0][1]), 2, 2, col)
                    else:
                        for a, b in zip(pts, pts[1:]):
                            rl.draw_line(int(a[0]), int(a[1]), int(b[0]), int(b[1]), col)
            rl.end_texture_mode()
            del self.geo_pending[:40]
        except Exception:  # noqa: BLE001 - the sketch is decoration; never break loading for it
            self.geo_pending = []

    @staticmethod
    def _cell_col(c, pulse):
        st = c["st"]
        if st == "active":
            return rl.Color(255, int(170 + 60 * pulse), 60, 255)
        return {"done": C_DONE, "cached": C_CACHED, "fail": C_FAIL, "split": C_SPLIT}.get(st, C_PENDING)

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
                line = f"{T.L_SERVER}: {self.mirror}" + (f"   {what}" if what else "") + (f"   {T.L_WAIT} {self.wait_sec} {T.SEC}" if self.net_state == "wait" else "")
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
            for ln in font.wrap(self.alert[0], 15, w)[:2]:
                font.draw_text(ln, x, y, 15, self.alert[1])
                y += 20
        if self.warn:
            font.draw_text(font.fit(self.warn, 15, w), x, y, 15, ORANGE)
            y += 22
        if self.radio_line:
            font.draw_text(font.fit(self.radio_line, 14, w), x, y, 14, GREY)
            y += 20
        return y

    @staticmethod
    def _bar(x, y, w, h, f, col):
        rl.draw_rectangle(x, y, w, h, rl.Color(50, 52, 58, 255))
        rl.draw_rectangle(x, y, int(w * max(0.0, min(1.0, f))), h, col)
        rl.draw_rectangle_lines(x, y, w, h, rl.Color(90, 92, 98, 255))


def fatal_screen(title, lines, seconds=0):
    """Show an error until the window is closed (or for `seconds`)."""
    t0 = time.time()
    while not rl.window_should_close():
        rl.begin_drawing()
        rl.clear_background(rl.Color(40, 18, 18, 255))
        font.draw_text(title, 60, 60, 36, rl.Color(255, 120, 100, 255))
        y = 120
        for ln in lines:
            font.draw_text(ln[:130], 60, y, 18, rl.Color(230, 230, 230, 255))
            y += 26
        font.draw_text(T.CLOSE_TO_EXIT, 60, y + 20, 18, rl.Color(200, 200, 200, 255))
        font.exit_button()
        rl.end_drawing()
        if seconds and time.time() - t0 > seconds:
            break
