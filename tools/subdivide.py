"""Split triangle edges at their midpoints without opening cracks: whether an edge is split depends on that edge alone, so
the two triangles on either side of it always agree and share the new vertex (draped on terrain, their faces stay joined)."""
import numpy as np


def split_edges(tri, col, flags):
    """tri (n, 3, 3), col (n, ...) and flags (n, 3): split edge k (corner k to k+1)?  -> (triangles, colours) with every
    flagged edge halved, winding kept."""
    count = flags.sum(axis=1)
    out_t, out_c = [tri[count == 0]], [col[count == 0]]
    for n in (1, 2, 3):
        ids = np.flatnonzero(count == n)
        if not len(ids):
            continue
        f = flags[ids]
        # turn each triangle so its split edges come first: the one split edge as AB, or the two as AB and BC
        k = f.argmax(axis=1) if n == 1 else (f.argmin(axis=1) + 1) % 3 if n == 2 else np.zeros(len(ids), int)
        t = tri[ids[:, None], (k[:, None] + np.arange(3)) % 3]
        a, b, c = t[:, 0], t[:, 1], t[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        parts = (((a, ab, c), (ab, b, c)) if n == 1 else
                 ((ab, b, bc), (a, ab, bc), (a, bc, c)) if n == 2 else
                 ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        out_t += [np.stack(p, axis=1) for p in parts]
        out_c += [col[ids]] * len(parts)
    return np.concatenate(out_t), np.concatenate(out_c)
