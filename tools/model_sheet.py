"""Dev tool: render contact sheets of every car and road-user model.
python tools/model_sheet.py cars.png peds.png
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pyray as rl  # noqa: E402

import gl3d  # noqa: E402
import vehicles  # noqa: E402

out_c = sys.argv[1] if len(sys.argv) > 1 else "cars.png"
out_p = sys.argv[2] if len(sys.argv) > 2 else "peds.png"
rl.set_config_flags(rl.FLAG_MSAA_4X_HINT)
rl.init_window(1800, 1000, "sheet")
rl.set_target_fps(60)
rl.rl_disable_backface_culling()
V3 = rl.Vector3


def shot(path, draw, cam):
    for _ in range(3):
        rl.begin_drawing()
        rl.clear_background(rl.Color(120, 120, 124, 255))
        rl.begin_mode_3d(cam)
        draw()
        rl.end_mode_3d()
        rl.end_drawing()
    rl.export_image(rl.load_image_from_screen(), path)


def cars():
    cols = 10
    for k in range(vehicles.N):
        m = gl3d.car_model(k, 13 if k % 3 == 0 else k)
        x = (k % cols) * 8.5 - 38
        z = (k // cols) * 6.5 - 14
        rl.draw_model_ex(m, V3(x, 0, z), V3(0, 1, 0), 20.0, V3(1, 1, 1), rl.WHITE)


def peds():
    cols = 10
    for a in range(vehicles.PED_COUNT):
        for fr in (0, 1):
            m = gl3d.ped_model(a, a % 3, fr, a % 4)
            x = (a % cols) * 4.2 - 19
            z = (a // cols) * 4.6 - 8 + fr * 1.7
            rl.draw_model_ex(m, V3(x, 0, z), V3(0, 1, 0), 90.0, V3(1, 1, 1), rl.WHITE)


shot(out_c, cars, rl.Camera3D(V3(0, 52, 28), V3(0, 0, 2), V3(0, 1, 0), 36.0, rl.CAMERA_PERSPECTIVE))
shot(out_p, peds, rl.Camera3D(V3(0, 30, 16), V3(0, 0, 0), V3(0, 1, 0), 36.0, rl.CAMERA_PERSPECTIVE))
rl.close_window()
