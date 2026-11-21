"""Every knob the lab offers, and how it maps onto the game's own code.

A parameter is either a lab option (how the experiment is run: cars, duration, seeds, incident rates ...) or a game
constant: a module or class attribute of the game (actors.Traffic.WAIT, signals.GREEN, trains.SPEED ...).  Game
constants are set in place before a run and put back afterwards, so every run drives the real game code with them.
Numeric class constants of actors.Traffic that are not listed here show up on the Advanced tab by themselves, so a
rule another thread adds to the game (a new Traffic.SOMETHING) can be compared in the lab without editing it."""
import math

from traffic_tuning import _resolve, MIX as _MIX

TABS = ("Run", "Drivers", "Junctions", "Signals", "Roads", "Fleet", "Transit", "Emergency", "Advanced")

# style groups for the vehicle mix (vehicles.STYLE)
MIX = _MIX
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service", "living_street")


class P:
    __slots__ = ("key", "tab", "label", "default", "lo", "hi", "step", "help", "target", "how", "kind", "choices")

    def __init__(self, key, tab, label, default, lo=None, hi=None, step=None, help="", target=None, how="set", kind=None, choices=None):
        self.key, self.tab, self.label, self.default = key, tab, label, default
        self.lo, self.hi, self.step, self.help = lo, hi, step, help
        self.target, self.how = target, how            # target "module.attr" or "module.Class.attr"; how: set | scale | lab
        self.kind = kind or ("bool" if isinstance(default, bool) else "choice" if choices else "int" if isinstance(default, int) else "float")
        self.choices = choices


def _lab(key, tab, label, default, lo=None, hi=None, step=None, help="", **kw):
    return P(key, tab, label, default, lo, hi, step, help, None, "lab", **kw)


