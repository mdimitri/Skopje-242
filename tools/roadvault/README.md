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
chain. Parallel turns share a Bézier alignment. Each slip traces its
approach lane to the split before blending into the mapped guide. A short
arclength filter eases curvature changes at the guide splices. The
approach from the west holds its inner lanes beside the slip
until the diverging paths have clearance. Vehicle envelopes complete the central apron,
with a bound on how far the movement centre lines can leave the mapped
road strips. Carriageway edges in the layout specify 2.4 m raised outer
sidewalks and 0.32 m median-side curbs. Median noses and island returns
follow the final asphalt outline, with openings at crossing landings.
Both slip lanes have raised pedestrian refuge islands. The larger northern
refuge is selected by its interior point so it can use the same surface and
curbs, with its sharp tips rounded into the adjoining asphalt.
At the southbound merge, the outer sidewalk also follows the final asphalt.
Mapped grass selects which divided-road medians are planted. The resulting
grass follows the generated curb enclosure and leaves pedestrian landings clear. Only designated crossing landings open the
median to pedestrians. Each zebra spans the paved cross-section at its
authored station, and signal stop lines are derived from those stations.
Lane arrows use mapped turn indications with the movement graph as a fallback.
Shark teeth mark both slip entries into the receiving carriageways. The
south approach’s left-turn pocket opens on the preceding way and
keeps the existing two lanes at full width through the opening taper,
leaving about 25 m of full-width queue space before the stop line.
The crossing groups follow the reference imagery approximately. OSM footways
can feed an existing sidewalk. The junction's road-owned walking surfaces
compile independently of them. Walkable surfaces and visual curbs are
separate polygons under `pedestrian` in the exported network.
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
- Crossing approaches connect sidewalks and use cut-throughs at designated
  median refuges. [FHWA intersection design guide](https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2022-06/fhwasa22017.pdf),
  [FHWA pedestrian refuge islands](https://highways.fhwa.dot.gov/safety/proven-safety-countermeasures/medians-and-pedestrian-refuge-islands-urban-and-suburban-areas)
