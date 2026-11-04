"""Weapon shapes as boxes, shared by the 3D renderer (pickups on the ground, the weapon in the avatar's hand) and the HUD icon.
Each box is (x, y, w, h, colour): x along the barrel (grip at 0), y up from the grip line, side view; depth is `d` in 3D."""
STEEL, DARK, WOOD, OLIVE, GRIP = (92, 94, 100), (38, 40, 46), (140, 92, 48), (84, 98, 52), (28, 28, 32)

BOXES = {
    "pistol": [(-0.02, 0.0, 0.26, 0.06, STEEL), (-0.02, 0.06, 0.26, 0.015, DARK), (-0.02, -0.12, 0.06, 0.12, GRIP), (0.0, -0.02, 0.07, 0.02, DARK)],
    "uzi": [(-0.04, -0.02, 0.32, 0.09, DARK), (0.28, 0.0, 0.1, 0.03, STEEL), (-0.02, -0.18, 0.045, 0.16, STEEL), (-0.08, -0.12, 0.05, 0.1, GRIP),
            (-0.16, 0.0, 0.12, 0.03, STEEL)],
    "shotgun": [(0.0, 0.0, 0.8, 0.04, STEEL), (0.0, -0.045, 0.8, 0.03, DARK), (0.22, -0.07, 0.2, 0.045, WOOD), (-0.4, -0.06, 0.4, 0.1, WOOD),
                (-0.1, -0.05, 0.1, 0.07, DARK)],
    "kalash": [(0.0, 0.0, 0.5, 0.06, DARK), (0.5, 0.01, 0.35, 0.025, STEEL), (-0.38, -0.03, 0.38, 0.09, WOOD), (0.12, -0.2, 0.05, 0.2, STEEL),
               (0.17, -0.2, 0.06, 0.04, STEEL), (-0.02, -0.1, 0.05, 0.1, GRIP), (0.1, 0.06, 0.4, 0.02, WOOD)],
    "bat": [(-0.1, 0.0, 0.2, 0.045, GRIP), (0.1, -0.01, 0.8, 0.075, WOOD)],
    "knuckles": [(-0.02, 0.0, 0.1, 0.05, STEEL), (-0.02, -0.05, 0.1, 0.015, STEEL), (0.0, 0.05, 0.015, 0.015, DARK), (0.03, 0.05, 0.015, 0.015, DARK),
                 (0.06, 0.05, 0.015, 0.015, DARK)],
    "chain": [(-0.1, 0.0, 0.2, 0.045, GRIP)] + [(0.1 + 0.09 * i, -0.012 * (i % 2), 0.075, 0.03, STEEL) for i in range(9)],
    "zolja": [(-0.45, -0.05, 1.1, 0.13, OLIVE), (-0.55, -0.07, 0.12, 0.17, DARK), (0.65, -0.07, 0.1, 0.17, DARK), (-0.1, -0.12, 0.05, 0.08, GRIP),
              (0.35, -0.12, 0.05, 0.08, GRIP)],
}
DEPTH = {"pistol": 0.05, "uzi": 0.07, "shotgun": 0.06, "kalash": 0.07, "bat": 0.07, "knuckles": 0.09, "chain": 0.04, "zolja": 0.13}
