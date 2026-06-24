"""Walk-forward (expanding-window) cross-validation over one loaded series.

The windowed detectors are *causal* — a point's verdict at index ``i`` depends
only on the trailing window ``data[:i]``. So scoring is exact and cheap: run
``detect`` once over the whole series, then score each contiguous fold by
slicing its results. This is identical to train-on-prior / score-on-fold but
removes the ``x folds`` cost, and never leaks future points.
"""

from __future__ import annotations

import numpy as np

from detectkit.autotune._types import CVPlan, FoldScores, TuneMode
from detectkit.autotune.labels import GroundTruth
from detectkit.autotune.scoring import score_predictions, unsupervised_objective
from detectkit.autotune.settings import TuneSettings
from detectkit.detectors.base import BaseDetector, DetectionResult


def build_cv_plan(n_points: int, context_size: int, fold_count: int) -> CVPlan:
    """Reserve ``context_size`` lead-in points, split the rest into folds."""
    context_end = min(max(context_size, 0), n_points)
    scored = n_points - context_end
    if scored <= 0 or fold_count < 1:
        return CVPlan(fold_bounds=[], context_end=context_end)

    folds = min(fold_count, scored)
    length = scored // folds
    bounds: list[tuple[int, int]] = []
    for k in range(folds):
        lo = context_end + k * length
        hi = n_points if k == folds - 1 else context_end + (k + 1) * length
        bounds.append((lo, hi))
    return CVPlan(fold_bounds=bounds, context_end=context_end)


def predictions_from_results(
    results: list[DetectionResult],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build aligned ``(y_pred, y_score, valid)`` arrays from detect() output.

    ``valid`` is False for points the detector could not score (missing /
    insufficient data — no confidence band); ``y_score`` is the normalized
    distance from the band center (``>1`` ⇔ flagged), 0 for invalid points.
    """
    n = len(results)
    y_pred = np.zeros(n, dtype=bool)
    y_score = np.zeros(n, dtype=float)
    valid = np.zeros(n, dtype=bool)
    for i, r in enumerate(results):
        if r.confidence_lower is None or r.confidence_upper is None:
            continue
        valid[i] = True
        y_pred[i] = bool(r.is_anomaly)
        half = (r.confidence_upper - r.confidence_lower) / 2.0
        center = (r.confidence_upper + r.confidence_lower) / 2.0
        pv = r.processed_value
        if half > 0 and pv is not None:
            y_score[i] = abs(float(pv) - center) / half
    return y_pred, y_score, valid


def _aggregate(per_fold: list[float], stability_lambda: float) -> tuple[float, float]:
    """Mean across folds minus a **downside-only** dispersion penalty.

    Returns ``(aggregate, penalty)``. The penalty uses the semi-deviation of the
    folds that score *below* the mean, not the full ``std``: a config that simply
    scores *higher* on some folds — e.g. a recency-aware baseline that fits the
    current regime better than stale history — should not be punished for that
    *upside* spread. Penalizing full ``std`` did exactly that, biasing the search
    against regime-adaptive configs; downside-only keeps the guard against
    genuinely unstable candidates while letting an adaptive one win.
    """
    arr = np.asarray(per_fold, dtype=float)
    mean = float(np.mean(arr))
    # Downside deviation: square only the shortfalls below the mean (upside → 0),
    # averaged over ALL folds. This is always <= the full std, and reduces to 0
    # when folds are equal — so a config that's merely *better* on recent folds is
    # not penalized, only one that drops below par on some.
    deficits = np.minimum(arr - mean, 0.0)
    downside = float(np.sqrt(np.mean(deficits**2)))
    penalty = stability_lambda * downside
    return mean - penalty, penalty


def run_cv(
    detector: BaseDetector,
    data: dict[str, np.ndarray],
    plan: CVPlan,
    ground_truth: GroundTruth,
    settings: TuneSettings,
) -> FoldScores:
    """Score *detector* over the CV folds and aggregate with a stability penalty."""
    results = detector.detect(data)
    y_pred, y_score, valid = predictions_from_results(results)
    y_true = ground_truth.y_true
    supervised = ground_truth.mode == TuneMode.SUPERVISED

    per_fold: list[float] = []
    for lo, hi in plan.fold_bounds:
        fold_valid = valid[lo:hi]
        if not fold_valid.any():
            continue
        yt = y_true[lo:hi][fold_valid]
        yp = y_pred[lo:hi][fold_valid]
        ys = y_score[lo:hi][fold_valid]
        if supervised:
            # Folds with no labeled incident are uninformative for a
            # supervised metric (and would drag a good candidate's variance
            # up); skip them and let the labeled folds drive the score.
            if not yt.any():
                continue
            per_fold.append(score_predictions(yt, yp, ys, settings.metric, settings.beta))
        else:
            per_fold.append(unsupervised_objective(yp, ys, settings.fpr_target))

    if not per_fold:
        return FoldScores(per_fold=[], aggregate=0.0, stability_penalty=0.0)

    aggregate, penalty = _aggregate(per_fold, settings.stability_lambda)
    return FoldScores(per_fold=per_fold, aggregate=aggregate, stability_penalty=penalty)
