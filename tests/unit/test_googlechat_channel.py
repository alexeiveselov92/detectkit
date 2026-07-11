"""Tests for GoogleChatChannel (Cards v2 space incoming webhook).

Reuses the ``AlertData`` fixture style from ``test_webhook_formats.py`` /
``test_channel_send_contract.py``.
"""

import html
from unittest.mock import Mock, patch

import numpy as np
import pytest
import requests

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.branding import BRAND_ICON_URL, BRAND_USERNAME
from detectkit.alerting.channels.googlechat import GoogleChatChannel


def make_alert_data(**overrides):
    base = {
        "metric_name": "m",
        "timestamp": np.datetime64("2024-01-01T12:00:00"),
        "timezone": "UTC",
        "value": 100.0,
        "confidence_lower": 80.0,
        "confidence_upper": 120.0,
        "detector_name": "mad",
        "detector_params": "{}",
        "direction": "up",
        "severity": 3.0,
        "detection_metadata": {},
        "consecutive_count": 1,
    }
    base.update(overrides)
    return AlertData(**base)


def widgets_of(section: dict) -> list[dict]:
    return section["widgets"]


def find_widget(sections: list[dict], key: str) -> list[dict]:
    """All widgets of *key* type (e.g. "decoratedText") across every section."""
    found = []
    for section in sections:
        for widget in widgets_of(section):
            if key in widget:
                found.append(widget[key])
    return found


class TestConstruction:
    def test_missing_webhook_url_raises_value_error(self):
        with pytest.raises(ValueError, match="webhook_url is required"):
            GoogleChatChannel(webhook_url="")

    def test_none_webhook_url_raises_value_error(self):
        with pytest.raises(ValueError, match="webhook_url is required"):
            GoogleChatChannel(webhook_url=None)  # type: ignore[arg-type]

    def test_default_icon_url_is_brand_avatar(self):
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        assert channel.icon_url == BRAND_ICON_URL

    def test_explicit_icon_url_overrides_default(self):
        channel = GoogleChatChannel(
            webhook_url="https://chat.googleapis.com/v1/spaces/x",
            icon_url="https://example.com/custom.png",
        )
        assert channel.icon_url == "https://example.com/custom.png"

    def test_default_timeout(self):
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        assert channel.timeout == 10

    def test_unknown_kwarg_raises_type_error(self):
        with pytest.raises(TypeError):
            GoogleChatChannel(  # type: ignore[call-arg]
                webhook_url="https://chat.googleapis.com/v1/spaces/x",
                bogus="nope",
            )


