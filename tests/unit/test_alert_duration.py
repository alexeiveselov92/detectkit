"""Tests for the incident-timing message additions.

Covers the "how long has this been going on" story:
- ``format_duration`` rendering,
- ``build_context`` duration / onset / lead values (and graceful fallback),
- the unified ``description → Rule → Value/Expected`` ordering on the webhook
  channel plus the ``Started``/``Latest``/``Cleared`` fields,
- the orchestrator resolving the *true* streak length + onset at fire time
  (and the symmetric incident span on recovery).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.core.interval import Interval
from detectkit.utils.datetime_utils import format_duration


# --------------------------------------------------------------------------- #
# format_duration
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "seconds,expected",
    [
        (30, "30s"),
        (60, "1m"),
        (600, "10m"),
        (9000, "2h 30m"),
        (3600, "1h"),
        (86400, "1d"),
        (90000, "1d 1h"),
        (0, "0m"),
        (-5, "0m"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


# --------------------------------------------------------------------------- #
# build_context — duration / onset / leads
# --------------------------------------------------------------------------- #
def _anomaly_alert(**overrides) -> AlertData:
    base = {
        "metric_name": "api_error_rate",
        "timestamp": np.datetime64("2026-06-19T12:36:00", "ms"),
        "timezone": "UTC",
        "value": 4.2,
        "confidence_lower": None,
        "confidence_upper": 1.1,
        "detector_name": "mad",
        "detector_params": '{"threshold": 3.0}',
        "direction": "up",
        "severity": 4.83,
        "detection_metadata": {},
        "consecutive_count": 5,
        "min_detectors": 1,
        "direction_policy": "same",
        "consecutive_required": 3,
        "detector_count": 1,
        "interval_seconds": 600,
        "onset_timestamp": np.datetime64("2026-06-19T11:56:00", "ms"),
    }
    base.update(overrides)
    return AlertData(**base)


def test_build_context_duration_fields():
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    ctx = ch.build_context(_anomaly_alert())

    assert ctx["interval_display"] == "10min"
    # 5 intervals * 10min = 50 minutes
    assert ctx["duration_display"] == "50m"
    assert ctx["streak_display"] == "5"
    assert "11:56:00" in ctx["started_display"]
    assert ctx["anomaly_lead"] == "Anomalous for 50m — 5 consecutive 10min intervals."
    assert "Incident lasted 50m (5 consecutive 10min intervals)." in ctx["recovery_lead"]
    # window line carries onset → latest
    assert ctx["window_line"].startswith("Started: ")
    assert "Latest: 2026-06-19 12:36:00" in ctx["window_line"]


def test_build_context_singular_interval():
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    ctx = ch.build_context(_anomaly_alert(consecutive_count=1))
    assert ctx["anomaly_lead"] == "Anomalous for 10m — 1 consecutive 10min interval."


def test_build_context_capped_streak():
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    ctx = ch.build_context(_anomaly_alert(consecutive_count=1000, streak_capped=True))
    assert ctx["duration_display"].startswith("over ")
    assert ctx["streak_display"] == "1000+"
    assert "or earlier" in ctx["started_display"]
    assert ctx["anomaly_lead"].startswith("Anomalous for over ")


def test_build_context_fallback_without_interval():
    """Direct-API callers that don't wire timing still render the legacy lead."""
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    ctx = ch.build_context(_anomaly_alert(interval_seconds=None, onset_timestamp=None))
    assert ctx["duration_display"] == ""
    assert ctx["started_display"] == ""
    assert ctx["anomaly_lead"] == "Latest 5/3 consecutive points met the quorum."
    assert ctx["window_line"].startswith("Detected at: ")


# --------------------------------------------------------------------------- #
# Webhook layout — description → Rule → Value/Expected, Started/Latest fields
# --------------------------------------------------------------------------- #
def test_webhook_anomaly_layout():
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    payload = ch.build_payload(_anomaly_alert())
    att = payload["attachments"][0]

    # Lead leads with the description, the Rule chip sits right below it.
    lead = att["text"]
    assert lead.index("Anomalous for") < lead.index("Rule")

    titles = [f["title"] for f in att["fields"]]
    assert "Started" in titles
    assert "Latest" in titles
    assert "Quorum" in titles
    # Value/Expected precede the Started/Latest span.
    assert titles.index("Value") < titles.index("Started")


def test_webhook_recovery_layout():
    ch = WebhookChannel(webhook_url="https://example.com/hook")
    data = _anomaly_alert(
        is_recovery=True,
        value=1.0,
        direction="none",
        severity=0.0,
        detector_name="mad",
    )
    att = ch.build_payload(data)["attachments"][0]

    assert "Incident lasted" in att["text"]
    titles = [f["title"] for f in att["fields"]]
    assert "Started" in titles
    assert "Cleared" in titles


# --------------------------------------------------------------------------- #
# Orchestrator — resolve the true streak / onset at fire time
# --------------------------------------------------------------------------- #
def _raw_rows(timestamps: list[str], direction: str = "above") -> list[dict]:
    """Build get_recent_detections-shaped rows (newest first) for one detector."""
    rows = []
    for ts in timestamps:
        rows.append(
            {
                "timestamp": datetime.fromisoformat(ts),
                "detector_ids": ["abc123"],
                "detector_names": ["mad"],
                "detector_params_list": ['{"threshold": 3.0}'],
                "detection_metadata_list": [{"direction": direction, "severity": 2.0}],
                "is_anomaly_flags": [True],
                "confidence_lowers": [None],
                "confidence_uppers": [1.1],
                "value": 4.2,
            }
        )
    return rows


def _record(ts: str) -> DetectionRecord:
    return DetectionRecord(
        timestamp=np.datetime64(ts, "ms"),
        detector_name="mad",
        detector_id="abc123",
        detector_params='{"threshold": 3.0}',
        value=4.2,
        is_anomaly=True,
        confidence_lower=None,
        confidence_upper=1.1,
        direction="up",
        severity=2.0,
        detection_metadata={"direction": "above", "severity": 2.0},
    )


def test_should_alert_resolves_true_streak():
    internal = Mock()
    # The deep lookback sees a 5-point anomalous run, grid-adjacent at 10min.
    internal.get_recent_detections.return_value = _raw_rows(
        [
            "2024-01-01T12:20:00",
            "2024-01-01T12:10:00",
            "2024-01-01T12:00:00",
            "2024-01-01T11:50:00",
            "2024-01-01T11:40:00",
        ]
    )

    orch = AlertOrchestrator(
        metric_name="api_error_rate",
        alert_config_id="cfg",
        interval=Interval("10min"),
        conditions=AlertConditions(min_detectors=1, direction="up", consecutive_anomalies=3),
        internal=internal,
    )

    # The shallow alert window (what the alert step loads) is just the required 3.
    recent = [
        _record("2024-01-01T12:00:00"),
        _record("2024-01-01T12:10:00"),
        _record("2024-01-01T12:20:00"),
    ]
    should, data = orch.should_alert(recent)

    assert should is True
    assert data.consecutive_count == 5  # true streak, not capped at 3
    assert data.interval_seconds == 600
    assert data.onset_timestamp == np.datetime64("2024-01-01T11:40:00", "ms")
    assert data.streak_capped is False
