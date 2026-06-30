"""OpenCV template-matching detector with the four-element safety confirmation.

Pipeline per monitor (lightweight first, precise only where needed):
  1. Downscale the monitor frame to 50% and coarsely locate the dialog *header*
     at several DPI-derived scales. This is the cheap pass that runs every cycle.
  2. For each coarse header candidate, crop a vertical band at FULL resolution and
     confirm every loaded anchor element is present:
        - "Allow this bash command?" header        (dialog_header.png)  REQUIRED
        - "1 Yes" / option-1 button                 (yes_button.png)     REQUIRED
        - "2 No" numbered row                        (no_button.png)      optional
        - "Tell Claude what to do instead" input     (input_field.png)    optional
        - "Esc to cancel" footer                     (footer.png)         optional
     If ANY *present* anchor template is missing in the band, the candidate is
     rejected — no click. The footer is the strongest discriminator (the words
     "yes"/"no" appear in chat/code, but the footer does not).
  3. The precise full-res Yes-button centre (physical pixels) is the click point.

All large mat objects are deleted at the end of each scan to prevent memory creep.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

from . import paths
from .logger import warn


# Roles and their template files. ``required`` anchors must exist on disk for the
# detector to run at all; optional anchors strengthen the four-element check when
# present.
ANCHORS = [
    ("header", paths.HEADER_TEMPLATE, True),
    ("yes", paths.YES_TEMPLATE, True),
    ("no", paths.LIST_TEMPLATE, False),
    ("input", paths.INPUT_TEMPLATE, False),
    ("footer", paths.FOOTER_TEMPLATE, False),
]

DOWNSCALE = 0.5
MAX_DIALOG_HEIGHT = 460   # logical px at scale 1.0; band height searched full-res
BAND_PAD_TOP = 40


@dataclass
class Detection:
    monitor_index: int
    yes_x: int          # physical-pixel click point (monitor-absolute)
    yes_y: int
    confidence: float
    region: tuple[int, int, int, int]  # physical bbox (left, top, w, h) of dialog
    scale: float        # matched template scale


@dataclass
class _Templ:
    role: str
    gray: np.ndarray
    required: bool


def _nms(boxes: list[tuple[int, int, int, int, float]], overlap: float = 0.4):
    """Greedy non-max suppression so one header isn't reported many times and so
    multiple *distinct* dialogs each survive."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[4], reverse=True)
    kept: list[tuple[int, int, int, int, float]] = []
    for b in boxes:
        bx, by, bw, bh, _ = b
        clash = False
        for k in kept:
            kx, ky, kw, kh, _ = k
            ix = max(bx, kx)
            iy = max(by, ky)
            ax = min(bx + bw, kx + kw)
            ay = min(by + bh, ky + kh)
            iw = max(0, ax - ix)
            ih = max(0, ay - iy)
            inter = iw * ih
            if inter and inter / float(bw * bh) > overlap:
                clash = True
                break
        if not clash:
            kept.append(b)
    return kept


