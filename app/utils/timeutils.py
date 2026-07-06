"""
Timezone-aware datetime helpers.

The application standardizes on timezone-aware UTC datetimes everywhere.
Legacy rows and SQLite may return naive datetimes; ``as_aware`` normalizes
them so arithmetic never mixes offset-naive and offset-aware values.
"""

from datetime import datetime, timezone
from typing import Optional

UTC = timezone.utc


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Coerce a datetime to timezone-aware UTC.

    Naive datetimes (e.g. from SQLite or legacy rows) are assumed to already
    be in UTC and are tagged accordingly. ``None`` passes through unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
