"""Petrol stations and car washes: the sites come from the world (props "fuelsites", built by tools/stations.py from OSM).

* Traffic: a passing car sometimes turns into a station to refuel / shop (Stations.steer picks the entrance at a junction,
  Stations.drive stands it next to the pumps for a while, then it carries on).  Lorries never do (they only park).
* Player: stand still next to the pumps and the tank is filled for money; at a car wash press 1 to have the car washed
  or 2 for the expensive re-spray, which also clears the police wanted level (hook: Sim.clear_wanted, to come with the
  police system; until then only the car is made good as new).

All in-game text here is written straight into the code in Macedonian Cyrillic (the text/ folder is edited by hand)."""
import math

import vehicles
import clock

FILL_PRICE = 1200          # ден. for a tank filled from empty
WASH_PRICE, RESPRAY_PRICE = 150, 1500
FUEL_R, WASH_R = 9.0, 10.0  # how close the player's car must stand to the stop point (m)
ENTER_P = {0: 0.30, 1: 0.18}   # chance a car takes the entrance of a station it passes
DWELL = {0: (18.0, 42.0), 1: (25.0, 45.0)}   # seconds a visitor stays
WASH_SECS = 3.0
T_FILL = "{n}: застани до пумпата за полнење на резервоарот ({p} ден.)"
T_FILLED = "Резервоарот е полн  −{p} ден."
T_WASH = "{n}:  [1] Миење {a} ден.   [2] Прелакирање {b} ден. (потерницата се брише)"
T_WASHED = "Колата е измиена  −{p} ден."
T_RESPRAY = "Колата е прелакирана, никој не те препознава!  −{p} ден."
T_BROKE = "Немаш доволно денари ({p} ден.)"
CARS = ("hatch", "sedan", "taxi", "mini", "suv", "wagon", "pickup", "van")


