"""Real-time sun shadows. The sun follows the game clock over Skopje; buildings, trees and street furniture are drawn
once into a small depth map seen from the sun (depth packed into two colour channels), and the ground, road and facade
shaders (gl3d.sunShadow) look it up. The map only covers the area around the camera and is redrawn when the camera has
moved a long way, when the sun has moved a little, or when new chunk meshes arrive, so most frames cost nothing extra."""
import math

import numpy as np
import pyray as rl

import gl3d

ffi = rl.ffi
LAT = math.radians(41.9973)         # Skopje
DECL = math.radians(18.0)           # sun declination: a late-spring / early-autumn day, ~14 h of daylight
NOON = 13.0                         # solar noon in game (local summer) time
MIN_ELEV = math.radians(7.0)        # shadows never get longer than ~8x the height; the sun is faded out below this
SIZE = 2048                         # shadow map resolution
HALF = 150.0                        # the map covers 300 m x 300 m of ground around the camera
RECENTER = 40.0                     # redraw when the camera has moved this far from the centre of the map
SUN_STEP = 0.004                    # redraw when the sun direction changed by this much (about 0.25 degrees)
BIAS_M = 0.35                       # depth bias in metres
SKIP_MATS = (3, 6)                  # road surface and graffiti decals cast no shadow

DEPTH_VS = """#version 330
in vec3 vertexPosition;
uniform mat4 mvp;
out float dz;
void main(){ gl_Position = mvp * vec4(vertexPosition, 1.0); dz = gl_Position.z * 0.5 + 0.5; }"""
DEPTH_FS = """#version 330
in float dz;
out vec4 finalColor;
void main(){ float d = clamp(dz, 0.0, 1.0) * 255.0; finalColor = vec4(floor(d) / 255.0, fract(d), 0.0, 1.0); }"""


def sun_at(hour):
    """(unit vector towards the sun in world axes x = east, y = up, z = south; elevation in radians) at a game hour."""
    h = math.radians(15.0 * (hour - NOON))
    se = math.sin(LAT) * math.sin(DECL) + math.cos(LAT) * math.cos(DECL) * math.cos(h)
    e = math.asin(max(-1.0, min(1.0, se)))
    ce = math.cos(e)
    az = math.atan2(-math.cos(DECL) * math.sin(h) / ce, (math.sin(DECL) - se * math.sin(LAT)) / (ce * math.cos(LAT)))
    ee = max(e, MIN_ELEV)                                   # keep the direction usable below the horizon (strength is 0 there)
    return np.array([math.cos(ee) * math.sin(az), math.sin(ee), -math.cos(ee) * math.cos(az)]), e


def _strength(e):
    t = min(1.0, max(0.0, (e - math.radians(2.0)) / math.radians(8.0)))
    return 0.92 * t * t * (3.0 - 2.0 * t)


def _look_at(eye, target):
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, (0.0, 1.0, 0.0))
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    V = np.eye(4)
    V[0, :3], V[1, :3], V[2, :3] = r, u, -f
    V[:3, 3] = -V[:3, :3] @ eye
    return V


def _ortho(l, r, b, t, n, f):
    P = np.eye(4)
    P[0, 0], P[1, 1], P[2, 2] = 2 / (r - l), 2 / (t - b), -2 / (f - n)
    P[0, 3], P[1, 3], P[2, 3] = -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n)
    return P


def _mat(M):
    return rl.Matrix(*[float(x) for x in M.ravel()])


