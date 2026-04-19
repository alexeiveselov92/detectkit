"""Shared state for orchestrator mixins."""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from detectkit.alerting.orchestrator._types import (
    AlertConditions,
    DetectionRecord,
)
from detectkit.core.interval import Interval


class _OrchestratorBase:
    def __init__(
        self,
        metric_name: str,
        interval: Interval,
        alert_config_id: str,
        conditions: Optional[AlertConditions] = None,
        timezone_display: str = "UTC",
        internal=None,  # InternalTablesManager
        alert_config=None,  # AlertConfig
        description: Optional[str] = None,
        mentions: Optional[List[str]] = None,
    ):
        self.metric_name = metric_name
        self.interval = interval
        self.alert_config_id = alert_config_id
        self.conditions = conditions or AlertConditions()
        self.timezone_display = timezone_display
        self.internal = internal
        self.alert_config = alert_config
        self.description = description
        self.mentions = mentions or []

    @staticmethod
    def _group_by_timestamp(
        detections: List[DetectionRecord],
    ) -> Dict[np.datetime64, List[DetectionRecord]]:
        grouped: Dict[np.datetime64, List[DetectionRecord]] = {}
        for d in detections:
            grouped.setdefault(d.timestamp, []).append(d)
        return grouped
