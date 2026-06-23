"""Stage 1: greedily build the optimal seasonality grouping.

Uses a cheap robust probe detector (MAD with defaults) to score candidate
seasonality groupings via the same cross-validation as the real search.
At each step it can either add a new column as its own component or merge a
column into the last component (forming a conjunctive group like
``["day_of_week", "hour"]``), accepting a move only if it beats the current
grouping by a margin and never fragmenting a component below the
per-group minimum.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune.scoring import oof_residual_reduction
from detectkit.detectors.factory import DetectorFactory
from detectkit.detectors.seasonality import parse_seasonality_data

# Sentinel key for points whose seasonality payload is missing a required column;
# they form a degenerate group that falls back to the global stats (matching the
# detector's all-True/global degrade).
_NA_KEY = "__dtk_na__"
# Center estimator per probe family, so the residual criterion matches the
# statistic the chosen detector actually consumes (median for MAD/IQR, mean for
# Z-Score). Kept off the detector classes on purpose (see detector_select).
_PROBE_CENTER = {"mad": "median", "iqr": "median", "zscore": "mean"}


def _distinct_count(arr: np.ndarray) -> int:
    return len({v for v in arr.tolist() if v is not None})


def _component_cols(component: Any) -> list[str]:
    return [component] if isinstance(component, str) else list(component)


def _fmt(components: list) -> str:
    parts = []
    for comp in components:
        cols = _component_cols(comp)
        parts.append("[" + "+".join(cols) + "]" if len(cols) > 1 else cols[0])
    return ", ".join(parts) if parts else "none"


def _candidate_moves(selected: list, columns: list[str], used: set[str]) -> list[list]:
    moves: list[list] = []
    for c in columns:
        if c in used:
            continue
        moves.append([*selected, c])  # add as its own component
        if selected:
            last_cols = _component_cols(selected[-1])
            moves.append([*selected[:-1], [*last_cols, c]])  # merge into last
    return moves


def _min_group_ok(move: list, distinct: dict[str, int], n_valid: int, floor: int) -> bool:
    """Reject a grouping that would shrink any component's groups below *floor*."""
    for comp in move:
        product = 1
        for c in _component_cols(comp):
            product *= max(1, distinct.get(c, 1))
        if n_valid / product < floor:
            return False
    return True


def _composite_keys(season: dict[str, np.ndarray], components: list | None, n: int) -> np.ndarray:
    """Per-point composite group key for *components* (one global group when None).

    Mirrors the detector's conjunctive AND-mask: a point's key is the tuple of its
    values across every column in every component. Any point missing a required
    column value gets the ``_NA_KEY`` sentinel so it falls back to global stats.
    """
    if not components:
        return np.zeros(n, dtype=np.int64)
    cols = [c for comp in components for c in _component_cols(comp)]
    arrs = [season[c] for c in cols]
    keys = np.empty(n, dtype=object)
    for i in range(n):
        parts = tuple(a[i] for a in arrs)
        keys[i] = _NA_KEY if any(p is None for p in parts) else parts
    return keys


def search_seasonality(tuner: _AutoTuneBase) -> list | None:
    """Return the chosen ``seasonality_components`` (or None for no seasonality)."""
    forced = tuner.settings.force_seasonality
    if forced:
        available = set(tuner.data.get("seasonality_columns", []))
        cols = [c for comp in forced for c in _component_cols(comp)]
        missing = [c for c in cols if c not in available]
        if missing:
            tuner.log(
                "seasonality",
                f"force_seasonality columns absent from data: {missing} — searching instead",
            )
        else:
            tuner.log(
                "seasonality",
                f"forced seasonality {_fmt(list(forced))} (search skipped)",
                chosen=list(forced),
                forced=True,
            )
            return list(forced)

    columns = [c for c in tuner.data.get("seasonality_columns", []) if c != "is_holiday"]
    allowed = tuner.settings.allowed_seasonality
    if allowed:
        columns = [c for c in columns if c in allowed]
    if not columns:
        tuner.log("seasonality", "no seasonality columns available — using none")
        return None

    season = parse_seasonality_data(tuner.data.get("seasonality_data", np.array([])), columns)
    distinct = {c: _distinct_count(season[c]) for c in columns if c in season}
    columns = [c for c in columns if distinct.get(c, 0) > 1]  # drop constant columns
    if not columns:
        tuner.log("seasonality", "no informative seasonality columns — using none")
        return None

    if tuner.cv_plan is None:
        tuner.log("seasonality", "no CV plan available — using none")
        return None

    values = np.asarray(tuner.data["value"], dtype=float)
    n = len(values)
    n_valid = int(np.sum(~np.isnan(values)))
    weights = np.ones(n, dtype=float)
    probe = tuner.settings.probe_detector_type
    floor = int(getattr(DetectorFactory.DETECTOR_TYPES[probe], "MIN_SAMPLES_PER_GROUP_DEFAULT", 10))
    center = _PROBE_CENTER.get(probe, "median")
    cv_plan = tuner.cv_plan

    def _score(components: list | None) -> tuple[float, float]:
        """Held-out residual reduction + fraction of folds that improved."""
        keys = _composite_keys(season, components, n)
        score, per_fold = oof_residual_reduction(
            values,
            weights,
            keys,
            cv_plan,
            center=center,
            min_group=floor,
            stability_lambda=tuner.settings.stability_lambda,
        )
        improved = float(np.mean([r > 0 for r in per_fold])) if per_fold else 0.0
        return score, improved

    # Baseline (no seasonality) scores exactly 0 by construction.
    selected: list = []
    used: set[str] = set()
    current_score = 0.0
    min_improvement = tuner.settings.min_improvement
    tested = ["none"]
    per_candidate: list[dict] = []

    while True:
        candidates = _candidate_moves(selected, columns, used)
        viable = [m for m in candidates if _min_group_ok(m, distinct, n_valid, floor)]
        if not viable:
            break
        best_move: list | None = None
        best_score = current_score
        best_improved = 0.0
        for move in viable:
            score, improved = _score(move)
            per_candidate.append(
                {
                    "components": _fmt(move),
                    "residual_reduction": round(score, 4),
                    "folds_improved": round(improved, 2),
                }
            )
            if best_move is None or score > best_score:
                best_move, best_score, best_improved = move, score, improved
        if best_move is None:
            break
        tested.append(_fmt(best_move))
        # Accept only a generalizing improvement that helps in the majority of folds.
        if best_score > current_score + min_improvement and best_improved >= 0.5:
            selected = best_move
            current_score = best_score
            used = {c for comp in selected for c in _component_cols(comp)}
        else:
            break

    # Compact per-candidate summary (component:residual_reduction) for the
    # decision log + emitted config header, so a rejection is never opaque.
    tried = ", ".join(f"{c['components']}:{c['residual_reduction']}" for c in per_candidate[:6])

    if not selected:
        tuner.log(
            "seasonality",
            f"tested {', '.join(tested)} — chose none "
            f"(no held-out residual reduction over baseline; tried {tried})",
            tested=tested,
            baseline=0.0,
            per_candidate=per_candidate,
        )
        return None

    tuner.log(
        "seasonality",
        f"chose {_fmt(selected)} "
        f"(held-out residual reduction {current_score:.3f} vs baseline 0.000; tried {tried})",
        chosen=selected,
        baseline=0.0,
        score=round(current_score, 4),
        per_candidate=per_candidate,
    )
    return selected
