"""Tests for alert channels."""

from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.mattermost import MattermostChannel


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

        assert "2024-01-01 12:00:00" in message
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
        """Test default template retrieval."""
        channel = MockAlertChannel()
        template = channel.get_default_template()

        assert "Anomaly detected" in template
        assert "{metric_name}" in template
        assert "{value}" in template

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


class TestMattermostChannel:
    """Test MattermostChannel."""

    def test_init_valid(self):
        """Test initialization with valid webhook URL."""
        channel = MattermostChannel(webhook_url="https://example.com/hooks/xxx")

        assert channel.webhook_url == "https://example.com/hooks/xxx"
        assert channel.username == "detectk"
        assert channel.icon_emoji == ":warning:"

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        channel = MattermostChannel(
            webhook_url="https://example.com/hooks/xxx",
            username="custom_bot",
            icon_emoji=":fire:",
            timeout=30,
        )

        assert channel.username == "custom_bot"
        assert channel.icon_emoji == ":fire:"
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
        # Check payload structure
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert "text" in payload
        assert payload["username"] == "detectk"
        assert payload["icon_emoji"] == ":warning:"

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
        assert "CUSTOM: cpu_usage = 95.0" in payload["text"]

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
