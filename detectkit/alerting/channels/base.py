"""
Base alert channel interface.

All alert channels must inherit from BaseAlertChannel and implement
the send() method for delivering alerts to specific destinations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from detectkit.detectors.base import DetectionResult


@dataclass
class AlertData:
    """
    Data for alert message.

    Contains all information needed to format and send an alert.

    Attributes:
        metric_name: Name of the metric
        timestamp: Timestamp of the anomaly (datetime64)
        timezone: Timezone for display (e.g., "Europe/Moscow")
        value: Actual metric value
        confidence_lower: Lower confidence bound
        confidence_upper: Upper confidence bound
        detector_name: Name/ID of detector that found the anomaly
        detector_params: Detector parameters (JSON string)
        direction: Direction of anomaly ("above" or "below")
        severity: Severity score
        detection_metadata: Additional metadata from detector
        consecutive_count: Number of consecutive anomalies
    """

    metric_name: str
    timestamp: Any  # datetime64 or datetime
    timezone: str
    value: float
    confidence_lower: Optional[float]
    confidence_upper: Optional[float]
    detector_name: str
    detector_params: str
    direction: str
    severity: float
    detection_metadata: Dict[str, Any]
    consecutive_count: int = 1


class BaseAlertChannel(ABC):
    """
    Abstract base class for alert channels.

    Alert channels deliver notifications to external systems when
    anomalies are detected. Each channel implements a specific
    delivery mechanism (webhook, email, etc.).

    Example:
        >>> class MyChannel(BaseAlertChannel):
        ...     def send(self, alert_data, template=None):
        ...         message = self.format_message(alert_data, template)
        ...         # Send via specific mechanism
        ...         return True
    """

    @abstractmethod
    def send(
        self,
        alert_data: AlertData,
        template: Optional[str] = None,
    ) -> bool:
        """
        Send alert to this channel.

        Args:
            alert_data: Alert data to send
            template: Optional custom message template
                     Uses default template if None

        Returns:
            True if sent successfully, False otherwise

        Raises:
            Exception: If sending fails critically

        Example:
            >>> alert = AlertData(
            ...     metric_name="cpu_usage",
            ...     timestamp=datetime.now(),
            ...     value=95.0,
            ...     ...
            ... )
            >>> success = channel.send(alert)
        """
        pass

    def format_message(
        self,
        alert_data: AlertData,
        template: Optional[str] = None,
    ) -> str:
        """
        Format alert message from template.

        Uses default template if none provided. Template variables:
        - {metric_name}
        - {timestamp}
        - {timezone}
        - {value}
        - {confidence_lower}
        - {confidence_upper}
        - {detector_name}
        - {direction}
        - {severity}
        - {consecutive_count}

        Args:
            alert_data: Alert data to format
            template: Optional custom template string

        Returns:
            Formatted message string

        Example:
            >>> template = "Anomaly in {metric_name}: {value}"
            >>> message = channel.format_message(alert_data, template)
        """
        if template is None:
            template = self.get_default_template()

        # Format timestamp to string
        from datetime import datetime
        import numpy as np

        ts = alert_data.timestamp
        if isinstance(ts, np.datetime64):
            ts = ts.astype(datetime)

        # Format timestamp with timezone
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        if alert_data.timezone:
            ts_str = f"{ts_str} ({alert_data.timezone})"

        # Format confidence interval
        if alert_data.confidence_lower is not None and alert_data.confidence_upper is not None:
            confidence_str = f"[{alert_data.confidence_lower:.2f}, {alert_data.confidence_upper:.2f}]"
        else:
            confidence_str = "N/A"

        # Format message
        try:
            message = template.format(
                metric_name=alert_data.metric_name,
                timestamp=ts_str,
                timezone=alert_data.timezone,
                value=alert_data.value,
                confidence_lower=alert_data.confidence_lower,
                confidence_upper=alert_data.confidence_upper,
                confidence_interval=confidence_str,
                detector_name=alert_data.detector_name,
                direction=alert_data.direction,
                severity=alert_data.severity,
                consecutive_count=alert_data.consecutive_count,
            )
        except KeyError as e:
            # If template has unknown variables, fall back to default
            message = self.format_message(alert_data, self.get_default_template())

        return message

    def get_default_template(self) -> str:
        """
        Get default message template.

        Returns:
            Default template string
        """
        return (
            "Anomaly detected in metric: {metric_name}\n"
            "Time: {timestamp}\n"
            "Value: {value}\n"
            "Confidence interval: {confidence_interval}\n"
            "Detector: {detector_name}\n"
            "Direction: {direction}\n"
            "Severity: {severity:.2f}"
        )

    def __repr__(self) -> str:
        """String representation of channel."""
        return f"{self.__class__.__name__}()"
