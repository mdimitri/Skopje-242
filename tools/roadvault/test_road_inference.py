"""Synthetic OSM cases exercise the city's shared inference rules without map downloads."""
import json
from pathlib import Path
import tempfile
import unittest

from shapely.geometry import box, shape

from run_candidate import compile_scene, infer_site
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

    def test_balanced_one_way_fork_reserves_the_outer_lane_for_its_slip(self):
        movements = self.infer([
            way(101, [2, 1], [(0, 0), (-50, 0)], lanes="3", oneway="-1"),
            way(102, [2, 3], [(0, 0), (50, -2)], lanes="2", oneway="yes"),
            way(103, [2, 4, 5], [(0, 0), (18, 5), (43, 20)], highway="tertiary_link", lanes="1", oneway="yes"),
        ])
        self.assertEqual({(m["from"], m["from_direction"], m["from_lane"], m["to"]) for m in movements},
                         {(101, 1, 0, 102), (101, 1, 1, 102), (101, 1, 2, 103)})

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


if __name__ == "__main__":
    unittest.main()
