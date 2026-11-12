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
# the builder's settings (photoview's settings tab; saved per photo folder in _photogram/settings.json).  Every setting that changes
# the result is part of the stored job's signature: change one and the stored per-photo results are not reused.
SETTINGS = {"res": 12.0,          # ДЕТАЛИ facade resolution, pixels per metre (8 fast / 12 / 16 fine)
            "dist": 200.0,        # walls further than this from a camera are not read (m)
            "workers": 0,         # worker processes, 0 = all cores but one
            "pose": "fast",       # camera position: fast / full / file
            "seg": "auto",        # segmenter: auto / segformer / simple
            "priors": True,       # depth from the usual Skopje block order when no side face is seen
            "sym": True,          # fill unseen columns from mirror symmetry / repeats
            "fuse": True,         # combine every view of a wall (else only the best one)
            "min_px": 1500}       # a view needs this many building pixels
# how the fitted numbers become geometry (tools/build_world.py photo_facade / photo_roof; no new fit needed when they change):
# the photogrammetry screen's ЕЛЕМЕНТИ tab; they go into photogram.json with the fit ("opts")
OPTS = {"relief": True, "windows": True, "frames": True, "blinds": True, "sills": True, "balconies": True, "ac": True,
        "bands": True, "ground": True, "steps": True, "opp": True, "cells": True, "roofs": True, "roof_extras": True,
        "eaves": True, "kit_on": True, "kit": [], "kit_auto": True, "kit_scope": "blocks", "style": "НИШТО",
        "inferred": "lite", "sat": 1.0, "lod": 400.0}
RESULT_KEYS = ("res", "dist", "pose", "seg", "priors", "sym", "min_px")       # these change the per-photo results
CODE_VER = 3                      # bump when the per-photo results change meaning
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
    ("detail", "ДЕТАЛИ", "прозорци, лоѓии, балкони, клими, кровови и површини во 3D, сè процедурално"),
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

    def __getstate__(self):                             # to a worker: no views, no fits, no cached triangles
        d = dict(self.__dict__)
        d.update(obs=[], fits={})
        d.pop("_tri", None)
        return d

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

    def __getstate__(self):                             # photo pixels travel between processes as bytes, not floats
        d = dict(self.__dict__)
        d["rgb"] = np.clip(self.rgb, 0, 255).astype(np.uint8)
        return d

    def __setstate__(self, d):
        d["rgb"] = d["rgb"].astype(np.float32)
        self.__dict__.update(d)


class Slim:
    """A facade view reduced to numbers in the worker: its facade.analyse result, its roof-line votes and a small colour sample.
    No photo pixels survive it, so thousands of them fit in memory, travel between processes and are stored for a resumed job."""

    def __init__(self, o, levels, log=None):
        import facade
        self.cap, self.bld, self.wi, self.a, self.b, self.nrm, self.ln = o.cap, o.bld, o.wi, o.a, o.b, o.nrm, o.ln
        self.shade, self.n_build, self.n_ok = o.shade, o.n_build, int(o.ok.sum())
        h0 = max(o.bld.gen["h"], getattr(o.bld, "h_seen", 0.0))
        self.hv, self.lows = _height_votes(o, h0)
        px = o.rgb[_rows(o, h0)]
        if len(px) > 3000:
            px = px[np.random.default_rng(o.wi).choice(len(px), 3000, replace=False)]
        self.px = np.clip(px, 0, 255).astype(np.uint8)
        try:
            self.fa = facade.analyse(o, levels, log)
        except Exception as e:  # noqa: BLE001 - one odd wall must not stop the photo
            self.fa = None
            if log:
                log(f"    ѕид {o.wi}: анализата падна ({type(e).__name__}: {e})")


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
        if np.hypot(*(b.c - eye[[0, 2]])) > SETTINGS["dist"]:
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
        v, lw = (o.hv, o.lows) if isinstance(o, Slim) else _height_votes(o, h0)
        lows += lw
        if v is not None:
            per_view.append(v)
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


def _height_votes(o, h0):
    """One view's roof-line vote: (median top, columns, spread) or None, and the lower bounds of cut-off columns."""
    lab, ok = o.lab, o.ok
    nv = lab.shape[0]
    isb = (lab == L_BUILDING) & ok
    issky = (lab == L_SKY) & ok
    tops, lows = [], []
    for j in np.nonzero(isb.any(0))[0]:
        rows = np.nonzero(isb[:, j])[0]
        if rows[0] > max(6.0, 0.5 * h0) * RES:             # no facade low down in this column: a building behind, not this one
            continue
        top = rows[-1]
        above = np.nonzero(issky[top + 1:min(nv, top + 1 + int(2.0 * RES)), j])[0]
        if len(above):
            tops.append((top + 1) / RES)
        elif not ok[top + 1:, j].any():
            lows.append((top + 1) / RES)
    if len(tops) < 6:
        return None, lows
    t = np.array(tops)
    q1, q3 = np.percentile(t, [25, 75])
    t = t[(t >= q1 - 1.5 * (q3 - q1) - 1) & (t <= q3 + 1.5 * (q3 - q1) + 1)]
    return (float(np.median(t)), len(t), float(q3 - q1)), lows


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
    px = np.concatenate([o.px.astype(np.float32) if isinstance(o, Slim) else o.rgb[_rows(o, h)] for o in obs]) if obs else np.zeros((0, 3))
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


