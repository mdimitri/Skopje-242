# Sound library (v2.1)

The game plays AI-generated sound effects from an external library and falls back, **per sound**, to the built-in procedural sounds (`src/audio.py`) for anything the library lacks. Speech (Suze) and everything in `text/` are unaffected.

## Artist workflow

1. Launch the game once. It writes one request JSON per missing sound into `sound_requests/` (219 files, 5-10 versions each; loops are 20-30 s, one-shots 1-10 s). Already-finished sounds are never requested again; existing request files are never overwritten.
2. Run the MOSS-SoundEffect batch worker with `--requests <game>\\sound_requests --output <game>\\library` (it deletes each request when done), or copy the JSONs into the worker's own `requests/` and copy its `library/` back into the game folder. Copy, don't move, if you work with separate folders: the game recreates a request only when neither the file nor a finished sidecar exists.
3. Launch the game again. The console prints `[sound] library: N sounds found`. Done sounds are used immediately; the rest stay procedural.

Nothing else to configure. `SK242_LIBRARY=<path>` points the game at another library folder.

## Format contract

- Request ids are `<key>_<crc>` (key = what the game asks for, e.g. `bird_duck_flock`); `meta.key` carries the key into the sidecar `<id>.json`, which is how the game matches library sounds. Files are `<id>_vNN_seedS.mp3` as the worker writes them.
- Seeds are stable per key (`seed = hash(key) % 9000 * 100`, so key ranges never overlap).
- To change a sound: edit its prompt in `src/soundcat.py`, delete the old `library/<folder>/<id>*` files, relaunch to get a new request. To add versions later, request a new id by hand.
- The full list (key, folder, length, versions, prompt) is `src/soundcat.py`; one catalogue row = one request.

## Quality check at load (`src/soundproc.py`)

A background thread checks every library file once (results cached in `library/.soundcache.json` by size and mtime, so later launches take a moment). A sound switches from procedural to the library as soon as its versions pass; rejects are listed in `logs/sound_rejects.txt` with the reason.

- **Rejected:** silent, mostly silence, too short, truncated (< 40 % of the requested length), corrupt, clipped, and versions that disagree with their siblings (> 10 dB louder/quieter or a very different tone, only when a sound has 4+ versions). If every version of a sound is rejected, the game keeps the procedural sound; ask the artist to rerun that id (delete its sidecar so the request is written again).
- **Cleaned when loaded:** DC offset and rumble below 25 Hz removed, leading/trailing silence trimmed from one-shots, 4 ms / 40 ms fades on one-shots, loops crossfaded end-into-start (equal power, up to 0.5 s) so the wrap is seamless, then loudness levelled.
- **Distance:** one-shots farther than 45 m play a muffled copy (low-pass at ~2.8 kHz) in addition to the volume fall-off. Reverb and wall occlusion are not done (they would need live audio filters).

## How the game uses it

- **Versions:** every play picks a random version, never the same twice in a row; loops start another version each time they wrap. One-shots get +-4 % detune.
- **Loudness:** at load each file is levelled (loops by RMS, one-shots by peak) times the catalogue `level`, so versions and sounds balance without hand-mixing. At most ~300 MB of decoded audio is cached (least recently used unloaded).
- **Space:** `Audio.at(...)` attenuates by distance from the player and pans left/right by position; ambience eases in and out.
- **Places:** `soundlib.Biomes` rasterises land use from the map (trees, parks, water, lake, creek, railway, industrial, plaza, playground, pitch). Ducks, geese and herons spawn on the Vardar, owls and woodpeckers in woods, crows and doves in parks, roosters in the outskirts; forest, river, lake, wind and hill ambience follow the same layers. Time of day picks dawn chorus, night owls, frogs, crickets. Old Bazaar, some city blocks (party, market, wedding, accordion), building sites (hammers, drills, mixer, jackhammer) and burning wrecks have their own sounds. Footsteps follow the surface; traffic cars whoosh by.
- **Fallback:** the procedural sound of the same name, or the catalogue `fb` entry; sounds with neither stay silent until the library has them.

## Testing without audio hardware

`python src/main.py --test 3000 --mute --sound-dry` runs all the sound logic without a device and prints, per sound, whether the library or the fallback would play.
