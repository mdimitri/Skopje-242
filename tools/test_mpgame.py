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
host.set_cfg(ff=True)
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
# ---- 5. player vs player (friendly fire on)
put(gs, hx + 6, hy + 6); frames(100)
assert gs.client and hg.auth == {0: 0, 1: 0}
hw, gw = hs.walker, gs.walker
gw.x, gw.y = hw.x + 1.0, hw.y; gw.lx, gw.ly = gw.x, gw.y
frames(25)
def face():
    gw.h = math.atan2(hw.y - gw.y, hw.x - gw.x)
h0 = hw.health
for _ in range(3):
    face(); gw.atk_cd = 0; gs.attack(); frames(3)
print("5a punches: host walker health %.0f -> %.0f" % (h0, hw.health)); assert hw.health < h0
hw.health = 100.0; frames(5)
gw.guns["pistol"] = 20; gw.weapon = "pistol"
h1 = hw.health
face(); gw.atk_cd = 0; gs.attack(); frames(12)
print("5b pistol : host walker health %.0f -> %.0f" % (h1, hw.health)); assert hw.health < h1
hs.pvp = False; h2 = hw.health; hg.take_hit(1, "shot", 30); assert hw.health == h2
hs.pvp = True
hw.health = 100.0; frames(5)
gw.weapon = "fist"
for _ in range(40):
    if hw.health <= 0: break
    face(); gw.atk_cd = 0; gs.attack(); frames(3)
frames(10)
print("5c kill   : host health %.0f, host deaths %d, guest kills %d" % (hw.health, hg.deaths, gg.kills))
assert hw.health <= 0 and hg.deaths == 1 and gg.kills == 1
# ---- 6. shared things: parked cars taken, dropped cars, stealing a traffic car as a follower, riding the host's bus
import actors, vehicles
hw.health = 100.0; hs.walker.cause = None; frames(5)
pk = actors.Body(hw.x + 40, hw.y + 40, 0.0, 1, 0); pk.parked_idx = 999
hs.bodies.append(pk); gs.gone.add(999); frames(30)
print("6a parked car taken by guest -> removed on host:", pk not in hs.bodies and 999 in hs.gone)
assert pk not in hs.bodies and 999 in hs.gone
dr = [b for b in gs.bodies if getattr(b, "drop_pid", None) == 0]
print("6b host's dropped car visible to guest:", len(dr))
assert len(dr) == 1
car = dr[0]
gw.x, gw.y = car.x + 2.0, car.y + 1.0; gw.lx, gw.ly = gw.x, gw.y
frames(10)
assert gs.try_enter() is True
frames(80)
print("6c guest took it: guest mode %s, host still has its car: %s, host drop_body %s" % (gs.mode, hs.car in hs.bodies, hg.drop_body))
assert gs.mode == "car" and hg.drop_body is None and hs.car not in hs.bodies
gs.exit_car(); frames(20)
# stealing a traffic car as a follower
gw = gs.walker
tgt = min(gs.traffic.cars, key=lambda c: math.hypot(c.x - gw.x, c.y - gw.y))
hostcar = min(hs.traffic.cars, key=lambda c: math.hypot(c.x - tgt.x, c.y - tgt.y))
gw.x, gw.y = tgt.x + 1.5, tgt.y; gw.lx, gw.ly = gw.x, gw.y
assert gs.try_enter() is True
frames(40)
print("6d traffic car stolen by follower -> host dropped it:", hostcar not in hs.traffic.cars)
assert hostcar not in hs.traffic.cars
# the bus
frames(120)
bus = actors.Body(hw.x + 8, hw.y, 0.0, 1, 0); bus.bus_line = "T1"; bus.ctl = (0.0, 0.0, True); bus.empty = False
hs.bodies.append(bus); frames(30)
pb = [b for b in gs.bodies if getattr(b, "puppet", False) and getattr(b, "bus_line", None)]
print("6e bus puppets on guest:", len(pb)); assert len(pb) == 1
gs.exit_car() if gs.mode == "car" else None
gw = gs.walker; gw.x, gw.y = pb[0].x + 0.3, pb[0].y + 1.2; gw.lx, gw.ly = gw.x, gw.y
gs.money = 100
assert gs.try_enter() is True
frames(40)
print("6f riding: guest riding puppet bus %s, mode %s; host sees guest drawn: body %s foot %s" % (gs.riding is not None, gs.mode, hg.remote[1].get("body"), 1 in hs.remote_foot))
assert gs.riding is not None and gs.mode == "car" and gs.car in gs.bodies
assert hg.remote[1].get("body") is None and 1 not in hs.remote_foot
gs.exit_car(); frames(10)
assert gs.mode == "foot"
# ---- 7. wire ids of cars / pedestrians that left the world are forgotten
frames(int(11 / dt))
live = {id(o) for o in hs.traffic.cars} | {id(o) for o in hs.peds.list} | {id(o) for o in hs.bodies}
print("7 wire ids kept: %d, all alive: %s" % (len(hg.byid), all(id(o) in live for o in hg.byid.values())))
frames(1)
# ---- 8. a message from one guest for another guest is passed on by the host
sent = []
_route = hg._route; hg._route = lambda to, m: sent.append((to, m["t"]))
for t in ("take", "claim", "dmg", "kill"):
    hg._rel({"t": t, "to": 2}, addr=("127.0.0.1", 1))
hg._route = _route
print("8 host passes on:", sent); assert sent == [(2, "take"), (2, "claim"), (2, "dmg"), (2, "kill")]
print("bytes: host tx %d rx %d" % (host.net.bytes_tx, host.net.bytes_rx))
# ---- 9. the host leaves: the guest carries on alone with real traffic, nothing frozen
assert gs.client
nc = len(gs.traffic.cars)
host.leave()
for _ in range(60):
    gs.update(dt, IDLE, 2); gg.update(dt); time.sleep(0.003)
c0 = [(c.x, c.y) for c in gs.traffic.cars]
for _ in range(90):
    gs.update(dt, IDLE, 2); gg.update(dt)
moved = sum(1 for c, q in zip(gs.traffic.cars, c0) if math.hypot(c.x - q[0], c.y - q[1]) > 0.5)
print("9 host left: guest state %s, client %s, cars %d -> %d (%d moving), other players %d" % (g.state, gs.client, nc, len(gs.traffic.cars), moved, len(gg.remote)))
assert g.state == "closed" and not gs.client and len(gs.traffic.cars) > 0 and moved > 0 and not gg.remote
print("OK mpgame groups")
