"""Tests for the dtk tune payload builder + HTML shell."""

from datetime import datetime, timedelta

import numpy as np

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.html import render_tune_html
from detectkit.tuning.payload import (
    _normalize_seasonality_components,
    _seed_detector,
    _seed_direction,
    build_tune_payload,
    default_window_points,
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


def test_seed_detector_no_detectors_falls_back_to_mad_defaults():
    # a metric with no detectors → seed MAD defaults so the sliders open sanely
    m = _metric(detectors=[])
    seed = _seed_detector(m)
    assert seed["type"] == "mad"
    assert seed["threshold"] == 3.0
    assert seed["windowSize"] == 100
    assert seed["windowWeights"] == "none"
    assert seed["seasonalityComponents"] is None
    assert seed["lowerBound"] is None
    assert seed["upperBound"] is None


def test_seed_detector_manual_bounds():
    # a manual_bounds metric seeds the bound sliders; the windowed knobs still
    # carry sane defaults so switching detector type in the UI never hits empties.
    m = _metric(
        detectors=[{"type": "manual_bounds", "params": {"lower_bound": 0, "upper_bound": 9}}]
    )
    seed = _seed_detector(m)
    assert seed["type"] == "manual_bounds"
    assert seed["lowerBound"] == 0
    assert seed["upperBound"] == 9
    assert seed["windowSize"] == 100  # windowed default present for the UI switch


def test_seed_direction_from_alerting():
    assert _seed_direction(_metric()) == "any"  # no alerting → any
    up = _metric(alerting=[{"channels": ["x"], "direction": "up"}])
    assert _seed_direction(up) == "up"
    # 'same' is a multi-detector agreement policy → reads as 'any' for the
    # single-detector tuning preview.
    same = _metric(alerting=[{"channels": ["x"], "direction": "same"}])
    assert _seed_direction(same) == "any"


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


def test_default_window_is_bounded_not_full_history():
    """With no --from, the window starts a budget-sized number of points before the
    last datapoint — NOT at the first datapoint — so huge histories stay interactive."""

    class Recording(FakeInternal):
        def __init__(self):
            super().__init__(n=10)
            self.requested_from = None

        def get_last_datapoint_timestamp(self, name):
            return datetime(2026, 6, 1, 0, 0, 0)

        def get_first_datapoint_timestamp(self, name):
            return datetime(2020, 1, 1, 0, 0, 0)  # years of history

        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            self.requested_from = from_timestamp
            return self._data

    rec = Recording()
    build_tune_payload(metric_config=_metric(), internal=rec)  # no start/end
    # seed is a default MAD detector (window 100) → smart default point count
    expected = datetime(2026, 6, 1, 0, 0, 0) - timedelta(seconds=3600 * default_window_points(100))
    assert rec.requested_from == expected  # bounded recent window, not 2020


def test_default_window_points_inverse_budget_with_window_fill_floor():
    # Small window → the inverse-budget term dominates, render-capped at MAX.
    assert default_window_points(100) == 15000  # 20M/100 = 200k → MAX
    assert default_window_points(2000) == 10000  # 20M/2000, fill 6000 < budget
    # Mid-large window: the budget term drops below a few windows' worth, so the
    # fill floor (3× window) takes over so the window is actually exercised in the
    # preview instead of leaving almost no scored region.
    assert default_window_points(4000) == 12000  # fill 4000*3 > budget 5000
    # Very large window → the fill floor clamps to MAX (never collapses to MIN, as
    # it used to — that left a big-window metric with no meaningful scored region).
    assert default_window_points(50000) == 15000
    assert default_window_points(0) == 15000  # guards divide-by-zero


def test_explicit_from_is_honored_in_full():
    """An explicit start (--from) is used as-is, not clamped to the recent window."""

    class Recording(FakeInternal):
        def __init__(self):
            super().__init__(n=10)
            self.requested_from = None

        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            self.requested_from = from_timestamp
            return self._data

    rec = Recording()
    explicit = datetime(2020, 3, 1, 0, 0, 0)
    build_tune_payload(
        metric_config=_metric(),
        internal=rec,
        start=explicit,
        end=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert rec.requested_from == explicit


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


def test_payload_includes_incidents_seed():
    incidents = [{"start": "2026-01-01 00:00:00", "end": "2026-01-01 02:00:00", "label": "x"}]
    payload = build_tune_payload(
        metric_config=_metric(), internal=FakeInternal(), incidents=incidents
    )
    assert payload["incidents"] == incidents
    # labels_save_url is injected by the server, not the builder.
    assert payload["labels_save_url"] is None


def test_payload_incidents_default_empty():
    payload = build_tune_payload(metric_config=_metric(), internal=FakeInternal())
    assert payload["incidents"] == []
    assert payload["labels_save_url"] is None
