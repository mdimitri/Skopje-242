"""Profile-lofted car bodies: a real side profile (nose, bonnet, windscreen, roof, rear glass / tailgate, deck), real wheelbase and
per-model face details, instead of one generic box-plus-cabin.  Pure numpy; gl3d.car_arrays calls build() for the car-like styles.

Positions are fractions f of the body length measured from the FRONT (f=0 nose, f=1 tail); heights are metres.
"""
import math

import numpy as np

from vehicle_look import ROAD, WINDOW_PILLARS

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


def _rim(name, tyre):
    if name in _PERIOD_RIMS:
        return _PERIOD_RIMS[name]
    if name in ROAD:
        diameter, style, count = ROAD[name][4]
        ratio = float(np.clip(diameter * 0.0127 / tyre, 0.43, 0.81))
        return style, count, ratio
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
    if name in ROAD:
        (length, _, _, wheelbase, overhang), levels, *_ = ROAD[name]
        fc, roof0, roof1, fd, belt, nose, deck, tail = levels
        s.update(fc=fc/100, fr1=roof0/100, fr0=roof1/100, fd=fd/100,
                 dn=(belt-nose)*L/length, dd=(deck-belt)*L/length, dt=(deck-tail)*L/length)
        wbr = wheelbase/length
        fo = overhang / length * L
    else:
        fo = (1-wbr) * L * s["pf"]
    s["arch"], s["wb"] = arch, wbr * L
    s["ax_f"], s["ax_r"] = L / 2 - fo, L / 2 - fo - s["wb"]
    fc, fr1, fr0, fd = s["fc"], s["fr1"], s["fr0"], s["fd"]
    fw0 = fc + 0.20 * (fr1 - fc)
    pw = 0.085 / L
    if name in WINDOW_PILLARS:
        partitions = WINDOW_PILLARS[name]
        wins = list(zip((fw0, *(f/100+pw/2 for f in partitions[:-1])),
                        (*(f/100-pw/2 for f in partitions[:-1]), partitions[-1]/100)))
    elif s["win"] == "cab":
        wins = [(fw0, min(fw0 + 1.13/L, fr0))]
    else:
        fwe = fr0 + s["fwe"] * (fd - fr0)
        n = s["nw"]
        wl = (fwe - fw0 - pw * (n - 1)) / n
        wins = [(fw0 + k * (wl + pw), fw0 + k * (wl + pw) + wl) for k in range(n)]
    s["wins"] = wins
    s["seams"] = [fw0 - 0.10 / L]
    s["seams"].extend((a[1] + b[0])/2 for a, b in zip(wins, wins[1:]))
    s["seams"].append(wins[-1][1] + 0.035/L)
    s["fw0"] = fw0
    _CACHE[name] = (L, s)
    return s


def wheel_track(W, tyre_width):
    """Half track for inset wheel faces, in both baked and separately animated meshes."""
    return W / 2 - tyre_width / 2 - 0.052


def render_dims(name, dims):
    """Scale reference proportions to the existing vehicle length."""
    if name not in ROAD:
        return dims
    reference, profile, *_ = ROAD[name]
    length, _, lower_edge, _, _ = dims
    scale = length/reference[0]
    return length, reference[1]*scale, lower_edge, profile[4]*scale, reference[2]*scale


