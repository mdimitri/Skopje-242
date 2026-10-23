"""Download elevation data for the world box and resample it to the 10 m terrain grid (data/osm/terrain.npy).

Source: the open "Terrarium" elevation tiles (Mapzen / AWS open data, built from SRTM and national DEMs).
If the download fails the game still builds - with flat terrain - and says so.
"""
import argparse
import io
import math
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import HX, HY, LAT0, LON0, M_LAT, M_LON, project
import net
import terrain

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "osm", "terrain.npy")
URLS = ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
        "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"]
Z = 13


def tile_xy(lat, lon, z):
    n = 2.0 ** z
    x = (np.asarray(lon, float) + 180.0) / 360.0 * n
    y = (1.0 - np.arcsinh(np.tan(np.radians(np.asarray(lat, float)))) / math.pi) / 2.0 * n
    return x, y


def tile_rect(z, x, y):
    """Local-metre rectangle [x0, y0, x1, y1] covered by a tile (for the progress map)."""
    n = 2.0 ** z
    lon0, lon1 = x / n * 360.0 - 180.0, (x + 1) / n * 360.0 - 180.0
    lat0 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat1 = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    ax, ay = project(lat0, lon0)
    bx, by = project(lat1, lon1)
    return [round(min(ax, bx)), round(min(ay, by)), round(max(ax, bx)), round(max(ay, by))]


def get_tile(z, x, y, mirrors, cache_dir):
    """One elevation tile: from the cache, else downloaded (mirrors rotated, bounded retries) and cached."""
    uid = f"dem:{x}:{y}"
    cp = os.path.join(cache_dir, f"{z}_{x}_{y}.npy")
    try:
        if os.path.exists(cp):
            a = np.load(cp)
            if a.shape == (256, 256):
                net.emit("cell", id=uid, state="done", cached=1)
                return a
    except Exception:  # noqa: BLE001 - corrupt cache file: fetch again
        pass
    net.emit("cell", id=uid, state="active")
    last = None
    for attempt in range(1, 7):
        u = mirrors.pick()
        try:
            raw = net.fetch(u.format(z=z, x=x, y=y), uid, first_byte=45, stall=15)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
            a = np.asarray(im, dtype=np.float32)
            if a.shape[:2] != (256, 256):
                raise net.Fail("bad", f"tile size {a.shape}")
            h = a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0
            mirrors.good(u, 1)
            np.save(cp + ".tmp.npy", h)
            os.replace(cp + ".tmp.npy", cp)
            net.emit("cell", id=uid, state="done")
            return h
        except net.Fail as f:
            last = f
        except Exception as e:  # noqa: BLE001 - not an image
            last = net.Fail("bad", str(e))
        mirrors.bad(u, last)
        net.emit("warn", id=uid, kind=last.kind, mirror=net.host(u), attempt=attempt, msg=last.msg[:90])
        if attempt >= 3 and mirrors.exhausted():
            break
        net.sleep_visible(min(20, 3 * attempt + last.retry_after), uid, last.kind)
    net.emit("cell", id=uid, state="fail", kind=last.kind if last else "net")
    raise RuntimeError(f"tile {z}/{x}/{y}: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if os.path.exists(OUT) and not a.force:
        print("[terrain] cached")
        return 0
    ny, nx = terrain.grid_shape(HX, HY)
    xs = np.linspace(-HX, HX, nx)
    ys = np.linspace(-HY, HY, ny)
    lon = LON0 + xs / M_LON
    lat = LAT0 - ys / M_LAT
    tx0, ty0 = tile_xy(lat.max(), lon.min(), Z)
    tx1, ty1 = tile_xy(lat.min(), lon.max(), Z)
    t_x0, t_x1, t_y0, t_y1 = int(tx0), int(tx1), int(ty0), int(ty1)
    if t_x1 < t_x0 or t_y1 < t_y0:
        t_x0, t_x1 = int(min(tx0, tx1)), int(max(tx0, tx1))
        t_y0, t_y1 = int(min(ty0, ty1)), int(max(ty0, ty1))
    ntiles = (t_x1 - t_x0 + 1) * (t_y1 - t_y0 + 1)
    cache_dir = os.path.join(os.path.dirname(OUT), "terrain_tiles")
    os.makedirs(cache_dir, exist_ok=True)
    mirrors = net.Mirrors(os.environ.get("SK242_DEM", "").split(",") if os.environ.get("SK242_DEM") else URLS)
    net.emit("plan", what="dem", cells=[{"id": f"dem:{x}:{y}", "layer": "dem", "r": tile_rect(Z, x, y)}
                                        for y in range(t_y0, t_y1 + 1) for x in range(t_x0, t_x1 + 1)])
    mosaic = np.zeros(((t_y1 - t_y0 + 1) * 256, (t_x1 - t_x0 + 1) * 256), np.float32)
    k = 0
    try:
        for ty in range(t_y0, t_y1 + 1):
            for tx in range(t_x0, t_x1 + 1):
                mosaic[(ty - t_y0) * 256:(ty - t_y0 + 1) * 256, (tx - t_x0) * 256:(tx - t_x0 + 1) * 256] = get_tile(Z, tx, ty, mirrors, cache_dir)
                k += 1
    except Exception as e:  # noqa: BLE001
        print("[terrain] FAILED:", e)
        print("[terrain] WARNING: no elevation data - the city will be flat. Re-run tools/fetch_terrain.py later.")
        return 1
    net.emit("done", what="dem")
    # sample the mosaic at every grid post (bilinear)
    fx = np.empty((ny, nx))
    fy = np.empty((ny, nx))
    px, _ = tile_xy(np.full(nx, LAT0), lon, Z)
    _, py = tile_xy(lat, np.full(ny, LON0), Z)
    fx = (px - t_x0) * 256.0
    fy = (py - t_y0) * 256.0
    ix = np.clip(np.floor(fx).astype(int), 0, mosaic.shape[1] - 2)
    iy = np.clip(np.floor(fy).astype(int), 0, mosaic.shape[0] - 2)
    tx_ = (fx - ix)[None, :]
    ty_ = (fy - iy)[:, None]
    g00 = mosaic[iy][:, ix]
    g01 = mosaic[iy][:, ix + 1]
    g10 = mosaic[iy + 1][:, ix]
    g11 = mosaic[iy + 1][:, ix + 1]
    g = (g00 * (1 - tx_) + g01 * tx_) * (1 - ty_) + (g10 * (1 - tx_) + g11 * tx_) * ty_
    # light smoothing: the source is ~14-30 m resolution, a 3x3 blur removes pixel stepping on slopes
    p = np.pad(g, 1, mode="edge")
    g = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 4 * p[1:-1, 1:-1]) / 8.0
    ref = float(g[ny // 2, nx // 2])
    print(f"[terrain] centre elevation {ref:.0f} m; range {g.min() - ref:+.0f} .. {g.max() - ref:+.0f} m relative to it")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.save(OUT + ".tmp.npy", (g - ref).astype(np.float32))
    os.replace(OUT + ".tmp.npy", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
