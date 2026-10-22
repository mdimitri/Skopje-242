"""Generate a fake Overpass-format dataset (street grid, river, parks, buildings).

Used as an offline fallback / test fixture:  data/osm_demo/*.json
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import LAT0, LON0, M_LAT, M_LON

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "osm_demo")


def ll(x, y):
    return {"lat": LAT0 - y / M_LAT, "lon": LON0 + x / M_LON}


class Gen:
    def __init__(self, seed=7):
        self.r = random.Random(seed)
        self.nid = 1
        self.wid = 1
        self.nodes = {}
        self.roads, self.buildings, self.areas, self.pois = [], [], [], []

    def node(self, x, y):
        key = (round(x, 1), round(y, 1))
        if key not in self.nodes:
            self.nodes[key] = self.nid
            self.nid += 1
        return self.nodes[key]

    def way(self, pts, tags, dest, close=False):
        pts = list(pts)
        if close:
            pts.append(pts[0])
        self.wid += 1
        dest.append({"type": "way", "id": self.wid, "tags": tags,
                     "nodes": [self.node(*p) for p in pts], "geometry": [ll(*p) for p in pts]})

    def build(self):
        r = self.r
        xs, ys = [-2600.0], [-2600.0]
        while xs[-1] < 2600:
            xs.append(xs[-1] + r.uniform(85, 150))
        while ys[-1] < 2600:
            ys.append(ys[-1] + r.uniform(85, 150))
        river_y = lambda x: 420 + 60 * math.sin(x / 600.0) + 25 * math.sin(x / 170.0)
        # river polygon
        top = [(x, river_y(x) - 35) for x in range(-2700, 2701, 100)]
        bot = [(x, river_y(x) + 35) for x in range(2700, -2701, -100)]
        self.way(top + bot, {"natural": "water", "water": "river"}, self.areas, close=True)
        self.way([(x, river_y(x)) for x in range(-2700, 2701, 100)], {"waterway": "river"}, self.areas)
        bridge_cols = {round(len(xs) * f) for f in (0.3, 0.5, 0.7)}
        bridged = set()
        # streets
        for j, y in enumerate(ys):
            cls = "primary" if j % 9 == 4 else "secondary" if j % 4 == 0 else "residential"
            for i in range(len(xs) - 1):
                self.way([(xs[i], y), (xs[i + 1], y)], {"highway": cls, "name": f"E{j}"}, self.roads)
        for i, x in enumerate(xs):
            cls = "primary" if i % 9 == 4 else "secondary" if i % 4 == 0 else "residential"
            for j in range(len(ys) - 1):
                y0, y1 = ys[j], ys[j + 1]
                ym = river_y(x)
                crosses = y0 < ym < y1 or abs(y0 - ym) < 72 or abs(y1 - ym) < 72
                if crosses:
                    if (i in bridge_cols or i % 9 == 4) and i not in bridged:
                        bridged.add(i)
                        self.way([(x, y0), (x, ym - 70), ] if y0 < ym - 70 else [(x, y0), (x, y0 + .1)],
                                 {"highway": cls}, self.roads)
                        self.way([(x, ym - 70), (x, ym + 70)], {"highway": cls, "bridge": "yes", "layer": "1"}, self.roads)
                        self.way([(x, ym + 70), (x, y1)] if y1 > ym + 70 else [(x, y1), (x, y1 + .1)],
                                 {"highway": cls}, self.roads)
                        # steps from the bridge head down to the riverside promenade
                        for sg in (-1, 1):
                            self.way([(x, ym + 70 * sg), (x + 3, river_y(x + 3) + 40 * sg)], {"highway": "footway"}, self.roads)
                    continue
                self.way([(x, y0), (x, y1)], {"highway": cls}, self.roads)
        # riverside promenades on both banks: they pass UNDER the bridges
        for sg in (-1, 1):
            pp = []
            for xq in range(-2700, 2701, 50):
                pp.append((xq, river_y(xq) + 40 * sg))
                for bc in bridge_cols:
                    if xs[bc] - 50 < xq <= xs[bc] and xq + 50 > xs[bc]:
                        pp.append((xs[bc] + 3, river_y(xs[bc] + 3) + 40 * sg))
            pp.sort(key=lambda q: q[0])
            self.way(pp, {"highway": "footway", "name": "Quay"}, self.roads)
        # a footbridge over a street (second level: you can fall from it onto the street)
        fy = ys[11]
        fx = (xs[14] + xs[15]) / 2
        self.way([(fx, fy - 95), (fx, fy - 45)], {"highway": "footway"}, self.roads)
        self.way([(fx, fy - 45), (fx, fy + 45)], {"highway": "footway", "bridge": "yes", "layer": "1"}, self.roads)
        self.way([(fx, fy + 45), (fx, fy + 95)], {"highway": "footway"}, self.roads)
        # diagonal avenue and a footpath park route
        self.way([(-2600, -2000), (-1000, -600), (0, 0), (1200, 900), (2600, 1900)], {"highway": "tertiary"}, self.roads)
        self.way([(-60, -60), (60, -60), (60, 60), (-60, 60)], {"highway": "pedestrian", "area": "yes"}, self.roads, close=True)
        # blocks
        for i in range(len(xs) - 1):
            for j in range(len(ys) - 1):
                x0, x1, y0, y1 = xs[i] + 9, xs[i + 1] - 9, ys[j] + 9, ys[j + 1] - 9
                cy = (y0 + y1) / 2
                if abs(cy - river_y((x0 + x1) / 2)) < 90 or abs((x0 + x1) / 2 - (xs[14] + xs[15]) / 2) < 20 and abs(cy - ys[11]) < 120 or abs((x0 + x1) / 2) < 70 and abs(cy) < 70:
                    continue
                if abs(cy - 0) < 40 and abs((x0 + x1) / 2) < 120:
                    continue
                roll = r.random()
                if roll < 0.10:
                    self.way([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], {"leisure": "park"}, self.areas, close=True)
                    for _ in range(r.randint(4, 12)):
                        p = self.node(r.uniform(x0 + 5, x1 - 5), r.uniform(y0 + 5, y1 - 5))
                        self.pois.append({"type": "node", "id": p, "tags": {"natural": "tree"}, **ll(*[k for k, v in self.nodes.items() if v == p][0])})
                    continue
                if roll < 0.14:
                    self.way([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], {"landuse": "industrial"}, self.areas, close=True)
                nx, ny = r.randint(1, 3), r.randint(1, 2)
                for a in range(nx):
                    for b in range(ny):
                        bx0 = x0 + (x1 - x0) * a / nx + 3
                        bx1 = x0 + (x1 - x0) * (a + 1) / nx - 3
                        by0 = y0 + (y1 - y0) * b / ny + 3
                        by1 = y0 + (y1 - y0) * (b + 1) / ny - 3
                        if r.random() < 0.15:
                            continue
                        tags = {"building": r.choice(["yes", "apartments", "house", "commercial", "yes"])}
                        if r.random() < 0.4:
                            tags["building:levels"] = str(r.randint(2, 10))
                        self.way([(bx0, by0), (bx1, by0), (bx1, by1), (bx0, by1)], tags, self.buildings, close=True)
        # lamps
        for k in range(400):
            x, y = r.uniform(-2400, 2400), r.choice(ys)
            n = self.node(x, y)
            self.pois.append({"type": "node", "id": 10**7 + k, "tags": {"highway": "street_lamp"}, **ll(x, y)})

    def dump(self):
        os.makedirs(OUT, exist_ok=True)
        for name, els in (("roads", self.roads), ("buildings", self.buildings), ("areas", self.areas), ("pois", self.pois)):
            with open(os.path.join(OUT, name + ".json"), "w") as f:
                json.dump({"elements": els}, f)
        import terrain
        from geo import HX, HY
        T = terrain.synthetic(HX, HY)
        terrain.save(T, os.path.join(OUT, "terrain.npy"))
        print("[demo] wrote", OUT, len(self.roads), "roads", len(self.buildings), "buildings")


if __name__ == "__main__":
    g = Gen()
    g.build()
    g.dump()
