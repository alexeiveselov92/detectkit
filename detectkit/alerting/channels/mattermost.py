"""
Mattermost alert channel.

Convenience wrapper around WebhookChannel for Mattermost.
"""

from detectkit.alerting.channels.branding import BRAND_USERNAME
from detectkit.alerting.channels.webhook import WebhookChannel


class MattermostChannel(WebhookChannel):
    """
    Mattermost alert channel using incoming webhooks.

    This is a convenience wrapper around WebhookChannel specifically
    for Mattermost. Mattermost webhooks are compatible with Slack API,
    so WebhookChannel can be used directly.

    The bot defaults to the **detectkit brand avatar** and name; override the
    avatar with ``icon_url`` (a custom image) or opt out of the avatar with
    ``icon_emoji``. See :class:`WebhookChannel` for the icon precedence rules.

    Parameters:
        webhook_url (str): Mattermost incoming webhook URL
        username (str): Bot username to display (default: "detectkit")
        icon_url (str): Bot avatar image URL (default: detectkit brand avatar)
        icon_emoji (str): Bot emoji icon — use instead of an avatar image
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
        username: str = BRAND_USERNAME,
        icon_url: str | None = None,
        icon_emoji: str | None = None,
        channel: str | None = None,
        timeout: int = 10,
    ):
        """Initialize Mattermost channel with webhook URL."""
        super().__init__(
            webhook_url=webhook_url,
            username=username,
            icon_url=icon_url,
            icon_emoji=icon_emoji,
            channel=channel,  # Optional: override webhook's default channel
            timeout=timeout,
        )

    def __repr__(self) -> str:
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        return f"MattermostChannel(url='{url_preview}', username='{self.username}')"
