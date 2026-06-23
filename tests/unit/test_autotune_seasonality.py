"""Tests for the unsupervised seasonality-selection criterion.

The criterion is a leak-free, walk-forward, band-width-aware Gaussian-NLL probe
(``oof_residual_reduction``) — decoupled from the detector flag-objective so it
measures *explained structure*, not flag rate.
"""

import json

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune.crossval import build_cv_plan
from detectkit.autotune.labels import IncidentLabels
from detectkit.autotune.scoring import oof_residual_reduction
from detectkit.autotune.seasonality_search import search_seasonality
from detectkit.autotune.settings import TuneSettings


def _plan(n, ctx=160, folds=4):
    return build_cv_plan(n, ctx, folds)


def test_oof_baseline_scores_zero():
    rng = np.random.default_rng(0)
    n = 600
    values = rng.normal(0, 1, n)
    flat = np.zeros(n, dtype=np.int64)
    score, _ = oof_residual_reduction(values, np.ones(n), flat, _plan(n), min_group=10)
    assert score == 0.0


def test_oof_rewards_center_seasonality():
    rng = np.random.default_rng(1)
    n = 800
    group = np.arange(n) % 2
    values = np.where(group == 0, 0.0, 20.0) + rng.normal(0, 1.0, n)
    score, _ = oof_residual_reduction(
        values, np.ones(n), group.astype(object), _plan(n), min_group=10
    )
    assert score > 0.5


def test_oof_rewards_spread_seasonality():
    rng = np.random.default_rng(2)
    n = 800
    group = np.arange(n) % 2
    values = rng.normal(0, 1.0, n)
    values[group == 1] = rng.normal(0, 8.0, int((group == 1).sum()))
    score, _ = oof_residual_reduction(
        values, np.ones(n), group.astype(object), _plan(n), min_group=10
    )
    assert score > 0.0


def test_oof_rejects_structureless_noise():
    rng = np.random.default_rng(3)
    n = 800
    values = rng.normal(0, 1.0, n)
    rand_key = rng.integers(0, 4, n).astype(object)
    score, _ = oof_residual_reduction(values, np.ones(n), rand_key, _plan(n), min_group=10)
    assert score <= 0.0


# ── end-to-end search_seasonality ────────────────────────────────────────────


def _series(n=24 * 40, hour_amp=30.0, noise=3.0, seed=7):
    rng = np.random.RandomState(seed)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    hours = np.array([i % 24 for i in range(n)])
    dow = np.array([(i // 24) % 7 for i in range(n)])
    vals = (100 + hour_amp * np.sin(2 * np.pi * hours / 24) + rng.normal(0, noise, n)).astype(float)
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


def _tuner(data, ts, interval=3600):
    gt = IncidentLabels([], []).to_ground_truth(ts, interval)
    settings = TuneSettings()
    t = _AutoTuneBase(
        metric_name="x",
        data=data,
        ground_truth=gt,
        interval_seconds=interval,
        settings=settings,
    )
    n = int(len(ts))
    t.cv_plan = build_cv_plan(n, 7 * 24, settings.fold_count)
    return t


def test_search_selects_hour_on_hourly_seasonal_series():
    data, ts = _series(hour_amp=30.0, noise=3.0)
    chosen = search_seasonality(_tuner(data, ts))
    assert chosen is not None
    flat = [c for comp in chosen for c in ([comp] if isinstance(comp, str) else comp)]
    assert "hour" in flat
    # day_of_week carries no signal here and must not be added.
    assert "day_of_week" not in flat


def test_search_chooses_none_on_structureless_series():
    rng = np.random.RandomState(11)
    data, ts = _series(hour_amp=0.0, noise=5.0, seed=11)
    # overwrite values with pure noise (no hour effect at all)
    data["value"] = (100 + rng.normal(0, 5.0, len(ts))).astype(float)
    assert search_seasonality(_tuner(data, ts)) is None


def test_force_seasonality_skips_search():
    # Structureless series the search would reject — force pins it anyway.
    rng = np.random.RandomState(12)
    data, ts = _series(hour_amp=0.0, noise=5.0, seed=12)
    data["value"] = (100 + rng.normal(0, 5.0, len(ts))).astype(float)
    tuner = _tuner(data, ts)
    tuner.settings.force_seasonality = ["hour"]
    assert search_seasonality(tuner) == ["hour"]


def test_force_seasonality_absent_column_falls_back_to_search():
    data, ts = _series(hour_amp=30.0, noise=3.0)
    tuner = _tuner(data, ts)
    tuner.settings.force_seasonality = ["league_day"]  # not in this series
    # Falls back to the normal search, which finds the real hour signal.
    chosen = search_seasonality(tuner)
    assert chosen is not None
    flat = [c for comp in chosen for c in ([comp] if isinstance(comp, str) else comp)]
    assert "hour" in flat
