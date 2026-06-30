"""System tray icon.

Green = running, red = stopped. The icon is only re-rendered on a state change
(never on a timer), per the spec. Right-click menu: Show Window, Start/Stop, Run
Live Test, Quit. Double-click restores the window.

pystray is used cross-platform (it has Windows, X11 and Darwin backends) and runs
in a daemon thread so the tkinter main loop keeps the UI thread free. On macOS,
where AppKit insists on the main thread, the tray is best-effort — the main
window remains fully functional if the tray can't start (see README); rumps is
documented there as the native alternative.
"""

from __future__ import annotations

import threading

from .logger import warn


def _make_icon_image(color: str):
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([6, 6, size - 6, size - 6], fill=color)
    # A small check mark to read as "clicker".
    d.line([(20, 34), (29, 44), (46, 22)], fill="white", width=6, joint="curve")
    return img


class Tray:
    def __init__(self, on_show, on_toggle, on_test, on_quit, is_running,
                 on_toggle_mute=None, is_muted=None):
        self.on_show = on_show
        self.on_toggle = on_toggle
        self.on_test = on_test
        self.on_quit = on_quit
        self.is_running = is_running  # callable -> bool
        self.on_toggle_mute = on_toggle_mute
        self.is_muted = is_muted  # callable -> bool
        self._icon = None
        self._thread = None
        self._running_state = None

    def _build_menu(self):
        import pystray
        running = self.is_running()
        toggle_label = "Stop" if running else "Start"
        items = [
            pystray.MenuItem("Show Window", lambda: self.on_show(), default=True),
            pystray.MenuItem(toggle_label, lambda: self.on_toggle()),
            pystray.MenuItem("Run Live Test", lambda: self.on_test()),
        ]
        if self.on_toggle_mute is not None:
            muted = self.is_muted() if self.is_muted else False
            items.append(pystray.MenuItem(
                "Unmute sound" if muted else "Mute sound",
                lambda: self.on_toggle_mute()))
        items += [pystray.Menu.SEPARATOR,
                  pystray.MenuItem("Quit", lambda: self.on_quit())]
        return pystray.Menu(*items)

    def start(self) -> bool:
        try:
            import pystray  # noqa: F401
        except Exception:
            warn("pystray unavailable — tray disabled (window still works)")
            return False

        try:
            import pystray
            running = self.is_running()
            self._running_state = running
            color = "#2ecc71" if running else "#e74c3c"
            self._icon = pystray.Icon(
                "yes_clicker",
                icon=_make_icon_image(color),
                title="Yes Clicker",
                menu=self._build_menu(),
            )
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            warn(f"could not start tray: {e}")
            return False

    def update_state(self) -> None:
        """Re-colour the icon and rebuild the menu — ONLY when state changed."""
        if self._icon is None:
            return
        running = self.is_running()
        if running == self._running_state:
            return
        self._running_state = running
        try:
            self._icon.icon = _make_icon_image("#2ecc71" if running else "#e74c3c")
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:
            pass

    def refresh_menu(self) -> None:
        """Rebuild the menu (e.g. after the mute state changed)."""
        if self._icon is None:
            return
        try:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = "Yes Clicker") -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
