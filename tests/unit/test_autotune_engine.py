"""End-to-end engine tests: distribution decision, full run, config emission."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from detectkit.autotune import (
    ScoringMetric,
    TuneSettings,
    compute_run_id,
    emit_tuned_config,
    parse_incident_labels,
    run_autotune_engine,
)
from detectkit.autotune.detector_select import detector_suitability
from detectkit.autotune.distribution import compute_distribution_features
from detectkit.autotune.labels import IncidentLabels
from detectkit.config.metric_config import MetricConfig


def _seasonal_series(n=24 * 40, anomalies=(300, 301, 600), bump=70.0, noise=4.0, seed=7):
    rng = np.random.RandomState(seed)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    hours = np.array([i % 24 for i in range(n)])
    dow = np.array([(i // 24) % 7 for i in range(n)])
    vals = (100 + 30 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, noise, n)).astype(np.float64)
    for i in anomalies:
        vals[i] += bump
    seas = np.array(
        [json.dumps({"hour": int(hours[i]), "day_of_week": int(dow[i])}) for i in range(n)],
        dtype=object,
    )
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": seas,
        "seasonality_columns": ["hour", "day_of_week"],
    }, ts


# ── distribution decision tree ───────────────────────────────────────────────


def test_suitability_prefers_zscore_on_clean_normal_data():
    clean = np.random.RandomState(0).normal(0, 1, 1000)
    f = compute_distribution_features(clean)
    z = detector_suitability("zscore", f)
    m = detector_suitability("mad", f)
    assert z > m  # gaussian → zscore wins


def test_suitability_prefers_mad_on_heavy_tailed_data():
    rng = np.random.RandomState(0)
    heavy = np.concatenate([rng.normal(0, 1, 1000), rng.normal(0, 1, 40) * 15])
    f = compute_distribution_features(heavy)
    assert detector_suitability("mad", f) > detector_suitability("zscore", f)


def test_unknown_type_is_neutral():
    f = compute_distribution_features(np.random.RandomState(0).normal(0, 1, 200))
    assert detector_suitability("future_detector", f) == 0.5


# ── full engine run ──────────────────────────────────────────────────────────


def _labels_for(ts, idxs):
    def to_dt(i):
        ms = int(np.datetime64(ts[i], "ms").astype(np.int64))
        return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")

    return parse_incident_labels(
        {"incidents": [{"at": to_dt(i)} for i in idxs]}, interval_seconds=3600
    )


def test_supervised_run_produces_valid_tuned_config(tmp_path):
    data, ts = _seasonal_series()
    gt = _labels_for(ts, [300, 301, 600]).to_ground_truth(ts, 3600)
    assert gt.mode.value == "supervised"

    result = run_autotune_engine(
        metric_name="demo",
        data=data,
        ground_truth=gt,
        interval_seconds=3600,
        settings=TuneSettings(metric=ScoringMetric.MCC),
    )
    assert result.chosen_detector_type in {"mad", "zscore", "iqr"}
    assert result.winning_detector_id in result.candidate_detector_ids
    assert result.chosen_detector_params["window_size"] >= 1

    # Emit + round-trip the config.
    orig = MetricConfig(
        name="demo",
        interval="1h",
        query="SELECT 1",
        seasonality_columns=["hour", "day_of_week"],
        alerting=[{"channels": ["slack"], "consecutive_anomalies": 3}],
    )
    run_id = compute_run_id(result)
    out_path, text, rid = emit_tuned_config(
        original_config=orig,
        original_path=Path("metrics/demo.yml"),
        result=result,
        project_root=Path("."),
        run_id=run_id,
    )
    assert rid == run_id
    assert text.lstrip().startswith("#")  # leads with the decision comment block
    assert "Auto-tuned by `dtk autotune`" in text
    assert out_path.name == f"demo__tuned_{run_id}.yml"

    written = tmp_path / out_path.name
    written.write_text(text)
    reparsed = MetricConfig.from_yaml_file(written)
    assert reparsed.name == f"demo__tuned_{run_id}"
    assert len(reparsed.detectors) == 1
    assert reparsed.detectors[0].type == result.chosen_detector_type


def test_unsupervised_run_without_labels(tmp_path):
    data, ts = _seasonal_series()
    gt = IncidentLabels([], []).to_ground_truth(ts, 3600)
    assert gt.mode.value == "unsupervised"
    result = run_autotune_engine(
        metric_name="demo",
        data=data,
        ground_truth=gt,
        interval_seconds=3600,
        settings=TuneSettings(),
    )
    assert result.chosen_detector_type in {"mad", "zscore", "iqr"}
    assert result.consecutive_anomalies is None  # alert window only tuned when supervised


def test_run_id_is_deterministic():
    data, ts = _seasonal_series()
    gt = _labels_for(ts, [300, 301, 600]).to_ground_truth(ts, 3600)
    r1 = run_autotune_engine(
        metric_name="demo",
        data=data,
        ground_truth=gt,
        interval_seconds=3600,
        settings=TuneSettings(),
    )
    r2 = run_autotune_engine(
        metric_name="demo",
        data=data,
        ground_truth=gt,
        interval_seconds=3600,
        settings=TuneSettings(),
    )
    assert compute_run_id(r1) == compute_run_id(r2)
