"""Live self-test (--test flag / "Run Live Test" button).

Renders the pixel-faithful replica dialog on screen, then drives the REAL
detection + click pipeline against the live framebuffer:

    dialog rendered -> detector finds it -> mouse physically moves to Yes ->
    click fires -> replica's Yes widget confirms the click landed on it.

PASS only if every link in that chain holds. FAIL (with the exact broken link) or
timeout (5s) otherwise. If real templates aren't captured yet, synthetic
templates are cropped from the replica so the pipeline can still be exercised.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk

import cv2
import numpy as np

from . import config
from .capture import ScreenCapture
from .clicker import Clicker
from .detector import Detector
from .dpi import Monitors, template_match_scales
from .replica import make_replica_window

TIMEOUT_S = 5.0


class _Result:
    def __init__(self):
        self.detected = False
        self.detection = None
        self.moved = False
        self.click_logical = None
        self.confirmed = False
        self.reason = ""
        self.done = threading.Event()
        self.confidence = 0.0
        self.used_synthetic = False


def _crop_template(full_phys: np.ndarray, monitor, bounds) -> np.ndarray | None:
    if bounds is None:
        return None
    px1, py1 = monitor.logical_to_physical(bounds.x, bounds.y)
    px2, py2 = monitor.logical_to_physical(bounds.x + bounds.w, bounds.y + bounds.h)
    x1 = max(0, px1 - monitor.left)
    y1 = max(0, py1 - monitor.top)
    x2 = min(full_phys.shape[1], px2 - monitor.left)
    y2 = min(full_phys.shape[0], py2 - monitor.top)
    if x2 - x1 < 6 or y2 - y1 < 6:
        return None
    crop = full_phys[y1:y2, x1:x2]
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def run_self_test(settings: config.Settings) -> tuple[bool, str]:
    result = _Result()
    monitors = Monitors()
    capture = ScreenCapture()

    root, dialog = make_replica_window()
    # Let the window paint before we screenshot/scan.
    root.update()
    root.update_idletasks()

    def worker():
        try:
            time.sleep(0.4)  # ensure compositor has drawn the window
            yes_cx, yes_cy = dialog.yes_center_screen()  # logical coords
            # Determine which monitor the dialog sits on (by logical point).
            mon = _monitor_for_logical(monitors, yes_cx, yes_cy)
            if mon is None:
                result.reason = "could not locate the monitor containing the dialog"
                result.done.set()
                return

            # Prefer the real OCR detector (what production uses). The replica draws
            # real text, so OCR genuinely detects it — a true end-to-end test.
            from .ocr_detector import TextPromptDetector
            ocr = TextPromptDetector(settings)
            if ocr.available:
                frame = capture.grab_bgra(mon)
                dets = ocr.scan(frame, mon)
                del frame
            else:
                frame = capture.grab_monitor(mon)
                detector = Detector(confidence=settings.confidence_threshold)
                if not detector.ready:
                    result.used_synthetic = True
                    grays = {}
                    for role in ("header", "yes", "no", "input", "footer"):
                        g = _crop_template(frame, mon, dialog.element_bounds(role))
                        if g is not None:
                            grays[role] = g
                    detector.set_templates(grays)
                    if not detector.ready:
                        result.reason = "failed to build templates from the replica"
                        result.done.set()
                        return
                scales = template_match_scales(monitors.scales())
                dets = detector.scan(frame, mon, scales)
                del frame

            if not dets:
                result.reason = (f"dialog NOT detected "
                                 f"(best confidence {detector.last_best_confidence:.2f} "
                                 f"< threshold {settings.confidence_threshold:.2f})")
                result.done.set()
                return

            # Pick the detection closest to the known Yes centre.
            tx, ty = mon.logical_to_physical(yes_cx, yes_cy)
            det = min(dets, key=lambda d: (d.yes_x - tx) ** 2 + (d.yes_y - ty) ** 2)
            result.detected = True
            result.detection = det
            result.confidence = det.confidence

            clicker = Clicker(restore_mouse=False, play_sound=False, confirm_enter=False)
            lx, ly = clicker.click_yes(mon, det.yes_x, det.yes_y)
            result.moved = True
            result.click_logical = (lx, ly)
        except Exception as e:
            result.reason = f"pipeline error: {e}"
        finally:
            # Give Tk a moment to dispatch the synthetic mouse event.
            time.sleep(0.2)
            result.done.set()

    threading.Thread(target=worker, daemon=True).start()

    start = time.time()

    def poll():
        if result.done.is_set() or (time.time() - start) > TIMEOUT_S:
            result.confirmed = dialog.clicked_on_yes
            try:
                root.destroy()
            except tk.TclError:
                pass
            return
        root.after(50, poll)

    root.after(50, poll)
    try:
        root.mainloop()
    except tk.TclError:
        pass
    capture.close()

    return _verdict(result)


def _monitor_for_logical(monitors: Monitors, lx: int, ly: int):
    for m in monitors.monitors:
        # Convert the monitor's physical bounds back to logical for comparison.
        l1, t1 = m.physical_to_logical(m.left, m.top)
        l2, t2 = m.physical_to_logical(m.right, m.bottom)
        if l1 <= lx < l2 and t1 <= ly < t2:
            return m
    return monitors.monitors[0] if monitors.monitors else None


def _verdict(r: _Result) -> tuple[bool, str]:
    lines = ["Yes Clicker — live self-test", "=" * 32]
    if r.used_synthetic:
        lines.append("(using synthetic templates cropped from the replica — capture")
        lines.append(" real templates with --capture for a production-accurate test)")
        lines.append("")

    def mark(ok, label, extra=""):
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + extra) if extra else ''}")

    mark(r.detected, "dialog detected",
         f"confidence {r.confidence:.2f}" if r.detected else r.reason)
    mark(r.moved, "mouse moved to Yes button",
         f"clicked at {r.click_logical}" if r.click_logical else "")
    mark(r.confirmed, "click confirmed on Yes button"
         if r.confirmed else "click confirmed on Yes button",
         "" if r.confirmed else (r.reason or "click did not land on Yes / timed out"))

    passed = r.detected and r.moved and r.confirmed
    lines.append("")
    lines.append("RESULT: " + ("PASS - full pipeline works" if passed
                               else "FAIL - see the failed step above"))
    return passed, "\n".join(lines)
