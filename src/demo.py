"""Cinematic demo: a news helicopter flies a random tour over the city and a free camera shows it from afar.
Camera shots are pure functions of the demo time and the helicopter, so a preview can jump to any moment (Demo.seek).
Variants VARIANTS[i] differ in camera path, orbit radius, height, pacing, time of day and framing."""
import bisect
import math
import random

import numpy as np
import pyray as rl

import gl3d

import os
LIMIT = float(os.environ.get("SK242_CINE_BOX", "1e9"))      # test only: keep the tour inside a sample world
V3 = rl.Vector3
UP = V3(0, 1, 0)

# name (in-game, Macedonian), English note for the preview, mode, then the parameters of that mode
VARIANTS = [
    dict(name="Класичен круг", en="Classic orbit: steady circle around the helicopter, golden hour", mode="orbit",
         hour=17.4, R=190, dh=75, w=6.0, alt=140, speed=16, fov=45),
    dict(name="Високо панорамско", en="High panorama: wide, slow orbit from far above, midday", mode="orbit",
         hour=12.6, R=470, dh=270, w=2.5, alt=260, speed=20, fov=38),
    dict(name="Статив", en="Tripod fly-by: locked low camera, the helicopter passes, cut to the next spot", mode="flyby",
         hour=15.2, R=130, dh=45, alt=95, speed=22, fov=40),
    dict(name="Ноќен неон", en="Neon night: lazy counter-clockwise orbit, city lights", mode="orbit",
         hour=22.3, R=240, dh=95, w=-5.0, alt=170, speed=15, fov=45),
    dict(name="Следење", en="Chase: camera trails behind and above, fast, morning light", mode="chase",
         hour=9.0, R=120, dh=42, alt=130, speed=30, fov=52),
    dict(name="Спирала", en="Breathing spiral: radius and height swell in and out", mode="spiral",
         hour=15.6, R=260, dh=130, w=4.5, alt=190, speed=17, fov=42),
    dict(name="Филмски сечења", en="Cut sequence: 9 s shots (orbit, chase, wide, fly-by) with dips to black, dusk", mode="cuts",
         hour=18.8, R=200, dh=80, w=5.0, alt=150, speed=18, fov=44),
    dict(name="Птичја перспектива", en="Drone top view: steep, almost map-like looking down", mode="orbit",
         hour=13.6, R=110, dh=330, w=4.0, alt=230, speed=18, fov=42),
    dict(name="Зора, телефото", en="Dawn telephoto: very far, long lens, compressed city, sunrise", mode="orbit",
         hour=6.5, R=680, dh=140, w=1.8, alt=190, speed=14, fov=20, hscale=3.4),
    dict(name="Осмица", en="Figure-eight dolly: camera sweeps in and out on a looping path, blue hour", mode="dolly",
         hour=20.0, R=240, dh=110, alt=150, speed=16, fov=42),
    dict(name="Преливање", en="Blend: starts high above the helicopter, slowly sinks to the low chase view while always turning slowly",
         mode="blend", hour=9.0, alt=140, speed=20, fov=50, hscale=3.0),
]


def _wrap(a):
    return (a + math.pi) % math.tau - math.pi


