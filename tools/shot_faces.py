"""Face windows headless: shot_faces.py <out.png> -> a sheet of moods rendered by the real mesh heads + frame-cost report.
Env: HEROES=1,10,13 (hero indices), SIZE=0..2, MESH=0 for the caricature fallback."""
import math, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.init_window(1280, 720, "t")
import font; font.load()
import faces, characters

class W:
    def ground_y(self, x, y): return 0.0
class S:
    w = W(); mode = "foot"; mp_view = None
sim = S()
cam = rl.Camera3D(rl.Vector3(0, 60, 40), rl.Vector3(0, 0, 0), rl.Vector3(0, 1, 0), 45.0, rl.CAMERA_PERSPECTIVE)
heroes = [int(a) for a in (os.environ.get("HEROES") or "1,10,13,17").split(",")]
cols = [(230, 60, 60), (60, 140, 235), (80, 200, 90), (240, 200, 60)]
cfg = {"faces_on": True, "faces_size": int(os.environ.get("SIZE", 2)), "faces_mesh": os.environ.get("MESH", "1") == "1"}
SC = {   # name: (per-frame function t -> dict of fields)
 "idle": lambda t: {},
 "talk": lambda t: {"talk": True, "lvl": .3 + .3 * math.sin(t * 17) ** 2},
 "shout": lambda t: {"talk": True, "lvl": .9},
 "fast": lambda t: {"foot": False, "vx": 30, "vy": 0, "h": 0},
 "crazy": lambda t: {"foot": False, "vx": 34, "vy": 0, "h": math.sin(t * 3) * 1.3},
 "brake": lambda t: {"foot": False, "vx": max(0.0, 30 - 90 * max(0, t - .5)), "vy": 0, "h": 0},
 "crash": lambda t: {"foot": False, "vx": 30 if t < .5 else 0, "vy": 0, "hp": 100 if t < .5 else 60},
 "fight": lambda t: {"atk": 1 if int(t * 4) % 2 else 0},
 "hit": lambda t: {"hp": 100 - 10 * min(t, 1.0) * 3 if t < 1 else 70},
 "cash": lambda t: {"money": int(100 + 50 * t)},
 "scared": lambda t: {"hp": 20},
 "dead": lambda t: {"hp": 0, "dead": True},
}
def rows(t, over, k):
    base = {"foot": True, "hp": 100, "vx": 0.0, "vy": 0.0, "h": 0.0, "atk": 0, "money": 100, "dead": False, "talk": False, "lvl": 0.0}
    out = []
    for j in range(2):
        d = dict(base); d.update(over(t)); d.update({"name": "P%d" % j, "color": cols[j], "lik": heroes[(k + j) % len(heroes)], "x": 100 * j, "y": 50, "pid": j if j else -1})
        out.append(d)
    return out
def run(over, frames=80, k=0, shot=False):
    cost = 0.0
    for i in range(frames):
        t = i / 60
        r = rows(t, over, k)
        sim.mp_view = {"me": r[0], "players": r[1:]}
        a = time.perf_counter(); faces.draw(sim, cam, 1280, 720, cfg, 1 / 60, "pre"); cost += time.perf_counter() - a
        rl.begin_drawing(); rl.clear_background(rl.Color(60, 70, 60, 255))
        a = time.perf_counter(); faces.draw(sim, cam, 1280, 720, cfg, 1 / 60, "blit"); cost += time.perf_counter() - a
        rl.end_drawing()
    rl.rl_draw_render_batch_active()
    img = rl.load_image_from_screen() if shot else None
    return cost / frames * 1000, img
from PIL import Image
sheet = Image.new("RGB", (len(SC) * 130, 260), (60, 70, 60))
for c, (name, over) in enumerate(SC.items()):
    faces._state.clear()
    ms, img = run(over, 80, c, True)
    im = Image.frombytes("RGBA", (img.width, img.height), bytes(rl.ffi.buffer(img.data, img.width * img.height * 4))) if hasattr(rl, "ffi") else None
    sheet.paste(im.convert("RGB").crop((8, 6, 138, 266)), (c * 130, 0))
    print("%-7s cpu ms/frame %.3f" % (name, ms))
sheet.save(sys.argv[1])
cfg["faces_on"] = False
print("off ms/frame:", round(run(SC["idle"], 200)[0], 4))
