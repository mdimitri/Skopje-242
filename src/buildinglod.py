"""Building-owned facade captures shared by prism and depth-correct sprite LODs.

Captures run outside the main 3D pass, one building at a time. Atlas groups are
bounded and contain only geometry identified by the world's per-building spans.
"""
import math
import time
from collections import OrderedDict

import numpy as np
import pyray as rl

import gl3d
from lightmap import WIN_VS, WIN_FS, SKIP_MATS, BUILDING_WIN_R

SIZE = 64
GROUP = 16
MAX_GROUPS = 192
SPRITE_DISTANCE = 1200.0
CAPTURE_SCALE = 4.0 / 3.0                    # eight transparent border pixels protect each face's mip levels
NAMES = ("A", "B", "roof", "white", "panel", "house", "graf", "brick", "conc", "concg", "cream", "mix") + gl3d.SURF_NAMES + ("glaz", "glaz")
# Camera forward, screen right and screen up for the four walls and roof.
VIEWS = (((-1, 0, 0), (0, 0, -1), (0, 1, 0)),
         ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
         ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
         ((0, 0, 1), (-1, 0, 0), (0, 1, 0)),
         ((0, -1, 0), (1, 0, 0), (0, 0, -1)))

VS = """#version 330
in vec3 vertexPosition; in vec2 vertexTexCoord;
uniform mat4 mvp;
uniform vec3 eye, right, up;
uniform vec3 low[16], high[16];
uniform int sprite;
out vec3 wp;
flat out int building;
void main(){
  building = int(vertexTexCoord.x + 0.5);
  wp = vertexPosition;
  if(sprite == 1){
    vec3 c = (low[building] + high[building]) * 0.5;
    float r = length(high[building] - low[building]) * 0.5;
    // A sphere's tangent plane needs a slightly larger card in perspective.
    float d = length(c - eye);
    r *= d / sqrt(max(d*d-r*r, 0.01));
    wp = c + r * (right * vertexPosition.x + up * vertexPosition.y);
  }
  gl_Position = mvp * vec4(wp, 1.0);
}"""

FS = """#version 330
in vec3 wp; flat in int building;
uniform mat4 mvp;
uniform sampler2D texture0, texture1;
uniform vec3 eye, low[16], high[16];
uniform float darkness;
uniform int glowPass;
uniform vec3 lightCenter;
out vec4 finalColor;
void main(){
  vec3 lo = low[building], hi = high[building];
  vec3 ray = normalize(wp-eye);
  vec3 inv = 1.0 / mix(vec3(0.000001), ray, greaterThan(abs(ray),vec3(0.000001)));
  vec3 a = (lo-eye)*inv, b = (hi-eye)*inv;
  vec3 entry = min(a,b), leave = max(a,b);
  float t = max(max(entry.x, entry.y), entry.z);
  if(t < 0.0 || t > min(min(leave.x, leave.y), leave.z)) discard;
  vec3 p = eye + ray*t, c = (lo+hi)*0.5;
  float scale = max(max(hi.x-lo.x, hi.y-lo.y), hi.z-lo.z) * (4.0/3.0);
  vec2 uv; int face;
  if(entry.y >= entry.x && entry.y >= entry.z){
    if(ray.y > 0.0) discard;
    face=4; uv=vec2(p.x-c.x, c.z-p.z);
  }else if(entry.x >= entry.z){
    face=ray.x < 0.0 ? 1 : 0;
    uv=vec2(ray.x < 0.0 ? p.z-c.z : c.z-p.z, p.y-c.y);
  }else{
    face=ray.z < 0.0 ? 3 : 2;
    uv=vec2(ray.z < 0.0 ? c.x-p.x : p.x-c.x, p.y-c.y);
  }
  uv=clamp(uv/scale+0.5, vec2(0.5/64.0), vec2(63.5/64.0));
  vec2 atlasSize=vec2(textureSize(texture0,0));
  float rows=atlasSize.y/64.0;
  uv=vec2((float(face)+uv.x)/5.0, 1.0-(float(building)+1.0-uv.y)/rows);
  float footprint=max(length(dFdx(uv)*atlasSize),length(dFdy(uv)*atlasSize));
  float level=clamp(log2(max(footprint,1.0)),0.0,3.0);
  vec4 day=textureLod(texture0,uv,level);
  if(day.a < 0.15) discard;
  if(glowPass == 1){
    vec3 glow=textureLod(texture1,uv,level).rgb*1.1*min(1.0,darkness*1.4)*0.95;
    glow *= 1.0-smoothstep(lightCenter.z*0.75,lightCenter.z,length(p.xz-lightCenter.xy));
    finalColor=vec4(glow,1.0);
  }else{
    finalColor=vec4(day.rgb,1.0);
  }
  vec4 clip=mvp*vec4(p,1.0);
  gl_FragDepth=clip.z/clip.w*0.5+0.5;
}"""