def _heli_boxes():
    """Body of a news helicopter, x forward; boxes (cx, base y, cz, sx, sy, sz, colour)."""
    W, R, G, K = (236, 236, 240), (205, 32, 52), (44, 74, 112), (40, 42, 48)
    b = [(0.0, 0.0, 0.9, 3.4, 0.10, 0.10, K), (0.0, 0.0, -0.9, 3.4, 0.10, 0.10, K),            # skids
         (0.7, 0.1, 0.9, 0.08, 0.6, 0.08, K), (-0.7, 0.1, 0.9, 0.08, 0.6, 0.08, K),
         (0.7, 0.1, -0.9, 0.08, 0.6, 0.08, K), (-0.7, 0.1, -0.9, 0.08, 0.6, 0.08, K),
         (0.2, 0.6, 0.0, 3.4, 1.5, 1.7, W),                                                    # cabin
         (0.2, 0.6, 0.0, 3.42, 0.28, 1.72, R),                                                 # red belt line
         (2.0, 0.8, 0.0, 1.1, 1.1, 1.5, G),                                                    # glass nose
         (-0.4, 2.1, 0.0, 1.8, 0.55, 1.1, W),                                                  # engine hump
         (0.0, 2.6, 0.0, 0.18, 0.4, 0.18, K),                                                  # rotor mast
         (-2.9, 1.5, 0.0, 4.4, 0.38, 0.36, W), (-2.9, 1.5, 0.0, 4.42, 0.12, 0.38, R),          # tail boom
         (-5.0, 1.5, 0.0, 0.5, 1.5, 0.12, W), (-5.0, 2.3, 0.0, 0.5, 0.18, 0.14, R),            # fin
         (-5.0, 2.45, 0.14, 0.12, 1.1, 0.06, K),                                                # tail rotor (static blur)
         (1.5, -0.25, 0.0, 0.7, 0.55, 0.6, (30, 30, 34))]                                      # camera ball
    return b


def _rotor_boxes():
    K = (36, 36, 40)
    return [(0.0, 0.0, 0.0, 10.8, 0.05, 0.3, K), (0.0, 0.0, 0.0, 0.3, 0.05, 10.8, K)]


class Route:
    """Random tour over the roads: Catmull-Rom spline through waypoints that are taken on random road edges."""

    def __init__(self, world, seed):
        self.w = world
        self.rng = random.Random(seed)
        self.edges = [e for e in world.edges if e["len"] > 40] or list(world.edges)
        self.pts = []
        self.poly = []
        self.cum = [0.0]
        for _ in range(4):
            self._add()
        self._seg(1)

    def _add(self):
        for _ in range(40):                                 # far enough from the last waypoint: new parts of the city, not a wiggle
            e = self.rng.choice(self.edges)
            x, y, _dx, _dy = self.w.edge_point(e, e["len"] / 2)
            if abs(x) > LIMIT or abs(y) > LIMIT:
                continue
            if not self.pts or 380.0 < math.hypot(x - self.pts[-1][0], y - self.pts[-1][1]) < 1300.0:
                break
        self.pts.append((x, y))

    def _seg(self, i):
        p0, p1, p2, p3 = self.pts[i - 1], self.pts[i], self.pts[i + 1], self.pts[i + 2]
        for k in range(0 if i > 1 else 0, 24):
            u = k / 24.0
            u2, u3 = u * u, u * u * u
            x = 0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * u + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * u2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * u3)
            y = 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * u + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * u2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * u3)
            if self.poly:
                self.cum.append(self.cum[-1] + math.hypot(x - self.poly[-1][0], y - self.poly[-1][1]))
            self.poly.append((x, y))
        self.n_seg = i

    def at(self, s):
        while s > self.cum[-1] - 500.0:                     # keep the road ahead long enough
            self._add()
            self._seg(self.n_seg + 1)
        i = max(1, min(len(self.poly) - 1, bisect.bisect_right(self.cum, s)))
        a, b = self.poly[i - 1], self.poly[i]
        l = max(1e-6, self.cum[i] - self.cum[i - 1])
        u = max(0.0, min(1.0, (s - self.cum[i - 1]) / l))
        return a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, math.atan2(b[1] - a[1], b[0] - a[0])


