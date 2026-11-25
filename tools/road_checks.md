# Road network quality checks

The catalogue the road audit (`tools/road_quality.py`, in progress) runs on every build sample. Each check has an id,
what it measures and the limit. A finding feeds back into the graph clean-up (`tools/roadclean.py`) or the junction
designer (`tools/junction_net.py`); the loop repeats until the sample is clean. Limits follow common European urban
road design practice, scaled for a game.

## A. Network shape (graph)
- A01 junction clusters: no two junction nodes closer than the paved area of their junction (merged softly)
- A02 short links: no drivable link shorter than its two junction boxes plus 2 m that is not merged
- A03 arm angle: arms meet at 70–110° where the geometry allows; a skew under 45° becomes a slip or Y layout
- A04 arms per junction: at most 5; 6+ is split into two junctions or a roundabout
- A05 straight approach: every arm is straight for its marking length (setback + stop line + arrows)
- A06 dual carriageways: one-way pairs within 40 m run as a boulevard pair with a constant median
- A07 median width: boulevard median 2–12 m, eased; under 1.5 m becomes a painted median or a barrier
- A08 frontage roads: a parallel service lane closer than 6 m to a main carriageway is merged or given a planted separator
- A09 loops: no self-loop edges; long loop ramps keep two distinct nodes
- A10 dead ends: every dead end of a two-way road gets a turning bulb sized to the road class
- A11 one-way traps: no node from which a car cannot leave legally
- A12 islands of the graph: no drivable component unreachable from the main network
- A13 duplicate geometry: no two edges overlapping for more than 5 m
- A14 tiny edges: no edge under 3 m outside a junction box
- A15 bridges: each bridge chain carries its approach road's lanes per direction
- A16 bridge ends: no junction on a deck end; a ramp meets a deck as a merge or diverge
- A17 merges and diverges: one-way splits and joins are tapers with a gore, never a marked junction
- A18 roundabouts: consistent ring direction, ring lanes 1–2, entries at least 25° apart
- A19 class continuity: a road does not change class back and forth along its length
- A20 speed continuity: speed limit changes at junctions only, never mid-block more than once

## B. Lanes and widths
- B01 lane width standard: 3.25 m urban, 3.5 m arterial and ramps; every lane on ground, ramp and deck alike
- B02 width continuity: a lane keeps its width across every join (0.05 m tolerance)
- B03 lane count changes: only inside a taper zone
- B04 taper length: at least 15 m per 1 m of lateral shift (eased, no kink)
- B05 lane caps: apply class caps only when OSM has no lane count; explicit OSM lane counts and directional splits are preserved
- B06 opposite arms: the two arms of one road through a junction carry the same lanes, or a taper before the box
- B07 turn pockets: a left-turn pocket opens with a 20–30 m taper and is 30–60 m long
- B08 bus bays: 3 m wide, 15 m tapers in and out
- B09 parking lanes: 2.0–2.5 m, never inside a junction box or on a bridge
- B10 bike lanes: 1.5–2.0 m, continuous across junctions with dashed red markings
- B11 no orphan lanes: every lane connects to a lane at both ends or to a defined start/end taper
- B12 lane arrows match connections: an arrow only where that movement exists
- B13 minimum carriageway: two-way roads at least 2 lanes wide (6.5 m); one-way at least 3.5 m
- B14 shoulder/edge: 0.3–0.5 m between the edge line and the kerb

