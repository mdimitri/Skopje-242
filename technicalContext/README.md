# Technical context index

Purpose: a compact, source-grounded latent map of Skopje 242 for quick agent orientation. It records relationships and implementation intent that are expensive to rediscover. It is not copied source and cannot replace checking current code. Target size is below 50,000 tokens. Current code and data always win when they disagree with this guide.

## Identity and architecture

Skopje 242 is a Windows-first Python 3D open-world driving and story sandbox, rendered with raylib and selected custom OpenGL paths. Its city geometry is generated from OSM and terrain inputs, with authored/procedural detail. The runtime consumes a baked world directory rather than parsing source map data every launch.

Architecture is a modular monolith. `src/main.py` is the composition root and owns startup, world readiness, long-lived simulation objects, and the frame loop. Most feature modules expose functions, data, or small stateful classes consumed by that root. The build pipeline is a separate tool application under `tools/`. Shared geographic or gameplay data conventions appear in modules under `src/`, while specialized build-only geometry lives in `tools/`.

Quick path map:

| Need | Begin at | Related implementation |
| --- | --- | --- |
| Launch, CLI, startup, frame composition | `run.bat`, `src/main.py` | `src/settings.py`, `src/updater.py`, `src/ui.py` |
| World source acquisition and build | `tools/build_world.py` | `tools/stages.py`, `tools/fetch_world.py`, `tools/terrain.py`, `tools/pack_world.py` |
| Runtime world loading and spatial queries | `src/world.py` | `src/geo.py`, `src/roadwidth.py`, `src/crosswalks.py` |
| Rendering and GPU resources | `src/render.py` | `src/gfx.py`, `src/gl3d.py`, `src/fastrl.py`, `src/present.py`, `src/lightmap.py` |
| Surface texture packs | `src/surfacepack.py` | `assets/textures/*/README.md`, `tools/process_texture_mosaics.py` |
| Player and AI simulation | `src/actors.py` | `src/driving.py`, `src/vehicles.py`, `src/trafficproc.py` |
| Dialogue and character identity | `src/characters.py` | `src/talk.py`, `src/texts.py`, `src/strings.py`, line/profile modules |
| Network session and replicated play | `src/mp.py` | `src/mpnet.py`, `src/discovery.py`, `src/mpgame.py`, `src/mpprofile.py` |
| Sound and music | `src/audio.py` | `src/soundlib.py`, `src/soundproc.py`, `src/radio.py`, `src/voice.py` |
| Data/visual quality checks | `tools/*_audit.py`, `tools/check_*.py` | Feature-specific test scripts in `tools/` |

## Runtime lifecycle and ownership

`run.bat` is the supported launch path. It creates or uses the managed Python environment, installs requirements as needed, and enters the game startup. `src/main.py` first establishes logging and an early splash path, optionally checks for updates, imports the broad runtime system set, parses launch arguments, ensures the selected world exists and is usable, then constructs the runtime systems and enters interactive play. Startup paths include demo world, custom world, refresh/build, menu, and multiplayer host/join. Confirm exact flags and sequencing in current source.

`main.py` is deliberately large as the integration/composition point. Feature logic should normally live in an appropriate focused module and be passed the needed state from main. Before changing initialization order, search constructors and update/draw call sites in main because a subsystem may rely on another subsystem already existing.

Frame ownership is split between game state and presentation. Simulation systems update entities and world state. Renderer and UI functions consume that state to draw. The `render.py` / `present.py` / `gfx.py` / `gl3d.py` division is a useful first map, but verify concrete ownership from imports and calls before touching a rendering path. Window and GPU operations generally belong on the main thread. Startup helpers such as `loading_task` keep the window responsive while CPU or I/O work runs off-thread.

Long-running and CPU-heavy work has explicit support: `src/cpusched.py` adjusts priority, `src/modelpool.py` manages model reuse, `src/bake.py` and stream helpers prepare data, and main's loading UI reports progress. Avoid adding expensive repeated work to per-frame paths. Profile using `tools/perf.py`, `tools/perf_gl.py`, and `tools/perf_report.py` when changing hot paths.

## World data model and coordinate flow

