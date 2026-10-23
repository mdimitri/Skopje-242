"""Што зборуваат луѓето на улица - по тип на лик и по тоа што прават (оди, удрен, бега, се тепа, нокаут).

Секој тип има свои теми (TOPICS); репликите при одење се темите сами и со скопски почеток („Леле, брат, ...“),
а при удар / бегање / тепачка се мешаат општите скопски реплики со оние на типот. Секој тип има над 100 реплики.
Сленгот е од Мартин (леле, брат, брату, сељак, сељаци, не биди сељак, ѓубре) и од општиот скопски говор;
форумите не можеа да се пребараат, па сè е непроверено од мајчин говорител (docs/TEXT_SOURCES.md)."""

from texts import TXT
OPENERS = [TXT("peds_lines.0001"), TXT("peds_lines.0002"), TXT("peds_lines.0003"), TXT("peds_lines.0004"), TXT("peds_lines.0005"), TXT("peds_lines.0006"), TXT("peds_lines.0007"), TXT("peds_lines.0008"), TXT("peds_lines.0009"), TXT("peds_lines.0010")]

TOPICS = {
    "Chichko": [TXT("peds_lines.0011"), TXT("peds_lines.0012"), TXT("peds_lines.0013"),
                TXT("peds_lines.0014"), TXT("peds_lines.0015"), TXT("peds_lines.0016"),
                TXT("peds_lines.0017"), TXT("peds_lines.0018"), TXT("peds_lines.0019"),
                TXT("peds_lines.0020"), TXT("peds_lines.0021"), TXT("peds_lines.0022")],
    "Baba": [TXT("peds_lines.0023"), TXT("peds_lines.0024"), TXT("peds_lines.0025"),
             TXT("peds_lines.0026"), TXT("peds_lines.0027"), TXT("peds_lines.0028"),
             TXT("peds_lines.0029"), TXT("peds_lines.0030"), TXT("peds_lines.0031"),
             TXT("peds_lines.0032"), TXT("peds_lines.0033"), TXT("peds_lines.0034")],
    "Biznismen": [TXT("peds_lines.0035"), TXT("peds_lines.0036"), TXT("peds_lines.0037"),
                  TXT("peds_lines.0038"), TXT("peds_lines.0039"), TXT("peds_lines.0040"),
                  TXT("peds_lines.0041"), TXT("peds_lines.0042"), TXT("peds_lines.0043"),
                  TXT("peds_lines.0044"), TXT("peds_lines.0045"), TXT("peds_lines.0046")],
    "Student": [TXT("peds_lines.0047"), TXT("peds_lines.0048"), TXT("peds_lines.0049"),
                TXT("peds_lines.0050"), TXT("peds_lines.0051"), TXT("peds_lines.0052"),
                TXT("peds_lines.0053"), TXT("peds_lines.0054"), TXT("peds_lines.0055"),
                TXT("peds_lines.0056"), TXT("peds_lines.0057"), TXT("peds_lines.0058")],
    "Navivach": [TXT("peds_lines.0059"), TXT("peds_lines.0060"), TXT("peds_lines.0061"), TXT("peds_lines.0062"),
                 TXT("peds_lines.0063"), TXT("peds_lines.0064"), TXT("peds_lines.0065"),
                 TXT("peds_lines.0066"), TXT("peds_lines.0067"), TXT("peds_lines.0068"), TXT("peds_lines.0069"),
                 TXT("peds_lines.0070")],
    "Dete": [TXT("peds_lines.0071"), TXT("peds_lines.0072"), TXT("peds_lines.0073"), TXT("peds_lines.0074"),
             TXT("peds_lines.0075"), TXT("peds_lines.0076"), TXT("peds_lines.0077"),
             TXT("peds_lines.0078"), TXT("peds_lines.0079"), TXT("peds_lines.0080"),
             TXT("peds_lines.0081"), TXT("peds_lines.0082")],
    "Rabotnik": [TXT("peds_lines.0083"), TXT("peds_lines.0084"), TXT("peds_lines.0085"), TXT("peds_lines.0086"),
                 TXT("peds_lines.0087"), TXT("peds_lines.0088"), TXT("peds_lines.0089"),
                 TXT("peds_lines.0090"), TXT("peds_lines.0091"), TXT("peds_lines.0092"), TXT("peds_lines.0093"),
                 TXT("peds_lines.0094")],
    "Devojka": [TXT("peds_lines.0095"), TXT("peds_lines.0096"), TXT("peds_lines.0097"), TXT("peds_lines.0098"),
                TXT("peds_lines.0099"), TXT("peds_lines.0100"), TXT("peds_lines.0101"),
                TXT("peds_lines.0102"), TXT("peds_lines.0103"), TXT("peds_lines.0104"),
                TXT("peds_lines.0105"), TXT("peds_lines.0106")],
    "Buregdzija": [TXT("peds_lines.0107"), TXT("peds_lines.0108"), TXT("peds_lines.0109"),
                   TXT("peds_lines.0110"), TXT("peds_lines.0111"), TXT("peds_lines.0112"),
                   TXT("peds_lines.0113"), TXT("peds_lines.0114"), TXT("peds_lines.0115"), TXT("peds_lines.0116"),
                   TXT("peds_lines.0117"), TXT("peds_lines.0118")],
    "Pandur": [TXT("peds_lines.0119"), TXT("peds_lines.0120"), TXT("peds_lines.0121"),
               TXT("peds_lines.0122"), TXT("peds_lines.0123"), TXT("peds_lines.0124"),
               TXT("peds_lines.0125"), TXT("peds_lines.0126"), TXT("peds_lines.0127"),
               TXT("peds_lines.0128"), TXT("peds_lines.0129"), TXT("peds_lines.0130")],
    "Parkingar": [TXT("peds_lines.0131"), TXT("peds_lines.0132"), TXT("peds_lines.0133"), TXT("peds_lines.0134"),
                  TXT("peds_lines.0135"), TXT("peds_lines.0136"), TXT("peds_lines.0137"),
                  TXT("peds_lines.0138"), TXT("peds_lines.0139"), TXT("peds_lines.0140"),
                  TXT("peds_lines.0141"), TXT("peds_lines.0142")],
    "Pop": [TXT("peds_lines.0143"), TXT("peds_lines.0144"), TXT("peds_lines.0145"), TXT("peds_lines.0146"),
            TXT("peds_lines.0147"), TXT("peds_lines.0148"), TXT("peds_lines.0149"),
            TXT("peds_lines.0150"), TXT("peds_lines.0151"), TXT("peds_lines.0152"),
            TXT("peds_lines.0153"), TXT("peds_lines.0154")],
    "Hipster": [TXT("peds_lines.0155"), TXT("peds_lines.0156"), TXT("peds_lines.0157"),
                TXT("peds_lines.0158"), TXT("peds_lines.0159"), TXT("peds_lines.0160"),
                TXT("peds_lines.0161"), TXT("peds_lines.0162"), TXT("peds_lines.0163"),
                TXT("peds_lines.0164"), TXT("peds_lines.0165"), TXT("peds_lines.0166")],
    "Influenser": [TXT("peds_lines.0167"), TXT("peds_lines.0168"), TXT("peds_lines.0169"), TXT("peds_lines.0170"),
                   TXT("peds_lines.0171"), TXT("peds_lines.0172"), TXT("peds_lines.0173"),
                   TXT("peds_lines.0174"), TXT("peds_lines.0175"), TXT("peds_lines.0176"),
                   TXT("peds_lines.0177"), TXT("peds_lines.0178")],
    "Telefonash": [TXT("peds_lines.0179"), TXT("peds_lines.0180"), TXT("peds_lines.0181"),
                   TXT("peds_lines.0182"), TXT("peds_lines.0183"), TXT("peds_lines.0184"), TXT("peds_lines.0185"),
                   TXT("peds_lines.0186"), TXT("peds_lines.0187"), TXT("peds_lines.0188"), TXT("peds_lines.0189"),
                   TXT("peds_lines.0190")],
    "Penzioner": [TXT("peds_lines.0191"), TXT("peds_lines.0192"), TXT("peds_lines.0193"), TXT("peds_lines.0194"),
                  TXT("peds_lines.0195"), TXT("peds_lines.0196"), TXT("peds_lines.0197"),
                  TXT("peds_lines.0198"), TXT("peds_lines.0199"), TXT("peds_lines.0200"),
                  TXT("peds_lines.0201"), TXT("peds_lines.0202")],
    "Kafana Chicko": [TXT("peds_lines.0203"), TXT("peds_lines.0204"), TXT("peds_lines.0205"),
                      TXT("peds_lines.0206"), TXT("peds_lines.0207"), TXT("peds_lines.0208"),
                      TXT("peds_lines.0209"), TXT("peds_lines.0210"), TXT("peds_lines.0211"),
                      TXT("peds_lines.0212"), TXT("peds_lines.0213"), TXT("peds_lines.0214")],
    "Turist": [TXT("peds_lines.0215"), TXT("peds_lines.0216"), TXT("peds_lines.0217"), TXT("peds_lines.0218"),
               TXT("peds_lines.0219"), TXT("peds_lines.0220"), TXT("peds_lines.0221"), TXT("peds_lines.0222"),
               TXT("peds_lines.0223"), TXT("peds_lines.0224"), TXT("peds_lines.0225"), TXT("peds_lines.0226")],
    "Gastarbajter": [TXT("peds_lines.0227"), TXT("peds_lines.0228"), TXT("peds_lines.0229"),
                     TXT("peds_lines.0230"), TXT("peds_lines.0231"), TXT("peds_lines.0232"),
                     TXT("peds_lines.0233"), TXT("peds_lines.0234"), TXT("peds_lines.0235"),
                     TXT("peds_lines.0236"), TXT("peds_lines.0237"), TXT("peds_lines.0238")],
    "Majka so Kolichka": [TXT("peds_lines.0239"), TXT("peds_lines.0240"), TXT("peds_lines.0241"),
                          TXT("peds_lines.0242"), TXT("peds_lines.0243"), TXT("peds_lines.0244"), TXT("peds_lines.0245"),
                          TXT("peds_lines.0246"), TXT("peds_lines.0247"), TXT("peds_lines.0248"),
                          TXT("peds_lines.0249"), TXT("peds_lines.0250")],
    "Partiski Aktivist": [TXT("peds_lines.0251"), TXT("peds_lines.0252"), TXT("peds_lines.0253"),
                          TXT("peds_lines.0254"), TXT("peds_lines.0255"), TXT("peds_lines.0256"),
                          TXT("peds_lines.0257"), TXT("peds_lines.0258"), TXT("peds_lines.0259"), TXT("peds_lines.0260"),
                          TXT("peds_lines.0261"), TXT("peds_lines.0262")],
    "Advokat": [TXT("peds_lines.0263"), TXT("peds_lines.0264"), TXT("peds_lines.0265"), TXT("peds_lines.0266"),
                TXT("peds_lines.0267"), TXT("peds_lines.0268"), TXT("peds_lines.0269"), TXT("peds_lines.0270"),
                TXT("peds_lines.0271"), TXT("peds_lines.0272"), TXT("peds_lines.0273"), TXT("peds_lines.0274")],
    "Teretana Brat": [TXT("peds_lines.0275"), TXT("peds_lines.0276"), TXT("peds_lines.0277"), TXT("peds_lines.0278"),
                      TXT("peds_lines.0279"), TXT("peds_lines.0280"), TXT("peds_lines.0281"),
                      TXT("peds_lines.0282"), TXT("peds_lines.0283"), TXT("peds_lines.0284"),
                      TXT("peds_lines.0285"), TXT("peds_lines.0286")],
    "Kiosk Chika": [TXT("peds_lines.0287"), TXT("peds_lines.0288"), TXT("peds_lines.0289"),
                    TXT("peds_lines.0290"), TXT("peds_lines.0291"), TXT("peds_lines.0292"),
                    TXT("peds_lines.0293"), TXT("peds_lines.0294"), TXT("peds_lines.0295"), TXT("peds_lines.0296"),
                    TXT("peds_lines.0297"), TXT("peds_lines.0298")],
    "Ribar": [TXT("peds_lines.0299"), TXT("peds_lines.0300"), TXT("peds_lines.0301"), TXT("peds_lines.0302"),
              TXT("peds_lines.0303"), TXT("peds_lines.0304"), TXT("peds_lines.0305"), TXT("peds_lines.0306"),
              TXT("peds_lines.0307"), TXT("peds_lines.0308"), TXT("peds_lines.0309"), TXT("peds_lines.0310")],
    "Golabar": [TXT("peds_lines.0311"), TXT("peds_lines.0312"), TXT("peds_lines.0313"), TXT("peds_lines.0314"),
                TXT("peds_lines.0315"), TXT("peds_lines.0316"), TXT("peds_lines.0317"), TXT("peds_lines.0318"),
                TXT("peds_lines.0319"), TXT("peds_lines.0320"), TXT("peds_lines.0321"), TXT("peds_lines.0322")],
    "Komunalec": [TXT("peds_lines.0323"), TXT("peds_lines.0324"), TXT("peds_lines.0325"), TXT("peds_lines.0326"),
                  TXT("peds_lines.0327"), TXT("peds_lines.0328"), TXT("peds_lines.0329"), TXT("peds_lines.0330"),
                  TXT("peds_lines.0331"), TXT("peds_lines.0332"), TXT("peds_lines.0333"), TXT("peds_lines.0334")],
    "Nevesta": [TXT("peds_lines.0335"), TXT("peds_lines.0336"), TXT("peds_lines.0337"), TXT("peds_lines.0338"),
                TXT("peds_lines.0339"), TXT("peds_lines.0340"), TXT("peds_lines.0341"), TXT("peds_lines.0342"),
                TXT("peds_lines.0343"), TXT("peds_lines.0344"), TXT("peds_lines.0345"),
                TXT("peds_lines.0346")],
    "Dostavuvach": [TXT("peds_lines.0347"), TXT("peds_lines.0348"), TXT("peds_lines.0349"), TXT("peds_lines.0350"),
                    TXT("peds_lines.0351"), TXT("peds_lines.0352"), TXT("peds_lines.0353"),
                    TXT("peds_lines.0354"), TXT("peds_lines.0355"), TXT("peds_lines.0356"),
                    TXT("peds_lines.0357"), TXT("peds_lines.0358")],
    "Velosipedist": [TXT("peds_lines.0359"), TXT("peds_lines.0360"), TXT("peds_lines.0361"),
                     TXT("peds_lines.0362"), TXT("peds_lines.0363"), TXT("peds_lines.0364"),
                     TXT("peds_lines.0365"), TXT("peds_lines.0366"), TXT("peds_lines.0367"),
                     TXT("peds_lines.0368"), TXT("peds_lines.0369"), TXT("peds_lines.0370")],
    "Dedo na Kolo": [TXT("peds_lines.0371"), TXT("peds_lines.0372"), TXT("peds_lines.0373"),
                     TXT("peds_lines.0374"), TXT("peds_lines.0375"), TXT("peds_lines.0376"),
                     TXT("peds_lines.0377"), TXT("peds_lines.0378"), TXT("peds_lines.0379"),
                     TXT("peds_lines.0380"), TXT("peds_lines.0381"), TXT("peds_lines.0382")],
    "Moped Tomos": [TXT("peds_lines.0383"), TXT("peds_lines.0384"), TXT("peds_lines.0385"), TXT("peds_lines.0386"),
                    TXT("peds_lines.0387"), TXT("peds_lines.0388"), TXT("peds_lines.0389"),
                    TXT("peds_lines.0390"), TXT("peds_lines.0391"), TXT("peds_lines.0392"),
                    TXT("peds_lines.0393"), TXT("peds_lines.0394")],
    "Glovo Skuter": [TXT("peds_lines.0395"), TXT("peds_lines.0396"), TXT("peds_lines.0397"),
                     TXT("peds_lines.0398"), TXT("peds_lines.0399"), TXT("peds_lines.0400"),
                     TXT("peds_lines.0401"), TXT("peds_lines.0402"), TXT("peds_lines.0403"),
                     TXT("peds_lines.0404"), TXT("peds_lines.0405"), TXT("peds_lines.0406")],
    "Trotinet Dete": [TXT("peds_lines.0407"), TXT("peds_lines.0408"), TXT("peds_lines.0409"), TXT("peds_lines.0410"),
                      TXT("peds_lines.0411"), TXT("peds_lines.0412"), TXT("peds_lines.0413"),
                      TXT("peds_lines.0414"), TXT("peds_lines.0415"), TXT("peds_lines.0416"),
                      TXT("peds_lines.0417"), TXT("peds_lines.0418")],
    "E-Trotinet Hipster": [TXT("peds_lines.0419"), TXT("peds_lines.0420"), TXT("peds_lines.0421"),
                           TXT("peds_lines.0422"), TXT("peds_lines.0423"), TXT("peds_lines.0424"),
                           TXT("peds_lines.0425"), TXT("peds_lines.0426"), TXT("peds_lines.0427"),
                           TXT("peds_lines.0428"), TXT("peds_lines.0429"), TXT("peds_lines.0430")],
    "Skejter": [TXT("peds_lines.0431"), TXT("peds_lines.0432"), TXT("peds_lines.0433"), TXT("peds_lines.0434"),
                TXT("peds_lines.0435"), TXT("peds_lines.0436"), TXT("peds_lines.0437"), TXT("peds_lines.0438"),
                TXT("peds_lines.0439"), TXT("peds_lines.0440"), TXT("peds_lines.0441"),
                TXT("peds_lines.0442")],
    "Rolerash": [TXT("peds_lines.0443"), TXT("peds_lines.0444"), TXT("peds_lines.0445"), TXT("peds_lines.0446"),
                 TXT("peds_lines.0447"), TXT("peds_lines.0448"), TXT("peds_lines.0449"), TXT("peds_lines.0450"),
                 TXT("peds_lines.0451"), TXT("peds_lines.0452"), TXT("peds_lines.0453"), TXT("peds_lines.0454")],
    "Kocija": [TXT("peds_lines.0455"), TXT("peds_lines.0456"), TXT("peds_lines.0457"), TXT("peds_lines.0458"),
               TXT("peds_lines.0459"), TXT("peds_lines.0460"), TXT("peds_lines.0461"),
               TXT("peds_lines.0462"), TXT("peds_lines.0463"), TXT("peds_lines.0464"), TXT("peds_lines.0465"), TXT("peds_lines.0466")],
    "Jogger": [TXT("peds_lines.0467"), TXT("peds_lines.0468"), TXT("peds_lines.0469"), TXT("peds_lines.0470"),
               TXT("peds_lines.0471"), TXT("peds_lines.0472"), TXT("peds_lines.0473"), TXT("peds_lines.0474"),
               TXT("peds_lines.0475"), TXT("peds_lines.0476"), TXT("peds_lines.0477"), TXT("peds_lines.0478")],
}

