"""Check the text/ folder: syntax, keys used by the code vs keys defined.

    python tools/check_text.py
Exit code 1 on any problem.  Run it after editing text/*.txt.
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import texts  # noqa: E402

bad = 0
table = {}
for path in sorted(glob.glob(os.path.join(texts.DIR, "*.txt"))):
    try:
        for no, key, val in texts.parse_file(path):
            if key in table:
                print("duplicate key %s (%s:%d)" % (key, path, no))
                bad += 1
            table[key] = val
            if not val.strip():
                print("empty text: %s" % key)
                bad += 1
    except ValueError as e:
        print(e)
        bad += 1

used = set()
for f in glob.glob(os.path.join(ROOT, "src", "*.py")) + glob.glob(os.path.join(ROOT, "tools", "*.py")):
    with open(f, encoding="utf-8") as fh:
        used.update(re.findall(r'TXT\("([a-z_0-9]+\.\d+)"\)', fh.read()))
for k in sorted(used - set(table)):
    print("key used in code but missing in text/: %s" % k)
    bad += 1
for k in sorted(set(table) - used):
    print("key in text/ but not used by code: %s" % k)
    bad += 1
print("%d texts, %d keys used in code, %d problems" % (len(table), len(used), bad))
sys.exit(1 if bad else 0)
