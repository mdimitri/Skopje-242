"""Renders the multiplayer name / browser / room screens headless (xvfb) to PNG files: shot_lobby.py <outdir>"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import pyray as rl
rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN * 0)
rl.init_window(1280, 720, "t")
import font; font.load()
import lobby, mp, profile
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
prof = profile.Profile("/nonexistent/p.json"); prof.name = "Мартин"
state = {"n": 0, "name": "x"}
real_end = rl.end_drawing
def end():
    real_end(); state["n"] += 1
    if state["n"] == 15: rl.take_screenshot(os.path.join(out, state["name"] + ".png"))
lobby.rl.end_drawing = end
lobby.rl.window_should_close = lambda: state["n"] >= 16
# name screen
p0 = profile.Profile("/nonexistent/p.json"); lobby._ask_name(p0, None)
state.update(n=0, name="name"); 
# browser
state.update(n=0, name="browser"); s = mp.Session(prof); s.mqtt = None; s.lan = None
s.found = {"a": {"id": "a", "name": "Ана", "n": 2, "max": 4, "ver": 1, "addr": ["1.2.3.4", 5], "seen": time.monotonic() + 999}}
s.browse = lambda: None; lobby._browser(prof, s, None)
# room
state.update(n=0, name="room"); h = mp.Session(prof); h.host(internet=False)
g = mp.Session(profile.Profile("/nonexistent/p.json")); g.prof.name = "Ана"; g.join({"addr": ["127.0.0.1", h.net.port], "lan": True})
for _ in range(200): h.update(); g.update(); time.sleep(0.005)
g.send_chat("Ајде на Кале"); h.send_chat("Важи, 10 мин"); h.set_cfg(spawn=2, ff=True)
for _ in range(60): h.update(); g.update(); time.sleep(0.005)
lobby._room(prof, h, None)
