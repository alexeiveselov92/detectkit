"""Window-grid seasonality-fill: ensure autotune offers a window large enough
for the chosen seasonality to actually engage.

Per-group statistics only engage when the trailing window holds
``min_samples_per_group`` points sharing the current point's seasonal key, which
recur every *cardinality* grid positions. None of the natural-unit candidates
(≈1 day, ≈1 week) reach that for hourly ``hour_of_day`` data (24 keys → 240), so
without an explicit fill candidate a chosen seasonality silently never engages at
the tuned window. These tests pin that the grid includes the fill window when the
fold budget allows it (and that the fill size is computed from the data).
"""

import json
from types import SimpleNamespace

import numpy as np

from detectkit.autotune.window_select import (
    max_seasonal_cardinality,
    seasonal_fill_window,
    window_grid,
)


def _hourly_tuner(n, *, fold_count=5, seasonal=True):
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    if seasonal:
        hours = np.arange(n) % 24
        season = np.array([json.dumps({"hour_of_day": int(h)}) for h in hours], dtype=object)
        cols = ["hour_of_day"]
    else:
        season = np.array(["{}"] * n, dtype=object)
        cols = []
    return SimpleNamespace(
        settings=SimpleNamespace(fixed_params={}, fold_count=fold_count),
        data={"timestamp": ts, "seasonality_data": season, "seasonality_columns": cols},
        interval_seconds=3600,
    )


def test_cardinality_and_fill_window_from_hourly_hour_of_day():
    tuner = _hourly_tuner(3000)
    assert max_seasonal_cardinality(tuner) == 24
    assert seasonal_fill_window(tuner) == 240  # min_samples_per_group(10) * 24


def test_window_grid_includes_seasonal_fill_when_budget_allows():
    # n=3000, fold cap = 3000 // 6 = 500 >= 240, so the fill window fits.
    tuner = _hourly_tuner(3000)
    grid = window_grid(tuner)
    assert 240 in grid, f"seasonal fill window must be offered, got {grid}"


def test_window_grid_omits_fill_window_when_history_too_short():
    # n=600, fold cap = 600 // 6 = 100 < 240, so the fill window can't fit; the
    # grid stays within budget (grid_search logs the under-fill advisory instead).
    tuner = _hourly_tuner(600)
    grid = window_grid(tuner)
    assert 240 not in grid
    assert max(grid) <= 100
    # The fill size itself is still reported (used for the advisory).
    assert seasonal_fill_window(tuner) == 240


def test_no_seasonality_means_no_fill_window():
    tuner = _hourly_tuner(3000, seasonal=False)
    assert max_seasonal_cardinality(tuner) == 0
    assert seasonal_fill_window(tuner) == 0
    assert window_grid(tuner) == [24, 100, 168]  # 1d, default, 1w (all <= cap 500)
