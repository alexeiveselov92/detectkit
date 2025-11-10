"""Tests for InternalTablesManager."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import numpy as np
import pytest

from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.tables import (
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_METRICS,
    TABLE_TASKS,
    get_datapoints_table_model,
    get_detections_table_model,
    get_metrics_table_model,
    get_tasks_table_model,
)


@pytest.fixture
def mock_manager():
    """Create mock BaseDatabaseManager."""
    manager = MagicMock()
    manager.internal_location = "detectk_internal"
    manager.get_full_table_name = lambda name, use_internal: f"detectk_internal.{name}"
    return manager


@pytest.fixture
def internal_manager(mock_manager):
    """Create InternalTablesManager with mock."""
    return InternalTablesManager(mock_manager)


class TestEnsureTables:
    """Test ensure_tables() method."""

    def test_creates_missing_tables(self, internal_manager, mock_manager):
        """Test that missing tables are created."""
        # Mock table_exists to return False (tables don't exist)
        mock_manager.table_exists.return_value = False

        # Call ensure_tables
        internal_manager.ensure_tables()

        # Verify create_table was called for each internal table
        assert mock_manager.create_table.call_count == 4

        # Verify correct table names
        created_tables = [
            call[0][0] for call in mock_manager.create_table.call_args_list
        ]
        assert f"detectk_internal.{TABLE_DATAPOINTS}" in created_tables
        assert f"detectk_internal.{TABLE_DETECTIONS}" in created_tables
        assert f"detectk_internal.{TABLE_TASKS}" in created_tables
        assert f"detectk_internal.{TABLE_METRICS}" in created_tables

    def test_skips_existing_tables(self, internal_manager, mock_manager):
        """Test that existing tables are not recreated."""
        # Mock table_exists to return True (tables exist)
        mock_manager.table_exists.return_value = True

        # Call ensure_tables
        internal_manager.ensure_tables()

        # Verify create_table was NOT called
        mock_manager.create_table.assert_not_called()

    def test_partial_existing_tables(self, internal_manager, mock_manager):
        """Test when some tables exist and some don't."""
        # Mock: only datapoints exists
        def table_exists_side_effect(name, schema=None):
            return name == TABLE_DATAPOINTS

        mock_manager.table_exists.side_effect = table_exists_side_effect

        # Call ensure_tables
        internal_manager.ensure_tables()

        # Verify create_table called only for missing tables (detections, tasks, metrics)
        assert mock_manager.create_table.call_count == 3

        created_tables = [
            call[0][0] for call in mock_manager.create_table.call_args_list
        ]
        assert f"detectk_internal.{TABLE_DATAPOINTS}" not in created_tables
        assert f"detectk_internal.{TABLE_DETECTIONS}" in created_tables
        assert f"detectk_internal.{TABLE_TASKS}" in created_tables
        assert f"detectk_internal.{TABLE_METRICS}" in created_tables


class TestSaveDatapoints:
    """Test save_datapoints() method."""

    def test_saves_datapoints_correctly(self, internal_manager, mock_manager):
        """Test saving datapoints with correct data structure."""
        # Prepare test data
        data = {
            "timestamp": np.array(
                ["2024-01-01T00:00:00", "2024-01-01T00:10:00"],
                dtype="datetime64[ms]"
            ),
            "value": np.array([0.5, 0.6], dtype=np.float64),
            "seasonality_data": np.array(
                ['{"hour": 0}', '{"hour": 0}'], dtype=object
            ),
        }

        mock_manager.insert_batch.return_value = 2

        # Save datapoints
        rows = internal_manager.save_datapoints(
            metric_name="cpu_usage",
            data=data,
            interval_seconds=600,
            seasonality_columns=["hour", "day_of_week"],
        )

        # Verify insert_batch was called
        assert rows == 2
        mock_manager.insert_batch.assert_called_once()

        # Verify call arguments
        call_args = mock_manager.insert_batch.call_args
        table_name = call_args[0][0]
        insert_data = call_args[0][1]
        conflict_strategy = call_args[1]["conflict_strategy"]

        assert table_name == f"detectk_internal.{TABLE_DATAPOINTS}"
        assert conflict_strategy == "ignore"

        # Verify data structure
        assert "metric_name" in insert_data
        assert "timestamp" in insert_data
        assert "value" in insert_data
        assert "seasonality_data" in insert_data
        assert "interval_seconds" in insert_data
        assert "seasonality_columns" in insert_data
        assert "created_at" in insert_data

        # Verify metric_name is filled
        assert np.all(insert_data["metric_name"] == "cpu_usage")

        # Verify interval_seconds is filled
        assert np.all(insert_data["interval_seconds"] == 600)

        # Verify seasonality_columns is comma-separated
        assert np.all(insert_data["seasonality_columns"] == "hour,day_of_week")

    def test_saves_nullable_values(self, internal_manager, mock_manager):
        """Test saving datapoints with NULL values."""
        data = {
            "timestamp": np.array(["2024-01-01T00:00:00"], dtype="datetime64[ms]"),
            "value": np.array([np.nan], dtype=np.float64),  # NULL value
            "seasonality_data": np.array(['{"hour": 0}'], dtype=object),
        }

        mock_manager.insert_batch.return_value = 1

        rows = internal_manager.save_datapoints(
            "cpu_usage", data, 600, ["hour"]
        )

        assert rows == 1
        call_args = mock_manager.insert_batch.call_args[0][1]
        assert np.isnan(call_args["value"][0])


