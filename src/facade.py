"""Facade analysis for src/photogram.py: one wall seen in one photo (resampled onto the wall plane, see photogram.Obs) ->
roof line, roof band (mansard / pitched roof slope seen above the wall), floor grid, bay columns, a texture tile per bay column
(the median of that column over its floors: trees, washing and one-offs drop out) and the small 3D details of each column
(air-conditioner boxes, balcony slabs).  numpy only (the game's embedded Python has no scipy / OpenCV).

Tiles are the photos' own pixels, so they stay on this computer: data/ is not in git and the game never uploads them.
"""
import warnings
from collections import deque

import numpy as np

L_BUILDING, L_SKY = 1, 2
LUM = np.array([.3, .59, .11])
RES = 12.0                                  # facade resampling for the detail analysis (pixels per metre)
TILE_PPM = 16.0                             # texture tiles in the atlas (pixels per metre)


def _medfilt(a, k):
    out = np.full_like(a, np.nan)
    for i in range(len(a)):
        w = a[max(0, i - k):i + k + 1]
        w = w[np.isfinite(w)]
        if len(w) >= max(1, k // 2):
            out[i] = np.median(w)
    return out


def _period(p, lo, hi):
    """Strongest repeat (samples) of a profile between lo and hi, and its strength 0..1."""
    p = np.asarray(p, np.float64)
    good = np.isfinite(p)
    if good.sum() < hi * 2:
        return None, 0.0
    p = np.where(good, p, np.nanmean(p))
    k = int(hi) * 2 + 1
    p = p - np.convolve(np.pad(p, k // 2, mode="edge"), np.ones(k) / k, "valid")
    p -= p.mean()
    den = float(p @ p) or 1.0
    best, bs = None, 0.0
    for lag in range(int(lo), int(hi) + 1):
        r = float(p[:-lag] @ p[lag:]) / den
        if r > bs:
            best, bs = lag, r
    return best, bs


def _fold_phase(prof, per):
    """Offset (samples) half a period away from where the profile peaks when folded at `per`: cell borders sit between windows."""
    per_i = max(2, int(round(per)))
    acc, n = np.zeros(per_i), np.zeros(per_i)
    for k, v in enumerate(prof):
        if np.isfinite(v):
            acc[k % per_i] += v
            n[k % per_i] += 1
    m = acc / np.maximum(n, 1)
    m = np.convolve(np.r_[m, m, m], np.ones(3) / 3, "same")[per_i:2 * per_i]
    return (int(np.argmax(m)) + per_i / 2) % per_i


def _resamp(a, h, w):
    return a[(np.arange(h) * a.shape[0] // h)[:, None], (np.arange(w) * a.shape[1] // w)[None, :]]


def _components(m):
    seen = np.zeros_like(m, bool)
    H, W = m.shape
    for y0, x0 in zip(*np.nonzero(m)):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)])
        seen[y0, x0] = True
        ys, xs = [], []
        while q:
            y, x = q.popleft()
            ys.append(y)
            xs.append(x)
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < H and 0 <= xx < W and m[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    q.append((yy, xx))
        yield np.array(ys), np.array(xs)


def tile_details(t, wall, fh, bw):
    """3D details of one column tile (rows: 0 = bottom of the floor) -> {"ac": [[u, v, w, h, r, g, b]], "balc": [depth, r, g, b] | None}:
    u = centre as a fraction of the column width, v / w / h in metres.  AC units: compact light / grey boxes; balcony: a bottom band that differs from the wall."""
    th, tw = t.shape[:2]
    f = t.astype(np.float32)
    lum, sat = f @ LUM, f.max(2) - f.min(2)
    diff = np.abs(f - wall).sum(2)
    out = {"ac": [], "balc": None}
    dark = lum < 0.62 * np.percentile(lum, 70)
    cand = (diff > 70) & (sat < 45) & (lum > 120) & ~dark
    ppm = th / fh
    for ys, xs in _components(cand):
        w_, h_ = (np.ptp(xs) + 1) / ppm, (np.ptp(ys) + 1) / ppm
        fill = len(ys) / ((np.ptp(xs) + 1) * (np.ptp(ys) + 1))
        if 0.45 <= w_ <= 1.3 and 0.3 <= h_ <= 1.0 and fill > 0.55 and w_ < 0.8 * bw:
            c = np.median(f[ys, xs], 0)
            out["ac"].append([round((xs.mean() + 0.5) / tw, 3), round((ys.mean() + 0.5) / ppm, 2), round(w_, 2), round(h_, 2),
                              *[int(v) for v in c]])
    bot, mid = f[:max(1, th // 3)].reshape(-1, 3), f[th // 3:].reshape(-1, 3)
    if np.abs(bot.mean(0) - mid.mean(0)).sum() > 45 and np.abs(bot.mean(0) - wall).sum() > 45:
        out["balc"] = [0.9, *[int(v) for v in np.median(bot, 0)]]
    return out


def analyse(o, levels=0.0, log=None):
    """One wall view (photogram.Obs at RES px/m) -> facade dict, or None when too little of it is building."""
    rgb = o.rgb.astype(np.float32)
    B = (o.lab == L_BUILDING) & o.ok
    SKY = (o.lab == L_SKY) & o.ok
    nv, nu = B.shape
    if B.sum() < 400 or nu < 2 * RES:
        return None
    lum, sat = rgb @ LUM, rgb.max(2) - rgb.min(2)
    # ---- roof line per column: a building pixel with sky right above it (the bottom may be hidden by trees and cars)
    top = np.full(nu, np.nan)
    for j in range(nu):
        r = np.nonzero(B[:, j])[0]
        if len(r) and SKY[r[-1] + 1:r[-1] + 1 + int(2 * RES), j].any():
            top[j] = (r[-1] + 1) / RES
    seen_top = np.isfinite(top).mean()
    ts = _medfilt(top, int(0.75 * RES))
    idx = np.nonzero(np.isfinite(ts))[0]
    if len(idx) < RES:
        hi_rows = np.nonzero(B.any(1))[0]
        ts = np.full(nu, (hi_rows[-1] + 1) / RES)                 # the top is out of the picture: the highest building row
        seen_top = 0.0
    else:
        ts = np.interp(np.arange(nu), idx, ts[idx])
    secs, s0 = [], 0
    for j in range(1, nu + 1):
        if j == nu or (abs(ts[j] - np.median(ts[s0:j])) > 0.9 and j - s0 >= 2 * RES):
            secs.append([s0, j, float(np.median(ts[s0:j]))])
            s0 = j
    m = []
    for sc in secs:
        if m and (sc[1] - sc[0] < 3 * RES or abs(sc[2] - m[-1][2]) < 0.8):
            w0, w1 = m[-1][1] - m[-1][0], sc[1] - sc[0]
            m[-1] = [m[-1][0], sc[1], (m[-1][2] * w0 + sc[2] * w1) / (w0 + w1)]
        else:
            m.append(sc)
    secs = m
    bl = lum[B]
    wall_l = np.percentile(bl, 75)
    wall_c = np.median(rgb[B & (lum >= np.percentile(bl, 40))], 0)
    # ---- roof band: from each column's top down, pixels that keep the roof's own colour (shingles / sheet / tiles)
    roofish = B & (sat < 60) & (lum < wall_l - 18) & (lum > 50)
    roof_px = []
    for sc in secs:
        cols = slice(sc[0], sc[1])
        t = int(round(sc[2] * RES))
        tp = rgb[max(0, t - int(0.6 * RES)):t, cols][roofish[max(0, t - int(0.6 * RES)):t, cols]]
        band, shc = 0.0, None
        if len(tp) >= 20 and seen_top > 0.2:
            top_c = np.median(tp, 0)
            like = B & (np.abs(rgb - top_c).sum(2) < 45)
            runs = []
            for j in range(sc[0], sc[1]):
                if not np.isfinite(top[j]):
                    continue
                r, k, miss = int(top[j] * RES) - 1, 0, 0
                while r - k > 0 and miss < 3:
                    miss = 0 if like[r - k, j] else miss + 1
                    k += 1
                runs.append(max(0, k - miss) / RES)
            runs = np.array(runs)
            roofy = runs >= 0.6
            if len(runs) and roofy.mean() > 0.2:
                band = float(np.clip(np.percentile(runs[roofy], 60), 0.0, 0.45 * sc[2]))
                shc = top_c
                roof_px.append(top_c)
        sc += [band if band >= 0.8 else 0.0, None if shc is None or band < 0.8 else [int(v) for v in shc]]
    h_top = max(s[2] for s in secs)
    walltop = float(np.median([s[2] - s[3] for s in secs for _ in range(max(1, (s[1] - s[0]) // int(RES)))]))
    # ---- floors: storey height from the rows' rhythm (OSM levels when it is weak), border phase between window bands
    k0, k1 = int(0.5 * RES), max(int(0.5 * RES) + 2, int((walltop - 0.3) * RES))
    clean = B[k0:k1].mean(0) > 0.6
    dif = np.abs(rgb - wall_c).sum(2)
    rowp = np.array([(dif[r][clean & B[r]].mean() if (clean & B[r]).sum() > 5 else np.nan) for r in range(nv)])
    rowp[int(walltop * RES):] = np.nan
    nfl = int(levels) if levels >= 1 else max(1, round(walltop / 3.0))
    fh = (h_top if any(s[3] > 0 for s in secs) else walltop) / nfl
    lagv, stv = _period(rowp[:int(walltop * RES)], 2.6 * RES, 4.2 * RES)
    if lagv and (levels < 1 or stv > 0.35):
        fh = lagv / RES
    fh = float(np.clip(fh, 2.5, 4.5))
    pv = _fold_phase(rowp, fh * RES) / RES
    # ---- bays: window rhythm along the wall; zones where the look of the columns changes (piers, balcony stacks, stairs)
    colp = np.where(clean, (lum * B)[k0:k1].sum(0) / np.maximum(B[k0:k1].sum(0), 1), np.nan)
    lag, _st = _period(colp, 2.2 * RES, 7 * RES)
    bw = float(np.clip((lag or 3.4 * RES) / RES, 2.2, 7.0))
    colp_d = np.where(clean, (dif * B)[k0:k1].sum(0) / np.maximum(B[k0:k1].sum(0), 1), np.nan)
    ph = _fold_phase(colp_d, bw * RES) / RES
    Bf = B[k0:k1]
    cnt = np.maximum(Bf.sum(0), 1)
    feat = np.stack([*(np.where(Bf[..., None], rgb[k0:k1], 0).sum(0) / cnt[:, None] / 255).T,
                     ((lum[k0:k1] < 0.62 * np.percentile(lum[k0:k1][Bf], 70)) & Bf).sum(0) / cnt * 2], 1) if Bf.any() else None
    okc = Bf.mean(0) > 0.35
    w = int(1.0 * RES)
    chg = np.zeros(nu)
    if feat is not None:
        for j in range(w, nu - w):
            a, b_ = okc[j - w:j], okc[j:j + w]
            if a.sum() > w // 2 and b_.sum() > w // 2:
                chg[j] = np.abs(feat[j - w:j][a].mean(0) - feat[j:j + w][b_].mean(0)).sum()
    cuts = []
    for j in np.argsort(-chg):
        if chg[j] < 0.18:
            break
        if all(abs(j - q) >= 1.5 * RES for q in cuts) and 1.2 * RES < j < nu - 1.2 * RES:
            cuts.append(int(j))
    zb = [0] + sorted(cuts) + [nu]
    ub = []
    for a, e in zip(zb[:-1], zb[1:]):
        n = max(1, int(round((e - a) / RES / bw)))
        g = [q for q in np.arange(ph - bw * 50, o.ln, bw) if a / RES + 0.6 < q < e / RES - 0.6] if n > 1 else []
        ub += [a / RES] + list(g)
    ub = np.array(ub + [o.ln])
    # ---- column tiles: the median of each column over its floors
    TH = int(round(fh * TILE_PPM))
    tiles, cols = [], []
    for u0, u1 in zip(ub[:-1], ub[1:]):
        a0, a1 = int(u0 * RES), int(u1 * RES)
        if a1 - a0 < 3:
            continue
        TW = max(4, int(round((u1 - u0) * TILE_PPM)))
        stack = []
        for i in range(-1, int(walltop / fh) + 2):
            v0, v1 = pv + i * fh, pv + (i + 1) * fh
            if v0 < 0 or v1 > walltop + 0.2:
                continue
            b0, b1 = int(v0 * RES), int(v1 * RES)
            mk = B[b0:b1, a0:a1]
            if mk.mean() < 0.45:
                continue
            im = _resamp(rgb[b0:b1, a0:a1], TH, TW).copy()
            im[~_resamp(mk, TH, TW)] = np.nan
            stack.append(im)
        tile = None
        if stack:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN pixels: nobody saw them, filled below
                e_ = np.nanmedian(np.array(stack), 0)
            if np.isnan(e_).mean() < 0.3:
                e_[np.isnan(e_)] = np.broadcast_to(wall_c, e_.shape)[np.isnan(e_)]
                tile = np.clip(e_, 0, 255).astype(np.uint8)
        cols.append([round(float(u0), 2), round(float(u1), 2), len(tiles) if tile is not None else -1, len(stack)])
        if tile is not None:
            tiles.append(tile)
    if not tiles:
        return None
    # columns nobody saw clearly: the nearest seen column's tile
    seen_ids = [c for c in cols if c[2] >= 0]
    for c in cols:
        if c[2] < 0:
            c[2] = min(seen_ids, key=lambda s: abs((s[0] + s[1]) - (c[0] + c[1])))[2]
    det = [tile_details(t, wall_c, fh, bw) for t in tiles]
    if log:
        log(f"    ѕид {o.wi}: {o.ln:.1f} м, врв {h_top:.1f} м, ѕид до {walltop:.1f} м, покрив {max(s[3] for s in secs):.1f} м, "
            f"кат {fh:.2f} м, колони {len(cols)}, плочки {len(tiles)}, клима {sum(len(d['ac']) for d in det)}, "
            f"балкони {sum(1 for d in det if d['balc'])}")
    return {"wi": o.wi, "a": [round(float(v), 2) for v in o.a], "b": [round(float(v), 2) for v in o.b], "ln": round(float(o.ln), 2),
            "secs": [[round(s[0] / RES, 2), round(s[1] / RES, 2), round(s[2], 2), round(s[3], 2), s[4]] for s in secs],
            "top": round(h_top, 2), "walltop": round(walltop, 2), "top_seen": round(float(seen_top), 2),
            "fh": round(fh, 3), "pv": round(float(pv), 3), "bw": round(bw, 3), "cols": cols, "det": det,
            "wall": [int(v) for v in wall_c], "shade": round(float(o.shade), 3), "_tiles": tiles,
            "roofc": [int(v) for v in np.median(roof_px, 0)] if roof_px else None}


def pack(tile_lists, width=4096, max_h=4096):
    """[[tile arrays] per building] -> (atlas uint8 (H, W, 3), [[ [u0, v0, u1, v1] per tile ] per building]) with 2 px edge padding;
    tiles shrink by half until they fit.  uv per tile: [u left, v bottom, u right, v top] (v = 0 at the image's top row)."""
    for scale in (1, 2, 4, 8):
        x = y = row_h = 0
        rects, place = [], []
        ok = True
        for tl in tile_lists:
            rr = []
            for t in tl:
                h, w = max(2, t.shape[0] // scale), max(2, t.shape[1] // scale)
                if x + w + 4 > width:
                    x, y, row_h = 0, y + row_h, 0
                if y + h + 4 > max_h:
                    ok = False
                    break
                place.append((t, x + 2, y + 2, w, h))
                rr.append((x + 2, y + 2, w, h))
                x += w + 4
                row_h = max(row_h, h + 4)
            if not ok:
                break
            rects.append(rr)
        if ok:
            break
    H = max(4, y + row_h)
    H = 1 << (H - 1).bit_length()
    atlas = np.zeros((H, width, 3), np.uint8)
    for t, px, py, w, h in place:
        s = _resamp(t[::-1], h, w)                                     # analysis row 0 = bottom, image row 0 = top
        atlas[py:py + h, px:px + w] = s
        atlas[py - 2:py, px:px + w] = s[:1]
        atlas[py + h:py + h + 2, px:px + w] = s[-1:]
        atlas[py - 2:py + h + 2, px - 2:px] = atlas[py - 2:py + h + 2, px:px + 1]
        atlas[py - 2:py + h + 2, px + w:px + w + 2] = atlas[py - 2:py + h + 2, px + w - 1:px + w]
    # uv: v = 0 at the image's top row (raylib's texture origin); the tile's row 0 is the bottom of the floor
    uv = [[[px / width, (py + h) / H, (px + w) / width, py / H] for px, py, w, h in rr] for rr in rects]
    return atlas, uv
