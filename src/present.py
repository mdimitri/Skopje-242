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

DOF_FS = """#version 330
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;     // the world colour
uniform sampler2D texture1;     // its depth (a depth texture attached to the same frame buffer)
uniform vec2 px;
uniform vec4 dof;               // x = blur radius at full defocus (buffer pixels), y = focus distance (m), z = near, w = far
uniform float aa;               // 1: sharp pixels still go through FXAA
uniform float keep;             // metres around the focus that never blur (the hero's own size)
uniform float gam;              // depth gamma: depth / far distance ^ gam drives the blur (1 = linear in distance, <1 blurs nearer, >1 only far away)
out vec4 finalColor;
float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }
float lin(vec2 uv) { float d = texture(texture1, uv).r * 2.0 - 1.0; return 2.0 * dof.z * dof.w / (dof.w + dof.z - d * (dof.w - dof.z)); }
float enc(float z) { return pow(clamp(z / dof.w, 0.0, 1.0), gam); }
float coc(float z) {                                   // pixels; 0 at the focus, full radius at the camera and at the far plane, the middle band stays sharp
    float dz = z - dof.y;
    z = abs(dz) < keep ? dof.y : z - sign(dz) * keep;                  // the hero and a little of what is right around it stay sharp
    float t = enc(z), tf = enc(dof.y);
    float x = (t > tf ? (t - tf) / max(1.0 - tf, 1e-3) : (tf - t) / max(tf, 1e-3));
    return dof.x * clamp((x - 0.05) * 1.1, 0.0, 1.0);
}
void main() {
    vec2 uv = fragTexCoord;
    float c0 = coc(lin(uv));
    if (c0 > 0.5) {                                     // out of focus: 14 taps on a rotated spiral, a tap counts only if its own blur reaches this pixel
        float rot = 6.2831853 * fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
        vec3 sum = texture(texture0, uv).rgb;
        float wsum = 1.0;
        for (int i = 0; i < 14; i++) {
            float r = sqrt((float(i) + 0.5) / 14.0);
            float a = rot + float(i) * 2.3999632;
            vec2 o = vec2(cos(a), sin(a)) * r * c0;
            vec2 tuv = uv + o * px;
            float w = clamp(coc(lin(tuv)) - r * c0 + 1.0, 0.0, 1.0);
            sum += texture(texture0, tuv).rgb * w;
            wsum += w;
        }
        finalColor = vec4(sum / wsum, 1.0);
        return;
    }
    vec3 rgbM = texture(texture0, uv).rgb;
    if (aa < 0.5) { finalColor = vec4(rgbM, 1.0); return; }
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
    _VS = "#version 330\nin vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; uniform mat4 mvp; out vec2 fragTexCoord; out vec4 fragColor;\nvoid main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; gl_Position = mvp * vec4(vertexPosition, 1.0); }"

    def __init__(self):
        self.rt = None
        self.ui = None                   # HUD layer (transparent), drawn after the world is shifted by the camera's sub-pixel remainder
        self.stage = 0                   # 0: drawing the world, 1: drawing the HUD layer
        self.shift = None                # (sx, sy) buffer pixels, or None: plain full-frame blit
        self.sh = None
        self.loc = 0
        self.dsh = None                  # depth-of-field shader (built on first use)
        self.dof = None                  # (radius px at full defocus, focus m, near, far) for this frame, or None: off
        self.depth = 0                   # id of the depth texture attached to rt (0 until depth of field is first used)
        self.dest = (0.0, 0.0, 1.0, 1.0)

    def _shader(self):
        if self.sh is None:
            self.sh = rl.load_shader_from_memory(self._VS, FS)
            self.loc = rl.get_shader_location(self.sh, "px")
        return self.sh

    def set_dof(self, strength, focus, near, far, gamma=1.0, keep=1.0):
        """This frame's world is a free 3D view: blur by depth around `focus` metres (strength 1 = 8 px at full defocus on a 1080-line frame).
        Call after the world is drawn, before end(); not calling it (or strength 0) leaves the frame exactly as without the effect."""
        self.dof = (strength * 8.0 * vh / 1080.0, max(1.0, focus), near, far) if strength > 0.01 and vh > 0 else None
        self.dof_g, self.dof_keep = gamma, keep

    def _depth_tex(self):
        """A depth texture in place of the render texture's depth renderbuffer (sampled by the blur; same storage, no extra pass)."""
        if not self.depth:
            self.depth = rl.rl_load_texture_depth(self.rt.texture.width, self.rt.texture.height, False)
            rl.rl_framebuffer_attach(self.rt.id, self.depth, rl.RL_ATTACHMENT_DEPTH, rl.RL_ATTACHMENT_TEXTURE2D, 0)
        return self.depth

    def activate(self, w, h):
        """Loop start: choose the buffer size, map the mouse (call once per frame, before reading input)."""
        global vw, vh
        if self.rt is None or (vw, vh) != (w, h) and (self.rt.texture.width, self.rt.texture.height) != (w, h):
            if self.rt is not None:
                rl.unload_render_texture(self.rt)
                rl.unload_render_texture(self.ui)
            self.rt = rl.load_render_texture(w, h)
            self.depth = 0
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

    def begin(self, dof=False):
        """dof: the effect is on this frame, so the world's depth must be kept in a texture."""
        self.stage = 0
        self.dof = None
        if dof:
            self._depth_tex()
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
        dof = self.dof if self.depth else None
        if dof:
            if self.dsh is None:
                self.dsh = rl.load_shader_from_memory(self._VS, DOF_FS)
                self.dloc = {k: rl.get_shader_location(self.dsh, k) for k in ("px", "dof", "aa", "gam", "keep", "texture1")}
            sh = self.dsh
            rl.set_shader_value(sh, self.dloc["px"], rl.ffi.new("float[2]", [1.0 / vw, 1.0 / vh]), rl.SHADER_UNIFORM_VEC2)
            rl.set_shader_value(sh, self.dloc["dof"], rl.ffi.new("float[4]", list(dof)), rl.SHADER_UNIFORM_VEC4)
            rl.set_shader_value(sh, self.dloc["gam"], rl.ffi.new("float *", float(getattr(self, "dof_g", 1.0))), rl.SHADER_UNIFORM_FLOAT)
            rl.set_shader_value(sh, self.dloc["keep"], rl.ffi.new("float *", float(getattr(self, "dof_keep", 1.0))), rl.SHADER_UNIFORM_FLOAT)
            rl.set_shader_value(sh, self.dloc["aa"], rl.ffi.new("float *", 1.0 if fxaa else 0.0), rl.SHADER_UNIFORM_FLOAT)
            rl.begin_shader_mode(sh)
            rl.set_shader_value_texture(sh, self.dloc["texture1"], rl.Texture(self.depth, self.rt.texture.width, self.rt.texture.height, 1, 19))
        elif fxaa:
            sh = self._shader()
            rl.set_shader_value(sh, self.loc, rl.ffi.new("float[2]", [1.0 / vw, 1.0 / vh]), rl.SHADER_UNIFORM_VEC2)
            rl.begin_shader_mode(sh)
        rl.draw_texture_pro(self.rt.texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
        if fxaa or dof:
            rl.end_shader_mode()
        if self.stage == 1:
            rl.set_texture_filter(self.ui.texture, flt)
            rl.begin_blend_mode(rl.BLEND_ALPHA_PREMULTIPLY)
            rl.draw_texture_pro(self.ui.texture, rl.Rectangle(0, 0, vw, -vh), dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
            rl.end_blend_mode()
