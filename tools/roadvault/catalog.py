"""The vault catalogue: 100 common road / junction types.  Every template is a function of keyword parameters (lane counts,
widths, medians, flares, pockets, slip lanes, crossings, signals, signs, angles, ring size ...) returning a Scene; the
numbers below are the defaults of that type and every one can be overridden:  catalog.make("X4_signal_2x2", lanes_main=3)."""
import dataclasses
import json
import math

from engine import Arm, Ring, Scene


def A(angle, **k):
    return Arm(angle, **k)


# ---------------------------------------------------------------- parameterised families
def straight(title, lanes=1, median="none", med_w=None, bike=False, bus=False, parking=False, oneway=False, trees=True,
             crossing=None, signal=False, paint=False, **kw):
    kd = dict(lin=lanes, lout=0 if oneway else lanes, median=("paint" if paint else median), med_w=med_w, bike=bike, bus=bus, parking=parking, trees=trees)
    a = A(180, zebra=None, **kd)
    b = A(0, zebra=crossing, signal=signal, **kd)
    if crossing is not None:
        b.zebra = crossing
    return Scene(title, [a, b], **kw)


def tee(title, main=2, minor=1, main_median="none", minor_median="none", signal=False, sign=None, slip=None, slip_both=False,
        flare=0, pocket=0, angle=90, bike=False, bus=False, zebras=True, parking=False, minor_oneway=False, med_w=None, **kw):
    z = 5.5 if zebras else None
    arms = [A(180, lin=main, lout=main, median=main_median, med_w=med_w, signal=signal, flare_in=flare, pocket=pocket, bike=bike, bus=bus, zebra=z, parking=parking),
            A(0, lin=main, lout=main, median=main_median, med_w=med_w, signal=signal, flare_in=flare, pocket=pocket, bike=bike, bus=bus, zebra=z, parking=parking),
            A(angle, lin=minor, lout=0 if minor_oneway else minor, median=minor_median, signal=signal, sign=None if signal else sign, flare_in=1 if (flare and minor < 3) else 0,
              bike=bike, zebra=z, stop="yield" if sign == "yield" else "line")]
    if slip:
        arms[0].slip = dict(slip)
        if slip_both:
            arms[2].slip = dict(slip)
    return Scene(title, arms, **kw)


def cross(title, main=2, minor=1, main_median="none", minor_median="none", signal=False, sign=None, slips=(), flare=0, pocket=0,
          flare_minor=0, pocket_minor=0, angle=90, bike=False, bus=False, zebras=True, parking=False, oneway=False, corner_r=5.0, slip_R=26.0,
          med_w=None, tram=False, **kw):
    z = 5.5 if zebras else None
    mm = "tram" if tram else main_median
    arms = [A(180, lin=main, lout=main, median=mm, med_w=med_w, signal=signal, flare_in=flare, pocket=pocket, bike=bike, bus=bus, zebra=z, parking=parking),
            A(0, lin=main, lout=main, median=mm, med_w=med_w, signal=signal, flare_in=flare, pocket=pocket, bike=bike, bus=bus, zebra=z, parking=parking),
            A(90 + (angle - 90), lin=minor, lout=0 if oneway else minor, median=minor_median, signal=signal, sign=None if signal else sign, flare_in=flare_minor, pocket=pocket_minor, bike=bike, zebra=z,
              stop="yield" if sign == "yield" else "line", parking=parking),
            A(270 + (angle - 90), lin=0 if oneway else minor, lout=minor, median=minor_median, signal=signal, sign=None if signal else sign, flare_in=flare_minor, pocket=pocket_minor, bike=bike, zebra=z,
              stop="yield" if sign == "yield" else "line", parking=parking)]
    if oneway:
        arms[3].lin, arms[3].lout = minor, minor     # one-way minor streets: keep both, flip below
        arms[2].lout, arms[3].lin = 0, 0
    for k in slips:
        arms[k].slip = {"R": slip_R}
    return Scene(title, arms, corner_r=corner_r, **kw)


