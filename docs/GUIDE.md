# Skopje GTA (prototype)

A top-down (3D, perspective) GTA-style driving sandbox of **Skopje, North Macedonia**: an 11 x 7 km box around the
city centre (Stone Bridge / Macedonia Square, 41.9973 N 21.4280 E: 3 km further east and west and 1 km further
north and south than the first version), built from **OpenStreetMap** data and open **elevation data** (hills, slopes).
Everything the map does not contain (building heights/colours/roofs, trees, street lamps, parked cars,
ground texture, traffic, pedestrians) is generated procedurally.

## Start

**Double-click `run.bat`.**  First run only: it sets up Python + libraries (a private Python is
downloaded if you have none; every step shows a progress bar), downloads the OSM data from Overpass (cached in `data/osm/`), and builds the
world (`data/cache/world/`) - expect a few minutes (an 11 x 7 km city is big). After that the game starts in seconds.
`run.bat` opens the **splash screen at once** with one progress bar and a running log in Skopje slang, then the **start menu**
(`Esc` in the game opens it again): resolution, fullscreen, detail, volumes, time of day and clock speed, traffic and pedestrian
density, ambulance / fire brigade on or off, voice engine. Settings are saved to `settings.json`.

| command | effect |
|---|---|
| `run.bat` | normal start |
| `run.bat demo` | offline synthetic demo city (no internet needed) |
| `run.bat refresh` | re-download the OSM data and rebuild |
| `run.bat aivoice` | one-time install of the optional neural (AI) voice, see below |
| `run.bat --size 1280x720` / `--fullscreen` / `--cars 150` / `--peds 200` | extra game options |

Fallbacks: download fails -> demo city (retry next run); world data corrupt -> rebuilt automatically; world build fails -> demo city;
GPU/texture or subsystem errors are logged to `logs/game.log` and the subsystem is skipped instead of crashing.

## Controls

| key | car | on foot |
|---|---|---|
| `W` `A` `S` `D` / arrows | throttle, steer, brake/reverse | `A`/`D` turn, `W`/`S` walk forward/back (GTA-1 style) |
| `Space` | handbrake (drift, skid marks) | **jump** (clear a car with a running jump) |
| `Ctrl` | - | **fight**: punch, punch, kick combo (pistol once you find one: it shoots) |
| `Shift` | - | run |
| `1` `2` `3` `4` | - | buy food at a **kiosk** (burek, tulumba, kebapi, ajvar sendvich) - restores health |
| `F` / `Enter` | get out | get in / **steal** any car next to you (traffic drivers get angry) |
| `H` | horn (toggles the siren in police / ambulance / fire trucks) | shout |
| `R` | put the car back on the road | - |
| `M` / `Tab` | full map - **click anywhere to teleport** | full map - click to teleport |
| `T` / `Shift+T` | next / previous neighbourhood (instant teleport) | same |
| `[` `]` | time of day -1 h / +1 h | same |
| `N` | mute | mute |
| mouse wheel, `F3`, `F11`, `Esc` | zoom, stats, fullscreen, quit | |

Things to do: collect **burek** (gold dots on the map), pick up **ajvar** (red jars - repairs your car completely),
ram trees and walls (cars deform and catch fire, then explode - burek-bomb), drift on Macedonia Square, steal cars,
scare pedestrians, stay out of the Vardar. Hit a pedestrian and they may hit back (hard ones like Chichko or the
Pandur do); knock them out and they drop money, get knocked out yourself and you wake up poorer a few seconds later.
Money (den) buys food at kiosks. Green pistol pickups lie around the pavements. Shop signs, graffiti and landmark
labels in Skopje slang are pinned all over the map (data in `src/slang.py` - edit or extend freely; the landmark
coordinates are approximate). Entering a neighbourhood pops up a name and a cynical one-liner (`src/places.py`).

**Time of day:** the clock runs a full day in about 22 minutes. Rush hours (07-09:30 and 16-18:45) fill the roads,
lunch and the evening promenade fill the pavements, nights are dark with street lamps, headlights and flashing
emergency lights. Cars have their own top speed, acceleration, grip and weight (`PERF` in `src/vehicles.py`).
**Sound:** all effects, ambience (city hum, birds, crickets), engines and sirens are synthesised with numpy at start-up.
Speech bubbles are also spoken by a small formant synthesiser (robotic Macedonian-ish voice, one voice per character).
Use `run.bat --mute` to switch it all off.

## Terrain, bridges, rescue services (round 4)

- **Terrain:** `tools/fetch_terrain.py` downloads open elevation tiles (Terrarium / SRTM-based) and resamples them to a 10 m grid
  (`data/osm/terrain.npy`, heights relative to the city centre). Buildings stand on the ground with a foundation skirt, roads, pavements, trees,
  lamps and street furniture follow it, the river bed is carved in. If the download fails the city is built flat and says so - re-run the tool.
- **Physics on slopes:** gravity pulls cars along the slope (a = -g sin angle: braking downhill, labouring uphill, the parking brake holds),
  cars **pitch and roll** with the ground, pedestrians and you walk with **Tobler's hiking function** (slower uphill, slightly faster gently downhill).
- **Bridges** have a real deck: ends meet the ground, the middle is lifted to clear roads and paths below, with girders, piers and parapets.
  Footpaths and roads pass **under** bridges and you can use both levels. Jump over a parapet or drive off a deck and you **fall**: landing
  damage grows with the drop (a few metres hurt, ~10 m kills), landing in the river makes a **splash**. When you are under a deck a yellow
  marker shows where you are.
