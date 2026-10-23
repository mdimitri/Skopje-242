"""Hardened HTTP for the map / terrain downloads.

* every request runs in a worker thread that the caller supervises: bytes, speed and waiting time are reported once a
  second (as `@@{json}` lines the game's splash screen turns into the progress map), a stalled transfer is aborted,
  nothing can hang forever;
* failures are classified (busy / rejected / stalled / timeout / offline / bad data) so the caller can pick another
  mirror or a smaller piece instead of repeating the same request;
* mirrors are scored: failing ones are put in a cool-down, the fastest healthy one is preferred.
"""
import collections
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

UA = "skopje-242/0.4 (+https://github.com/; hobby game, polite client)"


_LOCK = threading.Lock()


def emit(t, **kw):
    """Machine-readable progress line for the game (stdout, ASCII only)."""
    try:
        with _LOCK:
            sys.stdout.write("@@" + json.dumps({"t": t, **kw}) + "\n")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001 - never let reporting break a download
        pass


class Fail(Exception):
    """kind: offline | timeout | stall | busy | reject | bad | http"""

    def __init__(self, kind, msg="", retry_after=0.0):
        super().__init__(f"{kind}: {msg}")
        self.kind, self.msg, self.retry_after = kind, msg, retry_after


class Mirrors:
    def __init__(self, urls):
        self.urls = list(urls)
        self.cool = {u: 0.0 for u in self.urls}           # time until which a mirror is resting
        self.fails = {u: 0 for u in self.urls}
        self.speed = {u: 0.0 for u in self.urls}          # last good speed (B/s)
        self.inuse = {u: 0 for u in self.urls}            # requests running now (parallel workers spread over mirrors)
        self.lock = threading.Lock()

    def pick(self, avoid=()):
        with self.lock:
            u = self._pick(avoid)
            self.inuse[u] += 1
            return u

    def _pick(self, avoid=()):
        now = time.time()
        ready = [u for u in self.urls if self.cool[u] <= now and u not in avoid] or \
                [u for u in self.urls if self.cool[u] <= now] or sorted(self.urls, key=lambda u: self.cool[u])[:1]
        return max(ready, key=lambda u: (-self.inuse[u], -self.fails[u], self.speed[u]))

    def bad(self, u, f):
        self.inuse[u] = max(0, self.inuse[u] - 1)
        self.fails[u] += 1
        rest = {"busy": 20, "reject": 15, "stall": 45, "timeout": 45, "offline": 60}.get(f.kind, 20) * min(4, self.fails[u])
        self.cool[u] = time.time() + max(rest, f.retry_after)

    def good(self, u, bps):
        self.inuse[u] = max(0, self.inuse[u] - 1)
        self.fails[u] = max(0, self.fails[u] - 1)
        self.cool[u] = 0.0
        self.speed[u] = bps

    def exhausted(self):
        return all(self.fails[u] >= 3 for u in self.urls)


def host(url):
    return url.split("/")[2]