class Stations:
    def __init__(self, sim):
        self.sim = sim
        w = sim.w
        self.sites = []
        for x, y, kind, ei, s, visit, name in (getattr(w, "fuelsites", None) or []):
            ok = visit and 0 <= ei < len(w.edges)
            if ok:
                px, py, _dx, _dy = w.edge_point(w.edges[ei], s)
                ok = (px - x) ** 2 + (py - y) ** 2 < 9.0                 # the graph still matches the world the sites were built with
            self.sites.append({"x": x, "y": y, "kind": kind, "edge": ei if ok else -1, "s": s, "name": name})
        self.entry = {}                 # (edge, dir) -> [(site, hops)]: driving into it leads to the site's edge
        self.arrive = {}                # node -> [(edge, dir)] that arrive at it
        for ei, e in enumerate(w.edges):
            if e["drive"]:
                self.arrive.setdefault(e["b"], []).append((ei, 1))
                if not e["ow"]:
                    self.arrive.setdefault(e["a"], []).append((ei, -1))
        for k, st in enumerate(self.sites):
            if st["edge"] >= 0:
                self._index(k, st)
        self.prompt = ""
        self.fill_t = 0.0
        self.busy = 0.0                 # seconds left of the player's car wash
        self.n_visits = 0
        self.wanted_cleared = 0         # how many times the re-spray was bought (the police system will read the hook)

    def _index(self, k, st):
        w = self.sim.w
        ei = st["edge"]
        e = w.edges[ei]
        for d, node in ((1, e["a"]), (-1, e["b"])):                  # entering the station edge at node `node` driving direction d
            if (ei, d) in w.out.get(node, ()):
                self.entry.setdefault((ei, d), []).append((k, 0))
                for e2i, d2 in self.arrive.get(node, ()):             # one more hop: the edge that arrives at that node
                    if e2i != ei and w.edges[e2i]["len"] < 90 and w.edges[e2i]["cls"] in ("service", "living_street", "residential", "unclassified"):
                        self.entry.setdefault((e2i, d2), []).append((k, 1))

    # ----------------------------------------------------------------------------------- traffic
    def steer(self, c, good, turns):
        """Called when car c has picked its next edge: sometimes the entrance of a station instead."""
        tr = self.sim.traffic
        if c.stn is not None:                                         # already heading for one: keep to the way in
            for i, o in enumerate(good):
                if any(k == c.stn for k, _ in self.entry.get(o, ())):
                    c.nxt, c.turn = o, turns[i]
                    return
            c.stn = None
            return
        if c.kind in vehicles.LARGE or vehicles.STYLE[c.kind] not in CARS or c.kind in clock.EMERGENCY:
            return
        for i, o in enumerate(good):
            for k, hops in self.entry.get(o, ()):
                st = self.sites[k]
                if tr.rng.random() < ENTER_P[st["kind"]] * (1.0 if hops == 0 else 0.7):
                    c.nxt, c.turn, c.stn, c.dwell, c.stn_t = o, turns[i], k, None, 120.0
                    return

    def drive(self, c, e, vlim, dt):
        """Speed limit for a car heading for / standing at a station.  -> (vlim, waiting)"""
        st = self.sites[c.stn]
        c.stn_t -= dt
        if c.stn_t <= 0:
            c.stn = None
            return vlim, False
        if c.e != st["edge"]:
            return vlim, False                                       # still on the way in (steer() drops it if the way changes)
        stop = st["s"] if c.d == 1 else e["len"] - st["s"]
        rem = stop - c.s
        if c.dwell is None:
            if rem < -1.0:                                           # drove past the pumps: not this time
                c.stn = None
                return vlim, False
            if rem < 1.3 and c.v < 0.6:
                a, b = DWELL[st["kind"]]
                c.dwell = self.sim.rng.uniform(a, b)
                self.n_visits += 1
                return 0.0, True
            return min(vlim, math.sqrt(2 * 2.2 * max(rem - 0.4, 0.0)) + 0.3), False
        c.dwell -= dt
        if c.dwell <= 0:
            c.stn = None
            return vlim, False
        return 0.0, True

    # ----------------------------------------------------------------------------------- player
    def _near(self, x, y):
        best, bd = None, 1e9
        for st in self.sites:
            r = FUEL_R if st["kind"] == 0 else WASH_R
            d = (st["x"] - x) ** 2 + (st["y"] - y) ** 2
            if d < r * r and d < bd:
                best, bd = st, d
        return best

    def update(self, dt, inp):
        """Once a frame, before the physics.  -> an inp with the controls locked while the car is being washed, else None."""
        sim = self.sim
        self.prompt = ""
        car = sim.car
        if self.busy > 0:
            self.busy -= dt
            car.vx = car.vy = car.w = 0.0
            for sd in (-1, 1):                                       # water jets either side
                ex, ey = -math.sin(car.h) * sd, math.cos(car.h) * sd
                sim.ev("spray", x0=car.x + ex * 1.2, y0=car.y + ey * 1.2, x1=car.x - ex * 0.5, y1=car.y - ey * 0.5)
            return dict(inp, throttle=0.0, steer=0.0, handbrake=True, buy=None)
        if sim.mode != "car" or getattr(sim, "riding", None) is not None or not car.alive:
            self.fill_t = 0.0
            return None
        st = self._near(car.x, car.y)
        if st is None or car.speed > 2.5:
            self.fill_t = 0.0
            return None
        if st["kind"] == 0:
            miss = 1.0 - car.fuel
            price = max(20, int(math.ceil(miss * FILL_PRICE)))
            nm = st["name"] or "Бензинска пумпа"
            if miss < 0.03:
                self.prompt = nm
                return None
            self.prompt = T_FILL.format(n=nm, p=price)
            self.fill_t = self.fill_t + dt if car.speed < 1.0 else 0.0
            if self.fill_t > 1.2:
                self.fill_t = 0.0
                if sim.money < 20:
                    sim.ev("station", text=T_BROKE.format(p=price), snd="denied_buzz")
                else:
                    pay = min(price, sim.money)                          # short of money: as much fuel as it buys
                    car.fuel = min(1.0, car.fuel + miss * pay / price)
                    sim.money -= pay
                    sim.ev("station", text=T_FILLED.format(p=pay), snd="fuel_pour")
            return None
        self.prompt = T_WASH.format(n=st["name"] or "Автоперална", a=WASH_PRICE, b=RESPRAY_PRICE)
        k = inp.get("buy")
        if k in (0, 1):
            price = WASH_PRICE if k == 0 else RESPRAY_PRICE
            if sim.money < price:
                sim.ev("station", text=T_BROKE.format(p=price), snd="denied_buzz")
                return None
            sim.money -= price
            car.dents = []
            car.burn = 0.0
            car.model, car.dirty = None, True
            self.busy = WASH_SECS
            if k == 0:
                sim.ev("station", text=T_WASHED.format(p=price), snd="cash")
            else:
                self.wanted_cleared += 1
                hook = getattr(sim, "clear_wanted", None)            # the police system will provide it
                if hook is not None:
                    hook()
                sim.ev("station", text=T_RESPRAY.format(p=price), snd="cash")
        return None
