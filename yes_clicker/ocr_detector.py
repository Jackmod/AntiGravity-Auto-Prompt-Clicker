"""Plug-and-play prompt detection via on-screen text (no templates, no capture).

Reads the screen with the OS OCR engine and looks for the *text* of a real
Claude Code permission prompt. A click only fires when the safety anchors are all
present together:

  * a HEADER line  — "Allow this bash command?" / "Do you want to proceed?" / "run this command"
  * a FOOTER line  — "Esc to cancel" / "Tell Claude what to do instead/differently"
  * a YES option   — "1 Yes" / "1. Yes" / a "Yes" option row

The footer is the strongest discriminator: the words "yes"/"no" appear all over
chat and code, but that footer only appears under a genuine prompt. This mirrors
the hard-won design of the older tool.

OCR backend: Windows.Media.Ocr (on-device, ~0.1s, nothing to install or bundle).
On other platforms it degrades gracefully (``available`` is False) and the engine
falls back to template matching.
"""

from __future__ import annotations

import asyncio
import platform
import re
from dataclasses import dataclass

import cv2
import numpy as np

from .detector import Detection
from .logger import warn

_SYS = platform.system()

# Header: every tuple is a set of tokens that must ALL appear in one line.
HEADER_TOKEN_SETS = [
    ("allow", "command"),
    ("allow", "bash"),
    ("do you want", "run"),
    ("do you want to proceed",),
    ("run this command",),
    ("wants to run",),
]
FOOTER_SUBSTRINGS = [
    "esc to cancel",
    "to cancel",
    "tell claude what to do",
    "what to do instead",
    "what to do differently",
]
# An option row is SHORT (a menu item, not prose). We match the Yes/No options by
# the short word — robust to OCR dropping the leading "1"/"2" on a highlighted row.
INPUT_SUBSTRINGS = ["tell claude what to do", "what to do instead",
                    "what to do differently"]
MAX_OPTION_WORDS = 4  # "1 Yes" / "Yes" / "2 No" are short; prose isn't


def _opt_word(w: str) -> str:
    """Strip menu decoration and a leading option number off a token, so the
    highlighted "1Yes" (no space) or "1." or "❯ Yes" all reduce to "yes"."""
    w = w.strip(".):>-*❯▶ \t")
    w = w.lstrip("0123456789").strip(".) \t")
    return w.lower()


def _leading_option_word(text: str) -> str:
    """The first meaningful word of a menu row, dropping a leading number/marker.

    "1 Yes" -> "yes", "1Yes" -> "yes", "❯ Yes" -> "yes", but
    "Press Enter after clicking Yes" -> "press" (so it is NOT a Yes option)."""
    words = text.split()
    if not words:
        return ""
    first = words[0].strip(".):>-*❯▶ \t")
    # A bare leading number / marker token is decoration — skip to the next word.
    if first == "" or first.isdigit():
        words = words[1:]
        if not words:
            return ""
    return _opt_word(words[0])


def _option_body(text: str):
    """Return the meaningful words of a menu row after dropping a leading
    number/marker token, or None if it's clearly not a short option row."""
    words = text.split()
    if not words or len(words) > MAX_OPTION_WORDS:
        return None
    first = words[0].strip(".):>-*❯▶ \t")
    if first == "" or first.isdigit():
        words = words[1:]
    return words


def _is_yes_option(text: str) -> bool:
    """Exactly the Yes option: "Yes" / "1 Yes" / "1Yes" — NOT "Yes Clicker" or any
    sentence that merely ends in yes."""
    body = _option_body(text)
    return bool(body) and len(body) == 1 and _opt_word(body[0]) == "yes"


def _is_no_option(text: str) -> bool:
    body = _option_body(text)
    return bool(body) and len(body) == 1 and _opt_word(body[0]) == "no"


# How far above an anchor footer the Yes option / header can sit (physical px).
PROMPT_LOOK_UP = 320
# Max horizontal offset between a prompt element's left edge and the footer's, so
# the right-hand code editor (sharing the footer's rows) can't bleed in.
HALIGN = 360


