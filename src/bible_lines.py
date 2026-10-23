"""Реплики од „Речник на скопски сленг и жаргон“ (Skopje slang bible.txt, види и docs/): секој стил на лик има свој
говор за мирно одење (idle), удар (hit), паника, тепачка, нокаут и за вриска по туркање (bump 0-3).
Јазични нивоа (мени „Јазик“): 0 пристојно, 1 улично (сленг од речникот), 2 без цензура - тука цува без сопирачки.
Секоја реплика го користи терминот од речникот во неговото значење; стиловите ги одговараат ликовите (ARCH_STYLE).
Непроверено од мајчин говорител (docs/TEXT_SOURCES.md)."""
from texts import TXT
import random

# arch id (vehicles.PED_IDS) -> стил
ARCH_STYLE = {
    "Baba": "old", "Penzioner": "old", "Dedo na Kolo": "old", "Golabar": "old", "Kocija": "old",
    "Devojka": "woman", "Majka so Kolichka": "woman", "Nevesta": "woman",
    "Dete": "kid", "Trotinet Dete": "kid",
    "Navivach": "tough", "Teretana Brat": "tough", "Kafana Chicko": "tough", "Gastarbajter": "tough", "Rabotnik": "tough",
    "Ribar": "tough", "Chichko": "tough", "Moped Tomos": "tough",
    "Biznismen": "posh", "Advokat": "posh", "Turist": "posh", "Partiski Aktivist": "posh",
    "Student": "youth", "Hipster": "youth", "Influenser": "youth", "Telefonash": "youth", "E-Trotinet Hipster": "youth",
    "Skejter": "youth", "Rolerash": "youth",
    "Jogger": "sport", "Velosipedist": "sport",
    "Pop": "pop",
    "Buregdzija": "vendor", "Dostavuvach": "vendor", "Glovo Skuter": "vendor", "Kiosk Chika": "vendor",
    "Pandur": "cop", "Parkingar": "cop", "Komunalec": "cop",
}


def style_of(arch_id):
    return ARCH_STYLE.get(arch_id, "tough")


