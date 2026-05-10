"""
Base alert channel interface.

All alert channels must inherit from BaseAlertChannel and implement
the send() method for delivering alerts to specific destinations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AlertData:
    """
    Data for alert message.

    Contains all information needed to format and send an alert.

    Attributes:
        metric_name: Name of the metric
        timestamp: Timestamp of the anomaly (datetime64)
        timezone: Timezone for display (e.g., "Europe/Moscow")
        value: Actual metric value (None for no-data alerts)
        confidence_lower: Lower confidence bound
        confidence_upper: Upper confidence bound
        detector_name: Name/ID of detector that found the anomaly
        detector_params: Detector parameters (JSON string)
        direction: Direction of anomaly ("above" or "below")
        severity: Severity score
        detection_metadata: Additional metadata from detector
        consecutive_count: Number of consecutive anomalies
        is_recovery: True for recovery notifications
        is_no_data: True for missing-data alerts (no_data_alert)
    """

    metric_name: str
    timestamp: Any  # datetime64 or datetime
    timezone: str
    value: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    detector_name: str
    detector_params: str
    direction: str
    severity: float
    detection_metadata: dict[str, Any]
    consecutive_count: int = 1
    is_recovery: bool = False
    is_no_data: bool = False
    is_error: bool = False
    error_type: str | None = None
    error_message: str | None = None
    description: str | None = None
    mentions: list[str] = field(default_factory=list)


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
        template: str | None = None,
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
        template: str | None = None,
        recovery_template: str | None = None,
    ) -> str:
        """
        Format alert message from template.

        Uses default template if none provided. Template variables:
        - {metric_name}
        - {timestamp}
        - {timezone}
        - {value} / {value_display}
        - {confidence_lower}
        - {confidence_upper}
        - {detector_name}
        - {direction}
        - {severity}
        - {consecutive_count}
        - {status}

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
            if alert_data.is_error:
                template = self.get_default_error_template()
            elif alert_data.is_no_data:
                template = self.get_default_no_data_template()
            elif alert_data.is_recovery:
                template = recovery_template or self.get_default_recovery_template()
            else:
                template = self.get_default_template()

        # Format timestamp to string
        import math
        from datetime import datetime

        import numpy as np

        ts = alert_data.timestamp
        if isinstance(ts, np.datetime64):
            ts = ts.astype(datetime)

        # Convert naive UTC timestamp to target timezone if specified
        if alert_data.timezone:
            from zoneinfo import ZoneInfo

            ts = ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(alert_data.timezone))
            ts_str = f"{ts.strftime('%Y-%m-%d %H:%M:%S')} ({alert_data.timezone})"
        else:
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")

        # Format confidence interval
        if alert_data.confidence_lower is not None and alert_data.confidence_upper is not None:
            confidence_str = (
                f"[{alert_data.confidence_lower:.2f}, {alert_data.confidence_upper:.2f}]"
            )
        else:
            confidence_str = "N/A"

        # Display-safe value: stays usable even when value is None/NaN (no-data).
        raw_value = alert_data.value
        if raw_value is None or (isinstance(raw_value, float) and math.isnan(raw_value)):
            value_display = "no data"
            value_for_template: Any = "no data"
        else:
            value_display = f"{raw_value}"
            value_for_template = raw_value

        # Format description line (empty string if no description)
        description_line = f"{alert_data.description}\n" if alert_data.description else ""

        # Format mentions
        mentions_str = self.format_mentions(alert_data.mentions)
        mentions_line = f"\n{mentions_str}" if mentions_str else ""

        # Format message
        if alert_data.is_error:
            status = "ERROR"
        elif alert_data.is_no_data:
            status = "NO_DATA"
        elif alert_data.is_recovery:
            status = "RECOVERED"
        else:
            status = "ANOMALY"

        try:
            message = template.format(
                metric_name=alert_data.metric_name,
                timestamp=ts_str,
                timezone=alert_data.timezone,
                value=value_for_template,
                value_display=value_display,
                confidence_lower=alert_data.confidence_lower,
                confidence_upper=alert_data.confidence_upper,
                confidence_interval=confidence_str,
                detector_name=alert_data.detector_name,
                detector_params=alert_data.detector_params,
                direction=alert_data.direction,
                severity=alert_data.severity,
                consecutive_count=alert_data.consecutive_count,
                status=status,
                error_type=alert_data.error_type or "",
                error_message=alert_data.error_message or "",
                description=alert_data.description or "",
                description_line=description_line,
                mentions=mentions_str,
                mentions_line=mentions_line,
            )
        except (KeyError, ValueError, TypeError):
            # Template has an unknown variable or a format spec that doesn't fit
            # the actual value (e.g. ``{value:.2f}`` in a no-data template where
            # value is a string). Fall back to the kind-appropriate default.
            if alert_data.is_error:
                fallback = self.get_default_error_template()
            elif alert_data.is_no_data:
                fallback = self.get_default_no_data_template()
            elif alert_data.is_recovery:
                fallback = self.get_default_recovery_template()
            else:
                fallback = self.get_default_template()
            if template == fallback:
                # Already on the default — re-raise instead of recursing.
                raise
            message = self.format_message(alert_data, fallback)

        return message

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions list into platform-native syntax.

        Override in subclasses for platform-specific formatting.
        Default implementation prepends @ to each mention.

        Args:
            mentions: List of usernames or special keywords
                      ("channel", "all", "here")

        Returns:
            Formatted mentions string (e.g., "@john @here")
        """
        if not mentions:
            return ""
        return " ".join(f"@{m}" for m in mentions)

    def format_title(
        self,
        alert_data: AlertData,
    ) -> str:
        """
        Format alert title from template.

        Used by channels that support separate title fields (e.g., webhook attachments).

        Args:
            alert_data: Alert data to format

        Returns:
            Formatted title string
        """
        if alert_data.is_error:
            title_template = self.get_default_error_title_template()
        elif alert_data.is_no_data:
            title_template = self.get_default_no_data_title_template()
        elif alert_data.is_recovery:
            title_template = self.get_default_recovery_title_template()
        else:
            title_template = self.get_default_title_template()

        return title_template.format(metric_name=alert_data.metric_name)

    def get_default_template(self) -> str:
        """
        Get default message template for anomaly alerts.

        Returns:
            Default template string
        """
        return (
            "Anomaly detected in metric: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Value: {value} | CI: {confidence_interval}\n"
            "Direction: {direction} | Severity: {severity:.2f} | Consecutive: {consecutive_count}\n"
            "Detector: {detector_name}\n"
            "Parameters: {detector_params}"
            "{mentions_line}"
        )

    def get_default_recovery_template(self) -> str:
        """
        Get default message template for recovery alerts.

        Returns:
            Default recovery template string
        """
        return (
            "Metric recovered: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Value: {value} | CI: {confidence_interval}\n"
            "Detector: {detector_name}\n"
            "Status: metric returned to normal"
            "{mentions_line}"
        )

    def get_default_title_template(self) -> str:
        """
        Get default title template for anomaly alerts.

        Used by channels that support separate title fields (e.g., webhook attachments).

        Returns:
            Default title template string
        """
        return "Anomaly detected: {metric_name}"

    def get_default_recovery_title_template(self) -> str:
        """
        Get default title template for recovery alerts.

        Returns:
            Default recovery title template string
        """
        return "Metric recovered: {metric_name}"

    def get_default_no_data_template(self) -> str:
        """
        Get default message template for no-data alerts.

        Used when ``no_data_alert: true`` and the latest expected interval
        has no datapoint (no row OR row with NULL/NaN value).
        """
        return (
            "No data for metric: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Status: query returned no datapoint for the latest interval"
            "{mentions_line}"
        )

    def get_default_no_data_title_template(self) -> str:
        """Get default title template for no-data alerts."""
        return "No data: {metric_name}"

    def get_default_error_template(self) -> str:
        """Default body template for project-level error alerts."""
        return (
            "Pipeline failed for metric: {metric_name}\n"
            "{description_line}"
            "Time: {timestamp}\n"
            "Error: {error_type}: {error_message}"
            "{mentions_line}"
        )

    def get_default_error_title_template(self) -> str:
        """Default title template for project-level error alerts."""
        return "Pipeline error: {metric_name}"

    def __repr__(self) -> str:
        """String representation of channel."""
        return f"{self.__class__.__name__}()"
