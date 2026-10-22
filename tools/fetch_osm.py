"""Download OpenStreetMap data for the world box (11 x 7 km) from Overpass into data/osm/ - hardened.

* the box is cut into 3 x 2 cells and every (layer, cell) is one request; every finished request is stored in
  data/osm/parts/ so an interrupted or partly failed run resumes where it stopped;
* mirrors are scored and rotated, busy servers are asked politely (status check, Retry-After), rejected or timed-out
  cells are split into quarters, stalled transfers are aborted, everything has a deadline - no endless loops;
* progress goes to the game as `@@{json}` lines (plan / cell / net / warn), see net.py.

Exit code: 0 complete, 2 usable but incomplete (re-run resumes), 1 nothing usable.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from geo import HX, HY, bbox, project

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("GTA_OSM_DIR") or os.path.join(ROOT, "data", "osm")
PARTS = os.path.join(OUT, "parts")
MIRRORS = os.environ.get("GTA_OVERPASS", "").split(",") if os.environ.get("GTA_OVERPASS") else [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
    "https://overpass.osm.vi-di.fr/api/interpreter",
]
PARTS_FMT = 2          # 2: ways carry their node ids (the road graph needs them); older parts are fetched again
SOURCES = ("auto", "geofabrik", "overpass")
LAYERS = ["roads", "buildings", "areas", "pois", "places"]
REQUIRED = {"roads", "buildings"}
UNIT_LIMIT = float(os.environ.get("GTA_UNIT_LIMIT", 20 * 60))      # seconds per cell, all attempts together
TOTAL_LIMIT = float(os.environ.get("GTA_TOTAL_LIMIT", 55 * 60))    # seconds for the whole download
MAX_ATTEMPTS = 6
WORKERS = int(os.environ.get("GTA_WORKERS", 4))             # pieces downloaded at the same time
QUERY_TIMEOUT = int(os.environ.get("GTA_QUERY_TIMEOUT", 60))      # small tiles answer fast; a slow server is dropped early
GRID = (int(os.environ.get("GTA_TILES_X", 11)), int(os.environ.get("GTA_TILES_Y", 7)))   # ~1 x 1 km tiles

LEISURE = "park|garden|pitch|playground|golf_course|recreation_ground|nature_reserve|stadium|track|sports_centre"
PLACE = "suburb|neighbourhood|quarter|city_district|district|village|town|hamlet|locality|square|borough"


def queries(b):
    bb = "%f,%f,%f,%f" % b
    return {
        "places": (
            f'node["place"~"^({PLACE})$"]({bb});way["place"~"^({PLACE})$"]({bb});rel["place"~"^({PLACE})$"]({bb});'
            f'rel["boundary"="administrative"]["admin_level"~"^(7|8|9|10)$"]({bb});'
            f'way["boundary"="administrative"]["admin_level"~"^(9|10)$"]({bb});'
        ),
        "roads": f'way["highway"]({bb});',
        "buildings": f'way["building"]({bb});rel["building"]({bb});',
        "areas": (
            f'way["landuse"]({bb});way["natural"~"water|wood|scrub|grassland|bare_rock|sand|beach"]({bb});'
            f'way["leisure"~"{LEISURE}"]({bb});way["waterway"]({bb});way["amenity"="parking"]({bb});'
            f'way["railway"~"^(rail|light_rail|tram)$"]({bb});way["place"="square"]({bb});'
            f'rel["natural"="water"]({bb});rel["landuse"]({bb});rel["leisure"~"{LEISURE}"]({bb});'
            f'rel["waterway"="riverbank"]({bb});'
        ),
        "pois": f'node["natural"="tree"]({bb});node["highway"~"street_lamp|traffic_signals"]({bb});',
    }


def tiles(b, nx=3, ny=2):
    s_, w_, n_, e_ = b
    out = []
    for i in range(ny):
        for j in range(nx):
            out.append((i, j, (s_ + (n_ - s_) * i / ny, w_ + (e_ - w_) * j / nx, s_ + (n_ - s_) * (i + 1) / ny, w_ + (e_ - w_) * (j + 1) / nx)))
    return out


def local_rect(b):
    x0, y1 = project(b[0], b[1])
    x1, y0 = project(b[2], b[3])
    return [round(min(x0, x1)), round(min(y0, y1)), round(max(x0, x1)), round(max(y0, y1))]


def quarters(b):
    s_, w_, n_, e_ = b
    ms, mw = (s_ + n_) / 2, (w_ + e_) / 2
    return [(s_, w_, ms, mw), (s_, mw, ms, e_), (ms, w_, n_, mw), (ms, mw, n_, e_)]


# ------------------------------------------------------------------------------------------------ one request
def wait_for_slot(url, uid):
    """Ask Overpass whether it has a free slot (it rejects instead of queueing when it is full)."""
    st = url.rsplit("/", 1)[0] + "/status"
    for _ in range(4):
        try:
            txt = net.fetch(st, uid + ":status", first_byte=10, stall=10).decode("utf-8", "replace")
        except net.Fail:
            return                                        # status page missing / slow: just try the real request
        m = re.search(r"(\d+) slots? available now", txt)
        if m and int(m.group(1)) > 0:
            return
        m = re.search(r"in (\d+) seconds", txt)
        if not m:
            return
        wait = min(90, int(m.group(1)) + 1)
        net.emit("warn", id=uid, kind="busy", mirror=net.host(url), msg="no free slot", left=wait)
        net.sleep_visible(wait, uid, "busy")


def run_unit(mirrors, layer, bb, uid, deadline, depth=0):
    q = queries(bb)[layer]
    body = urllib.parse.urlencode({"data": f"[out:json][timeout:{QUERY_TIMEOUT}];({q});out geom;"}).encode()
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if time.time() > deadline:
            raise net.Fail("timeout", "time limit for this piece")
        u = mirrors.pick()
        try:
            wait_for_slot(u, uid)
            raw = net.fetch(u, uid, data=body, first_byte=QUERY_TIMEOUT + 15, stall=20)
            try:
                js = json.loads(raw)
            except ValueError as e:
                raise net.Fail("bad", f"unreadable answer ({e})")
            remark = str(js.get("remark", ""))
            if "elements" not in js or re.search(r"runtime error|out of memory|timed out|too many", remark, re.I):
                raise net.Fail("reject", remark[:80] or "no elements")
            els = js["elements"]
            if not els and layer in REQUIRED and depth == 0:
                raise net.Fail("bad", "empty answer for a city area")
            mirrors.good(u, 1)
            if depth:
                net.emit("cell", id=uid, state="done", n=len(els))
            return els
        except net.Fail as f:
            last = f
            mirrors.bad(u, f)
            net.emit("warn", id=uid, kind=f.kind, mirror=net.host(u), attempt=attempt, msg=f.msg[:90])
            if mirrors.exhausted() and attempt >= 3:
                raise net.Fail("exhausted", "every mirror failed repeatedly")
            if f.kind in ("reject", "timeout", "stall") and attempt >= 2 and depth < 2:
                net.emit("cell", id=uid, state="split")
                els, seen = [], set()
                for k, qb in enumerate(quarters(bb)):
                    for el in run_unit(mirrors, layer, qb, f"{uid}.{k}", deadline, depth + 1):
                        key = (el.get("type"), el.get("id"))
                        if key not in seen:
                            seen.add(key)
                            els.append(el)
                return els
            net.sleep_visible(min(45, 4 * attempt + f.retry_after), uid, f.kind)
    raise last or net.Fail("net", "failed")


# ------------------------------------------------------------------------------------------------ driver
def part_path(layer, i, j):
    return os.path.join(PARTS, f"{layer}_{i}_{j}.json")


def preview(uid, layer, els, limit=1500):
    """Send a light sketch of what a tile contains (roads as lines, buildings as dots) so the splash map draws the city
    as it arrives.  Coordinates: local metres, rounded to 5 m."""
    lines, n = [], 0
    for el in els:
        g = el.get("geometry")
        if not g:
            continue
        step = max(1, len(g) // 8)
        pts = g[::step] + ([g[-1]] if (len(g) - 1) % step else [])
        if layer == "buildings":
            pts = pts[:1]
        flat = []
        for p in pts:
            x, y = project(p["lat"], p["lon"])
            flat += [int(x / 5) * 5, int(y / 5) * 5]
        lines.append(flat)
        n += len(flat)
        if n > limit * 2:
            break
    if lines:
        net.emit("geo", id=uid, layer=layer, lines=lines)


def save_part(layer, i, j, els):
    tmp = part_path(layer, i, j) + f".tmp.{layer}_{i}_{j}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"elements": els}, fh)
    os.replace(tmp, part_path(layer, i, j))


def from_pbf(grid, todo, results):
    """Geofabrik route: fill the missing parts from one country file. Returns True when nothing is missing."""
    import fetch_pbf
    print(f"[osm] Geofabrik route: {len(todo)} pieces to fill from the country file")
    try:
        pbf = fetch_pbf.download(os.path.join(OUT, "pbf"))
        net.emit("note", kind="pbf_cut")
        s_, w_, n_, e_ = bbox()
        ny, nx = GRID[1], GRID[0]
        buf, seen = {}, set()

        def tile_of(el):
            lat, lon = fetch_pbf.first_point(el)
            if lat is None:
                return None
            return (min(ny - 1, max(0, int((lat - s_) / (n_ - s_) * ny))), min(nx - 1, max(0, int((lon - w_) / (e_ - w_) * nx))))

        def on_el(layer, el):                      # live: the tile lights up and its streets appear as they are found
            t = tile_of(el)
            if t is None:
                return
            k = (layer,) + t
            if k not in seen:
                seen.add(k)
                net.emit("cell", id=f"{layer}:{t[0]}:{t[1]}", state="active")
            buf.setdefault(k, []).append(el)

        def on_tick(st):
            for (layer, i, j), els in list(buf.items()):
                preview(f"{layer}:{i}:{j}", layer, els, limit=400)
            buf.clear()
            phase = {1: "relations", 2: "nodes + ways", 3: "done"}[st["pass"]]
            est = max(1.0, os.path.getsize(pbf) * 0.14)               # ~ objects per byte of a .osm.pbf
            frac = 0.05 if st["pass"] == 1 else min(0.95, 0.05 + 0.9 * (st["nodes"] + st["ways"]) / est)
            net.emit("cut", nodes=st["nodes"], ways=st["ways"], found=st["found"], frac=round(frac if st["pass"] < 3 else 0.97, 3),
                     **{"pass": st["pass"]})
            print(f"[osm] cutting Skopje out of the country file ({phase}): {st['nodes']:,} nodes, {st['ways']:,} ways, "
                  f"{st['rels']:,} relations read; {st['found']:,} objects in the box")
        by_layer = fetch_pbf.extract(pbf, on_el, on_tick)
    except ImportError:
        net.emit("warn", id="pbf", kind="bad", msg="pyosmium missing")
        print("[osm] pyosmium is not installed - using Overpass")
        return False
    except Exception as e:  # noqa: BLE001 - broken file, no network...: the other route takes over
        import traceback
        print("[osm] Geofabrik route failed:", repr(e))
        print(traceback.format_exc()[-800:])
        net.emit("warn", id="pbf", kind=getattr(e, "kind", "bad"), msg=str(e)[:90])
        try:
            os.remove(os.path.join(OUT, "pbf", "country.osm.pbf"))       # maybe corrupt: fetch it fresh next time
        except OSError:
            pass
        for layer, i, j, _b in todo:
            net.emit("cell", id=f"{layer}:{i}:{j}", state="pending")
        return False
    transit = by_layer.pop("_transit", [])
    try:                                        # bus lines for the game (only the Geofabrik route has them)
        with open(os.path.join(OUT, "transit.json.tmp"), "w", encoding="utf-8") as fh:
            json.dump(transit, fh)
        os.replace(os.path.join(OUT, "transit.json.tmp"), os.path.join(OUT, "transit.json"))
        print(f"[osm] bus lines: {len(transit)} ({', '.join(sorted({t['ref'] for t in transit if t['ref']})[:40])})")
    except OSError as e:
        print("[osm] could not save bus lines:", e)
    s_, w_, n_, e_ = bbox()
    ny, nx = GRID[1], GRID[0]
    want = {(l, i, j) for l, i, j, _b in todo}
    split = {k: [] for k in want}
    for layer, els in by_layer.items():
        for el in els:
            lat, lon = fetch_pbf.first_point(el)
            if lat is None:
                continue
            i = min(ny - 1, max(0, int((lat - s_) / (n_ - s_) * ny)))
            j = min(nx - 1, max(0, int((lon - w_) / (e_ - w_) * nx)))
            if (layer, i, j) in split:
                split[(layer, i, j)].append(el)
    for (layer, i, j), els in split.items():
        save_part(layer, i, j, els)
        results[(layer, i, j)] = els
        net.emit("cell", id=f"{layer}:{i}:{j}", state="done", n=len(els))
    print(f"[osm] Geofabrik route: {sum(len(v) for v in split.values())} objects in {len(split)} pieces")
    return True


def load_part(layer, i, j):
    try:
        with open(part_path(layer, i, j), encoding="utf-8") as f:
            js = json.load(f)
        return js["elements"] if "elements" in js else None
    except Exception:  # noqa: BLE001
        return None


def clear_parts():
    for fn in os.listdir(PARTS):
        if fn == "box.json":
            continue
        try:
            os.remove(os.path.join(PARTS, fn))
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--source", choices=SOURCES, default=os.environ.get("GTA_SOURCE", "auto"),
                    help="auto = Geofabrik file first, Overpass for whatever is still missing")
    a = ap.parse_args()
    os.makedirs(PARTS, exist_ok=True)
    if not net.single_instance("osm", OUT):
        net.emit("note", kind="busy_other")
        print("[osm] another download is already running - not starting a second one")
        return 2 if os.path.exists(os.path.join(OUT, "roads.json")) else 1
    net.clean_tmp(PARTS)
    net.clean_tmp(OUT)
    boxf = os.path.join(OUT, "box.json")
    try:
        old = json.load(open(boxf))
    except Exception:  # noqa: BLE001
        old = None
    if (old or {}).get("hx") != HX or (old or {}).get("hy") != HY:
        if old is not None or any(os.path.exists(os.path.join(OUT, n + ".json")) for n in LAYERS):
            net.emit("note", kind="newbox")
            print(f"[osm] the cached data covers another area; downloading the {HX * 2 / 1000:.0f} x {HY * 2 / 1000:.0f} km box")
    # the parts folder remembers its own box: an interrupted first download (no box.json yet) keeps what it already has
    pbox = os.path.join(PARTS, "box.json")
    try:
        pb = json.load(open(pbox))
    except Exception:  # noqa: BLE001
        pb = None
    if (pb or {}).get("hx") != HX or (pb or {}).get("hy") != HY or (pb or {}).get("grid") != list(GRID) or (pb or {}).get("fmt") != PARTS_FMT:
        clear_parts()
        json.dump({"hx": HX, "hy": HY, "grid": list(GRID), "fmt": PARTS_FMT}, open(pbox, "w"))
    if a.force:
        clear_parts()
    grid = tiles(bbox(), *GRID)
    cells = [(layer, i, j, b) for layer in LAYERS for (i, j, b) in grid]
    net.emit("plan", what="osm", box=[-HX, -HY, HX, HY], layers=LAYERS,
             cells=[{"id": f"{l}:{i}:{j}", "layer": l, "r": local_rect(b)} for l, i, j, b in cells])
    mirrors = net.Mirrors(MIRRORS)
    t_start = time.time()
    results = {}
    for layer, i, j, b in cells:
        els = load_part(layer, i, j)
        if els is not None:
            results[(layer, i, j)] = els
            net.emit("cell", id=f"{layer}:{i}:{j}", state="done", cached=1, n=len(els))
            preview(f"{layer}:{i}:{j}", layer, els)
    todo0 = [c for c in cells if (c[0], c[1], c[2]) not in results]
    print(f"[osm] source={a.source}, {len(cells) - len(todo0)} pieces cached, {len(todo0)} to get")
    if todo0 and a.source != "overpass":
        from_pbf(grid, todo0, results)
    tj = os.path.join(OUT, "transit.json")
    if not todo0 and a.source != "overpass" and not os.path.exists(tj):
        try:
            import fetch_pbf
            print("[osm] map cached; reading the JSP bus lines from the country file")
            tr = fetch_pbf.routes_only(fetch_pbf.download(os.path.join(OUT, "pbf")))
            with open(tj + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(tr, fh)
            os.replace(tj + ".tmp", tj)
            print(f"[osm] bus lines: {len(tr)}")
        except Exception as e:  # noqa: BLE001 - buses are optional
            print(f"[osm] bus lines skipped: {e}")
    if a.source != "overpass" and not os.path.exists(os.path.join(OUT, "map_pois.json")):
        try:
            import fetch_pois
            fetch_pois.main()
        except Exception as e:  # noqa: BLE001 - map markers are optional
            print(f"[osm] points of interest skipped: {e}")
    failed = []
    offline = a.source == "geofabrik"                 # chosen route only: no Overpass fallback
    if offline:
        failed = [f"{l}:{i}:{j}" for l, i, j, _b in cells if (l, i, j) not in results]
    bad_run = 0
    for rnd in (1, 2):
        todo = [c for c in cells if (c[0], c[1], c[2]) not in results]
        if not todo or offline:
            break
        if rnd == 2:
            net.emit("note", kind="second_pass", left=len(todo))
            for u in mirrors.urls:
                mirrors.cool[u] = 0.0
                mirrors.fails[u] = 0
        failed = []
        import concurrent.futures as cf
        lock = threading.Lock()
        state = {"offline": offline, "bad_run": bad_run}

        def work(cell):
            layer, i, j, b = cell
            uid = f"{layer}:{i}:{j}"
            if state["offline"] or time.time() - t_start > TOTAL_LIMIT:
                if not state["offline"]:
                    net.emit("note", kind="total_limit")
                return uid, None
            net.emit("cell", id=uid, state="active")
            try:
                els = run_unit(mirrors, layer, b, uid, min(time.time() + UNIT_LIMIT, t_start + TOTAL_LIMIT))
            except net.Fail as f:
                net.emit("cell", id=uid, state="fail", kind=f.kind)
                print(f"[osm] {uid} FAILED: {f}")
                with lock:
                    state["bad_run"] = state["bad_run"] + 1 if f.kind in ("offline", "exhausted") else 0
                    if f.kind == "offline" or state["bad_run"] >= 2:
                        net.emit("note", kind="offline" if f.kind == "offline" else "unreachable")
                        state["offline"] = True
                return uid, None
            with lock:
                state["bad_run"] = 0
            tmp = part_path(layer, i, j) + ".tmp." + uid.replace(":", "_")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"elements": els}, fh)
            os.replace(tmp, part_path(layer, i, j))
            results[(layer, i, j)] = els
            net.emit("cell", id=uid, state="done", n=len(els))
            preview(uid, layer, els)
            return uid, els

        failed = []
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:           # several small pieces at once, spread over mirrors
            for uid, els in ex.map(work, todo):
                if els is None:
                    failed.append(uid)
        offline = state["offline"]
        bad_run = state["bad_run"]
        if not failed:
            break
    # merge the parts of every layer that has any
    for layer in LAYERS:
        seen, merged, have = set(), [], 0
        for (l, i, j), els in results.items():
            if l != layer:
                continue
            have += 1
            for el in els:
                key = (el.get("type"), el.get("id"))
                if key not in seen:
                    seen.add(key)
                    merged.append(el)
        if have:
            tmp = os.path.join(OUT, layer + ".json.tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"elements": merged}, fh)
            os.replace(tmp, os.path.join(OUT, layer + ".json"))
    complete = not failed
    usable = all(any(l == r for (l, _i, _j) in results) for r in REQUIRED)
    json.dump({"hx": HX, "hy": HY, "fmt": PARTS_FMT, "complete": complete, "missing": failed, "t": time.time()}, open(boxf, "w"))
    net.emit("done", what="osm", complete=complete, usable=usable, missing=len(failed), sec=int(time.time() - t_start))
    if complete:
        print("[osm] done")
        return 0
    print(f"[osm] incomplete: {len(failed)} pieces missing; run again to resume")
    return 2 if usable else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print("[osm] ERROR:", e)
        sys.exit(1)
