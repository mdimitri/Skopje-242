"""Three players (host + two guests) over loopback UDP: actions of one guest reach the other guest through the host.
Usage: python3 tools/test_mpgame3.py <world_dir>"""
import math, os, random, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import mp, mpgame, mpprofile
from world import World
from actors import Sim

world = World(sys.argv[1], lambda f, note="": None)
names = ["Домаќин", "Гостин1", "Гостин2"]
profs, sims = [], []
for i, n in enumerate(names):
    p = mpprofile.Profile("/nonexistent/p.json"); p.name, p.uid = n, "u%d" % i
    sim = Sim(world, random.Random(i + 1), 60, 40); sim.ev = lambda *a, **k: None
    profs.append(p); sims.append(sim)
host = mp.Session(profs[0]); host.host(internet=False)
guests = []
for p in profs[1:]:
    g = mp.Session(p); g.join({"addr": ["127.0.0.1", host.net.port], "lan": True}); guests.append(g)
ses = [host] + guests
def pump(n=1, cond=None):
    for _ in range(n):
        for s in ses: s.update()
        time.sleep(0.005)
        if cond and cond(): return True
    return False
assert pump(600, lambda: all(g.state == "lobby" for g in guests))
host.set_cfg(ff=True)
host.set_ready(True)
for g_ in guests: g_.set_ready(True)
assert pump(400, lambda: host.all_ready())
host.start()
assert pump(400, lambda: all(g.state == "playing" for g in guests))
games = [mpgame.Game(s, e) for s, e in zip(sims, ses)]
for s, e in zip(sims, ses):
    mpgame.spawn(s, world, e); s.exit_car()
dt = 1 / 30
IDLE = {"throttle": 0, "steer": 0, "handbrake": False, "horn": False, "move": (0, 0), "run": False, "attack": False, "buy": None, "jump": False}
def frames(n):
    for _ in range(n):
        for s in sims: s.update(dt, IDLE, 2)
        for g in games: g.update(dt)
        time.sleep(0.003)
hs, g1s, g2s = sims
hx, hy = hs.focus()[:2]
for s in (g1s, g2s):
    nw = world.nearest_walk_point(hx + 5, hy + 5, 400)
    x, y, _a, _b = world.edge_point(world.edges[nw[0]], nw[1])
    w = s.walker; w.x, w.y, w.lx, w.ly, w.az = x, y, x, y, world.ground_y(x, y)
frames(150)
print("auth:", games[0].auth)
assert len(set(games[0].auth.values())) == 1 and g1s.client and g2s.client
# guest 1 punches guest 2: guest 2 loses health and sees guest 1's punch frame
w1, w2 = g1s.walker, g2s.walker
w1.x, w1.y = w2.x - 1.0, w2.y; w1.lx, w1.ly = w1.x, w1.y; w1.h = 0.0
frames(20)
h0, seen = w2.health, set()
for _ in range(3):
    w1.atk_cd = 0; g1s.attack()
    for _ in range(8):
        frames(1)
        if 1 in g2s.remote_foot: seen.add(g2s.remote_foot[1]["frame"])
print("guest1 punches guest2: health %.0f -> %.0f, frames seen by guest2 %s" % (h0, w2.health, seen))
assert w2.health < h0 and seen & {4, 5}
# guest 1 punches a pedestrian: the authority (host) and guest 2 both see the result
puppet = next(p for p in g1s.peds.list if p.mode == "walk")
wid = next(i for i, e in games[1].peds.items() if e["obj"] is puppet); real = games[0].byid[wid]
for _ in range(8):
    puppet = games[1].peds[wid]["obj"]
    w1.h = math.atan2(puppet.y - w1.y, puppet.x - w1.x); w1.x, w1.y = puppet.x - 1.0, puppet.y; w1.atk_cd = 0; g1s.attack(); frames(5)
    if real.hp < 40 or real.mode in ("ko", "dead", "flee", "fight"): break
frames(15)
other = games[2].peds.get(wid, {}).get("obj")
print("ped: host hp %.0f mode %s, guest2 sees mode %s" % (real.hp, real.mode, other.mode if other else None))
assert real.hp < 40 or real.mode != "walk"
assert other is not None and other.mode == real.mode
print("OK 3 players")
