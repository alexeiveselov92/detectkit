"""Decision logic: ``should_alert`` and the consecutive-anomaly helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.utils.datetime_utils import now_utc, to_aware_utc


class _DecisionMixin(_OrchestratorBase):
    def should_alert(
        self,
        recent_detections: List[DetectionRecord],
    ) -> Tuple[bool, Optional[AlertData]]:
        """Decide whether to fire an alert from recent detections.

        Steps (cheap → expensive):
            1. Bail out on empty input.
            2. Honour the alert cooldown so we don't spam channels.
            3. Require ``min_detectors`` triggering on the latest point.
            4. Require ``consecutive_anomalies`` matching the direction.
        """
        if not recent_detections:
            return False, None

        # Cooldown is checked first so a noisy run doesn't waste effort.
        if self._is_in_cooldown():
            return False, None

        detections_by_time = self._group_by_timestamp(recent_detections)
        timestamps_sorted = sorted(detections_by_time.keys(), reverse=True)

        latest_anomalies = [
            d for d in detections_by_time[timestamps_sorted[0]] if d.is_anomaly
        ]
        if len(latest_anomalies) < self.conditions.min_detectors:
            return False, None

        consecutive = self._count_consecutive_anomalies(
            detections_by_time, timestamps_sorted
        )
        if consecutive < self.conditions.consecutive_anomalies:
            return False, None

        return True, self._build_alert_data(latest_anomalies, consecutive)

    def _count_consecutive_anomalies(
        self,
        detections_by_time: Dict[np.datetime64, List[DetectionRecord]],
        timestamps_sorted: List[np.datetime64],
    ) -> int:
        """Walk timestamps newest→oldest counting matching anomalies."""
        direction_condition = self.conditions.direction
        consecutive = 0
        prev_direction: Optional[str] = None

        for ts in timestamps_sorted:
            anomalies = [d for d in detections_by_time[ts] if d.is_anomaly]
            if len(anomalies) < self.conditions.min_detectors:
                break

            current_direction = anomalies[0].direction

            if direction_condition == "any":
                consecutive += 1
            elif direction_condition == "same":
                if prev_direction is None:
                    consecutive = 1
                    prev_direction = current_direction
                elif current_direction == prev_direction:
                    consecutive += 1
                else:
                    break  # direction flipped → stop counting
            elif direction_condition == "up":
                if current_direction == "up":
                    consecutive += 1
                else:
                    break
            elif direction_condition == "down":
                if current_direction == "down":
                    consecutive += 1
                else:
                    break
            else:
                # Unknown direction policy — treat as "any" to stay safe.
                consecutive += 1

        return consecutive

    def _build_alert_data(
        self,
        anomalies: List[DetectionRecord],
        consecutive_count: int,
    ) -> AlertData:
        primary = anomalies[0]

        if len(anomalies) > 1:
            max_severity = max(d.severity for d in anomalies)
            detector_names = [d.detector_name for d in anomalies]
            detector_name = f"{len(anomalies)} detectors"
            detector_params = "; ".join(
                f"{d.detector_name}: {d.detector_params}" for d in anomalies
            )
            combined_metadata = {
                "detectors": detector_names,
                "count": len(anomalies),
            }
            for i, d in enumerate(anomalies):
                combined_metadata[f"detector_{i}_metadata"] = d.detection_metadata
        else:
            max_severity = primary.severity
            detector_name = primary.detector_name
            detector_params = primary.detector_params
            combined_metadata = primary.detection_metadata

        return AlertData(
            metric_name=self.metric_name,
            timestamp=primary.timestamp,
            timezone=self.timezone_display,
            value=primary.value,
            confidence_lower=primary.confidence_lower,
            confidence_upper=primary.confidence_upper,
            detector_name=detector_name,
            detector_params=detector_params,
            direction=primary.direction,
            severity=max_severity,
            detection_metadata=combined_metadata,
            consecutive_count=consecutive_count,
            description=self.description,
            mentions=self.mentions,
        )

    def get_last_complete_point(self, now: Optional[datetime] = None) -> datetime:
        """Floor ``now`` to the previous fully completed interval boundary."""
        if now is None:
            now = now_utc()
        now = to_aware_utc(now)

        interval_seconds = self.interval.seconds
        floored = (int(now.timestamp()) // interval_seconds) * interval_seconds
        last_complete = floored - interval_seconds
        return datetime.fromtimestamp(last_complete, tz=timezone.utc)
