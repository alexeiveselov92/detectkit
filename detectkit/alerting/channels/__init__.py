"""Alert channels for external notifications."""

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.discord import DiscordChannel
from detectkit.alerting.channels.email import EmailChannel
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.alerting.channels.googlechat import GoogleChatChannel
from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.alerting.channels.ntfy import NtfyChannel
from detectkit.alerting.channels.slack import SlackChannel
from detectkit.alerting.channels.teams import TeamsChannel
from detectkit.alerting.channels.telegram import TelegramChannel
from detectkit.alerting.channels.webhook import WebhookChannel

__all__ = [
    "AlertData",
    "BaseAlertChannel",
    "WebhookChannel",
    "MattermostChannel",
    "SlackChannel",
    "TelegramChannel",
    "EmailChannel",
    "DiscordChannel",
    "TeamsChannel",
    "GoogleChatChannel",
    "NtfyChannel",
    "AlertChannelFactory",
]
