"""Regression check for the two Partizanski / Glavinov slip-lane splits."""
import json
import unittest

from shapely.geometry import box

from run_candidate import HERE, ROOT, site_inputs
from road_candidate import compile_movements


class SlipLaneClearanceTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / "data/osm/roads.json").exists() and (ROOT / "data/osm/areas.json").exists(),
                         "Requires the local OSM road and area extracts")
    def test_slips_keep_a_full_lane_of_clearance_from_the_adjacent_movement(self):
        layout = json.loads((HERE / "partizanski_glavinov.json").read_text(encoding="utf-8"))
        radius = layout["radius"]
        edges, _, _ = site_inputs(layout, ROOT / "data/osm", box(-radius, -radius, radius, radius))
        routes = {spec["id"]: path for spec, path in
                  compile_movements({edge.id: edge for edge in edges}, layout["movements"])}
        for slip, adjacent in (("W-S-slip", "W-N-2"), ("N-W-slip", "N-S-2")):
            with self.subTest(slip=slip):
                gap = routes[slip].distance(routes[adjacent])
                self.assertGreaterEqual(gap, 3.24)


if __name__ == "__main__":
    unittest.main()
