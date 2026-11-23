"""Render the OSM network around a satellite screenshot through the vault's corridor engine (plan view + side view).
Roads: asphalt width from the OSM width tag, lanes from width, bridges / layer>0 lifted with ramped ends.  Plan coordinates are
(east, north); the mesh is mirrored to the game's (east, south) frame so north is up in the top view."""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shapely.geometry import Point
import corridor as C
from corridor import Plan, Road, K
import sat_overlay as S
from engine import WHITE, YELLOW

DRIVE = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street",
         "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
PRIO = {"motorway": 3, "trunk": 3, "primary": 2, "secondary": 2, "tertiary": 1}


def road_from(r, cx, cy, rid):
    pts = np.array([(x - cx, -(y - cy)) for x, y in r["pts"]], float)      # (east, north) relative to the site centre
    if len(pts) < 2:
        return None
    ln = float(np.hypot(*np.diff(pts, axis=0).T).sum())
    if ln < 4:
        return None
    ow = bool(r.get("ow"))
    w = float(r.get("w") or 6.0)
    drive = r["cls"] in DRIVE
    L = ln
    z = 0.0
    if r.get("bridge") or r.get("layer", 0) > 0:
        h = 6.2 * max(1, int(r.get("layer", 1) or 1)) if not r.get("tunnel") else 0.0
        rl = min(70.0, L * 0.38)
        z = K([(0, 0.0), (rl, h), (max(L - rl, rl + 1), h), (L, 0.0)]) if h else 0.0
    if drive:
        lanes = max(1, int(round(w / (3.3 if ow else 6.6))))
        half = w / 2
        rd = Road(f"{r['cls']}_{rid}", pts, lo=-half, hi=half, z=z, sh_lo=0.6, sh_hi=0.6, kind="cross", prio=PRIO.get(r["cls"].replace("_link", ""), 0), speed=50.0)
        rd.lines.append(dict(off=lambda s, rd=rd: rd.lo(s) + 0.25, kind="solid", col=WHITE))
        rd.lines.append(dict(off=lambda s, rd=rd: rd.hi(s) - 0.25, kind="solid", col=WHITE))
        if ow:
            for i in range(1, lanes):
                rd.lines.append(dict(off=-half + w * i / lanes, kind="dash", col=WHITE))
            for i in range(lanes):
                rd.cars.append((-half + w * (i + 0.5) / lanes, 0.25, 0))
        else:
            rd.lines.append(dict(off=0.0, kind="dbl" if lanes > 1 else "dash", col=YELLOW if lanes > 1 else WHITE, w=0.12))
            for i in range(1, lanes):
                rd.lines.append(dict(off=-lanes * 0 - i * (half / lanes), kind="dash", col=WHITE))
                rd.lines.append(dict(off=i * (half / lanes), kind="dash", col=WHITE))
            for i in range(lanes):
                rd.cars.append((-(i + 0.5) * half / lanes, 0.2, 0))
                rd.cars.append(((i + 0.5) * half / lanes, 0.2, 1))
        return rd
    rd = Road(f"{r['cls']}_{rid}", pts, lo=-max(1.0, w / 2), hi=max(1.0, w / 2), z=z, kind="cross", prio=0, col=(176, 172, 160))
    return rd


def plan_for(path, radius=105.0):
    lat, lng, mpp = S.parse(os.path.basename(path))
    from PIL import Image
    W = Image.open(path).size[0]
    s = mpp if mpp else 150.0 / W
    import geo
    cx, cy = geo.project(lat, lng)
    half = W * s * 0.5 + 40
    roads = []
    for i, r in enumerate(S.roads()):
        xs = [p[0] for p in r["pts"]]
        ys = [p[1] for p in r["pts"]]
        if max(xs) < cx - half or min(xs) > cx + half or max(ys) < cy - half or min(ys) > cy + half:
            continue
        if r["cls"] in ("footway", "path", "steps", "cycleway", "pedestrian", "track", "bridleway"):
            if r["w"] and r["w"] > 3.5 or not r.get("walk"):
                continue
        rd = road_from(r, cx, cy, i)
        if rd is not None:
            roads.append(rd)
    pl = Plan("osm", roads, extent=half + 40, seed=1, cars=True)
    pl.info.update(notrees=True, site=(lat, lng), scale=s, width_m=W * s, n_roads=len(roads))
    return pl


def render_views(path, r, size=(900, 900)):
    """Return (top view, side view) PIL images for the OSM roads around the screenshot."""
    import pyray as rl
    from PIL import Image
    pl = plan_for(path)
    W = Image.open(path).size[0]
    wm = pl.info["width_m"]
    m = C.build_plan(pl)
    P = np.array(m.P, np.float32)
    P[:, 2] *= -1.0                                  # (east, north) -> mesh (east, south)
    m.P = [p for p in P]
    # main road bearing: the highest-priority long road within 30 m of the centre
    best, bl = None, 0
    for rd in pl.roads:
        d = np.hypot(rd.pts[:, 0], rd.pts[:, 1]).min()
        if d < 35 and any(rd.name.startswith(c + "_") for c in DRIVE) and rd.L * (1 + rd.prio) > bl:
            best, bl = rd, rd.L * (1 + rd.prio)
    ang = 0.0
    if best is not None:
        i = int(np.argmin(np.hypot(best.pts[:, 0], best.pts[:, 1])))
        ang = float(best.Hd[min(i, len(best.Hd) - 1)])
    fov = 35.0
    top_h = (wm / 2) / math.tan(math.radians(fov / 2)) * 1.0
    import road_shot as rs
    import render as R
    out = []
    for kind in ("top", "side"):
        if kind == "top":
            eye, up = (0.0, top_h, 0.0), (0.0, 0.0, -1.0)
            tgt = (0.0, 0.0, 0.0)
        else:
            # perpendicular to the main road, south side looking along the plan so the deck profile shows
            nx, ny = -math.sin(ang), math.cos(ang)        # (east, north) normal
            dist = wm * 1.15
            eye = (nx * dist, 9.0, -ny * dist)
            tgt = (0.0, 3.0, 0.0)
            up = (0.0, 1.0, 0.0)
        pos = np.array(m.P, np.float32)
        col = np.array(m.C, np.uint8)
        models = rs.model(pos, col)
        cam = rl.Camera3D(eye, tgt, up, fov, rl.CAMERA_PERSPECTIVE)
        rl.rl_set_clip_planes(1.0, 3000.0)
        rl.begin_texture_mode(r.rt)
        rl.clear_background((190, 212, 236, 255))
        rl.begin_mode_3d(cam)
        rl.rl_disable_backface_culling()
        for mo in models:
            rl.draw_model(mo, (0, 0, 0), 1.0, rl.WHITE)
        rl.end_mode_3d()
        rl.end_texture_mode()
        img = rl.load_image_from_texture(r.rt.texture)
        rl.image_flip_vertical(img)
        tmp = f"/tmp/_osm_{os.getpid()}.png"
        rl.export_image(img, tmp)
        rl.unload_image(img)
        for mo in models:
            rl.unload_model(mo)
        out.append(Image.open(tmp).convert("RGB"))
    return out[0], out[1], pl