# ===================================================================== по стил
# idle = мирно (улично ниво, термини од речникот); hit = удрен; panic = паника; fight = тепа / се закануваат; ko = нокаут;
# bump = 4 нивоа (мрморење, навреда, закана, тепачка) по туркање; x_* = без цензура (ниво 2)
S = {
    "old": dict(
        idle=[TXT("bible_lines.0001"), TXT("bible_lines.0002"),
              TXT("bible_lines.0003"), TXT("bible_lines.0004"),
              TXT("bible_lines.0005"), TXT("bible_lines.0006"),
              TXT("bible_lines.0007"), TXT("bible_lines.0008"),
              TXT("bible_lines.0009"), TXT("bible_lines.0010"),
              TXT("bible_lines.0011"),
              TXT("bible_lines.0012"), TXT("bible_lines.0013")],
        hit=[TXT("bible_lines.0014"), TXT("bible_lines.0015"), TXT("bible_lines.0016"),
             TXT("bible_lines.0017"), TXT("bible_lines.0018")],
        panic=[TXT("bible_lines.0019"), TXT("bible_lines.0020"), TXT("bible_lines.0021"), TXT("bible_lines.0022")],
        fight=[TXT("bible_lines.0023"), TXT("bible_lines.0024"), TXT("bible_lines.0025"),
               TXT("bible_lines.0026"), TXT("bible_lines.0027")],
        ko=[TXT("bible_lines.0028"), TXT("bible_lines.0029"), TXT("bible_lines.0030")],
        bump=[[TXT("bible_lines.0031"), TXT("bible_lines.0032"), TXT("bible_lines.0033"), TXT("bible_lines.0034")],
              [TXT("bible_lines.0035"), TXT("bible_lines.0036"), TXT("bible_lines.0037"), TXT("bible_lines.0038")],
              [TXT("bible_lines.0039"), TXT("bible_lines.0040"), TXT("bible_lines.0041"), TXT("bible_lines.0042")],
              [TXT("bible_lines.0043"), TXT("bible_lines.0044"), TXT("bible_lines.0045")]],
        x_hit=[TXT("bible_lines.0046"), TXT("bible_lines.0047"), TXT("bible_lines.0048"), TXT("bible_lines.0049"),
               TXT("bible_lines.0050")],
        x_fight=[TXT("bible_lines.0051"), TXT("bible_lines.0052"), TXT("bible_lines.0053"),
                 TXT("bible_lines.0054"), TXT("bible_lines.0055")],
        x_bump=[[TXT("bible_lines.0056"), TXT("bible_lines.0057")], [TXT("bible_lines.0058"), TXT("bible_lines.0059")],
                [TXT("bible_lines.0060"), TXT("bible_lines.0061")],
                [TXT("bible_lines.0062"), TXT("bible_lines.0063")]],
        x_idle=[TXT("bible_lines.0064"), TXT("bible_lines.0065")],
    ),
    "woman": dict(
        idle=[TXT("bible_lines.0066"), TXT("bible_lines.0067"),
              TXT("bible_lines.0068"), TXT("bible_lines.0069"),
              TXT("bible_lines.0070"), TXT("bible_lines.0071"),
              TXT("bible_lines.0072"), TXT("bible_lines.0073"),
              TXT("bible_lines.0074"), TXT("bible_lines.0075"),
              TXT("bible_lines.0076"), TXT("bible_lines.0077"), TXT("bible_lines.0078")],
        hit=[TXT("bible_lines.0079"), TXT("bible_lines.0080"), TXT("bible_lines.0081"),
             TXT("bible_lines.0082"), TXT("bible_lines.0083")],
        panic=[TXT("bible_lines.0084"), TXT("bible_lines.0085"), TXT("bible_lines.0086"), TXT("bible_lines.0087")],
        fight=[TXT("bible_lines.0088"), TXT("bible_lines.0089"), TXT("bible_lines.0090"),
               TXT("bible_lines.0091"), TXT("bible_lines.0092")],
        ko=[TXT("bible_lines.0093"), TXT("bible_lines.0094"), TXT("bible_lines.0095")],
        bump=[[TXT("bible_lines.0096"), TXT("bible_lines.0097"), TXT("bible_lines.0098"), TXT("bible_lines.0099")],
              [TXT("bible_lines.0100"), TXT("bible_lines.0101"), TXT("bible_lines.0102"), TXT("bible_lines.0103")],
              [TXT("bible_lines.0104"), TXT("bible_lines.0105"), TXT("bible_lines.0106"), TXT("bible_lines.0107")],
              [TXT("bible_lines.0108"), TXT("bible_lines.0109"), TXT("bible_lines.0110")]],
        x_hit=[TXT("bible_lines.0111"), TXT("bible_lines.0112"), TXT("bible_lines.0113"),
               TXT("bible_lines.0114"), TXT("bible_lines.0115")],
        x_fight=[TXT("bible_lines.0116"), TXT("bible_lines.0117"), TXT("bible_lines.0118"),
                 TXT("bible_lines.0119"), TXT("bible_lines.0120")],
        x_bump=[[TXT("bible_lines.0121"), TXT("bible_lines.0122")], [TXT("bible_lines.0123"), TXT("bible_lines.0124")],
                [TXT("bible_lines.0125"), TXT("bible_lines.0126")],
                [TXT("bible_lines.0127"), TXT("bible_lines.0128")]],
        x_idle=[TXT("bible_lines.0129"), TXT("bible_lines.0130")],
    ),
    "kid": dict(
        idle=[TXT("bible_lines.0131"), TXT("bible_lines.0132"), TXT("bible_lines.0133"),
              TXT("bible_lines.0134"), TXT("bible_lines.0135"), TXT("bible_lines.0136"),
              TXT("bible_lines.0137"), TXT("bible_lines.0138"), TXT("bible_lines.0139"), TXT("bible_lines.0140")],
        hit=[TXT("bible_lines.0141"), TXT("bible_lines.0142"), TXT("bible_lines.0143"), TXT("bible_lines.0144")],
        panic=[TXT("bible_lines.0145"), TXT("bible_lines.0146"), TXT("bible_lines.0147"), TXT("bible_lines.0148")],
        fight=[TXT("bible_lines.0149"), TXT("bible_lines.0150"), TXT("bible_lines.0151"), TXT("bible_lines.0152")],
        ko=[TXT("bible_lines.0153"), TXT("bible_lines.0154"), TXT("bible_lines.0155")],
        bump=[[TXT("bible_lines.0156"), TXT("bible_lines.0157"), TXT("bible_lines.0158"), TXT("bible_lines.0159")], [TXT("bible_lines.0160"), TXT("bible_lines.0161"), TXT("bible_lines.0162"), TXT("bible_lines.0163")],
              [TXT("bible_lines.0164"), TXT("bible_lines.0165"), TXT("bible_lines.0166"), TXT("bible_lines.0167")],
              [TXT("bible_lines.0168"), TXT("bible_lines.0169"), TXT("bible_lines.0170")]],
        x_hit=[TXT("bible_lines.0171"), TXT("bible_lines.0172"), TXT("bible_lines.0173")],
        x_fight=[TXT("bible_lines.0174"), TXT("bible_lines.0175")],
        x_bump=[[TXT("bible_lines.0176"), TXT("bible_lines.0177")], [TXT("bible_lines.0178"), TXT("bible_lines.0179")], [TXT("bible_lines.0180"), TXT("bible_lines.0181")],
                [TXT("bible_lines.0182"), TXT("bible_lines.0183")]],
        x_idle=[TXT("bible_lines.0184"), TXT("bible_lines.0185")],
    ),
    "tough": dict(
        idle=[TXT("bible_lines.0186"), TXT("bible_lines.0187"), TXT("bible_lines.0188"),
              TXT("bible_lines.0189"), TXT("bible_lines.0190"), TXT("bible_lines.0191"),
              TXT("bible_lines.0192"), TXT("bible_lines.0193"), TXT("bible_lines.0194"),
              TXT("bible_lines.0195"), TXT("bible_lines.0196"), TXT("bible_lines.0197"), TXT("bible_lines.0198")],
        hit=[TXT("bible_lines.0199"), TXT("bible_lines.0200"), TXT("bible_lines.0201"), TXT("bible_lines.0202"), TXT("bible_lines.0203")],
        panic=[TXT("bible_lines.0204"), TXT("bible_lines.0205"), TXT("bible_lines.0206"), TXT("bible_lines.0207")],
        fight=[TXT("bible_lines.0208"), TXT("bible_lines.0209"), TXT("bible_lines.0210"), TXT("bible_lines.0211"),
               TXT("bible_lines.0212")],
        ko=[TXT("bible_lines.0213"), TXT("bible_lines.0214"), TXT("bible_lines.0215")],
        bump=[[TXT("bible_lines.0216"), TXT("bible_lines.0217"), TXT("bible_lines.0218"), TXT("bible_lines.0219")],
              [TXT("bible_lines.0220"), TXT("bible_lines.0221"), TXT("bible_lines.0222"), TXT("bible_lines.0223")],
              [TXT("bible_lines.0224"), TXT("bible_lines.0225"), TXT("bible_lines.0226"), TXT("bible_lines.0227"), TXT("bible_lines.0228")],
              [TXT("bible_lines.0229"), TXT("bible_lines.0230"), TXT("bible_lines.0231"), TXT("bible_lines.0232")]],
        x_hit=[TXT("bible_lines.0233"), TXT("bible_lines.0234"), TXT("bible_lines.0235"), TXT("bible_lines.0236"),
               TXT("bible_lines.0237")],
        x_fight=[TXT("bible_lines.0238"), TXT("bible_lines.0239"), TXT("bible_lines.0240"), TXT("bible_lines.0241"),
                 TXT("bible_lines.0242")],
        x_bump=[[TXT("bible_lines.0243"), TXT("bible_lines.0244")], [TXT("bible_lines.0245"), TXT("bible_lines.0246")],
                [TXT("bible_lines.0247"), TXT("bible_lines.0248")],
                [TXT("bible_lines.0249"), TXT("bible_lines.0250")]],
        x_idle=[TXT("bible_lines.0251"), TXT("bible_lines.0252")],
    ),
    "posh": dict(
        idle=[TXT("bible_lines.0253"), TXT("bible_lines.0254"), TXT("bible_lines.0255"),
              TXT("bible_lines.0256"), TXT("bible_lines.0257"), TXT("bible_lines.0258"),
              TXT("bible_lines.0259"), TXT("bible_lines.0260"), TXT("bible_lines.0261"),
              TXT("bible_lines.0262"), TXT("bible_lines.0263"), TXT("bible_lines.0264")],
        hit=[TXT("bible_lines.0265"), TXT("bible_lines.0266"), TXT("bible_lines.0267"), TXT("bible_lines.0268"), TXT("bible_lines.0269")],
        panic=[TXT("bible_lines.0270"), TXT("bible_lines.0271"), TXT("bible_lines.0272"), TXT("bible_lines.0273")],
        fight=[TXT("bible_lines.0274"), TXT("bible_lines.0275"), TXT("bible_lines.0276"), TXT("bible_lines.0277")],
        ko=[TXT("bible_lines.0278"), TXT("bible_lines.0279"), TXT("bible_lines.0280")],
        bump=[[TXT("bible_lines.0281"), TXT("bible_lines.0282"), TXT("bible_lines.0283"), TXT("bible_lines.0284")],
              [TXT("bible_lines.0285"), TXT("bible_lines.0286"), TXT("bible_lines.0287"), TXT("bible_lines.0288")],
              [TXT("bible_lines.0289"), TXT("bible_lines.0290"), TXT("bible_lines.0291"), TXT("bible_lines.0292")],
              [TXT("bible_lines.0293"), TXT("bible_lines.0294"), TXT("bible_lines.0295")]],
        x_hit=[TXT("bible_lines.0296"), TXT("bible_lines.0297"), TXT("bible_lines.0298"),
               TXT("bible_lines.0299"), TXT("bible_lines.0300")],
        x_fight=[TXT("bible_lines.0301"), TXT("bible_lines.0302"), TXT("bible_lines.0303"), TXT("bible_lines.0304")],
        x_bump=[[TXT("bible_lines.0305"), TXT("bible_lines.0306")], [TXT("bible_lines.0307"), TXT("bible_lines.0308")],
                [TXT("bible_lines.0309"), TXT("bible_lines.0310")],
                [TXT("bible_lines.0311"), TXT("bible_lines.0312")]],
        x_idle=[TXT("bible_lines.0313"), TXT("bible_lines.0314")],
    ),
    "youth": dict(
        idle=[TXT("bible_lines.0315"), TXT("bible_lines.0316"), TXT("bible_lines.0317"), TXT("bible_lines.0318"),
              TXT("bible_lines.0319"), TXT("bible_lines.0320"), TXT("bible_lines.0321"), TXT("bible_lines.0322"),
              TXT("bible_lines.0323"), TXT("bible_lines.0324"), TXT("bible_lines.0325"), TXT("bible_lines.0326"),
              TXT("bible_lines.0327")],
        hit=[TXT("bible_lines.0328"), TXT("bible_lines.0329"), TXT("bible_lines.0330"), TXT("bible_lines.0331"), TXT("bible_lines.0332")],
        panic=[TXT("bible_lines.0333"), TXT("bible_lines.0334"), TXT("bible_lines.0335"), TXT("bible_lines.0336")],
        fight=[TXT("bible_lines.0337"), TXT("bible_lines.0338"), TXT("bible_lines.0339"), TXT("bible_lines.0340")],
        ko=[TXT("bible_lines.0341"), TXT("bible_lines.0342"), TXT("bible_lines.0343")],
        bump=[[TXT("bible_lines.0344"), TXT("bible_lines.0345"), TXT("bible_lines.0346"), TXT("bible_lines.0347")],
              [TXT("bible_lines.0348"), TXT("bible_lines.0349"), TXT("bible_lines.0350"), TXT("bible_lines.0351")],
              [TXT("bible_lines.0352"), TXT("bible_lines.0353"), TXT("bible_lines.0354"), TXT("bible_lines.0355")],
              [TXT("bible_lines.0356"), TXT("bible_lines.0357"), TXT("bible_lines.0358")]],
        x_hit=[TXT("bible_lines.0359"), TXT("bible_lines.0360"), TXT("bible_lines.0361"), TXT("bible_lines.0362"), TXT("bible_lines.0363")],
        x_fight=[TXT("bible_lines.0364"), TXT("bible_lines.0365"), TXT("bible_lines.0366"), TXT("bible_lines.0367")],
        x_bump=[[TXT("bible_lines.0368"), TXT("bible_lines.0369")], [TXT("bible_lines.0370"), TXT("bible_lines.0371")],
                [TXT("bible_lines.0372"), TXT("bible_lines.0373")],
                [TXT("bible_lines.0374"), TXT("bible_lines.0375")]],
        x_idle=[TXT("bible_lines.0376"), TXT("bible_lines.0377")],
    ),
    "sport": dict(
        idle=[TXT("bible_lines.0378"), TXT("bible_lines.0379"), TXT("bible_lines.0380"), TXT("bible_lines.0381"),
              TXT("bible_lines.0382"), TXT("bible_lines.0383"), TXT("bible_lines.0384"),
              TXT("bible_lines.0385"), TXT("bible_lines.0386"), TXT("bible_lines.0387"), TXT("bible_lines.0388")],
        hit=[TXT("bible_lines.0389"), TXT("bible_lines.0390"), TXT("bible_lines.0391"), TXT("bible_lines.0392")],
        panic=[TXT("bible_lines.0393"), TXT("bible_lines.0394"), TXT("bible_lines.0395"), TXT("bible_lines.0396")],
        fight=[TXT("bible_lines.0397"), TXT("bible_lines.0398"), TXT("bible_lines.0399"), TXT("bible_lines.0400")],
        ko=[TXT("bible_lines.0401"), TXT("bible_lines.0402"), TXT("bible_lines.0403")],
        bump=[[TXT("bible_lines.0404"), TXT("bible_lines.0405"), TXT("bible_lines.0406"), TXT("bible_lines.0407")],
              [TXT("bible_lines.0408"), TXT("bible_lines.0409"), TXT("bible_lines.0410"), TXT("bible_lines.0411")],
              [TXT("bible_lines.0412"), TXT("bible_lines.0413"), TXT("bible_lines.0414"), TXT("bible_lines.0415")],
              [TXT("bible_lines.0416"), TXT("bible_lines.0417"), TXT("bible_lines.0418")]],
        x_hit=[TXT("bible_lines.0419"), TXT("bible_lines.0420"), TXT("bible_lines.0421"), TXT("bible_lines.0422")],
        x_fight=[TXT("bible_lines.0423"), TXT("bible_lines.0424"), TXT("bible_lines.0425"), TXT("bible_lines.0426")],
        x_bump=[[TXT("bible_lines.0427"), TXT("bible_lines.0428")], [TXT("bible_lines.0429"), TXT("bible_lines.0430")], [TXT("bible_lines.0431"), TXT("bible_lines.0432")],
                [TXT("bible_lines.0433"), TXT("bible_lines.0434")]],
        x_idle=[TXT("bible_lines.0435"), TXT("bible_lines.0436")],
    ),
    "pop": dict(
        idle=[TXT("bible_lines.0437"), TXT("bible_lines.0438"), TXT("bible_lines.0439"), TXT("bible_lines.0440"),
              TXT("bible_lines.0441"), TXT("bible_lines.0442"), TXT("bible_lines.0443"), TXT("bible_lines.0444"),
              TXT("bible_lines.0445"), TXT("bible_lines.0446")],
        hit=[TXT("bible_lines.0447"), TXT("bible_lines.0448"), TXT("bible_lines.0449"), TXT("bible_lines.0450")],
        panic=[TXT("bible_lines.0451"), TXT("bible_lines.0452"), TXT("bible_lines.0453"), TXT("bible_lines.0454")],
        fight=[TXT("bible_lines.0455"), TXT("bible_lines.0456"), TXT("bible_lines.0457"), TXT("bible_lines.0458")],
        ko=[TXT("bible_lines.0459"), TXT("bible_lines.0460"), TXT("bible_lines.0461")],
        bump=[[TXT("bible_lines.0462"), TXT("bible_lines.0463"), TXT("bible_lines.0464"), TXT("bible_lines.0465")],
              [TXT("bible_lines.0466"), TXT("bible_lines.0467"), TXT("bible_lines.0468"), TXT("bible_lines.0469")],
              [TXT("bible_lines.0470"), TXT("bible_lines.0471"), TXT("bible_lines.0472"), TXT("bible_lines.0473")],
              [TXT("bible_lines.0474"), TXT("bible_lines.0475"), TXT("bible_lines.0476")]],
        x_hit=[TXT("bible_lines.0477"), TXT("bible_lines.0478"), TXT("bible_lines.0479"), TXT("bible_lines.0480")],
        x_fight=[TXT("bible_lines.0481"), TXT("bible_lines.0482"), TXT("bible_lines.0483"), TXT("bible_lines.0484")],
        x_bump=[[TXT("bible_lines.0485"), TXT("bible_lines.0486")], [TXT("bible_lines.0487"), TXT("bible_lines.0488")], [TXT("bible_lines.0489"), TXT("bible_lines.0490")],
                [TXT("bible_lines.0491"), TXT("bible_lines.0492")]],
        x_idle=[TXT("bible_lines.0493"), TXT("bible_lines.0494")],
    ),
    "vendor": dict(
        idle=[TXT("bible_lines.0495"), TXT("bible_lines.0496"), TXT("bible_lines.0497"),
              TXT("bible_lines.0498"), TXT("bible_lines.0499"), TXT("bible_lines.0500"),
              TXT("bible_lines.0501"), TXT("bible_lines.0502"), TXT("bible_lines.0503"),
              TXT("bible_lines.0504"), TXT("bible_lines.0505"), TXT("bible_lines.0506")],
        hit=[TXT("bible_lines.0507"), TXT("bible_lines.0508"), TXT("bible_lines.0509"), TXT("bible_lines.0510"), TXT("bible_lines.0511")],
        panic=[TXT("bible_lines.0512"), TXT("bible_lines.0513"), TXT("bible_lines.0514"), TXT("bible_lines.0515")],
        fight=[TXT("bible_lines.0516"), TXT("bible_lines.0517"), TXT("bible_lines.0518"), TXT("bible_lines.0519")],
        ko=[TXT("bible_lines.0520"), TXT("bible_lines.0521"), TXT("bible_lines.0522")],
        bump=[[TXT("bible_lines.0523"), TXT("bible_lines.0524"), TXT("bible_lines.0525"), TXT("bible_lines.0526")],
              [TXT("bible_lines.0527"), TXT("bible_lines.0528"), TXT("bible_lines.0529"), TXT("bible_lines.0530")],
              [TXT("bible_lines.0531"), TXT("bible_lines.0532"), TXT("bible_lines.0533"), TXT("bible_lines.0534")],
              [TXT("bible_lines.0535"), TXT("bible_lines.0536"), TXT("bible_lines.0537")]],
        x_hit=[TXT("bible_lines.0538"), TXT("bible_lines.0539"), TXT("bible_lines.0540"), TXT("bible_lines.0541")],
        x_fight=[TXT("bible_lines.0542"), TXT("bible_lines.0543"), TXT("bible_lines.0544"), TXT("bible_lines.0545")],
        x_bump=[[TXT("bible_lines.0546"), TXT("bible_lines.0547")], [TXT("bible_lines.0548"), TXT("bible_lines.0549")], [TXT("bible_lines.0550"), TXT("bible_lines.0551")],
                [TXT("bible_lines.0552"), TXT("bible_lines.0553")]],
        x_idle=[TXT("bible_lines.0554"), TXT("bible_lines.0555")],
    ),
    "cop": dict(
        idle=[TXT("bible_lines.0556"), TXT("bible_lines.0557"), TXT("bible_lines.0558"),
              TXT("bible_lines.0559"), TXT("bible_lines.0560"), TXT("bible_lines.0561"),
              TXT("bible_lines.0562"), TXT("bible_lines.0563"), TXT("bible_lines.0564"),
              TXT("bible_lines.0565")],
        hit=[TXT("bible_lines.0566"), TXT("bible_lines.0567"), TXT("bible_lines.0568"), TXT("bible_lines.0569")],
        panic=[TXT("bible_lines.0570"), TXT("bible_lines.0571"), TXT("bible_lines.0572"), TXT("bible_lines.0573")],
        fight=[TXT("bible_lines.0574"), TXT("bible_lines.0575"), TXT("bible_lines.0576"), TXT("bible_lines.0577")],
        ko=[TXT("bible_lines.0578"), TXT("bible_lines.0579"), TXT("bible_lines.0580")],
        bump=[[TXT("bible_lines.0581"), TXT("bible_lines.0582"), TXT("bible_lines.0583"), TXT("bible_lines.0584")],
              [TXT("bible_lines.0585"), TXT("bible_lines.0586"), TXT("bible_lines.0587"), TXT("bible_lines.0588")],
              [TXT("bible_lines.0589"), TXT("bible_lines.0590"), TXT("bible_lines.0591"), TXT("bible_lines.0592")],
              [TXT("bible_lines.0593"), TXT("bible_lines.0594"), TXT("bible_lines.0595")]],
        x_hit=[TXT("bible_lines.0596"), TXT("bible_lines.0597"), TXT("bible_lines.0598"), TXT("bible_lines.0599")],
        x_fight=[TXT("bible_lines.0600"), TXT("bible_lines.0601"), TXT("bible_lines.0602"), TXT("bible_lines.0603")],
        x_bump=[[TXT("bible_lines.0604"), TXT("bible_lines.0605")], [TXT("bible_lines.0606"), TXT("bible_lines.0607")], [TXT("bible_lines.0608"), TXT("bible_lines.0609")],
                [TXT("bible_lines.0610"), TXT("bible_lines.0611")]],
        x_idle=[TXT("bible_lines.0612"), TXT("bible_lines.0613")],
    ),
}


