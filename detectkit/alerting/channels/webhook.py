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
        # Format message
        message = self.format_message(alert_data, template)

        # Prepare payload (Mattermost/Slack compatible format)
        payload = {
            "text": message,
            "username": self.username,
            "icon_emoji": self.icon_emoji,
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

    def __repr__(self) -> str:
        """String representation."""
        url_preview = self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"