def fit_position(cap, lab, blds, log=None, mode="fast", stop=lambda: False):
    """Where the photo was really taken: Google's panorama is often metres from the asked-for point.  Searches the camera
    position (up to 50 m back / 15 m sideways along the view) and yaw, and the target's height when OSM has no storeys, for the
    best match of the buildings' outlines with the labelled building pixels above the horizon (below it the road and the cars
    get mistaken for walls).  mode "full" tries every grid point (thousands of outline drawings); "fast" a coarse grid and then
    halving steps round the best (~150 drawings, same result on the test photos).  Moves the capture;
    -> (back m, right m, yaw deg, height factor, score)."""
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
    seen = {}

    def score(back, lat, dy, m):
        k = (round(back, 2), round(lat, 2), round(dy, 2), round(m, 2))
        if k not in seen:
            cap.x, cap.z = np.array([x0, z0]) - back * fw + lat * rt
            cap.dyaw = dy
            pred = _silhouette(cap, near, lambda b: b.gen["h"] * (m if b is tgt else 1.0), L.shape, step)
            a, nb = pred & valid, ~pred & valid
            seen[k] = float(isb[a].mean() - isb[nb].mean()) if a.sum() >= 20 and nb.sum() >= 20 else -9.0
        return seen[k]
    if not near or isb[valid].sum() < 50:
        return 0.0, 0.0, 0.0, 1.0, 0.0
    cap.dpitch = 0.0
    s0 = score(0.0, 0.0, 0.0, 1.0)
    best = (s0, 0.0, 0.0, 0.0, 1.0)
    ms = (1.0, 1.5, 2.0, 2.5, 3.0) if free else (1.0,)
    if mode == "full":
        grid = [(bk, lt, dy, m) for bk in np.arange(-10, 50.1, 2.5) for lt in np.arange(-15, 15.1, 2.5)
                for dy in (-3.0, -1.5, 0.0, 1.5, 3.0) for m in ms]
    else:
        grid = [(bk, lt, 0.0, m) for bk in np.arange(-10, 50.1, 10.0) for lt in (-15.0, -7.5, 0.0, 7.5, 15.0)
                for m in ((1.0, 2.0, 3.0) if free else (1.0,))]
    for g in grid:
        if stop():
            break
        sc = score(*g)
        if sc > best[0] + 1e-4:
            best = (sc, *g)
    if mode != "full":                      # halving pattern search round the best grid point
        st = [5.0, 3.75, 1.5, 0.5 if free else 0.0]
        while st[0] >= 1.2 and not stop():
            moved = False
            for i in range(4):
                if st[i] <= 0:
                    continue
                for sgn in (-1, 1):
                    c = list(best[1:])
                    c[i] += sgn * st[i]
                    c[0], c[1] = float(np.clip(c[0], -10, 50)), float(np.clip(c[1], -15, 15))
                    c[2], c[3] = float(np.clip(c[2], -3, 3)), float(np.clip(c[3], 1.0, 3.0))
                    sc = score(*c)
                    if sc > best[0] + 1e-4:
                        best, moved = (sc, *c), True
            if not moved:
                st = [v / 2 for v in st]
    s, back, lat, dy, m = best
    if s < s0 + 0.02:                                          # not clearly better: keep the recorded pose
        s, back, lat, dy, m = s0, 0.0, 0.0, 0.0, 1.0
    apply_pose(cap, blds, back, lat, dy, m, x0, z0)
    if log:
        log(f"{cap.file[:4]}: камера {back:+.1f} м назад, {lat:+.1f} м десно, {dy:+.1f}°" + (f", висина на целта x{m:.1f}" if m != 1.0 else "")
            + f" (поклопување {s0:.2f} -> {s:.2f}, {len(seen)} обиди)")
    return back, lat, dy, m, s


def apply_pose(cap, blds, back, lat, dy, m, x0=None, z0=None):
    """Move the capture by a found pose (back / right metres along its view, yaw) and note the target's seen height."""
    x0 = cap.x if x0 is None else x0
    z0 = cap.z if z0 is None else z0
    y = math.radians(cap.yaw)
    fw, rt = np.array([math.sin(y), -math.cos(y)]), np.array([math.cos(y), math.sin(y)])
    cap.x, cap.z = np.array([x0, z0]) - back * fw + lat * rt
    cap.dyaw, cap.dpitch = dy, 0.0
    tgt = blds.get(cap.bid)
    if tgt is not None and m != 1.0:
        tgt.h_seen = max(getattr(tgt, "h_seen", 0.0), tgt.gen["h"] * m)


