"""What YOUR character says (first person), at least 50 lines each, matched to likovi.txt.  One line per row."""

from texts import TXT
_RAW = {
"kumplung": TXT("hero_lines.0001"),
"maca": TXT("hero_lines.0002"),
"mile": TXT("hero_lines.0003"),
"stojan": TXT("hero_lines.0004"),
"influenser": TXT("hero_lines.0005"),
"influenserka": TXT("hero_lines.0006"),
"tetkica": TXT("hero_lines.0007"),
"baba": TXT("hero_lines.0008"),
"dedo": TXT("hero_lines.0009"),
"pandur": TXT("hero_lines.0010"),
"doktor": TXT("hero_lines.0011"),
"mali": TXT("hero_lines.0012"),
"radnik": TXT("hero_lines.0013"),
"burek": TXT("hero_lines.0014"),
"boza": TXT("hero_lines.0015"),
"fitka": TXT("hero_lines.0016"),
"bilder": TXT("hero_lines.0017"),
"shmizla": TXT("hero_lines.0018"),
"palavko": TXT("hero_lines.0019"),
"srednoskolec": TXT("hero_lines.0020"),
"vojnik": TXT("hero_lines.0021"),
"navivac": TXT("hero_lines.0022"),
"administratorka": TXT("hero_lines.0023"),
"nastavnica": TXT("hero_lines.0024")
}

LINES = {k: [l.strip() for l in v.strip().splitlines() if l.strip()] for k, v in _RAW.items()}

import bible_lines   # noqa: E402 - уште реплики по лик, од речникот на скопски сленг

for _k, _v in bible_lines.HERO.items():
    LINES.setdefault(_k, []).extend(_v)
