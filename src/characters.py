"""Ликови што можеш да ги избереш на почеток (од likovi.txt).  Сликите (карикатури) се во assets/likovi/<id>.png;
ако некоја недостасува, се црта привремена картичка.  Статистиките се текст; во играта влијае само почетниот паричник."""
from texts import TXT
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "assets", "likovi")

# id, име, статистики (според likovi.txt), почетни пари
LIKOVI = [
    ("kumplung", TXT("characters.0001"), TXT("characters.0002"), 250),
    ("maca", TXT("characters.0003"), TXT("characters.0004"), 400),
    ("mile", TXT("characters.0005"), TXT("characters.0006"), 300),
    ("stojan", TXT("characters.0007"), TXT("characters.0008"), 30),
    ("influenser", TXT("characters.0009"), TXT("characters.0010"), 200),
    ("influenserka", TXT("characters.0011"), TXT("characters.0012"), 200),
    ("tetkica", TXT("characters.0013"), TXT("characters.0014"), 150),
    ("baba", TXT("characters.0015"), TXT("characters.0016"), 900),
    ("dedo", TXT("characters.0017"), TXT("characters.0018"), 0),
    ("pandur", TXT("characters.0019"), TXT("characters.0020"), 250),
    ("doktor", TXT("characters.0021"), TXT("characters.0022"), 1500),
    ("mali", TXT("characters.0023"), TXT("characters.0024"), 100),
    ("radnik", TXT("characters.0025"), TXT("characters.0026"), 50),
    ("burek", TXT("characters.0027"), TXT("characters.0028"), 120),
    ("boza", TXT("characters.0029"), TXT("characters.0030"), 180),
    ("fitka", TXT("characters.0031"), TXT("characters.0032"), 220),
    ("bilder", TXT("characters.0033"), TXT("characters.0034"), 350),
    ("shmizla", TXT("characters.0035"), TXT("characters.0036"), 300),
    ("palavko", TXT("characters.0037"), TXT("characters.0038"), 20),
    ("srednoskolec", TXT("characters.0039"), TXT("characters.0040"), 40),
    ("vojnik", TXT("characters.0041"), TXT("characters.0042"), 150),
    ("navivac", TXT("characters.0043"), TXT("characters.0044"), 80),
    ("administratorka", TXT("characters.0045"), TXT("characters.0046"), 280),
    ("nastavnica", TXT("characters.0047"), TXT("characters.0048"), 260),
]


def image_path(i):
    p = os.path.join(DIR, LIKOVI[i][0] + ".png")
    return p if os.path.exists(p) else None


def apply(sim, i):
    """Применува одбран лик на новата игра."""
    sim.lik = i % len(LIKOVI)
    try:
        sim.money = LIKOVI[i % len(LIKOVI)][3]
    except Exception:  # noqa: BLE001
        pass
