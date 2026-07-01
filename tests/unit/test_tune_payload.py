"""Tests for the dtk tune payload builder + HTML shell."""

from datetime import datetime, timedelta, timezone

import numpy as np

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.html import render_tune_html
from detectkit.tuning.payload import (
    DEFAULT_FALSE_ALERT_BUDGET,
    _normalize_seasonality_components,
    _seed_detector,
    _seed_direction,
    build_tune_payload,
    default_window_points,
    seed_detector_params,
)


def test_seed_detector_params_maps_autotune_winner():
    """The shared snake->camel seam used to re-seed the controls from an autotune result."""
    seed = seed_detector_params(
        "zscore",
        {
            "threshold": 4.0,
            "window_size": 240,
            "window_weights": "exponential",
            "half_life": 30,
            "detrend": "linear",
            "seasonality_components": [["hour"]],
            "min_samples_per_group": 6,
        },
    )
    assert seed["type"] == "zscore"
    assert seed["threshold"] == 4.0
    assert seed["windowSize"] == 240
    assert seed["windowWeights"] == "exponential"
    assert seed["halfLife"] == 30
    assert seed["detrend"] == "linear"
    assert seed["seasonalityComponents"] == [["hour"]]
    assert seed["minSamplesPerGroup"] == 6
    # absent windowed knobs still carry sane defaults (no empty sliders)
    assert seed["smoothing"] == "none"
    assert seed["lowerBound"] is None


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


def test_detectors_payload_prefers_windowed_and_lists_all():
    """The cockpit opens on the first WINDOWED detector even when a manual_bounds
    floor comes first, and bakes ALL detectors for the picker with correct slots."""
    m = _metric(
        detectors=[
            {"type": "manual_bounds", "params": {"lower_bound": 1}},
            {"type": "mad", "params": {"threshold": 3.0, "window_size": 8640}},
        ]
    )
    payload = build_tune_payload(metric_config=m, internal=FakeInternal())
    assert payload["detector_index"] == 1  # the windowed mad, not the leading floor
    dets = payload["detectors"]
    assert [d["type"] for d in dets] == ["manual_bounds", "mad"]
    assert [d["index"] for d in dets] == [0, 1]
    assert all(d["tunable"] for d in dets)
    assert dets[0]["seed"]["lowerBound"] == 1
    assert dets[1]["seed"]["windowSize"] == 8640
    assert "lower=1" in dets[0]["summary"]
    # the top-level `detector` seed matches the active (windowed) entry
    assert payload["detector"]["type"] == "mad"


def test_detectors_payload_marks_non_tunable_and_preserves_index():
    """A prophet detector is listed but flagged non-tunable (no seed); the cockpit
    seeds the tunable mad and surfaces prophet as preserved-on-Apply."""
    m = _metric(
        detectors=[
            {"type": "prophet", "params": {"interval_width": 0.99}},
            {"type": "mad", "params": {"threshold": 3.0}},
        ]
    )
    payload = build_tune_payload(metric_config=m, internal=FakeInternal())
    assert payload["detector_index"] == 1
    dets = payload["detectors"]
    assert dets[0]["type"] == "prophet"
    assert dets[0]["tunable"] is False
    assert dets[0]["seed"] is None
    assert dets[1]["tunable"] is True


def test_detectors_payload_no_tunable_detector():
    """A metric with only a non-tunable detector → active index None, MAD-default
    seed, and the existing detector is still listed (preserved on Apply)."""
    m = _metric(detectors=[{"type": "prophet", "params": {"interval_width": 0.99}}])
    payload = build_tune_payload(metric_config=m, internal=FakeInternal())
    assert payload["detector_index"] is None
    assert payload["detector"]["type"] == "mad"  # fresh default seed
    assert [d["type"] for d in payload["detectors"]] == ["prophet"]


def test_detectors_payload_single_detector():
    """A plain single-detector metric: one entry, active index 0 (no picker needed)."""
    m = _metric(detectors=[{"type": "mad", "params": {"threshold": 3.0}}])
    payload = build_tune_payload(metric_config=m, internal=FakeInternal())
    assert payload["detector_index"] == 0
    assert len(payload["detectors"]) == 1
    assert payload["detectors"][0]["index"] == 0


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
    # endpoints are injected by the server, not the builder
    assert payload["labels_save_url"] is None
    assert payload["autotune_url"] is None
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
    assert payload["capture_windows"] == []
    assert payload["labels_save_url"] is None


def test_payload_includes_capture_windows_seed():
    capture = [{"start": "2026-01-01 00:00:00", "end": "2026-01-01 04:00:00"}]
    payload = build_tune_payload(
        metric_config=_metric(), internal=FakeInternal(), capture_windows=capture
    )
    assert payload["capture_windows"] == capture


def test_payload_false_alert_budget_defaults_when_unset():
    # No budget passed → the built-in default is baked, so the cockpit always has a
    # number to flag against.
    payload = build_tune_payload(metric_config=_metric(), internal=FakeInternal())
    assert payload["false_alert_budget"] == DEFAULT_FALSE_ALERT_BUDGET


