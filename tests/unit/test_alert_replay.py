"""Tests for the pure alert-event replay (``AlertOrchestrator.replay``).

Replay reconstructs the alert/recovery/no-data events the orchestrator *would
have* produced over a historical period from already-persisted detections — no
channel dispatch, no DB state writes, no wall-clock. These tests pin:

(a) a clean grid-adjacent anomalous run fires exactly one "anomaly" event at the
    right grid point,
(b) a gap in the grid breaks the streak (no fire),
(c) cooldown suppresses a second alert within the window,
(d) recovery fires once after the run clears when ``notify_on_recovery``,
(e) a no-data point fires a "no_data" event when ``no_data_alert`` and the
    grid value is ``None``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

from detectkit.alerting.orchestrator import (
    AlertConditions,
    AlertOrchestrator,
    DetectionRecord,
    ReplayedEvent,
)
from detectkit.core.interval import Interval

START = datetime(2024, 1, 1, 12, 0, 0)
STEP = np.timedelta64(10, "m")
INTERVAL_SECONDS = 600


def _alert_config(
    *,
    no_data_alert: bool = False,
    notify_on_recovery: bool = False,
    alert_cooldown=None,
    cooldown_reset_on_recovery: bool = True,
) -> SimpleNamespace:
    """Minimal alert_config stand-in (the orchestrator only reads attributes)."""
    return SimpleNamespace(
        no_data_alert=no_data_alert,
        notify_on_recovery=notify_on_recovery,
        alert_cooldown=alert_cooldown,
        cooldown_reset_on_recovery=cooldown_reset_on_recovery,
    )


def _orchestrator(
    *,
    min_detectors: int = 1,
    direction: str = "up",
    consecutive: int = 3,
    alert_config: SimpleNamespace | None = None,
) -> AlertOrchestrator:
    return AlertOrchestrator(
        metric_name="m",
        alert_config_id="cfg",
        interval=Interval("10min"),
        conditions=AlertConditions(
            min_detectors=min_detectors,
            direction=direction,
            consecutive_anomalies=consecutive,
        ),
        alert_config=alert_config,
    )


def _ts(i: int) -> np.datetime64:
    return np.datetime64(START, "ms") + STEP * i


def _record(i: int, *, direction: str = "up", is_anomaly: bool = True) -> DetectionRecord:
    return DetectionRecord(
        timestamp=_ts(i),
        detector_name="mad",
        detector_id="id_mad",
        detector_params="{}",
        value=100.0,
        is_anomaly=is_anomaly,
        confidence_lower=80.0,
        confidence_upper=120.0,
        direction=direction if is_anomaly else "none",
        severity=2.0 if is_anomaly else 0.0,
        detection_metadata={},
    )


def _grid_end(n_points: int) -> datetime:
    """End datetime covering ``n_points`` grid boundaries from START."""
    return START + timedelta(seconds=INTERVAL_SECONDS * (n_points - 1))


# --------------------------------------------------------------------------- #
# (a) clean run fires exactly one anomaly event at the right grid point
# --------------------------------------------------------------------------- #
def test_clean_run_fires_one_anomaly_at_third_point():
    orch = _orchestrator(consecutive=3, alert_config=_alert_config())
    # Points 0,1,2 anomalous and grid-adjacent.
    detections = [_record(0), _record(1), _record(2)]
    value_at = {_ts(i): 100.0 for i in range(3)}

    events = orch.replay(detections, value_at, START, _grid_end(3))

    anomalies = [e for e in events if e.kind == "anomaly"]
    assert len(anomalies) == 1
    # Quorum first satisfied (3 consecutive) at grid point index 2.
    assert anomalies[0].timestamp == _ts(2)
    ad = anomalies[0].alert_data
    assert ad.direction == "up"
    assert ad.consecutive_count == 3
    # onset = latest_ts - step*(streak-1) == point 0.
    assert ad.onset_timestamp == _ts(0)
    assert isinstance(anomalies[0], ReplayedEvent)


def test_no_fire_before_consecutive_threshold():
    """Only 2 anomalous points, threshold 3 → no anomaly event."""
    orch = _orchestrator(consecutive=3, alert_config=_alert_config())
    detections = [_record(0), _record(1)]
    value_at = {_ts(i): 100.0 for i in range(2)}

    events = orch.replay(detections, value_at, START, _grid_end(2))
    assert [e for e in events if e.kind == "anomaly"] == []


# --------------------------------------------------------------------------- #
# (b) a grid gap breaks the streak (no fire)
# --------------------------------------------------------------------------- #
def test_grid_gap_breaks_streak():
    orch = _orchestrator(consecutive=3, alert_config=_alert_config())
    # Anomalous at 0,1 then a gap (no point 2) then anomalous at 3,4 — never
    # 3 *adjacent* anomalies, so no alert.
    detections = [_record(0), _record(1), _record(3), _record(4)]
    value_at = {_ts(i): 100.0 for i in (0, 1, 3, 4)}

    events = orch.replay(detections, value_at, START, _grid_end(5))
    assert [e for e in events if e.kind == "anomaly"] == []


# --------------------------------------------------------------------------- #
# (c) cooldown suppresses a second alert within the window
# --------------------------------------------------------------------------- #
def test_cooldown_suppresses_second_alert():
    # consecutive=1 so every anomalous point would otherwise fire.
    orch = _orchestrator(
        consecutive=1,
        alert_config=_alert_config(alert_cooldown="30min", cooldown_reset_on_recovery=False),
    )
    # Six adjacent anomalies; without cooldown every point fires.
    detections = [_record(i) for i in range(6)]
    value_at = {_ts(i): 100.0 for i in range(6)}

    events = orch.replay(detections, value_at, START, _grid_end(6))
    anomalies = [e for e in events if e.kind == "anomaly"]

    # First fires at point 0; 30min == 3 intervals cooldown, so the next
    # eligible point is index 3 (elapsed 30min is NOT < 30min).
    assert [e.timestamp for e in anomalies] == [_ts(0), _ts(3)]


def test_no_cooldown_fires_every_point():
    orch = _orchestrator(consecutive=1, alert_config=_alert_config())
    detections = [_record(i) for i in range(4)]
    value_at = {_ts(i): 100.0 for i in range(4)}

    events = orch.replay(detections, value_at, START, _grid_end(4))
    anomalies = [e for e in events if e.kind == "anomaly"]
    assert [e.timestamp for e in anomalies] == [_ts(i) for i in range(4)]


# --------------------------------------------------------------------------- #
# (d) recovery fires once after the run clears
# --------------------------------------------------------------------------- #
def test_recovery_fires_once_after_clear():
    orch = _orchestrator(
        consecutive=3,
        direction="up",
        alert_config=_alert_config(notify_on_recovery=True),
    )
    # Anomalous 0,1,2 (fires at 2), then clean 3,4,5.
    detections = [
        _record(0),
        _record(1),
        _record(2),
        _record(3, is_anomaly=False),
        _record(4, is_anomaly=False),
        _record(5, is_anomaly=False),
    ]
    value_at = {_ts(i): 100.0 for i in range(6)}

    events = orch.replay(detections, value_at, START, _grid_end(6))

    anomalies = [e for e in events if e.kind == "anomaly"]
    recoveries = [e for e in events if e.kind == "recovery"]
    assert len(anomalies) == 1 and anomalies[0].timestamp == _ts(2)
    # Recovery fires once, at the first clean point after the alert (point 3).
    assert len(recoveries) == 1
    assert recoveries[0].timestamp == _ts(3)
    assert recoveries[0].alert_data.is_recovery is True


def test_no_recovery_when_not_configured():
    orch = _orchestrator(consecutive=3, alert_config=_alert_config(notify_on_recovery=False))
    detections = [
        _record(0),
        _record(1),
        _record(2),
        _record(3, is_anomaly=False),
    ]
    value_at = {_ts(i): 100.0 for i in range(4)}

    events = orch.replay(detections, value_at, START, _grid_end(4))
    assert [e for e in events if e.kind == "recovery"] == []


# --------------------------------------------------------------------------- #
# (e) no-data fires when configured and the grid value is None
# --------------------------------------------------------------------------- #
def test_no_data_fires_on_missing_value():
    orch = _orchestrator(consecutive=3, alert_config=_alert_config(no_data_alert=True))
    # No detections at all; the grid value at point 1 is missing.
    detections: list[DetectionRecord] = []
    value_at = {_ts(0): 100.0, _ts(1): None, _ts(2): 100.0}

    events = orch.replay(detections, value_at, START, _grid_end(3))
    no_data = [e for e in events if e.kind == "no_data"]
    assert len(no_data) == 1
    assert no_data[0].timestamp == _ts(1)
    assert no_data[0].alert_data.is_no_data is True


def test_no_data_silent_when_disabled():
    orch = _orchestrator(consecutive=3, alert_config=_alert_config(no_data_alert=False))
    detections: list[DetectionRecord] = []
    value_at = {_ts(0): 100.0, _ts(1): None, _ts(2): 100.0}

    events = orch.replay(detections, value_at, START, _grid_end(3))
    assert events == []
