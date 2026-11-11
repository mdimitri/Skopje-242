"""Photogrammetric building fit: a folder of street-level captures (images + manifest.csv with position / heading / pitch / fov)
guides the procedural look of the buildings they show.

Nothing from the photos reaches the game: every building gets a few numbers (height, facade material, wall tint, floor height,
window-bay width) that tools/build_world.py uses instead of its random pick when <osm>/photogram.json exists.

Pipeline (Job, in a thread; the viewer in src/photoview.py redraws after every step):
  1. manifest -> Capture (the pano position / pose from the Google URL when the row has one)
  2. the buildings around the captures, with the look the world build gives them (build_world.bld_style)
  3. per capture: labels (segment.py: building / sky / vegetation / vehicle / ground) + the screenshot's UI boxes masked
  4. per visible facade: the photo resampled onto the wall plane (RES px per metre), minus other buildings in front
  5. per building: one of ALGOS fits the numbers from all its facade views
  6. buildings nobody photographed borrow from fitted neighbours of the same kind ("inferred")
"""
import csv
import json
import math
import os
import random
import re
import sys
import threading
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EYE = 2.5                      # Street View camera height above the ground (m)
RES = 4.0                      # facade resampling: pixels per metre
VMAX = 90.0                    # highest facade point sampled (m)
NEAR = 320.0                   # buildings this close to a capture are loaded (and may be inferred)
CACHE = "_photogram"           # work folder inside the photo folder (labels, fits); never part of the game
# facade materials of the world build (build_world.MAT_*) -> texture names of gl3d.build_textures
MATS = {0: "A", 1: "B", 4: "panel", 5: "house", 7: "brick", 8: "conc", 9: "concg", 10: "cream", 11: "mix"}
SUN = np.array([-0.45, 0.80, -0.40]) / np.linalg.norm([-0.45, 0.80, -0.40])
# label ids (segment.py)
L_OTHER, L_BUILDING, L_SKY, L_VEG, L_VEHICLE, L_GROUND, L_NONE = 0, 1, 2, 3, 4, 5, 255
ALGOS = [
    ("colour", "БОЈА + ВИСИНА", "висина од силуетата, боја на ѕидот; фасадата останува"),
    ("grid", "РЕШЕТКА", "+ катови и прозорци од периодичноста, фасада по сличност"),
    ("render", "РЕНДЕР-СПОРЕДИ", "+ дотерување на камерата, фасада/катови/прозорци по најмала разлика"),
    ("detail", "ДЕТАЛИ", "плочки од фотографиите по колона, кровови, клими и балкони во 3D"),
]
URL_POSE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+),(?:[\d.]+a,)?([\d.]+)y,([\d.]+)h,([\d.]+)t")
# boxes of the Google Maps page around the picture (fractions of the screenshot): search box + place card, top icons, minimap,
# zoom / compass buttons, attribution strip
UI_BOXES = [(0.0, 0.0, 0.25, 0.25), (0.29, 0.0, 0.35, 0.08), (0.87, 0.0, 1.0, 0.09), (0.0, 0.84, 0.16, 1.0),
            (0.94, 0.78, 1.0, 1.0), (0.44, 0.94, 1.0, 1.0)]

_T = {}


def tools():
    """tools/build_world.py (bld_style, walls, polygons_of, terrain) without leaving tools/ modules shadowing the game's own
    (both folders have geo.py and stations.py)."""
    if "bw" not in _T:
        tdir = os.path.join(ROOT, "tools")
        saved = {m: sys.modules.pop(m) for m in ("geo", "stations", "terrain") if m in sys.modules}
        before = set(sys.modules)
        sys.path.insert(0, tdir)
        try:
            import build_world
            _T["bw"] = build_world
            _T["terrain"] = build_world.terrain_mod
        finally:
            while tdir in sys.path:
                sys.path.remove(tdir)
            for m in set(sys.modules) - before:
                sys.modules.pop(m, None)
            sys.modules.update(saved)
    return _T["bw"]


def project(lat, lon):
    import geo
    return geo.project(lat, lon)


# ------------------------------------------------------------------------------------------------------------ captures
class Capture:
    """One image and the camera it was taken with.  Pose angles in degrees: yaw from north clockwise, pitch up > 0, fov vertical."""

    def __init__(self, row, folder):
        self.idx = row.get("idx", "")
        self.file = row["file"]
        self.path = os.path.join(folder, self.file)
        try:
            self.bid = int(float(row.get("osm_building_id") or 0))
        except ValueError:
            self.bid = 0
        lat, lon = float(row["lat"]), float(row["lon"])
        self.yaw, self.pitch, self.fov = float(row["heading"]), float(row["pitch"]), float(row["fov"])
        m = URL_POSE.search(row.get("final_url") or "")
        if (row.get("pano_lat") or "").strip():
            lat, lon = float(row["pano_lat"]), float(row["pano_lng"])
        elif m:                                         # where the pano really is (a few metres from the asked-for point)
            lat, lon = float(m.group(1)), float(m.group(2))
            self.fov, self.yaw, self.pitch = float(m.group(3)), float(m.group(4)), float(m.group(5)) - 90.0
        self.screenshot = "google." in (row.get("final_url") or "")
        self.x, self.z = project(lat, lon)
        self.y = 0.0                                    # eye height, set from the terrain
        self.dyaw = self.dpitch = 0.0                   # refinement found by the "render" algorithm
        self.W = self.H = 0
        self.exists = os.path.exists(self.path)
        if self.exists:
            try:
                with Image.open(self.path) as im:
                    self.W, self.H = im.size
            except OSError:
                self.exists = False
        self.status = ""                                # what the builder made of it (viewer)

    def basis(self, refined=True):
        y = math.radians(self.yaw + (self.dyaw if refined else 0.0))
        p = math.radians(self.pitch + (self.dpitch if refined else 0.0))
        fwd = np.array([math.sin(y) * math.cos(p), math.sin(p), -math.cos(y) * math.cos(p)])
        right = np.array([math.cos(y), 0.0, math.sin(y)])
        up = np.cross(right, fwd)
        return fwd, right, up

    def focal(self):
        """Pixels per unit of tan: Google's fov ('90y' in the URL) is the VERTICAL one (checked against the footprints)."""
        return 0.5 * self.H / math.tan(math.radians(self.fov) / 2)

    def eye(self):
        return np.array([self.x, self.y, self.z])

    def project(self, P, refined=True):
        """World points (..., 3) -> pixel u, v and depth (along the view direction)."""
        fwd, right, up = self.basis(refined)
        d = np.asarray(P, np.float64) - self.eye()
        zc = d @ fwd
        zs = np.where(zc > 1e-3, zc, 1e-3)
        f = self.focal()
        return self.W / 2 + f * (d @ right) / zs, self.H / 2 - f * (d @ up) / zs, zc

    def image(self):
        return np.asarray(Image.open(self.path).convert("RGB"))

    def ui_mask(self):
        """True where the screenshot shows the map page instead of the street."""
        m = np.zeros((self.H, self.W), bool)
        if self.screenshot:
            for x0, y0, x1, y1 in UI_BOXES:
                m[int(y0 * self.H):int(math.ceil(y1 * self.H)), int(x0 * self.W):int(math.ceil(x1 * self.W))] = True
        return m


