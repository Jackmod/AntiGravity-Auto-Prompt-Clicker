"""Mouse clicking with DPI-correct coordinate conversion and safety options.

The detector reports the Yes button in **physical** pixels (mss space). pyautogui
moves in **logical** pixels. ``Monitor.physical_to_logical`` performs the per-
monitor conversion so a click lands correctly even on a mixed-DPI desktop.
"""

from __future__ import annotations

import platform
import time

from . import paths
from .logger import log

_SYS = platform.system()

# Configure pyautogui once. The library's own failsafe (slam mouse to a corner to
# abort) is left ON as an extra panic mechanism alongside F9.
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0  # we control our own timing
except Exception:  # pragma: no cover - import-time display issues
    pyautogui = None


class Clicker:
    def __init__(self, restore_mouse: bool = True, play_sound: bool = True,
                 confirm_enter: bool = True):
        self.restore_mouse = restore_mouse
        self.play_sound = play_sound
        # Press Enter after clicking: Claude Code's prompt is a keyboard menu, and
        # a bare click often selects the row without activating it — Enter confirms.
        # Harmless on a plain GUI button. (Lesson carried from the older tool.)
        self.confirm_enter = confirm_enter

    def click_yes(self, monitor, phys_x: int, phys_y: int) -> tuple[int, int]:
        """Move to and click the Yes button. Returns the logical click point."""
        if pyautogui is None:
            raise RuntimeError("pyautogui unavailable (no display?)")

        lx, ly = monitor.physical_to_logical(phys_x, phys_y)

        origin = None
        if self.restore_mouse:
            origin = pyautogui.position()

        pyautogui.moveTo(lx, ly, duration=0)
        # A real (non-zero-length) press; some GUIs ignore a zero-duration click.
        pyautogui.mouseDown(lx, ly, button="left")
        time.sleep(0.045)
        pyautogui.mouseUp(lx, ly, button="left")

        if self.confirm_enter:
            time.sleep(0.03)
            try:
                pyautogui.press("enter")
            except Exception:
                pass

        if self.play_sound:
            self._beep()

        if origin is not None:
            pyautogui.moveTo(origin[0], origin[1], duration=0)

        return lx, ly

    @staticmethod
    def _beep() -> None:
        try:
            if _SYS == "Windows":
                import winsound
                winsound.Beep(880, 60)
            elif _SYS == "Darwin":
                import subprocess
                subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
            else:
                # Terminal bell as a portable fallback.
                print("\a", end="", flush=True)
        except Exception:
            pass


def nudge_mouse_test() -> bool:
    """Audit helper: move the pointer 1px and back, confirming control works."""
    if pyautogui is None:
        return False
    try:
        x, y = pyautogui.position()
        pyautogui.moveTo(x + 1, y, duration=0)
        pyautogui.moveTo(x, y, duration=0)
        return True
    except Exception:
        return False
