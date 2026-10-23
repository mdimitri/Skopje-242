# Changelog

Screenshots: new 3D splash (`splash.jpg`), 24-avatar character select (`select.jpg`), roads (`roads.jpg`), night headlights (`night.jpg`), weapons (`weapons.jpg`), POI shop menu (`poi.jpg`), selfie sky (`selfie.jpg`), driving, kiosk and Vardar, all from the real game at 1280x720.

## v2.0 – walking, bumping, muffled car music, joined roads

- **Walk cycle (final):** eight-phase stride cycle with cosine limb swing at real cadence (one stride per ~1.5 m walking, ~2.6 m running); arms hang down when standing; arms holding a prop swing with it. Refreshed screenshots (drive, kiosk, roads, night) from the real map.

- **Walk animation:** longer strides, bigger leg and arm swing and a forward lean (strong when running) for the avatar and pedestrians, so the heading reads from above.
- **Speech:** your avatar only talks when you press `H` on foot. New menu row "Колку често зборуваат пешаците" (0.1x–2x, default 1x = as before).
- **Bumping:** walk into a pedestrian and they grumble, insult you, threaten you ("ќе ти врзам шамар", "гитла бе", "мрш", "фаќај магла" ...) and after a few bumps fight you. Lines depend on the character type (`src/bump_lines.py`).
- **Cars:** about 1 in 10 traffic cars plays the music from `music/` inside the cabin; only one at a time is heard, low-passed (muffled) and quiet. Nearby traffic now has an engine hum.
- **Combat:** much more ammo per pickup; a swung bat also smashes props; animated score pop-ups (sparks, bigger and hotter numbers for bigger payouts).
- **Roads (world version 12, rebuilds automatically):** roads that continue, bend, widen or narrow share one cross-section (same vertices, smooth width taper); pavements join into curved corners at junctions; tiny height offsets stop coplanar road pieces from z-fighting (flicker).

## v2.0 – slang bible

- All pedestrian talk now draws on `docs/Skopje_slang_bible.txt` (421 terms): `src/bible_lines.py` has per-character-style lines (old, woman, kid, tough, posh, youth, sport, priest, vendor, cop) for idle, hit, panic, fight, KO and the bump escalation, plus topic pools, neighbourhood lines and extra lines for all 24 playable characters.
- Language level 2 ("Без цензура") is now unhinged: much more and much harsher cursing, adapted to the character.
- `python tools/check_slang.py --missing` shows which bible terms the game text does not use yet.
- Limbs are rigged: legs swing from hip and knee, arms from shoulder and elbow, four-pose walk cycle and a bigger run cycle.

## v1.2 – collisions, combat, shops and radio

- **Collisions:** oriented-box (SAT) collisions for every car with a grid broadphase; traffic brakes for sideways cars; exact walker-vs-car push-out; careful driving.
- **Chaos:** punchable props that fly and break, blast waves, chain fires and explosions between cars; punches and kicks use the real limbs.
- **Money:** rewards for punches, props, car hits, run-overs and explosions.
- **Shops and places (POI):** walk in to cafes, food, schools, health, worship, fuel, banks, markets, police and more via 1–4 menus, with spoken lines.
- **Selfies** (`P`), weapon models, more road detail.
- **Radio:** plays local music from `music/` with station switching (`Q` / `E`); no more radio downloads.
- **Services:** reworked first responders (spray pose, CPR kneel, more jobs); chasers give up at distance; clogged junction spawn block.

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
