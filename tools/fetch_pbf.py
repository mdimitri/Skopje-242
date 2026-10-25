"""Second download route: one country file (.osm.pbf) from Geofabrik, cut to the world box locally with pyosmium.

The result has exactly the shape of an Overpass `out geom` answer (ways with "geometry", relations with "members" that
carry geometry, nodes with lat/lon), split into the same (layer, tile) parts as fetch_osm.py, so the game and
build_world.py cannot tell the two routes apart.

* the download resumes (HTTP Range) after an interruption, aborts a stalled transfer and rotates between mirrors;
* the finished file is kept in data/osm/pbf/ and reused for 7 days, so a rebuild needs no network at all.
"""
import os
import re
import socket
import time
import urllib.request

import net
from geo import bbox

PBF_URLS = os.environ.get("SK242_PBF", "").split(",") if os.environ.get("SK242_PBF") else [
    "https://download.geofabrik.de/europe/macedonia-latest.osm.pbf",
    "https://download.openstreetmap.fr/extracts/europe/macedonia-latest.osm.pbf",
]
MAX_AGE = 7 * 86400
STALL = 30


def download(folder, uid="pbf"):
    """Return the path of a complete .osm.pbf, resuming a partial one. Raises net.Fail."""
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, "country.osm.pbf")
    part = dst + ".part"
    if os.path.exists(dst) and time.time() - os.path.getmtime(dst) < MAX_AGE:
        print(f"[pbf] using the country file downloaded {int((time.time() - os.path.getmtime(dst)) / 3600)} h ago "
              f"({os.path.getsize(dst) / 1e6:.1f} MB) - no download needed")
        net.emit("net", id=uid, state="done", bytes=os.path.getsize(dst), size=os.path.getsize(dst), bps=0, sec=0, mirror="cache")
        return dst
    last = None
    for attempt in range(1, 7):
        url = PBF_URLS[(attempt - 1) % len(PBF_URLS)]
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(url, headers={"User-Agent": net.UA, **({"Range": f"bytes={have}-"} if have else {})})
        t0, got = time.time(), 0
        try:
            with urllib.request.urlopen(req, timeout=STALL) as r:
                if have and r.status != 206:                 # server ignored the range: start again
                    have = 0
                size = have + int(r.headers.get("Content-Length") or 0)
                m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
                if m:
                    size = int(m.group(1))
                last_emit = 0.0
                with open(part, "ab" if have else "wb") as fh:
                    while True:
                        chunk = r.read(256 * 1024)            # socket timeout = stall guard
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if now - last_emit >= 1.0:
                            if int(now - t0) % 3 == 0:
                                print(f"[pbf] {net.host(url)}: {(have + got) / 1e6:.1f} of {size / 1e6:.1f} MB, "
                                      f"{got / max(0.1, now - t0) / 1e6:.2f} MB/s")
                            last_emit = now
                            net.emit("net", id=uid, state="recv", bytes=have + got, size=size,
                                     bps=int(got / max(0.1, now - t0)), sec=int(now - t0), mirror=net.host(url))
            total = have + got
            if size and total < size:
                raise net.Fail("stall", f"cut off at {total}/{size}")
            os.replace(part, dst)
            net.emit("net", id=uid, state="done", bytes=total, size=total, bps=int(got / max(0.1, time.time() - t0)),
                     sec=int(time.time() - t0), mirror=net.host(url))
            return dst
        except net.Fail as f:
            last = f
        except (socket.timeout, TimeoutError) as e:
            last = net.Fail("stall", str(e))
        except urllib.error.HTTPError as e:
            if e.code == 416:                                # partial file already complete or broken: restart
                os.remove(part)
            last = net.Fail("http", f"HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            last = net.Fail("offline" if attempt >= 4 and not os.path.exists(part) else "net", str(e)[:80])
        net.emit("warn", id=uid, kind=last.kind, mirror=net.host(url), attempt=attempt, msg=last.msg[:90])
        net.sleep_visible(min(30, 3 * attempt), uid, last.kind)
    raise last or net.Fail("net", "download failed")


# ------------------------------------------------------------------------------------------ tag rules = Overpass queries
LEISURE = re.compile("park|garden|pitch|playground|golf_course|recreation_ground|nature_reserve|stadium|track|sports_centre")
NATURAL = re.compile("water|wood|scrub|grassland|bare_rock|sand|beach")
PLACE = re.compile(r"^(suburb|neighbourhood|quarter|city_district|district|village|town|hamlet|locality|square|borough)$")


def layers_of(kind, t):
    """Which layers an object with tags `t` belongs to (same rules as fetch_osm.queries)."""
    out = []
    g = t.get
    if kind == "n":
        if PLACE.search(g("place", "") or "-"):
            out.append("places")
        if g("natural") == "tree" or re.search("street_lamp|traffic_signals", g("highway", "")):
            out.append("pois")
        if re.search(r"^(station|halt|level_crossing|crossing)$", g("railway", "")):
            out.append("areas")
        return out
    if PLACE.search(g("place", "") or "-") or (g("boundary") == "administrative" and re.search(
            r"^(7|8|9|10)$" if kind == "r" else r"^(9|10)$", g("admin_level", ""))):
        out.append("places")
    if g("building"):
        out.append("buildings")
    if kind == "w":
        if g("highway"):
            out.append("roads")
        if (g("landuse") or NATURAL.search(g("natural", "") or "-") or LEISURE.search(g("leisure", "") or "-")
                or g("waterway") or g("amenity") == "parking" or g("place") == "square"
                or re.search(r"^(rail|light_rail|tram|disused|platform)$", g("railway", ""))):
            out.append("areas")
    else:
        if (g("natural") == "water" or g("landuse") or LEISURE.search(g("leisure", "") or "-")
                or g("waterway") == "riverbank"):
            out.append("areas")
    return out


def extract(pbf, on_el=None, on_tick=None):
    """Cut the box out of the country file. Returns {layer: [elements]} in Overpass `out geom` form.
    on_el(layer, el) is called for every object found (live map), on_tick(stats) about twice a second."""
    import osmium
    st = {"nodes": 0, "ways": 0, "rels": 0, "found": 0, "pass": 1}
    last = [time.time()]

    def tick(force=False):
        if on_tick and (force or time.time() - last[0] > 0.5):
            last[0] = time.time()
            on_tick(dict(st))

    def found(l, el):
        st["found"] += 1
        if on_el:
            on_el(l, el)
    s_, w_, n_, e_ = bbox()

    def inside(lat, lon):
        return s_ <= lat <= n_ and w_ <= lon <= e_

    # pass 1: relations we want, and the ways they need
    rels, need_ways, routes = [], set(), []
    for r in osmium.FileProcessor(pbf, osmium.osm.RELATION):
        st["rels"] += 1
        tick()
        t = dict(r.tags)
        if t.get("type") == "route" and t.get("route") in ("bus", "trolleybus"):     # city bus lines (JSP and others)
            mem = [(m.type, m.ref, m.role) for m in r.members]
            routes.append((r.id, t, mem))
            need_ways.update(ref for ty, ref, _ in mem if ty == "w")
        ls = layers_of("r", t)
        if ls:
            mem = [(m.type, m.ref, m.role) for m in r.members]
            rels.append((r.id, t, ls, mem))
            need_ways.update(ref for ty, ref, _ in mem if ty == "w")
    # pass 2: nodes and ways with node locations
    out = {k: [] for k in ("roads", "buildings", "areas", "pois", "places")}
    way_geom, node_pos = {}, {}
    st["pass"] = 2
    fp = osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        tick()
        if o.is_node():
            st["nodes"] += 1
            if not o.location.valid():
                continue
            lat, lon = o.location.lat, o.location.lon
            if len(o.tags) and inside(lat, lon):
                t = dict(o.tags)
                el = None
                for l in layers_of("n", t):
                    el = el or {"type": "node", "id": o.id, "lat": lat, "lon": lon, "tags": t}
                    out[l].append(el)
                    found(l, el)
                node_pos[o.id] = (lat, lon)
            continue
        st["ways"] += 1
        ls = layers_of("w", dict(o.tags)) if len(o.tags) else []
        if not ls and o.id not in need_ways:
            continue
        ok = [nd for nd in o.nodes if nd.location.valid()]
        geom = [{"lat": nd.lat, "lon": nd.lon} for nd in ok]
        if not geom:
            continue
        if o.id in need_ways:
            way_geom[o.id] = geom
        if ls and any(inside(p["lat"], p["lon"]) for p in geom):
            el = {"type": "way", "id": o.id, "nodes": [nd.ref for nd in ok], "geometry": geom, "tags": dict(o.tags)}
            for l in ls:
                out[l].append(el)
                found(l, el)
    for rid, t, ls, mem in rels:
        members, hit = [], False
        for ty, ref, role in mem:
            if ty == "w" and ref in way_geom:
                g = way_geom[ref]
                hit = hit or any(inside(p["lat"], p["lon"]) for p in g)
                members.append({"type": "way", "ref": ref, "role": role, "geometry": g})
            elif ty == "n" and ref in node_pos:
                hit = True
                members.append({"type": "node", "ref": ref, "role": role, "lat": node_pos[ref][0], "lon": node_pos[ref][1]})
        if hit:
            el = {"type": "relation", "id": rid, "members": members, "tags": t}
            for l in ls:
                out[l].append(el)
                found(l, el)
    transit = []
    for rid, t, mem in routes:
        ways = [way_geom[ref] for ty, ref, role in mem if ty == "w" and ref in way_geom and role in ("", "forward", "backward")]
        stops = [{"lat": node_pos[ref][0], "lon": node_pos[ref][1]} for ty, ref, role in mem if ty == "n" and ref in node_pos
                 and role.startswith(("stop", "platform"))]
        if ways and any(inside(p["lat"], p["lon"]) for g in ways for p in g):
            transit.append({"id": rid, "ref": t.get("ref", ""), "name": t.get("name", ""), "from": t.get("from", ""),
                            "to": t.get("to", ""), "operator": t.get("operator", t.get("network", "")), "ways": ways, "stops": stops,
                            "v": 2})
    out["_transit"] = transit
    st["pass"] = 3
    tick(True)
    return out


def first_point(el):
    if "lat" in el:
        return el["lat"], el["lon"]
    g = el.get("geometry") or next((m.get("geometry") for m in el.get("members", []) if m.get("geometry")), None)
    if g:
        return g[0]["lat"], g[0]["lon"]
    m = next((m for m in el.get("members", []) if "lat" in m), None)
    return (m["lat"], m["lon"]) if m else (None, None)


def routes_only(pbf):
    """Just the bus lines (for transit.json when every map part is already cached)."""
    import osmium
    s_, w_, n_, e_ = bbox()
    routes, need, need_n = [], set(), set()
    for r in osmium.FileProcessor(pbf, osmium.osm.RELATION):
        t = dict(r.tags)
        if t.get("type") == "route" and t.get("route") in ("bus", "trolleybus"):
            mem = [(m.type, m.ref, m.role) for m in r.members]
            routes.append((r.id, t, mem))
            need.update(ref for ty, ref, _ in mem if ty == "w")
            need_n.update(ref for ty, ref, role in mem if ty == "n" and role.startswith(("stop", "platform")))
    geom, pos = {}, {}
    for o in osmium.FileProcessor(pbf, osmium.osm.NODE | osmium.osm.WAY).with_locations():
        if not o.is_way():
            if o.id in need_n and o.location.valid():
                pos[o.id] = {"lat": o.location.lat, "lon": o.location.lon}
            continue
        if o.id in need:
            geom[o.id] = [{"lat": nd.lat, "lon": nd.lon} for nd in o.nodes if nd.location.valid()]
    out = []
    for rid, t, mem in routes:
        ways = [geom[ref] for ty, ref, role in mem if ty == "w" and geom.get(ref) and role in ("", "forward", "backward")]
        if ways and any(s_ <= p["lat"] <= n_ and w_ <= p["lon"] <= e_ for g in ways for p in g):
            out.append({"id": rid, "ref": t.get("ref", ""), "name": t.get("name", ""), "from": t.get("from", ""),
                        "to": t.get("to", ""), "operator": t.get("operator", t.get("network", "")), "ways": ways,
                        "stops": [pos[ref] for ty, ref, role in mem if ty == "n" and ref in pos and role.startswith(("stop", "platform"))],
                        "v": 2})
    return out
