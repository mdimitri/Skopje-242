"""The element kit of the photo-fitted buildings: 200+ parametric architectural elements on top of what src/facade.py measures
(tools/build_world.py photo_facade calls kit_wall for every wall and kit_roof once per building).

The kit is weighted towards the 1970s-80s Yugoslav housing blocks Skopje is full of (Karpoš, Aerodrom, Kisela Voda, Novo
Lisiče): prefab panel joints (IMS Žeželj / Jugomont / Rad systems), the exposed concrete skeleton of IMS frames, continuous
balcony parapet bands (smooth, ribbed, rounded ends), coloured spandrel panels, vertical fins and brise-soleil, cantilevered
erkers, staircase towers with strip windows or perforated screens, corner balconies, flower troughs, roller shutter boxes,
attic bands, pilotis, corbels, and on the roof the lift machine room, water tank, pergola, antenna masts and vents.

ELEMENTS: one entry per element = (id, family, Macedonian name, group, params).  Each family is one generator; the entries are
its measured / typical variants.  STYLES: named sets of elements (presets in the photogrammetry screen's ЕЛЕМЕНТИ tab).
auto_ids(fit): the elements the photo fit itself points to (cues), used when the fit's opts say kit_auto.
Every generator returns boxes in the wall's own frame:
    (u, out, y0, su, sd, hh, rgb)   u = along the wall from its start, out = the box centre's distance out of the OSM line,
                                    su = size along the wall, sd = size out of it, hh = height from y0
kit_roof returns world boxes (x, z, y0, sx, sz, hh, rgb, yaw).  numpy only; nothing here reads photos.
"""
import math

import numpy as np

CONC, WHITE, DARK, GLASS = (176, 174, 166), (232, 230, 224), (92, 90, 88), (64, 78, 92)
ACC = {"red": (156, 70, 52), "brick": (150, 84, 60), "ochre": (204, 150, 72), "yellow": (222, 196, 96), "blue": (74, 104, 150),
       "green": (92, 132, 96), "brown": (112, 84, 64), "grey": (128, 128, 126), "teal": (64, 128, 128), "orange": (214, 120, 60)}
MAX_BOXES = 1600                                                # per building: the kit never makes a building slow to draw

FAMILIES = {   # family -> (Macedonian name, group, where it goes)
    "fin": ("Вертикално ребро", "ѕид", "wall"), "slab": ("Плоча на катот (стреа)", "ѕид", "wall"),
    "parapet": ("Непрекинат балконски парапет", "балкони", "wall"), "joint": ("Спојници на монтажни панели", "ѕид", "wall"),
    "frame": ("Видлив бетонски скелет (IMS)", "ѕид", "wall"), "erker": ("Еркер", "волумен", "wall"),
    "tower": ("Скалишна кула", "волумен", "wall"), "louvre": ("Брисолеј", "прозорци", "wall"),
    "trough": ("Жардиниера", "балкони", "wall"), "shutterbox": ("Кутија за ролетна", "прозорци", "wall"),
    "cornerbal": ("Аголен балкон", "балкони", "wall"), "canopy": ("Настрешница над влезот", "приземје", "wall"),
    "pilotis": ("Столбови во приземјето", "приземје", "wall"), "corbel": ("Конзола под плочата", "ѕид", "wall"),
    "attic": ("Атика / завршен венец", "ѕид", "wall"), "spandrel": ("Обоен парапетен панел", "прозорци", "wall"),
    "screen": ("Перфориран параван", "волумен", "wall"), "rib": ("Ребраст бетон", "ѕид", "wall"),
    "checker": ("Наизменични балкони", "балкони", "wall"), "rail": ("Непрекината метална ограда", "балкони", "wall"),
    "plinth": ("Цокле", "приземје", "wall"), "surround": ("Рамка околу прозорецот", "прозорци", "wall"),
    "band": ("Обоена хоризонтална лента", "ѕид", "wall"), "pier": ("Ѕиден столб (пиластер)", "ѕид", "wall"),
    "roofroom": ("Машинска просторија за лифт", "покрив", "roof"), "tank": ("Резервоар за вода", "покрив", "roof"),
    "pergola": ("Пергола на покривот", "покрив", "roof"), "antenna": ("Антенски јарбол", "покрив", "roof"),
    "vents": ("Вентилациони оџаци", "покрив", "roof"), "rparapet": ("Покривен парапет", "покрив", "roof"),
    "roofrail": ("Ограда на покривна тераса", "покрив", "roof"), "solar": ("Сончеви колектори", "покрив", "roof"),
    "skylight": ("Светларник", "покрив", "roof"),
    "decowall": ("Декоративен бетонски ѕид", "волумен", "wall"), "breaker": ("Прекинувачки кат", "волумен", "wall"),
    "cascade": ("Каскадни испусти по висина", "волумен", "wall"), "divider": ("Преграден ѕид меѓу балкони", "балкони", "wall"),
    "curtain": ("Стаклена фасада", "стакло", "wall"), "weather": ("Дотраеност", "дотраеност", "wall"),
    "loggiafill": ("Затворени лоѓии (секој стан свое)", "балкони", "wall"), "flatpaint": ("Изолација по стан (шарено)", "дотраеност", "wall"),
    "chardak": ("Чардак (испуштен горен кат)", "волумен", "wall"), "unfinished": ("Недовршен кат (гола цигла)", "дотраеност", "wall"),
    "portico": ("Портик со столбови", "неокласика", "wall"), "dentil": ("Венец со забци", "неокласика", "wall"),
    "rustic": ("Рустика во приземјето", "неокласика", "wall"), "baluster": ("Балустрада", "неокласика", "wall"),
    "shopfront": ("Дуќан во приземјето", "приземје", "wall"), "laundry": ("Сушилки за алишта", "балкони", "wall"),
    "dish": ("Сателитски чинии на балкони", "балкони", "wall"), "flue": ("Надворешен оџак (печка на дрва)", "ѕид", "wall"),
    "nadgradba": ("Надградба на покривот", "покрив", "roof"), "sawroof": ("Пилест индустриски покрив", "покрив", "roof"),
    "billboard": ("Билборд на покривот", "покрив", "roof"), "plantscreen": ("Параван за уреди на покривот", "покрив", "roof"),
    "rebar": ("Арматура од столбовите (за следен кат)", "покрив", "roof"),
}