def _silhouette(cap, blds, h_of, shape, step):
    """Pixels covered by the buildings' boxes (footprint x height) from the capture camera, at 1/step resolution."""
    from PIL import ImageDraw
    im = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(im)
    eye = cap.eye()
    fwd, right, up = cap.basis()
    f = cap.focal()
    M = np.stack([right, up, fwd], 1)
    for b in blds:
        ws = b.walls()
        if not ws:
            continue
        h = h_of(b)
        A = np.array([w[0] for w in ws])
        Bq = np.array([w[1] for w in ws])
        Nq = np.array([w[2] for w in ws])
        vis = ((eye[[0, 2]] - (A + Bq) / 2) * Nq).sum(1) > 0
        if not vis.any():
            continue
        A, Bq = A[vis], Bq[vis]
        k = len(A)
        P = np.empty((k, 4, 3))
        P[:, 0, 0], P[:, 0, 2], P[:, 1, 0], P[:, 1, 2] = A[:, 0], A[:, 1], Bq[:, 0], Bq[:, 1]
        P[:, 2, 0], P[:, 2, 2], P[:, 3, 0], P[:, 3, 2] = Bq[:, 0], Bq[:, 1], A[:, 0], A[:, 1]
        P[:, :2, 1], P[:, 2:, 1] = b.base - 1, b.base + h
        q = (P - eye) @ M
        ok = (q[:, :, 2] >= 1).all(1)
        zs = np.maximum(q[:, :, 2], 1e-3)
        U = (cap.W / 2 + f * q[:, :, 0] / zs) / step
        V = (cap.H / 2 - f * q[:, :, 1] / zs) / step
        for j in np.nonzero(ok)[0]:
            d.polygon(list(zip(U[j].tolist(), V[j].tolist())), fill=1)
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


def _inward(ring, p, nrm):
    """How deep the footprint is from point p of a wall straight inwards (along -nrm) -> m."""
    d = -np.asarray(nrm, float)
    best = None
    n = len(ring)
    for i in range(n):
        a, e = ring[i], ring[(i + 1) % n]
        s = e - a
        den = d[0] * s[1] - d[1] * s[0]
        if abs(den) < 1e-9:
            continue
        w = a - p
        t = (w[0] * s[1] - w[1] * s[0]) / den
        q = (w[0] * d[1] - w[1] * d[0]) / den
        if t > 0.3 and 0 <= q <= 1 and (best is None or t < best):
            best = t
    return float(best) if best else 6.0