class Demo:
    VIEW_NEAR = 300.0          # full detail within this many metres of the helicopter, low quality (no facade/road detail) beyond
    VIEW_MID = 900.0           # beyond this: buildings only, no ground bake, no roads (the overview map shows them)
    VIEW_FAR = 2880.0          # 4x the first version

    def __init__(self, world, selfie):
        self.w = world
        self.selfie = selfie                                # its sky() paints the gradient, clouds, stars and moon
        self.active = False
        self.v = VARIANTS[0]
        self.models = None
        self.t = 0.0
        self.fade = 0.0
        self.place = ""
        self._place_t = -99.0

    # ---------------------------------------------------------------- start / state
    def start(self, variant, seed=None):
        self.vi = variant % len(VARIANTS)
        self.v = VARIANTS[self.vi]
        self.route = Route(self.w, seed if seed is not None else random.randrange(1 << 30))
        self.active = True
        self.seek(0.0)

    def stop(self):
        self.active = False

    def seek(self, t):
        self.t = t
        self.s = self.v["speed"] * t
        x, z, h = self.route.at(self.s)
        self.hx, self.hz, self.hh = x, z, h
        self.hy = self._alt_target(x, z)
        self.bank = 0.0
        self.rot = 0.0
        self.shake = (0.0, 0.0, 0.0)
        self._prev_h = h

    def _alt_target(self, x, z):
        g = max(self.w.ground_y(x + dx, z + dz) for dx, dz in ((0, 0), (40, 0), (-40, 0), (0, 40), (0, -40)))
        return g + self.v["alt"]

    def update(self, dt):
        if not self.active:
            return
        v = self.v
        self.t += dt
        self.s += v["speed"] * dt
        x, z, h = self.route.at(self.s)
        self.hx, self.hz = x, z
        d = _wrap(h - self.hh)
        self.hh += d * min(1.0, 1.6 * dt)
        yawrate = _wrap(self.hh - self._prev_h) / max(dt, 1e-4)
        self._prev_h = self.hh
        self.bank += (max(-0.45, min(0.45, yawrate * 1.2)) - self.bank) * min(1.0, 2.0 * dt)
        self.hy += (self._alt_target(x, z) - self.hy) * min(1.0, 0.7 * dt)
        self.rot = (self.rot + 38.0 * dt) % math.tau

    # ---------------------------------------------------------------- the camera
    def _shot(self, t):
        """(camera x, y, z, extra target offset y, fov) for the current variant at demo time t."""
        v, hx, hy, hz, hh = self.v, self.hx, self.hy, self.hz, self.hh
        m = v["mode"]
        if m == "cuts":
            idx = int(t // 9.0) % 4
            tt = t - (t // 9.0) * 9.0
            self.fade = max(0.0, 1.0 - tt / 0.7, 1.0 - (9.0 - tt) / 0.7)
            sub = (dict(mode="orbit", R=200, dh=80, w=5.0, fov=44), dict(mode="chase", R=130, dh=45, fov=50),
                   dict(mode="orbit", R=480, dh=250, w=-3.0, fov=36), dict(mode="flyby", R=120, dh=40, fov=40))[idx]
            v = dict(v, **sub)
            m = v["mode"]
            t = t + idx * 7.0
        else:
            self.fade = 0.0
        if m == "orbit":
            a = 0.6 + math.radians(v["w"]) * t
            R, dh = v["R"], v["dh"]
        elif m == "spiral":
            a = 0.6 + math.radians(v["w"]) * t
            k = 0.5 - 0.5 * math.cos(t * math.tau / 40.0)
            R, dh = 150 + (v["R"] + 160 - 150) * k, 45 + (v["dh"] + 90 - 45) * k
        elif m == "blend":                                  # top view -> low chase view -> back, one cycle 80 s, turning all the time
            k = 0.5 - 0.5 * math.cos(t * math.tau / 80.0)
            k = k * k * (3.0 - 2.0 * k)
            R, dh = 120.0 + 40.0 * k, 330.0 - 288.0 * k
            a = hh + math.pi + 0.07 * t
        elif m == "chase":
            a = hh + math.pi + 0.35 * math.sin(t * 0.22)
            R, dh = v["R"], v["dh"] + 8 * math.sin(t * 0.4)
        elif m == "dolly":
            R = v["R"] * (0.65 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.11 * 2)))
            dh = v["dh"] * (0.6 + 0.9 * (0.5 + 0.5 * math.cos(t * 0.08 * 2)))
            a = math.sin(t * 0.045 * math.tau) * 2.4 + 1.0
        else:                                               # flyby: a tripod on the ground ahead of the route; moves on when the helicopter has passed
            per = 14.0
            k = int(t // per)
            r = random.Random(k * 7919 + 13)
            s0 = v["speed"] * (k * per + per * 0.5)
            px, pz, ph = self.route.at(s0)
            side = 1 if r.random() < 0.5 else -1
            cx = px + math.cos(ph + side * math.pi / 2) * v["R"]
            cz = pz + math.sin(ph + side * math.pi / 2) * v["R"]
            cy = self.w.ground_y(cx, cz) + v["dh"] + 30 * r.random()
            tt = t - k * per
            if self.v["mode"] == "flyby":
                self.fade = max(0.0, 1.0 - tt / 0.6, 1.0 - (per - tt) / 0.6)
            return cx, cy, cz, v["fov"]
        cx = hx + math.cos(a) * R
        cz = hz + math.sin(a) * R
        sway = 1.5
        cy = hy + dh + sway * math.sin(t * 0.7)
        cx += sway * math.sin(t * 0.43)
        cz += sway * math.cos(t * 0.51)
        return cx, cy, cz, v["fov"]

    def camera(self):
        """-> (Camera3D, culling rect, far-plane scale).  Call after update()."""
        cx, cy, cz, fov = self._shot(self.t)
        cy = max(cy, self.w.ground_y(cx, cz) + 28.0)       # never below the roofs
        tx, ty, tz = self.hx, self.hy - 2.0, self.hz
        self.yaw = math.atan2(tz - cz, tx - cx)
        cam = rl.Camera3D(V3(cx, cy, cz), V3(tx, ty, tz), UP, fov, rl.CAMERA_PERSPECTIVE)
        far = max(self.VIEW_FAR, math.hypot(cx - tx, cz - tz) + 120.0)
        rect = (tx - far, tz - far, tx + far, tz + far)
        return cam, rect, far

    # ---------------------------------------------------------------- the helicopter
    def draw_heli(self, cam, night):
        if self.models is None:
            self.models = (gl3d._boxes_model(_heli_boxes()), gl3d._boxes_model(_rotor_boxes()))
        body, rotor = self.models
        sc = self.v.get("hscale", 2.0)
        pitch = 0.06
        M = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_multiply(rl.matrix_scale(sc, sc, sc), rl.matrix_rotate_x(self.bank)),
                                                  rl.matrix_rotate_z(-pitch)), rl.matrix_multiply(rl.matrix_rotate_y(-self.hh), rl.matrix_translate(self.hx, self.hy, self.hz)))
        R = rl.matrix_multiply(rl.matrix_multiply(rl.matrix_rotate_y(self.rot), rl.matrix_translate(0.0, 2.9, 0.0)), M)
        rl.begin_mode_3d(cam)
        try:
            rl.rl_disable_backface_culling()
            for m, T in ((body, M), (rotor, R)):
                old = m.transform
                m.transform = T
                rl.draw_model(m, V3(0, 0, 0), 1.0, rl.WHITE)
                m.transform = old
            if night > 0.3:                                 # navigation and strobe lights
                ph = (self.t * 1.7) % 1.0
                for lx, ly, lz, col in ((-5.0, 1.6, 0.0, (255, 255, 255)), (0.2, 2.5, 0.9, (255, 40, 40)), (0.2, 2.5, -0.9, (60, 255, 90)),
                                         (0.0, 0.0, 0.0, (255, 40, 40))):
                    if col == (255, 255, 255) and ph > 0.12:
                        continue
                    if col == (255, 40, 40) and lz == 0.0 and ph < 0.5:
                        continue
                    p = rl.vector3_transform(V3(lx, ly, lz), M)
                    rl.draw_sphere(p, 0.35 * sc, rl.Color(*col, 255))
        finally:
            rl.end_mode_3d()

    def sky_layers(self, cam, sw, sh, dark, hour):
        draw_sun(cam, sw, sh, hour, dark)
        draw_mountains(cam, self.yaw, sw, sh, dark, hour)

    def haze(self, cam, sw, sh, dark, hour):
        draw_haze(cam, self.yaw, sw, sh, dark, hour)

    # ---------------------------------------------------------------- 2D layer
    def overlay(self, sw, sh, font, place):
        bar = int(sh * 0.085)
        rl.draw_rectangle(0, 0, sw, bar, rl.BLACK)
        rl.draw_rectangle(0, sh - bar, sw, bar, rl.BLACK)
        if place and place != self.place:
            self.place, self._place_t = place, self.t
        a = max(0.0, min(1.0, (self.t - self._place_t) / 1.0, (6.0 - (self.t - self._place_t)) / 1.0))
        if self.place and a > 0:
            font.draw_text(self.place.upper(), 48, sh - bar - 56, 34, rl.Color(255, 255, 255, int(235 * a)))
        if self.fade > 0:
            rl.draw_rectangle(0, 0, sw, sh, rl.Color(0, 0, 0, int(255 * min(1.0, self.fade))))


