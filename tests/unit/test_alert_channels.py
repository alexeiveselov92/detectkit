"""Tests for alert channels."""

from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME
from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.alerting.channels.slack import SlackChannel
from detectkit.alerting.channels.telegram import TelegramChannel
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
        # The parameters the alert fired with are foregrounded (the shared
        # rule chip renders min_detectors/direction/consecutive — and the
        # fraction rule when configured).
        assert "{rule_display}" in template
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
        # One colored card whose long body folds behind "Show more".
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

    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_subject_strips_header_injection(self, mock_smtp):
        """CR/LF in the metric name must not inject extra email headers."""
        alert = _anomaly_alert()
        alert.metric_name = "cpu\r\nBcc: attacker@evil.test"
        self._channel().send(alert)
        msg = self._sent_message(mock_smtp)
        assert "attacker@evil.test" not in (msg["Bcc"] or "")
        assert "Bcc" not in msg or msg["Bcc"] is None
        assert "\n" not in msg["Subject"] and "\r" not in msg["Subject"]

    def test_build_html_body_escapes_and_brands_custom(self):
        """A custom-template body is escaped and rendered inside the branded card."""
        body = self._channel()._build_html_body(
            _anomaly_alert(), "value < 5 & rising", is_custom=True
        )
        assert BRAND_ICON_URL in body
        assert "value &lt; 5 &amp; rising" in body  # HTML-escaped

    def test_build_html_body_default_is_structured_card(self):
        """The default (no custom template) HTML is the structured stat card."""
        body = self._channel()._build_html_body(_anomaly_alert(), "ignored plain body")
        assert BRAND_ICON_URL in body
        assert "detectkit" in body  # wordmark survives images-off
        assert "ANOMALY" in body  # status pill
        assert "Expected" in body and "Severity" in body  # stat grid
        # status accent color present
        assert "#d63232".lower() in body.lower()

    def test_build_html_body_escapes_structured_values(self):
        """Interpolated values in the structured card are HTML-escaped."""
        alert = _anomaly_alert()
        alert.description = "drops < 5 & spikes"
        body = self._channel()._build_html_body(alert, "plain")
        assert "drops &lt; 5 &amp; spikes" in body

    def test_email_html_renders_dashboard_button(self):
        """A dashboard_url renders an Open-dashboard button linking to the URL."""
        alert = _anomaly_alert()
        alert.dashboard_url = "https://grafana.example/d/abc"
        body = self._channel()._build_html_body(alert, "plain")
        assert 'href="https://grafana.example/d/abc"' in body
        assert "Open dashboard" in body


class TestWebhookRichAttachment:
    """The default webhook payload is a single colored, foldable attachment."""

    def _payload(self, alert, template=None):
        return WebhookChannel(webhook_url="https://example.com/hooks/xxx").build_payload(
            alert, template
        )

    def test_single_attachment_holds_the_whole_body(self):
        alert = _anomaly_alert()
        alert.help_url = "https://docs.example/reading-alerts"
        attachments = self._payload(alert)["attachments"]
        # One block, one color — no second neutral-bar card.
        assert len(attachments) == 1
        card = attachments[0]
        assert card["color"] == "#D63232"
        assert "cpu_usage" in card["title"]
        # The whole body rides in one foldable ``text`` block (no fields grid):
        # essentials lead, the verbose tail follows and folds behind "Show more".
        assert "fields" not in card
        assert card["mrkdwn_in"] == ["text"]
        text = card["text"]
        assert "Value" in text
        assert "Expected" in text
        assert "Links" in text
        assert "Quorum" in text
        assert "Parameters" in text
        # Most-important-first: Rule + value/expected sit above the verbose tail.
        assert text.index("Rule") < text.index("Value")
        assert text.index("Value") < text.index("Quorum")
        assert text.index("Quorum") < text.index("Parameters")

    def test_branding_rides_the_single_attachment(self):
        # The footer + logo ride the one attachment and, being outside the text
        # fold, stay visible even when the body collapses.
        card = self._payload(_anomaly_alert())["attachments"][0]
        assert card["footer"] == "detectkit"
        assert card["footer_icon"] == BRAND_ICON_URL

    def test_mentions_ride_in_top_level_text(self):
        alert = _anomaly_alert()
        alert.mentions = ["here", "oncall"]
        payload = self._payload(alert)
        # Mentions notify only from top-level text, not inside the attachment.
        assert "here" in payload["text"]
        assert "@oncall" in payload["text"]

    def test_no_mentions_omits_top_level_text(self):
        payload = self._payload(_anomaly_alert())
        assert "text" not in payload

    def test_dashboard_url_makes_title_clickable(self):
        alert = _anomaly_alert()
        alert.dashboard_url = "https://grafana.example/d/abc"
        attachment = self._payload(alert)["attachments"][0]
        assert attachment["title_link"] == "https://grafana.example/d/abc"

    def test_custom_template_is_text_only_attachment(self):
        attachment = self._payload(_anomaly_alert(), template="CUSTOM: {metric_name}")[
            "attachments"
        ][0]
        assert "CUSTOM: cpu_usage" in attachment["text"]
        assert "fields" not in attachment  # opaque template → no fields grid
        assert attachment["color"] == "#D63232"
        assert attachment["footer"] == "detectkit"  # branding kept on fallback

    def test_recovery_uses_green_color(self):
        alert = _anomaly_alert()
        alert.is_recovery = True
        payload = self._payload(alert)
        assert len(payload["attachments"]) == 1  # one card, like every kind
        assert payload["attachments"][0]["color"] == "#36A64F"

    def test_error_uses_error_color(self):
        alert = _anomaly_alert()
        alert.is_error = True
        alert.error_type = "DBError"
        alert.error_message = "connection refused"
        payload = self._payload(alert)
        assert len(payload["attachments"]) == 1  # one card, like every kind
        assert payload["attachments"][0]["color"] == "#5A7A8C"

    def test_no_data_renders_single_attachment(self):
        # The short kinds collapse to one card too — guard against a per-kind
        # regression that re-splits or duplicates the attachment.
        alert = _anomaly_alert()
        alert.is_no_data = True
        alert.value = None
        attachments = self._payload(alert)["attachments"]
        assert len(attachments) == 1
        assert attachments[0]["color"] == "#F0AD4E"  # amber for no-data
        assert "no datapoint" in attachments[0]["text"]
        assert attachments[0]["footer"] == "detectkit"  # logo/footer still rides it


