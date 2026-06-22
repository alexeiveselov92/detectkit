"""Binary-classification scoring metrics — pure numpy, no scipy/sklearn.

Binary metrics (MCC / F-beta / balanced accuracy) consume the detector's
``is_anomaly`` flags; the AUC metrics (ROC / PR) consume a continuous score
(per-point normalized distance from the confidence band). The unsupervised
objective consumes the flags + scores when no labels are available.
"""

from __future__ import annotations

import math

import numpy as np

from detectkit.autotune._types import ScoringMetric


def confusion(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[int, int, int, int]:
    """Return ``(tp, fp, tn, fn)`` from boolean truth / prediction arrays."""
    yt = np.asarray(y_true, dtype=bool)
    yp = np.asarray(y_pred, dtype=bool)
    tp = int(np.sum(yt & yp))
    fp = int(np.sum(~yt & yp))
    tn = int(np.sum(~yt & ~yp))
    fn = int(np.sum(yt & ~yp))
    return tp, fp, tn, fn


def mcc(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Matthews correlation coefficient in ``[-1, 1]`` (0 on a degenerate cell)."""
    tp, fp, tn, fn = confusion(y_true, y_pred)
    numerator = float(tp * tn - fp * fn)
    denominator = math.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def f_beta(y_true: np.ndarray, y_pred: np.ndarray, beta: float = 1.0) -> float:
    """F-beta score (beta>1 weights recall over precision). Ignores true negatives."""
    tp, fp, _tn, fn = confusion(y_true, y_pred)
    b2 = beta * beta
    denominator = (1.0 + b2) * tp + b2 * fn + fp
    if denominator == 0.0:
        return 0.0
    return (1.0 + b2) * tp / denominator


def balanced_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Mean of sensitivity (TPR) and specificity (TNR)."""
    tp, fp, tn, fn = confusion(y_true, y_pred)
    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    tnr = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    return 0.5 * (tpr + tnr)


def _rankdata_average(values: np.ndarray) -> np.ndarray:
    """Assign ranks 1..n, averaging ties (numpy reimplementation of rankdata)."""
    values = np.asarray(values, dtype=float)
    n = values.size
    order = np.argsort(values, kind="mergesort")
    sorted_vals = values[order]
    sorted_ranks = np.empty(n, dtype=float)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        sorted_ranks[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    ranks = np.empty(n, dtype=float)
    ranks[order] = sorted_ranks
    return ranks


def roc_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Rank-based ROC-AUC (Mann-Whitney U); 0.5 when a class is absent."""
    yt = np.asarray(y_true, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    n_pos = int(np.sum(yt))
    n_neg = int(yt.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        return 0.5
    ranks = _rankdata_average(ys)
    sum_ranks_pos = float(np.sum(ranks[yt]))
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Average precision (area under the precision-recall curve)."""
    yt = np.asarray(y_true, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    n = yt.size
    n_pos = int(np.sum(yt))
    if n_pos == 0:
        return 0.0
    order = np.argsort(ys, kind="mergesort")[::-1]  # descending score
    yt_sorted = yt[order]
    ys_sorted = ys[order]
    tp = 0
    fp = 0
    prev_recall = 0.0
    average_precision = 0.0
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ys_sorted[j + 1] == ys_sorted[i]:
            j += 1
        block = yt_sorted[i : j + 1]
        tp += int(np.sum(block))
        fp += int(np.sum(~block))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / n_pos
        average_precision += (recall - prev_recall) * precision
        prev_recall = recall
        i = j + 1
    return average_precision


def score_predictions(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray,
    metric: ScoringMetric,
    beta: float = 1.0,
) -> float:
    """Dispatch to the requested metric (AUC metrics use ``y_score``)."""
    if metric == ScoringMetric.MCC:
        return mcc(y_true, y_pred)
    if metric == ScoringMetric.F1:
        return f_beta(y_true, y_pred, 1.0)
    if metric == ScoringMetric.F_BETA:
        return f_beta(y_true, y_pred, beta)
    if metric == ScoringMetric.BALANCED_ACCURACY:
        return balanced_accuracy(y_true, y_pred)
    if metric == ScoringMetric.ROC_AUC:
        return roc_auc(y_true, y_score)
    if metric == ScoringMetric.PR_AUC:
        return pr_auc(y_true, y_score)
    raise ValueError(f"Unknown scoring metric: {metric}")


def unsupervised_objective(
    y_pred: np.ndarray,
    y_score: np.ndarray,
    fpr_target: float = 0.01,
) -> float:
    """No-label objective: reward a low flag rate + clean separation.

    With no ground truth, every flag is a *potential* false positive, so we
    reward keeping the flag rate at/under ``fpr_target`` and reward flagged
    points sitting clearly farther from their band than normal points
    (so the detector flags genuine extremes, not borderline noise).
    """
    yp = np.asarray(y_pred, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    if yp.size == 0:
        return 0.0

    flag_rate = float(np.mean(yp))
    if fpr_target > 0:
        fpr_term = 1.0 - min(flag_rate / fpr_target, 1.0)
    else:
        fpr_term = 1.0 if flag_rate == 0.0 else 0.0

    flagged = ys[yp]
    normal = ys[~yp]
    if flagged.size == 0 or normal.size == 0:
        separation = 0.0
    else:
        med_flagged = float(np.median(flagged))
        med_normal = float(np.median(normal))
        denom = med_flagged + med_normal
        separation = (med_flagged - med_normal) / denom if denom > 0 else 0.0
        separation = max(0.0, min(1.0, separation))

    return 0.6 * fpr_term + 0.4 * separation
