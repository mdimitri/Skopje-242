"""Real projectiles: bullets, pellets and rockets fly at a visible speed and hit whatever they meet first -
people, parked or moving cars, building walls, trees / posts, or the ground at the end of their range.

Each hit raises an event the renderer turns into a puff, sparks, debris or an explosion, pays денари, and leaves
a mark: cars lose health (and burn then explode), walls keep bullet holes / scorch marks (capped list)."""
import math

import vehicles

# kind -> (speed m/s, radius m, tracer colour)
KINDS = {"bullet": (38.0, 0.06, (255, 236, 150)), "pellet": (32.0, 0.05, (255, 220, 140)),
         "rocket": (15.0, 0.16, (255, 160, 60))}
PAY = {"ped": 5, "kill": 20, "car": 8, "wreck": 40, "wall": 1, "tree": 1}
MARKS_MAX = 600
STEP = 1.2                                   # metres per collision sub-step


class Projectiles:
    def __init__(self, sim):
        self.sim = sim
        self.list = []                       # [x, y, vx, vy, travelled, reach, dmg, kind, z]
        self.marks = []                      # (x, y, z, nx, ny, size, dark) wall damage drawn by the renderer

    def fire(self, x, y, ang, kind, dmg, reach, z=1.15):
        sp = KINDS[kind][0]
        self.list.append([x, y, math.cos(ang) * sp, math.sin(ang) * sp, 0.0, reach, dmg, kind, z])

    def update(self, dt):
        keep = []
        for p in self.list:
            sp = math.hypot(p[2], p[3]) or 1.0
            dist = sp * dt
            n = max(1, int(dist / STEP) + 1)
            hit = False
            for _ in range(n):
                ox, oy = p[0], p[1]
                p[0] += p[2] * dt / n
                p[1] += p[3] * dt / n
                p[4] += dist / n
                if self._collide(p, ox, oy):
                    hit = True
                    break
                if p[4] >= p[5]:
                    self._impact(p, "ground", None, p[0], p[1])
                    hit = True
                    break
            if not hit:
                if p[7] == "rocket":
                    self.sim.ev("rocket_trail", x=p[0], y=p[1])
                keep.append(p)
        self.list = keep

    # ------------------------------------------------------------------ what did it hit?
    def _collide(self, p, ox, oy):
        sim, w = self.sim, self.sim.w
        x, y = p[0], p[1]
        r = 0.45 if p[7] != "rocket" else 0.7
        for q in sim.peds.list:
            if q.mode not in ("dead", "air") and abs(q.x - x) < 1 and abs(q.y - y) < 1 and (q.x - x) ** 2 + (q.y - y) ** 2 < r * r:
                return self._impact(p, "ped", q, x, y)
        for b in sim.bodies:
            if b is sim.car and sim.mode == "car":
                continue
            if abs(b.x - x) < 6 and abs(b.y - y) < 6:
                L, Wd = vehicles.CIRC[b.kind][0], vehicles.CIRC[b.kind][1]
                fx, fy = math.cos(b.h), math.sin(b.h)
                lx, ly = (x - b.x) * fx + (y - b.y) * fy, -(x - b.x) * fy + (y - b.y) * fx
                if abs(lx) < L + 0.4 and abs(ly) < Wd + 0.1:
                    return self._impact(p, "car", b, x, y)
        for c in sim.traffic.cars:
            if abs(c.x - x) < 2.4 and abs(c.y - y) < 2.4 and (c.x - x) ** 2 + (c.y - y) ** 2 < 2.0 ** 2:
                return self._impact(p, "traffic", c, x, y)
        for ax, ay, bx, by in w.edges_near(x, y, 0.3):          # building walls
            if _cross(ox, oy, x, y, ax, ay, bx, by):
                nx, ny = by - ay, -(bx - ax)
                ln = math.hypot(nx, ny) or 1.0
                return self._impact(p, "wall", (nx / ln, ny / ln), x, y)
        for tx, ty, tr, lo, hi in w.points_near(x, y, 1.0):     # trees, posts, lamps
            if lo <= p[8] <= hi and (tx - x) ** 2 + (ty - y) ** 2 < tr * tr:
                return self._impact(p, "tree", None, x, y)
        return False

    def _impact(self, p, what, obj, x, y):
        sim = self.sim
        kind, dmg = p[7], p[6]
        if kind == "rocket":
            sim.blast(x, y)
            self._mark(x, y, p[8], obj if what == "wall" else None, 1.6, 1)
            return True
        fx, fy = p[2], p[3]
        sp = math.hypot(fx, fy) or 1.0
        fx, fy = fx / sp, fy / sp
        pay = 0
        if what == "ped":
            q = obj
            q.hp -= dmg
            q.vx, q.vy = fx * 3, fy * 3
            sim.ev("hit", x=q.x, y=q.y, kick=True)
            pay = PAY["ped"]
            if q.hp <= 0:
                q.mode, q.t = "dead", sim.clear_time()
                sim.stats["peds"] += 1
                sim.ev("ped_shot", x=q.x, y=q.y)
                pay += PAY["kill"]
            else:
                q.mode, q.t = "flee", 4.0
                q.vx, q.vy = fx * 4, fy * 4
        elif what in ("car", "traffic"):
            b = obj
            if what == "traffic":                               # the driver bails out, the car is now a body
                b = sim.traffic.make_body(obj)
                sim.traffic.cars.remove(obj)
                b.empty = True
                sim.bodies.append(b)
                lx, ly = math.sin(b.h), -math.cos(b.h)
                sim.peds.eject(b.x + lx * 2.0, b.y + ly * 2.0, b.h + math.pi / 2, gz=b.az)
            was = b.health
            b.health -= dmg * 0.35
            b.dirty = True
            pay = PAY["car"] + (PAY["wreck"] if was > 0 >= b.health else 0)
            sim.ev("bullet_car", x=x, y=y, nx=-fx, ny=-fy)
        elif what == "wall":
            pay = PAY["wall"]
            self._mark(x, y, p[8], obj, 0.18, 0)
            sim.ev("bullet_wall", x=x, y=y, nx=obj[0], ny=obj[1])
        elif what == "tree":
            pay = PAY["tree"]
            sim.ev("bullet_tree", x=x, y=y)
        else:
            sim.ev("bullet_ground", x=x, y=y)
        if pay:
            sim.money += pay
            sim.ev("pay", x=x, y=y, amount=pay)
        return True

    def _mark(self, x, y, z, n, size, dark):
        if n is None:
            return
        self.marks.append((x - n[0] * 0.05, y - n[1] * 0.05, z, n[0], n[1], size, dark))
        if len(self.marks) > MARKS_MAX:
            del self.marks[: len(self.marks) - MARKS_MAX]


def _cross(x1, y1, x2, y2, x3, y3, x4, y4):
    """Do segments 1-2 and 3-4 intersect?"""
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return False
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return 0 <= t <= 1 and 0 <= u <= 1