LIST = [
    # ---- Run: the experiment itself
    _lab("cars", "Run", "AI cars (base)", 140, 0, 2000, 10, "Sim.base_cars: the game keeps base x hour factor (clock.traffic) cars alive around the player"),
    _lab("peds", "Run", "Pedestrians (base)", 60, 0, 1500, 10, "Sim.base_peds, scaled by the hour like the game"),
    _lab("hour", "Run", "Start hour", 11.0, 0.0, 23.9, 0.5, "game clock hour (route choice uses rush hours)"),
    _lab("freeze_clock", "Run", "Freeze the clock", True, help="keep the hour fixed during a run (the game runs a day in 22 min)"),
    _lab("duration", "Run", "Measured seconds", 240, 30, 3600, 30, "simulated seconds that count towards the report"),
    _lab("warm", "Run", "Warm-up seconds", 30, 0, 300, 5, "simulated seconds before measuring (cars spread out first)"),
    _lab("dt", "Run", "Time step (s)", 0.05, 0.02, 0.1, 0.01, "the game steps at 1/20 s"),
    _lab("seeds", "Run", "Batch: seeds per variant", 6, 1, 64, 1, "stochastic repetitions of every variant"),
    _lab("seed0", "Run", "Batch: first seed", 1, 0, 100000, 1, ""),
    _lab("workers", "Run", "Batch: worker processes", 0, 0, 32, 1, "0 = automatic (cores - 1, capped by free memory)"),
    _lab("full_rate", "Run", "Full-rate study area", True, help="every car inside the study area steps every frame (the game steps off-screen cars 1 in 3)"),
    _lab("hide_player", "Run", "Hide the idle player", True, help="the walker is no obstacle for the AI (as in the audit tools)"),

    # ---- Drivers
    P("aggro", "Drivers", "Driver aggression (mood)", 1, 0, 3, 1, "Sim.aggro 0 calm .. 3 furious: patience, jam manoeuvres, fights", "sim.aggro"),
    P("speed_factor", "Drivers", "Max speed / limit", 1.10, 0.6, 1.6, 0.05, "driving.TRAFFIC_SPEED_FACTOR: drivers pace 0.85 .. this x the limit", "actors.TRAFFIC_SPEED_FACTOR"),
    P("wait_scale", "Drivers", "Patience (x WAIT)", 1.0, 0.25, 4.0, 0.05, "actors.Traffic.WAIT: seconds a stopped car waits before trying to get out", "actors.Traffic.WAIT", "scale"),
    P("squeeze_v", "Drivers", "Squeeze speed (m/s)", 3.0, 0.5, 6.0, 0.25, "Traffic.SQUEEZE_V: crawl speed of stuck cars brushing past", "actors.Traffic.SQUEEZE_V"),
    P("lane_v", "Drivers", "Lane change speed (m/s)", 1.3, 0.4, 3.0, 0.1, "Traffic.LANE_V: sideways speed while changing lane", "actors.Traffic.LANE_V"),
    P("lane_hold", "Drivers", "No lane change after junction (m)", 14.0, 0.0, 40.0, 1.0, "Traffic.LANE_HOLD", "actors.Traffic.LANE_HOLD"),
    P("plan_m", "Drivers", "Turn planning horizon (m)", 130.0, 30.0, 300.0, 5.0, "Traffic.PLAN_M: path ahead whose turns pick lanes together", "actors.Traffic.PLAN_M"),
    P("turn_lane", "Drivers", "Turn that wants a turn lane (rad)", 0.5, 0.1, 1.2, 0.05, "Traffic.TURN_LANE", "actors.Traffic.TURN_LANE"),
    P("uturn", "Drivers", "U-turn threshold (rad)", 2.2, 1.6, 3.1, 0.05, "Traffic.UTURN: sharper turns count as U-turns", "actors.Traffic.UTURN"),

    # ---- Junctions
    P("appr", "Junctions", "Approach zone (m)", 24.0, 8.0, 60.0, 1.0, "Traffic.APPR: where cars sort out who goes first", "actors.Traffic.APPR"),
    P("claim_lead", "Junctions", "Claim look-ahead (s)", 1.4, 0.0, 5.0, 0.1, "Traffic.CLAIM_LEAD: extra time to ask for the junction", "actors.Traffic.CLAIM_LEAD"),
    P("clog_min", "Junctions", "Clogged after (game min)", 30.0, 2.0, 120.0, 1.0, "Traffic.CLOG_MIN: no new spawns feed a junction jammed this long", "actors.Traffic.CLOG_MIN"),
    P("stop_buffer", "Junctions", "Stop-line buffer (m)", 3.0, 0.5, 8.0, 0.25, "driving.SIGNAL_STOP_BUFFER (read by the traffic code)", "actors.SIGNAL_STOP_BUFFER"),

    # ---- Signals
    _lab("signals_on", "Signals", "Traffic lights on", True, help="off: every junction runs the unsignalised priority rules"),
    P("cycle", "Signals", "Cycle (s)", 50.0, 20.0, 150.0, 1.0, "signals.CYCLE", "signals.CYCLE"),
    P("green", "Signals", "Major green (s)", 24.0, 5.0, 100.0, 1.0, "signals.GREEN: the minor group gets the rest of the cycle", "signals.GREEN"),
    P("yellow", "Signals", "Yellow (s)", 3.0, 1.0, 6.0, 0.5, "signals.YELLOW", "signals.YELLOW"),
    P("clear", "Signals", "All-red (s)", 1.5, 0.0, 6.0, 0.5, "signals.CLEAR", "signals.CLEAR"),
    P("wave", "Signals", "Green wave speed (m/s)", 12.5, 4.0, 25.0, 0.5, "signals.WAVE: offsets along the east-west axis", "signals.WAVE"),
    _lab("preempt", "Signals", "Sirens turn lights green", True, help="Signals.preempt: emergency vehicles get green ahead"),

    # ---- Roads
    *[P("spd_" + c, "Roads", f"Limit x  {c}", 1.0, 0.3, 2.0, 0.05, f"scales the speed limit of every {c} edge", None, "edge") for c in ROAD_CLASSES],
    _lab("parked_on", "Roads", "Kerb-parked cars", True, help="world.parked: cars parked along the kerb (swerve-around obstacles)"),

    # ---- Fleet
    *[P("mix_" + g, "Fleet", f"Share x  {g}", 1.0, 0.0, 5.0, 0.1, "scales vehicles.TRAFFIC_W of the " + "/".join(s), None, "mix") for g, s in MIX.items()],
    P("heavy_turn", "Fleet", "Large-vehicle steer limit", 1.0, 0.5, 1.5, 0.05, "actors.TURN: turning radius vs the bicycle model (all vehicles)", "actors.TURN", "scale"),

    # ---- Transit
    _lab("buses_on", "Transit", "City buses", True, help="transit.Transit (JSP lines from transit.json)"),
    P("max_buses", "Transit", "Buses in service", 5, 0, 30, 1, "transit.MAX_BUSES", "transit.MAX_BUSES"),
    _lab("trains_on", "Transit", "Trains + level crossings", True, help="trains.Trains: crossings close while a train is near"),
    P("train_speed", "Transit", "Train speed (m/s)", 16.0, 4.0, 40.0, 1.0, "trains.SPEED", "trains.SPEED"),
    P("train_close", "Transit", "Crossing closes within (m)", 140.0, 30.0, 400.0, 10.0, "trains.CLOSE", "trains.CLOSE"),
    P("train_dwell", "Transit", "Station dwell (s)", 20.0, 0.0, 120.0, 5.0, "trains.DWELL", "trains.DWELL"),

    # ---- Emergency
    _lab("amb_rate", "Emergency", "Ambulance calls / hour", 20.0, 0.0, 240.0, 5.0, "a pedestrian in the study area collapses; services.Services sends an ambulance"),
    _lab("fire_rate", "Emergency", "Car fires / hour", 6.0, 0.0, 120.0, 2.0, "a burning wreck appears in a lane (an obstacle) and a fire engine comes"),
    _lab("breakdown_rate", "Emergency", "Breakdowns / hour", 6.0, 0.0, 120.0, 2.0, "a car stops dead in its lane for 'breakdown time' seconds"),
    _lab("breakdown_t", "Emergency", "Breakdown time (s)", 90.0, 10.0, 900.0, 10.0, ""),
    _lab("amb_on", "Emergency", "Ambulances respond", True, help="services.amb_on"),
    _lab("fire_on", "Emergency", "Fire brigade responds", True, help="services.fire_on"),
]
BY_KEY = {p.key: p for p in LIST}


