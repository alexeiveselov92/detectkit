"""Scoring metrics for the benchmark harness — pure numpy, no scipy/sklearn.

This module intentionally imports NOTHING from ``detectkit`` so the harness
stands alone: it must be able to score a detectkit checkout without being
coupled to whatever version of ``detectkit.autotune.scoring`` happens to be
installed. ``event_f_beta`` below is the same point-adjusted metric as
``detectkit.autotune.scoring.event_f_beta`` (added on this branch) — kept as
an independent local copy on purpose, not imported, so a future change to the
library's scoring internals can't silently change what this harness reports.

Every function handles empty/degenerate inputs by returning 0.0 (or 0.5 for
the AUC conventions), mirroring ``detectkit/autotune/scoring.py``.
"""

from __future__ import annotations

import numpy as np


def confusion(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[int, int, int, int]:
    """Return ``(tp, fp, tn, fn)`` from boolean truth / prediction arrays."""
    yt = np.asarray(y_true, dtype=bool)
    yp = np.asarray(y_pred, dtype=bool)
    tp = int(np.sum(yt & yp))
    fp = int(np.sum(~yt & yp))
    tn = int(np.sum(~yt & ~yp))
    fn = int(np.sum(yt & ~yp))
    return tp, fp, tn, fn


def f_beta(y_true: np.ndarray, y_pred: np.ndarray, beta: float = 1.0) -> float:
    """Pointwise F-beta score. Returns 0.0 when there is nothing to score."""
    tp, fp, _tn, fn = confusion(y_true, y_pred)
    b2 = beta * beta
    denominator = (1.0 + b2) * tp + b2 * fn + fp
    if denominator == 0.0:
        return 0.0
    return (1.0 + b2) * tp / denominator


def f1(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Pointwise F1 score."""
    return f_beta(y_true, y_pred, beta=1.0)


def _true_segments(y_true: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``True`` runs in ``y_true`` as ``(start, end_exclusive)``
    index pairs, via run-length encoding."""
    yt = np.asarray(y_true, dtype=bool)
    if yt.size == 0 or not yt.any():
        return []
    diff = np.diff(yt.astype(np.int8))
    starts = list(np.flatnonzero(diff == 1) + 1)
    ends = list(np.flatnonzero(diff == -1) + 1)
    if yt[0]:
        starts = [0] + starts
    if yt[-1]:
        ends = ends + [int(yt.size)]
    return list(zip(starts, ends, strict=True))


def event_f_beta(y_true: np.ndarray, y_pred: np.ndarray, beta: float = 1.0) -> float:
    """Point-adjusted / segment-aware F-beta (the "event" metric).

    Ground-truth segments are contiguous ``True`` runs in ``y_true`` (an
    incident). A segment is a TP if ANY predicted point falls inside it — one
    correct point anywhere in the incident is enough, matching how an
    alert-centric product is actually judged (an incident either got flagged
    once or was missed entirely, not scored point-by-point). A segment with
    no predicted point inside it is a FN. Predicted positives that fall
    OUTSIDE every segment are FP (each one counted, unlike the TP side — a
    detector that fires sporadically across a clean stretch should still be
    penalized per false alert). This point-adjusted convention follows Xu et
    al. 2018 and the NAB/Yahoo benchmark literature.

    Returns 0.0 when there is nothing to score (no segments and no false
    positives).
    """
    yt = np.asarray(y_true, dtype=bool)
    yp = np.asarray(y_pred, dtype=bool)
    if yt.size == 0:
        return 0.0

    segments = _true_segments(yt)
    covered = np.zeros(yt.size, dtype=bool)
    tp = 0
    fn = 0
    for start, end in segments:
        covered[start:end] = True
        if yp[start:end].any():
            tp += 1
        else:
            fn += 1

    fp = int(np.sum(yp & ~covered))

    b2 = beta * beta
    denominator = (1.0 + b2) * tp + b2 * fn + fp
    if denominator == 0.0:
        return 0.0
    return (1.0 + b2) * tp / denominator


def pr_auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Average precision (area under the precision-recall curve), tie-aware.

    Adapted in style from ``detectkit.autotune.scoring.pr_auc`` — a
    standalone reimplementation (not imported), consistent with this
    module's no-dependency-on-detectkit rule.
    """
    yt = np.asarray(y_true, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    n = yt.size
    n_pos = int(np.sum(yt))
    if n_pos == 0 or n == 0:
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


def _threshold_grid(y_score: np.ndarray, n_thresholds: int) -> np.ndarray:
    """Unique quantile values of ``y_score`` plus a ``+inf`` edge (so
    "flag nothing" is always a candidate threshold)."""
    ys = np.asarray(y_score, dtype=float)
    finite = ys[np.isfinite(ys)]
    if finite.size == 0:
        return np.array([np.inf])
    quantiles = np.linspace(0.0, 1.0, n_thresholds)
    thresholds = np.unique(np.quantile(finite, quantiles))
    return np.concatenate([thresholds, [np.inf]])


def f1_best(y_true: np.ndarray, y_score: np.ndarray, n_thresholds: int = 200) -> float:
    """Best pointwise F1 over a threshold sweep (``y_pred = y_score > thr``)."""
    yt = np.asarray(y_true, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    if yt.size == 0 or not yt.any():
        return 0.0
    best = 0.0
    for thr in _threshold_grid(ys, n_thresholds):
        best = max(best, f1(yt, ys > thr))
    return best


def event_f1_best(
    y_true: np.ndarray, y_score: np.ndarray, n_thresholds: int = 200, beta: float = 1.0
) -> float:
    """Best point-adjusted/event F-beta over the same threshold sweep as
    :func:`f1_best`."""
    yt = np.asarray(y_true, dtype=bool)
    ys = np.asarray(y_score, dtype=float)
    if yt.size == 0 or not yt.any():
        return 0.0
    best = 0.0
    for thr in _threshold_grid(ys, n_thresholds):
        best = max(best, event_f_beta(yt, ys > thr, beta=beta))
    return best
