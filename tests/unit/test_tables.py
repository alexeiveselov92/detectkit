"""Tests for internal table models."""

from detectkit.database.tables import (
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_TASKS,
    get_datapoints_table_model,
    get_detections_table_model,
    get_tasks_table_model,
)


class TestDatapointsTable:
    """Test _dtk_datapoints table model."""

    def test_table_name(self):
        """Test table name constant."""
        assert TABLE_DATAPOINTS == "_dtk_datapoints"

    def test_schema(self):
        """Test datapoints table schema."""
        model = get_datapoints_table_model()

        # Check all columns exist
        column_names = [col.name for col in model.columns]
        expected_columns = [
            "metric_name",
            "timestamp",
            "value",
            "seasonality_data",
            "interval_seconds",
            "seasonality_columns",
            "created_at",
        ]
        assert column_names == expected_columns

        # Check primary key
        assert model.primary_key == ["metric_name", "timestamp"]

        # Check engine and order (ReplacingMergeTree to prevent duplicates)
        assert model.engine == "ReplacingMergeTree(created_at)"
        assert model.order_by == ["metric_name", "timestamp"]

    def test_nullable_columns(self):
        """Test nullable columns in datapoints table."""
        model = get_datapoints_table_model()

        # value should be nullable (for missing data)
        value_col = model.get_column("value")
        assert value_col is not None
        assert value_col.nullable is True

        # metric_name should not be nullable
        metric_col = model.get_column("metric_name")
        assert metric_col is not None
        assert metric_col.nullable is False


class TestDetectionsTable:
    """Test _dtk_detections table model."""

    def test_table_name(self):
        """Test table name constant."""
        assert TABLE_DETECTIONS == "_dtk_detections"

    def test_schema(self):
        """Test detections table schema."""
        model = get_detections_table_model()

        # Check all columns exist (according to init_plan.md spec)
        column_names = [col.name for col in model.columns]
        expected_columns = [
            "metric_name",
            "detector_id",
            "timestamp",
            "is_anomaly",
            "confidence_lower",
            "confidence_upper",
            "value",
            "detector_params",
            "detection_metadata",
            "created_at",
        ]
        assert column_names == expected_columns

        # Check primary key
        assert model.primary_key == ["metric_name", "detector_id", "timestamp"]

        # Check engine and order (ReplacingMergeTree to prevent duplicates)
        assert model.engine == "ReplacingMergeTree(created_at)"
        assert model.order_by == ["metric_name", "detector_id", "timestamp"]

    def test_nullable_columns(self):
        """Test nullable columns in detections table."""
        model = get_detections_table_model()

        # These should be nullable
        nullable_cols = ["value", "confidence_lower", "confidence_upper"]
        for col_name in nullable_cols:
            col = model.get_column(col_name)
            assert col is not None, f"Column {col_name} not found"
            assert col.nullable is True, f"Column {col_name} should be nullable"

        # These should NOT be nullable
        not_nullable_cols = ["is_anomaly", "detector_params", "detection_metadata"]
        for col_name in not_nullable_cols:
            col = model.get_column(col_name)
            assert col is not None, f"Column {col_name} not found"
            assert col.nullable is False, f"Column {col_name} should not be nullable"


class TestTasksTable:
    """Test _dtk_tasks table model."""

    def test_table_name(self):
        """Test table name constant."""
        assert TABLE_TASKS == "_dtk_tasks"

    def test_schema(self):
        """Test tasks table schema."""
        model = get_tasks_table_model()

        # Check all columns exist (including those that were missing before!)
        column_names = [col.name for col in model.columns]
        expected_columns = [
            "metric_name",
            "detector_id",
            "process_type",
            "status",
            "started_at",
            "updated_at",  # This was missing before
            "last_processed_timestamp",  # This was missing before
            "error_message",
            "timeout_seconds",  # This was missing before
            "last_alert_sent",  # For alert cooldown tracking
            "alert_count",  # For alert statistics
        ]
        assert column_names == expected_columns

        # Check primary key
        assert model.primary_key == ["metric_name", "detector_id", "process_type"]

        # Check engine and order
        assert model.engine == "MergeTree"
        assert model.order_by == ["metric_name", "detector_id", "process_type"]

    def test_nullable_columns(self):
        """Test nullable columns in tasks table."""
        model = get_tasks_table_model()

        # These should be nullable
        nullable_cols = ["last_processed_timestamp", "error_message"]
        for col_name in nullable_cols:
            col = model.get_column(col_name)
            assert col is not None, f"Column {col_name} not found"
            assert col.nullable is True, f"Column {col_name} should be nullable"

        # These should NOT be nullable
        not_nullable_cols = [
            "metric_name",
            "detector_id",
            "process_type",
            "status",
            "started_at",
            "updated_at",
            "timeout_seconds",
        ]
        for col_name in not_nullable_cols:
            col = model.get_column(col_name)
            assert col is not None, f"Column {col_name} not found"
            assert col.nullable is False, f"Column {col_name} should not be nullable"

    def test_critical_fields_present(self):
        """Test that critical fields are present (those that were missing in previous version)."""
        model = get_tasks_table_model()

        # These were missing in the first implementation!
        assert model.get_column("updated_at") is not None
        assert model.get_column("last_processed_timestamp") is not None
        assert model.get_column("timeout_seconds") is not None
