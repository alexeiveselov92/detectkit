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
from detectkit.detectors.seasonality import parse_seasonality_data
from detectkit.detectors.statistical._windowed import WindowedStatDetector

# Reference per-group floor used to size a seasonality-fill window candidate. The
# windowed detectors share this default (MAD 10 is the largest); using it makes
# the fill window cover every windowed type so cross-validation can actually
# discover whether conditioning on a seasonal key helps. See
# ``seasonal_fill_window``.
_MSPG_REF = int(WindowedStatDetector.MIN_SAMPLES_PER_GROUP_DEFAULT)


def min_samples_for(window_size: int, floor: int) -> int:
    """Derived min_samples: a quarter of the window, clamped to ``[floor, window]``."""
    return min(window_size, max(floor, round(window_size / 4)))


def max_seasonal_cardinality(tuner: _AutoTuneBase) -> int:
    """Largest distinct-key count among the available single seasonality columns.

    Per-group statistics only engage once the window holds
    ``min_samples_per_group`` points sharing the current point's key, and same-key
    points recur every *cardinality* grid positions — so this is the recurrence
    period the window must cover. We use the most granular single column (e.g.
    ``hour_of_day`` → 24) as the representative key; conjunctive groupings are
    rarer and are backstopped by the detector's runtime under-fill warning.
    Returns 0 when no seasonality columns are present.
    """
    columns = [c for c in tuner.data.get("seasonality_columns", []) if c != "is_holiday"]
    if not columns:
        return 0
    season = parse_seasonality_data(tuner.data.get("seasonality_data", np.array([])), columns)
    card = 0
    for col in columns:
        vals = season.get(col)
        if vals is None or len(vals) == 0:
            continue
        distinct = {v for v in vals.tolist() if v is not None}
        card = max(card, len(distinct))
    return card


def seasonal_fill_window(tuner: _AutoTuneBase) -> int:
    """Smallest window that can fill a single-column seasonal group, else 0.

    ``min_samples_per_group * cardinality``. None of the natural-unit candidates
    (≈1 day, ≈1 week) reach this for hourly ``hour_of_day`` data (24 keys → 240),
    so without this the chosen seasonality silently never engages at the tuned
    window. Returns 0 when there is no seasonality to fill.
    """
    card = max_seasonal_cardinality(tuner)
    return _MSPG_REF * card if card > 0 else 0


def window_grid(tuner: _AutoTuneBase) -> list[int]:
    """Candidate window sizes (≈1 day, ≈1 week, default 100), clamped to fit folds.

    When the data carries seasonality columns, also offer a window large enough to
    fill the most granular seasonal group (``min_samples_per_group * cardinality``)
    so that — if seasonality is chosen downstream — cross-validation can evaluate a
    window where the per-group band actually engages instead of silently falling
    back to global statistics. Capped (like the other candidates) so it never
    exceeds the fold budget; if it doesn't fit, seasonality simply can't fill on
    this much history and the detector's runtime warning will say so.
    """
    fixed = tuner.settings.fixed_params.get("window_size")
    if isinstance(fixed, int):
        return [fixed]

    n = int(len(tuner.data["timestamp"]))
    fold_count = tuner.settings.fold_count
    cap = max(20, n // (fold_count + 1))
    pts_per_day = max(1, round(86400 / tuner.interval_seconds))
    candidates = {100, pts_per_day, 7 * pts_per_day}
    fill = seasonal_fill_window(tuner)
    if fill:
        candidates.add(fill)
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


# A level shift is "large" when the two regimes' centers differ by at least this
# many within-regime robust sigmas. Measured against the *within-segment* scale
# (not the global MAD) so a big step can't self-mask by inflating the yardstick.
_SHIFT_SIGMA_BAR = 3.0
_SHIFT_MIN_POINTS = 32  # too few points to meaningfully talk about two regimes
_SHIFT_MIN_SIDE_FRAC = 0.1  # each candidate segment must hold ≥10% of the points
_SHIFT_SCAN_SPLITS = 24  # coarse grid of candidate split points to scan


def detect_level_shift(tuner: _AutoTuneBase) -> tuple[bool, float, int]:
    """Scan for the strongest single level shift anywhere in the series.

    Complements :func:`trend_present`, which only compares the two *halves'*
    medians against the *global* MAD and so misses a shift that (a) sits
    off-center — both halves then straddle it — or (b) self-masks by inflating the
    global MAD it is measured against. This scans candidate split points across
    the series and scores each step against the **within-segment** robust scale,
    which a true step does not inflate (a smooth ramp, by contrast, keeps a large
    within-segment spread and so does not register). Returns ``(found,
    magnitude_sigmas, boundary_index)`` where ``boundary_index`` is the index of
    the **first point of the new regime** in ``tuner.data`` (so the caller can map
    it to a timestamp for a concrete ``--from`` suggestion). The scan runs on the
    raw grid (NaN-aware medians) so the index aligns with ``timestamp``. ``found``
    is ``True`` only when the strongest step clears :data:`_SHIFT_SIGMA_BAR`
    within-regime sigmas.
    """
    v = np.asarray(tuner.data["value"], dtype=float)
    n = int(v.size)
    min_side = max(4, int(n * _SHIFT_MIN_SIDE_FRAC))
    if n < _SHIFT_MIN_POINTS or n - 2 * min_side < 1:
        return (False, 0.0, 0)
    step = max(1, (n - 2 * min_side) // _SHIFT_SCAN_SPLITS)
    best_sigmas = 0.0
    best_idx = 0
    for s in range(min_side, n - min_side + 1, step):
        left, right = v[:s], v[s:]
        if np.isnan(left).all() or np.isnan(right).all():
            continue
        med_l = float(np.nanmedian(left))
        med_r = float(np.nanmedian(right))
        delta = abs(med_r - med_l)
        if delta <= 0:
            continue
        within = float(np.nanmedian(np.abs(np.concatenate([left - med_l, right - med_r]))))
        sigmas = delta / (1.4826 * within) if within > 0 else 99.0
        if sigmas > best_sigmas:
            best_sigmas, best_idx = sigmas, s
    return (best_sigmas >= _SHIFT_SIGMA_BAR, min(best_sigmas, 99.0), best_idx)


def half_life_grid(window_size: int, min_samples: int) -> list[int]:
    """Candidate half-lives (in points) for the recency-weighting sweep.

    Spaced as fractions of the window so the search can trade a fast-forgetting
    baseline (small half-life → tracks the current regime, good after a shift)
    against a steady one. Floored at ``min_samples / 2`` to keep the weighted
    effective sample size from collapsing into a noisy band.
    """
    floor = max(2, min_samples // 2)
    cands = {round(window_size * f) for f in (0.05, 0.1, 0.25, 0.5)}
    return sorted({max(floor, c) for c in cands if c >= 2})


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
