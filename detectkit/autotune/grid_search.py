"""Stage 3: bounded coordinate search over detector hyperparameters.

Not a Cartesian product — a greedy coordinate sweep per candidate type:
threshold → recency weighting → detrend (gated by a trend test) → window size
(the final axis, with the large-window tie-bias from window_select). The
objective is the cross-validated score (settings.metric). Total evaluations
stay in the low tens per type and are capped by settings.max_candidates.
"""

from __future__ import annotations

from typing import Any

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune._types import CandidateEval
from detectkit.autotune.window_select import min_samples_for, select_window, trend_present
from detectkit.detectors.factory import DetectorFactory


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

    has_trend = trend_present(tuner)
    eps = tuner.settings.min_improvement
    best_overall: CandidateEval | None = None

    for detector_type in detector_types:
        detector_cls = DetectorFactory.DETECTOR_TYPES[detector_type]
        floor = int(getattr(detector_cls, "MIN_SAMPLES_FLOOR", 1))
        threshold_default = float(getattr(detector_cls, "THRESHOLD_DEFAULT", 3.0))
        window = _initial_window(grid, floor)
        if window is None:
            tuner.log(
                "grid_search",
                f"{detector_type}: no window in {grid} fits min-samples floor {floor}, skipped",
            )
            continue

        accepted: dict[str, Any] = {
            **base,
            "threshold": threshold_default,
            "window_size": window,
            "min_samples": min_samples_for(window, floor),
        }
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

        # Axis 2: recency weighting (only adopt if it clears the margin).
        for weights in (None, "exponential"):
            if weights == accepted.get("window_weights"):
                continue
            ev = tuner.safe_evaluate(detector_type, {**accepted, "window_weights": weights})
            if ev is not None and ev.score > best.score + eps:
                best, accepted["window_weights"] = ev, weights

        # Axis 3: detrend (gated by the trend pre-test).
        if has_trend:
            for detrend in (None, "linear"):
                if detrend == accepted.get("detrend"):
                    continue
                ev = tuner.safe_evaluate(detector_type, {**accepted, "detrend": detrend})
                if ev is not None and ev.score > best.score + eps:
                    best, accepted["detrend"] = ev, detrend

        # Axis 4: window size (final; large-window tie-bias).
        window_best = select_window(tuner, detector_type, accepted, best, grid)
        if window_best.score >= best.score - tuner.settings.window_tie_margin:
            best = window_best

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
