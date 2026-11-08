"""Demo skyline: every building of the city as a plain extruded footprint (walls + roof, flat vertex colours), merged per
4x4-chunk block.  The arrays are made on a worker thread, uploaded a few blocks a frame; the renderer draws a block of them
until the streamer has the real (merged) meshes of that block, so no distant area is ever an empty street map."""
import math
import threading

import numpy as np

import gl3d
from bake import BLOCK, _sphere

WALL = [(206, 198, 182), (190, 172, 152), (172, 164, 154), (200, 186, 166), (168, 128, 106), (182, 182, 178), (214, 206, 190)]
ROOF = [(150, 96, 82), (126, 126, 132), (160, 110, 90), (110, 110, 116)]


def _arrays(world):
    """-> {block key: (pos float32 (n,3), col uint8 (n,4))}; pure numpy, safe on a thread."""
    S = world.chunk * BLOCK
    acc = {}
    up = np.array([0.0, 1.0, 0.0])
    roof_k = float(gl3d._shade(up))
    for bi, b in enumerate(world.buildings):
        ring = b["ring"]
        m = len(ring)
        if m < 3:
            continue
        h = float(b["h"])
        if h < 2.5:
            continue
        P = np.asarray(ring, np.float64)
        cx, cz = P.mean(0)
        y0 = float(world.ground_y(cx, cz)) - 2.0
        y1 = y0 + h + 2.0
        Q = np.roll(P, -1, 0)
        d = Q - P
        ln = np.hypot(d[:, 0], d[:, 1]) + 1e-9
        n = np.stack([d[:, 1] / ln, np.zeros(m), -d[:, 0] / ln], 1)
        sh = np.array([float(gl3d._shade(nn)) for nn in n])          # each wall's own light, like the real meshes
        wc = np.array(WALL[bi % len(WALL)], np.float32)
        wall = np.empty((m, 6, 3), np.float32)
        wall[:, 0, 0], wall[:, 0, 1], wall[:, 0, 2] = P[:, 0], y0, P[:, 1]
        wall[:, 1, 0], wall[:, 1, 1], wall[:, 1, 2] = Q[:, 0], y0, Q[:, 1]
        wall[:, 2, 0], wall[:, 2, 1], wall[:, 2, 2] = Q[:, 0], y1, Q[:, 1]
        wall[:, 3] = wall[:, 0]
        wall[:, 4] = wall[:, 2]
        wall[:, 5, 0], wall[:, 5, 1], wall[:, 5, 2] = P[:, 0], y1, P[:, 1]
        wcol = np.empty((m, 6, 4), np.uint8)
        wcol[:, :, :3] = np.clip(wc[None, None, :] * sh[:, None, None], 0, 255)
        wcol[:, :, 3] = 255
        tri = np.asarray(b["tri"], np.int64)
        rv = np.stack([P[tri, 0], np.full(len(tri), y1), P[tri, 1]], 1).astype(np.float32)
        rc = np.empty((len(tri), 4), np.uint8)
        rc[:, :3] = np.clip(np.array(ROOF[bi % len(ROOF)], np.float32) * roof_k, 0, 255)
        rc[:, 3] = 255
        key = (math.floor(cx / S), math.floor(cz / S))
        a = acc.setdefault(key, ([], []))
        a[0] += [wall.reshape(-1, 3), rv]
        a[1] += [wcol.reshape(-1, 4), rc]
    return {k: (np.concatenate(v[0]), np.concatenate(v[1])) for k, v in acc.items()}


class Skyline:
    def __init__(self, world, streamer):
        self.w, self.st = world, streamer
        self.models = {}                  # block key -> [model, sphere]
        self._arr = None
        self._thread = None
        self.error = None

    def start(self):
        """Begin making the arrays (once)."""
        if self._thread is None and not self.models:
            def work():
                try:
                    self._arr = _arrays(self.w)
                except Exception as e:  # noqa: BLE001 - no skyline rather than no demo
                    self.error = e
                    self._arr = {}
            self._thread = threading.Thread(target=work, daemon=True)
            self._thread.start()

    def update(self, per_frame=6):
        """Upload a few blocks a frame (main thread)."""
        if not self._arr:
            return
        for _ in range(per_frame):
            if not self._arr:
                break
            key, (pos, col) = self._arr.popitem()
            m = gl3d.make_model(pos, np.zeros((len(pos), 2), np.float32), col)
            if m is not None:
                S = self.w.chunk * BLOCK
                self.models[key] = [m, _sphere(key[0] * S, key[1] * S, (key[0] + 1) * S, (key[1] + 1) * S, float(pos[:, 1].min()), float(pos[:, 1].max()))]
