"""Draws the multiplayer name label + edge arrows (hud.draw_players) over a plain background headless: shot_players.py <out.png>"""
import math, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.init_window(1280, 720, "t")
import font; font.load()
import hud
class W:
    def ground_y(self, x, y): return 0.0
class S:
    w = W()
    mp_view = {"team": 900, "me_color": (230, 60, 60), "players": [
        {"pid": 1, "name": "Ана", "color": (60, 140, 235), "x": 12, "y": 4, "h": 0, "hp": 100, "foot": True},
        {"pid": 2, "name": "Кико", "color": (80, 200, 90), "x": 400, "y": -150, "h": 0, "hp": 100, "foot": False},
        {"pid": 3, "name": "Лазе", "color": (240, 200, 60), "x": -50, "y": 600, "h": 0, "hp": 100, "foot": False}]}
    def focus(self): return (0.0, 0.0, 0.0, 0.0)
cam = rl.Camera3D(rl.Vector3(0, 60, 40), rl.Vector3(0, 0, 0), rl.Vector3(0, 1, 0), 45.0, rl.CAMERA_PERSPECTIVE)
for i in range(3):
    rl.begin_drawing(); rl.clear_background(rl.Color(60, 70, 60, 255)); hud.draw_players(S(), cam, 1280, 720); rl.end_drawing()
rl.take_screenshot(sys.argv[1])
