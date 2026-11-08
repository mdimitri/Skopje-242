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

# Tilt-shift / "toytown": the picture stays sharp in a horizontal band round the middle and blurs towards the top and bottom,
# a little more colour and contrast like a miniature model. strength 0..1; the black demo bars (bar = fraction of the height) stay crisp.
DOF_FS = """#version 330
in vec2 fragTexCoord;
in vec4 fragColor;
uniform sampler2D texture0;
uniform vec2 px;
uniform float strength;
uniform float bar;
out vec4 finalColor;
void main() {
    vec2 uv = fragTexCoord;
    float d = abs(uv.y - 0.5) * 2.0;                                  // 0 in the middle, 1 at the top / bottom edge
    float r = strength * 14.0 * smoothstep(0.18, 1.0, d);             // blur radius in pixels
    vec3 c = texture(texture0, uv).rgb;
    if (r > 0.4 && abs(uv.y - 0.5) < 0.5 - bar) {
        vec3 acc = c;
        float wsum = 1.0;
        for (int i = 1; i <= 24; i++) {                               // golden-angle disc
            float a = float(i) * 2.39996;
            vec2 o = vec2(cos(a), sin(a)) * sqrt(float(i) / 24.0) * r * px;
            vec2 u2 = vec2(uv.x + o.x, clamp(uv.y + o.y, bar + 0.002, 1.0 - bar - 0.002));
            acc += texture(texture0, u2).rgb;
            wsum += 1.0;
        }
        c = acc / wsum;
    }
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    c = mix(vec3(l), c, 1.0 + 0.35 * strength);                        // saturation
    c = (c - 0.5) * (1.0 + 0.12 * strength) + 0.5;                     // contrast
    finalColor = vec4(c, 1.0);
}
"""


_orig_w, _orig_h, _orig_w2s = rl.get_screen_width, rl.get_screen_height, rl.get_world_to_screen
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


class Present:
    def __init__(self):
        self.rt = None
        self.sh = None
        self.loc = 0
        self.dof = 0.0                 # tilt-shift strength 0..1 (demo mode); 0 = off
        self.dof_bar = 0.0
        self.dsh = None
        self.dest = (0.0, 0.0, 1.0, 1.0)

    def _shader(self):
        if self.sh is None:
            vs = "#version 330\nin vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; uniform mat4 mvp; out vec2 fragTexCoord; out vec4 fragColor;\nvoid main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; gl_Position = mvp * vec4(vertexPosition, 1.0); }"
            self.sh = rl.load_shader_from_memory(vs, FS)
            self.loc = rl.get_shader_location(self.sh, "px")
        return self.sh

    def _dof_shader(self):
        if self.dsh is None:
            vs = "#version 330\nin vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; uniform mat4 mvp; out vec2 fragTexCoord; out vec4 fragColor;\nvoid main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; gl_Position = mvp * vec4(vertexPosition, 1.0); }"
            self.dsh = rl.load_shader_from_memory(vs, DOF_FS)
            self.dloc = tuple(rl.get_shader_location(self.dsh, n) for n in ("px", "strength", "bar"))
        return self.dsh

    def activate(self, w, h):
        """Loop start: choose the buffer size, map the mouse (call once per frame, before reading input)."""
        global vw, vh
        if self.rt is None or (vw, vh) != (w, h) and (self.rt.texture.width, self.rt.texture.height) != (w, h):
            if self.rt is not None:
                rl.unload_render_texture(self.rt)
            self.rt = rl.load_render_texture(w, h)
        vw, vh = w, h
        ww, wh = _orig_w(), _orig_h()
        s = min(ww / w, wh / h)
        dw, dh = w * s, h * s
        ox, oy = (ww - dw) / 2, (wh - dh) / 2
        self.dest = (ox, oy, dw, dh)
        rl.set_mouse_scale(w / dw, h / dh)
        rl.set_mouse_offset(-int(ox), -int(oy))

    def begin(self):
        rl.begin_texture_mode(self.rt)

    def end(self, nearest, fxaa):
        """Close the buffer and draw it onto the window (call before end_drawing)."""
        rl.end_texture_mode()
        if vw <= 0 or vh <= 0:   # window minimised: nothing to draw
            return
        rl.set_texture_filter(self.rt.texture, rl.TEXTURE_FILTER_POINT if nearest else rl.TEXTURE_FILTER_BILINEAR)
        rl.clear_background(rl.BLACK)
        src = rl.Rectangle(0, 0, vw, -vh)
        dst = rl.Rectangle(*self.dest)
        if self.dof > 0.0:
            sh = self._dof_shader()
            rl.set_shader_value(sh, self.dloc[0], rl.ffi.new("float[2]", [1.0 / vw, 1.0 / vh]), rl.SHADER_UNIFORM_VEC2)
            rl.set_shader_value(sh, self.dloc[1], rl.ffi.new("float *", self.dof), rl.SHADER_UNIFORM_FLOAT)
            rl.set_shader_value(sh, self.dloc[2], rl.ffi.new("float *", self.dof_bar), rl.SHADER_UNIFORM_FLOAT)
            rl.begin_shader_mode(sh)
            rl.draw_texture_pro(self.rt.texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
            rl.end_shader_mode()
            return
        if fxaa:
            sh = self._shader()
            rl.set_shader_value(sh, self.loc, rl.ffi.new("float[2]", [1.0 / vw, 1.0 / vh]), rl.SHADER_UNIFORM_VEC2)
            rl.begin_shader_mode(sh)
        rl.draw_texture_pro(self.rt.texture, src, dst, rl.Vector2(0, 0), 0.0, rl.WHITE)
        if fxaa:
            rl.end_shader_mode()
