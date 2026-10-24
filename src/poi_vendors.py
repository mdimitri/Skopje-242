"""Per-place menus: on the first load every POI gets a guessed vendor type (from its name, else from its OSM category)
and a witty set of 3 purchases + 1 freebie that such a shop might really sell in Skopje.
Item = (label, price ден., heal, gain ден., what the avatar says).  Stable per place (seeded by its name)."""
from texts import TXT
import json
import os
import random
import zlib

VERSION = 4
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# vendor: (title, [5 purchasable items], [2 free / money items])
V = {
    "pekara": (TXT("poi_vendors.0001"), [
        (TXT("poi_vendors.0002"), 40, 8, 0, TXT("poi_vendors.0003")), (TXT("poi_vendors.0004"), 90, 20, 0, TXT("poi_vendors.0005")), (TXT("poi_vendors.0006"), 35, 10, 0, TXT("poi_vendors.0007")),
        (TXT("poi_vendors.0008"), 110, 18, 0, TXT("poi_vendors.0009")), (TXT("poi_vendors.0010"), 30, 6, 0, TXT("poi_vendors.0011"))],
        [(TXT("poi_vendors.0012"), 0, 4, 0, TXT("poi_vendors.0013")), (TXT("poi_vendors.0014"), 0, -3, 60, TXT("poi_vendors.0015"))]),
    "burek": (TXT("poi_vendors.0016"), [
        (TXT("poi_vendors.0017"), 120, 25, 0, TXT("poi_vendors.0018")), (TXT("poi_vendors.0019"), 130, 28, 0, TXT("poi_vendors.0020")), (TXT("poi_vendors.0021"), 100, 20, 0, TXT("poi_vendors.0022")),
        (TXT("poi_vendors.0023"), 95, 18, 0, TXT("poi_vendors.0024")), (TXT("poi_vendors.0025"), 220, 45, 0, TXT("poi_vendors.0026"))],
        [(TXT("poi_vendors.0027"), 0, 3, 0, TXT("poi_vendors.0028")), (TXT("poi_vendors.0029"), 0, 2, 0, TXT("poi_vendors.0030"))]),
    "kebab": (TXT("poi_vendors.0031"), [
        (TXT("poi_vendors.0032"), 280, 38, 0, TXT("poi_vendors.0033")), (TXT("poi_vendors.0034"), 240, 34, 0, TXT("poi_vendors.0035")), (TXT("poi_vendors.0036"), 260, 36, 0, TXT("poi_vendors.0037")),
        (TXT("poi_vendors.0038"), 80, 12, 0, TXT("poi_vendors.0039")), (TXT("poi_vendors.0040"), 70, 3, 0, TXT("poi_vendors.0041"))],
        [(TXT("poi_vendors.0042"), 0, 4, 0, TXT("poi_vendors.0043")), (TXT("poi_vendors.0044"), 0, -2, 40, TXT("poi_vendors.0045"))]),
    "pizza": (TXT("poi_vendors.0046"), [
        (TXT("poi_vendors.0047"), 90, 14, 0, TXT("poi_vendors.0048")), (TXT("poi_vendors.0049"), 190, 26, 0, TXT("poi_vendors.0050")), (TXT("poi_vendors.0051"), 180, 24, 0, TXT("poi_vendors.0052")),
        (TXT("poi_vendors.0053"), 80, 10, 0, TXT("poi_vendors.0054")), (TXT("poi_vendors.0055"), 100, 15, 0, TXT("poi_vendors.0056"))],
        [(TXT("poi_vendors.0057"), 0, 1, 0, TXT("poi_vendors.0058")), (TXT("poi_vendors.0059"), 0, -3, 70, TXT("poi_vendors.0060"))]),
    "mehana": (TXT("poi_vendors.0061"), [
        (TXT("poi_vendors.0062"), 250, 32, 0, TXT("poi_vendors.0063")), (TXT("poi_vendors.0064"), 180, 15, 0, TXT("poi_vendors.0065")), (TXT("poi_vendors.0066"), 480, 55, 0, TXT("poi_vendors.0067")),
        (TXT("poi_vendors.0068"), 220, 22, 0, TXT("poi_vendors.0069")), (TXT("poi_vendors.0070"), 150, 12, 0, TXT("poi_vendors.0071"))],
        [(TXT("poi_vendors.0072"), 0, 1, 0, TXT("poi_vendors.0073")), (TXT("poi_vendors.0074"), 0, -5, 120, TXT("poi_vendors.0075"))]),
    "kafeana": (TXT("poi_vendors.0076"), [
        (TXT("poi_vendors.0077"), 130, 12, 0, TXT("poi_vendors.0078")), (TXT("poi_vendors.0079"), 100, 8, 0, TXT("poi_vendors.0080")), (TXT("poi_vendors.0081"), 320, 14, 0, TXT("poi_vendors.0082")),
        (TXT("poi_vendors.0083"), 170, 15, 0, TXT("poi_vendors.0084")), (TXT("poi_vendors.0085"), 80, 8, 0, TXT("poi_vendors.0086"))],
        [(TXT("poi_vendors.0087"), 0, 3, 0, TXT("poi_vendors.0088")), (TXT("poi_vendors.0089"), 0, 0, 150, TXT("poi_vendors.0090"))]),
    "kafe": (TXT("poi_vendors.0091"), [
        (TXT("poi_vendors.0092"), 60, 8, 0, TXT("poi_vendors.0093")), (TXT("poi_vendors.0094"), 90, 10, 0, TXT("poi_vendors.0095")), (TXT("poi_vendors.0096"), 140, 12, 0, TXT("poi_vendors.0097")),
        (TXT("poi_vendors.0098"), 70, 10, 0, TXT("poi_vendors.0099")), (TXT("poi_vendors.0100"), 80, 8, 0, TXT("poi_vendors.0101"))],
        [(TXT("poi_vendors.0102"), 0, 5, 0, TXT("poi_vendors.0103")), (TXT("poi_vendors.0104"), 0, 1, 0, TXT("poi_vendors.0105"))]),
    "slatkarnica": (TXT("poi_vendors.0106"), [
        (TXT("poi_vendors.0107"), 80, 10, 0, TXT("poi_vendors.0108")), (TXT("poi_vendors.0109"), 140, 14, 0, TXT("poi_vendors.0110")), (TXT("poi_vendors.0111"), 120, 14, 0, TXT("poi_vendors.0112")),
        (TXT("poi_vendors.0113"), 110, 12, 0, TXT("poi_vendors.0114")), (TXT("poi_vendors.0115"), 90, 9, 0, TXT("poi_vendors.0116"))],
        [(TXT("poi_vendors.0117"), 0, 3, 0, TXT("poi_vendors.0118")), (TXT("poi_vendors.0119"), 0, -2, 60, TXT("poi_vendors.0120"))]),
    "market": (TXT("poi_vendors.0121"), [
        (TXT("poi_vendors.0122"), 90, 10, 0, TXT("poi_vendors.0123")), (TXT("poi_vendors.0124"), 380, 32, 0, TXT("poi_vendors.0125")), (TXT("poi_vendors.0126"), 60, 6, 0, TXT("poi_vendors.0127")),
        (TXT("poi_vendors.0128"), 170, 0, 0, TXT("poi_vendors.0129")), (TXT("poi_vendors.0130"), 120, 10, 0, TXT("poi_vendors.0131"))],
        [(TXT("poi_vendors.0132"), 0, 0, 50, TXT("poi_vendors.0133")), (TXT("poi_vendors.0134"), 0, -1, 20, TXT("poi_vendors.0135"))]),
    "kiosk": (TXT("poi_vendors.0136"), [
        (TXT("poi_vendors.0137"), 160, -2, 0, TXT("poi_vendors.0138")), (TXT("poi_vendors.0139"), 90, 8, 0, TXT("poi_vendors.0140")), (TXT("poi_vendors.0141"), 40, 3, 0, TXT("poi_vendors.0142")),
        (TXT("poi_vendors.0143"), 100, 0, 0, TXT("poi_vendors.0144")), (TXT("poi_vendors.0145"), 200, 0, 0, TXT("poi_vendors.0146"))],
        [(TXT("poi_vendors.0147"), 0, 1, 0, TXT("poi_vendors.0148")), (TXT("poi_vendors.0149"), 0, 0, 120, TXT("poi_vendors.0150"))]),
    "apteka": (TXT("poi_vendors.0151"), [
        (TXT("poi_vendors.0152"), 60, 15, 0, TXT("poi_vendors.0153")), (TXT("poi_vendors.0154"), 140, 22, 0, TXT("poi_vendors.0155")), (TXT("poi_vendors.0156"), 190, 30, 0, TXT("poi_vendors.0157")),
        (TXT("poi_vendors.0158"), 480, 45, 0, TXT("poi_vendors.0159")), (TXT("poi_vendors.0160"), 30, 8, 0, TXT("poi_vendors.0161"))],
        [(TXT("poi_vendors.0162"), 0, 4, 0, TXT("poi_vendors.0163")), (TXT("poi_vendors.0164"), 0, 2, 0, TXT("poi_vendors.0165"))]),
    "tech": (TXT("poi_vendors.0166"), [
        (TXT("poi_vendors.0167"), 250, 0, 0, TXT("poi_vendors.0168")), (TXT("poi_vendors.0169"), 420, 6, 0, TXT("poi_vendors.0170")), (TXT("poi_vendors.0171"), 150, 0, 0, TXT("poi_vendors.0172")),
        (TXT("poi_vendors.0173"), 900, 12, 0, TXT("poi_vendors.0174")), (TXT("poi_vendors.0175"), 380, 3, 0, TXT("poi_vendors.0176"))],
        [(TXT("poi_vendors.0177"), 0, 4, 0, TXT("poi_vendors.0178")), (TXT("poi_vendors.0179"), 0, 0, 220, TXT("poi_vendors.0180"))]),
    "clothes": (TXT("poi_vendors.0181"), [
        (TXT("poi_vendors.0182"), 400, 4, 0, TXT("poi_vendors.0183")), (TXT("poi_vendors.0184"), 800, 5, 0, TXT("poi_vendors.0185")), (TXT("poi_vendors.0186"), 100, 2, 0, TXT("poi_vendors.0187")),
        (TXT("poi_vendors.0188"), 1200, 8, 0, TXT("poi_vendors.0189")), (TXT("poi_vendors.0190"), 350, 4, 0, TXT("poi_vendors.0191"))],
        [(TXT("poi_vendors.0192"), 0, 3, 0, TXT("poi_vendors.0193")), (TXT("poi_vendors.0194"), 0, -2, 70, TXT("poi_vendors.0195"))]),
    "barber": (TXT("poi_vendors.0196"), [
        (TXT("poi_vendors.0197"), 250, 6, 0, TXT("poi_vendors.0198")), (TXT("poi_vendors.0199"), 200, 8, 0, TXT("poi_vendors.0200")), (TXT("poi_vendors.0201"), 700, 5, 0, TXT("poi_vendors.0202")),
        (TXT("poi_vendors.0203"), 150, 12, 0, TXT("poi_vendors.0204")), (TXT("poi_vendors.0205"), 180, 6, 0, TXT("poi_vendors.0206"))],
        [(TXT("poi_vendors.0207"), 0, 3, 0, TXT("poi_vendors.0208")), (TXT("poi_vendors.0209"), 0, -2, 60, TXT("poi_vendors.0210"))]),
    "cvekjarnica": (TXT("poi_vendors.0211"), [
        (TXT("poi_vendors.0212"), 450, 6, 0, TXT("poi_vendors.0213")), (TXT("poi_vendors.0214"), 200, 3, 0, TXT("poi_vendors.0215")), (TXT("poi_vendors.0216"), 160, 4, 0, TXT("poi_vendors.0217")),
        (TXT("poi_vendors.0218"), 800, 5, 0, TXT("poi_vendors.0219")), (TXT("poi_vendors.0220"), 40, 1, 0, TXT("poi_vendors.0221"))],
        [(TXT("poi_vendors.0222"), 0, 4, 0, TXT("poi_vendors.0223")), (TXT("poi_vendors.0224"), 0, -3, 60, TXT("poi_vendors.0225"))]),
    "menuvacnica": (TXT("poi_vendors.0226"), [
        (TXT("poi_vendors.0227"), 300, 0, 380, TXT("poi_vendors.0228")), (TXT("poi_vendors.0229"), 250, 0, 0, TXT("poi_vendors.0230")), (TXT("poi_vendors.0231"), 100, 0, 0, TXT("poi_vendors.0232")),
        (TXT("poi_vendors.0233"), 500, 0, 0, TXT("poi_vendors.0234")), (TXT("poi_vendors.0235"), 200, 0, 0, TXT("poi_vendors.0236"))],
        [(TXT("poi_vendors.0237"), 0, 0, 500, TXT("poi_vendors.0238")), (TXT("poi_vendors.0239"), 0, 0, 100, TXT("poi_vendors.0240"))]),
    "bencin": (TXT("poi_vendors.0241"), [
        (TXT("poi_vendors.0242"), 1200, 0, 0, TXT("poi_vendors.0243")), (TXT("poi_vendors.0244"), 100, 10, 0, TXT("poi_vendors.0245")), (TXT("poi_vendors.0246"), 200, 0, 0, TXT("poi_vendors.0247")),
        (TXT("poi_vendors.0248"), 120, 14, 0, TXT("poi_vendors.0249")), (TXT("poi_vendors.0250"), 50, 6, 0, TXT("poi_vendors.0251"))],
        [(TXT("poi_vendors.0252"), 0, 0, 0, TXT("poi_vendors.0253")), (TXT("poi_vendors.0254"), 0, -1, 30, TXT("poi_vendors.0255"))]),
    "gradezen": (TXT("poi_vendors.0256"), [
        (TXT("poi_vendors.0257"), 450, -5, 0, TXT("poi_vendors.0258")), (TXT("poi_vendors.0259"), 380, 0, 0, TXT("poi_vendors.0260")), (TXT("poi_vendors.0261"), 260, 0, 0, TXT("poi_vendors.0262")),
        (TXT("poi_vendors.0263"), 1500, 0, 0, TXT("poi_vendors.0264")), (TXT("poi_vendors.0265"), 90, 0, 0, TXT("poi_vendors.0266"))],
        [(TXT("poi_vendors.0267"), 0, 2, 0, TXT("poi_vendors.0268")), (TXT("poi_vendors.0269"), 0, -6, 140, TXT("poi_vendors.0270"))]),
    "knigi": (TXT("poi_vendors.0271"), [
        (TXT("poi_vendors.0272"), 70, 1, 0, TXT("poi_vendors.0273")), (TXT("poi_vendors.0274"), 380, 6, 0, TXT("poi_vendors.0275")), (TXT("poi_vendors.0276"), 450, 3, 0, TXT("poi_vendors.0277")),
        (TXT("poi_vendors.0278"), 600, 2, 0, TXT("poi_vendors.0279")), (TXT("poi_vendors.0280"), 280, 6, 0, TXT("poi_vendors.0281"))],
        [(TXT("poi_vendors.0282"), 0, 4, 0, TXT("poi_vendors.0283")), (TXT("poi_vendors.0284"), 0, -2, 60, TXT("poi_vendors.0285"))]),
    "nakit": (TXT("poi_vendors.0286"), [
        (TXT("poi_vendors.0287"), 2400, 5, 0, TXT("poi_vendors.0288")), (TXT("poi_vendors.0289"), 650, 4, 0, TXT("poi_vendors.0290")), (TXT("poi_vendors.0291"), 3000, 8, 0, TXT("poi_vendors.0292")),
        (TXT("poi_vendors.0293"), 320, 2, 0, TXT("poi_vendors.0294")), (TXT("poi_vendors.0295"), 140, 1, 0, TXT("poi_vendors.0296"))],
        [(TXT("poi_vendors.0297"), 0, 3, 0, TXT("poi_vendors.0298")), (TXT("poi_vendors.0299"), 0, -1, 180, TXT("poi_vendors.0300"))]),
    "pazar": (TXT("poi_vendors.0301"), [
        (TXT("poi_vendors.0302"), 80, 10, 0, TXT("poi_vendors.0303")), (TXT("poi_vendors.0304"), 100, 12, 0, TXT("poi_vendors.0305")), (TXT("poi_vendors.0306"), 250, 20, 0, TXT("poi_vendors.0307")),
        (TXT("poi_vendors.0308"), 260, 22, 0, TXT("poi_vendors.0309")), (TXT("poi_vendors.0310"), 360, 24, 0, TXT("poi_vendors.0311"))],
        [(TXT("poi_vendors.0312"), 0, 3, 40, TXT("poi_vendors.0313")), (TXT("poi_vendors.0314"), 0, -1, 60, TXT("poi_vendors.0315"))]),
    "auto": (TXT("poi_vendors.0316"), [
        (TXT("poi_vendors.0317"), 400, 0, 0, TXT("poi_vendors.0318")), (TXT("poi_vendors.0319"), 280, 0, 0, TXT("poi_vendors.0320")), (TXT("poi_vendors.0321"), 1500, 0, 0, TXT("poi_vendors.0322")),
        (TXT("poi_vendors.0323"), 40, 1, 0, TXT("poi_vendors.0324")), (TXT("poi_vendors.0325"), 500, 0, 0, TXT("poi_vendors.0326"))],
        [(TXT("poi_vendors.0327"), 0, 3, 0, TXT("poi_vendors.0328")), (TXT("poi_vendors.0329"), 0, -2, 80, TXT("poi_vendors.0330"))]),
    "gym": (TXT("poi_vendors.0331"), [
        (TXT("poi_vendors.0332"), 200, 18, 0, TXT("poi_vendors.0333")), (TXT("poi_vendors.0334"), 250, 16, 0, TXT("poi_vendors.0335")), (TXT("poi_vendors.0336"), 600, 8, 0, TXT("poi_vendors.0337")),
        (TXT("poi_vendors.0338"), 500, 32, 0, TXT("poi_vendors.0339")), (TXT("poi_vendors.0340"), 100, 10, 0, TXT("poi_vendors.0341"))],
        [(TXT("poi_vendors.0342"), 0, 3, 0, TXT("poi_vendors.0343")), (TXT("poi_vendors.0344"), 0, -5, 90, TXT("poi_vendors.0345"))]),
}

