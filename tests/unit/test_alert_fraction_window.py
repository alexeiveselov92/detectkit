"""Tests for the fraction-based alert window (anomaly_window + min_anomaly_share).

Pins the rule's semantics:
- fires when the share of quorum-meeting points over the trailing window
  reaches the threshold AND the latest point itself meets the quorum;
- OR-ed with the consecutive rule (consecutive wins the message when both fire);
- grid slots with no detections count in the denominator only (missing data
  makes the rule harder to fire, not easier);
- "same" locks the direction from the latest quorum across the window;
- recovery gains hysteresis: share must drop below half the threshold;
- existing consecutive-only configs keep their alert_config_id and their
  message bytes.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel, format_rule_display
from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.config.metric_config import AlertConfig
from detectkit.core.interval import Interval
from detectkit.orchestration.task_manager._types import make_alert_config_id

T0 = np.datetime64("2024-01-01T12:00:00", "ms")
STEP = np.timedelta64(10, "m")


def record(ts, detector="a", direction="up", is_anomaly=True, severity=2.0):
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


def orchestrator(
    min_detectors=1,
    direction="any",
    consecutive=3,
    window_points=None,
    min_anomaly_share=None,
    alert_config=None,
):
    return AlertOrchestrator(
        metric_name="m",
        alert_config_id="cfg",
        interval=Interval("10min"),
        conditions=AlertConditions(
            min_detectors=min_detectors,
            direction=direction,
            consecutive_anomalies=consecutive,
            window_points=window_points,
            min_anomaly_share=min_anomaly_share,
        ),
        alert_config=alert_config,
    )


# ── config validation ─────────────────────────────────────────────────────────


class TestAlertConfigValidation:
    def test_pair_required(self):
        with pytest.raises(ValueError, match="set together"):
            AlertConfig(anomaly_window="30min")
        with pytest.raises(ValueError, match="set together"):
            AlertConfig(min_anomaly_share=0.3)

    def test_share_range(self):
        with pytest.raises(ValueError, match="fraction"):
            AlertConfig(anomaly_window="30min", min_anomaly_share=0.0)
        with pytest.raises(ValueError, match="fraction"):
            AlertConfig(anomaly_window="30min", min_anomaly_share=1.5)
        cfg = AlertConfig(anomaly_window="30min", min_anomaly_share=1.0)
        assert cfg.min_anomaly_share == 1.0

    def test_window_must_parse(self):
        with pytest.raises(ValueError, match="anomaly_window"):
            AlertConfig(anomaly_window="not-a-window", min_anomaly_share=0.3)
        assert AlertConfig(anomaly_window=1800, min_anomaly_share=0.3).anomaly_window == 1800

    def test_defaults_off(self):
        cfg = AlertConfig()
        assert cfg.anomaly_window is None
        assert cfg.min_anomaly_share is None


class TestConditionsResolution:
    def test_window_resolves_to_grid_points(self):
        cfg = AlertConfig(anomaly_window="30min", min_anomaly_share=0.3)
        cond = AlertConditions.from_alert_config(cfg, interval_seconds=600)
        assert cond.window_points == 3
        assert cond.min_anomaly_share == 0.3
        assert cond.lookback_points == 3  # max(consecutive=3, window=3)

    def test_window_wider_than_consecutive_drives_lookback(self):
        cfg = AlertConfig(anomaly_window="2h", min_anomaly_share=0.3, consecutive_anomalies=3)
        cond = AlertConditions.from_alert_config(cfg, interval_seconds=600)
        assert cond.window_points == 12
        assert cond.lookback_points == 12

    def test_unset_keeps_legacy_shape(self):
        cond = AlertConditions.from_alert_config(AlertConfig(), interval_seconds=600)
        assert cond.window_points is None
        assert cond.min_anomaly_share is None
        assert cond.lookback_points == cond.consecutive_anomalies


class TestAlertConfigId:
    def test_legacy_config_id_unchanged_by_new_fields(self):
        """A config without the fraction rule hashes exactly as before —
        including duck-typed stubs that predate the new attributes."""
        pydantic_cfg = AlertConfig(channels=["slack"], consecutive_anomalies=3)
        legacy_stub = SimpleNamespace(
            channels=["slack"],
            min_detectors=1,
            direction="same",
            consecutive_anomalies=3,
            alert_cooldown=None,
            cooldown_reset_on_recovery=True,
        )
        assert make_alert_config_id(pydantic_cfg) == make_alert_config_id(legacy_stub)

    def test_setting_fraction_rule_changes_id(self):
        base = AlertConfig(channels=["slack"])
        with_rule = AlertConfig(channels=["slack"], anomaly_window="30min", min_anomaly_share=0.3)
        assert make_alert_config_id(base) != make_alert_config_id(with_rule)


# ── firing semantics ──────────────────────────────────────────────────────────


class TestShareFire:
    def test_flapping_incident_fires_share_not_consecutive(self):
        """Alternating anomalies break every consecutive chain but reach the
        share threshold — the exact false-negative the rule exists to fix."""
        orch = orchestrator(consecutive=3, window_points=10, min_anomaly_share=0.5)
        detections = []
        for k in range(10):
            ts = T0 - STEP * k
            detections.append(record(ts, is_anomaly=(k % 2 == 0)))
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.fired_by_share is True
        assert data.window_matched == 5
        assert data.window_points == 10
        assert data.consecutive_count == 5
        # onset = the oldest matched slot the window can see
        assert data.onset_timestamp == T0 - STEP * 8

    def test_latest_point_must_meet_quorum(self):
        """A stale window (share met, latest point clean) never fires."""
        orch = orchestrator(consecutive=3, window_points=10, min_anomaly_share=0.4)
        detections = [record(T0, is_anomaly=False)]
        for k in range(1, 6):
            detections.append(record(T0 - STEP * k))
        should, _ = orch.should_alert(detections)
        assert should is False

    def test_missing_slots_count_in_denominator(self):
        """4 matched slots out of a 10-slot window (6 slots absent): 40%."""
        detections = [record(T0 - STEP * k) for k in range(4)]
        strict = orchestrator(consecutive=99, window_points=10, min_anomaly_share=0.5)
        should, _ = strict.should_alert(detections)
        assert should is False
        lenient = orchestrator(consecutive=99, window_points=10, min_anomaly_share=0.4)
        should, data = lenient.should_alert(detections)
        assert should is True
        assert data.window_matched == 4

    def test_consecutive_rule_wins_the_message_when_both_fire(self):
        orch = orchestrator(consecutive=2, window_points=10, min_anomaly_share=0.1)
        detections = [record(T0), record(T0 - STEP)]
        should, data = orch.should_alert(detections)
        assert should is True
        assert data.fired_by_share is False
        # configured rule still rides on the payload for the rule chip
        assert data.window_points == 10
        assert data.min_anomaly_share == 0.1

    def test_same_direction_locked_across_window(self):
        """same: down-anomalies in the window don't count toward an up quorum."""
        orch = orchestrator(
            direction="same", consecutive=99, window_points=6, min_anomaly_share=0.5
        )
        detections = [record(T0, direction="up")]
        for k in range(1, 6):
            detections.append(record(T0 - STEP * k, direction="down"))
        should, _ = orch.should_alert(detections)
        assert should is False  # only 1/6 up-matched

    def test_no_rule_configured_behaves_as_before(self):
        orch = orchestrator(consecutive=3)
        detections = [record(T0 - STEP * k, is_anomaly=(k % 2 == 0)) for k in range(10)]
        should, _ = orch.should_alert(detections)
        assert should is False


