"""Prints the neighbourhoods found in the downloaded OSM data (names, kind, position) so they can be checked by eye.
Usage:  python tools/check_places.py [data/osm]"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import project

src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "osm")
path = os.path.join(src, "places.json")
if not os.path.exists(path):
    sys.exit(f"{path} not found - run tools/fetch_osm.py first")
els = json.load(open(path, encoding="utf-8"))["elements"]
rows = []
for e in els:
    t = e.get("tags", {})
    if not t.get("name"):
        continue
    kind = t.get("place") or ("admin_level " + t.get("admin_level", "?"))
    if "lat" in e:
        x, y = project(e["lat"], e["lon"])
    elif "bounds" in e:
        b = e["bounds"]
        x, y = project((b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2)
    else:
        continue
    rows.append((kind, t.get("name:en") or t.get("name"), t.get("name"), e["type"], e["id"], round(x), round(y)))
rows.sort()
print(f"{len(rows)} named places in {path}\n")
print(f"{'kind':18} {'name (en)':28} {'local name':28} {'osm':14} x/y (m from centre)")
for kind, en, nm, ty, i, x, y in rows:
    print(f"{kind:18} {en:28} {nm:28} {ty}/{i:<10} {x:6d} {y:6d}")