# keyword (lower-case, Cyrillic or Latin) -> vendor; first match wins, so the specific ones come first
KEYS = [
    ("burek", (TXT("poi_vendors.0346"), "burek", TXT("poi_vendors.0347"))), ("pekara", (TXT("poi_vendors.0348"), "pekar", "bakery", TXT("poi_vendors.0349"), TXT("poi_vendors.0350"), "pastry")),
    ("kebab", (TXT("poi_vendors.0351"), TXT("poi_vendors.0352"), "kebap", "kebab", TXT("poi_vendors.0353"), TXT("poi_vendors.0354"), "skara", TXT("poi_vendors.0355"), "grill", TXT("poi_vendors.0356"))),
    ("pizza", (TXT("poi_vendors.0357"), "pizza", "burger", TXT("poi_vendors.0358"), "kfc", "mcd", "hot dog", TXT("poi_vendors.0359"), TXT("poi_vendors.0360"), "gyros", "fast food", "wok", "sandwich", TXT("poi_vendors.0361"), TXT("poi_vendors.0362"))),
    ("slatkarnica", (TXT("poi_vendors.0363"), "ice cream", "gelat", TXT("poi_vendors.0364"), TXT("poi_vendors.0365"), TXT("poi_vendors.0366"), TXT("poi_vendors.0367"), "tulumb", TXT("poi_vendors.0368"))),
    ("mehana", (TXT("poi_vendors.0369"), TXT("poi_vendors.0370"), "restor", "restaurant", TXT("poi_vendors.0371"), "tavern", TXT("poi_vendors.0372"), "bistro", TXT("poi_vendors.0373"), "trattoria", "trat")),
    ("kafeana", (TXT("poi_vendors.0374"), "kafeana", " pub", TXT("poi_vendors.0375"), " bar", TXT("poi_vendors.0376"), TXT("poi_vendors.0377"), "night", "club", TXT("poi_vendors.0378"), "lounge", TXT("poi_vendors.0379"))),
    ("kafe", (TXT("poi_vendors.0380"), "kafe", "cafe", "coffee", "espresso", TXT("poi_vendors.0381"), "caffe", "starbucks", TXT("poi_vendors.0382"), TXT("poi_vendors.0383"))),
    ("apteka", (TXT("poi_vendors.0384"), "apote", "apteka", "pharm", TXT("poi_vendors.0385"), "zegin", TXT("poi_vendors.0386"), TXT("poi_vendors.0387"))),
    ("tech", (TXT("poi_vendors.0388"), "mobil", "phone", TXT("poi_vendors.0389"), "tech", TXT("poi_vendors.0390"), "computer", TXT("poi_vendors.0391"), "electro", "neptun", TXT("poi_vendors.0392"), "setec", TXT("poi_vendors.0393"), "anhoch", TXT("poi_vendors.0394"), "gaming")),
    ("barber", (TXT("poi_vendors.0395"), "frizer", TXT("poi_vendors.0396"), "barber", TXT("poi_vendors.0397"), "salon", "beauty", TXT("poi_vendors.0398"), "cosmet", "nails", TXT("poi_vendors.0399"))),
    ("cvekjarnica", (TXT("poi_vendors.0400"), "cvek", "flower", "florist", TXT("poi_vendors.0401"))),
    ("menuvacnica", (TXT("poi_vendors.0402"), "menuvac", "exchange", TXT("poi_vendors.0403"), "western", TXT("poi_vendors.0404"), "bank", TXT("poi_vendors.0405"))),
    ("bencin", (TXT("poi_vendors.0406"), "petrol", "okta", TXT("poi_vendors.0407"), "makpetrol", TXT("poi_vendors.0408"), "lukoil", TXT("poi_vendors.0409"), "shell", TXT("poi_vendors.0410"), "fuel", "gas ")),
    ("gradezen", (TXT("poi_vendors.0411"), "builder", "hardware", TXT("poi_vendors.0412"), TXT("poi_vendors.0413"), "ceramic", TXT("poi_vendors.0414"), "boja", TXT("poi_vendors.0415"), "buildmart", TXT("poi_vendors.0416"))),
    ("knigi", (TXT("poi_vendors.0417"), "kniga", TXT("poi_vendors.0418"), "book", TXT("poi_vendors.0419"), "paper", TXT("poi_vendors.0420"), TXT("poi_vendors.0421"), TXT("poi_vendors.0422"))),
    ("nakit", (TXT("poi_vendors.0423"), TXT("poi_vendors.0424"), "zlat", TXT("poi_vendors.0425"), "jewel", TXT("poi_vendors.0426"), "optik", "optic", TXT("poi_vendors.0427"), "watch")),
    ("auto", (TXT("poi_vendors.0428"), "auto", TXT("poi_vendors.0429"), "guma", TXT("poi_vendors.0430"), "servis", "vulkan", TXT("poi_vendors.0431"), "mechanic", "tire")),
    ("gym", (TXT("poi_vendors.0432"), "fitness", "gym", TXT("poi_vendors.0433"), "sport", TXT("poi_vendors.0434"), "crossfit")),
    ("clothes", (TXT("poi_vendors.0435"), "fashion", TXT("poi_vendors.0436"), "shoes", TXT("poi_vendors.0437"), TXT("poi_vendors.0438"), "zara", "waikiki", TXT("poi_vendors.0439"), "boutique", "butik", "textile", TXT("poi_vendors.0440"), "kids", TXT("poi_vendors.0441"), TXT("poi_vendors.0442"))),
    ("pazar", (TXT("poi_vendors.0443"), "pazar", TXT("poi_vendors.0444"), TXT("poi_vendors.0445"), "fruit", "bitpazar", TXT("poi_vendors.0446"), "green")),
    ("market", ("market", TXT("poi_vendors.0447"), TXT("poi_vendors.0448"), TXT("poi_vendors.0449"), "vero", TXT("poi_vendors.0450"), "ramstor", TXT("poi_vendors.0451"), "tinex", TXT("poi_vendors.0452"), "kam ", TXT("poi_vendors.0453"), "reptil", TXT("poi_vendors.0454"), "mini ", "bakalnica", TXT("poi_vendors.0455"), TXT("poi_vendors.0456"))),
    ("kiosk", (TXT("poi_vendors.0457"), "kiosk", TXT("poi_vendors.0458"), "tobacco", TXT("poi_vendors.0459"), TXT("poi_vendors.0460"), "lotto")),
]
# second vendor set: (title, [options]) per kind; merged into V by _merge() below
_MORE = {
    "supermarket": (TXT("poi_vendors.0461"), [
        (TXT("poi_vendors.0462"), 5, 0, 0, TXT("poi_vendors.0463")),
        (TXT("poi_vendors.0464"), 35, 8, 0, TXT("poi_vendors.0465")),
        (TXT("poi_vendors.0466"), 190, 14, 0, TXT("poi_vendors.0467")),
        (TXT("poi_vendors.0468"), 260, 22, 0, TXT("poi_vendors.0469")),
        (TXT("poi_vendors.0470"), 0, 6, 0, TXT("poi_vendors.0471")),
        (TXT("poi_vendors.0472"), 0, 0, 30, TXT("poi_vendors.0473")),
        (TXT("poi_vendors.0474"), 100, 0, 150, TXT("poi_vendors.0475")),
        (TXT("poi_vendors.0476"), 0, 0, 0, TXT("poi_vendors.0477")),
        (TXT("poi_vendors.0478"), 40, 12, 0, TXT("poi_vendors.0479"))]),
    "minimarket": (TXT("poi_vendors.0480"), [
        (TXT("poi_vendors.0481"), 15, 0, 0, TXT("poi_vendors.0482")),
        (TXT("poi_vendors.0483"), 45, 10, 0, TXT("poi_vendors.0484")),
        (TXT("poi_vendors.0485"), 90, 16, 0, TXT("poi_vendors.0486")),
        (TXT("poi_vendors.0487"), 80, 6, 0, TXT("poi_vendors.0488")),
        (TXT("poi_vendors.0489"), 0, 0, 0, TXT("poi_vendors.0490")),
        (TXT("poi_vendors.0491"), 70, 8, 0, TXT("poi_vendors.0492")),
        (TXT("poi_vendors.0493"), 0, 2, 0, TXT("poi_vendors.0494"))]),
    "bakery": (TXT("poi_vendors.0495"), [
        (TXT("poi_vendors.0496"), 40, 12, 0, TXT("poi_vendors.0497")),
        (TXT("poi_vendors.0498"), 35, 14, 0, TXT("poi_vendors.0499")),
        (TXT("poi_vendors.0500"), 60, 18, 0, TXT("poi_vendors.0501")),
        (TXT("poi_vendors.0502"), 55, 15, 0, TXT("poi_vendors.0503")),
        (TXT("poi_vendors.0504"), 70, 10, 0, TXT("poi_vendors.0505")),
        (TXT("poi_vendors.0506"), 0, 4, 0, TXT("poi_vendors.0507")),
        (TXT("poi_vendors.0508"), 50, 8, 0, TXT("poi_vendors.0509"))]),
    "burek": (TXT("poi_vendors.0510"), [
        (TXT("poi_vendors.0511"), 70, 28, 0, TXT("poi_vendors.0512")),
        (TXT("poi_vendors.0513"), 110, 38, 0, TXT("poi_vendors.0514")),
        (TXT("poi_vendors.0515"), 40, 8, 0, TXT("poi_vendors.0516")),
        (TXT("poi_vendors.0517"), 65, 24, 0, TXT("poi_vendors.0518")),
        (TXT("poi_vendors.0519"), 60, 20, 0, TXT("poi_vendors.0520")),
        (TXT("poi_vendors.0521"), 0, 1, 0, TXT("poi_vendors.0522")),
        (TXT("poi_vendors.0523"), 280, 6, 0, TXT("poi_vendors.0524"))]),
    "kebab": (TXT("poi_vendors.0525"), [
        (TXT("poi_vendors.0526"), 220, 40, 0, TXT("poi_vendors.0527")),
        (TXT("poi_vendors.0528"), 260, 42, 0, TXT("poi_vendors.0529")),
        (TXT("poi_vendors.0530"), 70, 14, 0, TXT("poi_vendors.0531")),
        (TXT("poi_vendors.0532"), 150, 14, 0, TXT("poi_vendors.0533")),
        (TXT("poi_vendors.0534"), 50, 8, 0, TXT("poi_vendors.0535")),
        (TXT("poi_vendors.0536"), 40, 6, 0, TXT("poi_vendors.0537")),
        (TXT("poi_vendors.0538"), 100, 0, 0, TXT("poi_vendors.0539"))]),
    "pizza": (TXT("poi_vendors.0540"), [
        (TXT("poi_vendors.0541"), 350, 34, 0, TXT("poi_vendors.0542")),
        (TXT("poi_vendors.0543"), 120, 16, 0, TXT("poi_vendors.0544")),
        (TXT("poi_vendors.0545"), 330, 30, 0, TXT("poi_vendors.0546")),
        (TXT("poi_vendors.0547"), 0, 2, 0, TXT("poi_vendors.0548")),
        (TXT("poi_vendors.0549"), 70, 5, 0, TXT("poi_vendors.0550")),
        (TXT("poi_vendors.0551"), 90, 4, 0, TXT("poi_vendors.0552"))]),
    "sweets": (TXT("poi_vendors.0553"), [
        (TXT("poi_vendors.0554"), 40, 14, 0, TXT("poi_vendors.0555")),
        (TXT("poi_vendors.0556"), 120, 20, 0, TXT("poi_vendors.0557")),
        (TXT("poi_vendors.0558"), 80, 14, 0, TXT("poi_vendors.0559")),
        (TXT("poi_vendors.0560"), 90, 10, 0, TXT("poi_vendors.0561")),
        (TXT("poi_vendors.0562"), 800, 25, 0, TXT("poi_vendors.0563")),
        (TXT("poi_vendors.0564"), 110, 16, 0, TXT("poi_vendors.0565"))]),
    "cafe": (TXT("poi_vendors.0566"), [
        (TXT("poi_vendors.0567"), 60, 8, 0, TXT("poi_vendors.0568")),
        (TXT("poi_vendors.0569"), 110, 10, 0, TXT("poi_vendors.0570")),
        (TXT("poi_vendors.0571"), 120, 12, 0, TXT("poi_vendors.0572")),
        (TXT("poi_vendors.0573"), 80, 10, 0, TXT("poi_vendors.0574")),
        (TXT("poi_vendors.0575"), 0, 4, 0, TXT("poi_vendors.0576")),
        (TXT("poi_vendors.0577"), 0, 7, 0, TXT("poi_vendors.0578")),
        (TXT("poi_vendors.0579"), 130, 18, 0, TXT("poi_vendors.0580"))]),
    "kafana": (TXT("poi_vendors.0581"), [
        (TXT("poi_vendors.0582"), 150, 6, 0, TXT("poi_vendors.0583")),
        (TXT("poi_vendors.0584"), 380, 30, 0, TXT("poi_vendors.0585")),
        (TXT("poi_vendors.0586"), 160, 16, 0, TXT("poi_vendors.0587")),
        (TXT("poi_vendors.0588"), 100, 8, 0, TXT("poi_vendors.0589")),
        (TXT("poi_vendors.0590"), 200, 5, 0, TXT("poi_vendors.0591")),
        (TXT("poi_vendors.0592"), 140, 8, 0, TXT("poi_vendors.0593"))]),
    "bar": (TXT("poi_vendors.0594"), [
        (TXT("poi_vendors.0595"), 130, 10, 0, TXT("poi_vendors.0596")),
        (TXT("poi_vendors.0597"), 280, 12, 0, TXT("poi_vendors.0598")),
        (TXT("poi_vendors.0599"), 400, 14, 0, TXT("poi_vendors.0600")),
        (TXT("poi_vendors.0601"), 40, 3, 0, TXT("poi_vendors.0602")),
        (TXT("poi_vendors.0603"), 100, 4, 0, TXT("poi_vendors.0604")),
        (TXT("poi_vendors.0605"), 100, 0, 0, TXT("poi_vendors.0606"))]),
    "pharmacy": (TXT("poi_vendors.0607"), [
        (TXT("poi_vendors.0608"), 70, 15, 0, TXT("poi_vendors.0609")),
        (TXT("poi_vendors.0610"), 180, 25, 0, TXT("poi_vendors.0611")),
        (TXT("poi_vendors.0612"), 120, 18, 0, TXT("poi_vendors.0613")),
        (TXT("poi_vendors.0614"), 450, 10, 0, TXT("poi_vendors.0615")),
        (TXT("poi_vendors.0616"), 0, 4, 0, TXT("poi_vendors.0617")),
        (TXT("poi_vendors.0618"), 160, 22, 0, TXT("poi_vendors.0619")),
        (TXT("poi_vendors.0620"), 140, 12, 0, TXT("poi_vendors.0621"))]),
    "hospital": (TXT("poi_vendors.0622"), [
        (TXT("poi_vendors.0623"), 300, 60, 0, TXT("poi_vendors.0624")),
        (TXT("poi_vendors.0625"), 0, 5, 0, TXT("poi_vendors.0626")),
        (TXT("poi_vendors.0627"), 500, 70, 0, TXT("poi_vendors.0628")),
        (TXT("poi_vendors.0629"), 40, 6, 0, TXT("poi_vendors.0630")),
        (TXT("poi_vendors.0631"), 0, 8, 0, TXT("poi_vendors.0632"))]),
    "dentist": (TXT("poi_vendors.0633"), [
        (TXT("poi_vendors.0634"), 400, 20, 0, TXT("poi_vendors.0635")),
        (TXT("poi_vendors.0636"), 800, 30, 0, TXT("poi_vendors.0637")),
        (TXT("poi_vendors.0638"), 0, 4, 0, TXT("poi_vendors.0639")),
        (TXT("poi_vendors.0640"), 0, 3, 0, TXT("poi_vendors.0641"))]),
    "barber": (TXT("poi_vendors.0642"), [
        (TXT("poi_vendors.0643"), 250, 6, 0, TXT("poi_vendors.0644")),
        (TXT("poi_vendors.0645"), 180, 10, 0, TXT("poi_vendors.0646")),
        (TXT("poi_vendors.0647"), 600, 8, 0, TXT("poi_vendors.0648")),
        (TXT("poi_vendors.0649"), 0, 3, 0, TXT("poi_vendors.0650")),
        (TXT("poi_vendors.0651"), 300, 12, 0, TXT("poi_vendors.0652")),
        (TXT("poi_vendors.0653"), 150, 14, 0, TXT("poi_vendors.0654"))]),
    "beauty": (TXT("poi_vendors.0655"), [
        (TXT("poi_vendors.0656"), 700, 8, 0, TXT("poi_vendors.0657")),
        (TXT("poi_vendors.0658"), 500, 7, 0, TXT("poi_vendors.0659")),
        (TXT("poi_vendors.0660"), 350, 12, 0, TXT("poi_vendors.0661")),
        (TXT("poi_vendors.0662"), 900, 6, 0, TXT("poi_vendors.0663")),
        (TXT("poi_vendors.0664"), 0, 3, 0, TXT("poi_vendors.0665"))]),
    "mobile": (TXT("poi_vendors.0666"), [
        (TXT("poi_vendors.0667"), 100, 0, 0, TXT("poi_vendors.0668")),
        (TXT("poi_vendors.0669"), 250, 0, 0, TXT("poi_vendors.0670")),
        (TXT("poi_vendors.0671"), 350, 0, 0, TXT("poi_vendors.0672")),
        (TXT("poi_vendors.0673"), 1500, 5, 0, TXT("poi_vendors.0674")),
        (TXT("poi_vendors.0675"), 400, 6, 0, TXT("poi_vendors.0676")),
        (TXT("poi_vendors.0677"), 100, 0, 0, TXT("poi_vendors.0678"))]),
    "electronics": (TXT("poi_vendors.0679"), [
        (TXT("poi_vendors.0680"), 0, 0, 0, TXT("poi_vendors.0681")),
        (TXT("poi_vendors.0682"), 150, 0, 0, TXT("poi_vendors.0683")),
        (TXT("poi_vendors.0684"), 80, 0, 0, TXT("poi_vendors.0685")),
        (TXT("poi_vendors.0686"), 0, 0, 0, TXT("poi_vendors.0687"))]),
    "books": (TXT("poi_vendors.0688"), [
        (TXT("poi_vendors.0689"), 450, 8, 0, TXT("poi_vendors.0690")),
        (TXT("poi_vendors.0691"), 60, 2, 0, TXT("poi_vendors.0692")),
        (TXT("poi_vendors.0693"), 380, 8, 0, TXT("poi_vendors.0694")),
        (TXT("poi_vendors.0695"), 0, 4, 0, TXT("poi_vendors.0696")),
        (TXT("poi_vendors.0697"), 120, 0, 0, TXT("poi_vendors.0698"))]),
    "gym": (TXT("poi_vendors.0699"), [
        (TXT("poi_vendors.0700"), 200, 20, 0, TXT("poi_vendors.0701")),
        (TXT("poi_vendors.0702"), 250, 15, 0, TXT("poi_vendors.0703")),
        (TXT("poi_vendors.0704"), 400, 35, 0, TXT("poi_vendors.0705")),
        (TXT("poi_vendors.0706"), 0, 4, 0, TXT("poi_vendors.0707")),
        (TXT("poi_vendors.0708"), 180, 25, 0, TXT("poi_vendors.0709"))]),
    "florist": (TXT("poi_vendors.0710"), [
        (TXT("poi_vendors.0711"), 350, 8, 0, TXT("poi_vendors.0712")),
        (TXT("poi_vendors.0713"), 90, 6, 0, TXT("poi_vendors.0714")),
        (TXT("poi_vendors.0715"), 200, 5, 0, TXT("poi_vendors.0716")),
        (TXT("poi_vendors.0717"), 600, 0, 0, TXT("poi_vendors.0718"))]),
    "optics": (TXT("poi_vendors.0719"), [
        (TXT("poi_vendors.0720"), 1200, 6, 0, TXT("poi_vendors.0721")),
        (TXT("poi_vendors.0722"), 700, 5, 0, TXT("poi_vendors.0723")),
        (TXT("poi_vendors.0724"), 0, 8, 0, TXT("poi_vendors.0725")),
        (TXT("poi_vendors.0726"), 200, 3, 0, TXT("poi_vendors.0727"))]),
    "jewelry": (TXT("poi_vendors.0728"), [
        (TXT("poi_vendors.0729"), 3500, 10, 0, TXT("poi_vendors.0730")),
        (TXT("poi_vendors.0731"), 2000, 8, 0, TXT("poi_vendors.0732")),
        (TXT("poi_vendors.0733"), 0, 0, 900, TXT("poi_vendors.0734")),
        (TXT("poi_vendors.0735"), 0, 3, 0, TXT("poi_vendors.0736"))]),
    "clothes": (TXT("poi_vendors.0737"), [
        (TXT("poi_vendors.0738"), 400, 5, 0, TXT("poi_vendors.0739")),
        (TXT("poi_vendors.0740"), 1800, 6, 0, TXT("poi_vendors.0741")),
        (TXT("poi_vendors.0742"), 100, 3, 0, TXT("poi_vendors.0743")),
        (TXT("poi_vendors.0744"), 2200, 8, 0, TXT("poi_vendors.0745")),
        (TXT("poi_vendors.0746"), 0, 3, 0, TXT("poi_vendors.0747")),
        (TXT("poi_vendors.0748"), 0, 0, 0, TXT("poi_vendors.0749"))]),
    "shoes": (TXT("poi_vendors.0750"), [
        (TXT("poi_vendors.0751"), 2200, 6, 0, TXT("poi_vendors.0752")),
        (TXT("poi_vendors.0753"), 400, 4, 0, TXT("poi_vendors.0754")),
        (TXT("poi_vendors.0755"), 50, 0, 0, TXT("poi_vendors.0756")),
        (TXT("poi_vendors.0757"), 80, 4, 0, TXT("poi_vendors.0758"))]),
    "butcher": (TXT("poi_vendors.0759"), [
        (TXT("poi_vendors.0760"), 450, 24, 0, TXT("poi_vendors.0761")),
        (TXT("poi_vendors.0762"), 300, 16, 0, TXT("poi_vendors.0763")),
        (TXT("poi_vendors.0764"), 350, 20, 0, TXT("poi_vendors.0765")),
        (TXT("poi_vendors.0766"), 0, 0, 0, TXT("poi_vendors.0767")),
        (TXT("poi_vendors.0768"), 0, 3, 0, TXT("poi_vendors.0769"))]),
    "greengrocer": (TXT("poi_vendors.0770"), [
        (TXT("poi_vendors.0771"), 120, 15, 0, TXT("poi_vendors.0772")),
        (TXT("poi_vendors.0773"), 200, 14, 0, TXT("poi_vendors.0774")),
        (TXT("poi_vendors.0775"), 180, 12, 0, TXT("poi_vendors.0776")),
        (TXT("poi_vendors.0777"), 220, 18, 0, TXT("poi_vendors.0778")),
        (TXT("poi_vendors.0779"), 0, 4, 40, TXT("poi_vendors.0780"))]),
    "liquor": (TXT("poi_vendors.0781"), [
        (TXT("poi_vendors.0782"), 350, 8, 0, TXT("poi_vendors.0783")),
        (TXT("poi_vendors.0784"), 450, 6, 0, TXT("poi_vendors.0785")),
        (TXT("poi_vendors.0786"), 300, 8, 0, TXT("poi_vendors.0787")),
        (TXT("poi_vendors.0788"), 40, 8, 0, TXT("poi_vendors.0789"))]),
    "tobacco": (TXT("poi_vendors.0790"), [
        (TXT("poi_vendors.0791"), 180, 0, 0, TXT("poi_vendors.0792")),
        (TXT("poi_vendors.0793"), 10, 0, 0, TXT("poi_vendors.0794")),
        (TXT("poi_vendors.0795"), 40, 4, 0, TXT("poi_vendors.0796")),
        (TXT("poi_vendors.0797"), 30, 2, 0, TXT("poi_vendors.0798"))]),
    "betting": (TXT("poi_vendors.0799"), [
        (TXT("poi_vendors.0800"), 100, 0, 250, TXT("poi_vendors.0801")),
        (TXT("poi_vendors.0802"), 500, 0, 1200, TXT("poi_vendors.0803")),
        (TXT("poi_vendors.0804"), 100, 0, 250, TXT("poi_vendors.0805")),
        (TXT("poi_vendors.0806"), 0, 0, 0, TXT("poi_vendors.0807"))]),
    "exchange": (TXT("poi_vendors.0808"), [
        (TXT("poi_vendors.0809"), 0, 0, 50, TXT("poi_vendors.0810")),
        (TXT("poi_vendors.0811"), 0, 0, 0, TXT("poi_vendors.0812")),
        (TXT("poi_vendors.0813"), 0, 0, 80, TXT("poi_vendors.0814"))]),
    "bank": (TXT("poi_vendors.0815"), [
        (TXT("poi_vendors.0816"), 0, 0, 500, TXT("poi_vendors.0817")),
        (TXT("poi_vendors.0818"), 0, 0, 1000, TXT("poi_vendors.0819")),
        (TXT("poi_vendors.0820"), 0, 0, 100, TXT("poi_vendors.0821")),
        (TXT("poi_vendors.0822"), 0, 0, 300, TXT("poi_vendors.0823")),
        (TXT("poi_vendors.0824"), 0, 0, 0, TXT("poi_vendors.0825"))]),
    "atm": (TXT("poi_vendors.0826"), [
        (TXT("poi_vendors.0827"), 0, 0, 500, TXT("poi_vendors.0828")),
        (TXT("poi_vendors.0829"), 0, 0, 1000, TXT("poi_vendors.0830")),
        (TXT("poi_vendors.0831"), 0, 0, 100, TXT("poi_vendors.0832")),
        (TXT("poi_vendors.0833"), 0, 0, 0, TXT("poi_vendors.0834"))]),
    "kiosk": (TXT("poi_vendors.0835"), [
        (TXT("poi_vendors.0836"), 70, 8, 0, TXT("poi_vendors.0837")),
        (TXT("poi_vendors.0838"), 60, 0, 0, TXT("poi_vendors.0839")),
        (TXT("poi_vendors.0840"), 40, 4, 0, TXT("poi_vendors.0841")),
        (TXT("poi_vendors.0842"), 40, 0, 0, TXT("poi_vendors.0843")),
        (TXT("poi_vendors.0844"), 90, 8, 0, TXT("poi_vendors.0845"))]),
    "autoservice": (TXT("poi_vendors.0846"), [
        (TXT("poi_vendors.0847"), 60, 0, 0, TXT("poi_vendors.0848")),
        (TXT("poi_vendors.0849"), 1400, 0, 0, TXT("poi_vendors.0850")),
        (TXT("poi_vendors.0851"), 0, 0, 0, TXT("poi_vendors.0852")),
        (TXT("poi_vendors.0853"), 0, 0, 0, TXT("poi_vendors.0854"))]),
    "laundry": (TXT("poi_vendors.0855"), [
        (TXT("poi_vendors.0856"), 400, 4, 0, TXT("poi_vendors.0857")),
        (TXT("poi_vendors.0858"), 120, 3, 0, TXT("poi_vendors.0859")),
        (TXT("poi_vendors.0860"), 350, 2, 0, TXT("poi_vendors.0861"))]),
    "toys": (TXT("poi_vendors.0862"), [
        (TXT("poi_vendors.0863"), 150, 6, 0, TXT("poi_vendors.0864")),
        (TXT("poi_vendors.0865"), 700, 4, 0, TXT("poi_vendors.0866")),
        (TXT("poi_vendors.0867"), 20, 4, 0, TXT("poi_vendors.0868"))]),
    "vet": (TXT("poi_vendors.0869"), [
        (TXT("poi_vendors.0870"), 400, 4, 0, TXT("poi_vendors.0871")),
        (TXT("poi_vendors.0872"), 600, 5, 0, TXT("poi_vendors.0873")),
        (TXT("poi_vendors.0874"), 0, 3, 0, TXT("poi_vendors.0875"))]),
    "university": (TXT("poi_vendors.0876"), [
        (TXT("poi_vendors.0877"), 50, 0, 0, TXT("poi_vendors.0878")),
        (TXT("poi_vendors.0879"), 60, 8, 0, TXT("poi_vendors.0880")),
        (TXT("poi_vendors.0881"), 0, 3, 0, TXT("poi_vendors.0882")),
        (TXT("poi_vendors.0883"), 40, 0, 0, TXT("poi_vendors.0884"))]),
    "kindergarten": (TXT("poi_vendors.0885"), [
        (TXT("poi_vendors.0886"), 0, 5, 0, TXT("poi_vendors.0887")),
        (TXT("poi_vendors.0888"), 0, 0, 0, TXT("poi_vendors.0889")),
        (TXT("poi_vendors.0890"), 150, 4, 0, TXT("poi_vendors.0891"))]),
}

