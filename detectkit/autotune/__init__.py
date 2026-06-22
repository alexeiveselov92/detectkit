"""detectkit autotune engine.

Given a metric's loaded series (+ optional labeled incidents), automatically
chooses the seasonality grouping, detector type, hyperparameters and history
window, cross-validates the choice, and returns an :class:`AutoTuneResult`.

Pure and DB-free: the engine operates on the in-memory ``data`` dict and reuses
the existing ``WindowedStatDetector`` / ``DetectorFactory``. The CLI command
(``dtk autotune``) handles loading, persistence, config emission and cleanup.
"""

from __future__ import annotations

from detectkit.autotune._base import AutoTuneError, _AutoTuneBase
from detectkit.autotune._types import ScoringMetric, TuneMode
from detectkit.autotune.autotuner import AutoTuner, run_autotune_engine
from detectkit.autotune.config_emitter import compute_run_id, emit_tuned_config
from detectkit.autotune.html_labeler import render_labeler_html
from detectkit.autotune.labels import (
    GroundTruth,
    IncidentLabels,
    parse_incident_labels,
    parse_labels_file,
)
from detectkit.autotune.result import AutoTuneResult
from detectkit.autotune.settings import TuneSettings

__all__ = [
    "AutoTuner",
    "AutoTuneError",
    "AutoTuneResult",
    "GroundTruth",
    "IncidentLabels",
    "ScoringMetric",
    "TuneMode",
    "TuneSettings",
    "_AutoTuneBase",
    "compute_run_id",
    "emit_tuned_config",
    "parse_incident_labels",
    "parse_labels_file",
    "render_labeler_html",
    "run_autotune_engine",
]
