"""Tooltip lines for each Skopje neighbourhood (round 10): at least ten each, picked by the language setting.

Plain lines are always allowed; lines with street words (сељак, ѓубре, мрш ...) appear from level 1 ("улично");
NSFW lines (list X) only at level 2. Names that have no own list get the {n} templates. Original text, not
native-speaker reviewed; jokes are about places and habits, never about ethnic groups."""
from texts import TXT
import random

import bible_lines
import talk

T = {
    TXT("hood_lines.0001"): [TXT("hood_lines.0002"), TXT("hood_lines.0003"),
               TXT("hood_lines.0004"), TXT("hood_lines.0005"),
               TXT("hood_lines.0006"), TXT("hood_lines.0007"),
               TXT("hood_lines.0008"), TXT("hood_lines.0009"),
               TXT("hood_lines.0010"), TXT("hood_lines.0011"),
               TXT("hood_lines.0012"), TXT("hood_lines.0013")],
    TXT("hood_lines.0014"): [TXT("hood_lines.0015"), TXT("hood_lines.0016"),
             TXT("hood_lines.0017"), TXT("hood_lines.0018"),
             TXT("hood_lines.0019"), TXT("hood_lines.0020"),
             TXT("hood_lines.0021"), TXT("hood_lines.0022"),
             TXT("hood_lines.0023"), TXT("hood_lines.0024"),
             TXT("hood_lines.0025"), TXT("hood_lines.0026")],
    TXT("hood_lines.0027"): [TXT("hood_lines.0028"), TXT("hood_lines.0029"),
               TXT("hood_lines.0030"), TXT("hood_lines.0031"),
               TXT("hood_lines.0032"), TXT("hood_lines.0033"),
               TXT("hood_lines.0034"), TXT("hood_lines.0035"),
               TXT("hood_lines.0036"), TXT("hood_lines.0037"),
               TXT("hood_lines.0038"), TXT("hood_lines.0039")],
    TXT("hood_lines.0040"): [TXT("hood_lines.0041"), TXT("hood_lines.0042"),
                 TXT("hood_lines.0043"), TXT("hood_lines.0044"),
                 TXT("hood_lines.0045"), TXT("hood_lines.0046"),
                 TXT("hood_lines.0047"), TXT("hood_lines.0048"),
                 TXT("hood_lines.0049"), TXT("hood_lines.0050"),
                 TXT("hood_lines.0051"), TXT("hood_lines.0052")],
    TXT("hood_lines.0053"): [TXT("hood_lines.0054"), TXT("hood_lines.0055"),
                    TXT("hood_lines.0056"), TXT("hood_lines.0057"),
                    TXT("hood_lines.0058"), TXT("hood_lines.0059"),
                    TXT("hood_lines.0060"), TXT("hood_lines.0061"),
                    TXT("hood_lines.0062"), TXT("hood_lines.0063"),
                    TXT("hood_lines.0064")],
    TXT("hood_lines.0065"): [TXT("hood_lines.0066"), TXT("hood_lines.0067"),
                  TXT("hood_lines.0068"), TXT("hood_lines.0069"),
                  TXT("hood_lines.0070"), TXT("hood_lines.0071"),
                  TXT("hood_lines.0072"), TXT("hood_lines.0073"),
                  TXT("hood_lines.0074"), TXT("hood_lines.0075"),
                  TXT("hood_lines.0076")],
    TXT("hood_lines.0077"): [TXT("hood_lines.0078"), TXT("hood_lines.0079"),
                    TXT("hood_lines.0080"), TXT("hood_lines.0081"),
                    TXT("hood_lines.0082"), TXT("hood_lines.0083"),
                    TXT("hood_lines.0084"), TXT("hood_lines.0085"),
                    TXT("hood_lines.0086"), TXT("hood_lines.0087"),
                    TXT("hood_lines.0088"), TXT("hood_lines.0089")],
    TXT("hood_lines.0090"): [TXT("hood_lines.0091"), TXT("hood_lines.0092"),
                 TXT("hood_lines.0093"), TXT("hood_lines.0094"),
                 TXT("hood_lines.0095"), TXT("hood_lines.0096"),
                 TXT("hood_lines.0097"), TXT("hood_lines.0098"),
                 TXT("hood_lines.0099"), TXT("hood_lines.0100"),
                 TXT("hood_lines.0101")],
    TXT("hood_lines.0102"): [TXT("hood_lines.0103"), TXT("hood_lines.0104"),
             TXT("hood_lines.0105"), TXT("hood_lines.0106"),
             TXT("hood_lines.0107"), TXT("hood_lines.0108"), TXT("hood_lines.0109"),
             TXT("hood_lines.0110"), TXT("hood_lines.0111"),
             TXT("hood_lines.0112"), TXT("hood_lines.0113")],
    TXT("hood_lines.0114"): [TXT("hood_lines.0115"), TXT("hood_lines.0116"),
                  TXT("hood_lines.0117"), TXT("hood_lines.0118"),
                  TXT("hood_lines.0119"), TXT("hood_lines.0120"),
                  TXT("hood_lines.0121"), TXT("hood_lines.0122"),
                  TXT("hood_lines.0123"), TXT("hood_lines.0124"),
                  TXT("hood_lines.0125")],
    TXT("hood_lines.0126"): [TXT("hood_lines.0127"), TXT("hood_lines.0128"),
                 TXT("hood_lines.0129"), TXT("hood_lines.0130"),
                 TXT("hood_lines.0131"), TXT("hood_lines.0132"),
                 TXT("hood_lines.0133"), TXT("hood_lines.0134"),
                 TXT("hood_lines.0135"), TXT("hood_lines.0136"),
                 TXT("hood_lines.0137")],
    TXT("hood_lines.0138"): [TXT("hood_lines.0139"), TXT("hood_lines.0140"),
               TXT("hood_lines.0141"), TXT("hood_lines.0142"),
               TXT("hood_lines.0143"), TXT("hood_lines.0144"),
               TXT("hood_lines.0145"), TXT("hood_lines.0146"),
               TXT("hood_lines.0147"), TXT("hood_lines.0148"), TXT("hood_lines.0149")],
    TXT("hood_lines.0150"): [TXT("hood_lines.0151"), TXT("hood_lines.0152"),
              TXT("hood_lines.0153"), TXT("hood_lines.0154"),
              TXT("hood_lines.0155"), TXT("hood_lines.0156"),
              TXT("hood_lines.0157"), TXT("hood_lines.0158"),
              TXT("hood_lines.0159"), TXT("hood_lines.0160"),
              TXT("hood_lines.0161")],
    TXT("hood_lines.0162"): [TXT("hood_lines.0163"), TXT("hood_lines.0164"),
                    TXT("hood_lines.0165"), TXT("hood_lines.0166"),
                    TXT("hood_lines.0167"), TXT("hood_lines.0168"),
                    TXT("hood_lines.0169"), TXT("hood_lines.0170"),
                    TXT("hood_lines.0171"), TXT("hood_lines.0172"),
                    TXT("hood_lines.0173")],
    TXT("hood_lines.0174"): [TXT("hood_lines.0175"), TXT("hood_lines.0176"),
                TXT("hood_lines.0177"), TXT("hood_lines.0178"),
                TXT("hood_lines.0179"), TXT("hood_lines.0180"),
                TXT("hood_lines.0181"), TXT("hood_lines.0182"),
                TXT("hood_lines.0183"), TXT("hood_lines.0184")],
    TXT("hood_lines.0185"): [TXT("hood_lines.0186"), TXT("hood_lines.0187"),
              TXT("hood_lines.0188"), TXT("hood_lines.0189"), TXT("hood_lines.0190"),
              TXT("hood_lines.0191"), TXT("hood_lines.0192"), TXT("hood_lines.0193"),
              TXT("hood_lines.0194"), TXT("hood_lines.0195")],
    TXT("hood_lines.0196"): [TXT("hood_lines.0197"), TXT("hood_lines.0198"),
             TXT("hood_lines.0199"), TXT("hood_lines.0200"), TXT("hood_lines.0201"),
             TXT("hood_lines.0202"), TXT("hood_lines.0203"), TXT("hood_lines.0204"),
             TXT("hood_lines.0205"), TXT("hood_lines.0206")],
}
for _n in (TXT("hood_lines.0207"), TXT("hood_lines.0208"), TXT("hood_lines.0209"), TXT("hood_lines.0210")):
    T.setdefault(_n, [])
