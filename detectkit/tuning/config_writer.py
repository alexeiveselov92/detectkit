"""Write a hand-tuned detector config back into a metric YAML — safely.

The single mutation seam for ``dtk tune``. Mirrors the validate-before-write
discipline of ``autotune/config_emitter.py`` (PyYAML only, no round-trip
dependency) but, unlike autotune, edits the metric **in place** — so it first
**archives the previous YAML verbatim** under ``metrics/.history/<metric>/`` and
only overwrites after the new config validates. A broken or unparseable config
never lands; the original is always recoverable from the archive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from detectkit.config.metric_config import MetricConfig
from detectkit.detectors.factory import DetectorFactory

# The detector types the interactive tuner can emit: the windowed statistical
# detectors plus the stateless manual_bounds (lower/upper threshold) detector,
# whose bounds the tuner lets you drag against the real series.
_TUNABLE_TYPES = {"mad", "zscore", "iqr", "manual_bounds"}

_RULE = "# " + "─" * 61


@dataclass(frozen=True)
class AppliedConfig:
    """Result of applying a tuned config: the metric and the two file paths."""

    metric: str
    saved: Path
    archived: Path


def _stamp(now: datetime | None = None) -> str:
    """UTC filesystem-safe timestamp (``20260624T101530Z``)."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


def _apply_consecutive(body: dict[str, Any], consecutive: int) -> None:
    """Set ``consecutive_anomalies`` on the metric's first alerting config.

    Accepts the YAML's normalized forms (a single dict or a list of dicts).
    Does nothing when the metric has no ``alerting`` block — tuning never invents
    alerting that wasn't configured.
    """
    alerting = body.get("alerting")
    if isinstance(alerting, dict):
        alerting["consecutive_anomalies"] = consecutive
    elif isinstance(alerting, list) and alerting and isinstance(alerting[0], dict):
        alerting[0]["consecutive_anomalies"] = consecutive


def _header(metric: str, archive_rel: str, stamp: str) -> str:
    return "\n".join(
        [
            _RULE,
            f"# Hand-tuned via `dtk tune`  ({stamp})",
            f"# Previous config archived at: {archive_rel}",
            "# Only the detector block (and the alert consecutive window) was changed.",
            f"# Reproduce: dtk tune --select {metric}",
            _RULE,
        ]
    )


def apply_tuned_config(
    *,
    original_path: Path,
    project_root: Path,
    detector_type: str,
    detector_params: dict[str, Any],
    consecutive_anomalies: int | None = None,
    now: datetime | None = None,
) -> AppliedConfig:
    """Validate, archive, then overwrite ``original_path`` with the tuned detector.

    Returns the :class:`AppliedConfig` (metric name + written + archive paths).
    Raises ``ValueError`` (writing nothing) on an unknown/untunable detector
    type, invalid detector params, or a config body that fails ``MetricConfig``
    validation.
    """
    dtype = detector_type.lower()
    if dtype not in _TUNABLE_TYPES:
        raise ValueError(
            f"detector type '{detector_type}' is not tunable; "
            f"choose one of: {', '.join(sorted(_TUNABLE_TYPES))}"
        )

    # Strip non-param keys that may ride along from the client, then validate the
    # params by actually constructing the detector (its `_validate_params` runs).
    params = {
        k: v for k, v in detector_params.items() if k not in ("type", "consecutive_anomalies")
    }
    DetectorFactory.create(dtype, params)  # raises ValueError on bad params

    if consecutive_anomalies is not None and consecutive_anomalies < 1:
        raise ValueError("consecutive_anomalies must be at least 1")

    original_text = original_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(original_text)
    if not isinstance(raw, dict):
        raise ValueError(f"metric config is empty or malformed: {original_path}")

    # Support the nested `metric: { ... }` form (see MetricConfig.from_yaml_file).
    nested = isinstance(raw.get("metric"), dict)
    body: dict[str, Any] = raw["metric"] if nested else raw

    body["detectors"] = [{"type": dtype, "params": params}]
    if consecutive_anomalies is not None:
        _apply_consecutive(body, consecutive_anomalies)

    # Validate the whole metric before touching the filesystem.
    validated = MetricConfig.model_validate(body)
    metric_name = validated.name

    stamp = _stamp(now)
    archive_dir = project_root / "metrics" / ".history" / metric_name
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{metric_name}-{stamp}.yml"
    archive_path.write_text(original_text, encoding="utf-8")

    try:
        archive_rel = str(archive_path.relative_to(project_root))
    except ValueError:
        archive_rel = str(archive_path)

    yaml_body = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False, allow_unicode=True)
    new_text = f"{_header(metric_name, archive_rel, stamp)}\n{yaml_body}"
    original_path.write_text(new_text, encoding="utf-8")

    return AppliedConfig(metric=metric_name, saved=original_path, archived=archive_path)
