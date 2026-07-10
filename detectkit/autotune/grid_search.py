"""Stage 3: bounded coordinate search over detector hyperparameters.

Not a Cartesian product — a greedy coordinate sweep per candidate type:
threshold → recency weighting → detrend (gated by a trend test) → stabilization
(anomaly-robust baseline) → window size (with the trend-gated window tie-bias
from window_select) → a final threshold re-sweep at the chosen window (the
threshold↔window coupling fix). The objective is the cross-validated score
(settings.metric, or the unsupervised objective when there are no labels).
Total evaluations stay in the low tens per type and are capped by
settings.max_candidates.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune._types import CandidateEval
from detectkit.autotune.axis_spec import axis_spec_for, resolve_floor, resolve_threshold_default
from detectkit.autotune.window_select import (
    detect_level_shift,
    half_life_grid,
    min_samples_for,
    seasonal_fill_window,
    select_window,
    trend_present,
)


def _initial_window(grid: list[int], floor: int) -> int | None:
    """Pick a mid-sized window that satisfies the detector's min-samples floor."""
    fitting = [w for w in grid if w >= floor]
    if not fitting:
        return None
    return fitting[len(fitting) // 2]


def grid_search(
    tuner: _AutoTuneBase,
    detector_types: list[str],
    seasonality: list | None,
    grid: list[int],
) -> CandidateEval | None:
    """Return the best candidate across all shortlisted detector types."""
    base: dict[str, Any] = {}
    if seasonality:
        base["seasonality_components"] = seasonality
        # Per-group stats engage only when the window holds min_samples_per_group
        # points of the current seasonal key (~min_samples_per_group * cardinality
        # points). If even the largest fold-feasible window can't reach that, the
        # chosen seasonality will silently fall back to global at runtime — flag it
        # in the decision log so the tuned config isn't trusted to be seasonal.
        fill = seasonal_fill_window(tuner)
        if fill and grid and max(grid) < fill:
            tuner.log(
                "window",
                f"seasonality {seasonality} needs window_size >= {fill} to engage per-group "
                f"stats, but the fold budget caps the window at {max(grid)} on this history "
                "— the band will use global statistics (seasonality has no effect). Tune on "
                "more history, or use `dtk tune` to set a larger window manually.",
                seasonal_fill_window=fill,
            )

    has_trend = trend_present(tuner)
    if not has_trend:
        # The trend gate is a single midpoint-median test, so it silently misses a
        # level shift that sits off-center (both halves straddle it) or one big
        # enough to inflate the global MAD it is measured against. When that
        # happens the engine treats the series as stationary — prefers the largest
        # window, skips detrend — and the baseline quietly averages two regimes.
        # Surface it (with a concrete --from date) so the user can narrow the
        # window and re-tune; advisory only.
        found, sigmas, idx = detect_level_shift(tuner)
        if found:
            timestamps = tuner.data["timestamp"]
            n = int(len(timestamps))
            from_date = str(np.datetime64(timestamps[idx], "D"))
            pct = round(idx / n * 100) if n else 0
            tuner.log(
                "regime",
                f"series reads stationary, but a large level shift (~{sigmas:.1f}σ "
                f"within-regime) sits ~{pct}% in, around {from_date} — the midpoint "
                "trend test misses an off-center shift, so the baseline may average "
                f"two regimes. If the earlier regime is stale, re-tune with "
                f"`--from {from_date}` (or set `autotune.max_history`).",
                shift_sigmas=round(sigmas, 2),
                shift_at=from_date,
            )
    eps = tuner.settings.min_improvement
    best_overall: CandidateEval | None = None

    for detector_type in detector_types:
        spec = axis_spec_for(detector_type)
        floor = resolve_floor(detector_type)
        threshold_default = resolve_threshold_default(detector_type)
        window = _initial_window(grid, floor)
        if window is None:
            tuner.log(
                "grid_search",
                f"{detector_type}: no window in {grid} fits min-samples floor {floor}, skipped",
            )
            continue

        accepted: dict[str, Any] = {
            **(base if spec.seasonality else {}),
            **spec.initial,
            "threshold": threshold_default,
            "window_size": window,
        }
        accepted["min_samples"] = min_samples_for(window, floor, accepted.get("lags"))
        best = tuner.safe_evaluate(detector_type, accepted)
        if best is None:
            continue

        # Axis 1: threshold (strict improvement).
        for threshold in tuner.settings.threshold_grid(detector_type):
            if threshold == accepted["threshold"]:
                continue
            ev = tuner.safe_evaluate(detector_type, {**accepted, "threshold": threshold})
            if ev is not None and ev.score > best.score:
                best, accepted["threshold"] = ev, threshold

        # Axis 1b: AR order (autoreg only) — swept like threshold, with the
        # min-samples floor tracking lags + 2 (the detector validates that).
        if spec.lags:
            for lags in tuner.settings.lags_grid:
                if lags == accepted.get("lags"):
                    continue
                candidate = {
                    **accepted,
                    "lags": lags,
                    "min_samples": min_samples_for(accepted["window_size"], floor, lags),
                }
                ev = tuner.safe_evaluate(detector_type, candidate)
                if ev is not None and ev.score > best.score:
                    best = ev
                    accepted["lags"] = lags
                    accepted["min_samples"] = candidate["min_samples"]

        # Axis 2: recency weighting (only adopt if it clears the margin).
        if spec.weighting:
            for weights in (None, "exponential"):
                if weights == accepted.get("window_weights"):
                    continue
                ev = tuner.safe_evaluate(detector_type, {**accepted, "window_weights": weights})
                if ev is not None and ev.score > best.score + eps:
                    best, accepted["window_weights"] = ev, weights

            # Axis 2b: half-life of the recency weighting — only when exponential
            # weighting was adopted. The detector defaults to a fixed half-life;
            # this lets the search pick a faster-forgetting baseline that tracks
            # the current regime (the term that matters on a metric that shifted
            # level).
            if accepted.get("window_weights") == "exponential":
                for half_life in half_life_grid(accepted["window_size"], accepted["min_samples"]):
                    if half_life == accepted.get("half_life"):
                        continue
                    ev = tuner.safe_evaluate(detector_type, {**accepted, "half_life": half_life})
                    if ev is not None and ev.score > best.score + eps:
                        best, accepted["half_life"] = ev, half_life

        # Axis 3: detrend (gated by the trend pre-test).
        if spec.detrend and has_trend:
            for detrend in (None, "linear"):
                if detrend == accepted.get("detrend"):
                    continue
                ev = tuner.safe_evaluate(detector_type, {**accepted, "detrend": detrend})
                if ev is not None and ev.score > best.score + eps:
                    best, accepted["detrend"] = ev, detrend

        # Axis 3b: stabilization (anomaly-robust baseline; adopt only when it
        # clears the margin). Flagged points enter subsequent windows clamped
        # to the bound they violated, so a sustained incident cannot inflate
        # the band and mask its own tail — usually decisive on labeled data
        # with long incidents, near-neutral on clean series. Swept before the
        # window axis so select_window evaluates with the adopted baseline.
        if spec.stabilization:
            for stabilization in (None, "clamp"):
                if stabilization == accepted.get("stabilization"):
                    continue
                ev = tuner.safe_evaluate(
                    detector_type, {**accepted, "stabilization": stabilization}
                )
                if ev is not None and ev.score > best.score + eps:
                    best, accepted["stabilization"] = ev, stabilization

        # Axis 4: window size (large-window tie-bias, trend-gated in select_window).
        window_best = select_window(tuner, detector_type, accepted, best, grid)
        if window_best.score >= best.score - tuner.settings.window_tie_margin:
            best = window_best

        # Axis 5: re-sweep threshold at the now-fixed window. The optimal threshold
        # depends on window size (a longer window gives a steadier spread estimate),
        # but threshold was chosen first against the seed window — without this pass
        # a large window swing can leave it stranded. Strict improvement only.
        accepted = dict(best.params)
        for threshold in tuner.settings.threshold_grid(detector_type):
            if threshold == accepted.get("threshold"):
                continue
            ev = tuner.safe_evaluate(detector_type, {**accepted, "threshold": threshold})
            if ev is not None and ev.score > best.score:
                best = ev
                accepted["threshold"] = threshold

        tuner.log(
            "grid_search",
            f"{detector_type}: best score {best.score:.3f} "
            f"(threshold={best.params.get('threshold')}, "
            f"window_size={best.params.get('window_size')})",
            detector_type=detector_type,
            score=round(best.score, 4),
        )

        if best_overall is None or best.score > best_overall.score:
            best_overall = best

        if len(tuner.evaluated_ids()) >= tuner.settings.max_candidates:
            tuner.log("grid_search", f"reached max_candidates={tuner.settings.max_candidates}")
            break

    return best_overall
