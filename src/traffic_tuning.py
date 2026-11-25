"""Traffic tuning made in the traffic lab (trafficSimulator.bat), applied to the real game.

The lab writes traffic_tuning.json in the game folder ("Apply to game").  The game and its traffic worker process
(trafficproc.py) call startup() and signals_for() when they load, so the game drives with exactly what the lab tested.
The lab itself uses these same functions for every run: there is one implementation, so lab and game cannot differ.

File format (only what differs from the game's defaults is written):
  {"constants": {"actors.Traffic.WAIT": {"scale": 1.5}, "signals.GREEN": {"set": 28.0}, ...},
   "mix": {"trucks": 0.5, ...},                        # vehicles.TRAFFIC_W scale per vehicle style group
   "edge_speed": {"primary": 1.1, ...},                # speed-limit scale per road class
   "closures": [[x, y], ...],                          # closed roads: the drivable edge whose midpoint is nearest (< 12 m)
   "junctions": [{"x": .., "y": .., "off": false, "offset": 0.0, "green": 24.0, "cycle": 50.0}, ...],   # nearest lit junction (< 30 m)
   "signals_on": true, "preempt": true}
Coordinates, not edge / node numbers, so a tuning survives a world rebuild.  Delete the file to go back to the defaults."""
import importlib
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PATH = os.environ.get("SK242_TUNING") or os.path.join(ROOT, "traffic_tuning.json")
MIX = {"cars": ("hatch", "sedan", "wagon", "suv", "mini", "taxi", "limo"), "vans": ("van", "pickup"),
       "trucks": ("truck", "tractor"), "buses": ("bus",)}


def load(path=None):
    p = path or PATH
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(t, path=None):
    with open(path or PATH, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False, indent=1)


def _resolve(target):
    parts = target.split(".")
    obj = importlib.import_module(parts[0])
    for name in parts[1:-1]:
        obj = getattr(obj, name)
    return obj, parts[-1]


def apply_constants(t):
    """Set the game constants of tuning t.  Returns what to hand to restore() to put them back."""
    import vehicles
    saved = []
    for target, how in (t.get("constants") or {}).items():
        obj, name = _resolve(target)
        orig = getattr(obj, name)
        saved.append((obj, name, orig))
        if "scale" in how:
            v = how["scale"]
            new = tuple(x * v for x in orig) if isinstance(orig, tuple) else orig * v
        else:
            v = how["set"]
            new = type(orig)(v) if isinstance(orig, (int, float)) and not isinstance(orig, bool) else v
        setattr(obj, name, new)
    mix = t.get("mix") or {}
    if mix:
        saved.append((vehicles, "TRAFFIC_W", vehicles.TRAFFIC_W))
        scale = {st: mix.get(g, 1.0) for g, styles in MIX.items() for st in styles}
        new = [w * scale.get(vehicles.STYLE[i], 1.0) for i, w in enumerate(vehicles.TRAFFIC_W)]
        if any(new):
            vehicles.TRAFFIC_W = new
    return saved


def restore(saved):
    for obj, name, orig in reversed(saved):
        setattr(obj, name, orig)