def read_manifest(folder):
    """manifest.csv (or any *.csv with a 'file' column) -> [Capture]."""
    names = ["manifest.csv"] + sorted(f for f in os.listdir(folder) if f.lower().endswith((".csv", ".csf")) and f != "manifest.csv")
    for n in names:
        p = os.path.join(folder, n)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows and "file" in rows[0]:
            caps = [Capture(r, folder) for r in rows]
            return sorted(caps, key=lambda c: c.file)
    raise FileNotFoundError(f"no manifest.csv in {folder}")


# ------------------------------------------------------------------------------------------------------------ buildings
class Bld:
    def __init__(self, bid, tags, ring, holes, base):
        self.id = bid
        self.tags = tags
        self.ring = np.asarray(ring, np.float64)       # (n, 2) x east, z south; positive shoelace (the world build's winding)
        self.holes = holes
        self.base = base                                # ground height under it (mean of the terrain at the corners)
        self.area = abs(tools().shoelace(ring))
        self.c = self.ring.mean(0)
        r = random.Random(bid)
        h, roofc, wallc, mat, small = tools().bld_style(tags, self.area, ring, r)
        self.gen = {"h": h, "mat": mat, "wallc": list(wallc), "roofc": list(roofc), "floor": 3.2, "bay": 3.4, "small": small}
        self.fits = {}                                  # algo -> fitted dict (with "src": "photo" | "inferred", "conf")
        self.obs = []                                   # facade views (Obs)
        self.version = 0

    def look(self, algo=None):
        """The look to show / write: the fit of `algo` over the generated one (None = generated)."""
        d = dict(self.gen)
        if algo and algo in self.fits:
            d.update(self.fits[algo])
        return d

    def kind(self):
        b = self.tags.get("building", "yes")
        return "house" if b in ("house", "detached", "semidetached_house", "terrace", "bungalow") else \
            "flats" if b in ("apartments", "residential", "dormitory") else "other"

    def walls(self):
        """[(a, b, outward normal, length)] of the outer ring."""
        out = []
        r = self.ring
        for i in range(len(r)):
            a, b = r[i], r[(i + 1) % len(r)]
            d = b - a
            ln = float(np.hypot(*d))
            if ln < 1.0:
                continue
            out.append((a, b, np.array([d[1] / ln, -d[0] / ln]), ln))
        return out


def load_city(osm_dir, caps, log=print):
    """The buildings within NEAR of any capture -> {id: Bld}; the eye height of every capture."""
    bw = tools()
    import geo
    tfile = os.path.join(osm_dir, "terrain.npy")
    try:
        T = bw.terrain_mod.load(tfile, geo.HX, geo.HY)
    except Exception as e:  # noqa: BLE001 - flat ground is still usable
        log(f"терен: нема ({e}), рамно")
        T = bw.terrain_mod.flat(geo.HX, geo.HY)
    for c in caps:
        c.y = float(T.hs(c.x, c.z)) + EYE
    pts = np.array([(c.x, c.z) for c in caps]) if caps else np.zeros((0, 2))
    els = json.load(open(os.path.join(osm_dir, "buildings.json"), encoding="utf-8"))["elements"]
    blds = {}
    for el in els:
        t = el.get("tags", {})
        if "building" not in t or t.get("building") == "no":
            continue
        g = el.get("geometry") or [p for m in el.get("members", []) for p in (m.get("geometry") or [])]
        if not g:
            continue
        lat0, lon0 = g[0]["lat"], g[0]["lon"]
        x0, z0 = project(lat0, lon0)
        if not len(pts) or np.min(np.hypot(pts[:, 0] - x0, pts[:, 1] - z0)) > NEAR + 150:
            continue
        try:
            polys = bw.polygons_of(el)
        except Exception:  # noqa: BLE001
            continue
        for p_i, (outer, holes) in enumerate(polys[:1]):
            if len(outer) < 3 or abs(bw.shoelace(outer)) < 8:
                continue
            if bw.shoelace(outer) < 0:
                outer = outer[::-1]
            ring = np.asarray(outer, np.float64)
            if np.min(np.hypot(pts[:, 0] - ring[:, 0].mean(), pts[:, 1] - ring[:, 1].mean())) > NEAR:
                continue
            base = float(np.mean(T.h(ring[:, 0], ring[:, 1])))
            blds[el["id"]] = Bld(el["id"], t, outer, holes, base)
    log(f"згради околу снимките: {len(blds)}")
    return blds


# ------------------------------------------------------------------------------------------------------------ facades
class Obs:
    """One wall of one building as one capture sees it, resampled onto the wall plane: row k = height (k + .5) / RES above the
    base, column j = (j + .5) / RES metres along the wall from its first corner."""

    def __init__(self, cap, bld, wi, a, b, nrm, ln, rgb, lab, ok, occ_thr):
        self.cap, self.bld, self.wi = cap, bld, wi
        self.a, self.b, self.nrm, self.ln = a, b, nrm, ln
        self.rgb, self.lab, self.ok = rgb, lab, ok
        self.occ_thr = occ_thr
        n3 = np.array([nrm[0], 0.0, nrm[1]])
        self.shade = float(np.clip(0.52 + 0.55 * max(0.0, float(n3 @ SUN)), 0.45, 1.12))
        self.n_build = int(((lab == L_BUILDING) & ok).sum())


