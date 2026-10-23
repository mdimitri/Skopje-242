# Architecture

## Data pipeline (`tools/`)
1. `fetch_osm.py` - 4 Overpass queries (roads, buildings, areas/water/rail, POIs) for the bbox, `out geom`,
   mirrors + retries, cached as `data/osm/*.json`.
2. `build_world.py` - projects lat/lon to local metres (origin = centre, +x east, +y south), then:
   - buildings (incl. multipolygons with courtyards): earcut triangulation, height from `height` /
     `building:levels` or procedural from footprint area + seeded RNG, procedural roof/wall colours;
   - areas (parks, woods, water, plazas, parking, landuse) triangulated; waterways, rails;
   - roads: width/speed per class, bridges, one-ways; **routing graph** split at junctions;
   - procedural props: trees (parks/woods + street trees), lamps, parked cars, all rejected against a
     2 m occupancy raster; 2 m surface mask (ground / water / bridge / road) for gameplay;
   - **chunk index** (120 m chunks): which buildings/areas/road segments/props touch each chunk.
   Output: one pickle (`data/cache/world.pkl`). Deterministic (seeded by OSM ids).
3. `make_synthetic_osm.py` - fake Overpass data (grid city + river) used as offline demo / test fixture.

## Rendering (`src/render.py`, `src/bake.py`, `src/gl3d.py`)
- **Real 3D, top-down camera**: perspective camera high above the car with a slight tilt; buildings (walls with
  procedural window textures, roofs, pyramid roofs on houses, rooftop boxes), trees and lamp posts are real meshes,
  generated offline by `build_world.py` into `meshes.bin` (one blob, per chunk and material). Nothing 3D is rebuilt at runtime.
- **Streaming**: a 120 m chunk = one ground texture (roads, parks, water, building shadows; baked on the GPU, mipmapped)
  + up to 4 meshes uploaded from the memory-mapped blob. LRU caches, nearest-first, per-frame time budget, frustum culling.
- **LOD**: a 4096 px overview of the whole city is always drawn under the chunks and replaces them when zoomed out;
  it is also the minimap / full map (cached as PNG with an integrity check).
- **Decals** (skid marks, blood, scorch) are drawn straight into the ground chunk textures and replayed when a chunk is re-baked.
- **Cars**: procedural subdivided meshes; impacts displace vertices (dents) and darken them; a new model is built only when
  the car is hit. Undamaged cars share cached models. Pedestrians/pickups are small procedural meshes.

## Simulation (`src/actors.py`)
- Player: arcade top-down car (throttle/brake, speed-dependent steering, lateral grip, handbrake drift,
  off-road drag); 3 collision circles against a hashed grid of building/parked-car edges; water = respawn.
- Traffic: cars follow the road graph (right-hand traffic, lane offset), brake for anything ahead via a
  spatial hash (cars, player, pedestrians), slow for junctions, spawn/despawn in a ring around the player.
  Cars the player hits become physical wrecks. Known limitation: no junction right-of-way logic, no lights.
- Pedestrians walk sidewalks/footways of the same graph; getting hit knocks them down.

## Robustness
`Guard` wraps each subsystem (sim, streaming, rendering, HUD ...): errors are logged, repeated failures disable only that
subsystem. World loading verifies file sizes, rebuilds corrupt data, falls back to the demo city. The overview falls back to
smaller sizes; failed chunks are skipped.

## Ideas for next steps
Traffic lights, police/wanted level, enterable cars, day/night + headlights, sound, mission system,
building interiors/roof detail, shader-based night lighting, moving baking to a worker thread.

## Vehicles, people and street furniture
`src/vehicles.py` is the catalogue (names, sizes, collision circles, traffic weights, pedestrian archetypes).
`gl3d.car_arrays` builds each car from boxes plus decal quads (windows, lights, plates, wheel arches); the lower body
and cabin are subdivided so dents can displace vertices. `gl3d.ped_arrays(arch, tone, frame, skin)` builds people.
`tools/furniture.py` runs at world build time over the routing graph and writes static meshes plus `posts`
(collision circles) and `xwalks` (zebra crossings, drawn into the ground textures by `bake._crosswalk`).
Bridge parapets only appear where the water mask is under the bridge. `python tools/model_sheet.py out.png`
renders a contact sheet of all models.

## Round 3: 3D roads, time of day, combat, sound