# name fragments (lower-case, Cyrillic and Latin) -> kind; first match wins, so specific brands come first
_MORE_NAMES = [
    ((TXT("poi_vendors.0892"), "vero", TXT("poi_vendors.0893"), "ramstore", TXT("poi_vendors.0894"), "tinex", TXT("poi_vendors.0895"), "kam market", "market", TXT("poi_vendors.0896"), TXT("poi_vendors.0897"), TXT("poi_vendors.0898"), TXT("poi_vendors.0899"), "lidl"), "supermarket"),
    ((TXT("poi_vendors.0900"), "barber", TXT("poi_vendors.0901"), TXT("poi_vendors.0902")), "barber"),
    ((TXT("poi_vendors.0903"), "frizer", "hair", TXT("poi_vendors.0904"), TXT("poi_vendors.0905"), "beauty", TXT("poi_vendors.0906")), "beauty"),
    ((TXT("poi_vendors.0907"), "burek", TXT("poi_vendors.0908"), TXT("poi_vendors.0909")), "burek"),
    ((TXT("poi_vendors.0910"), TXT("poi_vendors.0911"), "kebab", "kebap", TXT("poi_vendors.0912"), "ćevap", TXT("poi_vendors.0913")), "kebab"),
    ((TXT("poi_vendors.0914"), "pizza", "pizz", TXT("poi_vendors.0915")), "pizza"),
    ((TXT("poi_vendors.0916"), "pekar", "bakery", TXT("poi_vendors.0917"), TXT("poi_vendors.0918")), "bakery"),
    ((TXT("poi_vendors.0919"), TXT("poi_vendors.0920"), "slatk", TXT("poi_vendors.0921"), "gelato", TXT("poi_vendors.0922"), "cake", TXT("poi_vendors.0923"), "baklava", TXT("poi_vendors.0924")), "sweets"),
    ((TXT("poi_vendors.0925"), "apteka", "pharm", TXT("poi_vendors.0926"), "zdravje", TXT("poi_vendors.0927"), "ph "), "pharmacy"),
    ((TXT("poi_vendors.0928"), "dental", TXT("poi_vendors.0929")), "dentist"),
    ((TXT("poi_vendors.0930"), TXT("poi_vendors.0931"), "hospital", "clinic", TXT("poi_vendors.0932"), TXT("poi_vendors.0933"), TXT("poi_vendors.0934")), "hospital"),
    ((TXT("poi_vendors.0935"), "mobile", TXT("poi_vendors.0936"), "telekom", "a1 ", "vip ", "one ", "gsm", "iphone", "samsung"), "mobile"),
    (("neptun", TXT("poi_vendors.0937"), "anhoch", TXT("poi_vendors.0938"), TXT("poi_vendors.0939"), TXT("poi_vendors.0940"), "electro", "computer", TXT("poi_vendors.0941"), TXT("poi_vendors.0942")), "electronics"),
    ((TXT("poi_vendors.0943"), "knizar", "bookshop", TXT("poi_vendors.0944"), TXT("poi_vendors.0945"), TXT("poi_vendors.0946")), "books"),
    ((TXT("poi_vendors.0947"), "fitness", "gym", TXT("poi_vendors.0948"), "crossfit", TXT("poi_vendors.0949"), TXT("poi_vendors.0950")), "gym"),
    ((TXT("poi_vendors.0951"), TXT("poi_vendors.0952"), "flowers", "florist", "cvekj"), "florist"),
    ((TXT("poi_vendors.0953"), "optic", "optik", TXT("poi_vendors.0954")), "optics"),
    ((TXT("poi_vendors.0955"), "zlatar", "jewel", TXT("poi_vendors.0956")), "jewelry"),
    ((TXT("poi_vendors.0957"), "shoes", "patiki", TXT("poi_vendors.0958"), "shoe"), "shoes"),
    ((TXT("poi_vendors.0959"), "fashion", "boutique", TXT("poi_vendors.0960"), "zara", "h&m", "waikiki", "lc ", "kids", TXT("poi_vendors.0961")), "clothes"),
    ((TXT("poi_vendors.0962"), "mesar", "butcher", TXT("poi_vendors.0963"), TXT("poi_vendors.0964")), "butcher"),
    ((TXT("poi_vendors.0965"), TXT("poi_vendors.0966"), "voce", TXT("poi_vendors.0967")), "greengrocer"),
    ((TXT("poi_vendors.0968"), TXT("poi_vendors.0969"), "wine", TXT("poi_vendors.0970"), "alcohol", TXT("poi_vendors.0971"), TXT("poi_vendors.0972"), TXT("poi_vendors.0973")), "liquor"),
    ((TXT("poi_vendors.0974"), "tutun", "tobacco", TXT("poi_vendors.0975")), "tobacco"),
    (("kladilnica", TXT("poi_vendors.0976"), TXT("poi_vendors.0977"), "loto", TXT("poi_vendors.0978"), "sportsbet", TXT("poi_vendors.0979"), "bet365"), "betting"),
    ((TXT("poi_vendors.0980"), "exchange", "forex", TXT("poi_vendors.0981")), "exchange"),
    ((TXT("poi_vendors.0982"), TXT("poi_vendors.0983"), "wash", "laundry", TXT("poi_vendors.0984")), "laundry"),
    ((TXT("poi_vendors.0985"), "auto", TXT("poi_vendors.0986"), TXT("poi_vendors.0987"), "servis", "mechanic", TXT("poi_vendors.0988")), "autoservice"),
    ((TXT("poi_vendors.0989"), "toys", "toy", "lego"), "toys"),
    ((TXT("poi_vendors.0990"), "veterin", "pet shop", "ljubimc", TXT("poi_vendors.0991")), "vet"),
    (("kiosk", TXT("poi_vendors.0992"), TXT("poi_vendors.0993"), "kosk"), "kiosk"),
    ((TXT("poi_vendors.0994"), "kafana", TXT("poi_vendors.0995"), "tavern", "kafeana"), "kafana"),
    ((TXT("poi_vendors.0996"), "kindergarten", TXT("poi_vendors.0997")), "kindergarten"),
    ((TXT("poi_vendors.0998"), "fakultet", TXT("poi_vendors.0999"), "university", "institute", TXT("poi_vendors.1000")), "university"),
]
# OSM sub-tag values (data/osm/map_poi_kinds.json) -> kind
_OSM_KINDS = {
    "bakery": "bakery", "pastry": "bakery", "confectionery": "sweets", "ice_cream": "sweets", "butcher": "butcher", "greengrocer": "greengrocer",
    "supermarket": "supermarket", "convenience": "minimarket", "general": "minimarket", "kiosk": "kiosk", "mall": "supermarket", "department_store": "supermarket",
    "clothes": "clothes", "shoes": "shoes", "boutique": "clothes", "jewelry": "jewelry", "mobile_phone": "mobile", "electronics": "electronics", "computer": "electronics",
    "hairdresser": "barber", "barber": "barber", "beauty": "beauty", "cosmetics": "beauty", "books": "books", "stationery": "books", "florist": "florist",
    "optician": "optics", "alcohol": "liquor", "beverages": "liquor", "wine": "liquor", "tobacco": "tobacco", "bookmaker": "betting", "lottery": "betting",
    "car_repair": "autoservice", "car_parts": "autoservice", "tyres": "autoservice", "car": "autoservice", "laundry": "laundry", "dry_cleaning": "laundry",
    "toys": "toys", "pet": "vet", "veterinary": "vet", "pharmacy": "pharmacy", "chemist": "pharmacy", "hospital": "hospital", "clinic": "hospital", "doctors": "hospital",
    "dentist": "dentist", "bank": "bank", "atm": "atm", "bureau_de_change": "exchange", "fitness_centre": "gym", "university": "university", "college": "university",
    "kindergarten": "kindergarten", "cafe": "cafe", "bar": "bar", "pub": "bar", "nightclub": "bar", "restaurant": "kafana", "fast_food": "burek",
    "fast_food/kebab": "kebab", "fast_food/pizza": "pizza", "restaurant/pizza": "pizza", "restaurant/kebab": "kebab", "restaurant/regional": "kafana",
    "fast_food/burger": "kebab", "fast_food/sandwich": "bakery", "fast_food/bakery": "bakery",
}
# no name, no sub-tag: category defaults to a witty kind (the rest keep the plain MENU of poi.py)
_CAT_KINDS = {"cafe": "cafe", "food": "kebab", "money": "bank", "health": "pharmacy", "shop": "minimarket"}


