"""Tests for the shared autotune runner (used by `dtk autotune` and `dtk tune`)."""

import numpy as np
import pytest

from detectkit.autotune._types import ScoringMetric, TuneMode
from detectkit.autotune.labels import IncidentLabels, parse_incident_labels
from detectkit.autotune.result import AutoTuneResult
from detectkit.autotune.runner import (
    DEFAULT_TRAIN_CAP,
    autotune_from_data,
    build_settings,
    cap_history,
    resolve_scoring,
)
from detectkit.config.metric_config import AutoTuneConfig


def _series(n: int = 600) -> dict:
    rng = np.random.RandomState(5)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    vals = (100 + rng.normal(0, 3, n)).astype(np.float64)
    for i in (200, 201, 400):
        if i < n:
            vals[i] += 60.0
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": np.array(["{}"] * n, dtype=object),
        "seasonality_columns": [],
    }


def test_resolve_scoring_default_and_override():
    cfg = AutoTuneConfig()
    assert resolve_scoring(None, cfg) == ScoringMetric.MCC
    assert resolve_scoring("f1", cfg) == ScoringMetric.F1
    # config value is used when no override
    assert resolve_scoring(None, AutoTuneConfig(scoring_metric="roc_auc")) == ScoringMetric.ROC_AUC


def test_resolve_scoring_bad_raises_valueerror():
    with pytest.raises(ValueError, match="Invalid scoring metric"):
        resolve_scoring("nonsense", AutoTuneConfig())


def test_build_settings_maps_config():
    cfg = AutoTuneConfig(folds=3, stability_lambda=0.25, detector_types=["mad", "iqr"])
    s = build_settings(scoring=ScoringMetric.MCC, autotune_cfg=cfg)
    assert s.fold_count == 3
    assert s.stability_lambda == 0.25
    assert s.allowed_detector_types == ["mad", "iqr"]
    assert s.metric == ScoringMetric.MCC


def test_cap_history_keeps_most_recent():
    data = _series(10)
    capped = cap_history(data, max_history=4)
    assert len(capped["timestamp"]) == 4
    assert capped["timestamp"][-1] == data["timestamp"][-1]  # newest retained
    # below the cap → returned unchanged (same object)
    assert cap_history(data, max_history=None) is data
    assert DEFAULT_TRAIN_CAP == 50_000


def test_autotune_from_data_unsupervised():
    result = autotune_from_data(
        metric_name="orders",
        data=_series(),
        labels=IncidentLabels([], []),
        interval_seconds=3600,
        autotune_cfg=AutoTuneConfig(folds=3),
    )
    assert isinstance(result, AutoTuneResult)
    assert result.mode == TuneMode.UNSUPERVISED.value
    assert result.chosen_detector_type in {"mad", "zscore", "iqr"}
    assert "threshold" in result.chosen_detector_params
    assert result.consecutive_anomalies is None  # only supervised sweeps the window


def test_autotune_from_data_supervised_sweeps_window():
    labels = parse_incident_labels(
        {"incidents": [{"start": "2026-01-09 08:00:00", "end": "2026-01-09 09:00:00"}]},
        interval_seconds=3600,
    )
    result = autotune_from_data(
        metric_name="orders",
        data=_series(),
        labels=labels,
        interval_seconds=3600,
        autotune_cfg=AutoTuneConfig(folds=3),
    )
    assert result.mode == TuneMode.SUPERVISED.value
    assert isinstance(result.consecutive_anomalies, int)


def test_autotune_from_data_caps_then_aligns_ground_truth():
    # The 600-pt series is capped to the most-recent 400 BEFORE ground truth is
    # projected; the incident (index ~200, i.e. 2026-01-09 08:00) stays in the kept
    # tail, so the label must still align to the capped grid. This fails loudly if
    # cap_history and to_ground_truth are ever reordered (length mismatch / lost
    # positives → mode would read UNSUPERVISED).
    labels = parse_incident_labels(
        {"incidents": [{"start": "2026-01-09 08:00:00", "end": "2026-01-09 09:00:00"}]},
        interval_seconds=3600,
    )
    result = autotune_from_data(
        metric_name="orders",
        data=_series(600),
        labels=labels,
        interval_seconds=3600,
        autotune_cfg=AutoTuneConfig(folds=3, max_history=400),
    )
    assert result.n_points == 400  # capped
    assert result.mode == TuneMode.SUPERVISED.value  # label still projected onto capped grid
    assert isinstance(result.consecutive_anomalies, int)
