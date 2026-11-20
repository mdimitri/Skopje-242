"""Compare the indexed terrain light overlay against its immediate-mode reference."""
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pyray as rl

import fastrl  # noqa: F401
from lightmap import GRID, LIFT, LightMap


def immediate(light, cam, dark):
    axis = np.arange(GRID + 1)
    xs = light.ox + axis * (light.span / GRID)
    zs = light.oz + axis * (light.span / GRID)
    x, z = np.meshgrid(xs, zs)
    y = light.w.th_v(x, z) + LIFT
    radius = np.maximum(np.abs(x - light.cx), np.abs(z - light.cz)) / (light.span / 2)
    a = (255 * min(1.0, dark * 1.5) * (1.0 - np.clip((radius - 0.75) / 0.25, 0.0, 1.0))).astype(int)
    u, v = (xs - light.ox) / light.span, 1.0 - (zs - light.oz) / light.span
    rl.begin_mode_3d(cam)
    rl.rl_disable_backface_culling()
    rl.rl_disable_depth_mask()
    rl.begin_blend_mode(rl.BLEND_ADDITIVE)
    rl.rl_set_texture(light.rt.texture.id)
    rl.rl_begin(rl.RL_QUADS)
    for i in range(GRID):
        for j in range(GRID):
            for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                ix, iz = i + di, j + dj
                rl.rl_color4ub(255, 255, 255, int(a[iz, ix]))
                rl.rl_tex_coord2f(float(u[ix]), float(v[iz]))
                rl.rl_vertex3f(float(xs[ix]), float(y[iz, ix]), float(zs[iz]))
    rl.rl_end()
    rl.rl_set_texture(0)
    rl.end_blend_mode()
    rl.rl_enable_depth_mask()
    rl.end_mode_3d()


def pixels(target, draw, cam, dark):
    rl.begin_texture_mode(target)
    rl.clear_background(rl.BLACK)
    draw(cam, dark)
    rl.end_texture_mode()
    image = rl.load_image_from_texture(target.texture)
    try:
        return np.frombuffer(rl.ffi.buffer(image.data, image.width * image.height * 4),
                             dtype=np.uint8).reshape(-1, 4)[:, :3].astype(np.int16)
    finally:
        rl.unload_image(image)


def main():
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
    rl.init_window(320, 240, "Terrain overlay parity")
    v = rl.Vector3
    world = SimpleNamespace(hilly=True, th_v=lambda x, z: (2.0 * np.sin(x / 9.0) * np.cos(z / 11.0)).astype(np.float32))
    light = LightMap(world, None)
    target = rl.load_render_texture(320, 240)
    try:
        cam = rl.Camera3D(v(0, 68, 60), v(0, 0, 0), v(0, 1, 0), 55, rl.CAMERA_PERSPECTIVE)
        for scale, dark in ((38, 0.41), (45, 0.62), (45, 0.51)):
            light.begin(cam, (-scale, -scale, scale, scale), False)
            light.pool(0, 0, 28, (255, 160, 90), 0.85)
            light.pool(35, 18, 25, (80, 160, 255), 1.0)
            light.render()
            before = pixels(target, lambda camera, darkness: immediate(light, camera, darkness), cam, dark)
            after = pixels(target, light.overlay, cam, dark)
            delta = np.abs(before - after)
            assert before.max() > 80 and after.max() > 80
            assert delta.mean() < 0.2 and np.mean(delta.max(axis=1) > 3) < 0.001, (
                scale, dark, delta.mean(), delta.max())
            print(f"Indexed overlay parity at bounds {scale} m, dark {dark:.2f}, mean channel delta {delta.mean():.4f}")
    finally:
        rl.unload_render_texture(target)
        light.close()
        rl.close_window()


if __name__ == "__main__":
    main()
