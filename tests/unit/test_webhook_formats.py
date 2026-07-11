"""Tests for WebhookChannel's ``format``/``secret`` knobs: the "json" and
"alertmanager" structured payloads and HMAC request signing. The default
"attachments" format must stay byte-identical to :meth:`build_payload`.

Reuses the ``AlertData`` fixture style from ``test_channel_send_contract.py``.
"""

import hashlib
import hmac
import json
from unittest.mock import Mock, patch

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.webhook import WebhookChannel


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


class TestConstruction:
    def test_bad_format_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown webhook format"):
            WebhookChannel(webhook_url="https://x", format="bogus")

    def test_bad_format_error_lists_allowed_values(self):
        with pytest.raises(ValueError) as exc_info:
            WebhookChannel(webhook_url="https://x", format="bogus")
        message = str(exc_info.value)
        assert "attachments" in message
        assert "json" in message
        assert "alertmanager" in message

    def test_default_format_is_attachments(self):
        assert WebhookChannel(webhook_url="https://x").format == "attachments"

    def test_default_secret_is_none(self):
        assert WebhookChannel(webhook_url="https://x").secret is None

    def test_explicit_format_and_secret_stick(self):
        channel = WebhookChannel(webhook_url="https://x", format="json", secret="s3cret")
        assert channel.format == "json"
        assert channel.secret == "s3cret"