T[TXT("hood_lines.0211")] += [TXT("hood_lines.0212"), TXT("hood_lines.0213"),
                       TXT("hood_lines.0214"), TXT("hood_lines.0215"),
                       TXT("hood_lines.0216"), TXT("hood_lines.0217"),
                       TXT("hood_lines.0218"), TXT("hood_lines.0219"),
                       TXT("hood_lines.0220"), TXT("hood_lines.0221"),
                       TXT("hood_lines.0222")]
T[TXT("hood_lines.0223")] += [TXT("hood_lines.0224"), TXT("hood_lines.0225"),
              TXT("hood_lines.0226"), TXT("hood_lines.0227"),
              TXT("hood_lines.0228"), TXT("hood_lines.0229"), TXT("hood_lines.0230"),
              TXT("hood_lines.0231"), TXT("hood_lines.0232"), TXT("hood_lines.0233")]
T[TXT("hood_lines.0234")] += [TXT("hood_lines.0235"), TXT("hood_lines.0236"),
                   TXT("hood_lines.0237"), TXT("hood_lines.0238"), TXT("hood_lines.0239"),
                   TXT("hood_lines.0240"), TXT("hood_lines.0241"),
                   TXT("hood_lines.0242"), TXT("hood_lines.0243"),
                   TXT("hood_lines.0244"), TXT("hood_lines.0245")]
