# Sound library (v2.1)

The game plays AI-generated sound effects from an external library and falls back, **per sound**, to the built-in procedural sounds (`src/audio.py`) for anything the library lacks. Speech (Suze) and everything in `text/` are unaffected.

## Artist workflow

1. Launch the game once. It writes one request JSON per missing sound into `sound_requests/` (221 files, 5-10 versions each; loops are 20-30 s, one-shots 1-10 s). Already-finished sounds are never requested again; existing request files are never overwritten.
2. Run the MOSS-SoundEffect batch worker with `--requests <game>\\sound_requests --output <game>\\library` (it deletes each request when done), or copy the JSONs into the worker's own `requests/` and copy its `library/` back into the game folder. Copy, don't move, if you work with separate folders: the game recreates a request only when neither the file nor a finished sidecar exists.
3. Launch the game again. The console prints `[sound] library: N sounds found`. Done sounds are used immediately; the rest stay procedural.

Nothing else to configure. `SK242_LIBRARY=<path>` points the game at another library folder.

## Format contract

- Request ids are `<key>_<crc>` (key = what the game asks for, e.g. `bird_duck_flock`); `meta.key` carries the key into the sidecar `<id>.json`, which is how the game matches library sounds. Files are `<id>_vNN_seedS.mp3` as the worker writes them.
- Seeds are stable per key (`seed = hash(key) % 9000 * 100`, so key ranges never overlap).
- To change a sound: edit its prompt in `src/soundcat.py`, delete the old `library/<folder>/<id>*` files, relaunch to get a new request. To add versions later, request a new id by hand.
- The full list (key, folder, length, versions, prompt) is `src/soundcat.py`; one catalogue row = one request.

## Writing prompts for MOSS-SoundEffect (game feel)

The model card shows only short, concrete one-sentence prompts ("fresh snow crunching under footsteps.", "a sports car roaring past on the highway.") and a duration; there are no documented control words, so the prompt is the whole recipe and the model renders every scene word you give it. A prompt that says "echoing between buildings" or "outdoors" gets a room and a tail, which is what made the first batch cinematic. Rules the catalogue now follows (`soundcat._gamify` applies them to every row):

- **One sound, plain nouns and verbs** ("A single pistol gunshot."), no scene, place, mood or story words.
- **Fixed style tail** on every one-shot: "Dry close-up game sound effect, sharp attack, tight and punchy, no reverb, no echo, no tail, no music, no speech." Ringing sounds (horns, bells, chimes) say "clean natural ring" instead; loops say "Seamless loop, steady and even, dry, no reverb tail".
- **Short clips:** one-shots are capped by type (steps 0.6 s, punches 0.5, UI 0.5, shots 1.0-1.5, impacts 0.8-1.5, explosions 2.5, horns 0.5-1.2, birds 2-3, crowd 3); loops and ambiences keep 8-30 s. The model fills the whole length, so a shorter length is the strongest "less cinematic" control.
- **Generation settings** written into every request: `cfg_scale` 5.0 for one-shots (holds the prompt harder, so the dry/punchy words stick) and 4.0 for loops. If a sound still comes out wet, raise `cfg_scale` toward 6-7 for that request, or make the prompt more specific about the source and surface ("rubber sole on dry asphalt").
- **Changing a prompt** changes the request id, so the game asks for the new version on the next launch, keeps playing the old one until the new files appear, and then uses only the new ones (the old files can be deleted).

## Quality check at load (`src/soundproc.py`)

A background thread checks every library file once (results cached in `library/.soundcache.json` by size and mtime, so later launches take a moment). A sound switches from procedural to the library as soon as its versions pass; rejects are listed in `logs/sound_rejects.txt` with the reason.