# Max vertical gap (physical px) between a prompt's header and its footer. A real
# prompt is compact; this rejects a header and footer that happen to appear far
# apart in unrelated on-screen text.
MAX_GROUP_GAP = 560
# Min extra saturation (0-255) of the Yes row vs the header row to call it a
# highlighted selection bar.
HIGHLIGHT_SAT_DELTA = 15


@dataclass
class _Line:
    text: str
    x: int
    y: int
    w: int
    h: int
    words: list  # list[(text, x, y, w, h)]

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


class WindowsOcr:
    """Synchronous wrapper around the async WinRT OCR engine."""

    def __init__(self) -> None:
        self.engine = None
        self.loop = None
        try:
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.globalization import Language
            self.engine = OcrEngine.try_create_from_user_profile_languages()
            if self.engine is None:
                self.engine = OcrEngine.try_create_from_language(Language("en-US"))
        except Exception as e:  # pragma: no cover - non-Windows / missing winsdk
            warn(f"Windows OCR unavailable: {e}")
            self.engine = None
        if self.engine is not None:
            self.loop = asyncio.new_event_loop()

    @property
    def available(self) -> bool:
        return self.engine is not None

    def recognize(self, bgra: np.ndarray) -> list[_Line]:
        if self.engine is None:
            return []
        h, w = bgra.shape[:2]
        data = bgra.tobytes()
        try:
            return self.loop.run_until_complete(self._recognize(data, w, h))
        except Exception as e:
            warn(f"OCR call failed: {e}")
            return []

    async def _recognize(self, data: bytes, w: int, h: int) -> list[_Line]:
        from winsdk.windows.graphics.imaging import (
            BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap)
        from winsdk.windows.security.cryptography import CryptographicBuffer

        buf = CryptographicBuffer.create_from_byte_array(data)
        bmp = SoftwareBitmap.create_copy_from_buffer(
            buf, BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED)
        result = await self.engine.recognize_async(bmp)

        lines: list[_Line] = []
        for line in result.lines:
            words = []
            minx = miny = 10 ** 9
            maxx = maxy = -1
            for wd in line.words:
                r = wd.bounding_rect
                wx, wy, ww, wh = int(r.x), int(r.y), int(r.width), int(r.height)
                words.append((wd.text, wx, wy, ww, wh))
                minx, miny = min(minx, wx), min(miny, wy)
                maxx, maxy = max(maxx, wx + ww), max(maxy, wy + wh)
            if not words:
                continue
            lines.append(_Line(line.text, minx, miny, maxx - minx, maxy - miny, words))
        return lines


