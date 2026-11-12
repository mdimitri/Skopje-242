"""Dev tool: close-up sheet of chosen vehicle models, each from 3/4-front, side and 3/4-rear (orthographic).
python tools/car_shot.py out.png "Zastava Yugo" "Golf Dvojka" ...   (names from vehicles.py, or 'all')"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pyray as rl  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import gl3d  # noqa: E402
import vehicles  # noqa: E402

out = sys.argv[1]
names = sys.argv[2:]
ids = list(range(vehicles.N)) if names == ["all"] else [vehicles.IDS.index(n) for n in names]
PAGE = int(os.environ.get("PAGE", "0"))   # PAGE=n: rows per output file (out_1.png, ...)
CW, CH = 440, 200
rl.init_window(CW, CH, "cars")
rl.set_target_fps(60)
rl.rl_disable_backface_culling()
V3 = rl.Vector3
YAWS = tuple(int(a) for a in os.environ.get("YAWS", "35,0,215").split(","))
NV = len(YAWS)
sheets = []
for r, k in enumerate(ids):
    if PAGE and r % PAGE == 0:
        sheets.append(Image.new("RGB", (CW * NV, CH * min(PAGE, len(ids) - r)), (150, 152, 156)))
    elif not PAGE and r == 0:
        sheets.append(Image.new("RGB", (CW * NV, CH * len(ids)), (150, 152, 156)))
    sheet, r0 = sheets[-1], (r % PAGE if PAGE else r)
    m = gl3d.car_model(k, [0, 2, 1, 3, 4][k % 5] if vehicles.FIXED[k] is None else 0)
    L = vehicles.DIMS[k][0]
    for c, yaw in enumerate(YAWS):
        a = math.radians(yaw)
        cam = rl.Camera3D(V3(math.sin(a) * 30, 30 * (0.45 if c != 1 else 0.02), math.cos(a) * 30), V3(0, 0.9, 0), V3(0, 1, 0),
                          max(L * 0.62, 3.0) / float(os.environ.get("ZOOM", "1")), rl.CAMERA_ORTHOGRAPHIC)
        for _ in range(2):
            rl.begin_drawing()
            rl.clear_background(rl.Color(150, 152, 156, 255))
            rl.begin_mode_3d(cam)
            rl.draw_model_ex(m, V3(0, 0, 0), V3(0, 1, 0), 0.0, V3(1, 1, 1), rl.WHITE)
            rl.end_mode_3d()
            rl.end_drawing()
        rl.export_image(rl.load_image_from_screen(), "/tmp/_cs.png")
        sheet.paste(Image.open("/tmp/_cs.png").convert("RGB"), (c * CW, r0 * CH))
    ImageDraw.Draw(sheet).text((8, r0 * CH + 6), vehicles.IDS[k], fill=(0, 0, 0))
rl.close_window()
for i, sh in enumerate(sheets):
    sh.save(out if len(sheets) == 1 else out.replace(".png", "_%d.png" % i))
