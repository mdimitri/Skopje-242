"""How close a rendered building is to its photo (src/photoview.py ОЦЕНИ): PSNR and SSIM on the building's pixels only, after the
render's colours are matched to the photo's (a per-channel gain + offset, so exposure / white balance / haze do not count), so
the numbers measure shape, rhythm and relative colour.  numpy only."""
import numpy as np


def match(ren, ph, mask):
    """ren, ph: (H, W, 3) float 0..255; -> ren with each channel fitted to the photo over the mask (least squares a*x + b)."""
    out = ren.copy()
    m = mask.astype(bool)
    if m.sum() < 50:
        return out
    for k in range(3):
        x, y = ren[..., k][m], ph[..., k][m]
        vx = x.var()
        a = float(((x - x.mean()) * (y - y.mean())).mean() / vx) if vx > 1e-6 else 0.0
        a = float(np.clip(a, 0.2, 5.0))
        out[..., k] = np.clip(a * (ren[..., k] - x.mean()) + y.mean(), 0, 255)
    return out


def psnr(a, b, mask):
    m = mask.astype(bool)
    if m.sum() < 50:
        return 0.0
    mse = float(((a[m] - b[m]) ** 2).mean())
    return 99.0 if mse < 1e-9 else float(10 * np.log10(255.0 ** 2 / mse))


def _box(x, r):
    """Mean over a (2r+1)^2 window (summed-area table, edges clamped)."""
    p = np.pad(x, r + 1, mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s[:x.shape[0], :x.shape[1]] / (k * k)


def ssim(a, b, mask, r=3):
    """Mean SSIM of the luminance over the mask (7x7 windows)."""
    m = mask.astype(bool)
    if m.sum() < 50:
        return 0.0
    w = np.array([0.299, 0.587, 0.114])
    x, y = a @ w, b @ w
    mx, my = _box(x, r), _box(y, r)
    vx, vy = _box(x * x, r) - mx * mx, _box(y * y, r) - my * my
    cxy = _box(x * y, r) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    s = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    return float(s[m].mean())


def score(ren, ph, mask):
    """-> (psnr dB, ssim, colour-matched render)."""
    ren, ph = ren.astype(np.float64), ph.astype(np.float64)
    rm = match(ren, ph, mask)
    return psnr(rm, ph, mask), ssim(rm, ph, mask), rm