class TestTelegramHtmlRendering:
    """Telegram defaults to escaped HTML with a status dot and rich layout."""

    @staticmethod
    def _channel():
        return TelegramChannel(bot_token="t", chat_id="c")

    def _alert(self):
        return AlertData(
            metric_name="api_error_rate",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            timezone="UTC",
            value=4.2,
            confidence_lower=None,
            confidence_upper=1.1,
            detector_name="mad",
            detector_params='{"threshold": 3.0, "window_size": 2016}',
            direction="up",
            severity=3.4,
            detection_metadata={},
            consecutive_count=3,
            min_detectors=1,
            direction_policy="same",
            consecutive_required=3,
            detector_count=1,
        )

    def test_default_parse_mode_is_html(self):
        assert self._channel().parse_mode == "HTML"

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_html_message_has_status_dot_and_escaped_params(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        self._channel().send(self._alert())
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"
        assert payload["disable_web_page_preview"] is True
        text = payload["text"]
        assert text.startswith("\U0001f534")  # red status dot for anomaly
        assert "<b>" in text
        # The underscore-bearing params live inside <code> (HTML-safe), which is
        # exactly what the legacy Markdown mode could not render.
        assert "window_size" in text
        assert "<code>" in text

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_html_message_renders_dashboard_link(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        alert = self._alert()
        alert.dashboard_url = "https://grafana.example/d/abc?x=1&y=2"
        self._channel().send(alert)
        text = mock_post.call_args.kwargs["json"]["text"]
        assert 'href="https://grafana.example/d/abc?x=1&amp;y=2"' in text
        assert "Open dashboard" in text

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_special_chars_in_metric_are_escaped(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        alert = self._alert()
        alert.metric_name = "orders<5 & rising"
        self._channel().send(alert)
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "orders&lt;5 &amp; rising" in text

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_recovery_uses_green_dot(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        alert = self._alert()
        alert.is_recovery = True
        self._channel().send(alert)
        assert mock_post.call_args.kwargs["json"]["text"].startswith("\U0001f7e2")


def _proj_alert(*, project_name="my_monitoring", **overrides):
    """An anomaly alert carrying a project name (and any field overrides)."""
    base = {
        "metric_name": "cpu_usage",
        "timestamp": datetime(2024, 1, 1, 12, 0, 0),
        "timezone": "UTC",
        "value": 95.0,
        "confidence_lower": 70.0,
        "confidence_upper": 90.0,
        "detector_name": "zscore",
        "detector_params": "{}",
        "direction": "above",
        "severity": 2.5,
        "detection_metadata": {},
        "project_name": project_name,
    }
    base.update(overrides)
    return AlertData(**base)


class TestProjectNameRendering:
    """The project name surfaces by default across every channel.

    With the brand bot name + avatar kept, the project label is what keeps two
    projects posting to the same channel distinguishable.
    """

    # ---- base default titles (used by every channel via format_title) ----
    def test_base_titles_prefix_project_for_all_kinds(self):
        channel = MockAlertChannel()
        assert channel.format_title(_proj_alert()) == "🔴 [my_monitoring] Alert: cpu_usage"
        assert (
            channel.format_title(_proj_alert(is_recovery=True))
            == "🟢 [my_monitoring] Alert cleared: cpu_usage"
        )
        assert (
            channel.format_title(_proj_alert(value=None, is_no_data=True))
            == "🟡 [my_monitoring] No data: cpu_usage"
        )

    def test_base_title_collapses_without_project(self):
        channel = MockAlertChannel()
        assert channel.format_title(_proj_alert(project_name=None)) == "🔴 Alert: cpu_usage"

    def test_default_body_leads_with_project_prefix(self):
        channel = MockAlertChannel()
        message = channel.format_message(_proj_alert())
        assert message.startswith("🔴 [my_monitoring] Alert: cpu_usage")

    def test_project_name_template_vars(self):
        channel = MockAlertChannel()
        message = channel.format_message(
            _proj_alert(), template="{project_name_prefix}{metric_name} ({project_name})"
        )
        assert message == "[my_monitoring] cpu_usage (my_monitoring)"

    # ---- webhook (Slack/Mattermost) ----
    def test_webhook_title_prefixed_and_footer_paired(self):
        payload = WebhookChannel(webhook_url="https://x/hooks/y").build_payload(_proj_alert())
        # Single attachment: the title and the brand footer both ride the one card.
        assert payload["attachments"][0]["title"] == "🔴 [my_monitoring] Alert: cpu_usage"
        assert payload["attachments"][-1]["footer"] == "detectkit · my_monitoring"

    def test_webhook_footer_plain_without_project(self):
        payload = WebhookChannel(webhook_url="https://x/hooks/y").build_payload(
            _proj_alert(project_name=None)
        )
        assert payload["attachments"][-1]["footer"] == "detectkit"

    def test_webhook_custom_username_paired_with_project(self):
        payload = WebhookChannel(webhook_url="https://x/hooks/y", username="ops-bot").build_payload(
            _proj_alert()
        )
        assert payload["attachments"][-1]["footer"] == "ops-bot · my_monitoring"

    def test_webhook_custom_template_keeps_project_title_and_footer(self):
        """The opaque custom-template path still carries the project label."""
        payload = WebhookChannel(webhook_url="https://x/hooks/y").build_payload(
            _proj_alert(), template="CUSTOM: {metric_name}"
        )
        attachment = payload["attachments"][0]
        assert attachment["title"] == "🔴 [my_monitoring] Alert: cpu_usage"
        assert attachment["footer"] == "detectkit · my_monitoring"
        assert "fields" not in attachment  # still a text-only attachment

    # ---- telegram ----
    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_telegram_headline_prefixed_with_project(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        TelegramChannel(bot_token="t", chat_id="c").send(_proj_alert())
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "<b>[my_monitoring] Anomaly · cpu_usage</b>" in text

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_telegram_escapes_project_name(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        TelegramChannel(bot_token="t", chat_id="c").send(_proj_alert(project_name="a & b"))
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "[a &amp; b]" in text

    @patch("detectkit.alerting.channels.telegram.requests.post")
    def test_telegram_no_prefix_without_project(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        TelegramChannel(bot_token="t", chat_id="c").send(_proj_alert(project_name=None))
        text = mock_post.call_args.kwargs["json"]["text"]
        assert "<b>Anomaly · cpu_usage</b>" in text

    # ---- email ----
    @staticmethod
    def _email_channel():
        from detectkit.alerting.channels.email import EmailChannel

        return EmailChannel(smtp_host="h", smtp_port=587, from_email="a@x", to_emails=["t@x"])

    @patch("detectkit.alerting.channels.email.smtplib.SMTP")
    def test_email_subject_prefixed_with_project(self, mock_smtp):
        self._email_channel().send(_proj_alert())
        import email as email_lib
        from email.header import decode_header, make_header

        raw = mock_smtp.return_value.sendmail.call_args[0][2]
        # The emoji makes the Subject RFC2047-encoded; decode before asserting.
        subject = str(make_header(decode_header(email_lib.message_from_string(raw)["Subject"])))
        assert "[my_monitoring] Alert: cpu_usage" in subject

    def test_email_html_has_project_eyebrow_and_footer(self):
        body = self._email_channel()._build_html_body(_proj_alert(), "plain")
        # Eyebrow above the metric title + brand-paired footer.
        assert "my_monitoring" in body
        assert "Sent by detectkit &middot; my_monitoring" in body

    def test_email_html_escapes_project_name(self):
        body = self._email_channel()._build_html_body(_proj_alert(project_name="a & b"), "plain")
        assert "a &amp; b" in body

    def test_email_without_project_unchanged(self):
        body = self._email_channel()._build_html_body(_proj_alert(project_name=None), "plain")
        assert "Sent by detectkit</td>" in body
