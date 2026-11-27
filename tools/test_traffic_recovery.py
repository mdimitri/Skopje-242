"""Headless regression scenarios for the ambient traffic update."""
import math
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from actors import HERO, Body, Car, Ped, Peds, Sim, Traffic, Walker, _corners, _sat, drive, parts, tow, turn_radius_factor
from driving import fastest_route, movement_lanes, turn_angle, turn_lanes
from vehicles import ARTIC_BUS, ARTIC_HINGE, ARTIC_JACK, ARTIC_REAR_AXLE, BUS, DIMS, IDS
from world import World


def road(a, b, start, end, width=7.2, ow=False, **tags):
    length = math.dist(start, end)
    return dict(a=a, b=b, pts=(start, end), cum=(0.0, length), len=length,
                drive=True, ow=ow, w=width, bridge=False, cls="residential", speed=12.0, **tags)


def setup(*edges, signals=()):
    out, nodes = {}, set()
    for i, e in enumerate(edges):
        nodes.update((e["a"], e["b"]))
        out.setdefault(e["a"], []).append((i, 1))
        if not e["ow"]:
            out.setdefault(e["b"], []).append((i, -1))
    world = SimpleNamespace(edges=list(edges), out=out,
                            main=nodes, hilly=False, drive_cells={}, sg=50.0, signals=signals,
                            level=lambda *_, **_kw: 0.0)
    world.edge_point = World.edge_point.__get__(world)
    return Traffic(world, random.Random(13), target=0)


def car(traffic, x, y, direction=1, speed=0.0):
    c = Car()
    c.kind, c.color, c.e, c.d, c.pace, c.v = 0, 0, 0, direction, 1.0, speed
    c.s = x if direction == 1 else traffic.w.edges[0]["len"] - x
    traffic._set_lane(c, traffic.w.edges[0])
    c.x, c.y, c.h = x, y, 0.0 if direction == 1 else math.pi
    traffic.cars.append(c)
    return c


def approach(traffic, ei, s, move, direction=1):
    c = car(traffic, 0.0, 0.0, direction)
    c.e, c.s, c.nxt = ei, s, move
    traffic._set_lane(c, traffic.w.edges[ei])
    c.x, c.y, c.h = traffic._place(c)
    c.turn = turn_angle(traffic.w.edges, (ei, direction), move)
    return c


