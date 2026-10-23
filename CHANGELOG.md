# Changelog

All notable changes to Скопје 242. Newest first.

## Unreleased

- All Macedonian text moved out of the code into `text/*.txt` (5553 strings, loaded by `src/texts.py`); `tools/check_text.py` validates it. Behaviour unchanged.

## v2.0 – people that move and talk like Skopje

### Animation
- Rigged limbs: legs swing from hip and knee, arms from shoulder and elbow, for the avatar and every pedestrian.
- Eight-phase walk and run cycle at a real pace (one stride per about 1.5 m walking and 2.6 m running), forward lean when running, arms down when standing. Arms holding a prop swing with it.

### Speech and slang
- All pedestrian, hero and neighbourhood lines are written against `docs/Skopje_slang_bible.txt` (421 terms) and adapted to each character type (old, woman, kid, tough, posh, youth, sport, priest, vendor, cop) and all 24 playable characters.
- Language level 2 ("Без цензура") is now unhinged.
- Your avatar only talks when you press `H` on foot. New menu row "Колку често зборуваат пешаците" (0.1x–2x).
- **Bumping:** walk into a pedestrian and they grumble, insult you, threaten you ("ќе ти врзам шамар", "гитла бе", "мрш", "фаќај магла"), and after a few bumps they fight you.
- `python tools/check_slang.py --missing` lists bible terms the game does not use yet.

### Cars and sound
- About 1 in 10 traffic cars plays music from `music/` in its cabin. It is muffled and quiet, and only one is heard at a time.
- Nearby traffic has an engine hum.

### Combat
- Much more ammo per pickup; a swung bat smashes props; animated score pop-ups that grow with the payout.

### Roads (world version 12, rebuilds automatically)
- Roads that continue, bend, widen or narrow share one cross-section with a smooth taper. Pavements join in curved corners at junctions. Small height offsets stop road pieces from flickering (z-fighting).

### Docs
- Reorganised README with gallery and project layout; refreshed screenshots (drive, kiosk, roads, night) from the real map.

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
