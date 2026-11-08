"""User settings, saved to settings.json next to run.bat."""
from texts import TXT
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "settings.json")

RESOLUTIONS = sorted({(w, h) for w, h in [
    (1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160), (960, 540),          # 16:9
    (1280, 800), (1440, 900), (1680, 1050), (1920, 1200), (2560, 1600),                                   # 16:10
    (1024, 768), (1280, 960), (1600, 1200),                                                               # 4:3
    (2560, 1080), (3440, 1440),                                                                           # 21:9
    (1280, 1024)]})                                                                                       # 5:4, sorted by width then height


def res_label(w, h):
    from math import gcd
    g = gcd(w, h)
    a, b = w // g, h // g
    a, b = {(8, 5): (16, 10), (64, 27): (21, 9), (43, 18): (21, 9), (683, 384): (16, 9), (85, 48): (16, 9)}.get((a, b), (a, b))
    return f"{w} x {h}  ({a}:{b})"


SCALE = ["Блиски соседи (остри пиксели)", "Мазно (билинеарно)"]
AA = ["Исклучено", "MSAA 4x", "FXAA", "MSAA 4x + FXAA"]
DETAIL = [TXT("settings.0001"), TXT("settings.0002"), TXT("settings.0003")]
TIME_SPEEDS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
DENSITY = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
MAP_SOURCES = [TXT("settings.0004"), TXT("settings.0005"), TXT("settings.0006")]
MAP_SOURCE_IDS = ["auto", "geofabrik", "overpass"]
SPEECH_SPEEDS = [1.0, 1.15, 1.3, 1.5, 1.75]
SPEECH_FREQ = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0]
AGGRO = [TXT("settings.0007"), TXT("settings.0008"), TXT("settings.0009"), TXT("settings.0010")]
LANGUAGE = [TXT("settings.0011"), TXT("settings.0012"), TXT("settings.0013")]
VOICES = [TXT("settings.0014"), TXT("settings.0015")]

MOUSE_MODE = ["Следење", "Управување", "Слободно гледање"]

DEFAULTS = {
    "resolution": RESOLUTIONS.index((1600, 900)), "aa": 1, "scale": 1, "fullscreen": False, "detail": 2,
    "vol_master": 0.8, "vol_sfx": 1.0, "vol_engine": 0.8, "vol_ambient": 0.8, "vol_speech": 1.0, "vol_radio": 0.7,
    "lik": 0, "hour": 17.0, "time_speed": 3, "traffic": 3, "peds": 3,
    "ambulance": True, "fire": True, "voice": 1, "speech_speed": 2, "speech_freq": 3, "aggro": 1, "lang": 1, "osm_source": 0, "smog": True, "smog_level": 1.0, "pollution": 1.0,
    "zoom_walk": 1.0, "zoom_car": 1.0, "shake": 1.0, "labels": True, "debug_chase": False, "debug": False, "mouse_sens": 1.0, "mouse_mode": 0,
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(PATH, "r", encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
                        self[k] = v
        except Exception:  # noqa: BLE001 - first run or unreadable file: defaults
            pass

    def save(self):
        try:
            with open(PATH + ".tmp", "w", encoding="utf-8") as f:
                json.dump(dict(self), f, indent=1)
            os.replace(PATH + ".tmp", PATH)
        except Exception:  # noqa: BLE001
            pass

    @property
    def time_mult(self):
        return TIME_SPEEDS[self["time_speed"]]

    @property
    def traffic_mult(self):
        return DENSITY[self["traffic"]]

    @property
    def ped_mult(self):
        return DENSITY[self["peds"]]
