"""Binary-classification scoring metrics — pure numpy, no scipy/sklearn.

Binary metrics (MCC / F-beta / balanced accuracy) consume the detector's
``is_anomaly`` flags; the AUC metrics (ROC / PR) consume a continuous score
(per-point normalized distance from the confidence band). The unsupervised
objective consumes the flags + scores when no labels are available.
"""

from __future__ import annotations

import math

import numpy as np

from detectkit.autotune._types import CVPlan, ScoringMetric
from detectkit.utils.stats import weighted_mad, weighted_mean, weighted_median, weighted_std

# Unsupervised objective weights (see :func:`unsupervised_objective`). They sum
# to 1.0 and are deliberately balanced: the *budget* keeps false positives in
# check, *sharpness* rewards a tight/well-calibrated band (the term the old
# ratio-only objective lacked), and *separation* rewards isolating genuine
# extremes. Kept here as named constants rather than user YAML — they are an
# engine-internal calibration, not a per-metric knob.
_UNSUP_W_BUDGET = 0.4
_UNSUP_W_SHARPNESS = 0.3
_UNSUP_W_SEPARATION = 0.3

# Clip on the standardized squared residual in the seasonality NLL probe, so a
# single wild held-out point (~>7 sigma) cannot dominate a fold's mean.
_NLL_Z2_CLIP = 50.0


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