# (id, family, variant name, params): the variants of every family
_V = [
    # vertical fins: t = thickness, d = depth, every = every n-th column edge, at = edge / mid, span = full / upper / ground, above
    ("fin_thin_1", "fin", "тенко 12 см, секој столб", dict(t=0.12, d=0.35, every=1)),
    ("fin_thin_2", "fin", "тенко 12 см, секој втор", dict(t=0.12, d=0.35, every=2)),
    ("fin_mid_1", "fin", "20 см, длабоко 50, секој столб", dict(t=0.2, d=0.5, every=1)),
    ("fin_mid_2", "fin", "20 см, длабоко 50, секој втор", dict(t=0.2, d=0.5, every=2)),
    ("fin_deep_1", "fin", "длабоко 90 см (брисолеј)", dict(t=0.18, d=0.9, every=1)),
    ("fin_deep_3", "fin", "длабоко 90, секој трет", dict(t=0.18, d=0.9, every=3)),
    ("fin_heavy_2", "fin", "масивно 35 см, секој втор", dict(t=0.35, d=0.6, every=2)),
    ("fin_upper_1", "fin", "само горните катови", dict(t=0.16, d=0.45, every=1, span="upper")),
    ("fin_above_2", "fin", "над покривот 1.2 м", dict(t=0.2, d=0.5, every=2, above=1.2)),
    ("fin_mid_col", "fin", "среде столбот", dict(t=0.14, d=0.4, every=1, at="mid")),
    ("fin_ground", "fin", "само приземје", dict(t=0.3, d=0.4, every=1, span="ground")),
    ("fin_ends", "fin", "само на краевите на ѕидот", dict(t=0.3, d=0.6, every=999)),
    # floor slabs / sunshade ledges at the floor lines
    ("slab_thin", "slab", "тенка 12 см, 40 см напред, секој кат", dict(d=0.4, t=0.12)),
    ("slab_deep", "slab", "длабока 1 м (сенка), секој кат", dict(d=1.0, t=0.16)),
    ("slab_2", "slab", "секој втор кат", dict(d=0.6, t=0.14, every=2)),
    ("slab_heavy", "slab", "масивна 30 см", dict(d=0.5, t=0.3)),
    ("slab_upper", "slab", "од вториот кат", dict(d=0.6, t=0.14, start=2)),
    ("slab_first", "slab", "само над приземјето", dict(d=1.2, t=0.2, start=1, stop=1)),
    ("slab_gap", "slab", "по столбови, со прекини", dict(d=0.5, t=0.12, gaps=1)),
    ("slab_white", "slab", "бела", dict(d=0.5, t=0.14, col="white")),
    # continuous balcony parapets (the classic horizontal bands of the blocks)
    ("par_smooth", "parapet", "мазен, цел ѕид, секој кат", dict(d=1.2, hh=1.0)),
    ("par_smooth_bal", "parapet", "мазен, само кај балконите", dict(d=1.2, hh=1.0, where="balc")),
    ("par_ribbed", "parapet", "ребраст (вертикални ребра)", dict(d=1.2, hh=1.0, ribs=0.3)),
    ("par_ribbed_fine", "parapet", "ситно ребраст", dict(d=1.1, hh=1.0, ribs=0.15)),
    ("par_round", "parapet", "заоблени краеви", dict(d=1.2, hh=1.0, round=1)),
    ("par_round_bal", "parapet", "заоблени, само балкони", dict(d=1.2, hh=1.0, round=1, where="balc")),
    ("par_low", "parapet", "низок 60 см + метална ограда", dict(d=1.1, hh=0.6, rail=1)),
    ("par_deep", "parapet", "длабок 1.8 м (лоѓа-тераса)", dict(d=1.8, hh=1.0)),
    ("par_shallow", "parapet", "плиток 60 см (француски)", dict(d=0.6, hh=0.95)),
    ("par_white", "parapet", "бел", dict(d=1.2, hh=1.0, col="white")),
    ("par_conc", "parapet", "сив бетон", dict(d=1.2, hh=1.0, col="conc")),
    ("par_red", "parapet", "црвено-кафеав", dict(d=1.2, hh=1.0, col="red")),
    ("par_ochre", "parapet", "окер", dict(d=1.2, hh=1.0, col="ochre")),
    ("par_blue", "parapet", "син", dict(d=1.2, hh=1.0, col="blue")),
    ("par_brown", "parapet", "кафеав", dict(d=1.2, hh=1.0, col="brown")),
    ("par_upper", "parapet", "од вториот кат", dict(d=1.2, hh=1.0, start=2)),
    ("par_2", "parapet", "секој втор кат", dict(d=1.2, hh=1.0, every=2)),
    ("par_loggia", "parapet", "само кај лоѓиите", dict(d=0.25, hh=1.0, where="loggia")),
    # prefab panel joints
    ("joint_floor", "joint", "хоризонтални на секој кат", dict(v=0)),
    ("joint_grid_1", "joint", "мрежа: кат × секој столб", dict(v=1)),
    ("joint_grid_2", "joint", "мрежа: кат × два столба (панел 6 м)", dict(v=2)),
    ("joint_grid_3", "joint", "мрежа: кат × три столба", dict(v=3)),
    ("joint_deep", "joint", "длабоки сенчести фуги", dict(v=1, w=0.06, col="dark")),
    ("joint_light", "joint", "светли фуги", dict(v=2, w=0.04, col="white")),
    ("joint_half", "joint", "мрежа: половина кат (два панели по висина)", dict(v=1, half=1)),
    # exposed skeleton
    ("frame_ims", "frame", "IMS: столбови + греди, 30 см", dict(t=0.3, d=0.12)),
    ("frame_ims_2", "frame", "IMS: секој втор столб", dict(t=0.3, d=0.12, every=2)),
    ("frame_deep", "frame", "длабок 40 см", dict(t=0.35, d=0.4)),
    ("frame_white", "frame", "бел скелет", dict(t=0.28, d=0.15, col="white")),
    ("frame_beams", "frame", "само греди (хоризонтално)", dict(t=0.3, d=0.15, cols=0)),
    ("frame_posts", "frame", "само столбови (вертикално)", dict(t=0.3, d=0.15, beams=0)),
    ("frame_conc", "frame", "сив бетон", dict(t=0.3, d=0.15, col="conc")),
    # erkers (cantilevered bays)
    ("erk_1", "erker", "еден столб, 80 см, секој трет", dict(w=1, d=0.8, every=3)),
    ("erk_2", "erker", "два столба, 1 м, секој четврти", dict(w=2, d=1.0, every=4)),
    ("erk_full", "erker", "секој втор столб, горни катови", dict(w=1, d=0.7, every=2)),
    ("erk_mid", "erker", "во средината на ѕидот", dict(w=2, d=1.0, every=0)),
    ("erk_deep", "erker", "длабок 1.4 м, стаклен", dict(w=1, d=1.4, every=3, glass=1)),
    ("erk_top", "erker", "само последните 3 ката", dict(w=1, d=0.8, every=2, top=3)),
    ("erk_conc", "erker", "бетонски, со прозорска лента", dict(w=1, d=0.9, every=3, col="conc")),
    ("erk_tri", "erker", "три столба, плиток", dict(w=3, d=0.6, every=6)),
    # staircase towers
    ("tow_mid", "tower", "среде ѕидот, лента прозорци", dict(at="mid", w=3.0, d=1.6, above=2.4)),
    ("tow_mid_scr", "tower", "среде ѕидот, перфориран параван", dict(at="mid", w=3.0, d=1.6, above=2.4, screen=1)),
    ("tow_end", "tower", "на крајот на ѕидот", dict(at="end", w=3.2, d=2.0, above=2.4)),
    ("tow_start", "tower", "на почетокот на ѕидот", dict(at="start", w=3.2, d=2.0, above=2.4)),
    ("tow_slim", "tower", "тесна (лифт)", dict(at="mid", w=2.2, d=1.2, above=3.0)),
    ("tow_glass", "tower", "стаклена лента цела висина", dict(at="mid", w=3.0, d=1.4, above=1.5, strip=1.6)),
    ("tow_blocks", "tower", "стаклени цигли", dict(at="mid", w=3.0, d=1.4, above=2.0, gblock=1)),
    ("tow_conc", "tower", "сив бетон", dict(at="mid", w=3.0, d=1.6, above=2.4, col="conc")),
    ("tow_red", "tower", "обоена", dict(at="mid", w=3.0, d=1.6, above=2.4, col="red")),
    ("tow_flush", "tower", "плитка, над покривот 3 м", dict(at="mid", w=3.4, d=0.5, above=3.0)),
    # brise-soleil
    ("lv_h3", "louvre", "3 хоризонтални ламели", dict(o="h", n=3, d=0.45)),
    ("lv_h5", "louvre", "5 хоризонтални ламели", dict(o="h", n=5, d=0.35)),
    ("lv_v3", "louvre", "3 вертикални ламели", dict(o="v", n=3, d=0.45)),
    ("lv_v5", "louvre", "5 вертикални ламели", dict(o="v", n=5, d=0.35)),
    ("lv_h_top", "louvre", "надпрозорска стреа", dict(o="h", n=1, d=0.6)),
    ("lv_grid", "louvre", "мрежа (саќе)", dict(o="g", n=3, d=0.4)),
    ("lv_h_white", "louvre", "бели хоризонтални", dict(o="h", n=4, d=0.4, col="white")),
    ("lv_v_conc", "louvre", "бетонски вертикални", dict(o="v", n=2, d=0.6, col="conc")),
    # flower troughs
    ("tr_balc", "trough", "на балконите", dict(where="balc")),
    ("tr_all", "trough", "под секој прозорец", dict(where="all")),
    ("tr_conc", "trough", "бетонски, на секој кат", dict(where="all", col="conc", hh=0.45)),
    ("tr_green", "trough", "со зеленило", dict(where="balc", plants=1)),
    ("tr_ground", "trough", "само над приземјето", dict(where="all", start=1, stop=1, plants=1)),
    # roller shutter boxes
    ("sb_std", "shutterbox", "надворешна кутија", dict(d=0.22, hh=0.22)),
    ("sb_white", "shutterbox", "бела", dict(d=0.22, hh=0.22, col="white")),
    ("sb_brown", "shutterbox", "кафеава", dict(d=0.22, hh=0.22, col="brown")),
    ("sb_big", "shutterbox", "голема (стар тип)", dict(d=0.3, hh=0.3)),
    # corner balconies
    ("cb_both", "cornerbal", "на двата агла", dict(w=2.4, d=1.2)),
    ("cb_end", "cornerbal", "само на крајниот агол", dict(w=2.4, d=1.2, ends="end")),
    ("cb_wide", "cornerbal", "широки 3.6 м", dict(w=3.6, d=1.4)),
    ("cb_round", "cornerbal", "заоблен парапет", dict(w=2.4, d=1.2, round=1)),
    ("cb_rail", "cornerbal", "со метална ограда", dict(w=2.4, d=1.2, rail=1)),
    # entrance canopies
    ("can_std", "canopy", "бетонска плоча 3 м", dict(w=3.0, d=1.5)),
    ("can_wide", "canopy", "широка 6 м", dict(w=6.0, d=2.0)),
    ("can_post", "canopy", "на два столба", dict(w=3.5, d=2.4, posts=1)),
    ("can_thin", "canopy", "тенка метална", dict(w=2.6, d=1.2, t=0.08, col="grey")),
    ("can_all", "canopy", "на секој ѕид", dict(w=3.0, d=1.5, all=1)),
    # pilotis
    ("pil_std", "pilotis", "столбови 40 см на 3 м", dict(s=3.0, t=0.4)),
    ("pil_dense", "pilotis", "густи на 1.8 м", dict(s=1.8, t=0.3)),
    ("pil_round", "pilotis", "кружни (осумаголни)", dict(s=3.0, t=0.45, oct=1)),
    ("pil_heavy", "pilotis", "масивни 70 см на 6 м", dict(s=6.0, t=0.7)),
    ("pil_white", "pilotis", "бели", dict(s=3.0, t=0.4, col="white")),
    # corbels
    ("cor_std", "corbel", "под секоја плоча, на столбовите", dict(d=0.6, hh=0.45)),
    ("cor_2", "corbel", "секој втор столб", dict(d=0.6, hh=0.45, every=2)),
    ("cor_deep", "corbel", "длабоки бруталистички", dict(d=1.1, hh=0.7, t=0.35)),
    ("cor_top", "corbel", "само под атиката", dict(d=0.5, hh=0.5, top=1)),
    # attic bands
    ("att_std", "attic", "венец 60 см", dict(hh=0.6, d=0.3)),
    ("att_high", "attic", "висока атика 1.2 м", dict(hh=1.2, d=0.2)),
    ("att_deep", "attic", "длабок венец 80 см", dict(hh=0.5, d=0.8)),
    ("att_white", "attic", "бел венец", dict(hh=0.6, d=0.3, col="white")),
    ("att_dark", "attic", "темен лим", dict(hh=0.4, d=0.15, col="grey")),
    ("att_stepped", "attic", "скалест (два слоја)", dict(hh=0.8, d=0.45, step=1)),
    ("att_red", "attic", "црвено-кафеав", dict(hh=0.6, d=0.3, col="red")),
    # coloured spandrels
    ("sp_red", "spandrel", "црвено-кафеави", dict(col="red")),
    ("sp_ochre", "spandrel", "окер", dict(col="ochre")),
    ("sp_yellow", "spandrel", "жолти", dict(col="yellow")),
    ("sp_blue", "spandrel", "сини", dict(col="blue")),
    ("sp_green", "spandrel", "зелени", dict(col="green")),
    ("sp_teal", "spandrel", "тиркизни", dict(col="teal")),
    ("sp_orange", "spandrel", "портокалови", dict(col="orange")),
    ("sp_brick", "spandrel", "цигла", dict(col="brick")),
    ("sp_grey", "spandrel", "сиви", dict(col="grey")),
    ("sp_dark", "spandrel", "темни", dict(col="dark")),
    ("sp_alt", "spandrel", "наизменично обоени", dict(col="red", alt=1)),
    ("sp_rel", "spandrel", "испакнати 8 см", dict(col="conc", d=0.08)),
    # perforated screens
    ("scr_mid", "screen", "среде ѕидот, цела висина", dict(w=3.0, d=0.3)),
    ("scr_end", "screen", "на крајот", dict(w=2.4, d=0.3, at="end")),
    ("scr_dense", "screen", "густа решетка", dict(w=3.0, d=0.25, s=0.2)),
    ("scr_white", "screen", "бела", dict(w=3.0, d=0.3, col="white")),
    ("scr_ground", "screen", "пред приземјето", dict(w=6.0, d=0.6, ground=1)),
    # ribbed concrete
    ("rib_06", "rib", "ребра на 60 см", dict(s=0.6)),
    ("rib_03", "rib", "ребра на 30 см", dict(s=0.3)),
    ("rib_12", "rib", "ребра на 1.2 м", dict(s=1.2, t=0.14, d=0.12)),
    ("rib_ground", "rib", "само приземје", dict(s=0.4, span="ground")),
    ("rib_upper", "rib", "само горни катови", dict(s=0.6, span="upper")),
    ("rib_corrug", "rib", "брановиден лим (индустрија)", dict(s=0.15, t=0.05, d=0.04, col="grey")),
    ("joint_acm", "joint", "алуминиумски панели (ACM)", dict(v=1, half=1, w=0.03, col="grey")),
    # alternating balconies
    ("chk_std", "checker", "шаховски распоред", dict(d=1.1)),
    ("chk_deep", "checker", "длабоки 1.6 м", dict(d=1.6)),
    ("chk_col", "checker", "по два столба", dict(d=1.2, w=2)),
    ("chk_rail", "checker", "со метална ограда", dict(d=1.1, rail=1)),
    ("chk_stair", "checker", "скалесто (дијагонално)", dict(d=1.1, diag=1)),
    # continuous metal railings
    ("rl_std", "rail", "на секој кат, 1.1 м напред", dict(d=1.1)),
    ("rl_slab", "rail", "со плоча", dict(d=1.1, slab=1)),
    ("rl_dense", "rail", "густи шипки", dict(d=1.0, s=0.12)),
    ("rl_dark", "rail", "темна", dict(d=1.1, col="dark")),
    ("rl_white", "rail", "бела", dict(d=1.1, col="white")),
    # plinths
    ("pl_low", "plinth", "низок 40 см", dict(hh=0.4, d=0.05)),
    ("pl_high", "plinth", "висок 1 м", dict(hh=1.0, d=0.06)),
    ("pl_stone", "plinth", "камен 80 см", dict(hh=0.8, d=0.08, col="grey")),
    ("pl_dark", "plinth", "темен", dict(hh=0.6, d=0.05, col="dark")),
    # window surrounds
    ("sur_std", "surround", "бела рамка 15 см", dict(w=0.15, d=0.06, col="white")),
    ("sur_deep", "surround", "длабока бетонска рамка", dict(w=0.2, d=0.3, col="conc")),
    ("sur_box", "surround", "кутиеста рамка (испакната)", dict(w=0.12, d=0.45)),
    ("sur_dark", "surround", "темна рамка", dict(w=0.12, d=0.05, col="dark")),
    ("sur_top", "surround", "само надвратник", dict(w=0.2, d=0.12, top=1)),
    ("sur_red", "surround", "црвена рамка", dict(w=0.15, d=0.06, col="red")),
    # coloured bands
    ("bd_red", "band", "црвена на секој кат", dict(col="red", hh=0.4)),
    ("bd_ochre", "band", "окер на секој кат", dict(col="ochre", hh=0.4)),
    ("bd_blue", "band", "сина на секој кат", dict(col="blue", hh=0.4)),
    ("bd_white", "band", "бела на секој кат", dict(col="white", hh=0.3)),
    ("bd_brown_2", "band", "кафеава на секој втор кат", dict(col="brown", hh=0.5, every=2)),
    ("bd_wide", "band", "широка 90 см (парапетна)", dict(col="conc", hh=0.9)),
    ("bd_top", "band", "само под покривот", dict(col="red", hh=0.8, top=1)),
    # piers / pilasters
    ("pr_ends", "pier", "на краевите", dict(t=0.6, d=0.2, ends=1)),
    ("pr_3", "pier", "секој трет столб", dict(t=0.5, d=0.2, every=3)),
    ("pr_wide", "pier", "широки 1.2 м, секој четврти", dict(t=1.2, d=0.25, every=4)),
    ("pr_white", "pier", "бели, секој втор", dict(t=0.4, d=0.12, every=2, col="white")),
    ("pr_brick", "pier", "цигла, на краевите", dict(t=0.8, d=0.1, ends=1, col="brick")),
    # colours measured from the photo (the most colourful cell / parapet of the wall): colourful blocks stay colourful
    ("par_photo", "parapet", "во бојата од сликата", dict(d=1.2, hh=1.0, col="photo")),
    ("par_photo_bal", "parapet", "бојата од сликата, само балкони", dict(d=1.2, hh=1.0, col="photo", where="balc")),
    ("par_photo_alt", "parapet", "две бои од сликата наизменично", dict(d=1.2, hh=1.0, col="photo", alt=1)),
    ("sp_photo", "spandrel", "во бојата од сликата", dict(col="photo")),
    ("sp_photo_alt", "spandrel", "две бои од сликата, шаховски", dict(col="photo", alt=1, two=1)),
    ("bd_photo", "band", "во бојата од сликата", dict(col="photo", hh=0.5)),
    ("tow_photo", "tower", "во бојата од сликата", dict(at="mid", w=3.0, d=1.6, above=2.4, col="photo")),
    ("erk_photo", "erker", "во бојата од сликата", dict(w=1, d=0.8, every=3, col="photo")),
    ("fin_photo", "fin", "во бојата од сликата, секој втор", dict(t=0.2, d=0.5, every=2, col="photo")),
    ("att_photo", "attic", "во бојата од сликата", dict(hh=0.7, d=0.3, col="photo")),
    ("frame_photo", "frame", "скелет во бојата од сликата", dict(t=0.3, d=0.12, col="photo")),
    ("pr_photo", "pier", "пиластри во бојата од сликата", dict(t=0.6, d=0.18, every=3, col="photo")),
    # decorative concrete walls (relief patterns on blank parts of the wall)
    ("dw_grid", "decowall", "квадратна мрежа на слепите ѕидови", dict(pat="grid", s=0.8)),
    ("dw_grid_fine", "decowall", "ситна мрежа", dict(pat="grid", s=0.45)),
    ("dw_diamond", "decowall", "ромбови", dict(pat="diamond", s=1.0)),
    ("dw_vert", "decowall", "вертикални канелури", dict(pat="vert", s=0.5)),
    ("dw_horiz", "decowall", "хоризонтални жлебови", dict(pat="horiz", s=0.4)),
    ("dw_blocks", "decowall", "испакнати блокови (бруталистички)", dict(pat="blocks", s=1.2, d=0.25)),
    ("dw_wave", "decowall", "бранови (наизменични ленти)", dict(pat="wave", s=0.6)),
    ("dw_end", "decowall", "цел краен ѕид без прозорци", dict(pat="grid", s=0.9, whole=1)),
    ("dw_photo", "decowall", "мрежа во бојата од сликата", dict(pat="grid", s=0.8, col="photo")),
    # interruption storeys (a recessed dark floor line + a heavy slab every few floors)
    ("br_4", "breaker", "на секој 4. кат", dict(every=4)),
    ("br_3", "breaker", "на секој 3. кат", dict(every=3)),
    ("br_mid", "breaker", "еден, на половина висина", dict(every=0)),
    ("br_first", "breaker", "над приземјето (мезанин)", dict(every=-1)),
    ("br_deep", "breaker", "длабок, на секој 5. кат", dict(every=5, d=1.4, hh=0.6)),
    # cascades (the upper floors step out section by section)
    ("cas_out", "cascade", "катовите излегуваат нанадвор нагоре", dict(dir=1, d=0.35)),
    ("cas_in", "cascade", "катовите се повлекуваат нагоре", dict(dir=-1, d=0.35)),
    ("cas_alt", "cascade", "наизменично по секции", dict(dir=0, d=0.5)),
    ("cas_photo", "cascade", "наизменично, во бојата од сликата", dict(dir=0, d=0.5, col="photo")),
    # dividing walls between balconies (perpendicular to the wall, the deep cells of the blocks)
    ("dv_std", "divider", "полн ѕид, секој столб", dict(d=1.3, every=1)),
    ("dv_2", "divider", "секој втор столб", dict(d=1.3, every=2)),
    ("dv_cut", "divider", "со кружен отвор (декоративен)", dict(d=1.3, every=1, cut=1)),
    ("dv_photo", "divider", "во бојата од сликата", dict(d=1.3, every=1, col="photo")),
    ("dv_deep", "divider", "длабок 2 м, цела висина", dict(d=2.0, every=2, full=1)),
    # glass curtain walls (modern commercial buildings; the fit's "glass" surface)
    ("cw_grid", "curtain", "мрежа од профили 1.5 м × кат", dict(s=1.5)),
    ("cw_grid_fine", "curtain", "густа мрежа 0.9 м", dict(s=0.9)),
    ("cw_vert", "curtain", "само вертикални профили", dict(s=1.2, horiz=0)),
    ("cw_horiz", "curtain", "само хоризонтални ленти", dict(s=0, spand=0.0)),
    ("cw_spandrel", "curtain", "темни парапетни ленти на секој кат", dict(s=1.5, spand=0.9)),
    ("cw_fins", "curtain", "надворешни стаклени перки", dict(s=1.5, fin=0.4)),
    ("cw_deep_fins", "curtain", "длабоки алуминиумски перки", dict(s=1.8, fin=0.8, col="grey")),
    ("cw_corner", "curtain", "стаклен агол без столб", dict(s=1.5, corner=1)),
    ("cw_blue", "curtain", "сино рефлектирачко стакло", dict(s=1.5, tint="blue")),
    ("cw_green", "curtain", "зеленикаво стакло", dict(s=1.5, tint="green")),
    ("cw_bronze", "curtain", "бронзено стакло", dict(s=1.5, tint="bronze")),
    ("cw_ribbon", "curtain", "лентести прозорци (стакло + бетонски ленти)", dict(s=1.5, spand=1.2, col="conc")),
    ("cw_canopy", "curtain", "стаклена настрешница над приземјето", dict(s=1.5, canopy=1)),
    ("cw_top", "curtain", "стаклен последен кат", dict(s=1.2, top=1)),
    # weathering of old / neglected buildings (as the photo shows it: rough or patchy walls)
    ("wt_peel", "weather", "оронета фасада (паднат малтер)", dict(k="peel", n=6)),
    ("wt_peel_heavy", "weather", "многу оронета", dict(k="peel", n=16)),
    ("wt_stain", "weather", "дамки од вода под прозорците", dict(k="stain", n=8)),
    ("wt_roofstain", "weather", "темни траги од стреата", dict(k="topstain", n=6)),
    ("wt_brick", "weather", "гола цигла низ малтерот", dict(k="brick", n=5)),
    ("wt_patch", "weather", "поправени крпи (посветли)", dict(k="patch", n=6)),
    ("wt_styro", "weather", "делумна изолација (стиропор)", dict(k="styro", n=3)),
    ("wt_graffiti", "weather", "графити ниско на ѕидот", dict(k="graffiti", n=5)),
    ("wt_crack", "weather", "пукнатини", dict(k="crack", n=6)),
    ("wt_dirt", "weather", "нечистотија над тротоарот", dict(k="dirt", n=1)),
    ("wt_rust", "weather", "рѓосани ограда и олуци", dict(k="rust", n=6)),
    ("wt_boarded", "weather", "заковани прозорци", dict(k="boarded", n=3)),
    ("wt_broken_shutter", "weather", "искривени ролетни / капаци", dict(k="shutter", n=5)),
    ("wt_moss", "weather", "мов и вегетација", dict(k="moss", n=4)),
    # what residents did to the blocks (each flat its own: seeded per cell)
    ("lf_half", "loggiafill", "половина од лоѓиите затворени", dict(share=0.5)),
    ("lf_most", "loggiafill", "речиси сите затворени", dict(share=0.85)),
    ("lf_few", "loggiafill", "по некоја затворена", dict(share=0.25)),
    ("lf_pvc", "loggiafill", "бел ПВЦ", dict(share=0.6, mix="pvc")),
    ("lf_alu", "loggiafill", "кафеав алуминиум", dict(share=0.6, mix="alu")),
    ("fp_some", "flatpaint", "по некој стан изолиран", dict(share=0.2)),
    ("fp_many", "flatpaint", "половина станови во пастелни бои", dict(share=0.5)),
    ("fp_rows", "flatpaint", "цели вертикали обоени", dict(share=0.35, vert=1)),
    ("ld_some", "laundry", "сушилки на некои балкони", dict(share=0.35)),
    ("ld_many", "laundry", "сушилки на повеќето балкони", dict(share=0.7)),
    ("ds_some", "dish", "по некоја чинија", dict(share=0.2)),
    ("ds_many", "dish", "многу чинии", dict(share=0.5)),
    ("fl_one", "flue", "една цевка по ѕидот", dict(n=1)),
    ("fl_many", "flue", "повеќе цевки", dict(n=3)),
    # old Skopje houses and the unfinished family house
    ("ch_std", "chardak", "60 см на дрвени конзоли", dict(d=0.6)),
    ("ch_deep", "chardak", "1 м, на конзоли", dict(d=1.0)),
    ("ch_plain", "chardak", "без конзоли, бетонски", dict(d=0.5, brackets=0)),
    ("uf_top", "unfinished", "последниот кат гола цигла", dict(floors=1)),
    ("uf_two", "unfinished", "два ката гола цигла", dict(floors=2)),
    ("uf_gable", "unfinished", "гола цигла само на краевите", dict(floors=1, ends=1)),
    # "Skopje 2014" neoclassical facades
    ("pt_four", "portico", "4 столба + тимпанон", dict(n=4)),
    ("pt_six", "portico", "6 столба + тимпанон", dict(n=6)),
    ("pt_full", "portico", "столбови по целиот ѕид", dict(n=0)),
    ("pt_engaged", "portico", "ѕидни полустолбови", dict(n=0, engaged=1)),
    ("dn_std", "dentil", "венец со забци", dict(s=0.3)),
    ("dn_fine", "dentil", "ситни забци", dict(s=0.18)),
    ("ru_std", "rustic", "хоризонтални фуги во приземјето", dict(s=0.5)),
    ("ru_block", "rustic", "блокови (рустика)", dict(s=0.6, blocks=1)),
    ("bl_top", "baluster", "балустрада на атиката", dict(top=1)),
    ("bl_bal", "baluster", "балустради на балконите", dict(top=0)),
    # ground floors
    ("sf_shutter", "shopfront", "ролетни + натпис", dict(sign=1)),
    ("sf_awning", "shopfront", "тенди над излозите", dict(awning=1)),
    ("sf_full", "shopfront", "излози, натписи и тенди", dict(sign=1, awning=1)),
    ("sf_kiosk", "shopfront", "доградени киосци", dict(kiosk=1)),
    # roof additions
    ("ng_pitched", "nadgradba", "доградена мансарда (коси покрив)", dict(kind="pitched")),
    ("ng_box", "nadgradba", "дограден кат повлечен", dict(kind="box")),
    ("ng_colour", "nadgradba", "доградба во друга боја", dict(kind="box", col="ochre")),
    ("sr_std", "sawroof", "пилест покрив (фабрика)", dict(s=6.0)),
    ("sr_fine", "sawroof", "густ пилест покрив", dict(s=3.5)),
    ("bb_one", "billboard", "голем билборд", dict(w=8.0)),
    ("bb_mast", "billboard", "мобилна антена (јарбол)", dict(mast=1)),
    ("ps_std", "plantscreen", "параван околу уредите", dict(hh=2.0)),
    ("rb_cols", "rebar", "шипки на столбовите", dict(hh=0.9)),
    # roof: lift machine rooms
    ("rr_std", "roofroom", "една, во средината", dict(w=4.0, d=3.0, hh=2.6)),
    ("rr_two", "roofroom", "две, по должината", dict(w=3.6, d=3.0, hh=2.6, n=2)),
    ("rr_three", "roofroom", "три (по еден влез)", dict(w=3.4, d=3.0, hh=2.6, n=3)),
    ("rr_tall", "roofroom", "висока 3.5 м", dict(w=4.0, d=3.0, hh=3.5)),
    ("rr_slope", "roofroom", "со коса плоча", dict(w=4.0, d=3.0, hh=2.6, lid=1)),
    ("rr_small", "roofroom", "мала кабина", dict(w=2.4, d=2.0, hh=2.2)),
    ("rr_conc", "roofroom", "сив бетон", dict(w=4.0, d=3.0, hh=2.6, col="conc")),
    # roof: water tanks
    ("tk_std", "tank", "на столбови", dict(r=1.2, hh=1.6, legs=1.2)),
    ("tk_low", "tank", "ниска", dict(r=1.4, hh=1.2, legs=0.0)),
    ("tk_two", "tank", "две", dict(r=1.0, hh=1.4, legs=1.0, n=2)),
    ("tk_box", "tank", "кутиеста на кабината", dict(r=1.0, hh=1.2, legs=0.0, box=1)),
    # roof: pergolas
    ("pg_std", "pergola", "бетонска пергола", dict(w=6.0, d=4.0, hh=2.4)),
    ("pg_long", "pergola", "долж целиот покрив", dict(w=0.0, d=3.0, hh=2.4)),
    ("pg_dense", "pergola", "густи греди", dict(w=6.0, d=4.0, hh=2.4, s=0.5)),
    ("pg_white", "pergola", "бела", dict(w=6.0, d=4.0, hh=2.4, col="white")),
    # roof: antenna masts
    ("an_one", "antenna", "еден јарбол", dict(n=1, hh=4.0)),
    ("an_many", "antenna", "многу ТВ антени", dict(n=6, hh=2.4)),
    ("an_tall", "antenna", "висок 8 м", dict(n=1, hh=8.0)),
    ("an_dish", "antenna", "сателитски чинии", dict(n=4, hh=1.0, dish=1)),
    # roof: vents
    ("vt_row", "vents", "ред оџаци", dict(n=6, hh=1.2)),
    ("vt_pairs", "vents", "парови", dict(n=4, hh=1.0, pair=1)),
    ("vt_big", "vents", "големи шахти", dict(n=3, hh=1.6, w=0.9)),
    ("vt_many", "vents", "многу ситни", dict(n=14, hh=0.7, w=0.3)),
    # roof: parapets
    ("rp_std", "rparapet", "60 см", dict(hh=0.6)),
    ("rp_high", "rparapet", "1.1 м", dict(hh=1.1)),
    ("rp_thick", "rparapet", "масивен", dict(hh=0.8, t=0.4)),
    ("rp_white", "rparapet", "бел", dict(hh=0.6, col="white")),
    # roof: terrace railings
    ("rf_std", "roofrail", "метална", dict(hh=1.0)),
    ("rf_dark", "roofrail", "темна", dict(hh=1.0, col="dark")),
    ("rf_dense", "roofrail", "густа", dict(hh=1.0, s=0.15)),
    # roof: solar collectors
    ("so_rows", "solar", "редови", dict(rows=3)),
    ("so_few", "solar", "два колектора", dict(rows=1)),
    ("so_full", "solar", "цел покрив", dict(rows=6)),
    # roof: skylights
    ("sk_one", "skylight", "еден", dict(n=1)),
    ("sk_row", "skylight", "ред", dict(n=4)),
    ("sk_big", "skylight", "голем стаклен", dict(n=1, big=1)),
]
ELEMENTS = [(i, fam, f"{FAMILIES[fam][0]}: {name}", FAMILIES[fam][1], p) for i, fam, name, p in _V]
BY_ID = {e[0]: e for e in ELEMENTS}

