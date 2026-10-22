"""Console progress bars with elapsed time and ETA (ASCII only, works in cmd.exe)."""
import json
import os
import sys
import time

EVENTS = os.environ.get("GTA_EVENTS") == "1"      # set by the game: also print machine-readable `@@{json}` lines


def _ev(**kw):
    if EVENTS:
        sys.stdout.write("@@" + json.dumps({"t": "prog", **kw}) + "\n")
        sys.stdout.flush()


def phase(label):
    """A step without a counter (graph, decks, ...): tells the game which phase is running."""
    _ev(label=label, n=0, total=0)
    sys.stdout.write(f"{label} ...\n")
    sys.stdout.flush()


def _fmt(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}:{sec % 60:02d}"


class Bar:
    def __init__(self, label, total=0, width=28, unit=""):
        self.label, self.total, self.width, self.unit = label, total, width, unit
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
        self._draw()

    def step(self, k=1, note=None):
        self.update(self.n + k, note)

    def _draw(self, force=False):
        now = time.time()
        if not force and now - self.last < 0.15:
            return
        self.last = now
        _ev(label=self.label, n=self.n, total=self.total)
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
        self._draw(force=True)
        _ev(label=self.label, n=self.total or self.n, total=self.total or self.n, done=1, sec=round(time.time() - self.t0, 2))
        sys.stdout.write(f"\r{self.label}: done in {_fmt(time.time() - self.t0)} {note}".ljust(118) + "\n")
        sys.stdout.flush()

    def fail(self, note=""):
        sys.stdout.write(f"\r{self.label}: FAILED {note}".ljust(118) + "\n")
        sys.stdout.flush()


def each(seq, label, unit=""):
    """for x in each(list, 'label'): ..."""
    seq = list(seq)
    b = Bar(label, len(seq), unit=unit)
    for i, x in enumerate(seq):
        yield x
        b.update(i + 1)
    b.done()