## C. Junction layout
- C01 box size: the junction box is no larger than the curb-return fillets require
- C02 corner radii: 6 m residential, 9 m tertiary, 12 m primary, 15 m with buses or lorries
- C03 fillets: curvature-continuous kerbs, no kinks
- C04 median noses: boulevard medians reach the crossing with a rounded nose, 1.0–1.5 m back from the zebra
- C05 refuges: a crossing longer than 2 lanes each way has a refuge at least 2.0 m deep
- C06 splitter islands: on minor arms of large junctions, at least 10 m² and with a nose
- C07 slip lanes: a free right turn has a triangular island at least 20 m² with its own zebra
- C08 no slivers: no island under 6 m², no asphalt sliver under 1 m wide
- C09 no wasted asphalt: a paved area a car never uses inside the box is an island (hatched or kerbed)
- C10 gore areas: hatched chevrons at every merge and diverge
- C11 sight triangles: no tree, sign or building in the sight triangle of a give-way arm
- C12 skewed arms: an arm meeting under 60° is realigned to meet near 90° within 30 m
- C13 offset arms: two minor arms facing each other offset by under 15 m are aligned
- C14 junction spacing: signalised junctions at least 60 m apart; closer ones are one junction
- C15 roundabout geometry: inscribed diameter by class, entry deflection, splitter islands on every arm

## D. Markings
- D01 zebra placement: 1–2 m back from the corner tangent, square to the kerb
- D02 zebra continuity: both ends of every zebra reach a pavement or a refuge with a kerb ramp
- D03 no zebra on a deck end, a merge or a diverge
- D04 no zebra to nowhere: a crossing exists only where a walking route continues on both sides
- D05 stop line: 1–2 m before the zebra, across the inbound lanes only
- D06 give-way line: minor arms without signals get a dashed give-way line and a triangle
- D07 solid lane lines: 30 m before a stop line, dashed beyond
- D08 centre line: double solid near junctions and bends, dashed on straight sections
- D09 edge lines: continuous along the carriageway, broken at junction mouths and bus bays
- D10 arrows: two rows per inbound lane on arms longer than 40 m
- D11 no overlapping paint: no two markings overlap; no marking crosses a kerb or island
- D12 no paint fragments: no line piece shorter than 2 m outside dashes
- D13 turn guides: dashed guide lines through junctions with offset or double turn lanes
- D14 bike crossings: red with dashed edges where a cycleway crosses
- D15 bus stops: "BUS" marking and zig-zag at each stop
- D16 school zones: marked where OSM has a school within 100 m
- D17 bridge markings: decks carry the same lane, edge and centre lines as their approaches
- D18 no markings in turning bulbs, gores or hatched areas except the hatch itself

## E. Kerbs, pavements, walking
- E01 pavements everywhere: both sides of every road, every deck and every underpass trench
- E02 pavement width: at least 2.0 m clear, 3.0 m on arterials
- E03 no inner pavement on twin decks: only the outer side of each deck
- E04 kerb height: 0.15 m, continuous
- E05 kerb ramps: at every zebra end, at most 8% slope, with tactile paving
- E06 refuges: flush cut-through at the zebra, kerbed around
- E07 obstacles: no pole, sign, lamp, bin or tree within the 1.5 m clear walking width
- E08 continuity: the pavement network has no gap over 0.3 m and no dead end except at buildings
- E09 crossing length: no unbroken crossing over 4 lanes; add a refuge
- E10 detours: a walker never needs to detour more than 1.5x the straight distance to cross at a junction
- E11 pavement crossfall: 1–2% toward the road
- E12 level pavements on slopes: the pavement keeps the road level across its width; a concrete fill below meets the terrain
- E13 steps: a walking route steeper than 8% uses stairs or a ramp with landings
- E14 underpass/overpass paths: lit, at least 2.5 m wide, 2.5 m headroom
- E15 bus stop platforms: kerbed, 2.5 m deep, shelter clear of the walking width
- E16 driveway crossings: dropped kerb, pavement level kept

