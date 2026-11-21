"""Dev draft: five tree LOD meshes (1 = cheapest, 5 = most realistic) for 4 species, rendered to a comparison sheet.
python tree_lod.py out.png   (needs numpy + Pillow)"""
import math, random, sys
import numpy as np
from PIL import Image, ImageDraw

def leaf_tex(n=128, leaves=34, seed=1, size=(.09, .17)):
    """Procedural alpha leaf-cluster sprite: (lightness 0..255, alpha 0/255). Tinted by the card's colour at draw time."""
    r = random.Random(seed); L = Image.new("L", (n, n), 0); A = Image.new("L", (n, n), 0); dl, da = ImageDraw.Draw(L), ImageDraw.Draw(A)
    tw = [(n*.5, n*.98), (n*.5+r.uniform(-.1, .1)*n, n*.55), (n*.5+r.uniform(-.2, .2)*n, n*.15)]
    dl.line(tw, fill=70, width=2); da.line(tw, fill=255, width=2)
    for _ in range(leaves):
        t = r.random(); cx = n*.5+(tw[2][0]-n*.5)*t*r.uniform(0, 1.6)+r.uniform(-.3, .3)*n*(1-.4*t); cy = n*(.95-.85*t)+r.uniform(-.05, .05)*n
        ln = r.uniform(*size)*n; wd = ln*r.uniform(.4, .6); a = r.uniform(0, 6.28); ca, sa = math.cos(a), math.sin(a)
        poly = [(cx+ca*ln*x-sa*wd*y, cy+sa*ln*x+ca*wd*y) for x, y in ((-1, 0), (-.3, .9), (.6, .8), (1, 0), (.6, -.8), (-.3, -.9))]
        dl.polygon(poly, fill=int(r.uniform(120, 255))); da.polygon(poly, fill=255)
    return np.array(L, np.uint8), np.array(A, np.uint8)
_TEX = {}
def tex(seed):
    if seed not in _TEX: _TEX[seed] = leaf_tex(seed=seed)
    return _TEX[seed]

def card(m, c, right, up, t, col):
    """One alpha-tested leaf-cluster quad = 2 triangles"""
    c, right, up = np.array(c, float), np.array(right, float), np.array(up, float)
    q = [c-right, c+right, c+right+up*2, c-right+up*2]
    m.card.append((q, t, col)); m.ncard += 2

def cards_at(m, c, size, n, col, rnd, seedtex, flat=False):
    for i in range(n):
        a = math.pi*i/n+rnd.uniform(-.3, .3); tilt = rnd.uniform(-.5, .5)
        right = np.array([math.cos(a), 0, math.sin(a)])*size*.5; up = np.array([math.sin(a)*tilt*.5, 1, -math.cos(a)*tilt*.5]); up = up/np.linalg.norm(up)*size*.5
        if flat: up = np.array([0, 0, 0.]) + np.array([-math.sin(a), 0, math.cos(a)])*size*.5
        card(m, np.array(c)-up*(0 if flat else 1)*1.0, right, up, seedtex, jit(col, rnd, .1))

class M:
    def __init__(s): s.t = []; s.card = []; s.ncard = 0          # (p0,p1,p2,rgb) lit later
    def tri(s, a, b, c, col): s.t.append((np.array(a, float), np.array(b, float), np.array(c, float), col))
    def n(s): return len(s.t)+s.ncard

def cyl(m, p0, p1, r0, r1, n, col):
    p0, p1 = np.array(p0, float), np.array(p1, float); d = p1 - p0; d /= np.linalg.norm(d) + 1e-9
    u = np.cross(d, (1, 0, 0) if abs(d[0]) < .9 else (0, 0, 1)); u /= np.linalg.norm(u); v = np.cross(d, u)
    for i in range(n):
        a0, a1 = 2*math.pi*i/n, 2*math.pi*(i+1)/n
        q = [p0+(u*math.cos(a)+v*math.sin(a))*r0 for a in (a0, a1)] + [p1+(u*math.cos(a)+v*math.sin(a))*r1 for a in (a1, a0)]
        m.tri(q[0], q[1], q[2], col); m.tri(q[0], q[2], q[3], col)

