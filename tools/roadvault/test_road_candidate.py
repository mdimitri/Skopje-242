"""Regression check for the two Partizanski / Glavinov slip-lane splits."""
import json
import math
import unittest

import numpy as np

from shapely.geometry import LineString, Point, Polygon, box, shape
from shapely.ops import unary_union

from run_candidate import HERE, ROOT, site_inputs
from road_candidate import (approach_arrows, compile_movements, compile_scene, crossing_span, footprint,
                            median_landscape, polys, yield_teeth)


@unittest.skipUnless((ROOT / "data/osm/roads.json").exists() and (ROOT / "data/osm/areas.json").exists(),
                     "Requires the local OSM road and area extracts")
class RoadCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = json.loads((HERE / "partizanski_glavinov.json").read_text(encoding="utf-8"))
        radius = cls.layout["radius"]
        cls.bounds = box(-radius, -radius, radius, radius)
        cls.edges, cls.walks, cls.greens = site_inputs(cls.layout, ROOT / "data/osm", cls.bounds)
        cls.by_id = {edge.id: edge for edge in cls.edges}
        cls.routes = {spec["id"]: path for spec, path in compile_movements(cls.by_id, cls.layout["movements"])}
        _, _, _, cls.asphalt, cls.pedestrian = compile_scene(cls.edges, cls.layout, cls.walks, cls.greens, cls.bounds)

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
        with_paths = self.pedestrian
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

    def test_south_turn_lane_is_full_width_well_before_the_stop_line(self):
        opening = self.by_id[671891272]
        approach = self.by_id[229984879]
        uphill = opening.section["left_lane_opening"]
        stop = dict(item for group in self.layout["crossings"] for item in group)[approach.id] - 3.4
        self.assertAlmostEqual(opening.line.length - uphill + stop, 25, delta=0.5)
        self.assertAlmostEqual(np.diff(opening.cross_section(0)).item(), 6.5)
        self.assertAlmostEqual(np.diff(opening.cross_section(uphill)).item(), 9.75)
        np.testing.assert_allclose(opening.cross_section(opening.line.length), approach.cross_section(0))
        self.assertGreater(footprint(opening).distance(footprint(self.by_id[190303100])), 2.0)

    def test_median_curb_returns_follow_the_finished_asphalt_edge(self):
        curb = shape(self.pedestrian["non_walkable_curbs"]).buffer(0.05)
        walkable = unary_union([shape(self.pedestrian[key]) for key in ("sidewalks", "crossing_landings")])
        for x, y, radius in self.layout["curb_returns"]:
            with self.subTest(nose=(x, y)):
                edge = self.asphalt.boundary.intersection(Point(x, y).buffer(radius - 0.15))
                edge = edge.difference(walkable.buffer(0.08))
                self.assertGreater(edge.length, 10)
                self.assertLess(edge.difference(curb).length, 0.05)

    def test_mapped_grass_fits_the_raised_median_noses(self):
        reserved = unary_union([self.asphalt, *(shape(self.pedestrian[key])
                                 for key in ("sidewalks", "non_walkable_curbs", "crossing_landings", "footpath_links"))])
        mapped = unary_union(self.greens).intersection(self.bounds).difference(reserved)
        planted = median_landscape(self.by_id, self.layout, self.greens, self.asphalt, self.bounds, reserved)
        self.assertGreater(planted.area, mapped.area)
        self.assertLess(planted.intersection(reserved).area, 0.01)
        for nose in ((-3, -9), (14, -17), (5, 9)):
            with self.subTest(nose=nose):
                self.assertFalse(mapped.covers(Point(nose)))
                self.assertTrue(planted.covers(Point(nose)))

    def test_both_slips_have_raised_refuges_connected_to_their_crossings(self):
        sidewalks, landings, curbs, crossings = (
            shape(self.pedestrian[key])
            for key in ("sidewalks", "crossing_landings", "non_walkable_curbs", "crosswalks")
        )
        island_surfaces = unary_union([sidewalks, landings, curbs])
        holes = [Polygon(ring) for surface in polys(self.asphalt) for ring in surface.interiors]
        for seed, expected_crossings in (((6, -32), 3), ((-10, 5), 2)):
            with self.subTest(island=seed):
                island = next(hole for hole in holes if hole.contains(Point(seed)))
                self.assertGreater(island.intersection(sidewalks).area, 75)
                self.assertLess(island.difference(island_surfaces).area, 0.01)
                connected = [zebra for zebra in polys(crossings) if island.distance(zebra) < 0.04]
                self.assertEqual(len(connected), expected_crossings)

    def test_southbound_merge_sidewalk_follows_the_asphalt_at_full_width(self):
        sidewalk = shape(self.pedestrian["sidewalks"])
        slip, receiving = self.by_id[16544466], self.by_id[190303100]
        for edge, station in ((slip, slip.line.length - 6), (slip, slip.line.length - 1),
                              (receiving, 0), (receiving, 5), (receiving, 10)):
            with self.subTest(way=edge.id, station=station):
                p, _, right, _, hi = crossing_span(edge, station, self.asphalt)
                width_probe = LineString([p + right * (hi + 0.02), p + right * (hi + 2.35)])
                self.assertAlmostEqual(sidewalk.intersection(width_probe).length, 2.33, delta=0.05)

    def test_approach_arrows_and_yield_teeth_fit_clear_of_crossings(self):
        crosswalks = shape(self.pedestrian["crosswalks"])
        stations = dict(item for group in self.layout["crossings"] for item in group)
        arrows = [(way, stations[way] - 7.9) for way in self.layout["stop_lines"]]
        arrows.extend(self.layout["approach_arrows"])
        pavement = self.asphalt.buffer(-0.08)
        for (way, station), expected in zip(arrows, (2, 2, 4, 3, 3, 4, 1, 1), strict=True):
            with self.subTest(arrow_way=way):
                edge = self.by_id[way]
                at = edge.line.length + station if station < 0 else station
                marks = approach_arrows(edge, at, self.layout["movements"])
                self.assertEqual(len(marks), expected)
                self.assertTrue(all(pavement.covers(mark) and mark.distance(crosswalks) > 0.25 for mark in marks))
        for way, station in self.layout["yield_lines"]:
            with self.subTest(yield_way=way):
                teeth = yield_teeth(self.by_id[way], station)
                self.assertEqual(len(teeth), 4)
                self.assertTrue(all(pavement.covers(tooth) and tooth.distance(crosswalks) > 0.25 for tooth in teeth))


if __name__ == "__main__":
    unittest.main()
