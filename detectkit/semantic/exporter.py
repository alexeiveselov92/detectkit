"""Export native detectkit metrics into an OSI fragment (the CI hedge).

``dtk osi export`` publishes detectkit's metrics into the governed layer: each
metric becomes an OSI ``metrics`` entry carrying its ``ai_context`` (so BI / the
agent see the same business meaning) plus a **lossless** ``custom_extensions``
block under the ``detectkit`` vendor namespace that round-trips the full detect /
alert config.

Honesty about the measure: a detectkit metric's query is an arbitrary
GROUP-BY-time SQL that does **not** cleanly decompose into a portable OSI
``expression`` measure, so the emitted ``expression`` is a placeholder and the
real, exact definition rides in ``custom_extensions[detectkit].data`` (a JSON
string, per the verified spec). Other OSI tools still get the metric's name +
``ai_context``; a detectkit-aware reader gets everything.
"""

from __future__ import annotations

import json
from typing import Any

from detectkit.config.metric_config import MetricConfig
from detectkit.semantic.osi_model import DETECTKIT_VENDOR

_PLACEHOLDER_EXPR = (
    "/* detectkit time-series metric — definition in custom_extensions[detectkit] */"
)


def _ai_context_osi(config: MetricConfig) -> dict[str, Any] | None:
    """The metric's ai_context in OSI shape (dropping empty fields), or None."""
    ac = config.ai_context
    if ac is None:
        return None
    out: dict[str, Any] = {}
    if ac.instructions:
        out["instructions"] = ac.instructions
    if ac.synonyms:
        out["synonyms"] = list(ac.synonyms)
    if ac.examples:
        out["examples"] = list(ac.examples)
    return out or None


def _detectkit_payload(config: MetricConfig) -> dict[str, Any]:
    """The full native config detectkit needs to reconstruct the metric exactly."""
    payload: dict[str, Any] = {
        "interval": config.interval,
        "detectors": [{"type": d.type, "params": d.params} for d in config.detectors],
    }
    if config.query is not None:
        payload["query"] = config.query
    if config.query_file is not None:
        payload["query_file"] = str(config.query_file)
    if config.seasonality_columns:
        payload["seasonality_columns"] = list(config.seasonality_columns)
    if config.alerting:
        payload["alerting"] = [
            a.model_dump(exclude_defaults=True, exclude_none=True) for a in config.alerting
        ]
    if config.tags:
        payload["tags"] = list(config.tags)
    return payload


def export_metric_to_osi(config: MetricConfig) -> dict[str, Any]:
    """Build one OSI ``metrics[]`` entry for a detectkit metric."""
    entry: dict[str, Any] = {
        "name": config.name,
        "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": _PLACEHOLDER_EXPR}]},
        "custom_extensions": [
            {
                "vendor_name": DETECTKIT_VENDOR,
                "data": json.dumps(_detectkit_payload(config), default=str, sort_keys=True),
            }
        ],
    }
    if config.description:
        entry["description"] = config.description
    ai_ctx = _ai_context_osi(config)
    if ai_ctx:
        entry["ai_context"] = ai_ctx
    return entry


def export_models(
    configs: list[MetricConfig], *, model_name: str = "detectkit_export"
) -> dict[str, Any]:
    """Assemble a full OSI document (``{semantic_model: [...]}``) from metrics."""
    return {
        "semantic_model": [
            {
                "name": model_name,
                "metrics": [export_metric_to_osi(c) for c in configs],
            }
        ]
    }