def _pick(lst, rng):
    return rng.choice(lst) if lst else None


# ===================================================================== јавни функции
def idle(arch_id, lang, rng=random):
    st = S.get(style_of(arch_id))
    if st is None:
        return None
    if lang >= 2 and rng.random() < 0.3:
        return _pick(st["x_idle"], rng)
    return _pick(st["idle"], rng)


def react(kind, arch_id, lang, rng=random):
    """kind: hit | panic | fight | ko | gun.  Ниво 2: најчесто без цензура."""
    st = S.get(style_of(arch_id))
    if st is None:
        return None
    key = {"gun": "panic"}.get(kind, kind)
    if key not in ("hit", "panic", "fight", "ko"):
        return None
    if lang >= 2 and key in ("hit", "fight") and rng.random() < 0.8:
        return _pick(st["x_hit"] if key == "hit" else st["x_fight"], rng)
    if lang >= 2 and key == "panic" and rng.random() < 0.45:
        return _pick(st["x_hit"], rng)
    return _pick(st[key], rng)


def bump(arch_id, stage, lang, rng=random):
    """Туркање: stage 0 мрморење, 1 навреда, 2 закана, 3 почнува тепачка."""
    st = S.get(style_of(arch_id))
    stage = max(0, min(3, stage))
    if st is None:
        return None
    if lang >= 2 and rng.random() < 0.85:
        return _pick(st["x_bump"][stage], rng)
    return _pick(st["bump"][stage], rng)