def wall_edges(blds, near_xz, radius):
    """All wall segments within `radius` of a point -> (E0 (M,2), E1 (M,2), top (M,), base (M,), owner ids, wall index)."""
    E0, E1, top, base, own, wix = [], [], [], [], [], []
    for b in blds.values():
        if np.hypot(*(b.c - near_xz)) > radius:
            continue
        h = max(b.gen["h"], b.look("render").get("h", 0) if b.fits else 0)
        r = b.ring
        for i in range(len(r)):
            E0.append(r[i]); E1.append(r[(i + 1) % len(r)])
            top.append(b.base + h); base.append(b.base); own.append(b.id); wix.append(i)
    if not E0:
        z = np.zeros((0, 2))
        return z, z, np.zeros(0), np.zeros(0), np.zeros(0, np.int64), np.zeros(0, np.int64)
    return np.array(E0), np.array(E1), np.array(top), np.array(base), np.array(own, np.int64), np.array(wix, np.int64)


def facade_views(cap, img, lab, ui, blds, edges, only=None, min_px=1500):
    """Every wall the capture sees -> [Obs] (only walls of `only` ids when given, and only views with >= min_px building pixels)."""
    E0, E1, etop, _ebase, eown, ewix = edges
    eye = cap.eye()
    out = []
    H, W = lab.shape
    for b in blds.values():
        if only is not None and b.id not in only:
            continue
        if np.hypot(*(b.c - eye[[0, 2]])) > 200:
            continue
        for wi, (a, bb, nrm, ln) in enumerate(b.walls()):
            mid = (a + bb) / 2
            to_cam = eye[[0, 2]] - mid
            if to_cam @ nrm <= 0.5:                      # faces away (or edge-on)
                continue
            nu = max(2, int(ln * RES))
            hh = max(b.gen["h"], getattr(b, "h_seen", 0.0))
            nv = int(min(VMAX, max(hh * 1.8, hh + 12)) * RES)
            us = (np.arange(nu) + 0.5) / RES
            vs = (np.arange(nv) + 0.5) / RES
            xz = a[None, :] + (bb - a)[None, :] * (us / ln)[:, None]               # (nu, 2)
            # quick reject: corners outside the view
            P = np.zeros((nv, nu, 3))
            P[:, :, 0] = xz[None, :, 0]
            P[:, :, 2] = xz[None, :, 1]
            P[:, :, 1] = b.base + vs[:, None]
            u, v, zc = cap.project(P)
            inimg = (zc > 1.0) & (u >= 0) & (u < W - 1) & (v >= 0) & (v < H - 1)
            if inimg.sum() < 200:
                continue
            # other walls between the camera and each column: rows below the threshold height are hidden
            thr = np.full(nu, -1.0)
            if len(E0):
                C = eye[[0, 2]]
                dq = xz - C                                                          # (nu, 2)
                e = E1 - E0                                                          # (M, 2)
                den = dq[:, None, 0] * e[None, :, 1] - dq[:, None, 1] * e[None, :, 0]
                w0 = E0[None, :, :] - C[None, None, :]
                with np.errstate(divide="ignore", invalid="ignore"):
                    t = (w0[..., 0] * e[None, :, 1] - w0[..., 1] * e[None, :, 0]) / den
                    s = (w0[..., 0] * dq[:, None, 1] - w0[..., 1] * dq[:, None, 0]) / den
                self_edge = (eown == b.id) & (ewix == wi)
                hit = (np.abs(den) > 1e-9) & (t > 0.02) & (t < 0.985) & (s >= 0) & (s <= 1) & ~self_edge[None, :]
                lim = np.where(hit, eye[1] + (etop[None, :] - eye[1]) / np.where(hit, t, 1.0), -1e9)
                thr = lim.max(1) - b.base
            occluded = vs[:, None] < thr[None, :]
            ui_ = np.ones_like(inimg)
            ui_[inimg] = ui[v[inimg].astype(int), u[inimg].astype(int)]
            ok = inimg & ~occluded & ~ui_
            rgb = np.zeros((nv, nu, 3), np.float32)
            lb = np.full((nv, nu), L_NONE, np.uint8)
            iu, iv = u[ok].astype(int), v[ok].astype(int)
            rgb[ok] = img[iv, iu]
            lb[ok] = lab[iv, iu]
            o = Obs(cap, b, wi, a, bb, nrm, ln, rgb, lb, ok, thr)
            if o.n_build >= min_px:
                out.append(o)
    return out


# ------------------------------------------------------------------------------------------------------------ fitting
def _osm_h(b):
    """The height OSM states (height= or building:levels=), or None."""
    t = b.tags
    for k, f in (("height", 1.0), ("building:levels", 3.1)):
        try:
            v = float(str(t.get(k, "")).split(";")[-1].replace("m", "").replace(",", ".").strip())
            return v * f + (1.0 if k == "building:levels" else 0.0)
        except ValueError:
            continue
    return None


def fit_height(obs, h0):
    """Roof line from the building -> sky change in every column -> (height, confidence 0..1).
    Robust to: a taller building behind (no sky above = no vote), trees over the roof (vegetation, not sky = no vote), a cut-off
    top (only a lower bound), single wrong columns (inter-quartile trim), views that disagree (median of per-view medians)."""
    per_view, lows = [], []
    for o in obs:
        lab, ok = o.lab, o.ok
        nv = lab.shape[0]
        isb = (lab == L_BUILDING) & ok
        issky = (lab == L_SKY) & ok
        tops = []
        for j in np.nonzero(isb.any(0))[0]:
            rows = np.nonzero(isb[:, j])[0]
            if rows[0] > max(6.0, 0.5 * h0) * RES:         # no facade low down in this column: a building behind, not this one
                continue
            top = rows[-1]
            above = np.nonzero(issky[top + 1:min(nv, top + 1 + int(2.0 * RES)), j])[0]
            if len(above):
                tops.append((top + 1) / RES)
            elif not ok[top + 1:, j].any():
                lows.append((top + 1) / RES)
        if len(tops) >= 6:
            t = np.array(tops)
            q1, q3 = np.percentile(t, [25, 75])
            t = t[(t >= q1 - 1.5 * (q3 - q1) - 1) & (t <= q3 + 1.5 * (q3 - q1) + 1)]
            per_view.append((float(np.median(t)), len(t), float(q3 - q1)))
    if per_view:
        hs = np.array([v[0] for v in per_view])
        n = sum(v[1] for v in per_view)
        h = float(np.median(hs))
        agree = 1.0 if len(hs) == 1 or float(hs.max() - hs.min()) < 4 else 0.6
        spread = np.median([v[2] for v in per_view])
        conf = min(1.0, n / 60.0) * agree * (1.0 if spread < 3 else 0.5)
        return max(3.0, min(120.0, h)), conf
    if lows:
        return max(h0, float(np.percentile(lows, 75))), 0.2
    return h0, 0.0