# Mountains round Skopje as seen from the centre, by game azimuth (0 = east, 90 = south, -90 = north):
# (azimuth deg, half width deg, peak elevation deg, distance km, seed, snow)
RANGES = [(-150, 42, 4.6, 32.0, 4, True),      # Šar Mountains / Ljuboten, far north-west
          (140, 40, 3.8, 40.0, 5, True),       # Jakupica / Solunska Glava, far south-west
          (-70, 55, 6.0, 12.0, 2, False),      # Skopska Crna Gora, north
          (95, 48, 7.5, 6.0, 1, False),        # Vodno, south
          (20, 45, 3.2, 20.0, 3, False)]       # eastern hills


def _mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _prof(a_deg, rng):
    az, half, peak, _dist, seed, _snow = rng
    d = _wrap(math.radians(a_deg - az)) / math.radians(half)
    if abs(d) >= 1.0:
        return 0.0
    env = math.cos(d * math.pi / 2) ** 1.5
    n = 0.62 + 0.22 * math.sin(a_deg * 0.31 + seed) + 0.12 * math.sin(a_deg * 0.83 + seed * 2.1) + 0.06 * math.sin(a_deg * 2.1 + seed * 5.3)
    return peak * env * n


def _haze_col(dark, hour):
    dusk = 1.0 - abs(dark - 0.5) * 2.0 if 0.0 < dark < 1.0 else 0.0
    return _mix(_mix((205, 220, 235), (255, 190, 140), dusk * 0.8), (30, 36, 70), dark)


