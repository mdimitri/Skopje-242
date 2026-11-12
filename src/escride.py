"""Fire-escape ride: F at the foot of a fire escape (or at its roof end) carries the player (on foot, or on a bike / scooter)
automatically along the stairs; S / a punch / F again stops the ride on the stairs.  Prompts and markers show where they are."""
import math

import vehicles

SPEED_FOOT, SPEED_BIKE = 4.6, 6.2
REACH = 3.5                                   # how near (m) to the foot / roof end F works
# in-game texts (Macedonian); text/ is a human-edited folder, so they live here
T_UP, T_DOWN, T_STOP = "F — искачи се по пожарните скали", "F — симни се по пожарните скали", "S / F — запри"


def _grid(sim):
    g = getattr(sim, "_esc_grid", None)
    if g is None:
        g = {}
        for s in (getattr(sim.w, "esc", None) or {}).get("stairs", ()):
            if "path" not in s:
                continue
            for e in (s["path"][0], s["path"][-1]):
                g.setdefault((int(e[0] // 64), int(e[1] // 64)), []).append(s)
        sim._esc_grid = g
    return g


def near(sim, x, y, r):
    """Fire escapes with an end within r m of (x, y)."""
    g, out = _grid(sim), []
    for cx in range(int((x - r) // 64), int((x + r) // 64) + 1):
        for cy in range(int((y - r) // 64), int((y + r) // 64) + 1):
            for s in g.get((cx, cy), ()):
                if s not in out:
                    out.append(s)
    return out


def _subject(sim):
    if sim.mode == "car":
        return sim.car if sim.car.kind in vehicles.BIKES else None
    return sim.walker if sim.walker is not None and sim.walker.health > 0 else None


def _find(sim):
    sub = _subject(sim)
    if sub is None or not getattr(sim.w, "esc", None):
        return None
    az = sub.az if sub.az is not None else sim.w.ground_y(sub.x, sub.y)
    best = None
    for s in near(sim, sub.x, sub.y, REACH + 1):
        for end, d in ((0, 1), (-1, -1)):
            x, y, h = s["path"][end]
            dist = math.hypot(x - sub.x, y - sub.y)
            if dist < REACH and abs(h - az) < 1.8 and (best is None or dist < best[0]):
                best = (dist, s, d)
    return best


def start(sim):
    """F pressed: stop a ride in progress, else start one if an end is in reach.  -> True when F was used."""
    if sim.esc is not None:
        sim.esc = None
        return True
    b = _find(sim)
    if b is None:
        return False
    _, s, d = b
    pts = s["path"]
    cum = [0.0]
    for a, c in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(c[0] - a[0], c[1] - a[1], c[2] - a[2]))
    sim.esc = {"pts": pts, "cum": cum, "s": 0.0 if d == 1 else cum[-1], "dir": d}
    return True


def _at(e, s):
    cum, pts = e["cum"], e["pts"]
    k = 1
    while k < len(cum) - 1 and cum[k] < s:
        k += 1
    t = (s - cum[k - 1]) / max(cum[k] - cum[k - 1], 1e-6)
    a, c = pts[k - 1], pts[k]
    return a[0] + (c[0] - a[0]) * t, a[1] + (c[1] - a[1]) * t, a[2] + (c[2] - a[2]) * t, math.atan2(c[1] - a[1], c[0] - a[0])


def tick(sim, dt, inp):
    """Every frame (before the player moves): advance the ride, or work out the prompt.  -> the input to use."""
    e = sim.esc
    sub = _subject(sim)
    if e is not None:
        mv = inp.get("move", (0, 0))
        if sub is None or mv[1] < -0.5 or inp.get("attack") or inp.get("brake"):
            sim.esc = None
            sim.esc_prompt = ""
            return inp
        e["s"] += e["dir"] * (SPEED_BIKE if sim.mode == "car" else SPEED_FOOT) * dt
        done = e["s"] <= 0.0 or e["s"] >= e["cum"][-1]
        e["s"] = min(max(e["s"], 0.0), e["cum"][-1])
        x, y, h, hd = _at(e, e["s"])
        if e["dir"] < 0:
            hd += math.pi
        sub.x, sub.y, sub.az, sub.vz = x, y, h - 0.02, 0.0              # a hair below: the surface snaps the feet up
        sub.lx, sub.ly = x, y
        sub.h = hd
        sub.vx = sub.vy = 0.0
        if sim.mode == "car":
            sub.air = False
        else:
            sub.anim += (SPEED_FOOT * dt)
        if done:
            sim.esc = None
        sim.esc_prompt = T_STOP if not done else ""
        return dict(inp, move=(0, 0), attack=False, jump=False, throttle=0, steer=0)
    b = _find(sim)
    sim.esc_prompt = (T_UP if b[2] == 1 else T_DOWN) if b else ""
    return inp
