"""Tests for the autotune scoring metrics (pure numpy)."""

import numpy as np

from detectkit.autotune._types import ScoringMetric
from detectkit.autotune.scoring import (
    balanced_accuracy,
    confusion,
    event_f_beta,
    f_beta,
    mcc,
    pr_auc,
    roc_auc,
    scorable_event_truth,
    score_predictions,
    true_segments,
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
    assert score_predictions(yt, yt, ys, ScoringMetric.EVENT_F1) == 1.0


def test_true_segments_rle():
    assert true_segments(np.zeros(5, dtype=bool)) == []
    assert true_segments(np.ones(3, dtype=bool)) == [(0, 3)]
    yt = np.array([0, 1, 1, 0, 0, 1, 0, 1], dtype=bool)
    assert true_segments(yt) == [(1, 3), (5, 6), (7, 8)]
    assert true_segments(np.zeros(0, dtype=bool)) == []


def test_event_f_beta_one_flag_catches_whole_incident():
    # A 50-point incident caught by a single flagged point is full recall —
    # the exact case pointwise F1 punishes with 49 FN.
    yt = np.zeros(100, dtype=bool)
    yt[20:70] = True
    yp = np.zeros(100, dtype=bool)
    yp[45] = True
    assert event_f_beta(yt, yp) == 1.0
    assert f_beta(yt, yp) < 0.1


def test_event_f_beta_counts_segments_and_pointwise_fps():
    # Two incidents: one caught, one missed; two scattered FPs outside.
    yt = np.zeros(30, dtype=bool)
    yt[5:10] = True
    yt[20:25] = True
    yp = np.zeros(30, dtype=bool)
    yp[7] = True  # catches segment 1
    yp[0] = True  # FP
    yp[15] = True  # FP
    # tp=1 (segment), fn=1 (segment), fp=2 (points) → f1 = 2/(2+1+2)
    assert event_f_beta(yt, yp) == 2.0 / 5.0


def test_event_f_beta_degenerate():
    yp = np.zeros(10, dtype=bool)
    # no incidents, no predictions → 0.0 (mirrors f_beta convention)
    assert event_f_beta(np.zeros(10, dtype=bool), yp) == 0.0
    # no incidents, one FP → 0.0
    yp2 = yp.copy()
    yp2[3] = True
    assert event_f_beta(np.zeros(10, dtype=bool), yp2) == 0.0
    # empty arrays
    assert event_f_beta(np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)) == 0.0


def test_event_f_beta_flag_inside_incident_is_not_fp():
    # Extra flags inside an already-caught incident cost nothing (one alert
    # fires per incident regardless of how many points inside are flagged).
    yt = np.zeros(20, dtype=bool)
    yt[5:15] = True
    one = np.zeros(20, dtype=bool)
    one[7] = True
    many = np.zeros(20, dtype=bool)
    many[6:14] = True
    assert event_f_beta(yt, one) == event_f_beta(yt, many) == 1.0


def test_scorable_event_truth_drops_unscorable_segments():
    yt = np.zeros(20, dtype=bool)
    yt[2:5] = True  # no valid point inside → unscorable
    yt[10:14] = True  # partially valid → kept whole
    valid = np.ones(20, dtype=bool)
    valid[2:5] = False
    valid[10:12] = False
    cleaned = scorable_event_truth(yt, valid)
    assert not cleaned[2:5].any()
    assert cleaned[10:14].all()
    # input untouched
    assert yt[2:5].all()


def test_unsupervised_objective_is_bounded():
    n = 100
    rng = np.arange(n) / n
    flags = rng > 0.95
    assert 0.0 <= unsupervised_objective(flags, rng * 2.0, 0.01) <= 1.0
    assert unsupervised_objective(np.zeros(0, dtype=bool), np.zeros(0), 0.01) == 0.0


def test_unsupervised_objective_catching_extreme_beats_all_suppress():
    # All-suppress: no flags, normals sit near the band center (slack band).
    n = 100
    no_flags = np.zeros(n, dtype=bool)
    slack = np.full(n, 0.1)
    all_suppress = unsupervised_objective(no_flags, slack, fpr_target=0.01)

    # A tight band that isolates a single genuine extreme, normals near the edge.
    few = np.zeros(n, dtype=bool)
    few[0] = True
    tight_scores = np.full(n, 0.85)
    tight_scores[0] = 8.0
    catching = unsupervised_objective(few, tight_scores, 0.01)

    assert catching > all_suppress
    # all-suppress no longer scores the old 0.6 plateau; it is bounded by w_budget.
    assert all_suppress < 0.5


def test_unsupervised_objective_rewards_tight_band_same_flags():
    # Same flag set, different band width: the tighter band (normals near the
    # edge) must score higher even though the slack band has larger separation.
    n = 100
    flags = np.zeros(n, dtype=bool)
    flags[0] = True

    tight = np.full(n, 0.9)
    tight[0] = 1.5
    slack = np.full(n, 0.2)
    slack[0] = 1.5

    assert unsupervised_objective(flags, tight, 0.01) > unsupervised_objective(flags, slack, 0.01)


def test_unsupervised_objective_penalizes_over_flagging():
    # A few well-separated flags beat flagging everything.
    n = 100
    scores = np.full(n, 0.3)
    few = np.zeros(n, dtype=bool)
    few[0] = True
    few_scores = scores.copy()
    few_scores[0] = 5.0
    over = np.ones(n, dtype=bool)
    assert unsupervised_objective(few, few_scores, 0.01) > unsupervised_objective(
        over, scores, 0.01
    )