T[TXT("hood_lines.0246")] += [TXT("hood_lines.0247"), TXT("hood_lines.0248"),
                     TXT("hood_lines.0249"), TXT("hood_lines.0250"), TXT("hood_lines.0251"),
                     TXT("hood_lines.0252"), TXT("hood_lines.0253"),
                     TXT("hood_lines.0254"), TXT("hood_lines.0255"), TXT("hood_lines.0256")]

X = {  # level 2 only (uncensored)
    TXT("hood_lines.0257"): [TXT("hood_lines.0258"), TXT("hood_lines.0259")],
    TXT("hood_lines.0260"): [TXT("hood_lines.0261")],
    TXT("hood_lines.0262"): [TXT("hood_lines.0263")],
    TXT("hood_lines.0264"): [TXT("hood_lines.0265")],
}

GENERIC = [TXT("hood_lines.0266"), TXT("hood_lines.0267"), TXT("hood_lines.0268"),
           TXT("hood_lines.0269"), TXT("hood_lines.0270"), TXT("hood_lines.0271"),
           TXT("hood_lines.0272"), TXT("hood_lines.0273"),
           TXT("hood_lines.0274"), TXT("hood_lines.0275"),
           TXT("hood_lines.0276"), TXT("hood_lines.0277"),
           TXT("hood_lines.0278"), TXT("hood_lines.0279")]
X_GENERIC = [TXT("hood_lines.0280"), TXT("hood_lines.0281")]


def line(name, lang, rng=random):
    base = name.replace(TXT("hood_lines.0282"), "").replace(TXT("hood_lines.0283"), "")
    own = T.get(base)
    if own is None:                                   # numbered parts: "Карпош 3" -> Карпош, "Влае 2" -> Влае
        root = base.rsplit(" ", 1)[0] if base[-1:].isdigit() else base
        own = T.get(root)
    lines = list(own or []) + [g.replace("{n}", base) for g in (GENERIC if not own else GENERIC[:4])]
    if lang >= 2:
        lines += [x.replace("{n}", base) for x in X.get(base, []) + X_GENERIC]
        return rng.choice(lines)
    return rng.choice([t for t in lines if talk.allowed(t, lang)] or lines[:1])
