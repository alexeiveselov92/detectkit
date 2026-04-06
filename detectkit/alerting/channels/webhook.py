"""
Generic webhook alert channel.

Sends alerts to any webhook endpoint that accepts JSON payload.
Compatible with Mattermost, Slack, and other webhook-based systems.
"""

from typing import Dict, Optional

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel


class WebhookChannel(BaseAlertChannel):
    """
    Generic webhook alert channel.

    Sends formatted alert messages to any webhook URL with JSON payload.
    Compatible with:
    - Mattermost incoming webhooks
    - Slack incoming webhooks
    - Custom webhook endpoints

    The payload format is compatible with Mattermost/Slack:
    {
        "text": "message",
        "username": "bot_name",
        "icon_emoji": ":emoji:",
        "channel": "#channel" (optional)
    }

    Parameters:
        webhook_url (str): Webhook URL to send alerts to
        username (str): Bot username to display (default: "detectk")
        icon_emoji (str): Bot emoji icon (default: ":warning:")
        channel (str): Target channel (optional, for Slack/Mattermost)
        timeout (int): Request timeout in seconds (default: 10)
        extra_headers (dict): Additional HTTP headers (optional)

    Example:
        >>> # Mattermost
        >>> channel = WebhookChannel(
        ...     webhook_url="https://mattermost.example.com/hooks/xxx"
        ... )
        >>>
        >>> # Slack
        >>> channel = WebhookChannel(
        ...     webhook_url="https://hooks.slack.com/services/xxx",
        ...     channel="#alerts"
        ... )
        >>>
        >>> # Custom webhook
        >>> channel = WebhookChannel(
        ...     webhook_url="https://custom.example.com/webhook",
        ...     extra_headers={"Authorization": "Bearer token"}
        ... )
    """

    def __init__(
        self,
        webhook_url: str,
        username: str = "detectk",
        icon_emoji: str = ":warning:",
        channel: Optional[str] = None,
        timeout: int = 10,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        """Initialize webhook channel."""
        if not webhook_url:
            raise ValueError("webhook_url is required")

        self.webhook_url = webhook_url
        self.username = username
        self.icon_emoji = icon_emoji
        self.channel = channel
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def send(
        self,
        alert_data: AlertData,
        template: Optional[str] = None,
    ) -> bool:
        """
        Send alert to webhook.

        Args:
            alert_data: Alert data to send
            template: Optional custom message template

        Returns:
            True if sent successfully, False otherwise

        Raises:
            requests.RequestException: If request fails critically

        Example:
            >>> channel = WebhookChannel(webhook_url="https://...")
            >>> success = channel.send(alert_data)
        """
        # Format title and body separately for attachments format
        title = self.format_title(alert_data)
        body = self.format_message(alert_data, template)

        # Color: red for anomaly, green for recovery
        color = "#36A64F" if alert_data.is_recovery else "#D63232"

        # Prepare payload using Mattermost/Slack attachments format.
        # Attachments give us: colored left sidebar, separate title, and
        # automatic "Show more" collapse for long body text in Mattermost.
        attachment = {
            "color": color,
            "title": title,
            "text": body,
        }

        payload = {
            "username": self.username,
            "icon_emoji": self.icon_emoji,
            "attachments": [attachment],
        }

        # Add channel if specified (for Slack)
        if self.channel:
            payload["channel"] = self.channel

        # Prepare headers
        headers = {"Content-Type": "application/json"}
        headers.update(self.extra_headers)

        # Send to webhook
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            # Log error but don't crash
            print(f"Failed to send webhook alert: {e}")
            return False

    def get_default_template(self) -> str:
        """
        Get default anomaly message body template for webhook channels.

        Metric name is shown in the attachment title, so it is omitted from the body.
        """
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Value: {value} | CI: {confidence_interval}\n"
            "Direction: {direction} | Severity: {severity:.2f} | Consecutive: {consecutive_count}\n"
            "Detector: {detector_name}\n"
            "Parameters: {detector_params}"
        )

    def get_default_recovery_template(self) -> str:
        """
        Get default recovery message body template for webhook channels.

        Metric name is shown in the attachment title, so it is omitted from the body.
        """
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Value: {value} | CI: {confidence_interval}\n"
            "Detector: {detector_name}\n"
            "Status: metric returned to normal"
        )

    def __repr__(self) -> str:
        """String representation."""
        url_preview = self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"
