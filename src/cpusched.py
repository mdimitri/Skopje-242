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
