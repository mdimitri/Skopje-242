"""Profile-lofted car bodies: a real side profile (nose, bonnet, windscreen, roof, rear glass / tailgate, deck), real wheelbase and
per-model face details, instead of one generic box-plus-cabin.  Pure numpy; gl3d.car_arrays calls build() for the car-like styles.

Positions are fractions f of the body length measured from the FRONT (f=0 nose, f=1 tail); heights are metres.
"""
import numpy as np

LOFT_STYLES = ("hatch", "sedan", "taxi", "mini", "wagon", "suv", "van", "limo", "pickup")

# profile knots: fc cowl (bonnet end / windscreen foot), fr1 roof front, fr0 roof rear, fd rear-glass foot (deck start);
# dn nose top below the belt, dc cowl above the belt, dd deck above the belt, dt tail top below the deck; tw roof width / body width;
# rnd plan rounding; gc ground clearance; hl head lamp kind, gr grille kind, tl tail lamp kind, bp bumper kind; win side glass; nw windows
_BASE = dict(dn=0.08, dc=0.03, dd=0.0, dt=0.0, tw=0.82, rnd=0.3, gc=0.24, hl="rect", gr="blk", tl="wide", bp="black", win="all", nw=2,
             pf=0.46, fwe=0.45, tr=None, hood=0.0, nrF=0.08, nrR=0.05)