class TrafficRecoveryTest(unittest.TestCase):
    def step(self, traffic, seconds, bodies=()):
        reversing = set()
        for _ in range(round(seconds * 20)):
            traffic.update(0.05, 70.0, 0.0, bodies, ())
            reversing.update(c for c in traffic.cars if c.rev > 0)
            actors = [*traffic.cars, *bodies]
            for i, a in enumerate(actors):
                for b in actors[i + 1:]:
                    for pa in parts(a):
                        for pb in parts(b):
                            hit = _sat(_corners(*pa), pa[2], _corners(*pb), pb[2])
                            self.assertIsNone(hit, (a.x, a.y, b.x, b.y))
        return reversing

    def test_green_with_blocked_exit_holds_before_crossing_and_then_clears(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, -65), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (210, 0), ow=True, lanes=1))
        tr.signals = SimpleNamespace(by_edge={(0, 1): 0}, stopd={(0, 1): 20.0},
                                     stop_for=lambda *_: False, state_of=lambda *_: 0)
        driver = approach(tr, 0, 67.0, (2, 1))
        blocker = Body(108.0, 0.0, 0.0, 0, 0)
        self.step(tr, 4.0, (blocker,))
        self.assertLess(driver.x + DIMS[0][0] / 2, 80.0)
        for _ in range(140):
            self.step(tr, 0.05)
            if 80.0 < driver.x < 110.0:
                self.assertGreater(driver.v, 0.3)
        self.assertEqual(driver.e, 2)

    def test_straight_car_goes_before_earlier_arriving_opposing_left_turn(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (175, 0), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (210, 0), ow=True, lanes=1),
                   road(1, 4, (100, 0), (100, 65), ow=True, lanes=1))
        turning = approach(tr, 1, 64.0, (3, 1))
        straight = approach(tr, 0, 89.0, (2, 1))
        turning.arr, straight.arr = -1.0, 0.0
        self.step(tr, 0.05)
        self.assertIn(straight, tr.exit_claims)
        self.assertNotIn(turning, tr.exit_claims)

    def test_through_car_does_not_stop_again_when_signal_plane_is_upstream_of_short_edge(self):
        tr = setup(road(0, 1, (90, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, -65), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (210, 0), ow=True, lanes=1))
        tr.signals = SimpleNamespace(by_edge={(0, 1): 0}, stopd={(0, 1): 13.0},
                                     stop_for=lambda *_: False, state_of=lambda *_: 0)
        tr._reserve_exits = lambda _: None  # delayed reservation after crossing an upstream signal plane
        driver = approach(tr, 0, 0.0, (2, 1))
        driver.v = 4.0
        for _ in range(80):
            self.step(tr, 0.05)
            self.assertGreater(driver.v, 0.3)
        self.assertEqual(driver.e, 2)

    def test_turning_lanes_follow_all_marked_arrows(self):
        edge = road(0, 1, (0, 0), (100, 0), 10.5, ow=True, lanes=3,
                    turn=("through;left|through;left;right|through;right", ""))
        tr = setup(edge, road(1, 2, (100, 0), (100, -50), ow=True),
                   road(1, 3, (100, 0), (100, 50), ow=True))
        self.assertEqual(movement_lanes(tr.w, (0, 1), (1, 1), -math.pi / 2), [0, 1])
        self.assertEqual(movement_lanes(tr.w, (0, 1), (2, 1), math.pi / 2), [1, 2])
        edge["turn"] = ("", "")
        self.assertEqual(movement_lanes(tr.w, (0, 1), (1, 1), -math.pi / 2), [0])
        self.assertEqual(movement_lanes(tr.w, (0, 1), (2, 1), math.pi / 2), [2])

    def test_parallel_marked_turns_keep_their_lanes(self):
        for angle, end, markings in ((-math.pi / 2, (100, -50), "left|left|through"),
                                     (math.pi / 2, (100, 50), "through|right|right")):
            edge = road(0, 1, (0, 0), (100, 0), 10.5, ow=True, lanes=3, turn=(markings, ""))
            tr = setup(edge, road(1, 2, (100, 0), end, 7.0, ow=True, lanes=2))
            for lane in movement_lanes(tr.w, (0, 1), (1, 1), angle):
                c = approach(tr, 0, 30.0, (1, 1))
                c.lidx, c.lcd, c.turn = lane, 0.0, angle
                c.lane = tr.lanes_of(edge)[lane]
                tr._lane_for_turn(c, edge, 70.0, 0.05)
                self.assertEqual(c.lidx, lane)
                expected = lane if angle < 0 else lane - 1
                self.assertEqual(tr._exit_lane(c, edge, tr.w.edges[1]), expected)

    def test_two_cars_complete_parallel_turns_without_merging_or_colliding(self):
        for end, markings, lanes in (((100, -100), "left|left|through", (0, 1)),
                                      ((100, 100), "through|right|right", (1, 2))):
            incoming = road(0, 1, (0, 0), (100, 0), 10.5, ow=True, lanes=3, turn=(markings, ""))
            outgoing = road(1, 2, (100, 0), end, 7.0, ow=True, lanes=2)
            tr = setup(incoming, outgoing)
            drivers = []
            for lane in lanes:
                c = approach(tr, 0, 65.0, (1, 1))
                c.lidx, c.v = lane, 5.0
                tr._set_lane(c, incoming)
                c.x, c.y, c.h = tr._place(c)
                drivers.append(c)
            self.step(tr, 8.0)                   # checks actual vehicle boxes every frame
            self.assertEqual([c.e for c in drivers], [1, 1])
            self.assertEqual([c.lidx for c in drivers], [0, 1])
            self.assertTrue(all(c.s > 20.0 for c in drivers))

    def test_pedestrian_reconnects_behind_a_dead_sidewalk(self):
        edge = road(0, 1, (0, 0), (150, 0))
        tr = setup(edge)
        tr.w.pedestrian_ground = lambda x, y: x < 50
        tr.w.edges_near = lambda *_: ()
        crowd = Peds(tr.w, random.Random(1), target=0)
        p = Ped()
        p.e, p.s, p.d, p.side = 0, 50.0, 1, 1
        p.x, p.y = 49.9, 4.6
        self.assertTrue(crowd._recover_walk_route(p, edge))
        self.assertEqual(p.d, -1)
        self.assertLess(p.walk_route[-1][0], 49.0)

    def test_visible_traffic_is_retained_past_the_normal_despawn_radius(self):
        tr = setup(road(0, 1, (0, 0), (900, 0)))
        driver = car(tr, 520.0, 1.8, speed=5.0)
        tr.sim = SimpleNamespace(view_rect=(-10, -20, 640, 20))
        tr.update(0.05, 0.0, 0.0, (), ())
        self.assertIn(driver, tr.cars)
        self.assertGreater(driver.x, 520.0)

    def test_pedestrian_sees_a_turn_before_entering_the_straight_collision_corridor(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.surface = lambda *_: 3
        tr.w.kerb = lambda *_: False
        driver = car(tr, 60, 0, speed=5.0)
        driver.str = 0.5
        crowd = Peds(tr.w, random.Random(1), target=0)
        p = Ped()
        p.x, p.y, p.gz = 63.0, 2.5, 0.0
        self.assertIsNone(crowd._traffic_danger(p, (driver,)))
        crowd.traffic_forecasts = tr.turn_forecasts((driver,))
        self.assertLess(crowd._traffic_danger(p, (driver,))[0], 1.4)

    def test_coordinator_assigns_one_retreat_to_a_head_on_pair(self):
        tr = setup(road(0, 1, (0, 0), (180, 0)))
        east = car(tr, 80.0, 0.0)
        west = car(tr, 85.0, 0.0, -1)
        tr.update(0.05, 80, 0, (), ())
        east.v = west.v = 0.0
        east.stuck = west.stuck = 4.0
        east.blk, west.blk = west, east
        tr._coordinate_jams({(0, 1): [east], (0, -1): [west]})
        self.assertEqual(sum(c.rev > 0 for c in (east, west)), 1)

    def test_coordinator_switches_to_a_clear_legal_approach_lane(self):
        tr = setup(road(0, 1, (0, 0), (150, 0), 7.2, ow=True, lanes=2),
                   road(1, 2, (150, 0), (230, 0), 7.2, ow=True, lanes=2))
        driver = approach(tr, 0, 90, (1, 1))
        first = approach(tr, 0, 98, (1, 1))
        tr.update(0.05, 90, 0, (), ())
        driver.v = first.v = 0.0
        driver.stuck = first.stuck = 4.0
        driver.blk = first
        tr._coordinate_jams({(0, 1): [driver, first]})
        self.assertNotEqual(driver.lidx, first.lidx)
        self.assertEqual(driver.nxt, (1, 1))

    def test_speed_allowance_tops_out_at_ten_percent(self):
        tr = setup(road(0, 1, (0, 0), (250, 0)))
        driver = car(tr, 55.0, 1.8, speed=12.0)
        driver.pace = 1.4
        self.step(tr, 4)
        self.assertAlmostEqual(driver.v, 12.0 * 1.1)

    def test_slip_road_replaces_main_right_turn_and_center_continues(self):
        edges = [
            road(0, 1, (-60, 0), (0, 0), 9, True, lanes=3, turn=("through|none|through;right", "")),
            road(1, 2, (0, 0), (20, 0), 9, True, lanes=3),
            road(2, 3, (20, 0), (20, 28), ow=True),
            road(1, 4, (0, 0), (12, 9), ow=True),
            road(4, 3, (12, 9), (20, 28), ow=True),
            road(2, 5, (20, 0), (120, 0), ow=True),
            road(3, 6, (20, 28), (20, 75), ow=True),
        ]
        edges[3]["cls"] = edges[4]["cls"] = "tertiary_link"
        tr = setup(*edges)
        self.assertEqual(movement_lanes(tr.w, (1, 1), (2, 1), math.pi / 2), [])
        self.assertEqual(movement_lanes(tr.w, (0, 1), (3, 1), turn_angle(edges, (0, 1), (3, 1))), [2])
        self.assertEqual(fastest_route(tr.w, 1, 6, (20, 75), incoming=(0, 1)), ((3, 1), (4, 1), (6, 1)))
        c = approach(tr, 0, 43.0, (3, 1))
        c.lidx = 1
        tr._set_lane(c, edges[0])
        c.x, c.y, c.h = tr._place(c)
        self.assertEqual(tr._choose(c, 0, 1)[0], [(1, 1)])
        self.step(tr, 8)
        self.assertIn(c.e, (1, 5))

    def test_shallow_right_slip_uses_outer_lane(self):
        edges = [road(0, 1, (-60, 0), (0, 0), 9, True, lanes=3),
                 road(1, 2, (0, 0), (80, 0), 9, True, lanes=3),
                 road(1, 3, (0, 0), (60, 6), 4, True, lanes=1)]
        edges[2]["cls"] = "tertiary_link"
        tr = setup(*edges)
        angle = turn_angle(edges, (0, 1), (2, 1))
        self.assertLess(angle, 0.2)
        self.assertEqual(movement_lanes(tr.w, (0, 1), (2, 1), angle), [2])

    def test_no_lane_change_starts_inside_a_junction(self):
        edges = [road(0, 1, (-60, 0), (0, 0), 14, ow=True, lanes=2),
                 road(1, 2, (0, 0), (120, 0), 14, ow=True, lanes=2),
                 road(2, 3, (120, 0), (120, 60), ow=True, lanes=1)]
        tr = setup(*edges)
        tr.junctions[1] = 8.0
        tr.ph, tr.hash = {}, {}
        c = approach(tr, 1, 4.0, (2, 1))
        c.lidx, c.lcd = 0, 0.0
        tr._set_lane(c, edges[1])
        tr._lane_for_turn(c, edges[1], 116.0, 0.05)
        self.assertEqual(c.lidx, 0)                            # just out of the box: it stays in its lane
        c.s, c.lcd = 40.0, 0.0
        tr._lane_for_turn(c, edges[1], 80.0, 0.05)
        self.assertEqual(c.lidx, 1)                            # further on it moves over for the right turn

    def test_left_turn_lanes_do_not_cross_straight_lanes(self):
        e = road(0, 1, (-60, 0), (0, 0), 10.5, True, lanes=3, turn=("left|through|through;right", ""))
        self.assertEqual(turn_lanes(e, 1, 0.0), [1, 2])
        self.assertEqual(turn_lanes(e, 1, 1.5), [2])
        e = road(0, 1, (-60, 0), (0, 0), 10.5, True, lanes=3, turn=("left|through|right", ""))
        self.assertEqual(turn_lanes(e, 1, 0.0), [1])
        e["turn"] = ("through|left|through", "")
        tr = setup(e, road(1, 2, (0, 0), (0, -60), ow=True))
        self.assertEqual(movement_lanes(tr.w, (0, 1), (1, 1), -math.pi / 2), [])

    def test_dead_end_uturn_starts_before_node_from_leftmost_lane(self):
        e = road(0, 1, (0, 0), (100, 0), 12, lanes=4)
        tr = setup(e)
        c = approach(tr, 0, 58.0, (0, -1))
        c.lidx = 1
        tr._set_lane(c, e)
        c.x, c.y, c.h = tr._place(c)
        first_turn = None
        for _ in range(260):
            tr.update(0.05, 75.0, 0.0, (), ())
            if c.turnaround and first_turn is None:
                first_turn = (c.lidx, c.turnaround[0], c.turnaround[3])
            if c.d == -1:
                break
        self.assertIsNotNone(first_turn)
        self.assertEqual(first_turn[0], 0)
        self.assertLess(first_turn[1], 98.0)
        self.assertLess(first_turn[2], 0.0)
        self.assertEqual(c.d, -1)

    def test_major_junction_replans_a_uturn_to_the_forward_exit(self):
        tr = setup(road(0, 1, (0, 0), (80, 0), width=14),
                   road(1, 2, (80, 0), (160, 0), width=14, ow=True),
                   road(1, 3, (80, 0), (80, 60), width=10, ow=True))
        c = approach(tr, 0, 57, (0, -1))
        tr.update(0.05, 72, 0, (), ())
        self.assertLessEqual(abs(c.turn), tr.UTURN)
        self.assertNotEqual(c.nxt, (0, -1))

    def test_blocked_corner_can_clear_via_a_short_exit_connector(self):
        e = road(0, 1, (0, 0), (10, 0), ow=True)
        tr = setup(e, road(1, 2, (10, 0), (10, -30), ow=True),
                   road(1, 3, (10, 0), (14, 0), ow=True), road(3, 4, (14, 0), (60, 0), ow=True))
        tr.internal_links[0] = tr.junction_complex[1] = 1
        tr.ph = {}
        c = approach(tr, 0, 6.0, (1, 1))
        c.stuck = 2.0
        following = Car()
        tr.exit_claims[following] = ((9, 1), 1, [((0, 1, 0), 10), ((2, 1, 0), 4)], 10)
        tr._clear_blocked_corner(c, e, 1)
        self.assertEqual(c.nxt, (2, 1))
        self.assertEqual(c.nx2, [((3, 1), 0.0)])
        self.assertTrue(tr._exit_complete(c, tr._exit_slots(c)))

    def test_blocked_corner_can_retreat_without_reversing_into_an_obstacle(self):
        e = road(0, 1, (0, 0), (16, 0), ow=True)
        tr = setup(e)
        tr.w.surface, tr.w.kerb = lambda *_: 3, lambda *_: False
        tr.ph = {}
        c = car(tr, 8.0, 0.0)
        obstacle = Body(4, 0, 0, 0, 0)
        tr.hash = {(0, 0): [(4.0, 0.0, 0.9, 2.0, obstacle, 0.0, 0.0)]}
        self.assertFalse(tr._retreat_in_box(c))
        tr.hash.clear()
        self.assertTrue(tr._retreat_in_box(c))
        for _ in range(23):
            tr._back_up(c, e, 2.5, 0.05)
        self.assertLess(c.x, 5.6)
        self.assertFalse(c.rev_box)
        self.assertEqual(c.h, 0.0)

    def test_crash_survivor_keeps_damage_and_honks(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        c = car(tr, 53.0, 0.0)
        ram = Body(50, 0, 0, 0, 0)
        ram.vx = 8.0
        sim = Sim.__new__(Sim)
        sim.traffic, sim.rng, sim.events = tr, random.Random(2), []
        sim.bodies = [ram]
        sim.peds = SimpleNamespace(eject=lambda *_a, **_kw: Ped())
        pokes = []
        def poke(vehicle, attr, value):
            pokes.append(attr)
            setattr(vehicle, attr, value)
        sim.tproc = SimpleNamespace(poke=poke)
        Sim._traffic_crashes(sim)
        self.assertIn(c, tr.cars)
        self.assertGreater(c.health, 50)
        self.assertLess(c.health, 100)
        self.assertEqual(tr.make_body(c).health, c.health)
        self.assertIn("health", pokes)
        self.assertEqual([name for name, _ in sim.events].count("horn"), 1)
        c.x, c.health, ram.x, ram.vx = 53.0, 50.0 + 6.0 * 3.4 / 1.33, 50.0, 8.0
        Sim._traffic_crashes(sim)
        self.assertNotIn(c, tr.cars)
        self.assertAlmostEqual(sim.bodies[-1].health, 50.0)
        self.assertEqual([name for name, _ in sim.events].count("horn"), 1)

    def test_wrong_lane_head_on_clears(self):
        for first in (1, -1):
            with self.subTest(first=first):
                tr = setup(road(0, 1, (0, 0), (150, 0)))
                encroaching = car(tr, 59.0, -1.8)
                oncoming = car(tr, 64.4, -1.8, -1)
                if first == -1:
                    tr.cars.reverse()
                self.step(tr, 7)
                self.assertGreater(encroaching.x, oncoming.x + 10.0)
                self.assertGreater(encroaching.y, 0.8)
                self.assertLess(oncoming.y, -0.8)

    def test_bumper_to_bumper_head_on_uses_reverse(self):
        tr = setup(road(0, 1, (0, 0), (200, 0), 5.6))
        east = car(tr, 79.0, -0.2)
        west = car(tr, 79.0 + DIMS[0][0] + 0.08, 0.2, -1)
        self.assertTrue(self.step(tr, 10))
        self.assertGreater(east.x, west.x + 10)
        self.assertGreater(east.y, 0.8)
        self.assertLess(west.y, -0.8)

    def test_head_on_queue_backs_up_from_the_rear(self):
        tr = setup(road(0, 1, (0, 0), (200, 0), 5.6))
        east = car(tr, 79.0, -0.2)
        follower = car(tr, east.x - DIMS[0][0] - 0.35, east.y)
        west = car(tr, east.x + DIMS[0][0] + 0.08, 0.2, -1)
        self.assertIn(follower, self.step(tr, 12))
        self.assertGreater(east.x, west.x + 10.0)

    def test_free_lane_goes_around_stationary_car(self):
        tr = setup(road(0, 1, (0, 0), (150, 0), 14.0, directional_lanes=(2, 2)))
        driver = car(tr, 51.0, 1.75)
        blocker = Body(57.0, 1.75, 0.0, 0, 0)
        self.step(tr, 13, (blocker,))
        self.assertGreater(driver.x, blocker.x + 8.0)

    def test_driver_borrows_empty_opposing_lane_and_returns(self):
        tr = setup(road(0, 1, (0, 0), (180, 0), 5.6))
        driver = car(tr, 51.0, 1.4)
        blocker = Body(57.0, 1.4, 0.0, 0, 0)
        self.step(tr, 8, (blocker,))
        self.assertLess(driver.y, 0.0)
        self.step(tr, 9, (blocker,))
        self.assertGreater(driver.x, blocker.x + 10.0)
        self.assertGreater(driver.y, 0.8)

    def test_approaching_car_swerves_round_a_wreck_across_the_line(self):
        tr = setup(road(0, 1, (0, 0), (300, 0), 6.6))
        driver = car(tr, 20.0, 1.6, 1, 12.0)
        wreck = Body(110.0, 1.2, 0.0, 0, 0)
        self.step(tr, 17, (wreck,))
        self.assertGreater(driver.x, wreck.x + 6.0)
        self.assertEqual(driver.rev, 0)

    def test_overtaker_waits_for_oncoming_car_then_passes(self):
        tr = setup(road(0, 1, (0, 0), (400, 0), 6.6))
        driver = car(tr, 20.0, 1.6, 1, 10.0)
        oncoming = car(tr, 330.0, -1.6, -1, 12.0)
        wreck = Body(110.0, 1.2, 0.0, 0, 0)
        self.step(tr, 8, (wreck,))
        self.assertLess(driver.x, wreck.x)
        self.step(tr, 30, (wreck,))
        self.assertGreater(driver.x, wreck.x + 6.0)

    def test_borrowing_checks_oncoming_traffic_beyond_the_merge(self):
        e = road(0, 1, (0, 0), (150, 0))
        tr = setup(e)
        driver = car(tr, 48.0, 1.8)
        other = car(tr, 86.0, -1.8, -1, 10.0)
        tr.update(0.05, 70.0, 0.0, (), ())
        self.assertFalse(tr._lane_room(driver, e, -1.8, 38.0, opposing=True))
        tr.cars.remove(other)
        tr.update(0.05, 70.0, 0.0, (), ())
        self.assertTrue(tr._lane_room(driver, e, -1.8, 38.0, opposing=True))

    def test_clear_wide_road_allows_turnaround(self):
        e = road(0, 1, (0, 0), (150, 0), 10.0)
        tr = setup(e)
        driver = car(tr, 70.0, 2.5)
        tr.update(0.05, 70.0, 0.0, (), ())
        self.assertTrue(tr._start_turnaround(driver, e, 2.5))
        self.step(tr, 5)
        self.assertEqual(driver.d, -1)
        self.assertLess(driver.x, 70.0)
        self.assertLess(driver.y, -1.5)

    def test_blocked_exit_changes_route_and_drops_unreachable_goal(self):
        incoming = road(0, 1, (0, 0), (100, 0))
        tr = setup(incoming)
        tr.w.edges.extend((road(1, 2, (100, 0), (175, 0)),
                           road(1, 3, (100, 0), (100, 70))))
        tr.w.main.update((2, 3))
        tr.w.out.update({1: [(0, -1), (1, 1), (2, 1)], 2: [(1, -1)], 3: [(2, -1)]})
        tr.junctions[1] = 3.6
        driver = car(tr, 88.0, 1.8)
        driver.nxt, driver.stuck, driver.goal = (1, 1), 8.0, (2, (175, 0))
        tr.occ[(1, 1, 0)] = [(3.0, 0.0, False)]
        tr._review_turn(driver, incoming, 1, 12.0)
        self.assertEqual(driver.nxt, (2, 1))
        self.assertIsNone(driver.goal)

    def test_red_queue_does_not_start_a_recovery_maneuver(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.signals = SimpleNamespace(state_of=lambda *_: 2, stopd={(0, 1): 10.0})
        driver = car(tr, 120.0, 1.8)
        driver.stuck = 20.0
        blocker = Body(125.0, 1.8, 0.0, 0, 0)
        self.assertFalse(self.step(tr, 8, (blocker,)))
        self.assertLess(driver.x, 134.0)
        self.assertEqual(driver.shift, 0.0)
        self.assertIsNone(driver.turnaround)

    def test_exit_reservation_reaches_past_short_link_and_serializes_merge(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, 75), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (105, 0), ow=True, lanes=1),
                   road(3, 4, (105, 0), (230, 0), ow=True, lanes=1))
        a = approach(tr, 0, 89.0, (2, 1))
        b = approach(tr, 1, 64.0, (2, 1))
        a.nx2 = b.nx2 = [((3, 1), 0.0)]
        blocker = Body(108.0, 0.0, 0.0, 0, 0)
        self.step(tr, 1.5, (blocker,))
        self.assertEqual((a.s, b.s), (89.0, 64.0))
        self.assertFalse(tr.exit_claims)
        self.step(tr, 0.05)
        self.assertEqual(len(tr.exit_claims), 1)
        claim = next(iter(tr.exit_claims))
        self.assertEqual([lane[0] for lane, _ in tr.exit_claims[claim][2]], [2, 3])
        self.step(tr, 10.0)
        self.assertEqual((a.e, b.e), (3, 3))

    def test_follower_on_previous_link_does_not_hold_leader_in_junction(self):
        tr = setup(road(0, 1, (0, 0), (96, 0), ow=True, lanes=1),
                   road(1, 2, (96, 0), (100, 0), ow=True, lanes=1),
                   road(3, 2, (100, -60), (100, 0), ow=True, lanes=1),
                   road(2, 4, (100, 0), (190, 0), ow=True, lanes=1))
        leader = approach(tr, 1, 1.2, (3, 1))
        follower = approach(tr, 0, 91.3, (1, 1))
        self.step(tr, 8)
        self.assertEqual((leader.e, follower.e), (3, 3))

    def test_stationary_priority_traffic_upstream_of_line_leaves_a_gap(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, -80), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (190, 0), ow=True, lanes=1))
        tr.w.edges[1]["cls"] = "primary"
        waiting = approach(tr, 1, 58.0, (2, 1))
        ready = approach(tr, 0, 89.0, (2, 1))
        self.step(tr, 0.05)
        self.assertIn(ready, tr.exit_claims)
        self.assertNotIn(waiting, tr.exit_claims)

    def test_parked_obstacle_before_red_can_be_passed(self):
        tr = setup(road(0, 1, (0, 0), (150, 0), 14.0, directional_lanes=(2, 2)))
        tr.signals = SimpleNamespace(state_of=lambda *_: 2, stopd={(0, 1): 10.0})
        driver = car(tr, 80.0, 1.75)
        blocker = Body(86.0, 1.75, 0.0, 0, 0)
        self.step(tr, 25, (blocker,))
        self.assertGreater(driver.x, 130.0)
        self.assertLess(driver.x, 140.0)
        self.assertAlmostEqual(driver.v, 0.0)

    def test_car_clears_reserved_connector_through_second_junction(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, 75), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (105, 0), ow=True, lanes=1),
                   road(3, 4, (105, 0), (230, 0), ow=True, lanes=1),
                   road(5, 3, (105, -65), (105, 0), ow=True, lanes=1))
        driver = approach(tr, 0, 89.0, (2, 1))
        driver.nx2 = [((3, 1), 0.0)]
        longest_pause = paused = 0
        for _ in range(130):
            tr.update(0.05, 70.0, 0.0, (), ())
            paused = paused + 1 if driver.e == 2 and driver.v < 0.3 else 0
            longest_pause = max(longest_pause, paused)
        self.assertEqual(driver.e, 3)
        self.assertLess(longest_pause, 4)

    def test_divided_intersection_reserves_past_its_whole_median(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), width=14, ow=True, lanes=1),
                   road(2, 1, (100, 70), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (116, 0), width=14, ow=True, lanes=1),
                   road(3, 4, (116, 0), (230, 0), ow=True, lanes=1),
                   road(5, 3, (116, -70), (116, 0), ow=True, lanes=1),
                   signals=((1,), (3,)))
        driver = approach(tr, 0, 89.0, (2, 1))
        driver.nx2 = [((3, 1), 0.0)]
        self.assertIn(2, tr.internal_links)
        blocker = Body(121.0, 0.0, 0.0, 0, 0)
        self.step(tr, 2.0, (blocker,))
        self.assertEqual(driver.e, 0)
        self.assertAlmostEqual(driver.s, 88.875, delta=0.15)
        self.step(tr, 7.0)
        self.assertEqual(driver.e, 3)

    def test_red_stop_line_can_extend_back_across_multiple_links(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(1, 2, (100, 0), (104, 0), ow=True, lanes=1),
                   road(2, 3, (104, 0), (109, 0), ow=True, lanes=1))
        driver = approach(tr, 0, 90.0, (1, 1))
        driver.nx2 = [((2, 1), 0.0)]
        tr.signals = SimpleNamespace(state_of=lambda ei, _: 2 if ei == 2 else None, stopd={(2, 1): 14.0})
        self.step(tr, 2.0)
        self.assertAlmostEqual(driver.s, 90.075, places=3)
        self.assertAlmostEqual(driver.v, 0.0)

    def test_yellow_braking_continues_to_the_buffered_stop(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.signals = SimpleNamespace(state_of=lambda *_: 1, stopd={(0, 1): 10.0})
        driver = car(tr, 134.0, 1.8, speed=2.6)
        self.step(tr, 2.0)
        self.assertLess(driver.x, 136.0)
        self.assertAlmostEqual(driver.v, 0.0)

    def test_parked_car_behind_does_not_brake_open_lane(self):
        tr = setup(road(0, 1, (0, 0), (180, 0)))
        c = car(tr, 52.0, 1.8)
        behind = Body(47.9, 3.6, 0.0, 0, 0)
        self.step(tr, 4.0, (behind,))
        self.assertGreater(c.x, 65.0)

    def test_waiting_cross_traffic_cannot_trigger_motion_forecast(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        c = car(tr, 45.0, 1.8, speed=3.0)
        other = car(tr, 50.0, 3.0)
        other.h = -math.pi / 2
        entry = (other.x, other.y, 0.8, 2.0, other, other.h, 0.0)
        tr.hblk[(0, 0)] = [(3, 0, [entry])]
        self.assertIsNone(tr._cross(c))
        other.v = 1.0
        self.assertIsNotNone(tr._cross(c))

    def test_corner_guidance_looks_ahead_of_short_exit_projection(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(1, 2, (100, 0), (100, 15), ow=True, lanes=1))
        driver = approach(tr, 0, 98.0, (1, 1))
        driver.x, driver.y = 98.0, 4.0
        x, y, _ = tr._corner_target(driver, tr.w.edges[0], 3.0)
        self.assertAlmostEqual(x, 100.0)
        self.assertGreaterEqual(y, driver.y + 3.0)

    def test_turn_indicator_latches_through_the_turn_and_cancels(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(1, 2, (100, 0), (100, 120), ow=True, lanes=1))
        driver = approach(tr, 0, 89.0, (1, 1))
        self.step(tr, 0.05)
        self.assertEqual(driver.indicator, 1)
        for _ in range(200):
            tr.update(0.05, 80.0, 0.0, (), ())
            if driver.e == 1:
                break
        self.assertEqual(driver.e, 1)
        self.assertEqual(driver.indicator, 1)
        self.step(tr, 2.0)
        self.assertEqual(driver.indicator, 0)

    def test_hero_signals_at_low_and_boulevard_speeds(self):
        world = SimpleNamespace(hilly=False, surface=lambda *_: 3)
        for speed, direction in ((0.0, -1), (9.0, 1), (18.0, -1)):
            hero = Body(0.0, 0.0, 0.0, IDS.index("Golf Dvojka"), 0)
            hero.player_car = True
            hero.vx = speed
            for _ in range(8):
                drive(hero, 0.4, direction * 0.65, False, 0.02, world)
            self.assertEqual(hero.indicator, direction)
            for _ in range(75):
                drive(hero, 0.0, 0.0, False, 0.02, world)
            self.assertEqual(hero.indicator, 0)

    def test_all_car_indicator_mounts_stay_on_their_light_cluster_side(self):
        import gl3d
        for kind in range(len(IDS)):
            for end, mount in zip((1, -1), gl3d.indicator_mounts(kind)):
                x, y, z, width, height = mount
                with self.subTest(vehicle=IDS[kind], end=end):
                    self.assertGreater(end * x, 0)
                    self.assertGreater(min(y, z, width, height), 0.0)
                    self.assertLess(z + width * 0.5, gl3d.visual_dims(kind)[1] * 0.6)

    def test_blocked_major_road_yields_the_junction_to_an_open_exit(self):
        tr = setup(road(0, 1, (0, 0), (100, 0), ow=True, lanes=1),
                   road(2, 1, (100, 75), (100, 0), ow=True, lanes=1),
                   road(1, 3, (100, 0), (200, 0), ow=True, lanes=1),
                   road(1, 4, (100, 0), (100, -100), ow=True, lanes=1))
        tr.w.edges[0]["cls"] = "primary"
        major = approach(tr, 0, 89.0, (2, 1))
        cross = approach(tr, 1, 64.0, (3, 1))
        blocker = Body(107.0, 0.0, 0.0, 0, 0)
        self.step(tr, 0.05, (blocker,))
        self.assertEqual(set(tr.exit_claims), {cross})
        self.assertEqual(major.s, 89.0)

    def test_opposite_entries_to_single_file_road_take_turns(self):
        tr = setup(road(0, 1, (0, 0), (70, 0)),
                   road(1, 2, (70, 0), (130, 0), 3.6),
                   road(2, 3, (130, 0), (200, 0)))
        a = approach(tr, 0, 64.0, (1, 1))
        b = approach(tr, 2, 64.0, (1, -1), direction=-1)
        crossed = set()
        for _ in range(420):
            tr.update(0.05, 100.0, 0.0, (), ())
            inside = {c for c in (a, b) if c.e == 1}
            self.assertLessEqual(len(inside), 1)
            crossed.update(inside)
            if len(crossed) == 2:
                break
        self.assertEqual(crossed, {a, b})

    def test_nearest_reachable_pullout_gets_used_before_head_on(self):
        tr = setup(road(0, 1, (0, 0), (150, 0), 3.4, taper=(None, (26.0, 6.6))))
        east = car(tr, 108.0, 1.3)
        west = car(tr, 139.0, -2.0, -1)
        self.step(tr, 0.05)
        self.assertEqual(tr.passing[0][:2], (east, west))
        self.assertLess(tr.passing[0][2] - west.s, 6.0)
        self.assertFalse(self.step(tr, 9.0))
        self.assertGreater(east.x, west.x)

    def test_recent_queue_diverts_upstream_traffic_across_both_detours(self):
        tr = setup(road(0, 1, (0, 0), (100, 0)),
                   road(1, 2, (100, 0), (140, 0)),
                   road(2, 3, (140, 0), (220, 0)),
                   road(1, 4, (100, 0), (135, 35)),
                   road(1, 5, (100, 0), (135, -35)),
                   road(4, 3, (135, 35), (220, 0)),
                   road(5, 3, (135, -35), (220, 0)))
        tr.queue[(2, 1)] = 6
        tr._remember_queues(12.0)
        tr.queue.clear()
        c1 = approach(tr, 0, 45.0, (1, 1))
        c2 = approach(tr, 0, 35.0, (1, 1))
        tr.route_demand[(1, 1)] = 2
        for c in (c1, c2):
            c.nx2 = [((2, 1), 0.0)]
            tr._review_route(c, tr.w.edges[0], 100.0 - c.s)
        self.assertEqual({c1.nxt, c2.nxt}, {(3, 1), (4, 1)})
        tr._remember_queues(45.0)
        self.assertNotIn((2, 1), tr.queue_history)


class PedestrianTrafficTest(unittest.TestCase):
    def test_stopped_traffic_only_checks_pavement_near_the_vehicle_nose(self):
        tr, driver, peds, p = self.clinch()
        driver.v = 0.0
        _, _, _, length, _ = parts(driver)[0]
        reads = []
        tr.w.surface = lambda x, y: reads.append((x, y)) or 3
        tr.w.kerb = lambda *_: True
        p.x = driver.x + length + 8.0
        self.assertIsNone(peds._traffic_danger(p, [driver]))
        self.assertEqual(reads, [])
        p.x = driver.x + length + 1.0
        self.assertIsNone(peds._traffic_danger(p, [driver, driver]))
        self.assertEqual(len(reads), 1)
        tr.w.kerb = lambda *_: False
        self.assertIs(peds._traffic_danger(p, [driver])[5], driver)

    def clinch(self, walls=()):
        tr = setup(road(0, 1, (0, 0), (200, 0)))
        tr.w.kerb = lambda *_: False
        tr.w.surface = lambda *_: 3
        tr.w.on_zebra = lambda *_: True
        tr.w.edges_near = lambda *_: walls
        tr.w.walk_cells = tr.w.walk_out = {}
        driver = car(tr, 70.0, tr.lanes_of(tr.w.edges[0])[0])
        _, _, _, length, _ = parts(driver)[0]
        p = Ped()
        p.x, p.y, p.s, p.gz = driver.x + length + 0.38, driver.y, 70.0, 0.0
        peds = Peds(tr.w, random.Random(3), target=0)
        peds.list = [p]
        peds.sim = SimpleNamespace(traffic=tr)
        return tr, driver, peds, p

    def test_waiting_car_and_pedestrian_clear_on_wide_asphalt(self):
        tr, driver, peds, p = self.clinch()
        tr.update(0.05, 70, 0, (), peds.list)
        self.assertEqual(driver.v, 0.0)
        for _ in range(80):
            peds.update(0.05, 70, 0, (), lambda *_a, **_kw: None)
            tr.update(0.05, 70, 0, (), peds.list)
        self.assertIn(p, peds.list)
        self.assertGreater(driver.x, 75.0)

    def test_sealed_pedestrian_releases_a_lane_after_three_seconds(self):
        tr, driver, peds, p = self.clinch()
        x, y = p.x, p.y
        walls = ((x-.45, y-.45, x+.45, y-.45), (x+.45, y-.45, x+.45, y+.45),
                 (x+.45, y+.45, x-.45, y+.45), (x-.45, y+.45, x-.45, y-.45))
        tr.w.edges_near = lambda *_: walls
        for _ in range(90):
            peds.update(0.05, 70, 0, (), lambda *_a, **_kw: None)
            tr.update(0.05, 70, 0, (), peds.list)
        self.assertNotIn(p, peds.list)
        self.assertGreater(driver.x, 71.0)

    def test_stopped_bus_releases_when_walker_clears_its_nose(self):
        from transit import Transit
        tr, _, peds, p = self.clinch()
        b = Body(65.0, 2.0, 0.0, BUS, 0)
        b.ctl, b.az = (0, 0, True), 0.0
        _, _, _, length, _ = parts(b)[0]
        p.x, p.y = b.x + length + 0.5, b.y
        bus = SimpleNamespace(body=b)
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(w=tr.w, peds=peds)
        self.assertTrue(transit._pedestrian_in_path(bus))
        p.gz = 4.0
        self.assertFalse(transit._pedestrian_in_path(bus))
        p.gz = 0.0
        for _ in range(25):
            peds._avoid_traffic(p, (b,), 0.05)
        self.assertFalse(transit._pedestrian_in_path(bus))

    def test_pedestrian_jumps_away_from_approaching_car_off_zebra(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.kerb = lambda x, y: abs(y) > 3.6
        tr.w.surface = lambda x, y: 0 if abs(y) > 3.6 else 3
        tr.w.on_zebra = lambda *_: False
        tr.w.walk_cells = {}
        peds = Peds(tr.w, random.Random(3), target=0)
        p = Ped()
        p.x, p.y = 70.0, 1.85
        approaching = car(tr, 64.0, 1.8, speed=8.0)
        self.assertTrue(peds._avoid_traffic(p, (approaching,), 0.05))
        self.assertGreater(p.hy, 0.0)
        self.assertGreater(p.vault_path[3], p.y)

    def test_pedestrian_seeks_same_side_refuge_only_when_traffic_threatens(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.kerb = lambda x, y: 3.6 < abs(y) < 6.0
        tr.w.surface = lambda x, y: 3 if abs(y) <= 3.6 else 0
        tr.w.walk_cells = {}
        peds = Peds(tr.w, random.Random(3), target=0)
        p = Ped()
        p.x, p.y, p.gz = 70.0, 1.9, 0.0
        approaching = car(tr, 61.0, 1.8, speed=8.0)
        for _ in range(30):
            peds._avoid_traffic(p, (approaching,), 0.05)
        self.assertGreater(p.y, 3.6)
        self.assertEqual(p.mode, "walk")
        p2 = Ped()
        p2.x, p2.y = 70.0, 4.4
        self.assertFalse(peds._avoid_traffic(p2, (approaching,), 0.05))
        self.assertEqual(p2.y, 4.4)

    def test_pedestrian_clears_lane_when_a_vehicle_has_already_yielded(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.kerb = lambda x, y: 3.6 < y < 6.0
        tr.w.surface = lambda x, y: 3 if abs(y) <= 3.6 else 0
        tr.w.walk_cells = {}
        peds = Peds(tr.w, random.Random(3), target=0)
        p = Ped()
        p.x, p.y, p.gz = 70.0, 1.9, 0.0
        waiting = car(tr, 66.0, 1.8)
        for _ in range(28):
            peds._avoid_traffic(p, (waiting,), 0.05)
        self.assertGreater(p.y, 3.6)

    def test_pedestrian_vaults_low_car_when_approaching_traffic_cuts_off_refuge(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.kerb = lambda x, y: y < -1.7
        tr.w.surface = lambda x, y: 3
        tr.w.edges_near = lambda *_: []
        tr.w.walk_cells = {}
        peds = Peds(tr.w, random.Random(3), target=0)
        p = Ped()
        p.x, p.y, p.gz = 70.0, 1.45, 0.0
        barrier = car(tr, 70.0, 0.0)
        approaching = car(tr, 63.5, 1.45, speed=8.0)
        self.assertTrue(peds._avoid_traffic(p, (barrier, approaching), 0.05, barrier))
        self.assertIsNotNone(p.vault_path)
        for _ in range(19):
            if p.vault_path is not None:
                peds._advance_vault(p, 0.05)
        self.assertLess(p.y, -1.7)
        self.assertEqual(p.hy, 0.0)


class PlayerHandlingTest(unittest.TestCase):
    def test_manual_steering_response_and_bus_radius(self):
        world = SimpleNamespace(hilly=False, ground_y=lambda *_: 0.0, surface=lambda *_: 3)
        b = Body(0, 0, 0, 0, 0)
        b.player_car = True
        drive(b, 0.0, 1.0, False, 0.01, world)
        self.assertAlmostEqual(b.steer, 9.0 * 0.01 * HERO["drv"] * 0.8)
        self.assertAlmostEqual(turn_radius_factor(5, BUS), 0.9 * turn_radius_factor(5))
        self.assertAlmostEqual(turn_radius_factor(5, ARTIC_BUS), 0.9 * 0.75 * 0.9)

    def test_player_walking_rotation_is_300_degrees_per_second(self):
        world = SimpleNamespace(hilly=False, pg2=None, ground_y=lambda *_: 0.0, level=lambda *_, **_kw: 0.0,
                                edges_near=lambda *_: (), points_near=lambda *_: ())
        walker = Walker(0.0, 0.0, 0.0)
        walker.update(0.1, 1.0, 1.0, False, world)
        self.assertAlmostEqual(math.degrees(walker.h), 30.0)


class ArticulatedBusTest(unittest.TestCase):
    def test_ambient_bus_rear_swing_checks_adjacent_vehicle(self):
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        bus = car(tr, 60.0, 0.0)
        bus.kind, bus.trh = ARTIC_BUS, -0.7
        tow(bus)
        obstacle = (58.5, 4.2, 0.0, 2.0, 0.85)
        self.assertTrue(all(_sat(_corners(*p), p[2], _corners(*obstacle), 0.0) is None for p in parts(bus)))
        tr.ph = {(3, 0): [(58.5, 4.2, 0.85, 2.0, 0.0, 0.0)]}
        self.assertFalse(tr._step_clear(bus, 61.0, 0.0, 0.12))
        tr.ph.clear()
        self.assertTrue(tr._step_clear(bus, 61.0, 0.0, 0.12))

    def test_return_trip_uses_city_block_to_rejoin_outbound_road(self):
        tr = setup(road(0, 1, (-60, 0), (0, 0)),
                   road(1, 2, (0, 0), (50, 0), ow=True),
                   road(2, 3, (50, 0), (50, 50), ow=True),
                   road(3, 4, (50, 50), (0, 50), ow=True),
                   road(4, 1, (0, 50), (0, 0), ow=True))
        loop = fastest_route(tr.w, 1, 1, (0, 0), incoming=(0, 1), outgoing=(0, -1))
        self.assertEqual(loop, ((1, 1), (2, 1), (3, 1), (4, 1)))
        self.assertEqual(fastest_route(tr.w, 1, 1, (0, 0), incoming=(0, 1), outgoing=(1, 1)), ())

    def test_bus_progress_stays_on_outbound_segment_beside_return_lane(self):
        from transit import Bus, Line, Transit
        points = [(0, 0), (80, 0), (80, 10), (70, 10), (70, 2), (1, 2), (-20, 2)]
        body = Body(40, 1.8, 0.0, ARTIC_BUS, 0)
        bus = Bus(Line({"ref": "QA"}, points), body, 0)
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(w=SimpleNamespace())
        transit._lane = lambda *_: (1.8, 3.7, 0.0, 10.0)
        transit._squeeze = lambda _: 0.0
        transit._posts = lambda *_: (0.0, False)
        transit._gap = lambda _: None
        transit._pedestrian_in_path = lambda _: False
        for x in range(40, 68):
            body.x = x
            transit._drive(bus, 0.1)
            self.assertAlmostEqual(bus.s, x)
            self.assertEqual(bus.i, 0)

    def test_transit_uses_swept_footprint_for_nearby_vehicles(self):
        from transit import Transit
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        intruder = car(tr, 54.0, 0.0)
        bus = Body(40, 0, 0, ARTIC_BUS, 0)
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(traffic=tr, bodies=[bus])
        self.assertLess(transit._swept_traffic_gap(bus, 8.0), 6.0)
        intruder.y = 4.0
        self.assertIsNone(transit._swept_traffic_gap(bus, 8.0))

    def test_bus_does_not_integrate_through_a_car_that_cuts_in(self):
        from transit import Transit
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.surface = lambda *_: 3
        car(tr, 40.0 + DIMS[ARTIC_BUS][0] / 2 + DIMS[0][0] / 2 + 0.04, 0.0)
        bus = Body(40.0, 0.0, 0.0, ARTIC_BUS, 0)
        bus.vx = 4.0
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(traffic=tr, bodies=[bus], w=tr.w)
        transit.drive_body(bus, (0.5, 0.0, False), 0.05)
        self.assertEqual((bus.x, bus.vx), (40.0, 0.0))
        self.assertTrue(bus.braking)

    def test_bus_can_back_away_from_contact_with_a_clear_rear(self):
        from transit import Transit
        tr = setup(road(0, 1, (0, 0), (150, 0)))
        tr.w.surface = lambda *_: 3
        tr.w.kerb = lambda *_: False
        bus = Body(40.0, 0.0, 0.0, ARTIC_BUS, 0)
        other = car(tr, bus.x + (DIMS[ARTIC_BUS][0] + DIMS[0][0]) * 0.5 + 0.04, 0.0)
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(traffic=tr, bodies=[bus], w=tr.w, mode="car", peds=SimpleNamespace(list=[]))
        rear = bus.x - DIMS[ARTIC_BUS][0] * 0.5
        transit.sim.peds.list.append(SimpleNamespace(x=rear - 0.5, y=0.0, gz=0.0))
        for _ in range(100):
            transit.drive_body(bus, (1.0, 0.0, False), 0.05)
            self.assertGreaterEqual(bus.x, 40.0)
        transit.sim.peds.list.clear()
        minimum_x = bus.x
        for _ in range(120):
            transit.drive_body(bus, (1.0, 0.0, False), 0.05)
            minimum_x = min(minimum_x, bus.x)
            self.assertLess(bus.x, other.x - (DIMS[ARTIC_BUS][0] + DIMS[0][0]) * 0.5 + 0.01)
        self.assertLess(minimum_x, 39.5)

    def test_length_and_section_ratio(self):
        bus = Body(0, 0, 0, ARTIC_BUS, 0)
        front, rear = parts(bus)
        self.assertAlmostEqual((front[3] + rear[3]) * 2, DIMS[IDS.index("JSP Dvokatnik")][0] * 1.5)
        self.assertAlmostEqual(rear[3] / front[3], 0.7)

    def test_front_turns_and_rear_axle_tracks_joint(self):
        world = SimpleNamespace(hilly=False, surface=lambda *_: 1)
        bus = Body(0, 0, 0, ARTIC_BUS, 0)
        bus.vx = 3.0
        tow(bus)
        max_bend = 0.0
        for _ in range(48):
            drive(bus, 0.0, 1.0, False, 0.04, world)
            bend = abs(math.remainder(bus.h - bus.trh, math.tau))
            max_bend = max(max_bend, bend)
            joint = (bus.x + ARTIC_HINGE * math.cos(bus.h), bus.y + ARTIC_HINGE * math.sin(bus.h))
            self.assertAlmostEqual(math.dist(joint, bus.tra), ARTIC_HINGE - ARTIC_REAR_AXLE)
            self.assertLessEqual(bend, ARTIC_JACK + 1e-12)
            self.assertEqual(parts(bus)[1][2], bus.trh)
        self.assertGreater(bus.h, 0.75)
        self.assertGreater(max_bend, 0.3)
        for _ in range(120):
            drive(bus, 0.25, 0.0, False, 0.04, world)
        self.assertLess(abs(math.remainder(bus.h - bus.trh, math.tau)), 0.05)

    def test_route_bus_follows_a_sharp_corner_in_both_directions(self):
        from transit import Bus, Line, Transit
        world = SimpleNamespace(hilly=False, surface=lambda *_: 1)
        transit = Transit.__new__(Transit)
        transit.sim = SimpleNamespace(w=world)
        transit._lane = lambda *_: (1.8, 3.7, 0.0, 10.0)
        transit._squeeze = lambda _: 0.0
        transit._posts = lambda *_: (0.0, False)
        transit._gap = lambda _: None
        transit._pedestrian_in_path = lambda _: False
        for sign in (-1, 1):
            with self.subTest(direction=sign):
                points = [(0, 0), (15, 0), (25, 0), (35, 0), (35, 10 * sign),
                          (35, 25 * sign), (35, 40 * sign), (35, 55 * sign), (35, 80 * sign)]
                body = Body(10, 1.8, 0, ARTIC_BUS, 0)
                body.vx = 4.0
                bus = Bus(Line({"ref": "QA"}, points), body, 1)
                bend = 0.0
                for _ in range(360):
                    transit._drive(bus, 1 / 30)
                    drive(body, *body.ctl, 1 / 30, world)
                    bend = max(bend, abs(math.remainder(body.h - body.trh, math.tau)))
                self.assertGreater(sign * body.y, 25.0)
                self.assertAlmostEqual(body.x, 35 - 1.8 * sign, delta=0.5)
                self.assertAlmostEqual(body.h, sign * math.pi / 2, delta=0.1)
                self.assertGreater(bend, 0.4)

    def test_bellows_joins_both_sections_at_full_lock(self):
        import gl3d
        arrays = gl3d.car_arrays(ARTIC_BUS, 0, steer_wheels=True)
        front = gl3d._bus_section(arrays)[0]
        rear = gl3d._bus_section(arrays, rear=True)[0]
        self.assertGreater(len(front), len(rear))
        gap = gl3d._BUS_BELLOWS_HALF
        self.assertAlmostEqual(float(front[:, 0].min()), ARTIC_HINGE + gap, places=5)
        self.assertAlmostEqual(float(rear[:, 0].max()), ARTIC_HINGE - gap, places=5)
        gap += gl3d._BUS_BELLOWS_OVERLAP
        width = gl3d.visual_dims(ARTIC_BUS)[1]
        for bend in (-ARTIC_JACK, 0.0, ARTIC_JACK):
            pos, uv, color = gl3d.bus_bellows_arrays(bend)
            rear_corner = (ARTIC_HINGE - gap * math.cos(bend) - width * 0.5 * math.sin(bend),
                           gl3d.visual_dims(ARTIC_BUS)[2], -gap * math.sin(bend) + width * 0.5 * math.cos(bend))
            self.assertLess(min(math.dist(v, rear_corner) for v in pos), 1e-6)
            self.assertEqual(len(pos), len(uv))
            self.assertEqual(len(pos), len(color))


if __name__ == "__main__":
    unittest.main()
