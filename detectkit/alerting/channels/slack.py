"""
Slack alert channel.

Convenience wrapper around WebhookChannel for Slack.
"""

from detectkit.alerting.channels.branding import BRAND_USERNAME
from detectkit.alerting.channels.webhook import WebhookChannel


class SlackChannel(WebhookChannel):
    """
    Slack alert channel using incoming webhooks.

    This is a convenience wrapper around WebhookChannel specifically
    for Slack. Slack and Mattermost use compatible webhook formats.

    The bot defaults to the **detectkit brand avatar** and name; override the
    avatar with ``icon_url`` (a custom image) or opt out of the avatar with
    ``icon_emoji``. See :class:`WebhookChannel` for the icon precedence rules.

    Parameters:
        webhook_url (str): Slack incoming webhook URL
        username (str): Bot username to display (default: "detectkit")
        icon_url (str): Bot avatar image URL (default: detectkit brand avatar)
        icon_emoji (str): Bot emoji icon — use instead of an avatar image
        channel (str): Target Slack channel (optional, e.g., "#alerts")
        timeout (int): Request timeout in seconds (default: 10)

    Example:
        >>> channel = SlackChannel(
        ...     webhook_url="https://hooks.slack.com/services/xxx",
        ...     channel="#alerts"
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
        """Initialize Slack channel with webhook URL."""
        super().__init__(
            webhook_url=webhook_url,
            username=username,
            icon_url=icon_url,
            icon_emoji=icon_emoji,
            channel=channel,
            timeout=timeout,
        )

    def format_mentions(self, mentions: list[str]) -> str:
        """
        Format mentions for Slack.

        Slack uses <!keyword> for broadcast mentions and <@USER_ID> for
        user pings. Plain @username is display-only in webhook messages.

        Args:
            mentions: List of usernames, user IDs, or special keywords

        Returns:
            Formatted mentions string
        """
        if not mentions:
            return ""
        parts = []
        for m in mentions:
            if m in ("channel", "here", "everyone"):
                parts.append(f"<!{m}>")
            elif m == "all":
                parts.append("<!everyone>")
            elif m.startswith("U") and len(m) >= 9 and m[1:].isalnum():
                # Slack user ID format (e.g., U12345678)
                parts.append(f"<@{m}>")
            else:
                parts.append(f"@{m}")
        return " ".join(parts)

    def __repr__(self) -> str:
        """String representation."""
        url_preview = (
            self.webhook_url[:30] + "..." if len(self.webhook_url) > 30 else self.webhook_url
        )
        channel_info = f", channel='{self.channel}'" if self.channel else ""
        return f"SlackChannel(url='{url_preview}', username='{self.username}'{channel_info})"
