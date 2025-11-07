"""
Telegram alert channel implementation.

Sends anomaly alerts via Telegram Bot API.
"""

from typing import Any, Dict, Optional

import requests

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel


class TelegramChannel(BaseAlertChannel):
    """
    Telegram alert channel using Bot API.

    Sends formatted messages to Telegram chat using bot token.

    Attributes:
        bot_token: Telegram bot token (from @BotFather)
        chat_id: Target chat ID (user, group, or channel)
        parse_mode: Message parse mode ("Markdown", "HTML", or None)
        disable_notification: Send silently without notification

    Example:
        >>> channel = TelegramChannel(
        ...     bot_token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
        ...     chat_id="-1001234567890"
        ... )
        >>> alert = AlertData(
        ...     metric_name="cpu_usage",
        ...     timestamp=np.datetime64("2024-01-01T10:00:00"),
        ...     value=95.0,
        ...     is_anomaly=True
        ... )
        >>> channel.send(alert)
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
        template: Optional[str] = None,
        **kwargs,
    ):
        """
        Initialize Telegram channel.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Target chat ID (can be user_id, @channel_name, or group ID)
            parse_mode: Message formatting ("Markdown", "HTML", or None)
            disable_notification: Send silently without notification sound
            template: Custom message template (optional)
            **kwargs: Additional parameters (ignored)

        Raises:
            ValueError: If bot_token or chat_id is missing
        """
        if not bot_token:
            raise ValueError("bot_token is required for TelegramChannel")
        if not chat_id:
            raise ValueError("chat_id is required for TelegramChannel")

        self.bot_token = bot_token
        self.chat_id = chat_id
        self.parse_mode = parse_mode
        self.disable_notification = disable_notification
        self.template = template

    def send(self, alert_data: AlertData) -> None:
        """
        Send alert to Telegram.

        Args:
            alert_data: Alert information to send

        Raises:
            requests.RequestException: If request fails
            requests.HTTPError: If Telegram API returns error

        Example:
            >>> channel.send(alert_data)
        """
        message = self.format_message(alert_data, self.template)

        # Telegram Bot API URL
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_notification": self.disable_notification,
        }

        if self.parse_mode:
            payload["parse_mode"] = self.parse_mode

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to send Telegram alert: {e}")

    def __repr__(self) -> str:
        """String representation."""
        return f"TelegramChannel(chat_id={self.chat_id})"