def test_payload_false_alert_budget_honored_when_passed():
    payload = build_tune_payload(
        metric_config=_metric(), internal=FakeInternal(), false_alert_budget=0.2
    )
    assert payload["false_alert_budget"] == 0.2

    # ...and on the empty (no-datapoints) payload path too.
    class Empty(FakeInternal):
        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            return {
                "timestamp": np.array([], dtype="datetime64[ms]"),
                "value": np.array([], dtype=float),
                "seasonality_data": np.array([], dtype=object),
                "seasonality_columns": [],
            }

    empty = build_tune_payload(metric_config=_metric(), internal=Empty(), false_alert_budget=0.2)
    assert empty["points"] == []
    assert empty["false_alert_budget"] == 0.2


class _WindowRecording(FakeInternal):
    """Records the [from, to] window the builder requests, with custom bounds."""

    def __init__(self, last, firstdp):
        super().__init__(n=10)
        self.requested_from = None
        self.requested_to = None
        self._last_dp = last
        self._firstdp = firstdp

    def get_last_datapoint_timestamp(self, name):
        return self._last_dp

    def get_first_datapoint_timestamp(self, name):
        return self._firstdp

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        self.requested_from = from_timestamp
        self.requested_to = to_timestamp
        return self._data


def test_seeded_incident_anchors_a_bounded_window_on_the_incident():
    """A seeded incident older than the recent slice anchors the (budget-sized)
    window on the incident region — it ends just past the latest incident rather
    than at the last datapoint — so the incident renders without loading history."""
    rec = _WindowRecording(datetime(2026, 6, 1, 0, 0, 0), datetime(2020, 1, 1, 0, 0, 0))
    build_tune_payload(
        metric_config=_metric(),  # 1h grid, window 100 → ~15000-point budget
        internal=rec,
        incidents=[{"start": "2024-01-01 00:00:00", "end": "2024-01-01 06:00:00"}],
    )
    budget_pts = default_window_points(100)
    # The window ENDS shortly after the latest incident, NOT at the last datapoint.
    assert rec.requested_to is not None and rec.requested_to < datetime(2026, 1, 1)
    assert rec.requested_to >= datetime(2024, 1, 1, 6, 0, 0)  # covers the incident end
    # ...and is budget-bounded, not the whole 2020→2026 history.
    span_hours = (rec.requested_to - rec.requested_from).total_seconds() / 3600
    assert span_hours <= budget_pts + 1


def test_seeded_incident_window_stays_budget_bounded():
    """A wildly old incident on a minute-grained series loads a budget-sized window
    around the incident — NOT the whole history (the recompute-budget protection)."""
    rec = _WindowRecording(datetime(2026, 6, 1, 0, 0, 0), datetime(2000, 1, 1, 0, 0, 0))
    build_tune_payload(
        metric_config=_metric(interval="1min"),
        internal=rec,
        incidents=[{"start": "2001-01-01 00:00:00", "end": "2001-01-01 00:05:00"}],
    )
    budget_pts = default_window_points(100)
    span_minutes = (rec.requested_to - rec.requested_from).total_seconds() / 60
    assert span_minutes <= budget_pts + 1  # bounded, not 26 years of minutes
    # anchored on the (ancient) incident, not the recent end
    assert rec.requested_to < datetime(2001, 2, 1)


def test_seeded_incident_with_tz_aware_db_timestamps():
    """A backend that returns tz-aware datetimes must not crash when anchoring the
    window on a (naive-UTC) seeded incident (regression: 'can't compare
    offset-naive and offset-aware datetimes')."""

    class AwareRecording(FakeInternal):
        def __init__(self):
            super().__init__(n=10)
            self.requested_from = None

        def get_last_datapoint_timestamp(self, name):
            return datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

        def get_first_datapoint_timestamp(self, name):
            return datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            self.requested_from = from_timestamp
            return self._data

    rec = AwareRecording()
    incident_start = datetime(2024, 1, 1, 0, 0, 0)  # naive UTC, well before the slice
    build_tune_payload(
        metric_config=_metric(),
        internal=rec,
        incidents=[{"start": "2024-01-01 00:00:00", "end": "2024-01-01 06:00:00"}],
    )
    assert rec.requested_from is not None
    # widened to (at/before) the incident, and stays tz-aware like the DB timestamps
    assert rec.requested_from.tzinfo is not None
    assert rec.requested_from <= incident_start.replace(tzinfo=timezone.utc)


def test_explicit_from_not_widened_by_incidents():
    """An explicit --from wins even when a seeded incident is older."""

    class Recording(FakeInternal):
        def __init__(self):
            super().__init__(n=10)
            self.requested_from = None

        def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
            self.requested_from = from_timestamp
            return self._data

    rec = Recording()
    explicit = datetime(2026, 1, 1, 0, 0, 0)
    build_tune_payload(
        metric_config=_metric(),
        internal=rec,
        start=explicit,
        end=datetime(2026, 2, 1, 0, 0, 0),
        incidents=[{"start": "2020-01-01 00:00:00", "end": "2020-01-01 06:00:00"}],
    )
    assert rec.requested_from == explicit