def true_segments(y_true: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``True`` runs in *y_true* as ``[lo, hi)`` index pairs.

    Run-length encoding over the boolean truth: the contiguity of positive
    points already encodes incident boundaries, so segment-aware metrics need
    no extra segment argument.
    """
    yt = np.asarray(y_true, dtype=bool)
    if yt.size == 0:
        return []
    diff = np.diff(yt.astype(np.int8))
    starts = np.flatnonzero(diff == 1) + 1
    ends = np.flatnonzero(diff == -1) + 1
    if yt[0]:
        starts = np.concatenate([[0], starts])
    if yt[-1]:
        ends = np.concatenate([ends, [yt.size]])
    return list(zip(starts.tolist(), ends.tolist(), strict=False))


def event_f_beta(y_true: np.ndarray, y_pred: np.ndarray, beta: float = 1.0) -> float:
    """Segment-aware (point-adjusted) F-beta — the alert-centric score.

    Incidents are the contiguous ``True`` runs in *y_true*. Counting follows
    the Revised-Point-Adjusted convention: a segment with **at least one**
    predicted point is one TP (the incident was caught — one alert fires per
    incident), a segment with none is one FN, and every predicted positive
    **outside** all segments counts pointwise as an FP. This deliberately mixes
    segment-level TP/FN with pointwise FP: catching a 50-point incident with a
    single flag is full credit, while scattered false flags each cost.

    Contiguity is meaningful here — callers must NOT boolean-mask the arrays
    before calling (masking splices distinct incidents together); see
    :func:`scorable_event_truth` for handling unscorable points.
    """
    yt = np.asarray(y_true, dtype=bool)
    yp = np.asarray(y_pred, dtype=bool)
    segments = true_segments(yt)
    tp = sum(1 for lo, hi in segments if bool(np.any(yp[lo:hi])))
    fn = len(segments) - tp
    fp = int(np.sum(yp & ~yt))
    b2 = beta * beta
    denominator = (1.0 + b2) * tp + b2 * fn + fp
    if denominator == 0.0:
        return 0.0
    return (1.0 + b2) * tp / denominator


def scorable_event_truth(y_true: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Zero out truth segments the detector could not score anywhere.

    The pointwise metrics drop invalid points by boolean masking; the event
    metric cannot (masking splices segments). Instead the full-length arrays
    are scored and any incident containing **no** valid point is removed from
    the truth — the detector had no confidence band anywhere inside it, so it
    is unscorable rather than missed. Invalid points can't contribute FPs
    (``y_pred`` is always False where invalid).
    """
    yt: np.ndarray = np.array(y_true, dtype=bool)
    v = np.asarray(valid, dtype=bool)
    for lo, hi in true_segments(yt):
        if not bool(np.any(v[lo:hi])):
            yt[lo:hi] = False
    return yt


def arrays_for_metric(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray,
    valid: np.ndarray,
    metric: ScoringMetric,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Prepare ``(y_true, y_pred, y_score)`` for a supervised metric.

    The single seam both CV folds and the alert-window sweep use, so the two
    can never disagree on how invalid (unscorable) points are handled:
    pointwise metrics drop them by boolean masking; the segment-aware metric
    keeps full-length arrays (masking would splice distinct incidents) with
    unscorable segments removed from the truth and invalid predictions zeroed.
    """
    if metric == ScoringMetric.EVENT_F1:
        return scorable_event_truth(y_true, valid), y_pred & valid, y_score
    return y_true[valid], y_pred[valid], y_score[valid]


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
    if metric == ScoringMetric.EVENT_F1:
        return event_f_beta(y_true, y_pred, 1.0)
    raise ValueError(f"Unknown scoring metric: {metric}")


def unsupervised_objective(
    y_pred: np.ndarray,
    y_score: np.ndarray,
    fpr_target: float = 0.01,
    *,
    w_budget: float = _UNSUP_W_BUDGET,
    w_sharpness: float = _UNSUP_W_SHARPNESS,
    w_separation: float = _UNSUP_W_SEPARATION,
) -> float:
    """No-label objective: a *tight, well-calibrated* band that flags only extremes.

    ``y_score`` is the band-relative distance ``|value - center| / half_width`` —
    ``<= 1`` for points inside the band (``y_pred`` False), ``> 1`` outside
    (``y_pred`` True). Three bounded, complementary terms (weights sum to 1):

    - **budget** — keeps the flag rate near/under ``fpr_target``. Smoothly
      decreasing in the flag rate (``1 / (1 + max(0, (f - t) / t))``): full
      credit at/under target, *no flat cliff* so there is always gradient back
      toward fewer flags, and — being one-sided — it never *rewards* flagging
      below target, so a genuinely clean metric is not pushed to manufacture
      anomalies.
    - **sharpness** — the median ``y_score`` of the *normal* points. A tight,
      well-calibrated band leaves normal points near its edge (``-> 1``); a slack
      or all-suppress band leaves them near the center (``-> 0``). This is **not**
      a ratio, so it directly rewards a narrow interval and fixes the old
      objective's blindness to band width (its ratio-only ``separation`` was
      scale-invariant, scoring a snug band and a hugely slack one identically).
    - **separation** — flagged points should sit clearly farther outside the band
      than normal points (a clean partition; the scale-invariant ratio of
      medians, retained for its partition-quality signal).

    The all-suppress detector (huge band → no flags, normals near center) now
    scores only ``w_budget`` (sharpness and separation both collapse to 0),
    so a tight band that isolates real extremes strictly beats doing nothing —
    removing the old ``0.6`` all-suppress plateau that made the tuner timid.
    """
    yp = np.asarray(y_pred, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    if yp.size == 0:
        return 0.0

    flag_rate = float(np.mean(yp))
    if fpr_target > 0:
        budget = 1.0 / (1.0 + max(0.0, (flag_rate - fpr_target) / fpr_target))
    else:
        budget = 1.0 if flag_rate == 0.0 else 0.0

    flagged = ys[yp]
    normal = ys[~yp]

    if normal.size == 0:
        sharpness = 0.0
    else:
        sharpness = max(0.0, min(1.0, float(np.median(normal))))

    if flagged.size == 0 or normal.size == 0:
        separation = 0.0
    else:
        med_flagged = float(np.median(flagged))
        med_normal = float(np.median(normal))
        denom = med_flagged + med_normal
        separation = (med_flagged - med_normal) / denom if denom > 0 else 0.0
        separation = max(0.0, min(1.0, separation))

    return w_budget * budget + w_sharpness * sharpness + w_separation * separation


def _center_spread(vals: np.ndarray, wts: np.ndarray, center: str) -> tuple[float, float]:
    """Robust (or moment) center + spread, matching the detector's stat family."""
    if center == "mean":
        c = weighted_mean(vals, wts)
        s = weighted_std(vals, wts, center=c, ddof=1)
    else:
        c = weighted_median(vals, wts)
        s = 1.4826 * weighted_mad(vals, wts, center=c)
    return c, s


def oof_residual_reduction(
    values: np.ndarray,
    weights: np.ndarray,
    keys: np.ndarray,
    plan: CVPlan,
    *,
    center: str = "median",
    min_group: int = 10,
    stability_lambda: float = 0.5,
    trim: float = 0.10,
) -> tuple[float, list[float]]:
    """Held-out fit gain from conditioning on a seasonal grouping.

    A leak-free, walk-forward measure of how much a candidate seasonal grouping
    improves the band the windowed detector would actually build — which applies
    seasonality as per-group center/scale ratios on the global statistics
    (``adjusted = global * group/global``, falling back to global for groups below
    ``min_group``). Both of the detector's seasonal effects — a per-group
    **center** shift and, crucially, a per-group **spread** (confidence-interval
    width) — must be rewarded; a plain residual ratio standardized by each
    model's own spread cancels them out. So each held-out point is scored by a
    robustified Gaussian **negative log-likelihood** in units of the global
    spread:

    - ``nll_global(z)   = 0.5 * z^2``                with ``z = (v - mu0) / s0``,
    - ``nll_seasonal(z) = 0.5 * ((v - mu_g)/s_g)^2 + log(s_g / s0)``.

    The ``log(s_g/s0)`` term rewards a *tighter* per-group interval and the
    squared term rewards better centering — so this criterion is band-width
    aware, mirroring how the detector consumes seasonality. The group falls back
    to global when unseen/too-sparse in train (exactly the detector's behavior),
    so an over-fragmented grouping contributes 0 and cannot win mechanically; an
    overfit group that does not generalize gets a *worse* held-out NLL and is
    rejected.

    The per-fold gain ``rho = 1 - mean(nll_seasonal) / mean(nll_global)`` (on the
    inlier points — the most baseline-anomalous ``trim`` fraction is dropped from
    *both* models so a real outlier cannot flatter either) is aggregated as
    ``mean(rho) - stability_lambda * std(rho)``. The no-seasonality baseline
    scores exactly 0, so any positive score is a genuine generalizing improvement.

    Returns ``(score, per_fold_rho)``.
    """
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    finite_v = v[np.isfinite(v)]
    eps = 1e-9 * float(np.median(np.abs(finite_v))) + 1e-12 if finite_v.size else 1e-12

    per_fold: list[float] = []
    for lo, hi in plan.fold_bounds:
        tr = np.arange(0, lo)
        ho = np.arange(lo, hi)
        tr = tr[np.isfinite(v[tr])]
        ho = ho[np.isfinite(v[ho])]
        if tr.size < min_group or ho.size == 0:
            continue

        mu0, s0 = _center_spread(v[tr], w[tr], center)
        s0 = max(s0, eps)

        # Per-group train stats; only groups with >= min_group points are trusted
        # (mirrors the detector's per-group fallback to global).
        group_stats: dict[object, tuple[float, float]] = {}
        buckets: dict[object, list[int]] = {}
        for idx in tr.tolist():
            buckets.setdefault(keys[idx], []).append(idx)
        for key, idxs in buckets.items():
            if len(idxs) < min_group:
                continue
            arr = np.asarray(idxs, dtype=np.int64)
            cg, sg = _center_spread(v[arr], w[arr], center)
            group_stats[key] = (cg, max(sg, eps))

        z = (v[ho] - mu0) / s0
        nll_0 = 0.5 * np.minimum(z * z, _NLL_Z2_CLIP)
        nll_g = np.empty(ho.size, dtype=float)
        for pos, idx in enumerate(ho.tolist()):
            cg, sg = group_stats.get(keys[idx], (mu0, s0))
            zg = (v[ho[pos]] - cg) / sg
            nll_g[pos] = 0.5 * min(zg * zg, _NLL_Z2_CLIP) + math.log(sg / s0)

        # Drop the most baseline-anomalous `trim` fraction from BOTH models so a
        # genuine outlier can't make either look better; score fit on the bulk.
        keep = nll_0.size - int(math.floor(trim * nll_0.size))
        if keep <= 0:
            keep = nll_0.size
        inliers = np.argsort(z * z, kind="mergesort")[:keep]
        mean_nll_0 = float(np.mean(nll_0[inliers]))
        mean_nll_g = float(np.mean(nll_g[inliers]))
        per_fold.append(1.0 - mean_nll_g / max(mean_nll_0, eps))

    if not per_fold:
        return 0.0, []
    arr = np.asarray(per_fold, dtype=float)
    return float(np.mean(arr) - stability_lambda * np.std(arr)), per_fold
