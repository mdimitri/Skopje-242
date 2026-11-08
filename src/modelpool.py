"""Procedural car / person models built on spare CPU cores.

The game loop is one Python thread; building a new car model costs ~9 ms and a person ~2-4 ms of pure Python/numpy,
which used to happen inside a frame (two per frame).  Here the vertex arrays are made in worker processes and the game
only uploads the finished arrays (well under a millisecond).  Until a model is ready the renderer keeps showing its
fallback (the plain-paint car, the person's base pose) exactly as it did when the per-frame build budget ran out.

SK242_MODELPOOL=0 turns it off (everything is built in the frame again, as before)."""
import os
import sys

_EX = None
_ON = os.environ.get("SK242_MODELPOOL", "1") != "0"


def _job(spec):
    import gl3d                                            # the worker imports it once
    kind = spec[0]
    if kind == "ped":
        return gl3d.ped_arrays(*spec[1:])
    if kind == "car":
        return gl3d.car_arrays(spec[1], spec[2], (), 0.0, False, True)
    raise ValueError(spec)


def _warm():
    import gl3d  # noqa: F401
    return True


def start():
    """Start the workers (call while loading: a process start must not land inside a frame)."""
    global _EX
    if _EX is not None or not _ON or (getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS")):
        return _EX
    try:
        import concurrent.futures as cf
        import multiprocessing as mp
        n = max(1, min(4, (os.cpu_count() or 2) - 2))
        main = sys.modules.get("__main__")
        mf = getattr(main, "__file__", None)
        try:
            if mf is not None:
                del main.__file__                          # spawned workers must not re-run main.py (it opens a window)
            _EX = cf.ProcessPoolExecutor(n, mp_context=mp.get_context("spawn"))
            for _ in range(n):
                _EX.submit(_warm)                          # starts the n workers now and imports gl3d in each
        finally:
            if mf is not None:
                main.__file__ = mf
    except Exception as e:  # noqa: BLE001 - no pool: models are built in the frame as before
        print(f"[modelpool] off: {e}")
        _EX = None
    return _EX


def stop():
    global _EX
    if _EX is not None:
        try:
            _EX.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass
        _EX = None


class Builder:
    """Asks for models by key; ready() hands back the finished arrays (key, (pos, uv, col)) once per frame."""

    def __init__(self, limit=48):
        self.jobs = {}
        self.limit = limit
        self.failed = set()

    def want(self, key, spec):
        """True when the job is queued (or already running); False when there is no pool or the queue is full."""
        if key in self.jobs:
            return True
        if _EX is None or len(self.jobs) >= self.limit or key in self.failed:
            return False
        try:
            self.jobs[key] = _EX.submit(_job, spec)
        except Exception:  # noqa: BLE001 - pool broken: build in the frame from now on
            stop()
            return False
        return True

    def ready(self):
        out = []
        for key, f in list(self.jobs.items()):
            if f.done():
                del self.jobs[key]
                try:
                    out.append((key, f.result()))
                except Exception:  # noqa: BLE001
                    self.failed.add(key)
        return out
