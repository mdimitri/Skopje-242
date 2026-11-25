"""Split 2x2 generated material sheets into color tiles and local-contrast height maps."""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


SIZE = 384
EDGE_BLEND = 24
FAMILIES = (
    "asphalt", "paving", "vegetation", "earth", "plaster", "masonry", "roof", "metal",
    "water", "bark", "leaf", "wood", "ceramic", "carpet", "cloth", "leather", "skin",
    "hair", "fur", "feather", "paint", "rubber", "plastic", "concrete", "paper",
)

# Five palettes crossed with four surface details make twenty distinct descriptions per family.
STYLES = {
    "asphalt": ("municipal roadway asphalt", ["warm charcoal gray", "cool blue gray", "pale weathered gray", "near-black basalt", "brown-gray aged"], ["fine limestone chips", "dense tiny granite aggregate", "sparse rounded mineral flecks", "subtle hairline wear and pinholes"]),
    "paving": ("urban sidewalk paving", ["cool light gray", "warm limestone beige", "muted red brown", "charcoal gray", "pale sand gray"], ["rectangular concrete slabs with flush joints", "small granite setts in courses", "square terrazzo tiles with fine fragments", "worn interlocking pavers with narrow joints"]),
    "vegetation": ("Balkan park ground cover", ["olive green", "spring green", "dry yellow green", "sage green", "deep meadow green"], ["short fine grass blades", "low clover leaves mixed with grass", "sparse shoots over dry soil", "dense tiny meadow foliage"]),
    "earth": ("natural ground soil", ["warm tan", "dry ochre", "deep brown", "cool gray brown", "pale sandy beige"], ["compacted fine silty soil", "tiny embedded gravel", "crumbly clay clods", "fine dry earth with scattered pebbles"]),
    "plaster": ("weathered exterior wall plaster", ["warm white", "cream beige", "cool light gray", "sand colored", "pale ivory"], ["fine lime stucco grain", "subtle trowel mottling", "tiny shallow pits", "gentle worn brush texture"]),
    "masonry": ("exterior masonry wall", ["faded red clay", "warm cream limestone", "neutral gray stone", "ochre brown brick", "pale tan block"], ["running-bond bricks with thin mortar", "rough staggered ashlar courses", "small weathered rubble stones", "regular masonry blocks with recessed joints"]),
    "roof": ("aged urban roof covering", ["muted terracotta", "burnt orange", "slate gray", "sandy brown", "deep red brown"], ["overlapping curved clay tiles", "small flat tiles in horizontal courses", "weathered bitumen with fine grit", "overlapping concrete roof shingles"]),
    "metal": ("exterior sheet-metal cladding", ["galvanized gray", "blue gray", "dull zinc silver", "oxidized brown", "dark neutral gray"], ["fine vertical corrugations", "standing-seam panels with straight joints", "shallow narrow ribs", "flat aged enamel panels with subtle wear"]),
    "water": ("close-up natural water surface", ["deep blue green", "cool slate blue", "muted olive green", "pale turquoise gray", "dark river gray"], ["fine overlapping ripples", "soft short wavelets", "subtle circular surface undulations", "calm water with tiny broken highlights"]),
    "bark": ("tree bark surface", ["warm chestnut brown", "cool gray brown", "dark walnut", "pale ash gray", "reddish umber"], ["fine vertical furrows", "shallow broken plates", "rough narrow ridges", "small irregular bark scales"]),
    "leaf": ("overhead leaf and foliage ground texture", ["olive green", "fresh spring green", "deep forest green", "dry ochre green", "sage green"], ["small overlapping broad leaves", "fine mixed leaf litter", "tiny clustered foliage", "rounded leaves with restrained veins"]),
    "wood": ("weathered wood surface", ["honey brown", "gray brown", "deep walnut", "pale pine", "reddish cedar"], ["fine lengthwise grain", "aged narrow planks with faint seams", "subtle saw-cut fibers", "weathered wood with small knots"]),
    "ceramic": ("ceramic tile surface", ["warm ivory", "muted terracotta", "cool gray", "pale sage", "deep blue gray"], ["small glazed square tiles with fine grout", "matte ceramic with subtle speckles", "rectangular tiles in staggered courses", "worn ceramic glaze with tiny imperfections"]),
    "carpet": ("close-up woven carpet surface", ["warm beige", "muted burgundy", "cool charcoal", "olive brown", "dusty blue"], ["dense short wool pile", "tight loop pile", "fine woven fibers", "subtle low geometric weave without a large motif"]),
    "cloth": ("close-up textile fabric", ["natural cream", "slate blue", "charcoal gray", "earth brown", "muted olive"], ["plain tight woven fibers", "fine diagonal twill", "soft linen crosshatch", "dense matte cloth weave"]),
    "leather": ("close-up natural leather surface", ["warm saddle brown", "dark espresso", "muted oxblood", "gray taupe", "near-black charcoal"], ["fine natural grain", "soft pebbled grain", "subtle creases and pores", "smooth worn leather with tiny irregular marks"]),
    "skin": ("close-up natural skin surface texture", ["warm light beige", "medium olive tan", "deep warm brown", "cool pale beige", "sun-warmed tan"], ["fine pores and subtle tonal variation", "soft natural skin grain", "tiny shallow freckles without distinct spots", "fine smooth texture with restrained pores"]),
    "hair": ("close-up natural hair strands", ["dark brown", "black", "warm chestnut", "ash brown", "dark blond"], ["fine parallel strands", "soft overlapping locks", "dense short strands", "subtle curved fibers with no visible scalp"]),
    "fur": ("close-up animal fur surface", ["warm tawny brown", "cream beige", "dark charcoal", "gray brown", "reddish brown"], ["short dense hairs", "soft medium-length fibers", "fine underfur with subtle direction", "overlapping coarse guard hairs"]),
    "feather": ("close-up layered feather surface", ["warm brown", "soft gray", "dark charcoal", "cream tan", "muted blue gray"], ["fine feather barbs", "overlapping small feathers", "soft down fibers", "narrow feather shafts with delicate barbs"]),
    "paint": ("painted solid surface", ["warm white", "sage green", "muted blue", "brick red", "charcoal gray"], ["matte enamel with fine orange peel", "weathered painted metal with tiny wear", "smooth wall paint with subtle roller grain", "aged paint with faint fine scratches"]),
    "rubber": ("rubber material surface", ["deep charcoal", "warm black", "cool dark gray", "muted brown black", "dark blue gray"], ["fine stippled grain", "subtle molded ribs", "dense tiny pores", "matte rubber with faint shallow scuffs"]),
    "plastic": ("molded plastic surface", ["warm ivory", "dark graphite", "muted blue gray", "olive green", "warm tan"], ["fine matte molded grain", "subtle orange-peel texture", "tiny regular stipple", "smooth polymer with faint shallow scuffs"]),
    "concrete": ("cast concrete surface", ["cool light gray", "warm gray", "pale beige gray", "charcoal gray", "soft taupe gray"], ["fine exposed aggregate", "tiny air pores and mineral flecks", "subtle trowel grain", "weathered cement with small embedded stones"]),
    "paper": ("unprinted paper surface", ["warm ivory", "natural cream", "cool pale gray", "light kraft tan", "soft white"], ["fine pressed fibers", "subtle handmade pulp flecks", "smooth paper with tiny fibers", "lightly fibrous matte stock"]),
}


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


