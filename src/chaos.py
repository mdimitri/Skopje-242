"""Things people punch, blow up and set on fire: street furniture that breaks or flies, blast waves that push props,
people and wrecks around, and chain fires between cars.  The Sim owns one Chaos (sim.chaos) and calls it from the
punch, the rocket / car explosion and the per-frame update; the renderer draws `chaos.fly`."""
import math
import random

import actors

FIRE_REACH = 5.5                  # a burning car sets another one alight within this distance (m)
FIRE_TIME = 2.6                   # seconds of exposure at point-blank range before a neighbour ignites
LIGHT_H, TALL_H = 2.2, 5.0        # props lower than LIGHT_H fly when hit, taller than TALL_H are posts / poles


def height(w, pt):
    """Real height of a collision point: its `lo` is often far below the ground (the point reaches down to the road)."""
    return pt[4] - max(pt[3], w.ground_y(pt[0], pt[1]) - 0.3)


def _kind(w, pt):
    """tree | post | light | mid: what a collision point (x, y, r, lo, hi) is, judged by its size."""
    tr = pt[2]
    h = height(w, pt)
    if tr >= 0.45 and h > 8:
        return "tree"
    if h > TALL_H:
        return "post"
    return "light" if h < LIGHT_H else "mid"


class Chaos:
    def __init__(self, sim):
        self.sim = sim
        self.rng = random.Random(77)
        self.fly = []             # [x, y, z, vx, vy, vz, spin, spin_v, w, h, (r, g, b), ttl]
        self.fires = 0            # cars set alight by other cars (stats)

    # ------------------------------------------------------------------ props
    def smash(self, pt, vx, vy, up=4.5, fly=None):
        """Knock a prop out of the world (its mesh is hidden by World.break_point) and, if it is light, throw it."""
        sim, w, rng = self.sim, self.sim.w, self.rng
        k = _kind(w, pt)
        w.break_point(pt)
        if fly is None:
            fly = k == "light"
        if k == "tree":
            col = (120, 96, 70)
        elif k == "post":
            col = (150, 150, 156)
        else:
            col = rng.choice(((96, 112, 100), (140, 110, 80), (120, 120, 126), (60, 100, 150)))
        if fly and k != "tree":
            h = max(0.3, min(1.4, height(w, pt)))
            gy = w.ground_y(pt[0], pt[1])
            self.fly.append([pt[0], pt[1], gy + 0.2, vx, vy, up + rng.uniform(0, 2.0), 0.0, rng.uniform(-300, 300),
                             max(0.25, pt[2] * 2), h, col, 14.0])
            if len(self.fly) > 60:
                self.fly.pop(0)
        sim.ev("prop_break", x=pt[0], y=pt[1], kind=k, fly=bool(fly))
        return k

    def _pay(self, amount, x, y):
        if amount > 0:
            self.sim.money += amount
            self.sim.ev("pay", x=x, y=y, amount=amount)

    def punch(self, wk, kick):
        """A punch / kick lands in front of the player: small things fly, bigger ones break, posts need a kick."""
        sim, w = self.sim, self.sim.w
        fx, fy = math.cos(wk.h), math.sin(wk.h)
        cx, cy = wk.x + fx * (1.0 if kick else 0.9), wk.y + fy * (1.0 if kick else 0.9)
        az = wk.az if wk.az is not None else 0.0
        done = 0
        for pt in sorted(w.points_near(cx, cy, 1.1), key=lambda q: (q[0] - cx) ** 2 + (q[1] - cy) ** 2):
            if math.hypot(pt[0] - cx, pt[1] - cy) > 0.7 + pt[2]:
                continue
            if pt[4] < az + 0.1 or pt[3] > az + 1.8:
                continue
            k = _kind(w, pt)
            if k == "tree" or (k == "post" and not kick):
                sim.ev("prop_thud", x=pt[0], y=pt[1], leaves=k == "tree")
                continue
            sp = 10.0 if kick else 7.0
            self.smash(pt, fx * sp + self.rng.uniform(-1.5, 1.5), fy * sp + self.rng.uniform(-1.5, 1.5), 7.0 if kick else 5.5)
            self._pay(self.rng.randint(10, 18) if k != "light" else self.rng.randint(5, 10), pt[0], pt[1])
            sim.stats["props"] = sim.stats.get("props", 0) + 1
            done += 1
            if done >= 2:
                break
        return done

    # ------------------------------------------------------------------ blasts
    def blast(self, x, y, r=9.0, peds=True):
        """Shock wave: props in range break or fly, flyers are pushed, people are thrown, the player is hurt."""
        sim, w, rng = self.sim, self.sim.w, self.rng
        if getattr(sim, "dogs", None) is not None:
            sim.dogs.scare(x, y, r * 5.5)
        for pt in w.points_near(x, y, r):
            d = math.hypot(pt[0] - x, pt[1] - y)
            if d > r:
                continue
            k = _kind(w, pt)
            if k == "tree" and d > r * 0.5:
                continue
            n = d or 1.0
            sp = (1.0 - d / r) * 16.0 + 3.0
            self.smash(pt, (pt[0] - x) / n * sp, (pt[1] - y) / n * sp, 4.0 + (1.0 - d / r) * 8.0, fly=k in ("light", "mid"))
            self._pay(4, pt[0], pt[1])
        for f in self.fly:
            d = math.hypot(f[0] - x, f[1] - y)
            if d < r * 1.3:
                n = d or 1.0
                sp = (1.0 - d / (r * 1.3)) * 14.0
                f[3] += (f[0] - x) / n * sp
                f[4] += (f[1] - y) / n * sp
                f[5] += 4.0 + sp * 0.4
                f[7] = rng.uniform(-500, 500)
        if peds:
            pay = 0
            for p in sim.peds.list:
                if p.mode in ("dead", "air", "svc"):
                    continue
                d = math.hypot(p.x - x, p.y - y)
                if d >= r:
                    continue
                n = d or 1.0
                p.hp -= (1.0 - d / r) * 110.0
                if p.hp <= 0 or d < r * 0.5:
                    p.mode, p.t, p.hy, p.hv = "air", actors.clear_secs(sim), 0.2, 5.0 + (1.0 - d / r) * 5.0
                    p.vx, p.vy = (p.x - x) / n * 9.0, (p.y - y) / n * 9.0
                    sim.stats["peds"] += 1
                    pay += 20
                else:
                    p.mode, p.t = "flee", rng.uniform(4.0, 7.0)
                    p.vx, p.vy = (p.x - x) / n * 5.0, (p.y - y) / n * 5.0
            self._pay(pay, x, y)
        wk = sim.walker
        if sim.mode == "foot" and wk is not None and wk.health > 0:
            d = math.hypot(wk.x - x, wk.y - y)
            if d < r:
                wk.health -= (1.0 - d / r) * 70.0
                n = d or 1.0
                wk.vx += (wk.x - x) / n * 6.0
                wk.vy += (wk.y - y) / n * 6.0
                wk.hurt_t = 0.4
                if wk.health <= 0:
                    wk.cause = "boom"
                    sim.ev("walker_dead", cause="explosion")

    # ------------------------------------------------------------------ per frame
    def update(self, dt):
        w = self.sim.w
        out = []
        for f in self.fly:
            f[11] -= dt
            if f[11] <= 0:
                continue
            f[0] += f[3] * dt
            f[1] += f[4] * dt
            f[2] += f[5] * dt
            f[5] -= 16.0 * dt
            f[6] += f[7] * dt
            gy = w.ground_y(f[0], f[1])
            if f[2] <= gy + f[9] * 0.5:
                f[2] = gy + f[9] * 0.5
                if f[5] < -2.5:                                   # bounce
                    f[5] = -f[5] * 0.35
                    f[3] *= 0.6
                    f[4] *= 0.6
                    f[7] *= 0.5
                else:
                    f[5] = 0.0
                    f[3] *= math.exp(-4.0 * dt)
                    f[4] *= math.exp(-4.0 * dt)
                    f[7] *= math.exp(-3.0 * dt)
            out.append(f)
        self.fly = out
        self._spread_fire(dt)

    # ------------------------------------------------------------------ fire
    def _spread_fire(self, dt):
        """A burning car heats the cars around it; after FIRE_TIME at close range they burn (and explode) too."""
        sim = self.sim
        burning = [b for b in sim.bodies if b.health <= 0 and not b.exploded and not b.out]
        if not burning:
            return
        for b in burning:
            for o in sim.bodies:
                if o is b or o.health <= 0 or o.exploded:
                    continue
                d = math.hypot(o.x - b.x, o.y - b.y)
                if d >= FIRE_REACH:
                    continue
                o.ignite += dt * (1.0 - d / FIRE_REACH) * 2.0 / FIRE_TIME * 1.6
                if o.ignite >= 1.0:
                    o.health = min(o.health, -1.0)
                    o.dirty = True
                    self.fires += 1
                    sim.ev("car_ignite", body=o)
            for c in list(sim.traffic.cars):                      # moving traffic: the driver bails out, the car is a wreck
                if (c.x - b.x) ** 2 + (c.y - b.y) ** 2 < (FIRE_REACH * 0.7) ** 2:
                    tmp = sim.traffic.make_body(c)
                    sim.traffic.cars.remove(c)
                    tmp.empty = True
                    tmp.ignite = 0.6
                    sim.bodies.append(tmp)
                    lx, ly = math.sin(tmp.h), -math.cos(tmp.h)
                    sim.peds.eject(tmp.x + lx * 2.0, tmp.y + ly * 2.0, tmp.h + math.pi / 2, gz=tmp.az)