# ===================================================================== општи теми од речникот (по афинитет на стилот)
TOPICS = {
    "greet": [TXT("bible_lines.0614"), TXT("bible_lines.0615"), TXT("bible_lines.0616"), TXT("bible_lines.0617"), TXT("bible_lines.0618"),
              TXT("bible_lines.0619"), TXT("bible_lines.0620"), TXT("bible_lines.0621"), TXT("bible_lines.0622"), TXT("bible_lines.0623")],
    "muabet": [TXT("bible_lines.0624"), TXT("bible_lines.0625"), TXT("bible_lines.0626"), TXT("bible_lines.0627"),
               TXT("bible_lines.0628"), TXT("bible_lines.0629"), TXT("bible_lines.0630"), TXT("bible_lines.0631"),
               TXT("bible_lines.0632"), TXT("bible_lines.0633")],
    "night": [TXT("bible_lines.0634"), TXT("bible_lines.0635"), TXT("bible_lines.0636"), TXT("bible_lines.0637"),
              TXT("bible_lines.0638"), TXT("bible_lines.0639"), TXT("bible_lines.0640"), TXT("bible_lines.0641")],
    "money": [TXT("bible_lines.0642"), TXT("bible_lines.0643"), TXT("bible_lines.0644"), TXT("bible_lines.0645"),
              TXT("bible_lines.0646"), TXT("bible_lines.0647"), TXT("bible_lines.0648"), TXT("bible_lines.0649")],
    "love": [TXT("bible_lines.0650"), TXT("bible_lines.0651"), TXT("bible_lines.0652"), TXT("bible_lines.0653"),
             TXT("bible_lines.0654"), TXT("bible_lines.0655"), TXT("bible_lines.0656"), TXT("bible_lines.0657")],
    "mood": [TXT("bible_lines.0658"), TXT("bible_lines.0659"), TXT("bible_lines.0660"), TXT("bible_lines.0661"),
             TXT("bible_lines.0662"), TXT("bible_lines.0663"), TXT("bible_lines.0664"), TXT("bible_lines.0665")],
    "food": [TXT("bible_lines.0666"), TXT("bible_lines.0667"), TXT("bible_lines.0668"), TXT("bible_lines.0669"),
             TXT("bible_lines.0670"), TXT("bible_lines.0671"), TXT("bible_lines.0672"), TXT("bible_lines.0673")],
    "traffic": [TXT("bible_lines.0674"), TXT("bible_lines.0675"), TXT("bible_lines.0676"), TXT("bible_lines.0677"),
                TXT("bible_lines.0678"), TXT("bible_lines.0679"), TXT("bible_lines.0680"), TXT("bible_lines.0681")],
    "genz": [TXT("bible_lines.0682"), TXT("bible_lines.0683"), TXT("bible_lines.0684"), TXT("bible_lines.0685"), TXT("bible_lines.0686"),
             TXT("bible_lines.0687"), TXT("bible_lines.0688"), TXT("bible_lines.0689"), TXT("bible_lines.0690"), TXT("bible_lines.0691")],
    "idiom": [TXT("bible_lines.0692"), TXT("bible_lines.0693"), TXT("bible_lines.0694"), TXT("bible_lines.0695"), TXT("bible_lines.0696"),
              TXT("bible_lines.0697"), TXT("bible_lines.0698"), TXT("bible_lines.0699"), TXT("bible_lines.0700")],
    "street": [TXT("bible_lines.0701"), TXT("bible_lines.0702"), TXT("bible_lines.0703"), TXT("bible_lines.0704"), TXT("bible_lines.0705"),
               TXT("bible_lines.0706"), TXT("bible_lines.0707"), TXT("bible_lines.0708"), TXT("bible_lines.0709"), TXT("bible_lines.0710")],
}