def ico(sub):
    t = (1+5**.5)/2
    V = [(-1,t,0),(1,t,0),(-1,-t,0),(1,-t,0),(0,-1,t),(0,1,t),(0,-1,-t),(0,1,-t),(t,0,-1),(t,0,1),(-t,0,-1),(-t,0,1)]
    F = [(0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),(1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),(3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),(4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1)]
    V = [np.array(v, float)/np.linalg.norm(v) for v in V]
    for _ in range(sub):
        nf = []
        for a, b, c in F:
            ids = []
            for x, y in ((a, b), (b, c), (c, a)):
                w = (V[x]+V[y]); V.append(w/np.linalg.norm(w)); ids.append(len(V)-1)
            nf += [(a, ids[0], ids[2]), (b, ids[1], ids[0]), (c, ids[2], ids[1]), (ids[0], ids[1], ids[2])]
        F = nf
    return V, F

SEA = {"on": False}
def blob(m, c, rx, ry, rz, sub, col, rnd, noise=0.0, flat=0.0):
    if SEA["on"]:                                            # fall: each lump drifts toward its own autumn colour, late fall drops lumps
        if rnd.random() < SEA["drop"]: return
        col = jit(mix(col, rnd.choice(SEA["cols"]), SEA["t"]*rnd.uniform(.6, 1.0)), rnd, .06)
    V, F = ico(sub)
    P = []
    for v in V:
        k = 1 + rnd.uniform(-noise, noise)
        y = v[1]*ry*k
        P.append(np.array(c) + np.array([v[0]*rx*k, y, v[2]*rz*k]))
    for a, b, d in F:
        cy = (V[a][1]+V[b][1]+V[d][1])/3
        sh = 0.72 + 0.4*(cy*.5+.5)                      # darker underside, lighter top
        cc = tuple(min(255, int(x*sh*rnd.uniform(.94, 1.06))) for x in col)
        m.tri(P[a], P[b], P[d], cc)

def tiers(m, x, z, y0, y1, rad, n_t, sides, col, rnd, droop=0.0, ripple=0.0, spikes=0):
    """stacked conifer skirts; each = ring at lower edge -> apex of the tier"""
    for t in range(n_t):
        f = t/(n_t-1 if n_t > 1 else 1)
        yb = y0 + (y1-y0)*f*0.82; yt = yb + (y1-y0)*(1.0/n_t)*1.9 + 0.3 if t < n_t-1 else y1
        r = rad*(1-f*0.82)
        top = (x, yt, z)
        for i in range(sides):
            a0, a1 = 2*math.pi*i/sides, 2*math.pi*(i+1)/sides
            r0 = r*(1+rnd.uniform(-ripple, ripple)); r1 = r*(1+rnd.uniform(-ripple, ripple))
            p0 = (x+math.cos(a0)*r0, yb-droop*r0, z+math.sin(a0)*r0); p1 = (x+math.cos(a1)*r1, yb-droop*r1, z+math.sin(a1)*r1)
            sh = 0.8+0.3*math.cos(a0+.8)
            lo = tuple(min(255, int(c*sh*.75)) for c in col); hi = tuple(min(255, int(c*sh*1.12)) for c in col)
            mid = ((p0[0]+p1[0]+2*x)/4, yb+(yt-yb)*.35-droop*r*.3, (p0[2]+p1[2]+2*z)/4)
            if spikes:
                m.tri(p0, p1, mid, lo); m.tri(p0, mid, top, hi); m.tri(mid, p1, top, hi)
            else:
                m.tri(p0, p1, top, hi)
            m.tri(p1, p0, (x, yb-.2, z), lo)