The source world pipeline starts from OSM and elevation inputs fetched or placed under `data/`. `tools/build_world.py` interprets source features, applies project-specific procedural rules, and emits mesh layers and runtime metadata. The output is packed into a versioned world directory with a manifest. `src/world.py` validates that manifest, loads the baked components, and provides runtime world geometry, collision/spatial indexes, routing data, and terrain access. Its `lean=True` load mode intentionally omits expensive visual/collision structures for worker processes that only need road routing and heights.

Road lane and width tags flow from OSM through `tools/build_world.py` and `tools/roadclean.py` into the graph and road mesh. Explicit OSM lane counts, directional splits, and widths are preserved; class lane caps and inferred widths apply only when OSM has no corresponding tag. Keep junction and bridge surface widths tied to the stored carriageway width, while lane markings use the directional lane counts.

The default ground-road mesh uses the reviewed compiler in `tools/roadvault/road_candidate.py`. The `roads3d` stage passes original OSM ways to `tools/roads_candidate.py` through `tools/roads_designer.py`. The adapter splits ways at shared nodes, like the preview, and uses the authored Partizanski–Glavinov core when its OSM inputs match. It retains reviewed inference windows for the four other reference sites. The cooked graph still supplies traffic bindings and bridge decks. Those systems need separate alignment with the original OSM road geometry. Startup checks baked world versions before accepting a prebuilt pack.

The `road_controls` stage adds citywide traffic controls with the candidate's signal meshes and live phases. It selects junctions from mapped signal locations and the road network, matches existing zebra sections where possible and adds stop lines, approach warnings and pedestrian signals. The approved Glavinov control plan takes precedence.

The candidate infers missing zebra crossings at substantial ground junctions, verifies both landings against the finished walkable surfaces, and links opposing carriageways across a known median. It tapers eligible one- or two-lane width changes, widens urban single-lane slips by 50%, and links enclosed slip refuges to the outer sidewalk where both landings join walkable surfaces. It generates turn arrows, slip yield markings and mapped cycle-lane markings. Candidate gantries span perpendicular to the local road heading and their heads share that span. Citywide controls use the nearby original OSM way for their local heading when it matches the traffic graph.

All road-network builds and algorithm adaptations are also governed by the user’s [RoadNet rulebook](../RoadNet%20rulebook/RoadNet%20rulebook.txt). Consult it before each such change, verify each applicable constraint in the output, attempt corrections for violations, and report any constraint that remains unmet.

Bridge approaches trimmed by `roads_designer.deck_feet` are explicit candidate edges joined through original OSM endpoint IDs. Grounded stretches use a 2 cm terrain tolerance; short portals remain at ground junctions so the compiler sees the bridge arm. `roads_designer.drape_feet` lifts their vertices onto the deck profile, including immediately rising ramps. `junction_net.port_decks` uses runtime lane bounds and directional counts for deck markings, the ground asphalt height offset and colour, and a height check before blending twin-carriageway medians. `tools/test_bridge_interfaces.py` checks approach coverage, sloping deck heights, asymmetric lane markings and stacked-deck separation. Traffic accepts all marked turn lanes and preserves a legal lane through parallel turns; unmarked turns and slip entries retain the outer-lane rules. The same `actors`/`driving` implementation runs in the traffic worker.

The road shader in `src/gl3d.py` uses the baked road palette and surface slope to choose asphalt, paving or ground vegetation detail. It uses world-space textures to keep grain continuous between tiles. `src/bake.py` offsets the candidate paint palette at upload so that asphalt triangulated separately on the terrain does not hide the markings. City controls skip stop bars that would touch a generated zebra.

`src/geo.py` and the corresponding build helper define conversion from geographic coordinates to local projected coordinates. Keep transformations and dimensions consistent across source acquisition, build, runtime queries, and authored additions. Do not casually mix longitude/latitude with local world units. Inspect `HX`, `HY`, projection helpers, and relevant metadata at the call site.

Build products include metadata and distinct semantic layers such as areas, roads, edges, buildings, props, chunks, surface masks, and terrain. `World.PARTS` in `src/world.py` is a direct index of the current serialized parts. The exact schema is defined by writer and reader code. If changing it, inspect packing, manifest/version checks, loading, demo data, and any worker consumer together.

