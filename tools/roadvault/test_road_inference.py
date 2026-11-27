"""Synthetic OSM cases exercise the city's shared inference rules without map downloads."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import unary_union

from run_candidate import ROOT, compile_scene, infer_site
from road_candidate import crossing_span, edge_band, footprint, polys
from geo import LAT0, LON0, M_LAT, M_LON


def geo(x, y):
    return {"lat": LAT0 - y / M_LAT, "lon": LON0 + x / M_LON}


def way(osm_id, nodes, coords, **tags):
    return dict(type="way", id=osm_id, nodes=nodes, geometry=[geo(*point) for point in coords],
                tags={"highway": "tertiary", **tags})


def restriction(osm_id, from_way, via, to_way, kind, via_type="node"):
    return dict(type="relation", id=osm_id, tags={"type": "restriction", "restriction": kind},
                members=[dict(role="from", ref=from_way, type="way"), dict(role="via", ref=via, type=via_type),
                         dict(role="to", ref=to_way, type="way")])


class OsmInferenceTests(unittest.TestCase):
    def infer(self, elements):
        self.layout = dict(version=1, name="Test", origin=(LAT0, LON0), radius=75)
        self.bounds = box(-75, -75, 75, 75)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "roads.json").write_text(json.dumps({"elements": elements}), encoding="utf-8")
            self.edges, self.walks, self.greens, self.originals, self.report = infer_site(
                self.layout, directory, self.bounds)
        return self.layout["movements"]

    def test_t_junction_splits_the_way_at_the_shared_interior_node(self):
        movements = self.infer([
            way(101, [1, 2, 3], [(-45, 0), (0, 0), (45, 0)], lanes="2"),
            way(102, [2, 4], [(0, 0), (0, 50)], lanes="2"),
        ])
        self.assertEqual(len(self.edges), 3)
        self.assertEqual(len(movements), 6)
        self.assertTrue(all(move["node"] == 2 for move in movements))
        self.assertEqual(sum(move["turn"] == "through" for move in movements), 2)
        result = compile_scene(self.edges, self.layout, self.walks, self.greens, self.bounds)
        self.assertTrue(result[3].is_valid)

    def test_four_to_two_lane_merge_tapers_to_the_receiving_width(self):
        self.infer([
            way(101, [1, 2], [(-12, 0), (0, 0)], name="Boulevard", lanes="4", oneway="yes"),
            way(102, [2, 3], [(0, 0), (35, 0)], name="Boulevard", lanes="2", oneway="yes"),
        ])
        wide, narrow = (next(edge for edge in self.edges if edge.id == way) for way in (101, 102))
        self.assertAlmostEqual(np.diff(wide.cross_section(wide.line.length)).item(), narrow.section["w"])
        self.assertAlmostEqual(np.diff(wide.cross_section(0)).item(), wide.section["w"])
        self.assertGreaterEqual(wide.section["tapers"][0][1], 10)

    def test_slip_merge_does_not_hide_additional_widening(self):
        self.infer([
            way(101, [1, 2], [(-60, 0), (0, 0)], name="Boulevard", lanes="2", oneway="yes"),
            way(102, [2, 3], [(0, 0), (65, 0)], name="Boulevard", lanes="4", oneway="yes"),
            way(103, [4, 2], [(-40, 15), (0, 0)], highway="tertiary_link", lanes="1", oneway="yes"),
        ])
        wide = next(edge for edge in self.edges if edge.id == 102)
        self.assertAlmostEqual(np.diff(wide.cross_section(0)).item(), wide.section["w"] * 3 / 4)
        self.assertAlmostEqual(np.diff(wide.cross_section(50)).item(), wide.section["w"])
        main = next(edge for edge in self.edges if edge.id == 101)
        slip = next(edge for edge in self.edges if edge.id == 103)
        self.assertAlmostEqual(main.cross_section(main.line.length)[0], wide.cross_section(0)[0], places=5)
        self.assertGreater(slip.cross_section(slip.line.length).mean(), 2)

    def test_unmapped_major_junction_crossings_and_cycle_lane_are_drawn(self):
        self.infer([
            way(101, [1, 2, 3], [(-50, 0), (0, 0), (50, 0)], lanes="2", **{"cycleway:right": "lane"}),
            way(102, [4, 2, 5], [(0, -50), (0, 0), (0, 50)], lanes="2"),
        ])
        self.assertGreaterEqual(len(self.layout["crossings"]), 3)
        self.assertTrue(any(edge.section.get("cycle_sides") == ["right"] for edge in self.edges))
        self.assertTrue(any(sign[0] == "cycleway" for sign in self.layout["signs"]))
        _, _, _, _, furniture, pedestrian = compile_scene(
            self.edges, self.layout, self.walks, self.greens, self.bounds, self.report)
        self.assertTrue(any(device["kind"] == "cycleway" for device in furniture))
        self.assertGreater(shape(pedestrian["crosswalks"]).area, 10)

    def test_balanced_one_way_fork_reserves_the_outer_lane_for_its_slip(self):
        movements = self.infer([
            way(101, [2, 1], [(0, 0), (-50, 0)], lanes="3", oneway="-1"),
            way(102, [2, 3], [(0, 0), (50, -2)], lanes="2", oneway="yes"),
            way(103, [2, 4, 5], [(0, 0), (18, 5), (43, 20)], highway="tertiary_link", lanes="1", oneway="yes"),
        ])
        self.assertEqual({(m["from"], m["from_direction"], m["from_lane"], m["to"]) for m in movements},
                         {(101, 1, 0, 102), (101, 1, 1, 102), (101, 1, 2, 103)})

    def test_balanced_right_fork_aligns_main_and_slip_lanes(self):
        self.infer([
            way(101, [1, 2], [(-60, 0), (0, 0)], lanes="4", oneway="yes"),
            way(102, [2, 3], [(0, 0), (60, 0)], lanes="3", oneway="yes"),
            way(103, [2, 4], [(0, 0), (60, 15)], highway="tertiary_link", lanes="1", oneway="yes"),
        ])
        source, main, slip = (next(e for e in self.edges if e.id == i) for i in (101, 102, 103))
        self.assertAlmostEqual(source.cross_section(source.line.length)[0], main.cross_section(0)[0], places=5)
        source_lane, _ = source.port(source.line.length, 3, 1)
        slip_lane, _ = slip.port(0, 0, 1)
        self.assertLess(np.linalg.norm(source_lane - slip_lane), 1.5)
        self.assertAlmostEqual(main.cross_section(25)[0], -main.section["w"] / 2, places=5)

    def test_right_slip_joins_the_outer_lane_without_adding_a_lane(self):
        self.infer([
            way(101, [1, 2], [(-60, 0), (0, 0)], lanes="3", oneway="yes"),
            way(102, [2, 3], [(0, 0), (60, 0)], lanes="3", oneway="yes"),
            way(103, [4, 2], [(-60, 15), (0, 0)], highway="tertiary_link", lanes="1", oneway="yes"),
        ])
        main, receiving, slip = (next(e for e in self.edges if e.id == i) for i in (101, 102, 103))
        np.testing.assert_allclose(main.cross_section(main.line.length), receiving.cross_section(0))
        slip_lane, _ = slip.port(slip.line.length, 0, 1)
        outside, _ = receiving.port(0, 2, 1)
        self.assertLess(np.linalg.norm(slip_lane - outside), 0.9)

    def test_turn_restrictions_and_lane_marks_constrain_the_crossroads(self):
        movements = self.infer([
            way(101, [1, 2], [(-40, 0), (0, 0)], lanes="2", oneway="yes", **{"turn:lanes": "left|through;right"}),
            way(102, [2, 3], [(0, 0), (45, 0)], lanes="2", oneway="yes"),
            way(103, [2, 4], [(0, 0), (0, -45)], lanes="1", oneway="yes"),
            way(104, [2, 5], [(0, 0), (0, 45)], lanes="1", oneway="yes"),
            restriction(900, 101, 2, 104, "no_right_turn"),
        ])
        self.assertEqual({(m["from_lane"], m["to"], m["turn"]) for m in movements},
                         {(0, 103, "left"), (1, 102, "through")})

    def test_unsupported_via_way_restriction_withholds_the_affected_approach(self):
        movements = self.infer([
            way(101, [1, 2], [(-45, 0), (0, 0)], lanes="2", oneway="yes"),
            way(102, [2, 3], [(0, 0), (45, 0)], lanes="2", oneway="yes"),
            way(103, [3, 4], [(45, 0), (45, 30)], lanes="1", oneway="yes"),
            restriction(901, 101, 102, 103, "no_right_turn", via_type="way"),
        ])
        self.assertTrue(any(m["from"] == 102 for m in movements))
        self.assertFalse(any(m["from"] == 101 for m in movements))
        self.assertTrue(any(d["kind"] == "unsupported_relation" and d["relation"] == 901 for d in self.report))

    def test_grade_separation_and_crossings_without_shared_nodes_do_not_create_turns(self):
        movements = self.infer([
            way(101, [1, 2, 3], [(-50, 0), (0, 0), (50, 0)], lanes="2"),
            way(102, [4, 2, 5], [(0, -45), (0, 0), (0, 45)], bridge="yes", layer="1"),
            way(103, [6, 7], [(15, -45), (15, 45)], lanes="2"),
        ])
        self.assertEqual(movements, [])
        self.assertEqual({edge.id for edge in self.edges}, {101, 103})
        self.assertIn(dict(kind="grade_separated_way", way=102), self.report)

    def test_tagged_zebra_on_a_signalized_one_way_approach_gets_a_gantry(self):
        self.infer([
            way(101, [1, 9, 2], [(-45, 0), (-15, 0), (0, 0)], lanes="2", oneway="yes"),
            way(102, [2, 3], [(0, 0), (45, 0)], lanes="2", oneway="yes"),
            way(103, [2, 4], [(0, 0), (0, 45)], lanes="1", oneway="yes"),
            dict(type="node", id=2, tags={"highway": "traffic_signals"}, **geo(0, 0)),
            dict(type="node", id=9, tags={"highway": "crossing", "crossing": "marked"}, **geo(-15, 0)),
        ])
        self.assertEqual(self.layout["stop_lines"], [101])
        *_, furniture, _ = compile_scene(self.edges, self.layout, self.walks, self.greens, self.bounds, self.report)
        gantry = next(item for item in furniture if item["kind"] == "vehicle_gantry")
        self.assertEqual(len(gantry["heads"]), 2)
        self.assertEqual(sum(item["kind"] == "pedestrian_signal" for item in furniture), 2)

    def test_roundabout_stays_one_way_and_does_not_join_nonadjacent_arms(self):
        movements = self.infer([
            way(101, [1, 2, 3, 4, 1], [(0, -16), (-16, 0), (0, 16), (16, 0), (0, -16)],
                junction="roundabout", lanes="1"),
            way(102, [2, 5], [(-16, 0), (-53, 0)], lanes="2"),
            way(103, [4, 6], [(16, 0), (53, 0)], lanes="2"),
        ])
        self.assertTrue(any(self.originals[m["from"]] == 102 and self.originals[m["to"]] == 101 for m in movements))
        self.assertTrue(any(self.originals[m["from"]] == 101 and self.originals[m["to"]] == 103 for m in movements))
        for move in movements:
            ports = (("from", "from_direction"), ("to", "to_direction"))
            self.assertEqual({move[direction] for edge, direction in ports if self.originals[move[edge]] == 101}
                             - {1}, set())
            self.assertNotEqual({self.originals[move["from"]], self.originals[move["to"]]}, {102, 103})

    def test_paired_carriageways_have_outer_sidewalks_and_a_median_cut_through(self):
        self.infer([
            way(101, [1, 2], [(-50, 7), (50, 7)], name="Divided Boulevard", lanes="2", oneway="yes"),
            way(102, [3, 4], [(50, -7), (-50, -7)], name="Divided Boulevard", lanes="2", oneway="yes"),
            way(103, [5, 6], [(0, 14), (0, -14)], highway="footway", footway="crossing"),
        ])
        self.assertEqual(self.layout["road_edges"], {"101": ["curb", "sidewalk"], "102": ["curb", "sidewalk"]})
        self.assertEqual(len(self.layout["median_corridors"]), 1)
        self.assertEqual([way for way, _ in self.layout["crossings"][0]], [101, 102])
        *_, pedestrian = compile_scene(self.edges, self.layout, self.walks, self.greens, self.bounds)
        self.assertGreater(shape(pedestrian["median_cut_throughs"]).area, 12)


@unittest.skipUnless((ROOT / "data/osm/roads.json").exists(), "Requires the local Skopje OSM extract")
class SkopjeInferenceTests(unittest.TestCase):
    def test_slip_islands_have_crossings_with_walkable_landings(self):
        for origin, island_count in [((42.0038599, 21.3902603), 4), ((42.0004324, 21.4270569), 2)]:
            with self.subTest(origin=origin):
                bounds = box(-115, -115, 115, 115)
                layout = dict(origin=origin, radius=115)
                edges, walks, greens, _, report = infer_site(layout, ROOT / "data/osm", bounds)
                _, _, _, asphalt, _, pedestrian = compile_scene(edges, layout, walks, greens, bounds, report)
                by_id = {edge.id: edge for edge in edges}
                walkable = unary_union([shape(pedestrian[name]) for name in
                                        ("sidewalks", "footpath_links", "median_cut_throughs")])
                for group in layout["crossings"]:
                    for way, station in group:
                        point, _, right, lo, hi = crossing_span(by_id[way], station, asphalt)
                        for lateral in (lo - 0.3, hi + 0.3):
                            self.assertLessEqual(walkable.distance(Point(point + right * lateral)), 2)
                raw = unary_union([polygon for edge in edges for polygon in polys(footprint(edge))])
                holes = [Polygon(ring) for polygon in polys(raw) for ring in polygon.interiors
                         if 15 <= Polygon(ring).area <= 420]
                slips = [edge for edge in edges if edge.section["ow"] and edge.section["cls"].endswith("_link")]
                islands = [hole for hole in holes if any(
                    hole.boundary.intersection(edge_band(edge, "left", 0.55).buffer(1)).length >= 3 for edge in slips)]
                self.assertEqual(len(islands), island_count)
                crossings = shape(pedestrian["crosswalks"])
                self.assertTrue(all(island.distance(crossings) < 0.1 for island in islands))
                for edge in slips:
                    self.assertAlmostEqual(edge.section["w"], 4.875)

    def test_boulevard_tapers_and_outer_slip_sidewalks(self):
        sites = [((41.99815, 21.42544), 95, 671715324, 233082416, [16540429, 16552477, 173142133, 173142141]),
                 ((42.00547, 21.41690), 93, 229980925, 669010521, [229986882, 229986884])]
        for origin, radius, wider, narrower, slips in sites:
            with self.subTest(origin=origin):
                bounds = box(-radius, -radius, radius, radius)
                layout = dict(origin=origin, radius=radius)
                edges, walks, greens, originals, report = infer_site(layout, ROOT / "data/osm", bounds)
                wide = next(e for e in edges if originals[e.id] == wider and "lane_taper" in e.section)
                narrow = next(e for e in edges if originals[e.id] == narrower and set(e.nodes) & set(wide.nodes))
                end, length, _ = wide.section["lane_taper"]
                start = 0 if end == "start" else wide.line.length
                finish = length if end == "start" else wide.line.length - length
                self.assertGreater(length, 20)
                self.assertLessEqual(length, 50)
                self.assertAlmostEqual(np.diff(wide.cross_section(start)).item(), narrow.section["w"])
                self.assertAlmostEqual(np.diff(wide.cross_section(finish)).item(), wide.section["w"])
                self.assertEqual(wide.section["lanes"] - narrow.section["lanes"], 1)
                _, _, _, asphalt, _, pedestrian = compile_scene(edges, layout, walks, greens, bounds, report)
                walkable = unary_union([shape(pedestrian[key]) for key in ("sidewalks", "crossing_landings")])
                for way in slips:
                    self.assertEqual(layout["road_edges"][str(way)], ["curb", "sidewalk"])
                    edge = next(item for item in edges if item.id == way)
                    p, _, right, _, hi = crossing_span(edge, edge.line.length * 0.5, asphalt)
                    probe = LineString([p + (hi + 0.04) * right, p + (hi + 1.7) * right])
                    self.assertGreater(walkable.intersection(probe).length, 1.3)
                if wider == 671715324:
                    cuts = shape(pedestrian["median_cut_throughs"])
                    self.assertTrue(any(cuts.covers(Point(x, 17)) for x in (-4, -3, -2)))
                    for y in (23, 27, 31, 35, 39, 43, 47, 55, 65):
                        # These transects span the two inner curb lines of the south leg.
                        probe = LineString([(-10, y), (0, y)])
                        self.assertGreater(probe.difference(asphalt).length, 0.7, y)


if __name__ == "__main__":
    unittest.main()
