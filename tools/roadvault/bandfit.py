"""Bounded satellite fit of road cross-sections, measured ONLY inside the OSM road bands.
OSM keeps topology and alignment, CS2 rules keep the limits; the satellite only picks width / lane count / sidewalk
width per OSM way.  Robust by construction:
  * colours normalised per image (asphalt reference = median of grey pixels on the OSM centrelines, so Skopje's
    lighter asphalt or a hazy capture does not bias anything);
  * every 3 m a cross-section is labelled asphalt / pavement / vegetation / unknown (cars, shadow, paint);
    unknown gaps up to 2.2 m are bridged, profiles that run into the search limit (car parks, plazas) or start
    off-asphalt (trees, shadow) are rejected;
  * per way: median after 2.5-MAD outlier rejection, needs >= 5 valid sections and >= 30 % of them, else OSM default;
  * lane count = width vote and painted-line vote (lines found as peaks in the along-road averaged profile),
    restricted to CS2-legal values (two-way even, lane width 2.7-3.7 m, at most +-2 lanes from the OSM tag).
Metrics (SSIM, PSNR, kerb-line distance, edge-orientation agreement, per-way width residual) are computed only inside the OSM band mask, after per-image normalisation."""
import math
import numpy as np
from PIL import Image, ImageDraw

STEP, DS = 3.0, 0.25


def img_arr(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)


def sampler(A, s):
    H, W, _ = A.shape

    def at(xy):                                                       # plan (east, north) metres -> bilinear RGB
        px = xy[..., 0] / s + W / 2 - 0.5
        py = H / 2 - xy[..., 1] / s - 0.5
        ok = (px >= 0) & (py >= 0) & (px < W - 1) & (py < H - 1)
        px, py = np.clip(px, 0, W - 1.001), np.clip(py, 0, H - 1.001)
        x0, y0 = px.astype(int), py.astype(int)
        fx, fy = (px - x0)[..., None], (py - y0)[..., None]
        v = (A[y0, x0] * (1 - fx) * (1 - fy) + A[y0, x0 + 1] * fx * (1 - fy) + A[y0 + 1, x0] * (1 - fx) * fy + A[y0 + 1, x0 + 1] * fx * fy)
        return v, ok
    return at


def frames(e, junc_mask=None):
    ls = e["ls"]
    out = []
    for t in np.arange(STEP, ls.length - STEP + 1e-6, STEP):
        a, b = ls.interpolate(t - 1.0), ls.interpolate(t + 1.0)
        tv = np.array([b.x - a.x, b.y - a.y])
        tv /= np.hypot(*tv) + 1e-9
        c = ls.interpolate(t)
        if junc_mask is not None and junc_mask.contains(c):
            continue
        out.append((np.array([c.x, c.y]), tv, np.array([-tv[1], tv[0]])))
    return out


def reference(at, drive):
    px = []
    for e in drive:
        for c, tv, nv in frames(e):
            v, ok = at(np.array([c, c + nv * 0.5, c - nv * 0.5]))
            px.append(v[ok])
    px = np.concatenate(px) if px else np.zeros((0, 3))
    sat = px.max(1) - px.min(1)
    g = px[sat < 22]
    if len(g) < 50:
        return np.array([135.0, 130.0, 132.0]), 16.0
    ref = np.median(g, 0)
    mad = np.median(np.abs(g.mean(1) - ref.mean()))
    return ref, float(np.clip(2.5 * 1.4826 * mad, 12.0, 30.0))


def labels(v, ref, tol):
    """0 unknown, 1 asphalt, 2 pavement, 3 vegetation, 4 paint (thin bright)."""
    lum = v.mean(-1)
    sat = v.max(-1) - v.min(-1)
    d = np.abs(v - ref).max(-1)
    L = np.zeros(v.shape[:-1], np.int8)
    rl = ref.mean()
    L[(d < tol) & (sat < 26)] = 1
    L[(lum > rl + max(14.0, tol * 0.8)) & (sat < 24) & (L == 0)] = 2
    L[(v[..., 1] > v[..., 0] + 6) & (v[..., 1] > v[..., 2] + 4)] = 3
    L[(lum > rl + 55) & (sat < 30)] = 4
    return L


def run(lab, i0, step, maxgap):
    """walk from i0 while asphalt / paint / short unknown; return (stop index, stopped by a real boundary)."""
    i, gap = i0, 0
    n = len(lab)
    while 0 <= i + step < n:
        j = i + step
        if lab[j] in (1, 4):
            gap = 0
        elif lab[j] == 0:
            gap += 1
            if gap > maxgap:                                          # long unknown (kerb shadow, dirt, wall): soft edge
                return i - step * (gap - 1), True
        else:
            return j - step * gap, True
        i = j
    return i, False