Generated geometry is designed to be plausible and performant at city scale. Build helpers triangulate polygons, chunk meshes, create collision/routing structures, and add deterministic variation for features without sufficient map detail. OSM identifiers and stable seeds help prevent random visual drift across builds. Continue using deterministic inputs when extending this layer.

## Incremental build system

`tools/build_world.py` declares ordered build stages and performs the actual transformations. `tools/stages.py` parses the stage markers, fingerprints each stage's code dependencies and declared input data, and caches stage state and emitted mesh layers. It can reuse unchanged stage outputs and stop propagating rebuilds when an upstream stage's output digest remains unchanged. The final write stage serializes the world from cached layers. This means a helper or imported local module can affect cache validity even when the visible stage body does not change.

When investigating stale or incorrect output:

1. Identify the stage that owns the output in `tools/build_world.py`.
2. Trace helpers, local modules, and input files that stage reads.
3. Check stage fingerprint, cached state, and output digest logic in `tools/stages.py`.
4. Use the project rebuild controls documented in those source files when a forced rebuild is genuinely needed.

Avoid bypassing the stage runner or editing generated cache files as a fix. Changes to output schema may also require a cache format or world version update. `build_world.VERSION` and the stage cache format serve distinct compatibility purposes, so inspect their comments and callers before changing them.

## Subsystem map

### Entities, vehicles, and traffic

`src/actors.py` contains entity/body and simulation foundations. `src/vehicles.py`, `src/vehicle_look.py`, and `src/carbody.py` define vehicle data and geometry. `src/driving.py` implements vehicle motion and control behavior. `src/engine_synth.py` and audio systems provide synthesized sound. `src/laneassist.py` and `src/roadwidth.py` centralize lane/road related assistance and dimensions.

Traffic simulation has a separation boundary. `src/trafficproc.py` runs traffic work in a worker process and reconstructs a deliberately reduced simulation/world view. It communicates state through process connections and serializable values. Changes to live simulation types or road graph fields must be checked against the worker reconstruction/serialization protocol, startup/shutdown logic, and recovery paths. `src/traffic_tuning.py` stores tuning. `src/signals.py`, `src/transit.py`, `src/trains.py`, and `src/stations.py` cover traffic control and transport systems.

### People, story, and interaction

`src/characters.py` coordinates character identity and behavior. Character-specific assets and presentation live in `characterart.py`, `faces.py`, `facerig.py`, and supporting art modules. Story/dialogue content is split by role and content type across `hero_lines.py`, `hood_lines.py`, `peds_lines.py`, `dog_lines.py`, `bible_lines.py`, `hero_stories.py`, `hero_profiles.py`, `hero_names.py`, `slang.py`, `texts.py`, and `strings.py`. `src/talk.py` is a runtime interaction point. Read `text/README.md`, `docs/Skopje_slang_bible.txt`, and `docs/TEXT_SOURCES.md` before changing language conventions or sourced text.

World interactions include locations, vendors, services, rentals, work activities, compounds, mall interiors, graffiti, garbage, and breakable chaos. Start from `places.py`, `poi.py`, `poi_vendors.py`, `services.py`, `rentals.py`, `works.py`, `compounds.py`, `mall.py`, or `chaos.py` depending on the feature, then trace main's integration.

New hero wallets use the profile's base amount times ten plus a 3,000-denar floor contribution. Loading restores the saved wallet as-is. The solo HUD shows a 10,000,000-denar cash target. Pump refueling charges for the missing fraction of a representative 45 L tank; the pedestrian fuel POI only offers directions, since the actual refuel is handled by the station interaction. The companion book's campaign multipliers and net-worth ledger are design proposals.

### Rendering, presentation, and world art

`src/render.py` and its imported rendering modules form the runtime drawing stack. `gfx.py`, `gl3d.py`, and `fastrl.py` provide graphics abstractions and optimized native bindings. `src/bake.py` prepares reusable visual data; `src/surfacepack.py`, `src/lightmap.py`, `src/sunshadow.py`, `src/night.py`, `src/smog.py`, and `src/fx.py` cover visual effects or environment behavior. Procedural building and compound helpers include `archkit.py`, `archlib.py`, `facade.py`, `compoundart.py`, and `treegen.py`.

