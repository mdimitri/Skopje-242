import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engine import *
import grade
from render import Renderer, aerial
sc1 = Scene("over", [Arm(180, lin=2, lout=2, median="raised", zebra=None), Arm(0, lin=2, lout=2, median="raised", zebra=None)], extra=[grade.ribbon(90, "over", lanes=2, median=2.0)])
sc2 = Scene("under", [Arm(180, lin=2, lout=2, median="raised", zebra=None), Arm(0, lin=2, lout=2, median="raised", zebra=None)], extra=[grade.ribbon(90, "under", lanes=2, median=2.0, h=5.6)])
r = Renderer(); eye, tgt = aerial(dist=170, az=215)
for sc in (sc1, sc2):
    m = build(sc); print(sc.name, len(m.P)//3)
    r.shot(m, f"/tmp/vt_{sc.name}.png", eye, tgt)
r.close()
