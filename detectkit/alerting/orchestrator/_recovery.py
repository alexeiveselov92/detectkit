"""Recovery decision and reconstruction logic."""

from __future__ import annotations

from datetime import datetime

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.alerting.orchestrator._types import (
    DetectionRecord,
    hydrate_detection_records,
)


class _RecoveryMixin(_OrchestratorBase):
    def should_send_recovery(
        self,
        recent_detections: list[DetectionRecord],
    ) -> tuple[bool, AlertData | None]:
        """Decide whether to send a recovery notification.

        Conditions (all must hold):
            1. A previous alert has been sent (``last_alert_sent`` exists).
            2. The metric has actually recovered (no blocking anomalies).
            3. We haven't already notified recovery for this incident.
        """
        if not self.internal:
            return False, None

        last_alert = self.internal.get_last_alert_timestamp(self.metric_name, self.alert_config_id)
        if not last_alert:
            return False, None

        last_recovery = self.internal.get_last_recovery_timestamp(
            self.metric_name, self.alert_config_id
        )
        if last_recovery and last_recovery >= last_alert:
            return False, None  # already notified for this incident

        if not self._check_recovery_since_last_alert(last_alert):
            return False, None

        recovery_data = self._build_recovery_data(recent_detections)
        if not recovery_data:
            return False, None
        return True, recovery_data

    def _check_recovery_since_last_alert(self, last_alert_timestamp: datetime) -> bool:
        """Return ``True`` when the metric has recovered since *last_alert_timestamp*.

        Direction-aware: a "down"-only alert is not blocked by a fresh
        "up" anomaly, since the alert condition no longer holds.
        """
        if not self.internal:
            return False

        last_point = self.get_last_complete_point()
        # +5 for safety margin so we don't truncate the consecutive window.
        num_points = self.conditions.consecutive_anomalies + 5

        recent_detections = self.internal.get_recent_detections(
            metric_name=self.metric_name,
            last_point=last_point,
            num_points=num_points,
            created_after=last_alert_timestamp,
        )
        if not recent_detections:
            # No fresh detections at all → assume recovery.
            return True

        records = hydrate_detection_records(recent_detections)

        detections_by_time = self._group_by_timestamp(records)
        timestamps_sorted = sorted(detections_by_time.keys(), reverse=True)
        latest_anomalies = [d for d in detections_by_time[timestamps_sorted[0]] if d.is_anomaly]

        direction_condition = self.conditions.direction
        if direction_condition == "down":
            blocking = [d for d in latest_anomalies if d.direction == "down"]
        elif direction_condition == "up":
            blocking = [d for d in latest_anomalies if d.direction == "up"]
        elif direction_condition == "same":
            trigger_direction = self._get_alert_trigger_direction(last_alert_timestamp)
            if trigger_direction is None:
                blocking = latest_anomalies  # conservative fallback
            else:
                blocking = [d for d in latest_anomalies if d.direction == trigger_direction]
        else:  # "any" / unknown — preserve historical behaviour
            blocking = latest_anomalies

        return len(blocking) == 0

    def _get_alert_trigger_direction(self, last_alert_timestamp: datetime) -> str | None:
        """Return the direction of the anomaly that triggered the last alert.

        Mirrors the quorum logic that fired the alert (``_quorum_at`` with
        no locked direction) so recovery checks the SAME direction the
        alert was raised for — not whichever anomalous detector happens to
        sort first. Falls back to a simple majority when the quorum can no
        longer be reconstructed.
        """
        if not self.internal:
            return None

        trigger_detections = self.internal.get_recent_detections(
            metric_name=self.metric_name,
            last_point=last_alert_timestamp,
            num_points=1,
        )
        if not trigger_detections:
            return None

        records = hydrate_detection_records(trigger_detections)
        by_time = self._group_by_timestamp(records)
        if not by_time:
            return None
        latest_ts = max(by_time.keys())
        anomalies = [d for d in by_time[latest_ts] if d.is_anomaly]
        if not anomalies:
            return None

        # _quorum_at lives in _DecisionMixin; both mixins are combined in
        # AlertOrchestrator, so the call resolves at runtime.
        _, direction = self._quorum_at(anomalies, None)
        if direction in ("up", "down"):
            return direction

        ups = sum(1 for d in anomalies if d.direction == "up")
        downs = sum(1 for d in anomalies if d.direction == "down")
        if ups > downs:
            return "up"
        if downs > ups:
            return "down"
        return None

    def _build_recovery_data(
        self,
        detections: list[DetectionRecord],
    ) -> AlertData | None:
        """Construct the AlertData payload sent as a recovery notification."""
        if not detections:
            return None

        # ``detections`` is oldest→newest, so the latest point lives at [-1].
        latest = detections[-1]

        # Prefer the latest CI so the message reflects the *current* interval.
        # Fall back to the last anomalous point only if the latest row has no
        # CI (e.g. missing-data / insufficient-data placeholders).
        recovery_ci_lower = latest.confidence_lower
        recovery_ci_upper = latest.confidence_upper
        recovery_detector_name = latest.detector_name
        recovery_detector_params = latest.detector_params

        if recovery_ci_lower is None or recovery_ci_upper is None:
            last_anomalous = next((d for d in reversed(detections) if d.is_anomaly), None)
            if last_anomalous:
                recovery_detector_name = last_anomalous.detector_name
                recovery_detector_params = last_anomalous.detector_params
                recovery_ci_lower = last_anomalous.confidence_lower
                recovery_ci_upper = last_anomalous.confidence_upper

        return AlertData(
            metric_name=self.metric_name,
            timestamp=latest.timestamp,
            timezone=self.timezone_display,
            value=latest.value,
            confidence_lower=recovery_ci_lower,
            confidence_upper=recovery_ci_upper,
            detector_name=recovery_detector_name,
            detector_params=recovery_detector_params,
            direction="none",
            severity=0.0,
            detection_metadata={},
            consecutive_count=0,
            is_recovery=True,
            description=self.description,
            mentions=self.mentions,
            dashboard_url=self.dashboard_url,
            links=self.links,
            # Echo the rule that had fired so the recovery message names the
            # same alert condition that just cleared.
            min_detectors=self.conditions.min_detectors,
            direction_policy=self.conditions.direction,
            consecutive_required=self.conditions.consecutive_anomalies,
        )
