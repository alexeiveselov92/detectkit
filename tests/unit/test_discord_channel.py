"""Tests for the Discord incoming-webhook alert channel."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import requests

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME
from detectkit.alerting.channels.discord import DiscordChannel


def _alert(**overrides: object) -> AlertData:
    """A base anomaly ``AlertData``; kwargs override/extend fields."""
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
        "consecutive_count": 3,
        "min_detectors": 1,
        "direction_policy": "same",
        "consecutive_required": 3,
        "detector_count": 1,
        "interval_seconds": 600,
        "onset_timestamp": datetime(2024, 1, 1, 11, 30, 0),
    }
    base.update(overrides)
    return AlertData(**base)  # type: ignore[arg-type]


def _channel(**overrides: object) -> DiscordChannel:
    return DiscordChannel(
        webhook_url="https://discord.com/api/webhooks/1/abc",  # type: ignore[arg-type]
        **overrides,  # type: ignore[arg-type]
    )


class TestInit:
    def test_missing_webhook_url_raises(self) -> None:
        with pytest.raises(ValueError):
            DiscordChannel(webhook_url="")

    def test_defaults_to_brand_identity(self) -> None:
        channel = _channel()
        assert channel.username == BRAND_USERNAME
        assert channel.avatar_url == BRAND_ICON_URL

    def test_custom_avatar_url_overrides_brand(self) -> None:
        channel = _channel(avatar_url="https://example.com/a.png")
        assert channel.avatar_url == "https://example.com/a.png"

    def test_unknown_param_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            DiscordChannel(webhook_url="https://x", bogus="y")  # type: ignore[call-arg]


class TestSendPayloadShape:
    """One embed per alert; payload shape across all four alert kinds."""

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_anomaly_payload_shape(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        assert channel.send(_alert()) is True

        payload = mock_post.call_args.kwargs["json"]
        assert payload["username"] == BRAND_USERNAME
        assert payload["avatar_url"] == BRAND_ICON_URL
        assert len(payload["embeds"]) == 1

        embed = payload["embeds"][0]
        assert embed["color"] == 0xD63232
        assert embed["title"].startswith("\U0001f534")
        assert "Rule" in embed["description"]
        assert "Value" in embed["description"]
        assert "Expected" in embed["description"]

        field_names = [f["name"] for f in embed["fields"]]
        assert "Quorum" in field_names
        assert "Severity" in field_names
        assert "Detectors" in field_names
        assert "Anomaly began" in field_names
        assert "Latest reading" in field_names
        assert all(f["inline"] is True for f in embed["fields"])
        assert "content" not in payload
        assert "allowed_mentions" not in payload

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_recovery_payload_shape(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        assert channel.send(_alert(is_recovery=True)) is True

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["color"] == 0x36A64F
        field_names = [f["name"] for f in embed["fields"]]
        assert "Anomaly began" in field_names
        assert "Recovered" in field_names
        assert "Detectors" in field_names

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_recovery_omits_fired_field_when_unknown(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        # No onset/interval wired in -> started_display is empty -> "Cleared at" branch.
        alert = _alert(is_recovery=True, onset_timestamp=None, interval_seconds=None)
        channel.send(alert)

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        field_names = [f["name"] for f in embed["fields"]]
        assert "Cleared at" in field_names
        assert "Alert fired" not in field_names

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_no_data_payload_shape(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        assert channel.send(_alert(is_no_data=True, value=None)) is True

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["color"] == 0xF0AD4E
        assert "no datapoint" in embed["description"]
        assert "fields" not in embed  # no verbose tail for no-data

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_error_payload_shape(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        alert = _alert(is_error=True, error_type="DBError", error_message="connection refused")
        assert channel.send(alert) is True

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["color"] == 0x5A7A8C
        assert "pipeline failed" in embed["description"]
        assert "DBError" in embed["description"]
        assert "fields" not in embed  # no verbose tail for error

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_dashboard_url_sets_embed_url_and_link(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        alert = _alert(dashboard_url="https://grafana.example/d/abc")
        channel.send(alert)

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["url"] == "https://grafana.example/d/abc"
        assert "[Dashboard](https://grafana.example/d/abc)" in embed["description"]

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_dashboard_extra_links_and_help_in_order(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        alert = _alert(
            dashboard_url="https://grafana.example/d/abc",
            links={"Runbook": "https://runbook.example"},
            help_url="https://docs.example/reading-alerts",
        )
        channel.send(alert)

        description = mock_post.call_args.kwargs["json"]["embeds"][0]["description"]
        dash = description.index("[Dashboard](https://grafana.example/d/abc)")
        runbook = description.index("[Runbook](https://runbook.example)")
        help_link = description.index(
            "[How to read this alert](https://docs.example/reading-alerts)"
        )
        assert dash < runbook < help_link

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_footer_carries_brand_and_project(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert(project_name="my_project"))

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["footer"]["text"] == f"{BRAND_USERNAME} · my_project"
        assert embed["footer"]["icon_url"] == BRAND_ICON_URL

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_timestamp_is_iso_utc(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert())

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["timestamp"] == "2024-01-01T12:00:00Z"


class TestCustomTemplate:
    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_custom_template_renders_as_description_no_fields(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        alert = _alert()
        assert channel.send(alert, template="CUSTOM: {metric_name} = {value}") is True

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert embed["description"] == "CUSTOM: cpu_usage = 95.0"
        assert "fields" not in embed
        assert embed["color"] == 0xD63232
        assert "footer" in embed

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_custom_template_description_truncated_at_4096(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        template = "{metric_name}: " + ("x" * 5000)
        channel.send(_alert(), template=template)

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert len(embed["description"]) == 4096
        assert embed["description"].endswith("…")


class TestMentions:
    @pytest.mark.parametrize(
        "mention,expected",
        [
            ("all", "@everyone"),
            ("everyone", "@everyone"),
            ("channel", "@everyone"),
            ("here", "@here"),
            ("<@123456789>", "<@123456789>"),
            ("<@&987654321>", "<@&987654321>"),
            ("oncall", "@oncall"),
        ],
    )
    def test_format_mentions_mapping(self, mention: str, expected: str) -> None:
        assert _channel().format_mentions([mention]) == expected

    def test_no_mentions_returns_empty_string(self) -> None:
        assert _channel().format_mentions([]) == ""

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_mentions_ride_in_content_with_allowed_mentions(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert(mentions=["here", "oncall"]))

        payload = mock_post.call_args.kwargs["json"]
        assert payload["content"] == "@here @oncall"
        assert payload["allowed_mentions"] == {"parse": ["everyone", "users", "roles"]}
        # Mentions never ride inside the embed (they wouldn't ping there).
        assert "@here" not in payload["embeds"][0]["description"]

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_no_mentions_omits_content_and_allowed_mentions(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert())

        payload = mock_post.call_args.kwargs["json"]
        assert "content" not in payload
        assert "allowed_mentions" not in payload


class TestTruncation:
    def test_cap_leaves_short_values_untouched(self) -> None:
        assert DiscordChannel._cap("short", 100) == "short"

    def test_cap_truncates_with_ellipsis(self) -> None:
        capped = DiscordChannel._cap("x" * 50, 10)
        assert len(capped) == 10
        assert capped.endswith("…")

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_title_capped_at_256(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert(metric_name="m" * 500))

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert len(embed["title"]) == 256

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_detector_params_capped_and_fenced(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        big_params = '{"threshold": 3.0, "note": "' + ("a" * 2000) + '"}'
        channel.send(_alert(detector_params=big_params))

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        assert "```" in embed["description"]
        assert len(embed["description"]) <= 4096

    def test_detector_params_dropped_when_over_budget(self) -> None:
        # Direct unit test of the drop-not-truncate rule: an already-huge
        # description must not gain a truncated/mangled fenced params block.
        channel = _channel()
        ctx = {"detector_params": '{"threshold": 3.0}'}
        huge_description = "d" * 3500
        result = channel._append_params(huge_description, ctx, "anomaly")
        assert result == huge_description
        assert "```" not in result

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_field_value_capped_at_1024(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = _channel()
        channel.send(_alert(detector_name="d" * 2000))

        embed = mock_post.call_args.kwargs["json"]["embeds"][0]
        detectors_field = next(f for f in embed["fields"] if f["name"] == "Detectors")
        assert len(detectors_field["value"]) == 1024


class TestTransportFailure:
    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_request_exception_returns_false(self, mock_post: Mock) -> None:
        mock_post.side_effect = requests.RequestException("boom")
        channel = _channel()
        assert channel.send(_alert()) is False

    @patch("detectkit.alerting.channels.discord.requests.post")
    def test_http_error_status_returns_false(self, mock_post: Mock) -> None:
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")
        mock_post.return_value = response
        channel = _channel()
        assert channel.send(_alert()) is False


class TestRepr:
    def test_repr_contains_class_name(self) -> None:
        assert "DiscordChannel" in repr(_channel())