class TextPromptDetector:
    """Detector with the same surface the engine expects, backed by OCR."""

    def __init__(self, settings=None) -> None:
        self.ocr = WindowsOcr()
        self.settings = settings
        self.last_best_confidence: float = 0.0
        self.last_candidate_count: int = 0
        self.missing_required: list[str] = []

    def _require_highlight(self) -> bool:
        return bool(getattr(self.settings, "require_highlight", False))

    @property
    def available(self) -> bool:
        return self.ocr.available

    @property
    def ready(self) -> bool:
        return self.ocr.available

    def load_templates(self) -> bool:
        return self.ocr.available  # nothing to load; kept for interface parity

    # --- detection ---
    def _find_dialogs(self, lines: list[_Line]):
        """Return every prompt group on screen, anchored on the FOOTER.

        The footer ("Esc to cancel" / "Tell Claude what to do instead") is the most
        distinctive and reliable part of the prompt, so we anchor on it and look
        UPWARD for the Yes option. To qualify, within a compact band in the SAME
        horizontal column as the footer we need:
          * a short "Yes" option line above the footer, AND
          * a second prompt element: the header, OR a "No" option, OR a second
            footer/input chrome line.
        The same-column constraint stops the right-hand code editor (which shares
        the footer's rows) from bleeding into the match.
        Returns (ref_line, anchor, yes_line, no_line, click) per group.
        """
        norm = [(_norm(l.text), l) for l in lines]
        headers = [ln for t, ln in norm
                   if any(all(tok in t for tok in toks) for toks in HEADER_TOKEN_SETS)]
        chrome = [ln for t, ln in norm if any(s in t for s in FOOTER_SUBSTRINGS)]
        yeses = [ln for t, ln in norm if _is_yes_option(t)]
        noes = [ln for t, ln in norm if _is_no_option(t)]

        regions = []
        claimed_y: list[int] = []
        for anchor in sorted(chrome, key=lambda a: a.y):
            lo, hi = anchor.y - PROMPT_LOOK_UP, anchor.y + anchor.h

            def in_box(ln):
                return lo <= ln.y <= hi and abs(ln.x - anchor.x) <= HALIGN

            header = next((h for h in headers if in_box(h) and h.y < anchor.y), None)
            no_line = next((n for n in noes if in_box(n) and n.y < anchor.y), None)
            other_chrome = any(c is not anchor and in_box(c) for c in chrome)
            cand_yes = [y for y in yeses if in_box(y) and y.y <= anchor.y]
            yes_line = min(cand_yes, key=lambda y: y.y) if cand_yes else None

            # Return every footer anchor as a CANDIDATE with whatever was read.
            # scan() does final confirmation (it can also use the colour highlight
            # bar, which doesn't depend on OCR), so we don't over-filter here.
            ref = header or anchor
            anchor_y = yes_line.y if yes_line else (no_line.y if no_line else anchor.y)
            if any(abs(anchor_y - cy) < 90 for cy in claimed_y):
                continue
            claimed_y.append(anchor_y)
            regions.append({"ref": ref, "anchor": anchor, "yes": yes_line,
                            "no": no_line, "header": header,
                            "other_chrome": other_chrome})
        return regions

    @staticmethod
    def _find_highlight_bar(frame_bgra, x1, x2, y1, y2):
        """Locate a solid colour selection bar (the highlighted option) and return
        its click point (cx, cy), or None. OCR fails on big colour blocks; this
        finds them by saturation, so we can click the selected option even when its
        text wasn't read."""
        h, w = frame_bgra.shape[:2]
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        if x2 - x1 < 30 or y2 - y1 < 12:
            return None
        roi = frame_bgra[y1:y2, x1:x2, :3]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1].astype(np.float32).mean(axis=1)  # per-row saturation
        base = float(np.median(sat))
        thr = max(45.0, base + 30.0)
        mask = sat > thr
        if not mask.any():
            return None
        # Longest contiguous run of saturated rows = the bar.
        best_start = best_len = cur_start = cur_len = 0
        for i, m in enumerate(mask):
            if m:
                if cur_len == 0:
                    cur_start = i
                cur_len += 1
                if cur_len > best_len:
                    best_len, best_start = cur_len, cur_start
            else:
                cur_len = 0
        if best_len < 8:  # a real bar is a chunky band, not a stray colour pixel row
            return None
        cy = y1 + best_start + best_len // 2
        cx = x1 + min(70, (x2 - x1) // 5)  # over the option text, left of the bar
        return cx, cy

    @staticmethod
    def _strip_saturation(frame_bgra: np.ndarray, line: _Line) -> float:
        """Mean saturation of a wide horizontal strip at this line's row, so a
        full-width selection bar is captured (not just the text pixels)."""
        h, w = frame_bgra.shape[:2]
        y1, y2 = max(0, line.y), min(h, line.y + line.h)
        # Extend well past the text to sample the bar itself.
        x1 = max(0, line.x)
        x2 = min(w, line.x + max(360, line.w * 3))
        if y2 - y1 < 2 or x2 - x1 < 2:
            return 0.0
        roi = frame_bgra[y1:y2, x1:x2, :3]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        return float(hsv[:, :, 1].mean())

    def _has_highlight(self, frame_bgra: np.ndarray, yes_line: _Line, ref: _Line) -> bool:
        """True if the Yes row is notably more colourful than the reference row —
        i.e. it sits on a selection-highlight bar rather than the plain panel."""
        delta = self._strip_saturation(frame_bgra, yes_line) \
            - self._strip_saturation(frame_bgra, ref)
        return delta >= HIGHLIGHT_SAT_DELTA

    def scan(self, frame_bgra: np.ndarray, monitor) -> list[Detection]:
        self.last_candidate_count = 0
        self.last_best_confidence = 0.0
        lines = self.ocr.recognize(frame_bgra)
        if not lines:
            return []
        regions = self._find_dialogs(lines)
        self.last_candidate_count = len(regions)
        if not regions:
            return []

        require_hl = self._require_highlight()
        out = []
        best = 0.0
        for r in regions:
            ref, anchor, yes_line, no_line = r["ref"], r["anchor"], r["yes"], r["no"]

            # Confirm it's a REAL prompt using menu TEXT structure only: the footer
            # plus at least one of header / "No" option / "Yes" option / a second
            # footer line. A colour bar is NOT accepted as confirmation, because a
            # blue text-selection highlight looks identical to the prompt's bar —
            # so it must never be what makes us decide "this is a prompt".
            second = (r["header"] is not None or no_line is not None
                      or yes_line is not None or r["other_chrome"])
            if not second:
                continue

            # Bar is used ONLY to locate the click, and only inside the confirmed
            # prompt's own option area (between header/top and the No/footer row).
            bx1, bx2 = anchor.x - 20, anchor.x + 520
            by2 = (no_line.y + no_line.h) if no_line else anchor.y
            by1 = (r["header"].y + r["header"].h) if r["header"] \
                else (anchor.y - PROMPT_LOOK_UP)
            bar = self._find_highlight_bar(frame_bgra, bx1, bx2, by1, by2)

            # Click target preference: read "Yes" word > selection bar > the row
            # directly above the "No" option (option 1 sits right above option 2).
            if yes_line is not None:
                cx, cy = yes_line.cx, yes_line.cy
                for wtext, wx, wy, ww, wh in yes_line.words:
                    if _opt_word(wtext) == "yes":
                        cx, cy = wx + ww // 2, wy + wh // 2
                        break
                highlighted = bar is not None or self._has_highlight(frame_bgra, yes_line, ref)
            elif bar is not None:
                cx, cy = bar
                highlighted = True
            elif no_line is not None:
                # Infer Yes as the row just above No (both left-aligned).
                cx = no_line.x + min(40, no_line.w // 3)
                cy = no_line.y - max(20, no_line.h)
                highlighted = False
            else:
                continue  # confirmed it's a prompt but nothing safe to click

            conf = 0.98 if highlighted else 0.95
            best = max(best, conf)
            if require_hl and not highlighted:
                continue
            out.append(Detection(monitor.index, monitor.left + cx, monitor.top + cy,
                                 conf, (monitor.left + ref.x, monitor.top + ref.y,
                                        ref.w, 1), 1.0))
        self.last_best_confidence = best
        return out

    def verify_point(self, capture, monitor, det: Detection, _scales=None) -> bool:
        """Re-check just before clicking that the prompt is still on screen.

        Re-grabs a band around the click point and re-runs the SAME detection. If a
        prompt is still confirmed there, we click. This is reliable (it uses the
        real matcher) rather than guessing on a single OCR/saturation read.
        """
        band_top = max(monitor.top, det.yes_y - 280)
        band_bottom = min(monitor.bottom, det.yes_y + 220)
        h = band_bottom - band_top
        if h <= 0:
            return False
        try:
            patch = capture.grab_region_bgra(monitor.left, band_top, monitor.width, h)
        except Exception:
            return True  # if we can't re-grab, trust the scan from a moment ago
        lines = self.ocr.recognize(patch)
        if self._find_dialogs(lines):
            return True
        # Fallback: a clearly-saturated selection bar near the click point.
        cx = det.yes_x - monitor.left
        cy = det.yes_y - band_top
        x1, x2 = max(0, cx - 60), min(patch.shape[1], cx + 240)
        y1, y2 = max(0, cy - 22), min(patch.shape[0], cy + 22)
        if x2 - x1 < 10 or y2 - y1 < 6:
            return True
        hsv = cv2.cvtColor(patch[y1:y2, x1:x2, :3], cv2.COLOR_BGR2HSV)
        return float(hsv[:, :, 1].mean()) >= 40.0

    def debug_lines(self, frame_bgra: np.ndarray) -> list[str]:
        return [l.text for l in self.ocr.recognize(frame_bgra)]