class TestSaveDetections:
    """Test save_detections() method."""

    def test_saves_detections_correctly(self, internal_manager, mock_manager):
        """Test saving detection results."""
        data = {
            "timestamp": np.array(["2024-01-01T00:00:00"], dtype="datetime64[ms]"),
            "is_anomaly": np.array([True], dtype=bool),
            "confidence_lower": np.array([0.4], dtype=np.float64),
            "confidence_upper": np.array([0.6], dtype=np.float64),
            "value": np.array([0.9], dtype=np.float64),
            "detection_metadata": np.array(
                ['{"severity": 0.8, "direction": "above"}'], dtype=object
            ),
        }

        mock_manager.insert_batch.return_value = 1

        rows = internal_manager.save_detections(
            metric_name="cpu_usage",
            detector_id="mad_abc123",
            data=data,
            detector_params='{"threshold": 3.0}',
        )

        assert rows == 1
        mock_manager.insert_batch.assert_called_once()

        # Verify call arguments
        call_args = mock_manager.insert_batch.call_args
        table_name = call_args[0][0]
        insert_data = call_args[0][1]

        assert table_name == f"detectk_internal.{TABLE_DETECTIONS}"

        # Verify data structure
        assert np.all(insert_data["metric_name"] == "cpu_usage")
        assert np.all(insert_data["detector_id"] == "mad_abc123")
        assert np.all(insert_data["detector_params"] == '{"threshold": 3.0}')
        assert insert_data["is_anomaly"][0] == True  # numpy bool == Python bool


class TestGetLastDatapointTimestamp:
    """Test get_last_datapoint_timestamp() method."""

    def test_returns_last_timestamp(self, internal_manager, mock_manager):
        """Test getting last timestamp."""
        expected_ts = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)
        mock_manager.get_last_timestamp.return_value = expected_ts

        ts = internal_manager.get_last_datapoint_timestamp("cpu_usage")

        assert ts == expected_ts
        mock_manager.get_last_timestamp.assert_called_once_with(
            f"detectk_internal.{TABLE_DATAPOINTS}", "cpu_usage"
        )

    def test_returns_none_when_no_data(self, internal_manager, mock_manager):
        """Test returns None when no data exists."""
        mock_manager.get_last_timestamp.return_value = None

        ts = internal_manager.get_last_datapoint_timestamp("cpu_usage")

        assert ts is None


class TestTaskLocking:
    """Test task locking methods."""

    def test_acquire_lock_success(self, internal_manager, mock_manager):
        """Test acquiring lock when not locked."""
        # Mock: no existing lock
        mock_manager.execute_query.return_value = []

        success = internal_manager.acquire_lock(
            "cpu_usage", "load", "load", timeout_seconds=3600
        )

        assert success is True

        # Verify upsert_task_status was called
        mock_manager.upsert_task_status.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="load",
            process_type="load",
            status="running",
            timeout_seconds=3600,
        )

    def test_acquire_lock_fails_when_locked(self, internal_manager, mock_manager):
        """Test acquiring lock when already locked."""
        # Mock: existing lock
        mock_manager.execute_query.return_value = [
            {"status": "running", "started_at": datetime.now(timezone.utc)}
        ]

        success = internal_manager.acquire_lock("cpu_usage", "load", "load")

        assert success is False

        # Verify upsert_task_status was NOT called
        mock_manager.upsert_task_status.assert_not_called()

    def test_release_lock_completed(self, internal_manager, mock_manager):
        """Test releasing lock with completed status."""
        last_ts = datetime(2024, 1, 1, 23, 59, tzinfo=timezone.utc)

        internal_manager.release_lock(
            "cpu_usage",
            "load",
            "load",
            status="completed",
            last_processed_timestamp=last_ts,
        )

        mock_manager.upsert_task_status.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="load",
            process_type="load",
            status="completed",
            last_processed_timestamp=last_ts,
            error_message=None,
        )

    def test_release_lock_failed(self, internal_manager, mock_manager):
        """Test releasing lock with failed status."""
        internal_manager.release_lock(
            "cpu_usage",
            "load",
            "load",
            status="failed",
            error_message="Connection timeout",
        )

        mock_manager.upsert_task_status.assert_called_once()
        call_kwargs = mock_manager.upsert_task_status.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["error_message"] == "Connection timeout"

    def test_check_lock_returns_status(self, internal_manager, mock_manager):
        """Test checking lock status."""
        expected_status = {
            "status": "running",
            "started_at": datetime.now(timezone.utc),
        }
        mock_manager.execute_query.return_value = [expected_status]

        status = internal_manager.check_lock("cpu_usage", "load", "load")

        assert status == expected_status

    def test_check_lock_returns_none_when_not_locked(
        self, internal_manager, mock_manager
    ):
        """Test checking lock when not locked."""
        mock_manager.execute_query.return_value = []

        status = internal_manager.check_lock("cpu_usage", "load", "load")

        assert status is None

    def test_update_task_progress(self, internal_manager, mock_manager):
        """Test updating task progress."""
        last_ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        internal_manager.update_task_progress(
            "cpu_usage", "load", "load", last_ts
        )

        mock_manager.upsert_task_status.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="load",
            process_type="load",
            status="running",
            last_processed_timestamp=last_ts,
        )