def prism_vertices(lo, hi):
    x, y, z = lo
    X, Y, Z = hi
    faces = (((x,y,z),(x,y,Z),(x,Y,Z),(x,Y,z)),
             ((X,y,Z),(X,y,z),(X,Y,z),(X,Y,Z)),
             ((X,y,z),(x,y,z),(x,Y,z),(X,Y,z)),
             ((x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)),
             ((x,Y,z),(x,Y,Z),(X,Y,Z),(X,Y,z)))
    return [q[i] for q in faces for i in (0,1,2,0,2,3)]


class Captures:
    def __init__(self, world, textures):
        self.w, self.textures = world, textures
        self.groups = OrderedDict()
        self.next_capture = 0.0
        self.view_uniforms = None
        self.tile = rl.load_render_texture(SIZE, SIZE)
        self.shader = rl.load_shader_from_memory(VS, FS)
        # Unlike the additive runtime pass, black non-window fragments must write
        # depth here so roofs and frames occlude windows on the opposite wall.
        win_fs = WIN_FS.replace("discard;", "{ finalColor=vec4(0.0,0.0,0.0,1.0); return; }")
        self.windows = rl.load_shader_from_memory(WIN_VS, win_fs)
        if not rl.is_shader_valid(self.shader) or not rl.is_shader_valid(self.windows):
            raise RuntimeError("building LOD shaders did not compile")
        self.loc = {n: rl.get_shader_location(self.shader, n) for n in
                    ("eye", "right", "up", "low", "high", "sprite", "darkness", "texture1", "glowPass", "lightCenter")}

    def _new(self, records):
        atlases = [rl.load_render_texture(SIZE*5, SIZE*len(records)) for _ in range(2)]
        for rt in atlases:
            rl.begin_texture_mode(rt)
            rl.clear_background(rl.BLANK)
            rl.end_texture_mode()
            rl.set_texture_filter(rt.texture, rl.TEXTURE_FILTER_BILINEAR)
            rl.set_texture_wrap(rt.texture, rl.TEXTURE_WRAP_CLAMP)
        bounds = tuple(rl.ffi.new("float[]", [value for record in records for value in record[index]])
                       for index in (0, 1))
        center = tuple((a + b) * 0.5 for a, b in zip(records[0][0], records[0][1]))
        return {"records": records, "atlases": atlases, "done": 0, "models": [],
                "bounds": bounds, "center": center}

    def _capture(self, key, group):
        row = group["done"]
        lo, hi, spans = group["records"][row]
        center = (np.asarray(lo)+hi)*0.5
        scale = max(np.asarray(hi)-lo)*CAPTURE_SCALE
        models = []
        try:
            for mat, start, count in spans:
                if mat == 6 and "graf" not in self.textures:
                    continue
                off, n = self.w.chunks[key]["m"][mat]
                arrays = self.w.mesh_arrays(off, n)
                m = gl3d.make_model(*(a[start:start+count] for a in arrays))
                if m is not None:
                    gl3d.set_texture(m, self.textures.get(NAMES[mat]) or self.textures["A"])
                    models.append((mat, m))
            rl.rl_set_clip_planes(0.1, max(100.0,float(scale)*5.0))
            for face, (forward, _, up) in enumerate(VIEWS):
                cam = rl.Camera3D(rl.Vector3(*(center-np.asarray(forward)*scale*2)),
                                  rl.Vector3(*center), rl.Vector3(*up), float(scale), rl.CAMERA_ORTHOGRAPHIC)
                for night, atlas in enumerate(group["atlases"]):
                    rl.begin_texture_mode(self.tile)
                    rl.clear_background(rl.BLANK)
                    rl.begin_mode_3d(cam)
                    rl.rl_disable_backface_culling()
                    if night:
                        rl.set_shader_value(self.windows, rl.get_shader_location(self.windows, "wc"),
                                            rl.ffi.new("float[3]", [center[0], center[2], 1e7]), rl.SHADER_UNIFORM_VEC3)
                        rl.set_shader_value(self.windows, rl.get_shader_location(self.windows, "wglow"),
                                            rl.ffi.new("float *", 1.0), rl.SHADER_UNIFORM_FLOAT)
                    for mat, m in models:
                        if night:
                            # Non-window materials still write depth and occlude windows behind them.
                            sh = m.materials[0].shader
                            saved = rl.ffi.new("Shader *", sh)
                            m.materials[0].shader = self.windows
                            strength = 0.0 if mat in SKIP_MATS else 1.0 / 1.1  # store emission without clipping its peak
                            rl.set_shader_value(self.windows, rl.get_shader_location(self.windows, "wglow"),
                                                rl.ffi.new("float *", strength), rl.SHADER_UNIFORM_FLOAT)
                            rl.draw_model(m, rl.Vector3(0,0,0), 1.0, rl.WHITE)
                            m.materials[0].shader = saved[0]
                        else:
                            rl.draw_model(m, rl.Vector3(0,0,0), 1.0, rl.WHITE)
                    rl.end_mode_3d()
                    rl.end_texture_mode()
                    rl.begin_texture_mode(atlas)
                    rl.draw_texture_rec(self.tile.texture, rl.Rectangle(0,0,SIZE,-SIZE),
                                        rl.Vector2(face*SIZE,row*SIZE), rl.WHITE)
                    rl.end_texture_mode()
        finally:
            for _, m in models:
                gl3d.free_model(m)
        group["done"] += 1
        if group["done"] == len(group["records"]):
            for rt in group["atlases"]:
                rl.gen_texture_mipmaps(rt.texture)
                rl.set_texture_filter(rt.texture,rl.TEXTURE_FILTER_TRILINEAR)
            for sprite in (False, True):
                pos, uv = [], []
                for i, (low, high, _) in enumerate(group["records"]):
                    p = [(x,y,0) for x,y in ((-1,-1),(1,-1),(1,1),(-1,-1),(1,1),(-1,1))] if sprite else prism_vertices(low,high)
                    pos.extend(p)
                    uv.extend([(i,0)]*len(p))
                m = gl3d.make_model(pos, uv, np.full((len(pos),4),255,np.uint8))
                m.materials[0].shader = self.shader
                gl3d.set_texture(m, group["atlases"][0].texture)
                m.materials[0].maps[1].texture = group["atlases"][1].texture
                group["models"].append(m)

    def prepare(self, keys, budget_ms=3.0):
        start_time = time.perf_counter()
        if start_time < self.next_capture:
            return
        deadline = start_time + budget_ms / 1000
        jobs = []
        for key in keys:
            records = self.w.chunks.get(key, {}).get("lod", ())
            for start in range(0,len(records),GROUP):
                jobs.append(((key,start),records[start:start+GROUP]))
        jobs = jobs[:MAX_GROUPS]
        wanted = {k for k,_ in jobs}
        for cache_key, records in jobs:
            if time.perf_counter() >= deadline:
                break
            g = self.groups.get(cache_key)
            if g is None:
                if len(self.groups) >= MAX_GROUPS:
                    victim = next((k for k in self.groups if k not in wanted),None)
                    if victim is None:
                        continue
                    self._free(self.groups.pop(victim))
                g = self.groups[cache_key] = self._new(records)
            self.groups.move_to_end(cache_key)
            if not g["models"]:
                self._capture(cache_key[0],g)
                # A capture is indivisible. Spread expensive captures out over
                # later frames so submitting their GPU work doesn't starve play.
                now = time.perf_counter()
                self.next_capture = now + min(0.25, max(0.012, 4 * (now - start_time)))
                break

    def _set_view(self, eye, target, camera_up, dark, glow):
        view = (eye, target, camera_up, dark, glow)
        if view == self.view_uniforms:
            return
        self.view_uniforms = view
        forward = np.asarray(target, np.float32) - np.asarray(eye, np.float32)
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, camera_up)
        right /= np.linalg.norm(right)
        up = np.cross(right,forward)
        for name, v in (("eye",eye),("right",right),("up",up)):
            rl.set_shader_value(self.shader,self.loc[name],rl.ffi.new("float[3]",list(v)),rl.SHADER_UNIFORM_VEC3)
        rl.set_shader_value(self.shader,self.loc["darkness"],rl.ffi.new("float *",dark),rl.SHADER_UNIFORM_FLOAT)
        rl.set_shader_value(self.shader,self.loc["glowPass"],rl.ffi.new("int *",int(glow)),rl.SHADER_UNIFORM_INT)
        rl.set_shader_value(self.shader,self.loc["lightCenter"],
                            rl.ffi.new("float[3]",[target[0],target[2],BUILDING_WIN_R]),rl.SHADER_UNIFORM_VEC3)

    def draw(self, key, cam, dark, glow=False, sprite_distance=SPRITE_DISTANCE):
        records = self.w.chunks.get(key, {}).get("lod")
        if not records:
            return False
        groups = [self.groups.get((key,s)) for s in range(0,len(records),GROUP)]
        if any(g is None or not g["models"] for g in groups):
            return False
        eye = (cam.position.x, cam.position.y, cam.position.z)
        self._set_view(eye, (cam.target.x, cam.target.y, cam.target.z), (cam.up.x, cam.up.y, cam.up.z), dark, glow)
        rl.rl_enable_backface_culling()
        for g in groups:
            for name, data in zip(("low", "high"), g["bounds"]):
                rl.set_shader_value_v(self.shader,self.loc[name],data,rl.SHADER_UNIFORM_VEC3,len(g["records"]))
            sprite = int(math.dist(g["center"], eye) >= sprite_distance)
            rl.set_shader_value(self.shader,self.loc["sprite"],rl.ffi.new("int *",sprite),rl.SHADER_UNIFORM_INT)
            if glow:
                rl.set_shader_value_texture(self.shader,self.loc["texture1"],g["atlases"][1].texture)
            rl.draw_model(g["models"][sprite],rl.Vector3(0,0,0),1.0,rl.WHITE)
        rl.rl_disable_backface_culling()
        return True

    def _free(self, group):
        for m in group["models"]:
            gl3d.free_model(m)
        for rt in group["atlases"]:
            rl.unload_render_texture(rt)

    def close(self):
        for g in self.groups.values():
            self._free(g)
        self.groups.clear()
        rl.unload_render_texture(self.tile)
        rl.unload_shader(self.shader)
        rl.unload_shader(self.windows)