Keep resource lifecycle, coordinate conventions, draw ordering, and batching in mind. For rendering defects, find whether geometry is produced at build time or at runtime before editing. Model and screenshot helpers under `tools/` are useful for inspecting visual output without conflating editor/build behavior with gameplay.

Vehicle gloss in `gl3d.CAR_FS` combines a sky/ground gradient with a seamless direction-space procedural cloud texture, Fresnel clear coat and sun/moon highlights. `gloss_frame` supplies the live day/dusk/night palette; this is a generic environment reflection, not a capture of nearby objects or the visible cloud positions. Matte material tags remain excluded. `tools/car_reflection_shot.py` checks real GPU compilation and produces before/after close-ups for all three lighting periods in `output/car_reflections/`.

The third-person far ring captures each building's own facades and roof for textured prisms, then samples the same captures on depth-correct sprites beyond 600 m on foot/in ground vehicles or 1200 m in helicopters. World version 87 adds per-building mesh spans. See [building LOD rendering](building-lod.md) for capture ownership, range limits, night lighting, cache limits and verification.

The Expanded pack shares one color and height atlas across world and object shaders. Runtime trees use bark detail on wood and foliage detail on solid crown LODs; individual leaf sprites retain their own atlas texture. Mall geometry stores the atlas family in UV.x so floors, walls, fixtures and displays can share one draw while glass and lights skip surface relief. Distant geometry fades the detail to limit shimmer.

### Audio and voice

`src/audio.py` coordinates game audio and generated/cached sounds. Sound building and processing support live in `soundlib.py`, `soundcat.py`, `soundproc.py`, `sfx_synth.py`, `loudness.py`, and `engine_synth.py`. Music selection/playback is handled by `radio.py` and `loadmusic.py`. Voice playback, generation, and speech workers are separated into `voice.py`, `speech.py`, and `voicelab.py`.

Follow the documented asset provenance and mix standards in `docs/SOUND_LIBRARY.md` and `docs/SOUND_LEVELS.md`. Inspect cache keys and generation settings when modifying generated sounds so cached results do not silently mask a change.

### Multiplayer

`src/mpnet.py` handles low-level networking primitives. `src/discovery.py` and `src/joinwords.py` support discovery and human-readable join codes. `src/mp.py` owns session states, players, transport lifecycle, and host/join connection behavior. `src/mpgame.py` owns replicated gameplay state and interpolation. `src/mpprofile.py` holds profile-related multiplayer data. Changes to packet fields or entity replication should be traced end-to-end across encoder, decoder, tick ordering, late/stale packet handling, and tests such as `tools/test_mp*.py`.

## Context lookup recipes

Use these producer-to-consumer paths to locate the complete contract before editing.

| Change request | Trace in this order | Common hidden dependency |
| --- | --- | --- |
| A map feature is missing | Acquisition scripts and `data/osm/` inputs → stage in `tools/build_world.py` → pack/write code → `src/world.py` consumer → render/gameplay consumer | The feature may require a side-list JSON file, a POI kind mapping, or a dedicated stage input declaration for cache invalidation. |
| World build did not rerun | `src/main.py` world freshness checks → `tools/stages.py` fingerprint/stale logic → stage marker and declared data in `tools/build_world.py` | A stage's helper or imported local module is part of the dependency graph. Generated cache state is user/build output. |
| World loads but geometry is wrong | Build producer and coordinate conversion → serialized part writer → `World` load/index/query → collision or renderer consumer | Coordinate handedness, height sampling, chunk indexing, and semantic layer can differ. Identify the layer first. |
| Road graph or AI routing is wrong | Graph stage → runtime graph fields in `src/world.py` → route/traffic consumer → `src/trafficproc.py` reduced worker world | Worker reconstruction can have separate graph-dependent logic. |
| Vehicle handles or collides incorrectly | `src/vehicles.py` dimensions/data → `src/actors.py` physics/collision → `src/driving.py` controls → `src/render.py`/`src/gl3d.py` visual model | Visual dimensions and physics dimensions can be defined separately. Search all `kind`-specific tables. |
| Menu/HUD text is wrong | `TXT("module.NNNN")` call → `text/*.txt` key → `src/texts.py` loader → `tools/check_text.py` | Keep keys stable, retain placeholders, preserve UTF-8 Cyrillic. Some text is matched against OSM or baked into world content. |
| Text appears in world geometry | Text key or source list → build tool reader → stage input declaration/fingerprint → generated sign/poster/world output | Runtime text loading does not update baked signs. Check `text/README.md` for rebuild implications. |
| Setting does not persist | Menu/UI writer → defaults and validation in `src/settings.py` → JSON serialization filter → runtime readers | Exact Python types are validated against defaults. Session-only options intentionally do not persist. |
| Save/restore is incomplete | Simulation capture fields → `src/savegame.py` version and JSON → restore behavior → menu and slot summary | Traffic and pedestrians respawn. Save format changes need compatibility/version handling. |
| Audio change is inaudible or stale | Gameplay caller → `src/audio.py` routing/cache → synthesis/library helper → volume settings → sound audit/docs | Generated cache keys, category gain, and master/category settings all affect output. |
| Multiplayer state desyncs | Gameplay mutation → `src/mpgame.py` serialize/apply/interpolate → `src/mp.py` session → `src/mpnet.py` transport → connection/recovery path | Packet order/tick comparison and local prediction may hide a one-sided protocol change. |
| Rendering regression | State/data producer → `Renderer` draw path → GPU/model/texture helper → present/postprocess path | Resource lifetime, LOD, batching, coordinate transforms, and draw order are frequent causes. |

