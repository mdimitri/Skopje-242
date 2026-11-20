"""GPU atlases for the generated city and expanded material packs."""
from pathlib import Path
from weakref import WeakValueDictionary

import numpy as np
from PIL import Image
import pyray as rl

DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "textures" / "generated"
EXPANDED = DIRECTORY.with_name("expanded")
FAMILIES = ("asphalt", "paving", "vegetation", "earth", "plaster", "masonry", "roof", "metal")
EXPANDED_FAMILIES = FAMILIES + (
    "water", "bark", "leaf", "wood", "ceramic", "carpet", "cloth", "leather",
    "skin", "hair", "fur", "feather", "paint", "rubber", "plastic", "concrete", "paper",
)
TILE, GUTTER, VARIANTS = 480, 16, 8
EXPANDED_TILE, EXPANDED_GUTTER, EXPANDED_VARIANTS = 240, 8, 20
ATLAS_MAP = 4

_atlas = None
_mode = 0
_uniforms = {}
_objects = WeakValueDictionary()


def _load_atlas(mode):
    expanded = mode == 2
    families = EXPANDED_FAMILIES if expanded else FAMILIES
    tile_size, gutter, variants = (
        (EXPANDED_TILE, EXPANDED_GUTTER, EXPANDED_VARIANTS) if expanded else (TILE, GUTTER, VARIANTS))
    cell = tile_size + 2 * gutter
    channels = 4 if expanded else 3
    atlas = np.empty((len(families) * cell, variants * cell, channels), dtype=np.uint8)
    for row, family in enumerate(families):
        for col in range(variants):
            key = f"{family}_{col + 1:02}"
            path = (EXPANDED / (key + ".jpg")) if expanded else (DIRECTORY / (key + ".png"))
            with Image.open(path) as image:
                if image.size != ((384, 384) if expanded else (tile_size, tile_size)):
                    raise ValueError(f"Unexpected size for {path.name}: {image.size}")
                if expanded:
                    image = image.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
            # The baked mesh already supplies the surface color. Center the detail on neutral
            # gray and retain a little of the original hue without doubling the baked tint.
            mean = rgb.mean(axis=(0, 1))
            lum = float(mean @ np.array([0.2126, 0.7152, 0.0722]))
            detail = 0.5 + (rgb - mean) * (0.57 / max(lum, 0.19)) + 0.22 * (mean - lum)
            tile = np.clip(detail * 255.0, 0, 255).astype(np.uint8)
            if expanded:
                with Image.open(EXPANDED / (key + "_height.png")) as height:
                    if height.size != (384, 384) or height.mode != "I;16":
                        raise ValueError(f"Invalid 16-bit height map for {key}")
                    height = height.convert("F").resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                    alpha = np.rint(np.clip(np.asarray(height) / 257, 0, 255)).astype(np.uint8)
                tile = np.dstack((tile, alpha))
            atlas[row * cell:(row + 1) * cell, col * cell:(col + 1) * cell] = np.pad(
                tile, ((gutter, gutter), (gutter, gutter), (0, 0)), mode="wrap")

    height, width = atlas.shape[:2]
    pixel_format = rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8 if expanded else rl.PIXELFORMAT_UNCOMPRESSED_R8G8B8
    image = rl.Image(rl.ffi.from_buffer(atlas), width, height, 1, pixel_format)
    texture = rl.load_texture_from_image(image)
    if not texture.id:
        raise RuntimeError("Could not upload generated surface textures")
    rl.gen_texture_mipmaps(texture)
    rl.set_texture_filter(texture, rl.TEXTURE_FILTER_TRILINEAR)
    rl.set_texture_wrap(texture, rl.TEXTURE_WRAP_CLAMP)
    return texture


def register(shader):
    sampler = rl.get_shader_location(shader, "texture4")
    enabled = rl.get_shader_location(shader, "generatedSurfaces")
    if sampler >= 0 and enabled >= 0:
        rl.set_shader_value(shader, sampler, rl.ffi.new("int *", ATLAS_MAP), rl.SHADER_UNIFORM_INT)
        rl.set_shader_value(shader, enabled, rl.ffi.new("int *", _mode), rl.SHADER_UNIFORM_INT)
        _uniforms[shader.id] = shader, enabled


