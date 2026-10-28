"""Hawaiʻi time for build and fetch dates (Pacific/Honolulu = UTC-10, no daylight saving)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    HST = ZoneInfo("Pacific/Honolulu")
except Exception:                       # no tz database: Hawaiʻi has a fixed offset
    HST = timezone(timedelta(hours=-10), "HST")


def now_hst() -> str:
    """Current time in Hawaiʻi, ISO 8601 with offset, e.g. 2026-10-27T21:40:00-10:00."""
    return datetime.now(HST).isoformat(timespec="seconds")


def from_timestamp_hst(ts: float) -> str:
    return datetime.fromtimestamp(ts, HST).isoformat(timespec="seconds")


def hst_date(iso: str | None) -> str:
    """Hawaiʻi calendar date (YYYY-MM-DD) of an ISO timestamp; naive values are UTC.
    Returns '' for empty input and the first 10 characters for unparseable input."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)[:10]
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(HST).date().isoformat()
