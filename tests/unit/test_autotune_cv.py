"""Tests for walk-forward cross-validation plan + scoring."""

import json

import numpy as np

from detectkit.autotune._types import ScoringMetric, TuneMode
from detectkit.autotune.crossval import build_cv_plan, predictions_from_results, run_cv
from detectkit.autotune.labels import GroundTruth
from detectkit.autotune.settings import TuneSettings
from detectkit.detectors.factory import DetectorFactory


def test_build_cv_plan_reserves_context_and_partitions():
    plan = build_cv_plan(n_points=120, context_size=20, fold_count=5)
    assert plan.context_end == 20
    assert plan.fold_bounds == [(20, 40), (40, 60), (60, 80), (80, 100), (100, 120)]
    # Every scored index is >= context_end (no point is scored without lead-in)
    assert all(lo >= plan.context_end for lo, _hi in plan.fold_bounds)


def test_build_cv_plan_too_small_yields_no_folds():
    plan = build_cv_plan(n_points=10, context_size=20, fold_count=5)
    assert plan.fold_bounds == []


def test_build_cv_plan_caps_folds_to_points():
    plan = build_cv_plan(n_points=23, context_size=20, fold_count=5)
    # only 3 scored points → at most 3 folds
    assert len(plan.fold_bounds) <= 3


def _series(n=480):
    rng = np.random.RandomState(3)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    hours = np.array([i % 24 for i in range(n)])
    vals = (100 + 20 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 3, n)).astype(np.float64)
    vals[300] += 80  # one clear anomaly
    seas = np.array([json.dumps({"hour": int(h)}) for h in hours], dtype=object)
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": seas,
        "seasonality_columns": ["hour"],
    }, ts


def test_predictions_align_with_results():
    data, _ = _series()
    detector = DetectorFactory.create("zscore", {"window_size": 100, "min_samples": 30})
    results = detector.detect(data)
    y_pred, y_score, valid = predictions_from_results(results)
    assert len(y_pred) == len(results) == len(data["timestamp"])
    # the first window_size points are cold-start (no band) → invalid
    assert not valid[:30].any()


def test_run_cv_returns_fold_scores():
    data, ts = _series()
    y = np.zeros(len(ts), dtype=bool)
    y[300] = True
    gt = GroundTruth(y_true=y, mode=TuneMode.SUPERVISED, n_positive=1, n_intervals=0, n_points=1)
    plan = build_cv_plan(len(ts), context_size=100, fold_count=5)
    detector = DetectorFactory.create("zscore", {"window_size": 100, "min_samples": 30})
    scores = run_cv(detector, data, plan, gt, TuneSettings(metric=ScoringMetric.MCC))
    # supervised: only the fold containing the labeled anomaly is scored
    assert len(scores.per_fold) >= 1
    assert -1.0 <= scores.aggregate <= 1.0
