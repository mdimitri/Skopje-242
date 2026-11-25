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
It writes plan, oblique, street-level and lane movement renders to `output/road-candidate`,
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
Both outer slip-lane sidewalks follow continuous blends of the finished
asphalt edge through the split and merge.
Mapped grass selects which divided-road medians are planted. The resulting
grass follows the generated curb enclosure. Paired zebras cut through the
planted median at road level, with rounded openings and curb returns on
both sides. The cut-throughs are included in the network's pedestrian
surfaces. On sidewalks and refuge islands, only curb ramps need separate
geometry. The paved surface is continuous across internal walking routes. Each zebra spans the paved cross-section at its
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
Each signalized approach with two or more inbound lanes gets a two-post
portal upstream of the stop line, with one head centered over each lane
and a roadside repeater past the zebra. The preview leaves 5.1 m under
the suspended housings and keeps both supports outside the road and
crossing entries. It places pedestrian heads at both ends of each of the six controlled zebra sections.
The slip crossings use crossing signs and the slip merges use give-way signs.
Signal-ahead warnings and keep-right signs mark the main approaches. The
placement is a proposal anchored to the generated road and crossing geometry.
The exported `traffic_furniture` records supports, lane heads and facing directions.
Signal heads show a static all-red preview. World-builder integration,
signal timing and runtime routing require separate work. The conflict list describes overlapping vehicle envelopes,
including merges and shared lanes. It supplies no signal timing.

### Applying the same rules to other OSM sites

```powershell
.runtime/venv/Scripts/python.exe tools/roadvault/run_candidate.py --infer 41.99815 21.42544 --radius 95 --out output/road-candidate-kliment
```

`road_inference.py` prepares a layout from the local OSM graph. The inferred
and authored layouts use the same geometry compiler. Inferred builds export
an editable `layout.json`, its review diagnostics, and the original OSM way
ID for every edge. Replay the layout with `--layout <path>` and the same
`--osm` extract. The default command builds the verified Partizanski–Glavinov
layout, including its reviewed lane assignments, tapers, refuge geometry,
crossing stations and furniture.

| Design rule | Evidence and behavior |
| --- | --- |
| Connect lanes before drawing the apron | Shared OSM nodes define topology, including nodes inside a way. Directions, turn lanes and direct via-node restrictions constrain movements. Candidate curves must fit near the mapped carriageways. |
| Keep lanes ordered through forks | When one mapped link and the mainline consume the inbound lane count, reserve the lanes on the link side. Urban one-way slip lanes get an outer sidewalk. Recognized right-hand slips can share a blended outer sidewalk edge. The blend is withheld if it would cut into a swept lane. |
| Keep sidewalks on the outside of a divided road | Opposing parallel one-way ways with matching names or refs and enough room for a median get inside curbs. The median is protected from inferred turn envelopes and junction rounding, and mapped grass selects planted medians. OSM footways can join the road-built sidewalk. |
| Connect paired crossings at street level | Tagged crossing geometry supplies the crossing positions. Nearby opposing zebra stations are aligned across the median and use the same rounded, flush break as the reference junction. Enclosed slip refuges get rounded tips. |
| Tie signals to the approaches they control | Mapped one-way signal approaches with a nearby zebra can supply stop lines, pedestrian heads and portals. Other signal positions are flagged for placement review. |
| Provide useful turn-lane storage | A single-lane width change on a clear one-way continuation gets a taper up to 25 m. Other changes are reported for review. The authored pocket supports the 25 m target at Partizanski–Glavinov; the inference pass needs room and traffic evidence before adding a pocket. |

The input is the game's local, right-hand-traffic, at-grade preview. A combined
`roads.json` can include OSM nodes and relations; `restrictions.json` is also
accepted. The shipped way-only extract lacks turn relations and most tagged
crossing nodes, so an inferred preview can differ substantially from the
authored site. Grade separation, complex via-way or conditional restrictions,
lane connectivity relations, and control placements without enough evidence
are reported for review. The fixture remains the reference for a divided,
signalized T with two slip lanes.

World builds use this compiler by default for ground-road surfaces and markings.
`tools/roads_candidate.py` feeds it the cooked road graph and mapped crossings
and medians, then clips the result into tiles for terrain draping. A matching
Glavinov extract uses the reviewed layout in the junction core. The candidate
exports gantries, repeaters, pedestrian heads, signs, stop lines and crossings
from the same layout used to draw the road. The game lights the baked heads
through separate vehicle approach and pedestrian phases. Inferred signal
placement depends on mapped controls and crossings that fit the layout.
An invalid tile can fall back to
the previous junction designer, with the tile and reason logged. The
`SK242_DESIGNER=0` build switch still selects the original ribbon builder.

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

- Signal faces and sign symbols use the Vienna Convention as a visual
  reference. [UNECE Convention on Road Signs and Signals](https://unece.org/DAM/trans/conventn/Conv_road_signs_2006v_EN.pdf)
- Overhead head placement and clearance use the signal mounting diagrams as
  a geometric reference. [FHWA traffic control signals](https://mutcd.fhwa.dot.gov/pdfs/11th_Edition/part4.pdf)

- OSM inference follows the source distinction between connectivity, lane
  indications and turn restrictions. [OSM turn restrictions](https://wiki.openstreetmap.org/wiki/Relation:restriction),
  [OSM lane connectivity](https://wiki.openstreetmap.org/wiki/Relation:connectivity),
  [SUMO OSM import and lane inference](https://sumo.dlr.de/userdoc/Networks/Import/OpenStreetMap.html)
