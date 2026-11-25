"""Split 2x2 generated material sheets into color tiles and local-contrast height maps."""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


SIZE = 384
EDGE_BLEND = 24


def wrap_edges(image, width=EDGE_BLEND):
    """Blend opposite edge strips so each output tile wraps continuously."""
    pixels = np.asarray(image, dtype=np.float32).copy()
    for axis in (1, 0):
        length = pixels.shape[axis]
        for offset in range(width):
            left = [slice(None)] * pixels.ndim
            right = [slice(None)] * pixels.ndim
            left[axis] = offset
            right[axis] = length - width + offset
            left, right = tuple(left), tuple(right)
            a, b = pixels[left].copy(), pixels[right].copy()
            t = 0.5 - 0.5 * np.cos(np.pi * offset / max(1, width - 1))
            average = (a + b) * 0.5
            pixels[left] = average + (a - average) * t
            pixels[right] = average + (b - average) * t
    return np.clip(np.rint(pixels), 0, 255).astype(np.uint8)


def height_map(rgb):
    """Estimate relief from local luminance after removing broad tonal variation."""
    luminance = Image.fromarray(rgb, "RGB").convert("L")
    detail = np.asarray(luminance, dtype=np.float32)
    broad = np.asarray(luminance.filter(ImageFilter.GaussianBlur(radius=8)), dtype=np.float32)
    detail -= broad
    scale = float(np.percentile(np.abs(detail), 98.5))
    if scale < 1.0:
        return np.full((SIZE, SIZE), 32768, dtype=np.uint16)
    normalized = np.clip(detail / scale, -1.0, 1.0)
    values = np.rint(32768.0 + normalized * 21000.0).astype(np.uint16)
    return values


def process(mosaic_path, family, variants, output_dir):
    with Image.open(mosaic_path) as source:
        mosaic = source.convert("RGB")
        if mosaic.width != mosaic.height or mosaic.width % 2:
            raise ValueError(f"Expected a square 2x2 mosaic: {mosaic.size}")
        half = mosaic.width // 2
        if len(variants) > 4:
            raise ValueError("A mosaic can contain at most four variants")
        output_dir.mkdir(parents=True, exist_ok=True)
        for quadrant, variant in enumerate(variants):
            row, column = divmod(quadrant, 2)
            tile = mosaic.crop((column * half, row * half,
                                (column + 1) * half, (row + 1) * half))
            tile = tile.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
            rgb = wrap_edges(np.asarray(tile, dtype=np.uint8))
            key = f"{family}_{int(variant):02d}"
            Image.fromarray(rgb, "RGB").save(
                output_dir / f"{key}.jpg", quality=94, subsampling=0, optimize=True)
            Image.fromarray(height_map(rgb)).save(
                output_dir / f"{key}_height.png", optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mosaic", type=Path)
    parser.add_argument("family")
    parser.add_argument("variants", nargs="+", type=int)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "assets" / "textures" / "expanded")
    args = parser.parse_args()
    process(args.mosaic, args.family, args.variants, args.output)


if __name__ == "__main__":
    main()
