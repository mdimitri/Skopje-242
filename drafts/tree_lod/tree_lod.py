"""Dev draft: five tree LOD meshes (1 = cheapest, 5 = most realistic) for 4 species, rendered to a comparison sheet.
python tree_lod.py out.png   (needs numpy + Pillow)"""
import math, random, sys
import numpy as np
from PIL import Image, ImageDraw

def unit(v): v = np.array(v, float); return v/(np.linalg.norm(v)+1e-9)

def anchor_cards(m, base, d, size, col, rnd, kind, n=2, shade=1.0):
    """Sprites rooted at a branch tip: the twig at the card's bottom edge starts exactly on the branch, the cluster grows along d."""
    d = unit(d); ref = np.array([0, 1., 0]) if abs(d[1]) < .9 else np.array([1., 0, 0]); r1 = unit(np.cross(d, ref)); r2 = unit(np.cross(d, r1))
    a0 = rnd.uniform(0, 3.14)
    for i in range(n):
        a = a0+math.pi*i/n; right = (r1*math.cos(a)+r2*math.sin(a))*size*.55*rnd.uniform(.85, 1.15)
        dd = unit(d+rnd.uniform(-.25, .25)*r1+rnd.uniform(-.25, .25)*r2)
        card(m, base, right, dd*size*.5*rnd.uniform(.9, 1.15), (kind, rnd.randint(0, 3)), tuple(int(c*shade) for c in jit(col, rnd, .1)))

def crown_tree(m, top, cr, ch, nl, spr, lvl, rnd, bark, col, kind, droop=0.0, low=False):
    """Imperfect crown: limbs of uneven length and angle, a heavy side, gaps and bare limbs; sprites sit on tips AND along the limbs,
    so leaves reach down into the middle of the crown instead of only capping it."""
    ns = 4; depth = 1 if lvl == 3 else 2; top = np.array(top, float)
    bias = unit([rnd.uniform(-1, 1), 0, rnd.uniform(-1, 1)]); bias_k = rnd.uniform(.05, .2)          # one side grows heavier
    def cl(p, f, d, size, shade, n=2):
        q = p+d*0                                           # (kept for readability)
        anchor_cards(m, q, d, size*rnd.uniform(.6, 1.3), col, rnd, kind, n, shade*rnd.uniform(.8, 1.0))
    def limb(p, d, ln, r, dp, bare):
        ln *= rnd.uniform(.75, 1.25); e = p+d*ln; cyl(m, p, e, r, r*.6, ns, bark)
        fo = np.linalg.norm((e-top)*[1, 1.4, 1])/(cr*1.1+1e-9)
        if not bare:
            for f in ((.25, .5, .75) if dp >= 1 else (.4, .7)):    # sprites along the limb, pointing outward-up at random angles, so the mid crown is leafy too
                if rnd.random() < .7:
                    side = unit(d+np.array([rnd.uniform(-.8, .8), rnd.uniform(-.3, .5), rnd.uniform(-.8, .8)]))
                    cl(p+(e-p)*f, f, side, cr*rnd.uniform(.22, .38), .62+.3*min(1, fo), 1 if lvl == 3 else 2)
        if dp == 0:
            if not bare and rnd.random() > .1:              # a few tips are left bare / broken
                cl(e, 1, d+np.array([0, droop, 0]), cr*.48, .75+.3*min(1, fo), 2 if lvl == 3 else 3)
            return
        for k in range(2 if dp <= 1 else 3):
            a = rnd.uniform(0, 6.28); t = rnd.uniform(.35, 1.1)
            nd = unit(d*math.cos(t)+np.array([math.cos(a), 0, math.sin(a)])*math.sin(t)+np.array([0, rnd.uniform(-.1, .3), 0])+bias*bias_k)
            limb(e, nd, ln*rnd.uniform(.55, .85), r*.62, dp-1, bare or rnd.random() < .04)
    for i in range(nl):
        a = 6.28*i/nl+rnd.uniform(-.5, .5); el = rnd.uniform(.35, 1.2) if not low else rnd.uniform(.1, .5)
        d = unit([math.cos(a)*math.cos(el)*spr*1.2, math.sin(el)+.15, math.sin(a)*math.cos(el)*spr*1.2]+bias*bias_k)
        limb(top, d, cr*rnd.uniform(.4, .72)*(1.0 if not low else 1.15), .13, depth, rnd.random() < .03)
    for i in range(rnd.randint(2, 3)):                      # leafy shoots straight off the upper trunk
        cl(top+np.array([rnd.uniform(-.4, .4), rnd.uniform(-.6, .9), rnd.uniform(-.4, .4)]), 0, unit([rnd.uniform(-1, 1), rnd.uniform(.2, .9), rnd.uniform(-1, 1)]), cr*.45, .6, 2)

