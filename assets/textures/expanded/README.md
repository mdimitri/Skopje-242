# Expanded materials

The expanded pack contains 500 repeating 384 × 384 materials: 20 variants for each of 25 families. Each `<id>.jpg` is the color tile and each `<id>_height.png` is its matching 16-bit grayscale bump map. Lighter pixels represent raised detail. The UVs and repeat period are shared by both files.

Built-in ImageGen created the color sources. The completed variants were generated four at a time as 2 × 2 material mosaics, then split into individual tiles. The processed tiles use overlapping edge strips for continuous wrapping. The height maps estimate relief from local luminance detail after removing broad tonal variation. The [catalog](materials.json) records each material description and identifies the original tiles whose prompts were not preserved.

Select **Графика → Пакет текстури → Проширени со релјеф** to use this pack in Skopje 242. The default **Стандардни** uses the original game materials and **Градски** uses the 64-texture city pack.

The renderer uses the expanded tiles for terrain, roads, water, buildings, tree bark and foliage, vehicles, characters, props, and mall interiors. Material detail fades as it becomes too small to resolve on screen. Glass, lights, and text decals retain their own rendering.
