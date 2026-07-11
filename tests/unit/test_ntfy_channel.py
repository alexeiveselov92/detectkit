"""Tests for the ntfy.sh alert channel (JSON publishing)."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import requests

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.ntfy import NtfyChannel


def _base_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "metric_name": "cpu_usage",
        "timestamp": datetime(2024, 1, 1, 12, 0, 0),
        "timezone": "UTC",
        "value": 95.0,
        "confidence_lower": 70.0,
        "confidence_upper": 90.0,
        "detector_name": "zscore",
        "detector_params": '{"threshold": 3.0}',
        "direction": "above",
        "severity": 2.5,
        "detection_metadata": {},
        "detector_count": 1,
        "min_detectors": 1,
        "direction_policy": "same",
        "consecutive_required": 1,
        "consecutive_count": 1,
    }
    base.update(overrides)
    return base


def _anomaly_alert(**overrides: object) -> AlertData:
    return AlertData(**_base_kwargs(**overrides))


def _recovery_alert(**overrides: object) -> AlertData:
    return AlertData(**_base_kwargs(is_recovery=True, direction="none", **overrides))


def _no_data_alert(**overrides: object) -> AlertData:
    return AlertData(**_base_kwargs(is_no_data=True, value=None, **overrides))


def _error_alert(**overrides: object) -> AlertData:
    return AlertData(
        **_base_kwargs(
            is_error=True,
            value=None,
            error_type="DBError",
            error_message="connection refused",
            **overrides,
        )
    )


def _ok_response() -> Mock:
    return Mock(status_code=200, raise_for_status=Mock())


class TestNtfyChannelInit:
    """Constructor validation and default resolution."""

    def test_valid_minimal_init(self):
        channel = NtfyChannel(topic="alerts")
        assert channel.topic == "alerts"
        assert channel.server == "https://ntfy.sh"
        assert channel.token is None
        assert channel.priority is None
        assert channel.timeout == 10

    def test_missing_topic_raises(self):
        with pytest.raises(ValueError, match="topic is required"):
            NtfyChannel(topic="")

    def test_trailing_slash_stripped_from_server(self):
        channel = NtfyChannel(topic="alerts", server="https://ntfy.example.com/")
        assert channel.server == "https://ntfy.example.com"

    @pytest.mark.parametrize("bad_priority", [0, 6, -1, 100])
    def test_invalid_priority_raises(self, bad_priority):
        with pytest.raises(ValueError, match="priority must be between 1 and 5"):
            NtfyChannel(topic="alerts", priority=bad_priority)

    @pytest.mark.parametrize("good_priority", [1, 2, 3, 4, 5])
    def test_valid_priority_accepted(self, good_priority):
        channel = NtfyChannel(topic="alerts", priority=good_priority)
        assert channel.priority == good_priority

    def test_unknown_kwarg_raises_type_error(self):
        with pytest.raises(TypeError):
            NtfyChannel(topic="alerts", bogus="x")  # type: ignore[call-arg]

    def test_repr(self):
        channel = NtfyChannel(topic="alerts", server="https://ntfy.example.com")
        r = repr(channel)
        assert "NtfyChannel" in r
        assert "alerts" in r
        assert "ntfy.example.com" in r


class TestNtfyPayloadShape:
    """Payload field shape for each of the four alert kinds."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_anomaly_payload_shape(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_anomaly_alert()) is True

        # Posts to the server ROOT, never server/topic.
        assert mock_post.call_args.args[0] == "https://ntfy.sh"
        payload = mock_post.call_args.kwargs["json"]

        assert payload["topic"] == "alerts"
        assert "cpu_usage" in payload["title"]
        assert isinstance(payload["message"], str) and payload["message"]
        assert payload["priority"] == 4
        assert payload["tags"] == ["rotating_light"]
        assert "click" not in payload
        assert "actions" not in payload

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_recovery_payload_shape(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_recovery_alert()) is True
        payload = mock_post.call_args.kwargs["json"]

        assert payload["tags"] == ["white_check_mark"]
        assert payload["priority"] == 3
        assert "cleared" in payload["title"].lower()

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_no_data_payload_shape(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_no_data_alert()) is True
        payload = mock_post.call_args.kwargs["json"]

        assert payload["tags"] == ["warning"]
        assert payload["priority"] == 3
        assert "no data" in payload["title"].lower()

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_error_payload_shape(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_error_alert()) is True
        payload = mock_post.call_args.kwargs["json"]

        assert payload["tags"] == ["large_blue_circle"]
        assert payload["priority"] == 4
        assert "error" in payload["title"].lower() or "pipeline" in payload["title"].lower()

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_status_dot_is_stripped_from_title(self, mock_post):
        """ntfy already renders the tag as a leading emoji; the base status
        dot must not be doubled into the title."""
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert())
        title = mock_post.call_args.kwargs["json"]["title"]
        for dot in ("\U0001f534", "\U0001f7e2", "\U0001f7e1", "\U0001f535"):
            assert not title.startswith(dot)
        assert title.startswith("Alert") or "cpu_usage" in title

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_dashboard_url_becomes_click_not_action(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        alert = _anomaly_alert(dashboard_url="https://grafana.example/d/abc")
        channel.send(alert)
        payload = mock_post.call_args.kwargs["json"]

        assert payload["click"] == "https://grafana.example/d/abc"
        # Never duplicated as a view action.
        for action in payload.get("actions", []):
            assert action["url"] != "https://grafana.example/d/abc"

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_links_and_help_become_view_actions(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        alert = _anomaly_alert(
            links={"Runbook": "https://wiki.example/runbook"},
            help_url="https://dtk.pipelab.dev/guides/reading-alerts/",
        )
        channel.send(alert)
        payload = mock_post.call_args.kwargs["json"]

        actions = payload["actions"]
        assert {"action": "view", "label": "Runbook", "url": "https://wiki.example/runbook"} in (
            actions
        )
        assert any(a["url"] == "https://dtk.pipelab.dev/guides/reading-alerts/" for a in actions)
        for action in actions:
            assert action["action"] == "view"

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_actions_capped_at_three(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        alert = _anomaly_alert(
            links={
                "A": "https://x/a",
                "B": "https://x/b",
                "C": "https://x/c",
                "D": "https://x/d",
            },
            help_url="https://dtk.pipelab.dev/guides/reading-alerts/",
        )
        channel.send(alert)
        payload = mock_post.call_args.kwargs["json"]
        assert len(payload["actions"]) == 3

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_no_links_omits_actions_key(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert())
        payload = mock_post.call_args.kwargs["json"]
        assert "actions" not in payload


class TestNtfyPriorityOverride:
    """priority= overrides only the anomaly/error default; recovery/no-data stay calm."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_override_applies_to_anomaly(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", priority=5)
        channel.send(_anomaly_alert())
        assert mock_post.call_args.kwargs["json"]["priority"] == 5

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_override_applies_to_error(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", priority=5)
        channel.send(_error_alert())
        assert mock_post.call_args.kwargs["json"]["priority"] == 5

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_override_does_not_apply_to_recovery(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", priority=5)
        channel.send(_recovery_alert())
        assert mock_post.call_args.kwargs["json"]["priority"] == 3

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_override_does_not_apply_to_no_data(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", priority=5)
        channel.send(_no_data_alert())
        assert mock_post.call_args.kwargs["json"]["priority"] == 3


class TestNtfyAuth:
    """Bearer-token vs basic-auth header/param construction."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_token_sends_bearer_header(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", token="tk_abc123")
        channel.send(_anomaly_alert())
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tk_abc123"
        assert mock_post.call_args.kwargs["auth"] is None

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_user_password_sends_basic_auth_tuple(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", user="alice", password="s3cret")
        channel.send(_anomaly_alert())
        assert mock_post.call_args.kwargs["auth"] == ("alice", "s3cret")
        assert "Authorization" not in mock_post.call_args.kwargs["headers"]

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_token_wins_over_user_password(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts", token="tk_abc123", user="alice", password="s3cret")
        channel.send(_anomaly_alert())
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer tk_abc123"
        assert mock_post.call_args.kwargs["auth"] is None

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_no_credentials_sends_no_auth(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert())
        assert mock_post.call_args.kwargs["auth"] is None
        assert "Authorization" not in mock_post.call_args.kwargs["headers"]


class TestNtfyCustomTemplate:
    """A custom template flows through format_message as the plain body."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_custom_template_used_as_message(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert(), template="CUSTOM: {metric_name} = {value}")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["message"] == "CUSTOM: cpu_usage = 95.0"

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_custom_template_does_not_change_title_tags_priority(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert(), template="CUSTOM: {metric_name}")
        payload = mock_post.call_args.kwargs["json"]
        assert "cpu_usage" in payload["title"]
        assert payload["tags"] == ["rotating_light"]
        assert payload["priority"] == 4

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_custom_template_keeps_click_and_actions(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        alert = _anomaly_alert(
            dashboard_url="https://grafana.example/d/abc",
            links={"Runbook": "https://wiki.example/runbook"},
        )
        channel.send(alert, template="CUSTOM: {metric_name}")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["click"] == "https://grafana.example/d/abc"
        assert payload["actions"][0]["url"] == "https://wiki.example/runbook"


class TestNtfyMentions:
    """Mentions render via the inherited default '@name' formatting."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_mentions_appear_in_message(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert(mentions=["oncall", "here"]))
        message = mock_post.call_args.kwargs["json"]["message"]
        assert "@oncall" in message
        assert "@here" in message

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_no_mentions_no_mention_lines(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        channel.send(_anomaly_alert())
        message = mock_post.call_args.kwargs["json"]["message"]
        assert "@" not in message


class TestNtfyTruncation:
    """Message is capped at 3800 UTF-8 bytes on a character boundary."""

    def test_cap_message_no_truncation_when_short(self):
        text = "short message"
        assert NtfyChannel._cap_message(text) == text

    def test_cap_message_truncates_and_appends_ellipsis(self):
        text = "a" * 20
        capped = NtfyChannel._cap_message(text, limit=10)
        assert capped.endswith("…")
        assert len(capped.encode("utf-8")) <= 10

    def test_cap_message_never_splits_multibyte_char(self):
        # Each "€" is 3 UTF-8 bytes; a naive byte-slice at an odd budget would
        # cut mid-character and raise/produce a mangled tail.
        text = "€" * 10
        capped = NtfyChannel._cap_message(text, limit=7)
        # Must decode cleanly (no exception) and respect the byte budget.
        assert len(capped.encode("utf-8")) <= 7
        assert capped.endswith("…")

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_long_params_are_capped_in_sent_message(self, mock_post):
        mock_post.return_value = _ok_response()
        channel = NtfyChannel(topic="alerts")
        huge_params = '{"threshold": ' + "9" * 5000 + "}"
        channel.send(_anomaly_alert(detector_params=huge_params))
        message = mock_post.call_args.kwargs["json"]["message"]
        assert len(message.encode("utf-8")) <= 3800
        assert message.endswith("…")


class TestNtfyTransportFailure:
    """A transport-level failure returns False instead of raising."""

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_request_exception_returns_false(self, mock_post):
        mock_post.side_effect = requests.RequestException("Connection error")
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_anomaly_alert()) is False

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_http_error_returns_false(self, mock_post):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("500")
        mock_post.return_value = response
        channel = NtfyChannel(topic="alerts")
        assert channel.send(_anomaly_alert()) is False

    @patch("detectkit.alerting.channels.ntfy.requests.post")
    def test_transport_failure_does_not_raise(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("boom")
        channel = NtfyChannel(topic="alerts")
        # Must not propagate — the pipeline catches per-channel failures via
        # the boolean return, not exceptions.
        result = channel.send(_anomaly_alert())
        assert result is False
