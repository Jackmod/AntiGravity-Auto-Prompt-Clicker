"""Self-audit (--audit flag / "Audit" button).

Each check returns PASS / WARN / FAIL plus a fix hint. ``run_audit`` returns the
overall worst status so the CLI can exit 0 (all pass/warn) or 1 (any fail).
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

import cv2
import numpy as np

from . import paths
from .capture import ScreenCapture
from .clicker import nudge_mouse_test
from .detector import ANCHORS, Detector
from .dpi import Monitors, template_match_scales
from .stats import Stats

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}
_SYS = platform.system()


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _detection_check() -> Check:
    """Prefer OCR (zero-config). Only fall back to template files if OCR is absent."""
    from .ocr_detector import TextPromptDetector
    det = TextPromptDetector()
    if det.available:
        return Check("Detection engine", PASS,
                     "Windows OCR available — no templates needed (plug-and-play)")
    # OCR unavailable: report on template files instead.
    tmpl = _templates_check()
    tmpl.name = "Detection engine (OCR unavailable, template fallback)"
    return tmpl


def _templates_check() -> Check:
    missing_required = []
    info = []
    for role, path, required in ANCHORS:
        if path.exists():
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                missing_required.append(path.name) if required else None
                info.append(f"{path.name}: UNREADABLE")
            else:
                size = path.stat().st_size
                info.append(f"{path.name}: {img.shape[1]}x{img.shape[0]}px, {size}B")
        elif required:
            missing_required.append(path.name)
            info.append(f"{path.name}: MISSING (required)")
        else:
            info.append(f"{path.name}: not captured (optional)")
    detail = "; ".join(info)
    if missing_required:
        return Check("Templates", FAIL, detail,
                     "Run `yes-clicker --capture` to capture the required templates.")
    return Check("Templates", PASS, detail)


def _capture_check() -> Check:
    try:
        cap = ScreenCapture()
        mons = Monitors().monitors
        if not mons:
            return Check("Screen capture", FAIL, "no monitors detected",
                         "Check display connection / OS permissions.")
        frame = cap.grab_monitor(mons[0])
        nonzero = int(np.count_nonzero(frame))
        cap.close()
        if nonzero == 0:
            return Check("Screen capture", FAIL, "captured an all-black frame",
                         "On macOS grant Screen Recording permission to this app.")
        return Check("Screen capture", PASS, f"grabbed {frame.shape[1]}x{frame.shape[0]}, "
                                             f"{nonzero} non-zero pixels")
    except Exception as e:
        return Check("Screen capture", FAIL, str(e), "Ensure mss is installed.")


def _mouse_check() -> Check:
    if nudge_mouse_test():
        return Check("Mouse control", PASS, "moved pointer 1px and back")
    return Check("Mouse control", FAIL, "pyautogui could not move the mouse",
                 "Install pyautogui; on macOS grant Accessibility permission.")


def _accessibility_check() -> Check:
    if _SYS != "Darwin":
        return Check("macOS Accessibility", PASS, "n/a on this platform")
    granted = _mac_accessibility_granted()
    if granted is True:
        return Check("macOS Accessibility", PASS, "permission granted")
    if granted is False:
        return Check("macOS Accessibility", FAIL, "permission NOT granted",
                     "System Settings > Privacy & Security > Accessibility -> enable Yes Clicker.")
    return Check("macOS Accessibility", WARN, "could not determine permission state",
                 "If clicks don't register, grant Accessibility permission.")


def _mac_accessibility_granted():
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore
        return bool(AXIsProcessTrusted())
    except Exception:
        return None


class _FakeMon:
    index = 1
    left = top = 0
    width = 1920
    height = 1080
    right = 1920
    bottom = 1080
    scale = 1.0


def _false_positive_check() -> Check:
    """Run the matcher against a blank screen — there must be NO match."""
    from .ocr_detector import TextPromptDetector
    ocr = TextPromptDetector()
    if ocr.available:
        blank = np.full((1080, 1920, 4), 30, dtype=np.uint8)
        dets = ocr.scan(blank, _FakeMon())
        if dets:
            return Check("False-positive risk", FAIL, "detected a prompt on a blank screen",
                         "Report this — the text anchors are too loose.")
        return Check("False-positive risk", PASS, "no detection on a blank screen")

    det = Detector()
    if not det.ready:
        return Check("False-positive risk", WARN, "no OCR and no templates, cannot test",
                     "Capture templates first.")
    blank = np.full((1080, 1920, 3), 30, dtype=np.uint8)
    dets = det.scan(blank, _FakeMon(), template_match_scales([1.0]))
    if dets:
        return Check("False-positive risk", FAIL, f"matched {len(dets)} dialog(s) on a blank screen",
                     "Raise the confidence threshold or recapture cleaner templates.")
    return Check("False-positive risk", PASS, "no match on a blank screen")


def _dpi_check() -> Check:
    mons = Monitors()
    if not mons.monitors:
        return Check("DPI / monitors", FAIL, "no monitors detected", "")
    lines = []
    for m in mons.monitors:
        lines.append(f"#{m.index} {m.width}x{m.height} @ scale {m.scale:g}")
    scales = template_match_scales(mons.scales())
    detail = "; ".join(lines) + f" | match scales: {scales}"

    det = Detector()
    if det.ready:
        # Confirm the templates match at the primary monitor's scale via a render
        # check is out of scope here; we just confirm scale list is non-empty.
        if not scales:
            return Check("DPI / monitors", WARN, detail, "No usable match scales derived.")
    return Check("DPI / monitors", PASS, detail)


def _history_check() -> Check:
    ok, detail = Stats().is_valid_file()
    if ok:
        return Check("Click history", PASS, detail)
    return Check("Click history", FAIL, detail,
                 "Delete or fix clicks.json (it must be a JSON list).")


def run_audit() -> tuple[str, list[Check]]:
    checks = [
        _detection_check(),
        _capture_check(),
        _mouse_check(),
        _accessibility_check(),
        _false_positive_check(),
        _dpi_check(),
        _history_check(),
    ]
    worst = PASS
    for c in checks:
        if _RANK[c.status] > _RANK[worst]:
            worst = c.status
    return worst, checks


def format_audit(worst: str, checks: list[Check]) -> str:
    lines = ["Yes Clicker — self-audit", "=" * 32]
    for c in checks:
        lines.append(f"[{c.status}] {c.name}: {c.detail}")
        if c.status != PASS and c.fix:
            lines.append(f"        fix: {c.fix}")
    lines.append("")
    lines.append(f"OVERALL: {worst}")
    return "\n".join(lines)
