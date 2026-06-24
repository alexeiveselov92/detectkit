"""Datapoints mixin: save / load / delete operations on ``_dtk_datapoints``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_DATAPOINTS
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _DatapointsMixin(_InternalTablesBase):
    def save_datapoints(
        self,
        metric_name: str,
        data: dict[str, np.ndarray],
        interval_seconds: int,
        seasonality_columns: list[str],
    ) -> int:
        """Insert a batch of metric datapoints. Duplicates are ignored."""
        num_rows = len(data["timestamp"])
        insert_data = {
            "metric_name": np.full(num_rows, metric_name, dtype=object),
            "timestamp": data["timestamp"],
            "value": data["value"],
            "seasonality_data": data["seasonality_data"],
            "interval_seconds": np.full(num_rows, interval_seconds, dtype=np.int32),
            "seasonality_columns": np.full(num_rows, ",".join(seasonality_columns), dtype=object),
            "created_at": np.full(num_rows, now_utc_naive(), dtype="datetime64[ms]"),
        }
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
        return self._manager.insert_batch(full_table_name, insert_data, conflict_strategy="ignore")

    def get_last_datapoint_timestamp(self, metric_name: str) -> datetime | None:
        """Return the most recent timestamp stored for *metric_name*, if any."""
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
        last_ts = self._manager.get_last_timestamp(full_table_name, metric_name)
        return self._normalize_max_timestamp(last_ts)

    def get_first_datapoint_timestamp(self, metric_name: str) -> datetime | None:
        """Return the earliest timestamp stored for *metric_name*, if any."""
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
        query = f"""
        SELECT min(timestamp) AS first_ts
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
        """
        result = self._manager.execute_query(query, {"metric_name": metric_name})
        if not result:
            return None
        # ClickHouse min() over an empty selection yields the epoch sentinel
        # rather than NULL; _normalize_max_timestamp maps that back to None.
        return self._normalize_max_timestamp(result[0].get("first_ts"))

    def get_value_at(self, metric_name: str, timestamp: datetime) -> float | None:
        """Return the stored ``value`` for an exact timestamp.

        Returns ``None`` if there is no row at that timestamp **or** the
        row's value is NULL/NaN — i.e. ``None`` means "no real datapoint".
        Used by the ``no_data_alert`` decision path.
        """
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
        query = f"""
        SELECT value
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s AND timestamp = %(timestamp)s
        LIMIT 1
        """
        results = self._manager.execute_query(
            query, params={"metric_name": metric_name, "timestamp": timestamp}
        )
        if not results:
            return None
        value = results[0].get("value")
        if value is None:
            return None
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            return None
        if np.isnan(value_f):
            return None
        return value_f

    def load_datapoints(
        self,
        metric_name: str,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> dict[str, np.ndarray]:
        """Load datapoints for *metric_name* in the [from, to) range."""
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)

        where_parts = ["metric_name = %(metric_name)s"]
        params: dict[str, Any] = {"metric_name": metric_name}
        if from_timestamp:
            where_parts.append("timestamp >= %(from_timestamp)s")
            params["from_timestamp"] = from_timestamp
        if to_timestamp:
            where_parts.append("timestamp < %(to_timestamp)s")
            params["to_timestamp"] = to_timestamp

        query = f"""
        SELECT timestamp, value, seasonality_data, seasonality_columns
        FROM {full_table_name}
        WHERE {" AND ".join(where_parts)}
        ORDER BY timestamp
        """
        results = self._manager.execute_query(query, params=params)

        if not results:
            return {
                "timestamp": np.array([], dtype="datetime64[ms]"),
                "value": np.array([], dtype=np.float64),
                "seasonality_data": np.array([], dtype=object),
                "seasonality_columns": [],
            }

        timestamps = [to_naive_utc(row["timestamp"]) for row in results]
        values = [row["value"] for row in results]
        seasonality = [row["seasonality_data"] for row in results]

        seasonality_columns_str = results[0].get("seasonality_columns", "") or ""
        seasonality_columns = [c.strip() for c in seasonality_columns_str.split(",") if c.strip()]

        return {
            "timestamp": np.array(timestamps, dtype="datetime64[ms]"),
            "value": np.array(values, dtype=np.float64),
            "seasonality_data": np.array(seasonality, dtype=object),
            "seasonality_columns": seasonality_columns,
        }

    def delete_datapoints(
        self,
        metric_name: str,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> int:
        """Delete datapoints for *metric_name* over the matching range.

        Returns the number of rows deleted when the backend reports it (SQL
        backends); ClickHouse mutations are asynchronous and report 0.
        """
        full_table_name = self._manager.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)

        where_parts = ["metric_name = %(metric_name)s"]
        params: dict[str, Any] = {"metric_name": metric_name}
        if from_timestamp:
            where_parts.append("timestamp >= %(from_timestamp)s")
            params["from_timestamp"] = from_timestamp
        if to_timestamp:
            where_parts.append("timestamp < %(to_timestamp)s")
            params["to_timestamp"] = to_timestamp

        return self._manager.delete_rows(full_table_name, " AND ".join(where_parts), params)