class TestAttachmentsFormatUnchanged:
    """The default format's posted body must round-trip to exactly the
    existing ``build_payload`` dict — a pure serialization-path change."""

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_body_round_trips_to_build_payload(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://x")
        alert = make_alert_data()
        assert channel.send(alert) is True
        body = mock_post.call_args.kwargs["data"]
        assert isinstance(body, bytes)
        assert json.loads(body) == channel.build_payload(alert)

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_no_event_header(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        WebhookChannel(webhook_url="https://x").send(make_alert_data())
        assert "X-Detectkit-Event" not in mock_post.call_args.kwargs["headers"]

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_no_signature_header_without_secret(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        WebhookChannel(webhook_url="https://x").send(make_alert_data())
        assert "X-Detectkit-Signature-256" not in mock_post.call_args.kwargs["headers"]


class TestJsonFormat:
    def _channel(self, **kwargs):
        return WebhookChannel(webhook_url="https://x", format="json", **kwargs)

    def test_anomaly_shape(self):
        payload = self._channel().build_event_payload(make_alert_data())
        assert payload["schema_version"] == 1
        assert payload["source"] == "detectkit"
        assert payload["kind"] == "anomaly"
        assert payload["status"] == "firing"
        assert payload["metric"] == "m"
        assert payload["timestamp"] == "2024-01-01T12:00:00Z"
        assert payload["value"] == 100.0
        assert payload["expected"] == {"lower": 80.0, "upper": 120.0}
        assert payload["detector"]["name"] == "mad"
        assert payload["error"] is None

    def test_recovery_status_is_resolved(self):
        payload = self._channel().build_event_payload(make_alert_data(is_recovery=True))
        assert payload["kind"] == "recovery"
        assert payload["status"] == "resolved"

    def test_no_data_kind_and_lead(self):
        alert = make_alert_data(
            is_no_data=True, value=None, confidence_lower=None, confidence_upper=None
        )
        payload = self._channel().build_event_payload(alert)
        assert payload["kind"] == "no_data"
        assert (
            payload["display"]["lead"]
            == "Query returned no datapoint for the latest expected interval."
        )
        assert payload["value"] is None
        assert payload["expected"] == {"lower": None, "upper": None}

    def test_error_kind_carries_error_object_and_lead(self):
        alert = make_alert_data(
            is_error=True,
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            error_type="DBError",
            error_message="connection refused",
        )
        payload = self._channel().build_event_payload(alert)
        assert payload["kind"] == "error"
        assert payload["error"] == {"type": "DBError", "message": "connection refused"}
        assert payload["display"]["lead"] == "The detectkit pipeline failed for this metric."

    def test_detector_params_parsed_from_json_object(self):
        alert = make_alert_data(detector_params='{"threshold": 3.0}')
        payload = self._channel().build_event_payload(alert)
        assert payload["detector"]["params"] == {"threshold": 3.0}

    def test_detector_params_empty_string_is_null(self):
        alert = make_alert_data(detector_params="")
        payload = self._channel().build_event_payload(alert)
        assert payload["detector"]["params"] is None

    def test_detector_params_non_json_string_passed_through_raw(self):
        alert = make_alert_data(detector_params="not-json")
        payload = self._channel().build_event_payload(alert)
        assert payload["detector"]["params"] == "not-json"

    def test_rule_display_matches_the_same_chip_build_context_renders(self):
        alert = make_alert_data(
            min_detectors=2, direction_policy="same", consecutive_required=3, detector_count=2
        )
        channel = self._channel()
        payload = channel.build_event_payload(alert)
        ctx = channel.build_context(alert)
        assert payload["rule"]["display"] == ctx["rule_display"]
        assert payload["rule"]["min_detectors"] == ctx["min_detectors"] == 2
        assert payload["rule"]["direction"] == ctx["direction_policy"] == "same"
        assert payload["rule"]["consecutive"] == ctx["consecutive_required"] == 3
        assert payload["quorum"] == {"detector_count": 2, "min_detectors": 2}

    def test_expected_null_for_nan_bound(self):
        alert = make_alert_data(confidence_lower=float("nan"), confidence_upper=120.0)
        payload = self._channel().build_event_payload(alert)
        assert payload["expected"]["lower"] is None
        assert payload["expected"]["upper"] == 120.0

    def test_expected_null_for_inf_bound(self):
        alert = make_alert_data(confidence_lower=float("-inf"), confidence_upper=float("inf"))
        payload = self._channel().build_event_payload(alert)
        assert payload["expected"] == {"lower": None, "upper": None}

    def test_incident_onset_iso_timestamp_and_duration(self):
        alert = make_alert_data(
            onset_timestamp=np.datetime64("2024-01-01T10:00:00"),
            interval_seconds=600,
            consecutive_count=3,
        )
        payload = self._channel().build_event_payload(alert)
        assert payload["incident"]["onset"] == "2024-01-01T10:00:00Z"
        assert payload["incident"]["streak"] == 3
        assert payload["incident"]["duration_seconds"] == 1800

    def test_incident_duration_null_without_interval(self):
        alert = make_alert_data(onset_timestamp=np.datetime64("2024-01-01T10:00:00"))
        payload = self._channel().build_event_payload(alert)
        assert payload["incident"]["duration_seconds"] is None

    def test_links_and_mentions_and_synonyms(self):
        alert = make_alert_data(
            dashboard_url="https://grafana.example/d/abc",
            help_url="https://docs.example/reading-alerts",
            links={"Runbook": "https://runbook.example"},
            mentions=["oncall"],
            ai_synonyms=["orders_total"],
        )
        payload = self._channel().build_event_payload(alert)
        assert payload["links"]["dashboard"] == "https://grafana.example/d/abc"
        assert payload["links"]["help"] == "https://docs.example/reading-alerts"
        assert payload["links"]["extra"] == {"Runbook": "https://runbook.example"}
        assert payload["mentions"] == ["oncall"]
        assert payload["synonyms"] == ["orders_total"]

    def test_help_link_null_when_unset(self):
        payload = self._channel().build_event_payload(make_alert_data())
        assert payload["links"]["help"] is None

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_posts_the_event_payload(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = self._channel()
        alert = make_alert_data()
        assert channel.send(alert) is True
        body = json.loads(mock_post.call_args.kwargs["data"])
        assert body == channel.build_event_payload(alert)

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_ignores_custom_template(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = self._channel()
        channel.send(make_alert_data(), template="CUSTOM: {metric_name}")
        body = json.loads(mock_post.call_args.kwargs["data"])
        assert "CUSTOM" not in json.dumps(body)

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_event_header_matches_status_kind(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        self._channel().send(make_alert_data())
        assert mock_post.call_args.kwargs["headers"]["X-Detectkit-Event"] == "anomaly"


class TestAlertmanagerFormat:
    def _channel(self, **kwargs):
        return WebhookChannel(webhook_url="https://x", format="alertmanager", **kwargs)

    def test_top_level_shape(self):
        payload = self._channel().build_alertmanager_payload(make_alert_data())
        assert payload["version"] == "4"
        assert payload["status"] == "firing"
        assert payload["receiver"] == "detectkit"
        assert payload["groupLabels"] == {"alertname": "m"}
        assert payload["groupKey"] == "detectkit/default/m"
        assert len(payload["alerts"]) == 1

    def test_group_key_uses_project_name_when_set(self):
        payload = self._channel().build_alertmanager_payload(make_alert_data(project_name="acme"))
        assert payload["groupKey"] == "detectkit/acme/m"
        assert payload["commonLabels"]["project"] == "acme"

    def test_firing_alert_has_zero_time_ends_at(self):
        alert = self._channel().build_alertmanager_payload(make_alert_data())["alerts"][0]
        assert alert["status"] == "firing"
        assert alert["endsAt"] == "0001-01-01T00:00:00Z"

    def test_recovery_of_the_same_incident_shares_the_firing_fingerprint(self):
        channel = self._channel()
        firing = make_alert_data(direction="up")
        # The orchestrator stamps recovery AlertData with direction="none"
        # (_recovery.py) — the fingerprint must still pair with the firing
        # alert's, which is why direction is an annotation, never a label.
        recovery = make_alert_data(direction="none", is_recovery=True)
        firing_alert = channel.build_alertmanager_payload(firing)["alerts"][0]
        recovery_alert = channel.build_alertmanager_payload(recovery)["alerts"][0]

        assert firing_alert["fingerprint"] == recovery_alert["fingerprint"]
        assert recovery_alert["status"] == "resolved"
        assert recovery_alert["endsAt"] != "0001-01-01T00:00:00Z"
        assert recovery_alert["labels"]["kind"] == "anomaly"

    def test_same_labels_produce_the_same_fingerprint(self):
        channel = self._channel()
        a = channel.build_alertmanager_payload(make_alert_data())["alerts"][0]
        b = channel.build_alertmanager_payload(make_alert_data())["alerts"][0]
        assert a["fingerprint"] == b["fingerprint"]

    def test_different_metric_produces_a_different_fingerprint(self):
        channel = self._channel()
        a = channel.build_alertmanager_payload(make_alert_data(metric_name="m1"))["alerts"][0]
        b = channel.build_alertmanager_payload(make_alert_data(metric_name="m2"))["alerts"][0]
        assert a["fingerprint"] != b["fingerprint"]

    def test_severity_label_mapping(self):
        channel = self._channel()

        anomaly = channel.build_alertmanager_payload(make_alert_data())["alerts"][0]
        assert anomaly["labels"]["severity"] == "critical"

        recovery = channel.build_alertmanager_payload(make_alert_data(is_recovery=True))["alerts"][
            0
        ]
        assert recovery["labels"]["severity"] == "critical"

        no_data = channel.build_alertmanager_payload(
            make_alert_data(
                is_no_data=True, value=None, confidence_lower=None, confidence_upper=None
            )
        )["alerts"][0]
        assert no_data["labels"]["severity"] == "warning"

        error = channel.build_alertmanager_payload(
            make_alert_data(
                is_error=True,
                value=None,
                confidence_lower=None,
                confidence_upper=None,
                error_type="E",
                error_message="boom",
            )
        )["alerts"][0]
        assert error["labels"]["severity"] == "critical"

    def test_direction_is_an_annotation_never_a_label(self):
        channel = self._channel()
        anomaly = channel.build_alertmanager_payload(make_alert_data(direction="down"))["alerts"][0]
        assert "direction" not in anomaly["labels"]
        assert anomaly["annotations"]["direction"] == "down"

        # Recovery carries direction="none" — no direction annotation, and the
        # label set stays identical to the firing alert's.
        recovery = channel.build_alertmanager_payload(
            make_alert_data(direction="none", is_recovery=True)
        )["alerts"][0]
        assert "direction" not in recovery["labels"]
        assert "direction" not in recovery["annotations"]

        no_data = channel.build_alertmanager_payload(
            make_alert_data(
                is_no_data=True, value=None, confidence_lower=None, confidence_upper=None
            )
        )["alerts"][0]
        assert "direction" not in no_data["labels"]
        assert "direction" not in no_data["annotations"]

    def test_annotations_have_value_and_expected_for_anomaly_only(self):
        channel = self._channel()
        anomaly = channel.build_alertmanager_payload(make_alert_data())["alerts"][0]
        assert "value" in anomaly["annotations"]
        assert "expected" in anomaly["annotations"]

        no_data = channel.build_alertmanager_payload(
            make_alert_data(
                is_no_data=True, value=None, confidence_lower=None, confidence_upper=None
            )
        )["alerts"][0]
        assert "value" not in no_data["annotations"]
        assert "expected" not in no_data["annotations"]

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_send_posts_the_alertmanager_payload(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = self._channel()
        alert = make_alert_data()
        assert channel.send(alert) is True
        body = json.loads(mock_post.call_args.kwargs["data"])
        assert body == channel.build_alertmanager_payload(alert)

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_event_header_matches_status_kind(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        self._channel().send(make_alert_data(is_recovery=True))
        assert mock_post.call_args.kwargs["headers"]["X-Detectkit-Event"] == "recovery"


class TestHmacSigning:
    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_signature_header_matches_recomputed_hmac(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://x", secret="s3cret")
        channel.send(make_alert_data())

        body = mock_post.call_args.kwargs["data"]
        headers = mock_post.call_args.kwargs["headers"]
        expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        assert headers["X-Detectkit-Signature-256"] == expected

    @pytest.mark.parametrize("fmt", ["attachments", "json", "alertmanager"])
    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_signature_present_for_every_format(self, mock_post, fmt):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(webhook_url="https://x", format=fmt, secret="s3cret")
        channel.send(make_alert_data())
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["X-Detectkit-Signature-256"].startswith("sha256=")

    @patch("detectkit.alerting.channels.webhook.requests.post")
    def test_extra_header_cannot_clobber_the_signature(self, mock_post):
        mock_post.return_value = Mock(raise_for_status=Mock())
        channel = WebhookChannel(
            webhook_url="https://x",
            secret="s3cret",
            extra_headers={"X-Detectkit-Signature-256": "not-a-real-signature"},
        )
        channel.send(make_alert_data())
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["X-Detectkit-Signature-256"] != "not-a-real-signature"
        assert headers["X-Detectkit-Signature-256"].startswith("sha256=")