def select(mode):
    """Switch shared shader state. Return true when cached meshes need rebinding."""
    global _atlas, _mode
    if mode == _mode:
        return False
    try:
        atlas = _load_atlas(mode) if mode else None
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[gfx] texture pack unavailable: {exc}")
        return False
    if _atlas is not None:
        rl.unload_texture(_atlas)
    _mode, _atlas = mode, atlas
    value = rl.ffi.new("int *", mode)
    for shader, location in _uniforms.values():
        rl.set_shader_value(shader, location, value, rl.SHADER_UNIFORM_INT)
    for model in list(_objects.values()):
        bind(model)
    return True


def current_mode():
    return _mode


def bind(model):
    if model is not None and model.materials[0].shader.id in _uniforms:
        active = _mode == 2 or (_mode == 1 and id(model) not in _objects)
        model.materials[0].maps[ATLAS_MAP].texture = _atlas if active else rl.Texture()


def track(model):
    _objects[id(model)] = model
    bind(model)


def forget(model):
    _objects.pop(id(model), None)


def close():
    if _atlas is not None:
        rl.unload_texture(_atlas)


SHADER = """
uniform sampler2D texture4;
uniform int generatedSurfaces;
float surfaceVariant(float region){
  return floor(fract(sin(region * 127.1 + 43.7) * 43758.5453) * (generatedSurfaces == 2 ? 20.0 : 8.0));
}
vec4 surfaceTile(vec2 uv, vec2 dx, vec2 dy, float family, float variant){
  if (generatedSurfaces == 2){
    vec2 dimensions = vec2(5120.0, 6400.0);
    vec2 coord = (vec2(variant, family) * 256.0 + 8.0 + fract(uv) * 240.0) / dimensions;
    return textureGrad(texture4, coord, dx * 240.0 / dimensions, dy * 240.0 / dimensions);
  }
  vec2 coord = (vec2(variant, family) * 512.0 + 16.0 + fract(uv) * 480.0) / 4096.0;
  return vec4(textureGrad(texture4, coord, dx * (480.0 / 4096.0), dy * (480.0 / 4096.0)).rgb, 0.5);
}
vec4 surfaceSample(vec2 uv, vec2 world, float family, float strength){
  vec2 dx = dFdx(uv), dy = dFdy(uv);
  float footprint = max(length(dx), length(dy)) * 480.0;
  strength *= 1.0 - smoothstep(6.0, 14.0, footprint);
  if (strength <= 0.001) return vec4(0.5);
  float region = dot(world, vec2(0.007, 0.0049)) + 0.37;
  float variant = surfaceVariant(floor(region));
  vec4 tile = surfaceTile(uv, dx, dy, family, variant);
  float blend = smoothstep(0.78, 1.0, fract(region));
  if (blend > 0.0){
    float next = surfaceVariant(floor(region) + 1.0);
    tile = mix(tile, surfaceTile(uv, dx, dy, family, next), blend);
  }
  return mix(vec4(0.5), tile, strength);
}
vec4 objectSample(vec2 uv, float family, float variant){
  vec2 dx = dFdx(uv), dy = dFdy(uv);
  float k = 1.0 - smoothstep(0.013, 0.029, max(length(dx), length(dy)));
  if (k <= 0.0) return vec4(0.5);
  return mix(vec4(0.5), surfaceTile(uv, dx, dy, family, variant), k);
}
vec3 surfaceNormal(vec3 p, vec3 n, float height, float amplitude){
  vec3 dx = dFdx(p), dy = dFdy(p);
  vec3 tx = cross(dy, n), ty = cross(n, dx);
  float det = dot(dx, tx);
  vec3 gradient = sign(det) * (dFdx(height) * tx + dFdy(height) * ty);
  vec3 bumped = abs(det) * n - amplitude * gradient;
  return dot(bumped, bumped) > 0.0 ? normalize(bumped) : n;
}
float surfaceAmplitude(float family){
  // Relative travel in meters, ordered exactly as EXPANDED_FAMILIES.
  const float amplitudes[25] = float[25](
    0.023, 0.032, 0.055, 0.040, 0.007, 0.032, 0.048, 0.010, 0.020, 0.039,
    0.026, 0.013, 0.010, 0.012, 0.007, 0.005, 0.0014, 0.006, 0.006, 0.004,
    0.0017, 0.010, 0.003, 0.018, 0.005);
  return amplitudes[int(family)];
}
vec2 surfaceProjection(vec3 p, vec3 n){
  vec3 a = abs(n);
  return a.y >= max(a.x, a.z) ? p.xz : (a.x > a.z ? p.zy : p.xy);
}
"""