BARK = (92, 70, 50)
def jit(c, rnd, a=.12): return tuple(max(0, min(255, int(v*rnd.uniform(1-a, 1+a)))) for v in c)
def mix(a, b, t): return tuple(int(x+(y-x)*t) for x, y in zip(a, b))
GREENS = [(84,140,62),(70,128,58),(96,150,64),(110,140,52),(62,114,54),(124,150,70)]
AUTUMN = [(196,120,40),(210,170,50),(170,70,40)]
# species: kind, bark, leaf palette, base height, trunk fraction, crown radius / height factors
SPECIES = {
 "spruce":   dict(kind="conifer", bark=BARK, pal=[(46,92,56),(40,84,60),(56,100,60)], h=(8,13), rad=(2.2,3.2), tiers=(8,11), droop=(.1,.3)),
 "fir":      dict(kind="conifer", bark=(80,62,48), pal=[(34,80,62),(44,90,70)], h=(9,15), rad=(1.6,2.2), tiers=(10,14), droop=(.05,.15)),
 "cypress":  dict(kind="column", bark=(100,80,60), pal=[(40,86,52),(48,96,56)], h=(8,14), rad=(.8,1.3), tf=.08),
 "poplar":   dict(kind="column", bark=BARK, pal=[(70,130,58),(84,140,62)], h=(11,16), rad=(1.1,1.7), tf=.2),
 "lime":     dict(kind="broad", bark=BARK, pal=GREENS, h=(7,11), rad=(3,4.4), ry=.8, tf=.3, lumps=(5,7), spread=(.8,1.1)),
 "oak":      dict(kind="broad", bark=(84,66,50), pal=[(72,118,52),(86,126,50),(96,120,48)], h=(8,12), rad=(4,5.6), ry=.62, tf=.26, lumps=(6,9), spread=(1.0,1.3)),
 "birch":    dict(kind="broad", bark=(228,228,220), pal=[(96,150,64),(110,160,70)], h=(8,12), rad=(2.4,3.3), ry=.9, tf=.38, lumps=(4,6), spread=(.7,1.0)),
 "acacia":   dict(kind="broad", bark=(78,64,52), pal=[(104,140,60),(120,150,66)], h=(6,9), rad=(3.2,4.4), ry=.38, tf=.5, lumps=(5,7), spread=(1.0,1.3)),
 "willow":   dict(kind="weep", bark=(86,72,54), pal=[(120,150,70),(132,158,76)], h=(7,10), rad=(3.4,4.6), tf=.3),
 "stonepine":dict(kind="broad", bark=(110,76,52), pal=[(58,104,56),(66,112,58)], h=(8,12), rad=(3.5,4.8), ry=.28, tf=.68, lumps=(5,7), spread=(1.0,1.4)),
 "dead":     dict(kind="dead", bark=(80,66,54), h=(5,9), rad=(1.6,2.6), tf=.5),
}

def branches(m, base, d, ln, r, depth, rnd, col, leaf, sides, leaf_sub, leaf_r, spread=0.7, kids=3):
    end = np.array(base)+np.array(d)*ln
    cyl(m, base, end, r, r*.62, sides, col)
    if depth == 0:
        if leaf_sub >= 0: blob(m, end, leaf_r, leaf_r*.8, leaf_r, leaf_sub, jit(leaf, rnd, .06), rnd, .22)
        return
    for k in range(kids):
        a = rnd.uniform(0, 6.28); t = spread*rnd.uniform(.7, 1.3)
        nd = np.array(d)*math.cos(t)+np.array([math.cos(a), 0, math.sin(a)])*math.sin(t)
        nd[1] += .25; nd /= np.linalg.norm(nd)
        branches(m, end, nd, ln*.85, r*.62, depth-1, rnd, col, leaf, sides, leaf_sub, leaf_r, spread, kids)

