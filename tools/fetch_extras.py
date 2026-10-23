"""Bus lines (transit.json), bus stops (bus_stops.json) and map POIs (map_pois.json) from the cached country file,
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


def main():
    pbf = os.path.join(OSM, "pbf", "country.osm.pbf")
    if not os.path.exists(pbf):
        print("[extras] no country file - skipped")
        return 0
    tj = os.path.join(OSM, "transit.json")
    if not os.path.exists(tj):
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
    if not os.path.exists(os.path.join(OSM, "map_pois.json")):
        import fetch_pois
        fetch_pois.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
