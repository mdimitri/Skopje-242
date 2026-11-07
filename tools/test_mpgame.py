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
dt = 1 / 30
IDLE = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0, 0), "run": False, "attack": False, "buy": None, "jump": False}

def frames(n, gmove=(0, 0)):
    for _ in range(n):
        hs.update(dt, IDLE, 2)
        gs.update(dt, dict(IDLE, move=gmove), 2)
        hg.update(dt); gg.update(dt); time.sleep(0.003)

def put(sim, x, y):
    nw = world.nearest_walk_point(x, y, 400)
    x, y, _a, _b = world.edge_point(world.edges[nw[0]], nw[1])
    w = sim.walker
    w.x, w.y, w.lx, w.ly = x, y, x, y
    w.az = world.ground_y(x, y)

def far_point():
    hx, hy = hs.focus()[:2]
    for dx, dy in ((1100, 0), (-1100, 0), (0, 1100), (0, -1100), (800, 800), (-800, -800)):
        q = world.nearest_drive_point(hx + dx, hy + dy, 300)
        if q and math.hypot(q[0] - hx, q[1] - hy) > 900:
            return q[0], q[1]
    return world.nearest_drive_point(hx + 1100, hy, 3000)[:2]

def err(a_list, b_list):
    return max(min(math.hypot(c.x - h.x, c.y - h.y) for h in b_list) for c in a_list)

# ---- 1. together: host is the authority, guest follows
frames(240, (1.0, 0.0))
print("1 near : auth", hg.auth, "guest client", gs.client, "| puppet cars %d peds %d" % (len(gs.traffic.cars), len(gs.peds.list)))
assert hg.auth == {0: 0, 1: 0} and gs.client and not hs.client
assert len(gs.traffic.cars) > 0 and len(gs.peds.list) > 0
print("  puppet error: cars %.2f m, peds %.2f m" % (err(gs.traffic.cars, hs.traffic.cars), err(gs.peds.list, hs.peds.list)))
assert err(gs.traffic.cars, hs.traffic.cars) < 6 and err(gs.peds.list, hs.peds.list) < 4
assert 1 in hs.remote_foot and 0 in gs.remote_foot
# ---- 2. guest far away: both run their own world
hx, hy = hs.focus()[:2]
fx, fy = far_point()
print("  far point %.0f m from host" % math.hypot(fx - hx, fy - hy))
assert math.hypot(fx - hx, fy - hy) > 900, "synthetic world too small for the far test"
put(gs, fx, fy)
frames(150)
print("2 apart: auth", hg.auth, "guest client", gs.client, "| guest own cars %d peds %d, host extra foci %d" % (len(gs.traffic.cars), len(gs.peds.list), len(hs.traffic.extra)))
assert hg.auth == {0: 0, 1: 1} and not gs.client and not hs.client and hs.traffic.extra == []
assert len(gs.traffic.cars) > 3 and len(gs.peds.list) > 3
# ---- 3. guest returns: joins the host's group again
put(gs, hx + 5, hy + 5)
frames(120)
print("3 meet : auth", hg.auth, "guest client", gs.client, "| puppet cars %d peds %d" % (len(gs.traffic.cars), len(gs.peds.list)))
assert hg.auth == {0: 0, 1: 0} and gs.client and len(gs.traffic.cars) > 0
# ---- 4. they part again: puppets must be adopted (no pop)
nc, npd = len(gs.traffic.cars), len(gs.peds.list)
put(gs, fx, fy)
frames(1)
print("4 split: puppets before %d cars %d peds, real after %d cars %d peds" % (nc, npd, len(gs.traffic.cars), len(gs.peds.list)))
frames(20)
assert not gs.client
print("bytes: host tx %d rx %d" % (host.net.bytes_tx, host.net.bytes_rx))
print("OK mpgame groups")
