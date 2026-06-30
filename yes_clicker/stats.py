"""Click history persistence and derived statistics.

Storage: ``clicks.json`` in the app folder — a list of records, each
``{"ts": <epoch>, "monitor": <int>, "confidence": <float>}``. Survives restarts.
Entries older than 90 days are pruned on load. Stats are computed on demand so the
UI can refresh live.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from dataclasses import dataclass

from . import paths

PRUNE_DAYS = 90
SECONDS_SAVED_PER_CLICK = 3  # spec: "assumes 3 seconds per manual click"

_DAY = 86400
_WEEK = 7 * _DAY


@dataclass
class ClickRecord:
    ts: float
    monitor: int
    confidence: float

    def to_dict(self) -> dict:
        return {"ts": self.ts, "monitor": self.monitor,
                "confidence": round(self.confidence, 4)}


class Stats:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.records: list[ClickRecord] = []
        self.session_clicks = 0
        self.load()

    # --- persistence ---
    def load(self) -> None:
        recs: list[ClickRecord] = []
        try:
            if paths.CLICKS_FILE.exists():
                data = json.loads(paths.CLICKS_FILE.read_text(encoding="utf-8"))
                for d in data:
                    try:
                        recs.append(ClickRecord(float(d["ts"]), int(d.get("monitor", 0)),
                                                float(d.get("confidence", 0.0))))
                    except (KeyError, TypeError, ValueError):
                        continue
        except (json.JSONDecodeError, OSError):
            recs = []
        # Prune > 90 days on startup.
        cutoff = time.time() - PRUNE_DAYS * _DAY
        recs = [r for r in recs if r.ts >= cutoff]
        with self._lock:
            self.records = recs
        self._flush()

    def _flush(self) -> None:
        try:
            with self._lock:
                data = [r.to_dict() for r in self.records]
            paths.CLICKS_FILE.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def record_click(self, monitor: int, confidence: float, ts: float | None = None) -> None:
        rec = ClickRecord(ts if ts is not None else time.time(), monitor, confidence)
        with self._lock:
            self.records.append(rec)
            self.session_clicks += 1
        self._flush()

    # --- derived stats ---
    def _count_since(self, seconds: float) -> int:
        cutoff = time.time() - seconds
        with self._lock:
            return sum(1 for r in self.records if r.ts >= cutoff)

    def today(self) -> int:
        # Since local midnight.
        now = time.localtime()
        midnight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                                0, 0, 0, 0, 0, -1))
        with self._lock:
            return sum(1 for r in self.records if r.ts >= midnight)

    def this_week(self) -> int:
        return self._count_since(_WEEK)

    def all_time(self) -> int:
        with self._lock:
            return len(self.records)

    def busiest_hour(self) -> str | None:
        with self._lock:
            if not self.records:
                return None
            hours = Counter(time.localtime(r.ts).tm_hour for r in self.records)
        hour, _ = hours.most_common(1)[0]
        end = (hour + 1) % 24
        return f"{_fmt_hour(hour)}–{_fmt_hour(end)}"

    def avg_per_day(self) -> float:
        with self._lock:
            if not self.records:
                return 0.0
            first = min(r.ts for r in self.records)
        span_days = max(1.0, (time.time() - first) / _DAY)
        return self.all_time() / span_days

    def time_saved_week_seconds(self) -> int:
        return self.this_week() * SECONDS_SAVED_PER_CLICK

    def recent(self, n: int = 5) -> list[ClickRecord]:
        with self._lock:
            return list(self.records[-n:])[::-1]

    # --- report ---
    def report(self) -> str:
        lines = [
            "Yes Clicker — statistics",
            "=" * 32,
            f"Today:        {self.today()}",
            f"This week:    {self.this_week()}",
            f"All time:     {self.all_time()}",
            f"Avg / day:    {self.avg_per_day():.1f}",
        ]
        bh = self.busiest_hour()
        if bh:
            lines.append(f"Busiest hour: {bh}")
        lines.append(f"Time saved (week): {_fmt_duration(self.time_saved_week_seconds())}")
        recent = self.recent(5)
        if recent:
            lines.append("")
            lines.append("Recent clicks:")
            for r in recent:
                lines.append(
                    f"  [{time.strftime('%H:%M:%S', time.localtime(r.ts))}] "
                    f"monitor #{r.monitor} confidence {r.confidence:.2f}"
                )
        return "\n".join(lines)

    def is_valid_file(self) -> tuple[bool, str]:
        """Audit helper: confirm clicks.json is valid/readable."""
        try:
            if not paths.CLICKS_FILE.exists():
                return True, "no history yet (clicks.json will be created)"
            data = json.loads(paths.CLICKS_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return False, "clicks.json is not a list"
            return True, f"{len(data)} records"
        except (json.JSONDecodeError, OSError) as e:
            return False, f"unreadable: {e}"


def _fmt_hour(h: int) -> str:
    suffix = "AM" if h < 12 else "PM"
    hour12 = h % 12 or 12
    return f"{hour12}{suffix}"


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"
