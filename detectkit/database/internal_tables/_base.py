"""Shared state for the internal-tables mixins.

The split of :class:`InternalTablesManager` into mixins relies on every
mixin reading ``self._manager`` and a couple of small helpers that handle
ClickHouse quirks (notably the "epoch-as-NULL" return for ``MAX(t)`` over
empty ranges). Putting that here gives every mixin one obvious place to
look for those helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from detectkit.database.manager import BaseDatabaseManager

_EPOCH_NAIVE = datetime(1970, 1, 1, 0, 0, 0)


class _InternalTablesBase:
    """Holds the underlying database manager and shared helpers."""

    def __init__(self, manager: BaseDatabaseManager):
        self._manager = manager

    @staticmethod
    def _normalize_max_timestamp(value: datetime | None) -> datetime | None:
        """Treat the Unix epoch sentinel as a missing value; return naive UTC.

        ClickHouse's ``max(timestamp)`` over an empty selection returns
        ``1970-01-01 00:00:00`` instead of NULL. Without normalisation,
        idempotency checks would think we already processed everything up
        to 1970 and refuse to do work.

        The driver may also hand back an *aware* datetime (clickhouse-driver
        attaches the server column's timezone), while everything in-memory in
        detectkit is naive UTC — mixing the two raises ``TypeError`` on the
        first comparison/subtraction. Cursor reads are normalized to naive
        UTC here, at the single seam every reader shares, instead of at each
        call site.
        """
        if value is None:
            return None
        epoch = _EPOCH_NAIVE
        if value.tzinfo is not None:
            epoch = epoch.replace(tzinfo=value.tzinfo)
        if value == epoch:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
