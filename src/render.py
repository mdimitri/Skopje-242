"""3D drawing: ground chunk quads, streamed building/tree meshes, cars with dents, pedestrians, pickups, shadows."""
import math
import time
import os
from collections import OrderedDict

import numpy as np
import pyray as rl
import raylib as RL            # the raw cffi functions: no per-call argument conversion (hot loops only)

import actors
import birdart
import characterart
import fx
import gl3d
import farview
import modelpool
import weaponart
import projectiles
import vehicles
import slang

FOV = 38.0
TILT = 0.20
TAN = math.tan(math.radians(FOV / 2))
WHITE = rl.WHITE
V3 = rl.Vector3
UP = V3(0, 1, 0)
ONE = V3(1, 1, 1)
LOD_PPM = 2.4
ZERO = V3(0, 0, 0)


def gait_cycle(arch, run):
    """Ground covered by one stride cycle (two steps) of a person model, matched to how far its legs reach (gl3d.WALK_AMP):
    ~1.85 m walking, ~2.85 m running at full size. The player moves at game speed (5.75 / 9.5 m/s), faster than real
    legs could keep up with, so its cycle is longer (a little foot slide instead of a frantic shuffle)."""
    if arch >= 100:
        return gl3d.ped_scale(arch) * (4.4 if run else 2.6)
    return gl3d.ped_scale(arch) * (2.85 if run else 1.85)


def character_tier(height_px, maximum, quality=1.0):
    """Lower the detailed mesh bands as the frame-time scaler falls."""
    px = height_px * quality
    return min(maximum, 3 if px >= 44.0 else 2 if px >= 23.0 else 1)



def _hull(pts):
    """Convex hull (monotone chain), counter-clockwise."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        out = []
        for p in seq:
            x, z = p
            while len(out) >= 2:
                ax, az = out[-2]
                bx, bz = out[-1]
                if not (bx - ax) * (z - az) - (bz - az) * (x - ax) <= 0:
                    break
                out.pop()
            out.append(p)
        return out[:-1]
    return half(pts) + half(reversed(pts))


def _keep(M):
    """An owned copy of a Model's transform (reading model.transform gives a view of the model's memory, so 'old = m.transform'
    would change along with it and the restore would keep the new matrix). Restore with m.transform = old[0]."""
    return RL.ffi.new("Matrix *", M)


AUDIT3D = bool(os.environ.get("SK242_AUDIT3D"))
_GL = None
_FLAT = False

FLAT_VS = """#version 330
in vec3 vertexPosition;
uniform mat4 mvp;
void main(){ gl_Position = mvp * vec4(vertexPosition, 1.0); }
"""
FLAT_FS = """#version 330
uniform vec4 colDiffuse;
out vec4 finalColor;
void main(){
  gl_FragDepth = floor(gl_FragCoord.z * 65535.0) / 65535.0;     // every layer of a flattened shadow gets the very same depth value, rounded towards the camera (never behind the road it lies on)
  finalColor = colDiffuse;
}
"""


WIND_SWAY = 0.22                        # metres the very top of a tree sways in the breeze (leaves shimmer in proportion); 0 = still
DETAIL_MATS = (17, 18, 19)                 # tools/build_world.py "glaz", MAT_KIT2, MAT_KIT3: pieces on walls and roofs


def _gl():
    """glDepthFunc, which raylib does not wrap, looked up once; {} when unavailable."""
    global _GL
    if _GL is None:
        _GL = {}
        try:
            f = RL.ffi
            p = RL.rlGetProcAddress(b"glDepthFunc")
            if p != f.NULL:
                _GL = {"depthfunc": f.cast("void(*)(unsigned)", p)}
            q, en, di = (RL.rlGetProcAddress(n_) for n_ in (b"glPolygonOffset", b"glEnable", b"glDisable"))
            if f.NULL not in (q, en, di):
                _GL.update(polyoffset=f.cast("void(*)(float, float)", q), enable=f.cast("void(*)(unsigned)", en),
                           disable=f.cast("void(*)(unsigned)", di))
        except Exception:
            _GL = {}
    return _GL


INST_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; in mat4 instanceTransform;
uniform mat4 mvp;
out vec2 fragTexCoord; out vec4 fragColor;
void main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor;
             gl_Position = mvp * instanceTransform * vec4(vertexPosition, 1.0); }
"""
INST_FS = """#version 330
in vec2 fragTexCoord; in vec4 fragColor;
uniform sampler2D texture0; uniform vec4 colDiffuse;
out vec4 finalColor;
void main(){ finalColor = texture(texture0, fragTexCoord) * colDiffuse * fragColor; }
"""
_INST = {"mat": False}
INSTANCE = os.environ.get("SK242_INSTANCE", "1") != "0"


def _inst_material():
    """A material with raylib's default look (vertex colour x tint) that draws many copies of a mesh in one call
    (DrawMeshInstanced: the per-copy matrix is the instanceTransform attribute).  None when it cannot be made."""
    if _INST["mat"] is False:
        _INST["mat"] = None
        try:
            sh = rl.load_shader_from_memory(INST_VS, INST_FS)
            if rl.is_shader_valid(sh):
                sh.locs[rl.SHADER_LOC_MATRIX_MVP] = rl.get_shader_location(sh, "mvp")
                sh.locs[rl.SHADER_LOC_MATRIX_MODEL] = rl.get_shader_location_attrib(sh, "instanceTransform")
                m = rl.load_material_default()
                m.shader = sh
                _INST["mat"] = RL.ffi.new("Material *", m)
        except Exception as e:  # noqa: BLE001 - no instancing: every copy is drawn on its own as before
            print(f"[render] instancing off: {e}")
    return _INST["mat"]


class Batch:
    """Copies of the same model collected over a frame and drawn in one call per (model, tint) at flush()."""

    def __init__(self):
        self.groups = {}

    def add(self, m, M, tint):
        if not INSTANCE or _inst_material() is None or m.meshCount != 1:
            old = _keep(m.transform)                      # no instancing: draw it now, as before
            m.transform = M
            rl.draw_model(m, ZERO, 1.0, tint)
            m.transform = old[0]
            return
        tc = tuple(tint) if isinstance(tint, tuple) else (tint.r, tint.g, tint.b, tint.a)
        k = (int(RL.ffi.cast("uintptr_t", m.meshes)), tc)
        g = self.groups.get(k)
        if g is None:
            g = self.groups[k] = (m, tc, [])
        g[2].append(RL.ffi.new("Matrix *", M))           # (owned copy: M is often a temporary)

    def flush(self):
        mp = _inst_material()
        for m, tint, mats in self.groups.values():
            n = len(mats)
            arr = RL.ffi.new("Matrix[]", n)
            for i, M in enumerate(mats):
                arr[i] = M[0]
            mp.maps[0].color = tint
            RL.DrawMeshInstanced(m.meshes[0], mp[0], arr, n)
        self.groups.clear()


def _flat_shader():
    """Flat-colour shader for projected shadows (None if it fails to compile: shadows then fall back to rectangles' absence, never a crash)."""
    global _FLAT
    if _FLAT is False:
        try:
            sh = rl.load_shader_from_memory(FLAT_VS, FLAT_FS)
            _FLAT = sh if rl.is_shader_valid(sh) else None
        except Exception:
            _FLAT = None
    return _FLAT


