"""Shared engine state + the candidate-evaluation primitive.

The stages are plain functions (in their own modules) that take an
:class:`_AutoTuneBase` as their first argument and call ``evaluate`` /
``log`` on it. This keeps cross-stage calls explicit and type-checkable
(no cross-mixin attribute access) while still splitting the pipeline into
focused, <250-line files.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from detectkit.autotune._types import (
    CandidateEval,
    CVPlan,
    DecisionEntry,
    GroupVote,
)
from detectkit.autotune.crossval import run_cv
from detectkit.autotune.labels import GroundTruth
from detectkit.autotune.settings import TuneSettings
from detectkit.detectors.factory import DetectorFactory


class AutoTuneError(RuntimeError):
    """Raised when a metric cannot be tuned (no data, no viable candidate, …)."""


class _AutoTuneBase:
    """Holds the loaded series, labels, settings, decision log + eval cache."""

    def __init__(
        self,
        *,
        metric_name: str,
        data: dict[str, np.ndarray],
        ground_truth: GroundTruth,
        interval_seconds: int,
        settings: TuneSettings,
        on_stage: Callable[[str, str], None] | None = None,
    ) -> None:
        self.metric_name = metric_name
        self.data = data
        self.ground_truth = ground_truth
        self.interval_seconds = interval_seconds
        self.settings = settings
        self._on_stage = on_stage
        self.decision_log: list[DecisionEntry] = []
        self.group_votes: list[GroupVote] = []
        self.cv_plan: CVPlan | None = None
        # detector_id -> evaluated candidate (doubles as the dedup cache and
        # the ledger of every candidate considered during the run)
        self._evaluated: dict[str, CandidateEval] = {}

    # ------------------------------------------------------------------
    # Progress + decision log
    # ------------------------------------------------------------------

    def emit(self, stage: str, line: str) -> None:
        """Stream one progress line to the CLI renderer (if attached)."""
        if self._on_stage is not None:
            self._on_stage(stage, line)

    def log(self, stage: str, message: str, *, emit: bool = True, **fields: Any) -> None:
        """Record a decision-log entry (and optionally stream it)."""
        self.decision_log.append(DecisionEntry(stage=stage, message=message, fields=fields))
        if emit:
            self.emit(stage, message)

    # ------------------------------------------------------------------
    # Candidate evaluation
    # ------------------------------------------------------------------

    def evaluate(self, detector_type: str, params: dict[str, Any]) -> CandidateEval:
        """Build + cross-validate a candidate detector (memoized by detector id)."""
        full_params = {**self.settings.fixed_params, **params}
        detector = DetectorFactory.create(detector_type, full_params)
        detector_id = detector.get_detector_id()
        cached = self._evaluated.get(detector_id)
        if cached is not None:
            return cached

        if self.cv_plan is None:
            raise AutoTuneError("CV plan not initialized before evaluation")
        fold_scores = run_cv(detector, self.data, self.cv_plan, self.ground_truth, self.settings)
        ev = CandidateEval(
            detector_type=detector_type,
            params=full_params,
            detector_id=detector_id,
            fold_scores=fold_scores,
            score=fold_scores.aggregate,
        )
        self._evaluated[detector_id] = ev
        return ev

    def safe_evaluate(self, detector_type: str, params: dict[str, Any]) -> CandidateEval | None:
        """Evaluate, returning None on an invalid parameter combination."""
        try:
            return self.evaluate(detector_type, params)
        except ValueError:
            return None

    def evaluated_ids(self) -> list[str]:
        """Every distinct detector id considered during the run (cleanup ledger)."""
        return list(self._evaluated.keys())
