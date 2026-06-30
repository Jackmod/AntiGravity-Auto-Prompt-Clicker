"""PyInstaller build script.

    python build.py            # build for the current platform
    python build.py --clean    # remove build/ dist/ first

Produces:
    Windows : dist/yes-clicker.exe   (--onefile, stripped, trimmed)
    macOS   : dist/Yes Clicker.app
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Stdlib / heavy modules we never import — excluding them shrinks the binary.
# Keep this conservative: pkg_resources (pulled in by PyInstaller's runtime
# hooks) transitively needs email/setuptools/distutils, so excluding those breaks
# startup with "No module named 'email'". Only exclude leaf modules nothing uses.
EXCLUDES = [
    "pytest", "doctest", "lib2to3", "pydoc_data",
    "test", "tkinter.test", "unittest.test",
]


def _clean():
    for d in ("build", "dist"):
        p = ROOT / d
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
    for spec in ROOT.glob("*.spec"):
        spec.unlink()
    print("cleaned build/ dist/ *.spec")


def build():
    name = "Yes Clicker" if IS_MAC else "yes-clicker"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name", name,
        "--strip" if not IS_WIN else "--noupx",  # strip symbols where supported
        "--clean",
        "--noconfirm",
    ]
    for ex in EXCLUDES:
        cmd += ["--exclude-module", ex]

    # winsdk loads its WinRT projections dynamically — bundle the whole package so
    # the on-device OCR works in the frozen exe.
    if IS_WIN:
        cmd += ["--collect-all", "winsdk"]

    # Hidden imports pystray/pynput backends sometimes need spelled out.
    for hidden in ("pystray._win32", "pystray._xorg", "pystray._darwin",
                   "pynput.keyboard._win32", "pynput.mouse._win32"):
        cmd += ["--hidden-import", hidden]

    if IS_MAC:
        cmd += ["--windowed"]

    cmd += ["-m", "yes_clicker"]
    # PyInstaller needs a script path, not -m. Use a tiny launcher shim.
    launcher = ROOT / "_entry.py"
    launcher.write_text("from yes_clicker.app import main\nimport sys\nsys.exit(main())\n",
                        encoding="utf-8")
    cmd[-2:] = [str(launcher)]

    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    launcher.unlink(missing_ok=True)
    if rc == 0:
        print("\nBuild complete. Binary is in dist/.")
        print("Drop your captured templates/ folder next to the executable.")
    return rc


if __name__ == "__main__":
    if "--clean" in sys.argv:
        _clean()
    sys.exit(build())
