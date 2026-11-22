"""Face windows headless: shot_faces.py <out_prefix>  -> <prefix>_idle.png, <prefix>_talk.png and a frame-cost report (CPU-side ms/frame of faces.draw)."""
import math, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.init_window(1280, 720, "t")
import font; font.load()
import faces, characters

class W:
    def ground_y(self, x, y): return 0.0
class S:
    w = W()
    mp_view = None
sim = S()
cam = rl.Camera3D(rl.Vector3(0, 60, 40), rl.Vector3(0, 0, 0), rl.Vector3(0, 1, 0), 45.0, rl.CAMERA_PERSPECTIVE)
heroes = [int(a) for a in (os.environ.get("HEROES") or "10,1,7,13").split(",")]
cols = [(230, 60, 60), (60, 140, 235), (80, 200, 90), (240, 200, 60)]
def state(t, talk_ids):
    pl = []
    for k in range(1, 4):
        pl.append({"pid": k, "name": "Играч%d" % k, "color": cols[k], "x": (-300, 200, 40)[k - 1], "y": (50, -100, 300)[k - 1], "h": 0, "hp": 100,
                   "foot": True, "talk": k in talk_ids, "lik": heroes[k], "lvl": 0.25 + 0.25 * math.sin(t * 17) ** 2})
    return {"players": pl, "me": {"pid": -1, "name": "Јас", "color": cols[0], "lik": heroes[0], "talk": 0 in talk_ids, "lvl": 0.3}}
cfg = {"faces_on": True, "faces_size": int(os.environ.get("SIZE", 1))}
def run(frames, talk, shot=None, measure=False):
    cost = 0.0
    for i in range(frames):
        t = i / 60
        sim.mp_view = state(t, talk)
        rl.begin_drawing(); rl.clear_background(rl.Color(60, 70, 60, 255))
        a = time.perf_counter(); faces.draw(sim, cam, 1280, 720, cfg, 1 / 60); cost += time.perf_counter() - a
        rl.end_drawing()
        if shot and i == frames - 1:
            rl.take_screenshot(shot)
    return cost / frames * 1000
run(2, set())
print("first-frame bake ok; idle ms/frame (CPU side):", round(run(300, set()), 3))
rl.set_target_fps(0)
run(100, set(), sys.argv[1] + "_idle.png")
print("talking ms/frame (CPU side):", round(run(300, {0, 1, 2, 3}, sys.argv[1] + "_talk.png"), 3))
cfg["faces_on"] = False
print("off ms/frame:", round(run(300, set()), 4))
