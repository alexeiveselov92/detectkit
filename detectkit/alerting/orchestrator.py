"""
Alert orchestrator for coordinating detection and alerting.

Handles:
- Checking consecutive anomaly logic
- Direction matching
- Multiple detector aggregation (min_detectors)
- Loading recent detection results
- Coordinating alert sending
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.core.interval import Interval


@dataclass
class AlertConditions:
    """Alert conditions configuration."""

    min_detectors: int = 1  # Minimum detectors needed for alert
    direction: str = "any"  # "any", "same", "up", "down"
    consecutive_anomalies: int = 1  # Number of consecutive anomalies required


@dataclass
class DetectionRecord:
    """Record of a detection result from database."""

    timestamp: np.datetime64
    detector_name: str
    detector_id: str
    value: float
    is_anomaly: bool
    confidence_lower: Optional[float]
    confidence_upper: Optional[float]
    direction: str  # "up", "down", "none"
    severity: float
    detection_metadata: Dict


class AlertOrchestrator:
    """
    Orchestrates the alert decision and sending process.

    Responsibilities:
    - Load recent detection results from database
    - Check consecutive anomaly conditions
    - Check direction matching
    - Aggregate multiple detectors (min_detectors)
    - Send alerts through configured channels

    Example:
        >>> orchestrator = AlertOrchestrator(
        ...     metric_name="cpu_usage",
        ...     interval=Interval.parse("10min"),
        ...     conditions=AlertConditions(consecutive_anomalies=3, direction="same")
        ... )
        >>> should_alert, alert_data = orchestrator.should_alert(recent_detections)
        >>> if should_alert:
        ...     orchestrator.send_alerts(alert_data, channels)
    """

    def __init__(
        self,
        metric_name: str,
        interval: Interval,
        conditions: Optional[AlertConditions] = None,
        timezone_display: str = "UTC",
    ):
        """
        Initialize alert orchestrator.

        Args:
            metric_name: Name of the metric
            interval: Metric interval
            conditions: Alert conditions (defaults to AlertConditions())
            timezone_display: Timezone for alert display (default: UTC)
        """
        self.metric_name = metric_name
        self.interval = interval
        self.conditions = conditions or AlertConditions()
        self.timezone_display = timezone_display

    def should_alert(
        self,
        recent_detections: List[DetectionRecord],
    ) -> tuple[bool, Optional[AlertData]]:
        """
        Determine if alert should be sent based on recent detections.

        Args:
            recent_detections: List of recent detection records (sorted by time, newest first)

        Returns:
            Tuple of (should_alert, alert_data)
            - should_alert: True if alert should be sent
            - alert_data: AlertData if should_alert=True, None otherwise

        Logic:
            1. Check if enough detectors triggered (min_detectors)
            2. Check consecutive anomalies with direction matching
            3. Return decision and formatted AlertData
        """
        if not recent_detections:
            return False, None

        # Group detections by timestamp
        detections_by_time = self._group_by_timestamp(recent_detections)

        # Check from newest to oldest
        timestamps_sorted = sorted(detections_by_time.keys(), reverse=True)

        # Check min_detectors for the latest point
        latest_timestamp = timestamps_sorted[0]
        latest_detections = detections_by_time[latest_timestamp]

        # Filter anomalies
        latest_anomalies = [d for d in latest_detections if d.is_anomaly]

        if len(latest_anomalies) < self.conditions.min_detectors:
            return False, None

        # Check consecutive anomalies
        consecutive_count = self._count_consecutive_anomalies(
            detections_by_time, timestamps_sorted
        )

        if consecutive_count < self.conditions.consecutive_anomalies:
            return False, None

        # Build AlertData from latest anomalies
        # If multiple detectors, aggregate them
        alert_data = self._build_alert_data(
            latest_anomalies, consecutive_count
        )

        return True, alert_data

    def _group_by_timestamp(
        self, detections: List[DetectionRecord]
    ) -> Dict[np.datetime64, List[DetectionRecord]]:
        """Group detection records by timestamp."""
        grouped = {}
        for detection in detections:
            if detection.timestamp not in grouped:
                grouped[detection.timestamp] = []
            grouped[detection.timestamp].append(detection)
        return grouped

    def _count_consecutive_anomalies(
        self,
        detections_by_time: Dict[np.datetime64, List[DetectionRecord]],
        timestamps_sorted: List[np.datetime64],
    ) -> int:
        """
        Count consecutive anomalies matching direction condition.

        Args:
            detections_by_time: Detections grouped by timestamp
            timestamps_sorted: Timestamps in descending order (newest first)

        Returns:
            Number of consecutive anomalies

        Logic:
            - direction="any": Count any anomalies
            - direction="same": Count anomalies in same direction (resets on change)
            - direction="up": Count only "up" anomalies
            - direction="down": Count only "down" anomalies
        """
        direction_condition = self.conditions.direction
        consecutive = 0
        prev_direction = None

        for timestamp in timestamps_sorted:
            detections = detections_by_time[timestamp]

            # Check if enough detectors found anomaly
            anomalies = [d for d in detections if d.is_anomaly]
            if len(anomalies) < self.conditions.min_detectors:
                break

            # Determine dominant direction (use first detector's direction)
            current_direction = anomalies[0].direction

            # Check direction matching
            if direction_condition == "any":
                consecutive += 1
            elif direction_condition == "same":
                if prev_direction is None:
                    consecutive = 1
                    prev_direction = current_direction
                elif current_direction == prev_direction:
                    consecutive += 1
                else:
                    # Direction changed, stop counting
                    break
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
                # Unknown direction condition
                consecutive += 1

        return consecutive

    def _build_alert_data(
        self,
        anomalies: List[DetectionRecord],
        consecutive_count: int,
    ) -> AlertData:
        """
        Build AlertData from anomalous detections.

        Args:
            anomalies: List of anomalous detections for the latest point
            consecutive_count: Number of consecutive anomalies

        Returns:
            AlertData for sending
        """
        # Use first detector for primary info (if multiple, we'll note it)
        primary = anomalies[0]

        # If multiple detectors, aggregate info
        if len(anomalies) > 1:
            # Take the worst severity
            max_severity = max(d.severity for d in anomalies)
            detector_names = [d.detector_name for d in anomalies]
            detector_name = f"{len(anomalies)} detectors"
            detector_params_list = [
                f"{d.detector_name}({d.detector_id[:8]})" for d in anomalies
            ]
            detector_params = ", ".join(detector_params_list)

            # Combine metadata
            combined_metadata = {
                "detectors": detector_names,
                "count": len(anomalies),
            }
            for i, d in enumerate(anomalies):
                combined_metadata[f"detector_{i}_metadata"] = d.detection_metadata
        else:
            max_severity = primary.severity
            detector_name = primary.detector_name
            detector_params = f"{primary.detector_id[:16]}"
            combined_metadata = primary.detection_metadata

        # Convert numpy timestamp for AlertData
        timestamp = primary.timestamp

        return AlertData(
            metric_name=self.metric_name,
            timestamp=timestamp,
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
        )

    def send_alerts(
        self,
        alert_data: AlertData,
        channels: List[BaseAlertChannel],
        template: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Send alerts through all configured channels.

        Args:
            alert_data: Alert data to send
            channels: List of alert channels
            template: Optional custom message template

        Returns:
            Dict mapping channel name to success status

        Example:
            >>> results = orchestrator.send_alerts(
            ...     alert_data,
            ...     channels=[mattermost, slack],
            ...     template="ALERT: {metric_name} = {value}"
            ... )
            >>> print(results)
            {'MattermostChannel': True, 'SlackChannel': True}
        """
        results = {}

        for channel in channels:
            try:
                success = channel.send(alert_data, template)
                channel_name = channel.__class__.__name__
                results[channel_name] = success
            except Exception as e:
                channel_name = channel.__class__.__name__
                print(f"Error sending alert via {channel_name}: {e}")
                results[channel_name] = False

        return results

    def get_last_complete_point(self, now: Optional[datetime] = None) -> datetime:
        """
        Determine the last complete time point for the metric.

        Args:
            now: Current time (default: datetime.now(timezone.utc))

        Returns:
            Last complete timestamp

        Logic:
            - Floor current time to interval boundary
            - Subtract one interval to get last complete point
            - Example: now=13:23, interval=10min -> 13:10

        Example:
            >>> orchestrator = AlertOrchestrator("metric", Interval.parse("10min"))
            >>> now = datetime(2024, 1, 1, 13, 23, 0, tzinfo=timezone.utc)
            >>> last_point = orchestrator.get_last_complete_point(now)
            >>> print(last_point)
            2024-01-01 13:10:00+00:00
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Ensure UTC
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Floor to interval
        interval_seconds = self.interval.seconds
        timestamp_seconds = int(now.timestamp())
        floored_seconds = (timestamp_seconds // interval_seconds) * interval_seconds

        # Subtract one interval to get last complete point
        last_complete_seconds = floored_seconds - interval_seconds

        return datetime.fromtimestamp(last_complete_seconds, tz=timezone.utc)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"AlertOrchestrator("
            f"metric='{self.metric_name}', "
            f"interval={self.interval}, "
            f"min_detectors={self.conditions.min_detectors}, "
            f"direction='{self.conditions.direction}', "
            f"consecutive={self.conditions.consecutive_anomalies})"
        )
