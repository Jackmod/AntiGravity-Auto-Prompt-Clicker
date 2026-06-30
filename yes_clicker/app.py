"""Entry point and CLI flag handling.

    (no flags)   launch the GUI (system tray + window)
    --test       run the live self-test, print PASS/FAIL, exit
    --audit      run the self-audit, print report, exit 0 (ok) / 1 (any fail)
    --stats      print the full statistics report, exit
    --capture    capture/recapture templates interactively, then self-test
    --no-tray    GUI without the system tray (window only)
"""

from __future__ import annotations

import argparse
import sys

from . import __app_name__, __version__, config, paths
from .logger import log


def _relaunch_argv() -> list[str]:
    """Base command that re-invokes this app (for the UI's subprocess actions)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "yes_clicker"]


def _cmd_stats() -> int:
    from .stats import Stats
    print(Stats().report())
    return 0


def _cmd_audit() -> int:
    from .audit import format_audit, run_audit
    worst, checks = run_audit()
    print(format_audit(worst, checks))
    return 1 if worst == "FAIL" else 0


def _cmd_test() -> int:
    from .selftest import run_self_test
    passed, report = run_self_test(config.load())
    print(report)
    return 0 if passed else 1


def _cmd_probe() -> int:
    import time
    from .probe import probe_once
    for i in range(4, 0, -1):
        _safe_print(f"Probing the live screen in {i}s — show the Antigravity prompt now...")
        time.sleep(1)
    detected, report = probe_once(config.load())
    _safe_print(report)
    return 0 if detected else 1


def _cmd_capture() -> int:
    from .capture_tool import run_capture
    paths.ensure_dirs()
    ok = run_capture()
    if not ok:
        _safe_print("Capture incomplete — required templates not saved.")
        return 1
    # Immediately confirm the new templates work — but only when we have a real
    # console to show the result. Launched from the GUI (windowed exe, no stdout)
    # the self-test's mouse movement would be invisible/confusing, so the GUI
    # offers "Run Live Test" instead.
    if sys.stdout is None:
        return 0
    from .selftest import run_self_test
    passed, report = run_self_test(config.load())
    _safe_print(report)
    return 0 if passed else 1


def _safe_print(msg: str) -> None:
    if sys.stdout is not None:
        print(msg)


def _run_gui(use_tray: bool) -> int:
    from .detector import Detector
    from .engine import Engine
    from .hotkeys import PanicHotkey
    from .stats import Stats
    from .ui import App

    paths.ensure_dirs()
    settings = config.load()
    stats = Stats()
    engine = Engine(settings, stats)

    tray = None
    app_holder = {}

    if use_tray:
        from .tray import Tray
        tray = Tray(
            on_show=lambda: app_holder["app"].show_window(),
            on_toggle=lambda: engine.toggle(),
            on_test=lambda: app_holder["app"]._run_test(),
            on_quit=lambda: app_holder["app"].root.after(0, app_holder["app"].quit),
            is_running=lambda: engine.running,
            on_toggle_mute=lambda: app_holder["app"].root.after(
                0, app_holder["app"]._toggle_mute),
            is_muted=lambda: not settings.play_sound,
        )

    app = App(settings, stats, engine, _relaunch_argv(), tray=tray)
    app_holder["app"] = app

    # Double-click tray -> show window (pystray maps default item to activate).
    if tray is not None:
        tray.start()

    # Panic hotkey (F9) from anywhere.
    panic = PanicHotkey(on_panic=engine.panic)
    panic.start()

    engine.start_thread()

    if engine.mode == "ocr":
        # Plug-and-play: reads on-screen text, no setup needed. Just run.
        app._set_banner("Ready — watching for Antigravity prompts (reads screen text, "
                        "no setup needed).", "#2ecc71")
        if settings.auto_start:
            engine.start()
    elif not engine.detector.ready:
        # Non-Windows fallback with no templates captured.
        app._set_banner(
            "OCR not available on this OS — using template mode. Click 'Recapture' "
            "to teach Yes Clicker what the prompt looks like.", "#4ea1ff")
        from tkinter import messagebox
        app.root.after(300, lambda: messagebox.showinfo(
            f"{__app_name__} — setup",
            "Windows text OCR isn't available, so this is using template matching.\n\n"
            "Click 'Recapture' and box the prompt elements to set it up."))
    elif settings.auto_start:
        engine.start()

    try:
        app.run()
    finally:
        panic.stop()
        engine.shutdown()
        if tray:
            tray.stop()
    return 0


def _force_utf8_stdout() -> None:
    """Avoid mojibake for em-dashes etc. on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _force_utf8_stdout()
    parser = argparse.ArgumentParser(prog="yes-clicker", description=f"{__app_name__} — "
                                     "auto-clicks the Yes button in Antigravity prompts.")
    parser.add_argument("--version", action="version",
                        version=f"{__app_name__} {__version__}")
    parser.add_argument("--test", action="store_true", help="run the live self-test and exit")
    parser.add_argument("--audit", action="store_true", help="run the self-audit and exit")
    parser.add_argument("--stats", action="store_true", help="print statistics and exit")
    parser.add_argument("--capture", action="store_true", help="capture/recapture templates")
    parser.add_argument("--probe", action="store_true",
                        help="scan the live screen once and report detection per element")
    parser.add_argument("--no-tray", action="store_true", help="GUI without the system tray")
    args = parser.parse_args(argv)

    if args.stats:
        return _cmd_stats()
    if args.audit:
        return _cmd_audit()
    if args.test:
        return _cmd_test()
    if args.probe:
        return _cmd_probe()
    if args.capture:
        return _cmd_capture()

    log(f"{__app_name__} {__version__} starting (app dir: {paths.APP_DIR})")
    return _run_gui(use_tray=not args.no_tray)


if __name__ == "__main__":
    sys.exit(main())