## F. Driving
- F01 turn radius: every legal movement has a path radius above the class minimum (8 m local, 12 m arterial)
- F02 swept path: no kerb, island or pole inside the swept path of a car or bus on any legal movement
- F03 lane continuity: a car never finds its lane ending without a taper or an arrow announcing it
- F04 merges: an acceleration lane at least 60 m on arterials
- F05 diverges: a deceleration lane at least 40 m
- F06 stop line visibility: the stop line or signal is visible 50 m ahead at the approach speed
- F07 decision distance: no stop line within 25 m after the previous junction's box
- F08 conflicting arrows: no two lanes with crossing turn arrows
- F09 U-turns: only where marked; never through a gore
- F10 wrong-way traps: no legal path leads into a one-way against its flow
- F11 signal phasing: every signalised movement belongs to a phase; no conflicting greens
- F12 speed changes: speed limit drops of more than 20 km/h get a warning sign 50 m before
- F13 bridge joins: no lateral jump over 0.1 m in lane centre between deck and ground
- F14 lane centre smoothness: curvature continuous along every lane; no heading jump over 3° per 2 m
- F15 junction clearance: a car fully clears the box before the next stop line

## G. Vertical profile, camber, roughness
- G01 crossfall (camber): 2–2.5% on straights, toward the gutters
- G02 superelevation: up to 6% on curves by design speed; smooth run-in over at least 20 m
- G03 crossfall flips: no change from left to right fall faster than 0.5% per metre
- G04 grade limits: arterials 6% or less, local streets 10% or less, ramps 8% or less, decks and approaches 5% or less
- G05 vertical curves: crest and sag curves sized so the grade changes at most 1% per 10 m on arterials
- G06 sight over crests: stopping sight distance kept over every crest
- G07 roughness: at most 3 cm deviation under a 3 m straightedge on any lane
- G08 steps: no height step over 1 cm between road pieces, tiles or deck joins
- G09 junction box flatness: grade inside the box 3% or less
- G10 drainage: no flat sag without a gully; pavements and medians shed water to the road
- G11 headroom: 4.6 m under decks over roads, 3.0 m over paths, 5.0 m over rail with catenary
- G12 deck ends: approach slab, no grade break over 2%
- G13 cuttings: retaining walls or slopes at 1:1.5 or less; no stepped terrain beside a road
- G14 embankments: slopes 1:2 or gentler, or walls with a parapet
- G15 terrain contact: the ground meets every kerb, wall and pavement edge with no gap or overlap
- G16 pavement level: pavements never tilt more than 2% across, even on cross-slopes (fill below instead)

## H. Structures
- H01 decks: abutments at both ends, wing walls, expansion joints, parapets on outer edges
- H02 piers: spacing 20–40 m, never in a lane or on a pavement below
- H03 soffit: clean underside, at least 0.8 m deep, lit underpasses
- H04 twin decks: a median barrier between, no inner pavements
- H05 underpasses: retaining walls, a roof slab, lighting, drainage, pavements on both sides
- H06 deck width: equals the lanes it carries plus pavements and parapets, no more

## I. Furniture and signs
- I01 street lamps: every 25–35 m on arterials, 35–45 m on local streets, staggered on wide roads, on decks too
- I02 signals: one primary head per approach at the stop line; mast arms over boulevard lanes; pedestrian heads at both zebra ends
- I03 signs: give-way or stop on minor arms, priority road on major, pedestrian crossing at zebras, speed at changes
- I04 lane signs: overhead lane signs on 3+ lane approaches to big junctions
- I05 street names at every junction corner
- I06 bollards: on refuges and splitter noses
- I07 guard rails: on embankments over 2 m and on ramps
- I08 trees: median trees on boulevards wider than 4 m, pavement trees where the pavement is wider than 3.5 m, never in sight triangles
- I09 bins and benches: at bus stops and every 100 m in centres
- I10 no furniture in lanes, crossings, kerb ramps or swept paths

## J. Visual quality
- J01 even asphalt tone per road; patches only by design
- J02 no z-fighting between layers anywhere
- J03 no visible tile seams
- J04 no floating or buried geometry
- J05 kerbs and markings line up across tile and chunk borders
- J06 every element passes "would a road engineer build it this way?"; out-of-place elements are flagged for review
