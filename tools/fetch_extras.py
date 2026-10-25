"""Bus lines (transit.json), bus stops (bus_stops.json), railway (rail.json), traffic signals (signals.json) and map POIs (map_pois.json) from the cached country file,
when any is missing.
Run by the game at start; needs no network and takes ~15-40 s once."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSM = os.environ.get("SK242_OSM_DIR") or os.path.join(ROOT, "data", "osm")


def bus_stops(pbf):
    """Every bus stop / platform node in the map box -> [[x, y, name], ...] in game metres (a plain list, so the world
    build's OSM reader skips this file)."""
    import osmium
    from geo import bbox, project
    s_, w_, n_, e_ = bbox()
    out = []
    for o in osmium.FileProcessor(pbf, osmium.osm.NODE):
        t = o.tags
        if t.get("highway") == "bus_stop" or (t.get("public_transport") == "platform" and t.get("bus") == "yes"):
            if o.location.valid() and s_ <= o.location.lat <= n_ and w_ <= o.location.lon <= e_:
                x, y = project(o.location.lat, o.location.lon)
                out.append([round(x, 1), round(y, 1), t.get("name", "")])
    return out


def signal_nodes(pbf):
    """Every highway=traffic_signals node in the map box -> [[x, y], ...] in game metres."""
    import osmium
    from geo import bbox, project
    s_, w_, n_, e_ = bbox()
    out = []
    for o in osmium.FileProcessor(pbf, osmium.osm.NODE):
        if o.tags.get("highway") == "traffic_signals" and o.location.valid() and s_ <= o.location.lat <= n_ and w_ <= o.location.lon <= e_:
            x, y = project(o.location.lat, o.location.lon)
            out.append([round(x, 1), round(y, 1)])
    return out


def rail_data(pbf):
    """Railway lines (rail / disused / platform ways with bridge, tunnel, layer) and stations, halts and level crossings in
    the map box -> [["way", kind, bridge, tunnel, [[x, y], ...]], ["node", kind, x, y, name], ...] in game metres (a plain
    list, so the world build's OSM reader skips this file)."""
    import osmium
    from geo import bbox, project
    s_, w_, n_, e_ = bbox()
    out = []

    class H(osmium.SimpleHandler):
        def node(self, n):
            t = n.tags
            k = t.get("railway")
            if k in ("station", "halt", "level_crossing", "crossing") and s_ <= n.location.lat <= n_ and w_ <= n.location.lon <= e_:
                x, y = project(n.location.lat, n.location.lon)
                out.append(["node", k, round(x, 1), round(y, 1), t.get("name", "")])

        def way(self, w):
            t = w.tags
            k = t.get("railway")
            if k not in ("rail", "disused", "platform"):
                return
            pts = [project(q.lat, q.lon) for q in w.nodes if q.location.valid()]
            if any(s_ <= q.lat <= n_ and w_ <= q.lon <= e_ for q in w.nodes if q.location.valid()):
                out.append(["way", k, t.get("bridge", "no") != "no", t.get("tunnel", "no") != "no", [[round(a, 1), round(b, 1)] for a, b in pts]])

    H().apply_file(pbf, locations=True)
    return out


def current_transit(tj):
    """transit.json exists and carries every line's own stops (v 2); older files are read again from the country file."""
    try:
        with open(tj, encoding="utf-8") as f:
            recs = json.load(f)
    except (OSError, ValueError):
        return False
    return not recs or recs[0].get("v") == 2


def main():
    pbf = os.path.join(OSM, "pbf", "country.osm.pbf")
    if not os.path.exists(pbf):
        print("[extras] no country file - skipped")
        return 0
    tj = os.path.join(OSM, "transit.json")
    if not current_transit(tj):
        import fetch_pbf
        tr = fetch_pbf.routes_only(pbf)
        with open(tj + ".tmp", "w", encoding="utf-8") as f:
            json.dump(tr, f)
        os.replace(tj + ".tmp", tj)
        print(f"[extras] bus lines: {len(tr)}")
    bs = os.path.join(OSM, "bus_stops.json")
    if not os.path.exists(bs):
        st = bus_stops(pbf)
        with open(bs + ".tmp", "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(bs + ".tmp", bs)
        print(f"[extras] bus stops: {len(st)}")
    rj = os.path.join(OSM, "rail.json")
    if not os.path.exists(rj):
        rl = rail_data(pbf)
        with open(rj + ".tmp", "w", encoding="utf-8") as f:
            json.dump(rl, f, ensure_ascii=False)
        os.replace(rj + ".tmp", rj)
        print(f"[extras] railway: {sum(1 for r in rl if r[0] == 'way')} ways, {sum(1 for r in rl if r[0] == 'node')} stations / crossings")
    sj = os.path.join(OSM, "signals.json")
    if not os.path.exists(sj):
        sl = signal_nodes(pbf)
        with open(sj + ".tmp", "w", encoding="utf-8") as f:
            json.dump(sl, f)
        os.replace(sj + ".tmp", sj)
        print(f"[extras] traffic signals: {len(sl)}")
    if not os.path.exists(os.path.join(OSM, "map_pois.json")):
        import fetch_pois
        fetch_pois.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