def discover():
    """Numeric constants and on/off rule switches of actors.Traffic not covered above: the Advanced tab."""
    import actors
    known = {p.target for p in LIST if p.target}
    out = []
    for name in sorted(vars(actors.Traffic)):
        v = vars(actors.Traffic)[name]
        if not name.isupper() or f"actors.Traffic.{name}" in known:
            continue
        if isinstance(v, bool):                  # a rule switch (Traffic.CREEP ...): on / off, comparable in batches and explore
            out.append(P("adv_" + name, "Advanced", f"Traffic.{name} (rule on/off)", v, help=f"actors.Traffic.{name}: a rule "
                         "switch found in the game code", target=f"actors.Traffic.{name}"))
            continue
        if not isinstance(v, (int, float)):
            continue
        lo, hi = (0.0, max(1.0, abs(v) * 4)) if v >= 0 else (v * 4, 0.0)
        step = 1 if isinstance(v, int) else (0.01 if abs(v) < 1 else 0.05 if abs(v) < 10 else 0.5)
        out.append(P("adv_" + name, "Advanced", f"Traffic.{name}", v, lo, hi, step, f"actors.Traffic.{name} (found in the game code)",
                     f"actors.Traffic.{name}"))
    return out


def all_params():
    """The registry; defaults of game constants are read from the game itself, so the lab shows the game's current values."""
    if not any(p.tab == "Advanced" for p in LIST):
        for p in LIST:
            if p.how == "set" and p.target and not p.target.startswith("sim."):
                obj, name = _resolve(p.target)
                p.default = getattr(obj, name)
        for p in discover():
            LIST.append(p)
            BY_KEY[p.key] = p
    return LIST


def defaults():
    return {p.key: p.default for p in all_params()}


def clamp(p, v):
    if p.kind == "bool":
        return bool(v)
    if p.kind == "choice":
        return v if v in p.choices else p.default
    v = max(p.lo, min(p.hi, v)) if p.lo is not None else v
    if p.kind == "int":
        return int(round(v))
    return round(v / p.step) * p.step if p.step else v


def tuning(settings, scenario=None):
    """The game tuning (src/traffic_tuning.py format) for these settings: only what differs from the game's defaults.
    The lab runs with exactly this and "Apply to game" writes exactly this."""
    t = {"constants": {}, "mix": {}, "edge_speed": {}, "closures": [], "junctions": [],
         "signals_on": bool(settings.get("signals_on", True)), "preempt": bool(settings.get("preempt", True))}
    for p in all_params():
        v = settings.get(p.key, p.default)
        if v == p.default or (p.kind != "bool" and isinstance(v, (int, float)) and isinstance(p.default, (int, float))
                              and math.isclose(v, p.default)):
            continue
        if p.how in ("set", "scale") and p.target and not p.target.startswith("sim."):
            t["constants"][p.target] = {"scale": v} if p.how == "scale" else {"set": v}
        elif p.how == "mix":
            t["mix"][p.key[4:]] = v
        elif p.how == "edge":
            t["edge_speed"][p.key[4:]] = v
    if scenario:
        t["closures"] = [list(c) for c in scenario.get("closures", ())]
        t["junctions"] = [dict(j) for j in scenario.get("junctions", ())]
    return t


def diff(a, b):
    """Keys whose values differ between two settings dicts (for variant labels)."""
    out = {}
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k, BY_KEY[k].default if k in BY_KEY else None), b.get(k, BY_KEY[k].default if k in BY_KEY else None)
        if isinstance(va, float) and isinstance(vb, float) and math.isclose(va, vb):
            continue
        if va != vb:
            out[k] = (va, vb)
    return out
