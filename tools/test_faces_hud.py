"""Pixel test of the face windows through the REAL frame structure (present.Present world buffer + HUD layer, faces pre/blit phases).
Fails when a face box is empty or its border is not the player's colour.  Run: xvfb-run python3 tools/test_faces_hud.py [out.png]"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.init_window(1280, 720, "t")
import font; font.load()
import faces, present
class W:
    def ground_y(self, x, y): return 0.0
class S:
    w = W(); mode = "foot"; mp_view = None
sim = S()
cam = rl.Camera3D(rl.Vector3(0, 60, 40), rl.Vector3(0, 0, 0), rl.Vector3(0, 1, 0), 45.0, rl.CAMERA_PERSPECTIVE)
cols = [(230, 60, 60), (60, 140, 235), (80, 200, 90), (240, 200, 60)]
base = {"foot": True, "hp": 100, "vx": 0.0, "vy": 0.0, "h": 0.0, "atk": 0, "money": 100, "dead": False, "talk": False, "lvl": 0.0, "x": 0, "y": 50}
def view(n):
    rows = [dict(base, pid=-1 if j == 0 else j, name="P%d" % j, color=cols[j], lik=(3 + 5 * j) % 20, talk=j > 0, lvl=.5) for j in range(n)]
    sim.mp_view = {"me": rows[0], "players": rows[1:]}
cfg = {"faces_on": True, "faces_size": 1, "faces_mesh": True}
pr = present.Present(); pr.activate(1280, 720)
bad = 0
def frame(dof, n, check):
    global bad
    view(n)
    faces.draw(sim, cam, 1280, 720, cfg, 1 / 60, "pre")
    rl.begin_drawing(); pr.begin(dof)
    rl.clear_background(rl.Color(60, 70, 60, 255))
    if dof: pr.ui_layer()
    faces.draw(sim, cam, 1280, 720, cfg, 1 / 60, "blit")
    pr.ui_layer()                         # as main: the HUD layer opens after the faces when dof is off
    rl.draw_circle(640, 360, 20, rl.RED)  # something drawn after the faces must still show
    pr.end(False, False); rl.end_drawing()
    rl.rl_draw_render_batch_active()
    if not check: return
    img = rl.load_image_from_screen(); W_ = img.width
    px = lambda x, y: (lambda c: (c.r, c.g, c.b))(rl.get_image_color(img, x, y))
    S_ = faces.SIZES[1]; y = 12
    for j in range(n):
        x = 14
        e = [px(x - 1 + dx, y + S_ // 2) for dx in (0, 1)]
        ok_b = any(max(abs(c[i] - cols[j][i]) for i in range(3)) < 40 for c in e)
        inner = {px(x + 8 + i * 7, y + 8 + k * 7) for i in range(12) for k in range(12)}
        ok_h = len(inner) > 12
        print("dof=%s n=%d box%d border=%s %s head_colours=%d %s" % (dof, n, j, e[0], "OK" if ok_b else "BAD", len(inner), "OK" if ok_h else "EMPTY"))
        bad += (not ok_b) + (not ok_h)
        y += S_ + max(12, S_ // 5) + 10
    ok_r = px(640, 360)[0] > 200 and px(640, 360)[1] < 60
    print("   marker after faces:", "OK" if ok_r else "MISSING"); bad += not ok_r
    if len(sys.argv) > 1:
        rl.export_image(img, sys.argv[1])
for dof in (False, True):
    faces._state.clear()
    for i in range(30):
        frame(dof, 3, i in (1, 5, 29))
print("RESULT", "FAIL" if bad else "PASS"); sys.exit(1 if bad else 0)