def roof_shape(b, walls, bands, roofcs, log=None):
    """The roof of the building from the roof lines its walls show (facade.roof_profile per wall section):
    a triangle of the wall's colour = a gable end (ridge across that wall), a triangle / trapezoid of the roof's colour = hip,
    a slope = shed, a level line over a roof band = ridge along that wall (hip on houses, mansard on blocks), nothing = flat.
    Heights seen above the wall plane are behind it: they are pushed back to their real depth with the camera's geometry
    (similar triangles).  -> {"kind", "rise", "c", "axis" [x, z] ridge direction, "eave", "chim" [[x, z, w, top]],
    "hous" [[x, z, sx, sz, top, yaw]], "high" [x, z] (shed: the high side's normal)} or None."""
    obs = []
    for f in walls:
        a, e = np.array(f["a"], float), np.array(f["b"], float)
        ln = max(1e-6, float(np.hypot(*(e - a))))
        t = (e - a) / ln
        nrm = np.array([t[1], -t[0]])
        uc, dn, ey = f.get("cam", [ln / 2, 20.0, 2.5])
        for rp, sc in zip(f.get("rp", []), f["secs"]):
            if f["top_seen"] < 0.2:
                continue
            obs.append((rp, f, a, t, nrm, dn, ey, sc[2] - sc[3]))
    if not obs:
        if bands and roofcs:
            return {"kind": "hip" if b.area < 400 else "mansard", "rise": round(float(np.median(bands)), 2),
                    "c": [int(v) for v in np.median(roofcs, 0)], "eave": 0.4 if b.area < 400 else 0.0, "chim": [], "hous": []}
        return None
    house = b.kind() == "house" or b.area < 400 or b.gen["small"]
    rc = [int(v) for v in np.median(roofcs, 0)] if roofcs else list(b.gen["roofc"])
    ring = b.ring

    def back(v, o, p):                     # a height seen on the wall plane -> its height where it really is (dr behind the wall)
        rp, f, a, t, nrm, dn, ey, wt = o
        dr = _inward(ring, a + t * p, nrm) / 2
        return ey + (v - ey) * (dn + dr) / dn

    for o in obs:                     # slopes on a block's roof line are partial views / trees, not shed or gable roofs
        rp = o[0]
        if rp["kind"] != "level" and (not house or rp["rise"] > min(6.0, 0.6 * rp["w"])):
            rp["kind"] = "level"
    peaks = [o for o in obs if o[0]["kind"] == "peak"]
    gables = [o for o in peaks if o[0].get("wall_like", 0) > 0.5]
    sheds = [o for o in obs if o[0]["kind"].startswith("shed")]
    traps = [o for o in obs if o[0]["kind"] == "trap"]
    levels = [o for o in obs if o[0]["kind"] == "level" and o[0]["band"] >= 0.8]
    axis, high = None, None
    if gables:
        o = max(gables, key=lambda o: o[0]["w"])
        kind, rise, axis = "gable", o[0]["rise"], o[4]                  # the gable wall is in the photo's plane: no correction
    elif peaks or traps:
        o = max(peaks + traps, key=lambda o: o[0]["w"])
        kind = "hip"
        rise = back(o[7] + o[0]["rise"], o, o[0]["u"]) - o[7]
        if o[0]["kind"] == "trap":
            axis = o[3]
    elif sheds:
        o = max(sheds, key=lambda o: o[0]["w"])
        kind, rise = "shed", o[0]["rise"]
        axis = o[4]
        high = (o[3] if o[0]["kind"] == "shed_r" else -o[3]).tolist()
    elif levels:
        o = max(levels, key=lambda o: o[0]["w"])
        rise = back(o[7] + o[0]["band"], o, o[0]["u"]) - o[7]
        if house:
            kind, axis = "hip", o[3]
        else:
            kind, rise = "mansard", o[0]["band"]
    elif bands and roofcs:
        kind, rise = ("hip" if house else "mansard"), float(np.median(bands))
    else:
        kind, rise = "flat", 0.0
    ext = np.ptp(ring, 0)
    if kind == "hip" and axis is None and max(ext) < 1.25 * max(1.0, min(ext)):
        kind = "pyramid"
    eaves = [o[0]["eave"] for o in obs if o[0].get("eave", 0) > 0]
    eave = float(np.median(eaves)) if eaves else (0.45 if kind in ("gable", "hip", "pyramid", "shed") else 0.0)
    chim, hous = [], []
    for o in obs:
        rp, f, a, t, nrm, dn, ey, wt = o
        for u, w, v in rp["chim"]:
            dep = _inward(ring, a + t * u, nrm)
            p = a + t * u - nrm * dep / 2
            chim.append([round(float(p[0]), 2), round(float(p[1]), 2), w, round(float(min(back(v, o, u), wt + rise + 2.5)), 2)])
        for u0, u1, v in rp["hous"]:
            dep = _inward(ring, a + t * (u0 + u1) / 2, nrm)
            sz = float(np.clip(dep * 0.3, 1.5, 5.0))
            p = a + t * (u0 + u1) / 2 - nrm * (min(2.0, dep * 0.2) + sz / 2)
            hous.append([round(float(p[0]), 2), round(float(p[1]), 2), round(u1 - u0, 2), round(sz, 2),
                         round(float(ey + (v - ey) * (dn + dep * 0.2) / dn), 2), round(math.atan2(t[1], t[0]), 3)])
    out = {"kind": kind, "rise": round(float(np.clip(rise, 0.0, 9.0)), 2), "c": rc, "eave": round(eave, 2),
           "chim": chim[:6], "hous": hous[:4]}
    if axis is not None:
        out["axis"] = [round(float(axis[0]), 3), round(float(axis[1]), 3)]
    if high is not None:
        out["high"] = [round(float(v), 3) for v in high]
    if log:
        log(f"    покрив: {kind}, подигање {out['rise']:.1f} м, стреа {eave:.2f} м" + (f", слеме {out.get('axis')}" if axis is not None else "")
            + f", оџаци {len(out['chim'])}, надградби {len(out['hous'])} (од {len(obs)} профили: "
            + ", ".join(f"{o[0]['kind']}" for o in obs) + ")")
    return out


