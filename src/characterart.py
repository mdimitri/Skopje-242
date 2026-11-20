"""Three-tier character shapes, portrait designs, materials and articulated poses."""
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np

import characters
import vehicles
import weaponart

ATLAS_SIZES = (0, 128, 256)


@dataclass(frozen=True)
class HeroLook:
    build: tuple                # height, shoulders, waist, hips, stride
    face: tuple                 # head width, height, nose size
    palette: str                # outer layer, accent, trousers, shoes, hair, skin
    hair: str
    outfit: str
    props: str = ''


_HERO_LOOKS = {
    'mile': HeroLook((1.00,.238,.213,.206,.82), (.157,.213,.071), '292529 d8ad4d 42434a 352925 322823 db946b', 'short', 'shirt', 'chain moustache'),
    'stojan': HeroLook((.99,.189,.162,.172,.96), (.144,.196,.060), '343f58 aa4149 375675 c5b194 3e2a20 dfa074', 'messy', 'vest', 'partyhat backpack snack'),
    'influenser': HeroLook((1.02,.198,.157,.167,1.04), (.141,.214,.043), '898381 555158 484244 d3d7db 874823 e4a172', 'quiff', 'jacket', 'shades backpack selfie'),
    'influenserka': HeroLook((.98,.178,.137,.217,.91), (.151,.208,.042), '9ea697 61524f 353039 dcc3b0 8e5633 dd9266', 'long', 'crop', 'shades phone lips'),
    'baba': HeroLook((.83,.175,.205,.214,.58), (.142,.193,.059), '494042 8a785f 5c4936 332c29 a19b8d c28865', 'scarf', 'coat_skirt', 'glasses cane marketbag'),
    'dedo': HeroLook((.92,.191,.178,.176,.64), (.140,.218,.074), '785339 c0a58b 4e494a 372c27 8b8270 d09369', 'flatcap', 'jacket', 'paper'),
    'pandur': HeroLook((1.04,.274,.237,.220,.82), (.172,.210,.062), '25446c 2b3449 263e61 28272b 342923 d58b5c', 'police', 'uniform', 'headphones badge notebook'),
    'doktor': HeroLook((1.02,.209,.173,.180,.92), (.143,.216,.044), 'e6e3e8 53776a 4b4442 312c2c 302723 e1a074', 'quiff', 'coat', 'shades tie stethoscope'),
    'mali': HeroLook((.68,.190,.163,.166,1.13), (.162,.211,.038), '306869 526896 3e4e6d c9c4bd 74452a e7a67a', 'messy', 'puffer'),
    'burek': HeroLook((1.00,.243,.207,.213,.77), (.161,.220,.066), '373339 e6d5bb 49453d 655443 423229 ca8963', 'baker', 'apron', 'stubble tray'),
    'boza': HeroLook((.96,.230,.217,.218,.73), (.153,.199,.064), '5c4c3e e5d0ae 524b44 533c2c a29381 d39163', 'baker', 'apron', 'moustache jug'),
    'bilder': HeroLook((1.11,.305,.199,.206,.82), (.150,.207,.050), 'e3dbd6 d4c5bc 38587d d6c5b5 392922 d8946c', 'short', 'tee', 'stubble shaker'),
    'shmizla': HeroLook((.98,.169,.132,.218,.93), (.145,.209,.035), 'd65b84 f38caa 476e8d c07461 e4bd76 e9a379', 'bunlong', 'crop', 'lips handbag'),
    'palavko': HeroLook((.71,.163,.143,.159,1.14), (.155,.209,.040), '3b669c 4875ab 8f7350 b8c0bc 81512d e5a87a', 'reversecap', 'shorts', 'cherries'),
    'srednoskolec': HeroLook((.91,.183,.153,.169,1.00), (.140,.197,.041), '858088 c0b9b5 333b4a c3bdb1 593a29 dda077', 'hood', 'jacket', 'backpack phone'),
    'vojnik': HeroLook((1.02,.236,.193,.201,.93), (.148,.208,.056), '6d7150 999063 686747 45362a 493b2c d4976a', 'beret', 'uniform', 'backpack flowers'),
    'navivac': HeroLook((1.00,.232,.198,.201,1.05), (.154,.199,.057), '343139 bc3b46 41404a bbb2aa 352824 dc9370', 'reversecap', 'jacket', 'scarf chain'),
    'administratorka': HeroLook((.93,.189,.170,.203,.82), (.145,.198,.044), '4f4143 e4cabc 534653 493738 52382c dda179', 'bun', 'cardigan', 'glasses pearls phone'),
    'nastavnica': HeroLook((.93,.191,.173,.206,.79), (.143,.205,.049), '544741 c0ab92 605148 4b382e 514032 ce956b', 'bun', 'skirt', 'glasses notebook'),
}

# Roster ID, playable, scale, shoulder, waist, hip, gait.
_CAST = (
    ('Baba', False, .87, .195, .21, .23, .63),
    ('Biznismen', False, 1.02, .225, .16, .175, .95),
    ('Navivach', False, 1.00, .235, .195, .20, 1.08),
    ('Buregdzija', False, .97, .245, .24, .23, .80),
    ('Dostavuvach', False, 1.00, .205, .16, .17, 1.10),
    ('kumplung', True, 1.01, .255, .245, .235, .78),
    ('maca', True, .99, .175, .135, .225, .87),
    ('tetkica', True, .91, .235, .24, .265, .78),
    ('radnik', True, 1.04, .245, .22, .205, .87),
    ('fitka', True, .99, .185, .145, .21, 1.15),
) + tuple((key, True, *look.build) for key, look in _HERO_LOOKS.items())

