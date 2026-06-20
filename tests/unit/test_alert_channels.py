"""Tests for alert channels."""

from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME
from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.alerting.channels.slack import SlackChannel
from detectkit.alerting.channels.webhook import WebhookChannel


# Mock channel for testing BaseAlertChannel
class MockAlertChannel(BaseAlertChannel):
    """Mock channel for testing."""

    def __init__(self):
        self.sent_messages = []

    def send(self, alert_data, template=None):
        """Mock send that records message."""
        message = self.format_message(alert_data, template)
        self.sent_messages.append(message)
        return True


class TestAlertData:
    """Test AlertData dataclass."""

    def test_create_alert_data(self):
        """Test creating AlertData."""
        alert = AlertData(
            metric_name="test_metric",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="test_detector",
            detector_params='{"threshold": 3.0}',
            direction="above",
            severity=2.5,
            detection_metadata={"foo": "bar"},
            consecutive_count=3,
        )

        assert alert.metric_name == "test_metric"
        assert alert.value == 100.0
        assert alert.consecutive_count == 3


class TestBaseAlertChannel:
    """Test BaseAlertChannel abstract class."""

    def test_format_message_default_template(self):
        """Test message formatting with default template."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=95.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="above",
            severity=2.5,
            detection_metadata={},
        )

        message = channel.format_message(alert)

        assert "cpu_usage" in message
        assert "95.0" in message
        assert "[70.00, 90.00]" in message
        assert "zscore" in message
        assert "above" in message

    def test_format_message_custom_template(self):
        """Test message formatting with custom template."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=95.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="above",
            severity=2.5,
            detection_metadata={},
        )

        template = "ALERT: {metric_name} = {value}"
        message = channel.format_message(alert, template)

        assert message == "ALERT: cpu_usage = 95.0"

    def test_format_message_with_numpy_timestamp(self):
        """Test formatting with numpy datetime64."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="test",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="Europe/Moscow",
            value=100.0,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )

        message = channel.format_message(alert)

        # 12:00 UTC = 15:00 Moscow (UTC+3)
        assert "2024-01-01 15:00:00" in message
        assert "Europe/Moscow" in message

    def test_format_message_missing_confidence(self):
        """Test formatting when confidence bounds are None."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="test",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=100.0,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )

        message = channel.format_message(alert)

        assert "N/A" in message  # Confidence interval shows as N/A

    def test_get_default_template(self):
        """Default anomaly template is alert-centric and surfaces the rule."""
        channel = MockAlertChannel()
        template = channel.get_default_template()

        # The alert is the subject, not the anomaly.
        assert "Alert" in template
        assert "Anomaly detected" not in template
        assert "{metric_name}" in template
        # The parameters the alert fired with are foregrounded.
        assert "{min_detectors}" in template
        assert "{direction_policy}" in template
        assert "{consecutive_required}" in template
        # The anomaly value is still present (secondary).
        assert "{value_display}" in template

    def test_send_method(self):
        """Test send method is called."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="test",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )

        success = channel.send(alert)

        assert success is True
        assert len(channel.sent_messages) == 1


class TestRecoveryFormatting:
    """Test recovery message formatting."""

    def test_format_recovery_default_template(self):
        """Test recovery uses recovery template by default."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=85.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_recovery=True,
        )

        message = channel.format_message(alert)

        assert "cleared" in message.lower()
        assert "cpu_usage" in message
        assert "85.0" in message

    def test_format_recovery_custom_template(self):
        """Test recovery with custom template."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=85.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_recovery=True,
        )

        template = "{status}: {metric_name} back to normal, value={value}"
        message = channel.format_message(alert, template)

        assert message == "RECOVERED: cpu_usage back to normal, value=85.0"

    def test_format_anomaly_has_status_variable(self):
        """Test that anomaly alerts also have {status} variable."""
        channel = MockAlertChannel()

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=95.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="above",
            severity=2.5,
            detection_metadata={},
            is_recovery=False,
        )

        template = "{status}: {metric_name} = {value}"
        message = channel.format_message(alert, template)

        assert message == "ANOMALY: cpu_usage = 95.0"

    def test_get_default_recovery_template(self):
        """Test default recovery template."""
        channel = MockAlertChannel()
        template = channel.get_default_recovery_template()

        assert "cleared" in template.lower()
        assert "{metric_name}" in template

    def test_is_recovery_default_false(self):
        """Test is_recovery defaults to False."""
        alert = AlertData(
            metric_name="test",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=100.0,
            confidence_lower=80.0,
            confidence_upper=120.0,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )
        assert alert.is_recovery is False


class TestMattermostChannel:
    """Test MattermostChannel."""

    def test_init_valid(self):
        """Defaults to the detectkit brand name and avatar."""
        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        assert channel.webhook_url == "https://example.com/hooks/xxx"
        assert channel.username == "detectkit"
        # Brand avatar by default; no emoji unless explicitly set.
        assert channel.icon_url == BRAND_ICON_URL
        assert channel.icon_emoji is None

    def test_init_custom_params(self):
        """An explicit emoji opts out of the brand avatar."""
        channel = MattermostChannel(
            webhook_url="https://example.com/hooks/xxx",
            username="custom_bot",
            icon_emoji=":fire:",
            timeout=30,
        )

        assert channel.username == "custom_bot"
        assert channel.icon_emoji == ":fire:"
        # icon_emoji given → brand avatar is not filled in.
        assert channel.icon_url is None
        assert channel.timeout == 30

    def test_init_missing_webhook(self):
        """Test that missing webhook raises error."""
        with pytest.raises(ValueError, match="webhook_url is required"):
            MattermostChannel(webhook_url="")

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_success(self, mock_post):
        """Test successful send to Mattermost."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=95.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="above",
            severity=2.5,
            detection_metadata={},
        )

        success = channel.send(alert)

        assert success is True
        assert mock_post.called
        # Check payload structure (attachments format)
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert "attachments" in payload
        assert len(payload["attachments"]) == 1
        attachment = payload["attachments"][0]
        assert attachment["color"] == "#D63232"  # red for anomaly
        assert "cpu_usage" in attachment["title"]
        assert payload["username"] == "detectkit"
        # Brand avatar is sent as icon_url (not an emoji) by default.
        assert payload["icon_url"] == BRAND_ICON_URL
        assert "icon_emoji" not in payload

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_with_custom_template(self, mock_post):
        """Test send with custom message template."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        alert = AlertData(
            metric_name="cpu_usage",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=95.0,
            confidence_lower=70.0,
            confidence_upper=90.0,
            detector_name="zscore",
            detector_params="{}",
            direction="above",
            severity=2.5,
            detection_metadata={},
        )

        template = "CUSTOM: {metric_name} = {value}"
        success = channel.send(alert, template=template)

        assert success is True
        payload = mock_post.call_args[1]["json"]
        assert "CUSTOM: cpu_usage = 95.0" in payload["attachments"][0]["text"]

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_request_error(self, mock_post):
        """Test handling of request error."""
        import requests

        mock_post.side_effect = requests.RequestException("Connection error")

        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        alert = AlertData(
            metric_name="test",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=100.0,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )

        success = channel.send(alert)

        assert success is False  # Should return False on error

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_http_error(self, mock_post):
        """Test handling of HTTP error response."""
        import requests

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404")
        mock_post.return_value = mock_response

        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        alert = AlertData(
            metric_name="test",
            timestamp=datetime(2024, 1, 1),
            timezone="UTC",
            value=100.0,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="test",
            detector_params="{}",
            direction="above",
            severity=1.0,
            detection_metadata={},
        )

        success = channel.send(alert)

        assert success is False

    def test_repr(self):
        """Test string representation."""
        channel = MattermostChannel(
            webhook_url="https://example.com/hooks/very_long_url_here",
            username="bot",
        )

        repr_str = repr(channel)

        assert "MattermostChannel" in repr_str
        assert "https://example.com" in repr_str
        assert "bot" in repr_str


def _anomaly_alert():
    return AlertData(
        metric_name="cpu_usage",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        timezone="UTC",
        value=95.0,
        confidence_lower=70.0,
        confidence_upper=90.0,
        detector_name="zscore",
        detector_params="{}",
        direction="above",
        severity=2.5,
        detection_metadata={},
    )


def _sent_payload(mock_post):
    return mock_post.call_args[1]["json"]


class TestBrandAvatar:
    """Default bot identity is the detectkit brand; overrides win cleanly."""

    def test_webhook_defaults_to_brand_name_and_avatar(self):
        channel = WebhookChannel(webhook_url="https://example.com/hooks/xxx")
        assert channel.username == BRAND_USERNAME
        assert channel.icon_url == BRAND_ICON_URL
        assert channel.icon_emoji is None

    def test_slack_inherits_brand_avatar(self):
        channel = SlackChannel(webhook_url="https://hooks.slack.com/services/xxx")
        assert channel.username == BRAND_USERNAME
        assert channel.icon_url == BRAND_ICON_URL

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_payload_sends_brand_icon_url_by_default(self, mock_post):
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
        WebhookChannel(webhook_url="https://example.com/hooks/xxx").send(_anomaly_alert())
        payload = _sent_payload(mock_post)
        assert payload["icon_url"] == BRAND_ICON_URL
        assert "icon_emoji" not in payload

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_icon_emoji_override_replaces_avatar(self, mock_post):
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://example.com/hooks/xxx", icon_emoji=":fire:")
        channel.send(_anomaly_alert())
        payload = _sent_payload(mock_post)
        assert payload["icon_emoji"] == ":fire:"
        assert "icon_url" not in payload

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_custom_icon_url_override(self, mock_post):
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
        custom = "https://example.com/avatar.png"
        channel = WebhookChannel(webhook_url="https://example.com/hooks/xxx", icon_url=custom)
        channel.send(_anomaly_alert())
        payload = _sent_payload(mock_post)
        assert payload["icon_url"] == custom
        assert "icon_emoji" not in payload

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_icon_url_wins_when_both_set(self, mock_post):
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
        channel = WebhookChannel(
            webhook_url="https://example.com/hooks/xxx",
            icon_url="https://example.com/avatar.png",
            icon_emoji=":fire:",
        )
        channel.send(_anomaly_alert())
        payload = _sent_payload(mock_post)
        assert payload["icon_url"] == "https://example.com/avatar.png"
        assert "icon_emoji" not in payload


class TestEmailBranding:
    """Email carries the brand via the From display name and an HTML logo."""

    @staticmethod
    def _sent_message(mock_smtp):
        import email as email_lib

        raw_message = mock_smtp.return_value.sendmail.call_args[0][2]
        return email_lib.message_from_string(raw_message)

    def _channel(self):
        from detectkit.alerting.channels.email import EmailChannel

        return EmailChannel(
            smtp_host="h", smtp_port=587, from_email="alerts@example.com", to_emails=["t@x"]
        )

    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_from_header_uses_brand_display_name(self, mock_smtp):
        self._channel().send(_anomaly_alert())
        from_header = self._sent_message(mock_smtp)["From"]
        # "detectkit <alerts@example.com>"
        assert BRAND_USERNAME in from_header
        assert "alerts@example.com" in from_header

    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_html_alternative_embeds_brand_logo(self, mock_smtp):
        self._channel().send(_anomaly_alert())
        msg = self._sent_message(mock_smtp)
        html_parts = [
            p.get_payload(decode=True).decode("utf-8")
            for p in msg.walk()
            if p.get_content_type() == "text/html"
        ]
        assert len(html_parts) == 1
        assert BRAND_ICON_URL in html_parts[0]
        # Plain-text alternative is still present as a fallback.
        assert any(p.get_content_type() == "text/plain" for p in msg.walk())

    def test_build_html_body_escapes_and_brands(self):
        body = self._channel()._build_html_body("value < 5 & rising")
        assert BRAND_ICON_URL in body
        assert "value &lt; 5 &amp; rising" in body  # HTML-escaped
