"""Tests for TaskManager."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.task_manager import PipelineStep, TaskManager, TaskStatus


class TestPipelineStep:
    """Test PipelineStep enum."""

    def test_pipeline_steps(self):
        """Test pipeline step enum values."""
        assert PipelineStep.LOAD == "load"
        assert PipelineStep.DETECT == "detect"
        assert PipelineStep.ALERT == "alert"


class TestTaskStatus:
    """Test TaskStatus enum."""

    def test_task_statuses(self):
        """Test task status enum values."""
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.SUCCESS == "success"
        assert TaskStatus.FAILED == "failed"


class TestTaskManager:
    """Test TaskManager."""

    def test_init(self):
        """Test TaskManager initialization."""
        internal_manager = Mock()
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        assert manager.internal == internal_manager
        assert manager.db_manager == db_manager

    def test_run_metric_success_all_steps(self):
        """Test successful metric run with all steps."""
        internal_manager = Mock()
        internal_manager.acquire_lock.return_value = True
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        # Mock config
        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.timeouts = {"total": 3600}

        # Mock the step methods
        manager._run_load_step = Mock(return_value={"points_loaded": 100})
        manager._run_detect_step = Mock(return_value={"anomalies_count": 5})
        manager._run_alert_step = Mock(return_value={"alerts_sent": 2})

        result = manager.run_metric(config)

        assert result["status"] == TaskStatus.SUCCESS
        assert result["datapoints_loaded"] == 100
        assert result["anomalies_detected"] == 5
        assert result["alerts_sent"] == 2
        assert result["error"] is None
        assert result["steps_completed"] == [
            PipelineStep.LOAD,
            PipelineStep.DETECT,
            PipelineStep.ALERT,
        ]

        # Verify lock was acquired and released (with new API signature)
        internal_manager.acquire_lock.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="pipeline",
            process_type="pipeline",
            timeout_seconds=3600,
        )
        internal_manager.release_lock.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="pipeline",
            process_type="pipeline",
            status="completed",
            error_message=None,
        )

    def test_run_metric_partial_steps(self):
        """Test running only specific pipeline steps."""
        internal_manager = Mock()
        internal_manager.acquire_lock.return_value = True
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.timeouts = {"total": 3600}

        manager._run_load_step = Mock(return_value={"points_loaded": 100})
        manager._run_detect_step = Mock(return_value={"anomalies_count": 5})
        manager._run_alert_step = Mock(return_value={"alerts_sent": 0})

        result = manager.run_metric(
            config,
            steps=[PipelineStep.LOAD, PipelineStep.DETECT],
        )

        assert result["status"] == TaskStatus.SUCCESS
        assert result["steps_completed"] == [PipelineStep.LOAD, PipelineStep.DETECT]
        assert PipelineStep.ALERT not in result["steps_completed"]

        # Verify only load and detect were called
        manager._run_load_step.assert_called_once()
        manager._run_detect_step.assert_called_once()
        manager._run_alert_step.assert_not_called()

    def test_run_metric_lock_failed(self):
        """Test failure when lock cannot be acquired."""
        internal_manager = Mock()
        internal_manager.acquire_lock.return_value = False
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.timeouts = {"total": 3600}

        result = manager.run_metric(config)

        assert result["status"] == TaskStatus.FAILED
        assert "Failed to acquire lock" in result["error"]
        assert result["steps_completed"] == []

        # Verify lock was not released (because it wasn't acquired)
        internal_manager.release_lock.assert_not_called()

    def test_run_metric_with_force(self):
        """Test running with force flag (ignore locks)."""
        internal_manager = Mock()
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.timeouts = {"total": 3600}

        manager._run_load_step = Mock(return_value={"points_loaded": 100})
        manager._run_detect_step = Mock(return_value={"anomalies_count": 5})
        manager._run_alert_step = Mock(return_value={"alerts_sent": 2})

        result = manager.run_metric(config, force=True)

        assert result["status"] == TaskStatus.SUCCESS

        # Verify lock was NOT acquired or released
        internal_manager.acquire_lock.assert_not_called()
        internal_manager.release_lock.assert_not_called()

    def test_run_metric_with_error(self):
        """Test error handling during pipeline execution."""
        internal_manager = Mock()
        internal_manager.acquire_lock.return_value = True
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.timeouts = {"total": 3600}

        # Make load step raise an error
        manager._run_load_step = Mock(side_effect=Exception("Database connection error"))

        result = manager.run_metric(config)

        assert result["status"] == TaskStatus.FAILED
        assert "Database connection error" in result["error"]
        assert result["steps_completed"] == []

        # Verify lock was released even on error (with new API signature)
        internal_manager.release_lock.assert_called_once_with(
            metric_name="cpu_usage",
            detector_id="pipeline",
            process_type="pipeline",
            status="completed",
            error_message=None,
        )

    def test_run_load_step(self):
        """Test _run_load_step method."""
        internal_manager = Mock()
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        # Mock get_interval() to return Interval object with seconds attribute
        mock_interval = Mock()
        mock_interval.seconds = 600  # 10 minutes
        config.get_interval.return_value = mock_interval
        config.loading_batch_size = 1000

        # Mock MetricLoader
        with patch("detectkit.orchestration.task_manager.MetricLoader") as MockLoader:
            mock_loader = MockLoader.return_value
            mock_loader.load_and_save.return_value = 100  # Returns int, not dict

            result = manager._run_load_step(
                config,
                from_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
                to_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
                full_refresh=False,
            )

            assert result["points_loaded"] == 100
            # Check constructor call (parameter order: config, db_manager, internal_manager)
            MockLoader.assert_called_once_with(
                config=config,
                db_manager=db_manager,
                internal_manager=internal_manager,
            )
            mock_loader.load_and_save.assert_called_once()

    def test_run_detect_step(self):
        """Test _run_detect_step method."""
        internal_manager = Mock()
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.interval = "10min"
        config.detectors = []

        result = manager._run_detect_step(config, None, None)

        # Currently returns 0 (placeholder implementation)
        assert result["anomalies_count"] == 0

    def test_run_alert_step_no_config(self):
        """Test _run_alert_step when no alerting configured."""
        internal_manager = Mock()
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        config.alerting = None  # No alerting configured

        result = manager._run_alert_step(config)

        assert result["alerts_sent"] == 0

    def test_get_metric_status(self):
        """Test getting metric status."""
        internal_manager = Mock()
        internal_manager.check_lock.return_value = {
            "locked_by": "worker-1",
            "locked_at": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        internal_manager.get_last_datapoint_timestamp.return_value = datetime(
            2024, 1, 1, 11, 50, 0, tzinfo=timezone.utc
        )
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        status = manager.get_metric_status("cpu_usage")

        assert status["metric_name"] == "cpu_usage"
        assert status["is_locked"] is True
        assert status["locked_by"] == "worker-1"
        assert status["last_datapoint"] == datetime(
            2024, 1, 1, 11, 50, 0, tzinfo=timezone.utc
        )

    def test_get_metric_status_not_locked(self):
        """Test getting status for unlocked metric."""
        internal_manager = Mock()
        internal_manager.check_lock.return_value = None
        internal_manager.get_last_datapoint_timestamp.return_value = None
        db_manager = Mock()

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        status = manager.get_metric_status("cpu_usage")

        assert status["is_locked"] is False
        assert status["locked_by"] is None
        assert status["last_datapoint"] is None

    def test_repr(self):
        """Test string representation."""
        internal_manager = Mock()
        db_manager = Mock()
        db_manager.__class__.__name__ = "ClickHouseDatabaseManager"

        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=db_manager,
        )

        repr_str = repr(manager)

        assert "TaskManager" in repr_str
        assert "ClickHouseDatabaseManager" in repr_str
