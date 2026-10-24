"""v2.1 external sound library: writes the artist's request files and indexes the finished library.

Launch: every catalogue sound that has no finished library entry gets a request JSON in `sound_requests/` (format of the
MOSS-SoundEffect batch worker, docs/SOUND_LIBRARY.md).  The artist generates them into `library/`; on the next launch the
game finds `library/**/<id>.json` sidecars and plays those files instead of the procedural sound, per sound."""
import json
import os
import re
import zlib

import soundcat

REQ_DIR, LIB_DIR = "sound_requests", "library"
_VER = re.compile(r"_v(\d+)_seed(\d+)\.mp3$")


def request_id(key, prompt):
    return f"{key}_{zlib.crc32(prompt.encode()) & 0xffffff:06x}"


def base_seed(key):
    return (zlib.crc32(key.encode()) % 9000) * 100          # <= 100 versions per key, never overlapping


def scan(lib_root, prompts=None):
    """-> (usable, fresh, secs): secs = {mp3 path: seconds its request asked for}; usable = key -> mp3 paths of the sidecar to play (one whose prompt equals the current catalogue prompt when there is
    one, else the newest older one); fresh = keys that have a sidecar made from the current prompt.  `prompts` = {key: catalogue prompt};
    without it every sidecar counts as current."""
    found, secs = {}, {}
    for dp, _dn, fns in os.walk(lib_root):
        for fn in fns:
            if not fn.endswith(".json") or fn.startswith("."):
                continue
            try:
                sc = json.load(open(os.path.join(dp, fn), encoding="utf-8"))
                meta = sc.get("meta") if isinstance(sc.get("meta"), dict) else {}
                key = meta.get("key") or re.sub(r"_[0-9a-f]{6}$", "", str(sc["id"]))
                if not isinstance(key, str) or not key:
                    continue
                paths = [os.path.join(dp, os.path.basename(str(f["file"]))) for f in sc["files"] if isinstance(f, dict) and str(f.get("file", "")).lower().endswith(".mp3")]
                paths = sorted(p for p in paths if os.path.isfile(p))
                if paths:
                    cur = prompts is None or sc.get("prompt") == prompts.get(key)
                    found.setdefault(key, []).append((cur, str(sc.get("completed_at", "")), paths))
                    for p in paths:
                        secs[p] = sc.get("seconds")
            except Exception:  # noqa: BLE001
                continue                                          # unreadable / malformed sidecar: that sound just stays procedural
    usable, fresh = {}, set()
    for key, lst in found.items():
        cur = [e for e in lst if e[0]]
        pick = cur if cur else [max(lst, key=lambda e: e[1])]
        if cur:
            fresh.add(key)
        usable[key] = [p for e in pick for p in e[2]]
    return usable, fresh, secs


def write_requests(root, have):
    """Write the missing request files (atomic rename).  Returns (written, total, already_done)."""
    d = os.path.join(root, REQ_DIR)
    os.makedirs(d, exist_ok=True)
    written = done = 0
    for key, folder, loop, secs, n, prompt, lvl, _fb in soundcat.CATALOG:
        if key in have:
            done += 1
            continue
        rid = request_id(key, prompt)
        fn = os.path.join(d, rid + ".json")
        if os.path.exists(fn):
            continue
        req = {"id": rid, "prompt": prompt, "versions": n, "seconds": secs, "output_dir": folder, "seed": base_seed(key), "cfg_scale": 4.0 if loop else 5.0,
               "meta": {"key": key, "category": folder.split("/")[0], "loop": loop, "level": lvl, "game": "skopje242 v2.1"}}
        tmp = fn + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False, indent=1)
        os.replace(tmp, fn)
        written += 1
    return written, len(soundcat.CATALOG), done


class Biomes:
    """Coarse map of what is around the listener (trees, grass, water, built-up) from the world's land-use polygons,
    so birds, ducks and forest ambience come from where they would really be."""
    CELL = 25.0

    def __init__(self, world):
        import numpy as np
        from PIL import Image, ImageDraw
        self.hx, self.hy = world.hx, getattr(world, "hy", world.hx)
        self.nx, self.ny = int(2 * self.hx / self.CELL) + 1, int(2 * self.hy / self.CELL) + 1
        layers = {"tree": ("wood", "scrub"), "park": ("park", "grass", "cemetery", "pitch", "playground"), "water": ("water",), "lake": ("water",),
                  "ind": ("industrial",), "plaza": ("plaza",), "play": ("playground",), "pitch": ("pitch",), "creek": (), "rail": ()}
        self.m = {}
        for nm, kinds in layers.items():
            im = Image.new("L", (self.nx, self.ny), 0)
            dr = ImageDraw.Draw(im)
            for a in world.areas:
                if a["kind"] in kinds:
                    pts = [((x + self.hx) / self.CELL, (y + self.hy) / self.CELL) for x, y in a["outer"]]
                    if len(pts) >= 3:
                        dr.polygon(pts, fill=255)
            lines = [(w["pts"], w["w"]) for w in getattr(world, "wlines", ()) if nm == "water" or (nm == "creek" and w["w"] < 6)]
            if nm == "rail":
                lines = [(r["pts"], 4) for r in getattr(world, "rails", ())]
            for pts, wd in lines:
                pp = [((x + self.hx) / self.CELL, (y + self.hy) / self.CELL) for x, y in pts]
                dr.line(pp, fill=255, width=max(1, int(wd / self.CELL + 1)))
            self.m[nm] = np.asarray(im, dtype=np.float32) / 255.0

    def at(self, x, y, r=3):
        """{'tree','park','water'}: share of cells within r cells (~75 m) of (x, y)."""
        ix, iy = int((x + self.hx) / self.CELL), int((y + self.hy) / self.CELL)
        x0, y0 = max(0, ix - r), max(0, iy - r)
        return {k: float(m[y0:iy + r + 1, x0:ix + r + 1].mean()) if m[y0:iy + r + 1, x0:ix + r + 1].size else 0.0 for k, m in self.m.items()}

    def find(self, x, y, layer, rng, rmax=70.0, tries=12):
        """A random point of `layer` within rmax of (x, y), or None."""
        import math
        m = self.m[layer]
        for _ in range(tries):
            a, d = rng.uniform(0, 6.283), rmax * math.sqrt(rng.random())
            px, py = x + d * math.cos(a), y + d * math.sin(a)
            ix, iy = int((px + self.hx) / self.CELL), int((py + self.hy) / self.CELL)
            if 0 <= ix < self.nx and 0 <= iy < self.ny and m[iy, ix] > 0.5:
                return px, py
        return None
