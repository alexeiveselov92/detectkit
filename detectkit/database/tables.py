"""
Internal table models for detectk.

Defines schemas for internal tables:
- _dtk_datapoints: Metric data points
- _dtk_detections: Anomaly detections
- _dtk_tasks: Task status and locking
- _dtk_metrics: Metric configuration metadata (informational)
"""

from detectkit.core.models import ColumnDefinition, TableModel


def get_datapoints_table_model() -> TableModel:
    """
    Get TableModel for _dtk_datapoints table.

    Schema:
        - metric_name: Metric identifier
        - timestamp: Data point timestamp (UTC, millisecond precision)
        - value: Metric value (nullable for missing data)
        - seasonality_data: JSON with seasonality components (hour, day_of_week, etc.)
        - interval_seconds: Interval in seconds
        - seasonality_columns: Comma-separated list of seasonality columns used
        - created_at: When record was created (UTC, millisecond precision)

    Primary Key: (metric_name, timestamp)
    """
    return TableModel(
        columns=[
            ColumnDefinition("metric_name", "String"),
            ColumnDefinition("timestamp", "DateTime64(3, 'UTC')"),
            ColumnDefinition("value", "Nullable(Float64)", nullable=True),
            ColumnDefinition("seasonality_data", "String"),
            ColumnDefinition("interval_seconds", "Int32"),
            ColumnDefinition("seasonality_columns", "String"),
            ColumnDefinition("created_at", "DateTime64(3, 'UTC')"),
        ],
        primary_key=["metric_name", "timestamp"],
        engine="ReplacingMergeTree(created_at)",
        order_by=["metric_name", "timestamp"],
    )


def get_detections_table_model() -> TableModel:
    """
    Get TableModel for _dtk_detections table.

    Schema:
        - metric_name: Metric identifier
        - detector_id: Detector identifier (hash of class + params)
        - detector_name: Detector class name (e.g., "MADDetector", "ZScoreDetector")
        - timestamp: Detection timestamp (UTC, millisecond precision)
        - is_anomaly: Whether point is anomalous
        - confidence_lower: Lower confidence bound
        - confidence_upper: Upper confidence bound
        - value: Actual metric value (ALWAYS original value)
        - processed_value: Value analyzed by detector (may be smoothed/transformed)
        - detector_params: JSON with sorted detector parameters
        - detection_metadata: JSON with missing_ratio, severity, direction, etc.
        - created_at: When detection was performed (UTC, millisecond precision)

    Primary Key: (metric_name, detector_id, timestamp)
    """
    return TableModel(
        columns=[
            ColumnDefinition("metric_name", "String"),
            ColumnDefinition("detector_id", "String"),
            ColumnDefinition("detector_name", "String"),
            ColumnDefinition("timestamp", "DateTime64(3, 'UTC')"),
            ColumnDefinition("is_anomaly", "Bool"),
            ColumnDefinition("confidence_lower", "Nullable(Float64)", nullable=True),
            ColumnDefinition("confidence_upper", "Nullable(Float64)", nullable=True),
            ColumnDefinition("value", "Nullable(Float64)", nullable=True),
            ColumnDefinition("processed_value", "Nullable(Float64)", nullable=True),
            ColumnDefinition("detector_params", "String"),
            ColumnDefinition("detection_metadata", "String"),
            ColumnDefinition("created_at", "DateTime64(3, 'UTC')"),
        ],
        primary_key=["metric_name", "detector_id", "timestamp"],
        engine="ReplacingMergeTree(created_at)",
        order_by=["metric_name", "detector_id", "timestamp"],
    )