STYLES = {   # name -> element ids (the ЕЛЕМЕНТИ tab's presets; the user ticks more or fewer after)
    "НИШТО": [],
    "ЈУГО БЛОК 80-ТИ (панели)": ["joint_grid_2", "par_smooth_bal", "sb_std", "tow_mid", "rr_two", "rp_std", "an_many", "vt_row"],
    "ЈУГО IMS СКЕЛЕТ": ["frame_ims", "sp_red", "par_smooth_bal", "rr_std", "rp_std", "att_std"],
    "ЈУГО РЕБРА И ЛЕНТИ": ["par_ribbed", "fin_mid_2", "att_std", "rr_two", "rp_std", "tk_box"],
    "ЈУГО ЗАОБЛЕНИ БАЛКОНИ": ["par_round", "cb_round", "tr_balc", "rr_std", "rp_std", "an_one"],
    "ЈУГО ЕРКЕРИ": ["erk_2", "slab_thin", "sb_std", "tow_end", "rr_std", "rp_std"],
    "БРУТАЛИЗАМ": ["fin_deep_3", "cor_deep", "att_deep", "pil_heavy", "tow_conc", "rr_conc", "pg_std"],
    "МОДЕРНИЗАМ (брисолеј)": ["lv_h3", "slab_deep", "pil_std", "att_white", "pg_white"],
    "ШАХОВСКИ БАЛКОНИ": ["chk_std", "joint_floor", "rr_std", "rp_std"],
    "КУЌИ": ["pl_low", "sur_std", "sb_white", "can_thin"],
    "ЈУГО ШАРЕНО (бои од сликата)": ["par_photo_alt", "sp_photo_alt", "tow_photo", "dv_photo", "rr_std", "rp_std"],
    "ЈУГО НИВОА И ПРЕКИНИ": ["br_4", "cas_alt", "dw_grid", "dv_std", "par_smooth_bal", "att_stepped", "rr_two", "rp_std"],
    "МОДЕРНА СТАКЛЕНА": ["cw_spandrel", "cw_fins", "cw_corner", "cw_canopy", "att_dark", "rp_std"],
    "СТАКЛЕНА КУЛА (сина)": ["cw_grid", "cw_blue", "cw_top", "rr_std", "rp_std"],
    "ДОТРАЕНА КУЌА": ["wt_peel", "wt_stain", "wt_brick", "wt_crack", "wt_dirt", "wt_rust", "wt_broken_shutter", "wt_moss", "pl_low"],
    "ЗАПУШТЕН БЛОК": ["wt_peel", "wt_stain", "wt_roofstain", "wt_patch", "wt_styro", "wt_graffiti", "wt_dirt", "wt_rust", "an_many", "rr_std"],
    "ЈУГО БЛОК ДЕНЕС (како што е)": ["lf_half", "fp_some", "ds_some", "ld_some", "sb_std", "wt_stain", "wt_dirt", "rr_std", "rp_std", "an_many"],
    "СТАРА СКОПСКА КУЌА": ["ch_std", "pl_stone", "sur_std", "wt_peel", "wt_moss"],
    "НЕДОВРШЕНА КУЌА": ["uf_top", "rb_cols", "pl_low", "sb_white"],
    "СКОПЈЕ 2014": ["pt_six", "dn_std", "ru_block", "bl_top", "sur_std", "att_white"],
    "ИНДУСТРИЈА": ["rib_corrug", "sr_std", "vt_big"],
    "ЈУГО ДЕКОРАТИВЕН БЕТОН": ["dw_blocks", "dw_end", "par_ribbed", "frame_conc", "cor_std", "rr_conc", "rp_thick"],
}


