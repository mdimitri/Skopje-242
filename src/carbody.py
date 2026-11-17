"""Profile-lofted car bodies: a real side profile (nose, bonnet, windscreen, roof, rear glass / tailgate, deck), real wheelbase and
per-model face details, instead of one generic box-plus-cabin.  Pure numpy; gl3d.car_arrays calls build() for the car-like styles.

Positions are fractions f of the body length measured from the FRONT (f=0 nose, f=1 tail); heights are metres.
"""
import math

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
    "Zastava Yugo": ("hatch_boxy", 0.63, dict(fc=0.255, fr1=0.44, dn=0.03, tr=0.275, hl="rect", gr="blk", fr0=0.792, fd=0.969, pf=0.47, bp="black", tl="wide", rnd=0.29)),
    "Golf Dvojka": ("hatch_boxy", 2.475 / 3.985, dict(tr=0.286, pf=0.475, fc=0.302, fr1=0.465, fr0=0.812, fd=0.982, dn=0.07, dd=0.05, dt=0.03, tw=0.83, rnd=0.39, gc=0.225, nrF=0.025, nrR=0.015)),
    "Kombi": ("van_cab", 0.54, dict(hl="round", gr="vee", nw=5, fc=0.15, fr1=0.22, pf=0.40, tr=0.33, bp="black", rnd=0.32, nrF=0.06, tl="wide")),
    "Lada Niva": ("suv_box", 0.59, dict(fc=0.25, fr1=0.41, fr0=0.884, hl="round", gr="blk", nw=2, tr=0.35, fd=0.976, nrR=0.09, tl="tall", bp="black")),
    "Mercedes 190": ("notch_boxy", 2.665 / 4.420, dict(tr=0.304, pf=0.475, fc=0.369, fr1=0.512, fr0=0.696, fd=0.831, dn=0.06, dd=0.05, dt=0.03, tw=0.81, rnd=0.39, gc=0.223, nrF=0.025, nrR=0.025)),
    "Taxi Zlatna Zolta": ("notch_boxy", 0.60, dict(tr=0.31)),
    "Fico": ("mini", 0.67, dict(hl="round", tr=0.26, gr="none", fr0=0.706, fd=0.935, dt=0.16, dn=0.14, tw=0.77, rnd=0.76)),
    "Zastava 101 Skala": ("hatch_boxy", 0.61, dict(fc=0.27, tr=0.285, fr0=0.773, fd=0.949, hl="round", tl="wide", bp="black", gr="slats")),
    "Zastava Koral": ("hatch_boxy", 0.62, dict(fc=0.26, fr1=0.45, tr=0.275, fr0=0.793, fd=0.969, pf=0.47, bp="body", tl="wide", rnd=0.40)),
    "Lada Samara": ("hatch_soft", 0.615, dict(dn=0.10, hl="rect", gr="blk", tr=0.285, fc=0.35, fr1=0.50, fr0=0.784, fd=0.952, dd=0.042, rnd=0.33)),
    "Lada 1500": ("notch_boxy", 0.585, dict(fc=0.40, tr=0.285, fr0=0.702, fd=0.834, hl="round", gr="chrome", tl="wide")),
    "Moskvich 412": ("notch_boxy", 0.57, dict(hl="round", gr="slats", tr=0.295, fr1=0.50, fr0=0.707, fd=0.83, rnd=0.21)),
    "Trabant 601": ("mini", 0.56, dict(fc=0.225, fr1=0.40, fr0=0.711, fd=0.857, dn=0.05, tw=0.86, rnd=0.35, gr="none", tl="tall", tr=0.28, bp="body", dd=-0.03)),
    "Wartburg 353": ("notch_boxy", 0.58, dict(fc=0.36, tr=0.29, fr1=0.48, fr0=0.716, fd=0.805, gr="slats", tl="wide", rnd=0.18)),
    "Skoda Octavia Karavan": ("wagon", 0.556, dict(tr=0.31, fr1=0.489, fr0=0.896, gr="chrome", bp="body", tl="tall")),
    "Pachuvka 2CV": ("mini", 0.63, dict(fc=0.30, fr1=0.42, fr0=0.675, fd=0.931, dn=0.14, tw=0.69, hl="round", gr="slats", tr=0.29, gc=0.30, dt=0.17, nrR=0.06)),
    "Renault 4 Katrca": ("hatch_boxy", 0.66, dict(fc=0.25, fr1=0.43, fr0=0.885, fd=0.974, dn=0.04, hl="round", gr="slats", tr=0.28, tw=0.83, tl="tall", bp="black")),
    "Fiat 126 Peglica": ("mini", 0.60, dict(fc=0.24, fr1=0.41, fr0=0.707, fd=0.897, dn=0.06, hl="rect", gr="none", tr=0.24, tl="wide", bp="black", dd=0.052)),
    "Fiat Punto": ("hatch_soft", 0.65, dict(tr=0.285, fc=0.31, fr1=0.47, fr0=0.811, tl="tall", bp="body", hl="slit")),
    "Fiat Uno": ("hatch_boxy", 0.65, dict(fc=0.26, fr1=0.43, dd=0.12, tr=0.28, fr0=0.850, tl="tall", bp="black", gr="slim")),
    "Opel Kadett": ("hatch_boxy", 0.63, dict(dn=0.08, tr=0.29, fr1=0.46, fr0=0.786, fd=0.970, tl="wide", bp="black", rnd=0.33)),
    "Opel Astra Karavan": ("wagon", 0.57, dict(dn=0.12, tr=0.30, fr0=0.90, fd=0.988, bp="body", tl="wide")),
    "Audi 80 Bachok": ("notch_boxy", 0.585, dict(gr="blk", dn=0.07, tr=0.30, fr1=0.517, fr0=0.738, fd=0.868, bp="body", tl="wide", hl="wrap", rnd=0.43)),
    "BMW E36 Bavarka": ("notch_soft", 2.700 / 4.433, dict(tr=0.309, pf=0.41, fc=0.366, fr1=0.535, fr0=0.708, fd=0.872, dn=0.10, dd=0.02, dt=0.035, tw=0.79, rnd=0.57, gc=0.215, nrF=0.048, nrR=0.038)),
    "BMW X5 Chorbadzija": ("suv_soft", 0.60, dict(gr="kidney", tr=0.375, fc=0.36, fr1=0.507, fr0=0.879, fd=0.978, bp="body", tl="wide")),
    "Mercedes 124 Taksist": ("notch_boxy", 0.59, dict(dn=0.09, tr=0.31, fr1=0.511, fr0=0.728, fd=0.841, bp="body", tl="wide")),
    "Mercedes S Mafijash": ("notch_soft", 0.59, dict(fc=0.398, dn=0.10, gr="chrome", tr=0.33, fd=0.856, fr1=0.542, fr0=0.719, bp="body", tl="slim")),
    "Mercedes G Politichar": ("suv_box", 0.545, dict(fc=0.28, fr1=0.42, dn=0.0, dc=0.12, hl="round", gr="slats", tr=0.37, nw=2, fr0=0.940, fd=0.98, rnd=0.10, tl="wide")),
    "Sprinter Gastarbajter": ("van_cab", 0.60, dict(fc=0.185, fr1=0.275, win="cab", pf=0.40, tr=0.345)),
    "Passat Dijaspora": ("notch_boxy", 0.57, dict(dn=0.09, gr="none", hl="wrap", tr=0.30, tw=0.82, fr1=0.518, fr0=0.727, fd=0.847, bp="body")),
    "Golf Trojka Gastarbajter": ("hatch_soft", 0.615, dict(dn=0.10, tr=0.30, fr1=0.47, fr0=0.817, fd=0.962, hl="rect", tl="wide", bp="black")),
    "Caddy Dostava": ("van_cab", 0.61, dict(fc=0.285, fr1=0.43, win="cab", dn=0.08, tr=0.31, fr0=0.964, hl="wrap", bp="body")),
    "Transporter Kombe": ("van_cab", 0.60, dict(fc=0.204, fr1=0.328, nw=4, pf=0.42, tr=0.335, fr0=0.963, hl="rect", bp="body")),
    "Renault Clio": ("hatch_soft", 0.65, dict(tr=0.29, fc=0.267, fr1=0.474, fr0=0.805, hl="wrap", bp="body", tl="wide")),
    "Toyota Corolla": ("notch_soft", 0.59, dict(tr=0.30, fc=0.333, fr1=0.498, fr0=0.740, bp="body", hl="wrap")),
    "Land Cruiser Lovec": ("suv_box", 0.58, dict(fc=0.30, fr1=0.47, dn=0.04, dc=0.12, tr=0.40, hl="rect", gr="chrome")),
    "Nissan Qashqai": ("suv_soft", 0.61, dict(tr=0.35, fc=0.327, fr1=0.495, fr0=0.843, fd=0.955, gr="vee", bp="body", tl="wide")),
    "Dacia Duster": ("suv_soft", 0.62, dict(dn=0.12, tw=0.84, rnd=0.2, tr=0.35, fc=0.332, fr1=0.471, fr0=0.891, fd=0.963, gr="slats", hl="rect", tl="tall")),
    "Dacia Logan": ("notch_soft", 0.62, dict(fr0=0.76, fd=0.86, dn=0.11, tr=0.29, tw=0.83, fc=0.321, fr1=0.484, gr="slats", bp="body", tl="tall")),
    "Kia Picanto": ("mini", 0.66, dict(hl="wrap", gr="slim", tr=0.27, dn=0.12, fc=0.277, fr1=0.472, fr0=0.839, bp="body", tl="wide")),
    "Tesla Elon": ("notch_soft", 0.595, dict(fc=0.31, fr1=0.54, fr0=0.80, fd=0.956, dn=0.17, gr="none", hl="slit", tl="slim", tr=0.35, rnd=0.5, tw=0.84, bp="body")),
    "Hummer Patriot": ("suv_box", 0.65, dict(fc=0.32, fr1=0.45, fr0=0.945, dn=0.0, dc=0.16, hl="rect", gr="slats", tr=0.40, bp="body", nrR=0.015, tl="tall", nw=3)),
    "Smart Sitnichka": ("mini", 0.69, dict(fc=0.22, fr1=0.385, fr0=0.842, fd=0.969, dn=0.10, hl="wrap", gr="slim", tr=0.26, pf=0.50, tw=0.82, bp="body", tl="wide", nw=1)),
    "Cayenne od Germanija": ("suv_soft", 0.60, dict(hl="round", tr=0.375, dn=0.12, fr1=0.506, fr0=0.852, fd=0.967, bp="body", tl="wide")),
    "Range Rover Ortak": ("suv_box", 0.60, dict(fc=0.31, fr1=0.46, fr0=0.939, dc=0.14, tr=0.38, hl="rect", gr="slats", fd=0.980, tw=0.91, tl="tall", bp="body")),
    "Policiska Skoda": ("notch_soft", 0.59, dict(tr=0.31, fr1=0.491, fr0=0.735, gr="chrome", bp="body")),
    "Brza Pomosh": ("van_cab", 0.60, dict(fc=0.185, fr1=0.275, win="cab", pf=0.40, tr=0.345)),
    "Burek Dostava": ("van_cab", 0.60, dict(fc=0.20, fr1=0.30, win="cab", tr=0.31)),
    "Makedonska Posta": ("van_cab", 0.60, dict(fc=0.19, fr1=0.29, win="cab", tr=0.33)),
    "Svadbarska Limuzina": ("notch_soft", 0.67, dict(fc=0.27, fr1=0.42, fr0=0.78, fd=0.855, nw=4, fwe=0.50, tr=0.33, gr="chrome")),
    "Sladoled Kombe": ("van_cab", 0.60, dict(fc=0.20, fr1=0.30, win="cab", tr=0.31)),
    "Golf Petka TDI": ("hatch_soft", 0.615, dict(dn=0.15, tr=0.31, fr1=0.48, fr0=0.821, fd=0.933, tl="wide", bp="body", gr="blk")),
    "Golf Shestka Uvezen": ("hatch_soft", 0.615, dict(dn=0.17, tr=0.32, rnd=0.35, hl="slit", fr1=0.495, fr0=0.805, fd=0.945, tl="wide", bp="body", gr="slim")),
    "Passat B5 Karavan": ("wagon", 0.575, dict(tr=0.31, fr1=0.491, fr0=0.914, fd=0.98, tl="wide", bp="body")),
    "Passat B6 TDI": ("notch_soft", 0.57, dict(dn=0.16, tr=0.32, fd=0.855, hl="slit", fr1=0.523, fr0=0.737, gr="shield", tl="wide", bp="body")),
    "Audi A4 Avant Shvajcarska": ("wagon", 0.58, dict(tr=0.32, gr="chrome", fr1=0.504, fr0=0.906, tl="wide", bp="body")),
    "Audi A6 Nemachka": ("notch_soft", 0.575, dict(tr=0.325, gr="shield", fd=0.85, fr1=0.518, fr0=0.726, tl="slim", bp="body")),
    "BMW E46 Tjunirana": ("notch_soft", 0.60, dict(gr="kidney", tr=0.325, fr1=0.530, fr0=0.714, fd=0.859, bp="body", tl="wide")),
    "BMW E39 520d": ("notch_soft", 0.59, dict(gr="kidney", dn=0.11, tr=0.32, fr1=0.536, fr0=0.726, fd=0.848, bp="body", tl="wide")),
    "Mercedes C Klasa W203": ("notch_soft", 0.60, dict(gr="chrome", tr=0.32, fr1=0.527, fr0=0.706, hl="dual", bp="body", tl="wide")),
    "Mercedes E Klasa W211": ("notch_soft", 0.59, dict(gr="chrome", tr=0.33, hl="dual", fr1=0.528, fr0=0.720, bp="body", tl="wide")),
    "Opel Astra G": ("hatch_soft", 0.635, dict(tr=0.30, fr1=0.48, fr0=0.817, bp="body", tl="wide")),
    "Opel Corsa C": ("hatch_soft", 0.65, dict(tr=0.285, dn=0.16, fc=0.261, fr1=0.459, fr0=0.815, bp="body", tl="tall")),
    "Opel Zafira Familijarna": ("mpv", 0.62, dict(tr=0.31, fc=0.272, fr1=0.441, fr0=0.908, bp="body", hl="rect")),
    "Renault Megane Scenic": ("mpv", 0.605, dict(fc=0.26, fr1=0.42, tr=0.31, hl="round", fr0=0.882, fd=0.956, bp="body", gr="none")),
    "Peugeot 206": ("hatch_soft", 0.64, dict(tr=0.28, fc=0.251, fr1=0.471, fr0=0.797, fd=0.944, bp="body", tl="wide")),
    "Peugeot 307 SW": ("wagon", 0.615, dict(fc=0.31, fr1=0.49, tr=0.31, fr0=0.916, fd=0.986, bp="body", gr="none")),
    "Citroen Berlingo": ("mpv", 0.65, dict(fc=0.22, fr1=0.34, dn=0.04, tw=0.88, tr=0.30, gr="blk", fr0=0.953, fd=0.990, nw=3, rnd=0.27)),
    "Fiat Stilo": ("hatch_soft", 0.62, dict(tr=0.31, fr1=0.477, fr0=0.842, fd=0.971, hl="slit", tl="wide", bp="body")),
    "Fiat Multipla": ("mpv", 0.67, dict(fc=0.23, fr1=0.352, dn=0.02, tw=0.88, tr=0.30, hl="dual", fr0=0.912, bp="body", tl="tall")),
    "Skoda Fabia": ("hatch_soft", 0.62, dict(tr=0.29, dn=0.12, fc=0.290, fr1=0.476, fr0=0.847, hl="rect", gr="chrome", bp="body")),
    "Skoda Octavia Taksi": ("notch_soft", 0.59, dict(tr=0.31, fr1=0.491, fr0=0.735, gr="chrome", bp="body")),
    "Seat Leon Kupra": ("hatch_soft", 0.60, dict(tr=0.325, dn=0.16, fc=0.286, fr1=0.489, fr0=0.797, fd=0.949, bp="body", tl="slim")),
    "Hyundai Getz": ("hatch_soft", 0.645, dict(tr=0.28, fc=0.30, fr1=0.49, fr0=0.865, fd=0.965, bp="body", hl="wrap", tl="tall")),
    "Toyota Yaris": ("hatch_soft", 0.655, dict(tr=0.285, fc=0.29, fr1=0.48, dn=0.12, fr0=0.793, fd=0.951, bp="body", tl="tall")),
    "Ford Focus Karavan": ("wagon", 0.585, dict(tr=0.31, hl="wrap", dn=0.15, fr0=0.918, fd=0.976, bp="body", tl="tall")),
    "Ford Transit Shverc": ("van_cab", 0.58, dict(fc=0.16, fr1=0.26, win="cab", pf=0.38, tr=0.345)),
    "Volvo V70 Dedov": ("wagon", 0.585, dict(dn=0.06, hl="rect", gr="chrome", tr=0.31, tw=0.84, fr0=0.938, fd=0.986, bp="body", tl="tall")),
    "Golf Chetvorka Bez Registracija": ("hatch_soft", 0.60, dict(dn=0.11, tr=0.30, fr1=0.48, fr0=0.812, fd=0.947, tl="wide", bp="body")),
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