def params(species, seed):
    """Everything that varies between two trees of one species, drawn from the seed (same for every LOD)."""
    sp = SPECIES[species]; r = random.Random(seed*7919+13); u = lambda ab: r.uniform(*ab)
    p = dict(sp); p["H"] = u(sp["h"]); p["R"] = u(sp["rad"]); p["lean"] = (r.uniform(-.1, .1)*p["H"], r.uniform(-.1, .1)*p["H"])
    p["col"] = jit(r.choice(AUTUMN) if sp["kind"] in ("broad", "weep") and r.random() < .1 else (r.choice(sp["pal"]) if "pal" in sp else BARK), r, .08)
    p["bark"] = jit(sp["bark"], r, .12); p["asym"] = (r.uniform(-.25, .25)*p["R"], r.uniform(-.25, .25)*p["R"])
    p["aspect"] = r.uniform(.85, 1.2); p["nl"] = r.randint(*sp["lumps"]) if "lumps" in sp else 0
    p["spr"] = u(sp["spread"]) if "spread" in sp else 1.0; p["ntier"] = r.randint(*sp["tiers"]) if "tiers" in sp else 0
    p["dr"] = u(sp["droop"]) if "droop" in sp else 0; p["seed"] = r.randint(0, 99999)
    return p

FALL = {0: None, 1: dict(t=.45, drop=0.0), 2: dict(t=.95, drop=0.0), 3: dict(t=1.0, drop=.3)}   # summer, early, full, late fall
FALLCOLS = [(196,120,40),(210,170,50),(170,70,40),(184,140,44),(150,60,36)]
def tree(species, lvl, seed=7, season=0, cards=False):
    p = params(species, seed)
    ever = p["kind"] in ("conifer", "column") and species != "poplar"
    f = FALL[season] if not ever else None
    SEA.update(on=bool(f))
    if f:
        r0 = random.Random(seed*31+5); base = r0.choice(FALLCOLS)
        SEA.update(f, cols=[base, mix(base, r0.choice(FALLCOLS), .5), r0.choice(FALLCOLS)])
    rnd = random.Random(p["seed"]); m = M(); k = p["kind"]
    H, R, col, bark = p["H"], p["R"], p["col"], p["bark"]; lx, lz = p["lean"]; ax, az = p["asym"]
    ns = (4, 6, 8, 8)[lvl-1]
    if k == "conifer":
        th = H*.18; cyl(m, (0,0,0), (lx*.3, th+1, lz*.3), .22, .1, ns, bark)
        n = (2, max(3, p["ntier"]//2), p["ntier"], p["ntier"]+2)[lvl-1]
        tiers(m, lx, lz, th-.4, H, R, n, (7, 8, 10, 12)[lvl-1], col, rnd, p["dr"]*(lvl>2), .1*(lvl>2)+.06*(lvl>3), lvl == 4)
    elif k == "column":
        th = H*p["tf"]; w = R; top = H-th
        cyl(m, (0,0,0), (lx*.4, th+1, lz*.4), .15, .08, ns, bark)
        if lvl == 1: blob(m, (lx, th+top/2, lz), w*.8, top/2, w*.8, 0, col, rnd)
        elif lvl == 2: blob(m, (lx, th+top/2, lz), w, top/2, w, 1, col, rnd, .1)
        else:
            n = 4 if lvl == 3 else 8
            for i in range(n):
                f = i/(n-1); ww = w*(1-abs(f-.4)*.6)
                blob(m, (lx*(.6+.4*f)+rnd.uniform(-.2, .2), th+top*(.08+.84*f), lz+rnd.uniform(-.2, .2)), ww, top/n*1.15, ww, 1, col, rnd, .2)
            if lvl == 4:
                for i in range(8):
                    a = i*2.4; y = th+top*(.1+.8*(i/7)); e = (lx+math.cos(a)*w*.9, y+.5, lz+math.sin(a)*w*.9)
                    cyl(m, (lx, y, lz), e, .05, .03, 5, bark); blob(m, e, w*.4, w*.45, w*.4, 0, col, rnd, .2)
    elif k == "weep":
        th = H*p["tf"]; cyl(m, (0,0,0), (lx, th, lz), .3, .16, ns, bark)
        if lvl == 1: blob(m, (lx, th+R*.45, lz), R, R*.9, R, 0, col, rnd)
        else:
            nb = (0, 4, 6, 9)[lvl-1]
            blob(m, (lx, th+R*.85, lz), R*.85, R*.5, R*.85, 1, col, rnd, .15)
            for i in range(nb*3):                            # hanging curtains
                a = 6.28*i/(nb*3)+rnd.uniform(-.2, .2); rr = R*rnd.uniform(.55, 1.0); cx, cz = lx+math.cos(a)*rr, lz+math.sin(a)*rr
                blob(m, (cx, th+R*.45, cz), R*.17, R*.6, R*.17, 0 if lvl < 4 else 1, mix(col, (60, 100, 50), rnd.random()*.4), rnd, .15)
            if lvl == 4:
                for i in range(6):
                    a = i*1.05; e = (lx+math.cos(a)*R*.6, th+R*.9, lz+math.sin(a)*R*.6); cyl(m, (lx, th, lz), e, .1, .05, 6, bark)
    elif k == "dead":
        th = H*p["tf"]; cyl(m, (0,0,0), (lx, th+H*.2, lz), .2, .06, ns, bark)
        nb = (3, 5, 7, 10)[lvl-1]
        for i in range(nb):
            a = rnd.uniform(0, 6.28); y = th*rnd.uniform(.5, 1.0)+H*.15; ln = R*rnd.uniform(.7, 1.2)
            e = (lx+math.cos(a)*ln, y+ln*.8, lz+math.sin(a)*ln); cyl(m, (lx*.8, y, lz*.8), e, .1, .02, 4 if lvl < 3 else 6, bark)
            if lvl == 4:
                e2 = (e[0]+math.cos(a+.6)*ln*.5, e[1]+ln*.35, e[2]+math.sin(a+.6)*ln*.5); cyl(m, e, e2, .05, .01, 5, bark)
    else:                                                    # broadleaf: lime, oak, birch, acacia, stone pine
        th = H*p["tf"]; cr = R; ch = cr*p["ry"]*p["aspect"]
        cx, cz = lx+ax*.3, lz+az*.3; cy = th+ch*.85
        if cards and lvl >= 3:
            ts = rnd.randint(1, 3)
            if lvl == 3:
                cyl(m, (0,0,0), (lx, th+.8, lz), .24, .1, ns, bark)
                blob(m, (cx, cy, cz), cr*.7, ch*.55, cr*.7, 0, mix(col, (30, 50, 25), .35), rnd)       # dark inner core so the sprites don't show daylight
                for i in range(p["nl"]*3):
                    a = rnd.uniform(0, 6.28); d = cr*rnd.uniform(.35, 1.0)*p["spr"]**.2; y = cy+rnd.uniform(-.7, .8)*ch
                    cards_at(m, (cx+math.cos(a)*d, y, cz+math.sin(a)*d), cr*.75, 2, col, rnd, ts)
            else:
                branches(m, (0,0,0), (lx*.05, 1, lz*.05), th*.75+.4, .26, 2, rnd, bark, col, 8, -1, 0, p["spr"]*.95, 3 if p["nl"] < 6 else 4)
                blob(m, (cx, cy, cz), cr*.6, ch*.45, cr*.6, 0, mix(col, (30, 50, 25), .35), rnd)
                for i in range(p["nl"]*5):
                    a = rnd.uniform(0, 6.28); d = cr*rnd.uniform(.2, 1.05)*p["spr"]**.2; y = cy+rnd.uniform(-.8, .9)*ch
                    cards_at(m, (cx+math.cos(a)*d, y, cz+math.sin(a)*d), cr*.6, 2, col, rnd, ts)
        elif lvl == 1:
            cyl(m, (0,0,0), (lx, th, lz), .17, .12, ns, bark); blob(m, (cx, cy, cz), cr, ch, cr, 0, col, rnd)
        elif lvl == 2:
            cyl(m, (0,0,0), (lx, th+.8, lz), .22, .1, ns, bark); blob(m, (cx, cy, cz), cr, ch, cr, 1, col, rnd, .1)
        elif lvl == 3:
            cyl(m, (0,0,0), (lx, th+.8, lz), .24, .1, ns, bark)
            n = p["nl"]
            for i in range(n):
                a = i*6.28/n+rnd.uniform(-.3, .3); d = cr*.5*p["spr"]
                blob(m, (cx+math.cos(a)*d, cy+rnd.uniform(-.2, .4)*ch, cz+math.sin(a)*d), cr*.62, ch*.7, cr*.62, 1, jit(col, rnd, .05), rnd, .2)
            blob(m, (cx, cy+ch*.35, cz), cr*.6, ch*.6, cr*.6, 1, col, rnd, .2)
        else:
            nk = 3 if p["nl"] < 6 else 4
            branches(m, (0,0,0), (lx/th*0 + lx*.05, 1, lz*.05), th*.75+.4, .26, 2, rnd, bark, col, 8, 1, cr*.36*(p["spr"]**.3), p["spr"]*.95, nk)
    return m

def render(m, W=360, Hh=520, yaw=.6, ymax=15.0):
    img = np.full((Hh, W, 3), 206, np.uint8); zb = np.full((Hh, W), 1e9)
    cy, sy = math.cos(yaw), math.sin(yaw); L = np.array([.45, .8, .35]); L /= np.linalg.norm(L)
    sc = Hh*.88/ymax
    def P(p):
        x = p[0]*cy - p[2]*sy; z = p[0]*sy + p[2]*cy
        return np.array([W/2 + x*sc, Hh*.95 - p[1]*sc, z])
    for a, b, c, col in m.t:
        n = np.cross(b-a, c-a); ln = np.linalg.norm(n)
        if ln < 1e-9: continue
        n /= ln; n = np.array([n[0]*cy - n[2]*sy, n[1], n[0]*sy + n[2]*cy]) if False else n
        sh = .62 + .5*abs(n @ L)
        A, B, C = P(a), P(b), P(c)
        x0, x1 = int(max(0, min(A[0], B[0], C[0]))), int(min(W-1, max(A[0], B[0], C[0])+1))
        y0, y1 = int(max(0, min(A[1], B[1], C[1]))), int(min(Hh-1, max(A[1], B[1], C[1])+1))
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1+1)+.5, np.arange(y0, y1+1)+.5)
        d = (B[1]-C[1])*(A[0]-C[0]) + (C[0]-B[0])*(A[1]-C[1])
        if abs(d) < 1e-9: continue
        w0 = ((B[1]-C[1])*(xs-C[0]) + (C[0]-B[0])*(ys-C[1]))/d
        w1 = ((C[1]-A[1])*(xs-C[0]) + (A[0]-C[0])*(ys-C[1]))/d
        w2 = 1-w0-w1; ins = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        z = w0*A[2]+w1*B[2]+w2*C[2]; sub = zb[y0:y1+1, x0:x1+1]
        ok = ins & (z < sub); sub[ok] = z[ok]
        img[y0:y1+1, x0:x1+1][ok] = [min(255, int(v*sh)) for v in col]
    for q, ts, col in sorted(m.card, key=lambda e: -np.mean([P(v)[2] for v in e[0]])):
        Lt, At = tex(ts); n = Lt.shape[0]; Q = [P(v) for v in q]
        for tri_, uv in (((0, 1, 2), ((0, 1), (1, 1), (1, 0))), ((0, 2, 3), ((0, 1), (1, 0), (0, 0)))):
            A, B, C = (Q[i] for i in tri_); (ua, va), (ub, vb), (uc, vc) = uv
            x0, x1 = int(max(0, min(A[0], B[0], C[0]))), int(min(W-1, max(A[0], B[0], C[0])+1)); y0, y1 = int(max(0, min(A[1], B[1], C[1]))), int(min(Hh-1, max(A[1], B[1], C[1])+1))
            if x1 < x0 or y1 < y0: continue
            xs, ys = np.meshgrid(np.arange(x0, x1+1)+.5, np.arange(y0, y1+1)+.5); d = (B[1]-C[1])*(A[0]-C[0]) + (C[0]-B[0])*(A[1]-C[1])
            if abs(d) < 1e-9: continue
            w0 = ((B[1]-C[1])*(xs-C[0]) + (C[0]-B[0])*(ys-C[1]))/d; w1 = ((C[1]-A[1])*(xs-C[0]) + (A[0]-C[0])*(ys-C[1]))/d; w2 = 1-w0-w1
            ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0); z = w0*A[2]+w1*B[2]+w2*C[2]
            u = np.clip((w0*ua+w1*ub+w2*uc)*(n-1), 0, n-1).astype(int); v = np.clip((w0*va+w1*vb+w2*vc)*(n-1), 0, n-1).astype(int)
            al = At[v, u] > 128; ok = ins & al & (z < zb[y0:y1+1, x0:x1+1]+1.5)
            lt = Lt[v, u]/255.0*.9+.25; sub = zb[y0:y1+1, x0:x1+1]; sub[ok] = np.minimum(sub[ok], z[ok])
            for ch_ in range(3): img[y0:y1+1, x0:x1+1, ch_][ok] = np.clip(col[ch_]*lt[ok]*.95, 0, 255).astype(np.uint8)
    return Image.fromarray(img)

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "tree_lod.png"
    mode = sys.argv[2] if len(sys.argv) > 2 else "levels"
    W, H = 300, 440
    names = list(SPECIES)
    if mode == "levels":
        sheet = Image.new("RGB", (W*4+110, H*len(names)), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
        for r, s_ in enumerate(names):
            dr.text((6, r*H+H//2), s_, fill=(0, 0, 0))
            for l in range(1, 5):
                m = tree(s_, l); print(s_, l, "tris", m.n()); sheet.paste(render(m, W, H, ymax=16), (110+(l-1)*W, r*H))
    elif mode == "cards":                                   # per row: lumps L3, cards L3, lumps L4, cards L4
        sp_ = ["lime", "oak", "birch", "acacia"]; sheet = Image.new("RGB", (W*4+110, H*len(sp_)), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
        for r, s_ in enumerate(sp_):
            for q, (l, c) in enumerate(((3, False), (3, True), (4, False), (4, True))):
                m = tree(s_, l, 3, 0, c); sheet.paste(render(m, W, H, ymax=16), (110+q*W, r*H)); dr.text((112+q*W, r*H+4), f"{s_} L{l} {'cards' if c else 'lumps'} {m.n()} tris", fill=(0, 0, 0)); print(s_, l, c, m.n())
    elif mode == "fall":                                     # rows = species, columns = summer / early / full / late fall (L3)
        sheet = Image.new("RGB", (W*4+110, H*len(names)), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
        for r, s_ in enumerate(names):
            dr.text((6, r*H+H//2), s_, fill=(0, 0, 0))
            for q in range(4): sheet.paste(render(tree(s_, 3, 3, q), W, H, ymax=16, yaw=.6), (110+q*W, r*H))
    else:                                                    # variety: 6 seeds of each species at L3
        lvl = int(mode)
        sheet = Image.new("RGB", (W*6+110, H*len(names)), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
        for r, s_ in enumerate(names):
            dr.text((6, r*H+H//2), s_, fill=(0, 0, 0))
            for q in range(6): sheet.paste(render(tree(s_, lvl, q+1), W, H, ymax=16, yaw=q*.7), (110+q*W, r*H))
    sheet.save(out)