# кој стил кои теми ги зборува (афинитет)
AFFINITY = {
    "old": ["muabet", "money", "traffic", "idiom", "food", "mood"],
    "woman": ["muabet", "love", "food", "money", "mood", "greet"],
    "kid": ["genz", "food", "mood", "greet"],
    "tough": ["greet", "night", "street", "money", "traffic", "muabet"],
    "posh": ["money", "night", "genz", "greet", "street"],
    "youth": ["genz", "love", "night", "greet", "mood", "street"],
    "sport": ["genz", "night", "mood", "idiom", "greet"],
    "pop": ["idiom", "muabet", "food", "mood"],
    "vendor": ["money", "food", "greet", "traffic", "street"],
    "cop": ["traffic", "street", "muabet", "idiom"],
}


def topic_line(arch_id, rng=random):
    name = rng.choice(AFFINITY.get(style_of(arch_id), ["greet"]))
    return rng.choice(TOPICS[name])


# ===================================================================== населби (од речникот 121-150)
HOOD = {
    TXT("bible_lines.0711"): [TXT("bible_lines.0712"), TXT("bible_lines.0713"), TXT("bible_lines.0714")],
    TXT("bible_lines.0715"): [TXT("bible_lines.0716"), TXT("bible_lines.0717"), TXT("bible_lines.0718")],
    TXT("bible_lines.0719"): [TXT("bible_lines.0720"), TXT("bible_lines.0721"), TXT("bible_lines.0722")],
    TXT("bible_lines.0723"): [TXT("bible_lines.0724"), TXT("bible_lines.0725")],
    TXT("bible_lines.0726"): [TXT("bible_lines.0727"), TXT("bible_lines.0728")],
    TXT("bible_lines.0729"): [TXT("bible_lines.0730"), TXT("bible_lines.0731")],
    TXT("bible_lines.0732"): [TXT("bible_lines.0733"), TXT("bible_lines.0734")],
    TXT("bible_lines.0735"): [TXT("bible_lines.0736"), TXT("bible_lines.0737")],
    TXT("bible_lines.0738"): [TXT("bible_lines.0739"), TXT("bible_lines.0740")],
    TXT("bible_lines.0741"): [TXT("bible_lines.0742"), TXT("bible_lines.0743")],
    TXT("bible_lines.0744"): [TXT("bible_lines.0745"), TXT("bible_lines.0746")],
    TXT("bible_lines.0747"): [TXT("bible_lines.0748"), TXT("bible_lines.0749")],
}


