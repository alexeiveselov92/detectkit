"""The structured outcome of one autotune run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AutoTuneResult:
    """Everything the command needs to persist, emit a config, and report.

    ``candidates`` lists every distinct detector evaluated during the search
    (type + params + id) so the command can persist their detections and then
    prune all but ``winning_detector_id``.
    """

    metric_name: str
    mode: str
    scoring_metric: str
    training_start: datetime | None
    training_end: datetime | None
    interval_seconds: int
    n_points: int
    labels_summary: dict[str, Any]

    chosen_seasonality: list | None
    chosen_detector_type: str
    chosen_detector_params: dict[str, Any]
    winning_detector_id: str
    score: float
    cv_per_fold: list[float]
    cv_stability_penalty: float

    consecutive_anomalies: int | None
    candidate_detector_ids: list[str]
    candidates: list[dict[str, Any]] = field(default_factory=list)
    group_votes: list[dict[str, Any]] = field(default_factory=list)
    decision_log: list[dict[str, Any]] = field(default_factory=list)
