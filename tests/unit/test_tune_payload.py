"""Tests for the dtk tune payload builder + HTML shell."""

from datetime import datetime

import numpy as np

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.html import render_tune_html
from detectkit.tuning.payload import (
    _normalize_seasonality_components,
    _seed_detector,
    build_tune_payload,
)


class FakeInternal:
    """In-memory stand-in for InternalTablesManager (only what the builder calls)."""

    def __init__(self, n=120, seasonal=False):
        ts = (
            np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n) * np.timedelta64(1, "h")
        ).astype("datetime64[ms]")
        values = (100.0 + np.sin(np.arange(n) / 6.0)).astype(float)
        values[5] = np.nan  # a gap
        self._data = {
            "timestamp": ts,
            "value": values,
            "seasonality_data": np.array(
                [{"hour": int(i % 24)} if seasonal else {} for i in range(n)], dtype=object
            ),
            "seasonality_columns": ["hour"] if seasonal else [],
        }
        self._first = ts[0].astype(datetime)
        self._last = ts[-1].astype(datetime)

    def get_last_datapoint_timestamp(self, name):
        return self._last

    def get_first_datapoint_timestamp(self, name):
        return self._first

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        return self._data


def _metric(**kw) -> MetricConfig:
    base = {"name": "orders", "interval": "1h", "query": "SELECT timestamp, value FROM t"}
    base.update(kw)
    return MetricConfig(**base)


def test_normalize_seasonality_components():
    assert _normalize_seasonality_components(None) is None
    assert _normalize_seasonality_components([]) is None
    assert _normalize_seasonality_components(["hour"]) == [["hour"]]
    assert _normalize_seasonality_components([["hour", "day_of_week"]]) == [["hour", "day_of_week"]]
    assert _normalize_seasonality_components(["hour", ["a", "b"]]) == [["hour"], ["a", "b"]]


def test_seed_detector_from_config():
    m = _metric(
        detectors=[
            {
                "type": "zscore",
                "params": {
                    "threshold": 2.0,
                    "window_size": 250,
                    "window_weights": "exponential",
                    "half_life": 30,
                    "seasonality_components": [["hour", "day_of_week"]],
                },
            }
        ]
    )
    seed = _seed_detector(m)
    assert seed["type"] == "zscore"
    assert seed["threshold"] == 2.0
    assert seed["windowSize"] == 250
    assert seed["windowWeights"] == "exponential"
    assert seed["halfLife"] == 30
    assert seed["seasonalityComponents"] == [["hour", "day_of_week"]]
    # camelCase 'none' normalization for unset detrend/smoothing
    assert seed["smoothing"] == "none"
    assert seed["detrend"] == "none"


def test_seed_detector_falls_back_to_mad_defaults():
    # only a manual_bounds detector → not tunable → MAD defaults
    m = _metric(
        detectors=[{"type": "manual_bounds", "params": {"lower_bound": 0, "upper_bound": 9}}]
    )
    seed = _seed_detector(m)
    assert seed["type"] == "mad"
    assert seed["threshold"] == 3.0
    assert seed["windowSize"] == 100
    assert seed["windowWeights"] == "none"
    assert seed["seasonalityComponents"] is None


def test_seed_detector_duration_half_life_falls_back_to_adaptive():
    m = _metric(
        detectors=[{"type": "mad", "params": {"window_weights": "exponential", "half_life": "1d"}}]
    )
    seed = _seed_detector(m)
    # a duration string can't seed a numeric slider → null (adaptive)
    assert seed["halfLife"] is None


def test_build_payload_shape():
    internal = FakeInternal(n=48, seasonal=True)
    m = _metric(
        seasonality_columns=["hour"],
        detectors=[{"type": "mad", "params": {"threshold": 3.0}}],
        alerting=[{"enabled": True, "channels": ["slack"], "consecutive_anomalies": 4}],
    )
    start = datetime(2026, 1, 1, 0, 0, 0)
    end = datetime(2026, 1, 2, 23, 0, 0)
    payload = build_tune_payload(
        metric_config=m, internal=internal, start=start, end=end, project_name="demo"
    )
    assert payload["metric"] == "orders"
    assert payload["project"] == "demo"
    assert payload["interval_seconds"] == 3600
    assert payload["save_url"] is None
    assert payload["consecutive_anomalies"] == 4
    # points + seasonality are aligned 1:1
    assert len(payload["points"]) == len(payload["seasonality"]) == 48
    assert payload["seasonality_columns"] == ["hour"]
    # a NaN value becomes None (gap)
    assert payload["points"][5]["v"] is None
    # seasonality cells parsed into dicts
    assert payload["seasonality"][0] == {"hour": 0}
    # detector seed present
    assert payload["detector"]["type"] == "mad"


def test_build_payload_empty_when_no_datapoints():
    class Empty(FakeInternal):
        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            return {
                "timestamp": np.array([], dtype="datetime64[ms]"),
                "value": np.array([], dtype=float),
                "seasonality_data": np.array([], dtype=object),
                "seasonality_columns": [],
            }

    m = _metric()
    payload = build_tune_payload(
        metric_config=m,
        internal=Empty(),
        start=datetime(2026, 1, 1),
        end=datetime(2026, 1, 2),
    )
    assert payload["points"] == []


def test_render_tune_html_bakes_payload_and_bundle():
    internal = FakeInternal(n=24)
    m = _metric(detectors=[{"type": "mad", "params": {"threshold": 3.0}}])
    payload = build_tune_payload(
        metric_config=m,
        internal=internal,
        start=datetime(2026, 1, 1, 0, 0, 0),
        end=datetime(2026, 1, 1, 23, 0, 0),
        save_url="http://127.0.0.1:9/apply?token=t",
    )
    html = render_tune_html(payload)
    assert "__DTK_TUNE__" in html
    assert "window.__DTK_TUNE_PAYLOAD__" in html
    assert "window.__DTK_TUNE__.render" in html
    # no leftover placeholders
    for placeholder in ("__PAYLOAD__", "__METRIC__", "__FAVICON__", "__TUNE_JS__"):
        assert placeholder not in html
