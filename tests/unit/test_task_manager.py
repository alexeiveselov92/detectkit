"""Tests for TaskManager."""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

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

        # Mock MetricLoader (imported inside the LOAD-step mixin module)
        with patch("detectkit.orchestration.task_manager._load_step.MetricLoader") as MockLoader:
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
        assert status["last_datapoint"] == datetime(2024, 1, 1, 11, 50, 0, tzinfo=timezone.utc)

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


class TestLoadRecentDetections:
    """Tests for ``_load_recent_detections`` fanout behavior."""

    def _make_manager(self, results):
        internal_manager = Mock()
        internal_manager.get_recent_detections.return_value = results
        manager = TaskManager(
            internal_manager=internal_manager,
            db_manager=Mock(),
        )
        return manager

    def test_emits_one_record_per_detector_per_timestamp(self):
        """Two detectors at the same timestamp must yield two DetectionRecords.

        Regression test: previously detectors were aggregated into a single
        record per timestamp, which silently broke ``min_detectors >= 2``.
        """
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        results = [
            {
                "timestamp": ts,
                "detector_ids": ["mad_id", "manual_id"],
                "detector_names": ["MADDetector", "ManualBoundsDetector"],
                "detector_params_list": ['{"threshold":3.0}', '{"lower_bound":7}'],
                "detection_metadata_list": [
                    '{"direction":"below","severity":2.5}',
                    '{"direction":"below"}',
                ],
                "is_anomaly_flags": [True, True],
                "confidence_lowers": [29.0, 7.0],
                "confidence_uppers": [75.1, None],
                "value": 5.0,
            }
        ]
        manager = self._make_manager(results)

        records = manager._load_recent_detections(
            metric_name="m",
            last_point=ts,
            num_points=1,
        )

        assert len(records) == 2
        names = {r.detector_name for r in records}
        assert names == {"MADDetector", "ManualBoundsDetector"}
        assert all(r.is_anomaly for r in records)
        assert all(r.direction == "down" for r in records)
        # Bounds are kept per-detector, not flattened to detector[0].
        mad = next(r for r in records if r.detector_name == "MADDetector")
        manual = next(r for r in records if r.detector_name == "ManualBoundsDetector")
        assert mad.confidence_upper == 75.1
        assert manual.confidence_upper is None

    def test_chronological_order_with_multiple_timestamps(self):
        """Output must be oldest→newest (recovery reads ``[-1]``)."""
        older = datetime(2024, 1, 1, 11, 50, 0, tzinfo=timezone.utc)
        newer = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # ``get_recent_detections`` returns newest first.
        results = [
            {
                "timestamp": newer,
                "detector_ids": ["a"],
                "detector_names": ["A"],
                "detector_params_list": ["{}"],
                "detection_metadata_list": [None],
                "is_anomaly_flags": [False],
                "confidence_lowers": [10.0],
                "confidence_uppers": [20.0],
                "value": 15.0,
            },
            {
                "timestamp": older,
                "detector_ids": ["a"],
                "detector_names": ["A"],
                "detector_params_list": ["{}"],
                "detection_metadata_list": [None],
                "is_anomaly_flags": [False],
                "confidence_lowers": [10.0],
                "confidence_uppers": [20.0],
                "value": 12.0,
            },
        ]
        manager = self._make_manager(results)

        records = manager._load_recent_detections(
            metric_name="m",
            last_point=newer,
            num_points=2,
        )

        assert [r.timestamp for r in records] == [older, newer]
        assert records[-1].value == 15.0  # newest is last (recovery contract)
