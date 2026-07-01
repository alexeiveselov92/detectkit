"""Write a hand-tuned detector config back into a metric YAML — safely.

The single mutation seam for ``dtk tune``. Mirrors the validate-before-write
discipline of ``autotune/config_emitter.py`` (PyYAML only, no round-trip
dependency) but, unlike autotune, edits the metric **in place** — so it first
**archives the previous YAML verbatim** under ``metrics/.history/<metric>/`` and
only overwrites after the new config validates. A broken or unparseable config
never lands; the original is always recoverable from the archive.

Write-back **merges**: each tuned detector rewrites only its own slot in the
metric's ``detectors:`` list; every detector the cockpit didn't touch (a
``manual_bounds`` floor, a ``prophet``/``timesfm`` detector, another windowed
detector) is preserved **verbatim**. This is the fix for the earlier bug where the
whole list was replaced with the single tuned detector — silently dropping the
others and, when an alert used ``min_detectors >= 2``, permanently killing it.
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

# Execution-only params the tuner never surfaces: they steer the pipeline (when to
# start detecting / how big a batch), not the detection maths, so the detector
# constructor rejects them. Carried over verbatim from the slot being retuned, but
# stripped before constructing the detector for validation.
_EXECUTION_PARAMS = ("start_time", "batch_size")

_RULE = "# " + "─" * 61


@dataclass(frozen=True)
class TunedDetector:
    """One detector the cockpit is writing back, plus the slot it edits.

    ``index`` is the position in the metric's existing ``detectors:`` list this
    detector replaces; ``None`` (or an out-of-range index) means "append a new
    detector", so the existing ones are always preserved.
    """

    type: str
    params: dict[str, Any]
    index: int | None = None


@dataclass(frozen=True)
class AppliedConfig:
    """Result of applying a tuned config: the metric, the file paths, and what changed."""

    metric: str
    saved: Path
    archived: Path
    # Detector types written this Apply and those left untouched (preserved verbatim),
    # so the CLI can reassure the user that a multi-detector metric kept its others.
    updated: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()


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


def _changed_line(updated: list[str], preserved: list[str]) -> str:
    """The header line stating exactly which detectors were rewritten vs kept.

    Honest about a multi-detector metric: the previous "Only the detector block was
    changed" masked that the whole list was replaced (dropping the others). Now it
    names what was updated and what was preserved verbatim.
    """
    upd = ", ".join(updated) if updated else "none"
    line = f"# Updated detector(s): {upd}"
    if preserved:
        line += f"; preserved verbatim: {', '.join(preserved)}"
    line += ". The alert consecutive window may also have changed."
    return line


def _header(
    metric: str, archive_rel: str, stamp: str, updated: list[str], preserved: list[str]
) -> str:
    return "\n".join(
        [
            _RULE,
            f"# Hand-tuned via `dtk tune`  ({stamp})",
            f"# Previous config archived at: {archive_rel}",
            _changed_line(updated, preserved),
            f"# Reproduce: dtk tune --select {metric}",
            _RULE,
        ]
    )


def _merge_detector(existing: list[Any], td: TunedDetector) -> tuple[dict[str, Any], int, str]:
    """Validate one tuned detector and return ``(new_dict, slot, preserved_from)``.

    ``slot`` is the index it lands at (its own index when in range, else the append
    position). Execution params (``start_time`` / ``batch_size``) the cockpit never
    exposes are carried over from the slot it replaces so a retune doesn't silently
    drop them. Raises ``ValueError`` (writing nothing upstream) on a bad type/params.
    """
    dtype = td.type.lower()
    if dtype not in _TUNABLE_TYPES:
        raise ValueError(
            f"detector type '{td.type}' is not tunable; "
            f"choose one of: {', '.join(sorted(_TUNABLE_TYPES))}"
        )
    # Strip non-param keys that may ride along from the client, then validate the
    # params by actually constructing the detector (its `_validate_params` runs).
    params = {k: v for k, v in td.params.items() if k not in ("type", "consecutive_anomalies")}

    idx = td.index
    old_params: dict[str, Any] = {}
    if idx is not None and 0 <= idx < len(existing):
        slot = idx  # replace this slot
        entry = existing[idx]
        if isinstance(entry, dict) and isinstance(entry.get("params"), dict):
            old_params = entry["params"]
    else:
        slot = len(existing)  # append (out-of-range / None index)
    # Carry over execution-only params the tuner doesn't surface (start_time picks up
    # detection; batch_size is a throughput knob) so re-tuning doesn't wipe them.
    for k in _EXECUTION_PARAMS:
        if k in old_params and k not in params:
            params[k] = old_params[k]

    # Validate by constructing the detector — but the constructor only takes
    # algorithm params, so strip the execution params first (they're re-emitted, not
    # validated, exactly as the pipeline treats them).
    algo = {k: v for k, v in params.items() if k not in _EXECUTION_PARAMS}
    DetectorFactory.create(dtype, algo)  # raises ValueError on bad params
    return {"type": dtype, "params": params}, slot, dtype


def apply_tuned_config(
    *,
    original_path: Path,
    project_root: Path,
    detectors: list[TunedDetector],
    consecutive_anomalies: int | None = None,
    now: datetime | None = None,
) -> AppliedConfig:
    """Validate, archive, then re-emit ``original_path`` with the tuned detector(s) merged in.

    **Merges** rather than replaces: each :class:`TunedDetector` rewrites only its
    own slot (by ``index``) and every other detector in the metric — a
    ``manual_bounds`` floor, a ``prophet``/``timesfm`` detector, or another tuned
    detector the user didn't touch — is kept **verbatim**. This is the fix for the
    silent data-loss bug where the whole ``detectors:`` list was overwritten with
    the single tuned detector (which quietly killed a ``min_detectors >= 2`` alert).

    Returns the :class:`AppliedConfig` (metric name + written/archive paths + the
    detector types updated vs preserved). Raises ``ValueError`` (writing nothing) on
    an unknown/untunable detector type, invalid detector params, an empty detector
    list, or a config body that fails ``MetricConfig`` validation.
    """
    if not detectors:
        raise ValueError("no detector to apply")

    if consecutive_anomalies is not None and consecutive_anomalies < 1:
        raise ValueError("consecutive_anomalies must be at least 1")

    original_text = original_path.read_text(encoding="utf-8")
    raw = yaml.safe_load(original_text)
    if not isinstance(raw, dict):
        raise ValueError(f"metric config is empty or malformed: {original_path}")

    # Support the nested `metric: { ... }` form (see MetricConfig.from_yaml_file).
    nested = isinstance(raw.get("metric"), dict)
    body: dict[str, Any] = raw["metric"] if nested else raw

    existing = body.get("detectors")
    merged: list[Any] = list(existing) if isinstance(existing, list) else []

    # Validate + merge each tuned detector before touching the filesystem. In-range
    # indices replace their slot; out-of-range/None indices append (preserving all
    # existing detectors either way).
    updated_slots: set[int] = set()
    updated_types: list[str] = []
    for td in detectors:
        new_det, slot, dtype = _merge_detector(merged, td)
        if slot < len(merged):
            merged[slot] = new_det
        else:
            merged.append(new_det)
        updated_slots.add(slot)
        updated_types.append(dtype)

    body["detectors"] = merged
    preserved_types = [
        str(d.get("type"))
        for i, d in enumerate(merged)
        if i not in updated_slots and isinstance(d, dict)
    ]

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
    new_text = (
        f"{_header(metric_name, archive_rel, stamp, updated_types, preserved_types)}\n{yaml_body}"
    )
    original_path.write_text(new_text, encoding="utf-8")

    return AppliedConfig(
        metric=metric_name,
        saved=original_path,
        archived=archive_path,
        updated=tuple(updated_types),
        preserved=tuple(preserved_types),
    )
