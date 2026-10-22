"""Interface texts (literary Macedonian, Cyrillic).  Banter, jokes and slang live in slang.py.
Sources and the review status of the wording: docs/TEXT_SOURCES.md."""

TITLE = "СКОПЈЕ GTA"
RADIO_DL = "Радио: {n}/{target} {title}"
TAGLINE = "Скопје: проектот никогаш не завршува"

# ------------------------------------------------------------------ loading screen
L_TOTAL = "Вкупно"
L_ELAPSED = "поминато"
L_LEFT = "уште околу"
L_MAP = "Што се презема и каде оди"
L_SPEED = "Брзина"
L_GOT = "Преземено"
L_WAIT = "чекање"
L_SERVER = "Сервер"
L_NOW = "Сега"

KB, MB = "КБ", "МБ"
PER_S = "/с"
SEC = "с"

LEG_PENDING = "чека"
LEG_ACTIVE = "се презема"
LEG_DONE = "готово"
LEG_CACHED = "веќе го имам"
LEG_FAIL = "не успеа"
LEG_SPLIT = "се дели на делови"

OBJECTS = "објекти"
CUTTING = "Го сечам Скопје од мапата на државата"
C_NODES, C_WAYS, C_FOUND = "точки", "линии", "објекти во градот"
KM = "км"
EAST, WEST, NORTH, SOUTH, CENTRE = "источно", "западно", "северно", "јужно", "центар"
LAYER = {
    "roads": "Патишта", "buildings": "Згради", "areas": "Зеленило и води", "pois": "Знаменитости",
    "places": "Населби", "dem": "Висини (рељеф)",
}

STAGE = {
    "osm": "Преземање на мапата (OpenStreetMap)",
    "dem": "Преземање на висините (рељеф)",
    "build": "Градење на светот",
    "world": "Читање на светот",
    "overview": "Прегледна мапа",
    "textures": "Текстури и 3D модели",
    "chunks": "Првите делови од градот",
}

# progress phases of tools/build_world.py (its English labels -> what the player reads)
BUILD = {
    "read OSM files": "Читање на податоците",
    "buildings -> 3D meshes": "Згради во 3D",
    "areas / water / rails": "Површини, води и пруга",
    "roads": "Патишта",
    "building meshes on terrain": "Згради на рељефот",
    "graph": "Сообраќајна мрежа",
    "bridge decks": "Мостови",
    "places": "Населби",
    "street furniture": "Урбана опрема",
    "procedural trees in parks/woods": "Дрвја во паркови",
    "street trees, lamps, parked cars": "Улични дрвја, лампи и паркирани коли",
    "3D roads": "Патишта во 3D",
    "ground rasters": "Растери на земјата",
    "tree meshes": "Модели на дрвја",
    "lamp meshes": "Модели на лампи",
    "chunk index: areas": "Индекс на делови",
    "spawn point": "Почетна точка",
    "write world": "Запишување",
    "write mesh blob": "Запишување на мрежите",
    "write world parts": "Запишување на деловите",
}

# warnings by failure kind (tools/net.py)
WARN = {
    "busy": "Серверот е зафатен – чекам ред.",
    "reject": "Серверот го одби барањето – го делам на помали делови.",
    "stall": "Преземањето запре – менувам сервер.",
    "timeout": "Серверот не одговара – пробувам друг.",
    "offline": "Нема врска со интернет.",
    "bad": "Добиен е неисправен одговор – повторувам.",
    "exhausted": "Сите сервери одбиваат – ќе пробам подоцна.",
    "http": "Серверот врати грешка – повторувам.",
    "net": "Мрежна грешка – повторувам.",
}
ATTEMPT = "обид"
REST = "пауза"
NO_DATA = "Нема нови податоци веќе"
NOTE = {
    "newbox": "Зачуваните податоци се за друго подрачје – се преземаат одново.",
    "second_pass": "Втор обид за делови што не успеаа:",
    "total_limit": "Истече вкупното време – продолжувам со тоа што го имам.",
    "offline": "Нема врска – продолжувам со податоците што ги имам.",
    "busy_other": "Друго преземање веќе работи – користам што има.",
    "pbf_cut": "Датотеката е преземена – го исекувам Скопје од мапата на државата...",
    "unreachable": "Серверите не се достапни – продолжувам со тоа што го имам.",
}
PARTIAL = "Мапата е непотполна – играта ќе работи со тоа што е преземено; следниот пат ќе го дополни."
FALLBACK_DEMO = "Нема податоци за градот – се користи демо-град."
CLOSE_TO_EXIT = "Затворете го прозорецот за излез."