def hood_lines(name):
    base = name.replace(TXT("bible_lines.0750"), "").replace(TXT("bible_lines.0751"), "")
    root = base.rsplit(" ", 1)[0] if base[-1:].isdigit() else base
    return HOOD.get(base) or HOOD.get(root) or []


# ===================================================================== лик на играчот (hero_lines.py): уште реплики по лик
HERO = {
    "kumplung": [TXT("bible_lines.0752"), TXT("bible_lines.0753"), TXT("bible_lines.0754"),
                 TXT("bible_lines.0755"), TXT("bible_lines.0756")],
    "maca": [TXT("bible_lines.0757"), TXT("bible_lines.0758"), TXT("bible_lines.0759"), TXT("bible_lines.0760"),
             TXT("bible_lines.0761")],
    "mile": [TXT("bible_lines.0762"), TXT("bible_lines.0763"), TXT("bible_lines.0764"), TXT("bible_lines.0765"),
             TXT("bible_lines.0766")],
    "stojan": [TXT("bible_lines.0767"), TXT("bible_lines.0768"), TXT("bible_lines.0769"), TXT("bible_lines.0770"),
               TXT("bible_lines.0771")],
    "influenser": [TXT("bible_lines.0772"), TXT("bible_lines.0773"), TXT("bible_lines.0774"), TXT("bible_lines.0775"),
                   TXT("bible_lines.0776")],
    "influenserka": [TXT("bible_lines.0777"), TXT("bible_lines.0778"), TXT("bible_lines.0779"), TXT("bible_lines.0780"),
                     TXT("bible_lines.0781")],
    "tetkica": [TXT("bible_lines.0782"), TXT("bible_lines.0783"), TXT("bible_lines.0784"), TXT("bible_lines.0785"),
                TXT("bible_lines.0786")],
    "baba": [TXT("bible_lines.0787"), TXT("bible_lines.0788"), TXT("bible_lines.0789"), TXT("bible_lines.0790"),
             TXT("bible_lines.0791")],
    "dedo": [TXT("bible_lines.0792"), TXT("bible_lines.0793"), TXT("bible_lines.0794"), TXT("bible_lines.0795"),
             TXT("bible_lines.0796")],
    "pandur": [TXT("bible_lines.0797"), TXT("bible_lines.0798"), TXT("bible_lines.0799"), TXT("bible_lines.0800"), TXT("bible_lines.0801")],
    "doktor": [TXT("bible_lines.0802"), TXT("bible_lines.0803"), TXT("bible_lines.0804"), TXT("bible_lines.0805"),
               TXT("bible_lines.0806")],
    "mali": [TXT("bible_lines.0807"), TXT("bible_lines.0808"), TXT("bible_lines.0809"), TXT("bible_lines.0810"), TXT("bible_lines.0811")],
    "radnik": [TXT("bible_lines.0812"), TXT("bible_lines.0813"), TXT("bible_lines.0814"), TXT("bible_lines.0815"),
               TXT("bible_lines.0816")],
    "burek": [TXT("bible_lines.0817"), TXT("bible_lines.0818"), TXT("bible_lines.0819"), TXT("bible_lines.0820"), TXT("bible_lines.0821")],
    "boza": [TXT("bible_lines.0822"), TXT("bible_lines.0823"), TXT("bible_lines.0824"), TXT("bible_lines.0825"), TXT("bible_lines.0826")],
    "fitka": [TXT("bible_lines.0827"), TXT("bible_lines.0828"), TXT("bible_lines.0829"), TXT("bible_lines.0830"), TXT("bible_lines.0831")],
    "bilder": [TXT("bible_lines.0832"), TXT("bible_lines.0833"), TXT("bible_lines.0834"), TXT("bible_lines.0835"), TXT("bible_lines.0836")],
    "shmizla": [TXT("bible_lines.0837"), TXT("bible_lines.0838"), TXT("bible_lines.0839"), TXT("bible_lines.0840"), TXT("bible_lines.0841")],
    "palavko": [TXT("bible_lines.0842"), TXT("bible_lines.0843"), TXT("bible_lines.0844"), TXT("bible_lines.0845"), TXT("bible_lines.0846")],
    "srednoskolec": [TXT("bible_lines.0847"), TXT("bible_lines.0848"), TXT("bible_lines.0849"), TXT("bible_lines.0850"), TXT("bible_lines.0851")],
    "vojnik": [TXT("bible_lines.0852"), TXT("bible_lines.0853"), TXT("bible_lines.0854"), TXT("bible_lines.0855"), TXT("bible_lines.0856")],
    "navivac": [TXT("bible_lines.0857"), TXT("bible_lines.0858"), TXT("bible_lines.0859"), TXT("bible_lines.0860"), TXT("bible_lines.0861")],
    "administratorka": [TXT("bible_lines.0862"), TXT("bible_lines.0863"), TXT("bible_lines.0864"), TXT("bible_lines.0865"), TXT("bible_lines.0866")],
    "nastavnica": [TXT("bible_lines.0867"), TXT("bible_lines.0868"), TXT("bible_lines.0869"), TXT("bible_lines.0870"), TXT("bible_lines.0871")],
}

