"""Faster pyray: imported once at start-up, before anything draws.

pyray wraps every raylib function in a Python function that walks all arguments (string encoding, pointer conversion)
and builds structs through a generic constructor with a weak-reference table. For the many functions whose C
arguments are all plain values (numbers, structs by value) that work does nothing, so the pyray name is pointed at the
raw cffi function instead; it takes the same arguments (cdata structs, or tuples for structs) and returns the same.
(Structs passed by value are copied as they are by both, pointer fields included.)
Functions with any pointer or string argument, or a string result, keep the pyray wrapper.
Plain float/int structs (Vector2/3/4, Color, Rectangle, Matrix ...) get a lean constructor (no weak-reference entry:
they hold no pointers that would need keeping alive)."""
import os

import pyray
import raylib

ffi = raylib.ffi
lib = raylib.rl
_new = ffi.new
patched = 0


def _plain(t):
    """True when a C type holds no pointers (numbers and nested plain structs only)."""
    if t.kind == "primitive" or t.kind == "enum":
        return True
    if t.kind == "struct":
        return all(_plain(f[1].type) for f in (t.fields or ()))
    if t.kind == "array":
        return _plain(t.item)
    return False


def _install():
    global patched
    for name in dir(lib):
        f = getattr(lib, name)
        try:
            ft = ffi.typeof(f)
        except TypeError:
            continue
        if ft.kind != "function" or ft.ellipsis:
            continue
        if any(a.kind == "pointer" for a in ft.args):
            continue                                     # pointers / strings: pyray converts these
        if ft.result.kind == "pointer":
            continue
        u = pyray._underscore(name) if hasattr(pyray, "_underscore") else None
        if u and hasattr(pyray, u):
            setattr(pyray, u, f)
            patched += 1
    for st in ("Vector2", "Vector3", "Vector4", "Color", "Rectangle", "Matrix", "Quaternion"):
        try:
            t = ffi.typeof(st)
        except Exception:  # noqa: BLE001
            continue
        if not _plain(t):
            continue
        n = len(t.fields)
        decl = st + " *"

        def make(*a, _d=decl, _n=n):
            return _new(_d, a if len(a) == _n else a + (0,) * (_n - len(a)))[0]
        setattr(pyray, st, make)


if os.environ.get("SK242_FASTRL", "1") != "0":
    _install()
