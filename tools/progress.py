"""Console progress bars with elapsed time and ETA (ASCII only, works in cmd.exe)."""
import json
import os
import sys
import time

EVENTS = os.environ.get("SK242_EVENTS") == "1"      # set by the game: also print machine-readable `@@{json}` lines


def _ev(**kw):
    if EVENTS:
        sys.stdout.write("@@" + json.dumps({"t": "prog", **kw}) + "\n")
        sys.stdout.flush()


def geo(layer, flat_lines):
    """Things that now exist, for the loading screen's map: a list of flat [x0, y0, x1, y1, ...] lists in world metres
    (a single [x, y] is a point).  The game paints them as pixels."""
    if EVENTS and flat_lines:
        sys.stdout.write("@@" + json.dumps({"t": "geo", "layer": layer, "lines": [[int(v) for v in fl] for fl in flat_lines]}) + "\n")
        sys.stdout.flush()


def spread(layer, items, fn, slices=10):
    """A phase that cannot report while it runs: when it is over, send what it made in `slices` parts, so the map fills in steps."""
    if not EVENTS:
        return
    items = list(items)
    for k in range(slices):
        geo(layer, [fl for fl in (fn(it) for it in items[k * len(items) // slices:(k + 1) * len(items) // slices]) if fl])


def flat(pts, keep=40):
    """[(x, y), ...] -> flat coordinate list, thinned to about `keep` points."""
    step = max(1, len(pts) // keep)
    return [c for q in pts[::step] for c in (q[0], q[1])]


_cur = {"label": "", "f": 0.0, "t": 0.0}


def phase(label):
    """A step without its own Bar (graph, decks, furniture, ...): tells the game which phase is running.  Its work then
    reports through span() / frac(), so the bar of the running step keeps moving."""
    _cur.update(label=label, f=0.0, t=time.time())
    _ev(label=label, n=0, total=1000)
    sys.stdout.write(f"{label} ...\n")
    sys.stdout.flush()


def frac(f, sub=""):
    """The running phase is `f` (0..1) done; `sub` names the part being made now.  Sent at most every 0.05 s, but always
    when another 5 % is passed, so every phase moves at least 20 times."""
    now = time.time()
    f = max(_cur["f"], min(1.0, f))
    if now - _cur["t"] > 0.05 or int(f * 20) > int(_cur["f"] * 20):
        _cur["t"] = now
        _ev(label=_cur["label"], n=int(f * 1000), total=1000, sub=sub)
    _cur["f"] = f


def span(seq, lo, hi, sub=""):
    """for x in span(items, 0.2, 0.6, "benches"): ...   the loop covers lo..hi of the running phase."""
    seq = seq if hasattr(seq, "__len__") else list(seq)
    n = max(1, len(seq))
    frac(lo, sub)
    for i, x in enumerate(seq):
        yield x
        frac(lo + (hi - lo) * (i + 1) / n, sub)


def _fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Bar:
    def __init__(self, label, total=0, width=28, unit="", feed=None):
        self.label, self.total, self.width, self.unit = label, total, width, unit
        # feed = (layer, list, fn) or a tuple of those: every 5 % what has been added to `list` goes to the map via fn(item) -> flat coords
        self.feed = [feed] if feed and not isinstance(feed[0], tuple) else list(feed or [])
        self.sent = [0] * len(self.feed)
        self.next_feed = 0.05
        self.t0 = time.time()
        self.n = 0
        self.last = 0.0
        self.note = ""
        self._draw(force=True)

    def update(self, n=None, note=None):
        if n is not None:
            self.n = n
        if note is not None:
            self.note = note
        if self.feed and self.total and self.n >= self.next_feed * self.total:
            self.next_feed = self.n / self.total + 0.05
            self._send()
        self._draw()

    def _send(self):
        for k, (layer, lst, fn) in enumerate(self.feed):
            new = lst[self.sent[k]:] if lst is not None else self.items[self.sent[k]:self.n]
            self.sent[k] = len(lst) if lst is not None else self.n
            geo(layer, [fl for fl in map(fn, new) if fl])

    def step(self, k=1, note=None):
        self.update(self.n + k, note)

    def _draw(self, force=False):
        now = time.time()
        if not force and now - self.last < 0.05:
            return
        self.last = now
        _ev(label=self.label, n=self.n, total=self.total, sub=self.note)
        el = now - self.t0
        if self.total:
            f = min(1.0, self.n / self.total)
            fill = int(self.width * f)
            eta = (el / f - el) if f > 0.02 else 0
            txt = (f"\r[{'#' * fill}{'-' * (self.width - fill)}] {f * 100:3.0f}% {self.label} "
                   f"{self.n}/{self.total}{self.unit}  {_fmt(el)} elapsed" + (f", ~{_fmt(eta)} left" if eta else "")
                   + (f"  {self.note}" if self.note else ""))
        else:   # indeterminate
            pos = int(el * 6) % (self.width - 4)
            bar = ['-'] * self.width
            for i in range(4):
                bar[pos + i] = '#'
            txt = (f"\r[{''.join(bar)}] {self.label} {self.n}{self.unit}  {_fmt(el)} elapsed"
                   + (f"  {self.note}" if self.note else ""))
        sys.stdout.write(txt.ljust(100)[:118])
        sys.stdout.flush()

    def done(self, note=""):
        if self.total:
            self.n = self.total
        if self.feed:
            self._send()
        self._draw(force=True)
        _ev(label=self.label, n=self.total or self.n, total=self.total or self.n, done=1, sec=round(time.time() - self.t0, 2))
        sys.stdout.write(f"\r{self.label}: done in {_fmt(time.time() - self.t0)} {note}".ljust(118) + "\n")
        sys.stdout.flush()

    def fail(self, note=""):
        sys.stdout.write(f"\r{self.label}: FAILED {note}".ljust(118) + "\n")
        sys.stdout.flush()


def each(seq, label, unit="", feed=None):
    """for x in each(list, 'label'): ...   `feed`: see Bar; a feed with list None draws the items being looped over."""
    seq = list(seq)
    b = Bar(label, len(seq), unit=unit, feed=feed)
    b.items = seq
    for i, x in enumerate(seq):
        yield x
        b.update(i + 1)
    b.done()