class TestUpsertMetricConfig:
    """Test upsert_metric_config() method."""

    def test_upserts_metric_config_with_all_fields(self, internal_manager, mock_manager):
        """Test upserting metric config with all fields populated."""
        # Create mock MetricConfig
        mock_config = MagicMock()
        mock_config.name = "cpu_usage"
        mock_config.interval = "10min"
        mock_config.loading_batch_size = 10000
        mock_config.loading_start_time = "2024-01-01 00:00:00"
        mock_config.tags = ["critical", "infrastructure"]
        mock_config.enabled = True

        # Mock alerting config
        mock_alert = MagicMock()
        mock_alert.enabled = True
        mock_alert.timezone = "Europe/Moscow"
        mock_alert.direction = "both"
        mock_alert.consecutive_anomalies = 3
        mock_alert.no_data_alert = True
        mock_alert.min_detectors = 2
        mock_config.alerting = mock_alert

        # Mock upsert_record to return 1 (success)
        mock_manager.upsert_record.return_value = 1

        # Call upsert_metric_config
        result = internal_manager.upsert_metric_config(
            metric_config=mock_config,
            file_path="metrics/cpu_usage.yml",
            table_name_override="_dtk_metrics"
        )

        # Verify upsert_record was called
        assert mock_manager.upsert_record.called
        assert result == 1

        # Verify table name
        call_args = mock_manager.upsert_record.call_args
        assert call_args[1]["table_name"] == "detectk_internal._dtk_metrics"

        # Verify key_columns
        assert call_args[1]["key_columns"] == {"metric_name": "cpu_usage"}

        # Verify data dict structure
        data = call_args[1]["data"]
        assert data["metric_name"][0] == "cpu_usage"
        assert data["path"][0] == "metrics/cpu_usage.yml"
        assert data["interval"][0] == "10min"
        assert data["loading_batch_size"][0] == 10000
        assert data["is_alert_enabled"][0] == 1
        assert data["timezone"][0] == "Europe/Moscow"
        assert data["direction"][0] == "both"
        assert data["consecutive_anomalies"][0] == 3
        assert data["no_data_alert"][0] == 1
        assert data["min_detectors"][0] == 2
        assert data["enabled"][0] == 1

    def test_upserts_metric_config_without_alerting(self, internal_manager, mock_manager):
        """Test upserting metric config without alerting configuration."""
        # Create mock MetricConfig without alerting
        mock_config = MagicMock()
        mock_config.name = "api_requests"
        mock_config.interval = "1h"
        mock_config.loading_batch_size = 5000
        mock_config.loading_start_time = None
        mock_config.tags = None
        mock_config.enabled = True
        mock_config.alerting = None  # No alerting

        mock_manager.upsert_record.return_value = 1

        # Call upsert_metric_config
        result = internal_manager.upsert_metric_config(
            metric_config=mock_config,
            file_path="metrics/api_requests.yml"
        )

        # Verify upsert_record was called
        assert mock_manager.upsert_record.called
        assert result == 1

        # Verify data has default alert values
        data = mock_manager.upsert_record.call_args[1]["data"]
        assert data["is_alert_enabled"][0] == 0
        assert data["timezone"][0] is None
        assert data["direction"][0] is None
        assert data["consecutive_anomalies"][0] == 3
        assert data["no_data_alert"][0] == 0
        assert data["min_detectors"][0] == 1

    def test_uses_default_table_name_when_no_override(self, internal_manager, mock_manager):
        """Test that default table name is used when no override provided."""
        mock_config = MagicMock()
        mock_config.name = "test_metric"
        mock_config.interval = "5min"
        mock_config.loading_batch_size = 1000
        mock_config.loading_start_time = None
        mock_config.tags = []
        mock_config.enabled = True
        mock_config.alerting = None

        mock_manager.upsert_record.return_value = 1

        # Call without table_name_override
        internal_manager.upsert_metric_config(
            metric_config=mock_config,
            file_path="metrics/test.yml"
        )

        # Verify default table name was used
        call_args = mock_manager.upsert_record.call_args
        assert call_args[1]["table_name"] == f"detectk_internal.{TABLE_METRICS}"