def fetch(url, uid, data=None, first_byte=240.0, stall=25.0, headers=None, limit=0.0):
    """GET / POST `url`; returns the body bytes.  Reports `net` events under id `uid`.

    first_byte: how long the server may think before answering (Overpass computes the whole result first);
    stall: longest pause allowed once data is flowing; limit: overall cap for this one request (0 = none)."""
    stall = float(os.environ.get("SK242_STALL", stall))
    h = {"User-Agent": UA}
    h.update(headers or {})
    st = {"n": 0, "t_last": time.time(), "body": None, "err": None, "r": None, "status": 0, "size": 0}
    t0 = time.time()

    def work():
        try:
            req = urllib.request.Request(url, data=data, headers=h)
            r = urllib.request.urlopen(req, timeout=first_byte)
            st["r"] = r
            st["status"] = getattr(r, "status", 200)
            try:
                st["size"] = int(r.headers.get("Content-Length") or 0)
            except ValueError:
                pass
            try:
                r.fp.raw._sock.settimeout(stall)               # data is flowing: pauses are stalls now
            except Exception:  # noqa: BLE001
                pass
            chunks = []
            while True:
                b = r.read1(65536) if hasattr(r, 'read1') else r.read(8192)
                if not b:
                    break
                chunks.append(b)
                st["n"] += len(b)
                st["t_last"] = time.time()
            st["body"] = b"".join(chunks)
        except urllib.error.HTTPError as e:
            try:
                ra = float(e.headers.get("Retry-After") or 0)
            except ValueError:
                ra = 0.0
            st["err"] = ("http", e.code, ra)
        except (socket.timeout, TimeoutError):
            st["err"] = ("timeout", 0, 0)
        except urllib.error.URLError as e:
            st["err"] = ("url", str(e.reason), 0)
        except Exception as e:  # noqa: BLE001
            st["err"] = ("exc", str(e), 0)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    hist = collections.deque(maxlen=6)
    last_emit = 0.0
    while th.is_alive():
        th.join(0.25)
        now = time.time()
        hist.append((now, st["n"]))
        if now - last_emit >= 1.0:
            last_emit = now
            bps = (hist[-1][1] - hist[0][1]) / max(hist[-1][0] - hist[0][0], 1e-6) if len(hist) > 1 else 0.0
            emit("net", id=uid, state="recv" if st["n"] else "wait", bytes=st["n"], size=st["size"], bps=int(bps),
                 sec=int(now - t0), mirror=host(url))
        if st["n"] and now - st["t_last"] > stall:
            _abort(st)
            raise Fail("stall", f"no data for {stall:.0f}s after {st['n']} bytes")
        if not st["n"] and now - t0 > first_byte + 15:
            _abort(st)
            raise Fail("timeout", f"no answer after {now - t0:.0f}s")
        if limit and now - t0 > limit:
            _abort(st)
            raise Fail("timeout", f"over the {limit:.0f}s limit")
    err = st["err"]
    if err:
        kind, a, b = err
        if kind == "http":
            if a in (429, 503):
                raise Fail("busy", f"HTTP {a}", b or 20.0)
            if a in (502, 504):
                raise Fail("busy", f"HTTP {a} (server overloaded)", b or 15.0)
            if a in (400, 413):
                raise Fail("reject", f"HTTP {a}")
            raise Fail("http", f"HTTP {a}")
        if kind == "timeout":
            raise Fail("timeout" if not st["n"] else "stall", "socket timeout")
        if kind == "url":
            raise Fail("offline", a)
        raise Fail("net", a)
    body = st["body"]
    if body is None:
        raise Fail("net", "aborted")
    if st["size"] and len(body) < st["size"]:
        raise Fail("bad", f"truncated ({len(body)} of {st['size']} bytes)")
    dt = max(time.time() - t0, 1e-3)
    emit("net", id=uid, state="done", bytes=len(body), size=len(body), bps=int(len(body) / dt), sec=int(dt), mirror=host(url))
    return body


def _abort(st):
    r = st.get("r")
    try:
        if r is not None:
            r.close()
    except Exception:  # noqa: BLE001
        pass


def sleep_visible(seconds, uid, why):
    """Wait, but keep telling the game why (so the splash never just sits there)."""
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            return
        emit("net", id=uid, state="rest", why=why, left=int(left), bytes=0, bps=0)
        time.sleep(min(1.0, left))


def single_instance(name, root, stale=2 * 3600):
    """Only one downloader / builder per data folder (two game windows would corrupt each other's parts).
    A lock left by a crashed or killed run (dead pid or older than `stale` seconds) is taken over.  -> True if we hold it."""
    path = os.path.join(root, f".{name}.lock")
    os.makedirs(root, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            import atexit
            atexit.register(lambda: os.path.exists(path) and os.remove(path))
            return True
        except FileExistsError:
            try:
                pid = int(open(path).read().strip() or 0)
                alive = _alive(pid) and time.time() - os.path.getmtime(path) < stale
            except (OSError, ValueError):
                alive = False
            if alive:
                return False
            try:
                os.remove(path)
            except OSError:
                return False
    return False


def _alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clean_tmp(folder):
    """Half-written *.tmp files of an interrupted run."""
    try:
        for fn in os.listdir(folder):
            if ".tmp" in fn:
                try:
                    os.remove(os.path.join(folder, fn))
                except OSError:
                    pass
    except OSError:
        pass
