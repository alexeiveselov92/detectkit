"""Tests for AlertOrchestrator."""

from datetime import datetime, timezone
from unittest.mock import Mock

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.orchestrator import (
    AlertConditions,
    AlertOrchestrator,
    DetectionRecord,
)
from detectkit.core.interval import Interval


class TestAlertConditions:
    """Test AlertConditions dataclass."""

    def test_default_conditions(self):
        """Test default alert conditions."""
        conditions = AlertConditions()

        # Defaults mirror the pydantic AlertConfig defaults
        assert conditions.min_detectors == 1
        assert conditions.direction == "same"
        assert conditions.consecutive_anomalies == 3

    def test_custom_conditions(self):
        """Test custom alert conditions."""
        conditions = AlertConditions(
            min_detectors=2,
            direction="same",
            consecutive_anomalies=3,
        )

        assert conditions.min_detectors == 2
        assert conditions.direction == "same"
        assert conditions.consecutive_anomalies == 3


class TestDetectionRecord:
    """Test DetectionRecord dataclass."""

    def test_create_detection_record(self):
        """Test creating detection record."""
        record = DetectionRecord(
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            detector_name="zscore",
            detector_id="abc123",
            detector_params='{"threshold": 3.0}',
            value=100.0,
            is_anomaly=True,
            confidence_lower=80.0,
            confidence_upper=120.0,
            direction="up",
            severity=2.5,
            detection_metadata={"threshold": 3.0},
        )

        assert record.detector_name == "zscore"
        assert record.is_anomaly is True
        assert record.direction == "up"
        assert record.severity == 2.5


