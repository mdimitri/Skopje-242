"""Stray dog art (round 23): a small scruffy low-poly dog out of boxes, in four coats and a handful of poses.

boxes(coat, frame) -> [(cx, base y, cz, sx, sy, sz, (r, g, b))] in body space: x forward, y up, z to the side.
Frames: 0-3 walk, 4-7 run (gallop), 8/9 sit (tail left / right), 10 asleep, 11 stand, 12 sniffing, 13 stand with the tail the other way."""
import math

# fur, patch (back / face), ear, socks + chest
COATS = [((176, 132, 84), (122, 84, 50), (118, 80, 46), (232, 222, 202)),
         ((52, 46, 44), (150, 98, 56), (34, 30, 30), (200, 170, 130)),
         ((220, 210, 192), (166, 124, 84), (170, 128, 90), (240, 236, 226)),
         ((128, 120, 110), (80, 72, 66), (70, 62, 56), (206, 200, 190))]
NOSE, EYE = (24, 20, 22), (18, 14, 14)
WALK, RUN, SIT, SLEEP, STAND, SNIFF = range(0, 4), range(4, 8), (8, 9), (10,), (11, 13), (12,)
FRAMES = 14


def _leg(out, x, z, swing, lift, h, fur, sock):
    out.append((x + swing, lift, z, 0.09, h - lift, 0.09, fur))
    out.append((x + swing, lift, z, 0.1, 0.07, 0.1, sock))           # white paw


def boxes(coat, frame):
    fur, patch, ear, sock = COATS[coat % len(COATS)]
    b = []
    if frame in SLEEP:                                                  # curled up, nose on the paws
        b += [(-0.02, 0.0, 0.0, 0.50, 0.19, 0.30, fur), (-0.02, 0.17, 0.0, 0.30, 0.03, 0.20, patch),
              (0.30, 0.0, 0.08, 0.20, 0.16, 0.17, fur), (0.40, 0.0, 0.08, 0.10, 0.08, 0.10, sock),
              (0.45, 0.04, 0.08, 0.04, 0.04, 0.05, NOSE), (0.28, 0.12, 0.17, 0.08, 0.10, 0.04, ear),
              (0.28, 0.12, -0.01, 0.08, 0.10, 0.04, ear), (-0.27, 0.0, -0.13, 0.20, 0.07, 0.07, fur)]
        return b
    sit = frame in SIT
    sniff = frame in SNIFF
    gal = frame in RUN
    ph = (frame % 4) * math.pi / 2 if frame < 8 else 0.0
    wag = 0.05 * (1 if frame in (8, 11) else -1) if frame in (8, 9, 11, 13) else 0.04 * math.sin(frame * 2.1)
    bob = 0.03 * abs(math.sin(ph)) if gal else 0.0
    if sit:
        b += [(-0.12, 0.0, 0.0, 0.34, 0.30, 0.24, fur), (0.18, 0.04, 0.0, 0.20, 0.42, 0.20, fur),    # haunches, upright chest
              (0.18, 0.04, 0.0, 0.205, 0.20, 0.205, sock), (0.26, 0.0, 0.07, 0.07, 0.30, 0.07, fur), (0.26, 0.0, -0.07, 0.07, 0.30, 0.07, fur),
              (0.27, 0.0, 0.07, 0.085, 0.06, 0.085, sock), (0.27, 0.0, -0.07, 0.085, 0.06, 0.085, sock),
              (-0.30, 0.0, wag, 0.16, 0.06, 0.07, fur), (-0.40, 0.0, wag * 2, 0.06, 0.06, 0.07, patch),
              (-0.10, 0.28, 0.0, 0.22, 0.03, 0.18, patch)]
        hx, hy = 0.26, 0.46
    else:
        y0 = 0.22 + bob
        hv = 0.21
        sw = 0.10 if gal else 0.07
        fl = 0.05 if gal else 0.035
        pairs = ((0.22, 0.075, ph if not gal else 0.0), (0.22, -0.075, ph + math.pi if not gal else 0.0),
                 (-0.22, 0.075, ph + math.pi if not gal else math.pi * 0.6), (-0.22, -0.075, ph if not gal else math.pi * 0.6))
        if frame in STAND_STILL:
            pairs = tuple((x, z, 0.0) for x, z, _ in pairs)
            sw = fl = 0.0
        for x, z, p in pairs:
            _leg(b, x, z, sw * math.sin(p), fl * max(0.0, math.cos(p)) * 2.0, hv + bob * 0, fur, sock)
        b += [(-0.02, y0, 0.0, 0.60, 0.21, 0.23, fur), (0.18, y0 - 0.02, 0.0, 0.25, 0.27, 0.25, fur),      # body, deeper chest
              (0.20, y0 - 0.02, 0.0, 0.245, 0.10, 0.225, sock),                                       # white blaze on the chest
              (-0.02, y0 + 0.17, 0.0, 0.34, 0.025, 0.15, patch), (-0.17, y0 + 0.17, 0.02, 0.10, 0.06, 0.07, fur),      # patch + a tuft on the back
              (0.10, y0 + 0.17, -0.03, 0.08, 0.05, 0.06, fur)]
        tail_up = 0.10 if gal else 0.14
        b += [(-0.33, y0 + 0.08, wag * 0.5, 0.09, tail_up, 0.05, fur), (-0.37, y0 + 0.08 + tail_up, wag * 1.5, 0.07, 0.12, 0.05, fur),
              (-0.37, y0 + 0.08 + tail_up + 0.10, wag * 2.0, 0.06, 0.05, 0.06, sock)]
        hx, hy = (0.40 if gal else 0.34), y0 + (0.12 if not sniff else -0.02)
        if sniff:
            hx = 0.42
        b += [(hx - 0.12, y0 + 0.07, 0.0, 0.14, 0.17, 0.12, fur)]                                    # neck
    # head: big for the body, which is what makes it cute
    b += [(hx + 0.10, hy, 0.0, 0.24, 0.22, 0.23, fur), (hx + 0.24, hy + 0.01, 0.0, 0.13, 0.095, 0.10, sock if frame in SIT else patch),
          (hx + 0.31, hy + 0.05, 0.0, 0.035, 0.04, 0.05, NOSE),
          (hx + 0.23, hy + 0.13, 0.085, 0.04, 0.05, 0.04, EYE), (hx + 0.23, hy + 0.13, -0.085, 0.04, 0.05, 0.04, EYE),
          (hx + 0.10, hy + 0.0, 0.115, 0.09, 0.17, 0.04, ear), (hx + 0.10, hy + 0.0, -0.115, 0.09, 0.17, 0.04, ear),     # floppy ears
          (hx + 0.07, hy + 0.19, 0.0, 0.09, 0.03, 0.12, patch)]
    return b


STAND_STILL = (11, 12, 13)
