"""Profile-lofted car bodies: a real side profile (nose, bonnet, windscreen, roof, rear glass / tailgate, deck), real wheelbase and
per-model face details, instead of one generic box-plus-cabin.  Pure numpy; gl3d.car_arrays calls build() for the car-like styles.

Positions are fractions f of the body length measured from the FRONT (f=0 nose, f=1 tail); heights are metres.
"""
import numpy as np

LOFT_STYLES = ("hatch", "sedan", "taxi", "mini", "wagon", "suv", "van", "limo")

# profile knots: fc cowl (bonnet end / windscreen foot), fr1 roof front, fr0 roof rear, fd rear-glass foot (deck start);
# dn nose top below the belt, dc cowl above the belt, dd deck above the belt, dt tail top below the deck; tw roof width / body width;
# rnd plan rounding; gc ground clearance; hl head lamp kind, gr grille kind, tl tail lamp kind, bp bumper kind; win side glass; nw windows
_BASE = dict(dn=0.08, dc=0.03, dd=0.0, dt=0.0, tw=0.82, rnd=0.3, gc=0.24, hl="rect", gr="blk", tl="wide", bp="black", win="all", nw=2,
             pf=0.46, fwe=0.45, tr=None, hood=0.0)
ARCH = {
    "hatch_boxy": dict(fc=0.30, fr1=0.475, fr0=0.835, fd=0.965, dn=0.05, dd=0.10, dt=0.05, tw=0.84, rnd=0.12, tl="tall", fwe=0.30, bp="chrome"),
    "hatch_soft": dict(fc=0.315, fr1=0.51, fr0=0.82, fd=0.955, dn=0.15, dc=0.04, dd=0.08, dt=0.06, tw=0.80, rnd=0.45, hl="wrap",
                       gr="slim", tl="tall", fwe=0.30),
    "mini": dict(fc=0.255, fr1=0.42, fr0=0.82, fd=0.955, dn=0.10, dc=0.05, dd=0.06, dt=0.08, tw=0.80, rnd=0.6, hl="round", tl="tall", fwe=0.30),
    "notch_boxy": dict(fc=0.375, fr1=0.545, fr0=0.745, fd=0.83, dn=0.05, dc=0.02, dd=0.0, dt=0.0, tw=0.85, rnd=0.12, gr="chrome",
                       tl="wide", bp="chrome", fwe=0.45),
    "notch_soft": dict(fc=0.36, fr1=0.545, fr0=0.75, fd=0.84, dn=0.14, dc=0.03, dd=-0.02, dt=0.0, tw=0.79, rnd=0.4, hl="wrap",
                       gr="slim", tl="wide", fwe=0.45),
    "wagon": dict(fc=0.335, fr1=0.51, fr0=0.935, fd=0.985, dn=0.10, dc=0.03, dd=0.12, dt=0.06, tw=0.82, rnd=0.3, hl="wrap",
                  gr="slim", tl="tall", nw=3, fwe=0.30),
    "suv_box": dict(fc=0.27, fr1=0.43, fr0=0.94, fd=0.985, dn=0.02, dc=0.10, dd=0.14, dt=0.0, tw=0.88, rnd=0.1, gc=0.30, hl="round",
                    gr="slats", tl="tall", nw=3, fwe=0.30, bp="black"),
    "suv_soft": dict(fc=0.33, fr1=0.515, fr0=0.915, fd=0.975, dn=0.10, dc=0.06, dd=0.14, dt=0.05, tw=0.80, rnd=0.35, gc=0.28, hl="wrap",
                     gr="slim", tl="tall", nw=3, fwe=0.30),
    "van_cab": dict(fc=0.17, fr1=0.27, fr0=0.985, fd=0.995, dn=0.0, dc=0.0, dd=0.0, dt=0.0, tw=0.94, rnd=0.12, gc=0.28, hl="rect",
                    gr="blk", tl="tall", nw=4, fwe=0.30, bp="black"),
    "mpv": dict(fc=0.27, fr1=0.43, fr0=0.935, fd=0.975, dn=0.10, dc=0.05, dd=0.14, dt=0.03, tw=0.84, rnd=0.35, hl="wrap", gr="slim",
                tl="tall", nw=3, fwe=0.30),
}
# name -> (arch, wheelbase / length, overrides)   (wheelbase ratios from the real cars' data sheets)
SPEC = {
    "Zastava Yugo": ("hatch_boxy", 0.63, dict(fc=0.255, fr1=0.44, dn=0.03, tr=0.275, hl="rect", gr="blk")),
    "Golf Dvojka": ("hatch_boxy", 0.62, dict(tr=0.29)),
    "Kombi": ("van_cab", 0.54, dict(hl="round", gr="vee", nw=5, fc=0.15, fr1=0.22, pf=0.40, tr=0.33)),
    "Lada Niva": ("suv_box", 0.59, dict(fc=0.25, fr1=0.41, fr0=0.945, hl="round", gr="blk", nw=2, tr=0.35)),
    "Mercedes 190": ("notch_boxy", 0.60, dict(tr=0.315, dd=0.04)),
    "Taxi Zlatna Zolta": ("notch_boxy", 0.60, dict(tr=0.31)),
    "Fico": ("mini", 0.67, dict(hl="rect", tr=0.26)),
    "Zastava 101 Skala": ("hatch_boxy", 0.61, dict(fc=0.27, tr=0.285)),
    "Zastava Koral": ("hatch_boxy", 0.62, dict(fc=0.26, fr1=0.45, tr=0.275)),
    "Lada Samara": ("hatch_soft", 0.615, dict(dn=0.10, hl="rect", gr="blk", tr=0.285)),
    "Lada 1500": ("notch_boxy", 0.585, dict(fc=0.38, tr=0.285)),
    "Moskvich 412": ("notch_boxy", 0.57, dict(hl="round", gr="slats", tr=0.295)),
    "Trabant 601": ("mini", 0.56, dict(fc=0.225, fr1=0.40, fr0=0.83, fd=0.91, dn=0.05, tw=0.86, rnd=0.35, gr="none", tl="wide", tr=0.28)),
    "Wartburg 353": ("notch_boxy", 0.58, dict(fc=0.36, tr=0.29)),
    "Skoda Octavia Karavan": ("wagon", 0.556, dict(tr=0.31)),
    "Pachuvka 2CV": ("mini", 0.63, dict(fc=0.30, fr1=0.42, fr0=0.88, fd=0.965, dn=0.14, tw=0.74, hl="round", gr="slats", tr=0.29, gc=0.30)),
    "Renault 4 Katrca": ("hatch_boxy", 0.66, dict(fc=0.25, fr1=0.43, fr0=0.86, fd=0.975, dn=0.04, hl="round", gr="slats", tr=0.28)),
    "Fiat 126 Peglica": ("mini", 0.60, dict(fc=0.24, fr1=0.41, fr0=0.85, fd=0.95, dn=0.06, hl="rect", gr="none", tr=0.24)),
    "Fiat Punto": ("hatch_soft", 0.65, dict(tr=0.285)),
    "Fiat Uno": ("hatch_boxy", 0.65, dict(fc=0.28, fr1=0.45, dd=0.12, tr=0.28)),
    "Opel Kadett": ("hatch_boxy", 0.63, dict(dn=0.08, tr=0.29)),
    "Opel Astra Karavan": ("wagon", 0.57, dict(dn=0.12, tr=0.30)),
    "Audi 80 Bachok": ("notch_boxy", 0.585, dict(gr="blk", dn=0.07, tr=0.30)),
    "BMW E36 Bavarka": ("notch_soft", 0.61, dict(gr="kidney", hl="rect", tr=0.315)),
    "BMW X5 Chorbadzija": ("suv_soft", 0.60, dict(gr="kidney", tr=0.375)),
    "Mercedes 124 Taksist": ("notch_boxy", 0.59, dict(dn=0.09, tr=0.31)),
    "Mercedes S Mafijash": ("notch_soft", 0.59, dict(fc=0.37, dn=0.10, gr="chrome", tr=0.33, fd=0.855)),
    "Mercedes G Politichar": ("suv_box", 0.545, dict(fc=0.28, fr1=0.42, dn=0.0, dc=0.12, hl="round", gr="slats", tr=0.37, nw=2)),
    "Sprinter Gastarbajter": ("van_cab", 0.60, dict(fc=0.185, fr1=0.275, win="cab", pf=0.40, tr=0.345)),
    "Passat Dijaspora": ("notch_boxy", 0.57, dict(dn=0.09, gr="slim", hl="wrap", tr=0.30, tw=0.82)),
    "Golf Trojka Gastarbajter": ("hatch_soft", 0.615, dict(dn=0.10, tr=0.30)),
    "Caddy Dostava": ("van_cab", 0.61, dict(fc=0.25, fr1=0.37, win="cab", dn=0.08, tr=0.31)),
    "Transporter Kombe": ("van_cab", 0.60, dict(fc=0.21, fr1=0.31, nw=4, pf=0.42, tr=0.335)),
    "Renault Clio": ("hatch_soft", 0.65, dict(tr=0.29)),
    "Toyota Corolla": ("notch_soft", 0.59, dict(tr=0.30)),
    "Land Cruiser Lovec": ("suv_box", 0.58, dict(fc=0.30, fr1=0.47, dn=0.04, dc=0.12, tr=0.40, hl="rect", gr="chrome")),
    "Nissan Qashqai": ("suv_soft", 0.61, dict(tr=0.35)),
    "Dacia Duster": ("suv_soft", 0.62, dict(dn=0.12, tw=0.84, rnd=0.2, tr=0.35)),
    "Dacia Logan": ("notch_soft", 0.62, dict(fr0=0.76, fd=0.86, dn=0.11, tr=0.29, tw=0.83)),
    "Kia Picanto": ("mini", 0.66, dict(hl="wrap", gr="slim", tr=0.27, dn=0.12)),
    "Tesla Elon": ("notch_soft", 0.595, dict(fc=0.31, fr1=0.54, fr0=0.80, fd=0.945, dn=0.17, gr="none", hl="slit", tl="slim", tr=0.35, rnd=0.5)),
    "Hummer Patriot": ("suv_box", 0.65, dict(fc=0.32, fr1=0.45, fr0=0.945, dn=0.0, dc=0.16, hl="rect", gr="slats", tr=0.40, bp="body")),
    "Smart Sitnichka": ("mini", 0.69, dict(fc=0.22, fr1=0.38, fr0=0.86, fd=0.97, dn=0.10, hl="wrap", gr="slim", tr=0.26, pf=0.50, tw=0.82)),
    "Cayenne od Germanija": ("suv_soft", 0.60, dict(hl="round", tr=0.375, dn=0.12)),
    "Range Rover Ortak": ("suv_box", 0.60, dict(fc=0.31, fr1=0.46, fr0=0.945, dc=0.14, tr=0.38, hl="rect", gr="slats")),
    "Policiska Skoda": ("notch_soft", 0.59, dict(tr=0.31)),
    "Brza Pomosh": ("van_cab", 0.60, dict(fc=0.185, fr1=0.275, win="cab", pf=0.40, tr=0.345)),
    "Burek Dostava": ("van_cab", 0.60, dict(fc=0.20, fr1=0.30, win="cab", tr=0.31)),
    "Makedonska Posta": ("van_cab", 0.60, dict(fc=0.19, fr1=0.29, win="cab", tr=0.33)),
    "Svadbarska Limuzina": ("notch_soft", 0.67, dict(fc=0.27, fr1=0.42, fr0=0.78, fd=0.855, nw=4, fwe=0.50, tr=0.33, gr="chrome")),
    "Sladoled Kombe": ("van_cab", 0.60, dict(fc=0.20, fr1=0.30, win="cab", tr=0.31)),
    "Golf Petka TDI": ("hatch_soft", 0.615, dict(dn=0.15, tr=0.31)),
    "Golf Shestka Uvezen": ("hatch_soft", 0.615, dict(dn=0.17, tr=0.32, rnd=0.35, hl="slit")),
    "Passat B5 Karavan": ("wagon", 0.575, dict(tr=0.31)),
    "Passat B6 TDI": ("notch_soft", 0.57, dict(dn=0.16, tr=0.32, fd=0.855, hl="slit")),
    "Audi A4 Avant Shvajcarska": ("wagon", 0.58, dict(tr=0.32, gr="blk")),
    "Audi A6 Nemachka": ("notch_soft", 0.575, dict(tr=0.325, gr="blk", fd=0.85)),
    "BMW E46 Tjunirana": ("notch_soft", 0.60, dict(gr="kidney", tr=0.325)),
    "BMW E39 520d": ("notch_soft", 0.59, dict(gr="kidney", dn=0.11, tr=0.32)),
    "Mercedes C Klasa W203": ("notch_soft", 0.60, dict(gr="chrome", tr=0.32)),
    "Mercedes E Klasa W211": ("notch_soft", 0.59, dict(gr="chrome", tr=0.33, hl="slit")),
    "Opel Astra G": ("hatch_soft", 0.635, dict(tr=0.30)),
    "Opel Corsa C": ("hatch_soft", 0.65, dict(tr=0.285, dn=0.16)),
    "Opel Zafira Familijarna": ("mpv", 0.62, dict(tr=0.31)),
    "Renault Megane Scenic": ("mpv", 0.605, dict(fc=0.26, fr1=0.42, tr=0.31, hl="round")),
    "Peugeot 206": ("hatch_soft", 0.64, dict(tr=0.28)),
    "Peugeot 307 SW": ("wagon", 0.615, dict(fc=0.31, fr1=0.49, tr=0.31)),
    "Citroen Berlingo": ("mpv", 0.65, dict(fc=0.22, fr1=0.34, dn=0.04, tw=0.88, tr=0.30, gr="blk")),
    "Fiat Stilo": ("hatch_soft", 0.62, dict(tr=0.31)),
    "Fiat Multipla": ("mpv", 0.67, dict(fc=0.23, fr1=0.37, dn=0.02, tw=0.88, tr=0.30, hl="round")),
    "Skoda Fabia": ("hatch_soft", 0.62, dict(tr=0.29, dn=0.12)),
    "Skoda Octavia Taksi": ("notch_soft", 0.59, dict(tr=0.31)),
    "Seat Leon Kupra": ("hatch_soft", 0.60, dict(tr=0.325, dn=0.16)),
    "Hyundai Getz": ("hatch_soft", 0.645, dict(tr=0.28, fc=0.30, fr1=0.49)),
    "Toyota Yaris": ("hatch_soft", 0.655, dict(tr=0.285, fc=0.29, fr1=0.48, dn=0.12)),
    "Ford Focus Karavan": ("wagon", 0.585, dict(tr=0.31, hl="wrap", dn=0.15)),
    "Ford Transit Shverc": ("van_cab", 0.58, dict(fc=0.16, fr1=0.26, win="cab", pf=0.38, tr=0.345)),
    "Volvo V70 Dedov": ("wagon", 0.585, dict(dn=0.06, hl="rect", gr="chrome", tr=0.31, tw=0.84)),
    "Golf Chetvorka Bez Registracija": ("hatch_soft", 0.60, dict(dn=0.11, tr=0.30)),
    "Maritsa": ("van_cab", 0.60, dict(fc=0.19, fr1=0.28, win="cab", pf=0.40, tr=0.345)),
}


