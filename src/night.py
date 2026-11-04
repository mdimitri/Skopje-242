"""Night look: a blue multiply tint over the 3D scene plus additive light pools (street lamps, headlights,
tail lights, emergency light bars, burning wrecks).  Screen-space, drawn after the 3D pass and before the HUD."""
import math

import pyray as rl

import clock
import vehicles

V3 = rl.Vector3
CELL = 60.0
OG = 16.0


def _col(r, g, b, a):
    return rl.Color(int(r), int(g), int(b), int(max(0, min(255, a))))


class Night:
    def __init__(self, world):
        self.cells = {}
        self.w = world
        self.detail = 2
        for x, y in getattr(world, "lamps", ()):
            self.cells.setdefault((int(x // CELL), int(y // CELL)), []).append((x, y))
        self.og = {}                                   # building walls with their roof height, for hiding glows behind buildings
        for b in getattr(world, "buildings", ()):
            ring = b["ring"]
            cx_, cy_ = ring[0]
            top = world.th(cx_, cy_) + b.get("h", 8.0)
            for i in range(len(ring)):
                (ax, ay), (bx, by) = ring[i], ring[(i + 1) % len(ring)]
                for gx in range(int(min(ax, bx) // OG), int(max(ax, bx) // OG) + 1):
                    for gy in range(int(min(ay, by) // OG), int(max(ay, by) // OG) + 1):
                        self.og.setdefault((gx, gy), []).append((ax, ay, bx, by, top))
        self.vis, self.vis_cam = {}, None
        self.street = 0.0

    def _seen(self, cam, x, z, y):
        """False when a building wall stands between the camera and the point (x, height y, z)."""
        p = cam.position
        key = (round(p.x, 1), round(p.y, 1), round(p.z, 1))
        if key != self.vis_cam:
            self.vis, self.vis_cam = {}, key
        k = (round(x, 1), round(z, 1), round(y, 1))
        r = self.vis.get(k)
        if r is not None:
            return r
        dx, dz, dy = x - p.x, z - p.z, y - p.y
        n = max(1, int(math.hypot(dx, dz) / (OG * 0.5)))
        cells = {(int((p.x + dx * i / n) // OG), int((p.z + dz * i / n) // OG)) for i in range(n + 1)}
        r = True
        for c in cells:
            for ax, ay, bx, by, top in self.og.get(c, ()):
                ex, ey = bx - ax, by - ay
                den = dx * ey - dz * ex
                if abs(den) < 1e-9:
                    continue
                t = ((ax - p.x) * ey - (ay - p.z) * ex) / den      # along camera -> light
                u = ((ax - p.x) * dz - (ay - p.z) * dx) / den      # along the wall
                if 0.0 < t < 0.97 and 0.0 <= u <= 1.0 and p.y + dy * t < top:
                    r = False
                    break
            if not r:
                break
        self.vis[k] = r
        return r

    def _glow(self, cam, x, z, y, rad_px, col, a):
        gy = y + self.w.ground_y(x, z)
        if not self._seen(cam, x, z, gy):
            return
        sp = rl.get_world_to_screen(V3(x, gy, z), cam)
        if self.street:
            p, q = cam.position, cam.target
            if (x - p.x) * (q.x - p.x) + (gy - p.y) * (q.y - p.y) + (z - p.z) * (q.z - p.z) <= 0:
                return                                         # behind the camera
            rad_px *= self.street / max(2.0, math.sqrt((x - p.x) ** 2 + (gy - p.y) ** 2 + (z - p.z) ** 2))
        if -rad_px < sp.x < rl.get_screen_width() + rad_px and -rad_px < sp.y < rl.get_screen_height() + rad_px:
            rl.draw_circle_gradient(rl.Vector2(sp.x, sp.y), rad_px, _col(col[0], col[1], col[2], a), _col(0, 0, 0, 0))

    def draw(self, cam, rect, ppm, sim, dark, t, sw, sh, street=False):
        self.street = (sh / 2) / math.tan(math.radians(cam.fovy) / 2) / ppm if street else 0.0   # street view: glows shrink with distance
        emerg = []
        for c in sim.traffic.cars:
            if c.kind in clock.EMERGENCY and rect[0] < c.x < rect[2] and rect[1] < c.y < rect[3]:
                emerg.append((c.x, c.y, c.h, c.v > 3, c.kind))
        for b in sim.bodies:
            if b.kind in clock.EMERGENCY and rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3] and b.alive:
                emerg.append((b.x, b.y, b.h, bool(getattr(b, "siren", False) or getattr(b, "service", False)) or (b.player_car and b.speed > 3), b.kind))
        if dark > 0.02:
            tint = _col(255 - dark * 190, 255 - dark * 172, 255 - dark * 105, 255)
            rl.begin_blend_mode(rl.BLEND_MULTIPLIED)
            rl.draw_rectangle(0, 0, sw, sh, tint)
            rl.end_blend_mode()
        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
        if dark > 0.02:
            r_lamp = 7.5 * ppm
            for cx in range(int(rect[0] // CELL), int(rect[2] // CELL) + 1):
                for cy in range(int(rect[1] // CELL), int(rect[3] // CELL) + 1):
                    for x, y in self.cells.get((cx, cy), ()):
                        self._glow(cam, x, y, 4.5, r_lamp, (255, 205, 120), 150 * dark)
            for p in (sim.peds.list if self.detail >= 1 else ()):         # NPC cyclists / mopeds / scooters: one lamp, one tail light
                if p.mode == "walk" and p.arch in vehicles.JACK_KIND and rect[0] < p.x < rect[2] and rect[1] < p.y < rect[3]:
                    self._lights(cam, p.x, p.y, p.h, vehicles.JACK_KIND[p.arch], ppm, dark, False)
            for c in (sim.traffic.cars if self.detail >= 1 else ()):
                if rect[0] < c.x < rect[2] and rect[1] < c.y < rect[3]:
                    self._lights(cam, c.x, c.y, c.h, c.kind, ppm, dark, c.braking)
            for b in sim.bodies:
                if rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3] and b.alive and not b.empty and not b.exploded:
                    self._lights(cam, b.x, b.y, b.h, b.kind, ppm, dark, b.braking)
        lights = getattr(sim, "lights", None)
        if lights is not None:                                       # traffic lights glow like tail lights: faint by day, bright at night
            col = ((60, 255, 110), (255, 205, 40), (255, 40, 30))
            for lx, lz, ly, st in lights.lit(rect):
                self._glow(cam, lx, lz, ly, (1.3 + 2.0 * dark) * ppm, col[st], 70 + 150 * dark)
                if dark > 0.3:
                    self._glow(cam, lx, lz, ly, 0.8 * ppm, (255, 255, 255), 90 * dark)
        for b in sim.bodies:
            if b.health <= 0 and not b.out and rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3]:
                fl = 0.75 + 0.25 * math.sin(t * 17 + b.x)
                self._glow(cam, b.x, b.y, 1.2, 7 * ppm * fl, (255, 140, 40), 170 * max(0.35, dark))
        for x, y, h, on, kind in emerg:
            if not on:
                continue
            ph = int(t * 6.0) & 1
            hl = vehicles.DIMS[kind][0] * 0.05                       # light bar on this vehicle's own roof
            top = vehicles.DIMS[kind][4] + 0.12
            ca, sa = math.cos(h), math.sin(h)
            a = 235 * max(0.55, dark)
            for side, col in ((-1, (255, 30, 30)), (1, (40, 80, 255))):
                lit = (ph == 0) == (side < 0)
                if lit:
                    px, py = x + ca * hl - sa * 0.5 * side, y + sa * hl + ca * 0.5 * side
                    self._glow(cam, px, py, top, 6.5 * ppm, col, a)
                    self._glow(cam, px, py, top, 2.2 * ppm, (255, 255, 255), a * 0.6)
        rl.end_blend_mode()

    def _beam(self, cam, x, y, ca, sa, a, length=13.0, spread=0.3):
        """A headlight beam: exactly one soft triangle from the lamp forward."""
        p, q = cam.position, cam.target
        L = math.sqrt((q.x - p.x) ** 2 + (q.y - p.y) ** 2 + (q.z - p.z) ** 2)
        def scr(d, side):
            w_ = d * spread * side
            px, py = x + ca * d - sa * w_, y + sa * d + ca * w_
            gy = self.w.ground_y(px, py) + 0.15
            if (px - p.x) * (q.x - p.x) + (gy - p.y) * (q.y - p.y) + (py - p.z) * (q.z - p.z) <= 1.5 * L:
                return None                                   # behind / right at the camera: it would project mirrored and screen-sized
            return rl.get_world_to_screen(V3(px, gy, py), cam)
        p0, p1, p2 = scr(0.2, 0), scr(length, -1), scr(length, 1)
        if p0 is None or p1 is None or p2 is None:
            return
        if (p1.x - p0.x) * (p2.y - p0.y) - (p1.y - p0.y) * (p2.x - p0.x) > 0:   # raylib needs counter-clockwise
            p1, p2 = p2, p1
        # vertex colours: full at the lamp, fading to nothing at the far edge
        rl.rl_set_texture(0)
        rl.rl_begin(rl.RL_TRIANGLES)
        rl.rl_color4ub(255, 238, 190, int(min(255, a * 0.4)))
        rl.rl_vertex2f(p0.x, p0.y)
        rl.rl_color4ub(255, 238, 190, 0)
        rl.rl_vertex2f(p1.x, p1.y)
        rl.rl_vertex2f(p2.x, p2.y)
        rl.rl_end()

    def _lights(self, cam, x, y, h, kind, ppm, dark, braking):
        ca, sa = math.cos(h), math.sin(h)
        L, W = vehicles.DIMS[kind][0] / 2, vehicles.DIMS[kind][1] / 2
        a = 150 * dark
        lamp_y = max(0.45, vehicles.DIMS[kind][3] - 0.3)            # headlight height (belt line), not one fixed value
        if kind in vehicles.BIKES:                                  # two-wheelers: a single lamp and tail light on the centre line
            lamp_y = 0.95 if vehicles.EXTRA[kind] != "kick" else 0.9
            hx, hy = x + ca * L * 0.8, y + sa * L * 0.8
            self._beam(cam, hx, hy, ca, sa, a, 10.0, 0.25)
            self._glow(cam, hx, hy, lamp_y, 0.8 * ppm, (255, 250, 230), a * 1.4)
            tx, ty = x - ca * L * 0.9, y - sa * L * 0.9
            self._glow(cam, tx, ty, 0.6, (1.8 if braking else 1.0) * ppm, (255, 20, 20), a * (1.6 if braking else 0.7))
            return
        for s in (-1, 1):
            hx, hy = x + ca * L - sa * s * W * 0.7, y + sa * L + ca * s * W * 0.7
            self._beam(cam, hx, hy, ca, sa, a)
            self._glow(cam, hx, hy, lamp_y, 0.9 * ppm, (255, 250, 230), a * 1.4)
            tx, ty = x - ca * L - sa * s * W * 0.7, y - sa * L + ca * s * W * 0.7
            self._glow(cam, tx, ty, lamp_y, (2.2 if braking else 1.2) * ppm, (255, 20, 20), a * (1.6 if braking else 0.7))
