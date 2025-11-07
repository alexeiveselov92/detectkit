"""Alert channels for external notifications."""

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.alerting.channels.slack import SlackChannel
from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.alerting.channels.telegram import TelegramChannel
from detectkit.alerting.channels.email import EmailChannel

from detectkit.alerting.channels.factory import AlertChannelFactory

__all__ = [
    "AlertData",
    "BaseAlertChannel",
    "WebhookChannel",
    "MattermostChannel",
    "SlackChannel",
    "TelegramChannel",
    "EmailChannel",
    "AlertChannelFactory",
]
