"""Incremental world build: tools/build_world.py main() is cut into stages (the `stage("name", data=(...))` marker
statements); every stage has a fingerprint and its results are cached, so a launch re-runs only the stages from the first
changed one on.

fingerprint(stage) = hash(previous stage's fingerprint, the stage's code, the helper functions / constants / tool modules
that code uses (found by name), the data files it reads)    -> a change ripples to every later stage, never to an earlier one.
Cache (<world>.stages/): <stage>.state.pkl = the variables the stage changed, <stage>.mesh.pkl = the geometry it emitted,
stages.json = fingerprints.  The final write of the world (stage "write") always runs, from the cached mesh layers.

Edit a stage's code, or a tool module it imports, and only that stage and the ones after it run again (comment / layout
edits do not count: code is hashed through ast.unparse).  Bump build_world.VERSION to force a full rebuild.
"""
import ast
import glob
import hashlib
import importlib
import json
import os
import pickle
import shutil
import sys
import time
import types

from progress import frac, phase

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FORMAT = 2                                    # layout of the cache itself
# module-level lists the tool modules fill while building; later code reads them, so they travel with the snapshots
MODSTATE = (("furniture", "SIGNALS"), ("furniture", "STOPS"), ("construction", "LOTS"))
SOURCE = os.path.join(HERE, "build_world.py")


def _md5(*parts):
    h = hashlib.md5()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


def _unparse(node):
    return ast.unparse(node)


# ------------------------------------------------------------------------------------------------ the stage layout
def _marker(stmt):
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) and getattr(stmt.value.func, "id", "") == "stage":
        c = stmt.value
        kw = {k.arg: ast.literal_eval(k.value) for k in c.keywords}
        return ast.literal_eval(c.args[0]), kw
    return None


def layout(path=SOURCE):
    """-> (tree, prelude, hoisted, stages): prelude = statements of main() before the first marker, hoisted = its top-level
    defs / classes (run every time, they are cheap and later stages call them), stages = [(name, kw, [stmts])]."""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    prelude, hoisted, stages = [], [], []
    for st in main.body:
        m = _marker(st)
        if m:
            stages.append((m[0], m[1], []))
        elif isinstance(st, (ast.FunctionDef, ast.ClassDef)):
            hoisted.append(st)
        else:
            (stages[-1][2] if stages else prelude).append(st)
    return tree, prelude, hoisted, stages


# ------------------------------------------------------------------------------------------------ code fingerprints
class _Code:
    def __init__(self, tree, hoisted):
        self.defs = {}                                    # name -> unparsed source of every top-level def / constant
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name != "main":
                self.defs[n.name] = n
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    for q in ast.walk(t):
                        if isinstance(q, ast.Name):
                            self.defs[q.id] = n
        for n in hoisted:
            self.defs[n.name] = n
        self.mods = {}

    @staticmethod
    def _names(node):
        out = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "__import__" and n.args and isinstance(n.args[0], ast.Constant):
                out.add("import:" + str(n.args[0].value))
            elif isinstance(n, ast.Import):
                out |= {"import:" + a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                out.add("import:" + n.module.split(".")[0])
        return out

    def module(self, name, seen):
        """Fingerprint parts of a local tool module (tools/ or src/) and, recursively, the local modules it imports."""
        if name in seen:
            return []
        seen.add(name)
        for d in ("tools", "src"):
            p = os.path.join(ROOT, d, name + ".py")
            if os.path.exists(p):
                break
        else:
            return []
        if p not in self.mods:
            raw = open(p, encoding="utf-8").read()
            try:
                t = ast.parse(raw)
                self.mods[p] = (_unparse(t), [n[7:] for n in self._names(t) if n.startswith("import:")])
            except SyntaxError:
                self.mods[p] = (raw, [])
        text, subs = self.mods[p]
        parts = [name, text]
        for s in sorted(subs):
            parts += self.module(s, seen)
        if name == "texts":                               # src/texts.py reads text/*.txt
            for f in sorted(glob.glob(os.path.join(ROOT, "text", "*"))):
                parts += [os.path.basename(f), open(f, "rb").read()]
        return parts

    def of(self, stmts, extra=()):
        """Everything the statements depend on, as a list of hashable parts."""
        parts, todo, done, mods, defs = [_unparse(s) for s in stmts], set(), set(), set(), {}
        for s in stmts:
            todo |= self._names(s)
        while todo:
            n = todo.pop()
            if n in done:
                continue
            done.add(n)
            if n.startswith("import:"):
                mods.add(n[7:])
            elif n in self.defs:
                node = self.defs[n]
                defs[n] = _unparse(node)
                todo |= self._names(node)
        parts += [defs[n] for n in sorted(defs)]            # sets iterate in a different order every run: sort
        seen = set()
        for m in sorted(mods) + list(extra):
            parts += self.module(m, seen)
        return parts


def _data_parts(names, src, extras):
    parts = []
    for n in names:
        if n == "elements":                               # every OSM json that is not a side list read by a stage of its own
            files = [f for f in sorted(glob.glob(os.path.join(src, "*.json"))) if os.path.basename(f) not in extras]
        else:
            files = [os.path.join(src, n)]
        for f in files:
            try:
                parts += [os.path.basename(f), _md5(open(f, "rb").read())]
            except OSError:
                parts += [os.path.basename(f), "missing"]
    return parts


def fingerprints(src, path=SOURCE, version=None):
    """-> [(stage name, fingerprint)] for a world built from `src` with the tools as they are now."""
    tree, prelude, hoisted, stages = layout(path)
    code = _Code(tree, hoisted)
    extras = {n for _, kw, _ in stages for n in kw.get("data", ()) if n.endswith(".json")}
    prev, out = _md5("fmt", FORMAT, version), []
    for name, kw, stmts in stages:
        parts = code.of(stmts + (prelude if not out else []), kw.get("mods", ())) + _data_parts(kw.get("data", ()), src, extras)
        prev = _md5(prev, name, *parts)
        out.append((name, prev))
    return out


def world_version(path=SOURCE):
    """build_world.VERSION (read from the source: importing build_world needs numpy / PIL)."""
    for n in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "VERSION" for t in n.targets):
            return ast.literal_eval(n.value)


