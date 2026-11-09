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


def free_mb():
    """Memory the system can still give out, in MB (None when unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong),
                            ("avirt", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            m = MS()
            m.len = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2 ** 20
        with open("/proc/meminfo") as f:
            for ln in f:
                if ln.startswith("MemAvailable:"):
                    return int(ln.split()[1]) / 1024
    except Exception:  # noqa: BLE001
        pass
    return None


WORKER_MB = 700                           # rough peak of one pool worker on the real map (numpy + its copy of the job's context)


def jobs():
    """Workers to run: every core, but never more than the free memory holds (8 GB laptops) - 1.5 GB stays for the build itself."""
    try:
        n = int(os.environ.get("SK242_JOBS", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        n = os.cpu_count() or 1
        fm = free_mb()
        if fm is not None:
            n = min(n, max(1, int((fm - 1500) // int(os.environ.get("SK242_WORKER_MB", WORKER_MB)))))
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


def _serial(fn, items, on):
    res = []
    for x in items:
        res.append(fn(x))
        if on:
            on(len(res), len(items))
    return res


def pmap(fn, items, init=None, chunk=None, on=None):
    """[fn(x) for x in items] in item order.  `chunk`: items per task (default: about 8 tasks per worker).
    `on(done, total)` is called as results arrive, so the loading bars keep moving while the workers run."""
    items = list(items)
    n = jobs()
    if n <= 1 or len(items) < 2 or getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS"):
        if init:
            init[0](*init[1])
        return _serial(fn, items, on)
    try:
        pool = _pool(init)
        res = []
        for r in pool.imap(fn, items, chunksize=chunk or max(1, len(items) // (n * 8))):
            res.append(r)
            if on:
                on(len(res), len(items))
        return res
    except (OSError, ImportError, mp.ProcessError, EOFError) as e:       # no pool possible here: do it in this process
        print(f"[build] parallel pool unavailable ({e}); running serially")
        close()
        if init:
            init[0](*init[1])
        return _serial(fn, items, on)
