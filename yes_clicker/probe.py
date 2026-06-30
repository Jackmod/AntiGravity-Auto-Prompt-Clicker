"""One-shot detection probe against the *live* screen.

Scans whatever is on screen right now and reports, per monitor, whether a real
prompt was detected. In OCR mode it also dumps the text lines it read near the
prompt, so if detection fails you can see exactly what the screen said.
"""

from __future__ import annotations

from . import config
from .capture import ScreenCapture
from .dpi import Monitors
from .ocr_detector import TextPromptDetector, _norm


def probe_once(settings: config.Settings) -> tuple[bool, str]:
    monitors = Monitors()
    detector = TextPromptDetector(settings)

    if not detector.available:
        # Fall back to the template detector's probe behaviour.
        return _template_probe(settings, monitors)

    capture = ScreenCapture()
    lines_out = ["Detection probe (live screen, OCR mode)", "=" * 38, ""]
    detected_any = False
    try:
        from .ocr_detector import (HEADER_TOKEN_SETS, FOOTER_SUBSTRINGS,
                                    _is_yes_option, _is_no_option)
        for mon in monitors.monitors:
            frame = capture.grab_bgra(mon)
            ocr_lines = detector.ocr.recognize(frame)
            groups = detector._find_dialogs(ocr_lines)
            dets = detector.scan(frame, mon)

            lines_out.append(f"Monitor #{mon.index} ({mon.width}x{mon.height}) — "
                             f"{len(ocr_lines)} text lines read")
            if groups:
                detected_any = detected_any or bool(dets)
                for r in groups:
                    yes_t = r["yes"].text if r["yes"] else "(not read - using bar)"
                    no_t = r["no"].text if r["no"] else "-"
                    lines_out.append(f"  -> PROMPT confirmed: yes={yes_t!r}, "
                                     f"no={no_t!r}, footer={r['anchor'].text!r}")
                if dets:
                    for d in dets:
                        lines_out.append(f"     would click Yes at ({d.yes_x},{d.yes_y}) "
                                         f"conf {d.confidence:.2f}")
                else:
                    lines_out.append("     STRICT mode is ON but no highlight bar was seen "
                                     "-> NOT clicked. Untick Strict if this is a real prompt.")
            else:
                # Show exactly what OCR read for each part so failures are diagnosable.
                def matches(pred):
                    return [l.text for l in ocr_lines if pred(_norm(l.text))][:6]
                hdr = matches(lambda t: any(all(k in t for k in toks)
                                            for toks in HEADER_TOKEN_SETS))
                ftr = matches(lambda t: any(s in t for s in FOOTER_SUBSTRINGS))
                yopt = matches(_is_yes_option)
                nopt = matches(_is_no_option)
                raw_yn = [l.text for l in ocr_lines
                          if "yes" in _norm(l.text) or "no" in _norm(l.text)][:8]
                lines_out.append("  group didn't form — what OCR read for each part:")
                lines_out.append(f"     headers:  {hdr or 'NONE'}")
                lines_out.append(f"     footers:  {ftr or 'NONE'}")
                lines_out.append(f"     yes opts: {yopt or 'NONE'}")
                lines_out.append(f"     no opts:  {nopt or 'NONE'}")
                lines_out.append(f"     raw lines with yes/no: {raw_yn or 'NONE'}")
                lines_out.append("  -> no confirmed prompt on this monitor")
            del frame
            lines_out.append("")
    finally:
        capture.close()

    if detected_any:
        lines_out.append("RESULT: prompt DETECTED — the clicker would click it.")
    else:
        lines_out.append("RESULT: no prompt detected.")
        lines_out.append("If a real prompt is on screen but not detected, copy the")
        lines_out.append("'relevant text seen' lines above so the matching can be tuned.")
    return detected_any, "\n".join(lines_out)


def _template_probe(settings, monitors):
    import cv2
    from .detector import Detector
    from .dpi import template_match_scales
    detector = Detector(confidence=settings.confidence_threshold)
    if not detector.ready:
        return False, ("No OCR and no templates — capture templates with Recapture.\n"
                       f"Missing: {', '.join(detector.missing_required) or 'yes_button'}")
    scales = template_match_scales(monitors.scales())
    capture = ScreenCapture()
    out = ["Detection probe (template mode)", "=" * 32, ""]
    detected = False
    try:
        for mon in monitors.monitors:
            frame = capture.grab_monitor(mon)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for t in detector.templates:
                conf, *_ = detector._best(gray, t.gray, scales)
                mark = "OK " if conf >= settings.confidence_threshold else "low"
                out.append(f"  {t.role:7s} {conf:.2f} [{mark}]")
            dets = detector.scan(frame, mon, scales)
            del frame, gray
            if dets:
                detected = True
                out.append(f"  -> CONFIRMED on monitor #{mon.index}")
            out.append("")
    finally:
        capture.close()
    out.append("RESULT: " + ("DETECTED" if detected else "not detected"))
    return detected, "\n".join(out)
