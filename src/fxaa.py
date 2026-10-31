"""FXAA post-process: the frame is drawn into a render texture and resolved to the screen through an edge-smoothing shader."""
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


class Fxaa:
    def __init__(self):
        self.rt = None
        self.size = (0, 0)
        self.sh = None

    def _shader(self):
        if self.sh is None:
            vs = "#version 330\nin vec3 vertexPosition; in vec2 vertexTexCoord; in vec4 vertexColor; uniform mat4 mvp; out vec2 fragTexCoord; out vec4 fragColor;\nvoid main(){ fragTexCoord = vertexTexCoord; fragColor = vertexColor; gl_Position = mvp * vec4(vertexPosition, 1.0); }"
            self.sh = rl.load_shader_from_memory(vs, FS)
            self.loc = rl.get_shader_location(self.sh, "px")
        return self.sh

    def begin(self, w, h):
        """Start drawing into the offscreen target (call right after begin_drawing)."""
        if self.rt is None or self.size != (w, h):
            if self.rt is not None:
                rl.unload_render_texture(self.rt)
            self.rt = rl.load_render_texture(w, h)
            rl.set_texture_filter(self.rt.texture, rl.TEXTURE_FILTER_BILINEAR)
            self.size = (w, h)
        rl.begin_texture_mode(self.rt)

    def end(self):
        """Close the offscreen target and draw it, smoothed, onto the screen."""
        rl.end_texture_mode()
        w, h = self.size
        sh = self._shader()
        rl.set_shader_value(sh, self.loc, rl.ffi.new("float[2]", [1.0 / w, 1.0 / h]), rl.SHADER_UNIFORM_VEC2)
        rl.begin_shader_mode(sh)
        rl.draw_texture_rec(self.rt.texture, rl.Rectangle(0, 0, w, -h), rl.Vector2(0, 0), rl.WHITE)
        rl.end_shader_mode()
