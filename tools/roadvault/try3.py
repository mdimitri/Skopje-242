import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engine import *
from render import Renderer, aerial
sc1 = Scene("rb", [Arm(a, lin=1, lout=1, flare_in=1, flare_out=0, median="raised", med_w=3.0, flare_len=25, taper=15) for a in (270, 0, 90, 180)], ring=Ring(ro=20, ri=11, lanes=1, center="trees"), corner_r=9)
sc2 = Scene("t_slip", [Arm(180, lin=2, lout=2, median="raised", signal=True, slip={"R": 26}), Arm(0, lin=2, lout=2, median="raised", signal=True, slip={"R": 26}), Arm(90, lin=1, lout=1, signal=True, slip={"R": 22})])
r = Renderer(); eye, tgt = aerial(dist=170)
for sc in (sc1, sc2):
    m = build(sc); print(sc.name, len(m.P)//3)
    r.shot(m, f"/tmp/vt_{sc.name}.png", eye, tgt)
r.close()