- **Ambulance:** revives pedestrians who were run over or killed (and you, if you wait). **Fire brigade:** puts out burning or exploded
  cars. Both can be switched off in the menu.
- **Neighbourhoods:** `python tools/check_places.py` lists every named place found in the downloaded OSM data with its position, so the
  names and locations can be checked against the real map (the game uses only what OSM says; the hand-placed fallback list is used only if
  OSM has nothing).
- **Voices:** the built-in formant synthesiser works everywhere. `run.bat aivoice` installs an optional neural Macedonian text-to-speech
  model (facebook/mms-tts-mkd via PyTorch, ~1 GB download) and the menu can switch to it.

## Round 5: Cyrillic, loading screen, posters

- All text is in Macedonian Cyrillic (font: DejaVu Sans, free). Wording and sources: `docs/TEXT_SOURCES.md` – **a native speaker should read it once**.
- The first start downloads the map and the terrain: the splash screen shows a map of the city with every piece (roads, buildings, green and water,
  landmarks, neighbourhoods, height tiles) as waiting / downloading / done / failed, the real transfer speed, and warnings when a server is busy,
  rejects or stalls (then it switches to another server or splits the piece). Nothing can hang: every request and every stage has a time limit;
  if the servers do not answer the game starts with what it has (or the demo city). A partial map is completed on a later start.
- While you wait, joke posters are shown (`assets/posters/`, regenerate with `python tools/make_posters.py`).

## What is in the world
- **59 named vehicles**, e.g. Zastava Yugo, Fico, Lada Niva, Trabant, Bavarka E36 (spoiler), Mercedes S Mafijash,
  Golf Trojka Gastarbajter and Passat Dijaspora (mattress and suitcases on the roof), Taxi Zlatna Zolta, Policiska Skoda,
  Brza Pomosh, Pozharna, Smetar Kamion, Betonjerka, Pajak, Burek Dostava, Traktor Belarus, Svadbarska Limuzina and the
  Ohrid coach. 16 paint jobs, dents still deform every mesh. List: `src/vehicles.py`.
- **39 road users + you**: Chichko, Baba, Pandur, Parkingar, Pop, Hipster, Influenser, Telefonash, Gastarbajter,
  Partiski Aktivist, Nevesta, Dostavuvach and more, plus riders: Velosipedist, Dedo na Kolo, Moped Tomos, Glovo Skuter,
  kick scooter kid, e-scooter hipster, Skejter, Rolerash and a horse cart (Kocija). Each has own one-liners; the name
  shows in the speech bubble.
- **3D roads:** smoothed centrelines (corners are rounded, the raw OSM polylines are only guidance), asphalt ribbons with
  gutters, junction fills, raised pavements with curb faces, lane markings, zebra crossings and stop lines. Higher-class
  roads sit on top of lower ones and pavements/markings are cut away where another road crosses them.
- **Kiosks** on the pavements (buy burek and friends), pistols, cash drops.
- **Street furniture:** traffic lights, stop/yield/priority/speed/crossing signs, zebra crossings with stop lines,
  bus shelters, benches, bins, and stone parapets on bridges over the river.
- `python tools/model_sheet.py cars.png peds.png` renders contact sheets of every model.

## Layout

```
run.bat            one-click start (setup + data + launch)
make_exe.bat       optional PyInstaller bundle (experimental)
src/               game: main.py (loop, events, fallbacks), render.py (3D), gl3d.py (models/textures), world.py, bake.py (ground chunks/overview),
                   actors.py (cars, damage, traffic, peds, on-foot, fighting, hijack), fx.py, hud.py, ui.py (loading bars), slang.py,
                   clock.py (time of day), night.py (night lighting), audio.py + speech.py (procedural sound and voices), places.py
                   settings.py + menu.py (options), services.py (ambulance + fire brigade)
tools/             fetch_osm.py, fetch_terrain.py, terrain.py, build_world.py (OSM + terrain -> 3D meshes + runtime world), roads3d.py, furniture.py,
                   check_places.py, make_synthetic_osm.py, setup.ps1, progress.py
data/osm/          cached Overpass JSON (the real map)      data/cache/   generated world + overview (git-ignored)
docs/              ARCHITECTURE.md
```

## Tech (all open source)

Python 3 + [raylib](https://www.raylib.com/) (OpenGL 3.3 GPU rendering, via `raylib` PyPI wheel), numpy, Pillow,
mapbox-earcut. Map data (c) OpenStreetMap contributors, ODbL. See `docs/ARCHITECTURE.md` for the rendering
optimisations (chunked streaming, baked mipmapped chunk textures, far-LOD overview, culling, sprite atlases).

## Car radio
Entering any vehicle starts the radio: tracks from `assets/radio/` play in random order with a short burst of static
between them; leaving the car stops it. Volume: Esc menu, "Радио". The music is downloaded by `tools/fetch_radio.py`
(run.bat does it on every start, resumable, skipped when 100 tracks are present) from Wikimedia Commons, only CC0 / CC BY /
CC BY-SA / public domain. Licences and authors are listed in `assets/radio/ATTRIBUTION.md`.

## Voice credit
Macedonian speech: **Suze** – Macedonian female voice for RHVoice, © UNICEF, made by the speech group of FEEIT UKIM
(https://github.com/RHVoice/suze-mkd), licensed CC BY-NC-ND 4.0 (non-commercial, no modifications). It is downloaded and
installed by `run.bat` (Windows speech/SAPI), not bundled with the game. RHVoice engine: LGPL-2.1+.