- **Profile per sound:** every catalogue entry gets expected limits (`soundproc.profile`): loop or one-shot, tonal or noisy, brightness range, how steady a loop must be, clear onset and decay for hits (shots, impacts, steps), a real tone for horns. The limits were calibrated on the first 536 real MOSS files and only catch gross failures, not taste.
- **Rejected, with the reason logged:** empty/undecodable/zero-length files, NaN or Inf samples, bad sample rate (< 16 kHz), silent or mostly silent, truncated (< 40 % of the requested length) or far too long, DC offset instead of sound, clipping, white noise or hiss (spectral flatness + slope + energy above 5 kHz), an unexpected steady tone or whistle, digital dropouts, clicks/glitches and digital repetition (stutter) in clean ambience loops, loops whose level wanders, one-shots that never decay or whose peak is at the very end (reversed), one-shots that are just steady noise, horns that are only noise, and versions that disagree with their siblings (> 20 dB louder/quieter or a 6x different tone, with 4+ versions). Nothing in the check can crash the game: every decode/analysis step is guarded, corrupt or odd sidecars are skipped, file names in sidecars are reduced to their base name.
- **Fail safe:** a sound with no accepted version is not published and stays procedural. Ask the artist to rerun it (delete its sidecar so the request is written again).
- **Cleaned when loaded:** DC offset and rumble below 25 Hz removed, leading/trailing silence trimmed from one-shots, 4 ms / 40 ms fades on one-shots, loops crossfaded end-into-start (equal power, up to 0.5 s) so the wrap is seamless, then loudness levelled.
- **Distance:** one-shots farther than 45 m play a muffled copy (low-pass at ~2.8 kHz) in addition to the volume fall-off. Reverb and wall occlusion are not done (they would need live audio filters).

## How the game uses it

- **Versions:** every play picks a random version, never the same twice in a row; loops start another version each time they wrap. One-shots get +-4 % detune.
- **Loudness:** at load each file is levelled (loops by RMS, one-shots by peak) times the catalogue `level`, so versions and sounds balance without hand-mixing. At most ~300 MB of decoded audio is cached (least recently used unloaded).
- **Space:** `Audio.at(...)` attenuates by distance from the player and pans left/right by position; ambience eases in and out.
- **Places:** `soundlib.Biomes` rasterises land use from the map (trees, parks, water, lake, creek, railway, industrial, plaza, playground, pitch). Ducks, geese and herons spawn on the Vardar, owls and woodpeckers in woods, crows and doves in parks, roosters in the outskirts; forest, river, lake, wind and hill ambience follow the same layers. Time of day picks dawn chorus, night owls, frogs, crickets. Old Bazaar, some city blocks (party, market, wedding, accordion), building sites (hammers, drills, mixer, jackhammer) and burning wrecks have their own sounds. Footsteps follow the surface; traffic cars whoosh by.
- **Loudness:** every version is levelled when loaded by A-weighted loudness of its active part (loops: whole file, one-shots: the part within 25 dB of the peak), capped below clipping, so sounds of the same catalogue level are equally loud.
- **Pitch variation:** each play of a library one-shot is detuned randomly by a category-sized amount (`soundcat.PITCH_VAR`: steps 8 %, birds/animals 7 %, impacts 5 %, weapons 3 %, interface 2 %).
- **One car, one engine:** a car always uses the same recording and the same small base-pitch offset, also after you leave it and get back in. Pitch follows speed through five gears (rises, drops at each shift, smoothed, higher under throttle); electric cars whine up continuously. Passing traffic and sirens get a Doppler shift and are panned to their side.
- **Sound travel:** world sounds (shots, crashes, explosions ...) arrive after distance / 343 m/s, so a far explosion is seen before it is heard; the same sound within 40 ms is played once.
- **Zoom:** zoomed in you hear street detail and speech; zoomed out those fade, one-shots switch to their muffled copy, and the city/wind bed (`city`, `wind`, `amb_city_far`, `amb_wind_high`) takes over. Speech content and its generation are untouched, only its mix level follows the zoom.
- **Fallback:** the procedural sound of the same name, or the catalogue `fb` entry; sounds with neither stay silent until the library has them.

## Testing the quality check

`python tools/test_soundproc.py [-v]` (needs ffmpeg) builds a corpus: the game's own synthetic sounds as good samples (36, mp3 round trip) and 163 deliberately bad ones (white/pink noise, hiss, silence, DC, tones, clipping, clicks, dropouts, stutter, endless or reversed one-shots, too long/short, bad sample rate, garbage and empty files, NaN) plus an end-to-end library with corrupt sidecars. Last run: 98 % of bad samples rejected, all for the intended reason; 6 % false rejections, both synthetic sounds that contain exact digital silence (the old bird and cricket generators). On the first real library (536 files, 88 sounds): 25 versions rejected (4.7 %), 511 used; the full check takes ~40 s on the first launch and is cached afterwards.

## Testing without audio hardware

`python src/main.py --test 3000 --mute --sound-dry` runs all the sound logic without a device and prints, per sound, whether the library or the fallback would play.