def measure(path, drive, s, junc_mask=None):
    A = img_arr(path)
    at = sampler(A, s)
    ref, tol = reference(at, drive)
    res = {}
    for e in drive:
        r = e["r"]
        if not r.get("nodes"):
            continue
        sp = e["sp"]
        R = min(22.0, sp["w"] / 2 + 12.0)
        offs = np.arange(-R, R + 1e-6, DS)
        ic = len(offs) // 2
        widths, sws, profs = [], [], []
        fr = frames(e, junc_mask)
        n_in = 0
        for c, tv, nv in fr:
            xy = c[None, :] + offs[:, None] * nv[None, :]
            v, ok = at(xy)
            if ok.mean() < 0.95:
                continue
            n_in += 1
            lab = labels(v, ref, tol)
            cand = [k for k in range(ic - 6, ic + 7) if lab[k] == 1]   # centre within 1.5 m on asphalt
            if not cand:
                continue
            k0 = min(cand, key=lambda k: abs(k - ic))
            gap = int(2.2 / DS)
            lo, okl = run(lab, k0, -1, gap)
            hi, okh = run(lab, k0, 1, gap)
            if not (okl and okh):
                continue
            w = (hi - lo + 1) * DS
            if w < 2.4:
                continue
            widths.append(w)
            lum = v.mean(-1)
            profs.append((lum - np.median(lum[lo:hi + 1]), lo, hi))
            for side, edge in ((-1, lo), (1, hi)):                    # sidewalk: pavement run beyond the asphalt edge
                k, gp, cnt = edge + side, 0, 0
                while 0 <= k < len(lab) and gp <= int(1.0 / DS):
                    if lab[k] == 2:
                        cnt += 1 + gp
                        gp = 0
                    elif lab[k] == 0:
                        gp += 1
                    else:
                        break
                    k += side
                if 0 <= k < len(lab) and cnt > 0:
                    sws.append(cnt * DS)
        nv_ = n_in
        out = dict(n_sec=nv_, n_ok=len(widths))
        if len(widths) >= 5 and len(widths) >= 0.3 * max(nv_, 1):
            w = np.array(widths)
            med = np.median(w)
            mad = 1.4826 * np.median(np.abs(w - med)) + 0.15
            w = w[np.abs(w - med) <= 2.5 * mad]
            out["w"] = float(np.median(w))
            out["w_spread"] = float(mad)
            # painted lines: average profiles aligned on the asphalt centre
            span = int(round(np.median([hi - lo for _, lo, hi in profs])))
            acc = np.zeros(span + 1)
            cntp = 0
            for p, lo, hi in profs:
                if abs((hi - lo) - span) <= 2:
                    seg = p[lo:lo + span + 1]
                    if len(seg) == span + 1:
                        acc += seg
                        cntp += 1
            if cntp >= 5:
                acc /= cntp
                inner = acc[int(0.6 / DS):len(acc) - int(0.6 / DS)]
                base = np.median(inner)
                pk = [i for i in range(1, len(inner) - 1) if inner[i] > base + 7 and inner[i] >= inner[i - 1] and inner[i] >= inner[i + 1]]
                lines = []
                for i in pk:                                          # merge peaks closer than 1.2 m (double centre line)
                    if not lines or (i - lines[-1]) * DS > 1.2:
                        lines.append(i)
                out["lines"] = len(lines)
        if len(sws) >= 5:
            q = np.array(sws)
            out["sw"] = float(np.clip(np.median(q), 1.0, 5.0))
        res[id(e)] = out
    return res, (ref, tol)


def legal(meas, e, lw_pref):
    """CS2-legal (n, lw, sw) from a measurement, or None to keep the OSM default."""
    sp = e["sp"]
    if "w" not in meas:
        return None
    w = meas["w"]
    n0 = sp["n"]
    cands = range(1, 6) if sp["ow"] else (2, 4, 6)
    best, bc = None, 1e9
    for n in cands:
        if abs(n - n0) > 2:
            continue
        lw = w / n
        if not 2.7 <= lw <= 3.7:
            continue
        cost = abs(lw - lw_pref)
        if "lines" in meas and meas["lines"] + 1 == n:
            cost -= 0.35                                              # painted lines agree
        if n == n0:
            cost -= 0.1                                               # tie goes to OSM
        if cost < bc:
            best, bc = n, cost
    if best is None:
        return None
    out = dict(n=best, lw=float(np.clip(w / best, 2.7, 3.7)), fit=True)
    if "sw" in meas:
        out["sw"] = meas["sw"]
    return out


# ---------------- metrics inside the OSM band mask ----------------

def band_mask(drive, s, size, extra=3.0):
    W = H = size
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for e in drive:
        P = e["pts"]
        px = [(x / s + W / 2, H / 2 - y / s) for x, y in P]
        wd = max(2, int((e["sp"]["w"] + 2 * e["sp"]["sw"] + 2 * extra) / s))
        d.line(px, fill=255, width=wd, joint="curve")
    return np.asarray(im) > 0


def _blur(a, sig):
    r = int(3 * sig) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sig) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda m: np.convolve(m, k, "same"), 0, a)
    return np.apply_along_axis(lambda m: np.convolve(m, k, "same"), 1, a)


def _norm(g, M):
    mu, sd = g[M].mean(), g[M].std() + 1e-6
    return np.clip(0.5 + (g - mu) / sd / 6.0, 0, 1)


