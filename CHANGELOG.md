# Changelog

## v1.2 – collisions, combat and rewards

- **Collisions:** every car has an oriented 2D box (SAT) with a bounding-circle test and a 16 m grid as broadphase, so crashes work at any angle, including T-bones and long buses; traffic brakes for cars crossing sideways; you can no longer walk through cars (exact box vs. circle push-out).
- **Punch the street:** bins, bollards and other small props fly away, bigger ones break, lamp posts fall to a kick; explosions break and throw props, push people and wrecks and hurt you; burning cars set neighbouring cars on fire and chain-explode (wrecks go after 20 in-game minutes).
- **Fight animation:** the punching arm and the kicking leg are the real limbs (no extra limbs on top any more).
- **Денари for mayhem:** punches, kicks, smashed props, car hits, running people over and explosions pay.
- **Chasers give up** when you get about 22 m away for a few seconds (or 45 m at once).
- **First responders:** more and closer ambulances / fire engines (3 jobs each, 420 m); firemen spray with the hose out while the flames die down, burning wrecks keep burning until they arrive; medics kneel over the patient and do CPR.
- **Traffic:** a junction with 3+ stuck cars for 30 in-game minutes is clogged and nothing new spawns into it until it clears.

## v1.1 – polish and 3D splash

- **3D loading splash:** endless street with the game's own buildings, furniture, cars and characters, jokes and sun shadows.
- **11 new characters (likovi):** administratorka, bilder, boza, burek, fitka, nastavnica, navivac, palavko, shmizla, srednoskolec, vojnik; extended showcase and hero lines.
- **Round 15:** you start as a walker beside your car (`--car` starts inside it); the first neighbourhood is not announced; pop-ups and banners stay as long as their text needs; dead-end roads within 7 m are joined to nearby roads (world version 11, rebuilds automatically).
- **Fixes:** standing on a bridge deck no longer counts as being in the river; crash when teleporting fixed; culling fix so people and cars are not drawn as bare shadows; the whole-city overview model is only drawn when a ground chunk is missing; shared, budgeted car models and freed dented-car models.

## v1.0 – first public version (all work so far)

- **Round 1–2:** top-down raylib prototype of Skopje from OSM; procedural buildings, trees, traffic, pedestrians; 59 vehicles, 39 road users, kiosks, pickups, slang signs and graffiti.
- **Round 3:** 3D roads with markings and crossings, day/night cycle and lighting, fighting, jumping, hijacking, synthesised sound and speech.
- **Round 4:** 11×7 km map, real terrain and slope physics, bridges with decks and falling, ambulance and fire brigade, options menu, neighbourhood names.
- **Round 5:** everything in Macedonian Cyrillic; download splash with a live map of pieces and honest speed; hardened downloads with mirrors and timeouts; Geofabrik PBF route; joke posters.
- **Round 6–8:** car radio (open-licence songs, shuffle, static); Suze voice as the only voice (RHVoice via SAPI).
- **Round 9–10:** working traffic lights with a green wave, smog, real projectiles and weapons, bullet holes and scorch marks.
- **Round 11–13:** kerbs and breakable props, hero avatars with 52 lines each, real bus stops, JSP buses on real lines that you can ride or take over, kids at playgrounds and school yards.
- **Round 14:** quit confirmation, `L` character switch, per-speaker Suze profiles, "people with problems" lines, showcase splash (cars and characters).
- **Settings and saves:** tabbed settings menu, save / load slots, character select.
