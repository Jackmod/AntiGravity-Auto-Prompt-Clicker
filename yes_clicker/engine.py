"""Background detection/click engine — a single worker thread that never blocks
the UI.

Responsibilities:
  * adaptive polling (slow down after a quiet streak, snap back on a match)
  * foreground-process gating (skip work unless Antigravity is frontmost)
  * runtime DPI re-detection (monitor plugged in / scaling changed)
  * per-region click cooldown (no double-clicking the same dialog)
  * pre-click re-check (abort if the button vanished in the last 50ms)
  * failsafes: rate cap, idle alert, low-confidence streak, panic stop
State-change callbacks let the UI/tray redraw only when something actually
changed (no timer-driven repaints).
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

from . import config
from .capture import ScreenCapture, foreground_is_target
from .clicker import Clicker
from .detector import Detector
from .dpi import Monitors
from .logger import log, warn
from .ocr_detector import TextPromptDetector
from .stats import Stats

# Re-run OCR at least once every this many cycles even if the frame looks
# unchanged, so OCR noise can't make a static prompt be skipped indefinitely.
RECHECK_EVERY = 3


class EngineEvent:
    CLICK = "click"
    STATE = "state"            # running/stopped changed
    RATE_TRIPPED = "rate"      # max clicks/min exceeded -> auto-stopped
    IDLE_ALERT = "idle"        # no prompt for N minutes
    RECAPTURE = "recapture"    # low-confidence streak
    PANIC = "panic"            # F9 pressed
    DPI_CHANGED = "dpi"


class Engine:
    def __init__(self, settings: config.Settings, stats: Stats,
                 on_event=None):
        self.settings = settings
        self.stats = stats
        self.on_event = on_event or (lambda kind, payload=None: None)

        # OCR text detection is the primary, zero-config path. If the OS OCR engine
        # isn't available (non-Windows), fall back to template matching.
        ocr = TextPromptDetector(settings)
        if ocr.available:
            self.detector = ocr
            self.mode = "ocr"
        else:
            self.detector = Detector(confidence=settings.confidence_threshold)
            self.mode = "template"
        self.monitors = Monitors()
        # Cheap per-monitor frame signatures so a static screen does no OCR.
        self._frame_sig: dict[int, tuple[int, int]] = {}
        # The app's own window rect (logical px), set by the UI, so we never detect
        # or click our own "Yes" text. None when the window is hidden/minimised.
        self.exclude_logical_rect: tuple[int, int, int, int] | None = None

        self._running = threading.Event()
        self._stop_flag = threading.Event()
        self._thread: threading.Thread | None = None
        self._panicked = False

        # cooldown: region-key -> expiry timestamp
        self._cooldowns: dict[tuple[int, int, int], float] = {}
        self._click_times: deque[float] = deque(maxlen=240)
        self._empty_streak = 0
        self._low_conf_streak = 0
        self._last_prompt_ts = time.time()
        self._idle_alerted = False
        self._recapture_alerted = False

    # --- lifecycle ---
    def start_thread(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._loop, name="yc-engine", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop_flag.set()
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self._panicked:
            self._panicked = False
        if not self._running.is_set():
            self._running.set()
            self._idle_alerted = False
            self._last_prompt_ts = time.time()
            # Force the next scan to be a full one so a prompt that is ALREADY on
            # screen is caught immediately (don't let a stale frame signature from
            # a previous run cause it to be skipped).
            self._frame_sig.clear()
            log("scanning started")
            self.on_event(EngineEvent.STATE, True)

    def stop(self) -> None:
        if self._running.is_set():
            self._running.clear()
            log("scanning stopped")
            self.on_event(EngineEvent.STATE, False)

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def panic(self) -> None:
        """Instant stop from anywhere (F9). Cannot be auto-restarted silently."""
        self._panicked = True
        was = self._running.is_set()
        self._running.clear()
        warn("PANIC — F9 pressed, clicker stopped")
        if was:
            self.on_event(EngineEvent.STATE, False)
        self.on_event(EngineEvent.PANIC)

    def reload_settings(self) -> None:
        if hasattr(self.detector, "confidence"):
            self.detector.confidence = self.settings.confidence_threshold
        self.clicker_restore = self.settings.restore_mouse

    def reload_templates(self) -> bool:
        ok = self.detector.load_templates()
        self._recapture_alerted = False
        self._low_conf_streak = 0
        return ok

    # --- main loop ---
    def _loop(self) -> None:
        capture = ScreenCapture()
        clicker = Clicker(self.settings.restore_mouse, self.settings.play_sound,
                          self.settings.confirm_enter)
        refresh_counter = 0
        try:
            while not self._stop_flag.is_set():
                if not self._running.is_set():
                    time.sleep(0.1)
                    continue

                clicker.restore_mouse = self.settings.restore_mouse
                clicker.play_sound = self.settings.play_sound
                clicker.confirm_enter = self.settings.confirm_enter

                interval = self._current_interval()

                # Foreground gate — skip scanning entirely when Antigravity isn't
                # frontmost (cheap, keeps idle CPU near zero).
                if self.settings.only_when_foreground_antigravity and \
                        not foreground_is_target(self.settings.foreground_process_names):
                    self._check_idle_alert()
                    time.sleep(interval)
                    continue

                # Re-detect DPI/monitors every ~2s of active scanning.
                refresh_counter += 1
                if refresh_counter >= 7:
                    refresh_counter = 0
                    if self.monitors.refresh():
                        log("display layout / DPI change detected — re-detected monitors")
                        self.on_event(EngineEvent.DPI_CHANGED)

                self._purge_cooldowns()
                clicked_any = self._scan_once(capture, clicker)

                self._update_streaks(clicked_any)
                self._check_idle_alert()
                self._check_recapture()

                time.sleep(self._current_interval())
        except Exception as e:  # pragma: no cover - keep thread alive on surprises
            warn(f"engine loop error: {e}")
        finally:
            capture.close()

    @staticmethod
    def _frame_signature(frame_bgra: np.ndarray) -> int:
        """Cheap hash of a heavily-downsampled frame for change detection."""
        small = frame_bgra[::29, ::29, 0]  # sparse luminance-ish sample
        return hash(small.tobytes())

    def _scan_once(self, capture, clicker) -> bool:
        clicked_any = False
        for monitor in self.monitors.monitors:
            try:
                if self.mode == "ocr":
                    frame = capture.grab_bgra(monitor)
                else:
                    frame = capture.grab_monitor(monitor)
            except Exception as e:
                warn(f"capture failed on monitor #{monitor.index}: {e}")
                continue

            # Frame-change gate: skip OCR entirely if this monitor is unchanged and
            # nothing is currently on cooldown there (keeps idle CPU near zero).
            try:
                if self.mode == "ocr":
                    sig = self._frame_signature(frame)
                    prev = self._frame_sig.get(monitor.index)
                    # Skip OCR on an unchanged frame to save CPU — but only for a few
                    # cycles, then force a re-OCR. OCR is noisy: a prompt can be
                    # missed on one frame and read fine on the next, so we must keep
                    # re-checking even when the picture hasn't changed.
                    if (prev and prev[0] == sig and prev[1] + 1 < RECHECK_EVERY
                            and not self._cooldowns):
                        self._frame_sig[monitor.index] = (sig, prev[1] + 1)
                        continue
                    dets = self.detector.scan(frame, monitor)
                    if dets:
                        self._frame_sig.pop(monitor.index, None)
                    else:
                        self._frame_sig[monitor.index] = (sig, 0)
                else:
                    from .dpi import template_match_scales
                    dets = self.detector.scan(frame, monitor,
                                              template_match_scales(self.monitors.scales()))
            finally:
                del frame

            for det in dets:
                if self._is_self_window(monitor, det):
                    continue
                if self._in_cooldown(det):
                    continue
                if not self._rate_ok():
                    self._trip_rate_cap()
                    return clicked_any
                # Pre-click re-check just before clicking.
                time.sleep(self.settings.preclick_recheck_ms / 1000.0)
                if not self.detector.verify_point(capture, monitor, det):
                    warn("prompt vanished before click — aborted")
                    continue
                try:
                    lx, ly = clicker.click_yes(monitor, det.yes_x, det.yes_y)
                except Exception as e:
                    warn(f"click failed: {e}")
                    continue
                self._register_click(det, lx, ly)
                clicked_any = True
                # Invalidate the cached signature so the next loop re-scans (the
                # prompt is gone now and a new one may appear).
                self._frame_sig.pop(monitor.index, None)
        return clicked_any

    # --- click bookkeeping ---
    def _register_click(self, det, lx, ly) -> None:
        now = time.time()
        self._click_times.append(now)
        self._cooldowns[self._region_key(det)] = now + self.settings.cooldown_ms / 1000.0
        self._last_prompt_ts = now
        self._idle_alerted = False
        self.stats.record_click(det.monitor_index, det.confidence, ts=now)
        log(f"Clicked Yes at ({lx}, {ly}) monitor #{det.monitor_index} "
            f"confidence {det.confidence:.2f}")
        self.on_event(EngineEvent.CLICK, det)

    # --- cooldown ---
    @staticmethod
    def _region_key(det) -> tuple[int, int, int]:
        # Quantise so tiny pixel jitter maps to the same region.
        return (det.monitor_index, det.yes_x // 40, det.yes_y // 40)

    def _in_cooldown(self, det) -> bool:
        return self._cooldowns.get(self._region_key(det), 0.0) > time.time()

    def _is_self_window(self, monitor, det) -> bool:
        """True if the click point lands inside the app's own window."""
        rect = self.exclude_logical_rect
        if not rect:
            return False
        lx, ly = monitor.physical_to_logical(det.yes_x, det.yes_y)
        x, y, w, h = rect
        m = 8  # small margin
        return (x - m) <= lx <= (x + w + m) and (y - m) <= ly <= (y + h + m)

    def _purge_cooldowns(self) -> None:
        now = time.time()
        for k in [k for k, exp in self._cooldowns.items() if exp <= now]:
            del self._cooldowns[k]

    # --- rate cap ---
    def _rate_ok(self) -> bool:
        cutoff = time.time() - 60
        recent = sum(1 for t in self._click_times if t >= cutoff)
        return recent < self.settings.max_clicks_per_minute

    def _trip_rate_cap(self) -> None:
        warn(f"rate cap hit (> {self.settings.max_clicks_per_minute}/min) — auto-stopping")
        self._running.clear()
        self.on_event(EngineEvent.STATE, False)
        self.on_event(EngineEvent.RATE_TRIPPED, self.settings.max_clicks_per_minute)

    # --- adaptive polling ---
    def _current_interval(self) -> float:
        if self._empty_streak >= self.settings.idle_after_empty_scans:
            return self.settings.idle_interval_ms / 1000.0
        return self.settings.scan_interval_ms / 1000.0

    def _update_streaks(self, clicked_any: bool) -> None:
        found_candidate = self.detector.last_candidate_count > 0
        if clicked_any or found_candidate:
            self._empty_streak = 0
        else:
            self._empty_streak += 1

        # Low-confidence streak: coarse candidates kept appearing but never cleared
        # the confidence bar -> templates may be stale.
        best = self.detector.last_best_confidence
        if found_candidate and 0 < best < self.settings.confidence_threshold:
            self._low_conf_streak += 1
        elif clicked_any:
            self._low_conf_streak = 0

    # --- alerts ---
    def _check_idle_alert(self) -> None:
        if not self.running or self._idle_alerted:
            return
        mins = (time.time() - self._last_prompt_ts) / 60.0
        if mins >= self.settings.idle_alert_minutes:
            self._idle_alerted = True
            log(f"idle {int(mins)}m with no prompt — sanity alert")
            self.on_event(EngineEvent.IDLE_ALERT, int(mins))

    def _check_recapture(self) -> None:
        if self._recapture_alerted:
            return
        if self._low_conf_streak >= self.settings.recapture_prompt_after_low:
            self._recapture_alerted = True
            warn("confidence below threshold many scans in a row — recapture templates?")
            self.on_event(EngineEvent.RECAPTURE, self._low_conf_streak)
