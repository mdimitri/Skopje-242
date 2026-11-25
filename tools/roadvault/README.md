# Road vault

Parametric library of road pieces, built fresh (not on junction_net/roads3d).

- `engine.py`: Scene/Arm/Ring -> mesh (asphalt, kerbed pavements, islands, slip lanes, paint, signals, cars, shadows)
- `grade.py`: overpasses/underpasses as ribbons with height profiles
- `elements.py`: 241 extra design elements (posts, furniture, signs, lighting, planting, gantries, barriers, markings, calming, transit, pedestrian, utilities)
- `catalog.py`: the 100 most common types (`make(id, **overrides)`)
- `typelib.py`: 10,000 stratified types out of ~3.3M valid parameter combinations (`python typelib.py out.json`)
- `run_all.py` / `gallery.py`: render the catalogue / the element gallery (`xvfb-run -a python ...`)

Previews come from this engine's own builder, not roads3d.

## Lane-based road candidate

`road_candidate.py` is an independent at-grade compiler. Start with
`partizanski_glavinov.json`, which records the divided junction of
Partizanski Odredi, Vasil Glavinov and Boulevard Blaže Koneski around
[OSM node 418949594](https://www.openstreetmap.org/node/418949594).
It uses the same mesh and renderer as the other vault tools.

```powershell
.runtime/venv/Scripts/python.exe tools/roadvault/run_candidate.py
```

The runner reads the local OSM road and area extracts under `data/osm`.
It writes plan, oblique and lane movement renders to `output/road-candidate`,
along with a vertex-colour triangle mesh (`mesh.npz`) and explicit lane
connections and swept-envelope conflicts (`network.json`). Use `--no-render`
for headless compilation. Coordinates are metres east and south from the
design's latitude and longitude, with up as the second axis in the mesh.

The compiler builds cross-sections from lane and width tags, sweeps their
boundaries along interpolated centre lines, and uses authored split and
merge tapers. Movements validate the direction, lane indices and OSM node
chain. Parallel turns share a Bézier alignment. The slip lanes preserve
their mapped guide curves. Vehicle envelopes complete the central apron,
with a bound on how far the movement centre lines can leave the mapped
road strips. Mapped paths and grass and the footprint's enclosed refuges
produce separate raised surfaces. The layout records the proposed movement
assignments, stop lines and crossing locations as site-specific design inputs.
The candidate is a flat preview with illustrative signal heads. The world
builder, runtime routing, traffic signals and editor would need separate
integration. The conflict list describes overlapping vehicle envelopes,
including merges and shared lanes. It supplies no signal timing.

Research references

- Road Builder separates the editable network configuration from its
  generated cross-section and node states and preserves IDs when loading
  designs. [Prefab generation](https://github.com/JadHajjar/RoadBuilder-CSII/blob/main/RoadBuilder/Utilities/NetworkPrefabGenerationUtil.cs),
  [serialization](https://github.com/JadHajjar/RoadBuilder-CSII/blob/main/RoadBuilder/Systems/RoadBuilderSerializeSystem.cs)
- The public road tool diary and mod source describe separate selection,
  upgrades and placement workflows. [Colossal Order road tools](https://www.paradoxinteractive.com/games/cities-skylines-ii/features/road-tools),
  [Road Builder tool](https://github.com/JadHajjar/RoadBuilder-CSII/blob/main/RoadBuilder/Systems/RoadBuilderToolSystem.cs),
  [Realistic Road Works](https://github.com/jasperaelvoet/realistic-road-works)
- The lane graph uses explicit incoming and outgoing lane indices and
  models intersecting movements separately from carriageway meshes.
  [ASAM OpenDRIVE lane links](https://publications.pages.asam.net/standards/ASAM_OpenDRIVE/ASAM_OpenDRIVE_Specification/v1.8.1/specification/12_junctions/12_04_connecting_roads.html),
  [SUMO internal junction lanes and conflicts](https://sumo.dlr.de/docs/Networks/SUMO_Road_Networks.html),
  [OSM lane order and turn markings](https://wiki.openstreetmap.org/wiki/Key:turn)
