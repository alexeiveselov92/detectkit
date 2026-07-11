"""Tests for the Microsoft Teams alert channel (Power Automate Workflows webhook)."""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
import requests

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.teams import TeamsChannel


def _alert(**overrides: object) -> AlertData:
    base: dict[str, object] = {
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
    }
    base.update(overrides)
    return AlertData(**base)  # type: ignore[arg-type]


def _timed_anomaly(**overrides: object) -> AlertData:
    """An anomaly alert with full incident-timing fields wired in, so
    "Anomaly began" / "Alert fired" facts are populated."""
    base: dict[str, object] = {
        "interval_seconds": 600,
        "onset_timestamp": datetime(2024, 1, 1, 11, 30, 0),
        "consecutive_count": 4,
        "consecutive_required": 4,
        "min_detectors": 1,
        "detector_count": 1,
        "direction_policy": "same",
    }
    base.update(overrides)
    return _alert(**base)


class TestInit:
    def test_missing_webhook_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="webhook_url is required"):
            TeamsChannel(webhook_url="")

    def test_unexpected_param_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            TeamsChannel(webhook_url="https://example.com/hook", extra_thing="nope")  # type: ignore[call-arg]

    def test_defaults(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        assert channel.webhook_url == "https://example.com/hook"
        assert channel.timeout == 10

    def test_repr(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hooks/very_long_workflow_url_xxx")
        assert "TeamsChannel" in repr(channel)


class TestPayloadEnvelope:
    """The outer POST body must match the Workflows Adaptive Card contract."""

    def test_build_card_has_adaptive_card_shape(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        card = channel.build_card(_alert())
        assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
        assert card["type"] == "AdaptiveCard"
        assert card["version"] == "1.4"
        assert card["msteams"] == {"width": "Full"}
        assert isinstance(card["body"], list)

    @patch("detectkit.alerting.channels.teams.requests.post")
    def test_send_posts_message_envelope_with_adaptive_attachment(self, mock_post: Mock) -> None:
        mock_post.return_value = Mock(status_code=200, raise_for_status=Mock())
        channel = TeamsChannel(webhook_url="https://example.com/hook")

        success = channel.send(_alert())

        assert success is True
        assert mock_post.called
        payload = mock_post.call_args.kwargs["json"]
        assert payload["type"] == "message"
        assert len(payload["attachments"]) == 1
        attachment = payload["attachments"][0]
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachment["contentUrl"] is None
        assert attachment["content"]["type"] == "AdaptiveCard"
        # url + timeout wiring
        assert mock_post.call_args.args[0] == "https://example.com/hook"
        assert mock_post.call_args.kwargs["timeout"] == 10


class TestAnomalyBody:
    def _card(self, alert: AlertData | None = None) -> dict:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        return channel.build_card(alert if alert is not None else _alert())

    def test_title_block_is_colored_attention(self) -> None:
        body = self._card()["body"]
        title_block = body[0]
        assert title_block["type"] == "TextBlock"
        assert "cpu_usage" in title_block["text"]
        assert title_block["weight"] == "Bolder"
        assert title_block["size"] == "Medium"
        assert title_block["color"] == "Attention"
        assert title_block["wrap"] is True

    def test_rule_block_is_monospace(self) -> None:
        body = self._card()["body"]
        rule_block = body[2]
        assert rule_block["text"].startswith("Rule: ")
        assert rule_block["fontType"] == "Monospace"
        assert rule_block["spacing"] == "Small"
        assert rule_block["wrap"] is True

    def test_fact_set_has_value_expected_quorum_severity_detected_detectors(self) -> None:
        body = self._card()["body"]
        fact_set = body[3]
        assert fact_set["type"] == "FactSet"
        titles = [f["title"] for f in fact_set["facts"]]
        assert titles == ["Value", "Expected", "Quorum", "Severity", "Detected at", "Detectors"]
        values = {f["title"]: f["value"] for f in fact_set["facts"]}
        assert values["Value"] == "95.0"
        assert values["Quorum"] == "1/1 · above"
        assert values["Severity"] == "2.50"

    def test_fact_set_uses_began_and_latest_when_timing_known(self) -> None:
        body = self._card(_timed_anomaly())["body"]
        fact_set = body[3]
        titles = [f["title"] for f in fact_set["facts"]]
        assert "Anomaly began" in titles
        assert "Latest reading" in titles
        assert "Detected at" not in titles

    def test_params_block_present_and_monospace(self) -> None:
        alert = _alert(detector_params='{"threshold": 3.0}')
        body = self._card(alert)["body"]
        # title, lead, rule, facts, params, footer
        params_block = body[4]
        assert params_block["text"] == '{"threshold": 3.0}'
        assert params_block["fontType"] == "Monospace"
        assert params_block["isSubtle"] is True

    def test_params_block_absent_when_empty(self) -> None:
        alert = _alert(detector_params="")
        body = self._card(alert)["body"]
        # title, lead, rule, facts, footer — no params block
        assert len(body) == 5
        assert all(b.get("fontType") != "Monospace" or b is body[2] for b in body)

    def test_params_truncated_to_cap(self) -> None:
        long_params = "x" * 950
        alert = _alert(detector_params=long_params)
        body = self._card(alert)["body"]
        params_block = body[4]
        assert len(params_block["text"]) == 900
        assert params_block["text"].endswith("…")

    def test_footer_block_is_last_and_plain_without_project(self) -> None:
        body = self._card()["body"]
        footer = body[-1]
        assert footer["text"] == "detectkit"
        assert footer["isSubtle"] is True
        assert footer["size"] == "Small"
        assert footer["spacing"] == "Medium"

    def test_footer_pairs_with_project_name(self) -> None:
        alert = _alert(project_name="my_project")
        body = self._card(alert)["body"]
        assert body[-1]["text"] == "detectkit · my_project"

    def test_mentions_block_present_when_set(self) -> None:
        alert = _alert(mentions=["here", "oncall"])
        body = self._card(alert)["body"]
        mention_texts = [b["text"] for b in body if b.get("isSubtle") and "@" in b.get("text", "")]
        assert mention_texts
        assert "@here" in mention_texts[0]
        assert "@oncall" in mention_texts[0]

    def test_mentions_block_absent_when_unset(self) -> None:
        body = self._card(_alert())["body"]
        assert not any("@" in b.get("text", "") for b in body)


class TestRecoveryBody:
    def _card(self, **overrides: object) -> dict:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        alert = _alert(is_recovery=True, direction="none", **overrides)
        return channel.build_card(alert)

    def test_title_is_colored_good(self) -> None:
        body = self._card()["body"]
        assert body[0]["color"] == "Good"

    def test_facts_use_cleared_at_when_timing_unknown(self) -> None:
        fact_set = self._card()["body"][3]
        titles = [f["title"] for f in fact_set["facts"]]
        assert "Cleared at" in titles
        assert "Anomaly began" not in titles
        assert "Alert fired" not in titles

    def test_facts_show_full_timeline_when_timing_known(self) -> None:
        timed = _timed_anomaly(is_recovery=True, direction="none")
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        fact_set = channel.build_card(timed)["body"][3]
        titles = [f["title"] for f in fact_set["facts"]]
        assert (
            titles.index("Anomaly began") < titles.index("Alert fired") < titles.index("Recovered")
        )

    def test_no_params_block_for_recovery(self) -> None:
        body = self._card(detector_params='{"threshold": 3.0}')["body"]
        assert not any(b.get("fontType") == "Monospace" and b.get("isSubtle") for b in body)


class TestNoDataBody:
    def _card(self) -> dict:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        alert = _alert(is_no_data=True, value=None)
        return channel.build_card(alert)

    def test_title_is_colored_warning(self) -> None:
        assert self._card()["body"][0]["color"] == "Warning"

    def test_short_body_no_quorum_severity_or_params(self) -> None:
        body = self._card()["body"]
        # title, lead, facts, footer — no Rule chip (no-data doesn't fire on
        # the quorum rule)
        assert len(body) == 4
        assert not any("Rule:" in str(block.get("text", "")) for block in body)
        fact_set = body[2]
        titles = [f["title"] for f in fact_set["facts"]]
        assert titles == ["Expected at", "Expected"]

    def test_lead_text(self) -> None:
        lead = self._card()["body"][1]["text"]
        assert "no datapoint" in lead


class TestErrorBody:
    def _card(self) -> dict:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        alert = _alert(is_error=True, error_type="DBError", error_message="connection refused")
        return channel.build_card(alert)

    def test_title_is_colored_accent(self) -> None:
        assert self._card()["body"][0]["color"] == "Accent"

    def test_short_body_with_detected_and_error_facts(self) -> None:
        body = self._card()["body"]
        # title, lead, facts, footer — no Rule chip (error doesn't fire on
        # the quorum rule)
        assert len(body) == 4
        fact_set = body[2]
        values = {f["title"]: f["value"] for f in fact_set["facts"]}
        assert values["Error"] == "DBError: connection refused"
        assert "Detected at" in values


class TestCustomTemplate:
    def test_custom_template_renders_minimal_card(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        card = channel.build_card(_alert(), template="CUSTOM: {metric_name} = {value}")
        body = card["body"]
        assert len(body) == 3
        assert "cpu_usage" in body[0]["text"]
        assert body[0]["color"] == "Attention"
        assert body[1]["text"] == "CUSTOM: cpu_usage = 95.0"
        assert body[1]["wrap"] is True
        assert body[2]["text"] == "detectkit"

    def test_custom_template_keeps_actions(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        alert = _alert(dashboard_url="https://grafana.example/d/abc")
        card = channel.build_card(alert, template="CUSTOM: {metric_name}")
        assert card["actions"] == [
            {"type": "Action.OpenUrl", "title": "Dashboard", "url": "https://grafana.example/d/abc"}
        ]


class TestActions:
    def test_no_actions_key_when_no_links(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        card = channel.build_card(_alert())
        assert "actions" not in card

    def test_dashboard_extra_links_and_help_in_order(self) -> None:
        channel = TeamsChannel(webhook_url="https://example.com/hook")
        alert = _alert(
            dashboard_url="https://grafana.example/d/abc",
            links={"Runbook": "https://runbook.example"},
            help_url="https://docs.example/reading-alerts",
        )
        card = channel.build_card(alert)
        actions = card["actions"]
        assert actions == [
            {
                "type": "Action.OpenUrl",
                "title": "Dashboard",
                "url": "https://grafana.example/d/abc",
            },
            {"type": "Action.OpenUrl", "title": "Runbook", "url": "https://runbook.example"},
            {
                "type": "Action.OpenUrl",
                "title": "How to read this alert",
                "url": "https://docs.example/reading-alerts",
            },
        ]


class TestTransportFailure:
    @patch("detectkit.alerting.channels.teams.requests.post")
    def test_request_exception_returns_false(self, mock_post: Mock) -> None:
        mock_post.side_effect = requests.RequestException("Connection error")
        channel = TeamsChannel(webhook_url="https://example.com/hook")

        success = channel.send(_alert())

        assert success is False

    @patch("detectkit.alerting.channels.teams.requests.post")
    def test_http_error_returns_false(self, mock_post: Mock) -> None:
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404")
        mock_post.return_value = mock_response
        channel = TeamsChannel(webhook_url="https://example.com/hook")

        success = channel.send(_alert())

        assert success is False
