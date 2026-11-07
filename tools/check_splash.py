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
# every label / sub the build tools report must have a real translation (mk() is only a safety net, never a translator)
import ast, glob   # noqa: E402
for f in glob.glob(os.path.join(ROOT, "tools", "*.py")):
    for n in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
        if not isinstance(n, ast.Call):
            continue
        nm = getattr(n.func, "id", getattr(n.func, "attr", ""))
        S = [a.value for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        S += [k.value.value for k in n.keywords if k.arg == "sub" and isinstance(k.value, ast.Constant)]
        if nm in ("phase", "Bar") and S and S[0] not in T.BUILD:
            bad.append((os.path.basename(f), f"no translation in strings.BUILD: {S[0]!r}"))
        elif nm in ("span", "frac") and S and S[-1] not in ui.MK_SUB:
            bad.append((os.path.basename(f), f"no translation in ui.MK_SUB: {S[-1]!r}"))
# every English label/sub the build tools emit must come out Cyrillic through the loader's own translation
srcs = open(os.path.join(ROOT, "src", "main.py"), encoding="utf-8").read()
for f in os.listdir(os.path.join(ROOT, "tools")):
    if f.endswith(".py"):
        t = open(os.path.join(ROOT, "tools", f), encoding="utf-8").read()
        for m in re.finditer(r'(?:span\([^"\n]*?,\s*[\d.]+,\s*[\d.]+,\s*|Bar\()"([^"]+)"', t):
            chk(f"tools/{f} sub/label {m[1]!r}", ui.mk(ui.MK_SUB.get(m[1], T.BUILD.get(m[1], m[1]))))
for m in re.finditer(r'loader\.(?:tick\([^,]+,\s*|say\()f?"([^"{]+)', srcs):
    if LAT.search(m[1]) and m[1] not in ui.MK_NOTE and not any(r.pattern.startswith('^' + m[1]) or r.match(m[1]) for r, _ in ui.MK_RE):
        bad.append(("main.py", f"note has no translation in ui.MK_NOTE: {m[1]!r}"))
chk("mk() sample", "overpass-api.de refresh")
if bad:
    for w, s in bad:
        print("LATIN:", w, "->", s)
    sys.exit(1)
print("splash strings: all Cyrillic")
