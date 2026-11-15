"""How true the photogrammetric heights are: compares the photo-only height of every fitted building that OSM gives a height
(height= or building:levels=) with that height.  Run after a build (or a sample build) to judge a change before a full rebuild.

    python tools/photogram_check.py <capture folder> [data/osm]

Prints the median / mean relative error and the median photo/OSM ratio (1.0 = no bias), all and for buildings that two or more
captures agree on, then the worst buildings (their ids, to look at in the viewer)."""
import json
import os
import statistics as S
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    import photogram as pg
    folder = sys.argv[1]
    osm = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "osm")
    fits = json.load(open(os.path.join(folder, pg.CACHE, "fit_detail.json"), encoding="utf-8"))["buildings"]
    tags = {str(e["id"]): e.get("tags", {}) for e in json.load(open(os.path.join(osm, "buildings.json"), encoding="utf-8"))["elements"]}
    rows = []
    for bid, f in fits.items():
        if f.get("src") != "photo" or "h_photo" not in f or not f.get("conf"):
            continue
        b = type("B", (), {"tags": tags.get(bid, {})})()
        ho = pg._osm_h(b)
        if ho:
            rows.append((abs(f["h_photo"] - ho) / ho, f["h_photo"] / ho, f.get("agree", 0), bid, ho, f["h_photo"], f["h"]))
    if not rows:
        print("no fitted building with an OSM height")
        return
    for name, rs in (("all", rows), ("2+ captures agree", [r for r in rows if r[2] >= 2])):
        if rs:
            print(f"{name:18s} n={len(rs):5d}  median error {100 * S.median(r[0] for r in rs):5.1f} %  mean {100 * S.mean(r[0] for r in rs):5.1f} %"
                  f"  median photo/OSM {S.median(r[1] for r in rs):.2f}")
    print("worst:")
    for r in sorted(rows, reverse=True)[:15]:
        print(f"  {r[3]}: OSM {r[4]:.1f} m, photo {r[5]:.1f} m, game {r[6]:.1f} m, agreeing captures {r[2]}")


if __name__ == "__main__":
    main()
