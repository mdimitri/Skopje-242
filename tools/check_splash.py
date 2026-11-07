"""Fails if any text the loading screen can show contains Latin letters.  Run: python tools/check_splash.py"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "tools")]
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
LAT = re.compile(r"[A-Za-z]")
try:
    import pyray  # noqa: F401
except ImportError:                      # headless box: only the text matters
    from unittest.mock import MagicMock
    for _m in ("pyray", "font", "poster"):
        sys.modules.setdefault(_m, MagicMock())
import strings as T, slang, ui   # noqa: E402

bad = []
def chk(where, s):
    s = ui.mk(s)                          # the loader shows every string through ui.mk
    if isinstance(s, str) and LAT.search(s):
        bad.append((where, s))

for name in ("STAGE", "BUILD", "LAYER", "WARN", "NOTE"):
    for k, v in getattr(T, name).items():
        chk(f"strings.{name}[{k}]", v)
for name in dir(T):
    if name.isupper() or name.startswith("L_") or name in ("KB", "MB"):
        v = getattr(T, name)
        if isinstance(v, str) and name not in ("TITLE_",):
            chk(f"strings.{name}", v)
for name in ("MK_LEG", "MK_PART", "MK_NOTE", "MK_SUB"):
    for k, v in getattr(ui, name).items():
        chk(f"ui.{name}[{k}]", v)
for q in slang.LOADING_QUIPS:
    chk("slang.LOADING_QUIPS", q)
# every English label/sub the build tools emit must come out Cyrillic through the loader's own translation
srcs = open(os.path.join(ROOT, "src", "main.py"), encoding="utf-8").read()
for f in os.listdir(os.path.join(ROOT, "tools")):
    if f.endswith(".py"):
        t = open(os.path.join(ROOT, "tools", f), encoding="utf-8").read()
        for m in re.finditer(r'(?:span\([^"\n]*?,\s*[\d.]+,\s*[\d.]+,\s*|Bar\()"([^"]+)"', t):
            chk(f"tools/{f} sub/label {m[1]!r}", ui.mk(ui.MK_SUB.get(m[1], T.BUILD.get(m[1], m[1]))))
for m in re.finditer(r'loader\.(?:tick\([^,]+,\s*|say\()f?"([^"{]+)', srcs):
    chk(f"main.py note {m[1]!r}", ui.Loader._tr(m[1]))
chk("mk() sample", "overpass-api.de refresh")
if bad:
    for w, s in bad:
        print("LATIN:", w, "->", s)
    sys.exit(1)
print("splash strings: all Cyrillic")