def _rim(name):
    """Choose the rim construction and the count of its vents or spokes."""
    if name in _PERIOD_RIMS:
        return _PERIOD_RIMS[name]
    if name in _ALLOY:
        return ("alloy", 7 if name.startswith(("Mercedes", "Audi")) else 5)
    if name.startswith(("Zastava", "Lada", "Fiat 126", "Fico", "Moskvich", "Renault 4", "Trabant", "Wartburg")):
        return ("steel", 6)
    if name.startswith(("Kombi", "Transporter", "Caddy", "Sprinter", "Ford Transit", "Maritsa")):
        return ("truck", 6)
    return ("steel", 8)                                  # everything else: pressed-steel wheel with a small hubcap


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


def wheel_track(W, tyre_width):
    """Half track for inset wheel faces, in both baked and separately animated meshes."""
    return W / 2 - tyre_width / 2 - 0.052


def layout(name, L):
    """What gl3d needs besides the mesh: roof centre / length, wheel axles, tyre radius, driver's door hinge and length."""
    s = spec(name, L)
    X = lambda f: L / 2 - f * L
    cx = (X(s["fr1"]) + X(s["fr0"])) / 2
    cl = X(s["fr1"]) - X(s["fr0"])
    hinge = X(s["seams"][0])
    return dict(hub=(176, 178, 184) if name in _ALLOY else (128, 130, 136), rim=_rim(name), cx=cx, cl=cl, ax_f=s["ax_f"], ax_r=s["ax_r"], tr=s["tr"], hinge=hinge, door=max(0.6, hinge - X(s["seams"][1])),
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
    detailed = name in ("Golf Dvojka", "Mercedes 190", "BMW E36 Bavarka")
    arch_r = tyre_r + 0.045
    arch_e = math.sqrt(arch_r ** 2 - (tyre_r - yb) ** 2)
    fs = {0.0, 0.035, 0.09, 0.94, 0.977, 1.0, fc, fr1, fr0, fd,
          fc * 0.5, (fc + fr1) / 2, (fr0 + fd) / 2, (fr1 + fr0) / 2}
    arch_samples = (-1, -.86, -.62, -.32, 0, .32, .62, .86, 1) if detailed else (-1, -.81, -.48, 0, .48, .81, 1)
    for axle in (s["ax_f"], s["ax_r"]):
        fs.update((L / 2 - axle + d * arch_e) / L for d in arch_samples)
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
    if fr0 > fr1 + 0.02:
        knots_f.insert(4, (fr1 + fr0) / 2)
        crown = 0.025 + 0.04 * s["rnd"]
        knots_y[3:5] = [roof - crown, roof - 0.01, roof - crown + 0.006]
    ty = np.interp(F, knots_f, knots_y)

    def arch_floor(x):
        dx = min(abs(x - s["ax_f"]), abs(x - s["ax_r"]))
        return max(yb, tyre_r + math.sqrt(arch_r ** 2 - dx ** 2)) if dx < arch_e - 1e-6 else yb

    def half_width(x):
        u = abs(x) / (L / 2)
        return W / 2 * (1 - s["rnd"] * 0.16 * np.clip((u - 0.62) / 0.38, 0, 1) ** 2)
    wins, seams = s["wins"], s["seams"]
    for i, f in enumerate(F):
        x = X(f)
        w = half_width(x)
        t_ = ty[i]
        shy = min(belt, t_ - 0.06)
        gh = t_ - shy
        tg = float(np.clip((gh - 0.06) / 0.5, 0, 1))
        wt = w * (1 - (1 - s["tw"]) * tg) - (1 - tg) * 0.07
        sy, sz = shy + 0.88 * gh, w - (w - wt) * 0.88
        edge = min(arch_floor(x), shy - 0.075)
        lip = min(edge + 0.035, shy - 0.04)
        L_ = [(edge, w - (0.038 if edge <= yb + 0.001 else 0.008)), (lip, w),
              (shy, w), (sy, sz), (t_, wt), (t_ + 0.01, wt - (0.064 if detailed else 0.07 + 0.035 * tg))]
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
                if in_win and gh > 0.09:
                    c, isglass[i, j] = gl, True
                elif name == "Kombi" and gh > 0.12:
                    c = roofc
            elif j in (4, 6):
                c = roofc if (in_roof or name == "Kombi") else body
            elif j in (3, 7) and name == "Kombi":
                c = roofc
            elif j == 5:
                if fc - 1e-6 <= m <= fr1 + 1e-6:
                    c, isglass[i, j] = gl, True
                elif s["win"] == "all" and fr0 - 1e-6 <= m <= fd + 1e-6:
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
    _wheelhouses(s, yb, arch_e, P, half_width, parts, shade, detailed)
    if detailed:
        _production_trim(name, s, L, yb, belt, hn, ht, P, X, half_width, arch_floor, parts, shade, body, quad)
        return parts
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
    lw, lh = {"round": (0.22, 0.22), "dual": (0.42, 0.18), "rect": (0.34, 0.15),
              "wrap": (0.46, 0.15), "slit": (0.52, 0.09)}[hl]
    lh = min(lh, max(0.05, ltop - (yb + 0.32)))

    def lamp(z, y, rz, ry, color, depth):
        ring = [(fxf(y + ry * math.sin(a)) + depth, y + ry * math.sin(a), z + rz * math.cos(a))
                for a in np.linspace(0, math.tau, 9)[:-1]]
        vertices = np.array([(ring[0], a, b) for a, b in zip(ring[1:], ring[2:])], np.float32).reshape(-1, 3)
        parts.append((vertices, np.tile(A(color) * shade(A((1, 0, 0))), (len(vertices), 1)), True))
    zo = capw - 0.05
    for sd in (-1, 1):
        zi = zo - lw
        lo, hi = sorted((sd * zo, sd * zi))
        if hl == "round":
            lamp((lo+hi)/2, ltop-lh/2, lw/2, lh/2+0.014, (156, 161, 165), 0.012)
            lamp((lo+hi)/2, ltop-lh/2, lw/2-0.018, lh/2, (235, 231, 209), 0.017)
        elif name == "Fiat Multipla":
            lamp((lo+hi)/2, ltop-lh/2, 0.088, lh*0.48, (225, 229, 216), 0.018)
            for fraction, y, radius in ((0.37, yb+0.13, 0.052), (0.31, hn+0.135, 0.070)):
                x = xf + 0.032 if y < hn else X(fc) + 0.062
                z = sd*W*fraction
                box(x-0.058, y-radius, z, 0.10, 2*radius, 2.05*radius, body*0.90)
                quad((x, y-radius*0.69, z-radius*0.69), (0, 0, radius*1.38),
                     (0, radius*1.38, 0), (1, 0, 0), (222, 227, 213))
        elif hl == "dual":
            lamp(lo+lw*0.28, ltop-lh/2, lw*0.25, lh*0.49, (220, 225, 220), 0.017)
            lamp(lo+lw*0.74, ltop-lh*0.57, lw*0.18, lh*0.39, (190, 200, 199), 0.017)
        else:
            fq(ltop - lh - 0.015, lh + 0.03, lo - 0.009, hi - lo + 0.018, (39, 41, 44), 0.009)
            fq(ltop - lh, lh, lo + 0.008, hi - lo - 0.016, (230, 232, 217), 0.014)
            if hl in ("rect", "wrap"):
                fq(ltop-lh+0.012, lh-0.024, lo+0.012 if sd == -1 else hi-0.070, 0.057, (215, 124, 38), 0.018)
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
    elif g == "shield":
        gz = min(0.37, capw * 0.49)
        fq(yb + 0.17, ltop - yb - 0.14, -gz, 2 * gz, (150, 155, 160), 0.01)
        fq(yb + 0.19, ltop - yb - 0.18, -gz + 0.025, 2 * gz - 0.05, (25, 26, 29), 0.015)
        for y in np.linspace(yb + 0.23, ltop - 0.025, 4):
            fq(y, 0.012, -gz + 0.032, 2 * gz - 0.064, (79, 82, 87), 0.02)
    elif g == "kidney":
        for sd in (-1, 1):
            fq(gy0 + 0.02, gy1 - gy0 - 0.02, sd * 0.2 - 0.17 * (sd < 0), 0.17, (196, 198, 204), 0.002)
            fq(gy0 + 0.04, gy1 - gy0 - 0.06, sd * 0.2 - 0.14 * (sd < 0), 0.13, (26, 26, 30), 0.004)
    fq(yb + 0.06, 0.10, -0.24, 0.48, (230, 232, 224), 0.046)
    fq(yb + 0.06, 0.10, -0.24, 0.024, (34, 70, 126), 0.049)
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
            rq(ttop - 0.16, 0.16, lo, hi - lo, (176, 30, 38), 0.009)
            rq(ttop - 0.05, 0.045, lo + 0.008, hi - lo - 0.016, (209, 117, 37), 0.014)
            rq(ttop - 0.093, 0.034, lo + (0.018 if sd == 1 else 0.215), 0.125, (218, 222, 211), 0.014)
    rq(yb + 0.20, 0.107, -0.24, 0.48, (232, 232, 225), 0.012)
    rq(yb + 0.20, 0.107, -0.24, 0.024, (34, 70, 126), 0.015)
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
    for sd in (-1, 1):
        zs = sd * (W / 2 + 0.008)
        sm = [seams[0], seams[1]] + ([seams[2]] if len(wins) > 1 else [])
        for fx in sm:                                                    # door shut lines from the sill to the shoulder
            x = X(fx)
            seam_bottom = min(belt - 0.14, max(yb + 0.10, arch_floor(x) + 0.031))
            quad((x, seam_bottom, sd * (half_width(x) + 0.009)), (0.013, 0, 0),
                 (0, belt - seam_bottom - 0.055, 0), (0, 0, sd), tuple(body * 0.5))
        for fx in sm[1:]:                                                # handles sit at the rear edge of each door
            quad((X(fx) + 0.10, belt - 0.14, zs + sd * 0.004), (0.15, 0, 0), (0, 0.03, 0), (0, 0, sd), (200, 200, 205))

        mxm = X(s["fw0"]) + 0.12                                         # mirror on the door's front corner, on a short stalk
        mw = half_width(mxm)
        box(mxm, belt + 0.045, sd * (mw + 0.052), 0.13, 0.085, 0.115, (40, 40, 44))
        box(mxm, belt + 0.044, sd * (mw - 0.005), 0.055, 0.034, 0.085, (60, 60, 64))
        quad((X(fc) - 0.2, belt - 0.04, zs + sd * 0.003), (0.5, 0, 0), (0, 0.02, 0), (0, 0, sd), tuple(body * 0.7))
        x0, x1 = s["ax_r"] + arch_e, s["ax_f"] - arch_e
        quad((x0, yb + 0.004, zs), (x1 - x0, 0, 0), (0, 0.035, 0), (0, 0, sd), (40, 40, 42))
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


def _wheelhouses(s, sill, extent, stations, half_width, parts, shade, detailed):
    """Back the fender openings so the body interior does not show through around the tyres."""
    for axle in (s["ax_f"], s["ax_r"]):
        for side in (-1, 1):
            edge = stations[:, 11 if side > 0 else 0]
            edge = edge[(abs(edge[:, 0] - axle) <= extent + 0.015) & (edge[:, 1] > sill + 0.001)]
            if len(edge) < 2:
                continue
            z = side * (half_width(axle) - 0.145)
            back = [(edge[0, 0] + 0.06, sill, z), *[(x, y + 0.015, z) for x, y, _ in edge],
                    (edge[-1, 0] - 0.06, sill, z)]
            v = [(back[0], a, b) for a, b in zip(back[1:], back[2:])]
            if detailed:
                for a, b in zip(edge, edge[1:]):
                    c, d = (b[0], b[1] + 0.015, z), (a[0], a[1] + 0.015, z)
                    v.extend(((a, b, c), (a, c, d)))
            verts = np.asarray(v, np.float32).reshape(-1, 3)
            colors = np.tile(np.array((18, 20, 23)) * shade(np.array((0, 0, side))), (len(verts), 1))
            parts.append((verts, colors, True))


def _production_trim(name, s, L, yb, belt, hn, ht, P, X, half_width, arch_floor, parts, shade, body, quad):
    golf = name == "Golf Dvojka"
    merc = name == "Mercedes 190"
    rubber, dark, chrome = (31, 32, 35), (18, 20, 23), (188, 193, 199)
    amber, lens, red = (222, 127, 41), (224, 227, 219), (169, 30, 36)
    xf, xr = L / 2, -L / 2

    def polygon(points, normal, color):
        vertices = np.array([(points[0], points[i], points[i + 1]) for i in range(1, len(points) - 1)],
                            np.float32).reshape(-1, 3)
        colors = np.tile(np.asarray(color) * shade(np.asarray(normal)), (len(vertices), 1))
        parts.append((vertices, colors, True))

    def face(end, outline, color, proud=0.008):
        front = end == 1
        top, rake = (hn, s["nrF"]) if front else (ht, s["nrR"])
        points = [(end * (L / 2 - rake * np.clip((y-yb-0.2) / (top-yb-0.2), 0, 1) + proud), y, z)
                  for z, y in outline]
        polygon(points, (end, 0, 0), color)

    def rect(end, z0, z1, y0, y1, color, proud=0.008):
        face(end, [(z0, y0), (z1, y0), (z1, y1), (z0, y1)], color, proud)

    def lens_disc(z, y, radius, color, proud):
        face(1, [(z + radius*np.cos(a), y + radius*np.sin(a))
                 for a in np.linspace(0, 2*np.pi, 14, endpoint=False)], color, proud)

    def bumper(end, low, high, color):
        end_width = half_width(end * L / 2)
        points = [(-end_width, 0.12), (-end_width, -0.021), (-end_width+0.10, -0.056),
                  (end_width-0.10, -0.056), (end_width, -0.021), (end_width, 0.12)]
        top = [(end * (L/2-d), high, z) for z, d in points]
        polygon(top, (0, 1, 0), np.minimum(np.asarray(color) * 1.18, 255))
        for i, (a, b) in enumerate(zip(top, top[1:])):
            normal = (end, 0, (-1, -0.6, 0, 0.6, 1)[i])
            polygon([a, b, (b[0], low, b[2]), (a[0], low, a[2])], normal, color)

    face_w = half_width(xf)
    bumper(1, yb+0.025, yb+(0.22 if golf else 0.29), rubber if golf else body*0.76)
    bumper(-1, yb+0.025, yb+(0.22 if golf else 0.28), rubber if golf else body*0.76)
    for end in (-1, 1):
        bw = half_width(end*L/2)-0.105
        rect(end, -bw, bw, yb+0.15, yb+0.19, dark, 0.066)
    if golf:
        rect(1, -face_w+0.024, face_w-0.024, hn-0.247, hn-0.017, dark, 0.026)
        for y in np.linspace(hn-0.228, hn-0.037, 5):
            rect(1, -face_w+0.035, face_w-0.035, y, y+0.012, (50, 52, 55), 0.030)
        for side in (-1, 1):
            lens_disc(side*(face_w-0.19), hn-0.132, 0.106, chrome, 0.038)
            lens_disc(side*(face_w-0.19), hn-0.132, 0.088, lens, 0.044)
            z0, z1 = sorted((side*0.40, side*0.61))
            rect(1, z0, z1, yb+0.104, yb+0.153, amber, 0.060)
        lens_disc(0, hn-0.136, 0.042, chrome, 0.038)
        lens_disc(0, hn-0.136, 0.032, (50, 57, 66), 0.043)
    elif merc:
        outline = [(-0.259, hn-0.029), (0.259, hn-0.029), (0.226, hn-0.265), (-0.226, hn-0.265)]
        face(1, outline, chrome, 0.026)
        face(1, [(-0.228, hn-0.053), (0.228, hn-0.053), (0.198, hn-0.24), (-0.198, hn-0.24)], dark, 0.030)
        for y in np.linspace(hn-0.225, hn-0.068, 5):
            width = 0.199 + 0.029 * (y - (hn-0.24)) / 0.187
            rect(1, -width, width, y, y+0.010, (141, 146, 151), 0.034)
        rect(1, -0.008, 0.008, hn-0.24, hn-0.053, chrome, 0.038)
        ornament_x = xf - 0.060
        quad((ornament_x, hn-0.009, -0.004), (0, 0, 0.008), (0, 0.058, 0), (1, 0, 0), chrome)
        ring = [(0.034*np.cos(a), hn + 0.075 + 0.034*np.sin(a)) for a in np.linspace(0, 2*np.pi, 10)]
        for (z0, y0), (z1, y1) in zip(ring, ring[1:]):
            polygon([(ornament_x, y0, z0), (ornament_x, y1, z1),
                     (ornament_x, hn+0.075+(y1-hn-0.075)*0.80, z1*0.8),
                     (ornament_x, hn+0.075+(y0-hn-0.075)*0.80, z0*0.8)], (1, 0, 0), chrome)
        for a in (np.pi/2, 7*np.pi/6, 11*np.pi/6):
            polygon([(ornament_x+0.001, hn+0.072, -0.004), (ornament_x+0.001, hn+0.072, 0.004),
                     (ornament_x+0.001, hn+0.075+0.031*np.sin(a), 0.031*np.cos(a))], (1, 0, 0), chrome)
    else:
        for side in (-1, 1):
            for inset, color in ((0, chrome), (0.016, dark)):
                x0, x1 = 0.016+inset, 0.169-inset
                lo, hi, cut = hn-0.207+inset, hn-0.064-inset, 0.024
                face(1, [(side*z, y) for z, y in [(x0+cut, lo), (x1-cut, lo), (x1, lo+cut), (x1, hi-cut),
                                                     (x1-cut, hi), (x0+cut, hi), (x0, hi-cut), (x0, lo+cut)]],
                     color, 0.020+inset)
            for z in (0.058, 0.086, 0.114, 0.142):
                ends = sorted((side*z, side*(z+0.005)))
                rect(1, *ends, hn-0.187, hn-0.084, (59, 62, 67), 0.040)

    if not golf:
        for side in (-1, 1):
            x0, x1 = 0.273 if merc else 0.187, face_w - 0.028
            lo, hi = (hn-0.240, hn-0.066) if merc else (hn-0.224, hn-0.080)
            face(1, [(side*z, y) for z, y in [(x0,lo), (x1,lo+0.027), (x1,hi-0.019), (x0,hi)]], dark, 0.026)
            ends = sorted((side*(x0+0.014), side*(x1-0.116)))
            rect(1, *ends, lo+0.039, hi-0.012, lens if merc else (159, 167, 169), 0.033)
            if not merc:
                for z in (x0+0.094, x0+0.23):
                    lens_disc(side*z, (lo+hi)*0.5+0.007, 0.048, lens, 0.042)
            face(1, [(side*z, y) for z, y in [(x1-0.106,lo+0.035), (x1-0.009,lo+0.037),
                                                 (x1-0.009,hi-0.026), (x1-0.106,hi-0.013)]], amber, 0.038)
            zf = side * (face_w + 0.006)
            zs = side * (half_width(xf-0.20) + 0.006)
            polygon([(xf-0.017, lo+0.031, zf), (xf-0.20, lo+0.092, zs),
                     (xf-0.20, hi-0.031, zs), (xf-0.017, hi-0.016, zf)], (0, 0, side), amber)
        rect(1, -0.33, 0.33, yb+0.073, yb+0.143, dark, 0.066)
    rect(1, -0.242, 0.242, yb+0.109, yb+0.205, (228, 231, 229), 0.073)
    rect(1, -0.242, -0.216, yb+0.109, yb+0.205, (39, 79, 146), 0.076)

    rear_w = half_width(xr)-0.04
    for side in (-1, 1):
        left, right = sorted((side*rear_w, side*(rear_w-(0.30 if golf else 0.36))))
        top = ht-0.048
        rect(-1, left-0.006, right+0.006, top-0.225, top+0.006, dark, 0.020)
        rect(-1, left, right, top-0.215, top-0.105, red, 0.028)
        rect(-1, left, right, top-0.095, top, (109, 36, 34) if merc else amber, 0.028)
        zl, zr = sorted((side*(rear_w-0.162), side*(rear_w-(0.29 if golf else 0.35))))
        rect(-1, zl, zr, top-(0.095 if not merc else 0.14), top-(0.015 if not merc else 0.08), lens, 0.034)
        if merc:
            for y in np.linspace(top-0.196, top-0.028, 4):
                rect(-1, left, right, y, y+0.010, (90, 37, 34), 0.038)
    rect(-1, -0.283, 0.283, yb+0.31, yb+0.459, dark, 0.023)
    rect(-1, -0.24, 0.24, yb+0.334, yb+0.433, (228, 231, 229), 0.031)
    rect(-1, -0.24, -0.214, yb+0.334, yb+0.433, (39, 79, 146), 0.034)

    for side in (-1, 1):
        def strip(x0, x1, y0, y1, color, offset=0.004):
            w0 = side*(half_width(x0)+offset)
            w1 = side*(half_width(x1)+offset)
            polygon([(x0, y0, w0), (x1, y0, w1), (x1, y1, w1), (x0, y1, w0)], (0, 0, side), color)

        for a, b in zip(np.linspace(xr+0.13, xf-0.14, 8)[:-1], np.linspace(xr+0.13, xf-0.14, 8)[1:]):
            strip(a, b, belt-0.188, belt-0.132 if merc else belt-0.154, rubber)
        for i, f in enumerate(s["seams"]):
            x = X(f)
            strip(x, x+0.009, min(belt-0.12, arch_floor(x)+0.042), belt-0.036, body*0.42, 0.010)
            if i:
                strip(x+0.055, x+0.175, belt-0.113, belt-0.090, rubber, 0.014)
        x = X(s["fw0"])+0.08
        z = side*(half_width(x)-0.034)
        quad((x-0.012, belt+0.022, z), (0.045, 0, 0), (0, 0, side*0.093), (0, 1, 0), rubber)
        points = [(x+0.070, z+side*0.042), (x+0.021, z+side*0.140),
                  (x-0.069, z+side*0.167), (x-0.087, z+side*0.04)]
        polygon([(a, belt+0.113, b) for a, b in points], (0, 1, 0), rubber if golf or merc else body)
        for i, ((a, b), (c, d)) in enumerate(zip(points, points[1:]+points[:1])):
            polygon([(a, belt+0.033, b), (c, belt+0.033, d), (c, belt+0.113, d), (a, belt+0.113, b)],
                    ((1, 0, -1, 0)[i], 0, side), (105, 119, 128) if i == 2 else rubber)



_PERIOD_RIMS = {
    "Golf Dvojka": ("golf_steel", 8),
    "Mercedes 190": ("w201_15_hole", 15),
    "BMW E36 Bavarka": ("e36_style_14", 10),
}

def draw_period_rim(vertices, colors, cx, cy, z, radius, rim):
    kind, count = rim
    metal = np.array((163, 167, 169) if kind == "golf_steel" else (182, 188, 193), dtype=np.float32)

    def point(r, angle, depth):
        return (cx+r*math.cos(angle), cy+r*math.sin(angle), z+depth)

    def face(points, color):
        for i in range(1, len(points)-1):
            vertices.extend((points[0], points[i], points[i+1]))
            colors.extend((color,)*3)

    def disk(r, depth, color, sides):
        face([point(r, i*math.tau/sides, depth) for i in range(sides)], color)

    def radial(inner, outer, angle, inner_half, outer_half, depth, color):
        face([point(inner, angle-inner_half, depth), point(outer, angle-outer_half, depth),
              point(outer, angle+outer_half, depth), point(inner, angle+inner_half, depth)], color)

    r = radius * (0.64 if kind == "golf_steel" else 0.69)
    if kind == "golf_steel":
        disk(r, 0, metal, 14)
        disk(r*0.85, 0.004, metal*0.69, 12)
        for i in range(count):
            radial(r*0.61, r*0.83, i*math.tau/count, 0.14, 0.19, 0.009, (33, 35, 36))
        disk(r*0.41, 0.016, (52, 55, 58), 8)
    elif kind == "w201_15_hole":
        disk(r, 0, metal*0.90, 14)
        disk(r*0.88, 0.003, metal, 12)
        for i in range(count):
            radial(r*0.64, r*0.86, i*math.tau/count, 0.075, 0.095, 0.009, (52, 55, 58))
        disk(r*0.32, 0.014, metal*1.06, 8)
    else:
        disk(r, 0.005, metal, 12)
        disk(r*0.88, 0.010, (50, 53, 58), 12)
        for i in range(count):
            angle = i*math.tau/count
            radial(r*0.29, r*0.91, angle, 0.23, 0.102, 0.017,
                   metal*(0.87+0.19*max(0, math.sin(angle))))
        disk(r*0.32, 0.023, metal, 8)
        disk(r*0.12, 0.027, (48, 92, 137), 6)
