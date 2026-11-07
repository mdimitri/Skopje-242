"""Selfie: key P.  The camera swings round in front of the avatar at eye level, the avatar blurts a catchy phrase,
and a burst of frames is saved to selfies/<date-time>/frame_NNN.png.  The world is drawn with a short view distance
(cheap city overview beyond it), over a procedural sky: clouds by day, stars and moon at night."""
from texts import TXT
import math
import os
import random
import time

import pyray as rl

import font
import poi

V3 = rl.Vector3
UP = V3(0, 1, 0)
DUR = 2.6
SHOTS = 10
FOVY = 68.0
VIEW = 150.0                                         # metres of full-detail world around the avatar

PHRASES = [TXT("selfie.0001"), TXT("selfie.0002"), TXT("selfie.0003"), TXT("selfie.0004"), TXT("selfie.0005"),
           TXT("selfie.0006"), TXT("selfie.0007"), TXT("selfie.0008"), TXT("selfie.0009"), TXT("selfie.0010")]


def _mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


MOON_AZ = 2.2                                             # fixed moon azimuth (rad)

class Selfie:
    def __init__(self, root):
        self.root = os.path.join(root, "selfies")
        self.t = None
        self.dir = None
        self.n = 0
        self.rng = random.Random(5)
        self.clouds = [(self.rng.uniform(0, math.tau), self.rng.uniform(0.12, 0.5), self.rng.uniform(0.7, 1.5),
                        [(self.rng.uniform(-1, 1), self.rng.uniform(-0.3, 0.3), self.rng.uniform(0.5, 1.0)) for _ in range(5)]) for _ in range(16)]
        self.stars = [(self.rng.uniform(0, math.tau), self.rng.uniform(0.05, 0.9), self.rng.uniform(0.4, 1.0)) for _ in range(190)]
        self.phrase = ""
        self.yaw = 0.0
        self.cam = None
        self.flash = 0.0
        self.saved_dir = ""

    @property
    def active(self):
        return self.t is not None

    def start(self, sim, lik_id, say):
        wk = sim.walker
        if self.active or sim.mode != "foot" or wk is None or wk.health <= 0:
            return False
        self.t, self.n = 0.0, 0
        stamp = time.strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(self.root, "selfie_" + stamp)
        self.phrase = f"{self.rng.choice(PHRASES)} {poi.tail_for(lik_id, self.rng)}"
        say(self.phrase, wk.x, wk.y)
        return True

    def camera(self, sim, world):
        """-> (Camera3D, rect) looking at the avatar's face from slightly to one side."""
        wk = sim.walker
        s = self.t / DUR
        ang = wk.h + math.sin(s * 3.1) * 0.55 + 0.1
        d = 1.35 + 0.25 * math.sin(s * 2.0)
        az = wk.az if wk.az is not None else world.ground_y(wk.x, wk.y)
        px, pz = wk.x + math.cos(ang) * d, wk.y + math.sin(ang) * d
        eye = az + 1.62 + 0.08 * math.sin(s * 5.0)
        self.yaw = math.atan2(wk.y - pz, wk.x - px)
        cam = rl.Camera3D(V3(px, eye, pz), V3(wk.x, az + 1.52, wk.y), UP, FOVY, rl.CAMERA_PERSPECTIVE)
        rect = (wk.x - VIEW, wk.y - VIEW, wk.x + VIEW, wk.y + VIEW)
        return cam, rect

    def chase(self, sim, world, dt):
        """Debug street-level chase camera: slightly behind and above the avatar (or car), looking where it faces."""
        o = sim.car if sim.mode == "car" else sim.walker
        tgt = o.h
        d = (tgt - getattr(self, "cy_", tgt) + math.pi) % math.tau - math.pi
        self.cy_ = getattr(self, "cy_", tgt) + d * min(1.0, 5.0 * dt)
        h = self.cy_
        az = o.az if o.az is not None else world.ground_y(o.x, o.y)
        back, up, ahead = (8.0, 5.5, 3.0) if sim.mode == "car" else (4.5, 3.6, 2.0)   # pitched ~25 deg down: horizon near the top edge
        h += getattr(self, "look_yaw", 0.0)                # mouse free-look orbit (0 when the mouse steers)
        up += getattr(self, "look_pitch", 0.0) * back
        px, pz = o.x - math.cos(h) * back, o.y - math.sin(h) * back
        self.yaw = h
        cam = rl.Camera3D(V3(px, az + up, pz), V3(o.x + math.cos(h) * ahead, az + 0.4, o.y + math.sin(h) * ahead), UP, FOVY, rl.CAMERA_PERSPECTIVE)
        self.cam = cam
        f = VIEW * 2.25                                    # drawn out to the low-quality ring
        return cam, (o.x - f, o.y - f, o.x + f, o.y + f)

    def sky(self, cam, dark, hour, t, sw, sh):
        """Gradient + clouds / stars, drawn before the 3D pass; returns the horizon screen y."""
        far = V3(cam.position.x + math.cos(self.yaw) * 4000, cam.position.y, cam.position.z + math.sin(self.yaw) * 4000)
        hy = int(max(sh * 0.15, min(sh * 0.9, rl.get_world_to_screen(far, cam).y)))
        dusk = 1.0 - abs(dark - 0.5) * 2.0 if 0.0 < dark < 1.0 else 0.0
        top = _mix(_mix((60, 120, 215), (230, 120, 90), dusk * 0.5), (6, 8, 26), dark)
        hor = _mix(_mix((190, 220, 245), (255, 175, 120), dusk * 0.8), (28, 34, 70), dark)
        rl.draw_rectangle_gradient_v(0, 0, sw, hy, rl.Color(*top, 255), rl.Color(*hor, 255))
        rl.draw_rectangle(0, hy, sw, sh - hy, rl.Color(*hor, 255))
        hfov = 2 * math.atan(math.tan(math.radians(FOVY) / 2) * sw / sh)
        ppr = sw / (2 * math.tan(hfov / 2))                           # pixels per radian near the centre
        def sx(az):
            d = (az - self.yaw + math.pi) % math.tau - math.pi
            return None if abs(d) > hfov * 0.7 else sw / 2 + math.tan(d) * ppr
        if dark > 0.35:
            a = int(255 * min(1.0, (dark - 0.35) * 2.0))
            for az, el, br in self.stars:
                x = sx(az)
                if x is not None:
                    y = hy - el * hy * 1.1
                    tw = 0.6 + 0.4 * math.sin(t * 2.0 + az * 9)
                    rl.draw_circle(int(x), int(y), 1.4 if br > 0.8 else 1.0, rl.Color(255, 255, 235, int(a * br * tw)))
            mx = sx(MOON_AZ)                                      # fixed spot in the world sky: only turning the camera moves it on screen
            if mx is not None:
                my = int(hy * 0.45)
                r = int(sh * 0.11)                                # cartoonishly big
                rl.draw_circle_gradient(rl.Vector2(int(mx), my), r * 2.6, rl.Color(200, 215, 255, int(70 * a / 255)), rl.Color(200, 215, 255, 0))
                rl.draw_circle(int(mx), my, r, rl.Color(244, 242, 220, a))
                for cx, cy, cr in ((-0.35, -0.25, 0.22), (0.30, 0.1, 0.16), (-0.1, 0.38, 0.12)):   # craters
                    rl.draw_circle(int(mx + cx * r), int(my + cy * r), int(cr * r), rl.Color(214, 212, 190, a))
        if dark < 0.8:
            ca = int(235 * (1.0 - dark / 0.8))
            tint = _mix((255, 255, 255), (255, 200, 170), dusk)
            for az, el, sz, puffs in self.clouds:
                x = sx(az + t * 0.004)
                if x is None:
                    continue
                y = hy - el * hy * 1.1
                for ox, oy, r in puffs:
                    rl.draw_circle_gradient(rl.Vector2(int(x + ox * 90 * sz), int(y + oy * 24 * sz)), int(r * 52 * sz), rl.Color(*tint, int(ca * 0.55)), rl.Color(*tint, 0))
        return hy

    def haze(self, hy, dark, sw):
        """Soft band at the horizon hiding where full-detail buildings end."""
        c = _mix((200, 215, 230), (30, 36, 70), dark)
        rl.draw_rectangle_gradient_v(0, hy - 70, sw, 70, rl.Color(*c, 0), rl.Color(*c, 150))
        rl.draw_rectangle_gradient_v(0, hy, sw, 50, rl.Color(*c, 150), rl.Color(*c, 0))

    def overlay(self, sw, sh):
        """Phone-style frame, caption and the flash of a shot."""
        rl.draw_rectangle_lines_ex(rl.Rectangle(10, 10, sw - 20, sh - 20), 6, rl.Color(255, 255, 255, 190))
        wpx = font.measure_text(self.phrase, 34)
        font.draw_text(self.phrase, sw // 2 - wpx // 2 + 2, sh - 92, 34, rl.Color(0, 0, 0, 200))
        font.draw_text(self.phrase, sw // 2 - wpx // 2, sh - 94, 34, rl.Color(255, 240, 150, 255))
        if self.flash > 0:
            rl.draw_rectangle(0, 0, sw, sh, rl.Color(255, 255, 255, int(150 * self.flash)))

    def advance(self, dt):
        """Call once per frame; returns True on frames that must be saved AFTER end_drawing's draw (see take)."""
        self.t += dt
        self.flash = max(0.0, self.flash - dt * 6.0)
        due = self.t >= (self.n + 1) * (DUR - 0.2) / (SHOTS + 1) and self.n < SHOTS
        if self.t >= DUR:
            self.t = None
        return due

    def take(self):
        """Grab the screen (call just before end_drawing) into the selfie folder."""
        if self.dir is None:
            self.n += 1
            return
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:
            self.n += 1
            return
        img = rl.load_image_from_screen()
        rl.export_image(img, os.path.join(self.dir, f"frame_{self.n:03d}.png"))
        rl.unload_image(img)
        self.n += 1
        self.flash = 1.0
        self.saved_dir = self.dir
