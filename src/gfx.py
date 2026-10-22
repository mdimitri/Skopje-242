"""Tiny immediate-mode helpers on top of raylib's rlgl (scalar calls, no per-vertex Vector2 objects)."""
import math

import pyray as rl

TRIANGLES = rl.RL_TRIANGLES
_begin, _end, _col, _vtx = rl.rl_begin, rl.rl_end, rl.rl_color4ub, rl.rl_vertex2f
_cos = [math.cos(2 * math.pi * i / 16) for i in range(17)]
_sin = [math.sin(2 * math.pi * i / 16) for i in range(17)]


def fill_tris(v, tri, c, ox=0.0, oy=0.0, ks=None):
    """Triangles given by flat index list `tri` into vertex list `v`; optional triangle subset `ks`."""
    _begin(TRIANGLES)
    _col(c[0], c[1], c[2], c[3] if len(c) > 3 else 255)
    it = range(len(tri) // 3) if ks is None else ks
    for k in it:
        a, b, d = v[tri[3 * k]], v[tri[3 * k + 1]], v[tri[3 * k + 2]]
        _vtx(a[0] + ox, a[1] + oy)
        _vtx(b[0] + ox, b[1] + oy)
        _vtx(d[0] + ox, d[1] + oy)
    _end()


def quad(ax, ay, bx, by, cx, cy, dx, dy, c):
    _begin(TRIANGLES)
    _col(c[0], c[1], c[2], c[3] if len(c) > 3 else 255)
    _vtx(ax, ay); _vtx(bx, by); _vtx(cx, cy)
    _vtx(ax, ay); _vtx(cx, cy); _vtx(dx, dy)
    _end()


def seg(x1, y1, x2, y2, hw, c):
    """Thick segment (half-width hw)."""
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return
    nx, ny = -dy / d * hw, dx / d * hw
    quad(x1 + nx, y1 + ny, x2 + nx, y2 + ny, x2 - nx, y2 - ny, x1 - nx, y1 - ny, c)


def disc(x, y, r, c, n=8):
    step = 16 // n
    _begin(TRIANGLES)
    _col(c[0], c[1], c[2], c[3] if len(c) > 3 else 255)
    for i in range(0, 16, step):
        _vtx(x, y)
        _vtx(x + _cos[i + step] * r, y + _sin[i + step] * r)
        _vtx(x + _cos[i] * r, y + _sin[i] * r)
    _end()


def rect_rot(cx, cy, hl, hw, ang, c, ox=0.0, oy=0.0):
    """Rotated rectangle centred at (cx,cy)+local offset (ox,oy), half-length hl along `ang`."""
    ca, sa = math.cos(ang), math.sin(ang)
    cx += ca * ox - sa * oy
    cy += sa * ox + ca * oy
    ax, ay = ca * hl, sa * hl
    bx, by = -sa * hw, ca * hw
    quad(cx - ax - bx, cy - ay - by, cx + ax - bx, cy + ay - by, cx + ax + bx, cy + ay + by, cx - ax + bx, cy - ay + by, c)
