"""UTC datetime utilities.

Contract: all internal timestamps are naive UTC (tzinfo=None).
- ClickHouse DateTime64(3, 'UTC') stores and returns naive UTC
- numpy datetime64 has no timezone representation
- Comparisons between timestamps must use the same convention

Functions:
    now_utc()       -> aware UTC datetime (for calculations requiring timezone)
    now_utc_naive() -> naive UTC datetime (for numpy / ClickHouse inserts)
    to_naive_utc()  -> normalize any datetime to naive UTC
    to_aware_utc()  -> normalize any datetime to aware UTC
"""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return current time as timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def now_utc_naive() -> datetime:
    """Return current time as naive UTC datetime (for numpy / ClickHouse)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """Strip tzinfo from a UTC datetime, returning naive UTC.

    Args:
        dt: datetime object (aware or naive) or None

    Returns:
        Naive UTC datetime, or None if input is None
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def to_aware_utc(dt: datetime | None) -> datetime | None:
    """Attach UTC timezone to a naive datetime.

    Args:
        dt: datetime object (aware or naive) or None

    Returns:
        Timezone-aware UTC datetime, or None if input is None
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
