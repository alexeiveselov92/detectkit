"""Datapoints mixin: save / load / delete operations on ``_dtk_datapoints``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_DATAPOINTS
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _DatapointsMixin(_InternalTablesBase):
    def save_datapoints(
        self,
        metric_name: str,
        data: Dict[str, np.ndarray],
        interval_seconds: int,
        seasonality_columns: List[str],
    ) -> int:
        """Insert a batch of metric datapoints. Duplicates are ignored."""
        num_rows = len(data["timestamp"])
        insert_data = {
            "metric_name": np.full(num_rows, metric_name, dtype=object),
            "timestamp": data["timestamp"],
            "value": data["value"],
            "seasonality_data": data["seasonality_data"],
            "interval_seconds": np.full(num_rows, interval_seconds, dtype=np.int32),
            "seasonality_columns": np.full(
                num_rows, ",".join(seasonality_columns), dtype=object
            ),
            "created_at": np.full(num_rows, now_utc_naive(), dtype="datetime64[ms]"),
        }
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )
        return self._manager.insert_batch(
            full_table_name, insert_data, conflict_strategy="ignore"
        )

    def get_last_datapoint_timestamp(self, metric_name: str) -> Optional[datetime]:
        """Return the most recent timestamp stored for *metric_name*, if any."""
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )
        last_ts = self._manager.get_last_timestamp(full_table_name, metric_name)
        return self._normalize_max_timestamp(last_ts)

    def load_datapoints(
        self,
        metric_name: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
    ) -> Dict[str, np.ndarray]:
        """Load datapoints for *metric_name* in the [from, to) range."""
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        where_parts = ["metric_name = %(metric_name)s"]
        params: Dict[str, Any] = {"metric_name": metric_name}
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
        seasonality_columns = [
            c.strip() for c in seasonality_columns_str.split(",") if c.strip()
        ]

        return {
            "timestamp": np.array(timestamps, dtype="datetime64[ms]"),
            "value": np.array(values, dtype=np.float64),
            "seasonality_data": np.array(seasonality, dtype=object),
            "seasonality_columns": seasonality_columns,
        }

    def delete_datapoints(
        self,
        metric_name: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
    ) -> int:
        """Issue an ``ALTER TABLE ... DELETE`` over the matching range."""
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        where_parts = ["metric_name = %(metric_name)s"]
        params: Dict[str, Any] = {"metric_name": metric_name}
        if from_timestamp:
            where_parts.append("timestamp >= %(from_timestamp)s")
            params["from_timestamp"] = from_timestamp
        if to_timestamp:
            where_parts.append("timestamp < %(to_timestamp)s")
            params["to_timestamp"] = to_timestamp

        query = (
            f"ALTER TABLE {full_table_name} DELETE WHERE {' AND '.join(where_parts)}"
        )
        self._manager.execute_query(query, params=params)
        # ClickHouse mutation is async; row count is unavailable
        return 0