# my kind -> existing vendor key (pools are merged); kinds not listed here become new vendors
_ALIAS = {"supermarket": "market", "bakery": "pekara", "sweets": "slatkarnica", "cafe": "kafe", "bar": "kafeana", "pharmacy": "apteka",
          "electronics": "tech", "florist": "cvekjarnica", "bank": "menuvacnica", "autoservice": "auto", "books": "knigi",
          "jewelry": "nakit", "greengrocer": "pazar", "mobile": "tech"}


def _merge():
    for k, (title, pool) in _MORE.items():
        key = _ALIAS.get(k, k)
        paid = [x for x in pool if x[1] > 0]
        free = [x for x in pool if x[1] == 0]
        if key in V:
            t, p0, f0 = V[key]
            have = {x[0] for x in p0 + f0}
            V[key] = (t, p0 + [x for x in paid if x[0] not in have], f0 + [x for x in free if x[0] not in have])
        else:
            V[key] = (title, paid, free)
    new = []
    for frags, k in _MORE_NAMES:
        key = _ALIAS.get(k, k)
        if key in dict(KEYS) and key in {a for a, _ in KEYS}:
            continue                                   # the existing keyword list already covers this vendor
        new.append((key, frags))
    KEYS[:0] = new                                     # new vendors first: their words are the more specific ones