def metrics(sat_img, ren_img, M, ref, tol):
    """masked SSIM / PSNR on normalised luminance, asphalt IoU on class maps; returns (dict, error map 0..1)."""
    a = np.asarray(sat_img.convert("RGB")).astype(np.float32)
    b = np.asarray(ren_img.convert("RGB")).astype(np.float32)
    ga, gb = _norm(a.mean(-1), M), _norm(b.mean(-1), M)
    sig = 2.0
    mu1, mu2 = _blur(ga, sig), _blur(gb, sig)
    s11, s22, s12 = _blur(ga * ga, sig) - mu1 ** 2, _blur(gb * gb, sig) - mu2 ** 2, _blur(ga * gb, sig) - mu1 * mu2
    C1, C2 = 0.01 ** 2, 0.03 ** 2
    ss = ((2 * mu1 * mu2 + C1) * (2 * s12 + C2)) / ((mu1 ** 2 + mu2 ** 2 + C1) * (s11 + s22 + C2))
    mse = float(((ga - gb) ** 2)[M].mean())
    # asphalt maps (satellite: majority-smoothed labels; render: asphalt colour), their edges = kerb lines
    from cs2_build import ASPH
    la = _blur((labels(a, ref, tol) == 1).astype(np.float32), 1.5) > 0.5
    lb = np.abs(b - np.array(ASPH, np.float32)).max(-1) < 18
    Mi = _blur(M.astype(np.float32), 2.0) > 0.99                      # keep away from the band border
    kerb = _chamfer(_edges(la) & Mi, _edges(lb) & Mi)
    # edge-orientation agreement: |cos| of gradient angles weighted by joint gradient strength (contrast/brightness invariant)
    ya, xa = np.gradient(mu1)
    yb, xb = np.gradient(mu2)
    ma, mb = np.hypot(xa, ya), np.hypot(xb, yb)
    wgt = np.sqrt(ma * mb) * M
    cosd = np.abs(xa * xb + ya * yb) / (ma * mb + 1e-9)
    orient = float((wgt * cosd).sum() / (wgt.sum() + 1e-9))
    err = np.clip((1 - ss) / 1.2, 0, 1)
    err[~M] = 0
    return dict(ssim=float(ss[M].mean()), psnr=float(10 * math.log10(1.0 / max(mse, 1e-9))), kerb_px=kerb, orient=orient), err, la, lb


def _edges(m):
    e = np.zeros_like(m)
    e[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    return e


def _chamfer(ea, eb, cap=4000):
    """symmetric trimmed (median) distance between two edge sets, in pixels; robust to clutter."""
    pa, pb = np.argwhere(ea).astype(np.float32), np.argwhere(eb).astype(np.float32)
    if len(pa) < 20 or len(pb) < 20:
        return float("nan")
    rng = np.random.default_rng(0)
    pa = pa[rng.choice(len(pa), min(cap, len(pa)), replace=False)]
    pb = pb[rng.choice(len(pb), min(cap, len(pb)), replace=False)]

    def nn(p, q):
        out = np.empty(len(p), np.float32)
        for i in range(0, len(p), 500):
            d = ((p[i:i + 500, None, :] - q[None, :, :]) ** 2).sum(-1)
            out[i:i + 500] = np.sqrt(d.min(1))
        return out
    d = np.concatenate([nn(pa, pb), nn(pb, pa)])
    return float(np.median(d))


def heat(sat_img, err, M, la, lb, s_ren):
    """dim satellite; OSM band tinted by smoothed structural error; satellite kerb lines coloured by their distance to
    our kerb lines (green < 0.5 m, yellow ~1 m, red >= 2 m)."""
    base = np.asarray(sat_img.convert("L").convert("RGB")).astype(np.float32) * 0.45
    e = _blur(err, 5.0)
    t = np.clip(e / 0.8, 0, 1)[..., None]
    tint = np.concatenate([t, 0.2 + 0 * t, 1 - t], -1) * 255
    out = base.copy()
    out[M] = 0.55 * base[M] + 0.45 * tint[M]
    Mi = _blur(M.astype(np.float32), 2.0) > 0.99
    ea, eb = _edges(la) & Mi, _edges(lb) & Mi
    pa, pb = np.argwhere(ea), np.argwhere(eb).astype(np.float32)
    if len(pa) and len(pb):
        d = np.empty(len(pa), np.float32)
        for i in range(0, len(pa), 400):
            d[i:i + 400] = np.sqrt(((pa[i:i + 400, None, :].astype(np.float32) - pb[None, :, :]) ** 2).sum(-1).min(1))
        dm = d * s_ren
        c = np.stack([np.clip(dm, 0, 1), np.clip(2 - dm, 0, 1), 0 * dm], -1) * 255
        for oy, ox in ((0, 0), (1, 0), (0, 1)):
            yy, xx = np.clip(pa[:, 0] + oy, 0, M.shape[0] - 1), np.clip(pa[:, 1] + ox, 0, M.shape[1] - 1)
            out[yy, xx] = c
    out[eb] = np.array([255, 255, 255])
    return Image.fromarray(out.astype(np.uint8))