ARCH = {
    "hatch_boxy": dict(nrF=0.04, nrR=0.02, fc=0.30, fr1=0.475, fr0=0.835, fd=0.965, dn=0.05, dd=0.10, dt=0.05, tw=0.84, rnd=0.12, tl="tall", fwe=0.30, bp="chrome"),
    "hatch_soft": dict(nrF=0.17, nrR=0.07, fc=0.315, fr1=0.51, fr0=0.82, fd=0.955, dn=0.15, dc=0.04, dd=0.08, dt=0.06, tw=0.80, rnd=0.45, hl="wrap",
                       gr="slim", tl="tall", fwe=0.30),
    "mini": dict(nrF=0.09, nrR=0.09, fc=0.255, fr1=0.42, fr0=0.82, fd=0.955, dn=0.10, dc=0.05, dd=0.06, dt=0.08, tw=0.80, rnd=0.6, hl="round", tl="tall", fwe=0.30),
    "notch_boxy": dict(nrF=0.05, nrR=0.04, fc=0.375, fr1=0.545, fr0=0.745, fd=0.83, dn=0.05, dc=0.02, dd=0.0, dt=0.0, tw=0.85, rnd=0.12, gr="chrome",
                       tl="wide", bp="chrome", fwe=0.45),
    "notch_soft": dict(nrF=0.16, nrR=0.10, fc=0.36, fr1=0.545, fr0=0.75, fd=0.84, dn=0.14, dc=0.03, dd=-0.02, dt=0.0, tw=0.79, rnd=0.4, hl="wrap",
                       gr="slim", tl="wide", fwe=0.45),
    "wagon": dict(nrF=0.13, nrR=0.03, fc=0.335, fr1=0.51, fr0=0.935, fd=0.985, dn=0.10, dc=0.03, dd=0.12, dt=0.06, tw=0.82, rnd=0.3, hl="wrap",
                  gr="slim", tl="tall", nw=3, fwe=0.30),
    "suv_box": dict(nrF=0.03, nrR=0.02, fc=0.27, fr1=0.43, fr0=0.94, fd=0.985, dn=0.02, dc=0.10, dd=0.14, dt=0.0, tw=0.88, rnd=0.1, gc=0.30, hl="round",
                    gr="slats", tl="tall", nw=3, fwe=0.30, bp="black"),
    "suv_soft": dict(nrF=0.13, nrR=0.06, fc=0.33, fr1=0.515, fr0=0.915, fd=0.975, dn=0.10, dc=0.06, dd=0.14, dt=0.05, tw=0.80, rnd=0.35, gc=0.28, hl="wrap",
                     gr="slim", tl="tall", nw=3, fwe=0.30),
    "van_cab": dict(nrF=0.03, nrR=0.02, fc=0.17, fr1=0.27, fr0=0.985, fd=0.995, dn=0.0, dc=0.0, dd=0.0, dt=0.0, tw=0.94, rnd=0.12, gc=0.28, hl="rect",
                    gr="blk", tl="tall", nw=4, fwe=0.30, bp="black"),
    "pickup": dict(fc=0.235, fr1=0.335, fr0=0.50, fd=0.525, dn=0.10, dc=0.06, dd=-0.02, dt=0.0, tw=0.86, rnd=0.2, gc=0.32, hl="rect", gr="slats",
                   tl="wide", nw=1, fwe=0.5, bp="chrome", nrF=0.05, nrR=0.0, win="all"),
    "mpv": dict(nrF=0.12, nrR=0.04, fc=0.27, fr1=0.43, fr0=0.935, fd=0.975, dn=0.10, dc=0.05, dd=0.14, dt=0.03, tw=0.84, rnd=0.35, hl="wrap", gr="slim",
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
    "Pikap Tovarnik": ("pickup", 0.60, dict(tr=0.37)),
    "Pajak Vlechna Sluzhba": ("pickup", 0.58, dict(tr=0.37, fc=0.25, fr1=0.35, fr0=0.52, fd=0.545)),
    "Maritsa": ("van_cab", 0.60, dict(fc=0.19, fr1=0.28, win="cab", pf=0.40, tr=0.345)),
}


# badge colour by make (first match of the model name's start / contents): a small disc on the grille, the way each make is told apart
_BADGE = (("Zastava", (200, 30, 30)), ("Golf", (30, 70, 160)), ("Passat", (30, 70, 160)), ("Caddy", (30, 70, 160)),
          ("Transporter", (30, 70, 160)), ("Kombi", (30, 70, 160)), ("Mercedes", (205, 208, 214)), ("Sprinter", (205, 208, 214)),
          ("Maritsa", (205, 208, 214)), ("Taxi", (205, 208, 214)), ("BMW", (40, 90, 200)), ("Audi", (205, 208, 214)),
          ("Opel", (240, 200, 30)), ("Renault", (230, 200, 40)), ("Peugeot", (190, 192, 200)), ("Citroen", (200, 40, 40)),
          ("Fiat", (200, 30, 30)), ("Fico", (200, 30, 30)), ("Toyota", (205, 208, 214)), ("Skoda", (40, 150, 70)),
          ("Policiska", (40, 150, 70)), ("Ford", (30, 70, 160)), ("Dacia", (205, 208, 214)), ("Kia", (200, 30, 30)),
          ("Hyundai", (205, 208, 214)), ("Nissan", (205, 208, 214)), ("Seat", (200, 30, 30)), ("Volvo", (30, 70, 160)),
          ("Lada", (210, 170, 40)), ("Moskvich", (200, 30, 30)), ("Trabant", (40, 150, 70)), ("Wartburg", (200, 30, 30)),
          ("Tesla", (205, 208, 214)), ("Hummer", (205, 208, 214)), ("Cayenne", (220, 180, 60)), ("Range", (40, 120, 70)),
          ("Land Cruiser", (200, 30, 30)), ("Smart", (230, 200, 40)), ("Pachuvka", (205, 208, 214)), ("Renault 4", (230, 200, 40)))
_SPARE = ("Mercedes G Politichar", "Hummer Patriot", "Land Cruiser Lovec")
_BULLBAR = ("Land Cruiser Lovec", "Hummer Patriot")
_ALLOY = ("BMW E46 Tjunirana", "Golf Shestka Uvezen", "Seat Leon Kupra", "Tesla Elon", "BMW X5 Chorbadzija", "Cayenne od Germanija",
          "Mercedes S Mafijash", "Audi A6 Nemachka", "Mercedes E Klasa W211", "Passat B6 TDI", "Range Rover Ortak", "BMW E39 520d")


def _rim(name, s):
    """(spokes, dark share, hub radius share) of a model's wheel face: pressed-steel hubcaps on the old and plain ones (subtle), 5-spoke
    alloys on 90s-2000s cars, 7-spoke on the premium and tuned ones, 6 on SUVs and pickups."""
    a = s["arch"]
    if name in _ALLOY:
        return (7, 0.45, 0.80)
    if a in ("suv_box", "suv_soft", "pickup"):
        return (6, 0.55, 0.74)
    if a in ("hatch_boxy", "notch_boxy", "mini", "van_cab"):
        return (4, 0.80, 0.66)
    return (5, 0.50, 0.76)


def badge(name):
    for k, c in _BADGE:
        if name.startswith(k) or k in name:
            return c
    return None


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
    return dict(hub=(212, 214, 220) if name in _ALLOY else (150, 152, 158), rim=_rim(name, s), cx=cx, cl=cl, ax_f=s["ax_f"], ax_r=s["ax_r"], tr=s["tr"], hinge=hinge, door=max(0.6, hinge - X(s["seams"][1])),
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
        rf = max(0.0, 1 - f * L / 0.55) * s["nrF"]                      # the nose / tail face leans back towards the top
        rr = max(0.0, 1 - (1 - f) * L / 0.55) * s["nrR"]
        for k, (y, z) in enumerate(L_):
            tt = float(np.clip((y - yb - 0.2) / max(0.1, t_ - yb - 0.2), 0, 1))
            xk = x - rf * tt + rr * tt
            P[i, k] = (xk, y, -z)
            P[i, 11 - k] = (xk, y, z)
    # ---- quads between stations -> triangles with per-quad colours
    fm = (F[:-1] + F[1:]) / 2
    cols = np.zeros((S - 1, 11, 3), np.float32)
    body = np.array(body_c, np.float32)
    if name == "Kombi":                                              # the T2/T3 bus: white roof and upper band over the body colour
        two, accent = True, (236, 236, 240)
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
                elif name == "Kombi" and gh > 0.12:
                    c = roofc
            elif j in (4, 6):
                c = roofc if (in_roof or name == "Kombi") else body
            elif j in (3, 7) and name == "Kombi":
                c = roofc
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
    tfr = lambda y: float(np.clip((y - yb - 0.2) / max(0.1, hn - yb - 0.2), 0, 1))     # how far back the nose face has leaned at height y
    fxf = lambda y: xf - s["nrF"] * tfr(y)                                                # the nose face's x at height y
    tfb = lambda y: float(np.clip((y - yb - 0.2) / max(0.1, ht - yb - 0.2), 0, 1))
    fxr = lambda y: xb + s["nrR"] * tfb(y)                                                # the tail face's x at height y

    def fq(y0_, h_, z0_, dz_, col, off=0.006):                                            # a quad lying on the (leaning) nose face
        quad((fxf(y0_) + off, y0_, z0_), (0, 0, dz_), (fxf(y0_ + h_) - fxf(y0_), h_, 0), (1, 0, 0), col)

    def rq(y0_, h_, z0_, dz_, col, off=0.006):
        quad((fxr(y0_) - off, y0_, z0_), (0, 0, dz_), (fxr(y0_ + h_) - fxr(y0_), h_, 0), (-1, 0, 0), col)
    hl = s["hl"]
    lw, lh = {"round": (0.22, 0.22), "rect": (0.34, 0.15), "wrap": (0.46, 0.15), "slit": (0.52, 0.09)}[hl]
    lh = min(lh, ltop - (yb + 0.32))
    zo = capw - 0.05
    for sd in (-1, 1):
        zi = zo - lw
        lo, hi = sorted((sd * zo, sd * zi))
        if hl == "round":
            fq(ltop - lh - 0.02, lh + 0.04, lo - 0.015, hi - lo + 0.03, (196, 198, 204), 0.0)
        fq(ltop - lh, lh, lo, hi - lo, (255, 244, 186), 0.004)
        if hl == "wrap":
            quad((fxf(ltop - lh) - 0.001, ltop - lh, sd * (capw + 0.002)), (-0.12, 0, 0), (0, lh, 0), (0, 0, sd), (255, 244, 186))
    gz = zo - lw - 0.03
    g = s["gr"]
    gy0, gy1 = yb + 0.28, ltop - 0.01
    if g in ("blk", "slim", "chrome", "slats", "vee") and gz > 0.1:
        gz = gz if g != "slim" else min(gz, 0.5)
        gc_ = (28, 28, 32)
        if g == "chrome":
            fq(gy0 - 0.03, gy1 - gy0 + 0.06, -gz - 0.03, 2 * gz + 0.06, (200, 202, 208), 0.0)
        if g in ("slim", "blk"):
            gy0 = max(gy0, ltop - (0.14 if g == "slim" else 0.2))
        fq(gy0, gy1 - gy0, -gz, 2 * gz, gc_, 0.002)
        if g == "slats":
            for k in range(1, 6):
                zk = -gz + k * 2 * gz / 6
                fq(gy0, gy1 - gy0, zk - 0.012, 0.024, (150, 152, 158), 0.004)
        if g == "vee":
            fq(gy0 + 0.05, 0.4, -0.03, 0.06, (214, 214, 218), 0.004)
    elif g == "kidney":
        for sd in (-1, 1):
            fq(gy0 + 0.02, gy1 - gy0 - 0.02, sd * 0.2 - 0.17 * (sd < 0), 0.17, (196, 198, 204), 0.002)
            fq(gy0 + 0.04, gy1 - gy0 - 0.06, sd * 0.2 - 0.14 * (sd < 0), 0.13, (26, 26, 30), 0.004)
    fq(yb + 0.07, 0.12, -0.25, 0.5, (236, 236, 230), 0.002)
    # ---- tail: lamps and plate
    ttop = ht - 0.04
    tl = s["tl"]
    zt = capwr - 0.05
    for sd in (-1, 1):
        if tl == "tall":
            hh = min(0.42, ttop - yb - 0.3)
            lo, hi = sorted((sd * zt, sd * (zt - 0.14)))
            rq(ttop - hh, hh, lo, hi - lo, (214, 30, 30))
        elif tl == "slim":
            lo, hi = sorted((sd * zt, sd * (zt - 0.5)))
            rq(ttop - 0.08, 0.08, lo, hi - lo, (214, 30, 30))
        else:
            lo, hi = sorted((sd * zt, sd * (zt - 0.36)))
            rq(ttop - 0.14, 0.14, lo, hi - lo, (214, 30, 30))
    rq(yb + 0.12, 0.12, 0.25, -0.5, (236, 236, 230), 0.002)
    if s["arch"] == "pickup":                                        # the open load bed behind the cab: floor is the deck, walls round it
        bx0 = X(fd) - 0.02
        bc2 = tuple(body * 0.95)
        quad((xb + 0.05, hd + 0.004, -W / 2 + 0.06), (bx0 - xb - 0.05, 0, 0), (0, 0, W - 0.12), (0, 1, 0), (46, 44, 42))
        for sd in (-1, 1):
            box((xb + bx0) / 2, hd, sd * (W / 2 - 0.05), bx0 - xb, 0.30, 0.08, bc2)
        box(xb + 0.05, hd, 0, 0.08, 0.30, W - 0.1, bc2)
        box(bx0 - 0.05, hd, 0, 0.08, 0.34, W - 0.1, tuple(body * 0.9))
    # ---- make badges, spare wheel, bull bar
    def disc(x_, y_, z_, r_, col, sgn):
        pts = [(x_, y_ + r_ * np.sin(a), z_ + r_ * np.cos(a)) for a in np.linspace(0, 2 * np.pi, 7)]
        v = np.array([q for k in range(6) for q in ((x_, y_, z_), pts[k], pts[k + 1])], np.float32)
        parts.append((v, np.tile(A(col) * shade(A((sgn, 0, 0))), (len(v), 1)), True))

    bcol = badge(name)
    if bcol is not None and g != "none":
        by = (gy0 + gy1) / 2 if g in ("blk", "slim", "chrome", "slats", "vee") else ltop - 0.1
        disc(fxf(by) + 0.012, by, 0.0, 0.05 if W < 1.9 else 0.06, bcol, 1)
        disc(fxr(ttop - 0.1) - 0.01, ttop - 0.1, 0.0, 0.035, bcol, -1)
    if name in _SPARE:
        rcy = yb + (ht - yb) * 0.48
        box(xb - 0.13, rcy - 0.33, 0, 0.26, 0.66, 0.66, (26, 26, 28))
        quad((xb - 0.262, rcy - 0.17, -0.17), (0, 0, 0.34), (0, 0.34, 0), (-1, 0, 0), (150, 152, 158))
    if name in _BULLBAR:
        box(xf + 0.12, yb + 0.28, 0, 0.07, 0.07, 2 * capw - 0.3, (190, 192, 198))
        for sd in (-1, 1):
            box(xf + 0.12, yb + 0.12, sd * (capw - 0.35), 0.07, 0.42, 0.06, (190, 192, 198))
    # ---- doors, handles, mirrors, wheel arches
    wr = tyre_r
    for sd in (-1, 1):
        zs = sd * (W / 2 + 0.008)
        sm = [seams[0], seams[1]] + ([seams[2]] if len(wins) > 1 else [])
        for fx in sm:                                                    # door shut lines from the sill to the shoulder
            quad((X(fx), yb + 0.14, zs), (0.025, 0, 0), (0, belt - yb - 0.2, 0), (0, 0, sd), tuple(body * 0.5))
        for fx in sm[1:]:                                                # handles sit at the rear edge of each door
            quad((X(fx) + 0.10, belt - 0.14, zs + sd * 0.004), (0.15, 0, 0), (0, 0.03, 0), (0, 0, sd), (200, 200, 205))
        for ax in (s["ax_f"], s["ax_r"]):
            ah = max(0.2, 2 * wr - yb + 0.06)
            quad((ax - wr - 0.07, yb, zs + sd * 0.002), (2 * wr + 0.14, 0, 0), (0, ah, 0), (0, 0, sd), (20, 20, 22))
        mxm = X(s["fw0"]) + 0.12                                         # mirror on the door's front corner, on a short stalk
        box(mxm, belt + 0.14, sd * (W / 2 + 0.05), 0.09, 0.11, 0.12, (40, 40, 44))
        box(mxm, belt + 0.12, sd * (W / 2 + 0.01), 0.04, 0.04, 0.06, (60, 60, 64))
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