# ── replay parity + recovery hysteresis ───────────────────────────────────────


def _alert_config_stub(**over):
    base = {
        "no_data_alert": False,
        "notify_on_recovery": True,
        "alert_cooldown": None,
        "cooldown_reset_on_recovery": True,
    }
    base.update(over)
    return SimpleNamespace(**base)


class TestReplay:
    def test_replay_emits_share_fired_event(self):
        orch = orchestrator(
            consecutive=99,
            window_points=6,
            min_anomaly_share=0.5,
            alert_config=_alert_config_stub(notify_on_recovery=False),
        )
        detections = []
        for k in range(6):
            ts = T0 - STEP * k
            detections.append(record(ts, is_anomaly=(k % 2 == 0)))
        start = (T0 - STEP * 6).astype("datetime64[ms]").astype("datetime64[s]").item()
        end = T0.astype("datetime64[ms]").astype("datetime64[s]").item()
        value_at = {T0 - STEP * k: 100.0 for k in range(8)}
        events = orch.replay(detections, value_at, start, end)
        anomalies = [e for e in events if e.kind == "anomaly"]
        assert anomalies
        assert anomalies[-1].alert_data.fired_by_share is True

    def test_recovery_hysteresis_holds_until_share_halves(self):
        """After a share-fired alert, a clean latest point alone does not
        recover while the window share is still >= threshold/2."""
        orch = orchestrator(
            consecutive=99,
            window_points=4,
            min_anomaly_share=0.5,
            alert_config=_alert_config_stub(),
        )
        # k: 9..0 chronological; anomalies at k=4..7 (a 4-point burst), then
        # clean tail k=3..0. Window=4: at the burst end share=1.0 (fires);
        # one clean point later share=0.75, then 0.5, 0.25, 0.0.
        detections = []
        for k in range(10):
            ts = T0 - STEP * k
            detections.append(record(ts, is_anomaly=(4 <= k <= 7)))
        start = (T0 - STEP * 9).astype("datetime64[ms]").astype("datetime64[s]").item()
        end = T0.astype("datetime64[ms]").astype("datetime64[s]").item()
        value_at = {T0 - STEP * k: 100.0 for k in range(12)}
        events = orch.replay(detections, value_at, start, end)
        kinds = [(e.kind, e.timestamp) for e in events]
        anomaly_ts = [t for k, t in kinds if k == "anomaly"]
        recovery_ts = [t for k, t in kinds if k == "recovery"]
        assert anomaly_ts and recovery_ts
        # recovery only once the share fell below 0.25 (=0.5/2): the first two
        # clean grid points (share 0.75, 0.5) must NOT recover; share 0.25 is
        # still >= threshold/2, so recovery lands at share 0.0 (k=0).
        assert recovery_ts[0] == T0

    def test_recovery_without_share_rule_unchanged(self):
        """Consecutive-only config recovers on the first clean point."""
        orch = orchestrator(
            consecutive=2,
            alert_config=_alert_config_stub(),
        )
        detections = []
        for k in range(10):
            ts = T0 - STEP * k
            detections.append(record(ts, is_anomaly=(4 <= k <= 7)))
        start = (T0 - STEP * 9).astype("datetime64[ms]").astype("datetime64[s]").item()
        end = T0.astype("datetime64[ms]").astype("datetime64[s]").item()
        value_at = {T0 - STEP * k: 100.0 for k in range(12)}
        events = orch.replay(detections, value_at, start, end)
        recovery_ts = [e.timestamp for e in events if e.kind == "recovery"]
        assert recovery_ts and recovery_ts[0] == T0 - STEP * 3


