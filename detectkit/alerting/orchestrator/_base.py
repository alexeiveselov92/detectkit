"""Shared state for orchestrator mixins."""

from __future__ import annotations

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
        conditions: AlertConditions | None = None,
        timezone_display: str = "UTC",
        internal=None,  # InternalTablesManager
        alert_config=None,  # AlertConfig
        description: str | None = None,
        mentions: list[str] | None = None,
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
        detections: list[DetectionRecord],
    ) -> dict[np.datetime64, list[DetectionRecord]]:
        grouped: dict[np.datetime64, list[DetectionRecord]] = {}
        for d in detections:
            grouped.setdefault(d.timestamp, []).append(d)
        return grouped