def is_stale(world, src, version=None):
    """True when `world` (a built directory) no longer matches the tools and data (stage by stage)."""
    version = version or world_version()
    try:
        man = json.load(open(os.path.join(world, "manifest.json")))
        if man.get("version") != version or not man.get("stages"):
            return True
        have = man["stages"]
        return any(have.get(n) != fp for n, fp in fingerprints(src, version=version) if n != "write")
    except Exception:  # noqa: BLE001 - unreadable = rebuild
        return True


def stale_stages(world, src, version=None):
    """Names of the stages that would run again (for the log)."""
    version = version or world_version()
    try:
        have = json.load(open(os.path.join(world, "manifest.json"))).get("stages") or {}
    except Exception:  # noqa: BLE001
        have = {}
    fps = [(n, fp) for n, fp in fingerprints(src, version=version) if n != "write"]
    first = next((i for i, (n, fp) in enumerate(fps) if have.get(n) != fp), len(fps))
    return [n for n, _ in fps[first:]]


# ------------------------------------------------------------------------------------------------ the cache
def _skip(v):
    return isinstance(v, (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, types.MethodType, type, types.GeneratorType))


class _Ticker:
    """A file-like sink for pickle: hashes and/or writes what it gets and moves the loading bar from lo to hi as the bytes
    come (est = the expected size), so pickling a big variable never freezes the bar."""

    def __init__(self, lo, hi, est, f=None, sub="saving"):
        self.h, self.f, self.n = hashlib.md5(), f, 0
        self.lo, self.hi, self.est, self.sub = lo, hi, max(1, est), sub

    def write(self, b):
        self.n += memoryview(b).nbytes                    # (protocol 5 hands big buffers over as PickleBuffer)
        if self.f is None:
            self.h.update(b)
        else:
            self.f.write(b)
        frac(self.lo + (self.hi - self.lo) * min(1.0, self.n / self.est), self.sub)
        return memoryview(b).nbytes


