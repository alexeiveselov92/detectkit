"""Emit the annotated, ready-to-run tuned metric config.

Builds a new metric YAML named ``<original>__tuned_<run_id>`` led by a
``#``-comment block that walks the entire decision log, followed by the real
config (single chosen detector + chosen seasonality + copied query/alerting).
The body is validated through ``MetricConfig`` before it is ever written, so a
broken config is never emitted. PyYAML only — no new dependency.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from detectkit.autotune.result import AutoTuneResult
from detectkit.config.metric_config import MetricConfig
from detectkit.utils.json_utils import json_dumps_sorted

_RULE = "# " + "─" * 61
_STAGE_LABELS = {
    "seasonality": "SEASONALITY",
    "detector_select": "DETECTOR",
    "grid_search": "GRID SEARCH",
    "window": "WINDOW",
}


def compute_run_id(result: AutoTuneResult) -> str:
    """Deterministic 6-hex id from the run's inputs + outputs (no wall-clock)."""
    payload = {
        "metric": result.metric_name,
        "training_start": result.training_start.isoformat() if result.training_start else None,
        "training_end": result.training_end.isoformat() if result.training_end else None,
        "labels": result.labels_summary,
        "detector_type": result.chosen_detector_type,
        "detector_params": result.chosen_detector_params,
        "seasonality": result.chosen_seasonality,
        "scoring_metric": result.scoring_metric,
    }
    return hashlib.sha256(json_dumps_sorted(payload).encode()).hexdigest()[:6]


def _flatten_scalar_seasonality(seasonality: list | None) -> list[str]:
    if not seasonality:
        return []
    cols: list[str] = []
    for comp in seasonality:
        for c in [comp] if isinstance(comp, str) else comp:
            if c not in cols:
                cols.append(c)
    return cols


def _build_alerting(original: MetricConfig, result: AutoTuneResult) -> list[dict] | None:
    if not original.alerting:
        return None
    first = original.alerting[0].model_dump(exclude_none=True, exclude_defaults=True)
    if result.consecutive_anomalies is not None:
        first["consecutive_anomalies"] = result.consecutive_anomalies
    first["min_detectors"] = 1  # single tuned detector now
    return [first]


def _build_body(original: MetricConfig, result: AutoTuneResult, new_name: str) -> dict[str, Any]:
    body: dict[str, Any] = {"name": new_name}
    if original.description:
        body["description"] = original.description
    if original.tags:
        body["tags"] = original.tags
    if original.profile:
        body["profile"] = original.profile
    if original.query is not None:
        body["query"] = original.query
    elif original.query_file is not None:
        body["query_file"] = str(original.query_file)
    if original.query_columns is not None:
        body["query_columns"] = original.query_columns.model_dump(exclude_none=True)
    body["interval"] = original.interval
    if result.training_start is not None:
        body["loading_start_time"] = result.training_start.strftime("%Y-%m-%d %H:%M:%S")
    elif original.loading_start_time:
        body["loading_start_time"] = original.loading_start_time
    body["loading_batch_size"] = original.loading_batch_size

    scalar_cols = _flatten_scalar_seasonality(result.chosen_seasonality)
    if scalar_cols:
        body["seasonality_columns"] = scalar_cols
    elif original.seasonality_columns:
        body["seasonality_columns"] = original.seasonality_columns

    body["detectors"] = [
        {"type": result.chosen_detector_type, "params": result.chosen_detector_params}
    ]
    alerting = _build_alerting(original, result)
    if alerting is not None:
        body["alerting"] = alerting
    body["enabled"] = True
    return body


def _build_comments(result: AutoTuneResult, source_label: str, run_id: str) -> str:
    lines = [
        _RULE,
        f"# Auto-tuned by `dtk autotune`  (run_id: {run_id})",
        f"# Generated from: {source_label}",
        "#",
    ]
    if result.training_start and result.training_end:
        lines.append(
            f"# Training period : {result.training_start:%Y-%m-%d %H:%M:%S} → "
            f"{result.training_end:%Y-%m-%d %H:%M:%S} UTC ({result.n_points:,} points)"
        )
    summary = result.labels_summary
    lines.append(
        f"# Labels          : {result.mode} — {summary.get('intervals', 0)} interval(s), "
        f"{summary.get('points', 0)} point(s), "
        f"{summary.get('positive_grid_points', 0)} labeled grid point(s)"
    )
    folds = " ".join(f"{f:.2f}" for f in result.cv_per_fold) or "—"
    lines.append(
        f"# Scoring metric  : {result.scoring_metric} = {result.score:.3f}  (CV folds: {folds})"
    )
    lines.append("#")
    for entry in result.decision_log:
        label = _STAGE_LABELS.get(entry.get("stage", ""))
        if label:
            lines.append(f"# {label:<12}: {entry.get('message', '')}")
    lines.append("#")
    lines.append(f"# Reproduce: dtk autotune --select {result.metric_name}")
    lines.append(_RULE)
    return "\n".join(lines)


def emit_tuned_config(
    *,
    original_config: MetricConfig,
    original_path: Path,
    result: AutoTuneResult,
    project_root: Path,
    run_id: str | None = None,
) -> tuple[Path, str, str]:
    """Return ``(out_path, yaml_text, run_id)`` for the tuned config.

    Validates the body through ``MetricConfig`` before returning so callers
    never write an unparseable file. Does not touch the filesystem.
    """
    run_id = run_id or compute_run_id(result)
    new_name = f"{original_config.name}__tuned_{run_id}"
    body = _build_body(original_config, result, new_name)

    # Fail fast on an invalid body rather than writing a broken config.
    MetricConfig.model_validate(body)

    try:
        source_label = str(original_path.relative_to(project_root))
    except ValueError:
        source_label = original_path.name

    comments = _build_comments(result, source_label, run_id)
    yaml_body = yaml.safe_dump(body, sort_keys=False, default_flow_style=False, allow_unicode=True)
    text = f"{comments}\n{yaml_body}"

    out_path = project_root / "metrics" / f"{original_path.stem}__tuned_{run_id}.yml"
    return out_path, text, run_id
