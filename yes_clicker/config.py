"""User settings — load/save to settings.json with safe defaults.

All tunables from the spec's Settings panel live here. Loading is tolerant: an
unknown or corrupt file falls back to defaults rather than crashing the app.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields

from . import paths


@dataclass
class Settings:
    # --- scanning ---
    scan_interval_ms: int = 300          # active interval, 100..2000
    idle_interval_ms: int = 1000         # slow interval after a quiet streak
    idle_after_empty_scans: int = 10     # scans with no match -> slow down
    confidence_threshold: float = 0.85   # 0.70..0.99 template-match minimum

    # --- safety ---
    max_clicks_per_minute: int = 20      # exceed -> auto-stop + alert
    cooldown_ms: int = 1500              # ignore a clicked region this long
    preclick_recheck_ms: int = 50        # re-verify button this long before click

    # --- behaviour toggles ---
    restore_mouse: bool = True           # move pointer back after clicking
    play_sound: bool = True              # soft click sound
    auto_start: bool = True              # begin scanning on launch
    confirm_enter: bool = True           # press Enter after clicking Yes
    require_highlight: bool = False      # strict: only click a visibly-highlighted option
    close_to_tray: bool = False          # X button quits by default (opt in to tray)

    # --- scoping ---
    only_when_foreground_antigravity: bool = True
    foreground_process_names: list[str] = field(
        default_factory=lambda: ["antigravity", "antigravity.exe"]
    )

    # --- alerts ---
    idle_alert_minutes: int = 30         # no prompt this long -> sanity ping
    recapture_prompt_after_low: int = 20 # low-confidence streak -> suggest recapture

    def clamp(self) -> "Settings":
        self.scan_interval_ms = int(min(2000, max(100, self.scan_interval_ms)))
        self.idle_interval_ms = int(min(5000, max(self.scan_interval_ms, self.idle_interval_ms)))
        self.confidence_threshold = float(min(0.99, max(0.70, self.confidence_threshold)))
        self.max_clicks_per_minute = int(max(1, self.max_clicks_per_minute))
        self.cooldown_ms = int(max(0, self.cooldown_ms))
        return self


_lock = threading.Lock()


def load() -> Settings:
    s = Settings()
    try:
        if paths.SETTINGS_FILE.exists():
            data = json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            for k, v in data.items():
                if k in known:
                    setattr(s, k, v)
    except (json.JSONDecodeError, OSError, TypeError):
        # Corrupt settings should never block startup.
        pass
    return s.clamp()


def save(settings: Settings) -> None:
    settings.clamp()
    with _lock:
        try:
            paths.SETTINGS_FILE.write_text(
                json.dumps(asdict(settings), indent=2), encoding="utf-8"
            )
        except OSError:
            pass