def auto_ids(fit):
    """What the fit itself points to (no guessing beyond the photo): panel joints on bare-concrete blocks, shutter boxes where
    the photo saw blinds, a lift machine room on a flat roof of six storeys or more (lifts were compulsory there, and the fit
    found no housing), a roof parapet on flat block roofs."""
    out = []
    fh = max(2.4, float(fit.get("floor", 3.2)))
    floors = float(fit.get("h", 10)) / fh
    roof = fit.get("roof") or {}
    params = fit.get("params") or []
    if fit.get("surf") == "concrete" and floors >= 4:
        out.append("joint_grid_2")
    if any(p.get("blind") for p in params):
        out.append("sb_std")
    if floors >= 6 and roof.get("kind", "flat") == "flat" and not roof.get("hous"):
        out.append("rr_std")
    if floors >= 4 and roof.get("kind", "flat") == "flat":
        out.append("rp_std")
    if fit.get("surf") == "glass":
        out += ["cw_grid", "cw_spandrel"]
    cells = [c for w in fit.get("walls") or [] for c in (w.get("cells") or {}).values() if len(c) == 3]
    patchy = float(np.mean(np.std(np.array(cells, float), 0))) if len(cells) >= 4 else 0.0
    if fit.get("src") == "photo" and (fit.get("rough", 0.0) >= 0.18 or patchy > 28):   # the photo shows a worn wall
        out += ["wt_peel", "wt_stain", "wt_dirt"] + (["wt_crack"] if floors < 4 else [])
    return out


ARCHETYPES = {"block": "стамбен блок", "tower": "кула (9+ ката)", "house": "куќа", "glass": "стаклена (деловна)",
              "industrial": "индустрија", "old": "стара / дотраена"}


def archetype(fit):
    """The building's kind from the fit's numbers (storeys, surface, roof, wear): sets which elements make sense."""
    fh = max(2.4, float(fit.get("floor", 3.2)))
    floors = float(fit.get("h", 10)) / fh
    kind = (fit.get("roof") or {}).get("kind", "flat")
    if fit.get("surf") == "glass":
        return "glass"
    if fit.get("surf") == "metal" and floors < 3:
        return "industrial"
    if floors >= 9:
        return "tower"
    if floors >= 4:
        return "block"
    if fit.get("rough", 0.0) >= 0.2:
        return "old"
    return "house" if kind != "flat" or floors < 3 else "block"


def kit_ids(fit, opts):
    """The fit's element ids: the ticked kit (if the building is in the kit's scope) + the cue-driven ones."""
    flat = (fit.get("roof") or {}).get("kind", "flat") == "flat"
    scope = opts.get("kit_scope", "blocks")
    at = archetype(fit)
    ok = {"all": True, "blocks": at in ("block", "tower"), "houses": at in ("house", "old"), "flat": flat,
          "photo": fit.get("src") == "photo"}.get(scope, scope == at)
    ids = list(opts.get("kit") or []) if ok else []
    if opts.get("kit_auto", True):
        ids += [i for i in auto_ids(fit) if i not in ids]
    return [i for i in ids if i in BY_ID]


def _col(p, W, alt=0):
    c = p.get("col", "wall")
    if c == "photo":                                            # the wall's own measured accent colours
        acc = W.get("accent") or [tuple(W["wallc"])]
        return tuple(acc[alt % len(acc)])
    if c == "wall":
        return tuple(W["wallc"])
    if c == "dark":
        return tuple(v * 0.55 for v in W["wallc"])
    return {"white": WHITE, "conc": CONC}.get(c) or ACC.get(c, CONC)


def _floor_lines(W, p, top=False):
    """Floor line heights over the ground storey (start = first storey line to use, stop, every)."""
    fh, pv, h = W["fh"], W["pv"], W["h"]
    ys = [pv + k * fh for k in range(1, int(h / fh) + 2) if W["y_bot"] + 1.5 < pv + k * fh < h - 0.5]
    st, sp, ev = int(p.get("start", 1)), int(p.get("stop", 999)), max(1, int(p.get("every", 1)))
    return [y for j, y in enumerate(ys, 1) if st <= j <= sp and (j - st) % ev == 0]


def _edges(W):
    cols = W["cols"]
    return [c[0] for c in cols] + [cols[-1][1]] if cols else []


def _railing(out, u0, u1, y, dep, rgb, s=0.14, hh=1.0):
    out.append(((u0 + u1) / 2, dep, y + hh - 0.05, u1 - u0, 0.05, 0.05, rgb))
    n = max(2, int((u1 - u0) / s))
    if n > 60:                                                  # far apart posts on long runs: a mid rail instead of many posts
        n = int((u1 - u0) / 1.2)
        out.append(((u0 + u1) / 2, dep, y + hh * 0.45, u1 - u0, 0.03, 0.03, rgb))
    for k in range(n + 1):
        out.append((u0 + (u1 - u0) * k / n, dep, y, 0.025, 0.025, hh, rgb))


