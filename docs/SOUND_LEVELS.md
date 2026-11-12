# Sound levels

One scale for everything (`src/loudness.py`): K-weighted LUFS (ITU BS.1770) of the active part of a sound (loops whole, one-shots the 100 ms blocks within 25 dB of the loudest).
`loudness.REF` gives each sound key its loudness at volume 1.0; the game's call sites then scale it (footsteps ask for 0.3-0.55, an explosion for 1.0).
Effective level = REF + 20·log10(volume) before the master/bus sliders.

| What | REF at volume 1.0 | Typical call volume | Effective |
|---|---|---|---|
| Explosions | -13 | 1.0 | -13 |
| Pistol / rifle shots | -16 (peak-limited, about -18 to -19) | 0.7 | -21 |
| Crashes, impacts, punches | -17 to -22 | 0.5-1.0 | -17 to -26 |
| Horns, car alarm | -18 / -20 | 0.6 | -23 |
| Sirens (kept hot: heard from 190 m) | -15 | up to 0.55 | -20 |
| Own engine / traffic engines | -20 | ~0.6 / ≤0.32 | -22 / -30 |
| Footsteps, landings | -22 to -23 | 0.3-0.55 | -28 to -30 |
| Pick-ups, UI | -19 to -24 | 0.35-0.8 | -23 |
| Animals, birds | -18 (barks) / -27 (birds) | 0.45-1.0 | -20 to -33 |
| Background beds (library and procedural) | -24 (±1.5 by catalogue level) | 0.1-0.55 | -30 to -40 |
| Speech | -20 (per clip, speaker's own loudness kept) | 0.15-1.0 | -20 |
| Radio / load music | files are -18 (checked), play at 0.56 / 0.38 | | about -23 |

Procedural sounds are levelled once in `audio.build()` (`loudness.level_all`, soft-clipping stray peaks), library files in `soundproc.loudness_gain` (the same table), speech per clip in `Audio.speak`.
`python3 tools/sound_audit.py [--library] [--wav DIR]` prints every procedural sound's loudness, target and peak (and the raw loudness of the library files).
New effects live in `src/sfx_synth.py` (modal impacts, formant voices, FM bird chirps, doppler passbys). `audio.build_cached()` keeps the rendered set in the temp folder keyed by a hash of the sources.