class TestLiveRecoveryHysteresis:
    """The live path computes the hysteresis window over an UNFILTERED fetch.

    ``_check_recovery_since_last_alert``'s primary fetch is
    ``created_after``-filtered (only rows persisted after the alert) — right
    for the freshness check, but the window walk would see almost every slot
    empty and recover immediately. Pins the dedicated unfiltered fetch.
    """

    @staticmethod
    def _row(ts, is_anomaly):
        meta = '{"direction": "above", "severity": 2.0}' if is_anomaly else "{}"
        return {
            "timestamp": ts.astype("datetime64[ms]").astype("datetime64[s]").item(),
            "detector_ids": ["id_a"],
            "detector_names": ["a"],
            "detector_params_list": ["{}"],
            "value": 100.0,
            "is_anomaly_flags": [is_anomaly],
            "confidence_lowers": [80.0],
            "confidence_uppers": [120.0],
            "detection_metadata_list": [meta],
        }

    class _FakeInternal:
        def __init__(self, rows_all, rows_fresh, last_alert):
            self.rows_all = rows_all
            self.rows_fresh = rows_fresh
            self.last_alert = last_alert

        def get_last_alert_timestamp(self, metric_name, alert_config_id):
            return self.last_alert

        def get_last_recovery_timestamp(self, metric_name, alert_config_id):
            return None

        def get_recent_detections(self, metric_name, last_point, num_points, created_after=None):
            return self.rows_fresh if created_after is not None else self.rows_all

    def _orchestrator(self, rows_all, rows_fresh):
        from datetime import datetime

        internal = self._FakeInternal(rows_all, rows_fresh, datetime(2024, 1, 1, 11, 0, 0))
        return AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            conditions=AlertConditions(
                min_detectors=1,
                direction="any",
                consecutive_anomalies=99,
                window_points=4,
                min_anomaly_share=0.5,
            ),
            internal=internal,
            alert_config=_alert_config_stub(),
        )

    def test_no_recovery_while_unfiltered_window_share_elevated(self):
        # Fresh (created_after) view: only the latest, clean point. Full
        # stored history: 3 of the previous 4 slots anomalous (share 0.75).
        rows_fresh = [self._row(T0, False)]
        rows_all = [self._row(T0, False)] + [self._row(T0 - STEP * k, True) for k in (1, 2, 3)]
        orch = self._orchestrator(rows_all, rows_fresh)
        from detectkit.alerting.orchestrator._types import hydrate_detection_records

        should, _ = orch.should_send_recovery(hydrate_detection_records(rows_fresh))
        assert should is False

    def test_recovery_once_window_clears(self):
        rows_fresh = [self._row(T0, False)]
        rows_all = [self._row(T0 - STEP * k, False) for k in range(4)] + [
            self._row(T0 - STEP * k, True) for k in (5, 6, 7)
        ]
        orch = self._orchestrator(rows_all, rows_fresh)
        from detectkit.alerting.orchestrator._types import hydrate_detection_records

        should, data = orch.should_send_recovery(hydrate_detection_records(rows_fresh))
        assert should is True
        # the recovery payload echoes the configured fraction rule
        assert data.window_points == 4
        assert data.min_anomaly_share == 0.5


