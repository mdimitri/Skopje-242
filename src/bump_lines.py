"""What a pedestrian growls when the player keeps bumping into them: grumble, insult, threat, then the fight.
Per character style, in Skopje street Macedonian (the slang is from memory, not scraped from forums)."""
from texts import TXT
import random

GENERIC = [
    [TXT("bump_lines.0001"), TXT("bump_lines.0002"), TXT("bump_lines.0003"), TXT("bump_lines.0004"), TXT("bump_lines.0005"), TXT("bump_lines.0006"),
     TXT("bump_lines.0007"), TXT("bump_lines.0008"), TXT("bump_lines.0009"), TXT("bump_lines.0010")],
    [TXT("bump_lines.0011"), TXT("bump_lines.0012"), TXT("bump_lines.0013"), TXT("bump_lines.0014"), TXT("bump_lines.0015"), TXT("bump_lines.0016"),
     TXT("bump_lines.0017"), TXT("bump_lines.0018"), TXT("bump_lines.0019"), TXT("bump_lines.0020"), TXT("bump_lines.0021")],
    [TXT("bump_lines.0022"), TXT("bump_lines.0023"), TXT("bump_lines.0024"), TXT("bump_lines.0025"), TXT("bump_lines.0026"), TXT("bump_lines.0027"),
     TXT("bump_lines.0028"), TXT("bump_lines.0029"), TXT("bump_lines.0030"), TXT("bump_lines.0031"),
     TXT("bump_lines.0032"), TXT("bump_lines.0033"), TXT("bump_lines.0034")],
    [TXT("bump_lines.0035"), TXT("bump_lines.0036"), TXT("bump_lines.0037"), TXT("bump_lines.0038"), TXT("bump_lines.0039"),
     TXT("bump_lines.0040"), TXT("bump_lines.0041"), TXT("bump_lines.0042")],
]