class SunShadow:
    def __init__(self, world, streamer):
        self.world, self.st = world, streamer
        self.enabled = True
        self.ok = False
        self.center = None
        self.L = None
        self.loaded = -1
        self.strength = 0.0
        try:
            self.rt = rl.load_render_texture(SIZE, SIZE)
            rl.set_texture_filter(self.rt.texture, rl.TEXTURE_FILTER_POINT)
            rl.set_texture_wrap(self.rt.texture, rl.TEXTURE_WRAP_CLAMP)
            sh = rl.load_shader_from_memory(DEPTH_VS, DEPTH_FS)
            if not sh.id or sh.id == rl.rl_get_shader_id_default():
                raise RuntimeError("depth shader did not compile")
            self.mat = rl.load_material_default()
            self.mat.shader = sh
            self.cam = rl.Camera3D(rl.Vector3(0, 10, 0), rl.Vector3(0, 0, 0), rl.Vector3(0, 1, 0), 30.0, rl.CAMERA_PERSPECTIVE)
            gl3d.SHADOW_TEX = self.rt.texture               # models made from now on bind it (gl3d.apply_*_detail)
            self.ok = True
        except Exception as e:  # noqa: BLE001 - no shadows rather than no game
            print(f"[gfx] sun shadows off: {e}")

    def update(self, hour, cx, cz, dark=0.0):
        """Call once per frame before drawing (outside any texture mode): moves the sun and redraws the map when needed."""
        if not (self.ok and self.enabled):
            if self.strength:
                self.strength = 0.0
                gl3d.set_sun(self.L if self.L is not None else gl3d.SUN, 0.0, np.eye(4), 1.0 / SIZE, 0.0)
            return
        L, e = sun_at(hour)
        k = _strength(e) * max(0.0, 1.0 - 1.6 * dark)      # no sun shadows once the game clock says it is getting dark
        redraw = (self.center is None or self.L is None or np.abs(L - self.L).max() > SUN_STEP
                  or math.hypot(cx - self.center[0], cz - self.center[1]) > RECENTER
                  or self.st.mesh_loaded != self.loaded)
        if not redraw:
            if abs(k - self.strength) > 0.01:                # the strength fades slowly at dawn and dusk
                self.strength = k
                gl3d.set_sun(self.L, k, self.vp, 1.0 / SIZE, self.bias)
            return
        self.L, self.center, self.loaded, self.strength = L, (cx, cz), self.st.mesh_loaded, k
        w = self.world
        gy = float(w.ground_y(cx, cz))
        pts = np.array([(cx + sx * HALF, gy + dy, cz + sz * HALF) for sx in (-1, 1) for sz in (-1, 1) for dy in (-30.0, 120.0)])
        V = _look_at(np.array([cx, gy, cz]) + L * 500.0, np.array([cx, gy, cz]))
        q = (V[:3, :3] @ pts.T).T + V[:3, 3]
        near, far = -q[:, 2].max() - 250.0, -q[:, 2].min() + 5.0         # 250 m more towards the sun: tall blocks outside the map still cast in
        P = _ortho(q[:, 0].min(), q[:, 0].max(), q[:, 1].min(), q[:, 1].max(), near, far)
        self.vp, self.bias = P @ V, BIAS_M / (far - near)
        self._draw_depth(_mat(V), _mat(P), cx, cz)
        gl3d.set_sun(L, k, self.vp, 1.0 / SIZE, self.bias)

    def _draw_depth(self, view, proj, cx, cz):
        pad = HALF + 170.0
        ident = rl.matrix_identity()
        rl.begin_texture_mode(self.rt)
        rl.clear_background(rl.Color(255, 0, 0, 255))              # far plane = depth 1
        rl.begin_mode_3d(self.cam)
        try:
            rl.rl_set_matrix_projection(proj)
            rl.rl_set_matrix_modelview(view)
            rl.rl_disable_backface_culling()
            rl.rl_enable_depth_test()
            for key, (models, _last) in list(self.st.meshes.items()):
                ch = self.world.chunks.get(key)
                bb = ch["bb"] if ch else None
                if bb is None or bb[2] < cx - pad or bb[0] > cx + pad or bb[3] < cz - pad or bb[1] > cz + pad:
                    continue
                for mat, m in models.items():
                    if mat not in SKIP_MATS:
                        rl.draw_mesh(m.meshes[0], self.mat, ident)
            rl.rl_draw_render_batch_active()
        finally:
            rl.end_mode_3d()
            rl.end_texture_mode()