def blend_height(b, h, conf):
    """The photo height against what OSM says: the tag wins unless the photos are sure, and never moves it more than 35 %."""
    ho = _osm_h(b)
    if ho is None:                                   # no tag: the photo decides, within what this kind of building can be
        g = b.gen["h"]
        h = h if conf >= 0.3 else g + (h - g) * conf / 0.3
        hi = 12.0 if b.kind() == "house" else (2.0 * g if b.area < 300 else 3.0 * g)
        return float(np.clip(h, 0.5 * g, max(g, hi)))
    w = min(1.0, conf) * 0.6
    return float(np.clip(ho + (h - ho) * w, ho * 0.65, ho * 1.35))


def _rows(o, h, lo=None):
    """Mask of the building pixels of a view between `lo` (default: above the ground-floor shops, cars, fences) and the roof."""
    k0 = int((lo if lo is not None else min(3.0, h * 0.25)) * RES)
    k1 = int(max(k0 + 1, (h - 0.3) * RES))
    m = np.zeros_like(o.ok)
    m[k0:k1] = True
    return m & o.ok & (o.lab == L_BUILDING)


def fit_colours(obs, h):
    """(wall colour, window colour) of the building pixels: two clusters, the bigger brighter one is the wall."""
    # the photo already carries its own light: no division by the game's baked wall shade (that clipped light walls to white)
    px = np.concatenate([o.rgb[_rows(o, h)] for o in obs]) if obs else np.zeros((0, 3))
    if len(px) < 50:
        return None, None
    if len(px) > 40000:
        px = px[np.random.default_rng(1).choice(len(px), 40000, replace=False)]
    lum = px @ np.array([0.3, 0.59, 0.11])
    c = np.array([np.percentile(lum, 70), np.percentile(lum, 20)])
    for _ in range(8):
        k = np.abs(lum[:, None] - c[None, :]).argmin(1)
        c = np.array([lum[k == i].mean() if (k == i).any() else c[i] for i in range(2)])
    wall = np.median(px[k == 0], 0) if (k == 0).any() else np.median(px, 0)
    win = np.median(px[k == 1], 0) if (k == 1).any() else wall * 0.5
    return np.clip(wall, 0, 255), np.clip(win, 0, 255)