- **`tools/roads3d.py`** builds the road network from the *routing graph* (not the raw OSM ways): edges are smoothed
  (quadratic Bézier corners, endpoints fixed so junctions stay connected), then extruded to mitred ribbons (asphalt +
  darker gutters), round end fills, 2 m pavements raised 0.16 m with a curb face (chequered paving colours), lane
  markings (dashed centre/lane lines, double yellow on wide roads, solid edge lines) and zebra crossings. Ribbons are cut
  into <= 24 m pieces so each lands in the correct 120 m chunk. A `Cover` hash around junctions removes pavement and
  marking pieces that lie under another road's asphalt (higher rank wins). Heights: asphalt 0.05 + 0.012 x rank,
  markings +0.025, zebra 0.134, pavement 0.16. Everything is material 3 (vertex colours), streamed like buildings.
  The manifest flag `roads3d` tells `bake.py` to stop drawing roads into the ground textures; the overview/minimap keep
  the 2D roads. `hgt` (zlib grid, 0 ground / 1 asphalt / 2 pavement) gives `World.ground_y` so people and cars stand on
  the right surface. Skids, blood and scorch (decals) are redrawn as flat quads above the road (`Renderer._decals`).
- **`src/clock.py`** time of day (22 real minutes per day): traffic/pedestrian density curves with rush hours, darkness.
  `Sim.update` scales the agent targets and culls the farthest surplus agents; `[`/`]` shift the clock by an hour.
- **`src/night.py`** after the 3D pass: a multiply tint, then additive light pools (lamps, headlights, brake lights,
  burning wrecks, flashing red/blue light bars on police/ambulance/fire kinds 47-49).
- **Combat** (`Sim.attack`, `Peds` modes `fight`/`ko`): Ctrl = punch, punch, kick with a 60 degree cone, knock-back,
  per-archetype hp and fight-back chance (`vehicles.FIGHT`); KO'd peds drop cash. The walker has hp, a knocked-out state
  (about 4.5 s, then wakes at 35 hp having lost 40 % of the money) and jump (`z`, `vz`) - walker/car collisions are
  circle based and ignored while the player is above roof height, damage scales with closing speed.
- **`src/audio.py`** synthesises all effects with numpy and plays them through raylib (no device -> silent).
  **`src/speech.py`** is a formant synthesiser (harmonic source shaped by 3 formant resonances + band noise for
  fricatives/bursts) run on a background thread and cached; one voice per speaker name.
- **`src/places.py`** neighbourhood tooltips and the `T` teleport list (OSM place nodes, hand-placed fallback list).

## Round 4: bigger map, menu, rescue services, terrain, bridge levels

- **World box** 11 x 7 km (`tools/geo.py` HX/HY; `World.hx/hy/ncx/ncy`; overview texture is rectangular). Overpass is fetched in 6 tiles.
- **`src/settings.py`, `src/menu.py`** options (`settings.json`), applied live (`main.apply_cfg`); `src/ui.py` `Loader` is the splash screen with a log.
- **`src/services.py`** ambulance (revive) and fire engine (extinguish): `Sim._dispatch` requests them, they spawn 240-380 m away, route over the
  graph (Dijkstra), drive by pure pursuit through `Body.ctl`, crew are `Ped(mode="svc")`.
- **Terrain** (`tools/terrain.py`): float32 grid, 10 m posts, bilinear `Terrain.h` (build) and `World.th` (run time) are the same function.
  `build_world.py` carves the river bed (`carve_water`), lifts buildings (mean height under the footprint + a skirt down to the lowest corner),
  and lifts trees / lamps / furniture by the height under their centre. Roads/pavements/markings (`roads3d.Out`) are lifted per vertex in
  `flush()`; ribbon pieces are split adaptively (`_pieces`) so a flat piece stays within 1.2 cm of the curved ground.
  World part `terrain.pkl` holds the grid and the bridge decks. `hgt` bit 2 = ground-level water (also under bridges).
- **Ground rendering:** each streamed chunk gets a 4 m grid mesh textured with its baked ground texture (`Streamer._ground_model`); the far-LOD
  overview is a 40 m min-pooled terrain mesh under the overview texture. The camera focus height is smoothed (`cam_h`).
- **Bridge decks** (`terrain.make_deck`): ends meet the terrain; where the deck crosses a road (4.4 m) or footpath (3.0 m) a monotone cubic
  (PCHIP) profile lifts it to clear it (not within 24 m of an end). `roads3d` adds girders, underside and piers; `furniture` puts the parapets
  at deck height. Run time: `World.deck_h` (nearest centreline point), `World.level(x, y, wy)` picks the deck when the feet are on / above it,
  otherwise the ground; `World.wet(x, y, wy)` is ground-level water. Collision circles carry a height window (x, y, r, lo, hi), so a parapet
  on the deck does not block the path below and a pier does not block the deck.