# --- тоа што го прават: удрени (од кола / тепачка), бегаат, се тепаат, нокаут
HIT = [TXT("peds_lines.0479"), TXT("peds_lines.0480"), TXT("peds_lines.0481"), TXT("peds_lines.0482"),
       TXT("peds_lines.0483"), TXT("peds_lines.0484"), TXT("peds_lines.0485"), TXT("peds_lines.0486"),
       TXT("peds_lines.0487"), TXT("peds_lines.0488"), TXT("peds_lines.0489"), TXT("peds_lines.0490"),
       TXT("peds_lines.0491"), TXT("peds_lines.0492"), TXT("peds_lines.0493")]
PANIC = [TXT("peds_lines.0494"), TXT("peds_lines.0495"), TXT("peds_lines.0496"), TXT("peds_lines.0497"), TXT("peds_lines.0498"), TXT("peds_lines.0499"),
         TXT("peds_lines.0500"), TXT("peds_lines.0501"), TXT("peds_lines.0502"), TXT("peds_lines.0503")]
FIGHT = [TXT("peds_lines.0504"), TXT("peds_lines.0505"), TXT("peds_lines.0506"), TXT("peds_lines.0507"),
         TXT("peds_lines.0508"), TXT("peds_lines.0509"), TXT("peds_lines.0510"), TXT("peds_lines.0511"),
         TXT("peds_lines.0512"), TXT("peds_lines.0513")]
