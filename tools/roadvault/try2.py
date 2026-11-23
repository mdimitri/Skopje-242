import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engine import *
from render import Renderer, aerial
sc = Scene("x4", [Arm(270, lin=2, lout=2, median="raised", signal=True, pocket=1, flare_in=1, slip={"R": 15}), Arm(0, lin=1, lout=1, signal=True), Arm(90, lin=2, lout=2, median="raised", signal=True, pocket=1, flare_in=1), Arm(180, lin=1, lout=1, signal=True)])
import time; t=time.time()
m = build(sc); print(len(m.P)//3, "tris", time.time()-t)
r = Renderer(); eye, tgt = aerial()
r.shot(m, "/tmp/vt_a.png", eye, tgt); r.shot(m, "/tmp/vt_t.png", (0,230,1), (0,0,0)); r.close()
