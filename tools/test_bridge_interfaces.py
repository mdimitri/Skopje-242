"""Bridge approach, deck geometry and lane-marking regressions."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junction_net as jn
import underpass
from roads_candidate import build_tile
from roads_designer import deck_feet, drape_feet


def edge(a, b, points, **tags):
    return dict(a=a, b=b, pts=points, len=LineString(points).length, w=7.0,
                drive=True, walk=True, bridge=True, road=0, ow=False,
                cls="primary", lanes=2, **tags)


class BridgeInterfaces(unittest.TestCase):
    def test_explicit_lower_layer_becomes_underpass_only_below_crossing_deck(self):
        bridge = dict(bridge=True, drive=True, layer=2, nodes=[1, 2], pts=[(-10, 0), (10, 0)])
        lower = dict(bridge=False, drive=True, layer=-1, nodes=[3, 4], pts=[(0, -8), (0, 8)])
        untagged = dict(lower, layer=0)
        nearby = dict(lower, pts=[(15, -8), (15, 8)])
        shared_junction = dict(lower, nodes=[1, 4])
        underpass.infer_layered_underpasses([bridge, lower, untagged, nearby, shared_junction])
        self.assertTrue(lower["tunnel"])
        self.assertFalse(any(road.get("tunnel") for road in (untagged, nearby, shared_junction)))

    def test_candidate_draws_grounded_bridge_approach(self):
        ground = edge(0, 1, [(-30, 0), (0, 0)])
        ground.update(bridge=False, road=1)
        bridge = edge(1, 2, [(0, 0), (100, 0)])
        deck = SimpleNamespace(at=lambda x, y: (max(0, x - 10) * 0.05, x, abs(y)))
        terrain = SimpleNamespace(h=lambda x, y: np.zeros_like(x))
        feet = deck_feet([ground, bridge], {0: deck}, terrain)
        self.assertEqual(bridge["span"], (10.0, 100.0))
        self.assertEqual(feet[0]["pts"], [(0.0, 0.0), (10.0, 0.0)])
        way = dict(id=10, nodes=[100, 101], tags=dict(highway="primary", lanes="2", width="7"))
        line = LineString(ground["pts"])
        source = SimpleNamespace(features=[("road", way, line)], index=STRtree([line]),
                                 road_ids=[20, 10], node_ids={0: 100, 1: 101, 2: 102},
                                 originals={10: 10}, tags={10: way["tags"], 20: way["tags"]},
                                 references=[], reviewed=None, relations=[])
        mesh = build_tile(source, [ground, bridge, *feet], 0, 0, 120)
        triangles = np.asarray(mesh.P).reshape(-1, 3, 3)
        asphalt = unary_union([Polygon(t[:, [0, 2]]) for t in triangles if np.allclose(t[:, 1], 0)])
        for x in (-1, 0, 5, 9.99):
            self.assertTrue(asphalt.covers(Point(x, 0)), x)
        self.assertFalse(asphalt.covers(Point(20, 0)))

    def test_rising_bridge_mouth_follows_the_deck_instead_of_flat_terrain(self):
        ground = edge(0, 1, [(-30, 0), (0, 0)])
        ground["bridge"] = False
        bridge = edge(1, 2, [(0, 0), (100, 0)])
        deck = SimpleNamespace(at=lambda x, y: (x * 0.1, x, abs(y)))
        terrain = SimpleNamespace(h=lambda x, y: np.zeros_like(x))
        feet = deck_feet([ground, bridge], {0: deck}, terrain)
        self.assertEqual(bridge["span"], (2.0, 100.0))
        points = np.array([[[0, 0, -3.5], [2, 0, 3.5], [1, 0, 0]],
                           [[-1, 0, 0], [3, 0, 0], [1, 0, 20]]], dtype=float)
        drape_feet(points, feet, {0: deck}, terrain, 0, 0)
        np.testing.assert_allclose(points[:, :, 1], [[0, 0.2, 0.1], [0, 0, 0]])

    def test_sloping_surface_and_paint_follow_runtime_widths(self):
        e = edge(0, 1, [(0, 0), (30, 0)], directional_lanes=(2, 1))
        e.update(w=10.5, lanes=3, span=(0, 30))
        d = dict(e=e, ln=LineString(e["pts"]), hw=5.25, per=2)
        deck = SimpleNamespace(at=lambda x, y: (x * 0.1 + 10, x, abs(y)))
        mesh = jn.port_decks([d], [d], 0, 0, {0: deck}, None)
        points = np.asarray(mesh.P)
        n = int(30 / 0.75)
        surface = points[:n * 6]
        np.testing.assert_allclose(surface[:, 1], 10.06 + surface[:, 0] * 0.1)
        paint = points[np.isclose(points[:, 1], 10.08 + points[:, 0] * 0.1)]
        # Forward lane divider at +1.75 m, asymmetric centre divider at -1.75 m.
        for offset in (1.675, 1.825, -1.665, -1.555, -1.945, -1.835):
            self.assertTrue(np.any(np.isclose(paint[:, 2], offset)), offset)

    def test_stacked_bridges_do_not_share_a_median(self):
        a = edge(0, 1, [(0, 0), (30, 0)])
        a.update(ow=True)
        b = dict(a, pts=[(0, 10), (30, 10)], road=1)
        da = dict(e=a, ln=LineString(a["pts"]), hw=3.5, per=2)
        db = dict(e=b, ln=LineString(b["pts"]), hw=3.5, per=2)
        decks = {i: SimpleNamespace(at=lambda x, y, h=h: (h, x, abs(y))) for i, h in ((0, 10), (1, 20))}
        alone = jn.port_decks([da], [da], 0, 0, decks, None)
        stacked = jn.port_decks([da, db], [da], 0, 0, decks, None)
        np.testing.assert_allclose(alone.P, stacked.P)

    def test_split_edges_of_one_bridge_do_not_form_a_twin(self):
        a = edge(0, 1, [(0, 0), (10, 0)])
        a["ow"] = True
        b = dict(a, pts=[(10, 0), (20, 0)])
        da = dict(e=a, ln=LineString(a["pts"]), hw=3.5, per=2)
        db = dict(e=b, ln=LineString(b["pts"]), hw=3.5, per=2)
        decks = {0: SimpleNamespace(at=lambda x, y: (10, x, abs(y)))}
        alone = jn.port_decks([da], [da], 0, 0, decks, None)
        split = jn.port_decks([da, db], [da], 0, 0, decks, None)
        np.testing.assert_allclose(alone.P, split.P)


if __name__ == "__main__":
    unittest.main()
