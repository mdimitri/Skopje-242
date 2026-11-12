"""Headless full photogrammetric build (ДЕТАЛИ) over a whole capture folder, then apply it to the game.
Resumable: re-running continues from the stored per-photo results.
    python tools/photogram_full.py <capture folder>
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    import photogram as pg
    folder = sys.argv[1]
    osm_dir = os.path.join(ROOT, "data", "osm")
    st, op = pg.load_settings(folder)
    pg.save_settings(folder, st, op)
    job = pg.Job(folder, "detail", None, osm_dir, settings=st)
    job.start()
    t0 = time.time()
    while job.is_alive():
        job.join(60)
        print(f"[progress] {time.time() - t0:7.0f}s  {job.frac * 100:5.1f}%  {job.step}  stats={job.stats}", flush=True)
    if job.error:
        print("[photogram_full] FAILED:", job.error, flush=True)
        sys.exit(1)
    pg.apply_to_game(folder, "detail", osm_dir, op)
    print("[photogram_full] applied to", os.path.join(osm_dir, "photogram.json"), flush=True)


if __name__ == "__main__":
    main()
