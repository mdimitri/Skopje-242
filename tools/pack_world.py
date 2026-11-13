"""Pack the built world into ONE file for players: dist/skopje242-world.zip  (publish it as a GitHub Release asset, tag world-pack).

    python tools/pack_world.py [--world data/cache/world] [--osm data/osm] [--out dist/skopje242-world.zip]

Contents: world/ (manifest.json + every file the manifest lists, nothing else: no overview cache, no stage cache) and the three
small data/osm files the game reads while playing (osm/transit.json, map_pois.json, map_poi_kinds.json), plus world/pack.json.
Never packed: text/, settings, saves, photos, photogram.json (it is baked into the world already).
Writes tools/world_pack.json (url, size, sha256): the game reads it to download and verify the pack.
"""
import argparse
import hashlib
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSM_FILES = ("transit.json", "map_pois.json", "map_poi_kinds.json")
URL = "https://github.com/mdimitri/skopje-242/releases/download/world-pack/skopje242-world.zip"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default=os.path.join(ROOT, "data", "cache", "world"))
    ap.add_argument("--osm", default=os.path.join(ROOT, "data", "osm"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "skopje242-world.zip"))
    a = ap.parse_args()
    man = json.load(open(os.path.join(a.world, "manifest.json")))
    for fn, size in man["sizes"].items():
        if os.path.getsize(os.path.join(a.world, fn)) != size:
            sys.exit(f"{fn}: wrong size, the world is incomplete")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    total = sum(man["sizes"].values())
    done = 0
    with zipfile.ZipFile(a.out + ".tmp", "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        z.writestr("world/pack.json", json.dumps({"format": 1, "world_version": man["version"]}))
        for fn in ["manifest.json"] + list(man["sizes"]):
            z.write(os.path.join(a.world, fn), "world/" + fn)
            done += os.path.getsize(os.path.join(a.world, fn))
            print(f"\r{done / total * 100:5.1f}%  {fn}".ljust(60), end="", flush=True)
        for fn in OSM_FILES:
            z.write(os.path.join(a.osm, fn), "osm/" + fn)
    os.replace(a.out + ".tmp", a.out)
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    size = os.path.getsize(a.out)
    d = {"url": URL, "size": size, "sha256": h.hexdigest(), "world_version": man["version"], "unpacked": total}
    json.dump(d, open(os.path.join(ROOT, "tools", "world_pack.json"), "w"), indent=1)
    print(f"\n{a.out}: {size / 1e9:.3f} GB ({size / 2**30:.3f} GiB; GitHub's limit is 2 GiB), unpacks to {total / 1e9:.2f} GB\nsha256 {d['sha256']}")


if __name__ == "__main__":
    main()
