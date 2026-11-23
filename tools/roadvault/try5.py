import sys, random
from interchanges import *
import corridor as C
from render import Renderer, aerial
r=Renderer()
fams=sys.argv[1:]
for fam in fams:
    p=sample(fam,random.Random(int(__import__('os').environ.get('SD',3)))); p['seed']=3
    p['kind']=fam if fam in('parclo_a','parclo_b','clover') else p.get('kind');pl=build_family(fam,p); m=C.build_plan(pl)
    fo=pl.info.get('focus'); eye,tgt=aerial(dist=fo[2] if fo else DIST.get(fam,300),az=215,el=40)
    if fo: eye=(eye[0]+fo[0],eye[1],eye[2]+fo[1]); tgt=(fo[0],0,fo[1])
    r.shot(m,f"/tmp/t_{fam}.png",eye,tgt); print(fam,len(m.P)//3,pl.info.get('fit_log'),{k:(v['min_radius'],v['max_grade_pct']) for k,v in pl.sim.items()})
r.close()
