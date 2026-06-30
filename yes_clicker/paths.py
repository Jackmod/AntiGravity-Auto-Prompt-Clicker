"""Filesystem locations for templates, settings and click history.

Everything lives next to the executable (when frozen by PyInstaller) or next to
the package source (when run from source), exactly as the spec requires:
"Templates saved in same folder as the executable".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Folder that holds templates / settings / clicks.json.

    When frozen with PyInstaller --onefile, ``sys.executable`` is the exe and
    its parent is where the user dropped it. When running from source we use the
    project root (parent of this package).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_DIR = app_dir()
TEMPLATE_DIR = APP_DIR / "templates"

# Template files. Header + yes button are required; footer + list are optional
# stricter anchors used by the four-element safety confirmation.
HEADER_TEMPLATE = TEMPLATE_DIR / "dialog_header.png"
YES_TEMPLATE = TEMPLATE_DIR / "yes_button.png"
FOOTER_TEMPLATE = TEMPLATE_DIR / "footer.png"      # "Esc to cancel"
LIST_TEMPLATE = TEMPLATE_DIR / "no_button.png"     # "2 No" row
INPUT_TEMPLATE = TEMPLATE_DIR / "input_field.png"  # "Tell Claude what to do instead"

SETTINGS_FILE = APP_DIR / "settings.json"
CLICKS_FILE = APP_DIR / "clicks.json"
LOG_FILE = APP_DIR / "yes-clicker.log"


def ensure_dirs() -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


def resource_path(rel: str) -> Path:
    """Path to a bundled read-only resource (icons baked into the build)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / rel
    return Path(__file__).resolve().parent / rel
