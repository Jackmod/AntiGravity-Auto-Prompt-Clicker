"""Global panic hotkey (F9) via pynput.

Works from anywhere — no UI focus required. Best-effort: if pynput is missing or
the OS denies a global listener (e.g. macOS Accessibility not granted), we log a
warning and continue; the in-app Stop button still works.
"""

from __future__ import annotations

from .logger import warn


class PanicHotkey:
    def __init__(self, on_panic, key: str = "f9"):
        self._on_panic = on_panic
        self._key = key
        self._listener = None

    def start(self) -> bool:
        try:
            from pynput import keyboard
        except Exception:
            warn("pynput unavailable — F9 panic hotkey disabled")
            return False

        try:
            target = getattr(keyboard.Key, self._key)
        except AttributeError:
            target = None

        def on_press(k):
            try:
                if target is not None and k == target:
                    self._on_panic()
            except Exception:
                pass

        try:
            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception as e:
            warn(f"could not register F9 hotkey: {e}")
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
