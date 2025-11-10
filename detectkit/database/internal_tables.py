"""
Internal tables manager for detectk.

High-level wrapper over BaseDatabaseManager for working with internal tables
(_dtk_datapoints, _dtk_detections, _dtk_tasks, _dtk_metrics).

This class provides convenient methods that use the UNIVERSAL BaseDatabaseManager
methods underneath. It does NOT duplicate logic - just provides semantic wrappers.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from detectkit.database.manager import BaseDatabaseManager
from detectkit.database.tables import (
    INTERNAL_TABLES,
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_METRICS,
    TABLE_TASKS,
)


class InternalTablesManager:
    """
    Manager for internal detectk tables.

    Provides high-level methods for working with _dtk_* tables:
    - Ensure tables exist
    - Save datapoints and detections
    - Task locking and status management
    - Query last timestamps

    This is a WRAPPER over BaseDatabaseManager - uses its universal methods.

    Example:
        >>> manager = ClickHouseDatabaseManager(...)
        >>> internal = InternalTablesManager(manager)
        >>> internal.ensure_tables()
        >>> internal.save_datapoints("cpu_usage", data)
    """

    def __init__(self, manager: BaseDatabaseManager):
        """
        Initialize internal tables manager.

        Args:
            manager: Database manager instance (ClickHouse, PostgreSQL, etc.)
        """
        self._manager = manager

    def ensure_tables(self) -> None:
        """
        Create all internal tables if they don't exist.

        Tables created:
        - _dtk_datapoints
        - _dtk_detections
        - _dtk_tasks

        This is idempotent - safe to call multiple times.

        Example:
            >>> internal.ensure_tables()
        """
        for table_name, model_factory in INTERNAL_TABLES.items():
            # Get fully qualified table name in internal location
            full_table_name = self._manager.get_full_table_name(
                table_name, use_internal=True
            )

            # Check if table exists
            if not self._manager.table_exists(
                table_name, schema=self._manager.internal_location
            ):
                # Create table from model
                table_model = model_factory()
                self._manager.create_table(
                    full_table_name, table_model, if_not_exists=True
                )

    def save_datapoints(
        self,
        metric_name: str,
        data: Dict[str, np.ndarray],
        interval_seconds: int,
        seasonality_columns: list[str],
    ) -> int:
        """
        Save metric datapoints to _dtk_datapoints table.

        Args:
            metric_name: Metric identifier
            data: Dictionary with keys:
                - timestamp: np.array of datetime64
                - value: np.array of float64 (nullable)
                - seasonality_data: np.array of JSON strings
            interval_seconds: Interval in seconds
            seasonality_columns: List of seasonality column names

        Returns:
            Number of rows inserted

        Example:
            >>> data = {
            ...     "timestamp": np.array([dt1, dt2], dtype="datetime64[ms]"),
            ...     "value": np.array([0.5, 0.6]),
            ...     "seasonality_data": np.array(['{"hour": 10}', '{"hour": 11}']),
            ... }
            >>> rows = internal.save_datapoints(
            ...     "cpu_usage", data, 600, ["hour", "day_of_week"]
            ... )
        """
        num_rows = len(data["timestamp"])

        # Prepare data for insert_batch
        insert_data = {
            "metric_name": np.full(num_rows, metric_name, dtype=object),
            "timestamp": data["timestamp"],
            "value": data["value"],
            "seasonality_data": data["seasonality_data"],
            "interval_seconds": np.full(num_rows, interval_seconds, dtype=np.int32),
            "seasonality_columns": np.full(
                num_rows, ",".join(seasonality_columns), dtype=object
            ),
            "created_at": np.full(
                num_rows, datetime.now(timezone.utc).replace(tzinfo=None), dtype="datetime64[ms]"
            ),
        }

        # Use universal insert_batch method
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        return self._manager.insert_batch(
            full_table_name, insert_data, conflict_strategy="ignore"
        )

    def save_detections(
        self,
        metric_name: str,
        detector_id: str,
        detector_name: str,
        data: Dict[str, np.ndarray],
        detector_params: str,
    ) -> int:
        """
        Save detection results to _dtk_detections table.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier (hash)
            detector_name: Detector class name (e.g., "MADDetector")
            data: Dictionary with keys:
                - timestamp: np.array of datetime64
                - is_anomaly: np.array of bool
                - confidence_lower: np.array of float64 (nullable)
                - confidence_upper: np.array of float64 (nullable)
                - value: np.array of float64 (nullable)
                - processed_value: np.array of float64 (nullable)
                - detection_metadata: np.array of JSON strings
            detector_params: JSON string with sorted detector parameters

        Returns:
            Number of rows inserted

        Example:
            >>> data = {
            ...     "timestamp": np.array([dt1, dt2]),
            ...     "is_anomaly": np.array([False, True]),
            ...     "confidence_lower": np.array([0.4, 0.5]),
            ...     "confidence_upper": np.array([0.6, 0.7]),
            ...     "value": np.array([0.5, 0.9]),
            ...     "processed_value": np.array([0.5, 0.9]),
            ...     "detection_metadata": np.array(['{"severity": 0.0}', '{"severity": 0.8}']),
            ... }
            >>> rows = internal.save_detections(
            ...     "cpu_usage", "mad_abc123", "MADDetector", data, '{"threshold": 3.0}'
            ... )
        """
        num_rows = len(data["timestamp"])

        # Prepare data for insert_batch
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
            "created_at": np.full(
                num_rows, datetime.now(timezone.utc).replace(tzinfo=None), dtype="datetime64[ms]"
            ),
        }

        # Use universal insert_batch method
        full_table_name = self._manager.get_full_table_name(
            TABLE_DETECTIONS, use_internal=True
        )

        return self._manager.insert_batch(
            full_table_name, insert_data, conflict_strategy="ignore"
        )

    def get_last_datapoint_timestamp(self, metric_name: str) -> Optional[datetime]:
        """
        Get last saved timestamp for a metric in _dtk_datapoints.

        Args:
            metric_name: Metric identifier

        Returns:
            Last timestamp or None if no data

        Example:
            >>> last_ts = internal.get_last_datapoint_timestamp("cpu_usage")
            >>> if last_ts:
            ...     print(f"Last data at {last_ts}")
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        return self._manager.get_last_timestamp(full_table_name, metric_name)

    def get_last_detection_timestamp(
        self, metric_name: str, detector_id: str
    ) -> Optional[datetime]:
        """
        Get last saved timestamp for a detector in _dtk_detections.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier

        Returns:
            Last timestamp or None if no data

        Example:
            >>> last_ts = internal.get_last_detection_timestamp("cpu_usage", "mad_abc123")
            >>> if last_ts:
            ...     print(f"Last detection at {last_ts}")
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DETECTIONS, use_internal=True
        )

        # Need to filter by both metric_name AND detector_id
        query = f"""
        SELECT max(timestamp) as last_ts
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND detector_id = %(detector_id)s
        """

        result = self._manager.execute_query(
            query, {"metric_name": metric_name, "detector_id": detector_id}
        )

        if result and result[0]["last_ts"]:
            return result[0]["last_ts"]

        return None

    def load_datapoints(
        self,
        metric_name: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
    ) -> Dict[str, np.ndarray]:
        """
        Load datapoints from _dtk_datapoints table.

        Args:
            metric_name: Metric identifier
            from_timestamp: Start timestamp (inclusive, optional)
            to_timestamp: End timestamp (exclusive, optional)

        Returns:
            Dict with numpy arrays: timestamp, value, seasonality_data

        Example:
            >>> data = internal.load_datapoints("cpu_usage", from_timestamp=start, to_timestamp=end)
            >>> print(f"Loaded {len(data['timestamp'])} points")
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        # Build WHERE clause
        where_parts = [f"metric_name = '{metric_name}'"]
        if from_timestamp:
            where_parts.append(f"timestamp >= '{from_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")
        if to_timestamp:
            where_parts.append(f"timestamp < '{to_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")

        where_clause = " AND ".join(where_parts)

        # Query data
        query = f"""
        SELECT
            timestamp,
            value,
            seasonality_data,
            seasonality_columns
        FROM {full_table_name}
        WHERE {where_clause}
        ORDER BY timestamp
        """

        results = self._manager.execute_query(query)

        # Convert to numpy arrays
        if not results:
            return {
                "timestamp": np.array([], dtype="datetime64[ms]"),
                "value": np.array([], dtype=np.float64),
                "seasonality_data": np.array([], dtype=object),
                "seasonality_columns": [],
            }

        # Convert timezone-aware timestamps to naive to avoid numpy warning
        timestamps = [
            row["timestamp"].replace(tzinfo=None)
            if hasattr(row["timestamp"], 'tzinfo') and row["timestamp"].tzinfo
            else row["timestamp"]
            for row in results
        ]
        values = [row["value"] for row in results]
        seasonality = [row["seasonality_data"] for row in results]

        # Get seasonality_columns from first row (comma-separated string)
        seasonality_columns_str = results[0].get("seasonality_columns", "")
        seasonality_columns = [c.strip() for c in seasonality_columns_str.split(",") if c.strip()] if seasonality_columns_str else []

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
        """
        Delete datapoints for a metric.

        Args:
            metric_name: Metric name
            from_timestamp: Optional start timestamp (inclusive)
            to_timestamp: Optional end timestamp (exclusive)

        Returns:
            Number of rows deleted (if supported by database)
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DATAPOINTS, use_internal=True
        )

        # Build WHERE clause
        where_parts = [f"metric_name = '{metric_name}'"]
        if from_timestamp:
            where_parts.append(f"timestamp >= '{from_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")
        if to_timestamp:
            where_parts.append(f"timestamp < '{to_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")

        where_clause = " AND ".join(where_parts)

        # Delete data
        query = f"ALTER TABLE {full_table_name} DELETE WHERE {where_clause}"
        self._manager.execute_query(query)

        # ClickHouse ALTER TABLE DELETE is async, return 0
        # Other databases might return affected rows
        return 0

    def delete_detections(
        self,
        metric_name: str,
        detector_id: Optional[str] = None,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
    ) -> int:
        """
        Delete detections for a metric.

        Args:
            metric_name: Metric name
            detector_id: Optional detector ID filter
            from_timestamp: Optional start timestamp (inclusive)
            to_timestamp: Optional end timestamp (exclusive)

        Returns:
            Number of rows deleted (if supported by database)
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DETECTIONS, use_internal=True
        )

        # Build WHERE clause
        where_parts = [f"metric_name = '{metric_name}'"]
        if detector_id:
            where_parts.append(f"detector_id = '{detector_id}'")
        if from_timestamp:
            where_parts.append(f"timestamp >= '{from_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")
        if to_timestamp:
            where_parts.append(f"timestamp < '{to_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'")

        where_clause = " AND ".join(where_parts)

        # Delete data
        query = f"ALTER TABLE {full_table_name} DELETE WHERE {where_clause}"
        self._manager.execute_query(query)

        # ClickHouse ALTER TABLE DELETE is async, return 0
        return 0

    def get_recent_detections(
        self,
        metric_name: str,
        last_point: datetime,
        num_points: int,
        created_after: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Get recent detection results grouped by timestamp.

        This method is fully database-agnostic - uses simple SELECT
        and groups data in Python (no GROUP BY, no database-specific functions).

        Args:
            metric_name: Metric identifier
            last_point: Last complete timestamp to query up to
            num_points: Number of recent timestamps to retrieve
            created_after: Optional filter to only include detections created after this time
                          (useful to filter out old detections from previous runs)

        Returns:
            List of dicts, each containing:
                - timestamp: Detection timestamp
                - detector_ids: List of detector IDs for this timestamp
                - detector_names: List of detector names
                - detector_params_list: List of detector params (JSON strings)
                - is_anomaly_flags: List of is_anomaly bools
                - confidence_lowers: List of lower confidence bounds
                - confidence_uppers: List of upper confidence bounds
                - value: Metric value (same for all detectors at this timestamp)

        Example:
            >>> detections = internal.get_recent_detections(
            ...     "cpu_usage",
            ...     datetime(2024, 1, 1, 12, 0, 0),
            ...     5
            ... )
            >>> for det in detections:
            ...     print(f"{det['timestamp']}: {len(det['detector_ids'])} detectors")
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_DETECTIONS, use_internal=True
        )

        # Step 1: Get distinct timestamps (database-agnostic)
        # Find last N timestamps with detections
        created_filter = ""
        params = {
            "metric_name": metric_name,
            "last_point": last_point,
            "num_points": num_points,
        }

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

        timestamp_results = self._manager.execute_query(
            timestamps_query,
            params=params,
        )

        if not timestamp_results:
            return []

        # Extract timestamps
        timestamps = [row["timestamp"] for row in timestamp_results]

        # Step 2: Get all detections for these timestamps (simple SELECT)
        # Build IN clause with timestamps
        timestamps_str = ", ".join([
            f"'{ts.strftime('%Y-%m-%d %H:%M:%S')}'" for ts in timestamps
        ])

        detections_query = f"""
        SELECT
            timestamp,
            detector_id,
            detector_name,
            detector_params,
            is_anomaly,
            confidence_lower,
            confidence_upper,
            value
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND timestamp IN ({timestamps_str})
        ORDER BY timestamp DESC, detector_id
        """

        detection_results = self._manager.execute_query(
            detections_query,
            params={"metric_name": metric_name},
        )

        if not detection_results:
            return []

        # Step 3: Group by timestamp in Python (no pandas, pure Python)
        # Use timestamp string as key to avoid datetime comparison issues
        grouped = {}
        for row in detection_results:
            ts = row["timestamp"]
            # Convert timestamp to string key for grouping
            if isinstance(ts, str):
                ts_key = ts
                ts_value = ts
            else:
                # datetime object - normalize and convert to string
                if hasattr(ts, 'tzinfo') and ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                ts_key = ts.isoformat()
                ts_value = ts

            if ts_key not in grouped:
                grouped[ts_key] = {
                    "timestamp": ts_value,
                    "detector_ids": [],
                    "detector_names": [],
                    "detector_params_list": [],
                    "is_anomaly_flags": [],
                    "confidence_lowers": [],
                    "confidence_uppers": [],
                    "value": row["value"],  # Same for all detectors at this timestamp
                }

            grouped[ts_key]["detector_ids"].append(row["detector_id"])
            grouped[ts_key]["detector_names"].append(row["detector_name"])
            grouped[ts_key]["detector_params_list"].append(row["detector_params"])
            grouped[ts_key]["is_anomaly_flags"].append(row["is_anomaly"])
            grouped[ts_key]["confidence_lowers"].append(row["confidence_lower"])
            grouped[ts_key]["confidence_uppers"].append(row["confidence_upper"])

        # Step 4: Convert to list, sorted by timestamp key (desc)
        result = [grouped[ts_key] for ts_key in sorted(grouped.keys(), reverse=True)]

        return result

    def acquire_lock(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        timeout_seconds: int = 3600,
    ) -> bool:
        """
        Acquire task lock by creating task record with status='running'.

        This implements task locking to prevent concurrent execution.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier (or "load" for loading tasks)
            process_type: Process type ("load" or "detect")
            timeout_seconds: Task timeout in seconds

        Returns:
            True if lock acquired, False if already locked

        Raises:
            Exception: If lock is held by another process (check timeout)

        Example:
            >>> if internal.acquire_lock("cpu_usage", "load", "load"):
            ...     try:
            ...         # Do work
            ...         pass
            ...     finally:
            ...         internal.release_lock("cpu_usage", "load", "load", "completed")
        """
        # Check if task is already running
        existing_status = self.check_lock(metric_name, detector_id, process_type)

        if existing_status:
            # Task is locked
            # TODO: Check if lock expired based on timeout
            return False

        # Acquire lock by creating task record
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
        last_processed_timestamp: Optional[datetime] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Release task lock by updating status to 'completed' or 'failed'.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier
            process_type: Process type
            status: Final status ("completed" or "failed")
            last_processed_timestamp: Last successfully processed timestamp
            error_message: Error message if status is "failed"

        Example:
            >>> internal.release_lock(
            ...     "cpu_usage", "load", "load",
            ...     status="completed",
            ...     last_processed_timestamp=datetime(2024, 1, 1, 23, 59)
            ... )
        """
        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status=status,
            last_processed_timestamp=last_processed_timestamp,
            error_message=error_message,
        )

    def check_lock(
        self, metric_name: str, detector_id: str, process_type: str
    ) -> Optional[Dict]:
        """
        Check if task is locked (running).

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier
            process_type: Process type

        Returns:
            Task status dict if locked, None if not locked

        Example:
            >>> status = internal.check_lock("cpu_usage", "load", "load")
            >>> if status and status["status"] == "running":
            ...     print("Task is locked")
        """
        full_table_name = self._manager.get_full_table_name(
            TABLE_TASKS, use_internal=True
        )

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

        if results:
            return results[0]
        return None

    def update_task_progress(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        last_processed_timestamp: datetime,
    ) -> None:
        """
        Update task progress (last_processed_timestamp) while task is running.

        This enables idempotency - if process crashes, it can resume from
        last_processed_timestamp.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier
            process_type: Process type
            last_processed_timestamp: Last successfully processed timestamp

        Example:
            >>> # Update progress every 1000 rows
            >>> internal.update_task_progress(
            ...     "cpu_usage", "load", "load",
            ...     datetime(2024, 1, 1, 12, 0)
            ... )
        """
        self._manager.upsert_task_status(
            metric_name=metric_name,
            detector_id=detector_id,
            process_type=process_type,
            status="running",
            last_processed_timestamp=last_processed_timestamp,
        )

    def upsert_metric_config(
        self,
        metric_config,  # MetricConfig type (avoiding circular import)
        file_path: str,
        table_name_override: Optional[str] = None
    ) -> int:
        """
        Save or update metric configuration metadata to _dtk_metrics table.

        This table is INFORMATIONAL ONLY - used by analysts for dashboards.
        It does NOT affect library logic.

        Updated on every dtk run via DELETE + INSERT pattern for guaranteed uniqueness.

        Args:
            metric_config: MetricConfig instance
            file_path: Path to .yml config file
            table_name_override: Optional override for table name (from ProjectConfig)

        Returns:
            Number of rows inserted (typically 1)

        Example:
            >>> internal.upsert_metric_config(
            ...     metric_config=config,
            ...     file_path="metrics/cpu_usage.yml",
            ...     table_name_override="_dtk_metrics"
            ... )
        """
        # Get table name (use override if provided, else default)
        table_name = table_name_override or TABLE_METRICS
        full_table_name = self._manager.get_full_table_name(
            table_name, use_internal=True
        )

        # Get current UTC time (naive for numpy compatibility)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Parse loading_start_time if provided
        loading_start_time_dt = None
        if metric_config.loading_start_time:
            try:
                from datetime import datetime as dt
                loading_start_time_dt = dt.strptime(
                    metric_config.loading_start_time,
                    "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=None)
            except (ValueError, AttributeError):
                # If parsing fails, leave as None
                pass

        # Extract alert configuration
        is_alert_enabled = 0
        timezone_str = None
        direction = None
        consecutive_anomalies = 3
        no_data_alert = 0
        min_detectors = 1

        if metric_config.alerting:
            is_alert_enabled = 1 if metric_config.alerting.enabled else 0
            timezone_str = metric_config.alerting.timezone
            direction = metric_config.alerting.direction
            consecutive_anomalies = metric_config.alerting.consecutive_anomalies
            no_data_alert = 1 if metric_config.alerting.no_data_alert else 0
            min_detectors = metric_config.alerting.min_detectors

        # Prepare data for INSERT
        data = {
            "metric_name": np.array([metric_config.name]),
            "description": np.array([getattr(metric_config, 'description', None)]),
            "path": np.array([file_path]),
            "interval": np.array([str(metric_config.interval)]),
            "loading_start_time": np.array(
                [loading_start_time_dt], dtype="datetime64[ms]"
            ) if loading_start_time_dt else np.array([None]),
            "loading_batch_size": np.array(
                [metric_config.loading_batch_size], dtype=np.uint32
            ),
            "is_alert_enabled": np.array([is_alert_enabled], dtype=np.uint8),
            "timezone": np.array([timezone_str]),
            "direction": np.array([direction]),
            "consecutive_anomalies": np.array(
                [consecutive_anomalies], dtype=np.uint32
            ),
            "no_data_alert": np.array([no_data_alert], dtype=np.uint8),
            "min_detectors": np.array([min_detectors], dtype=np.uint32),
            "tags": np.array([json.dumps(metric_config.tags or [])]),
            "enabled": np.array([1 if metric_config.enabled else 0], dtype=np.uint8),
            "created_at": np.array([now], dtype="datetime64[ms]"),
            "updated_at": np.array([now], dtype="datetime64[ms]"),
        }

        # Use upsert_record for DELETE + INSERT pattern
        return self._manager.upsert_record(
            table_name=full_table_name,
            key_columns={"metric_name": metric_config.name},
            data=data
        )