def _period(profile, lo, hi):
    """Strongest repeat (in samples) of a 1-D profile between lo and hi samples, and its strength 0..1."""
    p = np.asarray(profile, np.float64)
    good = np.isfinite(p)
    if good.sum() < hi * 2:
        return None, 0.0
    p = np.where(good, p, np.nanmean(p))
    k = int(hi) * 2 + 1                                        # detrend over two periods (slow lighting gradients only)
    pad = np.pad(p, k // 2, mode="edge")
    p = p - np.convolve(pad, np.ones(k) / k, "valid")
    p -= p.mean()
    den = float(p @ p) or 1.0
    best, bs = None, 0.0
    for lag in range(int(lo), int(hi) + 1):
        r = float(p[:-lag] @ p[lag:]) / den
        if r > bs:
            best, bs = lag, r
    return best, bs


def fit_grid(obs, h):
    """Floor height and window-bay width (m) from the repeats of the facade brightness -> (floor, bay, strength)."""
    fl, bays = [], []
    for o in obs:
        m = _rows(o, h, lo=0.5)
        # only the clean stretches: columns that are facade over most of their height (trees break the rhythm)
        k0, k1 = int(0.5 * RES), int(max(1.0, h - 0.3) * RES)
        clean = m[k0:k1].mean(0) > 0.7
        m = m & clean[None, :]
        if m.sum() < 400:
            continue
        lum = o.rgb @ np.array([0.3, 0.59, 0.11])
        cnt = m.sum(1)
        row = np.where(cnt > 3, (lum * m).sum(1) / np.maximum(cnt, 1), np.nan)
        lag, s = _period(row, 2.6 * RES, 4.2 * RES)
        if lag and s > 0.1:                           # weak repeats are noise (plain walls): no vote
            fl.append((lag / RES, s * cnt.sum()))
        cntc = m.sum(0)
        col = np.where(cntc > 3, (lum * m).sum(0) / np.maximum(cntc, 1), np.nan)
        lag, s = _period(col, 2.2 * RES, min(7.0, o.ln / 2) * RES)
        if lag and s > 0.1:
            bays.append((lag / RES, s * cntc.sum()))

    def wmed(v):
        if not v:
            return None, 0.0
        v = sorted(v)
        tot = sum(w for _, w in v)
        acc = 0.0
        for x, w in v:
            acc += w
            if acc >= tot / 2:
                return x, tot
        return v[-1][0], tot
    f, wf = wmed(fl)
    b, wb = wmed(bays)
    return f, b, (wf + wb)


def synth(o, tex, h, fh, bw):
    """The game's wall (texture tiles, no tint) on the view's grid -> (nv, nu, 3) in 0..1."""
    nv, nu = o.ok.shape
    floors = max(1, round(h / fh))
    nb = max(1, round(o.ln / bw))
    fe, be = h / floors, o.ln / nb
    us = (np.arange(nu) + 0.5) / RES
    vs = (np.arange(nv) + 0.5) / RES
    S = tex.shape[0]
    col = ((us / be) % 1.0 * S).astype(int) % S
    row = (((h - vs) / fe) % 1.0 * S).astype(int) % S
    return tex[row[:, None], col[None, :]] / 255.0


def render_loss(obs, texs, mat, h, fh, bw):
    """Relative L1 between the photo and the tinted game wall, with the best tint -> (loss, tint)."""
    tex = texs.get(MATS.get(mat))
    if tex is None:
        return None, None
    P, Tt = [], []
    for o in obs:
        m = _rows(o, h)
        if m.sum() < 100:
            continue
        s = synth(o, tex, h, fh, bw)                 # albedo against albedo: the photo's light is its own
        # 2x2 averaging: windows are big, single pixels are noise
        def half(a):
            nv, nu = a.shape[:2]
            a = a[:nv // 2 * 2, :nu // 2 * 2]
            return 0.25 * (a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2])
        mm = half(m.astype(np.float32)[..., None])[..., 0] > 0.99
        P.append(half(o.rgb)[mm])
        Tt.append(half(s)[mm])
    if not P:
        return None, None
    P, Tt = np.concatenate(P), np.concatenate(Tt)
    tint = (P * Tt).sum(0) / np.maximum((Tt * Tt).sum(0), 1e-6)
    if tint.max() > 255:                             # a texture darker than the wall: keep the hue, cap the brightness
        tint = tint * (255.0 / tint.max())
    tint = np.clip(tint, 0, 255)
    loss = float(np.abs(P - Tt * tint).sum() / max(1.0, P.sum()))
    return loss, tint


def refine_pose(cap, lab, blds, h_of=lambda b: b.gen["h"]):
    """Small yaw / pitch correction that lines the buildings' outlines up with the labelled building pixels."""
    H, W = lab.shape
    step = 4
    L = lab[::step, ::step]
    isb = (L == L_BUILDING).astype(np.float32)
    valid = (L != L_NONE) & (L != L_VEHICLE)
    near = [b for b in blds.values() if np.hypot(b.c[0] - cap.x, b.c[1] - cap.z) < 150]
    if not near or isb.sum() < 50:
        return 0.0, 0.0, 0.0
    best = (-1e9, 0.0, 0.0)
    base_y, base_p = cap.dyaw, cap.dpitch
    for dy in np.arange(-4.0, 4.01, 0.5):
        for dp in (-2.0, -1.0, 0.0, 1.0, 2.0):
            cap.dyaw, cap.dpitch = dy, dp
            pred = _silhouette(cap, near, h_of, L.shape, step)
            if pred is None:
                continue
            a = (pred & valid)
            n_a, n_b = a.sum(), (~pred & valid).sum()
            if n_a < 20 or n_b < 20:
                continue
            sc = isb[a].mean() - isb[~pred & valid].mean() - 0.002 * (abs(dy) + abs(dp))
            if sc > best[0]:
                best = (sc, dy, dp)
    cap.dyaw, cap.dpitch = 0.0, 0.0
    pred = _silhouette(cap, near, h_of, L.shape, step)
    s0 = isb[pred & valid].mean() - isb[~pred & valid].mean() if (pred & valid).sum() >= 20 and (~pred & valid).sum() >= 20 else -1e9
    if best[0] < s0 + 0.02:                                  # not clearly better: keep the recorded pose
        return 0.0, 0.0, s0
    cap.dyaw, cap.dpitch = best[1], best[2]
    return best[1], best[2], best[0]


def fit_position(cap, lab, blds, log=None):
    """Where the photo was really taken: Google's panorama is often metres from the asked-for point.  Searches the camera
    position (up to 50 m back / 15 m sideways along the view) and yaw, and the target's height when OSM has no storeys, for the
    best match of the buildings' outlines with the labelled building pixels above the horizon (below it the road and the cars
    get mistaken for walls).  Moves the capture; -> (back m, right m, yaw deg, height factor, score)."""
    step = 4
    L = lab[::step, ::step]
    isb = (L == L_BUILDING).astype(np.float32)
    valid = (L != L_NONE) & (L != L_VEHICLE)
    hz = int((cap.H / 2 + cap.focal() * math.tan(math.radians(cap.pitch))) / step)
    valid[max(0, hz):] = False
    x0, z0 = cap.x, cap.z
    y = math.radians(cap.yaw)
    fw, rt = np.array([math.sin(y), -math.cos(y)]), np.array([math.cos(y), math.sin(y)])
    near = [b for b in blds.values() if np.hypot(b.c[0] - x0, b.c[1] - z0) < 180]
    tgt = blds.get(cap.bid)
    free = tgt is not None and not tgt.tags.get("building:levels") and not tgt.tags.get("height")
    hm = [1.0]

    def score():
        pred = _silhouette(cap, near, lambda b: b.gen["h"] * (hm[0] if b is tgt else 1.0), L.shape, step)
        a, nb = pred & valid, ~pred & valid
        return float(isb[a].mean() - isb[nb].mean()) if a.sum() >= 20 and nb.sum() >= 20 else -9.0
    if not near or isb[valid].sum() < 50:
        return 0.0, 0.0, 0.0, 1.0, 0.0
    cap.dyaw = cap.dpitch = 0.0
    s0 = score()
    best = (s0, 0.0, 0.0, 0.0, 1.0)
    for back in np.arange(-10, 50.1, 2.5):
        for lat in np.arange(-15, 15.1, 2.5):
            cap.x, cap.z = np.array([x0, z0]) - back * fw + lat * rt
            for dy in (-3.0, -1.5, 0.0, 1.5, 3.0):
                cap.dyaw = dy
                for m in ((1.0, 1.5, 2.0, 2.5, 3.0) if free else (1.0,)):
                    hm[0] = m
                    s = score()
                    if s > best[0] + 1e-4:
                        best = (s, back, lat, dy, m)
    s, back, lat, dy, m = best
    if s < s0 + 0.02:                                          # not clearly better: keep the recorded pose
        s, back, lat, dy, m = s0, 0.0, 0.0, 0.0, 1.0
    cap.x, cap.z = np.array([x0, z0]) - back * fw + lat * rt
    cap.dyaw = dy
    if tgt is not None and m != 1.0:
        tgt.h_seen = max(getattr(tgt, "h_seen", 0.0), tgt.gen["h"] * m)
    if log:
        log(f"{cap.file[:4]}: камера {back:+.1f} м назад, {lat:+.1f} м десно, {dy:+.1f}°" + (f", висина на целта x{m:.1f}" if m != 1.0 else "")
            + f" (поклопување {s0:.2f} -> {s:.2f})")
    return back, lat, dy, m, s


def _silhouette(cap, blds, h_of, shape, step):
    """Pixels covered by the buildings' boxes (footprint x height) from the capture camera, at 1/step resolution."""
    from PIL import ImageDraw
    im = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(im)
    eye = cap.eye()
    for b in blds:
        for a, bb, nrm, ln in b.walls():
            if (eye[[0, 2]] - (a + bb) / 2) @ nrm <= 0:
                continue
            h = h_of(b)
            P = np.array([[a[0], b.base - 1, a[1]], [bb[0], b.base - 1, bb[1]], [bb[0], b.base + h, bb[1]], [a[0], b.base + h, a[1]]])
            u, v, zc = cap.project(P)
            if (zc < 1).any():
                continue
            d.polygon([(float(x) / step, float(y) / step) for x, y in zip(u, v)], fill=1)
    return np.asarray(im, bool)


def plausible_mats(b, h):
    """Facades that make sense for this building (the photo picks among them, it does not turn a tower into a cottage)."""
    kind = b.kind()
    if kind == "house" or h < 9:
        return [0, 5, 7, 10]                                       # plain, family house, brick, cream
    if b.tags.get("building") in ("commercial", "office", "retail", "industrial"):
        return [0, 1, 8, 11]
    return [0, 1, 4, 7, 8, 9, 10, 11] if h >= 15 else [0, 4, 7, 10, 11]


def _weighted_median(vals, w):
    o = np.argsort(vals)
    c = np.cumsum(np.asarray(w, np.float64)[o])
    return float(np.asarray(vals)[o][np.searchsorted(c, c[-1] / 2)])


def fit_detail(b, obs, log=None):
    """The 'detail' fit: height and colours as the other fits, then every seen wall through facade.analyse (roof line, roof band,
    floor grid, bay columns, a texture tile per column, AC units, balconies).  Tiles stay in b.tiles (photo pixels, local only)."""
    import facade
    good = [o for o in obs if o.n_build >= 0.25 * max(1, int(o.ok.sum()))] or obs
    h_raw, hc = fit_height(good, max(b.gen["h"], getattr(b, "h_seen", 0.0)))
    h = blend_height(b, h_raw, hc)
    out = {"h": round(h, 1), "h_photo": round(h_raw, 1), "src": "photo", "conf": round(hc, 2), "views": len(good)}
    wall, win = fit_colours(good, h)
    if wall is not None:
        out["wallc"] = [int(v) for v in wall]
    if win is not None:
        out["winc"] = [int(v) for v in win]
    try:
        lv = float(str(b.tags.get("building:levels", "")).split(";")[-1])
    except ValueError:
        lv = 0.0
    best_view = {}                               # per wall: its own capture first (aimed at it), then the most facade pixels
    rank = lambda o: (o.cap.bid == b.id, o.n_build)
    for o in good:
        if o.wi not in best_view or rank(o) > rank(best_view[o.wi]):
            best_view[o.wi] = o
    walls, tiles, dets = [], [], []
    for wi, o in sorted(best_view.items()):
        try:
            f = facade.analyse(o, lv, log)
        except Exception as e:  # noqa: BLE001 - one odd wall must not stop the building
            if log:
                log(f"    ѕид {wi}: анализата падна ({type(e).__name__}: {e})")
            continue
        if f is None:
            continue
        t = f.pop("_tiles")
        off = len(tiles)
        tiles += t
        dets += f.pop("det")
        for c in f["cols"]:
            c[2] += off
        walls.append(f)
    out["pitched"] = h < 11 and b.gen["small"]
    if not walls:
        return out
    lens = [f["ln"] for f in walls]
    seen = [f for f in walls if f["top_seen"] > 0.3]
    if seen:
        wt = _weighted_median([f["walltop"] for f in seen], [f["ln"] for f in seen])
        top = _weighted_median([f["top"] for f in seen], [f["ln"] for f in seen])
        if not (b.tags.get("height") or b.tags.get("building:levels")) or abs(top - b.gen["h"]) < 0.4 * b.gen["h"]:
            out["h"] = round(max(2.5, wt), 1)
            out["h_top"] = round(top, 1)
    elif getattr(b, "h_seen", 0.0) > out["h"]:
        out["h"] = round(b.h_seen, 1)
    bands = [s[3] for f in walls for s in f["secs"] if s[3] > 0]
    roofcs = [f["roofc"] for f in walls if f.get("roofc")]
    best = max(walls, key=lambda f: f["ln"] * (1 + len(f["cols"])))
    out.update(floor=best["fh"], bay=best["bw"], walls=walls, det=dets, cycle=[c[2] for c in best["cols"]], ntiles=len(tiles))
    if bands and roofcs:
        rise = float(np.median(bands))
        kind = "pitched" if (b.kind() == "house" or b.area < 260 or b.gen["small"]) else "mansard"
        out["roof"] = {"kind": kind, "rise": round(rise, 2), "c": [int(v) for v in np.median(roofcs, 0)]}
        out["roofc"] = out["roof"]["c"]
        out["pitched"] = kind == "pitched"
        if "h_top" not in out:
            out["h"] = round(max(2.5, out["h"] - rise), 1) if kind == "mansard" else out["h"]
    b.tiles = tiles
    if log:
        log(f"  зграда {b.id}: ѕид {out['h']:.1f} м" + (f" + покрив {out['roof']['kind']} {out['roof']['rise']:.1f} м" if "roof" in out else "")
            + f", ѕидови {len(walls)}, плочки {len(tiles)}, клима {sum(len(d['ac']) for d in dets)}, балкони {sum(1 for d in dets if d['balc'])}"
            + f", кат {best['fh']:.2f} м, колона {best['bw']:.2f} м")
    return out


def fit_building(b, obs, algo, texs, log=None):
    """The fitted look of one building from its views."""
    if algo == "detail":
        return fit_detail(b, obs, log)
    # views that are mostly something else (trees, cars) only add noise when there are better ones
    good = [o for o in obs if o.n_build >= 0.25 * max(1, int(o.ok.sum()))]
    obs = good or obs
    h_raw, hc = fit_height(obs, b.gen["h"])
    h = blend_height(b, h_raw, hc)
    out = {"h": round(h, 1), "h_photo": round(h_raw, 1), "src": "photo", "conf": round(hc, 2), "views": len(obs)}
    wall, win = fit_colours(obs, h)
    mat = b.gen["mat"]
    fh, bw = b.gen["floor"], b.gen["bay"]
    if algo == "colour":
        if wall is not None:
            loss, tint = render_loss(obs, texs, mat, h, fh, bw) if texs else (None, None)
            out["wallc"] = [int(v) for v in (tint if tint is not None else wall)]
            if loss is not None:
                out["loss"] = round(loss, 3)
    else:
        f_, b_, _s = fit_grid(obs, h)
        try:                                         # OSM storeys beat a weak brightness rhythm for the floor height
            lv = float(str(b.tags.get("building:levels", "")).split(";")[-1])
            f_ = float(np.clip((h - 1.0) / lv, 2.6, 4.2)) if lv >= 1 else f_
        except ValueError:
            pass
        if algo == "grid":
            fh, bw = (f_ or fh), (b_ or bw)
            cands = [(m, fh, bw) for m in plausible_mats(b, h)]
        else:
            fhs = sorted({round(x, 2) for x in (f_ or 3.2, 3.0, 3.2)})
            bws = sorted({round(x, 2) for x in (b_ or 3.4, 3.4, 2.6, 4.5)})
            cands = [(m, f, w) for m in plausible_mats(b, h) for f in fhs for w in bws]
        best = None
        for m, f, w in cands:
            loss, tint = render_loss(obs, texs, m, h, f, w) if texs else (None, None)
            if loss is not None and (best is None or loss < best[0]):
                best = (loss, m, f, w, tint)
        if best:
            out.update(loss=round(best[0], 3), mat=best[1], floor=best[2], bay=best[3], wallc=[int(v) for v in best[4]])
        elif wall is not None:
            out.update(wallc=[int(v) for v in wall], floor=fh, bay=bw)
    if win is not None:
        out["winc"] = [int(v) for v in win]
    out["pitched"] = h < 11 and b.gen["small"]
    return out


def infer(blds, algo, k=3):
    """Buildings without views borrow the look of the nearest fitted ones of the same kind (unseen faces of a fitted building
    simply share its numbers)."""
    done = [b for b in blds.values() if algo in b.fits and b.fits[algo].get("src") == "photo"]
    if not done:
        return 0
    n = 0
    C = np.array([b.c for b in done])
    for b in blds.values():
        if algo in b.fits and b.fits[algo].get("src") == "photo":
            continue
        same = [i for i, o in enumerate(done) if o.kind() == b.kind()] or list(range(len(done)))
        d = np.hypot(C[same, 0] - b.c[0], C[same, 1] - b.c[1])
        order = np.argsort(d)[:k]
        if d[order[0]] > 250:
            b.fits.pop(algo, None)
            continue
        src = [done[same[i]].fits[algo] for i in order]
        w = 1.0 / (1.0 + d[order])
        f = {"src": "inferred", "conf": round(float(0.5 / (1 + d[order[0]] / 60)), 2), "from": [done[same[i]].id for i in order]}
        if any("wallc" in s for s in src):
            cs = [(np.array(s["wallc"]), wi) for s, wi in zip(src, w) if "wallc" in s]
            f["wallc"] = [int(v) for v in sum(c * wi for c, wi in cs) / sum(wi for _, wi in cs)]
        if "mat" in src[0]:
            f["mat"], f["floor"], f["bay"] = src[0]["mat"], src[0].get("floor", 3.2), src[0].get("bay", 3.4)
        if "cycle" in src[0]:                       # the nearest fitted building's column tiles and details on every wall
            f.update(tile_src=f["from"][0], cycle=src[0]["cycle"], det=src[0]["det"], floor=src[0]["floor"], bay=src[0]["bay"])
            if "roof" in src[0] and (src[0]["roof"]["kind"] == "pitched") == (b.kind() == "house" or b.area < 260):
                f["roof"], f["roofc"] = src[0]["roof"], src[0]["roofc"]
        t = b.tags
        if not t.get("height") and not t.get("building:levels"):          # OSM gives no height: the neighbours' fitted one
            hs = [s["h"] for s, o in zip(src, order) if 0.4 < done[same[o]].area / max(b.area, 1) < 2.5]
            if hs:
                f["h"] = round(float(np.median(hs)), 1)
        b.fits[algo] = f
        n += 1
    return n


def atlas_path(fit_path):
    return os.path.splitext(fit_path)[0] + "_atlas.png"


def write_fits(blds, algo, path):
    """The game's file: only what differs from the generated look matters, the rest is for the viewer / later rounds."""
    out = {}
    for b in blds.values():
        f = b.fits.get(algo)
        if not f:
            continue
        e = {k: f[k] for k in ("h", "mat", "wallc", "roofc", "floor", "bay", "pitched", "src", "conf", "walls", "roof", "cycle",
                               "det", "tile_src") if k in f}
        out[str(b.id)] = e
    os.makedirs(os.path.dirname(path), exist_ok=True)
    owners = [b for b in blds.values() if b.fits.get(algo, {}).get("src") == "photo" and getattr(b, "tiles", None) and "cycle" in b.fits[algo]]
    if owners:                                    # one texture atlas for all tiles: photo pixels, stays next to the photos
        import facade
        atlas, uvs = facade.pack([b.tiles for b in owners])
        Image.fromarray(atlas).save(atlas_path(path))
        uv_of = {b.id: uv for b, uv in zip(owners, uvs)}
        for k, e in list(out.items()):
            src = uv_of.get(int(e.get("tile_src", k)))
            if "cycle" in e and src is not None:
                e["tiles"] = [[round(v, 6) for v in r] for r in src]
            elif "cycle" in e:
                for key in ("cycle", "walls", "det", "tile_src"):
                    e.pop(key, None)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "algo": algo, "made": time.strftime("%Y-%m-%d %H:%M"), "buildings": out}, f, indent=0)
    os.replace(tmp, path)
    return len(out)


