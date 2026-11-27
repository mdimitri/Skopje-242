"""Headless checks for pedestrian encounters and bump escalation."""
import math
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import actors
import talk
import vehicles


class Encounters(unittest.TestCase):
    def setUp(self):
        self.world = SimpleNamespace(level=lambda *args: 0.0)
        self.peds = actors.Peds(self.world, random.Random(4), target=0)
        self.peds._avoid_traffic = lambda *args: False
        self.peds._separate = lambda *args: None
        self.p = actors.Ped()
        self.p.x, self.p.y, self.p.gz = 2.0, 0.0, 0.0
        self.p.arch = next(i for i, stats in enumerate(vehicles.FIGHT) if stats[0] > 16)
        self.p.encounter = 5.0
        self.peds.list = [self.p]
        self.peds.walker = actors.Walker(0.0, 0.0, 0.0)
        self.peds.walker.az = 0.0
        self.events = []

    def event(self, kind, **data):
        self.events.append((kind, data))

    def test_approaches_faces_and_speaks(self):
        for _ in range(3):
            self.peds.update(0.5, 0.0, 0.0, [], self.event)
        self.assertAlmostEqual(self.p.x, 1.25)
        self.assertAlmostEqual(abs(self.p.h), math.pi)
        self.assertTrue(self.p.encounter_spoke)
        self.assertEqual(len(self.events), 1)
        self.assertIn(self.events[0][1]["text"], [talk.encounter_line("open", random.Random(i)) for i in range(20)])

    def test_three_bumps_trigger_fight(self):
        for _ in range(2):
            self.peds._bumped(self.p, self.peds.walker, self.event)
            self.assertEqual(self.p.mode, "walk")
        self.peds._bumped(self.p, self.peds.walker, self.event)
        self.assertEqual(self.p.mode, "fight")
        self.assertEqual(len(self.events), 3)


if __name__ == "__main__":
    unittest.main()
