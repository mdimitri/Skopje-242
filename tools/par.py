"""Worker pool for the world build: the heavy stages split their pure-geometry work into independent jobs and run them on
every core.  Spawn-based (the same on Windows and Linux): job functions must be top-level functions of an importable
module, their arguments and results picklable.  Results always come back in the order of the jobs, so a parallel build
produces exactly the same world as a serial one.

    par.pmap(fn, items)              -> [fn(item) for item in items], on all cores
    par.pmap(fn, items, init=(f, a)) -> workers call f(*a) once first (shared read-only context, built once per worker)
    par.start()                      -> start the workers in the background (the build does it first thing)
    par.submit(fn, items, ...)       -> like pimap, but the jobs run while the caller goes on; iterate the result later

One pool serves the whole build.  The context of a call is written to a file once and each worker reads it with its
first job of that call (handing it to the pool instead pickles it once per worker, one worker after another).

SK242_JOBS=1 turns it off (one process, no pool); SK242_JOBS=n limits the pool to n workers."""
import atexit
import multiprocessing as mp
import os
import pickle
import shutil
import sys
import tempfile
import threading

_POOL = [None, None]                      # the pool, the thread that is starting it
_DIR = [None, 0]                          # folder of the context files, files written so far


def mem_mb():
    """(available, total) system memory in MB, or None when unknown."""
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
            return m.avail / 2 ** 20, m.total / 2 ** 20
        mi = {}
        with open("/proc/meminfo") as f:
            for ln in f:
                k, v = ln.split(":", 1)
                mi[k] = int(v.split()[0]) / 1024
        return mi["MemAvailable"], mi["MemTotal"]
    except Exception:  # noqa: BLE001
        pass
    return None


WORKER_MB = 700                           # rough peak of one pool worker on the real map (numpy + its copy of the job's context)
_JOBS = [0]                               # decided once: the pool keeps its size for the whole build


def jobs():
    """Workers to run: every core, but only as many as fit while the whole machine stays under 70 % of its RAM (an 8 GB laptop
    gets few, a 32 GB PC more); 1 GB is kept back for the growing build itself."""
    try:
        n = int(os.environ.get("SK242_JOBS", "0"))
    except ValueError:
        n = 0
    if n <= 0:
        if _JOBS[0]:
            return _JOBS[0]
        n = os.cpu_count() or 1
        m = mem_mb()
        if m is not None:
            avail, total = m
            room = min(avail, 0.7 * total - (total - avail)) - 1000          # what workers may take before the machine passes 70 %
            n = min(n, max(1, int(room // int(os.environ.get("SK242_WORKER_MB", WORKER_MB)))))
        _JOBS[0] = max(1, min(n, 32))
        return _JOBS[0]
    return max(1, min(n, 61))             # default cap 32 (each worker holds a copy of numpy + its context); 61 = the Windows limit


def _warm():
    """First thing a worker does: the imports every build job needs, so the first real job does not wait for them."""
    for name in ("numpy", "shapely", "mapbox_earcut", "PIL.Image"):
        try:
            __import__(name)
        except ImportError:
            pass


def _parallel():
    return jobs() > 1 and not (getattr(sys, "frozen", False) and not hasattr(sys, "_MEIPASS"))


def start():
    """Start the pool in a background thread (20 process launches take seconds on Windows)."""
    if not _parallel() or _POOL[0] is not None or _POOL[1] is not None:
        return
    n = jobs()

    def run():
        try:
            _POOL[0] = mp.get_context("spawn").Pool(n, initializer=_warm)
        except (OSError, ImportError, mp.ProcessError, EOFError) as e:
            print(f"[build] parallel pool unavailable ({e}); running serially")
    _POOL[1] = threading.Thread(target=run, daemon=True)
    _POOL[1].start()


def _pool():
    start()
    if _POOL[1] is not None:
        _POOL[1].join()
    return _POOL[0]


def close():
    if _POOL[1] is not None:
        _POOL[1].join()
        _POOL[1] = None
    if _POOL[0] is not None:
        _POOL[0].terminate()
        _POOL[0].join()
        _POOL[0] = None
    if _DIR[0] is not None:
        shutil.rmtree(_DIR[0], ignore_errors=True)
        _DIR[0] = None


atexit.register(close)

_LOADED = {}                              # worker side: initializer -> the context file it last ran with


def _call(task):
    ctx, fn, x = task
    if ctx is not None:
        path, name = ctx
        if _LOADED.get(name) != path:
            with open(path, "rb") as f:
                init, args = pickle.load(f)
            init(*args)
            _LOADED[name] = path
    return fn(x)


def _context(init):
    if init is None:
        return None
    if _DIR[0] is None:
        _DIR[0] = tempfile.mkdtemp(prefix="sk242_par_")
    _DIR[1] += 1
    path = os.path.join(_DIR[0], f"ctx{_DIR[1]}.pkl")
    with open(path, "wb") as f:
        pickle.dump(init, f, protocol=pickle.HIGHEST_PROTOCOL)
    return path, f"{init[0].__module__}.{init[0].__name__}"


def _serial(fn, items, init, on):
    if init:
        init[0](*init[1])
    for k, x in enumerate(items):
        yield fn(x)
        if on:
            on(k + 1, len(items))


def submit(fn, items, init=None, chunk=None, on=None):
    """Queue the jobs now and return an iterator over their results in job order.  The workers start at once; the caller may
    do other work before reading.  `chunk`: items per task (default: about 8 tasks per worker).  `on(done, total)` is
    called as results are read, so the loading bars keep moving."""
    items = list(items)
    pool = _pool() if _parallel() and len(items) >= 1 else None
    if pool is None:
        return _serial(fn, items, init, on)
    ctx = _context(init)
    it = pool.imap(_call, [(ctx, fn, x) for x in items], chunksize=chunk or max(1, len(items) // (jobs() * 8)))

    def results():
        for k, r in enumerate(it):
            yield r
            if on:
                on(k + 1, len(items))
    return results()


def pimap(fn, items, init=None, chunk=None, on=None):
    """Like pmap, but yields the results in order as they arrive, so a caller that stores them right away never holds
    them all twice (memory on 8 GB machines)."""
    items = list(items)
    if len(items) < 2:
        return _serial(fn, items, init, on)
    return submit(fn, items, init, chunk, on)


def pmap(fn, items, init=None, chunk=None, on=None):
    """[fn(x) for x in items] in item order."""
    return list(pimap(fn, items, init, chunk, on))
