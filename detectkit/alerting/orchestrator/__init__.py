"""Public surface of the alert-orchestrator package."""

from detectkit.alerting.orchestrator._replay import ReplayedEvent
from detectkit.alerting.orchestrator._types import (
    AlertConditions,
    DetectionRecord,
    _direction_from_metadata,
    _parse_detection_metadata,
    hydrate_detection_records,
)
from detectkit.alerting.orchestrator.orchestrator import AlertOrchestrator

__all__ = [
    "AlertOrchestrator",
    "AlertConditions",
    "DetectionRecord",
    "ReplayedEvent",
    # Shared hydration of DetectionRecord rows from get_recent_detections
    # output (used by TaskManager and the recovery mixin).
    "hydrate_detection_records",
    "_direction_from_metadata",
    "_parse_detection_metadata",
]
