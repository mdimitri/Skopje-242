"""Headless full photogrammetric build (ДЕТАЛИ) over a capture folder (or a folder of capture folders), then apply it to the game.
Resumable: re-running continues from the stored per-photo results.
    python tools/photogram_full.py <capture folder>
    python tools/photogram_full.py <capture folder> --bg    (the game's background run, src/photobg.py: fewer worker processes,
        progress in <folder>/_photogram/progress.json, the fits written every few minutes, stops when <folder>/_photogram/stop
        appears; the game applies the fits itself at its next start)
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
CHECKPOINT = float(os.environ.get("SK242_PG_CHECKPOINT", 300))                       # seconds between fit files written while a background run goes on


def _write(path, d):
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except OSError:
        pass                              # the game reads it again in a second; a locked file only skips one update


def main():
    import photogram as pg
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--bg", action="store_true")
    ap.add_argument("--osm", default=os.path.join(ROOT, "data", "osm"))
    a = ap.parse_args()
    folder, osm_dir = a.folder, a.osm
    cache = os.path.join(folder, pg.CACHE)
    os.makedirs(cache, exist_ok=True)
    prog, stopf = os.path.join(cache, "progress.json"), os.path.join(cache, "stop")
    if os.path.exists(stopf):
        os.remove(stopf)
    st, op = pg.load_settings(folder)
    if a.bg:                              # leave cores for the game: half of them (the game, its traffic worker, the GPU feeder)
        st["workers"] = max(1, (os.cpu_count() or 4) // 2 - 1)
    pg.save_settings(folder, st, op)
    job = pg.Job(folder, "detail", None, osm_dir, settings=st)
    job.start()
    t0 = last_ck = last_p = time.time()
    while job.is_alive():
        job.join(1.0)
        now = time.time()
        n, N, f = job.cur
        if a.bg:
            _write(prog, {"frac": round(job.frac, 4), "n": n, "N": N, "file": f, "step": job.step, "done": False, "t": now})
            if os.path.exists(stopf):
                job.stop = True
            if now - last_ck > CHECKPOINT and job.blds:
                try:                       # what is fitted so far: the game applies it at its next start
                    pg.write_fits(job.blds, "detail", os.path.join(cache, "fit_detail.json"))
                except Exception as e:  # noqa: BLE001 - a fit changing under us; the next checkpoint writes it
                    print("[photogram_full] checkpoint skipped:", e, flush=True)
                last_ck = now
        if now - last_p > 60:
            print(f"[progress] {now - t0:7.0f}s  {job.frac * 100:5.1f}%  {job.step}  stats={job.stats}", flush=True)
            last_p = now
    if job.error:
        print("[photogram_full] FAILED:", job.error, flush=True)
        if a.bg:
            _write(prog, {"frac": round(job.frac, 4), "n": 0, "N": 0, "file": "", "step": "", "done": False, "error": job.error, "t": time.time()})
        sys.exit(1)
    if a.bg:
        done_n = sum(1 for c in (job.caps or ()) if c.exists and os.path.exists(pg._store_path(pg.job_store(folder, "detail"), c.file)))
        tot = sum(1 for c in (job.caps or ()) if c.exists)
        _write(prog, {"frac": 1.0 if not job.stop else round(done_n / max(1, tot), 4), "n": 0, "N": len(job.caps or ()), "file": "", "step": "",
                      "done": not job.stop, "t": time.time()})
        print("[photogram_full] background run", "stopped" if job.stop else "finished", flush=True)
        return
    pg.apply_to_game(folder, "detail", osm_dir, op)
    print("[photogram_full] applied to", os.path.join(osm_dir, "photogram.json"), flush=True)


if __name__ == "__main__":
    main()
