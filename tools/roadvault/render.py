import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import pyray as rl  # noqa: E402
import road_shot as rs  # noqa: E402


class Renderer:
    def __init__(self, size=(1600, 1000)):
        rl.set_trace_log_level(rl.LOG_WARNING)
        rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN | rl.FLAG_MSAA_4X_HINT)
        rl.init_window(size[0], size[1], "vault")
        self.size = size
        self.rt = rl.load_render_texture(*size)

    def shot(self, mesh, out_png, eye, tgt, fov=40.0):
        pos = np.array(mesh.P, np.float32)
        col = np.array(mesh.C, np.uint8)
        models = rs.model(pos, col)
        cam = rl.Camera3D(eye, tgt, (0, 1, 0), fov, rl.CAMERA_PERSPECTIVE)
        rl.rl_set_clip_planes(1.5, 3000.0)
        rl.begin_texture_mode(self.rt)
        rl.clear_background((190, 212, 236, 255))
        rl.begin_mode_3d(cam)
        rl.rl_disable_backface_culling()
        for mo in models:
            rl.draw_model(mo, (0, 0, 0), 1.0, rl.WHITE)
        rl.end_mode_3d()
        rl.end_texture_mode()
        img = rl.load_image_from_texture(self.rt.texture)
        rl.image_flip_vertical(img)
        rl.export_image(img, out_png)
        rl.unload_image(img)
        for mo in models:
            rl.unload_model(mo)

    def close(self):
        rl.close_window()


def aerial(extent=100.0, az=205.0, el=42.0, dist=190.0):
    a, e = math.radians(az), math.radians(el)
    return (math.sin(a) * math.cos(e) * dist, math.sin(e) * dist, -math.cos(a) * math.cos(e) * dist), (0, 0, 0)
