"""Points of interest for the map: shops, cafés, kafanas, schools, churches, mosques, pharmacies, petrol stations,
markets, monuments ... read from the cached Geofabrik country file (no extra download), written to
data/osm/map_pois.json as [[x, y, category, name], ...] in game metres."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import bbox, project  # noqa: E402

CATS = {  # tag value -> map category
    "amenity": {"cafe": "cafe", "bar": "cafe", "pub": "cafe", "restaurant": "food", "fast_food": "food",
                "school": "school", "university": "school", "college": "school", "kindergarten": "school",
                "pharmacy": "health", "hospital": "health", "clinic": "health", "doctors": "health", "dentist": "health",
                "place_of_worship": "worship", "fuel": "fuel", "bank": "money", "atm": "money", "marketplace": "market",
                "police": "police", "post_office": "public", "townhall": "public", "library": "public",
                "theatre": "culture", "cinema": "culture", "arts_centre": "culture", "nightclub": "night",
                "bus_station": "transport", "parking": None, "bench": None, "waste_basket": None},
    "shop": {"*": "shop"},
    "tourism": {"museum": "culture", "hotel": "hotel", "hostel": "hotel", "attraction": "sight", "viewpoint": "sight",
                "artwork": "sight", "gallery": "culture"},
    "historic": {"*": "sight"},
    "leisure": {"sports_centre": "sport", "stadium": "sport", "fitness_centre": "sport", "playground": "play"},
}


def cat_of(t):
    for k, m in CATS.items():
        v = t.get(k)
        if v:
            c = m.get(v, m.get("*"))
            if c:
                return c
    return None


def sub_of(t):
    """OSM sub-tag that tells the vendor type (shop=bakery -> "bakery", amenity=fast_food + cuisine=kebab -> "fast_food/kebab")."""
    for k in ("shop", "amenity", "tourism", "leisure"):
        v = t.get(k)
        if v:
            cu = (t.get("cuisine") or "").split(";")[0]
            return f"{v}/{cu}" if cu and k == "amenity" else v
    return ""


def main():
    import osmium
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    osm = os.environ.get("SK242_OSM_DIR") or os.path.join(root, "data", "osm")
    pbf = os.path.join(osm, "pbf", "country.osm.pbf")
    out = os.path.join(osm, "map_pois.json")
    if not os.path.exists(pbf):
        print("[poi] no country file (Overpass route) - no map POIs")
        return 0
    s_, w_, n_, e_ = bbox()
    res = []
    subs = {}                                       # "x,y" -> OSM sub-tag for the vendor menus (poi_vendors.py)

    class H(osmium.SimpleHandler):
        def node(self, n):
            if len(n.tags) and n.location.valid() and s_ <= n.location.lat <= n_ and w_ <= n.location.lon <= e_:
                t = dict(n.tags)
                c = cat_of(t)
                if c:
                    x, y = project(n.location.lat, n.location.lon)
                    res.append([round(x, 1), round(y, 1), c, t.get("name", "")[:40]])
                    subs[f"{round(x, 1)},{round(y, 1)}"] = sub_of(t)

        def area(self, a):
            t = dict(a.tags)
            c = cat_of(t)
            if not c:
                return
            try:
                ring = next(iter(a.outer_rings()))
                pts = [(p.lat, p.lon) for p in ring if p.location.valid()]
            except (StopIteration, Exception):  # noqa: BLE001
                return
            if not pts:
                return
            lat = sum(p[0] for p in pts) / len(pts)
            lon = sum(p[1] for p in pts) / len(pts)
            if s_ <= lat <= n_ and w_ <= lon <= e_:
                x, y = project(lat, lon)
                res.append([round(x, 1), round(y, 1), c, t.get("name", "")[:40]])
                subs[f"{round(x, 1)},{round(y, 1)}"] = sub_of(t)

    H().apply_file(pbf, locations=True)
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    os.replace(out + ".tmp", out)
    with open(os.path.join(osm, "map_poi_kinds.json"), "w", encoding="utf-8") as f:
        json.dump(subs, f, ensure_ascii=False)
    print(f"[poi] {len(res)} points of interest -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
