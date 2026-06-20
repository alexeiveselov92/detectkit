"""
Generic webhook alert channel.

Sends alerts to any webhook endpoint that accepts JSON payload.
Compatible with Mattermost, Slack, and other webhook-based systems.
"""

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME


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
        "icon_url": "https://.../bot-icon.png",   # or "icon_emoji": ":emoji:"
        "channel": "#channel" (optional)
    }

    Branding: the bot defaults to the **detectkit brand avatar** (``icon_url``)
    and name (``username``). An explicit ``icon_url`` overrides it with a custom
    image; an explicit ``icon_emoji`` opts out of the avatar in favor of an
    emoji. Only one icon field is sent (``icon_url`` wins when both are set).

    Parameters:
        webhook_url (str): Webhook URL to send alerts to
        username (str): Bot username to display (default: "detectkit")
        icon_url (str): Bot avatar image URL (default: detectkit brand avatar)
        icon_emoji (str): Bot emoji icon — use instead of an avatar image
            (default: None; falls back to the brand avatar)
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
        username: str = BRAND_USERNAME,
        icon_url: str | None = None,
        icon_emoji: str | None = None,
        channel: str | None = None,
        timeout: int = 10,
        extra_headers: dict[str, str] | None = None,
    ):
        """Initialize webhook channel."""
        if not webhook_url:
            raise ValueError("webhook_url is required")

        self.webhook_url = webhook_url
        self.username = username
        # Default to the detectkit brand avatar. An explicit icon_url or
        # icon_emoji opts out of the default; we only fill in the brand avatar
        # when the user configured neither.
        if icon_url is None and icon_emoji is None:
            icon_url = BRAND_ICON_URL
        self.icon_url = icon_url
        self.icon_emoji = icon_emoji
        self.channel = channel
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def send(
        self,
        alert_data: AlertData,
        template: str | None = None,
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

        # Color: red for anomaly, green for recovery, amber for no-data.
        if alert_data.is_recovery:
            color = "#36A64F"
        elif alert_data.is_no_data:
            color = "#F0AD4E"
        else:
            color = "#D63232"

        # Prepare payload using Mattermost/Slack attachments format.
        # Attachments give us: colored left sidebar, separate title, and
        # automatic "Show more" collapse for long body text in Mattermost.
        attachment = {
            "color": color,
            "title": title,
            "text": body,
        }

        payload: dict[str, object] = {
            "username": self.username,
            "attachments": [attachment],
        }

        # Send exactly one icon field: the avatar image (brand default or a
        # custom override) takes precedence over an emoji.
        if self.icon_url:
            payload["icon_url"] = self.icon_url
        elif self.icon_emoji:
            payload["icon_emoji"] = self.icon_emoji

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
            "Quorum {detector_count}/{min_detectors} · "
            "direction {direction} (policy {direction_policy}) · "
            "consecutive {consecutive_count}/{consecutive_required}\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
            "\n"
            "Latest point (evidence):\n"
            "· Time: {timestamp}\n"
            "· Value: {value_display} | Expected: {expected_range}\n"
            "· Severity: {severity:.2f}\n"
            "Detectors: {detector_name}\n"
            "Parameters: {detector_params}"
            "{mentions_line}"
        )

    def get_default_recovery_template(self) -> str:
        """
        Get default recovery message body template for webhook channels.

        Metric name is shown in the attachment title, so it is omitted from the body.
        """
        return (
            "{description_line}"
            "The alert condition no longer holds — "
            "the metric is back within expected bounds.\n"
            "Rule: min_detectors={min_detectors} · "
            "direction={direction_policy} · consecutive={consecutive_required}\n"
            "\n"
            "Latest point:\n"
            "· Time: {timestamp}\n"
            "· Value: {value_display} | Expected: {expected_range}\n"
            "Detectors: {detector_name}"
            "{mentions_line}"
        )

    def get_default_no_data_template(self) -> str:
        """Default no-data body template (metric name lives in the title)."""
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Status: query returned no datapoint for the latest interval"
            "{mentions_line}"
        )

    def get_default_error_template(self) -> str:
        """Default error body template (metric name lives in the title)."""
        return (
            "{description_line}"
            "Time: {timestamp}\n"
            "Error: {error_type}: {error_message}"
            "{mentions_line}"
        )

    def __repr__(self) -> str:
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"WebhookChannel(url='{url_preview}', username='{self.username}'{channel_info})"