STYLE = {
    "old": [
        [TXT("bump_lines.0043"), TXT("bump_lines.0044"), TXT("bump_lines.0045"), TXT("bump_lines.0046")],
        [TXT("bump_lines.0047"), TXT("bump_lines.0048"), TXT("bump_lines.0049"), TXT("bump_lines.0050")],
        [TXT("bump_lines.0051"), TXT("bump_lines.0052"), TXT("bump_lines.0053"), TXT("bump_lines.0054")],
        [TXT("bump_lines.0055"), TXT("bump_lines.0056"), TXT("bump_lines.0057")],
    ],
    "woman": [
        [TXT("bump_lines.0058"), TXT("bump_lines.0059"), TXT("bump_lines.0060"), TXT("bump_lines.0061")],
        [TXT("bump_lines.0062"), TXT("bump_lines.0063"), TXT("bump_lines.0064"), TXT("bump_lines.0065"), TXT("bump_lines.0066")],
        [TXT("bump_lines.0067"), TXT("bump_lines.0068"), TXT("bump_lines.0069"), TXT("bump_lines.0070")],
        [TXT("bump_lines.0071"), TXT("bump_lines.0072"), TXT("bump_lines.0073")],
    ],
    "kid": [
        [TXT("bump_lines.0074"), TXT("bump_lines.0075"), TXT("bump_lines.0076"), TXT("bump_lines.0077")],
        [TXT("bump_lines.0078"), TXT("bump_lines.0079"), TXT("bump_lines.0080"), TXT("bump_lines.0081")],
        [TXT("bump_lines.0082"), TXT("bump_lines.0083"), TXT("bump_lines.0084")],
        [TXT("bump_lines.0085"), TXT("bump_lines.0086"), TXT("bump_lines.0087")],
    ],
    "tough": [
        [TXT("bump_lines.0088"), TXT("bump_lines.0089"), TXT("bump_lines.0090"), TXT("bump_lines.0091")],
        [TXT("bump_lines.0092"), TXT("bump_lines.0093"), TXT("bump_lines.0094"), TXT("bump_lines.0095"), TXT("bump_lines.0096")],
        [TXT("bump_lines.0097"), TXT("bump_lines.0098"), TXT("bump_lines.0099"), TXT("bump_lines.0100"),
         TXT("bump_lines.0101"), TXT("bump_lines.0102"), TXT("bump_lines.0103")],
        [TXT("bump_lines.0104"), TXT("bump_lines.0105"), TXT("bump_lines.0106"), TXT("bump_lines.0107")],
    ],
    "posh": [
        [TXT("bump_lines.0108"), TXT("bump_lines.0109"), TXT("bump_lines.0110"), TXT("bump_lines.0111")],
        [TXT("bump_lines.0112"), TXT("bump_lines.0113"), TXT("bump_lines.0114"), TXT("bump_lines.0115"), TXT("bump_lines.0116")],
        [TXT("bump_lines.0117"), TXT("bump_lines.0118"), TXT("bump_lines.0119"), TXT("bump_lines.0120")],
        [TXT("bump_lines.0121"), TXT("bump_lines.0122"), TXT("bump_lines.0123")],
    ],
    "sport": [
        [TXT("bump_lines.0124"), TXT("bump_lines.0125"), TXT("bump_lines.0126")],
        [TXT("bump_lines.0127"), TXT("bump_lines.0128"), TXT("bump_lines.0129")],
        [TXT("bump_lines.0130"), TXT("bump_lines.0131"), TXT("bump_lines.0132")],
        [TXT("bump_lines.0133"), TXT("bump_lines.0134")],
    ],
    "pop": [
        [TXT("bump_lines.0135"), TXT("bump_lines.0136"), TXT("bump_lines.0137")],
        [TXT("bump_lines.0138"), TXT("bump_lines.0139"), TXT("bump_lines.0140")],
        [TXT("bump_lines.0141"), TXT("bump_lines.0142"), TXT("bump_lines.0143")],
        [TXT("bump_lines.0144"), TXT("bump_lines.0145")],
    ],
    "vendor": [
        [TXT("bump_lines.0146"), TXT("bump_lines.0147"), TXT("bump_lines.0148")],
        [TXT("bump_lines.0149"), TXT("bump_lines.0150"), TXT("bump_lines.0151")],
        [TXT("bump_lines.0152"), TXT("bump_lines.0153"), TXT("bump_lines.0154"), TXT("bump_lines.0155")],
        [TXT("bump_lines.0156"), TXT("bump_lines.0157")],
    ],
}

ARCH_STYLE = {
    "Baba": "old", "Penzioner": "old", "Dedo na Kolo": "old",
    "Devojka": "woman", "Majka so Kolichka": "woman", "Kiosk Chika": "woman", "Nevesta": "woman",
    "Dete": "kid", "Trotinet Dete": "kid",
    "Navivach": "tough", "Teretana Brat": "tough", "Kafana Chicko": "tough", "Gastarbajter": "tough", "Pandur": "tough",
    "Rabotnik": "tough", "Komunalec": "tough", "Ribar": "tough", "Golabar": "tough", "Kocija": "tough", "Chichko": "tough",
    "Biznismen": "posh", "Advokat": "posh", "Influenser": "posh", "Hipster": "posh", "E-Trotinet Hipster": "posh",
    "Turist": "posh", "Student": "posh", "Telefonash": "posh",
    "Jogger": "sport", "Skejter": "sport", "Rolerash": "sport", "Velosipedist": "sport",
    "Pop": "pop",
    "Buregdzija": "vendor", "Dostavuvach": "vendor", "Parkingar": "vendor", "Partiski Aktivist": "vendor",
}


def line(arch_id, stage, rng=random):
    """stage 0 = grumble, 1 = insult, 2 = threat, 3 = the fight starts.  arch_id = vehicles.PED_IDS[arch]."""
    stage = max(0, min(3, stage))
    own = STYLE.get(ARCH_STYLE.get(arch_id, ""), None)
    if own and rng.random() < 0.65:
        return rng.choice(own[stage])
    return rng.choice(GENERIC[stage])
