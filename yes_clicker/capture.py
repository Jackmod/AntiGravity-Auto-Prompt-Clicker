"""Screen capture (mss) and foreground-process gating.

mss is used per the spec ("not PIL") because it grabs the raw framebuffer with
no per-frame allocation churn. We return numpy BGR arrays ready for OpenCV and
free the mss buffer immediately.
"""

from __future__ import annotations

import platform

import numpy as np

_SYS = platform.system()


class ScreenCapture:
    """Thread-local mss grabber. One instance per worker thread (mss objects are
    not safe to share across threads)."""

    def __init__(self) -> None:
        import mss
        self._sct = mss.mss()

    def grab_monitor(self, monitor) -> np.ndarray:
        """Grab one monitor as a BGR uint8 array (physical pixels)."""
        region = {
            "left": monitor.left,
            "top": monitor.top,
            "width": monitor.width,
            "height": monitor.height,
        }
        raw = self._sct.grab(region)
        # raw.raw is BGRA; drop alpha. np.asarray avoids a copy of the bytes.
        arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        bgr = arr[:, :, :3]
        # Return a contiguous copy so the mss buffer can be released right away.
        return np.ascontiguousarray(bgr)

    def grab_bgra(self, monitor) -> np.ndarray:
        """Grab one monitor as a BGRA uint8 array (physical pixels).

        Keeps the alpha channel because Windows OCR wants BGRA8 bytes directly,
        which avoids a channel conversion on the hot path.
        """
        region = {"left": monitor.left, "top": monitor.top,
                  "width": monitor.width, "height": monitor.height}
        raw = self._sct.grab(region)
        arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        return np.ascontiguousarray(arr)

    def grab_region_bgra(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        raw = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        return np.ascontiguousarray(arr)

    def grab_region(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        raw = self._sct.grab({"left": left, "top": top, "width": width, "height": height})
        arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        return np.ascontiguousarray(arr[:, :, :3])

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:  # pragma: no cover
            pass


# --- foreground process check --------------------------------------------------

def foreground_process_name() -> str:
    """Lowercased process name of the window currently in the foreground.

    Empty string if it cannot be determined (treated as "unknown" by callers).
    """
    if _SYS == "Windows":
        return _win_foreground()
    if _SYS == "Darwin":
        return _mac_foreground()
    return _linux_foreground()


def _win_foreground() -> str:
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.replace("\\", "/").split("/")[-1].lower()
        finally:
            kernel32.CloseHandle(h)
    except (OSError, AttributeError):
        return ""
    return ""


def _mac_foreground() -> str:
    try:
        from AppKit import NSWorkspace  # type: ignore
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        name = app.localizedName() or ""
        return str(name).lower()
    except Exception:
        return ""


def _linux_foreground() -> str:
    # Best-effort via xdotool if present; otherwise unknown.
    import shutil
    import subprocess
    if not shutil.which("xdotool"):
        return ""
    try:
        wid = subprocess.check_output(
            ["xdotool", "getactivewindow"], text=True, timeout=0.5
        ).strip()
        name = subprocess.check_output(
            ["xdotool", "getwindowname", wid], text=True, timeout=0.5
        ).strip()
        return name.lower()
    except Exception:
        return ""


def foreground_is_target(target_names: list[str]) -> bool:
    """True if the foreground process matches one of the target names.

    Unknown foreground (empty) returns True so we never silently stop working if
    the OS query fails — safety leans toward scanning, the four-element check
    still prevents stray clicks.
    """
    name = foreground_process_name()
    if not name:
        return True
    name = name.lower()
    for t in target_names:
        t = t.lower().strip()
        if t and (t in name or name in t):
            return True
    return False