_HERO_IDS = {hero[0]: i for i, hero in enumerate(characters.LIKOVI, 100)}
DESIGNS = {(_HERO_IDS[key] if hero else vehicles.PED_IDS.index(key)): i
           for i, (key, hero, *_) in enumerate(_CAST)}


def scale(arch):
    return _CAST[DESIGNS[arch]][2]


def hero_arch(arch):
    return 100 + (arch - 100) % len(characters.LIKOVI)


def lod_frame(frame, tier):
    if tier == 1 and (20 <= frame <= 27 or 30 <= frame <= 37 or 40 <= frame <= 47):
        return frame & ~1
    return frame

# Base color, second layer, trousers, shoe, hair, complexion.
_PALETTES = (
    ('52445b','70546a','41384e','282431','96929a','d49b7b'),
    ('253b55','e5e6da','24354a','25212b','3a282a','dda283'),
    ('222632','bd3e49','33394a','dedad5','49302a','da9574'),
    ('e3d7c4','fcf0d6','524340','342a29','3a2b27','dca27a'),
    ('228582','f6af52','233b46','d3e0d9','282a30','a66d53'),
    ('715134','9a6c3d','333847','392b28','33251d','d99065'),
    ('cf3579','eb649c','cf3579','ac285f','e6ad49','edaa7a'),
    ('59476a','64758b','4d3e58','3e2e30','573529','dd9a68'),
    ('6e5034','376083','365572','42322a','5b4639','cb8764'),
    ('d94a82','ec769c','383245','e8d9d7','382a28','d8926b'),
) + tuple(tuple(look.palette.split()) for look in _HERO_LOOKS.values())


def rgb(code):
    return tuple(bytes.fromhex(code))


