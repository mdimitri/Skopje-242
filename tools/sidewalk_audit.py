"""Looks for badly merged pavements / junctions in a built world by rasterising the road mesh (material 3) top-down around
every junction and testing the picture against the routing graph.  Per junction window it counts, in m2:
  zfight   pavement and asphalt faces stacked within 4 cm (flicker)
  inlane   pavement sitting inside the drivable width of a road
  hole     nothing drawn inside a road's width + its pavement (the ground shows through)
  spike    triangles with an edge > 25 m or long and razor thin (a mis-joined polygon)
Usage: python3 tools/sidewalk_audit.py <world_dir> <out.json> [--png dir] [--max N] [--sharp] [--local]\n  --sharp: only junctions with an angle < 55 deg;  --local: rebuild the mesh from the current roads3d.py instead of reading the world's"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

PX = 0.2                                   # metres per pixel
R = 26.0                                   # window half size
SW_W = 2.0
CHUNK = 120.0
SIDEWALK = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "primary_link", "secondary_link", "tertiary_link", "trunk_link", "living_street"}


def load_tris(world, cx, cy, r):
    """Triangles (n,3,3) = x, y_up, z and colours (n,3) of material 3 in the chunks touching the window."""
    ps, cs = [], []
    for kx in range(int(math.floor((cx - r) / CHUNK)), int(math.floor((cx + r) / CHUNK)) + 1):
        for ky in range(int(math.floor((cy - r) / CHUNK)), int(math.floor((cy + r) / CHUNK)) + 1):
            ch = world.chunks.get((kx, ky))
            if not ch or 3 not in ch["m"]:
                continue
            off, n = ch["m"][3]
            pos, _uv, col = world.mesh_arrays(off, n)
            ps.append(np.array(pos).reshape(-1, 3, 3))
            cs.append(np.array(col).reshape(-1, 3, 4)[:, 0, :3])
    if not ps:
        return np.zeros((0, 3, 3), np.float32), np.zeros((0, 3), np.uint8)
    return np.concatenate(ps), np.concatenate(cs)


def local_tris(world, cx, cy, r):
    """Rebuilds the road mesh of the window from the world's own edges with the current tools/roads3d.py (flat terrain, heights
    relative to the ground): a few seconds, so a change to the pavement code can be judged without a 5 minute world build."""
    import roads3d
    sel = {i for i, e in enumerate(world.edges) if (e["drive"] or e["walk"]) and not e["bridge"]
           and any(abs(q[0] - cx) < r + 45 and abs(q[1] - cy) < r + 45 for q in e["pts"])}
    nodes = {world.edges[i]["a"] for i in sel} | {world.edges[i]["b"] for i in sel}
    sel |= {i for i, e in enumerate(world.edges) if (e["drive"] or e["walk"]) and not e["bridge"] and (e["a"] in nodes or e["b"] in nodes)}
    edges = [dict(world.edges[i]) for i in sorted(sel)]
    got = []
    roads3d.build(edges, [], lambda key, mat, pos, uv, col: got.append((pos, col)), lambda x, z: (0, 0), 3, T=None, decks=None)
    if not got:
        return np.zeros((0, 3, 3), np.float32), np.zeros((0, 3), np.uint8)
    return np.concatenate([g[0] for g in got]).reshape(-1, 3, 3), np.concatenate([g[1] for g in got]).reshape(-1, 3, 4)[:, 0, :3]


def is_pavement(col):
    c = col.astype(int)
    return (c[:, 0] - c[:, 2] >= 8) & (c[:, 0] - c[:, 2] <= 18) & (c[:, 0] >= 120) & (c[:, 0] <= 215) & (abs(c[:, 0] - c[:, 1]) <= 8)


def is_asphalt(col):
    c = col.astype(int)
    return (c[:, 2] - c[:, 0] >= 2) & (c[:, 0] <= 140) & (c[:, 2] >= 60)


def raster(tris, cols, cx, cy, n):
    """Top faces into: height of the highest face per pixel, pavement mask, asphalt mask, coverage, rgb picture."""
    H = np.full((n, n), -1e9, np.float32)
    HP = np.full((n, n), -1e9, np.float32)
    HA = np.full((n, n), -1e9, np.float32)
    cov = np.zeros((n, n), bool)
    img = np.zeros((n, n, 3), np.uint8)
    pav, asp = is_pavement(cols), is_asphalt(cols)
    nrm_y = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])[:, 1]
    for t in range(len(tris)):
        if abs(nrm_y[t]) < 1e-6:
            continue
        a, b, c = tris[t]
        xs = np.array([a[0], b[0], c[0]])
        zs = np.array([a[2], b[2], c[2]])
        x0, x1 = int((xs.min() - cx + R) / PX), int((xs.max() - cx + R) / PX) + 1
        z0, z1 = int((zs.min() - cy + R) / PX), int((zs.max() - cy + R) / PX) + 1
        if x1 < 0 or z1 < 0 or x0 >= n or z0 >= n or (x1 - x0) * (z1 - z0) > 40000:
            continue
        x0, z0, x1, z1 = max(x0, 0), max(z0, 0), min(x1, n), min(z1, n)
        gx, gz = np.meshgrid(cx - R + (np.arange(x0, x1) + 0.5) * PX, cy - R + (np.arange(z0, z1) + 0.5) * PX)
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        if abs(d) < 1e-9:
            continue
        l1 = ((b[2] - c[2]) * (gx - c[0]) + (c[0] - b[0]) * (gz - c[2])) / d
        l2 = ((c[2] - a[2]) * (gx - c[0]) + (a[0] - c[0]) * (gz - c[2])) / d
        l3 = 1.0 - l1 - l2
        ins = (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02)
        if not ins.any():
            continue
        hh = l1 * a[1] + l2 * b[1] + l3 * c[1]
        sl = (slice(z0, z1), slice(x0, x1))
        up = nrm_y[t] > 0
        if up:
            cov[sl] |= ins
            if pav[t]:
                HP[sl] = np.where(ins, np.maximum(HP[sl], hh), HP[sl])
            if asp[t]:
                HA[sl] = np.where(ins, np.maximum(HA[sl], hh), HA[sl])
            better = ins & (hh >= H[sl])
            H[sl] = np.where(better, hh, H[sl])
            img[sl][better] = cols[t]
    return H, HP, HA, cov, img


def corridor(world, cx, cy, n):
    """Masks of the pixels inside the drivable width (lane) and inside width + pavement, from the routing graph."""
    lane = np.zeros((n, n), bool)
    span = np.zeros((n, n), bool)
    gx, gz = np.meshgrid(cx - R + (np.arange(n) + 0.5) * PX, cy - R + (np.arange(n) + 0.5) * PX)
    for ei, e in enumerate(world.edges):
        if not e["drive"]:
            continue
        pts = e["pts"]
        if max(p[0] for p in pts) < cx - R - 12 or min(p[0] for p in pts) > cx + R + 12 or max(p[1] for p in pts) < cy - R - 12 or min(p[1] for p in pts) > cy + R + 12:
            continue
        hw = e["w"] / 2
        sw = SW_W if e["cls"].replace("_link", "") in {c.replace("_link", "") for c in SIDEWALK} and not e["bridge"] else 0.0
        for i in range(len(pts) - 1):
            ax, ay, bx, by = pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            if ll < 1e-9:
                continue
            t = np.clip(((gx - ax) * dx + (gz - ay) * dy) / ll, 0.0, 1.0)
            dist = np.hypot(gx - ax - dx * t, gz - ay - dy * t)
            lane |= dist < hw - 0.5
            span |= dist < hw + sw - 0.4
    return lane, span


def junction_windows(world, sharp_only):
    deg = {}
    for ei, e in enumerate(world.edges):
        if e["drive"]:
            deg.setdefault(e["a"], []).append((ei, 0))
            deg.setdefault(e["b"], []).append((ei, 1))
    out = []
    for node, lst in deg.items():
        if len(lst) < 3:
            continue
        angs = []
        for ei, end in lst:
            p = world.edges[ei]["pts"]
            a, b = (p[0], p[min(len(p) - 1, 2)]) if end == 0 else (p[-1], p[max(0, len(p) - 3)])
            angs.append(math.atan2(b[1] - a[1], b[0] - a[0]))
        angs.sort()
        gaps = [(angs[(i + 1) % len(angs)] - angs[i]) % (2 * math.pi) for i in range(len(angs))]
        sharp = min(gaps) < math.radians(55)
        if sharp_only and not sharp:
            continue
        e0 = world.edges[lst[0][0]]
        pt = e0["pts"][0] if lst[0][1] == 0 else e0["pts"][-1]
        out.append((node, pt[0], pt[1], len(lst), round(math.degrees(min(gaps)))))
    return out


def audit(world, cx, cy, png=None, tag="", local=False):
    n = int(2 * R / PX)
    tris, cols = local_tris(world, cx, cy, R + 4) if local else load_tris(world, cx, cy, R + 4)
    res = dict(zfight=0.0, inlane=0.0, hole=0.0, spike=0)
    if not len(tris):
        return res
    H, HP, HA, cov, img = raster(tris, cols, cx, cy, n)
    px2 = PX * PX
    both = (HP > -1e8) & (HA > -1e8) & (abs(HP - HA) < 0.04)
    lane, span = corridor(world, cx, cy, n)
    pav_px = HP > -1e8
    inlane = pav_px & lane & ~(HA > HP + 0.05)               # pavement not buried under asphalt that is clearly higher
    hole = span & ~cov
    res["zfight"], res["inlane"], res["hole"] = round(both.sum() * px2, 1), round(inlane.sum() * px2, 1), round(hole.sum() * px2, 1)
    ed = np.maximum.reduce([np.hypot(*(tris[:, i, [0, 2]] - tris[:, (i + 1) % 3, [0, 2]]).T) for i in range(3)])
    u, v = tris[:, 1, [0, 2]] - tris[:, 0, [0, 2]], tris[:, 2, [0, 2]] - tris[:, 0, [0, 2]]
    ar = 0.5 * abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
    inwin = (abs(tris[:, :, 0].mean(1) - cx) < R) & (abs(tris[:, :, 2].mean(1) - cy) < R)
    thin = (ed > 6.0) & (2 * ar / np.maximum(ed, 1e-6) < 0.05)
    res["spike"] = int((inwin & ((ed > 25.0) | thin)).sum())
    if png:
        rgb = img.copy()
        rgb[hole] = (255, 0, 255)
        rgb[inlane] = (255, 128, 0)
        rgb[both] = (255, 0, 0)
        from PIL import Image
        Image.fromarray(rgb[::-1]).resize((n * 3, n * 3), Image.NEAREST).save(os.path.join(png, f"{tag}.png"))
    return res


if __name__ == "__main__":
    from world import World
    wd, outp = sys.argv[1], sys.argv[2]
    LOCAL = "--local" in sys.argv
    png = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 10 ** 9
    if png:
        os.makedirs(png, exist_ok=True)
    w = World(wd, lambda f, note="": None)
    wins = junction_windows(w, "--sharp" in sys.argv)[:mx]
    rows = []
    for node, x, y, deg, ang in wins:
        r = audit(w, x, y, local=LOCAL)
        r.update(node=node, x=round(x), y=round(y), deg=deg, min_angle=ang)
        rows.append(r)
    rows.sort(key=lambda r: -(r["zfight"] + r["inlane"] + 2 * r["hole"] + 5 * r["spike"]))
    if png:
        for r in rows[:12]:
            audit(w, r["x"], r["y"], png, f"n{r['node']}_{r['x']}_{r['y']}", local=LOCAL)
    json.dump(rows, open(outp, "w"), ensure_ascii=False)
    tot = {k: round(sum(r[k] for r in rows), 1) for k in ("zfight", "inlane", "hole", "spike")}
    bad = sum(1 for r in rows if r["zfight"] + r["inlane"] + r["hole"] > 3 or r["spike"])
    print(f"{len(rows)} junctions, {bad} with defects; totals {tot}")
    for r in rows[:10]:
        print(r)
