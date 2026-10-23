# text/ — all Macedonian text of the game

Every Cyrillic string shown or spoken in the game lives here, one file per code module
(`text/talk.txt` ↔ `src/talk.py`, `text/poi_vendors.txt` ↔ `src/poi_vendors.py`, …;
`*_tool.txt` belong to `tools/`). Code never contains Cyrillic text any more; it asks
`TXT("talk.0042")` and `src/texts.py` loads these files at startup.

## Format

```
## say                       <- section comment: the function/class the text is used in
talk.0042 = Добар ден!       <- key = text
```

- One entry per line. Only edit the part **after ` = `**; never change the key (`talk.0042`).
- Lines starting with `#` and empty lines are ignored.
- Escapes: `\n` new line, `\t` tab, `\\` backslash, `\s` a space at the very start/end of a text.
- Keep placeholders exactly as they are: `{name}`, `{}`, `%s`, `%d` … (the code fills them in).
- Do not add or remove entries and do not reorder keys. To delete a line, edit its text instead.
- Save as UTF-8.

## Proofreading workflow

1. Edit the `.txt` files (or hand them to an external editor/tool — they are plain text).
2. Run `python tools/check_text.py` — it checks the syntax and that every key used in code exists.
3. Start the game (`run.bat demo` for a quick look).

## Careful

- Some entries are used as **identifiers**, not only for display (e.g. neighbourhood names in
  `places.txt` that are matched against map data, or names compared in code). If a changed
  word suddenly "does nothing" in the game, restore the original.
- Slang/register rules: see `docs/Skopje_slang_bible.txt` (the lines in `bible_lines.txt` are generated
  into the characters' speech styles).
- Text baked into the cached world (`junk_tool.txt`, shop signs) needs `run.bat refresh` / a world rebuild to show up.
- Poster *images* (`assets/posters/*.png`) contain painted text; their wording comes from `make_posters_tool.txt` and needs `python tools/make_posters.py` to regenerate.
