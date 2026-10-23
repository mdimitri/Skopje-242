"""Loader for all Macedonian (Cyrillic) game text.

The text lives in plain files in the `text/` folder at the project root
(one file per code module, `text/<module>.txt`) and is looked up by key:
`TXT("talk.0042")`.  See text/README.md for the file format.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DIR = os.path.join(getattr(sys, "_MEIPASS", _ROOT), "text")
if not os.path.isdir(DIR):
    DIR = os.path.join(_ROOT, "text")

_ESC = {"n": "\n", "t": "\t", "r": "\r", "s": " ", "\\": "\\"}


def unescape(s):
    if "\\" not in s:
        return s
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n in _ESC:
                out.append(_ESC[n])
                i += 2
                continue
            if n == "u" and i + 5 < len(s) + 0 and len(s) >= i + 6:
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
        out.append(c)
        i += 1
    return "".join(out)


def escape(s):
    s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    out = []
    for ch in s:
        out.append("\\u%04x" % ord(ch) if ord(ch) < 32 else ch)
    s = "".join(out)
    if s.startswith(" "):
        s = "\\s" + s[1:]
    if s.endswith(" ") and not s.endswith("\\s"):
        s = s[:-1] + "\\s"
    return s


def parse_file(path):
    """Yield (lineno, key, text) for every entry of one text file."""
    with open(path, encoding="utf-8") as f:
        for no, line in enumerate(f, 1):
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, sep, val = line.partition(" = ")
            if not sep:
                if line.endswith(" ="):
                    key, val = line[:-2], ""
                else:
                    raise ValueError("%s:%d: expected 'key = text'" % (path, no))
            yield no, key.strip(), unescape(val)


def load_all(directory=None):
    d = directory or DIR
    table = {}
    for name in sorted(os.listdir(d)):
        if not name.endswith(".txt"):
            continue
        path = os.path.join(d, name)
        for no, key, val in parse_file(path):
            if key in table:
                raise ValueError("%s:%d: duplicate key %s" % (path, no, key))
            table[key] = val
    return table


_TABLE = load_all()


def TXT(key):
    try:
        return _TABLE[key]
    except KeyError:
        raise KeyError("missing text key %r (check the files in %s)" % (key, DIR)) from None