class Frustum:
    """View frustum of a perspective Camera3D: sphere tests (one in Python, many at once in numpy)."""

    def __init__(self, cam, aspect, far):
        p, t = cam.position, cam.target
        fx, fy, fz = t.x - p.x, t.y - p.y, t.z - p.z
        n = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
        fx, fy, fz = fx / n, fy / n, fz / n
        rx, rz = -fz, fx                                    # right = forward x up (up = +y)
        n = math.hypot(rx, rz) or 1.0
        rx, rz = rx / n, rz / n
        ux, uy, uz = -rz * fy, rz * fx - rx * fz, rx * fy   # up' = right x forward
        self.p = (p.x, p.y, p.z)
        self.f, self.r, self.u = (fx, fy, fz), (rx, 0.0, rz), (ux, uy, uz)
        self.tv = math.tan(math.radians(cam.fovy) / 2)
        self.th = self.tv * aspect
        self.kv, self.kh = math.sqrt(1 + self.tv ** 2), math.sqrt(1 + self.th ** 2)
        self.far = far
        self.fpx = (rl.get_render_height() / 2) / max(self.tv, 1e-6)       # pixels per metre at 1 m in front of the camera

    def seen(self, x, y, z, r):
        """In the frustum and at least about half a pixel big on screen."""
        if not self.sphere(x, y, z, r):
            return False
        px, py, pz = self.p
        d = math.sqrt((x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2)
        return r * self.fpx > 0.5 * d

    def sphere(self, x, y, z, r):
        px, py, pz = self.p
        dx, dy, dz = x - px, y - py, z - pz
        f = self.f
        zc = dx * f[0] + dy * f[1] + dz * f[2]
        if zc < -r or zc > self.far + r:
            return False
        xc = dx * self.r[0] + dz * self.r[2]
        if abs(xc) - zc * self.th > r * self.kh:
            return False
        u = self.u
        yc = dx * u[0] + dy * u[1] + dz * u[2]
        return abs(yc) - zc * self.tv <= r * self.kv

    def spheres(self, S):
        """S: (N, 4) array of x, y, z, r -> bool mask of the spheres that touch the frustum."""
        D = S[:, :3] - np.asarray(self.p)
        r = S[:, 3]
        zc = D @ np.asarray(self.f)
        xc = D @ np.asarray(self.r)
        yc = D @ np.asarray(self.u)
        return ((zc >= -r) & (zc <= self.far + r) & (np.abs(xc) - zc * self.th <= r * self.kh)
                & (np.abs(yc) - zc * self.tv <= r * self.kv))


def quad_tex(tex_id, x0, z0, x1, z1, y, flip):
    rl.rl_set_texture(tex_id)
    rl.rl_begin(rl.RL_QUADS)
    rl.rl_color4ub(255, 255, 255, 255)
    v0, v1 = (1.0, 0.0) if flip else (0.0, 1.0)
    rl.rl_tex_coord2f(0.0, v0); rl.rl_vertex3f(x0, y, z0)
    rl.rl_tex_coord2f(1.0, v0); rl.rl_vertex3f(x1, y, z0)
    rl.rl_tex_coord2f(1.0, v1); rl.rl_vertex3f(x1, y, z1)
    rl.rl_tex_coord2f(0.0, v1); rl.rl_vertex3f(x0, y, z1)
    rl.rl_end()
    rl.rl_set_texture(0)


class Renderer:
    def __init__(self, world, streamer, overview):
        self.w = world
        self.st = streamer
        self.overview = overview
        self._built = 0
        self.shadows = True
        self.sun_k = 1.0              # 0..1: how much real sun there is (people's shadows fade with it)
        self.sun = None               # unit vector towards the sun (set by main each frame): contact shadows fall away from it
        self.car_models = {}
        self.front_wheels = {}        # kind -> (axle x, radius, track half, model)
        self.rear_axle_models = {}    # kind -> [(axle x, radius, 0, model)] of the other axles
        self._own = {}                         # id(body) -> body with its own model
        self._frames = 0
        self.log, self._vanish_t = print, -99.0          # main points log at logs/game.log
        self.ped_models = {}                       # tier 1 with the default palette, used as worker fallbacks
        self.ped_variants = OrderedDict()
        self.ped_variant_vertices = 0
        self.ped_textures = {}
        self.ped_detail = 3
        self.ped_quality = 1.0
        self.dog_models = {}
        self.bird_models = {}
        self.pick_models = {}
        self.wreck_models = {}
        self.t = 0.0
        self.drawn_chunks = 0
        self.drawn_meshes = 0
        self.frustum = None
        self.mb = modelpool.Builder()             # new car / person models made on other cores
        self.car_lods = {}                        # (kind, colour) -> car with its front wheels built in (distant cars: 1 draw, not 3)

    # ---------------------------------------------------------------- camera
    def camera(self, cx, cz, ppm, sw, sh, cy=0.0):
        """cy: height of the ground under the camera focus (terrain), so the zoom stays the same on a hill."""
        H = (sh / 2) / (ppm * TAN)
        cam = rl.Camera3D(V3(cx, cy + H, cz + H * TILT), V3(cx, cy, cz), UP, FOV, rl.CAMERA_PERSPECTIVE)
        k = 1.0 + (35.0 / H if self.w.hilly else 0.0)          # lower ground further out is seen from further away
        hw, hh = sw / (2 * ppm) * k, sh / (2 * ppm) * k
        rect = (cx - hw - 30, cz - hh - 30, cx + hw + 30, cz + hh + 30 + H * TILT * 0.4)
        return cam, H, rect

    # ---------------------------------------------------------------- the whole city, far LOD: coarse terrain under the overview map
    def _overview(self):
        self.build_overview()
        if self._ov_model is not None:
            rl.draw_model(self._ov_model, V3(0, 0, 0), 1.0, WHITE)

    def build_overview(self):
        """Builds the coarse model once (the loader calls it, so the first zoom-out never stalls a frame)."""
        if getattr(self, "_ov_model", None) is None:
            w = self.w
            if w.hilly:
                step = 4                                           # every 40 m; minimum of the 5x5 posts around: never pokes through
                g = getattr(w, "tgrid_low", w.tgrid)                # (lowered under the river quays)
                ny, nx = g.shape
                gi = np.arange(0, ny, step)
                gj = np.arange(0, nx, step)
                pad = np.pad(g, 2, mode="edge")
                low = np.min([pad[2 + di:2 + di + ny, 2 + dj:2 + dj + nx] for di in range(-2, 3) for dj in range(-2, 3)], axis=0)
                H = low[np.ix_(gi, gj)] - 0.4
                X = gj * w.tstep - w.hx
                Z = gi * w.tstep - w.hy
            else:
                X = np.array([-w.hx, w.hx])
                Z = np.array([-w.hy, w.hy])
                H = np.full((2, 2), -0.25)
            XX, ZZ = np.meshgrid(X, Z)
            P = np.stack([XX, H, ZZ], -1).astype(np.float32)
            U = np.stack([(XX + w.hx) / (2 * w.hx), (ZZ + w.hy) / (2 * w.hy)], -1).astype(np.float32)
            ny_, nx_ = H.shape
            i00 = (np.arange(ny_ - 1)[:, None] * nx_ + np.arange(nx_ - 1)[None, :]).ravel()
            idx = np.stack([i00, i00 + 1, i00 + nx_ + 1, i00, i00 + nx_ + 1, i00 + nx_], 1).ravel()
            m = gl3d.make_model(P.reshape(-1, 3)[idx], U.reshape(-1, 2)[idx], np.full((len(idx), 4), 255, np.uint8))
            if m is not None:
                gl3d.set_texture(m, self.overview)
            self._ov_model = m

    # ---------------------------------------------------------------- models
    def car_model(self, b):
        if b.dirty or (b.model is None and (b.dents or b.exploded)):
            if b.model is not None:
                gl3d.free_model(b.model)
                b.model = None                             # never keep a freed model if the rebuild below fails
            b.model = gl3d.car_model(b.kind, b.color, b.dents, 1.0 if b.exploded else min(1.0, b.burn / 6.0) * 0.5,
                                     b.color < 0, scene=True)
            b.dirty = False
            self._own[id(b)] = b
        if b.model is not None:
            return b.model
        if b.color >= 0:                                   # plain car: shared model, built within the per-frame budget
            return self.ai_model(b.kind, b.color)
        key = (b.kind, b.color)
        m = self.car_models.get(key)
        if m is None:
            m = self.car_models[key] = gl3d.car_model(b.kind, b.color, player=True, scene=True)
        return m

    trailer_m = None
    trailer_ax = None

    def _audit3d(self, cars, trailers, peds):
        """SK242_AUDIT3D=1 test harness: read the depth buffer (world drawn, people and cars not yet) and measure how far each
        actor's base floats above (+) or sinks into (-) the surface actually rendered under it; also checks that every
        person's shadow plane is their feet. Prints one [audit3d] line per category."""
        rl.rl_draw_render_batch_active()
        rw, rh = rl.get_render_width(), rl.get_render_height()
        f = RL.ffi
        rp = getattr(self, "_rp", None)
        if rp is None:
            p = RL.rlGetProcAddress(b"glReadPixels")
            rp = self._rp = f.cast("void(*)(int,int,int,int,unsigned,unsigned,void*)", p)
        buf = np.empty((rh, rw), np.float32)
        rp(0, 0, rw, rh, 0x1902, 0x1406, f.from_buffer(buf))
        cam, (n, fa) = self._cam, self._clip
        c = np.array([cam.position.x, cam.position.y, cam.position.z])
        fw = np.array([cam.target.x, cam.target.y, cam.target.z]) - c
        fw /= np.linalg.norm(fw)

        def err(x, y, z):
            q = rl.get_world_to_screen_ex(V3(x, y, z), cam, rw, rh)
            ix, iy = int(q.x), int(q.y)
            if not (2 <= ix < rw - 2 and 2 <= iy < rh - 2):
                return None
            d = float(buf[rh - 1 - iy, ix])
            if d >= 1.0:
                return None
            zb = n * fa / (fa - d * (fa - n))                     # eye depth of the rendered surface on that pixel
            P = np.array([x, y, z])
            zp = float(np.dot(P - c, fw))
            if zp <= n or zb < zp - 1.5:                          # behind the camera / hidden under a roof, tree, bridge
                return None
            Q = c + (P - c) * (zb / zp)
            return y - Q[1]

        rows = {}
        for x, z, h, m, tint, gy, pitch, roll, kind, *_ in cars:
            rows.setdefault("car", []).append((err(x, gy, z), (round(x, 1), round(z, 1), kind)))
        for x, z, th, gy, *_ in trailers:
            rows.setdefault("trailer", []).append((err(x, gy, z), (round(x, 1), round(z, 1))))
        for x, y, z, h, arch, tone, frame, skin, *ex in peds:
            if frame == 2:
                continue
            rows.setdefault("ped", []).append((err(x, y, z), (round(x, 1), round(z, 1), frame, round(self.w.ground_y(x, z), 2), self.w.kerb(x, z))))
            if len(ex) > 1 and abs(y - ex[1]) > 0.05:
                rows.setdefault("ped_shadow_off_feet", []).append((y - ex[1], (round(x, 1), round(z, 1), frame)))
        for k, v in rows.items():
            e = [(a, b) for a, b in v if a is not None]
            if not e:
                continue
            ar = np.array([a for a, _ in e])
            bad = sorted(e, key=lambda r: -abs(r[0]))[:3]
            print(f"[audit3d] {k}: n={len(e)} median={np.median(ar):+.3f} float>8cm={int((ar > 0.08).sum())} sink>8cm={int((ar < -0.08).sum())} "
                  f"worst={[(round(a, 2), b) for a, b in bad]}", flush=True)

    def _near(self, x, z):
        """On screen: its shadow is the projected mesh (see _proj_shadow), not the parallelogram."""
        return self.shadows and (x - self._sh_c[0]) ** 2 + (z - self._sh_c[1]) ** 2 < self._sh_r2

    def _heli_wind(self, sim):
        """Flying: air streaks fixed in the world round the helicopter, so they stream past against the travel direction
        (climb and descent included); more and longer the faster you go."""
        c = sim.car
        pts = getattr(self, "_wind", None)
        if pts is None:
            pts = self._wind = []
        if sim.mode != "car" or c is None or c.kind not in vehicles.FLY or c.az is None:
            pts.clear()
            return
        vx, vy, vz = c.vx, c.vy, getattr(c, "vz", 0.0)
        sp = math.sqrt(vx * vx + vy * vy + vz * vz)
        now = time.time()
        n_want = int(min(140, sp * 4.0)) if sp > 2.0 else 0
        rnd = np.random.random
        while len(pts) < n_want:                              # new streaks ahead of / round the machine, where it is going
            lead = 0.6
            pts.append([c.x + vx * lead + (rnd() - 0.5) * 50, c.y + vy * lead + (rnd() - 0.5) * 50,
                        c.az + 1.5 + vz * lead + (rnd() - 0.5) * 18, now + 0.5 + rnd() * 0.9, now])
        del pts[n_want:]
        if sp < 0.1:
            return
        L = min(6.0, 0.12 * sp + 0.4)                          # streak length grows with speed
        ux, uy, uz = vx / sp, vy / sp, vz / sp
        keep = []
        for q in pts:
            if now > q[3] or (q[0] - c.x) ** 2 + (q[1] - c.y) ** 2 > 45 ** 2:
                continue
            keep.append(q)
            a = int(210 * min(1.0, (now - q[4]) / 0.2) * min(1.0, (q[3] - now) / 0.3))
            col_ = rl.Color(240, 246, 255, a)
            for o_ in (0.0, 0.06):                                # two lines side by side: visible from high up
                rl.draw_line_3d(V3(q[0] + o_, q[2], q[1]), V3(q[0] + o_ - ux * L, q[2] - uz * L, q[1] - uy * L), col_)
        pts[:] = keep

    def _proj_shadow(self, m, M, gy, a):
        """Shadow of the real mesh: every vertex slid along the sun direction down onto the ground plane (a shear), drawn flat dark.
        Depth writes stay on, so where limbs / body / trailer overlap the shadow is not darkened twice."""
        sx, sz, k = self._sh_k
        a = int(a * (0.4 + 0.6 * k))
        if a <= 0 or m is None:
            return
        S = rl.Matrix(1.0, sx, 0.0, -sx * gy,  0.0, 0.0, 0.0, gy + 0.04,  0.0, sz, 1.0, -sz * gy,  0.0, 0.0, 0.0, 1.0)
        old = _keep(m.transform)
        m.transform = rl.matrix_multiply(M, S)
        sh = _flat_shader()
        gls = _gl()
        if sh is None or not gls:
            m.transform = old[0]
            return
        mat = m.materials[0]
        old_id, old_locs = mat.shader.id, mat.shader.locs        # (the struct is a view into the material: copy its fields)
        mat.shader = sh
        gls["depthfunc"](0x0201)                      # GL_LESS: the first layer at a pixel writes the (quantised, so identical) depth, the rest fail
        rl.draw_model(m, V3(0, 0, 0), 1.0, rl.Color(10, 10, 20, a))
        gls["depthfunc"](0x0203)
        mat.shader.id, mat.shader.locs = old_id, old_locs
        m.transform = old[0]

    def _trailer(self, out, sh, x, y, h, th, gy, pitch, roll, tgz=None, tpitch=None, troll=None, ckey=None):
        """Semi rig at (x, y, h): shadow of the short tractor and of the trailer hinged at its fifth wheel, trailer heading th.
        tgz / tpitch / troll: the trailer's own pose at the kingpin (actors.ride), else the tractor's."""
        hx, hy = x + math.cos(h) * vehicles.SEMI_HITCH, y + math.sin(h) * vehicles.SEMI_HITCH
        out.append((hx, hy, th, gy if tgz is None else tgz, pitch if tpitch is None else tpitch, roll if troll is None else troll, ckey))
        if self._near(x, y):
            return
        sh.append((x + math.cos(h) * vehicles.SEMI_SHIFT, y + math.sin(h) * vehicles.SEMI_SHIFT, h, vehicles.SEMI_TRACTOR_L / 2 + 0.2, vehicles.DIMS[vehicles.SEMI][1] / 2, 70, gy, vehicles.DIMS[vehicles.SEMI][4]))
        mid = vehicles.SEMI_TRAILER_L / 2 - 0.3
        sh.append((hx - math.cos(th) * mid, hy - math.sin(th) * mid, th, vehicles.SEMI_TRAILER_L / 2 + 0.2, vehicles.DIMS[vehicles.SEMI][1] / 2, 70, gy, 3.9))

    def _bus_rear(self, M, bend, x, z, gy, tint):
        hinge = vehicles.ARTIC_HINGE
        joint = rl.matrix_multiply(rl.matrix_translate(-hinge, 0, 0), rl.matrix_rotate_y(-bend))
        joint = rl.matrix_multiply(joint, rl.matrix_translate(hinge, 0, 0))
        rear_basis = rl.matrix_multiply(joint, M)
        rear = self.car_models.get("bus_rear")
        if rear is None:
            rear = self.car_models["bus_rear"] = gl3d.bus_rear_model()
        step = round(bend / 0.035)
        key = ("bus_bellows", step)
        bellows = self.car_models.get(key)
        if bellows is None:
            angle = max(-vehicles.ARTIC_JACK, min(vehicles.ARTIC_JACK, step * 0.035))
            bellows = self.car_models[key] = gl3d.object_detail(gl3d.make_model(*gl3d.bus_bellows_arrays(angle)), "rubber")
        for model, transform in ((rear, rear_basis), (bellows, M)):
            if model is not None:
                old = _keep(model.transform)
                model.transform = transform
                rl.draw_model(model, ZERO, 1.0, tint)
                if self._near(x, z):
                    self._proj_shadow(model, transform, gy, 70)
                model.transform = old[0]
        return rear_basis

    @staticmethod
    def _indicator_lens(cam, pose, mount, side, end, glows, body_end=None):
        x, y, z, width, height = mount
        z *= side
        center = rl.vector3_transform(V3(x, y, z), pose)
        normal = rl.vector3_transform(V3(x + end, y, z), pose)
        eye = cam.position
        dx, dy, dz = eye.x - center.x, eye.y - center.y, eye.z - center.z
        facing = (normal.x - center.x) * dx + (normal.y - center.y) * dy + (normal.z - center.z) * dz > 0.0
        if facing:
            a, b, c, d = [rl.vector3_transform(V3(x, y + sy * height * 0.5, z + sz * width * 0.5), pose)
                          for sy, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            if end < 0:
                b, d = d, b
            amber = rl.Color(255, 191, 66, 255)
            rl.draw_triangle_3d(a, b, c, amber)
            rl.draw_triangle_3d(a, c, d, amber)
        if body_end is not None and dy > math.hypot(dx, dz) * 1.1:
            # At a high angle, the bumper can hide the lens. Its spill is still visible just outside it.
            spill = rl.vector3_transform(V3(body_end + 0.10 * end, y, z), pose)
            glows.append((spill, max(0.37, width * 3.0)))
        elif facing:
            glows.append((center, max(0.17, width * 2.5)))

    def _indicator_glows(self, cam, glows):
        if not glows:
            return
        texture = getattr(self, "_indicator_texture", None)
        if texture is None:
            image = rl.gen_image_gradient_radial(32, 32, 0.0, rl.Color(255, 169, 66, 128), rl.BLANK)
            texture = self._indicator_texture = rl.load_texture_from_image(image)
            rl.unload_image(image)
            rl.set_texture_filter(texture, rl.TEXTURE_FILTER_BILINEAR)
        rl.rl_disable_depth_mask()
        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
        eye = cam.position
        for center, size in glows:
            # Keep the glow readable from the top / far camera: grow with distance (about 0.05 m per metre, capped).
            dist = math.sqrt((eye.x - center.x) ** 2 + (eye.y - center.y) ** 2 + (eye.z - center.z) ** 2)
            size *= min(6.0, max(1.0, dist * 0.05))
            flat = max(0.0, min(1.0, ((eye.y - center.y) / max(dist, 0.01) - 0.55) / 0.35))     # 0 level view .. 1 from straight above
            if flat < 1.0:
                rl.draw_billboard_pro(cam, texture, rl.Rectangle(0, 0, texture.width, texture.height), center,
                                      cam.up, rl.Vector2(size, size), rl.Vector2(size * 0.5, size * 0.5), 0.0,
                                      rl.Color(255, 255, 255, int(255 * (1.0 - flat))))
            if flat > 0.0:                                         # seen from above the glow lies flat on the road, not standing up
                h = size * 0.5
                rl.rl_set_texture(texture.id)
                rl.rl_begin(rl.RL_QUADS)
                rl.rl_color4ub(255, 255, 255, int(255 * flat))
                for u, v, dx, dz in ((0, 0, -h, -h), (0, 1, -h, h), (1, 1, h, h), (1, 0, h, -h)):
                    rl.rl_tex_coord2f(u, v)
                    rl.rl_vertex3f(center.x + dx, center.y + 0.03, center.z + dz)
                rl.rl_end()
                rl.rl_set_texture(0)
        rl.end_blend_mode()
        rl.rl_enable_depth_mask()

    def _free_orphans(self, bodies):
        """Dented / burnt cars own a model; give its video memory back once the car is gone (never for a car still in play)."""
        live = {id(b) for b in bodies}
        for k in [k for k in self._own if k not in live]:
            b = self._own.pop(k)
            if b.model is not None:
                gl3d.free_model(b.model)
                b.model = None
                b.dirty = True

    BUILD_BUDGET = 2                      # new procedural models per frame (keeps the first sight of a new car/person smooth)

    def warm_models(self, specs, progress):
        """Generate startup meshes on the model workers, then upload them on the window thread."""
        import time

        for start in range(0, len(specs), self.mb.limit):
            batch = specs[start:start + self.mb.limit]
            for spec in batch:
                self.mb.want(spec, spec)
            while self.mb.jobs:
                self._collect_models()
                progress(start + len(batch) - len(self.mb.jobs), len(specs))
                if self.mb.jobs:
                    time.sleep(0.002)
            # The normal synchronous path covers disabled workers and failed jobs.
            for offset, spec in enumerate(batch, start + 1):
                if spec[0] == "car":
                    self.ai_model(*spec[1:])
                elif self._cached_ped(spec[1:]) is None:
                    self._upload_ped(spec[1:], gl3d.ped_visual(*spec[1:]))
                progress(offset, len(specs))

    def ai_model(self, kind, color):
        key = (kind, color)
        m = self.car_models.get(key)
        if m is None:
            fb = self.car_models.get((kind, 0))
            if fb is not None and self.mb.want(("car", kind, color), ("car", kind, color)):
                return fb                                         # built on a worker; the plain-paint version until then
            if self._built >= self.BUILD_BUDGET:                 # over budget: show the plain-paint version for now
                m = fb
                if m is not None:
                    return m                                      # (none yet: build it now, a car is never invisible)
            self._built += 1
            m = self.car_models[key] = gl3d.car_model(kind, color, scene=True)
        return m

    LOD_PX = 40.0                         # a plain car shorter than this on screen is drawn as one model (front wheels straight)

    def car_lod(self, kind, color):
        key = (kind, color)
        m = self.car_lods.get(key)
        if m is None and not self.mb.want(("carlod",) + key, ("carlod",) + key) and self._built < self.BUILD_BUDGET:
            self._built += 1
            m = self.car_lods[key] = gl3d.car_model(kind, color, (), 0.0, False, False)
        return m

    @staticmethod
    def _gait(arch, anim, run):
        """Frame of the walk / run cycle: four poses per stride for people, two for riders and carts."""
        if 10 <= arch < 100 and vehicles.PED_IDS[arch] in vehicles.RIDERS:
            return int(anim * 2.2) & 1
        # eight phases per stride cycle (two steps); anim is the ground covered, so feet stay planted
        return (30 if run else 20) + (int(anim * 8 / gait_cycle(arch, run)) & 7)

    def _cached_ped(self, key):
        if key in self.ped_models:
            return self.ped_models[key]
        visual = self.ped_variants.get(key)
        if visual is not None:
            self.ped_variants.move_to_end(key)
        return visual

    def _upload_ped(self, key, data):
        arrays, grip = data
        model = gl3d.make_model(*arrays)
        tier = key[-1]
        gl3d.object_detail(model, "character" if tier > 1 else "cloth", key[0] + key[1] * 3)
        visual = model, grip, key[2]
        if tier == 1 and key[1] == key[3] == 0:
            self.ped_models[key] = visual
        else:
            if tier > 1:
                if tier not in self.ped_textures:
                    self.ped_textures[tier] = gl3d.ped_atlas(tier)
                gl3d.set_texture(model, self.ped_textures[tier])
            self.ped_variants[key] = visual
            self.ped_variant_vertices += model.meshes[0].vertexCount
            while self.ped_variant_vertices > 2_000_000:         # limit extra VRAM as the street mixes stages, outfits and poses
                _, (old, _, _) = self.ped_variants.popitem(last=False)
                self.ped_variant_vertices -= old.meshes[0].vertexCount
                gl3d.free_model(old)
        return visual

    def ped_model(self, arch, tone, frame, skin, tier=1):
        if arch >= 100:
            arch, tone, skin = characterart.hero_arch(arch), 0, 0
        low = characterart.lod_frame(frame, 1)
        key = (arch, tone, low if tier == 1 else frame, skin, tier)
        visual = self._cached_ped(key)
        if visual is not None:
            return visual
        fallback = (self._cached_ped((arch, tone, frame, skin, 2)) if tier == 3 else None)
        fallback = (fallback or self._cached_ped((arch, tone, low, skin, 1))
                    or self.ped_models.get((arch, 0, low, 0, 1))
                    or self._cached_ped((arch, tone, 12, skin, 1))
                    or self.ped_models.get((arch, 0, 12, 0, 1))
                    or self.ped_models.get((arch, 0, 0, 0, 1)))
        job = ("ped",) + key
        if fallback is not None and (self.mb.want(job, job) or self._built >= self.BUILD_BUDGET):
            return fallback
        self._built += 1
        return self._upload_ped(key, gl3d.ped_visual(*key))

    def close_ped_models(self):
        for model, _, _ in (*self.ped_models.values(), *self.ped_variants.values()):
            gl3d.free_model(model)
        for tex in self.ped_textures.values():
            rl.unload_texture(tex)

    def bird_model(self, art, frame):
        key = (art, frame)
        m = self.bird_models.get(key)
        if m is None:
            if self._built >= self.BUILD_BUDGET:
                return self.bird_models.get((art, 0))
            self._built += 1
            m = self.bird_models[key] = gl3d.bird_model(art, frame)
        return m

    def dog_model(self, coat, frame):
        key = (coat, frame)
        m = self.dog_models.get(key)
        if m is None:
            if self._built >= self.BUILD_BUDGET:
                return self.dog_models.get((coat, 11)) or self.dog_models.get((0, 11))      # (none yet: the next frame builds it)
            self._built += 1
            m = self.dog_models[key] = gl3d.dog_model(coat, frame)
        return m

    def _held(self, weapon, x, gy, z, h, frame, grip):
        """Attach the weapon to the right hand of the displayed pose."""
        wm = self.pick_model(weapon)
        if wm is None:
            return
        melee = weapon in actors.SWINGERS
        if melee and 60 <= frame <= 67:
            u = (frame - 60 + 0.5) / 8.0
            psi = weaponart.swing_az(u)
            hand = grip[0]
            pitch, yaw = 0.1 + 0.9 * (1.0 - u) ** 2, -psi
        else:
            hand, fa = grip
            pitch = max(-0.8, min(1.4, (1.0 if melee else 0.05) + fa - 0.25))
            yaw = 0.0
        Mh = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(1.1, 1.1, 1.1), rl.matrix_rotate_z(pitch)),
                                rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_y(yaw), rl.matrix_translate(*hand)), rl.matrix_rotate_y(-h)))
        Mh = rl.matrix_multiply(Mh, rl.matrix_translate(x, gy, z))
        old_t = _keep(wm.transform)
        wm.transform = Mh
        rl.draw_model(wm, V3(0, 0, 0), 1.0, WHITE)
        wm.transform = old_t[0]

    def pick_model(self, kind):
        m = self.pick_models.get(kind)
        if m is None:
            m = self.pick_models[kind] = gl3d.pickup_model(kind)
        return m

    # ---------------------------------------------------------------- scene
    def _collect_models(self):
        """Upload the models the workers finished (arrays -> VRAM)."""
        for key, arrs in self.mb.ready():
            kind, k = key[0], key[1:]
            if kind == "ped":
                if self._cached_ped(k) is None:
                    self._upload_ped(k, arrs)
                continue
            store = self.car_models if kind == "car" else self.car_lods
            if store.get(k) is None:
                store[k] = gl3d.gloss_apply(gl3d.make_model(*arrs), k[0])

    def draw(self, cam, H, rect, ppm, sim, particles, t, show_meshes=True, near=2.0, far_overview=False):
        self._built = 0
        self._collect_models()
        self._ppm = ppm
        w, st = self.w, self.st
        S = w.chunk
        self.t = t
        gl3d.ground_time(t)
        far_ = max(H * 4 + 400, getattr(self, "view_far", 0.0))     # helicopter street view: out to the far ring
        rl.rl_set_clip_planes(near, far_)
        self._cam, self._clip = cam, (near, far_)
        # full-model shadows for everything on screen: the frame's half diagonal on the ground (resolution x zoom setting x
        # the current zoom-out), the street view out to its full-detail distance; beyond that the parallelogram
        r = 150.0 if far_overview else 0.5 * math.hypot(rl.get_render_width(), rl.get_render_height()) / max(ppm, 0.1) + 8.0
        r = float(os.environ.get("SK242_SHADOW_R") or r)      # test harness: force the full-model range (0: all parallelograms)
        self._sh_r2 = r * r
        rl.begin_mode_3d(cam)
        try:
            rl.rl_disable_backface_culling()
            lod = ppm >= LOD_PPM
            drawn = 0
            missing = not lod
            fr = self.frustum = Frustum(cam, rl.get_render_width() / max(1, rl.get_render_height()), far_)
            gsph = st.gsph
            ind = getattr(self, "indoor", None)
            if ind is not None:                            # inside the GTC mall: only its hall and the actors are drawn
                ind.draw(cam)
                self.drawn_chunks = self.drawn_meshes = 0
                self._actors(rect, sim, t)
                self._shots(rect, sim)
                particles.draw()
                return
            if lod:
                x0, x1 = math.floor((rect[0]) / S), math.floor(rect[2] / S)
                y0, y1 = math.floor((rect[1]) / S), math.floor(rect[3] / S)
                for cx in range(x0, x1 + 1):
                    for cy in range(y0, y1 + 1):
                        gm = st.get_ground_model((cx, cy))
                        if gm is not None:
                            sp = gsph.get((cx, cy))
                            if sp is None or fr.sphere(*sp):
                                RL.DrawModel(gm, ZERO, 1.0, WHITE)
                                drawn += 1
                        else:
                            missing = True
            if missing or far_overview:                    # the coarse whole-city model is only seen where a chunk is not baked yet
                self._overview()
            fk = getattr(self, "far_keys", None)
            if fk:                                         # helicopter: cheap building / tree blocks beyond the streamed chunks
                if getattr(self, "farview", None) is None:
                    self.farview = farview.FarView(w, st.tex.get("A"))
                self.drawn_far = self.farview.draw(rl, fk, st.meshes, fr, self.view_far - 100)
            self.drawn_chunks = drawn
            nm = 0
            if lod and show_meshes:
                gl3d.tree_wind(t, WIND_SWAY)
                decals, detail = [], []
                gl_ = _gl()
                for key, e in self._visible_meshes(st, fr, rect):
                    for mat, m in e[0].items():
                        if mat == 22:
                            continue                         # crown blob for the sun-shadow pass only
                        if mat == 6:
                            decals.append(m)                 # graffiti: after every wall, without writing depth
                        elif mat in DETAIL_MATS and "polyoffset" in gl_:
                            detail.append(m)
                        else:
                            RL.DrawModel(m, ZERO, 1.0, WHITE)
                    nm += 1
                    e[1] = st.frame
                if detail:                                   # frames, sills, relief, clutter: pulled a hair towards the camera so
                    rl.rl_draw_render_batch_active()         # a piece in the plane of a wall or slab wins instead of flickering
                    gl_["enable"](0x8037)                    # GL_POLYGON_OFFSET_FILL
                    gl_["polyoffset"](-1.0, -2.0)
                    for m in detail:
                        RL.DrawModel(m, ZERO, 1.0, WHITE)
                    rl.rl_draw_render_batch_active()
                    gl_["disable"](0x8037)
                if decals:
                    rl.rl_draw_render_batch_active()
                    rl.rl_disable_depth_mask()
                    for m in decals:
                        RL.DrawModel(m, ZERO, 1.0, WHITE)
                    rl.rl_draw_render_batch_active()
                    rl.rl_enable_depth_mask()
            self.drawn_meshes = nm
            if lod:
                if getattr(w, "roads3d", False):
                    self._decals(rect)
                    if getattr(sim, "crews", None) is not None:
                        sim.crews.draw3d(rect, w.ground_y, rl)
                self._actors(rect, sim, t)
                self._shots(rect, sim)
                self._balls(rect, sim)
                self._garbage(rect, sim, t)
                if getattr(sim, "lights", None) is not None:
                    sim.lights.draw(rect, w.ground_y, fr.seen)
                if getattr(sim, "trains", None) is not None:
                    sim.trains.draw(rect, w.ground_y)
                particles.draw()
        finally:
            rl.end_mode_3d()

    def _visible_meshes(self, st, fr, rect):
        """(key, streamer entry) of the uploaded chunk meshes inside the rectangle and the view frustum (one numpy test)."""
        keys = list(st.meshes)
        if keys != getattr(self, "_vm_keys", None):
            self._vm_keys = keys
            sph = st.sph
            bbs, ss = [], []
            for k in keys:
                ch = self.w.chunks.get(k)
                bb = ch["bb"] if ch else None
                sp = sph.get(k)
                bbs.append(bb[:4] if bb is not None else (1e9, 1e9, -1e9, -1e9))
                ss.append(sp if sp is not None else (0.0, 0.0, 0.0, 1e9))
            self._vm_bb = np.asarray(bbs, np.float64).reshape(-1, 4)
            self._vm_s = np.asarray(ss, np.float64).reshape(-1, 4)
        if not keys:
            return []
        B = self._vm_bb
        ok = (B[:, 2] >= rect[0]) & (B[:, 0] <= rect[2]) & (B[:, 3] >= rect[1]) & (B[:, 1] <= rect[3]) & fr.spheres(self._vm_s)
        me = st.meshes
        return [(keys[i], me[keys[i]]) for i in np.flatnonzero(ok)]

    def _decals(self, rect):
        """Skid marks, blood and scorch as flat quads just above the 3D road surface."""
        w = self.w
        S = w.chunk
        rl.rl_disable_depth_mask()
        rl.rl_begin(rl.RL_QUADS)
        n = 0
        blobs = []
        for cx in range(math.floor(rect[0] / S), math.floor(rect[2] / S) + 1):
            for cy in range(math.floor(rect[1] / S), math.floor(rect[3] / S) + 1):
                for d in self.st.decals.get((cx, cy), ()):
                    if d[0] == "l":
                        _, x1, z1, x2, z2, hw, col = d
                        dx, dz = x2 - x1, z2 - z1
                        l = math.hypot(dx, dz) or 1.0
                        nx, nz = -dz / l * hw, dx / l * hw
                        y = max(w.ground_y(x1, z1), w.ground_y(x2, z2)) + 0.03
                        rl.rl_color4ub(col[0], col[1], col[2], col[3])
                        rl.rl_vertex3f(x1 + nx, y, z1 + nz); rl.rl_vertex3f(x2 + nx, y, z2 + nz)
                        rl.rl_vertex3f(x2 - nx, y, z2 - nz); rl.rl_vertex3f(x1 - nx, y, z1 - nz)
                    else:
                        blobs.append(d)
                    n += 1
                    if n > 2500:
                        break
        rl.rl_end()
        if blobs:                                    # blood / scorch: a few overlapping soft discs, no hard square edges
            rl.rl_set_texture(fx.soft_id())
            rl.rl_begin(rl.RL_QUADS)
            for _, x, z, r, col in blobs:
                y = w.ground_y(x, z) + 0.035
                hs = int(x * 31.7 + z * 17.3) & 0xFFFF
                for k in range(3):                   # main pool plus two smaller lobes, offset and turned by the position
                    a = (hs * 0.37 + k * 2.1) % 6.283
                    off, rr = (0.0, r * 1.25) if k == 0 else (r * 0.45, r * (0.8 - 0.15 * k))
                    cx, cz = x + math.cos(a) * off, z + math.sin(a) * off
                    ca, sa = math.cos(a) * rr, math.sin(a) * rr
                    rl.rl_color4ub(col[0], col[1], col[2], col[3] if k == 0 else col[3] * 2 // 3)
                    rl.rl_tex_coord2f(0, 0); rl.rl_vertex3f(cx - ca + sa, y, cz - sa - ca)
                    rl.rl_tex_coord2f(1, 0); rl.rl_vertex3f(cx + ca + sa, y, cz + sa - ca)
                    rl.rl_tex_coord2f(1, 1); rl.rl_vertex3f(cx + ca - sa, y, cz + sa + ca)
                    rl.rl_tex_coord2f(0, 1); rl.rl_vertex3f(cx - ca - sa, y, cz - sa + ca)
            rl.rl_end()
            rl.rl_set_texture(0)
        rl.rl_enable_depth_mask()

    @staticmethod
    def _kiosk(x, y, z, h):
        rl.rl_push_matrix()
        rl.rl_translatef(x, y, z)
        rl.rl_rotatef(-math.degrees(h), 0.0, 1.0, 0.0)
        rl.draw_cube(V3(0, 1.1, 0), 2.1, 2.2, 1.7, rl.Color(236, 226, 196, 255))
        rl.draw_cube(V3(0.08, 2.32, 0), 2.5, 0.16, 2.1, rl.Color(196, 40, 40, 255))
        rl.draw_cube(V3(1.06, 1.45, 0), 0.06, 0.7, 1.3, rl.Color(250, 214, 80, 255))        # serving window
        rl.draw_cube(V3(1.2, 1.12, 0), 0.34, 0.07, 1.4, rl.Color(150, 110, 70, 255))        # counter
        rl.draw_cube(V3(0, 2.62, 0), 0.9, 0.34, 0.12, rl.Color(250, 214, 80, 255))           # sign
        rl.rl_pop_matrix()

    def _in(self, x, z, rect, pad=6.0, gy=None):
        """gy: the thing's own height when it is known (cars, people): saves a ground_y lookup."""
        if not (rect[0] - pad < x < rect[2] + pad and rect[1] - pad < z < rect[3] + pad):
            return False
        fr = self.frustum
        if fr is None:
            return True
        if gy is None or gy != gy:
            gy = self.w.ground_y(x, z)
        return fr.sphere(x, gy + 2.0, z, pad + 4.0)      # behind / beside the camera (street views)      # behind / beside the camera (street views)

    def _shadow_batch(self, items):
        """Far-away shadows (off screen / beyond the full-model range): the footprint box swept along the sun direction by
        its height, i.e. the convex hull of the footprint and the footprint slid by the shadow vector, from the base."""
        sx, sz, k = self._sh_k
        rl.rl_disable_depth_mask()
        rl.rl_begin(rl.RL_TRIANGLES)
        for x, z, h, hl, hw, a, gy, ht in items:
            a = int(a * (0.4 + 0.6 * k))                    # at night only a faint contact patch remains
            if a <= 0:
                continue
            ca, sa = math.cos(h), math.sin(h)
            vx, vz = sx * ht, sz * ht
            fp = [(x + ca * lx - sa * lz, z + sa * lx + ca * lz) for lx, lz in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw))]
            hull = _hull(fp + [(px + vx, pz + vz) for px, pz in fp] if vx or vz else fp)
            # A convex polygon needs only n-2 triangles when anchored at a hull vertex.
            x0, z0 = hull[0]
            y = gy + 0.04
            rl.rl_color4ub(10, 10, 20, a)
            for i in range(1, len(hull) - 1):
                p0, p1 = hull[i], hull[i + 1]
                rl.rl_vertex3f(x0, y, z0)
                rl.rl_vertex3f(p1[0], y, p1[1])
                rl.rl_vertex3f(p0[0], y, p0[1])
        rl.rl_end()
        rl.rl_enable_depth_mask()

    def _shots(self, rect, sim):
        """Flying projectiles (short glowing streaks) and the bullet holes / scorch marks they left on walls."""
        sh = getattr(sim, "shots", None)
        if sh is None:
            return
        w = self.w
        for x, y, vx, vy, _tr, _re, _d, kind, z, *_src in sh.list:
            if self._in(x, y, rect):
                gy = w.ground_y(x, y) + z
                sp = math.hypot(vx, vy) or 1.0
                k = (1.6 if kind != "rocket" else 0.8) / sp
                if kind == "shell30":                        # 30 mm tracer: long, fat and bright, seen from the usual camera height
                    k = 6.0 / sp
                    for o_ in (-0.06, 0.0, 0.06):
                        rl.draw_line_3d(V3(x - vx * k, gy + o_, y - vy * k), V3(x, gy + o_, y), rl.Color(255, 200, 90, 255))
                    rl.draw_sphere(V3(x, gy, y), 0.28, rl.Color(255, 236, 160, 255))
                col = rl.Color(*projectiles.KINDS[kind][2], 255)
                if kind == "rocket":
                    rl.draw_cube(V3(x, gy, y), 0.35, 0.35, 0.35, rl.Color(80, 90, 50, 255))
                rl.draw_line_3d(V3(x - vx * k, gy, y - vy * k), V3(x, gy, y), col)
                rl.draw_cube(V3(x, gy, y), 0.09, 0.09, 0.09, col)
        for x, y, z, nx, ny, size, dark in sh.marks:
            if self._in(x, y, rect):
                gy = w.ground_y(x, y) + z
                c = rl.Color(30, 26, 22, 230) if dark else rl.Color(70, 64, 58, 230)
                rl.draw_cube(V3(x, gy, y), size * (1 - abs(nx)) + 0.02, size, size * (1 - abs(ny)) + 0.02, c)

    def _balls(self, rect, sim):
        """The kids' balls on the pitches."""
        kd = getattr(sim, "kids", None)
        for x, y, _vx, _vy, z, _vz in (kd.balls.values() if kd is not None else ()):
            if self._in(x, y, rect):
                rl.draw_sphere(V3(x, self.w.ground_y(x, y) + z + 0.11, y), 0.11, rl.Color(240, 240, 236, 255))

    def _garbage(self, rect, sim, t):
        """Waste containers (with the job a garbage truck is doing on one) and the amber beacons on the trucks."""
        g = getattr(sim, "garbage", None)
        if g is None:
            return
        w = self.w
        g.draw(rl, V3, w.ground_y, rect, t, self._sh_c)
        g.draw_beacons(rl, V3, sim.traffic.cars, w.ground_y, rect, t, fx.soft_id())

    def _fall_model(self, sp, v, lvl):
        """[solid, leaves] models of one tree species / variant for the trees that lie or tip over (made once)."""
        if not hasattr(self, "fall_models"):
            self.fall_models = {}
        e = self.fall_models.get((sp, v, lvl))
        if e is None:
            import treegen
            e = self.fall_models[(sp, v, lvl)] = [gl3d.tree_model(*a) if len(a[0]) else None for a in treegen.tree_mesh(sp, lvl, v)]
        return e

    def _actors(self, rect, sim, t):
        cam = self._cam
        w = self.w
        self._frames += 1
        self._sh_c = ((rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5)
        L = self.sun if self.sun is not None else gl3d.SUN
        k = self.sun_k
        sx, sz = (-L[0] / L[1], -L[2] / L[1]) if L[1] > 1e-6 else (0.0, 0.0)
        n = math.hypot(sx, sz)
        if n > 3.5:
            sx, sz = sx * 3.5 / n, sz * 3.5 / n
        self._sh_k = (sx * k, sz * k, k)                 # shadow slide per metre of height, no sun: straight down
        if self._frames % 240 == 0:
            self._free_orphans(sim.bodies)
        sh = []
        # pickups
        pk_glows = []
        for x, z, kind, alive, _t in sim.pickups:
            if not alive or not (rect[0] - 6.0 < x < rect[2] + 6.0 and rect[1] - 6.0 < z < rect[3] + 6.0):
                continue
            gy0 = w.ground_y(x, z)
            if self._in(x, z, rect, gy=gy0):
                m = self.pick_model(kind)
                if kind in weaponart.BOXES:                           # weapons: the real shape, big, slowly turning, over a glow disc
                    rl.draw_cylinder(V3(x, gy0 + 0.04, z), 0.9, 0.9, 0.03, 16, rl.Color(255, 200, 60, 90))
                    Mw = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(2.4, 2.4, 2.4), rl.matrix_rotate_x(1.45)),   # side face up, so the top view shows the shape
                                            rl.matrix_rotate_y(math.radians((t * 70 + x * 13) % 360)))
                    Mw = rl.matrix_multiply(Mw, rl.matrix_translate(x, gy0 + 1.0 + 0.15 * math.sin(t * 3 + x), z))
                    old_t = _keep(m.transform)
                    m.transform = Mw
                    rl.draw_model(m, V3(0, 0, 0), 1.0, WHITE)
                    m.transform = old_t[0]
                    pk_glows.append((V3(x, gy0 + 1.0, z), 4.0))        # one soft additive sprite, grows with distance
                else:
                    rl.draw_model_ex(m, V3(x, gy0 + 0.55 + 0.18 * math.sin(t * 3 + x), z), UP, (t * 90) % 360, V3(1.25, 1.25, 1.25), WHITE)
        self._indicator_glows(cam, pk_glows)
        # what is left of broken trees / posts / props (stump, bent pole, rubble): they stay, they just stop being solid
        for bx, bz, _r, _hi, bk, seed in w.broken:
            if self._in(bx, bz, rect):
                key = (bk, seed % 6 if bk == "mid" else 0)
                m = self.wreck_models.get(key)
                if m is None and key not in self.wreck_models:
                    family = "bark" if bk == "tree" else "metal"
                    m = self.wreck_models[key] = gl3d.object_detail(gl3d.wreck_model(bk, seed), family, seed)
                if m is not None:
                    rl.draw_model_ex(m, V3(bx, w.ground_y(bx, bz), bz), UP, float(seed % 360), ONE, WHITE)
        fl = getattr(w, "fallen", None)
        if fl and gl3d.tree_pack() is not None:                   # trees knocked over: they tip about their foot, then lie there
            now_ = time.monotonic()
            for fx_, fy_, sp_, v_, yaw_, sc_, dx_, dz_, t0_, bare_ in fl:
                if not self._in(fx_, fy_, rect, 8.0):
                    continue
                age = min(1.0, (now_ - t0_) / 1.5)
                ang = 82.0 * age * age
                ms = self._fall_model(sp_, v_, 4 if len(fl) < 12 else 3)
                M_ = rl.matrix_multiply(rl.matrix_scale(sc_, sc_, sc_), rl.matrix_rotate_y(-yaw_))
                M_ = rl.matrix_multiply(M_, rl.matrix_rotate(V3(dz_, 0, -dx_), math.radians(ang)))
                M_ = rl.matrix_multiply(M_, rl.matrix_translate(fx_, w.ground_y(fx_, fy_) + 0.9 * sc_ * age * age, fy_))
                for m_ in (ms[:1] if bare_ else ms):             # a tree stripped by an earlier hit lies bare
                    if m_ is not None:
                        old_t = _keep(m_.transform)
                        m_.transform = M_
                        rl.draw_model(m_, V3(0, 0, 0), 1.0, WHITE)
                        m_.transform = old_t[0]
        sg = getattr(w, "shedding", None)
        if sg and gl3d.tree_pack() is not None:                    # a tree losing its leaves: they go from the top down
            now_ = time.monotonic()
            for sx_, sy_, sp_, v_, yaw_, sc_, t0_, hh_, rr_, _c in list(sg.values()):
                if not self._in(sx_, sy_, rect, 8.0):
                    continue
                prog = min(1.0, (now_ - t0_) / w.SHED_T)
                M_ = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(sc_, sc_, sc_), rl.matrix_rotate_y(-yaw_)),
                                        rl.matrix_translate(sx_, w.ground_y(sx_, sy_), sy_))
                for i_, m_ in enumerate(self._fall_model(sp_, v_, 4)):
                    if m_ is not None:
                        gl3d.tree_cut(1e9 if i_ == 0 else hh_ * (1.0 - prog) ** 1.0)
                        old_t = _keep(m_.transform)
                        m_.transform = M_
                        rl.draw_model(m_, V3(0, 0, 0), 1.0, WHITE)
                        m_.transform = old_t[0]
                gl3d.tree_cut(1e9)
        for hx_, hy_, hz_, roof_ in getattr(sim, "helipads", ()):  # hospital helipads: grey disc with a white ring and H
            if self._in(hx_, hy_, rect):
                if roof_ is not None:                             # roof pad: a steel deck on posts, clear of the roof surface
                    rl.draw_cube(V3(hx_, (roof_ + hz_) / 2 - 0.3, hy_), 14.0, hz_ - roof_ + 0.6, 14.0, rl.Color(70, 72, 78, 255))
                g_ = hz_ + 0.06
                rl.draw_cylinder(V3(hx_, g_, hy_), 8.0, 8.0, 0.05, 28, rl.Color(96, 98, 104, 255))
                rl.draw_cylinder(V3(hx_, g_ + 0.04, hy_), 6.6, 6.6, 0.03, 28, rl.Color(236, 236, 240, 255))
                rl.draw_cylinder(V3(hx_, g_ + 0.06, hy_), 6.2, 6.2, 0.03, 28, rl.Color(96, 98, 104, 255))
                rl.draw_cube(V3(hx_, g_ + 0.1, hy_), 0.8, 0.04, 4.0, rl.Color(236, 236, 240, 255))
                rl.draw_cube(V3(hx_ - 1.4, g_ + 0.1, hy_), 0.8, 0.04, 4.0, rl.Color(236, 236, 240, 255))
                rl.draw_cube(V3(hx_ - 0.7, g_ + 0.1, hy_), 2.2, 0.04, 0.8, rl.Color(236, 236, 240, 255))
        self._heli_wind(sim)
        cmp_ = getattr(sim, "compounds", None)
        if cmp_ is not None and cmp_.list:                            # police stations and barracks: fences, gates, bunkers, signs
            if getattr(self, "cmp_art", None) is None:
                import compoundart
                self.cmp_art = compoundart.Art()
            fx_, fy_ = sim.focus()[:2]
            self.cmp_art.draw(cmp_, sim, w, lambda x_, y_, pad_: self._in(x_, y_, rect, pad_), fx_, fy_)
        st_ = getattr(sim, "heli_stairs", None)
        if st_:                                                       # steel stairs up to the roof helipads
            if getattr(self, "_stairs_m", None) is None:
                self._stairs_m = gl3d.stairs_model(st_)
            if self._stairs_m is not None:
                rl.draw_model(self._stairs_m, V3(0, 0, 0), 1.0, WHITE)
        # cars
        cars, doors, trailers, bus_bends, indicators = [], [], [], {}, {}
        for c in sim.traffic.cars:
            if self._in(c.x, c.y, rect, gy=c.gz):
                cars.append((c.x, c.y, c.h, self.ai_model(c.kind, c.color), WHITE, c.gz, c.pitch, c.roll, c.kind, c.str, c.color, id(c), c.v))
                if c.indicator:
                    indicators[id(c)] = (c.indicator, c.trh)
                if c.kind == vehicles.SEMI:
                    self._trailer(trailers, sh, c.x, c.y, c.h, c.trh if c.trh is not None else c.h, c.gz, c.pitch, c.roll, c.tgz, c.tpitch, c.troll, id(c))
                elif c.kind == vehicles.ARTIC_BUS:
                    bus_bends[id(c)] = math.remainder(c.trh - c.h, math.tau) if c.trh is not None else 0.0
                    if not self._near(c.x, c.y):
                        sh.extend((*part, 70, c.gz, vehicles.DIMS[c.kind][4]) for part in actors.parts(c))
                elif not self._near(c.x, c.y):
                    sh.append((c.x, c.y, c.h, vehicles.DIMS[c.kind][0] / 2, vehicles.DIMS[c.kind][1] / 2, 70, c.gz, vehicles.DIMS[c.kind][4]))
        for b in sim.bodies:
            if self._in(b.x, b.y, rect, gy=b.az):
                tint = WHITE if not b.exploded else rl.Color(70, 70, 70, 255)
                gy = b.az if b.az is not None else w.ground_y(b.x, b.y)
                m = self.car_model(b)
                if not (math.isfinite(b.pitch) and math.isfinite(b.roll)):     # a broken tilt would draw the car nowhere (only its shadow)
                    b.pitch = b.roll = 0.0
                if b.player_car and (m is None or not math.isfinite(gy)) and t - self._vanish_t > 5.0:
                    self._vanish_t = t
                    self.log(f"[vanish] player car not drawn: model {m is not None} own {b.model is not None} dirty {b.dirty} "
                             f"kind {b.kind} colour {b.color} y {gy}")
                cars.append((b.x, b.y, b.h, m, tint, gy, b.pitch, b.roll, b.kind, b.wheel,
                             b.color if b.model is None and b.color >= 0 and not b.exploded else None, id(b), math.hypot(b.vx, b.vy)))
                if b.indicator and b.alive and not b.exploded:
                    indicators[id(b)] = (b.indicator, b.trh)
                if b.door > 0.01:
                    doors.append((b, gy))
                if b.kind == vehicles.SEMI:
                    self._trailer(trailers, sh, b.x, b.y, b.h, b.trh if b.trh is not None else b.h, gy, b.pitch, b.roll, getattr(b, "tgz", None), getattr(b, "tpitch", None), getattr(b, "troll", None), id(b))
                elif b.kind == vehicles.ARTIC_BUS:
                    bus_bends[id(b)] = math.remainder(b.trh - b.h, math.tau) if b.trh is not None else 0.0
                    if not self._near(b.x, b.y):
                        sh.extend((*part, 80, gy, vehicles.DIMS[b.kind][4]) for part in actors.parts(b))
                elif not self._near(b.x, b.y):
                    sh.append((b.x, b.y, b.h, vehicles.DIMS[b.kind][0] / 2, vehicles.DIMS[b.kind][1] / 2, 80,
                               actors._heli_floor(b, w) if b.kind in vehicles.FLY else gy, vehicles.DIMS[b.kind][4]))
        # peds
        peds = []
        far2 = 90.0 ** 2 if self._ppm < 4.0 else 1e18                  # zoomed far out, people beyond 90 m from the view centre are 1-2 pixel dots: not worth a draw call each
        mcx, mcz = (rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5
        for p in sim.peds.list:
            if self._in(p.x, p.y, rect, gy=p.gz) and ((p.x - mcx) ** 2 + (p.y - mcz) ** 2 < far2 or p.mode in ("dead", "ko", "fight")):
                if p.mode in ("dead", "air"):
                    frame, y = 2, p.hy
                elif p.mode == "ko":
                    frame, y = 2, 0.0
                elif p.mode == "fight":
                    frame, y = (p.atk_kind if p.atk_t > 0 else self._gait(p.arch, p.anim, True)), 0.0
                elif p.mode == "rage":
                    frame, y = (3 if int(p.anim) & 1 else 0), 0.0
                elif getattr(p, "v", 1.0) < 0.1 and p.mode not in ("flee", "brawl"):
                    frame, y = 12, 0.0                             # standing still: arms down
                else:
                    frame, y = self._gait(p.arch, p.anim, p.traffic_run or p.mode in ("flee", "brawl")), (p.hy if p.vault > 0.0 else 0.0)
                    if p.vault > 0.0 and p.vault_up:
                        frame = 16
                    elif p.vault > 0.0:
                        frame = 40 + (int(p.anim * 3.0) & 7)       # ducking under a big vehicle: crawling
                lean = 0.0
                if p.pose == "spray":                              # fire fighter: arms out holding the nozzle
                    frame = 4
                elif p.pose == "work":                             # building site: hammering / shovelling, arms up and down
                    frame = 4 if int(p.anim * 2.4) & 1 else 12
                elif p.pose == "cpr":                              # medic kneeling over the patient, pumping
                    frame, lean, y = 4, -1.05 + 0.1 * math.sin(p.anim * 6.0), -0.3
                pg = p.gz if p.gz is not None else w.ground_y(p.x, p.y)
                peds.append((p.x, y + pg, p.y, p.h + p.spin, p.arch, p.shirt, frame, p.skin, lean, pg))
                if p.mode not in ("dead", "ko") and not self._near(p.x, p.y):
                    sh.append((p.x, p.y, p.h, 0.14, 0.24, 60, pg, 1.75))
        dogs = getattr(sim, "dogs", None)
        if dogs is not None:                                           # stray dogs: small, so culled early when zoomed out
            for d in dogs.live:
                if self._in(d.x, d.y, rect) and (d.x - mcx) ** 2 + (d.y - mcz) ** 2 < min(far2, 70.0 ** 2):
                    dm = self.dog_model(d.coat, dogs.frame(d, t))
                    if dm is not None:
                        dg = d.gz if d.gz is not None else w.ground_y(d.x, d.y)
                        rl.draw_model_ex(dm, V3(d.x, dg, d.y), UP, -math.degrees(d.h), V3(1.3, 1.3, 1.3), WHITE)           # a bit bigger than life: cute and readable from above
                        sh.append((d.x, d.y, d.h, 0.4 if d.pose != "sleep" else 0.32, 0.22, 55, dg, 0.55 if d.pose != "sleep" else 0.25))
        birds = getattr(sim, "birds", None)
        if birds is not None:                                          # ducks, pigeons, crows: tiny, culled early
            for b in birds.live:
                if self._in(b.x, b.y, rect) and (b.x - mcx) ** 2 + (b.y - mcz) ** 2 < min(far2, 60.0 ** 2):
                    bm = self.bird_model(b.art, birds.frame(b))
                    if bm is not None:
                        sc = 1.9 * birdart.SIZE[b.art]
                        rl.draw_model_ex(bm, V3(b.x, b.z, b.y), UP, -math.degrees(b.h), V3(sc, sc, sc), WHITE)
                        if b.state not in ("fly", "land"):
                            sh.append((b.x, b.y, b.h, 0.25 * sc, 0.15 * sc, 50, b.z, 0.2 * sc))
        cb = sim.car
        if sim.mode == "car" and cb is not None and cb.kind in vehicles.BIKES and getattr(sim, "riding", None) is None:
            gy = cb.az if cb.az is not None else w.ground_y(cb.x, cb.y)       # you, sitting on (or standing on) the two-wheeler
            seat = vehicles.EXTRA[cb.kind] != "kick"
            peds.append((cb.x - math.cos(cb.h) * (0.3 if seat else 0.0), gy + (0.0 if seat else 0.2), cb.y - math.sin(cb.h) * (0.3 if seat else 0.0),
                         cb.h, 100 + getattr(sim, "lik", 0), 0, 13 if seat else 12, 3, 0.0, gy))
        for rp in getattr(sim, "remote_foot", {}).values():            # other players on foot (multiplayer)
            if self._in(rp["x"], rp["y"], rect):
                fr = rp["frame"] if rp["frame"] is not None else self._gait(100 + rp["lik"], rp["anim"], rp["run"])
                gy = rp["z"] or w.ground_y(rp["x"], rp["y"])
                weapon = rp.get("weapon")
                peds.append((rp["x"], gy, rp["y"], rp["h"], 100 + rp["lik"], 0, fr, 3, 0.0, gy,
                             weapon if weapon in weaponart.BOXES and fr != 2 else None))
                if not self._near(rp["x"], rp["y"]):
                    sh.append((rp["x"], rp["y"], rp["h"], 0.14, 0.24, 60, gy, 1.75))
        wk = sim.walker
        if sim.mode == "foot" and wk is not None and not getattr(wk, "hidden", False):   # hidden: inside a POI
            frame = self._gait(100 + getattr(sim, "lik", 0), wk.anim, wk.speed > 6.0 or wk.esc_on or wk.stair) if wk.moving else 12
            swinging = wk.atk_t > 0 and wk.weapon in actors.SWINGERS and wk.ammo > 0
            if wk.atk_t > 0:
                frame = 60 + min(7, int((1.0 - wk.atk_t / actors.SWING_T) * 8)) if swinging else wk.atk_kind   # bat: arms and torso swing with it
            if wk.z > 0.35 or getattr(wk, "vz", 0.0) > 1.0:   # a real jump / fall, not a step off a kerb or a slope
                frame = 16                                 # jumping: upright, arms up, knees tucked
            if wk.duck_t > 0.0:
                frame = 40 + (int(wk.anim * 3.0) & 7)      # crawling under a big vehicle: face down, limbs animated
            if wk.health <= 0:
                frame = 2
            bp_ = sim.compounds.busted_pose() if getattr(sim, "compounds", None) is not None else 0
            if bp_:
                frame = 3 if bp_ == 1 else 12                  # hands up, then hands behind the back in cuffs
            if bp_ == 2:
                gyc_ = wk.az if wk.az is not None else w.ground_y(wk.x, wk.y)
                bx_, by_ = wk.x - math.cos(wk.h) * 0.2, wk.y - math.sin(wk.h) * 0.2
                for s_ in (-0.07, 0.07):
                    rl.draw_cube(V3(bx_ - math.sin(wk.h) * s_, gyc_ + 0.86, by_ + math.cos(wk.h) * s_), 0.07, 0.07, 0.07, rl.Color(200, 202, 210, 255))
            if wk.hurt_t > 0 and int(t * 20) & 1 and wk.health > 0:
                pass                                       # flicker while hurt
            else:
                weapon = (wk.weapon if wk.health > 0 and wk.weapon in weaponart.BOXES
                          and (wk.weapon in actors.MELEE or wk.ammo > 0) else None)
                feet = wk.az if wk.az is not None else w.ground_y(wk.x, wk.y)
                peds.append((wk.x, feet, wk.y, wk.h, 100 + getattr(sim, "lik", 0), 0, frame, 3, 0.0,
                             feet - wk.z if wk.az is not None else feet, weapon))
            if not self._near(wk.x, wk.y):
                sh.append((wk.x, wk.y, wk.h, 0.14, 0.24, 70 if wk.z < 0.1 else 40, (wk.az - wk.z) if wk.az is not None else 0.0, 1.75 + wk.z))
        for kx, kz, kh in sim.kiosks:
            if self._in(kx, kz, rect):
                self._kiosk(kx, w.ground_y(kx, kz), kz, kh)
        if AUDIT3D and self._frames % 30 == 0:
            self._audit3d(cars, trailers, peds)
        if self.shadows:
            self._shadow_batch(sh)
        self._draw_vehicle_models(sim, cars, trailers, indicators, bus_bends, doors)
        self._draw_ped_models(peds)
        self._service_hoses(sim, rect)
        for f in sim.chaos.fly:                                      # punched / blasted props tumbling through the air
            if self._in(f[0], f[1], rect):
                rl.rl_push_matrix()
                rl.rl_translatef(f[0], f[2], f[1])
                rl.rl_rotatef(f[6], 0.6, 0.3, 0.74)
                rl.draw_cube(V3(0, 0, 0), f[8], f[9], f[8], rl.Color(f[10][0], f[10][1], f[10][2], 255))
                rl.rl_pop_matrix()

        # the player's marker shines through the bridge deck when they are underneath it
        if sim.mode == "foot" and sim.walker is not None and sim.walker.az is not None:
            mx, mz, maz = sim.walker.x, sim.walker.y, sim.walker.az
        elif sim.mode == "car" and sim.car is not None and sim.car.az is not None:
            mx, mz, maz = sim.car.x, sim.car.y, sim.car.az
        else:
            return
        dk = w.deck_h(mx, mz)
        if dk is not None and maz < dk - 0.7:
            rl.rl_draw_render_batch_active()
            rl.rl_disable_depth_test()
            rl.draw_cylinder(V3(mx, maz + 0.1, mz), 0.9, 0.9, 0.04, 20, rl.Color(255, 220, 60, 120))
            rl.draw_circle_3d(V3(mx, maz + 0.16, mz), 1.2, V3(1, 0, 0), 90.0, rl.Color(255, 240, 120, 255))
            rl.rl_draw_render_batch_active()
            rl.rl_enable_depth_test()

    def _service_hoses(self, sim, rect):
        """A fire engine feeds one main hose to the fire, with a branch to each firefighter."""
        w = self.w
        for j in sim.services.jobs:
            b = j.body
            if j.kind != "fire" or j.state != "work" or b is None or not j.crew:
                continue
            tgt = j.target
            if max(rect[0], min(b.x, tgt.x)) > min(rect[2], max(b.x, tgt.x)) + 8.0 or \\
                    max(rect[1], min(b.y, tgt.y)) > min(rect[3], max(b.y, tgt.y)) + 8.0:
                continue
            start = (b.x - math.cos(b.h) * vehicles.DIMS[b.kind][0] * 0.38,
                     b.y - math.sin(b.h) * vehicles.DIMS[b.kind][0] * 0.38)
            hub = (tgt.x, tgt.y)

            truck_y = b.az if b.az is not None else w.ground_y(*start)
            hub_y = getattr(tgt, "az", None)
            if hub_y is None:
                hub_y = w.level(*hub, truck_y)

            def hose(a, z, height_a, height_z):
                x0, y0 = a
                x1, y1 = z
                length = math.hypot(x1 - x0, y1 - y0) or 1.0
                ox, oz = -(y1 - y0) / length * 0.035, (x1 - x0) / length * 0.035
                for lift, col in ((0.055, rl.Color(32, 38, 44, 255)), (0.095, rl.Color(150, 157, 164, 255))):
                    prev = None
                    for k in range(13):
                        u = k / 12.0
                        x, z_ = x0 + (x1 - x0) * u + ox, y0 + (y1 - y0) * u + oz
                        expected = height_a + (height_z - height_a) * u
                        ground = w.level(x, z_, expected)
                        point = V3(x, ground + lift, z_)
                        if prev is not None:
                            rl.draw_line_3d(prev, point, col)
                        prev = point

            hose(start, hub, truck_y, hub_y)
            for c in j.crew:
                worker_y = c.gz if c.gz is not None else w.level(c.x, c.y, hub_y)
                hose(hub, (c.x, c.y), hub_y, worker_y)

    def _draw_vehicle_models(self, sim, cars, trailers, indicators, bus_bends, doors):
        cam = self._cam
        fr = self.frustum
        now_ = time.perf_counter()
        sdt_ = min(0.1, now_ - getattr(self, "_spin_t", now_))
        self._spin_t = now_
        spin_ = getattr(self, "_spin", None)
        if spin_ is None or len(spin_) > 800:
            spin_ = self._spin = {}
        if trailers:
            if self.trailer_m is None:
                self.trailer_m = gl3d.trailer_model()
            tm = self.trailer_m
            old = _keep(tm.transform)
            if self.trailer_ax is None:
                self.trailer_ax = gl3d.trailer_axles()
            tax, trr, twm = self.trailer_ax
            for x, z, h, gy, pitch, roll, tkey in trailers:
                tm.transform = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_x(roll), rl.matrix_rotate_z(pitch)),
                                                                     rl.matrix_rotate_y(-h)), rl.matrix_translate(x, gy, z))
                rl.draw_model(tm, V3(0, 0, 0), 1.0, WHITE)
                if self._near(x, z):
                    self._proj_shadow(tm, tm.transform, gy, 70)
                Mt, old_w = tm.transform, _keep(twm.transform)
                for axx in tax:                              # trailer wheels roll with the tractor's
                    twm.transform = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(-spin_.get(tkey, 0.0)), rl.matrix_translate(axx, trr, 0.0)), Mt)
                    rl.draw_model(twm, V3(0, 0, 0), 1.0, WHITE)
                twm.transform = old_w[0]
            tm.transform = old[0]
        wheels = Batch()
        blink_start, this_blink, indicator_glows = getattr(self, "_indicator_blinks", {}), {}, []
        for x, z, h, m, tint, gy, pitch, roll, kind, ang, col, ckey, cspd in cars:
            if m is None:
                continue
            M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_x(roll), rl.matrix_rotate_z(pitch)),
                                                      rl.matrix_rotate_y(-h)), rl.matrix_translate(x, gy, z))
            hf_ = None
            if kind in vehicles.FLY:                             # helicopter: the shadow falls on the ground or roof below it
                hb_ = next((b_ for b_ in sim.bodies if id(b_) == ckey), None)
                hf_ = self.w.ground_y(x, z)
                rt_ = actors._bld_top(self.w, x, z)
                if rt_ is not None and rt_ <= gy + 0.7:
                    hf_ = max(hf_, rt_)
            if self._near(x, z):
                self._proj_shadow(m, M, hf_ if hf_ is not None else gy, 75)
            rear_basis = M
            if kind == vehicles.ARTIC_BUS:
                rear_basis = self._bus_rear(M, bus_bends[ckey], x, z, gy, tint)
            if ckey in indicators:
                side, rear_heading = indicators[ckey]
                old_side, start = blink_start.get(ckey, (side, now_))
                start = now_ if old_side != side else start
                this_blink[ckey] = side, start
                if (now_ - start) % 0.72 < 0.39:
                    length = gl3d.visual_dims(kind)[0]
                    nose, bumper = length * 0.5, -length * 0.5
                    if kind == vehicles.SEMI:
                        hinge = vehicles.SEMI_HITCH
                        offset = (h if rear_heading is None else rear_heading) - h
                        rear_basis = rl.matrix_multiply(rl.matrix_multiply(
                            rl.matrix_multiply(rl.matrix_translate(-hinge, 0, 0), rl.matrix_rotate_y(-offset)),
                            rl.matrix_translate(hinge, 0, 0)), M)
                        nose = vehicles.SEMI_SHIFT + vehicles.SEMI_TRACTOR_L * 0.5
                        bumper = hinge - vehicles.SEMI_TRAILER_L
                    front, tail = gl3d.indicator_mounts(kind)
                    self._indicator_lens(cam, M, front, side, 1, indicator_glows, nose)
                    self._indicator_lens(cam, rear_basis, tail, side, -1, indicator_glows, bumper)
            if col is not None and fr is not None and kind != vehicles.ARTIC_BUS and kind not in vehicles.BIKES and kind not in vehicles.FLY:
                px, py, pz = fr.p
                if vehicles.DIMS[kind][0] * fr.fpx < self.LOD_PX * math.sqrt((x - px) ** 2 + (gy - py) ** 2 + (z - pz) ** 2):
                    ml = self.car_lod(kind, col)
                    if ml is not None:                       # small on screen: one model, front wheels straight
                        old = _keep(ml.transform)
                        ml.transform = M
                        rl.draw_model(ml, ZERO, 1.0, tint)
                        ml.transform = old[0]
                        continue
            old = _keep(m.transform)
            m.transform = M                                  # tilt with the slope: roll, pitch, heading, then move
            rl.draw_model(m, V3(0, 0, 0), 1.0, tint)
            m.transform = old[0]
            if kind in vehicles.FLY:                         # helicopter: spinning main and tail rotor
                rot = next((b_.rotor for b_ in sim.bodies if id(b_) == ckey), 0.0)
                for tail in (False, True):
                    rk = ("rotor", kind, tail)
                    rm = self.car_models.get(rk)
                    if rm is None:
                        rm = self.car_models[rk] = gl3d.rotor_model(kind, tail)
                    if rm is None:
                        continue
                    if tail:
                        L_ = rl.matrix_multiply(rl.matrix_rotate_z(rot * 1.7), rl.matrix_translate(-7.0, 2.15, -0.32))
                    else:
                        L_ = rl.matrix_multiply(rl.matrix_rotate_y(rot), rl.matrix_translate(-0.6, 2.9, 0.0))
                    oldr = _keep(rm.transform)
                    rm.transform = rl.matrix_multiply(L_, M)
                    rl.draw_model(rm, V3(0, 0, 0), 1.0, tint)
                    if hf_ is not None and self._near(x, z):
                        self._proj_shadow(rm, rm.transform, hf_, 55)
                    rm.transform = oldr[0]
            if kind == vehicles.BTR:                         # БТР-80: the turret turns on its ring
                tb_ = next((b_ for b_ in sim.bodies if id(b_) == ckey), None)
                tm_ = self.car_models.get("turret")
                if tm_ is None:
                    tm_ = self.car_models["turret"] = gl3d.turret_model()
                if tm_ is not None:
                    Lt_ = rl.matrix_multiply(rl.matrix_rotate_y(-getattr(tb_, "turret", 0.0)), rl.matrix_translate(gl3d.APC_TURRET[0], gl3d.APC_TURRET[1], 0.0))
                    oldt_ = _keep(tm_.transform)
                    tm_.transform = rl.matrix_multiply(Lt_, M)
                    rl.draw_model(tm_, V3(0, 0, 0), 1.0, tint)
                    tm_.transform = oldt_[0]
            fw = self.front_wheels.get(kind)
            if fw is None:
                fw = self.front_wheels[kind] = gl3d.front_wheel(kind) if kind not in vehicles.FLY else (0, 0, 0, None)
            wx, wr, hz, wm = fw
            if wm is None:
                continue
            sp_ = spin_[ckey] = (spin_.get(ckey, 0.0) + cspd * sdt_ / max(0.1, wr)) % 6.2831853       # rolled distance / radius: the rim turns
            for sd in ((-hz, hz) if hz else (0.0,)):                             # front wheels turned about their own centres by the steering angle
                wheels.add(wm, rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(-sp_), rl.matrix_rotate_y(-ang)),
                                                                     rl.matrix_translate(wx, wr, sd)), M), tint)     # all wheels of a kind: one draw call
            if True:                                         # the other axles: one model per axle, spun about its own centre
                ra = self.rear_axle_models.get(kind)
                if ra is None:
                    ra = self.rear_axle_models[kind] = gl3d.rear_axles(kind)
                for i_, (ax_, rr_, _z, am_) in enumerate(ra):
                    if am_ is None:
                        continue
                    if i_ == 0 and kind == vehicles.BTR:           # БТР-80: the second axle steers too, less than the first (turn centre between axles 3 and 4)
                        for sd in (-hz, hz):
                            wheels.add(wm, rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(-sp_), rl.matrix_rotate_y(-ang * 0.6)),
                                                                                 rl.matrix_translate(ax_, rr_, sd)), M), tint)
                        continue
                    base = rear_basis if kind == vehicles.ARTIC_BUS and i_ == 1 else M
                    wheels.add(am_, rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(-sp_ * wr / max(0.1, rr_)), rl.matrix_translate(ax_, rr_, 0.0)), base), tint)
        wheels.flush()
        self._indicator_blinks = this_blink
        self._indicator_glows(cam, indicator_glows)
        for b, gy in doors:                                  # carjack: the driver's door swung out on its hinge
            key = ("door", b.kind, b.color)
            m = self.car_models.get(key)
            if m is None:
                m = self.car_models[key] = gl3d.door_model(b.kind, b.color)
            if m is None:
                continue
            hx, _dl = gl3d.door_geom(b.kind)
            W = gl3d.visual_dims(b.kind)[1]
            ang = -1.25 * b.door * (1.0 - 0.15 * (1.0 - b.door))
            M = rl.matrix_multiply(rl.matrix_rotate_y(ang), rl.matrix_translate(hx, 0.0, -(W / 2 + 0.03)))
            M = rl.matrix_multiply(M, rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_x(b.roll), rl.matrix_rotate_z(b.pitch)),
                                                                          rl.matrix_rotate_y(-b.h)), rl.matrix_translate(b.x, gy, b.y)))
            old = _keep(m.transform)
            m.transform = M
            rl.draw_model(m, V3(0, 0, 0), 1.0, WHITE)
            m.transform = old[0]

    def _draw_ped_models(self, peds):
        fr = self.frustum
        px, py, pz = fr.p
        for x, y, z, h, arch, tone, frame, skin, *ex in peds:
            tier = 1
            if self.ped_detail > 1:
                distance = math.sqrt((x-px)**2 + (y+.8-py)**2 + (z-pz)**2)
                height_px = 1.75 * gl3d.ped_scale(arch) * fr.fpx / max(.25, distance)
                tier = character_tier(height_px, self.ped_detail, self.ped_quality)
            pm, grip, shown_frame = self.ped_model(arch, tone, frame, skin, tier)
            if pm is not None:
                if frame != 2 and len(ex) > 1 and self._near(x, z):
                    M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(ex[0]), rl.matrix_rotate_y(-h)), rl.matrix_translate(x, y, z))
                    self._proj_shadow(pm, M, ex[1], 60)
                else:
                    M = None
                if ex and ex[0]:                                     # leaning over (CPR): tilt about the feet, then heading
                    if M is None:
                        M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(ex[0]), rl.matrix_rotate_y(-h)), rl.matrix_translate(x, y, z))
                    old = _keep(pm.transform)
                    pm.transform = M
                    rl.draw_model(pm, V3(0, 0, 0), 1.0, WHITE)
                    pm.transform = old[0]
                else:
                    rl.draw_model_ex(pm, V3(x, y, z), UP, -math.degrees(h), ONE, WHITE)
                if len(ex) > 2 and ex[2] is not None and grip is not None:
                    self._held(ex[2], x, y, z, h, shown_frame, grip)
