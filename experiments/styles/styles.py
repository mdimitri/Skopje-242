"""Image-space style experiments on a real game frame. Usage: python styles.py [raw_png]"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "raw", "a_11.png")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(1)


def load():
    im = cv2.imread(SRC)
    h, w = im.shape[:2]
    s = w / 1920
    mask = np.zeros((h, w), np.uint8)
    for x0, y0, x1, y1 in [(695, 578, 1215, 618)]:
        mask[int(y0 * s):int(y1 * s), int(x0 * s):int(x1 * s)] = 255
    im = cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA)
    cw, ch = int(1111 * s), int(625 * s)
    x0, y0 = int(450 * s), int(450 * s)
    im = im[y0:y0 + ch, x0:x0 + cw]
    return cv2.resize(im, (1280, 720), interpolation=cv2.INTER_AREA)


def edges(im, t1=60, t2=140, k=2):
    g = cv2.cvtColor(cv2.bilateralFilter(im, 7, 50, 50), cv2.COLOR_BGR2GRAY)
    return cv2.dilate(cv2.Canny(g, t1, t2), np.ones((k, k), np.uint8))


def posterize(im, n):
    q = 256 // n
    return ((im // q) * q + q // 2).astype(np.uint8)


def kmeans(im, k):
    d = im.reshape(-1, 3).astype(np.float32)
    _, lab, c = cv2.kmeans(d, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0), 1, cv2.KMEANS_PP_CENTERS)
    return c[lab.flatten()].reshape(im.shape).astype(np.uint8)


def gray(im):
    return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)


def hsv_shift(im, h=0, s=1.0, v=1.0):
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + h) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * s, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * v, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def gradmap(g, stops):
    xs = [s[0] * 255 for s in stops]
    out = np.zeros(g.shape + (3,), np.float32)
    for c in range(3):
        out[..., c] = np.interp(g, xs, [s[1][c] for s in stops])
    return out.astype(np.uint8)


def vignette(im, a=0.5):
    h, w = im.shape[:2]
    y, x = np.mgrid[0:h, 0:w]
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2)
    return np.clip(im * (1 - a * np.clip(r - 0.4, 0, 1)[..., None]), 0, 255).astype(np.uint8)


def halftone(ch, cell=9):
    h, w = ch.shape
    out = np.zeros((h, w), np.uint8)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            v = ch[y:y + cell, x:x + cell].mean() / 255
            cv2.circle(out, (x + cell // 2, y + cell // 2), int(cell * 0.72 * np.sqrt(v)), 255, -1)
    return out


def s_cel(im):
    sm = cv2.bilateralFilter(cv2.bilateralFilter(im, 9, 60, 60), 9, 60, 60)
    c = posterize(hsv_shift(sm, 0, 1.25, 1.0), 6)
    c[edges(im, 70, 160, 2) > 0] = (10, 10, 10)
    return c


def s_toy(im):
    sm = cv2.edgePreservingFilter(im, flags=1, sigma_s=60, sigma_r=0.4)
    c = hsv_shift(kmeans(sm, 9), 0, 0.55, 1.15)
    c = cv2.addWeighted(c, 0.75, np.full_like(c, (235, 225, 255)), 0.25, 0)
    return cv2.GaussianBlur(c, (0, 0), 1.2)


def s_popart(im):
    g = gray(cv2.bilateralFilter(im, 9, 60, 60))
    base = posterize(gradmap(g, [(0, (60, 0, 120)), (0.35, (200, 40, 220)), (0.6, (0, 60, 255)), (1, (0, 240, 255))]), 3)
    dots = halftone(255 - g, 8)
    base[dots > 0] = (base[dots > 0] * 0.55).astype(np.uint8)
    base[edges(im, 80, 170, 3) > 0] = (0, 0, 0)
    return base


def s_noir(im):
    g = cv2.createCLAHE(3.0, (8, 8)).apply(gray(im))
    g = np.clip((g.astype(np.float32) - 90) * 1.7 + 70, 0, 255)
    g = np.clip(g + rng.normal(0, 14, g.shape), 0, 255).astype(np.uint8)
    o = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    h, w = g.shape
    y, x = np.mgrid[0:h, 0:w]
    beam = np.clip(np.sin((x * 0.6 + y) / 70.0) * 0.5, 0, 1)[..., None] * 38
    return vignette(np.clip(o.astype(np.float32) + beam, 0, 255).astype(np.uint8), 0.9)


def s_neon(im):
    d = hsv_shift(cv2.convertScaleAbs(im, alpha=0.35, beta=0), 135, 1.0, 0.8)
    d[..., 0] = np.clip(d[..., 0].astype(np.float32) * 1.4 + 25, 0, 255)
    e = edges(im, 60, 150, 2)
    h, w = e.shape
    mag = np.zeros_like(d); mag[e > 0] = (255, 40, 255)
    cyan = np.zeros_like(d); cyan[e > 0] = (255, 240, 20)
    m = np.linspace(0, 1, w)[None, :, None]
    lines = (mag * (1 - m) + cyan * m).astype(np.uint8)
    bloom = cv2.GaussianBlur(lines, (0, 0), 7).astype(np.float32) * 2
    bright = cv2.GaussianBlur(cv2.threshold(gray(im), 215, 255, cv2.THRESH_BINARY)[1], (0, 0), 6).astype(np.float32)
    glowb = cv2.merge([bright, bright * 0, bright * 0.6])
    out = np.clip(d.astype(np.float32) + bloom + lines * 0.9 + glowb * 0.7, 0, 255)
    out[::3] *= 0.8
    return vignette(out.astype(np.uint8), 0.6)


def s_watercolor(im):
    c = cv2.bilateralFilter(cv2.stylization(im, sigma_s=70, sigma_r=0.5), 9, 70, 70)
    paper = cv2.GaussianBlur(rng.normal(0, 1, im.shape[:2]).astype(np.float32), (0, 0), 1.2)
    big = cv2.resize(rng.normal(0, 1, (36, 64)).astype(np.float32), (1280, 720), interpolation=cv2.INTER_CUBIC)
    c = c.astype(np.float32) * (1 + 0.04 * paper[..., None] + 0.035 * big[..., None])
    c = 255 - (255 - c) * 0.85
    e = cv2.GaussianBlur(edges(im, 50, 120, 1), (0, 0), 1.0)
    c = c * (1 - 0.35 * (e[..., None] / 255.0))
    return np.clip(c, 0, 255).astype(np.uint8)


def s_blueprint(im):
    e = edges(im, 45, 120, 2)
    fill = cv2.GaussianBlur(gray(im), (0, 0), 3)
    bg = np.clip(np.full(im.shape, (110, 55, 15), np.float32) + fill[..., None] * 0.12, 0, 255).astype(np.uint8)
    h, w = e.shape
    for x in range(0, w, 40):
        cv2.line(bg, (x, 0), (x, h), (150, 90, 40), 1)
    for y in range(0, h, 40):
        cv2.line(bg, (0, y), (w, y), (150, 90, 40), 1)
    bg[e > 0] = (255, 245, 235)
    return bg


def s_clay(im):
    sm = cv2.bilateralFilter(cv2.edgePreservingFilter(im, flags=1, sigma_s=40, sigma_r=0.6), 15, 80, 80)
    c = hsv_shift(sm, 0, 0.8, 1.0)
    g = gray(sm).astype(np.float32)
    gb = cv2.GaussianBlur(g, (0, 0), 2)
    shade = np.clip(1 + (-cv2.Sobel(gb, cv2.CV_32F, 1, 0) - cv2.Sobel(gb, cv2.CV_32F, 0, 1)) * 0.012, 0.6, 1.5)[..., None]
    c = c.astype(np.float32) * shade
    fp = cv2.GaussianBlur(rng.normal(0, 1, g.shape).astype(np.float32), (0, 0), 0.8)
    c = c * (1 + 0.05 * fp[..., None]) * np.array([0.9, 1.0, 1.1])
    spec = np.clip(cv2.GaussianBlur(g, (0, 0), 4) - cv2.GaussianBlur(g, (0, 0), 14), 0, 255)[..., None] * 0.6
    return np.clip(c + spec, 0, 255).astype(np.uint8)


def s_lowpoly(im):
    h, w = im.shape[:2]
    e = cv2.Canny(cv2.GaussianBlur(gray(im), (0, 0), 2), 40, 110)
    ys, xs = np.nonzero(e)
    sel = rng.choice(len(xs), min(2200, len(xs)), replace=False)
    pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)] + [(int(xs[i]), int(ys[i])) for i in sel]
    pts += [(int(rng.integers(w)), int(rng.integers(h))) for _ in range(500)]
    sub = cv2.Subdiv2D((0, 0, w, h))
    for p in pts:
        sub.insert(p)
    out = np.zeros_like(im)
    for t in sub.getTriangleList().reshape(-1, 3, 2):
        tri = t.astype(np.int32)
        if (tri < -5).any() or (tri[:, 0] > w + 5).any() or (tri[:, 1] > h + 5).any():
            continue
        cen = np.clip(tri.mean(0), 0, [w - 1, h - 1]).astype(int)
        cv2.fillConvexPoly(out, tri, im[cen[1], cen[0]].tolist(), cv2.LINE_8)
    return hsv_shift(out, 0, 1.15, 1.0)


def s_vapor(im):
    g = gray(cv2.bilateralFilter(im, 9, 50, 50))
    h, w = g.shape
    y = np.linspace(0, 1, h)[:, None]
    grad = np.clip((g.astype(np.float32) / 255) ** 1.8 * 0.75 + y * 0.2, 0, 1)
    out = gradmap((grad * 255).astype(np.uint8), [(0, (110, 30, 70)), (0.35, (200, 90, 200)), (0.65, (255, 150, 255)), (0.85, (190, 220, 255)), (1, (200, 255, 255))])
    sun_y = int(h * 0.15)
    yy, xx = np.mgrid[0:h, 0:w]
    sun = ((xx - w * 0.82) ** 2 + (yy - sun_y) ** 2) < 120 ** 2
    stripes = (yy > sun_y) & ((yy % 16) < (yy - sun_y + 120) / 15)
    keep = sun & ~stripes
    out[keep & (yy <= sun_y)] = (80, 120, 255)
    out[keep & (yy > sun_y)] = (150, 90, 255)
    out[edges(im, 80, 170, 1) > 0] = (255, 255, 120)
    return np.clip(out.astype(np.float32) + cv2.GaussianBlur(out, (0, 0), 6) * 0.5, 0, 255).astype(np.uint8)


def s_pixel(im):
    h, w = im.shape[:2]
    small = hsv_shift(cv2.resize(im, (w // 5, h // 5), interpolation=cv2.INTER_AREA), 0, 1.2, 1.0)
    cols = np.unique(kmeans(small, 16).reshape(-1, 3), axis=0).astype(np.float32)
    bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - 0.5
    bb = np.tile(bayer, (small.shape[0] // 4 + 1, small.shape[1] // 4 + 1))[:small.shape[0], :small.shape[1], None]
    dith = np.clip(small.astype(np.float32) + bb * 40, 0, 255)
    d = ((dith.reshape(-1, 1, 3) - cols[None]) ** 2).sum(2).argmin(1)
    return cv2.resize(cols[d].reshape(dith.shape).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)


def s_gameboy(im):
    g = gray(cv2.resize(cv2.resize(im, (213, 120), interpolation=cv2.INTER_AREA), (1280, 720), interpolation=cv2.INTER_NEAREST))
    q = (cv2.createCLAHE(2.0, (4, 4)).apply(g) // 64).astype(np.uint8)
    pal = np.array([(15, 56, 15), (48, 98, 48), (139, 172, 15), (155, 188, 15)], np.uint8)[:, ::-1]
    return pal[q]


def s_thermal(im):
    return gradmap(gray(im), [(0, (60, 0, 20)), (0.25, (180, 0, 120)), (0.5, (0, 60, 255)), (0.75, (0, 200, 255)), (1, (240, 255, 255))])


def s_ukiyo(im):
    sm = cv2.bilateralFilter(im, 9, 70, 70)
    pal = np.array([(235, 228, 205), (160, 110, 40), (90, 60, 30), (60, 70, 200), (80, 140, 80), (60, 180, 220), (40, 30, 25), (200, 180, 140)], np.float32)
    d = ((sm.reshape(-1, 1, 3).astype(np.float32) - pal[None]) ** 2).sum(2).argmin(1)
    c = cv2.medianBlur(pal[d].reshape(sm.shape).astype(np.uint8), 5)
    c[edges(im, 70, 160, 2) > 0] = (35, 25, 20)
    paper = cv2.GaussianBlur(rng.normal(0, 1, c.shape[:2]).astype(np.float32), (0, 0), 1.0)
    return np.clip(c * (1 + 0.04 * paper[..., None]), 0, 255).astype(np.uint8)


STYLES = [("cel_outline", s_cel), ("toy_pastel", s_toy), ("popart_halftone", s_popart), ("noir", s_noir), ("neon_synthwave", s_neon),
          ("watercolor", s_watercolor), ("blueprint", s_blueprint), ("claymation", s_clay), ("lowpoly", s_lowpoly),
          ("vaporwave_sunset", s_vapor), ("pixel_dither", s_pixel), ("gameboy", s_gameboy), ("thermal", s_thermal), ("ukiyoe_woodblock", s_ukiyo)]

if __name__ == "__main__":
    im = load()
    cv2.imwrite(os.path.join(OUT, "baseline.png"), im)
    for i, (n, f) in enumerate(STYLES, 1):
        cv2.imwrite(os.path.join(OUT, f"{i:02d}_{n}.png"), f(im))
        print("ok", n)
