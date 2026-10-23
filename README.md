<h1 align="center">Скопје 242</h1>
<p align="center"><b>A GTA-1-style sandbox of Skopje, North Macedonia, in real 3D, Macedonian Cyrillic and pure Skopje slang.</b></p>
<p align="center">v2.0 · Windows · Python + raylib</p>

<p align="center"><img src="docs/screenshots/title.jpg" width="820" alt="Title screen"></p>

An 11 × 7 km slice of Skopje around the Stone Bridge, built from **OpenStreetMap** and open elevation data.
Everything the map leaves out (building looks, trees, lamps, parked cars, traffic, pedestrians) is generated procedurally.
Drive a Yugo down Partizanska, ride a JSP bus, buy a burek at the kiosk, and get cussed at by pensioners in proper Skopje slang.

| | |
|---|---|
| ![Driving](docs/screenshots/drive.jpg) | ![Kiosk](docs/screenshots/kiosk.jpg) |
| ![Night](docs/screenshots/night.jpg) | ![Roads](docs/screenshots/roads.jpg) |

## Contents

[Quick start](#quick-start) · [Controls](#controls) · [Features](#features) · [Gallery](#gallery) · [Project layout](#project-layout) · [Known limits](#known-limits) · [Credits](#credits-and-licences)

## Quick start

1. Download or clone the repository.
2. Double-click **`run.bat`**.

The first start installs Python and the libraries, downloads the map (Geofabrik / Overpass) and the terrain, and builds the world. That takes a few minutes; later starts take seconds.

| command | what it does |
|---|---|
| `run.bat` | play on the real Skopje map |
| `run.bat demo` | offline synthetic demo city |
| `run.bat refresh` | re-download the map and rebuild the world |

Extra options: `--size 1280x720`, `--fullscreen`, `--cars N`, `--peds N`, `--hour H`, `--mute`.
Put your own music in `music/` for the car radio (sub-folders become stations).

## Controls

| key | in a car | on foot |
|---|---|---|
| `W A S D` / arrows | drive | walk / turn |
| `Shift` | – | run |
| `Space` | handbrake (drift) | jump |
| `Ctrl` | – | punch, punch, kick, or shoot |
| `F` / `Enter` | get out | enter / steal a car, board a bus (40 ден.) |
| `H` | horn / siren | say something |
| `1`–`4` | – | kiosk food: burek, tulumba, kebapi, ajvar sandwich |
| `Q` / `E` | radio station (last step = off) | – |
| `P` | – | selfie |
| `M` / `Tab` | map, click to teleport | map |
| `T` / `Shift+T` | next / previous neighbourhood | same |
| `[` / `]` | time of day −1 h / +1 h | same |
| `L` | switch character | same |
| `N` · `F3` · `F11` · `Esc` | mute · stats · fullscreen · menu / save / load | |

## Features

### The city
- Real OSM roads, buildings, water, parks, landmarks and neighbourhoods on real terrain. Slopes affect cars and walkers, and the Vardar bed is carved in.
- Smooth 3D roads with kerbs, gutters, markings and zebra crossings. Widening and narrowing roads share vertices, and pavements meet in curved corners.
- Bridges with real decks: drive under them or fall off into the river.
- Kiosks, bus shelters, real bus stops, playgrounds, school yards, street furniture and breakable props.
- Traffic lights in a green wave, a day/night cycle with street lamps and headlights, Skopje smog, bullet holes and scorch marks.

### People and vehicles
- **24 playable characters** with dozens of personal lines each, plus 39+ road users with their own one-liners.
- Pedestrians walk with a rigged stride (hips, knees, shoulders, elbows) at a real walking pace, lean into a run, and stand with their arms down.
- **Bump into someone** and they grumble, insult you, threaten you ("ќе ти врзам шамар", "фаќај магла") and finally fight you, each in their own character's voice.
- 59 named vehicles (Yugo, Fićo, Lada Niva, Trabant, Passat Dijaspora, taxi, police, ambulance, fire truck, JSP bus, wedding limo) with dents, fire and explosions.
- Real JSP city buses on real lines that stop at real stops: ride one or take it over.
- An ambulance revives the fallen and the fire brigade puts out burning wrecks.

### Action
- Fists, bats, pistols, uzis, shotguns, kalashnikovs and the zolja, with real projectiles that hit people, cars, walls and trees.
- Oriented-box car collisions, chain explosions, blast waves, and props that fly and break.
- Money (денари) for every punch, smash and explosion, shown as animated score pop-ups.
- Shops and places: walk into a café, bank, church, school, fuel station or market and pick from a menu.
- Selfie mode, kiosk food, burek and ajvar pickups, save and load slots.

### Language and sound
- All text is Macedonian Cyrillic, written against the [Skopje slang bible](docs/Skopje_slang_bible.txt). Three language levels: clean, street and uncensored (fully unhinged).
- Speech uses the Suze Macedonian voice with per-character pitch and rate, and a menu setting for how often pedestrians talk.
- The car radio plays your own music with static between stations. About one in ten passing cars plays muffled music in its cabin.
- All effects, engines, sirens and ambience are synthesised with numpy.

## Gallery

| | |
|---|---|
| ![Loading splash](docs/screenshots/splash.jpg) | ![Characters](docs/screenshots/likovi.jpg) |
| ![Character select](docs/screenshots/select.jpg) | ![Weapons](docs/screenshots/weapons.jpg) |
| ![Shop menu](docs/screenshots/poi.jpg) | ![Selfie](docs/screenshots/selfie.jpg) |
| ![Menu](docs/screenshots/menu_bg.jpg) | ![Vardar](docs/screenshots/vardar.jpg) |
| ![Smog](docs/screenshots/smog.jpg) | ![Wedding](docs/screenshots/wedding.jpg) |

*All screenshots are from the real game on the real Skopje map.*

## Project layout

| path | contents |
|---|---|
| `run.bat`, `make_exe.bat` | start the game, build a stand-alone exe |
| `src/` | the game: simulation (`actors.py`), rendering (`render.py`, `gl3d.py`), sound, radio, speech and all text |
| `tools/` | map and terrain download, world builder, road meshes, checks |
| `assets/` | fonts, character art, posters |
| `docs/` | [architecture](docs/ARCHITECTURE.md), [long guide](docs/GUIDE.md), [text sources](docs/TEXT_SOURCES.md), slang bible, screenshots |

Release history: [CHANGELOG.md](CHANGELOG.md).

## Known limits

- Windows only. The voice and the setup script need Windows.
- The Macedonian wording has not been reviewed by a native editor (see [docs/TEXT_SOURCES.md](docs/TEXT_SOURCES.md)).
- The map download and the voice need an internet connection on first start. Generated data (`data/`, logs) is not in the repository.

## Credits and licences

- Map data © OpenStreetMap contributors, ODbL. Terrain: AWS Terrarium tiles (SRTM-based open data).
- **Voice: Suze**, a Macedonian female voice for RHVoice, © UNICEF, by the speech group of FEEIT UKIM ([suze-mkd](https://github.com/RHVoice/suze-mkd)), licensed **CC BY-NC-ND 4.0**. `run.bat` downloads it; it is not bundled. RHVoice engine: LGPL-2.1+.
- Font: DejaVu Sans (`assets/fonts/LICENSE_DEJAVU`).
- Radio: only music you put in `music/` yourself is played.