def get_tasks_table_model() -> TableModel:
    """
    Get TableModel for _dtk_tasks table.

    Schema:
        - metric_name: Metric identifier
        - detector_id: Detector identifier (or "load" for loading tasks)
        - process_type: Type of process ("load" or "detect")
        - status: Task status ("running", "completed", "failed")
        - started_at: When task started (UTC, millisecond precision)
        - updated_at: Last update timestamp (UTC, millisecond precision)
        - last_processed_timestamp: Last successfully processed timestamp
        - error_message: Error message if failed (nullable)
        - timeout_seconds: Task timeout in seconds

    Primary Key: (metric_name, detector_id, process_type)

    This table serves dual purpose:
    1. Locking: Only one process can run for a given (metric, detector, type)
    2. Resume: Stores last_processed_timestamp to resume from interruptions
    """
    return TableModel(
        columns=[
            ColumnDefinition("metric_name", "String"),
            ColumnDefinition("detector_id", "String"),
            ColumnDefinition("process_type", "String"),
            ColumnDefinition("status", "String"),
            ColumnDefinition("started_at", "DateTime64(3, 'UTC')"),
            ColumnDefinition("updated_at", "DateTime64(3, 'UTC')"),
            ColumnDefinition(
                "last_processed_timestamp",
                "Nullable(DateTime64(3, 'UTC'))",
                nullable=True
            ),
            ColumnDefinition("error_message", "Nullable(String)", nullable=True),
            ColumnDefinition("timeout_seconds", "Int32"),
        ],
        primary_key=["metric_name", "detector_id", "process_type"],
        engine="MergeTree",
        order_by=["metric_name", "detector_id", "process_type"],
    )


def get_metrics_table_model() -> TableModel:
    """
    Get TableModel for _dtk_metrics table.

    This table stores metric configuration metadata for analytics dashboards.
    It is INFORMATIONAL ONLY - does not affect library logic.
    Updated on every dtk run via DELETE + INSERT pattern.

    Schema:
        - metric_name: Metric identifier (PRIMARY KEY)
        - description: Optional metric description
        - path: Path to .yml config file
        - interval: Interval as string ("10min", "1h", etc.)
        - loading_start_time: Start time for initial data loading
        - loading_batch_size: Batch size for loading operations
        - is_alert_enabled: Whether alerting is enabled (0/1)
        - timezone: Timezone for alerts (e.g., "Europe/Moscow")
        - direction: Required anomaly direction ("same", "any", "up", "down")
        - consecutive_anomalies: Consecutive anomalies to trigger alert
        - no_data_alert: Whether to alert on missing data (0/1)
        - min_detectors: Minimum detectors that must agree
        - tags: JSON array of tags
        - enabled: Whether metric is enabled for processing (0/1)
        - created_at: First time config was saved (UTC, millisecond precision)
        - updated_at: Last config update (UTC, millisecond precision)

    Primary Key: (metric_name)
    Engine: MergeTree (uses DELETE + INSERT for guaranteed uniqueness)
    """
    return TableModel(
        columns=[
            ColumnDefinition("metric_name", "String"),
            ColumnDefinition("description", "Nullable(String)", nullable=True),
            ColumnDefinition("path", "String"),
            ColumnDefinition("interval", "String"),
            ColumnDefinition(
                "loading_start_time",
                "Nullable(DateTime64(3, 'UTC'))",
                nullable=True
            ),
            ColumnDefinition("loading_batch_size", "UInt32"),
            ColumnDefinition("is_alert_enabled", "UInt8"),
            ColumnDefinition("timezone", "Nullable(String)", nullable=True),
            ColumnDefinition("direction", "Nullable(String)", nullable=True),
            ColumnDefinition("consecutive_anomalies", "UInt32"),
            ColumnDefinition("no_data_alert", "UInt8"),
            ColumnDefinition("min_detectors", "UInt32"),
            ColumnDefinition("tags", "String"),
            ColumnDefinition("enabled", "UInt8"),
            ColumnDefinition("created_at", "DateTime64(3, 'UTC')"),
            ColumnDefinition("updated_at", "DateTime64(3, 'UTC')"),
        ],
        primary_key=["metric_name"],
        engine="MergeTree",
        order_by=["metric_name"],
    )


# Table names as constants
TABLE_DATAPOINTS = "_dtk_datapoints"
TABLE_DETECTIONS = "_dtk_detections"
TABLE_TASKS = "_dtk_tasks"
TABLE_METRICS = "_dtk_metrics"

# Map of table names to model factories
INTERNAL_TABLES = {
    TABLE_DATAPOINTS: get_datapoints_table_model,
    TABLE_DETECTIONS: get_detections_table_model,
    TABLE_TASKS: get_tasks_table_model,
    TABLE_METRICS: get_metrics_table_model,
}