class TestAlertOrchestrator:
    """Test AlertOrchestrator."""

    def test_init_default(self):
        """Test initialization with defaults."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        assert orchestrator.metric_name == "cpu_usage"
        assert orchestrator.interval.seconds == 600
        assert orchestrator.conditions.min_detectors == 1
        assert orchestrator.timezone_display == "UTC"

    def test_init_custom_conditions(self):
        """Test initialization with custom conditions."""
        conditions = AlertConditions(
            min_detectors=2,
            direction="same",
            consecutive_anomalies=3,
        )

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
            timezone_display="Europe/Moscow",
        )

        assert orchestrator.conditions.min_detectors == 2
        assert orchestrator.conditions.direction == "same"
        assert orchestrator.conditions.consecutive_anomalies == 3
        assert orchestrator.timezone_display == "Europe/Moscow"

    def test_should_alert_no_detections(self):
        """Test should_alert with no detections."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        should_alert, alert_data = orchestrator.should_alert([])

        assert should_alert is False
        assert alert_data is None

    def test_should_alert_single_anomaly_default_conditions(self):
        """Test alert with a single anomalous point (consecutive=1)."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=AlertConditions(consecutive_anomalies=1),
        )

        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc123",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.5,
                detection_metadata={"threshold": 3.0},
            )
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is True
        assert alert_data is not None
        assert alert_data.metric_name == "cpu_usage"
        assert alert_data.value == 100.0
        assert alert_data.detector_name == "zscore"
        assert alert_data.consecutive_count == 1

    def test_should_alert_insufficient_detectors(self):
        """Test no alert when min_detectors not met."""
        conditions = AlertConditions(min_detectors=2)
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # Only 1 detector triggered
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc123",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.5,
                detection_metadata={},
            )
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is False
        assert alert_data is None

    def test_should_alert_multiple_detectors(self):
        """Test alert with multiple detectors."""
        conditions = AlertConditions(min_detectors=2, consecutive_anomalies=1)
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc123",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.5,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="mad",
                detector_id="def456",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=75.0,
                confidence_upper=125.0,
                direction="up",
                severity=3.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is True
        assert alert_data is not None
        assert alert_data.detector_name == "2 detectors"
        assert alert_data.severity == 3.0  # Max severity
        assert alert_data.detection_metadata["count"] == 2

    def test_consecutive_anomalies_direction_any(self):
        """Test consecutive anomalies with direction=any."""
        conditions = AlertConditions(
            direction="any",
            consecutive_anomalies=3,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # 3 consecutive anomalies with different directions
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=90.0,
                is_anomaly=True,
                confidence_lower=70.0,
                confidence_upper=110.0,
                direction="down",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:40:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=110.0,
                is_anomaly=True,
                confidence_lower=90.0,
                confidence_upper=130.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is True
        assert alert_data.consecutive_count == 3

    def test_consecutive_anomalies_direction_same(self):
        """Test consecutive anomalies with direction=same."""
        conditions = AlertConditions(
            direction="same",
            consecutive_anomalies=3,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # 3 consecutive anomalies in same direction
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=105.0,
                is_anomaly=True,
                confidence_lower=85.0,
                confidence_upper=125.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:40:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=110.0,
                is_anomaly=True,
                confidence_lower=90.0,
                confidence_upper=130.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is True
        assert alert_data.consecutive_count == 3

    def test_consecutive_anomalies_direction_changed(self):
        """Test consecutive stops when direction changes."""
        conditions = AlertConditions(
            direction="same",
            consecutive_anomalies=3,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # Direction changes on 3rd point
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=105.0,
                is_anomaly=True,
                confidence_lower=85.0,
                confidence_upper=125.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:40:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=90.0,
                is_anomaly=True,
                confidence_lower=70.0,
                confidence_upper=110.0,
                direction="down",  # Direction changed!
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        # Only 2 consecutive in same direction, need 3
        assert should_alert is False

    def test_consecutive_anomalies_direction_up(self):
        """Test consecutive anomalies with direction=up."""
        conditions = AlertConditions(
            direction="up",
            consecutive_anomalies=2,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=105.0,
                is_anomaly=True,
                confidence_lower=85.0,
                confidence_upper=125.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is True
        assert alert_data.consecutive_count == 2

    def test_consecutive_anomalies_direction_down_fails(self):
        """Test direction=down fails when direction is up."""
        conditions = AlertConditions(
            direction="down",
            consecutive_anomalies=2,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # Anomalies are "up" but we require "down"
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=105.0,
                is_anomaly=True,
                confidence_lower=85.0,
                confidence_upper=125.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        assert should_alert is False

    def test_consecutive_with_non_anomaly_break(self):
        """Test consecutive count breaks on non-anomaly."""
        conditions = AlertConditions(
            direction="any",
            consecutive_anomalies=3,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        # 2 anomalies, then normal, then 1 more anomaly
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:50:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=85.0,
                is_anomaly=True,
                confidence_lower=75.0,
                confidence_upper=95.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:40:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=50.0,
                is_anomaly=False,  # Normal point breaks consecutive
                confidence_lower=40.0,
                confidence_upper=60.0,
                direction="none",
                severity=0.0,
                detection_metadata={},
            ),
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T11:30:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=110.0,
                is_anomaly=True,
                confidence_lower=90.0,
                confidence_upper=130.0,
                direction="up",
                severity=2.0,
                detection_metadata={},
            ),
        ]

        should_alert, alert_data = orchestrator.should_alert(detections)

        # Only 2 consecutive, need 3
        assert should_alert is False

    def test_get_last_complete_point(self):
        """Test determining last complete point."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        # Now is 13:23 -> last complete is 13:10
        now = datetime(2024, 1, 1, 13, 23, 0, tzinfo=timezone.utc)
        last_point = orchestrator.get_last_complete_point(now)

        assert last_point == datetime(2024, 1, 1, 13, 10, 0, tzinfo=timezone.utc)

    def test_get_last_complete_point_hourly(self):
        """Test last complete point with hourly interval."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("1h"),
        )

        now = datetime(2024, 1, 1, 13, 45, 0, tzinfo=timezone.utc)
        last_point = orchestrator.get_last_complete_point(now)

        assert last_point == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_send_alerts_success(self):
        """Test sending alerts through channels."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        alert_data = AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="zscore",
            detector_params="abc123",
            direction="up",
            severity=2.5,
            detection_metadata={},
            consecutive_count=3,
        )

        # Mock channels
        channel1 = Mock()
        channel1.__class__.__name__ = "MattermostChannel"
        channel1.send.return_value = True

        channel2 = Mock()
        channel2.__class__.__name__ = "SlackChannel"
        channel2.send.return_value = True

        results = orchestrator.send_alerts(alert_data, [channel1, channel2])

        assert results["MattermostChannel"] is True
        assert results["SlackChannel"] is True
        assert channel1.send.called
        assert channel2.send.called

    def test_send_alerts_with_failure(self):
        """Test sending alerts with channel failure."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        alert_data = AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="zscore",
            detector_params="abc123",
            direction="up",
            severity=2.5,
            detection_metadata={},
        )

        # Mock channel that fails
        channel = Mock()
        channel.__class__.__name__ = "MattermostChannel"
        channel.send.return_value = False

        results = orchestrator.send_alerts(alert_data, [channel])

        assert results["MattermostChannel"] is False

    def test_send_alerts_with_exception(self):
        """Test sending alerts with channel exception."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        alert_data = AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="zscore",
            detector_params="abc123",
            direction="up",
            severity=2.5,
            detection_metadata={},
        )

        # Mock channel that raises exception
        channel = Mock()
        channel.__class__.__name__ = "MattermostChannel"
        channel.send.side_effect = Exception("Network error")

        results = orchestrator.send_alerts(alert_data, [channel])

        assert results["MattermostChannel"] is False

    def test_repr(self):
        """Test string representation."""
        conditions = AlertConditions(
            min_detectors=2,
            direction="same",
            consecutive_anomalies=3,
        )
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            conditions=conditions,
        )

        repr_str = repr(orchestrator)

        assert "AlertOrchestrator" in repr_str
        assert "cpu_usage" in repr_str
        assert "min_detectors=2" in repr_str
        assert "direction='same'" in repr_str
        assert "consecutive=3" in repr_str


