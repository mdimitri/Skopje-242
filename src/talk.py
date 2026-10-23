"""Кој што зборува на улица: скопски личности, населби, време од денот, политика, шеги - и колку грубо (мени).

say(p, sim) ја бира репликата за пешакот p. Нивоа на јазик (мени „Јазик“): 0 пристојно (без пцовки и навреди),
1 улично (сленг, „сељак“, „ѓубре“), 2 без цензура (вистински пцовки). Агресивност (мени) ги прави луѓето почесто нервозни.
Шегите се за професии, населби и навики, а не за етнички групи; политиката е без имиња на живи луѓе.
Сè е оригинален текст, непроверен од мајчин говорител (docs/TEXT_SOURCES.md)."""
from texts import TXT
import random

import bible_lines
import peds_lines
import problems

# ---------------------------------------------------------------------------------------- words that mark a level
RUDE = (TXT("talk.0001"), TXT("talk.0002"), TXT("talk.0003"), TXT("talk.0004"), TXT("talk.0005"), TXT("talk.0006"), TXT("talk.0007"), TXT("talk.0008"), TXT("talk.0009"), TXT("talk.0010"), TXT("talk.0011"),
        TXT("talk.0012"), TXT("talk.0013"), TXT("talk.0014"), TXT("talk.0015"), TXT("talk.0016"), TXT("talk.0017"), TXT("talk.0018"), TXT("talk.0019"), TXT("talk.0020"), TXT("talk.0021"), TXT("talk.0022"), TXT("talk.0023"), TXT("talk.0024"), TXT("talk.0025"))
NSFW = [TXT("talk.0026"), TXT("talk.0027"), TXT("talk.0028"), TXT("talk.0029"), TXT("talk.0030"),
        TXT("talk.0031"), TXT("talk.0032"), TXT("talk.0033"),
        TXT("talk.0034"), TXT("talk.0035"), TXT("talk.0036"),
        TXT("talk.0037"), TXT("talk.0038"), TXT("talk.0039"), TXT("talk.0040")]
NSFW += bible_lines.NSFW_MAX                         # (ниво 2: уште погруби, од речникот и пошироко)
POLITE_INSULT = [TXT("talk.0041"), TXT("talk.0042"), TXT("talk.0043"), TXT("talk.0044"),
                 TXT("talk.0045"), TXT("talk.0046")]
STREET_INSULT = [TXT("talk.0047"), TXT("talk.0048"), TXT("talk.0049"), TXT("talk.0050"), TXT("talk.0051"), TXT("talk.0052"),
                 TXT("talk.0053"), TXT("talk.0054"), TXT("talk.0055"), TXT("talk.0056")]


