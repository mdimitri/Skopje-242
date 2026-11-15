"""Where the music bar and the version / progress label go, so they never cover anything.

Screens call corner.avoid(rect, ...) every frame with the rectangles their own content uses (panels, buttons, titles).
The music widget (loadmusic.py) then takes the best free spot on the window - top left by default, else the first free
spot along the top edge, else along the bottom edge - and shrinks step by step when the space is tight:
logo + station list + song bar, no logo, song bar only, just the four buttons, and finally nothing at all.
font.draw_version() puts the version label (and the background photogrammetry's progress) under the bar, or in the
nearest free spot, and cuts the progress text down to what fits."""
import time

import pyray as rl

MARGIN = 6
_avoid = ([], 0.0)            # (rects, time set): only trusted while the screen keeps refreshing it
_box = (None, 0.0)            # where the music widget was drawn last: (x, y, w, h)
_cache = {}


def avoid(*rects):
    """This frame's content rectangles (x, y, w, h); anything may be passed, bad entries are ignored."""
    global _avoid
    _avoid = ([tuple(r) for r in rects if r and len(r) == 4 and r[2] > 0 and r[3] > 0], time.time())


def rects():
    r, t = _avoid
    return r if time.time() - t < 0.3 else []


def hit(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def free(r, W, H, extra=()):
    if r[0] < 0 or r[1] < 0 or r[0] + r[2] > W or r[1] + r[3] > H:
        return False
    g = (r[0] - MARGIN, r[1] - MARGIN, r[2] + 2 * MARGIN, r[3] + 2 * MARGIN)
    return not any(hit(g, a) for a in (*rects(), *extra))


def find(W, H, w, h, y_top=10, x_left=12, extra=()):
    """First free (x, y) for a w x h box: the top edge from the left, then the bottom edge; None if neither has room."""
    ys = (y_top, H - h - 10)
    for y in ys:
        x = x_left
        while x + w <= W:
            if free((x, y, w, h), W, H, extra):
                return x, y
            x += 8
    return None


def set_box(b):
    global _box
    _box = (b, time.time())


def music_box():
    b, t = _box
    return b if b is not None and time.time() - t < 0.3 else None


def version_spot(W, H, w, h):
    """Free spot for the version label block (w x h): under the music bar, beside it, else anywhere free.  None: hide it."""
    key = (W, H, w, h, music_box(), tuple(rects()))
    if key in _cache:
        return _cache[key]
    b = music_box()
    ex = (b,) if b else ()
    cands = []
    if b is None:
        cands.append((14, 52))
    else:
        cands += [(b[0] + 2, b[1] + b[3] + MARGIN + 1), (b[0] + b[2] + MARGIN + 8, b[1])]
    for c in cands:
        if free((c[0], c[1], w, h), W, H, ex):
            r = c
            break
    else:
        r = find(W, H, w, h, y_top=6, x_left=6, extra=ex)
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = r
    return r