class TestRecoveryNotifications:
    """Test recovery notification logic."""

    def _make_detection(self, timestamp_str, is_anomaly=True, direction="up"):
        """Helper to create DetectionRecord."""
        return DetectionRecord(
            timestamp=np.datetime64(timestamp_str, "ms"),
            detector_name="zscore",
            detector_id="abc123",
            detector_params='{"threshold": 3.0}',
            value=100.0,
            is_anomaly=is_anomaly,
            confidence_lower=80.0,
            confidence_upper=120.0,
            direction=direction,
            severity=2.0 if is_anomaly else 0.0,
            detection_metadata={},
        )

    def test_should_send_recovery_no_internal(self):
        """Recovery returns False when no internal manager."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
        )

        should_recover, data = orchestrator.should_send_recovery([])
        assert should_recover is False
        assert data is None

    def test_should_send_recovery_no_previous_alert(self):
        """Recovery returns False when no alert was ever sent."""
        internal = Mock()
        internal.get_last_alert_timestamp.return_value = None

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        detections = [self._make_detection("2024-01-01T12:00:00", is_anomaly=False)]
        should_recover, data = orchestrator.should_send_recovery(detections)

        assert should_recover is False

    def test_should_send_recovery_already_sent(self):
        """Recovery returns False when recovery already sent for this incident."""
        internal = Mock()
        internal.get_last_alert_timestamp.return_value = datetime(2024, 1, 1, 11, 0, 0)
        internal.get_last_recovery_timestamp.return_value = datetime(2024, 1, 1, 12, 0, 0)

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        detections = [self._make_detection("2024-01-01T12:10:00", is_anomaly=False)]
        should_recover, data = orchestrator.should_send_recovery(detections)

        assert should_recover is False

    def test_should_send_recovery_still_anomaly(self):
        """Recovery returns False when metric is still in anomaly state."""
        internal = Mock()
        internal.get_last_alert_timestamp.return_value = datetime(2024, 1, 1, 11, 0, 0)
        internal.get_last_recovery_timestamp.return_value = None

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        # Mock _check_recovery_since_last_alert to return False
        orchestrator._check_recovery_since_last_alert = Mock(return_value=False)

        detections = [self._make_detection("2024-01-01T12:00:00", is_anomaly=True)]
        should_recover, data = orchestrator.should_send_recovery(detections)

        assert should_recover is False

    def test_should_send_recovery_success(self):
        """Recovery returns True when conditions are met."""
        internal = Mock()
        internal.get_last_alert_timestamp.return_value = datetime(2024, 1, 1, 11, 0, 0)
        internal.get_last_recovery_timestamp.return_value = None
        # No prior detections to reconstruct the incident span from (recovery
        # still fires; it just omits the "Incident lasted …" duration).
        internal.get_recent_detections.return_value = []

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        # Mock recovery check
        orchestrator._check_recovery_since_last_alert = Mock(return_value=True)

        detections = [
            self._make_detection("2024-01-01T12:00:00", is_anomaly=False, direction="none")
        ]
        should_recover, data = orchestrator.should_send_recovery(detections)

        assert should_recover is True
        assert data is not None
        assert data.is_recovery is True
        assert data.metric_name == "cpu_usage"
        assert data.direction == "none"
        assert data.severity == 0.0

    def test_should_send_recovery_after_new_alert(self):
        """Recovery allowed when last_recovery < last_alert (new incident happened)."""
        internal = Mock()
        internal.get_last_alert_timestamp.return_value = datetime(2024, 1, 1, 14, 0, 0)
        internal.get_last_recovery_timestamp.return_value = datetime(2024, 1, 1, 12, 0, 0)
        internal.get_recent_detections.return_value = []

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        orchestrator._check_recovery_since_last_alert = Mock(return_value=True)

        detections = [
            self._make_detection("2024-01-01T15:00:00", is_anomaly=False, direction="none")
        ]
        should_recover, data = orchestrator.should_send_recovery(detections)

        assert should_recover is True
        assert data.is_recovery is True

    def test_send_recovery_updates_timestamp(self):
        """send_recovery updates last_recovery_sent timestamp."""
        internal = Mock()

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        recovery_data = AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=90.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="zscore",
            detector_params="{}",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_recovery=True,
        )

        channel = Mock()
        channel.__class__.__name__ = "MattermostChannel"
        channel.send.return_value = True

        results = orchestrator.send_recovery(recovery_data, [channel])

        assert results["MattermostChannel"] is True
        internal.update_recovery_timestamp.assert_called_once()

    def test_send_recovery_no_update_on_failure(self):
        """send_recovery does not update timestamp when all channels fail."""
        internal = Mock()

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
        )

        recovery_data = AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=90.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="zscore",
            detector_params="{}",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_recovery=True,
        )

        channel = Mock()
        channel.__class__.__name__ = "MattermostChannel"
        channel.send.return_value = False

        results = orchestrator.send_recovery(recovery_data, [channel])

        assert results["MattermostChannel"] is False
        internal.update_recovery_timestamp.assert_not_called()


class TestProjectNameThreading:
    """``project_name`` from the project config rides into every AlertData.

    Lets multiple projects share one alert channel (keeping the default brand
    bot name + avatar) while staying distinguishable in the message.
    """

    @staticmethod
    def _orchestrator(internal=None):
        return AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="cfg",
            interval=Interval("10min"),
            conditions=AlertConditions(consecutive_anomalies=1),
            internal=internal,
            project_name="my_monitoring",
        )

    def test_anomaly_alert_data_carries_project_name(self):
        orchestrator = self._orchestrator()
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=100.0,
                is_anomaly=True,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="up",
                severity=2.5,
                detection_metadata={},
            )
        ]
        should_alert, alert_data = orchestrator.should_alert(detections)
        assert should_alert is True
        assert alert_data.project_name == "my_monitoring"

    def test_no_data_alert_data_carries_project_name(self):
        alert_config = Mock()
        alert_config.no_data_alert = True
        internal = Mock()
        internal.get_value_at.return_value = None  # missing datapoint
        internal.get_last_alert_timestamp.return_value = None  # not in cooldown

        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="cfg",
            interval=Interval("10min"),
            conditions=AlertConditions(consecutive_anomalies=1),
            internal=internal,
            alert_config=alert_config,
            project_name="my_monitoring",
        )
        last_point = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        should_no_data, alert_data = orchestrator.should_alert_no_data(last_point)
        assert should_no_data is True
        assert alert_data.is_no_data is True
        assert alert_data.project_name == "my_monitoring"

    def test_recovery_alert_data_carries_project_name(self):
        orchestrator = self._orchestrator()
        detections = [
            DetectionRecord(
                timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
                detector_name="zscore",
                detector_id="abc",
                detector_params="{}",
                value=90.0,
                is_anomaly=False,
                confidence_lower=80.0,
                confidence_upper=120.0,
                direction="none",
                severity=0.0,
                detection_metadata={},
            )
        ]
        recovery_data = orchestrator._build_recovery_data(detections)
        assert recovery_data is not None
        assert recovery_data.project_name == "my_monitoring"

    def test_project_name_defaults_to_none(self):
        """Direct-API callers that don't set it render unchanged (back-compat)."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="cfg",
            interval=Interval("10min"),
        )
        assert orchestrator.project_name is None
