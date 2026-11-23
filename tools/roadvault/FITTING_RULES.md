# Satellite fitting rulebook (living document)

Source: p1 satellite review, 132 sites (bridge_end 21, long_bridge 8, main_cross 20, ramp_junction 78, underpass 5).
Panels show: satellite | satellite + OSM | top view | side view. Renders are the OSM network run through the
vault corridor engine (not the game's roads3d, and not yet a matched vault design).

## Evidence rules (what to trust, in order)
1. Satellite pixels for where asphalt is and how wide it is (lane count = paint lines / car rows).
2. OSM for topology, class, one-way, bridge/layer and names.
3. Traffic rulebook and common sense to settle conflicts (below).
4. Vault families only after 1-3 agree on what the junction type is.

## Learned so far
- Georeferencing holds: OSM centrelines land within a few metres of the visible asphalt (150 m frames, 0.19 m/px). Offsets
  larger than ~5 m mean OSM is wrong, not the image.
- OSM often under-states width on ramps and dual carriageways. Satellite shows 2-3 lanes per carriageway on the main
  boulevard sites (ramp_junction_0032, 0033) where OSM tags give fewer. Rule: take lane count from satellite car rows/paint
  when it disagrees, but never below the OSM tag.
- Purple (service/residential) OSM lines that run through yards, vegetable plots or empty lots (main_cross_0014, 0017, 0019)
  are usually unpaved tracks or private yards. Rule: demote unpaved or private service ways to track/path, no kerbs, no lines.
- Yellow dual-line primaries are two separate one-way carriageways with a median; keep the gap the satellite shows, do not
  merge them into one wide road.
- Small ring roads at service junctions are real (ramp_junction_0033 roundabout) and need island + give-way, not a plain loop.
- Ramps leave the carriageway tangentially and join it with a taper; OSM draws them as sharp T links. Rule: replace any OSM
  ramp that meets a carriageway at >25 degrees with a tapered merge (vault merge kinds on_taper/off_taper, 60-100 m).
- Bridge ends (bridge_end_*) need a ramped deck with abutment, not a step: OSM layer flips at one node, the real grade starts
  80-150 m earlier.
- Right-hand traffic: entry ramps merge on the right, exits leave on the right, loops turn clockwise for right exits.
- Footways and cycleways that duplicate a carriageway edge in OSM are the pavement, not a second road; drop them.

## Renderer notes
- Satellite-review renders have no trees (notrees flag) because only roads matter here.
- The side view is a low far camera: only useful on bridge/underpass sites. Flat at-grade sites look empty from the side.
  Next version should pick the side camera nearer and aim at the highest deck.

## Not built yet
- The actual fit step (choose family, lane counts, radii per site and render the matched design next to the OSM render).
- p2 sites (259) are not staged yet.