def _horizon_y(cam, yaw, sh):
    far = V3(cam.position.x + math.cos(yaw) * 4000.0, cam.position.y, cam.position.z + math.sin(yaw) * 4000.0)
    return rl.get_world_to_screen(far, cam).y


def draw_mountains(cam, yaw, sw, sh, dark, hour):
    """Layers of Macedonian mountains behind the city, fading into haze with distance."""
    hy = _horizon_y(cam, yaw, sh)
    f = (sh / 2) / math.tan(math.radians(cam.fovy) / 2)
    if hy < -f * 0.2:
        return hy
    hz = _haze_col(dark, hour)
    night = _mix((46, 70, 84), (10, 14, 30), dark)
    for rng in sorted(RANGES, key=lambda r: -r[3]):
        dist, snow = rng[3], rng[5]
        k = min(0.72, 0.1 + dist / 70.0)
        col = _mix(night, hz, k)
        cap = _mix(col, (245, 247, 250), 0.55 * (1 - dark * 0.6))
        for x in range(0, sw, 5):
            a = math.degrees(yaw + math.atan((x + 2 - sw / 2) / f))
            e = _prof(a, rng)
            if e <= 0.0:
                continue
            y = hy - f * math.tan(math.radians(e))
            if y >= sh:
                continue
            rl.draw_rectangle(x, int(y), 5, int(max(hy - y, 0) + sh * 0.4), rl.Color(*col, 255))
            if snow and e > rng[2] * 0.62:
                rl.draw_rectangle(x, int(y), 5, int(min(hy - y, (e - rng[2] * 0.62) * f * 0.03 + 3)), rl.Color(*cap, 255))
    return hy


