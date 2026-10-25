"""3D drawing: ground chunk quads, streamed building/tree meshes, cars with dents, pedestrians, pickups, shadows."""
import math

import numpy as np
import pyray as rl

import actors
import gl3d
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
        self.car_models = {}
        self.front_wheels = {}        # kind -> (axle x, radius, track half, model)
        self._own = {}                         # id(body) -> body with its own model
        self._frames = 0
        self.log, self._vanish_t = print, -99.0          # main points log at logs/game.log
        self.ped_models = {}
        self.pick_models = {}
        self.wreck_models = {}
        self.t = 0.0
        self.drawn_chunks = 0
        self.drawn_meshes = 0

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
                g = w.tgrid
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
                                     b.color < 0, True)
            b.dirty = False
            self._own[id(b)] = b
        if b.model is not None:
            return b.model
        if b.color >= 0:                                   # plain car: shared model, built within the per-frame budget
            return self.ai_model(b.kind, b.color)
        key = (b.kind, b.color)
        m = self.car_models.get(key)
        if m is None:
            m = self.car_models[key] = gl3d.car_model(b.kind, b.color, (), 0.0, True, True)
        return m

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

    def ai_model(self, kind, color):
        key = (kind, color)
        m = self.car_models.get(key)
        if m is None:
            if self._built >= self.BUILD_BUDGET:                 # over budget: show the plain-paint version for now
                m = self.car_models.get((kind, 0))
                if m is not None:
                    return m                                      # (none yet: build it now, a car is never invisible)
            self._built += 1
            m = self.car_models[key] = gl3d.car_model(kind, color, (), 0.0, False, True)
        return m

    @staticmethod
    def _gait(arch, anim, run):
        """Frame of the walk / run cycle: four poses per stride for people, two for riders and carts."""
        if 10 <= arch < 100 and vehicles.PED_IDS[arch] in vehicles.RIDERS:
            return int(anim * 2.2) & 1
        # one stride cycle (two steps) per ~1.5 m walking, ~2.6 m running: eight phases each
        return (30 if run else 20) + (int(anim * (8 / 2.6 if run else 8 / 1.5)) & 7)

    def ped_model(self, arch, tone, frame, skin):
        key = (arch, tone, frame, skin)
        m = self.ped_models.get(key)
        if m is None:
            if self._built >= self.BUILD_BUDGET:
                fb = self.ped_models.get((arch, 0, frame, 0)) or self.ped_models.get((arch, 0, 0, 0))
                if fb is not None:
                    return fb                                  # (none yet: build it now, a person is never just a shadow)
            self._built += 1
            m = self.ped_models[key] = gl3d.ped_model(arch, tone, frame, skin)
        return m

    def pick_model(self, kind):
        m = self.pick_models.get(kind)
        if m is None:
            m = self.pick_models[kind] = gl3d.pickup_model(kind)
        return m

    # ---------------------------------------------------------------- scene
    def draw(self, cam, H, rect, ppm, sim, particles, t, show_meshes=True, near=2.0, far_overview=False):
        self._built = 0
        self._ppm = ppm
        w, st = self.w, self.st
        S = w.chunk
        self.t = t
        gl3d.ground_time(t)
        rl.rl_set_clip_planes(near, H * 4 + 400)
        rl.begin_mode_3d(cam)
        try:
            rl.rl_disable_backface_culling()
            lod = ppm >= LOD_PPM
            drawn = 0
            missing = not lod
            if lod:
                x0, x1 = math.floor((rect[0]) / S), math.floor(rect[2] / S)
                y0, y1 = math.floor((rect[1]) / S), math.floor(rect[3] / S)
                for cx in range(x0, x1 + 1):
                    for cy in range(y0, y1 + 1):
                        gm = st.get_ground_model((cx, cy))
                        if gm is not None:
                            rl.draw_model(gm, V3(0, 0, 0), 1.0, WHITE)
                            drawn += 1
                        else:
                            missing = True
            if missing or far_overview:                    # the coarse whole-city model is only seen where a chunk is not baked yet
                self._overview()
            self.drawn_chunks = drawn
            nm = 0
            if lod and show_meshes:
                for key, (models, _last) in list(st.meshes.items()):
                    ch = w.chunks.get(key)
                    bb = ch["bb"] if ch else None
                    if bb is None or bb[2] < rect[0] or bb[0] > rect[2] or bb[3] < rect[1] or bb[1] > rect[3]:
                        continue
                    for m in models.values():
                        rl.draw_model(m, V3(0, 0, 0), 1.0, WHITE)
                    nm += 1
                    _last_touch = st.meshes[key]
                    _last_touch[1] = st.frame
            self.drawn_meshes = nm
            if lod:
                if getattr(w, "roads3d", False):
                    self._decals(rect)
                self._actors(rect, sim, t)
                self._shots(rect, sim)
                self._balls(rect, sim)
                if getattr(sim, "lights", None) is not None:
                    sim.lights.draw(rect, w.ground_y)
                if getattr(sim, "trains", None) is not None:
                    sim.trains.draw(rect, w.ground_y)
                particles.draw()
        finally:
            rl.end_mode_3d()

    def _decals(self, rect):
        """Skid marks, blood and scorch as flat quads just above the 3D road surface."""
        w = self.w
        S = w.chunk
        rl.rl_disable_depth_mask()
        rl.rl_begin(rl.RL_QUADS)
        n = 0
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
                        _, x, z, r, col = d
                        y = w.ground_y(x, z) + 0.035
                        rl.rl_color4ub(col[0], col[1], col[2], col[3])
                        for k in range(2):                       # an octagon-ish blob from two rotated squares
                            a = k * math.pi / 4
                            ca, sa = math.cos(a) * r, math.sin(a) * r
                            rl.rl_vertex3f(x - ca + sa, y, z - sa - ca); rl.rl_vertex3f(x + ca + sa, y, z + sa - ca)
                            rl.rl_vertex3f(x + ca - sa, y, z + sa + ca); rl.rl_vertex3f(x - ca - sa, y, z - sa + ca)
                    n += 1
                    if n > 2500:
                        break
        rl.rl_end()
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

    def _in(self, x, z, rect, pad=6.0):
        return rect[0] - pad < x < rect[2] + pad and rect[1] - pad < z < rect[3] + pad

    def _shadow_batch(self, items):
        rl.rl_disable_depth_mask()
        rl.rl_begin(rl.RL_QUADS)
        for x, z, h, hl, hw, a, gy in items:
            ca, sa = math.cos(h), math.sin(h)
            x += 0.5
            z += 0.4
            rl.rl_color4ub(10, 10, 20, a)
            for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                lx, lz = sx * hl, sz * hw
                rl.rl_vertex3f(x + ca * lx - sa * lz, gy + 0.18, z + sa * lx + ca * lz)
        rl.rl_end()
        rl.rl_enable_depth_mask()

    def _shots(self, rect, sim):
        """Flying projectiles (short glowing streaks) and the bullet holes / scorch marks they left on walls."""
        sh = getattr(sim, "shots", None)
        if sh is None:
            return
        w = self.w
        for x, y, vx, vy, _tr, _re, _d, kind, z in sh.list:
            if self._in(x, y, rect):
                gy = w.ground_y(x, y) + z
                sp = math.hypot(vx, vy) or 1.0
                k = (1.6 if kind != "rocket" else 0.8) / sp
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

    def _actors(self, rect, sim, t):
        w = self.w
        self._frames += 1
        if self._frames % 240 == 0:
            self._free_orphans(sim.bodies)
        sh = []
        # pickups
        for x, z, kind, alive, _t in sim.pickups:
            if alive and self._in(x, z, rect):
                m = self.pick_model(kind)
                gy0 = w.ground_y(x, z)
                if kind in weaponart.BOXES:                           # weapons: the real shape, big, slowly turning, over a glow disc
                    rl.draw_cylinder(V3(x, gy0 + 0.04, z), 0.9, 0.9, 0.03, 16, rl.Color(255, 200, 60, 90))
                    Mw = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(2.4, 2.4, 2.4), rl.matrix_rotate_x(1.45)),   # side face up, so the top view shows the shape
                                            rl.matrix_rotate_y(math.radians((t * 70 + x * 13) % 360)))
                    Mw = rl.matrix_multiply(Mw, rl.matrix_translate(x, gy0 + 1.0 + 0.15 * math.sin(t * 3 + x), z))
                    old_t = m.transform
                    m.transform = Mw
                    rl.draw_model(m, V3(0, 0, 0), 1.0, WHITE)
                    m.transform = old_t
                else:
                    rl.draw_model_ex(m, V3(x, gy0 + 0.55 + 0.18 * math.sin(t * 3 + x), z), UP, (t * 90) % 360, V3(1.25, 1.25, 1.25), WHITE)
        # what is left of broken trees / posts / props (stump, bent pole, rubble): they stay, they just stop being solid
        for bx, bz, _r, _hi, bk, seed in w.broken:
            if self._in(bx, bz, rect):
                key = (bk, seed % 6 if bk == "mid" else 0)
                m = self.wreck_models.get(key)
                if m is None and key not in self.wreck_models:
                    m = self.wreck_models[key] = gl3d.wreck_model(bk, seed)
                if m is not None:
                    rl.draw_model_ex(m, V3(bx, w.ground_y(bx, bz), bz), UP, float(seed % 360), ONE, WHITE)
        # cars
        cars, doors = [], []
        for c in sim.traffic.cars:
            if self._in(c.x, c.y, rect):
                cars.append((c.x, c.y, c.h, self.ai_model(c.kind, c.color), WHITE, c.gz, c.pitch, c.roll, c.kind, c.str))
                sh.append((c.x, c.y, c.h, vehicles.HALF_L[c.kind], 1.0, 70, c.gz))
        for b in sim.bodies:
            if self._in(b.x, b.y, rect):
                tint = WHITE if not b.exploded else rl.Color(70, 70, 70, 255)
                gy = b.az if b.az is not None else w.ground_y(b.x, b.y)
                m = self.car_model(b)
                if not (math.isfinite(b.pitch) and math.isfinite(b.roll)):     # a broken tilt would draw the car nowhere (only its shadow)
                    b.pitch = b.roll = 0.0
                if b.player_car and (m is None or not math.isfinite(gy)) and t - self._vanish_t > 5.0:
                    self._vanish_t = t
                    self.log(f"[vanish] player car not drawn: model {m is not None} own {b.model is not None} dirty {b.dirty} "
                             f"kind {b.kind} colour {b.color} y {gy}")
                cars.append((b.x, b.y, b.h, m, tint, gy, b.pitch, b.roll, b.kind, b.wheel))
                if b.door > 0.01:
                    doors.append((b, gy))
                hl = vehicles.HALF_L[b.kind] + 0.1
                sh.append((b.x, b.y, b.h, hl, 1.0, 80, gy))
        # peds
        peds = []
        far2 = 90.0 ** 2 if self._ppm < 4.0 else 1e18                  # zoomed far out, people beyond 90 m from the view centre are 1-2 pixel dots: not worth a draw call each
        mcx, mcz = (rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5
        for p in sim.peds.list:
            if self._in(p.x, p.y, rect) and ((p.x - mcx) ** 2 + (p.y - mcz) ** 2 < far2 or p.mode in ("dead", "ko", "fight")):
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
                    frame, y = self._gait(p.arch, p.anim, p.mode in ("flee", "brawl")), 0.0
                lean = 0.0
                if p.pose == "spray":                              # fire fighter: arms out holding the nozzle
                    frame = 4
                elif p.pose == "work":                             # building site: hammering / shovelling, arms up and down
                    frame = 4 if int(p.anim * 2.4) & 1 else 12
                elif p.pose == "cpr":                              # medic kneeling over the patient, pumping
                    frame, lean, y = 4, -1.05 + 0.1 * math.sin(p.anim * 6.0), -0.3
                pg = p.gz if p.gz is not None else w.ground_y(p.x, p.y)
                peds.append((p.x, y + pg, p.y, p.h + p.spin, p.arch, p.shirt, frame, p.skin, lean))
                if p.mode not in ("dead", "ko"):
                    sh.append((p.x, p.y, 0, 0.35, 0.35, 60, pg))
        cb = sim.car
        if sim.mode == "car" and cb is not None and cb.kind in vehicles.BIKES and getattr(sim, "riding", None) is None:
            gy = cb.az if cb.az is not None else w.ground_y(cb.x, cb.y)       # you, sitting on (or standing on) the two-wheeler
            seat = vehicles.EXTRA[cb.kind] != "kick"
            peds.append((cb.x - math.cos(cb.h) * (0.3 if seat else 0.0), gy + (0.0 if seat else 0.2), cb.y - math.sin(cb.h) * (0.3 if seat else 0.0),
                         cb.h, 100 + getattr(sim, "lik", 0), 0, 13 if seat else 12, 3))
        wk = sim.walker
        if sim.mode == "foot" and wk is not None and not getattr(wk, "hidden", False):   # hidden: inside a POI
            frame = self._gait(100, wk.anim, wk.speed > 6.0) if wk.moving else 12
            if wk.atk_t > 0:
                frame = wk.atk_kind
            if wk.z > 0.05:
                frame = 3
            if wk.health <= 0:
                frame = 2
            if wk.hurt_t > 0 and int(t * 20) & 1 and wk.health > 0:
                pass                                       # flicker while hurt
            else:
                peds.append((wk.x, wk.az if wk.az is not None else w.ground_y(wk.x, wk.y), wk.y, wk.h, 100 + getattr(sim, "lik", 0), 0, frame, 3))
            if wk.health > 0 and wk.weapon in weaponart.BOXES and (wk.weapon in actors.MELEE or wk.ammo > 0):
                wm = self.pick_model(wk.weapon)                  # the chosen weapon in the right hand (body-local: x forward, z to the side)
                if wm is not None:
                    sw_ = 0.12 * math.sin(wk.anim * 4.8) if wk.moving else 0.0
                    tilt, yaw = 0.8, 0.0
                    if wk.weapon in actors.MELEE and wk.atk_t > 0:      # bat swing: wound up behind the right shoulder, sweeps across the front
                        u = 1.0 - wk.atk_t / actors.SWING_T
                        e = u * u * (3 - 2 * u)
                        tilt, yaw = 0.3 + 1.1 * math.sin(math.pi * min(1.0, u * 1.3)), 1.4 - 2.9 * e
                    Mh = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(1.1, 1.1, 1.1), rl.matrix_rotate_x(tilt)),
                                            rl.matrix_multiply(rl.matrix_multiply(rl.matrix_translate(0.28 + sw_, 0.8, 0.36), rl.matrix_rotate_y(yaw)),
                                                               rl.matrix_rotate_y(-wk.h)))
                    Mh = rl.matrix_multiply(Mh, rl.matrix_translate(wk.x, wk.az if wk.az is not None else w.ground_y(wk.x, wk.y), wk.y))
                    old_t = wm.transform
                    wm.transform = Mh
                    rl.draw_model(wm, V3(0, 0, 0), 1.0, WHITE)
                    wm.transform = old_t
            sh.append((wk.x, wk.y, 0, 0.35, 0.35, 70 if wk.z < 0.1 else 40, (wk.az - wk.z) if wk.az is not None else 0.0))
        for kx, kz, kh in sim.kiosks:
            if self._in(kx, kz, rect):
                self._kiosk(kx, w.ground_y(kx, kz), kz, kh)
        if self.shadows:
            self._shadow_batch(sh)
        for x, z, h, m, tint, gy, pitch, roll, kind, ang in cars:
            if m is None:
                continue
            M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_x(roll), rl.matrix_rotate_z(pitch)),
                                                      rl.matrix_rotate_y(-h)), rl.matrix_translate(x, gy, z))
            old = m.transform
            m.transform = M                                  # tilt with the slope: roll, pitch, heading, then move
            rl.draw_model(m, V3(0, 0, 0), 1.0, tint)
            m.transform = old
            fw = self.front_wheels.get(kind)
            if fw is None:
                fw = self.front_wheels[kind] = gl3d.front_wheel(kind) if kind not in vehicles.BIKES else (0, 0, 0, None)
            wx, wr, hz, wm = fw
            if wm is None:
                continue
            old = wm.transform
            for sd in (-hz, hz):                             # front wheels turned about their own centres by the steering angle
                wm.transform = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_y(-ang), rl.matrix_translate(wx, wr, sd)), M)
                rl.draw_model(wm, V3(0, 0, 0), 1.0, tint)
            wm.transform = old
        for b, gy in doors:                                  # carjack: the driver's door swung out on its hinge
            key = ("door", b.kind, b.color)
            m = self.car_models.get(key)
            if m is None:
                m = self.car_models[key] = gl3d.door_model(b.kind, b.color)
            if m is None:
                continue
            hx, _dl = gl3d.door_geom(b.kind)
            W = vehicles.DIMS[b.kind][1]
            ang = -1.25 * b.door * (1.0 - 0.15 * (1.0 - b.door))
            M = rl.matrix_multiply(rl.matrix_rotate_y(ang), rl.matrix_translate(hx, 0.0, -(W / 2 + 0.03)))
            M = rl.matrix_multiply(M, rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_x(b.roll), rl.matrix_rotate_z(b.pitch)),
                                                                          rl.matrix_rotate_y(-b.h)), rl.matrix_translate(b.x, gy, b.y)))
            old = m.transform
            m.transform = M
            rl.draw_model(m, V3(0, 0, 0), 1.0, WHITE)
            m.transform = old
        for x, y, z, h, arch, tone, frame, skin, *ex in peds:
            pm = self.ped_model(arch, tone, frame, skin)
            if pm is not None:
                if ex and ex[0]:                                     # leaning over (CPR): tilt about the feet, then heading
                    M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_z(ex[0]), rl.matrix_rotate_y(-h)), rl.matrix_translate(x, y, z))
                    old = pm.transform
                    pm.transform = M
                    rl.draw_model(pm, V3(0, 0, 0), 1.0, WHITE)
                    pm.transform = old
                else:
                    rl.draw_model_ex(pm, V3(x, y, z), UP, -math.degrees(h), ONE, WHITE)
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