- **Vertical motion:** `Walker.az/vz` (feet height) and `actors.settle()` for cars: glued to the surface; when it ends they fall (g = 16 m/s2 for
  the walker's arcade jump, 9.81 for cars), landing damage `(v - 8.5) * 8` for the walker, `(v - 5) * 5` for cars, splash if the landing is wet.
  Car gravity along the slope, parking brake, pitch/roll (`Body.pitch/roll`, drawn with a model matrix), Tobler walking speed.
- Not modelled: vehicle clearance under low decks (cars pass under any deck; the clearance is 4.4 m by construction), deck ramps beyond the bridge ends
  (so humpback bridges can be steep), tunnels, retaining walls.

## Round 5: Cyrillic, honest loading screen, hardened downloads, posters

- **Cyrillic everywhere.** raylib's default font has no Cyrillic, so every text call goes through `src/font.py` (DejaVu Sans + Bold in
  `assets/fonts`, explicit code points: ASCII, Latin-1/Ext-A, U+0400-04FF, punctuation, arrows; free licence). All interface strings are
  literary Macedonian: `src/strings.py` (interface), `src/slang.py` (banter, shop names, graffiti), `vehicles.py` (`MK_CAR`, `MK_PED`,
  `MK_LINES`, kiosk menu; internal Latin ids stay as keys: `IDS`, `PED_IDS`), `places.py`. Neighbourhood names come straight from the OSM
  `name` tag (Cyrillic); the old transliteration is gone. `speech.py` turns Cyrillic into the formant synth's phonemes (`cyr_to_latin`) and
  hands Cyrillic untouched to the neural voice. Sources and review status: `docs/TEXT_SOURCES.md`.
- **Event protocol.** With `SK242_EVENTS=1` the tools print ASCII lines `@@{json}`: `plan` (cells with their rectangle in local metres),
  `cell` (state active / done / cached / fail / split), `net` (bytes, bytes per second, seconds waiting, mirror; state wait / recv / done /
  rest), `warn` (failure kind per mirror), `note`, `prog` (build phase label, n, total), `done`. `main.run_tool` parses them and feeds
  `ui.Loader.event`. `tools/net.py` emits them for every request, once a second.
- **Loader (`src/ui.py`).** Stages are planned before anything starts (`main.plan_needs`: osm, dem, build, world, overview, textures,
  chunks). The overall bar is the weighted sum of stage fractions and can never move backwards (`max()` clamp). Download stages count finished
  cells; the build stage uses the phases of `tools/build_world.py` (`progress.Bar` / `progress.phase`) weighted by the seconds each phase
  took on the last real build (`data/cache/build_times.json`, never written for the demo city; defaults until then). The map panel draws
  the 11 x 7 km box: per tile five stripes (roads, buildings, areas, places of interest, neighbourhoods), terrain tiles as tinted frames;
  colours pending / active / done / cached / failed / split; plus the real speed, bytes, waiting time, server and the warnings.
- **Hardened download** (`tools/net.py`, `fetch_osm.py`, `fetch_terrain.py`): worker thread + supervisor, first-byte and stall timeouts,
  error kinds (busy / reject / stall / timeout / offline / bad / exhausted / http), mirror scoring and cool-down, Overpass `/status`
  slot check, `Retry-After`, splitting a cell into quarters on reject / timeout, resume from `data/osm/parts`, per-cell and total deadlines,
  second pass, exit codes 0 ok / 2 partial but usable / 1 nothing usable. `run_tool` also kills a tool that overruns its limit (osm 62 min,
  terrain 20 min, build 60 min). A partial download is retried at the next start only after an hour (`box.json`: complete, missing, t).
- **Posters.** `tools/make_posters.py` (Pillow only) draws 17 joke posters and `title.png` into `assets/posters/` and writes `posters.json`
  (file + the Macedonian joke). `src/poster.py` loads them at random (each once before any repeat) with a cross-fade; the title poster is the
  first screen of the loader and the backdrop of the start menu. Regenerate with `python tools/make_posters.py` (`file.png` to redo one).

## Round 6 - car radio
src/radio.py (raylib music streams, shuffle bag, generated static), tools/fetch_radio.py (Commons API, licence filter), setting vol_radio.

## Round 15 (polish)
- World VERSION 11: `connect_roads()` in tools/build_world.py joins dead ends that stop within 7 m of another road (same level, pointing at it) to the nearest vertex or a new junction node. Needs a world rebuild (automatic: build_world.py is newer than the manifest).
- Pop-ups, banners and place names stay visible in proportion to their length (`fx.read_time`).
- Start: the player stands next to the car (`--car` starts inside it, `--walker` forces it in `--test`); the starting neighbourhood is not announced.
- `World.wet()` is false while standing on a bridge deck (deck ends dip to bank level and used to count as river).
- Renderer: the whole-city overview model is only drawn when a ground chunk is missing; plain cars/bodies use the shared, budgeted models; dented-car models are freed when the car is gone; a person is never drawn as just a shadow.
