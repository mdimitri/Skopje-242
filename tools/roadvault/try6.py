import sys, random, os
from interchanges import *
import corridor as C
from render import Renderer, aerial
r=Renderer()
for fam in sys.argv[1:]:
    p=sample(fam,random.Random(int(os.environ.get('SD',5)))); p['seed']=5
    pl=build_family(fam,p); m=C.build_plan(pl)
    fo=pl.info.get('focus'); eye,tgt=aerial(dist=fo[2] if fo else DIST.get(fam,330),az=215,el=40)
    if fo: eye=(eye[0]+fo[0],eye[1],eye[2]+fo[1]); tgt=(fo[0],0,fo[1])
    r.shot(m,f"/tmp/u_{fam}.png",eye,tgt)
    bad=[k for k,v in pl.sim.items() if not(v['ok_radius'] and v['ok_grade'])]
    print(fam,len(m.P)//3,pl.info.get('fit_log'),'bad',bad,min(v['min_radius'] for v in pl.sim.values()))
r.close()