# ---------------------------------------------------------------------------------------- street jargon (round 8)
JARGON = [
    TXT("talk.0057"), TXT("talk.0058"), TXT("talk.0059"), TXT("talk.0060"),
    TXT("talk.0061"), TXT("talk.0062"),
    TXT("talk.0063"), TXT("talk.0064"),
    TXT("talk.0065"), TXT("talk.0066"), TXT("talk.0067"),
    TXT("talk.0068"), TXT("talk.0069"),
    TXT("talk.0070"), TXT("talk.0071"),
    TXT("talk.0072"), TXT("talk.0073"),
    TXT("talk.0074"), TXT("talk.0075"),
    TXT("talk.0076"), TXT("talk.0077"),
    TXT("talk.0078"), TXT("talk.0079"),
    TXT("talk.0080"), TXT("talk.0081"), TXT("talk.0082"),
    TXT("talk.0083"), TXT("talk.0084"), TXT("talk.0085"), TXT("talk.0086"),
    TXT("talk.0087"), TXT("talk.0088"),
    TXT("talk.0089"), TXT("talk.0090"), TXT("talk.0091"), TXT("talk.0092"),
    TXT("talk.0093"), TXT("talk.0094"), TXT("talk.0095"), TXT("talk.0096"),
    TXT("talk.0097"), TXT("talk.0098"),
    TXT("talk.0099"), TXT("talk.0100"),
    TXT("talk.0101"), TXT("talk.0102"), TXT("talk.0103"),
    TXT("talk.0104"), TXT("talk.0105"),
    TXT("talk.0106"), TXT("talk.0107"), TXT("talk.0108"),
    TXT("talk.0109"), TXT("talk.0110"), TXT("talk.0111"),
    TXT("talk.0112"), TXT("talk.0113"), TXT("talk.0114"),
    TXT("talk.0115"), TXT("talk.0116"), TXT("talk.0117"),
    TXT("talk.0118"), TXT("talk.0119"), TXT("talk.0120"),
]
# ---------------------------------------------------------------------------------------- first person (round 9)
ME = [
    TXT("talk.0121"), TXT("talk.0122"),
    TXT("talk.0123"), TXT("talk.0124"),
    TXT("talk.0125"), TXT("talk.0126"),
    TXT("talk.0127"), TXT("talk.0128"),
    TXT("talk.0129"), TXT("talk.0130"),
    TXT("talk.0131"), TXT("talk.0132"),
    TXT("talk.0133"), TXT("talk.0134"),
    TXT("talk.0135"), TXT("talk.0136"),
    TXT("talk.0137"), TXT("talk.0138"),
    TXT("talk.0139"), TXT("talk.0140"),
    TXT("talk.0141"), TXT("talk.0142"),
    TXT("talk.0143"), TXT("talk.0144"),
    TXT("talk.0145"), TXT("talk.0146"),
    TXT("talk.0147"), TXT("talk.0148"),
    TXT("talk.0149"), TXT("talk.0150"),
    TXT("talk.0151"), TXT("talk.0152"),
    TXT("talk.0153"), TXT("talk.0154"),
    TXT("talk.0155"), TXT("talk.0156"),
    TXT("talk.0157"), TXT("talk.0158"),
    TXT("talk.0159"), TXT("talk.0160"),
    TXT("talk.0161"), TXT("talk.0162"),
    TXT("talk.0163"), TXT("talk.0164"),
    TXT("talk.0165"), TXT("talk.0166"),
    TXT("talk.0167"), TXT("talk.0168"),
    TXT("talk.0169"), TXT("talk.0170"),
]
GUN_PANIC = [TXT("talk.0171"), TXT("talk.0172"), TXT("talk.0173"), TXT("talk.0174"),
             TXT("talk.0175"), TXT("talk.0176"), TXT("talk.0177"),
             TXT("talk.0178"), TXT("talk.0179"), TXT("talk.0180"), TXT("talk.0181"),
             TXT("talk.0182"), TXT("talk.0183"), TXT("talk.0184"),
             TXT("talk.0185"), TXT("talk.0186"), TXT("talk.0187"),
             TXT("talk.0188"), TXT("talk.0189"), TXT("talk.0190")]
FIGHT_TALK = [TXT("talk.0191"), TXT("talk.0192"), TXT("talk.0193"), TXT("talk.0194"),
              TXT("talk.0195"), TXT("talk.0196"), TXT("talk.0197"), TXT("talk.0198"),
              TXT("talk.0199"), TXT("talk.0200"), TXT("talk.0201")]


def gossip(rng=random):
    """A line about another Skopje personality."""
    other = rng.choice(PERSONAS)[0]
    t = rng.choice((
        TXT("talk.0202"), TXT("talk.0203"), TXT("talk.0204"),
        TXT("talk.0205"), TXT("talk.0206"),
        TXT("talk.0207"), TXT("talk.0208"), TXT("talk.0209"),
        TXT("talk.0210"), TXT("talk.0211"), TXT("talk.0212"),
        TXT("talk.0213"), TXT("talk.0214"), TXT("talk.0215"),
        TXT("talk.0216"), TXT("talk.0217")))
    return t.replace("{o}", other).replace("{O}", other)


def allowed(text, lang):
    if lang >= 1:
        return True
    low = text.lower()
    return not any(w in low for w in RUDE)


