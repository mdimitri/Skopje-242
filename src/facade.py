"""Facade analysis for src/photogram.py: one wall seen in one photo (resampled onto the wall plane, see photogram.Obs) ->
roof line, roof band (mansard / pitched roof slope seen above the wall), floor grid, bay columns and, per bay column, the numbers
the world build turns into procedural 3D: window opening, glass / frame / blind colours, mullions, recess or loggia depth, sill,
balcony slab and railing, AC units; per cell the wall colour and blind; per wall the surface (plaster / concrete / tiles / brick)
and its roughness.  The photo pixels are only looked at here (the median of each column over its floors, in memory): nothing
of them is written, so the fit can ship with the game.  numpy only (the game's embedded Python has no scipy / OpenCV).
"""
import warnings
from collections import deque

import numpy as np

L_BUILDING, L_SKY = 1, 2
LUM = np.array([.3, .59, .11])
RES = 12.0                                  # facade resampling for the detail analysis (pixels per metre)
TILE_PPM = 16.0                             # the in-memory column medians (pixels per metre)


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


def col_params(t, wall, fh, cw):
    """One bay column's median tile (rows: 0 = bottom of the floor) -> the numbers of its procedural cell (metres / RGB):
    win [x0, x1, y0, y1] (fractions of the cell), glass, frame, mull (glazing bars), blind [fraction from the top, r, g, b],
    rec (recess depth: 0.18 window, ~1 m loggia), sill, balc [depth, rail r, g, b, solid 1 / bars 0], ac [[u, v, w, h, r, g, b]]
    (u a fraction of the column width)."""
    th, tw = t.shape[:2]
    f = t.astype(np.float32)
    lum, sat = f @ LUM, f.max(2) - f.min(2)
    diff = np.abs(f - wall).sum(2)
    ppm = th / fh
    out = {"win": None, "glass": None, "frame": None, "mull": 0, "blind": None, "rec": 0.18, "sill": 0, "balc": None, "ac": []}
    # AC units: compact light / grey boxes
    dark = lum < 0.62 * np.percentile(lum, 70)
    cand = (diff > 70) & (sat < 45) & (lum > 120) & ~dark
    acm = np.zeros_like(cand)
    for ys, xs in _components(cand):
        w_, h_ = (np.ptp(xs) + 1) / ppm, (np.ptp(ys) + 1) / ppm
        fill = len(ys) / ((np.ptp(xs) + 1) * (np.ptp(ys) + 1))
        if 0.45 <= w_ <= 1.3 and 0.3 <= h_ <= 1.0 and fill > 0.55 and w_ < 0.8 * cw:
            c = np.median(f[ys, xs], 0)
            out["ac"].append([round((xs.mean() + 0.5) / tw, 3), round((ys.mean() + 0.5) / ppm, 2), round(w_, 2), round(h_, 2),
                              *[int(v) for v in c]])
            acm[ys, xs] = True
    # balcony: a bottom band (up to ~1.1 m) that differs from the wall and from the floor above it
    nb = max(2, min(th // 3, int(1.1 * ppm)))
    bot, mid = f[:nb][~acm[:nb]], f[nb:][~acm[nb:]]
    if len(bot) > 10 and len(mid) > 10 and np.abs(bot.mean(0) - mid.mean(0)).sum() > 45 and np.abs(np.median(bot, 0) - wall).sum() > 45:
        band = f[:nb]
        hx = np.abs(np.diff(band @ LUM, axis=1)).mean()             # bars flicker along the rail, a parapet is smooth
        out["balc"] = [0.9, *[int(v) for v in np.median(bot, 0)], 0 if hx > 14 else 1]
    # window: the biggest blob that is not wall (above the balcony band when there is one)
    y_lo = nb if out["balc"] else int(0.15 * th)
    nw = (diff > 45) & ~acm
    nw[:y_lo] = False
    best = None
    for ys, xs in _components(nw):
        if best is None or len(ys) > len(best[0]):
            best = (ys, xs)
    if best is not None and len(best[0]) > 0.04 * th * tw:
        ys, xs = best
        x0, x1 = np.percentile(xs, 8) / tw, (np.percentile(xs, 92) + 1) / tw
        y0, y1 = np.percentile(ys, 8) / th, (np.percentile(ys, 92) + 1) / th
        if out["balc"]:
            y0 = min(y0, (nb + 1) / th)                               # a balcony door reaches the slab
        x0, x1 = max(0.04, x0), min(0.96, x1)
        y0, y1 = max(0.04, y0), min(0.94, y1)
        if x1 - x0 > 0.12 and y1 - y0 > 0.15:
            X0, X1, Y0, Y1 = int(x0 * tw), int(x1 * tw), int(y0 * th), int(y1 * th)
            reg = f[Y0:Y1, X0:X1]
            rl_ = reg @ LUM
            mid_ = (rl_ >= np.percentile(rl_, 20)) & (rl_ <= np.percentile(rl_, 60))   # glass: the panes' middle tones (reflections, curtains)
            gl = np.median(reg[mid_].reshape(-1, 3), 0)
            out["win"] = [round(float(x0), 3), round(float(x1), 3), round(float(y0), 3), round(float(y1), 3)]
            out["glass"] = [int(v) for v in gl]
            fr = reg[(rl_ > gl @ LUM + 50) & ((reg.max(2) - reg.min(2)) < 40)]
            out["frame"] = [int(v) for v in (np.median(fr, 0) if len(fr) > 8 else np.minimum(255, wall * 1.05))]
            colp = (rl_ > gl @ LUM + 50).mean(0)                     # glazing bars: bright full-height columns inside the opening
            inner = colp[int(0.12 * len(colp)):int(0.88 * len(colp)) + 1] > 0.6
            out["mull"] = int(min(3, np.sum(np.diff(inner.astype(int)) == 1) + (1 if len(inner) and inner[0] else 0)))
            n_bl = 0                                                  # blind / roller shutter: light, flat rows from the top down
            for r in range(Y1 - 1, Y0 - 1, -1):
                row = f[r, X0:X1]
                if (row @ LUM).mean() > 150 and (row.max(1) - row.min(1)).mean() < 40:
                    n_bl += 1
                else:
                    break
            if n_bl > 0.12 * (Y1 - Y0):
                bc = np.median(f[Y1 - n_bl:Y1, X0:X1].reshape(-1, 3), 0)
                out["blind"] = [round(n_bl / max(1, Y1 - Y0), 2), *[int(v) for v in bc]]
            if x1 - x0 > 0.72 and y1 - y0 > 0.55 and gl @ LUM < 70:  # a wide dark opening: a loggia, not a window
                out["rec"] = 1.0
            out["sill"] = 0 if out["balc"] else 1
    return out


def surface(rgb, B, wall_c):
    """Wall finish from the photo: 'glass' (a dark / bluish, smooth curtain wall), 'metal' (bright, smooth, grey cladding),
    'brick' (red-brown and rough), 'tiles' (a fine regular grid), 'concrete' (grey, porous) or 'plaster', and how rough
    (0 smooth .. 1 coarse) -> (name, roughness)."""
    lum = rgb @ LUM
    near = B & (np.abs(rgb - wall_c).sum(2) < 35)                 # plain wall only: frames, edges and clutter would read as grain
    if near.sum() < 200:
        return "plaster", 0.3
    bl = np.full_like(lum, np.nan)
    bl[near] = lum[near]
    hp = []
    for dy, dx in ((0, 1), (1, 0)):
        d = bl[dy:, dx:] - bl[:bl.shape[0] - dy, :bl.shape[1] - dx]
        hp.append(np.nanstd(d))
    rough = float(np.clip((np.mean(hp) - 3.0) / 14.0, 0.0, 1.0))
    r, g, b = wall_c
    sat = max(wall_c) - min(wall_c)
    # fine regular grid: rows / columns of wall pixels repeat every 2-5 px (0.17-0.4 m)
    per = 0.0
    for prof in (np.nanmean(bl, 1), np.nanmean(bl, 0)):
        lag, st = _period(prof, 2, 5)
        per = max(per, st if lag else 0.0)
    L = 0.3 * r + 0.59 * g + 0.11 * b
    if L < 110 and b >= r - 5 and rough < 0.35:
        return "glass", rough
    if sat < 20 and L > 150 and rough < 0.12 and per < 0.3:
        return "metal", rough
    if r - b > 45 and sat > 45 and rough > 0.35:
        return "brick", rough
    if per > 0.45 and rough > 0.25:
        return "tiles", rough
    if sat < 30 and 110 <= L < 185 and rough > 0.1:              # grey and a little porous: bare concrete / prefab panels
        return "concrete", rough
    return "plaster", rough


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
    # ---- per bay column: the median over its floors (in memory only) -> procedural parameters; per cell its own wall colour
    TH = int(round(fh * TILE_PPM))
    params, cols, cells = [], [], {}
    for ci, (u0, u1) in enumerate(zip(ub[:-1], ub[1:])):
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
            px = rgb[b0:b1, a0:a1][mk]
            cw_ = np.median(px[np.abs(px - wall_c).sum(1) < 90], 0) if (np.abs(px - wall_c).sum(1) < 90).sum() > 10 else None
            if cw_ is not None and np.abs(cw_ - wall_c).sum() > 18:
                cells[f"{len(cols)},{i}"] = [int(v) for v in cw_]
            im = _resamp(rgb[b0:b1, a0:a1], TH, TW).copy()
            im[~_resamp(mk, TH, TW)] = np.nan
            stack.append(im)
        pi = -1
        if stack:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN pixels: nobody saw them, filled below
                e_ = np.nanmedian(np.array(stack), 0)
            if np.isnan(e_).mean() < 0.3:
                e_[np.isnan(e_)] = np.broadcast_to(wall_c, e_.shape)[np.isnan(e_)]
                params.append(col_params(e_, wall_c, fh, u1 - u0))
                pi = len(params) - 1
        cols.append([round(float(u0), 2), round(float(u1), 2), pi, len(stack)])
    if not params:
        return None
    seen_ids = [c for c in cols if c[2] >= 0]                    # columns nobody saw clearly: the nearest seen column
    for c in cols:
        if c[2] < 0:
            c[2] = min(seen_ids, key=lambda s: abs((s[0] + s[1]) - (c[0] + c[1])))[2]
    surf, rough = surface(rgb, B, wall_c)
    if log:
        log(f"    ѕид {o.wi}: {o.ln:.1f} м, врв {h_top:.1f} м, ѕид до {walltop:.1f} м, покрив {max(s[3] for s in secs):.1f} м, "
            f"кат {fh:.2f} м, колони {len(cols)} ({len(params)} видени), површина {surf} {rough:.2f}, прозорци "
            f"{sum(1 for p in params if p['win'])}, ролетни {sum(1 for p in params if p['blind'])}, лоѓии {sum(1 for p in params if p['rec'] > 0.5)}, "
            f"клима {sum(len(p['ac']) for p in params)}, балкони {sum(1 for p in params if p['balc'])}, ќелии со своја боја {len(cells)}")
    return {"wi": o.wi, "a": [round(float(v), 2) for v in o.a], "b": [round(float(v), 2) for v in o.b], "ln": round(float(o.ln), 2),
            "secs": [[round(s[0] / RES, 2), round(s[1] / RES, 2), round(s[2], 2), round(s[3], 2), s[4]] for s in secs],
            "top": round(h_top, 2), "walltop": round(walltop, 2), "top_seen": round(float(seen_top), 2),
            "fh": round(fh, 3), "pv": round(float(pv), 3), "bw": round(bw, 3), "cols": cols, "params": params, "cells": cells,
            "surf": surf, "rough": round(rough, 2),
            "wall": [int(v) for v in wall_c], "shade": round(float(o.shade), 3),
            "roofc": [int(v) for v in np.median(roof_px, 0)] if roof_px else None}