Hospital helipads are runtime additions in `Sim._make_helis` (`src/actors.py`), rendered by `src/render.py`. Their circular walkable surfaces in `World.pg2` sit 0.18 m above the stored deck height to clear the H marking. Helicopters spawn there, and `_heli_floor` includes `World.plat_h` so they settle on raised decks rather than the roof below. `tools/test_helipads.py` checks all five locations for spawning, parking, landing and departure on ground and raised pads.

### World build stages at a glance

Current markers in `tools/build_world.py` establish stage ownership. Recheck names and inputs in source after pipeline edits.

| Stage | Main concern |
| --- | --- |
| `map` | Read map elements and terrain source, establish normalized/projected feature data. |
| `bmesh` | Build building geometry and related mesh output. |
| `graph` | Derive road/routing graph and map connections, with POI and bus-stop data. |
| `props` | Generate local props and environmental details. |
| `furniture` | Signals, stops, street furniture, and side lists. |
| `leisure`, `monument`, `construction`, `stations` | Dedicated place and infrastructure additions. |
| `fill`, `cleanup` | Fill remaining urban lots and normalize/remove invalid output. |
| `rail`, `roads3d` | Rail and detailed road geometry. |
| `rasters`, `escapes`, `index` | Surface/raster products, traversal escape routes, and spatial indexes. |
| `write` | Emit final runtime world files and manifest from stage products. |

Exact dependencies are expressed by `stage(name, data=...)` declarations and code analysis in `tools/stages.py`. For a data file to invalidate a stage, verify it is declared or included by the runner's broader fingerprint rules.

## Data contracts and compatibility

### World files

`src/world.py` declares semantic part names and validates manifest-recorded file sizes before loading. `tools/build_world.py` writes the format and world version. `tools/pack_world.py` includes manifest-listed files plus an explicit set of OSM inputs consumed at runtime. Pack format and world version metadata are distinct, and `tools/world_pack.json` carries release download metadata and a digest. When touching a world file, inspect stage output, writer/manifest, runtime loader, packer, and downloader. A local world can work while a distributable pack omits a required file.

### Text files

`src/texts.py` loads all `text/*.txt` entries by stable key. Format, escapes, placeholders, source annotations, and validation are in `text/README.md`. `tools/check_text.py` checks syntax and code references. Preserve numeric keys. Check for `WARNING: lookup` before rephrasing strings compared with map/data names. Build-baked text needs a world refresh or corresponding asset-generation step.

### Settings and saves

`src/settings.py` constructs defaults, reads `settings.json`, admits known keys whose values have the expected Python type, bounds selected values, and writes atomically via a temporary file. Session-only fields are omitted. This is user state and must not be committed.

`src/savegame.py` stores a selected subset of simulation state in `saves/slot<N>.json`. Saves carry a version and are written through a temporary path then replaced. Traffic and pedestrians respawn by design. Verify capture, validation, restore, reset, and UI summary when changing save behavior.

### Geometry and units

