"""Traffic lab: the game's traffic on a 2D map, with settings, edits, incidents and seeded batch reports.
    python tools/traffic_lab.py                       full-screen UI (trafficSimulator.bat)
    python tools/traffic_lab.py --windowed            in a 1600 x 900 window
    python tools/traffic_lab.py --batch spec.json     headless batch -> trafficlab/batches/<time>/report.html
    python tools/traffic_lab.py --shot out.png        UI screenshot test (runs a few seconds, then saves the screen)
--world / --osm choose the built world and its OSM folder (default data/cache/world and data/osm, as the game)."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trafficlab  # noqa: E402,F401  (puts src/ first on sys.path)
from trafficlab import ROOT  # noqa: E402


def fmt_best(e):
    b = e.best()
    return "-" if b is None or b.get("score") is None else f"c{b['id']} {b['score']:.1f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world", default=os.path.join(ROOT, "data", "cache", "world"))
    ap.add_argument("--osm", default=os.environ.get("SK242_OSM_DIR") or os.path.join(ROOT, "data", "osm"))
    ap.add_argument("--batch", help="run a batch spec (JSON) headless")
    ap.add_argument("--explore", help="run an explore spec (JSON) headless: search rules / constants, validate the best")
    ap.add_argument("--out", help="batch output folder")
    ap.add_argument("--scenario", help="scenario JSON to open in the UI")
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--size", default="1600x900")
    ap.add_argument("--shot", help="UI test: save a screenshot after --frames frames and quit")
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--tab", default=None, help="UI test: open this tab")
    ap.add_argument("--layer", default=None, help="UI test: map colouring")
    ap.add_argument("--report", help="UI test: load this batch folder into the Report tab")
    a = ap.parse_args()
    if a.batch:
        from trafficlab import batch
        with open(a.batch, encoding="utf-8") as f:
            spec = json.load(f)
        spec.setdefault("world", a.world)
        spec.setdefault("osm", a.osm)
        if not os.path.isdir(spec["world"]):
            print(f"No built world at {spec['world']}")
            return 1
        if "scenario" not in spec:
            from world import World
            from trafficlab import core
            spec["scenario"] = core.default_scenario(World(spec["world"]))
        summary, out = batch.run(spec, a.out, progress=lambda d, n, t: print(f"[{d}/{n}] {t}", flush=True))
        print("report:", os.path.join(out, "report.html"))
        return 0
    if a.explore:
        from trafficlab import explore
        with open(a.explore, encoding="utf-8") as f:
            spec = json.load(f)
        spec.setdefault("world", a.world)
        spec.setdefault("osm", a.osm)
        if "scenario" not in spec:
            from world import World
            from trafficlab import core
            spec["scenario"] = core.default_scenario(World(spec["world"]))
        ex = explore.Explorer(spec, progress=lambda e, t: print(f"[explore] {t}  best {fmt_best(e)}", flush=True)).run()
        for i, c in enumerate(ex.leader):
            print(f"#{i + 1} c{c['id']} search {c['score']:.1f}±{c['ci']:.1f}  validated {c.get('vscore', 0):.1f}±{c.get('vci', 0):.1f}  "
                  f"vs game {c.get('vdiff') or 0:+.1f} (p={c.get('vp') if c.get('vp') is not None else 1:.3f})  {c['settings']}")
        print("folder:", ex.out)
        return 0
    if not os.path.isdir(a.world):
        print(f"No built world at {a.world}: start the game once (run.bat) so it builds the world, or pass --world.")
        input("Press Enter to close.") if sys.stdin and sys.stdin.isatty() else None
        return 1
    from trafficlab import ui
    return ui.run(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
