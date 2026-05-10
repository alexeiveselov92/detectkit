"""Detections mixin: save / load / delete operations on ``_dtk_detections``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_DETECTIONS
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _DetectionsMixin(_InternalTablesBase):
    def save_detections(
        self,
        metric_name: str,
        detector_id: str,
        detector_name: str,
        data: dict[str, np.ndarray],
        detector_params: str,
    ) -> int:
        """Persist a batch of detection results."""
        num_rows = len(data["timestamp"])
        insert_data = {
            "metric_name": np.full(num_rows, metric_name, dtype=object),
            "detector_id": np.full(num_rows, detector_id, dtype=object),
            "detector_name": np.full(num_rows, detector_name, dtype=object),
            "timestamp": data["timestamp"],
            "is_anomaly": data["is_anomaly"],
            "confidence_lower": data["confidence_lower"],
            "confidence_upper": data["confidence_upper"],
            "value": data["value"],
            "processed_value": data["processed_value"],
            "detector_params": np.full(num_rows, detector_params, dtype=object),
            "detection_metadata": data["detection_metadata"],
            "created_at": np.full(num_rows, now_utc_naive(), dtype="datetime64[ms]"),
        }
        full_table_name = self._manager.get_full_table_name(TABLE_DETECTIONS, use_internal=True)
        return self._manager.insert_batch(full_table_name, insert_data, conflict_strategy="ignore")

    def get_last_detection_timestamp(self, metric_name: str, detector_id: str) -> datetime | None:
        """Return the most recent detection timestamp for the given detector."""
        full_table_name = self._manager.get_full_table_name(TABLE_DETECTIONS, use_internal=True)
        query = f"""
        SELECT max(timestamp) AS last_ts
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND detector_id = %(detector_id)s
        """
        result = self._manager.execute_query(
            query, {"metric_name": metric_name, "detector_id": detector_id}
        )
        if not result:
            return None
        return self._normalize_max_timestamp(result[0].get("last_ts"))

    def delete_detections(
        self,
        metric_name: str,
        detector_id: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> int:
        """Delete detection rows for the supplied filter set."""
        full_table_name = self._manager.get_full_table_name(TABLE_DETECTIONS, use_internal=True)

        where_parts = ["metric_name = %(metric_name)s"]
        params: dict[str, Any] = {"metric_name": metric_name}
        if detector_id:
            where_parts.append("detector_id = %(detector_id)s")
            params["detector_id"] = detector_id
        if from_timestamp:
            where_parts.append("timestamp >= %(from_timestamp)s")
            params["from_timestamp"] = from_timestamp
        if to_timestamp:
            where_parts.append("timestamp < %(to_timestamp)s")
            params["to_timestamp"] = to_timestamp

        query = f"ALTER TABLE {full_table_name} DELETE WHERE {' AND '.join(where_parts)}"
        self._manager.execute_query(query, params=params)
        return 0

    def get_recent_detections(
        self,
        metric_name: str,
        last_point: datetime,
        num_points: int,
        created_after: datetime | None = None,
    ) -> list[dict]:
        """Return the latest *num_points* timestamps with all per-detector rows.

        The result groups rows per timestamp so callers can evaluate the
        consecutive-anomaly logic without re-fanning the data themselves.
        """
        full_table_name = self._manager.get_full_table_name(TABLE_DETECTIONS, use_internal=True)

        params: dict[str, Any] = {
            "metric_name": metric_name,
            "last_point": last_point,
            "num_points": num_points,
        }
        created_filter = ""
        if created_after is not None:
            created_filter = "AND created_at > %(created_after)s"
            params["created_after"] = created_after

        timestamps_query = f"""
        SELECT DISTINCT timestamp
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND timestamp <= %(last_point)s
          {created_filter}
        ORDER BY timestamp DESC
        LIMIT %(num_points)s
        """
        timestamp_results = self._manager.execute_query(timestamps_query, params=params)
        if not timestamp_results:
            return []

        timestamps = [row["timestamp"] for row in timestamp_results]

        detections_query = f"""
        SELECT
            timestamp,
            detector_id,
            detector_name,
            detector_params,
            detection_metadata,
            is_anomaly,
            confidence_lower,
            confidence_upper,
            value
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND timestamp IN %(timestamps)s
        ORDER BY timestamp DESC, detector_id
        """
        detection_results = self._manager.execute_query(
            detections_query,
            params={
                "metric_name": metric_name,
                "timestamps": tuple(timestamps),
            },
        )
        if not detection_results:
            return []

        grouped: dict[str, dict] = {}
        for row in detection_results:
            ts = row["timestamp"]
            if isinstance(ts, str):
                ts_key, ts_value = ts, ts
            else:
                ts = to_naive_utc(ts)
                ts_key, ts_value = ts.isoformat(), ts

            if ts_key not in grouped:
                grouped[ts_key] = {
                    "timestamp": ts_value,
                    "detector_ids": [],
                    "detector_names": [],
                    "detector_params_list": [],
                    "detection_metadata_list": [],
                    "is_anomaly_flags": [],
                    "confidence_lowers": [],
                    "confidence_uppers": [],
                    # value is identical for all detectors at this timestamp
                    "value": row["value"],
                }

            entry = grouped[ts_key]
            entry["detector_ids"].append(row["detector_id"])
            entry["detector_names"].append(row["detector_name"])
            entry["detector_params_list"].append(row["detector_params"])
            entry["detection_metadata_list"].append(row.get("detection_metadata"))
            entry["is_anomaly_flags"].append(row["is_anomaly"])
            entry["confidence_lowers"].append(row["confidence_lower"])
            entry["confidence_uppers"].append(row["confidence_upper"])

        return [grouped[k] for k in sorted(grouped.keys(), reverse=True)]
