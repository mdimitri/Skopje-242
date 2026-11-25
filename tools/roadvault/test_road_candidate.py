"""Regression check for the two Partizanski / Glavinov slip-lane splits."""
import json
import math
import unittest

import numpy as np

from shapely.geometry import box, shape
from shapely.ops import unary_union

from run_candidate import HERE, ROOT, site_inputs
from road_candidate import compile_movements, compile_scene, polys


@unittest.skipUnless((ROOT / "data/osm/roads.json").exists() and (ROOT / "data/osm/areas.json").exists(),
                     "Requires the local OSM road and area extracts")
class RoadCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = json.loads((HERE / "partizanski_glavinov.json").read_text(encoding="utf-8"))
        radius = cls.layout["radius"]
        cls.bounds = box(-radius, -radius, radius, radius)
        cls.edges, cls.walks, cls.greens = site_inputs(cls.layout, ROOT / "data/osm", cls.bounds)
        cls.routes = {spec["id"]: path for spec, path in
                      compile_movements({edge.id: edge for edge in cls.edges}, cls.layout["movements"])}

    def test_slips_keep_a_full_lane_of_clearance_from_the_adjacent_movement(self):
        for slip, adjacent in (("W-S-slip", "W-N-2"), ("N-W-slip", "N-S-2")):
            with self.subTest(slip=slip):
                self.assertGreaterEqual(self.routes[slip].distance(self.routes[adjacent]), 3.24)

    def test_slip_heading_changes_gradually(self):
        for slip in ("W-S-slip", "N-W-slip"):
            with self.subTest(slip=slip):
                path = self.routes[slip]
                stations = np.linspace(0, path.length, math.ceil(path.length / 0.5) + 1)
                steps = np.diff([path.interpolate(station).coords[0] for station in stations], axis=0)
                headings = np.unwrap(np.arctan2(steps[:, 1], steps[:, 0]))
                self.assertLess(np.max(np.abs(np.degrees(np.diff(headings, n=2)))), 0.75)

    def test_walk_surfaces_connect_crossings_without_osm_footways(self):
        *_, with_paths = compile_scene(self.edges, self.layout, self.walks, self.greens, self.bounds)
        *_, without_paths = compile_scene(self.edges, self.layout, [], self.greens, self.bounds)
        self.assertFalse(shape(with_paths["footpath_links"]).is_empty)
        self.assertTrue(shape(without_paths["footpath_links"]).is_empty)
        for key in ("sidewalks", "crossing_landings", "crosswalks", "non_walkable_curbs"):
            self.assertEqual(with_paths[key], without_paths[key])
        sidewalks, landings, crossings, curbs = (
            shape(without_paths[key]) for key in ("sidewalks", "crossing_landings", "crosswalks", "non_walkable_curbs")
        )
        walkable = unary_union([sidewalks, landings, crossings])
        self.assertLess(curbs.intersection(walkable).area, 0.01)
        self.assertEqual(len(polys(crossings)), 8)
        self.assertTrue(any(component.covers(crossings) for component in polys(walkable.buffer(0.04))))


if __name__ == "__main__":
    unittest.main()
