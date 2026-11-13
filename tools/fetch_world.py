"""Download the ready-made world (tools/world_pack.json -> GitHub Release asset) and unpack it to data/cache/world.

Run by the game with the loading screen's progress events.  Resumable (data/cache/world_pack.part), verified by size + sha256,
unpacked next to the target and moved into place only when complete.  Exit 0 ok, 1 failed (the game then builds from OSM).
Needs free disk space for the pack (~1.4 GB) plus the unpacked world (~12 GB).
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from progress import frac, phase  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "cache")
WORLD = os.path.join(CACHE, "world")
PART = os.path.join(CACHE, "world_pack.part")
OSM = os.path.join(ROOT, "data", "osm")


def download(d):
    size = d["size"]
    have = os.path.getsize(PART) if os.path.exists(PART) else 0
    if have > size:
        os.remove(PART)
        have = 0
    phase("downloading the world")
    while have < size:
        req = urllib.request.Request(d["url"], headers={"User-Agent": "skopje-242", "Range": f"bytes={have}-"})
        with urllib.request.urlopen(req, timeout=30) as r:
            if have and r.status != 206:                     # server ignored Range: start again
                have = 0
            with open(PART, "ab" if have else "wb") as out:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
                    have += len(b)
                    frac(0.7 * have / size, f"{have / 1e6:.0f} / {size / 1e6:.0f} MB")
        if have < size and os.path.getsize(PART) == have:
            pass                                             # connection dropped: loop resumes
    h = hashlib.sha256()
    with open(PART, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
            frac(0.7 + 0.05 * f.tell() / size, "checking")
    if os.path.getsize(PART) != size or h.hexdigest() != d["sha256"]:
        os.remove(PART)
        raise RuntimeError("downloaded file is damaged")


def unpack(d):
    tmp = WORLD + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    free = shutil.disk_usage(CACHE).free
    if free < d["unpacked"] + (500 << 20):
        raise RuntimeError(f"not enough disk space: {d['unpacked'] / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free")
    phase("unpacking the world")
    os.makedirs(OSM, exist_ok=True)
    with zipfile.ZipFile(PART) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        for i in infos:
            if ".." in i.filename.split("/") or i.filename.split("/")[0] not in ("world", "osm"):
                raise RuntimeError("unexpected file in pack: " + i.filename)
        tot, done = sum(i.file_size for i in infos), 0
        for i in infos:
            top, rel = i.filename.split("/", 1)
            dest = os.path.join(tmp if top == "world" else OSM, *rel.split("/"))
            with z.open(i) as src, open(dest + ".new", "wb") as out:
                while True:
                    b = src.read(1 << 22)
                    if not b:
                        break
                    out.write(b)
                    done += len(b)
                    frac(0.75 + 0.24 * done / tot, rel)
            os.replace(dest + ".new", dest)
    shutil.rmtree(WORLD, ignore_errors=True)
    os.replace(tmp, WORLD)


def main():
    d = json.load(open(os.path.join(ROOT, "tools", "world_pack.json")))
    os.makedirs(CACHE, exist_ok=True)
    for attempt in range(6):
        try:
            download(d)
            break
        except OSError as e:
            print(f"download interrupted ({e}), retry {attempt + 1}")
    else:
        raise RuntimeError("download failed")
    unpack(d)
    os.remove(PART)
    frac(1.0, "done")
    print("[world pack] installed")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"[world pack] failed: {e}")
        sys.exit(1)
