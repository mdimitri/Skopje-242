"""Presents the game frame: the world is always drawn into an offscreen buffer of the resolution chosen in the menu
and scaled to the window (windowed, maximized or fullscreen) with the chosen filter, letterboxed, optionally through FXAA.
While active, rl.get_screen_width/height and rl.get_world_to_screen report the buffer, not the window, so all drawing
code keeps working in the chosen resolution; the mouse is mapped back through rl.set_mouse_scale/offset."""
import pyray as rl

FS = """#version 330
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform vec2 px;
out vec4 finalColor;
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
void main() {
    vec2 uv = fragTexCoord;
    vec3 rgbM = texture(texture0, uv).rgb;
    vec3 rgbNW = texture(texture0, uv + vec2(-1.0, -1.0) * px).rgb;
    vec3 rgbNE = texture(texture0, uv + vec2(1.0, -1.0) * px).rgb;
    vec3 rgbSW = texture(texture0, uv + vec2(-1.0, 1.0) * px).rgb;
    vec3 rgbSE = texture(texture0, uv + vec2(1.0, 1.0) * px).rgb;
    float lM = luma(rgbM), lNW = luma(rgbNW), lNE = luma(rgbNE), lSW = luma(rgbSW), lSE = luma(rgbSE);
    float lMin = min(lM, min(min(lNW, lNE), min(lSW, lSE)));
    float lMax = max(lM, max(max(lNW, lNE), max(lSW, lSE)));
    vec2 dir = vec2(-((lNW + lNE) - (lSW + lSE)), (lNW + lSW) - (lNE + lSE));
    float reduce = max((lNW + lNE + lSW + lSE) * 0.25 * (1.0 / 8.0), 1.0 / 128.0);
    float rcpMin = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduce);
    dir = clamp(dir * rcpMin, vec2(-8.0), vec2(8.0)) * px;
    vec3 a = 0.5 * (texture(texture0, uv + dir * (1.0 / 3.0 - 0.5)).rgb + texture(texture0, uv + dir * (2.0 / 3.0 - 0.5)).rgb);
    vec3 b = a * 0.5 + 0.25 * (texture(texture0, uv + dir * -0.5).rgb + texture(texture0, uv + dir * 0.5).rgb);
    float lB = luma(b);
    finalColor = vec4((lB < lMin || lB > lMax) ? a : b, 1.0);
}
"""

MARGIN = 2

_orig_w, _orig_h, _orig_w2s = rl.get_screen_width, rl.get_screen_height, rl.get_world_to_screen
_orig_w2s_ex = rl.get_world_to_screen_ex
vw = vh = 0                      # 0 = off: the helpers answer with the window
pending_quit = False             # the exit button was pressed while the frame buffer was active


def _sw():
    return vw or _orig_w()


def _sh():
    return vh or _orig_h()


def _w2s(pos, cam):
    return rl.get_world_to_screen_ex(pos, cam, vw, vh) if vw else _orig_w2s(pos, cam)


rl.get_screen_width, rl.get_screen_height, rl.get_world_to_screen = _sw, _sh, _w2s


def off():
    """Back to the plain window (menus and loaders draw to it directly)."""
    global vw, vh
    vw = vh = 0
    rl.set_mouse_scale(1.0, 1.0)
    rl.set_mouse_offset(0, 0)


def snap_cam(cam, w, h):
    """Free (street, chase, indoor) camera -> (camera snapped to the pixel lattice, (sx, sy) shift in buffer pixels).
    The view direction is rounded to whole pixels of the picture centre and the position to whole pixels at the distance of the
    look-at point (sideways and up only); the shift is where the true camera would show that point relative to the snapped one."""
    import math
    P, T = cam.position, cam.target
    fx, fy, fz = T.x - P.x, T.y - P.y, T.z - P.z
    D = math.sqrt(fx * fx + fy * fy + fz * fz)
    if D < 1e-3:
        return cam, (0.0, 0.0)
    f = (h / 2) / math.tan(math.radians(cam.fovy) / 2)
    q = 1.0 / f
    yq = round(math.atan2(fx, fz) / q) * q
    pq = round(math.asin(max(-0.999, min(0.999, fy / D))) / q) * q
    cp = math.cos(pq)
    F = (math.sin(yq) * cp, math.sin(pq), math.cos(yq) * cp)
    R = (F[2] / cp, 0.0, -F[0] / cp)                                   # F x up, normalised
    U = (R[1] * F[2] - R[2] * F[1], R[2] * F[0] - R[0] * F[2], R[0] * F[1] - R[1] * F[0])
    U = (-U[0], -U[1], -U[2]) if U[1] < 0 else U
    step = D / f
    a = P.x * R[0] + P.z * R[2]
    b = P.x * U[0] + P.y * U[1] + P.z * U[2]
    da, db = round(a / step) * step - a, round(b / step) * step - b
    P2 = rl.Vector3(P.x + da * R[0] + db * U[0], P.y + db * U[1], P.z + da * R[2] + db * U[2])
    T2 = rl.Vector3(P2.x + F[0] * D, P2.y + F[1] * D, P2.z + F[2] * D)
    cam2 = rl.Camera3D(P2, T2, cam.up, cam.fovy, cam.projection)
    p = _orig_w2s_ex(T, cam2, w, h)
    m = MARGIN - 0.1
    return cam2, (max(-m, min(m, w / 2 - p.x)), max(-m, min(m, h / 2 - p.y)))


