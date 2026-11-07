"""Headless sync test: a host Sim and a guest Sim (client mode) over loopback UDP on a synthetic world.
Usage: python3 tools/test_mpgame.py <world_dir>"""
import math, os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mp, mpgame, mpprofile
from world import World
from actors import Sim

world = World(sys.argv[1], lambda f, note="": None)

def mk(name, uid, seed):
    p = mpprofile.Profile("/nonexistent/p.json"); p.name, p.uid = name, uid
    sim = Sim(world, random.Random(seed), 60, 40); sim.ev = lambda *a, **k: None
    return p, sim

hp, hs = mk("Домаќин", "h", 1)
gp, gs = mk("Гостин", "g", 2)
host = mp.Session(hp); host.host(internet=False)
g = mp.Session(gp); g.join({"addr": ["127.0.0.1", host.net.port], "lan": True})
for _ in range(400):
    host.update(); g.update(); time.sleep(0.005)
    if g.state == "lobby": break
assert g.state == "lobby"
host.start()
for _ in range(200):
    host.update(); g.update(); time.sleep(0.005)
    if g.state == "playing": break
assert g.state == "playing"
hg, gg = mpgame.Game(hs, host), mpgame.Game(gs, g)
for s, ses in ((hs, host), (gs, g)):
    mpgame.spawn(s, world, ses); s.exit_car()
assert gs.client and not hs.client
dt = 1 / 30
for i in range(240):
    hs.update(dt, {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0, 0), "run": False, "attack": False, "buy": None, "jump": False}, 2)
    gs.update(dt, {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (1.0, 0.0), "run": False, "attack": False, "buy": None, "jump": False}, 2)
    hg.update(dt); gg.update(dt); time.sleep(0.004)
hc = [c for c in hs.traffic.cars if (c.x - gs.walker.x) ** 2 + (c.y - gs.walker.y) ** 2 < 230 ** 2]
print("host cars near guest %d, guest puppet cars %d; host peds near %d, guest puppet peds %d" % (
    len(hc), len(gs.traffic.cars), len([p for p in hs.peds.list if (p.x - gs.walker.x) ** 2 + (p.y - gs.walker.y) ** 2 < 130 ** 2]), len(gs.peds.list)))
assert len(gs.traffic.cars) > 0 and len(gs.peds.list) > 0
# every guest puppet car must be close to a host car (interpolation lag only)
worst = max(min(math.hypot(c.x - h.x, c.y - h.y) for h in hs.traffic.cars) for c in gs.traffic.cars)
print("worst puppet-car error vs host: %.2f m" % worst); assert worst < 6.0
worstp = max(min(math.hypot(c.x - h.x, c.y - h.y) for h in hs.peds.list) for c in gs.peds.list)
print("worst puppet-ped error vs host: %.2f m" % worstp); assert worstp < 4.0
# players see each other
assert 1 in hg.remote and 0 in gg.remote, (hg.remote.keys(), gg.remote.keys())
assert hg.remote[1]["flags"] & 1 and 1 in hs.remote_foot and 0 in gs.remote_foot
err = math.hypot(hs.remote_foot[1]["x"] - gs.walker.x, hs.remote_foot[1]["y"] - gs.walker.y)
print("host's view of guest walker error: %.2f m (guest walked %.1f m)" % (err, math.hypot(gs.walker.x - hg.remote[1]["x"] + err, 0)))
assert err < 2.5
print("bytes: host tx %d rx %d (4 s, 1 guest)" % (host.net.bytes_tx, host.net.bytes_rx))
print("OK mpgame sync")
