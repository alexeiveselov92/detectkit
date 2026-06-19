"""Task locking mixin: ``_dtk_tasks`` operations."""

from __future__ import annotations

from datetime import datetime

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_TASKS
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _TasksMixin(_InternalTablesBase):
    def acquire_lock(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        timeout_seconds: int = 3600,
        force: bool = False,
    ) -> bool:
        """Try to acquire the task lock; return False if it's actively held.

        A ``running`` row whose age exceeds its stored ``timeout_seconds`` is
        treated as stale and overridden — the owning process likely died
        without releasing the lock (e.g. the database restarted mid-run), and
        a hung row must never block future runs.

        With ``force=True`` the running-status check is skipped entirely and
        the lock is taken unconditionally; the row is still (re)written as
        ``running`` so the forced run owns the lock and releases it on exit.
        """
        if not force and self.check_lock(metric_name, detector_id, process_type) is not None:
            return False

        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status="running",
            timeout_seconds=timeout_seconds,
        )
        return True

    def clear_lock(
        self,
        metric_name: str,
        detector_id: str = "pipeline",
        process_type: str = "pipeline",
    ) -> bool:
        """Force-release a (possibly stale) lock; return True if one was held.

        Used by ``dtk unlock`` to recover from a hung run that left a
        ``running`` row behind. The age check is ignored so even a not-yet-
        stale lock is cleared. Marks the task ``completed`` so future runs
        proceed without ``--force``.
        """
        existing = self.check_lock(metric_name, detector_id, process_type, ignore_timeout=True)
        if existing is None:
            return False

        self.release_lock(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status="completed",
        )
        return True

    def release_lock(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        status: str,
        last_processed_timestamp: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark the task as ``completed`` or ``failed``."""
        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status=status,
            last_processed_timestamp=last_processed_timestamp,
            error_message=error_message,
        )

    def check_lock(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        ignore_timeout: bool = False,
    ) -> dict | None:
        """Return the active running-task row, or ``None`` if no lock is active.

        A ``running`` row whose age (``now - started_at``) exceeds its stored
        ``timeout_seconds`` is considered stale and reported as released
        (returns ``None``), so a hung process never blocks future runs. Pass
        ``ignore_timeout=True`` to get the raw running row regardless of age
        (used by ``dtk unlock`` to detect and report even stale locks).
        """
        full_table_name = self._manager.get_full_table_name(TABLE_TASKS, use_internal=True)
        query = f"""
        SELECT *
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND detector_id = %(detector_id)s
          AND process_type = %(process_type)s
          AND status = 'running'
        """
        results = self._manager.execute_query(
            query,
            {
                "metric_name": metric_name,
                "detector_id": detector_id,
                "process_type": process_type,
            },
        )
        if not results:
            return None

        row = results[0]
        if ignore_timeout:
            return row

        started_at = to_naive_utc(row.get("started_at"))
        timeout_seconds = row.get("timeout_seconds")
        if started_at is not None and timeout_seconds is not None:
            elapsed = (now_utc_naive() - started_at).total_seconds()
            if elapsed > timeout_seconds:
                # Stale lock: the owning process never released it. Treat as
                # free so the caller can override it.
                return None
        return row

    def update_task_progress(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        last_processed_timestamp: datetime,
    ) -> None:
        """Update ``last_processed_timestamp`` for an in-flight task."""
        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status="running",
            last_processed_timestamp=last_processed_timestamp,
        )
