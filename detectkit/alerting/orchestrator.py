"""
Alert orchestrator for coordinating detection and alerting.

Handles:
- Checking consecutive anomaly logic
- Direction matching
- Multiple detector aggregation (min_detectors)
- Loading recent detection results
- Coordinating alert sending
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from detectkit.utils.datetime_utils import now_utc, now_utc_naive, to_naive_utc, to_aware_utc

import numpy as np

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.core.interval import Interval


def _parse_detection_metadata(metadata: Any) -> Dict:
    """Parse detection_metadata stored as dict or JSON string into a dict."""
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
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _direction_from_metadata(metadata: Any, is_anomaly: bool) -> str:
    """
    Resolve alert direction ("up"/"down"/"none") from detector metadata.

    Detectors authoritatively write direction as "below"/"above" in
    detection_metadata. This is the source of truth — confidence-bound
    reconstruction does not work for one-sided detectors (e.g. ManualBounds
    with only upper_bound set).
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
    detector_params: str  # JSON string with detector parameters
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
        ...     alert_config_id="abc123",
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
        alert_config_id: str,
        conditions: Optional[AlertConditions] = None,
        timezone_display: str = "UTC",
        internal=None,  # InternalTablesManager (optional, for cooldown tracking)
        alert_config=None,  # AlertConfig (optional, for cooldown settings)
        description: Optional[str] = None,
        mentions: Optional[List[str]] = None,
    ):
        """
        Initialize alert orchestrator.

        Args:
            metric_name: Name of the metric
            interval: Metric interval
            alert_config_id: MD5 hash of alerting config params (for independent state per config)
            conditions: Alert conditions (defaults to AlertConditions())
            timezone_display: Timezone for alert display (default: UTC)
            internal: InternalTablesManager instance (optional, for cooldown tracking)
            alert_config: AlertConfig instance (optional, for cooldown settings)
            description: Optional metric description shown in alert messages
            mentions: Optional list of users/groups to mention in alerts
        """
        self.metric_name = metric_name
        self.interval = interval
        self.alert_config_id = alert_config_id
        self.conditions = conditions or AlertConditions()
        self.timezone_display = timezone_display
        self.internal = internal
        self.alert_config = alert_config
        self.description = description
        self.mentions = mentions or []

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
            3. Check alert cooldown (if configured)
            4. Return decision and formatted AlertData
        """
        if not recent_detections:
            return False, None

        # NEW: Check cooldown FIRST (before expensive checks)
        if self._is_in_cooldown():
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
                f"{d.detector_name}: {d.detector_params}" for d in anomalies
            ]
            detector_params = "; ".join(detector_params_list)

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
            detector_params = primary.detector_params
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
            description=self.description,
            mentions=self.mentions,
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

        # Update alert timestamp after sending (for cooldown tracking)
        if any(results.values()) and self.internal:
            # At least one channel succeeded - update timestamp
            self.internal.update_alert_timestamp(
                metric_name=self.metric_name,
                alert_config_id=self.alert_config_id,
                timestamp=now_utc_naive(),
                increment_count=True,
            )

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
            >>> orchestrator = AlertOrchestrator("metric", Interval.parse("10min"), alert_config_id="abc123")
            >>> now = datetime(2024, 1, 1, 13, 23, 0, tzinfo=timezone.utc)
            >>> last_point = orchestrator.get_last_complete_point(now)
            >>> print(last_point)
            2024-01-01 13:10:00+00:00
        """
        if now is None:
            now = now_utc()

        # Ensure UTC
        now = to_aware_utc(now)

        # Floor to interval
        interval_seconds = self.interval.seconds
        timestamp_seconds = int(now.timestamp())
        floored_seconds = (timestamp_seconds // interval_seconds) * interval_seconds

        # Subtract one interval to get last complete point
        last_complete_seconds = floored_seconds - interval_seconds

        return datetime.fromtimestamp(last_complete_seconds, tz=timezone.utc)

    def _is_in_cooldown(self) -> bool:
        """
        Check if alert is currently in cooldown period.

        Returns:
            True if in cooldown (should NOT send alert), False otherwise

        Logic:
            1. If alert_cooldown not configured → return False (no cooldown)
            2. Get last_alert_sent timestamp from database
            3. If never sent → return False (no cooldown)
            4. Calculate elapsed time since last alert
            5. If cooldown_reset_on_recovery=True:
               - Check if recovery happened since last alert
               - If yes → return False (cooldown reset)
            6. If elapsed < cooldown_interval → return True (in cooldown)
            7. Otherwise → return False (cooldown expired)
        """
        # No cooldown configured
        if not self.alert_config or not self.alert_config.alert_cooldown:
            return False

        # No internal manager (can't check cooldown)
        if not self.internal:
            return False

        # Get last alert timestamp
        last_sent = self.internal.get_last_alert_timestamp(self.metric_name, self.alert_config_id)

        if not last_sent:
            return False  # Never sent alert before

        # Parse cooldown interval
        from detectkit.core.interval import Interval
        cooldown_interval = Interval(self.alert_config.alert_cooldown)
        cooldown_seconds = cooldown_interval.seconds

        # Calculate elapsed time
        now = now_utc_naive()
        elapsed = (now - last_sent).total_seconds()

        # Check recovery reset (if enabled)
        if self.alert_config.cooldown_reset_on_recovery:
            # Check if recovery happened since last alert
            has_recovery = self._check_recovery_since_last_alert(last_sent)

            if has_recovery:
                return False  # Cooldown reset by recovery

        # Check if still in cooldown
        return elapsed < cooldown_seconds

    def _check_recovery_since_last_alert(
        self,
        last_alert_timestamp: datetime
    ) -> bool:
        """
        Check if recovery happened since last alert was sent.

        Recovery means: consecutive anomalies count dropped below threshold,
        indicating the metric returned to normal state.

        Args:
            last_alert_timestamp: Timestamp when last alert was sent

        Returns:
            True if recovery detected, False otherwise

        Logic:
            1. Load detections created after last_alert_timestamp
            2. Count consecutive anomalies using same logic as should_alert()
            3. If consecutive < required → recovery happened
            4. If consecutive >= required → still in anomaly state
        """
        if not self.internal:
            return False

        # Get last complete point
        last_point = self.get_last_complete_point()

        # Load detections created AFTER last alert
        # We need enough points to check consecutive anomalies
        num_points = self.conditions.consecutive_anomalies + 5  # +5 for margin

        recent_detections = self.internal.get_recent_detections(
            metric_name=self.metric_name,
            last_point=last_point,
            num_points=num_points,
            created_after=last_alert_timestamp  # Only detections AFTER last alert
        )

        if not recent_detections:
            # No new detections → assume recovery
            return True

        # Convert to DetectionRecord format
        detection_records = []
        for det in recent_detections:
            metadata_list = det.get("detection_metadata_list") or [None] * len(det["detector_ids"])
            # Group has multiple detectors per timestamp
            for i in range(len(det["detector_ids"])):
                value = det["value"]
                conf_lower = det["confidence_lowers"][i]
                conf_upper = det["confidence_uppers"][i]
                is_anomaly = det["is_anomaly_flags"][i]

                # Use detector-authoritative direction from detection_metadata
                # (works for one-sided detectors like ManualBounds where
                # confidence_lower/upper may be None).
                metadata = _parse_detection_metadata(metadata_list[i])
                direction = _direction_from_metadata(metadata, is_anomaly)

                record = DetectionRecord(
                    timestamp=np.datetime64(det["timestamp"]),
                    detector_name=det["detector_names"][i],
                    detector_id=det["detector_ids"][i],
                    detector_params=det["detector_params_list"][i],
                    value=value,
                    is_anomaly=is_anomaly,
                    confidence_lower=conf_lower,
                    confidence_upper=conf_upper,
                    direction=direction,
                    severity=0.0,  # Not used for recovery check
                    detection_metadata=metadata,
                )
                detection_records.append(record)

        # Group by timestamp and sort (same format as should_alert uses)
        detections_by_time = self._group_by_timestamp(detection_records)
        timestamps_sorted = sorted(detections_by_time.keys(), reverse=True)

        # Direction-aware recovery: only block recovery on anomalies that
        # match the alert's direction condition. For a "down"-only alert an
        # "up" anomaly already means the alert condition no longer holds, so
        # it should count as recovery.
        direction_condition = self.conditions.direction
        latest_ts = timestamps_sorted[0]
        latest_detections = detections_by_time[latest_ts]
        latest_anomalies = [d for d in latest_detections if d.is_anomaly]

        if direction_condition == "down":
            blocking = [d for d in latest_anomalies if d.direction == "down"]
        elif direction_condition == "up":
            blocking = [d for d in latest_anomalies if d.direction == "up"]
        elif direction_condition == "same":
            trigger_direction = self._get_alert_trigger_direction(last_alert_timestamp)
            if trigger_direction is None:
                # Unknown trigger direction → fall back to conservative behavior
                blocking = latest_anomalies
            else:
                blocking = [d for d in latest_anomalies if d.direction == trigger_direction]
        else:  # "any" and unknown — preserve historical behavior
            blocking = latest_anomalies

        return len(blocking) == 0

    def _get_alert_trigger_direction(
        self, last_alert_timestamp: datetime
    ) -> Optional[str]:
        """
        Resolve the direction of the anomaly that triggered the last alert.

        Used by direction="same" recovery logic. Loads the detection record
        at last_alert_timestamp and returns the dominant anomaly direction
        from detection_metadata.

        Returns:
            "up", "down", or None if not resolvable.
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

        det = trigger_detections[0]
        metadata_list = det.get("detection_metadata_list") or [None] * len(det["detector_ids"])
        for i in range(len(det["detector_ids"])):
            if not det["is_anomaly_flags"][i]:
                continue
            direction = _direction_from_metadata(metadata_list[i], True)
            if direction in ("up", "down"):
                return direction
        return None

    def should_send_recovery(
        self,
        recent_detections: List[DetectionRecord],
    ) -> tuple[bool, Optional[AlertData]]:
        """
        Determine if recovery notification should be sent.

        Recovery is sent when:
        1. A previous alert was sent (last_alert_sent exists)
        2. Metric has recovered (consecutive anomalies < threshold)
        3. Recovery hasn't already been sent for this incident
           (last_recovery_sent > last_alert_sent would mean already notified)

        Args:
            recent_detections: List of recent detection records (sorted by time, newest first)

        Returns:
            Tuple of (should_send, recovery_alert_data)
        """
        if not self.internal:
            return False, None

        # Check if there was a previous alert
        last_alert = self.internal.get_last_alert_timestamp(self.metric_name, self.alert_config_id)
        if not last_alert:
            return False, None  # Never alerted, nothing to recover from

        # Check if recovery already sent for this incident
        last_recovery = self.internal.get_last_recovery_timestamp(self.metric_name, self.alert_config_id)
        if last_recovery and last_recovery >= last_alert:
            return False, None  # Already sent recovery for this alert

        # Check if metric actually recovered
        has_recovery = self._check_recovery_since_last_alert(last_alert)
        if not has_recovery:
            return False, None  # Still in anomaly state

        # Build recovery AlertData from latest normal point
        recovery_data = self._build_recovery_data(recent_detections)
        if not recovery_data:
            return False, None

        return True, recovery_data

    def _build_recovery_data(
        self,
        detections: List[DetectionRecord],
    ) -> Optional[AlertData]:
        """
        Build AlertData for recovery notification from latest detection.

        Args:
            detections: Recent detection records

        Returns:
            AlertData with is_recovery=True, or None if no data
        """
        if not detections:
            return None

        # Use the latest (newest) detection point for recovery info.
        # detections are sorted oldest→newest by _load_recent_detections.
        latest = detections[-1]

        return AlertData(
            metric_name=self.metric_name,
            timestamp=latest.timestamp,
            timezone=self.timezone_display,
            value=latest.value,
            confidence_lower=latest.confidence_lower,
            confidence_upper=latest.confidence_upper,
            detector_name=latest.detector_name,
            detector_params=latest.detector_params,
            direction="none",
            severity=0.0,
            detection_metadata={},
            consecutive_count=0,
            is_recovery=True,
            description=self.description,
            mentions=self.mentions,
        )

    def send_recovery(
        self,
        alert_data: AlertData,
        channels: List[BaseAlertChannel],
        template: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Send recovery notifications through all configured channels.

        Args:
            alert_data: Recovery alert data (is_recovery=True)
            channels: List of alert channels
            template: Optional custom recovery message template

        Returns:
            Dict mapping channel name to success status
        """
        results = {}

        for channel in channels:
            try:
                success = channel.send(alert_data, template)
                channel_name = channel.__class__.__name__
                results[channel_name] = success
            except Exception as e:
                channel_name = channel.__class__.__name__
                print(f"Error sending recovery via {channel_name}: {e}")
                results[channel_name] = False

        # Update recovery timestamp after sending
        if any(results.values()) and self.internal:
            self.internal.update_recovery_timestamp(
                metric_name=self.metric_name,
                alert_config_id=self.alert_config_id,
                timestamp=now_utc_naive(),
            )

        return results

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"AlertOrchestrator("
            f"metric='{self.metric_name}', "
            f"interval={self.interval}, "
            f"config_id='{self.alert_config_id[:8]}...', "
            f"min_detectors={self.conditions.min_detectors}, "
            f"direction='{self.conditions.direction}', "
            f"consecutive={self.conditions.consecutive_anomalies})"
        )