def has(name):
    return name in SPEC


_CACHE = {}


def spec(name, L):
    """Merged parameter dict plus derived x positions (m, front at +L/2) of one model."""
    if name in _CACHE and _CACHE[name][0] == L:
        return _CACHE[name][1]
    arch, wbr, ov = SPEC[name]
    s = dict(_BASE)
    s.update(ARCH[arch])
    s.update(ov)
    s["arch"], s["wb"] = arch, wbr * L
    fo = (L - s["wb"]) * s["pf"]
    s["ax_f"], s["ax_r"] = L / 2 - fo, L / 2 - fo - s["wb"]
    fc, fr1, fr0, fd = s["fc"], s["fr1"], s["fr0"], s["fd"]
    fw0 = fc + 0.30 * (fr1 - fc)
    pw = 0.11 / L
    if s["win"] == "cab":
        wins = [(fw0, fw0 + 0.80 / L)]
    else:
        fwe = fr0 + s["fwe"] * (fd - fr0)
        n = s["nw"]
        wl = (fwe - fw0 - pw * (n - 1)) / n
        wins = [(fw0 + k * (wl + pw), fw0 + k * (wl + pw) + wl) for k in range(n)]
    s["wins"] = wins
    s["seams"] = [fw0 - 0.10 / L, (wins[0][1] + wins[1][0]) / 2 if len(wins) > 1 else wins[0][1] + 0.05 / L, wins[min(1, len(wins) - 1)][1] + 0.06 / L]
    s["fw0"] = fw0
    _CACHE[name] = (L, s)
    return s


