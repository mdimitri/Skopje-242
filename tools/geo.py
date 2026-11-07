"""Shared geo constants: the world box around Skopje centre and the local projection.

The box is 11 km (east-west) x 7 km (north-south): the original 5 x 5 km around the centre plus 3 km to the east and
west and 1 km to the north and south."""
import math

LAT0, LON0 = 41.9973, 21.4280      # Stone Bridge / Macedonia Square
HX = 6000.0                        # half-size east-west in metres
HY = 4000.0                        # half-size north-south in metres
HALF = HX                          # (kept for old callers: the longest half-extent)
M_LAT = 110574.0
M_LON = 111320.0 * math.cos(math.radians(LAT0))


def project(lat, lon):
    """lat/lon -> local metres. +x east, +y SOUTH (screen convention), origin = city centre."""
    return ((lon - LON0) * M_LON, -(lat - LAT0) * M_LAT)


def bbox():
    """(south, west, north, east) of the world box."""
    dlat = HY / M_LAT
    dlon = HX / M_LON
    return (LAT0 - dlat, LON0 - dlon, LAT0 + dlat, LON0 + dlon)
