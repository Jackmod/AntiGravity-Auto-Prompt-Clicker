"""Per-monitor DPI / scaling detection and coordinate-space conversion.

The hard problem this module solves (Windows, mixed-DPI):
  * mss captures **physical** pixels (the raw framebuffer).
  * pyautogui clicks in **logical** pixels (the virtual desktop coordinate space
    Windows exposes to mouse APIs).
On a 150%-scaled monitor those two spaces differ by 1.5x, so a match found in the
mss image must be divided by the monitor's scale before being handed to
pyautogui. On macOS the Retina backing-scale factor plays the same role.

Detection is re-run cheaply each scan cycle (``Monitors.refresh``) so plugging in
a display or changing scaling is picked up without a restart.
"""

from __future__ import annotations

import ctypes
import platform
from dataclasses import dataclass

import mss

_SYS = platform.system()


@dataclass
class Monitor:
    index: int          # 1-based, matches mss (0 is the "all monitors" virtual)
    left: int           # physical-pixel bounds from mss
    top: int
    width: int
    height: int
    scale: float = 1.0  # physical / logical ratio for this monitor

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains_physical(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def physical_to_logical(self, x: int, y: int) -> tuple[int, int]:
        """Map a physical (mss) point to the logical point pyautogui expects.

        We anchor on the monitor's own origin so each display converts in its own
        space; this is what makes mixed-DPI layouts land correctly.
        """
        lx = self.left + (x - self.left) / self.scale
        ly = self.top + (y - self.top) / self.scale
        return int(round(lx)), int(round(ly))

    def logical_to_physical(self, x: int, y: int) -> tuple[int, int]:
        """Inverse of :meth:`physical_to_logical` — logical (Tk/pyautogui) to the
        physical (mss) framebuffer point. Used to crop a screenshot at a widget's
        on-screen position."""
        px = self.left + (x - self.left) * self.scale
        py = self.top + (y - self.top) * self.scale
        return int(round(px)), int(round(py))


# --- Windows scale detection ---------------------------------------------------

def _win_set_dpi_aware() -> None:
    """Ask Windows for per-monitor-v2 DPI awareness so GetDpiForMonitor and the
    captured framebuffer agree. Best-effort; ignored on failure / older OS."""
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _win_scales() -> dict[tuple[int, int], float]:
    """Map (left, top) physical origin -> scale factor for every monitor."""
    scales: dict[tuple[int, int], float] = {}
    try:
        shcore = ctypes.windll.shcore
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        return scales

    MONITOR_DPI_TYPE_EFFECTIVE = 0
    monitors: list[int] = []

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_long), ctypes.c_double,
    )

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    def _cb(hmon, hdc, lprect, data):
        monitors.append(hmon)
        return 1

    try:
        user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(_cb), 0)
    except OSError:
        return scales

    for hmon in monitors:
        dpix = ctypes.c_uint()
        dpiy = ctypes.c_uint()
        try:
            shcore.GetDpiForMonitor(
                hmon, MONITOR_DPI_TYPE_EFFECTIVE,
                ctypes.byref(dpix), ctypes.byref(dpiy),
            )
        except OSError:
            continue
        # Physical origin of this monitor.
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                        ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        try:
            user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        except OSError:
            continue
        scale = dpix.value / 96.0 if dpix.value else 1.0
        scales[(info.rcMonitor.left, info.rcMonitor.top)] = scale
    return scales


# --- macOS scale detection -----------------------------------------------------

def _mac_scales() -> list[float]:
    try:
        from AppKit import NSScreen  # type: ignore
    except ImportError:
        return []
    out = []
    for screen in NSScreen.screens():
        try:
            out.append(float(screen.backingScaleFactor()))
        except Exception:  # pragma: no cover - AppKit edge cases
            out.append(1.0)
    return out


# --- public API ----------------------------------------------------------------

class Monitors:
    """Snapshot of all monitors with their scale factors. Cheap to refresh."""

    def __init__(self) -> None:
        if _SYS == "Windows":
            _win_set_dpi_aware()
        self.monitors: list[Monitor] = []
        self._signature: tuple = ()
        self.refresh(force=True)

    def refresh(self, force: bool = False) -> bool:
        """Re-detect monitors. Returns True if the layout/DPI changed."""
        with mss.mss() as sct:
            raw = sct.monitors  # [0] = virtual full desktop, [1..] = each monitor
        signature = tuple(
            (m["left"], m["top"], m["width"], m["height"]) for m in raw[1:]
        )
        if not force and signature == self._signature:
            return False
        self._signature = signature

        win_scales = _win_scales() if _SYS == "Windows" else {}
        mac_scales = _mac_scales() if _SYS == "Darwin" else []

        mons: list[Monitor] = []
        for i, m in enumerate(raw[1:], start=1):
            scale = 1.0
            if _SYS == "Windows":
                scale = win_scales.get((m["left"], m["top"]), _guess_scale(m))
            elif _SYS == "Darwin" and i - 1 < len(mac_scales):
                scale = mac_scales[i - 1]
            mons.append(Monitor(i, m["left"], m["top"], m["width"], m["height"], scale))
        self.monitors = mons
        return True

    def scales(self) -> list[float]:
        """Distinct scale factors detected, for driving multi-scale matching."""
        uniq = sorted({round(m.scale, 3) for m in self.monitors})
        return uniq or [1.0]

    def find_for_physical(self, x: int, y: int) -> Monitor | None:
        for m in self.monitors:
            if m.contains_physical(x, y):
                return m
        return None


def _guess_scale(_m: dict) -> float:
    """Fallback when GetDpiForMonitor is unavailable: assume unscaled."""
    return 1.0


def template_match_scales(detected: list[float]) -> list[float]:
    """Scales at which to run template matching.

    Derived from runtime DPI detection (never hardcoded): the captured templates
    were grabbed at some monitor's scale, so we try the ratios between detected
    scales plus the common steps so a template captured on one monitor still
    matches on another with different DPI.
    """
    base = set()
    for s in detected or [1.0]:
        base.add(round(s, 3))
        for other in detected or [1.0]:
            if other:
                base.add(round(s / other, 3))
    # Keep it sane: only plausible UI scale ratios.
    return sorted(x for x in base if 0.5 <= x <= 2.5)
