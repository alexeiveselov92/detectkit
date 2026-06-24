"""Unit tests for detectkit.reporting (payload builder + HTML renderer).

The fake manager deliberately omits ``get_recent_detections`` — so these tests
also prove the alert replay is pure (no DB read) for the recovery path.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from detectkit.config.metric_config import AlertConfig, MetricConfig
from detectkit.reporting import build_report_payload, render_report_html, resolve_window
from detectkit.utils.json_utils import json_dumps_sorted

INTERVAL = 3600
BASE = datetime(2026, 1, 1, 0, 0, 0)
N = 12
ANOMALY_IDX = {6, 7, 8}  # a 3-point cluster -> fires a consecutive=3 alert
DET_ID = "det00000000000001"


def _timestamps() -> np.ndarray:
    return np.array(
        [np.datetime64(BASE, "ms") + np.timedelta64(i * INTERVAL, "s") for i in range(N)]
    )


def _values() -> np.ndarray:
    v = np.full(N, 100.0)
    for i in ANOMALY_IDX:
        v[i] = 140.0
    return v


def _detection_rows() -> list[dict]:
    rows = []
    for i in range(N):
        is_anom = i in ANOMALY_IDX
        meta = {"severity": 6.0, "direction": "above"} if is_anom else {}
        rows.append(
            {
                "timestamp": BASE + timedelta(seconds=i * INTERVAL),
                "detector_id": DET_ID,
                "detector_name": "MADDetector",
                "is_anomaly": is_anom,
                "confidence_lower": 90.0,
                "confidence_upper": 110.0,
                "value": float(_values()[i]),
                "processed_value": float(_values()[i]),
                "detector_params": json_dumps_sorted({"threshold": 3.0, "window_size": 5}),
                "detection_metadata": json_dumps_sorted(meta),
            }
        )
    return rows


class FakeInternal:
    """Minimal in-memory stand-in — no get_recent_detections on purpose."""

    def __init__(self) -> None:
        self._ts = _timestamps()
        self._val = _values()
        self._rows = _detection_rows()

    def get_last_datapoint_timestamp(self, name):
        return BASE + timedelta(seconds=(N - 1) * INTERVAL)

    def get_first_datapoint_timestamp(self, name):
        return BASE

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        return {
            "timestamp": self._ts,
            "value": self._val,
            "seasonality_data": np.array(["{}"] * N, dtype=object),
            "seasonality_columns": [],
        }

    def load_detections(self, name, detector_id=None, from_timestamp=None, to_timestamp=None):
        return list(self._rows)


def _metric(alerting: list[AlertConfig] | None = None) -> MetricConfig:
    return MetricConfig(
        name="orders_per_min",
        interval="1h",
        query="SELECT 1",
        description="orders per minute",
        alerting=alerting,
    )


def _alerting() -> list[AlertConfig]:
    return [
        AlertConfig(
            channels=["slack"],
            min_detectors=1,
            direction="any",
            consecutive_anomalies=3,
            notify_on_recovery=True,
        )
    ]


def test_payload_shape_and_counts():
    payload = build_report_payload(
        metric_config=_metric(_alerting()),
        internal=FakeInternal(),
        project_name="acme",
    )
    assert payload["metric"] == "orders_per_min"
    assert payload["project"] == "acme"
    assert payload["interval_seconds"] == INTERVAL
    assert len(payload["points"]) == N
    # one detector, three flagged points
    assert len(payload["detectors"]) == 1
    det = payload["detectors"][0]
    assert det["id"] == DET_ID
    assert det["name"] == "MADDetector"
    assert det["anomaly_count"] == len(ANOMALY_IDX)
    assert det["params"] == {"threshold": 3.0, "window_size": 5}
    # warm-up onset: min_samples (default 30) exceeds the 12-point window -> the
    # whole window is still warming up, so there's no "full power" zone to mark.
    assert "effective_start" in det
    assert det["effective_start"] is None
    # distinct anomalous timestamps
    assert payload["summary"]["anomalies"] == len(ANOMALY_IDX)


def test_alert_replayed_from_cluster():
    payload = build_report_payload(
        metric_config=_metric(_alerting()),
        internal=FakeInternal(),
    )
    kinds = [a["kind"] for a in payload["alerts"]]
    assert "anomaly" in kinds, payload["alerts"]
    assert payload["summary"]["alerts"] >= 1
    # notify_on_recovery -> a recovery once the cluster clears
    assert "recovery" in kinds
    # alert rows carry the rule that fired
    anomaly = next(a for a in payload["alerts"] if a["kind"] == "anomaly")
    assert "consecutive=3" in anomaly["rule"]
    assert anomaly["consecutive"] >= 3


def test_no_alerting_still_renders_bands():
    payload = build_report_payload(metric_config=_metric(None), internal=FakeInternal())
    assert payload["alerts"] == []
    assert payload["summary"]["alerts"] == 0
    assert payload["detectors"][0]["anomaly_count"] == len(ANOMALY_IDX)


def test_render_html_is_self_contained():
    payload = build_report_payload(metric_config=_metric(_alerting()), internal=FakeInternal())
    html = render_report_html(payload)
    assert "__PAYLOAD__" not in html
    assert "__REPORT_JS__" not in html
    assert "__METRIC__" not in html
    assert "orders_per_min" in html
    assert "__DTK_REPORT__" in html  # the bundled renderer global
    assert "<canvas" in html or "dtk-report" in html


SEAS_N = 24
SEAS_DET_ID = "det00000000000002"


class SeasonalInternal(FakeInternal):
    """Series whose seasonality_data alternates two keys -> cardinality 2.

    Carries a detector configured with ``seasonality_components`` and small
    sample gates so the per-group warm-up lands *inside* the window, yielding a
    concrete (non-null) effective_start.
    """

    def __init__(self) -> None:
        self._ts = np.array(
            [np.datetime64(BASE, "ms") + np.timedelta64(i * INTERVAL, "s") for i in range(SEAS_N)]
        )
        self._val = np.full(SEAS_N, 100.0)
        # two distinct hour buckets -> cardinality 2
        self._seas = np.array(
            [json_dumps_sorted({"hour_bucket": i % 2}) for i in range(SEAS_N)], dtype=object
        )
        params = json_dumps_sorted(
            {
                "window_size": 50,
                "min_samples": 2,
                "min_samples_per_group": 2,
                "seasonality_components": [["hour_bucket"]],
            }
        )
        self._rows = [
            {
                "timestamp": BASE + timedelta(seconds=i * INTERVAL),
                "detector_id": SEAS_DET_ID,
                "detector_name": "MADDetector",
                "is_anomaly": False,
                "confidence_lower": 90.0,
                "confidence_upper": 110.0,
                "value": 100.0,
                "processed_value": 100.0,
                "detector_params": params,
                "detection_metadata": json_dumps_sorted({}),
            }
            for i in range(SEAS_N)
        ]

    def get_last_datapoint_timestamp(self, name):
        return BASE + timedelta(seconds=(SEAS_N - 1) * INTERVAL)

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        return {
            "timestamp": self._ts,
            "value": self._val,
            "seasonality_data": self._seas,
            "seasonality_columns": ["hour_bucket"],
        }


def test_seasonality_detector_has_effective_start():
    payload = build_report_payload(metric_config=_metric(None), internal=SeasonalInternal())
    det = payload["detectors"][0]
    eff = det["effective_start"]
    # group warm-up = min_samples_per_group(2) * cardinality(2) = 4 points in,
    # which fits the 50-point window -> a concrete onset past the period start.
    assert eff is not None
    assert eff > payload["period"]["start"]
    # exactly the timestamp of the grid point at index 4
    expected = payload["points"][4]["t"]
    assert eff == expected


def test_resolve_window_defaults_to_last_datapoint():
    start, end = resolve_window(FakeInternal(), "orders_per_min", INTERVAL, None, None)
    assert end == BASE + timedelta(seconds=(N - 1) * INTERVAL)
    assert start == BASE  # first datapoint, since the series is shorter than the lookback


def test_empty_when_no_datapoints():
    class Empty(FakeInternal):
        def get_last_datapoint_timestamp(self, name):
            return None

    payload = build_report_payload(metric_config=_metric(_alerting()), internal=Empty())
    assert payload["points"] == []
    assert payload["detectors"] == []
    assert payload["summary"] == {"anomalies": 0, "alerts": 0, "recoveries": 0, "no_data": 0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