_merge()

# category fallback: pool of plausible vendors, picked by the name's hash (the "estimate" when the name says nothing)
POOL = {
    "cafe": ("kafe", "kafe", "kafeana", "slatkarnica"),
    "food": ("kebab", "pizza", "burek", "pekara", "mehana"),
    "shop": ("market", "kiosk", "clothes", "tech", "market", "knigi", "nakit"),
    "market": ("pazar", "market", "pazar"),
    "night": ("kafeana", "kafeana", "kafe"),
    "money": ("menuvacnica",),
    "fuel": ("bencin",),
    "sport": ("gym",),
    "health": ("apteka",),
    "hotel": ("kafe", "mehana"),
}


_SUBS = None


def _sub(x, y):
    """OSM sub-tag of the place at (x, y) from data/osm/map_poi_kinds.json (written by tools/fetch_pois.py), '' if unknown."""
    global _SUBS
    if _SUBS is None:
        try:
            with open(os.path.join(os.environ.get("SK242_OSM_DIR") or os.path.join(_ROOT, "data", "osm"), "map_poi_kinds.json"), encoding="utf-8") as f:
                _SUBS = json.load(f)
        except (OSError, ValueError):
            _SUBS = {}
    return _SUBS.get(f"{x},{y}", "") if x is not None else ""


