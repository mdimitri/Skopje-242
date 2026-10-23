# Скопје 242 – Skopje GTA (v2.0)

A top-down, real-3D, GTA-1-style sandbox of **Skopje, North Macedonia**, in Macedonian Cyrillic and Skopje slang.
An 11 × 7 km map around the Stone Bridge is built from **OpenStreetMap** and open elevation data; everything the map
lacks (building looks, trees, lamps, parked cars, traffic, pedestrians) is generated procedurally.
Python + raylib (OpenGL 3.3), numpy, Pillow. Windows is the target platform (`run.bat`).

![Title](docs/screenshots/title.jpg)
![Driving](docs/screenshots/drive.jpg)
![Kiosk](docs/screenshots/kiosk.jpg)

*Screenshots (1280x720) are taken from the real game on the real Skopje map.*

## Run

Double-click **`run.bat`**. First start sets up Python and libraries, downloads the map (Geofabrik / Overpass) and terrain, and builds the world (a few minutes); later starts take seconds. `run.bat demo` runs an offline demo city,
`run.bat refresh` re-downloads the map. Options: `--size 1280x720`, `--fullscreen`, `--cars N`, `--peds N`, `--mute`, `--hour H`.

## Controls

| key | car | on foot |
|---|---|---|
| `W A S D` / arrows | drive | walk / turn |
| `Space` | handbrake (drift) | jump |
| `Ctrl` | – | punch, punch, kick (or shoot a weapon) |
| `Shift` | – | run |
| `1`–`4` | – | buy kiosk food (burek, tulumba, kebapi, ajvar sandwich) |
| `F` / `Enter` | get out | enter / steal a car, board a city bus (40 ден.) |
| `H` | horn / siren toggle | your character says something (only when pressed) |
| `Q` / `E` (or `,` `.`) | change radio station (last step = off) | – |
| `P` | – | take a selfie |
| `M` / `Tab` | map, click to teleport | same |
| `T` / `Shift+T` | next / previous neighbourhood | same |
| `[` `]` | time −/+ 1 h | same |
| `L` | switch character | same |
| `N`, `F3`, `F11`, `Esc` | mute, stats, fullscreen, menu / save / load | |

## Features

**World**
- Real OSM map of Skopje (roads, buildings, water, green areas, landmarks, neighbourhoods) and real terrain: slopes affect cars and walkers, the Vardar bed is carved in.
- Dead-end roads are joined to nearby roads, so there are fewer broken streets.
- Smoothed 3D roads with extra road detail (gutters, kerbs, markings, zebra crossings); bridges with real decks you can pass under or fall from (splash in the river).
- Street furniture, kiosks, bus shelters, **real bus stops** from OSM, bushes, playgrounds, goals and school yards, breakable props.
- Working **traffic lights** in a green wave, day/night cycle with lamps and headlights, **Skopje smog** haze, wall bullet holes and scorch marks.

**Vehicles and people**
- 59 named vehicles (Yugo, Fico, Lada Niva, Trabant, Passat Dijaspora, taxi, police, ambulance, fire truck, JSP bus, wedding limo…) with dents, fire and explosions.
- 39+ road users with their own one-liners; **35 playable characters** (11 new in v1.1: administratorka, bilder, boza, burek, fitka, nastavnica, navivac, palavko, shmizla, srednoskolec, vojnik) with 52 lines each; kids playing at playgrounds and pitches; "people with problems" lines.
- **Real JSP city buses** on real OSM lines that stop at real stops; ride one, or take it over.
- Ambulance revives the fallen, fire brigade puts out burning wrecks; reworked first responders (spray pose, CPR kneel, more jobs).
- **Oriented-box collisions**: every car is a rotated box, walkers are pushed out exactly, traffic brakes for sideways cars; careful driving by traffic and a clogged-junction spawn block.
- **Chain explosions**: fires spread between cars, blast waves throw people and props; punchable props fly and break; punches and kicks animate the real limbs.
- **Shops and places**: walk up to a cafe, shop, bank, church, school, fuel station, market or police station and pick 1–4 things to do from a menu; money rewards for punches, props, hits and explosions; chasers give up at distance.
- **Selfie mode** (`P`) and weapon models in the hand.

**Gameplay**
- Fighting, pistols and other weapons with real projectiles (bullets, pellets, rockets) hitting people, cars, walls and trees.
- Money (денари), kiosk food, burek and ajvar pickups, stats panel, character select, **save / load slots**.

**Menus and UI**
- All text in Macedonian Cyrillic (DejaVu Sans). Settings menu with tabs (display, camera, sound, light, map, game), saved to `settings.json`; quit confirmation.
- **Download splash**: a map of OSM cells and elevation tiles showing waiting / downloading / done / failed, real speed, and warnings; every request has a time limit, so it cannot hang.
- **3D loading splash**: an endless street built with the game's own generators, with cars and characters walking, fighting, chasing and shouting jokes while the world loads.
- Showcase splash (title poster, then cars in blocks of 10 and all characters with jokes) and joke posters.

**Sound**
- All effects, ambience, engines and sirens are synthesised with numpy.
- **Car radio**: plays your own music from the `music/` folder (sub-folders = stations, switch with `Q` / `E`), with static between tracks; volume in the menu. Nothing is downloaded.
- **Speech**: Suze (Macedonian RHVoice voice via Windows SAPI) with per-character pitch / rate profiles.

![Splash](docs/screenshots/splash.jpg)
![Characters](docs/screenshots/likovi.jpg)

![Character select](docs/screenshots/select.jpg)
![Roads](docs/screenshots/roads.jpg)
![Night headlights](docs/screenshots/night.jpg)
![Weapons](docs/screenshots/weapons.jpg)
![POI shop menu](docs/screenshots/poi.jpg)
![Selfie](docs/screenshots/selfie.jpg)

| ![](docs/screenshots/menu_bg.jpg) | ![](docs/screenshots/vardar.jpg) |
|---|---|
| ![](docs/screenshots/smog.jpg) | ![](docs/screenshots/wedding.jpg) |

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Technical notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); the earlier long guide is kept in [docs/GUIDE.md](docs/GUIDE.md).

## Known limits

Macedonian wording is not native-reviewed (see `docs/TEXT_SOURCES.md`). The radio, real map download and Suze voice only run on a real Windows PC with internet.
Large generated data (`data/`, radio audio, logs) is not in the repository.

## Credits and licences

- Map data © OpenStreetMap contributors, ODbL. Terrain: AWS Terrarium tiles (SRTM-based open data).
- **Voice: Suze** – Macedonian female voice for RHVoice, © UNICEF, by the speech group of FEEIT UKIM
  (https://github.com/RHVoice/suze-mkd), licensed **CC BY-NC-ND 4.0** (non-commercial, no modifications). It is downloaded and installed by `run.bat`, not bundled. RHVoice engine: LGPL-2.1+.
- Font: DejaVu Sans (`assets/fonts/LICENSE_DEJAVU`).
- Radio tracks are downloaded only under CC0 / CC BY / CC BY-SA / public domain; attributions are written to `assets/radio/ATTRIBUTION.md` on download.
