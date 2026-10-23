# text/ — all Macedonian text of the game (for the human editor)

Every Cyrillic string the game shows or speaks is in these files. The code contains no Cyrillic text:
it asks for a text by key (`TXT("talk.0042")`) and `src/texts.py` loads **every `*.txt` file in this
folder** at start-up. Edit, save, start the game — nothing else to do.

| File | What is in it |
|------|---------------|
| `01_ui_and_menus.txt` | menus, HUD, loading screen, settings, save slots, notifications, selfie |
| `02_characters_and_vehicles.txt` | playable characters, car names, buses/trams, police/ambulance, radio, voice |
| `03_places_and_pois.txt` | neighbourhoods, types of places (⚠ some matched against map data) |
| `04_shops_and_vendors.txt` | what shops, kiosks and vendors sell, their chatter |
| `05_dialogue_pedestrians.txt` | what pedestrians say, bump reactions, "people with problems" |
| `06_dialogue_slang.txt` | slang word lists and the per-character slang styles (see `docs/Skopje_slang_bible.txt`) |
| `07_dialogue_hero_and_hood.txt` | hero lines, neighbourhood lines, bump comments, loading-screen showcase |
| `08_tools_and_posters.txt` | poster captions, street-junk names, radio list (build tools) |

## Format

```
# --- function `say` · data `GREET` ---     <- where the text is used (comment, ignore when editing)
# used in: talk.py > say, talk.py > react   <- which code reads it
# [baba · greeting]                          <- who/what it belongs to
talk.0042 = Добар ден!                       <- key = text   (edit only the text)
```

- Lines starting with `#` and empty lines are comments; the game ignores them.
- **Never change the key** (`talk.0042`). Do not delete or reorder entries; edit the text instead.
- Escapes: `\n` new line, `\t` tab, `\\` backslash, `\s` a space at the very start/end of a text.
- Keep placeholders exactly as they are: `{name}`, `{}`, `%s`, `%d` … (the code fills them in).
- `sentence:` comments show how fragments are glued together in the game; `⟨…⟩` is a value inserted by code.
- `WARNING: lookup` means the text is also compared with other data (e.g. map names). Do not reword it
  without the developer.
- Save as UTF-8. Comments are English; texts are Macedonian.

## Check your edits

```
python tools/check_text.py
```
It checks the syntax and that every key used in the code exists (and vice versa). Then run the game
(`run.bat demo` for a quick look).

## Notes for developers

- New text: add `module.NNNN = text` (next free number of that module) to a suitable file and use `TXT("module.NNNN")` in the code.
- Text baked into the cached world (street junk, shop signs) needs `run.bat refresh`; poster images need `python tools/make_posters.py`.
