"""Dataclasses and metadata helpers shared by every orchestrator mixin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from detectkit.utils.json_utils import json_loads


def _parse_detection_metadata(metadata: Any) -> dict:
    """Coerce a stored metadata payload into a plain ``dict``.

    Accepts the shapes that come back from the database (``dict``,
    JSON ``str``/``bytes``) and degrades to ``{}`` on any malformed
    input rather than raising — alerting must never crash on bad data.
    """
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, (bytes, bytearray)):
        try:
            metadata = metadata.decode("utf-8")
        except Exception:
            return {}
    if isinstance(metadata, str):
        if not metadata:
            return {}
        try:
            parsed = json_loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _direction_from_metadata(metadata: Any, is_anomaly: bool) -> str:
    """Resolve alert direction (``up``/``down``/``none``) from metadata.

    Detectors authoritatively write ``"below"``/``"above"`` into
    ``detection_metadata``; we treat that as the source of truth because
    confidence-bound reconstruction does not work for one-sided detectors
    (e.g. ManualBounds with only ``upper_bound`` set).
    """
    if not is_anomaly:
        return "none"
    parsed = _parse_detection_metadata(metadata)
    raw = parsed.get("direction")
    if raw == "below":
        return "down"
    if raw == "above":
        return "up"
    return "none"


@dataclass
class AlertConditions:
    """Conditions that turn a sequence of detections into an alert."""

    min_detectors: int = 1
    direction: str = "any"  # "any", "same", "up", "down"
    consecutive_anomalies: int = 1


@dataclass
class DetectionRecord:
    """A single detection row hydrated from ``_dtk_detections``."""

    timestamp: np.datetime64
    detector_name: str
    detector_id: str
    detector_params: str  # JSON-encoded params used for grouping
    value: float
    is_anomaly: bool
    confidence_lower: float | None
    confidence_upper: float | None
    direction: str  # "up", "down", "none"
    severity: float
    detection_metadata: dict