`src/geo.py` uses a local equirectangular approximation centered at Skopje (41.9973, 21.4280), with local +y south. Its constants align with `tools/geo.py`. Runtime position tuples often distinguish planar x/y from vertical height h, while graphics code may name vertical axes differently. Never infer axis meaning from `z` alone. Check function signatures and transforms.

## Common verification entry points

| Concern | First check |
| --- | --- |
| Text key coverage and syntax | `python tools/check_text.py` |
| Slang/content conventions | `python tools/check_slang.py` and `docs/Skopje_slang_bible.txt` |
| Road network/data integrity | Relevant `tools/road_audit.py`, `tools/network_audit.py`, `tools/joint_audit.py`, or focused audit |
| Traffic simulation behavior | `tools/test_traffic_recovery.py`, traffic audits, then traffic lab for scenario-level issues |
| Multiplayer behavior | Narrow `tools/test_mp*.py` script and both ends of encode/apply path |
| World stage output | Stage-specific audit/render script and cache fingerprint/status |
| Runtime visual behavior | `run.bat demo` for demo-only issues, otherwise affected world and screenshot tools |
| Surface texture pack layout | `src/surfacepack.py` family/variant constants and `assets/textures/expanded/README.md` |
| Sound content | `tools/sound_audit.py`, `tools/test_soundproc.py`, and standards in `docs/` |

These are entry points, not a promise every script is side-effect free. Read arguments first. Some tools download data, rewrite caches, launch windows, or emit screenshots.

## Tools and experiments

`tools/` is an operational codebase of its own, not merely scripts. It includes source fetching, world generation, geometry and road design, content audits, performance capture, and screenshot workflows. `tools/trafficlab/` separates traffic simulation, parameters, exploration, batch execution, reports, tips, and UI. `tools/roadvault/` is a distinct road/interchange design and fitting toolkit. Use the local README and rules in those packages before extending them. The road candidate there shares one geometry compiler between reviewed layouts and OSM inference. See [the road vault guide](../tools/roadvault/README.md) for inputs, review diagnostics, and the Partizanski–Glavinov regression fixture.

Files in `drafts/` can contain experiments or migration patches and are not automatically production guidance. Check whether a draft is referenced by shipped paths before relying on it.

## Project conventions and methodology

- Keep changes narrow and follow existing module boundaries. Reuse local functions, representations, and formats before adding new abstractions.
- Trace data from producer to consumer. For serialized worlds, network packets, generated audio caches, or save data, inspect both sides of the boundary and compatibility/version logic.
- Treat per-frame performance, process ownership, and main-thread graphics constraints as architecture, not incidental details.
- Keep language content and authored asset choices consistent with project references. Preserve Macedonian Cyrillic and established terminology.
- Prefer deterministic procedural generation where reproducibility matters. Keep random seeds tied to stable inputs when the surrounding implementation does so.
- Use narrow diagnostics and audit scripts where they exercise the affected interface. Check the script's side effects before running it.
- User state and generated products are not source. Never commit `settings.json`, `saves/`, `tmp/`, `output/`, or generated world data.

## Repository map

- `src/`: runtime game code and shared runtime helpers.
- `tools/`: world generation, data acquisition, audits, profiling, screenshots, and traffic/road applications.
- `data/`: map inputs, world metadata, and related data. Inspect exact subdirectories locally because they can include large generated files.
- `assets/`: images, models, UI, and other bundled assets.
- `text/`: player-facing text source and content notes.
- `library/`: audio and reference library, including generated cache metadata.
- `docs/`: asset source references, style rules, manuals, and visual records.
- `drafts/`: experiments and work in progress.
- `run.bat`, `requirements.txt`, `make_exe.bat`: setup, launch dependencies, and packaging.

## Agent workflow

1. Start with `AGENTS.md`, this index, and the closest feature source.
2. Trace the actual entry point, interfaces, state ownership, and persistent formats involved.
3. Implement the smallest complete change while preserving existing callers and saved/build data compatibility.
4. Verify through the normal feature path or the narrowest suitable diagnostic. Inspect diff and status.
5. Refresh this guide only when facts, pointers, or durable design decisions change.

Repository sync instructions are in `AGENTS.md`. Current source takes precedence over every summary here.