def vendor_for(cat, name, sub=""):
    low = (" " + (name or "").lower() + " ")
    for v, keys in KEYS:
        if any(k in low for k in keys):
            return v
    k = _OSM_KINDS.get(sub) or _OSM_KINDS.get(sub.split("/")[0]) if sub else None
    if k:
        return _ALIAS.get(k, k)
    pool = POOL.get(cat)
    if pool:
        return pool[zlib.crc32(low.encode("utf-8")) % len(pool)]
    return None


_CACHE_PATH = os.path.join(_ROOT, "data", "cache", "poi_menus.json")
_CACHE = None


def _cache():
    global _CACHE
    if _CACHE is None:
        try:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                d = json.load(f)
            _CACHE = d["m"] if d.get("v") == VERSION else {}
        except (OSError, ValueError, KeyError, TypeError):
            _CACHE = {}
    return _CACHE


def _save():
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"v": VERSION, "m": _CACHE}, f, ensure_ascii=False)
        os.replace(_CACHE_PATH + ".tmp", _CACHE_PATH)
    except OSError:
        pass


def menu_for(cat, name, fallback, x=None, y=None):
    """-> (title or None, menu).  fallback = the plain category menu from poi.MENU/DEFAULT.
    Generated once per place (seeded by its name) and cached in data/cache/poi_menus.json."""
    key = f"{cat}|{x}|{y}|{name}"
    c = _cache()
    if key in c:
        t, m = c[key]
        return t, [tuple(i) for i in m]
    v = vendor_for(cat, name, _sub(x, y))
    if v is None or v not in V:
        return None, fallback
    title, paid, free = V[v]
    rng = random.Random(zlib.crc32((name or v).encode("utf-8")) ^ zlib.crc32(f"{x}{y}".encode()))
    k = 3 if free else 4
    items = rng.sample(paid, min(k, len(paid)))
    items += [rng.choice(free)] if free else []
    if len(items) < 4:                                  # a short pool: top up from the leftovers
        rest = [i for i in paid + free if i not in items]
        items += rng.sample(rest, min(4 - len(items), len(rest)))
    menu = [(a, b, max(0, c_), d, e) for a, b, c_, d, e in items]
    c[key] = [title, menu]
    _save()
    return title, menu