class TestWindowSpansTwoIntervals:
    def test_metric_config_rejects_one_point_window(self):
        from detectkit.config.metric_config import MetricConfig

        with pytest.raises(ValueError, match="at least 2"):
            MetricConfig(
                name="m",
                interval="10min",
                query="SELECT 1",
                alerting=[{"anomaly_window": "10min", "min_anomaly_share": 0.5}],
            )
        cfg = MetricConfig(
            name="m",
            interval="10min",
            query="SELECT 1",
            alerting=[{"anomaly_window": "20min", "min_anomaly_share": 0.5}],
        )
        assert cfg.alerting[0].anomaly_window == "20min"


# ── message rendering ─────────────────────────────────────────────────────────


class _Channel(BaseAlertChannel):
    def send(self, alert_data, template=None):  # pragma: no cover - not used
        return True


def _alert_data(**over):
    base = {
        "metric_name": "m",
        "timestamp": T0,
        "timezone": "",
        "value": 100.0,
        "confidence_lower": 80.0,
        "confidence_upper": 95.0,
        "detector_name": "MADDetector",
        "detector_params": "{}",
        "direction": "up",
        "severity": 2.0,
        "detection_metadata": {},
        "consecutive_count": 3,
        "min_detectors": 1,
        "direction_policy": "same",
        "consecutive_required": 3,
        "interval_seconds": 600,
        "onset_timestamp": T0 - STEP * 2,
    }
    base.update(over)
    return AlertData(**base)


class TestRuleDisplay:
    def test_legacy_chip_byte_identical(self):
        ctx = _Channel().build_context(_alert_data())
        assert ctx["rule_display"] == "min_detectors=1 · direction=same · consecutive=3"
        assert "Anomalous for" in ctx["anomaly_lead"]

    def test_configured_share_names_both_rules(self):
        ctx = _Channel().build_context(_alert_data(window_points=3, min_anomaly_share=0.3))
        assert ctx["rule_display"] == (
            "min_detectors=1 · direction=same · consecutive=3 (or share>=30% over 30m)"
        )

    def test_share_fired_lead_and_chip(self):
        ctx = _Channel().build_context(
            _alert_data(
                window_points=6,
                window_matched=3,
                min_anomaly_share=0.5,
                fired_by_share=True,
                consecutive_count=3,
            )
        )
        assert ctx["rule_display"] == "min_detectors=1 · direction=same · share>=50% over 1h"
        assert "3 of the last 6 10min intervals were anomalous (50%)" in ctx["anomaly_lead"]
        assert ctx["fired_display"] == ""
        assert ctx["streak_display"] == "3/6"
        # the whole-window span, not matched × interval
        assert ctx["duration_display"] == "1h"

    def test_format_rule_display_fallback_without_interval(self):
        chip = format_rule_display(
            min_detectors=1,
            direction_policy="any",
            consecutive_required=3,
            window_points=5,
            min_anomaly_share=0.25,
            fired_by_share=True,
            interval_seconds=None,
        )
        assert chip == "min_detectors=1 · direction=any · share>=25% over 5 points"

    def test_recovery_chip_names_the_configured_share_rule(self):
        """Fire and recovery must render one consistent rule chip."""
        orch = orchestrator(consecutive=3, window_points=6, min_anomaly_share=0.5)
        detections = [record(T0 - STEP * k, is_anomaly=(k >= 1)) for k in range(4)]
        data = orch._build_recovery_data(detections, incident_records=detections)
        assert data is not None
        assert data.window_points == 6
        assert data.min_anomaly_share == 0.5
        ctx = _Channel().build_context(data)
        assert "(or share>=50% over 1h)" in ctx["rule_display"]

    def test_default_template_renders_share_alert(self):
        channel = _Channel()
        msg = channel.format_message(
            _alert_data(
                window_points=6,
                window_matched=3,
                min_anomaly_share=0.5,
                fired_by_share=True,
            )
        )
        assert "Rule: min_detectors=1 · direction=same · share>=50% over 1h" in msg
        assert "3 of the last 6" in msg
