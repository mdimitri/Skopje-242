"""Cross-reference: which terms of the slang bible (docs/Skopje_slang_bible.txt) appear in the game's Macedonian text?
Run: python tools/check_slang.py [--missing]   (the game text = all src/*.py files)"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIBLE = os.path.join(ROOT, "docs", "Skopje_slang_bible.txt")


def terms():
    out = []
    for ln in open(BIBLE, encoding="utf-8"):
        m = re.match(r"\s*(\d+)\.\s*(.+?)\s+[–-]\s+(.*)", ln) if "(" not in ln.split("–")[0] else None
        if m:
            raw = m.group(2)
            for t in re.split(r"\s*/\s*", raw):
                t = t.strip(" „“\"?!.…").lower()
                if len(t) >= 3:
                    out.append((int(m.group(1)), t, m.group(3)))
    return out


def main():
    text = ""
    for p in glob.glob(os.path.join(ROOT, "src", "*.py")):
        if p.endswith("check_slang.py"):
            continue
        text += open(p, encoding="utf-8").read().lower() + "\n"
    ts = terms()
    miss = [(n, t, d) for n, t, d in ts if t not in text]
    print(f"{len(ts) - len(miss)} of {len(ts)} bible terms appear in src/")
    if "--missing" in sys.argv:
        for n, t, d in miss:
            print(f"  {n}. {t} – {d}")


if __name__ == "__main__":
    main()
