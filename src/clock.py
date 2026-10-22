"""Game clock: time of day, rush-hour traffic and pavement-crowd density, and how dark it is."""

# (hour, factor) control points, linearly interpolated, wrapping at 24 h
_TRAFFIC = [(0, 0.22), (4, 0.15), (5.5, 0.4), (7, 1.0), (8, 1.65), (9.3, 1.2), (11, 0.85), (13, 0.95), (15, 1.0),
            (16.3, 1.35), (17.5, 1.7), (19, 1.0), (21, 0.65), (23, 0.35), (24, 0.22)]
_PEDS = [(0, 0.18), (5, 0.1), (6.5, 0.4), (8, 1.1), (10, 0.85), (12, 1.2), (13.5, 1.3), (15, 0.9), (17, 1.3),
         (18.5, 1.75), (20.5, 1.6), (22, 0.8), (23.5, 0.3), (24, 0.18)]
_DARK = [(0, 1.0), (5, 1.0), (6.5, 0.45), (7.5, 0.0), (17.5, 0.0), (18.5, 0.3), (20, 0.85), (21, 1.0), (24, 1.0)]
EMERGENCY = (47, 48, 49)                         # police, ambulance, fire engine (vehicles.NAMES)


def _lerp(table, h):
    h %= 24.0
    for (h0, v0), (h1, v1) in zip(table, table[1:]):
        if h0 <= h <= h1:
            return v0 + (v1 - v0) * (h - h0) / (h1 - h0 or 1.0)
    return table[-1][1]


class GameClock:
    SECONDS_PER_HOUR = 55.0                      # a whole day is 22 real minutes

    def __init__(self, hour=17.0):
        self.hour = hour % 24.0
        self.speed = 1.0
        self.minutes = 0.0                       # in-game minutes since the start (never wraps): ages decals

    def update(self, dt):
        self.hour = (self.hour + dt * self.speed / self.SECONDS_PER_HOUR) % 24.0
        self.minutes += dt * self.speed / self.SECONDS_PER_HOUR * 60.0

    def shift(self, hours):
        self.hour = (self.hour + hours) % 24.0
        self.minutes += hours * 60.0

    @property
    def traffic(self):
        return _lerp(_TRAFFIC, self.hour)

    @property
    def peds(self):
        return _lerp(_PEDS, self.hour)

    @property
    def dark(self):
        return _lerp(_DARK, self.hour)

    @property
    def rush(self):
        return (7.0 <= self.hour < 9.5) or (16.0 <= self.hour < 18.8)

    def label(self):
        h = int(self.hour)
        m = int((self.hour - h) * 60)
        return f"{h:02d}:{m:02d}"

    def phase(self):
        """Coarse phase for one-off banners."""
        h = self.hour
        if 7 <= h < 9.5:
            return "rush_am"
        if 16 <= h < 18.8:
            return "rush_pm"
        if h >= 21 or h < 5:
            return "night"
        return "day"
