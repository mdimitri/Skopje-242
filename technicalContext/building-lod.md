# Building distance rendering

`tools/build_world.py` world version 87 adds `chunks[key]["lod"]`. Each record
contains `(low_xyz, high_xyz, spans)`, where a span is `(material, vertex_start,
vertex_count)` within that chunk's material arrays. The bmesh stage records these
while appending each building's actual geometry, before street props, cables and
other stages append more geometry. The incremental runner merges mesh layers in
stage order, preserving these offsets. Mesh arrays retain their existing layout;
read the complete material arrays with `World.mesh_arrays` before slicing a span.
No extra packed file is required. The normal world-version upgrade rebuilds the
affected stages. Old worlds and demo worlds without records retain legacy blocks.

`Renderer.prepare_far` runs before `present.begin`, alongside the other offscreen
preparation passes. `farview.FarView` plans visible chunks outside streamed meshes
and asks `buildinglod.Captures` to prepare them. Captures isolate each building by
its spans, preserving facade materials, vertex shading, roof, relief and clutter.
Four orthographic walls and one roof are packed into day and window-emission
atlases. The emission capture uses `lightmap.WIN_FS` with black depth-writing
occluders instead of discarded non-window surfaces. Capture targets must never be
nested inside the scene target: `end_texture_mode` returns to the default target.

Each atlas group contains at most 16 buildings, with 64-pixel face tiles and an
eight-pixel transparent border for mip filtering. Preparation uploads/captures
one building at a time under a 3 ms budget (one building can exceed that budget).
The cache admits at most 192 groups; atlas heights fit the actual record count
rather than reserving 16 rows. Nearest visible groups take priority, including
streamed chunks so their captures can warm before they leave the full-mesh ring. Pending
or unadmitted chunks retain the legacy footprint mesh. Trees retain their existing
cheap pyramids when a captured building group replaces a legacy chunk. Resources
are released on eviction and normal shutdown. There is no disk capture cache.

Buildings use rectangular textured prisms beyond the full/lite streaming range.
Beyond the view's sprite threshold, each group uses one camera-facing quad per building. Both forms use
the same shader: intersect the camera ray with the building bounds, sample the
same captured face, discard transparent texels and write the intersection depth.
This preserves perspective and occlusion at the prism/sprite handoff without an
angle-indexed sprite bank. Silhouette detail and parallax inside the simplified
prism remain approximations of the original geometry. Captures use the source
textures and baked vertex lighting; near-only procedural surface relief is not
re-evaluated on the stand-ins.

The renderer caches bounds per atlas group and uploads camera uniforms when the
camera or render pass changes. The day pass samples the color atlas. The glow
pass also samples the window-emission atlas.

The day pass writes the captured albedo. After `Night.draw` applies ambient tint,
`FarView.windows` adds captured emission with depth testing and no depth writes.
Backface culling prevents hidden prism faces from adding emission twice. New
worlds' street-view full meshes and captures share `lightmap.BUILDING_WIN_R`
(2600 m) and the same fade, strength and deterministic window selection. The far
ring is enabled for walking and driving in third-person chase view, as well as
helicopters. Regular third person retains full meshes to 150 m and lite meshes
to 337.5 m, then uses captured prisms to 600 m and sprites out to about 1100 m
(1200 m clip range with the existing 100 m far-ring margin). Helicopters retain
the 1200 m sprite threshold and approximately 2500 m far ring (2600 m clip range).
These are distance bands; chunk bounds and cached streamed meshes can overlap
them. `main.py` sets `renderer.far_sprite` and `view_far` each frame, so switching
between a ground vehicle and helicopter updates the ranges without rebuilding
captures. `FarView` forwards the same sprite threshold to the day and window
passes. The same 2600 m window-light fade is retained across both views.

`python tools/test_building_lod.py` runs a hidden real-OpenGL regression. It checks
multiple building spans/atlas rows, emission versus roof occlusion, prism/sprite
pixel agreement across four views (including axial and overhead rays), and
foreground occlusion by day and night. Review output is written to
`output/building_lod/day_night_prism_sprite.png`. This fixture does not replace a
flight through a rebuilt city when evaluating capture throughput or near/prism
silhouette changes.
