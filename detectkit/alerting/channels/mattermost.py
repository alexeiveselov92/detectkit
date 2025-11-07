"""
Mattermost alert channel.

Convenience wrapper around WebhookChannel for Mattermost.
"""

from typing import Optional

from detectkit.alerting.channels.webhook import WebhookChannel


class MattermostChannel(WebhookChannel):
    """
    Mattermost alert channel using incoming webhooks.

    This is a convenience wrapper around WebhookChannel specifically
    for Mattermost. Mattermost webhooks are compatible with Slack API,
    so WebhookChannel can be used directly.

    Parameters:
        webhook_url (str): Mattermost incoming webhook URL
        username (str): Bot username to display (default: "detectk")
        icon_emoji (str): Bot emoji icon (default: ":warning:")
        timeout (int): Request timeout in seconds (default: 10)

    Example:
        >>> channel = MattermostChannel(
        ...     webhook_url="https://mattermost.example.com/hooks/xxx"
        ... )
        >>> success = channel.send(alert_data)
    """

    def __init__(
        self,
        webhook_url: str,
        username: str = "detectk",
        icon_emoji: str = ":warning:",
        channel: Optional[str] = None,
        timeout: int = 10,
    ):
        """Initialize Mattermost channel with webhook URL."""
        super().__init__(
            webhook_url=webhook_url,
            username=username,
            icon_emoji=icon_emoji,
            channel=channel,  # Optional: override webhook's default channel
            timeout=timeout,
        )

    def __repr__(self) -> str:
        """String representation."""
        url_preview = self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        return f"MattermostChannel(url='{url_preview}', username='{self.username}')"