def atlas(size):
    """UV swatches: smooth, twill, knit, floral, denim, satin, hair, skin."""
    w, h = size // 4, size // 2
    y, x = np.mgrid[0:h, 0:w]
    u, v = x / w, y / h
    noise = np.random.default_rng(242).normal(0, 3, (h, w))
    turn = 2 * np.pi
    grain = np.sin(turn * (12*u + 8*v))
    seams = np.maximum(0, np.cos(turn * u * 4)) ** 40
    weave = np.cos(turn * 13*u) * np.cos(turn * 20*v)
    creases = np.cos(turn * (v * 3.5 + .25*np.sin(turn*u)))
    flower_x = (u * 8 + .45 * (y // max(1, h // 9) % 2)) % 1 - .5
    flower_y = (v * 9) % 1 - .5
    angle = np.arctan2(flower_y, flower_x)
    petal = np.hypot(flower_x, flower_y) < .18 + .064 * np.cos(angle*5)
    shade = [250 + noise, 232 + 11*grain - 23*seams + 5*creases + noise,
             211 + 27*weave + 12*grain + noise, 188 + 62*petal + 9*grain,
             216 + 10*grain + 18*creases - 24*seams + noise,
             232 + 15*creases + 8*np.sin(turn*u*4),
             225 + 22*np.cos(turn*(u*14 + .22*np.sin(turn*v))) + noise,
             247 + 6*creases + noise]
    image = np.empty((size, size, 4), np.uint8)
    image[:, :, 3] = 255
    for i, tile in enumerate(shade):
        colors = np.repeat(tile[:, :, None], 3, axis=2)
        if i == 3:
            colors[:, :, 1] -= 24*petal
            colors[:, :, 2] -= 45*petal
        xx, yy = (i % 4)*w, (i // 4)*h
        image[yy:yy+h, xx:xx+w, :3] = np.clip(colors, 0, 255)
    return image


def rotation(pitch=0., yaw=0., roll=0.):
    x, y, z = map(math.radians, (pitch, yaw, roll))
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    return np.array(((cy*cz, -cy*sz, sy), (cx*sz + sx*sy*cz, cx*cz - sx*sy*sz, -sx*cy),
                     (sx*sz - cx*sy*cz, sx*cz + cx*sy*sz, cx*cy)), np.float32)


def unit(vectors):
    return vectors / np.maximum(np.linalg.norm(vectors, axis=-1, keepdims=True), .00001)


def surface(profile, center, detail, tile, angles):
    """Closed elliptical ring mesh with an unwrapped UV seam."""
    sides = (6, 8, 12)[detail]
    height = (4, 6, 8)[detail]
    v = np.linspace(0, 1, height+1)
    u = np.linspace(0, 1, sides+1)
    shape = np.array(profile, np.float32)
    y, wx, wz = [np.interp(v, np.linspace(0, 1, len(shape)), shape[:, i]) for i in range(3)]
    xx = np.cos(u * math.tau)[None, :] * wx[:, None]
    zz = np.sin(u * math.tau)[None, :] * wz[:, None]
    yy = np.broadcast_to(y[:, None], xx.shape)
    center_mesh = np.stack((xx, yy, zz), axis=-1)
    du = np.stack((-np.sin(u*math.tau)[None, :]*wx[:, None], np.zeros_like(xx),
                   np.cos(u*math.tau)[None, :]*wz[:, None]), axis=-1)
    smooth = unit(np.cross(np.gradient(center_mesh, axis=0), du))
    ix = np.arange(height)[:, None] * (sides+1) + np.arange(sides)[None, :]
    below = ix + sides + 1
    faces = np.stack((ix, below, ix+1, ix+1, below, below+1), axis=-1).reshape(-1, 3)
    # A pole has one real triangle per segment.
    faces = faces[np.linalg.norm(np.cross(center_mesh.reshape(-1,3)[faces[:, 1]] - center_mesh.reshape(-1,3)[faces[:, 0]],
                                          center_mesh.reshape(-1,3)[faces[:, 2]] - center_mesh.reshape(-1,3)[faces[:, 0]]), axis=1) > 1e-8]
    xyz = center_mesh.reshape(-1, 3)[faces]
    normals = smooth.reshape(-1, 3)[faces]
    if detail < 2:
        face_normals = unit(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]))
        normals = np.broadcast_to(face_normals[:, None], xyz.shape)
    uv = np.stack(np.meshgrid((tile%4 + .045 + u*.91)/4, (tile//4 + .045 + (1-v)*.91)/2), axis=-1)
    turn = rotation(*angles)
    return ((xyz.reshape(-1, 3) @ turn.T + center).astype(np.float32),
            (normals.reshape(-1, 3) @ turn.T).astype(np.float32), uv.reshape(-1, 2)[faces].reshape(-1, 2))


@lru_cache(maxsize=72)
def street_part(form, tier, material):
    """Unit human parts for the street recipes, with the same UVs and tier resolutions as the portraits."""
    if form == 'torso':
        rings = ((-.5,0,0), (-.47,.38,.38), (-.27,.44,.43), (.16,.5,.50), (.37,.45,.47), (.48,.28,.37), (.5,0,0))
    elif form == 'limb':
        rings = ((-.5,0,0), (-.46,.32,.32), (-.30,.40,.41), (.12,.5,.5), (.34,.46,.45), (.46,.30,.33), (.5,0,0))
    elif form == 'hem':
        rings = ((-.5,0,0), (-.48,.5,.50), (-.27,.49,.49), (.04,.43,.43), (.30,.37,.37), (.47,.35,.36), (.5,0,0))
    else:
        rings = [(math.sin(a)*.5, math.cos(a)*.5, math.cos(a)*.5) for a in np.linspace(-math.pi/2, math.pi/2, 17)]
    return surface(rings, (0,0,0), tier - 1, material, (0,0,0))


@lru_cache(maxsize=3 * len(_CAST))
def sculpt(index, tier):
    key, _, _, shoulder, waist, hips, _ = _CAST[index]
    top, trim, leg, shoe, hair, skin = _PALETTES[index]
    look = _HERO_LOOKS.get(key)
    outfit = look.outfit if look else ''
    extras = look.props.split() if look else ()
    parts = []

    def add(bone, center, radii, color, texture=0, minimum=0, angle=(0,0,0), profile=None, small=False):
        if tier < minimum:
            return
        x, y, z = radii
        if profile is None:
            a = np.linspace(-math.pi/2, math.pi/2, 17)
            profile = [(y*math.sin(i), x*math.cos(i), z*math.cos(i)) for i in a]
        resolution = max(0, tier - (2 if small else 0))
        p, n, uv = surface(profile, center, resolution, texture if tier > 1 else int(texture > 0), angle)
        parts.append((bone, p, n, uv, rgb(color)))

    def garment(bottom, top_y, widths, depths, color, tile, bone='torso', center=(0,0,0), minimum=0):
        levels = np.linspace(bottom, top_y, len(widths))
        outline = [(bottom-.005, 0, 0), *zip(levels, widths, depths), (top_y+.005, 0, 0)]
        add(bone, center, (0,0,0), color, tile, minimum, profile=outline)

    skirt = index in (0, 6, 7) or outfit in ('skirt', 'coat_skirt')
    midriff = index == 9 or outfit == 'crop'
    long_coat = index == 0 or outfit == 'coat_skirt'
    if skirt:
        garment(-.38 if long_coat else -.23, .085, (hips*1.22, hips*1.09, hips, waist),
                (.145, .155, .153, .132), top if index == 6 else leg, 5 if index == 6 else 2, 'pelvis')
    else:
        add('pelvis', (0,.013,0), (hips,.117,.127), leg, 4)
    garment(.23 if midriff else .01, .535, (waist, waist*.95, shoulder, shoulder*.77),
            (.136, .147, .163 if index in (0, 3, 5, 7) else .133, .111),
            top, (2,1,1,1,1,2,5,3,1,5)[index] if not look else (2 if outfit in ('cardigan', 'coat_skirt') else 1))
    if midriff:
        add('torso', (0,.166,.008), (waist*.97,.13,.123), skin, 7)
        add('torso', (0,.255,.097), (.139,.022,.051), trim, 5, 1, small=True)
    add('torso', (0,.548,.011), (.073,.086,.071), skin, 7)

    for side in (-1, 1):
        arm = 'arm'+str(side)
        fore = 'fore'+str(side)
        hand = 'hand'+str(side)
        thigh = 'thigh'+str(side)
        calf = 'calf'+str(side)
        foot = 'foot'+str(side)
        sleeve = skin if index in (6, 9) or midriff else trim if index in (7, 8) or outfit == 'vest' else top
        bare_fore = index in (3, 6, 7, 8, 9) or outfit in ('shirt', 'crop', 'tee', 'shorts', 'apron') or key == 'pandur'
        wide = 1.42 if key == 'bilder' else 1.21 if index in (3, 5, 7, 8) or key == 'pandur' else .94
        add(arm, (0,-.137,0), (.077*wide,.188,.082*wide), sleeve, 7 if sleeve == skin else 1)
        if look and bare_fore and sleeve != skin:
            add(arm, (0,-.21,0), (.068*wide,.09,.073*wide), skin, 7)
        add(fore, (0,-.11,0), (.059*wide,.15,.066*wide), skin if bare_fore else sleeve, 7 if bare_fore else 1)
        if not bare_fore:
            add(fore, (0,-.205,0), (.061*wide,.039,.067*wide), trim if index in (1,4,5) else sleeve, 2, 1, small=True)
        add(hand, (0,-.04,.017), (.051,.077,.054), '2e2926' if index == 5 else skin, 7)
        bare_leg = index == 6
        width = .104 if not skirt else .09
        pants = skin if bare_leg else leg
        fabric = 7 if bare_leg else 4
        garment(-.443,.055,(width*.62,width*.84,width,width*.94),(.069,.088,.104,.09),pants,fabric,thigh)
        garment(-.41,.043,(.055,.064,.078,.067),(.06,.068,.08,.073),skin if outfit == 'shorts' else pants,
                7 if outfit == 'shorts' else fabric,calf)
        add(foot, (0,-.012,.064), (.086,.082,.15), shoe, 1)
        add(foot, (0,-.059,.074), (.088,.027,.145), 'd4c3aa' if index in (4, 9) else '29232c' if index != 6 else trim, 0, 1, small=True)
        if index in (2,4,9):
            for row in range(2):
                add(foot, (0,.049-row*.007,.064+row*.022), (.055,.009,.01), 'efdfcc', 0, 2, small=True)
        if index == 8:
            add(foot, (0,.067,.008), (.088,.106,.094), shoe, 1, 1)
        if index == 6:
            add(foot, (0,-.047,-.039), (.043,.067,.055), shoe, 5, 1, small=True)

    # Every face uses a different shape rather than a palette swap.
    if look:
        head_w, head_h, nose = look.face
    else:
        head_w = (.148,.139,.15,.161,.143,.185,.155,.164,.153,.147)[index]
        head_h = (.194,.205,.198,.206,.194,.225,.209,.201,.228,.202)[index]
        nose = (.055,.044,.047,.055,.044,.079,.034,.056,.06,.038)[index]
    add('head', (0,.143,0), (head_w,head_h,.138), skin, 7)
    add('head', (0,.061,.069), (head_w*.76,.104,.094), skin, 7, 2)
    add('head', (0,.146,.146), (nose,.054,.063 if index != 5 else .094), skin, 7)
    older = index in (0,3,5,7,8) or key in ('baba', 'dedo', 'boza')
    lip = 'ad2756' if index in (6, 9) or 'lips' in extras else '9a514a'
    add('head', (0,.076,.145), (.060 if index != 5 else .077,.021,.027), lip, 0, small=True)
    for side in (-1,1):
        x = side * head_w*.45
        eye_y = .197 + (.008 if index == 6 else 0)
        add('head', (side*head_w*.94,.131,0), (.036,.061,.04), skin, 7, 1, small=True)
        add('head', (x,eye_y,.125), (.038,.019,.022), 'efe4ce', 0, small=True)
        add('head', (x+side*.004,eye_y,.145), (.014,.017,.01), '553c32' if index != 6 else '476976', 0, small=True)
        add('head', (x+side*.006,eye_y+.005,.154), (.005,.006,.003), 'fff3dd', 0, 2, small=True)
        add('head', (x,.224,.129), (.047,.013 if index in (6,9) else .018,.016), hair, 6, angle=(0,0,side*(15 if older else 6)), small=True)
        add('head', (side*.084,.12,.115), (.065,.049,.04), skin, 7, 2)
        if index in (6,7,9):
            add('head', (side*head_w*.98,.086,.016), (.021,.029,.019), 'dca752', 0, 1, small=True)

    if not look and index not in (0,3,5,7,8):
        add('head', (0,.28,-.029), (head_w*1.07,.098,.135), hair, 6)
        if index in (1,6,9):
            add('head', (-.05,.28,.063), (head_w*.72,.058,.093), hair, 6, angle=(0,0,-26))

    if index in (0, 7):
        kerchief = '6e5064' if index == 0 else '4f607c'
        add('head', (0,.255,-.046), (head_w*1.14,.126,.147), kerchief, 3)
        for side in (-1,1):
            add('head', (side*.128,.135,-.028), (.069,.137,.119), kerchief, 3, angle=(0,0,-side*14))
        add('head', (0,-.041,.082), (.107,.044,.078), kerchief, 3, 1)
        add('head', (-.054,.269,.081), (.075,.042,.068), hair, 6, 1)
    if index == 0:
        for side in (-1,1):
            add('head', (side*.061,.193,.143), (.056,.03,.013), '593d46', 0, 1, small=True)
            add('head', (side*.061,.193,.155), (.043,.021,.009), 'dab490', 0, 1, small=True)
        add('hand1', (.065,-.19,.021), (.102,.159,.078), 'caae83', 1)
        add('hand1', (.065,-.313,.035), (.106,.051,.081), 'b78b63', 1, 2)
        add('hand1', (.06,-.079,.032), (.071,.042,.03), 'a27b60', 1, 2)
    elif index == 1:
        add('torso', (0,.333,.131), (.108,.172,.019), trim, 1)
        add('torso', (0,.31,.154), (.029,.148,.013), 'a63850', 5)
        for side in (-1,1):
            add('torso', (side*.104,.393,.143), (.044,.147,.027), '314961', 1, 1, angle=(0,0,side*21))
        add('hand1', (.042,-.185,.01), (.06,.153,.185), '794b3b', 2)
        add('hand1', (.102,-.119,.012), (.011,.04,.043), 'cf9856', 0, 2, small=True)
    elif index == 2:
        add('torso', (0,.501,.032), (.205,.055,.136), trim, 2)
        add('scarf', (.084,-.118,.019), (.071,.19,.042), trim, 2, angle=(0,0,-10))
        for j in range(2):
            add('scarf', (.07,-.226-j*.044,.049), (.062,.014,.021), '25242b', 0, 1, small=True)
        add('head', (0,.283,0), (.164,.085,.151), '242731', 2)
        add('head', (0,.257,.092), (.137,.018,.135), '272933', 0)
    elif index == 3:
        add('head', (0,.295,-.013), (.178,.081,.155), trim, 1)
        for j in (-1,0,1):
            add('head', (j*.066,.348,-.021), (.083,.073,.133), trim, 1, 1)
        add('torso', (0,.248,.132), (.184,.195,.03), trim, 1)
        add('pelvis', (0,-.117,.123), (.197,.196,.048), trim, 1)
        add('torso', (0,.20,.163), (.107,.054,.015), 'd4be9e', 1, 2)
        add('carry', (0,0,.091), (.224,.028,.211), '544751', 0)
        add('carry', (0,.021,.091), (.201,.035,.184), 'c68744', 5)
        for j in range(4):
            a = math.tau * j/4
            add('carry', (.113*math.cos(a),.047,.091+.105*math.sin(a)), (.065,.018,.055), 'e5a451', 5, 1, small=True)
    elif index == 4:
        add('torso', (0,.292,-.195), (.226,.221,.162), trim, 1)
        add('torso', (0,.325,-.301), (.202,.159,.051), 'd67a3c', 1, 1)
        for side in (-1,1):
            add('torso', (side*.132,.331,.126), (.027,.167,.029), '344e53', 1, angle=(0,0,side*9))
        add('head', (0,.282,.001), (.149,.079,.144), top, 1)
        add('head', (0,.257,.098), (.131,.017,.104), trim, 1)
    elif index == 5:
        for side in (-1,1):
            add('head', (side*.159,.211,-.047), (.066,.123,.094), hair, 6)
            add('head', (side*.061,.111,.172), (.094,.047,.043), hair, 6, angle=(0,0,-side*20))
        add('torso', (0,.489,.056), (.139,.048,.107), trim, 2, 1)
    elif index == 6:
        for side in (-1,1):
            add('hair'+str(side), (side*.139,-.064,-.036), (.103,.224,.126), hair, 6, angle=(6,0,side*13))
            add('hair'+str(side), (side*.18,-.101,.035), (.046,.167,.049), 'f4cc64', 6, 2, angle=(0,0,side*19))
            add('torso', (side*.099,.393,.119), (.023,.124,.019), trim, 5, 1, angle=(0,0,side*9), small=True)
        add('hand1', (.017,-.097,.046), (.025,.097,.027), '252330', 0, angle=(12,0,0), small=True)
        add('hand1', (.017,-.186,.07), (.053,.049,.049), '878394', 1, small=True)
        add('pelvis', (.124,-.083,.075), (.122,.035,.072), trim, 5, 2, angle=(0,0,20))
    elif index == 7:
        for side in (-1,1):
            add('torso', (side*.114,.274,.127), (.074,.198,.042), '76618a', 2, angle=(0,0,side*15))
        add('torso', (0,.409,.149), (.036,.032,.015), 'd1a055', 0, 1, small=True)
        add('hand1', (.054,-.168,.008), (.103,.132,.082), '714955', 2)
        add('hand1', (.054,-.112,.073), (.098,.053,.019), '95656d', 1, 1)
        add('hand1', (.056,-.143,.087), (.025,.02,.013), 'cc9a55', 0, 2, small=True)
    elif index == 8:
        add('head', (0,.279,-.016), (.193,.118,.169), 'd9a231', 0)
        add('head', (0,.251,.038), (.203,.024,.194), 'f2bd43', 0)
        add('head', (0,.348,-.01), (.036,.069,.13), 'ecc14c', 0, 1)
        add('head', (0,.044,.075), (.122,.077,.075), '8e6754', 6, 1)
        add('torso', (0,.215,.138), (.166,.171,.043), trim, 4)
        add('torso', (0,.24,.174), (.085,.053,.019), '486d87', 4, 1)
        for side in (-1,1):
            add('torso', (side*.131,.414,.123), (.045,.127,.025), trim, 4, angle=(0,0,side*11))
            add('torso', (side*.118,.317,.168), (.018,.02,.011), 'b38f55', 0, 1, small=True)
    elif index == 9:
        add('head', (0,.351,-.079), (.091,.071,.092), hair, 6)
        add('hair1', (.044,-.098,-.103), (.102,.191,.091), hair, 6, angle=(13,0,18))
        add('hair1', (.073,-.139,-.14), (.058,.13,.055), '563929', 6, 2, angle=(16,0,22))
        add('hand1', (.049,-.099,.014), (.043,.104,.042), '36303f', 1, small=True)
        add('hand1', (.049,-.015,.01), (.043,.026,.04), '5e5364', 0, 1, small=True)
        add('fore-1', (0,-.2,0), (.064,.025,.068), '272331', 0, 1, small=True)

    if look:
        _hero_details(add, garment, key, look.hair, outfit, extras, top, trim, hair, head_w)

    grouped = {}
    for bone in dict.fromkeys(part[0] for part in parts):
        chunks = [part for part in parts if part[0] == bone]
        grouped[bone] = tuple(np.concatenate(rows) for rows in zip(*[
            (p, n, uv, np.tile(color, (len(p),1))) for _, p, n, uv, color in chunks]))
    return grouped


def _hero_details(add, garment, key, style, outfit, extras, top, trim, hair, head_w):
    if style in ('baker', 'beret', 'flatcap', 'police', 'reversecap'):
        hat = {'baker': 'e6dbca', 'police': top, 'flatcap': '514638', 'beret': '535237', 'reversecap': trim}[style]
        add('head', (0,.289,-.028), (head_w*1.08,.09 if style == 'baker' else .069,.141), hat, 1)
        if style != 'baker':
            add('head', (0,.262,-.098 if style == 'reversecap' else .076), (.121,.017,.128), hat, 1)
    elif style in ('scarf', 'hood'):
        material = 3 if style == 'scarf' else 2
        add('head', (0,.254,-.049), (head_w*1.14,.135,.144), trim if style == 'scarf' else top, material)
        for side in (-1,1):
            add('head', (side*.128,.135,-.03), (.065,.129,.102), trim if style == 'scarf' else top, material)
    else:
        add('head', (0,.28,-.034), (head_w*1.06,.093,.136), hair, 6)
        if style in ('quiff', 'messy', 'bunlong'):
            add('head', (-.039,.31,.064), (head_w*.85,.063,.092), hair, 6, angle=(0,0,-26))
        if style in ('bun', 'bunlong'):
            add('head', (-.031,.363,-.058), (.10,.077,.093), hair, 6)
        if style in ('long', 'bunlong'):
            for side in (-1,1):
                add('hair'+str(side), (side*.134,-.096,-.036), (.077,.226,.115), hair, 6, angle=(4,0,side*13))

    if outfit in ('coat', 'apron'):
        color = top if outfit == 'coat' else trim
        garment(-.38,.03,(.205,.185,.172),(.133,.146,.125),color,1,'pelvis',minimum=0)
        add('torso', (0,.23,.141), (.137,.183,.025), trim, 1)
    elif outfit in ('cardigan', 'vest', 'jacket'):
        add('torso', (0,.297,.124), (.105,.185,.031), trim, 2)
        for side in (-1,1):
            add('torso', (side*.102,.365,.142), (.046,.119,.023), top, 1, 1, angle=(0,0,side*16))
    elif outfit == 'puffer':
        for y in (.15,.27,.39):
            add('torso', (0,y,.006), (.176,.092,.145), top, 2)
    elif outfit == 'uniform':
        add('pelvis', (0,.048,.03), (.224,.032,.132), '2f2d2b', 1)
        for side in (-1,1):
            add('torso', (side*.099,.320,.137), (.059,.052,.022), trim, 1)

    if 'backpack' in extras:
        add('torso', (0,.274,-.175), (.166,.212,.136), '4e4b3d' if key == 'vojnik' else '302d32', 1)
        for side in (-1,1):
            add('torso', (side*.113,.331,.126), (.022,.158,.024), '434139', 1)
    if 'scarf' in extras:
        add('torso', (0,.509,.048), (.190,.056,.134), trim, 2)
        add('scarf', (.065,-.115,.012), (.069,.160,.030), trim, 2)
        add('scarf', (.055,-.218,.030), (.065,.019,.026), 'e5cebb', 1)
    if 'partyhat' in extras:
        garment(.305,.515,(.068,.049,.015),(.067,.048,.015),'b8473b',5,'head',(-.037,0,-.04))
    if 'chain' in extras or 'pearls' in extras or 'stethoscope' in extras:
        for side in (-1,1):
            add('torso', (side*.055,.41,.148), (.018,.09,.015), 'd5ae58' if 'chain' in extras else 'ddd5c6' if 'pearls' in extras else '353439', 0,
                angle=(0,0,side*-24), small=True)
    if 'tie' in extras:
        add('torso', (0,.336,.169), (.021,.119,.011), '3d3936', 1)
    if 'badge' in extras:
        add('torso', (-.100,.392,.157), (.032,.036,.013), 'd7b35f', 0, small=True)
        add('head', (0,.304,.100), (.025,.027,.013), 'd7b35f', 0, small=True)
    if 'moustache' in extras or 'stubble' in extras:
        for side in (-1,1):
            add('head', (side*.041,.110 if 'moustache' in extras else .057,.150), (.064,.027,.027), hair, 6,
                angle=(0,0,side*-16), small=True)
    if 'glasses' in extras or 'shades' in extras or 'headphones' in extras:
        for side in (-1,1):
            if 'headphones' in extras:
                add('head', (side*.166,.156,-.016), (.036,.065,.065), '29272c', 0)
            else:
                add('head', (side*.065,.195,.144), (.059,.033,.022), '332936' if 'shades' in extras else '805b46', 0, small=True)
                if 'glasses' in extras:
                    add('head', (side*.065,.195,.159), (.046,.024,.012), 'cba181', 0, small=True)

    props = {
        'snack': ((.064,.064,.044), 'd29b57'), 'phone': ((.045,.079,.020), '5b4c59'),
        'paper': ((.096,.135,.028), 'd9c9aa'), 'notebook': ((.095,.110,.035), '4b4d61'),
        'marketbag': ((.086,.157,.071), 'd9d0bb'), 'jug': ((.078,.116,.077), 'a7653d'),
        'shaker': ((.049,.105,.051), '393842'), 'handbag': ((.105,.115,.067), '806046'),
        'cherries': ((.048,.041,.045), 'a33141'), 'flowers': ((.060,.066,.050), 'cbbb75'),
    }
    for prop in extras:
        if prop in props:
            radii, color = props[prop]
            add('hand1', (.029,-.139,.031), radii, color, 1)
    if 'cane' in extras:
        add('hand1', (.052,-.349,.067), (.021,.30,.022), '96673d', 1)
    if 'selfie' in extras:
        add('hand1', (.035,-.207,.043), (.016,.180,.016), '31333a', 0, small=True)
        add('hand1', (.035,-.370,.043), (.070,.042,.023), '353741', 0, small=True)
    if 'tray' in extras:
        add('carry', (0,.007,.088), (.205,.023,.187), '57505a')
        add('carry', (0,.029,.088), (.186,.027,.169), 'c68a4c', 5)


def _arm_basis(down):
    side = unit(np.cross((0., 0., 1.), down))
    if np.linalg.norm(side) < .01:
        side = unit(np.cross((1., 0., 0.), down))
    return np.column_stack((side, -down, np.cross(down, side)))


def _reach(shoulder, target):
    """Solve the two arm segments with an elbow that bends down toward the body."""
    upper, lower = .295, .27
    toward = target - shoulder
    distance = np.clip(np.linalg.norm(toward), .05, upper + lower - .001)
    toward = unit(toward)
    down = np.array((0., -1., 0.))
    bend = unit(down - toward * (down @ toward))
    along = (upper**2 - lower**2 + distance**2) / (2 * distance)
    elbow = shoulder + toward * along + bend * math.sqrt(max(0., upper**2 - along**2))
    wrist = shoulder + toward * distance
    return elbow, _arm_basis(unit(elbow - shoulder)), _arm_basis(unit(wrist - elbow))


def _pose(index, tier, frame):
    key, _, scale, shoulder, _, hips, gait = _CAST[index]
    walk = 20 <= frame <= 27 or frame in (0, 1, 6, 7)
    run = 30 <= frame <= 37 or 8 <= frame <= 11
    air, seated = frame == 16, frame == 13
    punch, kick = frame == 4, frame == 5
    wave = travel = 0.
    if walk or run:
        phase = math.tau * ((frame % 10) / 8 if frame >= 20 else
                           {0: 0., 1: .5, 6: .25, 7: .75, 8: 0., 9: .5, 10: .25, 11: .75}[frame])
        wave, travel = math.cos(phase), math.sin(phase)
    swing = weaponart.swing_az((frame - 60 + .5) / 8) if 60 <= frame <= 67 else None
    lean = (5. if index in (0, 7) or key in ('baba', 'dedo') else 0.) + ((14 if run else 3) * gait if walk or run else 0.)
    lean += 12 if air or punch else -8 if kick else 0
    twist = (8 if run else 5) * wave if tier == 3 else 0.
    if swing is not None:
        twist = math.degrees(.5 * max(-1.6, min(1.6, swing)))
    elif punch:
        twist = 20. if tier == 3 else 10.
    transforms = {}

    def bone(name, parent, offset, pitch=0., yaw=0., roll=0.):
        turn = rotation(pitch, yaw, roll)
        shift = np.array(offset, np.float32)
        if parent:
            parent_turn, parent_shift = transforms[parent]
            shift = parent_turn @ shift + parent_shift
            turn = parent_turn @ turn
        transforms[name] = (turn, shift)

    bone('pelvis', None, (0, .88 if seated else .961, .08 if punch else 0), lean*.19, -twist*.24)
    bone('torso', 'pelvis', (0,0,0), 21 if seated else lean*.8, twist)
    bone('head', 'torso', (0,.599,.035), -lean*.46, -twist*.45)
    bone('scarf', 'torso', (0,.484,.145), -10*wave if tier == 3 else 0.)
    for side in (-1, 1):
        tag = str(side)
        stride = (48 if run else 31)*gait*wave*side
        knee = (61 if run else 38)*max(0., -travel*side)**1.25 * (1. if tier > 1 else .58)
        upper = -stride * .81
        elbow = -(56 if run else 10) - (23 if run else 18)*max(0., wave*side)
        if side == 1 and index in (0,1,6,7,9):
            upper *= .64
            elbow -= 10 if index in (6,9) else 0
        if (index == 3 or key == 'burek') and (walk or run or frame == 12):
            upper, elbow = -29 + 4*wave*side, -63
        if air:
            stride, knee, upper, elbow = -32 - 10*side, 57 + 8*side, -89, -38
        elif seated:
            stride, knee = -51 + 12*side, 63 - 14*side
        elif frame == 3:
            upper, elbow = -113, -55
        elif punch:
            stride, knee = (-22, 22) if side == -1 else (13, 12)
            upper, elbow = (-86, -5) if side == -1 else (-25, -65)
        elif kick and side == -1:
            stride, knee, upper, elbow = -82, 8, -23, -59
        bone('thigh'+tag, 'pelvis', (side*hips*.54,-.047,0), stride, 0., side*2.5)
        bone('calf'+tag, 'thigh'+tag, (0,-.414,0), knee)
        bone('foot'+tag, 'calf'+tag, (0,-.413,0), -.36*(stride+knee) if tier == 3 else 0., 0., -side*2)
        bone('arm'+tag, 'torso', (side*shoulder*.94,.469,-.003), upper, 0., side*(24 if frame == 3 else 12))
        bone('fore'+tag, 'arm'+tag, (0,-.295,0), elbow if tier > 1 else .75*elbow, 0., -side*4)
        if seated or swing is not None:
            target = ((.70, .96, -side*.27) if seated else weaponart.swing_grip(swing))
            x, y, z = np.array(target) / (.88 * scale)
            reach = np.array((-z + (.045*side if not seated else 0.), y, x))
            at = transforms['arm'+tag][1]
            joint, arm, fore = _reach(at, reach)
            transforms['arm'+tag] = arm, at
            transforms['fore'+tag] = fore, joint
        bone('hand'+tag, 'fore'+tag, (0,-.231,0))
        bone('hair'+tag, 'head', (0,.224,-.04), 5*wave if tier == 3 else 0.)
    bone('carry', 'torso', (0,.167,.333) if walk or run or frame == 12 else (0,.22,-.28), -lean*.5)
    return transforms


_KEY_LIGHT = unit(np.array((-.54,.72,.62), np.float32))
_FILL_LIGHT = unit(np.array((.62,.32,-.62), np.float32))
_SKIN = np.array(((236,190,160), (200,150,110), (150,105,80), (240,205,180)))


def mesh(arch, tone, frame, skin, tier):
    """CPU-only mesh and right-hand socket for either a worker or the window thread."""
    index = DESIGNS[arch]
    crawl = 40 <= frame <= 47
    bones = _pose(index, tier, frame - 20 if crawl else frame)
    points, uvs, colors, soles = [], [], [], []
    top = np.array(rgb(_PALETTES[index][0]))
    complexion = np.array(rgb(_PALETTES[index][-1]))
    for name, (vertices, normals, uv, base) in sculpt(index, tier - 1).items():
        turn, shift = bones[name]
        p = vertices @ turn.T + shift
        points.append(p)
        if name.startswith('foot'):
            soles.append(p[:, 1].min())
        ns = normals @ turn.T
        shade = .65 + .36*np.maximum(0., ns @ _KEY_LIGHT) + .13*np.maximum(0., ns @ _FILL_LIGHT)
        if arch < 100 and (tone or skin):
            base = base.copy()
            base[(base == complexion).all(axis=1)] += (_SKIN[skin % 4] - _SKIN[0]) // 2
            base[(base == top).all(axis=1)] += ((0,0,0), (-8,9,12), (13,-5,-10))[tone % 3]
        colors.append(np.clip(base * shade[:, None] + 8, 0, 255))
        uvs.append(uv)

    # The engine faces +X, while the sculpt is built facing +Z. Feet remain at the simulation's origin.
    scalar = .88 * scale(arch)
    ground = min(soles) if frame not in (13, 16) and not 60 <= frame <= 67 else 0.

    def game_space(p):
        p = p[:, (2, 1, 0)].copy()
        p[:, 2] *= -1
        p[:, 1] -= ground
        p *= scalar
        if frame == 2:
            p[:, 0], p[:, 1] = -p[:, 1].copy(), p[:, 0].copy() + .18
        elif crawl:
            x, y = p[:, 0].copy(), p[:, 1].copy()
            c = np.clip(x, -.15, .3)
            p[:, 0] = y*.55 - .1 + (x-c)*.7
            p[:, 1] = (.3 - c - (x-c)*np.where(x < c, .12, .35))*.8 + .22
        return p

    grip = None
    if arch >= 100:
        r, wrist = bones['hand-1']
        _, elbow = bones['fore-1']
        hand, start = game_space(np.array((wrist + r @ (0, -.04, .017), elbow)))
        grip = tuple(float(v) for v in hand), math.atan2(hand[0] - start[0], start[1] - hand[1])
    pos = game_space(np.concatenate(points)).astype(np.float32, copy=False)
    rgba = np.full((len(pos), 4), 255, np.uint8)
    rgba[:, :3] = np.concatenate(colors)
    return (pos, np.concatenate(uvs).astype(np.float32, copy=False), rgba), grip