LEAFKIND = {"willow": "narrow"}
def _leaf_pts(kind, ln, wd, r):
    """Outline of one leaf, base at (0,0) pointing +x, as polygon points."""
    n = 28; up, dn = [], []
    for i in range(n+1):
        x = i/n
        if kind == "ovate":   w = math.sin(math.pi*x**.75)**.9*(1.0 if x > .1 else .6+x*4)         # heart-ish base, pointed tip
        elif kind == "lobed": w = math.sin(math.pi*x)**.7*(.62+.38*math.cos(x*5.2*math.pi+.6))
        elif kind == "serrate": w = math.sin(math.pi*x**.8)*(.85+.15*(1 if (i % 2) else -1))      # saw-tooth edge
        elif kind == "narrow": w = math.sin(math.pi*x**.9)*.3
        elif kind == "round": w = math.sin(math.pi*x**.9)**.55*(1.0 if x > .12 else .5+x*4)       # near-circular, heart base (Judas tree, mulberry)
        else: w = math.sin(math.pi*x)
        up.append((x*ln, w*wd)); dn.append((x*ln, -w*wd))
    return up+dn[::-1]

def leaf_tex(kind, variant, n=192):
    """Procedural alpha foliage sprite, drawn at 2x and filtered down: (lightness 0..255, alpha 0..255). Tinted at draw time."""
    r = random.Random(hash((kind, variant)) & 0xffff); S = n*2
    L = Image.new("L", (S, S), 0); A = Image.new("L", (S, S), 0); dl, da = ImageDraw.Draw(L), ImageDraw.Draw(A)
    def rot(pts, ox, oy, a): ca, sa = math.cos(a), math.sin(a); return [(ox+ca*x-sa*y, oy+sa*x+ca*y) for x, y in pts]
    def twig(x0, y0, ang, ln, lvl):                        # recursive twig; leaves sit on the tips and along it
        x1, y1 = x0+math.cos(ang)*ln, y0+math.sin(ang)*ln
        dl.line([(x0, y0), (x1, y1)], fill=60, width=max(3, int(8-lvl*2.6))); da.line([(x0, y0), (x1, y1)], fill=255, width=max(3, int(8-lvl*2.6)))
        return x1, y1
    sz = {"palmate": (.2, .2), "palmcomp": (.22, .2), "round": (.14, .13), "ovate": (.17, .15), "lobed": (.2, .13), "serrate": (.11, .09), "narrow": (.26, .05), "pinnate": (.07, .05), "needles": (.2, .012)}[kind]
    dens = r.randint(26, 42) if kind not in ("pinnate", "needles", "palmate", "palmcomp") else r.randint(7, 12)
    curve = r.uniform(-.35, .35); ang = -math.pi/2+r.uniform(-.2, .2); x, y = S*.5, S*.97; pts = [(x, y)]
    seg = S*.82/4
    for _ in range(4):                                     # main twig, slightly bowed
        ang += curve*.3; x, y = twig(x, y, ang, seg, 0); pts.append((x, y))
    leaves = []
    for i in range(dens):
        t = r.random(); k = min(3, int(t*4)); bx, by = pts[k]; ex, ey = pts[k+1]; f = t*4-k
        px, py = bx+(ex-bx)*f, by+(ey-by)*f; side = r.choice((-1, 1)) if kind != "needles" else r.choice((-1, 1))
        la = math.atan2(ey-by, ex-bx)+side*r.uniform(.5, 1.3); ln_ = S*sz[0]*r.uniform(.75, 1.3)*(1.15-.5*t*.0)
        leaves.append((t, px, py, la, ln_))
    if kind not in ("pinnate", "needles"):
        for _ in range(r.randint(1, 2)):                    # side twigs for body
            k = r.randint(1, 3); bx, by = pts[k]; a2 = ang+r.choice((-1, 1))*r.uniform(.6, 1.1); ex, ey = twig(bx, by, a2, seg*r.uniform(.8, 1.4), 1)
            for _ in range(dens//3): leaves.append((r.random(), ex+r.uniform(-.06, .06)*S, ey+r.uniform(-.06, .06)*S, a2+r.uniform(-1, 1), S*sz[0]*r.uniform(.7, 1.2)))
    leaves.append((1, pts[-1][0], pts[-1][1], ang, S*sz[0]*1.2))                # terminal leaf
    for t, px, py, la, ln_ in sorted(leaves, key=lambda q: q[0]):
        shade = int(r.uniform(.45, 1.0)*255*(.7+.3*t))                           # lower / inner leaves darker, tips brighter
        if kind == "pinnate":                               # compound leaf: rachis with paired leaflets
            ex, ey = px+math.cos(la)*ln_*1.7, py+math.sin(la)*ln_*1.7; dl.line([(px, py), (ex, ey)], fill=70, width=3); da.line([(px, py), (ex, ey)], fill=255, width=3)
            for q in range(7):
                f = (q+1)/8
                for sd in (-1, 1):
                    c = (px+(ex-px)*f, py+(ey-py)*f); poly = rot([(0, 0), (S*.03, S*.012), (S*.06, 0), (S*.03, -S*.012)], c[0], c[1], la+sd*1.1)
                    dl.polygon(poly, fill=int(shade*r.uniform(.8, 1.0))); da.polygon(poly, fill=255)
            continue
        if kind == "needles":                               # a spray of needles fanning out of the twig
            for q in range(10):
                a3 = la+r.uniform(-.8, .8); l3 = ln_*r.uniform(.5, 1.0); ex, ey = px+math.cos(a3)*l3, py+math.sin(a3)*l3
                dl.line([(px, py), (ex, ey)], fill=int(shade*r.uniform(.7, 1)), width=3); da.line([(px, py), (ex, ey)], fill=255, width=3)
            continue
        if kind in ("palmate", "palmcomp"):                  # plane / maple: 5 pointed lobes from one base; chestnut: 7 long leaflets
            nl = 5 if kind == "palmate" else 7
            for q in range(nl):
                a4 = la+(q-(nl-1)/2)*(.62 if kind == "palmate" else .42); l4 = ln_*(1.0-.22*abs(q-(nl-1)/2)/((nl-1)/2)*(1 if kind == "palmate" else .5))
                poly = rot(_leaf_pts("serrate" if kind == "palmate" else "ovate", l4, l4*(.26 if kind == "palmate" else .3), r), px, py, a4)
                dl.polygon(poly, fill=int(shade*r.uniform(.85, 1.0))); da.polygon(poly, fill=255); dl.line(rot([(0, 0), (l4*.9, 0)], px, py, a4), fill=min(255, shade+55), width=2)
            continue
        poly = rot(_leaf_pts(kind, ln_, ln_*sz[1]/sz[0]*r.uniform(.85, 1.15), r), px, py, la)
        dl.polygon(poly, fill=shade); da.polygon(poly, fill=255)
        mid = rot([(0, 0), (ln_*.92, 0)], px, py, la)                             # midrib and side veins, lighter than the blade
        dl.line(mid, fill=min(255, shade+60), width=2)
        for q in range(1, 5):
            vx = ln_*q*.2
            for for_ in (-1, 1):
                dl.line(rot([(vx, 0), (vx+ln_*.14, for_*ln_*sz[1]/sz[0]*.55)], px, py, la), fill=min(255, shade+35), width=1)
    Li, Ai = L.resize((n, n), Image.LANCZOS), A.resize((n, n), Image.LANCZOS)
    return np.array(Li, np.uint8), np.array(Ai, np.uint8)
_TEX = {}
def tex(key):
    if key not in _TEX: _TEX[key] = leaf_tex(*key)
    return _TEX[key]

def card(m, c, right, up, t, col):
    """One alpha-tested leaf-cluster quad = 2 triangles"""
    c, right, up = np.array(c, float), np.array(right, float), np.array(up, float)
    q = [c-right, c+right, c+right+up*2, c-right+up*2]
    m.card.append((q, t, col)); m.ncard += 2

def cards_at(m, c, size, n, col, rnd, kind, flat=False):
    for i in range(n):
        a = math.pi*i/n+rnd.uniform(-.3, .3); tilt = rnd.uniform(-.5, .5)
        right = np.array([math.cos(a), 0, math.sin(a)])*size*.5; up = np.array([math.sin(a)*tilt*.5, 1, -math.cos(a)*tilt*.5]); up = up/np.linalg.norm(up)*size*.5
        if flat: up = np.array([0, 0, 0.]) + np.array([-math.sin(a), 0, math.cos(a)])*size*.5
        card(m, np.array(c)-up*(0 if flat else 1)*1.0, right*rnd.uniform(.8, 1.2), up*rnd.uniform(.8, 1.2), (kind, rnd.randint(0, 3)), jit(col, rnd, .12))

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
SPECIES = {   # Skopje / Balkan street, park, riverside and hill trees
 "spruce":   dict(kind="conifer", bark=BARK, pal=[(46,92,56),(40,84,60),(56,100,60)], h=(8,14), rad=(2.2,3.2), tiers=(8,11), droop=(.1,.3)),
 "blackpine":dict(kind="conifer", bark=(76,58,46), pal=[(38,78,50),(46,88,52)], h=(9,16), rad=(2.4,3.4), tiers=(6,9), droop=(0,.1)),
 "cedar":    dict(kind="conifer", bark=(90,70,56), pal=[(52,98,80),(60,106,88)], h=(9,15), rad=(3.2,4.4), tiers=(5,7), droop=(.3,.5)),
 "cypress":  dict(kind="column", bark=(100,80,60), pal=[(40,86,52),(48,96,56)], h=(8,14), rad=(.8,1.3), tf=.08),
 "poplar":   dict(kind="column", bark=BARK, pal=[(70,130,58),(84,140,62)], h=(11,18), rad=(1.1,1.7), tf=.2),
 "plane":    dict(kind="broad", bark=(150,142,122), pal=[(98,142,60),(108,150,64)], h=(12,20), rad=(4.5,6.2), ry=.62, tf=.32, lumps=(7,10), spread=(1.0,1.3), fall=[(200,150,50),(176,120,40),(150,100,40)], leaf="palmate"),
 "linden":   dict(kind="broad", bark=(90,76,62), pal=[(80,134,58),(90,142,62)], h=(10,16), rad=(3.2,4.6), ry=.85, tf=.3, lumps=(6,8), spread=(.8,1.1), fall=[(210,180,60),(190,150,50)], leaf="ovate"),
 "chestnut": dict(kind="broad", bark=(84,66,52), pal=[(52,104,48),(60,112,50)], h=(10,15), rad=(3.6,5), ry=.8, tf=.3, lumps=(6,8), spread=(.9,1.1), fall=[(190,110,40),(160,80,36)], leaf="palmcomp"),
 "locust":   dict(kind="broad", bark=(70,58,50), pal=[(116,150,70),(126,158,76)], h=(10,16), rad=(3,4.2), ry=.7, tf=.4, lumps=(5,7), spread=(.9,1.2), fall=[(220,200,70),(200,170,50)], leaf="pinnate"),
 "ailanthus":dict(kind="broad", bark=(110,100,88), pal=[(96,138,62),(106,146,66)], h=(8,14), rad=(3,4.4), ry=.7, tf=.36, lumps=(5,7), spread=(1.0,1.3), fall=[(200,170,60)], leaf="pinnate"),
 "oak":      dict(kind="broad", bark=(84,66,50), pal=[(72,118,52),(86,126,50),(96,120,48)], h=(8,13), rad=(4,5.6), ry=.62, tf=.26, lumps=(6,9), spread=(1.0,1.3), fall=[(170,110,40),(150,90,40)], leaf="lobed"),
 "walnut":   dict(kind="broad", bark=(96,88,78), pal=[(84,128,56),(92,136,58)], h=(9,14), rad=(4,5.5), ry=.75, tf=.3, lumps=(6,8), spread=(1.0,1.2), fall=[(200,170,60),(170,130,50)], leaf="pinnate"),
 "maple":    dict(kind="broad", bark=(92,80,68), pal=[(90,140,56),(100,148,60)], h=(8,13), rad=(3,4.2), ry=.8, tf=.34, lumps=(5,7), spread=(.8,1.1), fall=[(196,60,36),(210,110,40),(220,170,50)], leaf="palmate"),
 "judas":    dict(kind="broad", bark=(72,56,48), pal=[(86,130,70),(94,138,74)], h=(5,8), rad=(2.4,3.4), ry=.8, tf=.3, lumps=(4,6), spread=(.9,1.2), fall=[(220,190,70),(200,150,60)], leaf="round"),
 "mulberry": dict(kind="broad", bark=(98,84,70), pal=[(100,144,60),(110,152,64)], h=(6,10), rad=(3,4.2), ry=.85, tf=.3, lumps=(5,7), spread=(.8,1.1), fall=[(220,200,70)], leaf="round"),
 "birch":    dict(kind="broad", bark=(228,228,220), pal=[(96,150,64),(110,160,70)], h=(8,12), rad=(2.4,3.3), ry=.9, tf=.38, lumps=(4,6), spread=(.7,1.0), fall=[(220,190,60)], leaf="serrate"),
 "willow":   dict(kind="weep", bark=(86,72,54), pal=[(120,150,70),(132,158,76)], h=(9,13), rad=(3.2,4.2), tf=.42, fall=[(200,180,70)]),
 "oldpine":  dict(kind="broad", bark=(110,76,52), pal=[(58,104,56),(66,112,58)], h=(9,14), rad=(3.5,4.8), ry=.28, tf=.68, lumps=(5,7), spread=(1.0,1.4), leaf="needles"),
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
    p["col"] = jit(r.choice(sp.get("fall", AUTUMN)) if sp["kind"] in ("broad", "weep") and r.random() < .1 else (r.choice(sp["pal"]) if "pal" in sp else BARK), r, .08)
    p["bark"] = jit(sp["bark"], r, .12); p["asym"] = (r.uniform(-.25, .25)*p["R"], r.uniform(-.25, .25)*p["R"])
    p["aspect"] = r.uniform(.85, 1.2); p["nl"] = r.randint(*sp["lumps"]) if "lumps" in sp else 0
    p["spr"] = u(sp["spread"]) if "spread" in sp else 1.0; p["ntier"] = r.randint(*sp["tiers"]) if "tiers" in sp else 0
    p["dr"] = u(sp["droop"]) if "droop" in sp else 0; p["seed"] = r.randint(0, 99999)
    return p

FALL = {0: None, 1: dict(t=.45, drop=0.0), 2: dict(t=.95, drop=0.0), 3: dict(t=1.0, drop=.3)}   # summer, early, full, late fall
FALLCOLS = [(196,120,40),(210,170,50),(170,70,40),(184,140,44),(150,60,36)]
def tree(species, lvl, seed=7, season=0, cards=True):
    p = params(species, seed)
    ever = p["kind"] in ("conifer", "column") and species not in ("poplar",)
    f = FALL[season] if not ever else None
    SEA.update(on=bool(f))
    if f:
        r0 = random.Random(seed*31+5); fc = p.get('fall') or FALLCOLS; base = r0.choice(fc)
        SEA.update(f, cols=[base, mix(base, r0.choice(fc), .5), r0.choice(fc)])
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
        elif cards and lvl >= 3:
            top = np.array((lx, th, lz)); cyl(m, (0,0,0), top, .3, .16, ns, bark)
            for i in range(8 if lvl == 3 else 10):            # limbs arch up and out, then curtains of narrow-leaf sprites hang from them
                a = 6.28*i/(8 if lvl == 3 else 10)+rnd.uniform(-.2, .2); d = unit([math.cos(a)*.9, 1.0, math.sin(a)*.9]); e = top+d*R*.8; e2 = e+unit([math.cos(a), .15, math.sin(a)])*R*.55
                cyl(m, top, e, .14, .09, ns, bark); cyl(m, e, e2, .09, .05, ns, bark)
                for q in range(2 if lvl == 3 else 3):
                    f = (q+1)/(2 if lvl == 3 else 3); pt = e+(e2-e)*f; anchor_cards(m, pt, (math.cos(a)*.15, -1, math.sin(a)*.15), R*1.1, col, rnd, "narrow", 2, .7+.3*f)
        elif lvl == 2:
            blob(m, (lx, th+R*.85, lz), R*.85, R*.5, R*.85, 1, col, rnd, .15)
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
            top = (lx, th*.85+.3, lz); cyl(m, (0,0,0), top, .25, .13, ns, bark)
            crown_tree(m, top, cr, ch, p["nl"], p["spr"], lvl, rnd, bark, col, p.get('leaf', 'ovate'), low=(species == "oldpine"))
        elif lvl == 1:
            cyl(m, (0,0,0), (lx, th, lz), .17, .12, ns, bark); blob(m, (cx, cy, cz), cr*.88, ch*.88, cr*.88, 0, col, rnd)
        elif lvl == 2:
            cyl(m, (0,0,0), (lx, th+.8, lz), .22, .1, ns, bark); blob(m, (cx, cy, cz), cr*.9, ch*.9, cr*.9, 1, col, rnd, .12)
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
        sp_ = ["plane", "linden", "chestnut", "locust", "maple", "judas"]; sheet = Image.new("RGB", (W*4+110, H*len(sp_)), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
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
