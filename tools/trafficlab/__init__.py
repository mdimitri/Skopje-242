"""Traffic lab: a standalone 2D traffic simulator around the game's own traffic code (trafficSimulator.bat).

Nothing here re-implements driving, collisions or signals: core.LabSim builds the game's actors.Sim (Traffic, buses,
emergency services, trains, pedestrians, signals) on a built world and only *observes* it; settings are applied by
setting the game's own module / class constants (params.py), so the lab can never drift away from the game."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SRC = os.path.join(ROOT, "src")
while _SRC in sys.path:
    sys.path.remove(_SRC)
sys.path.insert(0, _SRC)                 # the game's modules first: tools/ has same-named build scripts (stations.py ...)
OUT = os.path.join(ROOT, "trafficlab")               # user data: scenarios, batch results, reports (git-ignored)
