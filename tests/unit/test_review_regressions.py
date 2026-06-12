"""Regression tests for findings of the v0.7.0 adversarial review."""

from datetime import datetime, timezone
from unittest.mock import Mock

import numpy as np
import pytest
import yaml

from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.core.interval import Interval
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector


def make_data(values, step_minutes=10):
    values = np.asarray(values, dtype=float)
    timestamps = np.datetime64("2026-01-01") + np.arange(len(values)) * np.timedelta64(
        step_minutes, "m"
    )
    return {
        "timestamp": timestamps,
        "value": values,
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }


class TestWeightUnderflow:
    def test_tiny_half_life_with_long_nan_gap_does_not_crash(self):
        """All window points deep in the decay tail must degrade gracefully
        (near-uniform weights over old points), not crash on all-zero
        weights from float underflow."""
        rng = np.random.default_rng(0)
        values = rng.normal(100, 1, 2900)
        values[1100:2899] = np.nan  # long outage right before the evaluated tail
        det = MADDetector(
            window_size=2900,
            min_samples=10,
            window_weights="exponential",
            half_life=1,
        )
        results = det.detect(make_data(values))
        assert len(results) == 2900  # no exception

    def test_capped_weights_stay_positive(self):
        det = MADDetector(
            window_size=5000, min_samples=10, window_weights="exponential", half_life=1
        )
        lut = det._build_weight_lut(make_data(np.zeros(5000))["timestamp"])
        assert (lut > 0).all()


class TestSinglePointBatchWithDurationHalfLife:
    def test_one_point_batch_does_not_crash(self):
        """A brand-new metric's first 1-row batch must produce a graceful
        insufficient_data result, not a ValueError from grid inference."""
        det = ZScoreDetector(
            window_size=100,
            min_samples=10,
            window_weights="exponential",
            half_life="1d",
        )
        results = det.detect(make_data([42.0]))
        assert len(results) == 1
        assert results[0].is_anomaly is False


class TestAlgorithmVersionInDetectorId:
    def test_windowed_detectors_carry_v2_tag(self):
        """The σ-scaling/percentile-convention change must produce different
        detector IDs than v1 so old detections recompute instead of mixing."""
        det = MADDetector()
        assert det.ALGORITHM_VERSION == 2
        # v1 hash had no version tag — reproduce it and ensure inequality
        import hashlib

        v1_hash = hashlib.sha256(b"MADDetector[]").hexdigest()[:16]
        assert det.get_detector_id() != v1_hash


class TestSeverityConvention:
    def test_zscore_severity_is_zero_at_the_bound(self):
        """All windowed detectors share the 'distance beyond the bound in
        spread units' convention so the alert layer can compare them."""
        rng = np.random.default_rng(5)
        values = rng.normal(10, 1, 200)
        values[-1] = 50.0  # far beyond any bound
        det = ZScoreDetector(window_size=100, min_samples=30)
        result = det.detect(make_data(values))[-1]
        assert result.is_anomaly
        meta = result.detection_metadata
        expected = (50.0 - result.confidence_upper) / meta["adjusted_std"]
        assert meta["severity"] == pytest.approx(expected)


class TestRecoveryTriggerDirection:
    def test_trigger_direction_uses_quorum_not_first_row(self):
        """With 1 up-anomaly (sorting first) and 2 down-anomalies at the
        trigger point, the incident direction must be 'down'."""

        def row(detector_id, direction):
            return {
                "timestamp": datetime(2024, 1, 1, 12, 0, 0),
                "detector_ids": [detector_id],
                "detector_names": [detector_id],
                "detector_params_list": ["{}"],
                "detection_metadata_list": [
                    '{"direction": "%s", "severity": 2.0}'
                    % ("above" if direction == "up" else "below")
                ],
                "is_anomaly_flags": [True],
                "confidence_lowers": [1.0],
                "confidence_uppers": [2.0],
                "value": 5.0,
            }

        internal = Mock()
        internal.get_recent_detections.return_value = [
            row("a_up", "up"),
            row("b_down", "down"),
            row("c_down", "down"),
        ]
        orch = AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            conditions=AlertConditions(min_detectors=1, direction="same"),
            internal=internal,
        )
        direction = orch._get_alert_trigger_direction(
            datetime(2024, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
        )
        assert direction == "down"


class TestBaseExceptionLockStatus:
    def test_keyboard_interrupt_releases_lock_as_failed(self):
        from detectkit.config.metric_config import MetricConfig
        from detectkit.orchestration.task_manager import TaskManager

        internal_manager = Mock()
        internal_manager.acquire_lock.return_value = True
        manager = TaskManager(internal_manager=internal_manager, db_manager=Mock())

        config = Mock(spec=MetricConfig)
        config.name = "cpu_usage"
        manager._run_load_step = Mock(side_effect=KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            manager.run_metric(config)

        kwargs = internal_manager.release_lock.call_args.kwargs
        assert kwargs["status"] == "failed"
        assert "KeyboardInterrupt" in kwargs["error_message"]


class TestInitScaffolding:
    def test_generated_project_validates(self, tmp_path):
        from detectkit.cli.commands.init import run_init
        from detectkit.config.metric_config import MetricConfig
        from detectkit.config.profile import ProfilesConfig
        from detectkit.detectors.factory import DetectorFactory

        run_init("scaffold", str(tmp_path))

        metric = yaml.safe_load((tmp_path / "scaffold/metrics/example_cpu_usage.yml").read_text())
        mc = MetricConfig(**metric)
        for d in mc.detectors:
            DetectorFactory.create_from_config({"type": d.type, "params": d.params})

        profiles = yaml.safe_load((tmp_path / "scaffold/profiles.yml").read_text())
        pc = ProfilesConfig(**profiles)
        assert pc.default_profile == "dev"
        assert "dev" in pc.profiles and "prod" in pc.profiles
