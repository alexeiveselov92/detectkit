"""
Alert channel factory for creating channel instances from configuration.
"""

from detectkit.alerting.channels.base import BaseAlertChannel
from detectkit.alerting.channels.discord import DiscordChannel
from detectkit.alerting.channels.email import EmailChannel
from detectkit.alerting.channels.googlechat import GoogleChatChannel
from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.alerting.channels.ntfy import NtfyChannel
from detectkit.alerting.channels.slack import SlackChannel
from detectkit.alerting.channels.teams import TeamsChannel
from detectkit.alerting.channels.telegram import TelegramChannel
from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.utils.env_interpolation import interpolate_env_vars


class AlertChannelFactory:
    """
    Factory for creating alert channel instances from configuration.

    Supports environment variable interpolation in config values.

    Example:
        >>> factory = AlertChannelFactory()
        >>> channel = factory.create("mattermost", {"webhook_url": "https://..."})
        >>> isinstance(channel, MattermostChannel)
        True
    """

    # Registry of available channel types
    CHANNEL_TYPES = {
        "webhook": WebhookChannel,
        "mattermost": MattermostChannel,
        "slack": SlackChannel,
        "telegram": TelegramChannel,
        "email": EmailChannel,
        "discord": DiscordChannel,
        "teams": TeamsChannel,
        "googlechat": GoogleChatChannel,
        "ntfy": NtfyChannel,
    }

    @classmethod
    def create(cls, channel_type: str, params: dict) -> BaseAlertChannel:
        """
        Create alert channel instance from type and parameters.

        Supports environment variable interpolation:
        - ${ENV_VAR} or {{ env_var('ENV_VAR') }}

        Args:
            channel_type: Type of channel (e.g., "mattermost", "slack")
            params: Channel parameters

        Returns:
            Alert channel instance

        Raises:
            ValueError: If channel type is unknown

        Example:
            >>> channel = AlertChannelFactory.create(
            ...     "mattermost",
            ...     {"webhook_url": "${MATTERMOST_WEBHOOK}"}
            ... )
        """
        channel_type = channel_type.lower()

        if channel_type not in cls.CHANNEL_TYPES:
            available = ", ".join(sorted(cls.CHANNEL_TYPES.keys()))
            raise ValueError(
                f"Unknown channel type: '{channel_type}'. " f"Available types: {available}"
            )

        # Interpolate environment variables in params
        interpolated_params = cls._interpolate_env_vars(params)

        channel_class = cls.CHANNEL_TYPES[channel_type]

        try:
            return channel_class(**interpolated_params)
        except TypeError as e:
            raise ValueError(f"Invalid parameters for {channel_type} channel: {e}") from e

    @classmethod
    def _interpolate_env_vars(cls, params: dict) -> dict:
        """Interpolate ``${VAR}`` and ``{{ env_var('VAR') }}`` placeholders.

        Delegates to :func:`detectkit.utils.env_interpolation.interpolate_env_vars`,
        which walks nested dicts/lists recursively.
        """
        return interpolate_env_vars(params)

    @classmethod
    def create_from_config(cls, channel_config: dict) -> BaseAlertChannel:
        """
        Create channel from configuration dictionary.

        Args:
            channel_config: Configuration with 'type' and channel-specific params
                Example: {
                    "type": "mattermost",
                    "webhook_url": "${MATTERMOST_WEBHOOK}",
                    "username": "detectkit"
                }

        Returns:
            Alert channel instance

        Example:
            >>> config = {
            ...     "type": "mattermost",
            ...     "webhook_url": "https://example.com/hooks/xxx"
            ... }
            >>> channel = AlertChannelFactory.create_from_config(config)
        """
        channel_type = channel_config.get("type")
        if not channel_type:
            raise ValueError("Channel config must have 'type' field")

        # Extract all params except 'type'
        params = {k: v for k, v in channel_config.items() if k != "type"}

        return cls.create(channel_type, params)

    @classmethod
    def create_multiple(cls, channel_configs: list[dict]) -> list[BaseAlertChannel]:
        """
        Create multiple channels from list of configurations.

        Args:
            channel_configs: List of channel configurations

        Returns:
            List of channel instances

        Example:
            >>> configs = [
            ...     {"type": "mattermost", "webhook_url": "https://..."},
            ...     {"type": "slack", "webhook_url": "https://...", "channel": "#alerts"},
            ... ]
            >>> channels = AlertChannelFactory.create_multiple(configs)
            >>> len(channels)
            2
        """
        channels = []
        for config in channel_configs:
            channel = cls.create_from_config(config)
            channels.append(channel)
        return channels

    @classmethod
    def list_available_types(cls) -> list[str]:
        """
        Get list of available channel types.

        Returns:
            List of channel type names

        Example:
            >>> types = AlertChannelFactory.list_available_types()
            >>> "mattermost" in types
            True
        """
        return sorted(cls.CHANNEL_TYPES.keys())