def _nearest_edge(world, x, y, r=12.0):
    best, bd = None, r * r
    for ei, e in enumerate(world.edges):
        if not e["drive"]:
            continue
        pts = e["pts"]
        mx, my = pts[len(pts) // 2] if len(pts) > 2 else ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2)
        d = (mx - x) ** 2 + (my - y) ** 2
        if d < bd:
            best, bd = ei, d
    return best


def edge_mid(world, ei):
    pts = world.edges[ei]["pts"]
    if len(pts) > 2:
        return tuple(pts[len(pts) // 2])
    return (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2


def closed_edges(world, t):
    out = set()
    for x, y in t.get("closures") or ():
        ei = _nearest_edge(world, x, y)
        if ei is not None:
            out.add(ei)
    return out


def apply_world(world, t):
    """Speed-limit scales and road closures on the loaded world.  Returns an undo function."""
    speed0 = [e["speed"] for e in world.edges]
    sc = t.get("edge_speed") or {}
    if sc:
        for e in world.edges:
            e["speed"] = e["speed"] * sc.get(e["cls"].replace("_link", ""), 1.0)
    closed = closed_edges(world, t)
    out0 = cells0 = None
    if closed:
        out0 = {n: list(v) for n, v in world.out.items()}
        for lst in world.out.values():
            lst[:] = [(ei, d) for ei, d in lst if ei not in closed]
        cells = getattr(world, "drive_cells", None)
        if cells is not None:
            cells0 = {k: list(v) for k, v in cells.items()}
            for lst in cells.values():
                lst[:] = [ei for ei in lst if ei not in closed]

    def undo():
        for e, s in zip(world.edges, speed0):
            e["speed"] = s
        if out0 is not None:
            for n, lst in out0.items():
                world.out[n][:] = lst
        if cells0 is not None:
            for k, lst in cells0.items():
                world.drive_cells[k][:] = lst
    return undo


def make_signals_class():
    import signals

    class TunedSignals(signals.Signals):
        """The game's signals with per-junction changes: lights off, an offset, an own cycle / major green (the game's
        own state() runs with those values), or every light off."""

        def __init__(self, world, t=None):
            super().__init__(world)
            t = t or {}
            self.all_off = not t.get("signals_on", True)
            self.ov = {}
            for j in t.get("junctions") or ():
                node = self.node_near(j["x"], j["y"])
                if node is None:
                    continue
                for n in self.nodes:                    # the whole crossing (its nodes switch together) gets the change
                    if self.anchor.get(n) == self.anchor.get(node):
                        self.ov[n] = j
            if not t.get("preempt", True):
                self.preempt = lambda *a, **k: None

        def node_near(self, x, y, r=30.0):
            best, bd = None, r * r
            for n, ((jx, jy), _idx) in self.nodes.items():
                d = (jx - x) ** 2 + (jy - y) ** 2
                if d < bd:
                    best, bd = n, d
            return best

        def state(self, i):
            node = self.items[i][0]
            if node in self.candidate_groups:
                return super().state(i)
            ov = self.ov.get(node)
            if not ov:
                return super().state(i)
            saved = signals.GREEN, signals.CYCLE, self.t
            signals.GREEN = ov.get("green", signals.GREEN)
            signals.CYCLE = max(signals.GREEN + 2 * (signals.YELLOW + signals.CLEAR) + 4.0, ov.get("cycle", signals.CYCLE))
            self.t = self.t + ov.get("offset", 0.0)
            try:
                return super().state(i)
            finally:
                signals.GREEN, signals.CYCLE, self.t = saved

        def state_of(self, ei, end):
            i = self.by_edge.get((ei, end))
            if i is None or self.all_off or self.ov.get(self.items[i][0], {}).get("off"):
                return None
            return self.state(i)

        def stop_for(self, ei, end):
            st = self.state_of(ei, end)
            return st is not None and st != 0

    return TunedSignals


# ------------------------------------------------------------------ the game's two hooks (main.py, trafficproc.py)
_T = None


def startup(world, report=print):
    """Called once by the game and by its traffic worker after the world is loaded: apply traffic_tuning.json if any."""
    global _T
    try:
        _T = load()
        if not _T:
            return
        apply_constants(_T)
        apply_world(world, _T)
        report(f"[tuning] traffic_tuning.json applied: {len(_T.get('constants') or {})} constants, "
               f"{len(_T.get('closures') or ())} closed roads, {len(_T.get('junctions') or ())} junction changes")
    except Exception as e:  # noqa: BLE001 - a broken tuning file must never stop the game
        report(f"[tuning] traffic_tuning.json ignored: {e!r}")
        _T = None


def signals_for(world):
    import signals
    if not _T:
        return signals.Signals(world)
    try:
        return make_signals_class()(world, _T)
    except Exception as e:  # noqa: BLE001
        print(f"[tuning] junction changes ignored: {e!r}")
        return signals.Signals(world)

