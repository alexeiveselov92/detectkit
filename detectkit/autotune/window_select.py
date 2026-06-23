"""Stage 4: history-window selection.

Evaluate a small grid of window sizes expressed in natural seasonal units, and
among windows whose score is within a tie margin of the best, break the tie on
the trend pre-test: when the series is stationary prefer the *largest* window
(more context → steadier statistics); when a trend / regime shift is present
prefer the *smallest* (a fresher baseline that tracks the current level rather
than averaging in stale history). Also exposes the trend pre-test that gates the
detrend toggle in the grid search.
"""

from __future__ import annotations

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune._types import CandidateEval
from detectkit.detectors.factory import DetectorFactory


def min_samples_for(window_size: int, floor: int) -> int:
    """Derived min_samples: a quarter of the window, clamped to ``[floor, window]``."""
    return min(window_size, max(floor, round(window_size / 4)))


def window_grid(tuner: _AutoTuneBase) -> list[int]:
    """Candidate window sizes (≈1 day, ≈1 week, default 100), clamped to fit folds."""
    fixed = tuner.settings.fixed_params.get("window_size")
    if isinstance(fixed, int):
        return [fixed]

    n = int(len(tuner.data["timestamp"]))
    fold_count = tuner.settings.fold_count
    cap = max(20, n // (fold_count + 1))
    pts_per_day = max(1, round(86400 / tuner.interval_seconds))
    candidates = {100, pts_per_day, 7 * pts_per_day}
    grid = sorted({w for w in candidates if 20 <= w <= cap})
    if not grid:
        grid = [max(2, min(cap, 100))]
    return grid


def trend_present(tuner: _AutoTuneBase) -> bool:
    """Cheap robust trend test: is the second half's median materially shifted?"""
    v = np.asarray(tuner.data["value"], dtype=float)
    v = v[~np.isnan(v)]
    if v.size < 8:
        return False
    half = v.size // 2
    med_first = float(np.median(v[:half]))
    med_second = float(np.median(v[half:]))
    mad = float(np.median(np.abs(v - np.median(v))))
    if mad <= 0:
        return abs(med_second - med_first) > 0
    return abs(med_second - med_first) > 2.0 * 1.4826 * mad


def select_window(
    tuner: _AutoTuneBase,
    detector_type: str,
    accepted: dict,
    current_best: CandidateEval,
    grid: list[int],
) -> CandidateEval:
    """Sweep the window grid (final axis); return the tie-biased-largest winner."""
    floor = int(getattr(DetectorFactory.DETECTOR_TYPES[detector_type], "MIN_SAMPLES_FLOOR", 1))
    evals: list[tuple[int, CandidateEval]] = []
    for w in grid:
        if w < floor:
            continue
        candidate = {**accepted, "window_size": w, "min_samples": min_samples_for(w, floor)}
        ev = tuner.safe_evaluate(detector_type, candidate)
        if ev is not None:
            evals.append((w, ev))
    if not evals:
        return current_best

    best_score = max(ev.score for _w, ev in evals)
    margin = tuner.settings.window_tie_margin
    within = [(w, ev) for w, ev in evals if ev.score >= best_score - margin]
    if trend_present(tuner):
        # Regime shift / trend present: prefer a SHORTER window so the baseline
        # tracks the current level instead of averaging in stale pre-shift history.
        _w_chosen, ev_chosen = min(within, key=lambda item: item[0])
    else:
        # Stationary: "more history is better" — prefer the LARGER window.
        _w_chosen, ev_chosen = max(within, key=lambda item: item[0])
    return ev_chosen