# ===================================================================== NSFW (ниво 2): неограничено
NSFW_MAX = [
    TXT("bible_lines.0872"), TXT("bible_lines.0873"), TXT("bible_lines.0874"),
    TXT("bible_lines.0875"), TXT("bible_lines.0876"), TXT("bible_lines.0877"),
    TXT("bible_lines.0878"), TXT("bible_lines.0879"), TXT("bible_lines.0880"),
    TXT("bible_lines.0881"), TXT("bible_lines.0882"), TXT("bible_lines.0883"),
    TXT("bible_lines.0884"), TXT("bible_lines.0885"), TXT("bible_lines.0886"),
    TXT("bible_lines.0887"), TXT("bible_lines.0888"), TXT("bible_lines.0889"),
    TXT("bible_lines.0890"), TXT("bible_lines.0891"), TXT("bible_lines.0892"),
    TXT("bible_lines.0893"), TXT("bible_lines.0894"), TXT("bible_lines.0895"),
]


# ===================================================================== уште термини од речникот (втор круг)
TOPICS["greet"] += [TXT("bible_lines.0896"), TXT("bible_lines.0897"), TXT("bible_lines.0898"), TXT("bible_lines.0899"), TXT("bible_lines.0900"), TXT("bible_lines.0901")]
TOPICS["muabet"] += [
    TXT("bible_lines.0902"), TXT("bible_lines.0903"), TXT("bible_lines.0904"), TXT("bible_lines.0905"),
    TXT("bible_lines.0906"), TXT("bible_lines.0907"), TXT("bible_lines.0908"), TXT("bible_lines.0909"),
    TXT("bible_lines.0910"), TXT("bible_lines.0911"), TXT("bible_lines.0912"), TXT("bible_lines.0913"),
    TXT("bible_lines.0914"), TXT("bible_lines.0915"), TXT("bible_lines.0916"), TXT("bible_lines.0917"),
    TXT("bible_lines.0918"), TXT("bible_lines.0919"), TXT("bible_lines.0920"), TXT("bible_lines.0921"),
    TXT("bible_lines.0922"), TXT("bible_lines.0923")]
TOPICS["street"] += [
    TXT("bible_lines.0924"), TXT("bible_lines.0925"), TXT("bible_lines.0926"), TXT("bible_lines.0927"),
    TXT("bible_lines.0928"), TXT("bible_lines.0929"), TXT("bible_lines.0930"), TXT("bible_lines.0931"),
    TXT("bible_lines.0932"), TXT("bible_lines.0933"), TXT("bible_lines.0934"), TXT("bible_lines.0935"),
    TXT("bible_lines.0936"), TXT("bible_lines.0937"), TXT("bible_lines.0938"), TXT("bible_lines.0939"),
    TXT("bible_lines.0940"), TXT("bible_lines.0941")]
TOPICS["night"] += [
    TXT("bible_lines.0942"), TXT("bible_lines.0943"), TXT("bible_lines.0944"), TXT("bible_lines.0945"),
    TXT("bible_lines.0946"), TXT("bible_lines.0947"), TXT("bible_lines.0948"), TXT("bible_lines.0949"),
    TXT("bible_lines.0950"), TXT("bible_lines.0951"), TXT("bible_lines.0952"), TXT("bible_lines.0953")]
TOPICS["money"] += [
    TXT("bible_lines.0954"), TXT("bible_lines.0955"), TXT("bible_lines.0956"), TXT("bible_lines.0957"),
    TXT("bible_lines.0958"), TXT("bible_lines.0959"), TXT("bible_lines.0960"), TXT("bible_lines.0961"),
    TXT("bible_lines.0962"), TXT("bible_lines.0963")]
