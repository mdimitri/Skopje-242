"""Move a road-overlapping footprint intact when nearby space allows it."""
import math

import numpy as np
from PIL import Image, ImageDraw
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree


class BuildingMoves:
    def __init__(self, buildings, road_grid, water, hx, hy, cell):
        self.buildings, self.road_grid, self.water = buildings, road_grid, water
        self.hx, self.hy, self.cell = hx, hy, cell
        self.shapes = [Polygon(b["ring"]) for b in buildings]
        self.tree = STRtree(self.shapes)
        self.moved = {}

    def _over_water(self, shape):
        x0, y0, x1, y1 = shape.bounds
        ix0, iy0 = int((x0 + self.hx) / self.cell), int((y0 + self.hy) / self.cell)
        ix1, iy1 = int((x1 + self.hx) / self.cell) + 1, int((y1 + self.hy) / self.cell) + 1
        water = self.water[iy0:iy1, ix0:ix1]
        if not water.any():
            return False
        mask = Image.new("1", (water.shape[1], water.shape[0]))
        draw = ImageDraw.Draw(mask)
        def pixels(coords):
            return [((x + self.hx) / self.cell - ix0, (y + self.hy) / self.cell - iy0) for x, y in coords]
        draw.polygon(pixels(shape.exterior.coords), fill=1)
        for hole in shape.interiors:
            draw.polygon(pixels(hole.coords), fill=0)
        return bool(np.any(np.asarray(mask) & water))

    def move(self, index):
        original = self.shapes[index]
        if not original.is_valid or original.is_empty:
            return None
        x0, y0, x1, y1 = original.bounds
        reach = max(x1 - x0, y1 - y0) * 0.5
        if reach < 0.5:
            return None
        segments = set()
        for gx in range(math.floor((x0 - reach) / 30), math.floor((x1 + reach) / 30) + 1):
            for gy in range(math.floor((y0 - reach) / 30), math.floor((y1 + reach) / 30) + 1):
                segments.update(self.road_grid.get((gx, gy), ()))
        if not segments:
            return None
        corridor = unary_union([LineString([(a, b), (c, d)]).buffer(r, cap_style="round")
                                for a, b, c, d, r in segments])
        if not original.intersects(corridor):
            return None
        dirs = [(math.cos(i * math.pi / 8), math.sin(i * math.pi / 8)) for i in range(16)]
        coords = list(original.exterior.coords)
        limits = [(max(x * dx + y * dy for x, y in coords) - min(x * dx + y * dy for x, y in coords)) / 2
                  for dx, dy in dirs]
        for step in range(1, math.ceil(max(limits) * 2) + 1):
            distance = step * 0.5
            for (dx, dy), limit in zip(dirs, limits):
                if distance > limit + 1e-9:
                    continue
                candidate = translate(original, dx * distance, dy * distance)
                if not box(-self.hx, -self.hy, self.hx, self.hy).covers(candidate) or candidate.intersects(corridor):
                    continue
                if self._over_water(candidate):
                    continue
                nearby = set(self.tree.query(candidate)) | set(self.moved)
                if any(i != index and candidate.intersection(self.moved.get(i, self.shapes[i])).area > 0.05
                       for i in nearby):
                    continue
                self.moved[index] = candidate
                return dx * distance, dy * distance
        return None