class _State:
    """Digest of every picklable variable, so a stage's changes (also in-place ones) can be found."""

    def __init__(self):
        self.known = {}
        self.size = {}                                    # pickled bytes of each variable last time (progress estimates)
        self.unpicklable = set()

    def diff(self, ns, skip=(), lo=0.0, hi=1.0):
        changed, gone = {}, [n for n in self.known if n not in ns]
        for n in gone:
            del self.known[n]
        todo = [(n, v) for n, v in list(ns.items()) if not (n.startswith("__") or n in skip or _skip(v))]
        tot = sum(self.size.get(n, 1 << 20) for n, _ in todo) or 1
        done = 0
        for n, v in todo:
            w = self.size.get(n, 1 << 20)
            t = _Ticker(lo + (hi - lo) * done / tot, lo + (hi - lo) * (done + w) / tot, w, sub="checking what changed")
            done += w
            try:
                pickle.dump(v, t, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:  # noqa: BLE001 - e.g. an ImageDraw: the build re-creates those (rebind)
                self.unpicklable.add(n)
                continue
            self.size[n] = t.n
            d = t.h.hexdigest()
            if self.known.get(n) != d:
                self.known[n] = d
                changed[n] = v
        return changed, gone


def _dump(obj, path, lo=None, hi=None, est=1):
    with open(path + ".tmp", "wb") as f:
        pickle.dump(obj, f if lo is None else _Ticker(lo, hi, est, f), protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(path + ".tmp", path)


def run(argv=None):
    """Build the world with stage caching.  Returns normally when the world is written."""
    t_all = time.time()
    tree, prelude, hoisted, stages = layout()
    mod = sys.modules.get("build_world") or sys.modules["__main__"]
    ns = dict(vars(mod))
    ns["__name__"] = "build_world_staged"

    def go(nodes):
        if nodes:
            exec(compile(ast.Module(body=nodes, type_ignores=[]), SOURCE, "exec"), ns)

    go(hoisted)                                           # defs first: later stages call them whether or not their own stage runs
    go(prelude)                                           # arguments, OSM elements, terrain
    a = ns["a"]
    cache = a.out + ".stages"
    version = ns["VERSION"]
    fps = fingerprints(a.src, version=version)
    names = [n for n, _ in fps]
    stored = {}
    try:
        stored = json.load(open(os.path.join(cache, "stages.json")))
        if stored.get("format") != FORMAT:
            stored = {}
    except Exception:  # noqa: BLE001
        stored = {}
    have = stored.get("fps", {})
    state = _State()
    state.diff(ns)                                        # baseline: whatever the prelude made needs no snapshot

    first = len(fps) - 1                                  # "write" is last and always runs
    for i, (n, fp) in enumerate(fps[:-1]):
        ok = have.get(n) == fp and all(os.path.exists(os.path.join(cache, n + e)) for e in (".state.pkl", ".mesh.pkl"))
        if not ok:
            first = i
            break
    for n, _ in fps[first:-1]:                            # everything from the first stale stage on is going away
        for e in (".state.pkl", ".mesh.pkl"):
            try:
                os.remove(os.path.join(cache, n + e))
            except OSError:
                pass
    os.makedirs(cache, exist_ok=True)
    keep = {n: fp for n, fp in fps[:first]}

    def save_index():
        with open(os.path.join(cache, "stages.json"), "w") as f:
            json.dump({"format": FORMAT, "fps": keep}, f)

    save_index()
    print(f"[stages] reusing {first} of {len(fps) - 1}: {', '.join(names[:first]) or 'nothing'}; running: {', '.join(names[first:-1]) or 'nothing'}")

    layers = []                                           # mesh layers in stage order: dicts (chunk, material) -> (pos, uv, col)
    if first:
        phase("loading saved stages")
    for i in range(first):                                # restore the cached stages
        n = names[i]
        frac(i / first, n)
        d = pickle.load(open(os.path.join(cache, n + ".state.pkl"), "rb"))
        ns.update(d["vars"])
        for k, m in d["imports"].items():                 # "import roads3d" inside a stage that is not run again
            if k not in ns:
                ns[k] = importlib.import_module(m)
        for g in d["gone"]:
            ns.pop(g, None)
        for (m, attr), v in d["mods"].items():
            setattr(importlib.import_module(m), attr, v)
        layers.append(pickle.load(open(os.path.join(cache, n + ".mesh.pkl"), "rb")))
        print(f"[stages] {n}: reused")
    if first:
        state.diff(ns)
        if "rebind" in ns:
            ns["rebind"](ns)

    for i in range(first, len(fps) - 1):
        n, fp = fps[i]
        _, kw, stmts = stages[i]
        t0 = time.time()
        ns["mesh"] = ns["MeshAcc"]()
        go(stmts)
        t1 = time.time()
        phase("saving the stage")                         # snapshot of the stage for the next launch: big, so it reports too
        layer = {}
        items_ = list(ns["mesh"].d.items())
        for j_, (k, (P, U, C)) in enumerate(items_):
            if j_ % 64 == 0:
                frac(0.1 * j_ / max(1, len(items_)), "geometry")
            layer[k] = (P[0] if len(P) == 1 else __import__("numpy").concatenate(P),
                        U[0] if len(U) == 1 else __import__("numpy").concatenate(U),
                        C[0] if len(C) == 1 else __import__("numpy").concatenate(C))
        changed, gone = state.diff(ns, skip=("mesh",), lo=0.1, hi=0.5)
        mods = {}
        for m, attr in MODSTATE:
            if m in sys.modules:
                mods[(m, attr)] = getattr(sys.modules[m], attr, None)
        imports = {k: v.__name__ for k, v in ns.items() if isinstance(v, types.ModuleType) and not k.startswith("__")}
        _dump({"vars": changed, "gone": gone, "mods": mods, "imports": imports}, os.path.join(cache, n + ".state.pkl"),
              0.5, 0.7, sum(state.size.get(k, 1) for k in changed))
        _dump(layer, os.path.join(cache, n + ".mesh.pkl"), 0.7, 1.0, sum(a.nbytes for t_ in layer.values() for a in t_ if hasattr(a, "nbytes")))
        layers.append(layer)
        keep[n] = fp
        save_index()
        print(f"[stages] {n}: ran {t1 - t0:.1f}s, cached in {time.time() - t1:.1f}s ({', '.join(sorted(changed)) or 'no changes'})")

    # the write stage: the merged geometry of every layer, then the code of the stage itself
    merged = ns["MeshAcc"]()
    for layer in layers:
        for k, (p, u, c) in layer.items():
            e = merged.d.setdefault(k, ([], [], []))
            e[0].append(p); e[1].append(u); e[2].append(c)
    ns["mesh"] = merged
    ns["STAGE_FPS"] = {n: fp for n, fp in fps if n != "write"}
    go(stages[-1][2])
    print(f"[stages] done in {time.time() - t_all:.1f}s")