def fit_detail(b, obs, log=None):
    """The 'detail' fit: height and colours as the other fits, then every seen wall through facade.analyse (roof line, roof band,
    floor grid, bay columns and their procedural parameters).  Only numbers come out: no photo pixel reaches the game."""
    import facade
    good = [o for o in obs if o.n_build >= 0.25 * max(1, o.n_ok if isinstance(o, Slim) else int(o.ok.sum()))] or obs
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
    by_wall = {}                                 # per wall: every view of it, its own capture first (aimed at it), then pixels
    rank = lambda o: (o.cap.bid == b.id, o.n_build)
    for o in good:
        by_wall.setdefault(o.wi, []).append(o)
    walls, params = [], []
    for wi, vs in sorted(by_wall.items()):
        vs.sort(key=rank, reverse=True)
        if isinstance(vs[0], Slim):
            fas = [o.fa for o in vs if o.fa is not None]
        else:
            fas = []
            for o in vs[:1]:
                try:
                    fas.append(facade.analyse(o, lv, log))
                except Exception as e:  # noqa: BLE001 - one odd wall must not stop the building
                    if log:
                        log(f"    ѕид {wi}: анализата падна ({type(e).__name__}: {e})")
            fas = [f for f in fas if f is not None]
        if not fas:
            continue
        f = facade.fuse(fas[0], fas[1:], log) if SETTINGS["fuse"] and len(fas) > 1 else fas[0]
        off = len(params)
        params += f.pop("params")
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
    out.update(floor=best["fh"], bay=best["bw"], walls=walls, params=params, cycle=[c[2] for c in best["cols"]],
               surf=best["surf"], rough=best["rough"])
    roof = roof_shape(b, walls, bands, roofcs, log)
    if roof:
        out["roof"] = roof
        out["roofc"] = roof["c"]
        out["pitched"] = roof["kind"] not in ("flat", "mansard")
        if "h_top" not in out and roof["kind"] == "mansard":
            out["h"] = round(max(2.5, out["h"] - roof["rise"]), 1)
    if log:
        log(f"  зграда {b.id}: ѕид {out['h']:.1f} м" + (f" + покрив {out['roof']['kind']} {out['roof']['rise']:.1f} м" if "roof" in out else "")
            + f", ѕидови {len(walls)}, видени колони {len(params)}, површина {best['surf']}, клима {sum(len(p['ac']) for p in params)}, "
            f"балкони {sum(1 for p in params if p['balc'])}, кат {best['fh']:.2f} м, колона {best['bw']:.2f} м")
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
        if "cycle" in src[0]:                       # the nearest fitted building's columns (windows, balconies, ...) on every wall
            f.update(cycle=src[0]["cycle"], params=src[0]["params"], floor=src[0]["floor"], bay=src[0]["bay"],
                     surf=src[0]["surf"], rough=src[0]["rough"])
            if "roof" in src[0] and (src[0]["roof"]["kind"] in ("flat", "mansard")) == (not (b.kind() == "house" or b.area < 400)):
                f["roof"] = {k: v for k, v in src[0]["roof"].items() if k not in ("chim", "hous", "axis", "high")}   # world positions: its own
                f["roofc"] = src[0]["roofc"]
        t = b.tags
        if not t.get("height") and not t.get("building:levels"):          # OSM gives no height: the neighbours' fitted one
            hs = [s["h"] for s, o in zip(src, order) if 0.4 < done[same[o]].area / max(b.area, 1) < 2.5]
            if hs:
                f["h"] = round(float(np.median(hs)), 1)
        b.fits[algo] = f
        n += 1
    return n


def write_fits(blds, algo, path):
    """The game's file: only what differs from the generated look matters, the rest is for the viewer / later rounds."""
    out = {}
    for b in blds.values():
        f = b.fits.get(algo)
        if not f:
            continue
        e = {k: f[k] for k in ("h", "mat", "wallc", "roofc", "floor", "bay", "pitched", "src", "conf", "walls", "roof", "cycle",
                               "params", "surf", "rough") if k in f}
        out[str(b.id)] = e
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "algo": algo, "made": time.strftime("%Y-%m-%d %H:%M"), "buildings": out}, f, indent=0)
    os.replace(tmp, path)
    return len(out)


# ------------------------------------------------------------------------------------------------------------ the workers
_W = {}


def apply_settings(st, algo):
    """SETTINGS -> the module globals they drive (here and in facade)."""
    global RES
    import facade
    SETTINGS.update(st)
    facade.RES = float(SETTINGS["res"])
    facade.OPT.update(priors=bool(SETTINGS["priors"]), sym=bool(SETTINGS["sym"]))
    RES = facade.RES if algo == "detail" else 4.0


def _w_init(folder, osm_dir, algo, st):
    """A worker process: its own copy of the captures and the city (read once), the job's settings."""
    apply_settings(st, algo)
    caps = read_manifest(folder)
    _W.update(caps={c.file: c for c in caps}, blds=load_city(osm_dir, caps, log=lambda s: None), algo=algo)


def _levels(b):
    try:
        return float(str(b.tags.get("building:levels", "")).split(";")[-1])
    except ValueError:
        return 0.0


def _w_capture(file, x0, z0, mode, pk, lab):
    """One capture in a worker: true colours, camera pose (searched or saved), facade views; for ДЕТАЛИ every view is analysed
    here and only its numbers go back (Slim).  -> dict."""
    import facade
    t0 = time.time()
    c, blds = _W["caps"][file], _W["blds"]
    lines = []
    img = c.image()
    if _W["algo"] == "detail":                                       # true colours: haze veil off, the photo's own white point
        img, V, Wl = facade.restore(img, lab)
        lines.append(f"{file[:4]}: боја на снимката: измаглица {[int(v) for v in V]} одземена, бело {Wl:.0f} -> 255")
    c.x, c.z, c.dyaw, c.dpitch = x0, z0, 0.0, 0.0
    pose = None
    tgt = blds.get(c.bid)
    t1 = time.time()
    if mode == "file":
        r = (0.0, 0.0, 0.0, 1.0)
    elif pk:
        r = pk[:4]
        apply_pose(c, blds, *r, x0, z0)
        lines.append(f"{file[:4]}: камера од зачуваното ({r[0]:+.1f} м назад, {r[1]:+.1f} м десно, {r[2]:+.1f}°)")
    else:
        r = fit_position(c, lab, blds, lines.append, mode)
        pose = [round(float(v), 3) for v in r[:4]] + [mode]
    t2 = time.time()
    ui = lab == L_NONE
    edges = wall_edges(blds, np.array([c.x, c.z]), SETTINGS["dist"] + 20)
    views = facade_views(c, img, lab, ui, blds, edges, min_px=int(SETTINGS["min_px"]))
    t3 = time.time()
    if _W["algo"] == "detail":
        views = [Slim(o, _levels(o.bld), lines.append) for o in views]
    lines.append(f"{file[:4]}: време {time.time() - t0:.1f} с (боја {t1 - t0:.1f}, камера {t2 - t1:.1f}, ѕидови {t3 - t2:.1f}, "
                 f"анализа {time.time() - t3:.1f}), {len(views)} погледи")
    return {"x": float(c.x), "z": float(c.z), "dyaw": float(c.dyaw), "pose": pose, "log": lines, "views": views,
            "h_seen": float(tgt.gen["h"] * r[3]) if tgt is not None and r[3] != 1.0 else 0.0,
            "t": {"colour": t1 - t0, "pose": t2 - t1, "walls": t3 - t2, "analyse": time.time() - t3}}


