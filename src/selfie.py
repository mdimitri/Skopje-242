"""Selfie: key P.  The camera swings round in front of the avatar at eye level, the avatar blurts a catchy phrase,
and a burst of frames is saved to selfies/<date-time>/frame_NNN.jpg.  The world is drawn with a short view distance
(cheap city overview beyond it), over a procedural sky: clouds by day, stars and moon at night."""
from texts import TXT
import math
import os
import random
import time

import pyray as rl

import font
import vehicles
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
        self.clouds = [(self.rng.uniform(0, math.tau), self.rng.uniform(0.1, 0.85), self.rng.uniform(0.8, 1.9),
                        [(self.rng.uniform(-1, 1), self.rng.uniform(-0.3, 0.3), self.rng.uniform(0.5, 1.0)) for _ in range(5)]) for _ in range(30)]
        # cartoon shape: puffs in a row, biggest in the middle, all resting on one flat base line
        self.clouds = [(az, el, sz, sorted((ox, 0.0, (0.6 + 0.4 * (1 - abs(ox))) * r) for ox, _oy, r in puffs)) for az, el, sz, puffs in self.clouds]
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

    def tunnel(self, world, o):
        """-> (blend 0..1, heading) when o is down in a covered road underpass: 0 -> 1 over the first 10% of its length, back over the last 10%."""
        best = (0.0, 0.0)
        for u in getattr(world, "underpass", None) or ():
            P = u["pts"]
            cum = u.get("_cum")
            if cum is None:
                cum = [0.0]
                for (ax, ay), (bx, by) in zip(P, P[1:]):
                    cum.append(cum[-1] + math.hypot(bx - ax, by - ay))
                u["_cum"] = cum
            L = cum[-1]
            if L < 1.0:
                continue
            for i, ((ax, ay), (bx, by)) in enumerate(zip(P, P[1:])):
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy or 1e-9
                t = max(0.0, min(1.0, ((o.x - ax) * dx + (o.y - ay) * dy) / l2))
                if math.hypot(o.x - ax - dx * t, o.y - ay - dy * t) < u["hw"] and o.az is not None and o.az < u["roof"][i] - 2.0:
                    sd = cum[i] + t * (cum[i + 1] - cum[i])
                    k = max(0.0, min(1.0, min(sd, L - sd) / (0.1 * L)))
                    if k > best[0]:
                        hd = math.atan2(dy, dx)
                        if math.cos(o.h - hd) < 0:                 # face the way the avatar goes
                            hd += math.pi
                        best = (k, hd)
        return best

    def tunnel_cam(self, cam, o, world, dt):
        """Top view -> low wide 3rd-person view through a covered underpass (under its ceiling), blended by tunnel()."""
        k, hd = self.tunnel(world, o)
        k_ = getattr(self, "tk_", 0.0)
        k_ += (k - k_) * min(1.0, 8.0 * dt)                # just smooths the step at the mouths
        self.tk_ = k_
        if k_ < 1e-3:
            return cam
        d = (hd - getattr(self, "th_", hd) + math.pi) % math.tau - math.pi
        self.th_ = getattr(self, "th_", hd) + d * min(1.0, 3.0 * dt)
        h = self.th_
        self.yaw = h
        az = o.az if o.az is not None else world.ground_y(o.x, o.y)
        P = (o.x - math.cos(h) * 7.0, az + 2.7, o.y - math.sin(h) * 7.0)      # 4.4 m headroom: well under the ceiling
        T = (o.x + math.cos(h) * 3.0, az + 1.0, o.y + math.sin(h) * 3.0)
        p, t = cam.position, cam.target
        s = k_ * k_ * (3 - 2 * k_)
        m = lambda a, b: a + (b - a) * s
        return rl.Camera3D(V3(m(p.x, P[0]), m(p.y, P[1]), m(p.z, P[2])), V3(m(t.x, T[0]), m(t.y, T[1]), m(t.z, T[2])),
                           UP, m(cam.fovy, FOVY * 1.12), rl.CAMERA_PERSPECTIVE)

    def chase(self, sim, world, dt):
        """Debug street-level chase camera: slightly behind and above the avatar (or car), looking where it faces."""
        o = sim.car if sim.mode == "car" else sim.walker
        tgt = o.h
        d = (tgt - getattr(self, "cy_", tgt) + math.pi) % math.tau - math.pi
        self.cy_ = getattr(self, "cy_", tgt) + d * min(1.0, 5.0 * dt)
        h = self.cy_
        az = o.az if o.az is not None else world.ground_y(o.x, o.y)
        heli = sim.mode == "car" and sim.car is not None and sim.car.kind in vehicles.FLY
        back, up, ahead = (17.0, 8.5, 5.0) if heli else (8.0, 5.5, 3.0) if sim.mode == "car" else (4.5, 3.6, 2.0)   # pitched ~25 deg down: horizon near the top edge
        h += getattr(self, "look_yaw", 0.0)                # mouse free-look orbit (0 when the mouse steers)
        lp = getattr(self, "look_pitch", 0.0)
        up += max(lp, 0.0) * back
        lift = max(-lp, 0.0) * 30.0                     # mouse up: the camera tilts up towards the sky
        ind = getattr(o, "indoor", None)
        self.yaw = h
        px, pz = o.x - math.cos(h) * back, o.y - math.sin(h) * back
        cy_ = az + up
        if ind is not None:                                # in the mall: its own walls and ceiling
            px, pz = ind.cam_fit(px, pz)
            cy_ = min(cy_, az + ind.cam_top(px, pz))        # under the mall's ceiling (lower in the corridors and doors)
        cam = rl.Camera3D(V3(px, cy_, pz), V3(o.x + math.cos(h) * ahead, az + 0.4 + lift, o.y + math.sin(h) * ahead), UP, FOVY, rl.CAMERA_PERSPECTIVE)
        self.cam = cam
        f = VIEW * 2.25 * (2.0 if heli else 1.0)           # drawn out to the low-quality ring (twice as far from a helicopter)
        return cam, (o.x - f, o.y - f, o.x + f, o.y + f)

    def sky(self, cam, dark, hour, t, sw, sh):
        """Gradient + clouds / stars, drawn before the 3D pass; returns the horizon screen y."""
        far = V3(cam.position.x + math.cos(self.yaw) * 4000, cam.position.y, cam.position.z + math.sin(self.yaw) * 4000)
        hz = max(-3.0 * sh, min(4.0 * sh, rl.get_world_to_screen(far, cam).y))   # true horizon: sky objects hang off it
        hy = int(max(sh * 0.15, min(sh * 0.9, hz)))
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
        def ey(el):                                               # screen y of an elevation (el*0.6 rad above the horizon)
            return hz - math.tan(el * 0.6) * ppr
        if dark > 0.35:
            a = int(255 * min(1.0, (dark - 0.35) * 2.0))
            for az, el, br in self.stars:
                x = sx(az)
                if x is not None:
                    y = ey(el)
                    tw = 0.6 + 0.4 * math.sin(t * 2.0 + az * 9)
                    rl.draw_circle(int(x), int(y), 1.4 if br > 0.8 else 1.0, rl.Color(255, 255, 235, int(a * br * tw)))
            mx = sx(MOON_AZ)                                      # fixed spot in the world sky: only turning the camera moves it on screen
            if mx is not None:
                my = int(ey(0.6))
                r = int(sh * 0.11)                                # cartoonishly big
                rl.draw_circle_gradient(rl.Vector2(int(mx), my), r * 2.6, rl.Color(200, 215, 255, int(70 * a / 255)), rl.Color(200, 215, 255, 0))
                rl.draw_circle(int(mx), my, r, rl.Color(244, 242, 220, a))
                for cx, cy, cr in ((-0.35, -0.25, 0.22), (0.30, 0.1, 0.16), (-0.1, 0.38, 0.12)):   # craters
                    rl.draw_circle(int(mx + cx * r), int(my + cy * r), int(cr * r), rl.Color(214, 212, 190, a))
        night = min(1.0, max(0.0, dark - 0.45) / 0.45)                              # cartoon clouds: outline, shaded body, bright top, flat bottom
        top_c = _mix(_mix((255, 255, 255), (255, 226, 196), dusk), (92, 102, 140), night)
        body_c = _mix(_mix((206, 218, 238), (236, 158, 150), dusk), (50, 58, 92), night)
        line_c = _mix(_mix((118, 146, 192), (160, 92, 108), dusk), (26, 30, 56), night)
        for az, el, sz, puffs in self.clouds:
            x = sx(az + t * 0.004)
            if x is None:
                continue
            base = ey(el) + 20 * sz
            pc = [(x + ox * 90 * sz, r * 40 * sz) for ox, _oy, r in puffs]
            x0, x1 = pc[0][0], pc[-1][0]
            hb = min(r for _x, r in pc) * 1.2                           # height of the flat-bottomed slab under the puffs
            for grow, col in ((3, line_c), (0, body_c)):
                c = rl.Color(*col, 255)
                rl.draw_rectangle_rounded(rl.Rectangle(x0 - grow, base - hb - grow, x1 - x0 + 2 * grow, hb + 2 * grow), 0.3, 4, c)
                for px, r in pc:
                    rl.draw_circle(int(px), int(base - r), r + grow, c)
            c = rl.Color(*top_c, 255)
            for px, r in pc:                                      # lit tops: smaller discs nudged up, leaving shade below
                rl.draw_circle(int(px - r * 0.08), int(base - r * 1.22), r * 0.78, c)
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

    def take(self, tex=None):
        """Save one selfie.  Call after the frame is complete (the world lives in the offscreen buffer `tex`, the window's own
        framebuffer is not what the player sees), as a polaroid JPEG."""
        if self.dir is None:
            self.n += 1
            return
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:
            self.n += 1
            return
        try:
            if tex is not None:
                img = rl.load_image_from_texture(tex)
                rl.image_flip_vertical(img)
            else:
                img = rl.load_image_from_screen()
            rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
            w, h = img.width, img.height
            raw = bytes(rl.ffi.buffer(img.data, w * h * 4))
            rl.unload_image(img)
            from PIL import Image
            polaroid(Image.frombytes("RGBA", (w, h), raw).convert("RGB")).save(
                os.path.join(self.dir, f"frame_{self.n:03d}.jpg"), "JPEG", quality=92)
        except Exception as e:               # a failed photo must never take the game down
            print("[selfie] save failed:", e)
        self.n += 1
        self.flash = 1.0
        self.saved_dir = self.dir


def polaroid(im):
    """Instant-film look: warm faded tint, soft vignette, white frame with a thick bottom border and 'Скопје 242' inscribed."""
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    import numpy as np
    w, h = im.size
    a = np.asarray(im, dtype=np.float32) / 255.0
    a = 0.06 + a * 0.90                                             # lifted blacks, softer whites
    a *= np.array([1.05, 1.00, 0.90], dtype=np.float32)             # warm tint
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2))
    a *= (1.0 - 0.28 * np.clip(r - 0.55, 0.0, 1.0) ** 1.5)[..., None]   # vignette
    im = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
    im = ImageEnhance.Color(im).enhance(0.88)
    side = max(12, w // 28)
    bottom = side * 4
    out = Image.new("RGB", (w + 2 * side, h + side + bottom), (250, 248, 242))
    out.paste(im, (side, side))
    d = ImageDraw.Draw(out)
    try:
        f = ImageFont.truetype(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts", "Oswald-SemiBold.ttf"), int(bottom * 0.5))
    except OSError:
        f = ImageFont.load_default()
    txt = "Скопје 242"
    tw = d.textlength(txt, font=f)
    d.text(((out.width - tw) / 2, h + side + bottom * 0.2), txt, font=f, fill=(70, 62, 55))
    return out