class Detector:
    def __init__(self, confidence: float = 0.85):
        self.confidence = confidence
        self.templates: list[_Templ] = []
        self.missing_required: list[str] = []
        # Best header confidence seen on the last scan (incl. rejected near-misses)
        # so the engine can detect a "stale templates" streak.
        self.last_best_confidence: float = 0.0
        self.last_candidate_count: int = 0
        self.load_templates()

    # --- template loading ---
    def load_templates(self) -> bool:
        self.templates = []
        self.missing_required = []
        for role, path, required in ANCHORS:
            if not path.exists():
                if required:
                    self.missing_required.append(path.name)
                continue
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None or img.size == 0:
                if required:
                    self.missing_required.append(path.name)
                warn(f"template unreadable: {path.name}")
                continue
            self.templates.append(_Templ(role, img, required))
        return not self.missing_required

    def set_templates(self, grays: dict[str, np.ndarray]) -> None:
        """Inject in-memory templates (used by the self-test's synthetic dialog
        when real templates haven't been captured yet)."""
        required_roles = {role for role, _p, req in ANCHORS if req}
        self.templates = []
        self.missing_required = []
        for role, gray in grays.items():
            if gray is None or gray.size == 0:
                continue
            self.templates.append(_Templ(role, gray, role in required_roles))
        for role in required_roles:
            if role not in grays:
                self.missing_required.append(role)

    @property
    def ready(self) -> bool:
        return not self.missing_required and any(t.role == "yes" for t in self.templates)

    def _by_role(self, role: str) -> _Templ | None:
        for t in self.templates:
            if t.role == role:
                return t
        return None

    # --- matching primitives ---
    @staticmethod
    def _match_all(image: np.ndarray, templ: np.ndarray, scales, threshold: float):
        """Return all (x, y, w, h, conf) matches of templ in image across scales."""
        out: list[tuple[int, int, int, int, float]] = []
        ih, iw = image.shape[:2]
        for s in scales:
            if s != 1.0:
                tw = max(8, int(round(templ.shape[1] * s)))
                th = max(8, int(round(templ.shape[0] * s)))
                t = cv2.resize(templ, (tw, th), interpolation=cv2.INTER_AREA)
            else:
                t = templ
            th, tw = t.shape[:2]
            if th >= ih or tw >= iw:
                continue
            res = cv2.matchTemplate(image, t, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= threshold)
            for (y, x) in zip(ys.tolist(), xs.tolist()):
                out.append((x, y, tw, th, float(res[y, x])))
            del res
        return out

    @staticmethod
    def _best(image: np.ndarray, templ: np.ndarray, scales):
        """Best single match: (conf, x, y, w, h, scale)."""
        best = (-1.0, 0, 0, 0, 0, 1.0)
        ih, iw = image.shape[:2]
        for s in scales:
            if s != 1.0:
                tw = max(8, int(round(templ.shape[1] * s)))
                th = max(8, int(round(templ.shape[0] * s)))
                t = cv2.resize(templ, (tw, th), interpolation=cv2.INTER_AREA)
            else:
                t = templ
            th, tw = t.shape[:2]
            if th >= ih or tw >= iw:
                continue
            res = cv2.matchTemplate(image, t, cv2.TM_CCOEFF_NORMED)
            _, maxv, _, maxloc = cv2.minMaxLoc(res)
            if maxv > best[0]:
                best = (float(maxv), int(maxloc[0]), int(maxloc[1]), tw, th, s)
            del res
        return best

    # --- main scan ---
    def scan(self, frame_bgr: np.ndarray, monitor, match_scales) -> list[Detection]:
        """Find every confirmed dialog on one monitor frame (physical pixels)."""
        if not self.ready:
            return []
        header = self._by_role("header")
        yes = self._by_role("yes")
        if header is None or yes is None:
            return []

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, None, fx=DOWNSCALE, fy=DOWNSCALE,
                           interpolation=cv2.INTER_AREA)

        # Coarse pass: header at 50% * each DPI scale, with a relaxed threshold so
        # we don't drop a real dialog before the precise confirmation runs.
        coarse_scales = [round(DOWNSCALE * s, 3) for s in match_scales]
        coarse_thr = max(0.55, self.confidence - 0.15)
        cands = self._match_all(small, header.gray, coarse_scales, coarse_thr)
        # Map coarse boxes back to full-res and NMS.
        full_cands = [
            (int(x / DOWNSCALE), int(y / DOWNSCALE),
             int(w / DOWNSCALE), int(h / DOWNSCALE), c)
            for (x, y, w, h, c) in cands
        ]
        full_cands = _nms(full_cands, overlap=0.4)
        self.last_candidate_count = len(full_cands)
        self.last_best_confidence = 0.0

        detections: list[Detection] = []
        gh, gw = gray.shape[:2]
        for (hx, hy, hw, hh, _coarse) in full_cands:
            # Vertical band at full resolution covering the whole dialog.
            band_top = max(0, hy - BAND_PAD_TOP)
            # band height scales with how big the header matched.
            est_scale = hh / max(1, header.gray.shape[0])
            band_h = int(MAX_DIALOG_HEIGHT * max(est_scale, 0.6)) + hh + BAND_PAD_TOP
            band_bottom = min(gh, band_top + band_h)
            band = gray[band_top:band_bottom, 0:gw]

            det = self._confirm_band(band, band_top, monitor, match_scales)
            if det is not None:
                detections.append(det)
            del band

        del gray, small
        return detections

    def _confirm_band(self, band: np.ndarray, band_top: int, monitor, match_scales):
        """Confirm all present anchors live in the band; return a Detection or None."""
        header = self._by_role("header")
        yes = self._by_role("yes")

        h_conf, hx, hy, hw, hh, h_scale = self._best(band, header.gray, match_scales)
        self.last_best_confidence = max(self.last_best_confidence, h_conf)
        if h_conf < self.confidence:
            return None

        # Restrict the other anchors to the scale the header matched at (+/- one
        # neighbouring scale) so a confirmed dialog is internally consistent.
        local_scales = sorted({round(h_scale, 3)} |
                              {s for s in match_scales if abs(s - h_scale) < 0.3})

        y_conf, yx, yy, yw, yh, _ = self._best(band, yes.gray, local_scales)
        if y_conf < self.confidence:
            return None
        # Yes button must sit below the header.
        if yy + yh < hy:
            return None

        confs = [h_conf, y_conf]
        # Every OPTIONAL anchor that exists must also be present, or we abort.
        for role in ("no", "input", "footer"):
            t = self._by_role(role)
            if t is None:
                continue
            c, *_ = self._best(band, t.gray, local_scales)
            if c < self.confidence:
                return None
            confs.append(c)

        confidence = float(min(confs))

        # Yes-button centre -> physical monitor-absolute coordinates.
        cx = monitor.left + yx + yw // 2
        cy = monitor.top + band_top + yy + yh // 2
        region = (monitor.left + hx, monitor.top + band_top + hy, hw, hh)
        return Detection(monitor.index, cx, cy, confidence, region, h_scale)

    def verify_point(self, capture, monitor, det: Detection, match_scales=None) -> bool:
        """Pre-click re-check: confirm the Yes button is still where we think it is.

        Grabs a small region around the recorded click point and looks for the yes
        template there. Returns False if it has vanished (abort the click).
        """
        yes = self._by_role("yes")
        if yes is None:
            return False
        if match_scales is None:
            from .dpi import template_match_scales
            match_scales = template_match_scales([monitor.scale])
        pad = 90
        left = max(monitor.left, det.yes_x - pad)
        top = max(monitor.top, det.yes_y - pad)
        w = min(monitor.right - left, pad * 2)
        h = min(monitor.bottom - top, pad * 2)
        if w <= 0 or h <= 0:
            return False
        try:
            patch_bgr = capture.grab_region(left, top, w, h)
        except Exception:
            return False
        patch = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY)
        c, *_ = self._best(patch, yes.gray, match_scales)
        del patch, patch_bgr
        return c >= self.confidence
