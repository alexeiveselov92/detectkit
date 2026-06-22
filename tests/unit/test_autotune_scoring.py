"""Tests for the autotune scoring metrics (pure numpy)."""

import numpy as np

from detectkit.autotune._types import ScoringMetric
from detectkit.autotune.scoring import (
    balanced_accuracy,
    confusion,
    f_beta,
    mcc,
    pr_auc,
    roc_auc,
    score_predictions,
    unsupervised_objective,
)


def test_confusion_counts():
    yt = np.array([1, 1, 0, 0], dtype=bool)
    yp = np.array([1, 0, 1, 0], dtype=bool)
    assert confusion(yt, yp) == (1, 1, 1, 1)  # tp, fp, tn, fn


def test_mcc_perfect_inverted_degenerate():
    yt = np.array([1, 1, 0, 0, 1, 0], dtype=bool)
    assert mcc(yt, yt) == 1.0
    assert mcc(yt, ~yt) == -1.0
    # all-negative predictions → degenerate column → 0.0, never NaN
    assert mcc(yt, np.zeros(6, dtype=bool)) == 0.0


def test_f_beta_recall_weighting():
    yt = np.array([1, 1, 1, 0], dtype=bool)
    yp = np.array([1, 0, 0, 0], dtype=bool)  # 1 tp, 2 fn, 0 fp
    f1 = f_beta(yt, yp, 1.0)
    f2 = f_beta(yt, yp, 2.0)
    # beta>1 weights recall, and recall here is poor → f2 < f1
    assert f2 < f1
    assert f_beta(yt, yt, 1.0) == 1.0


def test_balanced_accuracy():
    yt = np.array([1, 1, 0, 0], dtype=bool)
    assert balanced_accuracy(yt, yt) == 1.0
    assert balanced_accuracy(yt, ~yt) == 0.0


def test_roc_auc_ranking_and_degenerate():
    yt = np.array([1, 1, 0, 0], dtype=bool)
    perfect = np.array([0.9, 0.8, 0.2, 0.1])
    assert roc_auc(yt, perfect) == 1.0
    inverted = np.array([0.1, 0.2, 0.8, 0.9])
    assert roc_auc(yt, inverted) == 0.0
    # one class present → 0.5
    assert roc_auc(np.zeros(4, dtype=bool), perfect) == 0.5


def test_roc_auc_tie_handling():
    yt = np.array([1, 0], dtype=bool)
    # tied scores → AUC 0.5
    assert roc_auc(yt, np.array([0.5, 0.5])) == 0.5


def test_pr_auc():
    yt = np.array([1, 1, 0, 0], dtype=bool)
    assert pr_auc(yt, np.array([0.9, 0.8, 0.2, 0.1])) == 1.0
    # no positives → 0.0
    assert pr_auc(np.zeros(4, dtype=bool), np.array([0.9, 0.8, 0.2, 0.1])) == 0.0


def test_score_predictions_dispatch():
    yt = np.array([1, 1, 0, 0], dtype=bool)
    ys = np.array([0.9, 0.8, 0.2, 0.1])
    assert score_predictions(yt, yt, ys, ScoringMetric.MCC) == 1.0
    assert score_predictions(yt, yt, ys, ScoringMetric.F1) == 1.0
    assert score_predictions(yt, yt, ys, ScoringMetric.ROC_AUC) == 1.0
    assert score_predictions(yt, yt, ys, ScoringMetric.PR_AUC) == 1.0


def test_unsupervised_objective_rewards_low_flag_rate():
    # No flags at all → no false positives → fpr term maxed (0.6 floor)
    n = 100
    no_flags = np.zeros(n, dtype=bool)
    scores = np.full(n, 0.3)
    assert unsupervised_objective(no_flags, scores, fpr_target=0.01) == 0.6

    # A few well-separated flags beat over-flagging
    few = np.zeros(n, dtype=bool)
    few[:1] = True
    few_scores = scores.copy()
    few_scores[0] = 5.0
    over = np.ones(n, dtype=bool)
    assert unsupervised_objective(few, few_scores, 0.01) > unsupervised_objective(
        over, scores, 0.01
    )