def draw_sun(cam, sw, sh, hour, dark):
    """The sun disc where the real sun is (same sun_at() as the shadows): behind the scene, so roofs and ridges cover it."""
    from sunshadow import sun_at
    L, e = sun_at(hour)
    if e < -0.04:
        return
    fx, fy, fz = cam.target.x - cam.position.x, cam.target.y - cam.position.y, cam.target.z - cam.position.z
    n = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    if (fx * L[0] + fy * L[1] + fz * L[2]) / n < 0.05:
        return
    sp = rl.get_world_to_screen(V3(cam.position.x + L[0] * 5000, cam.position.y + L[1] * 5000, cam.position.z + L[2] * 5000), cam)
    vis = max(0.0, min(1.0, (e + 0.04) / 0.08))
    low = max(0.0, min(1.0, 1.0 - e / 0.35))
    col = _mix((255, 246, 222), (255, 170, 90), low)
    x, y = int(sp.x), int(sp.y)
    rl.begin_blend_mode(rl.BLEND_ADDITIVE)
    rl.draw_circle_gradient(rl.Vector2(x, y), int(sh * 0.45), rl.Color(*col, int(70 * vis)), rl.Color(*col, 0))
    rl.draw_circle_gradient(rl.Vector2(x, y), int(sh * 0.12), rl.Color(*col, int(150 * vis)), rl.Color(*col, 0))
    rl.end_blend_mode()
    rl.draw_circle(x, y, max(6, int(sh * 0.028)), rl.Color(255, 252, 235, int(255 * vis)))


def draw_haze(cam, yaw, sw, sh, dark, hour):
    """Thick haze band round the true horizon: hides where the baked city ends and sits under the mountains."""
    hy = _horizon_y(cam, yaw, sh)
    f = (sh / 2) / math.tan(math.radians(cam.fovy) / 2)
    if hy < -sh * 0.3 or hy > sh * 1.5:
        return
    c = _haze_col(dark, hour)
    up, down = int(f * 0.16), int(f * 0.42)
    rl.draw_rectangle_gradient_v(0, int(hy) - up, sw, up, rl.Color(*c, 0), rl.Color(*c, 120))
    rl.draw_rectangle_gradient_v(0, int(hy), sw, down, rl.Color(*c, 120), rl.Color(*c, 0))


class Preview:
    """Test driver: walks through the variants, jumps to a few moments of each and saves a frame there."""
    TIMES = (4.0, 11.0, 19.0, 27.0, 35.0, 43.0, 51.0, 59.0, 67.0, 75.0)

    def __init__(self, demo, variants, dwell=14, times=None, seed=3):
        self.demo, self.variants, self.dwell, self.seed = demo, list(variants), dwell, seed
        self.times = list(times) if times else list(self.TIMES)
        self.n = 0

    def tick(self, frame, set_hour):
        """Call once per frame BEFORE update; returns the file suffix to save after drawing, or None."""
        total = len(self.variants) * len(self.times) * self.dwell
        if frame >= total:
            return "end"
        k, f = divmod(frame, self.dwell)
        vi, ti = divmod(k, len(self.times))
        if f == 0:
            if ti == 0:
                self.demo.start(self.variants[vi], seed=self.seed)
            self.demo.seek(self.times[ti])
            set_hour(self.demo.v["hour"])
        if f == self.dwell - 1:
            return f"v{self.variants[vi]:02d}_t{ti:02d}"
        return None
