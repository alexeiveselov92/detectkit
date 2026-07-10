"""Small shared types for the autotune engine.

Kept dependency-free (no imports from other autotune modules) so every stage
can import these without cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ScoringMetric(str, Enum):
    """Optimization target for the grid search.

    All are computed in pure numpy (see :mod:`detectkit.autotune.scoring`).
    MCC is the default: it uses all four confusion cells and is robust to the
    heavy class imbalance of rare anomalies. ``event_f1`` is segment-aware
    (point-adjusted): one flagged point anywhere inside a labeled incident
    counts the whole incident as caught — matching how the alert pipeline and
    the ``dtk tune`` cockpit's recall/FDR bar treat incidents.
    """

    MCC = "mcc"
    F1 = "f1"
    F_BETA = "f_beta"
    BALANCED_ACCURACY = "balanced_accuracy"
    ROC_AUC = "roc_auc"
    PR_AUC = "pr_auc"
    EVENT_F1 = "event_f1"


class TuneMode(str, Enum):
    """Whether the run optimizes against labels or data statistics."""

    SUPERVISED = "supervised"
    UNSUPERVISED = "unsupervised"


@dataclass
class CVPlan:
    """Walk-forward fold layout over a single loaded series.

    ``fold_bounds`` are ``[lo, hi)`` index ranges into the series; the first
    ``context_end`` points are reserved as pure context and never scored.
    """

    fold_bounds: list[tuple[int, int]]
    context_end: int


@dataclass
class FoldScores:
    """Per-fold scores plus the stability-penalized aggregate."""

    per_fold: list[float]
    aggregate: float
    stability_penalty: float


@dataclass
class CandidateEval:
    """A single evaluated detector candidate."""

    detector_type: str
    params: dict[str, Any]
    detector_id: str
    fold_scores: FoldScores
    score: float


@dataclass
class GroupVote:
    """Per-seasonality-group distribution features + ranked detector suitabilities."""

    group: list[str]
    features: dict[str, float]
    ranked_types: list[tuple[str, float]]


@dataclass
class DecisionEntry:
    """One ordered, human-readable rationale entry for the decision log."""

    stage: str
    message: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "message": self.message, "fields": self.fields}