def layout(name, L):
    """What gl3d needs besides the mesh: roof centre / length, wheel axles, tyre radius, driver's door hinge and length."""
    s = spec(name, L)
    X = lambda f: L / 2 - f * L
    cx = (X(s["fr1"]) + X(s["fr0"])) / 2
    cl = X(s["fr1"]) - X(s["fr0"])
    hinge = X(s["seams"][0])
    return dict(cx=cx, cl=cl, ax_f=s["ax_f"], ax_r=s["ax_r"], tr=s["tr"], hinge=hinge, door=max(0.6, hinge - X(s["seams"][1])),
                mirror=X(s["fc"]) - 0.02)


def build(name, L, W, belt, roof, body_c, accent, two, shade, glass, tyre_r):
    """Returns the body parts [(verts, colours, deformable)] of one car."""
    s = spec(name, L)
    X = lambda f: L / 2 - f * L
    yb = s["gc"]
    fc, fr1, fr0, fd = s["fc"], s["fr1"], s["fr0"], s["fd"]
    hn, hc, hd = belt - s["dn"], belt + s["dc"], belt + s["dd"]
    ht = hd - s["dt"]
    knots_f = [0.0, fc * 0.5, fc, fr1, fr0, fd, 1.0]
    knots_y = [hn, hn + (hc - hn) * 0.62 + s["hood"], hc, roof, roof, hd, ht]
    fs = {0.0, 0.02, 0.06, 0.04, 0.96, 0.45, 0.55, 0.65, 0.7, 0.10, 0.14, 0.2, 0.25, 0.32, 0.5, 0.6, 0.68, 0.75, 0.8, 0.86, 0.9, 0.94, 0.98, 1.0, fc, fr1, fr0, fd, fc * 0.5, (fc + fr1) / 2}
    for a, b in s["wins"]:
        fs.update((a, b))
    fs = sorted(f for f in fs if 0.0 <= f <= 1.0)
    F = [fs[0]]
    for f in fs[1:]:
        if f - F[-1] > 0.004:
            F.append(f)
    F = np.array(F)
    S = len(F)
    P = np.zeros((S, 12, 3), np.float32)
    ty = np.interp(F, knots_f, knots_y)
    wins, seams = s["wins"], s["seams"]
    for i, f in enumerate(F):
        x = X(f)
        u = abs(x) / (L / 2)
        w = W / 2 * (1 - s["rnd"] * 0.16 * np.clip((u - 0.62) / 0.38, 0, 1) ** 2)
        t_ = ty[i]
        shy = min(belt, t_ - 0.06)
        gh = t_ - shy
        tg = float(np.clip((gh - 0.06) / 0.5, 0, 1))
        wt = w * (1 - (1 - s["tw"]) * tg) - (1 - tg) * 0.07
        rail = 0.07 + 0.09 * tg
        sy, sz = shy + 0.88 * gh, w - (w - wt) * 0.88
        L_ = [(yb, w - 0.07), (yb + 0.10, w), (shy, w), (sy, sz), (t_, wt), (t_ + 0.01, wt - rail)]
        for k, (y, z) in enumerate(L_):
            P[i, k] = (x, y, -z)
            P[i, 11 - k] = (x, y, z)
    # ---- quads between stations -> triangles with per-quad colours
    fm = (F[:-1] + F[1:]) / 2
    cols = np.zeros((S - 1, 11, 3), np.float32)
    body = np.array(body_c, np.float32)
    roofc = np.array(accent, np.float32) * 1.05 if two else np.clip(body * 1.08, 0, 255)
    gl = np.array(glass, np.float32)
    isglass = np.zeros((S - 1, 11), bool)
    for i in range(S - 1):
        m = fm[i]
        in_win = any(a - 1e-6 <= m <= b + 1e-6 for a, b in wins)
        gh = ty[i] - min(belt, ty[i] - 0.06)
        in_roof = fr1 <= m <= fr0
        for j in range(11):
            c = body
            if j in (0, 10):
                c = body * 0.55
            elif j in (2, 8):
                if in_win and gh > 0.12:
                    c, isglass[i, j] = gl, True
            elif j in (4, 6):
                c = roofc if in_roof else body
            elif j == 5:
                if gh > 0.15 and fc - 1e-6 <= m <= fr1 + 1e-6:
                    c, isglass[i, j] = gl, True
                elif gh > 0.15 and s["win"] == "all" and fr0 - 1e-6 <= m <= fd + 1e-6:
                    c, isglass[i, j] = gl, True
                elif in_roof:
                    c = roofc
            cols[i, j] = c
    a, b, c, d = P[:-1, :-1], P[:-1, 1:], P[1:, 1:], P[1:, :-1]
    verts = np.stack((a, b, c, a, c, d), axis=2).reshape(-1, 3)
    tcol = np.repeat(cols.reshape(-1, 3), 6, axis=0)
    gmask = np.repeat(isglass.reshape(-1), 6)
    out_v, out_c = _shaded(verts, tcol, gmask, yb, belt, shade)
    parts = [(out_v, out_c, True)]
    # ---- front and rear caps (fans around the section centre)
    for i, sgn in ((0, 1), (S - 1, -1)):
        sec = P[i]
        ctr = sec.mean(0)
        tri = np.stack([np.stack((ctr, sec[k], sec[(k + 1) % 12])) for k in range(12)]).reshape(-1, 3)
        cv, cc = _shaded(tri, np.tile(body, (len(tri), 1)), np.zeros(len(tri), bool), yb, belt, shade)
        parts.append((cv, cc, True))
    A = lambda c: np.array(c, np.float32)

    def quad(o, du, dv, n, col):
        v = np.array([o, np.add(o, du), np.add(np.add(o, du), dv), o, np.add(np.add(o, du), dv), np.add(o, dv)], np.float32)
        parts.append((v, np.tile(A(col) * shade(A(n)), (6, 1)), True))

    def box(cx_, cy_, cz_, sx, sy, sz, col):
        from gl3d import box_faces
        for _n, (v, n) in box_faces(cx_, cy_, cz_, sx, sy, sz).items():
            parts.append((v, np.tile(A(col) * shade(A(n)), (len(v), 1)), True))

    xf, xb = L / 2, -L / 2
    capw = P[0, 11, 2]
    capwr = P[S - 1, 11, 2]
    # ---- bumpers
    bpc = {"chrome": (150, 152, 158), "black": (38, 38, 42), "body": tuple(body * 0.95)}[s["bp"]]
    bh = 0.20
    box(xf - 0.02, yb + 0.06, 0, 0.12, bh, 2 * capw + 0.02, bpc)
    box(xb + 0.02, yb + 0.06, 0, 0.12, bh, 2 * capwr + 0.02, bpc)
    # ---- front face: lamps and grille
    ltop = hn - 0.05
    xl = xf + 0.006
    hl = s["hl"]
    lw, lh = {"round": (0.22, 0.22), "rect": (0.34, 0.15), "wrap": (0.46, 0.15), "slit": (0.52, 0.09)}[hl]
    lh = min(lh, ltop - (yb + 0.32))
    zo = capw - 0.05
    for sd in (-1, 1):
        zi = zo - lw
        lo, hi = sorted((sd * zo, sd * zi))
        if hl == "round":
            quad((xl, ltop - lh - 0.02, lo - 0.015), (0, 0, hi - lo + 0.03), (0, lh + 0.04, 0), (1, 0, 0), (196, 198, 204))
        quad((xl + 0.004, ltop - lh, lo), (0, 0, hi - lo), (0, lh, 0), (1, 0, 0), (255, 244, 186))
        if hl == "wrap":
            quad((xl - 0.001, ltop - lh, sd * (capw + 0.002)), (-0.12, 0, 0), (0, lh, 0), (0, 0, sd), (255, 244, 186))
    gz = zo - lw - 0.03
    g = s["gr"]
    gy0, gy1 = yb + 0.28, ltop - 0.01
    if g in ("blk", "slim", "chrome", "slats", "vee") and gz > 0.1:
        gz = gz if g != "slim" else min(gz, 0.5)
        gc_ = (28, 28, 32)
        if g == "chrome":
            quad((xl, gy0 - 0.03, -gz - 0.03), (0, 0, 2 * gz + 0.06), (0, gy1 - gy0 + 0.06, 0), (1, 0, 0), (200, 202, 208))
        if g in ("slim", "blk"):
            gy0 = max(gy0, ltop - (0.14 if g == "slim" else 0.2))
        quad((xl + 0.002, gy0, -gz), (0, 0, 2 * gz), (0, gy1 - gy0, 0), (1, 0, 0), gc_)
        if g == "slats":
            for k in range(1, 6):
                zk = -gz + k * 2 * gz / 6
                quad((xl + 0.004, gy0, zk - 0.012), (0, 0, 0.024), (0, gy1 - gy0, 0), (1, 0, 0), (150, 152, 158))
        if g == "vee":
            quad((xl + 0.004, gy0 + 0.05, -0.03), (0, 0, 0.06), (0, 0.4, 0), (1, 0, 0), (214, 214, 218))
    elif g == "kidney":
        for sd in (-1, 1):
            quad((xl + 0.002, gy0 + 0.02, sd * 0.2 - 0.17 * (sd < 0) - 0.0), (0, 0, 0.17), (0, gy1 - gy0 - 0.02, 0), (1, 0, 0), (196, 198, 204))
            quad((xl + 0.004, gy0 + 0.04, sd * 0.2 - 0.15 * (sd < 0) + 0.01 * (sd < 0)), (0, 0, 0.13), (0, gy1 - gy0 - 0.06, 0), (1, 0, 0), (26, 26, 30))
    quad((xl + 0.002, yb + 0.07, -0.25), (0, 0, 0.5), (0, 0.12, 0), (1, 0, 0), (236, 236, 230))
    # ---- tail: lamps and plate
    xt = xb - 0.006
    ttop = ht - 0.04
    tl = s["tl"]
    zt = capwr - 0.05
    for sd in (-1, 1):
        if tl == "tall":
            hh = min(0.42, ttop - yb - 0.3)
            lo, hi = sorted((sd * zt, sd * (zt - 0.14)))
            quad((xt, ttop - hh, lo), (0, 0, hi - lo), (0, hh, 0), (-1, 0, 0), (214, 30, 30))
        elif tl == "slim":
            lo, hi = sorted((sd * zt, sd * (zt - 0.5)))
            quad((xt, ttop - 0.08, lo), (0, 0, hi - lo), (0, 0.08, 0), (-1, 0, 0), (214, 30, 30))
        else:
            lo, hi = sorted((sd * zt, sd * (zt - 0.36)))
            quad((xt, ttop - 0.14, lo), (0, 0, hi - lo), (0, 0.14, 0), (-1, 0, 0), (214, 30, 30))
    quad((xt - 0.002, yb + 0.12, 0.25), (0, 0, -0.5), (0, 0.12, 0), (-1, 0, 0), (236, 236, 230))
    # ---- doors, handles, mirrors, wheel arches
    wr = tyre_r
    for sd in (-1, 1):
        zs = sd * (W / 2 + 0.008)
        for fx in seams:
            quad((X(fx), yb + 0.14, zs), (0.025, 0, 0), (0, belt - yb - 0.2, 0), (0, 0, sd), tuple(body * 0.5))
        for fx in seams[:2]:
            quad((X(fx) - 0.30, belt - 0.14, zs + sd * 0.004), (0.16, 0, 0), (0, 0.035, 0), (0, 0, sd), (40, 40, 44))
        for ax in (s["ax_f"], s["ax_r"]):
            ah = max(0.2, 2 * wr - yb + 0.06)
            quad((ax - wr - 0.07, yb, zs + sd * 0.002), (2 * wr + 0.14, 0, 0), (0, ah, 0), (0, 0, sd), (20, 20, 22))
        box(X(fc) - 0.02, belt + 0.12, sd * (W / 2 + 0.08), 0.1, 0.1, 0.16, (40, 40, 44))
        box(X(fc) - 0.02, belt + 0.14, sd * (W / 2 + 0.01), 0.05, 0.05, 0.08, (60, 60, 64))
        for fx in seams[:2]:
            quad((X(fx) - 0.26, belt - 0.2, zs + sd * 0.006), (0.12, 0, 0), (0, 0.025, 0), (0, 0, sd), (200, 200, 205))
        quad((X(fc) - 0.2, belt - 0.04, zs + sd * 0.003), (0.5, 0, 0), (0, 0.02, 0), (0, 0, sd), tuple(body * 0.7))
        quad((xb + 0.05, yb - 0.01, zs), (L - 0.1, 0, 0), (0, 0.07, 0), (0, 0, sd), (40, 40, 42))
    return parts


def _shaded(verts, tcol, gmask, yb, belt, shade):
    """Per-triangle outward normal -> lit vertex colours (body gets the same darker-underneath gradient as the old model)."""
    tri = verts.reshape(-1, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1)
    keep = ln > 1e-7
    n = n / np.where(keep, ln, 1)[:, None]
    cen = tri.mean(1)
    flip = ((cen - np.array((0, yb + 0.35, 0), np.float32)) * n).sum(1) < 0
    n[flip] *= -1
    sh = 0.52 + 0.55 * np.clip(n @ _sun(), 0, None)
    c = tcol.reshape(-1, 3, 3) * sh[:, None, None]
    g = np.clip(0.72 + 0.4 * (tri[:, :, 1] - yb) / max(0.1, belt - yb), 0.6, 1.1)
    gm = gmask.reshape(-1, 3)
    g = np.where(gm, 0.9, g)
    c = c * g[:, :, None]
    keepv = np.repeat(keep, 3)
    return verts[keepv].astype(np.float32), c.reshape(-1, 3)[keepv].astype(np.float32)


def _sun():
    """The sun vector behind gl3d._shade: shade(n) = 0.52 + 0.55 max(0, n.SUN)."""
    import gl3d
    return gl3d.SUN
