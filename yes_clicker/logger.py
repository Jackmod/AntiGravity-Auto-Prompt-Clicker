"""Tiny stdout + file logger. Avoids the stdlib logging boilerplate while still
writing timestamped lines the spec asks for, e.g.

    [14:03:21] Clicked Yes at (1840, 712) monitor #2 confidence 0.94
"""

from __future__ import annotations

import sys
import threading
import time

from . import paths

_lock = threading.Lock()


def _stamp() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    line = f"[{_stamp()}] {msg}"
    with _lock:
        print(line, flush=True)
        try:
            with open(paths.LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def warn(msg: str) -> None:
    log("WARN  " + msg)


def error(msg: str) -> None:
    log("ERROR " + msg)
    sys.stderr.flush()
