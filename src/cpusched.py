"""Where the game's work runs on a hybrid CPU (Intel P-cores + E-cores) under Windows.

The frame loop keeps Windows' defaults (raising its priority measured no gain, 2026-11-13).  Background worker processes (model building,
photo fitting) ask for the opposite: below-normal priority and EcoQoS on, so Windows parks them on the efficiency cores and they
never compete with the frame.  Elsewhere (Linux, macOS, an old Windows) every call is a silent no-op."""
import sys

_PROCESS_POWER_THROTTLING = 4                  # ProcessPowerThrottling (PROCESS_INFORMATION_CLASS)
_EXECUTION_SPEED = 0x1                         # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
ABOVE_NORMAL, BELOW_NORMAL = 0x8000, 0x4000    # priority classes


def _apply(prio, eco):
    import os
    if sys.platform != "win32" or os.environ.get("SK242_NOSCHED"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _PPT(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        k = ctypes.windll.kernel32
        h = k.GetCurrentProcess()
        k.SetPriorityClass(h, prio)
        st = _PPT(1, _EXECUTION_SPEED, _EXECUTION_SPEED if eco else 0)
        k.SetProcessInformation(h, _PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st))
        return True
    except Exception:  # noqa: BLE001 - not available: leave the defaults
        return False


def worker():
    """A background worker process: efficiency cores, low priority."""
    return _apply(BELOW_NORMAL, True)


def game():
    """The game process: tell Windows never to throttle it (no EcoQoS, no timer coalescing), so its frame thread is not parked
    on an efficiency core at a low clock.  -> a short note for game.log about the CPU and the power source."""
    import os
    if sys.platform != "win32" or os.environ.get("SK242_NOSCHED"):
        return ""
    note = []
    try:
        import ctypes
        from ctypes import wintypes

        class _PPT(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetCurrentProcess.restype = k.GetCurrentThread.restype = wintypes.HANDLE      # (a plain int restype cut the handle: the calls failed)
        k.SetProcessInformation.argtypes = k.SetThreadInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        st = _PPT(1, _EXECUTION_SPEED, 0)          # execution speed + ignore timer resolution: both forced OFF (high QoS)
        ok = k.SetProcessInformation(k.GetCurrentProcess(), _PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st))
        tt = _PPT(1, _EXECUTION_SPEED, 0)
        ok2 = k.SetThreadInformation(k.GetCurrentThread(), 3, ctypes.byref(tt), ctypes.sizeof(tt))   # ThreadPowerThrottling
        note.append(f"throttling off: process {'ok' if ok else 'failed %d' % ctypes.get_last_error()}, frame thread {'ok' if ok2 else 'failed %d' % ctypes.get_last_error()}")

        class _SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                        ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]
        ps = _SPS()
        if k.GetSystemPowerStatus(ctypes.byref(ps)):
            note.append({0: "on battery", 1: "on AC power"}.get(ps.ACLineStatus, "power unknown")
                        + (", battery saver ON" if ps.SystemStatusFlag else ""))
    except Exception as e:  # noqa: BLE001
        note.append(f"throttling not changed ({e})")
    return "; ".join(note)


def cpu_now():
    """Logical CPU the calling thread runs on right now (Windows), or -1."""
    if sys.platform != "win32":
        return -1
    try:
        import ctypes
        return int(ctypes.windll.kernel32.GetCurrentProcessorNumber())
    except Exception:  # noqa: BLE001
        return -1
