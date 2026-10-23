"""User settings, saved to settings.json next to run.bat."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "settings.json")

RESOLUTIONS = [(1280, 720), (1600, 900), (1920, 1080), (2560, 1440)]
DETAIL = ["Ниско", "Средно", "Високо"]
TIME_SPEEDS = [0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
DENSITY = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
MAP_SOURCES = ["Автоматски", "Geofabrik (една датотека)", "Overpass (по плочки)"]
MAP_SOURCE_IDS = ["auto", "geofabrik", "overpass"]
SPEECH_SPEEDS = [1.0, 1.15, 1.3, 1.5, 1.75]
SPEECH_FREQ = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0]
AGGRO = ["Мирни", "Нормални", "Нервозни", "Луди"]
LANGUAGE = ["Пристојно", "Улично", "Без цензура (18+)"]
VOICES = ["Формантен (резервен)", "Сузе (RHVoice)"]

DEFAULTS = {
    "res": 1, "fullscreen": False, "detail": 2,
    "vol_master": 0.8, "vol_sfx": 1.0, "vol_engine": 0.8, "vol_ambient": 0.8, "vol_speech": 1.0, "vol_radio": 0.7,
    "lik": 0, "hour": 17.0, "time_speed": 3, "traffic": 3, "peds": 3,
    "ambulance": True, "fire": True, "voice": 1, "speech_speed": 2, "speech_freq": 3, "aggro": 1, "lang": 1, "osm_source": 0, "smog": True,
    "zoom_walk": 1.0, "zoom_car": 1.0, "shake": 1.0, "labels": True,
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