class Present:
    def __init__(self):
        self.rt = None
        self.ui = None                   # HUD layer (transparent), drawn after the world is shifted by the camera's sub-pixel remainder
        self.stage = 0                   # 0: drawing the world, 1: drawing the HUD layer
        self.shift = None                # (sx, sy) buffer pixels, or None: plain full-frame blit
        self.sh = None
        self.loc = 0
        self.dest = (0.0, 0.0, 1.0, 1.0)

    def _shader(self):
        if self.sh is None:
            vs = "#version 330\nin vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; uniform mat4 mvp; out vec2 fragTexCoord; out vec4 fragColor;\nvoid main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; gl_Position = mvp * vec4(vertexPosition, 1.0); }"
            self.sh = rl.load_shader_from_memory(vs, FS)
            self.loc = rl.get_shader_location(self.sh, "px")
        return self.sh

    def activate(self, w, h):
        """Loop start: choose the buffer size, map the mouse (call once per frame, before reading input)."""
        global vw, vh
        if self.rt is None or (vw, vh) != (w, h) and (self.rt.texture.width, self.rt.texture.height) != (w, h):
            if self.rt is not None:
                rl.unload_render_texture(self.rt)
                rl.unload_render_texture(self.ui)
            self.rt = rl.load_render_texture(w, h)
            self.ui = rl.load_render_texture(w, h)
        self.shift = None
        vw, vh = w, h
        ww, wh = _orig_w(), _orig_h()
        s = min(ww / w, wh / h)
        dw, dh = w * s, h * s
        ox, oy = (ww - dw) / 2, (wh - dh) / 2
        self.dest = (ox, oy, dw, dh)
        rl.set_mouse_scale(w / dw, h / dh)
        rl.set_mouse_offset(-int(ox), -int(oy))

    def begin(self):
        self.stage = 0
        rl.begin_texture_mode(self.rt)

    def set_shift(self, sx, sy):
        """The camera was snapped to whole buffer pixels; the world layer is shown moved by (sx, sy) buffer pixels (|s| <= 0.5) at window
        resolution, so the buffer never gets resampled while the motion stays smooth.  Call before ui()."""
        self.shift = (sx, sy)

    def ui_layer(self):
        """Everything drawn after this call is the HUD: it goes into its own transparent buffer and is not shifted."""
        rl.end_texture_mode()
        rl.begin_texture_mode(self.ui)
        rl.clear_background(rl.BLANK)
        rl.rl_set_blend_factors_separate(0x0302, 0x0303, 1, 0x0303, 0x8006, 0x8006)     # premultiplied colour, true alpha
        rl.begin_blend_mode(rl.BLEND_CUSTOM_SEPARATE)
        self.stage = 1

    def end(self, nearest, fxaa):
        """Close the buffer and draw it onto the window (call before end_drawing)."""
        if self.stage == 1:
            rl.end_blend_mode()
        rl.end_texture_mode()
        if vw <= 0 or vh <= 0:   # window minimised: nothing to draw
            return
        flt = rl.TEXTURE_FILTER_POINT if nearest else rl.TEXTURE_FILTER_BILINEAR
        rl.set_texture_filter(self.rt.texture, flt)
        rl.clear_background(rl.BLACK)
        if self.shift is not None and vw > 2 * MARGIN and vh > 2 * MARGIN:     # one buffer pixel is cut off all round, the shift moves the window over it
            sx, sy = self.shift
            src = rl.Rectangle(MARGIN - sx, MARGIN + sy, vw - 2 * MARGIN, -(vh - 2 * MARGIN))
        else:
            src = rl.Rectangle(0, 0, vw, -vh)
        dst = rl.Rectangle(*self.dest)
        if fxaa:
            sh = self._shader()
            rl.set_shader_value(sh, self.loc, rl.ffi.new("float[2]", [1.0 / vw, 1.0 / vh]), rl.SHADER_UNIFORM_VEC2)
            rl.begin_shader_mode(sh)
        rl.draw_texture_pro(self.rt.texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
        if fxaa:
            rl.end_shader_mode()
        if self.stage == 1:
            rl.set_texture_filter(self.ui.texture, flt)
            rl.begin_blend_mode(rl.BLEND_ALPHA_PREMULTIPLY)
            rl.draw_texture_pro(self.ui.texture, rl.Rectangle(0, 0, vw, -vh), dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
            rl.end_blend_mode()