class _Done:
    """A finished result from the job store, handled like a worker's future."""

    def __init__(self, r):
        self.r = r

    def result(self):
        return self.r

    def cancelled(self):
        return False

    def cancel(self):
        return False


def _read_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def job_store(folder, algo):
    return os.path.join(folder, CACHE, f"job_{algo}")


def job_signature(st, algo, seg_name):
    return {"algo": algo, "code": CODE_VER, "seg": seg_name, **{k: st[k] for k in RESULT_KEYS if k != "seg"}}


def _store_path(store, file):
    return os.path.join(store, os.path.splitext(file)[0] + ".pkl")


def _store_put(store, file, r):
    import pickle
    p = _store_path(store, file)
    with open(p + ".tmp", "wb") as f:
        pickle.dump(r, f, protocol=4)
    os.replace(p + ".tmp", p)                         # never a half-written file, even if the game is killed


def _store_get(store, file):
    import pickle
    p = _store_path(store, file)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:  # noqa: BLE001 - a broken file: that photo is simply redone
        return None


def job_status(folder, algo, st, seg_name=None):
    """(photos stored, signature matches the given settings) for the viewer."""
    store = job_store(folder, algo)
    if not os.path.isdir(store):
        return 0, True
    n = sum(1 for f in os.listdir(store) if f.endswith(".pkl"))
    old = _read_json(os.path.join(store, "job.json")).get("sig", {})
    same = all(old.get(k) == v for k, v in job_signature(st, algo, seg_name or old.get("seg")).items())
    return n, same


def clear_job(folder, algo, poses=True):
    """Forget the stored job (and the found camera poses): the next run starts from scratch."""
    import shutil
    shutil.rmtree(job_store(folder, algo), ignore_errors=True)
    if poses:
        try:
            os.remove(os.path.join(folder, CACHE, "poses.json"))
        except OSError:
            pass


def load_settings(folder):
    """-> (settings, opts) saved with the photo folder (defaults for what is missing or of the wrong type)."""
    d = _read_json(os.path.join(folder, CACHE, "settings.json"))
    st, op = dict(SETTINGS), json.loads(json.dumps(OPTS))
    def ok(v, ref):
        if isinstance(ref, float):
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        return type(v) is type(ref)
    st.update({k: (float(v) if isinstance(SETTINGS[k], float) else v) for k, v in d.items() if k in SETTINGS and ok(v, SETTINGS[k])})
    op.update({k: (float(v) if isinstance(OPTS[k], float) else v) for k, v in (d.get("opts") or {}).items() if k in OPTS and ok(v, OPTS[k])})
    return st, op