def material_description(family, variant):
    base, colors, details = STYLES[family]
    color = colors[(variant - 1) % len(colors)]
    detail = details[((variant - 1) // len(colors)) % len(details)]
    return f"{color} {base}, {detail}"


def make_prompt(family, variants):
    quadrants = "\n".join(
        f"{index + 1}. {material_description(family, variant)}"
        for index, variant in enumerate(variants))
    return (
        "Create exactly four distinct square photorealistic seamless albedo samples for a "
        "realistic open-world game as a precisely aligned 2-by-2 contact sheet. The quadrants "
        "in reading order must show:\n" + quadrants + "\n"
        "Every quadrant fills its square to the edges with one continuous, evenly scaled surface. "
        "Exact equal quadrants with a straight split at the center; no gutters, divider lines, "
        "borders, gaps, labels, or objects. Perfectly orthographic face-on close-up. Flat neutral "
        "diffuse illumination, albedo only, no directional shadows, no perspective, no dramatic "
        "lighting. Keep details fine enough to repeat as a 384-pixel game material. No text, logos, "
        "watermarks, or scene context."
    )


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


def plan(output_dir):
    jobs = []
    for family in FAMILIES:
        missing = [variant for variant in range(1, 21)
                   if not (output_dir / f"{family}_{variant:02d}.jpg").exists()]
        for start in range(0, len(missing), 4):
            variants = missing[start:start + 4]
            fillers = [variant for variant in range(1, 21) if variant not in variants]
            quadrants = variants + fillers[:4 - len(variants)]
            jobs.append({"family": family, "variants": variants, "quadrants": quadrants,
                         "prompt": make_prompt(family, quadrants)})
    return jobs


def write_catalog(output_dir, catalog_path):
    catalog = {
        "description": "500 expanded material variants. The original prompt records for pre-existing tiles were not in the repository.",
        "bump_map_method": "16-bit grayscale local-luminance detail after subtracting an 8-pixel Gaussian blur; broad tonal variation is removed. Opposite edge strips are blended for wrapping.",
        "materials": [],
    }
    for family in FAMILIES:
        for variant in range(1, 21):
            key = f"{family}_{variant:02d}"
            if not (output_dir / f"{key}.jpg").exists() or not (output_dir / f"{key}_height.png").exists():
                raise FileNotFoundError(f"Missing color or height map for {key}")
            generated = variant  # New tiles use the shared mosaic prompt and per-quadrant description.
            prompt = material_description(family, generated) if key not in PREEXISTING else None
            catalog["materials"].append({
                "id": key,
                "color": f"{key}.jpg",
                "height": f"{key}_height.png",
                "source": "pre-existing; original prompt unavailable" if prompt is None else "ImageGen 2x2 mosaic",
                "prompt": prompt,
            })
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


PREEXISTING_VARIANTS = {
    "asphalt": (1, 2, 3, 4, 5, 6, 7, 8, 10),
    "paving": (1, 2, 3, 4, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 20),
    "vegetation": (1, 2, 3, 4, 5, 7, 8, 9, 10),
    "earth": (1, 2, 3, 4), "plaster": (1, 2, 3, 4, 5),
    "masonry": (1, 2, 3, 4), "roof": (1, 2, 3, 4), "metal": (1, 2, 3, 4),
    "water": (1, 2, 3, 4), "bark": (2, 3, 4), "leaf": (1, 2, 3),
    "wood": (1, 2, 3), "ceramic": (1, 2, 3, 4), "carpet": (1, 2, 4),
    "cloth": (1, 2, 3, 4), "leather": (1, 2, 3, 4), "skin": (1, 2, 3),
    "hair": (1, 2, 3, 4), "fur": (1, 2, 3, 4), "feather": (1, 2, 3),
    "paint": (2, 3), "rubber": (1, 2, 3), "plastic": (1, 2, 3),
    "concrete": (1, 2, 3), "paper": (1, 2, 3),
}
PREEXISTING = {f"{family}_{variant:02d}"
               for family, variants in PREEXISTING_VARIANTS.items() for variant in variants}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parents[1] / "assets" / "textures" / "expanded")
    parser.add_argument("--plan", action="store_true", help="print the missing 2x2 mosaic jobs as JSON")
    parser.add_argument("--catalog", type=Path, help="write the completed 500-material catalog")
    parser.add_argument("mosaic", nargs="?", type=Path)
    parser.add_argument("family", nargs="?")
    parser.add_argument("variants", nargs="*", type=int)
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(args.output), ensure_ascii=False))
    elif args.catalog:
        write_catalog(args.output, args.catalog)
    elif args.mosaic and args.family and args.variants:
        process(args.mosaic, args.family, args.variants, args.output)
    else:
        parser.error("provide --plan, --catalog <file>, or a mosaic, family, and variant list")


if __name__ == "__main__":
    main()