def kit_wall(ids, W):
    """Boxes of the kit's wall elements on one wall.  W: a, ln, h, fh, pv, y_bot, cols [(u0, u1)], D(u, y) = the facade's depth
    there, wins [(x0, x1, y0, y1 fractions) or None per column], balc / loggia [bool per column], wallc, first / last (the wall is
    the building's longest / ...), longest."""
    out = []
    ln, h, fh, yb, D = W["ln"], W["h"], W["fh"], W["y_bot"], W["D"]
    cols = W["cols"]
    if not cols or ln < 1.5:
        return out
    gtop = yb + fh
    for eid in ids:
        _i, fam, _n, _g, p = BY_ID[eid]
        if FAMILIES[fam][2] != "wall":
            continue
        rgb = _col(p, W)
        if fam == "fin":
            t, d, ev = p["t"], p["d"], max(1, p.get("every", 1))
            span = p.get("span", "full")
            y0, y1 = (gtop, h) if span == "upper" else ((yb, gtop) if span == "ground" else (yb, h))
            y1 += p.get("above", 0.0) if span != "ground" else 0.0
            if p.get("at") == "mid":
                us = [(c[0] + c[1]) / 2 for c in cols]
            else:
                e = _edges(W)
                us = [u for j, u in enumerate(e) if j % ev == 0 or j == len(e) - 1]
            for u in us:
                u = min(ln - t / 2, max(t / 2, u))
                out.append((u, D(u, (y0 + y1) / 2) + d / 2, y0, t, d, y1 - y0, rgb))
        elif fam in ("slab", "corbel"):
            ys = _floor_lines(W, p)
            if fam == "corbel" and p.get("top"):
                ys = [h - 0.6]
            for y in ys:
                if fam == "slab":
                    segs = [(c[0] + 0.15, c[1] - 0.15) for c in cols] if p.get("gaps") else [(0.0, ln)]
                    for u0, u1 in segs:
                        u = (u0 + u1) / 2
                        out.append((u, D(u, y + 0.5) + p["d"] / 2, y - p["t"], u1 - u0, p["d"], p["t"], rgb))
                else:
                    ev = max(1, p.get("every", 1))
                    for j, u in enumerate(_edges(W)):
                        if j % ev:
                            continue
                        u = min(ln - 0.2, max(0.2, u))
                        out.append((u, D(u, y + 0.5) + p["d"] / 2, y - p["hh"], p.get("t", 0.25), p["d"], p["hh"], rgb))
        elif fam in ("parapet", "checker", "rail"):
            ys = _floor_lines(W, p)
            dep = p["d"]
            for fi, y in enumerate(ys):
                if fam == "checker":
                    wcol = max(1, p.get("w", 1))
                    segs = [(cols[j][0], cols[min(len(cols), j + wcol) - 1][1]) for j in range(0, len(cols), wcol)
                            if ((j // wcol) + (fi if p.get("diag") else fi % 2)) % 2 == 0]
                else:
                    where = p.get("where", "all")
                    mask = W["balc"] if where == "balc" else (W["loggia"] if where == "loggia" else [True] * len(cols))
                    segs, run = [], None
                    for j, c in enumerate(cols):                # runs of neighbouring columns
                        if mask[j]:
                            run = (run[0], c[1]) if run else (c[0], c[1])
                        elif run:
                            segs.append(run)
                            run = None
                    if run:
                        segs.append(run)
                if p.get("alt"):
                    rgb = _col(p, W, fi)
                for u0, u1 in segs:
                    if u1 - u0 < 0.5:
                        continue
                    u = (u0 + u1) / 2
                    base = D(u, y + 0.5)
                    if fam == "rail":
                        if p.get("slab"):
                            out.append((u, base + dep / 2, y - 0.14, u1 - u0, dep, 0.14, tuple(W["wallc"])))
                        _railing(out, u0, u1, y, base + dep - 0.03, rgb, p.get("s", 0.14))
                        continue
                    if fam == "parapet" and p.get("where") == "loggia":
                        out.append((u, base + 0.06, y, u1 - u0, 0.12, p["hh"], rgb))
                        continue
                    out.append((u, base + dep / 2, y - 0.16, u1 - u0, dep, 0.16, tuple(W["wallc"])))        # the slab
                    hh = p.get("hh", 1.0)
                    if p.get("round"):                          # rounded ends: the front stepped back in three slices
                        cut = min(0.6, (u1 - u0) / 4)
                        out.append((u, base + dep - 0.06, y, u1 - u0 - 2 * cut, 0.12, hh, rgb))
                        for side in (-1, 1):
                            for k, (du, dd) in enumerate(((0.35, 0.04), (0.65, 0.18), (0.9, 0.45))):
                                uu = u + side * ((u1 - u0) / 2 - cut + cut * du)
                                out.append((uu, base + dep - 0.06 - dd, y, cut * 0.36, 0.12 + dd * 0.4, hh, rgb))
                    elif fam == "checker" and p.get("rail"):
                        _railing(out, u0, u1, y, base + dep - 0.03, rgb)
                    else:
                        out.append((u, base + dep - 0.06, y, u1 - u0, 0.12, hh, rgb))
                        if fam == "parapet" or fam == "checker":
                            for su in (u0 + 0.05, u1 - 0.05):    # side cheeks back to the wall
                                out.append((su, base + dep / 2, y, 0.1, dep - 0.12, hh, rgb))
                    if p.get("ribs"):
                        s = p["ribs"]
                        for k in range(1, int((u1 - u0) / s)):
                            out.append((u0 + k * s, base + dep + 0.03, y, 0.06, 0.06, hh, rgb))
                    if p.get("rail"):
                        _railing(out, u0, u1, y + hh, base + dep - 0.06, (60, 60, 62), 0.14, 0.45)
        elif fam == "joint":
            w_, dc = p.get("w", 0.035), p.get("col", "dark")
            jc = _col({"col": dc}, W)
            ys = [W["pv"] + k * fh for k in range(1, int(h / fh) + 1) if yb + 0.5 < W["pv"] + k * fh < h - 0.2]
            if p.get("half"):
                ys = sorted(ys + [y - fh / 2 for y in ys])
            for y in ys:
                out.append((ln / 2, D(ln / 2, y) + 0.015, y - w_ / 2, ln, 0.03, w_, jc))
            v = int(p.get("v", 0))
            if v:
                for j, u in enumerate(_edges(W)[1:-1], 1):
                    if j % v == 0:
                        out.append((u, D(u, h / 2) + 0.015, yb, w_, 0.03, h - yb, jc))
        elif fam == "frame":
            t, d, ev = p["t"], p["d"], max(1, p.get("every", 1))
            if p.get("cols", 1):
                e = _edges(W)
                for j, u in enumerate(e):
                    if j % ev and j != len(e) - 1:
                        continue
                    u = min(ln - t / 2, max(t / 2, u))
                    out.append((u, D(u, h / 2) + d / 2, yb, t, d, h - yb, rgb))
            if p.get("beams", 1):
                for y in _floor_lines(W, {}) + [h]:
                    out.append((ln / 2, D(ln / 2, y - 0.3) + d / 2 + 0.01, y - t, ln, d, t, rgb))
        elif fam == "erker":
            wcol, d, ev = max(1, p["w"]), p["d"], p.get("every", 3)
            floors = _floor_lines(W, {})
            if p.get("top"):
                floors = floors[-int(p["top"]):]
            if not floors:
                continue
            y0, y1 = floors[0], min(h - 0.3, floors[-1] + fh)
            starts = [max(0, len(cols) // 2 - wcol // 2)] if ev == 0 else list(range(1, len(cols) - wcol, max(1, ev)))
            for j in starts:
                u0, u1 = cols[j][0], cols[min(len(cols), j + wcol) - 1][1]
                u = (u0 + u1) / 2
                base = D(u, y0 + 0.5)
                out.append((u, base + d / 2, y0, u1 - u0, d, y1 - y0, rgb))
                for y in floors:                                # window band on its front, a glass box per floor
                    gh = fh * (0.85 if p.get("glass") else 0.5)
                    out.append((u, base + d + 0.02, y + fh * 0.3 if not p.get("glass") else y + 0.1, (u1 - u0) * 0.8, 0.04,
                                min(gh, y1 - y - 0.2), GLASS))
        elif fam in ("tower", "screen"):
            at = p.get("at", "mid")
            w_ = min(p["w"], ln * 0.4)
            u = {"mid": ln / 2, "end": ln - w_ / 2, "start": w_ / 2}[at]
            d = p["d"]
            y0 = yb
            top = h + (p.get("above", 0.0) if fam == "tower" else 0.0)
            if fam == "screen" and p.get("ground"):
                top = gtop
            base = D(u, h / 2)
            if fam == "tower":
                out.append((u, base + d / 2, y0, w_, d, top - y0, rgb))
                if p.get("screen") or p.get("gblock"):
                    _screen(out, u, base + d + 0.05, y0 + 1.0, top - 0.6, w_ * 0.6, 0.12 if p.get("gblock") else 0.25,
                            (200, 214, 220) if p.get("gblock") else tuple(v * 0.9 for v in rgb))
                else:
                    sw = p.get("strip", 0.7)
                    out.append((u, base + d + 0.02, y0 + 1.0, sw, 0.04, top - y0 - 1.6, GLASS))
            else:
                _screen(out, u, base + d / 2, y0 + (0.0 if p.get("ground") else 0.5), top - 0.3, w_, p.get("s", 0.3), rgb, d)
        elif fam == "louvre":
            n_, d, o = int(p["n"]), p["d"], p["o"]
            for j, c in enumerate(cols):
                win = W["wins"][j]
                if not win:
                    continue
                cw = c[1] - c[0]
                for y in [W["pv"] + k * fh for k in range(int(h / fh) + 1) if yb + 1.0 < W["pv"] + k * fh + fh * 0.5 < h]:
                    wx0, wx1 = c[0] + win[0] * cw, c[0] + win[1] * cw
                    wy0, wy1 = y + win[2] * fh, y + win[3] * fh
                    base = D((wx0 + wx1) / 2, (wy0 + wy1) / 2)
                    if o in ("h", "g"):
                        for k in range(n_):
                            yy = wy1 + 0.05 - (wy1 - wy0) * k / max(1, n_)
                            out.append(((wx0 + wx1) / 2, base + d / 2, yy, wx1 - wx0 + 0.2, d, 0.05, rgb))
                    if o in ("v", "g"):
                        for k in range(n_ + 1):
                            out.append((wx0 + (wx1 - wx0) * k / max(1, n_), base + d / 2, wy0, 0.05, d, wy1 - wy0, rgb))
        elif fam in ("trough", "shutterbox", "spandrel", "surround"):
            lines = _floor_lines(W, p) if fam == "trough" else \
                [W["pv"] + k * fh for k in range(int(h / fh) + 1) if yb + (1.0 if fam != "surround" else 0.5) < W["pv"] + k * fh + fh * 0.5 < h]
            for fi, y in enumerate(lines):
                for j, c in enumerate(cols):
                    win = W["wins"][j]
                    cw = c[1] - c[0]
                    if fam == "trough":
                        if p.get("where") == "balc" and not W["balc"][j]:
                            continue
                        dep = (0.9 if W["balc"][j] else 0.0) + D((c[0] + c[1]) / 2, y + 0.5)
                        hh = p.get("hh", 0.32)
                        uu = (c[0] + c[1]) / 2
                        yy = y + (0.62 if W["balc"][j] else (win[2] * fh - hh if win else 0.6))
                        out.append((uu, dep + 0.18, yy, cw * 0.85, 0.32, hh, rgb))
                        if p.get("plants"):
                            out.append((uu, dep + 0.18, yy + hh, cw * 0.8, 0.26, 0.22, (78, 122, 60)))
                        continue
                    if not win:
                        continue
                    wx0, wx1 = c[0] + win[0] * cw, c[0] + win[1] * cw
                    wy0, wy1 = y + win[2] * fh, y + win[3] * fh
                    uu = (wx0 + wx1) / 2
                    base = D(uu, (wy0 + wy1) / 2)
                    if fam == "shutterbox":
                        if not W["balc"][j]:
                            out.append((uu, base + p["d"] / 2, wy1, wx1 - wx0 + 0.1, p["d"], p["hh"], rgb))
                    elif fam == "spandrel":
                        if W["balc"][j] or wy0 - y < 0.3 or (p.get("alt") and (j + fi) % 2):
                            continue
                        sd = p.get("d", 0.02)
                        out.append((uu, base + sd / 2 + 0.005, y + 0.08, wx1 - wx0, sd, wy0 - y - 0.12, _col(p, W, j + fi) if p.get("two") else rgb))
                    else:
                        w_, d = p["w"], p["d"]
                        out.append((uu, base + d / 2, wy1, wx1 - wx0 + 2 * w_, d, w_, rgb))
                        if not p.get("top"):
                            out.append((uu, base + d / 2, wy0 - w_, wx1 - wx0 + 2 * w_, d, w_, rgb))
                            for su in (wx0 - w_ / 2, wx1 + w_ / 2):
                                out.append((su, base + d / 2, wy0, w_, d, wy1 - wy0, rgb))
        elif fam == "cornerbal":
            w_, d = min(p["w"], ln / 3), p["d"]
            sides = ["end"] if p.get("ends") == "end" else ["start", "end"]
            for side in sides:
                u0, u1 = (ln - w_, ln + d) if side == "end" else (0.0, w_)      # the end one reaches round the corner
                u = (u0 + u1) / 2
                for y in _floor_lines(W, {}):
                    base = D(min(ln - 0.1, max(0.1, u)), y + 0.5)
                    out.append((u, base + d / 2, y - 0.16, u1 - u0, d, 0.16, tuple(W["wallc"])))
                    if p.get("rail"):
                        _railing(out, u0, u1, y, base + d - 0.03, (60, 60, 62))
                    else:
                        out.append((u, base + d - 0.06, y, u1 - u0 - (0.5 if p.get("round") else 0.0), 0.12, 1.0, rgb))
                        if p.get("round"):
                            out.append((u1 - 0.18 if side == "end" else u0 + 0.18, base + d - 0.2, y, 0.3, 0.2, 1.0, rgb))
        elif fam == "canopy":
            if not (W["longest"] or p.get("all")) or ln < 6:
                continue
            u = ln / 2
            t = p.get("t", 0.2)
            base = D(u, 1.0)
            y = min(gtop - 0.1, yb + 3.0)
            out.append((u, base + p["d"] / 2, y - t, p["w"], p["d"], t, rgb))
            if p.get("posts"):
                for su in (u - p["w"] / 2 + 0.2, u + p["w"] / 2 - 0.2):
                    out.append((su, base + p["d"] - 0.2, yb, 0.16, 0.16, y - t - yb, rgb))
        elif fam == "pilotis":
            s, t = p["s"], p["t"]
            k = max(1, int(ln / s))
            for j in range(k + 1):
                u = min(ln - t / 2, max(t / 2, ln * j / k))
                dep = max(D(u, gtop + 0.5), 0.0) - t / 2 - 0.05
                if p.get("oct"):
                    for yaw_k in range(2):                       # an eight-sided column: two crossed boxes
                        out.append((u, dep, yb, t * 0.82, t * 0.82, gtop - yb, rgb, math.pi / 4 * yaw_k))
                else:
                    out.append((u, dep, yb, t, t, gtop - yb, rgb))
        elif fam == "attic":
            hh, d = p["hh"], p["d"]
            out.append((ln / 2, D(ln / 2, h - 0.3) + d / 2, h - hh, ln, d, hh + (0.25 if hh > 1 else 0.05), rgb))
            if p.get("step"):
                out.append((ln / 2, D(ln / 2, h - 0.3) + d + 0.1, h - hh * 0.45, ln, 0.2, hh * 0.45, rgb))
        elif fam == "rib":
            s, t, d = p["s"], p.get("t", 0.08), p.get("d", 0.06)
            span = p.get("span", "full")
            y0, y1 = (gtop, h) if span == "upper" else ((yb, gtop) if span == "ground" else (yb, h))
            for k in range(1, int(ln / s)):
                u = k * s
                out.append((u, D(u, (y0 + y1) / 2) + d / 2, y0, t, d, y1 - y0, rgb))
        elif fam == "plinth":
            out.append((ln / 2, D(ln / 2, 0.5) + p["d"] / 2 + 0.01, yb, ln, p["d"], p["hh"], rgb))
        elif fam == "band":
            ys = [h - p["hh"] - 0.3] if p.get("top") else [y - 0.05 for y in _floor_lines(W, p)]
            for y in ys:
                out.append((ln / 2, D(ln / 2, y + 0.2) + 0.02, y - p["hh"] / 2, ln, 0.03, p["hh"], rgb))
        elif fam == "pier":
            t, d = p["t"], p["d"]
            e = _edges(W)
            us = [t / 2, ln - t / 2] if p.get("ends") else [u for j, u in enumerate(e[1:-1], 1) if j % max(1, p.get("every", 2)) == 0]
            for u in us:
                out.append((u, D(u, h / 2) + d / 2, yb, t, d, h - yb, rgb))
        elif fam == "decowall":
            blank = [W["wins"][j] is None and not W["balc"][j] for j in range(len(cols))]
            if p.get("whole"):
                runs = [(0.0, ln)] if all(blank) else []
            else:
                runs, run = [], None
                for j, c in enumerate(cols):
                    if blank[j]:
                        run = (run[0], c[1]) if run else (c[0], c[1])
                    elif run:
                        runs.append(run)
                        run = None
                if run:
                    runs.append(run)
            for u0, u1 in runs:
                if u1 - u0 < 1.0:
                    continue
                _pattern(out, p, u0 + 0.15, u1 - 0.15, yb + 0.4, h - 0.4, D((u0 + u1) / 2, h / 2), rgb)
        elif fam == "breaker":
            ys = _floor_lines(W, {})
            ev = int(p.get("every", 4))
            if ev == 0:
                ys = ys[len(ys) // 2:len(ys) // 2 + 1]
            elif ev < 0:
                ys = ys[:1]
            else:
                ys = [y for j, y in enumerate(ys, 1) if j % ev == 0]
            d, hh = p.get("d", 0.8), p.get("hh", 0.45)
            for y in ys:
                base = D(ln / 2, y + 0.5)
                out.append((ln / 2, base + 0.012, y - 0.42, ln, 0.02, 0.36, DARK))             # the shadow gap
                out.append((ln / 2, base + d / 2, y - 0.06, ln, d, hh, rgb if p.get("col") else CONC))
        elif fam == "cascade":
            d, dr = p["d"], p.get("dir", 0)
            floors = _floor_lines(W, {})
            ns = max(1, int(round(len(cols) / 3)))
            secs = [(cols[int(k * len(cols) / ns)][0], cols[int((k + 1) * len(cols) / ns) - 1][1]) for k in range(ns)]
            for k, (u0, u1) in enumerate(secs):
                for fi, y in enumerate(floors):
                    dep = d * (fi + 1) / max(1, len(floors)) * 2 if dr > 0 else (d * (len(floors) - fi) / max(1, len(floors)) * 2 if dr < 0 else (d if k % 2 == 0 else 0.0))
                    if dep < 0.08:
                        continue
                    u = (u0 + u1) / 2
                    base = D(u, y + 0.5)
                    c_ = _col(p, W, k) if p.get("col") else tuple(W["wallc"])
                    out.append((u, base + dep / 2, y - 0.2, u1 - u0, dep, 0.2, c_))                 # the floor's edge
                    for su in (u0 + 0.08, u1 - 0.08):
                        out.append((su, base + dep / 2, y, 0.16, dep, min(fh, h - y - 0.1), c_))
        elif fam == "divider":
            d, ev = p["d"], max(1, p.get("every", 1))
            y0 = yb if p.get("full") else gtop
            for j, u in enumerate(_edges(W)):
                if j % ev:
                    continue
                u = min(ln - 0.08, max(0.08, u))
                base = D(u, h / 2)
                if not p.get("cut"):
                    out.append((u, base + d / 2, y0, 0.15, d, h - 0.2 - y0, rgb))
                    continue
                for y in [y0] + _floor_lines(W, {}):              # a wall with an opening on every floor
                    if y >= h - 0.5:
                        continue
                    fy = min(fh, h - 0.2 - y)
                    out.append((u, base + d / 2, y, 0.15, d, fy * 0.35, rgb))
                    out.append((u, base + d / 2, y + fy * 0.75, 0.15, d, fy * 0.25, rgb))
                    out.append((u, base + d * 0.12, y + fy * 0.35, 0.15, d * 0.24, fy * 0.4, rgb))
                    out.append((u, base + d * 0.88, y + fy * 0.35, 0.15, d * 0.24, fy * 0.4, rgb))
        elif fam == "curtain":
            sp, fin = p.get("s", 1.5), p.get("fin", 0.0)
            mc = _col(p, W) if p.get("col") else (52, 56, 60)
            tint = {"blue": (70, 110, 160), "green": (90, 140, 130), "bronze": (130, 104, 80)}.get(p.get("tint"))
            y0 = gtop if p.get("top") is None else max(yb, h - fh)
            if p.get("top") is None:
                y0 = yb
            if tint:
                out.append((ln / 2, D(ln / 2, h / 2) + 0.03, y0, ln - 0.05, 0.02, h - y0, tint))
            if sp:
                for k in range(int(ln / sp) + 1):
                    u = min(ln - 0.04, max(0.04, k * sp))
                    if p.get("corner") and (k == 0 or u >= ln - 0.05):
                        continue
                    out.append((u, D(u, h / 2) + max(0.06, fin) / 2 + 0.03, y0, 0.06, max(0.06, fin), h - y0, mc))
            if p.get("horiz", 1):
                for y in [W["pv"] + k * fh for k in range(int(h / fh) + 1) if y0 < W["pv"] + k * fh < h]:
                    sh_ = p.get("spand", 0.0)
                    out.append((ln / 2, D(ln / 2, y) + 0.05, y - (sh_ or 0.06), ln, 0.05, sh_ or 0.08, mc if not sh_ else
                                (_col(p, W) if p.get("col") else (40, 44, 50))))
            if p.get("canopy") and W["longest"]:
                out.append((ln / 2, D(ln / 2, 1.0) + 1.2, min(gtop - 0.2, yb + 3.2), min(ln * 0.6, 8.0), 2.4, 0.08, (150, 176, 190)))
        elif fam == "weather":
            rnd = np.random.default_rng(int(abs(W["a"][0] * 7.3 + W["a"][1] * 13.1)) % (2 ** 31) + len(eid))
            k, n_ = p["k"], int(p["n"] * max(1.0, ln / 12.0))
            wc = np.array(W["wallc"], float)
            for _ in range(min(n_, 40)):
                u = float(rnd.uniform(0.4, ln - 0.4))
                if k in ("peel", "brick", "patch", "styro", "moss"):
                    w_, hh = float(rnd.uniform(0.4, 1.8)), float(rnd.uniform(0.3, 1.4))
                    y = float(rnd.uniform(yb + 0.3, h - hh - 0.2))
                    c_ = {"peel": wc * 0.78 + np.array([8, 4, 0]), "brick": np.array(ACC["brick"]) * 0.9, "patch": np.minimum(255, wc * 1.12),
                          "styro": np.array((236, 234, 226)), "moss": np.array((86, 102, 62))}[k]
                    if k == "moss":
                        y = float(rnd.choice([yb + 0.05, h - hh - 0.1]))
                    out.append((u, D(u, y + hh / 2) + 0.01 + (0.04 if k == "styro" else 0.0), y, w_, 0.02 + (0.06 if k == "styro" else 0.0), hh, tuple(c_)))
                elif k in ("stain", "topstain"):
                    w_ = float(rnd.uniform(0.15, 0.5))
                    if k == "stain":
                        y1 = float(rnd.uniform(yb + 2.0, h - 0.5))
                        hh = float(rnd.uniform(0.8, 2.5))
                    else:
                        y1, hh = h - 0.1, float(rnd.uniform(1.0, 3.0))
                    out.append((u, D(u, y1 - hh / 2) + 0.012, max(yb, y1 - hh), w_, 0.02, min(hh, y1 - yb), tuple(wc * 0.68)))
                elif k == "graffiti":
                    c_ = list(ACC.values())[int(rnd.integers(len(ACC)))]
                    w_, hh = float(rnd.uniform(0.8, 2.6)), float(rnd.uniform(0.4, 1.1))
                    out.append((u, D(u, 1.0) + 0.012, yb + float(rnd.uniform(0.2, 0.8)), w_, 0.02, hh, c_))
                elif k == "crack":
                    y = float(rnd.uniform(yb + 0.5, h - 1.5))
                    for s_ in range(4):                         # a zig-zag of short dark strokes
                        out.append((u + s_ * 0.12 * (1 if s_ % 2 else -1), D(u, y) + 0.012, y + s_ * 0.3, 0.03, 0.02, 0.34, tuple(wc * 0.45)))
                elif k == "dirt":
                    out.append((ln / 2, D(ln / 2, 0.4) + 0.012, yb, ln, 0.02, 0.6 + float(rnd.uniform(0, 0.4)), tuple(wc * 0.62)))
                    break
                elif k == "rust":
                    y = float(rnd.choice(_floor_lines(W, {}) or [h - 0.3]))
                    out.append((u, D(u, y) + 0.25, y + 0.9, float(rnd.uniform(0.6, 2.0)), 0.05, 0.08, (126, 70, 40)))
                elif k in ("boarded", "shutter"):
                    j = int(rnd.integers(len(cols)))
                    win = W["wins"][j]
                    if not win:
                        continue
                    c0, c1 = cols[j]
                    cw = c1 - c0
                    fl = _floor_lines(W, {}) or [yb]
                    y = float(rnd.choice([yb] + fl)) if k == "boarded" else float(rnd.choice(fl))
                    wx0, wx1, wy0, wy1 = c0 + win[0] * cw, c0 + win[1] * cw, y + win[2] * fh, y + win[3] * fh
                    uu = (wx0 + wx1) / 2
                    if k == "boarded":
                        for q in range(4):
                            out.append((uu, D(uu, wy0) + 0.03, wy0 + (wy1 - wy0) * q / 4, wx1 - wx0 + 0.1, 0.03, (wy1 - wy0) / 4.4, (120, 92, 64)))
                    else:
                        out.append((uu + (wx1 - wx0) * 0.08, D(uu, wy0) + 0.05, wy0 + (wy1 - wy0) * 0.35, wx1 - wx0, 0.03, (wy1 - wy0) * 0.6,
                                    (150, 140, 120)))
        elif fam in ("loggiafill", "flatpaint", "laundry", "dish", "unfinished"):
            rnd = np.random.default_rng(int(abs(W["a"][0] * 3.7 + W["a"][1] * 11.3)) % (2 ** 31) + len(eid))
            floors = [yb] + _floor_lines(W, {}) if fam in ("flatpaint", "unfinished") else _floor_lines(W, {})
            if fam == "unfinished":
                floors = floors[-int(p["floors"]):]
            share = p.get("share", 1.0)
            colv = [rnd.random() for _ in cols]
            for fi, y in enumerate(floors):
                yt = min(h, y + fh)
                for j, c in enumerate(cols):
                    c0, c1 = c
                    cw, uu = c1 - c0, (c0 + c1) / 2
                    r_ = colv[j] if p.get("vert") else rnd.random()
                    base = D(uu, y + 0.5)
                    bd = W["bdep"][j]
                    if fam == "loggiafill":
                        if not (W["balc"][j] or W["loggia"][j]) or r_ > share:
                            continue
                        mix = p.get("mix") or ("pvc", "alu", "pvc", "wood")[int(rnd.integers(4))]
                        fc = {"pvc": (236, 236, 232), "alu": (104, 80, 60), "wood": (138, 96, 62)}[mix]
                        dep = base + (bd - 0.08 if W["balc"][j] else 0.05)
                        gt = (int(rnd.integers(70, 120)), int(rnd.integers(84, 130)), int(rnd.integers(96, 140)))
                        out.append((uu, dep, y + 1.0, cw * 0.94, 0.04, yt - y - 1.25, gt))                  # glass over the parapet
                        out.append((uu, dep + 0.03, yt - 0.3, cw * 0.96, 0.06, 0.06, fc))
                        out.append((uu, dep + 0.03, y + 0.98, cw * 0.96, 0.06, 0.06, fc))
                        for k in range(3):
                            out.append((c0 + cw * (0.03 + 0.47 * k), dep + 0.03, y + 1.0, 0.06, 0.06, yt - y - 1.3, fc))
                        if W["loggia"][j] and not W["balc"][j]:
                            out.append((uu, dep, y, cw * 0.94, 0.04, 1.0, tuple(v * float(rnd.uniform(0.85, 1.1)) for v in W["wallc"])))
                    elif fam == "flatpaint":
                        if r_ > share:
                            continue
                        pc = [(232, 206, 120), (236, 168, 104), (230, 160, 136), (164, 200, 152), (152, 182, 212), (236, 224, 196)][int(r_ * 997) % 6]
                        _around(out, W, j, y, yt, base + 0.03, 0.04, pc)
                    elif fam == "unfinished":
                        _around(out, W, j, y, yt, base + 0.02, 0.03, (166, 86, 62))
                        for yy in np.arange(y + 0.25, yt, 0.25):           # brick courses
                            out.append((uu, base + 0.045, float(yy), cw, 0.01, 0.02, (120, 112, 104)))
                    elif fam == "laundry":
                        if not W["balc"][j] or r_ > share:
                            continue
                        for k in range(3):
                            out.append((uu, base + bd + 0.12 + 0.12 * k, y + 1.05, cw * 0.7, 0.02, 0.02, (210, 210, 210)))
                        cc = list(ACC.values())[int(rnd.integers(len(ACC)))]
                        out.append((uu + float(rnd.uniform(-0.3, 0.3)), base + bd + 0.24, y + 0.55, 0.5, 0.02, 0.48, cc))
                    else:
                        if not W["balc"][j] or r_ > share:
                            continue
                        out.append((c0 + cw * float(rnd.uniform(0.2, 0.8)), base + bd - 0.15, y + 1.0, 0.62, 0.08, 0.62, (226, 226, 222)))
        elif fam == "flue":
            rnd = np.random.default_rng(int(abs(W["a"][0] * 5.1 + W["a"][1] * 2.9)) % (2 ** 31))
            if ln < 4:
                continue
            for _ in range(int(p["n"])):
                u = float(rnd.uniform(0.5, ln - 0.5))
                out.append((u, D(u, h / 2) + 0.22, yb + float(rnd.uniform(0.5, 3.0)), 0.16, 0.16, h + 1.2 - yb - 2.0, (110, 112, 114)))
                out.append((u, D(u, h / 2) + 0.22, h + 1.0, 0.3, 0.3, 0.12, (90, 92, 94)))
        elif fam == "chardak":
            d = p["d"]
            fl = _floor_lines(W, {})
            if not fl:
                continue
            y = fl[0]
            base = D(ln / 2, y + 0.5)
            out.append((ln / 2, base + d / 2, y - 0.2, ln, d, 0.2, (138, 100, 70)))           # the floor's beam end
            out.append((ln / 2, base + d - 0.04, y, ln, 0.08, h - y - 0.1, tuple(W["wallc"])))   # the front wall, out over the street
            for su in (0.04, ln - 0.04):
                out.append((su, base + d / 2, y, 0.08, d, h - y - 0.1, tuple(W["wallc"])))
            if p.get("brackets", 1):
                for u in _edges(W):
                    u = min(ln - 0.1, max(0.1, u))
                    for k in range(3):                          # a diagonal timber bracket as three steps
                        out.append((u, base + d * (k + 1) / 6, y - 0.25 - 0.25 * (2 - k), 0.12, d * (k + 1) / 3, 0.25, (110, 80, 56)))
        elif fam == "portico":
            if not W["longest"] or ln < 8:
                continue
            ncol = int(p["n"]) or max(2, len(cols) + 1)
            top = min(h - 0.4, yb + 2 * fh + 1.0) if p["n"] else h - 0.4
            wv = min(ln * 0.8, 3.2 * (ncol - 1)) if p["n"] else ln - 0.6
            dep = 0.3 if p.get("engaged") else 2.0
            for k in range(ncol):
                u = ln / 2 - wv / 2 + wv * k / max(1, ncol - 1)
                base = D(u, 1.0)
                for yk in range(2):
                    out.append((u, base + dep - 0.35, yb, 0.62, 0.62, top - yb, WHITE, math.pi / 4 * yk))
                out.append((u, base + dep - 0.35, yb, 0.85, 0.85, 0.35, WHITE))
                out.append((u, base + dep - 0.35, top - 0.3, 0.85, 0.85, 0.3, WHITE))
            if not p.get("engaged"):
                base = D(ln / 2, top)
                out.append((ln / 2, base + dep / 2, top, wv + 1.2, dep + 0.2, 0.7, WHITE))      # entablature
                for k in range(6):                              # the pediment, in steps
                    ww = (wv + 1.2) * (1 - k / 6)
                    out.append((ln / 2, base + 0.2 + dep / 2, top + 0.7 + k * 0.32, ww, 0.4, 0.32, WHITE))
        elif fam == "dentil":
            y = h - 0.7
            base = D(ln / 2, y)
            out.append((ln / 2, base + 0.2, y + 0.25, ln, 0.4, 0.3, WHITE))
            for k in range(int(ln / p["s"])):
                out.append((k * p["s"] + p["s"] / 2, base + 0.1, y, p["s"] * 0.5, 0.2, 0.25, WHITE))
        elif fam == "rustic":
            s_ = p["s"]
            for k, y in enumerate(np.arange(yb + s_, gtop, s_)):
                out.append((ln / 2, D(ln / 2, 1.0) + 0.012, float(y), ln, 0.02, 0.04, tuple(v * 0.6 for v in W["wallc"])))
                if p.get("blocks"):
                    for u in np.arange(s_ * (k % 2 + 1), ln, s_ * 2):
                        out.append((float(u), D(float(u), 1.0) + 0.012, float(y) - s_, 0.04, 0.02, s_, tuple(v * 0.6 for v in W["wallc"])))
        elif fam == "baluster":
            spots = [(0.0, ln, h, D(ln / 2, h - 0.5))] if p.get("top") else \
                [(c[0], c[1], y, D((c[0] + c[1]) / 2, y + 0.5) + W["bdep"][j] - 0.08) for y in _floor_lines(W, {}) for j, c in enumerate(cols) if W["balc"][j]]
            for u0, u1, y, dep in spots[:60]:
                out.append(((u0 + u1) / 2, dep, y + 0.8, u1 - u0, 0.2, 0.12, WHITE))
                for u in np.arange(u0 + 0.15, u1 - 0.1, 0.28):
                    out.append((float(u), dep, y, 0.12, 0.12, 0.8, WHITE))
        elif fam == "shopfront":
            if ln < 5 or gtop > h - 0.5:
                continue
            rnd = np.random.default_rng(int(abs(W["a"][0] * 9.7 + W["a"][1] * 1.3)) % (2 ** 31))
            nshop = max(1, int(ln / 6))
            for k in range(nshop):
                u0, u1 = ln * k / nshop + 0.3, ln * (k + 1) / nshop - 0.3
                u = (u0 + u1) / 2
                base = D(u, 1.0)
                cc = list(ACC.values())[int(rnd.integers(len(ACC)))]
                out.append((u, base + 0.03, yb + 0.3, u1 - u0, 0.04, 2.1, (90, 96, 102) if rnd.random() < 0.4 else GLASS))
                if p.get("sign"):
                    out.append((u, base + 0.1, yb + 2.6, (u1 - u0) * 0.8, 0.2, 0.55, cc))
                if p.get("awning"):
                    for q in range(3):
                        out.append((u, base + 0.3 + q * 0.35, yb + 2.45 - q * 0.12, u1 - u0, 0.36, 0.06, cc))
                if p.get("kiosk") and k % 2 == 0:
                    out.append((u, base + 1.2, yb, min(3.0, u1 - u0), 2.2, 2.6, tuple(v * 0.95 for v in cc)))
                    out.append((u, base + 1.2, yb + 2.6, min(3.0, u1 - u0) + 0.3, 2.5, 0.12, (80, 80, 82)))
    return out


def _around(out, W, j, y, yt, dep, sd, rgb):
    """Paint a storey cell round its window (the window stays open)."""
    c0, c1 = W["cols"][j]
    cw = c1 - c0
    win = W["wins"][j]
    fh = W["fh"]
    if not win or yt - y < fh * 0.9:
        out.append(((c0 + c1) / 2, dep, y, cw, sd, yt - y, rgb))
        return
    wx0, wx1, wy0, wy1 = c0 + win[0] * cw, c0 + win[1] * cw, y + win[2] * fh, y + win[3] * fh
    out.append(((c0 + wx0) / 2, dep, y, wx0 - c0, sd, yt - y, rgb))
    out.append(((wx1 + c1) / 2, dep, y, c1 - wx1, sd, yt - y, rgb))
    out.append(((wx0 + wx1) / 2, dep, y, wx1 - wx0, sd, wy0 - y, rgb))
    out.append(((wx0 + wx1) / 2, dep, wy1, wx1 - wx0, sd, yt - wy1, rgb))


def _pattern(out, p, u0, u1, y0, y1, base, rgb):
    """A relief pattern of a decorative concrete wall between u0..u1, y0..y1 (at most ~120 boxes)."""
    pat, s, d = p["pat"], p["s"], p.get("d", 0.07)
    w, hgt = u1 - u0, y1 - y0
    if w < 0.5 or hgt < 0.5:
        return
    s = max(s, w / 30, hgt / 40)
    if pat in ("grid", "vert"):
        for k in range(int(w / s) + 1):
            out.append((u0 + k * s, base + d / 2, y0, 0.08, d, hgt, rgb))
    if pat in ("grid", "horiz", "wave"):
        for k in range(int(hgt / s) + 1):
            dd = d * (1.8 if pat == "wave" and k % 2 else 1.0)
            out.append(((u0 + u1) / 2, base + dd / 2, y0 + k * s, w, dd, 0.08 if pat != "wave" else s * 0.5, rgb))
    if pat in ("diamond", "blocks"):
        for i in range(int(hgt / s)):
            for k in range(int(w / s)):
                if pat == "diamond" and (i + k) % 2:
                    continue
                uu = u0 + (k + 0.5 + (0.5 if pat == "blocks" and i % 2 else 0.0)) * s
                if uu > u1 - s * 0.3:
                    continue
                out.append((uu, base + d / 2, y0 + i * s + s * 0.15, s * (0.5 if pat == "diamond" else 0.8), d, s * (0.5 if pat == "diamond" else 0.4), rgb))


def _screen(out, u, dep, y0, y1, w, s, rgb, d=0.12):
    """A perforated screen (claustra / glass blocks): a grid of slats both ways."""
    if y1 - y0 < 0.5 or w < 0.4:
        return
    nh, nv = min(40, int((y1 - y0) / s)), min(20, int(w / s))
    for k in range(nh + 1):
        out.append((u, dep, y0 + (y1 - y0) * k / max(1, nh) - 0.03, w, d, 0.06, rgb))
    for k in range(nv + 1):
        out.append((u - w / 2 + w * k / max(1, nv), dep, y0, 0.06, d, y1 - y0, rgb))


def _inside(p, r):
    x, z = p
    c = False
    n = len(r)
    for i in range(n):
        (x1, z1), (x2, z2) = r[i], r[(i + 1) % n]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1 + 1e-12) + x1:
            c = not c
    return c


def kit_roof(ids, ring, h, wallc, roof=None):
    """Boxes of the kit's roof elements -> [(x, z, y0, sx, sz, hh, rgb, yaw)].  Placed along the outline's longest edge
    direction, inside the outline; only on flat roofs (roof kind flat or none)."""
    if (roof or {}).get("kind", "flat") not in ("flat", None):
        return []
    r = np.asarray(ring, float)
    n = len(r)
    if n < 3:
        return []
    e = [(float(np.hypot(*(r[(i + 1) % n] - r[i]))), i) for i in range(n)]
    li = max(e)[1]
    t = (r[(li + 1) % n] - r[li]) / max(1e-6, max(e)[0])
    nv = np.array([-t[1], t[0]])
    yaw = math.atan2(t[1], t[0])
    c = r.mean(0)
    pu, pn = (r - c) @ t, (r - c) @ nv
    L, Wd = float(pu.max() - pu.min()), float(pn.max() - pn.min())
    cu, cn = float(pu.max() + pu.min()) / 2, float(pn.max() + pn.min()) / 2
    c = c + t * cu + nv * cn
    out = []

    def at(u, v):
        return c + t * u + nv * v

    def put(u, v, y0, su, sv, hh, rgb, ok=True):
        q = at(u, v)
        if ok and not _inside(q, r):
            return
        out.append((float(q[0]), float(q[1]), y0, su, sv, hh, rgb, yaw))
    for eid in ids:
        _i, fam, _n, _g, p = BY_ID[eid]
        if FAMILIES[fam][2] != "roof":
            continue
        rgb = _col(p, {"wallc": wallc})
        if fam == "roofroom":
            k = int(p.get("n", 1))
            for j in range(k):
                u = (j + 0.5) / k * L - L / 2 if k > 1 else 0.0
                put(u, 0.0, h, min(p["w"], L * 0.3), min(p["d"], Wd * 0.5), p["hh"], tuple(v * 0.97 for v in rgb))
                if p.get("lid"):
                    put(u, 0.0, h + p["hh"], min(p["w"], L * 0.3) + 0.3, min(p["d"], Wd * 0.5) + 0.3, 0.15, CONC)
        elif fam == "tank":
            for j in range(int(p.get("n", 1))):
                u = L * 0.25 * (1 if j else -1) if p.get("n", 1) > 1 else -L * 0.2
                y = h + p["legs"] + (2.6 if p.get("box") else 0.0)
                if p["legs"]:
                    for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                        put(u + du * p["r"] * 0.6, dv * p["r"] * 0.6, h, 0.12, 0.12, p["legs"], DARK)
                for k in range(2):                              # an eight-sided tank: two crossed boxes
                    q = at(u, 0.0)
                    if _inside(q, r):
                        out.append((float(q[0]), float(q[1]), y, p["r"] * 1.6, p["r"] * 1.6, p["hh"], (190, 190, 186), yaw + math.pi / 4 * k))
        elif fam == "pergola":
            w_ = min(p["w"] or L * 0.8, L * 0.8)
            d = min(p["d"], Wd * 0.6)
            s = p.get("s", 1.0)
            u0 = L / 2 - w_ / 2 - 1.0 if p["w"] else 0.0
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                put(u0 + du * w_ / 2, dv * d / 2, h, 0.2, 0.2, p["hh"], rgb)
            for k in range(int(w_ / s) + 1):
                put(u0 - w_ / 2 + k * s, 0.0, h + p["hh"], 0.12, d + 0.4, 0.2, rgb)
            for dv in (-1, 1):
                put(u0, dv * d / 2, h + p["hh"] - 0.25, w_ + 0.4, 0.18, 0.25, rgb)
        elif fam == "antenna":
            k = int(p["n"])
            for j in range(k):
                u = (j + 0.5) / k * L * 0.7 - L * 0.35
                v = Wd * 0.25 * (1 if j % 2 else -1) if k > 1 else Wd * 0.2
                if p.get("dish"):
                    put(u, v, h + 0.3, 0.9, 0.12, 0.9, (220, 220, 216))
                    put(u, v, h, 0.06, 0.06, 0.6, DARK)
                else:
                    put(u, v, h, 0.06, 0.06, p["hh"], DARK)
                    for y in (0.6, 0.8):
                        put(u, v, h + p["hh"] * y, 1.2, 0.04, 0.04, DARK)
        elif fam == "vents":
            k, w_ = int(p["n"]), p.get("w", 0.5)
            for j in range(k):
                u = (j + 0.5) / k * L * 0.8 - L * 0.4
                v = -Wd * 0.25 if p.get("pair") and j % 2 else Wd * 0.25
                put(u, v, h, w_, w_, p["hh"], tuple(v_ * 0.9 for v_ in wallc))
                put(u, v, h + p["hh"], w_ + 0.12, w_ + 0.12, 0.08, (90, 90, 92))
        elif fam in ("rparapet", "roofrail"):
            th = p.get("t", 0.2)
            for i in range(n):
                a, b = r[i], r[(i + 1) % n]
                ln = float(np.hypot(*(b - a)))
                if ln < 0.3:
                    continue
                tt = (b - a) / ln
                nin = np.array([-tt[1], tt[0]])
                if not _inside((a + b) / 2 + nin * 0.3, r):
                    nin = -nin
                yw = math.atan2(tt[1], tt[0])
                if fam == "rparapet":
                    q = (a + b) / 2 + nin * (th / 2 + 0.01)
                    out.append((float(q[0]), float(q[1]), h, ln - 0.02, th, p["hh"], rgb, yw))
                else:
                    s = p.get("s", 1.2)
                    q = (a + b) / 2 + nin * 0.1
                    out.append((float(q[0]), float(q[1]), h + p["hh"] - 0.05, ln, 0.05, 0.05, rgb, yw))
                    out.append((float(q[0]), float(q[1]), h + p["hh"] * 0.5, ln, 0.03, 0.03, rgb, yw))
                    for k in range(int(ln / s) + 1):
                        q2 = a + tt * min(ln, k * s) + nin * 0.1
                        out.append((float(q2[0]), float(q2[1]), h, 0.04, 0.04, p["hh"], rgb, yw))
        elif fam == "solar":
            k = int(p["rows"])
            for j in range(k):
                v = (j + 0.5) / k * Wd * 0.6 - Wd * 0.3
                for s_ in range(3):                             # a tilted panel as three steps
                    put(-L * 0.15, v + s_ * 0.35, h + 0.2 + s_ * 0.3, min(6.0, L * 0.4), 0.4, 0.06, (40, 52, 80))
        elif fam == "nadgradba":
            fh = 3.0
            sx, sz = L * 0.8, Wd * 0.72
            c_ = rgb if p.get("col") else tuple(min(255, v * 1.08) for v in wallc)
            put(0.0, 0.0, h, sx, sz, fh if p["kind"] == "box" else 1.2, c_)
            if p["kind"] == "pitched":
                for k in range(5):                              # a gabled roof over the added storey, in steps
                    put(0.0, 0.0, h + 1.2 + k * 0.45, sx + 0.4, (sz + 0.6) * (1 - k / 5), 0.45, (150, 82, 62))
            else:
                put(0.0, 0.0, h + fh, sx + 0.3, sz + 0.3, 0.15, CONC)
        elif fam == "sawroof":
            s_ = p["s"]
            for k in range(int(L / s_)):
                u = -L / 2 + (k + 0.5) * s_
                for q in range(4):
                    put(u + q * s_ * 0.12, 0.0, h + q * 0.5, s_ * (1 - q * 0.24), Wd * 0.92, 0.5, (150, 150, 146))
                put(u - s_ / 2 + 0.05, 0.0, h + 0.3, 0.06, Wd * 0.9, 1.6, (120, 150, 170))
        elif fam == "billboard":
            if p.get("mast"):
                put(L * 0.25, 0.0, h, 0.6, 0.6, 9.0, (150, 150, 150))
                for k in range(3):
                    put(L * 0.25 + 0.4 * (k - 1), 0.4, h + 7.0, 0.3, 0.12, 1.4, (220, 220, 216))
            else:
                w_ = min(p["w"], L * 0.8)
                for du in (-w_ / 3, w_ / 3):
                    put(du, 0.0, h, 0.2, 0.2, 2.0, DARK)
                put(0.0, 0.0, h + 2.0, w_, 0.25, 3.5, list(ACC.values())[int(abs(c[0] * 7)) % len(ACC)])
        elif fam == "plantscreen":
            w_, d = min(5.0, L * 0.4), min(4.0, Wd * 0.5)
            for k in range(int(p["hh"] / 0.25)):
                for dv in (-d / 2, d / 2):
                    put(L * 0.2, dv, h + 0.2 + k * 0.25, w_, 0.05, 0.12, (170, 170, 168))
                for du in (-w_ / 2, w_ / 2):
                    put(L * 0.2 + du, 0.0, h + 0.2 + k * 0.25, 0.05, d, 0.12, (170, 170, 168))
        elif fam == "rebar":
            for i in range(n):
                a, b = r[i], r[(i + 1) % n]
                ln = float(np.hypot(*(b - a)))
                for k in range(max(1, int(ln / 4.0))):
                    q = a + (b - a) * k / max(1, int(ln / 4.0))
                    for dx, dz in ((-0.1, -0.1), (0.1, -0.1), (0.1, 0.1), (-0.1, 0.1)):
                        out.append((float(q[0]) + dx, float(q[1]) + dz, h, 0.02, 0.02, p["hh"], (110, 64, 40), yaw))
        elif fam == "skylight":
            k = int(p["n"])
            for j in range(k):
                u = (j + 0.5) / k * L * 0.6 - L * 0.3
                sz = 3.0 if p.get("big") else 1.2
                put(u, -Wd * 0.2, h, sz, sz, 0.35, (150, 176, 196))
    return out
