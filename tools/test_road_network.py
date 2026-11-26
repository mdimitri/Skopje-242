"""Regression checks for routing, carriageway geometry and traffic controls."""
import math
import os
import random
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_world import collapse_short_road_links, connect_roads
import lanefix
import numpy as np
import roads3d
import road_controls
import roadclean
import roads_candidate
import building_move
import signals
from transit import Transit
import vehicles
from actors import Body, Car, Traffic, drive, fly, turn_radius_factor
from crosswalks import CrossingMap, walk_path
from driving import fastest_route, follow_speed, road_control_speed, turn_lanes
from roadwidth import half_width, lane_offset, nominal_offset
from sidewalk_audit import raster
from world import World


def road(nodes, pts, **tags):
    return dict(dict(nodes=list(nodes), pts=list(pts), drive=True, walk=True, bridge=False,
                     layer=0, cls="residential", ow=False), **tags)


def edge(a, b, p, q, **tags):
    length = math.dist(p, q)
    return dict(dict(a=a, b=b, pts=[p, q], cum=[0.0, length], len=length, w=7.0, ow=False,
                     drive=True, walk=True, bridge=False, cls="residential"), **tags)


class RoadNetworkTests(unittest.TestCase):
    def test_snap_on_long_segment_and_share_nearby_insertions(self):
        main = road((1, 2), ((0, 0), (100, 0)))
        a = road((3, 4), ((10, -20), (10, 0)))
        b = road((5, 6), ((10.4, 20), (10.4, 4)))
        tunnel = road((7, 8), ((30, -20), (30, -4)), tunnel=True)
        motorway = road((9, 10), ((50, -20), (50, -4)), cls="motorway")
        self.assertEqual(connect_roads([main, a, b, tunnel, motorway]), 2)
        self.assertEqual(main["pts"], [(0, 0), (10, 0), (100, 0)])
        self.assertEqual(a["nodes"][-1], main["nodes"][1])
        self.assertEqual(b["nodes"][-1], main["nodes"][1])
        self.assertEqual(tunnel["nodes"][-1], 8)
        self.assertEqual(motorway["nodes"][-1], 10)

    def test_parallel_one_way_approaches_do_not_form_a_through_pair(self):
        left = edge(0, 1, (-30, 0), (0, 0), ow=True)
        right = edge(2, 1, (30, 0), (0, 0), ow=True)
        self.assertEqual(lanefix.through_pairs([left, right]), {})
        right = edge(1, 2, (0, 0), (30, 0), ow=True)
        self.assertEqual(lanefix.through_pairs([left, right]), {(0, 1): 1, (1, 1): 0})

    def test_short_narrow_stretch_of_a_boulevard_takes_the_neighbour_layout(self):
        wide = dict(w=14.0, lanes=4, directional_lanes=(2, 2))
        edges = [edge(0, 1, (0, 0), (100, 0), **wide), edge(1, 2, (100, 0), (130, 0), w=7.0),
                 edge(2, 3, (130, 0), (230, 0), **wide)]
        self.assertEqual(lanefix.harmonize(edges), 1)
        self.assertEqual((edges[1]["w"], edges[1]["directional_lanes"]), (14.0, (2, 2)))

    def test_explicit_three_lane_approach_is_not_widened_by_graph_cleanup(self):
        edges = [edge(0, 1, (0, 0), (100, 0), w=13.0, lanes=4, ow=True, lanes_tagged=True),
                 edge(1, 2, (100, 0), (130, 0), w=9.75, lanes=3, ow=True, lanes_tagged=True),
                 edge(2, 3, (130, 0), (230, 0), w=13.0, lanes=4, ow=True, lanes_tagged=True)]
        lanefix.repair(edges)
        self.assertEqual((edges[1]["w"], edges[1]["lanes"]), (9.75, 3))

    def test_candidate_graph_keeps_original_junction_nodes(self):
        edges = [edge(0, 1, (-30, 0), (0, 0)), edge(1, 2, (0, 0), (12, 0)),
                 edge(2, 3, (12, 0), (40, 0)), edge(1, 4, (0, 0), (0, 30)),
                 edge(2, 5, (12, 0), (12, -30))]
        before = [(e["a"], e["b"], list(e["pts"])) for e in edges]
        roadclean.repair(edges, preserve_geometry=True)
        self.assertEqual([(e["a"], e["b"], list(e["pts"])) for e in edges], before)

    def test_candidate_graph_uses_the_rendered_slip_cross_section(self):
        e = edge(0, 1, (0, 0), (30, 0), road=0, ow=True, cls="tertiary_link", w=3.25, lanes=1)
        way = {"type": "way", "id": 7, "tags": {"highway": "tertiary_link", "oneway": "yes", "lanes": "1"}}
        self.assertEqual(roads_candidate.sync_graph_sections([e], [{"id": 7}], [way]), 1)
        self.assertAlmostEqual(e["w"], 4.875)
        self.assertEqual(e["lanes"], 1)

    def test_graph_taper_tracks_the_candidate_lane_centres(self):
        edges = [edge(0, 1, (0, 0), (40, 0), road=0, ow=True, cls="tertiary"),
                 edge(1, 2, (40, 0), (110, 0), road=1, ow=True, cls="tertiary")]
        ways = [{"type": "way", "id": i, "tags": {"highway": "tertiary", "oneway": "yes", "name": "Boulevard", "lanes": str(n)}}
                for i, n in ((7, 2), (8, 3))]
        from geo import LAT0, LON0, M_LON
        for way, nodes, positions in zip(ways, ((0, 1), (1, 2)), ((0, 40), (40, 110))):
            way["nodes"] = nodes
            way["geometry"] = [{"lat": LAT0, "lon": LON0 + x / M_LON} for x in positions]
        roads_candidate.sync_graph_sections(edges, [{"id": 7}, {"id": 8}], ways)
        wide = edges[1]
        self.assertEqual((wide["lane_taper"][0], wide["lane_taper"][2]), ("start", "left"))
        self.assertAlmostEqual(wide["lane_taper"][1], 50)
        self.assertAlmostEqual(2 * half_width(wide, 0), edges[0]["w"])
        from shapely.geometry import LineString
        section = {**wide, "tapers": [["start", 50, (wide["w"] - edges[0]["w"]) / 2,
                                     -(wide["w"] - edges[0]["w"]) / 2]]}
        drawn = roads_candidate.Edge(1, (1, 2), LineString(wide["pts"]), section)
        for nominal in Traffic.lanes_of(wide):
            for distance in (5, 15, 40):
                actual = lane_offset(wide, 1, distance, nominal)
                fraction = 0.5 + nominal / wide["w"]
                self.assertAlmostEqual(drawn.trace(fraction, [distance, distance + 0.01], lane_aligned=True).coords[0][1], actual)
                self.assertAlmostEqual(nominal_offset(wide, 1, distance, actual), nominal, places=5)

    def test_traffic_waits_and_merges_before_a_lane_closes(self):
        wide = edge(0, 1, (0, 0), (50, 0), w=9.75, lanes=3, ow=True,
                    taper=(None, (25, 3.25)), lane_taper=("end", 25, "left"))
        self.assertEqual(Traffic._lanes_fit(wide, 1, 50, 1), [1, 2])
        c = Car()
        c.kind, c.d, c.s, c.lane = 1, 1, 20.0, Traffic.lanes_of(wide)[0]
        self.assertIsNotNone(Traffic._taper_stop(c, wide))
        c.lane = Traffic.lanes_of(wide)[1]
        self.assertIsNone(Traffic._taper_stop(c, wide))

    def test_lane_mapping_preserves_both_through_lanes_at_a_left_taper(self):
        narrow = edge(0, 1, (0, 0), (50, 0), w=6.5, lanes=2, ow=True)
        opening = edge(1, 2, (50, 0), (100, 0), w=9.75, lanes=3, ow=True,
                       taper=((25, 3.25), None), lane_taper=("start", 25, "left"))
        closing = edge(2, 3, (100, 0), (150, 0), w=9.75, lanes=3, ow=True,
                       taper=(None, (25, 3.25)), lane_taper=("end", 25, "left"))
        after = edge(3, 4, (150, 0), (200, 0), w=6.5, lanes=2, ow=True)
        traffic = Traffic.__new__(Traffic)
        traffic.w = SimpleNamespace(edges=[narrow, opening, closing, after])
        traffic.internal_links = {}
        self.assertEqual([traffic._mapped_lane((0, 1), i, (1, 1), 0) for i in (0, 1)], [1, 2])
        self.assertEqual([traffic._mapped_lane((2, 1), i, (3, 1), 0) for i in (1, 2)], [0, 1])

    def test_slip_merge_targets_the_receiving_outer_lane(self):
        right = edge(0, 1, (-20, 5), (0, 0), ow=True, cls="primary_link", lanes=1)
        left = edge(2, 1, (-20, -5), (0, 0), ow=True, cls="primary_link", lanes=1)
        receiving = edge(1, 3, (0, 0), (40, 0), ow=True, cls="primary", lanes=3, w=9.75)
        traffic = Traffic.__new__(Traffic)
        traffic.w = SimpleNamespace(edges=[right, left, receiving], edge_point=lambda e, s: World.edge_point(None, e, s))
        traffic.internal_links = {}
        self.assertEqual(traffic._mapped_lane((0, 1), 0, (2, 1), -0.24), 2)
        self.assertEqual(traffic._mapped_lane((1, 1), 0, (2, 1), 0.24), 0)

    def test_rendered_taper_continues_across_a_graph_only_node(self):
        from geo import LAT0, LON0, M_LON
        ways = [{"type": "way", "id": i, "nodes": nodes,
                 "geometry": [{"lat": LAT0, "lon": LON0 + x / M_LON} for x in positions],
                 "tags": {"highway": "tertiary", "oneway": "yes", "name": "Boulevard", "lanes": str(n)}}
                for i, n, nodes, positions in ((7, 2, [0, 1], [0, 40]), (8, 3, [1, 2], [40, 90]))]
        edges = [edge(0, 1, (0, 0), (40, 0), road=0, ow=True, cls="tertiary"),
                 edge(1, 3, (40, 0), (54, 0), road=1, ow=True, cls="tertiary"),
                 edge(3, 2, (54, 0), (90, 0), road=1, ow=True, cls="tertiary")]
        roads_candidate.sync_graph_sections(edges, [{"id": 7}, {"id": 8}], ways)
        self.assertAlmostEqual(half_width(edges[1], 14), half_width(edges[2], 0), places=5)
        self.assertAlmostEqual(half_width(edges[2], 35), 9.75 / 2, places=5)

    def test_graph_follows_the_candidate_spline_between_osm_nodes(self):
        from geo import LAT0, LON0, M_LAT, M_LON
        from shapely.geometry import LineString
        points = [(0, 0), (20, 5), (40, 0)]
        way = {"type": "way", "id": 7, "nodes": [0, 1, 2],
               "geometry": [{"lat": LAT0 - y / M_LAT, "lon": LON0 + x / M_LON} for x, y in points],
               "tags": {"highway": "tertiary", "oneway": "yes", "lanes": "2"}}
        e = edge(0, 2, points[0], points[-1], road=0, ow=True, cls="tertiary")
        e["pts"] = points
        roads_candidate.sync_graph_sections([e], [{"id": 7}], [way])
        rendered = roads_candidate.road_edge(way, points).line
        self.assertLess(LineString(e["pts"]).hausdorff_distance(rendered), 0.001)

    def test_road_overlapping_building_moves_within_half_its_width(self):
        ring = [(-5, 2), (5, 2), (5, 8), (-5, 8)]
        grid = {(x, y): [(-30, 0, 30, 0, 3)] for x in (-1, 0) for y in (-1, 0)}
        mover = building_move.BuildingMoves([{"ring": ring}], grid, np.zeros((100, 100), bool), 50, 50, 1)
        dx, dy = mover.move(0)
        self.assertLessEqual(math.hypot(dx, dy), 3.01)
        self.assertGreater(dy, 1)

    def test_building_move_respects_neighbours_and_water(self):
        ring = [(-5, 2), (5, 2), (5, 8), (-5, 8)]
        neighbour = [(-20, 8.1), (20, 8.1), (20, 30), (-20, 30)]
        grid = {(x, y): [(-30, 0, 30, 0, 3)] for x in (-1, 0) for y in (-1, 0)}
        mover = building_move.BuildingMoves([{"ring": ring}, {"ring": neighbour}], grid,
                                            np.zeros((100, 100), bool), 50, 50, 1)
        self.assertIsNone(mover.move(0))
        water = np.zeros((100, 100), bool)
        water[58:, :] = True
        mover = building_move.BuildingMoves([{"ring": ring}], grid, water, 50, 50, 1)
        self.assertIsNone(mover.move(0))

    def test_gantry_moves_upstream_when_its_first_supports_are_blocked(self):
        edges = [edge(0, 1, (-80, 0), (0, 0), w=6.5, lanes=2, ow=True, cls="tertiary"),
                 edge(1, 2, (0, 0), (80, 0), w=6.5, lanes=2, ow=True, cls="tertiary"),
                 edge(1, 3, (0, 0), (0, 60), w=6.5, lanes=2, ow=True, cls="tertiary")]
        controls = {"signals": [], "heads": [], "crossings": []}
        with patch.object(road_controls, "plan_lights", return_value=({1}, {1: 1})), \
             patch.object(road_controls, "draw_gantry") as draw, patch.object(road_controls, "_bake"):
            road_controls.build(edges, [], controls, None, None, None, None,
                                lambda x, z: x < -10)
        self.assertEqual(draw.call_count, 1)
        device = draw.call_args.args[1]
        self.assertTrue(all(p[0] < -10 for p in device["supports"]))
        self.assertAlmostEqual(device["supports"][0][0], device["supports"][1][0])

    def test_submetre_links_weld_without_merging_elevations(self):
        main = road((0, 1, 2, 3), ((0, 0), (10, 0), (10.7, 0), (20, 0)))
        access = road((1, 4), ((10, 0), (10, 9)))
        path = road((2, 5), ((10.7, 0), (10.7, -9)), drive=False)
        bridge = road((6, 7), ((10, 0), (10.7, 0)), bridge=True, layer=1)
        roads = [main, access, path, bridge]
        self.assertEqual(collapse_short_road_links(roads), 1)
        self.assertEqual(main["nodes"], [0, 1, 3])
        self.assertEqual(path["pts"][0], (10, 0))
        self.assertEqual(path["nodes"][0], 1)
        self.assertEqual(bridge["nodes"], [6, 7])

    def test_taper_and_asymmetric_lane_centres(self):
        e = edge(0, 1, (0, 0), (40, 0), w=10.5, directional_lanes=(2, 1))
        result = roads3d._ribbon(e, 0, {(0, 0): ((0, 1), 1, 7.0), (0, 1): ((0, 1), 1, 3.5)}, {})
        self.assertEqual((result[1][0], result[1][-1]), (7.0, 3.5))
        self.assertEqual(half_width(e, 20.0), 5.25)
        self.assertEqual(Traffic.lanes_of(e, 1), [0.0, 3.5])
        self.assertEqual(Traffic.lanes_of(e, -1), [3.5])

    def test_kerb_exists_only_on_tagged_side(self):
        w = World.__new__(World)
        w.edges = [edge(0, 1, (0, 0), (40, 0), sidewalk_sides=(False, True))]
        self.assertTrue(w.kerb(20, 4.5))
        self.assertFalse(w.kerb(20, -4.5))
        self.assertFalse(w.kerb(20, 3.0))

    def test_pavement_stays_connected_behind_wide_t_junction(self):
        edges = [edge(0, 1, (-25, 0), (0, 0), road=0), edge(1, 2, (0, 0), (25, 0), road=1),
                 edge(1, 3, (0, 0), (0, -25), road=2, w=10.5)]
        mesh = []
        roads3d.build(edges, [], lambda _, mat, pos, uv, col: mesh.append((pos, col)), lambda x, y: (0, 0), 3)
        pos = np.concatenate([p for p, _ in mesh]).reshape(-1, 3, 3)
        col = np.concatenate([c for _, c in mesh]).reshape(-1, 3, 4)[:, 0, :3]
        _, pavement, _, _, _ = raster(pos, col, 0.0, 0.0, 260)
        self.assertTrue(np.all(pavement[152, 110:150] > 0.1))

    def test_ambient_route_prefers_street_to_narrow_service_access(self):
        edges = [edge(0, 1, (-30, 0), (0, 0)), edge(1, 2, (0, 0), (0, 30), cls="service", w=4.4),
                 edge(1, 3, (0, 0), (30, 0)), edge(2, 4, (0, 30), (30, 30)), edge(3, 4, (30, 0), (30, 30))]
        w = SimpleNamespace(edges=edges, main=set(range(5)), out={1: [(1, 1), (2, 1)], 2: [(3, 1)], 3: [(4, 1)]})
        w.edge_point = lambda e, s: World.edge_point(w, e, s)
        traffic = Traffic(w, random.Random(1))
        c = Car()
        c.e, c.d, c.s, c.kind = 0, 1, 0.0, 1
        for _ in range(10):
            options, _, chosen = traffic._choose(c, 0, 1)
            self.assertIn((1, 1), options)  # station routing still sees the road
            self.assertEqual(options[chosen], (2, 1))

    def test_fastest_route_uses_seconds_and_current_queue(self):
        edges = [edge(0, 1, (0, 0), (60, 0), speed=4.0, ow=True),
                 edge(0, 2, (0, 0), (30, 12), speed=16.0, ow=True),
                 edge(2, 1, (30, 12), (60, 0), speed=16.0, ow=True)]
        w = SimpleNamespace(edges=edges, out={0: [(0, 1), (1, 1)], 2: [(2, 1)]})
        self.assertEqual(fastest_route(w, 0, 1, (60, 0)), ((1, 1), (2, 1)))
        self.assertEqual(fastest_route(w, 0, 1, (60, 0), delay=lambda o: 15.0 if o == (1, 1) else 0.0), ((0, 1),))
        self.assertIsNone(fastest_route(w, 1, 0, (0, 0)))
        self.assertEqual(fastest_route(w, 1, 1, (60, 0)), ())

    def test_tagged_approach_disallows_wrong_turns_in_router(self):
        edges = [edge(0, 1, (-20, 0), (0, 0), speed=10.0, ow=True, lanes=1, turn=("through", "")),
                 edge(1, 2, (0, 0), (0, 20), speed=10.0, ow=True),
                 edge(1, 3, (0, 0), (20, 0), speed=10.0, ow=True),
                 edge(3, 2, (20, 0), (0, 20), speed=10.0, ow=True)]
        w = SimpleNamespace(edges=edges, out={0: [(0, 1)], 1: [(1, 1), (2, 1)], 3: [(3, 1)]})
        self.assertEqual(turn_lanes(edges[0], 1, math.pi / 2), [])
        self.assertEqual(turn_lanes(edges[0], 1, 0.0), [0])
        self.assertIsNone(fastest_route(w, 0, 2, (0, 20)))
        self.assertEqual(fastest_route(w, 0, 3, (20, 0)), ((0, 1), (2, 1)))

    def test_following_speed_responds_to_gap_and_leader_speed(self):
        self.assertEqual(follow_speed(1.0, 0.0), 0.0)
        self.assertAlmostEqual(follow_speed(15.3, 10.0), 9.818181818181818)
        self.assertLess(follow_speed(10.0, 0.0), follow_speed(10.0, 8.0))

    def test_traffic_predicts_a_moving_pedestrian_crossing(self):
        traffic = Traffic.__new__(Traffic)
        car = Car()
        car.x = car.y = car.h = 0.0
        car.kind, car.v, car.gz = 1, 3.0, 0.0
        pedestrian = SimpleNamespace(vx=0.0, vy=5.0)
        traffic.hash = {(0, 0): [(4.9, -4.0, 1.7, 0.4, pedestrian, None, 0.0)]}
        self.assertTrue(traffic._ped_in_way(car))
        pedestrian.vy = -5.0
        self.assertFalse(traffic._ped_in_way(car))

    def test_pedestrian_path_reaches_a_zebra_instead_of_cutting_across(self):
        crossings = CrossingMap([(0, 5, 0, 1, 4, 1)])
        world = SimpleNamespace(pedestrian_ground=lambda x, y: abs(x) > 2 or crossings.zebra(x, y))
        path = walk_path(world, (-5, 0), (5, 0))
        self.assertIsNotNone(path)
        across = [p for p in path if abs(p[0]) <= 2]
        self.assertTrue(across)
        self.assertTrue(all(crossings.zebra(*p) for p in across))

    def test_drivers_yield_ahead_at_zebras_and_brake_for_imminent_contact_elsewhere(self):
        traffic = Traffic.__new__(Traffic)
        traffic.w = SimpleNamespace(on_zebra=lambda *_: False)
        car = Car()
        car.x = car.y = car.h = 0.0
        car.kind, car.v = 1, 6.0
        ped = SimpleNamespace(vx=0.0, vy=0.0)
        traffic.hash = {(0, 0): [(8.0, 0.0, 0.3, 0.4, ped, None, 0.0)]}
        self.assertIsNone(traffic._ped_gap(car))
        traffic.w.on_zebra = lambda *_: True
        self.assertIsNotNone(traffic._ped_gap(car))
        traffic.w.on_zebra = lambda *_: False
        traffic.hash[(0, 0)] = [(4.0, 0.0, 0.3, 0.4, ped, None, 0.0)]
        self.assertIsNotNone(traffic._ped_gap(car))

    def test_bus_yields_to_a_moving_pedestrian_crossing(self):
        transit = Transit.__new__(Transit)
        body = SimpleNamespace(x=0.0, y=0.0, h=0.0, vx=3.0, vy=0.0, kind=vehicles.BUS)
        pedestrian = SimpleNamespace(x=4.9, y=-4.0, vx=0.0, vy=5.0, mode="walk")
        transit.sim = SimpleNamespace(peds=SimpleNamespace(list=[pedestrian]))
        bus = SimpleNamespace(body=body)
        self.assertTrue(transit._pedestrian_in_path(bus))
        pedestrian.vy = -5.0
        self.assertFalse(transit._pedestrian_in_path(bus))

    def test_scripted_drivers_stop_the_bumper_at_a_closed_rail_gate(self):
        w = SimpleNamespace(edges=[edge(0, 1, (-50, 0), (50, 0))])
        w.edge_point = lambda e, s: World.edge_point(w, e, s)
        sim = SimpleNamespace(w=w, trains=SimpleNamespace(closed={(0, 50.0)}))
        self.assertEqual(road_control_speed(sim, -8.0, 0.0, 0.0, 3.0, 1.0), 0.0)
        self.assertGreater(road_control_speed(sim, -22.0, 0.0, 0.0, 3.0, 1.0), 0.0)
        self.assertEqual(road_control_speed(sim, -8.0, 9.0, 0.0, 3.0, 1.0), math.inf)

    def test_red_light_stop_point_keeps_vehicle_front_three_metres_behind_pole(self):
        w = SimpleNamespace(edges=[edge(0, 1, (-30, 0), (0, 0))],
                            signals=[(1, 0, 1, 0, -8, 0, 0, 0, 3, 8)])
        lights = signals.Signals(w)
        lights.state = lambda _i: 2
        self.assertEqual(lights.red_ahead(-13.0, 0.0, 0.0, front=2.0, speed=0.0), 0.0)

    def test_right_turn_lookahead_uses_destination_kerb_lane(self):
        incoming = edge(0, 1, (-30, 0), (0, 0), ow=True, lanes=1)
        outgoing = edge(1, 2, (0, 0), (0, 30), ow=True, lanes=2)
        w = SimpleNamespace(edges=[incoming, outgoing])
        w.edge_point = lambda e, s: World.edge_point(w, e, s)
        traffic = Traffic(w, random.Random(1))
        c = Car()
        c.e, c.d, c.s, c.nxt, c.turn = 0, 1, 29.0, (1, 1), math.pi / 2
        c.kind = 1
        traffic._set_lane(c, incoming)
        self.assertAlmostEqual(traffic._target(c, incoming, 3.0)[0], -1.75)
        traffic.occ[(1, 1, 0)] = [(1.0, 0.0, False)]
        self.assertFalse(traffic._exit_blocked(c))
        traffic.occ[(1, 1, 1)] = [(1.0, 0.0, False)]
        self.assertTrue(traffic._exit_blocked(c))

    def test_lookahead_continues_through_short_links_to_the_next_turn(self):
        incoming = edge(0, 1, (-10, 0), (0, 0))
        short = edge(1, 2, (0, 0), (2, 0))
        north = edge(2, 3, (2, 0), (2, 20), ow=True, lanes=1)
        w = SimpleNamespace(edges=[incoming, short, north])
        w.edge_point = lambda e, s: World.edge_point(w, e, s)
        traffic = Traffic(w, random.Random(1))
        c = Car()
        c.e, c.d, c.s, c.nxt, c.nx2, c.turn, c.kind = 0, 1, 9.0, (1, 1), [((2, 1), math.pi / 2)], 0.0, 1
        traffic._set_lane(c, incoming)
        x, y, _ = traffic._target(c, incoming, 4.0)
        self.assertAlmostEqual(x, 2.0)
        self.assertAlmostEqual(y, 1.0)

    def test_junction_exit_uses_arrival_time_to_predict_queue_clearance(self):
        incoming = edge(0, 1, (-30, 0), (0, 0), ow=True)
        outgoing = edge(1, 2, (0, 0), (30, 0), ow=True)
        traffic = Traffic(SimpleNamespace(edges=[incoming, outgoing]), random.Random(1))
        c = Car()
        c.e, c.d, c.nxt, c.lidx, c.kind, c.v = 0, 1, (1, 1), 0, 1, 5.0
        traffic.occ[(1, 1, 0)] = [(1.0, 0.0, False), (8.0, 0.0, False)]
        self.assertTrue(traffic._exit_blocked(c, 1.0))
        traffic.occ[(1, 1, 0)] = [(1.0, 6.0, True)]
        self.assertTrue(traffic._exit_blocked(c, 0.2))
        self.assertFalse(traffic._exit_blocked(c, 4.0))

    def test_turn_radius_tightens_more_at_low_speed(self):
        self.assertAlmostEqual(turn_radius_factor(0.0), 0.67 * 0.75 * 0.75 * 0.75)
        self.assertAlmostEqual(turn_radius_factor(12.0), 0.67 * 0.75 * 0.75)

    def test_coasting_turns_do_not_create_speed_and_cars_cap_at_160_kph(self):
        p = Body(0.0, 0.0, 0.0, 1)
        p.vx = 10.0
        w = SimpleNamespace(hilly=False, surface=lambda _x, _y: 3)
        last = p.speed
        for k in range(40):
            drive(p, 0.0, 1.0 if k < 20 else -1.0, False, 0.05, w)
            self.assertLessEqual(p.speed, last + 1e-9)
            last = p.speed
        p.vx, p.vy = 60.0, 0.0
        drive(p, 0.0, 0.0, False, 0.05, w)
        self.assertLessEqual(p.speed, vehicles.MAX_ROAD_SPEED + 1e-9)

    def test_helicopter_caps_speed_and_doubles_climb_and_descent_rates(self):
        w = SimpleNamespace(ground_y=lambda _x, _y: 0.0, buildings=[])
        heli_kind = next(iter(vehicles.FLY))
        p = Body(0.0, 0.0, 0.0, heli_kind)
        p.az, p.vx, p.air = 1000.0, 60.0, True
        fly(p, None, 0.05, w)
        self.assertLessEqual(p.speed, vehicles.MAX_HELI_SPEED)
        up = Body(0.0, 0.0, 0.0, heli_kind)
        up.az, up.rpm, up.player_car = 1000.0, 1.0, True
        for _ in range(200):
            fly(up, {"handbrake": True, "run": False, "throttle": 0.0, "steer": 0.0}, 0.05, w)
        self.assertAlmostEqual(up.vz, 14.0, delta=0.1)
        down = Body(0.0, 0.0, 0.0, heli_kind)
        down.az, down.rpm, down.player_car, down.vz = 1000.0, 1.0, True, -14.0
        for _ in range(200):
            fly(down, {"handbrake": False, "run": True, "throttle": 0.0, "steer": 0.0}, 0.05, w)
        self.assertAlmostEqual(down.vz, -14.0, delta=0.1)

    def test_road_below_does_not_trigger_lead_braking(self):
        traffic = Traffic(SimpleNamespace(edges=[]), random.Random(1))
        c, lead = Car(), Car()
        c.h, c.gz = 0.0, 6.0
        c.x = c.y = 0.0
        c.kind = 1
        traffic.hash[(0, 0)] = [(9.0, 0.0, 1.0, 2.0, lead, 0.0, 0.0)]
        self.assertIsNone(traffic.scan(c, 20.0))
        traffic.hash[(0, 0)] = [(9.0, 0.0, 1.0, 2.0, lead, 0.0, 6.0)]
        self.assertGreater(traffic.scan(c, 20.0), 0.0)

    def test_preemption_clears_conflicting_green_before_serving_siren(self):
        w = SimpleNamespace(edges=[edge(0, 1, (-30, 0), (0, 0)), edge(2, 1, (0, -30), (0, 0))],
                            signals=[(1, 0, 1, 0, -7, 0, 0, 0, 3, 8), (1, 1, 1, 1, 0, -7, 0, 0, 3, 8)])
        lights = signals.Signals(w)
        self.assertEqual((lights.state(0), lights.state(1)), (0, 2))
        lights.preempt(0, -20, math.pi / 2)
        self.assertEqual((lights.state(0), lights.state(1)), (1, 2))
        lights.update(signals.YELLOW)
        self.assertEqual((lights.state(0), lights.state(1)), (2, 2))
        lights.update(signals.CLEAR)
        self.assertEqual((lights.state(0), lights.state(1)), (2, 0))

    def test_green_signal_does_not_inherit_red_from_next_link(self):
        edges = [edge(0, 1, (-30, 0), (0, 0)), edge(1, 2, (0, 0), (4, 0))]
        traffic = Traffic(SimpleNamespace(edges=edges), random.Random(1))
        c = Car()
        c.e, c.d, c.s, c.nxt = 0, 1, 10.0, (1, 1)
        c.kind = 1
        sg = SimpleNamespace(state_of=lambda e, end: 0 if e == 0 else 2, stopd={(1, 1): 8.0})
        self.assertIsNone(traffic._red_rem(c, 30.0, sg))
        sg.state_of = lambda e, end: None if e == 0 else 2
        self.assertAlmostEqual(traffic._red_rem(c, 30.0, sg), 16.0 - vehicles.HALF_L[c.kind] - 3.0)


if __name__ == "__main__":
    unittest.main()
