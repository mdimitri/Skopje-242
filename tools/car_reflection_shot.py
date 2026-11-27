"""Real-GPU close-ups and before/after comparison of vehicle sky reflections.

Run with the managed Python. Images go under output/car_reflections/.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pyray as rl
import gl3d
import vehicles
from clock import GameClock
from sunshadow import sun_at


def main():
    out = Path("output/car_reflections")
    out.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 560
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
    rl.init_window(width, height, "Vehicle reflection close-up")
    cam = rl.Camera3D(rl.Vector3(5.0, 2.7, 5.2), rl.Vector3(0, 0.85, 0),
                      rl.Vector3(0, 1, 0), 29, rl.CAMERA_PERSPECTIVE)
    gl3d.gloss_frame(cam.position, 12, 0, sun_at(12)[0], True, 1.0)
    shader = gl3d._gloss_shader()
    assert shader.id != rl.rl_get_shader_id_default(), "car shader failed to compile"
    old_fs = gl3d.CAR_FS.replace("vec3 env = reflectedSky(R);",
        "vec3 env = R.y > 0.0 ? mix(skyH, skyZ, sqrt(R.y)) : mix(skyH * 0.7, grnd, clamp(-R.y * 4.0, 0.0, 1.0));")
    old_fs = old_fs.replace("k * (0.26 + 0.65 * fr)", "k * (0.10 + 0.65 * fr)")
    old = rl.load_shader_from_memory(gl3d.CAR_VS, old_fs)
    assert old.id != rl.rl_get_shader_id_default(), "comparison shader failed to compile"
    old_loc = {n: rl.get_shader_location(old, n) for n in gl3d._gloss["loc"]}
    model = gl3d.car_model(vehicles.IDS.index("BMW E36 Bavarka"), 1)
    rt = rl.load_render_texture(width, height)
    sheet = Image.new("RGB", (width * 2, height * 3))
    clock = GameClock()
    frames = []
    try:
        for row, (label, hour) in enumerate((("Day", 12), ("Dusk", 18.5), ("Night", 23))):
            clock.hour = hour
            dark = clock.dark
            pair = []
            for col, (sh, loc) in enumerate(((old, old_loc), (shader, gl3d._gloss["loc"]))):
                gl3d._gloss["sh"], gl3d._gloss["loc"] = sh, loc
                gl3d.gloss_frame(cam.position, hour, dark, sun_at(hour)[0], True, 1.0)
                model.materials[0].shader = sh
                rl.begin_texture_mode(rt)
                bg = gl3d._mix((135, 159, 185), (12, 18, 32), dark)
                rl.clear_background(rl.Color(*(int(x) for x in bg), 255))
                rl.begin_mode_3d(cam)
                rl.rl_disable_backface_culling()
                ground = gl3d._mix((90, 94, 100), (18, 21, 29), dark)
                rl.draw_plane(rl.Vector3(0, -0.02, 0), rl.Vector2(200, 200), rl.Color(*(int(x) for x in ground), 255))
                tint = gl3d._mix((255, 255, 255), (65, 77, 110), dark)
                rl.draw_model(model, rl.Vector3(0, 0, 0), 1, rl.Color(*(int(x) for x in tint), 255))
                rl.end_mode_3d()
                rl.end_texture_mode()
                image = rl.load_image_from_texture(rt.texture)
                rl.image_flip_vertical(image)
                path = out / f"{label.lower()}_{'before' if col == 0 else 'after'}.png"
                rl.export_image(image, str(path))
                rl.unload_image(image)
                frame = Image.open(path).convert("RGB")
                pair.append(np.asarray(frame).astype(float))
                ImageDraw.Draw(frame).text((24, 20), f"{label} | {'Before' if col == 0 else 'Sky + cloud reflections'}", fill="white", stroke_width=1, stroke_fill="black")
                sheet.paste(frame, (col * width, row * height))
            delta = np.abs(pair[1] - pair[0]).mean()
            assert delta > 0.1, f"{label}: reflections did not change"
            frames.append(pair[1])
            print(f"{label}: reflection pixel difference {delta:.3f}")
        assert frames[2].mean() < frames[0].mean() * 0.5, "night preview is too bright"
        sheet.save(out / "comparison.png")
        print(f"PASS: GPU shader and day/dusk/night close-ups: {out.resolve()}")
    finally:
        gl3d.free_model(model)
        rl.unload_shader(old)
        rl.unload_render_texture(rt)
        rl.close_window()


if __name__ == "__main__":
    main()
