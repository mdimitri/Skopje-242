"""Roadside signal heads and sign faces for the road candidate preview."""
import math

import numpy as np

POST = (116, 124, 126)
DARK = (42, 46, 48)
WHITE = (244, 242, 228)
BLUE = (44, 98, 177)
RED = (206, 49, 45)


def face(mesh, point, heading, depth, vertices, color):
    side = np.array([heading[1], -heading[0]])
    center = point + heading * depth
    points = [(center[0] + side[0] * x, y, center[1] + side[1] * x) for x, y in vertices]
    for i in range(1, len(points) - 1):
        mesh.tri(points[0], points[i], points[i + 1], color, lit=False)


def disc(mesh, point, heading, depth, x, y, r, color):
    vertices = [(x + r * math.cos(i * math.tau / 16), y + r * math.sin(i * math.tau / 16)) for i in range(16)]
    face(mesh, point, heading, depth, vertices, color)


def person(mesh, point, heading, depth, y, color, walking=False):
    disc(mesh, point, heading, depth, 0, y + 0.075, 0.025, color)
    face(mesh, point, heading, depth, [(-0.022, y + 0.04), (0.022, y + 0.04),
                                      (0.026, y - 0.025), (-0.024, y - 0.025)], color)
    for side in (-1, 1):
        end = side * (0.064 if walking else 0.025)
        face(mesh, point, heading, depth, [(side * 0.006, y - 0.012), (side * 0.024, y - 0.014),
                                          (end + 0.01, y - 0.089), (end - 0.01, y - 0.089)], color)


GANTRY_CLEARANCE = 5.1
HEAD_HEIGHT = 0.87


def vehicle_head(mesh, point, heading, bottom, live=False):
    x, z = point
    yaw = math.atan2(heading[1], heading[0])
    mesh.box(x, bottom, z, 0.23, HEAD_HEIGHT, 0.36, DARK, yaw=yaw)
    for offset, color in ((0.69, (79, 48, 43) if live else (247, 77, 59)), (0.44, (99, 79, 48)), (0.19, (50, 79, 58))):
        disc(mesh, point, heading, 0.12, 0, bottom + offset, 0.107, color)


def draw_gantry(mesh, device, live=False):
    supports = np.array(device["supports"])
    left, right = supports
    span = right - left
    middle = (left + right) / 2
    across = math.atan2(span[1], span[0])
    clearance = device["clearance_m"]
    beam_bottom = clearance + HEAD_HEIGHT + 0.16
    for x, z in supports:
        mesh.box(x, -0.065, z, 0.31, beam_bottom + 0.22 + 0.065, 0.31, POST, yaw=across)
        mesh.box(x, -0.065, z, 0.46, 0.27, 0.46, POST, yaw=across)
    mesh.box(middle[0], beam_bottom, middle[1], float(np.linalg.norm(span)) + 0.31, 0.27, 0.29, POST, yaw=across)
    heading = np.array(device["facing"])
    yaw = math.atan2(heading[1], heading[0])
    for head in device["heads"]:
        point = np.array(head["position"])
        mesh.box(point[0], clearance + HEAD_HEIGHT, point[1], 0.11, 0.17, 0.11, DARK, yaw=yaw)
        vehicle_head(mesh, point, heading, clearance, live)


def draw_device(mesh, kind, position, direction, live=False):
    point = np.asarray(position)
    heading = np.asarray(direction)
    x, z = point
    yaw = math.atan2(heading[1], heading[0])
    height = 3.25 if kind == "vehicle_signal" else 2.35
    mesh.cyl(x, -0.065, height, z, 0.065, POST)
    if kind == "vehicle_signal":
        vehicle_head(mesh, point, heading, 2.78, live)
    elif kind == "pedestrian_signal":
        mesh.box(x, 2.06, z, 0.2, 0.53, 0.31, DARK, yaw=yaw)
        person(mesh, point, heading, 0.105, 2.45, (79, 48, 43) if live else (255, 94, 74))
        person(mesh, point, heading, 0.105, 2.20, (52, 86, 61), walking=True)
    elif kind in {"give_way", "signal_ahead"}:
        sign = -1 if kind == "give_way" else 1
        for depth, size, color in ((0.018, 1, RED), (0.020, 0.77, WHITE)):
            face(mesh, point, heading, depth, [(-0.42 * size, 2.45 - sign * 0.24 * size),
                                              (0.42 * size, 2.45 - sign * 0.24 * size),
                                              (0, 2.45 + sign * 0.46 * size)], color)
        if kind == "signal_ahead":
            face(mesh, point, heading, 0.023, [(-0.075, 2.28), (0.075, 2.28),
                                              (0.075, 2.64), (-0.075, 2.64)], DARK)
            for yy, cc in ((2.57, RED), (2.46, (235, 175, 54)), (2.35, (66, 150, 88))):
                disc(mesh, point, heading, 0.025, 0, yy, 0.038, cc)
    elif kind == "cycleway":
        disc(mesh, point, heading, 0.019, 0, 2.35, 0.32, BLUE)
        for x in (-0.15, 0.15):
            disc(mesh, point, heading, 0.022, x, 2.27, 0.075, WHITE)
            disc(mesh, point, heading, 0.024, x, 2.27, 0.048, BLUE)
        face(mesh, point, heading, 0.026,
             [(-0.15, 2.27), (-0.04, 2.41), (0.15, 2.27), (0.11, 2.25),
              (-0.04, 2.36), (-0.11, 2.25)], WHITE)
    elif kind == "keep_right":
        disc(mesh, point, heading, 0.019, 0, 2.16, 0.3, BLUE)
        face(mesh, point, heading, 0.022, [(-0.18, 2.29), (-0.13, 2.34), (0.12, 2.09), (0.07, 2.04)], WHITE)
        face(mesh, point, heading, 0.022, [(-0.04, 2.01), (0.16, 2.00), (0.16, 2.21)], WHITE)
    else:
        face(mesh, point, heading, 0.019, [(-0.35, 2.15), (0.35, 2.15), (0.35, 2.85), (-0.35, 2.85)], BLUE)
        face(mesh, point, heading, 0.021, [(-0.28, 2.24), (0.28, 2.24), (0, 2.77)], WHITE)
        person(mesh, point, heading, 0.024, 2.43, DARK, walking=True)
