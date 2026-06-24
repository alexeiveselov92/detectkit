"""Regime-shift advisory: detect a level shift the midpoint trend test misses.

`trend_present` is a single midpoint-median test, so it silently misses a level
shift that sits off-center (both halves straddle it). `detect_level_shift` scans
every split point against the within-segment scale and catches it; the grid step
then logs a `regime` advisory. These tests pin both the probe and the end-to-end
decision-log behaviour.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from detectkit.autotune import (
    TuneSettings,
    compute_run_id,
    emit_tuned_config,
    run_autotune_engine,
)
from detectkit.autotune.labels import IncidentLabels
from detectkit.autotune.window_select import detect_level_shift, half_life_grid, trend_present
from detectkit.config.metric_config import MetricConfig


def _series(n=1600, shift_at=None, hi=100.0, lo=30.0, noise=2.0, seed=11):
    """Hourly series; below ``shift_at`` it sits at ``hi``, after it at ``lo``."""
    rng = np.random.RandomState(seed)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    base = np.full(n, lo, dtype=np.float64)
    if shift_at is not None:
        base[:shift_at] = hi
    vals = base + rng.normal(0, noise, n)
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": np.array(["{}"] * n, dtype=object),
        "seasonality_columns": [],
    }


def _stub(values):
    return SimpleNamespace(data={"value": np.asarray(values, dtype=float)})


# ── the probe itself ─────────────────────────────────────────────────────────


def test_detect_level_shift_finds_off_center_drop():
    # Drop at 15% of the series (index 240): the lower regime dominates both
    # halves, so the midpoint test reads stationary while the scan still finds it.
    data = _series(shift_at=240)
    assert trend_present(_stub(data["value"])) is False
    found, sigmas, idx = detect_level_shift(_stub(data["value"]))
    assert found is True
    assert sigmas >= 3.0
    assert 120 < idx < 400  # boundary index near the true 240


def test_detect_level_shift_silent_on_stationary_series():
    data = _series(shift_at=None)
    found, sigmas, _idx = detect_level_shift(_stub(data["value"]))
    assert found is False
    assert sigmas < 3.0


def test_detect_level_shift_silent_on_short_series():
    found, sigmas, idx = detect_level_shift(_stub([1.0, 2.0, 1.0, 2.0]))
    assert (found, sigmas, idx) == (False, 0.0, 0)


def test_detect_level_shift_is_nan_aware_and_index_aligns_with_grid():
    # Gaps (NaN) must not shift the reported boundary index off the raw grid.
    data = _series(shift_at=240)
    v = data["value"].copy()
    v[400:410] = np.nan  # a gap inside the stable lower regime
    found, _sigmas, idx = detect_level_shift(_stub(v))
    assert found is True
    assert 120 < idx < 400


def test_smooth_ramp_does_not_register_as_a_level_shift():
    # A linear ramp keeps a large within-segment spread, so no single split clears
    # the within-regime sigma bar (the probe is for steps, not drift).
    ramp = np.linspace(0.0, 100.0, 1600) + np.random.RandomState(3).normal(0, 1, 1600)
    found, _sigmas, _idx = detect_level_shift(_stub(ramp))
    assert found is False


def test_half_life_grid_is_bounded_and_floored():
    grid = half_life_grid(window_size=100, min_samples=24)
    assert grid == sorted(set(grid))  # ascending, deduped
    assert all(hl >= 2 for hl in grid)
    assert all(hl >= 24 // 2 for hl in grid)  # floored at min_samples/2
    assert max(grid) <= 100  # never exceeds the window
    assert len(grid) >= 2  # a real spread to search


def test_dominant_late_shift_is_seen_by_the_midpoint_test():
    # When one level dominates the overall median (here ~65% high), the global MAD
    # collapses to the noise floor and the half-medians differ — trend_present
    # fires, so the advisory branch is gated off (no double-reporting).
    data = _series(shift_at=int(1600 * 0.65))
    assert trend_present(_stub(data["value"])) is True


# ── end-to-end: the decision-log advisory ────────────────────────────────────


def _run(data):
    gt = IncidentLabels([], []).to_ground_truth(data["timestamp"], 3600)
    return run_autotune_engine(
        metric_name="demo",
        data=data,
        ground_truth=gt,
        interval_seconds=3600,
        settings=TuneSettings(),
    )


def test_engine_emits_regime_advisory_on_hidden_shift(tmp_path):
    result = _run(_series(shift_at=240))
    regime = [e for e in result.decision_log if e["stage"] == "regime"]
    assert len(regime) == 1
    msg = regime[0]["message"]
    assert "level shift" in msg
    # The advisory suggests a CONCRETE --from date (mapped from the shift index).
    assert re.search(r"--from \d{4}-\d{2}-\d{2}", msg)
    assert regime[0]["fields"]["shift_sigmas"] >= 3.0
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", regime[0]["fields"]["shift_at"])

    # …and it surfaces in the annotated config header.
    orig = MetricConfig(name="demo", interval="1h", query="SELECT 1")
    run_id = compute_run_id(result)
    _out, text, _rid = emit_tuned_config(
        original_config=orig,
        original_path=Path("metrics/demo.yml"),
        result=result,
        project_root=Path("."),
        run_id=run_id,
    )
    assert "# REGIME" in text


def test_engine_silent_on_stationary_series():
    result = _run(_series(shift_at=None))
    assert not [e for e in result.decision_log if e["stage"] == "regime"]


def test_engine_silent_when_midpoint_test_already_detects_the_shift():
    # trend_present fires here, so the advisory must not also fire (it would be
    # redundant — the engine already prefers a fresher window).
    result = _run(_series(shift_at=int(1600 * 0.65)))
    assert not [e for e in result.decision_log if e["stage"] == "regime"]
