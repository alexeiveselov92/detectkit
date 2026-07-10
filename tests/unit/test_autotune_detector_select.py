"""Detector-selection tests: suitability routing + non-exclusion guarantee.

The suitability spec is hand-tuned, so these lock its routing on canonical
synthetic distributions; and they assert the stage never *excludes* a type
(all windowed statistical detectors must reach the grid search).
"""

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune.detector_select import detector_suitability, select_detector_types
from detectkit.autotune.distribution import compute_distribution_features
from detectkit.autotune.labels import IncidentLabels
from detectkit.autotune.settings import TuneSettings

_STAT_TYPES = {
    "mad",
    "zscore",
    "iqr",
    "autoreg",
}  # every tunable type (incl. autoreg since #97 Phase 2)


def _feat(values):
    return compute_distribution_features(np.asarray(values, dtype=float))


def test_suitability_clean_normal_prefers_zscore():
    f = _feat(np.random.RandomState(0).normal(0, 1, 2000))
    assert detector_suitability("zscore", f) > detector_suitability("mad", f)


def test_suitability_heavy_tailed_prefers_mad():
    rng = np.random.RandomState(1)
    heavy = np.concatenate([rng.normal(0, 1, 2000), rng.standard_t(2, 200) * 5])
    f = _feat(heavy)
    assert detector_suitability("mad", f) > detector_suitability("zscore", f)


def test_suitability_contaminated_prefers_mad():
    rng = np.random.RandomState(2)
    contaminated = np.concatenate([rng.normal(0, 1, 2000), rng.normal(0, 1, 100) * 20])
    f = _feat(contaminated)
    assert detector_suitability("mad", f) > detector_suitability("zscore", f)


def test_suitability_skewed_lognormal_boosts_iqr_over_zscore():
    f = _feat(np.random.RandomState(3).lognormal(0, 1.0, 3000))
    assert detector_suitability("iqr", f) > detector_suitability("zscore", f)


def test_unknown_type_is_neutral():
    f = _feat(np.random.RandomState(4).normal(0, 1, 500))
    assert detector_suitability("future_detector", f) == 0.5


# ── non-exclusion: all statistical types reach the grid search ────────────────


def _tuner(values):
    values = np.asarray(values, dtype=float)
    n = len(values)
    ts = (
        np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n) * np.timedelta64(1, "h")
    ).astype("datetime64[ms]")
    data = {
        "value": values,
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }
    gt = IncidentLabels([], []).to_ground_truth(ts, 3600)
    return _AutoTuneBase(
        metric_name="x", data=data, ground_truth=gt, interval_seconds=3600, settings=TuneSettings()
    )


def test_select_evaluates_all_types_ordered_by_suitability():
    clean = np.random.RandomState(5).normal(0, 1, 2000)
    chosen = select_detector_types(_tuner(clean), None)
    # Non-exclusion: every windowed statistical detector is evaluated.
    assert set(chosen) == _STAT_TYPES
    # Ordering: the global-distribution best (zscore on clean normal) is tried first.
    assert chosen[0] == "zscore"


def test_select_orders_mad_first_on_heavy_tails():
    rng = np.random.RandomState(6)
    heavy = np.concatenate([rng.normal(0, 1, 2000), rng.standard_t(2, 200) * 6])
    chosen = select_detector_types(_tuner(heavy), None)
    assert set(chosen) == _STAT_TYPES
    assert chosen.index("mad") < chosen.index("zscore")
