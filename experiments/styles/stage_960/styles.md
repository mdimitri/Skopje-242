# Skopje GTA - alternative rendering styles

Scene: 5-way tertiary junction in central Skopje, world coords (-66, -341) m from centre (Opstina Centar, "Zito Leb" / "DHL" / "Bar Crash" POIs nearby), 14:00, 150 cars / 200 peds.
Reproduce: `.runtime\venv\Scripts\python.exe src\main.py --test 12 --shot experiments\styles\raw\a --start=-66,-341 --hour 14 --mute --cars 150 --peds 200 --nomenu`, then `python experiments\styles\styles.py`.
All styles are image-space on the 1280x720 crop of that frame (HUD cropped out). Real in-game versions would use the raylib shader pipeline: render scene to RenderTexture, draw it through a fragment shader (depth/normal not needed for most; outlines look better with a depth/ID pass).

| # | Style | Look | In-game implementation | Cost / risk |
|---|---|---|---|---|
| 01 | cel_outline | Flat 6-level colour bands, thick black ink outlines | Post-process shader: posterize + Sobel edge on colour (better: depth/normal edge from a second pass) | Low; outlines flicker on grass/props noise, tune thresholds |
| 02 | toy_pastel | Soft pastel plasticine toy city, k-means colour blobs, no texture detail | Palette/asset change: swap vertex colours to pastel palette + disable detail textures; or shader desaturate+lerp to pastel | Low (shader) / Medium (asset palette) |
| 03 | popart_halftone | Magenta/green/red comic print, black halftone dots + thick outlines | Post-process shader: luminance gradient map, halftone via screen-space dot pattern, edge pass | Low-Med; dots shimmer in motion unless world-anchored |
| 04 | noir | High-contrast B&W, film grain, light shafts, heavy vignette | Post-process shader: grayscale + contrast curve + noise + vignette | Very low; trivially cheap |
| 05 | neon_synthwave | Dark night city, glowing cyan/magenta edge lines, bloom, scanlines | Post-process: darken + edge-detect glow + bloom blur chain; pairs with existing Night module lights | Medium (bloom needs blur passes), GPU cost moderate |
| 06 | watercolor | Washed pastel paint, paper grain, soft pigment edges | Post-process: Kuwahara/bilateral filter + paper noise texture + edge darkening | Medium; Kuwahara is expensive at 1080p+ (use separable/low radius) |
| 07 | blueprint | White line-art on blue grid paper, nothing filled | Post-process: edge detect on depth+colour, flat blue background + grid; also easy as a debug/map mode | Low; loses readability of cars/peds unless outlined separately |
| 08 | claymation | Puffy lit relief, warm clay colour, fingerprint noise | Shader: normal-ish relief from luminance gradient + noise; truer with real normals/matcap in the mesh shader | Medium; matcap on meshes is the high-fidelity route |
| 09 | lowpoly | Faceted flat triangles | Pure post-process is a hack (CPU Delaunay here); in-game: flat-shaded (face normals) meshes + vertex-colour quantisation, or geometry-shader-free derivative trick (dFdx/dFdy normals) | Low (flat shading shader) but triangulating the frame is not realistic per-frame |
| 10 | vaporwave_sunset | Pink/purple gradient world, retro striped sun, yellow outlines | Post-process: gradient LUT on luminance + vertical gradient + sun sprite overlay + edge pass | Low; LUT-based, cheap |
| 11 | pixel_dither | Chunky 5x pixels, 16-colour palette, Bayer dithering | Render at 1/5 resolution into RenderTexture, upscale nearest, palette quantise + Bayer in shader | Very low, actually a perf win |
| 12 | gameboy | 4-shade green handheld LCD look at ~213x120 | Same as pixel_dither with a 4-colour LUT | Very low |
| 13 | thermal | Thermal-camera heat palette from luminance | Post-process: luminance to gradient LUT (could use real "heat" tags for cars/peds for fidelity) | Very low |
| 14 | ukiyoe_woodblock | Limited 8-colour Japanese print palette, dark ink outlines, paper grain | Post-process: nearest-palette quantise + median + edge + paper noise; or palette swap in asset colours | Low-Med; palette choice dominates the result |

Notes: styles 01,03,05,07,10 benefit most from a depth/normal pre-pass (cleaner edges, no texture-noise lines); that is the single biggest fidelity upgrade. Default look is untouched - nothing in the game was modified.
