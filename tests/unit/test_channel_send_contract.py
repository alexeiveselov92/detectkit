"""Send-contract tests: every channel must accept (alert_data, template)
and return a truthy value on success — this is what the dispatch mixin
relies on. Telegram and Email historically violated the contract and
could never deliver a single alert through the orchestrator."""

from unittest.mock import Mock, patch

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData
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
from detectkit.alerting.orchestrator._dispatch import _DispatchMixin


def make_alert_data():
    return AlertData(
        metric_name="m",
        timestamp=np.datetime64("2024-01-01T12:00:00"),
        timezone="UTC",
        value=100.0,
        confidence_lower=80.0,
        confidence_upper=120.0,
        detector_name="mad",
        detector_params="{}",
        direction="up",
        severity=3.0,
        detection_metadata={},
        consecutive_count=1,
    )


class TestTelegramSendContract:
    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = TelegramChannel(bot_token="t", chat_id="c")
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called
        assert "custom m" in mock_post.call_args.kwargs["json"]["text"]

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_dispatch_records_success(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = TelegramChannel(bot_token="t", chat_id="c")
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"TelegramChannel": True}


class TestEmailSendContract:
    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_send_accepts_template_and_returns_true(self, mock_smtp):
        channel = EmailChannel(smtp_host="h", smtp_port=587, from_email="f@x", to_emails=["t@x"])
        assert channel.send(make_alert_data(), template=None) is True
        assert mock_smtp.called

    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_dispatch_records_success(self, mock_smtp):
        channel = EmailChannel(smtp_host="h", smtp_port=587, from_email="f@x", to_emails=["t@x"])
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"EmailChannel": True}


class TestWebhookSendContract:
    """Every ``format`` (attachments/json/alertmanager) must round-trip
    through the same send()/dispatch contract as every other channel."""

    @pytest.mark.parametrize("fmt", ["attachments", "json", "alertmanager"])
    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post, fmt):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://example.com/hooks/x", format=fmt)
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called

    @pytest.mark.parametrize("fmt", ["attachments", "json", "alertmanager"])
    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_dispatch_records_success(self, mock_post, fmt):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://example.com/hooks/x", format=fmt)
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"WebhookChannel": True}


class TestDiscordSendContract:
    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = DiscordChannel(webhook_url="https://discord.com/api/webhooks/1/abc")
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_dispatch_records_success(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = DiscordChannel(webhook_url="https://discord.com/api/webhooks/1/abc")
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"DiscordChannel": True}


class TestTeamsSendContract:
    @patch("detectkit.alerting.channels.teams.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = TeamsChannel(webhook_url="https://prod-00.westus.logic.azure.com/workflows/xxx")
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called

    @patch("detectkit.alerting.channels.teams.requests.post")
    def test_dispatch_records_success(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = TeamsChannel(webhook_url="https://prod-00.westus.logic.azure.com/workflows/xxx")
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"TeamsChannel": True}


class TestGoogleChatSendContract:
    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?key=K&token=T"
        )
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_dispatch_records_success(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?key=K&token=T"
        )
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"GoogleChatChannel": True}


class TestNtfySendContract:
    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_send_accepts_template_and_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = NtfyChannel(topic="my-alerts")
        assert channel.send(make_alert_data(), template="custom {metric_name}") is True
        assert mock_post.called

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_dispatch_records_success(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = NtfyChannel(topic="my-alerts")
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"NtfyChannel": True}


class TestDispatchCollisionSafety:
    def test_same_type_channels_get_distinct_result_keys(self):
        ok = Mock()
        ok.__class__ = type("FakeChannel", (), {})
        channel_a = Mock()
        channel_a.__class__.__name__ = "Webhook"
        channel_a.send = Mock(return_value=True)
        channel_b = Mock()
        channel_b.__class__.__name__ = "Webhook"
        channel_b.send = Mock(return_value=False)

        results = _DispatchMixin._dispatch([channel_a, channel_b], make_alert_data(), None, "alert")
        assert len(results) == 2
        assert results["Webhook"] is True
        assert results["Webhook#2"] is False


class TestFactoryRegistry:
    """Every registered type string must build its channel class from a
    minimal config — a typo in the config-facing name would otherwise only
    surface at user runtime."""

    CASES = [
        ("webhook", {"webhook_url": "https://example.com/hook"}, WebhookChannel),
        ("mattermost", {"webhook_url": "https://example.com/hook"}, MattermostChannel),
        ("slack", {"webhook_url": "https://hooks.slack.com/services/x"}, SlackChannel),
        ("telegram", {"bot_token": "t", "chat_id": "c"}, TelegramChannel),
        (
            "email",
            {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "from_email": "a@example.com",
                "to_emails": ["b@example.com"],
            },
            EmailChannel,
        ),
        ("discord", {"webhook_url": "https://discord.com/api/webhooks/1/a"}, DiscordChannel),
        ("teams", {"webhook_url": "https://example.com/flow"}, TeamsChannel),
        (
            "googlechat",
            {"webhook_url": "https://chat.googleapis.com/v1/spaces/A/messages?key=K&token=T"},
            GoogleChatChannel,
        ),
        ("ntfy", {"topic": "alerts"}, NtfyChannel),
    ]

    @pytest.mark.parametrize("type_name,config,expected_class", CASES)
    def test_registered_type_builds_expected_class(self, type_name, config, expected_class):
        channel = AlertChannelFactory.create(type_name, config)
        assert type(channel) is expected_class

    def test_registry_covers_exactly_the_documented_types(self):
        assert AlertChannelFactory.list_available_types() == [
            "discord",
            "email",
            "googlechat",
            "mattermost",
            "ntfy",
            "slack",
            "teams",
            "telegram",
            "webhook",
        ]
