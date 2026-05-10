"""Task locking mixin: ``_dtk_tasks`` operations."""

from __future__ import annotations

from datetime import datetime

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_TASKS


class _TasksMixin(_InternalTablesBase):
    def acquire_lock(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        timeout_seconds: int = 3600,
    ) -> bool:
        """Try to acquire the task lock; return False if it's already held."""
        # TODO: respect *timeout_seconds* by treating stale 'running' rows as released.
        if self.check_lock(metric_name, detector_id, process_type):
            return False

        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status="running",
            timeout_seconds=timeout_seconds,
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

    def check_lock(self, metric_name: str, detector_id: str, process_type: str) -> dict | None:
        """Return the running-task row, or ``None`` if no lock is active."""
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
        return results[0] if results else None

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