def save_settings(folder, st, op=None):
    os.makedirs(os.path.join(folder, CACHE), exist_ok=True)
    p = os.path.join(folder, CACHE, "settings.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump({**st, "opts": op if op is not None else OPTS}, f, indent=1, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def _kill(ex):
    """Stop the workers now (a running pose search or fit is not waited for)."""
    procs = list((getattr(ex, "_processes", None) or {}).values())
    ex.shutdown(wait=False, cancel_futures=True)
    for p in procs:
        try:
            p.terminate()
        except Exception:  # noqa: BLE001 - already gone
            pass


def _pool(folder, osm_dir, algo, log, st=None):
    """Worker processes on all cores but one (the GPU feeder / viewer); a single in-thread worker when processes fail."""
    import concurrent.futures as cf
    import multiprocessing as mp
    st = st or SETTINGS
    n = int(st.get("workers") or 0) or max(1, min(12, (os.cpu_count() or 2) - 1))
    main = sys.modules.get("__main__")
    mf = getattr(main, "__file__", None)
    try:
        if mf is not None:
            del main.__file__                              # spawned workers must not re-run main.py (it opens a window)
        ex = cf.ProcessPoolExecutor(n, mp_context=mp.get_context("spawn"), initializer=_w_init, initargs=(folder, osm_dir, algo, st))
        for f in [ex.submit(int, 0) for _ in range(n)]:    # start them all now, while main.py's name is hidden
            f.result()
        log(f"паралелно: {n} процеси (од {os.cpu_count()} јадра)")
        return ex, n
    except Exception as e:  # noqa: BLE001 - no processes: one worker thread
        log(f"паралелно: не може ({type(e).__name__}: {e}), една нишка")
        return cf.ThreadPoolExecutor(1, initializer=_w_init, initargs=(folder, osm_dir, algo, st)), 1
    finally:
        if mf is not None:
            main.__file__ = mf


# ------------------------------------------------------------------------------------------------------------ the job
class Job(threading.Thread):
    """Runs the pipeline for one folder and one algorithm; the viewer reads .caps / .blds / .log / .version while it works."""

    def __init__(self, folder, algo, texs=None, osm_dir=None, seg=None, state=None, pose=None, settings=None, only=None):
        super().__init__(daemon=True)
        self.folder, self.algo, self.texs = folder, algo, texs or {}
        self.osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
        self.settings = dict(SETTINGS, **(settings or {}))
        if seg:
            self.settings["seg"] = seg
        if pose:
            self.settings["pose"] = pose
        self.seg_kind = self.settings["seg"]
        self.only = set(only) if only else None      # proofing: only these photos (and the buildings they see)
        self.caps, self.blds = (state or (None, None))
        self.log_lines = []
        self.version = 0
        self.step, self.frac = "", 0.0
        self.done = False
        self.error = None
        self.stop = False
        self.pause = False
        self.pose = self.settings["pose"]  # "fast" | "full" search of the camera position, "file" = as the file says
        self.stats = {}                  # per stage seconds, photos from the store, ... (the viewer's status lines)
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
        apply_settings(self.settings, self.algo)
        self.log(f"поставки: {', '.join(f'{k}={v}' for k, v in self.settings.items())}")
        self.log(f"резолуција на фасадите: {RES:.0f} px/м")
        seg = segment.get(self.seg_kind, self.log)
        self.log(f"сегментација: {seg.name}")
        cache = os.path.join(self.folder, CACHE)
        os.makedirs(cache, exist_ok=True)
        caps = [c for c in self.caps if c.exists and (self.only is None or c.file in self.only)]
        if self.only is not None:
            self.log(f"ПРОБА: {len(caps)} избрани снимки, само зградите што тие ги гледаат")
        # the captures of one building one after the other, so it can be fitted (and shown) as soon as its last view is in
        caps.sort(key=lambda c: (c.bid, c.file))
        pose_path = os.path.join(cache, "poses.json")             # found poses are kept: a rebuild does not search again
        try:
            with open(pose_path, encoding="utf-8") as f:
                poses = json.load(f)
        except (OSError, ValueError):
            poses = {}
        # the stored job: each photo's result (numbers only) under a signature of the settings that shape it; a paused, stopped
        # or crashed run resumes from it, changed settings start a fresh one
        store = job_store(self.folder, self.algo)
        sig = job_signature(self.settings, self.algo, seg.name)
        if self.algo == "detail":
            old = _read_json(os.path.join(store, "job.json"))
            if old.get("sig") != sig:
                if old:
                    self.log("поставките се сменети: зачуваните резултати не важат, почнува ново")
                clear_job(self.folder, self.algo, poses=False)
            os.makedirs(store, exist_ok=True)
            with open(os.path.join(store, "job.json"), "w", encoding="utf-8") as f:
                json.dump({"sig": sig, "made": time.strftime("%Y-%m-%d %H:%M")}, f)
            nst = sum(1 for c in caps if os.path.exists(_store_path(store, c.file)))
            if nst:
                self.log(f"продолжува: {nst} од {len(caps)} снимки се веќе готови (зачувани)")
        t_start = time.time()
        # segmentation runs here (one GPU); pose search, facade views and fits run on the other cores, overlapped with it
        ex, nw = _pool(self.folder, self.osm_dir, self.algo, self.log, self.settings)
        cap_f = {}
        left = {}                                        # captures of each target not back yet
        for c in caps:
            left[c.bid] = left.get(c.bid, 0) + 1
        touched = set()
        nback = [0]

        def fit_one(bid):                                # numbers only by now (ДЕТАЛИ): quick, here
            b = self.blds[bid]
            b.fits[self.algo] = fit_building(b, b.obs, self.algo, self.texs, self.log)
            f = b.fits[self.algo]
            self.log(f"  зграда {bid}: {f['h']:.1f} м (од {b.gen['h']:.1f}), фасада {MATS.get(f.get('mat', b.gen['mat']))}"
                     + (f", кат {f['floor']:.2f} м, прозорец {f['bay']:.2f} м" if "floor" in f else "")
                     + (f", разлика {f['loss']:.2f}" if "loss" in f else ""))
            b.version += 1

        def drain(block=False):
            import concurrent.futures as cf
            allf = [f_ for f_ in cap_f if not isinstance(f_, _Done)]
            done = {f_ for f_ in cap_f if isinstance(f_, _Done)}
            if allf and not done:
                done, _ = cf.wait(allf, timeout=0.25 if block else 0, return_when=cf.FIRST_COMPLETED)   # short: stop stays quick
            for fu in done:
                c = cap_f.pop(fu)
                if fu.cancelled():
                    continue
                r = fu.result()
                if self.algo == "detail" and not r.get("stored"):
                    _store_put(store, c.file, r)
                for ln in r["log"]:
                    self.log(ln)
                for k_, v_ in (r.get("t") or {}).items():         # per-stage seconds over all workers (the viewer's ДНЕВНИК)
                    if not r.get("stored"):
                        self.stats[k_] = self.stats.get(k_, 0.0) + v_
                self.stats["stored" if r.get("stored") else "fresh"] = self.stats.get("stored" if r.get("stored") else "fresh", 0) + 1
                c.x, c.z, c.dyaw, c.dpitch = r["x"], r["z"], r["dyaw"], 0.0
                if r["pose"] is not None:
                    poses[c.file] = r["pose"]
                    with open(pose_path, "w", encoding="utf-8") as f:
                        json.dump(poses, f)
                if r["h_seen"] and c.bid in self.blds:
                    tb = self.blds[c.bid]
                    tb.h_seen = max(getattr(tb, "h_seen", 0.0), r["h_seen"])
                for o in r["views"]:
                    o.bld, o.cap = self.blds[o.bld.id], c
                    o.bld.obs.append(o)
                    touched.add(o.bld.id)
                tgt = sum(1 for o in r["views"] if o.bld.id == c.bid)
                c.status = f"{len(r['views'])} ѕида ({tgt} на целта)" if r["views"] else "ништо употребливо"
                self.log(f"{c.file[:4]}: {c.status}")
                left[c.bid] -= 1
                nback[0] += 1
                self.frac = nback[0] / max(1, len(caps))
                for bid in list(touched):          # every building whose own captures are all back
                    if left.get(bid, 0) <= 0:
                        touched.discard(bid)
                        fit_one(bid)
                self.version += 1

        for i, c in enumerate(caps):
            while self.pause and not self.stop:
                self.step = "пауза"
                drain()
                time.sleep(0.1)
            if self.stop:
                break
            if not hasattr(c, "x0"):
                c.x0, c.z0 = c.x, c.z
            if self.algo == "detail":
                r = _store_get(store, c.file)
                if r is not None:                         # done in an earlier (paused / stopped) run
                    r["stored"] = True
                    fu = _Done(r)
                    cap_f[fu] = c
                    drain()
                    continue
            self.step = f"снимка {i + 1}/{len(caps)}: сегментација ({nw} процеси работат)"
            self.version += 1
            ts = time.time()
            lp = os.path.join(cache, os.path.splitext(c.file)[0] + f".{seg.name}.png")
            lab = segment._cached(lp) if os.path.exists(lp) else None
            if lab is None or lab.shape != (c.H, c.W):
                lab = seg.labels(c.image(), lp)
            self.stats["seg"] = self.stats.get("seg", 0.0) + time.time() - ts
            self.labels[c.file] = lab
            lab = lab.copy()
            lab[c.ui_mask()] = L_NONE
            pk = poses.get(c.file)
            pk = pk if (pk and (pk[4] == "full" or pk[4] == self.pose)) else None
            cap_f[ex.submit(_w_capture, c.file, c.x0, c.z0, self.pose, pk, lab)] = c
            while len(cap_f) >= 2 * nw and not self.stop:   # a bounded queue: the views of many photos are big
                drain(True)
            drain()
        while cap_f and not self.stop:
            drain(True)
        if self.stop:                        # stop now: the workers are killed, what came back is fitted here
            self.log(f"застанато: {nback[0]} од {len(caps)} снимки готови, се довршуваат видените згради")
            cap_f.clear()
        _kill(ex)
        self.step = f"напасување на {len(touched)} згради"
        for bid in list(touched):
            fit_one(bid)
        self.step = "незабележани згради"
        n = infer(self.blds, self.algo) if self.only is None else 0
        for b in self.blds.values():
            b.version += 1
            b.obs = []                                   # free the resampled photos (the viewer keeps only numbers)
        self.log(f"изведени од соседи: {n}")
        out = os.path.join(cache, f"fit_{self.algo}" + ("_proof" if self.only is not None else "") + ".json")
        self.stats["total"] = time.time() - t_start
        k = write_fits(self.blds, self.algo, out)
        self.log(f"готово: {k} згради -> {out}")
        self.step, self.frac = "готово", 1.0


def apply_to_game(folder, algo, osm_dir=None, opts=None):
    """Copy a finished fit to <osm>/photogram.json: the next world build uses it (the setting decides, see set_enabled)."""
    import shutil
    osm_dir = osm_dir or os.path.join(ROOT, "data", "osm")
    src = os.path.join(folder, CACHE, f"fit_{algo}.json")
    dst = os.path.join(osm_dir, "photogram.json")
    if opts is None:
        shutil.copyfile(src, dst)
    else:                                                       # the element switches / kit go with the fit
        with open(src, encoding="utf-8") as f:
            d = json.load(f)
        d["opts"] = opts
        with open(dst + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, indent=0)
        os.replace(dst + ".tmp", dst)
    at = os.path.join(osm_dir, "photogram_atlas.png")          # an earlier version's photo-pixel atlas: no longer used
    if os.path.exists(at):
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