def layout(name, L):
    """What gl3d needs besides the mesh: roof centre / length, wheel axles, tyre radius, driver's door hinge and length."""
    s = spec(name, L)
    X = lambda f: L / 2 - f * L
    cx = (X(s["fr1"]) + X(s["fr0"])) / 2
    cl = X(s["fr1"]) - X(s["fr0"])
    hinge = X(s["seams"][0])
    return dict(hub=(176, 178, 184) if name in _ALLOY else (128, 130, 136), rim=_rim(name, s["tr"] or 0.3), cx=cx, cl=cl, ax_f=s["ax_f"], ax_r=s["ax_r"], tr=s["tr"], hinge=hinge, door=max(0.6, hinge - X(s["seams"][1])),
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
    detailed = name in ("Golf Dvojka", "Mercedes 190", "Taxi Zlatna Zolta", "BMW E36 Bavarka")
    vintage_fenders = name == "Pachuvka 2CV"
    tall_tail = name in ROAD and ROAD[name][3][0] == "pillar"
    arch_r = tyre_r + 0.045
    arch_e = math.sqrt(arch_r ** 2 - (tyre_r - yb) ** 2)
    fs = {0.0, 0.035, 0.09, 0.94, 0.977, 1.0, fc, fr1, fr0, fd,
          fc * 0.5, (fc + fr1) / 2, (fr0 + fd) / 2, (fr1 + fr0) / 2}
    arch_samples = (-1, -.86, -.62, -.32, 0, .32, .62, .86, 1) if detailed and name != "Taxi Zlatna Zolta" else (-1, -.81, -.48, 0, .48, .81, 1)
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
    if vintage_fenders:
        knots_y[1:3] = [hn+(hc-hn)*0.44, hc-0.018]
    if fr0 > fr1 + 0.02:
        knots_f.insert(4, (fr1 + fr0) / 2)
        crown = 0.017 + 0.055 * s["rnd"]
        if name in ("Fico", "Pachuvka 2CV", "Fiat 126 Peglica", "Smart Sitnichka"):
            crown += 0.046
        knots_y[3:5] = [roof - crown, roof - 0.01, roof - crown + 0.004]
    ty = np.interp(F, knots_f, knots_y)

    def arch_floor(x):
        dx = min(abs(x - s["ax_f"]), abs(x - s["ax_r"]))
        return max(yb, tyre_r + math.sqrt(arch_r ** 2 - dx ** 2)) if dx < arch_e - 1e-6 else yb

    def half_width(x):
        u = abs(x) / (L / 2)
        width = W/2 * (1 - s["rnd"] * 0.23 * np.clip((u - 0.56) / 0.44, 0, 1)**2)
        if vintage_fenders:
            dx = min(abs(x-s["ax_f"]), abs(x-s["ax_r"]))
            width *= 0.67 + 0.33 * math.exp(-(dx/0.46)**2)
        return width
    wins, seams = s["wins"], s["seams"]
    for i, f in enumerate(F):
        x = X(f)
        w = half_width(x)
        t_ = ty[i]
        shoulder = belt
        if s["arch"] in ("hatch_soft", "suv_soft", "mpv", "wagon", "notch_soft"):
            waist_rise = 0.034 + s["rnd"] * 0.08
            shoulder += waist_rise*np.clip((f-fc)/(fd-fc), 0, 1)
        if vintage_fenders:
            shoulder += 0.075 * math.exp(-((x-s["ax_f"])/0.41)**2)
        shy = min(shoulder, t_ - 0.06)
        gh = t_ - shy
        tg = float(np.clip((gh - 0.06) / 0.5, 0, 1))
        wt = w * (1 - (1 - s["tw"]) * tg) - (1 - tg) * 0.07
        shoulder_w = w
        rocker_w = w - (0.038 if s["rnd"] < 0.30 else 0.052)
        if s["rnd"] >= 0.30 and not detailed:
            shoulder_w -= 0.022 + 0.014 * tg
        rail = 0.064 if detailed else 0.067 + 0.03*tg
        if vintage_fenders:
            wt = min(wt, W*(0.29 if f < fc else 0.35))
            rail *= 0.65
        if name in ("Fico", "Cayenne od Germanija", "Smart Sitnichka"):
            wt -= 0.025*tg
        sy, sz = shy + 0.84 * gh, w - (w - wt) * 0.79
        edge = min(arch_floor(x), shy - 0.075)
        lip = min(edge + 0.035, shy - 0.04)
        L_ = [(edge, rocker_w if edge <= yb + 0.001 else w-0.008), (lip, w),
              (shy, shoulder_w), (sy, min(sz, shoulder_w-0.002)), (t_, wt), (t_ + 0.01, wt - rail)]
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
                if in_win and max(ty[i], ty[i+1]) > belt + 0.075:
                    c, isglass[i, j] = gl, True
                elif name == "Kombi" and gh > 0.12:
                    c = roofc
                elif name == "Smart Sitnichka" and 0.54 < m < 0.91:
                    c = np.array((173, 177, 181))
                elif tall_tail and m > fr0 and gh > 0.12:
                    c = np.array((143, 24, 31))
            elif j in (4, 6):
                if name == "Smart Sitnichka" and fr1 < m < fd:
                    c = np.array((171, 177, 180))
                else:
                    c = roofc if (in_roof or name == "Kombi") else body
            elif j in (3, 7) and name == "Kombi":
                c = roofc
            elif j == 5:
                if fc - 1e-6 <= m <= fr1 + 1e-6:
                    c, isglass[i, j] = gl, True
                elif s["win"] == "all" and fr0 - 1e-6 <= m <= fd + 1e-6:
                    c, isglass[i, j] = gl, True
                elif in_roof and name == "Tesla Elon":
                    c, isglass[i, j] = gl*0.87, True
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
    capw = P[0, 10, 2]
    capwr = P[S - 1, 10, 2]
    _wheelhouses(s, yb, arch_e, P, half_width, parts, shade, detailed)
    if detailed:
        _production_trim(name, s, L, yb, belt, hn, ht, P, X, half_width, arch_floor, parts, shade, body, quad)
        return parts
    def side_quad(x0, y0, x1, y1, side, col, depth=0.011):
        o = _side_point(P, x0, y0, side, depth)
        a = _side_point(P, x1, y0, side, depth)
        b = _side_point(P, x0, y1, side, depth)
        quad(o, a-o, b-o, (0, 0, side), col)

    trim = _road_trim(name, s, L, W, belt, yb, hn, ht, capw, capwr, body, side_quad, box, parts, shade)
    if vintage_fenders:
        _fenders_2cv(parts, shade, body, s, W, tyre_r, yb)
    if s["arch"] == "pickup":                                        # the open load bed behind the cab: floor is the deck, walls round it
        bx0 = X(fd) - 0.02
        bc2 = tuple(body * 0.95)
        quad((xb + 0.05, hd + 0.004, -W / 2 + 0.06), (bx0 - xb - 0.05, 0, 0), (0, 0, W - 0.12), (0, 1, 0), (46, 44, 42))
        for sd in (-1, 1):
            box((xb + bx0) / 2, hd, sd * (W / 2 - 0.05), bx0 - xb, 0.30, 0.08, bc2)
        box(xb + 0.05, hd, 0, 0.08, 0.30, W - 0.1, bc2)
        box(bx0 - 0.05, hd, 0, 0.08, 0.34, W - 0.1, tuple(body * 0.9))
    if name in _SPARE:
        rcy = yb + (ht - yb) * 0.45
        # Circular tyre and cover on the tailgate.
        trim(-1, [(-0.31*math.cos(a), rcy + 0.31*math.sin(a))
                  for a in np.linspace(0, math.tau, 13)[:-1]], (31, 32, 35), 0.132)
        trim(-1, [(-0.225*math.cos(a), rcy + 0.225*math.sin(a))
                  for a in np.linspace(0, math.tau, 13)[:-1]], (75, 79, 82), 0.146)
    if name in _BULLBAR:
        box(xf + 0.12, yb + 0.28, 0, 0.07, 0.07, 2 * capw - 0.3, (190, 192, 198))
        for sd in (-1, 1):
            box(xf + 0.12, yb + 0.12, sd * (capw - 0.35), 0.07, 0.42, 0.06, (190, 192, 198))
    # ---- doors, handles, mirrors, wheel arches
    for sd in (-1, 1):
        zs = sd * (W / 2 + 0.008)
        sm = seams[:3]
        for fx in sm:                                                    # door shut lines from the sill to the shoulder
            x = X(fx)
            seam_bottom = min(belt - 0.14, max(yb + 0.10, arch_floor(x) + 0.031))
            side_quad(x, seam_bottom, x+0.012, belt-0.053, sd, body*0.48)
        for fx in sm[1:]:                                                # handles sit at the rear edge of each door
            x = X(fx)
            side_quad(x+0.072, belt-0.142, x+0.183, belt-0.119, sd,
                      (157, 160, 163) if s["rnd"] < 0.25 else body*0.57, 0.018)

        mxm = X(s["fw0"]) + 0.12                                         # mirror on the door's front corner, on a short stalk
        mw = half_width(mxm)
        box(mxm, belt + 0.045, sd * (mw + 0.052), 0.13, 0.085, 0.115, (40, 40, 44))
        box(mxm, belt + 0.044, sd * (mw - 0.005), 0.055, 0.034, 0.085, (60, 60, 64))
        if name in ("Zastava Yugo", "Zastava 101 Skala", "Zastava Koral", "Fiat Uno", "Audi 80 Bachok",
                    "Mercedes 124 Taksist", "Lada Samara", "Passat Dijaspora", "Golf Trojka Gastarbajter",
                    "Opel Astra G", "Opel Astra Karavan", "Nissan Qashqai", "Citroen Berlingo",
                    "Transporter Kombe", "Ford Transit Shverc", "Lada Niva"):
            z0, z1 = xb+L*0.09, xf-L*0.075
            for a, b in zip(np.linspace(z0,z1,7)[:-1], np.linspace(z0,z1,7)[1:]):
                side_quad(a, belt-0.206, b, belt-0.166, sd, (39,41,43))
        x0, x1 = s["ax_r"] + arch_e, s["ax_f"] - arch_e
        quad((x0, yb + 0.004, zs), (x1 - x0, 0, 0), (0, 0.035, 0), (0, 0, sd), (40, 40, 42))
    return parts


def indicator_mounts(name, length, width, belt):
    """Front and rear amber lens centres on the positive side of the generated lamp clusters."""
    s = spec(name, length)
    sill = s["gc"]
    nose, tail = belt - s["dn"], belt + s["dd"] - s["dt"]
    fw = rw = width * 0.5 * (1.0 - s["rnd"] * 0.23)
    if name == "Pachuvka 2CV":
        fw *= 0.67 + 0.33 * math.exp(-((length * 0.5 - s["ax_f"]) / 0.46) ** 2)
        rw *= 0.67 + 0.33 * math.exp(-((-length * 0.5 - s["ax_r"]) / 0.46) ** 2)

    def mount(end, y, z, depth, lens_w, lens_h):
        top, rake = (nose, s["nrF"]) if end == 1 else (tail, s["nrR"])
        taper = max(0.0, min(1.0, (y - sill - 0.2) / max(0.1, top - sill - 0.2)))
        return (end * (length * 0.5 - rake * taper + depth), y, z, lens_w, lens_h)

    if name in ("Golf Dvojka", "Mercedes 190", "Taxi Zlatna Zolta", "BMW E36 Bavarka"):
        if name == "Golf Dvojka":
            front = mount(1, sill + 0.1285, 0.505, 0.064, 0.16, 0.047)
        else:
            front = mount(1, nose - 0.151, fw - 0.086, 0.043, 0.084, 0.105)
        return front, mount(-1, tail - 0.093, rw - 0.10, 0.043, 0.09, 0.068)

    reference, _, head, rear, _ = ROAD[name]
    lamp, _, lh, _ = head
    rear_style, lens_w, lens_h = rear
    scale = length / reference[0]
    bumper = sill + 0.024 + min(0.19, (nose - sill) * 0.34)
    bottom = nose - 0.041 - min(lh * scale, max(0.105, nose - bumper - 0.047))
    if name == "Lada Niva":
        front = mount(1, nose - 0.055, fw - 0.1375, 0.025, 0.12, 0.054)
    elif lamp in ("stalk", "round", "quad", "rect"):
        bottom = max(sill + 0.055, min(bottom - 0.079, bumper - 0.064))
        front = mount(1, bottom + 0.026, fw - 0.1075, 0.065, 0.09, 0.046)
    else:
        front = mount(1, (bottom + nose - 0.041) * 0.5, fw - 0.105, 0.027, 0.07, 0.059)
    rear_top = tail - 0.042
    rh = min(lens_h * scale, max(0.09, rear_top - sill - 0.174))
    rw -= 0.045
    rw -= max(0.044, min(lens_w * scale, rw - 0.12) * (0.28 if rear_style == "roundpair" else 0.16))
    return front, mount(-1, rear_top - rh * 0.39, rw, 0.027, 0.08, 0.045)


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


def _side_point(stations, x, y, side, depth):
    """Sample the loft at a panel height so trim follows the actual fender."""
    indices = slice(0, 6) if side < 0 else slice(11, 5, -1)
    sections = stations[::-1, indices]
    xs = sections[:, 0, 0]
    j = int(np.clip(np.searchsorted(xs, x), 1, len(xs)-1))
    a, b = sections[j-1], sections[j]
    f = np.clip((x-xs[j-1])/max(0.0001, xs[j]-xs[j-1]), 0, 1)
    ring = a + (b-a)*f
    z = np.interp(y, ring[:, 1], ring[:, 2])
    return np.array((x, y, z+side*depth), np.float32)


def _fenders_2cv(parts, shade, paint, spec, width, radius, sill):
    # Rounded pressed wings extend outside the narrow hood and fastback body.
    for axle in (spec["ax_f"], spec["ax_r"]):
        for side in (-1, 1):
            angles = np.linspace(0.34, math.pi-0.34, 8)
            radius_outer = radius + 0.073
            arch = [(axle+radius_outer*math.cos(a), radius+radius_outer*math.sin(a),
                     side*width*(0.462+0.029*math.sin(a))) for a in angles]
            inner = [(x, y+0.10*math.sin(a), side*width*0.269) for (x,y,z),a in zip(arch,angles)]
            v = [(a,b,c,a,c,d) for a,b,c,d in zip(arch,arch[1:],inner[1:],inner)]
            v = np.asarray(v, np.float32).reshape(-1,3)
            c = np.tile(np.minimum(paint*1.04,255), (len(v),1))
            vv, cc = _shaded(v, c, np.zeros(len(v),bool), sill, radius*2.4, shade)
            parts.append((vv, cc, True))


def _road_trim(name, spec, length, width, belt, sill, nose, tail, front_w, rear_w,
               paint, side_quad, box, parts, shade):
    reference, _, head, rear, _ = ROAD[name]
    lamp, lw, lh, grille = head
    rear_style, rw, rh = rear
    scale = length/reference[0]
    dark, rubber = (27, 29, 33), (42, 44, 47)
    chrome, clear, amber, red = (170, 176, 186), (228, 230, 215), (218, 131, 55), (182, 34, 46)

    def polygon(points, normal, color):
        vertices = np.asarray([(points[0], a, b) for a, b in zip(points[1:], points[2:])],
                              np.float32).reshape(-1, 3)
        rgb = np.tile(np.asarray(color)*shade(np.asarray(normal)), (len(vertices), 1))
        parts.append((vertices, rgb, True))

    def body_x(end, height):
        top, rake = (nose, spec["nrF"]) if end > 0 else (tail, spec["nrR"])
        return end * (length/2 - rake*np.clip((height-sill-0.2)/max(0.10, top-sill-0.2), 0, 1))

    def face(end, outline, color, depth=0.014):
        polygon([(body_x(end, y)+end*depth, y, z) for z, y in outline], (end, 0, 0), color)

    def rect(end, z0, z1, low, high, color, depth=0.014):
        face(end, [(z0,low), (z1,low), (z1,high), (z0,high)], color, depth)

    def ellipse(end, z, y, a, b, color, depth=0.015, sides=8):
        face(end, [(z+a*math.cos(t), y+b*math.sin(t))
                   for t in np.linspace(0, math.tau, sides, endpoint=False)], color, depth)

    def bumper(end, cap_w, top):
        bumper_w = cap_w-0.019
        bumper_h = min(0.19, (top-sill)*0.34)
        low = sill + 0.024
        high = low + bumper_h
        color = {"chrome": chrome, "black": rubber, "body": paint*0.88}[spec["bp"]]
        path = [(-bumper_w, 0.085), (-bumper_w, -0.01), (-bumper_w+0.095, -0.057),
                (bumper_w-0.095, -0.057), (bumper_w, -0.01), (bumper_w, 0.085)]
        top_points = [(end*(length/2-d), high, z) for z, d in path]
        polygon(top_points, (0, 1, 0), np.minimum(np.asarray(color)*1.18, 255))
        for i, (a, b) in enumerate(zip(top_points, top_points[1:])):
            n = (end, 0, (-1, -0.5, 0, 0.5, 1)[i])
            polygon([a,b,(b[0],low,b[2]),(a[0],low,a[2])], n, color)
        return high

    bumper_top = bumper(1, front_w, nose)
    bumper(-1, rear_w, tail)
    outer = front_w - (0.087 if lamp in ("round", "quad") else 0.048)
    lw = min(lw*scale, outer-0.092)
    lh = min(lh*scale, max(0.105, nose-bumper_top-0.047))
    top = nose-0.041
    bottom = top-lh
    inner = outer-lw

    # Each housing outlines a photographed lamp family, with the wide-lens types wrapping onto the fender.
    for side in (-1, 1):
        if lamp in ("round", "quad"):
            count = 2 if lamp == "quad" else 1
            radius = min(lw/(count*2.08), lh/2)
            for i in range(count):
                centre = outer - radius*(1+2.11*i)
                ellipse(1, side*centre, (top+bottom)/2, radius, radius*0.99, chrome, 0.021)
                ellipse(1, side*centre, (top+bottom)/2, radius*0.84, radius*0.84, clear, 0.025)
        elif lamp in ("oval", "dual"):
            if lamp == "dual":
                ellipse(1, side*(outer-lw*0.27), (top+bottom)/2, lw*0.285, lh*0.53, dark)
                ellipse(1, side*(outer-lw*0.26), (top+bottom)/2, lw*0.246, lh*0.45, clear, 0.02)
                ellipse(1, side*(outer-lw*0.74), top-lh*0.58, lw*0.21, lh*0.37, (200, 211, 213), 0.024)
            else:
                ellipse(1, side*(outer-lw/2), (top+bottom)/2, lw*0.50, lh*0.52, dark, 0.016)
                ellipse(1, side*(outer-lw/2), (top+bottom)/2, lw*0.46, lh*0.44, clear, 0.022)
        elif lamp == "stalk":
            x = spec["ax_f"]+length*0.047
            y, z = belt + 0.025, side*width*0.352
            box(x-0.071, y-0.17, z, 0.045, 0.16, 0.047, rubber)
            for r, x1, color in ((0.103, x-0.008, (74, 77, 83)), (0.086,x+0.003,clear)):
                polygon([(x1, y+r*math.sin(a), z+r*math.cos(a))
                         for a in np.linspace(0,math.tau,11,endpoint=False)], (1,0,0), color)
        elif lamp == "pod":
            ellipse(1, side*(outer-lw/2), (top+bottom)/2, lh*0.43, lh*0.46, clear, 0.019)
            ellipse(1, side*(outer-0.096), min(bumper_top-0.064, sill+0.12), 0.054, 0.046, clear, 0.060)
            x, z, radius = length/2 - spec["fc"]*length+0.055, side*width*0.30, 0.08
            box(x-0.057, belt-radius*0.38, z, 0.13, radius*1.8, radius*2.1, paint)
            polygon([(x+0.012, belt+0.036+radius*0.78*math.sin(a), z+radius*0.78*math.cos(a))
                     for a in np.linspace(0,math.tau,9,endpoint=False)], (1,0,0), clear)
        else:
            lift = lh*(0.52 if lamp == "sweep" else 0.31 if lamp == "wedge" else 0.13)
            shape = [(inner, bottom), (outer-0.036, bottom+lift*0.58), (outer, top+lift*0.32),
                     (outer-0.085, top+lift*0.38), (inner+0.027, top-lift*0.57)]
            face(1, [(side*z, y) for z, y in shape], dark, 0.018)
            mid = (inner+outer)/2, (top+bottom)/2
            face(1, [(side*(mid[0]+(z-mid[0])*0.93), mid[1]+(y-mid[1])*0.81)
                     for z,y in shape], clear, 0.023)
            if lamp in ("wide", "sweep", "wedge"):
                x = length/2
                side_quad(x-0.16, bottom+lift*0.48, x-0.012, top-0.006, side, clear)
        if lamp in ("stalk", "round", "quad", "rect"):
            z0, z1 = sorted((side*(front_w-0.16), side*(front_w-0.055)))
            low = max(sill+0.055, min(bottom-0.079, bumper_top-0.064))
            rect(1, z0, z1, low, low+0.051, amber, 0.061)
        if name == "Lada Niva":
            z0, z1 = sorted((side*(front_w-0.21), side*(front_w-0.065)))
            rect(1, z0, z1, nose-0.086, nose-0.025, amber, 0.021)

    def grille_shape(style, low, high, wide, narrow=None):
        upper = wide
        lower = wide*0.8 if narrow is None else narrow
        outer_pts = [(-lower,low),(lower,low),(upper,high),(-upper,high)]
        face(1, outer_pts, chrome if style in ("merc", "frame", "shield", "skoda", "crown") else rubber, 0.014)
        face(1, [(-lower+0.017,low+0.014),(lower-0.017,low+0.014),
                 (upper-0.017,high-0.014),(-upper+0.017,high-0.014)], dark, 0.019)
        if style in ("mesh", "merc", "frame", "bar", "shield", "van", "bars", "wing", "crown", "skoda", "vshape"):
            for f in (0.22, 0.43, 0.64, 0.83):
                y = low + (high-low)*f
                w = lower+(upper-lower)*f-0.02
                rect(1, -w, w, y-0.004, y+0.004, (77, 81, 87), 0.024)
        return (low+high)/2

    gap = max(0.12, inner-0.023)
    gy = (top+bottom)/2
    lower_w = width*(0.26 if grille in ("plain", "intake", "shield") else 0.23)
    if grille in ("plain", "intake", "honeycomb", "split", "vshape", "slit", "oval"):
        y = sill + (bumper_top-sill)*0.40
        rect(1, -lower_w, lower_w, y-0.026, y+0.025, dark, 0.061)
    if grille == "kidney":
        for side in (-1, 1):
            g = min(0.19, gap-0.004)
            z = side*(0.025+g*0.50)
            ellipse(1, z, gy, g/2, lh*0.39, chrome, 0.023)
            ellipse(1, z, gy, g*0.39, lh*0.30, dark, 0.027)
    elif grille == "bars":
        for i in range(-3,4):
            x = i*0.061
            rect(1, x-0.019, x+0.019, bottom-0.041, top+0.009, chrome, 0.019)
            rect(1, x-0.012, x+0.012, bottom-0.030, top+0.001, dark, 0.024)
    elif grille == "shield":
        gy = grille_shape(grille, max(sill+0.19,bottom-0.09), top+0.012, width*0.181, width*0.145)
    elif grille in ("skoda", "merc", "frame", "van", "crown", "mesh"):
        gy = grille_shape(grille, bottom-0.018, top+0.003, gap)
    elif grille in ("wing", "split", "slot", "slit", "vshape", "bar", "honeycomb"):
        gy = grille_shape(grille, top-min(lh*0.81,0.133), top-0.008, gap, gap*0.92)
    elif grille == "oval":
        ellipse(1, 0, gy, gap*0.78, lh*0.44, dark, 0.017)
    emblem = badge(name)
    if emblem and grille != "kidney":
        ellipse(1, 0, gy if grille != "plain" else nose-0.059, 0.028, 0.026, chrome, 0.029, 6)

    rear_top = tail-0.042
    rw = min(rw*scale, rear_w-0.16)
    rh = min(rh*scale, max(0.09, rear_top-sill-0.174))
    for side in (-1,1):
        z0 = rear_w-0.045
        z1 = z0-rw
        bottom = rear_top-rh
        if rear_style in ("wing", "band"):
            outline = [(z1,bottom+rh*0.24),(z0-0.032,bottom),(z0,rear_top),(z1+0.008,rear_top-rh*0.21)]
        elif rear_style in ("upright", "pillar"):
            outline = [(z1+rw*0.17,bottom),(z0-0.009,bottom),(z0,rear_top),(z1,rear_top-0.015)]
        else:
            outline = [(z1,bottom),(z0,bottom),(z0,rear_top),(z1,rear_top)]
        face(-1, [(side*z,y) for z,y in outline], red, 0.017)
        a,b = sorted((side*(z1+rw*0.13), side*(z0-rw*0.10)))
        if rear_style == "roundpair":
            for frac in (0.26,0.72):
                ellipse(-1, side*(z1+rw*frac), bottom+rh*0.54, rw*0.17, rh*0.35, (216, 55, 61), 0.023)
        else:
            rect(-1, a,b, bottom+rh*0.51, bottom+rh*0.71, clear if rear_style == "wing" else amber, 0.022)
        if rear_style in ("wing", "pillar", "upright"):
            x = -length/2
            reach = 0.14 if rear_style == "wing" else 0.08
            side_quad(x+0.014, bottom+rh*0.15, x+reach, rear_top-0.012, side, red)
    if rear_style == "band":
        rect(-1, -rear_w+rw+0.035, rear_w-rw-0.035, rear_top-rh*0.70, rear_top-rh*0.31, (85,29,36), 0.017)
    for end, h, depth in ((1, sill+0.052, 0.066), (-1, min(tail-0.145,sill+0.235), 0.026)):
        rect(end, -0.235, 0.235, h, h+0.093, (223,226,222), depth)
        rect(end, -0.235, -0.213, h, h+0.093, (39,79,146), depth+0.004)
    return face


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
    merc = name in ("Mercedes 190", "Taxi Zlatna Zolta")
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