def pool(lines, lang):
    """Filter a line list for the chosen language level (adds the uncensored set at level 2)."""
    out = [t for t in lines if allowed(t, lang)]
    if lang >= 2:                                   # a few real curses mixed in, not instead of everything else
        out = out + random.sample(NSFW, min(len(NSFW), max(1, len(out) // 4)))
    return out or lines[:1]


# ---------------------------------------------------------------------------------------- 100+ Skopje personalities
# name | ped type it looks like | what they say (in character)
_P = TXT("talk.0218")

PERSONAS = []
for row in _P.strip().split("\n"):
    f = row.split("|")
    PERSONAS.append((f[0], f[1], f[2:]))

# ---------------------------------------------------------------------------------------- where in the city
DISTRICT = {
    TXT("talk.0219"): [TXT("talk.0220"), TXT("talk.0221"), TXT("talk.0222"), TXT("talk.0223"),
               TXT("talk.0224"), TXT("talk.0225"), TXT("talk.0226")],
    TXT("talk.0227"): [TXT("talk.0228"), TXT("talk.0229"), TXT("talk.0230"), TXT("talk.0231"),
               TXT("talk.0232"), TXT("talk.0233")],
    TXT("talk.0234"): [TXT("talk.0235"), TXT("talk.0236"), TXT("talk.0237"),
                 TXT("talk.0238"), TXT("talk.0239")],
    TXT("talk.0240"): [TXT("talk.0241"), TXT("talk.0242"), TXT("talk.0243"), TXT("talk.0244"),
             TXT("talk.0245")],
    TXT("talk.0246"): [TXT("talk.0247"), TXT("talk.0248"), TXT("talk.0249"), TXT("talk.0250"),
                TXT("talk.0251")],
    TXT("talk.0252"): [TXT("talk.0253"), TXT("talk.0254"), TXT("talk.0255"), TXT("talk.0256")],
    TXT("talk.0257"): [TXT("talk.0258"), TXT("talk.0259"), TXT("talk.0260")],
    TXT("talk.0261"): [TXT("talk.0262"), TXT("talk.0263"), TXT("talk.0264")],
    TXT("talk.0265"): [TXT("talk.0266"), TXT("talk.0267"), TXT("talk.0268")],
    TXT("talk.0269"): [TXT("talk.0270"), TXT("talk.0271"), TXT("talk.0272")],
    TXT("talk.0273"): [TXT("talk.0274"), TXT("talk.0275"), TXT("talk.0276")],
    TXT("talk.0277"): [TXT("talk.0278"), TXT("talk.0279")],
    TXT("talk.0280"): [TXT("talk.0281"), TXT("talk.0282")],
    TXT("talk.0283"): [TXT("talk.0284"), TXT("talk.0285")],
    TXT("talk.0286"): [TXT("talk.0287"), TXT("talk.0288")],
    TXT("talk.0289"): [TXT("talk.0290"), TXT("talk.0291")],
    TXT("talk.0292"): [TXT("talk.0293"), TXT("talk.0294")],
    TXT("talk.0295"): [TXT("talk.0296"), TXT("talk.0297")],
    TXT("talk.0298"): [TXT("talk.0299"), TXT("talk.0300")],
    TXT("talk.0301"): [TXT("talk.0302"), TXT("talk.0303")],
}

# ---------------------------------------------------------------------------------------- time of day
TIME = {
    "morning": [TXT("talk.0304"), TXT("talk.0305"), TXT("talk.0306"), TXT("talk.0307"), TXT("talk.0308"),
                TXT("talk.0309"), TXT("talk.0310")],
    "noon": [TXT("talk.0311"), TXT("talk.0312"), TXT("talk.0313"), TXT("talk.0314"),
             TXT("talk.0315")],
    "evening": [TXT("talk.0316"), TXT("talk.0317"), TXT("talk.0318"), TXT("talk.0319"),
                TXT("talk.0320"), TXT("talk.0321")],
    "night": [TXT("talk.0322"), TXT("talk.0323"), TXT("talk.0324"), TXT("talk.0325"),
              TXT("talk.0326"), TXT("talk.0327")],
}

# ---------------------------------------------------------------------------------------- Skopje, politics, stereotypes, jokes
SKOPJE = [
    TXT("talk.0328"), TXT("talk.0329"), TXT("talk.0330"),
    TXT("talk.0331"), TXT("talk.0332"), TXT("talk.0333"),
    TXT("talk.0334"), TXT("talk.0335"), TXT("talk.0336"),
    TXT("talk.0337"), TXT("talk.0338"), TXT("talk.0339"),
    TXT("talk.0340"), TXT("talk.0341"), TXT("talk.0342"),
    TXT("talk.0343"), TXT("talk.0344"), TXT("talk.0345"),
    TXT("talk.0346"), TXT("talk.0347"), TXT("talk.0348"),
]
POLITICS = [
    TXT("talk.0349"), TXT("talk.0350"), TXT("talk.0351"),
    TXT("talk.0352"), TXT("talk.0353"), TXT("talk.0354"),
    TXT("talk.0355"), TXT("talk.0356"), TXT("talk.0357"),
    TXT("talk.0358"), TXT("talk.0359"), TXT("talk.0360"),
    TXT("talk.0361"), TXT("talk.0362"), TXT("talk.0363"),
]
STEREO = {   # light jokes about professions / types, not about ethnic groups
    "Chichko": [TXT("talk.0364"), TXT("talk.0365")],
    "Baba": [TXT("talk.0366"), TXT("talk.0367")],
    "Biznismen": [TXT("talk.0368"), TXT("talk.0369")],
    "Student": [TXT("talk.0370"), TXT("talk.0371")],
    "Pandur": [TXT("talk.0372"), TXT("talk.0373")],
    "Turist": [TXT("talk.0374"), TXT("talk.0375")],
    "Gastarbajter": [TXT("talk.0376"), TXT("talk.0377")],
    "Influenser": [TXT("talk.0378"), TXT("talk.0379")],
    "Taxi": [TXT("talk.0380"), TXT("talk.0381")],
}
JOKES = [
    TXT("talk.0382"),
    TXT("talk.0383"), TXT("talk.0384"),
    TXT("talk.0385"), TXT("talk.0386"),
    TXT("talk.0387"), TXT("talk.0388"),
    TXT("talk.0389"),
]


def _period(hour):
    return "morning" if 5 <= hour < 11 else ("noon" if hour < 16 else ("evening" if hour < 22 else "night"))


def district_lines(name):
    if not name:
        return []
    for k, v in DISTRICT.items():
        if k.lower() in name.lower():
            return v
    return []


def persona_of(p, rng):
    """Give a pedestrian a personality matching its look (stable per pedestrian)."""
    if getattr(p, "persona", None) is None:
        import vehicles
        a = vehicles.PED_IDS[p.arch]
        fits = [i for i, q in enumerate(PERSONAS) if q[1] == a]
        p.persona = rng.choice(fits) if fits and rng.random() < 0.8 else rng.randrange(len(PERSONAS))
    return PERSONAS[p.persona]


def wchoice(lines, rng=random, gamma=0.6):
    """Pick a line with probability falling with its length as (len/mean)^-gamma: long lines get spoken less often, never never."""
    lines = list(lines)
    if len(lines) < 2:
        return rng.choice(lines)
    ls = [max(len(str(x)), 1) for x in lines]
    m = sum(ls) / len(ls)
    w = [(l / m) ** -gamma for l in ls]
    return rng.choices(lines, weights=w)[0]


def say(p, sim, rng=random):
    """An idle line for pedestrian p: personality, type, district, time of day, Skopje/politics/jokes, insults by aggression."""
    import vehicles
    lang = getattr(sim, "lang", 1)
    aggro = getattr(sim, "aggro", 1)
    a = vehicles.PED_IDS[p.arch]
    r = rng.random()
    if rng.random() < 0.34:                                 # речник на скопски сленг: по стил на лик (bible_lines.py)
        t = bible_lines.idle(a, lang, rng) if rng.random() < 0.6 else bible_lines.topic_line(a, rng)
        if t and allowed(t, lang):
            return t
    if lang >= 2 and rng.random() < 0.05 + 0.03 * aggro:       # ниво 2: цуваат без сопирачки
        return rng.choice(bible_lines.NSFW_MAX)
    if aggro >= 2 and r < 0.08 * aggro:                     # nervous city: random cursing at nobody in particular
        return wchoice(NSFW if lang >= 2 else (STREET_INSULT if lang == 1 else POLITE_INSULT), rng)
    if rng.random() < 0.3:                                 # people with problems
        return wchoice(pool(problems.for_arch(a), lang), rng)
    r = rng.random()
    if r < 0.08:
        return wchoice(pool([gossip(rng)], lang), rng)
    if r < 0.12 or (0.38 <= r < 0.44):                   # thoughts in the first person
        return wchoice(pool(ME, lang), rng)
    if r < 0.2:
        return wchoice(pool(JARGON, lang), rng)
    if r < 0.38:
        lines = persona_of(p, rng)[2]
    elif r < 0.55:
        lines = peds_lines.idle(a)
    elif r < 0.68:
        pl = getattr(sim, "places", None)
        lines = district_lines(pl.where(p.x, p.y) if pl else None) or SKOPJE
    elif r < 0.78:
        lines = TIME[_period(sim.clock.hour)]
    elif r < 0.86:
        lines = SKOPJE
    elif r < 0.93:
        lines = POLITICS
    else:
        lines = STEREO.get(a, JOKES) + JOKES
    return wchoice(pool(lines, lang), rng)


def react(kind, arch, sim, base, rng=random):
    """Hit / panic / fight / KO lines filtered by the language level, with more insults when aggressive."""
    lang = getattr(sim, "lang", 1)
    aggro = getattr(sim, "aggro", 1)
    try:
        import vehicles
        b = bible_lines.react(kind, vehicles.PED_IDS[arch], lang, rng)
    except Exception:  # noqa: BLE001 - arch outside the table
        b = None
    if b and allowed(b, lang) and rng.random() < (0.6 if lang < 2 else 0.78):
        return b
    if lang >= 2 and kind in ("hit", "fight") and rng.random() < 0.3:
        return rng.choice(bible_lines.NSFW_MAX)
    lines = pool(base, lang)
    if kind == "fight" and rng.random() < 0.4:
        lines = pool(FIGHT_TALK, lang)
    if kind in ("hit", "fight") and rng.random() < 0.15 * aggro:
        lines = NSFW if lang >= 2 else (STREET_INSULT if lang == 1 else POLITE_INSULT)
    return wchoice(lines, rng)
