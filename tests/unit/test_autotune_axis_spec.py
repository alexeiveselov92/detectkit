"""Per-type axis-spec seam tests (issue #97 Phase 2).

Locks the seam's contract: windowed types keep exactly the pre-seam axes
(behavior-identical), autoreg sweeps only its own axes (threshold / lags /
stabilization / window) and never receives ``seasonality_components``, the
min-samples floor tracks ``lags + 2``, and the CV plan reserves the real
worst-case context (stabilization warm-up + AR lags) instead of the raw
window size.
"""

import json
from datetime import datetime, timedelta

import numpy as np

from detectkit.autotune import ScoringMetric, TuneSettings, parse_incident_labels
from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune.autotuner import run_autotune_engine
from detectkit.autotune.axis_spec import (
    AxisSpec,
    axis_spec_for,
    max_context_size,
    resolve_floor,
    resolve_threshold_default,
)
from detectkit.autotune.labels import IncidentLabels
from detectkit.autotune.window_select import min_samples_for

HOUR = 3600


def _hourly_ts(n):
    return np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )


def _dt_str(ts, i):
    ms = int(np.datetime64(ts[i], "ms").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


class TestSpecShape:
    def test_windowed_types_get_the_full_axis_set(self):
        for t in ("mad", "zscore", "iqr"):
            spec = axis_spec_for(t)
            assert spec.seasonality and spec.weighting and spec.detrend and spec.stabilization
            assert not spec.lags
            assert spec.initial == {}

    def test_unlisted_future_type_defaults_to_windowed(self):
        assert axis_spec_for("future_detector") == AxisSpec()

    def test_autoreg_spec_gates_windowed_only_axes(self):
        spec = axis_spec_for("autoreg")
        assert not spec.seasonality and not spec.weighting and not spec.detrend
        assert spec.stabilization and spec.lags
        assert spec.initial["stabilization"] == "clamp"  # detector default, explicit

    def test_floor_and_threshold_resolution(self):
        # autoreg has no MIN_SAMPLES_FLOOR/THRESHOLD_DEFAULT class attrs — the
        # spec override prevents the silent floor=1 fallback.
        assert resolve_floor("autoreg") == 10
        assert resolve_threshold_default("autoreg") == 3.0
        # Windowed types keep their class attributes.
        from detectkit.detectors.statistical.mad import MADDetector

        assert resolve_floor("mad") == int(MADDetector.MIN_SAMPLES_FLOOR)
        assert resolve_threshold_default("mad") == float(MADDetector.THRESHOLD_DEFAULT)


class TestMinSamplesLagsFloor:
    def test_lags_floor_applies(self):
        assert min_samples_for(40, 10, lags=20) == 22  # lags + 2 beats window/4

    def test_lags_floor_clamped_to_window(self):
        assert min_samples_for(20, 10, lags=19) == 20  # never exceeds window

    def test_windowed_signature_unchanged(self):
        assert min_samples_for(100, 10) == 25  # pre-seam behavior, golden


def _tuner_for_context(values, settings=None):
    ts = _hourly_ts(len(values))
    gt = IncidentLabels([], []).to_ground_truth(ts, HOUR)
    return _AutoTuneBase(
        metric_name="x",
        data={
            "timestamp": ts,
            "value": values,
            "seasonality_data": np.array([], dtype=object),
            "seasonality_columns": [],
        },
        ground_truth=gt,
        interval_seconds=HOUR,
        settings=settings or TuneSettings(),
    )


class TestMaxContext:
    def test_reserves_stabilization_and_lags_context(self):
        tuner = _tuner_for_context(np.random.RandomState(0).normal(0, 1, 2000))
        grid = [100]
        # Worst case: stabilized autoreg = 2×window + lags.
        assert max_context_size(tuner, grid) >= 2 * 100 + max(TuneSettings().lags_grid)

    def test_restricted_to_windowed_still_reserves_stabilization(self):
        settings = TuneSettings(allowed_detector_types=["mad"])
        tuner = _tuner_for_context(np.random.RandomState(0).normal(0, 1, 2000), settings)
        assert max_context_size(tuner, [100]) >= 2 * 100


class TestAutoregEngineRun:
    def test_autoreg_only_run_produces_valid_autoreg_config(self, tmp_path):
        """End-to-end: restricted to autoreg, the engine sweeps lags, floors
        min_samples at lags + 2, never injects seasonality_components, and the
        emitted config validates + round-trips."""
        from pathlib import Path

        from detectkit.autotune import emit_tuned_config
        from detectkit.config.metric_config import MetricConfig

        n = 24 * 40
        rng = np.random.RandomState(7)
        ts = _hourly_ts(n)
        hours = np.arange(n) % 24
        values = 100 + 30 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 4, n)
        anomalies = (300, 301, 600)
        for i in anomalies:
            values[i] += 70
        seas = np.array(
            [json.dumps({"hour": int(hours[i])}) for i in range(n)],
            dtype=object,
        )
        data = {
            "timestamp": ts,
            "value": values,
            "seasonality_data": seas,
            "seasonality_columns": ["hour"],
        }
        labels = parse_incident_labels(
            {"incidents": [{"at": _dt_str(ts, i)} for i in anomalies]}, interval_seconds=HOUR
        )
        gt = labels.to_ground_truth(ts, HOUR)

        result = run_autotune_engine(
            metric_name="demo",
            data=data,
            ground_truth=gt,
            interval_seconds=HOUR,
            settings=TuneSettings(metric=ScoringMetric.MCC, allowed_detector_types=["autoreg"]),
        )

        assert result.chosen_detector_type == "autoreg"
        params = result.chosen_detector_params
        assert "seasonality_components" not in params
        assert params["lags"] >= 1
        assert params["min_samples"] >= params["lags"] + 2
        assert params["window_size"] >= params["lags"] + 2

        orig = MetricConfig(
            name="demo",
            interval="1h",
            query="SELECT 1",
            seasonality_columns=["hour"],
            alerting=[{"channels": ["slack"]}],
        )
        out_path, text, _rid = emit_tuned_config(
            original_config=orig,
            original_path=Path("metrics/demo.yml"),
            result=result,
            project_root=Path("."),
        )
        written = tmp_path / out_path.name
        written.write_text(text)
        reparsed = MetricConfig.from_yaml_file(written)
        assert reparsed.detectors[0].type == "autoreg"
        assert "seasonality_components" not in reparsed.detectors[0].params
