"""Dev tool: renders of the 3D road network around chosen points, straight from a roads-only dump (no world build):
the road mesh of tools/roads3d.py (asphalt, pavements, markings, bridge decks, piers) on the real terrain, with plain
extruded buildings for context.  OpenGL through raylib (works under xvfb-run with software GL).

    SK242_ROADS_ONLY=dump.pkl python tools/build_world.py --src data/osm --out <any>
    xvfb-run -a python tools/road_shot.py dump.pkl shots.json out_dir

shots.json: [{"name": "a", "x": .., "y": .., "r": 140, "views": [[az_deg, elev_deg, dist_m], ...], "fov": 45}]
(views look at (x, y) from the compass bearing az (0 = north, 90 = east) at elevation elev, from dist metres).
Writes out_dir/<name>_<k>.png."""
import json
import math
import os
import pickle
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "src"))
import pyray as rl  # noqa: E402

ffi = rl.ffi
SUN = np.array([-0.45, 0.80, -0.40])
SUN = SUN / np.linalg.norm(SUN)


def road_mesh(dump, x, y, r):
    """Road triangles (n*3, 3) + colours (n*3, 4) of every edge reaching within r of (x, y), plus the edges joining them."""
    import roads3d
    E = dump["edges"]

    def near(e):                                                   # any point of the polyline (not just its vertices)
        P = np.asarray(e["pts"], np.float64)
        if len(P) > 1:
            t = np.linspace(0, 1, 9)[:, None, None]
            P = (P[:-1] + (P[1:] - P[:-1]) * t).reshape(-1, 2)
        return bool(((abs(P[:, 0] - x) < r + 30) & (abs(P[:, 1] - y) < r + 30)).any())
    sel = {i for i, e in enumerate(E) if (e["drive"] or e["walk"]) and near(e)}
    nodes = {E[i]["a"] for i in sel} | {E[i]["b"] for i in sel}
    sel |= {i for i, e in enumerate(E) if (e["drive"] or e["walk"]) and (e["a"] in nodes or e["b"] in nodes)}
    edges = [dict(E[i]) for i in sorted(sel)]
    got = []
    roads3d.PIER_SKIP = lambda *_a: False
    old = roads3d.par.jobs
    roads3d.par.jobs = lambda: 1                                   # small window: no worker pool
    try:
        roads3d.build(edges, [], lambda key, mat, pos, uv, col: got.append((pos, col)), lambda a, b: (int(a // 120), int(b // 120)), 3,
                      T=dump["T"], decks=dump["decks"])
    finally:
        roads3d.par.jobs = old
    up = [p for p in dump.get("upass") or [] if (abs(np.asarray(p["pts"])[:, 0] - x) < r + 60).any() and (abs(np.asarray(p["pts"])[:, 1] - y) < r + 60).any()]
    if up:                                                         # underpass roofs, cutting walls and parapets, as the game adds them
        import underpass
        if os.environ.get("SK242_DESIGNER") == "1":               # as build_world does before the roofs
            up = [dict(p) for p in up]
            underpass.open_under_decks(up, E)
        underpass.roof(up, lambda key, mat, pos, uv, col: got.append((pos, col)), lambda a, b: (int(a // 120), int(b // 120)), 0, dump["T"])
    if not got:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.uint8)
    return (np.concatenate([np.asarray(p, np.float32).reshape(-1, 3) for p, _ in got]),
            np.concatenate([np.asarray(c, np.uint8).reshape(-1, 4) for _, c in got]))


def terrain_mesh(T, x, y, r, st=2.0):
    gx = np.arange(x - r, x + r + st, st)
    gy = np.arange(y - r, y + r + st, st)
    X, Y = np.meshgrid(gx, gy)
    H = T.h(X, Y) - 0.02
    P = np.stack([X, H, Y], -1).astype(np.float32)
    a, b, c, d = P[:-1, :-1], P[:-1, 1:], P[1:, 1:], P[1:, :-1]
    tri = np.concatenate([np.stack([a, c, b], -2).reshape(-1, 3, 3), np.stack([a, d, c], -2).reshape(-1, 3, 3)])
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    n *= np.sign(n[:, 1:2] + 1e-9)
    lit = 0.55 + 0.45 * np.clip(n @ SUN, 0, 1)
    slope = 1 - n[:, 1]
    base = np.array([150, 172, 112]) * (1 - np.clip(slope * 3, 0, 1))[:, None] + np.array([150, 138, 116]) * np.clip(slope * 3, 0, 1)[:, None]
    col = np.clip(base * lit[:, None], 0, 255).astype(np.uint8)
    col = np.repeat(np.concatenate([col, np.full((len(col), 1), 255, np.uint8)], 1), 3, 0)
    return tri.reshape(-1, 3), col


def building_mesh(dump, T, x, y, r):
    P, C = [], []
    for ring, h in dump.get("buildings", ()):
        if not ring or abs(ring[0][0] - x) > r + 20 or abs(ring[0][1] - y) > r + 20:
            continue
        base = min(float(T.hs(*q)) for q in ring)
        top = base + float(h)
        n = len(ring)
        for k in range(n):
            (ax, ay), (bx, by) = ring[k], ring[(k + 1) % n]
            nx, nz = by - ay, -(bx - ax)
            ln = math.hypot(nx, nz) or 1.0
            lit = 0.6 + 0.4 * max(0.0, (nx * SUN[0] + nz * SUN[2]) / ln)
            c = [int(205 * lit), int(198 * lit), int(188 * lit), 255]
            P += [(ax, base, ay), (bx, base, by), (bx, top, by), (ax, base, ay), (bx, top, by), (ax, top, ay)]
            C += [c] * 6
        try:
            import mapbox_earcut as earcut
            v = np.array(ring, np.float64)
            idx = earcut.triangulate_float64(v, np.array([len(ring)], np.uint32))
            for t in idx:
                P.append((v[t][0], top, v[t][1]))
                C.append([176, 170, 162, 255])
        except Exception:  # noqa: BLE001
            pass
    if not P:
        return np.zeros((0, 3), np.float32), np.zeros((0, 4), np.uint8)
    return np.array(P, np.float32), np.array(C, np.uint8)


def model(pos, col):
    pos = np.ascontiguousarray(pos, np.float32)
    col = np.ascontiguousarray(col, np.uint8)
    out, keep = [], []
    step = 3 * 400000
    for s in range(0, len(pos) - len(pos) % 3, step):
        p, c = pos[s:s + step].copy(), col[s:s + step].copy()
        if len(p) < 3:
            continue
        m = rl.Mesh()
        m.vertexCount = len(p)
        m.triangleCount = len(p) // 3
        m.vertices = ffi.cast("float *", ffi.from_buffer(p))
        m.colors = ffi.cast("unsigned char *", ffi.from_buffer(c))
        rl.upload_mesh(ffi.addressof(m), False)
        m.vertices = ffi.NULL
        m.colors = ffi.NULL
        out.append(rl.load_model_from_mesh(m))
    return out


def both_sides(pos, col):
    """The road mesh has single-sided faces in both windings; draw everything double-sided for the sketch."""
    t = pos.reshape(-1, 3, 3)
    return np.concatenate([pos, t[:, ::-1].reshape(-1, 3)]), np.concatenate([col, col.reshape(-1, 3, 4)[:, ::-1].reshape(-1, 4)])


def render(dump, shots, out_dir, size=(1400, 900)):
    os.makedirs(out_dir, exist_ok=True)
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN | rl.FLAG_MSAA_4X_HINT)
    rl.init_window(size[0], size[1], "road_shot")
    rt = rl.load_render_texture(size[0], size[1])
    T = dump["T"]
    files = []
    for sh in shots:
        x, y, r = sh["x"], sh["y"], sh.get("r", 140.0)
        rp, rc = road_mesh(dump, x, y, r)
        tp, tc = terrain_mesh(T, x, y, r + 60, 1.0 if r <= 130 else 2.0)
        bp, bc = building_mesh(dump, T, x, y, r + 40) if sh.get("buildings", True) else (np.zeros((0, 3), np.float32), np.zeros((0, 4), np.uint8))
        rp, rc = both_sides(rp, rc)
        models = model(tp, tc) + model(bp, bc) + model(rp, rc)
        g = float(T.hs(x, y)) + sh.get("dh", 0.0)
        for k, (az, el, dist) in enumerate(sh.get("views", [[200, 35, 120]])):
            a, e = math.radians(az), math.radians(el)
            eye = (x + math.sin(a) * math.cos(e) * dist, g + math.sin(e) * dist, y - math.cos(a) * math.cos(e) * dist)
            cam = rl.Camera3D(eye, (x, g, y), (0, 1, 0), sh.get("fov", 45.0), rl.CAMERA_PERSPECTIVE)
            rl.begin_texture_mode(rt)
            rl.clear_background((196, 214, 232, 255))
            rl.rl_set_clip_planes(0.5, 4000.0) if hasattr(rl, "rl_set_clip_planes") else None    # before begin_mode_3d: it builds the projection
            rl.begin_mode_3d(cam)
            for m in models:
                rl.draw_model(m, (0, 0, 0), 1.0, rl.WHITE)
            rl.end_mode_3d()
            rl.end_texture_mode()
            img = rl.load_image_from_texture(rt.texture)
            rl.image_flip_vertical(img)
            fn = os.path.join(out_dir, f"{sh['name']}_{k}.png")
            rl.export_image(img, fn)
            rl.unload_image(img)
            files.append(fn)
        for m in models:
            rl.unload_model(m)
        print(f"[shot] {sh['name']}: {len(rp) // 3} road triangles")
    rl.close_window()
    return files


def main():
    dump = pickle.load(open(sys.argv[1], "rb"))
    shots = json.load(open(sys.argv[2]))
    render(dump, shots, sys.argv[3])


if __name__ == "__main__":
    main()
