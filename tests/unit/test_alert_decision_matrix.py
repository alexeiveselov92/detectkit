"""Decision-matrix tests for the multi-detector alert contract.

Documents and pins the direction-aware quorum semantics:
- "up"/"down": only anomalies in that direction count toward min_detectors
- "any": every anomaly counts regardless of direction
- "same": min_detectors must agree on ONE direction; it locks across points
- consecutive points must be exactly one interval apart (grid adjacency)
- the outcome never depends on record ordering
"""

import numpy as np

from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.core.interval import Interval

T0 = np.datetime64("2024-01-01T12:00:00", "ms")
STEP = np.timedelta64(10, "m")


def record(ts, detector, direction, is_anomaly=True, severity=2.0):
    return DetectionRecord(
        timestamp=ts,
        detector_name=detector,
        detector_id=f"id_{detector}",
        detector_params="{}",
        value=100.0,
        is_anomaly=is_anomaly,
        confidence_lower=80.0,
        confidence_upper=120.0,
        direction=direction if is_anomaly else "none",
        severity=severity if is_anomaly else 0.0,
        detection_metadata={},
    )


def orchestrator(min_detectors=1, direction="any", consecutive=1):
    return AlertOrchestrator(
        metric_name="m",
        alert_config_id="cfg",
        interval=Interval("10min"),
        conditions=AlertConditions(
            min_detectors=min_detectors,
            direction=direction,
            consecutive_anomalies=consecutive,
        ),
    )


class TestDirectionQuorum:
    def test_same_disagreeing_detectors_do_not_alert(self):
        """A says up, B says down: that's not consensus."""
        orch = orchestrator(min_detectors=2, direction="same")
        detections = [record(T0, "a", "up"), record(T0, "b", "down")]
        should, _ = orch.should_alert(detections)
        assert should is False

    def test_same_agreeing_detectors_alert(self):
        orch = orchestrator(min_detectors=2, direction="same")
        detections = [record(T0, "a", "down"), record(T0, "b", "down")]
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.direction == "down"

    def test_up_quorum_ignores_down_anomalies(self):
        """direction=up with one up + one down detector: only the up one
        counts, so min_detectors=2 is not met."""
        orch = orchestrator(min_detectors=2, direction="up")
        detections = [record(T0, "a", "up"), record(T0, "b", "down")]
        should, _ = orch.should_alert(detections)
        assert should is False

    def test_up_quorum_met_by_two_up_detectors(self):
        orch = orchestrator(min_detectors=2, direction="up")
        detections = [
            record(T0, "a", "up"),
            record(T0, "b", "down"),
            record(T0, "c", "up"),
        ]
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.direction == "up"
        assert data.detection_metadata["count"] == 2  # only the up pair

    def test_down_single_detector_fires_even_if_listed_second(self):
        """Order independence: the down detector must be found regardless
        of record ordering (old code looked only at anomalies[0])."""
        orch = orchestrator(min_detectors=1, direction="down")
        for order in (
            [record(T0, "a", "up"), record(T0, "b", "down")],
            [record(T0, "b", "down"), record(T0, "a", "up")],
        ):
            should, data = orch.should_alert(order)
            assert should is True
            assert data.direction == "down"

    def test_any_mixed_directions_count_together(self):
        orch = orchestrator(min_detectors=2, direction="any")
        detections = [record(T0, "a", "up"), record(T0, "b", "down")]
        should, data = orch.should_alert(detections)
        assert should is True

    def test_non_anomalous_records_never_count(self):
        orch = orchestrator(min_detectors=2, direction="any")
        detections = [record(T0, "a", "up"), record(T0, "b", "none", is_anomaly=False)]
        should, _ = orch.should_alert(detections)
        assert should is False


class TestConsecutive:
    def test_same_direction_locked_across_points(self):
        """same: latest point's winning direction must hold for the whole
        consecutive chain — a direction flip breaks it."""
        orch = orchestrator(min_detectors=1, direction="same", consecutive=2)
        flip = [
            record(T0 - STEP, "a", "up"),
            record(T0, "a", "down"),
        ]
        should, _ = orch.should_alert(flip)
        assert should is False

        stable = [
            record(T0 - STEP, "a", "down"),
            record(T0, "a", "down"),
        ]
        should, data = orch.should_alert(stable)
        assert should is True
        assert data.consecutive_count == 2

    def test_grid_gap_breaks_the_chain(self):
        """Two anomalies separated by a missing interval are NOT consecutive."""
        orch = orchestrator(min_detectors=1, direction="any", consecutive=2)
        detections = [
            record(T0 - 2 * STEP, "a", "down"),  # gap: T0 - STEP is missing
            record(T0, "a", "down"),
        ]
        should, _ = orch.should_alert(detections)
        assert should is False

    def test_adjacent_points_chain(self):
        orch = orchestrator(min_detectors=1, direction="any", consecutive=3)
        detections = [
            record(T0 - 2 * STEP, "a", "down"),
            record(T0 - STEP, "a", "down"),
            record(T0, "a", "down"),
        ]
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.consecutive_count == 3

    def test_latest_point_must_satisfy_quorum(self):
        """An anomaly streak that already ended must not alert."""
        orch = orchestrator(min_detectors=1, direction="any", consecutive=1)
        detections = [
            record(T0 - STEP, "a", "down"),
            record(T0, "a", "none", is_anomaly=False),
        ]
        should, _ = orch.should_alert(detections)
        assert should is False


class TestPrimaryRecord:
    def test_alert_payload_uses_highest_severity_detector(self):
        orch = orchestrator(min_detectors=2, direction="same")
        detections = [
            record(T0, "weak", "down", severity=1.5),
            record(T0, "strong", "down", severity=9.0),
        ]
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.severity == 9.0
        # combined payload mentions both
        assert data.detector_name == "2 detectors"
        assert set(data.detection_metadata["detectors"]) == {"weak", "strong"}

    def test_single_detector_payload(self):
        orch = orchestrator(min_detectors=1, direction="any")
        should, data = orch.should_alert([record(T0, "only", "up", severity=4.0)])
        assert should is True
        assert data.detector_name == "only"
        assert data.severity == 4.0
        assert data.direction == "up"

    def test_same_tie_broken_deterministically(self):
        """min_detectors=1, direction=same, one up + one down at the latest
        point: the more severe side wins, independent of ordering."""
        orch = orchestrator(min_detectors=1, direction="same")
        a = record(T0, "a", "up", severity=2.0)
        b = record(T0, "b", "down", severity=5.0)
        for order in ([a, b], [b, a]):
            should, data = orch.should_alert(order)
            assert should is True
            assert data.direction == "down"
