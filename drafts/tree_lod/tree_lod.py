"""Dev draft: five tree LOD meshes (1 = cheapest, 5 = most realistic) for 4 species, rendered to a comparison sheet.
python tree_lod.py out.png   (needs numpy + Pillow)"""
import math, random, sys
import numpy as np
from PIL import Image, ImageDraw

class M:
    def __init__(s): s.t = []          # (p0,p1,p2,rgb) lit later
    def tri(s, a, b, c, col): s.t.append((np.array(a, float), np.array(b, float), np.array(c, float), col))
    def n(s): return len(s.t)

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

def blob(m, c, rx, ry, rz, sub, col, rnd, noise=0.0, flat=0.0):
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

BARK = (92, 70, 50); GREEN = (84, 140, 62); PINE = (46, 92, 56); BIRCHB = (228, 228, 220)

def branches(m, base, d, ln, r, depth, rnd, col, leaf, sides, leaf_sub, leaf_r, spread=0.7, kids=3):
    end = np.array(base)+np.array(d)*ln
    cyl(m, base, end, r, r*.62, sides, col)
    if depth == 0:
        if leaf_sub >= 0: blob(m, end, leaf_r, leaf_r*.8, leaf_r, leaf_sub, leaf, rnd, .22)
        return
    for k in range(kids):
        a = rnd.uniform(0, 6.28); t = spread*rnd.uniform(.7, 1.3)
        nd = np.array(d)*math.cos(t)+np.array([math.cos(a), 0, math.sin(a)])*math.sin(t)
        nd[1] += .25; nd /= np.linalg.norm(nd)
        branches(m, end, nd, ln*.85, r*.62, depth-1, rnd, col, leaf, sides, leaf_sub, leaf_r, spread, kids)

def tree(species, lvl, seed=7):
    rnd = random.Random(seed); m = M()
    H = {"pine": 10, "round": 8.5, "poplar": 13, "birch": 9}[species]
    if species == "pine":
        th = 2.2
        cyl(m, (0,0,0), (0,th+1,0), .22, .1, (4, 6, 8, 8, 10)[lvl-1], BARK)
        if lvl == 1:   tiers(m, 0, 0, th-.4, H, 2.6, 2, 7, PINE, rnd)
        elif lvl == 2: tiers(m, 0, 0, th-.4, H, 2.7, 4, 8, PINE, rnd)
        elif lvl == 3: tiers(m, 0, 0, th-.4, H, 2.8, 6, 10, PINE, rnd, .12, .08)
        elif lvl == 4: tiers(m, 0, 0, th-.4, H, 2.9, 9, 12, PINE, rnd, .22, .15, 1)
        else:
            tiers(m, 0, 0, th-.4, H, 2.9, 12, 16, PINE, rnd, .3, .2, 1)
            for i in range(110):                           # needle tufts hanging off the branch tips
                f = rnd.random(); a = rnd.uniform(0, 6.28); r = 2.9*(1-f*.8)*.95
                blob(m, (math.cos(a)*r, th-.4+(H-th)*f*.8-.35, math.sin(a)*r), .32, .22, .32, 0, tuple(int(c*rnd.uniform(.85, 1.15)) for c in PINE), rnd, .3)
    elif species == "poplar":
        th = 2.6; col = (70, 130, 58)
        cyl(m, (0,0,0), (0,th+1,0), .17, .08, (4, 6, 8, 8, 10)[lvl-1], BARK)
        if lvl == 1:   blob(m, (0, 7, 0), .9, 5.5, .9, 0, col, rnd)
        elif lvl == 2: blob(m, (0, 7, 0), 1.2, 5.6, 1.2, 1, col, rnd, .1)
        elif lvl == 3:
            for k in range(4): blob(m, (0, 3.5+k*2.4, 0), 1.5-abs(k-1.5)*.2, 2.0, 1.5-abs(k-1.5)*.2, 1, col, rnd, .18)
        elif lvl == 4:
            for k in range(7): blob(m, (rnd.uniform(-.2, .2), 3.2+k*1.35, rnd.uniform(-.2, .2)), 1.45-abs(k-3)*.12, 1.5, 1.45-abs(k-3)*.12, 1, col, rnd, .22)
        else:
            for k in range(14):
                for j in range(3):
                    a = rnd.uniform(0, 6.28); r = rnd.uniform(.3, .9)*(1.1-abs(k-6)*.05)
                    blob(m, (math.cos(a)*r, 3.0+k*.72, math.sin(a)*r), .85, .9, .85, 1, tuple(int(c*rnd.uniform(.85, 1.15)) for c in col), rnd, .3)
    else:
        birch = species == "birch"; bark = BIRCHB if birch else BARK; col = (96, 150, 64) if birch else GREEN
        th = 3.0 if birch else 2.6; cr = 3.2 if birch else 4.0
        if lvl == 1:
            cyl(m, (0,0,0), (0,th,0), .16, .12, 4, bark); blob(m, (0, th+cr*.55, 0), cr, cr*.8, cr, 0, col, rnd)
        elif lvl == 2:
            cyl(m, (0,0,0), (0,th+.8,0), .2, .1, 6, bark); blob(m, (0, th+cr*.6, 0), cr, cr*.85, cr, 1, col, rnd, .1)
        elif lvl == 3:
            cyl(m, (0,0,0), (0,th+1,0), .22, .1, 8, bark)
            for k in range(5):
                a = k*1.26; blob(m, (math.cos(a)*cr*.5, th+cr*.55+rnd.uniform(-.3, .5), math.sin(a)*cr*.5), cr*.62, cr*.55, cr*.62, 1, col, rnd, .2)
            blob(m, (0, th+cr*.9, 0), cr*.65, cr*.55, cr*.65, 1, col, rnd, .2)
        elif lvl == 4:
            branches(m, (0,0,0), (0,1,0), th+.6, .24, 1, rnd, bark, col, 8, 1, cr*.5, 1.05, 4)
        else:
            branches(m, (0,0,0), (0,1,0), th+.5, .26, 3, rnd, bark, col, 8, 1, cr*.3, 1.0, 3)
            for i in range(26):
                a = rnd.uniform(0, 6.28); r = rnd.uniform(.2, .95)*cr*.85
                blob(m, (math.cos(a)*r, th+cr*.35+rnd.uniform(0, cr*.85), math.sin(a)*r), cr*.24, cr*.2, cr*.24, 1, tuple(int(c*rnd.uniform(.85, 1.15)) for c in col), rnd, .3)
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
    return Image.fromarray(img)

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "tree_lod.png"
    sp = ["pine", "round", "poplar", "birch"]; W, H = 360, 520
    sheet = Image.new("RGB", (W*5+110, H*4+40), (206, 206, 206)); dr = ImageDraw.Draw(sheet)
    for r, s in enumerate(sp):
        dr.text((6, 40+r*H+H//2), s, fill=(0, 0, 0))
        for l in range(1, 6):
            m = tree(s, l); print(s, l, "tris", m.n())
            sheet.paste(render(m, W, H), (110+(l-1)*W, 40+r*H))
            dr.text((110+(l-1)*W+8, 8+(0 if r == 0 else 0)), f"L{l}", fill=(0, 0, 0)) if r == 0 else None
    sheet.save(out)