class TestPayloadShape:
    def _channel(self, **kwargs):
        return GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x", **kwargs)

    def test_top_level_shape(self):
        payload = self._channel().build_payload(make_alert_data())
        assert list(payload["cardsV2"]) and len(payload["cardsV2"]) == 1
        entry = payload["cardsV2"][0]
        assert entry["cardId"] == "detectkit-alert"
        assert "card" in entry
        assert "text" not in payload  # no mentions -> no top-level text

    def test_header_fields(self):
        card = self._channel().build_card(make_alert_data())
        header = card["header"]
        assert header["title"].startswith("\U0001f534")  # red circle: anomaly
        assert "m" in header["title"]
        assert header["subtitle"] == BRAND_USERNAME
        assert header["imageUrl"] == BRAND_ICON_URL
        assert header["imageType"] == "CIRCLE"

    def test_header_subtitle_includes_project_name(self):
        card = self._channel().build_card(make_alert_data(project_name="acme"))
        assert card["header"]["subtitle"] == f"{BRAND_USERNAME} · acme"

    def test_header_omits_image_fields_when_icon_url_empty(self):
        channel = self._channel(icon_url="")
        header = channel.build_card(make_alert_data())["header"]
        assert "imageUrl" not in header
        assert "imageType" not in header

    def test_anomaly_evidence_rows(self):
        card = self._channel().build_card(make_alert_data())
        sections = card["sections"]
        decorated = find_widget(sections, "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert labels == [
            "Value",
            "Expected",
            "Quorum",
            "Severity",
            "Detected at",
            "Detectors",
        ]

    def test_anomaly_with_onset_shows_began_and_latest(self):
        alert = make_alert_data(
            onset_timestamp=np.datetime64("2024-01-01T10:00:00"),
            interval_seconds=600,
            consecutive_count=3,
        )
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert "Anomaly began" in labels
        assert "Latest reading" in labels
        assert "Detected at" not in labels

    def test_anomaly_lead_and_rule_text_paragraph(self):
        alert = make_alert_data(min_detectors=2, direction_policy="same", consecutive_required=3)
        channel = self._channel()
        card = channel.build_card(alert)
        ctx = channel.build_context(alert)
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        lead_block = text_paragraphs[0]["text"]
        assert html.escape(ctx["anomaly_lead"]) in lead_block
        assert "<b>Rule</b>" in lead_block
        assert html.escape(ctx["rule_display"]) in lead_block
        assert "<br>" in lead_block

    def test_anomaly_params_paragraph_present_when_set(self):
        alert = make_alert_data(detector_params='{"threshold": 3.0}')
        card = self._channel().build_card(alert)
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        assert any("threshold" in tp["text"] for tp in text_paragraphs)

    def test_anomaly_params_paragraph_absent_when_empty(self):
        alert = make_alert_data(detector_params="")
        card = self._channel().build_card(alert)
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        # Only the lead/rule paragraph remains.
        assert len(text_paragraphs) == 1

    def test_recovery_evidence_rows_without_onset(self):
        alert = make_alert_data(is_recovery=True)
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert labels == ["Value", "Expected", "Cleared at", "Detectors"]

    def test_recovery_evidence_rows_with_full_timeline(self):
        alert = make_alert_data(
            is_recovery=True,
            onset_timestamp=np.datetime64("2024-01-01T09:00:00"),
            interval_seconds=600,
            consecutive_count=3,
            consecutive_required=3,
            streak_capped=False,
        )
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert "Anomaly began" in labels
        assert "Alert fired" in labels
        assert "Recovered" in labels

    def test_no_data_evidence_rows(self):
        alert = make_alert_data(
            is_no_data=True, value=None, confidence_lower=None, confidence_upper=None
        )
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert labels == ["Expected at", "Expected"]
        # No quorum/severity/params for no-data — and no Rule chip either
        # (no-data doesn't fire on the quorum rule).
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        assert len(text_paragraphs) == 1  # the lead only
        assert "Rule" not in text_paragraphs[0]["text"]

    def test_error_evidence_rows(self):
        alert = make_alert_data(
            is_error=True,
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            error_type="DBError",
            error_message="connection refused",
        )
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert labels == ["Detected at", "Error"]
        error_row = next(d for d in decorated if d["topLabel"] == "Error")
        assert error_row["text"] == "DBError: connection refused"

    def test_error_row_omitted_when_error_fields_empty(self):
        alert = make_alert_data(
            is_error=True, value=None, confidence_lower=None, confidence_upper=None
        )
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        labels = [d["topLabel"] for d in decorated]
        assert labels == ["Detected at"]

    def test_buttons_dashboard_links_and_help(self):
        alert = make_alert_data(
            dashboard_url="https://grafana.example/d/abc",
            links={"Runbook": "https://runbook.example"},
            help_url="https://docs.example/reading-alerts",
        )
        channel = self._channel()
        card = channel.build_card(alert)
        button_lists = find_widget(card["sections"], "buttonList")
        assert len(button_lists) == 1
        buttons = button_lists[0]["buttons"]
        texts = [b["text"] for b in buttons]
        urls = [b["onClick"]["openLink"]["url"] for b in buttons]
        assert texts == ["Dashboard", "Runbook", "How to read this alert"]
        assert urls == [
            "https://grafana.example/d/abc",
            "https://runbook.example",
            "https://docs.example/reading-alerts",
        ]

    def test_no_button_section_when_no_links(self):
        card = self._channel().build_card(make_alert_data())
        assert find_widget(card["sections"], "buttonList") == []

    def test_html_escaping_of_metric_name_in_evidence(self):
        alert = make_alert_data(detector_name="<script>alert(1)</script>")
        card = self._channel().build_card(alert)
        decorated = find_widget(card["sections"], "decoratedText")
        detectors_row = next(d for d in decorated if d["topLabel"] == "Detectors")
        assert "<script>" not in detectors_row["text"]
        assert "&lt;script&gt;" in detectors_row["text"]

    def test_button_label_is_not_escaped(self):
        # Button text is plain text (the HTML subset applies to text widgets
        # only) — an escaped label would display the entities literally.
        alert = make_alert_data(links={"R&D runbook": "https://x.example"})
        card = self._channel().build_card(alert)
        buttons = find_widget(card["sections"], "buttonList")[0]["buttons"]
        assert buttons[0]["text"] == "R&D runbook"


