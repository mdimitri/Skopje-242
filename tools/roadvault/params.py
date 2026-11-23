"""Parameter registry: every tunable scalar of the vault, by group, with default and type.
    python tools/roadvault/params.py [out.json]   -> counts + params.json"""
import dataclasses
import json
import sys

import elements
import engine
import lanes
import slips

GROUPS = {
    "arm": engine.Arm, "lane": lanes.Lane, "slip": slips.Slip, "ring": engine.Ring, "scene": engine.Scene,
}
SKIP = {"arms", "ring", "grades", "elements", "lanes_in", "lanes_out", "slip", "arcs", "e", "name"}


def fields_of(cls):
    out = []
    for f in dataclasses.fields(cls):
        if f.name in SKIP:
            continue
        d = f.default if f.default is not dataclasses.MISSING else None
        out.append(dict(name=f.name, default=d if isinstance(d, (int, float, str, bool, type(None))) else str(d), type=type(d).__name__))
    return out


def grade_params():
    import grade
    import inspect
    sig = inspect.signature(grade.ribbon)
    return [dict(name=k, default=v.default if v.default is not inspect._empty else None) for k, v in sig.parameters.items()]


def element_params():
    keys = {"d0", "d1", "step", "side", "off"}
    n = 0
    names = []
    for eid, row in elements.EL.items():
        ks = set(row["p"]) | set(row["lay"])
        for k in ks:
            names.append(f"{eid}.{k}")
    return names


def registry(max_arms=8, lanes_per_side=8):
    """Parameter slots in the largest scene the schema allows."""
    reg = {}
    arm = fields_of(engine.Arm)
    lane = fields_of(lanes.Lane)
    slip = fields_of(slips.Slip)
    # arcs: 4 segments x (start, length, radius) per arm; 'width keys': 6 (d, w) pairs per lane
    arcs_per_arm = 4 * 3
    keys_per_lane = 6 * 2
    per_arm = len(arm) + arcs_per_arm
    per_lane = len(lane) + keys_per_lane
    reg["scene"] = len(fields_of(engine.Scene))
    reg["ring"] = len(fields_of(engine.Ring))
    reg["arm (x%d)" % max_arms] = per_arm * max_arms
    reg["lane (x%d arms x %d inbound + %d outbound)" % (max_arms, lanes_per_side, lanes_per_side)] = per_lane * 2 * lanes_per_side * max_arms
    reg["slip (x%d)" % max_arms] = len(slip) * max_arms
    reg["grade crossings (x4)"] = len(grade_params()) * 4
    reg["elements (%d element rows)" % len(elements.EL)] = len(element_params())
    return reg


if __name__ == "__main__":
    reg = registry()
    for k, v in reg.items():
        print(f"{v:6d}  {k}")
    print("total", sum(reg.values()))
    json.dump(dict(arm=fields_of(engine.Arm), lane=fields_of(lanes.Lane), slip=fields_of(slips.Slip), ring=fields_of(engine.Ring), scene=fields_of(engine.Scene),
                   grade=grade_params(), elements=element_params(), counts=reg), open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/params.json", "w"), indent=1, default=str)