# ------------------------------------------------------------------------------------------------------------ the job
class Job(threading.Thread):
    """Runs the pipeline for one folder and one algorithm; the viewer reads .caps / .blds / .log / .version while it works."""

    def __init__(self, folder, algo, texs=None, osm_dir=None, seg="auto", state=None):
        super().__init__(daemon=True)
        self.folder, self.algo, self.texs = folder, algo, texs or {}
        self.osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
        self.seg_kind = seg
        self.caps, self.blds = (state or (None, None))
        self.log_lines = []
        self.version = 0
        self.step, self.frac = "", 0.0
        self.done = False
        self.error = None
        self.stop = False
        self.labels = {}                 # capture file -> label map (viewer overlay)

    def log(self, s):
        self.log_lines.append(s)
        print("[photogram]", s)
        self.version += 1

    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 - shown in the viewer
            import traceback
            traceback.print_exc()
            self.error = f"{type(e).__name__}: {e}"
            self.log("ГРЕШКА: " + self.error)
        self.done = True
        self.version += 1

    def _run(self):
        import segment
        if self.caps is None:
            self.step = "манифест"
            self.caps = read_manifest(self.folder)
            miss = sum(1 for c in self.caps if not c.exists)
            self.log(f"снимки: {len(self.caps)}" + (f" ({miss} ги нема во папката)" if miss else ""))
            self.step = "згради"
            self.blds = load_city(self.osm_dir, self.caps, self.log)
            self.version += 1
        for b in self.blds.values():
            b.obs = []
            b.fits.pop(self.algo, None)
        global RES
        import facade
        RES = facade.RES if self.algo == "detail" else 4.0            # the detail fit reads windows and AC units: 12 px/m
        self.log(f"резолуција на фасадите: {RES:.0f} px/м")
        seg = segment.get(self.seg_kind, self.log)
        self.log(f"сегментација: {seg.name}")
        cache = os.path.join(self.folder, CACHE)
        os.makedirs(cache, exist_ok=True)
        caps = [c for c in self.caps if c.exists]
        # the captures of one building one after the other, so it can be fitted (and shown) as soon as its last view is in
        caps.sort(key=lambda c: (c.bid, c.file))
        last_of = {c.bid: i for i, c in enumerate(caps)}
        touched = set()
        for i, c in enumerate(caps):
            if self.stop:
                return
            self.step, self.frac = f"снимка {i + 1}/{len(caps)}: {c.file[:28]}", i / max(1, len(caps))
            self.version += 1
            img = c.image()
            lab = seg.labels(img, os.path.join(cache, os.path.splitext(c.file)[0] + f".{seg.name}.png"))
            self.labels[c.file] = lab
            ui = c.ui_mask()
            lab = lab.copy()
            lab[ui] = L_NONE
            c.dyaw = c.dpitch = 0.0
            if not hasattr(c, "x0"):
                c.x0, c.z0 = c.x, c.z
            c.x, c.z = c.x0, c.z0
            fit_position(c, lab, self.blds, self.log)                 # always: the photo is rarely taken where the file says
            edges = wall_edges(self.blds, np.array([c.x, c.z]), 220)
            views = facade_views(c, img, lab, ui, self.blds, edges)
            for o in views:
                o.bld.obs.append(o)
                touched.add(o.bld.id)
            tgt = sum(1 for o in views if o.bld.id == c.bid)
            c.status = f"{len(views)} ѕида ({tgt} на целта)" if views else "ништо употребливо"
            self.log(f"{c.file[:4]}: {c.status}")
            # fit every building whose views are all in (its own captures done; neighbours seen from here count too)
            pending_bids = {cc.bid for cc in caps[i + 1:]}
            for bid in list(touched):
                if bid in pending_bids:
                    continue
                b = self.blds[bid]
                b.fits[self.algo] = fit_building(b, b.obs, self.algo, self.texs, self.log)
                b.version += 1
                touched.discard(bid)
                f = b.fits[self.algo]
                if self.algo != "detail":
                    self.log(f"  зграда {bid}: {f['h']:.1f} м (од {b.gen['h']:.1f}), фасада {MATS.get(f.get('mat', b.gen['mat']))}"
                         + (f", кат {f['floor']:.2f} м, прозорец {f['bay']:.2f} м" if "floor" in f else "")
                         + (f", разлика {f['loss']:.2f}" if "loss" in f else ""))
                self.version += 1
            del img
        for bid in touched:
            b = self.blds[bid]
            b.fits[self.algo] = fit_building(b, b.obs, self.algo, self.texs, self.log)
            b.version += 1
        self.step = "незабележани згради"
        n = infer(self.blds, self.algo)
        for b in self.blds.values():
            b.version += 1
            b.obs = []                                   # free the resampled photos (the viewer keeps only numbers)
        self.log(f"изведени од соседи: {n}")
        out = os.path.join(cache, f"fit_{self.algo}.json")
        k = write_fits(self.blds, self.algo, out)
        self.log(f"готово: {k} згради -> {out}")
        self.step, self.frac = "готово", 1.0


