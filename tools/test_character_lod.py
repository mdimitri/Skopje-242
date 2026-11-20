"""Check that every roster entry has three real LODs and drawable poses without a GPU."""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import characters
import vehicles
from modelpool import _job


def check_roster():
    street = range(vehicles.PED_COUNT)
    heroes = range(100, 100 + len(characters.LIKOVI))
    for arch in (*street, *heroes):
        poses = (0, 2, 3, 4, 5, 12, 16, 23, 35, 43)
        if arch in heroes:
            poses += (13, 60, 67)
        for frame in poses:
            counts = []
            for tier in (1, 2, 3):
                (positions, uv, colors), grip = _job(("ped", arch, 2, frame, 3, tier))
                assert len(positions) % 3 == 0, (arch, frame, tier)
                assert positions.shape == (len(uv), 3) and uv.shape == (len(colors), 2), (arch, frame, tier)
                assert np.isfinite(positions).all() and np.isfinite(uv).all(), (arch, frame, tier)
                assert (grip is not None) == (arch in heroes), (arch, frame, tier)
                if tier > 1:
                    assert np.ptp(uv[:, 0]) > 0.05, (arch, frame, tier)
                counts.append(len(positions) // 3)
            assert counts[0] < counts[1] < counts[2], (arch, frame, counts)
    print(f"Verified three LODs for {len(street)} pedestrian IDs and {len(heroes)} heroes.")


if __name__ == "__main__":
    check_roster()
