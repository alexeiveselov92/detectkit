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
from detectkit.detectors.factory import DetectorFactory
from detectkit.detectors.seasonality import parse_seasonality_data


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


def search_seasonality(tuner: _AutoTuneBase) -> list | None:
    """Return the chosen ``seasonality_components`` (or None for no seasonality)."""
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

    values = np.asarray(tuner.data["value"], dtype=float)
    n_valid = int(np.sum(~np.isnan(values)))
    probe = tuner.settings.probe_detector_type
    floor = int(getattr(DetectorFactory.DETECTOR_TYPES[probe], "MIN_SAMPLES_PER_GROUP_DEFAULT", 10))

    probe_window = (
        tuner.cv_plan.context_end if tuner.cv_plan and tuner.cv_plan.context_end > 0 else 100
    )
    base_params = {"window_size": probe_window, "min_samples": min(probe_window, 30)}

    baseline = tuner.evaluate(probe, base_params)
    selected: list = []
    used: set[str] = set()
    current_score = baseline.score
    tested = ["none"]
    min_improvement = tuner.settings.min_improvement

    while True:
        candidates = _candidate_moves(selected, columns, used)
        viable = [m for m in candidates if _min_group_ok(m, distinct, n_valid, floor)]
        if not viable:
            break
        best_move: list | None = None
        best_score = current_score
        for move in viable:
            ev = tuner.safe_evaluate(probe, {**base_params, "seasonality_components": move})
            if ev is None:
                continue
            if best_move is None or ev.score > best_score:
                best_move, best_score = move, ev.score
        if best_move is None:
            break
        tested.append(_fmt(best_move))
        if best_score > current_score + min_improvement:
            selected = best_move
            current_score = best_score
            used = {c for comp in selected for c in _component_cols(comp)}
        else:
            break

    if not selected:
        tuner.log(
            "seasonality",
            f"tested {', '.join(tested)} — chose none (no improvement over baseline)",
            tested=tested,
            baseline=round(baseline.score, 4),
        )
        return None

    tuner.log(
        "seasonality",
        f"chose {_fmt(selected)} (score {baseline.score:.3f} → {current_score:.3f})",
        chosen=selected,
        baseline=round(baseline.score, 4),
        score=round(current_score, 4),
    )
    return selected
