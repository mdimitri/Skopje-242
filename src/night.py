"""Night look: a blue multiply tint over the 3D scene plus additive light pools (street lamps, headlights,
tail lights, emergency light bars, burning wrecks).  Screen-space, drawn after the 3D pass and before the HUD."""
import math

import pyray as rl

import clock
import vehicles

V3 = rl.Vector3
CELL = 60.0


def _col(r, g, b, a):
    return rl.Color(int(r), int(g), int(b), int(max(0, min(255, a))))


class Night:
    def __init__(self, world):
        self.cells = {}
        self.w = world
        self.detail = 2
        for x, y in getattr(world, "lamps", ()):
            self.cells.setdefault((int(x // CELL), int(y // CELL)), []).append((x, y))

    def _glow(self, cam, x, z, y, rad_px, col, a):
        sp = rl.get_world_to_screen(V3(x, y + self.w.ground_y(x, z), z), cam)
        if -rad_px < sp.x < rl.get_screen_width() + rad_px and -rad_px < sp.y < rl.get_screen_height() + rad_px:
            rl.draw_circle_gradient(rl.Vector2(sp.x, sp.y), rad_px, _col(col[0], col[1], col[2], a), _col(0, 0, 0, 0))

    def draw(self, cam, rect, ppm, sim, dark, t, sw, sh):
        emerg = []
        for c in sim.traffic.cars:
            if c.kind in clock.EMERGENCY and rect[0] < c.x < rect[2] and rect[1] < c.y < rect[3]:
                emerg.append((c.x, c.y, c.h, c.v > 3))
        for b in sim.bodies:
            if b.kind in clock.EMERGENCY and rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3] and b.alive:
                emerg.append((b.x, b.y, b.h, bool(getattr(b, "siren", False) or getattr(b, "service", False)) or (b.player_car and b.speed > 3)))
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
            for c in (sim.traffic.cars if self.detail >= 1 else ()):
                if rect[0] < c.x < rect[2] and rect[1] < c.y < rect[3]:
                    self._lights(cam, c.x, c.y, c.h, c.kind, ppm, dark, c.braking)
            for b in sim.bodies:
                if rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3] and b.alive and not b.empty and not b.exploded:
                    self._lights(cam, b.x, b.y, b.h, b.kind, ppm, dark, b.braking)
        for b in sim.bodies:
            if b.health <= 0 and not b.out and rect[0] < b.x < rect[2] and rect[1] < b.y < rect[3]:
                fl = 0.75 + 0.25 * math.sin(t * 17 + b.x)
                self._glow(cam, b.x, b.y, 1.2, 7 * ppm * fl, (255, 140, 40), 170 * max(0.35, dark))
        for x, y, h, on in emerg:
            if not on:
                continue
            ph = int(t * 6.0) & 1
            hl = vehicles.HALF_L[47] * 0.1
            ca, sa = math.cos(h), math.sin(h)
            a = 235 * max(0.55, dark)
            for side, col in ((-1, (255, 30, 30)), (1, (40, 80, 255))):
                lit = (ph == 0) == (side < 0)
                if lit:
                    px, py = x + ca * hl - sa * 0.5 * side, y + sa * hl + ca * 0.5 * side
                    self._glow(cam, px, py, 1.9, 6.5 * ppm, col, a)
                    self._glow(cam, px, py, 1.9, 2.2 * ppm, (255, 255, 255), a * 0.6)
        rl.end_blend_mode()

    def _beam(self, cam, x, y, ca, sa, a, length=13.0, spread=0.3):
        """A headlight beam: exactly one soft triangle from the lamp forward."""
        def scr(d, side):
            w_ = d * spread * side
            px, py = x + ca * d - sa * w_, y + sa * d + ca * w_
            return rl.get_world_to_screen(V3(px, self.w.ground_y(px, py) + 0.15, py), cam)
        p0, p1, p2 = scr(0.2, 0), scr(length, -1), scr(length, 1)
        if (p1.x - p0.x) * (p2.y - p0.y) - (p1.y - p0.y) * (p2.x - p0.x) > 0:   # raylib needs counter-clockwise
            p1, p2 = p2, p1
        rl.draw_triangle(p0, p1, p2, _col(255, 238, 190, a * 0.3))

    def _lights(self, cam, x, y, h, kind, ppm, dark, braking):
        ca, sa = math.cos(h), math.sin(h)
        L, W = vehicles.HALF_L[kind], vehicles.HALF_W[kind]
        a = 150 * dark
        for s in (-1, 1):
            hx, hy = x + ca * L - sa * s * W * 0.7, y + sa * L + ca * s * W * 0.7
            self._beam(cam, hx, hy, ca, sa, a)
            self._glow(cam, hx, hy, 0.6, 0.9 * ppm, (255, 250, 230), a * 1.4)
            tx, ty = x - ca * L - sa * s * W * 0.7, y - sa * L + ca * s * W * 0.7
            self._glow(cam, tx, ty, 0.6, (2.2 if braking else 1.2) * ppm, (255, 20, 20), a * (1.6 if braking else 0.7))
