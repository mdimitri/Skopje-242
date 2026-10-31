"""Скопски смог: a brownish haze over the screen plus slow drifting clouds of it, thickest on winter-like
mornings and evenings and with heavy traffic. Pure 2D overlay: a handful of soft circles, no extra 3D cost."""
import math

import pyray as rl

CELL = 70.0
WIND = (0.9, 0.35)                     # m/s, the clouds drift slowly over the city


def density(hour, traffic=0.5):
    """0..1: Skopje smog peaks in the morning (heating, rush hour) and late evening."""
    m = math.exp(-((hour - 8.0) / 2.2) ** 2)
    e = math.exp(-((hour - 20.5) / 3.0) ** 2)
    n = 0.35 if (hour >= 22 or hour < 5) else 0.0
    return min(1.0, 0.18 + 0.55 * max(m, e, n) + 0.25 * traffic)


def _h(i, j, k):
    v = math.sin(i * 127.1 + j * 311.7 + k * 74.7) * 43758.5453
    return v - math.floor(v)


def draw(cam, cam_x, cam_y, ppm, sw, sh, hour, t, traffic=0.5, strength=1.0, gy=0.0):
    d = density(hour, traffic) * strength
    if d <= 0.02:
        return
    rl.draw_rectangle(0, 0, sw, sh, rl.Color(150, 138, 112, min(210, int(64 * d))))
    ox, oy = WIND[0] * t, WIND[1] * t
    half_w, half_h = sw / 2 / ppm + CELL, sh / 2 / ppm + CELL
    i0, i1 = int(math.floor((cam_x - ox - half_w) / CELL)), int(math.floor((cam_x - ox + half_w) / CELL))
    j0, j1 = int(math.floor((cam_y - oy - half_h) / CELL)), int(math.floor((cam_y - oy + half_h) / CELL))
    if (i1 - i0 + 1) * (j1 - j0 + 1) > 160:           # far zoom: the flat haze is enough
        return
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            if _h(i, j, 0) > (0.35 + 0.5 * (1 - d) if d <= 1 else min(0.95, 0.35 + 0.2 * (d - 1))):
                continue
            wx = (i + _h(i, j, 1)) * CELL + ox
            wy = (j + _h(i, j, 2)) * CELL + oy
            r = (22 + 34 * _h(i, j, 3)) * ppm * (1.0 + 0.25 * max(0.0, d - 1))
            v = rl.get_world_to_screen(rl.Vector3(wx, gy + 2.5, wy), cam)
            sx, sy = v.x, v.y
            a = min(190, int(70 * d * (0.6 + 0.4 * math.sin(t * 0.2 + i * 1.7 + j))))
            rl.draw_circle_gradient(rl.Vector2(sx, sy), r, rl.Color(160, 148, 124, a), rl.Color(160, 148, 124, 0))
