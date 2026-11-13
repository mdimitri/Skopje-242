"""Interface texts (literary Macedonian, Cyrillic).  Banter, jokes and slang live in slang.py.
Sources and the review status of the wording: docs/TEXT_SOURCES.md."""

from texts import TXT
TITLE = TXT("strings.0001")
RADIO_DL = TXT("strings.0002")
TAGLINE = TXT("strings.0003")

# ------------------------------------------------------------------ loading screen
L_TOTAL = TXT("strings.0004")
L_ELAPSED = TXT("strings.0005")
L_LEFT = TXT("strings.0006")
L_MAP = TXT("strings.0007")
L_SPEED = TXT("strings.0008")
L_GOT = TXT("strings.0009")
L_WAIT = TXT("strings.0010")
L_SERVER = TXT("strings.0011")
L_NOW = TXT("strings.0012")

KB, MB = TXT("strings.0013"), TXT("strings.0014")
PER_S = TXT("strings.0015")
SEC = TXT("strings.0016")

LEG_PENDING = TXT("strings.0017")
LEG_ACTIVE = TXT("strings.0018")
LEG_DONE = TXT("strings.0019")
LEG_CACHED = TXT("strings.0020")
LEG_FAIL = TXT("strings.0021")
LEG_SPLIT = TXT("strings.0022")

OBJECTS = TXT("strings.0023")
CUTTING = TXT("strings.0024")
C_NODES, C_WAYS, C_FOUND = TXT("strings.0025"), TXT("strings.0026"), TXT("strings.0027")
KM = TXT("strings.0028")
EAST, WEST, NORTH, SOUTH, CENTRE = TXT("strings.0029"), TXT("strings.0030"), TXT("strings.0031"), TXT("strings.0032"), TXT("strings.0033")
LAYER = {
    "roads": TXT("strings.0034"), "buildings": TXT("strings.0035"), "areas": TXT("strings.0036"), "pois": TXT("strings.0037"),
    "places": TXT("strings.0038"), "dem": TXT("strings.0039"),
}

STAGE = {
    "osm": TXT("strings.0040"),
    "pack": "Го преземам светот",                    # (new label: not in text/ yet)
    "dem": TXT("strings.0041"),
    "build": TXT("strings.0042"),
    "world": TXT("strings.0043"),
    "overview": TXT("strings.0044"),
    "textures": TXT("strings.0045"),
    "chunks": TXT("strings.0046"),
}

# progress phases of tools/build_world.py (its English labels -> what the player reads)
BUILD = {
    "read OSM files": TXT("strings.0047"),
    "buildings -> 3D meshes": TXT("strings.0048"),
    "areas / water / rails": TXT("strings.0049"),
    "roads": TXT("strings.0050"),
    "building meshes on terrain": TXT("strings.0051"),
    "graph": TXT("strings.0052"),
    "bridge decks": TXT("strings.0053"),
    "places": TXT("strings.0054"),
    "street furniture": TXT("strings.0055"),
    "procedural trees in parks/woods": TXT("strings.0056"),
    "street trees, lamps, parked cars": TXT("strings.0057"),
    "3D roads": TXT("strings.0058"),
    "ground rasters": TXT("strings.0059"),
    "tree meshes": TXT("strings.0060"),
    "lamp meshes": TXT("strings.0061"),
    "chunk index: areas": TXT("strings.0062"),
    "spawn point": TXT("strings.0063"),
    "write world": TXT("strings.0064"),
    "write mesh blob": TXT("strings.0065"),
    "write world parts": TXT("strings.0066"),
    "furniture": "Улична опрема",
    "leisure": "Клупи, игралишта, терени",
    "construction sites": "Градилишта",
    "fill: gardens, scrub, boulders": "Градини, грмушки, камења",
    "carriageway cleanup": "Чистење на коловозите",
    "railway": "Железница",
    "parked cars": "Паркирани коли",
    "cables and ground": "Кабли и патишта на земјата",
    "saving the stage": "Го зачувувам направеното",
    "loading saved stages": "Го вчитувам зачуваното",
    "fire escapes and roof jumps": "Пожарни скали и скокови меѓу покриви",
    "monument": "Го кревам споменикот на плоштад",
    "petrol stations and car washes": "Бензинки и перална за коли",
}

# warnings by failure kind (tools/net.py)
WARN = {
    "busy": TXT("strings.0067"),
    "reject": TXT("strings.0068"),
    "stall": TXT("strings.0069"),
    "timeout": TXT("strings.0070"),
    "offline": TXT("strings.0071"),
    "bad": TXT("strings.0072"),
    "exhausted": TXT("strings.0073"),
    "http": TXT("strings.0074"),
    "net": TXT("strings.0075"),
}
ATTEMPT = TXT("strings.0076")
REST = TXT("strings.0077")
NO_DATA = TXT("strings.0078")
NOTE = {
    "newbox": TXT("strings.0079"),
    "second_pass": TXT("strings.0080"),
    "total_limit": TXT("strings.0081"),
    "offline": TXT("strings.0082"),
    "busy_other": TXT("strings.0083"),
    "pbf_cut": TXT("strings.0084"),
    "unreachable": TXT("strings.0085"),
}
PARTIAL = TXT("strings.0086")
FALLBACK_DEMO = TXT("strings.0087")
CLOSE_TO_EXIT = TXT("strings.0088")

# ------------------------------------------------------------------ real map only (no fake city); literals here because text/ is edited by hand
RETRYING = "Мапата сè уште не е целосно преземена – повторен обид {n}/{total} за {s} сек…"
RETRYING_NOW = "Го дополнувам она што недостасува – обид {n}/{total}…"
DL_TITLE = "Мапата на Скопје не е преземена"
DL_FAILED = "Не успеав да ја преземам целата мапа или теренот (серверите не одговараат или нема интернет). Преземеното е зачувано и ќе продолжи од каде застанало."
BUILD_FAILED = "Градот не можеше да се изгради од преземените податоци (види logs/game.log)."
DL_RETRY_KEYS = "Enter – обиди се повторно    Esc – излез"