KO = [TXT("peds_lines.0514"), TXT("peds_lines.0515"), TXT("peds_lines.0516"), TXT("peds_lines.0517"), TXT("peds_lines.0518"), TXT("peds_lines.0519")]

# what each type adds when hit / scared / fighting (short, in character)
TYPE_HIT = {
    "Baba": [TXT("peds_lines.0520"), TXT("peds_lines.0521")], "Chichko": [TXT("peds_lines.0522"), TXT("peds_lines.0523")],
    "Biznismen": [TXT("peds_lines.0524"), TXT("peds_lines.0525")], "Student": [TXT("peds_lines.0526")],
    "Navivach": [TXT("peds_lines.0527")], "Dete": [TXT("peds_lines.0528"), TXT("peds_lines.0529")], "Rabotnik": [TXT("peds_lines.0530")],
    "Devojka": [TXT("peds_lines.0531")], "Buregdzija": [TXT("peds_lines.0532")], "Pandur": [TXT("peds_lines.0533")],
    "Parkingar": [TXT("peds_lines.0534")], "Pop": [TXT("peds_lines.0535")], "Hipster": [TXT("peds_lines.0536")],
    "Influenser": [TXT("peds_lines.0537")], "Telefonash": [TXT("peds_lines.0538")],
    "Penzioner": [TXT("peds_lines.0539")], "Kafana Chicko": [TXT("peds_lines.0540")], "Turist": [TXT("peds_lines.0541")],
    "Gastarbajter": [TXT("peds_lines.0542")], "Majka so Kolichka": [TXT("peds_lines.0543")],
    "Partiski Aktivist": [TXT("peds_lines.0544")], "Advokat": [TXT("peds_lines.0545")], "Teretana Brat": [TXT("peds_lines.0546")],
    "Kiosk Chika": [TXT("peds_lines.0547")], "Ribar": [TXT("peds_lines.0548")], "Golabar": [TXT("peds_lines.0549")],
    "Komunalec": [TXT("peds_lines.0550")], "Nevesta": [TXT("peds_lines.0551")], "Dostavuvach": [TXT("peds_lines.0552")],
}


def idle(arch):
    """Lines while walking around: the type's topics, plain and with a Skopje opener."""
    t = TOPICS.get(arch, [])
    out = [x[:1].upper() + x[1:] for x in t]
    out += [f"{o} {x}" for o in OPENERS for x in t]
    return out


def hit(arch):
    return HIT + TYPE_HIT.get(arch, []) * 3


def panic(arch):
    return PANIC + [(TXT("peds_lines.0553") + f'{x}') for x in TYPE_HIT.get(arch, [])]


def fight(arch):
    return FIGHT + TYPE_HIT.get(arch, []) * 2


def count(arch):
    return len(set(idle(arch) + hit(arch) + panic(arch) + fight(arch) + KO))