def star(title, n=5, lanes=(1,), angles=None, signal=False, slip=None, median="none", flare=0, **kw):
    angles = angles or [i * 360.0 / n for i in range(n)]
    arms = []
    for i, ang in enumerate(angles):
        l = lanes[i % len(lanes)]
        arms.append(A(ang, lin=l, lout=l, signal=signal, median=median if l > 1 else "none", flare_in=flare if l > 1 else 0,
                      sign=None if signal else "priority", L=200))
    return Scene(title, arms, corner_r=kw.pop("corner_r", 6.0), **kw)


def roundabout(title, n=4, lanes=1, entry=1, ro=None, ri=None, center="trees", splitter=3.0, approach_lanes=1, signal=False,
               slips=(), zebra=6.5, bike=False, angles=None, offset=45.0, flare_len=30.0, **kw):
    ring = Ring(ro=ro or (18.0 + 4.0 * (lanes - 1)), ri=ri or (10.0 + 2.5 * (lanes - 1)), lanes=lanes, center=center)
    angles = angles or [offset + i * 360.0 / n for i in range(n)]
    arms = []
    for i, ang in enumerate(angles):
        arms.append(A(ang, lin=approach_lanes, lout=approach_lanes, flare_in=entry if entry != approach_lanes else 0, flare_len=flare_len, taper=14,
                      median="raised" if splitter else "none", med_w=splitter, stop="yield", zebra=zebra, signal=signal, bike=bike,
                      arrows=[]))
        if i in slips:
            arms[-1].slip = {"R": 24.0}
    return Scene(title, arms, ring=ring, corner_r=9.0, **kw)


def grade(title, kind, angle=90, ground_lanes=2, ground_median="raised", lanes=2, median=2.0, h=6.4, span=None, **kw):
    span = span or (ground_lanes * 3.25 + (3.0 if ground_median != "none" else 0) + 6.0 + 4)
    arms = [A(180, lin=ground_lanes, lout=ground_lanes, median=ground_median, zebra=None, signal=False),
            A(0, lin=ground_lanes, lout=ground_lanes, median=ground_median, zebra=None)]
    g = dict(angle=angle, kind=kind, lanes=lanes, median=median, h=h, span=span)
    g.update({k: v for k, v in kw.items() if k in ("ramp", "oneway", "walk", "offset")})
    return Scene(title, arms, grades=[g], corner_r=2.0)


def lane_change(title, a_in, b_in, at=70.0, med="none", **kw):
    """Straight road whose lane count changes along the way (taper = lane gain/drop)."""
    return Scene(title, [A(180, lin=a_in, lout=a_in, taper_in=0, median=med, zebra=None),
                         A(0, lin=min(a_in, b_in), lout=min(a_in, b_in), taper_in=abs(b_in - a_in) * (1 if b_in > a_in else -1), taper_at=at, median=med, zebra=None)], **kw)


