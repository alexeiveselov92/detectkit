"""Public surface of the alert-orchestrator package."""

from detectkit.alerting.orchestrator._types import (
    AlertConditions,
    DetectionRecord,
    _direction_from_metadata,
    _parse_detection_metadata,
)
from detectkit.alerting.orchestrator.orchestrator import AlertOrchestrator

__all__ = [
    "AlertOrchestrator",
    "AlertConditions",
    "DetectionRecord",
    # Re-exported for callers (notably TaskManager) that build
    # DetectionRecord rows manually before handing them to the orchestrator.
    "_direction_from_metadata",
    "_parse_detection_metadata",
]