TOPICS["love"] += [
    TXT("bible_lines.0964"), TXT("bible_lines.0965"), TXT("bible_lines.0966"), TXT("bible_lines.0967"), TXT("bible_lines.0968"),
    TXT("bible_lines.0969"), TXT("bible_lines.0970"), TXT("bible_lines.0971"), TXT("bible_lines.0972"), TXT("bible_lines.0973"),
    TXT("bible_lines.0974"), TXT("bible_lines.0975"), TXT("bible_lines.0976"), TXT("bible_lines.0977"), TXT("bible_lines.0978"),
    TXT("bible_lines.0979"), TXT("bible_lines.0980"), TXT("bible_lines.0981"), TXT("bible_lines.0982")]
TOPICS["mood"] += [
    TXT("bible_lines.0983"), TXT("bible_lines.0984"), TXT("bible_lines.0985"), TXT("bible_lines.0986"), TXT("bible_lines.0987"),
    TXT("bible_lines.0988"), TXT("bible_lines.0989"), TXT("bible_lines.0990"), TXT("bible_lines.0991"), TXT("bible_lines.0992"),
    TXT("bible_lines.0993"), TXT("bible_lines.0994"), TXT("bible_lines.0995"), TXT("bible_lines.0996"), TXT("bible_lines.0997"),
    TXT("bible_lines.0998"), TXT("bible_lines.0999"), TXT("bible_lines.1000"), TXT("bible_lines.1001"), TXT("bible_lines.1002"),
    TXT("bible_lines.1003")]
TOPICS["food"] += [
    TXT("bible_lines.1004"), TXT("bible_lines.1005"), TXT("bible_lines.1006"), TXT("bible_lines.1007"),
    TXT("bible_lines.1008"), TXT("bible_lines.1009"), TXT("bible_lines.1010"), TXT("bible_lines.1011"),
    TXT("bible_lines.1012"), TXT("bible_lines.1013"), TXT("bible_lines.1014"), TXT("bible_lines.1015"), TXT("bible_lines.1016")]
TOPICS["traffic"] += [
    TXT("bible_lines.1017"), TXT("bible_lines.1018"), TXT("bible_lines.1019"), TXT("bible_lines.1020"),
    TXT("bible_lines.1021"), TXT("bible_lines.1022"), TXT("bible_lines.1023")]
TOPICS["genz"] += [
    TXT("bible_lines.1024"), TXT("bible_lines.1025"), TXT("bible_lines.1026"), TXT("bible_lines.1027"), TXT("bible_lines.1028"),
    TXT("bible_lines.1029"), TXT("bible_lines.1030"), TXT("bible_lines.1031"), TXT("bible_lines.1032"), TXT("bible_lines.1033"),
    TXT("bible_lines.1034")]
TOPICS["idiom"] += [
    TXT("bible_lines.1035"), TXT("bible_lines.1036"), TXT("bible_lines.1037"), TXT("bible_lines.1038"), TXT("bible_lines.1039"), TXT("bible_lines.1040"),
    TXT("bible_lines.1041"), TXT("bible_lines.1042"), TXT("bible_lines.1043"), TXT("bible_lines.1044"), TXT("bible_lines.1045"), TXT("bible_lines.1046"),
    TXT("bible_lines.1047")]

# ликови на играчот: втор круг
HERO["kumplung"] += [TXT("bible_lines.1048"), TXT("bible_lines.1049"), TXT("bible_lines.1050")]
HERO["maca"] += [TXT("bible_lines.1051"), TXT("bible_lines.1052"), TXT("bible_lines.1053")]
HERO["mile"] += [TXT("bible_lines.1054"), TXT("bible_lines.1055"), TXT("bible_lines.1056")]
HERO["stojan"] += [TXT("bible_lines.1057"), TXT("bible_lines.1058"), TXT("bible_lines.1059")]
HERO["influenser"] += [TXT("bible_lines.1060"), TXT("bible_lines.1061"), TXT("bible_lines.1062")]
HERO["influenserka"] += [TXT("bible_lines.1063"), TXT("bible_lines.1064"), TXT("bible_lines.1065")]
HERO["tetkica"] += [TXT("bible_lines.1066"), TXT("bible_lines.1067"), TXT("bible_lines.1068")]
HERO["baba"] += [TXT("bible_lines.1069"), TXT("bible_lines.1070"), TXT("bible_lines.1071")]
HERO["dedo"] += [TXT("bible_lines.1072"), TXT("bible_lines.1073"), TXT("bible_lines.1074")]
HERO["pandur"] += [TXT("bible_lines.1075"), TXT("bible_lines.1076"), TXT("bible_lines.1077")]
HERO["doktor"] += [TXT("bible_lines.1078"), TXT("bible_lines.1079"), TXT("bible_lines.1080")]
HERO["mali"] += [TXT("bible_lines.1081"), TXT("bible_lines.1082"), TXT("bible_lines.1083")]
HERO["radnik"] += [TXT("bible_lines.1084"), TXT("bible_lines.1085"), TXT("bible_lines.1086")]
HERO["burek"] += [TXT("bible_lines.1087"), TXT("bible_lines.1088"), TXT("bible_lines.1089")]
HERO["boza"] += [TXT("bible_lines.1090"), TXT("bible_lines.1091"), TXT("bible_lines.1092")]
HERO["fitka"] += [TXT("bible_lines.1093"), TXT("bible_lines.1094"), TXT("bible_lines.1095")]
HERO["bilder"] += [TXT("bible_lines.1096"), TXT("bible_lines.1097"), TXT("bible_lines.1098")]
HERO["shmizla"] += [TXT("bible_lines.1099"), TXT("bible_lines.1100"), TXT("bible_lines.1101")]
HERO["palavko"] += [TXT("bible_lines.1102"), TXT("bible_lines.1103"), TXT("bible_lines.1104")]
HERO["srednoskolec"] += [TXT("bible_lines.1105"), TXT("bible_lines.1106"), TXT("bible_lines.1107")]
HERO["vojnik"] += [TXT("bible_lines.1108"), TXT("bible_lines.1109"), TXT("bible_lines.1110")]
HERO["navivac"] += [TXT("bible_lines.1111"), TXT("bible_lines.1112"), TXT("bible_lines.1113")]
HERO["administratorka"] += [TXT("bible_lines.1114"), TXT("bible_lines.1115"), TXT("bible_lines.1116")]
HERO["nastavnica"] += [TXT("bible_lines.1117"), TXT("bible_lines.1118"), TXT("bible_lines.1119")]
