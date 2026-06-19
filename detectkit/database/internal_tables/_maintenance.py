"""Maintenance mixin: cross-table cleanup helpers for ``dtk clean``.

These support pruning data left behind when an analyst edits metric configs
on production — most importantly removing all rows for a metric whose YAML no
longer exists in the project. They are used only by the ``dtk clean`` CLI
command, never by the run pipeline.
"""

from __future__ import annotations

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import (
    TABLE_ALERT_STATES,
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_METRICS,
    TABLE_TASKS,
)

# Every internal table is keyed by ``metric_name``, so a metric removed from
# the project (renamed or deleted YAML) leaves orphaned rows in all of them.
METRIC_KEYED_TABLES: tuple[str, ...] = (
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_TASKS,
    TABLE_ALERT_STATES,
    TABLE_METRICS,
)


class _MaintenanceMixin(_InternalTablesBase):
    def list_known_metric_names(self) -> set[str]:
        """Return every ``metric_name`` that has rows in any internal table.

        Unions ``SELECT DISTINCT metric_name`` across all metric-keyed tables
        so a metric is reported even if it only ever loaded datapoints (and
        thus never wrote an alert state, etc.).
        """
        names: set[str] = set()
        for table in METRIC_KEYED_TABLES:
            full_table_name = self._manager.get_full_table_name(table, use_internal=True)
            query = f"SELECT DISTINCT metric_name FROM {full_table_name}"
            result = self._manager.execute_query(query)
            names.update(row["metric_name"] for row in result if row.get("metric_name"))
        return names

    def count_metric_rows(self, metric_name: str) -> dict[str, int]:
        """Return per-table row counts for *metric_name* (for dry-run reports)."""
        counts: dict[str, int] = {}
        for table in METRIC_KEYED_TABLES:
            full_table_name = self._manager.get_full_table_name(table, use_internal=True)
            query = f"SELECT count(*) AS cnt FROM {full_table_name} WHERE metric_name = %(m)s"
            result = self._manager.execute_query(query, {"m": metric_name})
            counts[table] = int(result[0]["cnt"]) if result else 0
        return counts

    def purge_metric(self, metric_name: str) -> None:
        """Delete every row for *metric_name* across all internal tables.

        Each delete is issued synchronously (``sync=True``) so the purge is
        fully applied when this returns.
        """
        for table in METRIC_KEYED_TABLES:
            full_table_name = self._manager.get_full_table_name(table, use_internal=True)
            self._manager.delete_rows(
                full_table_name, "metric_name = %(m)s", {"m": metric_name}, sync=True
            )
