"""Night lights without touching the scene's geometry: street lamps, headlights and tail lights are painted as soft
additive sprites into one small top-down texture around the view (the light map, 512 px, redrawn every frame: it is only
a few dozen sprites), and that texture is laid over the ground as a thin additive grid (one cheap textured pass, depth
tested so buildings and cars hide it).  Lamp bulbs are small depth-tested glows.  A second light pass only makes a few
building windows glow (windows.py-style shader below).  Nothing here depends on how many lights there are or on zoom:
the map always covers the view, so layers cannot pop in and out."""
import math

import numpy as np
import pyray as rl

V3 = rl.Vector3
SIZE = 512
GRID = 28                        # the overlay is a GRID x GRID mesh draped over the terrain
LIFT = 0.28                      # metres above the ground: above the 0.16 m pavements
WIN_R = 90.0                     # windows glow within this distance of the view centre (top-down); STREET_WIN_R in street view
STREET_WIN_R = 190.0             # the street view sees far down the street: all those facades get lit windows too
SKIP_MATS = (3, 6)               # road surface meshes and graffiti decals have no windows (the decal's transparent texels would glow as a lit pane)

WIN_VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor;
uniform mat4 mvp;
out vec2 fragTexCoord; out vec3 wp;
void main(){ fragTexCoord = vertexTexCoord; wp = vertexPosition;
             gl_Position = mvp * vec4(vertexPosition, 1.0); gl_Position.z -= 0.0003 * gl_Position.w; }"""
WIN_FS = """#version 330
in vec2 fragTexCoord; in vec3 wp;
uniform sampler2D texture0; uniform float wglow; uniform vec3 wc;
out vec4 finalColor;
void main(){
  vec3 n = normalize(cross(dFdx(wp), dFdy(wp)));
  if (abs(n.y) > 0.6) discard;                                            // walls only
  vec3 tx = texture(texture0, fragTexCoord).rgb;
  float lum = dot(tx, vec3(0.333));
  float avg = dot(textureLod(texture0, fragTexCoord, 3.0).rgb, vec3(0.333));         // the facade's local average: glazing is darker than its surroundings
  float glass = max(1.0 - smoothstep(0.18, 0.36, lum), clamp((avg - lum) * 7.0 - 0.1, 0.0, 1.0));
  if (glass <= 0.01) discard;
  vec2 cell = floor(vec2((wp.x + wp.z) / 3.4, wp.y / 3.0));                // one random flag per ~3 m cell
  float h = fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
  float on = step(0.5, h) * (0.75 + 0.25 * fract(h * 7.0));
  float dist = length(wp.xz - wc.xy);
  float fade = 1.0 - smoothstep(0.75 * wc.z, wc.z, dist);                 // no hard cutoff ring
  if (fade <= 0.0) discard;
  vec3 col = mix(vec3(1.0, 0.78, 0.45), vec3(0.75, 0.88, 1.0), step(0.93, h));     // warm, a few TV-blue
  finalColor = vec4(col * glass * on * wglow * fade * 1.1, 1.0);
}"""


def _soft_tex():
    n = 128
    y, x = np.mgrid[0:n, 0:n]
    d = np.hypot((x + 0.5) / n * 2 - 1, (y + 0.5) / n * 2 - 1)
    v = np.clip(1.0 - d, 0.0, 1.0) ** 2
    px = np.zeros((n, n, 4), np.uint8)
    px[..., :3] = (v * 255)[..., None]
    px[..., 3] = 255
    img = rl.gen_image_color(n, n, rl.BLACK)
    rl.image_format(img, rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    tex = rl.load_texture_from_image(img)
    rl.unload_image(img)
    rl.update_texture(tex, rl.ffi.new("unsigned char[]", px.tobytes()))
    rl.set_texture_filter(tex, rl.TEXTURE_FILTER_BILINEAR)
    rl.set_texture_wrap(tex, rl.TEXTURE_WRAP_CLAMP)
    return tex


class LightMap:
    def __init__(self, world, streamer):
        self.w, self.st = world, streamer
        self.rt = rl.load_render_texture(SIZE, SIZE)
        rl.set_texture_filter(self.rt.texture, rl.TEXTURE_FILTER_BILINEAR)
        rl.set_texture_wrap(self.rt.texture, rl.TEXTURE_WRAP_CLAMP)
        self.soft = _soft_tex()
        self.sprites, self.bulbs = [], []
        self.ox = self.oz = 0.0
        self.span = 100.0
        self.cx = self.cz = 0.0
        self.win = None
        self.street = False

    # ------------------------------------------------------------ region + queue (before the frame's drawing starts)
    def begin(self, cam, rect, street):
        """The map covers the view: the visible rect (top-down) or 220 m around the avatar (street view)."""
        if street:
            self.cx, self.cz, self.span = cam.target.x, cam.target.z, 220.0
        else:
            self.cx, self.cz = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
            self.span = min(380.0, max(100.0, 1.15 * max(rect[2] - rect[0], rect[3] - rect[1])))
        self.ox, self.oz = self.cx - self.span / 2, self.cz - self.span / 2
        self.sprites, self.bulbs = [], []
        self.street = street

    def inside(self, x, z, pad=0.0):
        h = self.span / 2 + pad
        return abs(x - self.cx) < h and abs(z - self.cz) < h

    def pool(self, x, z, r, col, k):
        """A round pool of light (street lamp, tail light): radius r metres, peak strength k (0..1)."""
        self.sprites.append((x, z, 2 * r, 2 * r, 0.0, col, k))

    def spot(self, x, z, h, length, width, col, k):
        """A headlight beam on the ground: an ellipse starting at (x, z) and reaching length metres along heading h."""
        ca, sa = math.cos(h), math.sin(h)
        self.sprites.append((x + ca * length / 2, z + sa * length / 2, length, width, math.degrees(h), col, k))

    def bulb(self, x, y, z, col):
        self.bulbs.append((x, y, z, col))

    # ------------------------------------------------------------ draw: texture first (outside any texture mode)
    def render(self):
        rl.begin_texture_mode(self.rt)
        rl.clear_background(rl.Color(0, 0, 0, 255))
        rl.begin_mode_2d(rl.Camera2D(rl.Vector2(0, 0), rl.Vector2(self.ox, self.oz), 0.0, SIZE / self.span))
        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
        src = rl.Rectangle(0, 0, 128, 128)
        try:
            for x, z, ln, wd, deg, col, k in self.sprites:
                rl.draw_texture_pro(self.soft, src, rl.Rectangle(x, z, ln, wd), rl.Vector2(ln / 2, wd / 2), deg,
                                    rl.Color(col[0], col[1], col[2], int(255 * min(1.0, k))))
        finally:
            rl.end_blend_mode()
            rl.end_mode_2d()
            rl.end_texture_mode()

    # ------------------------------------------------------------ draw: overlay (inside the scene's render target, after the night tint)
    def overlay(self, cam, dark):
        w, n = self.w, GRID
        xs = self.ox + np.arange(n + 1) * (self.span / n)
        zs = self.oz + np.arange(n + 1) * (self.span / n)
        X, Z = np.meshgrid(xs, zs)
        Y = (w.th_v(X, Z) if w.hilly else np.zeros_like(X, np.float32)) + LIFT
        r = np.maximum(np.abs(X - self.cx), np.abs(Z - self.cz)) / (self.span / 2)
        fade = 1.0 - np.clip((r - 0.75) / 0.25, 0.0, 1.0)                  # the map fades out at its border: no hard edge
        A = (255 * np.minimum(1.0, dark * 1.5) * fade).astype(int)
        rl.begin_mode_3d(cam)
        try:
            rl.rl_disable_backface_culling()
            rl.rl_enable_depth_test()
            rl.rl_disable_depth_mask()
            rl.begin_blend_mode(rl.BLEND_ADDITIVE)
            rl.rl_set_texture(self.rt.texture.id)
            rl.rl_begin(rl.RL_QUADS)
            for i in range(n):
                for j in range(n):
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        a_, b_ = i + di, j + dj
                        rl.rl_color4ub(255, 255, 255, int(A[b_, a_]))
                        rl.rl_tex_coord2f((X[b_, a_] - self.ox) / self.span, 1.0 - (Z[b_, a_] - self.oz) / self.span)
                        rl.rl_vertex3f(float(X[b_, a_]), float(Y[b_, a_]), float(Z[b_, a_]))
            rl.rl_end()
            rl.rl_set_texture(self.soft.id)
            rl.rl_begin(rl.RL_QUADS)
            p, q = cam.position, cam.target
            fx_, fy_, fz_ = q.x - p.x, q.y - p.y, q.z - p.z
            fl = math.sqrt(fx_ * fx_ + fy_ * fy_ + fz_ * fz_) or 1.0
            fx_, fy_, fz_ = fx_ / fl, fy_ / fl, fz_ / fl
            rx, rz = fz_, -fx_                                              # right = forward x up
            rn = math.hypot(rx, rz) or 1.0
            rx, rz = rx / rn, rz / rn
            ux, uy, uz = -fy_ * rz, fx_ * rz - fz_ * rx, fy_ * rx           # up = right x forward
            un = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
            ux, uy, uz = ux / un, uy / un, uz / un
            for x, y, z, col in self.bulbs:
                d = math.sqrt((x - p.x) ** 2 + (y - p.y) ** 2 + (z - p.z) ** 2)
                s = max(0.5, d * 0.012)                                     # never smaller than a few pixels, grows slowly with distance
                rl.rl_color4ub(col[0], col[1], col[2], int(230 * min(1.0, dark * 1.5)))
                for (u, v, tu, tv) in ((-1, -1, 0, 0), (1, -1, 1, 0), (1, 1, 1, 1), (-1, 1, 0, 1)):
                    rl.rl_tex_coord2f(tu, tv)
                    rl.rl_vertex3f(x + (rx * u * s + ux * v * s), y + uy * v * s, z + (rz * u * s + uz * v * s))
            rl.rl_end()
            rl.rl_set_texture(0)
            rl.end_blend_mode()
        finally:
            rl.rl_enable_depth_mask()
            rl.end_mode_3d()

    def windows(self, cam, dark):
        """Some facade windows glow: the chunk meshes near the view centre are drawn again, additively, with a tiny shader."""
        if self.win is None:
            try:
                sh = rl.load_shader_from_memory(WIN_VS, WIN_FS)
                if not sh.id or sh.id == rl.rl_get_shader_id_default():
                    raise RuntimeError("window shader did not compile")
                self.win = (sh, rl.get_shader_location(sh, "wglow"), rl.get_shader_location(sh, "wc"))
            except Exception as e:  # noqa: BLE001
                print(f"[gfx] window glow off: {e}")
                self.win = False
        if not self.win:
            return
        sh, loc, wcl = self.win
        R = STREET_WIN_R if self.street else WIN_R
        rl.set_shader_value(sh, wcl, rl.ffi.new("float[3]", [self.cx, self.cz, R]), rl.SHADER_UNIFORM_VEC3)
        rl.set_shader_value(sh, loc, rl.ffi.new("float *", min(1.0, dark * 1.4) * 0.95), rl.SHADER_UNIFORM_FLOAT)
        S, st = self.w.chunk, self.st
        ident = rl.matrix_identity()
        rl.begin_mode_3d(cam)
        try:
            rl.rl_disable_backface_culling()
            rl.rl_enable_depth_test()
            rl.rl_disable_depth_mask()
            rl.begin_blend_mode(rl.BLEND_ADDITIVE)
            for cx_ in range(int((self.cx - R) // S), int((self.cx + R) // S) + 1):
                for cy_ in range(int((self.cz - R) // S), int((self.cz + R) // S) + 1):
                    me = st.meshes.get((cx_, cy_))
                    if me is None:
                        continue
                    for mat_id, m in me[0].items():
                        if mat_id in SKIP_MATS:
                            continue
                        mat = m.materials[0]
                        old = rl.ffi.new("Shader *", mat.shader)             # a real copy: mat.shader is a view into the material
                        mat.shader = sh
                        rl.draw_mesh(m.meshes[0], mat, ident)
                        mat.shader = old[0]
            rl.end_blend_mode()
        finally:
            rl.rl_enable_depth_mask()
            rl.end_mode_3d()
