"""Tiny copy of the projection used by tools/build_world.py (lat/lon -> local metres, +y south)."""
import math

LAT0, LON0 = 41.9973, 21.4280
M_LAT = 110574.0
M_LON = 111320.0 * math.cos(math.radians(LAT0))


def project(lat, lon):
    return ((lon - LON0) * M_LON, -(lat - LAT0) * M_LAT)

HX = 5500.0                         # half-size of the world box (east-west), same as tools/geo.py
HY = 3500.0
