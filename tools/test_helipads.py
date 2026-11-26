"""Helicopters must spawn and settle on the rendered hospital pad surfaces."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import actors
import geo
from world import World


class HelipadTests(unittest.TestCase):
    def make_sim(self, roof_height):
        w = World.__new__(World)
        w.hx = w.hy = 10000
        w.pg2, w.buildings = {}, []
        w.ground_y = lambda x, y: 250.0
        w.nearest_drive_point = lambda *args: None
        if roof_height:
            for lat, lon, _ in actors.HELI_PADS:
                x, y = geo.project(lat, lon)
                ring = [(x - 20, y - 20), (x + 20, y - 20), (x + 20, y + 20), (x - 20, y + 20)]
                w.buildings.append(dict(bb=(x - 20, y - 20, x + 20, y + 20), ring=ring, h=roof_height))
        sim = actors.Sim.__new__(actors.Sim)
        sim.w, sim.bodies = w, []
        with patch.object(sim, "_clear_pad"), patch.object(actors, "_mesh_top", return_value=None):
            sim._make_helis()
        return sim

    def test_all_five_pads_support_parked_and_landing_helicopters(self):
        for roof_height in (0.0, 12.0):
            sim = self.make_sim(roof_height)
            self.assertEqual(len(sim.bodies), 5)
            for body, (_, _, z, _) in zip(sim.bodies, sim.helipads):
                with self.subTest(roof_height=roof_height, x=body.x, y=body.y):
                    surface = z + 0.18  # top of the H marking in render.py
                    self.assertAlmostEqual(body.az, surface)
                    for _ in range(600):
                        actors.fly(body, None, 0.05, sim.w)
                    self.assertAlmostEqual(body.az, surface)
                    body.az, body.vz = surface + 15.0, -8.0
                    for _ in range(600):
                        actors.fly(body, None, 0.05, sim.w)
                    self.assertAlmostEqual(body.az, surface)
                    body.x += 40.0  # leaving the pad must allow descent to ground
                    for _ in range(600):
                        actors.fly(body, None, 0.05, sim.w)
                    self.assertAlmostEqual(body.az, 250.0)


if __name__ == "__main__":
    unittest.main()
