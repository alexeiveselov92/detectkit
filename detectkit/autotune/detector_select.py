"""Stage 2: order the candidate detector types by distribution suitability.

The "decision tree" is a small suitability spec keyed by detector *type name*
(kept here, not on the detector classes, so existing detectors stay untouched
and the whole feature is easy to remove). Each seasonality group votes for the
type that best fits its distribution. The vote is **advisory only** — it ranks
the types (most promising first) for the grid search, which then evaluates *all*
of them and lets the cross-validated objective pick the winner. A hand-tuned
heuristic therefore never excludes a type; it only decides who is tried first
(and is recorded in the decision log for transparency).
"""

from __future__ import annotations

import numpy as np

from detectkit.autotune._base import _AutoTuneBase
from detectkit.autotune._types import GroupVote
from detectkit.autotune.distribution import compute_distribution_features
from detectkit.detectors.factory import DetectorFactory
from detectkit.detectors.seasonality import parse_seasonality_data

# Detector types the engine can auto-tune. Derived from the factory minus the
# manual/stateless ones; the prediction-based "autoreg" participates via its
# AxisSpec (see autotune/axis_spec.py), which gates the windowed-only axes.
_EXCLUDED_TYPES = {"manual", "manual_bounds"}
# A seasonal sub-group needs at least this many points to vote.
_MIN_GROUP_FOR_VOTE = 10
# Cap on voting sub-groups so a high-cardinality component can't explode cost.
_MAX_VOTING_GROUPS = 12


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def detector_suitability(detector_type: str, features: dict[str, float]) -> float:
    """How well *detector_type* fits a distribution, in ``[0, 1]``.

    Unknown/future types default to a neutral 0.5 so they still participate.
    """
    normality = features["normality"]
    heavy_tail_ratio = features["heavy_tail_ratio"]
    outlier_fraction = features["outlier_fraction"]
    skewness = abs(features["skewness"])

    if detector_type == "zscore":
        # Best on clean, light-tailed, low-outlier data.
        return _clip01(normality * _clip01(heavy_tail_ratio) * (1.0 - outlier_fraction))
    if detector_type == "mad":
        # Robust baseline; boosted by heavy tails / outliers.
        heavy = max(0.0, 1.0 - heavy_tail_ratio)  # >0 when heavy-tailed
        return _clip01(0.6 + 0.4 * heavy + 0.5 * outlier_fraction)
    if detector_type == "iqr":
        # Best on skewed / asymmetric distributions.
        return _clip01(0.3 + 0.5 * min(1.0, skewness / 3.0) + 0.4 * outlier_fraction)
    if detector_type == "autoreg":
        # Prediction-based: models short-range dynamics, not level, and the
        # distribution shape says little about dynamics — so the vote is
        # mildly conservative (clean data, where a per-window AR fit is
        # stable, nudges it up; it never outranks a clearly-matched level
        # detector). Ordering only; the grid search still evaluates it.
        return _clip01(0.3 + 0.3 * normality * (1.0 - outlier_fraction))
    return 0.5


def _candidate_types(tuner: _AutoTuneBase) -> list[str]:
    universe = [t for t in DetectorFactory.DETECTOR_TYPES if t not in _EXCLUDED_TYPES]
    allowed = tuner.settings.allowed_detector_types
    if allowed:
        universe = [t for t in universe if t in allowed]
    return sorted(set(universe))


def _voting_groups(
    tuner: _AutoTuneBase,
    seasonality: list | None,
) -> list[tuple[str, np.ndarray]]:
    """Return ``(label, values)`` slices: the global group + seasonal sub-groups."""
    values = np.asarray(tuner.data["value"], dtype=float)
    valid = ~np.isnan(values)
    groups: list[tuple[str, np.ndarray]] = [("global", values[valid])]

    if not seasonality:
        return groups

    all_cols = sorted(
        {c for comp in seasonality for c in ([comp] if isinstance(comp, str) else comp)}
    )
    season = parse_seasonality_data(tuner.data.get("seasonality_data", np.array([])), all_cols)
    if not season:
        return groups

    sub: list[tuple[int, str, np.ndarray]] = []
    for comp in seasonality:
        cols = [comp] if isinstance(comp, str) else comp
        if any(c not in season for c in cols):
            continue
        # Build a combo key per row, then group rows by combo.
        n = len(values)
        keys: dict[tuple, list[int]] = {}
        for i in range(n):
            if not valid[i]:
                continue
            key = tuple(season[c][i] for c in cols)
            if any(part is None for part in key):
                continue
            keys.setdefault(key, []).append(i)
        for key, idxs in keys.items():
            if len(idxs) >= _MIN_GROUP_FOR_VOTE:
                gv = values[np.asarray(idxs, dtype=np.int64)]
                label = "+".join(cols) + "=" + "/".join(str(k) for k in key)
                sub.append((len(idxs), label, gv))

    sub.sort(key=lambda t: t[0], reverse=True)
    for _size, label, gv in sub[:_MAX_VOTING_GROUPS]:
        groups.append((label, gv))
    return groups


def select_detector_types(
    tuner: _AutoTuneBase,
    seasonality: list | None,
) -> list[str]:
    """Vote across groups; return the candidate detector type(s) to grid-search."""
    candidate_types = _candidate_types(tuner)
    if not candidate_types:
        raise ValueError("no tunable detector types available")

    groups = _voting_groups(tuner, seasonality)
    votes: dict[str, float] = dict.fromkeys(candidate_types, 0.0)
    total_suit: dict[str, float] = dict.fromkeys(candidate_types, 0.0)
    global_winner = candidate_types[0]

    for label, values in groups:
        features = compute_distribution_features(values)
        ranked = sorted(
            ((t, detector_suitability(t, features)) for t in candidate_types),
            key=lambda x: x[1],
            reverse=True,
        )
        tuner.group_votes.append(GroupVote(group=[label], features=features, ranked_types=ranked))
        for t, s in ranked:
            total_suit[t] += s
        top_score = ranked[0][1]
        winners = [t for t, s in ranked if s >= top_score - 1e-9]
        share = 1.0 / len(winners)
        for t in winners:
            votes[t] += share
        if label == "global":
            global_winner = ranked[0][0]

    # Evaluate ALL candidate types in the grid search and let the cross-validated
    # objective pick the winner — the suitability vote only ORDERS them (most
    # promising first) and is logged for transparency; it never excludes a type,
    # so a hand-tuned heuristic can't drop the detector that would have scored
    # best. The cap is a pure cost backstop (default ≥ the number of detectors).
    final = sorted(candidate_types, key=lambda t: total_suit[t], reverse=True)
    final = final[: tuner.settings.max_candidate_types]
    if global_winner not in final:
        final.append(global_winner)

    tally = ", ".join(f"{t}:{votes[t]:.1f}" for t in candidate_types)
    tuner.log(
        "detector_select",
        f"suitability votes — {tally}; evaluating (best-first): {', '.join(final)}",
        votes=votes,
        shortlist=final,
        n_groups=len(groups),
    )
    return final