def apply_to_game(folder, algo, osm_dir=None):
    """Copy a finished fit to <osm>/photogram.json: the next world build uses it (the setting decides, see set_enabled)."""
    import shutil
    osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
    src = os.path.join(folder, CACHE, f"fit_{algo}.json")
    shutil.copyfile(src, os.path.join(osm_dir, "photogram.json"))
    at = os.path.join(osm_dir, "photogram_atlas.png")
    if os.path.exists(atlas_path(src)):
        shutil.copyfile(atlas_path(src), at)
    elif os.path.exists(at):
        os.remove(at)
    off = os.path.join(osm_dir, "photogram.off.json")
    if os.path.exists(off):
        os.remove(off)


def enabled(osm_dir=None):
    """None = no fit made yet, True / False = the world build uses it / not."""
    osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
    if os.path.exists(os.path.join(osm_dir, "photogram.json")):
        return True
    return False if os.path.exists(os.path.join(osm_dir, "photogram.off.json")) else None


def set_enabled(on, osm_dir=None):
    """The 'current / photo-fitted buildings' switch: the fit file is renamed in and out of the build's way (the build's
    fingerprint sees the change and rebuilds)."""
    osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
    a, b = os.path.join(osm_dir, "photogram.json"), os.path.join(osm_dir, "photogram.off.json")
    if on and os.path.exists(b):
        os.replace(b, a)
    elif not on and os.path.exists(a):
        os.replace(a, b)