# ---------------------------------------------------------------- the list of 100
def _list():
    C = []
    add = lambda id, fn, **k: C.append((id, fn, k))
    # straights and mid-block crossings (18)
    add("S01_residential_1x1", straight, lanes=1)
    add("S02_residential_parking", straight, lanes=1, parking=True)
    add("S03_collector_bike_lanes", straight, lanes=1, bike=True)
    add("S04_collector_bike_parking", straight, lanes=1, bike=True, parking=True)
    add("S05_avenue_2x2", straight, lanes=2)
    add("S06_avenue_2x2_median", straight, lanes=2, median="raised")
    add("S07_avenue_bus_bike", straight, lanes=2, median="raised", bus=True, bike=True)
    add("S08_boulevard_3x3_green", straight, lanes=3, median="grass")
    add("S09_boulevard_3x3_tram", straight, lanes=3, median="tram")
    add("S10_boulevard_4x4_bike", straight, lanes=4, median="grass", bike=True)
    add("S11_oneway_2", straight, lanes=2, oneway=True)
    add("S12_oneway_3_parking", straight, lanes=3, oneway=True, parking=True)
    add("S13_street_paint_median", straight, lanes=1, paint=True, med_w=2.4)
    add("S14_avenue_green_parking", straight, lanes=2, median="grass", parking=True)
    add("S15_zebra_1x1", straight, lanes=1, crossing=5.5)
    add("S16_zebra_refuge_2x2", straight, lanes=2, median="raised", crossing=5.5)
    add("S17_signal_crossing_2x2", straight, lanes=2, median="raised", crossing=5.5, signal=True)
    add("S18_zebra_boulevard", straight, lanes=3, median="grass", crossing=5.5)
    # T junctions (14)
    add("T01_priority_1x1", tee, main=1, minor=1, sign="priority", zebras=False)
    add("T02_main_2x2_minor_1x1_zebra", tee, main=2, minor=1, sign="yield")
    add("T03_signal_raised_pocket", tee, main=2, minor=1, main_median="raised", signal=True, pocket=1, flare=1)
    add("T04_signal_slip_right", tee, main=2, minor=1, main_median="raised", signal=True, slip={"R": 26})
    add("T05_boulevard_3x3_minor_2x2", tee, main=3, minor=2, main_median="grass", signal=True, flare=1, pocket=1)
    add("T06_two_slips", tee, main=2, minor=2, main_median="raised", signal=True, slip={"R": 26}, slip_both=True)
    add("T07_skew_60", tee, main=1, minor=1, sign="priority", angle=60, zebras=False)
    add("T08_Y_45", tee, main=2, minor=1, main_median="raised", signal=True, angle=45, zebras=False, corner_r=6.0)
    add("T09_oneway_minor", tee, main=2, minor=2, main_median="raised", signal=True, minor_oneway=True)
    add("T10_bike_lanes", tee, main=1, minor=1, bike=True, sign="priority")
    add("T11_tram_boulevard", tee, main=2, minor=1, main_median="tram", signal=True)
    add("T12_flared_3_lane", tee, main=2, minor=1, main_median="raised", signal=True, flare=1, pocket=1, med_w=5.0)
    add("T13_splitter_island_stop", tee, main=2, minor=1, main_median="raised", minor_median="raised", sign="stop")
    add("T14_bus_lanes", tee, main=2, minor=1, main_median="raised", signal=True, bus=True, bike=True)
    # X crossings (20)
    add("X01_priority_1x1", cross, main=1, minor=1, sign="priority", zebras=False)
    add("X02_yield_1x1_zebra", cross, main=1, minor=1, sign="yield")
    add("X03_signal_2x2_x_1x1", cross, main=2, minor=1, signal=True, main_median="raised", pocket=1, flare=1)
    add("X04_signal_2x2_x_2x2", cross, main=2, minor=2, signal=True, main_median="raised", minor_median="raised", pocket=1, pocket_minor=1, flare=1, flare_minor=1)
    add("X05_boulevard_3x3_x_2x2", cross, main=3, minor=2, signal=True, main_median="grass", minor_median="raised", pocket=1, flare=1, flare_minor=1)
    add("X06_four_slips", cross, main=2, minor=2, signal=True, main_median="raised", minor_median="raised", slips=(0, 1, 2, 3))
    add("X07_two_slips_opposite", cross, main=2, minor=1, signal=True, main_median="raised", slips=(0, 1))
    add("X08_skew_70", cross, main=2, minor=1, signal=True, main_median="raised", angle=70)
    add("X09_skew_75_priority", cross, main=1, minor=1, sign="priority", angle=75, zebras=False)
    add("X10_oneway_grid", cross, main=2, minor=2, signal=True, oneway=True)
    add("X11_bike_bus", cross, main=2, minor=1, signal=True, main_median="raised", bike=True, bus=True)
    add("X12_tram_x_street", cross, main=2, minor=1, signal=True, tram=True)
    add("X13_double_flare", cross, main=2, minor=1, signal=True, main_median="raised", flare=2, pocket=1, med_w=5.0)
    add("X14_refuge_no_signal", cross, main=2, minor=1, main_median="raised", sign="yield")
    add("X15_boulevard_x_boulevard", cross, main=3, minor=3, signal=True, main_median="grass", minor_median="grass", pocket=1, pocket_minor=1, flare=1, flare_minor=1, med_w=7.0)
    add("X16_parking_streets", cross, main=1, minor=1, sign="priority", parking=True, zebras=False)
    add("X17_zebras_1x1_signal", cross, main=1, minor=1, signal=True)
    add("X18_signal_2x2_two_slips_minor", cross, main=2, minor=2, signal=True, main_median="raised", minor_median="raised", slips=(2, 3))
    add("X19_pockets_both", cross, main=2, minor=2, signal=True, main_median="raised", minor_median="raised", pocket=1, pocket_minor=1)
    add("X20_large_corner_radius", cross, main=2, minor=1, signal=True, main_median="raised", corner_r=9.0)
    # multi-arm (8)
    add("M01_star_5_priority", star, n=5, lanes=(1,))
    add("M02_star_5_two_collectors", star, n=5, lanes=(2, 1, 1, 2, 1), median="raised")
    add("M03_star_6", star, n=6, lanes=(1,))
    add("M04_Y_120", star, n=3, lanes=(2,), median="raised", signal=True)
    add("M05_five_arm_signal", star, n=5, lanes=(2, 1, 2, 1, 1), median="raised", signal=True, flare=1)
    add("M06_X_plus_diagonal", star, n=5, angles=[0, 90, 180, 270, 45], lanes=(2, 1, 2, 1, 1), median="raised", signal=True)
    add("M07_scissors_5", star, n=5, angles=[0, 72, 180, 252, 300], lanes=(1,))
    add("M08_Y_75_narrow", star, n=3, angles=[180, 20, 340], lanes=(2, 1, 1), median="raised", signal=True, corner_r=7.0)
    # roundabouts (16)
    add("R01_compact_3arm", roundabout, n=3, lanes=1, offset=30)
    add("R02_1lane_4arm_trees", roundabout, n=4)
    add("R03_1lane_monument", roundabout, n=4, center="monument", ro=21, ri=12)
    add("R04_2lane_4arm", roundabout, n=4, lanes=2, entry=2, approach_lanes=2, splitter=3.5)
    add("R05_2lane_fountain", roundabout, n=4, lanes=2, entry=2, approach_lanes=2, center="fountain", ro=26, ri=14)
    add("R06_2lane_5arm", roundabout, n=5, lanes=2, entry=2, approach_lanes=1, ro=27, ri=14)
    add("R07_2lane_3arm", roundabout, n=3, lanes=2, entry=2, approach_lanes=2, offset=210)
    add("R08_mini_plain", roundabout, n=4, lanes=1, ro=12.5, ri=3.4, center="plain", splitter=0, zebra=5.5)
    add("R09_flared_entries", roundabout, n=4, lanes=1, entry=2, approach_lanes=1, ro=21, ri=11)
    add("R10_1lane_slip_bypass", roundabout, n=4, lanes=1, slips=(0, 2))
    add("R11_2lane_four_bypass", roundabout, n=4, lanes=2, entry=2, approach_lanes=2, slips=(0, 1, 2, 3), ro=26, ri=14)
    add("R12_large_3lane_6arm", roundabout, n=6, lanes=3, entry=3, approach_lanes=2, ro=34, ri=18)
    add("R13_bike_lanes", roundabout, n=4, lanes=1, bike=True)
    add("R14_far_zebras", roundabout, n=4, lanes=1, zebra=12.0)
    add("R15_signalised_approaches", roundabout, n=4, lanes=2, entry=2, approach_lanes=2, signal=True, ro=26, ri=14, zebra=10.0)
    add("R16_boulevard_roundabout", roundabout, n=4, lanes=2, entry=3, approach_lanes=3, ro=30, ri=16, center="fountain")
    # grade separation (14)
    add("G01_overpass_2lane_over_street", grade, kind="over", ground_lanes=1, ground_median="none", lanes=1, median=0.0, h=6.2)
    add("G02_overpass_2x2_over_avenue", grade, kind="over", ground_lanes=2, lanes=2)
    add("G03_overpass_3x3_over_avenue", grade, kind="over", ground_lanes=2, lanes=3, h=6.6)
    add("G04_underpass_2x2_under_avenue", grade, kind="under", ground_lanes=2, lanes=2)
    add("G05_underpass_3x3", grade, kind="under", ground_lanes=2, lanes=3, h=5.8)
    add("G06_overpass_skew_60", grade, kind="over", angle=60, ground_lanes=2, lanes=2)
    add("G07_overpass_over_tram_boulevard", grade, kind="over", ground_lanes=2, ground_median="tram", lanes=2, h=7.0)
    add("G08_underpass_skew_55", grade, kind="under", angle=55, ground_lanes=2, lanes=2)
    add("G09_oneway_overpass", grade, kind="over", ground_lanes=2, lanes=3, median=0.0, oneway=True)
    add("G10_bridge_over_boulevard", grade, kind="over", ground_lanes=3, ground_median="grass", lanes=2, h=7.0)
    add("G11_underpass_1x1", grade, kind="under", ground_lanes=1, ground_median="none", lanes=1, median=0.0, h=5.0)
    add("G12_overpass_wide_median", grade, kind="over", ground_lanes=2, lanes=2, median=6.0)
    add("G13_overpass_30", grade, kind="over", angle=30, ground_lanes=2, lanes=2)
    add("G14_underpass_45", grade, kind="under", angle=45, ground_lanes=1, ground_median="none", lanes=2)
    # lane changes (6)
    add("L01_lane_gain_2_to_3", lane_change, a_in=2, b_in=3)
    add("L02_lane_drop_3_to_2", lane_change, a_in=3, b_in=2)
    add("L03_lane_gain_1_to_2", lane_change, a_in=1, b_in=2)
    add("L04_lane_drop_2_to_1", lane_change, a_in=2, b_in=1)
    add("L05_gain_median", lane_change, a_in=2, b_in=3, med="raised")
    add("L06_drop_median", lane_change, a_in=3, b_in=2, med="raised")
    # extra hybrids (4)
    add("H01_T_roundabout_3arm_1lane_big", roundabout, n=3, lanes=1, ro=24, ri=14, offset=0)
    add("H02_X_signal_slip_bike", cross, main=2, minor=1, signal=True, main_median="raised", bike=True, slips=(0,))
    add("H03_T_boulevard_slip", tee, main=3, minor=1, main_median="grass", signal=True, slip={"R": 30})
    add("H04_X_boulevard_tram_pockets", cross, main=2, minor=2, signal=True, tram=True, minor_median="raised", pocket_minor=1)
    return C


CATALOG = _list()
IDS = [c[0] for c in CATALOG]


def make(id, **over):
    for cid, fn, k in CATALOG:
        if cid == id:
            kk = dict(k)
            kk.update(over)
            sc = fn(cid, **kk)
            return sc
    raise KeyError(id)


def spec(sc):
    """JSON-able description of a scene: every arm / ring / grade field with its value."""
    return {"name": sc.name, "corner_r": sc.corner_r, "arms": [dataclasses.asdict(a) for a in sc.arms],
            "ring": dataclasses.asdict(sc.ring) if sc.ring else None, "grades": sc.grades}


def from_spec(d):
    arms = [Arm(**a) for a in d["arms"]]
    return Scene(d["name"], arms, ring=Ring(**d["ring"]) if d["ring"] else None, corner_r=d["corner_r"], grades=d["grades"])


if __name__ == "__main__":
    print(len(CATALOG))
