"""Bird art: low-poly ducks, pigeons and crows out of boxes.  boxes(kind, frame) -> [(cx, base y, cz, sx, sy, sz, (r, g, b))], x forward.
Frames: 0 stand, 1/2 walk, 3 peck, 4 wings up, 5 wings down, 6 swim.  Kinds: 0 mallard (drake), 1 duck (hen), 2 pigeon, 3 pigeon (white-necked grey), 4 crow."""
PAL = {0: ((92, 70, 52), (30, 110, 70), (222, 160, 40), (230, 230, 226)), 1: ((140, 108, 74), (120, 90, 60), (222, 150, 40), (200, 180, 150)),
       2: ((126, 130, 142), (60, 120, 110), (200, 90, 100), (230, 232, 236)), 3: ((160, 160, 166), (120, 90, 150), (200, 90, 100), (240, 240, 242)),
       4: ((38, 38, 42), (26, 26, 30), (40, 38, 38), (90, 90, 96))}
SIZE = {0: 1.0, 1: 1.0, 2: 0.55, 3: 0.55, 4: 0.8}
KINDS = 5
FRAMES = 7


def boxes(kind, frame):
    body, head, beak, wing = PAL[kind]
    duck, crow = kind < 2, kind == 4
    L = 0.52 if duck else 0.4 if crow else 0.3                       # body length
    H = 0.2 if duck else 0.16
    legs = 0.0 if frame == 6 else (0.07 if duck else 0.12 if not crow else 0.15)
    sw = 0.05 * (1 if frame == 1 else -1 if frame == 2 else 0)
    b = []
    if frame < 4 or frame == 6:
        for z in (0.04, -0.04):
            b.append((sw * (1 if z > 0 else -1), 0.0, z, 0.03, legs, 0.03, beak))
    y0 = legs if frame != 6 else -0.03
    tilt = 0.0
    b.append((0.0, y0, 0.0, L, H, H * 0.95, body))
    b.append((-L * 0.5, y0 + 0.03, 0.0, 0.14, 0.05, 0.1, wing if kind in (3,) else body))          # tail
    if frame >= 4:
        up = 0.18 if frame == 4 else -0.06
        for z in (1, -1):
            b.append((0.0, y0 + H * 0.5 + up * 0.4, z * (H * 0.5 + 0.17), L * 0.8, 0.02, 0.34, wing if kind != 4 else body))
    else:
        b.append((0.0, y0 + H * 0.55, 0.0, L * 0.7, 0.03, H * 1.02, wing if duck else body))
    hy = y0 + H + (0.02 if frame != 3 else -0.1)
    hx = L * 0.5 + (0.0 if frame != 3 else 0.1)
    s = 0.1 if duck else 0.09
    b.append((hx, hy, 0.0, s, s, s, head))
    if duck and kind == 0:
        b.append((hx - 0.03, hy - 0.06, 0.0, 0.06, 0.06, 0.08, (235, 235, 232)))          # white collar
    bl = 0.12 if duck else 0.1 if crow else 0.05
    b.append((hx + s * 0.9, hy + 0.02, 0.0, bl, 0.03, 0.05 if duck else 0.03, beak))
    return b
