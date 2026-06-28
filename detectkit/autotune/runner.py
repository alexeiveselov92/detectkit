"""Shared autotune entry point reused by ``dtk autotune`` and ``dtk tune``.

The pure ``run_autotune_engine`` operates on an in-memory ``data`` dict, a
``GroundTruth`` and a ``TuneSettings``. Both callers need the same plumbing to
get there from a metric's ``AutoTuneConfig`` + labels: resolve the scoring
metric, cap the training history, build the settings, project the labels onto
the grid, and run the engine. That plumbing used to live privately in
``cli/commands/autotune.py``; it lives here so the ``dtk tune`` server can reuse
it verbatim for its server-side **Autotune** mode (no browser port of the
scoring/CV/seasonality search). Neither this module nor the engine touches the
database or the filesystem — the caller loads the datapoints and decides what to
persist.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from detectkit.autotune._types import ScoringMetric
from detectkit.autotune.autotuner import run_autotune_engine
from detectkit.autotune.labels import IncidentLabels
from detectkit.autotune.result import AutoTuneResult
from detectkit.autotune.settings import TuneSettings
from detectkit.config.metric_config import AutoTuneConfig

# Cap the scored training span when the user doesn't pin max_history, so tuning
# stays responsive on very long histories (recent data is the most relevant).
DEFAULT_TRAIN_CAP = 50_000


def resolve_scoring(scoring_override: str | None, autotune_cfg: AutoTuneConfig) -> ScoringMetric:
    """Resolve the scoring metric: CLI override > config > MCC default.

    Raises ``ValueError`` on an unknown name (callers translate as they see fit).
    """
    value = scoring_override or autotune_cfg.scoring_metric or ScoringMetric.MCC.value
    try:
        return ScoringMetric(value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in ScoringMetric)
        raise ValueError(f"Invalid scoring metric '{value}'. Allowed: {allowed}") from exc


def build_settings(*, scoring: ScoringMetric, autotune_cfg: AutoTuneConfig) -> TuneSettings:
    """Map an ``AutoTuneConfig`` block (+ resolved scoring) to ``TuneSettings``."""
    return TuneSettings(
        metric=scoring,
        beta=autotune_cfg.beta,
        fold_count=autotune_cfg.folds,
        stability_lambda=autotune_cfg.stability_lambda,
        allowed_detector_types=autotune_cfg.detector_types,
        allowed_seasonality=autotune_cfg.seasonality_candidates,
        force_seasonality=autotune_cfg.force_seasonality,
        fixed_params=dict(autotune_cfg.fixed_params),
        max_history=autotune_cfg.max_history,
    )


def cap_history(data: dict[str, np.ndarray], max_history: int | None) -> dict[str, np.ndarray]:
    """Keep the most recent ``max_history`` (or the default cap) points."""
    n = len(data["timestamp"])
    cap = max_history if max_history is not None else DEFAULT_TRAIN_CAP
    if n <= cap:
        return data
    return {
        "timestamp": data["timestamp"][-cap:],
        "value": data["value"][-cap:],
        "seasonality_data": data["seasonality_data"][-cap:],
        "seasonality_columns": data["seasonality_columns"],
    }


def autotune_from_data(
    *,
    metric_name: str,
    data: dict[str, np.ndarray],
    labels: IncidentLabels,
    interval_seconds: int,
    autotune_cfg: AutoTuneConfig,
    scoring_override: str | None = None,
    on_stage: Callable[[str, str], None] | None = None,
) -> AutoTuneResult:
    """Run the full autotune engine on an in-memory series + labels.

    Caps the history, resolves the scoring metric, projects ``labels`` onto the
    (capped) grid as ground truth, builds the settings and runs the engine.
    Pure: no DB, no filesystem, no lock — the caller decides what to persist.
    """
    data = cap_history(data, autotune_cfg.max_history)
    scoring = resolve_scoring(scoring_override, autotune_cfg)
    ground_truth = labels.to_ground_truth(data["timestamp"], interval_seconds)
    settings = build_settings(scoring=scoring, autotune_cfg=autotune_cfg)
    return run_autotune_engine(
        metric_name=metric_name,
        data=data,
        ground_truth=ground_truth,
        interval_seconds=interval_seconds,
        settings=settings,
        on_stage=on_stage,
    )