class TestCustomTemplate:
    def _channel(self):
        return GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")

    def test_custom_template_renders_single_text_paragraph_section(self):
        channel = self._channel()
        alert = make_alert_data()
        card = channel.build_card(alert, template="CUSTOM {metric_name} = {value}")
        assert len(card["sections"]) == 1
        widgets = card["sections"][0]["widgets"]
        assert len(widgets) == 1
        assert "textParagraph" in widgets[0]
        assert "CUSTOM m = 100.0" in widgets[0]["textParagraph"]["text"]

    def test_custom_template_header_unchanged(self):
        channel = self._channel()
        alert = make_alert_data()
        card = channel.build_card(alert, template="CUSTOM {metric_name}")
        header = card["header"]
        assert header["subtitle"] == BRAND_USERNAME
        assert header["imageUrl"] == BRAND_ICON_URL

    def test_custom_template_escapes_html_and_converts_newlines(self):
        channel = self._channel()
        alert = make_alert_data()
        card = channel.build_card(alert, template="line1\nline2 <b>bold</b> {metric_name}")
        text = card["sections"][0]["widgets"][0]["textParagraph"]["text"]
        assert "line1<br>line2" in text
        assert "&lt;b&gt;bold&lt;/b&gt;" in text

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_send_with_template_posts_the_template_payload(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = self._channel()
        alert = make_alert_data()
        assert channel.send(alert, template="CUSTOM {metric_name}") is True
        payload = mock_post.call_args.kwargs["json"]
        assert payload == channel.build_payload(alert, template="CUSTOM {metric_name}")


class TestMentions:
    def _channel(self):
        return GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")

    @pytest.mark.parametrize("keyword", ["all", "everyone", "channel", "here", "ALL", "Here"])
    def test_broadcast_keywords_map_to_users_all(self, keyword):
        assert self._channel().format_mentions([keyword]) == "<users/all>"

    def test_multiple_broadcast_keywords_dedup_to_one_token(self):
        assert self._channel().format_mentions(["all", "channel", "here"]) == "<users/all>"

    def test_already_shaped_user_token_passes_through_verbatim(self):
        assert self._channel().format_mentions(["<users/12345>"]) == "<users/12345>"

    def test_duplicate_shaped_tokens_are_deduped(self):
        assert (
            self._channel().format_mentions(["<users/12345>", "<users/12345>"]) == "<users/12345>"
        )

    def test_plain_name_becomes_at_mention(self):
        assert self._channel().format_mentions(["oncall"]) == "@oncall"

    def test_mixed_mentions_join_with_space_preserving_order(self):
        result = self._channel().format_mentions(["oncall", "<users/999>", "all"])
        assert result == "@oncall <users/999> <users/all>"

    def test_empty_mentions_is_empty_string(self):
        assert self._channel().format_mentions([]) == ""

    def test_payload_has_no_top_level_text_without_mentions(self):
        payload = self._channel().build_payload(make_alert_data())
        assert "text" not in payload

    def test_payload_top_level_text_present_with_mentions(self):
        alert = make_alert_data(mentions=["oncall"])
        payload = self._channel().build_payload(alert)
        assert payload["text"] == "@oncall"


class TestTruncation:
    def _channel(self):
        return GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")

    def test_params_capped_at_900_chars(self):
        long_params = '{"threshold": ' + "9" * 1000 + "}"
        alert = make_alert_data(detector_params=long_params)
        channel = self._channel()
        card = channel.build_card(alert)
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        params_paragraph = next(tp for tp in text_paragraphs if "Parameters" in tp["text"])
        # The cap applies to the RAW params string (pre-escape), so an
        # escaped/expanded body can be longer than 900 — assert against the
        # same cap helper the channel uses, and that truncation actually
        # happened (ellipsis present).
        assert len(channel._cap(long_params, 900)) == 900
        assert "…" in params_paragraph["text"]

    def test_short_params_not_truncated(self):
        alert = make_alert_data(detector_params='{"threshold": 3.0}')
        card = self._channel().build_card(alert)
        text_paragraphs = find_widget(card["sections"], "textParagraph")
        params_paragraph = next(tp for tp in text_paragraphs if "Parameters" in tp["text"])
        assert "…" not in params_paragraph["text"]

    def test_cap_helper_truncates_with_ellipsis(self):
        channel = self._channel()
        capped = channel._cap("x" * 1000, 900)
        assert len(capped) == 900
        assert capped.endswith("…")

    def test_cap_helper_leaves_short_values_untouched(self):
        channel = self._channel()
        assert channel._cap("short", 900) == "short"


class TestTransportFailure:
    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_request_exception_returns_false(self, mock_post):
        mock_post.side_effect = requests.RequestException("boom")
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        assert channel.send(make_alert_data()) is False

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_http_error_status_returns_false(self, mock_post):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("500 error")
        mock_post.return_value = response
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        assert channel.send(make_alert_data()) is False

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_success_returns_true(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        assert channel.send(make_alert_data()) is True

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_does_not_raise_on_transport_error(self, mock_post):
        """Unlike telegram.py, GoogleChatChannel must swallow the transport
        error and return False rather than re-raising (matches webhook.py)."""
        mock_post.side_effect = requests.RequestException("boom")
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        try:
            result = channel.send(make_alert_data())
        except requests.RequestException:
            pytest.fail("send() must not re-raise RequestException")
        assert result is False


class TestSendContract:
    """Mirrors test_channel_send_contract.py's per-channel checks."""

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_send_posts_to_webhook_url_as_json(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        alert = make_alert_data()
        assert channel.send(alert) is True
        assert mock_post.call_args.args[0] == "https://chat.googleapis.com/v1/spaces/x"
        assert mock_post.call_args.kwargs["json"] == channel.build_payload(alert)
        assert mock_post.call_args.kwargs["timeout"] == 10

    @patch("detectkit.alerting.channels.googlechat.requests.post")
    def test_dispatch_records_success(self, mock_post):
        from detectkit.alerting.orchestrator._dispatch import _DispatchMixin

        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = GoogleChatChannel(webhook_url="https://chat.googleapis.com/v1/spaces/x")
        results = _DispatchMixin._dispatch([channel], make_alert_data(), None, "alert")
        assert results == {"GoogleChatChannel": True}
