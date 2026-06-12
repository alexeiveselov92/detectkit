"""Dataclasses and metadata helpers shared by every orchestrator mixin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from detectkit.utils.datetime_utils import to_naive_utc
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
    """Conditions that turn a sequence of detections into an alert.

    Defaults mirror :class:`detectkit.config.metric_config.AlertConfig`
    so direct API users get the same behavior as YAML users.
    """

    min_detectors: int = 1
    direction: str = "same"  # "any", "same", "up", "down"
    consecutive_anomalies: int = 3


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


def hydrate_detection_records(rows: list[dict]) -> list[DetectionRecord]:
    """Build :class:`DetectionRecord` rows from ``get_recent_detections`` output.

    Emits one record *per detector per timestamp* (the orchestrator counts
    records to evaluate ``min_detectors``). Input rows are timestamp-DESC as
    returned by SQL; output is oldest→newest. Timestamps are normalized to
    ``datetime64[ms]`` so grid-adjacency arithmetic is well-defined.
    """
    records: list[DetectionRecord] = []
    for row in reversed(rows):
        raw_ts = row["timestamp"]
        if isinstance(raw_ts, datetime):
            raw_ts = to_naive_utc(raw_ts)
        timestamp = np.datetime64(raw_ts, "ms")
        metadata_list = row.get("detection_metadata_list") or [None] * len(row["detector_ids"])
        for i in range(len(row["detector_ids"])):
            is_anomaly = bool(row["is_anomaly_flags"][i])
            metadata = _parse_detection_metadata(metadata_list[i])
            try:
                severity = float(metadata.get("severity", 0.0) or 0.0)
            except (TypeError, ValueError):
                severity = 0.0

            records.append(
                DetectionRecord(
                    timestamp=timestamp,
                    detector_name=row["detector_names"][i],
                    detector_id=row["detector_ids"][i],
                    detector_params=row["detector_params_list"][i],
                    value=row["value"],
                    is_anomaly=is_anomaly,
                    confidence_lower=row["confidence_lowers"][i],
                    confidence_upper=row["confidence_uppers"][i],
                    direction=_direction_from_metadata(metadata, is_anomaly),
                    severity=severity,
                    detection_metadata=metadata,
                )
            )

    return records
