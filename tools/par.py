"""Worker pool for the world build: the heavy stages split their pure-geometry work into independent jobs and run them on
every core.  Spawn-based (the same on Windows and Linux): job functions must be top-level functions of an importable
module, their arguments and results picklable.  Results always come back in the order of the jobs, so a parallel build
produces exactly the same world as a serial one.

    par.pmap(fn, items)              -> [fn(item) for item in items], on all cores
    par.pmap(fn, items, init=(f, a)) -> workers call f(*a) once first (shared read-only context, built once per worker)

SK242_JOBS=1 turns it off (one process, no pool); SK242_JOBS=n limits the pool to n workers."""
import multiprocessing as mp
import os
import sys

_POOL = [None, None]                      # the pool, the initializer it was started with


def jobs():
    try:
        n = int(os.environ.get("SK242_JOBS", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        n = os.cpu_count() or 1
    return max(1, min(n, 32 if "SK242_JOBS" not in os.environ else 61))     # default cap 32 (each worker holds a copy of numpy + its context); 61 = the Windows limit


def _pool(init):
    key = None if init is None else (init[0].__module__, init[0].__name__, id(init[1]))
    if _POOL[0] is not None and _POOL[1] == key:
        return _POOL[0]
    close()
    ctx = mp.get_context("spawn")
    _POOL[0] = ctx.Pool(jobs(), initializer=init[0] if init else None, initargs=init[1] if init else ())
    _POOL[1] = key
    return _POOL[0]


def close():
    if _POOL[0] is not None:
        _POOL[0].terminate()
        _POOL[0] = None
        _POOL[1] = None


def pmap(fn, items, init=None, chunk=None):
    """[fn(x) for x in items] in item order.  `chunk`: items per task (default: about 8 tasks per worker)."""
    items = list(items)
    n = jobs()
    if n <= 1 or len(items) < 2 or getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS"):
        if init:
            init[0](*init[1])
        return [fn(x) for x in items]
    try:
        pool = _pool(init)
        return pool.map(fn, items, chunksize=chunk or max(1, len(items) // (n * 8)))
    except (OSError, ImportError, mp.ProcessError, EOFError) as e:       # no pool possible here: do it in this process
        print(f"[build] parallel pool unavailable ({e}); running serially")
        close()
        if init:
            init[0](*init[1])
        return [fn(x) for x in items]
